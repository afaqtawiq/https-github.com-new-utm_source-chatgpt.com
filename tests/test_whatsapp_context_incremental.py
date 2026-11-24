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


def test_routine_photo_burst_gets_one_human_ack(setup, monkeypatch):
    """Owner, 24 Nov 2026: several photos from a customer -> one acknowledgement in the customer's language,
    never a failure notice per photo."""
    from test_whatsapp_agent import ACCOUNT
    store.update_settings(ACCOUNT, mode='routine', acceptance={'direct_owner_activation': True,
                          'owner_receipt_confirmed': True, 'confirmed_by': 'test-owner'})
    monkeypatch.setitem(sys.modules, 'app.team', SimpleNamespace(identify=lambda event: (None, None)))
    notices = []
    from app import owner_briefing

    async def deliver(text, urgent=False):
        notices.append(text)
    monkeypatch.setattr(owner_briefing, 'deliver', deliver)
    from app import whatsapp_natural

    async def natural(question, history=()):
        return 'Thank you, noted.'
    monkeypatch.setattr(whatsapp_natural, 'reply', natural)
    first = agent.accept_inbound(payload(95, 'Please find the shipment details'))
    assert tick()
    ids = []
    for number in range(96, 100):
        photo = payload(number, '')
        photo['message']['attachments'] = [{'type': 'image', 'mimeType': 'image/jpeg', 'id': f'm{number}'}]
        queued = agent.accept_inbound(photo)
        ids.append(queued['job_id'])
        assert tick()
    statuses = [store.get_job(i)['status'] for i in ids]
    sent = [s[1] for s in setup['sends']]
    assert statuses[0] == 'sent' and set(statuses[1:]) == {'blocked'}, statuses
    assert sent[-1].startswith('Thank you, we have received your attachments') and len(sent) == 2, sent
    assert len(notices) == 1 and 'مرفقات' in notices[0]


def test_customer_photo_burst_is_read_once_and_answered(setup, monkeypatch):
    import asyncio
    from app import customer_images as ci, whatsapp_natural, zernio_whatsapp as z, load_vision, owner_briefing
    from test_whatsapp_agent import ACCOUNT
    store.update_settings(ACCOUNT, mode='routine', acceptance={'direct_owner_activation': True,
                          'owner_receipt_confirmed': True, 'confirmed_by': 'test-owner'})
    monkeypatch.setitem(sys.modules, 'app.team', SimpleNamespace(identify=lambda event: (None, None)))
    scheduled = []
    monkeypatch.setattr(ci, 'schedule', lambda job: scheduled.append(job['sender']) or True)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-test-only')
    agent.accept_inbound(payload(120, 'Please find the shipment details'))
    from app import whatsapp_natural as wn

    async def natural(question, history=()):
        return 'Thank you, noted.'
    monkeypatch.setattr(wn, 'reply', natural)
    assert tick()
    for number in (121, 122, 123):
        photo = payload(number, '')
        photo['message']['attachments'] = [{'type': 'image', 'mimeType': 'image/jpeg', 'id': f'm{number}'}]
        agent.accept_inbound(photo)
        assert tick()
    sent = [s[1] for s in setup['sends']]
    assert sent[-1].startswith('Thank you, we have received your photos') and len(sent) == 2, sent
    assert len(scheduled) == 3  # every photo job asks; schedule() itself keeps one reader per sender

    # The reader: all three photos of the burst, one vision call, one reply, claimed so they are never read twice.
    fetched, sends, notices = [], [], []

    async def fetch(pseudo, index):
        fetched.append(pseudo['message']['platformMessageId'])
        return b'img', 'image/jpeg'

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {'content': [{'type': 'text', 'text': 'Photo 1: Krusman turbo oil drum, 208L, made in UAE.'}]}

    class Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw):
            assert sum(1 for b in kw['json']['messages'][0]['content'] if b['type'] == 'image') == 3
            return Resp()

    async def answer(question, history=()):
        assert 'Krusman' in question and history and history[-1]['question'] == 'Please find the shipment details'
        return 'Thank you Mohammed, the photos show Krusman turbo oil drums.'

    async def send(to, text, **kw):
        sends.append((to, text))

    async def deliver(text, urgent=False):
        notices.append(text)
    monkeypatch.setattr(load_vision, 'fetch_image', fetch)
    monkeypatch.setattr(ci.httpx, 'AsyncClient', Client)
    monkeypatch.setattr(wn, 'reply', answer)
    monkeypatch.setattr(z, 'send', send)
    monkeypatch.setattr(owner_briefing, 'deliver', deliver)
    monkeypatch.setattr(ci, 'WAIT_SECONDS', 0)
    monkeypatch.setattr(ci, 'QUIET_SECONDS', 0)
    sender = setup['sends'][0][0]
    asyncio.run(ci._run(ACCOUNT, sender, 'synthetic-conversation'))
    assert len(fetched) == 3 and sends == [(sender, 'Thank you Mohammed, the photos show Krusman turbo oil drums.')]
    assert len(notices) == 1 and 'Krusman' in notices[0]
    asyncio.run(ci._run(ACCOUNT, sender, 'synthetic-conversation'))
    assert len(sends) == 1  # already read
