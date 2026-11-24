from app import whatsapp_natural as n
from app.customs_knowledge import KNOWLEDGE


def test_safe_accepts_grounded_answer():
    assert n.safe('نعم نقدم التخليص الجمركي. تواصل معنا على 0507665873', KNOWLEDGE)


def test_safe_rejects_action_claims_and_foreign_numbers():
    assert n.safe('سأحجز النقل.', KNOWLEDGE) is None
    assert n.safe('تم الحجز لك', KNOWLEDGE) is None
    assert n.safe('كلم المندوب على 0551234567', KNOWLEDGE) is None
    assert n.safe('x' * 2300, KNOWLEDGE) is None


def test_history_messages_shape():
    msgs = n.messages('ومن جدة؟', [{'question': 'كم النقل للرياض', 'reply': 'من جدة 4500'}])
    assert [m['role'] for m in msgs] == ['user', 'assistant', 'user']


def test_clearance_without_saber_gets_import_on_behalf_offer():
    from app import whatsapp_natural as wn
    q = ('This is Mohammed from Domkoly Shipping LLC. We have regular shipments from Dubai to Saudi Arabia, and I would like '
         'to inquire whether you can arrange customs clearance at the Batha border without requiring a SABER certificate.')
    en = wn.import_on_behalf_reply(q)
    assert 'SAR 800' in en and 'SAR 1,400' in en and 'SAR 300' in en and '2.5%' in en and '15%' in en and 'customs duties' in en
    ar = wn.import_on_behalf_reply('ابغى اخلص شحنة بدون سابر')
    assert '800 ريال' in ar and '1400 ريال' in ar and '300 ريال' in ar and '2.5%' in ar and '15%' in ar
    assert wn.import_on_behalf_reply('كم سعر شهادة سابر؟') is None
