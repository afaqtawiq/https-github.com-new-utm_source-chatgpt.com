"""No services, credentials, database, or actual mail sends are used here."""
from email import message_from_bytes, policy
from email.message import EmailMessage
from html import escape

import pytest

from app.mail_content import extract_content


def parse(raw):
    return message_from_bytes(raw.encode('utf-8'), policy=policy.default)


def mail(body='Hello', subtype='plain'):
    msg = EmailMessage()
    msg['From'] = 'Buyer <buyer@example.invalid>'
    msg['Subject'] = 'Cargo inquiry'
    msg.set_content(body, subtype=subtype)
    return msg


def dsn(action='failed', status='5.1.1', recipient='Buyer@Example.Invalid',
        original='<Original.Case@example.invalid>', per_message='', recipient_headers='',
        extra_recipients='', returned_type='message/rfc822', returned=None):
    returned = ('Message-ID: ' + original + '\nFrom: sender@example.invalid\n'
                'To: buyer@example.invalid\n\nOriginal message.') if returned is None else returned
    return parse('MIME-Version: 1.0\nFrom: postmaster@example.invalid\n'
                 'Subject: Delivery Status Notification (Failure)\n'
                 'Message-ID: <the-notice@example.invalid>\n'
                 'In-Reply-To: <untrusted-reply@example.invalid>\n'
                 'Content-Type: multipart/report; report-type=delivery-status; boundary=dsn\n\n'
                 '--dsn\nContent-Type: text/plain; charset=utf-8\n\nDelivery report.\n'
                 '--dsn\nContent-Type: message/delivery-status\n\n'
                 'Reporting-MTA: dns; example.invalid\n' + per_message + '\n'
                 'Final-Recipient: rfc822; ' + recipient + '\n'
                 'Action: ' + action + '\nStatus: ' + status + '\n' + recipient_headers +
                 extra_recipients + '\n--dsn\nContent-Type: ' + returned_type + '\n\n' + returned +
                 '\n--dsn--\n')


def test_plain_text_is_bounded_and_not_misrepresented_as_safe_html():
    result = extract_content(mail('<b>literal</b>\x00' + 'A' * 40000))
    assert result['body_format'] == 'plain'
    assert len(result['body']) == 32000
    assert result['body'].startswith('<b>literal</b>')
    assert '\x00' not in result['body']
    assert escape(result['body']).startswith('&lt;b&gt;literal&lt;/b&gt;')
    assert result['notice_kind'] == 'none'


