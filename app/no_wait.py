"""«لا أحد ينتظر» — owner request (18 Nov 2026): three watchers over the customer WhatsApp conversations.

1. Promises: when the agent or an employee tells a customer «أرجع لك بالسعر خلال ساعة» / «سيتواصل معك فريقنا»,
   the promise becomes a task with a due time. Ten minutes before it falls due — and again 30 minutes after it if
   nothing was sent to the customer — the manager gets an alert.
2. Waiting customers: a conversation handed to staff (paused, or hand-off suggested), or a customer message that got
   no reply at all, and nobody answered for 20 minutes → alert; still unanswered after 60 minutes → escalation.
3. Upset customers: anger / complaint words, or the same customer sending several messages in a row with irritation
   → immediate alert to the manager with a summary, a hand-off record in the inbox, and existing-customer offers
   paused for that number for 7 days.

Builds only on existing tables (agent jobs, takeover receipts, inbox drafts, hand-off summaries). Before a promise or
waiting alert it reads that ONE conversation from the provider to make sure nobody already answered. Nothing is ever
sent to a customer from here. Alerts are held during the night (23:00–07:00 Riyadh). NO_WAIT_ENABLED=0 turns it off.
"""
import asyncio
import datetime as dt
import os
import re
from urllib.parse import quote

from app.storage import db, utcnow

RIYADH = dt.timezone(dt.timedelta(hours=3))
WAIT_FIRST, WAIT_ESCALATE = 20, 60          # minutes
PROMISE_REMIND, PROMISE_LATE = 10, 30       # minutes before / after the due time
UPSET_COOLDOWN_HOURS, HOLD_DAYS = 6, 7
QUIET = (23, 7)
LOOKBACK = dt.timedelta(minutes=15)         # overlap between scans; rows are de-duplicated by key
MAX_PROVIDER_READS = 6                      # per tick, to stay far below the WhatsApp provider limit
_READY = False


