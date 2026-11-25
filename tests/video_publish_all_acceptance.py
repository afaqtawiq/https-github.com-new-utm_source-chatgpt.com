"""Publishing a team video to every connected platform, on isolated PostgreSQL. MOCK level: Zernio and Meta are
simulated (no network); the real social_content/social_publications records are written. Nothing is published."""
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IDS = {'linkedin': 'a' * 24, 'twitter': 'b' * 24, 'threads': 'c' * 24, 'facebook': 'd' * 24, 'youtube': 'e' * 24, 'tiktok': 'f' * 24,
       'pinterest': '1' * 24}
URLS = {'linkedin': 'https://www.linkedin.com/feed/update/1', 'twitter': 'https://x.com/afaqtql0/status/1',
        'threads': 'https://www.threads.net/@afaq/post/1'}


def run():
    from app import video_publish as vp
    from app.storage import db
    vp.init()
    caption = vp.caption_for('شحنتك وصلت الميناء؟\nنخلصها وننقلها لين مستودعك بدون تعقيد.\n#تخليص_جمركي #آفاق_طويق #ميناء_جدة #نقل_بري')

    # 1) Per-platform captions: X short, no links, WhatsApp + 2 tags; LinkedIn keeps the full text.
    x = vp.adapt('twitter', caption)
    assert len(x) <= 270 and 'http' not in x and '0507665873' in x and x.count('#') == 2 and x.startswith('شحنتك وصلت')
    assert vp.adapt('linkedin', caption) == caption and 'http' not in vp.adapt('threads', caption)
    assert len(vp.adapt('twitter', 'سطر طويل جدا ' * 80)) <= 270

    # 2) Every healthy connected extra account gets one post with its own caption; FB/YouTube/TikTok are not duplicated,
    #    an expired account is skipped, unconnected platforms are reported with the exact next step.
    sent = []
    def provider(key, method, path, *, payload=None, request_id=None):
        if path == '/accounts':
            return {'accounts': [{'_id': IDS[p], 'platform': p, 'username': 'afaq', 'isActive': True}
                                 for p in ('linkedin', 'twitter', 'threads', 'facebook', 'youtube', 'tiktok', 'pinterest')]}
        if path.endswith('/health'):
            valid = IDS['pinterest'] not in path
            return {'tokenStatus': {'valid': valid}, 'permissions': {'canPost': True}}
        if path == '/posts':
            sent.append(payload)
            return {'post': {'_id': '9' * 24, 'status': 'published', 'platforms': [
                {'platform': p['platform'], 'accountId': p['accountId'], 'status': 'published', 'platformPostUrl': URLS[p['platform']]}
                for p in payload['platforms']]}}
        raise AssertionError(path)
    with db() as c:
        uid = c.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone()['id']
    with patch('app.social_zernio.provider_request', provider), patch('app.social_publishing.connection', lambda: ('k', {})), \
         patch('app.prospect_autopilot.system_user', lambda: uid):
        results = vp.extra_platforms(7, 'https://example.com/media/team-video/7.mp4', caption, ai_generated=True)
    assert len(sent) == 1
    entries = {p['platform']: p for p in sent[0]['platforms']}
    assert set(entries) == {'linkedin', 'twitter', 'threads'}, entries
    assert entries['twitter']['customContent'] == vp.adapt('twitter', caption) and sent[0]['mediaItems'][0]['type'] == 'video'
    assert sent[0]['metadata']['aiGenerated'] is True and sent[0]['publishNow'] is True
    assert results['لينكدإن'].startswith('✅ https://www.linkedin.com') and results['إكس'].startswith('✅ https://x.com')
    assert results['سناب شات'].startswith('⚪') and 'يدويًا' in results['سناب شات']
    with db() as c:
        pub = c.execute("SELECT p.status, c.platform FROM social_publications p JOIN social_content c ON c.id=p.content_id").fetchone()
    assert pub['status'] == 'published' and pub['platform'] == 'linkedin+threads+twitter'

    # 3) Nothing extra connected → no post, only the connect hints.
    sent.clear()
    with patch('app.social_zernio.provider_request', lambda *a, **k: {'accounts': []} if a[2] == '/accounts' else {}), \
         patch('app.social_publishing.connection', lambda: ('k', {})):
        only_hints = vp.extra_platforms(8, 'https://example.com/v.mp4', caption)
    assert not sent and all(v.startswith('⚪') for v in only_hints.values()) and 'لينكدإن' in only_hints

    # 4) The whole publish: Meta, YouTube/TikTok (AI disclosure for cinematic videos) and the rest, one report.
    vid = vp.save(b'mp4', 'video/mp4', caption, 'test', ai_generated=True)
    seen, reports = {}, []
    class Now:
        def __init__(self, target, daemon=True):
            self.target = target
        def start(self):
            self.target()
    with patch('app.meta_connect.credentials', lambda: {'page_id': '1', 'token': 't'}), \
         patch.object(vp, 'facebook', lambda conn, link, text: 'https://www.facebook.com/1'), \
         patch.object(vp, 'instagram', lambda conn, link, text: 'https://www.instagram.com/reel/1'), \
         patch.object(vp, 'youtube_tiktok', lambda v, link, text, actor, ai: seen.setdefault('ai', ai) and 'published'), \
         patch.object(vp, 'extra_platforms', lambda v, link, text, ai: {'لينكدإن': '✅ ok'}), \
         patch.object(vp.threading, 'Thread', Now), \
         patch('app.owner_briefing.deliver', lambda text: reports.append(text) or _done()):
        started = vp.publish(vid, 'المدير')
    assert 'كل المنصات المربوطة' in started and seen['ai'] is True
    with db() as c:
        row = c.execute('SELECT status, results_json FROM team_videos WHERE id=%s', (vid,)).fetchone()
    res = json.loads(row['results_json'])
    assert row['status'] == 'done' and res['فيسبوك'].startswith('✅') and res['لينكدإن'] == '✅ ok' and res['يوتيوب/تيك توك'].startswith('✅')
    assert reports and 'لينكدإن' in reports[0]
    assert 'الفيديو غير موجود أو نُشر مسبقًا' in vp.publish(vid, 'المدير')


async def _noop():
    return None


def _done():
    return _noop()


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'video_publish_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env):
            import app.main  # noqa: F401  full schema (users, social_content, social_publications)
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: one «نفذ» publishes the video to every connected platform with a caption per platform; unconnected ones reported.')


if __name__ == '__main__':
    main()
