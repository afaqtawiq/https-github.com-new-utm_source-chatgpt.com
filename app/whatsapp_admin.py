"""Owner-only WhatsApp commands. Called only after webhook signature verification.

No model-produced SQL, shell execution, publishing or implicit third-party sending.
All database writes share the receiver's event-deduplication transaction.
"""
import json
import os
import re
import secrets
from urllib.parse import quote, urlsplit

import httpx


def normalize(value):
    value = re.sub(r'[\u064b-\u065f\u0670ـ]', '', str(value or ''))
    return value.translate(str.maketrans('أإآ٠١٢٣٤٥٦٧٨٩', 'ااا0123456789')).strip()


def phone(value):
    value = str(value or '').strip()
    if not re.fullmatch(r'\+?[0-9 ()-]{9,22}', value):
        return ''
    value = re.sub(r'\D', '', value)
    if value.startswith('00'):
        value = value[2:]
    return value if re.fullmatch(r'[1-9][0-9]{8,14}', value) else ''


def is_admin_command(text):
    """Keep explicit management commands separate from a shipper's reply."""
    text = normalize(text)
    return bool(
        re.match(r'^(?:افاق(?: طويق)?|شواهد(?: الهدف)?)(?:\s|[:،-]|$)', text)
        or re.fullmatch(r'نفذ\s+[0-9A-Fa-f]{6}', text)
        or text.casefold() in {
            'الاوامر', 'اوامر', 'مساعدة', 'ادارة', 'help', 'menu',
            'مرحبا', 'السلام عليكم',
        }
    )


def owner_sender(payload):
    """Use provider identity, never text, names, or the business account phone."""
    expected = phone(os.getenv('WHATSAPP_COMMAND_OWNER', ''))
    account_id = os.getenv('WHATSAPP_COMMAND_ACCOUNT_ID', '')
    account = payload.get('account') or {}
    message = payload.get('message') or {}
    conversation = payload.get('conversation') or {}
    sender = message.get('sender') or {}
    actual = phone(sender.get('phoneNumber'))
    if not expected or not account_id or actual != expected:
        return ''
    if (account.get('accountId') or account.get('id')) != account_id:
        return ''
    if account.get('platform') != 'whatsapp' or message.get('direction') != 'incoming':
        return ''
    if conversation.get('isGroup') or message.get('isGroup'):
        return ''
    # A private conversation must identify the same participant as the sender.
    if phone(conversation.get('participantId')) != actual:
        return ''
    if sender.get('id') and phone(sender['id']) != actual:
        return ''
    return actual


def ensure_admin(c):
    c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_admin_audit(
        event_id TEXT PRIMARY KEY, sender TEXT NOT NULL, conversation_id TEXT NOT NULL,
        command TEXT NOT NULL, reply TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())''')
    c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(
        token TEXT PRIMARY KEY, sender TEXT NOT NULL, conversation_id TEXT NOT NULL,
        command TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL, consumed BOOLEAN DEFAULT FALSE)''')


HELP = '''أوامر الإدارة — آفاق طويق وشواهد الهدف
اكتب الأمر كاملًا، مثل:
آفاق اعرض السائقين
آفاق أضف السائق محمد ورقمه 0501234567
آفاق اعرض الشحنات
آفاق أضف شحنة مرجع REF-123 من الرياض إلى جدة
آفاق حالة الشحنة REF-123
آفاق اعرض العملاء
شواهد اعرض الطلبات
شواهد حالة SH-8
شواهد اعرض نص SH-8
شواهد عدل افتتاحية SH-8 إلى: Planning a cleaner desk setup?

التعديلات للمراجعة. النشر والإرسال للعملاء والحذف والصرف تتم من شاشة الاعتماد في البرنامج.
اكتب «الأوامر» لعرض هذه القائمة.'''


def run_command(c, raw, event_id):
    text = normalize(raw)
    if len(text) > 2000:
        return 'الأمر طويل؛ أرسل أمرًا واحدًا في رسالة قصيرة.'
    if text.casefold() in ('الاوامر', 'اوامر', 'مساعدة', 'ادارة', 'help', 'menu', 'مرحبا', 'السلام عليكم'):
        voice = 'جاهز' if os.getenv('OPENAI_API_KEY') else 'غير مفعّل؛ يحتاج ربط مفتاح تحويل الصوت'
        return HELP + '\nالملاحظات الصوتية: ' + voice
    if text in ('افاق', 'افاق طويق', 'شواهد', 'شواهد الهدف'):
        return HELP
    # Require the target program in every command; never infer from customer intake state.
    match = re.match(r'^(افاق(?: طويق)?|شواهد(?: الهدف)?)\s*[:،-]?\s+(.+)$', text, re.S)
    if not match:
        return 'ابدأ الأمر باسم البرنامج: آفاق أو شواهد.\n\n' + HELP
    target, command = match.groups()
    if target.startswith('افاق'):
        return afaaq_command(c, command)
    return shawahid_command(c, command, event_id, raw)


