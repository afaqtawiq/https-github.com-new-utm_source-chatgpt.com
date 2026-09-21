from decimal import Decimal
import json
from unittest.mock import patch

import httpx
import pytest

from app import media_fal as f


def pricing():
    return {'prices': [{'endpoint_id': f.IMAGE_MODEL, 'currency': 'USD', 'unit': 'image', 'unit_price': .03},
                       {'endpoint_id': f.VIDEO_MODEL, 'currency': 'USD', 'unit': 'second', 'unit_price': .07}]}


def receipt(stage):
    rid = '12345678-aaaa-bbbb-cccc-123456789012'
    root = '/'.join(f.MODELS[stage].split('/')[:2])
    url = f.QUEUE + root + '/requests/' + rid
    return {'request_id': rid, 'status_url': url + '/status', 'response_url': url}


def test_live_price_math_and_validation():
    data = pricing()
    with patch.object(f, 'call', return_value=data):
        assert f.prices('fixture') == {'image': Decimal('.030000'), 'video': Decimal('.350000')}
    for field, bad in [('currency', 'EUR'), ('unit', 'gpu-hour'), ('unit_price', 'NaN'), ('unit_price', -1)]:
        data = pricing()
        data['prices'][0][field] = bad
        with patch.object(f, 'call', return_value=data), pytest.raises(f.MediaError):
            f.prices('fixture')


@pytest.mark.parametrize('unit', ['seconds', 'video_second', 'video_seconds', 'Video-Second', ' second '])
def test_equivalent_second_units_preserve_five_second_budget(unit):
    data = pricing()
    data['prices'][1]['unit'] = unit
    with patch.object(f, 'call', return_value=data):
        assert f.prices('fixture')['video'] == Decimal('.350000')


def test_unknown_unit_stays_blocked_and_diagnostic_excludes_unsafe_values():
    for unit in ('megapixel', '<script>secret</script>', None, []):
        data = pricing()
        data['prices'][1]['unit'] = unit
        with patch.object(f, 'call', return_value=data), pytest.raises(f.MediaError) as error:
            f.prices('fixture')
        assert 'secret' not in str(error.value)
    assert 'unknown' in str(error.value)


@pytest.mark.parametrize('url', ['http://v3.fal.media/x.mp4', 'https://evil.example/x.mp4',
    'https://fal.media.evil.example/x.mp4', 'https://user@v3.fal.media/x.mp4',
    'https://127.0.0.1/x.mp4', 'https://storage.googleapis.com/other/x.mp4',
    'https://v3.fal.media/x.html', 'https://v3.fal.media:444/x.mp4'])
def test_only_provider_media_urls(url):
    with pytest.raises(f.MediaError):
        f.asset_url(url, 'video')


def test_queue_url_does_not_forward_credentials_elsewhere():
    r = receipt('image')
    assert f.queue_url(r['status_url'], f.IMAGE_MODEL, r['request_id'], status=True) == r['status_url']
    for url in (r['status_url'].replace('queue.fal.run', 'attacker.invalid'),
                r['status_url'] + '?redirect=https://attacker.invalid',
                r['status_url'].replace('bytedance', 'attacker'),
                r['status_url'].replace(r['request_id'], 'different-request')):
        with pytest.raises(f.MediaError):
            f.queue_url(url, f.IMAGE_MODEL, r['request_id'], status=True)


def test_exact_one_image_and_five_second_video():
    with patch.object(f, 'call', return_value=receipt('image')) as call:
        f.submit('fixture', 'image', 'a realistic truck', ratio='9:16')
        payload = call.call_args.kwargs['payload']
        assert payload['num_images'] == payload['max_images'] == 1
        assert payload['image_size'] == 'portrait_16_9' and payload['enable_safety_checker'] is True
    with patch.object(f, 'call', return_value=receipt('video')) as call:
        f.submit('fixture', 'video', 'natural wheel motion', image_url='https://v3.fal.media/files/truck.png')
        assert call.call_args.kwargs['payload']['duration'] == '5'


def test_no_retry_no_expiry_and_no_secret_error_echo():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={'error': 'secret-must-never-be-echoed'})
    real_client = httpx.Client
    with patch.object(f.httpx, 'Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
        with pytest.raises(f.MediaError) as error:
            f.call('fixture-key', 'POST', f.QUEUE + f.IMAGE_MODEL, payload={'prompt': 'fixture'})
    assert len(calls) == 1 and 'secret-must-never-be-echoed' not in str(error.value)
    assert calls[0].headers['X-Fal-No-Retry'] == '1'
    assert json.loads(calls[0].headers['X-Fal-Object-Lifecycle-Preference']) == {'expiration_duration_seconds': None}


def test_completed_error_is_not_success_and_wait_is_not_failure():
    r = receipt('video')
    with patch.object(f, 'call', return_value={'status': 'IN_PROGRESS'}):
        assert f.result('fixture', 'video', r) is None
    with patch.object(f, 'call', return_value={'status': 'COMPLETED', 'error': 'private detail'}) as call:
        with pytest.raises(f.MediaError):
            f.result('fixture', 'video', r)
        assert call.call_count == 1
    with patch.object(f, 'call', side_effect=[{'status': 'COMPLETED'}, {'video': {'url': 'https://v3.fal.media/files/test.mp4'}}]):
        assert f.result('fixture', 'video', r).endswith('.mp4')
