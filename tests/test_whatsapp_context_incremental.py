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
    monkeypatch.setenv('WHATSAPP_NATURAL_REPLIES', '0')  # exercises the guarded path itself
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
    assert document == {'legacy_local_only': True, 'team_agent': True}  # staff PDFs -> team lane (billing)
    team.identify = lambda event: (None, None)
    customer = agent.accept_inbound(payload(74, 'ومن جدة؟'))
    assert customer and customer.get('team_agent') is not True
    assert not setup['sends'] and not setup['model_calls'] and not setup['provider_reads']


def test_routine_customer_messages_get_natural_replies_with_context(setup, monkeypatch):
    """Owner, 24 Nov 2026: greetings, requests and unclear messages from customers are understood in context and
    answered naturally, not with canned gate replies. Sensitive text still never reaches the model."""
    from test_whatsapp_agent import ACCOUNT
    store.update_settings(ACCOUNT, mode='routine', acceptance={'direct_owner_activation': True,
                          'owner_receipt_confirmed': True, 'confirmed_by': 'test-owner'})
    monkeypatch.setitem(sys.modules, 'app.team', SimpleNamespace(identify=lambda event: (None, None)))
    seen = []
    from app import whatsapp_natural

    async def natural(question, history=()):
        seen.append((question, [h['question'] for h in history]))
        return 'رد طبيعي ' + str(len(seen))
    monkeypatch.setattr(whatsapp_natural, 'reply', natural)
    for number, text in enumerate(('السلام عليكم', 'ارسل لي عرض سعر تخليص حاوية', 'شكرا'), 81):
        queued = agent.accept_inbound(payload(number, text))
        assert tick()
        got = store.get_job(queued['job_id'])
        assert got['status'] == 'sent', (got['status'], got['diagnostics'], queued)
    assert [q for q, _ in seen] == ['السلام عليكم', 'ارسل لي عرض سعر تخليص حاوية', 'شكرا']
    assert seen[-1][1] == ['السلام عليكم', 'ارسل لي عرض سعر تخليص حاوية']  # earlier turns kept as context
    assert [s[1] for s in setup['sends']] == ['رد طبيعي 1', 'رد طبيعي 2', 'رد طبيعي 3']
    secret = agent.accept_inbound(payload(90, 'كلمة المرور حقتي 12345678 للدخول'))
    assert tick()
    assert len(seen) == 3 and 'conversation_text' not in store.get_job(secret['job_id'])['payload']
