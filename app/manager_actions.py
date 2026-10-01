"""Manager and team actions over WhatsApp.

1) Media download fix. The old path resolves attachments through
   /inbox/conversations/{id}/messages/{id}/attachments/{n}, which Zernio now answers with
   404 "attachment_not_found" for coexistence numbers. Every attachment also carries its own
   Zernio media URL (/api/v1/whatsapp/media/{media_id}?accountId=...), which works. Voice notes
   (whatsapp_admin.transcribe) and load screenshots (load_vision.fetch_image) now use it first
   and keep the old path as a fallback.

2) "أرسل رسالة إلى ..." from the manager or a team member: the message is sent at once from the
   Afaq WhatsApp number to a team member (by name or department) or to any phone number.
   Inside the 24-hour window it goes as normal text; outside it, the approved template
   afaaq_marketing_team_message_v1_ar carries the same text. Every send is written to the audit.
"""
import asyncio
import json
import os
import re
import threading

import httpx

from app import command_ai
from app import load_vision
from app import whatsapp_admin as admin
from app import zernio_whatsapp as wa

ZERNIO = 'https://zernio.com'
AUDIO = {'audio/ogg': 'ogg', 'audio/mpeg': 'mp3', 'audio/mp4': 'm4a', 'audio/wav': 'wav', 'audio/x-wav': 'wav',
         'audio/webm': 'webm', 'audio/aac': 'm4a', 'audio/amr': 'amr'}
IMAGES = {'image/jpeg', 'image/png', 'image/webp'}


async def media_bytes(payload, index, allowed, max_bytes):
    attachments = (payload.get('message') or {}).get('attachments') or []
    item = attachments[index] if 0 <= index < len(attachments) and isinstance(attachments[index], dict) else {}
    url = str(item.get('url') or '')
    if url.startswith('/api/v1/'):
        url = ZERNIO + url
    if not url.startswith(ZERNIO + '/api/v1/whatsapp/media/'):
        return None
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        async with client.stream('GET', url, headers={'Authorization': 'Bearer ' + os.environ['ZERNIO_API_KEY']}) as response:
            if response.status_code >= 400:
                return None
            mime = response.headers.get('content-type', '').split(';')[0].strip().lower()
            if mime not in allowed:
                return None
            data = b''
            async for chunk in response.aiter_bytes():
                data += chunk
                if len(data) > max_bytes:
                    raise ValueError('الملف كبير؛ أرسل ملفًا أصغر.')
    return data, mime


_old_transcribe = admin.transcribe


async def transcribe(payload, index):
    key = os.getenv('OPENAI_API_KEY', '')
    if not key:
        return await _old_transcribe(payload, index)
    got = await media_bytes(payload, index, AUDIO, 4 * 1024 * 1024)
    if not got:
        return await _old_transcribe(payload, index)
    data, mime = got
    async with httpx.AsyncClient(timeout=60) as client:
        result = await client.post('https://api.openai.com/v1/audio/transcriptions',
                                   headers={'Authorization': 'Bearer ' + key},
                                   data={'model': 'gpt-4o-mini-transcribe', 'response_format': 'json'},
                                   files={'file': ('command.' + AUDIO[mime], data, mime)})
        result.raise_for_status()
    text = str(result.json().get('text') or '').strip()
    if not text or len(text) > 2000:
        raise ValueError('لم أستخلص أمرًا قصيرًا واضحًا. اكتب الأمر أو أعد تسجيله.')
    return text


_old_fetch_image = load_vision.fetch_image


async def fetch_image(payload, index):
    got = await media_bytes(payload, index, IMAGES, 5 * 1024 * 1024)
    return got if got else await _old_fetch_image(payload, index)


admin.transcribe = transcribe
load_vision.fetch_image = fetch_image


# ------------------------------------------------------------------ send a WhatsApp message on command

CHECK, LQ, RQ, DASH = chr(0x2705), chr(0xAB), chr(0xBB), chr(0x2014)
TEMPLATE_INTRO = 'رسالة من إدارة آفاق طويق:'
TEMPLATE_OUTRO = 'للرد اكتب هنا مباشرة.'