def enabled():
    return os.getenv('NO_WAIT_ENABLED', '1') != '0'


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS no_wait_cursors(name TEXT PRIMARY KEY, at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS customer_promises(id BIGSERIAL PRIMARY KEY, account_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL, sender TEXT NOT NULL, source TEXT NOT NULL, source_ref TEXT NOT NULL,
            said_by TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, said_at TIMESTAMPTZ NOT NULL, due_at TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL DEFAULT 'open', reminded_at TIMESTAMPTZ, escalated_at TIMESTAMPTZ,
            closed_by TEXT, closed_at TIMESTAMPTZ, UNIQUE(source, source_ref))''')
        c.execute('CREATE INDEX IF NOT EXISTS customer_promises_open ON customer_promises(status, due_at)')
        c.execute('''CREATE TABLE IF NOT EXISTS customer_wait_alerts(account_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
            since TIMESTAMPTZ NOT NULL, level INTEGER NOT NULL, outcome TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(account_id, conversation_id, since, level))''')
        c.execute('''CREATE TABLE IF NOT EXISTS customer_upset_events(id BIGSERIAL PRIMARY KEY, account_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL, sender TEXT NOT NULL, source_ref TEXT NOT NULL UNIQUE, text TEXT NOT NULL,
            reasons TEXT NOT NULL, alerted_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS customer_marketing_holds(phone TEXT PRIMARY KEY, until TIMESTAMPTZ NOT NULL,
            reason TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')
    _READY = True


# ---------- text helpers ----------

def norm(text):
    text = re.sub(r'[ً-ٰـ]', '', str(text or '')).casefold()
    return re.sub(r'\s+', ' ', text.translate(str.maketrans('أإآىةؤئ', 'ااايهوي'))).strip()


def digits(value):
    d = re.sub(r'\D', '', str(value or ''))
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('05') and len(d) == 10:
        d = '966' + d[1:]
    return d


_COMMIT = re.compile(
    r'(?:ا|ن|ب|بن|س|سا|سن)?(?:رجع|عود|رد) (?:لك|لكم|عليك|عليكم|اليك|اليكم)|راجع(?:ين)? لك|ساعود|سنعود|سارجع|سنرجع'
    r'|(?:ا|ن|بن|سا|سن)(?:بلغك|بلغكم|بشرك|خبرك|خبركم|وافيك|وافيكم|زودك|زودكم)'
    r'|(?:ا|ن|ب|بن|سا|سن)رسل(?:ه|ها)? (?:لك|لكم)|(?:ا|ن|ب|بن)كلمك'
    r'|(?:ا|ن|ب|بن|سا|سن|سي|بي|ي)تواصل (?:معك|معكم)|سيتم (?:التواصل|الرد|ارسال|تزويدك)|(?:ا|ن|ب|بن)عطيك خبر'
    r"|get back to you|will (?:send|call|contact|update|share) (?:you|it)|we'?ll (?:send|call|contact|update)")
_MIN = re.compile(r'(?:خلال|بعد|في غضون|within|in)\s*(\d{1,3})\s*(?:دقيق|دقايق|دقائق|د\b|min)')
_HOURS = re.compile(r'(?:خلال|بعد|في غضون|within|in)\s*(\d{1,2})\s*(?:ساع|hour)')


def promise_due(text, said_at):
    """Due time of a commitment to the customer in this outgoing text, or None when there is none."""
    t = norm(text)
    if not _COMMIT.search(t):
        return None
    local = said_at.astimezone(RIYADH)
    minutes = None
    if m := _MIN.search(t):
        minutes = int(m.group(1))
    elif re.search(r'(?:خلال|بعد|في غضون) ?(?:نص|نصف) ساع|half an hour', t):
        minutes = 30
    elif re.search(r'ساعتين|two hours', t):
        minutes = 120
    elif m := _HOURS.search(t):
        minutes = 60 * int(m.group(1))
    elif re.search(r'(?:خلال|بعد|في غضون) ?(?:ال)?ساع|an hour|one hour', t):
        minutes = 60
    elif re.search(r'لحظات|دقايق|دقائق|شوي|قليل|shortly|few minutes', t):
        minutes = 30
    if minutes is not None:
        return said_at + dt.timedelta(minutes=max(10, min(minutes, 72 * 60)))
    if re.search(r'بكره|بكرا|غدا|الغد|tomorrow', t) or (re.search(r'الصبح|صباحا|الصباح|morning', t) and local.hour >= 6):
        day = local.date() + dt.timedelta(days=1)
        return dt.datetime.combine(day, dt.time(11), RIYADH)
    if re.search(r'الصبح|صباحا|الصباح|morning', t):
        return dt.datetime.combine(local.date(), dt.time(11), RIYADH)
    if re.search(r'اليوم|الليله|المساء|العصر|نهايه الدوام|اخر الدوام|today|tonight|this evening', t):
        end = dt.datetime.combine(local.date(), dt.time(17), RIYADH)
        return end if end - local >= dt.timedelta(hours=2) else said_at + dt.timedelta(hours=2)
    return said_at + dt.timedelta(hours=2)


_STRONG = ('شكوي', 'اشتكي', 'بشتكي', 'ساشتكي', 'راح اشتكي', 'نصب', 'نصابين', 'حرامي', 'احتيال', 'مهزله', 'فضيحه',
           'زفت', 'سيء جدا', 'اسوا', 'قله احترام', 'ما في احترام', 'مافي احترام', 'وزاره التجاره', 'حمايه المستهلك',
           'محامي', 'قضيه', 'رجعوا فلوسي', 'ابي فلوسي', 'ابغي فلوسي', 'استرجاع المبلغ', 'ما راح اتعامل', 'مارح اتعامل',
           'اخر مره اتعامل', 'الغي التعامل', 'complaint', 'scam', 'refund', 'worst', 'lawyer', 'unacceptable')
_MEDIUM = ('تاخرتم', 'متاخرين', 'تاخير', 'وين الرد', 'محد يرد', 'ما احد يرد', 'ماحد يرد', 'ليش ما ترد', 'ليه ما ترد',
           'ليش ما تردون', 'كم مره', 'للمره', 'زعلان', 'مستاء', 'منزعج', 'غير مقبول', 'ما يصير', 'مايصير', 'حرام عليكم',
           'مو معقول', 'مش معقول', 'معقول كذا', 'طولتوا', 'طولتو', 'مماطله', 'تلاعب', 'ما فيه تعامل', 'سيء', 'still waiting',
           'no response', 'disappointed', 'angry', 'terrible')


def upset_reasons(text):
    t = norm(text)
    found = [w for w in _STRONG if w in t]
    level = 'strong' if found else None
    medium = [w for w in _MEDIUM if w in t]
    if re.search(r'[!！]{3,}|[؟?]{3,}', str(text or '')):
        medium.append('علامات تعجب/استفهام متكررة')
    return level, found + medium


# ---------- small db helpers ----------

def _cursor(c, name, now):
    row = c.execute('SELECT at FROM no_wait_cursors WHERE name=%s', (name,)).fetchone()
    return row['at'] - LOOKBACK if row else now - dt.timedelta(hours=2)


def _move(c, name, at):
    c.execute('''INSERT INTO no_wait_cursors(name,at) VALUES(%s,%s)
        ON CONFLICT(name) DO UPDATE SET at=GREATEST(no_wait_cursors.at, EXCLUDED.at)''', (name, at))


def _exists(c, table):
    return bool(c.execute('SELECT to_regclass(%s) t', (table,)).fetchone()['t'])


def _question(payload):
    import json
    try:
        data = payload if isinstance(payload, dict) else json.loads(payload or '{}')
    except ValueError:
        return ''
    return str(data.get('question') or data.get('text') or '').strip()


def _team_numbers():
    out = {digits(os.getenv('WHATSAPP_COMMAND_OWNER', ''))}
    try:
        from app.team import team
        out |= {digits(k) for k in team()}
    except Exception:
        pass
    return {d for d in out if d}


def _staff_name(c, user_id):
    try:
        row = c.execute('SELECT name, email FROM users WHERE id=%s', (user_id,)).fetchone()
        return (row.get('name') or row.get('email') or '') if row else ''
    except Exception:
        return ''


def _local(at):
    return at.astimezone(RIYADH).strftime('%H:%M')


def _quiet(now):
    h = now.astimezone(RIYADH).hour
    return h >= QUIET[0] or h < QUIET[1]


# ---------- 1. collect promises and upset messages ----------

def collect(now=None):
    """Scan new outgoing texts for promises and new incoming texts for irritation. Returns counts."""
    init()
    now = now or utcnow()
    team = _team_numbers()
    out = {'promises': 0, 'upset': 0}
    with db() as c:
        if _exists(c, 'whatsapp_agent_jobs'):
            since = _cursor(c, 'agent_out', now)
            for r in c.execute('''SELECT id, account_id, conversation_id, sender, reply_text, completed_at FROM whatsapp_agent_jobs
                    WHERE status='sent' AND completed_at > %s AND completed_at <= %s ORDER BY completed_at''', (since, now)).fetchall():
                out['promises'] += _promise(c, r['account_id'], r['conversation_id'], r['sender'], 'agent', str(r['id']),
                                            'الوكيل الآلي', r['reply_text'], r['completed_at'], team)
            _move(c, 'agent_out', now)
            since = _cursor(c, 'agent_in', now)
            for r in c.execute('''SELECT id, account_id, conversation_id, sender, payload, created_at FROM whatsapp_agent_jobs
                    WHERE created_at > %s AND created_at <= %s ORDER BY id''', (since, now)).fetchall():
                out['upset'] += _upset(c, r['account_id'], r['conversation_id'], r['sender'], 'job-' + str(r['id']),
                                       _question(r['payload']), r['created_at'], team)
            _move(c, 'agent_in', now)
        if _exists(c, 'whatsapp_inbox_drafts'):
            since = _cursor(c, 'staff_out', now)
            for r in c.execute('''SELECT token, account_id, conversation_id, recipient, body, created_by, updated_at FROM whatsapp_inbox_drafts
                    WHERE state='accepted' AND updated_at > %s AND updated_at <= %s ORDER BY updated_at''', (since, now)).fetchall():
                out['promises'] += _promise(c, r['account_id'], r['conversation_id'], r['recipient'], 'staff', r['token'],
                                            _staff_name(c, r['created_by']) or 'موظف', r['body'], r['updated_at'], team)
            _move(c, 'staff_out', now)
        if _exists(c, 'whatsapp_takeover_receipts'):
            since = _cursor(c, 'held_in', now)
            for r in c.execute('''SELECT id, account_id, conversation_id, sender, body, received_at FROM whatsapp_takeover_receipts
                    WHERE received_at > %s AND received_at <= %s ORDER BY id''', (since, now)).fetchall():
                out['upset'] += _upset(c, r['account_id'], r['conversation_id'], r['sender'], 'held-' + str(r['id']),
                                       r['body'], r['received_at'], team)
            _move(c, 'held_in', now)
    return out


def _promise(c, account, cid, sender, source, ref, said_by, text, said_at, team):
    if not text or digits(sender) in team:
        return 0
    due = promise_due(text, said_at)
    if due is None:
        return 0
    if c.execute('''SELECT 1 FROM customer_promises WHERE account_id=%s AND conversation_id=%s AND status='open'
            AND said_at <= %s LIMIT 1''', (account, cid, said_at)).fetchone():
        return 0  # one open promise per conversation: the earliest one decides
    return c.execute('''INSERT INTO customer_promises(account_id,conversation_id,sender,source,source_ref,said_by,text,said_at,due_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(source,source_ref) DO NOTHING''',
                     (account, cid, sender, source, ref, said_by, str(text)[:600], said_at, due)).rowcount


def _upset(c, account, cid, sender, ref, text, at, team):
    if not text or digits(sender) in team:
        return 0
    level, reasons = upset_reasons(text)
    if not level:
        burst = c.execute('''SELECT COUNT(*) n FROM whatsapp_agent_jobs WHERE account_id=%s AND conversation_id=%s
            AND created_at BETWEEN %s AND %s''', (account, cid, at - dt.timedelta(minutes=15), at)).fetchone()['n'] \
            if _exists(c, 'whatsapp_agent_jobs') else 0
        if not (len(reasons) >= 2 or (reasons and burst >= 3)):
            return 0
        if burst >= 3:
            reasons = reasons + [f'{burst} رسائل خلال 15 دقيقة']
    if c.execute('''SELECT 1 FROM customer_upset_events WHERE account_id=%s AND conversation_id=%s AND created_at > %s LIMIT 1''',
                 (account, cid, at - dt.timedelta(hours=UPSET_COOLDOWN_HOURS))).fetchone():
        return 0
    return c.execute('''INSERT INTO customer_upset_events(account_id,conversation_id,sender,source_ref,text,reasons,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(source_ref) DO NOTHING''',
                     (account, cid, sender, ref, str(text)[:600], '، '.join(reasons[:6]), at)).rowcount


# ---------- provider check: did anybody answer? ----------

async def answered_after(account, cid, since, agent_texts=(), skip_texts=()):
    """True when a message that is not the agent's own automatic reply went to the customer after `since`;
    None when the provider could not be read (the alert then says so)."""
    from app import zernio_whatsapp as z
    try:
        async with z.client() as c:
            data = await z.read(c, '/inbox/conversations/' + quote(str(cid), safe='') + '/messages',
                                {'accountId': account, 'sortOrder': 'desc', 'limit': 30})
    except Exception as exc:
        print('NO_WAIT_READ_FAILED', type(exc).__name__, str(exc)[:120], flush=True)
        return None
    auto = {norm(t)[:200] for t in agent_texts if t} | {norm(t)[:200] for t in skip_texts if t}
    for msg in data.get('messages', []) if isinstance(data, dict) else []:
        if not isinstance(msg, dict) or msg.get('direction') == 'incoming':
            continue
        try:
            at = dt.datetime.fromisoformat(str(msg.get('createdAt')).replace('Z', '+00:00'))
        except ValueError:
            continue
        if at > since and norm(msg.get('message'))[:200] not in auto:
            return True
    return False


def _agent_texts(c, account, cid, since):
    if not _exists(c, 'whatsapp_agent_jobs'):
        return []
    return [r['reply_text'] for r in c.execute('''SELECT reply_text FROM whatsapp_agent_jobs WHERE account_id=%s
        AND conversation_id=%s AND completed_at > %s AND reply_text IS NOT NULL''', (account, cid, since)).fetchall()]


def _staff_answered_locally(c, account, cid, since):
    return _exists(c, 'whatsapp_inbox_drafts') and bool(c.execute('''SELECT 1 FROM whatsapp_inbox_drafts WHERE account_id=%s
        AND conversation_id=%s AND state='accepted' AND updated_at > %s LIMIT 1''', (account, cid, since)).fetchone())


# ---------- 2. decide what is due ----------

def due_promises(now):
    """[(promise, kind)] kind = remind | late."""
    with db() as c:
        c.execute('''UPDATE customer_promises SET status='expired', closed_at=%s, closed_by='auto'
            WHERE status='open' AND due_at < %s''', (now, now - dt.timedelta(days=3)))
        rows = c.execute('''SELECT * FROM customer_promises WHERE status='open' AND due_at <= %s ORDER BY due_at LIMIT 20''',
                         (now + dt.timedelta(minutes=PROMISE_REMIND),)).fetchall()
    out = []
    for p in rows:
        if now >= p['due_at'] + dt.timedelta(minutes=PROMISE_LATE) and not p['escalated_at']:
            out.append((p, 'late'))
        elif not p['reminded_at'] and now < p['due_at'] + dt.timedelta(minutes=PROMISE_LATE):
            out.append((p, 'remind'))
    return out


def waiting(now):
    """Conversations where the customer is waiting for a person: [{account, cid, sender, since, why, level}]."""
    found = {}
    with db() as c:
        def add(account, cid, sender, since, why):
            key = (account, cid)
            if key not in found or since > found[key]['since']:
                found[key] = {'account': account, 'cid': cid, 'sender': sender, 'since': since, 'why': why}
        window = now - dt.timedelta(hours=18)
        if _exists(c, 'whatsapp_conversation_takeovers') and _exists(c, 'whatsapp_takeover_receipts'):
            for r in c.execute('''SELECT r.account_id, r.conversation_id, r.sender, MAX(r.received_at) at
                    FROM whatsapp_takeover_receipts r JOIN whatsapp_conversation_takeovers t
                      ON t.account_id=r.account_id AND t.conversation_id=r.conversation_id AND t.paused
                    WHERE r.received_at > %s GROUP BY 1,2,3''', (window,)).fetchall():
                add(r['account_id'], r['conversation_id'], r['sender'], r['at'], 'المحادثة محوّلة لموظف والعميل كتب')
        if _exists(c, 'whatsapp_handoff_summaries'):
            for r in c.execute('''SELECT account_id, conversation_id, sender, MAX(created_at) at, MAX(reason) reason
                    FROM whatsapp_handoff_summaries WHERE created_at > %s AND reason <> 'staff' GROUP BY 1,2,3''', (window,)).fetchall():
                add(r['account_id'], r['conversation_id'], r['sender'], r['at'], 'طُلب تحويل المحادثة لموظف')
        if _exists(c, 'whatsapp_agent_jobs'):
            for r in c.execute('''SELECT j.account_id, j.conversation_id, j.sender, MAX(j.created_at) at FROM whatsapp_agent_jobs j
                    WHERE j.status IN ('failed','uncertain') AND j.created_at > %s
                      AND NOT EXISTS (SELECT 1 FROM whatsapp_agent_jobs k WHERE k.account_id=j.account_id
                          AND k.conversation_id=j.conversation_id AND k.status='sent' AND k.created_at > j.created_at)
                    GROUP BY 1,2,3''', (window,)).fetchall():
                add(r['account_id'], r['conversation_id'], r['sender'], r['at'], 'رسالة العميل لم يصلها أي رد')
        team, out = _team_numbers(), []
        for w in found.values():
            if digits(w['sender']) in team or _staff_answered_locally(c, w['account'], w['cid'], w['since']):
                continue
            minutes = (now - w['since']).total_seconds() / 60
            level = 2 if minutes >= WAIT_ESCALATE else 1 if minutes >= WAIT_FIRST else 0
            if not level:
                continue
            done = {r['level'] for r in c.execute('''SELECT level FROM customer_wait_alerts WHERE account_id=%s
                AND conversation_id=%s AND since=%s''', (w['account'], w['cid'], w['since'])).fetchall()}
            if level in done or (level == 1 and 2 in done):
                continue
            out.append(dict(w, level=level, minutes=int(minutes)))
    return out


# ---------- 3. alert texts ----------

def _who(sender):
    return '+' + digits(sender)


def promise_text(p, kind, checked):
    head = ('⏰ وعد لعميل يحل موعده الساعة ' + _local(p['due_at']) if kind == 'remind'
            else '🔴 وعد لعميل فات موعده (' + _local(p['due_at']) + ') ولم يُرسل له شيء')
    lines = [head, f"العميل: {_who(p['sender'])}", f"قالها: {p['said_by']} الساعة {_local(p['said_at'])}",
             '«' + ' '.join(str(p['text']).split())[:220] + '»']
    if checked is None:
        lines.append('(لم أتمكن من قراءة المحادثة للتأكد؛ إن رددتم عليه تجاهل التنبيه)')
    lines.append(f"إذا انتهى الموضوع اكتب: تم الوعد {p['id']}")
    return '\n'.join(lines)


def wait_text(w, checked):
    head = ('🔴 تصعيد: عميل ينتظر رد موظف منذ ' if w['level'] == 2 else '⏳ عميل ينتظر رد موظف منذ ') + f"{w['minutes']} دقيقة"
    lines = [head, f"العميل: {_who(w['sender'])}", 'السبب: ' + w['why'] + ' الساعة ' + _local(w['since'])]
    if checked is None:
        lines.append('(لم أتمكن من قراءة المحادثة للتأكد؛ إن رددتم عليه تجاهل التنبيه)')
    lines.append('الرد من صندوق محادثات واتساب في المنصة.')
    return '\n'.join(lines)


def upset_text(e, summary):
    lines = ['😠 عميل منزعج — تدخل الآن', f"العميل: {_who(e['sender'])}", 'رسالته: «' + ' '.join(str(e['text']).split())[:260] + '»',
             'المؤشرات: ' + e['reasons'], f'أوقفت عروض العملاء لهذا الرقم {HOLD_DAYS} أيام.']
    if summary:
        lines += ['', summary]
    return '\n'.join(lines)


# ---------- 4. one tick ----------

async def tick(now=None, deliver=None):
    """Collect, check and alert. Returns the list of alert texts that were delivered."""
    from starlette.concurrency import run_in_threadpool
    if not enabled():
        return []
    if deliver is None:
        from app.owner_briefing import deliver
    now = now or utcnow()
    await run_in_threadpool(collect, now)
    if _quiet(now):
        return []
    sent, reads = [], 0
    for e in await run_in_threadpool(_pending_upsets, now):
        text = upset_text(e, await run_in_threadpool(_handoff_summary, e, now))
        await run_in_threadpool(_hold, e['sender'], now)
        await deliver(text)
        await run_in_threadpool(_mark, 'UPDATE customer_upset_events SET alerted_at=%s WHERE id=%s', (now, e['id']))
        sent.append(text)
    for p, kind in await run_in_threadpool(due_promises, now):
        with db() as c:
            if _staff_answered_locally(c, p['account_id'], p['conversation_id'], p['said_at']):
                c.execute("UPDATE customer_promises SET status='kept', closed_at=%s, closed_by='auto' WHERE id=%s", (now, p['id']))
                continue
            agent = _agent_texts(c, p['account_id'], p['conversation_id'], p['said_at'])
        if reads >= MAX_PROVIDER_READS:
            break
        reads += 1
        checked = await answered_after(p['account_id'], p['conversation_id'], p['said_at'], agent, [p['text']])
        if checked:
            await run_in_threadpool(_mark, "UPDATE customer_promises SET status='kept', closed_at=%s, closed_by='auto' WHERE id=%s",
                                    (now, p['id']))
            continue
        text = promise_text(p, kind, checked)
        await deliver(text)
        sql = ('UPDATE customer_promises SET escalated_at=%s, reminded_at=COALESCE(reminded_at,%s) WHERE id=%s' if kind == 'late'
               else 'UPDATE customer_promises SET reminded_at=%s, reminded_at=reminded_at WHERE id=%s')
        params = (now, now, p['id']) if kind == 'late' else (now, p['id'])
        await run_in_threadpool(_mark, sql.replace(', reminded_at=reminded_at', ''), params)
        sent.append(text)
    for w in await run_in_threadpool(waiting, now):
        if reads >= MAX_PROVIDER_READS:
            break
        reads += 1
        with db() as c:
            agent = _agent_texts(c, w['account'], w['cid'], w['since'])
        checked = await answered_after(w['account'], w['cid'], w['since'], agent)
        outcome = 'answered' if checked else 'alerted'
        if not checked:
            text = wait_text(w, checked)
            await deliver(text)
            sent.append(text)
        await run_in_threadpool(_mark, '''INSERT INTO customer_wait_alerts(account_id,conversation_id,since,level,outcome,created_at)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''', (w['account'], w['cid'], w['since'], w['level'], outcome, now))
        if checked:  # answered: never alert this wait again at any level
            await run_in_threadpool(_mark, '''INSERT INTO customer_wait_alerts(account_id,conversation_id,since,level,outcome,created_at)
                VALUES(%s,%s,%s,2,'answered',%s) ON CONFLICT DO NOTHING''', (w['account'], w['cid'], w['since'], now))
    try:
        from app import group_watch
        if group_watch.enabled():
            await run_in_threadpool(group_watch.flush)
            await group_watch.poll(now)
            sent += await group_watch.check(now, deliver, reads_left=max(0, MAX_PROVIDER_READS - reads))
            from app import group_dispatch  # the general manager hands group requests to the departments
            group_dispatch.kick()
    except Exception as exc:
        print('GROUP_WATCH_TICK', type(exc).__name__, str(exc)[:160], flush=True)
    try:
        from app import office_inbox  # and every customer request from the private chats (owner, 27 Nov 2026)
        office_inbox.kick()
    except Exception as exc:
        print('GROUP_WATCH_TICK', type(exc).__name__, str(exc)[:160], flush=True)
    return sent


def _mark(sql, params):
    with db() as c:
        c.execute(sql, params)


def _pending_upsets(now):
    with db() as c:
        return c.execute('''SELECT * FROM customer_upset_events WHERE alerted_at IS NULL AND created_at > %s ORDER BY id LIMIT 5''',
                         (now - dt.timedelta(hours=12),)).fetchall()


def _handoff_summary(e, now=None):
    try:
        from app import auto_handoff
        row = auto_handoff.handoff(e['account_id'], e['conversation_id'], e['sender'], 'upset', details=e['reasons'],
                                   actor='no-wait', now=now)
        return row['summary'] if row else ''
    except Exception as exc:
        print('NO_WAIT_HANDOFF_FAILED', type(exc).__name__, str(exc)[:120], flush=True)
        return ''


def _hold(sender, now):
    with db() as c:
        c.execute('''INSERT INTO customer_marketing_holds(phone,until,reason,created_at) VALUES(%s,%s,'upset',%s)
            ON CONFLICT(phone) DO UPDATE SET until=GREATEST(customer_marketing_holds.until, EXCLUDED.until)''',
                  (digits(sender), now + dt.timedelta(days=HOLD_DAYS), now))


def held_numbers(c, now=None):
    """Numbers whose existing-customer offers are paused (used by customer_care)."""
    if not _exists(c, 'customer_marketing_holds'):
        return set()
    return {r['phone'] for r in c.execute('SELECT phone FROM customer_marketing_holds WHERE until > %s',
                                          (now or utcnow(),)).fetchall()}


# ---------- manager commands ----------

def list_text(now=None):
    init()
    now = now or utcnow()
    with db() as c:
        promises = c.execute('''SELECT * FROM customer_promises WHERE status='open' ORDER BY due_at LIMIT 15''').fetchall()
        waits = c.execute('''SELECT * FROM customer_wait_alerts WHERE created_at > %s AND outcome='alerted'
            ORDER BY created_at DESC LIMIT 10''', (now - dt.timedelta(hours=24),)).fetchall()
        upset = c.execute('''SELECT * FROM customer_upset_events WHERE created_at > %s ORDER BY id DESC LIMIT 10''',
                          (now - dt.timedelta(days=2),)).fetchall()
    lines = ['📋 لا أحد ينتظر']
    lines.append(f'الوعود المفتوحة: {len(promises)}')
    for p in promises:
        late = ' — متأخر' if p['due_at'] < now else ''
        lines.append(f"  {p['id']}. {_who(p['sender'])} — موعده {_local(p['due_at'])}{late} — {p['said_by']}: «{' '.join(str(p['text']).split())[:90]}»")
    lines.append(f'تنبيهات انتظار آخر 24 ساعة: {len(waits)}')
    for w in waits:
        lines.append(f"  • منذ {_local(w['since'])} — {'تصعيد' if w['level'] == 2 else 'تنبيه'}")
    lines.append(f'عملاء منزعجون آخر يومين: {len(upset)}')
    for e in upset:
        lines.append(f"  • {_who(e['sender'])}: «{' '.join(str(e['text']).split())[:80]}»")
    try:
        from app import group_watch
        lines.append(group_watch.list_text(now))
    except Exception:
        pass
    if promises:
        lines.append('لإقفال وعد: تم الوعد <الرقم>')
    return '\n'.join(lines)


def close(pid, actor=''):
    init()
    with db() as c:
        row = c.execute('''UPDATE customer_promises SET status='closed', closed_by=%s, closed_at=%s
            WHERE id=%s AND status='open' RETURNING id''', (actor or 'الفريق', utcnow(), pid)).fetchone()
    return f'✅ أُقفل الوعد {pid}.' if row else f'لا يوجد وعد مفتوح برقم {pid}.'


def register_worker(app):
    async def loop():
        await asyncio.sleep(400)
        while True:
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('NO_WAIT', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(120)

    @app.on_event('startup')
    async def _start():
        if enabled():
            init()
            app.state.no_wait_task = asyncio.create_task(loop())
