"""Isolated owner/team wiring; no storage initialization, live model, or sends."""
import asyncio
from contextvars import ContextVar
import importlib.util
import json
from pathlib import Path
import re
import sys
import threading
import types
from unittest.mock import Mock

import httpx
import pytest
from app import whatsapp_natural as natural

ROOT = Path(__file__).resolve().parents[1]
QUESTION = 'اطارات السيارات عليه سابر؟'


@pytest.fixture
def modules(monkeypatch):
    import app
    page = types.ModuleType('app.command_assistant')
    page.parse_command = Mock(return_value={'action_type': 'unknown'})
    admin = types.ModuleType('app.whatsapp_admin')
    admin.normalize = lambda value: str(value or '').translate(str.maketrans('أإآ', 'ااا')).strip()
    for name in ('run_command', 'afaaq_command', 'admin_reply'):
        setattr(admin, name, Mock(side_effect=AssertionError('operational route touched')))
    team = types.ModuleType('app.team')
    team.ROLE = ContextVar('synthetic_saber_role', default={})
    team.CONTEXT = ContextVar('synthetic_saber_context', default={})
    for name, value in [('command_assistant', page), ('whatsapp_admin', admin), ('team', team)]:
        monkeypatch.setitem(sys.modules, 'app.' + name, value)
        monkeypatch.setattr(app, name, value, raising=False)
    loaded = []
    for name in ('command_ai', 'command_agent'):
        spec = importlib.util.spec_from_file_location('test_isolated_' + name, ROOT / 'app' / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setitem(sys.modules, 'app.' + name, module)
        monkeypatch.setattr(app, name, module, raising=False)
        loaded.append(module)
    return loaded


@pytest.mark.parametrize('question', [QUESTION, 'هل الخشب يحتاج شهادة مطابقة؟',
                                     'Do car tires require SABER?', 'متطلبات سابر للاطارات'])
def test_pure_information_predicate(modules, question):
    ai, _ = modules
    assert ai.is_saber_information_question(question)


@pytest.mark.parametrize('question', ['ارسل للعميل تفاصيل سابر', 'نيرمين لو سمحتي احجزي موعد سابر',
    'سجل المنتج وأخبرني هل عليه سابر؟', 'كم رصيد العميل وهل بضاعته عليها سابر؟',
    'حالة شحنتي وسابر', 'Send the SABER requirements to the customer',
    'هل الخشب يحتاج شهادة مطابقة؟ احجزها', 'هل سابر مطلوب؟ احجز؟',
    'اطبع شهادة سابر', 'سابر', 'اعرض السائقين', 'كم تكلفة شهادة سابر؟'])
def test_actions_mixed_requests_and_unrelated_preserved(modules, question):
    ai, _ = modules
    assert not ai.is_saber_information_question(question)


def test_tool_and_top_level_use_shared_reply_without_db_or_team_model(modules, monkeypatch):
    ai, agent = modules
    seen = []
    async def reply(question, history=()):
        seen.append((question, history, threading.current_thread().name))
        return 'نتيجة رسمية للاختبار'
    monkeypatch.setattr(natural, 'reply', reply)
    monkeypatch.setattr(agent, 'call_model', Mock(side_effect=AssertionError('legacy model touched')))
    db = Mock(side_effect=AssertionError('database touched'))
    assert agent.tool_customs_question(db, {'question': QUESTION}) == 'نتيجة رسمية للاختبار'
    assert agent.run_agent(db, QUESTION) == 'نتيجة رسمية للاختبار'
    assert len(seen) == 2 and all(x[1] == () and x[2] == 'saber-readonly' for x in seen)
    db.assert_not_called()


def test_bridge_inside_running_event_loop(modules, monkeypatch):
    ai, _ = modules
    async def reply(question, history=()):
        await asyncio.sleep(0)
        return 'نتيجة'
    monkeypatch.setattr(natural, 'reply', reply)
    async def webhook():
        return ai.answer_question(QUESTION)
    assert asyncio.run(webhook()) == 'نتيجة'


@pytest.mark.parametrize('failure', ['none', 'exception', 'timeout', 'busy'])
def test_bridge_failures_do_not_fall_back_to_guessing(modules, monkeypatch, failure):
    ai, _ = modules
    async def reply(question, history=()):
        if failure == 'exception':
            raise RuntimeError('synthetic')
        if failure == 'timeout':
            await asyncio.sleep(1)
        return None
    monkeypatch.setattr(natural, 'reply', reply)
    monkeypatch.setattr(ai, '_SABER_DEADLINE', .01)
    if failure == 'busy':
        monkeypatch.setattr(ai, '_SABER_SLOTS', threading.BoundedSemaphore(0))
    assert ai.answer_question(QUESTION) == natural.SABER_UNVERIFIED_REPLY


def test_legacy_disable_gate_is_preserved(modules, monkeypatch):
    ai, agent = modules
    monkeypatch.setattr(natural, 'reply', Mock(side_effect=AssertionError('disabled')))
    token = ai.LEGACY_MODEL_DISABLED.set(True)
    try:
        assert ai.answer_question(QUESTION) is None
        assert agent.run_agent(None, QUESTION) is None
    finally:
        ai.LEGACY_MODEL_DISABLED.reset(token)


@pytest.mark.parametrize('question', ['اعرض السائقين', 'كم رصيد العميل وهل بضاعته عليها سابر؟',
                                     'ارسل للعميل تفاصيل سابر'])
def test_ordinary_agent_model_route_is_unchanged(modules, monkeypatch, question):
    ai, agent = modules
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-test-key')
    monkeypatch.setattr(agent, '_member', lambda: {'name': 'Test', 'manager': True})
    call = Mock(return_value={'content': [{'type':'text', 'text':'existing route'}]})
    monkeypatch.setattr(agent, 'call_model', call)
    monkeypatch.setattr(ai, 'answer_saber_question', Mock(side_effect=AssertionError('intercepted')))
    assert agent.run_agent(None, question) == 'existing route'
    call.assert_called_once()


@pytest.mark.parametrize('status', ['results', 'no_results', 'unavailable'])
def test_real_shared_tool_loop_grounding_for_team(modules, monkeypatch, status):
    ai, agent = modules
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-test-key')
    monkeypatch.setenv('WHATSAPP_NATURAL_REPLIES', '1')
    monkeypatch.setenv('WHATSAPP_NATURAL_MODEL', 'claude-test')
    requests, lookups = [], []
    async def official(query):
        lookups.append(query)
        return {'status': status, 'source_url':'https://saber.sa/Home/HSCodes',
                'query_kind': 'product', 'retrieved_at':'2026-11-08T00:00:00+00:00',
                'results': [{'code':'401110100000', 'description':'إطارات سيارات',
                             'regulation':'اللائحة الفنية الخليجية للاطارات',
                             'additional_requirements':'',
                             'certificates':'شهادة علامة الجودة أو بطاقة كفاءة الطاقة'}] if status == 'results' else []}
    from app import saber_answers
    monkeypatch.setattr(saber_answers, 'search_product', official)
    original_client = httpx.AsyncClient
    def model(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            assert body['tool_choice'] == {'type':'tool', 'name':'saber_search'}
            return httpx.Response(200, json={'content':[{'type':'tool_use','id':'lookup',
                'name':'saber_search','input':{'query':'إطارات'}}]})
        return httpx.Response(200, json={'content':[{'type':'text','text':'النتيجة الرسمية متاحة.'}]})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(model), **kw))
    monkeypatch.setattr(agent, 'call_model', Mock(side_effect=AssertionError('unguarded model')))
    result = agent.run_agent(None, QUESTION)
    assert lookups == ['إطارات']
    if status == 'results':
        assert 'شهادة علامة الجودة أو بطاقة كفاءة الطاقة' in result and len(requests) == 1
    else:
        assert result == natural.SABER_UNVERIFIED_REPLY and len(requests) == 1


