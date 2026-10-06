import asyncio
from contextlib import contextmanager
import json
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app import whatsapp_inbox as inbox
from app import zernio_whatsapp as z
from test_zernio_whatsapp import provider


@pytest.fixture
def setup(monkeypatch, provider):
    current = {'role':'admin','user_id':7,'id':'session','csrf':'csrf'}
    monkeypatch.setattr(z, 'session', lambda request: current if current.get('role') == 'admin' else denied())
    def permission(request):
        actor = z.session(request)
        if not current.get('permission',True): raise HTTPException(403)
        if not current.get('mfa',True): raise HTTPException(428)
        return actor
    monkeypatch.setattr(inbox,'send_authority',permission)
    conn = sqlite3.connect(':memory:',check_same_thread=False)
    conn.row_factory = sqlite3.Row
    class Cursor:
        def __init__(self,cursor): self.cursor=cursor
        def fetchone(self):
            row=self.cursor.fetchone()
            return dict(row) if row else None
    class Connection:
        def execute(self,sql,args=()):
            return Cursor(conn.execute(sql.replace('NOW()','CURRENT_TIMESTAMP').replace('%s','?'),args))
    @contextmanager
    def database():
        with conn: yield Connection()
    monkeypatch.setattr(inbox,'database',database)
    provider['conversations']=[{'id':'c1','accountId':'account-test','platform':'whatsapp','participantId':'966500000001','participantName':'colleague'}]
    from datetime import datetime,timezone
    provider['messages']=[{'id':'inbound','accountId':'account-test','conversationId':'c1','direction':'incoming','senderId':'966500000001','createdAt':datetime.now(timezone.utc).isoformat(),'message':'hello'}]
    app=FastAPI();app.include_router(inbox.router)
    with TestClient(app) as client:
        yield client,current,provider,conn
    conn.close()


def denied(): raise HTTPException(403)


def make_draft(client):
    response=client.post('/whatsapp-inbox/drafts',data={'csrf':'csrf','conversation':'c1','body':'Exact colleague message'},follow_redirects=False)
    assert response.status_code==303,response.text
    return response.headers['location']


def test_read_only_history_status_media_escape(setup):
    client,current,provider,conn=setup
    provider['messages'][0].update(message='<script>alert(1)</script>',deliveryStatus='sent',attachments=[{'filename':'receipt.pdf','mimeType':'application/pdf','url':'https://secret/?token=private'}])
    response=client.get('/whatsapp-inbox?conversation=c1')
    assert response.status_code==200
    assert '&lt;script&gt;' in response.text and '<script>' not in response.text
    assert 'receipt.pdf' in response.text and 'token=private' not in response.text
    assert 'التسليم غير مؤكد' in response.text
    assert response.headers['cache-control']=='no-store'
    assert not provider['posts']


@pytest.mark.parametrize('role',['viewer','sales','transport','finance',None])
def test_non_manager_rejected_before_reads(setup,role):
    client,current,provider,conn=setup;current['role']=role
    assert client.get('/whatsapp-inbox').status_code==403
    assert not provider['gets']
    assert client.post('/whatsapp-inbox/drafts',data={'csrf':'csrf'}).status_code==403


@pytest.mark.parametrize('change',[{'accountId':'other'},{'platform':'telegram'},{'isGroup':True},{'participantId':'invalid'}])
def test_cross_account_group_and_invalid_contact_hidden(setup,change):
    client,current,provider,conn=setup;provider['conversations'][0].update(change)
    assert client.get('/whatsapp-inbox?conversation=c1').status_code==404
    assert not any('/messages' in path for path in provider['gets'])
    assert not provider['posts']


def test_mismatched_message_identity_fails_closed(setup):
    client,current,provider,conn=setup;provider['messages'][0]['accountId']='other'
    assert client.get('/whatsapp-inbox?conversation=c1').status_code==503


def test_immutable_review_and_send_once_no_crm(setup):
    client,current,provider,conn=setup
    path=make_draft(client)
    assert not provider['posts']
    assert 'Exact colleague message' in client.get(path).text
    response=client.post(path+'/send',data={'csrf':'csrf','confirm':'yes','body':'injected','recipient':'966599999999'})
    assert response.status_code==200
    assert provider['posts']==[{'accountId':'account-test','message':'Exact colleague message'}]
    assert 'accepted' in response.text
    assert client.post(path+'/send',data={'csrf':'csrf','confirm':'yes'}).status_code==409
    assert len(provider['posts'])==1
    tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert tables==['whatsapp_inbox_drafts']


