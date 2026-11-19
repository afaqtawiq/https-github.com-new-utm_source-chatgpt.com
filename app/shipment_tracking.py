"""Live shipment tracking by bill of lading or container number (owner request, 19 Nov 2026).

«الوكيل ليش ما يعمل تتبع للشحنة لمعرفة مواعيد الوصول»: a document often has no arrival date (only the B/L issue
date). This asks a multi-carrier tracking service (ShipsGo API v2, 160+ ocean lines incl. CMA CGM, MSC, Maersk…) for
the vessel, ETD, ETA / actual discharge at the port of discharge, and:
- answers the team at once (command «تتبع البوليصة …», or automatically after a shipping document is read);
- writes the arrival date into the container desk (port storage + estimated last free day are recomputed);
- re-checks open shipments every 4 hours (re-reading costs no credit) and alerts the manager when the ETA moves by a
  day or more and when the containers are discharged.

Needs SHIPSGO_API_TOKEN (owner's ShipsGo account; each NEW shipment uses one paid credit — a B/L counts once for all
its containers). Without it nothing is called and the reply says tracking is not connected. SHIPMENT_TRACKING_AUTO=0
stops the automatic start after documents; SHIPMENT_TRACKING_DAILY_CAP (default 15) caps new automatic shipments.
Read-only towards carriers and customers: nothing is sent to anyone except the manager alerts.
"""
import asyncio
import datetime as dt
import json
import os
import re

import httpx

from app.storage import db, utcnow

BASE = 'https://api.shipsgo.com/v2'
RIYADH = dt.timezone(dt.timedelta(hours=3))
REFRESH_HOURS = 4
_READY = False
_CARRIERS = {'at': None, 'items': []}
_TOUCHED = {}

# Agent names used in the container desk → carrier SCAC (used to pick the carrier for a B/L).
SCAC = {'maersk': 'MAEU', 'msc': 'MSCU', 'cma cgm': 'CMDU', 'cosco': 'COSU', 'oocl': 'OOLU', 'hapag': 'HLCU',
        'one': 'ONEY', 'evergreen': 'EGLV', 'pil': 'PCIU', 'emirates': 'ESPU', 'yang ming': 'YMLU', 'hmm': 'HDMU',
        'zim': 'ZIMU', 'wan hai': 'WHLC', 'sealead': 'SJHH', 'gold star': 'GSLU'}
ARRIVAL_EVENTS = ('DISC', 'ARRV')


def token():
    return os.getenv('SHIPSGO_API_TOKEN', '').strip()


def enabled():
    return bool(token())


def auto_enabled():
    return enabled() and os.getenv('SHIPMENT_TRACKING_AUTO', '1') != '0'