def test_malicious_html_is_readable_inert_text_without_url_fetch(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Mail preview must not access the network')
    monkeypatch.setattr('socket.socket', forbidden)
    msg = mail('<head><title>Hidden title</title><style>hidden css</style></head>'
               '<h1>طلب شحن</h1><p>Hello &amp; goodbye<br>Second line</p>'
               '<script>sendCredentials()</script><iframe>iframe instructions</iframe>'
               '<svg><script>svg script</script>svg text</svg>'
               '<template>hidden template</template><!-- hidden comment -->'
               '<img src="https://track.invalid/pixel" onerror="steal()">'
               '<a href="https://track.invalid/click">Visible link</a>'
               '<p>&lt;img src=x onerror=evil()&gt;</p>', 'html')
    result = extract_content(msg)
    assert result['body_format'] == 'html_text'
    for value in ('طلب شحن', 'Hello & goodbye', 'Second line', 'Visible link'):
        assert value in result['body']
    for value in ('hidden', 'sendCredentials', 'iframe instructions', 'svg text', 'track.invalid', 'steal()'):
        assert value not in result['body']
    # Literal escaped markup is retained as text, escaped by the presentation layer.
    assert '&lt;img src=x onerror=evil()&gt;' in escape(result['body'])
    assert '<img' not in escape(result['body'])


def test_html_blocks_and_entities_remain_readable():
    result = extract_content(mail('<p>First&nbsp;line</p><p>Second line</p>'
                                  '<table><tr><td>One</td><td>Two</td></tr></table>', 'html'))
    assert result['body'] == 'First line\n\nSecond line\n\nOne Two'


def test_html_blockquotes_keep_their_authorship_boundary():
    result = extract_content(mail('<blockquote><p>STOP</p><p>Quoted instructions</p></blockquote>'
                                  '<p>Actual new text</p>', 'html'))
    lines = [line for line in result['body'].splitlines() if line.strip()]
    assert lines == ['> STOP', '> Quoted instructions', 'Actual new text']
    nested = extract_content(mail('<p>Hello</p><blockquote>Older text<blockquote>STOP</blockquote>'
                                  'Still quoted</blockquote><p>New text</p>', 'html'))['body']
    assert '> > STOP' in nested
    assert '\n> Still quoted' in nested
    assert nested.endswith('New text')


def test_plain_alternative_is_preferred_and_attached_text_is_ignored():
    msg = mail('Plain version')
    msg.add_alternative('<p>HTML version</p>', subtype='html')
    msg.add_attachment('Attachment with misleading body', filename='readme.txt')
    assert extract_content(msg)['body'] == 'Plain version\n'
    assert extract_content(msg)['body_format'] == 'plain'


def test_html_with_inline_image_and_attached_plaintext_uses_real_body():
    msg = mail('<p>Visible HTML body</p>', 'html')
    msg.add_related(b'not-an-image', maintype='image', subtype='png', cid='<tracking>')
    msg.add_attachment('False attachment body', filename='fake.txt')
    assert extract_content(msg)['body'] == 'Visible HTML body'
    assert extract_content(msg)['body_format'] == 'html_text'


def test_related_start_honored_and_unknown_start_not_guessed():
    msg = parse('Content-Type: multipart/related; boundary=x; start="<body>"\n\n'
                '--x\nContent-Type: text/plain\nContent-ID: <resource>\n\nNot the body\n'
                '--x\nContent-Type: text/html\nContent-ID: <body>\n\n<p>Actual body</p>\n--x--')
    assert extract_content(msg)['body'] == 'Actual body'
    msg.set_param('start', '<missing>')
    assert extract_content(msg)['body_format'] == 'unsupported'


def test_attached_forward_is_not_preview_or_notice_identity():
    msg = EmailMessage()
    msg.make_mixed()
    msg.add_attachment(dsn())
    result = extract_content(msg)
    assert result['body_format'] == 'unsupported'
    assert result['notice_kind'] == 'none'
    assert result['notice_message_id'] is None


def test_unknown_charset_and_invalid_bytes_are_safe():
    msg = message_from_bytes(b'Content-Type: text/html; charset=missing-charset\n\n<p>Good \xff</p>',
                             policy=policy.default)
    assert extract_content(msg)['body'] == 'Good \ufffd'


def test_unsupported_parts_and_deep_mime_are_bounded():
    msg = EmailMessage()
    msg.set_content(b'opaque', maintype='application', subtype='octet-stream')
    assert extract_content(msg)['body_format'] == 'unsupported'
    leaf = mail('Too deeply nested')
    for _ in range(25):
        outer = EmailMessage()
        outer.make_mixed()
        outer.attach(leaf)
        leaf = outer
    assert extract_content(leaf)['body_format'] == 'unsupported'
    assert len(extract_content(mail('<p>' + 'x' * 60000 + '</p>', 'html'))['body']) <= 32000


@pytest.mark.parametrize(('action', 'status', 'expected'), [
    ('failed', '5.1.1', 'delivery_failed'),
    ('delayed', '4.2.0', 'delivery_delayed'),
    ('failed', '4.1.1', 'delivery_notice'),
    ('delayed', '5.1.1', 'delivery_notice'),
    ('delivered', '2.0.0', 'delivery_notice'),
    ('failed', '5.1.1 trailing', 'delivery_notice'),
    ('failed', '550', 'delivery_notice'),
])
def test_structured_dsn_requires_consistent_action_and_status(action, status, expected):
    result = extract_content(dsn(action=action, status=status))
    assert result['notice_kind'] == expected
    assert result['notice_recipient'] == 'buyer@example.invalid'
    assert result['notice_message_id'] == '<Original.Case@example.invalid>'
    assert result['body'] == 'Delivery report.'


def test_returned_headers_can_supply_exact_original_id():
    result = extract_content(dsn(returned_type='text/rfc822-headers',
                                 returned='Message-ID: <Exact.Case@example.invalid>\nSubject: Original\n'))
    assert result['notice_message_id'] == '<Exact.Case@example.invalid>'


def test_original_message_id_in_dsn_without_returned_original():
    msg = dsn(per_message='Original-Message-ID: <DSN.Source@example.invalid>\n')
    msg.set_payload(msg.get_payload()[:2])
    assert extract_content(msg)['notice_message_id'] == '<DSN.Source@example.invalid>'


def test_dsn_own_id_and_references_are_never_original_identity():
    msg = dsn()
    msg.set_payload(msg.get_payload()[:2])
    msg['References'] = '<pretended-original@example.invalid>'
    assert extract_content(msg)['notice_message_id'] is None


def test_returned_id_identical_to_notice_own_id_is_rejected():
    assert extract_content(dsn(original='<the-notice@example.invalid>'))['notice_message_id'] is None


def test_ambiguous_mime_headers_and_truncated_report_stay_generic():
    raw = dsn().as_bytes()
    for malformed in (
        raw.replace(b'Content-Type: multipart/report;', b'Content-Type: text/plain\nContent-Type: multipart/report;', 1),
        raw.replace(b'report-type=delivery-status;', b'report-type=delivery-status; report-type=other;', 1),
        raw.replace(b'--dsn--', b''),
    ):
        assert malformed != raw
        result = extract_content(message_from_bytes(malformed, policy=policy.default))
        assert result['notice_kind'] == 'delivery_notice'
        assert result['notice_message_id'] is None


def test_standalone_delivery_status_can_supply_original_id():
    msg = parse('Content-Type: message/delivery-status\n\nReporting-MTA: dns; example.invalid\n'
                'Original-Message-ID: <original@example.invalid>\n\n'
                'Final-Recipient: rfc822; buyer@example.invalid\nAction: delayed\nStatus: 4.2.0\n')
    result = extract_content(msg)
    assert result['notice_kind'] == 'delivery_delayed'
    assert result['notice_message_id'] == '<original@example.invalid>'


def test_conflicting_or_malformed_original_ids_fail_closed():
    assert extract_content(dsn(per_message='Original-Message-ID: <different@example.invalid>\n'))['notice_message_id'] is None
    assert extract_content(dsn(per_message='Original-Message-ID: malformed\n'))['notice_message_id'] is None
    assert extract_content(dsn(returned='Message-ID: <one@example.invalid>\nMessage-ID: <two@example.invalid>\n\n'))['notice_message_id'] is None
    assert extract_content(dsn(returned='Subject: ID missing\n\nMessage-ID: <body@example.invalid>'))['notice_message_id'] is None


def test_duplicate_original_headers_even_identical_are_rejected():
    result = extract_content(dsn(per_message='Original-Message-ID: <Original.Case@example.invalid>\n'
                                            'Original-Message-ID: <Original.Case@example.invalid>\n'))
    assert result['notice_message_id'] is None


def test_nested_forward_id_not_used_when_original_lacks_id():
    forwarded = ('Content-Type: multipart/mixed; boundary=fwd\n\n'
                 '--fwd\nContent-Type: text/plain\n\nSee attached\n'
                 '--fwd\nContent-Type: message/rfc822\n\n'
                 'Message-ID: <forwarded@example.invalid>\n\nForwarded mail\n--fwd--\n')
    assert extract_content(dsn(returned=forwarded))['notice_message_id'] is None


def test_original_top_level_id_is_not_confused_with_nested_forward():
    forwarded = ('Message-ID: <actual-original@example.invalid>\n'
                 'Content-Type: multipart/mixed; boundary=fwd\n\n'
                 '--fwd\nContent-Type: message/rfc822\n\n'
                 'Message-ID: <forwarded@example.invalid>\n\nForwarded mail\n--fwd--\n')
    assert extract_content(dsn(returned=forwarded))['notice_message_id'] == '<actual-original@example.invalid>'


@pytest.mark.parametrize('recipient_headers', [
    'Final-Recipient: rfc822; second@example.invalid\n',
    'Final-Recipient: rfc822; Buyer@Example.Invalid\n',
    'Original-Recipient: rfc822; other@example.invalid\n',
    'Original-Recipient: rfc822; buyer@example.invalid\nOriginal-Recipient: rfc822; buyer@example.invalid\n',
])
def test_ambiguous_recipient_never_has_definitive_outcome(recipient_headers):
    result = extract_content(dsn(recipient_headers=recipient_headers))
    assert result['notice_kind'] == 'delivery_notice'
    assert result['notice_recipient'] is None
    assert result['notice_message_id'] is None


def test_multiple_recipient_blocks_are_ambiguous_even_when_identical():
    extra = '\nFinal-Recipient: rfc822; buyer@example.invalid\nAction: failed\nStatus: 5.1.1\n'
    result = extract_content(dsn(extra_recipients=extra))
    assert result['notice_kind'] == 'delivery_notice'
    assert result['notice_recipient'] is None


@pytest.mark.parametrize('recipient', ['One <buyer@example.invalid>', 'a@example.invalid,b@example.invalid', 'bad', 'x@example.invalid;other@example.invalid'])
def test_invalid_dsn_recipient_is_never_guessed(recipient):
    assert extract_content(dsn(recipient=recipient))['notice_kind'] == 'delivery_notice'
    assert extract_content(dsn(recipient=recipient))['notice_recipient'] is None


@pytest.mark.parametrize('recipient_headers', ['Action: failed\n', 'Status: 5.1.1\n'])
def test_duplicate_action_and_status_never_have_definitive_outcome(recipient_headers):
    assert extract_content(dsn(recipient_headers=recipient_headers))['notice_kind'] == 'delivery_notice'


def test_two_dsn_parts_or_returned_messages_are_not_silently_selected():
    msg = dsn()
    msg.attach(msg.get_payload()[1])
    result = extract_content(msg)
    assert result['notice_kind'] == 'delivery_notice'
    assert result['notice_recipient'] is None
    msg = dsn()
    msg.attach(msg.get_payload()[2])
    assert extract_content(msg)['notice_message_id'] is None


def test_non_dsn_multipart_and_forwarded_notice_not_treated_as_dsn():
    msg = dsn()
    msg.replace_header('From', 'buyer@example.invalid')
    msg.replace_header('Content-Type', 'multipart/mixed; boundary=dsn')
    assert extract_content(msg)['notice_kind'] == 'none'


def test_textual_bounce_requires_notice_sender_and_subject_and_stays_generic():
    msg = mail('Delivery to buyer@example.invalid failed permanently. Status: 5.1.1')
    assert extract_content(msg)['notice_kind'] == 'none'
    msg.replace_header('Subject', 'Delivery Status Notification (Failure)')
    assert extract_content(msg)['notice_kind'] == 'none'
    msg.replace_header('From', 'Mail Delivery System <mailer-daemon@example.invalid>')
    result = extract_content(msg)
    assert result['notice_kind'] == 'delivery_notice'
    assert result['notice_recipient'] is None
    assert result['notice_message_id'] is None
    msg.replace_header('Subject', 'A normal discussion about bouncing a message')
    assert extract_content(msg)['notice_kind'] == 'none'


def test_valid_original_recipient_agreement_is_canonicalized():
    result = extract_content(dsn(recipient_headers='Original-Recipient: rfc822; BUYER@example.invalid\n'))
    assert result['notice_kind'] == 'delivery_failed'
    assert result['notice_recipient'] == 'buyer@example.invalid'


def test_compat32_email_message_is_supported():
    raw = b'Content-Type: text/html; charset=utf-8\n\n<p>Legacy message</p>'
    assert extract_content(message_from_bytes(raw))['body'] == 'Legacy message'
