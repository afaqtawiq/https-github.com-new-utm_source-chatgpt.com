"""Broker assistant inside the FASAH workspace (Safe Assisted Mode).

For one workspace case it:
* reads the case documents (the text the workspace already extracted) with Claude and returns the
  declaration header data and every invoice line (description, quantity, value, origin);
* suggests the tariff line for each item from the GCC 12-digit tariff table (gcc_tariff) with its
  duty, plus the general requirement (SABER, SFDA, other permit) from the customs knowledge;
* prepares everything for the broker to copy into FASAH, or for Claude in Chrome to type into the
  FASAH page the broker opened and logged into himself.
It never logs into FASAH, stores credentials, reads the FASAH window, or submits anything.
All suggestions are preliminary; the licensed broker reviews and decides.
"""
import html
import json
import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import fasah_workspace as ws
from app import fasah_workspace_view as view
from app import tariff_lookup
from app.customs_knowledge import KNOWLEDGE
from app.fasah_fields import FASAH_URL, LABELS
from app.storage import utcnow

router = APIRouter()
MODEL = os.getenv('FASAH_AI_MODEL', 'claude-sonnet-5')
HEADER_KEYS = ['importer', 'registration', 'supplier', 'invoice_number', 'invoice_date', 'invoice_total', 'currency',
               'incoterm', 'bill_number', 'containers', 'arrival_port', 'packages', 'gross_weight', 'net_weight',
               'origin', 'description']
CHROME_HELP = 'https://support.claude.com/en/articles/12012173-get-started-with-claude-in-chrome'

EXTRACT = """You read shipping documents for a Saudi customs declaration. The text comes from OCR and may be noisy,
in Arabic, English or Chinese. Extract ONLY values that are written in the documents; never guess or compute.
Return ONLY JSON:
{"fields": {"<key>": {"value": str, "source": "<document name>"} | null, ...},
 "items": [{"description": str, "quantity": str|null, "unit": str|null, "value": str|null, "origin": str|null,
            "search_ar": [str], "search_en": [str]}],
 "issues": [str]}
Field keys: importer, registration, supplier, invoice_number, invoice_date, invoice_total, currency, incoterm,
bill_number, containers, arrival_port, packages, gross_weight, net_weight, origin, description.
items = each invoice line (max 30). search_ar/search_en: up to 3 short phrasings of the goods in customs tariff wording.
issues = mismatches between documents (importer, supplier, invoice number, B/L, weights, packages, origin), missing
documents or unreadable parts, written in Arabic."""

CLASSIFY = """You help a Saudi customs broker. For each item choose the most likely tariff line ONLY from its candidates
(or null if none fits), and state the general requirement for that goods type ONLY from the knowledge
(SABER product/shipment certificates, SFDA registration, other permit, or none). Arabic, short.
Return ONLY JSON: {"items": [{"index": int, "code": str|null, "alternatives": [str], "requirement": str, "note": str}]}
Codes must be copied exactly from the candidates. Never invent codes or rates."""


