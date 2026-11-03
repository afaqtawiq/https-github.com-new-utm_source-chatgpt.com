import importlib.util, pathlib, sys, types
from unittest.mock import Mock, patch
_storage = types.ModuleType('app.storage'); _storage.db = Mock(side_effect=AssertionError('db')); _storage.utcnow = Mock()
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec = importlib.util.spec_from_file_location('_pr', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'prospect_replies.py')
    pr = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(pr)


def test_prices_come_from_approved_knowledge():
    tiers, routes = pr.price_table()
    assert tiers == {1: 400, 2: 250, 6: 200}
    assert routes['من ميناء جدة الإسلامي إلى الرياض'] == 4500


def test_quote_tiers_and_unknown_route():
    text, total, missing = pr.build_quote('س', {'containers': 7, 'route_key': 'من ميناء جدة الإسلامي إلى الخرج'}, 'ATQ-1')
    assert total == 7 * 200 + 7 * 4600 and 'ATQ-1' in text and 'لا تشمل' in text and not missing
    text, total, missing = pr.build_quote('س', {'containers': 1, 'port': 'الدمام', 'destination': 'الرياض'}, 'ATQ-2')
    assert total == 400 and missing == ['سعر النقل لمسار الدمام → الرياض']
    assert pr.build_quote('س', {'service': 'نقل فقط', 'destination': 'تبوك'}, 'ATQ-3')[0] is None


def test_keyword_fallback():
    assert pr.fallback('إيقاف')['intent'] == 'stop'
    assert pr.fallback('لا شكرا')['intent'] == 'not_interested'
    assert pr.fallback('كم السعر؟')['intent'] == 'price_request'
    assert pr.fallback('مرحبا')['intent'] == 'other'
