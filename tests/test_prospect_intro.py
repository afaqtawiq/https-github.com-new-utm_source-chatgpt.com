"""Pure prospect safeguards. No database bootstrap, network, or module-cache leakage."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import types
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException


@pytest.fixture(scope='module')
def prospect():
    # Load only this file under a fresh private name. Restore sys.modules after
    # import so these tests cannot replace app.storage for neighboring suites.
    storage = types.ModuleType('app.storage')
    for name in ('db', 'one', 'rows', 'utcnow', 'get_session'):
        setattr(storage, name, Mock(side_effect=AssertionError('Pure test touched storage: '+name)))
    path = Path(__file__).resolve().parents[1] / 'app' / 'prospect_outreach.py'
    spec = importlib.util.spec_from_file_location('_prospect_intro_pure_tests', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'app.storage': storage}):
        spec.loader.exec_module(module)
    return module


def page(**changes):
    value = {'url': 'https://fixture.example.invalid/contact', 'title': 'Fixture Trading LLC',
             'request_text': 'Fixture Trading LLC official contact: buyer@fixture.example.invalid',
             'detail_extracted': False}
    value.update(changes)
    return value


def verify(prospect, value=None, recipient='buyer@fixture.example.invalid', identity='Fixture Trading LLC', url=None):
    source = value or page()
    with patch('app.discovery.fetch_public', return_value=source) as fetch:
        result = prospect.verify_source(url or 'https://fixture.example.invalid/contact', recipient, identity)
        fetch.assert_called_once()
        return result


def test_public_contact_is_a_prospect_without_fabricating_a_request(prospect):
    from app.opportunity_quality import assess
    source = page()
    assert not assess(source['title'], source['request_text'], source['url'])['is_request']
    assert verify(prospect, source) == source


@pytest.mark.parametrize('recipient', ['BUYER@fixture.example.invalid', ' buyer@fixture.example.invalid '])
def test_canonical_plain_address_and_case(prospect, recipient):
    assert prospect.canonical(recipient) == 'buyer@fixture.example.invalid'


@pytest.mark.parametrize('recipient', ['', None, 'not-an-email', 'Name <buyer@fixture.example.invalid>',
    'buyer@fixture.example.invalid,other@fixture.example.invalid',
    'buyer@fixture.example.invalid\r\nBcc: outsider@example.invalid'])
def test_recipient_lists_display_names_and_header_injection_rejected(prospect, recipient):
    with pytest.raises(HTTPException) as exc:
        prospect.canonical(recipient)
    assert exc.value.status_code == 400


@pytest.mark.parametrize('url', ['http://fixture.example.invalid/contact', 'ftp://fixture.example.invalid/contact',
    'https://user:secret@fixture.example.invalid/contact', 'https://fixture.example.invalid:444/contact',
    'https://fixture.example.invalid/contact#fragment', 'https://lookalike.example.invalid/contact',
    'https://fixture.example.invalid.attacker.invalid/contact'])
def test_nonofficial_source_identity_fails_before_fetch(prospect, url):
    with patch('app.discovery.fetch_public', side_effect=AssertionError('Unsafe source should not be fetched')) as fetch:
        with pytest.raises((ValueError, HTTPException)):
            prospect.verify_source(url, 'buyer@fixture.example.invalid', 'Fixture Trading LLC')
        fetch.assert_not_called()


@pytest.mark.parametrize('changed', [
    {'url': 'https://another.example.invalid/contact'},
    {'url': 'http://fixture.example.invalid/contact'},
    {'request_text': 'Fixture Trading LLC contact: other@fixture.example.invalid'},
    {'request_text': 'Contact buyer@fixture.example.invalid', 'title': 'Unrelated Entity'},
    {'request_text': 'Fixture Trading LLC contact: buyer@fixture.example.invalid.attacker.invalid'},
    {'request_text': 'Fixture Trading LLC contact: legal!buyer@fixture.example.invalid'},
    {'request_text': 'Fixture Trading LLC contact: legal%buyer@fixture.example.invalid'},
    {'request_text': 'Fixture Trading LLC contact: legal+buyer@fixture.example.invalid'},
])
def test_source_reverification_requires_exact_email_and_identity(prospect, changed):
    with pytest.raises((ValueError, HTTPException)):
        verify(prospect, page(**changed))


def test_exact_published_address_supports_legal_local_part_characters(prospect):
    recipient = 'legal!buyer@fixture.example.invalid'
    assert verify(prospect, page(request_text='Fixture Trading LLC '+recipient), recipient=recipient)


def test_source_fetch_failures_never_become_verified(prospect):
    with patch('app.discovery.fetch_public', side_effect=TimeoutError('fixture only')):
        with pytest.raises(TimeoutError):
            prospect.verify_source(page()['url'], 'buyer@fixture.example.invalid', 'Fixture Trading LLC')


def test_arabic_identity_normalization_and_html_entities(prospect):
    source = page(title='شركة أفق التجارية', request_text='شَرِكَة أفق التجارية: buyer&#64;fixture.example.invalid')
    assert verify(prospect, source, identity='شركة افق التجارية') == source


def message():
    return {'purpose': 'intro_prospect', 'prospect_id': 3, 'opportunity_id': None, 'reply_inbox_id': None,
            'mail_user_id': 7, 'recipient': 'buyer@fixture.example.invalid', 'subject': 'تعريف',
            'body': 'مقدمة راجعها المالك\nReply STOP to opt out.', 'proposal_text': ''}


def test_digest_is_deterministic_sha256_of_exact_approved_content(prospect):
    original = message()
    expected = hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert prospect.content_digest(original) == expected
    assert re.fullmatch('[0-9a-f]{64}', expected)
    assert prospect.content_digest(dict(reversed(list(original.items())))) == expected
    assert prospect.content_digest({**original, 'status': 'sent', 'provider_message_id': '<fixture@id>', 'updated_at': 'later'}) == expected


@pytest.mark.parametrize('field,changed', [
    ('purpose', 'public_request'), ('prospect_id', 99), ('opportunity_id', 9), ('reply_inbox_id', 5),
    ('mail_user_id', 8), ('recipient', 'other@fixture.example.invalid'), ('subject', 'Changed'),
    ('body', 'Changed'), ('body', message()['body']+' '), ('proposal_text', 'Injected proposal'),
])
def test_digest_binds_every_authorized_identity_and_content_field(prospect, field, changed):
    original = message()
    assert prospect.content_digest({**original, field: changed}) != prospect.content_digest(original)


@pytest.mark.parametrize('body', [
    'STOP', ' stop! ', 'Unsubscribe', 'remove me', 'Please stop', 'Please unsubscribe',
    'إيقاف', 'الرجاء إيقاف الرسائل', 'لا ترسلوا لي رسائل أخرى',
    'Stop\nFixture Person', 'إيقاف\nقسم المشتريات', 'Unsubscribe\n\nSent from my mobile',
    'STOP\n\nOn Tuesday Fixture wrote:\n> Reply STOP to opt out.',
    'Please stop emailing us', 'Please remove me from your mailing list',
])
def test_authored_optout_with_signature_is_respected(prospect, body):
    assert prospect.stop_requested(body)


@pytest.mark.parametrize('body', [
    '', None, 'Thanks, we will review the introduction.', 'Reply STOP to opt out.',
    '> STOP', 'On Tuesday Fixture wrote:\nSTOP', 'From: Fixture\nUnsubscribe',
    'Thanks\n\n> Reply STOP to opt out.', 'Please do not unsubscribe me',
    'The shipment will stop at the depot', 'We cannot stop our shipment',
    'هل يمكنكم شرح الخدمات؟\n> إيقاف',
])
def test_quoted_footer_and_incidental_stop_words_are_not_optout(prospect, body):
    assert not prospect.stop_requested(body)


def test_email_or_url_substring_does_not_prove_company_identity(prospect):
    for text in ('Contact buyer@fixture.example.invalid', 'https://fixture.example.invalid/contact buyer@fixture.example.invalid'):
        with pytest.raises(ValueError):
            verify(prospect, page(title='Contact us', request_text=text), identity='Fixture')
    with pytest.raises(ValueError):
        verify(prospect, page(title='FixtureGroup LLC', request_text='buyer@fixture.example.invalid'), identity='Fixture')


def test_sentence_punctuation_does_not_hide_exact_published_email(prospect):
    assert verify(prospect, page(request_text='Fixture Trading LLC: buyer@fixture.example.invalid.'))


def test_metadata_contact_can_verify_prospect_but_cannot_invent_company_identity(prospect):
    source = page(request_text='Fixture Trading LLC official contact page',
                  public_contact_emails=['buyer@fixture.example.invalid'])
    assert verify(prospect, source) == source
    with pytest.raises(ValueError):
        verify(prospect, {**source, 'title': 'Contact', 'request_text': ''})


def test_contact_metadata_does_not_weaken_original_buyer_request_guard(prospect):
    from app.opportunity_quality import assess, verify_public_request
    source = page(url='https://fixture.example.invalid/request/1', title='Fixture Trading LLC',
                  request_text='We need freight transport. Contact our procurement team.',
                  detail_extracted=True, public_contact_emails=['buyer@fixture.example.invalid'])
    assert assess(source['title'], source['request_text'], source['url'])['is_request']
    with patch('app.discovery.fetch_public', return_value=source):
        # The request exists, but its own extracted text does not prove this address.
        with pytest.raises(ValueError):
            verify_public_request(source['url'], 'buyer@fixture.example.invalid')
        assert verify_public_request(source['url']) == source


def test_fetch_public_keeps_raw_contact_metadata_separate_from_request_text():
    from app import discovery
    html = ('<title>Fixture Trading LLC</title><article>We need freight transport.</article>'
            '<a href="mailto:legal!buyer@fixture.example.invalid">Contact procurement</a>'
            '<script type="application/json">{"email":"buyer@fixture.example.invalid"}</script>')
    response = Mock(text=html, url='https://fixture.example.invalid/request/1', status_code=200,
                    headers={'content-type': 'text/html'})
    client = Mock(); client.get.return_value = response
    with patch.object(discovery, 'safe_url', return_value=True), patch.object(discovery.httpx, 'Client') as factory:
        factory.return_value.__enter__.return_value = client
        result = discovery.fetch_public(str(response.url))
    assert result['public_contact_emails'] == ['buyer@fixture.example.invalid', 'legal!buyer@fixture.example.invalid']
    assert result['request_text'] == 'We need freight transport.'
    assert result['detail_extracted'] is True
