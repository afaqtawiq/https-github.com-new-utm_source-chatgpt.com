"""Transport rate card (owner decision, 25 Nov 2026: «نبدأ بـ2» — price the missing lanes from the drivers).

1. rate_card_survey: Khaled asks the registered drivers, in the approved price-request template, for their price on each
   missing lane — ONE «نفذ» for the whole survey; every driver gets at most one lane (so a bare number reply is matched
   to the right lane), drivers based in/serving the origin first.
2. rate_card: approved customer prices per lane + the drivers' market price (lowest / median / count, last 60 days)
   and a suggested customer price for the lanes we do not sell yet.
3. approve_route_price: the manager approves a customer price for a lane → it joins the approved price table used by
   quotes, the /price calculator, follow-ups and the customer agent. Nothing is approved automatically.
"""
import asyncio
import re
import statistics
import threading

from app.storage import db, utcnow

# Lanes the approved price list does not cover yet (owner priority list, Nov 2026).
LANES = [
    {'origin': 'ميناء الملك عبدالعزيز بالدمام', 'destination': 'الرياض', 'cargo': 'حاوية 40 قدم على سطحة حتى 27 طن'},
    {'origin': 'ميناء الملك عبدالعزيز بالدمام', 'destination': 'الجبيل', 'cargo': 'حاوية 40 قدم على سطحة حتى 27 طن'},
    {'origin': 'ميناء الملك عبدالعزيز بالدمام', 'destination': 'القصيم', 'cargo': 'حاوية 40 قدم على سطحة حتى 27 طن'},
    {'origin': 'ميناء جدة الإسلامي', 'destination': 'مكة المكرمة', 'cargo': 'حاوية 40 قدم على سطحة حتى 27 طن'},
    {'origin': 'ميناء جدة الإسلامي', 'destination': 'المدينة المنورة', 'cargo': 'حاوية 40 قدم على سطحة حتى 27 طن'},
    {'origin': 'ميناء جدة الإسلامي', 'destination': 'الدمام', 'cargo': 'حاوية 40 قدم على سطحة حتى 27 طن'},
    {'origin': 'ميناء جدة الإسلامي', 'destination': 'أبها / خميس مشيط', 'cargo': 'حاوية 40 قدم على سطحة حتى 27 طن'},
    {'origin': 'الرياض', 'destination': 'الدمام', 'cargo': 'بضائع عامة على تريلا ستارة 13.5 متر حتى 25 طن', 'vehicle_type': 'ستارة'},
]
PER_LANE = 15
MARGIN = 0.15


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS approved_routes(label TEXT PRIMARY KEY, price INTEGER NOT NULL,
            approved_by TEXT, approved_at TIMESTAMPTZ NOT NULL)''')


def label(origin, destination):
    return 'من ' + re.sub(r'\s+', ' ', str(origin)).strip() + ' إلى ' + re.sub(r'\s+', ' ', str(destination)).strip()


def approved_extra():
    """Lanes approved through approve_route_price: {label: price}."""
    try:
        init()
        with db() as c:
            return {r['label']: int(r['price']) for r in c.execute('SELECT label, price FROM approved_routes ORDER BY label').fetchall()}
    except Exception:
        return {}


def approved_text():
    """Extra approved lanes for the agents' knowledge (the base price list text is pinned and never edited)."""
    extra = approved_extra()
    if not extra:
        return ''
    return ('\n\nأسعار نقل إضافية معتمدة من الإدارة (مكملة للبند 16، الحمولة 27 طن كحد أقصى، شاملة نفس شروط البند 16):\n'
            + '\n'.join(f'- {k}: {v:,} ريال' for k, v in extra.items()) + '\n')


GENERIC = {'ميناء', 'الملك', 'الاسلامي', 'الإسلامي', 'منفذ', 'مدينه', 'المدينه', 'محافظه', 'من', 'الى', 'إلى'}


def _words(text):
    from app.driver_quotes import fold
    out = set()
    for w in re.findall(r'[\w]+', fold(text)):
        for v in (w, w[1:] if w.startswith('ب') and len(w) > 4 else w):  # «بالدمام» = «الدمام»
            if len(v) >= 3 and fold(v) not in {fold(g) for g in GENERIC}:
                out.add(v)
    return out


def _side_match(a, b):
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and (wa <= wb or wb <= wa)


def split_label(lane_label):
    m = re.match(r'^من\s+(.+?)\s+إلى\s+(.+)$', str(lane_label).strip())
    return (m.group(1), m.group(2)) if m else (lane_label, '')


def _same_lane(lane_label, origin, destination):
    o, d = split_label(lane_label)
    return _side_match(o, origin) and _side_match(d, destination)


def market(origin, destination, days=60):
    """Drivers' prices for exactly this lane (both ends must match; «ميناء الملك» alone never matches)."""
    import datetime as dt
    from app import driver_quotes
    driver_quotes.init()
    with db() as c:
        rows = c.execute('''SELECT q.price, r.origin, r.destination FROM driver_price_quotes q JOIN driver_price_requests r ON r.id=q.request_id
            WHERE q.status='quoted' AND r.created_at>=%s''', (utcnow() - dt.timedelta(days=days),)).fetchall()
    return [float(r['price']) for r in rows if _side_match(r['origin'], origin) and _side_match(r['destination'], destination)]


# ---------- 1. survey ----------

def plan(lanes=None, per_lane=PER_LANE):
    """[(lane, drivers)] — distinct drivers across lanes, origin-matched first."""
    from app import driver_quotes
    driver_quotes.init()
    lanes = lanes or LANES
    used, out = set(), []
    for lane in lanes:
        req, missing = driver_quotes.normalize(lane)
        if missing:
            continue
        picked = [d for d in driver_quotes.pick_drivers(req, 400) if d['phone'] not in used][:per_lane]
        used.update(d['phone'] for d in picked)
        out.append((dict(lane, vehicle=req['vehicle']), picked))
    return out


def survey_preview(lanes=None, per_lane=PER_LANE):
    rows = plan(lanes, per_lane)
    total = sum(len(d) for _, d in rows)
    if not total:
        return None, 'لا يوجد سائقون مسجلون متاحون لطلبات الأسعار الآن.'
    lines = [f'📋 مسح أسعار المسارات الناقصة — {len(rows)} مسار، {total} سائق (كل سائق يُسأل عن مسار واحد فقط):']
    for i, (lane, drivers) in enumerate(rows, 1):
        lines.append(f"{i}. {lane['origin']} → {lane['destination']} — {lane['cargo']} — {len(drivers)} سائق")
    lines.append('الرسالة: قالب طلب السعر المعتمد «بكم تحملها؟ رد برقم السعر» — طلب سعر وليس إسنادًا.')
    return rows, '\n'.join(lines)


def start_survey(action, actor=''):
    """After «نفذ»: one driver_price_request per lane (TQ-n), sent one after another in the background."""
    import os
    from app import driver_quotes
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        return 'الإرسال الخارجي متوقف على الخادم؛ لم يُرسل شيء.'
    rows = plan(action.get('lanes') or LANES, int(action.get('per_lane') or PER_LANE))
    created = []
    for lane, drivers in rows:
        if not drivers:
            continue
        with db() as c:
            rid = c.execute('''INSERT INTO driver_price_requests(origin,destination,cargo,loading_date,vehicle,status,created_by,created_at)
                VALUES(%s,%s,%s,'خلال الأسبوع القادم',%s,'sending',%s,%s) RETURNING id''',
                (lane['origin'], lane['destination'], lane['cargo'], lane.get('vehicle') or '', actor or 'مسح الأسعار', utcnow())).fetchone()['id']
            for d in drivers:
                c.execute('''INSERT INTO driver_price_quotes(request_id,phone,driver_id,driver_name,vehicle_type,status)
                    VALUES(%s,%s,%s,%s,%s,'pending') ON CONFLICT DO NOTHING''',
                          (rid, d['phone'], d['id'], d.get('driver_name'), d.get('vehicle_type')))
        created.append((rid, lane, len(drivers)))
    if not created:
        return 'لا يوجد سائقون مناسبون؛ لم يُرسل شيء.'

    def go():
        for rid, _, _ in created:
            try:
                asyncio.run(driver_quotes.send_all(rid))
            except Exception as exc:
                print('RATE_CARD_SURVEY', rid, type(exc).__name__, str(exc)[:120], flush=True)
    threading.Thread(target=go, daemon=True).start()
    lines = [f'✅ بدأ مسح الأسعار: {len(created)} مسار، {sum(n for _, _, n in created)} سائق.']
    lines += [f'TQ-{rid}: {lane["origin"]} → {lane["destination"]} ({n} سائق)' for rid, lane, n in created]
    lines.append('يصلك ملخص كل مسار بعد 3 ساعات تلقائيًا. «جدول الأسعار» يعرض الكل مع السعر المقترح للعميل.')
    return '\n'.join(lines)


# ---------- 2. the card ----------

def suggested(median):
    return int(round(median * (1 + MARGIN) / 50.0) * 50)


def card(lanes=None):
    from app import driver_quotes
    from app.prospect_replies import price_table
    _, routes = price_table()
    lines = ['🚚 جدول أسعار النقل (للعميل، شاحنة حتى 27 طن):', '', '✅ مسارات معتمدة:']
    for k, v in routes.items():
        lines.append(f'• {k}: {v:,} ريال')
    lines.append('• دبي ← الرياض (+ تنزيل ثاني بالدمام)، ستارة 13.5م حتى 13 طن: 4,200 درهم (أدنى تفاوض 4,000)')
    lines += ['', '🔎 مسارات قيد التسعير (أسعار السائقين آخر 60 يومًا):']
    pending = 0
    for lane in lanes or LANES:
        name = label(lane['origin'], lane['destination'])
        if any(_same_lane(k, lane['origin'], lane['destination']) for k in routes):
            continue
        pending += 1
        prices = market(lane['origin'], lane['destination'])
        if prices:
            med = statistics.median(prices)
            lines.append(f'• {name}: {len(prices)} سعر — الأقل {min(prices):,.0f} | الوسيط {med:,.0f} ريال '
                         f'→ مقترح للعميل {suggested(med):,} ريال (+{int(MARGIN * 100)}%)')
        else:
            lines.append(f'• {name}: ما وصلت أسعار بعد')
    if not pending:
        lines.append('كل المسارات في القائمة معتمدة ✅')
    lines += ['', 'للاعتماد: «اعتمد سعر مسار <من … إلى …> <السعر>» — يدخل فورًا في عروض الأسعار والحاسبة وردود العملاء.']
    return '\n'.join(lines)


# ---------- 3. approval ----------

def approve(origin, destination, price, actor=''):
    try:
        price = int(round(float(str(price).replace(',', ''))))
    except (TypeError, ValueError):
        return 'السعر غير واضح؛ اكتبه بالأرقام بالريال.'
    if not 150 <= price <= 60000:
        return 'السعر خارج النطاق المعقول (150 – 60,000 ريال)؛ لم يُعتمد.'
    origin, destination = re.sub(r'\s+', ' ', str(origin or '')).strip(), re.sub(r'\s+', ' ', str(destination or '')).strip()
    if not origin or not destination:
        return 'حدد المسار: من وين إلى وين.'
    from app.prospect_replies import price_table
    _, routes = price_table(include_extra=False)
    if any(_same_lane(k, origin, destination) for k in routes):
        return 'هذا المسار له سعر معتمد في القائمة الأساسية؛ تعديله يكون من إدارة الأسعار، ولم يتغير شيء.'
    name = label(origin, destination)
    init()
    with db() as c:
        before = c.execute('SELECT price FROM approved_routes WHERE label=%s', (name,)).fetchone()
        c.execute('''INSERT INTO approved_routes(label,price,approved_by,approved_at) VALUES(%s,%s,%s,%s)
            ON CONFLICT(label) DO UPDATE SET price=EXCLUDED.price, approved_by=EXCLUDED.approved_by, approved_at=EXCLUDED.approved_at''',
                  (name, price, actor, utcnow()))
    was = f' (كان {before["price"]:,})' if before else ''
    return f'✅ اعتمدت {name}: {price:,} ريال للعميل{was}. يظهر الآن في عروض الأسعار والحاسبة وردود الوكيل.'
