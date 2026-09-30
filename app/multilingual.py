"""WhatsApp in the customer's language: Arabic, English or Chinese.

The Afaq intake logic is written in Arabic. This layer wraps zernio_receiver.intake_reply:
* detects the customer's language from each message and remembers it per conversation;
* for English or Chinese messages, gives the existing Arabic logic an Arabic translation of
  the message (numbers, codes, dates and names kept exactly), so fields are captured correctly;
* translates the Arabic reply (and any button titles) back into the customer's language,
  keeping request codes such as AF-12, phone numbers, links and figures unchanged.
Arabic conversations are untouched. If Claude is unavailable, the reply goes out in Arabic
exactly as before, so a translation problem can never block a customer reply.
"""
import json
import os
import re

import httpx

from app import zernio_receiver as receiver
from app.storage import db

MODEL = os.getenv('TRANSLATE_MODEL', 'claude-sonnet-5')
NAMES = {'ar': 'Arabic', 'en': 'English', 'zh': 'Simplified Chinese'}


def detect(text):
    text = str(text or '')
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    arabic = len(re.findall(r'[\u0600-\u06ff]', text))
    latin = len(re.findall(r'[A-Za-z]', text))
    if cjk >= 2 and cjk >= arabic:
        return 'zh'
    if arabic >= 2 and arabic >= latin / 2:
        return 'ar'
    if latin >= 3:
        return 'en'
    return None


def _init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS conversation_languages(
            conversation_id TEXT PRIMARY KEY, lang TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')


def remember(c, conversation_id, text):
    lang = detect(text)
    if lang:
        c.execute('''INSERT INTO conversation_languages(conversation_id,lang) VALUES(%s,%s)
            ON CONFLICT(conversation_id) DO UPDATE SET lang=EXCLUDED.lang,updated_at=NOW()''', (conversation_id, lang))
        return lang
    row = c.execute('SELECT lang FROM conversation_languages WHERE conversation_id=%s', (conversation_id,)).fetchone()
    return row['lang'] if row else 'ar'


def translate(items, target):
    """Translate a list of strings to target language. Returns None on any failure."""
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key or not items:
        return None
    system = ('You translate WhatsApp messages for Afaq Tuwaiq, a Saudi customs clearance and logistics company. '
              f'Translate every string into natural, polite business {NAMES[target]}. Keep exactly as written: request codes '
              '(e.g. AF-12, NQ-5, WA-...), phone numbers, emails, URLs, numbers, amounts, dates, company and place names '
              '(you may add the local name in brackets). Keep line breaks and bullet symbols. Do not add or remove information. '
              'Return ONLY a JSON array of strings, same length and order as the input.')
    body = {'model': MODEL, 'max_tokens': 1500, 'system': system,
            'messages': [{'role': 'user', 'content': json.dumps(items, ensure_ascii=False)}]}
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post('https://api.anthropic.com/v1/messages', json=body,
                                   headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
            response.raise_for_status()
        out = ''.join(p.get('text', '') for p in response.json().get('content', []) if p.get('type') == 'text')
        match = re.search(r'\[.*\]', out, re.S)
        result = json.loads(match.group(0)) if match else None
        if isinstance(result, list) and len(result) == len(items) and all(isinstance(x, str) for x in result):
            return result
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return None


def localize(reply, lang):
    if lang == 'ar' or not isinstance(reply, dict) or not reply.get('message'):
        return reply
    buttons = [b for b in reply.get('buttons') or [] if isinstance(b, dict) and b.get('title')]
    texts = translate([reply['message']] + [b['title'] for b in buttons], lang)
    if not texts:
        return reply
    out = dict(reply)
    out['message'] = texts[0]
    if buttons:
        titles = iter(texts[1:])
        out['buttons'] = [dict(b, title=next(titles)[:20]) if isinstance(b, dict) and b.get('title') else b
                          for b in reply['buttons']]
    return out


_original_intake_reply = receiver.intake_reply


def intake_reply(c, agent, conversation_id, event_id, text, selection, message):
    lang = remember(c, conversation_id, text)
    working = text
    if agent == 'afaaq' and detect(text) in ('en', 'zh'):
        arabic = translate([text], 'ar')
        if arabic:
            working = arabic[0]
    reply = _original_intake_reply(c, agent, conversation_id, event_id, working, selection, message)
    return localize(reply, lang) if agent == 'afaaq' else reply


receiver.intake_reply = intake_reply
_init()
