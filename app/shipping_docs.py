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
depot/yard if written), daily_cost (detention/demurrage per day per container in SAR if written), container_size (20, 40 or
45 when all containers on the document have the same size). null when absent."""


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
    from app import line_desk
    from app.storage import db
    line_desk.init()
    size = line_desk.size_of(fields.get('container_size'))
    with db() as c:
        existing = {r['container'] for r in c.execute('SELECT container FROM container_returns WHERE container = ANY(%s)', (numbers,)).fetchall()}
        agent = line_desk.agent_from_document(c, fields.get('shipping_line'), fields.get('bill_no'))
        agent_days = line_desk.free_days_for(c, agent['id']) if agent else None
        contact = line_desk.contact_for(c, agent['id']) if agent else None
    if not free_until and eta and agent_days:  # the agent's recorded free days, counted from arrival
        free_until, estimated, free_days = eta + dt.timedelta(days=agent_days - 1), True, agent_days
        args['free_until'] = free_until.isoformat()
    for n in numbers:
        container_returns.track(dict(args, container=n), 'مستند ملاحي')
    with db() as c:  # the agent written on the document beats the guess from the container prefix
        c.execute('''UPDATE container_returns SET agent_id=COALESCE(%s,agent_id),size=COALESCE(size,%s),arrived_on=COALESCE(arrived_on,%s),
            free_until_estimated=CASE WHEN %s THEN TRUE ELSE free_until_estimated END WHERE container = ANY(%s)''',
                  (agent['id'] if agent else None, size or None, eta, estimated, numbers))
    new = [n for n in numbers if n not in existing]
    head = ' — '.join(x for x in (str(fields.get('shipping_line') or '').strip(), str(fields.get('vessel') or '').strip()) if x)
    what = (f'سجلت {len(new)} حاوية جديدة' if new else 'الحاويات مسجلة سابقًا — حدّثت بياناتها') + \
        (f' وحدّثت {len(numbers) - len(new)}' if new and len(new) < len(numbers) else '')
    lines = [f'🚢 {what} من المستند الملاحي' + (f' ({head})' if head else '') + ' في مكتب الحاويات:',
             '، '.join(numbers)]
    for label, key in (('البوليصة', 'bill_no'), ('المستلم', 'consignee'), ('مكان الإرجاع', 'return_place')):
        if fields.get(key):
            lines.append(f'• {label}: {fields[key]}')
    if agent:
        lines.append(f"• الوكيل الملاحي: {agent['name']}" + (f" — بريد التمديد/الغرامات: {contact['email']}" if contact else ' — لا يوجد بريد مسجل له'))
    else:
        lines.append('• الوكيل الملاحي غير معروف عندي؛ اكتب: «وكيل البوليصة ' + str(fields.get('bill_no') or '...') + ' هو <الاسم>».')
    if eta:
        from app import port_terminals
        lines.append(f'• الوصول: {eta.isoformat()} — آخر يوم مجاني من أرضيات الميناء: '
                     f"{(eta + dt.timedelta(days=port_terminals.FREE_DAYS - 1)).strftime('%d/%m')} (3 أيام من النزول)")
    if free_until:
        lines.append(f'• آخر يوم مجاني عند الوكيل: {free_until.isoformat()}' + (f' (تقديري: الوصول + {free_days} يوم — تأكد من الخط)' if estimated else ''))
        lines.append('أجهز لك طلب التمديد قبل نهاية المدة بـ3 أيام، وما أقفل أي حاوية إلا بسند إرجاع.')
    elif agent and not agent_days:
        lines.append(f"• آخر يوم مجاني عند الوكيل غير مكتوب في المستند. اكتب مرة واحدة أيام السماح عند {agent['name']} (مثال: «أيام السماح {agent['name']} 14») "
                     'وأحسبه لكل حاوياته من تاريخ الوصول، أو أرسل التاريخ: «آخر يوم مجاني لحاويات البوليصة '
                     + str(fields.get('bill_no') or '...') + ' 15/11».')
    else:
        lines.append('• آخر يوم مجاني غير مكتوب ولا تاريخ الوصول؛ أرسله: «آخر يوم مجاني لحاويات البوليصة '
                     + str(fields.get('bill_no') or '...') + ' 15/11» عشان تشتغل التنبيهات وطلب التمديد.')
    return '\n'.join(lines)
