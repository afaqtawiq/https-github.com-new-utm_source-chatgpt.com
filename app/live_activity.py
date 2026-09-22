"""Bounded live state. Never store request bodies, credentials or event history."""
from datetime import datetime, timezone
from functools import wraps
from uuid import uuid4
import logging

_ready = False


def ensure_schema():
    global _ready
    if _ready:
        return
    from app.storage import db
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(73002028)')
        c.execute("""CREATE TABLE IF NOT EXISTS agent_live_operations(
            key TEXT PRIMARY KEY, label TEXT NOT NULL, status TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
    _ready = True


def begin(label):
    try:
        ensure_schema()
        from app.storage import db
        key = str(uuid4())
        with db() as c:
            c.execute("DELETE FROM agent_live_operations WHERE key<>'last' AND updated_at<NOW()-INTERVAL '24 hours'")
            c.execute("INSERT INTO agent_live_operations(key,label,status) VALUES(%s,%s,'running')", (key, label))
        return key
    except Exception:
        logging.getLogger(__name__).warning('Live monitor unavailable')


def finish(key, label, status='completed'):
    if not key:
        return
    try:
        from app.storage import db
        with db() as c:
            c.execute('DELETE FROM agent_live_operations WHERE key=%s', (key,))
            c.execute("""INSERT INTO agent_live_operations(key,label,status) VALUES('last',%s,%s)
                ON CONFLICT(key) DO UPDATE SET label=EXCLUDED.label,status=EXCLUDED.status,updated_at=NOW()""", (label, status))
    except Exception:
        logging.getLogger(__name__).warning('Live monitor update unavailable')


def observe(label, result):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            key = begin(label)
            try:
                value = fn(*args, **kwargs)
            except Exception:
                finish(key, 'تعذر: ' + label, 'failed')
                raise
            finish(key, result)
            return value
        return wrapped
    return decorate


def request_label(path):
    groups = (
        (('discovery', 'opportun', 'source', 'intelligence'), 'البحث عن الفرص'),
        (('freight', 'shipment', 'transport', 'driver'), 'معالجة النقل'),
        (('shipping-agent', 'bill', 'tracking'), 'معالجة البوليصة وتتبع الوصول'),
        (('advert', 'media'), 'إنتاج الصور والفيديو'),
        (('social', 'publish'), 'معالجة المحتوى والنشر'),
        (('whatsapp', 'zernio'), 'معالجة واتساب'),
        (('email', 'inbox', 'reply', 'outbound'), 'معالجة البريد والرسائل'),
        (('quote', 'pricing'), 'معالجة عرض السعر'),
        (('production-monitor',), 'معالجة تنبيهات التشغيل'),
    )
    return next((label for words, label in groups if any(w in path for w in words)), 'معالجة إجراء تشغيلي')


async def tracked_request(request, call_next, session):
    from starlette.concurrency import run_in_threadpool
    if not session or request.method not in ('POST', 'PUT', 'PATCH', 'DELETE') or request.url.path.startswith(('/login', '/logout', '/identity', '/mfa')):
        return await call_next(request)
    label = request_label(request.url.path)
    key = await run_in_threadpool(begin, label)
    try:
        response = await call_next(request)
    except Exception:
        await run_in_threadpool(finish, key, 'تعذر: ' + label, 'failed')
        raise
    failed = response.status_code >= 400
    # HTTP success is not evidence of external delivery or commercial agreement.
    await run_in_threadpool(finish, key, ('تعذر: ' if failed else 'انتهت معالجة الطلب: ') + label,
                           'failed' if failed else 'completed')
    return response


STATES = {
    'carrier_offer': ('waiting', 'عرض ناقل يبحث عن حمولة'),
    'running': ('running', 'جارٍ التنفيذ'), 'rendering': ('running', 'جارٍ تركيب الفيديو'),
    'submitting': ('running', 'جارٍ تقديم الطلب للمزود'), 'sending': ('running', 'جارٍ الإرسال'),
    'contacting': ('running', 'جارٍ التواصل'),
    'image_submitting': ('running', 'جارٍ طلب الصورة'), 'image_pending': ('waiting', 'بانتظار إنتاج الصورة'),
    'video_ready': ('waiting', 'بانتظار بدء الفيديو'), 'video_submitting': ('running', 'جارٍ طلب الفيديو'),
    'video_pending': ('waiting', 'بانتظار إنتاج الفيديو'), 'pending': ('waiting', 'بانتظار المزود'),
    'scheduled': ('waiting', 'مجدول — لم يثبت النشر بعد'),
    'awaiting_owner': ('waiting', 'بانتظار رد صاحب الحمولة'),
    'ready_to_contact': ('waiting', 'جاهز للتواصل — لم يرسل'),
    'missing_owner_phone': ('blocked', 'رقم صاحب الحمولة ناقص'),
    'contact_blocked': ('blocked', 'التواصل متوقف'),
    'owner_agreed': ('waiting', 'تم الاتفاق مع صاحب الحمولة — بانتظار السائق'),
    'driver_offer_pending_approval': ('waiting', 'عرض السائق بانتظار الاعتماد'),
    'driver_accepted': ('completed', 'سُجل قبول السائق'),
    'confirmed': ('waiting', 'معتمد — تحقق من نتيجة الإرسال'),
    'draft': ('waiting', 'مسودة — لم ترسل'), 'ready': ('waiting', 'بانتظار التنفيذ'),
    'needs_review': ('blocked', 'تحتاج مراجعة'), 'uncertain': ('blocked', 'نتيجة الإرسال غير مؤكدة'),
    'rejected': ('failed', 'رفض المزود الطلب'), 'failed': ('failed', 'تعذر التنفيذ'),
    'sent': ('completed', 'قبل المزود الإرسال — التسليم غير مؤكد'),
    'published': ('completed', 'أفاد المزود بالنشر'), 'complete': ('completed', 'اكتمل الإنتاج'),
    'completed': ('completed', 'انتهت المعالجة'), 'cancelled': ('completed', 'أُلغي الطلب'),
}

# Optional tables; select only status, reference and timestamp.
SOURCES = (
    ('media_jobs', 'إنتاج الصور والفيديو', 'id', 'status', 'updated_at'),
    ('advert_jobs', 'إنتاج الإعلان', 'id', 'status', 'updated_at'),
    ('social_publications', 'النشر الاجتماعي', 'id', 'status', 'updated_at'),
    ('freight_negotiations', 'تفاوض النقل', 'id', 'status', 'updated_at'),
    ('driver_broadcasts', 'عروض السائقين', 'id', 'status', 'updated_at'),
    ('afaaq_tracking_updates', 'تحديث تتبع الشحنة', 'id', 'state', 'updated_at'),
    ('official_reply_log', 'الرد بالبريد', 'inbox_id', 'status', 'created_at'),
    ('zernio_reply_events', 'الرد عبر واتساب المشترك', 'NULL', 'state', 'updated_at'),
    ('production_incidents', 'تنبيه التشغيل بالبريد', 'id', 'alert_status', 'alert_updated_at'),
)


def state_item(label, status, at, ref=None, now=None):
    kind, detail = STATES.get(status, ('unknown', 'حالة تحتاج مراجعة'))
    now = now or datetime.now(timezone.utc)
    stamp = datetime.fromisoformat(at) if isinstance(at, str) else at
    if stamp and stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    if kind == 'running' and (not stamp or (now - stamp).total_seconds() > 300):
        kind, detail = 'stale', 'تأخر تحديث التنفيذ — الحالة غير مؤكدة'
    return {'label': label + (' #' + str(ref) if ref is not None else '') + ' · ' + detail,
            'status': kind, 'at': at}


def current_items():
    from app.storage import db
    ensure_schema()
    items, unavailable = [], 0
    with db() as c:
        for row in c.execute("SELECT label,status,updated_at FROM agent_live_operations ORDER BY updated_at DESC").fetchall():
            item = state_item(row['label'], row['status'], row['updated_at'])
            if row['status'] == 'completed':
                item['label'] = row['label']
            items.append(item)
        for table, label, key, state, stamp in SOURCES:
            try:
                with c.transaction():
                    if not c.execute('SELECT to_regclass(%s) AS name', (table,)).fetchone()['name']:
                        continue
                    records = c.execute(f"""SELECT {key} AS ref,{state} AS status,{stamp} AS at
                        FROM {table} WHERE {stamp}>NOW()-INTERVAL '24 hours'
                        ORDER BY {stamp} DESC LIMIT 8""").fetchall()
                    items.extend(state_item(label, r['status'], r['at'], r['ref']) for r in records)
            except Exception:
                unavailable += 1
    items.sort(key=lambda x: str(x['at'] or ''), reverse=True)
    active = [x for x in items if x['status'] in ('running', 'waiting', 'blocked', 'stale')]
    terminal = [x for x in items if x['status'] not in ('running', 'waiting', 'blocked', 'stale')]
    return active[:12] + terminal[:1], unavailable
