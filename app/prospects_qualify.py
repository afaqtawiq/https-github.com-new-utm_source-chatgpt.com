"""Prospects: explainable qualification and public-website email discovery (SSRF-guarded, MX-checked).
"""
from app.prospects_schema import *  # noqa: F401,F403


# ---------------------------------------------------------------- qualification

def _has(text, terms):
    return [t for t in terms if t in text]


def qualify(place, email='', email_mx=None, phone='', website=''):
    """Return (score, tier, reasons). Deterministic and explainable."""
    name = str((place.get('displayName') or {}).get('text') or place.get('name') or '')
    category = str((place.get('primaryTypeDisplayName') or {}).get('text') or place.get('category') or '')
    types = place.get('types') or []
    text = ' '.join([name, category, ' '.join(types)]).lower()
    reasons = []
    status = str(place.get('businessStatus') or 'OPERATIONAL')
    if status.startswith('CLOSED'):
        return 0, 'excluded', ['النشاط مغلق على خرائط Google']
    competitor = _has(text, COMPETITOR_TERMS)
    target = _has(text, TARGET_TERMS)
    if competitor and not target:
        return 0, 'excluded', ['مزود خدمات لوجستية منافس: ' + '، '.join(competitor[:3])]
    irrelevant = _has(text, IRRELEVANT_TERMS)
    if irrelevant and not target:
        return 0, 'excluded', ['نشاط لا يحتاج خدمات لوجستية: ' + '، '.join(irrelevant[:3])]
    score = 0
    if target:
        score += 45
        reasons.append('نشاط مستهدف: ' + '، '.join(target[:3]))
    else:
        score += 15
        reasons.append('النشاط غير واضح من الاسم والتصنيف')
    if email and email_mx:
        score += 25
        reasons.append('بريد عام متحقق (MX)')
    elif email:
        reasons.append('بريد بدون خادم MX — مستبعد من الإرسال')
    if phone:
        score += 10
        reasons.append('رقم هاتف متوفر')
    if website:
        score += 10
        reasons.append('موقع إلكتروني')
    if int(place.get('userRatingCount') or 0) >= 10:
        score += 10
        reasons.append('نشاط قائم (' + str(place.get('userRatingCount')) + ' تقييم)')
    score = min(score, 100)
    if score >= 60 and email and email_mx:
        tier = 'qualified'
    elif score >= 55 and phone:
        tier = 'phone_only'
    else:
        tier = 'review'
    return score, tier, reasons


# ---------------------------------------------------------------- enrichment

def _public_host(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def _fetch(url, client, max_bytes=400_000):
    for _ in range(4):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or not _public_host(parts.hostname):
            return '', url
        with client.stream('GET', url) as response:
            if response.is_redirect:
                url = urllib.parse.urljoin(url, response.headers.get('location', ''))
                continue
            if response.status_code >= 400 or 'html' not in response.headers.get('content-type', 'text/html'):
                return '', url
            data = b''
            for chunk in response.iter_bytes():
                data += chunk
                if len(data) > max_bytes:
                    break
            return data.decode(response.encoding or 'utf-8', 'replace'), url
    return '', url


def _root(domain):
    parts = domain.lower().split('.')
    if len(parts) >= 3 and parts[-2] in ('com', 'net', 'org', 'gov', 'edu', 'co'):
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])


def pick_email(candidates, website):
    site = _root(urllib.parse.urlsplit(website).hostname or '') if website else ''
    best, rank = '', 99
    for raw in candidates:
        address = email_address(raw.strip('.').lower())
        if not address or JUNK_EMAIL.search(address) or re.search(r'\.(png|jpe?g|gif|svg|webp)$', address):
            continue
        local, domain = address.split('@')
        same = site and _root(domain) == site
        role = local in ('info', 'sales', 'contact', 'hello', 'enquiries', 'inquiry', 'cs', 'support', 'admin', 'office')
        r = 0 if same and role else 1 if same else 2 if domain in FREE_MAIL else 3
        if r < rank:
            best, rank = address, r
    return best


def emails_from_website(website):
    if not website:
        return '', ''
    found, source = [], ''
    try:
        with httpx.Client(timeout=8, follow_redirects=False, headers={'User-Agent': 'AfaaqTuwaiqBot/1.0 (+' + WEBSITE + ')'}) as client:
            page, final = _fetch(website, client)
            found += EMAIL_RE.findall(page)
            source = final if found else ''
            links = list(dict.fromkeys(CONTACT_HREF.findall(page) + CONTACT_LINK.findall(page)))[:2]
            for link in links:
                if pick_email(found, website):
                    break
                sub, sub_final = _fetch(urllib.parse.urljoin(final, html.unescape(link)), client)
                extra = EMAIL_RE.findall(sub)
                if extra:
                    found += extra
                    source = sub_final
    except (httpx.HTTPError, OSError, ValueError):
        return '', ''
    email = pick_email(found, website)
    return email, (source if email else '')


def has_mx(address):
    if not address:
        return False
    try:
        import dns.resolver
        answers = dns.resolver.resolve(address.split('@')[1], 'MX', lifetime=6)
        return any(str(a.exchange).strip('.') for a in answers)
    except Exception:
        return False


