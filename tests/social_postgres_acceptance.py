"""Exercise new publishing routes on the existing disposable PostgreSQL fixture."""
from concurrent.futures import ThreadPoolExecutor
import copy
import datetime as dt
import json
import os
import time
from unittest.mock import patch


def run(client, app):
    from cryptography.fernet import Fernet
    from app import social_zernio as z
    from app.social_publishing import connection
    from app.storage import db, get_session, one, utcnow

    session = get_session(client.cookies.get('gla_session'))
    csrf = session['csrf']
    key = 'local-ci-social-key-never-live'
    refresh_path = '/settings/social/refresh'
    os.environ['ZERNIO_API_KEY'] = 'local-ci-whatsapp-key-untouched'
    os.environ['TOKEN_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
    assert client.post('/settings/social', data={'csrf': csrf, 'api_key': key}, follow_redirects=False).status_code == 428
    assert client.post(refresh_path, data={'csrf': csrf}, follow_redirects=False).status_code == 428
    # Exercise the real verification endpoints, not a prefilled step-up record.
    from app.mfa_stepup import gen_secret, enc, hotp
    totp_secret = gen_secret()
    now = utcnow()
    with db() as c:
        c.execute('INSERT INTO user_mfa(user_id,secret_enc,mfa_enabled,updated_at) VALUES(%s,%s,1,%s)',
                  (session['user_id'], enc(totp_secret), now))
    assert client.post('/mfa/step-up', data={'csrf': csrf, 'code': 'invalid'}, follow_redirects=False).status_code == 400
    assert not one('SELECT * FROM stepup_auth WHERE session_id=?', (session['id'],))
    for _ in range(2):  # Both INSERT and ON CONFLICT paths must persist successfully.
        response = client.post('/mfa/step-up', data={'csrf': csrf, 'code': hotp(totp_secret, int(time.time()) // 30),
                               'next': '/settings/social'}, follow_redirects=False)
        assert response.status_code == 303 and response.headers['location'] == '/settings/social', response.text
        assert one('SELECT * FROM stepup_auth WHERE session_id=?', (session['id'],))['expires_at'] > utcnow()
    # Recovery endpoints are intentionally disabled; keep that boundary intact.
    assert client.post('/mfa/recovery/step-up', data={'csrf': csrf, 'code': 'unused'}, follow_redirects=False).status_code == 404
    print('PASS: real TOTP verification persists step-up (insert and update); invalid codes are blocked; recovery routes remain disabled.')
    assert client.post('/settings/social', data={'csrf': 'bad', 'api_key': key}, follow_redirects=False).status_code == 403
    assert client.post(refresh_path, data={'csrf': 'bad'}, follow_redirects=False).status_code == 403
    with patch('app.social_publishing.verified_accounts', side_effect=AssertionError('Missing settings must not call Zernio')):
        assert client.post(refresh_path, data={'csrf': csrf}, follow_redirects=False).status_code == 400
    accounts = {'youtube': {'accountId': 'a' * 24, 'username': 'afaqtaw'},
                'tiktok': {'accountId': 'b' * 24, 'username': 'afaqt79'}}
    posts, creates, provider_calls = {}, [], []
    mode = {'timeout': False, 'wrong_account': False, 'published': False, 'partial': False, 'accounts_error': False, 'health_error': False}
    creator = {'creator': {'canPostMore': True}, 'privacyLevels': [{'value': 'PUBLIC_TO_EVERYONE'}],
               'postingLimits': {'interactionSettings': {x: {'enabled': True} for x in
                                ('allow_comment', 'allow_duet', 'allow_stitch')}},
               'commercialContentTypes': [{'value': 'brand_organic'}]}

    def provider(api_key, method, path, *, payload=None, request_id=None):
        assert api_key == key, 'Only the saved social key may enter provider requests'
        provider_calls.append((method, path))
        if path == '/accounts':
            assert method == 'GET'
            if mode['accounts_error']:
                raise z.PublishingError('اختبار فشل قراءة الحسابات')
            return {'accounts': [{'platform': p, '_id': a['accountId'], 'isActive': True,
                'username': 'sonaaq' if mode['wrong_account'] and p == 'youtube' else a['username']}
                for p, a in accounts.items()]}
        if path.endswith('/health'):
            assert method == 'GET'
            if mode['health_error']:
                raise z.PublishingError('اختبار فشل التحقق من الحساب')
            p, a = next((p, a) for p, a in accounts.items() if a['accountId'] in path)
            return {'platform': p, 'accountId': a['accountId'], 'username': a['username'],
                    'tokenStatus': {'valid': True}, 'permissions': {'canPost': True}}
        if 'creator-info' in path:
            return creator
        if method == 'POST' and path == '/posts':
            creates.append((copy.deepcopy(payload), request_id))
            assert payload['publishNow'] is False
            if mode['timeout']:
                raise z.PublishingError('نتيجة غير مؤكدة — اختبار انقطاع الاتصال')
            post_id = format(len(creates), '024x')
            result = {'_id': post_id, 'status': 'scheduled', 'platforms': [
                {'platform': x['platform'], 'accountId': x['accountId'], 'status': 'pending'} for x in payload['platforms']]}
            posts[post_id] = result
            return {'post': result}
        if method == 'GET' and path.startswith('/posts/'):
            post = copy.deepcopy(posts[path.split('/')[-1]])
            if mode['partial']:
                post['status'] = 'partial'
                for i, target in enumerate(post['platforms']):
                    target['status'] = 'published' if i == 0 else 'failed'
            elif mode['published']:
                post['status'] = 'published'
                for target in post['platforms']:
                    target['status'] = 'published'
                    target['platformPostUrl'] = 'https://www.youtube.com/watch?v=ci-only' if target['platform'] == 'youtube' else 'https://www.tiktok.com/@afaqt79/video/1'
            return {'post': post}
        raise AssertionError('Unexpected provider request: ' + method + ' ' + path)

    def draft():
        response = client.post('/content-center', data={'title': 'فيديو اختبار لا يُنشر', 'body': 'آفاق طويق',
            'platform': 'YouTube+TikTok', 'content_type': 'video', 'media_url': 'https://media.example.com/ci.mp4',
            'scheduled_at': (utcnow() + dt.timedelta(hours=3)).replace(tzinfo=None).isoformat()}, follow_redirects=False)
        assert response.status_code == 303, response.text
        url = response.headers['location']
        assert client.post(url + '/request-approval', follow_redirects=False).status_code == 303
        assert client.post(url + '/approve', follow_redirects=False).status_code == 303
        content = one('SELECT * FROM social_content WHERE id=?', (int(url.rsplit('/', 1)[1]),))
        form = {'csrf': csrf, 'version': str(content['updated_at']), 'preview_confirmed': 'yes',
                'scheduled_at': (utcnow() + dt.timedelta(hours=1)).isoformat(), 'synthetic': 'yes',
                'youtube_visibility': 'public', 'made_for_kids': 'no', 'tiktok_privacy': 'PUBLIC_TO_EVERYONE',
                'allow_comment': 'yes', 'allow_duet': 'no', 'allow_stitch': 'no', 'commercial_content': 'brand_organic'}
        return content, url, form

    with patch('app.social_zernio.provider_request', provider), \
         patch('app.social_publishing.provider_request', provider), \
         patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('Unexpected live HTTP')) as sync_http, \
         patch('httpx.AsyncHTTPTransport.handle_async_request', side_effect=AssertionError('Unexpected live HTTP')) as async_http:
        mode['wrong_account'] = True
        assert client.post('/settings/social', data={'csrf': csrf, 'api_key': key}, follow_redirects=False).status_code == 400
        assert not one('SELECT id FROM social_publishing_settings WHERE id=1')
        mode['wrong_account'] = False
        assert client.post('/settings/social', data={'csrf': csrf, 'api_key': key}, follow_redirects=False).status_code == 303
        saved = one('SELECT * FROM social_publishing_settings WHERE id=1')
        assert key not in saved['api_key_enc'] and connection()[0] == key
        assert key not in client.get('/settings/social').text
        content, url, form = draft()
        preview = client.get(url + '/schedule')
        assert preview.status_code == 200 and '@afaqtaw' in preview.text and '@afaqt79' in preview.text
        assert client.post(url + '/mark-published', follow_redirects=False).status_code == 409
        assert client.post(url + '/schedule', data=form, follow_redirects=False).status_code == 409
        assert creates == []  # Global external-action gate.
        os.environ['ENABLE_EXTERNAL_ACTIONS'] = '1'
        assert client.post(url + '/schedule', data={**form, 'preview_confirmed': ''}, follow_redirects=False).status_code == 409
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: client.post(url + '/schedule', data=form, follow_redirects=False).status_code, range(4)))
        assert results.count(303) == 1 and len(creates) == 1, results
        assert one('SELECT status FROM social_content WHERE id=?', (content['id'],))['status'] == 'scheduled'
        assert client.get(url).status_code == 200
        assert client.post(url + '/schedule', data=form, follow_redirects=False).status_code == 409
        assert len(creates) == 1
        mode['partial'] = True
        assert client.post(url + '/sync-publication', data={'csrf': csrf}, follow_redirects=False).status_code == 303
        assert one('SELECT status,published_at FROM social_content WHERE id=?', (content['id'],)) == {'status': 'partial', 'published_at': None}
        mode['partial'], mode['published'] = False, True
        assert client.post(url + '/sync-publication', data={'csrf': csrf}, follow_redirects=False).status_code == 303
        assert one('SELECT published_at FROM social_content WHERE id=?', (content['id'],))['published_at']
        mode['timeout'] = True
        uncertain, url, form = draft()
        assert client.post(url + '/schedule', data=form, follow_redirects=False).status_code == 303
        assert one('SELECT status FROM social_content WHERE id=?', (uncertain['id'],))['status'] == 'needs_review'
        assert client.post(url + '/schedule', data=form, follow_redirects=False).status_code == 409
        assert len(creates) == 2
        assert os.environ['ZERNIO_API_KEY'] == 'local-ci-whatsapp-key-untouched'
        assert client.get('/api/v7/readiness').json()['integrations'][0]['configured'] is True
        check_refresh(client, app, session, key, totp_secret, accounts, mode, creates, provider_calls)
        sync_http.assert_not_called()
        async_http.assert_not_called()
    print('PASS: encrypted isolated social key, identity validation, MFA/CSRF, explicit preview, global gate, concurrent single submission, partial/published receipts, timeout/no retry. Live posts: 0.')


