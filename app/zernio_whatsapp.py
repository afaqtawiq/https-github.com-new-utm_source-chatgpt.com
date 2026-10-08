"""Transport WhatsApp adapter. Provider acceptance is not delivery confirmation."""
import asyncio
import inspect
import logging
import math
import os
import re
import time
import uuid
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import escape
from urllib.parse import quote, parse_qs

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

BASE = 'https://zernio.com/api/v1'
router = APIRouter()
logger = logging.getLogger(__name__)
_READ_ATTEMPTS = 3
_READ_BUDGET_SECONDS = 90
_BATCH_WAIT_BUDGET_SECONDS = 180
_BATCH_BUDGET_SECONDS = 300
_CACHE_SECONDS = 30
_sleep = asyncio.sleep
_monotonic = time.monotonic
_wall_time = time.time
_batch = ContextVar('zernio_transport_batch', default=None)
_dispatch_guard = ContextVar('zernio_dispatch_guard', default=None)


class WhatsAppBlocked(RuntimeError):
    """A preflight or explicit rejection proves no message was accepted."""


class WhatsAppPreflightBlocked(WhatsAppBlocked):
    """A read/rate gate failed before the send POST was attempted."""

    def __init__(self, diagnostic, *, retryable):
        super().__init__('تعذر التحقق من إعداد واتساب لدى Zernio؛ لم تُرسل الرسالة')
        self.diagnostic = dict(diagnostic)
        self.retryable = bool(retryable)


class WhatsAppSendUncertain(RuntimeError):
    """The POST happened, but its response did not prove provider acceptance."""

    def __init__(self, http_status):
        super().__init__('نتيجة إرسال واتساب غير مؤكدة؛ راجع المزود قبل إعادة المحاولة')
        self.http_status = http_status


class WhatsAppDocumentSendUncertain(WhatsAppSendUncertain):
    """A document POST was attempted; durable callers must freeze, never retry."""

    def __init__(self, http_status, reason='uncertain', *, provider_ids=(), public_attachment_url_present=False):
        if reason not in ('uncertain', 'invalid_receipt', 'receipt_mismatch', 'contradictory_response'):
            raise ValueError('Invalid document outcome category')
        super().__init__(http_status)
        self.reason = reason
        self.provider_ids = list(provider_ids)
        self.public_attachment_url_present = bool(public_attachment_url_present)


class _TransportState:
    def __init__(self, *, cache=False):
        self.account = account_id()
        self.cache_enabled = cache
        self.cache = {}
        self.windows = {}
        self.auth_error = None
        self.lock = asyncio.Lock()
        self.not_before = 0
        self.wait_spent = 0
        self.deadline = _monotonic() + _BATCH_BUDGET_SECONDS
        self.rate_hints = {}
        self.stack = AsyncExitStack()
        self.client = None

    async def get_client(self):
        async with self.lock:
            if self.client is None:
                self.client = await self.stack.enter_async_context(client())
                self.client._afaaq_whatsapp_state = self
        return self.client


@asynccontextmanager
async def transport_batch():
    """Share a lazy client and short account-scoped read cache within one batch."""
    existing = _batch.get()
    if existing is not None:
        _check_account(existing, '/accounts')
        yield existing
        return
    state = _TransportState(cache=True)
    token = _batch.set(state)
    try:
        async with state.stack:
            yield state
    finally:
        _batch.reset(token)


@contextmanager
def dispatch_guard(callback):
    """Run a caller's ownership/stop check immediately before the only send POST."""
    token = _dispatch_guard.set(callback)
    try:
        yield
    finally:
        _dispatch_guard.reset(token)


def _state_for(c):
    state = getattr(c, '_afaaq_whatsapp_state', None)
    if state is None:
        state = _TransportState()
        c._afaaq_whatsapp_state = state
    return state


def _endpoint(path):
    if path == '/accounts': return 'accounts'
    if path == '/whatsapp/templates': return 'templates'
    if path == '/inbox/conversations': return 'conversations'
    if path.startswith('/inbox/conversations/') and path.endswith('/messages'):
        return 'conversation_messages'
    return 'other'


