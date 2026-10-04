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
    state = {'posts': [], 'gets': [], 'clients': [], 'templates': [], 'messages': [], 'conversations': [], 'active': True,
             'get_overrides': {}, 'get_headers': {}, 'send_headers': {},
             'send_status': 200, 'send_data': {'success': True, 'data': {'messageId': 'wamid-test'}}}
    def handle(request):
        if request.method == 'POST':
            state['posts'].append(json.loads(request.content))
            return httpx.Response(state['send_status'], json=state['send_data'], headers=state['send_headers'])
        state['gets'].append(str(request.url))
        override = state['get_overrides'].get(request.url.path)
        if override is not None:
            return override(request)
        if request.url.path.endswith('/accounts'):
            result = {'accounts': [{'_id': 'account-test', 'platform': 'whatsapp', 'isActive': state['active']}]}
        elif request.url.path.endswith('/templates'):
            result = {'templates': state['templates']}
        elif request.url.path.endswith('/messages'):
            result = {'messages': state['messages']}
        else:
            result = {'data': state['conversations'], 'pagination': {'hasMore': False}}
        return httpx.Response(200, json=result, headers=state['get_headers'].get(request.url.path, {}))
    def make_client():
        result = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        state['clients'].append(result)
        return result
    monkeypatch.setattr(z, 'client', make_client)
    return state


@pytest.fixture
def fake_clock(monkeypatch):
    state = {'now': 1_800_000_000.0, 'sleeps': []}
    async def sleep(delay):
        state['sleeps'].append(delay)
        state['now'] += delay
    monkeypatch.setattr(z, '_sleep', sleep)
    monkeypatch.setattr(z, '_wall_time', lambda: state['now'])
    monkeypatch.setattr(z, '_monotonic', lambda: state['now'])
    return state


def approve_message(provider):
    provider['templates'] = [{'name': 'afaaq_transport_test', 'language': 'ar', 'status': 'APPROVED',
                              'components': [{'type': 'BODY', 'text': 'رسالة'}]}]


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
    from app.transport_owner import short_inquiry
    from app.transport_test import DISCLAIMER
    name = 'afaaq_transport_test_owner_inquiry_v1_ar' if test_mode else 'afaaq_transport_owner_inquiry_v3_ar'
    specs = z.required_templates()
    template = next(t for t in specs if t['name'] == name)
    message = (DISCLAIMER + '\n' if test_mode else '') + short_inquiry('جدة', 'الشارقة')
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


def test_real_owner_inquiry_uses_existing_v2_with_route_only_parameters(provider):
    from app.transport_owner import inquiry
    provider['templates'] = [{**t, 'status': 'APPROVED'} for t in z.required_templates()]
    asyncio.run(z.send('+966500000001', inquiry('جدة', 'دبي')))
    assert provider['posts'] == [{'accountId': 'account-test', 'participantId': '966500000001',
        'templateName': 'afaaq_transport_owner_inquiry_v2_ar', 'templateLanguage': 'ar',
        'templateParams': ['جدة', 'دبي']}]


@pytest.mark.parametrize('problem', ['missing', 'pending', 'body_changed'])
def test_real_owner_inquiry_never_substitutes_incomplete_or_unapproved_template(provider, problem):
    from app.transport_owner import inquiry
    specs = z.required_templates()
    provider['templates'] = [{**t, 'status': 'APPROVED'} for t in specs
                             if t['name'] != 'afaaq_transport_owner_inquiry_v2_ar']
    if problem != 'missing':
        template = next(t for t in specs if t['name'] == 'afaaq_transport_owner_inquiry_v2_ar')
        template = {**template, 'status': 'PENDING' if problem == 'pending' else 'APPROVED'}
        if problem == 'body_changed':
            template['components'][0]['text'] = template['components'][0]['text'].replace('ووزنها الفعلي ', '')
        provider['templates'].append(template)
    with pytest.raises(z.WhatsAppBlocked):
        asyncio.run(z.send('+966500000001', inquiry('جدة', 'دبي')))
    assert not provider['posts']  # No send, automatic registration, or fallback.