def daily_cap():
    try:
        return max(0, int(os.getenv('SHIPMENT_TRACKING_DAILY_CAP', '15')))
    except ValueError:
        return 15


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS shipment_tracks(id BIGSERIAL PRIMARY KEY, ref TEXT NOT NULL UNIQUE,
            ref_type TEXT NOT NULL, carrier TEXT, provider_id TEXT, status TEXT NOT NULL DEFAULT 'new',
            vessel TEXT, voyage TEXT, pol TEXT, pod TEXT, etd TIMESTAMPTZ, eta TIMESTAMPTZ, arrived BOOLEAN NOT NULL DEFAULT FALSE,
            containers TEXT NOT NULL DEFAULT '[]', last_event TEXT, error TEXT, auto BOOLEAN NOT NULL DEFAULT FALSE,
            notified_eta TIMESTAMPTZ, notified_arrival BOOLEAN NOT NULL DEFAULT FALSE, created_by TEXT,
            created_at TIMESTAMPTZ NOT NULL, checked_at TIMESTAMPTZ)''')
    _READY = True


# ---------- references ----------

def ref_type(ref):
    from app.fasah_containers import check_digit_ok
    clean = re.sub(r'[^A-Z0-9]', '', str(ref or '').upper())
    if re.fullmatch(r'[A-Z]{4}\d{7}', clean) and check_digit_ok(clean):
        return clean, 'container'
    if 6 <= len(clean) <= 20 and re.search(r'\d{4}', clean):
        return clean, 'bl'
    return None, None


def scac_for(name):
    n = str(name or '').casefold()
    for key, code in SCAC.items():
        if re.search(r'(?<![a-z])' + re.escape(key) + r'(?![a-z])', n):
            return code
    return None


async def _carrier_code(client, carrier_name):
    """ShipsGo's own carrier code for a carrier name/SCAC (looked up once a day); None lets ShipsGo detect it."""
    scac = scac_for(carrier_name) or (carrier_name if re.fullmatch(r'[A-Z]{4}', str(carrier_name or '')) else None)
    if not carrier_name:
        return None
    now = utcnow()
    if not _CARRIERS['at'] or now - _CARRIERS['at'] > dt.timedelta(days=1):
        try:
            r = await client.get(BASE + '/ocean/carriers', params={'take': 500})
            r.raise_for_status()
            data = r.json()
            _CARRIERS['items'] = _dicts(data)
            _CARRIERS['at'] = now
        except (httpx.HTTPError, ValueError) as exc:
            print('SHIPSGO_CARRIERS_FAILED', type(exc).__name__, str(exc)[:120], flush=True)
    name = str(carrier_name).casefold()
    for item in _CARRIERS['items']:
        scacs = item.get('scac') or item.get('scacs') or []
        scacs = [scacs] if isinstance(scacs, str) else scacs
        if (scac and scac in scacs) or name == str(item.get('name') or '').casefold():
            return item.get('code') or item.get('id')
    return None


def _dicts(data):
    """Every list of dicts inside a JSON response (carrier lists come wrapped differently)."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for v in data.values():
            found = _dicts(v)
            if found:
                return found
    return []


# ---------- provider calls ----------

def _client():
    return httpx.AsyncClient(timeout=30, headers={'X-Shipsgo-User-Token': token(), 'Accept': 'application/json'})


def _shipment_id(data):
    if isinstance(data, dict):
        ship = data.get('shipment') if isinstance(data.get('shipment'), dict) else data
        if ship.get('id') not in (None, ''):
            return str(ship['id'])
        for v in data.values():
            found = _shipment_id(v) if isinstance(v, dict) else None
            if found:
                return found
    return None


async def _create(client, ref, kind, carrier_name):
    body = {'container_number': ref} if kind == 'container' else {'booking_number': ref}
    code = await _carrier_code(client, carrier_name)
    if code:
        body['carrier'] = code
    r = await client.post(BASE + '/ocean/shipments', json=body)
    if r.status_code == 409:  # already tracked on this account: find it instead of paying again
        found = _shipment_id(r.json()) if r.content else None
        return found or await _find(client, ref)
    if r.status_code in (400, 404, 422):
        raise ValueError(_provider_message(r) or 'رفضت خدمة التتبع الرقم؛ تأكد من رقم البوليصة والخط الملاحي.')
    if r.status_code == 402:
        raise ValueError('رصيد التتبع في ShipsGo انتهى؛ اشحن الرصيد من حسابك ثم أعد الطلب.')
    r.raise_for_status()
    return _shipment_id(r.json())


async def _find(client, ref):
    r = await client.get(BASE + '/ocean/shipments', params={'take': 100})
    r.raise_for_status()
    for item in _dicts(r.json()):
        if ref in (str(item.get('booking_number') or '').upper(), str(item.get('container_number') or '').upper()):
            return str(item.get('id'))
    return None


def _provider_message(r):
    try:
        data = r.json()
    except ValueError:
        return ''
    msg = data.get('message') if isinstance(data, dict) else ''
    return ('خدمة التتبع: ' + str(msg)[:200]) if msg else ''


async def _get(client, provider_id):
    r = await client.get(BASE + '/ocean/shipments/' + str(provider_id))
    r.raise_for_status()
    data = r.json()
    return data.get('shipment') if isinstance(data, dict) and isinstance(data.get('shipment'), dict) else data


# ---------- reading a shipment ----------

def _when(value):
    try:
        at = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=RIYADH)


def _place(loc):
    if not isinstance(loc, dict):
        return str(loc or '')
    return ' '.join(x for x in (str(loc.get('name') or ''), '(' + str(loc.get('code')) + ')' if loc.get('code') else '') if x)


def parse(ship):
    """Summary of one ShipsGo shipment: vessel, POL/POD, ETD, ETA (or actual discharge), containers, status."""
    moves = []
    containers = []
    for cont in ship.get('containers') or []:
        if not isinstance(cont, dict):
            continue
        if cont.get('number'):
            containers.append({'number': str(cont['number']).upper(), 'size': cont.get('size'), 'type': cont.get('type')})
        for m in cont.get('movements') or []:
            if isinstance(m, dict) and _when(m.get('timestamp')):
                moves.append(m)
    moves.sort(key=lambda m: _when(m['timestamp']))
    loads = [m for m in moves if m.get('event') == 'LOAD']
    arrivals = [m for m in moves if m.get('event') in ARRIVAL_EVENTS]
    final = arrivals[-1] if arrivals else None
    if final:  # the discharge at the final port beats the vessel arrival there
        same = [m for m in arrivals if _place(m.get('location')) == _place(final.get('location'))]
        disc = [m for m in same if m.get('event') == 'DISC']
        final = disc[-1] if disc else same[-1]
    actual = [m for m in moves if m.get('status') == 'ACT']
    vessel_from = final or (loads[-1] if loads else None)
    return {
        'status': str(ship.get('status') or ''),
        'carrier': str((ship.get('carrier') or {}).get('name') or '') if isinstance(ship.get('carrier'), dict) else str(ship.get('carrier') or ''),
        'pol': _place(loads[0].get('location')) if loads else '',
        'etd': _when(loads[0]['timestamp']) if loads else None,
        'pod': _place(final.get('location')) if final else '',
        'eta': _when(final['timestamp']) if final else None,
        'arrived': bool(final and final.get('status') == 'ACT'),
        'vessel': str(((vessel_from or {}).get('vessel') or {}).get('name') or '') if isinstance((vessel_from or {}).get('vessel'), dict) else '',
        'voyage': str((vessel_from or {}).get('voyage') or ''),
        'last_event': (f"{actual[-1].get('event')} — {_place(actual[-1].get('location'))} — {_when(actual[-1]['timestamp']).astimezone(RIYADH).strftime('%d/%m/%Y')}"
                       if actual else ''),
        'containers': containers,
    }


EVENT_AR = {'LOAD': 'تحميل على السفينة', 'DISC': 'تفريغ', 'ARRV': 'وصول السفينة', 'DEPA': 'مغادرة السفينة',
            'GTIN': 'دخول البوابة', 'GTOT': 'خروج من البوابة', 'EMSH': 'استلام الفارغ', 'EMRT': 'إرجاع الفارغ'}


def _d(at):
    return at.astimezone(RIYADH).strftime('%d/%m/%Y') if at else '—'


def reply_text(ref, info):
    status = 'وصلت وتفرغت ✅' if info['arrived'] else ('في الطريق 🚢' if info['etd'] else 'بانتظار التحميل')
    lines = [f'🔎 تتبع {ref}' + (f" — {info['carrier']}" if info['carrier'] else '') + f': {status}']
    if info['vessel']:
        lines.append(f"• السفينة: {info['vessel']}" + (f" / رحلة {info['voyage']}" if info['voyage'] else ''))
    if info['pol']:
        lines.append(f"• التحميل: {info['pol']} — {_d(info['etd'])}")
    if info['pod']:
        lines.append(f"• {'التفريغ الفعلي' if info['arrived'] else 'الوصول المتوقع (ETA)'}: {info['pod']} — {_d(info['eta'])}")
    if info['last_event']:
        code = info['last_event'].split(' — ')[0]
        lines.append('• آخر حدث مؤكد: ' + info['last_event'].replace(code, EVENT_AR.get(code, code), 1))
    if info['containers']:
        lines.append('• الحاويات: ' + '، '.join(c['number'] for c in info['containers'][:20]))
    if not info['pod'] and not info['etd']:
        lines.append('لم تُنشر مواعيد بعد عند الخط؛ أتابعها كل 4 ساعات وأبلغك عند ظهورها.')
    else:
        lines.append('أتابعها كل 4 ساعات وأبلغك إذا تغير الموعد يومًا أو أكثر، وعند التفريغ.')
    return '\n'.join(lines)


# ---------- container desk ----------

def apply_to_desk(c, ref, kind, info):
    """Write the arrival date into the container desk for this B/L's (or container's) rows; recompute the estimated
    last free day from the agent's free days. Returns the number of containers touched."""
    if not info.get('eta'):
        return 0
    from app import line_desk
    line_desk.init()
    eta = info['eta'].astimezone(RIYADH).date()
    numbers = [x['number'] for x in info.get('containers') or []]
    if kind == 'container':
        numbers = list(dict.fromkeys(numbers + [ref]))
    rows = c.execute('''SELECT * FROM container_returns WHERE status NOT IN ('returned','closed')
        AND (container = ANY(%s) OR (%s <> '' AND upper(coalesce(bill,'')) = %s))''',
                     (numbers or ['-'], ref if kind == 'bl' else '', ref)).fetchall()
    touched = 0
    for r in rows:
        free_until, estimated = r.get('free_until'), r.get('free_until_estimated')
        if (not free_until or estimated) and r.get('agent_id'):
            days = line_desk.free_days_for(c, r['agent_id'])
            if days:
                free_until, estimated = eta + dt.timedelta(days=days - 1), True
        c.execute('''UPDATE container_returns SET arrived_on=%s, free_until=%s, free_until_estimated=%s WHERE id=%s''',
                  (eta, free_until, bool(estimated) if free_until else r.get('free_until_estimated'), r['id']))
        touched += 1
    return touched


# ---------- public entry points ----------

def _save(ref, kind, carrier, info=None, provider_id=None, error=None, actor='', auto=False):
    init()
    with db() as c:
        row = c.execute('''INSERT INTO shipment_tracks(ref,ref_type,carrier,provider_id,status,created_by,auto,created_at)
            VALUES(%s,%s,%s,%s,'new',%s,%s,%s) ON CONFLICT(ref) DO UPDATE SET
              provider_id=COALESCE(EXCLUDED.provider_id, shipment_tracks.provider_id),
              carrier=COALESCE(NULLIF(EXCLUDED.carrier,''), shipment_tracks.carrier) RETURNING *''',
                        (ref, kind, carrier or '', provider_id, actor, auto, utcnow())).fetchone()
        if info is not None:
            c.execute('''UPDATE shipment_tracks SET status=%s, vessel=%s, voyage=%s, pol=%s, pod=%s, etd=%s, eta=%s, arrived=%s,
                containers=%s, last_event=%s, error=NULL, checked_at=%s,
                notified_eta=COALESCE(notified_eta,%s) WHERE id=%s''',
                      ('arrived' if info['arrived'] else 'tracking', info['vessel'], info['voyage'], info['pol'], info['pod'],
                       info['etd'], info['eta'], info['arrived'], json.dumps(info['containers']), info['last_event'],
                       utcnow(), info['eta'], row['id']))
            touched = apply_to_desk(c, ref, kind, info)
            if touched and info.get('eta'):
                _TOUCHED[ref] = touched
        elif error:
            c.execute("UPDATE shipment_tracks SET error=%s, checked_at=%s WHERE id=%s", (error[:300], utcnow(), row['id']))
        return c.execute('SELECT * FROM shipment_tracks WHERE id=%s', (row['id'],)).fetchone()


def existing(ref):
    init()
    with db() as c:
        return c.execute('SELECT * FROM shipment_tracks WHERE ref=%s', (ref,)).fetchone()


def started_today():
    init()
    start = dt.datetime.combine(utcnow().astimezone(RIYADH).date(), dt.time(0), RIYADH)
    with db() as c:
        return c.execute('SELECT COUNT(*) n FROM shipment_tracks WHERE auto AND created_at >= %s', (start,)).fetchone()['n']


async def track(ref, carrier='', actor='', auto=False):
    """Start (or refresh) tracking for a B/L or container and return the Arabic reply."""
    clean, kind = ref_type(ref)
    if not clean:
        return 'اكتب رقم بوليصة الشحن أو رقم الحاوية (4 حروف و7 أرقام) للتتبع.'
    if not enabled():
        return ('🔎 التتبع المباشر للبوليصة غير مفعّل بعد: يحتاج ربط حساب خدمة تتبع (ShipsGo) بالمنصة '
                '— متغير SHIPSGO_API_TOKEN في Railway. بعد الربط أتابع كل بوليصة تلقائيًا وأبلغك بموعد الوصول وتغيراته.')
    old = existing(clean)
    if auto and not old and started_today() >= daily_cap():
        return f'🔎 لم أبدأ تتبع {clean} تلقائيًا: وصلت الحد اليومي للتتبع الآلي ({daily_cap()}). اكتب «تتبع البوليصة {clean}» لتتبعها الآن.'
    try:
        async with _client() as client:
            provider_id = (old or {}).get('provider_id') or await _create(client, clean, kind, carrier)
            if not provider_id:
                raise ValueError('لم تُرجع خدمة التتبع رقم متابعة للشحنة؛ أعد المحاولة بعد قليل.')
            info = parse(await _get(client, provider_id))
    except ValueError as exc:
        _save(clean, kind, carrier, error=str(exc), actor=actor, auto=auto)
        return '🔎 ' + str(exc)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        msg = ('رمز ربط ShipsGo غير صحيح أو منتهي؛ حدّثه في Railway.' if code in (401, 403)
               else 'خدمة التتبع مشغولة الآن؛ أعيد المحاولة تلقائيًا.' if code == 429 or code >= 500
               else f'تعذر التتبع الآن (HTTP {code}).')
        _save(clean, kind, carrier, error=msg, actor=actor, auto=auto)
        return '🔎 ' + msg
    except httpx.HTTPError as exc:
        _save(clean, kind, carrier, error=type(exc).__name__, actor=actor, auto=auto)
        return '🔎 تعذر الاتصال بخدمة التتبع الآن؛ أعيد المحاولة تلقائيًا.'
    _TOUCHED.pop(clean, None)
    _save(clean, kind, carrier, info=info, provider_id=provider_id, actor=actor, auto=auto)
    touched = _TOUCHED.pop(clean, 0)
    return reply_text(clean, info) + (f'\n• حدّثت تاريخ النزول وآخر يوم مجاني لـ{touched} حاوية في مكتب الحاويات.' if touched else '')


async def after_document(fields):
    """Called after a shipping document was read: start tracking its B/L (or first container) when the document has
    no arrival date, or confirm it when it has one. Returns an extra reply line, or ''."""
    ref = fields.get('bill_no') or next(iter(fields.get('container_numbers') or []), '')
    clean, _ = ref_type(ref)
    if not clean:
        return ''
    if not enabled():
        return '' if fields.get('eta') else ('• موعد الوصول غير مكتوب في المستند، والتتبع المباشر غير مفعّل بعد '
                                             '(يحتاج ربط ShipsGo بالمنصة).')
    if not auto_enabled():
        return '' if fields.get('eta') else f'• لمعرفة موعد الوصول اكتب: «تتبع البوليصة {clean}».'
    return await track(clean, fields.get('shipping_line') or '', 'مستند ملاحي', auto=True)


# ---------- refresh worker ----------

def due_tracks(now):
    init()
    with db() as c:
        return c.execute('''SELECT * FROM shipment_tracks WHERE provider_id IS NOT NULL
            AND (NOT arrived OR checked_at < eta + INTERVAL '2 days')
            AND created_at > %s AND (checked_at IS NULL OR checked_at < %s) ORDER BY checked_at NULLS FIRST LIMIT 40''',
                         (now - dt.timedelta(days=90), now - dt.timedelta(hours=REFRESH_HOURS))).fetchall()


def change_alerts(row, info):
    """Manager alerts for one refreshed shipment: ETA moved by ≥1 day, or containers discharged."""
    out = []
    old = row.get('notified_eta')
    if info['arrived'] and not row.get('notified_arrival'):
        out.append(f"✅ وصلت شحنة البوليصة {row['ref']} وتفرغت في {info['pod'] or 'ميناء التفريغ'} يوم {_d(info['eta'])}. "
                   'حدّثت تاريخ النزول في مكتب الحاويات (الأرضيات وأيام السماح تُحسب منه الآن).')
    elif info['eta'] and old and abs((info['eta'] - old).total_seconds()) >= 86400:
        later = info['eta'] > old
        out.append(f"{'⚠️ تأخر' if later else 'ℹ️ تقدّم'} موعد وصول البوليصة {row['ref']}: من {_d(old)} إلى {_d(info['eta'])}"
                   + (f" — {info['vessel']}" if info['vessel'] else '') + '.')
    elif info['eta'] and not old:
        out.append(f"🚢 ظهر موعد وصول البوليصة {row['ref']}: {_d(info['eta'])} ({info['pod']}).")
    return out


async def refresh(now=None, deliver=None):
    if not enabled():
        return []
    from starlette.concurrency import run_in_threadpool
    if deliver is None:
        from app.owner_briefing import deliver
    now = now or utcnow()
    sent = []
    async with _client() as client:
        for row in await run_in_threadpool(due_tracks, now):
            try:
                info = parse(await _get(client, row['provider_id']))
            except (httpx.HTTPError, ValueError) as exc:
                await run_in_threadpool(_mark_error, row['id'], type(exc).__name__)
                continue
            alerts = change_alerts(row, info)
            await run_in_threadpool(_save, row['ref'], row['ref_type'], row['carrier'], info, row['provider_id'])
            if alerts:
                await run_in_threadpool(_notified, row['id'], info)
                for text in alerts:
                    await deliver(text)
                    sent.append(text)
    return sent


def _mark_error(rid, error):
    with db() as c:
        c.execute('UPDATE shipment_tracks SET error=%s, checked_at=%s WHERE id=%s', (error, utcnow(), rid))


def _notified(rid, info):
    with db() as c:
        c.execute('UPDATE shipment_tracks SET notified_eta=%s, notified_arrival=(notified_arrival OR %s) WHERE id=%s',
                  (info['eta'], info['arrived'], rid))


def list_text():
    init()
    with db() as c:
        rows = c.execute('''SELECT * FROM shipment_tracks WHERE NOT arrived OR eta > NOW() - INTERVAL '5 days'
            ORDER BY eta NULLS LAST LIMIT 25''').fetchall()
    if not rows:
        return 'لا توجد شحنات قيد التتبع.' + ('' if enabled() else ' (التتبع المباشر غير مفعّل بعد.)')
    lines = ['🚢 الشحنات قيد التتبع:']
    for r in rows:
        state = 'تفرغت' if r['arrived'] else ('ETA ' + _d(r['eta']) if r['eta'] else ('خطأ: ' + r['error'] if r['error'] else 'بانتظار المواعيد'))
        lines.append(f"• {r['ref']}" + (f" ({r['vessel']})" if r['vessel'] else '') + f' — {state}')
    return '\n'.join(lines)


def register_worker(app):
    async def loop():
        await asyncio.sleep(500)
        while True:
            try:
                await refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('SHIPMENT_TRACKING', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(1800)

    @app.on_event('startup')
    async def _start():
        init()
        app.state.shipment_tracking_task = asyncio.create_task(loop())
