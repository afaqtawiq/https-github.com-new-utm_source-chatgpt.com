"""Signed transport webhook regressions against disposable, real PostgreSQL.

Run with AFAAQ_TEST_DATABASE_URL=postgresql://...@localhost/afaaq_test
python tests/transport_postgres_acceptance.py. The fixture uses a private schema,
real app/storage/row locks, and fake provider receipts. No live sends are allowed.
"""

import asyncio
import builtins
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
from threading import Barrier, Lock
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ACCOUNT = 'transport-ci-whatsapp'
SECRET = 'transport-ci-webhook-secret'
EMPLOYEE = '+966500000009'
DRIVER_PHONES = ('+966500000002', '+966500000003')


def database_target():
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    target = urlsplit(url)
    # Do not rely on assert for the destructive-fixture safety boundary. Query
    # parameters could override the hostname/database supplied in the URL.
    if (target.scheme not in {'postgres', 'postgresql'}
            or target.hostname not in {'localhost', '127.0.0.1'}
            or target.path != '/afaaq_test' or target.query or target.fragment):
        raise RuntimeError('AFAAQ_TEST_DATABASE_URL must name local disposable afaaq_test without URL parameters')
    return url


class Providers:
    """Thread-safe fakes; every unrecognized HTTP request is a test failure."""

    def __init__(self):
        self.lock = Lock()
        self.owner_calls = []
        self.driver_calls = []
        self.replies = {}
        self.unexpected = []
        self.driver_modes = {}
        self.owner_modes = {}

    async def owner(self, recipient, message):
        from app.zernio_whatsapp import WhatsAppBlocked
        with self.lock:
            self.owner_calls.append((recipient, message))
            receipt = 'fake-owner-' + str(len(self.owner_calls))
        mode = self.owner_modes.get(recipient)
        if mode == 'blocked':
            raise WhatsAppBlocked('CI owner preflight blocked; no provider send')
        if mode == 'no_receipt':
            return {'messages': []}
        return {'provider': 'ci-fake', 'messages': [{'id': receipt}]}

    async def driver(self, recipient, message):
        from app.zernio_whatsapp import WhatsAppBlocked
        match = re.search(r'(?:WA-[A-F0-9]{12}|NQ-\d+)', message)
        if not match:
            raise AssertionError('Unexpected non-transport driver send: ' + message)
        reference = match.group(0)
        with self.lock:
            self.driver_calls.append((recipient, message, reference))
            receipt = 'fake-driver-' + str(len(self.driver_calls))
        mode = self.driver_modes.get(reference)
        if mode == 'preflight_diagnostic':
            from app.zernio_whatsapp import WhatsAppPreflightBlocked
            raise WhatsAppPreflightBlocked({'phase':'preflight','endpoint':'accounts','http_status':429,
                'error_category':'rate_limited','attempts':3,'retryable':True,'rate_remaining':0}, retryable=True)
        if mode == 'post_timeout':
            from app.zernio_whatsapp import _dispatch_guard
            _dispatch_guard.get()()
            raise TimeoutError('CI outcome unknown after dispatch boundary')
        if mode == 'blocked' or (mode == 'partial' and recipient == DRIVER_PHONES[1]):
            raise WhatsAppBlocked('CI driver preflight blocked; no provider send')
        if mode == 'no_receipt':
            return {'messages': []}
        return {'provider': 'ci-fake', 'messages': [{'id': receipt}]}

    async def http_request(self, client, method, url, **kwargs):
        import httpx
        address = str(url)
        payload = kwargs.get('json') or {}
        headers = kwargs.get('headers') or {}
        if (method.upper() != 'POST'
                or not re.fullmatch(r'https://zernio\.com/api/v1/inbox/conversations/[^/]+/messages', address)
                or not headers.get('Idempotency-Key', '').startswith('shawahid-')
                or headers.get('Authorization') != 'Bearer transport-ci-not-a-real-key'):
            with self.lock:
                self.unexpected.append((method, address))
            raise AssertionError('Unmocked outbound HTTP request: ' + method + ' ' + address)
        event_id = headers['Idempotency-Key'][len('shawahid-'):]
        with self.lock:
            assert event_id not in self.replies, 'A duplicate webhook sent another reply'
            self.replies[event_id] = payload
        return httpx.Response(200, json={'success': True}, request=httpx.Request(method, address))

    def sent_to_drivers(self, reference):
        with self.lock:
            return [row for row in self.driver_calls if row[2] == reference]


