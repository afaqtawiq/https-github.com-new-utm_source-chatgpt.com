"""Owner, 21 Nov 2026: «العميل يرسل بالإنجليزي والوكيل يرد بالعربي — كارثة». Replies of the WhatsApp agent go out in the
customer's language (Arabic / English / Chinese). Side-effect free: no import of app.multilingual (it patches the intake)."""
import json
import os
import re

NAMES = {'en': 'English', 'zh': 'Simplified Chinese', 'ar': 'Arabic (polite Saudi business Arabic)',
         'hi': 'Hindi (Devanagari script)', 'ur': 'Urdu (Urdu script)'}
URDU_STRONG = re.compile(r'[ٹڈڑںےۓہۂ]')
URDU_WEAK = re.compile(r'[کیھگچپژ]')
ROMAN_URDU = re.compile(r'\b(ki|kya|kia|hai|hain|nahi|nahin|bhai|kitna|kahan|theek|thik|haan|jani|yaar|mujhe|aap|apka|kab)\b', re.I)


def detect(text):
    """'ar' / 'en' / 'zh' / 'hi' / 'ur' of a message, '' when it has no readable words (sticker, emoji, number)."""
    text = str(text or '')
    cjk = len(re.findall(r'[一-鿿]', text))
    deva = len(re.findall(r'[ऀ-ॿ]', text))
    arabic = len(re.findall(r'[؀-ۿ]', text))
    latin = len(re.findall(r'[A-Za-z]', text))
    if cjk >= 2 and cjk >= arabic:
        return 'zh'
    if deva >= 2 and deva >= latin / 2:
        return 'hi'
    if arabic >= 2 and arabic >= latin / 2:
        if URDU_STRONG.search(text) or len(URDU_WEAK.findall(text)) >= 3:
            return 'ur'
        return 'ar'
    if latin >= 3:
        return 'ur' if len(ROMAN_URDU.findall(text)) >= 2 else 'en'
    return ''


def customer_language(job):
    """Language of this message, else the one remembered for the conversation ('ar' by default)."""
    lang = (job.get('payload') or {}).get('lang') or ''
    try:
        from app.storage import db
        with db() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS conversation_languages(
                conversation_id TEXT PRIMARY KEY, lang TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')
            if lang:
                c.execute('''INSERT INTO conversation_languages(conversation_id,lang) VALUES(%s,%s)
                    ON CONFLICT(conversation_id) DO UPDATE SET lang=EXCLUDED.lang,updated_at=NOW()''', (job['conversation_id'], lang))
                return lang
            row = c.execute('SELECT lang FROM conversation_languages WHERE conversation_id=%s', (job['conversation_id'],)).fetchone()
            return row['lang'] if row else 'ar'
    except Exception as exc:
        print('WA_AGENT_LANGUAGE', type(exc).__name__, str(exc)[:120], flush=True)
        return lang or 'ar'


def translate(text, target):
    import httpx
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key:
        return None
    system = ('You translate WhatsApp replies of Afaq Tuwaiq, a Saudi customs clearance and logistics company. Translate into '
              f'natural, polite business {NAMES[target]}. Keep exactly: codes (AF-12, NQ-5, AFT-3...), phone numbers, emails, '
              'URLs, numbers, amounts, dates, company and place names. Keep line breaks. Add or remove nothing. '
              'Return ONLY a JSON array with one string.')
    body = {'model': os.getenv('TRANSLATE_MODEL', 'claude-sonnet-5'), 'max_tokens': 2000, 'system': system,
            'messages': [{'role': 'user', 'content': json.dumps([text], ensure_ascii=False)}]}
    try:
        with httpx.Client(timeout=25) as client:
            r = client.post('https://api.anthropic.com/v1/messages', json=body,
                            headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
            r.raise_for_status()
        out = ''.join(p.get('text', '') for p in r.json().get('content', []) if p.get('type') == 'text')
        m = re.search(r'\[.*\]', out, re.S)
        result = json.loads(m.group(0)) if m else None
        if isinstance(result, list) and result and isinstance(result[0], str) and result[0].strip():
            return result[0]
    except Exception as exc:
        print('WA_AGENT_TRANSLATE', type(exc).__name__, str(exc)[:120], flush=True)
    return None


def localized_reply(job):
    """Owner (21-22 Nov 2026): the customer gets the reply in HIS language — Arabic, English, Chinese, Hindi or Urdu —
    whatever language the reply was drafted in (a voice note/sticker keeps the conversation's language, Arabic by
    default). Codes, numbers and links are kept; if translation fails the original reply goes out."""
    text = job.get('reply_text') or ''
    plain = re.sub(r'(?:AFT?|NQ)-\d+|https?://\S+|\S+@\S+|Ref|Afaq Tuwaiq|آفاق طويق|رقم الطلب', ' ', text)
    have = detect(plain)
    if not have:
        return text
    lang = customer_language(job)
    if not lang or lang == have or lang not in NAMES:
        return text
    return translate(text, lang) or text
