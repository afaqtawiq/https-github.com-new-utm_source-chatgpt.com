import copy
import datetime as dt
import json

import httpx
import pytest

from app import social_zernio as z

NOW = dt.datetime(2026, 9, 20, 10, tzinfo=dt.timezone.utc)
ACCOUNTS = {'youtube': {'accountId': 'a' * 24, 'username': 'afaqtaw'},
            'tiktok': {'accountId': 'b' * 24, 'username': 'afaqtawaiq6'}}
ITEM = {'id': 1, 'platform': 'YouTube+TikTok', 'content_type': 'video', 'title': 'آفاق طويق',
        'body': 'حلول النقل والخدمات اللوجستية', 'media_url': 'https://media.example.com/afaaq.mp4'}
FORM = {'preview_confirmed': 'yes', 'scheduled_at': '2026-09-20T15:00', 'synthetic': 'yes',
        'youtube_visibility': 'public', 'made_for_kids': 'no', 'tiktok_privacy': 'PUBLIC_TO_EVERYONE',
        'allow_comment': 'yes', 'allow_duet': 'no', 'allow_stitch': 'no', 'commercial_content': 'brand_organic'}
CREATOR = {'creator': {'canPostMore': True}, 'privacyLevels': [{'value': 'PUBLIC_TO_EVERYONE'}],
           'postingLimits': {'interactionSettings': {k: {'enabled': k != 'allow_stitch'} for k in
                            ('allow_comment', 'allow_duet', 'allow_stitch')}},
           'commercialContentTypes': [{'value': 'brand_organic'}]}


def test_scheduled_payload_matches_provider_contract_and_riyadh():
    payload = z.make_payload(ITEM, ACCOUNTS, FORM, CREATOR, NOW)
    assert payload['scheduledFor'] == '2026-09-20T12:00:00+00:00'
    assert payload['publishNow'] is False and payload['timezone'] == 'Asia/Riyadh'
    assert {(x['platform'], x['accountId']) for x in payload['platforms']} == {('youtube', 'a' * 24), ('tiktok', 'b' * 24)}
    assert payload['platforms'][0]['platformSpecificData'] == {
        'title': ITEM['title'], 'visibility': 'public', 'madeForKids': False, 'containsSyntheticMedia': True}
    assert payload['tiktokSettings']['commercialContentType'] == 'brand_organic'
    assert payload['tiktokSettings']['videoMadeWithAi'] is True
    assert payload['tiktokSettings']['allow_stitch'] is False


@pytest.mark.parametrize('field,value', [('preview_confirmed', ''), ('synthetic', ''), ('made_for_kids', ''),
                                      ('youtube_visibility', ''), ('tiktok_privacy', 'SELF_ONLY'),
                                      ('allow_comment', ''), ('allow_stitch', 'yes'),
                                      ('commercial_content', 'brand_content'), ('scheduled_at', '2026-09-20T12:00')])
def test_unreviewed_or_invalid_requests_are_blocked(field, value):
    with pytest.raises(z.PublishingError):
        z.make_payload(ITEM, ACCOUNTS, {**FORM, field: value}, CREATOR, NOW)


@pytest.mark.parametrize('url', ['http://media.example.com/x.mp4', 'https://127.0.0.1/x.mp4',
                               'https://10.0.0.1/x.mp4', 'https://host.internal/x.mp4',
                               'https://user:secret@media.example.com/x.mp4',
                               'https://www.youtube.com/watch?v=123', 'javascript:alert(1)',
                               'https://[::1]/x.mp4', 'https://example.com:broken/x.mp4'])
def test_non_video_or_private_urls_are_blocked(url):
    with pytest.raises(z.PublishingError):
        z.media_url(url)


def test_legacy_all_does_not_silently_publish_to_two_accounts():
    with pytest.raises(z.PublishingError):
        z.make_payload({**ITEM, 'platform': 'All'}, ACCOUNTS, FORM, CREATOR, NOW)


