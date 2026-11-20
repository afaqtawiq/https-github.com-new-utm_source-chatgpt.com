"""Durable production alerts; support messages always require separate approval."""
import asyncio
from contextlib import suppress
import datetime as dt
import json
import os
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app import gmail_oauth as mail
from app.advert_studio import origin
from app.fine_permissions import has_permission
from app.media_settings import media_admin
from app.social_content import e, page, parse
from app.social_publishing import csrf, hidden_csrf
from app.storage import db, one, rows, utcnow

router = APIRouter()
SUPPORT = 'support@fal.ai'
ACTIVE = {'running', 'rendering', 'image_submitting', 'image_pending', 'video_ready', 'video_submitting', 'video_pending'}
FAILED = {'needs_review', 'failed'}
MAIL_LABELS = {'ready':'بانتظار الإرسال', 'draft':'مسودة لم تُرسل', 'sending':'جارٍ الإرسال',
               'sent':'أُرسلت', 'uncertain':'يلزم التحقق من الإرسال', 'cancelled':'لم تعد هناك حاجة للتنبيه'}


with db() as c:
    c.execute('''CREATE TABLE IF NOT EXISTS production_monitor_settings(
        user_id BIGINT PRIMARY KEY, recipient TEXT NOT NULL, sender TEXT NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT FALSE, stall_minutes INTEGER NOT NULL,
        enabled_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_incidents(
        id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, kind TEXT NOT NULL,
        job_id BIGINT NOT NULL, event TEXT NOT NULL, job_url TEXT NOT NULL,
        title TEXT NOT NULL, detail TEXT NOT NULL, progress TEXT NOT NULL,
        recipient TEXT NOT NULL, sender TEXT NOT NULL, alert_subject TEXT NOT NULL,
        alert_body TEXT NOT NULL, alert_status TEXT NOT NULL DEFAULT 'ready',
        alert_provider_id TEXT, alert_error TEXT, support_subject TEXT NOT NULL,
        support_body TEXT NOT NULL, support_status TEXT NOT NULL DEFAULT 'draft',
        support_provider_id TEXT, support_error TEXT, resolved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL, alert_updated_at TIMESTAMPTZ NOT NULL,
        support_updated_at TIMESTAMPTZ NOT NULL, UNIQUE(user_id,kind,job_id,event))''')


def access(request):
    session = media_admin(request)
    if not has_permission(session, 'send_email'):
        raise HTTPException(403)
    return session


async def form(request, session):
    raw = await request.body()
    if len(raw) > 4096:
        raise HTTPException(413)
    data = parse(raw)
    csrf(session, data)
    return data


def sender_ready(uid, sender):
    user = one('SELECT role,is_active FROM users WHERE id=?', (uid,))
    conn = mail.connection(uid)
    return (os.getenv('ENABLE_EXTERNAL_ACTIONS') == '1' and user and user['is_active']
            and user['role'] == 'admin' and has_permission(user, 'send_email')
            and has_permission(user, 'manage_media') and conn and conn['status'] == 'connected'
            and conn['sender_email'] == sender)


def snapshot(kind, jid):
    table = 'advert_jobs' if kind == 'advert' else 'media_jobs'
    job = one('SELECT * FROM ' + table + ' WHERE id=?', (jid,))
    if not job:
        return None
    if kind == 'advert':
        steps = rows('SELECT status,receipt,updated_at FROM advert_steps WHERE job_id=? ORDER BY ordinal', (jid,))
        done = sum(s['status'] == 'complete' for s in steps)
        progress = str(done) + ' / ' + str(len(steps)) + ' مراحل مكتملة'
        changed = max([job['updated_at']] + [s['updated_at'] for s in steps])
        title = json.loads(job['plan_json'])['title']
        receipts = [s['receipt'] for s in steps if s['receipt']]
    else:
        done = int(bool(job['image_url'])) + int(bool(job['video_url']))
        progress = str(done) + ' / ' + ('2' if job['kind'] == 'video' else '1') + ' مراحل مكتملة'
        changed, title = job['updated_at'], job['title']
        receipts = [job[k] for k in ('image_receipt', 'video_receipt') if job[k]]
    ids = []
    for encoded in receipts:
        try:
            rid = json.loads(encoded).get('request_id', '')
            if re.fullmatch(r'[a-zA-Z0-9-]{1,100}', rid):
                ids.append(rid)
        except (ValueError, TypeError):
            pass
    return {**job, 'title': title, 'progress': progress, 'changed': changed,
            'request_ids': ids, 'url': origin() + ('/advert-studio/' if kind == 'advert' else '/media-studio/') + str(jid)}


