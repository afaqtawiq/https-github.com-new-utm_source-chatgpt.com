"""Afaq customer conversations understood by Claude instead of fixed phrases.

Replaces afaaq_customer_reply.reply (same inputs and outputs). Claude reads the saved request,
the question the agent asked last, and the customer's message, and returns:
  * which request details the message actually states (service, route, cargo, deadline, company),
  * whether the message is about a NEW shipment rather than the saved one,
  * a short, natural reply that asks for the next missing detail.
Hard rules in the prompt: only the approved Afaq price list, no guaranteed dates, no booking or payment confirmation,
no invented facts. The previous rule-based reply is kept as the fallback, so a Claude error
never leaves a customer without an answer.
"""
import contextvars
import json
import os
import re

import httpx

from app import afaaq_customer_reply as base
from app import zernio_receiver as receiver
from app.customs_knowledge import KNOWLEDGE
from app import tariff_lookup

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
- Prices: quote ONLY Afaq's approved prices from the knowledge (clearance per container by number of containers in the
  bill of lading, and the listed transport routes), exactly as written, and say they are per the general price offer
  valid 15 days and clearly state (in plain words: لا تشمل) that they exclude customs duties, import VAT, government,
  port and shipping-line fees, which the importer pays.
  You may multiply a listed rate by the number of containers the customer stated. For anything not in the list
  (other routes, cities or services), say the team sends a dedicated quotation. Never invent or estimate other prices.
- Never promise dates, clearance times or outcomes, and never confirm a booking, payment or approval.
- Never invent facts about a shipment, a carrier or regulations. If unsure, say the team will confirm.
- Ask for only ONE missing detail at a time, the most important one first (service, route, cargo, deadline).
- When all four are known: thank them, say the team will review and send a quotation, and ask if there is anything else.
- Write in natural, warm, professional Saudi Arabic. Short: 1 to 3 sentences, or up to 6 short lines when answering
  a question about procedures, documents or requirements, and up to 10 short lines when the customer asks for links or how
  clearance works step by step (sea, air, land border, transit or export). No internal wording such as "execution cost",
  "management approval" or "review queue". Do not repeat the request code; the system adds it.
- Answer questions about Saudi customs procedures, documents, SABER, SFDA and other permits, prohibited goods and how
  duties and VAT work, using ONLY the knowledge below. Give the general requirement for the goods type, say the Afaq
  team confirms the exact requirement for their specific product (by HS code) before shipping, then ask the next
  missing detail. If the knowledge does not cover it, say the team will confirm; never guess.
- Customs code (البند الجمركي) and duty rate questions for a specific product: if no tariff_candidates are given,
  set "tariff_lookup" to up to 3 search phrasings in Arabic and 3 in English using customs tariff wording
  (for example sofa -> "مقاعد بهياكل خشب" / "seats with wooden frames"), and keep the reply to one short line.
  If tariff_candidates are given, answer from them ONLY: the 1 to 3 best matching 12-digit codes with their duty,
  say it is a preliminary classification from the GCC unified customs tariff and the broker confirms the final code,
  add the general requirements for that goods type from the knowledge, then ask the next missing detail.
  If no candidate fits, say the team will classify it. Never state a duty rate that is not in tariff_candidates,
  and never calculate an amount.
- Use correct Arabic spelling (for example يؤكد, not يأكد).
- When the customer wants Afaq to clear the shipment, agrees to proceed, or asks how to authorize the broker, give the
  FASAH authorization steps with Afaq's broker licence number 2513 (مؤسسة آفاق طويق للتخليص الجمركي) from the knowledge.
- When the customer asks for links, or a link would help (FASAH, SABER, SFDA, ports, ZATCA...), send the official links
  from the knowledge exactly as written, one per line with its name. Never invent or shorten a link.
- Reply ONLY to the customer's latest message. The recent conversation is given for context: do not repeat prices,
  requirements or explanations you already gave unless the customer asks again. If the latest message is a new
  question, answer just that question.
- When you multiply a rate by a number of containers, give the total too (for example 6 x 200 = 1,200 ريال).
- Do not assume facts about the goods (for example alcohol content, material or use). When a requirement depends on
  such a detail, state both cases briefly or ask about it.

Return ONLY a JSON object:
{"new_request": true|false,   // true only if the message clearly describes a different shipment from the saved request
 "fields": {"service": str|null, "route": str|null, "cargo": str|null, "deadline": str|null, "company": str|null},  // only what THIS message states
 "tariff_lookup": {"ar": [str], "en": [str]} | null,
 "reply": str}"""


SYSTEM = SYSTEM + '\n\nKnowledge (Arabic):\n' + KNOWLEDGE


def ask(fields, pending, text, candidates=None):
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key:
        return None
    saved = {k: fields.get(k) for k in KEYS + ('company',) if fields.get(k)}
    payload = {'saved_request': saved, 'last_question_asked': pending,
               'recent_conversation': HISTORY.get(), 'customer_message': text[:4000]}
    if candidates is not None:
        payload['tariff_candidates'] = candidates or 'no matching lines found'
    user = json.dumps(payload, ensure_ascii=False)
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
    lookup = ai.get('tariff_lookup')
    if isinstance(lookup, dict) and (lookup.get('ar') or lookup.get('en')):
        items = tariff_lookup.search_many(lookup.get('ar'), lookup.get('en'))
        second = ask(fields, pending, raw, candidates=tariff_lookup.as_prompt(items))
        if second:
            second['fields'] = {**(ai.get('fields') or {}), **(second.get('fields') or {})}
            ai = second
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

HISTORY = contextvars.ContextVar('afaq_history', default=[])
_inner_intake = receiver.intake_reply


def intake_reply(c, agent, conversation_id, event_id, text, selection, message):
    """Load the last exchanges of this conversation so Claude answers only the new message."""
    history = []
    if agent == 'afaaq':
        try:
            rows = c.execute('''SELECT m.body, m.reply FROM zernio_request_messages m
                JOIN zernio_requests r ON r.id=m.request_id
                WHERE r.conversation_id=%s AND r.agent=%s ORDER BY m.created_at DESC LIMIT 6''',
                             (conversation_id, agent)).fetchall()
            for row in reversed(rows):
                history.append({'customer': str(row['body'])[:600], 'assistant': str(row['reply'])[:600]})
        except Exception:
            history = []
    token = HISTORY.set(history)
    try:
        result = _inner_intake(c, agent, conversation_id, event_id, text, selection, message)
    finally:
        HISTORY.reset(token)
    return brand(result) if agent == 'afaaq' else result


HEADER = os.getenv('AFAQ_MESSAGE_HEADER', '🌐 *Afaq Tuwaiq | آفاق طويق*')


def brand(result):
    """Replace the leading request code with the Afaq header and move the code to a small last line."""
    if not isinstance(result, dict) or not isinstance(result.get('message'), str):
        return result
    match = re.match(r'^(AF-[0-9]+)[ \t]*\n+', result['message'])
    if not match:
        return result
    body = result['message'][match.end():].strip()
    out = dict(result)
    out['message'] = HEADER + '\n\n' + body + '\n\n_رقم الطلب / Ref: ' + match.group(1) + '_'
    return out


receiver.intake_reply = intake_reply
