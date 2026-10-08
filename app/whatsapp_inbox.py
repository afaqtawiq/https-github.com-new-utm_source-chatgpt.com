"""Manager inbox using the existing provider connection, without CRM enrolment.

Provider text is display data, never executable instructions. No background sends,
read receipts, token creation, account reconfiguration or notification subscription.
"""
import secrets
import asyncio
import re
import threading
from contextlib import contextmanager
from html import escape
from urllib.parse import quote, urlencode, parse_qs, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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


def render_message(message, conversation_id=None, csrf=None):
    labels = {'accepted': 'قبله المزود؛ التسليم غير مؤكد', 'sent': 'أُرسل؛ التسليم غير مؤكد',
              'delivered': 'تم التسليم', 'read': 'تمت القراءة', 'failed': 'فشل التسليم',
              'played': 'تم تشغيله', 'deleted': 'محذوف'}
    status = labels.get(message.get('deliveryStatus'), 'حالة التسليم غير مؤكدة')
    attachments = message.get('attachments') or []
    rows = []
    for index, item in enumerate(attachments):
        if not isinstance(item, dict):
            continue
        label = escape(str(item.get('filename') or item.get('type') or 'مرفق'))
        label += ' · ' + escape(str(item.get('mimeType') or ''))
        metadata = pdf_attachment_metadata(item)
        if (conversation_id and isinstance(message.get('id'), str)
                and _pdf_metadata_allowed(metadata)):
            query = urlencode({'conversation': conversation_id, 'message': message['id'], 'index': index})
            action = 'تنزيل PDF للمراجعة' if metadata['mime_status'] == 'declared_pdf' else 'فحص الملف وتنزيله إن كان PDF'
            label += ' · <a href="/whatsapp-inbox/attachment?' + escape(query) + '">' + action + '</a>'
            if csrf:
                label += '<form method="post" action="/whatsapp-inbox/attachment/text?' + escape(query) + '"><input type="hidden" name="csrf" value="' + escape(csrf) + '"><button>قراءة نص الملف محليًا</button></form>'
        rows.append('<li>' + label + '</li>')
    media = '<ul>' + ''.join(rows) + '</ul><small>تنزيل للمراجعة فقط؛ لا أرشفة أو اعتماد تلقائي للمحتوى.</small>' if rows else ''
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
            body += ''.join(render_message(m, cid, current['csrf']) for m in messages) or '<p>لم تظهر رسائل؛ النتيجة لا تثبت عدم وجود تواصل سابق.</p>'
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


MAX_PDF_BYTES = 20 * 1024 * 1024
_PDF_REVIEW_SLOT = threading.BoundedSemaphore(1)


class PDFValidationError(HTTPException):
    """Allowlisted diagnostics only; never include provider or document content."""
    _DETAILS = {
        ('metadata', 'count'): 'One PDF per message is required',
        ('metadata', 'mime'): 'Only verified PDF attachments are supported',
        ('response', 'encoding'): 'Compressed media is not supported',
        ('response', 'mime'): 'The media response is not a PDF',
        ('response', 'signature'): 'Invalid PDF signature',
        ('parser', 'invalid_pdf'): 'The media could not be validated as a PDF',
        ('parser', 'busy'): 'Another PDF is being reviewed; try again later',
        ('parser', 'timeout'): 'PDF validation exceeded the time limit',
        ('parser', 'unavailable'): 'Local PDF validation is unavailable',
    }

    def __init__(self, stage, reason):
        detail = self._DETAILS[(stage, reason)]
        self.stage = self.diagnostic_stage = stage
        self.reason = self.diagnostic_reason = reason
        super().__init__(415, detail)


def pdf_attachment_metadata(item):
    """Classify documented top-level fields without retaining raw provider data."""
    if not isinstance(item, dict):
        return {'mime': 'other', 'kind': 'unknown', 'mime_status': 'invalid'}
    kinds = ('file', 'image', 'video', 'audio', 'sticker', 'share', 'template', 'unsupported_type')
    raw_kind = item.get('type')
    kind = ('absent' if 'type' not in item else
            raw_kind if isinstance(raw_kind, str) and raw_kind in kinds else 'unknown')
    raw_mime = item.get('mimeType')
    if raw_mime is None or (isinstance(raw_mime, str) and not raw_mime.strip()):
        mime, status = 'unknown', 'absent'
    elif not isinstance(raw_mime, str):
        mime, status = 'other', 'invalid'
    elif raw_mime.split(';',1)[0].strip().lower() == 'application/pdf':
        mime, status = 'application/pdf', 'declared_pdf'
    else:
        mime, status = 'other', 'unsupported'
    return {'mime': mime, 'kind': kind, 'mime_status': status}