def classify(job, minutes, now):
    if job['status'] in FAILED:
        return 'failed'
    if job['status'] in ACTIVE and job['changed'] <= now - dt.timedelta(minutes=minutes):
        return 'stalled'
    return None


def record(settings, kind, job, event):
    # last_error is an application-sanitized message, never a provider response body.
    detail = (job.get('last_error') or 'تحتاج المهمة مراجعة داخل الاستوديو.') if event == 'failed' else 'لم تُسجل مرحلة جديدة خلال المدة المحددة؛ قد يكون الطلب ما زال لدى المزود.'
    label = 'تعثر الإنتاج' if event == 'failed' else 'تأخر الإنتاج'
    subject = 'آفاق طويق — ' + label + ' — طلب ' + str(job['id'])
    body = label + '\n' + job['title'] + '\n' + job['progress'] + '\n' + detail + '\n\nمتابعة المهمة: ' + job['url']
    body += '\n\nلم تُعد المراقبة أي توليد مدفوع. مسودة الدعم متاحة داخل صفحة متابعة الإنتاج لاعتمادها عند الحاجة.'
    support_body = ('Hello,\n\nPlease investigate a fal.ai production request for Afaaq Tuwaiq.\n'
                    'Our integration detected: ' + event + '.\n'
                    'Application status: ' + job['status'] + '\n'
                    'Application diagnostic: ' + detail + '\n'
                    'Completed progress: ' + job['progress'] + '\n'
                    'Provider request IDs: ' + (', '.join(job['request_ids']) or 'No confirmed request ID was returned.') + '\n'
                    'Detected at (UTC): ' + utcnow().isoformat() + '\n\n'
                    'No automatic retry has been submitted by the monitor. Please advise how to resolve this without duplicate charges.\n\nThank you.')
    now = utcnow()
    with db() as c:
        c.execute('''INSERT INTO production_incidents(user_id,kind,job_id,event,job_url,title,detail,progress,
            recipient,sender,alert_subject,alert_body,support_subject,support_body,created_at,alert_updated_at,support_updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,kind,job_id,event) DO NOTHING''',
            (settings['user_id'], kind, job['id'], event, job['url'], job['title'], detail, job['progress'],
             settings['recipient'], settings['sender'], subject, body, 'Production request needs investigation — Afaaq Tuwaiq',
             support_body, now, now, now))


def scan():
    now = utcnow()
    for settings in rows('SELECT * FROM production_monitor_settings WHERE enabled=TRUE'):
        for kind, table in [('advert', 'advert_jobs'), ('media', 'media_jobs')]:
            # Follow active jobs, and failures occurring after monitoring was enabled.
            jobs = rows('SELECT id FROM ' + table + " WHERE created_by=? AND approved_at IS NOT NULL AND status!='draft' AND (status NOT IN ('needs_review','failed') OR updated_at>=?) ORDER BY updated_at DESC",
                        (settings['user_id'], settings['enabled_at']))
            for candidate in jobs:
                job = snapshot(kind, candidate['id'])
                event = classify(job, settings['stall_minutes'], now)
                if event:
                    record(settings, kind, job, event)
                with db() as c:
                    if job['status'] == 'complete':
                        c.execute('UPDATE production_incidents SET resolved_at=%s WHERE user_id=%s AND kind=%s AND job_id=%s AND resolved_at IS NULL',
                                  (now, settings['user_id'], kind, job['id']))
                    elif job['status'] in ACTIVE and event is None:
                        c.execute("UPDATE production_incidents SET resolved_at=%s WHERE user_id=%s AND kind=%s AND job_id=%s AND event='stalled' AND resolved_at IS NULL",
                                  (now, settings['user_id'], kind, job['id']))


