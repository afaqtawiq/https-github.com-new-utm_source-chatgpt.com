"""Automatic hand-off of ONE conversation to staff (owner request, Nov 2026) — OFF by default.

Built on the existing conversation-scoped takeover (whatsapp_takeover): the same pause, the same generation
fence, the same explicit resume. Nothing here sends anything to the customer.

Triggers (each conversation separately):
  staff       — an employee sent a manual reply from the platform inbox;
  unverified  — the agent had to answer «لم أتمكن من التحقق …» (SABER / tariff / fee total could not be verified);
  repeat      — the customer sent the same question 3 times within 30 minutes (stuck / not satisfied).

AUTO_HANDOFF_ENABLED=0 (default): SHADOW mode — the summary is recorded and shown in the inbox as «يُقترح التسليم»,
but the automatic replies are NOT paused. AUTO_HANDOFF_ENABLED=1: the conversation is paused exactly like the manual
button, and the summary explains why. The manual pause/resume button is unchanged.
"""
import datetime as dt
import os
import re
from html import escape

from app import whatsapp_agent_store as store

REASONS = {'staff': 'تدخل موظف في المحادثة', 'unverified': 'تعذر التحقق من معلومة طلبها العميل',
           'repeat': 'كرر العميل نفس السؤال', 'conflict': 'نقص أو تعارض في بيانات/مستندات العميل'}
REPEAT_COUNT, REPEAT_MINUTES = 3, 30
SUGGEST_COOLDOWN_HOURS = 6
DDL = '''CREATE TABLE IF NOT EXISTS whatsapp_handoff_summaries(id BIGSERIAL PRIMARY KEY, account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL, sender TEXT NOT NULL, reason TEXT NOT NULL, mode TEXT NOT NULL, summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL)'''
_READY = False


def enabled():
    return os.getenv('AUTO_HANDOFF_ENABLED', '0') == '1'


def triggers():
    raw = os.getenv('AUTO_HANDOFF_TRIGGERS', 'staff,unverified,repeat,conflict')
    return {t.strip() for t in raw.split(',') if t.strip() in REASONS}


def init(connection=None):
    global _READY
    if _READY and connection is None:
        return
    with store.database() as c:
        c.execute(DDL)
        c.execute('CREATE INDEX IF NOT EXISTS whatsapp_handoff_conv ON whatsapp_handoff_summaries(account_id, conversation_id, created_at DESC)')
    _READY = True


def _unverified_prefixes():
    from app import whatsapp_natural as n
    return tuple(p[:60] for p in (n.TARIFF_UNVERIFIED_REPLY, n.SABER_UNVERIFIED_REPLY, n.FEE_TOTAL_UNVERIFIED_REPLY))


def _norm(text):
    text = re.sub(r'[ً-ٰٟـ؟?!.,،]', '', str(text or '')).casefold()
    return re.sub(r'\s+', ' ', text.translate(str.maketrans('أإآىة', 'اااية'))).strip()


def _question(payload):
    import json
    try:
        data = payload if isinstance(payload, dict) else json.loads(payload or '{}')
    except ValueError:
        return ''
    return str(data.get('question') or '')


def recent_exchanges(c, account, cid, limit=6):
    rows = c.execute('''SELECT payload, reply_text, status, created_at FROM whatsapp_agent_jobs
        WHERE account_id=%s AND conversation_id=%s ORDER BY id DESC LIMIT %s''', (account, cid, limit)).fetchall()
    return list(reversed([dict(r) for r in rows]))


