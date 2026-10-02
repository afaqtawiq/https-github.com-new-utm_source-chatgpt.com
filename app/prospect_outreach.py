"""Reviewed one-time introductions to verified prospects, never buying requests.

Public provenance is verified separately from explicit service-request evidence.
There is no scheduler, bulk import, automatic reply, quote, or conversion here.
"""
import hashlib
import html
import json
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from app.storage import db, one, rows, utcnow, get_session
from app.mail_threads import address
from app.public_contacts import PUBLIC_EMAIL, published_emails
from app.opportunity_quality import normalize

router = APIRouter()
EXCLUSION = 'owner_confirmed_not_current_customer'


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS sales_prospects(
            id BIGSERIAL PRIMARY KEY, company_name TEXT NOT NULL, recipient TEXT NOT NULL UNIQUE,
            mail_user_id BIGINT NOT NULL REFERENCES users(id),
            source_url TEXT NOT NULL, source_email TEXT NOT NULL, identity_name TEXT NOT NULL,
            confidence TEXT NOT NULL, verified_at TIMESTAMPTZ NOT NULL, exclusion_basis TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'prospect_verified', needs TEXT, voluntary_rate_notes TEXT,
            created_by BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS sales_prospect_email_once ON sales_prospects(LOWER(recipient))')
        c.execute('ALTER TABLE outbound_messages ADD COLUMN IF NOT EXISTS prospect_id BIGINT REFERENCES sales_prospects(id)')
        c.execute("ALTER TABLE outbound_messages ADD COLUMN IF NOT EXISTS purpose TEXT NOT NULL DEFAULT 'public_request'")
        c.execute('ALTER TABLE outbound_messages ADD COLUMN IF NOT EXISTS approval_digest TEXT')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS prospect_intro_once ON outbound_messages(prospect_id) WHERE purpose=\'intro_prospect\'')
        c.execute('ALTER TABLE official_mail_links ADD COLUMN IF NOT EXISTS prospect_id BIGINT REFERENCES sales_prospects(id)')


def admin(request):
    s = get_session(request.cookies.get('gla_session'))
    if not s:
        raise HTTPException(401)
    require_owner(s)
    return s


def require_owner(s):
    from app.fine_permissions import has_permission
    if s.get('role') != 'admin' or not has_permission(s, 'manage_gmail') or not has_permission(s, 'send_email'):
        raise HTTPException(403, 'Official mailbox owner permission required')


def canonical(value):
    result = address(value)
    if not result or result != str(value or '').strip().lower():
        raise HTTPException(400, 'One plain email address is required')
    return result


def host(value):
    p = urlsplit(str(value or ''))
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443) or p.fragment:
        raise ValueError('An official public HTTPS source is required')
    return p.hostname.lower().removeprefix('www.')


def verify_source(source_url, recipient, identity_name):
    """Recheck the exact public address and attested company identity, fail closed."""
    from app.discovery import fetch_public
    recipient = canonical(recipient)
    source_host = host(source_url)
    domain = recipient.rsplit('@', 1)[1]
    if source_host != domain and not source_host.endswith('.' + domain):
        raise ValueError('The email must belong to the verified official source domain')
    identity_name = str(identity_name or '').strip()
    if len(identity_name) < 4 or len(identity_name) > 300:
        raise ValueError('A company identity visible on the official source is required')
    page = fetch_public(source_url)
    if host(page['url']) != source_host:
        raise ValueError('Official source redirected to a different identity')
    text = html.unescape(str(page.get('title') or '')+' '+str(page.get('request_text') or ''))
    emails = published_emails(text)
    # Public contact metadata is evidence of an address only, never a request.
    emails.update(str(e).lower() for e in page.get('public_contact_emails', []))
    if recipient not in emails:
        raise ValueError('Recipient email is not published on the official source')
    clean = lambda v: re.sub(r'\s+', ' ', normalize(v)).strip()
    identity_text = PUBLIC_EMAIL.sub(' ', text)
    identity_text = re.sub(r'https?://\S+|(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:/\S*)?', ' ', identity_text, flags=re.I)
    if not re.search(r'(?<!\w)'+re.escape(clean(identity_name))+r'(?!\w)',clean(identity_text)):
        raise ValueError('Company identity was not found on the official source')
    return page


