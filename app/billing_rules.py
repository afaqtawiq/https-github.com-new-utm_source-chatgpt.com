"""Owner-approved billing rules: one customs declaration -> draft claims/payables in finance.

Rules (approved by the owner, Nov 2026):
- Import, invoice issued by الياسمين (supplier name contains Yasmen/ياسمين, or invoice number starts AB):
  claim on الياسمين = full FASAH fees (duty + other) + clearance 300 + Saber 1,450 + registry 700
  + VAT 15% + zakat 2.5% of the invoice value as written (no currency conversion; goods value not added).
- Import, any other invoice: claim on عمران = registry 800 + VAT 15% of the invoice value. عمران pays
  customs fees, clearance, Saber and zakat himself.
- Importer سلة الرحائب, import: (registry 600 + VAT 15% of the invoice value) per declaration; the total is
  split 50/50 between وكيل آفاق طويق and سلة الرحائب -> payable to سلة الرحائب = half.
- Exporter سلة الرحائب, export/re-export: payable to سلة الرحائب = net 100 per declaration.

Every document is created as a finance DRAFT; the owner reviews and posts it in /finance. Each declaration is
recorded once (unique by number and type).
"""
import datetime as dt
import json
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.storage import db, log, utcnow

router = APIRouter()
YASMEN, OMRAN, SALLA = 'الياسمين', 'عمران', 'سلة الرحائب'
CENT = Decimal('0.01')


def money(value):
    try:
        out = Decimal(str(value if value is not None else '').replace(',', '').replace('٬', '').strip() or '0')
    except InvalidOperation:
        raise ValueError('مبلغ غير صالح: ' + str(value)) from None
    if out < 0:
        raise ValueError('المبلغ لا يكون سالبًا')
    return out.quantize(CENT, ROUND_HALF_UP)


def fold(text):
    text = re.sub(r'[ً-ٰٟـ]', '', str(text or '')).lower()
    return text.translate(str.maketrans('أإآىئ', 'ااايي'))


def is_yasmen(supplier, invoice_no):
    s = fold(supplier)
    if re.search(r'(غير|ليس|مش|not|other)', s):
        return False
    if 'ياسمين' in s or 'yasmen' in s or 'yasmin' in s:
        return True
    return not s.strip() and str(invoice_no or '').strip().upper().startswith('AB')


def is_salla(name):
    return 'سله الرحايب' in fold(name).replace('ة', 'ه') or 'salla' in fold(name)


def compute(d):
    """Pure calculation. d: number, kind('import'|'export'), party (importer/exporter), invoice_no,
    invoice_value, supplier, duty, other. Returns list of {'party','kind','amount','components','label'}."""
    kind = d.get('kind') or 'import'
    out = []
    if kind == 'export':
        if is_salla(d.get('party')):
            out.append({'party': SALLA, 'kind': 'payable', 'amount': Decimal('100.00'), 'components': {},
                        'label': 'نصيب سلة الرحائب عن بيان تصدير'})
        return out
    value = money(d.get('invoice_value'))
    if value <= 0:
        raise ValueError('قيمة الفاتورة مطلوبة')
    tax = (value * Decimal('0.15')).quantize(CENT, ROUND_HALF_UP)
    if is_yasmen(d.get('supplier'), d.get('invoice_no')):
        comp = {'customs_duty': money(d.get('duty')), 'customs_other': money(d.get('other')), 'clearance': Decimal('300.00'),
                'saber': Decimal('1450.00'), 'registry': Decimal('700.00'), 'tax': tax,
                'zakat': (value * Decimal('0.025')).quantize(CENT, ROUND_HALF_UP)}
        out.append({'party': YASMEN, 'kind': 'claim', 'amount': sum(comp.values()), 'components': comp,
                    'label': 'مطالبة الياسمين'})
    else:
        comp = {'customs_duty': Decimal('0'), 'customs_other': Decimal('0'), 'clearance': Decimal('0'), 'saber': Decimal('0'),
                'registry': Decimal('800.00'), 'tax': tax, 'zakat': Decimal('0')}
        out.append({'party': OMRAN, 'kind': 'claim', 'amount': sum(comp.values()), 'components': comp,
                    'label': 'مطالبة عمران'})
    if is_salla(d.get('party')):
        half = ((Decimal('600.00') + tax) / 2).quantize(CENT, ROUND_HALF_UP)
        out.append({'party': SALLA, 'kind': 'payable', 'amount': half, 'components': {},
                    'label': 'نصيب سلة الرحائب 50% من (سجل 600 + ضريبة 15%)'})
    return out


def summary(d, items):
    lines = ['بيان ' + str(d['number']) + (' (تصدير)' if d.get('kind') == 'export' else '')]
    for it in items:
        lines.append('• ' + it['label'] + ': ' + format(it['amount'], ',.2f') + ' ريال')
    return '\n'.join(lines)