def afaaq_command(c, command):
    if command in ('اعرض السائقين', 'السائقين', 'السائقون'):
        items = c.execute('SELECT id,driver_name,whatsapp_phone,availability FROM drivers ORDER BY id DESC LIMIT 10').fetchall()
        return 'آخر 10 سائقين:\n' + ('\n'.join(f"{x['id']} · {x['driver_name']} · {x['whatsapp_phone']} · {x['availability']}" for x in items) or 'لا يوجد سائقون.')
    match = re.fullmatch(r'(?:اضف|سجل) (?:السائق|سائق) (.{1,100}?) (?:ورقمه|رقمه|ورقم|رقم|جواله) (\+?\d{10,15})(?: (?:ومركبته|مركبته) (.{1,100}))?', command)
    if match:
        name, number, vehicle = match.groups()
        if re.fullmatch(r'05\d{8}', number):
            number = '966' + number[1:]
        number = phone(number)
        if not re.fullmatch(r'9665\d{8}', number):
            return 'رقم السائق غير صالح؛ استخدم رقم جوال سعودي كاملًا.'
        number = '+' + number
        row = c.execute('''INSERT INTO drivers(driver_name,whatsapp_phone,vehicle_type,
            availability,offer_consent,notes,created_at,updated_at)
            VALUES(%s,%s,%s,'متاح',1,'أضيف بأمر واتساب من المالك؛ مسجل لاستقبال عروض الحمولات',NOW(),NOW())
            ON CONFLICT(whatsapp_phone) DO NOTHING RETURNING id''', (name, number, vehicle or 'غير محدد')).fetchone()
        if not row:
            return 'هذا الرقم مسجل لسائق بالفعل؛ لم أنشئ سجلًا مكررًا.'
        return f"تمت إضافة السائق {name} برقم {number}. رقم السجل: {row['id']}."
    if command in ('اعرض الشحنات', 'الشحنات'):
        items = c.execute('SELECT reference,origin,destination,status FROM shipments ORDER BY id DESC LIMIT 10').fetchall()
        return 'آخر 10 شحنات:\n' + ('\n'.join(f"{x['reference']} · {x['origin']} ← {x['destination']} · {x['status']}" for x in items) or 'لا توجد شحنات.')
    match = re.fullmatch(r'(?:اضف|سجل) شحنة مرجع ([A-Za-z0-9_-]{1,60}) من (.{1,100}?) (?:الى|إلى) (.{1,100})', command)
    if match:
        reference, origin, destination = match.groups()
        row = c.execute('''INSERT INTO shipments(reference,service_type,origin,destination,status,created_at,updated_at)
            VALUES(%s,'نقل',%s,%s,'new',NOW(),NOW()) ON CONFLICT(reference) DO NOTHING RETURNING id''', (reference, origin, destination)).fetchone()
        return (f'تم إنشاء الشحنة {reference}: من {origin} إلى {destination}. لم يتم اعتماد سعر أو حجز.'
                if row else f'الشحنة {reference} موجودة؛ لم أنشئ سجلًا مكررًا.')
    match = re.fullmatch(r'حالة (?:الشحنة|شحنة) ([A-Za-z0-9_-]{1,60})', command)
    if match:
        row = c.execute('SELECT reference,origin,destination,status FROM shipments WHERE reference=%s', (match[1],)).fetchone()
        return (f"{row['reference']}\nمن {row['origin']} إلى {row['destination']}\nالحالة: {row['status']}" if row else 'لم أجد هذه الشحنة.')
    if command in ('اعرض العملاء', 'العملاء'):
        items = c.execute('SELECT id,name,status FROM accounts ORDER BY id DESC LIMIT 10').fetchall()
        return 'آخر 10 عملاء:\n' + ('\n'.join(f"{x['id']} · {x['name']} · {x['status']}" for x in items) or 'لا يوجد عملاء في سجل الحسابات.')
    return 'لم أنفذ الأمر. استخدم إحدى الصيغ التالية:\n' + HELP


