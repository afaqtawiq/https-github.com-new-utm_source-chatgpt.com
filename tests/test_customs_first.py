"""Local customs-first contract tests. No real models, requests or messages."""
import ast
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import customs_policy as policy
from app import whatsapp_natural as natural
from app import whatsapp_agent_privacy as privacy
from app.customs_knowledge import KNOWLEDGE

ROOT = Path(__file__).resolve().parents[1]


def install_model(monkeypatch, response):
    original = httpx.AsyncClient
    calls = []
    async def deny_network(*args, **kwargs):
        raise AssertionError('Real network forbidden')
    def handle(request):
        assert request.url.host == 'api.anthropic.com'
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'content': response})
    monkeypatch.setenv('WHATSAPP_NATURAL_REPLIES', '1')
    monkeypatch.setenv('WHATSAPP_NATURAL_MODEL', 'claude-test')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-unit-test-key')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', deny_network)
    monkeypatch.setattr(natural.httpx, 'AsyncClient', lambda **kw: original(
        transport=httpx.MockTransport(handle), **kw))
    return calls


@pytest.mark.parametrize('question', [
    'عندي بضاعة واردة جدة من الصين، وش المستندات؟',
    'نبي نصدر منتج سعودي إلى عمان',
    'عندي ترانزيت من جدة للحديثة ثم الأردن',
    'شحنة جوية مؤقتة للمعرض بالرياض',
    'أحتاج نقل فقط من جدة إلى الرياض',
])
def test_primary_customer_lane_preserves_topic_and_tools(monkeypatch, question):
    calls = install_model(monkeypatch, [{'type': 'text', 'text': 'ما نوع البضاعة؟'}])
    assert asyncio.run(natural.reply(question)) == 'ما نوع البضاعة؟'
    assert policy.CUSTOMS_FIRST_POLICY in calls[0]['system']
    assert KNOWLEDGE in calls[0]['system']
    assert calls[0]['messages'][-1]['content'] == question
    assert {t['name'] for t in calls[0]['tools']} == {'saber_search', 'tariff_search'}
    assert 'tool_choice' not in calls[0]


def test_policy_covers_speciality_without_expanding_authority():
    for text in [
        'CUSTOMS-FIRST SERVICE POLICY', 'not a human or personally licensed customs broker',
        'Transport,', 'import INTO Saudi Arabia', 're-export, transit,',
        'entry AND exit/destination', 'one useful', 'not a verified classification',
        'No list here is exhaustive', 'No', 'untrusted evidence',
        'Existing staff tools, authorization, review and confirmation controls',
        'not private documents, customer names, phones or shipment references',
    ]:
        assert text in policy.CUSTOMS_FIRST_POLICY
    assert 'كأنك موظف حقيقي' not in natural.SYSTEM


def test_tariff_question_requires_actual_tool_and_cannot_invent_rate(monkeypatch):
    calls = install_model(monkeypatch, [{'type': 'text', 'text': 'البند مؤكد والرسوم 5%'}])
    assert asyncio.run(natural.reply('ما البند الجمركي للأخشاب؟')) == natural.TARIFF_UNVERIFIED_REPLY
    assert calls[0]['tool_choice'] == {'type': 'tool', 'name': 'tariff_search'}


