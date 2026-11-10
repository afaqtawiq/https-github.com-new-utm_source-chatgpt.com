"""Shipping-line desk: agent from container prefix, tiered detention estimate, automatic free-time extension draft
(sent only with «نفذ»), reminder + agent reply surfacing, extension result, fine audit with objection draft.
Isolated PostgreSQL; mail and WhatsApp simulated; nothing is sent."""
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


def run():
    from app.bootstrap import app  # noqa: F401
    from app import command_agent, container_returns, line_desk
    from app.storage import db, utcnow
    from app.team import ROLE
    line_desk.init()
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
    chat = patch('app.transport_desk.manager_chat', return_value=('966500000001', 'conv-m'))
    chat.start()
    today = dt.date.today()

    # 1) Registering a container links its agent from the prefix (MSCU → MSC); a leasing prefix stays unknown.
    out = container_returns.track({'container': 'MSCU1234567', 'bill': 'MEDU999001', 'customer': 'الحياة',
                                   'free_until': (today + dt.timedelta(days=2)).isoformat(), 'return_place': 'ساحة جدة'}, 'محمد')
    assert 'وكيل الملاحة: MSC' in out, out
    container_returns.track({'container': 'TGHU7654321', 'free_until': (today + dt.timedelta(days=1)).isoformat()}, 'محمد')
    with db() as c:
        assert c.execute("SELECT agent_id FROM container_returns WHERE container='TGHU7654321'").fetchone()['agent_id'] is None

    # 2) Tariff tiers: validation and cost.
    assert 'متصلة' in line_desk.set_tariff({'agent': 'MSC', 'tiers': '1-5:150، 7-10:300'})
    assert '✅' in line_desk.set_tariff({'agent': 'MSC', 'size': '40', 'tiers': '١-٥:150، 6-10:300، 11+:450'})
    tiers = line_desk.parse_tiers('1-5:150, 6-10:300, 11+:450')
    assert line_desk.tiers_cost(8, tiers) == 5 * 150 + 3 * 300 and line_desk.tiers_cost(12, tiers) == 750 + 1500 + 900
    assert '✅' in line_desk.set_container({'container': 'MSCU1234567', 'size': '40HC'})

    # 3) Daily tick: one extension draft to the MSC email with a code; unknown agent → one notice; nothing sent.
    msgs = line_desk.tick(today)
    draft = [m for m in msgs if 'طلب تمديد #' in m]
    assert len(draft) == 1 and 'MSCU1234567' in draft[0] and 'نفذ ' in draft[0], msgs
    assert any('TGHU7654321' in m and 'الوكيل غير محدد' in m for m in msgs), msgs
    with db() as c:
        req = c.execute('SELECT * FROM free_time_requests').fetchone()
        token_row = c.execute('SELECT command FROM whatsapp_voice_pending ORDER BY expires_at DESC LIMIT 1').fetchone()
    assert req['status'] == 'draft' and req['recipient'] == 'sau-ex-cs.localwest@msc.com' and 'MEDU999001' in req['body']
    assert json.loads(token_row['command'].partition(':')[2]) == {'tool': 'agent_email_send', 'kind': 'extension', 'id': req['id']}
    assert not [m for m in line_desk.tick(today) if 'طلب تمديد #' in m or 'TGHU' in m]  # no duplicates

    # 4) «نفذ» → sent once from the official mailbox; a second send is refused.
    sent = []
    with patch.object(line_desk, '_official_user', return_value=1), patch('app.spacemail.send', side_effect=lambda *a, **k: sent.append(a)):
        token = ROLE.set({'name': 'محمد', 'manager': True})
        assert '✅' in command_agent.execute_confirmed(None, json.dumps({'tool': 'agent_email_send', 'kind': 'extension', 'id': req['id']}))
        assert 'لم أرسله مرة ثانية' in line_desk.send('extension', req['id'])
        ROLE.reset(token)
    assert len(sent) == 1 and sent[0][1] == 'sau-ex-cs.localwest@msc.com' and 'Free Time Extension' in sent[0][2]

    # 5) No answer for 24h → reminder code; an agent reply in the official mailbox is surfaced.
    later = utcnow() + dt.timedelta(hours=25)
    msgs = line_desk.tick(today, now=later)
    assert any('لم يرد على طلب التمديد' in m and 'نفذ ' in m for m in msgs), msgs
    with db() as c:
        uid = c.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone()['id']
        c.execute('''INSERT INTO spacemail_inbox(user_id,uidvalidity,uid,sender,subject,body,imported_at)
            VALUES(%s,'1',1,'cs@msc.com','RE: Free Time Extension','Approved 5 days for MSCU1234567, new date 2026-12-01',%s)''',
                  (uid, later))
    msgs = line_desk.tick(today, now=later + dt.timedelta(minutes=30))
    assert any('📩 رد على طلب التمديد' in m and 'cs@msc.com' in m for m in msgs), msgs
    assert not any('📩' in m for m in line_desk.tick(today, now=later + dt.timedelta(hours=1)))

    # 6) Record the approved extension: new date kept, original remembered, request closed.
    new = today + dt.timedelta(days=9)
    assert 'ليس بعد' in line_desk.record_result({'containers': ['MSCU1234567'], 'result': 'approved', 'until': today.isoformat()})
    assert '✅' in line_desk.record_result({'containers': ['MSCU1234567'], 'result': 'approved', 'until': new.isoformat()})
    with db() as c:
        row = c.execute("SELECT * FROM container_returns WHERE container='MSCU1234567'").fetchone()
        req = c.execute('SELECT * FROM free_time_requests WHERE id=%s', (req['id'],)).fetchone()
    assert row['free_until'] == new and row['original_free_until'] == today + dt.timedelta(days=2) and req['status'] == 'approved'
    assert 'مُدّدت المدة المجانية' in container_returns.card(row)

    # 7) Fine audit: returned 8 days late → expected 1,650; 3,000 is over (objection + code), 1,650 is ok.
    with db() as c:
        c.execute("UPDATE container_returns SET free_until=%s WHERE container='MSCU1234567'", (today - dt.timedelta(days=8),))
    assert 'أُرجعت' in container_returns.update({'container': 'MSCU1234567', 'event': 'returned', 'note': 'EIR 778899 من المحطة'})
    out = line_desk.audit_claim({'container': 'MSCU1234567', 'amount': '3,000', 'days': '12'}, 'محمد',
                                make_token=lambda a: 'ABC123')
    assert 'أعلى من المستحق' in out and '1,650' in out and 'نفذ ABC123' in out, out
    with db() as c:
        claim = c.execute('SELECT * FROM detention_claims ORDER BY id DESC LIMIT 1').fetchone()
    assert claim['status'] == 'draft' and 'EIR 778899' in claim['body'] and claim['days_expected'] == 8
    assert 'مطابقة' in line_desk.audit_claim({'container': 'MSCU1234567', 'amount': '1650'}, 'محمد')

    # 8) Exposure summary and the desk page.
    container_returns.track({'container': 'MSCU7777777', 'free_until': (today - dt.timedelta(days=3)).isoformat(), 'size': '40'}, 'محمد')
    line_desk.set_container({'container': 'MSCU7777777', 'size': '40'})
    text = line_desk.exposure_text(today)
    assert 'MSC' in text and '450' in text, text
    with patch('app.naqliat_connector._session', return_value={}):
        html_page = line_desk.page(None).body.decode()
    assert 'مكتب الحاويات' in html_page and 'MSCU1234567' not in html_page.split('طلبات التمديد')[0] and 'وافق الوكيل' in html_page
    chat.stop()


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'line_desk_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: line desk — agent from prefix, tiered estimate, extension draft/send/reminder/reply/result, fine audit + objection.')


if __name__ == '__main__':
    main()
