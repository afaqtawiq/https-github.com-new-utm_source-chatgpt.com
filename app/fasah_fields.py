"""Conservative document candidates. No customs decisions or external actions."""
import re
import unicodedata

FASAH_URL = 'https://fasah.zatca.gov.sa/ar/broker/2.0/'
DOCUMENT_TYPES = {'invoice': 'فاتورة تجارية', 'packing': 'قائمة تعبئة', 'transport': 'بوليصة شحن', 'road_transport': 'وثيقة نقل', 'export_declaration': 'بيان تصدير / إعادة تصدير', 'origin': 'شهادة منشأ', 'other': 'مستند مساند / شهادة أو تصريح آخر'}
# This is an internal preparation checklist, not Fasah's regulatory schema.
FIELDS = [
    ('importer', 'المستورد / المرسل إليه', 'الأطراف', True, r'importer(?:\s+name)?|consignee|اسم المستورد|المستورد|المرسل إليه'),
    ('registration', 'السجل التجاري للمستورد', 'الأطراف', False, r'commercial registration(?:\s+(?:no\.?|number))?|رقم السجل التجاري|السجل التجاري'),
    ('supplier', 'المورد / المصدر', 'الأطراف', True, r'supplier(?:\s+name)?|exporter|shipper|المورد|المصدر|الشاحن'),
    ('invoice_number', 'رقم الفاتورة', 'الفاتورة', True, r'(?:commercial\s+)?invoice\s*(?:no\.?|number|#)|رقم الفاتورة'),
    ('invoice_date', 'تاريخ الفاتورة كما ورد', 'الفاتورة', True, r'invoice date|تاريخ الفاتورة'),
    ('invoice_total', 'إجمالي الفاتورة كما ورد', 'الفاتورة', True, r'(?:grand|invoice)\s+total|total\s+(?:amount|value)|إجمالي الفاتورة|الإجمالي النهائي'),
    ('currency', 'العملة', 'الفاتورة', True, r'currency|العملة'),
    ('incoterm', 'شرط التسليم', 'الفاتورة', False, r'incoterms?|delivery terms|شرط التسليم|شروط التسليم'),
    ('bill_number', 'رقم بوليصة / مستند النقل', 'النقل', True, r'(?:bill of lading|b[/.]?l|air\s*waybill|waybill)\s*(?:no\.?|number|#)?|رقم البوليصة|رقم بوليصة الشحن'),
    ('containers', 'أرقام الحاويات كما وردت', 'النقل', False, r'container(?:\s+(?:no\.?|numbers?))?|رقم الحاوية|أرقام الحاويات'),
    ('arrival_port', 'منفذ الوصول', 'النقل', True, r'port of (?:discharge|arrival)|ميناء الوصول|منفذ الوصول'),
    ('packages', 'عدد الطرود ووحدتها', 'البضاعة', True, r'(?:number|no\.?) of packages|total packages|عدد الطرود'),
    ('gross_weight', 'الوزن الإجمالي ووحدته', 'البضاعة', True, r'gross weight|الوزن الإجمالي'),
    ('net_weight', 'الوزن الصافي ووحدته', 'البضاعة', False, r'net weight|الوزن الصافي'),
    ('origin', 'بلد المنشأ', 'البضاعة', True, r'country of origin|بلد المنشأ'),
    ('description', 'وصف البضاعة', 'البضاعة', True, r'(?:goods|cargo|product) description|description of goods|وصف البضاعة|وصف السلعة'),
    ('hs_code', 'رمز HS الوارد في المستند — يراجعه المختص', 'البضاعة', False, r'hs\s*(?:code|no\.?)|رمز HS|البند الجمركي'),
]
FIELD_KEYS = {f[0] for f in FIELDS}
LABELS = {f[0]: f[1] for f in FIELDS}
SENSITIVE = re.compile(r'password|one[ -]time\s+(?:password|code)|\b(?:OTP|MFA|TOTP|CAPTCHA)\b|كلمة\s*(?:المرور|السر)|رمز\s*(?:التحقق|الدخول)|recovery\s+code', re.I)


def clean(value, limit=500):
    return re.sub(r'[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069]', '', str(value or '')).strip()[:limit]


