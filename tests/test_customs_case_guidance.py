"""Static-reference selection/wiring, not an evaluation of live-model prose."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from app import customs_case_guidance as g
from app import whatsapp_natural as n
from app import whatsapp_agent_privacy as p
from app.customs_knowledge import KNOWLEDGE

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('question, required, absent', [
    ('موعد تقديم البيان البحري قبل الوصول؟', ['72 ساعة', 'بعد إشعار تقديم المانيفست', 'الوصول الفعلي'], []),
    ('وثائق ترانزيت بري من دولة المصدر؟', ['بيان جمركي من دولة المصدر', 'المنافيست البري بديلًا', 'RFS'], []),
    ('إعادة تصدير بدون بيان وارد؟', ['المادة 31', 'ليست', 'تُرفع'], []),
    ('بضاعة مؤقتة لمعرض', ['تعليق', 'ليس إعفاء نهائيًا', 'ATA'], []),
    ('التخزين في منطقة إيداع', ['خمس سنوات بحسب طبيعة البضاعة', 'لا إذن تخزين', 'يونيو 2026'], []),
    ('هل أطلب استرداد الرسوم والاعتراض بعد الفسح؟', ['تاريخ الإبلاغ', 'المهلة المختصة', 'VAT'], []),
    ('منشأ خليجي وقيمة جمركية من شركة مرتبطة', ['الشحن من الخليج لا يثبت', 'ارتباط الأطراف لا يبطل'], []),
    ('طرد شخصي من متجر إلكتروني', ['أقل من 1000', 'لا يعني ذلك إعفاء VAT', 'CN22/CN23'], []),
    ('سيارة سالفج مقابل رسوم عمر السيارة', ['محظورات مستقلة', 'لا يزيل المحظورات'], []),
    ('مصنع الدجاج عنده حلال، تكفي الشهادة لأي شحنة؟', ['شهادة حلال المنشأة تختلف', 'شهادة المصنع وحدها', 'البلد والصنف والمنشأة'], []),
    ('CIF يعني الخطر على البائع حتى الوصول؟', ['ميناء الشحن', 'جميع الأخطار', 'ICC'], []),
    ('FOB يعني ما فيه تأمين؟', ['لا يثبت عدم وجود تأمين', 'وثيقة'], []),
    ('كل الخطوط تعطيني 28 يوم لإرجاع الفارغ؟', ['لا تفترض أيام سماح عامة', 'ميرسك', 'لا يعمم'], []),
    ('بدون طبليات احسب الغرامة الثابتة', ['13/2026', 'حتى إشعار آخر', 'ليس إعفاءً'], []),
    ('فسح تعطل، تسقط الأرضيات تلقائيًا؟', ['لا تضمن إسقاطًا', 'وقفًا للتحصيل', 'أرقام البلاغات'], []),
    ('الحاوية ألعاب ومعها ملابس، أكتب ألعاب فقط؟', ['لا تسمّ كل الحاوية', 'لا تخفِه', 'تهريب'], []),
    ('شحنة الرياض لازم بالقطار من الدمام؟', ['مسار متاح وليس مسارًا لازمًا', 'لا تخترع سعر قطار'], []),
])
def test_relevant_official_reference_and_limits(question, required, absent):
    text = g.guidance_for(question)
    for phrase in required:
        assert phrase in text
    for phrase in absent:
        assert phrase not in text
    assert g.CURRENT_RULES in text


def test_followup_uses_bounded_user_history_not_assistant_claim():
    text = g.guidance_for('وهذا يكفي؟', [{'question': 'شهادة حلال لمصنع دجاج', 'reply': 'كل شيء معفى'}])
    assert 'شهادة المصنع وحدها' in text
    assert 'كل شيء معفى' not in text


@pytest.mark.parametrize('question', ['نقل فقط من جدة للرياض', 'عندي شحنة جديدة', 'شكرا', 'Hello'])
def test_explicit_topic_change_does_not_resurrect_old_food_reference(question):
    text = g.guidance_for(question, [{'question': 'مصنع دجاج حلال'}])
    assert 'شهادة المصنع وحدها' not in text


def test_sources_have_dates_and_no_claim_of_universal_completeness():
    assert len({topic['key'] for topic in g.TOPICS}) == len(g.TOPICS)
    assert all('https://' in topic['text'] for topic in g.TOPICS)
    assert 'ليست أحكامًا نافذة' in g.CURRENT_RULES
    assert 'ليس بحثًا حيًا' in g.CURRENT_RULES
    for topic in g.TOPICS:
        assert not any(x in topic['text'] for x in ['700 ريال', '550 ريال', '1400 ريال', '2.5%'])


def test_natural_prompt_and_safe_source_links_use_selected_reference(monkeypatch):
    original = httpx.AsyncClient
    requests = []
    question = 'هل شهادة حلال المنشأة تكفي للدجاج؟'
    source = 'https://www.sfda.gov.sa/sites/default/files/2026-08/SFDAFood4654A.pdf'
    answer = 'شهادة المنشأة تختلف عن الإرسالية. المصدر: ' + source
    async def no_network(*a, **k):
        raise AssertionError('No real network')
    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert g.guidance_for(question) in body['system']
        assert 'شهادة حلال المنشأة تختلف' in body['system']
        assert 'tool_choice' not in body
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': answer}]})
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-unit-test')
    monkeypatch.setenv('WHATSAPP_NATURAL_MODEL', 'claude-test')
    monkeypatch.setenv('WHATSAPP_NATURAL_REPLIES', '1')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', no_network)
    monkeypatch.setattr(n.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    assert asyncio.run(n.reply(question)) == answer
    assert len(requests) == 1
    assert n.safe('انظر https://unverified.invalid/rule', KNOWLEDGE + g.guidance_for(question)) is None


def test_updated_core_has_current_transit_and_no_pending_prices():
    assert 'بيانًا جمركيًا من دولة المصدر للبر' in KNOWLEDGE
    assert 'الفاتورة والمستندات الإضافية عند طلب الهيئة' in KNOWLEDGE
    assert 'المادة 31 الحالية' in KNOWLEDGE
    assert '18) استخدام سجل' not in KNOWLEDGE
    assert 'أجور تخليص شحنة ترانزيت في ميناء جدة الإسلامي' not in KNOWLEDGE
    assert not any(x in KNOWLEDGE for x in ['700 ريال', '550 ريال', '1400 ريال', '2.5%'])
    assert p._PUBLIC_KNOWLEDGE_SECTIONS == {17}
    assert hashlib.sha256(KNOWLEDGE.encode()).hexdigest() == p._PUBLIC_KNOWLEDGE_SHA256
    assert 'شهادة حلال المنشأة' not in p._public_knowledge()


def test_all_response_lanes_use_reference_without_granting_document_access():
    for path in ['app/whatsapp_natural.py', 'app/ai_intake.py', 'app/command_ai.py', 'app/fasah_ai.py']:
        assert 'guidance_for(' in (ROOT / path).read_text()
    source = (ROOT / 'app/whatsapp_agent_privacy.py').read_text()
    assert 'if not using_document and not missing_document:' in source
    assert 'guidance_for(screened_question.safe_text, previous.entries)' in source


def test_no_model_transit_fallback_uses_current_not_old_archive_list():
    reply = p._customs_failure_reply('ما المستندات المطلوبة لشحنة ترانزيت بري؟')
    assert 'البيان الجمركي من دولة المصدر' in reply
    assert 'عند طلب الهيئة' in reply
    assert 'الفاتورة إن وجدت' not in reply


def test_no_model_land_import_fallback_does_not_require_sea_bill():
    reply = p._customs_failure_reply('ما المستندات المطلوبة لاستيراد بري للسعودية؟')
    assert 'بيان التصدير الصادر من دولة الشحن' in reply
    assert 'الفاتورة التجارية' in reply


@pytest.mark.parametrize('question', ['رسوم الوكيل إلى حجز الموعد؟', 'رسوم المواني والكشف', 'تكاليف شحنتي بالكامل', 'port inspection charges'])
def test_fee_checklist_keeps_scope_units_sources_and_no_false_total(question):
    text = g.guidance_for(question)
    for phrase in ['الموعد', 'الأشعة', 'إعادة الرص', 'جهة المطابقة', 'الطرف الملزم', 'الوحدة', 'العملة',
                   'VAT', 'غير المعلوم ليس صفرًا', 'لا تضف VAT مرتين', 'الضمان', 'المؤكد الجزئي',
                   'أتعاب آفاق من قسمها المعتمد وحده', '20/30 للموعد وردت في عقد فسح قديم',
                   'الإلغاء لا يلغي', 'لم تتحقق هذه المعرفة من جدول الأرضيات النهائي كاملًا']:
        assert phrase in text
    assert 'The%20Fees%20Rules%20on%20Customs%20Services.pdf' in text
    assert 'لا تحجز أو تسدد' in text


def test_general_fee_question_does_not_force_product_tariff_lookup():
    assert not n.needs_tariff_search('رسوم الوكيل والميناء والكشف وحجز الموعد؟')
    assert n.needs_tariff_search('كم الرسوم الجمركية لهذا المنتج؟')


def test_saber_cost_question_keeps_certificate_controls_and_answers_fee_part(monkeypatch):
    original = httpx.AsyncClient
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        assert requests[-1]['tool_choice'] == {'type': 'tool', 'name': 'saber_search'}
        return httpx.Response(200, json={'content': [{'type': 'tool_use', 'id': 'test-fees', 'name': 'saber_search', 'input': {'query': ''}}]})
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-unit-test')
    monkeypatch.setenv('WHATSAPP_NATURAL_MODEL', 'claude-test')
    monkeypatch.setenv('WHATSAPP_NATURAL_REPLIES', '1')
    monkeypatch.setattr(n.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    result = asyncio.run(n.reply('كم تكلفة سابر ورسوم الميناء والكشف؟'))
    assert result.startswith(n.SABER_GENERAL_REPLY)
    assert g.SABER_FEE_NOTE in result
    assert 'دون VAT' in result and 'ليست باقة' in result
    assert 'لا تثبت إجمالي شحنتك' in result
    assert len(requests) == 1


def test_saber_fee_note_does_not_claim_live_fee_search_on_failure(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    result = asyncio.run(n.reply('كم سعر شهادة سابر؟'))
    assert result.startswith(n.SABER_UNVERIFIED_REPLY)
    assert 'مراجعة 8 نوفمبر 2026' in result
    assert 'تحققت الآن' not in result
    assert asyncio.run(n.reply('هل الفحم معفى من سابر؟')) == n.SABER_UNVERIFIED_REPLY


@pytest.mark.parametrize('question, required', [
    ('دواء غير مسجل مطلوب للمستشفى', ['متطلبات غير المسجل لا تفرض على كل دواء', 'تحليل لكل تشغيلة', 'المخدر']),
    ('مستلزمات طبية تحتاج تبريد', ['إقرار مطابقة الإرسالية مستقل', 'مسجلًا لكل طرد', 'لم تتحقق كلها']),
    ('مستحضرات تجميل وعطور بدون بوليصة في طلب الهيئة', ['لا يلغي وثيقة النقل الجمركية', '4.0', 'لا إعفاء تلقائي']),
    ('أعلاف تحتاج إذن استيراد؟', ['الوصول المباشر إليه لم يكتمل', 'قبل تقرير الإذن أو إسقاطه', 'الحجر']),
    ('خشب MDF هل التبخير يكفي؟', ['ليست بديلًا تلقائيًا', 'لم يتحقق هنا حد حاسم', 'علامة التغليف']),
    ('مواد كيميائية وخطرة SDS', ['CAS', 'الأولى والثالثة', 'لا تعممها', 'ليس قائمة الاستيراد']),
    ('جهاز Wi-Fi يحتاج رخصة تردد؟', ['فقط حين يتطلبه الجهاز', 'لا تطلب ترخيص تردد لكل', 'لا تثبت قبول جهاز']),
])
def test_sector_knowledge_is_conditional_and_preserves_gaps(question, required):
    text = g.guidance_for(question)
    for phrase in required:
        assert phrase in text


@pytest.mark.parametrize('question', ['كم أجور شهادة سابر؟', 'سابر مجاني؟', 'رسوم سابر كم؟', 'How much are SABER fees?'])
def test_saber_fee_matcher_covers_explicit_cost_subject(monkeypatch, question):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    assert g.SABER_FEE_QUERY.search(question)
    assert g.SABER_FEE_NOTE in asyncio.run(n.reply(question))


def test_saber_mixed_transport_does_not_substitute_certificate_cost(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    question = 'هل الخشب يحتاج سابر وكم سعر النقل من ميناء جدة إلى الرياض؟'
    result = asyncio.run(n.reply(question))
    assert g.SABER_FEE_NOTE not in result
    assert g.SABER_TRANSPORT_FEE_NOTE in result
    assert result.startswith(n.SABER_UNVERIFIED_REPLY)
