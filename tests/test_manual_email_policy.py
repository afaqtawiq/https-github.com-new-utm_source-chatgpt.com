"""The official manual-mail exception is a pure, exact, fail-closed predicate."""
import pytest

from app.manual_email_policy import (
    is_manual_outbound_send,
    official_manual_send_without_stepup,
)


OFFICIAL = {'provider': 'spacemail', 'sender_email': 'afaq@shodai.cc', 'status': 'connected'}


@pytest.mark.parametrize('path', ['/outbound/1/send', '/outbound/234567890/send'])
def test_only_canonical_manual_post_is_eligible(path):
    assert is_manual_outbound_send('POST', path)
    assert official_manual_send_without_stepup('POST', path, OFFICIAL)


@pytest.mark.parametrize('method', ['GET', 'HEAD', 'OPTIONS', 'PUT', 'PATCH', 'DELETE', 'post', ' POST', ''])
def test_other_methods_are_never_eligible(method):
    assert not is_manual_outbound_send(method, '/outbound/1/send')
    assert not official_manual_send_without_stepup(method, '/outbound/1/send', OFFICIAL)


@pytest.mark.parametrize('path', [
    '', '/', '/outbound/send', '/outbound//send', '/outbound/0/send', '/outbound/00/send',
    '/outbound/01/send', '/outbound/-1/send', '/outbound/+1/send', '/outbound/1.0/send',
    '/outbound/1e2/send', '/outbound/١/send', '/outbound/１/send', '/outbound/NaN/send',
    '/outbound/1/send/', '/outbound/1/send\n', '/outbound/1/send?confirm=1',
    '/outbound/1/send#fragment', '/outbound/1/child/send', '/outbound/1%2Fsend',
    '/outbound/%31/send', '/outbound/1/send-all', '/outbound/1/approve',
    '/outbound/1/request-approval', '/outbound/1/update', '/outbound/from-opportunity/1',
    '/OUTBOUND/1/send', '//outbound/1/send', '/prefix/outbound/1/send',
    '/settings/email', '/settings/email/spacemail/save', '/settings/email/spacemail/test',
    '/shipping-agent-messages/1/send', '/customer-campaigns/1/send/email',
    '/customer-campaigns/schedule', '/production-monitor/1/send-support',
    '/production-monitor/settings', '/commands/broadcast/1/send',
])
def test_nearby_paths_and_other_email_actions_do_not_inherit_exception(path):
    assert not is_manual_outbound_send('POST', path)
    assert not official_manual_send_without_stepup('POST', path, OFFICIAL)


@pytest.mark.parametrize('selected', [
    None, {}, {'provider': 'spacemail'},
    {key: value for key, value in OFFICIAL.items() if key != 'provider'},
    {key: value for key, value in OFFICIAL.items() if key != 'sender_email'},
    {key: value for key, value in OFFICIAL.items() if key != 'status'},
    {**OFFICIAL, 'provider': 'gmail'}, {**OFFICIAL, 'provider': 'Spacemail'},
    {**OFFICIAL, 'provider': 'spacemail '}, {**OFFICIAL, 'provider': None},
    {**OFFICIAL, 'sender_email': 'other@shodai.cc'},
    {**OFFICIAL, 'sender_email': 'afaq@other.invalid'},
    {**OFFICIAL, 'sender_email': 'AFAQ@shodai.cc'},
    {**OFFICIAL, 'sender_email': 'afaq@SHODAI.CC'},
    {**OFFICIAL, 'sender_email': ' afaq@shodai.cc'},
    {**OFFICIAL, 'sender_email': 'afaq@shodai.cc '},
    {**OFFICIAL, 'sender_email': 'Afaq <afaq@shodai.cc>'},
    {**OFFICIAL, 'sender_email': 'afaq@shodai.cc.evil.invalid'},
    {**OFFICIAL, 'sender_email': 'afaq@shodai.cc\r\nBcc: outsider@example.invalid'},
    {**OFFICIAL, 'sender_email': None},
    {**OFFICIAL, 'status': 'disconnected'}, {**OFFICIAL, 'status': 'pending'},
    {**OFFICIAL, 'status': 'Connected'}, {**OFFICIAL, 'status': None},
])
def test_mailbox_must_be_connected_exact_official_provider_and_sender(selected):
    assert not official_manual_send_without_stepup('POST', '/outbound/1/send', selected)


def test_policy_is_stateless_and_does_not_change_mailbox_or_grant_permissions():
    selected = dict(OFFICIAL)
    assert official_manual_send_without_stepup('POST', '/outbound/1/send', selected)
    assert selected == OFFICIAL
    assert not official_manual_send_without_stepup('POST', '/customer-campaigns/1/send/email', selected)
    assert not official_manual_send_without_stepup('POST', '/outbound/1/send', {**selected, 'sender_email': 'other@example.invalid'})
