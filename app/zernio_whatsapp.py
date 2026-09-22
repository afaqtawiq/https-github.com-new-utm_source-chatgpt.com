"""Transport WhatsApp adapter. Provider acceptance is not delivery confirmation."""
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from html import escape
from urllib.parse import quote, parse_qs

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

BASE = 'https://zernio.com/api/v1'
router = APIRouter()


class WhatsAppBlocked(RuntimeError):
    """A preflight or explicit rejection proves no message was accepted."""


def account_id():
    return os.getenv('ZERNIO_WHATSAPP_ACCOUNT_ID', '') or os.getenv('WHATSAPP_COMMAND_ACCOUNT_ID', '')


def configured():
    return bool(os.getenv('ZERNIO_API_KEY') and account_id() and os.getenv('ZERNIO_WEBHOOK_SECRET'))


def phone(value):
    value = re.sub(r'[ ()+-]', '', str(value or ''))
    return value if re.fullmatch(r'[1-9][0-9]{8,14}', value) else ''


async def read(client, path, params=None):
    try:
        response = await client.get(BASE + path, params=params)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise WhatsAppBlocked('تعذر التحقق من إعداد واتساب لدى Zernio؛ لم تُرسل الرسالة') from None


def client():
    if not configured():
        raise WhatsAppBlocked('إعداد حساب واتساب في Zernio غير مكتمل؛ لم تُرسل الرسالة')
    return httpx.AsyncClient(timeout=20, headers={'Authorization': 'Bearer ' + os.environ['ZERNIO_API_KEY']})


async def validate_account(c):
    accounts = (await read(c, '/accounts')).get('accounts', [])
    if not any(a.get('_id') == account_id() and a.get('platform') == 'whatsapp'
               and a.get('isActive') is True for a in accounts):
        raise WhatsAppBlocked('حساب الإرسال المحدد ليس حساب واتساب نشطًا؛ لم تُرسل الرسالة')


async def templates(c):
    return (await read(c, '/whatsapp/templates', {'accountId': account_id()})).get('templates', [])


def required_templates():
    from app.freight_workflow import _owner_message
    return [
        {'name': 'afaaq_transport_owner_inquiry_v2_ar', 'language': 'ar', 'category': 'MARKETING',
         'components': [{'type': 'BODY', 'text': _owner_message({'origin': '{{1}}', 'destination': '{{2}}'}),
                         'example': {'body_text': [['رابغ', 'دبي']]}}]},
        {'name': 'afaaq_transport_driver_offer_v1_ar', 'language': 'ar', 'category': 'MARKETING',
         'components': [{'type': 'BODY', 'text': 'عرض حمولة من آفاق طويق — {{1}}\nالمسار: {{2}} → {{3}}\nالوزن: {{4}} طن\nسعر السائق: {{5}} ريال\nالتنزيل: {{6}}\nالدفع: {{7}}\nللرغبة اكتب: موافق {{1}}',
                         'example': {'body_text': [['NQ-19', 'رابغ', 'دبي', '20', '1,850.00', 'دبي', 'عند التسليم']]}}]},
    ]


def template_parameters(template, message):
    """Match the entire reviewed message; never substitute a different offer."""
    parts = template.get('components') or []
    if not parts or any(p.get('type', '').upper() not in ('BODY', 'FOOTER') for p in parts):
        return None
    text = '\n'.join(p.get('text', '') for p in parts)
    text = ' '.join(text.split())
    seen, pattern, offset = [], '', 0
    for m in re.finditer(r'\{\{([1-9][0-9]*)\}\}', text):
        index = m.group(1)
        pattern += re.escape(text[offset:m.start()])
        if index in seen:
            pattern += '(?P=p' + index + ')'
        else:
            if int(index) != len(seen) + 1:
                return None
            seen.append(index)
            pattern += '(?P<p' + index + '>.+?)'
        offset = m.end()
    pattern += re.escape(text[offset:])
    match = re.fullmatch(pattern, ' '.join(message.split()))
    return [match.group('p' + i) for i in seen] if match else None


async def open_conversation(c, target):
    cursor, visited = None, set()
    for _ in range(50):
        params = {'accountId': account_id(), 'platform': 'whatsapp', 'limit': 100}
        if cursor: params['cursor'] = cursor
        payload = await read(c, '/inbox/conversations', params)
        if (payload.get('meta') or {}).get('accountsFailed'):
            raise WhatsAppBlocked('تعذر التحقق من محادثات حساب واتساب؛ لم تُرسل الرسالة')
        for row in payload.get('data', []):
            if (row.get('accountId') == account_id() and row.get('platform') == 'whatsapp'
                    and not row.get('isGroup') and phone(row.get('participantId')) == target):
                cid = row.get('id')
                messages = await read(c, '/inbox/conversations/' + quote(str(cid), safe='') + '/messages',
                                      {'accountId': account_id(), 'sortOrder': 'desc', 'limit': 100})
                now = datetime.now(timezone.utc)
                for msg in messages.get('messages', []):
                    if msg.get('direction') != 'incoming' or phone(msg.get('senderId')) != target:
                        continue
                    try:
                        at = datetime.fromisoformat(msg['createdAt'].replace('Z', '+00:00'))
                        if timedelta(0) <= now - at < timedelta(hours=23, minutes=55):
                            return cid
                    except (KeyError, ValueError, TypeError):
                        continue
                return None
        pagination = payload.get('pagination') or {}
        if not pagination.get('hasMore'): return None
        cursor = pagination.get('nextCursor')
        if not cursor or cursor in visited: break
        visited.add(cursor)
    raise WhatsAppBlocked('تعذر إكمال التحقق من المحادثة؛ لم تُرسل الرسالة')


