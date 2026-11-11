"""Shipping-line document → container follow-up on local PostgreSQL. Image reading mocked; nothing sent."""
import asyncio
import datetime as dt
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from app.bootstrap import app  # noqa: F401
    from app import container_returns, load_vision, shipping_docs
    from app.storage import db
    container_returns.init()
    fields = {'document_kind': 'shipping_document', 'container_numbers': ['MSKU1234567', 'msku 7654321'],
              'shipping_line': 'MSC', 'vessel': 'MSC AURORA', 'bill_no': 'MEDU123456', 'consignee': 'مؤسسة النخبة',
              'eta': '2026-11-10', 'free_days': '7', 'free_until': None, 'return_place': 'ساحة جدة', 'daily_cost': '250'}
    reply = shipping_docs.register(fields, 'إشعار وصول TGHU1111111')
    assert 'سجلت 3 حاوية' in reply and '2026-11-16' in reply and 'تقديري' in reply and 'MEDU123456' in reply, reply
    with db() as c:
        rows = {r['container']: r for r in c.execute('SELECT * FROM container_returns').fetchall()}
    assert set(rows) == {'MSKU1234567', 'MSKU7654321', 'TGHU1111111'}
    r = rows['MSKU1234567']
    assert r['free_until'] == dt.date(2026, 11, 16) and r['bill'] == 'MEDU123456' and r['return_place'] == 'ساحة جدة' and float(r['daily_cost']) == 250
    # A written last free day wins over the estimate; registering again updates instead of duplicating.
    reply = shipping_docs.register(dict(fields, free_until='2026-11-20', container_numbers=['MSKU1234567']))
    assert '2026-11-20' in reply and 'تقديري' not in reply
    with db() as c:
        assert c.execute('SELECT COUNT(*) n FROM container_returns').fetchone()['n'] == 3
    assert shipping_docs.register({'container_numbers': []}) is None
    # The WhatsApp image path uses it for shipping documents.
    payload = {'message': {'text': 'إذن تسليم'}, 'conversation': {'id': 'c1'}}
    with patch.object(load_vision, 'fetch_image', AsyncMock(return_value=(b'x', 'image/jpeg'))), \
            patch.object(load_vision, 'extract', AsyncMock(return_value=dict(fields, container_numbers=['CMAU2222222']))), \
            patch('app.staff_intake.audit', side_effect=lambda c, p, s, reply, cmd: reply):
        with db() as c:
            out = asyncio.run(load_vision.handle_image(c, payload, '966500000001', 0))
    assert 'CMAU2222222' in out and 'مكتب الحاويات' in out, out
    # A bill of lading like the owner's (11 Nov 2026): leasing-prefix containers, carrier written in full, no dates.
    from app import line_desk
    bl = {'container_numbers': ['CAIU6195811', 'MEDU6178435', 'TGBU3513450'], 'bill_no': 'MEDUAIV05291',
          'shipping_line': 'Mediterranean Shipping Company S.A. (MSC)', 'vessel': 'MSC MOSS III - YM641A',
          'consignee': 'Imar Overseas Saudi Arabia Co. W.L.L', 'container_size': '40'}
    out = shipping_docs.register(bl)
    assert 'سجلت 3 حاوية جديدة' in out and 'الوكيل الملاحي: MSC' in out and 'sau-ex-cs.localwest@msc.com' in out, out
    assert 'أيام السماح MSC 14' in out and 'MEDUAIV05291' in out, out
    with db() as c:
        msc = c.execute("SELECT id FROM shipping_agents WHERE name='MSC'").fetchone()['id']
        got = c.execute("SELECT agent_id,size FROM container_returns WHERE container IN ('CAIU6195811','TGBU3513450')").fetchall()
    assert all(r['agent_id'] == msc and r['size'] == '40' for r in got), got
    # Same document again → no duplicate wording; with the agent's free days and an arrival date the day is estimated.
    assert 'مسجلة سابقًا' in shipping_docs.register(bl)
    line_desk.set_tariff({'agent': 'MSC', 'free_days': '14'})
    out = shipping_docs.register(dict(bl, eta='2026-11-12'))
    assert '2026-11-25' in out and 'تقديري' in out and 'أرضيات الميناء: 14/11' in out, out
    from app import command_agent
    with db() as c:
        done = command_agent.tool_track_container(c, {'bill': 'MEDUAIV05291', 'free_until': '2026-11-25'})
    assert 'حدّثت 3 حاوية' in done, done
    with db() as c:
        assert not c.execute("SELECT free_until_estimated e FROM container_returns WHERE container='TGBU3513450'").fetchone()['e']
        c.execute("UPDATE container_returns SET free_until_estimated=TRUE WHERE bill='MEDUAIV05291'")
        r = c.execute("SELECT free_until,free_until_estimated,arrived_on FROM container_returns WHERE container='CAIU6195811'").fetchone()
    assert r['free_until'] == dt.date(2026, 11, 25) and r['free_until_estimated'] and r['arrived_on'] == dt.date(2026, 11, 12)


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'shipping_docs_' + secrets.token_hex(5)
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
    print('PASS: shipping documents register containers for return follow-up; nothing sent.')


if __name__ == '__main__':
    main()
