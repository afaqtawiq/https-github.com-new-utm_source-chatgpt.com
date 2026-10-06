"""Owner receipt/provenance regressions inside the localhost-only PG harness.

All provider observations are synthetic. Reads cannot send, fabricate a reply,
change commercial values, or turn historical evidence into current-contact proof.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi import HTTPException


def run_owner_delivery(providers, inbound):
    from app import owner_delivery as delivery, freight_workflow as workflow
    from app import bootstrap, zernio_whatsapp as transport
    from app.storage import db, one, rows, execute, utcnow, create_session
    from app.whatsapp_admin import shipment_status
    from fastapi.testclient import TestClient

    uid = one("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")['id']
    actor = {'user_id': uid, 'role': 'admin', 'csrf': 'owner-receipt-csrf'}
    account, now = transport.account_id(), utcnow()
    calls, changes = [], {}
    serial, status, mode = 0, 'failed', 'normal'
    receipt_started, receipt_release = Event(), Event()

    def fixture(*, mid='owner-message', legacy=False, test=False):
        nonlocal serial
        serial += 1
        sid = execute('''INSERT INTO shipments(reference,service_type,origin,destination,status,is_test,revenue,cost,created_at,updated_at)
            VALUES(?,'freight','جدة','الشارقة',?, ?,0,0,?,?)''',
            ('OWNER-CI-' + str(serial), 'test_pending' if test else 'new', test, now, now))
        execute('''INSERT INTO freight_negotiations(shipment_id,owner_phone,status,contact_channel,
            provider_message_id,owner_message_provider,owner_message_account_id,owner_message_conversation_id,
            contacted_at,created_at,updated_at) VALUES(?,'+966500000711','awaiting_owner','whatsapp',?,?,?,?,?,?,?)''',
            (sid, mid, None if legacy else 'zernio', None if legacy else account,
             None if legacy else 'owner-conversation', now if mid else None, now, now))
        return sid

    def record_bound_reply(sid, *, at=None, inbound_account=None, inbound_conversation='owner-conversation'):
        with db() as c:
            c.execute('SELECT id FROM shipments WHERE id=%s FOR UPDATE', (sid,)).fetchone()
            contact = c.execute('SELECT * FROM freight_negotiations WHERE shipment_id=%s FOR UPDATE', (sid,)).fetchone()
            event = c.execute('''INSERT INTO shipment_events(shipment_id,event_type,summary,stage,happened_at)
                VALUES(%s,'owner_whatsapp_reply','CI verified reply','awaiting_owner',%s) RETURNING id''',
                (sid, at or now + timedelta(seconds=1))).fetchone()
            assert delivery.bind_reply(c, contact, event['id'], account_id=inbound_account or account,
                conversation_id=inbound_conversation, owner_phone=contact['owner_phone'],
                inbound_event_id='ci-bound-' + str(event['id']))
        return event['id']

    def evidence(sid):
        with db() as c:
            c.execute('SET TRANSACTION READ ONLY')
            return delivery.snapshot(c, sid)

    def fields(sid):
        return {'csrf': actor['csrf'], 'contact_fingerprint': evidence(sid)['fingerprint'], 'confirm_lookup': 'yes'}

    def request(values):
        async def body(): return urlencode(values).encode()
        return SimpleNamespace(body=body)

    def refresh(sid, values=None):
        return asyncio.run(workflow.reconcile_owner_delivery(sid, request(values or fields(sid))))

    def isolate_pending():
        execute("UPDATE freight_negotiations SET status='needs_review' WHERE shipment_id IN (SELECT id FROM shipments WHERE reference LIKE ?)", ('OWNER-CI-%',))

    async def read(client, path, params=None):
        calls.append((path, params))
        if mode == 'unavailable':
            raise transport.WhatsAppBlocked('synthetic provider lookup failed')
        if path == '/accounts':
            return {'accounts': [{'_id': account, 'platform': 'whatsapp', 'isActive': True}]}
        if path == '/inbox/conversations':
            data = [{'id': 'owner-conversation', 'accountId': account, 'platform': 'whatsapp',
                     'participantId': '966500000711', 'isGroup': False}]
            if mode == 'ambiguous': data.append({**data[0], 'id': 'other-conversation'})
            return {'data': data}
        assert path == '/inbox/conversations/owner-conversation/messages', path
        if mode == 'concurrent':
            receipt_started.set()
            assert receipt_release.wait(10), 'concurrency fixture timed out'
        if mode == 'change_contact':
            execute("UPDATE freight_negotiations SET owner_phone='+966500000712' WHERE shipment_id=?", (sid,))
        if mode == 'owner_reply':
            record_bound_reply(sid)
        return {'messages': [{'id': 'owner-message', 'direction': 'outgoing', 'accountId': account,
            'platform': 'whatsapp', 'conversationId': 'owner-conversation', 'deliveryStatus': status,
            'deliveryError': {'code': 131042} if status == 'failed' else None, **changes}]}

    before_sends = len(providers.owner_calls), len(providers.driver_calls)
    with patch.object(workflow, 'session', return_value=actor), patch.object(transport, 'read', read):
        sid = fixture()
        assert evidence(sid)['delivery_status'] == 'accepted'
        initial = one('SELECT * FROM freight_negotiations WHERE shipment_id=?', (sid,))
        shipment_before = one('SELECT * FROM shipments WHERE id=?', (sid,))
        token = fields(sid)
        refresh(sid, token)
        failed = evidence(sid)
        assert failed['delivery_status'] == 'failed' and failed['receipt']['error_code'] == 131042
        assert failed['receipt']['provider_message_id'] == initial['provider_message_id']
        assert failed['receipt']['checked_by'] == uid
        assert one('SELECT * FROM freight_negotiations WHERE shipment_id=?', (sid,)) == initial
        assert one('SELECT * FROM shipments WHERE id=?', (sid,)) == shipment_before
        # Repeated stale forms cannot incur additional provider reads.
        reads_before = len(calls)
        try: refresh(sid, token)
        except HTTPException as exc: assert exc.status_code == 409
        else: raise AssertionError('Repeated receipt form accepted')
        assert len(calls) == reads_before
        request_view = SimpleNamespace(cookies={})
        detail = workflow.workflow_detail(sid, request_view).body.decode()
        listing = workflow.workflow_page(request_view).body.decode()
        api_item = next(x for x in workflow.workflow_api(request_view)['items'] if x['shipment_id'] == sid)
        with db() as c:
            c.execute('SET TRANSACTION READ ONLY')
            report = shipment_status(c, shipment_before['reference'])
        assert 'owner_delivery_failed' in detail and '131042' in detail
        assert 'owner_delivery_failed' in listing and api_item['effective_status'] == 'owner_delivery_failed'
        assert api_item['owner_delivery_evidence']['delivery_status'] == 'failed'
        assert 'owner_delivery_failed' in report and '131042' in report
        assert "contact-owner'" not in detail
        assert len(calls) == reads_before
        status = 'delivered'
        refresh(sid)
        delivered = evidence(sid)
        assert delivered['delivery_status'] == 'delivered'
        row = failed['receipt']
        execute('''INSERT INTO freight_owner_receipts(negotiation_id,provider_message_id,owner_phone,contact_fingerprint,
            provider,account_id,conversation_id,delivery_status,error_code,reason,checked_at,checked_by)
            VALUES(?,?,?,?,'zernio',?,?,'failed',131042,'CI old response',?,?)''',
            (initial['id'], initial['provider_message_id'], initial['owner_phone'], delivery.fingerprint(initial),
             account, 'owner-conversation', row['checked_at'] - timedelta(minutes=1), uid))
        assert evidence(sid)['receipt']['id'] == delivered['receipt']['id']
        mode = 'unavailable'
        refresh(sid)
        assert evidence(sid)['delivery_status'] == 'unknown'
        assert 'owner_delivery_unknown' in workflow.workflow_detail(sid, request_view).body.decode()
        assert len(rows('SELECT * FROM freight_owner_receipts WHERE negotiation_id=?', (initial['id'],))) == 4
        mode = 'normal'
        # Legacy acceptance needs unique conversation plus exact outbound identity.
        sid, status = fixture(legacy=True), 'failed'
        refresh(sid)
        assert evidence(sid)['delivery_status'] == 'failed'
        assert one('SELECT owner_message_account_id FROM freight_negotiations WHERE shipment_id=?', (sid,))['owner_message_account_id'] is None
        empty_sid = fixture(mid=None)
        assert evidence(empty_sid)['delivery_status'] == 'not_sent'
        assert 'owner_delivery_failed' not in workflow.workflow_detail(empty_sid, request_view).body.decode()
        reads_before = len(calls)
        try: refresh(empty_sid)
        except HTTPException as exc: assert exc.status_code == 409
        else: raise AssertionError('Unsent message reconciled')
        assert len(calls) == reads_before
        for changes in ({'id': 'wrong'}, {'accountId': 'wrong'}, {'conversationId': 'wrong'},
                        {'direction': 'incoming'}, {'platform': 'telegram'}, {'deliveredAt': 'now'}):
            sid = fixture()
            refresh(sid)
            assert evidence(sid)['delivery_status'] == 'unknown', changes
        changes, mode = {}, 'ambiguous'
        sid = fixture()
        refresh(sid)
        assert evidence(sid)['delivery_status'] == 'unknown'
        mode, sid = 'normal', fixture()
        refresh(sid)
        for column in ('owner_message_conversation_id', 'owner_message_account_id', 'owner_phone', 'provider_message_id'):
            old = one('SELECT * FROM freight_negotiations WHERE shipment_id=?', (sid,))
            execute('UPDATE freight_negotiations SET ' + column + '=? WHERE shipment_id=?', ('changed', sid))
            assert evidence(sid)['receipt'] is None, column
            execute('UPDATE freight_negotiations SET ' + column + '=? WHERE shipment_id=?', (old[column], sid))
        sid, mode = fixture(), 'change_contact'
        try: refresh(sid)
        except HTTPException as exc: assert exc.status_code == 409
        else: raise AssertionError('Stale contact accepted')
        assert evidence(sid)['receipt'] is None
        # Verified replies can arrive while lookup holds only its advisory lock.
        sid, mode = fixture(test=True), 'owner_reply'
        refresh(sid)
        assert evidence(sid)['replied_at']
        assert 'الحالة الحالية: awaiting_owner' in workflow.workflow_detail(sid, request_view).body.decode()
        assert one('SELECT COUNT(*) n FROM driver_broadcasts WHERE shipment_id=?', (sid,))['n'] == 0
        sid, mode = fixture(), 'concurrent'
        token = fields(sid)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(refresh, sid, token)
            assert receipt_started.wait(10)
            reads_before = len(calls)
            try: refresh(sid, token)
            except HTTPException as exc: assert exc.status_code == 409
            else: raise AssertionError('Concurrent metered read started')
            assert len(calls) == reads_before
            record_bound_reply(sid)
            receipt_release.set()
            assert first.result().status_code == 303
        assert evidence(sid)['replied_at'] and evidence(sid)['delivery_status'] == 'failed'
        mode = 'normal'
        # NOW() is transaction-start time, not proof of reply identity.
        execute("UPDATE shipment_events SET happened_at=? WHERE shipment_id=? AND event_type='owner_whatsapp_reply'",
                (now - timedelta(minutes=1), sid))
        assert evidence(sid)['replied_at'] < evidence(sid)['accepted_at']
        assert 'الحالة الحالية: awaiting_owner' in workflow.workflow_detail(sid, request_view).body.decode()
        original = one('SELECT * FROM freight_negotiations WHERE shipment_id=?', (sid,))
        for column in ('owner_phone', 'owner_message_account_id', 'owner_message_conversation_id', 'provider_message_id', 'contacted_at'):
            value = now + timedelta(days=1) if column == 'contacted_at' else 'changed'
            execute('UPDATE freight_negotiations SET ' + column + '=? WHERE shipment_id=?', (value, sid))
            assert evidence(sid)['replied_at'] is None and evidence(sid)['historical_replied_at'], column
            execute('UPDATE freight_negotiations SET ' + column + '=? WHERE shipment_id=?', (original[column], sid))
        assert evidence(sid)['replied_at']
        # Legacy unbound events are history and never silently backfilled.
        sid = fixture()
        refresh(sid)
        execute("INSERT INTO shipment_events(shipment_id,event_type,summary,stage,happened_at) VALUES(?,'owner_whatsapp_reply','CI legacy reply','awaiting_owner',?)", (sid, now))
        assert evidence(sid)['replied_at'] is None and evidence(sid)['historical_replied_at']
        detail = workflow.workflow_detail(sid, request_view).body.decode()
        assert 'الحالة الحالية: owner_delivery_failed' in detail and 'دليلًا تاريخيًا' in detail
        mode = 'unavailable'
        refresh(sid)
        assert 'الحالة الحالية: owner_delivery_unknown' in workflow.workflow_detail(sid, request_view).body.decode()
        execute("UPDATE freight_negotiations SET status='owner_agreed' WHERE shipment_id=?", (sid,))
        assert 'الحالة الحالية: owner_agreed' in workflow.workflow_detail(sid, request_view).body.decode()
        execute("UPDATE shipments SET status='in_transit' WHERE id=?", (sid,))
        assert 'الحالة الحالية: in_transit' in workflow.workflow_detail(sid, request_view).body.decode()
        mode, sid = 'normal', fixture(legacy=True)
        with db() as c:
            contact = c.execute('SELECT * FROM freight_negotiations WHERE shipment_id=%s', (sid,)).fetchone()
            assert not delivery.bind_reply(c, contact, -1, account_id=account,
                conversation_id='owner-conversation', owner_phone=contact['owner_phone'], inbound_event_id='unbound')
        refresh(sid)
        record_bound_reply(sid)
        assert evidence(sid)['replied_at']
        assert one('SELECT binding_source FROM freight_owner_reply_bindings WHERE negotiation_id=?', (contact['id'],))['binding_source'] == 'verified_receipt'
        # A different currently configured account/CID cannot claim an old send.
        isolate_pending()
        sid = fixture()
        refresh(sid)
        before = one('SELECT * FROM freight_negotiations WHERE shipment_id=?', (sid,))
        with patch.dict('os.environ', {'ZERNIO_WHATSAPP_ACCOUNT_ID': 'new-account', 'WHATSAPP_COMMAND_ACCOUNT_ID': 'new-account'}):
            inbound('owner-wrong-current-account', before['owner_phone'], 'شكرًا', account='new-account', conversation='new-account-conversation')
        inbound('owner-wrong-current-conversation', before['owner_phone'], 'شكرًا', conversation='different-conversation')
        assert one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='owner_whatsapp_reply'", (sid,))['n'] == 0
        assert one('SELECT * FROM freight_negotiations WHERE shipment_id=?', (sid,)) == before
        assert evidence(sid)['replied_at'] is None and evidence(sid)['delivery_status'] == 'failed'
        assert 'الحالة الحالية: owner_delivery_failed' in workflow.workflow_detail(sid, request_view).body.decode()
        assert not rows('SELECT id FROM driver_broadcasts WHERE shipment_id=?', (sid,))
        inbound('owner-exact-current-contact', before['owner_phone'], 'شكرًا', conversation='owner-conversation')
        assert evidence(sid)['replied_at'] and evidence(sid)['delivery_status'] == 'failed'
        bindings = rows('SELECT * FROM freight_owner_reply_bindings WHERE negotiation_id=?', (before['id'],))
        assert len(bindings) == 1 and bindings[0]['account_id'] == account and bindings[0]['conversation_id'] == 'owner-conversation'
        assert bindings[0]['provider_message_id'] == before['provider_message_id'] and bindings[0]['binding_source'] == 'accepted_contact'
        assert inbound('owner-exact-current-contact', before['owner_phone'], 'شكرًا', conversation='owner-conversation')['duplicate']
        assert len(rows('SELECT * FROM freight_owner_reply_bindings WHERE negotiation_id=?', (before['id'],))) == 1
        # Force overlap between real manual-data code's shipment-first locks and
        # inbound selection, then ensure the edited contact is rechecked.
        isolate_pending()
        sid = fixture()
        shipment_locked, inbound_at_shipment, release_manual = Event(), Event(), Event()
        from app import zernio_receiver as receiver
        actual_workflow_db, actual_receiver_db = workflow.db, receiver.db
        @contextmanager
        def paused_manual_db():
            with actual_workflow_db() as c:
                def execute_manual(sql, args=()):
                    result = c.execute(sql, args)
                    if sql == 'SELECT id FROM shipments WHERE id=%s FOR UPDATE' and args == (sid,):
                        shipment_locked.set()
                        assert release_manual.wait(10), 'manual race release timed out'
                    return result
                yield SimpleNamespace(execute=execute_manual)
        @contextmanager
        def observed_inbound_db():
            with actual_receiver_db() as c:
                def execute_inbound(sql, args=()):
                    if sql == 'SELECT id FROM shipments WHERE id=%s FOR UPDATE' and args == (sid,):
                        inbound_at_shipment.set()
                    return c.execute(sql, args)
                yield SimpleNamespace(execute=execute_inbound)
        form = {'csrf': actor['csrf'], 'origin': 'جدة', 'destination': 'الشارقة',
                'owner_phone': '+966500000799', 'weight_tons': '20'}
        with patch.object(workflow, 'db', paused_manual_db), patch.object(receiver, 'db', observed_inbound_db):
            with ThreadPoolExecutor(max_workers=2) as pool:
                manual = pool.submit(asyncio.run, workflow.save_manual_data(sid, request(form)))
                assert shipment_locked.wait(10), 'manual edit did not acquire shipment first'
                incoming = pool.submit(inbound, 'owner-manual-edit-race', '+966500000711', 'شكرًا', conversation='owner-conversation')
                try:
                    assert inbound_at_shipment.wait(10), 'inbound did not use shipment-first locking'
                finally:
                    release_manual.set()
                assert manual.result(timeout=10).status_code == 303
                assert incoming.result(timeout=10)['state'] == 'sent'
        changed = one('SELECT * FROM freight_negotiations WHERE shipment_id=?', (sid,))
        assert changed['owner_phone'] == '+966500000799' and changed['status'] == 'ready_to_contact'
        assert one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='owner_whatsapp_reply'", (sid,))['n'] == 0
        assert not rows('SELECT * FROM freight_owner_reply_bindings WHERE negotiation_id=?', (changed['id'],))
        assert not rows('SELECT id FROM driver_broadcasts WHERE shipment_id=?', (sid,))
        # Explicit confirmation, CSRF, role, permission and MFA precede reads.
        reads_before = len(calls)
        for data, role, code in (({**fields(sid), 'csrf': 'wrong'}, 'admin', 403),
                                 ({**fields(sid), 'confirm_lookup': 'no'}, 'admin', 400),
                                 (fields(sid), 'viewer', 403)):
            with patch.object(workflow, 'session', return_value={**actor, 'role': role}):
                try: refresh(sid, data)
                except HTTPException as exc: assert exc.status_code == code
                else: raise AssertionError('Unapproved lookup')
        assert len(calls) == reads_before
        path = f'/freight-workflow/{sid}/owner-delivery/reconcile'
        assert bootstrap.sensitive_permission(SimpleNamespace(method='POST', url=SimpleNamespace(path=path))) == 'send_whatsapp'
        session_id, csrf, _ = create_session(uid)
        client = TestClient(bootstrap.app, base_url='http://testserver')
        client.cookies.set('gla_session', session_id)
        client.headers['origin'] = 'http://testserver'
        with patch.object(bootstrap, 'has_permission', return_value=False):
            assert client.post(path, data={**fields(sid), 'csrf': csrf}).status_code == 403
        with patch.object(bootstrap, 'has_permission', return_value=True), patch.object(bootstrap, 'mfa_state', return_value={'mfa_enabled': True}), patch.object(bootstrap, 'recent_stepup', return_value=False):
            response = client.post(path, data={**fields(sid), 'csrf': csrf})
            assert response.status_code == 428, response.text
            assert response.json()['step_up'] == f'/mfa/step-up?next=/freight-workflow/{sid}'
        client.close()
        assert len(calls) == reads_before
    assert (len(providers.owner_calls), len(providers.driver_calls)) == before_sends
    print('PASS: owner receipts and reply identity, immutable business rows, stale/concurrent safety, historical-only legacy replies, changed accounts, shipment-first locks, MFA and zero live sends.')
