"""Import vs transit from the shipping documents (owner, 26 Nov 2026).

«الوكيل لا يميز بين بيان الاستيراد للسعودية وبيان الترانزيت؛ عندما يكون المستلم الأخير خارج السعودية هذا ترانزيت».

A Saudi port of discharge (Jeddah/Dammam) or a Saudi notify party does NOT make a shipment an import: the notify party is
usually us (the broker). The final destination decides, read in this order: the consignee's country, the final place of
delivery, and «DEST:» in the marks. Everything foreign → transit; everything Saudi → import; mixed → review (never guess).
Pure functions only: no database, no network, no customs decision beyond naming the declaration type to prepare.
"""
import re
import unicodedata

COUNTRIES = {
    'SA': ('السعودية', ('saudi arabia', 'saudi', 'ksa', 'k.s.a', 'riyadh', 'ar riyad', 'jeddah', 'jiddah', 'dammam', 'khobar',
                        'jubail', 'yanbu', 'mecca', 'makkah', 'medina', 'madinah', 'qassim', 'buraidah', 'tabuk', 'abha',
                        'السعوديه', 'المملكه العربيه السعوديه', 'الرياض', 'جده', 'الدمام', 'الخبر', 'الجبيل', 'ينبع',
                        'مكه', 'المدينه المنوره', 'القصيم', 'بريده', 'تبوك', 'ابها')),
    'QA': ('قطر', ('qatar', 'quatr', 'qatr', 'doha', 'قطر', 'الدوحه')),
    'AE': ('الإمارات', ('uae', 'u.a.e', 'united arab emirates', 'emirates', 'dubai', 'deira', 'abu dhabi', 'sharjah', 'ajman',
                        'jebel ali', 'الامارات', 'دبي', 'ابوظبي', 'ابو ظبي', 'الشارقه', 'عجمان')),
    'KW': ('الكويت', ('kuwait', 'الكويت')),
    'BH': ('البحرين', ('bahrain', 'manama', 'البحرين', 'المنامه')),
    'OM': ('عُمان', ('oman', 'sultanate of oman', 'muscat', 'sohar', 'سلطنه عمان', 'مسقط', 'صحار')),
    'JO': ('الأردن', ('jordan', 'amman', 'الاردن', 'عمان الاردن')),
    'YE': ('اليمن', ('yemen', 'sanaa', "sana'a", 'aden', 'اليمن', 'صنعاء', 'عدن')),
    'IQ': ('العراق', ('iraq', 'baghdad', 'basra', 'العراق', 'بغداد', 'البصره')),
}
# The usual land exit for each destination. Shown as «expected»: the broker confirms the route in FASAH.
EXIT_PORT = {'QA': 'منفذ سلوى', 'AE': 'منفذ البطحاء', 'KW': 'منفذ الخفجي أو الرقعي', 'BH': 'جسر الملك فهد',
             'OM': 'منفذ الربع الخالي', 'JO': 'منفذ الحديثة', 'YE': 'منفذ الوديعة', 'IQ': 'منفذ جديدة عرعر'}
LABEL = {'import': 'استيراد', 'transit': 'ترانزيت (عبور)', 'review': 'يحتاج تحديد'}
_SOURCES = (('consignee', 'المرسل إليه'), ('consignee_address', 'عنوان المرسل إليه'), ('consignee_country', 'دولة المرسل إليه'),
            ('final_destination', 'مكان التسليم النهائي'), ('marks_destination', 'الوجهة في العلامات'),
            ('marks', 'الوجهة في العلامات'))


def _fold(text):
    text = unicodedata.normalize('NFKC', str(text or '')).lower()
    text = re.sub(r'[إأآ]', 'ا', text).replace('ة', 'ه').replace('ى', 'ي')
    return ' ' + re.sub(r"[^a-z0-9؀-ۿ.']+", ' ', text).strip() + ' '


def country_of(text):
    """ISO code of the one country named in the text, or None (none or several)."""
    folded = _fold(text)
    found = {code for code, (_, words) in COUNTRIES.items() if any(' ' + w + ' ' in folded for w in words)}
    if 'OM' in found and 'JO' in found:  # «عمان الأردن» is Amman, not Oman
        found.discard('OM')
    return found.pop() if len(found) == 1 else None


def _marks_destination(text):
    match = re.search(r'(?:final\s+)?dest(?:ination)?\.?\s*[:\-]\s*([^\n,;]{2,40})', str(text or ''), re.I)
    return match.group(1) if match else ''


def infer(fields):
    """fields: any of consignee, consignee_address, consignee_country, final_destination, marks_destination, marks,
    notify_party, pod. Returns {'movement': 'import'|'transit'|'review'|'', 'destination', 'destination_ar', 'exit_port',
    'evidence': [...], 'conflicts': [...]}."""
    fields = fields or {}
    evidence, seen = [], {}
    for key, label in _SOURCES:
        raw = fields.get(key)
        if not raw:
            continue
        text = _marks_destination(raw) if key == 'marks' else str(raw)
        if key == 'consignee' and re.search(r'\bto\s+(?:the\s+)?order\b|لأمر|لامر', text, re.I):
            evidence.append('المرسل إليه «لأمر» — لا يحدد الوجهة')
            continue
        code = country_of(text)
        if code:
            seen.setdefault(code, []).append(label)
            evidence.append(f'{label}: {COUNTRIES[code][0]}')
    notify = country_of(fields.get('notify_party'))
    if notify:
        evidence.append(f'الطرف المُخطَر في {COUNTRIES[notify][0]} — لا يحدد المستورد (غالبًا المخلص)')
    result = {'movement': '', 'destination': '', 'destination_ar': '', 'exit_port': '', 'evidence': evidence, 'conflicts': []}
    if not seen:
        return result
    if len(seen) > 1:
        result['movement'] = 'review'
        result['conflicts'] = ['المستندات تشير إلى أكثر من وجهة: ' + ' / '.join(
            f"{COUNTRIES[c][0]} ({'، '.join(dict.fromkeys(src))})" for c, src in seen.items())]
        return result
    code = next(iter(seen))
    result.update(destination=code, destination_ar=COUNTRIES[code][0])
    if code == 'SA':
        result['movement'] = 'import'
    else:
        result['movement'] = 'transit'
        result['exit_port'] = EXIT_PORT.get(code, '')
    return result


def summary_ar(result, pod=''):
    """One Arabic line for replies and cards."""
    movement = (result or {}).get('movement')
    if movement == 'transit':
        port = f' من {pod}' if pod else ''
        exit_port = f" — الخروج المتوقع: {result['exit_port']} (يؤكده المخلص حسب المسار)" if result.get('exit_port') else ''
        return f"🛃 نوع البيان: ترانزيت (عبور){port} إلى {result['destination_ar']}{exit_port}. لا تُطبق عليه خطوات الاستيراد."
    if movement == 'import':
        return '🛃 نوع البيان: استيراد إلى السعودية.'
    if movement == 'review':
        return '⚠️ نوع البيان غير محسوم: ' + '؛ '.join(result.get('conflicts') or []) + ' — حدّده قبل تجهيز البيان.'
    return ''


def normalize(value):
    """Staff wording → 'import' / 'transit' / ''."""
    folded = _fold(value)
    if re.search(r'ترانزيت|عبور|عابر|transit', folded):
        return 'transit'
    if re.search(r'استيراد|وارد|import', folded):
        return 'import'
    return ''
