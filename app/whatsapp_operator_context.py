"""Read bounded text context from a verified thread; never read attachments.

Provider messages are untrusted conversation data. They cannot authorize a send,
change identity, approve a document or establish an operational fact. This module
never persists message bodies and never reads receipts or sends messages.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from app import zernio_whatsapp as z, whatsapp_inbox as inbox
from app import whatsapp_agent_privacy as privacy


def _time(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    return privacy._history_time(value)


async def read_context(job):
    """Return only screened outgoing text and an exact provider-resolved quote.

    Missing or ambiguous quoted IDs are never resolved using webhook quote text
    or by guessing the latest message. A bounded first page is deliberately not
    treated as a complete transcript.
    """
    account, cid, sender = (job.get(k) for k in ('account_id', 'conversation_id', 'sender'))
    before = _time(job.get('created_at'))
    if (account != z.account_id() or not all(isinstance(v, str) and 0 < len(v) <= 255
            for v in (account, cid, sender)) or before is None
            or before > datetime.now(timezone.utc)):
        return ()
    quoted_id = (job.get('payload') or {}).get('quoted_platform_message_id')
    if not isinstance(quoted_id, str) or not 0 < len(quoted_id) <= 255:
        quoted_id = None
    try:
        async with z.client() as client:
            await z.validate_account(client)
            conversation = await inbox.verified_conversation(client, cid)
            if (conversation.get('accountId') != account or conversation.get('id') != cid
                    or conversation.get('platform') != 'whatsapp' or conversation.get('isGroup')
                    or z.phone(conversation.get('participantId')) != sender):
                return ()
            payload = await z.read(client, '/inbox/conversations/' + quote(cid, safe='') + '/messages',
                {'accountId': account, 'sortOrder': 'desc', 'limit': 50})
        if account != z.account_id():
            return ()
        messages = payload.get('messages')
        if not isinstance(messages, list) or len(messages) > 50:
            return ()
        if any(not isinstance(m, dict) or m.get('accountId', account) != account
               or m.get('conversationId', cid) != cid for m in messages):
            return ()
        ids = [m.get('platformMessageId') for m in messages]
        selected = []
        seen = set()
        for message in messages:
            mid = message.get('id')
            if not isinstance(mid, str) or not mid or mid in seen:
                continue
            seen.add(mid)
            timestamp = _time(message.get('createdAt'))
            if timestamp is None or not before - timedelta(hours=24) < timestamp < before:
                continue
            quoted = bool(quoted_id and message.get('platformMessageId') == quoted_id and ids.count(quoted_id) == 1)
            direction = message.get('direction')
            if direction not in ('outgoing', 'outbound', 'incoming') or (direction == 'incoming' and not quoted):
                continue
            if message.get('attachments') or message.get('deliveryStatus') in ('failed', 'deleted'):
                continue
            decision = privacy.screen_question(message.get('message'))
            if not decision.allowed or len(decision.safe_text) > 1500:
                continue
            selected.append((timestamp, {'direction': 'incoming' if direction == 'incoming' else 'outgoing',
                                        'text': decision.safe_text, 'quoted': quoted}))
        selected.sort(key=lambda row: row[0], reverse=True)
        # Keep a resolved quote even if newer outgoing messages fill the budget.
        chosen = [row for row in selected if row[1]['quoted']][:1]
        chosen += [row for row in selected if not row[1]['quoted']][:4 - len(chosen)]
        chosen.sort(key=lambda row: row[0])
        result, count = [], 0
        for _, row in chosen:
            if count + len(row['text']) <= 3000:
                result.append(row)
                count += len(row['text'])
        return tuple(result)
    except (z.WhatsAppBlocked, httpx.HTTPError, HTTPException, ValueError, TypeError):
        return ()
