"""Manager document flow: mocked provider, private disposable SQLite, synthetic PDF."""
from contextlib import contextmanager
import hashlib
import io
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from app import whatsapp_inbox as inbox
from app import zernio_whatsapp as z
from app import whatsapp_outgoing_diagnostic as outgoing_diagnostic
from test_zernio_whatsapp import provider

REAL_DOCUMENT_SEND = z.send_document


def pdf():
    out = io.BytesIO(); canvas = Canvas(out); canvas.drawString(30, 700, 'Synthetic document'); canvas.save()
    return out.getvalue()


@pytest.fixture
def ui(monkeypatch, provider):
    actor = {'role': 'admin', 'id': 'session', 'user_id': 7, 'csrf': 'csrf', 'permission': True, 'mfa': True}
    def session(request):
        if actor['role'] != 'admin': raise HTTPException(403)
        return actor
    def authority(request):
        value = session(request)
        if not value['permission']: raise HTTPException(403)
        if not value['mfa']: raise HTTPException(428)
        return value
    monkeypatch.setattr(z, 'session', session)
    monkeypatch.setattr(inbox, 'send_authority', authority)
    monkeypatch.setitem(sys.modules, 'app.fine_permissions', SimpleNamespace(has_permission=lambda value, permission: value['permission']))
    conn = sqlite3.connect(':memory:', check_same_thread=False); conn.row_factory = sqlite3.Row
    class Connection:
        dialect = 'sqlite'
        def execute(self, sql, args=()): return conn.execute(sql.replace('%s','?').replace('NOW()', 'CURRENT_TIMESTAMP'),args)
    @contextmanager
    def database():
        with conn: yield Connection()
    monkeypatch.setattr(inbox, 'database', database)
    provider['conversations'] = [{'id':'c1','accountId':'account-test','platform':'whatsapp','participantId':'966500000001'}]
    calls = []
    async def send(recipient, content, filename, caption, **kwargs):
        # The real transport invokes this again immediately before POST.
        calls.append((recipient, content, filename, caption, kwargs))
        return {'status':'accepted','provider_ids':['synthetic-id']}
    monkeypatch.setattr(z, 'send_document', send)
    app=FastAPI(); app.include_router(inbox.router); app.include_router(outgoing_diagnostic.router)
    with TestClient(app) as client: yield client,actor,provider,conn,calls
    conn.close()


def upload(client, content=None, **updates):
    fields={'csrf':'csrf','conversation':'c1','caption':'Synthetic caption'}; fields.update(updates)
    return client.post('/whatsapp-inbox/documents', data=fields,
        files={'attachment':('sample.pdf',content or pdf(),'application/pdf')}, follow_redirects=False)


def binding(conn):
    return dict(conn.execute('SELECT * FROM whatsapp_document_drafts').fetchone())


def confirmation(row):
    return {'csrf':'csrf','confirm':'yes','privacy_ack':'yes','sha256':row['sha256'],'recipient':row['recipient'],'account':row['account_id']}


def test_upload_review_send_once_and_remove_private_bytes(ui):
    client,actor,provider,conn,calls=ui; content=pdf()
    response=upload(client,content); assert response.status_code==303,response.text
    path=response.headers['location']; row=binding(conn)
    assert row['sha256']==hashlib.sha256(content).hexdigest() and not calls
    assert row['sha256'] in client.get(path).text
    download=client.get(path+'/file'); assert download.content==content
    assert download.headers['cache-control']=='no-store'
    result=client.post(path+'/send',data=confirmation(row),follow_redirects=False)
    assert result.status_code==303,result.text
    assert len(calls)==1 and calls[0][1]==content
    assert client.post(path+'/send',data=confirmation(row)).status_code==409
    assert client.get(path+'/file').status_code==404
    assert 'accepted' in client.get(path).text


@pytest.mark.parametrize('change,status',[({'mfa':False},428),({'permission':False},403),({'role':'viewer'},403)])
def test_send_requires_current_authority(ui,change,status):
    client,actor,provider,conn,calls=ui
    path=upload(client).headers['location']; row=binding(conn); actor.update(change)
    assert client.post(path+'/send',data=confirmation(row)).status_code==status
    assert not calls