@pytest.mark.parametrize('data',[{'csrf':'wrong','confirm':'yes'},{'csrf':'csrf'},{'csrf':'csrf','confirm':'no'}])
def test_send_requires_csrf_and_exact_confirmation(setup,data):
    client,current,provider,conn=setup;path=make_draft(client)
    assert client.post(path+'/send',data=data).status_code in (400,403)
    assert not provider['posts']


@pytest.mark.parametrize('setting,status',[('mfa',428),('permission',403)])
def test_send_requires_mfa_and_permission(setup,setting,status):
    client,current,provider,conn=setup;path=make_draft(client);current[setting]=False
    assert client.post(path+'/send',data={'csrf':'csrf','confirm':'yes'}).status_code==status
    assert not provider['posts']


def test_draft_other_manager_cannot_approve(setup):
    client,current,provider,conn=setup;path=make_draft(client);current['user_id']=8
    assert client.get(path).status_code==404
    assert client.post(path+'/send',data={'csrf':'csrf','confirm':'yes'}).status_code==409
    assert not provider['posts']


@pytest.mark.parametrize('failure',['window','conversation','account','uncertain'])
def test_failed_and_uncertain_never_retry_or_fallback(setup,monkeypatch,failure):
    client,current,provider,conn=setup;path=make_draft(client)
    if failure=='window': provider['messages']=[]
    if failure=='conversation': provider['conversations'][0]['id']='c2'
    if failure=='account': monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID','changed-account')
    if failure=='uncertain': provider['send_status']=500
    response=client.post(path+'/send',data={'csrf':'csrf','confirm':'yes'})
    assert response.status_code in (200,409)
    assert len(provider['posts'])==(1 if failure=='uncertain' else 0)
    assert client.post(path+'/send',data={'csrf':'csrf','confirm':'yes'}).status_code==409
    if failure=='uncertain': assert 'uncertain' in response.text
    assert len(provider['posts'])==(1 if failure=='uncertain' else 0)


def test_partial_provider_read_not_empty_inbox(setup):
    client,current,provider,conn=setup
    provider['get_overrides']['/api/v1/inbox/conversations']=lambda req:httpx.Response(200,json={'data':[],'meta':{'accountsFailed':1}})
    assert client.get('/whatsapp-inbox').status_code==503


def test_list_and_message_pagination(setup):
    client,current,provider,conn=setup
    def pages(req):
        cursor=req.url.params.get('cursor')
        return httpx.Response(200,json={'data':provider['conversations'] if cursor else [],'pagination':{'hasMore':not bool(cursor),'nextCursor':'opaque/next'}})
    provider['get_overrides']['/api/v1/inbox/conversations']=pages
    response=client.get('/whatsapp-inbox')
    assert 'opaque%2Fnext' in response.text
    assert client.get('/whatsapp-inbox?conversation=c1').status_code==200
    assert any('cursor=opaque%2Fnext' in url for url in provider['gets'])


def test_status_distinctions():
    statuses={status:inbox.render_message({'deliveryStatus':status}) for status in ('accepted','sent','delivered','read','failed','unknown')}
    assert len(set(statuses.values()))==6


@pytest.mark.parametrize('change',[{'accountId':'other'},{'conversationId':'other'},{'platform':'telegram'}])
def test_send_rejects_mismatched_window_proof(setup,change):
    client,current,provider,conn=setup;path=make_draft(client)
    provider['messages'][0].update(change)
    response=client.post(path+'/send',data={'csrf':'csrf','confirm':'yes'})
    assert response.status_code==200 and 'blocked' in response.text
    assert not provider['posts']


def test_bootstrap_stepup_returns_to_gettable_preview():
    """Exercise actual middleware code without importing the production database."""
    import ast
    import pathlib
    from fastapi.responses import JSONResponse,RedirectResponse
    tree=ast.parse(pathlib.Path('app/bootstrap.py').read_text())
    selected=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
              and n.name in ('sensitive_permission','enterprise_security_guard')]
    for n in selected: n.decorator_list=[]
    namespace=dict(JSONResponse=JSONResponse,RedirectResponse=RedirectResponse,
        csrf_guard=lambda r:True,get_session=lambda cookie:{'id':'s','user_id':7},
        one=lambda *a:{'is_active':True},execute=lambda *a:None,utcnow=lambda:None,
        role_allowed=lambda *a:True,has_permission=lambda *a:True,
        mfa_state=lambda uid:{'mfa_enabled':True},recent_stepup=lambda sid:False)
    exec(compile(ast.Module(body=selected,type_ignores=[]),'<actual-bootstrap>','exec'),namespace)
    request=SimpleNamespace(method='POST',url=SimpleNamespace(path='/whatsapp-inbox/drafts/abc/send'),cookies={})
    assert namespace['sensitive_permission'](request)=='send_whatsapp'
    response=asyncio.run(namespace['enterprise_security_guard'](request,None))
    assert response.status_code==428
    assert json.loads(response.body)['step_up']=='/mfa/step-up?next=/whatsapp-inbox/drafts/abc'


