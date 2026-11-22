from app import reply_language as rl


def test_english_customer_gets_english(monkeypatch):
    monkeypatch.setattr(rl, 'customer_language', lambda job: 'en')
    monkeypatch.setattr(rl, 'translate', lambda text, lang: 'You can reach the Afaq Tuwaiq team on 0507665873.')
    job = {'reply_text': 'تقدر تتواصل مع فريق آفاق طويق على 0507665873', 'payload': {'lang': 'en'}, 'conversation_id': 'c'}
    assert rl.localized_reply(job).startswith('You can reach')


def test_arabic_customer_and_failures_keep_arabic(monkeypatch):
    monkeypatch.setattr(rl, 'translate', lambda text, lang: None)
    monkeypatch.setattr(rl, 'customer_language', lambda job: 'en')
    job = {'reply_text': 'وصلت رسالتك', 'payload': {}, 'conversation_id': 'c'}
    assert rl.localized_reply(job) == 'وصلت رسالتك'
    monkeypatch.setattr(rl, 'customer_language', lambda job: 'ar')
    assert rl.localized_reply(job) == 'وصلت رسالتك'
    urdu = {'reply_text': 'لوڈ کی پیشکش ہے آپ کے لیے', 'payload': {}, 'conversation_id': 'c'}
    assert rl.localized_reply(urdu) == urdu['reply_text']
    assert rl.detect('Can I call you') == 'en' and rl.detect('你好，我想清关') == 'zh' and rl.detect('ابغى اخلص') == 'ar'


def test_every_language_both_ways(monkeypatch):
    monkeypatch.setattr(rl, 'translate', lambda text, lang: 'T:' + lang)
    for lang, reply in (('ar', 'Welcome! It seems the message did not come through correctly.'),
                        ('en', 'وصلت رسالتك'), ('zh', 'وصلت رسالتك'), ('hi', 'Your shipment arrives tonight.'),
                        ('ur', 'وصلت رسالتك')):
        monkeypatch.setattr(rl, 'customer_language', lambda job, l=lang: l)
        assert rl.localized_reply({'reply_text': reply, 'payload': {}, 'conversation_id': 'c'}) == 'T:' + lang
    monkeypatch.setattr(rl, 'customer_language', lambda job: 'ar')
    assert rl.localized_reply({'reply_text': 'Ref: AF-133 / رقم الطلب', 'conversation_id': 'c'}) == 'Ref: AF-133 / رقم الطلب'
    assert rl.detect('मेरा कंटेनर कब आएगा') == 'hi' and rl.detect('میرا کنٹینر کب آئے گا') == 'ur'
    assert rl.detect('bhai load kab hai') == 'ur' and rl.detect('مرحبا، باقي عندك حمولات لليوم؟') == 'ar'


def test_short_latin_does_not_switch_to_english():
    from app.reply_language import decisive
    assert not decisive('OK', 'en') and not decisive('Hi', 'en')
    assert decisive('Please send me the rate for Jeddah', 'en')
    assert decisive('مرحبا', 'ar') and decisive('ٹھیک ہے', 'ur') and decisive('thik hai bhai jan', 'ur')
    assert decisive('你好', 'zh') and decisive('ठीक है', 'hi')