def deliver(incident_id, *, support=False):
    field = 'support' if support else 'alert'
    with db() as c:
        item = c.execute('SELECT * FROM production_incidents WHERE id=%s FOR UPDATE', (incident_id,)).fetchone()
        if not item or item[field + '_status'] != ('draft' if support else 'ready'):
            return
        if support and item['resolved_at']:
            return
        settings = c.execute('SELECT * FROM production_monitor_settings WHERE user_id=%s FOR UPDATE', (item['user_id'],)).fetchone()
        if not settings or (not support and (not settings['enabled'] or settings['recipient'] != item['recipient'])):
            return
        if not sender_ready(item['user_id'], item['sender']):
            c.execute('UPDATE production_incidents SET ' + field + '_error=%s WHERE id=%s',
                      ('تعذر الإرسال: راجع اتصال Gmail وصلاحيات البريد وحالة الإجراءات الخارجية.', incident_id))
            return
        if not support:
            job = snapshot(item['kind'], item['job_id'])
            if not job or item['resolved_at'] or classify(job, settings['stall_minutes'], utcnow()) != item['event']:
                c.execute("UPDATE production_incidents SET alert_status='cancelled',resolved_at=%s WHERE id=%s", (utcnow(), incident_id))
                return
        c.execute('UPDATE production_incidents SET ' + field + "_status='sending'," + field + '_updated_at=%s WHERE id=%s', (utcnow(), incident_id))
    try:
        provider_id = mail.send_gmail(item['user_id'], SUPPORT if support else item['recipient'],
                                     item[field + '_subject'], item[field + '_body'])
        if not provider_id:
            raise RuntimeError('Missing receipt')
        status, error = 'sent', None
    except Exception:
        status, provider_id = 'uncertain', None
        error = 'لم يصل تأكيد إرسال. راجع مجلد الرسائل المرسلة؛ لن تُرسل نسخة أخرى تلقائيًا.'
    with db() as c:
        c.execute('UPDATE production_incidents SET ' + field + '_status=%s,' + field + '_provider_id=%s,' + field + '_error=%s,' + field + '_updated_at=%s WHERE id=%s',
                  (status, provider_id, error, utcnow(), incident_id))


