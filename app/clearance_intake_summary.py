"""Advisory, in-memory overview of a request before a clearance case exists."""
import re
from datetime import datetime, timedelta, timezone
from html import escape

# Deliberately limit displayed values to names/categories we recognize. Unknown
# phrases stay for staff review, rather than echoing identifiers from customer text.
_MOVEMENTS = {
    'import': ('استيراد', 'وارد', 'وارده', 'import'),
    'export': ('تصدير', 'صادر', 'صادره', 'export', 'اعاده تصدير', 're-export', 'reexport'),
    'transit': ('ترانزيت', 'عبور', 'transit'),
}
_PORTS = {
    'ميناء جدة الإسلامي': ('ميناء جده الاسلامي', 'jeddah islamic port'),
    'ميناء جدة': ('ميناء جده', 'jeddah port'),
    'ميناء الملك عبدالعزيز بالدمام': ('ميناء الدمام', 'ميناء الملك عبدالعزيز', 'ميناء الملك عبد العزيز', 'dammam port', 'king abdulaziz port'),
    'ميناء الملك عبدالله': ('ميناء الملك عبدالله', 'ميناء الملك عبد الله', 'king abdullah port'),
    'ميناء الجبيل': ('ميناء الجبيل', 'jubail port'),
    'ميناء ينبع': ('ميناء ينبع', 'yanbu port'),
    'ميناء جازان': ('ميناء جازان', 'jazan port'),
    'مطار الملك خالد': ('مطار الملك خالد', 'مطار الرياض', 'riyadh airport', 'king khalid airport'),
    'مطار الملك عبدالعزيز': ('مطار الملك عبدالعزيز', 'مطار الملك عبد العزيز', 'مطار جده', 'jeddah airport'),
    'مطار الملك فهد': ('مطار الملك فهد', 'مطار الدمام', 'dammam airport'),
    'منفذ البطحاء': ('منفذ البطحاء', 'جمرك البطحاء', 'al batha border'),
    'منفذ الحديثة': ('منفذ الحديثه', 'جمرك الحديثه', 'al haditha border'),
    'منفذ سلوى': ('منفذ سلوي', 'جمرك سلوي', 'salwa border'),
    'منفذ الوديعة': ('منفذ الوديعه', 'جمرك الوديعه', 'al wadiah border'),
    'منفذ جسر الملك فهد': ('جسر الملك فهد', 'king fahd causeway'),
}
_GOODS = {
    'مواد غذائية': ('مواد غذائيه', 'منتجات غذائيه', 'اغذيه', 'food products', 'foodstuffs'),
    'ملابس': ('ملابس', 'الملابس', 'clothing', 'garments'),
    'أثاث': ('اثاث', 'الاثاث', 'furniture'),
    'إلكترونيات': ('الكترونيات', 'اجهزه الكترونيه', 'electronics'),
    'قطع غيار': ('قطع غيار', 'spare parts'),
    'معدات': ('معدات', 'machinery', 'equipment'),
    'مستحضرات تجميل': ('مستحضرات تجميل', 'cosmetics'),
}
_LABELS = {'import': 'استيراد', 'export': 'تصدير', 'transit': 'ترانزيت'}
_REQUEST = re.compile(
    r'\b(?:ابغي|ابغى|ابي|اريد|عايز|عايزين|محتاج|محتاجين|نحتاج|نريد|طلب|نطلب|احتاج)\s+(?:الي\s+)?(?:خدمه\s+)?(?:تخليص|مخلص)\b'
    r'|\b(?:need|require|request|seeking|looking for)\s+(?:a\s+)?(?:customs clearance|customs broker)\b')
_NEW = re.compile(r'\b(?:شحنه جديده|شحنه اخري|طلب جديد|موضوع جديد|موضوع اخر|new shipment|different shipment|new request)\b')
_UNCERTAIN = re.compile(r'\b(?:هل|كم|كيف|ليس|ليست|مو|مش|بدون|غير محدد|يمكن|ربما|او|maybe|not|instead|or)\b|[?؟]')
_CORRECTION = re.compile(r'^(?:تصحيح|اقصد|الصحيح|correction|i mean)\b[:،,\s]*')
_OTHER_TOPIC = re.compile(r'^(?:كيف|هل|وين|اين|كم|استفسار عن|where|how|what|when)\b')
_DRIVER_CONTACT = re.compile(
    r'\b(?:رقم\s+(?:الجوال|جوال|هاتف)\s+(?:السائق|السايق)|رقم\s+(?:السائق|السايق)|'
    r'(?:السائق|السايق)\s+(?:ما\s+عندي\s+رقمه|رقمه)|(?:driver|courier).{0,15}(?:phone|mobile|contact))\b')
_AGE = timedelta(hours=72)


def _fold(value):
    value = re.sub(r'[\u064b-\u065f\u0670ـ]', '', value.lower())
    return ' '.join(value.translate(str.maketrans('أإآىة', 'ااايه')).split())