@pytest.mark.parametrize('key,value',[('sha256','0'*64),('recipient','966500000002'),('account','another-account'),('confirm','no'),('privacy_ack','no'),('csrf','wrong')])
def test_send_binding_and_csrf(ui,key,value):
    client,actor,provider,conn,calls=ui; path=upload(client).headers['location']; row=binding(conn)
    values=confirmation(row); values[key]=value
    assert client.post(path+'/send',data=values).status_code in (400,403,409)
    assert not calls


def test_owner_only_review_download_and_cancel(ui):
    client,actor,provider,conn,calls=ui; path=upload(client).headers['location']
    actor['user_id']=8
    assert client.get(path).status_code==404
    assert client.get(path+'/file').status_code==404
    actor['user_id']=7
    assert client.post(path+'/cancel',data={'csrf':'csrf'},follow_redirects=False).status_code==303
    assert client.get(path+'/file').status_code==404 and not calls


def test_invalid_pdf_and_csrf_never_stage(ui):
    client,actor,provider,conn,calls=ui
    assert upload(client,b'%PDF-fake').status_code==415
    assert upload(client,csrf='wrong').status_code==403
    assert not calls


def test_network_uncertainty_never_retries(ui,monkeypatch):
    client,actor,provider,conn,calls=ui; path=upload(client).headers['location']; row=binding(conn)
    async def uncertain(*args,**kwargs): calls.append(1); raise TimeoutError()
    monkeypatch.setattr(z,'send_document',uncertain)
    assert client.post(path+'/send',data=confirmation(row),follow_redirects=False).status_code==303
    assert 'uncertain' in client.get(path).text
    assert client.post(path+'/send',data=confirmation(row)).status_code==409
    assert len(calls)==1


@pytest.mark.parametrize('outcome',['partial','public_link_warning'])
def test_partial_or_public_link_outcome_is_terminal(ui,monkeypatch,outcome):
    client,actor,provider,conn,calls=ui; path=upload(client).headers['location']; row=binding(conn)
    async def attempt(*args,**kwargs):
        calls.append(1); return {'status':outcome,'provider_ids':['synthetic-part']}
    monkeypatch.setattr(z,'send_document',attempt)
    assert client.post(path+'/send',data=confirmation(row),follow_redirects=False).status_code==303
    assert outcome in client.get(path).text
    assert client.post(path+'/send',data=confirmation(row)).status_code==409
    assert client.get(path+'/file').status_code==404 and len(calls)==1


def test_account_change_during_provider_read_cannot_stage(ui,monkeypatch):
    client,actor,provider,conn,calls=ui
    original=inbox.verified_conversation
    async def changed(c,cid):
        result=await original(c,cid)
        monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID','changed-account')
        return result
    monkeypatch.setattr(inbox,'verified_conversation',changed)
    assert upload(client).status_code==409 and not calls


def test_session_change_during_pdf_parse_cannot_stage(ui,monkeypatch):
    client,actor,provider,conn,calls=ui
    def changed(content): actor['id']='replacement-session'
    monkeypatch.setattr(inbox,'validate_pdf_locally',changed)
    assert upload(client).status_code==409 and not calls


def test_upload_and_confirmation_size_limits(ui,monkeypatch):
    client,actor,provider,conn,calls=ui
    path=upload(client).headers['location']
    assert client.post(path+'/send',content=b'x'*8193).status_code==413
    monkeypatch.setattr(inbox,'MAX_PDF_BYTES',32)
    assert upload(client,b'%PDF-'+b'x'*40).status_code==413
    assert not calls


def test_provider_receipt_never_changes_reviewed_caption_or_file(ui):
    client,actor,provider,conn,calls=ui
    path=upload(client,caption='<script>synthetic</script>').headers['location']; row=binding(conn)
    assert '&lt;script&gt;' in client.get(path).text
    values=confirmation(row); values.update(caption='replacement',filename='replacement.pdf')
    assert client.post(path+'/send',data=values,follow_redirects=False).status_code==303
    assert calls[0][2]=='sample.pdf' and calls[0][3]=='<script>synthetic</script>'


