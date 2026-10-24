"""Customs declaration follow-up: FASAH case -> declaration stages -> customer updates -> finance claim draft.

Nobody here logs in to FASAH. A person signs in; data is entered in their session and the result
(declaration number, stage, fees shown by FASAH) is recorded here. Customer updates are prepared for each
stage and sent by email only after a person approves (MFA step-up); WhatsApp is a prefilled link.
Finance gets a *draft* claim that the finance team reviews and posts as usual.
"""
import html
import json
import re
import uuid
from datetime import date
from urllib.parse import parse_qs, quote, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.marketing_content import email_address, whatsapp_number
from app.storage import db, get_session, log, one, rows, utcnow

router = APIRouter()

STAGES = [
    ('preparing', 'تجهيز البيان'),
    ('submitted', 'تم تقديم البيان في فسح'),
    ('under_review', 'قيد التدقيق'),
    ('inspection', 'المعاينة / الكشف'),
    ('duties_due', 'بانتظار سداد الرسوم'),
    ('duties_paid', 'تم سداد الرسوم'),
    ('released', 'تم الفسح'),
    ('delivered', 'تم التسليم للعميل'),
    ('closed', 'مغلق'),
]
STAGE_LABELS = dict(STAGES)
FEES = [('customs_duty', 'الرسوم الجمركية'), ('tax', 'ضريبة القيمة المضافة'), ('customs_other', 'رسوم جمركية أخرى'),
        ('saber', 'سابر'), ('clearance', 'أتعاب التخليص'), ('zakat', 'زكاة'), ('registry', 'سجل تجاري')]
