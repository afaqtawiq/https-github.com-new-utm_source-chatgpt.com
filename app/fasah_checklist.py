"""Evidence-based internal document checklist; never makes a Fasah submission."""
import re
import unicodedata

from app.fasah_fields import DOCUMENT_TYPES, clean

IMPORT_SOURCE = 'https://zatca.gov.sa/ar/RulesRegulations/Taxes/Pages/customs-bussiness/import-pages/Import-Instructions.aspx'
PROFILE_OPTIONS = {
    'transaction': ('نوع المعاملة', {'': 'لم يحدد', 'commercial_import': 'استيراد تجاري', 'export': 'تصدير', 'reexport': 'إعادة تصدير', 'transit': 'عبور', 'temporary': 'إدخال مؤقت', 'other': 'نوع آخر'}),
    'mode': ('وسيلة النقل', {'': 'لم تحدد', 'sea': 'بحري', 'air': 'جوي', 'land': 'بري'}),
    'origin_marking': ('هل توجد دلالة منشأ ثابتة تم التحقق منها؟', {'': 'يحتاج تحقق', 'yes': 'نعم', 'no': 'لا'}),
}
PROFILE_KEYS = set(PROFILE_OPTIONS) | {'goods', 'dispatch_country'}
REQUIREMENTS = {k: v for k, v in DOCUMENT_TYPES.items() if k != 'other'}
STATES = {'complete': 'مكتمل', 'missing': 'ناقص', 'not_required': 'غير مطلوب', 'review': 'يحتاج مراجعة'}


def normalized(value):
    text = unicodedata.normalize('NFKC', clean(value, 200000)).casefold()
    return re.sub(r'[\s_\-.]+', ' ', text).strip()


def detected_kinds(document):
    found = {}
    for page in document.get('pages', []):
        text = unicodedata.normalize('NFKC', clean(page['text'], 200000)).casefold()
        patterns = {'invoice': r'^\s*(?:commercial\s+)?invoice\s*$',
                    'packing': r'^\s*packing list\s*$',
                    'origin': r'certificat(?:e|ion) of origin',
                    'road_transport': r'وثيقة نقل دولية|وثيقة بيان حمولة',
                    'transport': r'^\s*(?:bill of lading|air waybill)\s*$'}
        for key, pattern in patterns.items():
            if re.search(pattern, text, re.M):
                found.setdefault(key, []).append(page['page'])
        if 'dec no' in text and 'dec type' in text and re.search(r're[ -]?export|اعادة تصدير|إعادة تصدير', text):
            found.setdefault('export_declaration', []).append(page['page'])
    return found


def document_flags(document):
    text = ' '.join(normalized(p['text']) for p in document.get('pages', []))
    flags = []
    if re.search(r'نسخة للمراجعة|غير رسمية|unofficial|a copy for review|draft\s*/?\s*not paid', text):
        flags.append('المستند يحمل عبارة مسودة / نسخة غير رسمية؛ يلزم التحقق من النسخة النهائية.')
    if not any(clean(p['text'], 200000) for p in document.get('pages', [])):
        flags.append('لا يتوفر نص مقروء؛ راجع وضوح المستند.')
    return flags


def suggested_kind(document):
    """Filename is a hint, not proof of document type or validity."""
    content = detected_kinds(document)
    if content:
        return min(content, key=lambda key: min(content[key]))
    name = normalized(document['name'])
    patterns = {
        'invoice': r'فاتور|\binvoice\b',
        'packing': r'قائمة (?:التعبئة|تعبئة)|\bpacking\b',
        'transport': r'بوليصة|بوليصه|bill of lading|air waybill',
        'road_transport': r'وثيقة نقل|وثيقة النقل',
        'origin': r'شهادة (?:المنشأ|منشأ|منشاء|المنشاء)|certificate of origin',
    }
    found = [key for key, pattern in patterns.items() if re.search(pattern, name)]
    return found[0] if len(found) == 1 else None


def classification_issue(document):
    hint = suggested_kind(document)
    return bool(hint and hint != document['kind'] and not document.get('classification_confirmed'))


def profile_of(context):
    return {key: context.get('profile', {}).get(key, '') for key in PROFILE_KEYS}


