"""Disclosed transport test boundaries. No network calls or import-time writes."""
import hashlib
import json
import re

from fastapi import HTTPException

DISCLAIMER = 'اختبار للنظام فقط، لا توجد حمولة فعلية ولا حاجة للتحرك'


def display_reference(reference, is_test=False):
    return DISCLAIMER + ' — ' + reference if is_test else reference


def accepts_test_offer(text):
    """Accept only the exact disclosed instruction, never vague agreement."""
    return bool(re.fullmatch(r'موافق\s+' + re.escape(DISCLAIMER) +
                            r' — (?:NQ-\d+|WA-[A-F0-9]{12})[.!،\s]*', str(text or '').strip(), re.I))


def preview_digest(message, recipients):
    # Bind approval to the exact message and actual audience, not a posted count.
    audience = sorted((str(r['driver_id']), r['phone']) for r in recipients)
    return hashlib.sha256(json.dumps([message, audience], ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def test_broadcast_context(campaign, *, approved=False):
    from app.storage import one, rows
    shipment = one('SELECT reference,is_test FROM shipments WHERE id=?',
                   (campaign.get('shipment_id'),)) if campaign.get('shipment_id') else None
    is_test = bool((shipment or {}).get('is_test'))
    if bool(campaign.get('is_test')) != is_test:
        raise HTTPException(409, 'علامة الاختبار لا تطابق الشحنة؛ لم تُرسل الرسالة')
    if not is_test:
        return None
    reference = display_reference(shipment['reference'], True)
    message = campaign['message']
    if (not message.startswith('عرض حمولة من آفاق طويق — ' + reference + '\n')
            or not message.endswith('للرغبة اكتب: موافق ' + reference + '\nشكرًا لتعاونك.')
            or message.count(DISCLAIMER) != 2):
        raise HTTPException(409, 'إفصاح الاختبار إلزامي في العرض وتعليمات الرد؛ لم تُرسل الرسالة')
    recipients = rows('SELECT driver_id,phone FROM driver_broadcast_recipients WHERE broadcast_id=? ORDER BY id', (campaign['id'],))
    digest = preview_digest(message, recipients)
    if approved and (not campaign.get('test_approved_at') or not campaign.get('test_approved_by')
                     or campaign.get('test_preview_digest') != digest):
        raise HTTPException(409, 'يلزم اعتماد صريح لمعاينة الاختبار الحالية ومستلميها؛ لم تُرسل الرسالة')
    return {'digest': digest, 'disclaimer': DISCLAIMER}


def owner_inquiry(item):
    if not item.get('is_test'):
        raise HTTPException(409, 'هذا الإجراء مخصص لسجل اختبار معلن فقط')
    return (DISCLAIMER + '\n'
            + 'مرجع التجربة: ' + item['reference'] + '\n'
            + 'المسار الافتراضي: ' + item['origin'] + ' → ' + item['destination'] + '\n'
            + 'هل الحمولة الافتراضية متاحة للمحاكاة؟ أرسل مرجع التجربة مع بيانات محاكاة فقط:\n'
            + 'السعر النهائي: رقم أكبر من 150 ريال\nالوزن: رقم بالطن\nالتنزيل: موقع تجريبي\nطريقة الدفع: محاكاة دون دفع\n'
            + 'لن يترتب على الرد اتفاق نقل أو دفع، ولن يرسل عرض السائقين قبل مراجعته واعتماد الاختبار.')


def owner_inquiry_digest(item):
    return hashlib.sha256(json.dumps([item['owner_phone'], owner_inquiry(item)],
                                     ensure_ascii=False).encode()).hexdigest()