def _pdf_metadata_allowed(metadata):
    return ((metadata['mime_status'] == 'declared_pdf' and metadata['kind'] in ('file', 'absent'))
            or (metadata['mime_status'] == 'absent' and metadata['kind'] == 'file'))


async def verified_attachment(c, cid, message_id, index):
    """Resolve only attachments belonging to a verified private conversation."""
    await verified_conversation(c, cid)
    cursor, visited = None, set()
    for _ in range(50):
        params = {'accountId': z.account_id(), 'sortOrder': 'desc', 'limit': 100}
        if cursor:
            params['cursor'] = field(cursor, 2048)
        payload = await z.read(c, '/inbox/conversations/' + quote(cid, safe='') + '/messages', params)
        messages = payload.get('messages')
        if not isinstance(messages, list):
            raise z.WhatsAppBlocked('Incomplete message read')
        found = []
        for message in messages:
            if (not isinstance(message, dict) or message.get('accountId', z.account_id()) != z.account_id()
                    or message.get('conversationId', cid) != cid
                    or message.get('platform', 'whatsapp') != 'whatsapp'):
                raise z.WhatsAppBlocked('Message identity mismatch')
            if message.get('id') == message_id:
                found.append(message)
        if len(found) > 1:
            raise z.WhatsAppBlocked('Ambiguous message identity')
        if found:
            attachments = found[0].get('attachments') or []
            if found[0].get('isDeleted') or found[0].get('deliveryStatus') == 'deleted' or not isinstance(attachments, list) or index >= len(attachments):
                raise HTTPException(404, 'Attachment unavailable')
            item = attachments[index]
            if not _pdf_metadata_allowed(pdf_attachment_metadata(item)):
                raise PDFValidationError('metadata', 'mime')
            return item
        pagination = payload.get('pagination') or {}
        if not pagination.get('hasMore'):
            raise HTTPException(404, 'Message not found')
        cursor = pagination.get('nextCursor')
        if not cursor or cursor in visited:
            break
        visited.add(cursor)
    raise z.WhatsAppBlocked('Incomplete message lookup')


def media_identifier(value):
    if type(value) is int and value >= 0:
        value = str(value)
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,255}', value) else None


def canonical_media_identifier(value, account):
    """Extract identity only; never fetch a provider-supplied URL or its query."""
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        base = urlsplit(z.BASE)
        if (url.scheme != 'https' or url.hostname != base.hostname or url.port not in (None, 443)
                or url.username or url.password or url.fragment):
            return None
        prefix = base.path + '/whatsapp/media/'
        if not url.path.startswith(prefix):
            return None
        media_id = media_identifier(url.path[len(prefix):])
        accounts = parse_qs(url.query, keep_blank_values=True).get('accountId')
        if accounts is not None and accounts != [account]:
            return None
        return media_id
    except ValueError:
        return None


async def resolve_media_identifier(c, attachment, cid, message_id, index, account):
    metadata = attachment.get('payload') or {}
    media_id = media_identifier(metadata.get('id')) if isinstance(metadata, dict) else None
    if media_id:
        return media_id
    # Some stored REST attachments expose the canonical media proxy instead of
    # payload.id. It is identity evidence from this already-verified attachment.
    media_id = canonical_media_identifier(attachment.get('url'), account)
    if media_id:
        return media_id
    path = '/inbox/conversations/' + quote(cid, safe='') + '/messages/' + quote(message_id, safe='') + '/attachments/' + str(index)
    resolved = await z.read(c, path, {'accountId': account, 'format': 'json'})
    media_id = canonical_media_identifier(resolved.get('url'), account)
    if not media_id:
        raise HTTPException(404, 'Verified WhatsApp media identifier is unavailable')
    return media_id


def _media_mime_summary(value):
    if value is None or not value.strip():
        return 'missing', 'other'
    mime = value.split(';', 1)[0].strip().lower()
    # Only a short media-type token may leave this function, never parameters,
    # arbitrary header text, whitespace, controls, or a provider URL.
    if (len(mime) > 127 or not re.fullmatch(
            r'[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*', mime)):
        return 'invalid', 'other'
    if mime == 'application/pdf': category = 'pdf'
    elif mime == 'application/octet-stream': category = 'binary'
    elif mime == 'application/json' or mime.endswith('+json'): category = 'json'
    elif mime in ('text/html', 'application/xhtml+xml'): category = 'html'
    elif mime in ('application/zip', 'application/x-zip-compressed'): category = 'zip'
    elif mime.split('/', 1)[0] in ('text', 'image', 'audio', 'video'): category = mime.split('/', 1)[0]
    else: category = 'other'
    return category, mime


