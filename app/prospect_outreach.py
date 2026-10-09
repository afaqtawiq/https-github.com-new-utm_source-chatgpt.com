"""Reviewed one-time neutral outreach to verified companies, never buying requests.

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
RECORD_DERIVED = 'server_record_classification'
LEGACY_EXCLUSION = 'owner_confirmed_not_current_customer'  # Historical rows only, never fresh evidence.
# Shared hosting never proves two addresses belong to the same company.
SHARED_MAIL_DOMAINS = frozenset({'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com',
                               'live.com', 'yahoo.com', 'icloud.com', 'aol.com', 'proton.me', 'protonmail.com'})
CURRENT_STATUSES = frozenset({'customer', 'current_customer', 'active_customer', 'عميل', 'عميل حالي'})
PROSPECT_STATUSES = frozenset({'lead', 'prospect', 'new', 'جديد', 'عميل محتمل'})
WITHDRAWN_STATUSES = frozenset({'stopped', 'withdrawn', 'unsubscribed', 'do_not_contact', 'ايقاف', 'منسحب'})
RELATIONSHIP_LABELS = {'current': 'عميل حالي بحسب السجل', 'prospect': 'جهة محتملة بحسب السجل',
                       'unknown': 'العلاقة غير معروفة من السجلات'}


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
        c.execute("ALTER TABLE sales_prospects ADD COLUMN IF NOT EXISTS relationship_classification TEXT NOT NULL DEFAULT 'unknown'")
        c.execute("ALTER TABLE sales_prospects ADD COLUMN IF NOT EXISTS relationship_evidence TEXT NOT NULL DEFAULT '[]'")
        c.execute('ALTER TABLE sales_prospects ADD COLUMN IF NOT EXISTS relationship_checked_at TIMESTAMPTZ')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS sales_prospect_email_once ON sales_prospects(LOWER(recipient))')
        c.execute('ALTER TABLE outbound_messages ADD COLUMN IF NOT EXISTS prospect_id BIGINT REFERENCES sales_prospects(id)')
        c.execute("ALTER TABLE outbound_messages ADD COLUMN IF NOT EXISTS purpose TEXT NOT NULL DEFAULT 'public_request'")
        c.execute('ALTER TABLE outbound_messages ADD COLUMN IF NOT EXISTS approval_digest TEXT')
        c.execute('ALTER TABLE outbound_messages ADD COLUMN IF NOT EXISTS source_identity_digest TEXT')
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
    if domain not in SHARED_MAIL_DOMAINS and source_host != domain and not source_host.endswith('.' + domain):
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


def status_key(value):
    return normalize(str(value or '')).strip().lower()


def is_withdrawn(value):
    return status_key(value) in WITHDRAWN_STATUSES


def source_identity_digest(prospect):
    fields = ('company_name', 'recipient', 'source_url', 'source_email', 'identity_name', 'confidence')
    return hashlib.sha256(json.dumps({k: prospect.get(k) for k in fields}, sort_keys=True,
                                    ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def record_match(item, prospect):
    """Match an exact mailbox/name or a non-shared company domain, never Gmail alone."""
    recipient = canonical(prospect['recipient'])
    names = {normalized_name(prospect['company_name']), normalized_name(prospect['identity_name'])} - {''}
    prior_email = address(item.get('email'))
    if prior_email == recipient:
        return 'email'
    if normalized_name(item.get('company_name')) in names:
        return 'company_name'
    domain = recipient.rsplit('@', 1)[1]
    if domain in SHARED_MAIL_DOMAINS:
        return None
    prior_domain = prior_email.rsplit('@', 1)[1] if prior_email else None
    raw_domain = str(item.get('domain') or '').strip()
    try:
        other_domain = (urlsplit(raw_domain if '://' in raw_domain else '//'+raw_domain).hostname or '').lower().removeprefix('www.')
    except ValueError:
        other_domain = ''
    if prior_domain == domain or other_domain == domain:
        return 'company_domain'
    return None


def classify_relationship(c, prospect):
    """Only explicit account statuses establish a relationship; directories are mixed."""
    existing = c.execute('''SELECT 'account' AS source,id,name AS company_name,email,domain,status FROM accounts
        UNION ALL SELECT 'directory',id,company_name,email,NULL AS domain,NULL AS status FROM customer_directory''').fetchall()
    evidence, statuses = [], set()
    for item in existing:
        matched_by = record_match(item, prospect)
        if not matched_by:
            continue
        status = status_key(item.get('status'))
        evidence.append({'source': item['source'], 'id': item['id'], 'matched_by': matched_by, 'status': status or None})
        if item['source'] == 'account':
            if is_withdrawn(status):
                raise HTTPException(409, 'Recipient contact permission is stopped or withdrawn in CRM')
            statuses.add(status)
    if statuses & CURRENT_STATUSES:
        relationship = 'current'
    elif statuses and statuses <= PROSPECT_STATUSES:
        relationship = 'prospect'
    else:
        relationship = 'unknown'
    return relationship, evidence


def refresh_relationship(c, prospect):
    relationship, evidence = classify_relationship(c, prospect)
    checked_at = utcnow()
    c.execute('''UPDATE sales_prospects SET relationship_classification=%s,relationship_evidence=%s,
        relationship_checked_at=%s WHERE id=%s''',
        (relationship, json.dumps(evidence, ensure_ascii=False, sort_keys=True), checked_at, prospect['id']))
    prospect.update(relationship_classification=relationship, relationship_evidence=json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                    relationship_checked_at=checked_at)
    return prospect


def guard(c, prospect, exclude_mid=None):
    """One neutral introduction per exact address across drafts and campaign history."""
    recipient = canonical(prospect['recipient'])
    # Serializes every introduction for this destination even before a row exists.
    c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,73102))', (recipient,))
    if is_withdrawn(prospect.get('status')) or c.execute("SELECT 1 FROM marketing_suppressions WHERE channel='email' AND LOWER(recipient)=%s", (recipient,)).fetchone():
        raise HTTPException(409, 'Recipient has stopped or withdrawn email contact')
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
    if is_withdrawn(p['status']) or c.execute("SELECT 1 FROM marketing_suppressions WHERE channel='email' AND LOWER(recipient)=%s", (p['recipient'],)).fetchone():
        raise HTTPException(409, 'Recipient has stopped email contact')
    return p


def validate_intro(c, m, uid, verify=True):
    if m.get('purpose') != 'intro_prospect' or m.get('opportunity_id') or m.get('reply_inbox_id') or not m.get('prospect_id'):
        raise HTTPException(409, 'Prospect introduction identity mismatch')
    p = ensure_reply_allowed(c, m['prospect_id'], uid)
    if (m.get('mail_user_id') != uid or m.get('recipient') != p['recipient'] or p['source_email'] != p['recipient']
            or m.get('proposal_text')):
        raise HTTPException(409, 'Prospect introduction source/recipient mismatch')
    # Keep legacy historical assertions as history, never use them as evidence.
    if m.get('source_identity_digest'):
        if m['source_identity_digest'] != source_identity_digest(p):
            raise HTTPException(409, 'Prospect introduction source identity changed')
    elif p.get('exclusion_basis') != LEGACY_EXCLUSION:
        raise HTTPException(409, 'Prospect introduction source identity snapshot missing')
    guard(c, p, m['id'])
    if verify:
        try:
            verify_source(p['source_url'], p['recipient'], p['identity_name'])
        except Exception as exc:
            raise HTTPException(409, 'Official source could not be reverified: '+str(exc)[:200]) from None
    # Re-read CRM after any network lookup, directly before the send claim.
    refresh_relationship(c, p)
    return p


def content_digest(m):
    fields = ('purpose','prospect_id','opportunity_id','reply_inbox_id','mail_user_id','recipient','subject','body','proposal_text')
    # Null is the exact legacy digest format; new source snapshots are approved too.
    if m.get('source_identity_digest') is not None:
        fields += ('source_identity_digest',)
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
    if data.get('official_source_confirmed') != 'yes' or data.get('confidence') not in ('exact_legal','verified_brand_alias'):
        raise HTTPException(400, 'Official company identity must be reviewed')
    p = {'company_name':company, 'identity_name':identity, 'recipient':recipient,
         'source_url':str(data.get('source_url') or '').strip(), 'source_email': recipient, 'confidence': data['confidence']}
    with db() as c:
        guard(c, p)
        classify_relationship(c, p)
    try:
        verify_source(p['source_url'], recipient, identity)
    except Exception as exc:
        raise HTTPException(409, 'Official source could not be verified: '+str(exc)[:200]) from None
    now = utcnow()
    with db() as c:
        guard(c, p)
        relationship, evidence = classify_relationship(c, p)
        pid = c.execute('''INSERT INTO sales_prospects(company_name,recipient,mail_user_id,source_url,source_email,
            identity_name,confidence,verified_at,exclusion_basis,created_by,created_at,updated_at,
            relationship_classification,relationship_evidence,relationship_checked_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            (company,recipient,session['user_id'],p['source_url'],recipient,identity,data['confidence'],now,RECORD_DERIVED,session['user_id'],now,now,
             relationship,json.dumps(evidence,ensure_ascii=False,sort_keys=True),now)).fetchone()['id']
        mid = c.execute('''INSERT INTO outbound_messages(prospect_id,purpose,channel,recipient,subject,body,proposal_text,
            status,created_by,mail_user_id,created_at,updated_at,source_identity_digest) VALUES(%s,'intro_prospect','email',%s,%s,%s,'','draft',%s,%s,%s,%s,%s) RETURNING id''',
            (pid,recipient,subject,body,session['user_id'],session['user_id'],now,now,source_identity_digest(p))).fetchone()['id']
        c.execute('INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at) VALUES(%s,%s,%s,%s,%s,%s)',
                  (session['user_id'],'create_prospect_intro','outbound_message',mid,'Reviewed public company identity; record relationship: '+relationship+'; neutral outreach draft not sent',now))
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
    if is_withdrawn(p['status']):
        return
    stopped = stop_requested(item.get('body'))
    if stopped:
        c.execute("INSERT INTO marketing_suppressions(channel,recipient,created_at) VALUES('email',%s,%s) ON CONFLICT DO NOTHING", (p['recipient'],utcnow()))
        c.execute("UPDATE spacemail_inbox SET reply_address=NULL WHERE id=%s", (item['id'],))
    c.execute("UPDATE sales_prospects SET status=%s,updated_at=%s WHERE id=%s AND NOT (status=ANY(%s))", ('stopped' if stopped else 'replied',utcnow(),pid,sorted(WITHDRAWN_STATUSES)))


def is_prospect_sender(c, uid, sender):
    return bool(c.execute('SELECT 1 FROM sales_prospects WHERE mail_user_id=%s AND recipient=%s', (uid,address(sender))).fetchone())


@router.get('/sales-prospects', response_class=HTMLResponse)
def home(request: Request):
    s = admin(request)
    from app.outbound import shell, esc, nav
    from app.social_publishing import hidden_csrf
    data = rows('SELECT id,company_name,recipient,status,relationship_classification FROM sales_prospects WHERE mail_user_id=? ORDER BY id DESC', (s['user_id'],))
    listing = ''.join('<p><a href="/sales-prospects/'+str(p['id'])+'">'+esc(p['company_name'])+'</a> · '+esc(p['recipient'])+' · '+esc(p['status'])+' · '+esc(RELATIONSHIP_LABELS.get(p['relationship_classification'],RELATIONSHIP_LABELS['unknown']))+'</p>' for p in data)
    form = '''<form method="post" action="/sales-prospects/create">'''+hidden_csrf(s)+'''
        <input name="company_name" placeholder="اسم الشركة القانوني" required maxlength="300">
        <input name="recipient" type="email" placeholder="البريد المنشور الرسمي" required>
        <input name="source_url" type="url" placeholder="رابط صفحة الاتصال الرسمية HTTPS" required>
        <input name="identity_name" placeholder="اسم الشركة أو العلامة الظاهر حرفيًا في المصدر" required>
        <select name="confidence"><option value="exact_legal">مطابقة قانونية مؤكدة</option><option value="verified_brand_alias">مطابقة علامة تجارية راجعتها</option></select>
        <label><input style="width:auto" type="checkbox" name="official_source_confirmed" value="yes" required>راجعت هوية الشركة وأن الرابط مصدرها الرسمي</label>
        <p>يصنّف النظام العلاقة من سجلاته: عميل حالي، جهة محتملة، أو علاقة غير معروفة. غياب السجل لا يثبت أن الجهة عميل جديد. يُعاد الفحص قبل الإرسال.</p>
        <input name="subject" placeholder="عنوان رسالة التعريف للمراجعة" required maxlength="1000">
        <textarea name="body" placeholder="نص محايد للتعريف بالخدمات؛ لا تفترض علاقة سابقة أو جديدة أو طلب خدمة أو سعرًا" required maxlength="32000"></textarea>
        <button class="btn">تحقق وحفظ مسودة فقط</button></form>'''
    return HTMLResponse(shell('التواصل التعريفي',nav()+'<h1>التواصل التعريفي مع الشركات</h1><div class="card">هذه الجهات ليست طلبات خدمة مؤكدة. مصدر البريد والهوية يخضعان للتحقق، ثم موافقة على المستلم والنص قبل إرسال منفرد من البريد الرسمي. لا تُنشأ جدولة أو حملة تلقائية.</div><div class="card">'+listing+'</div><div class="card">'+form+'</div>'),headers={'Cache-Control':'no-store'})


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
    body = nav()+'<h1>'+esc(p['company_name'])+'</h1><div class="card"><p>تواصل تعريفي؛ الرد أو التحويل لا يثبت طلب خدمة</p><p>العلاقة: '+esc(RELATIONSHIP_LABELS.get(p.get('relationship_classification'),RELATIONSHIP_LABELS['unknown']))+'</p><p>'+esc(p['recipient'])+' · '+esc(p['status'])+'</p><p>مصدر البريد: <a href="'+esc(p['source_url'])+'" rel="noreferrer">'+esc(p['source_url'])+'</a></p><p>الهوية: '+esc(p['identity_name'])+' · '+esc(p['confidence'])+' · تحقق: '+esc(p['verified_at'])+'</p><p>آخر فحص للسجلات: '+esc(p.get('relationship_checked_at') or 'لم يُفحص بعد؛ يُفحص عند المراجعة والإرسال')+'</p><p>التصنيف بحسب سجلات النظام فقط؛ لا يثبت غياب العلاقة خارج النظام. النص التعريفي محايد، ويُعاد الفحص قبل الإرسال.</p>'+listing+'<a href="/official-inbox">مراجعة الردود في الوارد الرسمي</a></div>'
    body += '<div class="card"><form method="post" action="/sales-prospects/'+str(pid)+'/qualification">'+hidden_csrf(s)+'<label>احتياج ذكره العميل فعليًا، مع الوحدة والمسار والنطاق</label><textarea name="needs" maxlength="10000">'+esc(p.get('needs'))+'</textarea><label>سعر أو نطاق شاركه العميل طوعًا فقط، ووحدته وشروطه وشمول الضريبة</label><textarea name="voluntary_rate_notes" maxlength="10000">'+esc(p.get('voluntary_rate_notes'))+'</textarea><p>لا تُطلب عقود المنافسين أو بيانات سرية؛ لا يتحول السجل تلقائيًا إلى طلب أو عرض ملزم</p><button class="btn">حفظ المراجعة الداخلية</button></form></div>'
    return HTMLResponse(shell('تواصل تعريفي',body),headers={'Cache-Control':'no-store'})


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
