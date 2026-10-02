"""Signed TEST reply-context regressions in the disposable PostgreSQL fixture.

Called by transport_postgres_acceptance.py under mocked HTTP and a localhost-only
socket guard. Fixtures and receipts are synthetic; this suite never sends live.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import time
from threading import Barrier, Event, Lock, local
from unittest.mock import patch


def run_driver_test_context(providers, inbound):
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app.driver_offer import offer_message
    from app.storage import db, execute, one, rows
    from app.transport_test import DISCLAIMER, display_reference, preview_digest

    account = os.environ['ZERNIO_WHATSAPP_ACCOUNT_ID']
    uid = one("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")['id']
    serial = 9200
    web = TestClient(app, base_url='http://testserver')

    def fixture(*, phones=None, bound=True, is_test=True, status='sent',
                retry=None, hours=0, receipt=True, sender_account=None):
        nonlocal serial
        serial += 1
        ref = 'NQ-' + str(serial)
        now = datetime.now(timezone.utc)
        sent = now - timedelta(hours=hours)
        phones = phones or ['+9665' + str(serial * 10).zfill(8)]
        sid = execute('''INSERT INTO shipments(reference,service_type,origin,destination,status,is_test,revenue,cost,created_at,updated_at)
            VALUES(?,'freight','جدة','الشارقة',?,?,0,0,?,?)''',
            (ref,'test_pending' if is_test else 'new',is_test,now,now))
        execute('''INSERT INTO freight_negotiations(shipment_id,record_kind,owner_phone,status,agreed_owner_price,driver_offer_price,weight_tons,payment_method,created_at,updated_at)
            VALUES(?,'shipment_request',?,'owner_agreed',2000,1850,20,'محاكاة دون دفع',?,?)''',
            (sid,'+96657' + str(serial).zfill(7),now,now))
        execute("INSERT INTO shipment_operations(shipment_id,stage,created_at,updated_at) VALUES(?,?,?,?)",
                (sid,'test_pending' if is_test else 'new',now,now))
        body = offer_message(one('''SELECT s.*,n.agreed_owner_price,n.weight_tons,n.payment_method,
            n.unloading_location,n.loading_port_status FROM shipments s
            JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?''',(sid,)))
        bid = execute('''INSERT INTO driver_broadcasts(raw_command,message,status,recipient_count,shipment_id,is_test,
            created_by,created_at,updated_at,test_approved_by,test_approved_at)
            VALUES('CI TEST reply context',?,'awaiting_driver',?,?,?,?,?,?,?,?)''',
            (body,len(phones),sid,is_test,uid,now,now,uid if is_test else None,now if is_test else None))
        recs = []
        for index, phone in enumerate(phones):
            driver = one('SELECT id FROM drivers WHERE whatsapp_phone=?',(phone,))
            did = driver['id'] if driver else execute('''INSERT INTO drivers(driver_name,whatsapp_phone,vehicle_type,offer_consent,created_at,updated_at)
                VALUES(?,?,'truck',1,?,?)''',('CI context '+str(serial)+'-'+str(index),phone,now,now))
            mid = 'context-original-' + str(serial) + '-' + str(index) if receipt else None
            rid = execute('''INSERT INTO driver_broadcast_recipients(broadcast_id,driver_id,driver_name,phone,status,
                provider_message_id,sent_at,provider_account_id) VALUES(?,?,?,?,?,?,?,?)''',
                (bid,did,'CI context driver',phone,status,mid,sent if mid else None,
                 (sender_account or account) if bound else None))
            recs.append({'id':rid,'driver_id':did,'phone':phone,'mid':mid})
        execute('UPDATE driver_broadcasts SET test_preview_digest=? WHERE id=?',(preview_digest(body,recs),bid))
        batch = None
        if retry is not None:
            batch = execute('''INSERT INTO driver_recovery_batches(broadcast_id,account_id,message,source_digest,preview_digest,status,
                budget_sar,reserved_sar,prior_reserved_sar,created_by,created_at,approved_by,approved_at)
                VALUES(?,?,?,'context-source','context-preview','completed',25,0.30,0,?,?,?,?)''',
                (bid,sender_account or account,body,uid,now,uid,now))
            for index, rec in enumerate(recs):
                mid = 'context-retry-' + str(serial) + '-' + str(index) if receipt else None
                aid = execute('''INSERT INTO driver_recovery_attempts(batch_id,recipient_id,driver_id,phone,source_evidence,
                    status,provider_message_id,conversation_id,sent_at,post_attempted_at)
                    VALUES(?,?,?,?, '{}',?,?,?,?,?)''',
                    (batch,rec['id'],rec['driver_id'],rec['phone'],retry,mid,
                     'ci-context-'+rec['phone'].lstrip('+'),sent if mid else None,sent))
                rec.update(attempt_id=aid,retry_mid=mid)
        return {'sid':sid,'bid':bid,'ref':ref,'batch':batch,'recipients':recs,
                'phone':phones[0],'mid':recs[0].get('retry_mid',recs[0]['mid'])}

    def state(case):
        return {
            'shipment':one('SELECT * FROM shipments WHERE id=?',(case['sid'],)),
            'operation':one('SELECT * FROM shipment_operations WHERE shipment_id=?',(case['sid'],)),
            'negotiation':one('SELECT * FROM freight_negotiations WHERE shipment_id=?',(case['sid'],)),
            'broadcast':one('SELECT * FROM driver_broadcasts WHERE id=?',(case['bid'],)),
            'recipients':rows('SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=? ORDER BY id',(case['bid'],)),
            'attempts':rows('SELECT * FROM driver_recovery_attempts WHERE batch_id=? ORDER BY id',(case['batch'],)),
        }

    def counters():
        return (one('SELECT COUNT(*) n FROM shipments')['n'],
                one('SELECT COUNT(*) n FROM business_shipments')['n'],
                rows('SELECT * FROM zernio_requests ORDER BY id'),
                len(providers.owner_calls),len(providers.driver_calls))

    def send(event, case, text, *, quote=None, metadata=None, message_extra=None, **kwargs):
        event = 'driver-context-' + event
        metadata = metadata if metadata is not None else ({'quotedMessageId':quote} if quote is not None else None)
        conversation = kwargs.pop('conversation','ci-context-'+case['phone'].lstrip('+'))
        if message_extra is None:
            return inbound(event,case['phone'],text,conversation=conversation,metadata=metadata,**kwargs)
        assert not kwargs
        number = case['phone'].lstrip('+')
        payload = {'id':event,'event':'message.received',
            'account':{'accountId':account,'platform':'whatsapp'},
            'conversation':{'id':conversation,'participantId':number,'isGroup':False},
            'message':{'direction':'incoming','text':text,'isGroup':False,
                       'sender':{'phoneNumber':number,'id':number},**message_extra}}
        if metadata is not None: payload['metadata']=metadata
        raw = json.dumps(payload,ensure_ascii=False).encode()
        digest = hmac.new(os.environ['ZERNIO_WEBHOOK_SECRET'].encode(),raw,hashlib.sha256).hexdigest()
        result = web.post('/webhooks/zernio',content=raw,headers={'x-zernio-signature':digest,'content-type':'application/json'})
        assert result.status_code == 200,result.text
        return result.json()

    def test_notice(event,case,text,**kwargs):
        before,counts = state(case),counters()
        events = rows("SELECT * FROM shipment_events WHERE shipment_id=? AND event_type='driver_test_reply' ORDER BY id",(case['sid'],))
        result = send(event,case,text,**kwargs)
        assert result['agent']=='afaaq' and result['state']=='sent',result
        reply = providers.replies['driver-context-'+event]['message']
        assert DISCLAIMER in reply and 'دفع' in reply,reply
        assert 'تم تسجيل نجاح' not in reply and 'تم تسجيل موافقتك' not in reply,reply
        assert 'لم يُسجّل' in reply or 'لم أسجل' in reply,reply
        assert state(case)==before,(event,state(case),before)
        assert counters()==counts,event
        logged = rows("SELECT * FROM shipment_events WHERE shipment_id=? AND event_type='driver_test_reply' ORDER BY id",(case['sid'],))
        assert len(logged)==len(events)+1,(event,logged)
        summary = json.loads(logged[-1]['summary'])
        assert summary['event_id']=='driver-context-'+event and summary['accepted'] is False
        return reply

    def not_selected(event,case,text,*,ambiguous=False,**kwargs):
        before = state(case)
        count = one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='driver_test_reply'",(case['sid'],))['n']
        result = send(event,case,text,**kwargs)
        assert state(case)==before,event
        assert one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='driver_test_reply'",(case['sid'],))['n']==count,event
        reply = providers.replies.get('driver-context-'+event,{}).get('message','')
        assert 'تم تسجيل نجاح رد الاختبار' not in reply,event
        if ambiguous:
            assert 'لم أستطع تحديد العرض' in reply,(event,result,reply)
        return result,reply

    # The real worker persists account evidence from a successful Zernio
    # response only. It must not substitute the currently configured account.
    from app import command_assistant as commands, zernio_whatsapp as transport
    for index,(provider,returned_account,expected) in enumerate([
            ('zernio',account,account),('zernio',None,None),('ci-other',account,None)]):
        sent_case = fixture(bound=False,status='pending',receipt=False)
        execute("UPDATE driver_broadcasts SET status='sending' WHERE id=?",(sent_case['bid'],))
        sent_calls=[]
        async def original_send(phone,message):
            guard=transport._dispatch_guard.get()
            assert guard is not None
            guard()
            sent_calls.append((phone,message))
            return {'provider':provider,'account_id':returned_account,
                    'messages':[{'id':'context-worker-'+str(index)}],'http_status':200}
        with patch.object(commands,'send_text_message',original_send):
            asyncio.run(commands.deliver_driver_broadcast(sent_case['bid']))
        recipient=one('SELECT * FROM driver_broadcast_recipients WHERE id=?',(sent_case['recipients'][0]['id'],))
        assert len(sent_calls)==1 and recipient['status']=='sent',recipient
        assert recipient['provider_account_id']==expected,recipient
        if expected:
            test_notice('captured-original-binding',sent_case,'طيب')
        else:
            not_selected('worker-no-binding-'+str(index),sent_case,'طيب')
    print('PASS: original worker retains only actual Zernio receipt account evidence; missing/non-Zernio responses never fabricate a fallback binding.')

    # A strong quote identifies the original TEST even with a previous Afaaq
    # selection. Generic intake must not create or update any AF request.
    original = fixture()
    with db() as c:
        c.execute("INSERT INTO zernio_conversation_agents(conversation_id,agent) VALUES(%s,'afaaq')",
                  ('ci-context-'+original['phone'].lstrip('+'),))
    test_notice('quoted-price',original,'السعر ضعيف وما يناسب المشوار',quote=original['mid'])
    test_notice('platform-quote',original,'كم السعر؟',metadata={
        'quotedMessageId':'other-perspective','quotedMessage':{'messageId':'internal-id','platformMessageId':original['mid']}})
    test_notice('explicit-reference',original,'السعر غير مناسب '+original['ref'])
    test_notice('short-unique',original,'طيب')
    test_notice('vague-acceptance',original,'موافق')
    test_notice('voice-unique',original,'',message_extra={'attachments':[{
        'type':'audio','url':'https://invalid.example/never-fetch.ogg'}]})
    test_notice('image-quote',original,None,quote=original['mid'],message_extra={'attachments':[{
        'type':'image','url':'https://invalid.example/never-fetch.jpg'}]})
    test_notice('greeting-unique',original,'السلام عليكم')
    snapshot,calls=state(original),len(providers.replies)
    assert send('quoted-price',original,'السعر ضعيف وما يناسب المشوار',quote=original['mid'])['duplicate']
    assert state(original)==snapshot and len(providers.replies)==calls
    # An already-claimed historical event is not reprocessed after the fix.
    with db() as c:
        c.execute("INSERT INTO zernio_reply_events(event_id,conversation_id,state) VALUES(%s,'ci-old-event','sent')",('driver-context-historical',))
    assert send('historical',original,'موافق '+display_reference(original['ref'],True))['duplicate']
    assert state(original)==snapshot
    print('PASS: quoted objections, short/voice/media/greeting TEST replies remain disclosed; no acceptance, media fetch, AF record, or duplicate/historical replay.')

    legacy = fixture(bound=False)
    test_notice('legacy-quote',legacy,'سعر قليل',quote=legacy['mid'])
    test_notice('legacy-reference',legacy,'سعر قليل '+legacy['ref'])
    not_selected('legacy-no-binding',legacy,'طيب')
    stale = fixture(hours=25)
    not_selected('stale-fallback',stale,'طيب')
    test_notice('stale-strong-quote',stale,'طيب',quote=stale['mid'])
    for event,kwargs in [('wrong-account',{'account':'not-current-account'}),
                         ('group',{'conversation_group':True}),('message-group',{'message_group':True}),
                         ('participant-mismatch',{'participant':'966599999997'}),
                         ('sender-mismatch',{'sender_id':'966599999997'}),
                         ('missing-direction',{'direction':None}),('outbound',{'direction':'outgoing'}),
                         ('unsigned',{'signature':False})]:
        not_selected(event,original,'موافق '+display_reference(original['ref'],True),quote=original['mid'],**kwargs)
    for mode in ('failed','uncertain','excluded'):
        rejected = fixture(status=mode)
        not_selected('original-'+mode,rejected,'السعر؟',quote=rejected['mid'])
    missing = fixture(receipt=False)
    not_selected('missing-receipt',missing,'طيب '+missing['ref'])
    changed = fixture(sender_account='old-account')
    not_selected('changed-original-account',changed,'موافق '+display_reference(changed['ref'],True),quote=changed['mid'])
    print('PASS: original legacy/stale strong evidence works; unsigned, wrong-account, group, mismatched identity, failed/uncertain/excluded/missing receipts cannot select or accept TEST.')

    retry = fixture(status='failed',retry='accepted')
    test_notice('retry-quote',retry,'السعر قليل',quote=retry['mid'])
    test_notice('retry-reference',retry,'السعر قليل '+retry['ref'])
    test_notice('retry-short',retry,'تمام')
    not_selected('superseded-original',retry,'السعر قليل',quote=retry['recipients'][0]['mid'],ambiguous=True)
    for terminal in ('failed','deleted'):
        case = fixture(status='failed',retry='accepted')
        execute('''INSERT INTO driver_recovery_receipts(attempt_id,provider_message_id,delivery_status,checked_at)
            VALUES(?,?,?,NOW())''',(case['recipients'][0]['attempt_id'],case['mid'],terminal))
        not_selected('retry-'+terminal,case,'موافق '+display_reference(case['ref'],True),quote=case['mid'])
    for mode in ('uncertain','pending','closed'):
        case = fixture(status='failed',retry=mode)
        not_selected('retry-'+mode,case,'طيب',quote=case['mid'])
    case = fixture(status='failed',retry='accepted',sender_account='old-account')
    not_selected('retry-wrong-binding',case,'طيب',quote=case['mid'])
    print('PASS: accepted linked retry receipts retain TEST context; superseded original, failed/deleted/uncertain/pending/closed retries and changed sender binding fail closed.')

    older = fixture()
    newer = fixture(phones=[older['phone']])
    not_selected('two-tests-unquoted',older,'طيب',ambiguous=True)
    test_notice('older-quote-not-latest',older,'قليل',quote=older['mid'])
    test_notice('older-reference-not-latest',older,'قليل '+older['ref'])
    for event,text,quote in [('unknown-quote','قليل','not-a-receipt'),
                              ('malformed-quote','قليل',''),
                              ('conflict-quote-reference','قليل '+newer['ref'],older['mid']),
                              ('multi-reference','قليل '+older['ref']+' '+newer['ref'],None),
                              ('acceptance-conflict','موافق '+display_reference(newer['ref'],True),older['mid'])]:
        not_selected(event,newer,text,quote=quote,ambiguous=True)
    real = fixture(phones=[original['phone']],is_test=False)
    not_selected('real-conflict-unquoted',original,'طيب',ambiguous=True)
    test_notice('strong-test-over-real',original,'قليل',quote=original['mid'])
    result,_=not_selected('explicit-real-acceptance',original,'موافق '+real['ref'])
    assert result['agent']=='afaaq'
    assert one('SELECT status FROM shipments WHERE id=?',(real['sid'],))['status']=='driver_assigned'
    old_real_test = fixture()
    fixture(phones=[old_real_test['phone']],is_test=False,hours=25)
    not_selected('older-active-real-conflict',old_real_test,'طيب',ambiguous=True)
    print('PASS: conflicting/unknown/multiple identifiers and concurrent real/TEST contexts never choose newest; explicit real acceptance keeps its original behavior.')

    # A phone can be a TEST recipient and a real shipment owner. The existing
    # owner's strong quote/reference and unique pending flow must still work.
    owner_case = fixture()
    owner_sid = execute('''INSERT INTO shipments(reference,service_type,origin,destination,status,created_at,updated_at)
        VALUES('WA-000000009999','freight','الرياض','جدة','new',NOW(),NOW())''')
    execute('''INSERT INTO freight_negotiations(shipment_id,record_kind,owner_phone,status,contact_channel,
        provider_message_id,created_at,updated_at) VALUES(?,'shipment_request',?,'awaiting_owner','whatsapp','context-owner-inquiry',NOW(),NOW())''',
        (owner_sid,owner_case['phone']))
    owner_before=one('SELECT * FROM freight_negotiations WHERE shipment_id=?',(owner_sid,))
    not_selected('owner-unquoted',owner_case,'السعر: 2100',ambiguous=True)
    assert one('SELECT * FROM freight_negotiations WHERE shipment_id=?',(owner_sid,))==owner_before
    for event,text,kwargs in [('owner-price-quoted','السعر: 2100',{'quote':'context-owner-inquiry'}),
                              ('owner-quoted','الوزن: 21 طن',{'quote':'context-owner-inquiry'}),
                              ('owner-reference','WA-000000009999\nالتحميل من خارج الميناء',{})]:
        not_selected(event,owner_case,text,**kwargs)
    saved = one('SELECT asking_price,weight_tons,loading_port_status FROM freight_negotiations WHERE shipment_id=?',(owner_sid,))
    assert saved['asking_price']==2100 and saved['weight_tons']==21 and saved['loading_port_status']=='outside',saved
    with patch.dict(os.environ,{'WHATSAPP_COMMAND_OWNER':owner_case['phone'],'AFAQ_TEAM':'[]'}):
        result,_=not_selected('admin-not-driver',owner_case,'آفاق حالة الشحنة '+owner_case['ref'])
        assert result['agent']=='owner',result
    normal = fixture()
    count = one('SELECT COUNT(*) n FROM shipments')['n']
    before=state(normal)
    result = send('explicit-new-real-request',normal,'طلب نقل\nمن الرياض إلى جدة\nجوال صاحب الشحنة: +966599999994')
    assert result['agent']=='afaaq' and one('SELECT COUNT(*) n FROM shipments')['n']==count+1
    assert state(normal)==before
    assert one('SELECT is_test FROM shipments ORDER BY id DESC LIMIT 1')['is_test'] is False
    for event,text in [('explicit-menu','القائمة'),('explicit-route','شواهد')]:
        not_selected(event,normal,text)
    print('PASS: owner/TEST overlap fails closed; strong real owner quote/reference, administrator commands, explicit new real requests and menu routing are preserved.')

    # Competing exact disclosed acceptances still produce only one TEST winner.
    winner = fixture(phones=['+966591999991','+966591999992'],status='failed',retry='accepted')
    before_recipients=state(winner)['recipients']
    counts=counters()
    barrier=Barrier(2)
    def accept(index):
        case={**winner,'phone':winner['recipients'][index]['phone'],'mid':winner['recipients'][index]['retry_mid']}
        barrier.wait()
        send('race-'+str(index),case,'موافق '+display_reference(winner['ref'],True),quote=case['mid'])
    with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(accept,range(2)))
    replies=[providers.replies['driver-context-race-'+str(index)]['message'] for index in range(2)]
    assert sum('تم تسجيل نجاح رد الاختبار' in reply for reply in replies)==1,replies
    broadcast=one('SELECT * FROM driver_broadcasts WHERE id=?',(winner['bid'],))
    assert broadcast['status']=='test_completed' and broadcast['accepted_driver_id'] in [r['driver_id'] for r in winner['recipients']]
    assert one('SELECT status,revenue,cost FROM shipments WHERE id=?',(winner['sid'],))=={'status':'test_completed','revenue':0,'cost':0}
    assert one('SELECT stage,driver_name,driver_phone FROM shipment_operations WHERE shipment_id=?',(winner['sid'],))=={
        'stage':'test_completed','driver_name':None,'driver_phone':None}
    assert state(winner)['recipients']==before_recipients and counters()==counts
    test_notice('completed-short',winner,'طيب')
    test_notice('completed-voice',winner,'',quote=winner['mid'],message_extra={'attachments':[{'type':'audio'}]})
    test_notice('completed-exact-repeat',winner,'موافق '+display_reference(winner['ref'],True),quote=winner['mid'])
    assert one('SELECT accepted_driver_id FROM driver_broadcasts WHERE id=?',(winner['bid'],))['accepted_driver_id']==broadcast['accepted_driver_id']
    # Force the earlier owner-inquiry deadlock ordering: a duplicate start
    # queues for the shipment row before the first send records its receipt.
    # Both transactions must acquire shipment before negotiation; a receipt
    # transaction must never hold negotiation while waiting for the shipment FK.
    from fastapi import HTTPException
    from app import freight_workflow as workflow
    from app.transport_test import owner_inquiry_digest
    inquiry = fixture(status='pending',receipt=False)
    execute("UPDATE freight_negotiations SET status='awaiting_owner' WHERE shipment_id=?",(inquiry['sid'],))
    item=one('''SELECT s.*,n.owner_phone FROM shipments s JOIN freight_negotiations n
        ON n.shipment_id=s.id WHERE s.id=?''',(inquiry['sid'],))
    preview=owner_inquiry_digest(item)
    provider_ready,release_provider=Event(),Event()
    duplicate_open,finalization_open=Event(),Event()
    roles=local()
    observations,transactions,sends={},{},[]
    observed_lock=Lock()
    actual_db=workflow.db

    @contextmanager
    def observed_db():
        with actual_db() as connection:
            role=getattr(roles,'role','other')
            with observed_lock:
                transactions[role]=transactions.get(role,0)+1
                if role=='duplicate':
                    observations['duplicate']=connection.info.backend_pid
                    duplicate_open.set()
                elif role=='first' and transactions[role]==2:
                    observations['finalization']=connection.info.backend_pid
                    finalization_open.set()
            yield connection

    async def held_owner_send(phone,message):
        sends.append((phone,message))
        provider_ready.set()
        assert release_provider.wait(8),'Receipt release timed out'
        return {'provider':'ci-fake','messages':[{'id':'context-owner-lock-receipt'}]}

    def inquiry_start(role):
        roles.role=role
        try:
            return asyncio.run(workflow.send_test_owner_inquiry(inquiry['sid'],uid,preview))
        except HTTPException as exc:
            return exc.status_code

    def waiting_on_lock(pid):
        until=time.monotonic()+8
        while time.monotonic()<until:
            row=one('SELECT wait_event_type FROM pg_stat_activity WHERE pid=?',(pid,))
            if row and row['wait_event_type']=='Lock':
                return
            time.sleep(0.01)
        raise AssertionError('Expected transaction was not queued on its row lock')

    with patch.object(workflow,'db',observed_db),patch.object(workflow,'send_text_message',held_owner_send):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(inquiry_start,'first')
            assert provider_ready.wait(8),'Owner send did not begin'
            try:
                with db() as held:
                    held.execute('SELECT id FROM shipments WHERE id=%s FOR UPDATE',(inquiry['sid'],))
                    duplicate=pool.submit(inquiry_start,'duplicate')
                    assert duplicate_open.wait(8)
                    waiting_on_lock(observations['duplicate'])
                    release_provider.set()
                    assert finalization_open.wait(8)
                    waiting_on_lock(observations['finalization'])
                assert first.result(timeout=8)=='context-owner-lock-receipt'
                assert duplicate.result(timeout=8)==409
            finally:
                release_provider.set()
    assert len(sends)==1 and sends[0][1].startswith(DISCLAIMER)
    assert one('SELECT test_owner_contact_status,provider_message_id FROM freight_negotiations WHERE shipment_id=?',(inquiry['sid'],))=={
        'test_owner_contact_status':'sent','provider_message_id':'context-owner-lock-receipt'}
    assert one("SELECT COUNT(*) n FROM shipment_events WHERE shipment_id=? AND event_type='test_owner_inquiry_submitted'",(inquiry['sid'],))['n']==1
    print('PASS: forced duplicate-start versus receipt-finalization ordering cannot deadlock; exactly one TEST owner send and durable receipt remain.')

    assert not providers.unexpected,providers.unexpected
    web.close()
    print('PASS: concurrent exact disclosed acceptance retains a single TEST-only winner; later text/media/exact repeats never assign work or invent another acceptance.')