def run(providers):
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import freight_workflow as workflow
    from app.storage import db, one, execute, rows

    # Do not enter TestClient as a context manager: app startup workers are not
    # part of this webhook test and must not run scheduled work in the fixture.
    client = TestClient(app, base_url='http://testserver')

    def inbound(event, sender, text, *, account=ACCOUNT, conversation=None,
                participant=None, sender_id=None, conversation_group=False,
                message_group=False, direction='incoming', signature=True, metadata=None):
        sender = sender.lstrip('+')
        payload = {
            'id': event, 'event': 'message.received',
            'account': {'accountId': account, 'platform': 'whatsapp'},
            'conversation': {
                'id': conversation or 'ci-transport-' + sender,
                'participantId': participant if participant is not None else sender,
                'isGroup': conversation_group,
            },
            'message': {
                'direction': direction, 'text': text, 'isGroup': message_group,
                'sender': {'phoneNumber': sender, 'id': sender_id if sender_id is not None else sender},
            },
        }
        if metadata is not None:
            payload['metadata'] = metadata
        body = json.dumps(payload, ensure_ascii=False).encode()
        digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        response = client.post('/webhooks/zernio', content=body, headers={
            'x-zernio-signature': digest if signature else 'invalid',
            'content-type': 'application/json',
        })
        assert response.status_code == (200 if signature else 401), response.text
        return response.json()

    def create_request(tag, owner, *, weight=20, conversation=None):
        event = 'transport-create-' + tag
        conversation = conversation or 'ci-employee-' + tag
        text = 'طلب نقل\nمن الرياض إلى جدة\nجوال صاحب الشحنة: ' + owner
        if weight is not None:
            text += '\nالوزن: ' + str(weight) + ' طن'
        response = inbound(event, EMPLOYEE, text, conversation=conversation)
        assert response['agent'] == 'afaaq' and response['state'] == 'sent', response
        reference = 'WA-' + hashlib.sha256((conversation + ':' + event).encode()).hexdigest()[:12].upper()
        item = one('SELECT * FROM shipments WHERE reference=?', (reference,))
        assert item, 'Signed transport intake did not create its shipment'
        assert item['origin'] == 'الرياض' and item['destination'] == 'جدة'
        assert one('SELECT COUNT(*) n FROM shipments WHERE reference=?', (reference,))['n'] == 1
        assert one('SELECT stage FROM shipment_operations WHERE shipment_id=?', (item['id'],))['stage'] == 'new'
        return item, (event, EMPLOYEE, text, conversation)

    def negotiation(item):
        return one('SELECT * FROM freight_negotiations WHERE shipment_id=?', (item['id'],))

    def broadcasts(item):
        return rows('SELECT * FROM driver_broadcasts WHERE shipment_id=? ORDER BY id', (item['id'],))

    def admin_status(item):
        from app.whatsapp_admin import shipment_status
        with db() as connection:
            connection.execute('SET TRANSACTION READ ONLY')
            return shipment_status(connection, item['reference'])

    def assert_unagreed(item):
        state = negotiation(item)
        assert state['status'] == 'awaiting_owner', state
        assert state['agreed_owner_price'] is None and state['driver_offer_price'] is None, state
        assert not broadcasts(item)
        assert one('SELECT revenue,cost FROM shipments WHERE id=?', (item['id'],)) == {'revenue': 0, 'cost': 0}
        return state

    def assert_offer(item, price):
        offers = broadcasts(item)
        assert len(offers) == 1, offers
        offer = offers[0]
        assert offer['status'] == 'awaiting_driver', offer
        assert offer['recipient_count'] == offer['sent_count'] == len(DRIVER_PHONES)
        assert offer['failed_count'] == 0
        assert f'{price - 150:,.2f}' in offer['message'], offer['message']
        state = negotiation(item)
        assert state['agreed_owner_price'] == price and state['driver_offer_price'] == price - 150, state
        assert one('SELECT revenue,cost FROM shipments WHERE id=?', (item['id'],)) == {
            'revenue': price, 'cost': price - 150,
        }
        recipients = rows('SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=?', (offer['id'],))
        assert len(recipients) == len(DRIVER_PHONES)
        assert all(row['status'] == 'sent' and row['provider_message_id'] for row in recipients)
        calls = providers.sent_to_drivers(item['reference'])
        assert len(calls) == len(DRIVER_PHONES), calls
        assert {row[0] for row in calls} == set(DRIVER_PHONES)
        return offer

    def terms(price, reference='', weight=20):
        return (reference + '\nالسعر النهائي: ' + str(price) + ' ريال'
                + '\nالوزن: ' + str(weight) + ' طن'
                + '\nالتنزيل: مستودع جدة\nطريقة الدفع: عند التسليم')

    def advance(owner, text, item):
        return asyncio.run(workflow.advance_owner_whatsapp_reply(owner, text, shipment_id=item['id']))

    with ExitStack() as stack:
        stack.enter_context(patch('app.freight_workflow.send_text_message', providers.owner))
        stack.enter_context(patch('app.command_assistant.send_text_message', providers.driver))
        # Catch accidental calls through the original adapter as well as direct
        # provider HTTP. Only the two explicitly mocked workflow senders may run.
        async def forbidden_adapter(*args, **kwargs):
            providers.unexpected.append(('adapter', 'whatsapp'))
            raise AssertionError('Transport escaped its mocked sending boundary')
        stack.enter_context(patch('app.whatsapp_integration.send_text_message', forbidden_adapter))

        with db() as connection:
            for number, phone in enumerate(DRIVER_PHONES, start=1):
                connection.execute('''INSERT INTO drivers(driver_name,whatsapp_phone,vehicle_type,offer_consent,created_at,updated_at)
                    VALUES(%s,%s,'truck',1,NOW(),NOW())''', ('CI driver ' + str(number), phone))
        driver_ids = {row['whatsapp_phone']: row['id'] for row in rows('SELECT id,whatsapp_phone FROM drivers')}

        before = one('SELECT COUNT(*) n FROM shipments')['n']
        inbound('invalid-signature', EMPLOYEE, 'طلب نقل\nمن الرياض إلى جدة\nجوال صاحب الشحنة: 0500000101', signature=False)
        assert one('SELECT COUNT(*) n FROM shipments')['n'] == before
        assert not providers.owner_calls and not providers.replies

        # Full signed-webhook chain: registration, verified owner contact, split
        # replies, one offer per registered driver, and first acceptance wins.
        owner = '+966500000101'
        item, replay = create_request('happy', owner, weight=None)
        state = assert_unagreed(item)
        assert state['contact_channel'] == 'whatsapp' and state['provider_message_id'].startswith('fake-owner-')
        report = admin_status(item)
        assert '(awaiting_owner)' in report and 'قبل مزود واتساب' in report, report
        assert 'تسليم الرسالة وقراءتها غير مؤكدين' in report and 'الحالة: new' not in report, report
        assert len(providers.owner_calls) == 1 and providers.owner_calls[0][0] == owner
        event, sender, text, conversation = replay
        assert inbound(event, sender, text, conversation=conversation)['duplicate']
        assert len(providers.owner_calls) == 1
        assert one('SELECT COUNT(*) n FROM shipments')['n'] == before + 1

        reply = inbound('happy-price', owner, 'السعر النهائي: ٢٠٠٠ ريال')
        assert reply['agent'] == 'afaaq'
        state = assert_unagreed(item)
        assert state['asking_price'] == 2000 and state['weight_tons'] is None
        assert 'الوزن' in providers.replies['happy-price']['message']
        assert inbound('happy-price', owner, 'السعر النهائي: ٢٠٠٠ ريال')['duplicate']
        assert one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='owner_whatsapp_reply'", (item['id'],))['n'] == 1
        inbound('happy-details', owner, 'الوزن: ٢٠ طن\nالتنزيل: مستودع جدة\nطريقة الدفع: عند التسليم')
        offer = assert_offer(item, 2000)
        assert '(awaiting_driver)' in admin_status(item)
        assert inbound('happy-details', owner, 'الوزن: ٢٠ طن\nالتنزيل: مستودع جدة\nطريقة الدفع: عند التسليم')['duplicate']
        assert len(providers.sent_to_drivers(item['reference'])) == len(DRIVER_PHONES)
        assert not workflow.accept_driver_reply(DRIVER_PHONES[0], 'غير موافق ' + item['reference'])
        assert not workflow.accept_driver_reply('+966500000099', 'موافق ' + item['reference'])
        inbound('happy-driver-first', DRIVER_PHONES[0], 'موافق ' + item['reference'])
        assigned = one('SELECT * FROM driver_broadcasts WHERE id=?', (offer['id'],))
        assert assigned['status'] == 'driver_accepted' and assigned['accepted_driver_id'] == driver_ids[DRIVER_PHONES[0]]
        assert one('SELECT status FROM shipments WHERE id=?', (item['id'],))['status'] == 'driver_assigned'
        assert negotiation(item)['status'] == 'driver_accepted'
        assert '(driver_assigned)' in admin_status(item)
        assert one('SELECT driver_phone,stage FROM shipment_operations WHERE shipment_id=?', (item['id'],)) == {
            'driver_phone': DRIVER_PHONES[0], 'stage': 'driver_assigned',
        }
        assert inbound('happy-driver-first', DRIVER_PHONES[0], 'موافق ' + item['reference'])['duplicate']
        inbound('happy-driver-repeat', DRIVER_PHONES[0], 'موافق ' + item['reference'])
        inbound('happy-driver-second', DRIVER_PHONES[1], 'موافق ' + item['reference'])
        assert not workflow.accept_driver_reply(DRIVER_PHONES[1], 'موافق ' + item['reference'])
        assert one('SELECT accepted_driver_id FROM driver_broadcasts WHERE id=?', (offer['id'],))['accepted_driver_id'] == driver_ids[DRIVER_PHONES[0]]
        assert rows('SELECT status,COUNT(*) n FROM driver_broadcast_recipients WHERE broadcast_id=? GROUP BY status ORDER BY status', (offer['id'],)) == [
            {'status': 'accepted', 'n': 1}, {'status': 'closed', 'n': 1},
        ]
        print('PASS: signed intake → owner receipt → accumulated terms → one 150 SAR-margin offer → first driver wins; duplicates are inert.')

        # Seed an Afaaq route so invalid inbound identities would hit the old
        # overly broad post-intake auto-advance branch instead of merely a menu.
        guarded_owner = '+966500000102'
        inbound('guard-select-agent', guarded_owner, 'آفاق طويق')
        guarded, _ = create_request('guarded', guarded_owner)
        baseline = negotiation(guarded)
        baseline_contacts = len(providers.owner_calls)
        invalid_variants = [
            ('wrong-account', {'account': 'different-whatsapp-account'}),
            ('conversation-group', {'conversation_group': True}),
            ('message-group', {'message_group': True}),
            ('wrong-participant', {'participant': '966500000199'}),
            ('wrong-sender-id', {'sender_id': '966500000199'}),
            ('missing-direction', {'direction': None}),
            ('outgoing', {'direction': 'outgoing'}),
        ]
        for tag, overrides in invalid_variants:
            inbound('guard-' + tag, guarded_owner, terms(2200, guarded['reference']), **overrides)
            assert negotiation(guarded) == baseline, tag
            assert not broadcasts(guarded), tag
            assert len(providers.owner_calls) == baseline_contacts, tag
        assert one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='owner_whatsapp_reply'", (guarded['id'],))['n'] == 0
        assert not advance('+966500000199', terms(2200, guarded['reference']), guarded)
        assert negotiation(guarded) == baseline
        for tag, overrides in [('wrong-account', {'account': 'different-whatsapp-account'}),
                               ('group', {'conversation_group': True})]:
            inbound('untrusted-intake-' + tag, EMPLOYEE,
                    'طلب نقل\nمن الرياض إلى جدة\nجوال صاحب الشحنة: +966500000198',
                    conversation='ci-untrusted-intake-' + tag, **overrides)
            assert len(providers.owner_calls) == baseline_contacts, tag

        # An ordinary Afaaq message must not even import the freight workflow;
        # this protects isolated routing and keeps unrelated replies side-effect free.
        original_import = builtins.__import__
        def guard_import(name, *args, **kwargs):
            if name == 'app.freight_workflow':
                raise AssertionError('Unrelated Afaaq reply imported freight workflow')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', guard_import):
            inbound('unrelated-afaaq', EMPLOYEE, 'آفاق طويق', conversation='ci-unrelated-afaaq')
        assert negotiation(guarded) == baseline
        print('PASS: wrong account, group messages, mismatched identities and unrelated Afaaq replies cannot advance freight.')

        # Signed quote metadata resolves the older pending row without any visible
        # reference. A stale quote cannot fall back to the remaining unique row.
        quote_owner = '+966500000151'
        older, _ = create_request('quote-older', quote_owner)
        newer, _ = create_request('quote-newer', quote_owner)
        older_receipt = negotiation(older)['provider_message_id']
        quote = {'quotedMessageId':'different-meta-perspective',
                 'quotedMessage':{'messageId':'internal-zernio-id','platformMessageId':older_receipt}}
        untouched = negotiation(newer)
        inbound('quote-older-terms', quote_owner, terms(2800), metadata=quote)
        assert_offer(older, 2800)
        assert negotiation(newer) == untouched
        assert inbound('quote-older-terms', quote_owner, terms(2800), metadata=quote)['duplicate']
        inbound('quote-stale', quote_owner, terms(9900), metadata=quote)
        inbound('quote-unknown', quote_owner, terms(9900), metadata={'quotedMessageId':'unknown'})
        inbound('quote-malformed', quote_owner, terms(9900), metadata={'quotedMessage':{'messageId':'internal-only'}})
        assert negotiation(newer) == untouched and not broadcasts(newer)
        assert not asyncio.run(workflow.advance_owner_whatsapp_reply(quote_owner, terms(9900),
            shipment_id=newer['id'], quoted_message_id=older_receipt))
        inbound('quote-newer-unique', quote_owner, terms(2900))
        assert_offer(newer, 2900)
        # A route can disambiguate, but only terms from that same new message count.
        route_owner = '+966500000152'
        route_a, _ = create_request('route-a', route_owner, weight=None)
        route_b, _ = create_request('route-b', route_owner, weight=None)
        execute('UPDATE shipments SET origin=?,destination=? WHERE id=?', ('جدة','الشارقة',route_b['id']))
        route_before = negotiation(route_a)
        inbound('route-ambiguous', route_owner, terms(9000))
        assert not broadcasts(route_a) and not broadcasts(route_b)
        assert 'NQ-' not in providers.replies['route-ambiguous']['message']
        assert 'WA-' not in providers.replies['route-ambiguous']['message']
        inbound('route-only', route_owner, 'جدة إلى الشارقة')
        assert negotiation(route_b)['asking_price'] is None and not broadcasts(route_b)
        inbound('route-terms', route_owner, 'جدة إلى الشارقة\n' + terms(3100))
        assert_offer(route_b, 3100)
        assert negotiation(route_a) == route_before
        print('PASS: reference-free owner quote/route/unique correlation; stale quotes and ambiguous terms stay isolated.')

        # Multiple independent shipments for one owner require an explicit,
        # unique matching reference. No newest-shipment fallback is permitted.
        shared_owner = '+966500000103'
        first, _ = create_request('shared-a', shared_owner)
        second, _ = create_request('shared-b', shared_owner)
        assert first['id'] != second['id'] and first['reference'] != second['reference']
        first_before, second_before = negotiation(first), negotiation(second)
        ambiguous = terms(2400)
        inbound('shared-ambiguous', shared_owner, ambiguous)
        assert first['reference'] not in providers.replies['shared-ambiguous']['message']
        assert second['reference'] not in providers.replies['shared-ambiguous']['message']
        assert 'رد مباشرة' in providers.replies['shared-ambiguous']['message']
        assert negotiation(first) == first_before and negotiation(second) == second_before
        assert not asyncio.run(workflow.advance_owner_whatsapp_reply(shared_owner, ambiguous))
        inbound('shared-wrong-reference', shared_owner, terms(2400, 'WA-000000000000'))
        inbound('shared-multiple-references', shared_owner, terms(2400, first['reference'] + ' ' + second['reference']))
        assert negotiation(first) == first_before and negotiation(second) == second_before
        assert not advance(shared_owner, terms(2400, second['reference']), first)
        assert negotiation(first) == first_before and negotiation(second) == second_before
        inbound('shared-specific-a', shared_owner, terms(2400, first['reference']))
        first_offer = assert_offer(first, 2400)
        assert negotiation(second) == second_before
        inbound('shared-old-reference', shared_owner, terms(9999, first['reference']))
        assert negotiation(second) == second_before
        inbound('shared-specific-b', shared_owner, terms(2600, second['reference']))
        second_offer = assert_offer(second, 2600)
        assert first_offer['id'] != second_offer['id']
        assert not workflow.accept_driver_reply(DRIVER_PHONES[0], 'موافق ' + first['reference'] + ' ' + second['reference'])
        assert one('SELECT accepted_driver_id FROM driver_broadcasts WHERE id=?', (first_offer['id'],))['accepted_driver_id'] is None
        assert one('SELECT accepted_driver_id FROM driver_broadcasts WHERE id=?', (second_offer['id'],))['accepted_driver_id'] is None
        print('PASS: same-owner shipments stay independent; ambiguous, multiple, stale and mismatched references are rejected.')

        # Different conversations bypass the receiver advisory lock, so the
        # workflow itself must serialize PostgreSQL updates and broadcast claims.
        concurrent_owner = '+966500000104'
        concurrent, _ = create_request('concurrent', concurrent_owner)
        barrier = Barrier(4)
        def reply_at_once(price):
            barrier.wait(timeout=20)
            return advance(concurrent_owner, terms(price, concurrent['reference']), concurrent)
        prices = (2800, 2900, 3000, 3100)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(reply_at_once, prices))
        winner = negotiation(concurrent)['agreed_owner_price']
        assert winner in prices
        concurrent_offer = assert_offer(concurrent, winner)
        returned_ids = {result['broadcast_id'] for result in results if result and result.get('broadcast_id')}
        assert returned_ids == {concurrent_offer['id']}, results
        assert sum(bool(result and result.get('broadcast_sent')) for result in results) >= 1, results
        assert one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='driver_offer_prepared'", (concurrent['id'],))['n'] == 1
        # Once an offer exists, later owner terms cannot rewrite its economics.
        advance(concurrent_owner, terms(9999, concurrent['reference']), concurrent)
        assert_offer(concurrent, winner)

        fragments_owner = '+966500000105'
        fragments, _ = create_request('parallel-fragments', fragments_owner, weight=None)
        barrier = Barrier(3)
        def fragment_at_once(text):
            barrier.wait(timeout=20)
            return advance(fragments_owner, fragments['reference'] + '\n' + text, fragments)
        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(fragment_at_once, ('السعر النهائي: ٣٢٠٠ ريال', 'الوزن: ٢٤ طن', 'طريقة الدفع: عند التسليم')))
        assert_offer(fragments, 3200)
        assert negotiation(fragments)['weight_tons'] == 24

        # Both eligible drivers race in real transactions: exactly one wins.
        barrier = Barrier(2)
        def accept_at_once(phone):
            barrier.wait(timeout=20)
            return workflow.accept_driver_reply(phone, 'موافق ' + concurrent['reference'])
        with ThreadPoolExecutor(max_workers=2) as executor:
            accepts = list(executor.map(accept_at_once, DRIVER_PHONES))
        assert sorted(accepts) == [False, True], accepts
        assert one('SELECT accepted_driver_id FROM driver_broadcasts WHERE id=?', (concurrent_offer['id'],))['accepted_driver_id'] in driver_ids.values()
        print('PASS: concurrent complete/partial owner replies share one broadcast; concurrent driver acceptances have one winner.')

        # Provider nonacceptance and the global kill switch must never produce
        # an affirmative "sent to drivers" response or enable acceptance.
        for mode in ('blocked', 'no_receipt'):
            blocked_owner = '+966500000' + ('106' if mode == 'blocked' else '107')
            blocked_item, _ = create_request('driver-' + mode, blocked_owner)
            providers.driver_modes[blocked_item['reference']] = mode
            result = advance(blocked_owner, terms(3400, blocked_item['reference']), blocked_item)
            assert result and result['broadcast_id'] and result['broadcast_sent'] is False, result
            assert result.get('blocked'), result
            offer = broadcasts(blocked_item)[0]
            assert offer['sent_count'] == 0 and offer['failed_count'] == len(DRIVER_PHONES)
            recipients = rows('SELECT status,provider_message_id FROM driver_broadcast_recipients WHERE broadcast_id=?', (offer['id'],))
            assert all(row['status'] == ('failed' if mode == 'blocked' else 'uncertain') and not row['provider_message_id'] for row in recipients)
            assert not workflow.accept_driver_reply(DRIVER_PHONES[0], 'موافق ' + blocked_item['reference'])
            calls_before = len(providers.sent_to_drivers(blocked_item['reference']))
            advance(blocked_owner, terms(3400, blocked_item['reference']), blocked_item)
            asyncio.run(workflow.start_driver_broadcast(offer['id']))
            assert len(providers.sent_to_drivers(blocked_item['reference'])) == calls_before

        # Durable phase evidence preserves the preflight/uncertain distinction.
        for mode, suffix in (('preflight_diagnostic','155'),('post_timeout','156')):
            diagnostic_owner = '+966500000' + suffix
            diagnostic_item, _ = create_request(mode, diagnostic_owner)
            providers.driver_modes[diagnostic_item['reference']] = mode
            result = advance(diagnostic_owner, terms(3500, diagnostic_item['reference']), diagnostic_item)
            diagnostic_bid = result['broadcast_id']
            snapshot = rows('SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=? ORDER BY id', (diagnostic_bid,))
            assert all(not r['provider_message_id'] for r in snapshot)
            if mode == 'preflight_diagnostic':
                assert all(r['status']=='failed' and r['send_phase']=='preflight_failed' and r['post_attempted_at'] is None for r in snapshot)
                assert all(json.loads(r['preflight_diagnostic'])['http_status']==429 for r in snapshot)
            else:
                assert all(r['status']=='uncertain' and r['send_phase']=='uncertain' and r['post_attempted_at'] for r in snapshot)
                assert all(r['preflight_diagnostic'] is None for r in snapshot)
            calls = len(providers.sent_to_drivers(diagnostic_item['reference']))
            from app.command_assistant import deliver_driver_broadcast
            asyncio.run(deliver_driver_broadcast(diagnostic_bid))
            assert rows('SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=? ORDER BY id', (diagnostic_bid,)) == snapshot
            assert len(providers.sent_to_drivers(diagnostic_item['reference'])) == calls
        print('PASS: sanitized durable preflight diagnostics, uncertain POST boundary evidence and no automatic replay.')

        webhook_blocked, _ = create_request('webhook-blocked', '+966500000108')
        providers.driver_modes[webhook_blocked['reference']] = 'blocked'
        inbound('webhook-blocked-terms', '+966500000108', terms(3600, webhook_blocked['reference']))
        blocked_reply = providers.replies['webhook-blocked-terms']['message']
        assert 'تجهيز وإرسال' not in blocked_reply and 'تم إرسال' not in blocked_reply, blocked_reply
        assert broadcasts(webhook_blocked)[0]['sent_count'] == 0

        partial, _ = create_request('partial-receipts', '+966500000116')
        providers.driver_modes[partial['reference']] = 'partial'
        inbound('partial-receipts-terms', '+966500000116', terms(3700, partial['reference']))
        partial_offer = broadcasts(partial)[0]
        assert partial_offer['sent_count'] == 1 and partial_offer['failed_count'] == 1
        assert partial_offer['status'] == 'completed_with_errors'
        assert '1 من 2' in providers.replies['partial-receipts-terms']['message']
        assert not workflow.accept_driver_reply(DRIVER_PHONES[1], 'موافق ' + partial['reference'])
        assert workflow.accept_driver_reply(DRIVER_PHONES[0], 'موافق ' + partial['reference'])

        kill_item, _ = create_request('kill-switch', '+966500000109')
        with patch.dict(os.environ, {'ENABLE_EXTERNAL_ACTIONS': '0'}):
            result = advance('+966500000109', terms(3800, kill_item['reference']), kill_item)
        assert result and result['broadcast_sent'] is False and result.get('blocked'), result
        assert broadcasts(kill_item)[0]['status'] == 'draft'
        assert not providers.sent_to_drivers(kill_item['reference'])
        assert not workflow.accept_driver_reply(DRIVER_PHONES[0], 'موافق ' + kill_item['reference'])

        # An old saved request is never re-contacted as a side effect of a later
        # generic Afaaq reply, even when sending becomes enabled in the meantime.
        with patch.dict(os.environ, {'ENABLE_EXTERNAL_ACTIONS': '0'}):
            stale, stale_replay = create_request('stale-contact', '+966500000110')
        assert negotiation(stale)['status'] == 'contact_blocked'
        contacts_before = len(providers.owner_calls)
        inbound('stale-contact-followup', EMPLOYEE, 'شكرًا، وصلت التفاصيل', conversation=stale_replay[3])
        assert len(providers.owner_calls) == contacts_before
        assert negotiation(stale)['status'] == 'contact_blocked'
        print('PASS: missing provider receipts, preflight rejection and kill switch stay unsent; old requests are not auto-recontacted.')

        # Owner contact uncertainty is similarly retained, never retried by a
        # duplicate webhook or generic conversation continuation.
        for mode, owner in (('blocked', '+966500000111'), ('no_receipt', '+966500000112')):
            providers.owner_modes[owner] = mode
            contact_item, replay = create_request('owner-' + mode, owner)
            state = negotiation(contact_item)
            assert state['status'] == ('contact_blocked' if mode == 'blocked' else 'contact_uncertain')
            assert not state['provider_message_id'] and not broadcasts(contact_item)
            count = len(providers.owner_calls)
            event, sender, text, conversation = replay
            assert inbound(event, sender, text, conversation=conversation)['duplicate']
            inbound('owner-' + mode + '-followup', EMPLOYEE, 'آفاق طويق', conversation=conversation)
            assert len(providers.owner_calls) == count
            assert not advance(owner, terms(4000, contact_item['reference']), contact_item)

        # A carrier offer must not be treated as a shipment-owner agreement,
        # even if a legacy row still carries awaiting_owner/whatsapp state.
        carrier, _ = create_request('carrier', '+966500000113')
        execute("UPDATE freight_negotiations SET record_kind='carrier_offer' WHERE shipment_id=?", (carrier['id'],))
        carrier_before = negotiation(carrier)
        assert not advance('+966500000113', terms(4200, carrier['reference']), carrier)
        inbound('carrier-owner-reply', '+966500000113', terms(4200, carrier['reference']))
        assert negotiation(carrier) == carrier_before and not broadcasts(carrier)

        # No eligible driver is a recoverable, truthful blocked outcome. Preserve
        # the owner agreement, and never claim a draft or message was created.
        with db() as connection:
            connection.execute("UPDATE drivers SET whatsapp_phone='invalid-' || id::text")
        try:
            no_drivers, _ = create_request('no-drivers', '+966500000114')
            result = advance('+966500000114', terms(4400, no_drivers['reference']), no_drivers)
            assert result and result['broadcast_id'] is None and result['broadcast_sent'] is False, result
            assert result.get('blocked') and negotiation(no_drivers)['last_error'], result
            assert negotiation(no_drivers)['status'] == 'owner_agreed'
            assert negotiation(no_drivers)['agreed_owner_price'] == 4400
            assert not broadcasts(no_drivers) and not providers.sent_to_drivers(no_drivers['reference'])
            no_drivers_webhook, _ = create_request('no-drivers-webhook', '+966500000115')
            inbound('no-drivers-terms', '+966500000115', terms(4600, no_drivers_webhook['reference']))
            reply = providers.replies['no-drivers-terms']['message']
            assert 'تجهيز وإرسال' not in reply and 'تم إرسال' not in reply, reply
            assert not broadcasts(no_drivers_webhook)
            assert negotiation(no_drivers_webhook)['agreed_owner_price'] == 4600
        finally:
            with db() as connection:
                for phone, driver_id in driver_ids.items():
                    connection.execute('UPDATE drivers SET whatsapp_phone=%s WHERE id=%s', (phone, driver_id))
        assert not providers.unexpected, providers.unexpected
        print('PASS: owner contact failures remain unconfirmed, carrier offers are excluded, and no-driver agreements return a truthful blocker.')

        # Exercise the same management wrappers used by the production entrypoint.
        # The classifier is simulated; owner/driver sends must stay unchanged.
        from app import load_vision, command_ai, team, manager_actions
        manager_phone = '+966509999999'
        calls_before = (len(providers.owner_calls), len(providers.driver_calls))
        records_before = (one('SELECT COUNT(*) n FROM shipments')['n'], one('SELECT COUNT(*) n FROM drivers')['n'])
        with patch.dict(os.environ, {'WHATSAPP_COMMAND_OWNER': manager_phone, 'AFAQ_TEAM': '[]'}):
            with patch.object(manager_actions, '_original_ask', side_effect=AssertionError('Greeting invoked a paid model')):
                result = inbound('manager-greeting', manager_phone, 'مرحبًا نيرمين')
                assert result['agent'] == 'owner'
                assert 'تقدر تتكلم معي بشكل عادي' in providers.replies['manager-greeting']['message']
                assert inbound('manager-greeting', manager_phone, 'مرحبًا نيرمين')['duplicate']
            with patch.object(manager_actions, '_original_ask', return_value={'action': 'shipment_status', 'reference': item['reference']}):
                inbound('manager-status', manager_phone, 'ما حالة الشحنة ' + item['reference'] + '؟')
                assert '(driver_assigned)' in providers.replies['manager-status']['message']
            with patch.object(manager_actions, '_original_ask', return_value={'action': 'send_message', 'to': 'سارة', 'text': 'secret'}):
                with patch.object(manager_actions, 'deliver', side_effect=AssertionError('Conversation sent an external message')):
                    inbound('manager-question', manager_phone, 'هل يمكنك إرسال رسالة إلى سارة؟')
                    assert 'هل تريد إرسال' in providers.replies['manager-question']['message']
            with db() as connection:
                legacy = connection.execute("""INSERT INTO shipments(reference,service_type,origin,destination,status,created_at,updated_at)
                    VALUES('CI-LEGACY','نقل','الرياض','جدة','in_transit',NOW(),NOW()) RETURNING reference""").fetchone()
            assert admin_status(legacy) == 'CI-LEGACY\nمن الرياض إلى جدة\nالحالة: in_transit'
            assert admin_status({'reference': "' OR 1=1 --"}) == 'لم أجد هذه الشحنة.'
        assert (len(providers.owner_calls), len(providers.driver_calls)) == calls_before
        assert (one('SELECT COUNT(*) n FROM shipments')['n'], one('SELECT COUNT(*) n FROM drivers')['n']) == (records_before[0] + 1, records_before[1])
        assert not providers.unexpected, providers.unexpected
        print('PASS: read-only transport status, legacy fallback, signed natural greeting/query, duplicate idempotency and no chat-triggered sends.')
        from transport_disclosed_acceptance import run_disclosed
        run_disclosed(providers, inbound)
        from broadcast_recovery_acceptance import run_recovery
        run_recovery(providers, inbound)
        from driver_test_context_acceptance import run_driver_test_context
        run_driver_test_context(providers, inbound)
    client.close()


