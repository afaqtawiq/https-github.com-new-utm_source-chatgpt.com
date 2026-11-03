"""Existing customers first (owner request, Nov 2026).

1) Transport cross-sell: customers we clear for (customs files / FASAH importers) with no transport with us in the last
   120 days get a transport offer for their own route, from the approved price list only.
2) Win-back: registered customers with no recorded activity for 60+ days get a personal check-in.

Every working day at 10:00 (Riyadh) the agent prepares at most 20 personal messages and sends the manager the list with
ONE «نفذ CODE» for the batch. Nothing is sent before that code. Opt-outs, the team's own numbers, anyone messaged by
marketing in the last 21 days and anyone already in this programme in the last 60 days are always skipped. Replies are
classified like outreach replies; interested customers get a formal quote prepared for approval.
"""
import asyncio
import datetime as dt
import json
import os
import re
import threading

from app.storage import db, utcnow

TEMPLATE = 'afaaq_marketing_customer_care_v1_ar'
RIYADH = dt.timezone(dt.timedelta(hours=3))
BATCH_CAP = 20
CROSS_DAYS, DORMANT_DAYS, REPEAT_DAYS, MARKETING_GAP_DAYS = 120, 60, 60, 21
SEGMENTS = {'cross_sell': 'عرض النقل لعملاء التخليص', 'win_back': 'استرجاع عميل متوقف'}


def body(name, offer):
    return (f'مرحبًا {name}،\nشكرًا لثقتكم بآفاق طويق للتخليص الجمركي والنقل.\n{offer}\n'
            'للطلب أو الاستفسار ردّوا على هذه الرسالة.\nلإيقاف الرسائل أرسل: إيقاف')


def template_spec():
    return {'name': TEMPLATE, 'language': 'ar', 'category': 'MARKETING', 'components': [
        {'type': 'body', 'text': body('{{1}}', '{{2}}'),
         'example': {'body_text': [['مؤسسة المثال التجارية',
                                    'يسعدنا نقل حاوياتكم من ميناء جدة الإسلامي إلى مستودعكم في الرياض بسعر معتمد 4,500 ريال للحاوية.']]}}]}


