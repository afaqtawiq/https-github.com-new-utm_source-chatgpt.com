"""Append-only owner-message evidence; reads never send or advance a shipment.

Provider acceptance, delivery observations and an actual owner reply are separate
facts. Legacy records acquire receipt evidence only after exact provider matching.
"""
import hashlib
import json

from fastapi import HTTPException


def init_storage(connection):
    for name in ('owner_message_provider', 'owner_message_account_id', 'owner_message_conversation_id'):
        connection.execute('ALTER TABLE freight_negotiations ADD COLUMN IF NOT EXISTS ' + name + ' TEXT')
    connection.execute('''CREATE TABLE IF NOT EXISTS freight_owner_receipts(
        id BIGSERIAL PRIMARY KEY,
        negotiation_id BIGINT NOT NULL REFERENCES freight_negotiations(id) ON DELETE CASCADE,
        provider_message_id TEXT NOT NULL, owner_phone TEXT NOT NULL,
        contact_fingerprint TEXT NOT NULL,
        provider TEXT NOT NULL CHECK (provider='zernio'), account_id TEXT NOT NULL,
        conversation_id TEXT, delivery_status TEXT NOT NULL CHECK
          (delivery_status IN ('sent','delivered','read','played','failed','deleted','unknown')),
        error_code INTEGER, reason TEXT, checked_at TIMESTAMPTZ NOT NULL,
        checked_by BIGINT NOT NULL)''')
    connection.execute('''CREATE INDEX IF NOT EXISTS freight_owner_receipts_lookup
        ON freight_owner_receipts(negotiation_id,provider_message_id,checked_at DESC,id DESC)''')
    connection.execute('''CREATE TABLE IF NOT EXISTS freight_owner_reply_bindings(
        shipment_event_id BIGINT PRIMARY KEY REFERENCES shipment_events(id) ON DELETE CASCADE,
        negotiation_id BIGINT NOT NULL REFERENCES freight_negotiations(id) ON DELETE CASCADE,
        contact_fingerprint TEXT NOT NULL, provider_message_id TEXT NOT NULL,
        owner_phone TEXT NOT NULL, account_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
        inbound_event_id TEXT NOT NULL, inbound_message_id TEXT,
        binding_source TEXT NOT NULL CHECK (binding_source IN ('accepted_contact','verified_receipt')),
        recorded_at TIMESTAMPTZ NOT NULL)''')
    connection.execute('''CREATE INDEX IF NOT EXISTS freight_owner_reply_binding_lookup
        ON freight_owner_reply_bindings(negotiation_id,contact_fingerprint)''')



def fingerprint(item, receipt_id=None):
    """Bind the operator's form and subsequent save to this specific contact."""
    keys = ('id', 'shipment_id', 'record_kind', 'owner_phone', 'contact_channel',
            'provider_message_id', 'owner_message_provider', 'owner_message_account_id',
            'owner_message_conversation_id', 'contacted_at')
    return hashlib.sha256(json.dumps([item.get(k) for k in keys] + [receipt_id], default=str).encode()).hexdigest()


def snapshot(connection, shipment_id):
    item = connection.execute('SELECT * FROM freight_negotiations WHERE shipment_id=%s', (shipment_id,)).fetchone()
    if not item or item.get('record_kind') == 'carrier_offer':
        return None
    # Only a reply with exact recorded identity can outrank this contact's receipt.
    # Legacy events remain visible as history, never silently backfilled. Identity
    # also avoids PostgreSQL NOW() transaction-start timestamp ordering races.
    reply = connection.execute('''SELECT e.happened_at FROM shipment_events e
        JOIN freight_owner_reply_bindings b ON b.shipment_event_id=e.id
        WHERE e.shipment_id=%s AND e.event_type='owner_whatsapp_reply'
          AND b.negotiation_id=%s AND b.contact_fingerprint=%s
        ORDER BY e.happened_at DESC,e.id DESC LIMIT 1''',
        (shipment_id, item['id'], fingerprint(item))).fetchone()
    historical_reply = connection.execute('''SELECT e.happened_at FROM shipment_events e
        WHERE e.shipment_id=%s AND e.event_type='owner_whatsapp_reply'
          AND NOT EXISTS (SELECT 1 FROM freight_owner_reply_bindings b
              WHERE b.shipment_event_id=e.id AND b.negotiation_id=%s AND b.contact_fingerprint=%s)
        ORDER BY e.happened_at DESC,e.id DESC LIMIT 1''',
        (shipment_id, item['id'], fingerprint(item))).fetchone()
    latest = None
    mid = item.get('provider_message_id')
    if mid and item.get('contact_channel') == 'whatsapp':
        latest = connection.execute('''SELECT * FROM freight_owner_receipts
            WHERE negotiation_id=%s AND provider_message_id=%s AND owner_phone=%s
              AND contact_fingerprint=%s
            ORDER BY checked_at DESC,id DESC LIMIT 1''',
            (item['id'], mid, item.get('owner_phone'), fingerprint(item))).fetchone()
    return {'provider_message_id': mid, 'provider_call_id': item.get('provider_call_id'),
            'accepted_at': item.get('contacted_at'), 'receipt': latest,
            'delivery_status': latest['delivery_status'] if latest else 'accepted' if mid else 'not_sent',
            'replied_at': reply['happened_at'] if reply else None,
            'historical_replied_at': historical_reply['happened_at'] if historical_reply else None,
            'fingerprint': fingerprint(item, latest['id'] if latest else None)}


