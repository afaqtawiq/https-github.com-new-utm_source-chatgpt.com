"""Additional real-PostgreSQL assertions called inside the network-isolated fixture."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi import BackgroundTasks, HTTPException


def run_disclosed(providers, inbound):
    from app import command_assistant as commands, freight_workflow as workflow
    from app.naqliat_connector import NaqliatLoad, _save
    from app.storage import one, rows, execute, db
    from app.transport_test import DISCLAIMER, display_reference, test_broadcast_context, owner_inquiry_digest
    from app.zernio_whatsapp import required_templates, template_parameters

    owner = '+966509999998'
    payload = dict(origin='جدة', destination='الشارقة', owner_phone=owner,
                   description='CI isolated disclosed transport test')
    real_id = _save(NaqliatLoad(**payload, capture_method='android_accessibility'))[2]
    before_real = rows('SELECT * FROM business_shipments ORDER BY id')
    before_owner_calls = len(providers.owner_calls)
    saved = _save(NaqliatLoad(**payload, capture_method='manual_test'))
    sid = saved[2]
    assert sid != real_id and _save(NaqliatLoad(**payload, capture_method='manual_test'))[2] == sid
    item = one('SELECT * FROM shipments WHERE id=?', (sid,))
    ref = item['reference']
    assert item['is_test'] and item['status'] == 'test_pending'
    assert not one('SELECT id FROM business_shipments WHERE id=?', (sid,))
    asyncio.run(workflow.contact_owner(sid, approved=True))
    assert len(providers.owner_calls) == before_owner_calls
    assert not workflow.sync_retell_negotiation({'shipment_id': sid, 'freight_negotiation': True}, {'agreed_price': 5000})

    # Exercise the runnable browser route, with real middleware and single-flight
    # PostgreSQL claims. The provider remains the fixture fake.
    from app.bootstrap import app
    from app.storage import create_session
    from fastapi.testclient import TestClient
    uid = one("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")['id']
    session_id, csrf, _ = create_session(uid)
    web = TestClient(app, base_url='http://testserver', follow_redirects=False)
    web.cookies.set('gla_session', session_id)
    web.headers['origin'] = 'http://testserver'
    inquiry_item = one('SELECT s.*,n.owner_phone FROM shipments s JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?', (sid,))
    inquiry_form = {'csrf':csrf, 'test_owner_confirmed':'yes', 'test_owner_preview':owner_inquiry_digest(inquiry_item)}
    inquiry_path = f'/freight-workflow/{sid}/test-owner-inquiry'
    detail = web.get(f'/freight-workflow/{sid}')
    assert detail.status_code == 200 and inquiry_path in detail.text and DISCLAIMER in detail.text, detail.text
    assert web.post(inquiry_path, data=inquiry_form).status_code == 428
    assert len(providers.owner_calls) == before_owner_calls
    with patch('app.bootstrap.mfa_state', return_value={'mfa_enabled':1}), patch('app.bootstrap.recent_stepup', return_value=False):
        stepped = web.post(inquiry_path, data=inquiry_form)
        assert stepped.status_code == 428 and f'/freight-workflow/{sid}' in stepped.json()['step_up']
    with patch('app.bootstrap.mfa_state', return_value={'mfa_enabled':1}), patch('app.bootstrap.recent_stepup', return_value=True):
        assert web.post(inquiry_path, data={**inquiry_form,'csrf':'wrong'}).status_code == 403
        assert web.post(inquiry_path, data={**inquiry_form,'test_owner_confirmed':''}).status_code == 400
        assert web.post(inquiry_path, data={**inquiry_form,'test_owner_preview':'stale'}).status_code == 400
        barrier = Barrier(2)
        def inquiry_once(_):
            barrier.wait()
            return web.post(inquiry_path, data=inquiry_form).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(inquiry_once, range(2))) == [303,409]
    assert len(providers.owner_calls) == before_owner_calls + 1
    assert providers.owner_calls[-1][0] == owner and providers.owner_calls[-1][1].startswith(DISCLAIMER)
    assert ref not in providers.owner_calls[-1][1] and 'جدة إلى الشارقة' in providers.owner_calls[-1][1]
    contacted = one('SELECT test_owner_contact_status,provider_message_id,status FROM freight_negotiations WHERE shipment_id=?', (sid,))
    assert contacted['test_owner_contact_status'] == 'sent' and contacted['provider_message_id'].startswith('fake-owner-')
    assert contacted['status'] == 'awaiting_owner'
    assert one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='test_owner_inquiry_submitted'", (sid,))['n'] == 1
    assert not rows('SELECT id FROM driver_broadcasts WHERE shipment_id=?', (sid,))
    assert web.post(f'/freight-workflow/{sid}/manual-data', data={'csrf':csrf,'origin':'جدة','destination':'دبي','owner_phone':owner}).status_code == 409
    before_owner_calls += 1
    web.close()
    print('PASS: disclosed owner inquiry UI, admin/CSRF/MFA checks, concurrent single send and persisted actual provider receipt.')

    def terms(reference=ref):
        return (reference + '\nالسعر النهائي: 2000 ريال\nالوزن: 20 طن'
                '\nالتنزيل: مستودع تجريبي\nطريقة الدفع: محاكاة دون دفع')

    # The verified administrator may also be the test owner. A unique pending
    # inquiry accepts a reference-free reply; admin command routing is unchanged.
    with patch.dict('os.environ', {'WHATSAPP_COMMAND_OWNER': owner, 'AFAQ_TEAM': '[]'}):
        inbound('test-owner-no-reference', owner, 'السعر: 2000\nالدفع: محاكاة دون دفع\nالتحميل من خارج الميناء')
        saved = one('SELECT asking_price,weight_tons,loading_port_status FROM freight_negotiations WHERE shipment_id=?', (sid,))
        assert saved['asking_price'] == 2000 and saved['loading_port_status'] == 'outside'
        assert not rows('SELECT id FROM driver_broadcasts WHERE shipment_id=?', (sid,))
        assert 'الوزن' in providers.replies['test-owner-no-reference']['message']
        inbound('test-owner-wrong-number', '+966509999997', terms())
        assert not rows('SELECT id FROM driver_broadcasts WHERE shipment_id=?', (sid,))
        inbound('test-owner-terms', owner, terms(''))
        assert inbound('test-owner-terms', owner, terms(''))['duplicate']
    offer = one('SELECT * FROM driver_broadcasts WHERE shipment_id=?', (sid,))
    bid = offer['id']
    assert offer['is_test'] and offer['status'] == 'draft'
    assert len(rows('SELECT id FROM driver_broadcasts WHERE shipment_id=?', (sid,))) == 1
    assert 'اختبار' in providers.replies['test-owner-terms']['message']
    assert 'تم حفظ الاتفاق' not in providers.replies['test-owner-terms']['message']
    assert not providers.sent_to_drivers(ref)
    assert not asyncio.run(workflow.start_driver_broadcast(bid))
    template = next(t for t in required_templates() if t['name'] == 'afaaq_transport_driver_offer_v1_ar')
    assert template_parameters(template, offer['message'])[0] == display_reference(ref, True)
    assert offer['message'].count(DISCLAIMER) == 2
    assert one('SELECT revenue,cost FROM shipments WHERE id=?', (sid,)) == {'revenue': 0, 'cost': 0}
    assert workflow.prepare_driver_offer(sid, None) == bid

    admin = {'user_id': one("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")['id'],
             'role': 'admin', 'csrf': 'ci-test-csrf'}
    def request(data):
        async def body(): return urlencode(data).encode()
        return SimpleNamespace(body=body)
    def send(data, role='admin', deliver=False):
        tasks = BackgroundTasks()
        with patch.object(commands, 'session', return_value={**admin, 'role': role}):
            result = asyncio.run(commands.send_broadcast(bid, request(data), tasks))
            if deliver: asyncio.run(tasks())
        return result
    def blocked(data, status, role='admin'):
        try:
            send(data, role)
        except HTTPException as exc:
            assert exc.status_code == status, (exc.status_code, exc.detail)
        else:
            raise AssertionError('Unapproved test broadcast was accepted')

    # Correct a legacy wholly-unsent audience through the guarded UI. The
    # original driver registry is immutable; invalid recipients stay as audit rows.
    from app.driver_offer import preview_plan
    driver_snapshot = rows('SELECT * FROM drivers ORDER BY id')
    original_count = offer['recipient_count']
    driver_id = one('SELECT driver_id FROM driver_broadcast_recipients WHERE broadcast_id=? LIMIT 1', (bid,))['driver_id']
    for number in ('+966055504207', '+966050850729'):
        execute("INSERT INTO driver_broadcast_recipients(broadcast_id,driver_id,driver_name,phone,status) VALUES(?,?,?,?,'pending')", (bid,driver_id,'CI malformed contact',number))
    execute('UPDATE driver_broadcasts SET recipient_count=recipient_count+2 WHERE id=?', (bid,))
    execute("UPDATE freight_negotiations SET loading_port_status='inside' WHERE shipment_id=?", (sid,))
    legacy = one('SELECT * FROM driver_broadcasts WHERE id=?', (bid,))
    legacy_digest = test_broadcast_context(legacy)['digest']
    with db() as c:
        candidates = c.execute('SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=%s ORDER BY id', (bid,)).fetchall()
        plan = preview_plan(legacy, candidates, commands._preview_message(c, legacy))
    assert len(plan['active']) == original_count and len(plan['excluded']) == 2
    refresh_data = {'csrf':csrf,'refresh_confirmed':'yes','refresh_preview':plan['digest']}
    web = TestClient(app, base_url='http://testserver', follow_redirects=False)
    web.cookies.set('gla_session',session_id)
    web.headers['origin'] = 'http://testserver'
    refresh_path = f'/commands/broadcast/{bid}/refresh-preview'
    assert web.post(refresh_path,data=refresh_data).status_code == 428
    with patch('app.bootstrap.mfa_state', return_value={'mfa_enabled':1}), patch('app.bootstrap.recent_stepup', return_value=True):
        assert web.post(refresh_path,data={**refresh_data,'csrf':'wrong'}).status_code == 403
        assert web.post(refresh_path,data={**refresh_data,'refresh_confirmed':''}).status_code == 400
        assert web.post(refresh_path,data={**refresh_data,'refresh_preview':'stale'}).status_code == 409
        barrier = Barrier(2)
        def refresh_or_send(which):
            barrier.wait()
            if which == 'refresh':
                return web.post(refresh_path,data=refresh_data).status_code
            return web.post(f'/commands/broadcast/{bid}/send',data={'csrf':csrf,'confirmed':'yes',
                'test_confirmed':'yes','test_preview':legacy_digest}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(refresh_or_send, ('refresh','send')))
        assert results[0] == 303 and results[1] in (400,409), results
    web.close()
    offer = one('SELECT * FROM driver_broadcasts WHERE id=?', (bid,))
    assert offer['status'] == 'draft' and offer['recipient_count'] == original_count
    assert offer['sent_count'] == offer['failed_count'] == 0 and not offer['test_preview_digest']
    assert 'جدة (التحميل داخل الميناء)' in offer['message']
    assert template_parameters(template, offer['message'])[1] == 'جدة (التحميل داخل الميناء)'
    exclusions = rows("SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=? AND status='excluded' ORDER BY id", (bid,))
    assert len(exclusions) == 2 and all(r['last_error'].startswith('invalid_saudi_trunk_prefix:') for r in exclusions)
    assert rows('SELECT * FROM drivers ORDER BY id') == driver_snapshot
    assert not providers.sent_to_drivers(ref)
    assert one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='driver_preview_refreshed'", (sid,))['n'] == 1
    print('PASS: guarded unsent preview refresh, Saudi contact exclusions, faithful port template, stale approval and send/refresh race.')

    with patch.object(commands, 'session', return_value=admin):
        preview = commands.broadcast_review(bid, SimpleNamespace()).body.decode()
    assert DISCLAIMER in preview and 'name=test_confirmed' in preview and 'name=test_preview' in preview
    assert 'https://wa.me/' not in preview  # No manual-send bypass in a test preview.
    base = {'csrf': admin['csrf'], 'confirmed': 'yes'}
    blocked(base, 400)
    blocked({**base, 'test_confirmed': 'yes', 'test_preview': 'stale'}, 400)
    blocked({**base, 'test_confirmed': 'yes'}, 403, role='transport')
    assert not providers.sent_to_drivers(ref)

    # Direct worker invocation cannot send before the explicit approval record.
    execute("UPDATE driver_broadcasts SET status='sending' WHERE id=?", (bid,))
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert not providers.sent_to_drivers(ref)
    assert one('SELECT status FROM driver_broadcasts WHERE id=?', (bid,))['status'] == 'test_blocked'
    execute("UPDATE driver_broadcasts SET status='draft' WHERE id=?", (bid,))
    digest = test_broadcast_context(offer)['digest']
    approved = {**base, 'test_confirmed': 'yes', 'test_preview': digest}
    # Two approval attempts must claim once. Delivery remains a separate worker.
    barrier = Barrier(2)
    # Patch globally once; avoid overlapping patch restorations between threads.
    with patch.object(commands, 'session', return_value=admin):
        def approve_race(_):
            barrier.wait()
            try:
                asyncio.run(commands.send_broadcast(bid, request(approved), BackgroundTasks()))
                return True
            except HTTPException as exc:
                assert exc.status_code == 409
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(approve_race, range(2))) == [False, True]
    barrier = Barrier(2)
    def deliver_once(_):
        barrier.wait()
        asyncio.run(commands.deliver_driver_broadcast(bid))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(deliver_once, range(2)))
    recipients = rows("SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=? AND status<>'excluded' ORDER BY id", (bid,))
    assert len(providers.sent_to_drivers(ref)) == len(recipients)
    assert all(x['status'] == 'sent' and x['provider_message_id'] for x in recipients)
    assert all(DISCLAIMER in x[1] for x in providers.sent_to_drivers(ref))
    assert not workflow.accept_driver_reply(recipients[0]['phone'], 'موافق ' + ref)

    # Test acceptance is distinct from a booking or an operational assignment.
    reply = 'موافق ' + display_reference(ref, True)
    with patch.dict('os.environ', {'WHATSAPP_COMMAND_OWNER': recipients[0]['phone'], 'AFAQ_TEAM': '[]'}):
        inbound('test-admin-not-driver', recipients[0]['phone'], reply)
    assert one('SELECT status FROM driver_broadcasts WHERE id=?', (bid,))['status'] == 'awaiting_driver'
    inbound('test-driver-accept', recipients[0]['phone'], reply)
    assert inbound('test-driver-accept', recipients[0]['phone'], reply)['duplicate']
    assert 'لم يتم تعيينك' in providers.replies['test-driver-accept']['message']
    assert not workflow.accept_driver_reply(recipients[1]['phone'], reply)
    assert one('SELECT status,revenue,cost FROM shipments WHERE id=?', (sid,)) == {
        'status': 'test_completed', 'revenue': 0, 'cost': 0}
    operation = one('SELECT stage,driver_name,driver_phone FROM shipment_operations WHERE shipment_id=?', (sid,))
    assert operation == {'stage': 'test_completed', 'driver_name': None, 'driver_phone': None}
    assert rows("SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=? AND status='excluded' ORDER BY id", (bid,)) == exclusions
    # Missing provider receipts never count as sent and cannot authorize acceptance.
    other = _save(NaqliatLoad(**{**payload, 'description': 'CI disclosed missing receipt'}, capture_method='manual_test'))
    other_item = one('SELECT * FROM shipments WHERE id=?', (other[2],))
    other_ref = other_item['reference']
    result = asyncio.run(workflow.advance_owner_whatsapp_reply(owner, terms(other_ref), shipment_id=other[2]))
    bid = result['broadcast_id']
    other_offer = one('SELECT * FROM driver_broadcasts WHERE id=?', (bid,))
    providers.driver_modes[other_ref] = 'no_receipt'
    approved = {**base, 'test_confirmed': 'yes', 'test_preview': test_broadcast_context(other_offer)['digest']}
    send(approved, deliver=True)
    uncertain = one('SELECT status,sent_count,failed_count FROM driver_broadcasts WHERE id=?', (bid,))
    assert uncertain['sent_count'] == 0 and uncertain['failed_count'] == len(recipients)
    assert uncertain['status'] == 'completed_with_errors'
    assert not workflow.accept_driver_reply(recipients[0]['phone'], 'موافق ' + display_reference(other_ref, True))
    assert rows('SELECT * FROM business_shipments ORDER BY id') == before_real
    assert len(providers.owner_calls) == before_owner_calls
    print('PASS: disclosed test preview/approval, owner/admin correlation, duplicate/racing send protection, non-business acceptance and KPI isolation.')
