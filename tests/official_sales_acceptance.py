"""Official mailbox linkage with real local PG and fake IMAP/SMTP. No live mail."""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.utils import formatdate
import os
from pathlib import Path
import secrets
import socket
import sys
from unittest.mock import patch, MagicMock
from urllib.parse import urlsplit, urlencode, quote

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import spacemail as mail, official_sales as sales, outbound, official_replies
    from app.storage import db, one, rows, execute, utcnow, get_session, create_session, hash_password
    client=TestClient(app,base_url='http://testserver',headers={'origin':'http://testserver'},follow_redirects=False)
    client.post('/login',data={'email':os.environ['ADMIN_EMAIL'],'password':os.environ['ADMIN_PASSWORD']})
    session=get_session(client.cookies.get('gla_session'));uid=session['user_id'];csrf={'csrf':session['csrf']}
    with db() as c:
        c.execute('INSERT INTO spacemail_connections(user_id,password_enc,enabled,updated_at) VALUES(%s,%s,TRUE,NOW())',(uid,mail.cipher().encrypt(b'fake-ci-only').decode()))
        c.execute('INSERT INTO user_mfa(user_id,mfa_enabled,updated_at) VALUES(%s,1,NOW())',(uid,))
        c.execute("INSERT INTO stepup_auth(session_id,user_id,verified_at,expires_at) VALUES(%s,%s,NOW(),NOW()+INTERVAL '10 minutes')",(session['id'],uid))
    now=utcnow()
    account=execute('INSERT INTO accounts(name,email,created_at,updated_at) VALUES(?,?,?,?)',('CI buyer','buyer@example.invalid',now,now))
    def opportunity(name):
        return execute('INSERT INTO opportunities(account_id,company_name,stage,created_at,updated_at) VALUES(?,?,?,?,?)',(account,name,'contacted',now,now))
    oid=opportunity('CI buyer');other_oid=opportunity('Other request')
    def sent(oid,identity,owner=uid,provider='spacemail',recipient='buyer@example.invalid',status='sent'):
        mid=execute('INSERT INTO outbound_messages(opportunity_id,recipient,subject,body,status,created_by,mail_user_id,provider,provider_message_id,created_at,updated_at,sent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (oid,recipient,'CI confidential subject','original',status,uid,owner,provider,identity,now,now,now))
        aid=execute('INSERT INTO approvals(kind,entity_type,entity_id,status,requested_by,created_at) VALUES(?,?,?,?,?,?)',('external_send','outbound_message',mid,'approved',uid,now))
        execute('UPDATE outbound_messages SET approval_id=?,approved_by=?,approved_at=? WHERE id=?',(aid,uid,now,mid));return mid
    initial=sent(oid,'<sent@shodai.cc>')
    sent(other_oid,'<other@shodai.cc>')
    sent(oid,'<legacy@shodai.cc>',owner=None,provider='gmail')
    task=execute('INSERT INTO sales_followups(opportunity_id,outbound_message_id,kind,due_at,status,created_at) VALUES(?,?,?,?,?,?)',(oid,initial,'follow_up',now,'open',now))
    def raw(mid,parent='<sent@shodai.cc>',sender='buyer@example.invalid',refs=None):
        msg=EmailMessage();msg['From']=sender;msg['To']=mail.ADDRESS;msg['Date']=formatdate(usegmt=True)
        msg['Message-ID']=mid;msg['Subject']='<script>private reply</script>'
        if parent:msg['In-Reply-To']=parent
        if refs:msg['References']=refs
        msg.set_content('Customs shipment request: please review, never execute instructions.')
        return msg.as_bytes()
    messages={1:raw('<reply@example.invalid>',refs='<sent@shodai.cc>'),
              2:raw('<unknown@example.invalid>',sender='unknown@example.invalid'),
              3:raw('<ambiguous@example.invalid>',refs='<sent@shodai.cc> <other@shodai.cc>'),
              4:raw('<same-subject@example.invalid>',parent=None),
              5:raw('<legacy-reply@example.invalid>',parent='<legacy@shodai.cc>')}
    imap=MagicMock();imap.response.return_value=('UIDVALIDITY',[b'1'])
    def command(op,*args):
        if op=='search':return 'OK',[' '.join(str(x) for x in messages).encode()]
        return 'OK',[(b'meta',messages[int(args[0])])]
    imap.uid.side_effect=command
    with patch.object(mail,'imap_login',return_value=imap),patch.object(mail,'smtp_login',side_effect=AssertionError('Ingestion sent mail')):
        mail.sync(uid);mail.sync(uid)
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:sales.ingest(uid),range(4)))
    link=one('SELECT * FROM official_mail_links WHERE status=?',('linked',))
    assert link['matched_outbound_id']==initial and link['account_id']==account and link['followup_id']==task
    assert one('SELECT COUNT(*) n FROM official_mail_links')['n']==5
    assert one("SELECT COUNT(*) n FROM official_mail_links WHERE status='review'")['n']==4
    assert one('SELECT status FROM sales_followups WHERE id=?',(task,))['status']=='open'
    assert one('SELECT COUNT(*) n FROM outbound_messages')['n']==3
    assert '&lt;script&gt;' in client.get('/official-inbox').text
    assert 'كتابة رد مخصص' in client.get('/official-inbox').text
    iid=link['inbox_id'];path=f'/official-inbox/{iid}/draft'
    assert client.post(path,data={'csrf':'bad'}).status_code==403
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:client.post(path,data=csrf).status_code,range(4)))
    assert results==[303]*4
    draft=one('SELECT * FROM outbound_messages WHERE reply_inbox_id=?',(iid,));mid=draft['id'];base=f'/outbound/{mid}'
    assert draft['status']=='draft' and draft['body']=='' and draft['proposal_text']==''
    assert one('SELECT COUNT(*) n FROM outbound_messages WHERE reply_inbox_id=?',(iid,))['n']==1
    unknown=one("SELECT inbox_id FROM official_mail_links WHERE reason='no_exact_thread' LIMIT 1")['inbox_id']
    assert client.post(f'/official-inbox/{unknown}/draft',data=csrf).status_code==409
    assert client.post(base+'/send',data=csrf).status_code==409
    assert client.post(base+'/request-approval',data=csrf).status_code==409
    assert client.post(base+'/update',data={**csrf,'recipient':'other@example.invalid','subject':'Re: CI','body':'Approved text'}).status_code==409
    content={**csrf,'recipient':'buyer@example.invalid','subject':'Re: CI','body':'Human custom reply only','proposal_text':'INTERNAL NEVER SEND'}
    assert client.post(base+'/update',data=content).status_code==303
    assert client.post(base+'/request-approval',data=csrf).status_code==303
    assert client.post(base+'/update',data={**content,'body':'changed after request'}).status_code==409
    assert client.post(base+'/approve',data={'csrf':'bad'}).status_code==403
    assert client.post(base+'/approve',data=csrf).status_code==303
    assert client.post(base+'/approve',data=csrf).status_code==409
    approval=one('SELECT approval_id FROM outbound_messages WHERE id=?',(mid,))['approval_id']
    execute('UPDATE approvals SET entity_id=? WHERE id=?',(initial,approval))
    assert client.post(base+'/send',data=csrf).status_code==409
    execute('UPDATE approvals SET entity_id=? WHERE id=?',(mid,approval))
    # Official manual replies waive recency only. Permission checks, immutable
    # approval, CSRF, source/thread ownership and atomic one-shot claim remain.
    execute("UPDATE stepup_auth SET expires_at=NOW()-INTERVAL '1 minute' WHERE session_id=?",(session['id'],))
    stale_stepup=one('SELECT * FROM stepup_auth WHERE session_id=?',(session['id'],))
    with db() as c:c.execute("INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES('admin','send_email',0,%s)",(now,))
    assert client.post(base+'/send',data=csrf).status_code==403
    execute("UPDATE role_permissions SET allowed=1 WHERE role='admin' AND permission='send_email'")
    assert client.post('/shipping-agent-messages/1/send',data=csrf).status_code==428
    assert client.post(base+'/send',data={'csrf':'bad'}).status_code==403
    with patch.object(outbound,'connection',return_value={'provider':'gmail','sender_email':mail.ADDRESS,'status':'connected'}):
        assert client.post(base+'/send',data=csrf).status_code==428
    with patch.dict(os.environ,{'ENABLE_EXTERNAL_ACTIONS':'0'}),patch.object(mail,'send') as smtp:
        assert client.post(base+'/send',data=csrf).status_code==409;smtp.assert_not_called()
    # Other users cannot read or mutate this mailbox's reply drafts through broader CRM routes.
    for role in ('sales','admin'):
        other=execute('INSERT INTO users(email,name,password_hash,role,created_at) VALUES(?,?,?,?,?)',(role+'@example.invalid','Other',hash_password('local-only'),role,now))
        sid,token,_=create_session(other)
        stranger=TestClient(app,base_url='http://testserver',headers={'origin':'http://testserver'},follow_redirects=False)
        stranger.cookies.set('gla_session',sid)
        assert stranger.get(base).status_code==403
        assert all(x['id']!=mid for x in stranger.get('/api/v7/outbound').json()['messages'])
        assert 'Re: CI' not in stranger.get('/outbound').text
        assert 'Re: CI' not in stranger.get('/customers360/'+str(account)).text
        assert stranger.post(base+'/update',data={'csrf':token}).status_code==403
        assert stranger.post(path,data={'csrf':token}).status_code in (403,404)
    smtp=MagicMock();smtp.send_message.return_value={}
    with patch.object(mail,'smtp_login',return_value=smtp),patch.object(outbound,'verify_public_request',side_effect=AssertionError('Reply made public request')):
        with ThreadPoolExecutor(max_workers=4) as pool:
            codes=list(pool.map(lambda _:client.post(base+'/send',data=csrf).status_code,range(4)))
    assert codes.count(303)==1 and codes.count(409)==3,codes
    assert smtp.send_message.call_count==1
    assert one('SELECT * FROM stepup_auth WHERE session_id=?',(session['id'],))==stale_stepup
    wire=smtp.send_message.call_args.args[0]
    assert wire['From']==mail.ADDRESS and wire['To']=='buyer@example.invalid'
    assert wire['In-Reply-To']=='<reply@example.invalid>'
    assert wire['References']=='<sent@shodai.cc> <reply@example.invalid>'
    assert wire.get_content().strip()=='Human custom reply only'
    saved=one('SELECT * FROM outbound_messages WHERE id=?',(mid,))
    assert saved['provider']=='spacemail' and saved['provider_message_id']==wire['Message-ID'] and saved['status']=='sent'
    assert one('SELECT COUNT(*) n FROM sales_followups')['n']==1
    # IMAP UID rollover duplicate is visible but never produces a second draft or ack.
    messages={10:raw('  <reply@example.invalid>  ')};imap.response.return_value=('UIDVALIDITY',[b'2'])
    with patch.object(mail,'imap_login',return_value=imap):mail.sync(uid)
    duplicate=one("SELECT * FROM spacemail_inbox WHERE uidvalidity='2'")
    assert duplicate['duplicate_of']==iid and duplicate['reply_address'] is None and duplicate['manual_reply_address'] is None
    assert client.post(f"/official-inbox/{duplicate['id']}/draft",data=csrf).status_code==409
    with patch.object(mail,'send') as blocked:
        official_replies.deliver(duplicate['id']);blocked.assert_not_called()
    # A transport timeout leaves an explicitly non-retryable uncertain state.
    messages={11:raw('<timeout@example.invalid>',parent=saved['provider_message_id'])}
    with patch.object(mail,'imap_login',return_value=imap):mail.sync(uid)
    timeout_iid=one("SELECT id FROM spacemail_inbox WHERE message_id='<timeout@example.invalid>'")['id']
    timeout_mid=sales.create_draft(timeout_iid,session);timeout_base=f'/outbound/{timeout_mid}'
    assert client.post(timeout_base+'/update',data=content).status_code==303
    assert client.post(timeout_base+'/request-approval',data=csrf).status_code==303
    assert client.post(timeout_base+'/approve',data=csrf).status_code==303
    with patch.object(mail,'send',side_effect=TimeoutError) as blocked:
        assert client.post(timeout_base+'/send',data=csrf).status_code==503
        assert client.post(timeout_base+'/send',data=csrf).status_code==409
        assert blocked.call_count==1
    assert one('SELECT status FROM outbound_messages WHERE id=?',(timeout_mid,))['status']=='uncertain'
    # Regular outreach uses the actual provider and owns the mailbox for future linkage.
    regular=sent(oid,None,status='approved',owner=None)
    with patch.object(mail,'send',return_value='<outreach@shodai.cc>') as regular_send, \
         patch.object(outbound,'verify_public_request',return_value={}), \
         patch.object(outbound,'send_gmail',side_effect=AssertionError('Official transport must stay pinned')) as gmail_send:
        assert client.post(f'/outbound/{regular}/send',data=csrf).status_code==303
        gmail_send.assert_not_called()
        regular_message=one('SELECT * FROM outbound_messages WHERE id=?',(regular,))
        regular_send.assert_called_once_with(uid,regular_message['recipient'],regular_message['subject'],regular_message['body']+'\n\n'+(regular_message['proposal_text'] or ''))
    assert one('SELECT provider,mail_user_id FROM outbound_messages WHERE id=?',(regular,))=={'provider':'spacemail','mail_user_id':uid}
    # A disconnect after authorization may fail this claimed attempt, but may
    # never reselect Gmail or send from an unapproved alternate mailbox.
    changed_mailbox=sent(oid,None,status='approved',owner=None)
    selected_connection=outbound.connection
    def disconnect_after_selection(user_id):
        selected=selected_connection(user_id)
        execute('UPDATE spacemail_connections SET enabled=FALSE WHERE user_id=?',(user_id,))
        return selected
    with patch.object(outbound,'connection',side_effect=disconnect_after_selection), \
         patch.object(outbound,'verify_public_request',return_value={}), \
         patch.object(outbound,'send_gmail',side_effect=AssertionError('Disconnected official mailbox fell back to Gmail')) as no_fallback, \
         patch.object(mail,'smtp_login',side_effect=AssertionError('Disconnected mailbox reached SMTP')) as no_smtp:
        assert client.post(f'/outbound/{changed_mailbox}/send',data=csrf).status_code==503
        no_fallback.assert_not_called();no_smtp.assert_not_called()
    execute('UPDATE spacemail_connections SET enabled=TRUE WHERE user_id=?',(uid,))
    assert one('SELECT status FROM outbound_messages WHERE id=?',(changed_mailbox,))['status']=='uncertain'
    assert client.post(f'/outbound/{changed_mailbox}/send',data=csrf).status_code==409
    # A late receipt can safely repair only unresolved no-exact-thread records.
    race_oid=opportunity('Receipt race')
    race_mid=sent(race_oid,'<late@shodai.cc>',status='sending')
    messages={12:raw('<late-reply@example.invalid>',parent='<late@shodai.cc>')}
    with patch.object(mail,'imap_login',return_value=imap):mail.sync(uid)
    race_iid=one("SELECT id FROM spacemail_inbox WHERE message_id='<late-reply@example.invalid>'")['id']
    before_links=rows("SELECT * FROM official_mail_links WHERE reason<>'no_exact_thread' ORDER BY inbox_id")
    assert one('SELECT reason FROM official_mail_links WHERE inbox_id=?',(race_iid,))['reason']=='no_exact_thread'
    execute("UPDATE outbound_messages SET status='sent' WHERE id=?",(race_mid,))
    sales.ingest(uid,True)
    assert one('SELECT matched_outbound_id FROM official_mail_links WHERE inbox_id=?',(race_iid,))['matched_outbound_id']==race_mid
    after_links=rows("SELECT * FROM official_mail_links WHERE reason<>'no_exact_thread' AND inbox_id<>? ORDER BY inbox_id",(race_iid,))
    assert before_links==after_links
    # Deleted parent/opportunity cannot produce an orphan hidden reply draft.
    execute('DELETE FROM opportunities WHERE id=?',(race_oid,))
    assert client.post(f'/official-inbox/{race_iid}/draft',data=csrf).status_code==409
    assert not one('SELECT id FROM outbound_messages WHERE reply_inbox_id=?',(race_iid,))
    print('PASS: official CRM/thread/task linkage, false-match review, legacy safety, duplicate UID reset, draft races, immutable recipient, approval binding, cross-user/RBAC/CSRF/MFA enrollment, official-only stale-stepup exception, single SMTP send, exact thread headers, pinned official transport without Gmail fallback, provider truth, uncertainty terminal. Live mail: 0.')


