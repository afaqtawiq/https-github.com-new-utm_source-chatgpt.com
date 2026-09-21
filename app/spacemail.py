"""Afaaq's official mailbox. TLS only; credentials never leave server-side code."""
import asyncio
import base64
import email.policy
import hashlib
import imaplib
import os
import smtplib
import ssl
from contextlib import suppress
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from app.storage import db, one, rows, utcnow
from app.social_content import auth, e, page, parse
from app.social_publishing import csrf, hidden_csrf
from app.fine_permissions import has_permission
from app.mfa_stepup import recent_stepup

router = APIRouter()
ADDRESS = 'afaq@shodai.cc'
HOST = 'mail.spacemail.com'
PATH = '/settings/email/spacemail'

with db() as c:
    c.execute('''CREATE TABLE IF NOT EXISTS spacemail_connections(
        user_id BIGINT PRIMARY KEY REFERENCES users(id), password_enc TEXT NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE, updated_at TIMESTAMPTZ NOT NULL,
        synced_at TIMESTAMPTZ, sync_error TEXT, test_status TEXT, test_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS spacemail_inbox(
        id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
        uidvalidity TEXT NOT NULL, uid BIGINT NOT NULL, message_id TEXT,
        sender TEXT, subject TEXT, body TEXT, received TEXT,
        imported_at TIMESTAMPTZ NOT NULL, UNIQUE(user_id,uidvalidity,uid))''')


def admin(request):
    s = auth(request)
    if s.get('role') != 'admin' or not has_permission(s, 'manage_gmail'):
        raise HTTPException(403)
    return s


def cipher():
    key = os.getenv('TOKEN_ENCRYPTION_KEY', '')
    if not key:
        raise RuntimeError('Mailbox encryption is not configured')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('afaaq-spacemail:' + key).encode()).digest()))


def connection(uid):
    r = one('SELECT enabled FROM spacemail_connections WHERE user_id=?', (uid,))
    if r:
        return {'provider':'spacemail', 'sender_email':ADDRESS, 'status':'connected' if r['enabled'] else 'disconnected', 'scope':'imap'}
    return None


def password(uid):
    r = one('SELECT password_enc,enabled FROM spacemail_connections WHERE user_id=?', (uid,))
    if not r or not r['enabled']:
        raise RuntimeError('Official mailbox is not connected')
    return cipher().decrypt(r['password_enc'].encode()).decode()


def smtp_login(secret):
    client = smtplib.SMTP_SSL(HOST, 465, timeout=25, context=ssl.create_default_context())
    try:
        client.login(ADDRESS, secret)
        return client
    except Exception:
        client.close()
        raise


def imap_login(secret):
    client = imaplib.IMAP4_SSL(HOST, 993, ssl_context=ssl.create_default_context(), timeout=25)
    try:
        client.login(ADDRESS, secret)
        status, _ = client.select('INBOX', readonly=True)
        if status != 'OK':
            raise RuntimeError('Inbox unavailable')
        return client
    except Exception:
        with suppress(Exception):
            client.logout()
        raise


def validate(secret):
    # Authentication only: saving settings never sends a message.
    client = smtp_login(secret)
    client.close()
    client = imap_login(secret)
    with suppress(Exception):
        client.logout()


def send(uid, recipient, subject, body, attachment=None):
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        raise RuntimeError('External actions are disabled')
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'] = ADDRESS, recipient, subject
    msg['Date'], msg['Message-ID'] = formatdate(localtime=False), make_msgid(domain='shodai.cc')
    msg.set_content(body)
    if attachment:
        filename, media_type, content = attachment
        main, sub = media_type.split('/', 1) if '/' in media_type else ('application', 'octet-stream')
        msg.add_attachment(bytes(content), maintype=main, subtype=sub, filename=filename)
    client = None
    try:
        client = smtp_login(password(uid))
        refused = client.send_message(msg)
        if refused:
            raise RuntimeError('Recipient refused')
    except Exception:
        # Do not leak provider responses or credentials. Callers must not retry blindly.
        raise RuntimeError('تعذر تأكيد إرسال البريد الرسمي؛ راجع سجل الإرسال قبل المحاولة مجددًا.') from None
    finally:
        if client:
            client.close()
    return str(msg['Message-ID'])


