"""Afaq Tuwaiq team on WhatsApp.

The team list comes from the AFAQ_TEAM environment variable (JSON list of
{"phone": "+9665...", "name": "...", "short": "...", "role": "...", "manager": true|false}).
* Every listed number is recognised with the same provider-identity checks as the original owner
  check (account, direction, private chat, participant), never by names or message text.
* Team members can prepare records and use internal commands: adding drivers and shipments, voice notes (with
  the confirmation code), questions, tariff lookups, search, reports and explicitly requested load screenshots.
* Customer/driver sends require the existing manager authority; internal discussion never starts transport.
* The manager (manager=true, or the WHATSAPP_COMMAND_OWNER number) is addressed with "أستاذ".
* Every reply to a team member starts with a respectful Saudi greeting with their name.
"""
import contextvars
import json
import os
import random
import re

from app import whatsapp_admin as admin

ROLE = contextvars.ContextVar('afaq_team_member', default=None)
CONTEXT = contextvars.ContextVar('afaq_team_context', default=None)
TEAM_GREETINGS = ['طال عمرك يا {n}', 'أبشر يا {n}', 'تحت أمرك يا {n}', 'الله يعطيك العافية يا {n}', 'من عيوني يا {n}']
MANAGER_GREETINGS = ['طال عمرك يا أستاذ {n}', 'أبشر يا أستاذ {n}', 'تحت أمرك يا أستاذ {n}', 'من عيوني يا أستاذ {n}']


def phone(value):
    """Normalize Saudi local/international forms without trusting display names."""
    from app.logistics_parsing import digits
    value = digits(value).strip()
    compact = re.sub(r'[ ()-]', '', value)
    if re.fullmatch(r'05\d{8}', compact):
        compact = '966' + compact[1:]
    return admin.phone(compact)


def team():
    try:
        members = json.loads(os.getenv('AFAQ_TEAM', '[]'))
    except ValueError:
        members = []
    out = {}
    for m in members if isinstance(members, list) else []:
        number = phone(m.get('phone')) if isinstance(m, dict) else ''
        if number:
            out[number] = {'name': str(m.get('name') or ''), 'short': str(m.get('short') or m.get('name') or '').strip(),
                           'role': str(m.get('role') or ''), 'manager': m.get('manager') is True}
    owner = phone(os.getenv('WHATSAPP_COMMAND_OWNER', ''))
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
    actual = phone(sender.get('phoneNumber'))
    if not actual or actual not in members or not account_id:
        return '', None
    if (account.get('accountId') or account.get('id')) != account_id:
        return '', None
    if account.get('platform') != 'whatsapp' or message.get('direction') != 'incoming':
        return '', None
    if conversation.get('isGroup') or message.get('isGroup'):
        return '', None
    if phone(conversation.get('participantId')) != actual:
        return '', None
    if sender.get('id') and phone(sender['id']) != actual:
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
    admin.ensure_admin(c)
    c.execute("""CREATE TABLE IF NOT EXISTS whatsapp_staff_context(
        id BIGSERIAL PRIMARY KEY,event_id TEXT UNIQUE NOT NULL,account_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,sender TEXT NOT NULL,command TEXT NOT NULL,
        reply TEXT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW())""")
    account = payload.get('account') or {}
    account_id = account.get('accountId') or account.get('id')
    history = c.execute("""SELECT command,reply FROM whatsapp_staff_context
        WHERE account_id=%s AND sender=%s AND conversation_id=%s ORDER BY id DESC LIMIT 8""",
        (account_id,number,payload['conversation']['id'])).fetchall()
    context = {'member': member, 'history': list(reversed(history))}
    token = ROLE.set(member)
    context_token = CONTEXT.set(context)
    try:
        from app.staff_intake import internal_reply
        result = await internal_reply(c, payload, sender, context)
        if result is None:
            result = await _inner_admin_reply(c, payload, sender)
    finally:
        CONTEXT.reset(context_token)
        ROLE.reset(token)
    if isinstance(result, dict) and isinstance(result.get('message'), str):
        logged = c.execute('SELECT command FROM whatsapp_admin_audit WHERE event_id=%s', (payload['id'],)).fetchone()
        c.execute('''INSERT INTO whatsapp_staff_context(event_id,account_id,conversation_id,sender,command,reply)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING''',
            (payload['id'],account_id,payload['conversation']['id'],number,
             (logged or {}).get('command') or str((payload.get('message') or {}).get('text') or '')[:8000],
             result['message']))
        result = dict(result)
        result['message'] = greeting(member) + '\n\n' + result['message']
    return result


async def route_reply(c, payload):
    number, member = identify(payload)
    if member is None:
        return None
    # Preserve the manager's already-approved disclosed simulation workflow.
    # This exception cannot select a real shipment or dispatch a driver offer.
    message = payload.get('message') or {}
    text = str(message.get('text') or '')
    from app.transport_intake import is_transport_request
    from app.command_ai import explicit_action_request
    from app.zernio_receiver import is_menu_request, explicit_agent
    test_terms = (bool(re.search(r'(?:السعر(?: النهائي)?|(?:طريقة )?الدفع|الوزن)\s*:', text))
                  and 'محاكاة دون دفع' in text)
    if (member.get('manager') is True and not message.get('attachments') and test_terms
            and not admin.is_admin_command(text) and not is_transport_request(text)
            and not is_menu_request(text) and not explicit_agent(text)
            and not any(explicit_action_request(text, action)
                        for action in ('send_message','add_driver','add_shipment'))):
        pending = c.execute('''SELECT s.is_test,n.test_owner_contact_status,n.provider_message_id
            FROM shipments s JOIN freight_negotiations n ON n.shipment_id=s.id
            WHERE n.owner_phone=%s AND n.contact_channel='whatsapp'
            AND n.status='awaiting_owner' AND n.record_kind='shipment_request' ''', ('+'+number,)).fetchall()
        if (len(pending)==1 and pending[0]['is_test']
                and pending[0]['test_owner_contact_status']=='sent' and pending[0]['provider_message_id']):
            return None
    return await admin.admin_reply(c, payload, number)


admin.owner_sender = owner_sender
admin.admin_reply = admin_reply

from app import zernio_receiver
zernio_receiver.team_reply = route_reply
