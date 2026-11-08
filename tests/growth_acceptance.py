"""Prospect follow-ups + public price calculator on local PostgreSQL. WhatsApp mocked; external network blocked."""
import asyncio
import datetime as dt
import os
import secrets
import socket
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_followups_at(pf, when):
    # The eligibility clock and persisted send timestamps must advance together.
    with patch.object(pf, 'utcnow', return_value=when):
        return asyncio.run(pf.run(when))


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import prospect_followups as pf, prospect_replies, zernio_whatsapp as wa
    from app.daily_prospects import decide, today
    from app.storage import db
    pf.init(); prospect_replies.init()
    now = dt.datetime(2026, 11, 8, 6, 35, tzinfo=dt.timezone.utc)
    with db() as c:
        uid = c.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('a@fixture.invalid','admin','x','admin',%s) RETURNING id",
                        (now,)).fetchone()['id']
        ids = []
        for i, phone in enumerate(('+966500000501', '+966500000502', '+966500000503', '+966500000504')):
            ids.append(c.execute('''INSERT INTO daily_prospects(source_key,company_name,phone,email,city,activity,website,score,segment,
                reason,message,message_source,status,batch_date,created_at,updated_at)
                VALUES(%s,%s,%s,'','جدة','استيراد','',50,'importer','x','رسالة تعريف تجريبية طويلة','template','pending',%s,%s,%s) RETURNING id''',
                                 ('fu:' + str(i), 'شركة ' + str(i), phone, today(), now, now)).fetchone()['id'])
    for pid in ids:
        decide([pid], 'approve', uid)
        decide([pid], 'contacted', uid, note='autopilot: whatsapp')
    with db() as c:
        c.execute('UPDATE daily_prospects SET decided_at=%s WHERE id=ANY(%s)', (now - dt.timedelta(days=4), ids))
        c.execute("INSERT INTO marketing_suppressions(channel,recipient,created_at) VALUES('whatsapp','+966500000503',%s)", (now,))
        c.execute("INSERT INTO prospect_replies(job_id,prospect_id,sender,body,intent,created_at) VALUES(1,%s,'x','نعم','interested',%s)", (ids[3], now))
    sent = []
    env = {'AUTO_OUTREACH': '1', 'ENABLE_EXTERNAL_ACTIONS': '1'}
    fri = now
    while fri.astimezone(pf.RIYADH).weekday() != 4:
        fri += dt.timedelta(days=1)
    assert not pf.in_hours(fri)
    work = now
    while not pf.in_hours(work):
        work += dt.timedelta(hours=1)
    with db() as c:
        c.execute('UPDATE daily_prospects SET decided_at=%s WHERE id=ANY(%s)', (work - dt.timedelta(days=4), ids))
    with patch.dict(os.environ, env), patch.object(pf, 'ensure_template', AsyncMock(return_value='APPROVED')), \
            patch.object(wa, 'send', AsyncMock(side_effect=lambda to, text, **k: sent.append((to, text)))):
        stats = run_followups_at(pf, work)
        assert stats['sent'] == 2, stats
        assert sorted(t for t, _ in sent) == ['+966500000501', '+966500000502']  # not suppressed, not replied
        assert 'نتابع معكم رسالتنا السابقة' in sent[0][1] and 'لإيقاف الرسائل أرسل: إيقاف' in sent[0][1]
        assert run_followups_at(pf, work)['sent'] == 0  # step 1 only once
        later = work + dt.timedelta(days=4)
        while not pf.in_hours(later):
            later += dt.timedelta(hours=1)
        assert run_followups_at(pf, later)['sent'] == 2  # step 2 at day 7+
        assert 'جرّبونا في شحنة واحدة' in sent[-1][1]
        assert run_followups_at(pf, later + dt.timedelta(days=5))['sent'] == 0  # then stop
    with patch.dict(os.environ, {'AUTO_OUTREACH': '0'}):
        assert run_followups_at(pf, work)['enabled'] is False
    # Template text must match the exact message the agent sends.
    params = wa.template_parameters({'components': [{'type': 'BODY', 'text': pf.template_spec()['components'][0]['text']}]},
                                    pf.body('شركة 0', pf.step_line(1)))
    assert params and params[0] == 'شركة 0'

    # Price calculator: page, lead, validation, rate limit; no session needed.
    client = TestClient(app, base_url='http://testserver')
    page = client.get('/price?src=social')
    assert page.status_code == 200 and 'احسب سعر شحنتك' in page.text and 'من ميناء جدة الإسلامي إلى الرياض' in page.text
    delivered = []
    with patch('app.owner_briefing.deliver', AsyncMock(side_effect=lambda t: delivered.append(t))):
        ok = client.post('/price/lead', json={'company': 'مؤسسة النخبة', 'phone': '0551234567', 'service': 'both',
                                              'route': 'من ميناء جدة الإسلامي إلى الرياض', 'containers': 3, 'source': 'social'})
        assert ok.status_code == 200, ok.text
        link = ok.json()['whatsapp']
        assert link.startswith('https://wa.me/966507665873?text=') and '14%2C250' in link
        assert client.post('/price/lead', json={'company': 'x', 'phone': '1', 'service': 'both'}).status_code == 400
        assert client.post('/price/lead', json={'company': 'بوت', 'phone': '0551234567', 'service': 'both', 'website': 'x'}).status_code == 400
        for _ in range(4):
            client.post('/price/lead', json={'company': 'مؤسسة النخبة', 'phone': '0551234567', 'service': 'clearance', 'containers': 1})
        assert client.post('/price/lead', json={'company': 'مؤسسة النخبة', 'phone': '0551234567', 'service': 'clearance'}).status_code == 429
    with db() as c:
        row = c.execute('SELECT * FROM price_leads ORDER BY id LIMIT 1').fetchone()
    assert row['phone'] == '966551234567' and row['total'] == 3 * 250 + 3 * 4500 and row['source'] == 'social'


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema = 'growth_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1', 'testserver'):
            raise AssertionError('External network blocked')
        return connect(sock, address)
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '', 'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32),
               'ADMIN_EMAIL': 'bootstrap@fixture.invalid', 'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', local_only):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: prospect follow-ups and price calculator leads; external sends 0.')


if __name__ == '__main__':
    main()
