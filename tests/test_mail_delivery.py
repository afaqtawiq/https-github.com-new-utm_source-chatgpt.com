from app.mail_delivery import delivery_notice, MailRecipientRejected


def test_provider_bounce_is_recipient_scoped():
    result = delivery_notice('Mail Delivery Subsystem <mailer-daemon@bounces.jellyfish.systems>',
        'Delivery Status Notification (Failure)',
        'Delivery to the following recipient failed permanently:\n target@example.com\n'
        '550 5.1.1 The email account does not exist.', 'Wed, 23 Sep 2026 06:03:43 +0000')
    assert result[0] == 'target@example.com' and result[2] is True


def test_mailbox_full_is_not_permanent_suppression():
    result = delivery_notice('postmaster@outlook.com', 'Undeliverable: brochure',
        "Delivery has failed to these recipients or groups:\n target@example.com<mailto:target@example.com>\nThe recipient's mailbox is full",
        'Wed, 23 Sep 2026 06:03:43 +0000')
    assert result[0] == 'target@example.com' and result[2] is False


def test_unrelated_messages_and_bad_dates_are_not_bounces():
    args = ['person@example.com', 'Undeliverable: brochure',
        'Delivery to the following recipient failed permanently: target@example.com\nmailbox unavailable',
        'Wed, 23 Sep 2026 06:03:43 +0000']
    assert delivery_notice(*args) is None
    args[0] = 'postmaster@example.com'
    args[3] = 'invalid'
    assert delivery_notice(*args) is None


def test_rejection_codes_distinguish_temporary_and_permanent():
    assert not MailRecipientRejected(450).permanent
    assert MailRecipientRejected(550).permanent
