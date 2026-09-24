"""Conservative extraction shared by shipment intake and operational tests."""
import re


def digits(value):
    return str(value or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))


def phone(value):
    value = digits(value).strip()
    if not re.fullmatch(r"[+\d\s()-]+", value):
        return ""
    number = re.sub(r"\D", "", value)
    if number.startswith("00"):
        number = number[2:]
    if re.fullmatch(r"05\d{8}", number):
        number = "966" + number[1:]
    return "+" + number if re.fullmatch(r"[1-9]\d{7,14}", number) else ""


def extract_phone(text):
    text = digits(text)
    matches = re.findall(r"(?<!\d)(?:(?:\+|00)?966[\s-]*5|05)(?:[\s-]*\d){8}(?!\d)", text)
    found = list(dict.fromkeys(phone(x) for x in matches if phone(x)))
    # Multiple contact numbers need review, not an arbitrary first selection.
    return found[0] if len(found) == 1 else ""


LOCATION_LABELS = r"(?:موقع|مدينة|مكان|نقطة)?\s*(?:التحميل|الاستلام|الانطلاق|التنزيل|التسليم|الوصول|الوجهة)"
STOP_LABELS = r"(?:الحمولة|نوع الشاحنة|الشاحنة|الوزن|السعر|طريقة الدفع|الدفع|التواصل|جوال|رقم|المسافة|موعد التحميل)"


def clean_location(value):
    value = re.split(r"\n|[،|]|\s+" + STOP_LABELS + r"\s*[:：]", value, maxsplit=1)[0]
    value = re.sub(r"\s+", " ", value).strip(" :：،,|.-–—>←→")
    return value[:120] if len(value) >= 2 and value not in {"غير محدد", "غير معروف"} else ""


def extract_route(raw):
    text = re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", str(raw or ""))
    text = text.replace("\u00a0", " ").replace("\r", "\n")
    # Mobile captures often place the short direction label on its own line.
    # Bind the next line only; adjacent labels or an unlabeled list of cities
    # do not provide a reliable direction.
    short_labels = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    direction = re.compile(r"^(من|إلى|الى|إلي|الي)\s*[:：]?\s*(.*)$")
    for index, line in enumerate(lines):
        match = direction.fullmatch(line)
        if not match or (match.group(2) and not re.match(r"^(?:من|إلى|الى|إلي|الي)(?:\s|[:：])", line)):
            continue
        value = match.group(2).strip()
        if not value and index + 1 < len(lines):
            value = lines[index + 1]
        if (not value or direction.fullmatch(value) or
            re.search(r"(?:^|\s)(?:إلى|الى|إلي|الي)(?:\s|[:：]|$)", value) or
            re.match(LOCATION_LABELS + r"\s*[:：]?", value) or
            re.match(STOP_LABELS + r"\s*[:：]", value)):
            continue
        value = clean_location(value)
        if value:
            key = "origin" if match.group(1) == "من" else "destination"
            short_labels.setdefault(key, set()).add(value)
    # Label order can differ in RTL screenshots. Bind each value to its label.
    labeled = {key: set(values) for key, values in short_labels.items()}
    label_pattern = re.compile(r"(?<!\w)(?:موقع|مدينة|مكان|نقطة)?\s*(التحميل|الاستلام|الانطلاق|التنزيل|التسليم|الوصول|الوجهة)\s*[:：]?\s*")
    labels = list(label_pattern.finditer(text))
    for i, match in enumerate(labels):
        end = labels[i + 1].start() if i + 1 < len(labels) else len(text)
        value = clean_location(text[match.end():end].strip())
        key = "origin" if match.group(1) in {"التحميل", "الاستلام", "الانطلاق"} else "destination"
        if value:
            labeled.setdefault(key, set()).add(value)
    if any(len(values) > 1 for values in labeled.values()):
        return "", ""
    routes = set()
    if all(len(labeled.get(k, set())) == 1 for k in ("origin", "destination")):
        routes.add((next(iter(labeled["origin"])), next(iter(labeled["destination"]))))
    patterns = [
        r"(?:^|\s)من\s*[:：]?\s*(.+?)\s+(?:إلى|الى|إلي|الي)\s*[:：]?\s*(.+?)(?=\n|[،|]|$)",
        r"(?:المسار|خط السير|الطريق)\s*[:：]?\s*(.+?)\s*(?:→|->|إلى|الى|–|—|-)\s*(.+?)(?=\n|[،|]|$)",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.I)
        routes.update((clean_location(a), clean_location(b)) for a, b in matches
                      if clean_location(a) and clean_location(b))
    if len(routes) == 1:
        result = next(iter(routes))
        if all(not labeled.get(key) or value in labeled[key]
               for key, value in zip(("origin", "destination"), result)):
            return result
    # Unlabelled city mentions do not establish shipment direction.
    return "", ""


def accepts_offer(text):
    text = digits(text).strip()
    text = re.sub(r"[\u064b-\u065f\u0670ـ]", "", text).replace("أ", "ا")
    return bool(re.fullmatch(r"(?:موافق|اقبل|جاهز|نعم)\s+(?:NQ-\d+|WA-[A-F0-9]{12})[.!،\s]*", text, re.I))
