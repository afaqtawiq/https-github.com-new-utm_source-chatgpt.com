"""Google review requests (owner request, Nov 2026). Active only once GOOGLE_REVIEW_URL holds the Afaq Tuwaiq Google
Business Profile review link. The request is added to the «released» customer message (sent only after «نفذ») and
prepared as a «نفذ» message when a container is closed as returned. Never sent automatically."""
import os
import re
from urllib.parse import urlsplit

HOSTS = ('g.page', 'search.google.com', 'maps.app.goo.gl', 'g.co', 'www.google.com', 'google.com', 'maps.google.com')


def review_url():
    url = os.getenv('GOOGLE_REVIEW_URL', '').strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return ''
    return url if parts.scheme == 'https' and parts.hostname in HOSTS and not re.search(r'\s', url) else ''


def line():
    url = review_url()
    return f'رأيكم يهمنا ⭐ قيّموا تجربتكم مع آفاق طويق على قوقل (دقيقة واحدة): {url}' if url else ''


def after_delivery_text(customer=''):
    url = review_url()
    if not url:
        return None
    return ((f'مرحبًا {customer}،\n' if customer else 'عميلنا العزيز،\n')
            + 'شكرًا لثقتكم بآفاق طويق؛ اكتملت شحنتكم وأُعيدت الحاوية الفارغة.\n'
            + 'لو كانت تجربتكم معنا جيدة، يسعدنا تقييمكم على قوقل — يساعد غيركم يعرفنا:\n' + url
            + '\nآفاق طويق للتخليص الجمركي والنقل — 0507665873')