def test_tariff_preserves_context_and_mixed_request(monkeypatch):
    original = httpx.AsyncClient
    calls, searches = [], []
    candidate = {'code': '440711000000', 'desc_ar': 'غيرها', 'duty': '5% حسب الشروط المذكورة',
                 'context_ar': 'خشب صنوبري منشور ضمن الشروط والاستثناءات المفصلة في الفصل'}
    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            assert body['tool_choice'] == {'type': 'tool', 'name': 'tariff_search'}
            return httpx.Response(200, json={'content': [{'type': 'tool_use', 'id': 'tariff-1',
                'name': 'tariff_search', 'input': {'ar': ['خشب'], 'en': ['wood']}}]})
        assert 'tool_choice' not in body
        evidence = json.loads(body['messages'][-1]['content'][0]['content'])
        assert evidence['candidates'][0]['context'] == candidate['context_ar']
        assert evidence['candidates'][0]['duty'] == candidate['duty']
        return httpx.Response(200, json={'content': [{'type': 'text',
            'text': 'البند المرشح 440711000000 يحتاج مطابقة المواصفات. النقل من ميناء جدة الإسلامي إلى الرياض 4,500 ريال ضمن الشروط المعتمدة.'}]})
    install_model(monkeypatch, [])
    monkeypatch.setattr(natural.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setenv('DATABASE_URL', 'postgresql://unit-test-only.invalid/no-network')
    from app import tariff_lookup
    def search(ar, en):
        searches.append((ar, en))
        return [candidate]
    monkeypatch.setattr(tariff_lookup, 'search_many', search)
    answer = asyncio.run(natural.reply('ما البند الجمركي للخشب وكم النقل من ميناء جدة إلى الرياض؟'))
    assert len(calls) == 2 and searches == [(['خشب'], ['wood'])]
    assert '440711000000' in answer and '4,500' in answer
    assert answer.startswith(natural.TARIFF_SOURCE_NOTE)


@pytest.mark.parametrize('question', ['كم الرسوم الجمركية للخشب؟', 'كم جمارك الخشب؟', 'What are the customs duties on timber?'])
def test_common_duty_question_cannot_skip_actual_lookup(monkeypatch, question):
    install_model(monkeypatch, [{'type': 'text', 'text': '5% فقط'}])
    assert asyncio.run(natural.reply(question)) == natural.TARIFF_UNVERIFIED_REPLY


def test_failed_tariff_tool_is_not_permission_for_guess(monkeypatch):
    install_model(monkeypatch, [{'type': 'tool_use', 'id': 'empty', 'name': 'tariff_search', 'input': {'ar': ['wood']}}])
    monkeypatch.setattr(natural, 'tariff_result', lambda a: [])
    assert asyncio.run(natural.reply('البند الجمركي للخشب؟')) == natural.TARIFF_UNVERIFIED_REPLY


def test_tariff_call_cannot_bypass_required_saber_lookup(monkeypatch):
    calls = install_model(monkeypatch, [{'type': 'tool_use', 'id': 'wrong-tool',
        'name': 'tariff_search', 'input': {'ar': ['wood']}}])
    monkeypatch.setattr(natural, 'tariff_result', lambda a: [])
    answer = asyncio.run(natural.reply('هل البند الجمركي للخشب عليه سابر؟'))
    assert answer == natural.SABER_UNVERIFIED_REPLY
    assert calls[0]['tool_choice'] == {'type': 'tool', 'name': 'saber_search'}


def test_no_model_never_generates_tariff_rate(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    assert asyncio.run(natural.reply('ما البند الجمركي للأخشاب؟')) == natural.TARIFF_UNVERIFIED_REPLY


def test_intake_fields_are_optional_bounded_and_never_authority():
    assert policy.intake_details({'customs_direction': 'transit', 'entry_port': 'جدة',
        'exit_port': 'الحديثة', 'transport_mode': 'sea', 'hs_code': '٤٤٠٧',
        'documents_available': 'الفاتورة متاحة', 'permission': 'approved'}) == {
        'customs_direction': 'transit', 'entry_port': 'جدة', 'exit_port': 'الحديثة',
        'transport_mode': 'sea', 'hs_code': '4407', 'documents_available': 'الفاتورة متاحة'}
    assert policy.intake_details({'customs_direction': 'approved', 'transport_mode': 'rail',
        'hs_code': '1234567890123', 'product_details': 'x' * 501}) == {}
    assert policy.intake_details('malformed') == {}


def isolated_intake_reply(model_result):
    # Avoid import-time monkeypatches of the legacy receiver in a shared suite.
    tree = ast.parse((ROOT / 'app/ai_intake.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'reply')
    scope = {'base': SimpleNamespace(repair_legacy_fields=lambda fields: (dict(fields), {}),
        QUESTIONS=[('service',''), ('route',''), ('cargo',''), ('deadline','')]),
        'ask': lambda *a: model_result, 'KEYS': ('service','route','cargo','deadline'),
        'INTAKE_CUSTOMS_KEYS': policy.INTAKE_CUSTOMS_KEYS, 'intake_details': policy.intake_details,
        '_fallback': lambda *a: ('fallback',), 'tariff_lookup': SimpleNamespace()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / 'app/ai_intake.py'), 'exec'), scope)
    return scope['reply']


def test_intake_correction_preserves_unaffected_customs_context():
    reply = isolated_intake_reply({'fields': {'entry_port': 'الدمام'}, 'reply': 'تم فهم منفذ الوصول.'})
    fields, pending, state, _ = reply({'service': 'تخليص وارد', 'route': 'الصين إلى السعودية',
        'cargo': 'خشب', 'deadline': 'الشهر القادم', 'entry_port': 'جدة', 'customs_direction': 'import',
        'documents_available': 'الفاتورة متاحة'}, None, 'التصحيح الدخول الدمام', None, {}, False)
    assert fields['entry_port'] == 'الدمام' and fields['customs_direction'] == 'import'
    assert fields['documents_available'] == 'الفاتورة متاحة' and fields['cargo'] == 'خشب'
    assert state == 'ready_for_review'  # review, not approval or customs completion


@pytest.mark.parametrize('has_legacy_service', [True, False])
def test_new_shipment_archives_and_does_not_mix_customs_details(has_legacy_service):
    reply = isolated_intake_reply({'new_request': True, 'fields': {'service': 'نقل فقط'}, 'reply': 'ما مسار النقل؟'})
    fields, pending, state, _ = reply({**({'service': 'تخليص'} if has_legacy_service else {}), 'entry_port': 'جدة',
        'customs_direction': 'import', 'documents_available': 'فاتورة'}, None,
        'عندي شحنة ثانية نقل فقط', None, {}, False)
    assert fields['service'] == 'نقل فقط' and 'entry_port' not in fields
    assert fields['_previous_requests'][-1]['customs_direction'] == 'import'
    assert fields['_previous_requests'][-1]['documents_available'] == 'فاتورة'
    assert pending == 'route' and state == 'collecting'


def test_lanes_use_policy_without_new_tools_or_document_privilege():
    for name in ['whatsapp_natural', 'ai_intake', 'command_ai', 'command_agent', 'whatsapp_agent_privacy']:
        source = (ROOT / ('app/' + name + '.py')).read_text()
        assert 'CUSTOMS_FIRST_POLICY' in source
    assert hashlib.sha256(KNOWLEDGE.encode()).hexdigest() == privacy._PUBLIC_KNOWLEDGE_SHA256
    assert privacy._PUBLIC_KNOWLEDGE_SECTIONS == {17}
    public = privacy._public_knowledge()
    assert '700' not in public and '400' not in public
    assert 'دليل تراخيص الاستيراد' not in public


def test_reviewed_general_guidance_has_no_legacy_blanket_claims():
    general = KNOWLEDGE.split('16) أسعار')[0]
    for removed in ['أغلب السلع 5%', 'المدة المعتادة للشحنة المكتملة',
                    'قد يكفي تقديم الفاتورة', 'تحتاج أيضًا موافقة خاصة ويُتحقق من نسبة الكحول']:
        assert removed not in general
    for expected in ['دلالة منشأ ثابتة', 'لا تعتبر كل خشب مصنع', 'إعادة تصدير',
                     '31 أغسطس 2026', 'www.uqn.gov.sa', 'Integrated-Tarrifs.aspx']:
        assert expected in general


def test_tool_only_loop_cannot_report_empty_success(monkeypatch):
    calls = install_model(monkeypatch, [{'type': 'tool_use', 'id': 'again',
        'name': 'tariff_search', 'input': {'ar': ['wood']}}])
    monkeypatch.setattr(natural, 'tariff_result', lambda a: [
        {'code': '44 07 11 00 00 00', 'description': 'wood', 'context': 'wood heading', 'duty': '5%'}])
    assert asyncio.run(natural.reply('ما البند الجمركي للخشب؟')) == natural.TARIFF_UNVERIFIED_REPLY
    assert len(calls) == 3
