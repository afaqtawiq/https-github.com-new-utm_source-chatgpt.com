from decimal import Decimal as D
import importlib.util, pathlib, sys, types
from unittest.mock import Mock, patch
import fastapi  # noqa: F401
_storage = types.ModuleType('app.storage')
for _n in ('db', 'utcnow', 'log'):
    setattr(_storage, _n, Mock(side_effect=AssertionError('storage touched')))
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec = importlib.util.spec_from_file_location('_br', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'billing_rules.py')
    br = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(br)


def by_party(items):
    return {i['party']: i for i in items}


def test_yasmen_claim_and_salla_half():
    items = by_party(br.compute({'kind': 'import', 'party': 'مؤسسة سلة الرحائب للتجارة', 'invoice_no': 'AB-584',
                                 'invoice_value': '7000', 'duty': '434.53', 'other': '15'}))
    assert items['الياسمين']['amount'] == D('4124.53')
    assert items['سلة الرحائب']['amount'] == D('825.00')


def test_omran_claim():
    items = by_party(br.compute({'kind': 'import', 'party': 'سلة الرحائب', 'invoice_no': 'IR-7231', 'invoice_value': '20500', 'supplier': 'شركة أخرى'}))
    assert items['عمران']['amount'] == D('3875.00')
    assert items['سلة الرحائب']['amount'] == D('1837.50')


def test_export_salla_100_and_supplier_name_wins():
    assert br.compute({'kind': 'export', 'party': 'مؤسسة سلة الرحائب للتجارة'})[0]['amount'] == D('100.00')
    items = by_party(br.compute({'kind': 'import', 'party': 'x', 'supplier': 'الياسمين', 'invoice_value': '500', 'duty': '200'}))
    assert items['الياسمين']['amount'] == D('200') + 300 + 1450 + 700 + D('75.00') + D('12.50')
    assert 'سلة الرحائب' not in items