@pytest.mark.parametrize('problem', ['widened_v2', 'generic_alternative', 'extra_component', 'changed_fixed_whitespace'])
def test_real_owner_template_requires_literal_v2_schema(provider, problem):
    from app.transport_owner import inquiry
    template = next(t for t in z.required_templates() if t['name'] == 'afaaq_transport_owner_inquiry_v2_ar')
    template['status'] = 'APPROVED'
    if problem == 'widened_v2':
        template['components'] = [{'type': 'BODY', 'text': 'السلام عليكم، {{1}}'}]
    elif problem == 'generic_alternative':
        template['name'] = 'afaaq_transport_generic_ar'
        template['components'] = [{'type': 'BODY', 'text': '{{1}}'}]
    elif problem == 'extra_component':
        template['components'].append({'type': 'FOOTER', 'text': ''})
    else:
        template['components'][0]['text'] = ' '.join(template['components'][0]['text'].split())
    # The old fuzzy matcher accepted all four and would submit a changed schema.
    assert z.template_parameters(template, inquiry('رابغ', 'دبي')) is not None
    provider['templates'] = [template]
    with pytest.raises(z.WhatsAppBlocked):
        asyncio.run(z.send('+966500000001', inquiry('رابغ', 'دبي')))
    assert not provider['posts']


def test_recent_recipient_window_preserves_complete_real_owner_inquiry(provider):
    from app.transport_owner import inquiry
    provider['conversations'] = [{'id': 'c1', 'accountId': 'account-test', 'platform': 'whatsapp',
                                  'participantId': '966500000001'}]
    provider['messages'] = [{'direction': 'incoming', 'senderId': '966500000001',
                             'createdAt': datetime.now(timezone.utc).isoformat()}]
    message = inquiry('جدة', 'دبي')
    asyncio.run(z.send('+966500000001', message))
    assert provider['posts'] == [{'accountId': 'account-test', 'message': message}]


@pytest.mark.parametrize('status', [401, 403, 400, 404])
def test_get_permanent_errors_never_retry_or_post(provider, fake_clock, status, caplog):
    provider['get_overrides']['/api/v1/accounts'] = lambda request: httpx.Response(
        status, json={'error': 'secret-token recipient-966500000001'},
        headers={'X-RateLimit-Limit': '60', 'X-RateLimit-Remaining': '0', 'Retry-After': 'secret-token'})
    with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
        asyncio.run(z.send('+966500000001', 'رسالة'))
    error = caught.value
    assert isinstance(error, z.WhatsAppBlocked)
    assert error.retryable is False
    assert error.diagnostic['retryable'] is False
    assert error.diagnostic['phase'] == 'preflight'
    assert error.diagnostic['endpoint'] == 'accounts'
    assert error.diagnostic['http_status'] == status
    assert error.diagnostic['error_category'] == ('authentication' if status in (401, 403) else 'http_error')
    assert error.diagnostic['attempts'] == 1
    assert 'secret-token' not in str(error.diagnostic) + str(error) + caplog.text
    assert '966500000001' not in str(error.diagnostic) + str(error) + caplog.text
    assert len(provider['gets']) == 1
    assert provider['posts'] == []
    assert fake_clock['sleeps'] == []


