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
from app.freight_workflow import prepare_driver_offer, accept_driver_reply, sync_retell_negotiation
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
# A shared contact (even on the same route) is not a duplicate shipment.
second_raw = raw + '\nوصف الحمولة: طلب مستقل رقم 2'
second_response = connector.post('/api/v7/naqliat/ocr', json={'raw_text': second_raw}, headers={'Authorization': 'Bearer local-ci-connector'})
assert second_response.status_code == 200 and second_response.json()['created']
second_sid = one('SELECT id FROM shipments WHERE reference=?', ('NQ-' + str(second_response.json()['id']),))['id']
assert second_sid != sid
classification_path = f'/freight-workflow/{second_sid}/classification'
assert client.post(classification_path, data={'record_kind':'carrier_offer'}, follow_redirects=False).status_code == 403
assert client.post(classification_path, data={'csrf':csrf,'record_kind':'carrier_offer'}, follow_redirects=False).status_code == 303
record = one('SELECT * FROM freight_negotiations WHERE shipment_id=?', (second_sid,))
assert record['record_kind'] == 'carrier_offer' and record['owner_phone'] == load['owner_phone']
assert one('SELECT record_kind FROM freight_negotiations WHERE shipment_id=?', (sid,))['record_kind'] == 'shipment_request'
detail = client.get(f'/freight-workflow/{second_sid}').text
assert 'عرض ناقل يبحث عن حمولة' in detail and 'اعتماد التواصل مع صاحب الشحنة' not in detail
from app.freight_workflow import contact_owner
asyncio.run(contact_owner(second_sid, approved=True))
assert one('SELECT status FROM freight_negotiations WHERE shipment_id=?', (second_sid,))['status'] == 'carrier_offer'
assert not sync_retell_negotiation({'shipment_id':second_sid,'freight_negotiation':True}, {'agreed_owner_price':2000})
assert client.post(f'/freight-workflow/{second_sid}/agreement', data={'csrf':csrf,'agreed_owner_price':2000}, follow_redirects=False).status_code == 409
assert client.post(classification_path, data={'csrf':csrf,'record_kind':'shipment_request'}, follow_redirects=False).status_code == 303
assert one('SELECT status FROM freight_negotiations WHERE shipment_id=?', (second_sid,))['status'] == 'ready_to_contact'
print('PASS: carrier classification is reversible, blocks shipper workflow and preserves separate shipments sharing a phone.')
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
assert client.post(f'/freight-workflow/{sid}/agreement', data={
    'csrf': csrf, 'agreed_owner_price': '3000', 'weight_tons': '20', 'payment_method': 'عند التسليم',
    'unloading_location': 'جدة'}, follow_redirects=False).status_code == 409
assert sync_retell_negotiation({'shipment_id': sid, 'freight_negotiation': True}, {'agreed_owner_price': 3000})
assert one('SELECT revenue,cost FROM shipments WHERE id=?', (sid,)) == {'revenue': 2000, 'cost': 1850}
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
from app.transport_intake import transport_reply
from app.storage import db
with db() as connection:
    result = transport_reply(connection, {}, 'طلب نقل\nمن جدة إلى الشارقة\nجوال صاحب الشحنة: 0500000001\nالوزن: 20 طن',
                             'ci-transport-event', 'ci-employee', {'sender': {'phoneNumber': '+966500000009'}})
    reference = result[0]['_last_transport_reference']
    duplicate = transport_reply(connection, {}, 'طلب نقل\nمن جدة إلى الشارقة\nجوال صاحب الشحنة: 0500000001\nالوزن: 20 طن',
                                'ci-transport-event', 'ci-employee', {})
    assert duplicate[0]['_last_transport_reference'] == reference
