"""Pure, bounded mail previews and conservative delivery-notice metadata.

``body`` is Unicode text, never safe HTML. Callers must escape it at the final
presentation boundary, just like any other untrusted mail field. No URLs,
images, styles, scripts, or attachments are fetched or rendered here.
"""
import re
from email import policy
from email.parser import BytesHeaderParser
from html.parser import HTMLParser

from app.mail_threads import ADDRESS, address, message_id

MAX_BODY = 32000
_MAX_SOURCE = 262144
_MAX_DEPTH = 20
_MAX_PARTS = 100
_UNSUPPORTED = 'تعذر عرض محتوى الرسالة النصي؛ افتحها من بريد Spacemail لعرضها.'
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_STATUS = re.compile(r'[245]\.[0-9]{1,3}\.[0-9]{1,3}')
_NOTICE_SUBJECT = re.compile(
    r'^(?:delivery (?:status notification|failure|failed|delayed|notification)|'
    r'undeliverable\b|undelivered mail\b|returned mail\b|mail delivery (?:failed|failure)|'
    r'failure notice\b|warning: message.*(?:delayed|undelivered))', re.I)


def _clean(text):
    return _CONTROL.sub('', text.replace('\r\n', '\n').replace('\r', '\n'))


def _bytes(part):
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload[:_MAX_SOURCE]
    return None


def _decode(part):
    payload = _bytes(part)
    if payload is None:
        payload = part.get_payload()
        return payload[:_MAX_SOURCE] if isinstance(payload, str) else ''
    charset = part.get_content_charset() or 'utf-8'
    try:
        return payload.decode(charset, errors='replace')
    except (LookupError, UnicodeError):
        return payload.decode('utf-8', errors='replace')


class _TextHTML(HTMLParser):
    # Suppress active content and non-body metadata completely, not only tags.
    _drop = frozenset(('head', 'script', 'style', 'title', 'template', 'noscript',
                       'iframe', 'object', 'svg', 'math', 'canvas'))
    _block = frozenset(('address', 'article', 'aside', 'blockquote', 'br', 'dd',
                        'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure',
                        'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                        'header', 'hr', 'li', 'main', 'nav', 'ol', 'p', 'pre',
                        'section', 'table', 'tr', 'ul'))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.pieces = []
        self.size = 0
        self.quote_depth = 0
        self.line_start = True

    def _append(self, value):
        if not value or self.size >= MAX_BODY:
            return
        quoted = []
        for line in value.splitlines(keepends=True):
            if self.line_start and line != '\n' and self.quote_depth:
                quoted.append('> ' * self.quote_depth)
            quoted.append(line)
            self.line_start = line.endswith('\n')
        value = ''.join(quoted)
        # Bound storage as well as the final output.
        value = value[:max(0, MAX_BODY - self.size)]
        if value:
            self.pieces.append(value)
            self.size += len(value)

    def handle_starttag(self, tag, attrs):
        if tag in self._drop:
            self.hidden.append(tag)
        if not self.hidden:
            if tag == 'blockquote':
                self._append('\n')
                self.quote_depth += 1
            elif tag in self._block:
                self._append('\n')
            elif tag in ('td', 'th'):
                self._append(' ')

    def handle_startendtag(self, tag, attrs):
        if tag not in self._drop:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in self.hidden:
            last = len(self.hidden) - 1 - self.hidden[::-1].index(tag)
            del self.hidden[last:]
        elif not self.hidden and tag == 'blockquote':
            self._append('\n')
            self.quote_depth = max(0, self.quote_depth - 1)
        elif not self.hidden and tag in self._block:
            self._append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self._append(re.sub(r'\s+', ' ', _clean(data)))

    def text(self):
        text = ''.join(self.pieces)
        text = '\n'.join(line.strip() for line in text.splitlines())
        return re.sub(r'\n{3,}', '\n\n', text).strip()[:MAX_BODY]


def _html_text(value):
    parser = _TextHTML()
    parser.feed(value[:_MAX_SOURCE])
    parser.close()
    return parser.text()


def _body(part, budget, depth=0):
    """Find display content without walking into attached/forwarded messages."""
    if depth > _MAX_DEPTH or budget[0] <= 0:
        return None
    budget[0] -= 1
    if part.get_content_disposition() == 'attachment' or part.get_filename():
        return None
    kind = part.get_content_type()
    if kind == 'text/plain':
        return _clean(_decode(part))[:MAX_BODY], 'plain'
    if kind == 'text/html':
        return _html_text(_decode(part)), 'html_text'
    if part.get_content_maintype() != 'multipart' or kind == 'multipart/encrypted':
        return None
    children = part.get_payload()
    if not isinstance(children, list):
        return None
    if kind == 'multipart/related':
        start = part.get_param('start')
        if start:
            roots = [p for p in children if str(p.get('Content-ID', '')).strip() == start]
            children = roots if len(roots) == 1 else []
        else:
            children = children[:1]
    elif kind in ('multipart/report', 'multipart/signed'):
        children = children[:1]
    alternative = None
    for child in children[:_MAX_PARTS]:
        found = _body(child, budget, depth + 1)
        if found:
            if kind != 'multipart/alternative' or found[1] == 'plain':
                return found
            alternative = alternative or found
    return alternative


