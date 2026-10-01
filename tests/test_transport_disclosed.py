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
