"""Naqliat connector v0.4: the visible load list text → loads saved once (re-reading a page adds nothing), one summary to
the owner (best price per km first), and «اعرض NQ-…» prepares the one-approval offer with the 2.5% commission.
Claude and WhatsApp are replaced; isolated PostgreSQL."""
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PAGE = [{'origin': 'جدة', 'destination': 'الرياض', 'distance_km': 908, 'weight_tons': 27, 'vehicle_type': 'سطحة تريلا',
         'price_sar': 5300, 'age_text': 'قبل 16 ساعة', 'description': 'ساحة الفردوس إلى رياض البضائع'},
        {'origin': 'الدمام', 'destination': 'الرياض', 'distance_km': 410, 'weight_tons': 25, 'vehicle_type': 'ستارة',
         'price_sar': 2600, 'age_text': 'قبل ساعة', 'description': ''},
        {'origin': 'جدة', 'destination': '', 'price_sar': 900}]


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import command_agent as ca, naqliat_connector as nc
    from app.storage import db
    from app.team import ROLE
    sent = []

    async def split(text):
        return PAGE

    async def deliver(text):
        sent.append(text)
    client = TestClient(app)
    auth = {'Authorization': 'Bearer connector-token-fixture'}
    text = 'جدة\nالرياض\n27 طن\n٥،٣٠٠ ر.س\nالدمام\nالرياض\n25 طن\n2,600 ر.س'
    assert client.post('/api/v7/naqliat/list', json={'text': text}, headers={'Authorization': 'Bearer wrong'}).status_code == 401
    with patch.object(nc, '_split_list', side_effect=split), patch('app.owner_briefing.deliver', side_effect=deliver):
        r = client.post('/api/v7/naqliat/list', json={'text': text, 'page': 0}, headers=auth).json()
        assert r['ok'] and r['read'] == 3 and r['new'] == 2, r
        again = client.post('/api/v7/naqliat/list', json={'text': text, 'page': 1}, headers=auth).json()
        assert again['new'] == 0, again
    assert len(sent) == 1, sent
    digest = sent[0]
    assert digest.index('الدمام') < digest.index('جدة'), 'best price per km first'
    assert '5,300 ر.س' in digest and '908 كم' in digest and 'اعرض NQ' in digest and '2.5%' in digest, digest
    with db() as c:
        row = c.execute("SELECT * FROM naqliat_loads WHERE origin='جدة' AND capture_method='android_list'").fetchone()
    assert row and 'السعر: 5300' in row['description']
    with db() as c:
        c.execute("""INSERT INTO drivers(driver_name,whatsapp_phone,vehicle_type,offer_consent,created_at,updated_at)
            VALUES('سائق','+966500000078','سطحة',1,NOW(),NOW()) ON CONFLICT DO NOTHING""")
    r_, t_ = ROLE.set({'name': 'محمد', 'manager': True}), ca.CHAT.set(('966500000001', 'private-1'))
    try:
        from app import whatsapp_admin
        with db() as c:
            whatsapp_admin.ensure_admin(c)
            out = ca.tool_load_offer(c, {'load_ref': f"NQ-{row['id']}"})
    finally:
        ROLE.reset(r_)
        ca.CHAT.reset(t_)
    assert '5,300' in out and '5,160' in out and 'جدة → الرياض' in out and 'العرض للسائقين فقط' in out and 'نفذ' in out, out


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'naq_list_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0', 'WHATSAPP_COMMAND_OWNER': '',
               'NAQLIAT_CONNECTOR_TOKEN': 'connector-token-fixture'}
        with patch.dict(os.environ, env):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: naqliat list — visible list text → new loads saved once, one owner summary best price/km first, «اعرض NQ» → one-approval offer at 2.5%.')


if __name__ == '__main__':
    main()
