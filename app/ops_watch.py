"""Owner (22 Nov 2026): «إضافات تجعل الوكيل احترافيًا».

1) AI health guard: every 30 minutes a 1-token probe of the Anthropic API. If the account is out of credit, the key is
   refused or the API keeps failing, the owner gets ONE WhatsApp alert (repeated at most every 6 hours) with the exact
   fix — instead of discovering it from silent employees (20 Nov 2026: credit ran out and every manager stopped).
2) Arrival watch: every morning 07:45 Riyadh, shipments arriving in the next 48 hours (from tracking) with vessel,
   ETA, containers and the port free-days reminder, so the declaration and the trucks are ready before discharge.
"""
import asyncio
import datetime as dt
import json
import os
import time

RIYADH = dt.timezone(dt.timedelta(hours=3))
ALERT_EVERY = 6 * 3600
_last_alert = {'t': 0.0, 'kind': ''}
_failures = {'n': 0}


def probe():
    """Returns '' when healthy, else a short reason code."""
    import httpx
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key:
        return 'no_key'
    model = os.getenv('HEALTH_MODEL') or os.getenv('COMMAND_AGENT_MODEL') or os.getenv('COMMAND_AI_MODEL', 'claude-sonnet-5')
    try:
        with httpx.Client(timeout=40) as client:
            r = client.post('https://api.anthropic.com/v1/messages',
                            headers={'x-api-key': key, 'anthropic-version': '2023-06-01'},
                            json={'model': model, 'max_tokens': 1, 'messages': [{'role': 'user', 'content': 'ok'}]})
    except httpx.HTTPError:
        return 'network'
    if r.status_code == 200:
        return ''
    body = r.text.lower()
    if 'credit balance' in body:
        return 'credit'
    if r.status_code in (401, 403):
        return 'key'
    if r.status_code == 429:
        return ''  # busy is not down
    return f'http_{r.status_code}'


MESSAGES = {
    'credit': ('⚠️ تنبيه عاجل: رصيد Anthropic API خلص — كل موظفي الوكيل (فيصل، خالد، نورة، ريم…) وردود واتساب الذكية متوقفة الآن.\n'
               'الحل: اشحن الرصيد من https://console.anthropic.com/settings/billing وفعّل Auto-reload. يرجع الوكيل فور الشحن.'),
    'key': '⚠️ تنبيه عاجل: مفتاح Anthropic API مرفوض (401/403) — الموظفون متوقفون. راجع ANTHROPIC_API_KEY في Railway.',
    'no_key': '⚠️ تنبيه: لا يوجد ANTHROPIC_API_KEY على الخادم — الموظفون متوقفون.',
}


def health_tick(now=None):
    """Returns the alert text to send now, or ''."""
    now = now or time.time()
    reason = probe()
    if not reason:
        _failures['n'] = 0
        return ''
    _failures['n'] += 1
    print('AI_HEALTH', reason, _failures['n'], flush=True)
    if reason in ('network',) or reason.startswith('http_'):
        if _failures['n'] < 3:  # transient: alert only after 3 failed probes in a row (~1.5 h)
            return ''
        text = f'⚠️ تنبيه: خدمة الذكاء الاصطناعي تفشل منذ أكثر من ساعة ({reason}). الموظفون قد لا يردون؛ أتابعها.'
    else:
        text = MESSAGES[reason]
    if _last_alert['kind'] == reason and now - _last_alert['t'] < ALERT_EVERY:
        return ''
    _last_alert.update(t=now, kind=reason)
    return text


def arrivals_text(now=None):
    from app.storage import db
    now = now or dt.datetime.now(dt.timezone.utc)
    with db() as c:
        if not c.execute("SELECT to_regclass('shipment_tracks') t").fetchone()['t']:
            return ''
        rows = c.execute('''SELECT ref,vessel,voyage,pod,eta,containers,carrier FROM shipment_tracks
            WHERE NOT arrived AND eta IS NOT NULL AND eta BETWEEN %s AND %s ORDER BY eta''',
                         (now - dt.timedelta(hours=6), now + dt.timedelta(hours=48))).fetchall()
    if not rows:
        return ''
    lines = ['🚢 سلطان — شحنات تصل خلال 48 ساعة:']
    for r in rows:
        try:
            boxes = json.loads(r['containers'] or '[]')
        except ValueError:
            boxes = []
        eta = r['eta'].astimezone(RIYADH).strftime('%a %d/%m %H:%M')
        lines.append(f"• {r['ref']}" + (f" — {r['vessel']} {r.get('voyage') or ''}".rstrip() if r.get('vessel') else '')
                     + f" — الوصول {eta}" + (f" — {r['pod']}" if r.get('pod') else '') + (f' — {len(boxes)} حاوية' if boxes else ''))
    lines.append('تذكير: أرضيات الميناء مجانية 3 أيام من التنزيل — تأكد أن البيان مقدّم والنقل مرتب قبل الوصول. '
                 'للنقل اكتب لخالد: «جهّز نقل حاويات البوليصة <الرقم>».')
    return '\n'.join(lines)


def register_worker(app):
    async def loop():
        from starlette.concurrency import run_in_threadpool
        from app.owner_briefing import deliver
        await asyncio.sleep(240)
        last_probe, arrivals_day = 0.0, None
        while True:
            try:
                if os.getenv('AI_HEALTH_GUARD', '1') == '1' and time.time() - last_probe >= 1800:
                    last_probe = time.time()
                    text = await run_in_threadpool(health_tick)
                    if text:
                        await deliver(text)
                now = dt.datetime.now(RIYADH)
                if now.hour == 7 and now.minute >= 45 and arrivals_day != now.date():
                    arrivals_day = now.date()
                    text = await run_in_threadpool(arrivals_text)
                    if text:
                        await deliver(text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('OPS_WATCH', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(120)

    @app.on_event('startup')
    async def start():
        app.state.ops_watch_worker = asyncio.create_task(loop())
