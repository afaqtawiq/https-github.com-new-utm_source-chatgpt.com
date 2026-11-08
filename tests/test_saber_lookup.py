"""Synthetic public-schema fixtures; no customer data, tokens or live network."""
import asyncio
import html
import httpx
import pytest
from app import saber_lookup as s


def row(code='401110100000', description='- - - إطارات خارجية هوائية جديدة، من مطاط للسيارات السياحية وسيارات الاستيشن'):
    # Public displayed row, rebuilt minimally (not an HTML snapshot).
    values = [code, html.escape(description), 'اللائحة الفنية الخليجية للاطارات',
              '<span>شهادة علامة الجودة (QM)</span><span>أو بطاقة كفاءة الطاقة للإطارات</span>', '']
    return '<tr>' + ''.join(f'<td class="{cls}">{v}</td>' for cls, v in zip(
        ['HSCodeCustoms', 'NameAr', 'NameEn', 'NameEn', 'NameEn'], values)) + '</tr>'


def page(query='إطارات', rows=None, total=1):
    return (f'<input id="Tags" name="Tags" value="{html.escape(query, quote=True)}">'
            f'<span class="table-result">{total}</span><table aria-describedby="saberTable"><tbody><tr>'
            + ''.join(f'<th>{h}</th>' for h in s.HEADERS) + '</tr>'
            + (row() if rows is None else rows) + '</tbody></table>')


def run(body=None, query='إطارات', status=200, headers=None):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, text=page() if body is None else body,
                              headers=headers or {'content-type': 'text/html; charset=utf-8'})
    result = asyncio.run(s.lookup_saber(query, transport=httpx.MockTransport(handler)))
    return result, requests


def test_official_tire_evidence_and_request_boundary():
    r, requests = run()
    assert r['status'] == 'results' and r['retrieved_at']
    assert r['results'][0]['code'] == '401110100000'
    assert r['results'][0]['certificates'] == 'شهادة علامة الجودة (QM) أو بطاقة كفاءة الطاقة للإطارات'
    assert r['results'][0]['match'] == 'official_search_candidate'
    assert r['results'][0]['additional_requirements'] == ''
    assert len(requests) == 1
    req = requests[0]
    assert req.method == 'GET' and req.url.host == 'saber.sa'
    assert req.url.path == '/Home/HSCodes' and dict(req.url.params) == {'Tags': 'إطارات'}
    assert not req.content and 'cookie' not in req.headers and 'authorization' not in req.headers


@pytest.mark.parametrize('query', ['', None, {}, 'a'*51, 'https://evil.test', '<script>', 'wood&Tags=x', 'a@b.com', '+966500000001', '966500000001', '401110100000\n', '999999999999', '12345', '401110', '0500000001', '40111010', 'one two three four five six seven'])
def test_invalid_query_never_network(query):
    r, requests = run(query=query)
    assert r['status'] == 'invalid_query' and requests == []
    assert r['query'] == ''


def test_exact_matching():
    for query, kind in [('401110100000', 'hs_exact')]:
        r, _ = run(page(query), query=query)
        assert r['status'] == 'results' and r['query_kind'] == kind
    r, _ = run(page('401120100000'), query='401120100000')
    assert r['status'] == 'unavailable' and r['reason'] == 'hs_mismatch'


@pytest.mark.parametrize('body', [
    page().replace('الصنف', 'changed'), page().replace('NameAr', 'Changed'),
    page().replace('401110100000', 'abc'), page().replace('</table>', ''),
    page().replace('value="إطارات"', 'value="خشب"'), page().replace('<input', '<other'),
    page().replace('<td class="NameAr">', '<td class="NameAr"><script>bad</script>'),
    page().replace('</tbody>', '<tr><td>x</td></tr></tbody>'),
    page(total=0), page(total=1, rows=''), page() + page(), '<html>login or captcha</html>',
])
def test_schema_drift_is_unavailable(body):
    r, _ = run(body)
    assert r['status'] == 'unavailable' and not r['results']


def test_empty_explicit_search_only():
    r, _ = run('<input id="Tags" name="Tags" value="unknown"><h3>لم يتم العثور على النتائج</h3>', query='unknown')
    assert r['status'] == 'no_results' and r['total_results'] == 0
    assert 'exempt' not in r
    r, _ = run('<input id="Tags" name="Tags" value="unknown">', query='unknown')
    assert r['status'] == 'unavailable'


def test_links_and_escaping_are_plain_text_only():
    body = page(rows=row(description='إطارات <b> & "test"')).replace('شهادة علامة الجودة (QM)', '<a href="https://evil.test/collect">شهادة علامة الجودة (QM)</a>')
    r, requests = run(body)
    assert r['status'] == 'results' and len(requests) == 1
    assert r['results'][0]['description'] == 'إطارات <b> & "test"'
    assert 'evil.test' not in str(r)
    assert '<a' not in r['results'][0]['certificates']


@pytest.mark.parametrize('status', [301, 302, 403, 404, 429, 500])
def test_http_failure_no_retry(status):
    r, requests = run(status=status, headers={'content-type': 'text/html', 'location': 'https://evil.test'})
    assert r['status'] == 'unavailable' and len(requests) == 1


def test_content_type_and_size_caps():
    for body, headers in [(page(), {'content-type':'application/json'}),
                          (page(), {'content-type':'text/html', 'content-length':str(s.MAX_BYTES+1)}),
                          ('x'*(s.MAX_BYTES+1), {'content-type':'text/html'})]:
        r, _ = run(body, headers=headers)
        assert r['status'] == 'unavailable'


