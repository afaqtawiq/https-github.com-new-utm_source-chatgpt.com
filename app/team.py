"""Afaq Tuwaiq team on WhatsApp.

The team list comes from the AFAQ_TEAM environment variable (JSON list of
{"phone": "+9665...", "name": "...", "short": "...", "role": "...", "manager": true|false}).
* Every listed number is recognised with the same provider-identity checks as the original owner
  check (account, direction, private chat, participant), never by names or message text.
* Every team member has the full WhatsApp command set: adding drivers and shipments, voice notes (with
  the confirmation code), questions, tariff lookups, search, reports and load screenshots.
* The manager (manager=true, or the WHATSAPP_COMMAND_OWNER number) is addressed with "أستاذ".
* Every reply to a team member starts with a respectful Saudi greeting with their name.
"""
import contextvars
import json
import os
import random

from app import whatsapp_admin as admin

ROLE = contextvars.ContextVar('afaq_team_member', default=None)
TEAM_GREETINGS = ['طال عمرك يا {n}', 'أبشر يا {n}', 'تحت أمرك يا {n}', 'الله يعطيك العافية يا {n}', 'من عيوني يا {n}']
MANAGER_GREETINGS = ['طال عمرك يا أستاذ {n}', 'أبشر يا أستاذ {n}', 'تحت أمرك يا أستاذ {n}', 'من عيوني يا أستاذ {n}']


def team():
    try:
        members = json.loads(os.getenv('AFAQ_TEAM', '[]'))
    except ValueError:
        members = []
    out = {}
    for m in members if isinstance(members, list) else []:
        number = admin.phone(m.get('phone')) if isinstance(m, dict) else ''
        if number:
            out[number] = {'name': str(m.get('name') or ''), 'short': str(m.get('short') or m.get('name') or '').strip(),
                           'role': str(m.get('role') or ''), 'manager': bool(m.get('manager'))}
    owner = admin.phone(os.getenv('WHATSAPP_COMMAND_OWNER', ''))
    if owner:
        out.setdefault(owner, {'name': 'المدير', 'short': '', 'role': 'المدير', 'manager': True})['manager'] = True
    return out


def identify(payload):
    """Same provider-identity checks as whatsapp_admin.owner_sender, for every team number."""
    members = team()
    account_id = os.getenv('WHATSAPP_COMMAND_ACCOUNT_ID', '')
    account = payload.get('account') or {}
    message = payload.get('message') or {}
    conversation = payload.get('conversation') or {}
    sender = message.get('sender') or {}
    actual = admin.phone(sender.get('phoneNumber'))
    if not actual or actual not in members or not account_id:
        return '', None
    if (account.get('accountId') or account.get('id')) != account_id:
        return '', None
    if account.get('platform') != 'whatsapp' or message.get('direction') != 'incoming':
        return '', None
    if conversation.get('isGroup') or message.get('isGroup'):
        return '', None
    if admin.phone(conversation.get('participantId')) != actual:
        return '', None
    if sender.get('id') and admin.phone(sender['id']) != actual:
        return '', None
    return actual, members[actual]


def owner_sender(payload):
    return identify(payload)[0]


def greeting(member):
    name = member.get('short') or member.get('name') or ''
    if not name:
        return 'طال عمرك'
    return random.choice(MANAGER_GREETINGS if member.get('manager') else TEAM_GREETINGS).format(n=name)


_inner_admin_reply = admin.admin_reply


async def admin_reply(c, payload, sender):
    number, member = identify(payload)
    if not number or number != sender:
        raise PermissionError('Team identity required')
    token = ROLE.set(member)
    try:
        result = await _inner_admin_reply(c, payload, sender)
    finally:
        ROLE.reset(token)
    if isinstance(result, dict) and isinstance(result.get('message'), str):
        result = dict(result)
        result['message'] = greeting(member) + '\n\n' + result['message']
    return result


admin.owner_sender = owner_sender
admin.admin_reply = admin_reply
