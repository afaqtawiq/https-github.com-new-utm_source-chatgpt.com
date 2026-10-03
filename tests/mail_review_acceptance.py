"""Local PostgreSQL + fake IMAP acceptance. Never connects to an external service."""
import datetime as dt
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
    from app import spacemail as mail, official_sales, mail_review
    from app.storage import db, one, rows, execute, utcnow, get_session, create_session, hash_password
    client=TestClient(app,base_url='http://testserver',headers={'origin':'http://testserver'},follow_redirects=False)
    client.post('/login',data={'email':os.environ['ADMIN_EMAIL'],'password':os.environ['ADMIN_PASSWORD']})
    session=get_session(client.cookies.get('gla_session'));uid=session['user_id'];csrf={'csrf':session['csrf']};now=utcnow()
    with db() as c:
        c.execute('INSERT INTO spacemail_connections(user_id,password_enc,enabled,updated_at) VALUES(%s,%s,TRUE,NOW())',(uid,mail.cipher().encrypt(b'fake-ci-only').decode()))
    pid=execute('''INSERT INTO sales_prospects(company_name,recipient,mail_user_id,source_url,source_email,identity_name,
        confidence,verified_at,exclusion_basis,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        ('Fixture prospect','buyer@example.invalid',uid,'https://example.invalid','buyer@example.invalid','Fixture prospect',
         'exact_legal',now,'owner_confirmed_not_current_customer','contacted',uid,now,now))
    mid=execute('''INSERT INTO outbound_messages(prospect_id,purpose,recipient,subject,body,status,created_by,mail_user_id,
        provider,provider_message_id,created_at,updated_at,sent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (pid,'intro_prospect','buyer@example.invalid','Introduction','Fixture','sent',uid,uid,'spacemail','<sent@shodai.cc>',now,now,now-dt.timedelta(days=4)))
    aid=execute('INSERT INTO approvals(kind,entity_type,entity_id,status,requested_by,created_at) VALUES(?,?,?,?,?,?)',('external_send','outbound_message',mid,'approved',uid,now))
    execute('UPDATE outbound_messages SET approval_id=? WHERE id=?',(aid,mid))
    def message(identity,html=False,parent=None,html_body=None):
        msg=EmailMessage();msg['From']='buyer@example.invalid';msg['To']=mail.ADDRESS;msg['Date']=formatdate(usegmt=True)
        msg['Message-ID']=identity;msg['Subject']='Customer response needing review'
        if parent:msg['In-Reply-To']=parent
        if html:msg.set_content(html_body or '<html><head><style>hidden</style></head><body><p>Actual customer HTML response</p><script>malicious()</script><img src="https://tracker.invalid/pixel"><p>&lt;script&gt;escaped&lt;/script&gt;</p></body></html>',subtype='html')
        else:msg.set_content('Actual customer response, please review')
        return msg.as_bytes()
    def dsn(identity,action='delayed',recipient='buyer@example.invalid',parent='<sent@shodai.cc>'):
        code='4.4.1' if action=='delayed' else '5.2.2'
        return (f'From: Mail Delivery System <mailer-daemon@example.invalid>\r\nTo: {mail.ADDRESS}\r\nMessage-ID: {identity}\r\nSubject: Delivery Status Notification\r\nReturn-Path: <>\r\nMIME-Version: 1.0\r\nContent-Type: multipart/report; report-type=delivery-status; boundary="dsn"\r\n\r\n'
                f'--dsn\r\nContent-Type: text/plain\r\n\r\nDelivery {action}: mailbox full or connection timed out\r\n'
                f'--dsn\r\nContent-Type: message/delivery-status\r\n\r\nReporting-MTA: dns; mail.example.invalid\r\n\r\nFinal-Recipient: rfc822; {recipient}\r\nAction: {action}\r\nStatus: {code}\r\n\r\n'
                f'--dsn\r\nContent-Type: text/rfc822-headers\r\n\r\nMessage-ID: {parent}\r\nTo: {recipient}\r\n\r\n--dsn--\r\n').encode()
    messages={1:message('<html@example.invalid>',True),2:dsn('<delay@example.invalid>'),3:dsn('<bounce@example.invalid>','failed'),4:dsn('<mismatch@example.invalid>','failed','other@example.invalid')}
    imap=MagicMock();imap.response.return_value=('UIDVALIDITY',[b'1'])
    def command(op,*args):
        if op=='search':return 'OK',[' '.join(str(x) for x in messages).encode()]
        assert args[1]=='(BODY.PEEK[]<0.262144>)'
        return 'OK',[(b'meta',messages[int(args[0])])]
    imap.uid.side_effect=command
    with patch.object(mail,'imap_login',return_value=imap),patch.object(mail,'smtp_login',side_effect=AssertionError('Review attempted mail')):
        mail.sync(uid);mail.sync(uid)
    assert one('SELECT COUNT(*) n FROM spacemail_inbox')['n']==4
    assert one('SELECT COUNT(*) n FROM official_mail_reviews')['n']==0
    assert one('SELECT COUNT(*) n FROM sales_followups')['n']==0
    assert one('SELECT COUNT(*) n FROM accounts')['n']==0
    assert one('SELECT COUNT(*) n FROM opportunities')['n']==0
    assert one('SELECT COUNT(*) n FROM outbound_messages')['n']==1
    assert one('SELECT status FROM sales_prospects WHERE id=?',(pid,))['status']=='contacted'
    items,truncated=mail_review.review_items(uid)
    assert not truncated and len(items)==5
    assert sum(x['kind']=='waiting_reply' for x in items)==1
    delay=next(x for x in items if x['kind']=='delivery_delayed')
    assert delay['related_outbound_id']==mid and delay['association_basis']=='delivery_notice_reference'
    mismatch=next(x for x in items if x.get('notice_recipient')=='other@example.invalid')
    assert mismatch['related_outbound_id'] is None
    # A legacy wrong link cannot become the reference for a reclassified DSN.
    execute("UPDATE official_mail_links SET status='linked',matched_outbound_id=?,prospect_id=? WHERE inbox_id=?",(mid,pid,mismatch['id']))
    mismatch_review=next(x for x in mail_review.review_items(uid)[0] if x['source_kind']=='inbox' and x['id']==mismatch['id'])
    assert mismatch_review['related_outbound_id'] is None and mismatch_review['association_basis'] is None
    html=one('SELECT * FROM spacemail_inbox WHERE message_id=?',('<html@example.invalid>',));iid=html['id']
    assert html['body_format']=='html_text' and 'Actual customer HTML response' in html['body']
    response=client.get('/official-inbox/'+str(iid));assert response.status_code==200
    assert 'Actual customer HTML response' in response.text and '&lt;script&gt;escaped&lt;/script&gt;' in response.text
    assert '<script>' not in response.text and 'tracker.invalid' not in response.text and 'malicious()' not in response.text
    assert 'مراجعات سارة' in client.get('/sales-today').text
    assert 'مراجعة انتظار الرد' in client.get('/sales-review').text
    api=client.get('/api/v7/sales-review').json()
    assert api['automatic_followup'] is False and api['delivery_confirmed_by_smtp'] is False
    path='/sales-review/inbox/'+str(iid)
    payload={**csrf,'status':'open','notes':'Reviewed source; manual association only','related_outbound_id':str(mid),'due_at':'2026-10-05T09:00'}
    assert client.post(path,data={**payload,'csrf':'bad'}).status_code==403
    assert client.post(path,data={**payload,'notes':''}).status_code==400
    assert client.post(path,data={**payload,'due_at':'not-date'}).status_code==400
    assert client.post(path,data=payload).status_code==303
    assert client.post(path,data=payload).status_code==303
    assert one('SELECT COUNT(*) n FROM official_mail_reviews')['n']==1
    # Simulate a selected reference outside the newest-200 dropdown window.
    with patch.object(mail_review,'rows',return_value=[]):
        assert 'value="'+str(mid)+'" selected' in client.get(path).text
    reviewed=next(x for x in mail_review.review_items(uid)[0] if x['source_kind']=='inbox' and x['id']==iid)
    assert reviewed['association_basis']=='manual_review_reference' and reviewed['related_outbound_id']==mid
    # Manual references never bypass exact-thread proof or alter the prospect stage.
    assert client.post('/official-inbox/'+str(iid)+'/draft',data=csrf).status_code==409
    assert one('SELECT status FROM sales_prospects WHERE id=?',(pid,))['status']=='contacted'
    assert client.post(path,data={**payload,'status':'done','notes':'Reviewed; external response still requires approval'}).status_code==303
    assert not any(x['source_kind']=='inbox' and x['id']==iid for x in mail_review.review_items(uid)[0])
    assert client.post(path,data=payload).status_code==303
    assert any(x['source_kind']=='inbox' and x['id']==iid for x in mail_review.review_items(uid)[0])
    # Backfill of an already imported HTML placeholder must not duplicate the row
    # or change original import date, eligibility, safe links, or review decisions.
    before=one('SELECT * FROM spacemail_inbox WHERE id=?',(iid,))
    execute("UPDATE spacemail_inbox SET body='Legacy HTML placeholder',body_format=NULL,content_version=0 WHERE id=?",(iid,))
    with patch.object(mail,'imap_login',return_value=imap),patch.object(mail,'smtp_login',side_effect=AssertionError('Backfill sent')):mail.sync(uid)
    after=one('SELECT * FROM spacemail_inbox WHERE id=?',(iid,))
    assert after['body']==before['body'] and after['imported_at']==before['imported_at'] and after['manual_reply_address']==before['manual_reply_address']
    assert one('SELECT COUNT(*) n FROM official_mail_reviews')['n']==1
    # Exact reply now links; a notice never becomes a reply/draft, even if a
    # forged pre-existing link points at an otherwise valid thread.
    messages[5]=message('<linked@example.invalid>',True,'<sent@shodai.cc>')
    with patch.object(mail,'imap_login',return_value=imap):mail.sync(uid)
    linked=one('SELECT * FROM spacemail_inbox WHERE message_id=?',('<linked@example.invalid>',))
    assert one('SELECT status FROM sales_prospects WHERE id=?',(pid,))['status']=='replied'
    assert not any(x['kind']=='waiting_reply' for x in mail_review.review_items(uid)[0])
    assert client.post('/official-inbox/'+str(linked['id'])+'/draft',data=csrf).status_code==303
    assert one('SELECT status FROM outbound_messages WHERE reply_inbox_id=?',(linked['id'],))['status']=='draft'
    assert client.post('/official-inbox/'+str(delay['id'])+'/draft',data=csrf).status_code==409
    # Refreshing a historical HTML placeholder must honor an actual opt-out,
    # without making ordinary refreshed mail advance CRM state.
    messages[5]=message('<changed-identity@example.invalid>',True,'<sent@shodai.cc>','<p>STOP</p>')
    execute("UPDATE spacemail_inbox SET body='Old HTML placeholder',content_version=0 WHERE id=?",(linked['id'],))
    with patch.object(mail,'imap_login',return_value=imap):mail.sync(uid)
    assert one('SELECT status FROM sales_prospects WHERE id=?',(pid,))['status']=='replied'
    messages[5]=message('<linked@example.invalid>',True,'<sent@shodai.cc>','<blockquote><p>STOP</p></blockquote>')
    with patch.object(mail,'imap_login',return_value=imap):mail.sync(uid)
    assert one('SELECT status FROM sales_prospects WHERE id=?',(pid,))['status']=='replied'
    execute("UPDATE spacemail_inbox SET body='Old HTML placeholder',content_version=0 WHERE id=?",(linked['id'],))
    messages[5]=message('<linked@example.invalid>',True,'<sent@shodai.cc>','<p>STOP</p>')
    with patch.object(mail,'imap_login',return_value=imap):mail.sync(uid)
    assert one('SELECT status FROM sales_prospects WHERE id=?',(pid,))['status']=='stopped'
    assert one("SELECT recipient FROM marketing_suppressions WHERE channel='email' AND recipient='buyer@example.invalid'")
    assert client.post('/official-inbox/'+str(linked['id'])+'/draft',data=csrf).status_code==409
    # A charset the auto-ack parser cannot decode must not wedge the mailbox.
    messages[6]=(f'From: malformed@example.invalid\r\nTo: {mail.ADDRESS}\r\nDate: {formatdate(usegmt=True)}\r\nMessage-ID: <bad-charset@example.invalid>\r\nSubject: shipping request\r\nContent-Type: text/plain; charset=unknown-mail-charset\r\n\r\nShipping request readable as UTF8').encode()
    messages[7]=message('<later@example.invalid>')
    with patch.object(mail,'imap_login',return_value=imap):mail.sync(uid)
    bad=one("SELECT * FROM spacemail_inbox WHERE message_id='<bad-charset@example.invalid>'")
    assert bad and 'Shipping request readable' in bad['body'] and bad['reply_address'] is None
    assert one("SELECT id FROM spacemail_inbox WHERE message_id='<later@example.invalid>'")
    # UID reset deduplicates the source, so no duplicate work appears.
    imap.response.return_value=('UIDVALIDITY',[b'2']);messages={10:message('<html@example.invalid>',True)}
    with patch.object(mail,'imap_login',return_value=imap):mail.sync(uid)
    duplicate=one("SELECT * FROM spacemail_inbox WHERE uidvalidity='2'")
    assert duplicate['duplicate_of']==iid
    assert client.get('/sales-review/inbox/'+str(duplicate['id'])).status_code==409
    assert not any(x['source_kind']=='inbox' and x['id']==duplicate['id'] for x in mail_review.review_items(uid)[0])
    for role in ('admin','sales'):
        other=execute('INSERT INTO users(email,name,password_hash,role,created_at) VALUES(?,?,?,?,?)',(role+'@example.invalid','Other',hash_password('local-only'),role,now))
        sid,token,_=create_session(other)
        stranger=TestClient(app,base_url='http://testserver',headers={'origin':'http://testserver'},follow_redirects=False)
        stranger.cookies.set('gla_session',sid)
        assert stranger.get('/official-inbox/'+str(iid)).status_code in (403,404)
        assert stranger.get(path).status_code in (403,404)
        assert stranger.post(path,data={**payload,'csrf':token}).status_code in (403,404)
        assert 'Actual customer HTML response' not in stranger.get('/sales-today').text
        if role=='admin':assert stranger.get('/api/v7/sales-review').json()['items']==[]
        else:assert stranger.get('/api/v7/sales-review').status_code==403
    # Follow-up review of provider acceptance is also manual and auditable.
    wait_path='/sales-review/outbound/'+str(mid)
    assert client.post(wait_path,data={**csrf,'status':'done','notes':'Reviewed; no resend'}).status_code==303
    assert one('SELECT COUNT(*) n FROM sales_followups')['n']==0
    assert one('SELECT COUNT(*) n FROM official_reply_log')['n']==0
    assert one('SELECT COUNT(*) n FROM outbound_messages')['n']==2
    print('PASS: source-backed review queue, HTML safety, delay/failure separation, exact DSN reference, manual-only linkage, no false replied/qualified/delivered, idempotent review/reopen, legacy content refresh, duplicate exclusion, RBAC/ownership/CSRF, approval-only reply draft. Live sends: 0.')


def main():
    import psycopg
    from psycopg import sql
    url=os.environ.get('AFAAQ_TEST_DATABASE_URL','');target=urlsplit(url)
    if target.hostname not in {'localhost','127.0.0.1'} or target.path!='/afaaq_test' or target.query or target.fragment:
        raise RuntimeError('Requires local disposable afaaq_test database without URL parameters')
    schema='mail_review_test_'+secrets.token_hex(6)
    with psycopg.connect(url,autocommit=True) as c:c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        environment={'DATABASE_URL':url+'?'+urlencode({'options':'-c search_path='+schema+' -c statement_timeout=30000 -c lock_timeout=15000'},quote_via=quote),
            'ADMIN_EMAIL':'mail-review-ci@example.invalid','ADMIN_PASSWORD':secrets.token_urlsafe(24),'TOKEN_ENCRYPTION_KEY':'local-fixture-only',
            'DISCOVERY_AUTO_ENABLED':'0','ENABLE_EXTERNAL_ACTIONS':'0','BROWSER_COOKIE_SECURE':'0'}
        original=socket.socket.connect;attempts=[]
        def local_only(sock,destination):
            if isinstance(destination,tuple) and destination[0] not in {'localhost','127.0.0.1','::1'}:
                attempts.append(destination);raise AssertionError('Live network disabled in mail review acceptance')
            return original(sock,destination)
        with patch.dict(os.environ,environment),patch.object(socket.socket,'connect',local_only):run()
        assert not attempts,attempts
    finally:
        with psycopg.connect(url,autocommit=True) as c:c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__=='__main__':main()
