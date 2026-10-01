"""Pure disclosure and approval invariants; all storage reads are local fakes."""
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.transport_test import (DISCLAIMER, accepts_test_offer, display_reference,
                                preview_digest, test_broadcast_context as context)
from app.zernio_whatsapp import template_parameters

TEMPLATE = {'components': [{'type': 'BODY', 'text': 'عرض حمولة من آفاق طويق — {{1}}\nالمسار: {{2}} → {{3}}\nالوزن: {{4}} طن\nسعر السائق: {{5}} ريال\nالتنزيل: {{6}}\nالدفع: {{7}}\nللرغبة اكتب: موافق {{1}}\nشكرًا لتعاونك.'}]}


def message(ref='NQ-900'):
    ref = display_reference(ref, True)
    return f'عرض حمولة من آفاق طويق — {ref}\nالمسار: جدة → الشارقة\nالوزن: 20 طن\nسعر السائق: 1,850.00 ريال\nالتنزيل: مستودع تجريبي\nالدفع: محاكاة دون دفع\nللرغبة اكتب: موافق {ref}\nشكرًا لتعاونك.'


@pytest.fixture
def campaign(monkeypatch):
    state = {'shipment': {'reference': 'NQ-900', 'is_test': True},
             'recipients': [{'driver_id': 2, 'phone': '+966500000002'}, {'driver_id': 3, 'phone': '+966500000003'}]}
    monkeypatch.setitem(sys.modules, 'app.storage', SimpleNamespace(
        one=lambda *args: state['shipment'], rows=lambda *args: state['recipients']))
    return {'id': 9, 'shipment_id': 900, 'is_test': True, 'message': message()}, state


def test_disclosure_uses_existing_template_consistently():
    params = template_parameters(TEMPLATE, message())
    assert len(params) == 7 and params[0] == display_reference('NQ-900', True)
    assert message().count(DISCLAIMER) == 2
    assert template_parameters(TEMPLATE, message().replace('موافق ' + DISCLAIMER, 'موافق')) is None


@pytest.mark.parametrize('text,valid', [
    ('موافق ' + display_reference('NQ-900', True), True),
    ('موافق NQ-900', False), ('غير موافق ' + display_reference('NQ-900', True), False),
    ('هل توافق ' + display_reference('NQ-900', True), False),
    ('موافق ' + display_reference('NQ-900', True) + ' NQ-901', False),
])
def test_test_acceptance_is_exact_and_correlated(text, valid):
    assert accepts_test_offer(text) is valid


def test_unapproved_direct_delivery_is_blocked(campaign):
    item, _ = campaign
    assert context(item)['digest']
    with pytest.raises(HTTPException): context(item, approved=True)


@pytest.mark.parametrize('change', ['message', 'audience', 'marker', 'shipment_marker', 'approver'])
def test_approval_binds_message_audience_and_persistent_markers(campaign, change):
    item, state = campaign
    digest = context(item)['digest']
    item.update(test_approved_by=1, test_approved_at='now', test_preview_digest=digest)
    assert context(item, approved=True)['digest'] == digest
    if change == 'message': item['message'] = item['message'].replace(DISCLAIMER, '')
    if change == 'audience': state['recipients'].append({'driver_id': 4, 'phone': '+966500000004'})
    if change == 'marker': item['is_test'] = False
    if change == 'shipment_marker': state['shipment']['is_test'] = False
    if change == 'approver': item['test_approved_by'] = None
    with pytest.raises(HTTPException): context(item, approved=True)


def test_real_broadcast_does_not_acquire_test_approval(campaign):
    item, state = campaign
    item['is_test'] = state['shipment']['is_test'] = False
    assert context(item, approved=True) is None


def test_digest_is_order_independent_but_not_audience_independent(campaign):
    item, state = campaign
    recipients = state['recipients']
    assert preview_digest(item['message'], recipients) == preview_digest(item['message'], recipients[::-1])
    assert preview_digest(item['message'], recipients) != preview_digest(item['message'], recipients[:1])


def test_short_owner_inquiry_has_only_approved_questions_and_no_reference():
    from app.transport_owner import inquiry
    from app.transport_test import owner_inquiry
    body = 'السلام عليكم، معك آفاق طويق. بخصوص حمولة جدة إلى الشارقة: كم السعر؟ وما طريقة الدفع؟ والتحميل من داخل الميناء أم خارجه؟'
    assert inquiry('جدة', 'الشارقة') == body
    assert owner_inquiry({'is_test':True,'reference':'NQ-29','origin':'جدة','destination':'الشارقة'}) == DISCLAIMER + '\n' + body


@pytest.fixture
def pending_owners():
    return [{'id':1,'reference':'NQ-1','provider_message_id':'wamid-old','origin':'جدة','destination':'الشارقة','is_test':True},
            {'id':2,'reference':'NQ-2','provider_message_id':'wamid-new','origin':'الرياض','destination':'دبي','is_test':False}]