def evidence_lines(evidence):
    if not evidence:
        return []
    lines = []
    if evidence.get('provider_message_id'):
        lines.append('تواصل صاحب الشحنة: قبل مزود واتساب طلب الإرسال وله معرف مسجل.')
        receipt = evidence.get('receipt')
        if not receipt:
            lines.append('تسليم الرسالة وقراءتها غير مؤكدين في هذا السجل.')
        else:
            descriptions = {
                'sent': 'الإيصال المحفوظ: أرسل المزود الرسالة؛ لا يثبت التسليم أو القراءة.',
                'delivered': 'الإيصال المحفوظ: وصلت الرسالة إلى المستلم؛ لا يثبت ردًا أو اتفاقًا.',
                'read': 'الإيصال المحفوظ: قرأ المستلم الرسالة؛ لا يثبت ردًا أو اتفاقًا.',
                'played': 'الإيصال المحفوظ: شغّل المستلم الرسالة؛ لا يثبت ردًا أو اتفاقًا.',
                'failed': 'الإيصال المحفوظ: فشل تسليم رسالة صاحب الشحنة؛ يحتاج مراجعة دون إعادة إرسال تلقائية.',
                'deleted': 'الإيصال المحفوظ: الرسالة محذوفة لدى المزود؛ التسليم الحالي غير مؤكد.',
                'unknown': 'نتيجة فحص الإيصال غير مؤكدة؛ لا تُعامل كتسليم ناجح أو فشل مؤكد.',
            }
            lines.append(descriptions[receipt['delivery_status']])
            if receipt.get('error_code') is not None:
                lines.append('رمز خطأ المزود: ' + str(receipt['error_code']))
            lines.append('وقت فحص الإيصال المحفوظ: ' + str(receipt['checked_at']) + '؛ ليست قراءة مباشرة الآن.')
    elif evidence.get('provider_call_id'):
        lines.append('تواصل صاحب الشحنة: قبل مزود الاتصال طلب المكالمة وله معرف مسجل؛ هذا لا يثبت الرد عليها.')
    else:
        lines.append('تواصل صاحب الشحنة: لا يوجد معرف قبول مسجل من المزود.')
    if (evidence.get('provider_message_id') or evidence.get('provider_call_id')) and evidence.get('accepted_at'):
        lines.append('وقت قبول طلب التواصل: ' + str(evidence['accepted_at']))
    if evidence.get('replied_at'):
        lines.append('يوجد رد حقيقي محفوظ ومرتبط بهذه الشحنة: ' + str(evidence['replied_at']) + '؛ لا يثبت وحده اتفاقًا أو استمرار توفر الحمولة.')
    if evidence.get('historical_replied_at'):
        lines.append('يوجد رد محفوظ في سجل الشحنة: ' + str(evidence['historical_replied_at']) + '؛ ارتباطه بمحاولة التواصل الحالية غير مثبت، ويبقى دليلًا تاريخيًا للمراجعة.')
    return lines


def current_status(negotiation_status, evidence):
    # Receipt failure never undoes a real reply, agreement or later progression.
    if negotiation_status != 'awaiting_owner' or not evidence or evidence.get('replied_at'):
        return negotiation_status
    status = evidence.get('delivery_status')
    if status == 'failed':
        return 'owner_delivery_failed'
    if status in ('unknown', 'deleted'):
        return 'owner_delivery_unknown'
    return negotiation_status


def reply_identity_matches(item, *, account_id, conversation_id, owner_phone):
    """Known contact/account/conversation changes cannot inherit an old reply."""
    return bool(item and item.get('contact_channel') == 'whatsapp'
        and item.get('record_kind') == 'shipment_request' and item.get('status') == 'awaiting_owner'
        and item.get('owner_phone') == owner_phone and account_id and conversation_id
        and item.get('owner_message_provider') in (None, '', 'zernio')
        and item.get('owner_message_account_id') in (None, '', account_id)
        and item.get('owner_message_conversation_id') in (None, '', conversation_id))