@pytest.mark.parametrize('failure,category,status', [
    ('429', 'rate_limited', 429), ('500', 'server_error', 500), ('503', 'server_error', 503),
    ('timeout', 'timeout', None), ('network', 'network_error', None),
    ('json', 'invalid_json', 200), ('array', 'invalid_json', 200),
])
def test_get_transient_errors_retry_only_three_times(provider, fake_clock, failure, category, status, caplog):
    def fail(request):
        if failure == 'timeout': raise httpx.ReadTimeout('secret-token', request=request)
        if failure == 'network': raise httpx.ConnectError('secret-token', request=request)
        if failure == 'json': return httpx.Response(200, text='secret-token')
        if failure == 'array': return httpx.Response(200, json=['secret-token'])
        return httpx.Response(int(failure), json={'error': 'secret-token'})
    provider['get_overrides']['/api/v1/accounts'] = fail
    with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
        asyncio.run(z.send('+966500000001', 'رسالة'))
    assert caught.value.retryable is True
    assert caught.value.diagnostic['error_category'] == category
    assert caught.value.diagnostic['http_status'] == status
    assert caught.value.diagnostic['attempts'] == 3
    assert len(provider['gets']) == 3
    assert provider['posts'] == []
    assert fake_clock['sleeps'] == [1, 2]
    assert 'secret-token' not in str(caught.value.diagnostic) + str(caught.value) + caplog.text


def test_rate_limited_get_recovers_using_retry_after(provider, fake_clock):
    approve_message(provider)
    attempts = []
    def accounts(request):
        attempts.append(fake_clock['now'])
        if len(attempts) == 1:
            return httpx.Response(429, headers={'Retry-After': '7', 'X-RateLimit-Remaining': '0'})
        return httpx.Response(200, json={'accounts': [{'_id': 'account-test', 'platform': 'whatsapp', 'isActive': True}]})
    provider['get_overrides']['/api/v1/accounts'] = accounts
    asyncio.run(z.send('+966500000001', 'رسالة'))
    assert attempts[1] - attempts[0] == 7
    assert fake_clock['sleeps'] == [7]
    assert len(provider['posts']) == 1


def test_exhausted_header_waits_before_next_get(provider, fake_clock):
    approve_message(provider)
    provider['get_headers']['/api/v1/accounts'] = {
        'X-RateLimit-Limit': '60', 'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': str(fake_clock['now'] + 4)}
    seen = []
    def conversations(request):
        seen.append(fake_clock['now'])
        return httpx.Response(200, json={'data': []})
    provider['get_overrides']['/api/v1/inbox/conversations'] = conversations
    start = fake_clock['now']
    asyncio.run(z.send('+966500000001', 'رسالة'))
    assert seen == [start + 4]
    assert fake_clock['sleeps'] == [4]
    assert len(provider['posts']) == 1


def test_template_rate_gate_runs_before_dispatch_guard(provider, fake_clock):
    approve_message(provider)
    start = fake_clock['now']
    provider['get_headers']['/api/v1/whatsapp/templates'] = {
        'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': str(start + 9), 'Retry-After': '5'}
    seen = []
    async def guard():
        seen.append((fake_clock['now'], len(provider['posts'])))
    async def run():
        with z.dispatch_guard(guard):
            await z.send('+966500000001', 'رسالة')
    asyncio.run(run())
    assert seen == [(start + 9, 0)]
    assert fake_clock['sleeps'] == [9]
    assert len(provider['posts']) == 1


def test_guard_can_stop_send_after_backoff_and_exception_is_unchanged(provider, fake_clock):
    approve_message(provider)
    provider['get_headers']['/api/v1/whatsapp/templates'] = {'Retry-After': '8'}
    error = RuntimeError('caller stopped this dispatch')
    def guard():
        assert fake_clock['sleeps'] == [8]
        raise error
    async def run():
        with z.dispatch_guard(guard):
            await z.send('+966500000001', 'رسالة')
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(run())
    assert caught.value is error
    assert not isinstance(caught.value, z.WhatsAppPreflightBlocked)
    assert provider['posts'] == []
    assert z._dispatch_guard.get() is None