def team_members():
    try:
        members = json.loads(os.getenv('AFAQ_TEAM', '[]'))
    except ValueError:
        return []
    return [m for m in members if isinstance(m, dict) and m.get('phone')]


def resolve(target):
    """Team member by name, short name or department; otherwise a phone number."""
    target = str(target or '').strip()
    digits = re.sub(r'[^0-9]', '', target)
    if len(digits) >= 9:
        if digits.startswith('00'):
            digits = digits[2:]
        if digits.startswith('0') and len(digits) == 10:
            digits = '966' + digits[1:]
        elif len(digits) == 9 and digits.startswith('5'):
            digits = '966' + digits
        return admin.phone('+' + digits), target
    wanted = admin.normalize(target)
    for m in team_members():
        names = [admin.normalize(str(m.get(k) or '')) for k in ('name', 'short', 'role')]
        if any(n and (n in wanted or wanted in n) for n in names):
            return admin.phone(m['phone']), str(m.get('name') or m.get('short'))
    return '', target


def deliver(number, text):
    """Run the async provider call from this synchronous command handler."""
    message = TEMPLATE_INTRO + '\n' + text.strip() + '\n' + TEMPLATE_OUTRO
    box = {}

    def run():
        try:
            box['result'] = asyncio.run(wa.send(number, message, template_prefix='afaaq_marketing_'))
        except Exception as error:
            box['error'] = error
    worker = threading.Thread(target=run)
    worker.start()
    worker.join(60)
    if 'error' in box:
        raise box['error']
    if 'result' not in box:
        raise RuntimeError('انتهت مهلة الإرسال؛ تحقق قبل إعادة المحاولة.')
    return box['result']


def send_message(c, parsed):
    number, label = resolve(parsed.get('to'))
    text = re.sub(r'\s+', ' ', str(parsed.get('text') or '')).strip()[:900]
    if not number:
        return 'لم أتعرف على المستلم ' + LQ + label + RQ + '. اكتب رقمه أو اسمه كما هو في فريق آفاق.'
    if not text:
        return 'ما نص الرسالة المطلوب إرسالها؟'
    try:
        from app.team import ROLE
        sender = ROLE.get() or {}
        signed = text + (' ' + DASH + ' ' + sender['name'] if sender.get('name') else '')
    except ImportError:
        signed = text
    try:
        deliver(number, signed)
    except wa.WhatsAppBlocked as error:
        return 'لم تُرسل الرسالة إلى ' + label + ': ' + str(error)
    except Exception:
        return 'تعذر التأكد من إرسال الرسالة إلى ' + label + '؛ راجع المحادثة قبل إعادة المحاولة.'
    return CHECK + ' أُرسلت الرسالة إلى ' + label + ' (+' + number.lstrip('+') + '):\n' + LQ + signed + RQ


command_ai.WA_ACTIONS = command_ai.WA_ACTIONS.replace(
    '- unsupported {"reason": str}                 # anything that would send messages to customers, delete, pay, publish, or is not listed',
    '- send_message {"to": str, "text": str}       # send a WhatsApp message now; "to" = team member name/department or a phone number;'
    ' "text" = the message to deliver, written as addressed to the recipient\n'
    '- unsupported {"reason": str}                 # delete, pay, publish, or anything not listed')

_old_run_ai_command = command_ai.run_ai_command
_original_ask = command_ai.ask_claude
_answers = {}


def ask_claude(actions, text):
    """Reuse the interpretation already made for this message, so Claude is asked only once."""
    key = (actions, text)
    if key in _answers:
        return _answers.pop(key)
    return _original_ask(actions, text)


def run_ai_command(c, raw):
    parsed = _original_ask(command_ai.WA_ACTIONS, raw)
    if parsed and parsed.get('action') == 'send_message':
        return send_message(c, parsed)
    _answers[(command_ai.WA_ACTIONS, raw)] = parsed
    try:
        return _old_run_ai_command(c, raw)
    finally:
        _answers.pop((command_ai.WA_ACTIONS, raw), None)


command_ai.ask_claude = ask_claude


command_ai.run_ai_command = run_ai_command