def test_actual_send_authority_requires_admin_permission_and_mfa(monkeypatch):
    current={'user_id':7,'id':'session'}
    monkeypatch.setattr(z,'session',lambda req:current)
    monkeypatch.setitem(sys.modules,'app.fine_permissions',SimpleNamespace(has_permission=lambda *a:False))
    monkeypatch.setitem(sys.modules,'app.mfa_stepup',SimpleNamespace(recent_stepup=lambda *a:True))
    with pytest.raises(HTTPException) as error: inbox.send_authority(None)
    assert error.value.status_code==403
    monkeypatch.setitem(sys.modules,'app.fine_permissions',SimpleNamespace(has_permission=lambda *a:True))
    monkeypatch.setitem(sys.modules,'app.mfa_stepup',SimpleNamespace(recent_stepup=lambda *a:False))
    with pytest.raises(HTTPException) as error: inbox.send_authority(None)
    assert error.value.status_code==428


def test_authority_revoked_during_preflight_stops_post(setup,monkeypatch):
    client,current,provider,conn=setup;path=make_draft(client)
    def messages(req):
        current['mfa']=False
        return httpx.Response(200,json={'messages':provider['messages']})
    provider['get_overrides']['/api/v1/inbox/conversations/c1/messages']=messages
    client.post(path+'/send',data={'csrf':'csrf','confirm':'yes'})
    assert not provider['posts']


def test_full_arabic_length_draft(setup):
    client,current,provider,conn=setup
    response=client.post('/whatsapp-inbox/drafts',data={'csrf':'csrf','conversation':'c1','body':'ش'*4000},follow_redirects=False)
    assert response.status_code==303
    assert not provider['posts']
    assert client.post('/whatsapp-inbox/drafts',data={'csrf':'csrf','conversation':'c1','body':'ش'*4001}).status_code==400


@pytest.fixture
def pdf_setup(setup,monkeypatch):
    client,current,provider,conn=setup
    provider['messages'][0]['attachments']=[{'type':'file','mimeType':'application/pdf','filename':'receipt.pdf','payload':{'id':'media-123'}}]
    media={'requests':[],'status':200,'headers':{'content-type':'application/pdf'},'body':b'%PDF-1.7\nSynthetic test only'}
    def handle(request):
        media['requests'].append(request)
        return httpx.Response(media['status'],stream=httpx.ByteStream(media['body']),headers=media['headers'])
    provider['get_overrides']['/api/v1/whatsapp/media/media-123']=handle
    return client,current,provider,conn,media


def test_pdf_download_authenticated_bounded_and_no_credentials(pdf_setup):
    client,current,provider,conn,media=pdf_setup
    response=client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0')
    assert response.status_code==200 and response.content==media['body']
    assert response.headers['cache-control']=='no-store'
    assert response.headers['x-content-type-options']=='nosniff'
    assert response.headers['content-disposition'].startswith('attachment;')
    assert response.headers['content-security-policy'].startswith('sandbox')
    assert len(media['requests'])==1
    assert str(media['requests'][0].url)=='https://zernio.com/api/v1/whatsapp/media/media-123?accountId=account-test'
    assert 'cookie' not in media['requests'][0].headers
    assert not provider['posts']
    assert list(conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))==[]


def test_pdf_link_uses_internal_identity_not_private_url(pdf_setup):
    client,current,provider,conn,media=pdf_setup
    provider['messages'][0]['attachments'][0]['url']='https://private.invalid/?token=secret'
    response=client.get('/whatsapp-inbox?conversation=c1')
    assert '/whatsapp-inbox/attachment?conversation=c1&amp;message=inbound&amp;index=0' in response.text
    assert 'token=secret' not in response.text
    assert not media['requests'] and not provider['posts']


