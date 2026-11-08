"""Dated official SABER guidance wiring; no live model, database, lookup or sends."""
import asyncio
import ast
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from app.customs_knowledge import KNOWLEDGE
from app import whatsapp_agent_privacy as privacy
from app import whatsapp_natural as natural

ROOT = Path(__file__).resolve().parents[1]
LOOKUP = 'https://saber.sa/Home/HSCodes'
NONREGULATED = 'https://saber.sa/Home/NonRegulatedProducts'
SOURCE = 'https://www.saso.gov.sa/ar/mediacenter/news/Pages/saso-news-1483.aspx'
TERMS = 'https://saber.sa/Home/Terms'


def test_knowledge_distinguishes_product_self_declaration_and_shipment_routes():
    section = KNOWLEDGE.split('3) منصة سابر', 1)[1].split('4) منتجات', 1)[0]
    for required in ('1 أكتوبر 2025', 'الخاضعة وغير الخاضعة', 'قبل تقديم البيان الجمركي',
                     'عدم الخضوع للائحة فنية لا يعني الإعفاء من سابر',
                     'شهادة مطابقة المنتج', 'إقرار ذاتي', 'شهادة الإرسالية',
                     '252520000000', '320649000001', 'ليست قائمة شاملة',
                     'لا تعمم مثالًا على فصل جمركي كامل',
                     'لا توجد هنا وثيقة رسمية تثبت إعفاء جميع أنواعه',
                     'الحجري/المعدني', 'الفحم النباتي/الخشبي',
                     'عدم ظهور نتيجة ليس إعفاءً', 'لا توفر بحثًا حيًا تلقائيًا',
                     LOOKUP, NONREGULATED, SOURCE, TERMS):
        assert required in section


def test_guarded_guidance_has_same_regulatory_boundaries_and_official_sources():
    system = privacy._CUSTOMS_GUIDANCE_SYSTEM
    for required in ('2026-11-07', 'regulated AND', 'Nonregulated is NOT exempt',
                     '12-digit HS code', 'no live Saber', 'missing result means unverified',
                     'No verified blanket exemption for coal or charcoal',
                     'product-certificate exemption do NOT establish',
                     '252520000000', '320649000001', 'not permanent shipment determinations',
                     LOOKUP, NONREGULATED, SOURCE, TERMS):
        assert required in system


def test_updated_hash_preserves_public_knowledge_allowlist_and_document_boundary():
    assert hashlib.sha256(KNOWLEDGE.encode()).hexdigest() == privacy._PUBLIC_KNOWLEDGE_SHA256
    assert privacy._PUBLIC_KNOWLEDGE_SECTIONS == {17}
    public = privacy._public_knowledge()
    assert 'تنسيق شهادات سابر' in public
    assert '252520000000' not in public
    assert '320649000001' not in public
    assert LOOKUP not in public


@pytest.mark.parametrize('question,answer,tariff_boundary', [
    ('الفحم مستثنى من سابر صح؟',
     'لا أقدر أؤكد إعفاء الفحم بشكل عام. هل المقصود فحم نباتي أو حجري، وما رمزه الجمركي إن توفر؟', False),
    ('البضاعة غير خاضعة للوائح يعني ما تحتاج سابر؟',
     'غير الخاضع للائحة فنية يحتاج إقرارًا ذاتيًا ثم شهادة الإرسالية، وليس إعفاءً من سابر.', False),
    ('عطني المنتجات والبنود اللي عليها شهادة مطابقة واللي ما عليها',
     'التصنيف يعتمد على البند الكامل والوصف. القائمة الرسمية: https://saber.sa/Home/HSCodes', False),
    ('البند الجمركي ما ظهر في سابر هل هو معفى؟',
     'عدم ظهور البند ليس إعفاءً. يلزم مراجعة الرمز والوصف مع الفريق.', True),
    ('البند 252520000000 عليه شهادة مطابقة منتج؟',
     'مسحوق ميكا ظهر في القائمة غير الخاضعة وقت المراجعة؛ يلزم تأكيد التصنيف الحالي قبل الشحن.', False),
    ('استورد فحم والرسوم الجمركية صفر، خلاص ما أحتاج سابر؟',
     'الإعفاء الجمركي لا يحدد حالة سابر. يلزم التحقق من نوع الفحم والبند الكامل.', True),
])
def test_natural_prompt_receives_saber_boundaries_and_sources(monkeypatch, question, answer, tariff_boundary):
    requests = []
    original = httpx.AsyncClient

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert KNOWLEDGE in body['system']
        assert 'لا تؤكد إعفاء الفحم أو حالة بند غير متحققة' in body['system']
        assert 'ولا تدّعِ بحثًا حيًا في سابر دون نتيجة ناجحة' in body['system']
        assert LOOKUP in body['system'] and SOURCE in body['system']
        assert [tool['name'] for tool in body['tools']] == ['tariff_search', 'saber_search']
        if len(requests) == 1:
            assert body['messages'][-1]['content'] == question
            assert body['tool_choice'] == {'type': 'tool', 'name': 'saber_search'}
            return httpx.Response(200, json={'content': [{'type': 'tool_use', 'id': 'reference-test',
                'name': 'saber_search', 'input': {'query': ''}}]})
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': answer}]})

    async def deny_network(*args, **kwargs):
        raise AssertionError('No live network permitted')

    monkeypatch.setenv('WHATSAPP_NATURAL_REPLIES', '1')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-only-local')
    monkeypatch.setenv('WHATSAPP_NATURAL_MODEL', 'claude-test')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', deny_network)
    monkeypatch.setattr(natural.httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(handle), **kwargs))
    result = asyncio.run(natural.reply(question))
    # A customs-code/duty premise is not verified by an empty SABER query.
    # Preserve the exact deterministic answer and label only that unchecked
    # premise; no additional model turn or tariff lookup is implied.
    expected = natural.SABER_GENERAL_REPLY
    if tariff_boundary:
        expected += ('\n\nوبخصوص البند أو الرسم الجمركي، نتيجة سابر لا تحددهما؛ '
                     'لم أتحقق هنا من تعرفة هذه البضاعة، ويلزم بحث مستقل ومراجعة البند السعودي الساري قبل الاعتماد.')
    assert result == expected
    assert len(requests) == 1


def test_fasah_classification_cannot_use_duty_data_as_live_saber_status():
    tree = ast.parse((ROOT / 'app/fasah_ai.py').read_text())
    classify = next(ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == 'CLASSIFY'
                        for target in node.targets))
    for required in ('not a verified live SABER classification', 'coal/charcoal',
                     'Distinguish product COC, self-declaration and shipment certificate',
                     'no live SABER lookup'):
        assert required in classify
