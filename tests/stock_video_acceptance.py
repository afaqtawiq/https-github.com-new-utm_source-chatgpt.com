"""Free stock-video production on isolated PostgreSQL. MOCK level: Pexels and the media CDN are simulated with
httpx.MockTransport serving locally generated clips; the Piper voice is replaced by a synthetic tone (the real voice
model is downloaded on the server); real FFmpeg edits the video. Nothing is published or sent."""
import json
import math
import os
import secrets
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def make_clip(path, seconds=7, w=1080, h=1920):
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc=size={w}x{h}:rate=30',
                    '-t', str(seconds), '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(path)], check=True)


def tone(path, seconds=3.0):
    rate = 22050
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        out.writeframes(b''.join(struct.pack('<h', int(8000 * math.sin(2 * math.pi * 220 * n / rate))) for n in range(int(rate * seconds))))


def run():
    import httpx
    from app import stock_video as sv, video_publish
    from app.storage import db
    sv.init(); video_publish.init()
    folder = Path(tempfile.mkdtemp())
    portrait, landscape = folder / 'p.mp4', folder / 'l.mp4'
    make_clip(portrait); make_clip(landscape, 6, 1280, 720)
    calls = []
    counter = [0]

    def handler(request):
        calls.append(str(request.url))
        host = request.url.host
        if host == 'api.pexels.com':
            assert request.headers['Authorization'] == 'test-pexels-key'
            q = request.url.params['query']
            counter[0] += 1
            base = counter[0] * 10
            return httpx.Response(200, json={'videos': [
                {'id': base + k, 'duration': 7, 'url': f'https://www.pexels.com/video/{base + k}/', 'user': {'name': 'Tester'},
                 'video_files': [{'file_type': 'video/mp4', 'width': 1080, 'height': 1920, 'link': f'https://videos.pexels.com/video-files/{base + k}.mp4'},
                                 {'file_type': 'video/mp4', 'width': 1920, 'height': 1080, 'link': 'https://videos.pexels.com/land.mp4'}]}
                for k in range(3)] + [{'id': 999, 'duration': 2, 'video_files': []}]})
        if host == 'videos.pexels.com':
            if request.url.path.endswith('redirect.mp4'):
                return httpx.Response(302, headers={'location': 'https://evil.example.com/x.mp4'})
            return httpx.Response(200, content=portrait.read_bytes())
        raise AssertionError('unexpected host ' + host)

    real_client = httpx.Client
    fake_client = lambda **kw: real_client(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != 'transport'})

    # 0) Without a key nothing starts.
    with patch.dict(os.environ, {'PEXELS_API_KEY': '', 'PIXABAY_API_KEY': ''}):
        assert 'PEXELS_API_KEY' in sv.start('اختبار')
    # 1) Plan guard: prices / digits / guarantees fall back to the safe plan.
    bad = {'scenes': [{'text': 'أرخص سعر 500 ريال', 'voice': 'نضمن لك', 'query': 'port'}] * 4}
    assert sv.clean_plan(bad, 'x') == sv.fallback_plan('x')
    good = sv.clean_plan({'caption': 'c', 'scenes': [{'text': 'شحنتك في أمان', 'voice': 'نخلص شحنتك باحترافية', 'query': 'port cranes!!'}] * 4}, 'x')
    assert good['scenes'][0]['query'] == 'port cranes' and len(good['scenes']) == 4

    with patch.dict(os.environ, {'PEXELS_API_KEY': 'test-pexels-key', 'ANTHROPIC_API_KEY': '', 'FREESOUND_API_KEY': ''}), \
         patch.object(sv.httpx, 'Client', fake_client), \
         patch.object(sv, 'narrate', lambda text, path, client: tone(path, 2.5 + len(text) / 40)):
        with db() as c:
            job = c.execute("INSERT INTO stock_video_jobs(topic,status,created_at) VALUES('اختبار','queued',NOW()) RETURNING id").fetchone()['id']
        vid, duration, credits, note, caption = sv.produce(job, 'التخليص في ميناء جدة', 'المدير')
    # 2) Final video: 1080x1920 H.264 with audio, 4 scenes + end card, stored for the existing publisher.
    with db() as c:
        row = c.execute('SELECT video,caption,status FROM team_videos WHERE id=%s', (vid,)).fetchone()
        usage = c.execute('SELECT COUNT(*) n FROM stock_clip_usage WHERE job_id=%s', (job,)).fetchone()['n']
        jobrow = c.execute('SELECT status,credits_json FROM stock_video_jobs WHERE id=%s', (job,)).fetchone()
    out = folder / 'final.mp4'
    out.write_bytes(bytes(row['video']))
    meta = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(out)],
                                     capture_output=True, check=True).stdout)
    video = [s for s in meta['streams'] if s['codec_type'] == 'video'][0]
    assert (video['width'], video['height'], video['codec_name']) == (1080, 1920, 'h264')
    assert any(s['codec_type'] == 'audio' for s in meta['streams'])
    assert 20 <= float(meta['format']['duration']) <= 40 and abs(float(meta['format']['duration']) - duration) < 1.5, duration
    assert row['status'] == 'ready' and 'Pexels' in row['caption'] and '0507665873' in row['caption']
    assert usage == 4 and jobrow['status'] == 'ready' and len(json.loads(jobrow['credits_json'])) == 4
    assert any('خلفية أصلية' in n for n in note)
    # 3) The same clips are never reused by the next video.
    with db() as c:
        used = {r['clip_id'] for r in c.execute('SELECT clip_id FROM stock_clip_usage').fetchall()}
    with patch.dict(os.environ, {'PEXELS_API_KEY': 'test-pexels-key'}), real_client(transport=httpx.MockTransport(handler)) as client:
        clip = sv.pick_clip('container port', job, client)
        assert clip['id'] not in used
        # 4) Downloads only from allowed media hosts; a redirect elsewhere is refused.
        try:
            sv.download('https://videos.pexels.com/redirect.mp4', folder / 'x.mp4', client)
            raise AssertionError('redirect to unknown host accepted')
        except sv.VideoError:
            pass
        try:
            sv.download('https://evil.example.com/a.mp4', folder / 'x.mp4', client)
            raise AssertionError('unknown host accepted')
        except sv.VideoError:
            pass
    # 5) Manager message: preview link + «نفذ» for the existing publish flow; nothing published.
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
        with patch('app.transport_desk.manager_chat', return_value=('966500000001', 'conv-m')):
            text = sv.manager_text(c, vid, duration, note, caption)
        action = json.loads(c.execute('SELECT command FROM whatsapp_voice_pending').fetchone()['command'].partition(':')[2])
    assert '/media/team-video/' in text and 'نفذ ' in text and action == {'tool': 'publish_video', 'video_id': vid}
    assert not any('graph.facebook' in u or 'zernio' in u for u in calls)


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'stock_video_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: free stock video planned, footage picked once, voiced, edited 1080x1920 with brand cards; publish only after «نفذ».')


if __name__ == '__main__':
    main()
