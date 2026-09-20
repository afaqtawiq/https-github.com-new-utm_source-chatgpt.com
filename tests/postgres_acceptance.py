"""Real PostgreSQL + complete app acceptance in a disposable, empty CI database."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import secrets
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
database_url = os.environ['AFAAQ_TEST_DATABASE_URL']
# Refuse to run the database-writing fixture against a production endpoint.
from urllib.parse import urlsplit
target = urlsplit(database_url)
assert target.hostname in {'localhost', '127.0.0.1'} and target.path == '/afaaq_test'
password = secrets.token_urlsafe(24)
os.environ.update(DATABASE_URL=database_url, DISCOVERY_AUTO_ENABLED='0',
                  ENABLE_EXTERNAL_ACTIONS='0', ADMIN_EMAIL='acceptance@example.invalid',
                  ADMIN_PASSWORD=password, NAQLIAT_CONNECTOR_TOKEN='local-ci-connector',
                  BROWSER_COOKIE_SECURE='0')
from fastapi.testclient import TestClient
from app.bootstrap import app
from app.storage import one, execute, get_session
from app.freight_workflow import prepare_driver_offer, accept_driver_reply
from app.command_assistant import deliver_driver_broadcast

client = TestClient(app, base_url='http://testserver', headers={'accept': 'text/html', 'origin': 'http://testserver'})
assert client.get('/naqliat', follow_redirects=False).status_code == 303
assert client.get('/api/v7/naqliat/loads', follow_redirects=False).status_code == 401
response = client.post('/login', data={'email': 'acceptance@example.invalid', 'password': password, 'next': '/naqliat'}, follow_redirects=False)
assert response.status_code == 303 and response.headers['location'] == '/naqliat'
csrf = get_session(client.cookies.get('gla_session'))['csrf']
for path in ('/dashboard', '/naqliat', '/commands', '/readiness', '/api/v7/readiness', '/shipping-agents/identify'):
    assert client.get(path).status_code == 200, path

response = client.post('/commands', data={'csrf': csrf, 'command': 'أضف السائق سائق الاختبار ورقم جواله 0500000002'}, follow_redirects=False)
assert response.status_code == 303, response.text
driver = one("SELECT * FROM drivers WHERE whatsapp_phone=?", ('+966500000002',))
assert driver and driver['driver_name'] == 'سائق الاختبار' and driver['offer_consent'] == 0
duplicate = client.post('/commands', data={'csrf': csrf, 'command': 'أضف السائق سائق الاختبار ورقم جواله 0500000002'}, follow_redirects=False)
assert duplicate.status_code == 409
execute('UPDATE drivers SET offer_consent=1 WHERE id=?', (driver['id'],))

raw = 'مدينة التحميل\nالرياض\nمدينة التنزيل\nجدة\nالوزن: ٢٠ طن\nالجوال: ٠٥٠٠٠٠٠٠٠١'
# Connector calls do not carry browser cookies.
connector = TestClient(app, base_url='http://testserver')
response = connector.post('/api/v7/naqliat/ocr', json={'raw_text': raw}, headers={'Authorization': 'Bearer local-ci-connector'})
assert response.status_code == 200, response.text
load = response.json()
assert load['origin'] == 'الرياض' and load['destination'] == 'جدة' and load['owner_phone'] == '+966500000001'
shipment = one('SELECT * FROM shipments WHERE reference=?', ('NQ-' + str(load['id']),))
sid = shipment['id']
assert one('SELECT status FROM freight_negotiations WHERE shipment_id=?', (sid,))['status'] == 'contact_ready'
repeat = connector.post('/api/v7/naqliat/ocr', json={'raw_text': raw}, headers={'Authorization': 'Bearer local-ci-connector'})
assert repeat.status_code == 200 and not repeat.json()['created']
response = client.post(f'/freight-workflow/{sid}/agreement', data={
    'csrf': csrf, 'agreed_owner_price': '2000', 'weight_tons': '20', 'payment_method': 'عند التسليم',
    'unloading_location': 'جدة'}, follow_redirects=False)
assert response.status_code == 303, response.text
with ThreadPoolExecutor(max_workers=4) as executor:
    bids = list(executor.map(lambda _: prepare_driver_offer(sid, driver['id']), range(4)))
assert len(set(bids)) == 1
bid = bids[0]
offer = one('SELECT * FROM driver_broadcasts WHERE id=?', (bid,))
assert '1,850.00' in offer['message'] and offer['status'] == 'draft'
assert one('SELECT COUNT(*) n FROM driver_broadcasts WHERE shipment_id=?', (sid,))['n'] == 1
assert client.get(f'/commands/broadcast/{bid}').status_code == 200
assert client.get(f'/freight-workflow/{sid}').status_code == 200
assert client.post(f'/commands/broadcast/{bid}/send', data={'csrf': csrf, 'confirmed': 'yes'}, follow_redirects=False).status_code == 428

# Provider stub exercises database transitions, not an actual message delivery.
calls = []
async def provider(*args):
    calls.append(args)
    return {'messages': [{'id': 'ci-provider-id'}]}
execute("UPDATE driver_broadcasts SET status='sending' WHERE id=?", (bid,))
with patch('app.command_assistant.send_text_message', provider):
    asyncio.run(deliver_driver_broadcast(bid))
    asyncio.run(deliver_driver_broadcast(bid))
assert len(calls) == 1
assert not accept_driver_reply('+966500000002', 'غير موافق ' + shipment['reference'])
assert accept_driver_reply('+966500000002', 'موافق ' + shipment['reference'])
assert not accept_driver_reply('+966500000002', 'موافق ' + shipment['reference'])
assert one('SELECT status FROM shipments WHERE id=?', (sid,))['status'] == 'driver_assigned'
print('PASS: PostgreSQL startup, protected pages, Arabic command persistence, OCR intake, duplicate intake, agreement, concurrent offer creation, guarded sends, driver assignment. External sends: 0.')
