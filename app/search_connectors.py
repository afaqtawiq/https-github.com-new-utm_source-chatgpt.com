import hashlib
import os
import urllib.parse

import httpx


MAP_QUERIES = [
    "شركات استيراد وتصدير في جدة السعودية",
    "مستوردين مواد غذائية في الرياض السعودية",
    "مصانع في الدمام السعودية",
    "شركات تجارة دولية في السعودية",
    "import export companies in Dubai UAE",
    "food importers in Dubai UAE",
    "manufacturers in Abu Dhabi UAE",
    "warehouses and distributors in Sharjah UAE",
]

WEB_QUERIES = [
    '"مطلوب تخليص جمركي" السعودية',
    '"طلب عرض سعر" نقل بضائع السعودية',
    '"مطلوب مستودع" OR "مطلوب تخزين" السعودية',
    'site:haraj.com.sa مطلوب نقل بضائع',
    'site:haraj.com.sa مطلوب تخليص جمركي',
    '"customs clearance" RFQ Saudi Arabia',
    '"transport services" tender Saudi Arabia',
    '"warehousing" RFQ UAE',
    '"freight services" tender UAE',
]


def _manual_search_candidates(queries, channel):
    """Expose safe one-click searches until API credentials are connected."""
    items = []
    for query in queries:
        encoded = urllib.parse.quote_plus(query)
        if channel == "google_maps":
            url = "https://www.google.com/maps/search/?api=1&query=" + encoded
            title = "بحث خرائط Google — " + query
            matched = ["Google Maps", "بحث جاهز للمراجعة"]
        else:
            url = "https://www.google.com/search?q=" + encoded
            title = "بحث الويب — " + query
            matched = ["محرك البحث", "بحث جاهز للمراجعة"]
        items.append({
            "manual_search": True,
            "title": title[:500],
            "url": url,
            "excerpt": (
                "رابط بحث مباشر أعده النظام للاستخدام الفوري. "
                "تظهر النتائج داخل المصدر للمراجعة، ولا تتحول إلى فرصة آلية "
                "حتى يتم ربط مفتاح API والتحقق من بيانات الشركة."
            ),
            "score": 35,
            "matched_terms": matched,
            "company_name": "بحث سوق جاهز",
        })
    return items


def google_places_candidates(limit=30):
    key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        items = _manual_search_candidates(MAP_QUERIES, "google_maps")
        return items[:limit], f"وضع روابط مباشرة — {min(len(items), limit)} عمليات بحث جاهزة"
    results = []
    seen = set()
    field_mask = "places.id,places.displayName,places.formattedAddress,places.googleMapsUri,places.types"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": field_mask,
    }
    with httpx.Client(timeout=20, headers=headers) as client:
        for query in MAP_QUERIES:
            response = client.post(
                "https://places.googleapis.com/v1/places:searchText",
                json={"textQuery": query, "maxResultCount": 10, "languageCode": "ar"},
            )
            response.raise_for_status()
            for place in response.json().get("places", []):
                place_id = place.get("id")
                if not place_id or place_id in seen:
                    continue
                seen.add(place_id)
                name = (place.get("displayName") or {}).get("text") or "شركة محتملة"
                address = place.get("formattedAddress") or ""
                url = place.get("googleMapsUri") or f"https://www.google.com/maps/search/?api=1&query_place_id={place_id}"
                results.append({
                    "title": name,
                    "url": url,
                    "excerpt": f"شركة مكتشفة عبر Google Maps. العنوان: {address}. عبارة البحث: {query}.",
                    "score": 62,
                    "matched_terms": ["Google Maps", "شركة محتملة", query],
                    "company_name": name,
                })
                if len(results) >= limit:
                    return results, f"متصل آليا — {len(results)} نتيجة"
    return results, f"متصل آليا — {len(results)} نتيجة"


def brave_search_candidates(limit=40):
    key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        items = _manual_search_candidates(WEB_QUERIES, "web_search")
        return items[:limit], f"وضع روابط مباشرة — {min(len(items), limit)} عمليات بحث جاهزة"
    results = []
    seen = set()
    headers = {"Accept": "application/json", "X-Subscription-Token": key}
    with httpx.Client(timeout=20, headers=headers) as client:
        for query in WEB_QUERIES:
            response = client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 10, "country": "SA", "search_lang": "ar", "safesearch": "strict"},
            )
            response.raise_for_status()
            for item in (response.json().get("web") or {}).get("results", []):
                url = item.get("url") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                title = item.get("title") or "فرصة بحث"
                description = item.get("description") or ""
                text = (title + " " + description).lower()
                intent = any(term in text for term in (
                    "مطلوب", "طلب عرض", "مناقصة", "rfq", "tender",
                    "request for quotation", "looking for", "seeking"
                ))
                service = any(term in text for term in (
                    "تخليص", "جمرك", "نقل", "شحن", "مستودع", "تخزين",
                    "customs", "clearance", "transport", "freight", "warehouse", "storage"
                ))
                score = 78 if intent and service else (52 if service else 25)
                results.append({
                    "title": title[:500],
                    "url": url,
                    "excerpt": description[:900],
                    "score": score,
                    "matched_terms": ["محرك البحث", "نية شراء" if intent else "شركة محتملة"],
                    "company_name": title[:200],
                })
                if len(results) >= limit:
                    return results, f"متصل آليا — {len(results)} نتيجة"
    return results, f"متصل آليا — {len(results)} نتيجة"


def external_search_candidates():
    combined = []
    statuses = {}
    for name, loader in (("google_maps", google_places_candidates), ("web_search", brave_search_candidates)):
        try:
            items, status = loader()
            combined.extend(items)
            statuses[name] = status
        except Exception as exc:
            statuses[name] = "خطأ: " + str(exc)[:180]
    unique = {}
    for item in combined:
        key = hashlib.sha256(item["url"].encode("utf-8")).hexdigest()
        unique[key] = item
    return list(unique.values()), statuses