def tick():
    scan()
    with db() as c:
        for field in ('alert', 'support'):
            c.execute('UPDATE production_incidents SET ' + field + "_status='uncertain'," + field + '_error=%s WHERE ' + field + "_status='sending' AND " + field + '_updated_at<%s',
                      ('انقطع تأكيد إرسال البريد؛ راجع الرسائل المرسلة قبل أي إعادة إرسال.', utcnow()-dt.timedelta(minutes=3)))
    for item in rows("""SELECT i.id FROM production_incidents i JOIN production_monitor_settings s ON s.user_id=i.user_id
        WHERE i.alert_status='ready' AND s.enabled=TRUE AND s.recipient=i.recipient AND s.sender=i.sender ORDER BY i.id LIMIT 20"""):
        deliver(item['id'])


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
        app.state.production_monitor = asyncio.create_task(loop())
    @app.on_event('shutdown')
    async def stop():
        task = getattr(app.state, 'production_monitor', None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


@router.get('/production-monitor', response_class=HTMLResponse)
def dashboard(request: Request):
    s = access(request)
    settings = one('SELECT * FROM production_monitor_settings WHERE user_id=?', (s['user_id'],))
    conn = mail.connection(s['user_id'])
    sender = conn.get('sender_email', '') if conn else ''
    body = '<div class="nav"><a href="/advert-studio">استوديو الإعلان</a><a href="/settings/email">اتصال البريد</a></div><div class="hero"><h1>متابعة الإنتاج والتنبيهات</h1><p>فحص كل دقيقة، وتنبيه واحد لكل مهمة عند التأخر وتنبيه عند الفشل. لا تعيد المراقبة التوليد المدفوع، ولا ترسل للدعم دون اعتماد.</p></div>'
    body += '<div class="card"><p>الحالة: ' + ('مفعّلة' if settings and settings['enabled'] else 'متوقفة') + '</p><p>حساب الإرسال: ' + e(sender or 'Gmail غير مربوط') + '</p>'
    body += '<p>يراقب المهام الجارية والأعطال الجديدة بعد التفعيل. يمكن توثيق مهمة متعثرة سابقة من نموذج الفحص أدناه.</p>'
    body += '<form method="post" action="/production-monitor/check-email">' + hidden_csrf(s) + '<button class="btn">فحص صلاحية اتصال البريد دون إرسال</button></form>'
    from app.mfa_stepup import recent_stepup
    if not recent_stepup(s['id']):
        body += '<a class="btn" href="/mfa/step-up?next=/production-monitor">التحقق لإدارة التنبيهات</a>'
    else:
        body += '<form method="post" action="/production-monitor/settings">' + hidden_csrf(s)
        body += '<label>بريد استلام التنبيه<input type="email" name="recipient" required value="' + e(settings['recipient'] if settings else sender) + '"></label>'
        body += '<label>مدة عدم التقدم بالدقائق<input type="number" name="minutes" min="5" max="120" value="' + str(settings['stall_minutes'] if settings else 15) + '"></label>'
        body += '<label><input type="checkbox" name="enabled" value="yes" style="width:auto"' + (' checked' if settings and settings['enabled'] else '') + '> تفعيل إرسال تنبيهات الإنتاج تلقائيًا لهذا البريد</label><button class="btn">حفظ إعدادات المتابعة</button></form>'
    body += '</div><div class="card"><h2>فحص مهمة سابقة</h2><form method="post" action="/production-monitor/check">' + hidden_csrf(s)
    body += '<select name="kind"><option value="advert">إعلان متكامل</option><option value="media">إنتاج صورة أو فيديو</option></select><label>رقم المهمة<input name="job_id" type="number" min="1" required></label><button class="btn">فحص وتسجيل التنبيه إن كانت المهمة متعثرة</button></form></div>'
    for item in rows('SELECT * FROM production_incidents WHERE user_id=? ORDER BY id DESC LIMIT 50', (s['user_id'],)):
        body += '<div class="card"><h2>' + e(item['title']) + '</h2><p>' + e(item['detail']) + '</p><p>' + e(item['progress']) + '</p>'
        body += '<p>الحالة: ' + ('انتهى سبب التنبيه' if item['resolved_at'] else 'تحتاج متابعة') + '</p><p>تنبيه البريد: ' + e(MAIL_LABELS.get(item['alert_status'], item['alert_status'])) + ' · ' + e(item['alert_error']) + '</p>'
        body += '<a class="btn" href="' + e(item['job_url']) + '">فتح المهمة</a><h3>مسودة الدعم — ' + SUPPORT + '</h3><p>' + e(item['support_subject']) + '</p><pre dir="auto" style="white-space:pre-wrap">' + e(item['support_body']) + '</pre>'
        body += '<p>إرسال الدعم: ' + e(MAIL_LABELS.get(item['support_status'], item['support_status'])) + ' · ' + e(item['support_error']) + '</p>'
        if item['support_status'] == 'draft' and not item['resolved_at']:
            if recent_stepup(s['id']):
                body += '<form method="post" action="/production-monitor/' + str(item['id']) + '/send-support">' + hidden_csrf(s)
                body += '<label><input type="checkbox" name="approve" value="yes" required style="width:auto"> أعتمد إرسال النص المعروض إلى دعم fal.ai من حساب البريد أعلاه</label><button class="btn">اعتماد وإرسال رسالة الدعم</button></form>'
            else:
                body += '<a href="/mfa/step-up?next=/production-monitor">التحقق قبل اعتماد رسالة الدعم</a>'
        body += '</div>'
    return HTMLResponse(page(body), headers={'Cache-Control': 'no-store'})


@router.post('/production-monitor/check-email', response_class=HTMLResponse)
async def check_email(request: Request):
    s = access(request)
    await form(request, s)
    # Refresh credentials only: never send a message or expose a token/error body.
    try:
        await run_in_threadpool(mail.access_token, s['user_id'])
        message = 'نجح تجديد اتصال Gmail. هذا الفحص لا يرسل رسالة ولا يؤكد تسليم التنبيهات.'
    except Exception as exc:
        error = str(exc)
        if error.startswith('Google OAuth ') and 'invalid_grant' in error:
            message = 'رفض Google تجديد الاتصال (invalid_grant). أعد ربط Gmail ثم أعد الفحص.'
        elif error.startswith('Google OAuth ') and 'invalid_client' in error:
            message = 'رفض Google إعدادات تطبيق البريد (invalid_client). يلزم إصلاح إعدادات Google OAuth.'
        elif error == 'Google OAuth is not fully configured':
            message = 'إعدادات تطبيق Google OAuth غير مكتملة.'
        elif error == 'Gmail is not connected':
            message = 'Gmail غير مربوط. اربط حساب البريد ثم أعد الفحص.'
        else:
            message = 'تعذر تجديد اتصال Gmail. يلزم مراجعة اتصال الخدمة وإعدادات الربط قبل الاعتماد على التنبيهات.'
    return HTMLResponse(page('<h1>فحص اتصال البريد</h1><p>' + e(message) + '</p><a href="/settings/email">إعداد Gmail</a> · <a href="/production-monitor">العودة للمتابعة</a>'), headers={'Cache-Control': 'no-store'})


@router.post('/production-monitor/settings')
async def save_settings(request: Request):
    s = access(request)
    data = await form(request, s)
    recipient = data.get('recipient', '').strip()
    if not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}', recipient) or len(recipient) > 254:
        raise HTTPException(400, 'أدخل بريدًا صالحًا.')
    try:
        minutes = int(data.get('minutes', '15'))
        if not 5 <= minutes <= 120:
            raise ValueError()
    except ValueError:
        raise HTTPException(400, 'مدة المراقبة من 5 إلى 120 دقيقة.') from None
    conn = mail.connection(s['user_id'])
    if not conn or conn['status'] != 'connected':
        raise HTTPException(409, 'اربط Gmail قبل تفعيل التنبيهات.')
    now = utcnow()
    with db() as c:
        c.execute('''INSERT INTO production_monitor_settings(user_id,recipient,sender,enabled,stall_minutes,enabled_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET recipient=EXCLUDED.recipient,
            sender=EXCLUDED.sender,enabled=EXCLUDED.enabled,stall_minutes=EXCLUDED.stall_minutes,
            enabled_at=CASE WHEN production_monitor_settings.enabled THEN production_monitor_settings.enabled_at ELSE EXCLUDED.enabled_at END,
            updated_at=EXCLUDED.updated_at''', (s['user_id'], recipient, conn['sender_email'], data.get('enabled') == 'yes', minutes, now, now))
        c.execute('''INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at)
            VALUES(%s,'production_monitor_configured','user',%s,%s,%s)''', (s['user_id'], s['user_id'], 'Production alert email settings updated; support requires separate approval.', now))
    return RedirectResponse('/production-monitor', 303)


