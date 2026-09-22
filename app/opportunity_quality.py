"""Conservative buyer/request qualification, separate from keyword relevance."""
import re
from urllib.parse import urlparse, unquote


def normalize(text):
    return re.sub(r'[\u064b-\u065f\u0640]', '', str(text or '')).translate(str.maketrans('أإآى', 'اااي')).lower()


def assess(title, text, url):
    p = urlparse(url or '')
    path = unquote(p.path).lower()
    body = normalize(text)
    combined = normalize(title) + ' ' + body
    def result(kind, reason):
        return {'kind': kind, 'reason': reason, 'is_request': kind == 'buyer_request'}
    if p.scheme not in ('http', 'https') or not p.hostname:
        return result('prospect', 'عميل محتمل؛ لا يوجد مصدر عام يثبت طلب خدمة')
    if ('google.' in p.hostname and ('maps' in path or path.startswith('/search'))) or any(
        segment in path for segment in ('/search/', '/city/', '/tags/', '/users/', 'directory', 'procurement-and-tenders-for-the-fiscal-year')
    ) or path in ('', '/'):
        return result('listing', 'صفحة عامة أو دليل شركات وليست طلب عميل محدد')
    if any(x in combined for x in ('العرض محذوف', 'محذوف او قديم', 'تم التخليص', 'تم تنفيذ الطلب', 'تم اغلاق', 'tender closed', 'expired', 'deleted')):
        return result('closed', 'الطلب محذوف أو منتهٍ أو منفذ')
    if re.search(r'وظيف|وظائف|توظيف|مسوق|بالعمول|مندوب مبيعات|job vacancy|recruit|commission.only|sales agent', combined):
        return result('recruitment', 'إعلان توظيف أو تسويق بالعمولة')
    if re.search(r'نقدم.{0,30}خدم|خدماتنا|اسعار تنافسي|لدينا.{0,25}خبر|نحن.{0,30}تخليص|we (?:offer|provide)|our services', combined):
        return result('provider', 'عرض خدمات من مقدم خدمة وليس طلب شراء')
    service = r'(?:تخليص|مخلص|نقل|شحن|تخزين|مستودع|customs|clearance|freight|transport|warehous|storage)'
    buyer = r'(?:احتاج|نحتاج|ابحث عن|نبحث عن|مطلوب|طلب عرض سعر|طلب عروض|اريد|need|require|seeking|looking for|rfq|request for quotation)'
    if not re.search(buyer + r'.{0,100}' + service, body):
        return result('unverified', 'لم يثبت طلب خدمة صريح في نص المصدر؛ عنوان البحث وحده لا يكفي')
    return result('buyer_request', 'طلب خدمة صريح؛ يلزم التحقق من توفره وبيانات التواصل قبل الاتفاق')


def assess_opportunity(op):
    return assess(op.get('company_name', ''), op.get('signal', ''), op.get('source_url', ''))


def verify_public_request(url, recipient=None):
    from app.discovery import fetch_public
    page = fetch_public(url)
    quality = assess(page['title'], page.get('request_text', ''), page['url'])
    if not quality['is_request']:
        raise ValueError(quality['reason'])
    if not page.get('detail_extracted'):
        raise ValueError('لم نستطع عزل نص الطلب عن الإعلانات والقوائم المحيطة؛ يلزم مراجعة المصدر')
    if recipient:
        # Never trust a manually substituted destination without source evidence.
        emails = re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', page['request_text'])
        if recipient.strip().lower() not in {e.lower() for e in emails}:
            raise ValueError('بريد المستلم غير مثبت في نص الطلب الأصلي')
    return page