@pytest.mark.parametrize('status', [200, 429, 500])
def test_long_rate_wait_fails_closed_with_no_extra_request(provider, fake_clock, status):
    approve_message(provider)
    provider['get_overrides']['/api/v1/accounts'] = lambda request: httpx.Response(
        status, json={'accounts': [{'_id': 'account-test', 'platform': 'whatsapp', 'isActive': True}]},
        headers={'Retry-After': '120', 'X-RateLimit-Remaining': '0'})
    with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
        asyncio.run(z.send('+966500000001', 'رسالة'))
    assert caught.value.diagnostic['error_category'] == 'rate_wait_exceeds_budget'
    assert caught.value.retryable
    assert caught.value.diagnostic['retry_after_seconds'] == 120
    assert len(provider['gets']) == 1
    assert not provider['posts']
    assert not fake_clock['sleeps']


def test_retry_wait_budget_is_total_per_read(provider, fake_clock):
    provider['get_overrides']['/api/v1/accounts'] = lambda request: httpx.Response(429, headers={'Retry-After': '60'})
    with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
        asyncio.run(z.send('+966500000001', 'رسالة'))
    assert caught.value.diagnostic['error_category'] == 'rate_wait_exceeds_budget'
    assert len(provider['gets']) == 2
    assert fake_clock['sleeps'] == [60]
    assert provider['posts'] == []


def test_batch_cache_shares_client_and_refreshes_after_thirty_seconds(provider, fake_clock):
    approve_message(provider)
    async def run():
        async with z.transport_batch():
            await z.send('+966500000001', 'رسالة')
            await z.send('+966500000002', 'رسالة')
            assert len(provider['gets']) == 3
            assert len(provider['clients']) == 1
            fake_clock['now'] += 31
            await z.send('+966500000003', 'رسالة')
            assert len(provider['gets']) == 6
            assert not provider['clients'][0].is_closed
        assert provider['clients'][0].is_closed
        await z.send('+966500000004', 'رسالة')
    asyncio.run(run())
    assert len(provider['gets']) == 9
    assert len(provider['clients']) == 2
    assert len(provider['posts']) == 4


def test_empty_batch_never_constructs_client(monkeypatch):
    def fail(): raise AssertionError('empty/mocked batch must stay lazy')
    monkeypatch.setattr(z, 'client', fail)
    async def run():
        async with z.transport_batch():
            pass
    asyncio.run(run())


def test_batch_cache_does_not_reuse_another_account(provider, fake_clock, monkeypatch):
    approve_message(provider)
    async def run():
        async with z.transport_batch():
            await z.send('+966500000001', 'رسالة')
            monkeypatch.setenv('ZERNIO_WHATSAPP_ACCOUNT_ID', 'different-account')
            with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
                await z.send('+966500000002', 'رسالة')
            assert caught.value.diagnostic['error_category'] == 'account_changed'
            assert caught.value.retryable is False
    asyncio.run(run())
    assert len(provider['clients']) == 1
    assert len(provider['gets']) == 3
    assert len(provider['posts']) == 1


def test_batch_window_is_per_target_and_messages_are_never_cached(provider, fake_clock):
    provider['conversations'] = [
        {'id': 'c1', 'accountId': 'account-test', 'platform': 'whatsapp', 'participantId': '966500000001'},
        {'id': 'c2', 'accountId': 'account-test', 'platform': 'whatsapp', 'participantId': '966500000002'},
    ]
    provider['messages'] = [{'direction': 'incoming', 'senderId': '966500000001', 'createdAt': datetime.now(timezone.utc).isoformat()}]
    async def run():
        async with z.transport_batch():
            await z.send('+966500000001', 'رسالة')
            with pytest.raises(z.WhatsAppBlocked):
                await z.send('+966500000002', 'رسالة')
            provider['messages'] = []
            with pytest.raises(z.WhatsAppBlocked):
                await z.send('+966500000001', 'رسالة')
    asyncio.run(run())
    assert len([u for u in provider['gets'] if '/messages?' in u]) == 3
    assert len([u for u in provider['gets'] if '/conversations?' in u]) == 1
    assert len(provider['posts']) == 1


