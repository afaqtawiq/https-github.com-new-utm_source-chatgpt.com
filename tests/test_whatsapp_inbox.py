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