def ask(system, payload, max_tokens=4000):
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key:
        raise ValueError('التحليل غير مفعّل: يلزم مفتاح Claude على الخادم.')
    body = {'model': MODEL, 'max_tokens': max_tokens, 'thinking': {'type': 'disabled'}, 'system': system,
            'messages': [{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
    with httpx.Client(timeout=90) as client:
        response = client.post('https://api.anthropic.com/v1/messages', json=body,
                               headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
        response.raise_for_status()
    text = ''.join(p.get('text', '') for p in response.json().get('content', []) if p.get('type') == 'text')
    match = re.search(r'\{.*\}', text, re.S)
    if not match:
        raise ValueError('لم يرجع التحليل بيانات منظمة؛ أعد المحاولة.')
    return json.loads(match.group(0))


def document_text(case, limit=60000):
    parts, used = [], 0
    for doc in case['documents']:
        pages = doc.get('pages') or []
        text = '\n'.join(p if isinstance(p, str) else str(p.get('text', '')) for p in pages)
        text = text[:max(0, limit - used)]
        used += len(text)
        parts.append({'document': doc.get('name'), 'type': doc.get('kind'), 'text': text})
    return parts


def analyze(case):
    docs = document_text(case)
    if not any(d['text'].strip() for d in docs):
        raise ValueError('لا يوجد نص مستخرج من المستندات. ارفع الفاتورة والبوليصة وقائمة التعبئة أولًا.')
    extracted = ask(EXTRACT, {'documents': docs})
    items = [i for i in (extracted.get('items') or []) if isinstance(i, dict) and i.get('description')][:30]
    candidates = []
    for index, item in enumerate(items):
        found = tariff_lookup.search_many(item.get('search_ar'), item.get('search_en'), limit=6)
        candidates.append({'index': index, 'description': item.get('description'),
                           'candidates': tariff_lookup.as_prompt(found)})
    choices = {}
    if items:
        result = ask(CLASSIFY + '\n\nKnowledge (Arabic):\n' + KNOWLEDGE, {'items': candidates}, max_tokens=4000)
        choices = {c.get('index'): c for c in result.get('items') or [] if isinstance(c, dict)}
    duty = {}
    for entry in candidates:
        for cand in entry['candidates']:
            duty[re.sub(r'[^0-9]', '', cand['code'])] = cand['duty']
    for index, item in enumerate(items):
        choice = choices.get(index) or {}
        code = re.sub(r'[^0-9]', '', str(choice.get('code') or ''))
        item['code'] = tariff_lookup.format_code(code) if code in duty else ''
        item['duty'] = duty.get(code, '')
        item['alternatives'] = [tariff_lookup.format_code(re.sub(r'[^0-9]', '', a)) for a in choice.get('alternatives') or []
                                if re.sub(r'[^0-9]', '', str(a)) in duty][:3]
        item['requirement'] = str(choice.get('requirement') or '')[:300]
        item['note'] = str(choice.get('note') or '')[:300]
    fields = {}
    for key in HEADER_KEYS:
        value = (extracted.get('fields') or {}).get(key)
        if isinstance(value, dict) and str(value.get('value') or '').strip():
            fields[key] = {'value': str(value['value'])[:500], 'source': str(value.get('source') or '')[:180]}
    return {'analyzed_at': utcnow().isoformat(), 'fields': fields, 'items': items,
            'issues': [str(x)[:400] for x in extracted.get('issues') or []][:20], 'model': MODEL}


def chrome_prompt(case, ai):
    lines = ['أنت تساعد مخلصًا جمركيًا في منصة فسح. التبويب المفتوح هو شاشة البيان الجمركي، والمخلص سجّل دخوله بنفسه.',
             'املأ الحقول المطابقة فقط من البيانات التالية. لا تضغط أي زر إرسال أو تقديم أو اعتماد أو سداد، ولا تغيّر أي حقل غير مذكور.',
             'إذا لم تجد حقلًا مطابقًا أو كانت القيمة غير واضحة فاتركه وأخبرني. بعد الانتهاء اعرض لي قائمة بما أدخلته.', '',
             'بيانات البيان:']
    for key, item in (ai.get('fields') or {}).items():
        lines.append(f"- {LABELS.get(key, key)}: {item['value']}")
    lines.append('')
    lines.append('بنود البضاعة:')
    for n, item in enumerate(ai.get('items') or [], 1):
        lines.append(f"{n}) {item.get('description')} | الكمية: {item.get('quantity') or '-'} {item.get('unit') or ''} | "
                     f"القيمة: {item.get('value') or '-'} | المنشأ: {item.get('origin') or '-'} | البند المقترح: {item.get('code') or 'يحدده المخلص'}")
    return '\n'.join(lines)


def copy_button(code):
    if not code:
        return ''
    return '<button type="button" class="btn copy" data-v="' + code + '">نسخ البند</button>'


def page(case, session, error=''):
    esc = html.escape
    ai = case['context'].get('ai') or {}
    hidden = ws.token(session) + f'<input type="hidden" name="revision" value="{case["revision"]}">'
    body = f'''<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/fasah-workspace">مساحة فسح</a>
      <a href="/fasah-workspace/{case["id"]}">المعاملة</a></div>
      <div class="hero"><div class="eyebrow">BROKER ASSISTANT · SAFE ASSISTED MODE</div><h1>مساعد المخلص — {esc(case["title"])}</h1>
      <p>Claude يقرأ مستندات المعاملة، ويقترح البنود والاشتراطات، ويجهز البيانات لإدخالها في فسح. كل ما يظهر هنا اقتراح مبدئي يراجعه المخلص.</p>
      <form method="post" action="/fasah-workspace/{case["id"]}/assistant/analyze" style="display:inline">{hidden}
      <button class="btn">🤖 تحليل المستندات بـ Claude</button></form>
      <a class="btn" href="{FASAH_URL}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">فتح فسح ↗</a></div>'''
    if error:
        body += f'<div class="card warn"><p>{esc(error)}</p></div>'
    if not ai:
        body += '<div class="card"><p>لم يُحلَّل بعد. ارفع المستندات في صفحة المعاملة ثم اضغط "تحليل المستندات بـ Claude".</p></div>'
        return ws.render('مساعد المخلص', body)
    body += f'<p class="muted">آخر تحليل: {esc(ai.get("analyzed_at", "")[:16].replace("T", " "))}</p>'
    if ai.get('issues'):
        body += '<div class="card warn"><h2>ملاحظات وتعارضات</h2><ul>' + ''.join(f'<li>{esc(x)}</li>' for x in ai['issues']) + '</ul></div>'
    rows_html = ''
    for key, item in (ai.get('fields') or {}).items():
        value = esc(item['value'])
        rows_html += (f'<tr><td>{esc(LABELS.get(key, key))}</td><td class="val">{value}</td><td class="muted">{esc(item.get("source", ""))}</td>'
                      f'<td><button type="button" class="btn copy" data-v="{value}">نسخ</button></td></tr>')
    body += ('<div class="card"><h2>بيانات البيان</h2><div class="scroll"><table><tr><th>الحقل</th><th>القيمة</th><th>المصدر</th><th></th></tr>'
             + (rows_html or '<tr><td colspan="4">لم تُستخرج بيانات.</td></tr>') + '</table></div></div>')
    items_html = ''
    for n, item in enumerate(ai.get('items') or [], 1):
        code = esc(item.get('code') or '')
        alts = '، '.join(esc(a) for a in item.get('alternatives') or [])
        items_html += (f'<tr><td>{n}</td><td>{esc(item.get("description") or "")}</td>'
                       f'<td>{esc(str(item.get("quantity") or ""))} {esc(item.get("unit") or "")}</td><td>{esc(str(item.get("value") or ""))}</td>'
                       f'<td>{esc(item.get("origin") or "")}</td>'
                       f'<td><b dir="ltr">{code or "—"}</b> {("· " + esc(item.get("duty"))) if item.get("duty") else ""}'
                       f'{("<div class=muted>بدائل: " + alts + "</div>") if alts else ""}</td>'
                       f'<td>{esc(item.get("requirement") or "")}<div class="muted">{esc(item.get("note") or "")}</div></td>'
                       f'<td>{copy_button(code)}</td></tr>')
    body += ('<div class="card"><h2>بنود البضاعة والبند الجمركي المقترح</h2>'
             '<p class="muted">البنود من جدول التعرفة الخليجية الموحدة (12 رقمًا). المخلص يؤكد البند النهائي، ويتحقق من إذن فسح السلع المقيدة في فسح.</p>'
             '<div class="scroll"><table><tr><th>#</th><th>الوصف</th><th>الكمية</th><th>القيمة</th><th>المنشأ</th><th>البند والرسم</th><th>الاشتراطات</th><th></th></tr>'
             + (items_html or '<tr><td colspan="8">لم تُستخرج بنود.</td></tr>') + '</table></div></div>')
    prompt = esc(chrome_prompt(case, ai))
    body += f'''<div class="card"><h2>🤖 الإدخال في فسح بواسطة Claude in Chrome</h2>
      <p><button type="button" class="btn" id="launchFasah" data-url="{FASAH_URL}">نسخ التعليمات وفتح فسح ↗</button></p>
      <ol><li>الزر أعلاه ينسخ تعليمات البيان كاملة ويفتح فسح في تبويب جديد. سجّل دخولك بنفسك وافتح شاشة البيان.</li>
      <li>افتح Claude من أيقونته في شريط المتصفح (أو بالاختصار الذي تضبطه من chrome://extensions/shortcuts)، وتأكد أن تبويب فسح ضمن مجموعة تبويبات Claude.</li>
      <li>الصق التعليمات (Ctrl + V) وأرسلها. سيملأ الحقول أمامك دون أن يضغط تقديم.</li>
      <li>راجع كل حقل، ثم قدّم البيان بنفسك.</li></ol>
      <details><summary>عرض التعليمات</summary><textarea id="chromePrompt" rows="12" style="width:100%;direction:rtl">{prompt}</textarea></details>
      <p class="muted">المتصفح لا يسمح لأي موقع بفتح لوحة Claude تلقائيًا؛ فتحها يكون بضغطتك على الأيقونة أو الاختصار. <a href="{CHROME_HELP}" target="_blank" rel="noopener noreferrer">مساعدة Claude in Chrome ↗</a></p></div>
      <script>document.querySelectorAll('.copy').forEach(function(b){{b.addEventListener('click',function(){{
        var v=b.dataset.target?document.getElementById(b.dataset.target).value:b.dataset.v;
        navigator.clipboard.writeText(v).then(function(){{var t=b.textContent;b.textContent='تم النسخ ✓';setTimeout(function(){{b.textContent=t}},1500)}});}})}});
      var L=document.getElementById('launchFasah');if(L){{L.addEventListener('click',function(){{
        var open=function(){{window.open(L.dataset.url,'_blank','noopener,noreferrer');}};
        navigator.clipboard.writeText(document.getElementById('chromePrompt').value).then(function(){{
          L.textContent='تم نسخ التعليمات ✓ — الصقها في Claude داخل تبويب فسح';open();}},open);}})}}</script>'''
    return ws.render('مساعد المخلص', body)


@router.get('/fasah-workspace/{case_id}/assistant', response_class=HTMLResponse)
def assistant(case_id: int, request: Request):
    session = ws.authorized(request)
    return page(ws.get_draft(case_id, session), session)


@router.post('/fasah-workspace/{case_id}/assistant/analyze')
async def run_analysis(case_id: int, request: Request):
    session = ws.authorized(request)
    case = ws.get_draft(case_id, session)
    form = await request.form()
    ws.check_csrf(session, form.get('csrf'))
    if str(case['revision']) != str(form.get('revision')):
        raise HTTPException(409, 'حدّث الصفحة قبل التحليل.')
    from starlette.concurrency import run_in_threadpool
    try:
        result = await run_in_threadpool(analyze, case)
    except (ValueError, httpx.HTTPError, json.JSONDecodeError) as error:
        message = str(error) if isinstance(error, ValueError) else 'تعذر التحليل الآن؛ أعد المحاولة بعد قليل.'
        return page(case, session, message)
    case['context']['ai'] = result
    ws.persist(case, session, form.get('revision'), 'fasah_ai_analyzed')
    return RedirectResponse(f'/fasah-workspace/{case_id}/assistant', 303)


_original_panel = view.document_panel


def document_panel(case, hidden, esc):
    link = (f'<div class="card"><a class="btn" href="/fasah-workspace/{case["id"]}/assistant">🤖 مساعد المخلص: قراءة المستندات '
            'واقتراح البنود وتجهيز البيان لفسح</a></div>')
    return link + _original_panel(case, hidden, esc)


view.document_panel = document_panel