def _matching(text, names):
    return {key for key, aliases in names.items()
            if any(re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', text) for alias in aliases)}


def _time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, OverflowError):
        return None


def build(messages, participant, phone, *, now=None):
    """Latest inbound verified participant only. Input already scoped to one thread.

    Incomplete evidence is marked uncovered, never inferred from templates,
    staff replies, attachments, phone suffixes, or previous topics.
    """
    now = now or datetime.now(timezone.utc)
    incoming = []
    for m in messages[:40]:
        if (m.get('direction') != 'incoming' or not participant
                or phone(m.get('senderId')) != participant):
            continue
        when = _time(m.get('createdAt'))
        value = m.get('message')
        if when is None or not now - _AGE <= when <= now + timedelta(minutes=5):
            continue
        if m.get('attachments'):
            # Do not infer from a caption, file name, or attachment content.
            incoming.append((when, None))
        elif isinstance(value, str) and 0 < len(value) <= 800:
            incoming.append((when, _fold(value)))
    incoming.sort(key=lambda item: item[0])  # stable; reject ambiguous equal-time anchors below
    if not incoming:
        return None
    active = False
    attachment_needs_review = False
    known = {key: set() for key in ('movement', 'port', 'goods', 'entry', 'exit')}
    for index, (when, value) in enumerate(incoming):
        if value is None:
            attachment_needs_review = attachment_needs_review or active
            continue
        starts_request = bool(_REQUEST.search(value))
        if _DRIVER_CONTACT.search(value):
            active = False
            continue
        if _NEW.search(value) or starts_request:
            active = starts_request
            attachment_needs_review = False
            known = {key: set() for key in known}
        elif _OTHER_TOPIC.search(value):
            active = False
        if not active:
            continue
        if ((index > 0 and when == incoming[index - 1][0]) or
                (index + 1 < len(incoming) and when == incoming[index + 1][0])):
            return None
        correction = _CORRECTION.match(value)
        for clause in re.split(r'[،,؛;.!]+', value):
            if _UNCERTAIN.search(clause):
                continue
            for key, aliases in (('movement', _MOVEMENTS), ('port', _PORTS), ('goods', _GOODS)):
                values = _matching(clause, aliases)
                if values:
                    if correction:
                        known[key] = values
                    else:
                        known[key].update(values)
            segments = re.split(r'(?<!\w)(?:و)?(الدخول|دخول|الخروج|خروج|entry|exit)\b', clause)
            for marker, tail in zip(segments[1::2], segments[2::2]):
                key = 'entry' if marker in ('الدخول', 'دخول', 'entry') else 'exit'
                matches = _matching(tail, _PORTS)
                if matches:
                    if correction:
                        known[key] = matches
                    else:
                        known[key].update(matches)
    if not active:
        return None
    for key in ('port', 'entry', 'exit'):
        if 'ميناء جدة الإسلامي' in known[key]:
            known[key].discard('ميناء جدة')
    movement = next(iter(known['movement'])) if len(known['movement']) == 1 else ''
    # Two names alone do not establish entry/exit direction for transit.
    entry = next(iter(known['entry'])) if len(known['entry']) == 1 else ''
    exit_port = next(iter(known['exit'])) if len(known['exit']) == 1 else ''
    port = next(iter(known['port'])) if len(known['port']) == 1 else ''
    if movement == 'transit':
        port = f'دخول: {entry}، خروج: {exit_port}' if entry and exit_port and entry != exit_port else ''
    goods = next(iter(known['goods'])) if len(known['goods']) == 1 else ''
    port_view = port
    if movement == 'transit' and not port and entry != exit_port:
        port_view = (f'دخول: {entry}؛ الخروج غير واضح' if entry else f'خروج: {exit_port}؛ الدخول غير واضح')
    values = {'الإجراء': _LABELS.get(movement, ''), 'المنفذ': port_view, 'البضاعة': goods}
    questions = (
        (not movement, 'هل الطلب استيراد إلى السعودية، تصدير منها، أم ترانزيت؟'),
        (not port, ('ما منفذ الخروج في الترانزيت؟' if entry and not exit_port else
                    'ما منفذ الدخول في الترانزيت؟' if exit_port and not entry else
                    'ما منفذا الدخول والخروج في الترانزيت؟') if movement == 'transit'
         else 'ما اسم المنفذ الجمركي لهذه الشحنة؟'),
        (not goods, 'ما نوع البضاعة؟'),
    )
    question = next((prompt for missing, prompt in questions if missing), '')
    return values, question, bool(question and attachment_needs_review)


def panel(summary):
    if summary is None:
        return ''
    values, question, attachment_needs_review = summary
    detail = ''.join('<dt>' + escape(key) + '</dt><dd>' +
                     escape(value or 'غير واضح في الرسائل') + '</dd>' for key, value in values.items())
    step = ('<p><strong>الخطوة التالية:</strong> تأكد أن المعلومة لم ترد في مرفق أو رسالة أقدم، '
            'ثم راجع السؤال المقترح:</p><label>سؤال واحد للنسخ<textarea readonly rows="2">'
            + escape(question) + '</textarea></label>' if question else
            '<p><strong>الخطوة التالية:</strong> راجع ملخص الطلب مع موظف التخليص لتحديد المستند التالي. '
            'اكتمال المعلومات الأولية لا يعني جاهزية المعاملة أو صدور عرض سعر.</p>')
    if attachment_needs_review:
        step = ('<p><strong>الخطوة التالية:</strong> راجع المرفق قبل سؤال العميل؛ '
                'قد تجد فيه التفاصيل الناقصة. لم يقرأ الملخص محتوى المرفق.</p>')
    return ('<article aria-labelledby="clearance-intake-title"><h3 id="clearance-intake-title">ملخص طلب التخليص</h3>'
            '<small>اقتراح داخلي من رسائل العميل النصية الحديثة، وليس تحققًا من مستنداته. '
            'لا يحفظ أو يرسل شيئًا.</small><dl>' + detail + '</dl>' + step + '</article>')