def check_refresh(client, app, session, key, totp_secret, accounts, mode, creates, provider_calls):
    """Refresh only the saved mapping, with populated history and real guards."""
    from fastapi.testclient import TestClient
    from app import social_zernio as z
    from app.mfa_stepup import hotp
    from app.social_content import init_social_content
    from app.social_publishing import cipher, connection
    from app.storage import db, one, rows, utcnow

    path, form = '/settings/social/refresh', {'csrf': session['csrf']}
    settings_sql = 'SELECT * FROM social_publishing_settings WHERE id=1'

    def history():
        return {table: rows('SELECT * FROM ' + table + ' ORDER BY id')
                for table in ('social_content', 'social_publications', 'approvals')}

    # Deliberate legacy fixture: preserve the published receipt and payload for
    # the old account even after the current connection points at the new one.
    legacy = {'accountId': 'c' * 24, 'username': 'afaqtawaiq6'}
    publication = one('SELECT * FROM social_publications WHERE status=?', ('published',))
    payload, receipt = json.loads(publication['payload_json']), json.loads(publication['results_json'])
    for target in payload['platforms']:
        if target['platform'] == 'tiktok':
            target['accountId'] = legacy['accountId']
    for result in receipt:
        if result['platform'] == 'tiktok':
            result.update(accountId=legacy['accountId'], url='https://www.tiktok.com/@afaqtawaiq6/video/1')
    with db() as c:
        c.execute('UPDATE social_publications SET payload_json=%s,results_json=%s WHERE id=%s',
                  (json.dumps(payload), json.dumps(receipt), publication['id']))

    # Reproduce a previous startup which hid afaqt79 and seeded the legacy URL.
    current_url, old_url = 'https://www.tiktok.com/@afaqt79', 'https://www.tiktok.com/@afaqtawaiq6'
    seeded = one('SELECT * FROM social_channels WHERE platform=? AND profile_url=?', ('TikTok', current_url))
    assert seeded and seeded['created_by'] is None
    with db() as c:
        c.execute("UPDATE social_channels SET status='superseded' WHERE id=%s", (seeded['id'],))
        c.execute("""INSERT INTO social_channels(platform,account_name,profile_url,status,created_by,created_at,updated_at)
            VALUES('TikTok','Legacy seeded TikTok',%s,'saved',NULL,%s,%s)
            ON CONFLICT(platform,profile_url) DO NOTHING""", (old_url, utcnow(), utcnow()))
    old_seed = one('SELECT * FROM social_channels WHERE platform=? AND profile_url=?', ('TikTok', old_url))
    historical = history()
    other_channels = rows("SELECT * FROM social_channels WHERE platform!='TikTok' ORDER BY id")
    init_social_content()
    first_seed = rows('SELECT * FROM social_channels ORDER BY id')
    init_social_content()
    assert rows('SELECT * FROM social_channels ORDER BY id') == first_seed
    assert history() == historical
    assert rows("SELECT * FROM social_channels WHERE platform!='TikTok' ORDER BY id") == other_channels
    current_seed = one('SELECT * FROM social_channels WHERE id=?', (seeded['id'],))
    old_seed_after = one('SELECT * FROM social_channels WHERE id=?', (old_seed['id'],))
    assert current_seed['status'] != 'superseded' and current_seed['created_at'] == seeded['created_at']
    assert old_seed_after == {**old_seed, 'status': 'superseded'}
    assert one('SELECT COUNT(*) n FROM social_channels WHERE platform=? AND profile_url=?', ('TikTok', current_url))['n'] == 1
    screen = client.get('/content-center')
    assert screen.status_code == 200 and current_url in screen.text and old_url not in screen.text
    print('PASS: startup restores the required TikTok card, supersedes only the legacy seed, is idempotent, and retains publication history.')

    saved = one(settings_sql)
    saved_accounts = json.loads(saved['accounts_json'])
    old_accounts = {**saved_accounts, 'tiktok': legacy}
    with db() as c:
        c.execute('UPDATE social_publishing_settings SET accounts_json=%s WHERE id=1', (json.dumps(old_accounts),))
    stale = one(settings_sql)
    protected = {**history(), 'social_channels': rows('SELECT * FROM social_channels ORDER BY id')}
    activity_before = rows('SELECT * FROM activity ORDER BY id')
    calls_before, creates_before = len(provider_calls), copy.deepcopy(creates)
    screen = client.get('/settings/social')
    assert screen.status_code == 200 and screen.headers['cache-control'] == 'no-store'
    for visible in ('@afaqtaw', '@afaqt79', '@afaqtawaiq6', accounts['youtube']['accountId'], legacy['accountId'],
                    'action="/settings/social/refresh"', 'الحساب المحفوظ لا يطابق الحساب المعتمد'):
        assert visible in screen.text, visible
    assert key not in screen.text and stale['api_key_enc'] not in screen.text

    anonymous = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    assert anonymous.post(path, data=form, follow_redirects=False).status_code == 401
    for invalid in ({}, {'csrf': 'bad'}):
        assert client.post(path, data=invalid, follow_redirects=False).status_code == 403
    assert client.post(path, data=form, headers={'origin': 'https://attacker.invalid'}, follow_redirects=False).status_code == 403
    assert client.post(path, content=b'x' * 4097, follow_redirects=False).status_code == 413

    # The role guard must still reject a non-admin even when manage_social is
    # explicitly allowed for that role and this session has valid MFA.
    assert not one("SELECT * FROM role_permissions WHERE role='sales' AND permission='manage_social'")
    with db() as c:
        c.execute("INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES('sales','manage_social',1,%s)", (utcnow(),))
    try:
        for role in ('viewer', 'sales'):
            with db() as c:
                c.execute('UPDATE users SET role=%s WHERE id=%s', (role, session['user_id']))
            assert client.post(path, data=form, follow_redirects=False).status_code == 403
    finally:
        with db() as c:
            c.execute("UPDATE users SET role='admin' WHERE id=%s", (session['user_id'],))
            c.execute("DELETE FROM role_permissions WHERE role='sales' AND permission='manage_social'")

    assert not one("SELECT * FROM role_permissions WHERE role='admin' AND permission='manage_social'")
    with db() as c:
        c.execute("INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES('admin','manage_social',0,%s)", (utcnow(),))
    try:
        assert client.post(path, data=form, follow_redirects=False).status_code == 403
    finally:
        with db() as c:
            c.execute("DELETE FROM role_permissions WHERE role='admin' AND permission='manage_social'")

    mfa = one('SELECT * FROM user_mfa WHERE user_id=?', (session['user_id'],))
    stepup = one('SELECT * FROM stepup_auth WHERE session_id=?', (session['id'],))
    with db() as c:
        c.execute('UPDATE user_mfa SET mfa_enabled=0 WHERE user_id=%s', (session['user_id'],))
    try:
        assert client.post(path, data=form, follow_redirects=False).status_code == 428
    finally:
        with db() as c:
            c.execute('UPDATE user_mfa SET mfa_enabled=%s WHERE user_id=%s', (mfa['mfa_enabled'], session['user_id']))
    with db() as c:
        c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow() - dt.timedelta(minutes=1), session['id']))
    try:
        response = client.post(path, data=form, follow_redirects=False)
        assert response.status_code == 428
        assert response.json()['step_up'] == '/mfa/step-up?next=/settings/social'
        response = client.post('/mfa/step-up', data={**form,
            'code': hotp(totp_secret, int(time.time()) // 30), 'next': '/settings/social'}, follow_redirects=False)
        assert response.status_code == 303 and response.headers['location'] == '/settings/social'
        assert client.get(response.headers['location']).status_code == 200
    finally:
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (stepup['expires_at'], session['id']))
    assert one(settings_sql) == stale and len(provider_calls) == calls_before

    # An unreadable saved credential cannot be replaced or reach the provider.
    with db() as c:
        c.execute('UPDATE social_publishing_settings SET api_key_enc=%s WHERE id=1', ('invalid-local-ci-ciphertext',))
    unreadable = one(settings_sql)
    try:
        assert client.post(path, data=form, follow_redirects=False).status_code == 400
        assert one(settings_sql) == unreadable and len(provider_calls) == calls_before
    finally:
        with db() as c:
            c.execute('UPDATE social_publishing_settings SET api_key_enc=%s WHERE id=1', (stale['api_key_enc'],))

    # Both provider endpoints must be safe to fail before any settings write.
    for failure in ('accounts_error', 'health_error'):
        mode[failure] = True
        try:
            assert client.post(path, data=form, follow_redirects=False).status_code == 400
            assert one(settings_sql) == stale
        finally:
            mode[failure] = False
    youtube = copy.deepcopy(accounts['youtube'])
    accounts['youtube']['accountId'] = 'd' * 24
    try:
        assert client.post(path, data=form, follow_redirects=False).status_code == 400
        assert one(settings_sql) == stale
    finally:
        accounts['youtube'] = youtube

    calls_before = len(provider_calls)
    refreshed_at = utcnow()
    response = client.post(path, data=form, follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'] == '/settings/social', response.text
    refreshed = one(settings_sql)
    assert refreshed['api_key_enc'] == stale['api_key_enc']
    assert connection() == (key, accounts)
    assert json.loads(refreshed['accounts_json'])['youtube'] == old_accounts['youtube']
    assert refreshed['verified_at'] >= refreshed_at and refreshed['updated_by'] == session['user_id']
    assert provider_calls[calls_before:] == [('GET', '/accounts'),
        ('GET', '/accounts/' + accounts['youtube']['accountId'] + '/health'),
        ('GET', '/accounts/' + accounts['tiktok']['accountId'] + '/health')]
    screen = client.get('/settings/social')
    assert accounts['tiktok']['accountId'] in screen.text and '@afaqt79' in screen.text
    assert '@afaqtawaiq6' not in screen.text and 'الحساب المحفوظ لا يطابق الحساب المعتمد' not in screen.text
    assert key not in screen.text and refreshed['api_key_enc'] not in screen.text

    # Repeating refresh revalidates read-only and never rotates the saved key.
    assert client.post(path, data=form, follow_redirects=False).status_code == 303
    repeated = one(settings_sql)
    assert repeated['api_key_enc'] == refreshed['api_key_enc']
    assert repeated['accounts_json'] == refreshed['accounts_json']
    assert repeated['verified_at'] >= refreshed['verified_at']

    # Deterministic concurrent-save interleaving: validation completes, another
    # transaction replaces the saved key or map, then refresh attempts its write.
    for changed_field in ('api_key_enc', 'accounts_json'):
        replacement = []

        def validate_then_replace(api_key):
            verified = z.verified_accounts(api_key)
            value = (cipher().encrypt(key.encode()).decode() if changed_field == 'api_key_enc'
                     else json.dumps({**accounts, 'tiktok': legacy}))
            with db() as c:
                c.execute('UPDATE social_publishing_settings SET ' + changed_field + '=%s WHERE id=1', (value,))
            replacement.append(one(settings_sql))
            return verified

        try:
            with patch('app.social_publishing.verified_accounts', validate_then_replace):
                assert client.post(path, data=form, follow_redirects=False).status_code == 409
            assert replacement and one(settings_sql) == replacement[0]
        finally:
            with db() as c:
                c.execute("""UPDATE social_publishing_settings SET api_key_enc=%s,accounts_json=%s,
                    verified_at=%s,updated_by=%s WHERE id=1""",
                    (repeated['api_key_enc'], repeated['accounts_json'], repeated['verified_at'], repeated['updated_by']))

    assert {**history(), 'social_channels': rows('SELECT * FROM social_channels ORDER BY id')} == protected
    assert rows('SELECT * FROM activity WHERE id<=? ORDER BY id', (activity_before[-1]['id'],)) == activity_before
    refresh_logs = rows("SELECT * FROM activity WHERE action='social_connection_refreshed' ORDER BY id")
    assert len(refresh_logs) == 2
    assert all(entry['user_id'] == session['user_id'] and entry['summary'] for entry in refresh_logs)
    assert key not in str(refresh_logs) and repeated['api_key_enc'] not in str(refresh_logs)
    assert creates == creates_before and os.environ['ZERNIO_API_KEY'] == 'local-ci-whatsapp-key-untouched'
    assert one(settings_sql) == repeated and connection() == (key, accounts)
    print('PASS: stored-key refresh, required/saved UI, role/permission/MFA/CSRF guards, provider failures, YouTube identity preservation, concurrent-save conflicts, repeat safety, and complete history preservation. Refresh post calls: 0.')