def main():
    import httpx
    import psycopg
    from psycopg import sql

    url = database_target()
    schema = 'transport_test_' + secrets.token_hex(6)
    providers = Providers()
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        options = '-c search_path=' + schema + ' -c statement_timeout=30000 -c lock_timeout=15000'
        environment = {
            'DATABASE_URL': url + '?' + urlencode({'options': options}, quote_via=quote),
            'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '1',
            'ADMIN_EMAIL': 'transport-acceptance@example.invalid',
            'ADMIN_PASSWORD': secrets.token_urlsafe(24),
            'WHATSAPP_PROVIDER': 'zernio', 'FREIGHT_OWNER_CONTACT_CHANNEL': 'whatsapp',
            'WHATSAPP_COMMAND_OWNER': '', 'WHATSAPP_COMMAND_ACCOUNT_ID': ACCOUNT,
            'ZERNIO_WHATSAPP_ACCOUNT_ID': ACCOUNT,
            'ZERNIO_API_KEY': 'transport-ci-not-a-real-key', 'ZERNIO_WEBHOOK_SECRET': SECRET,
            'BROWSER_COOKIE_SECURE': '0',
        }
        async def fake_http(client, method, url, **kwargs):
            return await providers.http_request(client, method, url, **kwargs)
        original_connect = socket.socket.connect
        def local_connections_only(sock, address):
            # HTTP is mocked above; fail closed for any accidental Python socket
            # egress while still permitting loopback PostgreSQL/Unix sockets.
            if isinstance(address, tuple) and address[0] not in {'localhost', '127.0.0.1', '::1'}:
                providers.unexpected.append(('socket', str(address)))
                raise AssertionError('Live network disabled in transport acceptance')
            return original_connect(sock, address)
        with patch.dict(os.environ, environment), patch.object(httpx.AsyncClient, 'request', fake_http), patch.object(socket.socket, 'connect', local_connections_only):
            run(providers)
        assert not providers.unexpected, providers.unexpected
        print('PASS: transport PostgreSQL acceptance complete. Live external sends: 0 (all receipts simulated).')
    finally:
        # Only this generated fixture schema can be removed, including on failure.
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
