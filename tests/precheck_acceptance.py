"""Pre-purchase check on local PostgreSQL with a small tariff table; no AI key (text fallback); nothing sent."""
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import precheck
    from app.storage import db
    with db() as c:
        c.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
        c.execute('''CREATE TABLE IF NOT EXISTS gcc_tariff(code TEXT PRIMARY KEY, desc_ar TEXT, desc_en TEXT, context_ar TEXT,
            duty TEXT, search TEXT)''')
        c.execute('''INSERT INTO gcc_tariff VALUES('940161000000','مقاعد بهياكل من خشب منجدة','upholstered seats with wooden frames',
            'أثاث','5%','مقاعد بهياكل من خشب منجدة كنب upholstered seats wooden frames sofa'),
            ('841510000000','أجهزة تكييف الهواء من النوع الجداري','air conditioning machines wall split','أجهزة','5%',
            'أجهزة تكييف الهواء مكيفات سبليت air conditioning split')''')
    client = TestClient(app, base_url='http://testserver')
    page = client.get('/check?src=price')
    assert page.status_code == 200 and 'فحص قبل الشراء' in page.text and 'value="price"' in page.text
    assert 'افحص أصناف عرض المورد' in client.get('/price').text
    sent = []
    with patch('app.owner_briefing.deliver', AsyncMock(side_effect=lambda t: sent.append(t))):
        r = client.post('/check/run', data={'items': 'كنب مقاعد خشب منجدة — 10000 USD\nمكيفات تكييف سبليت 2000 SAR\nشيء غير معروف',
                                              'company': 'مؤسسة النخبة', 'phone': '0551234567'})
        assert r.status_code == 200, r.text
        rep = r.json()['report']
        assert len(rep) == 3 and rep[0]['code'] == '94 01 61 00 00 00' and rep[0]['duty'] == '5%'
        est = rep[0]['estimate']  # 10000 USD → 37500 SAR; duty 5% = 1875; VAT 15% of 39375 = 5906.25
        assert est == {'value_sar': 37500.0, 'duty': 1875.0, 'vat': 5906.25}, est
        assert rep[1]['estimate']['duty'] == 100.0 and rep[2]['code'] == '' and rep[2]['estimate'] is None
        assert r.json()['whatsapp'].startswith('https://wa.me/966507665873?text=')
        assert len(sent) == 1 and 'مؤسسة النخبة' in sent[0] and '+966551234567' in sent[0]
        assert client.post('/check/run', data={'items': 'x'}).status_code == 400
        assert client.post('/check/run', data={'items': 'كنب', 'website': 'bot'}).status_code == 400
        assert client.post('/check/run', files={'file': ('a.pdf', b'not a pdf', 'application/pdf')}, data={'items': ''}).status_code == 400
        client.post('/check/run', data={'items': 'مكيفات'}); client.post('/check/run', data={'items': 'مكيفات'})
        assert client.post('/check/run', data={'items': 'مكيفات'}).status_code == 429
    assert precheck.duty_rate('معفاة') == 0.0 and precheck.duty_rate('12%') == 0.12 and precheck.duty_rate('ممنوع') is None


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'precheck_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema + ',public'}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: pre-purchase check (tariff candidates, estimates, lead alert); nothing sent.')


if __name__ == '__main__':
    main()