@pytest.mark.parametrize('role',['viewer','sales','transport',None])
def test_pdf_nonmanager_cannot_read(pdf_setup,role):
    client,current,provider,conn,media=pdf_setup;current['role']=role
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==403
    assert not provider['gets'] and not media['requests']


@pytest.mark.parametrize('query,status',[
    ('conversation=c2&message=inbound&index=0',404),
    ('conversation=c1&message=missing&index=0',404),
    ('conversation=c1&message=inbound&index=1',404),
    ('conversation=c1&message=inbound&index=-1',400),
    ('conversation=c1&message=inbound&index=0.1',400),
    ('conversation=c1&message=inbound&index=100',400),
    ('conversation=c1&message=inbound&index=٠',400),
    ('conversation=c1&index=0',400)])
def test_pdf_rejects_unbound_identity(pdf_setup,query,status):
    client,current,provider,conn,media=pdf_setup
    assert client.get('/whatsapp-inbox/attachment?'+query).status_code==status
    assert not media['requests'] and not provider['posts']


@pytest.mark.parametrize('change,status',[
    ({'accountId':'other'},502),({'conversationId':'other'},502),({'platform':'telegram'},502),
    ({'isDeleted':True},404),({'deliveryStatus':'deleted'},404),({'attachments':[{'mimeType':'text/html'}]},415)])
def test_pdf_rejects_wrong_message_or_type(pdf_setup,change,status):
    client,current,provider,conn,media=pdf_setup;provider['messages'][0].update(change)
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==status
    assert not media['requests']


@pytest.mark.parametrize('url',[
    'http://lookaside.fbsbx.com/a','https://127.0.0.1/a','https://localhost/a',
    'https://lookaside.fbsbx.com.attacker.example/a','https://lookaside.fbsbx.com:8443/a',
    'https://user:password@lookaside.fbsbx.com/a','https://lookaside.fbsbx.com:wrong/a',
    'file:///etc/passwd','https://lookaside.fbsbx.com/a#fragment',None])
def test_pdf_supplied_media_url_is_never_used(pdf_setup,url):
    client,current,provider,conn,media=pdf_setup
    provider['messages'][0]['attachments'][0].update(url=url,refreshUrl=url)
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==200
    assert len(media['requests'])==1 and media['requests'][0].url.host=='zernio.com'


@pytest.mark.parametrize('status',[301,302,307,308,401,403,404,500])
def test_pdf_media_redirect_or_failure_not_followed(pdf_setup,status):
    client,current,provider,conn,media=pdf_setup
    media.update(status=status);media['headers']['location']='http://127.0.0.1/private'
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==502
    assert len(media['requests'])==1


@pytest.mark.parametrize('mime,body', [('text/html',b'%PDF-1.7'),('application/pdf',b'<html>not pdf</html>')])
def test_pdf_mime_and_signature_required(pdf_setup,mime,body):
    client,current,provider,conn,media=pdf_setup;media['headers']['content-type']=mime;media['body']=body
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==415


@pytest.mark.parametrize('declared',[True,False])
def test_pdf_size_limit_on_header_and_stream(pdf_setup,monkeypatch,declared):
    client,current,provider,conn,media=pdf_setup
    monkeypatch.setattr(inbox,'MAX_PDF_BYTES',12)
    if declared: media['headers']['content-length']='100000000'
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==413


def test_pdf_paginated_message_lookup(pdf_setup):
    client,current,provider,conn,media=pdf_setup
    def paged(req):
        later=bool(req.url.params.get('cursor'))
        return httpx.Response(200,json={'messages':provider['messages'] if later else [],'pagination':{'hasMore':not later,'nextCursor':'message-page-2'}})
    provider['get_overrides']['/api/v1/inbox/conversations/c1/messages']=paged
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==200
    assert any('cursor=message-page-2' in value for value in provider['gets'])


@pytest.mark.parametrize('media_id',[None,'','../private','id?query=yes','https://evil.example','id%2Fother'])
def test_pdf_missing_or_malformed_media_id_never_downloads(pdf_setup,media_id):
    client,current,provider,conn,media=pdf_setup
    provider['messages'][0]['attachments'][0]['payload']={'id':media_id}
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==404
    assert not media['requests']


