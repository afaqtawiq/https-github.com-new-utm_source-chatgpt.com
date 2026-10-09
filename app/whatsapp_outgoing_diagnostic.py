"""Bounded, read-only privacy inspection of a creator-owned document receipt.

Provider metadata stays server-side. A URL is never accepted from the caller,
returned, persisted, logged, resolved, or followed. The optional anonymous check
uses only an exact fixed-origin media path from verified outgoing metadata and
requires an explicit fictional/nonsensitive-file affirmation for this request.
"""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import hmac
import json
import logging
import re
from urllib.parse import parse_qsl, quote, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app import whatsapp_document_store as documents
from app import whatsapp_inbox as inbox
from app import zernio_whatsapp as z

router = APIRouter()
_PROVIDER_BASE = 'https://zernio.com/api/v1'
_MEDIA_PREFIX = '/api/v1/whatsapp/media/'
# No CDN host has been verified for this provider. Keep this empty until a
# reviewed provider contract establishes exact hosts; never infer suffixes.
_PROVIDER_CDN_HOSTS = frozenset()
_METADATA_BYTES = 1024 * 1024
_MAX_PAGES = 5
_TOTAL_SECONDS = 25
_PROBE_SECONDS = 5
_PROBE_BYTES = 256
_FORM_KEYS = frozenset({'csrf', 'sha256', 'account', 'conversation', 'recipient',
                        'receipt', 'probe', 'fictional'})
_STATES = frozenset({'accepted', 'partial', 'uncertain', 'public_link_warning'})
_quiet = ContextVar('whatsapp_outgoing_diagnostic_io', default=False)


class _DiagnosticLogFilter(logging.Filter):
    def filter(self, record):
        # httpx logs complete request URLs at INFO; httpcore DEBUG can include
        # headers. Suppress only this task's diagnostic IO, not concurrent tasks.
        return not _quiet.get()


_LOG_FILTER = _DiagnosticLogFilter()


@contextmanager
def _quiet_http():
    # Known httpcore trace loggers plus any already-created descendants. Logger
    # filters are applied at the emitting logger, not at ancestor propagation.
    names = {'httpx', 'httpcore', 'httpcore.connection', 'httpcore.http11',
             'httpcore.http2', 'httpcore.proxy', 'httpcore.socks',
             'httpcore.connection_pool'}
    names.update(name for name in tuple(logging.Logger.manager.loggerDict)
                 if name.startswith(('httpcore.', 'httpx.')))
    for name in names:
        logger = logging.getLogger(name)
        if _LOG_FILTER not in logger.filters:
            logger.addFilter(_LOG_FILTER)
    token = _quiet.set(True)
    try:
        yield
    finally:
        _quiet.reset(token)


def _fail(reason, status=409):
    raise HTTPException(status, reason)


def _canonical_media(value, account):
    """Return only validated media identity, never an arbitrary target URL."""
    if (not isinstance(value, str) or len(value) > 4096
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.netloc != 'zernio.com'
                or parsed.fragment or not parsed.path.startswith(_MEDIA_PREFIX)):
            return None
        media_id = parsed.path[len(_MEDIA_PREFIX):]
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,255}', media_id):
            return None
        query = parse_qsl(parsed.query, keep_blank_values=True,
                          strict_parsing=True, max_num_fields=2)
        if query not in ([], [('accountId', account)]):
            return None
        # Reject alternate query spellings/extra delimiters and preserve the
        # exact canonical target's account-query presence for the no-auth check.
        canonical = httpx.URL(_PROVIDER_BASE + '/whatsapp/media/' + media_id,
                              params={'accountId': account} if query else None)
        if str(canonical) != value:
            return None
        return media_id, bool(query)
    except (ValueError, TypeError):
        return None


def classify_origin(value, account):
    if value is None or value == '':
        return 'absent'
    if _canonical_media(value, account):
        return 'canonical_provider_proxy'
    if isinstance(value, str) and len(value) <= 4096:
        try:
            parsed = urlsplit(value)
            if (parsed.scheme == 'https' and parsed.netloc in _PROVIDER_CDN_HOSTS
                    and not parsed.fragment):
                return 'allowlisted_provider_cdn'
        except ValueError:
            pass
    return 'unknown'


async def _read_metadata(client, path, params, authority):
    authority()
    # All paths are built below from fixed endpoint segments and quoted IDs.
    async with client.stream('GET', _PROVIDER_BASE + path, params=params,
            headers={'Accept-Encoding': 'identity'}, follow_redirects=False,
            timeout=8) as response:
        if response.status_code != 200:
            _fail('provider_metadata_unavailable', 502)
        if response.headers.get('content-encoding', '').strip().lower() not in ('', 'identity'):
            _fail('provider_metadata_encoding', 502)
        raw = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            if len(raw) + len(chunk) > _METADATA_BYTES:
                _fail('provider_metadata_limit', 502)
            raw.extend(chunk)
    authority()
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        _fail('provider_metadata_invalid', 502)
    if not isinstance(payload, dict):
        _fail('provider_metadata_invalid', 502)
    meta = payload.get('meta') or {}
    if not isinstance(meta, dict) or meta.get('accountsFailed') or meta.get('accountsSkipped'):
        _fail('provider_metadata_incomplete', 502)
    return payload