async def send(recipient, message):
    target = phone(recipient)
    if not target or not message.strip():
        raise WhatsAppBlocked('رقم المستلم أو نص الرسالة غير صالح')
    async with client() as c:
        await validate_account(c)
        cid = await open_conversation(c, target)
        body = {'accountId': account_id()}
        if cid:
            path = '/inbox/conversations/' + quote(cid, safe='') + '/messages'
            body['message'] = message
        else:
            options = await templates(c)
            selected = None
            for template in options:
                if not template.get('name', '').startswith('afaaq_transport_') or template.get('language') != 'ar':
                    continue
                params = template_parameters(template, message)
                if params is not None and template.get('status') == 'APPROVED':
                    selected = (template, params)
                    break
            if selected is None:
                raise WhatsAppBlocked('لا توجد نافذة محادثة مفتوحة ولا قالب معتمد مطابق للرسالة؛ راجع اعتماد Meta في صفحة قناة واتساب. لم تُرسل الرسالة')
            template, params = selected
            path = '/inbox/conversations'
            body.update(participantId=target, templateName=template['name'], templateLanguage='ar', templateParams=params)
        # No automatic retry after the sending boundary, even with idempotency.
        response = await c.post(BASE + path, json=body, headers={'Idempotency-Key': 'afaaq-' + uuid.uuid4().hex})
        if 400 <= response.status_code < 500 and response.status_code not in (408, 409):
            raise WhatsAppBlocked('رفض مزود واتساب الإرسال (HTTP ' + str(response.status_code) + ')؛ راجع القالب وصلاحية الحساب')
        response.raise_for_status()
        data = response.json()
        mid = (data.get('data') or {}).get('messageId')
        if data.get('success') is not True or not mid or (data.get('data') or {}).get('partialFailure'):
            raise RuntimeError('نتيجة إرسال واتساب غير مؤكدة؛ راجع المزود قبل إعادة المحاولة')
        return {'provider': 'zernio', 'messages': [{'id': mid}], 'conversation_id': data['data'].get('conversationId')}


def session(request):
    from app.storage import get_session
    value = get_session(request.cookies.get('gla_session'))
    if not value: raise HTTPException(401)
    if value.get('role') != 'admin': raise HTTPException(403)
    return value


@router.get('/settings/whatsapp/channel', response_class=HTMLResponse)
async def channel_page(request: Request):
    s = session(request)
    error, listing = '', []
    try:
        async with client() as c:
            await validate_account(c)
            listing = await templates(c)
    except (WhatsAppBlocked, httpx.HTTPError):
        error = 'تعذر التحقق من المزود؛ تأكد من ربط حساب واتساب والمفتاح.'
    lines = ''.join('<tr><td>' + escape(str(t.get('name'))) + '</td><td>' + escape(str(t.get('status'))) + '</td></tr>'
                    for t in listing if t.get('name', '').startswith('afaaq_transport_'))
    from app.freight_workflow import _page
    return HTMLResponse(_page('قناة واتساب', f'''<div class=card><h1>قناة واتساب للنقل</h1>
    <p>المزود: {escape(os.getenv('WHATSAPP_PROVIDER', 'meta'))} · قناة أصحاب الحمولات: {escape(os.getenv('FREIGHT_OWNER_CONTACT_CHANNEL', 'retell'))}</p>
    <p>{escape(error or 'تم التحقق من حساب Zernio وقراءة حالة القوالب.')}</p>
    <p>الإرسال الحر متاح عند وجود رسالة حديثة من المستلم. بدء التواصل يحتاج قالبًا مطابقًا ومعتمدًا. قبول الإرسال لا يعني التسليم.</p>
    <table><tr><th>القالب</th><th>حالة Meta</th></tr>{lines}</table>
    <form method=post action=/settings/whatsapp/channel/templates><input type=hidden name=csrf value="{escape(s['csrf'])}"><button>تجهيز قوالب أصحاب الحمولات والسائقين الناقصة</button></form>
    <p>هذا الإجراء يرفع القوالب للمراجعة فقط، ولا يرسل رسائل للعملاء أو السائقين.</p>
    <p><a href=/freight-workflow>الشحنات</a> · <a href=/readiness>جاهزية التشغيل</a></p></div>'''))


@router.post('/settings/whatsapp/channel/templates')
async def provision_templates(request: Request):
    s = session(request)
    form = parse_qs((await request.body()).decode())
    if form.get('csrf', [''])[0] != s['csrf']: raise HTTPException(403)
    async with client() as c:
        await validate_account(c)
        listing = await templates(c)
        for template in required_templates():
            if any(t.get('name') == template['name'] and t.get('language') == 'ar' for t in listing):
                continue
            response = await c.post(BASE + '/whatsapp/templates', json={'accountId': account_id(), **template})
            if not response.is_success:
                raise HTTPException(502, 'لم يتم تأكيد إنشاء القالب؛ راجع صفحة القناة قبل إعادة المحاولة')
    return RedirectResponse('/settings/whatsapp/channel', status_code=303)
