"""Phone connector screenshot: a readable route is registered even below the WhatsApp confidence threshold;
a rate table or an image without a route is refused with what was read. Isolated PostgreSQL; nothing sent."""
import base64
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import load_vision, transport_desk
    from app.storage import db
    client = TestClient(app)
    body = {'image_base64': base64.b64encode(b'x' * 400).decode(), 'mime': 'image/jpeg'}
    auth = {'Authorization': 'Bearer ' + os.environ['NAQLIAT_CONNECTOR_TOKEN']}
    assert client.post('/api/v7/naqliat/screenshot', json=body).status_code == 401
    load = {'document_kind': 'load_listing', 'is_single_load': True, 'confidence': 0.7, 'origin': 'ميناء جدة الإسلامي',
            'destination': 'الرياض', 'weight_tons': 25, 'vehicle_type': 'تريلا', 'owner_phone': '+966538372324', 'summary': 'حمولة'}
    with patch.object(load_vision, 'extract', return_value=load), patch.object(transport_desk, 'notify_capture', return_value=None):
        r = client.post('/api/v7/naqliat/screenshot', json=body, headers=auth).json()
    assert r['ok'] and 'الرياض' in r['message'], r
    with db() as c:
        row = c.execute('SELECT origin,destination,owner_phone FROM naqliat_loads WHERE id=%s', (r['id'],)).fetchone()
    assert 'جدة' in row['origin'] and row['destination'] == 'الرياض' and row['owner_phone'].endswith('538372324')
    for fields in ({'document_kind': 'rate_table', 'origin': 'جدة', 'destination': 'الرياض', 'summary': 'جدول أسعار'},
                   {'document_kind': 'other', 'origin': None, 'destination': None, 'summary': 'شاشة الإعدادات'}):
        with patch.object(load_vision, 'extract', return_value=fields):
            r = client.post('/api/v7/naqliat/screenshot', json=body, headers=auth).json()
        assert not r['ok'] and 'ما قرأته' in r['message'], r


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'naq_shot_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0',
               'NAQLIAT_CONNECTOR_TOKEN': secrets.token_urlsafe(24)}
        with patch.dict(os.environ, env):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: connector screenshot — readable route registered, rate table / no route refused with what was read.')


if __name__ == '__main__':
    main()
