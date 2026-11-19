"""Ask the destination shipping agent for the arrival date by email (owner request, 19 Nov 2026:
«المفروض الموظف في الوكيل يرسل ايميل للشركة ويسأل عن موعد الوصول»).

When tracking finds no confirmed ETA, the agent finds the destination / delivery agent of the shipment (from the B/L the
team sent, or the name the manager gives), takes its import / operations address from the Jeddah shipping-agents
directory, and prepares a short English email. It is an external send: it goes out from the official mailbox only after
«نفذ CODE» (same confirmation as every other email).
"""
import json
import re

from app.storage import db

AGENT_KEYS = ('delivery_agent', 'destination_agent', 'agent', 'notify_party', 'shipping_line')
PURPOSE_ORDER = ('import', 'arrival', 'operations', 'customer service', 'general', 'd/o')


def _fold(text):
    text = str(text or '').lower()
    return re.sub(r'[^a-z0-9؀-ۿ]+', ' ', text).strip()


def _texts(ref, given):
    """Candidate agent names, most specific first: what the manager named, then the document's agent fields."""
    out = [given] if given else []
    try:
        with db() as c:
            if c.execute("SELECT to_regclass('staff_documents') t").fetchone()['t']:
                for d in c.execute('SELECT fields FROM staff_documents WHERE fields ILIKE %s ORDER BY id DESC LIMIT 3',
                                   ('%' + ref + '%',)).fetchall():
                    try:
                        f = json.loads(d['fields'] or '{}')
                    except ValueError:
                        continue
                    facts = f.get('key_facts') if isinstance(f.get('key_facts'), dict) else {}
                    for k in AGENT_KEYS:
                        if f.get(k):
                            out.append(str(f[k]))
                    for k, v in facts.items():
                        if re.search(r'agent|وكيل|delivery|notify|carrier|line|ناقل', str(k), re.I) and v:
                            out.append(str(v))
    except Exception as exc:
        print('ETA_INQUIRY_DOCS', type(exc).__name__, str(exc)[:120], flush=True)
    return [t for t in out if t and t.strip()]


def find_agent(ref, given=''):
    """(agent name, email, purpose) from the shipping-agents directory, or None."""
    with db() as c:
        if not c.execute("SELECT to_regclass('shipping_agents') t").fetchone()['t']:
            return None
        agents = c.execute('SELECT id, name FROM shipping_agents WHERE status=%s', ('active',)).fetchall()
        for text in _texts(ref, given):
            folded = ' ' + _fold(text) + ' '
            for a in agents:
                words = [w for w in _fold(a['name']).split() if len(w) >= 4 and w not in ('line', 'shipping', 'maritime', 'cargo', 'logistics', 'agency', 'freight', 'team')]
                if words and any(' ' + w + ' ' in folded for w in words[:2]):
                    contacts = c.execute('''SELECT email, purpose FROM shipping_agent_contacts WHERE agent_id=%s AND status='active'
                        AND email IS NOT NULL AND email<>'' ORDER BY id''', (a['id'],)).fetchall()
                    if not contacts:
                        continue
                    best = next((x for p in PURPOSE_ORDER for x in contacts if p in x['purpose'].lower()), contacts[0])
                    return a['name'], best['email'], best['purpose']
    return None


def compose(ref, agent, hints):
    vessel = ' / V.'.join(x for x in (hints.get('vessel'), hints.get('voyage')) if x)
    subject = f'ETA / Arrival Notice Request - B/L {ref}' + (f' - {vessel}' if vessel else '')
    lines = [f'Dear {agent} Team,', '',
             'Good day. Kindly advise the expected arrival date (ETA) at Jeddah Islamic Port and share the arrival notice '
             'for the shipment below:', '', f'- B/L No.: {ref}']
    if vessel:
        lines.append(f'- Vessel / Voyage: {vessel}')
    if hints.get('pol'):
        lines.append(f"- Port of Loading: {hints['pol']}")
    lines.append(f"- Port of Discharge: {hints.get('pod') or 'Jeddah'}")
    if hints.get('containers'):
        lines.append('- Containers: ' + ', '.join(hints['containers'][:12]))
    lines += ['', 'We are the customs broker handling this shipment in Jeddah. Your early reply is appreciated.', '',
              'Best regards,', 'Afaq Tuwaiq for Customs Clearance & Transport']
    return subject[:200], '\n'.join(lines)


def prepare(ref, agent_name, make_code, hints=None):
    """Arabic reply with the prepared email and its confirmation code; nothing is sent here."""
    from app.shipment_tracking import hints_for, ref_type
    clean, _ = ref_type(ref)
    clean = clean or str(ref or '').strip().upper()
    if not clean:
        return 'اكتب رقم البوليصة اللي تبغى نسأل الوكيل عنها.'
    found = find_agent(clean, agent_name)
    if not found:
        return ('ما عرفت الوكيل الملاحي لهذه الشحنة أو ما عندي إيميله في دليل وكلاء جدة'
                + (f' («{agent_name}»)' if agent_name else '') + '. اكتب اسم الوكيل أو إيميله وأجهّز الرسالة.')
    agent, email, purpose = found
    h = dict(hints or {})
    h.update({k: v for k, v in hints_for(clean).items() if v and not h.get(k)})
    subject, body = compose(clean, agent, h)
    code = make_code({'tool': 'send_email', 'to': email, 'subject': subject, 'body': body})
    return (f'✉️ جهّزت إيميل لوكيل الوجهة {agent} ({email} — {purpose}) يسأل عن موعد الوصول وإشعار الوصول للبوليصة {clean}.\n'
            f'العنوان: {subject}\nللإرسال من البريد الرسمي اكتب: نفذ {code}')