def repeated(c, account, cid, question, now=None):
    q = _norm(question)
    if len(q) < 4:
        return False
    since = (now or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(minutes=REPEAT_MINUTES)
    rows = c.execute('''SELECT payload FROM whatsapp_agent_jobs WHERE account_id=%s AND conversation_id=%s AND created_at>=%s
        ORDER BY id DESC LIMIT 20''', (account, cid, since)).fetchall()
    return sum(_norm(_question(r['payload'])) == q for r in rows) >= REPEAT_COUNT


def summary_text(c, account, cid, sender, reason, details=''):
    lines = [f'🔔 تسليم المحادثة للموظف — {REASONS.get(reason, reason)}', f'العميل: +{sender.lstrip("+")}']
    if details:
        lines.append('التفاصيل: ' + details[:300])
    exchanges = recent_exchanges(c, account, cid)
    if exchanges:
        last = _question(exchanges[-1]['payload'])
        if last:
            lines.append('آخر ما طلبه العميل: ' + last[:300])
        lines.append('آخر الرسائل:')
        for e in exchanges:
            q = _question(e['payload'])
            if q:
                lines.append('  العميل: ' + q[:160])
            if e.get('reply_text'):
                lines.append('  الوكيل: ' + str(e['reply_text'])[:160] + ('' if e['status'] == 'sent' else f" ({e['status']})"))
    try:
        from app.customer_shipments import for_phone
        ships = for_phone(c, sender)
    except Exception:
        ships = []
    if ships:
        lines.append('شحنات مرتبطة بهذا الرقم:')
        for s in ships[:5]:
            lines.append(f"  • {s['ref']}: {s['status']}" + (f" — التالي: {s['next_step']}" if s.get('next_step') else ''))
    lines.append('الرد الآلي ' + ('موقوف لهذه المحادثة فقط؛ الاستئناف من صندوق المحادثات.' if enabled() and reason in triggers()
                                else 'لم يُوقف (الإيقاف التلقائي غير مفعّل) — يُقترح أن يتولاها موظف.'))
    return '\n'.join(lines)


def handoff(account, cid, sender, reason, details='', actor='auto-handoff', now=None):
    """Record a hand-off summary; pause the conversation only when enabled. Returns the stored row (or None)."""
    from app import whatsapp_takeover as takeover
    if reason not in REASONS:
        raise ValueError('unknown hand-off reason')
    init()
    now = now or dt.datetime.now(dt.timezone.utc)
    mode = 'paused' if enabled() and reason in triggers() else 'suggested'
    with store.database() as c:
        c.execute(DDL)
        if mode == 'suggested':
            recent = c.execute('''SELECT 1 FROM whatsapp_handoff_summaries WHERE account_id=%s AND conversation_id=%s
                AND reason=%s AND created_at>=%s LIMIT 1''', (account, cid, reason, now - dt.timedelta(hours=SUGGEST_COOLDOWN_HOURS))).fetchone()
            if recent:
                return None
        text = summary_text(c, account, cid, sender, reason, details)
    if mode == 'paused':
        state = takeover.read_state(account, cid)
        if state['paused']:
            mode = 'already_paused'
        else:
            try:
                takeover.set_paused(account, cid, True, actor + ':' + reason, state['generation'], sender=sender)
            except takeover.StateConflict:
                mode = 'suggested'  # a concurrent change won; never force it
    with store.database() as c:
        return c.execute('''INSERT INTO whatsapp_handoff_summaries(account_id,conversation_id,sender,reason,mode,summary,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *''', (account, cid, sender, reason, mode, text, now)).fetchone()


def after_send(job):
    """Called after an automatic reply was accepted by the provider. Returns the reason or None."""
    reply = str(job.get('reply_text') or '')
    reason = None
    if reply.startswith(_unverified_prefixes()):
        reason = 'unverified'
    else:
        with store.database() as c:
            if repeated(c, job['account_id'], job['conversation_id'], _question(job.get('payload'))):
                reason = 'repeat'
    if reason:
        handoff(job['account_id'], job['conversation_id'], job['sender'], reason)
    return reason


def staff_sent(account, cid, sender, user_id):
    return handoff(account, cid, sender, 'staff', actor='auto-handoff-staff-' + str(user_id))


def latest(account, cid, limit=3):
    init()
    with store.database() as c:
        return c.execute('''SELECT * FROM whatsapp_handoff_summaries WHERE account_id=%s AND conversation_id=%s
            ORDER BY id DESC LIMIT %s''', (account, cid, limit)).fetchall()


def install():
    """Show hand-off summaries next to the existing manual takeover control in the inbox."""
    from app import whatsapp_inbox as inbox
    original = inbox.takeover_render
    if original is None or getattr(original, '_handoff', False):
        return

    async def render(account, cid, sender, csrf):
        from starlette.concurrency import run_in_threadpool
        html = await original(account, cid, sender, csrf)
        try:
            rows = await run_in_threadpool(latest, account, cid)
        except Exception:
            rows = []
        label = {'paused': 'أُوقف الرد الآلي تلقائيًا', 'suggested': 'يُقترح التسليم للموظف (الإيقاف التلقائي غير مفعّل)',
                 'already_paused': 'المحادثة موقوفة أصلًا'}
        for r in rows:
            html += ('<section><h3>' + escape(label.get(r['mode'], r['mode'])) + ' — ' + escape(REASONS.get(r['reason'], r['reason']))
                     + '</h3><pre dir="auto">' + escape(r['summary']) + '</pre></section>')
        return html
    render._handoff = True
    inbox.takeover_render = render