def _one(part, name):
    values = part.get_all(name, [])
    return str(values[0]).strip() if len(values) == 1 else None


def _invalid_type(part):
    values = part.get_all('Content-Type', [])
    return len(values) != 1 or bool(getattr(values[0], 'defects', ()))


def _recipient(value):
    if not value or ';' not in value:
        return None
    kind, value = value.split(';', 1)
    value = value.strip()
    if kind.strip().lower() != 'rfc822' or not ADDRESS.fullmatch(value):
        return None
    return value.lower()


def _original_id(blocks, returned):
    """Only direct DSN/original headers qualify; never References or a walk()."""
    identities = []
    for block in blocks:
        if block.get_all('Original-Message-ID', []):
            mid = message_id(_one(block, 'Original-Message-ID'))
            if not mid:
                return None
            identities.append(mid)
    if len(returned) > 1:
        return None
    for part in returned:
        if part.get_content_type() == 'message/rfc822':
            payload = part.get_payload()
            if not isinstance(payload, list) or len(payload) != 1:
                return None
            original = payload[0]
        else:
            payload = _bytes(part)
            if payload is None:
                return None
            original = BytesHeaderParser(policy=policy.default).parsebytes(payload)
        mid = message_id(_one(original, 'Message-ID'))
        if not mid:
            return None
        identities.append(mid)
    return identities[0] if identities and len(set(identities)) == 1 else None


def _notice(msg):
    empty = {'notice_kind': 'none', 'notice_recipient': None, 'notice_message_id': None}
    kind = msg.get_content_type()
    report = (kind == 'multipart/report'
              and str(msg.get_param('report-type', '')).lower() == 'delivery-status')
    children = msg.get_payload() if report else []
    children = children if isinstance(children, list) else []
    statuses = [p for p in children if p.get_content_type() == 'message/delivery-status']
    if kind == 'message/delivery-status':
        statuses = [msg]
    if report or statuses:
        result = dict(empty, notice_kind='delivery_notice')
        report_types = [v for k, v in (msg.get_params() or []) if k.lower() == 'report-type']
        if (len(statuses) != 1 or msg.defects or _invalid_type(msg)
                or (report and len(report_types) != 1)
                or statuses[0].defects or _invalid_type(statuses[0])):
            return result
        blocks = statuses[0].get_payload()
        # First block is per-message; exactly one following recipient is allowed.
        if (not isinstance(blocks, list) or len(blocks) != 2
                or any(blocks[0].get_all(h, []) for h in ('Action', 'Status', 'Final-Recipient', 'Original-Recipient'))):
            return result
        recipient = _recipient(_one(blocks[1], 'Final-Recipient'))
        original_recipients = blocks[1].get_all('Original-Recipient', [])
        if (not recipient or (original_recipients
                and _recipient(_one(blocks[1], 'Original-Recipient')) != recipient)):
            return result
        result['notice_recipient'] = recipient
        returned = [p for p in children if p.get_content_type() in ('message/rfc822', 'text/rfc822-headers')]
        result['notice_message_id'] = _original_id(blocks, returned)
        if result['notice_message_id'] in {message_id(v) for v in msg.get_all('Message-ID', [])}:
            result['notice_message_id'] = None
        action = (_one(blocks[1], 'Action') or '').lower()
        status = _one(blocks[1], 'Status') or ''
        if _STATUS.fullmatch(status):
            if action == 'failed' and status.startswith('5.'):
                result['notice_kind'] = 'delivery_failed'
            elif action == 'delayed' and status.startswith('4.'):
                result['notice_kind'] = 'delivery_delayed'
        return result
    sender = address(_one(msg, 'From'))
    subject = _one(msg, 'Subject') or ''
    if (sender and sender.split('@', 1)[0] in ('mailer-daemon', 'postmaster', 'bounce', 'bounces')
            and _NOTICE_SUBJECT.match(subject)):
        return dict(empty, notice_kind='delivery_notice')
    return empty


def extract_content(msg):
    """Return bounded inert preview text and exact, conservative DSN metadata.

    A structured action is a reported delivery outcome, not authentication of
    its sender. Callers must still verify the exact original ID, recipient,
    mailbox ownership, and thread uniqueness before changing delivery state.
    Ambiguous/malformed DSNs remain a generic notice for manual review.
    """
    preview = _body(msg, [_MAX_PARTS])
    body, body_format = preview if preview is not None else (_UNSUPPORTED, 'unsupported')
    return {'body': body, 'body_format': body_format, **_notice(msg)}
