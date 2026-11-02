from app import whatsapp_natural as n
from app.customs_knowledge import KNOWLEDGE


def test_safe_accepts_grounded_answer():
    assert n.safe('نعم نقدم التخليص الجمركي. تواصل معنا على 0507665873', KNOWLEDGE)


def test_safe_rejects_action_claims_and_foreign_numbers():
    assert n.safe('سأحجز النقل.', KNOWLEDGE) is None
    assert n.safe('تم الحجز لك', KNOWLEDGE) is None
    assert n.safe('كلم المندوب على 0551234567', KNOWLEDGE) is None
    assert n.safe('x' * 2000, KNOWLEDGE) is None


def test_history_messages_shape():
    msgs = n.messages('ومن جدة؟', [{'question': 'كم النقل للرياض', 'reply': 'من جدة 4500'}])
    assert [m['role'] for m in msgs] == ['user', 'assistant', 'user']
