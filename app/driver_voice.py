"""Spoken replies for drivers (owner, 24 Nov 2026): drivers on the road cannot read or type while driving.

After a text reply to a driver is accepted by WhatsApp, the same reply is spoken (OpenAI text-to-speech, OGG/Opus)
and sent as a voice note in the driver's language. The text stays the record; the voice is a copy of it, so it never
says anything the guarded text did not. Customers who are not drivers keep text replies only.
"""
import hashlib
import os
import re

import httpx

URDU = re.compile(r'[ٹڈڑںےۓھہۂۃکی]')
ARABIC = re.compile(r'[؀-ۿ]')
LATIN = re.compile(r'[A-Za-z]')
EMOJI = re.compile(r'[\U0001F000-\U0001FAFF☀-➿️‍]')
VOICE_STYLE = {
    'ar': 'Speak Arabic with a clear, friendly Saudi (Najdi/Hijazi) accent, at a calm pace, like a dispatcher talking to a truck driver.',
    'ur': 'Speak Urdu clearly and slowly, in a friendly tone, like a dispatcher talking to a truck driver.',
    'en': 'Speak simple English clearly and slowly, in a friendly tone, like a dispatcher talking to a truck driver.',
}


def enabled():
    return os.getenv('DRIVER_VOICE_REPLIES', '1') == '1' and bool(os.getenv('OPENAI_API_KEY'))


def is_driver(phone):
    """A registered driver, or someone who received a load offer in the last 14 days."""
    from app.storage import db
    d = re.sub(r'\D', '', str(phone or ''))[-9:]
    if len(d) < 9:
        return False
    with db() as c:
        for sql in ("SELECT 1 FROM drivers WHERE right(regexp_replace(whatsapp_phone,'\\D','','g'),9)=%s LIMIT 1",
                    "SELECT 1 FROM load_broadcast_recipients WHERE right(phone,9)=%s AND sent_at > now() - interval '14 days' LIMIT 1"):
            try:
                if c.execute(sql, (d,)).fetchone():
                    return True
            except Exception:
                c.rollback() if hasattr(c, 'rollback') else None
    return False


def spoken_part(text):
    """(language, words to speak). A bilingual reply (Urdu block + English block) speaks the Urdu block only."""
    text = str(text or '').strip()
    blocks = [b.strip() for b in re.split(r'\n\s*\n', text) if b.strip()]
    urdu = [b for b in blocks if URDU.search(b)]
    if urdu:
        lang, chosen = 'ur', urdu
    elif ARABIC.search(text):
        lang, chosen = 'ar', [b for b in blocks if ARABIC.search(b)]
    else:
        lang, chosen = 'en', blocks
    words = '\n'.join(chosen)
    words = EMOJI.sub('', words)
    words = re.sub(r'https?://\S+', '', words)
    words = re.sub(r'AFT-(\d+)', r'AFT \1', words)
    words = re.sub(r'[•→←]', ' ', words)
    return lang, words.strip()[:1500]


async def speak(text, lang):
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post('https://api.openai.com/v1/audio/speech',
                              headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY']},
                              json={'model': os.getenv('DRIVER_VOICE_MODEL', 'gpt-4o-mini-tts'),
                                    'voice': os.getenv('DRIVER_VOICE_NAME', 'onyx'), 'input': text,
                                    'instructions': VOICE_STYLE.get(lang, VOICE_STYLE['en']), 'response_format': 'opus'})
        r.raise_for_status()
    if not r.content.startswith(b'OggS'):
        raise ValueError('speech output is not OGG/Opus')
    return r.content


async def after_text(job):
    """Called once the text reply was accepted. Sends the voice copy to drivers; never raises."""
    from app import zernio_whatsapp as z
    try:
        if not enabled():
            return False
        from starlette.concurrency import run_in_threadpool
        if not await run_in_threadpool(is_driver, job['sender']):
            return False
        lang, words = spoken_part(job.get('reply_text'))
        if len(words) < 2:
            return False
        audio = await speak(words, lang)
        key = 'wa-document-' + hashlib.sha256(('voice:' + str(job['idempotency_key'])).encode()).hexdigest()
        with z.automation_origin(job['account_id'], job['sender'], job['payload'].get('takeover_generation', 0)), \
                z.dispatch_guard(lambda: None):
            await z.send_voice(job['sender'], audio, 'afaq-reply.ogg', expected_account=job['account_id'],
                               expected_conversation=job['conversation_id'], idempotency_key=key)
        return True
    except Exception as exc:
        print('DRIVER_VOICE', type(exc).__name__, str(exc)[:160], flush=True)
        return False
