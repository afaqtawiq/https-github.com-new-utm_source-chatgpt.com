"""One explicitly approved Runway clip; polling never submits paid work."""
import asyncio
from contextlib import suppress
import datetime as dt
from decimal import Decimal
import os
import re
import secrets
import shutil
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from app import runway_video_provider as provider
from app.media_runway import RunwayError, organization_balance
from app.media_settings import media_admin
from app.runway_settings import credential, connection_status, require_stepup, fresh_approval, form_data, NO_STORE, RUNWAY_KEY_LOCK
from app.social_content import e, page
from app.social_publishing import hidden_csrf
from app.storage import db, one, rows, utcnow

router = APIRouter()
QUOTA = 128 * 1024 * 1024
QUOTA_LOCK = 70600501
PROCESS_LOCK = 70600502
LABELS = {'draft': 'بانتظار اعتماد التقدير والمحتوى', 'submitting': 'جارٍ تقديم الطلب مرة واحدة',
          'pending': 'بانتظار فيديو Runway', 'complete': 'اكتمل الفيديو — مسودة للمراجعة',
          'needs_review': 'تحتاج المهمة مراجعة', 'failed': 'انتهت المهمة دون فيديو ناجح'}
DEFAULT_PROMPT = ('A single five-second photorealistic cinematic tracking shot of a modern tractor-trailer '
    'carrying one securely locked shipping container along a marked access road at a Saudi Arabian seaport at sunrise. '
    'Organized container stacks and gantry cranes in the background. Natural wheel rotation, correct axles, mirrors, '
    'tire contact and consistent shadows. Smooth steady camera at matching road speed. Navy blue and warm gold palette. '
    'Keep the truck centered in a vertical composition. No text, logos, badges or government emblems. '
    'Representative logistics scene, not a depiction of an actual company fleet.')
DEFAULT_CAPTION = ('كل شحنة تحمل فرصة...\nآفاق طويق للتخليص الجمركي والنقل والشحن والتخزين وخدمات الباب إلى الباب.\n'
                   'مشهد توضيحي مولّد بالذكاء الاصطناعي.\n#آفاق_طويق #التخليص_الجمركي #النقل #الشحن')