def _next_cursor(payload, visited):
    pagination = payload.get('pagination') or {}
    if not isinstance(pagination, dict):
        _fail('provider_metadata_invalid', 502)
    if not pagination.get('hasMore'):
        return None
    cursor = pagination.get('nextCursor')
    if (not isinstance(cursor, str) or not cursor or len(cursor) > 2048
            or cursor in visited):
        _fail('provider_metadata_incomplete', 502)
    visited.add(cursor)
    return cursor


async def _verified_attachment(client, item, receipt, authority):
    account, cid, target = item['account_id'], item['conversation_id'], item['recipient']
    payload = await _read_metadata(client, '/accounts', None, authority)
    accounts = payload.get('accounts')
    if not isinstance(accounts, list):
        _fail('provider_account_unavailable', 502)
    matches = [row for row in accounts if isinstance(row, dict) and row.get('_id') == account]
    if (len(matches) != 1 or matches[0].get('platform') != 'whatsapp'
            or matches[0].get('isActive') is not True):
        _fail('provider_account_mismatch')
    cursor, visited = None, set()
    for _ in range(_MAX_PAGES):
        params = {'accountId': account, 'platform': 'whatsapp', 'limit': 100}
        if cursor:
            params['cursor'] = cursor
        payload = await _read_metadata(client, '/inbox/conversations', params, authority)
        rows = payload.get('data')
        if not isinstance(rows, list) or len(rows) > 100:
            _fail('provider_metadata_invalid', 502)
        matches = [row for row in rows if isinstance(row, dict) and row.get('id') == cid]
        if matches:
            if (len(matches) != 1 or matches[0].get('accountId') != account
                    or matches[0].get('platform') != 'whatsapp' or matches[0].get('isGroup')
                    or z.phone(matches[0].get('participantId')) != target):
                _fail('conversation_binding_mismatch')
            break
        cursor = _next_cursor(payload, visited)
        if cursor is None:
            _fail('conversation_not_found', 404)
    else:
        _fail('provider_lookup_limit', 502)
    cursor, visited = None, set()
    for _ in range(_MAX_PAGES):
        params = {'accountId': account, 'sortOrder': 'desc', 'limit': 100}
        if cursor:
            params['cursor'] = cursor
        payload = await _read_metadata(client,
            '/inbox/conversations/' + quote(cid, safe='') + '/messages', params, authority)
        messages = payload.get('messages')
        if not isinstance(messages, list) or len(messages) > 100:
            _fail('provider_metadata_invalid', 502)
        matches = []
        for message in messages:
            if (not isinstance(message, dict)
                    or message.get('accountId', account) != account
                    or message.get('conversationId', cid) != cid
                    or message.get('platform', 'whatsapp') != 'whatsapp'):
                _fail('message_binding_mismatch')
            if message.get('id') == receipt:
                matches.append(message)
        if matches:
            if len(matches) != 1:
                _fail('ambiguous_receipt')
            message = matches[0]
            # The sender's account is established above; senderId itself has no
            # verified phone/account schema. Recipient is the private thread's
            # verified participant, never inferred from an outgoing senderId.
            if (message.get('direction') != 'outgoing' or message.get('isDeleted')
                    or message.get('deliveryStatus') == 'deleted'):
                _fail('outgoing_receipt_required')
            for key in ('recipientId', 'participantId'):
                if key in message and z.phone(message[key]) != target:
                    _fail('message_recipient_mismatch')
            attachments = message.get('attachments')
            if not isinstance(attachments, list) or len(attachments) != 1:
                _fail('single_document_attachment_required')
            attachment = attachments[0]
            if not inbox._pdf_metadata_allowed(inbox.pdf_attachment_metadata(attachment)):
                _fail('pdf_attachment_required')
            # A provider hash, when present, must corroborate the immutable local
            # hash. Otherwise receipt ownership is the file association; do not
            # claim the remote bytes were hashed or download the document.
            provider_hash = attachment.get('sha256')
            if provider_hash is not None and (not isinstance(provider_hash, str)
                    or not re.fullmatch(r'[0-9a-f]{64}', provider_hash)
                    or not hmac.compare_digest(provider_hash, item['sha256'])):
                _fail('attachment_hash_mismatch')
            return attachment, ('sha256_matched' if provider_hash else 'stored_receipt_only')
        cursor = _next_cursor(payload, visited)
        if cursor is None:
            _fail('receipt_not_found', 404)
    _fail('provider_lookup_limit', 502)


def _anonymous_client():
    # Fresh cookie jar, no Authorization/default auth/netrc/proxy environment,
    # no authenticated-client reuse, no redirects and no credential creation.
    return httpx.AsyncClient(auth=None, cookies={}, trust_env=False,
        follow_redirects=False, timeout=_PROBE_SECONDS,
        headers={'Accept-Encoding': 'identity'},
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=0))


