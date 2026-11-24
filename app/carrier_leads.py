"""Transport companies and fleet owners who contact Afaq are partners, not shippers (owner, 24 Nov 2026).

When a WhatsApp conversation shows the other side owns trucks / a fleet (or its WhatsApp name is a transport
company), the company is saved once in the carrier directory and the manager is told, so Khaled can collect its
rates. Nothing is sent to the company from here.
"""
import re

CARRIER_TEXT = re.compile(
    r'(?:نقليات|شركة\s*نقل|مؤسسة\s*نقل|للنقل(?:\s|$)|أسطول|اسطول|ناقل(?:ين)?\b|'
    r'(?:عندنا|لدينا|عندي|لدي|نملك|نمتلك|أملك|املك)\s*(?:\d+|[٠-٩]+)?\s*(?:شاحن|تريل|سطح|دينا|قلاب|براد|لوبد|ستار)|'
    r'(?:نبي|نبغى|نبغي|نود|حابين|نرغب)\s*(?:نتعاون|التعاون|نشتغل\s*معكم)|'
    r'\b(?:trucking|transport(?:ation)?\s+company|logistics\s+company|fleet|carrier|we\s+(?:have|own|operate)\s+\d*\s*(?:trucks|trailers))\b)',
    re.I)
COUNT_TRUCKS = re.compile(r'(?:\d+|[٠-٩]+)\s*(?:شاحن\S*|تريل\S*|trucks?|trailers?)', re.I)


def looks_like_carrier(texts, sender_name=''):
    joined = ' '.join(str(t or '') for t in texts)
    if CARRIER_TEXT.search(str(sender_name or '')) or CARRIER_TEXT.search(joined):
        return True
    return False


def fleet_hint(texts):
    m = None
    for t in texts:
        m = COUNT_TRUCKS.search(str(t or '')) or m
    return m.group(0) if m else ''


def note(sender, texts, sender_name=''):
    """Save the company once in the carrier directory; return a manager notice the first time, else None."""
    from app.storage import db, utcnow
    digits = re.sub(r'\D', '', str(sender))
    country = {'966': 'SA', '971': 'AE', '974': 'QA', '965': 'KW', '973': 'BH', '968': 'OM'}.get(digits[:3], 'SA')
    name = ' '.join(str(sender_name or '').split())[:80] or f'شركة نقل +{digits}'
    fleet = fleet_hint(texts)
    with db() as c:
        if not c.execute("SELECT to_regclass('carrier_companies') AS t").fetchone()['t']:
            c.execute('CREATE TABLE IF NOT EXISTS carrier_lead_notices(phone TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL)')
            if c.execute('INSERT INTO carrier_lead_notices VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING phone',
                         (digits, utcnow())).fetchone() is None:
                return None
        elif c.execute("SELECT 1 FROM carrier_companies WHERE regexp_replace(phone,'\\D','','g') LIKE %s LIMIT 1",
                     ('%' + digits[-9:],)).fetchone():
            return None
        else:
            now = utcnow()
            c.execute('''INSERT INTO carrier_companies(company_name,normalized_name,country,phone,capacity,notes,
            created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(normalized_name,country) DO NOTHING''',
                  (name, ' '.join(name.lower().split()), country, '+' + digits, fleet,
                   'تواصلت معنا عبر واتساب تعرض التعاون (تسجيل آلي) — آخر رسالة: ' + str(texts[-1] if texts else '')[:200],
                   now, now))
    return (f'🤝 شركة نقل تعرض التعاون: {name} (+{digits})' + (f' — أسطول: {fleet}' if fleet else '')
            + '\nسجلتها في دليل الناقلين. الوكيل طلب منهم أنواع الشاحنات والمسارات وقائمة الأسعار.'
            + '\nخالد: تابع أسعارهم وأضفهم لقائمة السائقين/الناقلين.')