# ---------- persistence ----------

def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS billing_declarations(
            id BIGSERIAL PRIMARY KEY, number TEXT NOT NULL, kind TEXT NOT NULL, party TEXT NOT NULL DEFAULT '',
            invoice_no TEXT NOT NULL DEFAULT '', invoice_value TEXT NOT NULL DEFAULT '', supplier TEXT NOT NULL DEFAULT '',
            duty TEXT NOT NULL DEFAULT '0', other TEXT NOT NULL DEFAULT '0', decl_date DATE,
            items_json TEXT NOT NULL, finance_ids TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL,
            error TEXT, created_by BIGINT, created_at TIMESTAMPTZ NOT NULL, UNIQUE(number, kind))''')


def party_id(c, name, actor):
    from app import finance_service as service
    # Prefer the existing party whose name contains the rule name (e.g. «عمران (إقبال)»), oldest first,
    # so claims join the customer's real statement instead of a new duplicate party.
    row = c.execute("""SELECT id FROM finance_party_display WHERE kind='counterparty' AND confirmed
        AND (name=%s OR name LIKE %s) ORDER BY id LIMIT 1""", (name, name + '%')).fetchone()
    if row:
        return row['id']
    return service.create_party({'name': name, 'identity_ref': 'billing:' + name, 'kind': 'counterparty', 'confirmed': '1'}, actor)


def owner_id(c):
    row = c.execute("SELECT id FROM finance_party_display WHERE kind='owner' AND confirmed ORDER BY id LIMIT 1").fetchone()
    if not row:
        raise ValueError('لا يوجد صاحب حساب مؤكد في المالية')
    return row['id']


def create_documents(d, items, actor):
    from app import finance_service as service
    ids = []
    with db() as c:
        owner = owner_id(c)
        parties = {it['party']: party_id(c, it['party'], actor) for it in items}
    date = (d.get('date') or dt.date.today()).isoformat()
    for it in items:
        ref = 'بيان ' + str(d['number']) + (' / فاتورة ' + d['invoice_no'] if d.get('invoice_no') else '')
        detail = ' + '.join(k + ' ' + format(v, 'f') for k, v in it['components'].items() if v) or it['label']
        form = {'kind': it['kind'], 'currency': 'SAR', 'amount': format(it['amount'], 'f'), 'document_date': date,
                'amount_basis': 'gross', 'source_role': 'detail', 'source_verification': 'recorded',
                'owner_id': str(owner), 'counterparty_id': str(parties[it['party']]),
                'source_ref': it['label'] + ': ' + ref, 'source_locator': 'منصة فسح — بيان ' + str(d['number']),
                'economic_ref': ('EXPORT' if d.get('kind') == 'export' else 'IMPORT') + ':' + str(d['number']) + ':' + it['kind'].upper() + ':SAR',
                'source_amount_raw': format(it['amount'], 'f') + ' SAR = ' + detail,
                'invoice_ref': d.get('invoice_no') or '', 'customs_ref': str(d['number']),
                'notes': 'قيد تلقائي وفق قواعد الفوترة المعتمدة من صاحب الحساب. ' + it['label'] + '. قيمة الفاتورة ' +
                         str(d.get('invoice_value') or '-') + ' كما هي دون تحويل عملة. مسودة بانتظار المراجعة والترحيل.',
                'idempotency_key': str(uuid.uuid5(uuid.NAMESPACE_URL, 'billing:' + str(d.get('row_id')) + ':' + str(d['number']) + ':' +
                                                  str(d.get('kind')) + ':' + it['party'] + ':' + str(parties[it['party']])))}
        doc_id = service.create_document(form, actor)
        ids.append(doc_id)
        if it['kind'] == 'claim':
            details = {k: format(v, 'f') if v else '0' for k, v in it['components'].items()}
            details.update({'goods_amount': format(money(d['invoice_value']), 'f'), 'goods_currency': 'AED', 'exchange_rate': '1',
                            'source_ref': ref, 'reason': 'تفصيل تلقائي وفق القواعد المعتمدة', 'confirmation': '1',
                            'expected_revision': '0',
                            'idempotency_key': str(uuid.uuid5(uuid.NAMESPACE_URL, 'billing-detail:' + str(doc_id)))})
            try:
                service.attach_claim_details(doc_id, actor, details)
            except Exception as exc:  # detail is presentation only; the draft stays valid
                print('BILLING_DETAIL_SKIPPED', doc_id, str(exc)[:160], flush=True)
    return ids


def record(d, actor):
    """Record one declaration once and create its finance drafts. Returns (items, finance_ids, message)."""
    init()
    d = dict(d)
    d['number'] = re.sub(r'\D', '', str(d.get('number') or ''))
    if not d['number']:
        raise ValueError('رقم البيان مطلوب')
    if not str(d.get('party') or '').strip():
        d['party'] = SALLA  # the approved rules are for سلة الرحائب shipments unless another importer is named
    d['kind'] = 'export' if str(d.get('kind') or '').strip().lower() in ('export', 'تصدير', 'صادر', 'إعادة تصدير', 'اعادة تصدير') else 'import'
    items = compute(d)
    if not items:
        return [], [], 'لا توجد قاعدة فوترة تنطبق على هذا البيان.'
    with db() as c:
        claimed = c.execute('''INSERT INTO billing_declarations(number,kind,party,invoice_no,invoice_value,supplier,duty,other,decl_date,
            items_json,status,created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'recording',%s,%s)
            ON CONFLICT(number,kind) DO NOTHING RETURNING id''',
            (d['number'], d['kind'], str(d.get('party') or ''), str(d.get('invoice_no') or ''), str(d.get('invoice_value') or ''),
             str(d.get('supplier') or ''), str(d.get('duty') or '0'), str(d.get('other') or '0'), d.get('date'),
             json.dumps([{**i, 'amount': str(i['amount']), 'components': {k: str(v) for k, v in i['components'].items()}} for i in items], ensure_ascii=False),
             actor, utcnow())).fetchone()
    if not claimed:
        return items, [], 'هذا البيان مسجل مسبقًا في الحسابات؛ لم يتكرر القيد.'
    try:
        ids = create_documents({**d, 'row_id': claimed['id']}, items, actor)
        status, error = 'drafted', None
    except Exception as exc:
        ids, status, error = [], 'failed', str(getattr(exc, 'detail', exc))[:300]
    with db() as c:
        c.execute('UPDATE billing_declarations SET finance_ids=%s,status=%s,error=%s WHERE id=%s',
                  (json.dumps(ids), status, error, claimed['id']))
    log(actor, 'billing_declaration_recorded', 'billing_declaration', claimed['id'], d['number'] + ' ' + status)
    if error:
        return items, ids, 'تعذر إنشاء القيود: ' + error
    return items, ids, summary(d, items) + '\nسُجّلت مسودات في المالية بانتظار مراجعتك وترحيلها.'


# ---------- page ----------

def admin_session(request):
    from app.social_publishing import admin
    return admin(request)


@router.get('/billing', response_class=HTMLResponse)
def page(request: Request):
    from app.social_content import e, page as layout
    admin_session(request)
    init()
    with db() as c:
        rows = c.execute('SELECT * FROM billing_declarations ORDER BY id DESC LIMIT 200').fetchall()
    body = '<div class="nav"><a href="/finance">المحاسبة والمالية</a><a href="/declarations">متابعة البيانات</a></div>'
    body += ('<div class="hero"><h1>فوترة البيانات الجمركية</h1><p class="muted">أدخل رقم البيان وقيمة الفاتورة والجهة المصدّرة، '
             'فيحسب الوكيل المطالبات وفق القواعد المعتمدة (الياسمين، عمران، سلة الرحائب) ويسجلها مسودات في المالية.</p></div>')
    body += ('<div class="card"><form method="post" action="/billing"><div class="formgrid">'
             '<input name="number" placeholder="رقم البيان" required><select name="kind"><option value="import">استيراد</option><option value="export">تصدير / إعادة تصدير</option></select>'
             '<input name="party" placeholder="المستورد/المصدّر (مثال: سلة الرحائب)"><input name="invoice_no" placeholder="رقم الفاتورة">'
             '<input name="invoice_value" placeholder="قيمة الفاتورة"><select name="supplier"><option value="">الجهة المصدِّرة للفاتورة…</option><option value="الياسمين">الياسمين</option><option value="جهة أخرى (عمران)">جهة أخرى (عمران)</option></select>'
             '<input name="duty" placeholder="رسوم جمركية من فسح (لفواتير الياسمين)"><input name="other" placeholder="رسوم أخرى من فسح">'
             '<input name="date" type="date"></div><button class="btn">احسب وسجّل مسودات</button></form></div>')
    body += '<div class="card scroll"><table><tr><th>البيان</th><th>النوع</th><th>الجهة</th><th>الفاتورة</th><th>القيود</th><th>الحالة</th></tr>'
    for r in rows:
        items = json.loads(r['items_json'] or '[]')
        cells = '<br>'.join(e(i['label']) + ': ' + e(i['amount']) for i in items)
        links = ' '.join('<a href="/finance/documents/' + str(x) + '">#' + str(x) + '</a>' for x in json.loads(r['finance_ids'] or '[]'))
        body += ('<tr><td>' + e(r['number']) + '</td><td>' + ('تصدير' if r['kind'] == 'export' else 'استيراد') + '</td><td>' + e(r['party']) +
                 '</td><td>' + e(r['invoice_no']) + ' · ' + e(r['invoice_value']) + '</td><td>' + cells + '<br>' + links +
                 '</td><td><span class="pill">' + e(r['status']) + '</span> ' + e(r['error'] or '') +
                 '<form method="post" action="/billing/' + str(r['id']) + '/void"><button class="btn danger">إلغاء المسودات لإعادة التسجيل</button></form></td></tr>')
    body += '</table></div>'
    return HTMLResponse(layout(body), headers={'Cache-Control': 'no-store'})


@router.post('/billing')
async def submit(request: Request):
    from app.social_content import e, page as layout, parse
    session = admin_session(request)
    data = parse(await request.body())
    try:
        date = dt.date.fromisoformat(data['date']) if data.get('date') else None
        _, _, message = record({**data, 'date': date}, session['user_id'])
    except ValueError as exc:
        message = str(exc)
    return HTMLResponse(layout('<div class="card"><pre style="white-space:pre-wrap">' + e(message) +
                               '</pre><a class="btn" href="/billing">رجوع</a> <a class="btn" href="/finance">المالية</a></div>'))


def void(row_id, actor):
    """Void this declaration's finance drafts (posted ones need a reversal in /finance) and free it for re-entry."""
    from app import finance_service as service
    with db() as c:
        row = c.execute('SELECT * FROM billing_declarations WHERE id=%s', (row_id,)).fetchone()
    if not row:
        raise ValueError('السجل غير موجود')
    for doc_id in json.loads(row['finance_ids'] or '[]'):
        service.void_document(doc_id, actor, {'reason': 'إلغاء مسودة فوترة البيان ' + row['number'] + ' لإعادة التسجيل بالبيانات الصحيحة'})
    with db() as c:
        c.execute('DELETE FROM billing_declarations WHERE id=%s', (row_id,))
    log(actor, 'billing_declaration_voided', 'billing_declaration', row_id, row['number'])


@router.post('/billing/{row_id}/void')
async def void_route(row_id: int, request: Request):
    session = admin_session(request)
    try:
        void(row_id, session['user_id'])
    except Exception as exc:
        raise HTTPException(409, str(getattr(exc, 'detail', exc))[:200]) from None
    return RedirectResponse('/billing', 303)


@router.get('/billing/statement', response_class=HTMLResponse)
def statement_page(request: Request, party: str = '', month: str = ''):
    import html as _h
    admin_session(request)
    from app import statement_import
    if not re.fullmatch(r'\d{4}-\d{2}', month or ''):
        return HTMLResponse('اذكر الشهر بصيغة 2026-10', status_code=400)
    s = statement_import.statement(party, month)
    e = lambda v: _h.escape(str(v if v is not None else ''))
    rows = ''.join(f"<tr><td>{i + 1}</td><td>{e(l['number'])}</td><td>{e(l['date'])}</td><td>{e(l['invoice'])}</td>"
                   f"<td>{e(l['registry'])}</td><td>{e(l['tax'])}</td><td>{l['amount']:,.2f}</td></tr>" for i, l in enumerate(s['lines']))
    pays = ''.join(f"<tr><td>{e(p['pay_date'])}</td><td>{float(p['amount']):,.2f}</td><td>{e(p['ref'])}</td></tr>" for p in s['payments'])
    body = (f"<h1>كشف حساب {e(s['party'])} — {e(month)}</h1><p>مؤسسة آفاق طويق للتخليص الجمركي — ترخيص 2513</p>"
            '<table border=1 cellpadding=6 style="border-collapse:collapse;width:100%"><tr><th>#</th><th>رقم البيان</th><th>التاريخ</th>'
            '<th>قيمة الفاتورة</th><th>السجل التجاري</th><th>الضريبة 15%</th><th>المطالبة</th></tr>' + rows +
            f"<tr><th colspan=6>الإجمالي</th><th>{s['total']:,.2f}</th></tr></table>"
            '<h2>السداد خلال الشهر</h2><table border=1 cellpadding=6 style="border-collapse:collapse;width:100%"><tr><th>التاريخ</th><th>المبلغ</th><th>المرجع</th></tr>'
            + pays + f"<tr><th>الإجمالي</th><th>{s['paid']:,.2f}</th><th></th></tr></table>"
            f"<h2>الصافي المستحق عن الشهر: {s['total'] - s['paid']:,.2f} ريال</h2>"
            '<p style="color:#777">من القيود المسجلة قبل الترحيل.</p>')
    return HTMLResponse('<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><title>كشف حساب</title>'
                        '<body style="font-family:Arial;padding:24px">' + body + '</body></html>')