def test_timeout_and_network_error():
    for error in [httpx.ReadTimeout('timeout'), httpx.ConnectError('offline')]:
        def handler(request):
            raise error
        r = asyncio.run(s.lookup_saber('إطارات', transport=httpx.MockTransport(handler)))
        assert r['status'] == 'unavailable' and r['reason'] == 'fetch_failed'


def test_rows_and_results_are_bounded():
    rows = ''.join(row(code=str(401110100000+i)) for i in range(25))
    r, _ = run(page(rows=rows, total=200))
    assert r['status'] == 'results' and len(r['results']) == s.MAX_RESULTS and r['truncated']
    r, _ = run(page(rows=''.join(row(code=str(401110100000+i)) for i in range(s.MAX_ROWS+1)), total=200))
    assert r['status'] == 'unavailable' and r['reason'] == 'row_limit'


def test_chunked_size_limit_and_invalid_encoding():
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(10):
                yield b'x' * 60_000
    def handler(request):
        return httpx.Response(200, headers={'content-type':'text/html'}, stream=Chunks())
    r = asyncio.run(s.lookup_saber('tires', transport=httpx.MockTransport(handler)))
    assert r['status'] == 'unavailable' and r['reason'] == 'response_size'
    r = asyncio.run(s.lookup_saber('tires', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type':'text/html'}, content=b'\xff'))))
    assert r['status'] == 'unavailable' and r['reason'] == 'fetch_failed'


def test_alternatives_and_multiple_candidates_are_not_collapsed():
    rows = row() + row('842641000000', 'ـ ـ على إطارات')
    r, _ = run(page(rows=rows, total=2))
    assert r['status'] == 'results' and len(r['results']) == 2
    assert {x['code'] for x in r['results']} == {'401110100000', '842641000000'}
    assert all('أو' in x['certificates'] for x in r['results'])


def test_explicit_self_declaration_evidence_is_not_a_missing_result():
    body = page(query='252520000000', rows=row('252520000000', 'ـ مسحوق ميكا'))
    body = body.replace('اللائحة الفنية الخليجية للاطارات', '-')
    body = body.replace('<span>شهادة علامة الجودة (QM)</span><span>أو بطاقة كفاءة الطاقة للإطارات</span>', '- اقرار ذاتي')
    result, _ = run(body, query='252520000000')
    assert result['status'] == 'results'
    assert result['results'][0]['regulation'] == '-'
    assert result['results'][0]['certificates'] == '- اقرار ذاتي'


@pytest.mark.parametrize('location', [
    'HSCodes?query=syntheticToken/abc+def=',
    '/Home/HSCodes?query=syntheticToken%2Fabc%2Bdef%3D',
    'https://saber.sa/Home/HSCodes?query=syntheticToken=',
    'https://saber.sa:443/home/hscodes?query=synthetic-token_',
])
def test_one_validated_official_redirect_without_cookies(location):
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={'location':location, 'set-cookie':'session=synthetic; Path=/'})
        assert 'cookie' not in request.headers and 'authorization' not in request.headers
        assert request.method == 'GET' and not request.content
        return httpx.Response(200, text=page(), headers={'content-type':'text/html'})
    result = asyncio.run(s.lookup_saber('إطارات', transport=httpx.MockTransport(handler)))
    assert result['status'] == 'results' and len(requests) == 2
    assert result['source_url'].startswith(s.SOURCE_URL + '?Tags=')
    assert 'synthetic' not in str(result)


@pytest.mark.parametrize('location', [
    'https://evil.test/Home/HSCodes?query=abc',
    '//evil.test/Home/HSCodes?query=abc',
    'http://saber.sa/Home/HSCodes?query=abc',
    'https://saber.sa:444/Home/HSCodes?query=abc',
    '/Home/Login?query=abc', '/Home/HSCodes?auth=abc',
    '/Home/HSCodes?query=abc&auth=secret', '/Home/HSCodes?query=abc&query=def',
    'https://user:secret@saber.sa/Home/HSCodes?query=abc',
    '/Home/HSCodes?query=abc#fragment', '/Home/HSCodes?query=abc#',
    '/Home/HSCodes?query=', '/Home/HSCodes?query=' + 'a'*513,
    '/Home/HSCodes?query=abc%0A', '/Home/HSCodes?query=abc%26auth%3Dsecret',
    '/Home/HSCodes?query=abc%2526auth', '/Home/HSCodes?query=abc\\def',
    '/Home/HSCodes?query=abc def', '/Home/HSCodes?Tags=tires', '',
])
def test_unsafe_redirects_fail_without_second_request(location):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={'location':location})
    result = asyncio.run(s.lookup_saber('إطارات', transport=httpx.MockTransport(handler)))
    assert result['status'] == 'unavailable' and len(calls) == 1


def test_second_redirect_not_followed():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={'location':'HSCodes?query=synthetic'})
    result = asyncio.run(s.lookup_saber('إطارات', transport=httpx.MockTransport(handler)))
    assert result['status'] == 'unavailable' and len(calls) == 2


def test_redirect_still_requires_original_query_reflection_and_size_limit():
    for text in [page(query='wood'), 'x' * (s.MAX_BYTES + 1)]:
        calls = []
        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(302, headers={'location':'HSCodes?query=synthetic'})
            return httpx.Response(200, text=text, headers={'content-type':'text/html'})
        result = asyncio.run(s.lookup_saber('إطارات', transport=httpx.MockTransport(handler)))
        assert result['status'] == 'unavailable' and len(calls) == 2
