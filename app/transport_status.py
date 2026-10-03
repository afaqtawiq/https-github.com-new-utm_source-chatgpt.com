"""Read-only transport evidence. Sending, delivery and driver consent are distinct.

Original broadcast facts remain immutable when a linked recovery is present.
Provider observations are selected by observation time, never insertion order.
"""
from collections import Counter


def snapshot(connection, broadcast):
    if not broadcast:
        return None
    batch = connection.execute('SELECT * FROM driver_recovery_batches WHERE broadcast_id=%s',
                               (broadcast['id'],)).fetchone()
    result = {
        'broadcast_id': broadcast['id'], 'is_test': bool(broadcast.get('is_test')),
        'effective_status': broadcast['status'],
        'original': {key: broadcast.get(key) for key in
                     ('status', 'sent_count', 'failed_count', 'confirmed_at', 'completed_at')},
        'driver_acceptance': {key: broadcast.get(key) for key in ('accepted_driver_id', 'accepted_at')},
        'recovery': None,
    }
    if not batch:
        return result
    attempts = connection.execute('''SELECT a.*,
        (SELECT r.delivery_status FROM driver_recovery_receipts r
         WHERE r.attempt_id=a.id AND r.provider_message_id=a.provider_message_id
         ORDER BY r.checked_at DESC,r.id DESC LIMIT 1) delivery_status,
        (SELECT r.checked_at FROM driver_recovery_receipts r
         WHERE r.attempt_id=a.id AND r.provider_message_id=a.provider_message_id
         ORDER BY r.checked_at DESC,r.id DESC LIMIT 1) checked_at
        FROM driver_recovery_attempts a WHERE a.batch_id=%s ORDER BY a.id''', (batch['id'],)).fetchall()
    observations = [a['checked_at'] for a in attempts if a.get('checked_at')]
    result['recovery'] = {
        'batch_id': batch['id'], 'status': batch['status'], 'account_id': batch['account_id'],
        'approved_at': batch.get('approved_at'), 'completed_at': batch.get('completed_at'),
        'attempt_count': len(attempts), 'attempt_statuses': dict(Counter(a['status'] for a in attempts)),
        'provider_accepted': sum(bool(a.get('provider_message_id')) for a in attempts),
        'reply_eligible': sum(a['status']=='accepted' and bool(a.get('provider_message_id'))
                              and a.get('delivery_status') not in ('failed','deleted') for a in attempts),
        'delivery_statuses': dict(Counter(a.get('delivery_status') or 'not_checked' for a in attempts)),
        'observed_from': min(observations) if observations else None,
        'observed_to': max(observations) if observations else None,
    }
    # A retry finishing is not driver consent. Never rewrite the stored original
    # state merely to show progress; a genuine accepted reply remains first-wins.
    if not broadcast.get('accepted_driver_id') and broadcast.get('is_test'):
        if batch['status'] == 'completed':
            result['effective_status'] = ('awaiting_test_driver_reply' if result['recovery']['reply_eligible']
                                          else 'recovery_needs_review')
        elif batch['status'] in ('prepared', 'sending', 'stopped'):
            result['effective_status'] = 'recovery_' + batch['status']
    return result


def evidence_lines(evidence):
    if not evidence:
        return []
    original = evidence['original']
    lines = [f"السجل الأصلي #{evidence['broadcast_id']}: {original['status']}؛ قبل المزود {original['sent_count'] or 0}؛ فشل/غير مؤكد {original['failed_count'] or 0}"]
    if original.get('completed_at'):
        lines.append('انتهت المحاولة الأصلية: ' + str(original['completed_at']))
    recovery = evidence['recovery']
    if recovery:
        counts = '، '.join(f'{key}: {value}' for key, value in sorted(recovery['attempt_statuses'].items()))
        lines.append(f"الاستعادة المرتبطة #{recovery['batch_id']}: {recovery['status']}؛ نتائج المحاولات: {counts}")
        if recovery.get('completed_at'):
            lines.append('وقت انتهاء الاستعادة: ' + str(recovery['completed_at']))
        delivery = '، '.join(f'{key}: {value}' for key, value in sorted(recovery['delivery_statuses'].items()))
        lines.append('إيصالات المزود المحفوظة للاستعادة: ' + delivery)
        if recovery['observed_to']:
            lines.append(f"أوقات فحص الإيصالات المحفوظة: {recovery['observed_from']} إلى {recovery['observed_to']}؛ ليست قراءة مباشرة الآن")
        else:
            lines.append('لم يُحفظ فحص تسليم للاستعادة؛ قبول المزود لا يثبت التسليم أو القراءة')
    accepted = evidence['driver_acceptance']
    if accepted.get('accepted_driver_id'):
        kind = 'قبول رد اختبار فقط، دون تعيين أو تحريك شحنة' if evidence['is_test'] else 'قبول السائق المسجل'
        lines.append(f"{kind}: {accepted['accepted_driver_id']}؛ الوقت: {accepted.get('accepted_at') or 'غير مسجل'}")
    else:
        lines.append('لم يُسجل قبول سائق مرتبط بهذا العرض بعد')
    return lines


def current_status(shipment_status, negotiation_status, evidence):
    """Actual shipment progress takes precedence over an older negotiation/offer."""
    if shipment_status and shipment_status not in {'new', 'carrier_offer', 'test_pending'}:
        return shipment_status
    return evidence['effective_status'] if evidence else negotiation_status
