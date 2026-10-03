"""Isolated full-app PostgreSQL Runway acceptance with zero live HTTP or spend.

Called by postgres_acceptance after the credential intake fixture. The only
credential consumed here is that fixture's deliberately fake Runway key.
"""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
from decimal import Decimal
from itertools import count
import os
import re
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient


def run(client, app):
    target = urlsplit(os.environ['DATABASE_URL'])
    assert target.hostname in {'localhost', '127.0.0.1'} and target.path == '/afaaq_test', \
        'Refuse database-writing acceptance outside the disposable local fixture'
    from app import runway_studio as s, runway_video_provider as p
    from app.media_runway import RunwayError
    from app.storage import db, get_session, one, rows, utcnow

    session = get_session(client.cookies.get('gla_session'))
    csrf, user_id = session['csrf'], session['user_id']
    fake_key = 'local-ci-runway-key-never-live-replacement'
    base = '/runway-studio'
    data = {'csrf': csrf, 'title': 'CI Runway representative scene',
            'prompt': 'A representative truck moving smoothly along a marked port road at sunrise.',
            'caption': 'آفاق طويق — مشهد اختباري تمثيلي لا يُنشر'}
    payload = b'ci-runway-video-fixture-0123456789'
    sequence = count(1)
    submitted, polled, downloaded, validated = [], [], [], []
    mode = {'balance': 4042, 'submit_error': False, 'estimate': Decimal(60),
            'status': 'pending', 'cost': Decimal(60), 'poll_error': False,
            'download_error': False, 'validate_error': False, 'late_receipt_job': None}
    created_jobs = []
    untouched_tables = ('media_provider_settings', 'media_jobs', 'advert_jobs',
                        'advert_exports', 'social_publishing_settings', 'social_publications')
    untouched = {table: rows('SELECT * FROM ' + table + ' ORDER BY ' + ('token' if table == 'advert_exports' else 'id'))
                 for table in untouched_tables}
    existing_content = rows('SELECT * FROM social_content ORDER BY id')
    saved = one('SELECT updated_at,checked_at,verified_at,credit_balance FROM runway_provider_settings WHERE id=1')
    assert saved, 'Run runway_settings_acceptance before this fixture'

    def job(jid):
        return one('SELECT * FROM runway_video_jobs WHERE id=%s', (jid,))

    def balance(key):
        assert key == fake_key, 'Only the known fake fixture key may reach a provider mock'
        return mode['balance']

    def submit(key, prompt):
        assert key == fake_key and prompt == data['prompt']
        task_id = f'00000000-0000-4000-8000-{next(sequence):012d}'
        submitted.append(task_id)
        if mode['submit_error']:
            raise RunwayError('Simulated ambiguous submission timeout; never retry')
        if mode['late_receipt_job'] is not None:
            # Deterministically pause the response after the durable claim,
            # letting the watchdog mark it uncertain before the receipt arrives.
            delayed = mode['late_receipt_job']
            assert job(delayed)['status'] == 'submitting' and job(delayed)['task_id'] is None
            with db() as c:
                c.execute('UPDATE runway_video_jobs SET updated_at=%s WHERE id=%s',
                          (utcnow() - dt.timedelta(minutes=10), delayed))
            s.process_job(delayed)
            assert job(delayed)['status'] == 'needs_review' and job(delayed)['task_id'] is None
        return {'task_id': task_id, 'estimated_credits': mode['estimate']}

    def poll(key, task_id):
        assert key == fake_key and task_id in submitted
        polled.append(task_id)
        if mode['poll_error']:
            raise RunwayError('Simulated malformed task response')
        result = {'status': mode['status'], 'cost_credits': mode['cost']
                  if mode['status'] in ('succeeded', 'failed', 'cancelled') else None}
        if mode['status'] == 'succeeded':
            result['output_url'] = 'https://dnznrvs05pmza.cloudfront.net/acceptance/' + task_id + '.mp4'
        return result

    def download(url):
        assert url.startswith('https://dnznrvs05pmza.cloudfront.net/acceptance/')
        downloaded.append(url)
        if mode['download_error']:
            raise RunwayError('Simulated recoverable download failure')
        return payload

    def validate_file(value):
        assert value == payload
        validated.append(value)
        if mode['validate_error']:
            raise RunwayError('Simulated invalid MP4 dimensions, codec or duration')
        return {'container': 'mp4', 'codec': 'h264', 'width': 720, 'height': 1280,
                'duration': 5.0, 'size': len(value)}

    def prepare(**extra):
        response = client.post(base + '/prepare', data={**data, **extra}, follow_redirects=False)
        assert response.status_code == 303, (response.status_code, response.text)
        jid = int(response.headers['location'].rsplit('/', 1)[1])
        created_jobs.append(jid)
        return jid

    def approval_form(jid, **extra):
        return {'csrf': csrf, 'approve_cost': 'yes', 'approved_credits': '60',
                'quote_stamp': job(jid)['quote_expires_at'].isoformat(), **extra}

    def approve(jid, **extra):
        return client.post(f'{base}/{jid}/run', data=approval_form(jid, **extra), follow_redirects=False)

    def sync(jid):
        return client.post(f'{base}/{jid}/sync', data={'csrf': csrf}, follow_redirects=True)

    def due(jid):
        # Move only the isolated fixture's poll timestamp; never sleep or weaken
        # production polling guards just to make this suite run quickly.
        with db() as c:
            c.execute('UPDATE runway_video_jobs SET last_polled_at=%s WHERE id=%s',
                      (utcnow() - dt.timedelta(minutes=10), jid))

    def process(jid, *, manual=False):
        due(jid)
        s.process_job(jid, manual=manual)

    def fresh_mfa():
        with db() as c:
            c.execute('UPDATE user_mfa SET mfa_enabled=1 WHERE user_id=%s', (user_id,))
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s',
                      (utcnow() + dt.timedelta(minutes=10), session['id']))

    with patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('Unexpected live HTTP')) as live_sync, \
         patch('httpx.AsyncHTTPTransport.handle_async_request', side_effect=AssertionError('Unexpected live HTTP')) as live_async, \
         patch.object(s, 'organization_balance', balance), \
         patch.object(p, 'submit', submit), patch.object(p, 'poll', poll), \
         patch.object(p, 'download', download), patch.object(p, 'validate_file', validate_file), \
         patch.dict('os.environ', {'ENABLE_EXTERNAL_ACTIONS': '1'}):
        now = utcnow()
        with db() as c:
            c.execute('UPDATE runway_provider_settings SET checked_at=%s,verified_at=%s,credit_balance=4042 WHERE id=1',
                      (now, now))
        fresh_mfa()
        jid = prepare()
        assert submitted == [] and job(jid)['status'] == 'draft'
        assert job(jid)['estimated_credits'] == 60 and job(jid)['approved_by'] is None
        assert job(jid)['approved_at'] is None and job(jid)['task_id'] is None
        screen = client.get(f'{base}/{jid}')
        assert screen.status_code == 200 and screen.headers['cache-control'] == 'no-store'
        assert 'Gen-4.5' in screen.text and '720' in screen.text and '1280' in screen.text
        assert '60' in screen.text and 'name="approved_credits"' in screen.text
        assert 'name="quote_stamp"' in screen.text and 'name="approve_cost"' in screen.text
        assert 'هذا تقدير، وليس حدًا يفرضه Runway قبل الطلب' in screen.text
        assert 'الجدولة والنشر يحتاجان مراجعتهما وموافقتهما المنفصلتين' in screen.text
        assert fake_key not in screen.text
        before_get = job(jid)
        assert client.get(base).status_code == 200
        assert client.get(f'{base}/{jid}').status_code == 200
        assert job(jid) == before_get
        assert client.get(f'{base}/999999999').status_code == 404

        public = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
        protected_gets = (base, f'{base}/{jid}')
        protected_posts = ((base + '/prepare', data),
                           (f'{base}/{jid}/run', approval_form(jid)),
                           (f'{base}/{jid}/sync', {'csrf': csrf}))
        for path in protected_gets:
            assert public.get(path).status_code == 401
        for path, form in protected_posts:
            assert public.post(path, data=form).status_code == 401
        for role in ('viewer', 'sales', 'finance', 'transport', 'customs'):
            with db() as c:
                c.execute('UPDATE users SET role=%s WHERE id=%s', (role, user_id))
            try:
                for path in protected_gets:
                    assert client.get(path).status_code == 403
                for path, form in protected_posts:
                    assert client.post(path, data=form).status_code == 403
            finally:
                with db() as c:
                    c.execute("UPDATE users SET role='admin' WHERE id=%s", (user_id,))
        with db() as c:
            c.execute("INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES('admin','manage_media',0,%s)", (utcnow(),))
        try:
            for path in protected_gets:
                assert client.get(path).status_code == 403
            for path, form in protected_posts:
                assert client.post(path, data=form).status_code == 403
        finally:
            with db() as c:
                c.execute("DELETE FROM role_permissions WHERE role='admin' AND permission='manage_media'")

        for path, form in protected_posts:
            for invalid in ('', 'bad', 'مفتاح'):
                assert client.post(path, data={**form, 'csrf': invalid}).status_code == 403
            assert client.post(path, data=form, headers={'origin': 'https://attacker.invalid'}).status_code == 403
            assert client.post(path, content=b'\xff').status_code == 400
            assert client.post(path, content=b'x' * 65537).status_code == 413
            duplicate = 'csrf=' + csrf + '&csrf=' + csrf
            assert client.post(path, content=duplicate.encode()).status_code == 400
        before_jobs = one('SELECT COUNT(*) n FROM runway_video_jobs')['n']
        for field, invalid in (('title', ''), ('title', 'x' * 151), ('caption', ''),
                               ('caption', 'x' * 3001), ('prompt', ''), ('prompt', 'x' * 1001)):
            response = client.post(base + '/prepare', data={**data, field: invalid}, follow_redirects=False)
            assert response.status_code == 409, (field, response.status_code)
        # Keep the UTF-16 edge case below the form's byte cap so the prompt
        # validator, rather than the transport-size guard, rejects it.
        utf16_form = ('csrf=' + csrf + '&title=CI&caption=CI&prompt=' + '🚚' * 501).encode()
        assert client.post(base + '/prepare', content=utf16_form,
                           headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 409
        assert one('SELECT COUNT(*) n FROM runway_video_jobs')['n'] == before_jobs
        assert submitted == []
        max_caption = prepare(caption='ش' * 3000, prompt='🚚' * 500)
        assert job(max_caption)['caption'] == 'ش' * 3000 and job(max_caption)['prompt'] == '🚚' * 500
        escaped = prepare(title='<script>acceptance()</script>')
        escaped_screen = client.get(f'{base}/{escaped}')
        assert '&lt;script&gt;acceptance()&lt;/script&gt;' in escaped_screen.text
        assert '<script>acceptance()</script>' not in escaped_screen.text

        for mfa_enabled, expiry in ((0, utcnow() + dt.timedelta(minutes=10)),
                                    (1, utcnow() - dt.timedelta(minutes=1))):
            with db() as c:
                c.execute('UPDATE user_mfa SET mfa_enabled=%s WHERE user_id=%s', (mfa_enabled, user_id))
                c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (expiry, session['id']))
            assert approve(jid).status_code == 428
        fresh_mfa()
        original_form_data = s.form_data

        async def expire_mfa_after_body(request, active_session, *args, **kwargs):
            parsed = await original_form_data(request, active_session, *args, **kwargs)
            with db() as c:
                c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s',
                          (utcnow() - dt.timedelta(minutes=1), session['id']))
            return parsed

        try:
            with patch.object(s, 'form_data', expire_mfa_after_body):
                assert approve(jid).status_code == 428
            assert submitted == [] and job(jid)['status'] == 'draft'
            assert job(jid)['approved_at'] is None and job(jid)['reserved_bytes'] == 0
        finally:
            fresh_mfa()

        def expire_mfa_during_balance(key):
            assert key == fake_key
            with db() as c:
                c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s',
                          (utcnow() - dt.timedelta(minutes=1), session['id']))
            return mode['balance']

        try:
            with patch.object(s, 'organization_balance', expire_mfa_during_balance):
                assert approve(jid).status_code == 428
            assert submitted == [] and job(jid)['status'] == 'draft'
            assert job(jid)['approved_at'] is None and job(jid)['reserved_bytes'] == 0
        finally:
            fresh_mfa()

        for field, invalids in (('approve_cost', ('', 'no')),
                               ('approved_credits', ('', '0', '59', '61', '600', '60.0', '060', '+60',
                                                     ' 60 ', 'NaN', 'Infinity')),
                               ('quote_stamp', ('', 'old', (utcnow() - dt.timedelta(days=1)).isoformat()))):
            for invalid in invalids:
                assert approve(jid, **{field: invalid}).status_code == 409, (field, invalid)
        with patch.dict('os.environ', {'ENABLE_EXTERNAL_ACTIONS': '0'}):
            assert approve(jid).status_code == 409
        for low_balance in (0, 59):
            mode['balance'] = low_balance
            assert approve(jid).status_code == 409
        mode['balance'] = 4042
        with patch.object(s, 'organization_balance', side_effect=RunwayError('Simulated read-only balance failure')):
            assert approve(jid).status_code == 409
        with patch.object(s, 'QUOTA', p.MAX_EXPORT - 1):
            assert approve(jid).status_code == 409
        assert job(jid)['status'] == 'draft' and job(jid)['approved_by'] is None
        assert job(jid)['reserved_bytes'] == 0
        assert submitted == []
        s.tick()
        s.process_job(jid)
        assert sync(jid).status_code == 200
        assert submitted == [] and polled == []  # Workers and sync never pay for a draft.

        stale = prepare()
        with db() as c:
            c.execute('UPDATE runway_video_jobs SET quote_expires_at=%s WHERE id=%s',
                      (utcnow() - dt.timedelta(seconds=1), stale))
        assert approve(stale).status_code == 409
        changed_key = prepare()
        with db() as c:
            c.execute('UPDATE runway_video_jobs SET credential_version=%s WHERE id=%s',
                      (saved['updated_at'] - dt.timedelta(days=1), changed_key))
        assert approve(changed_key).status_code == 409 and submitted == []

        def rotate_during_balance(key):
            assert key == fake_key
            with db() as c:
                c.execute('UPDATE runway_provider_settings SET updated_at=%s WHERE id=1',
                          (saved['updated_at'] + dt.timedelta(seconds=1),))
            return 4042
        try:
            with patch.object(s, 'organization_balance', rotate_during_balance):
                assert approve(jid).status_code == 409
            assert job(jid)['status'] == 'draft' and submitted == []
        finally:
            with db() as c:
                c.execute('UPDATE runway_provider_settings SET updated_at=%s WHERE id=1', (saved['updated_at'],))

        # Every concurrent request carries the same exact quote; only the
        # transaction winning the claim may issue one paid submission.
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(lambda _: approve(jid).status_code, range(4)))
        assert statuses.count(303) == 1 and statuses.count(409) == 3, statuses
        assert len(submitted) == 1
        receipt = job(jid)
        assert receipt['task_id'] == submitted[0]
        assert receipt['approved_by'] == user_id and receipt['approved_at']
        assert receipt['approved_credits'] == 60 and receipt['provider_estimated_credits'] == 60
        assert receipt['reserved_bytes'] > 0 and receipt['content_id'] is None
        assert approve(jid).status_code == 409
        for status in ('pending', 'throttled', 'running'):
            mode['status'] = status
            process(jid)
            assert job(jid)['task_id'] == receipt['task_id'] and job(jid)['content_id'] is None
            assert len(submitted) == 1
        before_poll = len(polled)
        s.process_job(jid)
        assert sync(jid).status_code == 200
        assert len(polled) == before_poll  # Both entry points honor the five-second minimum.
        mode['status'] = 'succeeded'
        due(jid)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: s.process_job(jid), range(4)))
        complete = job(jid)
        assert complete['status'] == 'complete' and complete['content_id']
        assert complete['reserved_bytes'] == len(payload) and complete['final_credits'] == 60
        assert len(submitted) == 1 and validated
        content = one('SELECT * FROM social_content WHERE id=%s', (complete['content_id'],))
        assert content['title'] == data['title'] and content['body'] == data['caption']
        assert content['status'] == 'draft' and content['platform'] == 'YouTube+TikTok'
        assert content['content_type'] == 'video' and content['approval_id'] is None
        assert content['scheduled_at'] is None and content['published_at'] is None
        assert content['created_by'] == user_id
        exports = rows('SELECT * FROM runway_video_exports WHERE job_id=%s', (jid,))
        assert len(exports) == 1 and bytes(exports[0]['payload']) == payload
        token = exports[0]['token']
        assert re.fullmatch(r'[0-9a-f]{48}', token)
        export_path = '/runway-exports/' + token + '.mp4'
        assert urlsplit(content['media_url']).path == export_path
        before_poll, before_download = len(polled), len(downloaded)
        for _ in range(2):
            assert sync(jid).status_code == 200
            s.process_job(jid)
            s.tick()
        assert len(submitted) == 1 and len(polled) == before_poll and len(downloaded) == before_download
        assert one('SELECT COUNT(*) n FROM runway_video_exports WHERE job_id=%s', (jid,))['n'] == 1
        assert one('SELECT COUNT(*) n FROM social_content WHERE title=%s', (data['title'],))['n'] == 1
        assert not one('SELECT id FROM social_publications WHERE content_id=%s', (content['id'],))
        # Public, durable bytes remain available with the provider offline.
        with patch.object(p, 'poll', side_effect=AssertionError('Export must not call provider')), \
             patch.object(p, 'download', side_effect=AssertionError('Export must not redownload')):
            response = public.get(export_path)
            assert response.status_code == 200 and response.content == payload
            assert response.headers['content-type'].startswith('video/mp4')
            assert response.headers['accept-ranges'] == 'bytes'
            assert response.headers['x-content-type-options'] == 'nosniff'
            assert response.headers['content-length'] == str(len(payload))
            head = public.head(export_path)
            assert head.status_code == 200 and head.content == b''
            assert head.headers['content-length'] == str(len(payload))
            for byte_range, expected, start, end in (
                    ('bytes=2-7', payload[2:8], 2, 7),
                    ('bytes=4-', payload[4:], 4, len(payload) - 1),
                    ('bytes=-6', payload[-6:], len(payload) - 6, len(payload) - 1),
                    ('bytes=0-999999', payload, 0, len(payload) - 1)):
                partial = public.get(export_path, headers={'Range': byte_range})
                assert partial.status_code == 206 and partial.content == expected
                assert partial.headers['content-range'] == f'bytes {start}-{end}/{len(payload)}'
                assert partial.headers['content-length'] == str(len(expected))
            partial_head = public.head(export_path, headers={'Range': 'bytes=2-7'})
            assert partial_head.status_code == 206 and partial_head.content == b''
            assert partial_head.headers['content-length'] == '6'
            for invalid in ('bytes=999999-', 'bytes=5-2', 'bytes=-0', 'bytes=-',
                            'bytes=0-1,3-4', 'items=0-2', 'bytes=' + '9' * 100 + '-'):
                response = public.get(export_path, headers={'Range': invalid})
                assert response.status_code == 416 and response.headers['content-range'] == f'bytes */{len(payload)}'
            for invalid_token in ('f' * 48, 'x' * 48, 'a' * 47, 'a' * 49, str(jid)):
                assert public.get('/runway-exports/' + invalid_token + '.mp4').status_code == 404

        # A valid paid receipt arriving after the submitting watchdog must not
        # disappear. Keep review status, then recover only the same known task.
        delayed = prepare()
        before = len(submitted)
        mode['late_receipt_job'] = delayed
        try:
            assert approve(delayed).status_code == 303
        finally:
            mode['late_receipt_job'] = None
        late = job(delayed)
        assert len(submitted) == before + 1
        assert late['status'] == 'needs_review' and late['task_id'] == submitted[-1]
        assert late['provider_estimated_credits'] == 60 and not late['cost_alert']
        assert late['approved_at'] and late['approved_by'] == user_id
        assert late['content_id'] is None and late['reserved_bytes'] == p.MAX_EXPORT
        before_poll = len(polled)
        s.process_job(delayed)
        s.tick()
        assert len(polled) == before_poll and len(submitted) == before + 1
        assert approve(delayed).status_code == 409
        due(delayed)
        assert sync(delayed).status_code == 200
        assert job(delayed)['status'] == 'complete' and job(delayed)['task_id'] == late['task_id']
        assert polled[-1] == late['task_id'] and len(submitted) == before + 1
        assert one('SELECT COUNT(*) n FROM runway_video_exports WHERE job_id=%s', (delayed,))['n'] == 1
        assert sync(delayed).status_code == 200 and len(submitted) == before + 1

        # An uncertain submit or crash after claiming must never cause a paid
        # retry from a second click, manual sync, or the automatic worker.
        uncertain = prepare()
        mode['submit_error'] = True
        assert approve(uncertain).status_code == 303
        mode['submit_error'] = False
        assert job(uncertain)['status'] == 'needs_review' and job(uncertain)['task_id'] is None
        before = len(submitted)
        process(uncertain)
        assert sync(uncertain).status_code == 200
        s.tick()
        assert approve(uncertain).status_code == 409 and len(submitted) == before
        crashed = prepare()
        with db() as c:
            c.execute("UPDATE runway_video_jobs SET status='submitting',approved_by=%s,approved_at=%s,reserved_bytes=%s,updated_at=%s WHERE id=%s",
                      (user_id, utcnow() - dt.timedelta(minutes=10), p.MAX_EXPORT,
                       utcnow() - dt.timedelta(minutes=10), crashed))
        s.tick()
        assert job(crashed)['status'] == 'needs_review' and job(crashed)['task_id'] is None
        assert approve(crashed).status_code == 409 and len(submitted) == before

        # Preserve provider receipts even when their reported estimate or final
        # charge disagrees with the reviewed quote. Never hide the discrepancy.
        for estimate in (Decimal(61), None):
            mismatch = prepare()
            mode['estimate'] = estimate
            assert approve(mismatch).status_code == 303
            mismatch_row = job(mismatch)
            assert mismatch_row['task_id'] == submitted[-1]
            assert mismatch_row['provider_estimated_credits'] == estimate
            assert mismatch_row['status'] == 'needs_review' and mismatch_row['cost_alert']
            assert mismatch_row['content_id'] is None and approve(mismatch).status_code == 409
            before_poll = len(polled)
            process(mismatch)
            assert sync(mismatch).status_code == 200 and len(polled) == before_poll
            assert job(mismatch)['status'] == 'needs_review'
        mode['estimate'] = Decimal(60)
        for final_cost in (Decimal(61), None):
            charged = prepare()
            assert approve(charged).status_code == 303
            mode['status'], mode['cost'] = 'succeeded', final_cost
            process(charged)
            charged_row = job(charged)
            assert charged_row['task_id'] == submitted[-1] and charged_row['final_credits'] == final_cost
            assert charged_row['status'] == 'needs_review' and charged_row['cost_alert']
            assert charged_row['content_id'] is None and approve(charged).status_code == 409
            before_poll = len(polled)
            assert sync(charged).status_code == 200 and len(polled) == before_poll
        mode['cost'] = Decimal(60)

        for terminal in ('failed', 'cancelled'):
            failed = prepare()
            assert approve(failed).status_code == 303
            mode['status'] = terminal
            process(failed)
            failed_row = job(failed)
            assert failed_row['status'] == 'failed' and failed_row['task_id'] == submitted[-1]
            assert failed_row['content_id'] is None and failed_row['reserved_bytes'] == 0
            before = len(submitted)
            process(failed)
            assert sync(failed).status_code == 200
            assert approve(failed).status_code == 409 and len(submitted) == before

        malformed = prepare()
        assert approve(malformed).status_code == 303
        mode['poll_error'] = True
        process(malformed)
        mode['poll_error'] = False
        assert job(malformed)['task_id'] == submitted[-1] and job(malformed)['content_id'] is None
        assert job(malformed)['last_error'] and approve(malformed).status_code == 409
        before = len(submitted)
        mode['status'] = 'succeeded'
        invalid_file = prepare()
        assert approve(invalid_file).status_code == 303
        mode['validate_error'] = True
        process(invalid_file)
        mode['validate_error'] = False
        assert job(invalid_file)['status'] == 'needs_review' and job(invalid_file)['content_id'] is None
        assert not one('SELECT token FROM runway_video_exports WHERE job_id=%s', (invalid_file,))
        assert len(submitted) == before + 1 and approve(invalid_file).status_code == 409

        # Recovery fetches the original paid task again and creates one draft,
        # never another generation request or social publication.
        recovered = prepare()
        assert approve(recovered).status_code == 303
        original_task, before = job(recovered)['task_id'], len(submitted)
        mode['download_error'] = True
        process(recovered)
        mode['download_error'] = False
        assert job(recovered)['status'] == 'needs_review' and job(recovered)['content_id'] is None
        assert job(recovered)['task_id'] == original_task
        due(recovered)
        assert sync(recovered).status_code == 200
        assert job(recovered)['status'] == 'complete' and job(recovered)['task_id'] == original_task
        assert len(submitted) == before
        assert one('SELECT COUNT(*) n FROM runway_video_exports WHERE job_id=%s', (recovered,))['n'] == 1
        assert sync(recovered).status_code == 200 and len(submitted) == before

        assert one('SELECT * FROM media_provider_settings WHERE id=1') == untouched['media_provider_settings'][0]
        for table, original in untouched.items():
            assert rows('SELECT * FROM ' + table + ' ORDER BY ' + ('token' if table == 'advert_exports' else 'id')) == original, table
        for original in existing_content:
            assert one('SELECT * FROM social_content WHERE id=%s', (original['id'],)) == original
        generated = rows('''SELECT c.* FROM social_content c JOIN runway_video_jobs j ON j.content_id=c.id
                            WHERE j.id=ANY(%s) ORDER BY c.id''', (created_jobs,))
        for item in generated:
            assert item['status'] == 'draft' and item['approval_id'] is None
            assert item['scheduled_at'] is None and item['published_at'] is None
            assert item['platform'] == 'YouTube+TikTok'
            assert not one('SELECT id FROM social_publications WHERE content_id=%s', (item['id'],))
        audit = rows("SELECT action,summary FROM activity WHERE entity_type='runway_video'")
        assert audit and fake_key not in str(audit)
        live_sync.assert_not_called()
        live_async.assert_not_called()
        # Do not make the earlier credentials fixture look live-verified after
        # this local-only acceptance scenario has finished.
        with db() as c:
            c.execute('UPDATE runway_provider_settings SET checked_at=%s,verified_at=%s,credit_balance=%s WHERE id=1',
                      (saved['checked_at'], saved['verified_at'], saved['credit_balance']))
    print('PASS: isolated Runway preparation; auth/permission/MFA/CSRF and exact-cost gates; '
          'one concurrent paid submission; durable receipt, ambiguous/crash no-retry; '
          'cost discrepancies and malformed output; same-task download recovery; '
          'one unapproved YouTube+TikTok draft with durable Range/HEAD export; '
          'fal/social state unchanged. Live HTTP and spend: 0.')
