"""Clearance case card (owner request, Nov 2026) — built ON the existing FASAH workspace, nothing replaced.

For one workspace case it shows: shipment type, port, goods, documents, every requirement as
مكتمل / ناقص / مشروط / يحتاج تحقق / غير مطلوب, the next step and who is responsible, the fee ledger, and a
cross-document check that binds every quantity / value / field to document + page + line and reports
conflicts between the invoice, the bill of lading and the packing list.

Everything here is LOCAL and deterministic: no model call, no external service, no FASAH action. A change of the
shipment data (fields such as the arrival port, the profile or documents) changes the case fingerprint, so any
saved AI analysis is shown as stale with a «أعد التحليل» step instead of being reused.
"""
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import fasah_workspace as ws
from app.fasah_checklist import PROFILE_OPTIONS, checklist, profile_of
from app.fasah_fields import DOCUMENT_TYPES, LABELS

router = APIRouter()

CARD_STATES = {'complete': 'مكتمل', 'missing': 'ناقص', 'conditional': 'مشروط', 'verify': 'يحتاج تحقق', 'not_required': 'غير مطلوب'}
ROLES = {'customer_service': 'خدمة العملاء (يطلبه من العميل)', 'clearance': 'موظف التخليص', 'broker': 'المخلص المرخّص',
         'accounts': 'الحسابات', 'manager': 'المدير'}
# Fields compared across invoice / bill of lading / packing list.
CROSS_FIELDS = ('invoice_number', 'bill_number', 'containers', 'packages', 'gross_weight', 'net_weight',
                'importer', 'supplier', 'origin', 'arrival_port', 'currency', 'invoice_total')
NUMERIC = {'packages', 'gross_weight', 'net_weight', 'invoice_total'}
CONTAINER = re.compile(r'\b([A-Z]{4})\s?(\d{7})\b')


# ---------- fingerprints / staleness ----------

def fields_fingerprint(case):
    from app.fasah_ai import fields_fingerprint as fp
    return fp(case)


def analysis_state(case):
    """('none'|'fresh'|'stale'|'unknown', reasons)."""
    from app import fasah_ai
    ai = (case.get('context') or {}).get('ai')
    if not ai:
        return 'none', ['لم يُشغَّل تحليل المستندات بعد.']
    reasons = []
    if not ai.get('source_fingerprint') or ai['source_fingerprint'] != fasah_ai.source_fingerprint(case):
        reasons.append('تغيّرت المستندات أو بيانات الشحنة (نوع المعاملة/الوسيلة/البضاعة) بعد التحليل.')
    if ai.get('fields_fingerprint') and ai['fields_fingerprint'] != fields_fingerprint(case):
        reasons.append('تغيّرت حقول الشحنة (مثل منفذ الوصول أو الأوزان) بعد التحليل.')
    if reasons:
        return 'stale', reasons
    if not ai.get('fields_fingerprint'):
        return 'unknown', ['التحليل أقدم من تتبع تغيّر الحقول؛ لا يُعرف إن تغيّر المنفذ أو الأوزان بعده.']
    return 'fresh', []


# ---------- evidence: document / page / line ----------

def _fold(text):
    text = unicodedata.normalize('NFKC', str(text or '')).casefold()
    return text.translate(str.maketrans('أإآىةؤئ٠١٢٣٤٥٦٧٨٩', 'اااياوي0123456789'))


