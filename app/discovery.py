import re, socket, ipaddress, hashlib, os, threading, time
from urllib.parse import urlparse, urljoin
import httpx

from app.search_connectors import external_search_candidates

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


def extract_candidates(raw, base_url):
    candidates = []
    seen = set()
    directory_mode = any(host in base_url.lower() for host in (
        "saudiexports.gov.sa", "investindubai.gov.ae"
    ))
    for match in re.finditer(r"""(?is)<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""", raw):
        href = urljoin(base_url, match.group(1).strip())
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https") or parsed.hostname != urlparse(base_url).hostname:
            continue
        title = re.sub(r"(?s)<[^>]+>", " ", match.group(2))
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) < 5 or href in seen:
            continue
        around = raw[max(0, match.start()-280):min(len(raw), match.end()+520)]
        _, context = strip_html(around)
        score, matched = score_text(title + " " + context)
        if directory_mode and (
            "company" in context.lower() or "city" in context.lower() or
            "شركة" in context or "مؤسسة" in context or "مصنع" in context
        ):
            score = max(score, 62)
            matched = list(dict.fromkeys(matched + ["شركة تجارية محتملة"]))
        if score < 30:
            continue
        seen.add(href)
        candidates.append({
            "title": title[:500],
            "url": href,
            "excerpt": context[:900],
            "score": score,
            "matched_terms": matched,
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:40]

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
    return {'title':title or urlparse(url).hostname,'url':str(r.url),'excerpt':excerpt,'score':score,'matched_terms':matched,
            'candidates':extract_candidates(raw,str(r.url))}

def fingerprint(url):return hashlib.sha256(url.strip().encode()).hexdigest()


DEFAULT_SOURCES = [
    ("منصة اعتماد — المنافسات والمشتريات", "https://etimad.sa/LandingPage/CompetationContent", "government"),
    ("زاتكا — المنافسات والمشتريات", "https://zatca.gov.sa/ar/AboutUs/Pages/Procurement-and-Tenders.aspx", "government"),
    ("زاتكا — خطة المشتريات 2026", "https://zatca.gov.sa/ar/MediaCenter/Elan/Pages/Procurement-and-Tenders-for-the-Fiscal-Year-2026.aspx", "government"),
    ("الهيئة العامة للموانئ", "https://mawani.gov.sa/", "government"),
    ("دليل المصدرين السعوديين", "https://www.saudiexports.gov.sa/en/ExportersDirectory?Source=%2Fen%2FExportersDirectory%2FPages%2F", "company_directory"),
    ("الإمارات — التحقق من الرخص والشركات", "https://u.ae/en/information-and-services/business/important-digital-services/inquire-about-licences-names-and-activities", "company_directory"),
    ("دليل شركات دبي", "https://www.investindubai.gov.ae/ar/dubai-business-directory-search", "company_directory"),
    ("حراج — مطلوب تخليص جمركي", "https://haraj.com.sa/search/%D9%85%D8%B7%D9%84%D9%88%D8%A8%2B%D8%AA%D8%AE%D9%84%D9%8A%D8%B5%2B%D8%AC%D9%85%D8%B1%D9%83%D9%8A/", "marketplace"),
    ("حراج — مطلوب نقل بضائع", "https://haraj.com.sa/search/%D9%85%D8%B7%D9%84%D9%88%D8%A8%2B%D9%86%D9%82%D9%84%2B%D8%A8%D8%B6%D8%A7%D8%A6%D8%B9/", "marketplace"),
    ("حراج — مطلوب مستودع أو تخزين", "https://haraj.com.sa/search/%D9%85%D8%B7%D9%84%D9%88%D8%A8%2B%D9%85%D8%B3%D8%AA%D9%88%D8%AF%D8%B9%2B%D8%AA%D8%AE%D8%B2%D9%8A%D9%86/", "marketplace"),
]

_worker_started = False


def ensure_default_sources():
    from app.storage import execute, one, utcnow
    for name, url, source_type in DEFAULT_SOURCES:
        if not one("SELECT id FROM source_watches WHERE url=?", (url,)):
            execute(
                "INSERT INTO source_watches(name,url,source_type,enabled,last_status,last_checked_at,created_at) VALUES(?,?,?,?,?,?,?)",
                (name, url, source_type, 1, "جاهز للفحص", None, utcnow()),
            )


def _promote_signal(signal_id, source_name, result):
    from app.storage import execute, one, utcnow
    signal = one("SELECT * FROM discovered_signals WHERE id=?", (signal_id,))
    if not signal or signal.get("opportunity_id"):
        return signal.get("opportunity_id") if signal else None
    now = utcnow()
    opportunity_id = execute(
        """INSERT INTO opportunities(company_name,source_url,signal,score,stage,estimated_value,currency,owner,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            source_name,
            result["url"],
            result["excerpt"][:1400],
            result["score"],
            "new",
            0,
            "SAR",
            "محرك الفرص الآلي",
            now,
            now,
        ),
    )
    execute("UPDATE discovered_signals SET status='promoted',opportunity_id=? WHERE id=?", (opportunity_id, signal_id))
    services = []
    matched = " ".join(result.get("matched_terms") or []).lower()
    if any(x in matched for x in ("تخليص", "جمرك", "customs", "clearance", "broker")):
        services.append("التخليص الجمركي")
    if any(x in matched for x in ("نقل", "شاحن", "transport", "trucking", "fleet")):
        services.append("النقل")
    if any(x in matched for x in ("مستودع", "تخزين", "warehouse", "storage", "warehousing")):
        services.append("التخزين")
    service_text = "، ".join(services) or "الخدمات اللوجستية"
    proposal = (
        "مسودة آلية — غير مرسلة\n\n"
        f"السادة/ {source_name}،\n"
        f"اطلعنا على الفرصة المنشورة المتعلقة بخدمات {service_text}. "
        "تقدم آفاق طويق خدمات التخليص الجمركي والنقل والتخزين عبر المنافذ الجمركية السعودية، "
        "ونرغب في مراجعة نطاق العمل والمتطلبات لتقديم عرض فني وتجاري مناسب.\n\n"
        "يجب مراجعة المصدر والمتطلبات وبيانات التواصل قبل اعتماد الإرسال."
    )
    intelligence_id = execute(
        """INSERT INTO opportunity_intelligence(opportunity_id,priority,intent,services,evidence,next_action,proposal_draft,follow_up_status,generated_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            opportunity_id,
            "P1" if result["score"] >= 80 else "P2",
            "High" if result["score"] >= 70 else "Medium",
            service_text,
            result["excerpt"][:1400],
            "مراجعة رابط المصدر والموعد والمتطلبات ثم اعتماد مسودة التواصل.",
            proposal,
            "draft",
            now,
            now,
        ),
    )
    message_id = execute(
        """INSERT INTO outbound_messages(opportunity_id,channel,recipient,subject,body,proposal_text,status,provider,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            opportunity_id,
            "email" if result.get("email") else ("whatsapp" if result.get("phone") else "email"),
            result.get("recipient", ""),
            "طلب تفاصيل فرصة خدمات لوجستية — آفاق طويق",
            proposal,
            proposal,
            "draft",
            "pending_channel",
            now,
            now,
        ),
    )
    approval_id = execute(
        """INSERT INTO approvals(kind,entity_type,entity_id,status,notes,created_at)
           VALUES(?,?,?,?,?,?)""",
        (
            "outreach",
            "outbound_message",
            message_id,
            "pending",
            f"فرصة آلية #{opportunity_id}: راجع المصدر وبيانات التواصل قبل الإرسال.",
            now,
        ),
    )
    execute("UPDATE outbound_messages SET approval_id=? WHERE id=?", (approval_id, message_id))
    return opportunity_id



IMPORTER_TERMS = (
    "استيراد", "مستورد", "تصدير", "تجارة دولية", "تجاري", "مصنع", "مصانع",
    "import", "importer", "export", "trading", "manufacturer", "distribution"
)
CUSTOMER_SERVICE_TERMS = (
    "تخليص", "جمرك", "شحن", "نقل", "مستودع", "تخزين",
    "customs", "clearance", "freight", "transport", "warehouse", "storage"
)


def _scan_registered_customers():
    from app.storage import rows, one, execute, utcnow
    stats = {"customers_checked": 0, "customer_signals": 0, "customer_opportunities": 0}
    try:
        customers = rows(
            """SELECT 'account' kind,id,name company_name,COALESCE(country,'') city,
                      COALESCE(phone,'') phone,COALESCE(email,'') email,COALESCE(notes,'') notes
               FROM accounts
               UNION ALL
               SELECT 'directory' kind,id,company_name,COALESCE(city,'') city,
                      COALESCE(phone,'') phone,COALESCE(email,'') email,'' notes
               FROM customer_directory"""
        )
    except Exception:
        customers = rows(
            """SELECT 'account' kind,id,name company_name,COALESCE(country,'') city,
                      COALESCE(phone,'') phone,COALESCE(email,'') email,COALESCE(notes,'') notes
               FROM accounts"""
        )
    seen = set()
    for customer in customers:
        name = (customer.get("company_name") or "").strip()
        phone = (customer.get("phone") or "").strip()
        email = (customer.get("email") or "").strip()
        key = (name.lower(), phone or email)
        if not name or key in seen:
            continue
        seen.add(key)
        stats["customers_checked"] += 1
        text = " ".join((name, customer.get("city") or "", customer.get("notes") or "")).lower()
        importer_hits = [term for term in IMPORTER_TERMS if term.lower() in text]
        service_hits = [term for term in CUSTOMER_SERVICE_TERMS if term.lower() in text]
        contact_score = 15 if (phone or email) else 0
        score = min(95, 35 + contact_score + (25 if importer_hits else 0) + (20 if service_hits else 0))
        signal_url = f"internal://customer/{customer['kind']}/{customer['id']}"
        if one("SELECT id FROM discovered_signals WHERE url=?", (signal_url,)):
            continue
        matched = list(dict.fromkeys(importer_hits + service_hits))
        excerpt = (
            f"عميل مسجل في النظام: {name}. المدينة/الدولة: {customer.get('city') or 'غير محدد'}. "
            f"بيانات التواصل: {'متوفرة' if (phone or email) else 'غير مكتملة'}. "
            f"التصنيف: {'مستورد أو نشاط تجاري محتمل' if importer_hits else 'عميل يحتاج تأهيل'}."
        )
        signal_id = execute(
            """INSERT INTO discovered_signals(title,url,company_name,excerpt,score,matched_terms,status,discovered_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                "فرصة من قاعدة العملاء — " + name,
                signal_url,
                name,
                excerpt,
                score,
                "، ".join(matched) if matched else "عميل مسجل",
                "new",
                utcnow(),
            ),
        )
        stats["customer_signals"] += 1
        if score >= 65:
            result = {
                "title": "فرصة عميل مسجل — " + name,
                "url": signal_url,
                "excerpt": excerpt,
                "score": score,
                "matched_terms": matched,
                "email": email,
                "phone": phone,
                "recipient": email or phone,
            }
            _promote_signal(signal_id, name, result)
            stats["customer_opportunities"] += 1
    return stats


def _scan_external_search():
    from app.storage import one, execute, utcnow
    items, statuses = external_search_candidates()
    connector_urls = {
        "google_maps": ("Google Maps — بحث الشركات", "https://places.googleapis.com/v1/places:searchText"),
        "web_search": ("محرك البحث — فرص السوق", "https://api.search.brave.com/res/v1/web/search"),
    }
    source_ids = {}
    for key, (name, url) in connector_urls.items():
        source = one("SELECT id FROM source_watches WHERE url=?", (url,))
        if source:
            source_ids[key] = source["id"]
            execute("UPDATE source_watches SET last_status=?,last_checked_at=? WHERE id=?",
                    (statuses.get(key, "غير معروف"), utcnow(), source["id"]))
        else:
            source_ids[key] = execute(
                "INSERT INTO source_watches(name,url,source_type,enabled,last_status,last_checked_at,created_at) VALUES(?,?,?,?,?,?,?)",
                (name, url, "api_connector", 0, statuses.get(key, "غير معروف"), utcnow(), utcnow()),
            )
    stats = {"external_checked": len(items), "external_signals": 0, "external_opportunities": 0}
    for item in items:
        if item.get('manual_search'):
            continue
        source_key = "google_maps" if "google.com/maps" in item["url"] else "web_search"
        digest = hashlib.sha256((item["url"] + "|" + item["title"]).encode("utf-8")).hexdigest()[:20]
        signal_url = item["url"].split("#", 1)[0] + "#external-" + digest
        if one("SELECT id FROM discovered_signals WHERE url=?", (signal_url,)):
            continue
        signal_id = execute(
            """INSERT INTO discovered_signals(source_watch_id,title,url,company_name,excerpt,score,matched_terms,status,discovered_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                source_ids.get(source_key),
                item["title"],
                signal_url,
                item.get("company_name") or item["title"],
                item["excerpt"],
                item["score"],
                "، ".join(item["matched_terms"]),
                "new",
                utcnow(),
            ),
        )
        stats["external_signals"] += 1
        if item["score"] >= 60:
            _promote_signal(signal_id, item.get("company_name") or item["title"], item)
            stats["external_opportunities"] += 1
    return stats

def _activate_customer_pilot(limit=10):
    """Select exactly ten real contacts for the controlled sales pilot."""
    from app.storage import rows, one, execute, utcnow

    pilot_owner = "حملة تجريبية — 10 فرص"
    active = one("SELECT COUNT(*) n FROM opportunities WHERE owner=?", (pilot_owner,))["n"]
    needed = max(0, limit - active)
    activated = 0
    if needed:
        candidates = rows(
            """SELECT id,company_name,source_url,score FROM opportunities
               WHERE source_url LIKE 'internal://customer/%%'
                 AND COALESCE(owner,'')<>?
               ORDER BY score DESC,id ASC LIMIT ?""",
            (pilot_owner, needed * 8),
        )
        for opportunity in candidates:
            parts = opportunity["source_url"].split("/")
            kind, raw_id = parts[-2], parts[-1]
            if kind not in ("account", "directory") or not raw_id.isdigit():
                continue
            table = "accounts" if kind == "account" else "customer_directory"
            contact = one(
                f"SELECT COALESCE(phone,'') phone,COALESCE(email,'') email FROM {table} WHERE id=?",
                (int(raw_id),),
            )
            if not contact or not (contact.get("phone") or contact.get("email")):
                continue
            execute(
                "UPDATE opportunities SET owner=?,stage='qualified',updated_at=? WHERE id=?",
                (pilot_owner, utcnow(), opportunity["id"]),
            )
            activated += 1
            if activated >= needed:
                break
    return {
        "pilot_target": limit,
        "pilot_active": active + activated,
        "pilot_activated": activated,
    }


def run_discovery_cycle():
    # Shared across web process and the scheduled worker, without persistent flags.
    from app.storage import db
    with db() as connection:
        if not connection.execute('SELECT pg_try_advisory_xact_lock(73002026) acquired').fetchone()['acquired']:
            return {'skipped': 'cycle_already_running'}
        return _run_discovery_cycle()


def _run_discovery_cycle():
    from app.storage import rows, one, execute, utcnow
    ensure_default_sources()
    stats = {"checked": 0, "signals": 0, "opportunities": 0, "errors": 0}
    customer_stats = _scan_registered_customers()
    stats.update(customer_stats)
    pilot_stats = _activate_customer_pilot(10)
    stats.update(pilot_stats)
    external_stats = _scan_external_search()
    stats.update(external_stats)
    for source in rows("SELECT * FROM source_watches WHERE enabled=1 ORDER BY id"):
        stats["checked"] += 1
        try:
            result = fetch_public(source["url"])
            scan_results = result.get("candidates") or [result]
            highest_score = 0
            for candidate in scan_results:
                highest_score = max(highest_score, candidate["score"])
                digest = hashlib.sha256(
                    (candidate["title"] + "|" + candidate["excerpt"]).encode("utf-8")
                ).hexdigest()[:20]
                candidate_url = candidate["url"].split("#", 1)[0]
                signal_url = candidate_url + "#signal-" + digest
                signal = one("SELECT id,opportunity_id FROM discovered_signals WHERE split_part(url,'#',1)=? LIMIT 1", (candidate_url,))
                if signal or candidate["score"] < 25:
                    continue
                signal_id = execute(
                    """INSERT INTO discovered_signals(source_watch_id,title,url,company_name,excerpt,score,matched_terms,status,discovered_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        source["id"],
                        candidate["title"][:500],
                        signal_url,
                        source["name"],
                        candidate["excerpt"],
                        candidate["score"],
                        "، ".join(candidate["matched_terms"]),
                        "new",
                        utcnow(),
                    ),
                )
                stats["signals"] += 1
                if candidate["score"] >= 50:
                    _promote_signal(signal_id, source["name"], candidate)
                    stats["opportunities"] += 1
            execute(
                "UPDATE source_watches SET last_status=?,last_checked_at=? WHERE id=?",
                (f"تم الفحص — {len(scan_results)} نتيجة — أعلى درجة {highest_score}", utcnow(), source["id"]),
            )
        except Exception as exc:
            stats["errors"] += 1
            execute(
                "UPDATE source_watches SET last_status=?,last_checked_at=? WHERE id=?",
                ("تعذر الفحص: " + str(exc)[:180], utcnow(), source["id"]),
            )
    return stats


def start_discovery_worker():
    global _worker_started
    if _worker_started or os.getenv("DISCOVERY_AUTO_ENABLED", "1") != "1":
        return
    _worker_started = True

    def loop():
        time.sleep(20)
        while True:
            try:
                stats = run_discovery_cycle()
                print("DISCOVERY_CYCLE", stats, flush=True)
            except Exception as exc:
                print("DISCOVERY_CYCLE_ERROR", str(exc)[:300], flush=True)
            time.sleep(max(900, int(os.getenv("DISCOVERY_INTERVAL_SECONDS", "21600"))))

    threading.Thread(target=loop, name="afaaq-discovery", daemon=True).start()
