import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import driver_voice as dv


def test_spoken_part_prefers_urdu_block_and_cleans_symbols():
    text = 'آفاق طویق کی طرف سے لوڈ کی پیشکش — AFT-3\nروٹ: ام القیوین ← جدہ 👍\n\nLoad offer from Afaq Tuwaiq — AFT-3'
    lang, words = dv.spoken_part(text)
    assert lang == 'ur' and 'Load offer' not in words and 'AFT 3' in words and '👍' not in words and '←' not in words
    assert dv.spoken_part('تم تسجيل موافقتك على الحمولة AFT-2')[0] == 'ar'
    assert dv.spoken_part('Your acceptance of load AFT-2 is recorded')[0] == 'en'


def test_after_text_sends_voice_only_to_drivers(monkeypatch):
    sent = []

    async def speak(words, lang):
        return b'OggS-audio'

    async def send_voice(to, audio, name, **kw):
        sent.append((to, audio, kw['idempotency_key']))
    from app import zernio_whatsapp as z
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic')
    monkeypatch.setattr(dv, 'speak', speak)
    monkeypatch.setattr(z, 'send_voice', send_voice)
    job = {'sender': '966539206035', 'reply_text': 'Load offer AFT-3', 'idempotency_key': 'wa-agent-' + '0' * 64,
           'account_id': z.account_id() or 'acc', 'conversation_id': 'c1', 'payload': {}}
    monkeypatch.setattr(dv, 'is_driver', lambda phone: False)
    assert asyncio.run(dv.after_text(job)) is False and not sent
    monkeypatch.setattr(dv, 'is_driver', lambda phone: True)
    assert asyncio.run(dv.after_text(job)) is True
    assert sent[0][0] == '966539206035' and sent[0][1] == b'OggS-audio' and sent[0][2].startswith('wa-document-')