def normalized_name(value):
    return re.sub(r'[^\w]+', '', normalize(value))


def guard(c, prospect, exclude_mid=None):
    """One prospect introduction per address, across drafts and campaign history."""
    recipient = canonical(prospect['recipient'])
    # Serializes every introduction for this destination even before a row exists.
    c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,73102))', (recipient,))
    if prospect.get('status') == 'stopped' or c.execute("SELECT 1 FROM marketing_suppressions WHERE channel='email' AND LOWER(recipient)=%s", (recipient,)).fetchone():
        raise HTTPException(409, 'Recipient has stopped email contact')
    names = {normalized_name(prospect['company_name']), normalized_name(prospect['identity_name'])}
    # Existing directories contain current customers and mixed legacy leads. Both
    # require review instead of treating missing customer labels as permission.
    existing = c.execute('''SELECT name AS company_name,email,domain FROM accounts
        UNION ALL SELECT company_name,email,NULL AS domain FROM customer_directory''').fetchall()
    domain = recipient.rsplit('@',1)[1]
    for item in existing:
        prior_email = address(item.get('email'))
        prior_domain = prior_email.rsplit('@',1)[1] if prior_email else None
        raw_domain = str(item.get('domain') or '').strip()
        try:other_domain = (urlsplit(raw_domain if '://' in raw_domain else '//'+raw_domain).hostname or '').lower().removeprefix('www.')
        except ValueError:other_domain = ''
        if (prior_email == recipient or prior_domain == domain or normalized_name(item['company_name']) in names
                or other_domain == domain):
            raise HTTPException(409, 'Existing CRM company/customer requires review; introduction blocked')
    if c.execute("SELECT 1 FROM customer_campaign_recipients WHERE channel='email' AND LOWER(recipient)=%s LIMIT 1", (recipient,)).fetchone():
        raise HTTPException(409, 'Recipient already appears in a customer campaign')
    if c.execute('''SELECT 1 FROM outbound_messages WHERE channel='email' AND LOWER(recipient)=%s
        AND id<>%s AND status<>'rejected' LIMIT 1''', (recipient, exclude_mid or 0)).fetchone():
        raise HTTPException(409, 'Recipient already has an outbound contact record')
    if c.execute('SELECT 1 FROM sales_prospects WHERE LOWER(recipient)=%s AND id<>%s', (recipient, prospect.get('id') or 0)).fetchone():
        raise HTTPException(409, 'Recipient already has a prospect record')


def campaign_duplicate(c, recipient):
    """Keep this manual prospect flow out of pre-existing customer campaigns."""
    email = address(recipient)
    if not email:
        return False
    c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,73102))', (email,))
    return bool(c.execute('SELECT 1 FROM sales_prospects WHERE recipient=%s', (email,)).fetchone())


def ensure_reply_allowed(c, prospect_id, uid):
    p = c.execute('SELECT * FROM sales_prospects WHERE id=%s FOR UPDATE', (prospect_id,)).fetchone()
    if not p or p['mail_user_id'] != uid:
        raise HTTPException(403, 'Prospect mailbox ownership mismatch')
    if p['status'] == 'stopped' or c.execute("SELECT 1 FROM marketing_suppressions WHERE channel='email' AND LOWER(recipient)=%s", (p['recipient'],)).fetchone():
        raise HTTPException(409, 'Recipient has stopped email contact')
    return p


