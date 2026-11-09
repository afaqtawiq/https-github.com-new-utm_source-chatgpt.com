"""Driver market-price requests on local PostgreSQL. Sending is mocked (nothing leaves); replies are parsed into prices."""
import asyncio
import datetime as dt
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from app.bootstrap import app  # noqa: F401  (creates the base schema)
    from app import command_agent, driver_quotes as dq, zernio_whatsapp as z
    from app.storage import db, utcnow
    with db() as c:
        for i, (name, vt, city, avail, consent) in enumerate([('سعد', 'سطحة', 'جدة', 'متاح', 1), ('فهد', 'جوانب', 'الرياض', 'متاح', 1),
                                                              ('خالد', 'سطحة', 'الدمام', 'غير متاح', 1), ('ماجد', 'سطحة', 'جدة', 'متاح', 0),
                                                              ('علي', 'سطحة 40 قدم', 'جدة', 'متاح', 1)]):
            c.execute('INSERT INTO drivers(driver_name,whatsapp_phone,vehicle_type,current_city,availability,offer_consent,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,NOW(),NOW())',
                      (name, f'+96655000000{i}', vt, city, avail, consent))
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
    args = {'origin': 'ميناء جدة الإسلامي', 'destination': 'الرياض', 'cargo': 'حاوية 40 قدم على سطحة 22 طن', 'loading_date': 'الثلاثاء'}

    # 1) Preparing only produces a «نفذ» code — nothing is sent; unavailable / non-consenting drivers excluded; sutha drivers first.
    req, drivers, err = dq.prepare(args)
    assert not err and [d['driver_name'] for d in drivers][:2] == ['سعد', 'علي'] and len(drivers) == 3, drivers
    assert dq.prepare({'origin': 'جدة'})[2].startswith('ناقص')
    token = command_agent.CHAT.set(('966500000001', 'conv-manager'))
    with db() as c:
        out = command_agent.tool_driver_price_request(c, args)
        action = json.loads(c.execute('SELECT command FROM whatsapp_voice_pending').fetchone()['command'].partition(':')[2])
    command_agent.CHAT.reset(token)
    assert 'نفذ ' in out and 'بكم تحملها' in out and action['tool'] == 'driver_price_request' and action['limit'] == 3

    # 2) The template body matches the exact message (so Meta template params resolve) and the send is mocked.
    rid, count = dq.create(action, 'المدير')
    assert count == 3
    text = dq.body('TQ-' + str(rid), 'ميناء جدة الإسلامي → الرياض', action['cargo'], 'الثلاثاء')
    spec = {'components': [{'type': 'BODY', 'text': dq.template_spec()['components'][0]['text']}]}
    assert z.template_parameters(spec, text) == ['TQ-' + str(rid), 'ميناء جدة الإسلامي → الرياض', action['cargo'], 'الثلاثاء']
    sent = []

    async def fake_send(phone, message, **kw):
        sent.append((phone, message))
        return {}
    with patch.object(z, 'send', side_effect=fake_send), patch.dict(os.environ, {'LOAD_BROADCAST_DELAY': '0'}):
        asyncio.run(dq.send_all(rid))
    assert len(sent) == 3 and all('TQ-' + str(rid) in m for _, m in sent)

    # 3) Replies: plain number, «الفين وخمسمية» style with digits, thousand shorthand, decline, unrelated, non-recipient.
    r1 = dq.capture('966550000000', '2800')
    assert '2,800' in r1[0] and r1[1] and 'وصلنا 1 سعر' in r1[1], r1
    r2 = dq.capture('+966550000004', f'TQ-{rid} ٣٢٠٠ ريال')
    assert '3,200' in r2[0]
    assert dq.capture('966550000001', 'ما اقدر مشغول')[0].startswith('ولا يهمك')
    assert dq.capture('966550000000', 'السلام عليكم كيف الحال') is None
    assert dq.capture('966559999999', '2500') is None
    assert dq.price_in('3.5 الف') == 3500 and dq.price_in('رقمي 0551234567') is None and dq.price_in('2500 او 2700') is None
    assert 'ما وضح لي السعر' in dq.capture('966550000000', f'TQ-{rid} تمام')[0]

    # 4) Summary and the automatic summary after 3 hours (once).
    s = dq.summary(rid)
    assert 'رد بسعر 2' in s and 'اعتذر 1' in s and 'الأقل 2,800' in s and 'الوسيط 3,000' in s and 'الأعلى 3,200' in s, s
    assert dq.due_summaries() == []
    with db() as c:
        c.execute('UPDATE driver_price_requests SET sent_at=%s WHERE id=%s', (utcnow() - dt.timedelta(hours=4), rid))
    assert len(dq.due_summaries()) == 1 and dq.due_summaries() == []
    # Market reference appears once a route has ≥3 prices.
    with db() as c:
        c.execute("UPDATE driver_price_quotes SET status='quoted',price=3000 WHERE request_id=%s AND status='declined'", (rid,))
    assert 'مرجع السوق لنفس المسار' in dq.summary(rid)
    assert len(dq.market('جدة', 'الرياض')) == 3 and dq.market('الدمام', 'الرياض') == []
    # External switch off → nothing starts.
    with patch.dict(os.environ, {'ENABLE_EXTERNAL_ACTIONS': '0'}):
        assert 'متوقف' in dq.start(action)


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'driver_q_' + secrets.token_hex(5)
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
    print('PASS: drivers asked «بكم تحملها» only after «نفذ»; replies parsed into prices; summary + market reference.')


if __name__ == '__main__':
    main()
