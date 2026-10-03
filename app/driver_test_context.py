"""Deterministic, non-operational replies inside a disclosed driver TEST.

This never transcribes media, infers acceptance, creates intake requests, or
replays earlier messages. The signed receiver owns sender/account validation and
one-event/one-response claims. Original receipts without sender-account metadata
require a quote or explicit reference; they are never guessed for an unquoted
conversation. New original sends retain their account ID; retries already do.
"""
from datetime import datetime, timedelta, timezone
import json
import re

from app.transport_test import DISCLAIMER, accepts_test_offer

NOTICE = (DISCLAIMER + '؛ الأسعار والوزن وشروط الدفع بيانات محاكاة، '
          'ولا يوجد التزام نقل أو دفع. لم يُسجّل هذا الرد قبولًا لتنفيذ شحنة.')
AMBIGUOUS = ('لم أستطع تحديد العرض المقصود. عرض الاختبار لا يمثل حمولة فعلية أو طلب تحرك أو التزام دفع. '
             'رد مباشرة على الرسالة المقصودة؛ لم أسجل قبولًا.')


def _recent(value, now):
    try:
        at = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return at.tzinfo is not None and timedelta(0) <= now - at <= timedelta(hours=24)
    except (ValueError, TypeError):
        return False


def eligible(row, account):
    if (bool(row.get('is_test')) != bool(row.get('shipment_is_test'))
            or not row.get('provider_message_id') or not row.get('driver_id')
            or row.get('recipient_status') == 'excluded'):
        return False
    if row.get('attempt_id'):
        return (row.get('sender_account_id') == account
                and row.get('attempt_status') in ('accepted','test_accepted')
                and row.get('delivery_status') not in ('failed','deleted'))
    return (row.get('recipient_status') in ('sent','test_accepted','closed')
            and (not row.get('sender_account_id') or row['sender_account_id'] == account))


def select_context(candidates, text, quote_id, account, *, owner_pending=False,
                   explicit_new_request=False, now=None):
    """Return a TEST, a clarification, or None for the existing real/owner flow."""
    now = now or datetime.now(timezone.utc)
    candidates = [r for r in candidates if eligible(r, account)]
    tests = [r for r in candidates if r['is_test']]
    if not tests:
        return None
    refs = set(re.findall(r'(?<!\w)(?:NQ-\d+|WA-[A-F0-9]{12})(?!\w)', str(text).upper()))
    quote_matches = [r for r in candidates if quote_id is not None and r['provider_message_id'] == quote_id]
    ref_matches = [r for r in candidates if r['reference'].upper() in refs]
    test_ref = any(r['is_test'] for r in ref_matches)
    test_quote = any(r['is_test'] for r in quote_matches)
    # A clearly new request or a specifically identified real offer keeps its
    # existing flow unless another identifier explicitly points to a TEST.
    if explicit_new_request and not test_ref and not test_quote:
        return None
    if refs and len(refs) == 1 and ref_matches and all(not r['is_test'] for r in ref_matches) and not test_quote:
        return None
    if quote_matches and all(not r['is_test'] for r in quote_matches) and not test_ref:
        return None
    if quote_id is not None or refs:
        selected = candidates
        if refs:
            if len(refs) != 1: return {'kind':'ambiguous'}
            selected = [r for r in selected if r['reference'].upper() in refs]
        if quote_id is not None:
            if not quote_id: return {'kind':'ambiguous'}
            selected = [r for r in selected if r['provider_message_id'] == quote_id]
        if len(selected) == 1 and selected[0]['is_test']:
            return {'kind':'test','context':selected[0]}
        return {'kind':'ambiguous'}
    recent = [r for r in candidates if _recent(r.get('sent_at'),now)]
    active_tests = [r for r in recent if r['is_test']]
    if not active_tests:
        return None
    # A person can be both owner and driver. An unquoted ambiguous reply must
    # not advance a real negotiation just because its TEST could not be chosen.
    if owner_pending:
        return {'kind':'ambiguous'} if any(r.get('sender_account_id') == account for r in active_tests) else None
    real_conflict = any(not r['is_test'] and (r in recent or r.get('broadcast_status') in
        ('sending','completed','completed_with_errors','awaiting_driver')) for r in candidates)
    if real_conflict:
        return {'kind':'ambiguous'}
    if len(recent) == 1 and active_tests[0].get('sender_account_id') == account:
        return {'kind':'test','context':active_tests[0]}
    if len(recent) > 1:
        return {'kind':'ambiguous'}
    return None


