"""Regression coverage for the approved land-export fee; no live network or sends."""
import asyncio
import hashlib
import importlib.util
import json
import pathlib
import sys
import types
from unittest.mock import Mock, patch

import httpx
import pytest

from app.customs_knowledge import KNOWLEDGE
from app import whatsapp_agent_privacy as privacy
from app import whatsapp_natural as natural

ROOT = pathlib.Path(__file__).resolve().parents[1]
FEE = 'أجور تخليص الصادر عبر المنافذ البرية: 200 ريال سعودي لكل بوليصة أو شحنة تريلا واحدة، تكلفة التخليص فقط، ولا تشمل أي رسوم أو تكاليف أخرى.'


def isolated_module(name, path, patches):
    with patch.dict(sys.modules, patches):
        spec = importlib.util.spec_from_file_location(name, ROOT / path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


storage = types.ModuleType('app.storage')
storage.db = Mock(side_effect=AssertionError('No real database access'))
storage.utcnow = Mock()
prospects = isolated_module('_land_export_prospects', 'app/prospect_replies.py', {'app.storage': storage})
calculator = isolated_module('_land_export_calculator', 'app/price_calculator.py', {'app.storage': storage})


def test_knowledge_has_exact_unit_scope_exclusions_and_no_inferred_tax():
    assert KNOWLEDGE.count(FEE) == 1
    assert 'لا تعممه على الصادر البحري أو الجوي' in KNOWLEDGE
    assert 'لا تفترض عدد البوالص أو شحنات التريلا من عدد الحاويات' in KNOWLEDGE
    assert 'لا تفترض أن 200 ريال شامل أو غير شامل لضريبة القيمة المضافة' in KNOWLEDGE
    assert 'مستقلة عن مدة عرض السعر العام أعلاه' in KNOWLEDGE


def test_existing_prices_and_transport_routes_are_unchanged():
    tiers, routes = prospects.price_table()
    assert tiers == {1: 400, 2: 250, 6: 200}
    assert routes == {
        'من ميناء جدة الإسلامي إلى جدة (الخمرة)': 900,
        'من ميناء جدة الإسلامي إلى الرياض': 4500,
        'من ميناء جدة الإسلامي إلى الخرج': 4600,
        'من ميناء جدة الإسلامي إلى القصيم': 4500,
        'من ميناء الملك عبدالله (رابغ) إلى الرياض': 6000,
        'من ميناء الملك عبدالله (رابغ) إلى القصيم': 6000,
        'من ميناء الملك عبدالله (رابغ) إلى جدة': 2000,
        'من جدة (الميناء) إلى جدة (الصناعية)': 1300,
        'من جدة (الميناء) إلى جدة (الساحة)': 500,
        'من جدة (الساحة) إلى جدة (الخمرة)': 750,
        'من جدة (الساحة) إلى جدة (الصناعية)': 1000,
    }


def test_public_knowledge_pin_updated_without_expanding_privacy_scope():
    assert hashlib.sha256(KNOWLEDGE.encode()).hexdigest() == privacy._PUBLIC_KNOWLEDGE_SHA256
    assert privacy._PUBLIC_KNOWLEDGE_SECTIONS == {17}
    assert 'التخليص في جميع المنافذ السعودية' in privacy._public_knowledge()
    assert '200' not in privacy._public_knowledge()


@pytest.mark.parametrize('question', [
    'كم تخليص صادر بري لكل تريلا؟',
    'عندي بوليصة صادر من منفذ بري كم أجوركم؟',
    'هل 200 ريال تشمل الرسوم وأي تكاليف أخرى؟',
])
def test_natural_prompt_receives_land_scope_and_exact_fee(monkeypatch, question):
    original = httpx.AsyncClient
    requests = []

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert FEE in body['system']
        assert 'لا تعممه على الصادر البحري أو الجوي' in body['system']
        assert 'لا تستخدم شرائح الحاويات أو تستنتج المعاملة الضريبية' in body['system']
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': FEE}]})

    async def deny_network(*args, **kwargs):
        raise AssertionError('Live network is not permitted')

    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', deny_network)
    monkeypatch.setattr(natural.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'local-test-only')
    monkeypatch.setenv('WHATSAPP_NATURAL_MODEL', 'claude-local-test')
    monkeypatch.setenv('WHATSAPP_NATURAL_REPLIES', '1')
    assert asyncio.run(natural.reply(question)) == FEE
    assert len(requests) == 1


@pytest.mark.parametrize('details', [
    {'service': 'تخليص صادر بري', 'containers': 1},
    {'service': 'تصدير', 'containers': 7},
    {'customs_direction': 'export', 'containers': 7},
    {'summary': 'export customs clearance', 'containers': 1},
    {'summary': 'customs for exported goods', 'containers': 1},
    {'service': 're-export customs', 'containers': 1},
    {'service': 'تخليص للتصدير', 'containers': 1},
    {'summary': '出口清关', 'containers': 7},
    {'service': 'تخليص صادر بحري', 'route_key': 'من ميناء جدة الإسلامي إلى الرياض'},
    {'service': 'تخليص الصادر الجوي', 'containers': 1},
])
def test_export_cannot_receive_container_tier_or_import_transport_quote(details):
    text, total, missing = prospects.build_quote('شركة اختبار', details, 'LOCAL-TEST')
    assert text is None and total == 0
    assert missing == ['تأكيد منفذ التصدير وعدد البوالص أو شحنات التريلا قبل إعداد عرض الصادر']


@pytest.mark.parametrize('message', ['كم تخليص الصادر؟', 'export clearance price', 'سعر تصدير تريلا', '出口价格'])
def test_classifier_fallback_preserves_export_scope_without_model(monkeypatch, message):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    details = prospects.classify(message)
    assert details['customs_direction'] == 'export'
    assert prospects.build_quote('شركة اختبار', details, 'LOCAL-TEST')[0] is None


def test_classifier_cannot_lose_explicit_export_scope(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'local-test-only')
    with patch.object(httpx, 'post', return_value=Mock(json=lambda: {'content': [{'type': 'text', 'text': '{"intent":"price_request","service":"تخليص","containers":1}'}]})):
        data = prospects.classify('كم سعر تخليص الصادر البري لتريلا؟')
    assert data['customs_direction'] == 'export'
    assert prospects.build_quote('شركة اختبار', data, 'LOCAL-TEST')[0] is None


@pytest.mark.parametrize('n,expected', [(1,400),(2,500),(5,1250),(6,1200),(200,40000)])
def test_legacy_container_calculation_unchanged(monkeypatch, n, expected):
    tiers, routes = prospects.price_table()
    monkeypatch.setattr(calculator, 'prices', lambda: {'tiers': tiers, 'routes': routes})
    assert calculator.compute('clearance', '', n) == (n, expected, 0)
    assert calculator.compute('both', 'من ميناء جدة الإسلامي إلى الرياض', n) == (n, expected, n * 4500)


def test_calculator_explicitly_excludes_land_export_and_explains_its_fee(monkeypatch):
    tiers, routes = prospects.price_table()
    monkeypatch.setattr(calculator, 'prices', lambda: {'tiers': tiers, 'routes': routes})
    html = calculator.page().body.decode()
    assert 'لا تُستخدم نتائج هذه الحاسبة لتخليص الصادر عبر المنافذ البرية' in html
    assert '200 ريال لكل بوليصة أو شحنة تريلا واحدة' in html
    assert 'تكلفة التخليص فقط، ولا تشمل أي رسوم أو تكاليف أخرى' in html
    assert 'أجور التخليص نفسها في جميع المنافذ' not in html


def test_export_detection_does_not_confuse_sources_with_exports():
    assert not prospects.export_request({'source_text': 'ما مصادر الأسعار؟'})


def test_land_export_lead_does_not_use_container_total_or_touch_database():
    class Request:
        async def json(self):
            return {'scope': 'land_export', 'containers': 7, 'service': 'both'}
    response = asyncio.run(calculator.lead(Request()))
    assert response.status_code == 400
    assert '200 ريال لكل بوليصة أو شحنة تريلا واحدة' in json.loads(response.body)['error']
    storage.db.assert_not_called()


def test_calculator_ui_scope_switches_hide_wrong_totals_and_restore_containers(monkeypatch):
    import re
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is needed for frontend scope regression')
    tiers, routes = prospects.price_table()
    monkeypatch.setattr(calculator, 'prices', lambda: {'tiers': tiers, 'routes': routes})
    html = calculator.page().body.decode()
    script = re.search(r'<script>(.*?)</script>', html, re.S).group(1)
    harness = r"""
const assert = require('node:assert/strict');
const ids = ['scope','n','route','containerOptions','containerResult','leadForm','exportResult','c','t','tot','routeBox','go','err'];
const elems = Object.fromEntries(ids.map(id => [id,{value:'',hidden:false,style:{},textContent:''}]));
elems.scope.value='containers';elems.n.value='1';elems.route.value='من ميناء جدة الإسلامي إلى الرياض';
const document={getElementById:id=>elems[id],querySelectorAll:()=>[]};
"""
    checks = r"""
assert.equal(elems.tot.textContent,'4,900 ريال');
assert.equal(elems.exportResult.hidden,true);
for (let i=0;i<3;i++) {
 elems.scope.value='land_export';elems.scope.oninput();
 assert.equal(elems.containerResult.hidden,true);
 assert.equal(elems.containerOptions.hidden,true);
 assert.equal(elems.leadForm.hidden,true);
 assert.equal(elems.exportResult.hidden,false);
 elems.n.value='7';elems.n.oninput();
 assert.equal(elems.containerResult.hidden,true);
 elems.scope.value='containers';elems.scope.oninput();
 assert.equal(elems.containerResult.hidden,false);
 assert.equal(elems.containerOptions.hidden,false);
 assert.equal(elems.leadForm.hidden,false);
 assert.equal(elems.exportResult.hidden,true);
 assert.equal(elems.tot.textContent,'32,900 ريال');
}
"""
    subprocess.run([node, '-e', harness + script + checks], check=True, capture_output=True, text=True)
