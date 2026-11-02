import importlib.util, pathlib, sys, types
from unittest.mock import Mock, patch
import fastapi  # noqa: F401
_storage = types.ModuleType('app.storage'); _storage.db = Mock(side_effect=AssertionError('db'))
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec = importlib.util.spec_from_file_location('_cd', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'collections_desk.py')
    cd = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(cd)


def test_find_party_and_text(monkeypatch):
    rows = [{'id': 3, 'name': 'الياسمين', 'receivable_minor': 377189, 'oldest_claim': None, 'last_receipt': None, 'drafts': 2},
            {'id': 4, 'name': 'عمران (إقبال)', 'receivable_minor': 100, 'oldest_claim': None, 'last_receipt': None, 'drafts': 0}]
    monkeypatch.setattr(cd, 'balances', lambda: rows)
    assert cd.find_party('ياسمين')['id'] == 3
    assert '3,771.89' in cd.customer_balance_text('الياسمين')
    assert 'مسودات' in cd.customer_balance_text('الياسمين')
    assert cd.record_payment('غير موجود', '10', 1).startswith('لم أجد')
