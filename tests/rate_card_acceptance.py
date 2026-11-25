"""Transport rate card on isolated PostgreSQL. MOCK level: WhatsApp sending is replaced; the real drivers,
driver_price_requests/quotes and approved_routes tables are used. Nothing is sent."""
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
    from app import driver_quotes, prospect_replies, rate_card
    from app.storage import db
    from app import data_import
    data_import._init(); driver_quotes.init(); rate_card.init()
    with db() as c:
        for i in range(40):
            city = 'الدمام' if i < 12 else 'جدة' if i < 30 else 'الرياض'
            c.execute('''INSERT INTO drivers(driver_name,whatsapp_phone,vehicle_type,current_city,preferred_routes,availability,offer_consent,created_at,updated_at)
                VALUES(%s,%s,%s,%s,'',%s,1,NOW(),NOW())''', (f'سائق {i}', f'9665{i:08d}', 'سطحة' if i % 5 else 'ستارة', city, 'متاح'))

    # 1) Survey plan: every lane gets drivers, no driver is asked about two lanes, origin city first.
    rows = rate_card.plan(per_lane=4)
    phones = [d['phone'] for _, ds in rows for d in ds]
    assert len(rows) == len(rate_card.LANES) and len(phones) == len(set(phones))
    dammam = rows[0][1]
    assert rows[0][0]['destination'] == 'الرياض' and all('الدمام' in d['current_city'] for d in dammam), dammam
    preview_rows, text = rate_card.survey_preview(per_lane=4)
    assert 'كل سائق يُسأل عن مسار واحد' in text and '8 مسار' in text

    # 2) «نفذ»: one TQ request per lane, recipients pending, sending in the background (mocked); external off → nothing.
    with patch.dict(os.environ, {'ENABLE_EXTERNAL_ACTIONS': '0'}):
        assert 'متوقف' in rate_card.start_survey({'per_lane': 4})
    sent = []
    async def fake_send(rid):
        sent.append(rid)
        with db() as c:
            c.execute("UPDATE driver_price_quotes SET status='sent',sent_at=NOW() WHERE request_id=%s", (rid,))
            c.execute("UPDATE driver_price_requests SET status='sent',sent_at=NOW() WHERE id=%s", (rid,))
    class Now:
        def __init__(self, target, daemon=True):
            self.target = target
        def start(self):
            self.target()
    with patch.dict(os.environ, {'ENABLE_EXTERNAL_ACTIONS': '1'}), patch.object(driver_quotes, 'send_all', fake_send), \
         patch.object(rate_card.threading, 'Thread', Now):
        out = rate_card.start_survey({'per_lane': 4})
    assert out.startswith('✅ بدأ مسح الأسعار: 8 مسار') and len(sent) == 8 and 'TQ-' in out
    with db() as c:
        reqs = c.execute('SELECT id, origin, destination FROM driver_price_requests ORDER BY id').fetchall()
        n = c.execute("SELECT COUNT(DISTINCT phone) n, COUNT(*) t FROM driver_price_quotes").fetchone()
    assert len(reqs) == 8 and n['n'] == n['t']

    # 3) Drivers reply with a bare number → it lands on their only lane; the card shows median + suggestion.
    first = reqs[0]
    with db() as c:
        targets = [r['phone'] for r in c.execute('SELECT phone FROM driver_price_quotes WHERE request_id=%s', (first['id'],)).fetchall()]
    for phone, price in zip(targets, ('2400', '2600', '٢٥٠٠')):
        reply, _ = driver_quotes.capture(phone, price)
        assert 'تم تسجيل سعرك' in reply and first['destination'] in reply
    text = rate_card.card()
    assert 'من ميناء جدة الإسلامي إلى الرياض: 4,500 ريال' in text
    line = [l for l in text.split('\n') if 'الدمام إلى الرياض' in l][0]
    assert '3 سعر' in line and 'الوسيط 2,500' in line and 'مقترح للعميل 2,900' in line, line
    assert 'من ميناء جدة الإسلامي إلى المدينة المنورة: ما وصلت أسعار بعد' in text

    # 4) Approval: only the manager's explicit price; the lane joins the approved table everywhere; base lanes untouched.
    assert 'خارج النطاق' in rate_card.approve('ميناء الملك عبدالعزيز بالدمام', 'الرياض', '20')
    assert 'القائمة الأساسية' in rate_card.approve('ميناء جدة الإسلامي', 'الرياض', '3000')
    ok = rate_card.approve('ميناء الملك عبدالعزيز بالدمام', 'الرياض', '2,900', 'المدير')
    assert ok.startswith('✅ اعتمدت من ميناء الملك عبدالعزيز بالدمام إلى الرياض: 2,900')
    again = rate_card.approve('ميناء الملك عبدالعزيز بالدمام', 'الرياض', '3000', 'المدير')
    assert '(كان 2,900)' in again
    _, routes = prospect_replies.price_table()
    assert routes['من ميناء الملك عبدالعزيز بالدمام إلى الرياض'] == 3000 and routes['من ميناء جدة الإسلامي إلى الرياض'] == 4500
    assert 'من ميناء الملك عبدالعزيز بالدمام إلى الرياض: 3,000 ريال' in rate_card.approved_text()
    from app import price_calculator
    assert price_calculator.compute('transport', 'من ميناء الملك عبدالعزيز بالدمام إلى الرياض', 2)[2] == 6000
    after = rate_card.card()
    assert '✅' in after and 'الدمام إلى الرياض: 3,000' in after and 'الدمام إلى الرياض: 3 سعر' not in after

    # 5) The GM tools: manager-only approval and survey, the code carries the survey.
    from app import command_agent, virtual_office
    for name in ('rate_card', 'rate_card_survey', 'approve_route_price'):
        assert name in command_agent.HANDLERS and name in virtual_office.DEPARTMENTS['transport']['tools']
    with patch.object(command_agent, '_member', lambda: {'name': 'موظف', 'manager': False}):
        assert 'للمدير فقط' in command_agent.tool_approve_route_price(None, {'origin': 'a', 'destination': 'b', 'price': '1000'})
        assert 'المدير فقط' in command_agent.tool_rate_card_survey(None, {})
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
        token = command_agent.CHAT.set(('966500000001', 'conv-m'))
        try:
            with patch.object(command_agent, '_member', lambda: {'name': 'المدير', 'manager': True}):
                msg = command_agent.tool_rate_card_survey(c, {'per_lane': 4})
        finally:
            command_agent.CHAT.reset(token)
        action = json.loads(c.execute('SELECT command FROM whatsapp_voice_pending').fetchone()['command'].partition(':')[2])
    assert 'نفذ ' in msg and action == {'tool': 'rate_card_survey', 'per_lane': 5}, (msg, action)


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'rate_card_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env):
            import app.main  # noqa: F401  full schema (drivers, users)
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: rate card — one-code survey (one lane per driver), market median + suggestion, manager-approved lanes join every price table.')


if __name__ == '__main__':
    main()
