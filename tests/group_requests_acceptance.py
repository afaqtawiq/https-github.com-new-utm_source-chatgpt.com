"""Group request inbox — the owner's scenarios, simulated (provider and e-mail replaced; nothing is sent anywhere):
two requests in one group (approvals + 2 files, then a different request), a greeting, alert failure on both channels
(urgent list, no duplicates, back-off retry, then delivery receipt), restart, an interrupted send (uncertain, never
re-sent), a quoted reply that closes only its request, intake stop → one independent e-mail alert. Isolated PostgreSQL."""
import asyncio
import datetime as dt
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
T0 = dt.datetime(2026, 11, 20, 7, 0, tzinfo=dt.timezone.utc)   # 10:00 Riyadh
OWNER = '966557345991'
CUSTOMER, OTHER, RAMI = '971501112233', '971502223344', '966507150680'
M = dt.timedelta(minutes=1)


def event(mid, text='', files=(), at=T0, sender=CUSTOMER, name='عمران ناقل R 2', reply_to=None):
    msg = {'id': mid, 'direction': 'incoming', 'text': text, 'createdAt': at.isoformat(),
           'sender': {'phoneNumber': '+' + sender, 'name': name},
           'attachments': [{'type': 'document', 'fileName': f} for f in files]}
    if reply_to:
        msg['replyTo'] = reply_to
    return {'event': 'message.received', 'id': 'ev-' + mid, 'account': {'accountId': 'acc-1', 'platform': 'whatsapp'},
            'conversation': {'id': 'grp-test', 'isGroup': True, 'name': 'Afaq internal test'}, 'message': msg}


