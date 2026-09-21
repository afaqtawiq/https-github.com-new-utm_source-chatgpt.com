"""Budget-reviewed durable generation jobs. Publishing keeps its own approval."""
import asyncio
from contextlib import suppress
import datetime as dt
import json
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app import media_fal as fal
from app.media_settings import media_admin, media_cipher
from app.social_content import e, page, parse
from app.social_publishing import csrf, hidden_csrf
from app.storage import db, one, rows, utcnow

router = APIRouter()
ACTIVE = ('image_submitting', 'image_pending', 'video_ready', 'video_submitting', 'video_pending')
LABELS = {'draft': 'بانتظار اعتماد تكلفة الإنتاج', 'image_submitting': 'إرسال طلب الصورة',
          'image_pending': 'جارٍ إنتاج الصورة', 'video_ready': 'الصورة جاهزة؛ تجهيز الفيديو',
          'video_submitting': 'إرسال طلب الفيديو', 'video_pending': 'جارٍ إنتاج الفيديو',
          'complete': 'اكتمل إنتاج الوسائط', 'needs_review': 'تحتاج المهمة مراجعة', 'failed': 'توقف الإنتاج'}
DEFAULT_IMAGE = ('Photorealistic premium logistics commercial in Saudi Arabia. One modern tractor-trailer '
    'carrying a securely locked shipping container, driving on a marked port access road at sunrise. '
    'Correct truck proportions, axles, mirrors and tire contact; organized container stacks and working '
    'gantry cranes in the distant background. Low three-quarter side view, warm practical sunlight, '
    'navy blue and subtle gold visual palette. Keep the truck in the central safe area. No text, no logos, '
    'no fake badges, no government emblems. This is a representative scene, not a photograph of a real company fleet.')
DEFAULT_VIDEO = ('A single continuous cinematic tracking shot over five seconds. The camera tracks smoothly '
    'beside the truck at matching road speed. The truck advances in its lane; wheels rotate naturally '
    'with real ground contact and consistent shadows. Preserve the trailer, container, truck geometry '
    'and direction of travel. No teleportation, abrupt turns, time jumps or text. Subtle port background motion.')
DEFAULT_CAPTION = ('كل شحنة تحمل فرصة...\nآفاق طويق للتخليص الجمركي والنقل والشحن والتخزين وخدمات الباب إلى الباب.\n'
    'من الحدود... إلى وجهة تجارتك.\nتواصل معنا لطلب عرض لخدمات شحنتك.\n#آفاق_طويق #التخليص_الجمركي #النقل #الشحن')


def init_studio():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS media_jobs(
            id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('image','video')),
            status TEXT NOT NULL, title TEXT NOT NULL, caption TEXT NOT NULL,
            image_prompt TEXT NOT NULL, video_prompt TEXT NOT NULL, ratio TEXT NOT NULL,
            image_cost NUMERIC(12,6) NOT NULL, video_cost NUMERIC(12,6) NOT NULL,
            quote_expires_at TIMESTAMPTZ NOT NULL, credential_version TIMESTAMPTZ NOT NULL,
            approved_by BIGINT, approved_at TIMESTAMPTZ,
            image_receipt TEXT, video_receipt TEXT, image_url TEXT, video_url TEXT,
            content_id BIGINT UNIQUE REFERENCES social_content(id), last_error TEXT,
            created_by BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS media_jobs_status_idx ON media_jobs(status)')


init_studio()


def credential(version=None):
    saved = one("SELECT api_key_enc,updated_at FROM media_provider_settings WHERE id=1 AND provider='fal'")
    if not saved:
        raise fal.MediaError('احفظ مفتاح fal.ai من إعدادات الإنتاج أولًا.')
    if version is not None and saved['updated_at'] != version:
        raise fal.MediaError('تغير مفتاح الإنتاج بعد تجهيز المهمة. أعد تجهيز طلب جديد بالمفتاح الحالي.')
    try:
        return media_cipher().decrypt(saved['api_key_enc'].encode()).decode(), saved['updated_at']
    except Exception:
        raise fal.MediaError('تعذر فتح مفتاح الإنتاج المشفر. راجع إعدادات الإنتاج.') from None


def enabled():
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        raise fal.MediaError('الإجراءات الخارجية متوقفة. لم يبدأ التوليد.')


