"""Run the real application against isolated PostgreSQL; never use production."""
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
url = os.environ['AFAAQ_TEST_DATABASE_URL']
assert urlsplit(url).hostname in {'localhost', '127.0.0.1'} and urlsplit(url).path == '/afaaq_test'
import psycopg
schema = 'fasah_test_' + secrets.token_hex(5)
with psycopg.connect(url, autocommit=True) as connection:
    connection.execute('CREATE SCHEMA ' + schema)
os.environ.update(DATABASE_URL=url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
                  DISCOVERY_AUTO_ENABLED='0', ENABLE_EXTERNAL_ACTIONS='0',
                  ADMIN_EMAIL='fasah@example.invalid', ADMIN_PASSWORD=secrets.token_urlsafe(24))
try:
    from app.bootstrap import app
    from app.storage import db, one, execute, utcnow, create_session
    from app.fasah_fields import FIELD_KEYS, FASAH_URL
    from fastapi.testclient import TestClient
    from test_fasah_workspace import sample_pdf
    client = TestClient(app, follow_redirects=False)
    assert client.get('/fasah-workspace').status_code == 401
    uid = one("SELECT id FROM users WHERE email='fasah@example.invalid'")['id']
    sid, csrf, _ = create_session(uid)
    client.cookies.set('gla_session', sid)
    client.headers['origin'] = 'http://testserver'
    assert client.get('/fasah-workspace').status_code == 200
    assert client.post('/fasah-workspace', data={'title': 'test', 'csrf': 'wrong'}).status_code == 403
    created = client.post('/fasah-workspace', data={'title': 'Local test <script>bad()</script>', 'csrf': csrf})
    assert created.status_code == 303
    path = created.headers['location']; case_id = int(path.rsplit('/', 1)[-1])
    def draft():
        row = one('SELECT * FROM fasah_workspace_drafts WHERE id=?', (case_id,))
        row['fields'] = json.loads(row['fields_json']); row['documents'] = json.loads(row['documents_json'])
        return row
    def post_text(text, name='invoice.txt'):
        return client.post(path + '/text', data={'csrf': csrf, 'revision': draft()['revision'], 'kind': 'invoice', 'name': name, 'text': text})
    page = client.get(path)
    assert page.status_code == 200 and '<script>bad()' not in page.text and '&lt;script&gt;' in page.text
    assert FASAH_URL in page.text and '<iframe' not in page.text
    assert "frame-src 'none'" in page.headers['content-security-policy']
    assert page.headers['cache-control'] == 'no-store'
    assert post_text('Invoice No: INV-111\nImporter: Test importer\nGross Weight: 100 KG').status_code == 303
    assert draft()['fields']['invoice_number']['value'] == 'INV-111'
    assert post_text('Invoice No: INV-111\nImporter: Test importer\nGross Weight: 100 KG').status_code == 409
    assert post_text('OTP: 654321').status_code == 422
    assert '654321' not in draft()['documents_json']
    assert post_text('Invoice No: INV-222', 'other.txt').status_code == 303
    assert len(draft()['fields']['invoice_number']['candidates']) == 2
    assert 'تعارضات غير محسومة' in client.get(path).text
    fields = draft()['fields']
    values = {'csrf': csrf, 'revision': draft()['revision'], **{'value_' + k: f['value'] for k, f in fields.items()}}
    values.update(value_invoice_number='INV-222', review_invoice_number='yes')
    saved_revision = values['revision']
    assert client.post(path + '/fields', data=values).status_code == 303
    assert draft()['fields']['invoice_number']['reviewed']
    assert client.post(path + '/fields', data=values).status_code == 409
    assert draft()['revision'] == saved_revision + 1
    values.update(revision=draft()['revision'], password='do-not-store')
    assert client.post(path + '/fields', data=values).status_code == 422
    assert 'do-not-store' not in draft()['fields_json']
    response = client.post(path + '/documents', data={'csrf': csrf, 'revision': draft()['revision'], 'kind': 'invoice'}, files={'file': ('invoice.pdf', sample_pdf(), 'application/pdf')})
    assert response.status_code == 303, response.text
    assert draft()['fields']['invoice_number']['reviewed'] is False
    assert any(c['value'] == 'TEST-772' for c in draft()['fields']['invoice_number']['candidates'])
    assert client.post(path + '/documents', data={'csrf': csrf, 'revision': draft()['revision'], 'kind': 'invoice'}, files={'file': ('fake.pdf', b'<html>not pdf</html>', 'application/pdf')}).status_code == 422
    assert client.post(path + '/documents', content=b'x', headers={'Content-Type': 'text/plain'}).status_code == 415
    document_id = draft()['documents'][0]['id']
    assert client.post(path + '/documents/' + document_id + '/remove', data={'csrf': csrf, 'revision': draft()['revision']}).status_code == 303
    assert not draft()['fields']['importer']['value']
    assert not any(c['document_id'] == document_id for c in draft()['fields']['invoice_number']['candidates'])
    client.headers['origin'] = 'https://untrusted.invalid'
    assert client.post(path + '/fields', data={'csrf': csrf}).status_code == 403
    client.headers['origin'] = 'http://testserver'
    # New document checklist routes operate on the same existing draft and revisions.
    from app.fasah_checklist import checklist
    def checked():
        row = draft()
        return checklist(row['documents'], json.loads(row['context_json']))
    def post_review(endpoint, **values):
        return client.post(path + endpoint, data={'csrf': csrf, 'revision': draft()['revision'], **values})
    profile = {'transaction': 'commercial_import', 'mode': 'land', 'goods': 'mixed goods', 'dispatch_country': 'UAE', 'origin_marking': 'yes'}
    assert post_review('/profile', **profile).status_code == 303
    assert post_review('/check').status_code == 303
    assert json.loads(draft()['context_json'])['checked_at']
    assert 'فحص اكتمال المستندات' in client.get(path).text
    assert post_review('/requirements/packing', choice='not_required', reason='', source='').status_code == 422
    decision = {'choice': 'not_required', 'reason': 'Confirmed for this case', 'source': 'Specific case reference'}
    assert post_review('/requirements/packing', **decision).status_code == 303
    assert not json.loads(draft()['context_json']).get('checked_at')
    assert next(r for r in checked()['rows'] if r['key'] == 'packing')['state'] == 'not_required'
    assert post_review('/profile', **{**profile, 'goods': 'changed goods'}).status_code == 303
    assert next(r for r in checked()['rows'] if r['key'] == 'packing')['state'] == 'review'
    assert post_review('/scope-review', confirmed='yes', reason='Checked all commodity requirements', source='Specific tariff reference').status_code == 303
    assert post_review('/extra-requirements', label='Specific certificate', choice='required', document_id='', reason='Required for this product', source='Specific official reference').status_code == 303
    assert checked()['rows'][-1]['state'] == 'missing'
    assert not json.loads(draft()['context_json']).get('scope_review')
    response = client.post(path + '/text', data={'csrf': csrf, 'revision': draft()['revision'], 'kind': 'origin', 'name': 'بوليصة شحن.pdf', 'text': 'DEC TYPE Re-Export\nDEC NO: EX-TEST\nA copy for review, unofficial'})
    assert response.status_code == 303
    draft_doc = draft()['documents'][-1]['id']
    assert post_review('/documents/' + draft_doc + '/review', kind='export_declaration', reviewed='yes').status_code == 422
    assert post_review('/documents/' + draft_doc + '/review', kind='export_declaration').status_code == 303
    assert draft()['documents'][-1]['kind'] == 'export_declaration'
    assert draft()['documents'][-1]['reviewed'] is False
    current_doc = draft()['documents'][0]['id']
    assert post_review('/documents/' + current_doc + '/review', kind='invoice', reviewed='yes').status_code == 303
    assert draft()['documents'][0]['reviewed'] is True
    assert post_review('/extra-requirements', label='Invalid reference', choice='required', document_id='not-owned', reason='reason here', source='source here').status_code == 422
    assert client.post(path + '/check', data={'csrf': 'wrong', 'revision': draft()['revision']}).status_code == 403
    assert client.post(path + '/check', data={'csrf': csrf, 'revision': 1}).status_code == 409
    for role in ('sales', 'transport', 'finance', 'viewer', 'customs', 'admin'):
        new_uid = execute('INSERT INTO users(email,name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                          (role + '@example.invalid', 'Test', 'unused', role, utcnow()))
        other_sid, other_csrf, _ = create_session(new_uid)
        client.cookies.set('gla_session', other_sid)
        assert client.get('/fasah-workspace').status_code == (200 if role in ('admin', 'customs') else 403)
        assert client.get(path).status_code == (404 if role in ('admin', 'customs') else 403)
        assert client.post(path + '/fields', data={'csrf': other_csrf}).status_code in (403, 404)
        for endpoint in ('/check', '/profile', '/requirements/packing', '/scope-review', '/extra-requirements', '/documents/' + current_doc + '/review'):
            assert client.post(path + endpoint, data={'csrf': other_csrf}).status_code in (403, 404)
        if role == 'customs':
            assert client.post('/fasah-workspace', data={'csrf': other_csrf, 'title': 'Customs draft'}).status_code == 303
    forbidden_routes = ['/fasah-workspace/login', path + '/submit', path + '/approve', path + '/otp']
    for route in forbidden_routes:
        assert client.post(route, data={'csrf': other_csrf}).status_code in (404, 405)
    print('PASS: document inventory, contextual completeness, existing-draft migration, classification correction, unofficial-document block, requirement/scope invalidation, custom certificates, persistence, real PDF upload, stale updates, CSRF, owner isolation, no official action routes.')
finally:
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute('DROP SCHEMA ' + schema + ' CASCADE')
