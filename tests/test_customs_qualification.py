"""Offline customer scenarios. Mocked LLM prose is NOT live-model qualification.

Passing orchestration tests prove plumbing/guards only. Explicit limitation
tests preserve evidence that numeric guards are not semantic reconciliation.
"""
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import customs_case_guidance as g
from app import customs_policy as policy
from app import whatsapp_natural as n
from app.customs_knowledge import KNOWLEDGE

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    async def deny(*args, **kwargs):
        raise AssertionError('No network or live-model calls allowed')
    def deny_sync(*args, **kwargs):
        raise AssertionError('No network allowed')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', deny)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', deny_sync)
    monkeypatch.setenv('WHATSAPP_NATURAL_REPLIES', '1')
    monkeypatch.setenv('WHATSAPP_NATURAL_MODEL', 'claude-test')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-local-fixture')


def model_response(monkeypatch, content):
    calls = []
    original = httpx.AsyncClient
    def handler(request):
        assert request.url.host == 'api.anthropic.com'
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'content': content})
    monkeypatch.setattr(n.httpx, 'AsyncClient', lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw))
    return calls


@pytest.mark.parametrize('question,reference', [
    ('وارد بحري خشب من الصين إلى جدة، ما المستندات؟', 'الشهادة النباتية'),
    ('صادر بري منتج سعودي إلى عمان، ما الوثائق؟', 'وثيقة البر'),
    ('إعادة تصدير معدات سبق استيرادها، ماذا يلزم؟', 'المادة 31'),
    ('ترانزيت بري من البطحاء إلى الحديثة، ماذا يلزم؟', 'بيان جمركي من دولة المصدر'),
    ('إدخال مؤقت لمعرض جوي، ما المستندات؟', 'ليس إعفاء نهائيًا'),
])
def test_movement_scenarios_wire_context_not_validate_prose(monkeypatch, question, reference):
    calls = model_response(monkeypatch, [{'type': 'text', 'text': 'ما وصف البضاعة واستخدامها؟'}])
    assert asyncio.run(n.reply(question)) == 'ما وصف البضاعة واستخدامها؟'
    assert reference in calls[0]['system']
    assert policy.CUSTOMS_FIRST_POLICY in calls[0]['system']
    assert calls[0]['messages'][-1]['content'] == question
    assert 'tool_choice' not in calls[0]


@pytest.mark.parametrize('question', ['وكم نسبة الرسم؟', 'ما نسبه الجمارك للأخشاب؟',
    'What is the duty rate on timber?'])
def test_duty_paraphrases_cannot_bypass_required_evidence(monkeypatch, question):
    calls = model_response(monkeypatch, [{'type': 'text', 'text': 'الرسم 7% مؤكد'}])
    assert asyncio.run(n.reply(question)) == n.TARIFF_UNVERIFIED_REPLY
    assert calls[0]['tool_choice']['name'] == 'tariff_search'


@pytest.mark.parametrize('claim', ['تم إصدار شهادة سابر لشحنتك', 'تم تقديم البيان الجمركي',
    'تم سداد الرسوم الجمركية', 'تم ارسال بيان جمركي', 'تم دفع رسوم جمركية'])
def test_fabricated_customs_execution_is_rejected(monkeypatch, claim):
    model_response(monkeypatch, [{'type': 'text', 'text': claim}])
    # No question keyword is needed for the response-side action guard.
    assert asyncio.run(n.reply('تابع لي الطلب')) is None


def test_corrected_context_reaches_model_in_order(monkeypatch):
    calls = model_response(monkeypatch, [{'type': 'text', 'text': 'ما وسيلة الشحن؟'}])
    history = [{'question': 'وارد خشب إلى جدة', 'reply': 'ما وسيلة الشحن؟'}]
    question = 'تصحيح، المنفذ الدمام وليس جدة'
    asyncio.run(n.reply(question, history))
    assert [m['content'] for m in calls[0]['messages']] == [
        history[0]['question'], history[0]['reply'], question]
    # Selection and correction reasoning itself are not evaluated by this mock.


