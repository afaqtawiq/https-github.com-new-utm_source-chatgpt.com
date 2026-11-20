"""Owner-requested: a load sent by the manager on WhatsApp is offered to ALL registered drivers (Nov 2026).

Flow: team member writes the load -> tool broadcast_load prepares the offer and counts recipients -> the
manager confirms with «نفذ CODE» -> the offer is sent one by one, in the exact text of the approved Meta
template afaaq_transport_driver_offer_v1_ar (so it reaches drivers outside the 24h window). Each driver
receives a load once; results are stored. Drivers answer «موافق AFT-n» and the manager sees it.
"""
import asyncio
import os
import re
import threading

from app.storage import db, utcnow


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS load_broadcasts(
            id BIGSERIAL PRIMARY KEY, origin TEXT NOT NULL, destination TEXT NOT NULL, weight TEXT NOT NULL,
            driver_price TEXT NOT NULL, unloading TEXT NOT NULL, payment TEXT NOT NULL, audience TEXT NOT NULL,
            message TEXT NOT NULL, status TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
            created_by TEXT, created_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ)''')
        c.execute('''CREATE TABLE IF NOT EXISTS load_broadcast_recipients(
            broadcast_id BIGINT NOT NULL REFERENCES load_broadcasts(id), driver_id BIGINT, phone TEXT NOT NULL,
            status TEXT NOT NULL, error TEXT, sent_at TIMESTAMPTZ, PRIMARY KEY(broadcast_id, phone))''')
        c.execute('ALTER TABLE load_broadcasts ADD COLUMN IF NOT EXISTS negotiation_id BIGINT')
        c.execute('ALTER TABLE load_broadcasts ADD COLUMN IF NOT EXISTS assigned_phone TEXT')
        c.execute('ALTER TABLE load_broadcast_recipients ADD COLUMN IF NOT EXISTS replied_at TIMESTAMPTZ')


def clean(value, limit=80):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def price_text(value):
    raw = re.sub(r'[^\d.]', '', str(value or ''))
    try:
        return f'{float(raw):,.2f}'
    except ValueError:
        return ''


def message(ref, load):
    """Exactly the approved template body (afaaq_transport_driver_offer_v1_ar)."""
    return (f'عرض حمولة من آفاق طويق — {ref}\n'
            f"المسار: {load['origin']} → {load['destination']}\n"
            f"الوزن: {load['weight']} طن\n"
            f"سعر السائق: {load['driver_price']} ريال\n"
            f"التنزيل: {load['unloading']}\n"
            f"الدفع: {load['payment']}\n"
            f'للرغبة اكتب: موافق {ref}\nشكرًا لتعاونك.')


def audience_filter(audience):
    return {'saudi': "AND regexp_replace(whatsapp_phone,'\\D','','g') LIKE '966%%'",
            'uae': "AND regexp_replace(whatsapp_phone,'\\D','','g') LIKE '971%%'"}.get(audience, '')


def drivers(audience='all'):
    with db() as c:
        return c.execute("""SELECT id, driver_name, whatsapp_phone FROM drivers
            WHERE COALESCE(offer_consent,1)=1 AND COALESCE(availability,'') NOT IN ('غير متاح','موقوف') """
                         + audience_filter(audience) + ' ORDER BY id').fetchall()


def normalize(args):
    load = {'origin': clean(args.get('origin')), 'destination': clean(args.get('destination')),
            'weight': clean(args.get('weight'), 12), 'driver_price': price_text(args.get('driver_price')),
            'unloading': clean(args.get('unloading')) or clean(args.get('destination')),
            'payment': clean(args.get('payment')) or 'حسب الاتفاق',
            'audience': args.get('audience') if args.get('audience') in ('saudi', 'uae') else 'all'}
    missing = [label for key, label in (('origin', 'مدينة التحميل'), ('destination', 'الوجهة'), ('weight', 'الوزن'),
                                        ('driver_price', 'سعر السائق')) if not load[key]]
    return load, missing


def prepare(args):
    """Validate and count recipients; returns (load, count, error)."""
    init()
    load, missing = normalize(args)
    if missing:
        return load, 0, 'ناقص: ' + '، '.join(missing)
    return load, len(drivers(load['audience'])), None


async def send_all(broadcast_id):
    from app import zernio_whatsapp as z
    with db() as c:
        item = c.execute('SELECT * FROM load_broadcasts WHERE id=%s', (broadcast_id,)).fetchone()
        targets = c.execute("SELECT phone FROM load_broadcast_recipients WHERE broadcast_id=%s AND status='pending'",
                            (broadcast_id,)).fetchall()
    sent = failed = 0
    stop_after = int(os.getenv('LOAD_BROADCAST_STOP_AFTER', '5') or 0)
    stopped = None
    for row in targets:
        with db() as c:
            state = c.execute('''SELECT b.status,b.assigned_phone,(SELECT COUNT(*) FROM load_broadcast_recipients r
                WHERE r.broadcast_id=b.id AND r.status IN ('accepted','assigned')) a FROM load_broadcasts b WHERE b.id=%s''',
                              (broadcast_id,)).fetchone()
        if state['status'] == 'stop_requested':
            stopped = 'أوقفه المدير'
        elif state.get('assigned_phone'):
            stopped = 'أُسندت الحمولة'
        elif stop_after and state['a'] >= stop_after:
            stopped = f"وصلت {state['a']} موافقات"
        if stopped:
            break
        with db() as c:
            claimed = c.execute("""UPDATE load_broadcast_recipients SET status='sending' WHERE broadcast_id=%s AND phone=%s
                AND status='pending' RETURNING phone""", (broadcast_id, row['phone'])).fetchone()
        if not claimed:
            continue
        status, error = 'sent', None
        localized = None
        try:
            from app import driver_language as dl
            dl.init()
            with db() as c:
                lang = dl.driver_language(c, row['phone'])
            localized = dl.offer_for(lang, 'AFT-' + str(broadcast_id), item)
        except Exception:
            localized = None
        try:
            if localized:
                try:  # free text works only inside an open 24h window; else fall back to the Arabic template
                    await z.send(row['phone'], localized)
                except z.WhatsAppBlocked:
                    await z.send(row['phone'], item['message'])
            else:
                await z.send(row['phone'], item['message'])
        except Exception as exc:  # never retried automatically
            status, error = ('failed' if isinstance(exc, z.WhatsAppBlocked) else 'uncertain'), str(exc)[:200]
        with db() as c:
            c.execute('UPDATE load_broadcast_recipients SET status=%s,error=%s,sent_at=%s WHERE broadcast_id=%s AND phone=%s',
                      (status, error, utcnow(), broadcast_id, row['phone']))
        sent += status == 'sent'
        failed += status != 'sent'
        await asyncio.sleep(float(os.getenv('LOAD_BROADCAST_DELAY', '1.2')))
    with db() as c:
        if stopped:
            c.execute("UPDATE load_broadcast_recipients SET status='skipped' WHERE broadcast_id=%s AND status='pending'", (broadcast_id,))
        c.execute("UPDATE load_broadcasts SET status=%s,sent=sent+%s,failed=failed+%s,finished_at=%s WHERE id=%s",
                  ('stopped' if stopped else 'done', sent, failed, utcnow(), broadcast_id))
    print('LOAD_BROADCAST', broadcast_id, 'sent', sent, 'failed', failed, 'stopped' if stopped else 'done', stopped or '', flush=True)


def interrupted_on_startup():
    """The sender thread lives in the web process; after a restart nothing is sending any more. Say so honestly."""
    init()
    with db() as c:
        c.execute("UPDATE load_broadcast_recipients SET status='uncertain',error='انقطع أثناء الإرسال (إعادة تشغيل)' "
                  "WHERE status='sending' AND broadcast_id IN (SELECT id FROM load_broadcasts WHERE status IN ('sending','stop_requested'))")
        c.execute("UPDATE load_broadcasts SET status='interrupted',finished_at=%s WHERE status IN ('sending','stop_requested')", (utcnow(),))


def stop(ref):
    m = re.search(r'(\d+)', str(ref or ''))
    if not m:
        return 'اذكر رقم الحمولة مثل AFT-7.'
    with db() as c:
        row = c.execute("UPDATE load_broadcasts SET status='stop_requested' WHERE id=%s AND status='sending' RETURNING id",
                        (int(m.group(1)),)).fetchone()
    return (f'⏹️ أوقفت إرسال AFT-{m.group(1)}؛ ما يُرسل لأي سائق جديد بعد الآن.' if row
            else f'إرسال AFT-{m.group(1)} غير جارٍ أصلًا (منتهٍ أو متوقف).')


def start(action, actor_name=''):
    """Create the broadcast with all current recipients and send in the background. Returns a reply."""
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        return 'الإرسال الخارجي متوقف على الخادم؛ لم يُرسل شيء.'
    init()
    load, missing = normalize(action)
    if missing:
        return 'ناقص: ' + '، '.join(missing) + '؛ لم يُرسل شيء.'
    targets = drivers(load['audience'])
    if not targets:
        return 'لا يوجد سائقون مسجلون لهذه الفئة؛ لم يُرسل شيء.'
    with db() as c:
        nid = action.get('negotiation_id')
        bid = c.execute('''INSERT INTO load_broadcasts(origin,destination,weight,driver_price,unloading,payment,audience,message,status,created_by,created_at,negotiation_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,'','sending',%s,%s,%s) RETURNING id''',
            (load['origin'], load['destination'], load['weight'], load['driver_price'], load['unloading'], load['payment'],
             load['audience'], actor_name, utcnow(), int(nid) if nid else None)).fetchone()['id']
        ref = 'AFT-' + str(bid)
        text = message(ref, load)
        c.execute('UPDATE load_broadcasts SET message=%s WHERE id=%s', (text, bid))
        seen = set()
        for d in targets:
            phone = re.sub(r'\D', '', str(d['whatsapp_phone'] or ''))
            if len(phone) < 9 or phone in seen:
                continue
            seen.add(phone)
            c.execute("INSERT INTO load_broadcast_recipients(broadcast_id,driver_id,phone,status) VALUES(%s,%s,%s,'pending') ON CONFLICT DO NOTHING",
                      (bid, d['id'], phone))
    threading.Thread(target=lambda: asyncio.run(send_all(bid)), daemon=True).start()
    return (f'✅ بدأ إرسال الحمولة {ref} إلى {len(seen)} سائق ({load["origin"]} → {load["destination"]}، سعر السائق {load["driver_price"]} ريال). '
            f'السائق يرد بـ «موافق {ref}» وأبلغك فورًا بكل موافقة لتختار السائق. اسأل «حالة الإرسال {ref}» لمعرفة النتيجة.')


def status_text(ref):
    m = re.search(r'(\d+)', str(ref or ''))
    with db() as c:
        row = c.execute('SELECT * FROM load_broadcasts WHERE id=%s', (int(m.group(1)),)).fetchone() if m else \
            c.execute('SELECT * FROM load_broadcasts ORDER BY id DESC LIMIT 1').fetchone()
        if not row:
            return 'لا يوجد إرسال حمولات مسجل.'
        counts = c.execute('''SELECT COUNT(*) FILTER (WHERE status='sent') s, COUNT(*) FILTER (WHERE status IN ('failed','uncertain')) f,
            COUNT(*) FILTER (WHERE status IN ('pending','sending')) p,
            COUNT(*) FILTER (WHERE status IN ('accepted','assigned')) a, COUNT(*) FILTER (WHERE status='skipped') k
            FROM load_broadcast_recipients WHERE broadcast_id=%s''', (row['id'],)).fetchone()
    label = {'sending': 'الإرسال جارٍ الآن', 'done': 'اكتمل الإرسال', 'stop_requested': 'جارٍ الإيقاف',
             'stopped': f"توقف الإرسال تلقائيًا ({counts['k']} سائق لم يُرسل لهم)",
             'interrupted': 'الإرسال متوقف (انقطع بإعادة تشغيل الخادم) — لا يُرسل شيء الآن'}.get(row['status'], row['status'])
    pending = counts['p'] if row['status'] in ('sending', 'stop_requested') else 0
    return (f"الحمولة AFT-{row['id']} ({row['origin']} → {row['destination']}): {label}. أُرسلت {counts['s']}، "
            f"تعذر {counts['f']}، متبقي {pending}، وافق {counts['a']}."
            + (f" — مسندة للسائق +{row['assigned_phone']}" if row.get('assigned_phone') else ''))
