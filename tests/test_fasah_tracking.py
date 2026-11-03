import importlib.util, pathlib, sys, types
from unittest.mock import Mock, patch
_storage = types.ModuleType('app.storage'); _storage.db = Mock(side_effect=AssertionError('db')); _storage.utcnow = Mock()
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec = importlib.util.spec_from_file_location('_ft', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'fasah_tracking.py')
    ft = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ft)


def test_fasah_status_phrases():
    assert ft.classify('مرحلة إنتظار تحصيل الرسوم الجمركيه') == 'duties_due'
    assert ft.classify('جاهز لطباعة إشعار الفسح الجمركي') == 'released'
    assert ft.classify('فسح كلي') == 'released'
    assert ft.classify('تحت المعالجة') == 'under_review'
    assert ft.classify('لم يصل الى المنفذ') == 'not_arrived'
    assert ft.classify('انتهاء مراجعة مركز العمليات الجمركية') == 'reviewed'
    assert ft.classify('مسودة') == 'draft'
    assert ft.classify('سلة الرحائب ميناء جدة') == 'unknown'


def test_phone_and_customer_text():
    assert ft.phone_digits('0551234567') == '966551234567'
    assert ft.phone_digits('+966 55 123 4567') == '966551234567'
    assert ft.phone_digits('123') == ''
    text = ft.customer_text('418900', 'import', 'duties_due')
    assert '418900' in text and 'سداد الرسوم' in text and '0507665873' in text
    assert 'للتصدير' in ft.customer_text('206987', 'export', 'released')
    assert ft.customer_text('1', 'import', 'draft') is None
