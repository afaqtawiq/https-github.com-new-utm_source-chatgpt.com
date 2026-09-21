"""Durable, budget-approved cinematic advertisements; never auto-publishes."""
import asyncio
from contextlib import suppress
import datetime as dt
from decimal import Decimal
import json
import os
import re
import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from app import advert_provider as provider, advert_render as renderer
from app.advert_spec import default_plan, plan_from_form, step_specs
from app.media_fal import MediaError, asset_url
from app.media_settings import media_admin
from app.media_studio import credential, enabled
from app.social_content import e, page, parse
from app.social_publishing import csrf, hidden_csrf
from app.storage import db, one, rows, utcnow

router = APIRouter()
EXPORT_QUOTA = 128 * 1024 * 1024
LABELS = {'draft': 'بانتظار اعتماد تكلفة الإعلان', 'running': 'جارٍ إنتاج المشاهد والتعليق',
          'rendering': 'جارٍ المونتاج وإضافة الهوية', 'complete': 'اكتمل الإعلان — جاهز للمراجعة',
          'needs_review': 'تحتاج المهمة مراجعة'}


def init_adverts():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS advert_brand(
            id INTEGER PRIMARY KEY CHECK(id=1), logo BYTEA NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
            updated_by BIGINT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS advert_jobs(
            id BIGSERIAL PRIMARY KEY, status TEXT NOT NULL, plan_json TEXT NOT NULL, logo BYTEA,
            total_cost NUMERIC(12,6) NOT NULL, credential_version TIMESTAMPTZ NOT NULL,
            quote_expires_at TIMESTAMPTZ NOT NULL, approved_by BIGINT, approved_at TIMESTAMPTZ,
            reserved_bytes BIGINT NOT NULL DEFAULT 0, last_error TEXT,
            created_by BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS advert_steps(
            id BIGSERIAL PRIMARY KEY, job_id BIGINT NOT NULL REFERENCES advert_jobs(id),
            ordinal INTEGER NOT NULL, step_key TEXT NOT NULL, spec_json TEXT NOT NULL,
            status TEXT NOT NULL, cost_limit NUMERIC(12,6) NOT NULL, receipt TEXT, asset_url TEXT,
            updated_at TIMESTAMPTZ NOT NULL, UNIQUE(job_id,ordinal), UNIQUE(job_id,step_key))''')
        c.execute('''CREATE TABLE IF NOT EXISTS advert_exports(
            token TEXT PRIMARY KEY, job_id BIGINT NOT NULL REFERENCES advert_jobs(id), ratio TEXT NOT NULL,
            payload BYTEA NOT NULL, duration DOUBLE PRECISION NOT NULL, width INTEGER NOT NULL,
            height INTEGER NOT NULL, content_id BIGINT UNIQUE REFERENCES social_content(id),
            created_at TIMESTAMPTZ NOT NULL, UNIQUE(job_id,ratio))''')
        c.execute('CREATE INDEX IF NOT EXISTS advert_status_idx ON advert_jobs(status)')


init_adverts()


def audit(c, user_id, action, job_id, summary):
    c.execute('''INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at)
        VALUES(%s,%s,'advert_job',%s,%s,%s)''', (user_id, action, job_id, summary, utcnow()))


def origin():
    value = os.getenv('AFAAQ_PUBLIC_ORIGIN', 'https://gulf-logistics-ai-v7-production.up.railway.app').rstrip('/')
    u = urlsplit(value)
    if u.scheme != 'https' or not u.hostname or u.path or u.query or u.fragment or u.username or u.password or u.port not in (None, 443):
        raise MediaError('عنوان ملفات الإعلان العام غير مهيأ.')
    return value


def export_url(token):
    return origin() + '/media-exports/' + token + '.mp4'


def job_record(job_id):
    job = one('SELECT * FROM advert_jobs WHERE id=?', (job_id,))
    if not job:
        raise HTTPException(404)
    return job


async def data_form(request, session):
    raw = await request.body()
    if len(raw) > 32768:
        raise HTTPException(413)
    try:
        data = parse(raw)
    except (UnicodeError, ValueError):
        raise HTTPException(400) from None
    csrf(session, data)
    return data


def error(message, status=409):
    return HTMLResponse(page('<div class="card"><p>' + e(message) +
        '</p><a class="btn" href="/advert-studio">استوديو الإعلان</a></div>'), status_code=status,
        headers={'Cache-Control': 'no-store'})


def prepare_plan(plan, user_id):
    renderer.prerequisites()
    origin()
    key, version = credential()
    current_rates = provider.rates(key)
    specs = step_specs(plan)
    costs = [provider.step_cost(s, current_rates) for s in specs]
    total = sum(costs, Decimal(0))
    if total > 20:
        raise MediaError('التكلفة تتجاوز سقف هذا القالب؛ يلزم مراجعة إعداداته.')
    now = utcnow()
    with db() as c:
        brand = c.execute('SELECT logo FROM advert_brand WHERE id=1').fetchone()
        job = c.execute('''INSERT INTO advert_jobs(status,plan_json,logo,total_cost,credential_version,
            quote_expires_at,created_by,created_at,updated_at)
            VALUES('draft',%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            (json.dumps(plan, ensure_ascii=False), brand['logo'] if brand else None, total, version,
             now + dt.timedelta(minutes=15), user_id, now, now)).fetchone()
        for n, (spec, cost) in enumerate(zip(specs, costs)):
            c.execute('''INSERT INTO advert_steps(job_id,ordinal,step_key,spec_json,status,cost_limit,updated_at)
                VALUES(%s,%s,%s,%s,'ready',%s,%s)''',
                (job['id'], n, spec['key'], json.dumps(spec, ensure_ascii=False), cost, now))
        audit(c, user_id, 'advert_quote_prepared', job['id'], 'Prepared priced storyboard; no generation submitted.')
    return job['id']


def requote(job_id, user_id):
    job = job_record(job_id)
    if job['status'] != 'draft':
        raise MediaError('يمكن تحديث تكلفة المسودات التي لم تبدأ فقط.')
    key, version = credential()
    current_rates = provider.rates(key)
    with db() as c:
        locked = c.execute('SELECT status FROM advert_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if locked['status'] != 'draft':
            raise MediaError('بدأ الإعلان بالفعل؛ لم تتغير الموافقة.')
        steps = c.execute('SELECT * FROM advert_steps WHERE job_id=%s ORDER BY ordinal', (job_id,)).fetchall()
        total = Decimal(0)
        for step in steps:
            cost = provider.step_cost(json.loads(step['spec_json']), current_rates)
            c.execute('UPDATE advert_steps SET cost_limit=%s WHERE id=%s', (cost, step['id']))
            total += cost
        if total > 20:
            raise MediaError('تجاوزت التكلفة سقف القالب.')
        c.execute('''UPDATE advert_jobs SET total_cost=%s,credential_version=%s,quote_expires_at=%s,
            updated_at=%s WHERE id=%s''', (total, version, utcnow()+dt.timedelta(minutes=15), utcnow(), job_id))
        audit(c, user_id, 'advert_requoted', job_id, 'Refreshed price only; no generation.')


def approve(job_id, user_id, quote_stamp):
    enabled()
    renderer.prerequisites()
    job = job_record(job_id)
    key, _ = credential(job['credential_version'])
    current_rates = provider.rates(key)
    with db() as c:
        # One shared reservation lock prevents concurrent jobs overfilling the media budget.
        c.execute('SELECT pg_advisory_xact_lock(752201)')
        locked = c.execute('SELECT * FROM advert_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if (locked['status'] != 'draft' or locked['quote_expires_at'] <= utcnow()
                or locked['credential_version'] != job['credential_version']
                or locked['quote_expires_at'].isoformat() != quote_stamp):
            raise MediaError('انتهى عرض التكلفة أو بدأ الطلب أو تغير المفتاح. راجع حالة الإعلان.')
        steps = c.execute('SELECT * FROM advert_steps WHERE job_id=%s', (job_id,)).fetchall()
        if any(provider.step_cost(json.loads(s['spec_json']), current_rates) > s['cost_limit'] for s in steps):
            raise MediaError('ارتفع سعر إحدى مراحل الإنتاج؛ حدّث عرض التكلفة أولًا.')
        reservation = len(json.loads(locked['plan_json'])['ratios']) * renderer.MAX_EXPORT
        used = c.execute('SELECT COALESCE(SUM(octet_length(payload)),0) n FROM advert_exports').fetchone()['n']
        reserved = c.execute('SELECT COALESCE(SUM(reserved_bytes),0) n FROM advert_jobs').fetchone()['n']
        if used + reserved + reservation > EXPORT_QUOTA:
            raise MediaError('المساحة المخصصة للإعلانات ممتلئة؛ لم يبدأ الإنتاج المدفوع.')
        now = utcnow()
        c.execute('''UPDATE advert_jobs SET status='running',approved_by=%s,approved_at=%s,
            reserved_bytes=%s,last_error=NULL,updated_at=%s WHERE id=%s''', (user_id, now, reservation, now, job_id))
        audit(c, user_id, 'advert_cost_approved', job_id, 'Approved maximum USD ' + str(locked['total_cost']) + '; publishing not approved.')


def review(job_id, message, expected='running'):
    with db() as c:
        c.execute("UPDATE advert_jobs SET status='needs_review',last_error=%s,updated_at=%s WHERE id=%s AND status=%s",
                  (message, utcnow(), job_id, expected))


def process(job_id, *, allow_paid=True):
    job = job_record(job_id)
    if job['status'] != 'running':
        return
    step = one("SELECT * FROM advert_steps WHERE job_id=? AND status!='complete' ORDER BY ordinal LIMIT 1", (job_id,))
    if not step:
        if allow_paid:
            render_job(job_id)
        return
    if step['status'] == 'submitting':
        if step['updated_at'] < utcnow() - dt.timedelta(minutes=3):
            review(job_id, 'انقطع تأكيد طلب مدفوع. راجع سجل fal.ai؛ لن يُعاد إرساله تلقائيًا.')
        return
    try:
        key, _ = credential(job['credential_version'])
        spec = json.loads(step['spec_json'])
        if step['status'] == 'pending':
            url = provider.result(key, spec['stage'], json.loads(step['receipt']))
            if url:
                with db() as c:
                    c.execute("UPDATE advert_steps SET status='complete',asset_url=%s,updated_at=%s WHERE id=%s AND status='pending' AND receipt=%s",
                              (url, utcnow(), step['id'], step['receipt']))
            return
        if step['status'] != 'ready' or not allow_paid:
            return
        enabled()
        current_rates = provider.rates(key)
        if provider.step_cost(spec, current_rates) > step['cost_limit']:
            raise MediaError('ارتفع سعر المرحلة عن السقف المعتمد؛ حُفظت النتائج السابقة وتوقف الإنفاق.')
        dependency_url = None
        with db() as c:
            locked = c.execute('SELECT status,approved_by FROM advert_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
            if locked['status'] != 'running' or not locked['approved_by']:
                return
            if spec.get('depends_on'):
                source = c.execute("SELECT asset_url FROM advert_steps WHERE job_id=%s AND step_key=%s AND status='complete'",
                                   (job_id, spec['depends_on'])).fetchone()
                if not source:
                    return
                dependency_url = source['asset_url']
            claimed = c.execute("UPDATE advert_steps SET status='submitting',updated_at=%s WHERE id=%s AND status='ready' RETURNING id",
                                (utcnow(), step['id'])).fetchone()
            if not claimed:
                return
        # The durable submitting claim commits before the paid request.
        receipt = provider.submit(key, spec, image_url=dependency_url)
        with db() as c:
            c.execute("UPDATE advert_steps SET status='pending',receipt=%s,updated_at=%s WHERE id=%s AND status='submitting'",
                      (json.dumps(receipt), utcnow(), step['id']))
    except (MediaError, ValueError, KeyError) as exc:
        review(job_id, str(exc) if isinstance(exc, MediaError) else 'بيانات المرحلة غير مكتملة؛ لم يُكرر التوليد.')


def render_job(job_id):
    enabled()
    # A session-scoped lock serializes CPU/memory-heavy rendering across replicas.
    with db() as lease:
        if not lease.execute('SELECT pg_try_advisory_lock(752202) acquired').fetchone()['acquired']:
            return
        try:
            with db() as c:
                job = c.execute('SELECT * FROM advert_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
                if not job or job['status'] != 'running' or not job['approved_by']:
                    return
                steps = c.execute('SELECT step_key,status,asset_url FROM advert_steps WHERE job_id=%s', (job_id,)).fetchall()
                if not steps or any(s['status'] != 'complete' for s in steps):
                    return
                c.execute("UPDATE advert_jobs SET status='rendering',updated_at=%s WHERE id=%s", (utcnow(), job_id))
            plan = json.loads(job['plan_json'])
            outputs = {s['step_key']: s['asset_url'] for s in steps}
            if plan.get('reused_video_url'):
                outputs['video-9:16-0'] = plan['reused_video_url']
            files = renderer.render(plan, outputs, logo=bytes(job['logo']) if job['logo'] else None)
            if set(files) != set(plan['ratios']) or any(len(f['data']) > renderer.MAX_EXPORT for f in files.values()):
                raise MediaError('ملفات الإعلان لا تطابق المقاسات المعتمدة.')
            with db() as c:
                locked = c.execute('SELECT status FROM advert_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
                if locked['status'] != 'rendering':
                    return
                for ratio, output in files.items():
                    token = secrets.token_hex(24)
                    url = export_url(token)
                    draft = c.execute('''INSERT INTO social_content(title,platform,content_type,body,media_url,status,created_by,created_at,updated_at)
                        VALUES(%s,%s,'video',%s,%s,'draft',%s,%s,%s) RETURNING id''',
                        (plan['title'] + (' — عمودي' if ratio == '9:16' else ' — أفقي'),
                         'YouTube+TikTok' if ratio == '9:16' else 'YouTube', plan['caption'], url, job['created_by'], utcnow(), utcnow())).fetchone()
                    c.execute('''INSERT INTO advert_exports(token,job_id,ratio,payload,duration,width,height,content_id,created_at)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                        (token, job_id, ratio, output['data'], output['duration'], output['width'], output['height'], draft['id'], utcnow()))
                c.execute("UPDATE advert_jobs SET status='complete',reserved_bytes=0,last_error=NULL,updated_at=%s WHERE id=%s", (utcnow(), job_id))
                audit(c, job['approved_by'], 'advert_completed', job_id, 'Rendered audio/video and created separate review drafts; no publishing.')
        except MediaError as exc:
            review(job_id, str(exc), 'rendering')
        except Exception:
            review(job_id, 'تعذر حفظ أو مونتاج الإعلان. النتائج الأصلية محفوظة؛ يمكن إعادة المونتاج دون توليد.', 'rendering')
        finally:
            lease.execute('SELECT pg_advisory_unlock(752202)')


def tick():
    for job in rows("SELECT id,status,updated_at FROM advert_jobs WHERE status IN ('running','rendering') ORDER BY id LIMIT 4"):
        if job['status'] == 'rendering':
            if job['updated_at'] < utcnow() - dt.timedelta(minutes=30):
                review(job['id'], 'انقطع المونتاج؛ أعد المونتاج من النتائج المحفوظة دون توليد.', 'rendering')
        else:
            process(job['id'])


def register_worker(app):
    async def loop():
        while True:
            try:
                await run_in_threadpool(tick)
            except Exception:
                pass  # Durable claims survive; never log provider credentials or raw bodies.
            await asyncio.sleep(10)
    @app.on_event('startup')
    async def start():
        app.state.advert_worker = asyncio.create_task(loop())
    @app.on_event('shutdown')
    async def stop():
        task = getattr(app.state, 'advert_worker', None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


@router.get('/advert-studio', response_class=HTMLResponse)
def studio(request: Request):
    session = media_admin(request)
    plan = default_plan()
    body = '<div class="nav"><a href="/media-studio">استوديو الإنتاج</a><a href="/content-center">مركز المحتوى</a></div>'
    body += '<div class="hero"><h1>إعلان آفاق طويق المتكامل</h1><p>أربع لقطات سينمائية وخاتمة · 25–30 ثانية · تعليق عربي رجالي ونصوص وهوية</p></div>'
    body += '<div class="card"><h2>هوية الإعلان</h2>'
    if one('SELECT id FROM advert_brand WHERE id=1'):
        body += '<img src="/advert-studio/brand/logo.png" alt="شعار آفاق المحفوظ" style="max-width:240px;max-height:150px"><p>يُحفظ الشعار مع كل طلب حتى لا يتغير إعلان معتمد عند رفع شعار جديد.</p>'
    else:
        body += '<p>لا يوجد ملف شعار محفوظ. يظهر اسم «آفاق طويق» كنص في المعاينة؛ أضف الشعار المعتمد إذا أردت إدراجه في الإعلان.</p>'
    body += '<form method="post" enctype="multipart/form-data" action="/advert-studio/brand">' + hidden_csrf(session)
    body += '<label>ملف الشعار — PNG أو JPEG أو WebP، حتى 2 ميغابايت<input type="file" name="logo" accept="image/png,image/jpeg,image/webp" required></label><button class="btn">حفظ الشعار</button></form></div>'
    body += '<form method="post" action="/advert-studio/prepare">' + hidden_csrf(session)
    body += '<div class="card"><h2>خطة الإعلان</h2><label>العنوان<input name="title" maxlength="150" required value="' + e(plan['title']) + '"></label>'
    body += '<label>نسخ الإعلان<select name="format"><option value="both">عمودي 9:16 وأفقي 16:9 — مشاهد أصلية لكل مقاس</option><option value="9:16">عمودي فقط</option><option value="16:9">أفقي فقط</option></select></label>'
    reuse = rows("SELECT id,title FROM media_jobs WHERE status='complete' AND kind='video' AND ratio='9:16' AND video_url IS NOT NULL ORDER BY id DESC LIMIT 10")
    body += '<label>إعادة استخدام لقطة عمودية أولى<select name="reuse_job_id"><option value="">إنتاج جميع المشاهد من جديد</option>'
    body += ''.join('<option value="' + str(j['id']) + '">' + e(j['title']) + ' — طلب ' + str(j['id']) + '</option>' for j in reuse) + '</select></label>'
    body += '<p>تخفض إعادة الاستخدام تكلفة اللقطة الأولى للنسخة العمودية. راجع ملاءمتها للنص أدناه.</p>'
    body += '<label>نص المنشور<textarea name="caption" maxlength="2200" required>' + e(plan['caption']) + '</textarea></label></div>'
    for i, scene in enumerate(plan['scenes']):
        body += '<div class="card"><h2>' + str(i+1) + '. ' + e(scene['name']) + '</h2><p>نحو خمس ثوانٍ؛ يضبط المونتاج المدة بحسب طول التعليق دون قطع الكلام.</p>'
        body += '<label>نص الشاشة<input name="text_' + str(i) + '" maxlength="48" required value="' + e(scene['text']) + '"></label>'
        body += '<label>التعليق العربي<textarea name="voice_' + str(i) + '" maxlength="180" required>' + e(scene['voice']) + '</textarea></label>'
        if i < 4:
            for field, label, limit in [('image', 'وصف اللقطة', 1800), ('motion', 'حركة الكاميرا والمشهد', 1500)]:
                body += '<details><summary>' + label + '</summary><textarea dir="auto" name="' + field + '_' + str(i) + '" maxlength="' + str(limit) + '" required>' + e(scene[field]) + '</textarea></details>'
        body += '</div>'
    body += '<div class="card"><p>صوت رجالي عربي اصطناعي بنبرة منخفضة، ومؤثرات انتقال أصلية هادئة. المشاهد تمثيلية مولدة بالذكاء الاصطناعي. الناتج مسودات للمراجعة، ولا يُنشر تلقائيًا.</p><button class="btn">تجهيز الإعلان ومعاينة الهوية وحساب التكلفة — دون توليد</button></div></form>'
    jobs = rows('SELECT id,status,plan_json FROM advert_jobs ORDER BY id DESC LIMIT 20')
    body += '<div class="card"><h2>إعلاناتي</h2>' + ''.join('<p><a class="btn" href="/advert-studio/' + str(j['id']) + '">' + e(json.loads(j['plan_json'])['title']) + '</a> · ' + e(LABELS.get(j['status'], j['status'])) + '</p>' for j in jobs) + '</div>'
    return HTMLResponse(page(body), headers={'Cache-Control': 'no-store'})


@router.post('/advert-studio/brand')
async def upload_logo(request: Request):
    session = media_admin(request)
    length = request.headers.get('content-length', '')
    if not length.isdigit() or int(length) > 3 * 1024 * 1024:
        raise HTTPException(413)
    async with request.form(max_files=1, max_fields=2) as form:
        csrf(session, form)
        upload = form.get('logo')
        if not upload or not hasattr(upload, 'read'):
            return error('اختر ملف شعار.')
        try:
            logo = await run_in_threadpool(renderer.normalized_logo, await upload.read(2*1024*1024+1))
        except MediaError as exc:
            return error(str(exc))
    with db() as c:
        c.execute('''INSERT INTO advert_brand(id,logo,updated_at,updated_by) VALUES(1,%s,%s,%s)
            ON CONFLICT(id) DO UPDATE SET logo=EXCLUDED.logo,updated_at=EXCLUDED.updated_at,updated_by=EXCLUDED.updated_by''',
            (logo, utcnow(), session['user_id']))
    return RedirectResponse('/advert-studio', 303)


@router.get('/advert-studio/brand/logo.png')
def logo_page(request: Request):
    media_admin(request)
    saved = one('SELECT logo FROM advert_brand WHERE id=1')
    if not saved:
        raise HTTPException(404)
    return Response(bytes(saved['logo']), media_type='image/png', headers={'Cache-Control': 'no-store'})


@router.post('/advert-studio/prepare')
async def prepare_route(request: Request):
    session = media_admin(request)
    data = await data_form(request, session)
    try:
        plan = plan_from_form(data)
        if data.get('reuse_job_id') and '9:16' in plan['ratios']:
            if not re.fullmatch(r'[0-9]{1,18}', data['reuse_job_id']):
                raise MediaError('اللقطة المختارة غير صالحة.')
            reuse = one("SELECT id,video_url FROM media_jobs WHERE id=? AND status='complete' AND kind='video' AND ratio='9:16'", (int(data['reuse_job_id']),))
            if not reuse:
                raise MediaError('اختر لقطة مكتملة من الاستوديو.')
            plan['reuse_job_id'] = reuse['id']
            plan['reused_video_url'] = asset_url(reuse['video_url'], 'video')
        job_id = await run_in_threadpool(prepare_plan, plan, session['user_id'])
    except MediaError as exc:
        return error(str(exc))
    return RedirectResponse('/advert-studio/' + str(job_id), 303)


@router.get('/advert-studio/{job_id}', response_class=HTMLResponse)
def detail(job_id: int, request: Request):
    session = media_admin(request)
    job = job_record(job_id)
    plan = json.loads(job['plan_json'])
    steps = rows('SELECT step_key,status,cost_limit,spec_json FROM advert_steps WHERE job_id=? ORDER BY ordinal', (job_id,))
    body = '<div class="nav"><a href="/advert-studio">استوديو الإعلان</a><a href="/content-center">مركز المحتوى</a></div>'
    body += '<div class="hero"><h1>' + e(plan['title']) + '</h1><p>' + e(LABELS.get(job['status'], job['status'])) + '</p></div>'
    body += '<div class="card"><p>25–30 ثانية · ' + e(' + '.join(plan['ratios'])) + ' · تعليق عربي رجالي</p><p>' + ('شعار محفوظ مع الإعلان.' if job['logo'] else 'هوية نصية باسم آفاق طويق؛ لم يُرفق ملف شعار.') + '</p>'
    if plan.get('reuse_job_id'):
        body += '<p>ستُستخدم اللقطة الأولى من طلب الإنتاج ' + str(plan['reuse_job_id']) + ' للنسخة العمودية دون توليدها مجددًا.</p>'
    body += '<p style="white-space:pre-wrap">' + e(plan['caption']) + '</p></div>'
    totals = {stage: sum((s['cost_limit'] for s in steps if json.loads(s['spec_json'])['stage'] == stage), Decimal(0)) for stage in ('image','video','voice')}
    body += '<div class="card"><h2>تكلفة الإنتاج قبل الاعتماد</h2><p>الصور: ' + format(totals['image'], '.4f') + ' USD · المشاهد: ' + format(totals['video'], '.4f') + ' USD · سقف الصوت: ' + format(totals['voice'], '.4f') + ' USD</p>'
    body += '<p><b>إجمالي سقف التوليد: ' + format(job['total_cost'], '.4f') + ' USD قبل الضرائب، من رصيد fal.ai.</b></p><p>الصوت محسوب تحفظيًا بحد أدنى ألف حرف لكل مقطع؛ الاستهلاك الفعلي قد يقل. المونتاج يجري على خادم الوكيل ولا يستدعي نموذج توليد إضافيًا.</p>'
    if job['last_error']:
        body += '<p role="alert">' + e(job['last_error']) + '</p>'
    if job['status'] == 'draft':
        from app.mfa_stepup import recent_stepup
        body += '<p>صلاحية العرض حتى: ' + e(job['quote_expires_at']) + '</p>'
        body += '<form method="post" action="/advert-studio/' + str(job_id) + '/requote">' + hidden_csrf(session) + '<button class="btn">تحديث السعر دون توليد</button></form>'
        if job['quote_expires_at'] <= utcnow():
            body += '<p>انتهى عرض التكلفة؛ حدّث السعر قبل الاعتماد.</p>'
        elif not recent_stepup(session['id']):
            body += '<a class="btn" href="/mfa/step-up?next=/advert-studio/' + str(job_id) + '">التحقق قبل اعتماد الإنتاج</a>'
        else:
            body += '<form method="post" action="/advert-studio/' + str(job_id) + '/run">' + hidden_csrf(session)
            body += '<input type="hidden" name="quote_stamp" value="' + e(job['quote_expires_at'].isoformat()) + '">'
            body += '<label><input type="checkbox" name="approve_cost" value="yes" required style="width:auto"> أوافق على إنتاج الإعلان بالمشاهد والنص والصوت والهوية المعروضة، ضمن سقف التكلفة أعلاه. أراجع النتيجة قبل النشر.</label><button class="btn">اعتماد التكلفة وبدء الإنتاج</button></form>'
    if job['status'] == 'running':
        body += '<p>تُستكمل المراحل تلقائيًا. لا تُعد إرسال طلب الإنتاج.</p><form method="post" action="/advert-studio/' + str(job_id) + '/sync">' + hidden_csrf(session) + '<button class="btn">تحديث نتيجة الطلب الموجود — دون توليد</button></form>'
    if job['status'] == 'needs_review' and all(s['status'] == 'complete' for s in steps):
        body += '<form method="post" action="/advert-studio/' + str(job_id) + '/retry-render">' + hidden_csrf(session) + '<button class="btn">إعادة المونتاج من النتائج المحفوظة — دون توليد</button></form>'
    body += '</div><div class="card"><h2>السيناريو والتعليق</h2><table><tr><th>اللقطة</th><th>نص الشاشة</th><th>التعليق الرجالي</th></tr>'
    for i, scene in enumerate(plan['scenes']):
        body += '<tr><td>' + str(i+1) + '. ' + e(scene['name']) + '</td><td>' + e(scene['text']) + '</td><td>' + e(scene['voice']) + '</td></tr>'
    body += '</table><p>تتكيّف مدة اللقطة مع التعليق، وتظهر الدعوة لطلب عرض السعر في الخاتمة.</p></div>'
    body += '<div class="card"><h2>معاينة الخاتمة دون توليد</h2>'
    for ratio in plan['ratios']:
        slug = 'vertical' if ratio == '9:16' else 'horizontal'
        body += '<img alt="معاينة الخاتمة ' + ratio + '" src="/advert-studio/' + str(job_id) + '/preview/' + slug + '.png" style="max-width:100%;max-height:560px;margin:8px">'
    body += '</div>'
    if job['status'] != 'draft':
        done = sum(s['status'] == 'complete' for s in steps)
        body += '<div class="card"><h2>مراحل الإنتاج</h2><p>' + str(done) + ' / ' + str(len(steps)) + ' مكتملة</p><details><summary>تفاصيل المراحل</summary>' + ''.join('<p>' + e(s['step_key']) + ' · ' + e(s['status']) + '</p>' for s in steps) + '</details></div>'
    for output in rows('SELECT token,ratio,duration,content_id FROM advert_exports WHERE job_id=? ORDER BY ratio DESC', (job_id,)):
        url = export_url(output['token'])
        body += '<div class="card"><h2>الإعلان ' + e(output['ratio']) + '</h2><video controls preload="metadata" src="' + e(url) + '" style="max-width:100%;max-height:620px"></video><p>' + format(output['duration'], '.1f') + ' ثانية</p><a class="btn" href="' + e(url) + '">فتح ملف الإعلان</a> <a class="btn" href="/content-center/' + str(output['content_id']) + '">مراجعة المسودة واعتماد النشر</a></div>'
    html = page(body)
    if job['status'] in ('running','rendering'):
        html = html.replace('<title>', '<meta http-equiv="refresh" content="20"><title>', 1)
    return HTMLResponse(html, headers={'Cache-Control': 'no-store'})


@router.get('/advert-studio/{job_id}/preview/{size}.png')
def preview(job_id: int, size: str, request: Request):
    media_admin(request)
    job = job_record(job_id)
    ratio = {'vertical':'9:16','horizontal':'16:9'}.get(size)
    plan = json.loads(job['plan_json'])
    if ratio not in plan['ratios']:
        raise HTTPException(404)
    return Response(renderer.card(ratio, plan['scenes'][-1], end=True, logo=bytes(job['logo']) if job['logo'] else None, preview=True),
                    media_type='image/png', headers={'Cache-Control': 'no-store'})


@router.post('/advert-studio/{job_id}/requote')
async def requote_route(job_id: int, request: Request):
    session = media_admin(request)
    await data_form(request, session)
    try:
        await run_in_threadpool(requote, job_id, session['user_id'])
    except MediaError as exc:
        return error(str(exc))
    return RedirectResponse('/advert-studio/' + str(job_id), 303)


@router.post('/advert-studio/{job_id}/run')
async def run_route(job_id: int, request: Request):
    session = media_admin(request)
    data = await data_form(request, session)
    if data.get('approve_cost') != 'yes':
        return error('يلزم اعتماد تكلفة الإعلان ومحتواه قبل الإنتاج.')
    try:
        await run_in_threadpool(approve, job_id, session['user_id'], data.get('quote_stamp', ''))
    except MediaError as exc:
        return error(str(exc))
    return RedirectResponse('/advert-studio/' + str(job_id), 303)


@router.post('/advert-studio/{job_id}/sync')
async def sync_route(job_id: int, request: Request):
    session = media_admin(request)
    await data_form(request, session)
    await run_in_threadpool(process, job_id, allow_paid=False)
    return RedirectResponse('/advert-studio/' + str(job_id), 303)


@router.post('/advert-studio/{job_id}/retry-render')
async def retry_render(job_id: int, request: Request):
    session = media_admin(request)
    await data_form(request, session)
    with db() as c:
        job = c.execute('SELECT status,approved_by FROM advert_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if not job or job['status'] != 'needs_review' or not job['approved_by']:
            return error('المهمة ليست جاهزة لإعادة المونتاج.')
        pending = c.execute("SELECT id FROM advert_steps WHERE job_id=%s AND status!='complete' LIMIT 1", (job_id,)).fetchone()
        if pending:
            return error('إحدى مراحل التوليد غير مكتملة؛ لا يُسمح بإعادة طلب مدفوع هنا.')
        c.execute("UPDATE advert_jobs SET status='running',last_error=NULL,updated_at=%s WHERE id=%s", (utcnow(), job_id))
        audit(c, session['user_id'], 'advert_render_requeued', job_id, 'Reuse completed assets; no new paid generation.')
    return RedirectResponse('/advert-studio/' + str(job_id), 303)


@router.api_route('/media-exports/{token}.mp4', methods=['GET','HEAD'])
def media_export(token: str, request: Request):
    if not re.fullmatch(r'[0-9a-f]{48}', token):
        raise HTTPException(404)
    record = one("""SELECT x.payload FROM advert_exports x JOIN advert_jobs j ON j.id=x.job_id
        WHERE x.token=? AND j.status='complete' AND j.approved_by IS NOT NULL""", (token,))
    if not record:
        raise HTTPException(404)
    data = bytes(record['payload'])
    total = len(data)
    start, end, status = 0, total-1, 200
    headers = {'Accept-Ranges': 'bytes', 'Cache-Control': 'public,max-age=3600,immutable',
               'Content-Disposition': 'inline; filename="afaaq-advert.mp4"', 'X-Content-Type-Options': 'nosniff'}
    requested = request.headers.get('range')
    if requested:
        match = re.fullmatch(r'bytes=([0-9]{0,20})-([0-9]{0,20})', requested)
        if not match or not any(match.groups()):
            return Response(status_code=416, headers={'Content-Range': f'bytes */{total}'})
        left, right = match.groups()
        if not left:
            count = int(right)
            start = max(0, total-count) if count > 0 else total
        else:
            start = int(left)
            end = min(total-1, int(right)) if right else total-1
        if start >= total or start > end:
            return Response(status_code=416, headers={'Content-Range': f'bytes */{total}'})
        status = 206
        headers['Content-Range'] = f'bytes {start}-{end}/{total}'
    headers['Content-Length'] = str(end-start+1)
    return Response(b'' if request.method == 'HEAD' else data[start:end+1], status_code=status, media_type='video/mp4', headers=headers)
