"""Exercise credential intake on the disposable full-app PostgreSQL fixture."""
import datetime as dt
import os
from unittest.mock import patch

from fastapi.testclient import TestClient


def run(client, app):
    from app.media_settings import media_connection
    from app.storage import db, get_session, one, rows, utcnow

    session = get_session(client.cookies.get('gla_session'))
    csrf = session['csrf']
    path = '/settings/media'
    key = 'local-ci-fal-id:local-ci-fal-secret-never-live'
    form = {'csrf': csrf, 'api_key': key}
    social = one('SELECT * FROM social_publishing_settings WHERE id=1')
    publications = one('SELECT COUNT(*) n FROM social_publications')['n']
    encryption_key = os.environ['TOKEN_ENCRYPTION_KEY']

    anonymous = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    assert anonymous.get(path).status_code == 401
    assert anonymous.post(path, data=form).status_code == 401
    for role in ('viewer', 'sales'):
        with db() as c:
            c.execute('UPDATE users SET role=%s WHERE id=%s', (role, session['user_id']))
        try:
            assert client.get(path).status_code == 403
            assert client.post(path, data=form).status_code == 403
        finally:
            with db() as c:
                c.execute("UPDATE users SET role='admin' WHERE id=%s", (session['user_id'],))

    with db() as c:
        c.execute("INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES('admin','manage_media',0,%s)", (utcnow(),))
    try:
        assert client.get(path).status_code == 403
        assert client.post(path, data=form).status_code == 403
    finally:
        with db() as c:
            c.execute("DELETE FROM role_permissions WHERE role='admin' AND permission='manage_media'")

    with db() as c:
        c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow() - dt.timedelta(minutes=1), session['id']))
    expired = client.get(path)
    assert expired.status_code == 200 and '/mfa/step-up?next=/settings/media' in expired.text
    assert 'name="api_key"' not in expired.text
    assert client.post(path, data=form).status_code == 428
    # Disposable test-session fixture; production MFA logic is unchanged.
    with db() as c:
        c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow() + dt.timedelta(minutes=10), session['id']))

    page = client.get(path)
    assert page.status_code == 200 and page.headers['cache-control'] == 'no-store'
    assert 'type="password"' in page.text and 'name="api_key"' in page.text
    assert client.post(path, data={**form, 'csrf': 'bad'}).status_code == 403
    assert client.post(path, data=form, headers={'origin': 'https://attacker.invalid'}).status_code == 403
    for invalid in ('', 'short', 'x' * 513, 'internal space value', 'control\x00character', 'مفتاح-غير-صحيح-للاختبار'):
        response = client.post(path, data={**form, 'api_key': invalid})
        assert response.status_code == 400
        assert key not in response.text
    assert client.post(path, content=b'x' * 4097).status_code == 413
    assert client.post(path, content=b'\xff').status_code == 400
    assert not one('SELECT id FROM media_provider_settings WHERE id=1')

    os.environ['TOKEN_ENCRYPTION_KEY'] = ''
    try:
        assert client.post(path, data=form).status_code == 503
        assert not one('SELECT id FROM media_provider_settings WHERE id=1')
    finally:
        os.environ['TOKEN_ENCRYPTION_KEY'] = encryption_key

    # Prevent real HTTP through provider transports while allowing TestClient.
    with patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('Unexpected provider call')) as sync_http, \
         patch('httpx.AsyncHTTPTransport.handle_async_request', side_effect=AssertionError('Unexpected provider call')) as async_http:
        for saved_key in (key, key + '-replacement'):
            response = client.post(path, data={**form, 'api_key': saved_key}, follow_redirects=False)
            assert response.status_code == 303 and response.headers['location'] == path
            record = one('SELECT * FROM media_provider_settings WHERE id=1')
            assert record['provider'] == 'fal' and record['updated_by'] == session['user_id']
            assert saved_key not in record['api_key_enc'] and media_connection() == saved_key
            page = client.get(path)
            assert 'مفتاح fal.ai محفوظ ومشفّر' in page.text
            assert 'حفظ المفتاح لا يثبت نجاح التوليد' in page.text and '/media-pricing' in page.text
            assert saved_key not in page.text and record['api_key_enc'] not in page.text
            assert 'value="' + saved_key not in page.text
        sync_http.assert_not_called()
        async_http.assert_not_called()

    current = one('SELECT * FROM media_provider_settings WHERE id=1')
    assert client.post(path, data={**form, 'api_key': ''}).status_code == 400
    assert one('SELECT * FROM media_provider_settings WHERE id=1') == current
    assert one('SELECT * FROM social_publishing_settings WHERE id=1') == social
    assert one('SELECT COUNT(*) n FROM social_publications')['n'] == publications
    assert os.environ['ZERNIO_API_KEY'] == 'local-ci-whatsapp-key-untouched'
    assert key not in str(rows("SELECT summary FROM activity WHERE action='media_credential_saved'"))
    assert '/settings/media' in client.get('/content-center').text
    assert '/settings/media' in client.get('/settings/social').text
    print('PASS: fal credential encryption and replacement, role/permission/MFA/CSRF guards, no secret echo or logs, invalid input preservation, Zernio isolation. Provider calls and paid generations: 0.')
