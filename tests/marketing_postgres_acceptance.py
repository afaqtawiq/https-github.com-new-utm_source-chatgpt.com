"""Campaign persistence, MIME content, gates and non-duplication in disposable CI DB."""
import asyncio
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlencode, quote
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parents[1]))
url=os.environ['AFAAQ_TEST_DATABASE_URL']
assert urlsplit(url).hostname in {'localhost','127.0.0.1'} and urlsplit(url).path=='/afaaq_test'
import psycopg
schema='marketing_test_'+secrets.token_hex(5)
with psycopg.connect(url,autocommit=True) as conn:
    conn.execute('CREATE SCHEMA '+schema)
password=secrets.token_urlsafe(24)
os.environ.update(DATABASE_URL=url+'?'+urlencode({'options':'-c search_path='+schema},quote_via=quote),
    DISCOVERY_AUTO_ENABLED='0',ENABLE_EXTERNAL_ACTIONS='0',ADMIN_EMAIL='marketing@example.invalid',
    ADMIN_PASSWORD=password,BROWSER_COOKIE_SECURE='0')
from fastapi.testclient import TestClient
from app.bootstrap import app
from app.storage import execute,one,rows,get_session,utcnow,db
from app import customer_marketing as m
from app import spacemail
from app.marketing_content import EMAIL,WEBSITE,PHONE
from app.zernio_whatsapp import WhatsAppBlocked,template_parameters

client=TestClient(app,base_url='http://testserver',headers={'origin':'http://testserver'})
assert client.get('/customer-campaigns').status_code==401
assert client.get(m.PDF_PATH).content.startswith(b'%PDF')
assert client.post('/login',data={'email':'marketing@example.invalid','password':password}).status_code==200
session=get_session(client.cookies.get('gla_session'));csrf=session['csrf']
for name,email,phone in [('Fixture A','fixture-a@example.com','+966500000021'),('Fixture B','fixture-b@example.com','+971500000022'),('Duplicate','FIXTURE-A@example.com','+966500000021')]:
    execute('INSERT INTO accounts(name,email,phone,status,created_at,updated_at) VALUES(?,?,?,?,?,?)',(name,email,phone,'lead',utcnow(),utcnow()))
assert client.post('/customer-campaigns/prepare',data={}).status_code==403
response=client.post('/customer-campaigns/prepare',data={'csrf':csrf},follow_redirects=False)
assert response.status_code==303,response.text
cid=int(response.headers['location'].rsplit('/',1)[1])
assert m.prepare(session['user_id'])==cid
campaign=one('SELECT * FROM customer_campaigns WHERE id=?',(cid,))
recipients=rows('SELECT * FROM customer_campaign_recipients WHERE campaign_id=?',(cid,))
assert len(recipients)==4
assert all(r['sources'] for r in recipients)
assert client.get('/customer-campaigns/'+str(cid)).status_code==200
assert EMAIL in client.get(f'/customer-campaigns/{cid}/preview').text
assert template_parameters(m.template_spec(campaign),campaign['plain_template'].replace('__UNSUBSCRIBE__','https://example.com/unsub'))==['https://example.com/unsub']
sendpath=f'/customer-campaigns/{cid}/send/email'
assert client.post(sendpath,data={'csrf':csrf,'confirmed':'yes'}).status_code==428
calls=[]
def provider(*args,**kwargs):
    calls.append((args,kwargs));return 'ci-'+str(len(calls))
os.environ['ENABLE_EXTERNAL_ACTIONS']='1'
with patch('app.bootstrap.mfa_state',return_value={'mfa_enabled':1}),patch('app.bootstrap.recent_stepup',return_value=True),patch.object(m,'mailbox_connection',return_value={'status':'connected'}),patch.object(m,'official_send',provider):
    assert client.post(sendpath,data={'csrf':csrf}).status_code==400
    response=client.post(sendpath,data={'csrf':csrf,'confirmed':'yes'})
    assert response.status_code==200,response.text
    assert len(calls)==2
    assert client.post(sendpath,data={'csrf':csrf,'confirmed':'yes'}).status_code==409
    asyncio.run(m.deliver(cid,'email',session['user_id']))
    assert len(calls)==2
    assert calls[0][0][4][2].startswith(b'%PDF')
    assert all(v in calls[0][1]['html_body'] for v in (EMAIL,WEBSITE,PHONE))
    async def blocked(*args):raise WhatsAppBlocked('PENDING')
    with patch.object(m,'approved_template',blocked),patch.object(m.wa,'send',side_effect=AssertionError('Must not send unapproved template')):
        assert client.post(f'/customer-campaigns/{cid}/send/whatsapp',data={'csrf':csrf,'confirmed':'yes'}).status_code==200
        assert one("SELECT status FROM customer_campaign_channels WHERE campaign_id=? AND channel='whatsapp'",(cid,))['status']=='waiting_template'

# GET unsubscribe must never mutate, including mail security link scans.
wa_recipient=next(r for r in recipients if r['channel']=='whatsapp')
path='/marketing/unsubscribe/'+wa_recipient['unsubscribe_token']
assert client.get(path).status_code==200
assert not rows('SELECT * FROM marketing_suppressions')
assert client.post(path).status_code==200
assert one('SELECT status FROM customer_campaign_recipients WHERE id=?',(wa_recipient['id'],))['status']=='suppressed'
execute("UPDATE customer_campaign_channels SET status='sending' WHERE campaign_id=? AND channel='whatsapp'",(cid,))
attempts=[]
async def uncertain(*args,**kwargs):attempts.append(args);raise TimeoutError()
with patch.object(m.wa,'send',uncertain):
    asyncio.run(m.deliver(cid,'whatsapp',session['user_id']))
    execute("UPDATE customer_campaign_channels SET status='sending' WHERE campaign_id=? AND channel='whatsapp'",(cid,))
    asyncio.run(m.deliver(cid,'whatsapp',session['user_id']))
assert len(attempts)==1
assert one("SELECT COUNT(*) n FROM customer_campaign_recipients WHERE status='uncertain'")['n']==1

# Inspect the real MIME builder without connecting to an external mail server.
class SMTP:
    def send_message(self,msg):self.message=msg;return {}
    def close(self):pass
smtp=SMTP()
with patch.object(spacemail,'password',return_value='fixture'),patch.object(spacemail,'smtp_login',return_value=smtp):
    mid=spacemail.send(session['user_id'],'fixture@example.com','Subject','Plain',('brochure.pdf','application/pdf',m.PDF.read_bytes()),html_body='<b>Brochure</b>')
assert mid and smtp.message['From']==EMAIL
assert smtp.message.get_body(preferencelist=('html',)).get_content().strip()=='<b>Brochure</b>'
assert next(smtp.message.iter_attachments()).get_content().startswith(b'%PDF')
print('PASS: customer roster deduplication, public PDF, immutable approval, MFA, HTML+PDF MIME, template gate, unsubscribe, receipts, uncertain-send non-retry.')
with psycopg.connect(url,autocommit=True) as conn:conn.execute('DROP SCHEMA '+schema+' CASCADE')
