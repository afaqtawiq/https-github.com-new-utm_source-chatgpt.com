"""Pure, conservative brochure eligibility, independent of application startup."""
from datetime import timedelta, timezone
from app.marketing_content import email_address, whatsapp_number

FOLLOWUP_DELAY = timedelta(days=7)
RESERVED = {'pending', 'blocked'}
UNRESOLVED = {'sending', 'uncertain'}
STOPPED = {'bounced', 'rejected', 'replied'}


def identity(channel, recipient):
    return email_address(recipient) if channel == 'email' else whatsapp_number(recipient) if channel == 'whatsapp' else ''


def decision(history, now, *, current_id=None):
    """Return (stage, reason). Unknown outcome never creates a follow-up slot.

    Pending rows reserve their identity. During delivery only an older reservation
    takes priority, so legacy duplicate queues converge without starving each other.
    A stage is not a delivery claim: the DB caller must serialize this check/claim.
    """
    if any(r['id'] == current_id and (r.get('sent_at') or r.get('provider_message_id')) for r in history):
        return None, 'current_attempt_already_accepted'
    history = [r for r in history if r['id'] != current_id]
    known = RESERVED | UNRESOLVED | STOPPED | {'sent', 'cancelled', 'suppressed', 'excluded_prospect', 'cadence_skipped'}
    if any(r['status'] not in known for r in history):
        return None, 'unknown_previous_outcome'
    if any(r['status'] in UNRESOLVED for r in history):
        return None, 'unresolved_previous_attempt'
    if any(r['status'] in STOPPED for r in history):
        return None, 'previous_failure_or_reply'
    sent = [r for r in history if r['status'] == 'sent' or r.get('provider_message_id') or r.get('sent_at')]
    if len(sent) >= 2:
        return None, 'sequence_complete'
    if any(r['status'] in RESERVED and (current_id is None or r['id'] < current_id) for r in history):
        return None, 'already_queued'
    if not sent:
        return 'initial', None
    first = sent[0].get('sent_at')
    if first is None:
        return None, 'missing_accepted_timestamp'
    if first.tzinfo is None or now.tzinfo is None:
        return None, 'missing_timestamp_timezone'
    if now.astimezone(timezone.utc) < first.astimezone(timezone.utc) + FOLLOWUP_DELAY:
        return None, 'followup_not_due'
    return 'followup', None
