from app.driver_language import lang_hint, offer_ur, offer_en, accept_reply
from app.transport_desk import ACCEPT


def test_hints():
    assert lang_hint('????') == 'unclear'
    assert lang_hint('یہ لوڈ کہاں سے ہے') == 'ur'
    assert lang_hint('kitna kiraya hai bhai') == 'ur'
    assert lang_hint('how much?') == 'en'
    assert lang_hint('كم السعر؟') == 'ar'
    assert lang_hint('') == ''


def test_offer_texts():
    b = {'origin': 'جدة', 'destination': 'الرياض', 'weight': '27', 'driver_price': '5,160.00',
         'unloading': 'الرياض', 'payment': 'حسب الاتفاق'}
    ur = offer_ur('AFT-2', b)
    assert 'OK AFT-2' in ur and 'ٹن' in ur and '5,160.00' in ur and 'طے شدہ' in ur
    assert 'OK AFT-2' in offer_en('AFT-2', b) and 'as agreed' in offer_en('AFT-2', b)
    assert 'AFT-2' in accept_reply('ur', 'AFT-2') and accept_reply('ar', 'AFT-2') is None


def test_accept_words():
    for t in ('OK AFT-2', 'ٹھیک ہے AFT-2', 'yes AFT-2', 'موافق AFT-2'):
        assert ACCEPT.search(t)