async def _anonymous_probe(media_identity, account):
    if (not isinstance(media_identity, tuple) or len(media_identity) != 2
            or not isinstance(media_identity[0], str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,255}', media_identity[0])
            or type(media_identity[1]) is not bool
            or not isinstance(account, str) or not account):
        return 'not_eligible', 'inconclusive'
    media_id, with_account = media_identity
    try:
        async with asyncio.timeout(_PROBE_SECONDS):
            async with _anonymous_client() as client:
                async with client.stream('GET', _PROVIDER_BASE + '/whatsapp/media/' + media_id,
                        params={'accountId': account} if with_account else None,
                        follow_redirects=False, timeout=_PROBE_SECONDS) as response:
                    if response.status_code in (401, 403):
                        return 'denied', 'inconclusive'
                    if 300 <= response.status_code < 400:
                        return 'redirect', 'inconclusive'
                    if response.status_code == 404:
                        return 'not_found', 'inconclusive'
                    if not 200 <= response.status_code < 300:
                        return 'other_status', 'inconclusive'
                    if response.headers.get('content-encoding', '').strip().lower() not in ('', 'identity'):
                        return 'encoded_response', 'inconclusive'
                    prefix = b''
                    async for chunk in response.aiter_bytes(chunk_size=_PROBE_BYTES):
                        prefix += chunk[:_PROBE_BYTES - len(prefix)]
                        if len(prefix) >= _PROBE_BYTES:
                            break
                    if prefix.startswith(b'%PDF-'):
                        return 'pdf_prefix_observed', 'public_bytes_observed'
                    return 'http_success', 'inconclusive'
    except (httpx.TimeoutException, TimeoutError):
        return 'timeout', 'inconclusive'
    except httpx.HTTPError:
        return 'network_error', 'inconclusive'


def _snapshot(item):
    return tuple(item.get(key) for key in ('token', 'creator_id', 'account_id',
        'conversation_id', 'recipient', 'sha256', 'state', 'reason')) + (tuple(item['provider_ids']),)


@router.post('/whatsapp-inbox/documents/{token}/privacy-diagnostic')
async def outgoing_privacy_diagnostic(token: str, request: Request):
    actor, account = dict(inbox.send_authority(request)), z.account_id()
    if request.query_params:
        _fail('invalid_diagnostic_form', 400)
    values = await inbox.document_confirmation(request, actor)
    if set(values) - _FORM_KEYS or not (_FORM_KEYS - {'probe', 'fictional'}).issubset(values):
        _fail('invalid_diagnostic_form', 400)
    if values.get('probe', 'no') not in ('no', 'yes') or values.get('fictional', 'no') not in ('no', 'yes'):
        _fail('invalid_diagnostic_form', 400)
    probe = values.get('probe') == 'yes'
    if probe and values.get('fictional') != 'yes':
        _fail('fictional_nonsensitive_confirmation_required', 400)

    def authority():
        inbox.document_actor(request, actor, account, sending=True)

    def get_bound_item():
        authority()
        try:
            item = documents.get(token, actor['user_id'], db_factory=inbox.database,
                                 require_valid_binding=True)
        except documents.StoreError:
            _fail('document_binding_invalid')
        if item is None:
            _fail('document_not_found', 404)
        if item.get('state') not in _STATES:
            _fail('terminal_document_receipt_required')
        if (item.get('account_id') != account or values['account'] != account
                or values['conversation'] != item.get('conversation_id')
                or values['recipient'] != item.get('recipient')
                or not re.fullmatch(r'[0-9a-f]{64}', values['sha256'])
                or not hmac.compare_digest(values['sha256'], item.get('sha256', ''))):
            _fail('document_binding_mismatch')
        receipt = values['receipt']
        if (z._document_receipt_ids({'messageId': receipt}) is None
                or receipt not in item.get('provider_ids', [])):
            _fail('stored_receipt_required')
        return item

    item = get_bound_item()
    initial = _snapshot(item)
    try:
        with _quiet_http():
            async with asyncio.timeout(_TOTAL_SECONDS):
                async with z.client() as client:
                    attachment, file_binding = await _verified_attachment(
                        client, item, values['receipt'], authority)
                if _snapshot(get_bound_item()) != initial:
                    _fail('document_changed_during_diagnostic')
                origin = classify_origin(attachment.get('url'), account)
                result, assessment = 'not_requested', 'inconclusive'
                if probe:
                    identity = _canonical_media(attachment.get('url'), account)
                    if identity is None:
                        result = 'not_eligible'
                    else:
                        authority()
                        result, assessment = await _anonymous_probe(identity, account)
                if _snapshot(get_bound_item()) != initial:
                    _fail('document_changed_during_diagnostic')
    except (httpx.TimeoutException, TimeoutError):
        _fail('diagnostic_timeout', 504)
    except (z.WhatsAppBlocked, httpx.HTTPError):
        _fail('diagnostic_unavailable', 502)
    return JSONResponse({'scope': 'matched_document_receipt',
        'file_binding': file_binding, 'origin_category': origin,
        'anonymous_result': result, 'privacy_assessment': assessment},
        headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                 'X-Content-Type-Options': 'nosniff'})
