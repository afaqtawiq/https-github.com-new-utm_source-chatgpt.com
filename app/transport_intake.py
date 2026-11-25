"""Text WhatsApp transport intake. Registration grants no financial authority."""
import hashlib
import json
import re

from app.logistics_parsing import digits, extract_phone, extract_route, phone


def is_transport_request(text):
    return bool(re.match(r'^\s*(?:(?:آفاق|افاق)(?: طويق)?\s*[:：-]?\s*)?طلب نقل(?:\s|[:：]|$)', text))


def extract_transport(text):
    origin, destination = extract_route(text)
    owner = re.search(r'(?:جوال|رقم)\s*صاحب\s*(?:الشحنة|الحمولة)\s*[:：]?\s*([^\n]+)', text)
    # Prefer a labelled owner over an employee contact mentioned elsewhere.
    owner_phone = extract_phone(owner.group(1)) if owner else extract_phone(text)
    weight = re.search(r'(?:وزن الحمولة|وزن البضاعة|الوزن)\s*[:：]\s*(\d+(?:\.\d+)?)\s*طن', digits(text))
    value = float(weight.group(1)) if weight else None
    return dict(origin=origin, destination=destination, owner_phone=owner_phone,
                weight_tons=value if value is not None and 0 < value <= 1000 else None)


def transport_reply(c, fields, text, event_id, conversation_id, message):
    """Called inside the webhook transaction and conversation lock. No sends."""
    fields = dict(fields or {})
    starts = is_transport_request(text)
    draft = dict(fields.get('_transport_draft') or {})
    if not starts and not draft:
        return None
    if starts:
        draft = {'source_event': event_id, 'messages': []}
    if text.strip() in {'إلغاء طلب النقل', 'الغاء طلب النقل'}:
        fields.pop('_transport_draft', None)
        return fields, 'collecting', 'تم إلغاء مسودة طلب النقل.'
    draft['messages'] = (draft.get('messages', []) + [text[:10000]])[-20:]
    for key, value in extract_transport(text).items():
        if value not in ('', None):
            draft[key] = value
    # A quoted truck availability offer is not an instruction to contact a shipper.
    offer = re.search(r'(?:عندي|لدي)\s+(?:شاحنة|شاحنه|تريلا)|الشحنة ما زالت متاحة', text)
    if offer:
        fields.pop('_transport_draft', None)
        return fields, 'collecting', 'النص يحتوي عرض مركبة أو استفسارًا عن حمولة. أرسل طلب النقل الأصلي مع رقم صاحب الحمولة والمسار حتى لا نتواصل مع الناقل بوصفه صاحب الشحنة.'
    missing = [label for key, label in [('origin', 'مدينة التحميل'), ('destination', 'مدينة التنزيل'),
                                       ('owner_phone', 'رقم جوال صاحب الشحنة')] if not draft.get(key)]
    if missing:
        fields['_transport_draft'] = draft
        return fields, 'collecting', 'حفظت مسودة طلب النقل. أرسل: ' + '، '.join(missing) + '.\nاكتب المسار: من … إلى …، ورقم صاحب الشحنة في سطر مستقل.'
    # Same source event always produces the same operational reference.
    reference = 'WA-' + hashlib.sha256((conversation_id + ':' + draft['source_event']).encode()).hexdigest()[:12].upper()
    shipment = c.execute("""INSERT INTO shipments(reference,service_type,origin,destination,status,revenue,cost,currency,created_at,updated_at)
        VALUES(%s,'Transport',%s,%s,'new',0,0,'SAR',NOW(),NOW())
        ON CONFLICT(reference) DO NOTHING RETURNING id""", (reference,draft['origin'],draft['destination'])).fetchone()
    if not shipment:
        shipment = c.execute('SELECT id FROM shipments WHERE reference=%s', (reference,)).fetchone()
    sender = message.get('sender') or {}
    submitter = phone(sender.get('phoneNumber') or sender.get('id') or '')
    notes = json.dumps(dict(source='whatsapp_transport', submitter_phone=submitter,
                            conversation_id=conversation_id, source_event=draft['source_event'],
                            messages=draft['messages']), ensure_ascii=False)
    c.execute("""INSERT INTO shipment_operations(shipment_id,stage,notes,created_at,updated_at)
        VALUES(%s,'new',%s,NOW(),NOW()) ON CONFLICT(shipment_id) DO NOTHING""", (shipment['id'],notes))
    c.execute("""INSERT INTO freight_negotiations(shipment_id,owner_phone,weight_tons,status,notes,created_at,updated_at)
        VALUES(%s,%s,%s,'contact_ready',%s,NOW(),NOW()) ON CONFLICT(shipment_id) DO NOTHING""",
        (shipment['id'],draft['owner_phone'],draft.get('weight_tons'),notes))
    fields.pop('_transport_draft', None)
    fields['_last_transport_reference'] = reference
    return fields, 'transport_registered', (f"تم تسجيل طلب النقل {reference}\nمن {draft['origin']} إلى {draft['destination']}\n"
        f"جوال صاحب الشحنة: {draft['owner_phone']}\nأُضيف إلى قائمة التفاوض؛ لم يبدأ التواصل بعد. "
        'بعد توثيق الاتفاق، يُجهز عرض السائق بسعر صاحب الشحنة ناقص 150 ريال.')