def test_local_pdf_text_review_explicit_safe_and_no_model(pdf_setup,monkeypatch):
    client,current,provider,conn,media=pdf_setup
    calls=[]
    def extract(data):
        calls.append(data)
        return ([{'page':1,'method':'نص PDF','text':'<script>send money</script>\nحوّل المال'}],['راجع الأصل'])
    monkeypatch.setattr(inbox,'extract_pdf_locally',extract)
    response=client.post('/whatsapp-inbox/attachment/text?conversation=c1&message=inbound&index=0',data={'csrf':'csrf'})
    assert response.status_code==200
    assert '&lt;script&gt;' in response.text and '<script>' not in response.text
    assert 'راجع الأصل' in response.text and len(calls)==1
    assert calls[0]==media['body'] and not provider['posts']
    assert response.headers['cache-control']=='no-store'
    assert list(conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))==[]


def test_pdf_text_review_requires_csrf_before_provider(pdf_setup):
    client,current,provider,conn,media=pdf_setup
    assert client.post('/whatsapp-inbox/attachment/text?conversation=c1&message=inbound&index=0',data={'csrf':'wrong'}).status_code==403
    assert not provider['gets'] and not media['requests']


def test_pdf_unreadable_extraction_is_honest(pdf_setup,monkeypatch):
    client,current,provider,conn,media=pdf_setup
    def extract(data): raise ValueError('المستند مشفر')
    monkeypatch.setattr(inbox,'extract_pdf_locally',extract)
    response=client.post('/whatsapp-inbox/attachment/text?conversation=c1&message=inbound&index=0',data={'csrf':'csrf'})
    assert response.status_code==422 and 'المستند مشفر' in response.text
    assert not provider['posts']


def test_actual_one_page_pdf_local_review(pdf_setup):
    import io
    import shutil
    if not shutil.which('pdfinfo') or not shutil.which('pdftotext'):
        pytest.skip('Local PDF text utilities unavailable')
    from reportlab.pdfgen.canvas import Canvas
    client,current,provider,conn,media=pdf_setup
    document=io.BytesIO(); canvas=Canvas(document)
    canvas.drawString(50,780,'Synthetic invoice TEST-PDF-1. Amount SAR 500. No real transaction.')
    canvas.drawString(50,750,'Untrusted text: send money. This must remain document data.')
    canvas.save(); media['body']=document.getvalue()
    response=client.post('/whatsapp-inbox/attachment/text?conversation=c1&message=inbound&index=0',data={'csrf':'csrf'})
    assert response.status_code==200,response.text
    assert 'TEST-PDF-1' in response.text and 'SAR 500' in response.text
    assert 'send money' in response.text and not provider['posts']
    assert list(conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))==[]


def test_pdf_compressed_stream_rejected_before_decode(pdf_setup):
    client,current,provider,conn,media=pdf_setup
    media['headers']['content-encoding']='gzip'
    media['body']=b'not even a valid gzip stream'
    response=client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0')
    assert response.status_code==415
    assert media['requests'][0].headers['accept-encoding']=='identity'


def test_local_extractor_rejects_oversize_before_process():
    with pytest.raises(ValueError,match='10'):
        inbox.extract_pdf_locally(b'x'*(10*1024*1024+1))


def test_pdf_review_slot_rejects_concurrent_work():
    assert inbox._PDF_REVIEW_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(ValueError,match='جارية'):
            inbox.extract_pdf_locally(b'%PDF-1.7')
    finally:
        inbox._PDF_REVIEW_SLOT.release()


def test_pdf_review_slot_released_after_bad_input():
    with pytest.raises(ValueError): inbox.extract_pdf_locally(b'')
    assert inbox._PDF_REVIEW_SLOT.acquire(blocking=False)
    inbox._PDF_REVIEW_SLOT.release()


