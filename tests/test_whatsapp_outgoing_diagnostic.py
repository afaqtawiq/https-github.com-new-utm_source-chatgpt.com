"""Fictional outgoing receipts; every provider and anonymous request is mocked."""
from contextlib import contextmanager
from copy import deepcopy
from html.parser import HTMLParser
import asyncio
import hashlib
import json
import logging
import sqlite3
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import whatsapp_document_store as documents
from app import whatsapp_inbox as inbox
from app import whatsapp_outgoing_diagnostic as diagnostic
from app import zernio_whatsapp as z


@pytest.fixture
def setup(monkeypatch):
    actor = {'role': 'admin', 'id': 'synthetic-session', 'user_id': 7,
             'csrf': 'synthetic-csrf', 'permission': True, 'mfa': True}
    def session(request):
        if actor['role'] != 'admin':
            raise HTTPException(403)
        return actor
    def authority(request):
        value = session(request)
        if not value['permission']:
            raise HTTPException(403)
        if not value['mfa']:
            raise HTTPException(428)
        return value
    monkeypatch.setattr(z, 'session', session)
    monkeypatch.setattr(inbox, 'send_authority', authority)
    monkeypatch.setitem(sys.modules, 'app.fine_permissions',
        SimpleNamespace(has_permission=lambda value, permission: value['permission']))
    monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID', 'account-test')
    monkeypatch.delenv('ZERNIO_WHATSAPP_ACCOUNT_ID', raising=False)
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    class Connection:
        dialect = 'sqlite'
        def execute(self, sql, args=()):
            return conn.execute(sql.replace('%s', '?'), args)
    @contextmanager
    def database():
        with conn:
            yield Connection()
    monkeypatch.setattr(inbox, 'database', database)
    documents.init_storage(db_factory=database)
    content = b'%PDF-1.7 Synthetic fixture only; no real document.'
    item = documents.create(creator_id=7, account_id='account-test', conversation_id='c1',
        recipient='966500000001', filename='fictional.pdf', content=content, db_factory=database)
    claimed = documents.claim(item['token'], 7, confirmed_sha256=item['sha256'],
        confirmed_recipient=item['recipient'], confirmed_account_id=item['account_id'], db_factory=database)
    documents.finish(item['token'], claimed['send_token'], status='public_link_warning',
                     provider_ids=['synthetic-receipt'], db_factory=database)
    state = {'actor': actor, 'conn': conn, 'item': item, 'requests': [], 'anonymous': [],
        'anonymous_options': [], 'clients': [], 'anonymous_status': 403,
        'anonymous_headers': {}, 'anonymous_body': b'private body must not escape',
        'accounts': [{'_id': 'account-test', 'platform': 'whatsapp', 'isActive': True}],
        'conversations': [{'id': 'c1', 'accountId': 'account-test', 'platform': 'whatsapp',
                           'participantId': '966500000001'}],
        'messages': [{'id': 'synthetic-receipt', 'accountId': 'account-test',
            'conversationId': 'c1', 'platform': 'whatsapp', 'direction': 'outgoing',
            'senderId': 'synthetic-business-sender', 'deliveryStatus': 'delivered',
            'attachments': [{'type': 'file', 'mimeType': 'application/pdf',
                'url': 'https://zernio.com/api/v1/whatsapp/media/media-synthetic?accountId=account-test'}]}]}
    real_client = httpx.AsyncClient
    async def handle(request):
        state['requests'].append(request)
        await asyncio.sleep(0)
        assert request.method == 'GET' and request.url.host == 'zernio.com'
        assert request.headers['authorization'] == 'Bearer synthetic-only'
        if state.get('provider_error'):
            raise state['provider_error']('private URL token and body')
        if request.url.path.endswith('/accounts'):
            payload = {'accounts': state['accounts']}
        elif request.url.path.endswith('/conversations'):
            payload = {'data': state['conversations'], 'pagination': state.get('conversation_pagination', {})}
        elif request.url.path.endswith('/messages'):
            payload = {'messages': state['messages'], 'pagination': state.get('message_pagination', {})}
        else:
            raise AssertionError('No media downloads, resolves, uploads, or unrelated endpoints')
        if state.get('on_read'):
            state['on_read'](request)
        return httpx.Response(state.get('provider_status', 200),
            headers={'set-cookie': 'provider_session=synthetic-secret', **state.get('provider_headers', {})},
            json=payload)
    def make_authenticated():
        client = real_client(transport=httpx.MockTransport(handle), follow_redirects=True,
                             headers={'Authorization': 'Bearer synthetic-only'})
        state['clients'].append(client)
        return client
    async def anonymous_handle(request):
        state['anonymous'].append(request)
        await asyncio.sleep(0)
        assert request.method == 'GET' and request.url.host == 'zernio.com'
        assert 'authorization' not in request.headers and 'cookie' not in request.headers
        assert 'proxy-authorization' not in request.headers
        if state.get('on_anonymous'):
            state['on_anonymous'](request)
        if state.get('anonymous_error'):
            raise state['anonymous_error']('private token URL')
        return httpx.Response(state['anonymous_status'], headers=state['anonymous_headers'],
            content=state['anonymous_body'], stream=state.get('anonymous_stream'))
    def make_anonymous(**kwargs):
        state['anonymous_options'].append(kwargs.copy())
        client = real_client(transport=httpx.MockTransport(anonymous_handle), **kwargs)
        state['clients'].append(client)
        return client
    monkeypatch.setattr(z, 'client', make_authenticated)
    monkeypatch.setattr(diagnostic.httpx, 'AsyncClient', make_anonymous)
    app = FastAPI()
    app.include_router(diagnostic.router)
    with TestClient(app) as client:
        state['client'] = client
        yield state
    conn.close()


