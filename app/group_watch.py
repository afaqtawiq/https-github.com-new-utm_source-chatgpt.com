"""WhatsApp GROUP watch (owner report, 20 Nov 2026: a partner group asked about an HS code approval with two packing lists
and nobody answered for an hour — «شغل كويس ربما ضاع منا بعدم المتابعة»).

Group messages were dropped at intake (the agent never answers in groups). Now they are kept, the important ones
(a question, a request, a document) are tracked, and when nobody from Afaq answers in the group within 30 minutes the
owner gets an alert with the message and the next step; still unanswered after 2 hours → escalation. Nothing is ever
posted in a group from here.

Sources: the webhook (when the provider pushes group events) and a light polling fallback over the group conversations.
GROUP_WATCH_ENABLED=0 turns it off.
"""
import collections
import datetime as dt
import os
import re
from urllib.parse import quote

from app.storage import db, utcnow

RIYADH = dt.timezone(dt.timedelta(hours=3))
FIRST, ESCALATE = 30, 120            # minutes without an answer
POLL_GROUPS = 3                      # group conversations read per polling round
_READY = False

ASK = re.compile(r'[?؟]|\b(pls|please|plz|kindly|can you|could you|check|confirm|quote|quotation|rate|price|cost|hs ?code|'
                 r'approval|license|licence|urgent|asap|required|need|when|eta|status|update|advise|send)\b|'
                 r'(ممكن|ابغى|ابغي|ابي|نبغى|نبي|كم|سعر|عرض|متى|وين|ضروري|عاجل|لو سمحت|تكفى|بيان|تخليص|فسح|بند|تعرفة|'
                 r'موافقة|ترخيص|سابر|الحاوية|الشحنة|ارسل|أرسل|ردوا|رد علي|وش صار|ايش صار|تحديث)', re.I)
SMALL = re.compile(r'^\s*(ok|okay|thanks?|thank you|tnx|noted|well noted|done|👍|🙏|✅|تمام|شكرا|شكراً|مشكور|يعطيك العافية|'
                   r'تم|ابشر|أبشر|حاضر|اوكي|اوك|طيب|خلاص)[\s.!]*$', re.I)
NEXT = ((re.compile(r'hs ?code|approval|license|licence|بند|تعرفة|سابر|موافقة|ترخيص|اشتراطات', re.I), 'فيصل (التخليص): «فيصل: راجع البند والاشتراطات للمنتج …»'),
        (re.compile(r'container|demurrage|detention|eta|arrival|vessel|حاوية|الحاويات|وصول|الباخرة|غرامة', re.I), 'سلطان (الحاويات): «سلطان: …»'),
        (re.compile(r'truck|transport|trailer|delivery|نقل|شاحنة|سطحة|توصيل|سواق', re.I), 'خالد (النقل): «خالد: …»'),
        (re.compile(r'invoice|payment|statement|فاتورة|دفع|سداد|كشف|حساب', re.I), 'نورة (المالية): «نورة: …»'),
        (re.compile(r'quote|quotation|rate|price|cost|سعر|عرض', re.I), 'ريم (المبيعات): «ريم: جهزي عرض سعر …»'))


def enabled():
    return os.getenv('GROUP_WATCH_ENABLED', '1') != '0'


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_group_messages(id BIGSERIAL PRIMARY KEY, account_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL, group_name TEXT NOT NULL DEFAULT '', message_id TEXT NOT NULL UNIQUE,
            direction TEXT NOT NULL DEFAULT 'incoming', sender TEXT NOT NULL DEFAULT '', sender_name TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '', media INTEGER NOT NULL DEFAULT 0, team BOOLEAN NOT NULL DEFAULT FALSE,
            important BOOLEAN NOT NULL DEFAULT FALSE, level INTEGER NOT NULL DEFAULT 0, answered_at TIMESTAMPTZ,
            received_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS whatsapp_group_messages_conv ON whatsapp_group_messages(conversation_id, received_at)')
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_group_poll(conversation_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
            polled_at TIMESTAMPTZ)''')
        # Request inbox (group_requests): which message a reply quotes, and the attached file names.
        c.execute("ALTER TABLE whatsapp_group_messages ADD COLUMN IF NOT EXISTS quoted_id TEXT")
        c.execute("ALTER TABLE whatsapp_group_messages ADD COLUMN IF NOT EXISTS files TEXT NOT NULL DEFAULT '[]'")
        # Intake health: last successful read of the group conversations / last webhook event.
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_group_health(key TEXT PRIMARY KEY, ok_at TIMESTAMPTZ,
            error TEXT NOT NULL DEFAULT '', error_at TIMESTAMPTZ)''')
    _READY = True


