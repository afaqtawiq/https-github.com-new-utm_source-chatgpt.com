"""Owner-only extension of the existing morning briefing, not a second worker.

Activation pins the established owner destination by an externally configured
SHA256 of its normalized E.164 number. No phone number or pin is embedded in code.
The new section is sent only by WhatsApp. Existing email fallback receives only
the original briefing. A provider acceptance is never described as delivery.
"""
from datetime import timedelta
import hashlib
import hmac
import os

from starlette.concurrency import run_in_threadpool
from app.customer_followup import endpoint, digest, snapshot


def configuration():
    owner = endpoint('whatsapp', os.getenv('WHATSAPP_COMMAND_OWNER', ''))
    pin = os.getenv('CUSTOMER_FOLLOWUP_OWNER_SHA256', '').strip().lower()
    match = bool(owner and len(pin) == 64 and hmac.compare_digest(
        hashlib.sha256(owner.encode()).hexdigest(), pin))
    return {'enabled': os.getenv('CUSTOMER_FOLLOWUP_DIGEST_ENABLED', '0') == '1',
            'owner': owner, 'owner_matches_verified_recipient': match,
            'owner_suffix': owner[-3:] if owner else None,
            'account': os.getenv('ZERNIO_WHATSAPP_ACCOUNT_ID', '') or os.getenv('WHATSAPP_COMMAND_ACCOUNT_ID', '')}


def init():
    from app.storage import db
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS owner_followup_delivery(
            day DATE PRIMARY KEY, status TEXT NOT NULL,
            recipient_sha256 TEXT NOT NULL, provider_message_id TEXT,
            detail_code TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ NOT NULL)''')


def claim(day, recipient_hash):
    from app.storage import db, utcnow
    with db() as c:
        return bool(c.execute('''INSERT INTO owner_followup_delivery(day,status,recipient_sha256,updated_at)
            VALUES(%s,'prepared',%s,%s) ON CONFLICT DO NOTHING RETURNING day''',
            (day, recipient_hash, utcnow())).fetchone())


def record(day, status, message_id=None, detail=''):
    from app.storage import db, utcnow
    with db() as c:
        c.execute('''UPDATE owner_followup_delivery SET status=%s,provider_message_id=%s,
            detail_code=%s,updated_at=%s WHERE day=%s''', (status, message_id, detail, utcnow(), day))


def summary(today):
    # Preserve the established briefing's mailbox-owner selection. It already
    # uses this same system_user for its official-mailbox fallback.
    from app.prospect_autopilot import system_user
    from app.fine_permissions import has_permission
    uid = system_user()
    mail = bool(uid and has_permission({'user_id': uid, 'role': 'admin'}, 'manage_gmail'))
    conf = configuration()
    data = snapshot(uid, conf['account'], mail)
    activity = {'customer_campaign_recipients', 'outbound_messages', 'spacemail_inbox',
                'whatsapp_agent_jobs', 'whatsapp_takeover_receipts', 'whatsapp_inbox_drafts',
                'sales_followups', 'opportunities'}
    if not any(r['source'] in activity and r['status'] == 'read' for r in data['coverage']):
        raise RuntimeError('source_evidence_unavailable')
    result = digest(data, today - timedelta(days=1))
    return result['text'] + '\nمصادر غير مكتملة أو غير متاحة: ' + str(result['incomplete_sources'])


async def deliver_morning(base_text, today):
    """Called after the existing owner_briefings day claim. No new scheduler."""
    from app import owner_briefing as original
    from app import zernio_whatsapp as wa
    if not original.enabled():
        return 'disabled'
    conf = configuration()
    if not conf['enabled']:
        return await original.deliver(base_text)
    if not conf['owner_matches_verified_recipient'] or not conf['account']:
        # This does not change the original, separately configured briefing.
        return await original.deliver(base_text)
    recipient_hash = hashlib.sha256(conf['owner'].encode()).hexdigest()
    if not await run_in_threadpool(claim, today, recipient_hash):
        return 'followup_already_claimed'
    try:
        extra = await run_in_threadpool(summary, today)
        text = base_text + '\n\n📌 متابعة العملاء والفرص\n' + extra
        if len(text) > 4000:
            raise ValueError('briefing_too_long')
    except Exception:
        await run_in_threadpool(record, today, 'generation_failed', None, 'snapshot_unavailable')
        return await original.deliver(base_text) if original.enabled() else 'disabled'

    def guard():
        current = configuration()
        if (not original.enabled() or not current['enabled'] or not current['owner_matches_verified_recipient']
                or current['owner'] != conf['owner'] or current['account'] != conf['account']):
            raise wa.WhatsAppBlocked('Owner digest authorization changed')

    key = 'wa-agent-' + hashlib.sha256(('owner-followup:' + today.isoformat() + ':' + recipient_hash).encode()).hexdigest()
    try:
        with wa.dispatch_guard(guard):
            receipt = await wa.send(conf['owner'], text, expected_account=conf['account'], idempotency_key=key)
    except wa.WhatsAppBlocked:
        await run_in_threadpool(record, today, 'blocked', None, 'provider_or_window_blocked')
    except Exception:
        # Do not retry any uncertain WhatsApp outcome. Keep the day claimed.
        await run_in_threadpool(record, today, 'uncertain', None, 'send_outcome_uncertain')
    else:
        mid = (receipt.get('messages') or [{}])[0].get('id')
        if not isinstance(mid, str) or not mid.strip():
            await run_in_threadpool(record, today, 'uncertain', None, 'receipt_missing')
        else:
            await run_in_threadpool(record, today, 'accepted', mid, 'provider_acceptance_not_delivery')
        return 'whatsapp'
    # The user authorized this new section on WhatsApp only. Never send extra
    # to an email fallback and never make a second WhatsApp attempt.
    return await original.deliver_email(base_text) if original.enabled() else 'disabled'


def public_status():
    from app.storage import db
    conf = configuration()
    latest = None
    with db() as c:
        row = c.execute('''SELECT day,status,detail_code,updated_at FROM owner_followup_delivery
            ORDER BY day DESC LIMIT 1''').fetchone()
        if row:
            latest = dict(row)
    worker_enabled = os.getenv('AFAQ_OWNER_ALERTS', '1') == '1' and os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') == '1'
    configured = conf['owner_matches_verified_recipient'] and bool(conf['account'])
    return {'enabled': conf['enabled'], 'owner_suffix': conf['owner_suffix'],
            'owner_matches_verified_recipient': conf['owner_matches_verified_recipient'],
            'account_configured': bool(conf['account']),
            'configuration_state': 'disabled' if not conf['enabled'] or not worker_enabled else
                'configured' if configured else 'blocked',
            'timezone': 'Asia/Riyadh', 'hour': int(os.getenv('OWNER_BRIEFING_HOUR', '8')),
            'existing_owner_worker_enabled': worker_enabled,
            'latest_attempt': latest, 'channel': 'whatsapp', 'new_section_email_fallback': False,
            'delivery_constraint': 'An open WhatsApp service window or an approved exact matching template is required.'}