def form(state, **updates):
    item = state['item']
    return {'csrf': 'synthetic-csrf', 'sha256': item['sha256'], 'account': item['account_id'],
        'conversation': item['conversation_id'], 'recipient': item['recipient'],
        'receipt': 'synthetic-receipt', **updates}


def inspect(state, **updates):
    return state['client'].post('/whatsapp-inbox/documents/' + state['item']['token'] +
                                '/privacy-diagnostic', data=form(state, **updates))


def summary(response):
    class Fields(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values, self.key = {}, None
        def handle_starttag(self, tag, attrs):
            if tag == 'dd':
                self.key = dict(attrs).get('data-field')
        def handle_data(self, data):
            if self.key:
                self.values[self.key] = self.values.get(self.key, '') + data
        def handle_endtag(self, tag):
            if tag == 'dd':
                self.key = None
    parser = Fields()
    parser.feed(response.text)
    return parser.values


def attachment(state):
    return state['messages'][0]['attachments'][0]


def test_default_metadata_only_exact_stored_receipt(setup):
    state = setup
    before = dict(state['conn'].execute('SELECT * FROM whatsapp_document_drafts').fetchone())
    response = inspect(state)
    assert response.status_code == 200, response.text
    assert summary(response) == {'scope': 'matched_document_receipt', 'file_binding': 'stored_receipt_only',
        'origin_category': 'canonical_provider_proxy', 'anonymous_result': 'not_requested',
        'privacy_assessment': 'inconclusive'}
    assert len(state['requests']) == 3 and not state['anonymous']
    assert all(client.is_closed for client in state['clients'])
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert dict(state['conn'].execute('SELECT * FROM whatsapp_document_drafts').fetchone()) == before
    for secret in ('https:', 'synthetic-receipt', 'account-test', state['item']['sha256'], 'provider_session'):
        assert secret not in response.text


@pytest.mark.parametrize('change,status', [({'role': 'viewer'}, 403), ({'permission': False}, 403),
                                         ({'mfa': False}, 428), ({'user_id': 8}, 404)])
def test_manager_recent_mfa_permission_and_creator_before_reads(setup, change, status):
    setup['actor'].update(change)
    assert inspect(setup).status_code == status
    assert not setup['requests'] and not setup['anonymous']


@pytest.mark.parametrize('key,value,status', [
    ('csrf', 'wrong', 403), ('account', 'other-account', 409), ('conversation', 'other', 409),
    ('recipient', '966500000002', 409), ('sha256', '0' * 64, 409),
    ('receipt', 'unknown-receipt', 409), ('receipt', 'https://private.invalid', 409),
    ('url', 'http://127.0.0.1/private', 400), ('probe', 'maybe', 400), ('fictional', 'maybe', 400)])
def test_binding_and_no_arbitrary_target_before_reads(setup, key, value, status):
    assert inspect(setup, **{key: value}).status_code == status
    assert not setup['requests'] and not setup['anonymous']


@pytest.mark.parametrize('missing', ['account', 'conversation', 'recipient', 'receipt', 'sha256'])
def test_missing_binding_even_with_optional_fields_rejected(setup, missing):
    values = form(setup, probe='no', fictional='no')
    del values[missing]
    response = setup['client'].post('/whatsapp-inbox/documents/' + setup['item']['token'] +
                                    '/privacy-diagnostic', data=values)
    assert response.status_code == 400 and not setup['requests']


def test_anonymous_probe_requires_explicit_nonsensitive_affirmation(setup):
    assert inspect(setup, probe='yes').status_code == 400
    assert not setup['requests'] and not setup['anonymous']


def test_terminal_binding_tampering_rejected_before_reads(setup):
    setup['conn'].execute("UPDATE whatsapp_document_drafts SET sha256=?", ('0' * 64,))
    setup['conn'].commit()
    assert inspect(setup, sha256='0' * 64).status_code == 409
    assert not setup['requests'] and not setup['anonymous']


@pytest.mark.parametrize('state', ['draft', 'sending', 'blocked', 'failed', 'expired', 'cancelled'])
def test_non_receipt_terminal_state_does_not_probe(setup, state):
    setup['conn'].execute('UPDATE whatsapp_document_drafts SET state=?', (state,))
    setup['conn'].commit()
    assert inspect(setup).status_code == 409 and not setup['requests']


@pytest.mark.parametrize('change', ['account', 'platform', 'inactive', 'duplicate', 'missing'])
def test_authenticated_account_identity_fails_closed(setup, change):
    row = setup['accounts'][0]
    if change == 'account': row['_id'] = 'other-account'
    if change == 'platform': row['platform'] = 'telegram'
    if change == 'inactive': row['isActive'] = False
    if change == 'duplicate': setup['accounts'].append(deepcopy(row))
    if change == 'missing': setup['accounts'] = []
    assert inspect(setup).status_code == 409
    assert len(setup['requests']) == 1 and not setup['anonymous']


@pytest.mark.parametrize('change', ['account', 'platform', 'group', 'recipient', 'duplicate'])
def test_private_conversation_recipient_binding(setup, change):
    row = setup['conversations'][0]
    if change == 'account': row['accountId'] = 'other-account'
    if change == 'platform': row['platform'] = 'telegram'
    if change == 'group': row['isGroup'] = True
    if change == 'recipient': row['participantId'] = '966500000002'
    if change == 'duplicate': setup['conversations'].append(deepcopy(row))
    assert inspect(setup).status_code == 409 and not setup['anonymous']


@pytest.mark.parametrize('change,status', [
    ('account', 409), ('conversation', 409), ('platform', 409), ('incoming', 409),
    ('deleted', 409), ('recipient', 409), ('duplicate', 409), ('missing', 404),
    ('multiple_attachments', 409), ('no_attachments', 409), ('non_pdf', 409), ('wrong_hash', 409)])
def test_exact_outgoing_receipt_and_attachment_binding(setup, change, status):
    row = setup['messages'][0]
    if change == 'account': row['accountId'] = 'other-account'
    if change == 'conversation': row['conversationId'] = 'other-conversation'
    if change == 'platform': row['platform'] = 'telegram'
    if change == 'incoming': row['direction'] = 'incoming'
    if change == 'deleted': row['isDeleted'] = True
    if change == 'recipient': row['recipientId'] = '966500000002'
    if change == 'duplicate': setup['messages'].append(deepcopy(row))
    if change == 'missing': row['id'] = 'different-receipt'
    if change == 'multiple_attachments': row['attachments'].append(deepcopy(row['attachments'][0]))
    if change == 'no_attachments': row['attachments'] = []
    if change == 'non_pdf': attachment(setup)['mimeType'] = 'image/png'
    if change == 'wrong_hash': attachment(setup)['sha256'] = '0' * 64
    assert inspect(setup, probe='yes', fictional='yes').status_code == status
    assert not setup['anonymous']


def test_provider_hash_corrobates_local_hash_without_downloading(setup):
    attachment(setup)['sha256'] = setup['item']['sha256']
    assert summary(inspect(setup))['file_binding'] == 'sha256_matched'
    assert not setup['anonymous']


@pytest.mark.parametrize('url', [
    'http://zernio.com/api/v1/whatsapp/media/media-synthetic',
    'https://zernio.com.evil.invalid/api/v1/whatsapp/media/media-synthetic',
    'https://zernio.com@evil.invalid/api/v1/whatsapp/media/media-synthetic',
    'https://user:secret@zernio.com/api/v1/whatsapp/media/media-synthetic',
    'https://zernio.com:444/api/v1/whatsapp/media/media-synthetic',
    'https://zernio.com/api/v1/whatsapp/media/media-synthetic?accountId=other',
    'https://zernio.com/api/v1/whatsapp/media/media-synthetic?accountId=account-test&token=secret',
    'https://zernio.com/api/v1/whatsapp/media/media-synthetic?accountId=account-test&accountId=account-test',
    'https://zernio.com/api/v1/whatsapp/media/media-synthetic?token=secret',
    'https://zernio.com/api/v1/whatsapp/media/media-synthetic#token-secret',
    'https://zernio.com/api/v1/whatsapp/media/../private',
    'https://zernio.com/api/v1/whatsapp/media/%2e%2e',
    'https://zernio.com/api/v1/whatsapp/media/media%2Fother',
    'https://zernio.com/api/v1/whatsapp/media/media-synthetic\n',
    'https://zernio.com/api/v1/whatsapp/media/media-synthetic?',
    'https://lookaside.fbsbx.com/private?token=secret',
    'https://mmg.whatsapp.net/private?token=secret',
    'https://cdn.provider.invalid/private.pdf', 'http://127.0.0.1/private',
    'http://169.254.169.254/latest/meta-data', 'http://[::1]/private',
    'file:///etc/passwd', '//zernio.com/api/v1/whatsapp/media/media-synthetic',
    {'url': 'https://private.invalid'}, 123])
def test_unknown_urls_never_probed_or_returned(setup, url):
    attachment(setup)['url'] = url
    response = inspect(setup, probe='yes', fictional='yes')
    assert response.status_code == 200
    assert summary(response)['origin_category'] == 'unknown'
    assert summary(response)['anonymous_result'] == 'not_eligible'
    assert not setup['anonymous'] and 'secret' not in response.text and 'private' not in response.text


@pytest.mark.parametrize('url', [None, ''])
def test_absent_url_is_inconclusive_and_unprobed(setup, url):
    attachment(setup)['url'] = url
    result = summary(inspect(setup, probe='yes', fictional='yes'))
    assert result['origin_category'] == 'absent' and result['privacy_assessment'] == 'inconclusive'
    assert not setup['anonymous']


def test_future_allowlisted_cdn_classification_never_authorizes_a_probe(setup,monkeypatch):
    monkeypatch.setattr(diagnostic,'_PROVIDER_CDN_HOSTS',frozenset({'cdn.provider.invalid'}))
    attachment(setup)['url']='https://cdn.provider.invalid/private.pdf?token=secret'
    result=summary(inspect(setup,probe='yes',fictional='yes'))
    assert result['origin_category']=='allowlisted_provider_cdn'
    assert result['anonymous_result']=='not_eligible' and result['privacy_assessment']=='inconclusive'
    assert not setup['anonymous'] and 'secret' not in json.dumps(result)


@pytest.mark.parametrize('status,result', [(401, 'denied'), (403, 'denied'), (404, 'not_found'),
    (302, 'redirect'), (307, 'redirect'), (500, 'other_status'), (429, 'other_status')])
def test_fixed_anonymous_no_auth_no_redirect_and_no_privacy_proof(setup, status, result):
    state = setup
    state['anonymous_status'] = status
    state['anonymous_headers'] = {'Location': 'http://127.0.0.1/private?token=secret'}
    response = inspect(state, probe='yes', fictional='yes')
    assert response.status_code == 200, response.text
    assert summary(response)['anonymous_result'] == result
    assert summary(response)['privacy_assessment'] == 'inconclusive'
    assert len(state['anonymous']) == 1
    request = state['anonymous'][0]
    assert str(request.url) == attachment(state)['url']
    assert not any(key in request.headers for key in ('authorization', 'cookie', 'proxy-authorization'))
    options = state['anonymous_options'][0]
    assert options['auth'] is None and options['cookies'] == {} and options['trust_env'] is False
    assert options['follow_redirects'] is False and options['timeout'] == diagnostic._PROBE_SECONDS
    assert all(client.is_closed for client in state['clients'])
    assert 'secret' not in response.text and 'private' not in response.text


@pytest.mark.parametrize('url', [
    'https://zernio.com/api/v1/whatsapp/media/media-synthetic',
    'https://zernio.com/api/v1/whatsapp/media/media-synthetic?accountId=account-test'])
def test_probe_preserves_exact_canonical_query_presence(setup, url):
    attachment(setup)['url'] = url
    assert inspect(setup, probe='yes', fictional='yes').status_code == 200
    assert str(setup['anonymous'][0].url) == url


class PrefixStream(httpx.AsyncByteStream):
    def __init__(self):
        self.reads = 0
        self.closed = False
    async def __aiter__(self):
        for index in range(100):
            self.reads += 1
            yield (b'%PDF-' + b'x' * 59) if index == 0 else b'x' * 64
    async def aclose(self):
        self.closed = True


def test_anonymous_reads_only_bounded_prefix_and_reports_observation(setup):
    stream = PrefixStream()
    setup['anonymous_stream'] = stream
    setup['anonymous_status'] = 200
    response = inspect(setup, probe='yes', fictional='yes')
    assert response.status_code == 200, response.text
    assert summary(response)['anonymous_result'] == 'pdf_prefix_observed'
    assert summary(response)['privacy_assessment'] == 'public_bytes_observed'
    assert stream.reads == 4 and stream.closed
    assert '%PDF' not in response.text


@pytest.mark.parametrize('status', [403, 302])
def test_denial_redirect_never_reads_body(setup, status):
    stream = PrefixStream()
    setup['anonymous_stream'] = stream
    setup['anonymous_status'] = status
    assert inspect(setup, probe='yes', fictional='yes').status_code == 200
    assert stream.reads == 0 and stream.closed


def test_compressed_response_never_reads_or_decompresses(setup):
    stream = PrefixStream()
    setup.update(anonymous_stream=stream, anonymous_status=200, anonymous_headers={'content-encoding': 'gzip'})
    result = summary(inspect(setup, probe='yes', fictional='yes'))
    assert result['anonymous_result'] == 'encoded_response' and stream.reads == 0 and stream.closed


@pytest.mark.parametrize('error,result', [(httpx.ReadTimeout, 'timeout'), (httpx.ConnectError, 'network_error')])
def test_anonymous_error_sanitized_and_not_retried(setup, error, result):
    setup['anonymous_error'] = error
    response = inspect(setup, probe='yes', fictional='yes')
    assert summary(response)['anonymous_result'] == result
    assert len(setup['anonymous']) == 1 and 'private' not in response.text and 'token' not in response.text


@pytest.mark.parametrize('error,status', [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)])
def test_authenticated_error_sanitized_and_not_retried(setup, error, status):
    setup['provider_error'] = error
    response = inspect(setup)
    assert response.status_code == status and len(setup['requests']) == 1
    assert 'private' not in response.text and 'token' not in response.text


