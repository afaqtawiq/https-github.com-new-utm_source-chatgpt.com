"""Pure driver-recipient validation and faithful freight offer previews."""
import hashlib
import json
import re

from fastapi import HTTPException
from app.logistics_parsing import phone as normalize_phone
from app.transport_test import display_reference


def phone_error(value):
    number = str(value or '')
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', number):
        return 'invalid_e164: الرقم ليس بصيغة دولية صالحة'
    if number.startswith('+966'):
        national = number[4:]
        if national.startswith('0'):
            return 'invalid_saudi_trunk_prefix: لا يجوز وضع صفر محلي بعد +966'
        if len(national) != 9:
            return 'invalid_saudi_nsn_length: الرقم السعودي يحتاج 9 أرقام بعد +966'
    return ''


def driver_phone(value):
    number = normalize_phone(value)
    return number if number and not phone_error(number) else ''


def offer_message(item):
    reference = display_reference(item['reference'], item.get('is_test'))
    qualifier = {'inside': ' (التحميل داخل الميناء)', 'outside': ' (التحميل خارج الميناء)'}.get(item.get('loading_port_status'), '')
    origin = item['origin'] + qualifier
    price = round(float(item['agreed_owner_price']) - 150, 2)
    return (f'عرض حمولة من آفاق طويق — {reference}\n'
            f"المسار: {origin} → {item['destination']}\n"
            f"الوزن: {item['weight_tons']} طن\n"
            f'سعر السائق: {price:,.2f} ريال\n'
            f"التنزيل: {item.get('unloading_location') or item['destination']}\n"
            f"الدفع: {item['payment_method']}\n"
            f'للرغبة اكتب: موافق {reference}\nشكرًا لتعاونك.')


def require_unattempted(campaign, recipients):
    if (campaign.get('status') != 'draft' or campaign.get('confirmed_at') or campaign.get('confirmed_by')
            or campaign.get('accepted_at') or campaign.get('accepted_driver_id')
            or campaign.get('completed_at') or campaign.get('sent_count') or campaign.get('failed_count')
            or any(r['status'] not in ('pending', 'excluded') or r.get('provider_message_id')
                   or r.get('sent_at') or r.get('replied_at') for r in recipients)):
        raise HTTPException(409, 'بدأت محاولة إرسال هذه الحملة؛ لا يمكن تحديث مستلميها أو نصها')


def preview_plan(campaign, recipients, message):
    require_unattempted(campaign, recipients)
    active, excluded, seen = [], [], set()
    for row in recipients:
        reason = row.get('last_error') if row['status'] == 'excluded' else phone_error(row['phone'])
        if row['status'] == 'excluded':
            reason = reason or 'excluded: مستبعد سابقًا'
        if not reason and row['phone'] in seen:
            reason = 'duplicate_recipient: الرقم مكرر في هذه الحملة'
        if reason:
            excluded.append({**row, 'reason': reason})
        else:
            seen.add(row['phone'])
            active.append(row)
    payload = [campaign['id'], campaign['message'], message,
               [(r['id'], r['driver_id'], r['phone'], r['status'], r.get('last_error')) for r in recipients]]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
    return {'message': message, 'active': active, 'excluded': excluded, 'digest': digest,
            'changed': message != campaign['message'] or any(r['status'] != 'excluded' for r in excluded)
                       or campaign['recipient_count'] != len(active)}


def require_valid_audience(campaign, recipients):
    active = [r for r in recipients if r['status'] != 'excluded']
    if (not active or len(active) != campaign['recipient_count']
            or len({r['phone'] for r in active}) != len(active)
            or any(phone_error(r['phone']) for r in active)):
        raise HTTPException(409, 'راجع الأرقام واستبعد غير الصالح من معاينة المسودة قبل الإرسال')
