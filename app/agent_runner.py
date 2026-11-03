"""Work-computer runner for the Afaq agent (owner request, Nov 2026).

The agent itself runs on Railway and cannot touch a browser that is signed in to FASAH or a desktop program.
A small program (desktop-runner/afaq_runner.py) runs on a dedicated work computer, in its OWN Chrome profile where
the owner signs in himself. It asks this server for approved tasks, executes them, and reports every step
(text + optional screenshot), the files it downloaded (verified: size, type, opens) and the result.

Safety:
- Device tokens are generated here, shown once and stored only as SHA-256; nothing in the code holds a password,
  OTP or session cookie. The runner never types passwords or OTPs.
- Only allowlisted domains (RUNNER_ALLOWED_DOMAINS) — checked here when a task is created and again on the runner.
- Task kinds are read-only for now (read pages, download, list FASAH declarations). Anything that submits forms,
  pays, deletes, sends data or changes account settings is not a kind the runner accepts.
- Every task can be stopped from WhatsApp or /agent-runner; the runner checks after each step.
- A task is «done» only when the runner verified its result (e.g. the file exists, has the right type and opens).
"""
import base64
import datetime as dt
import hashlib
import html
import json
import os
import re
import secrets
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.storage import db, utcnow

router = APIRouter()
DEFAULT_DOMAINS = 'fasah.zatca.gov.sa,zatca.gov.sa,gulf-logistics-ai-v7-production.up.railway.app'
KINDS = {
    'download_test': 'تجربة: تنزيل ملف تجريبي من النظام والتحقق منه',
    'read_page': 'قراءة صفحة مسموحة وحفظ نصها وصورة منها',
    'download_file': 'تنزيل ملف من رابط مسموح والتحقق منه',
    'fasah_declarations': 'قراءة قائمة البيانات في فسح (استيراد/تصدير) وحفظها كملف CSV — قراءة فقط',
}
STATUS_AR = {'queued': 'بالانتظار', 'running': 'قيد التنفيذ', 'stopping': 'جارٍ الإيقاف', 'stopped': 'أوقفت',
             'done': 'نجحت وتم التحقق ✅', 'failed': 'فشلت ❌'}
_READY = False


def allowed_domains():
    return [d.strip().lower() for d in os.getenv('RUNNER_ALLOWED_DOMAINS', DEFAULT_DOMAINS).split(',') if d.strip()]


