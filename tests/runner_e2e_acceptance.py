"""Work-computer runner end to end on a TRIAL device: real PostgreSQL + the real app over HTTP + the real runner
with a headless browser + a local dummy site. Dummy files only; no external network, nothing real is sent."""
import base64
import os
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'desktop-runner'))
SITE = {'posts': 0}


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, body, ctype='text/html; charset=utf-8', status=200, headers=None):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        port = self.server.server_address[1]
        if self.path == '/page':
            return self.reply('<html><title>صفحة وهمية</title><body><h1>كشف تجريبي</h1><p>بيان 123</p></body></html>')
        if self.path == '/redirect-out':
            return self.reply('', status=302, headers={'Location': f'http://localhost:{port}/page'})
        if self.path == '/popup':
            return self.reply(f'<html><body><p>نافذة</p><script>window.open("http://localhost:{port}/page")</script></body></html>')
        if self.path == '/slow':
            return self.reply('<html><body><p>بطيئة</p><script>setTimeout(()=>{{}},1)</script></body></html>')
        if self.path == '/broken.pdf':
            return self.reply(b'%PDF-1.4 broken without end', 'application/pdf')
        if self.path == '/login':
            return self.reply('<html><body><input type="password" name="p"></body></html>')
        if self.path == '/form':
            return self.reply('<html><body><form method="post" action="/form"><label>اسم العميل <input name="n"></label>'
                              '<label>كلمة المرور <input type="password" name="p"></label><button>إرسال</button></form></body></html>')
        return self.reply('nf', status=404)

    def do_POST(self):
        SITE['posts'] += 1
        return self.reply('<html><body>تم</body></html>')


