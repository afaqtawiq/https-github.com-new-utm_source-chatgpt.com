"""Incremental conversation tests; preserve current staff routing, mock all I/O."""
import json
import sys
from types import SimpleNamespace
import httpx
from test_whatsapp_agent import setup, payload, tick, agent, store, privacy, REAL_UNDERSTAND

def test_natural_transport_worker_journey_retains_context_without_execution(setup, monkeypatch):
    bodies = []
    original_client = httpx.AsyncClient
    def model(request):
        bodies.append(json.loads(request.content))
        answer = 'ما نوع الحمولة ووزنها؟' if len(bodies) == 1 else 'سأحجز النقل.'
        return httpx.Response(200, json={'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': answer}]})
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-test-only')
    monkeypatch.setattr(privacy, 'understand', REAL_UNDERSTAND)
    monkeypatch.setattr(privacy.httpx, 'AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(model), **kw))
    for number, text in enumerate(('السلام عليكم', 'كم سعر النقل من الرياض إلى الدمام؟', 'ومن جدة؟'), 1):
        queued = agent.accept_inbound(payload(number, text))
        assert tick()
        assert store.get_job(queued['job_id'])['status'] == 'sent'
    assert len(bodies) == 2 and len(setup['sends']) == 3
    assert setup['sends'][-1][1] == 'تقصد من جدة إلى الدمام؟'
    assert all('tools' not in body for body in bodies)
    assert any('الرياض' in row['user'] for row in json.loads(bodies[-1]['messages'][0]['content'])['history'])
    assert not setup['provider_reads']


def test_incremental_context_preserves_claude_staff_routing(setup, monkeypatch):
    original = store.get_settings
    monkeypatch.setattr(store, 'get_settings', lambda account: dict(original(account), mode='routine'))
    team = SimpleNamespace(identify=lambda event: ('synthetic', {'manager': True}))
    monkeypatch.setitem(sys.modules, 'app.team', team)
    assert agent.accept_inbound(payload(71, 'خلينا نتكلم عن ترتيب الشغل')) == {
        'legacy_local_only': True, 'team_agent': True}
    voice = payload(72, '')
    voice['message']['attachments'] = [{'type': 'audio'}]
    assert agent.accept_inbound(voice) == {'legacy_local_only': True, 'team_agent': True}
    document = agent.accept_inbound(payload(73, 'لخص المستند', True))
    assert document and document.get('team_agent') is not True
    team.identify = lambda event: (None, None)
    customer = agent.accept_inbound(payload(74, 'ومن جدة؟'))
    assert customer and customer.get('team_agent') is not True
    assert not setup['sends'] and not setup['model_calls'] and not setup['provider_reads']