wa = one('SELECT id FROM shipments WHERE reference=?', (reference,))
assert one('SELECT COUNT(*) n FROM shipments WHERE reference=?', (reference,))['n'] == 1
execute("UPDATE freight_negotiations SET agreed_owner_price=2000,payment_method='عند التسليم' WHERE shipment_id=?", (wa['id'],))
wa_bid = prepare_driver_offer(wa['id'], driver['id'])
assert '1,850.00' in one('SELECT message FROM driver_broadcasts WHERE id=?', (wa_bid,))['message']
execute("UPDATE driver_broadcasts SET status='sending' WHERE id=?", (wa_bid,))
with patch('app.command_assistant.send_text_message', provider):
    asyncio.run(deliver_driver_broadcast(wa_bid))
# Signed Zernio inbound uses the same transaction as event deduplication.
import hashlib
import hmac
import json
import httpx
class ReplyClient:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def post(self, *args, **kwargs):
        return httpx.Response(200, json={'success': True})
def inbound(event, sender, text, account='ci-wa-account'):
    body = json.dumps({'id':event, 'event':'message.received',
        'account':{'accountId':account,'platform':'whatsapp'},
        'conversation':{'id':'ci-c-' + sender,'participantId':sender},
        'message':{'direction':'incoming','text':text,'sender':{'phoneNumber':sender,'id':sender}}}).encode()
    signature = hmac.new(b'ci-secret', body, hashlib.sha256).hexdigest()
    return connector.post('/webhooks/zernio', content=body, headers={'x-zernio-signature':signature})
with patch.dict(os.environ, {'ZERNIO_API_KEY':'ci-not-real','ZERNIO_WEBHOOK_SECRET':'ci-secret',
                             'WHATSAPP_COMMAND_ACCOUNT_ID':'ci-wa-account'}):
    with patch('app.zernio_receiver.httpx.AsyncClient', lambda **kwargs: ReplyClient()):
        reply = inbound('ci-driver-accept', '966500000002', 'موافق ' + reference)
        assert reply.status_code == 200 and reply.json()['agent'] == 'afaaq', reply.text
        assert inbound('ci-driver-accept', '966500000002', 'موافق ' + reference).json()['duplicate']
        assert one('SELECT status FROM shipments WHERE id=?',(wa['id'],))['status'] == 'driver_assigned'
        execute("UPDATE freight_negotiations SET status='awaiting_owner',contact_channel='whatsapp' WHERE shipment_id=?", (second_sid,))
        reply = inbound('ci-owner-reply', '966500000001', 'السعر 2000 ريال')
        assert reply.json()['agent'] == 'afaaq', reply.text
        assert inbound('ci-owner-reply', '966500000001', 'السعر 2000 ريال').json()['duplicate']
        assert one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='owner_whatsapp_reply'", (second_sid,))['n'] == 1
        assert one('SELECT agreed_owner_price FROM freight_negotiations WHERE shipment_id=?',(second_sid,))['agreed_owner_price'] is None
print('PASS: PostgreSQL startup, transport intake, duplicate intake, agreement, concurrent offer creation, 150 SAR margin and driver assignment for NQ and WA references. External sends: 0.')

from social_postgres_acceptance import run as run_social_acceptance
run_social_acceptance(client, app)

from media_settings_acceptance import run as run_media_settings_acceptance
run_media_settings_acceptance(client, app)

from media_studio_acceptance import run as run_media_studio_acceptance
run_media_studio_acceptance(client, app)

from advert_acceptance import run as run_advert_acceptance
run_advert_acceptance(client, app)

from production_monitor_acceptance import run as run_production_monitor_acceptance
run_production_monitor_acceptance(client, app)
from spacemail_acceptance import run as run_spacemail_acceptance
run_spacemail_acceptance(client, app)
from agent_operations_acceptance import run as run_agent_operations_acceptance
run_agent_operations_acceptance(client, app)
from official_replies_acceptance import run as run_official_replies_acceptance
run_official_replies_acceptance(client, app)
from publication_reports_acceptance import run as run_publication_reports_acceptance
run_publication_reports_acceptance(client, app)
