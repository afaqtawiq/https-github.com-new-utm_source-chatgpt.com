import re, socket, ipaddress, hashlib
from urllib.parse import urlparse, urljoin
import httpx

TERMS={
 'customs':['تخليص جمركي','مخلص جمركي','التخليص الجمركي','customs clearance','customs broker','clearance services'],
 'transport':['نقل بري','خدمات النقل','ناقلة','شاحنات','transport services','road transport','trucking','fleet'],
 'shipping':['شحن بحري','شحن جوي','خدمات الشحن','shipping services','freight forwarding','air freight','sea freight'],
 'warehouse':['مستودع','مستودعات','تخزين','خدمات التخزين','warehouse','warehousing','storage services'],
 'door':['من الباب إلى الباب','باب إلى باب','door to door','last mile'],
 'intent':['منافسة','مناقصة','طلب عروض','طلب عرض سعر','توريد خدمة','تبحث عن','مطلوب','rfq','rfx','tender','request for proposal','request for quotation','seeking','looking for provider','vendor']
}
NEGATIVE=['وظائف','وظيفة','توظيف','job vacancy','career','training course','دورة تدريبية']

def safe_url(url):
    p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname: return False
    if p.hostname.lower() in ('localhost','localhost.localdomain'): return False
    try:
        for info in socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM):
            ip=ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast: return False
    except Exception:return False
    return True

def strip_html(raw):
    raw=re.sub(r'(?is)<(script|style|noscript).*?>.*?</\1>',' ',raw)
    title=''
    m=re.search(r'(?is)<title[^>]*>(.*?)</title>',raw)
    if m:title=re.sub(r'<[^>]+>',' ',m.group(1))
    text=re.sub(r'(?s)<[^>]+>',' ',raw); text=re.sub(r'&nbsp;',' ',text); text=re.sub(r'&amp;','&',text); text=re.sub(r'\s+',' ',text).strip()
    return title.strip(),text[:120000]

def score_text(text):
    t=text.lower(); matched=[]; service_hits=0; intent_hits=0
    for group,terms in TERMS.items():
        hits=[x for x in terms if x.lower() in t]
        if hits:
            matched.extend(hits)
            if group=='intent': intent_hits+=len(hits)
            else: service_hits+=len(hits)
    score=min(100,service_hits*12+intent_hits*18+(20 if service_hits and intent_hits else 0))
    if any(x.lower() in t for x in NEGATIVE):score=max(0,score-35)
    return score,matched[:20]

def fetch_public(url):
    if not safe_url(url): raise ValueError('URL is not allowed')
    headers={'User-Agent':'GulfLogisticsAI/1.0 (+public-source-monitor; contact=admin)'}
    with httpx.Client(timeout=12,follow_redirects=False,headers=headers) as c:
        r=c.get(url)
        if r.status_code in (301,302,303,307,308):
            nxt=urljoin(url,r.headers.get('location',''))
            if not safe_url(nxt):raise ValueError('Unsafe redirect')
            r=c.get(nxt)
        r.raise_for_status()
        ctype=r.headers.get('content-type','').lower()
        if not any(x in ctype for x in ('text/html','text/plain','application/xhtml+xml','application/xml','text/xml','application/rss+xml')):raise ValueError('Unsupported content type')
        raw=r.text[:500000]
    title,text=strip_html(raw); score,matched=score_text(title+' '+text)
    excerpt=text[:900]
    return {'title':title or urlparse(url).hostname,'url':str(r.url),'excerpt':excerpt,'score':score,'matched_terms':matched}

def fingerprint(url):return hashlib.sha256(url.strip().encode()).hexdigest()
