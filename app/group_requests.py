"""Group request inbox (owner spec, 20 Nov 2026) — built on the group watch (#259) and run entirely on the server.

1. Every request in a WhatsApp group becomes its own card: the message(s) and files of one burst from one sender,
   the department that owns it (HS code / approvals → فيصل, …) and a named human backup, when it arrived and the last
   action. A greeting, small talk or an answer to another request never closes it; a team reply that quotes one of its
   messages closes that request only (an unquoted real answer closes it only when it is the group's single open request).
2. If nobody confirmed the request within 15 minutes (working hours), the backup is alerted. Every channel attempt is
   recorded with its state: «attempted» (sending), «sent» (provider accepted), «delivered» (WhatsApp delivery receipt),
   «failed», «uncertain». WhatsApp failed / not delivered in 5 minutes → e-mail. Both failed → the request stays in the
   urgent list and is retried with back-off, never re-sending a channel that already went out. If group intake itself
   stops (no successful read for 20 minutes) the owner is told by e-mail, and the page shows the last sync time.
   Nothing is ever sent to the customer or posted in the group from here.

GROUP_REQUESTS_ENABLED=1 turns it on (and replaces the simple group-watch alerts).
"""
import datetime as dt
import json
import os
import re

from app.storage import db, utcnow

RIYADH = dt.timezone(dt.timedelta(hours=3))
ACK_MINUTES = 15
DELIVERY_WAIT_MINUTES = 5
BURST_MINUTES = 15
INTAKE_STALE_MINUTES = 20
RETRY_MINUTES = (10, 30, 60, 120)
_READY = False

ROUTES = (  # (topic, regex, department key)
    ('clearance', re.compile(r'hs ?code|approval|license|licence|saber|sfda|permit|بند|تعرفة|سابر|موافقة|موافقات|ترخيص|اشتراطات|فسح|بيان', re.I), 'clearance'),
    ('containers', re.compile(r'container|demurrage|detention|eta|arrival|vessel|\bbl\b|b/l|حاوية|الحاويات|وصول|الباخرة|غرامة|بوليصة', re.I), 'containers'),
    ('transport', re.compile(r'truck|transport|trailer|delivery|flatbed|نقل|شاحنة|سطحة|توصيل|سواق|تريلا', re.I), 'transport'),
    ('finance', re.compile(r'invoice|payment|statement|فاتورة|دفع|سداد|كشف|حساب', re.I), 'finance'),
    ('sales', re.compile(r'quote|quotation|rate|price|cost|سعر|عرض', re.I), 'sales'),
)


def enabled():
    return os.getenv('GROUP_REQUESTS_ENABLED', '0') == '1'


