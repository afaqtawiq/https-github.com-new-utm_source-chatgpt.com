"""Direct document transport uses synthetic bytes and MockTransport only."""
import asyncio
import io
import json
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser

import httpx
import pytest
from app import zernio_whatsapp as z
from test_zernio_whatsapp import fake_clock

KEY = 'wa-document-' + 'a' * 64

@pytest.fixture(scope='module')
def document_bytes():
    from reportlab.pdfgen.canvas import Canvas
    output=io.BytesIO(); canvas=Canvas(output)
    canvas.drawString(50,750,'Synthetic document transport test. No real transaction.')
    canvas.save()
    return output.getvalue()

@pytest.fixture
def document_provider(monkeypatch,document_bytes):
    monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID','account-test')
    monkeypatch.delenv('ZERNIO_WHATSAPP_ACCOUNT_ID',raising=False)
    state={'requests':[],'posts':[],'clients':[],'active':True,'guard_calls':0,
        'get_headers':{},'send_headers':{},'send_status':200,
        'send_data':{'success':True,'data':{'messageId':'wamid-document','conversationId':'c1'}},
        'conversations':[{'id':'c1','accountId':'account-test','platform':'whatsapp','participantId':'966500000001'}],
        'messages':[{'direction':'incoming','senderId':'966500000001','createdAt':datetime.now(timezone.utc).isoformat()}],
        'content':document_bytes}
    def guard(): state['guard_calls']+=1
    state['guard']=guard
    def handle(request):
        state['requests'].append(request)
        assert request.url.host=='zernio.com'
        if request.method=='POST':
            state['posts'].append(request)
            if state.get('post_error'): raise state['post_error']('private provider token and URL')
            if 'send_raw' in state:
                return httpx.Response(state['send_status'],content=state['send_raw'],headers=state['send_headers'])
            return httpx.Response(state['send_status'],json=state['send_data'],headers=state['send_headers'])
        if request.url.path.endswith('/accounts'):
            result={'accounts':[{'_id':'account-test','platform':'whatsapp','isActive':state['active']}]}
        elif request.url.path.endswith('/messages'): result={'messages':state['messages']}
        elif request.url.path.endswith('/conversations'): result={'data':state['conversations'],'pagination':{'hasMore':False}}
        else: raise AssertionError('No templates, public upload or unrelated endpoint permitted')
        return httpx.Response(200,json=result,headers=state['get_headers'].get(request.url.path,{}))
    def make_client():
        c=httpx.AsyncClient(transport=httpx.MockTransport(handle),follow_redirects=True,
                           headers={'Authorization':'Bearer synthetic-test-only'})
        state['clients'].append(c)
        return c
    monkeypatch.setattr(z,'client',make_client)
    return state

def document_arguments(state,**changes):
    return {'recipient':'+966500000001','content':state['content'],'filename':'reviewed-document.pdf',
        'caption':'Exact reviewed caption','expected_account':'account-test','expected_conversation':'c1',
        'idempotency_key':KEY,**changes}

async def guarded_send(state,**changes):
    with z.dispatch_guard(state['guard']):
        return await z.send_document(**document_arguments(state,**changes))

def send(state,**changes): return asyncio.run(guarded_send(state,**changes))