def test_owner_correlation_unique_quote_and_route(pending_owners):
    from app.transport_owner import select_pending, quoted_receipt, clarification
    first, second = pending_owners
    assert select_pending([first], 'السعر: 2000') == first
    assert select_pending(pending_owners, 'السعر: 2000') is None
    assert select_pending(pending_owners, 'جدة إلى الشارقة\nالسعر: 2000') == first
    payload = {'id':'event','message':{'id':'inbound'},'metadata':{'quotedMessageId':'wamid-other-perspective',
        'quotedMessage':{'messageId':'internal-id','platformMessageId':'wamid-old'}}}
    assert quoted_receipt(payload) == 'wamid-old'
    assert select_pending(pending_owners, 'السعر: 2000', quoted_receipt(payload)) == first
    assert 'NQ-' not in clarification(pending_owners)
    assert 'جدة إلى الشارقة' in clarification(pending_owners)
    assert select_pending([first, {**second, 'origin':'جدة','destination':'الشارقة'}], 'جدة إلى الشارقة السعر: 2000') is None


@pytest.mark.parametrize('quote,text', [('stale','السعر: 2000'), ('','السعر: 2000'), ('wamid-new','NQ-1 السعر: 2000')])
def test_stale_malformed_or_conflicting_quote_never_falls_back(pending_owners, quote, text):
    from app.transport_owner import select_pending
    assert select_pending(pending_owners, text, quote) is None
    assert select_pending(pending_owners[:1], text, quote) is None


@pytest.mark.parametrize('metadata,expected', [({},None), ({'quotedMessageId':'raw'},'raw'),
    ({'quotedMessage':{'messageId':'internal'}},''), ({'quotedMessageId':123},''),
    ({'quotedMessage':{},'quotedMessageId':'raw'},'raw')])
def test_quote_contract_uses_only_documented_platform_identifiers(metadata, expected):
    from app.transport_owner import quoted_receipt
    assert quoted_receipt({'metadata':metadata}) == expected


@pytest.mark.parametrize('text,expected', [('من داخل الميناء','inside'),('التحميل خارج الميناء','outside'),
    ('داخل الميناء أم خارج الميناء',None),('ليس داخل الميناء',None),('لا أعرف',None),('داخل الميناء؟',None),('التنزيل داخل الميناء',None),('داخل الميناء أو خارجه',None),('التحميل خارج الميناء\nالتحميل داخل الميناء',None)])
def test_port_status_is_explicit_only(text, expected):
    from app.transport_owner import loading_port_status
    assert loading_port_status(text) == expected


def test_explicit_wrong_route_and_empty_quote_do_not_match_unique_pending(pending_owners):
    from app.transport_owner import select_pending
    first, second = pending_owners
    assert select_pending([second], 'جدة إلى الشارقة\nالسعر: 2000') is None
    assert select_pending(pending_owners, 'جدة إلى الشارقة\nالسعر: 2000', 'wamid-new') is None
    assert select_pending([{**first,'provider_message_id':''}], 'السعر: 2000', '') is None
    assert select_pending([first], 'جدة إلى الشارقة أو الرياض إلى دبي السعر: 2000') is None


def test_hidden_reference_still_binds_owner_preview_approval():
    from app.transport_test import owner_inquiry, owner_inquiry_digest
    first = {'is_test':True,'reference':'NQ-1','owner_phone':'+966500000001','origin':'جدة','destination':'الشارقة'}
    second = {**first,'reference':'NQ-2'}
    assert owner_inquiry(first) == owner_inquiry(second)
    assert owner_inquiry_digest(first) != owner_inquiry_digest(second)


@pytest.mark.parametrize('number,reason', [
    ('+966055504207','invalid_saudi_trunk_prefix'), ('+966050850729','invalid_saudi_trunk_prefix'),
    ('+96655504207','invalid_saudi_nsn_length'), ('+9665555042070','invalid_saudi_nsn_length'),
    ('+966555504207',''), ('+966115504207',''), ('+971501234567',''), ('+12025550123',''),
    ('+00012345678','invalid_e164'), ('not-a-phone','invalid_e164')])
def test_driver_contact_validation_never_repairs_bad_saudi_numbers(number, reason):
    from app.driver_offer import phone_error, driver_phone
    assert phone_error(number).split(':')[0] == reason
    assert bool(driver_phone(number)) == (not reason)


def test_port_qualifier_is_truthful_approved_template_parameter():
    from app.driver_offer import offer_message
    item = {'reference':'NQ-29','origin':'جدة','destination':'الشارقة','is_test':True,
            'agreed_owner_price':8700,'weight_tons':25,'payment_method':'عند التنزيل','loading_port_status':'inside'}
    message = offer_message(item)
    params = template_parameters(TEMPLATE, message)
    assert params == [display_reference('NQ-29', True),'جدة (التحميل داخل الميناء)','الشارقة','25','8,550.00','الشارقة','عند التنزيل']
    assert item['origin'] == 'جدة' and message.count(DISCLAIMER) == 2
    item['loading_port_status'] = None
    assert '(التحميل' not in offer_message(item)