def init():
    global _READY
    if _READY:
        return
    from app import group_watch
    group_watch.init()
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS group_requests(id BIGSERIAL PRIMARY KEY, account_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL, group_name TEXT NOT NULL DEFAULT '', sender TEXT NOT NULL DEFAULT '',
            sender_name TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '', files TEXT NOT NULL DEFAULT '[]',
            topic TEXT NOT NULL DEFAULT 'general', owner_key TEXT NOT NULL DEFAULT 'service',
            status TEXT NOT NULL DEFAULT 'open', received_at TIMESTAMPTZ NOT NULL, last_message_at TIMESTAMPTZ NOT NULL,
            ack_at TIMESTAMPTZ, ack_by TEXT, closed_at TIMESTAMPTZ, closed_by TEXT,
            last_action TEXT NOT NULL DEFAULT '', last_action_at TIMESTAMPTZ, urgent BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS group_requests_open ON group_requests(status, conversation_id)')
        c.execute('''CREATE TABLE IF NOT EXISTS group_request_messages(message_id TEXT PRIMARY KEY, request_id BIGINT,
            kind TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS group_request_alerts(id BIGSERIAL PRIMARY KEY, request_id BIGINT NOT NULL,
            channel TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1, recipient TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL, provider_id TEXT, conversation_id TEXT, error TEXT NOT NULL DEFAULT '',
            attempted_at TIMESTAMPTZ NOT NULL, sent_at TIMESTAMPTZ, delivered_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE(request_id, channel, attempt))''')
        c.execute('''CREATE TABLE IF NOT EXISTS group_request_cursor(key TEXT PRIMARY KEY, last_id BIGINT NOT NULL DEFAULT 0,
            alerted_at TIMESTAMPTZ)''')
    _READY = True


# ---------------------------------------------------------------- people

def backup_for(owner_key):
    """The named human who is alerted for this department: GROUP_REQUESTS_BACKUP = {"clearance": {"name": "…",
    "phone": "+9665…", "email": "…"}, "*": {...}}; default the owner (WHATSAPP_COMMAND_OWNER)."""
    try:
        table = json.loads(os.getenv('GROUP_REQUESTS_BACKUP', '{}'))
    except ValueError:
        table = {}
    item = table.get(owner_key) or table.get('*') or {}
    return {'name': item.get('name') or 'محمد (المدير)',
            'phone': item.get('phone') or os.getenv('WHATSAPP_COMMAND_OWNER', ''),
            'email': item.get('email') or os.getenv('OWNER_ALERT_EMAIL', 'info@afaqtawiqs.net')}


def owner_label(owner_key):
    try:
        from app.virtual_office import DEPARTMENTS
        d = DEPARTMENTS.get(owner_key) or {}
        return f"{d.get('person', '')} — {d.get('name', '')}".strip(' —') or owner_key
    except Exception:
        return owner_key


def route(text, files):
    blob = ' '.join([text or ''] + list(files or []))
    for topic, rx, key in ROUTES:
        if rx.search(blob):
            return topic, key
    return 'general', 'service'


def working(now):
    """GROUP_REQUESTS_HOURS = "8-22" (Riyadh); default all day (Afaq works 24/7)."""
    raw = os.getenv('GROUP_REQUESTS_HOURS', '0-24')
    try:
        start, end = (int(x) for x in raw.split('-', 1))
    except ValueError:
        start, end = 0, 24
    h = now.astimezone(RIYADH).hour
    return start <= h < end if start <= end else (h >= start or h < end)


# ---------------------------------------------------------------- 1. requests from group messages

def _files(row):
    try:
        return [str(x) for x in json.loads(row.get('files') or '[]')]
    except ValueError:
        return []


def _act(c, rid, text, at):
    c.execute('UPDATE group_requests SET last_action=%s, last_action_at=%s WHERE id=%s', (text[:300], at, rid))


def build(now=None):
    """Turn new group messages into request cards / closures. Returns counts."""
    from app import group_watch
    init()
    out = {'new': 0, 'joined': 0, 'closed': 0, 'other': 0}
    with db() as c:
        cur = c.execute("SELECT last_id FROM group_request_cursor WHERE key='messages'").fetchone()
        last = cur['last_id'] if cur else 0
        rows = c.execute('SELECT * FROM whatsapp_group_messages WHERE id > %s ORDER BY id LIMIT 500', (last,)).fetchall()
        for m in rows:
            last = m['id']
            if c.execute('SELECT 1 FROM group_request_messages WHERE message_id=%s', (m['message_id'],)).fetchone():
                continue
            files = _files(m)
            if not m['team'] and m['direction'] == 'incoming':
                if not m['important']:
                    c.execute("INSERT INTO group_request_messages(message_id,request_id,kind,created_at) VALUES(%s,NULL,'other',%s)",
                              (m['message_id'], utcnow()))
                    out['other'] += 1
                    continue
                topic, key = route(m['text'], files)
                quoted = c.execute('SELECT request_id FROM group_request_messages WHERE message_id=%s', (m['quoted_id'],)).fetchone() \
                    if m.get('quoted_id') else None
                same = c.execute('''SELECT * FROM group_requests WHERE conversation_id=%s AND sender=%s AND status='open'
                    AND ack_at IS NULL AND last_message_at >= %s ORDER BY id DESC LIMIT 1''',
                                 (m['conversation_id'], m['sender'], m['received_at'] - dt.timedelta(minutes=BURST_MINUTES))).fetchone()
                join = None
                if quoted and quoted['request_id']:
                    join = c.execute("SELECT * FROM group_requests WHERE id=%s AND status='open'", (quoted['request_id'],)).fetchone()
                elif same:
                    # One burst = one request (files, then the question). A second question on another topic is a new request.
                    split = (not files and _question_like(same['text']) and _question_like(m['text'])
                             and topic != 'general' and topic != same['topic'])
                    join = None if split else same
                if join:
                    merged = (join['text'] + '\n' + m['text']).strip() if m['text'] else join['text']
                    allfiles = _files(join) + files
                    t2, k2 = (topic, key) if join['topic'] == 'general' else (join['topic'], join['owner_key'])
                    c.execute('''UPDATE group_requests SET text=%s, files=%s, topic=%s, owner_key=%s, last_message_at=%s WHERE id=%s''',
                              (merged[:4000], json.dumps(allfiles[:20], ensure_ascii=False), t2, k2, m['received_at'], join['id']))
                    c.execute("INSERT INTO group_request_messages(message_id,request_id,kind,created_at) VALUES(%s,%s,'request',%s)",
                              (m['message_id'], join['id'], utcnow()))
                    out['joined'] += 1
                else:
                    rid = c.execute('''INSERT INTO group_requests(account_id,conversation_id,group_name,sender,sender_name,text,files,
                        topic,owner_key,received_at,last_message_at,last_action,last_action_at,created_at)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                                    (m['account_id'], m['conversation_id'], m['group_name'], m['sender'], m['sender_name'],
                                     m['text'][:4000], json.dumps(files, ensure_ascii=False), topic, key, m['received_at'],
                                     m['received_at'], 'وصل الطلب في القروب', m['received_at'], utcnow())).fetchone()['id']
                    c.execute("INSERT INTO group_request_messages(message_id,request_id,kind,created_at) VALUES(%s,%s,'request',%s)",
                              (m['message_id'], rid, utcnow()))
                    out['new'] += 1
                continue
            # A message from Afaq (team member or the business number).
            target = None
            if m.get('quoted_id'):
                link = c.execute('SELECT request_id FROM group_request_messages WHERE message_id=%s', (m['quoted_id'],)).fetchone()
                if link and link['request_id']:
                    target = c.execute("SELECT * FROM group_requests WHERE id=%s AND status='open'", (link['request_id'],)).fetchone()
            small = (not m['text'].strip()) or bool(group_watch.SMALL.match(m['text'])) or _greeting(m['text'])
            if not target and not small:
                opened = c.execute('''SELECT * FROM group_requests WHERE conversation_id=%s AND status='open' AND received_at <= %s''',
                                   (m['conversation_id'], m['received_at'])).fetchall()
                if len(opened) == 1:
                    target = opened[0]
            who = m['sender_name'] or ('+' + m['sender'] if m['sender'] else 'رقم الشركة')
            if target and (not small or m.get('quoted_id')):
                c.execute('''UPDATE group_requests SET status='closed', closed_at=%s, closed_by=%s,
                    ack_at=COALESCE(ack_at,%s), ack_by=COALESCE(ack_by,%s), urgent=FALSE WHERE id=%s''',
                          (m['received_at'], who, m['received_at'], who, target['id']))
                _act(c, target['id'], f'ردّ {who} في القروب: «{" ".join(m["text"].split())[:120]}»', m['received_at'])
                c.execute("INSERT INTO group_request_messages(message_id,request_id,kind,created_at) VALUES(%s,%s,'answer',%s)",
                          (m['message_id'], target['id'], utcnow()))
                out['closed'] += 1
            else:
                c.execute("INSERT INTO group_request_messages(message_id,request_id,kind,created_at) VALUES(%s,NULL,'team_other',%s)",
                          (m['message_id'], utcnow()))
        c.execute('''INSERT INTO group_request_cursor(key,last_id) VALUES('messages',%s)
            ON CONFLICT(key) DO UPDATE SET last_id=EXCLUDED.last_id''', (last,))
    return out


GREET = re.compile(r'^\s*(السلام عليكم|سلام|صباح الخير|مساء الخير|هلا|مرحبا|اهلا|أهلا|good morning|good evening|hi|hello|'
                   r'thanks?|thank you|جزاك الله خير|الله يعطيك العافية)[\s!.،,]*\S{0,20}\s*$', re.I)


def _greeting(text):
    return bool(GREET.match(text or ''))


def _question_like(text):
    from app.group_watch import ASK
    return bool(ASK.search(text or ''))


# ---------------------------------------------------------------- manual actions (office page / WhatsApp)

def acknowledge(rid, who):
    init()
    with db() as c:
        row = c.execute('''UPDATE group_requests SET ack_at=COALESCE(ack_at,NOW()), ack_by=COALESCE(ack_by,%s), urgent=FALSE
            WHERE id=%s AND status='open' RETURNING id''', (who, rid)).fetchone()
        if row:
            _act(c, rid, f'تأكد الاستلام: {who}', utcnow())
    return bool(row)


def close(rid, who, note=''):
    init()
    with db() as c:
        row = c.execute('''UPDATE group_requests SET status='closed', closed_at=NOW(), closed_by=%s, urgent=FALSE,
            ack_at=COALESCE(ack_at,NOW()), ack_by=COALESCE(ack_by,%s) WHERE id=%s AND status='open' RETURNING id''',
                        (who, who, rid)).fetchone()
        if row:
            _act(c, rid, f'أُقفل بواسطة {who}' + (f': {note}' if note else ''), utcnow())
    return bool(row)


# ---------------------------------------------------------------- 2. alerts with delivery states

def _forced(channel):
    """Test hook for the staging run: GROUP_REQUESTS_FORCE_FAIL=whatsapp,email simulates a channel failure."""
    return channel in {x.strip() for x in os.getenv('GROUP_REQUESTS_FORCE_FAIL', '').split(',') if x.strip()}


def alert_text(r, now):
    minutes = int((now - r['received_at']).total_seconds() // 60)
    files = _files(r)
    who = r['sender_name'] or ('+' + r['sender'] if r['sender'] else 'عضو')
    lines = [f"📥 طلب #{r['id']} في قروب «{r['group_name'] or 'واتساب'}» لم يُؤكَّد استلامه منذ {minutes} دقيقة",
             f'من: {who}' + (f" — {len(files)} ملف: {'، '.join(files[:4])}" if files else ''),
             f"«{' '.join((r['text'] or '').split())[:400]}»",
             f"المسؤول: {owner_label(r['owner_key'])} — وأنت البديل.",
             f"للتأكيد اكتب: استلمت {r['id']} — وعند الرد في القروب اقتبس رسالة الطلب ليُقفل تلقائيًا."]
    return '\n'.join(lines)


def _attempt(c, rid, channel, recipient, now):
    """Reserve the next attempt row (state 'attempted') before sending; returns its id or None if one is still open."""
    busy = c.execute('''SELECT 1 FROM group_request_alerts WHERE request_id=%s AND channel=%s
        AND state IN ('attempted','sent','delivered','uncertain')''', (rid, channel)).fetchone()
    if busy:
        return None
    n = c.execute('SELECT COALESCE(MAX(attempt),0)+1 n FROM group_request_alerts WHERE request_id=%s AND channel=%s',
                  (rid, channel)).fetchone()['n']
    return c.execute('''INSERT INTO group_request_alerts(request_id,channel,attempt,recipient,state,attempted_at,updated_at)
        VALUES(%s,%s,%s,%s,'attempted',%s,%s) ON CONFLICT DO NOTHING RETURNING id''',
                     (rid, channel, n, recipient, now, now)).fetchone()


def _set(aid, **f):
    f['updated_at'] = utcnow()
    with db() as c:
        c.execute('UPDATE group_request_alerts SET ' + ', '.join(k + '=%s' for k in f) + ' WHERE id=%s', (*f.values(), aid))
        row = c.execute('SELECT request_id, channel, attempt, state, attempted_at, sent_at, delivered_at, error FROM group_request_alerts WHERE id=%s',
                        (aid,)).fetchone()
    if row:
        print('GROUP_REQUESTS_ALERT_STATE', {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in row.items()}, flush=True)


async def send_whatsapp(phone, text):
    from app import zernio_whatsapp as z
    if _forced('whatsapp'):
        raise z.WhatsAppBlocked('فشل مُحاكى (GROUP_REQUESTS_FORCE_FAIL)')
    result = await z.send(phone, text)
    msg = (result.get('messages') or [{}])[0]
    return msg.get('id'), result.get('conversation_id')


def send_email(to, subject, text):
    if _forced('email'):
        raise RuntimeError('فشل مُحاكى (GROUP_REQUESTS_FORCE_FAIL)')
    from app.prospect_autopilot import system_user
    from app.spacemail import send
    uid = system_user()
    if not uid:
        raise RuntimeError('لا يوجد بريد رسمي متصل')
    return send(uid, to, subject, text)


async def delivery_state(conversation_id, provider_id):
    """'delivered' / 'read' / 'failed' / 'sent' / None from the provider's message list."""
    from urllib.parse import quote
    from app import zernio_whatsapp as z
    async with z.client() as c:
        data = await z.read(c, '/inbox/conversations/' + quote(str(conversation_id), safe='') + '/messages',
                            {'accountId': z.account_id(), 'sortOrder': 'desc', 'limit': 30})
    for m in (data.get('messages') or []) if isinstance(data, dict) else []:
        if isinstance(m, dict) and provider_id in (m.get('id'), m.get('platformMessageId'), m.get('messageId')):
            state = str(m.get('status') or m.get('deliveryStatus') or m.get('state') or '').lower()
            if os.getenv('GROUP_WATCH_DEBUG_KEYS') == '1':
                print('GROUP_REQUESTS_STATUS', provider_id[-12:], state, sorted(m.keys())[:30], flush=True)
            return state or 'sent'
    return None


def due_alerts(now):
    init()
    with db() as c:
        return c.execute('''SELECT r.* FROM group_requests r WHERE r.status='open' AND r.ack_at IS NULL
            AND r.received_at <= %s AND r.received_at > %s ORDER BY r.received_at LIMIT 20''',
                         (now - dt.timedelta(minutes=ACK_MINUTES), now - dt.timedelta(days=3))).fetchall()


async def alerts(now=None):
    """Run the delivery chain for every unconfirmed request. Returns a list of (request id, channel, state)."""
    from starlette.concurrency import run_in_threadpool
    now = now or utcnow()
    done = []
    if not working(now):
        return done
    await run_in_threadpool(_stale_attempts, now)
    for r in await run_in_threadpool(due_alerts, now):
        b = backup_for(r['owner_key'])
        text = alert_text(r, now)

        def rows():
            with db() as c:
                return c.execute('SELECT * FROM group_request_alerts WHERE request_id=%s ORDER BY id', (r['id'],)).fetchall()
        history = await run_in_threadpool(rows)
        wa = [a for a in history if a['channel'] == 'whatsapp']
        em = [a for a in history if a['channel'] == 'email']
        # a) WhatsApp delivery receipt for an alert already sent
        for a in wa:
            if a['state'] == 'sent' and a['provider_id'] and a['conversation_id']:
                try:
                    st = await delivery_state(a['conversation_id'], a['provider_id'])
                except Exception as exc:
                    st = None
                    print('GROUP_REQUESTS_RECEIPT', type(exc).__name__, str(exc)[:120], flush=True)
                if st in ('delivered', 'read', 'played'):
                    await run_in_threadpool(lambda: _set(a['id'], state='delivered', delivered_at=now))
                    await run_in_threadpool(lambda: _note(r['id'], f"وصل تنبيه واتساب إلى {b['name']} ({now.astimezone(RIYADH):%H:%M})", now))
                    a['state'] = 'delivered'
                    done.append((r['id'], 'whatsapp', 'delivered'))
                elif st == 'failed':
                    await run_in_threadpool(lambda: _set(a['id'], state='failed', error='provider: failed'))
                    a['state'] = 'failed'
        # b) first WhatsApp attempt, or a retry when every earlier attempt failed and the back-off passed
        if _retry_ok(wa, now):
            def reserve():
                with db() as c:
                    return _attempt(c, r['id'], 'whatsapp', b['phone'], now)
            slot = await run_in_threadpool(reserve)
            if slot:
                try:
                    if not b['phone']:
                        raise RuntimeError('لا يوجد رقم واتساب للبديل')
                    pid, conv = await send_whatsapp(b['phone'], text)
                    await run_in_threadpool(lambda: _set(slot['id'], state='sent', provider_id=pid, conversation_id=conv, sent_at=now))
                    await run_in_threadpool(lambda: _note(r['id'], f"حاولنا تنبيه {b['name']} على واتساب ({now.astimezone(RIYADH):%H:%M}) — بانتظار إشعار الوصول", now))
                    done.append((r['id'], 'whatsapp', 'sent'))
                    wa.append({'state': 'sent', 'sent_at': now, 'attempted_at': now})
                except Exception as exc:
                    from app import zernio_whatsapp as z
                    state = 'uncertain' if isinstance(exc, getattr(z, 'WhatsAppSendUncertain', ())) else 'failed'
                    await run_in_threadpool(lambda: _set(slot['id'], state=state, error=(type(exc).__name__ + ': ' + str(exc))[:300]))
                    await run_in_threadpool(lambda: _note(r['id'], f"فشل تنبيه واتساب ({state}): {str(exc)[:80]}", now))
                    done.append((r['id'], 'whatsapp', state))
                    wa.append({'state': state, 'attempted_at': now})
        # c) e-mail when WhatsApp failed / uncertain / not delivered within DELIVERY_WAIT_MINUTES
        wa_ok = any(a['state'] == 'delivered' for a in wa)
        wa_late = any(a['state'] == 'sent' and (a.get('sent_at') or now) <= now - dt.timedelta(minutes=DELIVERY_WAIT_MINUTES) for a in wa)
        wa_bad = wa and all(a['state'] in ('failed', 'uncertain') for a in wa)
        if not wa_ok and (wa_bad or wa_late) and _retry_ok(em, now):
            def reserve_mail():
                with db() as c:
                    return _attempt(c, r['id'], 'email', b['email'], now)
            slot = await run_in_threadpool(reserve_mail)
            if slot:
                try:
                    mid = await run_in_threadpool(send_email, b['email'], f"طلب #{r['id']} في قروب {r['group_name']} بلا تأكيد", text)
                    await run_in_threadpool(lambda: _set(slot['id'], state='sent', provider_id=str(mid or '')[:200], sent_at=now))
                    await run_in_threadpool(lambda: _note(r['id'], f"أُرسل تنبيه بريد إلى {b['email']} ({now.astimezone(RIYADH):%H:%M}) — قبله خادم البريد", now))
                    done.append((r['id'], 'email', 'sent'))
                    em.append({'state': 'sent'})
                except Exception as exc:
                    await run_in_threadpool(lambda: _set(slot['id'], state='failed', error=(type(exc).__name__ + ': ' + str(exc))[:300]))
                    await run_in_threadpool(lambda: _note(r['id'], f"فشل تنبيه البريد: {str(exc)[:80]}", now))
                    done.append((r['id'], 'email', 'failed'))
                    em.append({'state': 'failed', 'attempted_at': now})
        # d) both failed → urgent list (retried later with back-off, never duplicating a channel that went out)
        failed_all = (wa and all(a['state'] in ('failed', 'uncertain') for a in wa)
                      and em and all(a['state'] == 'failed' for a in em))
        await run_in_threadpool(_urgent, r['id'], bool(failed_all), now)
    return done


def _stale_attempts(now):
    """A send interrupted by a restart: it may or may not have gone out → 'uncertain' (never re-sent on that channel)."""
    with db() as c:
        c.execute('''UPDATE group_request_alerts SET state='uncertain', error='انقطع أثناء الإرسال (إعادة تشغيل)', updated_at=%s
            WHERE state='attempted' AND attempted_at < %s''', (now, now - dt.timedelta(minutes=10)))


def _retry_ok(attempts, now):
    """No attempt yet → go. Anything that may have gone out (attempted / sent / delivered / uncertain) → never again.
    Only failed attempts are retried, after RETRY_MINUTES[n] from the last one."""
    if not attempts:
        return True
    if any(a['state'] != 'failed' for a in attempts):
        return False
    wait = RETRY_MINUTES[min(len(attempts) - 1, len(RETRY_MINUTES) - 1)]
    last = max(a.get('attempted_at') or now for a in attempts)
    return last <= now - dt.timedelta(minutes=wait)


def _note(rid, text, at):
    with db() as c:
        _act(c, rid, text, at)


def _urgent(rid, flag, now):
    with db() as c:
        was = c.execute('SELECT urgent FROM group_requests WHERE id=%s', (rid,)).fetchone()
        if was and bool(was['urgent']) != flag:
            c.execute('UPDATE group_requests SET urgent=%s WHERE id=%s', (flag, rid))
            if flag:
                _act(c, rid, 'فشل التنبيه عبر واتساب والبريد — في القائمة العاجلة، سأعيد المحاولة', now)


# ---------------------------------------------------------------- intake health

def health(now=None):
    from app import group_watch
    group_watch.init()
    now = now or utcnow()
    with db() as c:
        rows = {r['key']: r for r in c.execute('SELECT * FROM whatsapp_group_health').fetchall()}
    last = max([r['ok_at'] for r in rows.values() if r.get('ok_at')], default=None)
    errors = [r for r in rows.values() if r.get('error_at') and (not r.get('ok_at') or r['error_at'] > r['ok_at'])]
    stale = last is None or last < now - dt.timedelta(minutes=INTAKE_STALE_MINUTES)
    return {'last_ok': last, 'stale': stale, 'error': errors[0]['error'] if errors else ''}


def health_alert(now=None, mailer=None):
    """Group intake stopped: tell the owner by e-mail (independent of WhatsApp), once per outage."""
    init()
    now = now or utcnow()
    h = health(now)
    with db() as c:
        cur = c.execute("SELECT alerted_at FROM group_request_cursor WHERE key='intake'").fetchone()
        if not h['stale']:
            if cur and cur['alerted_at']:
                c.execute("UPDATE group_request_cursor SET alerted_at=NULL WHERE key='intake'")
            return None
        if cur and cur['alerted_at']:
            return None
    since = h['last_ok'].astimezone(RIYADH).strftime('%d/%m %H:%M') if h['last_ok'] else 'لم تنجح أي قراءة بعد'
    text = (f'⚠️ استقبال رسائل قروبات واتساب متوقف. آخر مزامنة ناجحة: {since}.\n'
            + (f"آخر خطأ: {h['error']}\n" if h['error'] else '')
            + 'الطلبات الجديدة في القروبات لن تظهر حتى يعود الاستقبال. افتح صفحة طلبات القروبات للتفاصيل.')
    try:
        (mailer or send_email)(os.getenv('OWNER_ALERT_EMAIL', 'info@afaqtawiqs.net'), 'تنبيه: توقف استقبال قروبات واتساب', text)
        sent = True
    except Exception as exc:
        print('GROUP_REQUESTS_INTAKE_ALERT', type(exc).__name__, str(exc)[:160], flush=True)
        sent = False
    if sent:
        with db() as c:
            c.execute('''INSERT INTO group_request_cursor(key,last_id,alerted_at) VALUES('intake',0,%s)
                ON CONFLICT(key) DO UPDATE SET alerted_at=EXCLUDED.alerted_at''', (now,))
    return text if sent else None


# ---------------------------------------------------------------- the worker

async def tick(now=None):
    from starlette.concurrency import run_in_threadpool
    from app import group_watch
    if not enabled():
        return {}
    now = now or utcnow()
    await run_in_threadpool(group_watch.flush)
    read = await group_watch.poll(now)
    built = await run_in_threadpool(build, now)
    sent = await alerts(now)
    await run_in_threadpool(health_alert, now)
    if os.getenv('GROUP_WATCH_DEBUG_KEYS') == '1' or sent or any(built.values()):
        h = await run_in_threadpool(health, now)
        print('GROUP_REQUESTS_TICK_OK', {'new_messages': read, 'built': built, 'alerts': sent,
                                         'last_sync': h['last_ok'].isoformat() if h['last_ok'] else None}, flush=True)
    return {'built': built, 'alerts': sent}


def register_worker(app):
    import asyncio

    async def loop():
        await asyncio.sleep(45)
        while True:
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('GROUP_REQUESTS_TICK', type(exc).__name__, str(exc)[:200], flush=True)
            await asyncio.sleep(int(os.getenv('GROUP_REQUESTS_INTERVAL', '60')))

    @app.on_event('startup')
    async def start():
        if enabled():
            app.state.group_requests_worker = asyncio.create_task(loop())


# ---------------------------------------------------------------- views

STATUS_AR = {'open': 'مفتوح', 'closed': 'مقفل'}


def cards(limit=60):
    init()
    with db() as c:
        reqs = c.execute('''SELECT * FROM group_requests ORDER BY (status='open') DESC, urgent DESC, received_at DESC LIMIT %s''',
                         (limit,)).fetchall()
        ids = [r['id'] for r in reqs]
        al = c.execute('SELECT * FROM group_request_alerts WHERE request_id = ANY(%s) ORDER BY id', (ids,)).fetchall() if ids else []
    by = {}
    for a in al:
        by.setdefault(a['request_id'], []).append(a)
    out = []
    for r in reqs:
        b = backup_for(r['owner_key'])
        out.append({'id': r['id'], 'group': r['group_name'], 'from': r['sender_name'] or ('+' + r['sender'] if r['sender'] else ''),
                    'text': r['text'], 'files': _files(r), 'owner': owner_label(r['owner_key']), 'backup': b['name'],
                    'status': r['status'], 'urgent': r['urgent'], 'received_at': r['received_at'],
                    'ack': (r['ack_by'], r['ack_at']), 'closed': (r['closed_by'], r['closed_at']),
                    'last_action': r['last_action'], 'last_action_at': r['last_action_at'],
                    'alerts': [(a['channel'], a['attempt'], a['state'], a['attempted_at'], a['sent_at'], a['delivered_at'], a['error'])
                               for a in by.get(r['id'], [])]})
    return out


def list_text():
    rows = [c for c in cards(40) if c['status'] == 'open']
    if not rows:
        return '📥 لا توجد طلبات قروبات مفتوحة.'
    out = [f'📥 طلبات القروبات المفتوحة: {len(rows)}']
    for c in rows:
        out.append(f"{'🚨 ' if c['urgent'] else ''}#{c['id']} «{c['group']}» — {c['from']} — {c['received_at'].astimezone(RIYADH):%d/%m %H:%M}"
                   f" — {c['owner']}\n   «{' '.join(c['text'].split())[:120]}»\n   آخر إجراء: {c['last_action']}")
    return '\n'.join(out)


def page_html(rows, h, action_url, extra_fields=''):
    """Cards page (office). action_url(id, action) → form action."""
    import html as _h
    e = lambda v: _h.escape(str(v if v is not None else ''))
    t = lambda v: v.astimezone(RIYADH).strftime('%d/%m %H:%M') if v else '—'
    state_ar = {'attempted': 'حاولنا الإرسال', 'sent': 'قبله المزود — بانتظار الوصول', 'delivered': 'وصل ✅',
                'failed': 'فشل ❌', 'uncertain': 'غير مؤكد ⚠️'}
    chan_ar = {'whatsapp': 'واتساب', 'email': 'بريد'}
    sync = ('🟢 الاستقبال يعمل' if not h['stale'] else '🔴 الاستقبال متوقف') + ' — آخر مزامنة: ' + t(h['last_ok']) \
        + (f" — آخر خطأ: {e(h['error'])}" if h['error'] else '')
    cards_html = []
    for c in rows:
        cls = 'urgent' if c['urgent'] else ('closed' if c['status'] == 'closed' else 'open')
        alerts = ''.join(f"<li>{chan_ar.get(a[0], a[0])} #{a[1]}: {state_ar.get(a[2], a[2])} — محاولة {t(a[3])}"
                         + (f" · قُبل {t(a[4])}" if a[4] else '') + (f" · وصل {t(a[5])}" if a[5] else '')
                         + (f" · {e(a[6])}" if a[6] and a[2] in ('failed', 'uncertain') else '') + '</li>' for a in c['alerts'])
        buttons = '' if c['status'] == 'closed' else ''.join(
            f"<form method=post action='{action_url(c['id'], act)}'>{extra_fields}<button>{label}</button></form>"
            for act, label in (('ack', '✋ استلمت'), ('close', '✅ تم الرد / إقفال')) if not (act == 'ack' and c['ack'][1]))
        cards_html.append(
            f"<div class='card {cls}'><div class=top><b>#{c['id']}</b> «{e(c['group'])}» — {e(c['from'])}"
            f"<span class=st>{'🚨 عاجل' if c['urgent'] else ('مقفل' if c['status'] == 'closed' else 'مفتوح')}</span></div>"
            f"<p class=txt>{e(c['text'])}</p>"
            + (f"<p class=files>📎 {' · '.join(e(f) for f in c['files'])}</p>" if c['files'] else '')
            + f"<div class=meta>المسؤول: <b>{e(c['owner'])}</b> · البديل: {e(c['backup'])} · وصل: {t(c['received_at'])}"
            + (f" · استلمه: {e(c['ack'][0])} {t(c['ack'][1])}" if c['ack'][1] else '')
            + (f" · أقفله: {e(c['closed'][0])} {t(c['closed'][1])}" if c['closed'][1] else '') + '</div>'
            + f"<div class=meta>آخر إجراء: {e(c['last_action'])} ({t(c['last_action_at'])})</div>"
            + (f"<ul class=alerts>{alerts}</ul>" if alerts else '') + f"<div class=btns>{buttons}</div></div>")
    open_n = sum(1 for c in rows if c['status'] == 'open')
    urgent_n = sum(1 for c in rows if c['urgent'])
    return ("<!doctype html><html lang=ar dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>طلبات القروبات</title><style>body{font-family:system-ui,Tahoma;background:#0b1620;color:#e6eef4;margin:0;padding:14px}"
            "h1{font-size:19px;margin:4px 0 8px}.sync{background:#10222f;border-radius:10px;padding:8px 10px;margin-bottom:10px;font-size:13px}"
            ".card{background:#10222f;border-radius:12px;padding:10px 12px;margin:10px 0;border-right:4px solid #38bdf8}"
            ".card.urgent{border-color:#ef4444;background:#2a1215}.card.closed{opacity:.6;border-color:#22c55e}"
            ".top{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.st{margin-inline-start:auto;font-size:12px;background:#17344a;border-radius:8px;padding:2px 8px}"
            ".txt{white-space:pre-wrap;margin:6px 0}.files{color:#93c5fd;font-size:13px}.meta{color:#9fb3c2;font-size:12.5px;margin:3px 0}"
            ".alerts{font-size:12.5px;color:#cbd5e1;margin:6px 0;padding-inline-start:18px}.btns{display:flex;gap:8px}"
            "button{background:#16a34a;color:#fff;border:0;border-radius:8px;padding:7px 12px;font-size:14px;cursor:pointer}"
            "a{color:#7dd3fc}</style></head><body>"
            f"<h1>📥 طلبات القروبات — مفتوحة {open_n}" + (f" · 🚨 عاجلة {urgent_n}" if urgent_n else '') + "</h1>"
            f"<div class=sync>{sync}</div>" + (''.join(cards_html) or '<p>لا توجد طلبات بعد.</p>') + "</body></html>")
