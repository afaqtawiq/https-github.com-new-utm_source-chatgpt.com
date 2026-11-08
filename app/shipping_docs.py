"""Shipping-line documents → container follow-up (owner request, Nov 2026).

When staff send an arrival notice, delivery order or bill of lading (photo or PDF) on WhatsApp, every container on it is
registered in the container-return follow-up with the bill, consignee, return depot and the last free day (as written,
or estimated from arrival date + free days and clearly marked as an estimate). The daily due-date alerts already in place
then take over. Internal records only; nothing is sent to anyone.
"""
import datetime as dt
import re

FIELDS_HINT = """
For shipping_document (arrival notice / delivery order / bill of lading / إشعار وصول / إذن تسليم) also return:
shipping_line, vessel, bill_no, consignee, eta (YYYY-MM-DD arrival/discharge date), free_days (integer free time days for
container detention/demurrage), free_until (YYYY-MM-DD last free day if written), return_place (empty container return
depot/yard if written), daily_cost (detention/demurrage per day per container in SAR if written). null when absent."""


def _date(value):
    from app.container_returns import date
    return date(value) if value else None


def register(fields, caption=''):
    """Register/refresh the containers of one shipping document. Returns the Arabic reply."""
    from app import container_returns
    numbers = []
    for raw in list(fields.get('container_numbers') or []) + re.findall(r'[A-Za-z]{4}\s?\d{7}', caption or ''):
        n = container_returns.number(str(raw))
        if n and n not in numbers:
            numbers.append(n)
    if not numbers:
        return None
    numbers = numbers[:40]
    free_until, estimated = _date(fields.get('free_until')), False
    eta = _date(fields.get('eta'))
    try:
        free_days = int(re.sub(r'\D', '', str(fields.get('free_days') or '')) or 0)
    except ValueError:
        free_days = 0
    if not free_until and eta and 0 < free_days <= 60:
        free_until, estimated = eta + dt.timedelta(days=free_days - 1), True
    args = {'customer': fields.get('consignee') or None, 'bill': fields.get('bill_no') or None,
            'return_place': fields.get('return_place') or None, 'daily_cost': fields.get('daily_cost') or None,
            'free_until': free_until.isoformat() if free_until else None}
    for n in numbers:
        container_returns.track(dict(args, container=n), 'مستند ملاحي')
    head = ' — '.join(x for x in (str(fields.get('shipping_line') or '').strip(), str(fields.get('vessel') or '').strip()) if x)
    lines = [f'🚢 سجلت {len(numbers)} حاوية من المستند الملاحي' + (f' ({head})' if head else '') + ' في متابعة الإرجاع:',
             '، '.join(numbers)]
    for label, key in (('البوليصة', 'bill_no'), ('المستلم', 'consignee'), ('مكان الإرجاع', 'return_place')):
        if fields.get(key):
            lines.append(f'• {label}: {fields[key]}')
    if eta:
        lines.append(f'• الوصول: {eta.isoformat()}')
    if free_until:
        lines.append(f'• آخر يوم مجاني: {free_until.isoformat()}' + (f' (تقديري: الوصول + {free_days} يوم — تأكد من الخط)' if estimated else ''))
    else:
        lines.append('• آخر يوم مجاني غير مكتوب؛ أرسله: «الحاوية <رقم> آخر يوم مجاني 15/11» عشان تشتغل التنبيهات.')
    lines.append('أنبهك قبل نهاية المدة المجانية بيومين، وما أقفل أي حاوية إلا بسند إرجاع.')
    return '\n'.join(lines)
