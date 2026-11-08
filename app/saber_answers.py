"""Public-vocabulary gate and deterministic rendering for official SABER evidence."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import re
import threading
from urllib.parse import parse_qs, urlsplit

from app.saber_lookup import SOURCE_URL, lookup_saber, normalize_query

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='saber-vocabulary')
_SLOTS = threading.BoundedSemaphore(2)
_WORD = re.compile(r'[A-Za-z\u0621-\u063a\u0641-\u064a\u066e-\u06d3]+')
MAX_CHARS = 1400


def _words(text):
    text = re.sub(r'[\u064b-\u065f\u0670ـ]', '', str(text or ''))
    return _WORD.findall(text)


def _norm(word):
    return word.casefold().translate(str.maketrans('أإآ', 'ااا'))


def _public_query(query):
    from app import tariff_lookup
    numeric = query.isascii() and query.isdigit()
    entries = tariff_lookup.search_many([query], [], limit=12)
    wanted = [_norm(w) for w in _words(query)]
    for entry in entries:
        if numeric:
            if str(entry.get('code', '')) == query:
                return str(entry['code'])
            continue
        for field in ('desc_ar', 'desc_en', 'context_ar', 'context_en'):
            words = _words(entry.get(field, ''))
            normalized = [_norm(w) for w in words]
            for i in range(len(words) - len(wanted) + 1):
                if wanted and normalized[i:i + len(wanted)] == wanted:
                    public = ' '.join(words[i:i + len(wanted)])
                    if normalize_query(public) is not None:
                        return public
    return None


def _unverified(reason):
    return {'status': 'unavailable', 'reason': reason, 'results': [],
            'source_url': SOURCE_URL, 'query': '', 'retrieved_at': None}


async def search_product(query):
    """Never contact SABER until the query is reconstructed from public tariff data."""
    query = normalize_query(query)
    if query is None:
        return _unverified('invalid_query')
    if not _SLOTS.acquire(blocking=False):
        return _unverified('local_vocabulary_busy')
    try:
        future = _POOL.submit(_public_query, query)
    except Exception:
        _SLOTS.release()
        return _unverified('local_vocabulary_unavailable')
    future.add_done_callback(lambda _: _SLOTS.release())
    try:
        public = await asyncio.wait_for(asyncio.wrap_future(future), timeout=3)
    except Exception:
        return _unverified('local_vocabulary_unavailable')
    if public is None:
        return _unverified('query_not_in_public_vocabulary')
    return await lookup_saber(public)


def _source(evidence):
    source = evidence.get('source_url', '')
    if source == SOURCE_URL:
        return source
    try:
        parsed = urlsplit(source)
        params = parse_qs(parsed.query, strict_parsing=True)
        if (parsed.scheme == 'https' and parsed.netloc == 'saber.sa'
                and parsed.path == '/Home/HSCodes' and not parsed.fragment
                and set(params) == {'Tags'} and len(params['Tags']) == 1
                and normalize_query(params['Tags'][0]) is not None):
            return source
    except (TypeError, ValueError):
        pass
    return SOURCE_URL


def render_answer(evidence, question=''):
    """Quote complete official fields, never model-generated conformity claims."""
    source = _source(evidence)
    fallback = ('نتيجة سابر تحتاج مراجعة تفاصيل المنتج؛ لا أؤكد تصنيفًا أو إعفاءً. '
                'يراجع فريق التخليص الفئات والمتطلبات كاملة. المصدر الرسمي: ' + source)
    if len(fallback) > MAX_CHARS:
        fallback = 'تعذر عرض التفاصيل كاملة؛ يلزم التحقق من الفئة والمتطلبات. المصدر الرسمي: ' + SOURCE_URL
    if evidence.get('status') != 'results' or not evidence.get('results'):
        return 'لم أتمكن من التحقق من متطلبات المنتج في سابر؛ لا أؤكد شهادة أو إعفاءً. المصدر: ' + SOURCE_URL
    rows = evidence['results']
    exact = evidence.get('query_kind') == 'hs_exact'
    if exact:
        rows = [r for r in rows if r.get('code') == evidence.get('query')]
        if len(rows) != 1:
            return fallback
    else:
        tokens = {_norm(w) for w in _words(question)}
        rows = sorted(rows, key=lambda r: (-len(tokens & {_norm(w) for w in _words(r.get('description', ''))}), str(r.get('code', ''))))[:3]
    lines = ['نتيجة دليل سابر الحالية؛ يلزم مطابقة الوصف بمواصفات المنتج.' if exact
             else 'فئات مرشحة من دليل سابر، وليست تصنيفًا نهائيًا لبضاعتك:']
    for row in rows:
        if (not re.fullmatch(r'[0-9]{12}', str(row.get('code', '')))
                or any(not isinstance(row.get(k), str) or not row[k].strip()
                       for k in ('description', 'regulation', 'certificates'))):
            return fallback
        fields = [row['description'], row['regulation'], row['certificates'], row.get('additional_requirements', '')]
        # Never turn catalogue prose containing arbitrary links into outbound links.
        if any(not isinstance(v, str) or re.search(r'https?://|[\x00-\x08\x0b-\x1f]', v) for v in fields):
            return fallback
        lines += [f"البند {'المبحوث' if exact else 'المرشح'} {row['code']}: {row['description']}",
                  'اللائحة: ' + row['regulation'], 'الشهادات المطلوبة: ' + row['certificates']]
        if row.get('additional_requirements', '').strip():
            lines.append('متطلبات إضافية: ' + row['additional_requirements'])
    if not exact and (evidence.get('truncated') or len(evidence['results']) > len(rows)):
        lines.append('هذه بعض النتائج فقط؛ قد توجد فئات أخرى.')
    lines.append('شهادة الإرسالية خطوة منفصلة للمنتجات ضمن نطاق سابر؛ هذه نتيجة دليل وليست إصدار شهادة.')
    timestamp = str(evidence.get('retrieved_at') or '')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}T[0-9:.+Z-]+', timestamp):
        lines.append('وقت التحقق (UTC): ' + timestamp)
    lines += ['المصدر: ' + source, 'ما استخدام المنتج ومواصفاته لتحديد الفئة المناسبة؟']
    answer = '\n'.join(lines)
    return answer if len(answer) <= MAX_CHARS else fallback
