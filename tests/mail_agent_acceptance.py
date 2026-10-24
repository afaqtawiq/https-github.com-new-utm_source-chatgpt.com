"""Mail agent on local PostgreSQL with a fake mailbox. Non-loopback egress blocked; nothing real is sent."""
import datetime as dt
import os
import secrets
import socket
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FakeImap:
    def __init__(self):
        self.moves, self.created = [], []
        self.capabilities = ('IMAP4REV1', 'MOVE', 'UIDPLUS')

    def login(self, *a): return 'OK', []
    def select(self, *a): return 'OK', [b'3']
    def response(self, key): return key, [b'77']
    def list(self): return 'OK', [b'(\\HasNoChildren) "." INBOX', b'(\\HasNoChildren \\Junk) "." INBOX.Spam', b'(\\HasNoChildren \\Trash) "." INBOX.Trash']
    def create(self, name): self.created.append(name); return 'OK', []
    def uid(self, op, uid, *args): self.moves.append((op, uid) + args); return 'OK', []
    def logout(self): pass


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import mail_agent as ma, spacemail
    from app.storage import db, one, rows, create_session, utcnow
    now = utcnow()
    with db() as c:
        uid = c.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('mailadmin@fixture.invalid','a','x','admin',%s) RETURNING id", (now,)).fetchone()['id']
        c.execute('INSERT INTO spacemail_connections(user_id,password_enc,enabled,updated_at,address) VALUES(%s,%s,TRUE,%s,%s)',
                  (uid, spacemail.cipher().encrypt(b'fixture').decode(), now, spacemail.ADDRESS))
        c.execute('INSERT INTO user_mfa(user_id,mfa_enabled,updated_at) VALUES(%s,1,%s)', (uid, now))
    own = spacemail.ADDRESS
    mails = [
        # key, sender, safe reply address, subject, body, notice
        ('req', 'buyer@client.invalid', 'buyer@client.invalid', 'طلب عرض سعر تخليص', 'لدينا حاويتان 40 قدم ملابس تصل ميناء جدة، نحتاج تخليص ونقل إلى الرياض.', 'none'),
        ('fin', 'acc@vendor.invalid', 'acc@vendor.invalid', 'فاتورة رقم 5512', 'مرفق فاتورة الشهر للسداد.', 'none'),
        ('news', 'newsletter@shop.invalid', None, 'عروض الأسبوع', 'خصومات كبيرة. لإلغاء الاشتراك اضغط هنا unsubscribe', 'none'),
        ('bounce', 'mailer-daemon@mx.invalid', None, 'Undelivered', 'delivery failed', 'failure'),
        ('old', 'old@client.invalid', 'old@client.invalid', 'شحنة قديمة', 'نحتاج نقل حاوية', 'none'),
        ('again', 'buyer@client.invalid', 'buyer@client.invalid', 'متابعة الشحن', 'هل وصلكم طلب التخليص؟', 'none'),
    ]
    ids = {}
    with db() as c:
        for n, (key, sender, reply, subject, body, notice) in enumerate(mails, start=1):
            imported = now - dt.timedelta(hours=30) if key == 'old' else now + dt.timedelta(seconds=n)
            ids[key] = c.execute('''INSERT INTO spacemail_inbox(user_id,uidvalidity,uid,message_id,sender,subject,body,received,imported_at,
                sender_address,manual_reply_address,notice_kind) VALUES(%s,'77',%s,%s,%s,%s,%s,'',%s,%s,%s,%s) RETURNING id''',
                (uid, 100 + n, f'<{key}@fixture.invalid>', sender, subject, body, imported, sender, reply, notice)).fetchone()['id']

    sent = []
    def fake_send(user, to, subject, body, **kw):
        sent.append((to, subject, body, kw)); return '<reply-%d@afaqtawiqs.net>' % len(sent)

    # 1) Agent off (default): everything classified, nothing sent, auto categories shown as preview.
    with patch.object(spacemail, 'send', side_effect=fake_send):
        ma.tick()
    items = {r['inbox_id']: r for r in rows('SELECT * FROM mail_agent_items')}
    assert len(items) == 6 and not sent
    assert items[ids['req']]['category'] == 'service_request' and items[ids['req']]['action'] == 'preview'
    assert items[ids['fin']]['category'] == 'finance' and items[ids['fin']]['action'] == 'draft'
    assert items[ids['news']]['category'] == 'newsletter' and items[ids['news']]['action'] == 'no_reply'
    assert items[ids['bounce']]['category'] == 'notice' and items[ids['bounce']]['action'] == 'no_reply'
    assert own in items[ids['req']]['reply_body'] and '11/00098402' in items[ids['req']]['reply_body']
    print('PASS: classification and preview with auto-reply off; nothing sent.')

    # 2) Auto-reply on: only fresh, safe service mail gets one reply per sender per day; sensitive stays draft.
    with db() as c:
        c.execute('DELETE FROM mail_agent_items')
        c.execute('INSERT INTO mail_agent_settings(user_id,auto_reply,organize,daily_cap,enabled_at,updated_at) VALUES(%s,TRUE,FALSE,60,%s,%s)',
                  (uid, now - dt.timedelta(hours=40), now))
    with patch.dict(os.environ, {'ENABLE_EXTERNAL_ACTIONS': '1'}), patch.object(spacemail, 'send', side_effect=fake_send), \
            patch('app.mail_agent.ai_classify', return_value=None):
        ma.tick()
    items = {r['inbox_id']: r for r in rows('SELECT * FROM mail_agent_items')}
    assert [s[0] for s in sent] == ['buyer@client.invalid'], sent
    to, subject, body, kw = sent[0]
    assert subject == 'Re: طلب عرض سعر تخليص' and kw['in_reply_to'] == '<req@fixture.invalid>' and kw['automatic'] is True
    assert items[ids['req']]['action'] == 'auto_sent' and items[ids['req']]['reply_message_id']
    assert items[ids['again']]['action'] == 'draft' and '24' in items[ids['again']]['reason']
    assert items[ids['old']]['action'] == 'draft' and items[ids['fin']]['action'] == 'draft'
    print('PASS: auto reply once per sender, older and sensitive mail kept for approval.')

    # 3) Safety filter: invented prices/links force approval.
    assert not ma.safe_reply('نقدم لكم السعر 500 ريال للحاوية الواحدة مع التخليص والنقل.', 'نحتاج تخليص')
    assert not ma.safe_reply('زوروا موقعنا https://evil.invalid لمعرفة المزيد عن خدماتنا وأسعارنا الحالية.', '')
    assert ma.safe_reply('شكرًا لتواصلكم بخصوص الحاويتين 40 قدم، نرجو تزويدنا بموعد الوصول ومدينة التسليم.', 'لدينا حاويتان 40 قدم')
    result = {'category': 'service_request', 'urgency': 'normal', 'needs_reply': True, 'reply': 'السعر 900 ريال شامل كل شيء وموعد التسليم غدًا.'}
    action, reason = ma.decide({'manual_reply_address': 'x@y.invalid', 'imported_at': utcnow(), 'subject': '', 'body': ''}, result,
                               {'auto_reply': True, 'daily_cap': 60, 'enabled_at': None}, 0, False, False)
    assert action == 'draft' and 'فلتر' in reason
    print('PASS: replies with invented numbers, prices or links are not auto-sent.')

    # 4) Approval flow over HTTP (step-up required by the sensitive-route guard).
    client = TestClient(app, base_url='http://testserver', follow_redirects=False)
    sid, csrf, _ = create_session(uid)
    client.cookies.set('gla_session', sid)
    h = {'Origin': 'http://testserver'}
    page = client.get('/mail-agent?view=attention', headers=h)
    assert page.status_code == 200 and 'فاتورة رقم 5512' in page.text and 'التحقق لاعتماد الردود' in page.text
    blocked = client.post(f"/mail-agent/{ids['fin']}/send", data={'csrf': csrf, 'body': 'شكرًا، استلمنا الفاتورة وسيتم مراجعتها من الإدارة المالية.'}, headers=h)
    assert blocked.status_code == 428
    with patch('app.bootstrap.recent_stepup', return_value=True), patch('app.mfa_stepup.recent_stepup', return_value=True), \
            patch.dict(os.environ, {'ENABLE_EXTERNAL_ACTIONS': '1'}), patch.object(spacemail, 'send', side_effect=fake_send):
        ok = client.post(f"/mail-agent/{ids['fin']}/send", data={'csrf': csrf, 'body': 'شكرًا، استلمنا الفاتورة وسيتم مراجعتها من الإدارة المالية.'}, headers=h)
        assert ok.status_code == 303, ok.text
        again = client.post(f"/mail-agent/{ids['fin']}/send", data={'csrf': csrf, 'body': 'مرة ثانية'}, headers=h)
        assert again.status_code in (400, 409)
    assert sent[-1][0] == 'acc@vendor.invalid' and sent[-1][3]['automatic'] is False
    assert one('SELECT action FROM mail_agent_items WHERE inbox_id=?', (ids['fin'],))['action'] == 'approved_sent'
    assert client.post(f"/mail-agent/{ids['old']}/dismiss", data={'csrf': csrf}, headers=h).status_code == 303
    assert one('SELECT action FROM mail_agent_items WHERE inbox_id=?', (ids['old'],))['action'] == 'dismissed'
    print('PASS: approval requires step-up, sends once, dismiss works.')

    # 5) Organising: moves into folders, spam/newsletters to Junk/Trash, never expunges outside a move.
    fake = FakeImap()
    with db() as c:
        c.execute('UPDATE mail_agent_settings SET organize=TRUE WHERE user_id=%s', (uid,))
    with patch('app.mail_agent.imaplib.IMAP4_SSL', return_value=fake):
        moved = ma.organize(uid)
    targets = {m[2] for m in fake.moves}
    assert ('INBOX.Trash' in targets) and 'INBOX.Afaq-Requests' in targets and 'INBOX.Afaq-Finance' in targets, fake.moves
    assert all(m[0] == 'MOVE' for m in fake.moves) and 'INBOX.Afaq-Requests' in fake.created
    assert one('SELECT folder_status FROM mail_agent_items WHERE inbox_id=?', (ids['news'],))['folder_status'] == 'moved'
    assert moved == len(fake.moves)
    print('PASS: mailbox organised by moves only (recoverable).')

    # 6) The old fixed acknowledgement stays silent while the agent replies.
    assert ma.active_for(uid) is True
    client.close()


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    target = urlsplit(url)
    if target.scheme not in ('postgres', 'postgresql') or target.hostname not in ('localhost', '127.0.0.1') or target.path != '/afaaq_test' or target.query:
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema = 'mailagent_test_' + secrets.token_hex(6)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1'):
            raise AssertionError('External network blocked in mail agent acceptance')
        return connect(sock, address)
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema + ' -c statement_timeout=30000'}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '', 'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32),
               'ADMIN_EMAIL': 'bootstrap@fixture.invalid', 'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', local_only):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: mail agent PostgreSQL acceptance; real sends 0.')


if __name__ == '__main__':
    main()