def run():
    import uvicorn
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import agent_runner
    from app.storage import db, create_session, utcnow
    import afaq_runner as runner

    site = ThreadingHTTPServer(('127.0.0.1', 0), Site)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    sport = site.server_address[1]
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); aport = sock.getsockname()[1]; sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=aport, log_level='warning'))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    base = f'http://127.0.0.1:{aport}'
    client = TestClient(app, base_url='http://testserver', follow_redirects=False)
    now = utcnow()
    with db() as c:
        admin = c.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('runner-admin@fixture.invalid','a','x','admin',%s) RETURNING id", (now,)).fetchone()['id']
        viewer = c.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('runner-viewer@fixture.invalid','v','x','viewer',%s) RETURNING id", (now,)).fetchone()['id']
    sessions = {}
    for name, uid in (('admin', admin), ('viewer', viewer)):
        sid, csrf, _ = create_session(uid)
        sessions[name] = (sid, csrf)

    def as_user(name, method, path, **kw):
        client.cookies.clear()
        if name:
            client.cookies.set('gla_session', sessions[name][0])
        return client.request(method, path, headers={'Origin': 'http://testserver'}, **kw)

    # 1. Device token: shown once in the body (not the URL), stored hashed, revocable and rotatable.
    r = as_user('admin', 'POST', '/agent-runner/devices', data={'csrf': sessions['admin'][1], 'name': 'جهاز تجريبي'})
    assert r.status_code == 200 and 'location' not in r.headers and r.headers.get('cache-control') == 'no-store'
    token = r.text.split('afaq-runner-')[1].split('<')[0]
    token = 'afaq-runner-' + token
    with db() as c:
        stored = c.execute('SELECT token_hash FROM runner_devices').fetchone()['token_hash']
    assert token not in stored and stored == agent_runner.token_hash(token)
    assert as_user('viewer', 'GET', '/agent-runner').status_code == 403
    assert as_user(None, 'POST', '/api/runner/claim').status_code == 401
    print('PASS: token shown once (no URL), stored hashed; non-admin and tokenless access refused.')

    api = runner.Api(base, token)
    from playwright.sync_api import sync_playwright
    os.environ['AFAQ_RUNNER_DOWNLOADS'] = str(Path(os.environ['RUNNER_TMP']) / 'downloads')
    runner.DOWNLOADS = Path(os.environ['AFAQ_RUNNER_DOWNLOADS'])
    site_url = f'http://127.0.0.1:{sport}'

    def task(kind, **params):
        tid, _ = agent_runner.create_task(kind, params, 'test')
        assert tid, kind
        return tid

    def status(tid):
        with db() as c:
            return c.execute('SELECT status FROM runner_tasks WHERE id=%s', (tid,)).fetchone()['status']

    def files(tid):
        with db() as c:
            return c.execute('SELECT name,verified,size FROM runner_files WHERE task_id=%s', (tid,)).fetchall()

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(Path(os.environ['RUNNER_TMP']) / 'profile'), headless=True, accept_downloads=True)

        def run_next():
            got = api.post('/api/runner/claim')
            return runner.run_one(api, got, context)

        # 2. Trial: dummy PDF downloaded, verified to open, uploaded; finish twice is refused.
        t1 = task('download_test')
        assert run_next() == 'done' and status(t1) == 'done'
        f = files(t1)
        assert len(f) == 1 and f[0]['verified'] and f[0]['size'] > 100
        assert as_user('admin', 'GET', '/agent-runner/files/1').status_code == 200
        assert as_user('viewer', 'GET', '/agent-runner/files/1').status_code == 403
        assert api.post('/api/runner/claim') == {'task': None}
        try:
            api.post(f'/api/runner/tasks/{t1}/finish', {'status': 'done'})
            raise AssertionError('second finish accepted')
        except Exception as exc:
            assert '409' in str(exc)
        print('PASS: trial download verified and stored; files only for authorized admins; a task runs and finishes once.')

        # 3. A broken file is never «done».
        t2 = task('download_file', url=site_url + '/broken.pdf')
        assert run_next() == 'failed' and not files(t2)[0]['verified']
        print('PASS: an unopenable download fails the task.')

        # 4. Allowlist on redirects and popups.
        t3 = task('read_page', url=site_url + '/redirect-out')
        assert run_next() in ('failed', 'stopped') and not files(t3)
        t4 = task('read_page', url=site_url + '/popup')
        run_next()
        with db() as c:
            texts = [r['text'] for r in c.execute('SELECT text FROM runner_steps WHERE task_id=%s', (t4,)).fetchall()]
        assert any('غير مسموح' in t for t in texts), texts
        assert agent_runner.create_task('read_page', {'url': 'https://evil.example.com/x'})[0] is None
        print('PASS: redirect and popup to a non-allowed address are blocked and stop the task.')

        # 5. No screenshot of a sign-in page.
        t5 = task('read_page', url=site_url + '/login')
        run_next()
        with db() as c:
            assert c.execute('SELECT COUNT(*) n FROM runner_steps WHERE task_id=%s AND screenshot IS NOT NULL', (t5,)).fetchone()['n'] == 0
        print('PASS: sign-in pages are never photographed.')

        # 6. Form filling: password field refused; submit waits for approval; denial sends nothing; approval sends once.
        assert agent_runner.create_task('fill_form', {'url': site_url + '/form', 'fields': [{'label': 'كلمة المرور', 'value': 'x'}]})[0] is None
        t6 = task('fill_form', url=site_url + '/form', fields=[{'label': 'اسم العميل', 'value': 'عميل تجريبي'}], submit_label='إرسال')

        def decide_when_asked(approve):
            for _ in range(200):
                with db() as c:
                    a = c.execute("SELECT id FROM runner_approvals WHERE task_id=%s AND status='pending'", (t6 if approve is False else t7,)).fetchone()
                if a:
                    agent_runner.decide(a['id'], approve, 'test')
                    return
                time.sleep(0.1)
        threading.Thread(target=decide_when_asked, args=(False,), daemon=True).start()
        assert run_next() == 'failed' and SITE['posts'] == 0
        t7 = task('fill_form', url=site_url + '/form', fields=[{'label': 'اسم العميل', 'value': 'عميل تجريبي'}], submit_label='إرسال')
        threading.Thread(target=decide_when_asked, args=(True,), daemon=True).start()
        assert run_next() == 'done' and SITE['posts'] == 1
        print('PASS: passwords never filled; submitting waits for approval; refused = nothing sent; approved = sent once.')

        # 7. Stop during execution.
        t8 = task('fill_form', url=site_url + '/form', fields=[{'label': 'اسم العميل', 'value': 'x'}], submit_label='إرسال')
        def stop_when_waiting():
            for _ in range(200):
                with db() as c:
                    if c.execute("SELECT 1 FROM runner_approvals WHERE task_id=%s", (t8,)).fetchone():
                        agent_runner.stop_task(t8)
                        return
                time.sleep(0.1)
        threading.Thread(target=stop_when_waiting, daemon=True).start()
        assert run_next() == 'stopped' and status(t8) == 'stopped' and SITE['posts'] == 1
        print('PASS: stop takes effect while the task is running; nothing is submitted after stop.')

        # 8. Revoke and rotate.
        r = as_user('admin', 'POST', '/agent-runner/devices/1/rotate', data={'csrf': sessions['admin'][1]})
        new_token = 'afaq-runner-' + r.text.split('afaq-runner-')[1].split('<')[0]
        assert runner.Api(base, token).post.__self__  # old api object
        try:
            api.post('/api/runner/claim'); raise AssertionError('old token still works')
        except Exception as exc:
            assert '401' in str(exc)
        assert runner.Api(base, new_token).post('/api/runner/claim') == {'task': None}
        as_user('admin', 'POST', '/agent-runner/devices/1/revoke', data={'csrf': sessions['admin'][1]})
        try:
            runner.Api(base, new_token).post('/api/runner/claim'); raise AssertionError('revoked token works')
        except Exception as exc:
            assert '401' in str(exc)
        print('PASS: rotate invalidates the old token; revoke disables the device.')
        context.close()
    server.should_exit = True
    site.shutdown()


def main():
    import psycopg
    import tempfile
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    target = urlsplit(url)
    if target.scheme not in ('postgres', 'postgresql') or target.hostname not in ('localhost', '127.0.0.1') or target.path != '/afaaq_test':
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'runner_test_' + secrets.token_hex(6)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect = socket.socket.connect

    def local_only(s, address):
        if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1'):
            raise AssertionError('External network blocked in runner acceptance')
        return connect(s, address)
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0', 'RUNNER_ALLOWED_DOMAINS': '127.0.0.1',
               'RUNNER_ALLOW_HTTP_LOOPBACK': '1', 'RUNNER_TMP': tempfile.mkdtemp(), 'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'}
        with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', local_only):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: work-computer runner acceptance on a trial device; external network 0, real data 0.')


if __name__ == '__main__':
    main()
