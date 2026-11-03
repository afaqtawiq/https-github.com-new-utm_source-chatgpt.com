"""Transport desk — one flow from a Naqliat load to a linked driver (owner-requested, Nov 2026).

1. Intake: the manager sends a Naqliat screenshot (or the Android connector captures an opened load).
   The load is saved (NQ-n) and the manager gets a ready «نفذ CODE» to start the owner conversation.
   If the owner's number is not on the screenshot, the next number (typed, or on another screenshot) within
   an hour is attached; a number sent first is kept for the next load the same way.
2. Negotiation (owner_negotiation): seeded with what the listing already shows, so the owner only confirms.
3. Drivers (load_broadcast): after «اعتمد الحمولة N عمولة X».
4. Link: a driver answers «موافق AFT-n» -> recorded, manager notified -> «اسند AFT-n للسائق <رقم>» + «نفذ CODE»
   -> the driver receives the owner's contact and loading details, the owner receives the driver's details, and
   the other drivers who accepted are told the load was taken.
Nothing leaves the company without the manager's confirmation code.
"""
import asyncio
import json
import os
import re
import secrets
import threading

from app.storage import db, utcnow

CONFIRM_PREFIX = '__agent_action__:'
SUPPORT = '0507665873'


_READY = False


def init():
    global _READY
    if _READY:
        return
    from app import load_broadcast, owner_negotiation
    owner_negotiation.init()
    load_broadcast.init()
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS transport_intake(
            id BIGSERIAL PRIMARY KEY, sender TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
            used BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('ALTER TABLE naqliat_loads ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ')
    _READY = True


# ---------- helpers ----------

def digits(phone):
    d = re.sub(r'\D', '', str(phone or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')))
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('05') and len(d) == 10:
        d = '966' + d[1:]
    elif d.startswith('5') and len(d) == 9:
        d = '966' + d
    return d


PHONE_RE = re.compile(r'(?:\+?966|00966|0)?\s*5[\d\s-]{8,11}')


def phones_in(text):
    text = str(text or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    out = []
    for raw in PHONE_RE.findall(text):
        d = digits(raw)
        if re.fullmatch(r'9665\d{8}', d) and d not in out:
            out.append(d)
    return out


def pending(c, sender, conversation_id, action, minutes=60):
    token = secrets.token_hex(3).upper()
    c.execute('''INSERT INTO whatsapp_voice_pending(token,sender,conversation_id,command,expires_at)
        VALUES(%s,%s,%s,%s,NOW()+make_interval(mins => %s))''',
              (token, sender, conversation_id, CONFIRM_PREFIX + json.dumps(action, ensure_ascii=False), int(minutes)))
    return token


def manager_chat(c):
    """The manager's last command chat with the agent (sender, conversation_id), or None."""
    owner = re.sub(r'\D', '', os.getenv('WHATSAPP_COMMAND_OWNER', ''))
    if not owner:
        return None
    row = c.execute('''SELECT sender,conversation_id FROM whatsapp_admin_audit WHERE right(regexp_replace(sender,'\\D','','g'),9)=%s
        ORDER BY created_at DESC NULLS LAST LIMIT 1''', (owner[-9:],)).fetchone()
    return (row['sender'], row['conversation_id']) if row else None


def run_async(coro_factory, timeout=60):
    """Run an async job from sync code (worker thread) and wait for its result."""
    out = {}

    def run():
        try:
            out['value'] = asyncio.run(coro_factory())
        except Exception as exc:
            out['error'] = exc
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    if 'error' in out:
        raise out['error']
    return out.get('value')


# ---------- 1. intake ----------

def load_row(c, load_id):
    return c.execute('SELECT * FROM naqliat_loads WHERE id=%s', (int(load_id),)).fetchone()


def listing(load):
    """What the Naqliat listing already shows — the owner is only asked to confirm it."""
    text = str(load.get('description') or '') + '\n' + str(load.get('raw_text') or '')
    seed = {}
    if load.get('weight_tons'):
        seed['weight'] = f"{load['weight_tons']:g}"
    if load.get('vehicle_type'):
        seed['vehicle'] = str(load['vehicle_type'])[:80]
    if load.get('distance_km'):
        seed['distance_km'] = str(load['distance_km'])
    for key, label in (('goods', 'البضاعة'), ('price', 'السعر المعروض'), ('payment', 'الدفع'), ('loading_date', 'موعد التحميل')):
        m = re.search(label + r'\s*[:：]\s*([^\n]{1,120})', text)
        if m:
            seed[key] = m.group(1).strip()
    try:
        raw = json.loads(load.get('raw_text') or '{}')
        if isinstance(raw, dict):
            for key, src in (('goods', 'goods'), ('payment', 'payment'), ('loading_date', 'loading_date'), ('price', 'price_sar')):
                if raw.get(src) not in (None, '', 'null') and key not in seed:
                    seed[key] = str(raw[src])[:120]
    except ValueError:
        pass
    return seed


def describe(load):
    seed = listing(load)
    lines = [f"🚛 حمولة NQ-{load['id']}: {load['origin']} → {load['destination']}"]
    for key, label in (('weight', 'الوزن (طن)'), ('vehicle', 'الشاحنة'), ('goods', 'البضاعة'), ('price', 'السعر المعروض'),
                       ('payment', 'الدفع'), ('loading_date', 'موعد التحميل')):
        if seed.get(key):
            lines.append(f'• {label}: {seed[key]}')
    if load.get('owner_phone'):
        lines.append('• صاحب الحمولة: +' + digits(load['owner_phone']))
    return '\n'.join(lines)


def offer_negotiation(c, sender, conversation_id, load_id, minutes=60):
    """Reply text for a saved load: ready code to contact the owner, or ask for the number."""
    load = load_row(c, load_id)
    if not load:
        return 'لم أجد الحمولة.'
    phone = digits(load.get('owner_phone'))
    head = describe(load)
    if not re.fullmatch(r'9\d{10,13}', phone or ''):
        c.execute("INSERT INTO transport_intake(sender,kind,value,created_at) VALUES(%s,'load',%s,%s)",
                  (sender, str(load['id']), utcnow()))
        return head + '\n\nرقم صاحب الحمولة غير ظاهر. أرسل الرقم (أو لقطة فيها الرقم) وأجهز لك بدء التفاوض.'
    token = pending(c, sender, conversation_id, {'tool': 'negotiate_owner', 'phone': phone, 'origin': load['origin'][:60],
                                                 'destination': load['destination'][:60], 'load_id': load['id']}, minutes)
    return (head + f'\n\nللتواصل مع صاحب الحمولة والتفاوض معه بشكل طبيعي اكتب: نفذ {token}\n'
            '(لن أقبل أو أرفض أي سعر؛ أرسل لك الملخص للاعتماد وتحديد العمولة.)')


def attach_phone(c, sender, conversation_id, phone):
    """A number from the manager: attach it to the waiting load, or keep it for the next load."""
    row = c.execute("""SELECT id,value FROM transport_intake WHERE sender=%s AND kind='load' AND NOT used
        AND created_at>NOW()-INTERVAL '60 minutes' ORDER BY id DESC LIMIT 1""", (sender,)).fetchone()
    if row:
        c.execute('UPDATE transport_intake SET used=TRUE WHERE id=%s', (row['id'],))
        c.execute('UPDATE naqliat_loads SET owner_phone=%s WHERE id=%s', ('+' + phone, int(row['value'])))
        c.execute("""UPDATE freight_negotiations SET owner_phone=%s,updated_at=%s WHERE naqliat_load_id=%s
            AND COALESCE(owner_phone,'')=''""", ('+' + phone, utcnow(), int(row['value'])))
        return offer_negotiation(c, sender, conversation_id, int(row['value']))
    c.execute("INSERT INTO transport_intake(sender,kind,value,created_at) VALUES(%s,'phone',%s,%s)", (sender, phone, utcnow()))
    return None


def waiting_phone(c, sender):
    row = c.execute("""SELECT id,value FROM transport_intake WHERE sender=%s AND kind='phone' AND NOT used
        AND created_at>NOW()-INTERVAL '30 minutes' ORDER BY id DESC LIMIT 1""", (sender,)).fetchone()
    if row:
        c.execute('UPDATE transport_intake SET used=TRUE WHERE id=%s', (row['id'],))
        return row['value']
    return None


def waiting_load(c, sender):
    return c.execute("""SELECT 1 FROM transport_intake WHERE sender=%s AND kind='load' AND NOT used
        AND created_at>NOW()-INTERVAL '60 minutes' LIMIT 1""", (sender,)).fetchone() is not None


def phone_message(text):
    """A short manager message that is just the owner's number (optionally with a label)."""
    value = str(text or '').strip()
    found = phones_in(value)
    if len(found) != 1 or len(value) > 60:
        return None
    rest = PHONE_RE.sub('', value.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')))
    rest = re.sub(r'(رقم|صاحب|الحمولة|الشحنة|جوال|واتساب|هذا|هو|التواصل|مع|[\s:+\-،.])', '', rest)
    return found[0] if not rest else None


def connector_notice(load_id):
    """A load captured by the Android connector: send the manager the summary + ready code."""
    init()
    with db() as c:
        claimed = c.execute('UPDATE naqliat_loads SET notified_at=%s WHERE id=%s AND notified_at IS NULL RETURNING id',
                            (utcnow(), int(load_id))).fetchone()
        if not claimed:
            return None  # the manager was already told about this load
        chat = manager_chat(c)
        load = load_row(c, load_id)
        if not load:
            return None
        if chat:
            return offer_negotiation(c, chat[0], chat[1], load_id, minutes=120)
        return describe(load) + f'\n\nللتفاوض مع صاحب الحمولة اكتب للوكيل: فاوض NQ-{load_id}'


async def notify_capture(load_id):
    from app.owner_briefing import deliver
    from starlette.concurrency import run_in_threadpool
    try:
        text = await run_in_threadpool(connector_notice, load_id)
        if text:
            await deliver('📲 التقطت حمولة من نقليات\n' + text)
    except Exception as exc:
        print('TRANSPORT_CAPTURE_NOTICE', type(exc).__name__, str(exc)[:160], flush=True)


# ---------- 4. driver acceptance and linking ----------

ACCEPT = re.compile(r'(موافق|اوافق|أوافق|تمام|نعم|ابغاها|أبغاها|ابيها|أبيها|ok)', re.I)
REF = re.compile(r'AFT\s*-?\s*(\d+)', re.I)


def driver_accept(phone, text):
    """«موافق AFT-n» from a driver who received that load. Returns (driver_reply, manager_text) or None."""
    m = REF.search(str(text or ''))
    if not m or not ACCEPT.search(str(text)):
        return None
    init()
    bid = int(m.group(1))
    d = digits(phone)
    with db() as c:
        b = c.execute('SELECT * FROM load_broadcasts WHERE id=%s FOR UPDATE', (bid,)).fetchone()
        rec = c.execute('''SELECT r.*,dr.driver_name,dr.vehicle_type FROM load_broadcast_recipients r LEFT JOIN drivers dr ON dr.id=r.driver_id
            WHERE r.broadcast_id=%s AND right(r.phone,9)=%s''', (bid, d[-9:])).fetchone() if b else None
        if not b or not rec:
            return None
        ref = 'AFT-' + str(bid)
        if b.get('assigned_phone'):
            if b['assigned_phone'][-9:] == d[-9:]:
                return ('الحمولة ' + ref + ' مسندة لك ✅ وتفاصيل صاحب الحمولة أرسلناها لك. للاستفسار: ' + SUPPORT, None)
            return ('شكرًا لتجاوبك 🙏 الحمولة ' + ref + ' أُسندت لسائق آخر، ونرسل لك الحمولات القادمة أولًا بأول.', None)
        first = rec['status'] != 'accepted'
        c.execute("UPDATE load_broadcast_recipients SET status='accepted',replied_at=%s WHERE broadcast_id=%s AND phone=%s",
                  (utcnow(), bid, rec['phone']))
        count = c.execute("SELECT COUNT(*) n FROM load_broadcast_recipients WHERE broadcast_id=%s AND status='accepted'", (bid,)).fetchone()['n']
    reply = ('تم تسجيل موافقتك على الحمولة ' + ref + ' 👍 ننسق الآن مع صاحب الحمولة ونرجع لك بالتأكيد خلال وقت قصير. '
             'للاستفسار: ' + SUPPORT)
    manager = None
    if first:
        name = rec.get('driver_name') or 'سائق'
        manager = (f"🚚 وافق السائق {name} (+{rec['phone']}){' — ' + rec['vehicle_type'] if rec.get('vehicle_type') else ''} "
                   f"على الحمولة {ref} ({b['origin']} → {b['destination']}، سعر السائق {b['driver_price']} ريال).\n"
                   f"عدد الموافقين حتى الآن: {count}\n"
                   f"لإسنادها له وربطه بصاحب الحمولة اكتب: اسند {ref} للسائق {rec['phone']}")
    return reply, manager


def accepted_list(c, bid):
    return c.execute('''SELECT r.phone,dr.driver_name,dr.vehicle_type FROM load_broadcast_recipients r LEFT JOIN drivers dr ON dr.id=r.driver_id
        WHERE r.broadcast_id=%s AND r.status='accepted' ORDER BY r.replied_at''', (bid,)).fetchall()


def link_messages(b, driver, negotiation):
    fields = json.loads(negotiation['fields'] or '{}') if negotiation else {}
    ref = 'AFT-' + str(b['id'])
    lines = [f'✅ تم إسناد الحمولة {ref} لك من آفاق طويق', f"المسار: {b['origin']} → {b['destination']}"]
    for key, label in (('loading_point', 'موقع التحميل'), ('unloading', 'موقع التنزيل'), ('loading_date', 'موعد التحميل'),
                       ('goods', 'البضاعة'), ('weight', 'الوزن (طن)')):
        if fields.get(key):
            lines.append(f'{label}: {fields[key]}')
    lines.append(f"سعرك: {b['driver_price']} ريال — الدفع: {b['payment']}")
    if negotiation:
        lines.append(f"صاحب الحمولة: +{negotiation['phone']} (تواصل معه لتنسيق موعد ومكان التحميل)")
    lines.append('فريق آفاق طويق: ' + SUPPORT)
    to_driver = '\n'.join(lines)
    to_owner = None
    if negotiation:
        to_owner = '\n'.join(x for x in [
            f"السلام عليكم، تم تجهيز سائق لحمولتكم من {b['origin']} إلى {b['destination']} ✅",
            f"السائق: {driver.get('driver_name') or 'سائق آفاق طويق'}",
            f"الجوال: +{driver['phone']}",
            ('الشاحنة: ' + driver['vehicle_type']) if driver.get('vehicle_type') else '',
            'بيتواصل معكم لتنسيق التحميل. لأي استفسار: ' + SUPPORT] if x)
    return to_driver, to_owner


def prepare_assign(c, sender, conversation_id, ref, driver_phone=''):
    """Manager: «اسند AFT-n للسائق <رقم>» -> preview both messages + confirmation code."""
    init()
    m = re.search(r'(\d+)', str(ref or ''))
    b = c.execute('SELECT * FROM load_broadcasts WHERE id=%s', (int(m.group(1)),)).fetchone() if m else None
    if not b:
        return 'لا توجد حمولة مرسلة بهذا الرقم.'
    if b.get('assigned_phone'):
        return f"الحمولة AFT-{b['id']} مسندة مسبقًا للسائق +{b['assigned_phone']}."
    accepted = accepted_list(c, b['id'])
    if not accepted:
        return f"لم يوافق أي سائق على AFT-{b['id']} بعد."
    want = digits(driver_phone)
    driver = next((a for a in accepted if want and a['phone'][-9:] == want[-9:]), None) if want else accepted[0]
    if not driver:
        return 'هذا الرقم ليس من السائقين الموافقين. الموافقون: ' + '، '.join('+' + a['phone'] for a in accepted)
    negotiation = c.execute('SELECT * FROM owner_negotiations WHERE id=%s', (b['negotiation_id'],)).fetchone() if b.get('negotiation_id') else None
    to_driver, to_owner = link_messages(b, driver, negotiation)
    token = pending(c, sender, conversation_id, {'tool': 'assign_driver', 'broadcast_id': b['id'], 'phone': driver['phone']}, 30)
    text = f"جاهز لإسناد AFT-{b['id']} للسائق {driver.get('driver_name') or ''} (+{driver['phone']}).\n\n— رسالة السائق:\n{to_driver}"
    text += f"\n\n— رسالة صاحب الحمولة:\n{to_owner}" if to_owner else '\n\n(لا يوجد ملف صاحب حمولة مرتبط؛ أرسل له بيانات السائق بنفسك.)'
    others = len(accepted) - 1
    if others:
        text += f'\n\nوسأبلغ {others} سائق آخر وافق أن الحمولة أُسندت.'
    return text + f'\n\nللتنفيذ اكتب: نفذ {token}'


def assign(action):
    """After «نفذ CODE»: send both link messages, mark the load assigned, release the other drivers."""
    from app import zernio_whatsapp as z
    init()
    bid = int(action['broadcast_id'])
    with db() as c:
        b = c.execute('SELECT * FROM load_broadcasts WHERE id=%s', (bid,)).fetchone()
        if not b or b.get('assigned_phone'):
            return 'الحمولة مسندة مسبقًا أو غير موجودة؛ لم يُرسل شيء.'
        accepted = accepted_list(c, bid)
        driver = next((a for a in accepted if a['phone'][-9:] == digits(action['phone'])[-9:]), None)
        if not driver:
            return 'السائق لم يعد ضمن الموافقين؛ لم يُرسل شيء.'
        negotiation = c.execute('SELECT * FROM owner_negotiations WHERE id=%s', (b['negotiation_id'],)).fetchone() if b.get('negotiation_id') else None
        c.execute('UPDATE load_broadcasts SET assigned_phone=%s WHERE id=%s AND assigned_phone IS NULL', (driver['phone'], bid))
        c.execute("UPDATE load_broadcast_recipients SET status='assigned' WHERE broadcast_id=%s AND phone=%s", (bid, driver['phone']))
        if negotiation:
            c.execute("UPDATE owner_negotiations SET status='assigned',updated_at=%s WHERE id=%s", (utcnow(), negotiation['id']))
    to_driver, to_owner = link_messages(b, driver, negotiation)
    others = [a['phone'] for a in accepted if a['phone'] != driver['phone']]

    async def send_all():
        results = {}
        for key, phone, text in (('driver', driver['phone'], to_driver), ('owner', negotiation['phone'] if negotiation else None, to_owner)):
            if not phone or not text:
                continue
            try:
                await z.send(phone, text)
                results[key] = 'ok'
            except Exception as exc:
                results[key] = str(exc)[:160]
        released = 0
        for phone in others:
            try:
                await z.send(phone, f'شكرًا لتجاوبك 🙏 الحمولة AFT-{bid} أُسندت لسائق آخر، ونرسل لك الحمولات القادمة أولًا بأول.')
                released += 1
            except Exception:
                pass
        results['released'] = released
        return results
    try:
        results = run_async(send_all, 90) or {}
    except Exception as exc:
        results = {'driver': str(exc)[:160]}
    print('TRANSPORT_ASSIGN', bid, json.dumps(results, ensure_ascii=False)[:300], flush=True)
    lines = [f"تم إسناد AFT-{bid} للسائق +{driver['phone']}."]
    lines.append('✅ وصلت تفاصيل صاحب الحمولة للسائق.' if results.get('driver') == 'ok'
                 else f"❌ لم تصل رسالة السائق: {results.get('driver')} — أرسل له يدويًا: wa.me/{driver['phone']}")
    if negotiation:
        lines.append('✅ وصلت بيانات السائق لصاحب الحمولة.' if results.get('owner') == 'ok'
                     else f"❌ لم تصل رسالة صاحب الحمولة: {results.get('owner')} — أرسل له يدويًا: wa.me/{negotiation['phone']}")
    if others:
        lines.append(f"أبلغت {results.get('released', 0)} من {len(others)} سائق آخر أن الحمولة أُسندت.")
    return '\n'.join(lines)


# ---------- templates ----------

def templates_text():
    from app import zernio_whatsapp as z

    async def fetch():
        async with z.client() as c:
            return await z.templates(c)
    try:
        items = run_async(fetch, 40) or []
    except Exception as exc:
        return 'تعذر قراءة القوالب الآن: ' + str(exc)[:120]
    labels = {'APPROVED': '✅ معتمد', 'PENDING': '⏳ قيد المراجعة', 'REJECTED': '❌ مرفوض'}
    from app.transport_owner import OWNER_INQUIRY_TEMPLATE, inquiry
    rows = [f"• {t.get('name')}: {labels.get(t.get('status'), t.get('status'))}" for t in items
            if str(t.get('name', '')).startswith(('afaaq_transport_', 'afaaq_marketing_'))]
    v4 = next((t for t in items if t.get('name') == OWNER_INQUIRY_TEMPLATE), None)
    if v4:
        parts = v4.get('components') or []
        body = ' '.join(str((parts[0] if parts else {}).get('text') or '').split())
        same = len(parts) == 1 and body == ' '.join(inquiry('{{1}}', '{{2}}').split())
        rows.append('قالب استفسار صاحب الحمولة v4 ' + ('مطابق لنص الوكيل ✅' if same else
                    '⚠️ نصه في Meta يختلف عن نص الوكيل (' + str(len(parts)) + ' أجزاء)'))
    return 'قوالب واتساب في Meta:\n' + ('\n'.join(rows) if rows else 'لا توجد قوالب.')