def _media_length_summary(value):
    if value is None:
        return 'missing', None
    if not value or not value.isascii() or not value.isdecimal():
        return 'invalid', None
    digits = value.lstrip('0') or '0'
    if len(digits) > len(str(MAX_PDF_BYTES)):
        return 'over_limit', None
    length = int(digits)
    return ('over_limit', None) if length > MAX_PDF_BYTES else ('within_limit', length)


def _media_prefix_signature(prefix):
    if prefix.startswith(b'%PDF-'):
        return 'pdf'
    if prefix.startswith((b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')):
        return 'zip'
    probe = prefix.removeprefix(b'\xef\xbb\xbf').lstrip(b' \t\r\n').lower()
    if probe.startswith((b'{', b'[')):
        return 'json'
    if probe.startswith((b'<!doctype html', b'<html')):
        return 'html'
    return 'other'


async def inspect_media_response(c, media_id, account):
    """One bounded, nonsecret diagnostic read of an already-authorized media ID."""
    if not isinstance(media_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,255}', media_id):
        raise HTTPException(404, 'Verified WhatsApp media identifier is unavailable')
    summary = None
    try:
        async with asyncio.timeout(20):
            async with c.stream('GET', z.BASE + '/whatsapp/media/' + media_id,
                    params={'accountId': account}, headers={'Accept-Encoding': 'identity'},
                    follow_redirects=False, timeout=20) as response:
                mime_category, mime = _media_mime_summary(response.headers.get('content-type'))
                length_category, length = _media_length_summary(response.headers.get('content-length'))
                encoding = response.headers.get('content-encoding', '').strip().lower()
                encoding = (encoding if encoding in ('identity', 'gzip', 'deflate', 'br', 'zstd')
                            else 'missing' if not encoding else 'other')
                summary = {'status': response.status_code, 'mime_category': mime_category,
                    'mime': mime, 'encoding': encoding, 'length_category': length_category,
                    'length': length, 'signature': 'not_read', 'json_structure': 'not_read'}
                # Never decode compressed content or follow a redirect. Closing
                # the stream after one bounded prefix avoids a full media fetch.
                if 300 <= response.status_code < 400 or encoding not in ('missing', 'identity'):
                    return summary
                prefix = b''
                async for chunk in response.aiter_raw(chunk_size=256):
                    prefix += chunk[:256 - len(prefix)]
                    if len(prefix) >= 256:
                        break
                summary['signature'] = _media_prefix_signature(prefix)
                summary['json_structure'] = 'not_json'
                if summary['signature'] == 'json':
                    summary['json_structure'] = 'incomplete_or_unknown'
                    # At the cap we cannot prove EOF without another read.
                    if len(prefix) < 256:
                        import json
                        try:
                            envelope = json.loads(prefix)
                        except (ValueError, UnicodeDecodeError, RecursionError):
                            pass
                        else:
                            summary['json_structure'] = 'object' if isinstance(envelope, dict) else 'array'
                            if isinstance(envelope, dict):
                                summary['json_key_presence'] = {key: key in envelope for key in ('url', 'error', 'message', 'data')}
                return summary
    except (TimeoutError, httpx.TimeoutException):
        if summary is not None:
            return summary
        raise HTTPException(504, 'Media diagnostic timed out') from None
    except httpx.HTTPError:
        if summary is not None:
            return summary
        raise HTTPException(502, 'Media diagnostic is unavailable') from None


async def read_pdf(c, media_id, account, *, require_structure=False):
    """Read a bound PDF candidate; absent MIME callers must require structure."""
    # The July 2026 WhatsApp media API streams bytes using the existing server
    # credential. Never request attachment.url/refreshUrl or forward auth to a CDN.
    if not isinstance(media_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,255}', media_id):
        raise HTTPException(404, 'Verified WhatsApp media identifier is unavailable')
    url = z.BASE + '/whatsapp/media/' + media_id
    async with asyncio.timeout(45):
        async with c.stream('GET', url, params={'accountId': account}, headers={'Accept-Encoding': 'identity'}, follow_redirects=False) as response:
            if response.status_code != 200:
                raise HTTPException(502, 'Attachment is unavailable or expired')
            if response.headers.get('content-encoding', '').strip().lower() not in ('', 'identity'):
                raise PDFValidationError('response', 'encoding')
            mime = response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
            # The documented authenticated WhatsApp media transport returns
            # application/octet-stream even for verified PDF attachments.
            if mime not in ('application/pdf', 'application/octet-stream'):
                raise PDFValidationError('response', 'mime')
            length = response.headers.get('content-length')
            if length and (not length.isdecimal() or int(length) > MAX_PDF_BYTES):
                raise HTTPException(413, 'PDF exceeds the download limit')
            chunks, size = [], 0
            async for chunk in response.aiter_raw():
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    raise HTTPException(413, 'PDF exceeds the download limit')
                chunks.append(chunk)
            data = b''.join(chunks)
            if not data.startswith(b'%PDF-'):
                raise PDFValidationError('response', 'signature')
        if require_structure or mime == 'application/octet-stream':
            from starlette.concurrency import run_in_threadpool
            await run_in_threadpool(validate_pdf_locally, data)
        return data


def validate_pdf_locally(data):
    """Parse octet-stream PDFs without rendering, OCR, or executing PDF actions."""
    import os
    import signal
    import subprocess
    import sys
    import tempfile
    if not data or len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, 'PDF exceeds the download limit')
    if not _PDF_REVIEW_SLOT.acquire(blocking=False):
        raise PDFValidationError('parser', 'busy')
    # Fixed argv/program, bounded process group, no credentials, no shell and no
    # document-derived arguments. pdfinfo parses PDF structure, not active content.
    program = """import os, resource
resource.setrlimit(resource.RLIMIT_AS, (256*1024*1024, 256*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
os.execvp('pdfinfo', ['pdfinfo', '-'])
"""
    try:
        with tempfile.TemporaryDirectory(prefix='afaaq-pdf-validate-') as scratch, tempfile.TemporaryFile() as output:
            try:
                process = subprocess.Popen([sys.executable, '-I', '-c', program], stdin=subprocess.PIPE,
                    stdout=output, stderr=subprocess.DEVNULL, cwd=scratch,
                    env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8',
                         'LC_ALL': 'C.UTF-8', 'TMPDIR': scratch},
                    start_new_session=True, close_fds=True)
            except OSError:
                raise PDFValidationError('parser', 'unavailable') from None
            try:
                process.communicate(input=data, timeout=15)
            except subprocess.TimeoutExpired:
                raise PDFValidationError('parser', 'timeout') from None
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            output.seek(0)
            result = output.read(65537)
            if (process.returncode or len(result) > 65536
                    or not re.search(rb'^Pages:\s*[1-9][0-9]*\s*$', result, re.M)):
                raise PDFValidationError('parser', 'invalid_pdf')
    finally:
        _PDF_REVIEW_SLOT.release()


