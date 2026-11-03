"""Outreach replies → pipeline + approval-gated quotes, on local PostgreSQL. Synthetic records; no AI key (keyword
fallback); external network blocked; nothing is sent (quotes are only «نفذ» codes)."""
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from app.bootstrap import app  # noqa: F401  (creates the schema; startup workers are not started)
    from app import prospect_replies as pr
    from app.daily_prospects import decide, today
    from app.storage import db, utcnow
    pr.init()
    now = utcnow()
    with db() as c:
        uid = c.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('a@fixture.invalid','admin','x','admin',%s) RETURNING id",
                        (now,)).fetchone()['id']
        ids = {}
        for i, (name, phone) in enumerate((('مؤسسة المثال للاستيراد', '+966500000301'), ('شركة الرفض', '0500000302'),
                                           ('شركة الإيقاف', '+966500000303'), ('شركة لم ترد', '+966500000304'))):
            ids[name] = c.execute('''INSERT INTO daily_prospects(source_key,company_name,phone,email,city,activity,website,score,segment,
                reason,message,message_source,status,batch_date,created_at,updated_at)
                VALUES(%s,%s,%s,'','جدة','استيراد','',%s,'importer','x','رسالة تعريف تجريبية طويلة','template','pending',%s,%s,%s) RETURNING id''',
                                  ('fx:' + str(i), name, phone, 50 + i, today(), now, now)).fetchone()['id']
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ)''')
    for pid in ids.values():
        decide([pid], 'approve', uid)
        decide([pid], 'contacted', uid, note='autopilot: whatsapp')

    def inbound(n, sender, text):
        with db() as c:
            c.execute('''INSERT INTO whatsapp_agent_jobs(account_id,message_id,event_id,sender,conversation_id,payload,idempotency_key,created_at,updated_at)
                VALUES('acc',%s,%s,%s,%s,%s,%s,NOW(),NOW())''', ('m' + str(n), 'e' + str(n), sender, 'conv-' + sender,
                                                               json.dumps({'question': text}, ensure_ascii=False), 'k' + str(n)))

    inbound(1, '966500000301', 'السلام عليكم كم سعر تخليص 3 حاويات ونقلها من جدة للرياض')
    inbound(2, '966500000302', 'لا شكرا غير مهتم')
    inbound(3, '966500000303', 'إيقاف')
    inbound(4, '966599999999', 'رسالة من رقم ليس عميلًا محتملًا')
    data = {'intent': 'price_request', 'containers': 3, 'route_key': 'من ميناء جدة الإسلامي إلى الرياض', 'port': 'ميناء جدة الإسلامي',
            'destination': 'الرياض', 'cargo': 'مواد بناء', 'summary': 'يطلب سعر تخليص ونقل 3 حاويات'}
    real = pr.classify
    with patch('app.transport_desk.manager_chat', return_value=('966500000001', 'conv-manager')), \
            patch.object(pr, 'classify', side_effect=lambda t: data if '3 حاويات' in t else real(t)):
        out = pr.process()
        assert pr.process() == []  # every reply handled once
    assert len(out) == 3, out
    hot = next(x for x in out if 'مؤسسة المثال' in x)
    assert 'يطلب سعر' in hot and '3 حاوية × 250 ريال = 750 ريال' in hot and '3 × 4,500 ريال = 13,500 ريال' in hot
    assert '14,250 ريال' in hot and 'نفذ ' in hot and 'لا تشمل الأسعار' in hot
    assert any('شركة الرفض' in x and 'غير مهتم' in x for x in out)
    assert any('شركة الإيقاف' in x and 'أوقفت عنه' in x for x in out)
    with db() as c:
        st = {r['company_name']: r['status'] for r in c.execute('SELECT company_name,status FROM daily_prospects').fetchall()}
        assert st == {'مؤسسة المثال للاستيراد': 'interested', 'شركة الرفض': 'not_interested', 'شركة الإيقاف': 'not_interested',
                      'شركة لم ترد': 'contacted'}, st
        assert c.execute("SELECT 1 FROM marketing_suppressions WHERE channel='whatsapp' AND recipient='+966500000303'").fetchone()
        pend = c.execute('SELECT command FROM whatsapp_voice_pending').fetchall()
        assert len(pend) == 1
        action = json.loads(pend[0]['command'].partition(':')[2])
        assert action['tool'] == 'send_whatsapp' and action['to'] == '+966500000301' and 'ATQ-' in action['text']
        assert c.execute('SELECT COUNT(*) n FROM prospect_replies').fetchone()['n'] == 3

    # A second message from the same interested company within 24h: recorded, no duplicate alert or quote.
    inbound(5, '966500000301', 'تمام نبي نبدأ')
    with patch('app.transport_desk.manager_chat', return_value=('966500000001', 'conv-manager')):
        assert pr.process() == []
    text = pr.status_text()
    assert 'ردّ 3 شركة' in text and 'مؤسسة المثال للاستيراد' in text and 'ATQ-' in text, text


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema = 'prospect_replies_' + secrets.token_hex(5)
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
               'ADMIN_EMAIL': 'bootstrap@fixture.invalid', 'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', local_only):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: prospect replies → pipeline and approval-gated quotes; external sends 0.')


if __name__ == '__main__':
    main()
