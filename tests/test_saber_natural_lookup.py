"""Synthetic official-lookup/model orchestration; never calls a live model/site or sends messages."""
import asyncio
import json

import httpx
import pytest

from app import whatsapp_natural as natural
from app.customs_knowledge import KNOWLEDGE

SOURCE = 'https://saber.sa/Home/HSCodes?Tags=%D8%A5%D8%B7%D8%A7%D8%B1%D8%A7%D8%AA'
TIRE = {'code': '401110100000', 'description': 'إطارات خارجية هوائية جديدة للسيارات السياحية',
        'regulation': 'اللائحة الفنية الخليجية للاطارات',
        'certificates': 'شهادة علامة الجودة (QM) أو بطاقة كفاءة الطاقة للإطارات',
        'additional_requirements': '', 'match': 'candidate'}
EVIDENCE = {'status': 'results', 'query': 'إطارات', 'query_kind': 'product',
            'source_url': SOURCE, 'retrieved_at': '2026-11-08T00:00:00+00:00',
            'results': [TIRE], 'total_results': 1, 'truncated': False}
ANSWER = ('نعم، للإطارات الجديدة المذكورة في نتيجة سابر مسار علامة الجودة أو بطاقة كفاءة الطاقة للإطارات، '
          'ثم شهادة الإرسالية. البند المرشح 401110100000 يلزم مطابقته بمواصفات المنتج. المصدر: ' + SOURCE)


def install_model(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setenv('WHATSAPP_NATURAL_REPLIES', '1')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-test-key')
    monkeypatch.setenv('WHATSAPP_NATURAL_MODEL', 'claude-test')
    async def deny_network(*args, **kwargs):
        raise AssertionError('Real network forbidden in unit tests')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', deny_network)
    monkeypatch.setattr(natural.httpx, 'AsyncClient', lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw))


def test_tire_question_performs_lookup_before_answer_and_retains_current_history(monkeypatch):
    calls, searches = [], []
    question = 'اطارات السيارات عليه سابر؟'
    history = [{'question': 'بضاعة جديدة للاستيراد', 'reply': 'ما نوع البضاعة؟'}]
    async def lookup(query):
        searches.append(query)
        return EVIDENCE
    monkeypatch.setattr('app.saber_answers.search_product', lookup)
    def handle(request):
        assert request.url.host == 'api.anthropic.com'
        body = json.loads(request.content)
        calls.append(body)
        assert 'tariff_search' in [x['name'] for x in body['tools']]
        assert 'saber_search' in [x['name'] for x in body['tools']]
        assert KNOWLEDGE in body['system']
        assert 'Preserve OR alternatives exactly' in body['system']
        if len(calls) == 1:
            assert body['tool_choice'] == {'type': 'tool', 'name': 'saber_search'}
            assert body['messages'][-1]['content'] == question
            assert body['messages'][0]['content'] == history[0]['question']
            return httpx.Response(200, json={'content': [{'type': 'tool_use', 'id': 'saber-1',
                'name': 'saber_search', 'input': {'query': 'إطارات'}}]})
        assert 'tool_choice' not in body
        result = json.loads(body['messages'][-1]['content'][0]['content'])
        assert result == EVIDENCE
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': ANSWER}]})
    install_model(monkeypatch, handle)
    answer = asyncio.run(natural.reply(question, history))
    assert TIRE['certificates'] in answer and TIRE['description'] in answer
    assert SOURCE in answer and '401110100000' in answer
    assert searches == ['إطارات'] and len(calls) == 1


@pytest.mark.parametrize('status', ['unavailable', 'no_results', 'invalid_query'])
def test_missing_official_result_cannot_be_turned_into_exemption(monkeypatch, status):
    calls = []
    async def lookup(query):
        return {'status': status, 'results': []}
    monkeypatch.setattr('app.saber_answers.search_product', lookup)
    def handle(request):
        calls.append(request)
        assert len(calls) == 1  # no model chance to invent a route after failed lookup
        return httpx.Response(200, json={'content': [{'type': 'tool_use', 'id': 'saber-1',
            'name': 'saber_search', 'input': {'query': 'synthetic product'}}]})
    install_model(monkeypatch, handle)
    assert asyncio.run(natural.reply('المنتج عليه سابر؟')) == natural.SABER_UNVERIFIED_REPLY
    assert 'لا أؤكد' in natural.SABER_UNVERIFIED_REPLY


