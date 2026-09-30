"""Owner sends a Naqliat load screenshot on WhatsApp -> Claude reads it -> load is created.

Only the verified owner (whatsapp_admin.owner_sender) reaches this code. The load goes
through the existing naqliat_connector._save and freight_workflow.contact_owner, so every
existing safety gate (ENABLE_EXTERNAL_ACTIONS, FREIGHT_AUTO_OWNER_CONTACT, approvals,
templates) still decides whether and how the load owner and drivers are contacted.
"""
import asyncio
import base64
import json
import os
import re
import threading
from urllib.parse import quote

import httpx

from app import whatsapp_admin as admin

IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
MAX_BYTES = 5 * 1024 * 1024
PROMPT = """This is a screenshot of a freight load from the Saudi "Naqliat" app (or a similar load listing).
Read ONLY what is visible. Never guess. Use null for anything not clearly shown.
Return ONLY a JSON object, no markdown, with these keys:
origin: loading city/location (Arabic as shown, e.g. after "مطلوب من" / "من" / "التحميل")
destination: unloading city/location (e.g. after "إلى" / "التنزيل")
owner_phone: the load owner's phone number digits if visible
weight_tons: number (tons) if visible
vehicle_type: truck type if visible (e.g. "نوع الشاحنة")
price_sar: offered transport price in SAR as a number if visible
payment: payment terms if visible
loading_date: loading date/time text if visible
goods: goods description if visible
distance_km: integer if visible
notes: any other useful detail, short
confidence: number 0..1 for how sure you are about origin and destination"""


def image_index(message):
    for index, item in enumerate(message.get('attachments') or []):
        if isinstance(item, dict) and (item.get('type') == 'image' or str(item.get('mimeType', '')).startswith('image/')):
            return index
    return None


async def fetch_image(payload, index):
    message, account = payload['message'], payload['account']
    message_id = message.get('platformMessageId')
    if not message_id:
        raise ValueError('لم أجد معرف الصورة؛ أعد إرسالها.')
    path = ('/inbox/conversations/' + quote(payload['conversation']['id'], safe='') + '/messages/'
            + quote(message_id, safe='') + f'/attachments/{index}')
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        resolved = await client.get('https://zernio.com/api/v1' + path,
                                    params={'accountId': account.get('accountId') or account['id'], 'format': 'json'},
                                    headers={'Authorization': 'Bearer ' + os.environ['ZERNIO_API_KEY']})
        resolved.raise_for_status()
        url = resolved.json().get('url')
        if not admin.safe_media_url(url):
            raise ValueError('رابط الصورة غير مدعوم بأمان؛ أعد إرسالها.')
        async with client.stream('GET', url) as response:
            response.raise_for_status()
            mime = response.headers.get('content-type', '').split(';')[0].strip().lower()
            if mime not in IMAGE_TYPES:
                raise ValueError('صيغة الصورة غير مدعومة؛ أرسل لقطة شاشة JPG أو PNG.')
            data = b''
            async for chunk in response.aiter_bytes():
                data += chunk
                if len(data) > MAX_BYTES:
                    raise ValueError('الصورة كبيرة؛ أرسل لقطة شاشة أصغر من 5 ميجابايت.')
    return data, mime