def main():
    import psycopg
    from psycopg import sql
    url=os.environ.get('AFAAQ_TEST_DATABASE_URL','');target=urlsplit(url)
    if target.hostname not in {'localhost','127.0.0.1'} or target.path!='/afaaq_test' or target.query or target.fragment:
        raise RuntimeError('Requires local disposable afaaq_test database without URL parameters')
    schema='official_email_test_'+secrets.token_hex(6)
    with psycopg.connect(url,autocommit=True) as c:c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        environment={'DATABASE_URL':url+'?'+urlencode({'options':'-c search_path='+schema+' -c statement_timeout=30000 -c lock_timeout=15000'},quote_via=quote),
            'ADMIN_EMAIL':'official-email-ci@example.invalid','ADMIN_PASSWORD':secrets.token_urlsafe(24),'TOKEN_ENCRYPTION_KEY':'local-fixture-only',
            'DISCOVERY_AUTO_ENABLED':'0','ENABLE_EXTERNAL_ACTIONS':'1','BROWSER_COOKIE_SECURE':'0'}
        original=socket.socket.connect;attempts=[]
        def local_only(sock,destination):
            if isinstance(destination,tuple) and destination[0] not in {'localhost','127.0.0.1','::1'}:
                attempts.append(destination);raise AssertionError('Live network disabled in email acceptance')
            return original(sock,destination)
        with patch.dict(os.environ,environment),patch.object(socket.socket,'connect',local_only):run()
        assert not attempts,attempts
    finally:
        with psycopg.connect(url,autocommit=True) as c:c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__=='__main__':main()