def domain_allowed(url):
    host = (urlparse(str(url or '')).hostname or '').lower()
    return bool(host) and urlparse(url).scheme == 'https' and any(host == d or host.endswith('.' + d) for d in allowed_domains())


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS runner_devices(id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
            enabled BOOLEAN NOT NULL DEFAULT TRUE, last_seen TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS runner_tasks(id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL, params_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', device_id BIGINT, created_by TEXT, result_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ)''')
        c.execute('''CREATE TABLE IF NOT EXISTS runner_steps(id BIGSERIAL PRIMARY KEY, task_id BIGINT NOT NULL, ok BOOLEAN NOT NULL,
            text TEXT NOT NULL, screenshot BYTEA, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS runner_files(id BIGSERIAL PRIMARY KEY, task_id BIGINT NOT NULL, name TEXT NOT NULL,
            mime TEXT NOT NULL, size BIGINT NOT NULL, sha256 TEXT NOT NULL, verified BOOLEAN NOT NULL, data BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL)''')
    _READY = True


# ---------- tasks (from WhatsApp / page) ----------

def create_task(kind, params, actor=''):
    init()
    if kind not in KINDS:
        return None, 'نوع المهمة غير مدعوم. المتاح: ' + '، '.join(KINDS.values())
    params = {k: v for k, v in (params or {}).items() if v not in (None, '')}
    if kind in ('read_page', 'download_file') and not domain_allowed(params.get('url')):
        return None, 'الموقع غير مسموح. المواقع المسموحة: ' + '، '.join(allowed_domains())
    if kind == 'fasah_declarations':
        params['which'] = 'export' if str(params.get('which', '')).startswith(('ex', 'تص')) else 'import'
    with db() as c:
        tid = c.execute('INSERT INTO runner_tasks(kind,params_json,created_by,created_at) VALUES(%s,%s,%s,%s) RETURNING id',
                        (kind, json.dumps(params, ensure_ascii=False), actor, utcnow())).fetchone()['id']
        device = c.execute('SELECT MAX(last_seen) s FROM runner_devices WHERE enabled').fetchone()['s']
    online = device and (dt.datetime.now(dt.timezone.utc) - device).total_seconds() < 180
    return tid, (f'🖥 أنشأت المهمة #{tid}: {KINDS[kind]}.' + ('' if online else
                 '\n⚠️ جهاز العمل غير متصل الآن؛ تبدأ المهمة عند تشغيله.') + f'\nللإيقاف اكتب: أوقف المهمة {tid}')


def stop_task(tid):
    init()
    with db() as c:
        row = c.execute("""UPDATE runner_tasks SET status=CASE WHEN status='queued' THEN 'stopped' ELSE 'stopping' END,
            finished_at=CASE WHEN status='queued' THEN %s ELSE finished_at END WHERE id=%s AND status IN ('queued','running')
            RETURNING status""", (utcnow(), int(tid))).fetchone()
    return f'⏹ أوقفت المهمة #{tid}.' if row else 'المهمة غير موجودة أو انتهت.'


def task_text(tid=None):
    init()
    with db() as c:
        task = (c.execute('SELECT * FROM runner_tasks WHERE id=%s', (int(tid),)).fetchone() if tid else
                c.execute('SELECT * FROM runner_tasks ORDER BY id DESC LIMIT 1').fetchone())
        if not task:
            return 'لا توجد مهام.'
        steps = c.execute('SELECT ok,text FROM runner_steps WHERE task_id=%s ORDER BY id', (task['id'],)).fetchall()
        files = c.execute('SELECT id,name,size,verified FROM runner_files WHERE task_id=%s', (task['id'],)).fetchall()
    lines = [f"🖥 المهمة #{task['id']} — {KINDS.get(task['kind'], task['kind'])}: {STATUS_AR.get(task['status'], task['status'])}"]
    lines += [('✅ ' if s['ok'] else '❌ ') + s['text'] for s in steps[-12:]]
    from app.daily_poster import base_url
    lines += [f"📎 {f['name']} ({f['size']:,} بايت){' — تم التحقق' if f['verified'] else ''}: {base_url()}/agent-runner/files/{f['id']}" for f in files]
    return '\n'.join(lines)


# ---------- runner API ----------

def device_for(request):
    init()
    token = request.headers.get('X-Runner-Token', '')
    if not token:
        raise HTTPException(401, 'token required')
    digest = hashlib.sha256(token.encode()).hexdigest()
    with db() as c:
        device = c.execute('SELECT * FROM runner_devices WHERE token_hash=%s AND enabled', (digest,)).fetchone()
        if not device:
            raise HTTPException(401, 'unknown device')
        c.execute('UPDATE runner_devices SET last_seen=%s WHERE id=%s', (utcnow(), device['id']))
    return device


def own_task(c, device, tid):
    task = c.execute('SELECT * FROM runner_tasks WHERE id=%s AND device_id=%s', (tid, device['id'])).fetchone()
    if not task:
        raise HTTPException(404, 'task')
    return task


@router.post('/api/runner/claim')
def claim(request: Request):
    device = device_for(request)
    with db() as c:
        task = c.execute("""UPDATE runner_tasks SET status='running',device_id=%s,started_at=%s WHERE id=(
            SELECT id FROM runner_tasks WHERE status='queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *""",
                         (device['id'], utcnow())).fetchone()
    if not task:
        return {'task': None}
    params = json.loads(task['params_json'])
    if 'url' in params and not domain_allowed(params['url']):
        stop_task(task['id'])
        return {'task': None}
    return {'task': {'id': task['id'], 'kind': task['kind'], 'params': params}, 'allowed_domains': allowed_domains()}


@router.post('/api/runner/tasks/{tid}/step')
async def step(tid: int, request: Request):
    device = device_for(request)
    body = await request.json()
    shot = body.get('screenshot_b64')
    data = base64.b64decode(shot) if shot else None
    if data and len(data) > 3 * 1024 * 1024:
        data = None
    with db() as c:
        task = own_task(c, device, tid)
        c.execute('INSERT INTO runner_steps(task_id,ok,text,screenshot,created_at) VALUES(%s,%s,%s,%s,%s)',
                  (tid, bool(body.get('ok', True)), str(body.get('text') or '')[:1000], data, utcnow()))
    return {'stop': task['status'] == 'stopping'}


@router.post('/api/runner/tasks/{tid}/file')
async def upload(tid: int, request: Request):
    device = device_for(request)
    body = await request.json()
    data = base64.b64decode(body.get('data_b64') or '')
    if not data or len(data) > 25 * 1024 * 1024:
        raise HTTPException(400, 'file size')
    digest = hashlib.sha256(data).hexdigest()
    if body.get('sha256') and body['sha256'] != digest:
        raise HTTPException(400, 'checksum mismatch')
    with db() as c:
        own_task(c, device, tid)
        fid = c.execute('''INSERT INTO runner_files(task_id,name,mime,size,sha256,verified,data,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (tid, re.sub(r'[^\w.\-؀-ۿ ]', '_', str(body.get('name') or 'file'))[:120],
                                                            str(body.get('mime') or 'application/octet-stream')[:80], len(data), digest,
                                                            bool(body.get('verified')), data, utcnow())).fetchone()['id']
    return {'id': fid, 'sha256': digest}


@router.post('/api/runner/tasks/{tid}/finish')
async def finish(tid: int, request: Request):
    device = device_for(request)
    body = await request.json()
    status = body.get('status') if body.get('status') in ('done', 'failed', 'stopped') else 'failed'
    with db() as c:
        task = own_task(c, device, tid)
        if status == 'done':
            verified = c.execute('SELECT COUNT(*) n FROM runner_files WHERE task_id=%s AND verified', (tid,)).fetchone()['n']
            if task['kind'] in ('download_test', 'download_file', 'fasah_declarations') and not verified:
                status = 'failed'  # never «done» without a verified result
        c.execute('UPDATE runner_tasks SET status=%s,result_json=%s,finished_at=%s WHERE id=%s',
                  (status, json.dumps(body.get('result') or {}, ensure_ascii=False)[:20000], utcnow(), tid))
    try:
        import asyncio
        from app.owner_briefing import deliver
        asyncio.get_running_loop().create_task(deliver(task_text(tid)))
    except Exception:
        pass
    return {'status': status}


@router.get('/agent-runner/test-file.pdf')
def test_file():
    """Harmless public PDF for the first trial."""
    pdf = (b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj '
           b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj '
           b'4 0 obj<</Length 44>>stream\nBT /F1 18 Tf 30 70 Td (Afaq runner test) Tj ET\nendstream endobj '
           b'5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n')
    return Response(pdf, media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename="afaq-runner-test.pdf"'})


# ---------- admin page ----------

def admin(request):
    from app.social_publishing import admin as social_admin
    return social_admin(request)


@router.get('/agent-runner', response_class=HTMLResponse)
def page(request: Request, new_token: str = ''):
    from app.naqliat_connector import _page
    session = admin(request)
    init()
    e = lambda v: html.escape(str(v if v is not None else ''))
    with db() as c:
        devices = c.execute('SELECT * FROM runner_devices ORDER BY id').fetchall()
        tasks = c.execute('SELECT * FROM runner_tasks ORDER BY id DESC LIMIT 30').fetchall()
        steps = c.execute('SELECT id,task_id,ok,text,(screenshot IS NOT NULL) shot,created_at FROM runner_steps WHERE task_id = ANY(%s) ORDER BY id',
                          ([t['id'] for t in tasks] or [0],)).fetchall()
        files = c.execute('SELECT id,task_id,name,size,verified FROM runner_files WHERE task_id = ANY(%s)', ([t['id'] for t in tasks] or [0],)).fetchall()
    csrf = '<input type="hidden" name="csrf" value="' + e(session['csrf']) + '">'
    body = ('<div class="nav"><a href="/dashboard">الرئيسية</a></div><h1>جهاز العمل (تنفيذ في المتصفح)</h1>'
            '<p class="muted">المواقع المسموحة: ' + e('، '.join(allowed_domains())) + '. المهام الحالية قراءة وتنزيل فقط؛ '
            'لا دفع ولا حذف ولا إرسال بيانات ولا تغيير إعدادات.</p>')
    if new_token:
        body += ('<div class="card" style="border-color:#ff7900"><b>رمز الجهاز (يظهر مرة واحدة فقط — انسخه الآن إلى برنامج الجهاز):</b>'
                 '<p dir="ltr" style="font-size:18px;word-break:break-all">' + e(new_token) + '</p></div>')
    body += '<div class="card"><h2>الأجهزة</h2>' + ''.join(
        f"<p>{e(d['name'])} — {'متصل' if d['last_seen'] and (dt.datetime.now(dt.timezone.utc) - d['last_seen']).total_seconds() < 180 else 'غير متصل'}"
        f" — آخر ظهور {e(str(d['last_seen'])[:16])}</p>" for d in devices) + (
        '<form method="post" action="/agent-runner/devices">' + csrf + '<input name="name" placeholder="اسم الجهاز (مثال: كمبيوتر المكتب)" required>'
        '<button class="btn">إضافة جهاز وإنشاء رمز</button></form></div>')
    body += ('<div class="card"><h2>مهمة جديدة</h2><form method="post" action="/agent-runner/tasks">' + csrf +
             '<select name="kind">' + ''.join(f'<option value="{k}">{e(v)}</option>' for k, v in KINDS.items()) +
             '</select><input name="url" placeholder="الرابط (لقراءة صفحة أو تنزيل ملف)"><button class="btn">إنشاء</button></form></div>')
    for t in tasks:
        tsteps = [s for s in steps if s['task_id'] == t['id']]
        tfiles = [f for f in files if f['task_id'] == t['id']]
        stop = ('<form method="post" action="/agent-runner/tasks/' + str(t['id']) + '/stop" style="display:inline">' + csrf +
                '<button class="btn">إيقاف</button></form>') if t['status'] in ('queued', 'running') else ''
        body += (f"<div class='card'><h3>#{t['id']} — {e(KINDS.get(t['kind'], t['kind']))}: {e(STATUS_AR.get(t['status'], t['status']))} {stop}</h3>"
                 + ''.join(f"<div>{'✅' if s['ok'] else '❌'} {e(s['text'])}"
                           + (f" — <a href='/agent-runner/shots/{s['id']}' target=_blank>صورة</a>" if s['shot'] else '') + '</div>' for s in tsteps)
                 + ''.join(f"<div>📎 <a href='/agent-runner/files/{f['id']}'>{e(f['name'])}</a> ({f['size']:,} بايت){' ✅ تم التحقق' if f['verified'] else ''}</div>"
                           for f in tfiles) + '</div>')
    return HTMLResponse(_page('جهاز العمل', body))


@router.post('/agent-runner/devices')
async def add_device(request: Request):
    from app.social_publishing import csrf
    from urllib.parse import parse_qs, quote
    session = admin(request)
    data = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    csrf(session, data)
    init()
    token = 'afaq-runner-' + secrets.token_urlsafe(32)
    with db() as c:
        c.execute('INSERT INTO runner_devices(name,token_hash,created_at) VALUES(%s,%s,%s)',
                  (str(data.get('name') or 'جهاز')[:80], hashlib.sha256(token.encode()).hexdigest(), utcnow()))
    return RedirectResponse('/agent-runner?new_token=' + quote(token), 303)


@router.post('/agent-runner/tasks')
async def add_task(request: Request):
    from app.social_publishing import csrf
    from urllib.parse import parse_qs
    session = admin(request)
    data = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    csrf(session, data)
    create_task(data.get('kind'), {'url': data.get('url')}, 'الموقع')
    return RedirectResponse('/agent-runner', 303)


@router.post('/agent-runner/tasks/{tid}/stop')
async def stop_from_page(tid: int, request: Request):
    from app.social_publishing import csrf
    from urllib.parse import parse_qs
    session = admin(request)
    csrf(session, {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()})
    stop_task(tid)
    return RedirectResponse('/agent-runner', 303)


@router.get('/agent-runner/files/{fid}')
def file_download(fid: int, request: Request):
    from app.naqliat_connector import _session
    _session(request)
    with db() as c:
        f = c.execute('SELECT name,mime,data FROM runner_files WHERE id=%s', (fid,)).fetchone()
    if not f:
        raise HTTPException(404)
    from urllib.parse import quote
    return Response(bytes(f['data']), media_type=f['mime'], headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(f['name'])})


@router.get('/agent-runner/shots/{sid}')
def screenshot(sid: int, request: Request):
    from app.naqliat_connector import _session
    _session(request)
    with db() as c:
        s = c.execute('SELECT screenshot FROM runner_steps WHERE id=%s', (sid,)).fetchone()
    if not s or not s['screenshot']:
        raise HTTPException(404)
    return Response(bytes(s['screenshot']), media_type='image/png')