def numbers(text):
    out = []
    t = str(text or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩٫٬', '0123456789.,'))
    for m in re.finditer(r'(?<![\w.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w,])|(?<![\w.,])\d+(?:\.\d+)?(?![\w,])', t):
        try:
            out.append(Decimal(m.group().replace(',', '')))
        except InvalidOperation:
            pass
    return out


def weight_kg(value):
    """Weight with its unit converted to kg; None when the unit is not explicit."""
    t = _fold(value)
    nums = numbers(t)
    if len(nums) != 1:
        return None
    if re.search(r'\b(?:kg|kgs|kilograms?)\b|كجم|كغ|كيلو', t):
        return nums[0]
    if re.search(r'\b(?:t|tons?|tonnes?|mt)\b|طن|اطنان', t):
        return nums[0] * 1000
    if re.search(r'\b(?:lbs?|pounds?)\b', t):
        return (nums[0] * Decimal('0.45359237')).quantize(Decimal('0.1'))
    return None


def comparable(key, value):
    if key == 'containers':
        found = {a + b for a, b in CONTAINER.findall(str(value or '').upper())}
        return frozenset(found) if found else None
    if key in ('gross_weight', 'net_weight'):
        kg = weight_kg(value)
        return ('kg', kg.normalize()) if kg is not None else None
    if key in NUMERIC:
        nums = numbers(value)
        return nums[0].normalize() if len(nums) == 1 else None
    folded = re.sub(r'[\s\-_/.,:#()]+', '', _fold(value))
    for word in ('company', 'co', 'ltd', 'limited', 'llc', 'شركه', 'مؤسسه', 'trading'):
        folded = folded.replace(word, '')
    return folded or None


def locate(case, needle, hint=''):
    """Every (document, page, line) where a value appears; lines containing the hint words come first."""
    target = comparable('x', needle) if not numbers(needle) else None
    wanted = numbers(needle)
    hint_words = {w for w in re.split(r'\W+', _fold(hint)) if len(w) >= 4}
    hits = []
    for doc in case.get('documents', []):
        for page in doc.get('pages') or []:
            for i, line in enumerate(str(page.get('text') or '').splitlines(), start=1):
                if wanted:
                    ok = len(wanted) == 1 and wanted[0] in numbers(line)
                else:
                    ok = bool(target) and target in re.sub(r'[\s\-_/.,:#()]+', '', _fold(line))
                if ok:
                    score = len(hint_words & set(re.split(r'\W+', _fold(line))))
                    hits.append({'document': doc.get('name'), 'document_id': doc.get('id'), 'kind': doc.get('kind'),
                                 'page': page.get('page'), 'line': i, 'text': line.strip()[:300], 'score': score})
    return sorted(hits, key=lambda h: -h['score'])


def line_of(doc, page_no, evidence):
    for page in doc.get('pages') or []:
        if page.get('page') != page_no:
            continue
        lines = str(page.get('text') or '').splitlines()
        head = str(evidence or '').split(' / ')[0].strip()
        for i, line in enumerate(lines, start=1):
            if head and line.strip() and (line.strip() == head or head in line):
                return i
    return None


def cross_check(case):
    """Per-field values from each document (with page/line), and conflicts between documents."""
    docs = {d.get('id'): d for d in case.get('documents', [])}
    by_name = {d.get('name'): d for d in case.get('documents', [])}
    fields, conflicts = {}, []
    for key in CROSS_FIELDS:
        field = (case.get('fields') or {}).get(key) or {}
        seen = []
        for cand in field.get('candidates') or []:
            doc = docs.get(cand.get('document_id')) or by_name.get(cand.get('source')) or {}
            seen.append({'value': cand.get('value'), 'document': cand.get('source') or doc.get('name'),
                         'kind': doc.get('kind'), 'page': cand.get('page'),
                         'line': line_of(doc, cand.get('page'), cand.get('evidence')) if doc else None,
                         'evidence': cand.get('evidence'), 'norm': comparable(key, cand.get('value'))})
        if not seen:
            continue
        fields[key] = seen
        known = [s for s in seen if s['norm'] is not None]
        if key in ('gross_weight', 'net_weight') and len(known) < len(seen):
            conflicts.append({'field': key, 'label': LABELS.get(key, key), 'type': 'unit',
                              'message': f"{LABELS.get(key, key)}: قيمة بدون وحدة واضحة لا يمكن مقارنتها؛ تحقق منها.",
                              'values': [s for s in seen if s['norm'] is None]})
        distinct = {}
        for s in known:
            distinct.setdefault(s['norm'], []).append(s)
        if key == 'containers' and len(distinct) > 1:
            union = frozenset().union(*distinct)
            missing = [(s, sorted(union - s['norm'])) for s in known if union - s['norm']]
            if missing:
                conflicts.append({'field': key, 'label': LABELS.get(key, key), 'type': 'mismatch',
                                  'message': 'أرقام الحاويات غير متطابقة بين المستندات: ' + '؛ '.join(
                                      f"{s['document']} لا يذكر {', '.join(m)}" for s, m in missing),
                                  'values': known})
        elif len(distinct) > 1:
            kinds = {s['kind'] for s in known}
            conflicts.append({'field': key, 'label': LABELS.get(key, key), 'type': 'mismatch',
                              'cross_document': len(kinds) > 1,
                              'message': f"{LABELS.get(key, key)} مختلف بين " + ('المستندات' if len(kinds) > 1 else 'صفحات/مواضع المستند') + ': ' +
                                         ' ≠ '.join(f"{v[0]['value']} ({v[0]['document']} ص{v[0]['page']}" + (f" س{v[0]['line']}" if v[0]['line'] else '') + ')'
                                                    for v in distinct.values()),
                              'values': known})
    # Item quantities / values from the saved analysis, bound to document + page + line.
    items = []
    ai = (case.get('context') or {}).get('ai') or {}
    for item in ai.get('items') or []:
        row = {'index': item.get('source_index'), 'description': item.get('description'), 'evidence': {}}
        for key in ('quantity', 'value'):
            if item.get(key) in (None, ''):
                continue
            hits = locate(case, str(item[key]), item.get('description', ''))
            best = [h for h in hits if h['score'] > 0] or hits
            row['evidence'][key] = {'value': item[key], 'status': ('linked' if len(best) >= 1 and best[0]['score'] > 0 and (len(best) == 1 or best[0]['score'] > best[1]['score'])
                                                                    else 'ambiguous' if hits else 'not_found'),
                                    'where': best[:3]}
        items.append(row)
    # Missing core documents for a comparison.
    present = {d.get('kind') for d in case.get('documents', [])}
    gaps = [DOCUMENT_TYPES[k] for k in ('invoice', 'transport', 'packing') if k not in present]
    return {'fields': fields, 'conflicts': conflicts, 'items': items, 'missing_for_comparison': gaps}


# ---------- the card ----------

def requirement_rows(case):
    data = checklist(case.get('documents', []), case.get('context') or {})
    rows = []
    for r in data['rows']:
        if r['state'] == 'complete':
            state, step, role = 'complete', '', ''
        elif r['state'] == 'not_required':
            state, step, role = 'not_required', '', ''
        elif r['state'] == 'missing':
            state, step, role = 'missing', f"اطلب {r['label']} من العميل.", 'customer_service'
        elif r['required'] is None:
            state, step, role = 'conditional', r['reason'], 'broker'
        else:
            state, step, role = 'verify', f"طابق {r['label']} مع الأصل وأكد تصنيفه وراجعه.", 'clearance'
        rows.append({'key': r['key'], 'label': r['label'], 'state': state, 'reason': r['reason'], 'source': r['source'],
                     'documents': [d.get('name') for d in r['documents']], 'next_step': step, 'role': role})
    return rows, data['blockers']


def build(case):
    from app import fee_ledger
    profile = profile_of(case.get('context') or {})
    fields = case.get('fields') or {}
    transaction = PROFILE_OPTIONS['transaction'][1].get(profile['transaction'], 'لم يحدد')
    mode = PROFILE_OPTIONS['mode'][1].get(profile['mode'], 'لم تحدد')
    rows, blockers = requirement_rows(case)
    analysis, analysis_reasons = analysis_state(case)
    check = cross_check(case)
    fees = fee_ledger.summary(case['id']) if case.get('id') is not None else None
    steps = []
    if analysis in ('stale', 'none'):
        steps.append((('أعد تحليل المستندات' if analysis == 'stale' else 'شغّل تحليل المستندات') + ': ' + ' '.join(analysis_reasons), 'clearance'))
    for c in check['conflicts']:
        steps.append(('احسم التعارض: ' + c['message'], 'clearance'))
    for b in blockers:
        steps.append((b, 'clearance'))
    for r in rows:
        if r['next_step']:
            steps.append((r['next_step'], r['role']))
    for item in check['items']:
        for key, ev in item['evidence'].items():
            if ev['status'] != 'linked':
                steps.append((f"تحقق من {'كمية' if key == 'quantity' else 'قيمة'} البند {item['index'] + 1 if isinstance(item['index'], int) else ''} ({ev['value']}): "
                             + ('ظهر في أكثر من موضع' if ev['status'] == 'ambiguous' else 'غير موجود في نص المستندات'), 'clearance'))
    if fees and fees['unresolved']:
        steps.append((f"أكّد {len(fees['unresolved'])} بند رسوم (المبلغ/الضريبة/المصدر).", 'accounts'))
    assigned = (case.get('context') or {}).get('card') or {}
    counts = {k: sum(r['state'] == k for r in rows) for k in CARD_STATES}
    overall = ('ناقص' if counts['missing'] else 'فيه تعارض' if check['conflicts'] else
               'يحتاج تحقق' if counts['verify'] or counts['conditional'] or blockers or analysis != 'fresh' else 'جاهز للمراجعة النهائية')
    return {'id': case.get('id'), 'title': case.get('title'), 'shipment_type': f'{transaction} — {mode}',
            'port': (fields.get('arrival_port') or {}).get('value') or 'غير محدد',
            'goods': profile.get('goods') or (fields.get('description') or {}).get('value') or 'غير محدد',
            'dispatch_country': profile.get('dispatch_country') or 'غير محدد',
            'documents': [{'name': d.get('name'), 'kind': DOCUMENT_TYPES.get(d.get('kind'), d.get('kind')), 'pages': len(d.get('pages') or []),
                           'reviewed': bool(d.get('reviewed'))} for d in case.get('documents', [])],
            'requirements': rows, 'counts': counts, 'blockers': blockers, 'analysis': analysis,
            'analysis_reasons': analysis_reasons, 'cross_check': check, 'fees': fees, 'steps': steps,
            'next_step': steps[0][0] if steps else 'راجع المعاملة كاملة في فسح؛ الاعتماد والإرسال للموظف المخوّل.',
            'next_role': ROLES.get(steps[0][1] if steps else 'broker', 'المخلص المرخّص'),
            'owner': assigned.get('owner') or '', 'due': assigned.get('due') or '', 'overall': overall}


# ---------- page ----------

def _esc(v):
    from app.main import esc
    return esc(v)


def render_card(case, session, message=''):
    card = build(case)
    hidden = ws.token(session) + f'<input type="hidden" name="revision" value="{case["revision"]}">'
    color = {'complete': 'good', 'missing': 'bad', 'conditional': 'warn', 'verify': 'warn', 'not_required': 'muted'}
    req = ''.join(f"<tr><td>{_esc(r['label'])}</td><td class='{color[r['state']]}'><b>{CARD_STATES[r['state']]}</b></td>"
                  f"<td>{_esc('، '.join(r['documents']) or '—')}</td><td>{_esc(r['next_step'] or r['reason'])}</td>"
                  f"<td>{_esc(ROLES.get(r['role'], '—'))}</td></tr>" for r in card['requirements'])
    conf = ''.join(f"<li class='bad'>{_esc(c['message'])}</li>" for c in card['cross_check']['conflicts']) or '<li class="good">لا تعارض في الحقول المقروءة بين المستندات.</li>'
    gaps = card['cross_check']['missing_for_comparison']
    items = ''
    for it in card['cross_check']['items']:
        for key, ev in it['evidence'].items():
            where = '؛ '.join(f"{w['document']} ص{w['page']} س{w['line']}" for w in ev['where']) or '—'
            label = {'linked': 'مرتبط بسطر', 'ambiguous': 'أكثر من موضع — يحتاج تحقق', 'not_found': 'غير موجود — يحتاج تحقق'}[ev['status']]
            items += f"<tr><td>{_esc(it['description'])}</td><td>{'الكمية' if key == 'quantity' else 'القيمة'}</td><td>{_esc(ev['value'])}</td><td>{label}</td><td>{_esc(where)}</td></tr>"
    fields_html = ''
    for key, seen in card['cross_check']['fields'].items():
        fields_html += f"<tr><td>{_esc(LABELS.get(key, key))}</td><td>" + '<br>'.join(
            _esc(f"{s['value']} — {s['document']} ص{s['page']}" + (f" س{s['line']}" if s['line'] else '')) for s in seen) + '</td></tr>'
    from app import fee_ledger
    fee_text = fee_ledger.text(case['id'])
    options = lambda d: ''.join(f'<option value="{k}">{v}</option>' for k, v in d.items())
    steps = ''.join(f"<li>{_esc(s)} <small>— {_esc(ROLES.get(r, r))}</small></li>" for s, r in card['steps'][:15])
    analysis_label = {'fresh': 'محدّث', 'stale': 'قديم — أعد التحليل', 'none': 'لم يُشغَّل', 'unknown': 'يحتاج تحقق'}[card['analysis']]
    body = ws.intro() + f'''<div class="nav"><a href="/fasah-workspace/{case["id"]}">المعاملة</a><a href="/fasah-workspace/{case["id"]}/assistant">مساعد المخلص</a></div>
    <h2>بطاقة المعاملة: {_esc(card['title'])}</h2>{'<p class="warn">' + _esc(message) + '</p>' if message else ''}
    <div class="grid"><div class="kpi">الحالة<b>{_esc(card['overall'])}</b></div><div class="kpi">نوع الشحنة<b>{_esc(card['shipment_type'])}</b></div>
    <div class="kpi">المنفذ<b>{_esc(card['port'])}</b></div><div class="kpi">السلعة<b>{_esc(card['goods'])}</b></div>
    <div class="kpi">ناقص<b>{card['counts']['missing']}</b></div><div class="kpi">مشروط<b>{card['counts']['conditional']}</b></div>
    <div class="kpi">يحتاج تحقق<b>{card['counts']['verify']}</b></div><div class="kpi">تحليل المستندات<b>{analysis_label}</b></div></div>
    <div class="card"><h2>الخطوة التالية</h2><p><b>{_esc(card['next_step'])}</b></p><p>المسؤول: {_esc(card['owner'] or card['next_role'])}{(' · الموعد: ' + _esc(card['due'])) if card['due'] else ''}</p>
    <ol>{steps}</ol>
    <form method="post" action="/fasah-workspace/{case["id"]}/card/owner">{hidden}<label>الموظف المسؤول<input name="owner" maxlength="80" value="{_esc(card['owner'])}"></label>
    <label>موعد الخطوة التالية<input name="due" type="date" value="{_esc(card['due'])}"></label><button class="btn">حفظ</button></form></div>
    <div class="card"><h2>المتطلبات</h2><div class="scroll"><table><tr><th>المتطلب</th><th>الحالة</th><th>المستندات</th><th>الخطوة/السبب</th><th>المسؤول</th></tr>{req}</table></div>
    <p class="muted">«مشروط» = يعتمد انطباقه على بيانات الشحنة ويحسمه المخلص. «يحتاج تحقق» = المستند موجود ولم تكتمل مطابقته.</p></div>
    <div class="card"><h2>مطابقة المستندات (الفاتورة / البوليصة / قائمة التعبئة)</h2><ul>{conf}</ul>
    {('<p class="warn">لا يمكن المقارنة الكاملة دون: ' + _esc('، '.join(gaps)) + '</p>') if gaps else ''}
    <details><summary>قيم كل حقل ومصدرها (مستند/صفحة/سطر)</summary><table>{fields_html or '<tr><td>لا قيم مقروءة</td></tr>'}</table></details>
    <h3>كميات وقيم البنود من التحليل</h3><div class="scroll"><table><tr><th>البند</th><th>الحقل</th><th>القيمة</th><th>الإثبات</th><th>الموضع</th></tr>{items or '<tr><td colspan=5>لا توجد بنود محللة.</td></tr>'}</table></div>
    <p class="muted">المطابقة محلية على النص المستخرج؛ أي سطر OCR يلزم مطابقته مع الأصل.</p></div>
    <div class="card"><h2>سجل الرسوم</h2><pre dir="auto">{_esc(fee_text)}</pre>
    <form method="post" action="/fasah-workspace/{case["id"]}/card/fees">{hidden}<label>الجهة<select name="category" required>{options(fee_ledger.CATEGORIES)}</select></label>
    <label>الوصف<input name="description" maxlength="200" required></label><label>المبلغ (فارغ إن لم يُعرف)<input name="amount" maxlength="20" inputmode="decimal"></label>
    <label>العملة<select name="currency">{''.join(f'<option>{c}</option>' for c in sorted(fee_ledger.CURRENCIES, key=lambda x: x != 'SAR'))}</select></label>
    <label>الضريبة<select name="vat">{options(fee_ledger.VAT)}</select></label><label>نسبة الضريبة %<input name="vat_rate" maxlength="6"></label>
    <label>المصدر<select name="source_kind">{options(fee_ledger.SOURCES)}</select></label><label>مرجع المصدر (رقم فاتورة/سداد/عرض)<input name="source_ref" maxlength="160"></label>
    <label>يشمل<input name="includes" maxlength="300"></label><label>ضمن بند رقم (إن كان مشمولًا في بند آخر)<input name="included_in" maxlength="12"></label>
    <label>الحالة<select name="status">{options(fee_ledger.STATUS)}</select></label><button class="btn">إضافة البند</button></form>
    <p class="muted">لا يُعرض إجمالي نهائي إلا إذا كانت كل البنود مؤكدة بمصدرها وضريبتها وبعملة واحدة.</p></div>
    <style>.good{{color:#7ee2a8}}.bad{{color:#ff9a9a}}.warn{{color:#ffd978}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid var(--line);padding:8px;vertical-align:top}}</style>'''
    return ws.render('بطاقة المعاملة', body)


@router.get('/fasah-workspace/{case_id}/card', response_class=HTMLResponse)
def card_page(case_id: int, request: Request):
    session = ws.authorized(request)
    return render_card(ws.get_draft(case_id, session), session)


@router.get('/api/v7/clearance-card/{case_id}')
def card_api(case_id: int, request: Request):
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse
    session = ws.authorized(request)
    data = build(ws.get_draft(case_id, session))
    for f in data['cross_check']['fields'].values():
        for s in f:
            s['norm'] = str(s['norm']) if s['norm'] is not None else None
    for c in data['cross_check']['conflicts']:
        for s in c.get('values', []):
            s['norm'] = str(s['norm']) if s.get('norm') is not None else None
    return JSONResponse(jsonable_encoder(data), headers={'Cache-Control': 'no-store'})


@router.post('/fasah-workspace/{case_id}/card/owner')
async def save_owner(case_id: int, request: Request):
    session = ws.authorized(request)
    case = ws.get_draft(case_id, session)
    form = await ws.small_form(request, session)
    owner = re.sub(r'\s+', ' ', str(form.get('owner') or '')).strip()[:80]
    due = str(form.get('due') or '').strip()
    if due and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', due):
        raise HTTPException(422, 'صيغة التاريخ غير صالحة.')
    case['context']['card'] = {'owner': owner, 'due': due}
    # The fee/owner card data never changes documents, fields or the analysis fingerprint.
    ws.persist(case, session, form.get('revision'), 'clearance_card_owner_saved')
    return RedirectResponse(f'/fasah-workspace/{case_id}/card', 303)


@router.post('/fasah-workspace/{case_id}/card/fees')
async def add_fee(case_id: int, request: Request):
    from app import fee_ledger
    session = ws.authorized(request)
    case = ws.get_draft(case_id, session)
    form = await ws.small_form(request, session)
    try:
        for key in ('description', 'source_ref', 'includes'):
            ws.validate_text(str(form.get(key) or ''), 300)
        fee_ledger.add(case_id, {k: form.get(k) for k in ('category', 'description', 'amount', 'currency', 'vat', 'vat_rate',
                                                           'source_kind', 'source_ref', 'includes', 'included_in', 'status')},
                       str(session.get('user_id')))
    except ValueError as error:
        return render_card(case, session, str(error))
    return RedirectResponse(f'/fasah-workspace/{case_id}/card', 303)


def install():
    """Add the card link to the existing case page without changing it."""
    from app import fasah_workspace_view as view
    original = view.document_panel
    if getattr(original, '_card_link', False):
        return

    def document_panel(case, hidden, esc):
        link = (f'<div class="card"><a class="btn" href="/fasah-workspace/{case["id"]}/card">🗂️ بطاقة المعاملة: '
                'المتطلبات والتعارضات والرسوم والخطوة التالية</a></div>')
        return link + original(case, hidden, esc)
    document_panel._card_link = True
    view.document_panel = document_panel
