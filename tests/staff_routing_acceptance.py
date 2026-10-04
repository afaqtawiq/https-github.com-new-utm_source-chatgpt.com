"""Synthetic staff regression fixtures through the signed, real-PostgreSQL webhook.
No real employee names, phone numbers, tariff sheets or live model/provider calls.
"""
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch

STAFF = '+966500000091'
COLLEAGUE = '+966500000092'
MANAGER = '+966500000093'
EXTERNAL = '+966500000094'


def run_staff_routing(providers, inbound):
    from app import load_vision, team, manager_actions, command_ai
    from app.storage import db, one, execute
    from app.staff_intake import explicit_load, context_for_model
    fixtures = json.loads((Path(__file__).parent/'fixtures/staff_document_ocr.json').read_text())
    roster = [{'phone':'0500000091','name':'موظف النقل التجريبي','short':'موظف النقل','role':'transport','manager':False},
              {'phone':COLLEAGUE,'name':'زميل تجريبي','short':'الزميل','role':'customs','manager':False}]
    env = {'AFAQ_TEAM':json.dumps(roster), 'WHATSAPP_COMMAND_OWNER':MANAGER}
    attachments = [{'type':'image','mimeType':'image/jpeg','url':'https://example.invalid/synthetic.jpg'}]
    start_sends = (len(providers.owner_calls),len(providers.driver_calls))
    start_records = one('SELECT COUNT(*) n FROM shipments')['n']
    with patch.dict(os.environ,env), patch.object(load_vision,'fetch_image',return_value=(b'synthetic-image-bytes','image/jpeg')), \
         patch.object(load_vision,'_start_workflow',side_effect=AssertionError('Staff image started an external workflow')):
        assert team.phone('٠٥٠٠٠٠٠٠٩١') == STAFF[1:]
        assert team.phone('00966500000091') == STAFF[1:]
        assert not team.phone('staff 0500000091')
        assert not explicit_load('هل أسجل هذه الحمولة؟')
        assert not explicit_load('لا تسجل هذه الحمولة')
        assert not explicit_load('قال العميل: سجل هذه الحمولة')
        assert explicit_load('سجلي هذه الحمولة')
        with patch.object(load_vision,'extract',return_value=fixtures['rate_table']), \
             patch.object(load_vision,'save_load',side_effect=AssertionError('Tariff table became a shipment')):
            response = inbound('staff-01-image',STAFF,'',attachments=attachments)
            assert response['agent']=='owner'
            assert 'جدول أسعار النقل' in providers.replies['staff-01-image']['message']
            assert inbound('staff-01-image',STAFF,'',attachments=attachments)['duplicate']
            inbound('staff-02-caption-price',STAFF,'سجل هذه الحمولة',attachments=attachments)
        inbound('staff-03-correction',STAFF,'6200 الأخير دا الدمام دي الأسعار المعتمدة في آفاق طويق')
        answer = providers.replies['staff-03-correction']['message']
        assert 'الدمام' in answer and 'قطر' not in answer and 'صاحب الشحنة' not in answer
        inbound('staff-04-archive',STAFF,'راجعي الأرشيف')
        assert 'جدول الأسعار' in providers.replies['staff-04-archive']['message']
        assert 'لم أتحقق' in providers.replies['staff-04-archive']['message']
        assert one('SELECT COUNT(*) n FROM shipments')['n']==start_records
        assert one("SELECT COUNT(*) n FROM whatsapp_staff_context WHERE event_id='staff-01-image'")['n']==1
        # A colleague never sees the other employee's document context.
        inbound('staff-05-other-person',COLLEAGUE,'راجعي الأرشيف')
        assert 'جدول الأسعار' not in providers.replies['staff-05-other-person']['message']
        # Both unknown account and private-identity disagreement fail the staff boundary.
        for kwargs in ({'account':'other-account'}, {'participant':EXTERNAL}, {'sender_id':EXTERNAL},
                       {'conversation_group':True}, {'message_group':True}):
            payload = {'account':{'accountId':kwargs.get('account',os.environ['WHATSAPP_COMMAND_ACCOUNT_ID']),'platform':'whatsapp'},
                       'conversation':{'id':'x','participantId':kwargs.get('participant',STAFF),'isGroup':kwargs.get('conversation_group',False)},
                       'message':{'direction':'incoming','sender':{'phoneNumber':STAFF,'id':kwargs.get('sender_id',STAFF)},'isGroup':kwargs.get('message_group',False)}}
            assert team.identify(payload)==('',None)
        assert inbound('staff-bad-signature',STAFF,'أسعار النقل',signature=False)['error']=='Invalid webhook signature'
        # Explicit operations and price questions immediately after a tariff image
        # must not be swallowed by the prior numeric-correction shortcut.
        with patch.object(load_vision,'extract',return_value=fixtures['rate_table']):
            inbound('staff-05b-price-again',STAFF,'الدمام حسب الجدول المحلي',attachments=attachments)
        with patch.object(manager_actions,'_original_ask',return_value={'action':'question'}), \
             patch.object(command_ai,'answer_question',side_effect=lambda _: 'سياق داخلي: ' + context_for_model()) as answer_model:
            inbound('staff-05c-price-question',STAFF,'كم سعر الدمام؟')
            assert answer_model.call_count==1
            assert '6200' in providers.replies['staff-05c-price-question']['message']
            assert 'تعليق الموظف' in providers.replies['staff-05c-price-question']['message']
        inbound('staff-05d-canonical-add',STAFF,'آفاق أضف شحنة مرجع CI-STAFF-123 من الرياض إلى جدة')
        assert one("SELECT id FROM shipments WHERE reference='CI-STAFF-123'")
        with patch.object(load_vision,'extract',return_value=fixtures['rate_table']):
            inbound('staff-05e-price-again',STAFF,'',attachments=attachments)
        inbound('staff-05f-canonical-status',STAFF,'آفاق حالة الشحنة CI-STAFF-123')
        assert 'CI-STAFF-123' in providers.replies['staff-05f-canonical-status']['message']
        with patch.object(load_vision,'extract',return_value=fixtures['rate_table']):
            inbound('staff-05g-price-again',STAFF,'',attachments=attachments)
        inbound('staff-05h-request-after-price',STAFF,'طلب نقل\nمن جدة إلى الرياض\nجوال صاحب الشحنة: '+EXTERNAL)
        assert 'تم تسجيل طلب النقل' in providers.replies['staff-05h-request-after-price']['message']
        before_note=one("SELECT fields FROM zernio_requests WHERE conversation_id=? AND agent='afaaq'",('ci-transport-'+STAFF[1:],))['fields']
        with patch.object(manager_actions,'_original_ask',return_value={'action':'chat'}), \
             patch.object(command_ai,'answer_question',return_value='ملاحظة داخلية للمراجعة'):
            inbound('staff-05i-post-completion-note',STAFF,'الوزن: 30 طن')
        assert one("SELECT fields FROM zernio_requests WHERE conversation_id=? AND agent='afaaq'",('ci-transport-'+STAFF[1:],))['fields']==before_note
        # Staff + pending owner role collision must never update a freight agreement.
        with db() as c:
            sid=c.execute("""INSERT INTO shipments(reference,service_type,origin,destination,status,created_at,updated_at)
                VALUES('CI-STAFF-COLLISION','نقل','جدة','الرياض','new',NOW(),NOW()) RETURNING id""").fetchone()['id']
            c.execute("""INSERT INTO freight_negotiations(shipment_id,owner_phone,status,contact_channel,record_kind,created_at,updated_at)
                VALUES(%s,%s,'awaiting_owner','whatsapp','shipment_request',NOW(),NOW())""",(sid,STAFF))
        with patch.object(manager_actions,'_original_ask',return_value={'action':'chat'}), \
             patch.object(command_ai,'answer_question',return_value='وصلت ملاحظتك الداخلية للمراجعة.'):
            inbound('staff-06-owner-collision',STAFF,'CI-STAFF-COLLISION نعم متاحة')
        assert one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='owner_whatsapp_reply'",(sid,))['n']==0
        assert one('SELECT status FROM freight_negotiations WHERE shipment_id=?',(sid,))['status']=='awaiting_owner'
        # Image load needs its own current instruction and confident classification.
        with patch.object(load_vision,'extract',return_value=fixtures['single_load']), \
             patch.object(load_vision,'save_load',side_effect=AssertionError('Unrequested image registered')):
            inbound('staff-07-load-ambiguous',STAFF,'',attachments=attachments)
            assert 'هل تريد تسجيلها' in providers.replies['staff-07-load-ambiguous']['message']
            inbound('staff-08-load-negated',STAFF,'لا تسجل هذه الحمولة',attachments=attachments)
        for confidence in (None,False,float('nan'),float('inf'),-1,1.1,0.79,'0.99'):
            fields={**fixtures['single_load'],'confidence':confidence}
            assert not load_vision.verified_single_load(fields)
        for kind in ('rate_table','shipping_document','unknown',None):
            assert not load_vision.verified_single_load({**fixtures['single_load'],'document_kind':kind})
        assert not load_vision.verified_single_load([])
        with patch.object(load_vision,'extract',return_value=fixtures['single_load']), \
             patch.object(load_vision,'save_load',wraps=load_vision.save_load) as save:
            inbound('staff-09-load-explicit',STAFF,'سجل هذه الحمولة',attachments=attachments)
            inbound('staff-09-load-explicit',STAFF,'سجل هذه الحمولة',attachments=attachments)
            assert save.call_count==1
            assert 'لم أبدأ أي تواصل' in providers.replies['staff-09-load-explicit']['message']
            image_saved=one("SELECT n.id,s.id shipment_id,f.provider_message_id FROM naqliat_loads n JOIN shipments s ON s.reference=('NQ-'||n.id::text) JOIN freight_negotiations f ON f.shipment_id=s.id WHERE n.capture_method='whatsapp_image_ai' ORDER BY n.id DESC LIMIT 1")
            assert image_saved and image_saved['provider_message_id'] is None
            inbound('staff-09b-load-same-image',STAFF,'سجل هذه الحمولة',attachments=attachments)
            assert 'مسجلة سابقًا' in providers.replies['staff-09b-load-same-image']['message']
            assert one("SELECT COUNT(*) n FROM shipments WHERE reference=?",('NQ-'+str(image_saved['id']),))['n']==1
        # Explicit staff text still registers, without the receiver auto-advancing it.
        inbound('staff-10-text-load',STAFF,'طلب نقل\nمن الرياض إلى جدة\nجوال صاحب الشحنة: '+EXTERNAL+'\nالوزن: 20 طن')
        request=one("SELECT fields FROM zernio_requests WHERE conversation_id=? AND agent='afaaq'",('ci-transport-'+STAFF[1:],))
        reference=request['fields']['_last_transport_reference']
        assert one('SELECT n.status FROM freight_negotiations n JOIN shipments s ON s.id=n.shipment_id WHERE s.reference=?',(reference,))['status']=='contact_ready'
        inbound('staff-11-draft',STAFF,'طلب نقل من الرياض إلى جدة')
        inbound('staff-12-prices-during-draft',STAFF,'هذه أسعار النقل الداخلية 5100 ريال')
        request=one("SELECT fields FROM zernio_requests WHERE conversation_id=? AND agent='afaaq'",('ci-transport-'+STAFF[1:],))
        assert '_transport_draft' in request['fields']
        assert 'صاحب الشحنة' not in providers.replies['staff-12-prices-during-draft']['message']
        inbound('staff-13-cancel',STAFF,'إلغاء طلب النقل')
        request=one("SELECT fields FROM zernio_requests WHERE conversation_id=? AND agent='afaaq'",('ci-transport-'+STAFF[1:],))
        assert '_transport_draft' not in request['fields']
        before_note=request['fields']
        with patch.object(manager_actions,'_original_ask',return_value={'action':'chat'}), \
             patch.object(command_ai,'answer_question',return_value='ملاحظة داخلية للمراجعة'):
            inbound('staff-14-post-cancel-note',STAFF,'من الرياض إلى الدمام')
        assert one("SELECT fields FROM zernio_requests WHERE conversation_id=? AND agent='afaaq'",('ci-transport-'+STAFF[1:],))['fields']==before_note
        # A disclosed-test owner exception cannot swallow a fresh manager command
        # or send a real load by falling through the ordinary customer intake lane.
        with db() as c:
            test_sid=c.execute("""INSERT INTO shipments(reference,service_type,origin,destination,status,is_test,created_at,updated_at)
                VALUES('CI-STAFF-SIM','نقل','جدة','الرياض','test_pending',TRUE,NOW(),NOW()) RETURNING id""").fetchone()['id']
            c.execute("""INSERT INTO freight_negotiations(shipment_id,owner_phone,status,contact_channel,record_kind,
                test_owner_contact_status,provider_message_id,created_at,updated_at)
                VALUES(%s,%s,'awaiting_owner','whatsapp','shipment_request','sent','ci-test-inquiry',NOW(),NOW())""",(test_sid,MANAGER))
        inbound('staff-15-manager-test-new-real',MANAGER,'طلب نقل\nمن جدة إلى الرياض\nجوال صاحب الشحنة: '+EXTERNAL+'\nالدفع: محاكاة دون دفع')
        assert providers.replies['staff-15-manager-test-new-real']['message'].find('تم تسجيل طلب النقل')>=0
        with patch.object(manager_actions,'_original_ask',return_value={'action':'send_message','to':COLLEAGUE,'text':'الدفع: محاكاة دون دفع'}), \
             patch.object(manager_actions,'deliver',return_value={}) as sender:
            inbound('staff-16-manager-test-command',MANAGER,'أرسل رسالة إلى '+COLLEAGUE+': الدفع: محاكاة دون دفع')
            assert sender.call_count==1
        # Actual send boundary: non-manager retains team-to-team sends, but no external send.
        with db() as c, patch.object(manager_actions,'deliver',return_value={'messages':[{'id':'fake-internal'}]}) as delivery:
            token=team.ROLE.set(team.team()[STAFF[1:]])
            try:
                blocked=manager_actions.send_message(c,{'to':EXTERNAL,'text':'synthetic'})
                assert 'اعتماد المدير' in blocked and not delivery.called
                manager_actions.send_message(c,{'to':COLLEAGUE,'text':'synthetic internal'})
                assert delivery.call_count==1
            finally:
                team.ROLE.reset(token)
            token=team.ROLE.set(team.team()[MANAGER[1:]])
            try:
                manager_actions.send_message(c,{'to':EXTERNAL,'text':'synthetic manager request'})
                assert delivery.call_count==2
            finally:
                team.ROLE.reset(token)
        assert context_for_model()==''
        token=team.CONTEXT.set({'member':roster[0],'history':[{'command':'جدول أسعار محلي','reply':'وصل'}]})
        try:
            prompt=context_for_model()
            assert 'internal colleague' in prompt and 'جدول أسعار محلي' in prompt
        finally:
            team.CONTEXT.reset(token)
    assert (len(providers.owner_calls),len(providers.driver_calls))==start_sends
    print('PASS: signed staff-first routing, synthetic image OCR, context isolation, price corrections, role collisions, explicit registration, duplicate events and internal/external send boundaries. Live sends: 0.')