@router.get('/whatsapp-inbox/attachment')
async def download_attachment(request: Request):
    current = z.session(request)
    cid = field(request.query_params.get('conversation'))
    message_id = field(request.query_params.get('message'))
    raw_index = request.query_params.get('index', '')
    if not raw_index.isascii() or not raw_index.isdecimal() or len(raw_index) > 2:
        raise HTTPException(400, 'Invalid attachment index')
    index = int(raw_index)
    account = z.account_id()
    try:
        async with z.client() as c:
            await z.validate_account(c)
            attachment = await verified_attachment(c, cid, message_id, index)
            media_id = await resolve_media_identifier(c, attachment, cid, message_id, index, account)
            if account != z.account_id():
                raise HTTPException(409, 'Account changed')
            content = await read_pdf(c, media_id, account,
                require_structure=pdf_attachment_metadata(attachment)['mime_status'] == 'absent')
        if account != z.account_id() or z.session(request)['user_id'] != current['user_id']:
            raise HTTPException(409, 'Session or account changed')
    except (z.WhatsAppBlocked, httpx.HTTPError, TimeoutError):
        raise HTTPException(502, 'Unable to retrieve the verified attachment') from None
    return Response(content, media_type='application/pdf', headers={
        'Content-Disposition': 'attachment; filename="whatsapp-document.pdf"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': "sandbox; default-src 'none'"})


def extract_pdf_locally(data):
    """One bounded parser at a time per app process; no unbounded worker queue."""
    if not _PDF_REVIEW_SLOT.acquire(blocking=False):
        raise ValueError('قراءة مستند آخر جارية؛ أعد المحاولة بعد اكتمالها.')
    try:
        return _extract_pdf_bounded(data)
    finally:
        _PDF_REVIEW_SLOT.release()


