"""Runway transport tests use fake keys and mock HTTP only; no paid endpoints."""
from unittest.mock import patch

import httpx
import pytest

from app import media_runway as r


def invoke(handler):
    original = httpx.Client
    with patch.object(r.httpx, 'Client', side_effect=lambda **kw: original(
            transport=httpx.MockTransport(handler), **kw)) as client:
        result = r.organization_balance('local-ci-runway-key-never-live')
        assert client.call_args.kwargs == {'timeout': 20, 'follow_redirects': False, 'trust_env': False}
        return result


@pytest.mark.parametrize('balance', [0, 4042])
def test_fixed_read_only_request_and_allowlisted_response(balance):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == 'GET'
        assert str(request.url) == 'https://api.dev.runwayml.com/v1/organization'
        assert request.headers['Authorization'] == 'Bearer local-ci-runway-key-never-live'
        assert request.headers['X-Runway-Version'] == '2024-11-06'
        assert not request.content
        return httpx.Response(200, json={'creditBalance': balance, 'tier': {'models': {}},
                                        'extra': '<script>secret-provider-content</script>'})
    assert invoke(handler) == balance
    assert len(calls) == 1
    assert not hasattr(r, 'submit')


@pytest.mark.parametrize('balance', [None, True, False, -1, 1.5, '4042', 'NaN', float('inf'), {}, [], 10**20])
def test_invalid_credit_balance_is_not_verification(balance):
    # custom Response.json allows nonfinite input without serializing invalid JSON.
    response = httpx.Response(200)
    with patch.object(response, 'json', return_value={'creditBalance': balance}):
        with pytest.raises(r.RunwayError):
            invoke(lambda request: response)


@pytest.mark.parametrize('status', [301, 302, 307, 401, 403, 429, 500, 503])
def test_no_redirect_retry_or_secret_error_echo(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='local-ci-runway-key-never-live private-provider-detail',
                              headers={'location': 'https://attacker.invalid/'})
    with pytest.raises(r.RunwayError) as error:
        invoke(handler)
    assert len(calls) == 1
    assert 'private-provider-detail' not in str(error.value)
    assert 'local-ci-runway-key' not in str(error.value)


@pytest.mark.parametrize('body', [b'not-json', b'[]', b'null', b'{}'])
def test_bad_json_and_missing_balance_are_sanitized(body):
    with pytest.raises(r.RunwayError):
        invoke(lambda request: httpx.Response(200, content=body))


def test_transport_errors_are_sanitized_and_not_retried():
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('private-provider-detail local-ci-runway-key', request=request)
    with pytest.raises(r.RunwayError) as error:
        invoke(handler)
    assert len(calls) == 1
    assert 'private-provider-detail' not in str(error.value)
    assert 'local-ci-runway-key' not in str(error.value)