@pytest.mark.parametrize('change',[{'role':'viewer'},{'permission':False}])
def test_upload_denied_before_provider_or_staging(ui,change):
    client,actor,provider,conn,calls=ui; actor.update(change)
    assert upload(client).status_code==403
    assert not provider['gets'] and not calls


def test_draft_account_change_does_not_consume_attempt(ui,monkeypatch):
    client,actor,provider,conn,calls=ui
    path=upload(client).headers['location']; row=binding(conn)
    monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID','replacement-account')
    assert client.post(path+'/send',data=confirmation(row)).status_code==409
    assert binding(conn)['state']=='draft' and not calls


def test_cancel_session_change_preserves_draft(ui,monkeypatch):
    client,actor,provider,conn,calls=ui; path=upload(client).headers['location']
    original=inbox.document_confirmation
    async def replaced(request,current):
        result=await original(request,current); actor['id']='new-session'; return result
    monkeypatch.setattr(inbox,'document_confirmation',replaced)
    assert client.post(path+'/cancel',data={'csrf':'csrf'}).status_code==409
    assert binding(conn)['state']=='draft' and not calls


def test_upload_rejects_duplicate_fields(ui):
    client,actor,provider,conn,calls=ui
    response=client.post('/whatsapp-inbox/documents',files=[
        ('csrf',(None,'csrf')),('csrf',(None,'csrf')),('conversation',(None,'c1')),
        ('caption',(None,'')),('attachment',('sample.pdf',pdf(),'application/pdf'))])
    assert response.status_code in (400,413) and not calls


def test_provider_verification_failure_is_bounded_and_does_not_stage(ui):
    client,actor,provider,conn,calls=ui; provider['active']=False
    response=upload(client)
    assert response.status_code==503 and 'nothing was sent' in response.text
    assert not calls