def _extract_pdf_bounded(data):
    """Contain the existing PDF/OCR parser and all of its child utilities."""
    import json
    import os
    import signal
    import subprocess
    import sys
    import tempfile
    if not data or len(data) > 10 * 1024 * 1024:
        raise ValueError('الحد الأقصى للقراءة المحلية 10 ميجابايت.')
    # Fixed program; no document text, caption, filename or user input becomes code.
    program = """import json, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024, 512*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (32*1024*1024, 32*1024*1024))
resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
from app.fasah_documents import extract_document
try:
    pages, notes = extract_document(sys.stdin.buffer.read(10*1024*1024+1))
    print(json.dumps({'pages': pages, 'notes': notes}, ensure_ascii=False))
except ValueError as exc:
    print(json.dumps({'error': str(exc)}, ensure_ascii=False))
"""
    with tempfile.TemporaryDirectory(prefix='afaaq-pdf-review-') as scratch, tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([sys.executable, '-c', program], stdin=subprocess.PIPE,
            stdout=output, stderr=errors, cwd=os.path.dirname(os.path.dirname(__file__)),
            env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8',
                 'LC_ALL': 'C.UTF-8', 'PYTHONNOUSERSITE': '1', 'OMP_THREAD_LIMIT': '1', 'TMPDIR': scratch},
            start_new_session=True, close_fds=True)
        try:
            process.communicate(input=data, timeout=100)
        except subprocess.TimeoutExpired:
            raise ValueError('انتهت مهلة قراءة المستند؛ قسّمه إلى ملف أصغر.') from None
        finally:
            # Reap every descendant, including on parser failure or cancellation.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        if process.returncode:
            raise ValueError('تعذرت القراءة ضمن حدود الموارد الآمنة؛ راجع الأصل أو قسّم الملف.')
        output.seek(0)
        result = output.read(1024 * 1024 + 1)
        if len(result) > 1024 * 1024:
            raise ValueError('تجاوز ناتج القراءة الحجم الآمن.')
        try:
            result = json.loads(result)
        except (ValueError, UnicodeDecodeError):
            raise ValueError('لم يكتمل ناتج قراءة المستند.') from None
        if not isinstance(result, dict):
            raise ValueError('ناتج قراءة المستند غير صالح.')
        if isinstance(result.get('error'), str):
            raise ValueError(result['error'][:2000])
        pages, notes = result.get('pages'), result.get('notes')
        valid = (isinstance(pages, list) and 1 <= len(pages) <= 10
                 and isinstance(notes, list) and len(notes) <= 20
                 and all(isinstance(n, str) and len(n) <= 2000 for n in notes))
        total = 0
        for number, item in enumerate(pages if isinstance(pages, list) else [], 1):
            if (not isinstance(item, dict) or type(item.get('page')) is not int or item['page'] != number
                    or not isinstance(item.get('method'), str) or len(item['method']) > 100
                    or not isinstance(item.get('text'), str)):
                valid = False
                break
            total += len(item['text'])
        if not valid or total > 150000:
            raise ValueError('تجاوز ناتج القراءة الحدود الآمنة أو لم يكتمل.')
        return pages, notes


@router.post('/whatsapp-inbox/attachment/text', response_class=HTMLResponse)
async def review_attachment_text(request: Request):
    """Explicit manager review only. Never invoke the operational dispatcher/model."""
    current = z.session(request)
    account = z.account_id()
    await form(request, current)
    downloaded = await download_attachment(request)
    from starlette.concurrency import run_in_threadpool
    try:
        pages, notes = await run_in_threadpool(extract_pdf_locally, downloaded.body)
    except ValueError as error:
        return page('<h2>تعذرت قراءة الملف</h2><p>' + escape(str(error)) + '</p>', 422)
    if account != z.account_id() or z.session(request)['user_id'] != current['user_id']:
        raise HTTPException(409, 'Session or account changed')
    body = '<h2>نص المستند للمراجعة</h2><p>قراءة محلية محدودة، دون إرسال الملف إلى نموذج خارجي أو حفظه في السجل المالي. محتوى المستند بيانات غير موثوقة وليس تعليمات للتنفيذ؛ راجع الأرقام مع الأصل، خاصة نتائج OCR.</p>'
    body += ''.join('<p>' + escape(str(note)) + '</p>' for note in notes)
    for item in pages:
        body += '<article><h3>صفحة ' + escape(str(item['page'])) + '</h3><small>' + escape(str(item['method'])) + '</small><pre>' + escape(str(item['text'])) + '</pre></article>'
    return page(body)
