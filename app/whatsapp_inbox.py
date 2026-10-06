"""Manager inbox using the existing provider connection, without CRM enrolment.

Provider text is display data, never executable instructions. No background sends,
read receipts, token creation, account reconfiguration or notification subscription.
"""
import secrets
from contextlib import contextmanager
from html import escape
from urllib.parse import quote, urlencode, parse_qs

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app import zernio_whatsapp as z

router = APIRouter()


@contextmanager
def database():
    from app.storage import db
    with db() as c:
        yield c


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_inbox_drafts(
        token TEXT PRIMARY KEY, account_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
        recipient TEXT NOT NULL, body TEXT NOT NULL, created_by BIGINT NOT NULL,
        state TEXT NOT NULL DEFAULT 'draft', provider_message_id TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')


def send_authority(request):
    current = z.session(request)
    from app.fine_permissions import has_permission
    from app.mfa_stepup import recent_stepup
    if not has_permission(current, 'send_whatsapp'):
        raise HTTPException(403, 'Permission required')
    if not recent_stepup(current['id']):
        raise HTTPException(428, 'Recent MFA step-up required')
    return current


def field(value, maximum=255):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise HTTPException(400, 'Invalid input')
    return value


def page(body, status=200):
    return HTMLResponse('''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width"><title>محادثات واتساب</title>
    <style>body{font:17px Tahoma;background:#0b2031;color:white;max-width:1000px;margin:auto;padding:24px}
    a{color:#ffd978}article,form{padding:18px;border:1px solid #496071;border-radius:12px;margin:14px 0}
    pre{white-space:pre-wrap;overflow-wrap:anywhere}textarea{width:95%;min-height:130px}button{padding:12px;margin:12px 0}
    small{color:#afc6d7}</style><nav><a href="/dashboard">الرئيسية</a> · <a href="/whatsapp-inbox">محادثات واتساب</a></nav>
    <h1>محادثات واتساب</h1><p>قراءة من حساب آفاق الحالي. لا تُرسل علامة قراءة، ولا يُضاف المستلم إلى العملاء أو الحملات.</p>'''
    + body + '</html>', status_code=status, headers={'Cache-Control': 'no-store',
    'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})


async def conversations(c, cursor=None):
    params = {'accountId': z.account_id(), 'platform': 'whatsapp', 'limit': 100}
    if cursor:
        params['cursor'] = field(cursor, 2048)
    payload = await z.read(c, '/inbox/conversations', params)
    meta = payload.get('meta') or {}
    if meta.get('accountsFailed') or meta.get('accountsSkipped'):
        raise z.WhatsAppBlocked('Incomplete provider read')
    items = payload.get('data')
    if not isinstance(items, list):
        raise z.WhatsAppBlocked('Invalid provider read')
    return [row for row in items if isinstance(row, dict)
            and row.get('accountId') == z.account_id() and row.get('platform') == 'whatsapp'
            and not row.get('isGroup') and z.phone(row.get('participantId'))
            and isinstance(row.get('id'), str)], payload.get('pagination') or {}


async def verified_conversation(c, cid):
    field(cid)
    cursor, visited = None, set()
    for _ in range(50):
        items, pagination = await conversations(c, cursor)
        matches = [row for row in items if row['id'] == cid]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise z.WhatsAppBlocked('Ambiguous conversation')
        if not pagination.get('hasMore'):
            raise HTTPException(404, 'Conversation not available for this account')
        cursor = pagination.get('nextCursor')
        if not cursor or cursor in visited:
            break
        visited.add(cursor)
    raise z.WhatsAppBlocked('Incomplete conversation lookup')


def next_link(pagination, **query):
    if not pagination.get('hasMore'):
        return ''
    cursor = pagination.get('nextCursor')
    if not isinstance(cursor, str) or not cursor:
        return '<p>لم تكتمل القراءة؛ لا يمكن تأكيد نهاية السجل.</p>'
    return '<p><a href="?' + escape(urlencode({**query, 'cursor': cursor})) + '">الصفحة التالية</a></p>'


def render_message(message):
    labels = {'accepted': 'قبله المزود؛ التسليم غير مؤكد', 'sent': 'أُرسل؛ التسليم غير مؤكد',
              'delivered': 'تم التسليم', 'read': 'تمت القراءة', 'failed': 'فشل التسليم',
              'played': 'تم تشغيله', 'deleted': 'محذوف'}
    status = labels.get(message.get('deliveryStatus'), 'حالة التسليم غير مؤكدة')
    attachments = message.get('attachments') or []
    media = ''.join('<li>' + escape(str(item.get('filename') or item.get('type') or 'مرفق'))
                    + ' · ' + escape(str(item.get('mimeType') or '')) + '</li>'
                    for item in attachments if isinstance(item, dict))
    if media:
        media = '<ul>' + media + '</ul><small>بيانات المرفق فقط؛ محتواه غير معروض أو مؤرشف هنا.</small>'
    return '<article><small>' + escape(str(message.get('createdAt') or '')) + ' · ' + (
        'وارد' if message.get('direction') == 'incoming' else 'صادر') + ' · ' + status + '</small><pre>' + escape(
        str(message.get('message') or '')) + '</pre>' + media + '</article>'


@router.get('/whatsapp-inbox', response_class=HTMLResponse)
async def inbox(request: Request):
    current = z.session(request)
    cid, cursor = request.query_params.get('conversation'), request.query_params.get('cursor')
    try:
        async with z.client() as c:
            await z.validate_account(c)
            if not cid:
                items, pagination = await conversations(c, cursor)
                body = ''.join('<article><a href="?' + escape(urlencode({'conversation': row['id']})) + '">'
                    + escape(str(row.get('participantName') or 'محادثة')) + ' · +'
                    + escape(z.phone(row['participantId'])) + '</a><pre>'
                    + escape(str(row.get('lastMessage') or '')) + '</pre></article>' for row in items)
                return page((body or '<p>لا توجد محادثات فردية في هذه الصفحة.</p>') + next_link(pagination))
            row = await verified_conversation(c, cid)
            params = {'accountId': z.account_id(), 'sortOrder': 'desc', 'limit': 100}
            if cursor:
                params['cursor'] = field(cursor, 2048)
            payload = await z.read(c, '/inbox/conversations/' + quote(cid, safe='') + '/messages', params)
            messages = payload.get('messages')
            if not isinstance(messages, list):
                raise z.WhatsAppBlocked('Invalid message read')
            # Reject a provider response claiming a different account/thread.
            if any(not isinstance(m, dict) or m.get('accountId', z.account_id()) != z.account_id()
                   or m.get('conversationId', cid) != cid for m in messages):
                raise z.WhatsAppBlocked('Message identity mismatch')
            body = '<h2>' + escape(str(row.get('participantName') or '')) + ' · +' + escape(z.phone(row['participantId'])) + '</h2>'
            body += ''.join(render_message(m) for m in messages) or '<p>لم تظهر رسائل؛ النتيجة لا تثبت عدم وجود تواصل سابق.</p>'
            body += next_link(payload.get('pagination') or {}, conversation=cid)
            body += '<form method="post" action="/whatsapp-inbox/drafts"><input type="hidden" name="csrf" value="' + escape(current['csrf']) + '"><input type="hidden" name="conversation" value="' + escape(cid) + '"><label>رد للمراجعة<textarea name="body" maxlength="4000" required></textarea></label><p>لا يُرسل الآن. إرسال الرد بعد المراجعة يحتاج صلاحية المدير والتحقق الإضافي ونافذة 24 ساعة مفتوحة. خارجها يلزم قالب معتمد عبر المسار المخصص.</p><button>حفظ مسودة الرد</button></form>'
            return page(body)
    except (z.WhatsAppBlocked, httpx.HTTPError):
        return page('<p>تعذرت قراءة المزود. لم يُرسل شيء؛ أعد القراءة لاحقًا.</p>', 503)


async def form(request, current):
    raw = await request.body()
    if len(raw) > 64000:
        raise HTTPException(413)
    try:
        values = parse_qs(raw.decode(), keep_blank_values=True)
    except UnicodeDecodeError:
        raise HTTPException(400, 'Invalid form encoding') from None
    if any(len(value) != 1 for value in values.values()):
        raise HTTPException(400)
    values = {key: value[0] for key, value in values.items()}
    if values.get('csrf') != current['csrf']:
        raise HTTPException(403)
    return values


@router.post('/whatsapp-inbox/drafts')
async def draft(request: Request):
    current = z.session(request)
    values = await form(request, current)
    body = field(values.get('body'), 4000)
    if not body.strip():
        raise HTTPException(400)
    account = z.account_id()
    async with z.client() as c:
        await z.validate_account(c)
        row = await verified_conversation(c, values.get('conversation'))
    if account != z.account_id():
        raise HTTPException(409, 'Account changed during review')
    token = secrets.token_hex(24)
    with database() as c:
        ensure(c)
        c.execute('''INSERT INTO whatsapp_inbox_drafts(token,account_id,conversation_id,recipient,body,created_by)
            VALUES(%s,%s,%s,%s,%s,%s)''', (token,account,row['id'],z.phone(row['participantId']),body,current['user_id']))
    return RedirectResponse('/whatsapp-inbox/drafts/' + token, 303)


@router.get('/whatsapp-inbox/drafts/{token}', response_class=HTMLResponse)
async def preview(token: str, request: Request):
    current = z.session(request)
    with database() as c:
        ensure(c)
        item = c.execute('SELECT * FROM whatsapp_inbox_drafts WHERE token=%s AND created_by=%s', (field(token),current['user_id'])).fetchone()
    if not item:
        raise HTTPException(404)
    body = '<h2>مراجعة الرد إلى +' + escape(item['recipient']) + '</h2><pre>' + escape(item['body']) + '</pre><p>الحالة: ' + escape(item['state']) + '</p>'
    if item['state'] == 'draft':
        body += '<p><a href="/mfa/step-up?' + escape(urlencode({'next': '/whatsapp-inbox/drafts/' + token})) + '">التحقق الإضافي قبل الإرسال</a></p>'
        body += '<form method="post" action="/whatsapp-inbox/drafts/' + escape(token) + '/send"><input type="hidden" name="csrf" value="' + escape(current['csrf']) + '"><label><input type="checkbox" name="confirm" value="yes" required>أوافق على إرسال النص المعروض إلى هذا الرقم</label><button>إرسال هذا الرد مرة واحدة</button></form>'
    else:
        body += '<p>accepted تعني قبول المزود فقط. sending أو uncertain تحتاج مراجعة سجل المزود قبل أي محاولة جديدة؛ لا يوجد تكرار تلقائي.</p>'
    return page(body)


@router.post('/whatsapp-inbox/drafts/{token}/send')
async def send_draft(token: str, request: Request):
    current = send_authority(request)
    values = await form(request, current)
    if values.get('confirm') != 'yes':
        raise HTTPException(400, 'Explicit approval required')
    with database() as c:
        ensure(c)
        item = c.execute('''UPDATE whatsapp_inbox_drafts SET state='sending',updated_at=NOW()
            WHERE token=%s AND created_by=%s AND state='draft' AND account_id=%s RETURNING *''',
            (field(token),current['user_id'],z.account_id())).fetchone()
    if not item:
        raise HTTPException(409, 'Draft unavailable or already attempted')
    state, receipt = 'uncertain', None
    try:
        def recheck_authority():
            if send_authority(request)['user_id'] != current['user_id']:
                raise z.WhatsAppBlocked('Manager changed before send')
        with z.dispatch_guard(recheck_authority):
            result = await z.send(item['recipient'], item['body'], expected_account=item['account_id'],
                                  expected_conversation=item['conversation_id'])
        state, receipt = 'accepted', result['messages'][0]['id']
    except z.WhatsAppBlocked:
        state = 'blocked'
    except Exception:
        # A timeout/crash/5xx never authorizes a second attempt.
        state = 'uncertain'
    with database() as c:
        c.execute('''UPDATE whatsapp_inbox_drafts SET state=%s,provider_message_id=%s,updated_at=NOW()
            WHERE token=%s AND state='sending' ''', (state,receipt,token))
    return RedirectResponse('/whatsapp-inbox/drafts/' + token, 303)
