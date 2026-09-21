"""Explicit recovery and verifiable operational checks for the official agent."""
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from app.storage import db, one, rows, utcnow
from app.social_content import page, e
from app.social_publishing import hidden_csrf
from app.mfa_stepup import recent_stepup
from app import advert_studio as advert, production_monitor as monitor, spacemail

router = APIRouter()
with db() as c:
    c.execute('''CREATE TABLE IF NOT EXISTS agent_recoveries(
        job_id BIGINT PRIMARY KEY REFERENCES advert_jobs(id), user_id BIGINT NOT NULL,
        step_id BIGINT NOT NULL, previous_error TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS agent_checks(
        user_id BIGINT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
        message_id TEXT, created_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(user_id,kind))''')


def access(request):
    return monitor.access(request)


async def form(request, session):
    if not recent_stepup(session['id']):
        raise HTTPException(428, 'يلزم تحقق Authenticator حديث.')
    return await monitor.form(request, session)


def recover(job_id, uid):
    advert.enabled()
    with db() as c:
        job = c.execute('SELECT * FROM advert_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if not job or job['created_by'] != uid or job['status'] != 'needs_review' or not job['approved_by']:
            raise HTTPException(409, 'المهمة غير جاهزة للاستئناف.')
        # Legacy error is known to mean HTTP 402/403, not a lost success response.
        reason = job['last_error'] or ''
        if not (reason.startswith('الرصيد غير كافٍ أو الدفع غير مهيأ لدى fal.ai.') or reason.startswith('رفض fal.ai الطلب قبل قبوله (HTTP ')):
            raise HTTPException(409, 'نتيجة الطلب غير مؤكدة؛ يلزم ربط نتيجته من المزود بدل تكراره.')
        step = c.execute("SELECT * FROM advert_steps WHERE job_id=%s AND status!='complete' ORDER BY ordinal LIMIT 1 FOR UPDATE", (job_id,)).fetchone()
        if not step or step['status'] != 'submitting' or step['receipt'] or step['asset_url']:
            raise HTTPException(409, 'لا توجد مرحلة مرفوضة قابلة للاستئناف.')
        claim = c.execute('''INSERT INTO agent_recoveries(job_id,user_id,step_id,previous_error,created_at)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING job_id''',
            (job_id,uid,step['id'],reason,utcnow())).fetchone()
        if not claim:
            raise HTTPException(409, 'استُخدمت محاولة الاستئناف؛ راجع المزود قبل أي محاولة إضافية.')
        c.execute("UPDATE advert_steps SET status='ready',updated_at=%s WHERE id=%s", (utcnow(),step['id']))
        c.execute("UPDATE advert_jobs SET status='running',last_error=NULL,updated_at=%s WHERE id=%s", (utcnow(),job_id))
        advert.audit(c, uid, 'advert_recovery_reviewed', job_id, 'Provider history checked: rejected request absent. One recovery, same approved budget, preserve assets.')


def alert_check(uid):
    conn = spacemail.connection(uid)
    if not conn or conn['status'] != 'connected':
        raise HTTPException(409, 'اربط البريد الرسمي أولًا.')
    settings = one('SELECT * FROM production_monitor_settings WHERE user_id=? AND enabled=TRUE', (uid,))
    if not settings or settings['sender'] != spacemail.ADDRESS or settings['recipient'] != spacemail.ADDRESS:
        raise HTTPException(409, 'اضبط التنبيهات على البريد الرسمي أولًا.')
    candidate = one("SELECT id FROM advert_jobs WHERE created_by=? AND approved_at IS NOT NULL AND status='needs_review' ORDER BY id DESC LIMIT 1", (uid,))
    if not candidate:
        raise HTTPException(409, 'لا توجد مهمة متعثرة لاختبار التصنيف.')
    job = monitor.snapshot('advert', candidate['id'])
    event = monitor.classify(job, settings['stall_minutes'], utcnow())
    if event != 'failed':
        raise HTTPException(409)
    with db() as c:
        claimed = c.execute("INSERT INTO agent_checks(user_id,kind,status,created_at) VALUES(%s,'alert','sending',%s) ON CONFLICT DO NOTHING RETURNING user_id", (uid,utcnow())).fetchone()
    if not claimed:
        return
    subject = 'آفاق طويق — اختبار تنبيه تعثر الإنتاج'
    body = 'اختبار تشغيلي للتنبيه، وليس عطلًا جديدًا.\n' + job['title'] + '\n' + job['progress'] + '\n' + (job['last_error'] or '') + '\n' + job['url']
    try:
        mid = spacemail.send(uid, spacemail.ADDRESS, subject, body)
        status = 'accepted'
    except Exception:
        mid, status = None, 'uncertain'
    with db() as c:
        c.execute("UPDATE agent_checks SET status=%s,message_id=%s WHERE user_id=%s AND kind='alert'", (status,mid,uid))


@router.get('/agent-operations', response_class=HTMLResponse)
def dashboard(request: Request):
    s = access(request)
    body = '<h1>تشغيل وكيل آفاق طويق</h1><p><a href="/official-inbox">البريد الوارد</a> · <a href="/production-monitor">تنبيهات الإنتاج</a> · <a href="/advert-studio">إنتاج الإعلان</a></p>'
    with db() as c:
        c.execute("""UPDATE agent_checks t SET status='received' WHERE user_id=%s AND status='accepted'
            AND EXISTS(SELECT 1 FROM spacemail_inbox i WHERE i.user_id=t.user_id AND i.message_id=t.message_id)""", (s['user_id'],))
    labels = {'sending':'جارٍ الإرسال','accepted':'قُبل الإرسال؛ ننتظر وصوله','received':'نجح الاختبار ووصل إلى الوارد','uncertain':'نتيجة الإرسال غير مؤكدة؛ لن نكرر تلقائيًا'}
    for check in rows('SELECT kind,status FROM agent_checks WHERE user_id=?', (s['user_id'],)):
        body += '<p>اختبار التنبيه: ' + e(labels.get(check['status'],check['status'])) + '</p>'
    if not recent_stepup(s['id']):
        body += '<a href="/mfa/step-up?next=/agent-operations">التحقق لتشغيل الاختبارات والاستئناف</a>'
    else:
        body += '<form method="post" action="/agent-operations/test-alert">' + hidden_csrf(s) + '<button>اختبار تنبيه التعطل على البريد الرسمي</button></form>'
        for job in rows("SELECT id,last_error FROM advert_jobs WHERE created_by=? AND status='needs_review' ORDER BY id DESC", (s['user_id'],)):
            if one('SELECT job_id FROM agent_recoveries WHERE job_id=?', (job['id'],)):
                body += '<p>الطلب ' + str(job['id']) + ': استُخدمت محاولة الاستئناف. راجع نتيجة المزود قبل التكرار.</p>'
                continue
            body += '<div><h2>استئناف الطلب ' + str(job['id']) + '</h2><p>' + e(job['last_error']) + '</p><form method="post" action="/agent-operations/recover/' + str(job['id']) + '">' + hidden_csrf(s)
            body += '<label><input type="checkbox" name="reviewed" value="yes" required> راجعت سجل fal.ai وتأكدت من عدم قبول المرحلة المرفوضة، وأعتمد استئنافها مرة واحدة ضمن سقف التكلفة السابق.</label><button>استئناف المهمة ضمن الميزانية المعتمدة</button></form></div>'
    return HTMLResponse(page(body), headers={'Cache-Control':'no-store'})


@router.post('/agent-operations/recover/{job_id}')
async def resume(job_id: int, request: Request):
    s = access(request)
    data = await form(request, s)
    if data.get('reviewed') != 'yes':
        raise HTTPException(409)
    await run_in_threadpool(recover, job_id, s['user_id'])
    return RedirectResponse('/advert-studio/' + str(job_id),303)


@router.post('/agent-operations/test-alert')
async def test_alert(request: Request):
    s = access(request)
    await form(request, s)
    await run_in_threadpool(alert_check, s['user_id'])
    return RedirectResponse('/agent-operations',303)
