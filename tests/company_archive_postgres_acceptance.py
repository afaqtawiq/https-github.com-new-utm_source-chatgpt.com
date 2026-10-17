"""Full application archive check; synthetic records in a disposable local schema."""
import hashlib
import io
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql

url = os.environ['COMPANY_ARCHIVE_TEST_URL']
target = urlsplit(url)
assert target.hostname in ('localhost', '127.0.0.1') and target.path.endswith('_test')
assert not target.query and not target.fragment
schema = 'company_bootstrap_' + uuid4().hex
with psycopg.connect(url, hostaddr='127.0.0.1') as c:
    c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
password = secrets.token_urlsafe(24)
os.environ.update(DATABASE_URL=url, PGOPTIONS='-c search_path=' + schema,
    COMPANY_DOCUMENTS_ENABLED='1', DISCOVERY_AUTO_ENABLED='0', ENABLE_EXTERNAL_ACTIONS='0',
    ADMIN_EMAIL='company-archive-test@example.invalid', ADMIN_PASSWORD=password,
    BROWSER_COOKIE_SECURE='0')
sys.path.insert(0, str(Path(__file__).parents[1]))
try:
    from fastapi.testclient import TestClient
    from PIL import Image
    from app.bootstrap import app
    from app.storage import get_session, one, execute
    from app import company_documents as archive

    # No lifespan workers: only explicit local requests are exercised.
    client = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    assert client.get('/company-documents').status_code in (401, 403)
    response = client.post('/login', data={'email': 'company-archive-test@example.invalid',
        'password': password, 'next': '/company-documents'}, follow_redirects=False)
    assert response.status_code == 303
    session = get_session(client.cookies.get('gla_session'))
    assert session['role'] == 'admin'
    assert 'href="/company-documents"' in client.get('/dashboard').text
    assert client.get('/company-documents').status_code == 200
    blob = io.BytesIO(); Image.new('RGB', (8, 8), (11, 22, 33)).save(blob, 'PNG')
    content = blob.getvalue()
    fields = {'csrf': session['csrf'], 'name': 'SYNTHETIC ONLY', 'kind': 'other',
              'issued_on': '', 'expires_on': ''}
    files = {'file': ('synthetic.png', content, 'image/png')}
    assert client.post('/company-documents', data=fields, files=files,
        headers={'origin': 'https://untrusted.invalid'}, follow_redirects=False).status_code == 403
    assert client.post('/company-documents', data=fields, files=files, follow_redirects=False).status_code == 303
    row = one('SELECT id FROM company_documents WHERE sha256=?', (hashlib.sha256(content).hexdigest(),))
    response = client.get('/company-documents/' + str(row['id']) + '/download')
    assert response.status_code == 200 and response.content == content
    assert 'no-store' in response.headers['cache-control']
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-disposition'].startswith('attachment;')
    execute("UPDATE users SET role='viewer' WHERE id=?", (session['user_id'],))
    assert client.get('/company-documents/' + str(row['id']) + '/download').status_code == 403
    archive.ENABLED = False
    assert client.get('/company-documents').status_code == 404
    assert one('SELECT COUNT(*) n FROM company_documents')['n'] == 1
    print('PASS: full-app archive registration, admin login, navigation, origin/CSRF, original download, revocation and disabled gate. Synthetic only; external sends/uploads: 0.')
finally:
    with psycopg.connect(url, hostaddr='127.0.0.1', options='-c search_path=public') as c:
        c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
