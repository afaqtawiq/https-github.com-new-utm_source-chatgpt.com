"""Independent append-only recovery assertions inside the isolated PG harness.

Every provider interaction is synthetic. This file is invoked only by the
localhost-only, socket-guarded transport_postgres_acceptance fixture.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from decimal import Decimal
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi import BackgroundTasks, HTTPException


def run_recovery(providers, inbound):
    from app import broadcast_recovery as recovery, freight_workflow as workflow
    from app import command_assistant as commands, zernio_whatsapp as transport
    from app.bootstrap import app
    from app.driver_offer import offer_message
    from app.storage import db, one, rows, execute, utcnow, create_session
    from app.transport_test import display_reference, preview_digest
    from fastapi.testclient import TestClient

    uid = one("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")['id']
    admin = {'user_id': uid, 'role': 'admin', 'csrf': 'recovery-csrf'}
    account = transport.account_id()
    serial = 8100
    cases, messages, posts = {}, {}, []
    send_modes, sent_lock = {}, Lock()

    def request(data):
        async def body(): return urlencode(data).encode()
        return SimpleNamespace(body=body)

    def fixture(states):
        nonlocal serial
        serial += 1
        ref = 'NQ-' + str(serial)
        now = utcnow()
        sid = execute('''INSERT INTO shipments(reference,service_type,origin,destination,status,is_test,revenue,cost,created_at,updated_at)
            VALUES(?,'freight','جدة','الشارقة','test_pending',TRUE,0,0,?,?)''', (ref,now,now))
        execute('''INSERT INTO freight_negotiations(shipment_id,record_kind,owner_phone,status,agreed_owner_price,driver_offer_price,weight_tons,payment_method,created_at,updated_at)
            VALUES(?,'shipment_request','+966509999998','owner_agreed',2000,1850,20,'محاكاة دون دفع',?,?)''',(sid,now,now))
        execute("INSERT INTO shipment_operations(shipment_id,stage,created_at,updated_at) VALUES(?,'test_pending',?,?)",(sid,now,now))
        body = offer_message({'reference':ref,'origin':'جدة','destination':'الشارقة','is_test':True,
            'agreed_owner_price':2000,'weight_tons':20,'payment_method':'محاكاة دون دفع'})
        bid = execute('''INSERT INTO driver_broadcasts(raw_command,message,status,recipient_count,shipment_id,is_test,created_by,created_at,updated_at,test_approved_by,test_approved_at)
            VALUES('CI recovery',?,'completed_with_errors',?,?,TRUE,?,?,?,?,?)''',
            (body,sum(s != 'excluded' for s in states),sid,uid,now,now,uid,now))
        recipients = []
        for i,state in enumerate(states):
            number = '+9665' + str(serial * 100 + i).zfill(8)
            did = execute('''INSERT INTO drivers(driver_name,whatsapp_phone,vehicle_type,offer_consent,created_at,updated_at)
                VALUES(?,?,'truck',1,?,?)''',('CI recovery '+str(i),number,now,now))
            status = {'legacy':'failed','preflight':'failed','uncertain':'uncertain','excluded':'excluded'}.get(state,'sent')
            mid = 'old-' + str(serial) + '-' + str(i) if status == 'sent' else None
            phase = 'preflight_failed' if state == 'preflight' else 'uncertain' if state == 'uncertain' else 'accepted' if mid else None
            error = recovery.LEGACY_PREFLIGHT_ERROR if state == 'legacy' else 'CI known preflight' if state == 'preflight' else None
            rid = execute('''INSERT INTO driver_broadcast_recipients(broadcast_id,driver_id,driver_name,phone,status,provider_message_id,sent_at,last_error,send_phase,post_attempted_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',(bid,did,'CI recovery '+str(i),number,status,mid,now if mid else None,error,phase,now if state=='uncertain' else None))
            cid = 'ci-recovery-' + str(rid)
            if mid:
                messages[mid] = {'id':mid,'direction':'outgoing','accountId':account,'platform':'whatsapp',
                    'conversationId':cid,'deliveryStatus':state,'deliveryError':{'code':131042} if state=='failed' else None}
            cases[number] = cid
            recipients.append({'id':rid,'driver_id':did,'phone':number,'state':state,'mid':mid,'cid':cid})
        eligible_audience = [r for r in recipients if r['state'] != 'excluded']
        execute('UPDATE driver_broadcasts SET test_preview_digest=? WHERE id=?',(preview_digest(body,eligible_audience),bid))
        return {'sid':sid,'bid':bid,'ref':ref,'body':body,'recipients':recipients}

    async def validated(client): return {'id':account,'platform':'whatsapp','isActive':True}
    async def fake_read(client,path,params=None):
        if path == '/inbox/conversations':
            return {'data':[{'id':cid,'accountId':account,'platform':'whatsapp','participantId':phone,'isGroup':False}
                            for phone,cid in cases.items()], 'pagination':{'hasMore':False}}
        if path.startswith('/inbox/conversations/') and path.endswith('/messages'):
            cid = path.split('/')[-2]
            return {'messages':[m for m in messages.values() if m['conversationId']==cid], 'pagination':{'hasMore':False}}
        raise AssertionError('Unexpected recovery read '+path)
    async def fake_send(phone,body):
        mode = send_modes.get(phone)
        if callable(mode): mode()
        guard = transport._dispatch_guard.get()
        assert guard is not None, 'Recovery bypassed final dispatch guard'
        await guard()
        with sent_lock:
            mid = 'new-recovery-' + str(len(posts)+1)
            posts.append((phone,body,mid))
        if mode == 'timeout': raise TimeoutError('simulated uncertain POST')
        cid = cases[phone]
        messages[mid] = {'id':mid,'direction':'outgoing','accountId':account,'platform':'whatsapp',
                         'conversationId':cid,'deliveryStatus':'delivered'}
        return {'messages':[{'id':mid}], 'conversation_id':cid}

    def prepare(case):
        with db() as c: campaign,recipients = recovery._source(c,case['bid'])
        data = {'csrf':admin['csrf'],'source_digest':recovery._fingerprint(campaign,recipients)}
        asyncio.run(recovery.prepare(case['bid'],request(data)))
        return one('SELECT * FROM driver_recovery_batches WHERE broadcast_id=?',(case['bid'],))
    def approve(case):
        batch = one('SELECT * FROM driver_recovery_batches WHERE broadcast_id=?',(case['bid'],))
        tasks = BackgroundTasks()
        asyncio.run(recovery.send_recovery(case['bid'],request({'csrf':admin['csrf'],'confirmed':'yes','preview_digest':batch['preview_digest']}),tasks))
        return batch
    def attempts(batch): return rows('SELECT * FROM driver_recovery_attempts WHERE batch_id=? ORDER BY id',(batch['id'],))
    def history(case): return rows('SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=? ORDER BY id',(case['bid'],))
    def expect_http(code,callback):
        try: callback()
        except HTTPException as exc: assert exc.status_code == code,(exc.status_code,exc.detail)
        else: raise AssertionError('Expected HTTP '+str(code))

    with ExitStack() as stack:
        stack.enter_context(patch.object(transport,'validate_account',validated))
        stack.enter_context(patch.object(transport,'read',fake_read))
        stack.enter_context(patch.object(transport,'send',fake_send))

        case = fixture(['legacy','preflight','failed','delivered','unknown','uncertain','excluded'])
        snapshot = history(case)
        # Exercise actual middleware before direct concurrency tests.
        session_id, csrf, _ = create_session(uid)
        web = TestClient(app,base_url='http://testserver',follow_redirects=False)
        web.cookies.set('gla_session',session_id)
        web.headers['origin']='http://testserver'
        page = web.get(f"/commands/broadcast/{case['bid']}/recovery")
        assert page.status_code == 200 and '25' in page.text and case['body'] in page.text
        with db() as c: campaign,recs = recovery._source(c,case['bid'])
        form = {'csrf':csrf,'source_digest':recovery._fingerprint(campaign,recs)}
        path = f"/commands/broadcast/{case['bid']}/recovery/prepare"
        assert web.post(path,data=form).status_code == 428
        with patch('app.bootstrap.mfa_state',return_value={'mfa_enabled':1}),patch('app.bootstrap.recent_stepup',return_value=True):
            assert web.post(path,data={**form,'csrf':'bad'}).status_code == 403
            assert web.post(path,data={**form,'source_digest':'stale'}).status_code == 409
            assert web.post(path,data=form).status_code == 303
        web.close()
        assert not posts and history(case)==snapshot

        stack.enter_context(patch.object(commands,'session',return_value=admin))
        batch = one('SELECT * FROM driver_recovery_batches WHERE broadcast_id=?',(case['bid'],))
        assert {a['recipient_id'] for a in attempts(batch)} == {r['id'] for r in case['recipients'][:3]}
        assert batch['budget_sar'] == Decimal('25.00') and batch['reserved_sar'] <= Decimal('25.00')
        assert prepare(case)['id']==batch['id']
        assert len(attempts(batch))==3
        barrier = Barrier(2)
        def approve_once(_):
            barrier.wait()
            try: approve(case); return 303
            except HTTPException as exc: return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool: assert sorted(pool.map(approve_once,range(2))) == [303,409]
        barrier = Barrier(2)
        def deliver_once(_): barrier.wait(); asyncio.run(recovery.deliver(batch['id']))
        with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(deliver_once,range(2)))
        assert len(posts)==3,(posts,attempts(batch))
        assert all(a['status']=='accepted' and a['provider_message_id'] and a['post_attempted_at'] for a in attempts(batch))
        assert all(body==case['body'] for _,body,_ in posts)
        assert history(case)==snapshot
        asyncio.run(recovery.deliver(batch['id']))
        expect_http(409,lambda:approve(case))
        assert len(posts)==3
        # Reconciliation appends facts without rewriting either set of receipts.
        asyncio.run(recovery.reconcile(case['bid'],request({'csrf':admin['csrf']})))
        asyncio.run(recovery.reconcile(case['bid'],request({'csrf':admin['csrf']})))
        assert one('SELECT COUNT(*) n FROM driver_recovery_receipts r JOIN driver_recovery_attempts a ON a.id=r.attempt_id WHERE a.batch_id=?',(batch['id'],))['n']==6
        assert history(case)==snapshot
        print('PASS: recovery role/CSRF/MFA, explicit current failures only, original rows immutable, duplicate approval/worker claims and append-only receipt reconciliation.')

        reply = 'موافق '+display_reference(case['ref'],True)
        first = case['recipients'][0]
        assert not workflow.accept_driver_reply(first['phone'],'موافق '+case['ref'])
        assert not workflow.accept_driver_reply('+966599999999',reply)
        with patch.dict('os.environ',{'WHATSAPP_COMMAND_OWNER':first['phone'],'AFAQ_TEAM':'[]'}):
            inbound('recovery-admin-not-driver',first['phone'],reply)
        assert one('SELECT status FROM driver_broadcasts WHERE id=?',(case['bid'],))['status']=='completed_with_errors'
        inbound('recovery-first-driver',first['phone'],reply)
        assert inbound('recovery-first-driver',first['phone'],reply)['duplicate']
        assert 'لم يتم تعيينك' in providers.replies['recovery-first-driver']['message']
        assert not workflow.accept_driver_reply(case['recipients'][1]['phone'],reply)
        assert one('SELECT status,revenue,cost FROM shipments WHERE id=?',(case['sid'],))=={'status':'test_completed','revenue':0,'cost':0}
        assert one('SELECT stage,driver_name,driver_phone FROM shipment_operations WHERE shipment_id=?',(case['sid'],))=={'stage':'test_completed','driver_name':None,'driver_phone':None}
        assert not one('SELECT id FROM business_shipments WHERE id=?',(case['sid'],))
        assert history(case)==snapshot
        asyncio.run(recovery.deliver(batch['id']))
        assert len(posts)==3
        print('PASS: signed first disclosed reply via retry receipt completes TEST only; admin/unknown/undisclosed/replayed replies cannot assign operations or revenue.')

        # A prepare race creates one batch; direct invocation cannot skip approval.
        unapproved = fixture(['legacy'])
        barrier=Barrier(2)
        def prepare_once(_): barrier.wait(); return prepare(unapproved)['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            prepared_ids=list(pool.map(prepare_once,range(2)))
        assert prepared_ids[0]==prepared_ids[1]
        ab=one('SELECT * FROM driver_recovery_batches WHERE id=?',(prepared_ids[0],))
        before=len(posts)
        asyncio.run(recovery.deliver(ab['id']))
        assert len(posts)==before and attempts(ab)[0]['status']=='pending'
        with patch.object(commands,'session',return_value={**admin,'role':'transport'}):
            expect_http(403,lambda:approve(unapproved))
        approve(unapproved)
        with patch.dict('os.environ',{'ENABLE_EXTERNAL_ACTIONS':'0'}):
            asyncio.run(recovery.deliver(ab['id']))
        assert len(posts)==before and attempts(ab)[0]['post_attempted_at'] is None

        # A stored receipt cannot authorize a reply through a changed account.
        moved=fixture(['legacy'])
        mb=prepare(moved);approve(moved);asyncio.run(recovery.deliver(mb['id']))
        with patch.dict('os.environ',{'ZERNIO_WHATSAPP_ACCOUNT_ID':'other-account'}):
            assert not workflow.accept_driver_reply(moved['recipients'][0]['phone'],'موافق '+display_reference(moved['ref'],True))
        assert one('SELECT status FROM shipments WHERE id=?',(moved['sid'],))['status']=='test_pending'
        print('PASS: racing preparation stays single-flight; direct worker, nonadmin, kill-switch, and changed-account reply paths cannot bypass approval.')

        # A current provider status change after prepare must block at the final boundary.
        changed = fixture(['failed'])
        cb = prepare(changed); approve(changed)
        source = changed['recipients'][0]
        send_modes[source['phone']] = lambda: messages[source['mid']].update(deliveryStatus='delivered')
        before = len(posts); old = history(changed)
        asyncio.run(recovery.deliver(cb['id']))
        assert len(posts)==before and attempts(cb)[0]['post_attempted_at'] is None
        assert history(changed)==old

        uncertain = fixture(['legacy'])
        ub=prepare(uncertain);approve(uncertain)
        send_modes[uncertain['recipients'][0]['phone']] = 'timeout'
        before=len(posts)
        asyncio.run(recovery.deliver(ub['id']))
        assert len(posts)==before+1 and attempts(ub)[0]['status']=='uncertain'
        asyncio.run(recovery.deliver(ub['id']))
        assert len(posts)==before+1
        assert not workflow.accept_driver_reply(uncertain['recipients'][0]['phone'],'موافق '+display_reference(uncertain['ref'],True))
        print('PASS: changed delivery proof stops before POST; uncertain retry consumes its unique attempt and never authorizes a reply or automatic replay.')

        # Every source field that proves preflight safety must invalidate approval.
        stale = fixture(['preflight'])
        sb=prepare(stale);approve(stale)
        execute('UPDATE driver_broadcast_recipients SET provider_response_status=200 WHERE id=?',(stale['recipients'][0]['id'],))
        before=len(posts)
        asyncio.run(recovery.deliver(sb['id']))
        assert len(posts)==before,'Source response change was not included in stale-proof protection'

        # Conservatively account for possible charges from original POSTs too.
        costly = fixture(['failed']*81)
        expect_http(409,lambda:prepare(costly))
        assert not one('SELECT id FROM driver_recovery_batches WHERE broadcast_id=?',(costly['bid'],))

        # Mid-flight TEST completion blocks the next dispatch even after preflight starts.
        finish=fixture(['legacy','legacy'])
        fb=prepare(finish);approve(finish)
        first,second=finish['recipients']
        send_modes[second['phone']]=lambda: workflow.accept_driver_reply(first['phone'],'موافق '+display_reference(finish['ref'],True))
        before=len(posts);old=history(finish)
        asyncio.run(recovery.deliver(fb['id']))
        assert len(posts)==before+1 and history(finish)==old
        assert one('SELECT status FROM driver_recovery_batches WHERE id=?',(fb['id'],))['status']=='test_completed'
        assert one('SELECT status FROM shipments WHERE id=?',(finish['sid'],))['status']=='test_completed'
        print('PASS: source-proof changes, original-plus-retry 25 SAR ceiling, and TEST-completed final-boundary stop all fail closed.')