def health_mark(key, ok, error='', at=None):
    """Record a successful (or failed) intake read: 'poll' for the provider read, 'webhook' for pushed events."""
    init()
    at = at or utcnow()
    with db() as c:
        if ok:
            c.execute('''INSERT INTO whatsapp_group_health(key,ok_at) VALUES(%s,%s)
                ON CONFLICT(key) DO UPDATE SET ok_at=EXCLUDED.ok_at''', (key, at))
        else:
            c.execute('''INSERT INTO whatsapp_group_health(key,error,error_at) VALUES(%s,%s,%s)
                ON CONFLICT(key) DO UPDATE SET error=EXCLUDED.error, error_at=EXCLUDED.error_at''', (key, str(error)[:300], at))


def quoted_of(m):
    """The id of the message this one replies to (provider shapes differ)."""
    for key in ('replyTo', 'reply_to', 'quotedMessageId', 'quotedId', 'replyToMessageId', 'contextMessageId'):
        v = m.get(key)
        if isinstance(v, dict):
            v = v.get('id') or v.get('messageId') or v.get('platformMessageId')
        if isinstance(v, str) and v.strip():
            return v.strip()[:255]
    for key in ('context', 'quoted', 'quotedMessage', 'replyContext'):
        v = m.get(key)
        if isinstance(v, dict):
            inner = v.get('id') or v.get('message_id') or v.get('messageId') or v.get('platformMessageId')
            if isinstance(inner, str) and inner.strip():
                return inner.strip()[:255]
    return None


def files_of(atts):
    out = []
    for a in atts:
        if isinstance(a, dict):
            name = a.get('fileName') or a.get('filename') or a.get('name') or a.get('caption') or a.get('type') or 'ملف'
            out.append(' '.join(str(name).split())[:120])
    return out


def _digits(v):
    return re.sub(r'\D', '', str(v or ''))


def _team():
    from app.no_wait import _team_numbers
    return _team_numbers()


def important(text, media):
    text = str(text or '').strip()
    if media and not SMALL.match(text):
        return True
    if not text or SMALL.match(text) or len(text) < 4:
        return False
    return bool(ASK.search(text))


