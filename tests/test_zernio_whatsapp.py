import asyncio
from datetime import datetime, timezone
import json

import httpx
import pytest

from app import zernio_whatsapp as z


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID', 'account-test')
    monkeypatch.delenv('ZERNIO_WHATSAPP_ACCOUNT_ID', raising=False)
    state = {'posts': [], 'templates': [], 'messages': [], 'conversations': [], 'active': True,
             'send_status': 200, 'send_data': {'success': True, 'data': {'messageId': 'wamid-test'}}}
    def handle(request):
        if request.method == 'POST':
            state['posts'].append(json.loads(request.content))
            return httpx.Response(state['send_status'], json=state['send_data'])
        if request.url.path.endswith('/accounts'):
            result = {'accounts': [{'_id': 'account-test', 'platform': 'whatsapp', 'isActive': state['active']}]}
        elif request.url.path.endswith('/templates'):
            result = {'templates': state['templates']}
        elif request.url.path.endswith('/messages'):
            result = {'messages': state['messages']}
        else:
            result = {'data': state['conversations'], 'pagination': {'hasMore': False}}
        return httpx.Response(200, json=result)
    monkeypatch.setattr(z, 'client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    return state


def test_pending_template_never_sends(provider):
    provider['templates'] = [{'name': 'afaaq_transport_test', 'language': 'ar', 'status': 'PENDING',
                              'components': [{'type': 'BODY', 'text': 'المسار {{1}}'}]}]
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(z.send('+966500000001', 'المسار جدة'))
    assert provider['posts'] == []


def test_approved_template_preserves_exact_offer(provider):
    provider['templates'] = [{'name': 'afaaq_transport_test', 'language': 'ar', 'status': 'APPROVED',
                              'components': [{'type': 'BODY', 'text': 'المسار {{1}} إلى {{2}}، من {{1}}'}]}]
    result = asyncio.run(z.send('+966500000001', 'المسار جدة إلى دبي، من جدة'))
    assert result['messages'][0]['id'] == 'wamid-test'
    assert provider['posts'][0]['templateParams'] == ['جدة', 'دبي']
    assert provider['posts'][0]['participantId'] == '966500000001'
    assert 'message' not in provider['posts'][0]


def test_template_mismatch_blocks(provider):
    provider['templates'] = [{'name': 'afaaq_transport_test', 'language': 'ar', 'status': 'APPROVED',
                              'components': [{'type': 'BODY', 'text': 'السعر 2000 ريال'}]}]
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(z.send('+966500000001', 'السعر 1850 ريال'))
    assert not provider['posts']


@pytest.mark.parametrize('direction,age', [('outgoing', 0), ('incoming', 2)])
def test_only_recent_inbound_opens_window(provider, direction, age):
    from datetime import timedelta
    provider['conversations'] = [{'id': 'c1', 'accountId': 'account-test', 'platform': 'whatsapp', 'participantId': '966500000001'}]
    provider['messages'] = [{'direction': direction, 'senderId': '966500000001',
                             'createdAt': (datetime.now(timezone.utc) - timedelta(days=age)).isoformat()}]
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(z.send('+966500000001', 'رسالة'))
    assert not provider['posts']


def test_active_session_sends_text(provider):
    provider['conversations'] = [{'id': 'c1', 'accountId': 'account-test', 'platform': 'whatsapp', 'participantId': '966500000001'}]
    provider['messages'] = [{'direction': 'incoming', 'senderId': '966500000001', 'createdAt': datetime.now(timezone.utc).isoformat()}]
    asyncio.run(z.send('+966500000001', 'رسالة'))
    assert provider['posts'] == [{'accountId': 'account-test', 'message': 'رسالة'}]


def test_wrong_or_inactive_account_never_sends(provider):
    provider['active'] = False
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(z.send('+966500000001', 'رسالة'))
    assert not provider['posts']


@pytest.mark.parametrize('status', [408, 409, 500, 502])
def test_ambiguous_post_not_classified_as_safe_retry(provider, status):
    provider['templates'] = [{'name': 'afaaq_transport_test', 'language': 'ar', 'status': 'APPROVED',
                              'components': [{'type': 'BODY', 'text': 'رسالة'}]}]
    provider['send_status'] = status
    with pytest.raises(httpx.HTTPStatusError): asyncio.run(z.send('+966500000001', 'رسالة'))
    assert len(provider['posts']) == 1


def test_missing_receipt_is_uncertain(provider):
    provider['templates'] = [{'name': 'afaaq_transport_test', 'language': 'ar', 'status': 'APPROVED',
                              'components': [{'type': 'BODY', 'text': 'رسالة'}]}]
    provider['send_data'] = {'success': True, 'data': {}}
    with pytest.raises(RuntimeError) as caught: asyncio.run(z.send('+966500000001', 'رسالة'))
    assert not isinstance(caught.value, z.WhatsAppBlocked)
    assert len(provider['posts']) == 1


@pytest.mark.parametrize('test_mode', [False, True])
def test_short_owner_inquiry_requires_matching_new_approved_template(provider, test_mode):
    from app.transport_owner import inquiry
    from app.transport_test import DISCLAIMER
    name = 'afaaq_transport_test_owner_inquiry_v1_ar' if test_mode else 'afaaq_transport_owner_inquiry_v3_ar'
    specs = z.required_templates()
    template = next(t for t in specs if t['name'] == name)
    message = (DISCLAIMER + '\n' if test_mode else '') + inquiry('جدة', 'الشارقة')
    legacy = next(t for t in specs if t['name'] == 'afaaq_transport_owner_inquiry_v2_ar')
    provider['templates'] = [{**legacy,'status':'APPROVED'}, {**template,'status':'PENDING'}]
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(z.send('+966500000001', message))
    assert not provider['posts']
    provider['templates'][1]['status'] = 'APPROVED'
    asyncio.run(z.send('+966500000001', message))
    assert provider['posts'][0]['templateName'] == name
    assert provider['posts'][0]['templateParams'] == ['جدة','الشارقة']


def test_legacy_owner_template_still_exact_matches(provider):
    legacy = next(t for t in z.required_templates() if t['name'] == 'afaaq_transport_owner_inquiry_v2_ar')
    provider['templates'] = [{**legacy,'status':'APPROVED'}]
    message = legacy['components'][0]['text'].replace('{{1}}','رابغ').replace('{{2}}','دبي')
    asyncio.run(z.send('+966500000001', message))
    assert provider['posts'][0]['templateName'] == legacy['name']
    assert provider['posts'][0]['templateParams'] == ['رابغ','دبي']
