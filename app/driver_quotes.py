"""Market prices from drivers (owner idea, Nov 2026): «بكم تحمل؟».

The manager gives the agent a REAL shipment (route, cargo/truck, loading date). After «نفذ» the agent asks the matching
registered drivers on WhatsApp, in the approved template afaaq_transport_driver_price_v1_ar, how much they would carry it
for. Drivers simply reply with a number. Every price is stored per route; the manager gets the lowest / median / highest
price and a market reference for that route (last 60 days) to price customers with confidence.

Nothing is promised to any driver: the message says it is a price request, and no load is assigned from here.
"""
import asyncio
import datetime as dt
import os
import re
import statistics
import threading

from app.storage import db, utcnow

TEMPLATE = 'afaaq_transport_driver_price_v1_ar'
MAX_DRIVERS = 40
REPLY_HOURS = 72
SUMMARY_AFTER_HOURS = 3
MIN_PRICE, MAX_PRICE = 150, 60000
DECLINE = re.compile(r'(ما\s*(اقدر|أقدر|أبغى|ابغى|ابي|أبي)|مش\s*فاضي|مو\s*فاضي|مشغول|ما\s*عندي|لا\s*شكرا|اعتذر|أعتذر|ما\s*يناسبني)')
REF = re.compile(r'TQ\s*-?\s*(\d+)', re.I)


def body(ref, route, cargo, date):
    return (f'طلب تسعير من آفاق طويق — {ref}\n'
            f'المسار: {route}\n'
            f'الحمولة: {cargo}\n'
            f'موعد التحميل: {date}\n'
            f'بكم تحملها؟ رد برقم السعر بالريال فقط، مثال: {ref} 2500\n'
            'هذا طلب سعر وليس إسنادًا للحمولة. شكرًا لتعاونك.')


def template_spec():
    return {'name': TEMPLATE, 'language': 'ar', 'category': 'UTILITY', 'components': [
        {'type': 'body', 'text': body('{{1}}', '{{2}}', '{{3}}', '{{4}}'),
         'example': {'body_text': [['TQ-12', 'ميناء جدة الإسلامي → الرياض (السلي)', 'حاوية 40 قدم على سطحة، 22 طن', 'الثلاثاء 10 نوفمبر']]}}]}


async def ensure_template():
    from app import zernio_whatsapp as wa
    async with wa.client() as c:
        await wa.validate_account(c)
        for item in await wa.templates(c):
            if item.get('name') == TEMPLATE and item.get('language') == 'ar':
                return str(item.get('status') or 'UNKNOWN')
        result = await c.post(wa.BASE + '/whatsapp/templates', json={'accountId': wa.account_id(), **template_spec()})
        return 'SUBMITTED' if result.is_success else 'CREATE_FAILED_' + str(result.status_code)