def _diagnostic(path, category, *, retryable, status=None, attempt=0, hints=None):
    # Strictly allowlisted categories and numeric headers; never URLs, IDs, bodies,
    # request/exception text, recipient data, or credentials in logs or persistence.
    return {'phase': 'preflight', 'endpoint': _endpoint(path), 'http_status': status,
            'error_category': category, 'attempts': attempt, 'retryable': bool(retryable), **(hints or {})}


def _blocked(path, category, *, retryable, status=None, attempt=0, hints=None):
    diagnostic = _diagnostic(path, category, retryable=retryable, status=status, attempt=attempt, hints=hints)
    logger.warning('Zernio WhatsApp preflight blocked: %s', diagnostic)
    return WhatsAppPreflightBlocked(diagnostic, retryable=retryable)


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _observe_rate(state, response):
    """Honor documented Zernio headers on GET and POST, without parsing bodies."""
    # https://docs.zernio.com/guides/rate-limits (Reset is Unix seconds).
    now, hints = _wall_time(), {}
    for header, key in (('X-RateLimit-Limit', 'rate_limit'),
                        ('X-RateLimit-Remaining', 'rate_remaining'),
                        ('X-RateLimit-Reset', 'rate_reset_unix')):
        value = _number(response.headers.get(header))
        if value is not None: hints[key] = value
    retry = response.headers.get('Retry-After')
    delay = _number(retry)
    if delay is None and retry:
        try:
            delay = max(0, parsedate_to_datetime(retry).timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            pass
    if delay is not None: hints['retry_after_seconds'] = delay
    if hints.get('rate_remaining') == 0:
        reset_delay = (max(0, hints['rate_reset_unix'] - now) if 'rate_reset_unix' in hints
                       else delay if delay is not None else 60)
        delay = max(delay or 0, reset_delay)
    if delay is not None:
        state.not_before = max(state.not_before, _monotonic() + delay)
    state.rate_hints = hints
    return hints


def _check_account(state, path):
    if state.account != account_id():
        raise _blocked(path, 'account_changed', retryable=False)
    if state.auth_error is not None:
        raise WhatsAppPreflightBlocked(state.auth_error, retryable=False)


def _check_window(state, path, target, cid, proof):
    if cid is None:
        return
    if (not proof or proof[:3] != (state.account, target, str(cid))
            or not timedelta(0) <= datetime.now(timezone.utc) - proof[3] < timedelta(hours=23, minutes=55)):
        raise _blocked(path, 'conversation_window_expired', retryable=False)


def _check_deadline(state, path, deadline, *, attempt=0, status=None):
    if _monotonic() >= min(deadline, state.deadline):
        raise _blocked(path, 'batch_budget_exhausted' if _monotonic() >= state.deadline else 'read_budget_exhausted',
                       retryable=True, status=status, attempt=attempt, hints=state.rate_hints)


async def _wait_ready(state, path, deadline, *, attempt=0, backoff=0, status=None):
    _check_account(state, path)
    _check_deadline(state, path, deadline, attempt=attempt, status=status)
    deadline = min(deadline, state.deadline)
    delay = max(0, state.not_before - _monotonic(), backoff)
    remaining = deadline - _monotonic()
    if delay >= remaining:
        raise _blocked(path, 'rate_wait_exceeds_budget' if delay else 'read_budget_exhausted',
                       retryable=True, status=status, attempt=attempt, hints=state.rate_hints)
    if state.wait_spent + delay > _BATCH_WAIT_BUDGET_SECONDS:
        raise _blocked(path, 'batch_wait_exceeds_budget', retryable=True,
                       status=status, attempt=attempt, hints=state.rate_hints)
    if delay:
        state.wait_spent += delay
        await _sleep(delay)
    _check_deadline(state, path, deadline, attempt=attempt, status=status)
    _check_account(state, path)


def account_id():
    return os.getenv('ZERNIO_WHATSAPP_ACCOUNT_ID', '') or os.getenv('WHATSAPP_COMMAND_ACCOUNT_ID', '')


def configured():
    return bool(os.getenv('ZERNIO_API_KEY') and account_id() and os.getenv('ZERNIO_WEBHOOK_SECRET'))


def phone(value):
    value = re.sub(r'[ ()+-]', '', str(value or ''))
    return value if re.fullmatch(r'[1-9][0-9]{8,14}', value) else ''


async def read(client, path, params=None):
    state = _state_for(client)
    deadline = min(_monotonic() + _READ_BUDGET_SECONDS, state.deadline)
    key = (state.account, path, tuple(sorted((params or {}).items())))
    cacheable = state.cache_enabled and path in ('/accounts', '/whatsapp/templates', '/inbox/conversations')
    async with state.lock:
        _check_account(state, path)
        cached = state.cache.get(key) if cacheable else None
        if cached and cached[0] > _monotonic():
            return cached[1]
        status, backoff = None, 0
        for attempt in range(1, _READ_ATTEMPTS + 1):
            await _wait_ready(state, path, deadline, attempt=attempt - 1, backoff=backoff, status=status)
            status, hints = None, {}
            try:
                response = await asyncio.wait_for(client.get(BASE + path, params=params),
                                                 timeout=deadline - _monotonic())
                status = response.status_code
                hints = _observe_rate(state, response)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError('Expected a JSON object')
            except httpx.HTTPStatusError:
                category = ('authentication' if status in (401, 403) else 'rate_limited' if status == 429
                            else 'server_error' if status >= 500 else 'http_error')
                retryable = status == 429 or 500 <= status < 600
            except (httpx.TimeoutException, asyncio.TimeoutError):
                category, retryable = 'timeout', True
            except httpx.RequestError:
                category, retryable = 'network_error', True
            except ValueError:
                category, retryable = 'invalid_json', True
            else:
                if cacheable:
                    state.cache[key] = (_monotonic() + _CACHE_SECONDS, payload)
                return payload
            diagnostic = _diagnostic(path, category, retryable=retryable, status=status, attempt=attempt, hints=hints)
            logger.warning('Zernio WhatsApp GET failed: %s', diagnostic)
            if category == 'authentication':
                # An account/template cache cannot override a later failed auth
                # check. Stop every subsequent recipient in this batch before IO.
                state.cache.clear()
                state.windows.clear()
                state.auth_error = diagnostic
            if not retryable or attempt == _READ_ATTEMPTS:
                raise WhatsAppPreflightBlocked(diagnostic, retryable=retryable) from None
            backoff = 2 ** (attempt - 1)


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
    from app.transport_owner import OWNER_INQUIRY_TEMPLATE, inquiry, legacy_v2_inquiry, short_inquiry
    from app.transport_test import DISCLAIMER
    return [
        {'name': OWNER_INQUIRY_TEMPLATE, 'language': 'ar', 'category': 'MARKETING',
         'components': [{'type': 'body', 'text': inquiry('{{1}}', '{{2}}'),
                         'example': {'body_text': [['جدة', 'دبي']]}}]},
        {'name': 'afaaq_transport_owner_inquiry_v3_ar', 'language': 'ar', 'category': 'MARKETING',
         'components': [{'type': 'body', 'text': short_inquiry('{{1}}', '{{2}}'),
                         'example': {'body_text': [['جدة', 'الشارقة']]}}]},
        {'name': 'afaaq_transport_test_owner_inquiry_v1_ar', 'language': 'ar', 'category': 'MARKETING',
         'components': [{'type': 'body', 'text': DISCLAIMER + '\n' + short_inquiry('{{1}}', '{{2}}'),
                         'example': {'body_text': [['جدة', 'الشارقة']]}}]},
        {'name': 'afaaq_transport_owner_inquiry_v2_ar', 'language': 'ar', 'category': 'MARKETING',
         'components': [{'type': 'body', 'text': legacy_v2_inquiry('{{1}}', '{{2}}'),
                         'example': {'body_text': [['رابغ', 'دبي']]}}]},
        {'name': 'afaaq_transport_driver_offer_v1_ar', 'language': 'ar', 'category': 'MARKETING',
         'components': [{'type': 'body', 'text': 'عرض حمولة من آفاق طويق — {{1}}\nالمسار: {{2}} → {{3}}\nالوزن: {{4}} طن\nسعر السائق: {{5}} ريال\nالتنزيل: {{6}}\nالدفع: {{7}}\nللرغبة اكتب: موافق {{1}}\nشكرًا لتعاونك.',
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
                    if (not isinstance(msg, dict)
                            or msg.get('accountId', account_id()) != account_id()
                            or msg.get('conversationId', cid) != cid
                            or msg.get('platform', 'whatsapp') != 'whatsapp'):
                        raise WhatsAppBlocked('هوية رسالة نافذة المحادثة غير مطابقة؛ لم تُرسل الرسالة')
                    if msg.get('direction') != 'incoming' or phone(msg.get('senderId')) != target:
                        continue
                    try:
                        at = datetime.fromisoformat(msg['createdAt'].replace('Z', '+00:00'))
                        if timedelta(0) <= now - at < timedelta(hours=23, minutes=55):
                            _state_for(c).windows[(target, str(cid))] = (account_id(), target, str(cid), at)
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


async def send(recipient, message, *, template_prefix='afaaq_transport_', expected_account=None, expected_conversation=None, idempotency_key=None):
    if template_prefix not in ('afaaq_transport_', 'afaaq_marketing_'):
        raise WhatsAppBlocked('نوع قالب الإرسال غير مسموح')
    if idempotency_key is not None and not re.fullmatch(r'wa-agent-[0-9a-f]{64}', idempotency_key):
        raise WhatsAppBlocked('معرف محاولة الإرسال غير صالح')
    target = phone(recipient)
    if not target or not message.strip():
        raise WhatsAppBlocked('رقم المستلم أو نص الرسالة غير صالح')
    if expected_account is not None and expected_account != account_id():
        raise WhatsAppBlocked('تغير حساب واتساب؛ لم تُرسل الرسالة')
    async with transport_batch() as batch:
        c = await batch.get_client()
        await validate_account(c)
        cid = await open_conversation(c, target)
        if expected_conversation is not None and (not cid or str(cid) != expected_conversation):
            raise WhatsAppBlocked('المحادثة تغيرت أو نافذة الرد مغلقة؛ لم تُرسل الرسالة')
        proof = batch.windows.get((target, str(cid)))
        body = {'accountId': account_id()}
        if cid:
            path = '/inbox/conversations/' + quote(cid, safe='') + '/messages'
            body['message'] = message
        else:
            options = await templates(c)
            selected = None
            # A real-owner inquiry must use the current v4 schema. A broad
            # approved placeholder must never swallow its fixed questions/footer.
            from app.transport_owner import OWNER_INQUIRY_TEMPLATE, inquiry
            owner_body = inquiry('{{1}}', '{{2}}')
            owner_spec = {'components': [{'type': 'BODY', 'text': owner_body}]}
            owner_params = template_parameters(owner_spec, message) if template_prefix == 'afaaq_transport_' else None
            for template in options:
                if not template.get('name', '').startswith(template_prefix) or template.get('language') != 'ar':
                    continue
                if owner_params is not None:
                    components = template.get('components') or []
                    if (template.get('name') != OWNER_INQUIRY_TEMPLATE
                            or len(components) != 1
                            or components[0].get('type', '').upper() != 'BODY'
                            or components[0].get('text') != owner_body):
                        continue
                    params = owner_params
                else:
                    params = template_parameters(template, message)
                if params is not None and template.get('status') == 'APPROVED':
                    selected = (template, params)
                    break
            if selected is None:
                raise WhatsAppBlocked('لا توجد نافذة محادثة مفتوحة ولا قالب معتمد مطابق للرسالة؛ راجع اعتماد Meta في صفحة قناة واتساب. لم تُرسل الرسالة')
            template, params = selected
            path = '/inbox/conversations'
            body.update(participantId=target, templateName=template['name'], templateLanguage='ar', templateParams=params)
        # The rate gate and optional caller guard are still BEFORE the sending
        # boundary. No automatic retry after that boundary, even with idempotency.
        async with batch.lock:
            deadline = min(_monotonic() + _READ_BUDGET_SECONDS, batch.deadline)
            await _wait_ready(batch, path, deadline)
            _check_window(batch, path, target, cid, proof)
            guard = _dispatch_guard.get()
            if guard is not None:
                result = guard()
                if inspect.isawaitable(result):
                    await result
            # A guard can itself await; never let that extend a freeform window.
            _check_deadline(batch, path, deadline)
            _check_account(batch, path)
            _check_window(batch, path, target, cid, proof)
            response = await c.post(BASE + path, json=body, headers={'Idempotency-Key': idempotency_key or 'afaaq-' + uuid.uuid4().hex})
            _observe_rate(batch, response)
        if 400 <= response.status_code < 500 and response.status_code not in (408, 409):
            error = WhatsAppBlocked('رفض مزود واتساب الإرسال (HTTP ' + str(response.status_code) + ')؛ راجع القالب وصلاحية الحساب')
            error.http_status = response.status_code
            raise error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            error.http_status = response.status_code
            raise
        try:
            data = response.json()
        except ValueError:
            raise WhatsAppSendUncertain(response.status_code) from None
        receipt = data.get('data') if isinstance(data, dict) else None
        mid = receipt.get('messageId') if isinstance(receipt, dict) else None
        if (not isinstance(data, dict) or data.get('success') is not True or not isinstance(mid, str)
                or not mid.strip() or receipt.get('partialFailure')):
            raise WhatsAppSendUncertain(response.status_code)
        return {'provider': 'zernio', 'messages': [{'id': mid}], 'conversation_id': receipt.get('conversationId'),
                'http_status': response.status_code, 'account_id': batch.account}


MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


def _document_receipt_ids(receipt):
    def valid(value):
        return (isinstance(value, str) and len(value) <= 1024 and '://' not in value
                and not value.lower().startswith(('http:', 'https:', 'ftp:', 'file:', 'data:', 'mailto:', 'www.', '/'))
                and re.fullmatch(r'[A-Za-z0-9_.:+/=\-]+', value) is not None)
    mid = receipt.get('messageId')
    ids = receipt.get('messageIds', [mid])
    if (not valid(mid) or not isinstance(ids, list) or not 1 <= len(ids) <= 5
            or not all(valid(value) for value in ids) or ids[0] != mid or len(set(ids)) != len(ids)):
        return None
    return ids


async def send_document(recipient, content, filename, caption='', *, expected_account,
                        expected_conversation, idempotency_key):
    """One direct multipart PDF POST. Partial/warning results are frozen outcomes."""
    import unicodedata
    target = phone(recipient)
    if (not target or not isinstance(expected_account, str) or not expected_account
            or expected_account != account_id() or not isinstance(expected_conversation, str)
            or not expected_conversation or len(expected_conversation) > 255
            or expected_conversation in ('.', '..')
            or any(ord(char) < 32 or ord(char) == 127 for char in expected_conversation)):
        raise WhatsAppBlocked('هوية المستلم أو الحساب أو المحادثة غير صالحة؛ لم يُرسل الملف')
    if not isinstance(idempotency_key, str) or not re.fullmatch(r'wa-document-[0-9a-f]{64}', idempotency_key):
        raise WhatsAppBlocked('معرف محاولة إرسال الملف غير صالح')
    if not isinstance(content, bytes) or not content.startswith(b'%PDF-') or len(content) > MAX_DOCUMENT_BYTES:
        raise WhatsAppBlocked('يلزم ملف PDF ضمن حد 20 ميجابايت؛ لم يُرسل الملف')
    if (not isinstance(filename, str) or not 4 < len(filename) <= 180
            or len(filename.encode('utf-8', errors='replace')) > 255
            or filename != filename.strip() or not filename.lower().endswith('.pdf')
            or any(char in '/\\' or unicodedata.category(char).startswith('C') for char in filename)):
        raise WhatsAppBlocked('اسم ملف PDF غير صالح؛ لم يُرسل الملف')
    if not isinstance(caption, str) or len(caption) > 1024:
        raise WhatsAppBlocked('وصف الملف غير صالح؛ لم يُرسل الملف')
    if _dispatch_guard.get() is None:
        raise WhatsAppBlocked('يلزم التحقق من صلاحية إرسال الملف قبل المحاولة')
    from app.whatsapp_inbox import validate_pdf_locally
    from starlette.concurrency import run_in_threadpool
    try:
        await run_in_threadpool(validate_pdf_locally, content)
    except (HTTPException, ValueError, OSError):
        raise WhatsAppBlocked('تعذر التحقق المحلي من ملف PDF؛ لم يُرسل الملف') from None
    async with transport_batch() as batch:
        # Parsing awaited in a worker: never adopt an account changed while the
        # reviewed bytes were being checked, including an existing batch scope.
        if batch.account != expected_account or account_id() != expected_account:
            raise WhatsAppBlocked('تغير حساب واتساب أثناء مراجعة الملف؛ لم يُرسل الملف')
        c = await batch.get_client()
        await validate_account(c)
        cid = await open_conversation(c, target)
        if not cid or str(cid) != expected_conversation:
            raise WhatsAppBlocked('المحادثة تغيرت أو نافذة الرد مغلقة؛ لم يُرسل الملف')
        path = '/inbox/conversations/' + quote(expected_conversation, safe='') + '/messages'
        proof = batch.windows.get((target, str(cid)))
        async with batch.lock:
            deadline = min(_monotonic() + _READ_BUDGET_SECONDS, batch.deadline)
            await _wait_ready(batch, path, deadline)
            _check_window(batch, path, target, cid, proof)
            guard = _dispatch_guard.get()
            if guard is None:
                raise WhatsAppBlocked('صلاحية إرسال الملف لم تعد متاحة؛ لم يُرسل الملف')
            checked = guard()
            if inspect.isawaitable(checked):
                await checked
            _check_deadline(batch, path, deadline)
            _check_account(batch, path)
            _check_window(batch, path, target, cid, proof)
            # Caller has durably reserved this key and marked its exact reviewed
            # document as sending. No retry exists beyond this boundary.
            try:
                response = await c.post(BASE + path,
                    data={'accountId': batch.account, 'message': caption},
                    files={'attachment': (filename, content, 'application/pdf')},
                    headers={'Idempotency-Key': idempotency_key}, follow_redirects=False)
            except (httpx.HTTPError, TimeoutError, asyncio.CancelledError):
                raise WhatsAppDocumentSendUncertain(None) from None
            _observe_rate(batch, response)
        status = response.status_code
        try:
            data = response.json()
        except ValueError:
            data = None
        receipt = data.get('data') if isinstance(data, dict) else None
        provider_ids = _document_receipt_ids(receipt) if isinstance(receipt, dict) else None
        attachments = receipt.get('attachments', []) if isinstance(receipt, dict) else []
        public_url = (isinstance(attachments, list) and any(isinstance(item, dict)
            and isinstance(item.get('url'), str) and bool(item['url']) for item in attachments))
        acceptance_evidence = ((isinstance(data, dict) and data.get('success') is True)
            or (isinstance(receipt, dict) and any(receipt.get(key) is not None
                for key in ('messageId', 'messageIds', 'partialFailure'))) or public_url)
        if 400 <= status < 500 and status not in (408, 409) and not acceptance_evidence:
            error = WhatsAppBlocked('رفض مزود واتساب إرسال الملف (HTTP ' + str(status) + ')')
            error.http_status = status
            raise error
        if not 200 <= status < 300:
            raise WhatsAppDocumentSendUncertain(status,
                'contradictory_response' if acceptance_evidence else 'uncertain',
                provider_ids=provider_ids or [], public_attachment_url_present=public_url)
        if not isinstance(data, dict) or data.get('success') is not True or not isinstance(receipt, dict):
            raise WhatsAppDocumentSendUncertain(status, 'invalid_receipt',
                provider_ids=provider_ids or [], public_attachment_url_present=public_url)
        if public_url:
            outcome = 'public_link_warning'
        elif receipt.get('partialFailure') is not None:
            outcome = 'partial'
        elif provider_ids is None or not isinstance(attachments, list):
            raise WhatsAppDocumentSendUncertain(status, 'invalid_receipt', provider_ids=provider_ids or [])
        elif receipt.get('conversationId', expected_conversation) != expected_conversation:
            raise WhatsAppDocumentSendUncertain(status, 'receipt_mismatch', provider_ids=provider_ids)
        else:
            outcome = 'accepted'
        return {'status': outcome, 'provider': 'zernio', 'provider_ids': provider_ids or [],
                'http_status': status, 'account_id': batch.account,
                'conversation_id': expected_conversation, 'public_attachment_url_present': public_url}


def session(request):
    from app.storage import get_session
    value = get_session(request.cookies.get('gla_session'))
    if not value: raise HTTPException(401)
    if value.get('role') != 'admin': raise HTTPException(403)
    return value


@router.get('/settings/whatsapp/channel', response_class=HTMLResponse)
async def channel_page(request: Request):
    from app.transport_owner import OWNER_INQUIRY_TEMPLATE
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
    <p>تعريف صاحب الحمولة الجديد: معك آفاق طويق للتخليص الجمركي والنقل. يلزم اعتماد Meta للقالب {OWNER_INQUIRY_TEMPLATE} قبل بدء التواصل بهذه الصيغة.</p>
    <form method=post action=/settings/whatsapp/channel/templates><input type=hidden name=csrf value="{escape(s['csrf'])}"><input type=hidden name=template_name value="{OWNER_INQUIRY_TEMPLATE}"><button>تجهيز قالب التخليص الجمركي والنقل فقط (v4)</button></form>
    <form method=post action=/settings/whatsapp/channel/templates><input type=hidden name=csrf value="{escape(s['csrf'])}"><button>تجهيز قوالب أصحاب الحمولات والسائقين الناقصة</button></form>
    <p>هذا الإجراء يرفع القوالب للمراجعة فقط، ولا يرسل رسائل للعملاء أو السائقين.</p>
    <p><a href=/freight-workflow>الشحنات</a> · <a href=/readiness>جاهزية التشغيل</a></p></div>'''))


@router.post('/settings/whatsapp/channel/templates')
async def provision_templates(request: Request):
    from app.transport_owner import OWNER_INQUIRY_TEMPLATE
    s = session(request)
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    if form.get('csrf', [''])[0] != s['csrf']: raise HTTPException(403)
    required = required_templates()
    if 'template_name' in form:
        # A malformed or unexpected selector must never fall back to bulk
        # registration. The new scoped control may create only current v4.
        if form['template_name'] != [OWNER_INQUIRY_TEMPLATE]:
            raise HTTPException(400, 'اختيار قالب الاستفسار غير صالح؛ لم يتم تجهيز أي قالب')
        required = [t for t in required if t['name'] == OWNER_INQUIRY_TEMPLATE]
    async with client() as c:
        await validate_account(c)
        listing = await templates(c)
        for template in required:
            if any(t.get('name') == template['name'] and t.get('language') == 'ar' for t in listing):
                continue
            response = await c.post(BASE + '/whatsapp/templates', json={'accountId': account_id(), **template})
            if not response.is_success:
                from app.freight_workflow import _page
                try:
                    failure = response.json()
                    detail = str(failure.get('error') or failure.get('message') or '')
                except (ValueError, AttributeError):
                    detail = ''
                detail = detail.replace(os.getenv('ZERNIO_API_KEY', 'not-a-key'), '[redacted]')[:600]
                return HTMLResponse(_page('تعذر تجهيز القالب',
                    '<div class=card><h1>لم يتم تأكيد إنشاء القالب</h1><p>HTTP ' + str(response.status_code) + '</p><p>' + escape(detail) +
                    '</p><p>لم تُرسل رسائل إلى العملاء أو السائقين.</p><a href=/settings/whatsapp/channel>العودة إلى حالة القوالب</a></div>'))
    return RedirectResponse('/settings/whatsapp/channel', status_code=303)
