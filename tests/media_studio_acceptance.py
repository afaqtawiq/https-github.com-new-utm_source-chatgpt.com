"""Paid generation state machine against the real disposable PostgreSQL DB."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
from decimal import Decimal
from unittest.mock import patch


def run(client, app):
    from app import media_fal as f, media_studio as s
    from app.storage import db, get_session, one, utcnow

    session = get_session(client.cookies.get('gla_session'))
    csrf = session['csrf']
    data = {'csrf': csrf, 'kind': 'video', 'ratio': '9:16', 'title': 'CI representative truck scene',
            'caption': 'آفاق طويق — اختبار لا ينشر', 'image_prompt': s.DEFAULT_IMAGE, 'video_prompt': s.DEFAULT_VIDEO}
    quotes = {'image': Decimal('.03'), 'video': Decimal('.35')}
    calls = []
    mode = {'timeout': False, 'waiting': False}
    def prices(key):
        assert key.endswith('-replacement')
        return dict(quotes)
    def submit(key, stage, prompt, **kwargs):
        calls.append(stage)
        if mode['timeout']:
            raise f.MediaError('Simulated ambiguous timeout')
        return {'request_id': 'ci-' + stage + '-request-id', 'status_url': 'fixture', 'response_url': 'fixture'}
    def result(key, stage, receipt):
        if mode['waiting']:
            return None
        return 'https://v3.fal.media/files/ci.' + ('png' if stage == 'image' else 'mp4')
    def prepare(kind='video'):
        response = client.post('/media-studio/prepare', data={**data, 'kind': kind}, follow_redirects=False)
        assert response.status_code == 303, response.text
        return int(response.headers['location'].rsplit('/', 1)[1])
    def run_job(jid):
        return client.post(f'/media-studio/{jid}/run', data={'csrf': csrf, 'approve_cost': 'yes'}, follow_redirects=False)

    with patch.object(f, 'prices', prices), patch.object(f, 'submit', submit), patch.object(f, 'result', result):
        assert client.get('/media-studio').status_code == 200
        assert client.get('/media-pricing').status_code == 200 and calls == []
        jid = prepare()
        assert calls == [] and '0.3800' in client.get(f'/media-studio/{jid}').text
        assert client.post(f'/media-studio/{jid}/run', data={'csrf': csrf}).status_code == 409
        assert client.post(f'/media-studio/{jid}/run', data={'csrf': 'wrong', 'approve_cost': 'yes'}).status_code == 403
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow() - dt.timedelta(minutes=1), session['id']))
        assert run_job(jid).status_code == 428
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow() + dt.timedelta(minutes=10), session['id']))
        with patch.dict('os.environ', {'ENABLE_EXTERNAL_ACTIONS': '0'}):
            assert run_job(jid).status_code == 409
        quotes['image'] = Decimal('.04')
        assert run_job(jid).status_code == 409 and calls == []
        quotes['image'] = Decimal('.03')
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: run_job(jid).status_code, range(4)))
        assert responses.count(303) == 1 and calls == ['image'], responses
        mode['waiting'] = True
        s.tick()
        assert one('SELECT status FROM media_jobs WHERE id=?', (jid,))['status'] == 'image_pending'
        mode['waiting'] = False
        s.tick()
        assert one('SELECT status FROM media_jobs WHERE id=?', (jid,))['status'] == 'video_ready'
        # A read-status button cannot create a second paid request.
        assert client.post(f'/media-studio/{jid}/sync', data={'csrf': csrf}).status_code == 200
        assert calls == ['image']
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: s.process_job(jid), range(3)))
        assert calls == ['image', 'video']
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: s.process_job(jid), range(3)))
        job = one('SELECT * FROM media_jobs WHERE id=?', (jid,))
        assert job['status'] == 'complete' and job['content_id']
        content = one('SELECT * FROM social_content WHERE id=?', (job['content_id'],))
        assert content['status'] == 'draft' and content['platform'] == 'YouTube+TikTok'
        assert content['media_url'].endswith('.mp4') and content['approval_id'] is None
        assert one('SELECT COUNT(*) n FROM social_content WHERE title=?', (data['title'],))['n'] == 1
        assert not one('SELECT id FROM social_publications WHERE content_id=?', (job['content_id'],))
        assert run_job(jid).status_code == 409 and calls == ['image', 'video']

        image_job = prepare('image')
        assert run_job(image_job).status_code == 303
        s.tick()
        assert one('SELECT status FROM media_jobs WHERE id=?', (image_job,))['status'] == 'complete'
        assert calls == ['image', 'video', 'image']

        uncertain = prepare()
        mode['timeout'] = True
        assert run_job(uncertain).status_code == 303
        before = len(calls)
        assert one('SELECT status FROM media_jobs WHERE id=?', (uncertain,))['status'] == 'needs_review'
        s.tick()
        s.process_job(uncertain, allow_paid=False)
        assert run_job(uncertain).status_code == 409 and len(calls) == before
        mode['timeout'] = False

        stale = prepare()
        with db() as c:
            c.execute('UPDATE media_jobs SET quote_expires_at=%s WHERE id=%s', (utcnow() - dt.timedelta(minutes=1), stale))
        assert run_job(stale).status_code == 409 and len(calls) == before
        crashed = prepare()
        with db() as c:
            c.execute("UPDATE media_jobs SET status='image_submitting',updated_at=%s WHERE id=%s", (utcnow() - dt.timedelta(minutes=4), crashed))
        s.tick()
        assert one('SELECT status FROM media_jobs WHERE id=?', (crashed,))['status'] == 'needs_review'
        assert len(calls) == before

        increased = prepare()
        assert run_job(increased).status_code == 303
        s.process_job(increased)
        quotes['video'] = Decimal('.50')
        before = len(calls)
        s.process_job(increased)
        assert one('SELECT status,image_url FROM media_jobs WHERE id=?', (increased,))['status'] == 'needs_review'
        assert len(calls) == before
        quotes['video'] = Decimal('.35')
        changed_key = prepare()
        with db() as c:
            c.execute('UPDATE media_jobs SET credential_version=%s WHERE id=%s', (utcnow() - dt.timedelta(days=1), changed_key))
        assert run_job(changed_key).status_code == 409 and len(calls) == before
    print('PASS: live quote review, explicit cost approval, MFA/CSRF/global gates, concurrent single submissions, automatic image-to-video handoff, durable draft completion, image-only output, quote expiry, price increase/key changes, ambiguous receipt/crash no retry. Real paid requests: 0.')