def audit(c, user_id, action, job_id, summary):
    c.execute('''INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at)
        VALUES(%s,%s,'media_job',%s,%s,%s)''', (user_id, action, job_id, summary, utcnow()))


def error_page(message, code=400):
    return HTMLResponse(page('<div class="card"><p>' + e(message) + '</p><a class="btn" href="/media-studio">استوديو الإنتاج</a> '
        '<a class="btn" href="/settings/media">إعدادات الإنتاج</a></div>'), status_code=code, headers={'Cache-Control': 'no-store'})


async def form_data(request, session):
    raw = await request.body()
    if len(raw) > 16384:
        raise HTTPException(413)
    try:
        data = parse(raw)
    except (UnicodeError, ValueError):
        raise HTTPException(400, 'نموذج غير صالح.') from None
    csrf(session, data)
    return data


@router.get('/media-studio', response_class=HTMLResponse)
def studio_page(request: Request):
    session = media_admin(request)
    body = '<div class="nav"><a href="/content-center">مركز المحتوى</a><a href="/settings/media">إعدادات الإنتاج</a><a href="/settings/social">إعدادات النشر</a></div>'
    body += '<div class="hero"><h1>استوديو آفاق طويق</h1><p>اختر إعلانًا متكاملًا أو صورة أو مشهدًا قصيرًا. تُعرض التكلفة قبل التشغيل.</p></div>'
    body += '<div class="card"><h2>إعلان متكامل بالصوت والهوية</h2><p>أربع لقطات وخاتمة خلال 25–30 ثانية، تعليق عربي رجالي، نصوص وشعار، ومقاسان عمودي وأفقي.</p><a class="btn" href="/advert-studio">تجهيز إعلان ومراجعة تكلفته</a></div>'
    body += '<div class="card"><p>المشهد التجريبي بلا تعليق صوتي أو شعار. راجع النتيجة قبل اعتمادها للنشر.</p>'
    body += '<form method="post" action="/media-studio/prepare">' + hidden_csrf(session)
    body += '<label>عنوان المحتوى<input name="title" maxlength="150" required value="آفاق طويق — كل شحنة تحمل فرصة"></label>'
    body += '<label>نوع الإنتاج<select name="kind"><option value="video">صورة ثم فيديو — 5 ثوانٍ</option><option value="image">صورة فقط</option></select></label>'
    body += '<label>المقاس<select name="ratio"><option value="9:16">عمودي 9:16</option><option value="16:9">أفقي 16:9</option></select></label>'
    body += '<label>نص المنشور<textarea name="caption" maxlength="3000" required>' + e(DEFAULT_CAPTION) + '</textarea></label>'
    body += '<label>وصف الصورة<textarea name="image_prompt" maxlength="3000" dir="auto" required>' + e(DEFAULT_IMAGE) + '</textarea></label>'
    body += '<label>حركة الفيديو<textarea name="video_prompt" maxlength="2000" dir="auto" required>' + e(DEFAULT_VIDEO) + '</textarea></label>'
    body += '<button class="btn">تجهيز الطلب وعرض التكلفة — دون توليد</button></form></div>'
    jobs = rows('SELECT id,title,kind,status,created_at FROM media_jobs ORDER BY id DESC LIMIT 30')
    if jobs:
        body += '<div class="card"><h2>مهام الإنتاج</h2>' + ''.join('<p><a class="btn" href="/media-studio/' + str(j['id']) + '">' + e(j['title']) + '</a> · ' + e(LABELS.get(j['status'], j['status'])) + '</p>' for j in jobs) + '</div>'
    return HTMLResponse(page(body), headers={'Cache-Control': 'no-store'})


