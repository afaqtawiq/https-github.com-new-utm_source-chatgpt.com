"""Admin handoff HTTP contracts using synthetic provider identities only."""
import pytest
import httpx
from app import whatsapp_takeover_control as control
from app import whatsapp_inbox as inbox
from app import zernio_whatsapp as z
from test_whatsapp_inbox import setup, make_draft
from test_zernio_whatsapp import provider


@pytest.fixture
def handoff(setup, monkeypatch):
    client, current, provider_state, conn = setup
    state = {'paused': False, 'generation': 0, 'changes': []}
    def read(account, cid):
        return {'account_id': account, 'conversation_id': cid,
                'paused': state['paused'], 'generation': state['generation']}
    def change(account, cid, paused, actor, generation, *, sender):
        if generation != state['generation']:
            raise control.store.StateConflict('stale')
        state['changes'].append((account, cid, paused, actor, sender))
        state.update(paused=paused, generation=generation + 1)
        return read(account, cid)
    monkeypatch.setattr(control.store, 'read_state', read)
    monkeypatch.setattr(control.store, 'set_paused', change)
    monkeypatch.setattr(inbox, 'takeover_render', control.render)
    client.app.include_router(control.router)
    return client, current, provider_state, state


def fields(**changes):
    return dict(csrf='csrf', account='account-test', conversation='c1',
                sender='966500000001', generation='0', action='pause', **changes)


def test_explicit_pause_resume_state_and_scope(handoff):
    client, current, provider, state = handoff
    page = client.get('/whatsapp-inbox?conversation=c1')
    assert 'إيقاف الرد الآلي لهذه المحادثة' in page.text
    assert 'name="generation" value="0"' in page.text
    assert page.headers['cache-control'] == 'no-store'
    response = client.post('/whatsapp-inbox/takeover', data=fields(), follow_redirects=False)
    assert response.status_code == 303
    assert state['changes'] == [('account-test', 'c1', True, 7, '966500000001')]
    page = client.get('/whatsapp-inbox?conversation=c1')
    assert 'موقوف — يتولى الموظف المحادثة' in page.text
    assert 'استئناف الردود الآلية الجديدة' in page.text
    assert state['paused']  # A read cannot resume automation.
    data = fields(); data.update(action='resume', generation='1')
    assert client.post('/whatsapp-inbox/takeover', data=data, follow_redirects=False).status_code == 303
    assert not state['paused'] and state['generation'] == 2
    assert not provider['posts']


@pytest.mark.parametrize('field,value,status', [
    ('csrf', 'wrong', 403), ('account', 'other-account', 409),
    ('sender', '966500000002', 409), ('conversation', 'missing', 404),
    ('generation', '1', 409), ('generation', '-1', 400),
    ('generation', 'invalid', 400), ('action', 'toggle', 409),
])
def test_mutations_require_exact_verified_scope(handoff, field, value, status):
    client, current, provider, state = handoff
    data = fields(); data[field] = value
    assert client.post('/whatsapp-inbox/takeover', data=data).status_code == status
    assert not state['changes'] and not provider['posts']


@pytest.mark.parametrize('key,value,status', [('permission', False, 403), ('mfa', False, 428), ('role', 'viewer', 403)])
def test_existing_authority_required(handoff, key, value, status):
    client, current, provider, state = handoff
    current[key] = value
    assert client.post('/whatsapp-inbox/takeover', data=fields()).status_code == status
    assert not provider['gets'] and not state['changes']


@pytest.mark.parametrize('change', ['account', 'actor', 'mfa', 'participant'])
def test_revocation_during_provider_read_prevents_mutation(handoff, monkeypatch, change):
    client, current, provider, state = handoff
    def conversations(request):
        if change == 'account': monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID', 'other-account')
        elif change == 'actor': current['user_id'] = 8
        elif change == 'mfa': current['mfa'] = False
        else: provider['conversations'][0]['participantId'] = '966500000002'
        return httpx.Response(200, json={'data': provider['conversations'], 'pagination': {'hasMore': False}})
    provider['get_overrides']['/api/v1/inbox/conversations'] = conversations
    assert client.post('/whatsapp-inbox/takeover', data=fields()).status_code in (404, 409, 428, 503)
    assert not state['changes'] and not provider['posts']


def test_paused_conversation_still_allows_reviewed_manual_draft(handoff, monkeypatch):
    client, current, provider, state = handoff
    state.update(paused=True, generation=1)
    async def forbidden(*args):
        raise AssertionError('An authorized manual send must bypass automation admission')
    monkeypatch.setattr(z, 'automation_snapshot', forbidden)
    path = make_draft(client)
    response = client.post(path + '/send', data={'csrf': 'csrf', 'confirm': 'yes'})
    assert response.status_code == 200 and 'accepted' in response.text
    assert len(provider['posts']) == 1 and state['paused']