def reply_for_driver_test(c, phone, text, quote_id, account, event_id, message,
                          *, explicit_new_request=False):
    candidates = c.execute("""SELECT b.id broadcast_id,b.shipment_id,b.status broadcast_status,
        b.is_test,s.is_test shipment_is_test,s.reference,r.id recipient_id,r.driver_id,r.status recipient_status,
        a.id attempt_id,a.status attempt_status,
        CASE WHEN a.id IS NOT NULL THEN a.provider_message_id ELSE r.provider_message_id END provider_message_id,
        CASE WHEN a.id IS NOT NULL THEN a.sent_at ELSE r.sent_at END sent_at,
        CASE WHEN a.id IS NOT NULL THEN rb.account_id ELSE r.provider_account_id END sender_account_id,
        (SELECT dr.delivery_status FROM driver_recovery_receipts dr
            WHERE dr.attempt_id=a.id AND dr.provider_message_id=a.provider_message_id
            ORDER BY dr.checked_at DESC,dr.id DESC LIMIT 1) delivery_status
        FROM driver_broadcasts b JOIN shipments s ON s.id=b.shipment_id
        JOIN driver_broadcast_recipients r ON r.broadcast_id=b.id
        LEFT JOIN driver_recovery_batches rb ON rb.broadcast_id=b.id
        LEFT JOIN driver_recovery_attempts a ON a.batch_id=rb.id AND a.recipient_id=r.id
        WHERE r.phone=%s AND b.status IN ('sending','completed','completed_with_errors','awaiting_driver','driver_accepted','test_completed')
        ORDER BY b.id,r.id""", (phone,)).fetchall()
    pending_owners = c.execute("""SELECT n.shipment_id,n.provider_message_id,s.reference
        FROM freight_negotiations n JOIN shipments s ON s.id=n.shipment_id
        WHERE n.owner_phone=%s AND n.contact_channel='whatsapp' AND n.status='awaiting_owner'
          AND n.record_kind='shipment_request'""", (phone,)).fetchall()
    refs = set(re.findall(r'(?<!\w)(?:NQ-\d+|WA-[A-F0-9]{12})(?!\w)', str(text).upper()))
    test_identity = any(r['is_test'] and eligible(r,account) and
        (r['reference'].upper() in refs or (quote_id and r['provider_message_id'] == quote_id)) for r in candidates)
    owner_identity = any(r['reference'].upper() in refs or
        (quote_id and r.get('provider_message_id') == quote_id) for r in pending_owners)
    if owner_identity and not test_identity:
        return None
    selected = select_context(candidates,text,quote_id,account,owner_pending=bool(pending_owners),
                              explicit_new_request=explicit_new_request)
    if selected is None:
        return None
    if selected['kind'] == 'ambiguous':
        return {'message':AMBIGUOUS}
    item = selected['context']
    # The text predicate and the locked first-wins/receipt checks are unchanged.
    # A quoted TEST is context, never permission to manufacture an acceptance.
    if accepts_test_offer(text):
        from app.freight_workflow import accept_driver_reply
        if accept_driver_reply(phone,text,connection=c,event_id=event_id,inbound_message_id=message.get('id')):
            return {'message':DISCLAIMER + '؛ تم تسجيل نجاح رد الاختبار فقط، ولم يتم تعيينك لتنفيذ شحنة.'}
    kinds = sorted({str(a.get('type') or 'attachment')[:40] for a in (message.get('attachments') or []) if isinstance(a,dict)})
    summary = json.dumps({'event_id':event_id,'broadcast_id':item['broadcast_id'],
        'recipient_id':item['recipient_id'],'text':str(text)[:2000],
        'attachment_types':kinds,'accepted':False},ensure_ascii=False)
    c.execute("""INSERT INTO shipment_events(shipment_id,event_type,summary,stage,happened_at)
        VALUES(%s,'driver_test_reply',%s,'test_reply_review',NOW())""",(item['shipment_id'],summary))
    return {'message':NOTICE}
