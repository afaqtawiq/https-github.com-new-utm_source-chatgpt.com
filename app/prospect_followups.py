"""Follow-ups for prospects who did not reply (owner request, Nov 2026: the agent contacts prospects on its own).

Step 1 three days after the introduction, step 2 seven days after it (at least four days after step 1), then stop.
Only companies still «contacted» (no reply recorded), never opted out, Sunday–Thursday 9:00–20:00 Riyadh, at most
FOLLOWUP_DAILY_CAP per day, through one Meta-approved marketing template. An uncertain provider result stops the run.
Enabled only with the same switches as the introduction autopilot (AUTO_OUTREACH=1 and ENABLE_EXTERNAL_ACTIONS=1).
"""
import datetime as dt
import os
import re

from app.storage import db, utcnow

TEMPLATE = 'afaaq_marketing_prospect_followup_v1_ar'
RIYADH = dt.timezone(dt.timedelta(hours=3))
STEPS = {1: dt.timedelta(days=3), 2: dt.timedelta(days=7)}


def body(name, line):
    return (f'مرحبًا {name}،\nنتابع معكم رسالتنا السابقة من آفاق طويق للتخليص الجمركي والنقل.\n{line}\n'
            'للاستفسار ردّوا على هذه الرسالة.\nلإيقاف الرسائل أرسل: إيقاف')


def step_line(step):
    from app.prospect_replies import price_table
    tiers, routes = price_table()
    low, riyadh = min(tiers.values() or [200]), routes.get('من ميناء جدة الإسلامي إلى الرياض')
    if step == 1:
        return (f'هل لديكم شحنات قادمة؟ نخلّصها في جميع المنافذ السعودية البحرية والجوية والبرية، ونرسل العرض في نفس اليوم: التخليص من {low:,} ريال للحاوية'
                + (f' والنقل من ميناء جدة إلى الرياض {riyadh:,} ريال للحاوية.' if riyadh else '.'))
    return ('إذا كان لديكم مخلص حالي، جرّبونا في شحنة واحدة فقط: نخلّصها وننقلها ونتابعها حتى إعادة الحاوية الفارغة، '
            'ونعطيكم تقريرًا بكل مرحلة.')


def template_spec():
    return {'name': TEMPLATE, 'language': 'ar', 'category': 'MARKETING', 'components': [
        {'type': 'body', 'text': body('{{1}}', '{{2}}'),
         'example': {'body_text': [['مؤسسة المثال التجارية', 'هل لديكم شحنات قادمة خلال الأسابيع القادمة؟ نرسل لكم عرض السعر في نفس اليوم.']]}}]}


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
        c.execute('''CREATE TABLE IF NOT EXISTS prospect_followups(id BIGSERIAL PRIMARY KEY, prospect_id BIGINT NOT NULL, step INTEGER NOT NULL,
            status TEXT NOT NULL, error TEXT, created_at TIMESTAMPTZ NOT NULL, UNIQUE(prospect_id, step))''')


def cap():
    try:
        return max(0, min(100, int(os.getenv('FOLLOWUP_DAILY_CAP', '30'))))
    except ValueError:
        return 30


def in_hours(now):
    local = now.astimezone(RIYADH)
    return local.weekday() not in (4, 5) and 9 <= local.hour < 20