def test_authenticated_redirect_never_followed(setup):
    setup.update(provider_status=302, provider_headers={'Location': 'https://private.invalid?token=secret'})
    assert inspect(setup).status_code == 502
    assert len(setup['requests']) == 1 and not setup['anonymous']


def test_metadata_byte_limit_before_next_request(setup, monkeypatch):
    monkeypatch.setattr(diagnostic, '_METADATA_BYTES', 12)
    assert inspect(setup).status_code == 502
    assert len(setup['requests']) == 1 and not setup['anonymous']


@pytest.mark.parametrize('pagination', [{'hasMore': True}, {'hasMore': True, 'nextCursor': 'same'}])
def test_incomplete_or_repeated_pagination_fails_closed(setup, pagination):
    setup['conversations'] = []
    setup['conversation_pagination'] = pagination
    assert inspect(setup).status_code == 502 and not setup['anonymous']
    assert len(setup['requests']) <= 3


def test_metadata_lookup_page_limit(setup):
    setup['conversations'] = []
    setup['conversation_pagination'] = {'hasMore': True, 'nextCursor': 'first'}
    def next_page(request):
        setup['conversation_pagination']['nextCursor'] = 'cursor-' + str(len(setup['requests']))
    setup['on_read'] = next_page
    assert inspect(setup).status_code == 502
    assert len(setup['requests']) == 1 + diagnostic._MAX_PAGES and not setup['anonymous']