def shawahid_command(c, command, event_id, original=''):
    if command in ('اعرض الطلبات', 'الطلبات'):
        items = c.execute("SELECT id,status FROM zernio_requests WHERE agent='shawahid' ORDER BY updated_at DESC LIMIT 10").fetchall()
        return 'آخر 10 طلبات شواهد:\n' + ('\n'.join(f"SH-{x['id']} · {x['status']}" for x in items) or 'لا توجد طلبات.')
    match = re.fullmatch(r'(حالة|اعرض نص|عدل افتتاحية)\s+SH-(\d{1,12})(?:\s+الى\s*:\s*(.+))?', command, re.I | re.S)
    if not match:
        return 'لم أنفذ الأمر. جرّب: شواهد حالة SH-8، أو شواهد اعرض نص SH-8.\nاكتب «الأوامر» لبقية الصيغ.'
    action, request_id, opening = match.groups()
    row = c.execute("SELECT id,status,fields FROM zernio_requests WHERE id=%s AND agent='shawahid' FOR UPDATE", (int(request_id),)).fetchone()
    if not row:
        return 'لم أجد طلب شواهد بهذا الرقم.'
    if action == 'حالة':
        fields = row['fields'] or {}
        return f"SH-{row['id']}\nالحالة: {row['status']}\nالخدمة: {str(fields.get('service', 'غير محددة'))[:700]}\nالميزانية: {str(fields.get('budget', 'غير محددة'))[:300]}\nالموعد: {str(fields.get('deadline', 'غير محدد'))[:300]}"
    from app.material_bridge import ensure_materials, material_reply
    ensure_materials(c)
    if action == 'عدل افتتاحية':
        original_opening = re.split(r'\s+(?:إلى|الى)\s*:\s*', original, maxsplit=1)
        if len(original_opening) == 2:
            opening = original_opening[1].strip()
        if not opening or len(opening) > 500 or any(x in opening for x in ('\n', '"', '“', '”')):
            return 'اكتب: شواهد عدل افتتاحية SH-8 إلى: ثم الجملة الجديدة في سطر واحد.'
        # Existing mirror preserves URLs/disclosures and syncs changes back to the project.
        result = material_reply(c, int(request_id), event_id,
            'Change the opening of Promotional Caption 1 to: “' + opening + '”')
        return f'SH-{request_id}\n' + result
    state = c.execute('SELECT state FROM shawahid_materials WHERE request_id=%s', (int(request_id),)).fetchone()
    if not state:
        return 'مواد المشروع غير مرتبطة بهذا الطلب بعد.'
    state = state['state']
    for artifact in state.get('artifacts', []):
        edit = next((x for x in state.get('edits', []) if x['id'] == artifact['id']), None)
        document = edit['text'] if edit else artifact['text']
        match = re.search(r'(?im)^\s*(?:\d+[.)]\s*)?Promotional Caption 1\s*\n+', document)
        if match:
            section = document[match.end():]
            end = re.search(r'(?m)^\s*\d+[.)]\s+[^\n]+\n', section)
            section = section[:end.start()] if end else section
            if len(section) > 3400:
                return 'النص أطول من رسالة واحدة؛ افتحه في صفحة المشروع للحفاظ على النص والرابط كاملين.'
            return f'SH-{request_id} — نص للمراجعة:\n\n' + section.strip()
    return 'لم أجد Promotional Caption 1 في المواد المرتبطة.'


def audio_index(message):
    for index, attachment in enumerate(message.get('attachments') or []):
        if isinstance(attachment, dict) and (attachment.get('type') in ('audio', 'voice') or str(attachment.get('mimeType', '')).startswith('audio/')):
            return index
    return None


def safe_media_url(url):
    p = urlsplit(str(url or ''))
    host = p.hostname or ''
    # No arbitrary URLs or redirects, no authorization headers forwarded to CDNs.
    return p.scheme == 'https' and p.port in (None, 443) and not p.username and not p.password and (
        host in ('zernio.com', 'lookaside.fbsbx.com') or host.endswith('.fbcdn.net') or host.endswith('.whatsapp.net'))