@router.post('/production-monitor/check')
async def check_job(request: Request):
    s = access(request)
    data = await form(request, s)
    if data.get('kind') not in ('advert', 'media') or not re.fullmatch(r'[0-9]{1,18}', data.get('job_id', '')):
        raise HTTPException(400)
    settings = one('SELECT * FROM production_monitor_settings WHERE user_id=? AND enabled=TRUE', (s['user_id'],))
    job = snapshot(data['kind'], int(data['job_id']))
    if not settings or not job or job['created_by'] != s['user_id'] or not job['approved_at']:
        raise HTTPException(409, 'فعّل التنبيهات واختر مهمة إنتاج معتمدة تخص حسابك.')
    event = classify(job, settings['stall_minutes'], utcnow())
    if event:
        record(settings, data['kind'], job, event)
    return RedirectResponse('/production-monitor', 303)


@router.post('/production-monitor/{incident_id}/send-support')
async def send_support(incident_id: int, request: Request):
    s = access(request)
    data = await form(request, s)
    item = one('SELECT user_id,resolved_at FROM production_incidents WHERE id=?', (incident_id,))
    if not item or item['user_id'] != s['user_id']:
        raise HTTPException(404)
    if data.get('approve') != 'yes' or item['resolved_at']:
        raise HTTPException(409, 'راجع الرسالة واعتمدها قبل الإرسال.')
    await run_in_threadpool(deliver, incident_id, support=True)
    return RedirectResponse('/production-monitor', 303)
