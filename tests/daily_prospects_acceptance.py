"""Daily prospect list on local PostgreSQL. Synthetic records; non-loopback egress blocked."""
import os
import re
import secrets
import socket
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import daily_prospects as dp
    from app.storage import db, one, rows, create_session, utcnow
    client = TestClient(app, base_url='http://testserver', follow_redirects=False)
    now = utcnow()
    sessions = {}
    with db() as c:
        for role in ('admin', 'sales', 'transport', 'viewer'):
            uid = c.execute('INSERT INTO users(email,name,password_hash,role,created_at) VALUES(%s,%s,%s,%s,%s) RETURNING id',
                            (role + '@fixture.invalid', role, 'not-a-password', role, now)).fetchone()['id']
            sessions[role] = uid
        fixtures = [
            ('Fixture China Sourcing', '+966500000201', '', 'source:x | جدة | استيراد من الصين / وسيط توريد', 'lead'),
            ('Fixture Foods Trading', '0500000202', 'food@fixture.invalid', 'source:x | الرياض | استيراد مواد غذائية', 'lead'),
            ('Fixture Plain Est.', '+966500000203', '', 'source:x | تبوك | ', 'lead'),
            ('Fixture Opted Out', '+966500000204', '', 'جدة استيراد', 'unsubscribed'),
            ('Fixture No Contact', '', '', 'جدة استيراد', 'lead'),
            ('Fixture Suppressed', '+966500000205', '', 'جدة استيراد', 'lead'),
            ('Fixture Duplicate Phone', '+966500000201', '', 'جدة', 'lead'),
        ]
        for name, phone, email, notes, status in fixtures:
            c.execute('INSERT INTO accounts(name,country,status,notes,phone,email,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                      (name, 'السعودية', status, notes, phone, email or None, now, now))
        c.execute("INSERT INTO marketing_suppressions(channel,recipient,created_at) VALUES('whatsapp','+966500000205',%s)", (now,))
    for role, uid in list(sessions.items()):
        sid, csrf, _ = create_session(uid)
        sessions[role] = {'id': sid, 'csrf': csrf, 'user_id': uid}

    def request(role, method, path, **kwargs):
        client.cookies.clear()
        if role:
            client.cookies.set('gla_session', sessions[role]['id'])
        return client.request(method, path, headers={'Origin': 'http://testserver'}, **kwargs)

    before = {t: one('SELECT COUNT(*) n FROM ' + t)['n'] for t in ('accounts', 'outbound_messages', 'approvals')}
    # Access control.
    assert request(None, 'GET', '/daily-prospects').status_code == 303
    assert request('transport', 'GET', '/daily-prospects').status_code == 403
    assert request('sales', 'GET', '/daily-prospects').status_code == 200
    assert request('sales', 'POST', '/daily-prospects/build', data={}).status_code == 403

    # Without an AI key every message is the reviewed template; build is idempotent.
    result = dp.build_batch(day=date(2026, 10, 24), limit=10)
    assert result['added'] == 3 and result['ai_messages'] == 0, result
    assert dp.build_batch(day=date(2026, 10, 24), limit=10)['added'] == 0
    items = {r['company_name']: r for r in rows('SELECT * FROM daily_prospects ORDER BY score DESC')}
    assert set(items) == {'Fixture China Sourcing', 'Fixture Foods Trading', 'Fixture Plain Est.'}, set(items)
    ranked = [r['company_name'] for r in rows('SELECT company_name FROM daily_prospects ORDER BY score DESC')]
    assert ranked[0] == 'Fixture China Sourcing' and ranked[-1] == 'Fixture Plain Est.'
    china, food = items['Fixture China Sourcing'], items['Fixture Foods Trading']
    assert china['segment'] == 'china' and china['city'] == 'جدة' and china['phone'] == '+966500000201'
    assert food['phone'] == '+966500000202' and food['email'] == 'food@fixture.invalid'
    assert 'Fixture China Sourcing' in china['message'] and '2513' in china['message'] and '+966530130435' in china['message']
    assert all(r['status'] == 'pending' for r in items.values())

    page = request('sales', 'GET', '/daily-prospects?' + urlencode({'day': '2026-10-24'})).text
    assert 'Fixture China Sourcing' in page and 'فتح واتساب' not in page

    # Edit + approve one; bulk reject another.
    csrf = sessions['sales']['csrf']
    assert request('sales', 'POST', f"/daily-prospects/{china['id']}", data={'action': 'approve', 'message': 'x'}).status_code == 403
    edited = china['message'] + '\nمع التحية.'
    assert request('sales', 'POST', f"/daily-prospects/{china['id']}", data={'csrf': csrf, 'action': 'approve', 'message': edited}).status_code == 303
    approved = one('SELECT * FROM daily_prospects WHERE id=?', (china['id'],))
    assert approved['status'] == 'approved' and approved['message'] == edited and approved['opportunity_id']
    opp = one('SELECT * FROM opportunities WHERE id=?', (approved['opportunity_id'],))
    assert opp['stage'] == 'qualified' and opp['owner'] == dp.OWNER
    assert one("SELECT COUNT(*) n FROM sales_followups WHERE opportunity_id=? AND status='open'", (opp['id'],))['n'] == 1
    page = request('sales', 'GET', '/daily-prospects?' + urlencode({'day': '2026-10-24', 'status': 'approved'})).text
    assert 'https://wa.me/966500000201?text=' in page
    # Approving twice does nothing new.
    request('sales', 'POST', f"/daily-prospects/{china['id']}", data={'csrf': csrf, 'action': 'approve'})
    assert one('SELECT COUNT(*) n FROM opportunities')['n'] == 1

    assert request('admin', 'POST', '/daily-prospects/bulk', data={'csrf': sessions['admin']['csrf'], 'action': 'approve', 'ids': [str(food['id'])]}).status_code == 303
    food_after = one('SELECT * FROM daily_prospects WHERE id=?', (food['id'],))
    assert food_after['status'] == 'approved'
    # Email contact: an outbound draft is created, still unsent and unapproved.
    draft = one('SELECT * FROM outbound_messages WHERE opportunity_id=?', (food_after['opportunity_id'],))
    assert draft and draft['status'] == 'draft' and draft['recipient'] == 'food@fixture.invalid' and draft['sent_at'] is None
    assert request('admin', 'POST', '/daily-prospects/bulk', data={'csrf': sessions['admin']['csrf'], 'action': 'reject', 'ids': [str(items['Fixture Plain Est.']['id'])]}).status_code == 303
    assert one('SELECT status FROM daily_prospects WHERE id=?', (items['Fixture Plain Est.']['id'],))['status'] == 'rejected'

    # Outcomes move the opportunity.
    request('sales', 'POST', f"/daily-prospects/{china['id']}", data={'csrf': csrf, 'action': 'contacted'})
    request('sales', 'POST', f"/daily-prospects/{china['id']}", data={'csrf': csrf, 'action': 'interested'})
    assert one('SELECT status FROM daily_prospects WHERE id=?', (china['id'],))['status'] == 'interested'
    assert one('SELECT stage FROM opportunities WHERE id=?', (opp['id'],))['stage'] == 'proposal'
    request('sales', 'POST', f"/daily-prospects/{food['id']}", data={'csrf': csrf, 'action': 'no_answer'})
    assert one("SELECT COUNT(*) n FROM sales_followups WHERE opportunity_id=? AND status='open'", (food_after['opportunity_id'],))['n'] == 1
    # Invalid transition is ignored.
    request('sales', 'POST', f"/daily-prospects/{items['Fixture Plain Est.']['id']}", data={'csrf': csrf, 'action': 'interested'})
    assert one('SELECT status FROM daily_prospects WHERE id=?', (items['Fixture Plain Est.']['id'],))['status'] == 'rejected'

    summary = request('sales', 'GET', '/api/v7/daily-prospects/summary').json()
    assert summary['remaining_pool'] == 0
    after = {t: one('SELECT COUNT(*) n FROM ' + t)['n'] for t in ('accounts', 'outbound_messages', 'approvals')}
    assert after['accounts'] == before['accounts'] and after['approvals'] == before['approvals']
    assert one("SELECT COUNT(*) n FROM outbound_messages WHERE status<>'draft' OR sent_at IS NOT NULL")['n'] == 0
    print('PASS: ranked daily list, exclusions, idempotent batches, review/edit/approve, opportunities and follow-ups, no sends.')

    # AI opening is used only when it passes the fact filter.
    from app.daily_prospects import valid_opening, compose, score_contact
    assert valid_opening('يسعدنا أن نكون شريككم في تخليص شحناتكم القادمة عبر ميناء جدة.')
    for bad in ('نقدم خصم 20% لكم', 'زوروا www.example.com', 'السعر 500 ريال', 'short'):
        assert not valid_opening(bad), bad
    info = score_contact({'company_name': 'Test Foods', 'phone': '0500000299', 'notes': 'جدة غذائية'})
    with patch('app.daily_prospects.ai_opening', return_value='يسعدنا خدمة شحناتكم الغذائية القادمة عبر ميناء جدة.'):
        text, source = compose('Test Foods', info)
    assert source == 'ai' and text.split('\n')[2] == 'يسعدنا خدمة شحناتكم الغذائية القادمة عبر ميناء جدة.' and 'Test Foods' in text
    with patch('app.daily_prospects.ai_opening', return_value=None):
        assert compose('Test Foods', info)[1] == 'template'
    print('PASS: AI opening guarded with template fallback.')

    # Offer covers clearance and transport together with both licences.
    assert '2513' in text and dp.TRANSPORT_LICENCE in text and 'التخليص الجمركي والنقل' in text
    # Pending drafts from the earlier template are upgraded once; edited or decided ones are not touched.
    pitch = dp.DEFAULT_PITCH
    with db() as c:
        ids = []
        for key, msg, source, status in (
                ('directory:9001', dp._previous_template('Old Plain', pitch), 'template', 'pending'),
                ('directory:9002', '\n'.join([dp._previous_template('Old AI', pitch).split('\n')[0], 'يسعدنا خدمتكم في شحناتكم القادمة.'] + dp._previous_template('Old AI', pitch).split('\n')[2:]), 'ai', 'pending'),
                ('directory:9003', 'رسالة عدّلها الفريق يدويًا قبل الاعتماد للتواصل', 'template', 'pending'),
                ('directory:9004', dp._previous_template('Old Approved', pitch), 'template', 'approved')):
            ids.append(c.execute('''INSERT INTO daily_prospects(source_key,company_name,score,segment,reason,message,message_source,status,batch_date,created_at,updated_at)
                VALUES(%s,%s,50,'general','r',%s,%s,%s,%s,%s,%s) RETURNING id''', (key, key, msg, source, status, date(2026, 10, 23), now, now)).fetchone()['id'])
    with db() as c:
        c.execute("UPDATE daily_prospects SET company_name='Old Plain' WHERE id=%s", (ids[0],))
        c.execute("UPDATE daily_prospects SET company_name='Old AI' WHERE id=%s", (ids[1],))
        c.execute("UPDATE daily_prospects SET company_name='Old Approved' WHERE id=%s", (ids[3],))
    first = dp.refresh_pending_messages(); second = dp.refresh_pending_messages()
    assert first == 2 and second == 0
    msgs = [one('SELECT message FROM daily_prospects WHERE id=?', (i,))['message'] for i in ids]
    assert msgs[0] == dp.template_message('Old Plain', pitch)
    assert msgs[1] == dp._with_opening(dp.template_message('Old AI', pitch), 'يسعدنا خدمتكم في شحناتكم القادمة.')
    assert msgs[2] == 'رسالة عدّلها الفريق يدويًا قبل الاعتماد للتواصل'
    assert dp.TRANSPORT_LICENCE not in msgs[3]
    print('PASS: clearance + transport offer; earlier pending drafts upgraded, edited/approved untouched.')

    # Openings that re-introduce the sender are replaced (AI) or dropped (no AI); good ones stay.
    assert not dp.valid_opening('نتواصل معكم من شركة آفاق طويق للتخليص الجمركي والخدمات اللوجستية.')
    redundant = dp._with_opening(dp.template_message('Redundant Co', pitch), 'نتواصل معكم من شركة آفاق طويق للتخليص الجمركي.')
    good = dp._with_opening(dp.template_message('Good Co', pitch), 'يسعدنا التواصل مع فريقكم بشأن شحناتكم القادمة إلى جدة.')
    with db() as c:
        r1, r2, r3 = (c.execute('''INSERT INTO daily_prospects(source_key,company_name,score,segment,reason,message,message_source,status,batch_date,created_at,updated_at)
            VALUES(%s,%s,50,'general','r',%s,'ai','pending',%s,%s,%s) RETURNING id''', (k, n, m, date(2026, 10, 23), now, now)).fetchone()['id']
            for k, n, m in (('directory:9101', 'Redundant Co', redundant), ('directory:9102', 'Good Co', good), ('directory:9103', 'Redundant Two', redundant)))
    with patch('app.daily_prospects.ai_opening', side_effect=['يسعدنا خدمة شحناتكم القادمة عبر جدة.', None]):
        assert dp.repair_openings() == 2
    fixed = one('SELECT message,message_source FROM daily_prospects WHERE id=?', (r1,))
    assert fixed['message_source'] == 'ai' and fixed['message'].split('\n')[2] == 'يسعدنا خدمة شحناتكم القادمة عبر جدة.'
    assert one('SELECT message FROM daily_prospects WHERE id=?', (r2,))['message'] == good
    dropped = one('SELECT message,message_source FROM daily_prospects WHERE id=?', (r3,))
    assert dropped['message_source'] == 'template' and dropped['message'] == dp.template_message('Redundant Co', pitch)
    print('PASS: redundant AI openings repaired.')
    client.close()


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    target = urlsplit(url)
    if target.scheme not in ('postgres', 'postgresql') or target.hostname not in ('localhost', '127.0.0.1') or target.path != '/afaaq_test' or target.query:
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema = 'prospects_test_' + secrets.token_hex(6)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1'):
            raise AssertionError('External network blocked in daily prospects acceptance')
        return connect(sock, address)
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema + ' -c statement_timeout=30000'}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'ADMIN_EMAIL': 'bootstrap@fixture.invalid', 'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', local_only):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: daily prospects PostgreSQL acceptance; external sends 0.')


if __name__ == '__main__':
    main()