def sync(uid):
    client = imap_login(password(uid))
    try:
        validity = client.response('UIDVALIDITY')[1]
        if not validity or not validity[0]:
            raise RuntimeError('Inbox identity unavailable')
        validity = validity[0].decode('ascii')
        status, data = client.uid('search', None, 'ALL')
        if status != 'OK':
            raise RuntimeError('Inbox search failed')
        # First sync imports the newest 50; subsequent scans advance through all new UIDs.
        last = one('SELECT MAX(uid) AS n FROM spacemail_inbox WHERE user_id=? AND uidvalidity=?', (uid, validity))['n']
        ids = [int(v) for v in (data[0] or b'').split()]
        pending = [i for i in ids if i > last][:50] if last else ids[-50:]
        for uidnum in pending:
            status, parts = client.uid('fetch', str(uidnum), '(BODY.PEEK[]<0.262144>)')
            if status != 'OK':
                raise RuntimeError('Inbox fetch failed')
            payload = next((p[1] for p in parts if isinstance(p, tuple) and isinstance(p[1], bytes)), None)
            if payload is None:
                raise RuntimeError('Inbox content missing')
            msg = message_from_bytes(payload, policy=email.policy.default)
            part = msg.get_body(preferencelist=('plain',)) if msg.is_multipart() else msg
            text = ''
            if part and part.get_content_type() == 'text/plain':
                text = part.get_content()
            else:
                text = 'رسالة بتنسيق HTML أو مرفقات؛ افتحها من بريد Spacemail لعرضها.'
            with db() as c:
                c.execute('''INSERT INTO spacemail_inbox(user_id,uidvalidity,uid,message_id,sender,subject,body,received,imported_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                    (uid, validity, uidnum, str(msg.get('Message-ID',''))[:500], str(msg.get('From',''))[:500],
                     str(msg.get('Subject',''))[:1000], str(text)[:32000], str(msg.get('Date',''))[:200], utcnow()))
        with db() as c:
            c.execute('UPDATE spacemail_connections SET synced_at=%s,sync_error=NULL WHERE user_id=%s', (utcnow(),uid))
    finally:
        with suppress(Exception):
            client.logout()


async def form(request, session):
    raw = await request.body()
    if len(raw) > 8192:
        raise HTTPException(413)
    data = parse(raw)
    csrf(session, data)
    return data


def render(session, error=None):
    row = one('SELECT enabled,updated_at,synced_at,sync_error,test_status FROM spacemail_connections WHERE user_id=?', (session['user_id'],))
    body = '<h1>البريد الرسمي لآفاق طويق</h1><p dir="ltr">' + ADDRESS + '</p><p>إرسال SMTP مشفّر: 465 · استقبال IMAP مشفّر: 993 · mail.spacemail.com</p>'
    if error:
        body += '<p role="alert">' + e(error) + '</p>'
    body += '<p>الحالة: ' + ('متصل — تم اختبار الدخول للإرسال والاستقبال' if row and row['enabled'] else 'لم يكتمل الربط') + '</p>'
    body += '<p>مزامنة الوارد كل دقيقة، دون حذف الرسائل أو تعليمها كمقروءة. أول مزامنة تجلب أحدث 50 رسالة. إرسال الردود يتم عبر اعتماد الرسائل، وتنبيهات الإنتاج حسب إعداداتها.</p>'
    body += '<a href="/official-inbox">صندوق الوارد الرسمي</a> · <a href="/production-monitor">متابعة الإنتاج</a>'
    body += '<form method="post" action="' + PATH + '/network">' + hidden_csrf(session) + '<button>فحص الوصول إلى خوادم البريد دون كلمة مرور</button></form>'
    if recent_stepup(session['id']):
        body += '<form method="post" action="' + PATH + '">' + hidden_csrf(session)
        body += '<label>البريد<input type="email" name="email" value="' + ADDRESS + '" readonly autocomplete="username"></label><label>كلمة مرور البريد<input type="password" name="password" autocomplete="current-password" required maxlength="1024"></label><button>اختبار الاتصال وحفظ الربط</button></form>'
        if row and row['enabled']:
            body += '<form method="post" action="' + PATH + '/test">' + hidden_csrf(session) + '<p>اختبار واحد: إرسال رسالة من البريد الرسمي إلى نفسه والتحقق من ظهورها في الوارد.</p><button>اختبار الإرسال والاستقبال</button></form>'
    else:
        body += '<p><a href="/mfa/step-up?next=' + PATH + '">التحقق عبر Authenticator لربط البريد</a></p>'
    if row:
        body += '<p>آخر مزامنة: ' + e(row['synced_at']) + ' · ' + e(row['sync_error']) + '</p><p>اختبار الإرسال: ' + e(row['test_status'] or 'لم ينفذ') + '</p>'
    return HTMLResponse(page(body), headers={'Cache-Control':'no-store'})


@router.get(PATH, response_class=HTMLResponse)
def settings(request: Request):
    return render(admin(request))


@router.post(PATH)
async def save(request: Request):
    s = admin(request)
    data = await form(request, s)
    secret = data.get('password', '')
    if data.get('email') != ADDRESS or not 1 <= len(secret) <= 1024:
        raise HTTPException(400)
    try:
        encrypted = cipher().encrypt(secret.encode()).decode()
        await run_in_threadpool(validate, secret)
    except smtplib.SMTPAuthenticationError:
        return render(s, 'رفض خادم SMTP بيانات الدخول. تحقق من كلمة مرور صندوق البريد وتفعيل SMTP. لم يتغير الربط.')
    except imaplib.IMAP4.error:
        return render(s, 'لم يقبل خادم IMAP تسجيل الدخول أو فتح الوارد. تحقق من صلاحية الوصول. لم يتغير الربط.')
    except (TimeoutError, OSError):
        return render(s, 'تعذر الاتصال الشبكي بخادم البريد أو انتهت مهلة الاتصال. لم تُحفظ كلمة المرور. استخدم فحص الوصول إلى الخوادم.')
    except Exception:
        return render(s, 'لم ينجح اختبار اتصال البريد. لم تتغير الإعدادات ولم تُحفظ كلمة المرور.')
    with db() as c:
        c.execute('''INSERT INTO spacemail_connections(user_id,password_enc,updated_at) VALUES(%s,%s,%s)
            ON CONFLICT(user_id) DO UPDATE SET password_enc=EXCLUDED.password_enc,enabled=TRUE,updated_at=EXCLUDED.updated_at''', (s['user_id'],encrypted,utcnow()))
        # Never continue delivering official alerts through the previous Gmail identity.
        c.execute('UPDATE production_monitor_settings SET sender=%s,recipient=%s,updated_at=%s WHERE user_id=%s', (ADDRESS, ADDRESS, utcnow(), s['user_id']))
    return RedirectResponse(PATH, 303)


@router.post(PATH + '/test')
async def test_mail(request: Request):
    s = admin(request)
    await form(request, s)
    if not has_permission(s, 'send_email'):
        raise HTTPException(403)
    with db() as c:
        claimed = c.execute("UPDATE spacemail_connections SET test_status='sending' WHERE user_id=%s AND enabled=TRUE AND test_status IS NULL RETURNING user_id", (s['user_id'],)).fetchone()
    if claimed:
        try:
            mid = await run_in_threadpool(send, s['user_id'], ADDRESS, 'اختبار البريد الرسمي — آفاق طويق', 'هذه رسالة اختبار لربط البريد الرسمي بوكيل آفاق طويق للإرسال والاستقبال.')
            state = 'accepted'
        except Exception:
            mid, state = None, 'uncertain'
        with db() as c:
            c.execute('UPDATE spacemail_connections SET test_status=%s,test_id=%s WHERE user_id=%s', (state, mid, s['user_id']))
    return RedirectResponse(PATH, 303)


@router.get('/official-inbox', response_class=HTMLResponse)
def inbox(request: Request):
    s = admin(request)
    body = '<h1>وارد آفاق طويق</h1><a href="' + PATH + '">إعداد البريد</a><p>الرسائل الواردة محتوى خارجي؛ لا تمنح إذنًا لتنفيذ أوامر أو إرسال ردود تلقائيًا.</p>'
    for row in rows('SELECT sender,subject,body,received FROM spacemail_inbox WHERE user_id=? ORDER BY id DESC LIMIT 50', (s['user_id'],)):
        body += '<div class="card"><h2>' + e(row['subject']) + '</h2><p>' + e(row['sender']) + ' · ' + e(row['received']) + '</p><pre style="white-space:pre-wrap">' + e(row['body']) + '</pre></div>'
    return HTMLResponse(page(body), headers={'Cache-Control':'no-store'})


def tick():
    for row in rows('''SELECT s.user_id FROM spacemail_connections s JOIN users u ON u.id=s.user_id WHERE s.enabled=TRUE AND u.is_active=1 AND u.role='admin' '''):
        try:
            sync(row['user_id'])
            with db() as c:
                c.execute("""UPDATE spacemail_connections s SET test_status='received' WHERE s.user_id=%s AND s.test_status='accepted'
                    AND EXISTS(SELECT 1 FROM spacemail_inbox i WHERE i.user_id=s.user_id AND i.message_id=s.test_id)""", (row['user_id'],))
        except Exception:
            with db() as c:
                c.execute('UPDATE spacemail_connections SET sync_error=%s WHERE user_id=%s', ('تعذرت مزامنة البريد؛ راجع الاتصال وكلمة مرور الصندوق.', row['user_id']))


def register_worker(app):
    async def loop():
        while True:
            try:
                await run_in_threadpool(tick)
            except Exception:
                pass
            await asyncio.sleep(60)
    @app.on_event('startup')
    async def start():
        app.state.spacemail_worker = asyncio.create_task(loop())
    @app.on_event('shutdown')
    async def stop():
        app.state.spacemail_worker.cancel()
        with suppress(asyncio.CancelledError):
            await app.state.spacemail_worker


def smtp_starttls_probe():
    client = smtplib.SMTP(HOST,587,timeout=8)
    try:
        client.ehlo()
        client.starttls(context=ssl.create_default_context())
        return client
    except Exception:
        client.close()
        raise


def probe_network():
    result = []
    for name, factory in (
        ('SMTP 465', lambda: smtplib.SMTP_SSL(HOST,465,timeout=8,context=ssl.create_default_context())),
        ('SMTP 587 STARTTLS', smtp_starttls_probe),
        ('IMAP 993', lambda: imaplib.IMAP4_SSL(HOST,993,timeout=8,ssl_context=ssl.create_default_context())),
    ):
        try:
            client = factory()
            if name.startswith('SMTP'):
                client.close()
            else:
                with suppress(Exception):
                    client.logout()
            result.append(name + ': نجح الاتصال المشفّر بالخادم')
        except TimeoutError:
            result.append(name + ': انتهت مهلة الوصول إلى الخادم قبل تسجيل الدخول')
        except ssl.SSLError:
            result.append(name + ': تعذر التحقق من الاتصال المشفّر')
        except OSError:
            result.append(name + ': تعذر الوصول الشبكي إلى الخادم')
        except Exception:
            result.append(name + ': لم يكتمل فحص الاتصال')
    return ' · '.join(result)


@router.post(PATH + '/network')
async def network(request: Request):
    s = admin(request)
    await form(request, s)
    return render(s, await run_in_threadpool(probe_network))