def test_document_direct_multipart_preserves_exact_reviewed_content(document_provider):
    state=document_provider
    result=send(state,filename='مستند-مراجعة.pdf',caption='الوصف المعتمد بالضبط')
    assert result=={'status':'accepted','provider':'zernio','provider_ids':['wamid-document'],
        'http_status':200,'account_id':'account-test','conversation_id':'c1','public_attachment_url_present':False}
    assert len(state['posts'])==1 and state['guard_calls']==1
    request=state['posts'][0]
    assert str(request.url)==z.BASE+'/inbox/conversations/c1/messages'
    assert request.headers['idempotency-key']==KEY
    assert request.headers['authorization']=='Bearer synthetic-test-only'
    envelope=BytesParser(policy=policy.default).parsebytes(
        ('Content-Type: '+request.headers['content-type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+request.content)
    fields={part.get_param('name',header='content-disposition'):part for part in envelope.iter_parts()}
    assert set(fields)=={'accountId','message','attachment'}
    assert fields['accountId'].get_payload(decode=True)==b'account-test'
    assert fields['message'].get_payload(decode=True).decode()=='الوصف المعتمد بالضبط'
    assert fields['attachment'].get_content_type()=='application/pdf'
    assert fields['attachment'].get_filename()=='مستند-مراجعة.pdf'
    assert fields['attachment'].get_payload(decode=True)==state['content']
    assert all(c.is_closed for c in state['clients'])

def test_document_caption_can_be_empty(document_provider):
    assert send(document_provider,caption='')['status']=='accepted'

@pytest.mark.parametrize('change',[
    {'expected_account':None},{'expected_account':'other'},{'expected_conversation':None},
    {'expected_conversation':''},{'expected_conversation':'..'},{'expected_conversation':'x\nsecret'},
    {'idempotency_key':None},{'idempotency_key':'wa-agent-'+'a'*64},{'idempotency_key':'random'},
    {'recipient':'invalid'},{'content':b'not PDF'},{'content':bytearray(b'%PDF-1.7')},
    {'filename':'../file.pdf'},{'filename':'C:\\file.pdf'},{'filename':'bad\r\nname.pdf'},
    {'filename':'bad\u202ename.pdf'},{'filename':'file.txt'},{'filename':'.pdf'},
    {'filename':'x'*180+'.pdf'},{'filename':'ع'*128+'.pdf'},
    {'caption':None},{'caption':'x'*1025},
])
def test_document_invalid_input_never_reads_or_posts(document_provider,change):
    with pytest.raises(z.WhatsAppBlocked): send(document_provider,**change)
    assert not document_provider['requests']

def test_document_requires_durable_bound_arguments_and_guard(document_provider):
    values=document_arguments(document_provider);values.pop('expected_account')
    with pytest.raises(TypeError): asyncio.run(z.send_document(**values))
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(z.send_document(**document_arguments(document_provider)))
    assert not document_provider['requests']

def test_document_structure_and_size_checked_before_reads(document_provider,monkeypatch):
    with pytest.raises(z.WhatsAppBlocked): send(document_provider,content=b'%PDF-1.7 malformed')
    assert not document_provider['requests']
    monkeypatch.setattr(z,'MAX_DOCUMENT_BYTES',10)
    with pytest.raises(z.WhatsAppBlocked): send(document_provider)
    assert not document_provider['requests']

@pytest.mark.parametrize('problem',['inactive','wrong_account','wrong_platform','group','recipient','closed','wrong_message_account','wrong_message_conversation','different_conversation'])
def test_document_preflight_binds_account_recipient_open_window(document_provider,problem):
    state=document_provider
    if problem=='inactive': state['active']=False
    if problem=='wrong_account': state['conversations'][0]['accountId']='other'
    if problem=='wrong_platform': state['conversations'][0]['platform']='telegram'
    if problem=='group': state['conversations'][0]['isGroup']=True
    if problem=='recipient': state['conversations'][0]['participantId']='966500000002'
    if problem=='closed': state['messages'][0]['createdAt']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    if problem=='wrong_message_account': state['messages'][0]['accountId']='other'
    if problem=='wrong_message_conversation': state['messages'][0]['conversationId']='other'
    if problem=='different_conversation': state['conversations'][0]['id']='c2'
    with pytest.raises(z.WhatsAppBlocked): send(state)
    assert not state['posts']

@pytest.mark.parametrize('mode',['deny','account_change','deadline','window'])
def test_document_guard_and_postwait_rechecks(document_provider,fake_clock,monkeypatch,mode):
    state=document_provider
    async def guard():
        if mode=='deny': raise z.WhatsAppBlocked('Authority revoked')
        if mode=='account_change': monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID','other')
        if mode=='deadline': fake_clock['now']+=301
        if mode=='window':
            class Later(datetime):
                @classmethod
                def now(cls,tz=None): return datetime.now(timezone.utc)+timedelta(days=1)
            monkeypatch.setattr(z,'datetime',Later)
    state['guard']=guard
    with pytest.raises(z.WhatsAppBlocked): send(state)
    assert not state['posts']

def test_document_rate_gate_precedes_guard(document_provider,fake_clock):
    state=document_provider
    state['get_headers']['/api/v1/inbox/conversations/c1/messages']={'Retry-After':'5'}
    state['guard']=lambda:state.update(guard_at=fake_clock['now'])
    start=fake_clock['now'];send(state)
    assert state['guard_at']==start+5 and fake_clock['sleeps']==[5]
    assert len(state['posts'])==1

@pytest.mark.parametrize('status',[301,302,307,308,408,409,500,502,503])
def test_document_ambiguous_http_never_retries_or_redirects(document_provider,status):
    state=document_provider;state['send_status']=status;state['send_data']={'error':'private body'}
    state['send_headers']={'Location':'https://private.invalid/?token=secret','Retry-After':'1'}
    with pytest.raises(z.WhatsAppDocumentSendUncertain) as caught: send(state)
    assert caught.value.http_status==status and caught.value.provider_ids==[]
    assert not isinstance(caught.value,z.WhatsAppBlocked)
    assert len(state['posts'])==1 and 'private' not in str(caught.value)

@pytest.mark.parametrize('status',[400,401,403,404,422,429])
def test_document_clear_rejection_never_retries(document_provider,status):
    state=document_provider;state['send_status']=status;state['send_data']={'success':False,'error':'private failure'}
    with pytest.raises(z.WhatsAppBlocked) as caught: send(state)
    assert caught.value.http_status==status and len(state['posts'])==1
    assert not isinstance(caught.value,z.WhatsAppPreflightBlocked) and 'private' not in str(caught.value)

@pytest.mark.parametrize('evidence',[{'messageId':'wamid-maybe'},{'partialFailure':{}},{'messageIds':['wamid-maybe']},{'attachments':[{'url':'https://private.invalid'}]}])
def test_document_contradictory_4xx_is_uncertain(document_provider,evidence):
    state=document_provider;state['send_status']=400;state['send_data']={'success':False,'data':evidence}
    with pytest.raises(z.WhatsAppDocumentSendUncertain) as caught: send(state)
    assert caught.value.reason=='contradictory_response' and len(state['posts'])==1
    assert 'private' not in str(vars(caught.value))

@pytest.mark.parametrize('failure',[httpx.ReadTimeout,httpx.ConnectError,TimeoutError,asyncio.CancelledError])
def test_document_post_exception_frozen_nonsecret(document_provider,failure):
    state=document_provider;state['post_error']=failure
    with pytest.raises(z.WhatsAppDocumentSendUncertain) as caught: send(state)
    assert caught.value.http_status is None and caught.value.provider_ids==[]
    assert len(state['posts'])==1 and 'private' not in str(caught.value)

@pytest.mark.parametrize('data',[
    None,[],{}, {'success':False,'data':{'messageId':'wamid-maybe'}},
    {'success':True,'data':{}}, {'success':True,'data':{'messageId':123}},
    {'success':True,'data':{'messageId':'https://private.invalid'}},
    {'success':True,'data':{'messageId':'//private.invalid/file'}},
    {'success':True,'data':{'messageId':'https:private'}},
    {'success':True,'data':{'messageId':'www.private.invalid'}},
    {'success':True,'data':{'messageId':'private token text'}},
    {'success':True,'data':{'messageId':'x'*1025}},
    {'success':True,'data':{'messageId':'wamid-a','messageIds':['different']}},
    {'success':True,'data':{'messageId':'wamid-a','messageIds':['wamid-a']*2}},
    {'success':True,'data':{'messageId':'wamid-a','attachments':{}}},
])
def test_document_malformed_receipt_uncertain(document_provider,data):
    state=document_provider;state['send_data']=data
    with pytest.raises(z.WhatsAppDocumentSendUncertain) as caught: send(state)
    assert caught.value.reason=='invalid_receipt' and len(state['posts'])==1
    assert 'private' not in str(vars(caught.value))

def test_document_nonjson_receipt_uncertain(document_provider):
    state=document_provider;state['send_raw']=b'private not-json'
    with pytest.raises(z.WhatsAppDocumentSendUncertain) as caught: send(state)
    assert caught.value.reason=='invalid_receipt' and len(state['posts'])==1

def test_document_response_conversation_mismatch_preserves_id(document_provider):
    state=document_provider;state['send_data']['data']['conversationId']='other'
    with pytest.raises(z.WhatsAppDocumentSendUncertain) as caught: send(state)
    assert caught.value.reason=='receipt_mismatch' and caught.value.provider_ids==['wamid-document']

def test_document_multiple_receipt_ids_bounded(document_provider):
    state=document_provider;state['send_data']['data']['messageIds']=['wamid-document','wamid-caption']
    assert send(state)['provider_ids']==['wamid-document','wamid-caption']

@pytest.mark.parametrize('partial',[{}, {'part':'text','error':'private body'}])
def test_document_partial_failure_terminal_result(document_provider,partial):
    state=document_provider;state['send_data']['data']['partialFailure']=partial
    result=send(state)
    assert result['status']=='partial' and result['provider_ids']==['wamid-document']
    assert not result['public_attachment_url_present'] and len(state['posts'])==1
    assert 'private' not in json.dumps(result)

def test_document_returned_link_warning_without_url(document_provider):
    state=document_provider
    state['send_data']['data'].update(attachments=[{'type':'file','url':'https://private.invalid/?token=secret'}],partialFailure={'error':'private'})
    result=send(state)
    assert result['status']=='public_link_warning' and result['public_attachment_url_present'] is True
    assert result['provider_ids']==['wamid-document'] and len(state['posts'])==1
    assert 'private' not in json.dumps(result) and 'secret' not in json.dumps(result)


def test_document_account_change_during_parser_never_reads_or_posts(document_provider,monkeypatch):
    from app import whatsapp_inbox as inbox
    def parser(data): monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID','changed-account')
    monkeypatch.setattr(inbox,'validate_pdf_locally',parser)
    with pytest.raises(z.WhatsAppBlocked): send(document_provider)
    assert not document_provider['requests']
