"""Conservative RFC message identity helpers; never match subjects or domains."""
import re
from email.utils import getaddresses

MID = re.compile(r'<[^\s<>\x00-\x1f\x7f]{1,450}>')
ADDRESS = re.compile(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I)


def message_id(value):
    value = str(value or '').strip()
    return value if MID.fullmatch(value) else None


def references(value):
    # Reject malformed or overlong headers rather than partially trusting them.
    value = str(value or '').strip()
    if len(value) > 16000:
        return []
    ids = MID.findall(value)
    if MID.sub('', value).strip():
        return []
    return list(dict.fromkeys(ids)) if len(ids) <= 30 else []


def address(value):
    if any(c in str(value or '') for c in '\r\n\x00'):
        return None
    found = getaddresses([str(value or '')])
    if len(found) != 1 or not ADDRESS.fullmatch(found[0][1]):
        return None
    return found[0][1].lower()


def headers(msg, own):
    sender = address(str(msg.get('From', ''))) if len(msg.get_all('From', [])) == 1 else None
    reply_headers = msg.get_all('Reply-To', [])
    reply_to = address(str(msg.get('Reply-To', ''))) if len(reply_headers) == 1 else (sender if not reply_headers else None)
    to = [a.lower() for _, a in getaddresses(msg.get_all('To', []) + msg.get_all('Cc', []))]
    mid = message_id(msg.get('Message-ID')) if len(msg.get_all('Message-ID', [])) == 1 else None
    parent = message_id(msg.get('In-Reply-To')) if len(msg.get_all('In-Reply-To', [])) == 1 else None
    refs = references(msg.get('References')) if len(msg.get_all('References', [])) == 1 else []
    automated = (str(msg.get('Auto-Submitted', 'no')).lower() != 'no' or msg.get('List-Id')
                 or msg.get('List-Unsubscribe') or msg.get('X-Auto-Response-Suppress')
                 or str(msg.get('Precedence', '')).lower() in ('bulk', 'list', 'junk')
                 or str(msg.get('Return-Path', '')).strip() == '<>')
    threading_valid = (len(msg.get_all('In-Reply-To', [])) <= 1 and len(msg.get_all('References', [])) <= 1
                       and (not msg.get('In-Reply-To') or parent) and (not msg.get('References') or refs))
    safe = bool(mid and sender and sender != own and reply_to == sender and own in to and not automated and threading_valid)
    return {'message_id': mid, 'sender_address': sender, 'in_reply_to': parent,
            'message_references': ' '.join(refs), 'manual_reply_address': sender if safe else None}


def select_match(candidates, sender, user_id, parent=None, reference_ids=()):
    """All recognized ancestors must agree, including identity/owner, or review."""
    if not candidates:
        return None, 'no_exact_thread'
    if any((c.get('recipient') or '').strip().lower() != sender or c.get('mail_user_id') != user_id for c in candidates):
        return None, 'sender_or_mailbox_mismatch'
    # A prospect is its own identity, never an invented request or customer.
    # Keep every recognized ancestor within exactly one kind of identity.
    identities = {(c.get('opportunity_id'), c.get('account_id'), c.get('prospect_id')) for c in candidates}
    if (len(identities) != 1
            or any(bool(c.get('opportunity_id')) == bool(c.get('prospect_id')) for c in candidates)
            or any(c.get('prospect_id') and c.get('account_id') is not None for c in candidates)):
        return None, 'ambiguous_thread'
    by_identity = {}
    for item in candidates:
        identity = item.get('provider_message_id')
        if not identity or identity in by_identity:
            return None, 'duplicate_thread_identity'
        by_identity[identity] = item
    if parent in by_identity:
        return by_identity[parent], 'exact_thread'
    for identity in reversed(reference_ids):
        if identity in by_identity:
            return by_identity[identity], 'exact_thread'
    return None, 'no_exact_thread'
