"""Fasah preparation only: no connector, credentials, submission or automation."""
import hashlib
import hmac
import json
import urllib.parse
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.datastructures import UploadFile
from python_multipart.exceptions import MultipartParseError

from app.fasah_documents import MAX_BYTES, extract_document
from app.fasah_fields import (DOCUMENT_TYPES, FASAH_URL, FIELDS, FIELD_KEYS, LABELS,
    clean, empty_fields, extract_candidates, merge_candidates, readiness, reject_credentials)
from app.storage import db, get_session, log, one, rows, utcnow

router = APIRouter()


def init_storage():
    with db() as connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS fasah_workspace_drafts (
            id BIGSERIAL PRIMARY KEY, created_by BIGINT NOT NULL REFERENCES users(id),
            title TEXT NOT NULL, fields_json TEXT NOT NULL, documents_json TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL)''')


init_storage()


def authorized(request):
    session = get_session(request.cookies.get('gla_session'))
    if not session:
        raise HTTPException(401, 'يلزم الدخول إلى وكيل آفاق.')
    if session.get('role') not in ('admin', 'customs'):
        raise HTTPException(403, 'مساحة فسح متاحة للإدارة وموظفي التخليص فقط.')
    return session


def check_csrf(session, value):
    if not isinstance(value, str) or not hmac.compare_digest(value, session['csrf']):
        raise HTTPException(403, 'انتهت صلاحية النموذج. حدّث الصفحة.')


def get_draft(case_id, session):
    case = one('SELECT * FROM fasah_workspace_drafts WHERE id=? AND created_by=?', (case_id, session['user_id']))
    if not case:
        raise HTTPException(404, 'المسودة غير موجودة أو غير متاحة لهذا الموظف.')
    case['fields'] = json.loads(case['fields_json'])
    case['documents'] = json.loads(case['documents_json'])
    return case


def persist(case, session, revision, action):
    if str(case['revision']) != str(revision):
        raise HTTPException(409, 'عُدلت المسودة في صفحة أخرى. حدّث الصفحة قبل المتابعة.')
    with db() as connection:
        updated = connection.execute('''UPDATE fasah_workspace_drafts
            SET fields_json=%s,documents_json=%s,revision=revision+1,updated_at=%s
            WHERE id=%s AND created_by=%s AND revision=%s RETURNING id''',
            (json.dumps(case['fields'], ensure_ascii=False), json.dumps(case['documents'], ensure_ascii=False),
             utcnow(), case['id'], session['user_id'], case['revision'])).fetchone()
        if not updated:
            raise HTTPException(409, 'عُدلت المسودة بالتزامن. حدّث الصفحة.')
    # Audit identifiers/actions only; never document contents or field values.
    log(session['user_id'], action, 'fasah_workspace', case['id'], 'Internal preparation only; no Fasah action')


async def small_form(request, session):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 200000:
            raise HTTPException(413, 'النص أو النموذج كبير جدًا.')
    try:
        values = urllib.parse.parse_qs(body.decode('utf-8'), keep_blank_values=True, max_num_fields=80)
    except (UnicodeError, ValueError):
        raise HTTPException(422, 'صيغة النموذج غير صحيحة.') from None
    if any(len(v) != 1 for v in values.values()):
        raise HTTPException(422, 'حقول مكررة في النموذج.')
    values = {k: v[0] for k, v in values.items()}
    check_csrf(session, values.get('csrf'))
    return values


def validate_text(value, maximum=500):
    if not isinstance(value, str) or len(value) > maximum:
        raise HTTPException(422, 'تجاوز النص الحد المسموح.')
    try:
        reject_credentials(value)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return clean(value, maximum)


def back(case_id):
    return RedirectResponse('/fasah-workspace/' + str(case_id), 303)


def render(title, body):
    from app.main import page
    response = HTMLResponse(page(title, body))
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; connect-src 'self'; frame-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def token(session):
    from app.main import esc
    return '<input type="hidden" name="csrf" value="' + esc(session['csrf']) + '">'


def intro():
    return f'''<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/fasah-workspace">مساحة فسح</a></div>
    <div class="hero"><div class="eyebrow">SAFE ASSISTED MODE</div><h1>مساحة فسح</h1>
    <p>جهّز مستندات المعاملة، راجع الحقول والنواقص، ثم أدخلها بنفسك في فسح.</p>
    <a class="btn" href="{FASAH_URL}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">فتح فسح الرسمية في نافذة مستقلة ↗</a>
    <p class="muted">تسجيل الدخول والتحقق والاعتماد والإرسال داخل فسح بيد الموظف المخوّل. هذه المساحة لا تقرأ نافذة فسح ولا تتحكم بها.</p></div>'''


@router.get('/fasah-workspace', response_class=HTMLResponse)
def home(request: Request):
    session = authorized(request)
    from app.main import esc
    cases = rows('SELECT id,title,updated_at FROM fasah_workspace_drafts WHERE created_by=? ORDER BY updated_at DESC LIMIT 100', (session['user_id'],))
    listing = ''.join(f'<tr><td><a href="/fasah-workspace/{c["id"]}">{esc(c["title"])}</a></td><td>{esc(c["updated_at"])}</td><td>مسودة داخلية</td></tr>' for c in cases)
    body = intro() + '<div class="card"><h2>مسودة تجهيز جديدة</h2><form method="post" action="/fasah-workspace">' + token(session) + '<label for="case-title">مرجع المعاملة الداخلي</label><input id="case-title" name="title" maxlength="120" required placeholder="مثال: معاملة العميل — رقم داخلي"><button class="btn">إنشاء مساحة تجهيز</button></form></div>'
    body += '<div class="card scroll"><h2>مسوداتي</h2><table><tr><th>المعاملة</th><th>آخر تعديل</th><th>النوع</th></tr>' + (listing or '<tr><td colspan="3">لا توجد مسودات بعد.</td></tr>') + '</table></div>'
    return render('مساحة فسح — آفاق طويق', body)


@router.post('/fasah-workspace')
async def create(request: Request):
    session = authorized(request)
    values = await small_form(request, session)
    if set(values) - {'csrf', 'title'}:
        raise HTTPException(422, 'حقول غير مدعومة.')
    title = validate_text(values.get('title', ''), 120)
    if not title:
        raise HTTPException(422, 'أدخل مرجع المعاملة.')
    with db() as connection:
        case_id = connection.execute('''INSERT INTO fasah_workspace_drafts
            (created_by,title,fields_json,documents_json,created_at,updated_at)
            VALUES(%s,%s,%s,'[]',%s,%s) RETURNING id''',
            (session['user_id'], title, json.dumps(empty_fields()), utcnow(), utcnow())).fetchone()['id']
    log(session['user_id'], 'fasah_draft_created', 'fasah_workspace', case_id, 'Internal draft')
    return back(case_id)


def attach(case, session, revision, kind, name, pages, notes, fingerprint):
    if kind not in DOCUMENT_TYPES:
        raise HTTPException(422, 'اختر نوع المستند.')
    if len(case['documents']) >= 12:
        raise HTTPException(422, 'الحد الأقصى 12 مستندًا لكل مسودة.')
    if any(d['sha256'] == fingerprint for d in case['documents']):
        raise HTTPException(409, 'هذا المستند مضاف بالفعل.')
    document_id = uuid.uuid4().hex
    try:
        candidates = extract_candidates(pages, name, document_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    found = sum(len(v) for v in candidates.values())
    if not found:
        notes.append('لم تُحدد حقول ذات عناوين واضحة. راجع النص أدناه وأكمل الحقول يدويًا.')
    case['fields'] = merge_candidates(case['fields'], candidates)
    case['documents'].append({'id': document_id, 'kind': kind, 'name': name, 'sha256': fingerprint,
                              'pages': pages, 'notes': notes, 'candidate_count': found})
    persist(case, session, revision, 'fasah_document_prepared')


@router.post('/fasah-workspace/{case_id}/documents')
async def upload(case_id: int, request: Request):
    session = authorized(request)
    case = get_draft(case_id, session)
    # Reject off-origin uploads before reading bytes, in addition to the app guard.
    origin = request.headers.get('origin') or request.headers.get('referer', '')
    if urllib.parse.urlparse(origin).netloc != (request.headers.get('x-forwarded-host') or request.headers.get('host')):
        raise HTTPException(403, 'طلب رفع من مصدر غير مسموح.')
    async def bounded_stream():
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BYTES + 65536:
                raise MultiPartException('حجم الملف يتجاوز 10 ميجابايت.')
            yield chunk
    if not request.headers.get('content-type', '').lower().startswith('multipart/form-data;'):
        raise HTTPException(415, 'استخدم نموذج رفع المستند.')
    parser = MultiPartParser(request.headers, bounded_stream(), max_files=1, max_fields=3)
    try:
        form = await parser.parse()
    except (MultiPartException, MultipartParseError, UnicodeError):
        for temporary in parser._files_to_close_on_error:
            temporary.close()
        raise HTTPException(413, 'ملف كبير جدًا أو صيغة رفع غير صحيحة؛ الحد 10 ميجابايت.') from None
    try:
        if set(form) - {'csrf', 'revision', 'kind', 'file'} or len(list(form.multi_items())) != 4:
            raise HTTPException(422, 'صيغة الرفع غير صحيحة.')
        check_csrf(session, form.get('csrf'))
        if str(case['revision']) != str(form.get('revision')):
            raise HTTPException(409, 'حدّث الصفحة قبل رفع المستند.')
        file = form.get('file')
        if not isinstance(file, UploadFile):
            raise HTTPException(422, 'اختر مستندًا.')
        name = validate_text((file.filename or 'document').replace('\\', '/').rsplit('/', 1)[-1], 180)
        data = await file.read(MAX_BYTES + 1)
        try:
            pages, notes = await run_in_threadpool(extract_document, data)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        attach(case, session, form.get('revision'), form.get('kind'), name, pages, notes, hashlib.sha256(data).hexdigest())
    finally:
        await form.close()
    return back(case_id)


@router.post('/fasah-workspace/{case_id}/text')
async def paste(case_id: int, request: Request):
    session = authorized(request)
    case = get_draft(case_id, session)
    values = await small_form(request, session)
    if set(values) - {'csrf', 'revision', 'kind', 'name', 'text'}:
        raise HTTPException(422, 'حقول غير مدعومة.')
    source = validate_text(values.get('text', ''), 15000)
    if not source:
        raise HTTPException(422, 'الصق نص المستند.')
    # Preserve line boundaries for extraction; validate_text only sanitizes display fields.
    source = values['text']
    name = validate_text(values.get('name', 'نص منسوخ'), 180) or 'نص منسوخ'
    attach(case, session, values.get('revision'), values.get('kind'), name,
           [{'text': source, 'page': 1, 'method': 'نص أدخله الموظف — ترقيم الصفحة غير موثق'}],
           [], hashlib.sha256(source.encode()).hexdigest())
    return back(case_id)


@router.post('/fasah-workspace/{case_id}/fields')
async def save_fields(case_id: int, request: Request):
    session = authorized(request)
    case = get_draft(case_id, session)
    values = await small_form(request, session)
    allowed = {'csrf', 'revision'} | {'value_' + k for k in FIELD_KEYS} | {'review_' + k for k in FIELD_KEYS}
    if set(values) - allowed:
        raise HTTPException(422, 'حقول غير مدعومة؛ لا تُدخل بيانات حساب فسح.')
    if not all('value_' + k in values for k in FIELD_KEYS):
        raise HTTPException(422, 'نموذج غير مكتمل. حدّث الصفحة.')
    for key in FIELD_KEYS:
        value = validate_text(values['value_' + key])
        case['fields'][key]['value'] = value
        case['fields'][key]['reviewed'] = bool(value and values.get('review_' + key) == 'yes')
    persist(case, session, values.get('revision'), 'fasah_fields_reviewed')
    return back(case_id)


@router.post('/fasah-workspace/{case_id}/documents/{document_id}/remove')
async def remove_document(case_id: int, document_id: str, request: Request):
    session = authorized(request)
    case = get_draft(case_id, session)
    values = await small_form(request, session)
    if not any(d['id'] == document_id for d in case['documents']):
        raise HTTPException(404, 'المستند غير موجود.')
    case['documents'] = [d for d in case['documents'] if d['id'] != document_id]
    for field in case['fields'].values():
        previous = field['candidates']
        remaining = [c for c in previous if c['document_id'] != document_id]
        if len(previous) != len(remaining):
            if any(c['document_id'] == document_id and c['value'] == field['value'] for c in previous):
                field['value'] = ''
            field['reviewed'] = False
            field['candidates'] = remaining
    persist(case, session, values.get('revision'), 'fasah_document_removed')
    return back(case_id)


@router.get('/fasah-workspace/{case_id}', response_class=HTMLResponse)
def detail(case_id: int, request: Request):
    session = authorized(request)
    case = get_draft(case_id, session)
    from app.main import esc
    status = readiness(case['fields'], case['documents'])
    hidden = token(session) + f'<input type="hidden" name="revision" value="{case["revision"]}">'
    options = ''.join(f'<option value="{key}">{label}</option>' for key, label in DOCUMENT_TYPES.items())
    body = intro() + f'<h2>{esc(case["title"])}</h2><div class="grid"><div class="kpi">حقول أساسية ناقصة<b>{len(status["missing"])}</b></div><div class="kpi">حقول تحتاج مراجعة<b>{len(status["unreviewed"])}</b></div><div class="kpi">تعارضات غير محسومة<b>{len(status["conflicts"])}</b></div></div>'
    body += '<div class="card warn"><h2>مراجعة التجهيز</h2>'
    if status['missing']:
        body += '<p>الحقول الناقصة: ' + esc('، '.join(status['missing'])) + '</p>'
    if status['conflicts']:
        body += '<p>قيم مختلفة بين المستندات: ' + esc('، '.join(status['conflicts'])) + ' — اختر القيمة الصحيحة بعد مطابقة الأصل.</p>'
    if status['document_types_missing']:
        body += '<p>مستندات لم تُضف: ' + esc('، '.join(status['document_types_missing'])) + '.</p>'
    if status['review_complete']:
        body += '<p class="good">اكتملت مراجعة الحقول الأساسية داخليًا.</p>'
    body += '<p class="muted">قائمة تجهيز داخلية وليست تحققًا رسميًا من اكتمال متطلبات فسح. راجع بنود البضاعة تفصيليًا والمستندات والتصاريح المطلوبة للمعاملة داخل فسح؛ لا يحدد الوكيل تصنيفًا جمركيًا أو رسومًا.</p></div>'
    body += f'''<div class="card"><h2>1. أضف مستندات المعاملة</h2><p class="muted">PDF أو PNG أو JPEG، حتى 10 ميجابايت و10 صفحات لكل ملف. القراءة محلية؛ يُحفظ النص المستخرج ومصادر الحقول داخل آفاق، وتُحذف نسخة المعالجة المؤقتة. لا ترفع بيانات الدخول.</p>
    <form method="post" enctype="multipart/form-data" action="/fasah-workspace/{case_id}/documents">{hidden}<label for="doc-kind">نوع المستند</label><select id="doc-kind" name="kind">{options}</select><label for="doc-file">الملف</label><input id="doc-file" name="file" type="file" accept=".pdf,.png,.jpg,.jpeg" required><button class="btn">قراءة المستند وتجهيز الحقول</button></form>
    <details><summary>أو الصق نصًا من مستند المعاملة</summary><form method="post" action="/fasah-workspace/{case_id}/text">{hidden}<label>نوع المستند<select name="kind">{options}</select></label><label>اسم المصدر<input name="name" maxlength="180" required></label><label>نص المستند<textarea name="text" maxlength="15000" required></textarea></label><button class="btn">استخراج من النص</button></form></details></div>'''
    field_rows = ''
    last_group = None
    for key, label, group, required, _ in FIELDS:
        field = case['fields'][key]
        if group != last_group:
            field_rows += f'<h3>{group}</h3>'
            last_group = group
        evidence = ''
        for candidate in field['candidates']:
            evidence += f'<li><b>{esc(candidate["value"])}</b> — {esc(candidate["source"])}، صفحة {candidate["page"]}، {esc(candidate["method"])}<br><small>{esc(candidate["evidence"])}</small> <button type="button" class="pick" data-target="v-{key}" data-value="{esc(candidate["value"])}">اختيار هذه القيمة</button></li>'
        field_rows += f'''<div class="field-row"><label for="v-{key}">{label}{' *' if required else ''}</label><div class="field-input"><input id="v-{key}" data-key="{key}" name="value_{key}" maxlength="500" value="{esc(field['value'])}" dir="auto"><button type="button" class="copy" data-target="v-{key}">نسخ</button></div><label class="review"><input id="review-{key}" type="checkbox" name="review_{key}" value="yes" {'checked' if field['reviewed'] else ''}> راجعت هذه القيمة مع الأصل وحسمت أي تعارض</label><details><summary>مصادر القيمة ({len(field['candidates'])})</summary><ul>{evidence or '<li>لا توجد قيمة مستخرجة موثوقة؛ أكملها يدويًا من المستند.</li>'}</ul></details></div>'''
    body += f'<div class="card"><h2>2. راجع الحقول ورتبها للإدخال اليدوي</h2><p>النجمة تعني حقلًا أساسيًا في قائمة التجهيز الداخلية. جميع القيم المستخرجة تحتاج مراجعتك.</p><form id="field-form" method="post" action="/fasah-workspace/{case_id}/fields">{hidden}{field_rows}<button class="btn">حفظ المراجعة الداخلية</button><span id="dirty-message" role="status"></span></form><p id="copy-status" role="status" aria-live="polite"></p></div>'
    body += '<div class="card"><h2>3. أدخل المعاملة في فسح</h2><ol><li>احفظ مراجعتك وافتح فسح من الزر الرسمي.</li><li>سجّل الدخول وأكمل التحقق بنفسك داخل فسح.</li><li>انسخ القيم التي راجعتها والصقها في الحقول المقابلة؛ راجع أيضًا بنود الأصناف والكميات والوحدات.</li><li>راجع المعاملة كاملة في فسح؛ الاعتماد والإرسال الرسمي للموظف المخوّل فقط.</li></ol></div>'
    for document in case['documents']:
        notes = ''.join('<p class="warn">' + esc(n) + '</p>' for n in document['notes'])
        text = ''.join(f'<h4>صفحة {p["page"]} — {esc(p["method"])}</h4><pre dir="auto">{esc(p["text"])}</pre>' for p in document['pages'])
        body += f'<div class="card"><h3>{esc(document["name"])}</h3><p>{DOCUMENT_TYPES[document["kind"]]} · {len(document["pages"])} صفحة · {document["candidate_count"]} قيمة مرشحة</p>{notes}<details><summary>عرض النص المستخرج لمراجعة التفاصيل والبنود</summary>{text}</details><form method="post" action="/fasah-workspace/{case_id}/documents/{document["id"]}/remove">{hidden}<button class="btn">إزالة المستند ونتائجه من المسودة</button></form></div>'
    body += '''<style>.field-row{border-bottom:1px solid var(--line);padding:16px 0}.field-input{display:flex;gap:8px}.field-input input{flex:1;min-width:0}.review{display:flex;align-items:center;gap:8px}.review input{width:auto}.field-row button{padding:8px;border-radius:8px;cursor:pointer}details{margin:12px 0}summary{cursor:pointer;color:var(--gold2)}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto}#dirty-message{margin:12px;color:var(--gold2)}</style>
    <script>
    (()=>{
      let dirty=false;
      const form=document.getElementById('field-form');
      const mark=()=>{dirty=true;document.getElementById('dirty-message').textContent='توجد تعديلات غير محفوظة';};
      form.querySelectorAll('input[data-key]').forEach(input=>input.addEventListener('input',()=>{document.getElementById('review-'+input.dataset.key).checked=false;mark();}));
      form.querySelectorAll('input[type=checkbox]').forEach(input=>input.addEventListener('change',mark));
      document.querySelectorAll('.pick').forEach(button=>button.addEventListener('click',()=>{const input=document.getElementById(button.dataset.target);input.value=button.dataset.value;input.dispatchEvent(new Event('input'));input.focus();}));
      document.querySelectorAll('.copy').forEach(button=>button.addEventListener('click',async()=>{
        const input=document.getElementById(button.dataset.target),status=document.getElementById('copy-status');
        if(!input.value || !document.getElementById('review-'+input.dataset.key).checked){status.textContent='راجع القيمة وحدد مربع المراجعة قبل نسخها.';return;}
        try{await navigator.clipboard.writeText(input.value);status.textContent='نُسخت القيمة فقط؛ الصقها يدويًا في فسح.';}catch(_){input.focus();input.select();status.textContent='تم تحديد القيمة؛ انسخها يدويًا باستخدام Ctrl+C.';}
      }));
      form.addEventListener('submit',()=>{dirty=false;});
      document.querySelectorAll('form').forEach(other=>{if(other!==form)other.addEventListener('submit',event=>{if(dirty){event.preventDefault();document.getElementById('dirty-message').textContent='احفظ مراجعة الحقول قبل إضافة مستند أو إزالته.';form.scrollIntoView({behavior:'smooth'});}});});
      window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
    })();
    </script>'''
    return render('مساحة فسح — ' + case['title'], body)
