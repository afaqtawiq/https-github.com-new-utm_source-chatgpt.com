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
