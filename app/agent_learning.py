"""Daily learning loop for the customer WhatsApp agent (Claude's own plan, Nov 2026).

Every morning the manager gets a short scorecard of yesterday's customer conversations and the questions the agent
could NOT answer well (it had to say «لم أتمكن من التحقق», the reply failed, or the same question was repeated).
The manager teaches the correct answer in one line: «جواب 2: …» (or «علّم الوكيل: السؤال … الجواب …»).
After «نفذ» the answer is stored as an APPROVED TEAM ANSWER and the agent uses it from then on — so every gap the
team answers once never comes back. Answers can be listed and revoked. Nothing is sent to customers from here.
"""
import asyncio
import datetime as dt
import json
import os
import re

from app.storage import db, utcnow

RIYADH = dt.timezone(dt.timedelta(hours=3))
REPORT_HOUR = 8
MAX_GAPS = 8
MAX_ANSWERS = 40
_CACHE = {'at': None, 'block': ''}
_READY = False


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS agent_learned_answers(id BIGSERIAL PRIMARY KEY, question TEXT NOT NULL,
            answer TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'approved', created_by TEXT, created_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ)''')
        c.execute('''CREATE TABLE IF NOT EXISTS agent_learning_reports(day DATE PRIMARY KEY, gaps_json TEXT NOT NULL,
            text TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')
    _READY = True


def norm(text):
    text = re.sub(r'[ً-ٰٟـ؟?!.,،:؛"\'()]', ' ', str(text or '')).casefold()
    text = text.translate(str.maketrans('أإآىةؤئ', 'اااياوي'))
    return ' '.join(text.split())


STOP = {'هل', 'في', 'من', 'على', 'عن', 'الى', 'مع', 'او', 'كم', 'ما', 'ماهي', 'ايش', 'وش'}


def stem(w):
    for p in ('وال', 'بال', 'فال', 'كال', 'لل', 'ال', 'و', 'ب', 'ل', 'ف'):
        if w.startswith(p) and len(w) - len(p) >= 3:
            w = w[len(p):]
            break
    return w


def words(text):
    return {stem(w) for w in norm(text).split() if w not in STOP and len(stem(w)) > 2}


def _question(payload):
    try:
        data = payload if isinstance(payload, dict) else json.loads(payload or '{}')
    except ValueError:
        return ''
    return str(data.get('question') or '').strip()


def _unverified_prefixes():
    from app import whatsapp_natural as n
    return tuple(p[:60] for p in (n.TARIFF_UNVERIFIED_REPLY, n.SABER_UNVERIFIED_REPLY, n.FEE_TOTAL_UNVERIFIED_REPLY))


# ---------- 1. measure yesterday ----------

def day_window(day):
    start = dt.datetime.combine(day, dt.time(0), RIYADH)
    return start, start + dt.timedelta(days=1)


def gaps(day):
    """Scorecard + grouped weak questions for one Riyadh day."""
    start, end = day_window(day)
    with db() as c:
        if not c.execute("SELECT to_regclass('whatsapp_agent_jobs') t").fetchone()['t']:
            return {'total': 0, 'customers': 0, 'sent': 0, 'weak': 0, 'groups': []}
        rows = c.execute('''SELECT sender, payload, reply_text, status, diagnostics FROM whatsapp_agent_jobs
            WHERE created_at >= %s AND created_at < %s ORDER BY id''', (start, end)).fetchall()
    prefixes = _unverified_prefixes()
    weak, counts = [], {}
    for r in rows:
        q = _question(r['payload'])
        if not q:
            continue
        key = (r['sender'], norm(q))
        counts[key] = counts.get(key, 0) + 1
        reason = None
        if str(r['reply_text'] or '').startswith(prefixes):
            reason = 'تعذر التحقق'
        elif r['status'] in ('failed', 'uncertain'):
            reason = 'لم يُرسل رد'
        elif counts[key] == 3:
            reason = 'كرره العميل'
        if reason:
            weak.append({'question': q[:300], 'reason': reason, 'sender': r['sender']})
    groups = []
    for w in weak:
        ws = words(w['question'])
        for g in groups:
            inter, union = len(ws & g['words']), len(ws | g['words']) or 1
            if inter / union >= 0.5:
                g['count'] += 1
                g['senders'].add(w['sender'])
                g['reasons'].add(w['reason'])
                break
        else:
            groups.append({'question': w['question'], 'words': ws, 'count': 1, 'senders': {w['sender']}, 'reasons': {w['reason']}})
    groups.sort(key=lambda g: (-len(g['senders']), -g['count']))
    learned = approved()
    out = []
    for g in groups:
        if any(len(g['words'] & words(a['question'])) / (len(g['words'] | words(a['question'])) or 1) >= 0.5 for a in learned):
            continue  # already taught
        out.append({'question': g['question'], 'count': g['count'], 'customers': len(g['senders']), 'reasons': sorted(g['reasons'])})
        if len(out) >= MAX_GAPS:
            break
    return {'total': len(rows), 'customers': len({r['sender'] for r in rows}),
            'sent': sum(r['status'] == 'sent' for r in rows), 'weak': len(weak), 'groups': out}


def report(day=None):
    init()
    day = day or (dt.datetime.now(RIYADH).date() - dt.timedelta(days=1))
    data = gaps(day)
    lines = [f'📈 أداء وكيل العملاء أمس ({day.isoformat()})',
             f"رسائل: {data['total']} من {data['customers']} عميل — أُرسل رد: {data['sent']}"]
    if data['total']:
        rate = 100 * (data['total'] - data['weak']) / data['total']
        lines.append(f"نسبة الأسئلة المجابة بثقة: {rate:.0f}% — أسئلة ضعيفة: {data['weak']}")
    if data['groups']:
        lines.append('\nأسئلة ما عرف يجاوبها (علّمه مرة واحدة ولن تتكرر):')
        for i, g in enumerate(data['groups'], 1):
            lines.append(f"{i}. «{g['question'][:140]}» — {g['count']} مرة من {g['customers']} عميل ({'، '.join(g['reasons'])})")
        lines.append('\nللتعليم اكتب: جواب 1: <الجواب الصحيح كما تريد أن يقوله الوكيل>')
    else:
        lines.append('لا توجد أسئلة ضعيفة جديدة 👌')
    text = '\n'.join(lines)
    with db() as c:
        c.execute('''INSERT INTO agent_learning_reports(day,gaps_json,text,created_at) VALUES(%s,%s,%s,%s)
            ON CONFLICT(day) DO UPDATE SET gaps_json=EXCLUDED.gaps_json,text=EXCLUDED.text''',
                  (day, json.dumps(data['groups'], ensure_ascii=False), text, utcnow()))
    return text


def gap_question(number):
    """Question text of gap N in the latest report."""
    init()
    with db() as c:
        row = c.execute('SELECT gaps_json FROM agent_learning_reports ORDER BY day DESC LIMIT 1').fetchone()
    groups = json.loads(row['gaps_json']) if row else []
    return groups[number - 1]['question'] if 1 <= number <= len(groups) else None


# ---------- 2. teach / revoke ----------

def validate(question, answer):
    question = re.sub(r'\s+', ' ', str(question or '')).strip()[:300]
    answer = re.sub(r'[ \t]+', ' ', str(answer or '')).strip()[:600]
    if len(question) < 4 or len(answer) < 8:
        raise ValueError('اكتب السؤال والجواب بوضوح.')
    if re.search(r'https?://(?!afaqtwiq\.com)', answer):
        raise ValueError('لا تضع روابط خارجية في الجواب المعتمد.')
    return question, answer


def save(question, answer, actor=''):
    init()
    question, answer = validate(question, answer)
    with db() as c:
        n = c.execute("SELECT COUNT(*) n FROM agent_learned_answers WHERE status='approved'").fetchone()['n']
        if n >= MAX_ANSWERS:
            return f'وصلت الأجوبة المعتمدة للحد ({MAX_ANSWERS}). احذف جوابًا قديمًا أولًا: «الأجوبة المعتمدة».'
        rid = c.execute('INSERT INTO agent_learned_answers(question,answer,created_by,created_at) VALUES(%s,%s,%s,%s) RETURNING id',
                        (question, answer, actor, utcnow())).fetchone()['id']
    _CACHE['at'] = None
    return f'✅ تعلّم الوكيل الجواب #{rid}. من الآن يجيب به عن: «{question[:100]}».'


def revoke(rid, actor=''):
    init()
    with db() as c:
        row = c.execute("UPDATE agent_learned_answers SET status='revoked',revoked_at=%s WHERE id=%s AND status='approved' RETURNING id",
                        (utcnow(), int(rid))).fetchone()
    _CACHE['at'] = None
    return f'🗑️ أُلغي الجواب #{rid}.' if row else 'الجواب غير موجود أو ملغي مسبقًا.'


def approved():
    init()
    with db() as c:
        return c.execute("SELECT id,question,answer FROM agent_learned_answers WHERE status='approved' ORDER BY id").fetchall()


def list_text():
    rows = approved()
    if not rows:
        return 'لا توجد أجوبة معتمدة بعد. علّم الوكيل من التقرير الصباحي: «جواب 1: …».'
    return 'الأجوبة المعتمدة:\n' + '\n'.join(f"#{r['id']} «{r['question'][:80]}» ← {r['answer'][:120]}" for r in rows) + \
        '\nللإلغاء: «الغ الجواب <رقم>».'


def block():
    """Approved answers for the customer agent prompt and grounding (cached 5 minutes; empty if unavailable)."""
    now = dt.datetime.now(dt.timezone.utc)
    if _CACHE['at'] and now - _CACHE['at'] < dt.timedelta(minutes=5):
        return _CACHE['block']
    try:
        rows = approved()
    except Exception:
        return ''
    text = ''
    if rows:
        text = ('\n\nAPPROVED TEAM ANSWERS (written and approved by Afaq management; when a customer asks one of these, '
                'answer with this content in natural Arabic, keep every number exactly, do not add to it):\n'
                + '\n'.join(f"- سؤال: {r['question']}\n  الجواب المعتمد: {r['answer']}" for r in rows))
    _CACHE.update(at=now, block=text)
    return text


# ---------- 3. morning delivery ----------

def due(now=None):
    local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(RIYADH)
    if local.hour < REPORT_HOUR:
        return False
    init()
    with db() as c:
        return not c.execute('SELECT 1 FROM agent_learning_reports WHERE day=%s', (local.date() - dt.timedelta(days=1),)).fetchone()


def register_worker(app):
    async def loop():
        from starlette.concurrency import run_in_threadpool
        from app.owner_briefing import deliver
        await asyncio.sleep(320)
        while True:
            try:
                if await run_in_threadpool(due):
                    await deliver(await run_in_threadpool(report))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('AGENT_LEARNING', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(600)

    @app.on_event('startup')
    async def _start():
        init()
        app.state.agent_learning_task = asyncio.create_task(loop())