def automatic_requirement(key, profile):
    # Only the supported commercial-import rules below are automatic.
    # No absence of a rule is interpreted as an exemption.
    if profile['transaction'] != 'commercial_import':
        return None, 'حدد نوع المعاملة أو وثّق متطلب هذا النوع بعد مراجعة المختص.', ''
    if key == 'invoice':
        return True, 'الفاتورة ضمن مستندات الاستيراد التجاري في إرشادات زاتكا.', IMPORT_SOURCE
    if key == 'transport' and profile['mode'] in ('sea', 'air'):
        return True, 'بوليصة الشحن مطلوبة للاستيراد؛ تطابق مع وسيلة النقل المحددة.', IMPORT_SOURCE
    if key == 'origin':
        if profile['origin_marking'] == 'yes':
            return False, 'أكد الموظف وجود دلالة منشأ ثابتة؛ الإرشادات تستثني هذه الحالة من إلزامية شهادة المنشأ.', IMPORT_SOURCE
        if profile['origin_marking'] == 'no':
            return True, 'لا توجد دلالة منشأ ثابتة وفق بيانات المعاملة؛ تطلب شهادة المنشأ.', IMPORT_SOURCE
        return None, 'تحقق من دلالة المنشأ الثابتة قبل تقرير وجوب شهادة المنشأ.', IMPORT_SOURCE
    if key == 'road_transport':
        return None, 'حدد انطباق وثيقة النقل على مسار الشحنة، بما فيه الشحنات الواردة من الإمارات؛ لا يعد بلد الإرسال وحده دليلاً على الإلزام.', ''
    if key == 'packing':
        return None, 'تحقق من حاجة هذه الشحنة إلى قائمة تعبئة بحسب بنود البضاعة ومتطلبات المعاملة.', ''
    if key == 'export_declaration':
        return None, 'تحقق من الحاجة إلى البيان الصادر من بلد الإرسال ومن أن النسخة نهائية.', ''
    return None, 'تحقق من مستند النقل المقبول لهذه الوسيلة وهذه المعاملة.', ''


def requirement_state(required, documents, key=None):
    if required is False:
        return 'not_required'
    if required is None:
        return 'review'
    if not documents:
        return 'missing'
    if any(d.get('reviewed') and d.get('classification_confirmed') and not document_flags(d) and
           not classification_issue(d) and (key is None or d['kind'] == key or key in d.get('covers', [])) for d in documents):
        return 'complete'
    return 'review'


def checklist(documents, context):
    profile = profile_of(context)
    decisions = context.get('decisions', {})
    result = []
    for key, label in REQUIREMENTS.items():
        required, reason, source = automatic_requirement(key, profile)
        decision = decisions.get(key, {})
        if decision:
            if decision.get('profile') == profile:
                required = {'required': True, 'not_required': False, 'review': None}[decision['choice']]
                reason, source = decision['reason'], 'مراجعة الموظف: ' + decision['source']
            else:
                required, reason, source = None, 'تغيرت بيانات الشحنة؛ أعد مراجعة القرار السابق لهذا المستند.', ''
        matches = [d for d in documents if d['kind'] == key or key in d.get('covers', []) or key in detected_kinds(d)
                   or (classification_issue(d) and suggested_kind(d) == key)]
        state = requirement_state(required, matches, key)
        if any(classification_issue(d) for d in matches) and state != 'not_required':
            state = 'review'
            reason += ' يوجد اختلاف بين اسم ملف ونوعه المسجل؛ صحح التصنيف أو أكده بعد مطابقة الأصل.'
        result.append({'key': key, 'label': label, 'required': required, 'reason': reason, 'source': source,
                       'documents': matches, 'state': state})
    for extra in context.get('extras', []):
        matches = [d for d in documents if d['id'] == extra.get('document_id')]
        required = extra['required'] if extra.get('profile') == profile else None
        result.append({'key': extra['id'], 'label': extra['label'], 'required': required,
                       'reason': extra['reason'] if required is not None else 'تغيرت بيانات الشحنة؛ أعد مراجعة هذا المتطلب.',
                       'source': 'مراجعة الموظف: ' + extra['source'], 'documents': matches,
                       'state': requirement_state(required, matches), 'extra': True})
    counts = {state: sum(row['state'] == state for row in result) for state in STATES}
    blockers = []
    if not all(profile[k] for k in ('transaction', 'mode', 'goods', 'dispatch_country')):
        blockers.append('أكمل نوع المعاملة ووسيلة النقل ووصف البضاعة وبلد الإرسال لتحديد المطلوب.')
    if context.get('scope_review', {}).get('profile') != profile:
        blockers.append('راجع اشتراطات البضاعة وأضف كل شهادة أو تصريح مطلوب باسمه، ثم سجل مرجع المراجعة.')
    if any(classification_issue(d) for d in documents):
        blockers.append('صحح اختلافات أسماء الملفات وأنواعها في جدول المستندات المرفوعة.')
    return {'rows': result, 'counts': counts, 'blockers': blockers,
            'complete': bool(result) and not blockers and not counts['missing'] and not counts['review']}
