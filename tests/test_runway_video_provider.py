"""Fixture-only Runway video tests. No credential reads or live paid requests."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from app import runway_video_provider as r

KEY = 'fixture-runway-key-never-live'
TASK = '17f20503-6c24-4c16-946b-35dbbce2af2f'
OTHER_TASK = '355e42da-b3f9-4b65-9be2-fb10bda026fc'
URL = 'https://dnznrvs05pmza.cloudfront.net/test/output.mp4?_jwt=fixture-token'
PROMPT = 'شاحنة تسير على الطريق عند الفجر'
FTYP = b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomavc1'


@pytest.fixture(autouse=True)
def transport(monkeypatch):
    """Every HTTP call must use an explicit per-test fixture handler."""
    state = SimpleNamespace(calls=[], clients=[], handler=None)
    original = httpx.Client

    def dispatch(request):
        state.calls.append(request)
        assert state.handler is not None, 'Unexpected/unmocked HTTP request'
        return state.handler(request)

    def client(**kwargs):
        state.clients.append(kwargs)
        assert kwargs == {'timeout': 30, 'follow_redirects': False, 'trust_env': False}
        return original(transport=httpx.MockTransport(dispatch), **kwargs)

    monkeypatch.setattr(r.httpx, 'Client', client)
    return state


def receipt(estimate=60):
    return {'id': TASK, 'estimatedCost': {'credits': estimate}}


def task(status='SUCCEEDED', **updates):
    result = {'id': TASK, 'status': status, 'cost': {'credits': 60},
              'output': [URL], 'failure': KEY + ' private-provider-detail',
              'failureCode': '<script>private-provider-detail</script>'}
    result.update(updates)
    return result


def test_fixed_submission_and_published_estimate(transport):
    transport.handler = lambda request: httpx.Response(200, json=receipt())
    result = r.submit(KEY, PROMPT)
    assert result == {'task_id': TASK, 'estimated_credits': Decimal(60)}
    assert (r.MODEL, r.DURATION, r.RATIO, r.ESTIMATED_CREDITS, r.MAX_EXPORT) == (
        'gen4.5', 5, '720:1280', 60, 14 * 1024 * 1024)
    assert r.PRICING_URL == 'https://docs.dev.runwayml.com/guides/pricing/'
    assert len(transport.calls) == 1
    request = transport.calls[0]
    assert request.method == 'POST'
    assert str(request.url) == 'https://api.dev.runwayml.com/v1/text_to_video'
    assert request.headers['authorization'] == 'Bearer ' + KEY
    assert request.headers['x-runway-version'] == '2024-11-06'
    assert json.loads(request.content) == {
        'model': 'gen4.5', 'promptText': PROMPT, 'duration': 5,
        'ratio': '720:1280', 'outputFormat': 'mp4'}
    assert 'cookie' not in request.headers


@pytest.mark.parametrize('prompt', ['a', 'a' * 1000, '🚚' * 500, 'وصف ' + '🚚' * 498])
def test_prompt_utf16_valid_boundary(prompt):
    assert r.validate_prompt(prompt) == prompt


@pytest.mark.parametrize('prompt', [None, 5, True, {}, [], '', '  \n', 'a' * 1001,
                                   '🚚' * 501, 'a' + '🚚' * 500, '\ud800', '\udfff'])
def test_bad_prompt_rejected_before_transport(transport, prompt):
    with pytest.raises(r.RunwayError):
        r.submit(KEY, prompt)
    assert not transport.calls


@pytest.mark.parametrize('estimate,expected', [(0, Decimal(0)), (60, Decimal(60)),
    (61, Decimal(61)), (120.5, Decimal('120.5')), (9007199254740991, Decimal('9007199254740991')),
    (None, None), (True, None), (False, None), ('60', None), (-1, None), ({}, None),
    ([], None), (10**20, None)])
def test_preserve_receipt_for_all_estimates(transport, estimate, expected):
    transport.handler = lambda request: httpx.Response(200, json=receipt(estimate))
    assert r.submit(KEY, PROMPT) == {'task_id': TASK, 'estimated_credits': expected}
    assert len(transport.calls) == 1


@pytest.mark.parametrize('cost', [None, {}, [], '60', {'wrong': 60}])
def test_missing_or_wrong_cost_shape_keeps_receipt(transport, cost):
    transport.handler = lambda request: httpx.Response(200, json={'id': TASK, 'estimatedCost': cost})
    assert r.submit(KEY, PROMPT) == {'task_id': TASK, 'estimated_credits': None}


@pytest.mark.parametrize('number', ['NaN', 'Infinity', '-Infinity', '1e99999'])
def test_nonfinite_cost_keeps_receipt(transport, number):
    transport.handler = lambda request: httpx.Response(
        200, content=('{"id":"%s","estimatedCost":{"credits":%s}}' % (TASK, number)).encode())
    assert r.submit(KEY, PROMPT) == {'task_id': TASK, 'estimated_credits': None}


@pytest.mark.parametrize('task_id', [None, '', True, {}, [], '../organization',
    'https://attacker.invalid', '17f20503-6c24-1c16-946b-35dbbce2af2f',
    '17f20503-6c24-4c16-746b-35dbbce2af2f', TASK + '\n', TASK + '/cancel'])
def test_invalid_returned_id_never_retries(transport, task_id):
    transport.handler = lambda request: httpx.Response(200, json={'id': task_id, 'estimatedCost': {'credits': 60}})
    with pytest.raises(r.RunwayError):
        r.submit(KEY, PROMPT)
    assert len(transport.calls) == 1


@pytest.mark.parametrize('status', [201, 202, 301, 302, 303, 307, 308, 400, 401, 402, 403, 404, 429, 500, 503])
@pytest.mark.parametrize('operation', ['submit', 'poll', 'download'])
def test_http_failures_are_sanitized_no_redirect_or_retry(transport, status, operation):
    transport.handler = lambda request: httpx.Response(status, text=KEY + ' private-provider-detail',
        headers={'location': 'https://attacker.invalid/private'})
    with pytest.raises(r.RunwayError) as error:
        if operation == 'submit':
            r.submit(KEY, PROMPT)
        elif operation == 'poll':
            r.poll(KEY, TASK)
        else:
            r.download(URL)
    assert KEY not in str(error.value) and 'private-provider-detail' not in str(error.value)
    assert len(transport.calls) == 1


@pytest.mark.parametrize('error_type', [httpx.ReadTimeout, httpx.ConnectTimeout,
                                     httpx.WriteError, httpx.RemoteProtocolError])
@pytest.mark.parametrize('operation', ['submit', 'poll', 'download'])
def test_transport_failures_never_resubmit(transport, error_type, operation):
    def fail(request):
        raise error_type(KEY + ' private-provider-detail', request=request)
    transport.handler = fail
    with pytest.raises(r.RunwayError) as error:
        if operation == 'submit':
            r.submit(KEY, PROMPT)
        elif operation == 'poll':
            r.poll(KEY, TASK)
        else:
            r.download(URL)
    assert KEY not in str(error.value) and 'private-provider-detail' not in str(error.value)
    assert len(transport.calls) == 1


@pytest.mark.parametrize('body', [b'not-json', b'[]', b'null', b'{}', b'"text"', b'', b'\xff',
                                b'[' * 2000 + b']' * 2000])
@pytest.mark.parametrize('operation', ['submit', 'poll'])
def test_malformed_json_is_sanitized(transport, body, operation):
    transport.handler = lambda request: httpx.Response(200, content=body)
    with pytest.raises(r.RunwayError):
        r.submit(KEY, PROMPT) if operation == 'submit' else r.poll(KEY, TASK)
    assert len(transport.calls) == 1


@pytest.mark.parametrize('method,path,payload', [
    ('DELETE', '/v1/tasks/' + TASK, None), ('PATCH', '/v1/tasks/' + TASK, None),
    ('POST', '/v1/tasks/' + TASK, {}), ('GET', '/v1/text_to_video', None),
    ('POST', '/v1/image_to_video', {}), ('GET', '/v1/organization', None),
    ('GET', '/v1/tasks/../organization', None), ('GET', '/v1/tasks/' + TASK + '?x=1', None),
    ('GET', '/v1/tasks/' + TASK, {}), ('GET', 'https://attacker.invalid/', None),
])
def test_unauthorized_methods_and_endpoints_never_use_transport(transport, method, path, payload):
    with pytest.raises(r.RunwayError):
        r._api_request(KEY, method, path, payload)
    assert not transport.calls


@pytest.mark.parametrize('key', [None, '', True, 'a\nb', 'a\rb', 'x y', 'x' * 4097, 'مفتاح'])
def test_invalid_keys_sanitized_before_transport(transport, key):
    with pytest.raises(r.RunwayError):
        r.submit(key, PROMPT)
    assert not transport.calls


@pytest.mark.parametrize('status', ['PENDING', 'THROTTLED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'])
def test_poll_known_statuses_sanitizes_fields(transport, status):
    transport.handler = lambda request: httpx.Response(200, json=task(status))
    result = r.poll(KEY, TASK)
    expected = {'status': status.lower(), 'cost_credits': Decimal(60) if status in (
        'SUCCEEDED', 'FAILED', 'CANCELLED') else None}
    if status == 'SUCCEEDED':
        expected['output_url'] = URL
    assert result == expected
    assert KEY not in str(result) and 'private-provider-detail' not in str(result)
    request = transport.calls[0]
    assert request.method == 'GET'
    assert str(request.url) == 'https://api.dev.runwayml.com/v1/tasks/' + TASK
    assert request.headers['authorization'] == 'Bearer ' + KEY
    assert not request.content
    assert len(transport.calls) == 1


@pytest.mark.parametrize('task_id', [OTHER_TASK, TASK.upper(), None, 3, TASK + '/x'])
def test_poll_echoed_task_id_must_match_exactly(transport, task_id):
    transport.handler = lambda request: httpx.Response(200, json=task(id=task_id))
    with pytest.raises(r.RunwayError):
        r.poll(KEY, TASK)
    assert len(transport.calls) == 1


@pytest.mark.parametrize('task_id', ['', None, '../organization', TASK + '?x=1'])
def test_poll_rejects_bad_request_id_before_http(transport, task_id):
    with pytest.raises(r.RunwayError):
        r.poll(KEY, task_id)
    assert not transport.calls


@pytest.mark.parametrize('status', [None, 3, [], {}, 'COMPLETED', 'succeeded', 'ERROR', 'DELETED'])
def test_poll_unknown_status_fails_closed(transport, status):
    transport.handler = lambda request: httpx.Response(200, json=task(status))
    with pytest.raises(r.RunwayError):
        r.poll(KEY, TASK)


@pytest.mark.parametrize('cost', [None, True, -1, '60', {}, [], 10**20])
def test_poll_unknown_cost_is_never_defaulted(transport, cost):
    transport.handler = lambda request: httpx.Response(200, json=task(cost={'credits': cost}))
    assert r.poll(KEY, TASK) == {'status': 'succeeded', 'cost_credits': None, 'output_url': URL}


@pytest.mark.parametrize('output', [None, [], [URL, URL], URL, {}, [None], [42]])
def test_success_requires_exactly_one_valid_output(transport, output):
    transport.handler = lambda request: httpx.Response(200, json=task(output=output))
    with pytest.raises(r.RunwayError):
        r.poll(KEY, TASK)


@pytest.mark.parametrize('url', [
    None, 42, '', 'http://dnznrvs05pmza.cloudfront.net/output.mp4',
    'https://attacker.cloudfront.net/output.mp4', 'https://cloudfront.net/output.mp4',
    'https://sub.dnznrvs05pmza.cloudfront.net/output.mp4',
    'https://dnznrvs05pmza.cloudfront.net.attacker.invalid/output.mp4',
    'https://dnznrvs05pmza.cloudfront.net@attacker.invalid/output.mp4',
    'https://user:password@dnznrvs05pmza.cloudfront.net/output.mp4',
    'https://dnznrvs05pmza.cloudfront.net:443/output.mp4',
    'https://dnznrvs05pmza.cloudfront.net:/output.mp4',
    'https://dnznrvs05pmza.cloudfront.net:8443/output.mp4',
    'https://dnznrvs05pmza.cloudfront.net./output.mp4',
    'https://DNZNRVS05PMZA.cloudfront.net/output.mp4',
    'https://127.0.0.1/output.mp4', 'https://[::1]/output.mp4',
    'https://169.254.169.254/latest/meta-data.mp4', 'https://2130706433/output.mp4',
    'file:///etc/private.mp4', 'ftp://dnznrvs05pmza.cloudfront.net/output.mp4',
    'https://dnznrvs05pmza.cloudfront.net/a/../output.mp4',
    'https://dnznrvs05pmza.cloudfront.net/./output.mp4',
    'https://dnznrvs05pmza.cloudfront.net/%2e%2e/output.mp4',
    'https://dnznrvs05pmza.cloudfront.net/output.mp4#fragment',
    'https://dnznrvs05pmza.cloudfront.net/output.mp4#',
    'https://dnznrvs05pmza.cloudfront.net/output.mov',
    'https://dnznrvs05pmza.cloudfront.net/output.mp4\r\n',
    '\nhttps://dnznrvs05pmza.cloudfront.net/output.mp4',
    'https://dnznrvs05pmza.cloudfront.net\\attacker.invalid/output.mp4',
    'https://dnznrvs05pmza.cloudfront.net/ع.mp4', URL + 'x' * 8192,
])
def test_ssrf_urls_fail_before_download_transport(transport, url):
    with pytest.raises(r.RunwayError):
        r.download(url)
    assert not transport.calls


def test_output_signed_query_is_preserved():
    assert r.output_url(URL + '&Signature=a%2Bb%3D&Expires=123') == URL + '&Signature=a%2Bb%3D&Expires=123'


def test_download_uses_no_credential_and_validates_bytes(transport, monkeypatch):
    payload = FTYP + b'fixture'
    transport.handler = lambda request: httpx.Response(200, content=payload, headers={'content-type': 'video/mp4'})
    validated = []
    monkeypatch.setattr(r, 'validate_file', lambda data: validated.append(data))
    assert r.download(URL) == payload
    assert validated == [payload]
    request = transport.calls[0]
    assert request.method == 'GET' and str(request.url) == URL
    assert all(name not in request.headers for name in ('authorization', 'cookie', 'x-runway-version', 'referer'))
    assert len(transport.calls) == 1


class ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    def __iter__(self):
        yield from self.chunks


@pytest.mark.parametrize('length', [str(r.MAX_EXPORT + 1), '-1', 'invalid', '0', '1', '9999999999999'])
def test_download_rejects_bad_announced_length(transport, length):
    transport.handler = lambda request: httpx.Response(200, content=FTYP, headers={'content-length': length})
    with pytest.raises(r.RunwayError):
        r.download(URL)
    assert len(transport.calls) == 1


def test_download_enforces_actual_stream_limit_without_length(transport, monkeypatch):
    monkeypatch.setattr(r, 'MAX_EXPORT', 1024)
    transport.handler = lambda request: httpx.Response(200, stream=ChunkStream([b'x' * 700, b'x' * 700]))
    with pytest.raises(r.RunwayError):
        r.download(URL)


def test_download_accepts_exact_size_limit(transport, monkeypatch):
    monkeypatch.setattr(r, 'MAX_EXPORT', 1024)
    monkeypatch.setattr(r, 'validate_file', lambda payload: {})
    transport.handler = lambda request: httpx.Response(200, stream=ChunkStream([b'x' * 512, b'x' * 512]))
    assert len(r.download(URL)) == 1024


@pytest.mark.parametrize('operation', ['submit', 'poll', 'download'])
def test_compressed_response_is_rejected(transport, operation):
    # Content compression defeats simple announced-versus-actual size checks.
    transport.handler = lambda request: httpx.Response(
        200, stream=ChunkStream([b'not-a-compressed-body']), headers={'content-encoding': 'gzip'})
    with pytest.raises(r.RunwayError):
        if operation == 'submit':
            r.submit(KEY, PROMPT)
        elif operation == 'poll':
            r.poll(KEY, TASK)
        else:
            r.download(URL)
    assert len(transport.calls) == 1


def test_api_json_is_size_bounded(transport, monkeypatch):
    monkeypatch.setattr(r, '_MAX_JSON', 1024)
    transport.handler = lambda request: httpx.Response(200, stream=ChunkStream([b' ' * 1025]))
    with pytest.raises(r.RunwayError):
        r.submit(KEY, PROMPT)
    assert len(transport.calls) == 1


def test_stream_deadline_is_bounded(transport, monkeypatch):
    # An inactivity timeout alone does not bound a slow dribbling stream.
    times = iter([100, 200])
    monkeypatch.setattr(r.time, 'monotonic', lambda: next(times))
    transport.handler = lambda request: httpx.Response(200, stream=ChunkStream([FTYP]))
    with pytest.raises(r.RunwayError):
        r.download(URL)


def probe_metadata():
    return {'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 720, 'height': 1280,
                         'duration': '5.000000', 'nb_frames': '120', 'nb_read_frames': '120',
                         'disposition': {'attached_pic': 0}}],
            'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2', 'duration': '5.000000'}}


def mock_probe(monkeypatch, data=None, **updates):
    monkeypatch.setattr(r.shutil, 'which', lambda *args, **kwargs: '/usr/bin/ffprobe')
    result = {'returncode': 0, 'stdout': json.dumps(data or probe_metadata()).encode(), 'stderr': b''}
    result.update(updates)
    monkeypatch.setattr(r.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(**result))


def test_ffprobe_only_sees_local_file_with_no_network_or_credentials(monkeypatch):
    paths = []
    monkeypatch.setattr(r.shutil, 'which', lambda *args, **kwargs: '/usr/bin/ffprobe')

    def run(command, **kwargs):
        paths.append(Path(command[-1]))
        assert paths[-1].read_bytes() == FTYP
        assert command[command.index('-protocol_whitelist') + 1] == 'file'
        assert command[command.index('-format_whitelist') + 1] == 'mov'
        assert command[command.index('-enable_drefs') + 1] == '0'
        assert command[command.index('-use_absolute_path') + 1] == '0'
        assert '-count_frames' in command
        assert kwargs == {'capture_output': True, 'timeout': 30, 'check': False,
                          'env': {'PATH': r.os.defpath, 'LANG': 'C'}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(probe_metadata()).encode(), stderr=b'')

    monkeypatch.setattr(r.subprocess, 'run', run)
    assert r.validate_file(FTYP) == {'container': 'mp4', 'codec': 'h264', 'width': 720,
                                  'height': 1280, 'duration': 5.0, 'size': len(FTYP)}
    assert paths and not paths[0].exists()


@pytest.mark.parametrize('payload', [None, 'text', bytearray(FTYP), b'', b'x' * 100,
    b'#EXTM3U\nhttps://attacker.invalid/private', b'{"video":"fake"}',
    b'\x00\x00\x00\x18ftypqt  \x00\x00\x02\x00qt  avc1',
    b'\x00\x00\x00\x17ftypisom\x00\x00\x02\x00isomavc1',
    b'\xff\xff\xff\xffftypisom\x00\x00\x02\x00isomavc1'])
def test_not_mp4_rejected_before_ffprobe(payload, monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail('ffprobe should not run for invalid payload')
    monkeypatch.setattr(r.subprocess, 'run', fail)
    with pytest.raises(r.RunwayError):
        r.validate_file(payload)


def test_oversized_payload_rejected_before_ffprobe(monkeypatch):
    monkeypatch.setattr(r, 'MAX_EXPORT', 25)
    with pytest.raises(r.RunwayError):
        r.validate_file(FTYP + b'xx')


@pytest.mark.parametrize('field,value', [
    ('codec_name', 'hevc'), ('codec_name', 'mpeg4'), ('width', 1280), ('height', 720),
    ('duration', '4.79'), ('duration', '5.31'), ('duration', 'NaN'), ('duration', 'Infinity'),
    ('duration', None), ('nb_read_frames', '0'), ('nb_read_frames', 'N/A'),
    ('nb_read_frames', '119'), ('nb_frames', 'N/A'),
    ('disposition', {'attached_pic': 1}), ('tags', {'rotate': '90'}),
    ('side_data_list', [{'rotation': -90}]),
])
def test_ffprobe_rejects_wrong_video_metadata(monkeypatch, field, value):
    metadata = probe_metadata()
    metadata['streams'][0][field] = value
    mock_probe(monkeypatch, metadata)
    with pytest.raises(r.RunwayError):
        r.validate_file(FTYP)


@pytest.mark.parametrize('duration', ['4.8', '5', '5.3'])
def test_duration_tolerance_inclusive(monkeypatch, duration):
    metadata = probe_metadata()
    metadata['streams'][0]['duration'] = metadata['format']['duration'] = duration
    mock_probe(monkeypatch, metadata)
    assert r.validate_file(FTYP)['duration'] == float(duration)


@pytest.mark.parametrize('change', ['missing_streams', 'two_videos', 'extra_subtitle', 'wrong_container',
                                  'wrong_container_duration', 'invalid_root'])
def test_ffprobe_malformed_or_unexpected_structure(monkeypatch, change):
    metadata = probe_metadata()
    if change == 'missing_streams':
        metadata.pop('streams')
    elif change == 'two_videos':
        metadata['streams'].append(deepcopy(metadata['streams'][0]))
    elif change == 'extra_subtitle':
        metadata['streams'].append({'codec_type': 'subtitle'})
    elif change == 'wrong_container':
        metadata['format']['format_name'] = 'matroska,webm'
    elif change == 'wrong_container_duration':
        metadata['format']['duration'] = '30'
    else:
        metadata = ['bad']
    mock_probe(monkeypatch, metadata)
    with pytest.raises(r.RunwayError):
        r.validate_file(FTYP)


@pytest.mark.parametrize('updates', [{'returncode': 1}, {'stderr': b'private-provider-detail'},
                                  {'stdout': b'not-json'}, {'stdout': b'x' * 65537}])
def test_ffprobe_failures_do_not_expose_diagnostics(monkeypatch, updates):
    mock_probe(monkeypatch, **updates)
    with pytest.raises(r.RunwayError) as error:
        r.validate_file(FTYP)
    assert 'private-provider-detail' not in str(error.value)


def test_ffprobe_missing_is_safe_failure(monkeypatch):
    monkeypatch.setattr(r.shutil, 'which', lambda *args, **kwargs: None)
    with pytest.raises(r.RunwayError):
        r.validate_file(FTYP)


def test_ffprobe_timeout_is_safe_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired('private-provider-detail', 30)
    monkeypatch.setattr(r.subprocess, 'run', fail)
    with pytest.raises(r.RunwayError) as error:
        r.validate_file(FTYP)
    assert 'private-provider-detail' not in str(error.value)


@pytest.fixture(scope='module')
def real_videos(tmp_path_factory):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):
        pytest.skip('Local ffmpeg and ffprobe are required for real MP4 fixtures')
    directory = tmp_path_factory.mktemp('runway-fixture')
    outputs = {}
    for name, size, duration, codec in [('valid', '720x1280', 5, 'libx264'),
            ('landscape', '1280x720', 5, 'libx264'), ('long', '720x1280', 6, 'libx264'),
            ('wrong_codec', '720x1280', 5, 'mpeg4')]:
        path = directory / (name + '.mp4')
        command = [ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=' + size + ':r=12',
                   '-t', str(duration), '-an', '-c:v', codec, '-threads', '1', '-pix_fmt', 'yuv420p',
                   '-movflags', '+faststart', str(path)]
        subprocess.run(command, check=True, capture_output=True, timeout=30)
        outputs[name] = path.read_bytes()
    return outputs


def test_real_five_second_portrait_h264_mp4(real_videos, transport):
    payload = real_videos['valid']
    assert len(payload) < 100_000
    metadata = r.validate_file(payload)
    assert metadata == {'container': 'mp4', 'codec': 'h264', 'width': 720, 'height': 1280,
                        'duration': 5.0, 'size': len(payload)}
    transport.handler = lambda request: httpx.Response(200, content=payload)
    assert r.download(URL) == payload


@pytest.mark.parametrize('name', ['landscape', 'long', 'wrong_codec'])
def test_real_nonconforming_videos_rejected(real_videos, name):
    with pytest.raises(r.RunwayError):
        r.validate_file(real_videos[name])


def test_real_truncated_h264_rejected(real_videos):
    with pytest.raises(r.RunwayError):
        r.validate_file(real_videos['valid'][:-300])


def test_no_cancel_delete_or_generic_generation_interface():
    assert all(not hasattr(r, name) for name in ('cancel', 'delete', 'image_to_video', 'create_router', 'retry'))
