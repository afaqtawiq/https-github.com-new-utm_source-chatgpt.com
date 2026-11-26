"""Free official tracking through the shipping lines' own APIs (owner, 25 Nov 2026: «ابحث عن بدائل تتبع مجاني»).

The lines' websites block the work computer (blank page / captcha), but CMA CGM, Maersk and Hapag-Lloyd publish a free
Track & Trace API on the open DCSA standard (one parser for all), and Ship24 has a free monthly allowance for other
lines. The manager pastes each portal key once on /settings/tracking (stored encrypted, never shown again); a test
button checks a key against a real reference. Read-only: GET/track calls only, nothing is booked or changed.
"""
import base64
import datetime as dt
import hashlib
import json
import os
import re

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.storage import db, utcnow

router = APIRouter()
PATH = '/settings/tracking'
JEDDAH = ('SAJED', 'SAJEDD')
# Defaults from each portal's DCSA Track & Trace product; the page lets the manager correct the address / header names
# exactly as his portal shows them.
PROVIDERS = {
    'FIRECRAWL': {'name': 'Firecrawl — قارئ صفحات التتبع (يعمل مع كل الخطوط)', 'portal': 'https://www.firecrawl.dev/app/api-keys',
                  'url': 'https://api.firecrawl.dev/v2/scrape', 'key_header': 'Authorization', 'secret_header': ''},
    'CMDU': {'name': 'CMA CGM (ومعها APL و ANL)', 'portal': 'https://api-portal.cma-cgm.com',
             'url': 'https://apis.cma-cgm.net/operation/trackandtrace/v1/events', 'key_header': 'KeyId', 'secret_header': ''},
    'MAEU': {'name': 'Maersk', 'portal': 'https://developer.maersk.com',
             'url': 'https://api.maersk.com/track-and-trace-private/events', 'key_header': 'Consumer-Key', 'secret_header': ''},
    'HLCU': {'name': 'Hapag-Lloyd', 'portal': 'https://api-portal.hlag.com',
             'url': 'https://api.hlag.com/hlag/external/v2/events/', 'key_header': 'X-IBM-Client-Id',
             'secret_header': 'X-IBM-Client-Secret'},
    'SHIP24': {'name': 'Ship24 (باقي الخطوط — 10 شحنات مجانية شهريًا)', 'portal': 'https://www.ship24.com/tracking-api',
               'url': 'https://api.ship24.com/public/v1/trackers/track', 'key_header': 'Authorization', 'secret_header': ''},
}


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS carrier_api_keys(code TEXT PRIMARY KEY, key_enc TEXT NOT NULL,
            secret_enc TEXT NOT NULL DEFAULT '', url TEXT NOT NULL, key_header TEXT NOT NULL, secret_header TEXT NOT NULL DEFAULT '',
            last_test TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ NOT NULL, updated_by BIGINT)''')


def _cipher():
    raw = os.getenv('TOKEN_ENCRYPTION_KEY', '').strip()
    if not raw:
        raise ValueError('تشفير المفاتيح غير مهيأ على الخادم؛ لم يُحفظ شيء.')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('afaaq-carrier-api:' + raw).encode()).digest()))


def save(code, key, secret='', url='', key_header='', secret_header='', user_id=None):
    if code not in PROVIDERS:
        raise ValueError('خط غير معروف.')
    d = PROVIDERS[code]
    url = (url or d['url']).strip()
    if not re.fullmatch(r'https://[A-Za-z0-9.\-]+(/[A-Za-z0-9._~/\-]*)?', url):
        raise ValueError('عنوان الربط يجب أن يبدأ بـ https:// وبدون رموز غريبة.')
    for h in (key_header, secret_header):
        if h and not re.fullmatch(r'[A-Za-z0-9\-]{2,40}', h):
            raise ValueError('اسم الخانة في الطلب (Header) غير صالح.')
    if not 8 <= len(key) <= 600 or any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
        raise ValueError('الصق المفتاح كاملًا بدون مسافات.')
    f = _cipher()
    init()
    with db() as c:
        c.execute('''INSERT INTO carrier_api_keys(code,key_enc,secret_enc,url,key_header,secret_header,updated_at,updated_by)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(code) DO UPDATE SET key_enc=EXCLUDED.key_enc,
            secret_enc=CASE WHEN EXCLUDED.secret_enc<>'' THEN EXCLUDED.secret_enc ELSE carrier_api_keys.secret_enc END,
            url=EXCLUDED.url,key_header=EXCLUDED.key_header,secret_header=EXCLUDED.secret_header,last_test='',
            updated_at=EXCLUDED.updated_at,updated_by=EXCLUDED.updated_by''',
                  (code, f.encrypt(key.encode()).decode(), f.encrypt(secret.encode()).decode() if secret else '', url,
                   key_header or d['key_header'], secret_header if secret_header is not None else d['secret_header'], utcnow(), user_id))


def _conn(code):
    init()
    with db() as c:
        row = c.execute('SELECT * FROM carrier_api_keys WHERE code=%s', (code,)).fetchone()
    if not row:
        return None
    try:
        f = _cipher()
        return dict(row, key=f.decrypt(row['key_enc'].encode()).decode(),
                    secret=f.decrypt(row['secret_enc'].encode()).decode() if row['secret_enc'] else '')
    except (InvalidToken, ValueError):
        return None


def configured():
    init()
    with db() as c:
        return {r['code'] for r in c.execute('SELECT code FROM carrier_api_keys').fetchall()}


# ---------- DCSA events → the tracking fields used everywhere else ----------

def _iso(v):
    try:
        at = dt.datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return at.date().isoformat()
    except ValueError:
        return None


def parse_dcsa(events, ref, bl_pod=''):
    """DCSA Track & Trace 2.x events → {found, vessel, voyage, pol, etd, pod, eta, discharged, containers, last_event}.
    The port is the B/L port of discharge when known; «discharged» is only the container's ACTUAL discharge (equipment
    event DISC, classifier ACT) at that port — a vessel arrival there or anywhere else is not an arrival."""
    from app.shipment_tracking import port_code
    events = [e for e in events if isinstance(e, dict)]
    if not events:
        return {'found': False, 'reason': 'لا توجد أحداث لهذا الرقم عند الخط'}

    def when(e):
        return str(e.get('eventDateTime') or e.get('eventCreatedDateTime') or '')
    events.sort(key=when)
    calls = []
    for e in events:
        tc = e.get('transportCall') if isinstance(e.get('transportCall'), dict) else {}
        loc = tc.get('location') if isinstance(tc.get('location'), dict) else {}
        code = str(tc.get('UNLocationCode') or loc.get('UNLocationCode') or '').upper()
        vessel = tc.get('vessel') if isinstance(tc.get('vessel'), dict) else {}
        calls.append({'code': code, 'name': loc.get('locationName') or code, 'vessel': vessel.get('vesselName') or '',
                      'voyage': tc.get('exportVoyageNumber') or tc.get('importVoyageNumber') or tc.get('carrierExportVoyageNumber') or '',
                      'equipment': e.get('eventType') == 'EQUIPMENT' or bool(e.get('equipmentEventTypeCode')),
                      'type': e.get('transportEventTypeCode') or e.get('equipmentEventTypeCode') or e.get('shipmentEventTypeCode') or '',
                      'cls': e.get('eventClassifierCode') or '', 'at': when(e), 'equip': e.get('equipmentReference') or ''})
    loads = [c for c in calls if c['type'] in ('LOAD', 'DEPA') and c['code']]
    discs = [c for c in calls if c['type'] == 'DISC' and c['equipment'] and c['code']]
    arrivals = [c for c in calls if c['type'] in ('ARRI', 'DISC') and c['code']]
    want = port_code(bl_pod)
    pod_code = want or (discs[-1]['code'] if discs else (arrivals[-1]['code'] if arrivals else ''))
    actual = [c for c in discs if c['code'] == pod_code and c['cls'] == 'ACT']
    planned = [c for c in arrivals if c['code'] == pod_code and c['cls'] in ('EST', 'PLN')]
    at_pod = [c for c in arrivals if c['code'] == pod_code]
    pod_name = (at_pod[-1]['name'] if at_pod else '') or bl_pod
    with_vessel = [c for c in calls if c['vessel']]
    acts = [c for c in calls if c['cls'] == 'ACT' and c['type']]
    last = acts[-1] if acts else None
    return {'found': bool(calls), 'carrier': '', 'vessel': (with_vessel[-1]['vessel'] if with_vessel else ''),
            'voyage': next((c['voyage'] for c in reversed(calls) if c['voyage']), ''),
            'pol': loads[0]['name'] if loads else '', 'etd': _iso(loads[0]['at']) if loads else None,
            'pod': pod_name, 'eta': _iso(planned[-1]['at']) if planned else (_iso(actual[-1]['at']) if actual else None),
            'discharged': _iso(actual[-1]['at']) if actual else None,
            'containers': sorted({c['equip'] for c in calls if c['equip']}),
            'last_event': (f"{last['type']} {last['name']}" if last else ''), 'last_event_date': _iso(last['at']) if last else None}


def parse_ship24(data, ref):
    trackings = (((data or {}).get('data') or {}).get('trackings') or []) if isinstance(data, dict) else []
    if not trackings:
        return {'found': False, 'reason': 'لم تجد Ship24 بيانات لهذا الرقم'}
    t = trackings[0]
    ship = t.get('shipment') or {}
    events = sorted((e for e in t.get('events') or [] if isinstance(e, dict)), key=lambda e: str(e.get('occurrenceDatetime') or ''))
    delivery = ship.get('delivery') or {}
    last = events[-1] if events else {}
    return {'found': bool(events or delivery.get('estimatedDeliveryDate')), 'vessel': '', 'voyage': '',
            'pol': str((ship.get('recipient') or {}).get('address') or '')[:0], 'etd': None,
            'pod': str(((ship.get('recipient') or {}).get('address') or {}).get('city') or '') if isinstance((ship.get('recipient') or {}).get('address'), dict) else '',
            'eta': _iso(delivery.get('estimatedDeliveryDate')) if delivery.get('estimatedDeliveryDate') else None,
            'discharged': None, 'containers': [],  # Ship24 milestones are not a confirmed container discharge
            'last_event': str(last.get('status') or '')[:120] + (' — ' + str(last.get('location')) if last.get('location') else ''),
            'last_event_date': _iso(last.get('occurrenceDatetime')) if last.get('occurrenceDatetime') else None}


async def lookup(code, ref, kind, bl_pod=''):
    """Fields for `ref` from the line's own API (or Ship24), or None when no key is saved for it. Raises ValueError with
    an Arabic reason when the API refuses."""
    if code == 'FIRECRAWL':
        return None
    conn = _conn(code) or (_conn('SHIP24') if code != 'SHIP24' else None)
    if not conn:
        return None
    async with httpx.AsyncClient(timeout=30) as client:
        if conn['code'] == 'SHIP24':
            r = await client.post(conn['url'], json={'trackingNumber': ref},
                                  headers={'Authorization': 'Bearer ' + conn['key'], 'Accept': 'application/json'})
            _raise(r, 'Ship24')
            return parse_ship24(r.json(), ref)
        headers = {conn['key_header']: conn['key'], 'Accept': 'application/json'}
        if conn['secret_header'] and conn['secret']:
            headers[conn['secret_header']] = conn['secret']
        param = 'equipmentReference' if kind == 'container' else 'transportDocumentReference'
        r = await client.get(conn['url'], params={param: ref, 'limit': 100}, headers=headers)
        _raise(r, PROVIDERS[conn['code']]['name'])
        data = r.json()
        events = data if isinstance(data, list) else (data.get('events') or data.get('data') or []) if isinstance(data, dict) else []
        out = parse_dcsa(events, ref, bl_pod)
        out['carrier'] = PROVIDERS[conn['code']]['name'].split(' (')[0]
        return out


def _raise(r, name):
    if r.status_code in (401, 403):
        raise ValueError(f'مفتاح {name} غير مقبول (HTTP {r.status_code}) — تأكد من المفتاح واسم الخانة في صفحة مفاتيح التتبع.')
    if r.status_code == 404:
        raise ValueError(f'{name}: الرقم غير موجود عند الخط (قد تكون البوليصة مسودة لم تُصدر بعد).')
    if r.status_code == 429:
        raise ValueError(f'{name}: تجاوزنا عدد الطلبات المسموح؛ أعيد المحاولة لاحقًا.')
    r.raise_for_status()


# ---------- settings page ----------

def _admin(request):
    from app.social_content import auth
    session = auth(request)
    if session.get('role') != 'admin':
        raise HTTPException(403, 'مفاتيح التتبع للإدارة فقط.')
    return session


def _page(session, note=''):
    from app.social_content import e, page
    from app.social_publishing import hidden_csrf
    init()
    with db() as c:
        rows = {r['code']: r for r in c.execute('SELECT code,url,key_header,secret_header,last_test,updated_at FROM carrier_api_keys').fetchall()}
    body = '<div class="hero"><h1>مفاتيح التتبع المجاني</h1><p>ربط رسمي مع الخطوط الملاحية — قراءة فقط</p></div>'
    if note:
        body += '<div class="card" role="status">' + e(note) + '</div>'
    body += ('<div class="card"><p>ادخل بوابة كل خط بحساب آفاق طويق، افتح قسم المفاتيح (API Keys / Apps)، اشترك في خدمة '
             '<b>Track &amp; Trace</b>، وانسخ المفتاح هنا. يُحفظ مشفرًا ولا يظهر مرة ثانية.</p></div>')
    for code, d in PROVIDERS.items():
        row = rows.get(code)
        body += '<div class="card"><h2>' + e(d['name']) + '</h2>'
        body += '<p>البوابة: <a href="' + e(d['portal']) + '" target="_blank" rel="noopener">' + e(d['portal']) + '</a></p>'
        if row:
            body += '<p class="ok">✅ المفتاح محفوظ — آخر حفظ ' + e(str(row['updated_at'])[:16]) + '</p>'
            if row['last_test']:
                body += '<p>آخر فحص: ' + e(row['last_test']) + '</p>'
        body += '<form method="post" action="' + PATH + '">' + hidden_csrf(session) + '<input type="hidden" name="code" value="' + code + '">'
        body += '<label>المفتاح<input name="key" type="password" dir="ltr" autocomplete="off" required minlength="8" maxlength="600"></label>'
        if d['secret_header'] or code == 'HLCU':
            body += '<label>المفتاح السري (Client Secret)<input name="secret" type="password" dir="ltr" autocomplete="off" maxlength="600"></label>'
        body += ('<details><summary>إعدادات متقدمة (عدّلها فقط إذا البوابة تذكر غيرها)</summary>'
                 '<label>عنوان الربط<input name="url" dir="ltr" value="' + e((row or {}).get('url') or d['url']) + '"></label>'
                 '<label>اسم خانة المفتاح<input name="key_header" dir="ltr" value="' + e((row or {}).get('key_header') or d['key_header']) + '"></label>'
                 + ('<label>اسم خانة السر<input name="secret_header" dir="ltr" value="' + e((row or {}).get('secret_header') or d['secret_header']) + '"></label>'
                    if d['secret_header'] else '') + '</details>')
        body += '<button class="btn">حفظ المفتاح</button></form>'
        if row:
            body += ('<form method="post" action="' + PATH + '/test">' + hidden_csrf(session) + '<input type="hidden" name="code" value="' + code + '">'
                     '<label>رقم بوليصة أو حاوية للفحص<input name="ref" dir="ltr" required maxlength="20"></label>'
                     '<button class="btn">فحص الربط</button></form>')
        body += '</div>'
    from fastapi.responses import HTMLResponse as H
    return H(page(body), headers={'Cache-Control': 'no-store'})


@router.get(PATH, response_class=HTMLResponse)
def settings_page(request: Request):
    return _page(_admin(request))


async def _form(request, session):
    from app.social_content import parse
    from app.social_publishing import csrf
    raw = await request.body()
    if len(raw) > 6000:
        raise HTTPException(413)
    data = parse(raw)
    csrf(session, data)
    return data


@router.post(PATH)
async def settings_save(request: Request):
    session = _admin(request)
    data = await _form(request, session)
    try:
        save(data.get('code', ''), data.get('key', '').strip(), data.get('secret', '').strip(), data.get('url', ''),
             data.get('key_header', '').strip(), data.get('secret_header', '').strip() if 'secret_header' in data else None,
             session.get('user_id'))
    except ValueError as exc:
        return _page(session, str(exc))
    return RedirectResponse(PATH, 303, headers={'Cache-Control': 'no-store'})


@router.post(PATH + '/test')
async def settings_test(request: Request):
    session = _admin(request)
    data = await _form(request, session)
    from app.shipment_tracking import ref_type
    code = data.get('code', '')
    ref, kind = ref_type(data.get('ref', ''))
    if code not in PROVIDERS or not ref:
        return _page(session, 'اكتب رقم بوليصة أو حاوية صحيح.')
    try:
        if code == 'FIRECRAWL':  # the page reader: run the full tracking read for this reference (line from its prefix)
            from starlette.concurrency import run_in_threadpool
            from app.shipment_tracking import api_fields, hints_for
            hints = await run_in_threadpool(hints_for, ref)
            got, why = await api_fields(ref, kind, hints.get('carrier') or '', hints)
            got = got or {'found': False, 'reason': why}
        else:
            got = await lookup(code, ref, kind)
        if got is None:
            result = 'لا يوجد مفتاح محفوظ.'
        elif got.get('found'):
            result = (f"✅ يعمل — {ref}: السفينة {got.get('vessel') or '—'}، الوصول المتوقع {got.get('eta') or '—'}"
                      f"{'، التفريغ الفعلي ' + got['discharged'] if got.get('discharged') else ''}، آخر حدث {got.get('last_event') or '—'}")
        else:
            result = f"المفتاح مقبول لكن: {got.get('reason')}"
    except ValueError as exc:
        result = '⚠️ ' + str(exc)
    except httpx.HTTPError as exc:
        result = f'⚠️ تعذر الاتصال ({type(exc).__name__})'
    with db() as c:
        c.execute('UPDATE carrier_api_keys SET last_test=%s WHERE code=%s', (f"{dt.datetime.now(dt.timezone(dt.timedelta(hours=3))):%d/%m %H:%M} — {result}"[:300], code))
    return _page(session, result)


def describe():
    """For the manager: which free connections are active."""
    have = configured()
    return '، '.join(PROVIDERS[c]['name'] + (' ✅' if c in have else ' ⏳') for c in PROVIDERS)


def _json(v):
    return json.dumps(v, ensure_ascii=False)


# ---------- Firecrawl: read the line's own tracking page without being blocked ----------

async def read_page(url):
    """Markdown of a public tracking page through Firecrawl (stealth proxy, fresh). None when no key is saved."""
    conn = _conn('FIRECRAWL')
    if not conn:
        return None
    body = {'url': url, 'formats': ['markdown'], 'onlyMainContent': True, 'waitFor': 8000, 'maxAge': 0, 'proxy': 'stealth',
            'timeout': 90000}
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(conn['url'], json=body, headers={'Authorization': 'Bearer ' + conn['key']})
    if r.status_code in (401, 403):
        raise ValueError('مفتاح Firecrawl غير مقبول — حدّثه من صفحة مفاتيح التتبع.')
    if r.status_code == 402:
        raise ValueError('رصيد Firecrawl انتهى — اشحنه من حساب Firecrawl.')
    r.raise_for_status()
    data = r.json()
    return str(((data.get('data') or {}) if isinstance(data, dict) else {}).get('markdown') or '')
