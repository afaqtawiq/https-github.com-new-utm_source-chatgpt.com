"""Owner inquiry wording and deterministic, reference-free reply correlation."""
import re

OWNER_INQUIRY_TEMPLATE = 'afaaq_transport_owner_inquiry_v4_ar'


def inquiry(origin, destination):
    """Current real-owner body; changed branding needs its own approved v4."""
    return legacy_v2_inquiry(origin, destination).replace(
        'السلام عليكم، معك آفاق طويق للنقل والخدمات اللوجستية.',
        'السلام عليكم، معك آفاق طويق للتخليص الجمركي والنقل.', 1)


def legacy_v2_inquiry(origin, destination):
    """Preserve the existing v2 registration payload without changing its body."""
    return ('السلام عليكم، معك آفاق طويق للنقل والخدمات اللوجستية.\n\n'
            f'بخصوص الحمولة من {origin} إلى {destination}، هل ما زالت متاحة؟\n\n'
            'نرجو توضيح:\n'
            f'• موقع التحميل في {origin}: هل داخل الميناء أم خارجه؟\n'
            f'• موقع التنزيل في {destination}.\n'
            '• نوع البضاعة ووزنها الفعلي ونوع الشاحنة المطلوبة.\n'
            '• موعد التحميل.\n'
            '• السعر المعروض للنقل وطريقة وموعد الدفع.\n\n'
            'للتواصل مع آفاق طويق عبر واتساب فقط:\n'
            '+966530130435')


def short_inquiry(origin, destination):
    """Preserve the separately reviewed short/test template wording."""
    return (f'السلام عليكم، معك آفاق طويق. بخصوص حمولة {origin} إلى {destination}: '
            'كم السعر؟ وما طريقة الدفع؟ والتحميل من داخل الميناء أم خارجه؟')


def _normalized(value):
    value = re.sub('[أإآ]', 'ا', str(value or '')).replace('ى', 'ي')
    return re.sub(r'\s+', ' ', value).strip()


def quoted_receipt(payload):
    """Zernio resolves Meta's quote perspective to the stored platform ID.

    The top-level signed webhook metadata is authoritative. Do not confuse the
    internal quotedMessage.messageId or current inbound ID with a sent receipt.
    Empty string means a quote was present but unusable, which fails closed.
    """
    metadata = payload.get('metadata') or {}
    if not isinstance(metadata, dict):
        return ''
    if 'quotedMessage' not in metadata and 'quotedMessageId' not in metadata:
        return None
    resolved = metadata.get('quotedMessage') or {}
    value = resolved.get('platformMessageId') if isinstance(resolved, dict) else None
    value = value or metadata.get('quotedMessageId')
    return value if isinstance(value, str) and 0 < len(value) <= 512 else ''


def select_pending(pending, text, quoted_message_id=None):
    """Only pending rows already scoped to the verified owner/account are eligible.

    Explicit stale/conflicting identifiers fail closed. Never select the newest
    row. The caller rechecks this selection under a lock before advancing it.
    """
    candidates = list(pending)
    if quoted_message_id is not None and not quoted_message_id:
        return None
    refs = set(re.findall(r'(?<!\w)(?:NQ-\d+|WA-[A-F0-9]{12})(?!\w)', str(text).upper()))
    if len(refs) > 1:
        return None
    if refs:
        candidates = [x for x in candidates if x['reference'].upper() in refs]
    if quoted_message_id is not None:
        candidates = [x for x in candidates if x.get('provider_message_id') == quoted_message_id]
    normalized = _normalized(text)
    route_markers = re.findall(r'(?<!\w)الي(?!\w)|→|->', normalized)
    matching = []
    for item in candidates:
        origin, destination = _normalized(item.get('origin')), _normalized(item.get('destination'))
        if origin and destination and re.search(
                r'(?<!\w)' + re.escape(origin) + r'\s*(?:الي|→|->|[-–])\s*' + re.escape(destination) + r'(?!\w)', normalized):
            matching.append(item)
    # A supplied route must agree even with a single pending row or a quote.
    # Contradictory/multiple routes are never reduced to the newest candidate.
    if route_markers or matching:
        if len(route_markers) > 1:
            return None
        return matching[0] if len(matching) == 1 else None
    return candidates[0] if len(candidates) == 1 else None



def clarification(pending):
    routes = list(dict.fromkeys(str(x.get('origin') or '') + ' إلى ' + str(x.get('destination') or '') for x in pending))
    if len(pending) == 1:
        return 'لم أستطع ربط الرد برسالة الاستفسار. تقصد حمولة ' + routes[0] + '؟ أرسل المسار مع التفاصيل، أو رد مباشرة على رسالة الاستفسار الخاصة بها.'
    if len(routes) > 1:
        return 'تقصد أي حمولة: ' + '، أم '.join(routes) + '؟ أرسل المسار مع التفاصيل، أو رد مباشرة على رسالة الاستفسار الخاصة بها.'
    return 'لدينا أكثر من حمولة على هذا المسار. رد مباشرة على رسالة الاستفسار الخاصة بالحمولة المقصودة حتى نربط ردك بها.'


def loading_port_status(text):
    """Do not infer a port location from missing, negated, or conflicting terms."""
    values = set()
    for clause in re.split(r'[\n،;.]', str(text)):
        if re.search(r'[؟?]|ليس|ليست|مو\s|غير\s|لا\s|(?<!\w)(?:أو|او|أم|ام)(?!\w)', clause):
            continue
        if re.search(r'التنزيل|التسليم|الوصول', clause):
            continue
        if not re.search(r'التحميل', clause) and not re.fullmatch(
                r'\s*(?:من\s+)?(?:داخل|خارج)\s+(?:ال)?ميناء\s*', clause):
            continue
        inside = bool(re.search(r'داخل\s+(?:ال)?ميناء', clause))
        outside = bool(re.search(r'خارج\s+(?:ال)?ميناء', clause))
        if inside != outside:
            values.add('inside' if inside else 'outside')
    return next(iter(values)) if len(values) == 1 else None
