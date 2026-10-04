"""Bounded brochure execution with local PostgreSQL and fake providers only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import os
from pathlib import Path
import secrets
import socket
import sys
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
url = os.environ['AFAAQ_TEST_DATABASE_URL']
assert urlsplit(url).hostname in {'localhost', '127.0.0.1'} and urlsplit(url).path == '/afaaq_test'
import psycopg
schema = 'brochure_test_' + secrets.token_hex(5)
with psycopg.connect(url, autocommit=True) as c:
    c.execute('CREATE SCHEMA ' + schema)
os.environ.update(DATABASE_URL=url+'?'+urlencode({'options':'-c search_path='+schema}, quote_via=quote),
    DISCOVERY_AUTO_ENABLED='0', ENABLE_EXTERNAL_ACTIONS='0', ADMIN_EMAIL='cadence@example.invalid',
    ADMIN_PASSWORD=secrets.token_urlsafe(24), BROWSER_COOKIE_SECURE='0')
from app.bootstrap import app
from app import customer_marketing as cm, campaign_cadence as cadence, spacemail
from app.storage import db, execute, one, rows, utcnow
from app.mail_delivery import MailConnectionFailed
from fastapi.testclient import TestClient

uid = one('SELECT id FROM users WHERE email=?', (os.environ['ADMIN_EMAIL'],))['id']
clock = [datetime(2070, 1, 1, 9, tzinfo=cm.RIYADH)]
seq = [0]
def now(): return clock[0]
def reset():
    with db() as c:
        c.execute('TRUNCATE customer_campaign_recipients,customer_campaign_channels,customer_campaigns,customer_campaign_replies,marketing_suppressions CASCADE')
        c.execute('DELETE FROM accounts')
        c.execute('DELETE FROM customer_directory')
        c.execute('DELETE FROM spacemail_inbox')
    clock[0] = datetime(2070, 1, 1, 9, tzinfo=cm.RIYADH)

def customer(email='fixture@example.com', phone=''):
    execute('INSERT INTO accounts(name,email,phone,status,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            ('Fixture', email, phone, 'lead', now(), now()))

def queued(recipient='fixture@example.com', channel='email', *, key=None, status='pending', sent_at=None, receipt=None):
    seq[0] += 1
    with db() as c:
        cid = c.execute('''INSERT INTO customer_campaigns(campaign_key,title,subject,plain_template,html_template,brochure_url,unsubscribe_base,created_by,created_at)
            VALUES(%s,'Fixture','Fixture','__UNSUBSCRIBE__','__UNSUBSCRIBE__',%s,'https://example.invalid/unsub/',%s,%s) RETURNING id''',
            (key or cm.KEY+'-fixture-'+str(seq[0]),cm.origin()+cm.PDF_PATH,uid,now())).fetchone()['id']
        c.execute("INSERT INTO customer_campaign_channels(campaign_id,channel,status,updated_at) VALUES(%s,%s,'sending',%s)", (cid, channel, now()))
        rid = c.execute('''INSERT INTO customer_campaign_recipients(campaign_id,channel,recipient,company_name,sources,unsubscribe_token,status,sent_at,claimed_at,provider_message_id)
            VALUES(%s,%s,%s,'Fixture','[]',%s,%s,%s,%s,%s) RETURNING id''', (cid,channel,recipient,secrets.token_urlsafe(),status,sent_at,sent_at,receipt)).fetchone()['id']
    return cid, rid

calls=[]
def email(*args, **kwargs):
    if kwargs.get('dispatch_check'): kwargs['dispatch_check']()
    calls.append(('email',args[1])); return '<fixture-'+str(len(calls))+'@example.invalid>'
async def whatsapp(*args, **kwargs):
    # The real transport executes its context guard immediately before POST.
    guard = cm.wa._dispatch_guard.get()
    if guard: guard()
    calls.append(('whatsapp',args[0])); return {'messages':[{'id':'wa-fixture-'+str(len(calls))}]}
def send(cid, channel='email'): asyncio.run(cm.deliver(cid,channel,uid))
def approve(cid):
    execute("UPDATE customer_campaign_channels SET status='sending' WHERE campaign_id=?", (cid,))

with patch.object(cm,'utcnow',now), patch.object(cadence,'utcnow',now), patch.object(cm,'official_send',email), patch.object(cm.wa,'send',whatsapp):
    reset(); customer(); calls.clear()
    cid = cm.prepare(uid); approve(cid); send(cid)
    assert len(calls)==1
    for elapsed in (timedelta(days=1),timedelta(days=7)-timedelta(seconds=1)):
        clock[0] = datetime(2070,1,1,9,tzinfo=cm.RIYADH)+elapsed
        duplicate, rid = queued(); send(duplicate)
        assert one('SELECT status FROM customer_campaign_recipients WHERE id=?',(rid,))['status']=='cadence_skipped'
        assert len(calls)==1
    clock[0] += timedelta(seconds=1)
    duplicate, rid = queued(); send(duplicate); assert len(calls)==2
    clock[0] += timedelta(days=400)
    duplicate, rid = queued(); send(duplicate); assert len(calls)==2
    assert one('SELECT cadence_stage FROM customer_campaign_recipients WHERE id=?',(rid,))['cadence_stage'] is None
    print('PASS: initial, +1 day, 168h-1s, exact 168h follow-up, lifetime two-send cap')

    reset(); customer(); calls.clear()
    queued(' FIXTURE@EXAMPLE.COM ',key=cm.KEY,status='sent',sent_at=now()-timedelta(days=1),receipt='<legacy@example.invalid>')
    c1,r1=queued(); c2,r2=queued()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(send,[c1,c2]))
    assert not calls
    clock[0] += timedelta(days=7)
    c3,r3=queued(); c4,r4=queued()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(send,[c3,c4]))
    assert len(calls)==1
    assert len(rows("SELECT id FROM customer_campaign_recipients WHERE status='sent'"))==2
    print('PASS: bare-key legacy history, normalized email identity, cross-campaign parallel old queues')

    reset();customer();calls.clear();cid,rid=queued()
    from threading import Event
    entered,release=Event(),Event()
    def slow_email(*args,**kwargs):
        entered.set()
        assert release.wait(5), 'fixture provider release timed out'
        return email(*args,**kwargs)
    with patch.object(cm,'official_send',slow_email),ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(send,cid)
        assert entered.wait(5)
        second=pool.submit(send,cid);second.result(5)
        assert one("SELECT status FROM customer_campaign_channels WHERE campaign_id=? AND channel='email'",(cid,))['status']=='sending'
        release.set();first.result(5)
    assert len(calls)==1
    print('PASS: concurrent workers on one channel preserve in-flight ownership and send once')

    reset(); customer(); calls.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids=list(pool.map(lambda day:cm.prepare(uid,day),[now().date(),(now()+timedelta(days=1)).date()]))
    assert one("SELECT COUNT(*) n FROM customer_campaign_recipients WHERE status='pending'")['n']==1
    for cid in ids: approve(cid); send(cid)
    assert len(calls)==1
    for state in ('sending','uncertain','bounced','rejected'):
        reset();customer();calls.clear()
        queued(status=state,sent_at=now()-timedelta(days=30))
        cid,rid=queued();send(cid);assert not calls, state
    reset();customer();calls.clear();queued(status='sent')
    cid,rid=queued();send(cid);assert not calls
    print('PASS: concurrent preparations reserve once; unresolved/failure/missing legacy timestamps fail closed')

    reset();customer();calls.clear();cid,rid=queued()
    with patch.object(cm,'official_send',side_effect=MailConnectionFailed()):send(cid)
    assert one('SELECT status FROM customer_campaign_recipients WHERE id=?',(rid,))['status']=='pending'
    approve(cid);send(cid);assert len(calls)==1
    reset();customer();calls.clear();cid,rid=queued()
    with patch.object(cm,'official_send',side_effect=TimeoutError()):send(cid)
    clock[0]+=timedelta(days=30);cid2,rid2=queued();send(cid2);assert not calls
    assert one('SELECT status FROM customer_campaign_recipients WHERE id=?',(rid,))['status']=='uncertain'
    print('PASS: known pre-send failure retries same row; ambiguous outcome never retries or follows up')

    reset();customer();calls.clear();cid,rid=queued()
    execute("UPDATE accounts SET status='do_not_contact'")
    send(cid);assert not calls
    reset();customer();calls.clear();cid,rid=queued()
    with db() as c:c.execute("INSERT INTO marketing_suppressions VALUES('email',' FIXTURE@EXAMPLE.COM ',%s)",(now(),))
    send(cid);assert not calls
    reset();customer();calls.clear();cid,rid=queued()
    def stop_during_preflight(*args,**kwargs):
        execute("UPDATE customer_campaign_channels SET status='paused' WHERE campaign_id=?",(cid,))
        kwargs['dispatch_check']();raise AssertionError('must not submit')
    with patch.object(cm,'official_send',stop_during_preflight):send(cid)
    assert one('SELECT status FROM customer_campaign_recipients WHERE id=?',(rid,))['status']=='cadence_skipped'
    print('PASS: changed CRM optout, normalized suppression and stop during provider preflight')

    def inbox(sender='fixture@example.com',owner=uid,notice='none',duplicate=None,parent='<intro@example.invalid>'):
        seq[0]+=1
        with db() as c:c.execute('''INSERT INTO spacemail_inbox(user_id,uidvalidity,uid,sender,sender_address,manual_reply_address,in_reply_to,message_references,duplicate_of,notice_kind,imported_at)
            VALUES(%s,'fixture',%s,%s,%s,%s,%s,'',%s,%s,%s)''',(owner,seq[0],sender,sender,sender,parent,duplicate,notice,now()))
    for kind in ('exact','wrong_sender','notice','wrong_thread'):
        reset();customer();calls.clear()
        queued(status='sent',sent_at=now()-timedelta(days=8),receipt='<intro@example.invalid>')
        inbox(sender='other@example.com' if kind=='wrong_sender' else 'fixture@example.com',notice='bounce' if kind=='notice' else 'none',parent='<wrong@example.invalid>' if kind=='wrong_thread' else '<intro@example.invalid>')
        cid,rid=queued();send(cid)
        assert len(calls)==(0 if kind=='exact' else 1),kind
    print('PASS: exact validated email reply stops; unrelated sender/thread and notices do not invent replies')

    reset();customer('', '0500000021');calls.clear()
    queued('966500000021','whatsapp',status='cancelled',sent_at=now()-timedelta(days=8),receipt='wa-intro')
    with db() as c:
        cadence.record_whatsapp_reply(c,'+966500000021','event1')
        cadence.record_whatsapp_reply(c,'+966500000021','event1')
    assert one('SELECT COUNT(*) n FROM customer_campaign_replies')['n']==1
    cid,rid=queued('+966500000021','whatsapp');send(cid,'whatsapp');assert not calls
    print('PASS: normalized WhatsApp history and idempotent reliable inbound evidence stop follow-up')

    # A reply may arrive after dispatch, before the acceptance write completes.
    reset();customer('', '+966500000021');calls.clear()
    first,rid=queued('+966500000021','whatsapp',status='sending')
    with db() as c:cadence.record_whatsapp_reply(c,'+966500000021','fast-reply')
    clock[0]+=timedelta(seconds=1)
    execute("UPDATE customer_campaign_recipients SET status='sent',sent_at=?,provider_message_id='fast-receipt' WHERE id=?",(now(),rid))
    clock[0]+=timedelta(days=8)
    cid,rid=queued('+966500000021','whatsapp');send(cid,'whatsapp');assert not calls

    reset();customer();calls.clear();cid,rid=queued()
    real_execute=cm.execute
    def lose_receipt(sql,args=()):
        if "status='sent',provider_message_id" in sql:raise RuntimeError('fixture DB outage after acceptance')
        return real_execute(sql,args)
    with patch.object(cm,'execute',lose_receipt):
        try:send(cid)
        except RuntimeError:pass
        else:raise AssertionError('expected receipt persistence outage')
    clock[0]+=timedelta(days=8);second,rid2=queued();send(second)
    assert len(calls)==1
    assert one('SELECT status FROM customer_campaign_recipients WHERE id=?',(rid,))['status']=='sending'
    print('PASS: fast reply before receipt persistence; accepted-send DB failure never replays')

    # Persisted actual mailbox identity wins even if the channel approver changes.
    from app.storage import hash_password
    other=execute('INSERT INTO users(email,name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                  ('other-admin@example.invalid','Other',hash_password('fixture-password'),'admin',now()))
    reset();customer();calls.clear()
    first,rid=queued(status='sent',sent_at=now()-timedelta(days=8),receipt='<intro@example.invalid>')
    execute('UPDATE customer_campaign_recipients SET sender_user_id=? WHERE id=?',(other,rid))
    execute('UPDATE customer_campaign_channels SET approved_by=? WHERE campaign_id=?',(uid,first))
    inbox(owner=other)
    cid,rid=queued();send(cid);assert not calls
    print('PASS: linked reply uses persisted sending mailbox instead of campaign creator')

    # Exercise the real signed webhook envelope with fake reply transport.
    import hashlib,hmac,json,httpx
    from app import zernio_receiver as receiver
    client=TestClient(app,base_url='http://testserver')
    async def fake_post(*args,**kwargs):return httpx.Response(200,json={'ok':True})
    def incoming(event,**changes):
        payload={'id':event,'event':'message.received',
            'account':{'accountId':changes.get('account','fixture-account'),'platform':'whatsapp'},
            'conversation':{'id':'fixture-conv-'+event,'participantId':changes.get('participant','966500000021'),'isGroup':changes.get('group',False)},
            'message':{'direction':changes.get('direction','incoming'),'text':changes.get('text','hello'),
                'sender':{'phoneNumber':'966500000021','id':'966500000021'}}}
        raw=json.dumps(payload).encode();signature=hmac.new(b'fixture-secret',raw,hashlib.sha256).hexdigest()
        return client.post('/webhooks/zernio',content=raw,headers={'x-zernio-signature':signature if changes.get('signed',True) else 'invalid'})
    reset();customer('', '+966500000021')
    queued('+966500000021','whatsapp',status='sent',sent_at=now()-timedelta(days=8),receipt='wa-intro')
    with patch.dict(os.environ,{'ZERNIO_API_KEY':'fixture','ZERNIO_WEBHOOK_SECRET':'fixture-secret','ZERNIO_WHATSAPP_ACCOUNT_ID':'fixture-account','WHATSAPP_COMMAND_OWNER':''}),patch.object(receiver.httpx.AsyncClient,'post',fake_post),patch.object(receiver,'choose_agent',return_value=None):
        for tag,changes in [('unsigned',{'signed':False}),('wrong-account',{'account':'other'}),('group',{'group':True}),('outbound',{'direction':'outbound'}),('wrong-participant',{'participant':'966500000099'})]:
            assert incoming(tag,**changes).status_code in (200,401)
            assert not rows('SELECT * FROM customer_campaign_replies'),tag
        assert incoming('valid').status_code==200
        assert incoming('valid').status_code==200
        assert one('SELECT COUNT(*) n FROM customer_campaign_replies')['n']==1
        # Exact opt-out is honored even before any campaign attempt exists.
        reset();customer('', '+966500000021')
        assert incoming('stop-before-first',text='STOP').status_code==200
        assert one("SELECT COUNT(*) n FROM marketing_suppressions WHERE channel='whatsapp'")['n']==1
    print('PASS: signed expected-account private inbound guard; replay dedupe; STOP before first send')

# Inspect the actual SMTP boundary callback, without contacting SMTP.
class SMTP:
    submitted=False
    closed=False
    def send_message(self,msg):self.submitted=True;return {}
    def close(self):self.closed=True
smtp=SMTP()
os.environ['ENABLE_EXTERNAL_ACTIONS']='1'
def guard():raise cadence.CadenceStopped('fixture_stop')
with patch.object(spacemail,'password',return_value='fixture'),patch.object(spacemail,'smtp_login',return_value=smtp):
    try:spacemail.send(uid,'fixture@example.com','fixture','fixture',dispatch_check=guard)
    except cadence.CadenceStopped:pass
    else:raise AssertionError('guard lost')
assert not smtp.submitted and smtp.closed
print('PASS: real SMTP stops after login but before send_message without becoming uncertain')

with psycopg.connect(url,autocommit=True) as c:c.execute('DROP SCHEMA '+schema+' CASCADE')
