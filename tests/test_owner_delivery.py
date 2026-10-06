"""Owner evidence remains distinct from an accepted send and shipment progress."""
import pytest

from app import owner_delivery
from app.transport_status import current_status


@pytest.mark.parametrize('delivery,expected', [
    ('accepted', 'awaiting_owner'), ('sent', 'awaiting_owner'),
    ('delivered', 'awaiting_owner'), ('read', 'awaiting_owner'),
    ('failed', 'owner_delivery_failed'), ('unknown', 'owner_delivery_unknown'),
    ('deleted', 'owner_delivery_unknown'), ('not_sent', 'awaiting_owner'),
])
def test_effective_status_is_honest_without_changing_negotiation(delivery, expected):
    evidence = {'delivery_status': delivery}
    assert current_status('new', 'awaiting_owner', None, evidence) == expected
    assert evidence == {'delivery_status': delivery}


@pytest.mark.parametrize('stage', ['owner_agreed', 'driver_offer_pending_approval', 'driver_accepted', 'closed'])
def test_receipt_never_undoes_negotiation_progress(stage):
    assert current_status('new', stage, None, {'delivery_status': 'failed'}) == stage


@pytest.mark.parametrize('stage', ['driver_assigned', 'in_transit', 'delivered', 'closed', 'test_completed'])
def test_receipt_never_undoes_shipment_progress(stage):
    assert current_status(stage, 'awaiting_owner', None, {'delivery_status': 'failed'}) == stage


def test_true_reply_and_driver_evidence_take_priority():
    assert current_status('new', 'awaiting_owner', None,
                          {'delivery_status': 'failed', 'replied_at': 'now'}) == 'awaiting_owner'
    assert current_status('new', 'awaiting_owner', {'effective_status': 'awaiting_driver'},
                          {'delivery_status': 'failed'}) == 'awaiting_driver'


@pytest.mark.parametrize('status,phrase', [
    ('sent', 'لا يثبت التسليم'), ('delivered', 'وصلت الرسالة'),
    ('read', 'قرأ المستلم'), ('failed', 'فشل تسليم'),
    ('unknown', 'غير مؤكدة'), ('deleted', 'محذوفة'), ('played', 'شغّل المستلم'),
])
def test_receipt_text_identifies_observation_not_agreement(status, phrase):
    evidence = {'provider_message_id': 'receipt', 'accepted_at': 'accepted-at',
                'receipt': {'delivery_status': status, 'checked_at': 'checked-at', 'error_code': 131042}}
    lines = '\n'.join(owner_delivery.evidence_lines(evidence))
    assert phrase in lines and 'ليست قراءة مباشرة' in lines
    assert 'accepted-at' in lines and 'checked-at' in lines and '131042' in lines
    assert 'يوجد رد حقيقي' not in lines


def test_no_receipt_is_acceptance_only_and_calls_are_separate():
    lines = '\n'.join(owner_delivery.evidence_lines({'provider_message_id': 'id'}))
    assert 'غير مؤكدين' in lines and 'فشل تسليم' not in lines
    lines = '\n'.join(owner_delivery.evidence_lines({'provider_call_id': 'call'}))
    assert 'المكالمة' in lines and 'واتساب' not in lines


def test_fingerprint_binds_all_identity_fields_and_observation_version():
    item = dict(id=1, shipment_id=3, record_kind='shipment_request', owner_phone='+966500000001',
                contact_channel='whatsapp', provider_message_id='message', owner_message_provider='zernio',
                owner_message_account_id='account', owner_message_conversation_id='conversation', contacted_at='now')
    before = owner_delivery.fingerprint(item)
    for field in item:
        assert owner_delivery.fingerprint({**item, field: 'changed'}) != before, field
    assert owner_delivery.fingerprint(item, 1) != owner_delivery.fingerprint(item, 2)
    # An actual reply/agreement may arrive during the provider read without
    # invalidating the receipt's identity. Its stronger status is preserved.
    assert owner_delivery.fingerprint({**item, 'status': 'owner_agreed'}) == before


@pytest.mark.parametrize('change', [
    {'provider_message_id': None}, {'status': 'ready_to_contact'},
    {'owner_phone': '+966500000002'}, {'contact_channel': 'retell'},
    {'record_kind': 'carrier_offer'}, {'owner_message_provider': 'twilio'},
    {'owner_message_account_id': 'different'}, {'owner_message_conversation_id': 'different'},
])
def test_reply_binding_requires_current_accepted_identity(change):
    item = {'id': 1, 'shipment_id': 2, 'provider_message_id': 'mid', 'owner_phone': '+966500000001',
            'status': 'awaiting_owner', 'contact_channel': 'whatsapp', 'record_kind': 'shipment_request',
            'owner_message_provider': 'zernio', 'owner_message_account_id': 'account',
            'owner_message_conversation_id': 'conversation', **change}
    class NeverQuery:
        def execute(self, *args): raise AssertionError('Mismatched identity must not bind')
    assert not owner_delivery.bind_reply(NeverQuery(), item, 3, account_id='account',
        conversation_id='conversation', owner_phone='+966500000001', inbound_event_id='event')


def test_historical_reply_does_not_override_failed_receipt():
    evidence = {'provider_message_id': 'mid', 'delivery_status': 'failed',
                'historical_replied_at': 'yesterday', 'replied_at': None}
    assert current_status('new', 'awaiting_owner', None, evidence) == 'owner_delivery_failed'
    text = '\n'.join(owner_delivery.evidence_lines(evidence))
    assert 'دليلًا تاريخيًا' in text and 'يوجد رد حقيقي' not in text


@pytest.mark.parametrize('provider,account,conversation', [
    ('zernio', 'account', None), (None, None, None), ('zernio', None, 'conversation'),
])
def test_missing_accepted_provenance_requires_exact_saved_receipt(provider, account, conversation):
    item = {'id': 1, 'shipment_id': 2, 'provider_message_id': 'mid', 'owner_phone': '+966500000001',
            'status': 'awaiting_owner', 'contact_channel': 'whatsapp', 'record_kind': 'shipment_request',
            'owner_message_provider': provider, 'owner_message_account_id': account,
            'owner_message_conversation_id': conversation}
    class NoProviderProof:
        def execute(self, sql, args):
            assert sql.lstrip().startswith('SELECT id FROM freight_owner_receipts')
            return self
        def fetchone(self): return None
    assert not owner_delivery.bind_reply(NoProviderProof(), item, 3, account_id='account',
        conversation_id='conversation', owner_phone='+966500000001', inbound_event_id='event')