async def ensure_template():
    from app import zernio_whatsapp as wa
    async with wa.client() as c:
        await wa.validate_account(c)
        for item in await wa.templates(c):
            if item.get('name') == TEMPLATE and item.get('language') == 'ar':
                return str(item.get('status') or 'UNKNOWN')
        result = await c.post(wa.BASE + '/whatsapp/templates', json={'accountId': wa.account_id(), **template_spec()})
        return 'SUBMITTED' if result.is_success else 'CREATE_FAILED_' + str(result.status_code)


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS customer_care_batches(id BIGSERIAL PRIMARY KEY, status TEXT NOT NULL DEFAULT 'prepared',
            result TEXT, created_at TIMESTAMPTZ NOT NULL, sent_at TIMESTAMPTZ)''')
        c.execute('''CREATE TABLE IF NOT EXISTS customer_care_messages(id BIGSERIAL PRIMARY KEY, batch_id BIGINT NOT NULL,
            phone TEXT NOT NULL, name TEXT NOT NULL, segment TEXT NOT NULL, offer TEXT NOT NULL, text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'prepared', error TEXT, reply TEXT, reply_intent TEXT, replied_at TIMESTAMPTZ,
            sent_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS customer_care_messages_phone ON customer_care_messages(phone, created_at)')


def digits(value):
    d = re.sub(r'\D', '', str(value or ''))
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('05') and len(d) == 10:
        d = '966' + d[1:]
    elif d.startswith('5') and len(d) == 9:
        d = '966' + d
    return d if 11 <= len(d) <= 15 else ''


def _q(c, sql, args=()):
    """A source that does not exist yet simply contributes nothing."""
    try:
        c.execute('SAVEPOINT care_src')
        rows = c.execute(sql, args).fetchall()
        c.execute('RELEASE SAVEPOINT care_src')
        return rows
    except Exception:
        c.execute('ROLLBACK TO SAVEPOINT care_src')
        return []


def activity(c):
    """phone → {name, roster, last_clearance, ports, last_transport, last_inbound, last_marketing}."""
    people = {}

    def get(phone, name=''):
        p = digits(phone)
        if not p:
            return None
        item = people.setdefault(p, {'phone': p, 'name': '', 'roster': False, 'last_clearance': None, 'ports': [],
                                     'last_transport': None, 'last_inbound': None, 'last_marketing': None})
        if name and not item['name']:
            item['name'] = ' '.join(str(name).split())[:80]
        return item

    def later(a, b):
        return b if a is None or (b is not None and b > a) else a

    for r in _q(c, "SELECT name, phone, COALESCE(status,'') status FROM accounts WHERE phone IS NOT NULL AND phone<>''"):
        item = get(r['phone'], r['name'])
        if item and r['status'].lower() not in ('unsubscribed', 'do_not_contact', 'opted_out', 'محظور', 'إيقاف'):
            item['roster'] = True
    for r in _q(c, "SELECT company_name name, phone FROM customer_directory WHERE phone IS NOT NULL AND phone<>''"):
        item = get(r['phone'], r['name'])
        if item:
            item['roster'] = True
    for r in _q(c, "SELECT customer_name name, customer_phone phone, port, updated_at t FROM customs_declarations WHERE customer_phone<>''"):
        item = get(r['phone'], r['name'])
        if item:
            item['last_clearance'] = later(item['last_clearance'], r['t'])
            if r['port'] and r['port'] not in item['ports']:
                item['ports'].append(r['port'])
    for r in _q(c, '''SELECT k.name, k.phone, MAX(s.seen_at) t FROM fasah_importer_contacts k JOIN fasah_status s
            ON position(k.name in s.details)>0 WHERE k.name<>'__session_notice__' GROUP BY k.name, k.phone'''):
        item = get(r['phone'], r['name'])
        if item:
            item['last_clearance'] = later(item['last_clearance'], r['t'])
    for sql in ("SELECT customer_phone phone, MAX(updated_at) t FROM container_returns WHERE customer_phone<>'' GROUP BY 1",
                "SELECT owner_phone phone, MAX(created_at) t FROM freight_negotiations WHERE owner_phone<>'' GROUP BY 1",
                "SELECT phone, MAX(created_at) t FROM owner_negotiations GROUP BY 1"):
        for r in _q(c, sql):
            item = people.get(digits(r['phone']))
            if item:
                item['last_transport'] = later(item['last_transport'], r['t'])
    for r in _q(c, "SELECT sender phone, MAX(created_at) t FROM whatsapp_agent_jobs WHERE created_at > NOW()-INTERVAL '400 days' GROUP BY 1"):
        item = people.get(digits(r['phone']))
        if item:
            item['last_inbound'] = later(item['last_inbound'], r['t'])
    for r in _q(c, "SELECT recipient phone, MAX(sent_at) t FROM customer_campaign_recipients WHERE channel='whatsapp' AND sent_at IS NOT NULL GROUP BY 1"):
        item = people.get(digits(r['phone']))
        if item:
            item['last_marketing'] = later(item['last_marketing'], r['t'])
    for r in _q(c, "SELECT phone, MAX(COALESCE(sent_at, created_at)) t FROM customer_care_messages WHERE status IN ('sent','uncertain') GROUP BY 1"):
        item = people.get(r['phone'])
        if item:
            item['last_care'] = r['t']
    return people


def blocked(c):
    out = set()
    for r in _q(c, "SELECT recipient FROM marketing_suppressions WHERE channel='whatsapp'"):
        if digits(r['recipient']):
            out.add(digits(r['recipient']))
    try:
        from app.team import team
        out |= {digits(m.get('phone')) for m in team() if digits(m.get('phone'))}
    except Exception:
        pass
    for key in ('WHATSAPP_COMMAND_OWNER',):
        if digits(os.getenv(key, '')):
            out.add(digits(os.getenv(key, '')))
    out |= {'966507665873', '966530130435'}
    return out


# ---------- offers (approved prices only) ----------

def transport_offer(ports):
    from app.prospect_replies import price_table
    _, routes = price_table()
    port = ' '.join(ports)
    if 'رابغ' in port or 'الملك عبدالله' in port:
        route = 'من ميناء الملك عبدالله (رابغ) إلى الرياض'
        where = 'ميناء الملك عبدالله'
    else:
        route = 'من ميناء جدة الإسلامي إلى الرياض'
        where = 'ميناء جدة الإسلامي'
    price = routes.get(route)
    if not price:
        return 'يسعدنا نقل حاوياتكم من الميناء إلى مستودعكم مباشرة بعد التخليص، بأسعار معتمدة وتتبع حتى إعادة الحاوية الفارغة.'
    return (f'بعد تخليص شحناتكم معنا، يسعدنا نقل حاوياتكم من {where} إلى مستودعكم مباشرة '
            f'(مثال: إلى الرياض {price:,} ريال للحاوية حسب عرضنا المعتمد)، مع متابعة إعادة الحاوية الفارغة لتجنب غرامات التأخير.')


WIN_BACK = ('هل لديكم شحنات قادمة؟ نخلّصها في جميع المنافذ السعودية، ونجهّز التخليص قبل وصول الشحنة لتجنب الأرضيات، وننقلها إلى مستودعكم، '
            'وأجور التخليص تبدأ من 200 ريال للحاوية حسب عدد الحاويات.')


def candidates(now=None, limit=BATCH_CAP):
    init()
    now = now or utcnow()
    with db() as c:
        people, stop = activity(c), blocked(c)
    out = []
    for p in people.values():
        if p['phone'] in stop or len(p['phone']) < 11:
            continue
        if p.get('last_care') and now - p['last_care'] < dt.timedelta(days=REPEAT_DAYS):
            continue
        if p['last_marketing'] and now - p['last_marketing'] < dt.timedelta(days=MARKETING_GAP_DAYS):
            continue
        if p['last_inbound'] and now - p['last_inbound'] < dt.timedelta(days=3):
            continue  # talking with us right now: no campaign message on top
        recent_clear = p['last_clearance'] and now - p['last_clearance'] < dt.timedelta(days=CROSS_DAYS)
        recent_transport = p['last_transport'] and now - p['last_transport'] < dt.timedelta(days=CROSS_DAYS)
        stamps = [t for t in (p['last_clearance'], p['last_transport'], p['last_inbound']) if t]
        last = max(stamps) if stamps else None
        dormant = last is None or now - last >= dt.timedelta(days=DORMANT_DAYS)
        if (p['roster'] or p['last_clearance']) and dormant:
            out.append({**p, 'segment': 'win_back', 'offer': WIN_BACK, 'rank': 1 if last else 2})
        elif recent_clear and not recent_transport:
            out.append({**p, 'segment': 'cross_sell', 'offer': transport_offer(p['ports']), 'rank': 0})
    out.sort(key=lambda x: (x['rank'], -(x['last_clearance'] or dt.datetime.min.replace(tzinfo=dt.timezone.utc)).timestamp()))
    return out[:limit]


def name_for(p):
    name = (p.get('name') or '').strip()
    return name if len(name) >= 2 else 'عميلنا العزيز'


def prepare(now=None, limit=BATCH_CAP):
    """Prepare today's batch. Returns the manager message (with one «نفذ» code), or None when nothing to send."""
    from app import transport_desk
    init()
    now = now or utcnow()
    items = candidates(now, limit)
    if not items:
        return None
    with db() as c:
        chat = transport_desk.manager_chat(c)
        if not chat:
            return None
        bid = c.execute('INSERT INTO customer_care_batches(created_at) VALUES(%s) RETURNING id', (now,)).fetchone()['id']
        for p in items:
            text = body(name_for(p), p['offer'])
            c.execute('''INSERT INTO customer_care_messages(batch_id,phone,name,segment,offer,text,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s)''', (bid, p['phone'], name_for(p), p['segment'], p['offer'], text, now))
        token = transport_desk.pending(c, chat[0], chat[1], {'tool': 'customer_care_send', 'batch': bid}, 24 * 60)
    counts = {s: sum(1 for p in items if p['segment'] == s) for s in SEGMENTS}
    lines = [f'🤝 رسائل العملاء الحاليين لليوم (دفعة #{bid}) — {len(items)} عميل:',
             f"• {SEGMENTS['cross_sell']}: {counts['cross_sell']}", f"• {SEGMENTS['win_back']}: {counts['win_back']}", '']
    for p in items[:20]:
        lines.append(f"• {name_for(p)} (+{p['phone']}) — {SEGMENTS[p['segment']]}")
    sample = next((p for p in items if p['segment'] == 'cross_sell'), items[0])
    lines += ['', 'نموذج الرسالة:', body(name_for(sample), sample['offer']), '',
              f'للإرسال لكل القائمة اكتب: نفذ {token}', 'وإذا ما تبي ترسل اليوم تجاهل الرمز.']
    return '\n'.join(lines)


async def send_batch(bid):
    from app import zernio_whatsapp as wa
    init()
    status = await ensure_template()
    if status != 'APPROVED':
        return f'⏳ قالب رسائل العملاء ({TEMPLATE}) حالته في ميتا: {status}. لم تُرسل الدفعة #{bid}؛ أرسلها بعد الاعتماد.'
    with db() as c:
        claimed = c.execute("UPDATE customer_care_batches SET status='sending' WHERE id=%s AND status='prepared' RETURNING id", (bid,)).fetchone()
        rows = c.execute("SELECT * FROM customer_care_messages WHERE batch_id=%s AND status='prepared' ORDER BY id", (bid,)).fetchall() if claimed else []
        stop = blocked(c)
    if not claimed:
        return f'الدفعة #{bid} أُرسلت أو أُلغيت سابقًا؛ لم يُرسل شيء.'
    sent = failed = skipped = 0
    stopped = None
    for r in rows:
        if r['phone'] in stop:
            with db() as c:
                c.execute("UPDATE customer_care_messages SET status='skipped',error='suppressed' WHERE id=%s", (r['id'],))
            skipped += 1
            continue
        try:
            await wa.send('+' + r['phone'], r['text'], template_prefix='afaaq_marketing_')
            with db() as c:
                c.execute("UPDATE customer_care_messages SET status='sent',sent_at=%s WHERE id=%s", (utcnow(), r['id']))
            sent += 1
        except wa.WhatsAppBlocked as exc:
            with db() as c:
                c.execute("UPDATE customer_care_messages SET status='failed',error=%s WHERE id=%s", (str(exc)[:200], r['id']))
            failed += 1
        except Exception as exc:  # uncertain provider result: stop, never retry automatically
            with db() as c:
                c.execute("UPDATE customer_care_messages SET status='uncertain',error=%s WHERE id=%s", (type(exc).__name__, r['id']))
            stopped = type(exc).__name__
            break
    result = f'✅ دفعة العملاء #{bid}: أُرسلت {sent}' + (f'، تعذر {failed}' if failed else '') + (f'، مستبعد {skipped}' if skipped else '') + (
        f'\n⚠️ توقفت الدفعة لنتيجة غير مؤكدة ({stopped}) ولم أعد المحاولة تلقائيًا.' if stopped else '')
    with db() as c:
        c.execute("UPDATE customer_care_batches SET status='sent',sent_at=%s,result=%s WHERE id=%s", (utcnow(), result, bid))
    return result


def start_send(bid):
    """Called after «نفذ CODE»: sends in the background and reports the result to the manager."""
    def run():
        try:
            text = asyncio.run(send_batch(int(bid)))
        except Exception as exc:
            text = f'⚠️ تعذر إرسال دفعة العملاء #{bid}: {type(exc).__name__}'
        try:
            from app.owner_briefing import deliver
            asyncio.run(deliver(text))
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()
    return f'⏳ بدأ إرسال دفعة العملاء #{bid}؛ أرسل لك النتيجة خلال دقائق.'


# ---------- replies ----------

def process_replies(now=None):
    """First reply from a customer of a sent batch (7 days): stop → suppression; interested → alert + quote for approval."""
    from app import prospect_replies, transport_desk
    init()
    now = now or utcnow()
    out = []
    with db() as c:
        if not c.execute("SELECT to_regclass('whatsapp_agent_jobs') t").fetchone()['t']:
            return out
        rows = c.execute('''SELECT m.id, m.phone, m.name, m.segment, j.payload, j.sender FROM customer_care_messages m
            JOIN LATERAL (SELECT * FROM whatsapp_agent_jobs j WHERE right(regexp_replace(j.sender,'\\D','','g'),9)=right(m.phone,9)
                AND j.created_at > m.sent_at ORDER BY j.id LIMIT 1) j ON TRUE
            WHERE m.status='sent' AND m.replied_at IS NULL AND m.sent_at > %s - INTERVAL '7 days' LIMIT 50''', (now,)).fetchall()
    for r in rows:
        text = prospect_replies.message_text(r['payload'])
        d = prospect_replies.classify(text) if text else {'intent': 'other'}
        intent = d.get('intent', 'other')
        with db() as c:
            if not c.execute('''UPDATE customer_care_messages SET replied_at=%s,reply=%s,reply_intent=%s WHERE id=%s AND replied_at IS NULL
                    RETURNING id''', (now, text[:2000], intent, r['id'])).fetchone():
                continue
            if intent == 'stop':
                c.execute("INSERT INTO marketing_suppressions(channel,recipient,created_at) VALUES('whatsapp',%s,%s) ON CONFLICT DO NOTHING",
                          ('+' + r['phone'], now))
                out.append(f"📭 {r['name']} طلب إيقاف الرسائل؛ أوقفت عنه كل الرسائل التسويقية.")
                continue
            if intent not in prospect_replies.HOT:
                if intent == 'not_interested':
                    out.append(f"📭 {r['name']} رد على رسالة العملاء: غير مهتم حاليًا.")
                continue
            lines = [f"🔥 عميل حالي رد: {r['name']} (+{r['phone']}) — {SEGMENTS[r['segment']]}",
                     f"التصنيف: {prospect_replies.INTENTS[intent]}", f'رسالته: «{text[:300]}»']
            for label, k in (('المطلوب', 'summary'), ('البضاعة', 'cargo'), ('المنفذ', 'port'), ('الوجهة', 'destination'),
                             ('عدد الحاويات', 'containers')):
                if d.get(k):
                    lines.append(f'{label}: {d[k]}')
            number = 'ATQ-' + now.astimezone(RIYADH).strftime('%y%m%d') + '-C' + str(r['id']).zfill(4)
            quote, total, missing = prospect_replies.build_quote(r['name'], d, number) if (
                d.get('containers') or d.get('route_key') or intent == 'price_request') else (None, 0, [])
            chat = transport_desk.manager_chat(c)
            if quote and chat:
                token = transport_desk.pending(c, chat[0], chat[1], {'tool': 'send_whatsapp', 'to': '+' + r['phone'], 'text': quote}, 24 * 60)
                lines += ['', f'📄 عرض سعر جاهز ({number}) — {total:,} ريال:', quote, '', f'للإرسال اكتب: نفذ {token}']
            if missing:
                lines.append('⚠️ يحتاج تسعير من الفريق: ' + '، '.join(missing))
            lines.append('الوكيل رد عليه في المحادثة ويكمل التفاصيل.')
            out.append('\n'.join(lines))
    return out


def status_text(days=30):
    init()
    with db() as c:
        rows = c.execute('''SELECT segment, status, COUNT(*) n, COUNT(replied_at) r,
            COUNT(*) FILTER (WHERE reply_intent IN ('interested','price_request','question')) hot
            FROM customer_care_messages WHERE created_at > NOW()-make_interval(days => %s) GROUP BY 1,2''', (int(days),)).fetchall()
    upcoming = candidates()
    lines = [f'🤝 برنامج العملاء الحاليين — آخر {days} يوم:']
    if not rows:
        lines.append('لم تُرسل رسائل بعد.')
    for seg, label in SEGMENTS.items():
        sent = sum(r['n'] for r in rows if r['segment'] == seg and r['status'] == 'sent')
        replied = sum(r['r'] for r in rows if r['segment'] == seg)
        hot = sum(r['hot'] for r in rows if r['segment'] == seg)
        if sent or replied:
            lines.append(f'• {label}: أُرسلت {sent} — ردود {replied} — مهتمون {hot}')
    lines.append(f"المرشحون الآن: {sum(1 for p in upcoming if p['segment'] == 'cross_sell')} لعرض النقل، "
                 f"{sum(1 for p in upcoming if p['segment'] == 'win_back')} للاسترجاع (الحد {BATCH_CAP} يوميًا).")
    lines.append('لتجهيز دفعة الآن اكتب: جهز رسائل العملاء')
    return '\n'.join(lines)


# ---------- schedule ----------

def due_today(now=None):
    now = now or utcnow()
    local = now.astimezone(RIYADH)
    if os.getenv('CUSTOMER_CARE', '1') == '0' or local.weekday() in (4, 5) or local.hour < 10:
        return False  # Friday/Saturday off; from 10:00 Riyadh
    init()
    with db() as c:
        start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc)
        return not c.execute('SELECT 1 FROM customer_care_batches WHERE created_at >= %s LIMIT 1', (start,)).fetchone()


def register_worker(app):
    async def loop():
        from starlette.concurrency import run_in_threadpool
        from app.owner_briefing import deliver
        await asyncio.sleep(260)
        try:
            print('CUSTOMER_CARE_TEMPLATE', await ensure_template(), flush=True)
        except Exception as exc:
            print('CUSTOMER_CARE_TEMPLATE', 'ERROR_' + type(exc).__name__, flush=True)
        while True:
            try:
                if await run_in_threadpool(due_today):
                    text = await run_in_threadpool(prepare)
                    if text:
                        await deliver(text)
                for text in await run_in_threadpool(process_replies):
                    await deliver(text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('CUSTOMER_CARE_WORKER', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(300)

    @app.on_event('startup')
    async def start():
        init()
        app.state.customer_care_worker = asyncio.create_task(loop())