async def extract(data, mime):
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key:
        raise ValueError('قراءة الصور غير مفعّلة: يلزم ضبط ANTHROPIC_API_KEY على الخادم. أرسل تفاصيل الحمولة كتابةً مؤقتًا.')
    body = {'model': os.getenv('LOAD_VISION_MODEL', 'claude-sonnet-5'), 'max_tokens': 800,
            'messages': [{'role': 'user', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': base64.b64encode(data).decode()}},
                {'type': 'text', 'text': PROMPT}]}]}
    async with httpx.AsyncClient(timeout=60) as client:
        result = await client.post('https://api.anthropic.com/v1/messages', json=body,
                                   headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
        result.raise_for_status()
    text = ''.join(part.get('text', '') for part in result.json().get('content', []) if part.get('type') == 'text')
    match = re.search(r'\{.*\}', text, re.S)
    if not match:
        raise ValueError('لم أستخرج بيانات واضحة من الصورة؛ أرسل لقطة أوضح لشاشة تفاصيل الحمولة.')
    return json.loads(match.group(0))


def _text(value, limit=120):
    value = str(value or '').strip()
    return '' if value.lower() in ('null', 'none') else value[:limit]


def _number(value):
    try:
        return float(str(value).replace(',', '').strip()) if value not in (None, '') else None
    except ValueError:
        return None


def save_load(fields):
    from app.naqliat_connector import NaqliatLoad, _save
    origin, destination = _text(fields.get('origin')), _text(fields.get('destination'))
    if len(origin) < 2 or len(destination) < 2:
        return None
    weight = _number(fields.get('weight_tons'))
    distance = _number(fields.get('distance_km'))
    price = _number(fields.get('price_sar'))
    details = [('البضاعة', fields.get('goods')), ('السعر المعروض', f'{price:,.0f} ريال' if price else ''),
               ('الدفع', fields.get('payment')), ('موعد التحميل', fields.get('loading_date')), ('ملاحظات', fields.get('notes'))]
    description = '\n'.join(f'{k}: {_text(v, 300)}' for k, v in details if _text(v, 300))
    load = NaqliatLoad(origin=origin, destination=destination,
                       distance_km=int(distance) if distance is not None and 0 <= distance <= 20000 else None,
                       weight_tons=weight if weight is not None and 0 <= weight <= 1000 else None,
                       vehicle_type=_text(fields.get('vehicle_type'), 200), description=description[:3000],
                       owner_phone=_text(fields.get('owner_phone'), 40),
                       raw_text=json.dumps(fields, ensure_ascii=False)[:10000], capture_method='whatsapp_image_ai')
    return _save(load)


def _start_workflow(shipment_id):
    from app.freight_workflow import contact_owner

    def run():
        try:
            asyncio.run(contact_owner(shipment_id, approved=True))
        except Exception:
            pass  # the workflow records its own status; the owner can retry from /freight-workflow
    threading.Thread(target=run, daemon=True).start()


def summary(fields, saved):
    load_id, created, shipment_id = saved
    rows = [('من', fields.get('origin')), ('إلى', fields.get('destination')),
            ('الوزن', f"{fields.get('weight_tons')} طن" if _number(fields.get('weight_tons')) else ''),
            ('الشاحنة', fields.get('vehicle_type')), ('البضاعة', fields.get('goods')),
            ('السعر المعروض', f"{_number(fields.get('price_sar')):,.0f} ريال" if _number(fields.get('price_sar')) else ''),
            ('رقم صاحب الحمولة', fields.get('owner_phone'))]
    lines = [f'{k}: {_text(v)}' for k, v in rows if _text(v)]
    head = f'✅ استخرجت الحمولة NQ-{load_id}' if created else f'ℹ️ هذه الحمولة مسجلة سابقًا: NQ-{load_id}'
    missing = [k for k, key in (('رقم صاحب الحمولة', 'owner_phone'), ('الوزن', 'weight_tons')) if not _text(fields.get(key))]
    tail = ('\n\nناقص: ' + '، '.join(missing) + '. أكمله من صفحة الشحنة.' if missing else
            '\n\nبدأت دورة النقل: التواصل مع صاحب الحمولة ثم عرضها على السائقين.')
    try:
        if float(fields.get('confidence') or 1) < 0.6:
            tail += '\nتنبيه: قراءة المسار غير مؤكدة، راجعها قبل الإرسال.'
    except (TypeError, ValueError):
        pass
    return head + '\n' + '\n'.join(lines) + tail + f'\n/freight-workflow/{shipment_id}'


async def handle_image(c, payload, sender, index):
    try:
        data, mime = await fetch_image(payload, index)
        fields = await extract(data, mime)
        saved = save_load(fields)
        if not saved:
            reply = 'لم أتمكن من قراءة مدينة التحميل والتنزيل من الصورة. أرسل لقطة أوضح لشاشة تفاصيل الحمولة.'
        else:
            reply = summary(fields, saved)
            if saved[1] and _text(fields.get('owner_phone')):
                _start_workflow(saved[2])
    except ValueError as error:
        reply = str(error)
    except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError):
        reply = 'تعذر قراءة الصورة الآن؛ لم تُسجل أي حمولة. أعد الإرسال بعد قليل أو اكتب التفاصيل.'
    c.execute('''INSERT INTO whatsapp_admin_audit(event_id,sender,conversation_id,command,reply)
        VALUES(%s,%s,%s,%s,%s)''', (payload['id'], sender, payload['conversation']['id'], '[صورة حمولة]', reply))
    return {'message': reply}


_original_admin_reply = admin.admin_reply


async def admin_reply(c, payload, sender):
    if not sender or admin.owner_sender(payload) != sender:
        raise PermissionError('Owner identity required')
    message = payload.get('message') or {}
    index = image_index(message)
    if index is not None and admin.audio_index(message) is None:
        admin.ensure_admin(c)
        return await handle_image(c, payload, sender, index)
    return await _original_admin_reply(c, payload, sender)


admin.admin_reply = admin_reply
