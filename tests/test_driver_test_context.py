"""Pure TEST reply correlation. No provider, credential or database access."""
from datetime import datetime, timedelta, timezone
import pytest
from app.driver_test_context import select_context, eligible, NOTICE
from app.transport_test import DISCLAIMER

NOW=datetime(2026,10,2,10,tzinfo=timezone.utc)


def candidate(**changes):
    return dict(broadcast_id=1,shipment_id=1,reference='NQ-1',is_test=True,
        shipment_is_test=True,recipient_id=1,driver_id=1,recipient_status='failed',
        attempt_id=1,attempt_status='accepted',provider_message_id='new-receipt',
        sender_account_id='account',delivery_status='delivered',sent_at=NOW-timedelta(minutes=10),**changes)


def chosen(rows,text='',quote=None,**kwargs):
    return select_context(rows,text,quote,'account',now=NOW,**kwargs)


@pytest.mark.parametrize('text',['أجار رخيص جدا','موافق','السلام عليكم','','👍','أحتاج توضيحًا'])
def test_unique_recent_bound_test_keeps_context_without_acceptance_inference(text):
    assert chosen([candidate()],text)['kind']=='test'
    assert DISCLAIMER in NOTICE and 'ولا يوجد التزام نقل أو دفع' in NOTICE


def test_strong_quote_or_reference_overrides_age_but_never_conflict():
    row=candidate();row['sent_at']=NOW-timedelta(days=3)
    assert chosen([row],'اعتراض','new-receipt')['kind']=='test'
    assert chosen([row],'NQ-1')['kind']=='test'
    assert chosen([row],'NQ-2','new-receipt')['kind']=='ambiguous'
    assert chosen([row],'NQ-1','unknown')['kind']=='ambiguous'
    assert chosen([row],'NQ-1','')['kind']=='ambiguous'
    assert chosen([row],'NQ-1 NQ-2')['kind']=='ambiguous'
    assert chosen([row],'') is None


def test_original_legacy_requires_identifier_and_does_not_guess_account():
    row=candidate();row.update(attempt_id=None,attempt_status=None,recipient_status='sent',sender_account_id=None)
    assert chosen([row],'أجار رخيص') is None
    assert chosen([row],'أجار رخيص','new-receipt')['kind']=='test'
    assert chosen([row],'NQ-1')['kind']=='test'
    row['sender_account_id']='account'
    assert chosen([row],'')['kind']=='test'
    row['sender_account_id']='other'
    assert chosen([row],'NQ-1','new-receipt') is None


@pytest.mark.parametrize('field,value',[
    ('provider_message_id',None),('driver_id',None),('recipient_status','excluded'),
    ('sender_account_id','other'),('attempt_status','uncertain'),('attempt_status','failed'),
    ('delivery_status','failed'),('delivery_status','deleted'),('shipment_is_test',False)])
def test_unverified_or_failed_receipts_never_supply_test_context(field,value):
    row=candidate();row[field]=value
    assert not eligible(row,'account')
    assert chosen([row],'NQ-1','new-receipt') is None


def test_multiple_tests_are_not_selected_by_order_or_latest():
    a=candidate();b={**a,'broadcast_id':2,'reference':'NQ-2','provider_message_id':'second'}
    assert chosen([a,b],'')['kind']=='ambiguous'
    assert chosen([b,a],'')['kind']=='ambiguous'
    assert chosen([a,b],'','second')['context']['reference']=='NQ-2'
    assert chosen([a,b],'NQ-1','second')['kind']=='ambiguous'


def test_real_owner_and_new_request_remain_separate():
    test=candidate();real={**test,'broadcast_id':2,'reference':'NQ-2','is_test':False,'shipment_is_test':False,'provider_message_id':'real'}
    assert chosen([test,real],'hello')['kind']=='ambiguous'
    assert chosen([test,real],'موافق NQ-2') is None
    assert chosen([test,real],'hello','real') is None
    assert chosen([test,real],'NQ-1','real')['kind']=='ambiguous'
    assert chosen([test],'',owner_pending=True)['kind']=='ambiguous'
    assert chosen([test],'طلب نقل',explicit_new_request=True) is None
    assert chosen([test],'طلب نقل','new-receipt',explicit_new_request=True)['kind']=='test'
    assert chosen([test],'NQ-1',owner_pending=True)['kind']=='test'


def test_future_naive_or_missing_times_never_supply_unquoted_context():
    for at in (None,'bad',NOW+timedelta(seconds=1),NOW.replace(tzinfo=None)):
        row=candidate();row['sent_at']=at
        assert chosen([row],'') is None


def test_older_active_real_offer_still_blocks_unquoted_fallback():
    test=candidate()
    real={**test,'is_test':False,'shipment_is_test':False,'reference':'NQ-2',
          'provider_message_id':'real','sent_at':NOW-timedelta(days=5),'broadcast_status':'awaiting_driver'}
    assert chosen([test,real],'')['kind']=='ambiguous'