@pytest.mark.parametrize('revoke',[False,True])
def test_ui_through_real_transport_has_durable_guard_and_single_multipart(ui,monkeypatch,revoke):
    import httpx
    from datetime import datetime, timezone
    from app import whatsapp_document_store as documents
    client,actor,provider,conn,calls=ui; content=pdf()
    path=upload(client,content).headers['location']; row=binding(conn)
    posts=[]; checks=[]
    original_guard=documents.send_authorized
    def guard(*args,**kwargs):
        result=original_guard(*args,**kwargs); checks.append(result); return result
    monkeypatch.setattr(documents,'send_authorized',guard)
    def handler(request):
        if request.method=='POST':
            assert binding(conn)['state']=='sending' and checks==[True]
            posts.append(request)
            return httpx.Response(200,json={'success':True,'data':{'messageId':'wamid.synthetic','conversationId':'c1'}})
        if request.url.path.endswith('/accounts'):
            return httpx.Response(200,json={'accounts':[{'_id':'account-test','platform':'whatsapp','isActive':True}]})
        if request.url.path.endswith('/messages'):
            if revoke: actor['permission']=False
            return httpx.Response(200,json={'messages':[{'id':'incoming','accountId':'account-test','conversationId':'c1',
                'direction':'incoming','senderId':'966500000001','createdAt':datetime.now(timezone.utc).isoformat()}]})
        return httpx.Response(200,json={'data':provider['conversations'],'pagination':{'hasMore':False}})
    monkeypatch.setattr(z,'client',lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(z,'send_document',REAL_DOCUMENT_SEND)
    response=client.post(path+'/send',data=confirmation(row),follow_redirects=False)
    assert response.status_code==303,response.text
    if revoke:
        assert not posts and binding(conn)['state']=='blocked'
    else:
        assert len(posts)==1 and content in posts[0].content
        assert b'name="attachment"; filename="sample.pdf"' in posts[0].content
        assert posts[0].headers['idempotency-key']==row['idempotency_key']
        assert binding(conn)['state']=='accepted'
    assert client.post(path+'/send',data=confirmation(row)).status_code in (403,409)
    assert len(posts)==(0 if revoke else 1)


def test_interrupted_upload_recovers_owned_draft_without_changing_review(ui):
    client,actor,provider,conn,calls=ui; content=pdf()
    first=upload(client,content,caption='Original description')
    second=upload(client,content,caption='Replacement must not overwrite')
    assert second.status_code==303,second.text
    assert second.headers['location']==first.headers['location']+'?recovered=1'
    preview=client.get(second.headers['location'])
    assert 'Original description' in preview.text and 'Replacement must not overwrite' not in preview.text
    assert not calls


@pytest.mark.parametrize('reason',['invalid_receipt','receipt_mismatch','contradictory_response','uncertain'])
def test_public_url_uncertainty_preserves_reason_and_privacy_independently(ui,monkeypatch,reason):
    client,actor,provider,conn,calls=ui
    content=pdf();path=upload(client,content).headers['location'];row=binding(conn)
    async def uncertain(*args,**kwargs):
        calls.append(1)
        raise z.WhatsAppDocumentSendUncertain(200,reason,provider_ids=['synthetic-receipt'],
                                            public_attachment_url_present=True)
    monkeypatch.setattr(z,'send_document',uncertain)
    response=client.post(path+'/send',data=confirmation(row),follow_redirects=False)
    assert response.status_code==303,response.text
    result=binding(conn)
    assert result['state']=='uncertain' and result['receipt_reason']==reason
    assert result['public_attachment_url_present'] and result['content_b64'] is None
    assert client.post(path+'/send',data=confirmation(row)).status_code==409
    assert upload(client,content).status_code==409 and len(calls)==1


@pytest.mark.parametrize('status',['partial','public_link_warning'])
def test_valid_partial_or_warning_retains_separate_privacy_evidence(ui,monkeypatch,status):
    client,actor,provider,conn,calls=ui
    path=upload(client).headers['location'];row=binding(conn)
    async def sent(*args,**kwargs):
        calls.append(1)
        return {'status':status,'provider_ids':['synthetic-receipt'],'public_attachment_url_present':True}
    monkeypatch.setattr(z,'send_document',sent)
    assert client.post(path+'/send',data=confirmation(row),follow_redirects=False).status_code==303
    result=binding(conn)
    assert result['state']==status and result['public_attachment_url_present']
    assert result['receipt_reason'] is None and result['content_b64'] is None
    assert client.post(path+'/send',data=confirmation(row)).status_code==409 and len(calls)==1


@pytest.mark.parametrize('change,status,reason',[
    ({'partialFailure':{}},'partial',None),
    ({'conversationId':'different'},'uncertain','receipt_mismatch'),
    ({'messageId':None},'uncertain','invalid_receipt'),
    ({'messageIds':['different']},'uncertain','invalid_receipt'),
    ({'conversationId':'different','partialFailure':{}},'uncertain','receipt_mismatch'),
])
def test_real_transport_public_url_receipt_quality_survives_durable_ui(ui,monkeypatch,change,status,reason):
    import httpx
    from datetime import datetime,timezone
    client,actor,provider,conn,calls=ui
    content=pdf();path=upload(client,content).headers['location'];row=binding(conn);posts=[]
    receipt={'messageId':'synthetic-receipt','conversationId':'c1',
             'attachments':[{'url':'https://private.invalid?token=secret'}],**change}
    def handler(request):
        if request.method=='POST':
            posts.append(request)
            assert binding(conn)['state']=='sending'
            return httpx.Response(200,json={'success':True,'data':receipt})
        if request.url.path.endswith('/accounts'):
            return httpx.Response(200,json={'accounts':[{'_id':'account-test','platform':'whatsapp','isActive':True}]})
        if request.url.path.endswith('/messages'):
            return httpx.Response(200,json={'messages':[{'direction':'incoming','senderId':'966500000001',
                'accountId':'account-test','conversationId':'c1','createdAt':datetime.now(timezone.utc).isoformat()}]})
        return httpx.Response(200,json={'data':provider['conversations'],'pagination':{'hasMore':False}})
    monkeypatch.setattr(z,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(z,'send_document',REAL_DOCUMENT_SEND)
    response=client.post(path+'/send',data=confirmation(row),follow_redirects=False)
    assert response.status_code==303,response.text
    result=binding(conn)
    assert result['state']==status and result['receipt_reason']==reason
    assert result['public_attachment_url_present'] and result['content_b64'] is None
    assert len(posts)==1 and content in posts[0].content
    assert client.post(path+'/send',data=confirmation(row)).status_code==409
    assert len(posts)==1
    preview=client.get(path)
    assert 'private.invalid' not in preview.text and 'secret' not in preview.text
    assert 'private.invalid' not in str(result) and 'secret' not in str(result)


def diagnostic_form(html):
    from html.parser import HTMLParser
    class Forms(HTMLParser):
        def __init__(self):
            super().__init__();self.forms=[];self.current=None
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if tag=='form':self.current={'attrs':attrs,'inputs':[],'receipts':[]}
            elif self.current is not None and tag=='input':self.current['inputs'].append(attrs)
            elif self.current is not None and tag=='option':self.current['receipts'].append(attrs.get('value'))
        def handle_endtag(self,tag):
            if tag=='form' and self.current is not None:
                self.forms.append(self.current);self.current=None
    parser=Forms();parser.feed(html)
    return [form for form in parser.forms if form['attrs'].get('action','').endswith('/privacy-diagnostic')]


def test_terminal_diagnostic_ui_submits_bound_receipt_and_defaults_to_metadata_only(ui):
    client,actor,provider,conn,calls=ui
    path=upload(client).headers['location'];row=binding(conn)
    assert not diagnostic_form(client.get(path).text)
    assert client.post(path+'/send',data=confirmation(row),follow_redirects=False).status_code==303
    forms=diagnostic_form(client.get(path).text)
    assert len(forms)==1 and forms[0]['attrs']['method']=='post'
    form=forms[0];assert form['receipts']==['synthetic-id']
    fields={entry['name']:entry['value'] for entry in form['inputs'] if entry.get('type')=='hidden'}
    assert fields=={'csrf':'csrf','sha256':row['sha256'],'account':row['account_id'],
                    'conversation':row['conversation_id'],'recipient':row['recipient']}
    checks=[entry for entry in form['inputs'] if entry.get('type')=='checkbox']
    assert {entry['name'] for entry in checks}=={'probe','fictional'}
    assert all('checked' not in entry for entry in checks)
    provider['messages']=[{'id':'synthetic-id','accountId':row['account_id'],
        'conversationId':row['conversation_id'],'direction':'outgoing',
        'attachments':[{'type':'file','mimeType':'application/pdf',
                        'url':'https://zernio.com/api/v1/whatsapp/media/synthetic-media?accountId=account-test'}]}]
    response=client.post(form['attrs']['action'],data={**fields,'receipt':'synthetic-id'})
    assert response.status_code==200,response.text
    assert response.json()['anonymous_result']=='not_requested'
    assert len(calls)==1 and binding(conn)['state']=='accepted'
    assert not any('/whatsapp/media/' in url for url in provider['gets'])


def test_terminal_diagnostic_form_requires_fresh_mfa_at_submission(ui):
    client,actor,provider,conn,calls=ui
    path=upload(client).headers['location'];row=binding(conn)
    assert client.post(path+'/send',data=confirmation(row),follow_redirects=False).status_code==303
    actor['mfa']=False
    form=diagnostic_form(client.get(path).text)[0]
    fields={entry['name']:entry['value'] for entry in form['inputs'] if entry.get('type')=='hidden'}
    before=len(provider['gets'])
    assert client.post(form['attrs']['action'],data={**fields,'receipt':'synthetic-id'}).status_code==428
    assert len(provider['gets'])==before and len(calls)==1