async def transcribe(payload, index):
    key = os.getenv('OPENAI_API_KEY', '')
    if not key:
        raise ValueError('الملاحظات الصوتية غير مفعّلة: يلزم ربط مفتاح OpenAI بخادم واتساب. اكتب الأمر أو استخدم إملاء لوحة مفاتيح الجوال مؤقتًا.')
    message, account = payload['message'], payload['account']
    message_id = message.get('platformMessageId')
    if not message_id:
        raise ValueError('لم أجد معرف التسجيل الصوتي؛ أعد إرساله أو اكتب الأمر.')
    path = '/inbox/conversations/' + quote(payload['conversation']['id'], safe='') + '/messages/' + quote(message_id, safe='') + f'/attachments/{index}'
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        resolved = await client.get('https://zernio.com/api/v1' + path,
            params={'accountId': account.get('accountId') or account['id'], 'format': 'json'},
            headers={'Authorization': 'Bearer ' + os.environ['ZERNIO_API_KEY']})
        resolved.raise_for_status()
        url = resolved.json().get('url')
        if not safe_media_url(url):
            raise ValueError('رابط التسجيل غير مدعوم بأمان؛ أرسل الأمر كتابةً.')
        async with client.stream('GET', url) as response:
            response.raise_for_status()
            mime = response.headers.get('content-type', '').split(';')[0]
            formats = {'audio/ogg': 'ogg', 'audio/mpeg': 'mp3', 'audio/mp4': 'm4a', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/webm': 'webm'}
            if mime not in formats:
                raise ValueError('صيغة التسجيل غير مدعومة؛ أرسل ملاحظة صوتية قصيرة.')
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    raise ValueError('التسجيل كبير؛ أرسل أمرًا صوتيًا قصيرًا أقل من 4 ميجابايت.')
                chunks.append(chunk)
        result = await client.post('https://api.openai.com/v1/audio/transcriptions',
            headers={'Authorization': 'Bearer ' + key},
            data={'model': 'gpt-4o-mini-transcribe', 'response_format': 'json'},
            files={'file': ('command.' + formats[mime], b''.join(chunks), mime)})
        result.raise_for_status()
        text = str(result.json().get('text') or '').strip()
        if not text or len(text) > 2000:
            raise ValueError('لم أستخلص أمرًا قصيرًا واضحًا. اكتب الأمر أو أعد تسجيله.')
        return text


async def admin_reply(c, payload, sender):
    # Recheck at the privilege boundary, even if called independently in the future.
    if not sender or owner_sender(payload) != sender:
        raise PermissionError('Owner identity required')
    ensure_admin(c)
    event_id, conversation = payload['id'], payload['conversation']['id']
    message = payload['message']
    raw = str(message.get('text') or '').strip()
    index = audio_index(message)
    if index is not None:
        try:
            raw = await transcribe(payload, index)
            token = secrets.token_hex(3).upper()
            c.execute('''INSERT INTO whatsapp_voice_pending(token,sender,conversation_id,command,expires_at)
                VALUES(%s,%s,%s,%s,NOW()+INTERVAL '10 minutes')''', (token, sender, conversation, raw))
            reply = f'سمعت:\n{raw}\n\nللتنفيذ اكتب: نفذ {token}\nالرمز صالح 10 دقائق. لم أنفذ الأمر بعد.'
        except ValueError as error:
            reply = str(error)
        except (httpx.HTTPError, KeyError, TypeError):
            reply = 'تعذر تحويل الصوت الآن؛ لم أنفذ أي أمر. أرسله كتابةً.'
    elif raw:
        confirmation = re.fullmatch(r'نفذ\s+([0-9A-Fa-f]{6})', normalize(raw))
        if confirmation:
            row = c.execute('''UPDATE whatsapp_voice_pending SET consumed=TRUE
                WHERE token=%s AND sender=%s AND conversation_id=%s AND NOT consumed AND expires_at>NOW()
                RETURNING command''', (confirmation[1].upper(), sender, conversation)).fetchone()
            reply = run_command(c, row['command'], event_id) if row else 'رمز التأكيد غير صالح أو استُخدم أو انتهت مدته؛ لم أنفذ الأمر.'
        else:
            reply = run_command(c, raw, event_id)
    else:
        reply = 'أرسل أمرًا مكتوبًا أو تسجيلًا صوتيًا.\n' + HELP
    c.execute('''INSERT INTO whatsapp_admin_audit(event_id,sender,conversation_id,command,reply)
        VALUES(%s,%s,%s,%s,%s)''', (event_id, sender, conversation, raw[:2000], reply))
    return {'message': reply}