def bind_reply(connection, item, shipment_event_id, *, account_id, conversation_id,
               owner_phone, inbound_event_id, inbound_message_id=None):
    """Bind an already verified private inbound reply under the receiver's row lock.

    No historical reply gets a guessed identity. Legacy contacts may use an exact
    saved provider observation as proof; otherwise their new reply stays history.
    """
    if not item.get('provider_message_id') or not reply_identity_matches(item,
            account_id=account_id, conversation_id=conversation_id, owner_phone=owner_phone):
        return False
    source = None
    identity = fingerprint(item)
    if (item.get('owner_message_provider') == 'zernio' and item.get('owner_message_account_id') == account_id
            and item.get('owner_message_conversation_id') == conversation_id):
        source = 'accepted_contact'
    else:
        verified = connection.execute('''SELECT id FROM freight_owner_receipts
            WHERE negotiation_id=%s AND contact_fingerprint=%s AND provider_message_id=%s
              AND provider='zernio' AND account_id=%s AND conversation_id=%s
              AND owner_phone=%s AND delivery_status <> 'unknown'
            ORDER BY checked_at DESC,id DESC LIMIT 1''',
            (item['id'], identity, item['provider_message_id'], account_id, conversation_id, owner_phone)).fetchone()
        if verified:
            source = 'verified_receipt'
    if not source:
        return False
    connection.execute('''INSERT INTO freight_owner_reply_bindings(shipment_event_id,negotiation_id,
        contact_fingerprint,provider_message_id,owner_phone,account_id,conversation_id,
        inbound_event_id,inbound_message_id,binding_source,recorded_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()) ON CONFLICT(shipment_event_id) DO NOTHING''',
        (shipment_event_id, item['id'], identity, item['provider_message_id'], owner_phone,
         account_id, conversation_id, inbound_event_id, inbound_message_id, source))
    return True


async def reconcile(shipment_id, expected_fingerprint, user_id):
    """Explicit operator lookup only. Never called by status GETs or workers."""
    from app.storage import db, utcnow
    from app import zernio_whatsapp as transport
    from app.broadcast_recovery import conversation_index, receipt

    # A double click cannot run concurrent metered checks. No shipment/negotiation
    # row is held across provider I/O, so actual replies can continue normally.
    with db() as c:
        locked = c.execute('SELECT pg_try_advisory_xact_lock(hashtext(%s)) acquired',
                           ('owner-delivery:' + str(shipment_id),)).fetchone()
        if not locked['acquired']:
            raise HTTPException(409, 'فحص الإيصال جارٍ بالفعل؛ انتظر النتيجة')
        item = c.execute('SELECT * FROM freight_negotiations WHERE shipment_id=%s', (shipment_id,)).fetchone()
        if not item:
            raise HTTPException(404, 'الشحنة غير موجودة')
        evidence = snapshot(c, shipment_id)
        if not evidence or evidence['fingerprint'] != expected_fingerprint:
            raise HTTPException(409, 'تغير سجل التواصل أو سبق فحصه؛ راجع الصفحة قبل الفحص')
        contact_before = fingerprint(item)
        if (item.get('record_kind') != 'shipment_request' or item.get('contact_channel') != 'whatsapp'
                or not item.get('provider_message_id') or not transport.phone(item.get('owner_phone'))):
            raise HTTPException(409, 'لا توجد رسالة صاحب شحنة موثقة قابلة للفحص')
        account = transport.account_id()
        if (not account or item.get('owner_message_provider') not in (None, '', 'zernio')
                or item.get('owner_message_account_id') not in (None, '', account)):
            raise HTTPException(409, 'المزود أو الحساب لا يطابق رسالة التواصل؛ لم يبدأ الفحص')
        checked_at = utcnow()  # observation start, not later insertion/HTTP completion
        result = {'delivery_status': 'unknown', 'reason': 'lookup_unavailable'}
        cid = None
        try:
            # This read-only session does not invoke a sender or acquire retry rights.
            async with transport.client() as client:
                await transport.validate_account(client)
                index = await conversation_index(client)
                cids = index.get(transport.phone(item['owner_phone']), [])
                if len(cids) == 1 and (not item.get('owner_message_conversation_id')
                                      or item['owner_message_conversation_id'] == cids[0]):
                    cid = cids[0]
                    result = await receipt(client, cid, item['provider_message_id'])
                    result['reason'] = 'exact_message' if result.get('provider_message_id') else 'message_not_verified'
                else:
                    result['reason'] = 'conversation_not_unique'
        except (transport.WhatsAppBlocked, transport.httpx.HTTPError):
            # Persist failed lookup as unknown, without leaking provider error bodies.
            pass
        current = c.execute('SELECT * FROM freight_negotiations WHERE shipment_id=%s FOR UPDATE', (shipment_id,)).fetchone()
        if not current or fingerprint(current) != contact_before or transport.account_id() != account:
            raise HTTPException(409, 'تغير سجل التواصل أثناء الفحص؛ لم يُربط الإيصال بسجل مختلف')
        c.execute('''INSERT INTO freight_owner_receipts(negotiation_id,provider_message_id,owner_phone,
            contact_fingerprint,provider,account_id,conversation_id,delivery_status,error_code,reason,checked_at,checked_by)
            VALUES(%s,%s,%s,%s,'zernio',%s,%s,%s,%s,%s,%s,%s)''',
            (item['id'], item['provider_message_id'], item['owner_phone'], contact_before, account, cid,
             result['delivery_status'], result.get('error_code'), result['reason'], checked_at, user_id))
    return result['delivery_status']
