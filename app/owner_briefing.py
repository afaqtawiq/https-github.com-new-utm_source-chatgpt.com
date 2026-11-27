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
            # Transport, containers & shipping, e-mail (owner direction 20 Nov 2026: every department in one morning view).
            'loads': q('SELECT COUNT(*) FROM naqliat_loads WHERE created_at::date=%s', (y,)),
            'offers': q('SELECT COUNT(*) FROM load_broadcasts WHERE created_at::date=%s', (y,)),
            'offer_sent': q('''SELECT COUNT(*) FROM load_broadcast_recipients r JOIN load_broadcasts b ON b.id=r.broadcast_id
                             WHERE b.created_at::date=%s AND r.status='sent' ''', (y,)),
            'overdue': q("SELECT COUNT(*) FROM container_returns WHERE status IN ('open','delivered','driver_reported') AND free_until < %s", (today,)),
            'ending': q('''SELECT COUNT(*) FROM container_returns WHERE status IN ('open','delivered','driver_reported')
                         AND free_until BETWEEN %s AND %s''', (today, today + dt.timedelta(days=2))),
            'ext_drafts': q("SELECT COUNT(*) FROM free_time_requests WHERE status='draft'"),
            'arriving': q('''SELECT COUNT(*) FROM shipment_tracks WHERE NOT arrived AND eta::date BETWEEN %s AND %s''',
                          (today, today + dt.timedelta(days=7))),
            'mail_wait': q("SELECT COUNT(*) FROM mail_agent_items WHERE action IN ('draft','preview','send_failed')"),
        }
    fmt = lambda v: '—' if v is None else str(v)
    lines = ['☀️ صباح الخير — ملخص آفاق طويق ليوم ' + y.isoformat(), '',
             '📋 العمليات',
             '• بيانات سُجلت في الفوترة: ' + fmt(data['billing']),
             '• بيانات مفتوحة: ' + fmt(data['open_decl']) + ' — منها بانتظار سداد الرسوم: ' + fmt(data['duties']),
             '', '🚚 النقل (خالد)',
             '• حمولات جديدة من نقليات: ' + fmt(data['loads']) + ' — عروض للسائقين: ' + fmt(data['offers'])
             + ' (وصلت ' + fmt(data['offer_sent']) + ' سائق)',
             '', '🚢 الحاويات والشحن (سلطان)',
             '• حاويات متأخرة عن المدة المجانية: ' + fmt(data['overdue']) + ' — تنتهي خلال يومين: ' + fmt(data['ending']),
             '• طلبات تمديد جاهزة بانتظار «نفذ»: ' + fmt(data['ext_drafts']),
             '• شحنات متوقع وصولها خلال 7 أيام: ' + fmt(data['arriving']),
             '', '📧 البريد (دانة)',
             '• رسائل تنتظر رد: ' + fmt(data['mail_wait']),
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
    if today.weekday() == 6:  # Sunday: the weekly scorecard of the virtual office (owner, 27 Nov 2026)
        try:
            from app import office_scorecard
            lines += ['', office_scorecard.text(7)]
        except Exception as exc:
            print('OFFICE_SCORECARD', type(exc).__name__, str(exc)[:120], flush=True)
    return '\n'.join(lines)


# ---------- delivery ----------

DIGEST_QUIET = 90      # seconds without a new update before the manager sends the bundle
DIGEST_MAX_WAIT = 300  # never hold an update longer than this
MANAGER = 'المدير العام'


def _outbox(c):
    c.execute('''CREATE TABLE IF NOT EXISTS owner_outbox(id BIGSERIAL PRIMARY KEY, body TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), sent_at TIMESTAMPTZ)''')


async def deliver(text, urgent=False):
    """Owner (23 Nov 2026): «تواصلي مع المدير، وهو يوزع المهام ويعطيني النتائج — رسالة واحدة تكفي». Every
    department's notice goes to the general manager's outbox; he sends ONE message with all updates (after 90 s of
    quiet, at most 5 minutes later). urgent=True (or OWNER_DIGEST=0) sends at once."""
    if not urgent and os.getenv('OWNER_DIGEST', '1') != '0' and str(text or '').strip():
        try:
            def queue():
                with db() as c:
                    _outbox(c)
                    c.execute('INSERT INTO owner_outbox(body) VALUES(%s)', (str(text)[:6000],))
            await run_in_threadpool(queue)
            return 'queued'
        except Exception as exc:
            print('OWNER_OUTBOX_FAILED', type(exc).__name__, str(exc)[:120], flush=True)
    return await send_now(text)


def bundle(bodies):
    """One message from the manager: duplicates merged (×n), each update separated, split under WhatsApp's limit."""
    seen, order = {}, []
    for b in bodies:
        key = b.strip()
        if key in seen:
            seen[key] += 1
        else:
            seen[key] = 1
            order.append(key)
    items = [k + (f'\n(تكرر ×{seen[k]})' if seen[k] > 1 else '') for k in order]
    head = f'📋 {MANAGER} — ' + ('تحديث' if len(items) == 1 else f'{len(items)} تحديثات من الأقسام')
    parts, cur = [], head
    for it in items:
        block = '\n\n▫️ ' + it
        if len(cur) + len(block) > 3500 and cur != head:
            parts.append(cur)
            cur = f'📋 {MANAGER} (تكملة)'
        cur += block[:3400]
    parts.append(cur)
    return parts


async def flush_outbox(force=False):
    def take():
        with db() as c:
            _outbox(c)
            rows = c.execute('SELECT id, body, created_at FROM owner_outbox WHERE sent_at IS NULL ORDER BY id').fetchall()
            if not rows:
                return []
            now = dt.datetime.now(dt.timezone.utc)
            quiet = (now - rows[-1]['created_at']).total_seconds() >= DIGEST_QUIET
            old = (now - rows[0]['created_at']).total_seconds() >= DIGEST_MAX_WAIT
            if not (force or quiet or old):
                return []
            c.execute('UPDATE owner_outbox SET sent_at=NOW() WHERE id = ANY(%s)', ([r['id'] for r in rows],))
            c.execute("DELETE FROM owner_outbox WHERE sent_at < NOW() - INTERVAL '7 days'")
            return [r['body'] for r in rows]
    bodies = await run_in_threadpool(take)
    for part in (bundle(bodies) if bodies else []):
        await send_now(part)
    return len(bodies)


async def send_now(text):
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

    async def digest_loop():
        await asyncio.sleep(20)
        while True:
            try:
                await flush_outbox()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('OWNER_DIGEST_ERROR', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(30)

    @app.on_event('startup')
    async def start():
        app.state.owner_briefing_worker = asyncio.create_task(loop())
        app.state.owner_digest_worker = asyncio.create_task(digest_loop())