def test_team_question_cannot_accept_model_guess_without_tool(modules, monkeypatch):
    _, agent = modules
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-test-key')
    monkeypatch.setenv('WHATSAPP_NATURAL_REPLIES', '1')
    monkeypatch.setenv('WHATSAPP_NATURAL_MODEL', 'claude-test')
    original_client = httpx.AsyncClient
    requests = []
    def model(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'content':[{'type':'text','text':'غالبا لا تحتاج شهادة'}]})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(model), **kw))
    assert agent.run_agent(None, QUESTION) == natural.SABER_UNVERIFIED_REPLY
    assert requests[0]['tool_choice'] == {'type':'tool', 'name':'saber_search'}


def test_ordinary_answer_question_keeps_legacy_route(modules, monkeypatch):
    ai, _ = modules
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-test-key')
    monkeypatch.setattr(ai, '_staff_context', lambda: '')
    monkeypatch.setattr(ai, 'answer_saber_question', Mock(side_effect=AssertionError('intercepted')))
    original_client = httpx.Client
    calls = []
    def model(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'content':[{'type':'text','text':'legacy answer'}]})
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original_client(transport=httpx.MockTransport(model), **kw))
    assert ai.answer_question('كيف حالك؟') == 'legacy answer'
    assert len(calls) == 1 and 'tools' not in calls[0]
