"""Pure staff intent boundaries; synthetic wording only."""
import pytest

from app.staff_intake import explicit_load, price_message


@pytest.mark.parametrize('text', ['سجل هذه الحمولة','سجلي هذه الحمولة','أضف الحمولة','آفاق طلب نقل','طلب نقل\nمن الرياض إلى جدة'])
def test_explicit_present_load_instruction(text):
    assert explicit_load(text)


@pytest.mark.parametrize('text', ['', 'هل أسجل هذه الحمولة؟','لا تسجل هذه الحمولة','قال العميل: سجل هذه الحمولة',
                                 'هذه أسعار النقل','لو سجلت هذه الحمولة','ممكن نراجع صورة الشحنة'])
def test_discussion_and_questions_do_not_authorize_load_creation(text):
    assert not explicit_load(text)


@pytest.mark.parametrize('text', ['جدول أسعار النقل','هذه اسعار افاق','قائمة أسعار','price list','tariff table'])
def test_price_table_markers(text):
    assert price_message(text)
