"""Existing-customer programme (transport cross-sell + win-back) on local PostgreSQL. Synthetic records; WhatsApp is
mocked; external network blocked; nothing leaves before the batch «نفذ» code."""
import asyncio
import datetime as dt
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from app.bootstrap import app  # noqa: F401
    from app import customer_care as cc, declarations, container_returns
    from app.storage import db, utcnow
    cc.init()
    declarations.init() if hasattr(declarations, 'init') else None
    container_returns.init()
    now = utcnow()
    old = now - dt.timedelta(days=90)
    with db() as c:
        uid = c.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('a@fixture.invalid','admin','x','admin',%s) RETURNING id",
                        (now,)).fetchone()['id']
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ)''')
        roster = [('شركة التخليص فقط', '0500000401'), ('شركة تخليص ونقل', '0500000402'), ('عميل متوقف', '0500000403'),
                  ('عميل نشط يكلمنا', '0500000404'), ('عميل أوقف الرسائل', '0500000405'), ('الفريق', '0507665873'),
                  ('عميل حديث بدون شحنات', '0500000406')]
        for name, phone in roster:
            c.execute('INSERT INTO accounts(name,country,status,phone,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s)',
                      (name, 'السعودية', 'customer', phone, now, now))
        for name, phone, when in (('شركة التخليص فقط', '0500000401', now - dt.timedelta(days=10)),
                                  ('شركة تخليص ونقل', '0500000402', now - dt.timedelta(days=12)),
                                  ('عميل متوقف', '0500000403', old)):
            c.execute('''INSERT INTO customs_declarations(customer_name,customer_phone,port,created_by,created_at,updated_at)
                VALUES(%s,%s,'ميناء جدة الإسلامي',%s,%s,%s)''', (name, phone, uid, when, when))
        c.execute('''INSERT INTO container_returns(container,customer,customer_phone,status,created_at,updated_at)
            VALUES('MSKU7654321','شركة تخليص ونقل','966500000402','open',%s,%s)''', (now - dt.timedelta(days=5), now - dt.timedelta(days=5)))
        c.execute('''INSERT INTO whatsapp_agent_jobs(account_id,message_id,event_id,sender,conversation_id,payload,idempotency_key,created_at,updated_at)
            VALUES('acc','m0','e0','966500000404','c4','{"question":"وين شحنتي"}','k0',NOW(),NOW())''')
        c.execute('''INSERT INTO accounts(name,country,status,phone,created_at,updated_at) VALUES('عميل نشط يكلمنا','x','customer','0500000404',%s,%s)''', (now, now))
        c.execute("INSERT INTO marketing_suppressions(channel,recipient,created_at) VALUES('whatsapp','+966500000405',%s)", (now,))

    names = {p['name']: p['segment'] for p in cc.candidates(now)}
    assert names == {'شركة التخليص فقط': 'cross_sell', 'عميل متوقف': 'win_back', 'عميل حديث بدون شحنات': 'win_back'}, names
    assert list(names)[0] == 'شركة التخليص فقط'  # cross-sell first

    with patch('app.transport_desk.manager_chat', return_value=('966500000001', 'conv-manager')):
        text = cc.prepare(now)
    assert 'دفعة #' in text and 'عرض النقل لعملاء التخليص: 1' in text and 'استرجاع عميل متوقف: 2' in text and 'نفذ ' in text
    assert '4,500 ريال للحاوية' in text and 'لإيقاف الرسائل أرسل: إيقاف' in text
    with db() as c:
        bid = c.execute('SELECT MAX(id) b FROM customer_care_batches').fetchone()['b']
        action = json.loads(c.execute('SELECT command FROM whatsapp_voice_pending').fetchone()['command'].partition(':')[2])
    assert action == {'tool': 'customer_care_send', 'batch': bid}
    assert not cc.due_today(now.replace(hour=12)) or now.astimezone(cc.RIYADH).weekday() in (4, 5)  # one batch per day

    # Template must match the exact message; ignore Meta: pretend APPROVED.
    from app import zernio_whatsapp as wa
    params = wa.template_parameters(cc.template_spec() | {'components': [{'type': 'BODY', 'text': cc.template_spec()['components'][0]['text']}]},
                                    cc.body('شركة التخليص فقط', cc.transport_offer(['ميناء جدة الإسلامي'])))
    assert params and params[0] == 'شركة التخليص فقط'
    sent = []
    with patch.object(cc, 'ensure_template', AsyncMock(return_value='APPROVED')), \
            patch.object(wa, 'send', AsyncMock(side_effect=lambda to, text, **k: sent.append(to))):
        result = asyncio.run(cc.send_batch(bid))
        again = asyncio.run(cc.send_batch(bid))
    assert 'أُرسلت 3' in result and len(sent) == 3 and 'سابقًا' in again
    with patch.object(cc, 'ensure_template', AsyncMock(return_value='PENDING')):
        assert 'لم تُرسل' in asyncio.run(cc.send_batch(bid + 99))
    assert cc.candidates(now) == []  # nobody twice within 60 days

    # Replies: interested with details → alert + quote code; stop → suppression.
    with db() as c:
        for n, (phone, msg) in enumerate((('966500000401', 'ممتاز عندنا 2 حاويات تجي جدة الأسبوع الجاي للرياض كم السعر'),
                                           ('966500000403', 'إيقاف'))):
            c.execute('''INSERT INTO whatsapp_agent_jobs(account_id,message_id,event_id,sender,conversation_id,payload,idempotency_key,created_at,updated_at)
                VALUES('acc',%s,%s,%s,%s,%s,%s,NOW()+INTERVAL '1 minute',NOW())''', ('r' + str(n), 're' + str(n), phone, 'c' + phone,
                                                                                  json.dumps({'question': msg}, ensure_ascii=False), 'rk' + str(n)))
    d = {'intent': 'price_request', 'containers': 2, 'route_key': 'من ميناء جدة الإسلامي إلى الرياض', 'summary': 'حاويتين للرياض'}
    from app import prospect_replies
    real = prospect_replies.classify
    with patch('app.transport_desk.manager_chat', return_value=('966500000001', 'conv-manager')), \
            patch.object(prospect_replies, 'classify', side_effect=lambda t: d if 'حاويات' in t else real(t)):
        out = cc.process_replies(now + dt.timedelta(minutes=5))
        assert cc.process_replies(now + dt.timedelta(minutes=6)) == []
    hot = next(x for x in out if 'شركة التخليص فقط' in x)
    assert 'يطلب سعر' in hot and '2 حاوية × 250 ريال = 500 ريال' in hot and '9,500 ريال' in hot and 'نفذ ' in hot
    assert any('أوقفت عنه' in x for x in out)
    with db() as c:
        assert c.execute("SELECT 1 FROM marketing_suppressions WHERE recipient='+966500000403'").fetchone()
    st = cc.status_text()
    assert 'عرض النقل لعملاء التخليص: أُرسلت 1 — ردود 1 — مهتمون 1' in st, st


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema = 'customer_care_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1'):
            raise AssertionError('External network blocked')
        return connect(sock, address)
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '', 'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32),
               'ADMIN_EMAIL': 'bootstrap@fixture.invalid', 'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0',
               'AFAQ_TEAM': '[]', 'WHATSAPP_COMMAND_OWNER': ''}
        with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', local_only):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: existing-customer cross-sell and win-back; approval-gated batch; external sends 0.')


if __name__ == '__main__':
    main()