_READY = False


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS driver_price_requests(id BIGSERIAL PRIMARY KEY, origin TEXT NOT NULL,
            destination TEXT NOT NULL, cargo TEXT NOT NULL, loading_date TEXT NOT NULL, vehicle TEXT, status TEXT NOT NULL,
            created_by TEXT, created_at TIMESTAMPTZ NOT NULL, sent_at TIMESTAMPTZ, summary_sent_at TIMESTAMPTZ,
            notified INTEGER NOT NULL DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS driver_price_quotes(request_id BIGINT NOT NULL, phone TEXT NOT NULL,
            driver_id BIGINT, driver_name TEXT, vehicle_type TEXT, status TEXT NOT NULL, price NUMERIC, reply TEXT,
            error TEXT, sent_at TIMESTAMPTZ, replied_at TIMESTAMPTZ, PRIMARY KEY(request_id, phone))''')
        c.execute('CREATE INDEX IF NOT EXISTS driver_price_quotes_phone ON driver_price_quotes(right(phone,9), sent_at)')
    _READY = True


def clean(value, limit=80):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def fold(text):
    text = re.sub(r'[ً-ٰٟـ]', '', str(text or '')).lower()
    return text.translate(str.maketrans('أإآىئة', 'اااييه'))


def normalize(args):
    req = {'origin': clean(args.get('origin'), 60), 'destination': clean(args.get('destination'), 60),
           'cargo': clean(args.get('cargo'), 90), 'loading_date': clean(args.get('loading_date'), 40) or 'حسب الاتفاق',
           'vehicle': clean(args.get('vehicle_type'), 40)}
    if not req['cargo'] and req['vehicle']:
        req['cargo'] = req['vehicle']
    missing = [label for key, label in (('origin', 'مدينة التحميل'), ('destination', 'الوجهة'),
                                        ('cargo', 'وصف الحمولة (حاوية/طن/نوع الشاحنة)')) if not req[key]]
    return req, missing


def pick_drivers(req, limit=MAX_DRIVERS):
    """Consenting, available drivers; vehicle match first, then drivers based in/serving the origin."""
    with db() as c:
        rows = c.execute("""SELECT id, driver_name, whatsapp_phone, vehicle_type, current_city, preferred_routes FROM drivers
            WHERE COALESCE(offer_consent,1)=1 AND COALESCE(availability,'') NOT IN ('غير متاح','موقوف') ORDER BY id""").fetchall()
    origin, vehicle = fold(req['origin']), fold(req.get('vehicle') or req['cargo'])

    def score(d):
        s = 0
        vt = fold(d.get('vehicle_type'))
        if vt and any(w in vehicle for w in vt.split() if len(w) >= 3):
            s += 2
        place = fold(str(d.get('current_city') or '') + ' ' + str(d.get('preferred_routes') or ''))
        if origin and any(w in place for w in origin.split() if len(w) >= 3):
            s += 1
        return -s
    seen, out = set(), []
    for d in sorted(rows, key=score):
        phone = re.sub(r'\D', '', str(d['whatsapp_phone'] or ''))
        if len(phone) < 11 or phone in seen:
            continue
        seen.add(phone)
        out.append(dict(d, phone=phone))
        if len(out) >= limit:
            break
    return out


def prepare(args):
    """Validate; returns (req, drivers, error)."""
    init()
    req, missing = normalize(args)
    if missing:
        return req, [], 'ناقص: ' + '، '.join(missing)
    return req, pick_drivers(req, min(int(args.get('limit') or MAX_DRIVERS), MAX_DRIVERS)), None


def preview(req):
    return body('TQ-…', f"{req['origin']} → {req['destination']}", req['cargo'], req['loading_date'])


async def send_all(rid):
    from app import zernio_whatsapp as z
    with db() as c:
        r = c.execute('SELECT * FROM driver_price_requests WHERE id=%s', (rid,)).fetchone()
        targets = c.execute("SELECT phone FROM driver_price_quotes WHERE request_id=%s AND status='pending'", (rid,)).fetchall()
    text = body('TQ-' + str(rid), f"{r['origin']} → {r['destination']}", r['cargo'], r['loading_date'])
    sent = 0
    for row in targets:
        with db() as c:
            if not c.execute("UPDATE driver_price_quotes SET status='sending' WHERE request_id=%s AND phone=%s AND status='pending' RETURNING phone",
                             (rid, row['phone'])).fetchone():
                continue
        status, error = 'sent', None
        try:
            await z.send('+' + row['phone'], text)
        except Exception as exc:  # never retried automatically
            status, error = ('failed' if isinstance(exc, z.WhatsAppBlocked) else 'uncertain'), str(exc)[:200]
        with db() as c:
            c.execute('UPDATE driver_price_quotes SET status=%s,error=%s,sent_at=%s WHERE request_id=%s AND phone=%s',
                      (status, error, utcnow(), rid, row['phone']))
        sent += status == 'sent'
        await asyncio.sleep(float(os.getenv('LOAD_BROADCAST_DELAY', '1.2')))
    with db() as c:
        c.execute("UPDATE driver_price_requests SET status='sent',sent_at=%s WHERE id=%s", (utcnow(), rid))
    print('DRIVER_PRICE_REQUEST', rid, 'sent', sent, flush=True)


def create(action, actor=''):
    """Create the request with its recipients (status pending). Returns (id, count)."""
    init()
    req, missing = normalize(action)
    if missing:
        return None, 0
    targets = pick_drivers(req, min(int(action.get('limit') or MAX_DRIVERS), MAX_DRIVERS))
    if not targets:
        return None, 0
    with db() as c:
        rid = c.execute('''INSERT INTO driver_price_requests(origin,destination,cargo,loading_date,vehicle,status,created_by,created_at)
            VALUES(%s,%s,%s,%s,%s,'sending',%s,%s) RETURNING id''',
                        (req['origin'], req['destination'], req['cargo'], req['loading_date'], req['vehicle'], actor, utcnow())).fetchone()['id']
        for d in targets:
            c.execute('''INSERT INTO driver_price_quotes(request_id,phone,driver_id,driver_name,vehicle_type,status)
                VALUES(%s,%s,%s,%s,%s,'pending') ON CONFLICT DO NOTHING''',
                      (rid, d['phone'], d['id'], d.get('driver_name'), d.get('vehicle_type')))
    return rid, len(targets)


def start(action, actor=''):
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        return 'الإرسال الخارجي متوقف على الخادم؛ لم يُرسل شيء.'
    rid, count = create(action, actor)
    if not rid:
        return 'لا يوجد سائقون مناسبون أو البيانات ناقصة؛ لم يُرسل شيء.'
    threading.Thread(target=lambda: asyncio.run(send_all(rid)), daemon=True).start()
    return (f'✅ بدأ طلب الأسعار TQ-{rid} إلى {count} سائق ({action.get("origin")} → {action.get("destination")}). '
            f'السائق يرد برقم السعر فقط، وأرسل لك ملخص الأسعار بعد {SUMMARY_AFTER_HOURS} ساعات، أو اكتب «أسعار TQ-{rid}» أي وقت.')


# ---------- driver replies ----------

def price_in(text):
    t = str(text or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩٫٬', '0123456789.,'))
    t = REF.sub(' ', t)
    t = re.sub(r'(?<=\d),(?=\d{3}\b)', '', t)
    m = re.search(r'(\d+(?:\.\d+)?)\s*(الف|ألف|آلاف|الاف|k)\b', t, re.I)
    if m:
        value = float(m.group(1)) * 1000
    else:
        nums = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', t)]
        nums = [n for n in nums if MIN_PRICE <= n <= MAX_PRICE]
        if len(nums) != 1:
            return None
        value = nums[0]
    return value if MIN_PRICE <= value <= MAX_PRICE else None


def capture(phone, text):
    """A driver's reply to a price request. Returns (driver_reply, manager_text|None) or None if not a price reply."""
    init()
    d = re.sub(r'\D', '', str(phone or ''))[-9:]
    if len(d) < 9:
        return None
    ref = REF.search(str(text or ''))
    since = utcnow() - dt.timedelta(hours=REPLY_HOURS)
    with db() as c:
        if ref:
            q = c.execute('''SELECT q.*, r.origin, r.destination FROM driver_price_quotes q JOIN driver_price_requests r ON r.id=q.request_id
                WHERE q.request_id=%s AND right(q.phone,9)=%s AND q.status IN ('sent','quoted','declined')''', (int(ref.group(1)), d)).fetchone()
        else:
            q = c.execute('''SELECT q.*, r.origin, r.destination FROM driver_price_quotes q JOIN driver_price_requests r ON r.id=q.request_id
                WHERE right(q.phone,9)=%s AND q.status IN ('sent','quoted','declined') AND q.sent_at>=%s
                ORDER BY q.sent_at DESC LIMIT 1''', (d, since)).fetchone()
        if not q:
            return None
        price = price_in(text)
        tq = 'TQ-' + str(q['request_id'])
        if price is None:
            if DECLINE.search(str(text or '')):
                c.execute("UPDATE driver_price_quotes SET status='declined',reply=%s,replied_at=%s WHERE request_id=%s AND phone=%s",
                          (str(text)[:300], utcnow(), q['request_id'], q['phone']))
                return ('ولا يهمك، شكرًا لردك 🙏 نرسل لك الطلبات القادمة.', None)
            if not ref:
                return None  # an ordinary message; let the normal agent answer
            return (f'ما وضح لي السعر 🙏 اكتب السعر بالريال فقط، مثال: {tq} 2500', None)
        first = q['status'] != 'quoted'
        c.execute("UPDATE driver_price_quotes SET status='quoted',price=%s,reply=%s,replied_at=%s WHERE request_id=%s AND phone=%s",
                  (price, str(text)[:300], utcnow(), q['request_id'], q['phone']))
        stats = c.execute("SELECT COUNT(*) n, MIN(price) lo FROM driver_price_quotes WHERE request_id=%s AND status='quoted'",
                          (q['request_id'],)).fetchone()
        notify = first and c.execute('UPDATE driver_price_requests SET notified=notified+1 WHERE id=%s AND notified<5 RETURNING id',
                                     (q['request_id'],)).fetchone()
    reply = (f'تم تسجيل سعرك {price:,.0f} ريال لطلب {tq} ({q["origin"]} → {q["destination"]}) 👍 '
             'نرجع لك إذا اعتمدنا الحمولة. للاستفسار: 0507665873')
    manager = None
    if notify:
        manager = (f"💬 سعر سائق لطلب {tq} ({q['origin']} → {q['destination']}): {price:,.0f} ريال — "
                   f"{q.get('driver_name') or 'سائق'} (+{q['phone']}). وصلنا {stats['n']} سعر، الأقل {float(stats['lo']):,.0f}.")
    return reply, manager


# ---------- summaries ----------

def market(origin, destination, days=60):
    with db() as c:
        rows = c.execute('''SELECT q.price, r.origin, r.destination FROM driver_price_quotes q JOIN driver_price_requests r ON r.id=q.request_id
            WHERE q.status='quoted' AND r.created_at>=%s''', (utcnow() - dt.timedelta(days=days),)).fetchall()
    o, d = fold(origin), fold(destination)

    def same(a, b):
        a, b = fold(a), fold(b)
        return bool(a and b) and (a in b or b in a or bool({w for w in a.split() if len(w) >= 3} & {w for w in b.split() if len(w) >= 3}))
    return [float(r['price']) for r in rows if same(r['origin'], o) and same(r['destination'], d)]


def summary(rid=None):
    init()
    with db() as c:
        r = c.execute('SELECT * FROM driver_price_requests WHERE id=%s', (rid,)).fetchone() if rid else \
            c.execute('SELECT * FROM driver_price_requests ORDER BY id DESC LIMIT 1').fetchone()
        if not r:
            return 'لا يوجد طلب أسعار من السائقين بعد. اكتب مثلًا: «اجمع أسعار من السواقين: جدة → الرياض حاوية 40 التحميل بكرة».'
        rows = c.execute("SELECT * FROM driver_price_quotes WHERE request_id=%s ORDER BY price NULLS LAST", (r['id'],)).fetchall()
    tq = 'TQ-' + str(r['id'])
    quoted = [x for x in rows if x['status'] == 'quoted']
    sent = sum(x['status'] in ('sent', 'quoted', 'declined') for x in rows)
    lines = [f"📊 أسعار السائقين — {tq}: {r['origin']} → {r['destination']} ({r['cargo']})",
             f"أُرسل لـ {sent} سائق، رد بسعر {len(quoted)}، اعتذر {sum(x['status'] == 'declined' for x in rows)}"
             + (f"، تعذر {sum(x['status'] in ('failed', 'uncertain') for x in rows)}" if any(x['status'] in ('failed', 'uncertain') for x in rows) else '')]
    if quoted:
        prices = [float(x['price']) for x in quoted]
        lines.append(f'الأقل {min(prices):,.0f} | الوسيط {statistics.median(prices):,.0f} | الأعلى {max(prices):,.0f} ريال')
        for x in quoted[:8]:
            lines.append(f"• {float(x['price']):,.0f} — {x.get('driver_name') or 'سائق'} (+{x['phone']})"
                         + (f" — {x['vehicle_type']}" if x.get('vehicle_type') else ''))
    else:
        lines.append('لم يصل أي سعر حتى الآن.')
    hist = market(r['origin'], r['destination'])
    if len(hist) >= 3:
        lines.append(f'مرجع السوق لنفس المسار (آخر 60 يومًا، {len(hist)} سعر): الوسيط {statistics.median(hist):,.0f} '
                     f'(من {min(hist):,.0f} إلى {max(hist):,.0f})')
    if quoted:
        lines.append('سعر العميل = سعر السائق المختار + عمولتك. لعرض الحمولة على كل السائقين بسعر محدد استخدم «أرسل الحمولة للسائقين».')
    return '\n'.join(lines)


def due_summaries():
    """Requests sent ≥ SUMMARY_AFTER_HOURS ago whose summary was not sent yet (claimed once)."""
    init()
    with db() as c:
        rows = c.execute('''UPDATE driver_price_requests SET summary_sent_at=%s WHERE status='sent' AND summary_sent_at IS NULL
            AND sent_at <= %s RETURNING id''', (utcnow(), utcnow() - dt.timedelta(hours=SUMMARY_AFTER_HOURS))).fetchall()
    return [summary(r['id']) for r in rows]


def register_worker(app):
    async def loop():
        from starlette.concurrency import run_in_threadpool
        from app.owner_briefing import deliver
        await asyncio.sleep(290)
        try:
            print('DRIVER_PRICE_TEMPLATE', await ensure_template(), flush=True)
        except Exception as exc:
            print('DRIVER_PRICE_TEMPLATE', 'ERROR_' + type(exc).__name__, flush=True)
        while True:
            try:
                for text in await run_in_threadpool(due_summaries):
                    await deliver(text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('DRIVER_PRICE_WORKER', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(600)

    @app.on_event('startup')
    async def _start():
        if os.getenv('DISCOVERY_AUTO_ENABLED', '1') != '0':
            app.state.driver_price_task = asyncio.create_task(loop())