def init_studio():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS runway_video_jobs(
            id BIGSERIAL PRIMARY KEY, status TEXT NOT NULL, title TEXT NOT NULL,
            prompt TEXT NOT NULL, caption TEXT NOT NULL, estimated_credits INTEGER NOT NULL,
            approved_credits INTEGER, credential_version TIMESTAMPTZ NOT NULL,
            quote_expires_at TIMESTAMPTZ NOT NULL, approved_by BIGINT, approved_at TIMESTAMPTZ,
            task_id TEXT UNIQUE, provider_estimated_credits NUMERIC(16,6), final_credits NUMERIC(16,6),
            cost_alert BOOLEAN NOT NULL DEFAULT FALSE, reserved_bytes BIGINT NOT NULL DEFAULT 0,
            last_error TEXT, last_polled_at TIMESTAMPTZ,
            content_id BIGINT UNIQUE REFERENCES social_content(id),
            created_by BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS runway_video_exports(
            token TEXT PRIMARY KEY, job_id BIGINT UNIQUE NOT NULL REFERENCES runway_video_jobs(id),
            payload BYTEA NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS runway_video_status_idx ON runway_video_jobs(status)')


init_studio()


def audit(c, user_id, action, job_id, summary):
    c.execute('''INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at)
        VALUES(%s,%s,'runway_video',%s,%s,%s)''', (user_id, action, job_id, summary, utcnow()))


def public_url(token):
    origin = os.getenv('AFAAQ_PUBLIC_ORIGIN', 'https://gulf-logistics-ai-v7-production.up.railway.app').rstrip('/')
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise RunwayError('عنوان حفظ ملف الفيديو غير مهيأ. لم يبدأ الإنتاج.')
    return origin + '/runway-exports/' + token + '.mp4'


def enabled():
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        raise RunwayError('الإجراءات الخارجية متوقفة. لم يبدأ إنتاج Runway.')


def prerequisites():
    if not shutil.which('ffprobe', path=os.defpath):
        raise RunwayError('فحص ملفات الفيديو غير جاهز على الخادم. لم يبدأ الإنتاج.')
    public_url('0' * 48)


def record(job_id):
    job = one('SELECT * FROM runway_video_jobs WHERE id=?', (job_id,))
    if not job:
        raise HTTPException(404)
    return job


def cost_value(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        cost = Decimal(str(value))
        return cost if cost.is_finite() and 0 <= cost <= 1_000_000 else None
    except (ValueError, ArithmeticError):
        return None


def prepare(data, user_id):
    prerequisites()
    for field, limit in (('title', 150), ('caption', 3000)):
        if not 1 <= len(data.get(field, '').strip()) <= limit:
            raise RunwayError('أكمل عنوان الفيديو ونص المنشور ضمن الطول المحدد.')
    prompt = provider.validate_prompt(data.get('prompt', '').strip())
    state = connection_status()
    if not state['verified_at']:
        raise RunwayError('افحص اتصال Runway من إعدادات الربط أولًا.')
    key, version = credential()
    if version != state['updated_at']:
        raise RunwayError('تغير مفتاح Runway أثناء تجهيز الطلب. افحص الاتصال مجددًا.')
    if organization_balance(key) < provider.ESTIMATED_CREDITS:
        raise RunwayError('رصيد Runway الحالي لا يغطي التقدير. لم يبدأ التوليد.')
    now = utcnow()
    with db() as c:
        job_id = c.execute('''INSERT INTO runway_video_jobs(status,title,prompt,caption,estimated_credits,
            credential_version,quote_expires_at,created_by,created_at,updated_at)
            VALUES('draft',%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            (data['title'].strip(), prompt, data['caption'].strip(), provider.ESTIMATED_CREDITS, version,
             now + dt.timedelta(minutes=15), user_id, now, now)).fetchone()['id']
        audit(c, user_id, 'runway_video_prepared', job_id, 'Prepared fixed five-second estimate; no generation.')
    return job_id


def approve(job_id, user_id, stamp, approved_credits, *, session_id, csrf_token):
    # Saving a replacement waits until this exact old-key request has a receipt
    # or a durable uncertain state. The claim itself commits in a separate DB
    # transaction before the paid HTTP call.
    with db() as lock:
        lock.execute('SELECT pg_advisory_xact_lock(%s)', (RUNWAY_KEY_LOCK,))
        return approve_locked(job_id, user_id, stamp, approved_credits, session_id, csrf_token)


def approve_locked(job_id, user_id, stamp, approved_credits, session_id, csrf_token):
    enabled()
    prerequisites()
    job = record(job_id)
    if str(approved_credits) != str(provider.ESTIMATED_CREDITS):
        raise RunwayError('اعتمد تقدير هذا الفيديو المحدد فقط.')
    key, version = credential()
    if version != job['credential_version']:
        raise RunwayError('تغير مفتاح Runway بعد تجهيز الطلب. جهّز طلبًا جديدًا.')
    if organization_balance(key) < job['estimated_credits']:
        raise RunwayError('الرصيد لا يغطي التقدير. لم يُرسل طلب مدفوع.')
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)', (QUOTA_LOCK,))
        locked = c.execute('SELECT * FROM runway_video_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        current_key = c.execute('SELECT updated_at,verified_at FROM runway_provider_settings WHERE id=1').fetchone()
        if (locked['status'] != 'draft' or locked['approved_at'] is not None):
            raise RunwayError('سبق اعتماد هذه المهمة أو توقفها. لن يُكرر طلب التوليد.')
        if locked['quote_expires_at'] <= utcnow() or stamp != locked['quote_expires_at'].isoformat():
            raise RunwayError('انتهى التقدير أو تغيرت مراجعته. جهّز طلبًا جديدًا.')
        if not current_key or not current_key['verified_at'] or current_key['updated_at'] != version or locked['credential_version'] != version:
            raise RunwayError('تغير مفتاح Runway أثناء الاعتماد. جهّز طلبًا جديدًا.')
        if locked['estimated_credits'] != provider.ESTIMATED_CREDITS:
            raise RunwayError('تغير تقدير النموذج. لم يبدأ التوليد.')
        used = c.execute('SELECT COALESCE(SUM(reserved_bytes),0) n FROM runway_video_jobs').fetchone()['n']
        if used + provider.MAX_EXPORT > QUOTA:
            raise RunwayError('بلغ حفظ فيديوهات Runway حد التخزين. لم يبدأ التوليد المدفوع.')
        fresh_approval(session_id, user_id, csrf_token)
        now = utcnow()
        c.execute('''UPDATE runway_video_jobs SET status='submitting',approved_by=%s,approved_at=%s,
            approved_credits=%s,reserved_bytes=%s,updated_at=%s WHERE id=%s''',
            (user_id, now, provider.ESTIMATED_CREDITS, provider.MAX_EXPORT, now, job_id))
        audit(c, user_id, 'runway_video_approved', job_id, 'Approved one fixed generation estimate; committed submission claim.')
    # Claim is durable before the only paid HTTP request. No worker calls submit.
    try:
        receipt = provider.submit(key, job['prompt'])
    except RunwayError as exc:
        with db() as c:
            c.execute("UPDATE runway_video_jobs SET status='needs_review',last_error=%s,updated_at=%s WHERE id=%s AND status='submitting'",
                      (str(exc) + ' لن يُكرر الطلب؛ راجع سجل Runway قبل طلب مدفوع جديد.', utcnow(), job_id))
        return
    estimate = cost_value(receipt.get('estimated_credits'))
    alert = estimate is None or estimate > provider.ESTIMATED_CREDITS
    with db() as c:
        linked = c.execute('''UPDATE runway_video_jobs SET task_id=%s,provider_estimated_credits=%s,cost_alert=%s,
            status=CASE WHEN status='needs_review' OR %s THEN 'needs_review' ELSE 'pending' END,
            last_error=CASE WHEN %s THEN %s ELSE last_error END,updated_at=%s
            WHERE id=%s AND approved_at=%s AND task_id IS NULL AND status IN ('submitting','needs_review') RETURNING id''',
            (receipt['task_id'], estimate, alert, alert,
             alert,
             'تكلفة المزود بعد قبول الطلب غير مطابقة للتقدير. قد يكون احتُسب رصيد؛ حُفظ رقم الطلب للمراجعة ولا يُعاد التوليد.' if alert else None,
             utcnow(), job_id, now)).fetchone()
        # A watchdog may have paused the claim while the HTTP call was in flight.
        # Never lose the accepted receipt, or falsely audit that it was linked.
        audit(c, user_id, 'runway_video_receipt' if linked else 'runway_video_receipt_review', job_id,
              'Stored accepted provider task receipt; no retry.' if linked else
              'Unlinked accepted task receipt retained for manual review: ' + receipt['task_id'])


def mark_review(c, job_id, message):
    c.execute("UPDATE runway_video_jobs SET status='needs_review',last_error=%s,updated_at=%s WHERE id=%s", (message, utcnow(), job_id))


def process_job(job_id, manual=False):
    with db() as c:
        # One poll/download/finalization per job across processes and web requests.
        if not c.execute('SELECT pg_try_advisory_xact_lock(%s,%s) locked', (PROCESS_LOCK, job_id)).fetchone()['locked']:
            return
        job = c.execute('SELECT * FROM runway_video_jobs WHERE id=%s', (job_id,)).fetchone()
        if not job or job['status'] in ('draft', 'complete', 'failed'):
            return
        if job['status'] == 'submitting':
            if job['updated_at'] < utcnow() - dt.timedelta(minutes=3):
                mark_review(c, job_id, 'لم يُحفظ تأكيد إرسال الطلب. راجع سجل Runway؛ لن يُكرر التوليد.')
            return
        if (job['status'] != 'pending' and not manual) or not job['task_id'] or job['cost_alert']:
            return
        if job['last_polled_at'] and job['last_polled_at'] > utcnow() - dt.timedelta(seconds=5):
            return
        c.execute('UPDATE runway_video_jobs SET last_polled_at=%s WHERE id=%s', (utcnow(), job_id))
        try:
            key, version = credential()
            if version != job['credential_version']:
                raise RunwayError('تغير مفتاح Runway. حُفظ رقم المهمة؛ راجع اتصال المشروع قبل استئناف الفحص.')
            result = provider.poll(key, job['task_id'])
            if result['status'] in ('pending', 'throttled', 'running'):
                c.execute("UPDATE runway_video_jobs SET status='pending',last_error=NULL,updated_at=%s WHERE id=%s", (utcnow(), job_id))
                return
            cost = cost_value(result.get('cost_credits'))
            if cost is None or cost > job['approved_credits']:
                c.execute('UPDATE runway_video_jobs SET final_credits=%s,cost_alert=TRUE WHERE id=%s', (cost, job_id))
                raise RunwayError('التكلفة النهائية غير مطابقة للتقدير المعتمد. توقف المسار للمراجعة؛ لن يُكرر التوليد.')
            c.execute('UPDATE runway_video_jobs SET final_credits=%s WHERE id=%s', (cost, job_id))
            if result['status'] in ('failed', 'cancelled'):
                c.execute("UPDATE runway_video_jobs SET status='failed',reserved_bytes=0,last_error=%s,updated_at=%s WHERE id=%s",
                          ('أبلغ Runway انتهاء المهمة دون فيديو ناجح. راجع التكلفة والسجل؛ لم يُكرر التوليد.', utcnow(), job_id))
                return
            if result['status'] != 'succeeded':
                raise RunwayError('حالة Runway غير معروفة. حُفظ الطلب للمراجعة.')
            payload = provider.download(result['output_url'])
            provider.validate_file(payload)
            token = secrets.token_hex(24)
            now = utcnow()
            url = public_url(token)
            # The advisory lock serializes finish; both output and draft commit together.
            content_id = c.execute('''INSERT INTO social_content(title,platform,content_type,body,media_url,
                status,created_by,created_at,updated_at) VALUES(%s,'YouTube+TikTok','video',%s,%s,'draft',%s,%s,%s) RETURNING id''',
                (job['title'], job['caption'], url, job['created_by'], now, now)).fetchone()['id']
            c.execute('INSERT INTO runway_video_exports(token,job_id,payload,created_at) VALUES(%s,%s,%s,%s)', (token, job_id, payload, now))
            c.execute("UPDATE runway_video_jobs SET status='complete',content_id=%s,reserved_bytes=%s,last_error=NULL,updated_at=%s WHERE id=%s", (content_id, len(payload), now, job_id))
            audit(c, job['approved_by'], 'runway_video_completed', job_id, 'Stored one MP4 and unapproved content draft; no publishing or scheduling.')
        except RunwayError as exc:
            mark_review(c, job_id, str(exc))


def tick():
    for job in rows("SELECT id FROM runway_video_jobs WHERE status IN ('submitting','pending') ORDER BY updated_at LIMIT 5"):
        process_job(job['id'])


def error(message, status=409):
    return HTMLResponse(page('<div class="card" role="alert"><p>' + e(message) +
        '</p><a class="btn" href="/runway-studio">استوديو Runway</a></div>'), status_code=status, headers=NO_STORE)


@router.get('/runway-studio', response_class=HTMLResponse)
def studio_page(request: Request):
    session = media_admin(request)
    body = '<div class="nav"><a href="/content-center">مركز المحتوى</a><a href="/settings/runway">ربط Runway</a><a href="/media-studio">استوديو fal.ai</a></div>'
    body += '<div class="hero"><h1>فيديو آفاق عبر Runway</h1><p>فيديو واحد عمودي 9:16 · 720×1280 · 5 ثوانٍ · Gen-4.5 · دون تعليق صوتي أو موسيقى مضافة</p></div>'
    body += '<div class="card"><p>التقدير المرجعي: 60 كريديت من مشروع Runway Developer API. لا يبدأ التوليد عند تجهيز الطلب.</p>'
    body += '<form method="post" action="/runway-studio/prepare">' + hidden_csrf(session)
    body += '<label>العنوان<input name="title" maxlength="150" required value="آفاق طويق — كل شحنة تحمل فرصة"></label>'
    body += '<label>وصف المشهد<textarea name="prompt" maxlength="1000" dir="auto" required>' + e(DEFAULT_PROMPT) + '</textarea></label>'
    body += '<label>نص المنشور<textarea name="caption" maxlength="3000" required>' + e(DEFAULT_CAPTION) + '</textarea></label>'
    body += '<button class="btn">تجهيز الفيديو ومراجعة التقدير — دون توليد</button></form></div>'
    jobs = rows('SELECT id,title,status FROM runway_video_jobs ORDER BY id DESC LIMIT 30')
    body += '<div class="card"><h2>مهام Runway</h2>' + ''.join('<p><a href="/runway-studio/' + str(j['id']) + '">' + e(j['title']) + '</a> · ' + e(LABELS.get(j['status'], j['status'])) + '</p>' for j in jobs) + '</div>'
    return HTMLResponse(page(body), headers=NO_STORE)


@router.post('/runway-studio/prepare')
async def prepare_route(request: Request):
    session = media_admin(request)
    data = await form_data(request, session, max_size=48000)
    try:
        job_id = await run_in_threadpool(prepare, data, session['user_id'])
    except RunwayError as exc:
        return error(str(exc))
    return RedirectResponse('/runway-studio/' + str(job_id), 303, headers=NO_STORE)


@router.get('/runway-studio/{job_id}', response_class=HTMLResponse)
def job_page(job_id: int, request: Request):
    session = media_admin(request)
    job = record(job_id)
    body = '<div class="nav"><a href="/runway-studio">استوديو Runway</a><a href="/settings/runway">الربط والرصيد</a></div>'
    body += '<div class="hero"><h1>' + e(job['title']) + '</h1><p>' + e(LABELS.get(job['status'], job['status'])) + '</p></div>'
    body += '<div class="card"><h2>مراجعة الطلب</h2><p>Gen-4.5 · فيديو واحد 5 ثوانٍ · 9:16 · 720×1280 · MP4 عادي</p><p>لا يشمل صوتًا أو تعليقًا أو شعارًا أو مونتاج إعلان طويل.</p>'
    body += '<p dir="auto">' + e(job['prompt']) + '</p><p style="white-space:pre-wrap">' + e(job['caption']) + '</p>'
    body += '<p><b>التكلفة التقديرية: ' + str(job['estimated_credits']) + ' كريديت</b> من Runway Developer API، بحسب 12 كريديت/ثانية في <a href="' + provider.PRICING_URL + '" rel="noreferrer">تعرفة Runway</a> التي روجعت في 2026-10-03.</p>'
    body += '<p>هذا تقدير، وليس حدًا يفرضه Runway قبل الطلب. يرد تقدير المزود بعد قبول الطلب؛ إذا اختلفت التكلفة يتوقف المسار للمراجعة وقد يكون احتُسب رصيد بالفعل. لا إعادة تلقائية أو شراء رصيد.</p>'
    body += '<p>عند الاكتمال يُحفظ الملف برابط غير مفهرس يصعب تخمينه ومسودة غير معتمدة في مركز المحتوى. الجدولة والنشر يحتاجان مراجعتهما وموافقتهما المنفصلتين.</p>'
    if job['status'] == 'draft':
        if job['quote_expires_at'] <= utcnow():
            body += '<p>انتهت مهلة هذا التقدير. جهّز طلبًا جديدًا قبل الاعتماد.</p>'
        else:
            try:
                require_stepup(session)
            except HTTPException:
                body += '<a class="btn" href="/mfa/step-up?next=/runway-studio/' + str(job_id) + '">التحقق قبل اعتماد التوليد</a>'
            else:
                body += '<form method="post" action="/runway-studio/' + str(job_id) + '/run">' + hidden_csrf(session)
                body += '<input type="hidden" name="quote_stamp" value="' + e(job['quote_expires_at'].isoformat()) + '"><input type="hidden" name="approved_credits" value="60">'
                body += '<label><input style="width:auto" type="checkbox" name="approve_cost" value="yes" required> أوافق على هذا الوصف وإرساله إلى Runway وتقديره 60 كريديت لفيديو واحد، مع احتمال تغير تعرفة المزود ودون إعادة الطلب، وحفظ المسودة والملف للمراجعة.</label>'
                body += '<button class="btn">اعتماد التقدير وبدء فيديو واحد</button></form>'
    if job.get('task_id'):
        body += '<p>رقم طلب Runway: ' + e(job['task_id']) + '</p>'
    if job.get('final_credits') is not None:
        body += '<p>التكلفة التي أبلغ عنها المزود: ' + e(str(job['final_credits'])) + ' كريديت</p>'
    if job.get('last_error'):
        body += '<p role="alert">' + e(job['last_error']) + '</p>'
    if job['status'] in ('pending', 'needs_review') and job.get('task_id') and not job['cost_alert']:
        body += '<form method="post" action="/runway-studio/' + str(job_id) + '/sync">' + hidden_csrf(session) + '<button class="btn">فحص الطلب الموجود وحفظ نتيجته — دون توليد جديد</button></form>'
    body += '</div>'
    if job['status'] == 'complete':
        export = one('SELECT token FROM runway_video_exports WHERE job_id=?', (job_id,))
        if export:
            url = public_url(export['token'])
            body += '<div class="card"><video controls preload="metadata" style="max-width:100%;max-height:620px" src="' + e(url) + '"></video><p><a class="btn" href="/content-center/' + str(job['content_id']) + '">مراجعة المسودة والجدولة</a></p></div>'
    html = page(body)
    if job['status'] in ('submitting', 'pending'):
        html = html.replace('<title>', '<meta http-equiv="refresh" content="20"><title>', 1)
    return HTMLResponse(html, headers=NO_STORE)


@router.post('/runway-studio/{job_id}/run')
async def run_route(job_id: int, request: Request):
    session = media_admin(request)
    require_stepup(session)
    data = await form_data(request, session)
    fresh_approval(session['id'], session['user_id'], data.get('csrf'))
    if data.get('approve_cost') != 'yes':
        return error('يلزم اعتماد وصف هذا الفيديو وتقدير تكلفته صراحة.')
    try:
        await run_in_threadpool(approve, job_id, session['user_id'], data.get('quote_stamp', ''),
                               data.get('approved_credits', ''), session_id=session['id'], csrf_token=data.get('csrf'))
    except RunwayError as exc:
        return error(str(exc))
    return RedirectResponse('/runway-studio/' + str(job_id), 303, headers=NO_STORE)


@router.post('/runway-studio/{job_id}/sync')
async def sync_route(job_id: int, request: Request):
    session = media_admin(request)
    await form_data(request, session)
    record(job_id)
    await run_in_threadpool(process_job, job_id, manual=True)
    return RedirectResponse('/runway-studio/' + str(job_id), 303, headers=NO_STORE)


@router.api_route('/runway-exports/{token}.mp4', methods=['GET', 'HEAD'])
def export_file(token: str, request: Request):
    if not re.fullmatch(r'[0-9a-f]{48}', token):
        raise HTTPException(404)
    found = one('''SELECT x.payload FROM runway_video_exports x JOIN runway_video_jobs j ON j.id=x.job_id
        WHERE x.token=? AND j.status='complete' AND j.approved_at IS NOT NULL''', (token,))
    if not found:
        raise HTTPException(404)
    payload = bytes(found['payload'])
    size, start, end, status = len(payload), 0, len(payload)-1, 200
    headers = {'Accept-Ranges': 'bytes', 'Cache-Control': 'public,max-age=3600,immutable',
               'Content-Disposition': 'inline; filename="afaaq-runway.mp4"', 'X-Content-Type-Options': 'nosniff'}
    requested = request.headers.get('range')
    if requested:
        match = re.fullmatch(r'bytes=([0-9]{0,20})-([0-9]{0,20})', requested)
        if not match or not any(match.groups()):
            return Response(status_code=416, headers={'Content-Range': f'bytes */{size}'})
        left, right = match.groups()
        if left:
            start, end = int(left), min(size-1, int(right)) if right else size-1
        else:
            start = max(0, size-int(right)) if int(right) else size
        if start >= size or start > end:
            return Response(status_code=416, headers={'Content-Range': f'bytes */{size}'})
        status = 206
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    headers['Content-Length'] = str(end-start+1)
    return Response(b'' if request.method == 'HEAD' else payload[start:end+1], status_code=status, media_type='video/mp4', headers=headers)


def register_worker(app):
    async def loop():
        while True:
            try:
                await run_in_threadpool(tick)
            except Exception:
                # Keep durable receipts/claims; do not log payloads or resubmit work.
                pass
            await asyncio.sleep(15)

    @app.on_event('startup')
    async def start():
        app.state.runway_video_worker = asyncio.create_task(loop())

    @app.on_event('shutdown')
    async def stop():
        task = getattr(app.state, 'runway_video_worker', None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