def _when(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return utcnow()


def store(account, cid, name, mid, direction, sender, sender_name, text, media, at, quoted_id=None, files=None):
    """Insert one group message (idempotent). Returns True when it was new."""
    import json as _json
    init()
    team = direction != 'incoming' or (_digits(sender) in _team())
    imp = direction == 'incoming' and not team and important(text, media)
    with db() as c:
        row = c.execute('''INSERT INTO whatsapp_group_messages(account_id,conversation_id,group_name,message_id,direction,sender,
            sender_name,text,media,team,important,received_at,created_at,quoted_id,files)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(message_id) DO NOTHING RETURNING id''',
                        (account, cid, (name or '')[:200], str(mid)[:255], direction, _digits(sender)[:20], (sender_name or '')[:120],
                         str(text or '')[:4000], int(media or 0), team, imp, at, utcnow(), quoted_id,
                         _json.dumps(list(files or [])[:10], ensure_ascii=False))).fetchone()
        if row and team:
            # Someone from Afaq spoke in the group: earlier open messages there count as answered.
            c.execute('''UPDATE whatsapp_group_messages SET answered_at=%s WHERE conversation_id=%s AND important
                AND answered_at IS NULL AND received_at <= %s''', (at, cid, at))
    return bool(row)


_QUEUE = collections.deque(maxlen=2000)


def capture(payload):
    """Webhook hook (message.received): only queues the group event in memory — no database work inside the webhook.
    The watch flushes the queue every round; the polling fallback covers anything lost on a restart."""
    try:
        if not enabled():
            return False
        conv, msg = payload.get('conversation') or {}, payload.get('message') or {}
        if not (conv.get('isGroup') or msg.get('isGroup')):
            return False
        _QUEUE.append(payload)
        return True
    except Exception as exc:
        print('GROUP_WATCH_CAPTURE', type(exc).__name__, str(exc)[:120], flush=True)
        return False


def flush():
    """Store the queued webhook group events. Returns how many were new."""
    n = 0
    while _QUEUE:
        n += bool(_store_event(_QUEUE.popleft()))
    return n


def _store_event(payload):
    try:
        conv, msg = payload.get('conversation') or {}, payload.get('message') or {}
        if not (conv.get('isGroup') or msg.get('isGroup')):
            return False
        sender = msg.get('sender') if isinstance(msg.get('sender'), dict) else {}
        atts = msg.get('attachments') if isinstance(msg.get('attachments'), list) else []
        text = msg.get('text') or msg.get('message') or msg.get('body') or ''
        if isinstance(text, dict):
            text = text.get('body') or ''
        captions = ' '.join(str(a.get('caption') or a.get('fileName') or a.get('filename') or '') for a in atts if isinstance(a, dict))
        account = (payload.get('account') or {}).get('accountId') or (payload.get('account') or {}).get('id') or ''
        ok = store(account, conv.get('id') or '', conv.get('name') or conv.get('participantName') or conv.get('title') or '',
                   msg.get('platformMessageId') or msg.get('id') or payload.get('id'), 'incoming',
                   sender.get('phoneNumber') or sender.get('id') or '', sender.get('name') or sender.get('displayName') or '',
                   (str(text) + (' ' + captions if captions else '')).strip(), len(atts), _when(msg.get('createdAt')),
                   quoted_of(msg), files_of(atts))
        health_mark('webhook', True)
        return ok
    except Exception as exc:
        print('GROUP_WATCH_CAPTURE', type(exc).__name__, str(exc)[:120], flush=True)
        return False


def _msg_fields(m):
    sender = m.get('sender') if isinstance(m.get('sender'), dict) else {}
    atts = m.get('attachments') if isinstance(m.get('attachments'), list) else []
    text = m.get('message') or m.get('text') or ''
    if isinstance(text, dict):
        text = text.get('body') or ''
    captions = ' '.join(str(a.get('caption') or a.get('fileName') or a.get('filename') or '') for a in atts if isinstance(a, dict))
    who = (sender.get('phoneNumber') or sender.get('id') or m.get('senderPhone') or m.get('from') or m.get('participantId') or '')
    name = sender.get('name') or sender.get('displayName') or m.get('senderName') or ''
    return (m.get('platformMessageId') or m.get('id'), 'incoming' if m.get('direction') == 'incoming' else 'outgoing',
            who, name, (str(text) + (' ' + captions if captions else '')).strip(), len(atts), _when(m.get('createdAt')),
            quoted_of(m), files_of(atts))


async def poll(now=None):
    """Fallback when group events are not pushed: read the most stale group conversations. Returns new messages stored."""
    from starlette.concurrency import run_in_threadpool
    from app import statement_groups
    from app import zernio_whatsapp as z
    init()
    now = now or utcnow()
    try:
        found = await statement_groups.groups()
    except Exception as exc:
        print('GROUP_WATCH_LIST', type(exc).__name__, str(exc)[:120], flush=True)
        await run_in_threadpool(health_mark, 'poll', False, type(exc).__name__ + ': ' + str(exc)[:200])
        return 0

    def plan():
        with db() as c:
            for cid, name in found:
                c.execute('''INSERT INTO whatsapp_group_poll(conversation_id,name) VALUES(%s,%s)
                    ON CONFLICT(conversation_id) DO UPDATE SET name=EXCLUDED.name''', (cid, name or ''))
            ids = [cid for cid, _ in found]
            return c.execute('''SELECT * FROM whatsapp_group_poll WHERE conversation_id = ANY(%s)
                ORDER BY polled_at NULLS FIRST LIMIT %s''', (ids, poll_groups())).fetchall() if ids else []
    stored, failed = 0, 0
    if os.getenv('GROUP_WATCH_DEBUG_KEYS') == '1':
        print('GROUP_WATCH_GROUPS', len(found), [n[:30] for _, n in found][:12], flush=True)
    for g in await run_in_threadpool(plan):
        try:
            async with z.client() as c:
                data = await z.read(c, '/inbox/conversations/' + quote(g['conversation_id'], safe='') + '/messages',
                                    {'accountId': z.account_id(), 'sortOrder': 'desc', 'limit': 25})
        except Exception as exc:
            print('GROUP_WATCH_READ', type(exc).__name__, str(exc)[:120], flush=True)
            failed += 1
            await run_in_threadpool(health_mark, 'poll', False, type(exc).__name__ + ': ' + str(exc)[:200])
            continue
        msgs = [m for m in (data.get('messages') or []) if isinstance(m, dict)] if isinstance(data, dict) else []
        if msgs and os.getenv('GROUP_WATCH_DEBUG_KEYS') == '1':
            print('GROUP_WATCH_KEYS', sorted(msgs[0].keys())[:40], flush=True)
        for m in sorted(msgs, key=lambda m: str(m.get('createdAt') or '')):
            mid, direction, who, name, text, media, at, quoted, files = _msg_fields(m)
            if mid and now - at < dt.timedelta(days=2):
                stored += await run_in_threadpool(store, z.account_id(), g['conversation_id'], g['name'], mid, direction,
                                                  who, name, text, media, at, quoted, files)
        await run_in_threadpool(lambda: _touch(g['conversation_id'], now))
    if not failed:
        await run_in_threadpool(health_mark, 'poll', True, '', now)
    return stored


def poll_groups():
    try:
        return max(1, min(20, int(os.getenv('GROUP_WATCH_POLL_GROUPS', str(POLL_GROUPS)))))
    except ValueError:
        return POLL_GROUPS


def _touch(cid, now):
    with db() as c:
        c.execute('UPDATE whatsapp_group_poll SET polled_at=%s WHERE conversation_id=%s', (now, cid))


def due(now):
    init()
    with db() as c:
        return c.execute('''SELECT * FROM whatsapp_group_messages WHERE important AND answered_at IS NULL
            AND received_at > %s AND ((level = 0 AND received_at <= %s) OR (level = 1 AND received_at <= %s))
            ORDER BY received_at LIMIT 10''', (now - dt.timedelta(days=2), now - dt.timedelta(minutes=FIRST),
                                               now - dt.timedelta(minutes=ESCALATE))).fetchall()


def _thread(c, m):
    """The burst this message belongs to: same sender, same group, within 15 minutes before it (files + question)."""
    return c.execute('''SELECT * FROM whatsapp_group_messages WHERE conversation_id=%s AND sender=%s AND direction='incoming'
        AND received_at BETWEEN %s AND %s ORDER BY received_at''', (m['conversation_id'], m['sender'],
                                                                    m['received_at'] - dt.timedelta(minutes=15),
                                                                    m['received_at'] + dt.timedelta(minutes=15))).fetchall()


def alert_text(m, burst, now):
    minutes = int((now - m['received_at']).total_seconds() // 60)
    span = f'{minutes} دقيقة' if minutes < 120 else f'{minutes // 60} ساعة'
    who = m['sender_name'] or ('+' + m['sender'] if m['sender'] else 'عضو')
    files = sum(x['media'] for x in burst)
    text = ' '.join(' '.join(x['text'].split()) for x in burst if x['text'])[:500]
    head = '🚨 تصعيد' if m['level'] == 1 else '📣 رسالة مهمة'
    lines = [f"{head} في قروب «{m['group_name'] or 'واتساب'}» بدون رد من {span}",
             f'من: {who}' + (f' — مع {files} ملف' if files else ''), f'«{text}»']
    steps = [s for rx, s in NEXT if rx.search(text)]
    if steps:
        lines.append('الخطوة التالية: ' + steps[0])
    lines.append('ردّوا في القروب، أو اكتب لي ما تريد قوله وأجهزه لك.')
    return '\n'.join(lines)


async def check(now=None, deliver=None, reads_left=3):
    """Alert on important group messages nobody answered. Returns the texts delivered.
    When the request inbox (group_requests) is on, it owns the alerts and this returns nothing."""
    if os.getenv('GROUP_REQUESTS_ENABLED', '0') == '1':
        return []
    from starlette.concurrency import run_in_threadpool
    from app.no_wait import answered_after
    if deliver is None:
        from app.owner_briefing import deliver
    now = now or utcnow()
    sent = []
    done = set()
    for m in await run_in_threadpool(due, now):
        if m['conversation_id'] in done:
            continue
        done.add(m['conversation_id'])
        checked = None
        if reads_left > 0:
            reads_left -= 1
            checked = await answered_after(m['account_id'], m['conversation_id'], m['received_at'])
        if checked:
            await run_in_threadpool(_mark, 'UPDATE whatsapp_group_messages SET answered_at=%s WHERE conversation_id=%s AND important AND answered_at IS NULL AND received_at <= %s',
                                    (now, m['conversation_id'], m['received_at']))
            continue
        def burst_of():
            with db() as c:
                return _thread(c, m)
        text = alert_text(m, await run_in_threadpool(burst_of), now)
        await deliver(text)
        sent.append(text)
        # One alert per group per level: the whole open burst in that group moves up together.
        await run_in_threadpool(_mark, '''UPDATE whatsapp_group_messages SET level=%s WHERE conversation_id=%s AND important
            AND answered_at IS NULL AND level<=%s''', (m['level'] + 1, m['conversation_id'], m['level']))
        try:
            from app import virtual_office
            await run_in_threadpool(virtual_office.log, 'service', 'قروب', m['group_name'] or 'قروب', text.split('\n')[0], text)
        except Exception:
            pass
    return sent


def _mark(sql, params):
    with db() as c:
        c.execute(sql, params)


def list_text(now=None):
    init()
    now = now or utcnow()
    with db() as c:
        rows = c.execute('''SELECT DISTINCT ON (conversation_id, sender) * FROM whatsapp_group_messages WHERE important
            AND answered_at IS NULL AND received_at > %s ORDER BY conversation_id, sender, received_at''',
                         (now - dt.timedelta(days=2),)).fetchall()
    if not rows:
        return 'رسائل القروبات المهمة بلا رد: لا يوجد.'
    out = [f'رسائل القروبات المهمة بلا رد: {len(rows)}']
    for r in rows:
        out.append(f"  • «{r['group_name'] or 'قروب'}» — {r['sender_name'] or '+' + r['sender']} منذ "
                   f"{r['received_at'].astimezone(RIYADH):%H:%M}: «{' '.join(r['text'].split())[:90]}»")
    return '\n'.join(out)
