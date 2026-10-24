"""Declaration follow-up on local PostgreSQL. No FASAH access, no real sends."""
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import spacemail, finance_service as fs
    from app.fasah_fields import empty_fields
    from app.storage import db, one, rows, create_session, utcnow
    now = utcnow()
    with db() as c:
        uid = c.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('decl@fixture.invalid','a','x','admin',%s) RETURNING id", (now,)).fetchone()['id']
        sales = c.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('sales@fixture.invalid','s','x','sales',%s) RETURNING id", (now,)).fetchone()['id']
        c.execute('INSERT INTO user_mfa(user_id,mfa_enabled,updated_at) VALUES(%s,1,%s)', (uid, now))
        fields = empty_fields(); fields['importer']['value'] = 'Fixture Importer'; fields['bill_number']['value'] = 'MSKU1234567'
        case = c.execute("INSERT INTO fasah_workspace_drafts(created_by,title,fields_json,documents_json,created_at,updated_at) VALUES(%s,'Fixture case',%s,'[]',%s,%s) RETURNING id",
                         (uid, json.dumps(fields), now, now)).fetchone()['id']
    owner = fs.create_party({'name': 'آفاق طويق', 'kind': 'owner', 'identity_ref': 'CR-OWNER-FIXTURE', 'confirmed': '1'}, uid)
    customer = fs.create_party({'name': 'Fixture Customer', 'kind': 'counterparty', 'identity_ref': 'CR-CUST-FIXTURE', 'confirmed': '1'}, uid)
    client = TestClient(app, base_url='http://testserver', follow_redirects=False)
    sid, csrf, _ = create_session(uid)
    ssid, _, _ = create_session(sales)
    h = {'Origin': 'http://testserver'}
    client.cookies.set('gla_session', ssid)
    assert client.get('/declarations', headers=h).status_code == 403
    client.cookies.set('gla_session', sid)
    r = client.post('/declarations', data={'csrf': csrf, 'case_id': str(case), 'customer_name': 'Fixture Customer', 'customer_phone': '0500000777',
                                           'customer_email': 'buyer@fixture.invalid', 'bill_number': 'MSKU1234567', 'port': 'ميناء جدة'}, headers=h)
    assert r.status_code == 303, r.text
    did = int(r.headers['location'].rsplit('/', 1)[1])
    d = one('SELECT * FROM customs_declarations WHERE id=?', (did,))
    assert d['customer_phone'] == '+966500000777' and d['stage'] == 'preparing'
    page = client.get(f'/declarations/{did}', headers=h).text
    assert 'Fixture Importer' in page and 'MSKU1234567' in page
    entry = client.get(f'/api/v7/declarations/{did}/entry', headers=h).json()
    assert any(f['key'] == 'importer' and f['value'] == 'Fixture Importer' for f in entry['fields'])

    r = client.post(f'/declarations/{did}/stage', data={'csrf': csrf, 'stage': 'submitted', 'declaration_number': '2026-123456', 'note': 'قدمه الموظف'}, headers=h)
    assert r.status_code == 303
    ev = rows('SELECT * FROM customs_declaration_events WHERE declaration_id=? ORDER BY id', (did,))
    assert ev[-1]['stage'] == 'submitted' and '2026-123456' in ev[-1]['customer_message'] and ev[-1]['message_status'] == 'draft'
    assert client.post(f'/declarations/{did}/stage', data={'csrf': csrf, 'stage': 'duties_due', 'fee_customs_duty': '1,500.50', 'fee_tax': '2250', 'fee_clearance': '800'}, headers=h).status_code == 303
    assert client.post(f'/declarations/{did}/stage', data={'csrf': csrf, 'stage': 'duties_due', 'fee_tax': 'abc'}, headers=h).status_code == 400
    assert json.loads(one('SELECT fees FROM customs_declarations WHERE id=?', (did,))['fees'])['customs_duty'] == '1500.50'
    page = client.get(f'/declarations/{did}', headers=h).text
    assert 'https://wa.me/966500000777?text=' in page and 'التحقق لإرسال البريد' in page
    print('PASS: declaration created from FASAH case, stages, fees, customer update drafts.')

    eid = ev[-1]['id']
    assert client.post(f'/declarations/{did}/events/{eid}/send', data={'csrf': csrf}, headers=h).status_code == 428
    sent = []
    with patch('app.bootstrap.recent_stepup', return_value=True), patch.object(spacemail, 'send', side_effect=lambda *a, **k: sent.append(a) or '<m@x>'):
        assert client.post(f'/declarations/{did}/events/{eid}/send', data={'csrf': csrf}, headers=h).status_code == 303
        assert client.post(f'/declarations/{did}/events/{eid}/send', data={'csrf': csrf}, headers=h).status_code == 409
    assert len(sent) == 1 and sent[0][1] == 'buyer@fixture.invalid'
    print('PASS: customer email needs step-up and sends once.')

    r = client.post(f'/declarations/{did}/finance', data={'csrf': csrf, 'owner_id': str(owner), 'counterparty_id': str(customer), 'document_date': '2026-10-24',
                                                         'goods_amount': '50000', 'goods_currency': 'SAR', 'exchange_rate': '1', 'confirmation': '1'}, headers=h)
    assert r.status_code == 303, r.text
    doc_id = one('SELECT finance_document_id FROM customs_declarations WHERE id=?', (did,))['finance_document_id']
    doc = one('SELECT * FROM finance_documents WHERE id=?', (doc_id,))
    assert doc['kind'] == 'claim' and doc['status'] == 'draft' and doc['amount_minor'] == 455050 and doc['customs_ref'] == '2026-123456'
    detail = one('SELECT components FROM finance_claim_details WHERE document_id=?', (doc_id,))
    comps = detail['components'] if isinstance(detail['components'], dict) else json.loads(detail['components'])
    assert comps['customs_duty'] == 150050 and comps['tax'] == 225000 and comps['clearance'] == 80000
    assert one("SELECT COUNT(*) n FROM finance_entries")['n'] == 0
    assert client.post(f'/declarations/{did}/finance', data={'csrf': csrf, 'owner_id': str(owner), 'counterparty_id': str(customer), 'goods_amount': '1', 'goods_currency': 'SAR', 'exchange_rate': '1', 'confirmation': '1'}, headers=h).status_code == 303
    assert one('SELECT COUNT(*) n FROM finance_documents')['n'] == 1
    print('PASS: draft finance claim with itemised fees, nothing posted, idempotent.')
    client.close()


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    target = urlsplit(url)
    if target.scheme not in ('postgres', 'postgresql') or target.hostname not in ('localhost', '127.0.0.1') or target.path != '/afaaq_test' or target.query:
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema = 'decl_test_' + secrets.token_hex(6)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1'):
            raise AssertionError('External network blocked')
        return connect(sock, address)
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema + ' -c statement_timeout=30000'}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '', 'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32),
               'ADMIN_EMAIL': 'bootstrap@fixture.invalid', 'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', local_only):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: declarations PostgreSQL acceptance; real sends 0.')


if __name__ == '__main__':
    main()
