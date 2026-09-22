"""Reviewed Jeddah campaign content and deterministic recipient selection."""
import html
import re

EMAIL = 'afaq@shodai.cc'
PHONE = '+966530130435'
WEBSITE = 'https://www.afaqtwiq.com/'
SUBJECT = 'خدمات آفاق طويق في ميناء جدة الإسلامي | التخليص والنقل والتخزين'
TEMPLATE_NAME = 'afaaq_marketing_jeddah_brochure_v1_ar'
SERVICES = [
    ('التخليص الجمركي', 'متابعة إجراءات التخليص في ميناء جدة.'),
    ('استقبال الشحنات', 'تنسيق وصول الشحنة ومتابعة المستندات.'),
    ('النقل البري', 'ترتيب نقل البضائع إلى وجهتها داخل المملكة.'),
    ('المناولة والتحميل', 'تنسيق تحميل وتفريغ ومناولة البضائع.'),
    ('التخزين والحاويات', 'حلول التخزين وتنظيم الحاويات والساحات.'),
    ('الشحن والتسليم', 'ترتيبات الشحن والتوصيل إلى الوجهة النهائية.'),
]


def email_address(value):
    value = str(value or '').strip().lower()
    return value if len(value) <= 254 and re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}', value) else ''


def whatsapp_number(value):
    value = str(value or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    value = re.sub(r'[\s()\-]', '', value)
    if value.startswith('00'): value = '+' + value[2:]
    if re.fullmatch(r'05\d{8}', value): value = '+966' + value[1:]
    if re.fullmatch(r'(966|971|973|965|968|974)\d+', value): value = '+' + value
    if not re.fullmatch(r'\+[1-9]\d{7,14}', value): return ''
    for code, length in [('966',9),('971',9),('973',8),('965',8),('968',8),('974',8)]:
        if value.startswith('+' + code):
            national = value[len(code)+1:]
            if len(national) != length or national.startswith('0'): return ''
    return value


def select_recipients(records, suppressed=()):
    """Select the registered customer roster only; never infer missing contacts."""
    blocked = set(suppressed)
    for row in records:
        if str(row.get('status') or '').lower() in {'unsubscribed','do_not_contact','opted_out','محظور','إيقاف'}:
            blocked.add(('email', email_address(row.get('email'))))
            blocked.add(('whatsapp', whatsapp_number(row.get('phone'))))
    selected = {}
    for row in records:
        for channel, target in [('email', email_address(row.get('email'))), ('whatsapp', whatsapp_number(row.get('phone')))]:
            if not target or (channel, target) in blocked or target in {EMAIL, PHONE}:
                continue
            key = (channel, target)
            item = selected.setdefault(key, {'channel':channel,'recipient':target,'company_name':row['name'],'sources':[]})
            item['sources'].append(str(row['source']))
    return list(selected.values())


def message_text(brochure_url, unsubscribe_url):
    return ('آفاق طويق | خدمات ميناء جدة الإسلامي\n\n'
            'هل لديكم شحنة قادمة عبر ميناء جدة؟\n'
            'نقدم خدمات التخليص الجمركي، تنسيق استقبال الشحنات، النقل البري، مناولة البضائع، التخزين وترتيبات الشحن والتسليم.\n\n'
            'لطلب عرض سعر، أرسلوا نوع البضاعة والوزن أو عدد الحاويات وموعد الوصول والوجهة.\n'
            'البروشور: ' + brochure_url + '\n'
            'واتساب: ' + PHONE + '\nالبريد: ' + EMAIL + '\nالموقع: ' + WEBSITE + '\n'
            'لإيقاف الرسائل: ' + unsubscribe_url + '\nشكرًا لتواصلكم مع آفاق طويق.')


def message_html(brochure_url, unsubscribe_url):
    e = html.escape
    cards = ''.join('<tr><td style="padding:14px 22px;border-bottom:1px solid #e4e8eb"><b style="color:#0b2537">'+e(t)+'</b><br><span style="color:#526777">'+e(d)+'</span></td></tr>' for t,d in SERVICES)
    return f'''<!doctype html><html lang="ar" dir="rtl"><body style="margin:0;background:#f5f3ed;font-family:Arial,sans-serif">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
    <table role="presentation" width="600" style="width:100%;max-width:600px;background:white;border-collapse:collapse">
    <tr><td style="background:#0b2537;color:white;padding:30px 24px"><b style="color:#d9b365">آفاق طويق</b><h1 style="font-size:28px;line-height:1.5">شحناتكم عبر ميناء جدة<br>خدمات متكاملة حتى وجهتكم</h1><p>من وصول الشحنة إلى التخليص والنقل والتسليم.</p></td></tr>
    {cards}<tr><td style="padding:24px;background:#d9b365;color:#0b2537"><h2 style="margin-top:0">اطلب عرض سعر لشحنتك</h2><p>أرسل نوع البضاعة والوزن أو عدد الحاويات وموعد الوصول والوجهة.</p><a href="https://wa.me/966530130435" style="display:inline-block;padding:12px 20px;background:#0b2537;color:white;text-decoration:none;border-radius:6px">تواصل عبر واتساب</a> <a href="{e(brochure_url)}" style="color:#0b2537">تحميل البروشور PDF</a></td></tr>
    <tr><td style="padding:22px;background:#0b2537;color:white;line-height:2">واتساب: <a dir="ltr" style="color:white" href="https://wa.me/966530130435">{PHONE}</a><br>البريد: <a style="color:white" href="mailto:{EMAIL}">{EMAIL}</a><br>الموقع: <a style="color:white" href="{WEBSITE}">www.afaqtwiq.com</a><br><small>من الحدود... إلى وجهة تجارتك</small></td></tr>
    <tr><td style="padding:16px;font-size:12px;color:#526777">رسالة تعريفية بخدمات آفاق طويق. <a href="{e(unsubscribe_url)}" style="color:#526777">إيقاف الرسائل التسويقية</a></td></tr>
    </table></td></tr></table></body></html>'''