@pytest.mark.parametrize('status', [400, 401, 403, 429])
def test_explicit_post_rejections_never_become_preflight_or_retry(provider, fake_clock, status):
    approve_message(provider)
    provider['send_status'] = status
    provider['send_headers'] = {'Retry-After': '10'}
    with pytest.raises(z.WhatsAppBlocked) as caught:
        asyncio.run(z.send('+966500000001', 'رسالة'))
    assert not isinstance(caught.value, z.WhatsAppPreflightBlocked)
    assert len(provider['posts']) == 1
    assert fake_clock['sleeps'] == []


def test_post_rate_headers_apply_before_next_cached_batch_send(provider, fake_clock):
    approve_message(provider)
    provider['send_headers'] = {'X-RateLimit-Remaining': '0', 'Retry-After': '10'}
    seen = []
    start = fake_clock['now']
    def guard(): seen.append(fake_clock['now'])
    async def run():
        async with z.transport_batch():
            with z.dispatch_guard(guard):
                await z.send('+966500000001', 'رسالة')
                await z.send('+966500000002', 'رسالة')
    asyncio.run(run())
    assert seen == [start, start + 10]
    assert len(provider['gets']) == 3
    assert len(provider['posts']) == 2
    assert fake_clock['sleeps'] == [10]


def test_batch_has_shared_wait_budget(provider, fake_clock, monkeypatch):
    approve_message(provider)
    monkeypatch.setattr(z, '_BATCH_WAIT_BUDGET_SECONDS', 15)
    provider['send_headers'] = {'Retry-After': '10'}
    async def run():
        async with z.transport_batch():
            await z.send('+966500000001', 'رسالة')
            await z.send('+966500000002', 'رسالة')
            with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
                await z.send('+966500000003', 'رسالة')
            assert caught.value.diagnostic['error_category'] == 'batch_wait_exceeds_budget'
    asyncio.run(run())
    assert len(provider['posts']) == 2
    assert fake_clock['sleeps'] == [10]


def test_batch_has_total_elapsed_budget(provider, fake_clock):
    approve_message(provider)
    async def run():
        async with z.transport_batch():
            await z.send('+966500000001', 'رسالة')
            fake_clock['now'] += z._BATCH_BUDGET_SECONDS
            with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
                await z.send('+966500000002', 'رسالة')
            assert caught.value.diagnostic['error_category'] == 'batch_budget_exhausted'
    asyncio.run(run())
    assert len(provider['posts']) == 1
    assert len(provider['gets']) == 3


@pytest.mark.parametrize('advance_in_guard', [False, True])
def test_freeform_window_is_rechecked_after_all_waits(provider, fake_clock, monkeypatch, advance_in_guard):
    from datetime import timedelta
    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(fake_clock['now'], timezone.utc)
    monkeypatch.setattr(z, 'datetime', ClockDateTime)
    provider['conversations'] = [{'id': 'c1', 'accountId': 'account-test', 'platform': 'whatsapp', 'participantId': '966500000001'}]
    provider['messages'] = [{'direction': 'incoming', 'senderId': '966500000001',
                             'createdAt': (ClockDateTime.now() - timedelta(hours=23, minutes=54, seconds=58)).isoformat()}]
    if not advance_in_guard:
        provider['get_headers']['/api/v1/inbox/conversations/c1/messages'] = {'Retry-After': '5'}
    async def guard():
        if advance_in_guard:
            fake_clock['now'] += 5
    async def run():
        with z.dispatch_guard(guard):
            await z.send('+966500000001', 'رسالة')
    with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
        asyncio.run(run())
    assert caught.value.diagnostic['error_category'] == 'conversation_window_expired'
    assert caught.value.retryable is False
    assert provider['posts'] == []


