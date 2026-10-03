"""Full-app PostgreSQL acceptance. Fake credentials and mocked provider calls only."""
import datetime as dt
import os
from unittest.mock import patch

from fastapi.testclient import TestClient


def run(client, app):
    from app import runway_settings as r
    from app.media_settings import media_cipher
    from app.media_runway import RunwayError
    from app.storage import db, get_session, one, rows, utcnow
    from cryptography.fernet import InvalidToken

    session = get_session(client.cookies.get('gla_session'))
    csrf = session['csrf']
    path, check = '/settings/runway', '/settings/runway/check'
    key = 'local-ci-runway-key-never-live'
    form = {'csrf': csrf, 'api_key': key}
    fal = one('SELECT * FROM media_provider_settings WHERE id=1')
    social = one('SELECT * FROM social_publishing_settings WHERE id=1')
    counts = {table: one('SELECT COUNT(*) n FROM ' + table)['n']
              for table in ('media_jobs', 'advert_jobs', 'social_publications', 'social_content')}
    original_encryption_key = os.environ['TOKEN_ENCRYPTION_KEY']

    with patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('Unexpected live HTTP')), \
         patch('httpx.AsyncHTTPTransport.handle_async_request', side_effect=AssertionError('Unexpected live HTTP')):
        anonymous = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
        assert anonymous.get(path).status_code == 401
        for endpoint in (path, check):
            assert anonymous.post(endpoint, data=form).status_code == 401
        for role in ('viewer', 'sales', 'finance', 'transport', 'customs'):
            with db() as c:
                c.execute('UPDATE users SET role=%s WHERE id=%s', (role, session['user_id']))
            try:
                assert client.get(path).status_code == 403
                for endpoint in (path, check):
                    assert client.post(endpoint, data=form).status_code == 403
            finally:
                with db() as c:
                    c.execute("UPDATE users SET role='admin' WHERE id=%s", (session['user_id'],))
        with db() as c:
            c.execute("INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES('admin','manage_media',0,%s)", (utcnow(),))
        try:
            assert client.get(path).status_code == 403
            for endpoint in (path, check):
                assert client.post(endpoint, data=form).status_code == 403
        finally:
            with db() as c:
                c.execute("DELETE FROM role_permissions WHERE role='admin' AND permission='manage_media'")

        for mfa_enabled, expires_at in ((0, utcnow() + dt.timedelta(minutes=10)), (1, utcnow() - dt.timedelta(minutes=1))):
            with db() as c:
                c.execute('UPDATE user_mfa SET mfa_enabled=%s WHERE user_id=%s', (mfa_enabled, session['user_id']))
                c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (expires_at, session['id']))
            screen = client.get(path)
            assert screen.status_code == 200 and 'name="api_key"' not in screen.text
            for endpoint in (path, check):
                response = client.post(endpoint, data=form)
                assert response.status_code == 428
                if mfa_enabled:
                    assert response.json()['step_up'].endswith('next=/settings/runway')
        with db() as c:
            c.execute('UPDATE user_mfa SET mfa_enabled=1 WHERE user_id=%s', (session['user_id'],))
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow() + dt.timedelta(minutes=10), session['id']))

        screen = client.get(path)
        assert screen.status_code == 200 and screen.headers['cache-control'] == 'no-store'
        assert 'type="password"' in screen.text and 'name="api_key"' in screen.text
        for endpoint in (path, check):
            for bad_csrf in ('bad', 'مفتاح'):
                assert client.post(endpoint, data={**form, 'csrf': bad_csrf}).status_code == 403
            assert client.post(endpoint, data=form, headers={'origin': 'https://attacker.invalid'}).status_code == 403
            assert client.post(endpoint, content=b'x' * 4097).status_code == 413
            assert client.post(endpoint, content=b'\xff').status_code == 400
        assert client.post(path, content=('csrf=' + csrf + '&api_key=a&api_key=b').encode()).status_code == 400
        for invalid in ('', 'short', 'x' * 513, 'internal space value', 'control\x00character', 'مفتاح-غير-صحيح-للاختبار'):
            assert client.post(path, data={**form, 'api_key': invalid}).status_code == 400
        assert not r.connection_status()['configured']
        with patch.object(r, 'organization_balance', side_effect=AssertionError('Missing key must not call provider')):
            assert client.post(check, data={'csrf': csrf}).status_code == 400
        os.environ['TOKEN_ENCRYPTION_KEY'] = ''
        try:
            assert client.post(path, data=form).status_code == 503
            assert not r.connection_status()['configured']
        finally:
            os.environ['TOKEN_ENCRYPTION_KEY'] = original_encryption_key

        with patch.object(r, 'organization_balance', side_effect=AssertionError('Save/GET must not call provider')) as provider:
            response = client.post(path, data=form, follow_redirects=False)
            assert response.status_code == 303 and response.headers['location'] == path
            assert response.headers['cache-control'] == 'no-store'
            record = one('SELECT * FROM runway_provider_settings WHERE id=1')
            assert record['api_key_enc'] != key and r.credential()[0] == key
            try:
                media_cipher().decrypt(record['api_key_enc'].encode())
                raise AssertionError('Runway must use a different encryption domain from fal')
            except InvalidToken:
                pass
            with patch.object(r, 'credential', side_effect=AssertionError('GET must not decrypt credential')):
                screen = client.get(path)
                status = r.connection_status()
                assert status['configured'] and status['verified_at'] is None
                assert status['generation_enabled'] is False
            assert key not in screen.text and record['api_key_enc'] not in screen.text
            assert 'لم يُفحص الاتصال بعد' in screen.text
            provider.assert_not_called()

        for balance in (4042, 0):
            with patch.object(r, 'organization_balance', return_value=balance) as provider:
                response = client.post(check, data={'csrf': csrf}, follow_redirects=False)
                assert response.status_code == 303 and response.headers['cache-control'] == 'no-store'
                provider.assert_called_once_with(key)
            status = r.connection_status()
            assert status['verified_at'] and status['credit_balance'] == balance
            screen = client.get(path)
            assert f'<b>{balance} credits</b>' in screen.text
            assert 'توليد فيديو Runway يبدأ فقط بعد مراجعة' in screen.text
            assert key not in screen.text
            readiness = client.get('/api/v7/readiness').json()
            item = next(x for x in readiness['integrations'] if 'Runway' in x['name'])
            assert item['connection_verified'] and not item['live_tested']
            assert item['generation_enabled'] == (os.environ.get('ENABLE_EXTERNAL_ACTIONS') == '1')
            assert item['state_label'] in client.get('/readiness').text
        with patch.object(r, 'organization_balance', side_effect=RunwayError('تعذر فحص الاتصال')):
            response = client.post(check, data={'csrf': csrf})
            assert response.status_code == 502 and response.headers['cache-control'] == 'no-store'
        assert r.connection_status()['verified_at'] is None
        assert r.connection_status()['credit_balance'] is None
        assert r.connection_status()['checked_at']

        # A new key resets verification; an old request cannot verify the new key.
        def replace_while_checking(old_key):
            assert old_key == key
            response = client.post(path, data={**form, 'api_key': key + '-replacement'}, follow_redirects=False)
            assert response.status_code == 303
            return 9999
        with patch.object(r, 'organization_balance', side_effect=replace_while_checking):
            assert client.post(check, data={'csrf': csrf}).status_code == 409
        assert r.credential()[0] == key + '-replacement'
        status = r.connection_status()
        assert status['verified_at'] is None and status['credit_balance'] is None and status['checked_at'] is None
        current = one('SELECT * FROM runway_provider_settings WHERE id=1')
        assert client.post(path, data={**form, 'api_key': ''}).status_code == 400
        assert one('SELECT * FROM runway_provider_settings WHERE id=1') == current
        # Corrupt/unreadable ciphertext must fail closed without calling provider.
        with patch.object(r, 'organization_balance', return_value=4042):
            assert client.post(check, data={'csrf': csrf}, follow_redirects=False).status_code == 303
        assert r.connection_status()['verified_at']
        with db() as c:
            c.execute("UPDATE runway_provider_settings SET api_key_enc='invalid-fixture-ciphertext' WHERE id=1")
        try:
            with patch.object(r, 'organization_balance', side_effect=AssertionError('Unreadable key must not call provider')):
                assert client.post(check, data={'csrf': csrf}).status_code == 400
                assert r.connection_status()['verified_at'] is None
                assert r.connection_status()['credit_balance'] is None
        finally:
            with db() as c:
                c.execute('UPDATE runway_provider_settings SET api_key_enc=%s WHERE id=1', (current['api_key_enc'],))

        assert one('SELECT * FROM media_provider_settings WHERE id=1') == fal
        assert one('SELECT * FROM social_publishing_settings WHERE id=1') == social
        for table, count in counts.items():
            assert one('SELECT COUNT(*) n FROM ' + table)['n'] == count
        audit = str(rows("SELECT action,summary FROM activity WHERE entity_type='runway_provider'"))
        assert key not in audit and current['api_key_enc'] not in audit
        assert '/settings/runway' in client.get('/content-center').text
        assert '/settings/runway' in client.get('/settings/media').text
        readiness = client.get('/api/v7/readiness')
        assert readiness.status_code == 200 and 'Runway' in readiness.text
        item = next(x for x in readiness.json()['integrations'] if 'Runway' in x['name'])
        assert item['configured'] and not item['live_tested'] and not item['generation_enabled']
        assert key not in readiness.text and current['api_key_enc'] not in readiness.text
    print('PASS: isolated Runway key encryption; role/permission/MFA/CSRF guards; read-only balance and zero-credit display; replacement/race/error handling; no key echo/logs; fal/social/jobs unchanged. Live HTTP and generation: 0.')