def run():
    from app.bootstrap import app  # noqa: F401
    from app import group_requests as gr, group_watch as gw
    from app.storage import db
    gr.init()
    feed = lambda *evs: ([gw.capture(e) for e in evs], gw.flush())

    # 1) Request A: two files, then the approvals question → ONE card owned by التخليص (فيصل).
    feed(event('a1', files=['_ PL 326 KMC POTATO GRANULES.pdf'], at=T0),
         event('a2', files=['_ CI 326 KMC POTATO GRANULES.pdf'], at=T0 + M),
         event('a3', 'This shipment required 3rd party license charges. can you pls check the HS CODE whether they required any approval.', at=T0 + 2 * M))
    # 2) A different request in the same group (another member), 3) a greeting.
    feed(event('b1', 'Kindly share your rate for 2x40HC from Jebel Ali to Riyadh', at=T0 + 4 * M, sender=OTHER, name='Hany'),
         event('g1', 'Good morning all', at=T0 + 5 * M, sender=CUSTOMER))
    out = gr.build(T0 + 6 * M)
    assert out == {'new': 2, 'joined': 2, 'closed': 0, 'other': 1}, out
    cards = {c['id']: c for c in gr.cards()}
    a, b = sorted(cards.values(), key=lambda c: c['received_at'])
    assert a['files'] == ['_ PL 326 KMC POTATO GRANULES.pdf', '_ CI 326 KMC POTATO GRANULES.pdf'] and 'HS CODE' in a['text']
    assert 'فيصل' in a['owner'] and 'ريم' in b['owner'] and a['backup'].startswith('محمد') and a['status'] == b['status'] == 'open'
    assert a['last_action'] == 'وصل الطلب في القروب'

    # A team greeting does not close anything.
    with patch.dict(os.environ, {'AFAQ_TEAM': json.dumps([{'phone': '+' + RAMI, 'name': 'رامي'}])}):
        feed(event('t0', 'صباح الخير', at=T0 + 7 * M, sender=RAMI, name='رامي'))
        gr.build(T0 + 7 * M)
    assert all(c['status'] == 'open' for c in gr.cards())

    # 4) No receipt in 15 min → backup alert. WhatsApp and e-mail both fail → urgent list, recorded states.
    sent_wa, sent_mail, receipts = [], [], {}

    async def wa_ok(phone, text):
        sent_wa.append((phone, text))
        return 'wamid-' + str(len(sent_wa)), 'conv-owner'

    def mail_ok(to, subject, text):
        sent_mail.append((to, subject))
        return '<m@afaq>'

    async def receipt(conv, pid):
        return receipts.get(pid, 'sent')
    env = {'WHATSAPP_COMMAND_OWNER': '+' + OWNER, 'GROUP_REQUESTS_FORCE_FAIL': 'whatsapp,email'}
    with patch.dict(os.environ, env), patch.object(gr, 'delivery_state', side_effect=receipt):
        assert asyncio.run(gr.alerts(T0 + 10 * M)) == []                       # before 15 minutes: nothing
        res = asyncio.run(gr.alerts(T0 + 17 * M))
        assert (a['id'], 'whatsapp', 'failed') in res and (a['id'], 'email', 'failed') in res, res
        assert not any(r[0] == b['id'] for r in res), 'B is only 13 minutes old'
        assert asyncio.run(gr.alerts(T0 + 18 * M)) == [], 'no duplicate attempts before the back-off'
    card = {c['id']: c for c in gr.cards()}[a['id']]
    assert card['urgent'] and [x[2] for x in card['alerts']] == ['failed', 'failed'] and 'العاجلة' in card['last_action']
    with db() as c:
        assert c.execute('SELECT COUNT(*) n FROM group_request_alerts').fetchone()['n'] == 2

    # 5) Restart: in-memory state gone, everything comes back from the database; still no duplicates.
    gr._READY = gw._READY = False
    gw._QUEUE.clear()
    gr.init()
    assert {c['id'] for c in gr.cards() if c['status'] == 'open'} == {a['id'], b['id']}
    # Channels repaired: after the back-off, WhatsApp is retried (attempt 2) and is accepted → «sent», not yet «delivered».
    with patch.dict(os.environ, {'WHATSAPP_COMMAND_OWNER': '+' + OWNER, 'GROUP_REQUESTS_FORCE_FAIL': ''}), \
            patch.object(gr, 'send_whatsapp', side_effect=wa_ok), patch.object(gr, 'send_email', side_effect=mail_ok), \
            patch.object(gr, 'delivery_state', side_effect=receipt):
        res = asyncio.run(gr.alerts(T0 + 29 * M))
        assert (a['id'], 'whatsapp', 'sent') in res and (b['id'], 'whatsapp', 'sent') in res, res
        assert len(sent_wa) == 2 and sent_wa[0][0] == '+' + OWNER and 'Afaq internal test' in sent_wa[0][1] and 'استلمت' in sent_wa[0][1]
        card = {c['id']: c for c in gr.cards()}[a['id']]
        assert not card['urgent'] and card['alerts'][-1][2] == 'sent' and 'بانتظار إشعار الوصول' in card['last_action']
        # Delivery receipt for A arrives; B's alert stays «sent» and after 5 minutes falls back to e-mail.
        receipts['wamid-1'] = 'delivered'
        res = asyncio.run(gr.alerts(T0 + 31 * M))
        assert (a['id'], 'whatsapp', 'delivered') in res and not sent_mail, res
        res = asyncio.run(gr.alerts(T0 + 35 * M))
        assert (b['id'], 'email', 'sent') in res and len(sent_mail) == 1 and len(sent_wa) == 2, res
        assert asyncio.run(gr.alerts(T0 + 40 * M)) == [] and len(sent_wa) == 2 and len(sent_mail) == 1
    card = {c['id']: c for c in gr.cards()}[a['id']]
    assert card['alerts'][-1][5] is not None and 'وصل تنبيه واتساب' in card['last_action']

    # An interrupted send (restart between reserve and result) is «uncertain» and never re-sent on WhatsApp.
    feed(event('c1', 'Please confirm the SABER requirement for these heaters', at=T0 + 41 * M, sender=OTHER, name='Hany'))
    gr.build(T0 + 41 * M)
    cid = max(c['id'] for c in gr.cards())
    with db() as c:
        c.execute('''INSERT INTO group_request_alerts(request_id,channel,attempt,recipient,state,attempted_at,updated_at)
            VALUES(%s,'whatsapp',1,%s,'attempted',%s,%s)''', (cid, '+' + OWNER, T0 + 56 * M, T0 + 56 * M))
    with patch.dict(os.environ, {'WHATSAPP_COMMAND_OWNER': '+' + OWNER}), patch.object(gr, 'send_whatsapp', side_effect=wa_ok), \
            patch.object(gr, 'send_email', side_effect=mail_ok), patch.object(gr, 'delivery_state', side_effect=receipt):
        res = asyncio.run(gr.alerts(T0 + 70 * M))
    assert (cid, 'email', 'sent') in res and len(sent_wa) == 2, res
    assert [x[2] for x in {c['id']: c for c in gr.cards()}[cid]['alerts']][0] == 'uncertain'

    # 6) A team reply quoting request B closes B only; A and C stay open.
    with patch.dict(os.environ, {'AFAQ_TEAM': json.dumps([{'phone': '+' + RAMI, 'name': 'رامي'}])}):
        feed(event('t1', 'Rate for 2x40HC Jebel Ali → Riyadh: 4,200 SAR per container', at=T0 + 72 * M, sender=RAMI, name='رامي', reply_to='b1'))
        assert gr.build(T0 + 72 * M)['closed'] == 1
    state = {c['id']: c['status'] for c in gr.cards()}
    assert state[b['id']] == 'closed' and state[a['id']] == state[cid] == 'open', state
    assert 'رامي' in {c['id']: c for c in gr.cards()}[b['id']]['last_action']
    # «استلمت» from the office stops alerts for A without closing it.
    assert gr.acknowledge(a['id'], 'محمد') and {c['id']: c for c in gr.cards()}[a['id']]['status'] == 'open'
    assert all(r['id'] != a['id'] for r in gr.due_alerts(T0 + 80 * M))
    assert '#' + str(a['id']) in gr.list_text() and '#' + str(b['id']) not in gr.list_text()

    # 7) Intake stopped (no successful read for 20 min) → one e-mail on an independent channel, shown on the page.
    mails = []
    gw.health_mark('poll', True, at=T0)
    with patch.object(gr, 'utcnow', lambda: T0 + 30 * M):
        h = gr.health(T0 + 30 * M)
        assert h['stale'] and gr.health_alert(T0 + 30 * M, mailer=lambda *a: mails.append(a))
        assert gr.health_alert(T0 + 31 * M, mailer=lambda *a: mails.append(a)) is None and len(mails) == 1
    gw.health_mark('poll', True, at=T0 + 32 * M)
    assert gr.health_alert(T0 + 33 * M, mailer=lambda *a: mails.append(a)) is None
    html = gr.page_html(gr.cards(), gr.health(T0 + 33 * M), lambda r, x: f'/x/{r}/{x}')
    assert 'آخر مزامنة' in html and 'POTATO' in html and 'وصل ✅' in html and 'غير مؤكد' in html

    # Staging app: token-protected page, health endpoint.
    from fastapi.testclient import TestClient
    from app import staging_requests
    with patch.dict(os.environ, {'STAGING_VIEW_TOKEN': 'x' * 32}):
        client = TestClient(staging_requests.app)
        assert client.get('/staging/requests?token=wrong').status_code == 404
        assert 'طلبات القروبات' in client.get('/staging/requests?token=' + 'x' * 32).text
        assert client.get('/health').json()['ok']


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'group_req_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0', 'WHATSAPP_COMMAND_OWNER': '',
               'GROUP_REQUESTS_ENABLED': '1'}
        with patch.dict(os.environ, env):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: group requests — two requests + files + greeting, owner/backup, 15-min alert, attempted/sent/delivered, '
          'WhatsApp→e-mail→urgent, back-off without duplicates, restart, uncertain never re-sent, quoted reply closes only its request, intake alert.')


if __name__ == '__main__':
    main()
