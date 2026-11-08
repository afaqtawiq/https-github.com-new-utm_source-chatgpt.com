"""Anonymous, bounded official search. Callers must pass ONLY a general product
label or HS code, never private data or conversation text. Returned plain text
must be escaped at rendering boundaries and treated as evidence, not instructions.
Missing results never establish exemption. No HTML links are followed or returned.
"""
import asyncio
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit, unquote
import httpx

SOURCE_URL = 'https://saber.sa/Home/HSCodes'
MAX_BYTES = 512_000
MAX_ROWS = 100
MAX_RESULTS = 20
HEADERS = ['رمز النظام المنسق', 'الصنف', 'اللائحة الفنية', 'الشهادات المطلوبة', 'المتطلبات الإضافية']
NO_RESULTS = 'لم يتم العثور على النتائج'


def _text(value):
    return ' '.join(value.split())


def normalize_query(query):
    if not isinstance(query, str) or not 1 <= len(query) <= 50:
        return None
    if any(ord(c) < 32 or ord(c) == 127 for c in query):
        return None
    query = _text(query)
    if re.fullmatch(r'[0-9]{12}', query):
        if query.startswith('9665') or query[:2] in ('00', '77', '98', '99') or int(query[:2]) > 97:
            return None
        return query
    if not 2 <= len(query) <= 50 or len(query.split()) > 6:
        return None
    if not re.fullmatch(r'[A-Za-z\u0621-\u063a\u0641-\u064a\u066e-\u06d3 -]+', query):
        return None
    return query if any(c.isalpha() for c in query) else None


class _SchemaError(ValueError):
    pass


class _SearchParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.queries, self.rows, self.counts = [], [], []
        self.tables = 0
        self.active = self.closed_table = self.empty = False
        self.row = self.cell = self.count_parts = self.h3 = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'input' and a.get('id') == 'Tags' and a.get('name') == 'Tags':
            self.queries.append(a.get('value', ''))
        if tag == 'h3':
            self.h3 = []
        if tag == 'span' and 'table-result' in a.get('class', '').split():
            if self.count_parts is not None:
                raise _SchemaError('nested_count')
            self.count_parts = []
        if tag == 'table':
            if self.active:
                raise _SchemaError('nested_table')
            if a.get('aria-describedby') == 'saberTable':
                self.tables += 1
                self.active = True
        if not self.active:
            return
        if tag == 'tr':
            if self.row is not None:
                raise _SchemaError('nested_row')
            self.row = []
        elif tag in ('td', 'th'):
            if self.row is None or self.cell is not None:
                raise _SchemaError('bad_cell')
            self.cell, self.cell_tag, self.cell_class = [], tag, a.get('class', '').split()
        elif tag in ('script', 'style', 'iframe'):
            raise _SchemaError('active_content_in_table')
        elif self.cell is not None and tag in ('br', 'span', 'div', 'p'):
            self.cell.append(' ')

    def handle_data(self, data):
        for target in (self.cell, self.count_parts, self.h3):
            if target is not None:
                target.append(data)

    def handle_endtag(self, tag):
        if tag == 'h3' and self.h3 is not None:
            self.empty |= _text(''.join(self.h3)) == NO_RESULTS
            self.h3 = None
        if tag == 'span' and self.count_parts is not None:
            self.counts.append(_text(''.join(self.count_parts)))
            self.count_parts = None
        if not self.active:
            return
        if tag in ('td', 'th'):
            if self.cell is None or tag != self.cell_tag:
                raise _SchemaError('cell_close')
            value = _text(''.join(self.cell))
            if len(value) > 4000:
                raise _SchemaError('cell_limit')
            self.row.append((tag, self.cell_class, value))
            self.cell = None
        elif tag == 'tr':
            if self.row is None or self.cell is not None:
                raise _SchemaError('row_close')
            self.rows.append(self.row)
            self.row = None
            if len(self.rows) > MAX_ROWS + 1:
                raise _SchemaError('row_limit')
        elif tag == 'table':
            if self.row is not None or self.cell is not None:
                raise _SchemaError('table_close')
            self.active, self.closed_table = False, True