CUSTOMER_TEXT = {
    'submitted': 'تم تقديم البيان الجمركي لشحنتكم في منصة فسح{ref}. سنوافيكم بأي تحديث.',
    'under_review': 'البيان الجمركي لشحنتكم{ref} قيد التدقيق لدى الجمارك.',
    'inspection': 'شحنتكم{ref} في مرحلة المعاينة/الكشف الجمركي. فريقنا يتابع الإجراء في المنفذ.',
    'duties_due': 'صدرت الرسوم الجمركية لشحنتكم{ref} وهي بانتظار السداد. سنرسل لكم تفاصيل المبالغ للسداد.',
    'duties_paid': 'تم سداد الرسوم الجمركية لشحنتكم{ref}، والبيان في المراحل الأخيرة.',
    'released': 'تم فسح شحنتكم{ref} بحمد الله. نرتب الآن النقل إلى موقع التسليم.',
    'delivered': 'تم تسليم شحنتكم{ref}. شكرًا لثقتكم بآفاق طويق.',
}


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS customs_declarations(
            id BIGSERIAL PRIMARY KEY, case_id BIGINT, customer_name TEXT NOT NULL, customer_phone TEXT NOT NULL DEFAULT '',
            customer_email TEXT NOT NULL DEFAULT '', bill_number TEXT NOT NULL DEFAULT '', declaration_number TEXT NOT NULL DEFAULT '',
            port TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL DEFAULT 'preparing', fees TEXT NOT NULL DEFAULT '{}',
            finance_document_id BIGINT, notes TEXT NOT NULL DEFAULT '', created_by BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS customs_declaration_events(
            id BIGSERIAL PRIMARY KEY, declaration_id BIGINT NOT NULL REFERENCES customs_declarations(id),
            stage TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', customer_message TEXT NOT NULL DEFAULT '',
            message_status TEXT NOT NULL DEFAULT 'none', message_ref TEXT, created_by BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS customs_declarations_stage_idx ON customs_declarations(stage,updated_at DESC)')


def esc(v):
    return html.escape(str(v or ''))


def session(request, write=False):
    s = get_session(request.cookies.get('gla_session'))
    if not s:
        return None
    if s.get('role') not in ('admin', 'customs'):
        raise HTTPException(403, 'متابعة البيانات متاحة للإدارة والتخليص')
    return s


async def form(request):
    s = session(request)
    if not s:
        raise HTTPException(401)
    raw = parse_qs((await request.body()).decode())
    data = {k: v[0] for k, v in raw.items()}
    if data.get('csrf') != s['csrf']:
        raise HTTPException(403)
    return s, data


def clean(value, limit=300):
    return re.sub(r'[\x00-\x1f]', ' ', str(value or '')).strip()[:limit]


def ref_text(d):
    parts = []
    if d['declaration_number']:
        parts.append('رقم البيان ' + d['declaration_number'])
    if d['bill_number']:
        parts.append('البوليصة ' + d['bill_number'])
    return (' (' + '، '.join(parts) + ')') if parts else ''


def customer_message(d, stage):
    body = CUSTOMER_TEXT.get(stage)
    if not body:
        return ''
    return ('السلام عليكم ' + d['customer_name'] + '،\n' + body.format(ref=ref_text(d)) +
            '\nللاستفسار: +966530130435 · info@afaqtawiqs.net\nآفاق طويق للتخليص الجمركي والنقل')


def case_fields(case_id):
    if not case_id:
        return {}
    row = one('SELECT fields_json,title FROM fasah_workspace_drafts WHERE id=?', (case_id,))
    if not row:
        return {}
    try:
        fields = json.loads(row['fields_json'] or '{}')
    except ValueError:
        fields = {}
    return {'title': row['title'], 'fields': fields if isinstance(fields, dict) else {}}


STYLE = '''<style>body{font-family:Arial,sans-serif;background:#07131f;color:#eef6fb;margin:0}*{box-sizing:border-box}
.w{max-width:1200px;margin:auto;padding:20px}.nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.nav a,.btn{display:inline-block;padding:9px 14px;border-radius:10px;background:#18384d;color:#fff;text-decoration:none;border:0;font-weight:700;cursor:pointer;font-size:14px}
.btn.go{background:#22c55e;color:#04130a}.btn.wa{background:#25d366;color:#04130a}
.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:16px;margin:12px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
input,select,textarea{width:100%;padding:10px;border-radius:10px;border:1px solid #36586e;background:#081925;color:#fff;font:inherit}
textarea{min-height:110px}.muted{color:#9fb4c4;font-size:14px}.ltr{direction:ltr;unicode-bidi:embed}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.tab{padding:8px 14px;border-radius:999px;background:#0b1d2b;border:1px solid #28475d;color:#eef6fb;text-decoration:none}
.tab.on{background:#eab308;color:#111}.steps{display:flex;gap:6px;flex-wrap:wrap}.step{padding:6px 10px;border-radius:999px;background:#0b1d2b;font-size:13px}
.step.done{background:#14532d}.step.now{background:#eab308;color:#111;font-weight:700}
table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #28475d;text-align:right;vertical-align:top}</style>'''


def page(title, body):
    return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'
                        + esc(title) + '</title>' + STYLE + '<body><div class="w"><div class="nav"><a href="/dashboard">الرئيسية</a>'
                        '<a href="/declarations">متابعة البيانات</a><a href="/fasah-workspace">مساحة فسح</a><a href="/finance">المحاسبة والمالية</a></div>'
                        + body + '</div></body></html>', headers={'Cache-Control': 'no-store'})


@router.get('/declarations', response_class=HTMLResponse)
def home(request: Request, stage: str = 'open'):
    s = session(request)
    if not s:
        return RedirectResponse('/login', 303)
    init()
    counts = {r['stage']: r['n'] for r in rows('SELECT stage,COUNT(*) n FROM customs_declarations GROUP BY stage')}
    where, args = ("stage NOT IN ('delivered','closed')", ()) if stage == 'open' else ('TRUE', ()) if stage == 'all' else ('stage=?', (stage,))
    if stage not in ('open', 'all') and stage not in STAGE_LABELS:
        raise HTTPException(400)
    items = rows('SELECT * FROM customs_declarations WHERE ' + where + ' ORDER BY updated_at DESC LIMIT 100', args)
    cases = rows('SELECT id,title FROM fasah_workspace_drafts ORDER BY id DESC LIMIT 50') if one("SELECT to_regclass('fasah_workspace_drafts') t")['t'] else []
    tabs = ''.join('<a class="tab' + (' on' if k == stage else '') + '" href="/declarations?stage=' + k + '">' + esc(label) + ' ' + str(n) + '</a>'
                   for k, label, n in [('open', 'المفتوحة', sum(v for k2, v in counts.items() if k2 not in ('delivered', 'closed')))] +
                   [(k, label, counts.get(k, 0)) for k, label in STAGES] + [('all', 'الكل', sum(counts.values()))])
    table = ''.join('<tr><td><a href="/declarations/' + str(d['id']) + '">' + esc(d['customer_name']) + '</a></td><td class="ltr">' + esc(d['declaration_number'] or '—') +
                    '</td><td class="ltr">' + esc(d['bill_number']) + '</td><td>' + esc(d['port']) + '</td><td>' + esc(STAGE_LABELS.get(d['stage'])) +
                    '</td><td>' + ('✓ مسودة مطالبة' if d['finance_document_id'] else '—') + '</td><td>' + esc(str(d['updated_at'])[:16]) + '</td></tr>' for d in items) \
        or '<tr><td colspan="7" class="muted">لا توجد بيانات في هذا التبويب.</td></tr>'
    case_options = '<option value="">بدون ربط</option>' + ''.join('<option value="' + str(c['id']) + '">#' + str(c['id']) + ' — ' + esc(c['title']) + '</option>' for c in cases)
    body = ('<h1 style="margin:0">متابعة البيانات الجمركية</h1><p class="muted">من تجهيز البيان في فسح حتى الفسح والتسليم: مرحلة كل بيان، تحديثات العميل، ومسودة المطالبة المالية. '
            'الدخول إلى فسح يتم بحساب الموظف فقط.</p><div class="tabs">' + tabs + '</div>'
            '<div class="card"><table><tr><th>العميل</th><th>رقم البيان</th><th>البوليصة</th><th>المنفذ</th><th>المرحلة</th><th>المالية</th><th>آخر تحديث</th></tr>' + table + '</table></div>'
            '<div class="card"><h3>بيان جديد</h3><form method="post" action="/declarations"><input type="hidden" name="csrf" value="' + esc(s['csrf']) + '"><div class="grid">'
            '<label>ملف مساحة فسح<select name="case_id">' + case_options + '</select></label>'
            '<label>اسم العميل<input name="customer_name" required></label><label>جوال العميل (واتساب)<input name="customer_phone" class="ltr"></label>'
            '<label>بريد العميل<input name="customer_email" type="email" class="ltr"></label><label>رقم البوليصة<input name="bill_number" class="ltr"></label>'
            '<label>المنفذ<input name="port" placeholder="ميناء جدة الإسلامي"></label></div><button class="btn go" style="margin-top:10px">إنشاء</button></form></div>')
    return page('متابعة البيانات', body)


@router.post('/declarations')
async def create(request: Request):
    s, data = await form(request)
    init()
    name = clean(data.get('customer_name'), 200)
    if len(name) < 2:
        raise HTTPException(400, 'اسم العميل مطلوب')
    phone = whatsapp_number(data.get('customer_phone')) if data.get('customer_phone') else ''
    email = email_address(data.get('customer_email')) if data.get('customer_email') else ''
    if data.get('customer_phone') and not phone:
        raise HTTPException(400, 'رقم الجوال غير صالح')
    if data.get('customer_email') and not email:
        raise HTTPException(400, 'البريد غير صالح')
    case_id = int(data['case_id']) if str(data.get('case_id') or '').isdigit() else None
    if case_id and not one('SELECT id FROM fasah_workspace_drafts WHERE id=?', (case_id,)):
        raise HTTPException(400, 'ملف مساحة فسح غير موجود')
    now = utcnow()
    with db() as c:
        did = c.execute('''INSERT INTO customs_declarations(case_id,customer_name,customer_phone,customer_email,bill_number,port,created_by,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (case_id, name, phone, email, clean(data.get('bill_number'), 100),
                                                               clean(data.get('port'), 100), s['user_id'], now, now)).fetchone()['id']
        c.execute("INSERT INTO customs_declaration_events(declaration_id,stage,note,created_by,created_at) VALUES(%s,'preparing','إنشاء ملف المتابعة',%s,%s)",
                  (did, s['user_id'], now))
    log(s['user_id'], 'declaration_created', 'customs_declaration', did, name)
    return RedirectResponse('/declarations/' + str(did), 303)


def load(did):
    d = one('SELECT * FROM customs_declarations WHERE id=?', (did,))
    if not d:
        raise HTTPException(404)
    return d


@router.get('/declarations/{did}', response_class=HTMLResponse)
def detail(did: int, request: Request):
    s = session(request)
    if not s:
        return RedirectResponse('/login', 303)
    init()
    d = load(did)
    from app.mfa_stepup import recent_stepup
    stepped = recent_stepup(s['id'])
    fees = json.loads(d['fees'] or '{}')
    events = rows('SELECT * FROM customs_declaration_events WHERE declaration_id=? ORDER BY id DESC', (did,))
    order = [k for k, _ in STAGES]
    steps = ''.join('<span class="step' + (' now' if k == d['stage'] else ' done' if order.index(k) < order.index(d['stage']) else '') + '">' + esc(label) + '</span>' for k, label in STAGES)
    csrf = esc(s['csrf'])
    case = case_fields(d['case_id'])
    from app.fasah_fields import LABELS
    case_rows = ''.join('<tr><td>' + esc(LABELS.get(k, k)) + '</td><td>' + esc(v.get('value') if isinstance(v, dict) else v) + '</td></tr>'
                        for k, v in case.get('fields', {}).items() if (v.get('value') if isinstance(v, dict) else v))
    stage_options = ''.join('<option value="' + k + '"' + (' selected' if k == d['stage'] else '') + '>' + esc(label) + '</option>' for k, label in STAGES)
    fee_inputs = ''.join('<label>' + esc(label) + '<input name="fee_' + k + '" value="' + esc(fees.get(k, '')) + '" class="ltr" inputmode="decimal"></label>' for k, label in FEES)
    body = ('<h1 style="margin:0">' + esc(d['customer_name']) + '</h1><p class="muted">بيان ' + esc(d['declaration_number'] or 'لم يُسجل رقمه بعد') + ' · بوليصة ' + esc(d['bill_number'] or '—') +
            ' · ' + esc(d['port']) + '</p><div class="steps">' + steps + '</div>')
    if case:
        body += ('<div class="card"><h3>بيانات الإدخال في فسح — ملف #' + str(d['case_id']) + ' ' + esc(case['title']) + '</h3>'
                 '<p class="muted">تُنقل هذه القيم إلى نماذج فسح داخل جلسة الموظف، ثم يُسجل رقم البيان هنا.</p><table>' + (case_rows or '<tr><td class="muted">لا توجد حقول مكتملة في الملف.</td></tr>') +
                 '</table><p><a href="/fasah-workspace/' + str(d['case_id']) + '">فتح ملف مساحة فسح</a></p></div>')
    body += ('<div class="card"><h3>تحديث المرحلة</h3><form method="post" action="/declarations/' + str(did) + '/stage"><input type="hidden" name="csrf" value="' + csrf + '"><div class="grid">'
             '<label>المرحلة<select name="stage">' + stage_options + '</select></label><label>رقم البيان في فسح<input name="declaration_number" class="ltr" value="' + esc(d['declaration_number']) + '"></label>'
             '<label>ملاحظة<input name="note"></label></div><h4>المبالغ كما ظهرت في فسح أو الفاتورة (ريال)</h4><div class="grid">' + fee_inputs + '</div>'
             '<button class="btn go" style="margin-top:10px">حفظ وتجهيز رسالة العميل</button></form></div>')
    timeline = ''
    for e in events:
        timeline += '<div class="card"><b>' + esc(STAGE_LABELS.get(e['stage'], e['stage'])) + '</b> <span class="muted">' + esc(str(e['created_at'])[:16]) + ' · ' + esc(e['note']) + '</span>'
        if e['customer_message']:
            timeline += '<pre style="white-space:pre-wrap">' + esc(e['customer_message']) + '</pre><p class="muted">حالة الرسالة: ' + esc({'draft': 'بانتظار الإرسال', 'sent': 'أُرسلت بالبريد', 'failed': 'تعذر الإرسال', 'whatsapp': 'فُتحت في واتساب'}.get(e['message_status'], e['message_status'])) + '</p>'
            if d['customer_phone']:
                timeline += '<a class="btn wa" target="_blank" rel="noopener" href="https://wa.me/' + d['customer_phone'].lstrip('+') + '?text=' + quote(e['customer_message']) + '">إرسال عبر واتساب</a> '
            if d['customer_email'] and e['message_status'] in ('draft', 'failed'):
                timeline += ('<form method="post" action="/declarations/' + str(did) + '/events/' + str(e['id']) + '/send" style="display:inline"><input type="hidden" name="csrf" value="' + csrf + '">'
                             '<button class="btn go">إرسال بالبريد إلى ' + esc(d['customer_email']) + '</button></form>' if stepped else
                             '<a class="btn" href="/mfa/step-up?next=/declarations/' + str(did) + '">التحقق لإرسال البريد</a>')
        timeline += '</div>'
    body += '<h3>سجل المراحل وتحديثات العميل</h3>' + timeline
    body += finance_box(d, fees, csrf)
    return page('بيان ' + d['customer_name'], body)


def finance_box(d, fees, csrf):
    if d['finance_document_id']:
        return ('<div class="card"><h3>المالية</h3><p>تم إنشاء مسودة مطالبة مالية للعميل. المراجعة والترحيل يتمان في قسم المالية.</p>'
                '<a class="btn" href="/finance/documents/' + str(d['finance_document_id']) + '">فتح المطالبة #' + str(d['finance_document_id']) + '</a></div>')
    if one("SELECT to_regclass('finance_parties') t")['t'] is None:
        return ''
    owners = rows("SELECT id,name FROM finance_parties WHERE kind='owner' AND confirmed ORDER BY id")
    parties = rows("SELECT id,name FROM finance_parties WHERE kind='counterparty' AND confirmed ORDER BY name")
    total = sum(float(fees.get(k) or 0) for k, _ in FEES)
    opt = lambda items, guess='': ''.join('<option value="' + str(p['id']) + '"' + (' selected' if guess and guess in p['name'] else '') + '>' + esc(p['name']) + '</option>' for p in items)
    return ('<div class="card"><h3>إنشاء مطالبة مالية (مسودة)</h3><p class="muted">تُنشأ المطالبة كمسودة في قسم المالية ببنود المبالغ المسجلة أعلاه (الإجمالي ' + f'{total:,.2f}' +
            ' ريال)، ثم يراجعها فريق المالية ويرحّلها. لا يتم ترحيل أي قيد تلقائيًا.</p><form method="post" action="/declarations/' + str(d['id']) + '/finance"><input type="hidden" name="csrf" value="' + csrf + '"><div class="grid">'
            '<label>المنشأة<select name="owner_id">' + opt(owners, 'آفاق') + '</select></label><label>العميل في المالية<select name="counterparty_id">' + opt(parties, d['customer_name']) + '</select></label>'
            '<label>تاريخ المطالبة<input type="date" name="document_date" value="' + date.today().isoformat() + '"></label>'
            '<label>قيمة فاتورة البضاعة<input name="goods_amount" class="ltr" required></label><label>عملة الفاتورة<input name="goods_currency" value="SAR" class="ltr" required></label>'
            '<label>سعر التحويل إلى الريال<input name="exchange_rate" value="1" class="ltr" required></label></div>'
            '<label><input type="checkbox" name="confirmation" value="1" style="width:auto" required> المبالغ مطابقة لفسح والفواتير، ولا تشمل قيمة البضاعة</label><br>'
            '<button class="btn go">إنشاء المسودة في المالية</button></form>'
            + ('' if parties else '<p class="muted">لا توجد جهة عميل مؤكدة في المالية؛ أضفها من قسم المالية أولًا.</p>') + '</div>')


def money(raw):
    raw = clean(raw, 32).replace(',', '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    if raw == '':
        return ''
    if not re.fullmatch(r'\d{1,12}(\.\d{1,2})?', raw):
        raise HTTPException(400, 'مبلغ غير صالح: ' + raw)
    return raw


@router.post('/declarations/{did}/stage')
async def update_stage(did: int, request: Request):
    s, data = await form(request)
    d = load(did)
    stage = data.get('stage')
    if stage not in STAGE_LABELS:
        raise HTTPException(400)
    number = clean(data.get('declaration_number'), 60)
    if number and not re.fullmatch(r'[A-Za-z0-9\-/]{3,60}', number):
        raise HTTPException(400, 'رقم البيان غير صالح')
    fees = json.loads(d['fees'] or '{}')
    for k, _ in FEES:
        if 'fee_' + k in data:
            fees[k] = money(data.get('fee_' + k))
    now = utcnow()
    updated = dict(d, declaration_number=number or d['declaration_number'], stage=stage)
    message = customer_message(updated, stage) if stage != d['stage'] else ''
    with db() as c:
        c.execute('UPDATE customs_declarations SET stage=%s,declaration_number=%s,fees=%s,updated_at=%s WHERE id=%s',
                  (stage, updated['declaration_number'], json.dumps(fees), now, did))
        if stage != d['stage'] or data.get('note'):
            c.execute('''INSERT INTO customs_declaration_events(declaration_id,stage,note,customer_message,message_status,created_by,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s)''', (did, stage, clean(data.get('note'), 500), message, 'draft' if message else 'none', s['user_id'], now))
    log(s['user_id'], 'declaration_stage', 'customs_declaration', did, STAGE_LABELS[stage])
    return RedirectResponse('/declarations/' + str(did), 303)


@router.post('/declarations/{did}/events/{eid}/send')
async def send_email(did: int, eid: int, request: Request):
    s, _ = await form(request)
    d = load(did)
    if not d['customer_email']:
        raise HTTPException(400, 'لا يوجد بريد للعميل')
    with db() as c:
        e = c.execute("UPDATE customs_declaration_events SET message_status='sending' WHERE id=%s AND declaration_id=%s AND message_status IN ('draft','failed') AND customer_message<>'' RETURNING *",
                      (eid, did)).fetchone()
    if not e:
        raise HTTPException(409, 'سبق إرسال الرسالة أو لا توجد رسالة')
    from app import spacemail
    try:
        mid = await run_in_threadpool(spacemail.send, s['user_id'], d['customer_email'], 'تحديث شحنتكم — ' + STAGE_LABELS[e['stage']], e['customer_message'])
        state = 'sent'
    except Exception:
        mid, state = None, 'failed'
    with db() as c:
        c.execute('UPDATE customs_declaration_events SET message_status=%s,message_ref=%s WHERE id=%s', (state, mid, eid))
    log(s['user_id'], 'declaration_customer_email', 'customs_declaration', did, state)
    return RedirectResponse('/declarations/' + str(did), 303)


@router.post('/declarations/{did}/finance')
async def create_claim(did: int, request: Request):
    s, data = await form(request)
    from app.fine_permissions import has_permission
    if not has_permission(s, 'edit_finance'):
        raise HTTPException(403, 'صلاحية تعديل المالية مطلوبة')
    d = load(did)
    if d['finance_document_id']:
        return RedirectResponse('/declarations/' + str(did), 303)
    fees = json.loads(d['fees'] or '{}')
    components = {k: (fees.get(k) or '0') for k, _ in FEES}
    from decimal import Decimal
    total = sum(Decimal(v) for v in components.values())
    if total <= 0:
        raise HTTPException(400, 'سجّل مبالغ البيان أولًا')
    from app import finance_service as fs
    economic = 'customs-claim:' + (d['declaration_number'] or ('declaration-' + str(did)))
    doc_form = {'kind': 'claim', 'currency': 'SAR', 'amount': str(total), 'document_date': data.get('document_date') or date.today().isoformat(),
                'amount_basis': 'gross', 'source_role': 'detail', 'source_ref': 'customs_declaration:' + str(did),
                'source_locator': 'fees:' + json.dumps(components, sort_keys=True), 'economic_ref': economic,
                'customs_ref': d['declaration_number'], 'owner_id': data.get('owner_id'), 'counterparty_id': data.get('counterparty_id'),
                'notes': 'مطالبة بيان جمركي للعميل ' + d['customer_name'] + ref_text(d), 'idempotency_key': str(uuid.uuid5(uuid.NAMESPACE_URL, 'declaration-doc-%d' % did))}
    try:
        from app import finance_core as core
        doc_id = fs.create_document(doc_form, s['user_id'])
        detail_form = dict({'idempotency_key': str(uuid.uuid5(uuid.NAMESPACE_URL, 'declaration-detail-%d' % did)), 'expected_revision': '0',
                            'confirmation': data.get('confirmation'), 'goods_amount': data.get('goods_amount'), 'goods_currency': data.get('goods_currency'),
                            'exchange_rate': data.get('exchange_rate'), 'source_ref': 'customs_declaration:' + str(did),
                            'reason': 'بنود البيان الجمركي كما سُجلت في متابعة البيانات'}, **components)
        fs.attach_claim_details(doc_id, s['user_id'], detail_form)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    with db() as c:
        c.execute('UPDATE customs_declarations SET finance_document_id=%s,updated_at=%s WHERE id=%s', (doc_id, utcnow(), did))
        c.execute("INSERT INTO customs_declaration_events(declaration_id,stage,note,created_by,created_at) VALUES(%s,%s,%s,%s,%s)",
                  (did, d['stage'], 'أُنشئت مسودة مطالبة مالية #' + str(doc_id), s['user_id'], utcnow()))
    log(s['user_id'], 'declaration_finance_claim', 'customs_declaration', did, 'draft claim ' + str(doc_id))
    return RedirectResponse('/declarations/' + str(did), 303)


@router.get('/api/v7/declarations/{did}/entry')
def entry_package(did: int, request: Request):
    """Field values to transfer into FASAH inside a staff member's own signed-in session."""
    if not session(request):
        raise HTTPException(401)
    d = load(did)
    case = case_fields(d['case_id'])
    from app.fasah_fields import LABELS
    return JSONResponse({'declaration_id': did, 'customer': d['customer_name'], 'bill_number': d['bill_number'], 'port': d['port'],
                         'fields': [{'key': k, 'label': LABELS.get(k, k), 'value': v.get('value') if isinstance(v, dict) else v}
                                    for k, v in case.get('fields', {}).items()]})