def test_whole_diagnostic_has_wall_clock_budget(setup, monkeypatch):
    monkeypatch.setattr(diagnostic, '_TOTAL_SECONDS', 0)
    assert inspect(setup).status_code == 504
    assert not setup['anonymous'] and all(client.is_closed for client in setup['clients'])


def test_anonymous_has_separate_wall_clock_budget(setup, monkeypatch):
    monkeypatch.setattr(diagnostic, '_PROBE_SECONDS', 0)
    response = inspect(setup, probe='yes', fictional='yes')
    assert response.status_code == 200 and summary(response)['anonymous_result'] == 'timeout'
    assert len(setup['anonymous']) <= 1 and all(client.is_closed for client in setup['clients'])


@pytest.mark.parametrize('identity', [None, ('../private', True), ('https://private.invalid', False),
    ('media?token=secret', False), ('media-synthetic', 'yes'), ('media-synthetic', True, 'extra')])
def test_anonymous_helper_revalidates_its_fixed_path_without_io(setup, identity):
    result = asyncio.run(diagnostic._anonymous_probe(identity, 'account-test'))
    assert result == ('not_eligible', 'inconclusive') and not setup['anonymous']


def test_query_target_never_accepted(setup):
    response = setup['client'].post('/whatsapp-inbox/documents/' + setup['item']['token'] +
        '/privacy-diagnostic?url=http://127.0.0.1/private', data=form(setup))
    assert response.status_code == 400 and not setup['requests'] and not setup['anonymous']