def test_conversation_page_cache_is_keyed_by_cursor(provider, fake_clock):
    approve_message(provider)
    cursors = []
    def conversations(request):
        cursor = request.url.params.get('cursor')
        cursors.append(cursor)
        if cursor is None:
            return httpx.Response(200, json={'data': [], 'pagination': {'hasMore': True, 'nextCursor': 'page-2'}})
        return httpx.Response(200, json={'data': [], 'pagination': {'hasMore': False}})
    provider['get_overrides']['/api/v1/inbox/conversations'] = conversations
    async def run():
        async with z.transport_batch():
            await z.send('+966500000001', 'رسالة')
            await z.send('+966500000002', 'رسالة')
    asyncio.run(run())
    assert cursors == [None, 'page-2']
    assert len(provider['posts']) == 2


def test_retry_after_http_date(provider, fake_clock):
    from email.utils import format_datetime
    approve_message(provider)
    retry_date = format_datetime(datetime.fromtimestamp(fake_clock['now'] + 6, timezone.utc), usegmt=True)
    provider['get_headers']['/api/v1/whatsapp/templates'] = {'Retry-After': retry_date}
    asyncio.run(z.send('+966500000001', 'رسالة'))
    assert fake_clock['sleeps'] == [6]
    assert len(provider['posts']) == 1


@pytest.mark.parametrize('failure', ['timeout', 'network', 'json'])
def test_post_transport_failure_never_becomes_preflight_or_retries(provider, fake_clock, monkeypatch, failure):
    approve_message(provider)
    original_client = z.client
    posts = []
    def make_client():
        c = original_client()
        async def post(*args, **kwargs):
            posts.append(kwargs)
            if failure == 'timeout': raise httpx.ReadTimeout('POST timeout')
            if failure == 'network': raise httpx.ConnectError('POST connection failure')
            return httpx.Response(200, content=b'not json', request=httpx.Request('POST', z.BASE + '/inbox/conversations'))
        c.post = post
        return c
    monkeypatch.setattr(z, 'client', make_client)
    with pytest.raises((httpx.HTTPError, z.WhatsAppSendUncertain)) as caught:
        asyncio.run(z.send('+966500000001', 'رسالة'))
    assert not isinstance(caught.value, z.WhatsAppPreflightBlocked)
    if failure == 'json':
        assert caught.value.http_status == 200
    assert len(posts) == 1
    assert fake_clock['sleeps'] == []


def test_response_status_is_exposed_without_provider_body(provider):
    approve_message(provider)
    result = asyncio.run(z.send('+966500000001', 'رسالة'))
    assert result['http_status'] == 200
    provider['send_status'] = 429
    with pytest.raises(z.WhatsAppBlocked) as caught:
        asyncio.run(z.send('+966500000002', 'رسالة'))
    assert caught.value.http_status == 429
    assert not isinstance(caught.value, z.WhatsAppPreflightBlocked)


def test_overslept_rate_gate_does_not_post(provider, fake_clock, monkeypatch):
    approve_message(provider)
    provider['get_headers']['/api/v1/whatsapp/templates'] = {'Retry-After': '1'}
    async def oversleep(delay):
        fake_clock['now'] += 100
    monkeypatch.setattr(z, '_sleep', oversleep)
    with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
        asyncio.run(z.send('+966500000001', 'رسالة'))
    assert caught.value.diagnostic['error_category'] == 'read_budget_exhausted'
    assert provider['posts'] == []


def test_remaining_zero_without_reset_waits_conservatively(provider, fake_clock):
    approve_message(provider)
    provider['get_headers']['/api/v1/whatsapp/templates'] = {'X-RateLimit-Remaining': '0'}
    asyncio.run(z.send('+966500000001', 'رسالة'))
    assert fake_clock['sleeps'] == [60]
    assert len(provider['posts']) == 1