def test_no_post_when_creator_cannot_publish():
    with pytest.raises(z.PublishingError):
        z.make_payload(ITEM, ACCOUNTS, FORM, {**CREATOR, 'creator': {'canPostMore': False}}, NOW)


def test_wrong_account_key_and_revoked_permissions_rejected(monkeypatch):
    records = [{'platform': p, '_id': a['accountId'], 'username': '@' + a['username'], 'isActive': True}
               for p, a in ACCOUNTS.items()]
    health = {a['accountId']: {'accountId': a['accountId'], 'platform': p, 'username': a['username'],
              'tokenStatus': {'valid': True}, 'permissions': {'canPost': True}} for p, a in ACCOUNTS.items()}
    def provider(key, method, path):
        assert key == 'dedicated-social-key' and method == 'GET'
        return {'accounts': records} if path == '/accounts' else health[path.split('/')[2]]
    monkeypatch.setattr(z, 'provider_request', provider)
    assert z.verified_accounts('dedicated-social-key') == ACCOUNTS
    records[0]['username'] = 'sonaaq'
    with pytest.raises(z.PublishingError): z.verified_accounts('dedicated-social-key')
    records[0]['username'] = 'afaqtaw'
    health['a' * 24]['permissions']['canPost'] = False
    with pytest.raises(z.PublishingError): z.verified_accounts('dedicated-social-key')


def result(state='scheduled'):
    targets = [{'platform': p, 'accountId': a['accountId'], 'status': 'pending'} for p, a in ACCOUNTS.items()]
    return {'post': {'_id': 'c' * 24, 'status': state, 'platforms': copy.deepcopy(targets)}}, targets


def test_partial_207_is_not_reported_as_published():
    response, targets = result('partial')
    response['post']['platforms'][0]['status'] = 'published'
    response['post']['platforms'][1]['status'] = 'failed'
    assert z.publication_result(response, targets)[1] == 'partial'
    response['post']['status'] = 'published'
    assert z.publication_result(response, targets)[1] == 'needs_review'


def test_wrong_result_targets_and_missing_receipt_rejected():
    response, targets = result()
    response['post']['platforms'][0]['accountId'] = 'd' * 24
    with pytest.raises(z.PublishingError): z.publication_result(response, targets)
    with pytest.raises(z.PublishingError): z.publication_result({'success': True}, targets)


def test_provider_uses_fixed_origin_and_idempotency_and_no_redirects(monkeypatch):
    response, targets = result('partial')
    captured = []
    transport = httpx.MockTransport(lambda request: (captured.append(request), httpx.Response(207, json=response))[1])
    real_client = httpx.Client
    monkeypatch.setattr(z.httpx, 'Client', lambda **kw: real_client(transport=transport, **kw))
    data = z.provider_request('social-key', 'POST', '/posts', payload={'content': 'test'}, request_id='unique-id')
    assert z.publication_result(data, targets)[1] == 'partial'
    assert str(captured[0].url) == 'https://zernio.com/api/v1/posts'
    assert captured[0].headers['Authorization'] == 'Bearer social-key'
    assert captured[0].headers['x-request-id'] == 'unique-id'


def test_provider_errors_do_not_expose_keys_or_response_text(monkeypatch):
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={'error': 'DO-NOT-EXPOSE-SECRET'}))
    monkeypatch.setattr(z.httpx, 'Client', lambda **kw: real_client(transport=transport, **kw))
    with pytest.raises(z.PublishingError) as error:
        z.provider_request('DO-NOT-EXPOSE-SECRET', 'GET', '/accounts')
    assert 'DO-NOT-EXPOSE' not in str(error.value)


def test_existing_request_receipt_accepted_without_new_publish():
    response, targets = result()
    post = response.pop('post')
    for entry in post['platforms']:
        entry['accountId'] = {'_id': entry['accountId']}
    assert z.publication_result({'existingPost': post}, targets)[1] == 'scheduled'
