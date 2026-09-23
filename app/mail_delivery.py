"""Sanitized transport failures and narrow parsing of provider delivery notices."""
import re
from email.utils import parseaddr, parsedate_to_datetime


class MailRecipientRejected(RuntimeError):
    def __init__(self, code):
        self.code = int(code)
        self.permanent = self.code >= 500
        super().__init__(f'رفض خادم البريد المستلم (SMTP {self.code})؛ لم يقبل الرسالة.')


class MailConnectionFailed(RuntimeError):
    def __init__(self):
        super().__init__('تعذر الاتصال أو تسجيل الدخول إلى البريد قبل إرسال الرسالة.')


def delivery_notice(sender, subject, body, received):
    """Return only a named recipient in a recognized failure notice, never prose commands."""
    address = parseaddr(sender)[1].lower()
    if not (address == 'mailer-daemon@bounces.jellyfish.systems' or
            address.startswith('postmaster@')):
        return None
    if not any(s in subject.lower() for s in ('delivery status notification (failure)', 'undeliverable:')):
        return None
    patterns = (
        r'Delivery to the following recipient failed permanently:\s*([^\s<>]+@[^\s<>]+)',
        r'Your message to ([^\s<>]+@[^\s<>]+) couldn.t be delivered',
        r'Delivery has failed to these recipients or groups:\s*([^\s<>]+@[^\s<>]+)',
    )
    head = body[:2500]
    match = next((m for p in patterns if (m := re.search(p, head, re.I))), None)
    if not match:
        return None
    recipient = match.group(1).strip('.,;').lower()
    try:
        stamp = parsedate_to_datetime(received)
        if stamp.tzinfo is None:
            return None
    except (TypeError, ValueError):
        return None
    if re.search(r'mailbox (?:is )?full|5\.2\.2', head, re.I):
        return recipient, stamp, False, 'تعذر التسليم: صندوق المستلم ممتلئ.'
    if re.search(r'does not exist|wasn.t found|No MX server found|mailbox unavailable|Recipient address rejected', head, re.I):
        return recipient, stamp, True, 'ارتداد دائم من مزود البريد؛ استُبعد العنوان من الحملات.'
    return None
