"""English/Arabic isolation and concurrent claims in disposable local CI PostgreSQL.

All provider functions are mocked. The database URL must explicitly select the
local afaaq_test database; the script cannot be pointed at production.
"""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
import os
from pathlib import Path
import secrets
import sys
from unittest.mock import Mock, patch
from urllib.parse import quote, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
url = os.environ['AFAAQ_TEST_DATABASE_URL']
assert urlsplit(url).hostname in {'localhost', '127.0.0.1'}
assert urlsplit(url).path == '/afaaq_test'
import psycopg
schema = 'english_poster_test_' + secrets.token_hex(5)
with psycopg.connect(url, autocommit=True) as c:
    c.execute('CREATE SCHEMA ' + schema)
password = secrets.token_urlsafe(24)
os.environ.update(DATABASE_URL=url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
    DISCOVERY_AUTO_ENABLED='0', ENABLE_EXTERNAL_ACTIONS='0', AFAQ_DAILY_POSTER='0', AFAQ_DAILY_POSTER_EN='0',
    ADMIN_EMAIL='english-poster@example.invalid', ADMIN_PASSWORD=password, BROWSER_COOKIE_SECURE='0')
from app.bootstrap import app
from app import daily_poster as ar, daily_poster_english as en, meta_connect, prospect_autopilot
from app.storage import db, one
from fastapi.testclient import TestClient

try:
    uid = one('SELECT id FROM users WHERE email=?', (os.environ['ADMIN_EMAIL'],))['id']
    day = dt.date(2070, 1, 1)
    morning = dt.datetime(2070, 1, 1, 9, tzinfo=en.RIYADH)
    en.init()
    en.init()  # migration is additive and safe to run again
    assert ar.claim(day, ar.topic_for(day), 'Arabic fixture, preserve exactly')
    before = one('SELECT * FROM afaq_daily_posters WHERE day=?', (day,))
    assert en.run_for(day, morning)['skipped'] == 'disabled'
    assert one('SELECT count(*) n FROM afaq_daily_posters_en')['n'] == 0

    fb = Mock(return_value={'status': 'published', 'id': 'FB-fixture', 'url': 'https://facebook.com/fixture'})
    ig = Mock(return_value={'status': 'published', 'id': 'IG-fixture', 'url': 'https://instagram.com/fixture'})
    video = Mock(return_value={'status': 'publishing', 'tiktok': True, 'content_id': 999})
    os.environ.update(ENABLE_EXTERNAL_ACTIONS='1', AFAQ_DAILY_POSTER_EN='1', POSTER_EN_HOUR='9')
    with patch.object(prospect_autopilot, 'system_user', return_value=uid), \
         patch.object(en, 'render_poster', return_value=b'fixture-jpeg'), \
         patch.object(en, 'render_video', return_value=b'fixture-mp4'), \
         patch.object(meta_connect, 'connected', return_value=True), \
         patch.object(meta_connect, 'credentials', return_value={'page_id': 'fixture'}), \
         patch.object(ar, 'publish_facebook', fb), patch.object(en, 'publish_instagram', ig), \
         patch.object(en, 'publish_video', video), \
         patch('httpx.Client.request', side_effect=AssertionError('Real provider HTTP is forbidden')):
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda _: en.run_for(day, morning), range(8)))
        assert sum(r.get('status') == 'pending' for r in outcomes) == 1, outcomes
        assert sum(r.get('skipped') == 'already_claimed' for r in outcomes) == 7, outcomes
        assert en.run_for(day, morning)['skipped'] == 'already_claimed'
        assert en.run_for(day, morning.replace(hour=19))['skipped'] == 'outside_morning_window'
    assert fb.call_count == ig.call_count == video.call_count == 1
    assert one('SELECT count(*) n FROM afaq_daily_posters_en')['n'] == 1
    assert one('SELECT * FROM afaq_daily_posters WHERE day=?', (day,)) == before
    record = one('SELECT * FROM afaq_daily_posters_en WHERE day=?', (day,))
    assert record['status'] == 'pending'
    assert bytes(record['image']) == b'fixture-jpeg' and bytes(record['video']) == b'fixture-mp4'
    results = json.loads(record['results_json'])
    assert results['drafts']['status'] == 'saved' and len(results['drafts']['content_ids']) == 2
    assert one("SELECT count(*) n FROM social_content WHERE platform IN ('X','LinkedIn') AND status='draft'")['n'] == 2
    assert one("SELECT count(*) n FROM social_content WHERE platform='Facebook+Instagram' AND status='published'")['n'] == 1
    os.environ.update(ENABLE_EXTERNAL_ACTIONS='0', AFAQ_DAILY_POSTER_EN='0')
    client = TestClient(app, base_url='http://testserver')
    assert client.get('/daily-posters-en').status_code == 401
    assert client.get('/daily-posters-en/preview/0.jpg').status_code == 401
    assert client.get('/media/daily-poster-en/2070-01-01.jpg').content == b'fixture-jpeg'
    assert client.get('/media/daily-poster-en/2070-01-01.mp4').content == b'fixture-mp4'
    assert client.get('/media/daily-poster-en/not-a-date.jpg').status_code == 404
    assert client.get('/media/daily-poster-en/2070-01-01.txt').status_code == 404
    print('PASS: additive schema, 8 concurrent claims, one provider pass, same-day Arabic isolation, saved drafts, morning cutoff, public media and admin protection.')
finally:
    os.environ.update(ENABLE_EXTERNAL_ACTIONS='0', AFAQ_DAILY_POSTER_EN='0')
    with psycopg.connect(url, autocommit=True) as c:
        c.execute('DROP SCHEMA ' + schema + ' CASCADE')