def due(now=None, limit=None):
    """(prospect, step) pairs due now, oldest first."""
    init()
    now = now or utcnow()
    local_day = now.astimezone(RIYADH).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc)
    with db() as c:
        sent_today = c.execute("SELECT COUNT(*) n FROM prospect_followups WHERE created_at >= %s AND status IN ('sent','uncertain')",
                               (local_day,)).fetchone()['n']
        room = (cap() if limit is None else limit) - sent_today
        if room <= 0:
            return []
        rows = c.execute('''SELECT d.*, (SELECT MAX(step) FROM prospect_followups f WHERE f.prospect_id=d.id) last_step,
                (SELECT MAX(created_at) FROM prospect_followups f WHERE f.prospect_id=d.id) last_at
            FROM daily_prospects d WHERE d.status='contacted' AND d.phone<>'' AND d.outcome_note LIKE 'autopilot: whatsapp%%'
            AND d.decided_at < %s AND d.decided_at > %s - INTERVAL '30 days'
            AND NOT EXISTS (SELECT 1 FROM marketing_suppressions s WHERE s.channel='whatsapp'
                AND right(regexp_replace(s.recipient,'\\D','','g'),9)=right(regexp_replace(d.phone,'\\D','','g'),9))
            ORDER BY d.decided_at LIMIT 500''', (now - STEPS[1], now)).fetchall()
        replied = {r['prospect_id'] for r in c.execute('SELECT DISTINCT prospect_id FROM prospect_replies').fetchall()} \
            if c.execute("SELECT to_regclass('prospect_replies') t").fetchone()['t'] else set()
    out = []
    for r in rows:
        if r['id'] in replied:
            continue
        step = (r['last_step'] or 0) + 1
        if step not in STEPS or now - r['decided_at'] < STEPS[step]:
            continue
        if r['last_at'] and now - r['last_at'] < dt.timedelta(days=4):
            continue
        out.append((r, step))
        if len(out) >= room:
            break
    return out


async def run(now=None):
    from app import prospect_autopilot, zernio_whatsapp as wa
    stats = {'enabled': prospect_autopilot.enabled(), 'sent': 0, 'failed': 0, 'template': None}
    now = now or utcnow()
    if not stats['enabled']:
        return stats
    try:
        stats['template'] = await ensure_template()
    except Exception as exc:
        stats['template'] = 'ERROR_' + type(exc).__name__
    if stats['template'] != 'APPROVED' or not in_hours(now):
        return stats
    from starlette.concurrency import run_in_threadpool
    for r, step in await run_in_threadpool(due, now):
        with db() as c:
            if not c.execute('''INSERT INTO prospect_followups(prospect_id,step,status,created_at) VALUES(%s,%s,'sending',%s)
                    ON CONFLICT DO NOTHING RETURNING id''', (r['id'], step, utcnow())).fetchone():
                continue
        name = ' '.join(str(r['company_name'] or '').split())[:80] or 'عميلنا العزيز'
        try:
            await wa.send(r['phone'], body(name, step_line(step)), template_prefix='afaaq_marketing_')
            status, error = 'sent', None
            stats['sent'] += 1
        except wa.WhatsAppBlocked as exc:
            status, error = 'failed', str(exc)[:200]
            stats['failed'] += 1
        except Exception as exc:  # uncertain: stop, never retry automatically
            status, error = 'uncertain', type(exc).__name__
            stats['stopped'] = error
        with db() as c:
            c.execute('UPDATE prospect_followups SET status=%s,error=%s WHERE prospect_id=%s AND step=%s', (status, error, r['id'], step))
        if status == 'uncertain':
            break
    return stats


def summary(days=7):
    init()
    with db() as c:
        rows = c.execute('''SELECT step, status, COUNT(*) n FROM prospect_followups WHERE created_at > NOW()-make_interval(days => %s)
            GROUP BY 1,2''', (int(days),)).fetchall()
    sent = {s: sum(r['n'] for r in rows if r['step'] == s and r['status'] == 'sent') for s in STEPS}
    return f'متابعات العملاء المحتملين (آخر {days} أيام): الأولى {sent[1]} — الثانية {sent[2]}.'


def register_worker(app):
    import asyncio

    async def loop():
        await asyncio.sleep(280)
        while True:
            try:
                stats = await run()
                if stats.get('sent') or stats.get('failed') or stats.get('stopped') or (stats['enabled'] and stats['template'] not in (None, 'APPROVED')):
                    print('PROSPECT_FOLLOWUP', stats, flush=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('PROSPECT_FOLLOWUP_ERROR', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(900)

    @app.on_event('startup')
    async def start():
        init()
        app.state.prospect_followups_worker = asyncio.create_task(loop())