def validate_intro(c, m, uid, verify=True):
    if m.get('purpose') != 'intro_prospect' or m.get('opportunity_id') or m.get('reply_inbox_id') or not m.get('prospect_id'):
        raise HTTPException(409, 'Prospect introduction identity mismatch')
    p = ensure_reply_allowed(c, m['prospect_id'], uid)
    if (m.get('mail_user_id') != uid or m.get('recipient') != p['recipient'] or p['source_email'] != p['recipient']
            or p['exclusion_basis'] != EXCLUSION or m.get('proposal_text')):
        raise HTTPException(409, 'Prospect introduction source/recipient mismatch')
    guard(c, p, m['id'])
    if verify:
        try:
            verify_source(p['source_url'], p['recipient'], p['identity_name'])
        except Exception as exc:
            raise HTTPException(409, 'Official source could not be reverified: '+str(exc)[:200]) from None
    return p


def content_digest(m):
    fields = ('purpose','prospect_id','opportunity_id','reply_inbox_id','mail_user_id','recipient','subject','body','proposal_text')
    return hashlib.sha256(json.dumps({k:m.get(k) for k in fields}, sort_keys=True, ensure_ascii=False, separators=(',',':')).encode()).hexdigest()


def create_draft(data, session):
    require_owner(session)
    recipient = canonical(data.get('recipient'))
    from app.spacemail import connection
    selected = connection(session['user_id'])
    if not selected or selected.get('status') != 'connected':
        raise HTTPException(409, 'Official mailbox is not connected')
    company = str(data.get('company_name') or '').strip()
    identity = str(data.get('identity_name') or '').strip()
    subject = str(data.get('subject') or '').strip()
    body = str(data.get('body') or '')
    if not 4 <= len(company) <= 300 or not subject or len(subject)>1000 or any(x in subject for x in '\r\n') or not body.strip() or len(body)>32000:
        raise HTTPException(400, 'Company, subject and introduction text are required')
    if (data.get('official_source_confirmed') != 'yes' or data.get('customer_exclusion_confirmed') != 'yes'
            or data.get('exclusion_basis') != EXCLUSION or data.get('confidence') not in ('exact_legal','verified_brand_alias')):
        raise HTTPException(400, 'Official identity and existing-customer exclusion must be reviewed')
    p = {'company_name':company, 'identity_name':identity, 'recipient':recipient,
         'source_url':str(data.get('source_url') or '').strip()}
    with db() as c:
        guard(c, p)
    try:
        verify_source(p['source_url'], recipient, identity)
    except Exception as exc:
        raise HTTPException(409, 'Official source could not be verified: '+str(exc)[:200]) from None
    now = utcnow()
    with db() as c:
        guard(c, p)
        pid = c.execute('''INSERT INTO sales_prospects(company_name,recipient,mail_user_id,source_url,source_email,
            identity_name,confidence,verified_at,exclusion_basis,created_by,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            (company,recipient,session['user_id'],p['source_url'],recipient,identity,data['confidence'],now,EXCLUSION,session['user_id'],now,now)).fetchone()['id']
        mid = c.execute('''INSERT INTO outbound_messages(prospect_id,purpose,channel,recipient,subject,body,proposal_text,
            status,created_by,mail_user_id,created_at,updated_at) VALUES(%s,'intro_prospect','email',%s,%s,%s,'','draft',%s,%s,%s,%s) RETURNING id''',
            (pid,recipient,subject,body,session['user_id'],session['user_id'],now,now)).fetchone()['id']
        c.execute('INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at) VALUES(%s,%s,%s,%s,%s,%s)',
                  (session['user_id'],'create_prospect_intro','outbound_message',mid,'Reviewed public company identity; prospect only; draft not sent',now))
    return mid


def stop_requested(body):
    # Inspect only the first authored command, never quoted introductory footers.
    opening = ''
    for line in str(body or '').splitlines():
        text = line.strip()
        if text.startswith('>') or re.match(r'(?i)^(on .+wrote:|from:|-----original|في .+كتب)', text):
            break
        candidate = normalize(text).strip(' .!؟،:;«»"')
        if not candidate or candidate in ('السلام عليكم','مرحبا','hello','hi'):
            continue
        opening = candidate
        break
    command = (r'(?:ايقاف|stop|unsubscribe|remove me|please (?:stop|unsubscribe)'
               r'|(?:please )?stop (?:emailing|contacting|sending (?:emails?|messages?) to) (?:me|us)'
               r'|(?:please )?remove (?:me|us) from your (?:mailing|email) list'
               r'|لا ترسلوا(?: لي| لنا)? رسائل(?: اخري)?|(?:الرجاء|يرجى) ايقاف الرسائل)')
    return bool(re.fullmatch(command, opening))


def ingest_reply(c, item, match):
    pid = match.get('prospect_id')
    if not pid:
        return
    p = c.execute('SELECT * FROM sales_prospects WHERE id=%s FOR UPDATE', (pid,)).fetchone()
    if not p or p['mail_user_id'] != item['user_id'] or p['recipient'] != item.get('manual_reply_address'):
        return
    stopped = stop_requested(item.get('body'))
    if stopped:
        c.execute("INSERT INTO marketing_suppressions(channel,recipient,created_at) VALUES('email',%s,%s) ON CONFLICT DO NOTHING", (p['recipient'],utcnow()))
        c.execute("UPDATE spacemail_inbox SET reply_address=NULL WHERE id=%s", (item['id'],))
    c.execute("UPDATE sales_prospects SET status=%s,updated_at=%s WHERE id=%s AND status<>'stopped'", ('stopped' if stopped else 'replied',utcnow(),pid))


def is_prospect_sender(c, uid, sender):
    return bool(c.execute('SELECT 1 FROM sales_prospects WHERE mail_user_id=%s AND recipient=%s', (uid,address(sender))).fetchone())


@router.get('/sales-prospects', response_class=HTMLResponse)
def home(request: Request):
    s = admin(request)
    from app.outbound import shell, esc, nav
    from app.social_publishing import hidden_csrf
    data = rows('SELECT id,company_name,recipient,status FROM sales_prospects WHERE mail_user_id=? ORDER BY id DESC', (s['user_id'],))
    listing = ''.join('<p><a href="/sales-prospects/'+str(p['id'])+'">'+esc(p['company_name'])+'</a> · '+esc(p['recipient'])+' · '+esc(p['status'])+'</p>' for p in data)
    form = '''<form method="post" action="/sales-prospects/create">'''+hidden_csrf(s)+'''
        <input name="company_name" placeholder="اسم الشركة القانوني" required maxlength="300">
        <input name="recipient" type="email" placeholder="البريد المنشور الرسمي" required>
        <input name="source_url" type="url" placeholder="رابط صفحة الاتصال الرسمية HTTPS" required>
        <input name="identity_name" placeholder="اسم الشركة أو العلامة الظاهر حرفيًا في المصدر" required>
        <select name="confidence"><option value="exact_legal">مطابقة قانونية مؤكدة</option><option value="verified_brand_alias">مطابقة علامة تجارية راجعتها</option></select>
        <label><input style="width:auto" type="checkbox" name="official_source_confirmed" value="yes" required>راجعت هوية الشركة وأن الرابط مصدرها الرسمي</label>
        <label><input style="width:auto" type="checkbox" name="customer_exclusion_confirmed" value="yes" required>تحققت أن الشركة ليست من عملاء آفاق الحاليين، بما يشمل المعلومات خارج النظام</label>
        <input type="hidden" name="exclusion_basis" value="owner_confirmed_not_current_customer">
        <input name="subject" placeholder="عنوان رسالة التعريف للمراجعة" required maxlength="1000">
        <textarea name="body" placeholder="نص التعريف فقط؛ لا تفترض وجود طلب خدمة أو تضع سعرًا" required maxlength="32000"></textarea>
        <button class="btn">تحقق وحفظ مسودة فقط</button></form>'''
    return HTMLResponse(shell('العملاء المحتملون',nav()+'<h1>التعريف بالعملاء المحتملين</h1><div class="card">هذه الجهات ليست طلبات خدمة مؤكدة. مصدر البريد والهوية يخضعان للتحقق، ثم موافقة على المستلم والنص قبل إرسال منفرد من البريد الرسمي. لا تُنشأ جدولة أو حملة تلقائية.</div><div class="card">'+listing+'</div><div class="card">'+form+'</div>'),headers={'Cache-Control':'no-store'})


@router.post('/sales-prospects/create')
async def create(request: Request):
    s = admin(request)
    from app.outbound import checked_form
    data = await checked_form(request,s)
    mid = await run_in_threadpool(create_draft,data,s)
    return RedirectResponse('/outbound/'+str(mid),303)


@router.get('/sales-prospects/{pid}',response_class=HTMLResponse)
def detail(pid:int,request:Request):
    s = admin(request)
    from app.outbound import shell, esc, nav
    from app.social_publishing import hidden_csrf
    p = one('SELECT * FROM sales_prospects WHERE id=? AND mail_user_id=?',(pid,s['user_id']))
    if not p:
        raise HTTPException(404)
    messages = rows('SELECT id,purpose,status,provider,sent_at,provider_message_id FROM outbound_messages WHERE prospect_id=? AND mail_user_id=? ORDER BY id',(pid,s['user_id']))
    listing = ''.join('<p><a href="/outbound/'+str(m['id'])+'">'+esc(m['purpose'])+'</a> · '+esc(m['status'])+(' · قبل مزود البريد الرسالة؛ التسليم غير مؤكد' if m['status']=='sent' else '')+'</p>' for m in messages)
    body = nav()+'<h1>'+esc(p['company_name'])+'</h1><div class="card"><p>عميل محتمل؛ الرد أو التحويل لا يثبت طلب خدمة</p><p>'+esc(p['recipient'])+' · '+esc(p['status'])+'</p><p>مصدر البريد: <a href="'+esc(p['source_url'])+'" rel="noreferrer">'+esc(p['source_url'])+'</a></p><p>الهوية: '+esc(p['identity_name'])+' · '+esc(p['confidence'])+' · تحقق: '+esc(p['verified_at'])+'</p><p>استبعاد العملاء: إقرار مراجعة القائمة + فحص سجل النظام قبل المسودة والإرسال</p>'+listing+'<a href="/official-inbox">مراجعة الردود في الوارد الرسمي</a></div>'
    body += '<div class="card"><form method="post" action="/sales-prospects/'+str(pid)+'/qualification">'+hidden_csrf(s)+'<label>احتياج ذكره العميل فعليًا، مع الوحدة والمسار والنطاق</label><textarea name="needs" maxlength="10000">'+esc(p.get('needs'))+'</textarea><label>سعر أو نطاق شاركه العميل طوعًا فقط، ووحدته وشروطه وشمول الضريبة</label><textarea name="voluntary_rate_notes" maxlength="10000">'+esc(p.get('voluntary_rate_notes'))+'</textarea><p>لا تُطلب عقود المنافسين أو بيانات سرية؛ لا يتحول السجل تلقائيًا إلى طلب أو عرض ملزم</p><button class="btn">حفظ المراجعة الداخلية</button></form></div>'
    return HTMLResponse(shell('عميل محتمل',body),headers={'Cache-Control':'no-store'})


@router.post('/sales-prospects/{pid}/qualification')
async def qualification(pid:int,request:Request):
    s = admin(request)
    from app.outbound import checked_form
    d = await checked_form(request,s)
    if len(d.get('needs',''))>10000 or len(d.get('voluntary_rate_notes',''))>10000:
        raise HTTPException(400)
    with db() as c:
        p = c.execute('SELECT * FROM sales_prospects WHERE id=%s AND mail_user_id=%s FOR UPDATE',(pid,s['user_id'])).fetchone()
        if not p:
            raise HTTPException(404)
        if p['status'] != 'replied':
            raise HTTPException(409,'Qualification requires an actual linked reply')
        c.execute('UPDATE sales_prospects SET needs=%s,voluntary_rate_notes=%s,updated_at=%s WHERE id=%s',(d.get('needs',''),d.get('voluntary_rate_notes',''),utcnow(),pid))
    return RedirectResponse('/sales-prospects/'+str(pid),303)
