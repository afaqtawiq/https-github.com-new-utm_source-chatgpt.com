import datetime as dt
import importlib.util, pathlib, sys, types
from unittest.mock import Mock, patch
_storage = types.ModuleType('app.storage'); _storage.db = Mock(side_effect=AssertionError('db')); _storage.utcnow = Mock()
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec = importlib.util.spec_from_file_location('_cr', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'container_returns.py')
    cr = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(cr)


def test_container_number_and_dates():
    assert cr.number('الحاوية msku 1234567 رجعت') == 'MSKU1234567'
    assert cr.number('TEST0000001') == 'TEST0000001'
    assert cr.number('بدون رقم') == ''
    assert cr.date('2026-11-10') == dt.date(2026, 11, 10)
    assert cr.date('١٠/١١/٢٠٢٦') == dt.date(2026, 11, 10)


def test_card_shows_overdue_cost():
    row = {'container': 'MSKU1234567', 'is_test': False, 'status': 'delivered', 'free_until': dt.date.today() - dt.timedelta(days=3),
           'daily_cost': 250, 'customer': 'الحياة', 'return_place': 'ساحة جدة'}
    text = cr.card(row)
    assert 'متأخرة 3 يوم' in text and '750' in text and 'ساحة جدة' in text


def test_reminders_name_place_and_date():
    row = {'container': 'MSKU1234567', 'free_until': dt.date(2026, 11, 10), 'return_place': 'ساحة جدة'}
    customer, driver = cr.reminder_texts(row)
    assert '10/11' in customer and 'ساحة جدة' in driver and 'EIR' in driver
