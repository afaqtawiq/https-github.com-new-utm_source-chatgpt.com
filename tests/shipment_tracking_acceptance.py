"""Live tracking (ShipsGo v2 simulated): B/L → ETA/vessel reply, one paid creation only, container desk arrival and
estimated last free day updated, ETA change and discharge alerts once, automatic start after a document with a daily
cap, not-connected and bad-token messages. Isolated PostgreSQL; nothing real is called or sent."""
import asyncio
import datetime as dt
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATE = {'eta': '2026-12-02T06:00:00+03:00', 'disc': 'EST', 'posts': [], 'status': 200}


def shipment():
    return {'shipment': {'id': 555, 'booking_number': 'SHZ8739334', 'status': 'SAILING',
                         'carrier': {'scac': 'CMDU', 'name': 'CMA CGM'},
                         'containers': [{'number': CONT, 'size': 40, 'movements': [
                             {'event': 'LOAD', 'status': 'ACT', 'timestamp': '2026-11-12T10:00:00+08:00',
                              'location': {'code': 'CNSHK', 'name': 'Shekou'}, 'vessel': {'name': 'CMA CGM TIGRIS'}, 'voyage': '0FX3W'},
                             {'event': 'ARRV', 'status': STATE['disc'], 'timestamp': STATE['eta'],
                              'location': {'code': 'SAJED', 'name': 'Jeddah'}, 'vessel': {'name': 'CMA CGM TIGRIS'}, 'voyage': '0FX3W'},
                             {'event': 'DISC', 'status': STATE['disc'], 'timestamp': STATE['eta'],
                              'location': {'code': 'SAJED', 'name': 'Jeddah'}, 'vessel': {'name': 'CMA CGM TIGRIS'}, 'voyage': '0FX3W'}]}]}}


def handler(request):
    if STATE['status'] != 200:
        return httpx.Response(STATE['status'], json={'message': 'unauthorized'})
    assert request.headers['X-Shipsgo-User-Token'] == 'fixture-token'
    path = request.url.path
    if path == '/v2/ocean/carriers':
        return httpx.Response(200, json={'carriers': [{'code': 'SG_MSC', 'name': 'MSC', 'scac': 'MSCU'},
                                                      {'code': 'SG_CMA', 'name': 'CMA CGM', 'scac': ['CMDU', 'CMAU']}]})
    if path == '/v2/ocean/shipments' and request.method == 'POST':
        STATE['posts'].append(json.loads(request.content))
        return httpx.Response(200, json={'message': 'success', 'shipment': {'id': 555}})
    if path == '/v2/ocean/shipments/555':
        return httpx.Response(200, json=shipment())
    return httpx.Response(404, json={'message': 'not found'})


def client():
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={'X-Shipsgo-User-Token': 'fixture-token'})


CONT = None