@pytest.mark.parametrize('change', ['mfa', 'session', 'user', 'account'])
def test_authority_revocation_after_metadata_blocks_further_reads_and_probe(setup, monkeypatch, change):
    def revoke(request):
        if change == 'mfa': setup['actor']['mfa'] = False
        if change == 'session': setup['actor']['id'] = 'changed-session'
        if change == 'user': setup['actor']['user_id'] = 8
        if change == 'account': monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID', 'changed-account')
    setup['on_read'] = revoke
    assert inspect(setup, probe='yes', fictional='yes').status_code in (409, 428)
    assert len(setup['requests']) == 1 and not setup['anonymous']


def test_receipt_changed_during_metadata_never_probed(setup):
    def change(request):
        if request.url.path.endswith('/messages'):
            setup['conn'].execute('UPDATE whatsapp_document_drafts SET provider_ids=?',
                                   (json.dumps(['different-receipt']),))
            setup['conn'].commit()
    setup['on_read'] = change
    assert inspect(setup, probe='yes', fictional='yes').status_code == 409
    assert not setup['anonymous']


def test_authority_revocation_during_anonymous_suppresses_result(setup):
    setup['on_anonymous'] = lambda request: setup['actor'].update(mfa=False)
    assert inspect(setup, probe='yes', fictional='yes').status_code == 428
    assert len(setup['anonymous']) == 1