def test_model_cannot_skip_required_lookup_with_vague_or_confident_answer(monkeypatch):
    def handle(request):
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'غالبًا عليه سابر.'}]})
    install_model(monkeypatch, handle)
    assert asyncio.run(natural.reply('اطارات السيارات عليه سابر؟')) == natural.SABER_UNVERIFIED_REPLY


def test_general_saber_process_question_does_not_transmit_user_text_to_website(monkeypatch):
    calls = []
    async def forbidden_lookup(*args, **kwargs):
        raise AssertionError('General process question is not a product query')
    monkeypatch.setattr('app.saber_answers.search_product', forbidden_lookup)
    answer = 'غير الخاضع للائحة الفنية يحتاج إقرارًا ذاتيًا ثم شهادة الإرسالية، وليس إعفاءً من سابر.'
    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={'content': [{'type': 'tool_use', 'id': 'general-1',
                'name': 'saber_search', 'input': {'query': ''}}]})
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': answer}]})
    install_model(monkeypatch, handle)
    assert asyncio.run(natural.reply('غير الخاضع يعني معفى من سابر؟')) == natural.SABER_GENERAL_REPLY
    assert len(calls) == 1
    assert 'لا يعني الإعفاء' in natural.SABER_GENERAL_REPLY


def test_unrelated_transport_flow_remains_unforced(monkeypatch):
    def handle(request):
        body = json.loads(request.content)
        assert 'tool_choice' not in body
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'ما مسار النقل المطلوب؟'}]})
    install_model(monkeypatch, handle)
    assert asyncio.run(natural.reply('عندكم نقل؟')) == 'ما مسار النقل المطلوب؟'


def test_lookup_does_not_authorize_unknown_code_or_executed_action(monkeypatch):
    assert natural.safe(ANSWER, KNOWLEDGE) is None
    grounding = KNOWLEDGE + json.dumps([EVIDENCE], ensure_ascii=False)
    assert natural.safe(ANSWER, grounding) == ANSWER
    assert natural.safe(ANSWER.replace('401110100000', '987654321099'), grounding) is None
    assert natural.safe('تم الفسح لشحنتك', grounding) is None
    assert natural.safe('راجع https://private.invalid/customer', grounding) is None


def test_unrecognized_tool_is_not_silently_dispatched_to_tariff(monkeypatch):
    def handle(request):
        return httpx.Response(200, json={'content': [{'type': 'tool_use', 'id': 'unknown',
            'name': 'send_certificate', 'input': {'query': 'product'}}]})
    install_model(monkeypatch, handle)
    assert asyncio.run(natural.reply('هل يحتاج سابر؟')) == natural.SABER_UNVERIFIED_REPLY


def test_model_http_failure_and_rejected_answer_cannot_fall_back_to_unchecked_guess(monkeypatch):
    install_model(monkeypatch, lambda request: httpx.Response(503))
    assert asyncio.run(natural.reply('هل الإطارات تحتاج شهادة مطابقة؟')) == natural.SABER_UNVERIFIED_REPLY

    calls = []
    async def lookup(query):
        return EVIDENCE
    monkeypatch.setattr('app.saber_answers.search_product', lookup)
    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={'content': [{'type': 'tool_use', 'id': 'saber-1',
                'name': 'saber_search', 'input': {'query': 'إطارات'}}]})
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'تم الفسح لشحنتك'}]})
    # Restore the class because install_model captures it for the mock factory.
    monkeypatch.undo()
    monkeypatch.setattr('app.saber_answers.search_product', lookup)
    install_model(monkeypatch, handle)
    answer = asyncio.run(natural.reply('اطارات السيارات عليه سابر؟'))
    assert TIRE['certificates'] in answer and 'تم الفسح' not in answer
    assert len(calls) == 1


def test_empty_query_cannot_bypass_product_evidence_gate(monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        assert len(calls) == 1
        return httpx.Response(200, json={'content': [{'type': 'tool_use', 'id': 'empty',
            'name': 'saber_search', 'input': {'query': ''}}]})
    install_model(monkeypatch, handle)
    assert asyncio.run(natural.reply('اطارات السيارات عليه سابر؟')) == natural.SABER_GENERAL_REPLY
    assert 'الإطارات' not in natural.SABER_GENERAL_REPLY