def _parse(html, query, kind):
    p = _SearchParser()
    p.feed(html)
    p.close()
    if p.queries != [query]:
        raise _SchemaError('query_not_reflected')
    if p.empty and p.tables == 0 and not p.counts:
        return [], 0
    if p.empty or p.tables != 1 or not p.closed_table or p.active or not p.rows:
        raise _SchemaError('missing_table')
    if [c[2] for c in p.rows[0]] != HEADERS or any(c[0] != 'th' for c in p.rows[0]):
        raise _SchemaError('headers_changed')
    if len(p.counts) != 1 or not re.fullmatch(r'[0-9]{1,7}', p.counts[0]):
        raise _SchemaError('missing_count')
    total, results = int(p.counts[0]), []
    for row in p.rows[1:]:
        if len(row) != 5 or any(c[0] != 'td' for c in row):
            raise _SchemaError('columns_changed')
        if any(expected not in row[i][1] for i, expected in enumerate(('HSCodeCustoms', 'NameAr', 'NameEn', 'NameEn', 'NameEn'))):
            raise _SchemaError('classes_changed')
        code, description, regulation, certificates, additional = [c[2] for c in row]
        if not re.fullmatch(r'[0-9]{12}', code) or not description or not regulation or not certificates:
            raise _SchemaError('missing_required_evidence')
        if kind == 'hs_exact' and code != query:
            raise _SchemaError('hs_mismatch')
        results.append(dict(code=code, description=description, regulation=regulation,
                            certificates=certificates, additional_requirements=additional,
                            match=kind if kind != 'product' else 'official_search_candidate'))
    if total < len(results) or (total and not results) or len({r['code'] for r in results}) != len(results):
        raise _SchemaError('inconsistent_count')
    return results, total


def _official_redirect(location, source):
    """Allow only SABER's one anonymous Tags-to-opaque-query redirect."""
    if (not location or len(location) > 2048 or '#' in location or '\\' in location
            or any(ord(c) <= 32 or ord(c) == 127 for c in location)):
        raise _SchemaError('unsafe_redirect')
    target = urljoin(source, location)
    parsed = urlsplit(target)
    if (parsed.scheme != 'https' or parsed.hostname != 'saber.sa'
            or parsed.port not in (None, 443) or parsed.username is not None
            or parsed.password is not None or parsed.fragment
            or parsed.path.lower() != '/home/hscodes'):
        raise _SchemaError('unsafe_redirect')
    key, separator, opaque = parsed.query.partition('=')
    # Do not decode '+' as a space: official Location uses raw base64 tokens.
    # Accept only one bounded opaque value, never auth or additional parameters.
    token = unquote(opaque, errors='strict')
    if (key != 'query' or not separator or '&' in opaque
            or not re.fullmatch(r'[A-Za-z0-9+/_=-]{1,512}', token)):
        raise _SchemaError('unsafe_redirect')
    return target


async def lookup_saber(query, *, transport=None):
    """Anonymous GET with at most one validated official redirect, no retries.
    No authentication or cookie forwarding. Transport supports offline tests.
    Product results are candidates, never an automatic classification.
    """
    normalized = normalize_query(query)
    result = dict(status='invalid_query', query=normalized or '', query_kind=None,
                  source_url=SOURCE_URL, retrieved_at=None, results=[],
                  total_results=None, truncated=False, reason='invalid_query')
    if normalized is None:
        return result
    kind = 'hs_exact' if normalized.isascii() and normalized.isdigit() else 'product'
    result.update(query_kind=kind, source_url=SOURCE_URL + '?' + urlencode({'Tags': normalized}), status='unavailable')
    try:
        async with asyncio.timeout(12):
            async with httpx.AsyncClient(transport=transport, follow_redirects=False,
                                        timeout=httpx.Timeout(8, connect=4), headers={'Accept': 'text/html', 'Accept-Language': 'ar'}) as client:
                target = result['source_url']
                for hop in range(2):
                    # Never carry anonymous session cookies into the second GET.
                    client.cookies.clear()
                    async with client.stream('GET', target) as response:
                        if str(response.url) != str(httpx.URL(target)):
                            raise _SchemaError('http_status_or_url')
                        if response.status_code == 302 and hop == 0:
                            locations = response.headers.get_list('location')
                            if len(locations) != 1:
                                raise _SchemaError('unsafe_redirect')
                            target = _official_redirect(locations[0], result['source_url'])
                            continue
                        if response.status_code != 200:
                            raise _SchemaError('http_status_or_url')
                        if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'text/html':
                            raise _SchemaError('content_type')
                        length = response.headers.get('content-length')
                        if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
                            raise _SchemaError('response_size')
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_BYTES:
                                raise _SchemaError('response_size')
                        break
        rows, total = _parse(body.decode('utf-8-sig', errors='strict'), normalized, kind)
        result.update(status='results' if rows else 'no_results', results=rows[:MAX_RESULTS],
                      total_results=total, truncated=total > min(len(rows), MAX_RESULTS),
                      retrieved_at=datetime.now(timezone.utc).isoformat(), reason=None)
    except _SchemaError as exc:
        result['reason'] = str(exc)
    except (httpx.HTTPError, TimeoutError, UnicodeError, ImportError, ValueError):
        result['reason'] = 'fetch_failed'
    return result