def run():
    global CONT
    from app.bootstrap import app  # noqa: F401
    from app import command_agent, container_returns, line_desk, shipment_tracking as st
    from app.fasah_containers import check_digit_ok
    from app.storage import db
    from app.team import ROLE
    CONT = next(f'CMAU123456{d}' for d in range(10) if check_digit_ok(f'CMAU123456{d}'))
    line_desk.init(); st.init()
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')

    # 1) No paid service → the work computer opens the line's public tracking page; the result comes back as a PDF.
    from app import agent_runner, tracking_pdf
    agent_runner.init()
    with patch.dict(os.environ, {'SHIPSGO_API_TOKEN': ''}):
        assert 'اسم الخط الملاحي' in asyncio.run(st.track('799610583408'))        # line unknown → asks, no task
        out = asyncio.run(st.track('MEDU7788990', chat=('966500000001', 'conv-m')))
        assert 'جهاز آفاق طويق' in out and 'PDF' in out, out
        with db() as c:
            task = c.execute("SELECT * FROM runner_tasks WHERE kind='read_page' ORDER BY id DESC LIMIT 1").fetchone()
        params = json.loads(task['params_json'])
        assert params['url'].startswith('https://www.msc.com/') and 'MEDU7788990' in params['url'] and params['purpose'] == 'tracking'
        assert params['chat'] == ['966500000001', 'conv-m'] and agent_runner.domain_allowed(params['url'])
        assert agent_runner.domain_allowed('https://www.maersk.com/tracking/123') and not agent_runner.domain_allowed('https://evil.example/x')
        out = asyncio.run(st.track('CMAU1234565', carrier='CMA CGM'))
        assert 'CMA CGM' in out
        # The runner finished: page text → result saved, desk updated, PDF sent to the requester, summary delivered.
        container_returns.track({'container': 'MSCU1234565', 'bill': 'MEDU7788990'}, 'محمد')
        with db() as c:
            c.execute("UPDATE runner_tasks SET status='done' WHERE id=%s", (task['id'],))
            c.execute('''INSERT INTO runner_files(task_id,name,mime,size,sha256,verified,data,created_at) VALUES(%s,'page.txt','text/plain',5,'x',TRUE,%s,NOW())''',
                      (task['id'], 'MSC tracking MEDU7788990 ... ETA Jeddah 05/12/2026'.encode()))
        page = {'found': True, 'carrier': 'MSC', 'vessel': 'MSC ANNA', 'voyage': 'QX547A', 'pol': 'Ningbo', 'etd': '2026-11-15',
                'pod': 'Jeddah', 'eta': '2026-12-05', 'arrived': False, 'last_event': 'Loaded on vessel, Ningbo',
                'last_event_date': '2026-11-15', 'containers': ['MSCU1234565']}
        sent, delivered = [], []

        async def fake_extract(text, ref):
            assert 'MEDU7788990' in text and ref == 'MEDU7788990'
            return page

        async def fake_send(chat, ref, info, source):
            sent.append((chat, ref, tracking_pdf.build(ref, info, source)[:5]))
            return True

        async def fake_deliver(text):
            delivered.append(text)
        with patch.object(st, 'extract_page', side_effect=fake_extract), patch.object(tracking_pdf, 'send', side_effect=fake_send), \
                patch('app.owner_briefing.deliver', side_effect=fake_deliver):
            text = st.after_page(task['id'], 'done')
        assert '05/12/2026' in text and 'MSC ANNA' in text and '📎' in text and delivered == [text], text
        assert sent == [(('966500000001', 'conv-m'), 'MEDU7788990', b'%PDF-')]
        with db() as c:
            row = c.execute("SELECT * FROM shipment_tracks WHERE ref='MEDU7788990'").fetchone()
            cr = c.execute("SELECT arrived_on FROM container_returns WHERE container='MSCU1234565'").fetchone()
        assert row['vessel'] == 'MSC ANNA' and cr['arrived_on'] == dt.date(2026, 12, 5)
        # A blocked / captcha page → honest message, nothing saved as a result.
        async def _blocked(t, r):
            return {'found': False, 'reason': 'captcha'}
        with patch.object(st, 'extract_page', side_effect=_blocked), patch('app.owner_briefing.deliver', side_effect=fake_deliver):
            text = st.after_page(task['id'], 'done')
        assert 'لم تعرض نتيجة' in text and 'captcha' in text
        assert 'جهاز آفاق طويق' in asyncio.run(st.after_document({'bill_no': 'MEDU5556667', 'shipping_line': 'MSC'}))

        # 1b) Public sources on the server come first (no device needed): a DRAFT B/L found through its vessel and voyage.
        from app import staff_documents
        staff_documents.save('966500000001', 'KSA-C.462_BL.pdf', 'application/pdf', b'%PDF-1.4 x',
                             {'document_kind': 'shipping_document', 'bill_no': 'SHZ8739334', 'vessel': 'CMA CGM LORENZACCIO',
                              'shipping_line': 'CMA CGM', 'container_numbers': ['CAIU9727815'], 'key_facts': {'Voyage': '0RDPCW1MA'}})
        hints = st.hints_for('SHZ8739334')
        assert hints['vessel'] == 'CMA CGM LORENZACCIO' and hints['voyage'] == '0RDPCW1MA' and hints['containers'] == ['CAIU9727815']
        seen = []

        async def fake_research(ref, kind, carrier, h):
            seen.append((ref, kind, h.get('vessel'), h.get('voyage')))
            return {'found': True, 'method': 'vessel_schedule', 'carrier': 'CMA CGM', 'vessel': 'CMA CGM LORENZACCIO',
                    'voyage': '0RDPCW1MA', 'pol': 'Shekou', 'etd': '2026-11-09', 'pod': 'Jeddah', 'eta': '2026-11-29',
                    'arrived': False, 'last_event': 'Singapore', 'last_event_date': '2026-11-14',
                    'containers': ['CAIU9727815'], 'sources': ['https://www.cma-cgm.com/x.pdf', 'https://service-finder.shipsgo.com/v']}
        pdfs = []

        async def fake_pdf(chat, ref, info, source):
            pdfs.append((chat, ref, source, tracking_pdf.build(ref, info, source)[:5]))
            return True
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture'}), patch.object(st, 'research', side_effect=fake_research), \
                patch.object(tracking_pdf, 'send', side_effect=fake_pdf):
            out = asyncio.run(st.track('SHZ8739334', 'CMA CGM', 'سلطان', chat=('966500000001', 'conv-m')))
            assert '29/11/2026' in out and 'جدول رحلة السفينة' in out and 'cma-cgm.com' in out and 'مسودة' in out and '📎' in out, out
            assert seen[-1] == ('SHZ8739334', 'bl', 'CMA CGM LORENZACCIO', '0RDPCW1MA') and pdfs[-1][1] == 'SHZ8739334'
            with db() as c:
                row = c.execute("SELECT * FROM shipment_tracks WHERE ref='SHZ8739334'").fetchone()
            assert row['source'] == 'web' and row['eta'].astimezone(st.RIYADH).date() == dt.date(2026, 11, 29)
            # Vessel and voyage alone.
            out = asyncio.run(st.track('', vessel='CMA CGM LORENZACCIO', voyage='0RDPCW1MA'))
            assert '29/11/2026' in out and seen[-1][1] == 'vessel'
            # Twice-daily re-check: ETA moves → one alert.
            with db() as c:
                c.execute("UPDATE shipment_tracks SET checked_at = NOW() - INTERVAL '13 hours' WHERE ref='SHZ8739334'")
            alerts = []

            async def later(ref, kind, carrier, h):
                d = await fake_research(ref, kind, carrier, h)
                return dict(d, eta='2026-12-02')

            async def collect(text):
                alerts.append(text)
            with patch.object(st, 'research', side_effect=later):
                asyncio.run(st.refresh_web(deliver=collect))
            assert any('SHZ8739334' in a and '02/12/2026' in a for a in alerts), alerts

        # Nothing reliable in public sources → the work computer is asked next.
        async def nothing(ref, kind, carrier, h):
            return {'found': False, 'note': 'not found'}
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture'}), patch.object(st, 'research', side_effect=nothing):
            out = asyncio.run(st.track('MEDU1112223', 'MSC'))
        assert 'ما لقيت موعدًا مؤكدًا' in out and 'جهاز آفاق طويق' in out, out

        # Small NVOCC line (SHIPNER), no published schedule: the vessel's AIS position gives a clearly marked estimate.
        async def ais_only(ref, kind, carrier, h):
            return {'found': False, 'vessel': 'HAI TAO 205', 'voyage': 'HT26001W', 'pod': 'Jeddah', 'note': 'no schedule',
                    'ais': {'lat': 2.06907, 'lon': 102.11924, 'area': 'Malacca Strait', 'position_time': '2026-11-02 12:22',
                            'speed_knots': 8.7, 'destination': 'PORT SUDAN', 'destination_eta': '2026-11-24',
                            'mmsi': '630001353', 'url': 'https://www.myshiptracking.com/vessels/hai-tao-205'}}
        pdfs.clear()
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture'}), patch.object(st, 'research', side_effect=ais_only), \
                patch.object(tracking_pdf, 'send', side_effect=fake_pdf):
            out = asyncio.run(st.track('SSATAOJED2609210', 'SHIPNER', 'سلطان', chat=('966500000001', 'conv-m'),
                                       vessel='HAI TAO 205', voyage='HT26001W'))
        assert 'AIS' in out and 'Malacca Strait' in out and 'الوصول التقديري' in out and 'ليس موعدًا رسميًا' in out, out
        assert 'PORT SUDAN' in out and 'ليست جدة' in out and 'myshiptracking.com' in out and pdfs[-1][1] == 'SSATAOJED2609210', out
        with db() as c:
            row = c.execute("SELECT * FROM shipment_tracks WHERE ref='SSATAOJED2609210'").fetchone()
        assert row['source'] == 'web' and row['eta'] is None and json.loads(row['hints'])['ais']['mmsi'] == '630001353'

        # No confirmed date → an ETA question to the destination agent named on the B/L, prepared for «نفذ» only.
        from app import eta_inquiry
        staff_documents.save('966500000001', 'SHIPNER_BL.pdf', 'application/pdf', b'%PDF-1.4 y',
                             {'document_kind': 'shipping_document', 'bill_no': 'SSATAOJED2609210', 'vessel': 'HAI TAO 205',
                              'voyage': 'HT26001W', 'shipping_line': 'SHIPNER', 'container_numbers': ['DFSU7046619', 'FCIU9539014'],
                              'key_facts': {'Destination Agent': 'GOODRICH ARABIA CO'}})
        prepared = []
        out = eta_inquiry.prepare('SSATAOJED2609210', '', lambda action: (prepared.append(action), 'C0DE42')[1])
        assert 'نفذ C0DE42' in out and 'goodrich.jed@goodricharabia.com' in out, out
        mail = prepared[-1]
        assert mail['tool'] == 'send_email' and mail['to'] == 'goodrich.jed@goodricharabia.com'
        assert 'SSATAOJED2609210' in mail['subject'] and 'HAI TAO 205 / V.HT26001W' in mail['subject']
        assert 'DFSU7046619' in mail['body'] and 'Dear Goodrich Team' in mail['body'] and 'ETA' in mail['body']
        assert 'اكتب اسم الوكيل' in eta_inquiry.prepare('UNKNOWN1234567', '', lambda action: 'X')
        assert eta_inquiry.find_agent('UNKNOWN1234567', 'Maersk Line')[1] == 'sa.import@maersk.com'
        assert 'ask_eta_by_email' in command_agent.HANDLERS

        # research() talks to the Claude API with web search + fetch and continues a paused turn.
        calls = []

        def api(request):
            body = json.loads(request.content)
            calls.append((request.headers.get('anthropic-beta'), [t['name'] for t in body['tools']], len(body['messages'])))
            if len(calls) == 1:
                return httpx.Response(200, json={'stop_reason': 'pause_turn', 'content': [{'type': 'text', 'text': 'searching'}]})
            return httpx.Response(200, json={'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'نتيجة: {"found": true, "eta": "2026-11-29"}'}]})
        real = httpx.AsyncClient
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture'}), \
                patch('httpx.AsyncClient', lambda **k: real(transport=httpx.MockTransport(api))):
            got = asyncio.run(st.research('SHZ8739334', 'bl', 'CMA CGM', {'vessel': 'CMA CGM LORENZACCIO'}))
        assert got == {'found': True, 'eta': '2026-11-29'} and calls[0][0] == 'web-fetch-2025-09-10'
        assert calls[0][1] == ['web_search', 'web_fetch'] and calls[1][2] == 2
        assert asyncio.run(st.after_document({'bill_no': 'SHZ8739334', 'eta': '2026-12-01'})) == ''

    os.environ['SHIPSGO_API_TOKEN'] = 'fixture-token'
    assert '✅' in line_desk.set_tariff({'agent': 'CMA CGM', 'free_days': '14'})
    container_returns.track({'container': CONT, 'bill': 'SHZ8739334', 'customer': 'PROMATE'}, 'محمد')

    with patch.object(st, '_client', client):
        # 2) Manager asks to track the B/L → one creation with the ShipsGo carrier code; ETA, vessel, desk updated.
        token = ROLE.set({'name': 'محمد', 'manager': True})
        out = command_agent.tool_track_shipment(None, {'ref': 'SHZ 8739334', 'carrier': 'CMA CGM'})
        ROLE.reset(token)
        assert '02/12/2026' in out and 'CMA CGM TIGRIS' in out and 'Jeddah' in out and 'Shekou' in out, out
        assert 'حاوية في مكتب الحاويات' in out, out
        assert STATE['posts'] == [{'booking_number': 'SHZ8739334', 'carrier': 'SG_CMA'}], STATE['posts']
        with db() as c:
            row = c.execute('SELECT * FROM container_returns WHERE container=%s', (CONT,)).fetchone()
        assert row['arrived_on'] == dt.date(2026, 12, 2) and row['free_until'] == dt.date(2026, 12, 15) and row['free_until_estimated']

        # 3) Asked again → no second paid creation.
        asyncio.run(st.track('SHZ8739334'))
        assert len(STATE['posts']) == 1

        # 4) Refresh after 5 h with the ETA two days later → one alert; desk follows.
        alerts = []

        async def deliver(text):
            alerts.append(text)
        later = st.utcnow() + dt.timedelta(hours=5)
        STATE['eta'] = '2026-12-04T06:00:00+03:00'
        asyncio.run(st.refresh(now=later, deliver=deliver))
        assert len(alerts) == 1 and 'تأخر' in alerts[0] and '04/12/2026' in alerts[0], alerts
        with db() as c:
            assert c.execute('SELECT arrived_on FROM container_returns WHERE container=%s', (CONT,)).fetchone()['arrived_on'] == dt.date(2026, 12, 4)
            c.execute("UPDATE shipment_tracks SET checked_at = checked_at - INTERVAL '5 hours'")
        # 5) Discharged → one arrival alert; then quiet.
        STATE['disc'] = 'ACT'
        asyncio.run(st.refresh(now=later + dt.timedelta(hours=5), deliver=deliver))
        assert len(alerts) == 2 and 'وصلت' in alerts[1], alerts
        with db() as c:
            c.execute("UPDATE shipment_tracks SET checked_at = checked_at - INTERVAL '5 hours'")
        asyncio.run(st.refresh(now=later + dt.timedelta(hours=10), deliver=deliver))
        assert len(alerts) == 2

        # 6) Automatic start after a document without arrival date; daily cap respected.
        STATE['disc'] = 'EST'
        with patch.dict(os.environ, {'SHIPMENT_TRACKING_DAILY_CAP': '1'}):
            out = asyncio.run(st.after_document({'bill_no': 'SHZ1111111', 'shipping_line': 'CMA CGM'}))
            assert out.startswith('🔎') and 'الوصول المتوقع' in out, out
            out = asyncio.run(st.after_document({'bill_no': 'SHZ2222222', 'shipping_line': 'CMA CGM'}))
            assert 'الحد اليومي' in out, out
        with patch.dict(os.environ, {'SHIPMENT_TRACKING_AUTO': '0'}):
            assert 'تتبع البوليصة SHZ3333333' in asyncio.run(st.after_document({'bill_no': 'SHZ3333333'}))

        # 7) List and bad token.
        assert 'SHZ8739334' in st.list_text()
        STATE['status'] = 401
        assert 'رمز ربط ShipsGo' in asyncio.run(st.track('SHZ4444444'))
    assert st.ref_type('CMAU 1234567')[1] in ('container', 'bl') and st.ref_type('abc') == (None, None)
    assert st.scac_for('CMA CGM SAUDI') == 'CMDU' and st.scac_for('Mediterranean') is None


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'ship_track_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0', 'SHIPSGO_API_TOKEN': ''}
        with patch.dict(os.environ, env):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: shipment tracking — B/L ETA/vessel, single paid creation, desk arrival + free day, ETA change and discharge alerts, auto start with cap.')


if __name__ == '__main__':
    main()
