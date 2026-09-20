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
    os.environ['ZERNIO_API_KEY'] = 'local-ci-whatsapp-key-untouched'
    os.environ['TOKEN_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
    assert client.post('/settings/social', data={'csrf': csrf, 'api_key': key}, follow_redirects=False).status_code == 428
    # Exercise the real verification endpoints, not a prefilled step-up record.
    from app.mfa_stepup import gen_secret, enc, hotp
    from app.mfa_recovery import generate_codes
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
    recovery_code = generate_codes(session['user_id'])[0]
    with db() as c:
        c.execute('DELETE FROM stepup_auth WHERE session_id=%s', (session['id'],))
    response = client.post('/mfa/recovery/step-up', data={'csrf': csrf, 'code': recovery_code, 'next': '/settings/social'}, follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'] == '/settings/social', response.text
    assert one('SELECT * FROM stepup_auth WHERE session_id=?', (session['id'],))['expires_at'] > utcnow()
    assert client.post('/mfa/recovery/step-up', data={'csrf': csrf, 'code': recovery_code}, follow_redirects=False).status_code == 400
    print('PASS: real TOTP verification persists step-up (insert and update); recovery code creates step-up once; invalid codes remain blocked.')
    assert client.post('/settings/social', data={'csrf': 'bad', 'api_key': key}, follow_redirects=False).status_code == 403
    accounts = {'youtube': {'accountId': 'a' * 24, 'username': 'afaqtaw'},
                'tiktok': {'accountId': 'b' * 24, 'username': 'afaqtawaiq6'}}
    posts, creates = {}, []
    mode = {'timeout': False, 'wrong_account': False, 'published': False, 'partial': False}
    creator = {'creator': {'canPostMore': True}, 'privacyLevels': [{'value': 'PUBLIC_TO_EVERYONE'}],
               'postingLimits': {'interactionSettings': {x: {'enabled': True} for x in
                                ('allow_comment', 'allow_duet', 'allow_stitch')}},
               'commercialContentTypes': [{'value': 'brand_organic'}]}

    def provider(api_key, method, path, *, payload=None, request_id=None):
        assert api_key == key, 'The WhatsApp key must never enter social requests'
        if path == '/accounts':
            return {'accounts': [{'platform': p, '_id': a['accountId'], 'isActive': True,
                'username': 'sonaaq' if mode['wrong_account'] and p == 'youtube' else a['username']}
                for p, a in accounts.items()]}
        if path.endswith('/health'):
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
                    target['platformPostUrl'] = 'https://www.youtube.com/watch?v=ci-only' if target['platform'] == 'youtube' else 'https://www.tiktok.com/@afaqtawaiq6/video/1'
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

    with patch('app.social_zernio.provider_request', provider), patch('app.social_publishing.provider_request', provider):
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
        assert preview.status_code == 200 and '@afaqtaw' in preview.text and '@afaqtawaiq6' in preview.text
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
    print('PASS: encrypted isolated social key, identity validation, MFA/CSRF, explicit preview, global gate, concurrent single submission, partial/published receipts, timeout/no retry. Live posts: 0.')
