"""Owner-requested monitoring and morning briefing (Nov 2026).

1) Health alerts, hourly: Claude API key, Meta (Facebook/Instagram) page token, Zernio social key and the
   WhatsApp account. A message goes to the owner only when a check changes state (broken / recovered).
2) Morning briefing at 08:00 Riyadh: yesterday's work, finance drafts awaiting approval, declarations waiting
   for duties, sales/marketing activity.
Messages go to the owner's WhatsApp (WHATSAPP_COMMAND_OWNER); if WhatsApp refuses (no open window/template),
the same text is emailed from the official mailbox to OWNER_ALERT_EMAIL (default info@afaqtawiqs.net).
Enabled with ENABLE_EXTERNAL_ACTIONS=1 and AFAQ_OWNER_ALERTS (default 1).
"""
import asyncio
import datetime as dt
import os

import httpx
from starlette.concurrency import run_in_threadpool

from app.social_zernio import RIYADH
from app.storage import db, utcnow


def enabled():
    return os.getenv('AFAQ_OWNER_ALERTS', '1') == '1' and os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') == '1'


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS owner_health(name TEXT PRIMARY KEY, ok BOOLEAN NOT NULL,
            detail TEXT NOT NULL DEFAULT '', changed_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS owner_briefings(day DATE PRIMARY KEY, channel TEXT NOT NULL,
            body TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')
    from app.customer_followup_digest import init as init_followup_delivery
    init_followup_delivery()


LABELS = {'claude': 'مفتاح Claude (فهم رسائل واتساب والردود)', 'meta': 'ربط فيسبوك وإنستغرام (Meta)',
          'zernio_social': 'ربط يوتيوب وتيك توك (Zernio)', 'whatsapp': 'حساب واتساب للوكيل'}


# ---------- checks ----------

async def check_claude():
    key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    if not key:
        return False, 'المفتاح غير موجود'
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get('https://api.anthropic.com/v1/models', headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
    return r.status_code == 200, '' if r.status_code == 200 else 'HTTP ' + str(r.status_code)


async def check_meta():
    from app.meta_connect import MetaError, connected, credentials, graph
    if not await run_in_threadpool(connected):
        return False, 'غير مربوط'
    try:
        conn = await run_in_threadpool(credentials)
        await run_in_threadpool(graph, 'GET', conn['page_id'], conn['token'], params={'fields': 'id'})
        return True, ''
    except MetaError as exc:
        return False, str(exc)[:160]


async def check_zernio_social():
    from app.social_publishing import connection
    from app.social_zernio import provider_request
    try:
        key, _ = await run_in_threadpool(connection)
        await run_in_threadpool(provider_request, key, 'GET', '/accounts')
        return True, ''
    except Exception as exc:
        return False, str(exc)[:160]


async def check_whatsapp():
    from app import zernio_whatsapp as z
    try:
        async with z.client() as c:
            await z.validate_account(c)
        return True, ''
    except Exception as exc:
        return False, (type(exc).__name__ + ' ' + str(exc))[:160]


CHECKS = {'claude': check_claude, 'meta': check_meta, 'zernio_social': check_zernio_social, 'whatsapp': check_whatsapp}


def transition(name, ok, detail):
    """Store state; return 'broken'/'recovered' only when it changes (first observation of a failure alerts)."""
    with db() as c:
        row = c.execute('SELECT ok FROM owner_health WHERE name=%s', (name,)).fetchone()
        if row and row['ok'] == ok:
            return None
        c.execute('''INSERT INTO owner_health(name,ok,detail,changed_at) VALUES(%s,%s,%s,%s)
            ON CONFLICT(name) DO UPDATE SET ok=excluded.ok,detail=excluded.detail,changed_at=excluded.changed_at''',
                  (name, ok, detail, utcnow()))
    if not ok:
        return 'broken'
    return 'recovered' if row else None


async def run_checks():
    alerts = []
    for name, fn in CHECKS.items():
        try:
            ok, detail = await asyncio.wait_for(fn(), 40)
        except Exception as exc:
            ok, detail = False, type(exc).__name__
        change = await run_in_threadpool(transition, name, ok, detail)
        if change == 'broken':
            alerts.append('⚠️ تعطل: ' + LABELS[name] + (' — ' + detail if detail else ''))
        elif change == 'recovered':
            alerts.append('✅ عاد للعمل: ' + LABELS[name])
    return alerts


# ---------- briefing ----------

def scalar(c, sql, params=()):
    try:
        c.execute('SAVEPOINT q')
        row = c.execute(sql, params).fetchone()
        c.execute('RELEASE SAVEPOINT q')
        return list(row.values())[0] if row else 0
    except Exception:
        c.execute('ROLLBACK TO SAVEPOINT q')
        return None


def briefing_text(today=None):
    today = today or dt.datetime.now(RIYADH).date()
    y = today - dt.timedelta(days=1)
    with db() as c:
        q = lambda sql, p=(): scalar(c, sql, p)
        data = {
            'billing': q('SELECT COUNT(*) FROM billing_declarations WHERE created_at::date=%s', (y,)),
            'drafts': q("SELECT COUNT(*) FROM finance_documents WHERE status IN ('draft','reviewed')"),
            'duties': q("""SELECT COUNT(*) FROM customs_declarations d WHERE (SELECT stage FROM customs_declaration_events e
                         WHERE e.declaration_id=d.id ORDER BY e.id DESC LIMIT 1)='duties_due'"""),
            'open_decl': q("""SELECT COUNT(*) FROM customs_declarations d WHERE (SELECT stage FROM customs_declaration_events e
                         WHERE e.declaration_id=d.id ORDER BY e.id DESC LIMIT 1) NOT IN ('delivered','closed')"""),
            'customers': q("SELECT COUNT(DISTINCT sender) FROM whatsapp_agent_jobs WHERE status='sent' AND created_at::date=%s", (y,)),
            'contacted': q("SELECT COUNT(*) FROM daily_prospects WHERE status='contacted' AND updated_at::date=%s", (y,)),
            'comments': q("SELECT COUNT(*) FROM afaq_auto_comment_replies WHERE status='sent' AND created_at::date=%s", (y,)),
            'poster': q('SELECT status FROM afaq_daily_posters WHERE day=%s', (y,)),
            'broken': q('SELECT COUNT(*) FROM owner_health WHERE NOT ok'),
            'receivable': q('''SELECT COALESCE(SUM(e.signed_minor),0) FROM finance_entries e JOIN finance_documents d ON d.id=e.document_id
                             WHERE e.side='receivable' AND d.status IN ('posted','reversed') AND d.currency='SAR' '''),
        }
    fmt = lambda v: '—' if v is None else str(v)
    lines = ['☀️ صباح الخير — ملخص آفاق طويق ليوم ' + y.isoformat(), '',
             '📋 العمليات',
             '• بيانات سُجلت في الفوترة: ' + fmt(data['billing']),
             '• بيانات مفتوحة: ' + fmt(data['open_decl']) + ' — منها بانتظار سداد الرسوم: ' + fmt(data['duties']),
             '', '💰 المالية',
             '• قيود بانتظار اعتمادك وترحيلك: ' + fmt(data['drafts']) + ' (صفحة المالية)',
             '• إجمالي المستحق لكم: ' + ('—' if data['receivable'] is None else format(data['receivable'] / 100, ',.2f')) + ' ريال (صفحة التحصيل)',
             '', '📣 المبيعات والتسويق',
             '• عملاء رد عليهم الوكيل في واتساب: ' + fmt(data['customers']),
             '• شركات تم التواصل معها: ' + fmt(data['contacted']),
             '• ردود على تعليقات السوشيال: ' + fmt(data['comments']),
             '• البوستر اليومي: ' + {'done': 'نُشر ✅', 'partial': 'نُشر جزئيًا ⚠️', 'failed': 'فشل ❌'}.get(data['poster'] or '', 'لم يُنشر')]
    if data['broken']:
        lines += ['', '⚠️ روابط معطلة الآن: ' + fmt(data['broken']) + ' — راجع رسائل التنبيه.']
    return '\n'.join(lines)


# ---------- delivery ----------

async def deliver(text):
    from app import zernio_whatsapp as z
    owner = os.getenv('WHATSAPP_COMMAND_OWNER', '').strip()
    if owner:
        try:
            await z.send(owner, text)
            return 'whatsapp'
        except Exception as exc:
            print('OWNER_ALERT_WHATSAPP_FAILED', type(exc).__name__, str(exc)[:120], flush=True)
    return await deliver_email(text)


async def deliver_email(text):
    """Existing fallback, kept separate so new WhatsApp-only sections cannot leak."""
    try:
        from app.prospect_autopilot import system_user
        from app.spacemail import send as mail_send
        to = os.getenv('OWNER_ALERT_EMAIL', 'info@afaqtawiqs.net')
        await run_in_threadpool(mail_send, system_user(), to, 'تنبيه وكيل آفاق طويق', text)
        return 'email'
    except Exception as exc:
        print('OWNER_ALERT_EMAIL_FAILED', type(exc).__name__, str(exc)[:120], flush=True)
        return 'failed'


def claim_briefing(day):
    with db() as c:
        return bool(c.execute("""INSERT INTO owner_briefings(day,channel,body,created_at) VALUES(%s,'pending','',%s)
            ON CONFLICT DO NOTHING RETURNING day""", (day, utcnow())).fetchone())


def save_briefing(day, channel, body):
    with db() as c:
        c.execute('UPDATE owner_briefings SET channel=%s,body=%s WHERE day=%s', (channel, body, day))


def register_worker(app):
    async def loop():
        await asyncio.sleep(120)
        last_check = None
        while True:
            if enabled():
                try:
                    await run_in_threadpool(init)
                    now = dt.datetime.now(RIYADH)
                    if last_check is None or (now - last_check).total_seconds() >= 3600:
                        last_check = now
                        alerts = await run_checks()
                        if alerts:
                            await deliver('تنبيه من وكيل آفاق طويق\n' + '\n'.join(alerts))
                    hour = int(os.getenv('OWNER_BRIEFING_HOUR', '8'))
                    if now.hour >= hour and await run_in_threadpool(claim_briefing, now.date()):
                        text = await run_in_threadpool(briefing_text, now.date())
                        from app.customer_followup_digest import deliver_morning
                        channel = await deliver_morning(text, now.date())
                        await run_in_threadpool(save_briefing, now.date(), channel, text)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print('OWNER_BRIEFING_ERROR', type(exc).__name__, str(exc)[:200], flush=True)
            await asyncio.sleep(300)

    @app.on_event('startup')
    async def start():
        app.state.owner_briefing_worker = asyncio.create_task(loop())
