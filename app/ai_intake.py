"""Afaq customer conversations understood by Claude instead of fixed phrases.

Replaces afaaq_customer_reply.reply (same inputs and outputs). Claude reads the saved request,
the question the agent asked last, and the customer's message, and returns:
  * which request details the message actually states (service, route, cargo, deadline, company),
  * whether the message is about a NEW shipment rather than the saved one,
  * a short, natural reply that asks for the next missing detail.
Hard rules in the prompt: no prices, no guaranteed dates, no booking or payment confirmation,
no invented facts. The previous rule-based reply is kept as the fallback, so a Claude error
never leaves a customer without an answer.
"""
import json
import os
import re

import httpx

from app import afaaq_customer_reply as base
from app.customs_knowledge import KNOWLEDGE

MODEL = os.getenv('INTAKE_MODEL', 'claude-sonnet-5')
KEYS = ('service', 'route', 'cargo', 'deadline')

SYSTEM = """You are the WhatsApp assistant of Afaq Tuwaiq (آفاق طويق), a Saudi customs clearance and logistics company with an office in Jeddah.
Services: customs clearance at all Saudi customs ports (sea ports, airports and land borders) for import, export and transit;
acting as the Saudi importer of record for companies without a Saudi entity; SABER/SASO certificate coordination;
land transport across Saudi Arabia and the GCC; storage and handling; door-to-door delivery. Customers are Saudi, GCC and foreign companies.

Your job in each reply: understand the customer, answer briefly and honestly, and collect the four request details:
service (what they need), route (port of arrival or customs port; for transport the origin and destination),
cargo (goods type and weight, quantity or number of containers), deadline (expected arrival or required date).

Rules you must never break:
- Never give prices, costs, rates or estimates. If asked, say the team prepares a quotation once the details are complete.
- Never promise dates, clearance times or outcomes, and never confirm a booking, payment or approval.
- Never invent facts about a shipment, a carrier or regulations. If unsure, say the team will confirm.
- Ask for only ONE missing detail at a time, the most important one first (service, route, cargo, deadline).
- When all four are known: thank them, say the team will review and send a quotation, and ask if there is anything else.
- Write in natural, warm, professional Saudi Arabic. Short: 1 to 3 sentences, or up to 6 short lines when answering
  a question about procedures, documents or requirements. No internal wording such as "execution cost",
  "management approval" or "review queue". Do not repeat the request code; the system adds it.
- Answer questions about Saudi customs procedures, documents, SABER, SFDA and other permits, prohibited goods and how
  duties and VAT work, using ONLY the knowledge below. Give the general requirement for the goods type, say the Afaq
  team confirms the exact requirement for their specific product (by HS code) before shipping, then ask the next
  missing detail. If the knowledge does not cover it, say the team will confirm; never guess.
- Never state a duty rate or an amount for a specific product; explain the general structure only.
- Use correct Arabic spelling (for example يؤكد, not يأكد).

Return ONLY a JSON object:
{"new_request": true|false,   // true only if the message clearly describes a different shipment from the saved request
 "fields": {"service": str|null, "route": str|null, "cargo": str|null, "deadline": str|null, "company": str|null},  // only what THIS message states
 "reply": str}"""


SYSTEM = SYSTEM + '\n\nKnowledge (Arabic):\n' + KNOWLEDGE


def ask(fields, pending, text):
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key:
        return None
    saved = {k: fields.get(k) for k in KEYS + ('company',) if fields.get(k)}
    user = json.dumps({'saved_request': saved, 'last_question_asked': pending, 'customer_message': text[:4000]},
                      ensure_ascii=False)
    body = {'model': MODEL, 'max_tokens': 1000, 'thinking': {'type': 'disabled'}, 'system': SYSTEM, 'messages': [{'role': 'user', 'content': user}]}
    try:
        with httpx.Client(timeout=25) as client:
            response = client.post('https://api.anthropic.com/v1/messages', json=body,
                                   headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
            response.raise_for_status()
        out = ''.join(p.get('text', '') for p in response.json().get('content', []) if p.get('type') == 'text')
        match = re.search(r'\{.*\}', out, re.S)
        data = json.loads(match.group(0)) if match else None
        if isinstance(data, dict) and isinstance(data.get('reply'), str) and data['reply'].strip():
            return data
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return None


_fallback = base.reply


def reply(fields, pending, text, selection, updates, greeting):
    raw = str(text or '').strip()
    if selection or not raw:
        return _fallback(fields, pending, text, selection, updates, greeting)
    fields, _ = base.repair_legacy_fields(fields)
    ai = ask(fields, pending, raw)
    if not ai:
        return _fallback(fields, pending, text, selection, updates, greeting)
    fields = dict(fields)
    if ai.get('new_request') and any(fields.get(k) for k in KEYS):
        history = list(fields.get('_previous_requests') or [])
        history.append({k: fields.get(k) for k in KEYS + ('company', 'latest_follow_up') if fields.get(k)})
        fields = {k: v for k, v in fields.items() if k.startswith('_whatsapp')}
        fields['_previous_requests'] = history[-10:]
    for k, v in (ai.get('fields') or {}).items():
        if k in KEYS + ('company',) and isinstance(v, str) and v.strip() and v.strip().lower() not in ('null', 'none'):
            fields[k] = v.strip()[:2000]
    fields.update(updates or {})
    fields['latest_message'] = raw[:12000]
    missing = [k for k, _ in base.QUESTIONS if not fields.get(k)]
    return fields, (missing[0] if missing else None), ('collecting' if missing else 'ready_for_review'), ai['reply'].strip()[:1500]


base.reply = reply
