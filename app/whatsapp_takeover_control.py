"""Existing admin/MFA authority controls scoped handoff; no global configuration changes."""
from contextlib import asynccontextmanager
from html import escape
import hashlib
from urllib.parse import urlencode

import anyio
import httpx
from psycopg.errors import LockNotAvailable
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from app import whatsapp_takeover as store, whatsapp_inbox as inbox, zernio_whatsapp as z

router = APIRouter()
_release_limiter = anyio.CapacityLimiter(4)


async def snapshot(account, sender):
    try:
        return await run_in_threadpool(store.read_recipient_state, account, sender) or {'generation': 0}
    except store.StateConflict:
        raise z.WhatsAppBlocked('تعذر تحديد محادثة وحيدة؛ لم يُرسل الرد الآلي') from None


@asynccontextmanager
async def guard(account, cid, sender, state):
    # This control manages only the existing configured Afaq account. Other
    # legacy accounts retain their own routing/authorization behavior.
    if account != z.account_id():
        if state is not None:
            raise z.WhatsAppBlocked('Configured account changed after intake')
        yield
        return
    if not isinstance(state, dict):
        raise z.WhatsAppBlocked('Missing automatic send scope')
    known = state.get('conversation_id')
    if known and cid and str(cid) != known:
        raise z.WhatsAppBlocked('Automatic conversation scope changed')
    target = str(cid) if cid else known
    if not target:
        # No known paused conversation and no freeform thread. Serialize template
        # dispatch on recipient too, because pause can discover a thread meanwhile.
        target = 'recipient:' + sender
    manager = store.send_guard(account, target, state['generation'], sender=sender or None)
    entered = False
    try:
        # Cancellation must not abandon a lock acquired in a worker thread.
        with anyio.CancelScope(shield=True):
            allowed = await run_in_threadpool(manager.__enter__)
            entered = True
        if not allowed:
            raise z.WhatsAppBlocked('الرد الآلي موقوف لهذه المحادثة أو تغير نطاقه')
        yield
    finally:
        if entered:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(manager.__exit__, None, None, None, limiter=_release_limiter)


async def inbound(payload):
    from app.whatsapp_agent import identity
    who = identity(payload)
    message = payload.get('message') or {}
    event_id = payload.get('id')
    if (not who and isinstance(message, dict) and not message.get('platformMessageId')
            and not message.get('id') and isinstance(event_id, str) and 0 < len(event_id) <= 255):
        # Older signed legacy events have an event ID but no platform message ID.
        # Retain/deduplicate them under an explicit event-derived receipt identity,
        # while preserving every account/participant/direction check.
        receipt_id = 'legacy-event:' + hashlib.sha256(event_id.encode()).hexdigest()
        who = identity({**payload, 'message': {**message, 'id': receipt_id}})
    if not who:
        account = payload.get('account') or {}
        cid = (payload.get('conversation') or {}).get('id')
        aid = account.get('accountId') or account.get('id')
        if aid != z.account_id() or not isinstance(cid, str):
            return None
        state = await run_in_threadpool(store.read_state, aid, cid)
        return {**state, 'sender': state.get('sender', ''), 'held': bool(state['paused'])}
    message = payload['message']
    state = await run_in_threadpool(store.capture_inbound, **who, return_state=True,
        text=str(message.get('text') or ''),
        attachment_count=len(message.get('attachments') or []) if isinstance(message.get('attachments') or [], list) else 0)
    return {**state, 'sender': who['sender']}


async def render(account, cid, sender, csrf):
    state = await run_in_threadpool(store.read_state, account, cid)
    label = 'موقوف — يتولى الموظف المحادثة' if state['paused'] else 'متاح بحسب إعداد المساعد'
    action = 'resume' if state['paused'] else 'pause'
    button = 'استئناف الردود الآلية الجديدة' if state['paused'] else 'إيقاف الرد الآلي لهذه المحادثة'
    hidden = {'csrf': csrf, 'account': account, 'conversation': cid, 'sender': sender,
              'generation': str(state['generation']), 'action': action}
    return '<section><h3>الرد الآلي: ' + label + '</h3><p>الاستقبال والإرسال اليدوي مستمران. الاستئناف صريح ولا يعيد الردود القديمة. قد تكون رسالة بدأت لدى المزود قبل الإيقاف؛ لا يمكن سحبها هنا.</p><form method="post" action="/whatsapp-inbox/takeover">' + ''.join(
        '<input type="hidden" name="' + key + '" value="' + escape(value, quote=True) + '">' for key, value in hidden.items()) + '<button>' + button + '</button></form></section>'


@router.post('/whatsapp-inbox/takeover')
async def change(request: Request):
    current = dict(inbox.send_authority(request))
    values = await inbox.form(request, current)
    account = inbox.field(values.get('account'))
    cid = inbox.field(values.get('conversation'))
    sender = inbox.field(values.get('sender'))
    if account != z.account_id() or values.get('action') not in ('pause', 'resume'):
        raise HTTPException(409, 'Invalid account or action')
    try:
        generation = int(values.get('generation', ''))
        if generation < 0: raise ValueError()
    except ValueError:
        raise HTTPException(400, 'Invalid generation') from None
    try:
        async with z.client() as client:
            await z.validate_account(client)
            row = await inbox.verified_conversation(client, cid)
        if z.phone(row.get('participantId')) != sender:
            raise HTTPException(409, 'Conversation participant changed')
        # Revalidate authority after the provider read; no new role or access path.
        latest = inbox.send_authority(request)
        if latest['user_id'] != current['user_id'] or account != z.account_id():
            raise HTTPException(409, 'Authority changed')
        await run_in_threadpool(store.set_paused, account, cid, values['action'] == 'pause',
                               current['user_id'], generation, sender=sender)
    except store.StateConflict:
        raise HTTPException(409, 'Conversation changed; refresh before acting') from None
    except (z.WhatsAppBlocked, httpx.HTTPError, LockNotAvailable):
        raise HTTPException(503, 'Conversation could not be verified') from None
    return RedirectResponse('/whatsapp-inbox?' + urlencode({'conversation': cid}), 303)


def register(app):
    from app import whatsapp_agent_store, zernio_receiver
    store.init_storage()
    whatsapp_agent_store.conversation_admission = store.admission
    whatsapp_agent_store.conversation_inspection = store._state
    z.automation_snapshot = snapshot
    z.automation_guard = guard
    zernio_receiver.takeover_inbound = inbound
    inbox.takeover_render = render
    app.include_router(router)
