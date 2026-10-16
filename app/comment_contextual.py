"""Bounded public prose checks; semantic approval is additionally required."""
import re
from app import comment_policy as policy

FACTS = ('Afaq Tuwaiq offers customs clearance, transport, shipping, storage and '
         'door-to-door services in Saudi Arabia and the Gulf. These are the ONLY approved facts. '
         'No particular route, cargo type, capacity, availability, price, delivery time, '
         'facility, certification, contact detail or completed action is verified.')
SERVICE_WORDS = {
    'clearance': r'clearance|\u062a\u062e\u0644\u064a\u0635',
    'transport': r'transport|\u0646\u0642\u0644',
    'shipping': r'shipping|\u0634\u062d\u0646',
    'storage': r'storage|\u062a\u062e\u0632\u064a\u0646',
    'door': r'door.to.door|\u0627\u0644\u0628\u0627\u0628',
}
# Deliberately over-reject: monetary terms, time commitments, promises, operational
# status, instructions and unsupported scope all need a human, even when negated.
RISK = re.compile(
    r'price|cost|quote|pay|free|dollar|riyal|sar\b|usd\b|guarantee|promise|ensure|always|everywhere|worldwide|'
    r'tomorrow|today|hour|day|week|month|minute|deadline|available|availability|immediate|instant|'
    r'booked|confirmed|processed|dispatched|tracking|order|compensation|insurance|medical|weapon|'
    r'legal|duty|duties|tax|bypass|evade|hack|\bname\b|address|contact|\.(?:com|net|org)\b|'
    r'\u0633\u0639\u0631|\u0623\u0633\u0639\u0627\u0631|\u0627\u0633\u0639\u0627\u0631|\u062a\u0643\u0644\u0641|\u0628\u0643\u0645|\b\u0643\u0645\b|\u0631\u064a\u0627\u0644|\u062f\u0648\u0644\u0627\u0631|\u0645\u062c\u0627\u0646|'
    r'\u0636\u0645\u0627\u0646|\u0646\u0636\u0645\u0646|\u0645\u0636\u0645\u0648\u0646|\u0646\u0639\u062f|\u0646\u0644\u062a\u0632\u0645|\u0645\u0624\u0643\u062f|\u0641\u0648\u0631|\u0645\u062a\u0627\u062d|\u062a\u0648\u0641\u0631|\u0645\u062a\u0648\u0641\u0631|'
    r'\u0633\u0627\u0639\u0629|\u0633\u0627\u0639\u0627\u062a|\u064a\u0648\u0645|\u0623\u064a\u0627\u0645|\u0627\u064a\u0627\u0645|\u0623\u0633\u0628\u0648\u0639|\u0627\u0633\u0628\u0648\u0639|\u0634\u0647\u0631|\u063a\u062f|\u0628\u0643\u0631\u0629|\u0645\u0648\u0639\u062f|\u0645\u062f\u0629|'
    r'\u062a\u0645 |\u062d\u062c\u0632|\u062a\u0623\u0643\u064a\u062f|\u062a\u0627\u0643\u064a\u062f|\u062a\u062a\u0628\u0639|\u062a\u0623\u0645\u064a\u0646|\u062a\u0627\u0645\u064a\u0646|\u0636\u0631\u064a\u0628|\u0631\u0633\u0648\u0645|\u062a\u0647\u0631\u064a\u0628|\u062a\u062c\u0627\u0648\u0632|\u0627\u0633\u0645\u064a|\u0639\u0646\u0648\u0627\u0646', re.I)

def normalized(text):
    # Remove Arabic vocalization/tatweel before risk matching.
    return re.sub(r'[\u0640\u064b-\u065f\u0670]', '', policy.clean(text)).casefold()

def services(text):
    return {key for key, pattern in SERVICE_WORDS.items() if re.search(pattern, normalized(text))}

def eligible(question):
    return (policy.screen(question) == 'safe' and bool(services(question))
            and not RISK.search(normalized(question)))

def valid_output(question, reply):
    if not eligible(question) or not isinstance(reply, str) or not 12 <= len(reply) <= 480:
        return False
    return (policy.screen(reply) == 'safe' and not RISK.search(normalized(reply))
            and bool(services(reply)) and services(reply) <= services(question)
            and not re.search(r'[<>\[\]{}\\/]|[\u20a0-\u20cf$%]', reply))