def reject_credentials(text):
    if SENSITIVE.search(str(text or '')):
        raise ValueError('لا ترفع صفحات الدخول أو رموز التحقق أو بيانات الحساب. استخدم مستندات المعاملة فقط.')


def empty_fields():
    return {key: {'value': '', 'reviewed': False, 'candidates': []} for key in FIELD_KEYS}


def value_problem(key, value):
    value = unicodedata.normalize('NFKC', str(value or '')).strip()
    if not value:
        return ''
    if not re.search(r'[\w\u0600-\u06ff]', value) or value.casefold() in {'n/a', 'na', 'none', 'null'}:
        return 'القيمة علامة فارغة وليست بيانات؛ راجع الأصل.'
    if key in ('gross_weight', 'net_weight') and not re.fullmatch(
            r'[\d\s.,٬٫]+\s*(?:kg|kgs|kilograms?|g|grams?|t|tons?|tonnes?|lbs?|pounds?|كجم|كغ|كيلو\s*جرام|طن|أطنان|غرام|جرام)\.?', value, re.I):
        return 'الوزن يحتاج رقمًا ووحدة واضحة؛ قد يكون النص المستخرج عنوانًا من الجدول.'
    if key == 'arrival_port' and re.search(r'ميناء التفريغ|port of discharge|منفذ الوصول|ميناء الوصول', value, re.I):
        return 'القيمة تبدو عنوان حقل وليست اسم منفذ؛ راجع الأصل.'
    return ''


def extract_candidates(pages, source, document_id):
    """Only explicitly labelled values; preserve competing values and page evidence."""
    result = {key: [] for key in FIELD_KEYS}
    reject_credentials(source)
    for page in pages:
        reject_credentials(page['text'])
        # Tabs / wide spaces usually delimit columns: never silently combine columns.
        lines = [clean(x, 1000) for x in page['text'].splitlines()]
        for index, line in enumerate(lines):
            for key, _, _, _, labels in FIELDS:
                match = re.match(r'^\s*(?:' + labels + r')\s*(?:[:：#=]\s*|\s{2,})(.+)$', line, re.I)
                value = match.group(1) if match else ''
                if not value and re.fullmatch(r'(?:' + labels + r')\s*[:：#]?', line, re.I) and index + 1 < len(lines):
                    following = lines[index + 1]
                    if following and not any(re.match(r'^(?:' + f[4] + r')\b', following, re.I) for f in FIELDS):
                        value = following
                if not value:
                    continue
                # A second label suggests a multi-column row needing manual interpretation.
                value = clean(re.split(r'\t| {2,}|\s\|\s', value)[0])
                if not value or value_problem(key, value) or any(re.search(r'(?:' + f[4] + r')\s*[:：]', value, re.I) for f in FIELDS):
                    continue
                evidence = clean(line + (' / ' + value if not match else ''), 600)
                item = {'value': value, 'source': source, 'page': page['page'], 'method': page['method'], 'evidence': evidence, 'document_id': document_id}
                if not any(c['value'] == value and c['page'] == item['page'] for c in result[key]):
                    result[key].append(item)
    return result


def merge_candidates(fields, candidates):
    for key in FIELD_KEYS:
        new = candidates.get(key, [])
        if not new:
            continue
        field = fields[key]
        field['candidates'].extend(new)
        field['reviewed'] = False
        if not field['value'] and len({c['value'] for c in field['candidates']}) == 1:
            field['value'] = new[0]['value']
    return fields


def readiness(fields, documents):
    invalid = [LABELS[key] for key, field in fields.items() if value_problem(key, field['value'])]
    missing = [label for key, label, _, required, _ in FIELDS if required and (not fields[key]['value'] or label in invalid)]
    unreviewed = [LABELS[key] for key, field in fields.items() if field['value'] and not field['reviewed']]
    conflicts = [LABELS[key] for key, field in fields.items() if len({c['value'].casefold() for c in field['candidates']}) > 1 and not field['reviewed']]
    return {'missing': missing, 'unreviewed': unreviewed, 'conflicts': conflicts, 'invalid': invalid,
            'review_complete': not (missing or unreviewed or conflicts or invalid)}
