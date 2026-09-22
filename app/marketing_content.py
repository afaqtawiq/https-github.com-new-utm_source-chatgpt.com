"""Reviewed Jeddah campaign content and deterministic recipient selection."""
import html
import re

EMAIL = 'afaq@shodai.cc'
PHONE = '+966530130435'
WEBSITE = 'https://www.afaqtwiq.com/'
SUBJECT = 'خدمات آفاق طويق في ميناء جدة الإسلامي | التخليص والنقل والتخزين'
TEMPLATE_NAME = 'afaaq_marketing_jeddah_brochure_v2_ar'
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
    artwork_url = brochure_url.rsplit('.', 1)[0] + '.jpg'
    return f'''<!doctype html><html lang="ar" dir="rtl"><body style="margin:0;background:#e9edf1;font-family:Arial,sans-serif">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:20px 8px">
    <table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;background:white;border-collapse:collapse">
    <tr><td><a href="{e(brochure_url)}"><img src="{e(artwork_url)}" width="640" alt="آفاق طويق — شحناتك في ميناء جدة، نكمل رحلتها. تخليص جمركي، نقل بري، تخزين ومناولة، شحن وتسليم." style="display:block;width:100%;max-width:640px;height:auto;border:0"></a></td></tr>
    <tr><td style="padding:26px;color:#082139;font-size:16px;line-height:1.9"><h2 style="margin:0 0 10px">هل لديكم شحنة قادمة عبر ميناء جدة؟</h2><p>آفاق طويق لخدمات التخليص الجمركي، استقبال الشحنات، النقل البري، المناولة والتخزين، والشحن والتسليم.</p><p>لطلب عرض سعر، أرسلوا نوع البضاعة والوزن أو عدد الحاويات وموعد الوصول والوجهة.</p><a href="https://wa.me/966530130435" style="display:inline-block;padding:12px 22px;background:#082139;color:white;text-decoration:none;border-radius:6px">اطلب عرض سعر عبر واتساب</a><p><a href="{e(brochure_url)}" style="color:#082139">تحميل البروشور PDF</a> — تجدون نسخة مرفقة أيضًا.</p></td></tr>
    <tr><td style="padding:22px;background:#082139;color:white;line-height:2">واتساب: <a dir="ltr" style="color:#ecc183" href="https://wa.me/966530130435">{PHONE}</a><br>البريد: <a style="color:#ecc183" href="mailto:{EMAIL}">{EMAIL}</a><br>الموقع: <a style="color:#ecc183" href="{WEBSITE}">www.afaqtwiq.com</a></td></tr>
    <tr><td style="padding:16px;font-size:12px;color:#526777">رسالة تعريفية بخدمات آفاق طويق. <a href="{e(unsubscribe_url)}" style="color:#526777">إيقاف الرسائل التسويقية</a></td></tr>
    </table></td></tr></table></body></html>'''
