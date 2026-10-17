"""Final provider boundary tests; no network or production data."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import httpx
import pytest
from app import zernio_whatsapp as z, whatsapp_takeover_control as control
from test_zernio_whatsapp import provider


@pytest.fixture
def protected(provider, monkeypatch):
    state = {'paused': True, 'generation': 1, 'guards': []}
    provider['conversations'] = [{'id': 'c1', 'accountId': 'account-test', 'platform': 'whatsapp', 'participantId': '966500000001'}]
    provider['messages'] = [{'direction': 'incoming', 'senderId': '966500000001', 'createdAt': datetime.now(timezone.utc).isoformat()}]
    provider['templates'] = [{'name': 'afaaq_transport_test', 'language': 'ar', 'status': 'APPROVED', 'components': [{'type': 'BODY', 'text': 'رسالة'}]}]
    def read(account, sender):
        return ({'conversation_id': 'c1', 'generation': state['generation'], 'paused': state['paused']}
                if sender == '966500000001' else None)
    @contextmanager
    def guard(account, cid, generation, *, sender):
        state['guards'].append((account, cid, generation, sender))
        yield sender != '966500000001' or (not state['paused'] and generation == state['generation'])
    monkeypatch.setattr(control.store, 'read_recipient_state', read)
    monkeypatch.setattr(control.store, 'send_guard', guard)
    monkeypatch.setattr(z, 'automation_snapshot', control.snapshot)
    monkeypatch.setattr(z, 'automation_guard', control.guard)
    return provider, state


@pytest.mark.parametrize('window', [True, False])
def test_paused_legacy_direct_send_cannot_fall_back_to_template(protected, window):
    provider, state = protected
    if not window: provider['messages'] = []
    with pytest.raises(z.WhatsAppBlocked):
        asyncio.run(z.send('+966500000001', 'رسالة'))
    assert not provider['posts'] and len(state['guards']) == 1


def test_other_conversation_continues(protected):
    provider, state = protected
    asyncio.run(z.send('+966500000002', 'رسالة'))
    assert len(provider['posts']) == 1
    assert provider['posts'][0]['participantId'] == '966500000002'
    assert state['paused']


@pytest.mark.parametrize('resume', [False, True])
def test_pause_during_preflight_invalidates_send_even_after_resume(protected, resume):
    provider, state = protected
    state.update(paused=False, generation=0)
    def messages(request):
        state.update(paused=not resume, generation=2 if resume else 1)
        return httpx.Response(200, json={'messages': provider['messages']})
    provider['get_overrides']['/api/v1/inbox/conversations/c1/messages'] = messages
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(z.send('+966500000001', 'رسالة'))
    assert not provider['posts']
    assert state['guards'][0][2] == 0


def test_old_legacy_origin_does_not_adopt_resumed_generation(protected):
    provider, state = protected
    state.update(paused=False, generation=2)
    async def send():
        with z.automation_origin('account-test', '+966500000001', 0):
            await z.send('+966500000001', 'رسالة')
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(send())
    assert not provider['posts'] and state['guards'][0][2] == 0


def test_manual_context_is_reset_after_authorized_send(protected):
    provider, state = protected
    async def send():
        with z.manual_dispatch(), z.dispatch_guard(lambda: None):
            await z.send('+966500000001', 'رسالة')
        with pytest.raises(z.WhatsAppBlocked):
            await z.send('+966500000001', 'رسالة')
    asyncio.run(send())
    assert len(provider['posts']) == 1 and len(state['guards']) == 1


@pytest.mark.parametrize('outcome', ['http_error', 'missing_receipt'])
def test_uncertain_outcome_is_never_retried(protected, outcome):
    provider, state = protected
    state['paused'] = False
    if outcome == 'http_error': provider['send_status'] = 500
    else: provider['send_data'] = {'success': True, 'data': {}}
    with pytest.raises((httpx.HTTPStatusError, RuntimeError)):
        asyncio.run(z.send('+966500000001', 'رسالة'))
    assert len(provider['posts']) == 1 and len(state['guards']) == 1


def test_changed_thread_identity_blocks_before_post(protected):
    provider, state = protected
    state['paused'] = False
    provider['conversations'][0]['id'] = 'c2'
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(z.send('+966500000001', 'رسالة'))
    assert not provider['posts'] and not state['guards']


def test_ambiguous_recipient_state_fails_closed(protected, monkeypatch):
    provider, state = protected
    def ambiguous(*args): raise control.store.StateConflict('ambiguous')
    monkeypatch.setattr(control.store, 'read_recipient_state', ambiguous)
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(z.send('+966500000001', 'رسالة'))
    assert not provider['posts'] and not provider['gets']


def test_signed_paused_inbound_is_retained_without_new_or_legacy_reply(monkeypatch):
    """Execute the real receiver function without production storage imports."""
    import ast
    import hashlib
    import hmac
    import json
    import os
    from pathlib import Path
    from types import SimpleNamespace
    from fastapi.responses import JSONResponse
    tree = ast.parse(Path('app/zernio_receiver.py').read_text())
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in ('receive', 'valid_signature')]
    for node in selected: node.decorator_list = []
    retained = []
    def forbidden(*args): raise AssertionError('Paused inbound cannot reach either automatic reply lane')
    async def hold(payload):
        retained.append(payload['message']['id'])
        return {'held': True, 'generation': 1}
    namespace = dict(os=os, json=json, hmac=hmac, hashlib=hashlib, Request=object,
                     JSONResponse=JSONResponse, ensure_tables=lambda: None,
                     ensure_intake_tables=lambda: None, takeover_inbound=hold,
                     durable_inbound=forbidden, db=forbidden)
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<actual-receiver>', 'exec'), namespace)
    monkeypatch.setenv('ZERNIO_WEBHOOK_SECRET', 'synthetic-secret')
    monkeypatch.setenv('ZERNIO_API_KEY', 'synthetic-key')
    payload = {'id': 'event-test', 'event': 'message.received',
               'account': {'id': 'account-test', 'platform': 'whatsapp'},
               'conversation': {'id': 'c1'},
               'message': {'id': 'message-test', 'direction': 'incoming', 'text': 'Synthetic only'}}
    raw = json.dumps(payload).encode()
    async def body(): return raw
    request = SimpleNamespace(body=body, headers={'x-zernio-signature': hmac.new(b'synthetic-secret', raw, hashlib.sha256).hexdigest()})
    result = asyncio.run(namespace['receive'](request))
    assert result == {'ok': True, 'held_for_operator': True, 'automatic_retry_of_send': False}
    assert retained == ['message-test']
    request.headers['x-zernio-signature'] = 'invalid'
    result = asyncio.run(namespace['receive'](request))
    assert result.status_code == 401 and retained == ['message-test']


def test_automatic_document_send_obeys_pause_at_final_boundary(protected, monkeypatch):
    from app import whatsapp_inbox as inbox
    provider, state = protected
    monkeypatch.setattr(inbox, 'validate_pdf_locally', lambda content: None)
    async def send():
        with z.dispatch_guard(lambda: None):
            await z.send_document('+966500000001', b'%PDF-synthetic', 'synthetic.pdf',
                expected_account='account-test', expected_conversation='c1',
                idempotency_key='wa-document-' + 'a' * 64)
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(send())
    assert not provider['posts'] and len(state['guards']) == 1


def test_caller_authority_revoked_while_entering_takeover_fence_prevents_post(protected, monkeypatch):
    provider, state = protected
    state['paused'] = False
    permission = {'active': True, 'checks': 0}
    @contextmanager
    def guard(*args, **kwargs):
        # Simulates a lock wait across which the original authority is revoked.
        permission['active'] = False
        yield True
    monkeypatch.setattr(control.store, 'send_guard', guard)
    def authority():
        permission['checks'] += 1
        if not permission['active']: raise z.WhatsAppBlocked('Authority revoked')
    async def send():
        with z.dispatch_guard(authority):
            await z.send('+966500000001', 'رسالة')
    with pytest.raises(z.WhatsAppBlocked): asyncio.run(send())
    assert permission['checks'] == 2 and not provider['posts']


def test_legacy_direct_post_is_blocked_when_pause_wins_after_preparation(protected, monkeypatch):
    """Exercise actual receiver dispatch with only the legacy preparation stubbed."""
    import ast
    import hashlib
    import hmac
    import json
    import os
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool
    from urllib.parse import quote
    provider, state = protected
    tree = ast.parse(Path('app/zernio_receiver.py').read_text())
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in ('receive', 'valid_signature')]
    for node in selected:
        node.decorator_list = []
        if node.name == 'receive':
            for inner in node.body:
                if isinstance(inner, ast.FunctionDef) and inner.name == 'prepare_reply':
                    inner.body = ast.parse("return 'afaaq', {'message': 'Synthetic reply'}").body
    updates = []
    @contextmanager
    def database():
        yield SimpleNamespace(execute=lambda sql, args: updates.append(args))
    async def admitted(payload):
        return {'held': False, 'sender': '966500000001', 'generation': 0, 'conversation_id': 'c1'}
    monkeypatch.setitem(sys.modules, 'app.whatsapp_admin', SimpleNamespace(
        owner_sender=lambda p: None, admin_reply=None, is_admin_command=lambda text: False))
    namespace = dict(os=os, json=json, hmac=hmac, hashlib=hashlib, Request=object,
                     JSONResponse=JSONResponse, ensure_tables=lambda: None,
                     ensure_intake_tables=lambda: None, takeover_inbound=admitted,
                     durable_inbound=None, db=database, run_in_threadpool=run_in_threadpool,
                     httpx=httpx, quote=quote)
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), '<actual-legacy-receiver>', 'exec'), namespace)
    monkeypatch.setenv('ZERNIO_WEBHOOK_SECRET', 'synthetic-secret')
    monkeypatch.setenv('ZERNIO_API_KEY', 'synthetic-key')
    payload = {'id': 'event-test', 'event': 'message.received',
               'account': {'id': 'account-test', 'platform': 'whatsapp'},
               'conversation': {'id': 'c1'}, 'message': {'id': 'message-test', 'direction': 'incoming'}}
    raw = json.dumps(payload).encode()
    async def body(): return raw
    request = SimpleNamespace(body=body, headers={'x-zernio-signature': hmac.new(b'synthetic-secret', raw, hashlib.sha256).hexdigest()})
    def forbidden(*args, **kwargs): raise AssertionError('Legacy raw provider client must not be reached')
    monkeypatch.setattr(httpx, 'AsyncClient', forbidden)
    result = asyncio.run(namespace['receive'](request))
    assert result['state'] == 'blocked' and result['retry_automatically'] is False
    assert updates == [('blocked', 'event-test')] and not provider['posts']


def test_other_legacy_account_is_not_disabled(monkeypatch):
    from app import whatsapp_takeover_control as control
    monkeypatch.setattr(z, 'account_id', lambda: 'afaq-test')
    async def check():
        async with control.guard('other-test', 'other-thread', '', None):
            return True
    assert asyncio.run(check()) is True


def test_managed_legacy_account_switch_cannot_bypass_captured_fence(monkeypatch):
    from app import whatsapp_takeover_control as control
    monkeypatch.setattr(z, 'account_id', lambda: 'new-account')
    async def check():
        async with control.guard('old-account', 'thread', '966500000001', {'generation': 0}):
            pytest.fail('Must not dispatch after account switch')
    with pytest.raises(z.WhatsAppBlocked):
        asyncio.run(check())