def test_failed_read_diagnostic_never_exposes_conversation_or_header_text(provider, fake_clock, caplog):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
                503, text='private-message api-key', headers={
                    'X-RateLimit-Limit': 'nan', 'X-RateLimit-Remaining': 'api-key',
                    'X-RateLimit-Reset': 'inf', 'Retry-After': 'private-message'}))) as c:
            await z.read(c, '/inbox/conversations/private-conversation/messages', {'accountId': 'private-account'})
    with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
        asyncio.run(run())
    assert caught.value.diagnostic == {
        'phase': 'preflight', 'endpoint': 'conversation_messages', 'http_status': 503,
        'error_category': 'server_error', 'attempts': 3, 'retryable': True}
    logged = str(caught.value.diagnostic) + str(caught.value) + caplog.text
    assert not any(secret in logged for secret in ['private-message', 'api-key', 'private-account', 'private-conversation'])


@pytest.mark.parametrize('seconds,category', [(91, 'read_budget_exhausted'), (301, 'batch_budget_exhausted')])
def test_slow_dispatch_guard_cannot_send_after_deadline(provider, fake_clock, seconds, category):
    approve_message(provider)
    async def guard():
        fake_clock['now'] += seconds
    async def run():
        with z.dispatch_guard(guard):
            await z.send('+966500000001', 'رسالة')
    with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
        asyncio.run(run())
    assert caught.value.diagnostic['error_category'] == category
    assert provider['posts'] == []


@pytest.mark.parametrize('payload', [
    [], 'private-message', None,
    {'success': True, 'data': []}, {'success': True, 'data': 'private-message'},
    {'success': True, 'data': {}},
    {'success': True, 'data': {'messageId': 'wamid-test', 'partialFailure': True}},
    {'success': True, 'data': {'messageId': {'private-message': True}}},
    {'success': True, 'data': {'messageId': '  '}},
])
def test_ambiguous_post_response_preserves_only_status_and_never_retries(provider, fake_clock, payload):
    approve_message(provider)
    provider['send_data'] = payload
    with pytest.raises(z.WhatsAppSendUncertain) as caught:
        asyncio.run(z.send('+966500000001', 'رسالة'))
    assert caught.value.http_status == 200
    assert not isinstance(caught.value, z.WhatsAppBlocked)
    assert 'private-message' not in str(caught.value)
    assert len(provider['posts']) == 1
    assert fake_clock['sleeps'] == []


@pytest.mark.parametrize('status', [401, 403])
def test_batch_auth_failure_clears_cache_and_stops_all_later_io(provider, fake_clock, status):
    approve_message(provider)
    provider['conversations'] = [
        {'id': 'c2', 'accountId': 'account-test', 'platform': 'whatsapp', 'participantId': '966500000002'},
    ]
    provider['get_overrides']['/api/v1/inbox/conversations/c2/messages'] = lambda request: httpx.Response(status)
    async def run():
        async with z.transport_batch() as batch:
            await z.send('+966500000001', 'رسالة')
            assert len(provider['gets']) == 3
            assert batch.cache
            with pytest.raises(z.WhatsAppPreflightBlocked) as caught:
                await z.send('+966500000002', 'رسالة')
            assert caught.value.diagnostic['http_status'] == status
            assert caught.value.diagnostic['error_category'] == 'authentication'
            assert caught.value.retryable is False
            assert not batch.cache
            assert not batch.windows
            assert len(provider['gets']) == 4
            assert len(provider['posts']) == 1
            with pytest.raises(z.WhatsAppPreflightBlocked) as later:
                await z.send('+966500000003', 'رسالة')
            assert later.value.diagnostic == caught.value.diagnostic
            assert len(provider['gets']) == 4
            assert len(provider['posts']) == 1
            # Direct reads on the same shared client also remain blocked.
            with pytest.raises(z.WhatsAppPreflightBlocked):
                await z.read(batch.client, '/accounts')
            assert len(provider['gets']) == 4
        # A fresh, independent send can verify authentication again.
        await z.send('+966500000003', 'رسالة')
    asyncio.run(run())
    assert len(provider['gets']) == 7
    assert len(provider['posts']) == 2
    assert fake_clock['sleeps'] == []
