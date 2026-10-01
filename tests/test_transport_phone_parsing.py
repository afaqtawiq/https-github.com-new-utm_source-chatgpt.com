"""Conservative international owner-phone extraction; no storage or sends."""
import pytest

from app.logistics_parsing import extract_phone
from app.transport_intake import extract_transport


@pytest.mark.parametrize("raw, expected", [
    ("0500000001", "+966500000001"),
    ("966500000001", "+966500000001"),
    ("+966500000001", "+966500000001"),
    ("00966500000001", "+966500000001"),
    ("(050) 000-0001", "+966500000001"),
    ("+966 (50) 000-0001", "+966500000001"),
    ("+971501234567", "+971501234567"),
    ("00971501234567", "+971501234567"),
    ("+971 (50) 123-4567", "+971501234567"),
    ("00 971 (50) 123 4567", "+971501234567"),
    ("+20 (100) 123-4567", "+201001234567"),
    ("+965 5123 4567", "+96551234567"),
    ("+1 (202) 555-0123", "+12025550123"),
    ("+44 20 7946 0958", "+442079460958"),
    ("+٩٧١ (٥٠) ١٢٣-٤٥٦٧", "+971501234567"),
    ("۰۰۹۷۱ (۵۰) ۱۲۳-۴۵۶۷", "+971501234567"),
    ("٠٥٠٠٠٠٠٠٠١", "+966500000001"),
    ("+971\u00a050\u00a0123\u00a04567", "+971501234567"),
])
def test_extract_supported_phone_formats(raw, expected):
    assert extract_phone(raw) == expected
    result = extract_transport("طلب نقل\nمن جدة إلى دبي\nجوال صاحب الشحنة: " + raw + "\nالوزن: 20 طن")
    assert result == dict(origin="جدة", destination="دبي", owner_phone=expected, weight_tons=20.0)


@pytest.mark.parametrize("text", [
    "السعر: 2500 ريال\nالوزن: 20 طن",
    "السعر: +25000000 ريال",
    "الوزن: 001234567890 كجم",
    "price: +25000000 USD",
    "weight: 001234567890 kg",
    "السعر: 0500000001",
    "+123",                         # Incomplete international number.
    "+1234567890123456",            # Longer than E.164, no truncation.
    "009715012345678901234",
    "971501234567",                 # Do not infer a foreign country prefix.
    "201001234567",
    "123450500000001",              # Do not extract a Saudi suffix.
    "+971501234567x",
    "+9715012345 67999x",            # Do not backtrack to a shorter phone.
    "+971501234567 123456x",
    "+971501234567.89",             # A decimal amount is not a phone.
    "0500000001.20",
    "20.0500000001",
    "ref971501234567",
    "رقم الطلب: 202609240001",
    "السعر: 2,500.00 ريال\nوزن الحمولة: ٢٠ طن",
])
def test_reject_non_phone_numbers_and_incomplete_candidates(text):
    assert extract_phone(text) == ""


@pytest.mark.parametrize("separator", [" / ", "، ", "\n", "; ", " "])
def test_multiple_distinct_numbers_require_review(separator):
    assert extract_phone("+971501234567" + separator + "+966500000001") == ""


def test_repeated_normalized_phone_is_one_contact():
    assert extract_phone("+971 (50) 123-4567 / 00971501234567") == "+971501234567"
    assert extract_phone("0500000001، +966500000001") == "+966500000001"


def test_unlabeled_international_phone_does_not_absorb_other_lines():
    result = extract_transport("طلب نقل\nمن جدة إلى دبي\n+971501234567\n20\nالسعر: 2500 ريال")
    assert result["owner_phone"] == "+971501234567"


def test_labelled_owner_takes_priority_over_employee_contact():
    result = extract_transport("طلب نقل\nمن جدة إلى دبي\nجوال الموظف: +966500000009\nجوال صاحب الحمولة: +971 (50) 123-4567\nالوزن: 20 طن")
    assert result["owner_phone"] == "+971501234567"


def test_multiple_labelled_owner_numbers_are_not_arbitrarily_selected():
    result = extract_transport("طلب نقل\nمن جدة إلى دبي\nجوال صاحب الشحنة: +971501234567 / +201001234567")
    assert result["owner_phone"] == ""