def intake_reply(ai):
    tree = ast.parse((ROOT / 'app/ai_intake.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'reply')
    scope = {'base': SimpleNamespace(repair_legacy_fields=lambda f: (dict(f), {}),
        QUESTIONS=[('service',''), ('route',''), ('cargo',''), ('deadline','')]),
        'ask': lambda *a: ai, 'KEYS': ('service','route','cargo','deadline'),
        'INTAKE_CUSTOMS_KEYS': policy.INTAKE_CUSTOMS_KEYS, 'intake_details': policy.intake_details,
        '_fallback': lambda *a: None, 'tariff_lookup': SimpleNamespace()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'isolated_intake', 'exec'), scope)
    return scope['reply']


@pytest.mark.parametrize('direction', ['import', 'export', 're_export', 'transit'])
def test_new_shipment_resets_previous_movement_once_model_identifies_it(direction):
    run = intake_reply({'new_request': True, 'fields': {'service': 'تخليص',
        'customs_direction': direction}, 'reply': 'ما المنفذ؟'})
    saved = {'service': 'تخليص', 'entry_port': 'جدة', 'documents_available': 'فاتورة',
        'hs_code': '440711000000', 'customs_direction': 'import'}
    fields, pending, state, answer = run(saved, None, 'هذه شحنة جديدة', None, {}, False)
    assert fields['customs_direction'] == direction
    assert not {'entry_port', 'documents_available', 'hs_code'} & fields.keys()
    assert fields['_previous_requests'][-1] == saved
    assert state == 'collecting' and pending == 'route'


def test_correction_merges_only_supplied_fields_after_mocked_extraction():
    run = intake_reply({'fields': {'customs_direction': 'transit', 'exit_port': 'الحديثة'},
                        'reply': 'ما الوجهة النهائية؟'})
    fields, _, _, _ = run({'service': 'تخليص', 'entry_port': 'جدة',
        'customs_direction': 'import', 'cargo': 'معدات'}, None,
        'تصحيح ترانزيت والخروج الحديثة', None, {}, False)
    assert fields['customs_direction'] == 'transit' and fields['exit_port'] == 'الحديثة'
    assert fields['entry_port'] == 'جدة' and fields['cargo'] == 'معدات'


@pytest.mark.parametrize('question,fragments', [
    ('وثائق ترانزيت بري؟', ['الفاتورة وأي مستند إضافي يطلبان عند الحاجة', 'بيان جمركي من دولة المصدر']),
    ('هل كل صنف يحتاج قائمة تعبئة؟', ['تحقق من المسار', 'إلزامية للجميع']),
    ('فاتورة الوكيل تشمل المناولة، كيف أجمع التكلفة؟', ['لا تجمع total مع مكوناته', 'لا تضف VAT مرتين']),
    ('سعر الميناء مجهول، ما إجمالي التكلفة؟', ['غير المعلوم ليس صفرًا', 'لا تصفه إجماليًا نهائيًا']),
])
def test_conditional_documents_and_fees_are_guidance_not_calculators(question, fragments):
    selected = g.guidance_for(question)
    assert all(fragment in selected for fragment in fragments)


@pytest.mark.parametrize('query,kind', [('401110100000', 'hs_exact'), ('إطارات', 'product')])
def test_saber_exact_and_general_product_evidence_is_deterministic(monkeypatch, query, kind):
    calls = model_response(monkeypatch, [{'type':'tool_use', 'id':'s1',
        'name':'saber_search', 'input': {'query':query}}])
    async def lookup(value):
        assert value == query
        return {'status':'results', 'query':query, 'query_kind':kind,
            'results':[{'code':'401110100000', 'description':'إطارات سيارات جديدة',
            'regulation':'لائحة الإطارات', 'certificates':'علامة الجودة أو بطاقة كفاءة الطاقة',
            'additional_requirements':'باستثناء الفئات المذكورة'}],
            'source_url':'https://saber.sa/Home/HSCodes', 'retrieved_at':'2026-11-08T00:00:00Z'}
    monkeypatch.setattr('app.saber_answers.search_product', lookup)
    result = asyncio.run(n.reply('هل الإطارات تحتاج سابر؟'))
    assert 'علامة الجودة أو بطاقة كفاءة الطاقة' in result
    assert 'باستثناء الفئات المذكورة' in result
    assert len(calls) == 1  # no second model gets to reinterpret certificate evidence


def test_general_saber_with_cost_does_not_invent_shipment_total(monkeypatch):
    model_response(monkeypatch, [{'type':'tool_use', 'id':'s1',
        'name':'saber_search', 'input': {'query':''}}])
    result = asyncio.run(n.reply('كيف سابر وكم رسوم سابر؟'))
    assert result == n.SABER_GENERAL_REPLY + '\n\n' + g.SABER_FEE_NOTE
    assert 'لا تثبت إجمالي شحنتك' in result and 'دون VAT' in result


@pytest.mark.parametrize('has_key', [True, False])
def test_mixed_saber_tariff_explicitly_marks_unchecked_part(monkeypatch, has_key):
    model_response(monkeypatch, [{'type':'tool_use', 'id':'s1',
        'name':'saber_search', 'input': {'query':''}}])
    if not has_key:
        monkeypatch.delenv('ANTHROPIC_API_KEY')
    result = asyncio.run(n.reply('هل يحتاج سابر وما الرسوم الجمركية؟'))
    assert 'لم أتحقق هنا من تعرفة هذه البضاعة' in result
    assert 'بحث مستقل' in result


@pytest.mark.parametrize('answer', [
    'الوكيل 100 شامل المناولة 100، الإجمالي 200 ريال',
    'الإجمالي النهائي 700 ريال، رسوم الميناء غير معروفة',
])
def test_unsafe_customs_fee_aggregates_defer_without_claiming_reconciliation(monkeypatch, answer):
    model_response(monkeypatch, [{'type':'text', 'text': answer}])
    assert asyncio.run(n.reply('احسب تكلفة التخليص ورسوم الوكيل والميناء')) == n.FEE_TOTAL_UNVERIFIED_REPLY


def test_gap_clearance_guarantee_is_not_rejected():
    assert n.safe('أضمن لك الفسح خلال يومين', KNOWLEDGE) is None


def test_gap_unsupported_short_rate_is_not_rejected_after_lookup(monkeypatch):
    original = httpx.AsyncClient
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        content = ([{'type':'tool_use', 'id':'t1', 'name':'tariff_search',
                     'input': {'ar':['خشب']}}] if len(calls) == 1 else
                   [{'type':'text', 'text':'البند مرشح والرسم 99%'}])
        return httpx.Response(200, json={'content': content})
    monkeypatch.setattr(n.httpx, 'AsyncClient', lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(n, 'tariff_result', lambda args: [
        {'code':'440711000000', 'description':'خشب منشور', 'duty':'5%'}])
    result = asyncio.run(n.reply('ما الرسوم الجمركية للخشب؟'))
    assert len(calls) == 2
    assert result == n.TARIFF_UNVERIFIED_REPLY


@pytest.mark.parametrize('statement', [
    'لم يتم إصدار شهادة سابر لشحنتك',
    'لا نؤكد أنه تم إصدار شهادة سابر لشحنتك',
    'إذا تم تقديم البيان الجمركي فالمراجعة لا تعني الإفراج',
    'عندما تم إصدار شهادة سابر سابقًا لا يعني ذلك صلاحيتها لهذه الشحنة',
    'هل تم سداد الرسوم الجمركية؟',
])
def test_customs_claim_guard_preserves_negation_and_procedures(statement):
    assert n.safe(statement, KNOWLEDGE) == statement


def test_negated_clause_does_not_mask_separate_execution_claim():
    assert n.safe('لم يتم إصدار شهادة سابر، تم تقديم البيان الجمركي', KNOWLEDGE) is None


@pytest.mark.parametrize('word', ['وثائق', 'الوثائق', 'وثايق', 'وثيقة', 'مستندات'])
def test_document_reference_selector_understands_plural_forms(word):
    assert 'وثيقة البر' in g.guidance_for('ما ' + word + ' الصادر البري؟')


@pytest.mark.parametrize('statement', ['لا أضمن الفسح خلال يومين', 'لن نضمن لكم الإفراج',
    'هل أضمن الفسح؟', 'قد يلزم ضمان جمركي بحسب المسار'])
def test_guarantee_guard_preserves_negation_and_customs_bonds(statement):
    assert n.safe(statement, KNOWLEDGE) == statement


@pytest.mark.parametrize('statement', ['أضمن الفسح', 'نضمن لكم الإفراج خلال يوم',
    'لا أضمن النقل، أضمن لك الفسح'])
def test_guarantee_guard_rejects_positive_clearance_promise(statement):
    assert n.safe(statement, KNOWLEDGE) is None


@pytest.mark.parametrize('statement', ['5%', '٥٪', '5.0%', '٥٫٠٪'])
def test_percentage_grounding_normalizes_numeric_forms(statement):
    assert n.percentages(statement) == n.percentages('5%')


def test_percentage_grounding_does_not_claim_rate_applicability():
    # Known limitation: membership cannot prove which product a rate belongs to.
    assert not n.percentages('الصنف الأول 15%') - n.percentages('الصنف الثاني 15%')


@pytest.mark.parametrize('question,answer', [
    ('كم رسوم الكشف؟', 'الإجمالي 200 ريال'),
    ('كم فاتورة الوكيل؟', 'المجموع 500 ريال'),
    ('كم رسوم حجز الموعد؟', 'إجمالي الرسوم 300 ريال'),
    ('What are the port charges?', 'The total is 300 SAR'),
    ('كم رسوم الميناء مع النقل؟', 'الإجمالي 700 ريال'),
    ('احسب تكلفة التخليص', 'المجموع الجزئي 100 ريال، الإجمالي النهائي 700 ريال'),
    ('احسب تكلفة التخليص', 'لا أؤكد إجمالي 500 ريال، الإجمالي النهائي 700 ريال'),
])
def test_external_fee_contexts_reject_unsupported_numeric_aggregates(question, answer):
    assert n.unverified_fee_total(question, answer)


@pytest.mark.parametrize('question,answer', [
    ('كم أتعاب التخليص؟', 'أتعاب آفاق 700 ريال للحاوية وفق العرض المعتمد ولا تشمل رسوم الجهات الأخرى'),
    ('كم فاتورة الميناء؟', 'المجموع الجزئي 100 ريال، رسوم أخرى غير معروفة وهذا ليس إجمالي الشحنة'),
    ('كم فاتورة الميناء؟', 'المجموع الجزئي: 100 ريال، المبلغ غير نهائي'),
    ('كم تكلفة التخليص؟', 'لا أؤكد إجمالي 700 ريال قبل مراجعة الرسوم'),
    ('كم تكلفة التخليص؟', 'لا أستطيع تأكيد الإجمالي 700 ريال'),
    ('كم تكلفة التخليص؟', 'ليس الإجمالي 700 ريال، لا يتوفر مجموع مؤكد'),
    ('كم تكلفة التخليص؟', 'الإجمالي غير معروف ورسوم الميناء تحتاج تسعيرًا'),
    ('كم نقل فقط من ميناء جدة إلى الرياض لحاويتين؟', 'الإجمالي 9000 ريال، لا يشمل رسوم الميناء أو الجمارك'),
    ('نقل من جدة للرياض فقط', 'المجموع 9000 ريال'),
])
def test_fee_guard_preserves_individual_partial_negated_and_transport_answers(monkeypatch, question, answer):
    model_response(monkeypatch, [{'type':'text', 'text':answer}])
    assert not n.unverified_fee_total(question, answer)
    assert asyncio.run(n.reply(question)) == answer


def test_short_fee_followup_uses_bounded_context_without_touching_new_transport():
    history = [{'question':'احسب رسوم الميناء', 'reply':'ما البنود؟'}]
    assert n.unverified_fee_total('وكم المجموع؟', 'الإجمالي 700 ريال', history)
    assert not n.unverified_fee_total('نقل فقط من جدة للرياض', 'الإجمالي 700 ريال', history)


def test_numeric_aggregate_deferral_is_not_duplicate_fee_semantic_validation():
    # No numeric aggregate: still not a typed or reconciled ledger. Never claim
    # this guard verifies every component, inclusion, tax or amount.
    assert not n.unverified_fee_total('احسب رسوم الميناء',
        'الوكيل 100 شامل المناولة، أضف مناولة 100 ريال')