@router.post('/media-studio/prepare')
async def prepare(request: Request):
    session = media_admin(request)
    data = await form_data(request, session)
    if data.get('kind') not in ('image', 'video') or data.get('ratio') not in ('9:16', '16:9'):
        return error_page('اختر نوع الإنتاج والمقاس.')
    for field, limit in [('title', 150), ('caption', 3000), ('image_prompt', 3000), ('video_prompt', 2000)]:
        if not 1 <= len(data.get(field, '').strip()) <= limit:
            return error_page('أكمل حقول المحتوى ضمن الطول المحدد.')
    try:
        key, version = credential()
        quote = await run_in_threadpool(fal.prices, key)
    except fal.MediaError as error:
        return error_page(str(error))
    now = utcnow()
    with db() as c:
        row = c.execute('''INSERT INTO media_jobs(kind,status,title,caption,image_prompt,video_prompt,ratio,
            image_cost,video_cost,quote_expires_at,credential_version,created_by,created_at,updated_at)
            VALUES(%s,'draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            (data['kind'], data['title'].strip(), data['caption'].strip(), data['image_prompt'].strip(),
             data['video_prompt'].strip(), data['ratio'], quote['image'], quote['video'] if data['kind'] == 'video' else 0,
             now + dt.timedelta(minutes=15), version, session['user_id'], now, now)).fetchone()
        audit(c, session['user_id'], 'media_quote_prepared', row['id'], 'Live fal price quote; no generation submitted.')
    return RedirectResponse('/media-studio/' + str(row['id']), 303)


@router.get('/media-studio/{job_id}', response_class=HTMLResponse)
def job_page(job_id: int, request: Request):
    session = media_admin(request)
    job = one('SELECT * FROM media_jobs WHERE id=?', (job_id,))
    if not job:
        raise HTTPException(404)
    body = '<div class="nav"><a href="/media-studio">استوديو الإنتاج</a><a href="/content-center">مركز المحتوى</a></div>'
    body += '<div class="hero"><h1>' + e(job['title']) + '</h1><p>' + e(LABELS.get(job['status'], job['status'])) + '</p></div>'
    body += '<div class="card"><h2>مراجعة الطلب</h2><p>' + ('صورة ثم فيديو 5 ثوانٍ' if job['kind'] == 'video' else 'صورة واحدة') + ' · ' + e(job['ratio']) + '</p>'
    body += '<p style="white-space:pre-wrap">' + e(job['caption']) + '</p><details><summary>وصف المشهد والحركة</summary><p dir="auto">' + e(job['image_prompt']) + '</p><p dir="auto">' + e(job['video_prompt']) + '</p></details>'
    amount = job['image_cost'] + job['video_cost']
    body += '<p><b>تكلفة التوليد المتوقعة: ' + format(amount, '.4f') + ' USD</b> من رصيد fal.ai، قبل أي ضرائب.</p>'
    if job['status'] == 'draft':
        from app.mfa_stepup import recent_stepup
        if job['quote_expires_at'] <= utcnow():
            body += '<p>انتهت صلاحية عرض التكلفة. جهّز طلبًا جديدًا لمعرفة السعر الحالي.</p>'
        elif not recent_stepup(session['id']):
            body += '<a class="btn" href="/mfa/step-up?next=/media-studio/' + str(job_id) + '">التحقق قبل اعتماد التكلفة</a>'
        else:
            body += '<form method="post" action="/media-studio/' + str(job_id) + '/run">' + hidden_csrf(session)
            body += '<label><input style="width:auto" type="checkbox" name="approve_cost" value="yes" required> أوافق على تكلفة هذا الطلب. هذه موافقة إنتاج فقط؛ يُراجع المحتوى قبل النشر.</label>'
            body += '<button class="btn">اعتماد التكلفة وبدء الإنتاج</button></form>'
    body += '</div>'
    if job.get('last_error'):
        body += '<div class="card" role="alert">' + e(job['last_error']) + '</div>'
    if job.get('image_url'):
        body += '<div class="card"><img alt="الصورة المنتجة لآفاق طويق" style="max-width:100%;max-height:480px" src="' + e(job['image_url']) + '"></div>'
    if job.get('video_url'):
        body += '<div class="card"><video controls preload="metadata" style="max-width:100%;max-height:480px" src="' + e(job['video_url']) + '"></video></div>'
    if job.get('content_id'):
        body += '<div class="card"><a class="btn" href="/content-center/' + str(job['content_id']) + '">فتح المسودة للمراجعة والنشر</a></div>'
    if job['status'] in ACTIVE:
        body += '<div class="card"><p>تتابع المهمة تلقائيًا حتى ظهور النتيجة. لا تحتاج إلى إعادة طلب التوليد.</p></div>'
    if job['status'] in ('image_pending', 'video_pending', 'needs_review'):
        body += '<form method="post" action="/media-studio/' + str(job_id) + '/sync">' + hidden_csrf(session) + '<button class="btn">تحديث حالة الطلب الموجود</button></form>'
    html = page(body)
    if job['status'] in ACTIVE:
        html = html.replace('<title>', '<meta http-equiv="refresh" content="20"><title>', 1)
    return HTMLResponse(html, headers={'Cache-Control': 'no-store'})


def mark_review(job_id, message, expected_status):
    with db() as c:
        c.execute("UPDATE media_jobs SET status='needs_review',last_error=%s,updated_at=%s WHERE id=%s AND status=%s", (message, utcnow(), job_id, expected_status))


def send_claimed(job_id, stage, key):
    job = one('SELECT * FROM media_jobs WHERE id=?', (job_id,))
    try:
        receipt = fal.submit(key, stage, job[stage + '_prompt'], ratio=job['ratio'], image_url=job.get('image_url'))
    except fal.MediaError as error:
        mark_review(job_id, str(error) + ' لم يُكرر الطلب؛ راجع سجل fal.ai قبل إنشاء مهمة جديدة.', stage + '_submitting')
        return
    # A lost process before this write leaves a submitting claim; never resubmit it.
    with db() as c:
        field = 'image_receipt' if stage == 'image' else 'video_receipt'
        c.execute('UPDATE media_jobs SET ' + field + '=%s,status=%s,last_error=NULL,updated_at=%s WHERE id=%s AND status=%s',
            (json.dumps(receipt), stage + '_pending', utcnow(), job_id, stage + '_submitting'))


def approve_job(job_id, user_id):
    enabled()
    job = one('SELECT * FROM media_jobs WHERE id=?', (job_id,))
    if not job or job['status'] != 'draft':
        raise fal.MediaError('هذه المهمة بدأت بالفعل أو غير متاحة. لن يتكرر التوليد.')
    key, _ = credential(job['credential_version'])
    quote = fal.prices(key)
    if quote['image'] > job['image_cost'] or (job['kind'] == 'video' and quote['video'] > job['video_cost']):
        raise fal.MediaError('ارتفع سعر التوليد. جهّز طلبًا جديدًا لمراجعة التكلفة.')
    with db() as c:
        locked = c.execute('SELECT * FROM media_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if locked['status'] != 'draft' or locked['quote_expires_at'] <= utcnow():
            raise fal.MediaError('انتهى عرض التكلفة أو بدأ الطلب. لن يتكرر التوليد.')
        now = utcnow()
        c.execute("UPDATE media_jobs SET status='image_submitting',approved_by=%s,approved_at=%s,updated_at=%s WHERE id=%s", (user_id, now, now, job_id))
        audit(c, user_id, 'media_cost_approved', job_id, 'Approved generation quote USD ' + str(locked['image_cost'] + locked['video_cost']))
    send_claimed(job_id, 'image', key)


@router.post('/media-studio/{job_id}/run')
async def run_job(job_id: int, request: Request):
    session = media_admin(request)
    data = await form_data(request, session)
    if data.get('approve_cost') != 'yes':
        return error_page('يلزم اعتماد تكلفة المهمة قبل بدء التوليد.', 409)
    try:
        await run_in_threadpool(approve_job, job_id, session['user_id'])
    except fal.MediaError as error:
        return error_page(str(error), 409)
    return RedirectResponse('/media-studio/' + str(job_id), 303)


def finish(c, job, url):
    now = utcnow()
    content = c.execute('''INSERT INTO social_content(title,platform,content_type,body,media_url,status,created_by,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,'draft',%s,%s,%s) RETURNING id''',
        (job['title'], 'YouTube+TikTok' if job['kind'] == 'video' else 'All',
         'video' if job['kind'] == 'video' else 'image', job['caption'], url, job['created_by'], now, now)).fetchone()
    c.execute("UPDATE media_jobs SET status='complete',content_id=%s,last_error=NULL,updated_at=%s WHERE id=%s", (content['id'], now, job['id']))
    audit(c, job['approved_by'], 'media_generation_completed', job['id'], 'Created social draft ' + str(content['id']) + '; not published.')


def process_job(job_id, *, allow_paid=True):
    job = one('SELECT * FROM media_jobs WHERE id=?', (job_id,))
    if not job or job['status'] == 'complete':
        return
    if job['status'].endswith('_submitting'):
        if job['updated_at'] < utcnow() - dt.timedelta(minutes=3):
            mark_review(job_id, 'لم يُحفظ تأكيد الطلب. راجع سجل fal.ai؛ لن يُعاد إرسال طلب مدفوع تلقائيًا.', job['status'])
        return
    try:
        key, _ = credential(job['credential_version'])
        if job['status'] == 'video_ready':
            if not allow_paid:
                return
            enabled()
            quote = fal.prices(key)
            if quote['video'] > job['video_cost']:
                raise fal.MediaError('ارتفع سعر الفيديو عن التكلفة المعتمدة. حُفظت الصورة ولم يبدأ الفيديو.')
            with db() as c:
                current = c.execute('SELECT * FROM media_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
                if current['status'] != 'video_ready' or not current['approved_by']:
                    return
                c.execute("UPDATE media_jobs SET status='video_submitting',updated_at=%s WHERE id=%s", (utcnow(), job_id))
            send_claimed(job_id, 'video', key)
            return
        if job['status'] not in ('image_pending', 'video_pending', 'needs_review'):
            return
        stage = 'video' if job.get('video_receipt') else 'image'
        encoded = job.get(stage + '_receipt')
        if not encoded:
            return
        url = fal.result(key, stage, json.loads(encoded))
        if not url:
            return
        with db() as c:
            current = c.execute('SELECT * FROM media_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
            if current['status'] not in (stage + '_pending', 'needs_review') or current.get(stage + '_receipt') != encoded:
                return
            field = 'image_url' if stage == 'image' else 'video_url'
            c.execute('UPDATE media_jobs SET ' + field + '=%s,last_error=NULL,updated_at=%s WHERE id=%s', (url, utcnow(), job_id))
            if stage == 'image' and current['kind'] == 'video':
                c.execute("UPDATE media_jobs SET status='video_ready' WHERE id=%s", (job_id,))
            else:
                finish(c, current, url)
    except (fal.MediaError, ValueError) as error:
        mark_review(job_id, str(error) if isinstance(error, fal.MediaError) else 'تعذر قراءة بيانات المهمة. لم يُكرر التوليد.', job['status'])


@router.post('/media-studio/{job_id}/sync')
async def sync_job(job_id: int, request: Request):
    session = media_admin(request)
    await form_data(request, session)
    if not one('SELECT id FROM media_jobs WHERE id=?', (job_id,)):
        raise HTTPException(404)
    await run_in_threadpool(process_job, job_id, allow_paid=False)
    return RedirectResponse('/media-studio/' + str(job_id), 303)


def tick():
    for job in rows("SELECT id FROM media_jobs WHERE status IN ('image_submitting','image_pending','video_ready','video_submitting','video_pending') ORDER BY updated_at LIMIT 5"):
        process_job(job['id'])


@router.get('/media-pricing', response_class=HTMLResponse)
def connection_check(request: Request):
    media_admin(request)
    try:
        key, _ = credential()
        quote = fal.prices(key)
    except fal.MediaError as error:
        return error_page(str(error))
    body = '<div class="hero"><h1>نجح التحقق من مفتاح fal.ai</h1><p>قبلت المنصة المفتاح وأعادت أسعار النموذجين. لم يبدأ أي توليد، ولم يُفحص رصيد الحساب.</p></div>'
    body += '<div class="card"><p>صورة واحدة: <b>' + str(quote['image']) + ' USD</b></p>'
    body += '<p>صورة ثم فيديو خمس ثوانٍ: <b>' + str(quote['image'] + quote['video']) + ' USD</b> قبل الضرائب.</p>'
    body += '<a class="btn" href="/media-studio">تجهيز طلب الإنتاج ومراجعة التكلفة</a></div>'
    return HTMLResponse(page(body), headers={'Cache-Control': 'no-store'})


def register_worker(app):
    async def loop():
        while True:
            try:
                await run_in_threadpool(tick)
            except Exception:
                # Durable claims survive process/provider errors; never log credentials.
                pass
            await asyncio.sleep(15)

    @app.on_event('startup')
    async def start():
        app.state.media_worker = asyncio.create_task(loop())

    @app.on_event('shutdown')
    async def stop():
        task = getattr(app.state, 'media_worker', None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
