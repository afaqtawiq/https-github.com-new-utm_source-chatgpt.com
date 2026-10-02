"""Pure provider-evidence and immutable-snapshot checks, no live network or DB."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest


@pytest.fixture
def recovery(monkeypatch):
    fake = SimpleNamespace(**{k:lambda *a,**kw:None for k in ('db','execute','one','rows','utcnow')})
    monkeypatch.setitem(sys.modules,'app.storage',fake)
    spec = importlib.util.spec_from_file_location('isolated_recovery',Path(__file__).resolve().parents[1]/'app/broadcast_recovery.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.transport,'account_id',lambda:'account')
    return module


def test_only_proven_preflight_is_eligible(recovery):
    row = {'status':'failed','last_error':recovery.LEGACY_PREFLIGHT_ERROR}
    assert recovery.preflight_proven(row)
    for key,value in [('status','uncertain'),('provider_message_id','receipt'),('sent_at','now'),
                      ('replied_at','now'),('post_attempted_at','now'),('provider_response_status',400),
                      ('send_phase','dispatching'),('last_error','network error')]:
        assert not recovery.preflight_proven({**row,key:value}),key
    assert recovery.preflight_proven({'status':'failed','send_phase':'preflight_failed'})


def test_source_snapshot_detects_every_send_safety_change(recovery):
    campaign = {'id':2,'message':'test','status':'completed_with_errors','is_test':True}
    recipient = {'id':3,'driver_id':4,'phone':'+966500000000','status':'failed','last_error':'preflight'}
    baseline = recovery._fingerprint(campaign,[recipient])
    for key in ('phone','status','driver_id','provider_message_id','sent_at','replied_at','post_attempted_at','send_phase','last_error','provider_response_status'):
        assert recovery._fingerprint(campaign,[{**recipient,key:'changed'}]) != baseline
    assert recovery._fingerprint({**campaign,'accepted_at':'now'},[recipient]) != baseline
    assert recovery._fingerprint({**campaign,'message':'changed'},[recipient]) != baseline
    assert recovery.UNIT_RESERVE * 81 <= recovery.CAP == 25


@pytest.mark.parametrize('change,expected',[
    ({},'failed'),({'deliveryStatus':'delivered'},'delivered'),({'deliveryStatus':'read'},'read'),
    ({'deliveryStatus':'failed','deliveredAt':'now'},'unknown'),
    ({'deliveryStatus':'failed','readAt':'now'},'unknown'),
    ({'direction':'incoming'},'unknown'),({'accountId':'wrong'},'unknown'),
    ({'platform':'telegram'},'unknown'),({'conversationId':'wrong'},'unknown'),
    ({'deliveryStatus':'new_status'},'unknown'),({'id':'wrong'},'unknown')])
def test_receipt_must_match_exact_account_direction_conversation_and_id(recovery,monkeypatch,change,expected):
    msg={'id':'receipt','accountId':'account','conversationId':'conversation','direction':'outgoing',
         'platform':'whatsapp','deliveryStatus':'failed','deliveryError':{'code':131042}}
    async def read(*a,**kw):return {'messages':[{**msg,**change}]}
    monkeypatch.setattr(recovery.transport,'read',read)
    result=asyncio.run(recovery.receipt(None,'conversation','receipt'))
    assert result['delivery_status']==expected


def test_receipt_follows_only_provider_pagination_and_missing_fails_closed(recovery,monkeypatch):
    calls=[]
    async def read(client,path,params):
        calls.append(params.copy())
        return {'messages':[], 'pagination':{'hasMore':True,'nextCursor':'opaque'}}
    monkeypatch.setattr(recovery.transport,'read',read)
    assert asyncio.run(recovery.receipt(None,'conversation','receipt'))=={'delivery_status':'unknown'}
    assert len(calls)==2 and calls[1]['cursor']=='opaque'


def test_conversation_index_fails_closed_on_partial_accounts(recovery,monkeypatch):
    async def read(*a,**kw):return {'data':[],'meta':{'accountsFailed':1}}
    monkeypatch.setattr(recovery.transport,'read',read)
    with pytest.raises(recovery.transport.WhatsAppBlocked):
        asyncio.run(recovery.conversation_index(None))


def test_total_budget_keeps_prior_cost_and_never_recycles_uncertain(recovery):
    failed=[{'id':i,'status':'failed','last_error':recovery.LEGACY_PREFLIGHT_ERROR} for i in range(66)]
    sent=[{'id':i+66,'status':'sent','provider_message_id':'old'} for i in range(15)]
    evidence={x['id']:{'kind':'provider_failed'} for x in sent}
    assert recovery.prior_reserve(failed+sent,evidence)==recovery.FAILED_METER_RESERVE*15
    assert recovery.prior_reserve(failed+sent,evidence)+recovery.UNIT_RESERVE*81 <= recovery.CAP
    assert recovery.prior_reserve([{'id':1,'status':'uncertain'}],{})==recovery.UNIT_RESERVE
    assert recovery.prior_reserve([{'id':1,'status':'sent','provider_message_id':'x'}],{})==recovery.UNIT_RESERVE