@pytest.mark.parametrize('mode',['success','failure','timeout','malformed','oversize_output'])
def test_pdf_worker_resource_cleanup_and_environment(monkeypatch,mode):
    import os
    import subprocess
    calls={'kills':[],'waits':0}
    monkeypatch.setenv('ZERNIO_API_KEY','synthetic-must-not-reach-worker')
    class Process:
        pid=999991
        returncode=1 if mode=='failure' else 0
        def __init__(self,args,**kwargs):
            assert args[1]=='-c'
            assert 'RLIMIT_AS' in args[2] and 'RLIMIT_CORE' in args[2]
            assert kwargs['start_new_session'] is True and kwargs['close_fds'] is True
            assert 'ZERNIO_API_KEY' not in kwargs['env'] and kwargs['env']['OMP_THREAD_LIMIT']=='1'
            calls['scratch']=kwargs['env']['TMPDIR']
            from pathlib import Path
            Path(calls['scratch'],'source.pdf').write_bytes(b'synthetic private test')
            payload={'pages':[{'page':1,'method':'text','text':'bounded'}],'notes':[]}
            if mode=='malformed': payload=['wrong shape']
            output=json.dumps(payload).encode() if mode!='oversize_output' else b'x'*(1024*1024+1)
            kwargs['stdout'].write(output);kwargs['stdout'].flush()
        def communicate(self,**kwargs):
            assert kwargs=={'input':b'%PDF-1.7 test','timeout':100}
            if mode=='timeout': raise subprocess.TimeoutExpired('fixed-worker',100)
        def wait(self): calls['waits']+=1
    monkeypatch.setattr(subprocess,'Popen',Process)
    monkeypatch.setattr(os,'killpg',lambda pid,sig:calls['kills'].append(pid))
    if mode=='success':
        pages,notes=inbox.extract_pdf_locally(b'%PDF-1.7 test')
        assert pages[0]['text']=='bounded'
    else:
        with pytest.raises(ValueError): inbox.extract_pdf_locally(b'%PDF-1.7 test')
    assert calls['kills']==[999991] and calls['waits']==1
    assert not os.path.exists(calls['scratch'])


def test_account_change_during_pdf_extraction_rejects_output(pdf_setup,monkeypatch):
    client,current,provider,conn,media=pdf_setup
    def extract(data):
        monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID','changed-account')
        return ([{'page':1,'method':'text','text':'Do not reveal on changed account'}],[])
    monkeypatch.setattr(inbox,'extract_pdf_locally',extract)
    response=client.post('/whatsapp-inbox/attachment/text?conversation=c1&message=inbound&index=0',data={'csrf':'csrf'})
    assert response.status_code==409
    assert 'Do not reveal' not in response.text


def test_numeric_provider_media_id_is_supported(pdf_setup):
    client,current,provider,conn,media=pdf_setup
    provider['messages'][0]['attachments'][0]['payload']={'id':1234567890123456}
    provider['get_overrides']['/api/v1/whatsapp/media/1234567890123456']=provider['get_overrides']['/api/v1/whatsapp/media/media-123']
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==200
    assert '/whatsapp/media/1234567890123456?' in str(media['requests'][0].url)


def test_canonical_attachment_proxy_supplies_verified_identity(pdf_setup):
    client,current,provider,conn,media=pdf_setup
    item=provider['messages'][0]['attachments'][0]
    item['payload']={};item['url']='https://zernio.com/api/v1/whatsapp/media/media-123?accountId=account-test'
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==200
    assert not any('/attachments/' in url for url in provider['gets'])


def test_official_resolver_fallback_uses_bound_message_only(pdf_setup):
    client,current,provider,conn,media=pdf_setup
    provider['messages'][0]['attachments'][0]['payload']={}
    path='/api/v1/inbox/conversations/c1/messages/inbound/attachments/0'
    def resolve(req):
        assert req.url.params['accountId']=='account-test' and req.url.params['format']=='json'
        return httpx.Response(200,json={'url':'https://zernio.com/api/v1/whatsapp/media/media-123?accountId=account-test'})
    provider['get_overrides'][path]=resolve
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==200
    assert len(media['requests'])==1


@pytest.mark.parametrize('url',[
    'https://evil.example/api/v1/whatsapp/media/media-123',
    'https://zernio.com.evil.example/api/v1/whatsapp/media/media-123',
    'https://zernio.com/api/v1/whatsapp/media/media-123?accountId=other',
    'https://zernio.com/api/v1/whatsapp/media/media-123?accountId=account-test&accountId=other',
    'https://zernio.com/api/v1/whatsapp/media/../accounts',
    'https://zernio.com/api/v1/whatsapp/media/media-123/extra',
    'https://zernio.com/api/v1/whatsapp/media/media-123%2Fextra',
    'http://zernio.com/api/v1/whatsapp/media/media-123',
    'https://user:pass@zernio.com/api/v1/whatsapp/media/media-123',
    'https://zernio.com:444/api/v1/whatsapp/media/media-123',
])
def test_resolved_media_identity_cannot_change_origin_or_account(pdf_setup,url):
    client,current,provider,conn,media=pdf_setup
    item=provider['messages'][0]['attachments'][0];item['payload']={};item['url']=url
    provider['get_overrides']['/api/v1/inbox/conversations/c1/messages/inbound/attachments/0']=lambda req:httpx.Response(200,json={'url':url})
    assert client.get('/whatsapp-inbox/attachment?conversation=c1&message=inbound&index=0').status_code==404
    assert not media['requests']