def test_transport_logs_do_not_capture_provider_urls_headers_or_bodies(setup, caplog):
    caplog.set_level(logging.DEBUG)
    assert inspect(setup, probe='yes', fictional='yes').status_code == 200
    output = '\n'.join(record.getMessage() for record in caplog.records
                       if record.name.startswith(('httpx', 'httpcore')))
    for secret in ('zernio.com', 'accountId', 'media-synthetic', 'synthetic-only',
                   'provider_session', 'private body'):
        assert secret not in output


def test_optional_probe_does_not_change_frozen_send_state(setup):
    before = dict(setup['conn'].execute('SELECT * FROM whatsapp_document_drafts').fetchone())
    assert inspect(setup, probe='yes', fictional='yes').status_code == 200
    after = dict(setup['conn'].execute('SELECT * FROM whatsapp_document_drafts').fetchone())
    assert after == before and after['content_b64'] is None
    assert after['state'] == 'public_link_warning'
    assert hashlib.sha256(b'%PDF-1.7 Synthetic fixture only; no real document.').hexdigest() == after['sha256']


def test_result_is_plain_html_without_redirect_script_or_automatic_retry(setup):
    response = inspect(setup)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/html')
    assert 'location' not in response.headers
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert '<html lang="ar" dir="rtl">' in response.text
    assert '<script' not in response.text and '<form' not in response.text
    assert 'http-equiv' not in response.text
    assert 'href="/whatsapp-inbox"' in response.text
    assert 'لم تُحفظ هذه النتيجة' in response.text
    assert len(summary(response)) == 5
    assert len(setup['requests']) == 3 and not setup['anonymous']
