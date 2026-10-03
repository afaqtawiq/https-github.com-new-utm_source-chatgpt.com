import html
import json
import math
import os
import re
import urllib.parse

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.storage import db, execute, get_session, log, one, rows, utcnow
from app.whatsapp_integration import send_text_message
from app.zernio_whatsapp import WhatsAppBlocked
from contextlib import nullcontext
from app.logistics_parsing import phone as normalize_phone, accepts_offer, digits
from app.transport_owner import inquiry, select_pending, loading_port_status
from app.driver_offer import driver_phone, offer_message
from app.transport_test import DISCLAIMER, display_reference, accepts_test_offer, owner_inquiry, owner_inquiry_digest


router = APIRouter()


def _init_storage():
    statements = [
        """CREATE TABLE IF NOT EXISTS freight_negotiations(
            id BIGSERIAL PRIMARY KEY,
            shipment_id BIGINT UNIQUE NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
            naqliat_load_id BIGINT REFERENCES naqliat_loads(id) ON DELETE SET NULL,
            owner_phone TEXT,
            status TEXT NOT NULL DEFAULT 'ready_to_contact',
            contact_channel TEXT,
            provider_call_id TEXT,
            provider_message_id TEXT,
            asking_price DOUBLE PRECISION,
            agreed_owner_price DOUBLE PRECISION,
            driver_offer_price DOUBLE PRECISION,
            weight_tons DOUBLE PRECISION,
            unloading_location TEXT,
            payment_method TEXT,
            notes TEXT,
            last_error TEXT,
            contacted_at TIMESTAMPTZ,
            agreed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )""",
        "ALTER TABLE freight_negotiations ADD COLUMN IF NOT EXISTS loading_port_status TEXT",
        "ALTER TABLE freight_negotiations ADD COLUMN IF NOT EXISTS test_owner_contact_status TEXT NOT NULL DEFAULT 'not_sent'",
        "ALTER TABLE freight_negotiations ADD COLUMN IF NOT EXISTS test_owner_approved_by BIGINT",
        "ALTER TABLE freight_negotiations ADD COLUMN IF NOT EXISTS test_owner_preview_digest TEXT",
        "ALTER TABLE freight_negotiations ADD COLUMN IF NOT EXISTS record_kind TEXT NOT NULL DEFAULT 'shipment_request'",
        "ALTER TABLE driver_broadcasts ADD COLUMN IF NOT EXISTS shipment_id BIGINT REFERENCES shipments(id) ON DELETE SET NULL",
        "ALTER TABLE driver_broadcasts ADD COLUMN IF NOT EXISTS accepted_driver_id BIGINT REFERENCES drivers(id) ON DELETE SET NULL",
        "ALTER TABLE driver_broadcasts ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ",
        "ALTER TABLE driver_broadcast_recipients ADD COLUMN IF NOT EXISTS replied_at TIMESTAMPTZ",
    ]
    with db() as c:
        for statement in statements:
            c.execute(statement)
        c.execute(
            """INSERT INTO freight_negotiations(shipment_id,naqliat_load_id,owner_phone,weight_tons,status,created_at,updated_at)
               SELECT s.id,n.id,n.owner_phone,n.weight_tons,'ready_to_contact',%s,%s
               FROM shipments s JOIN naqliat_loads n ON s.reference=('NQ-' || n.id::text)
               ON CONFLICT(shipment_id) DO NOTHING""",
            (utcnow(), utcnow()),
        )


_init_storage()


def esc(value):
    return html.escape(str(value or ""))


def form(raw):
    return {key: value[0] for key, value in urllib.parse.parse_qs(raw.decode(), keep_blank_values=True).items()}


def session(request):
    current = get_session(request.cookies.get("gla_session"))
    if not current:
        raise HTTPException(401, "Login required")
    return current


def ensure_negotiation(shipment_id, load_id=None, owner_phone="", weight_tons=None):
    now = utcnow()
    with db() as c:
        c.execute(
            """INSERT INTO freight_negotiations(shipment_id,naqliat_load_id,owner_phone,weight_tons,status,created_at,updated_at)
               VALUES(%s,%s,%s,%s,'ready_to_contact',%s,%s)
               ON CONFLICT(shipment_id) DO UPDATE SET
                 naqliat_load_id=COALESCE(freight_negotiations.naqliat_load_id,EXCLUDED.naqliat_load_id),
                 owner_phone=COALESCE(NULLIF(freight_negotiations.owner_phone,''),EXCLUDED.owner_phone),
                 weight_tons=COALESCE(freight_negotiations.weight_tons,EXCLUDED.weight_tons),
                 updated_at=EXCLUDED.updated_at""",
            (shipment_id, load_id, owner_phone, weight_tons, now, now),
        )


def _owner_message(item):
    if item.get('is_test'):
        return owner_inquiry(item)
    return inquiry(_usable_text(item.get('origin')) or 'مدينة التحميل',
                   _usable_text(item.get('destination')) or 'مدينة التنزيل')


def _whatsapp_link(phone, message):
    """Create a click-to-chat URL without sending anything through an API."""
    normalized = _valid_phone(phone)
    if not normalized:
        return ""
    return "https://wa.me/" + normalized.lstrip("+") + "?text=" + urllib.parse.quote(message)


async def contact_owner(shipment_id, approved=False, user_id=None):
    item = one("""SELECT s.*,n.record_kind,n.owner_phone,n.status negotiation_status,n.provider_call_id,n.provider_message_id FROM shipments s
        JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?""", (shipment_id,))
    if not item:
        return
    if item.get('record_kind') == 'carrier_offer' or item.get('is_test'):
        return
    terminal = {'contacting', 'contact_uncertain', 'awaiting_owner', 'owner_agreed',
                'driver_offer_pending_approval', 'driver_accepted', 'delivered', 'closed'}
    if item['negotiation_status'] in terminal or item.get('provider_call_id') or item.get('provider_message_id'):
        return
    item['owner_phone'] = _valid_phone(item.get('owner_phone'))
    if not item['owner_phone']:
        execute("UPDATE freight_negotiations SET status='missing_owner_phone',last_error=?,updated_at=? WHERE shipment_id=?",
                ("رقم صاحب الشحنة غير متوفر", utcnow(), shipment_id))
        return
    missing = _shipment_requirements(item)
    # Never cross the WhatsApp sending boundary with an unknown route. The approved
    # owner template requires real origin/destination values; ask the operator to
    # repair extraction on the same shipment instead of producing a non-matching
    # free-form message that will be blocked by Meta.
    if not _usable_text(item.get('origin')) or not _usable_text(item.get('destination')):
        execute("UPDATE freight_negotiations SET status='needs_manual_data',last_error=?,updated_at=? WHERE shipment_id=?",
                ("المسار غير مكتمل؛ صحح مدينة التحميل والتنزيل من النص المحفوظ ثم أعد التواصل. لم تُرسل رسالة", utcnow(), shipment_id))
        return
    if not approved:
        status = 'needs_contact_approval' if missing else 'contact_ready'
        execute("UPDATE freight_negotiations SET status=?,last_error=?,updated_at=? WHERE shipment_id=?",
                (status, "رسالة استكمال البيانات جاهزة لاعتماد التواصل" if missing else "التواصل جاهز للاعتماد", utcnow(), shipment_id))
        return
    if os.getenv("ENABLE_EXTERNAL_ACTIONS", "0") != "1":
        execute("UPDATE freight_negotiations SET status='contact_blocked',last_error=?,updated_at=? WHERE shipment_id=?",
                ("الإرسال الخارجي غير مفعّل على الخادم؛ لم تُرسل رسالة صاحب الشحنة", utcnow(), shipment_id))
        return
    # Claim before any network request. Concurrent invocations cannot send twice.
    with db() as c:
        claimed = c.execute("""UPDATE freight_negotiations SET status='contacting',last_error=NULL,updated_at=%s
            WHERE shipment_id=%s AND record_kind='shipment_request' AND status IN ('ready_to_contact','contact_ready','needs_contact_approval','contact_blocked','contact_failed','needs_manual_data')
              AND COALESCE(provider_call_id,'')='' AND COALESCE(provider_message_id,'')='' RETURNING id""",
            (utcnow(), shipment_id)).fetchone()
    if not claimed:
        return
    channel = os.getenv("FREIGHT_OWNER_CONTACT_CHANNEL", "whatsapp").lower()
    attempted = False
    try:
        if channel == "retell":
            api_key = os.getenv("RETELL_API_KEY", "")
            agent_id = os.getenv("RETELL_AGENT_ID", "")
            from_number = os.getenv("RETELL_FROM_NUMBER", "")
            test_mode = os.getenv("PHONE_CALLS_TEST_MODE", "1") == "1"
            test_phone = _valid_phone(os.getenv("TEST_PHONE_RECIPIENT", ""))
            if test_mode and _valid_phone(item["owner_phone"]) != test_phone:
                raise RuntimeError("وضع اختبار المكالمات يمنع الاتصال برقم صاحب الشحنة")
            if os.getenv("RETELL_TRANSFER_SAFE", "0") != "1":
                raise RuntimeError("تحويل المكالمات في Retell غير مؤمّن")
            if not api_key or not agent_id or not from_number:
                raise RuntimeError("إعدادات Retell غير مكتملة")
            objective = (
                "أنت مفاوض نقل تابع لآفاق طويق. تحقق من هوية صاحب الحمولة ثم ناقش الحمولة "
                f"{item['reference']} من {item.get('origin')} إلى {item.get('destination')}. "
                "اجمع السعر المطلوب وأقل سعر مقبول والوزن وموقع التحميل والتنزيل وموعد التحميل وطريقة الدفع. "
                "كرر جميع الشروط بوضوح واعتبر الاتفاق مبدئياً خاضعاً للتأكيد التشغيلي. "
                "في التحليل أرجع agreed_owner_price وasking_price وweight_tons وunloading_location وpayment_method."
            )
            payload = {"from_number": from_number, "to_number": item["owner_phone"],
                       "override_agent_id": agent_id,
                       "metadata": {"shipment_id": shipment_id, "freight_negotiation": True},
                       "retell_llm_dynamic_variables": {"call_objective": objective,
                           "shipment_reference": item["reference"], "origin": item.get("origin") or "",
                           "destination": item.get("destination") or ""}}
            async with httpx.AsyncClient(timeout=20) as client:
                attempted = True
                response = await client.post("https://api.retellai.com/v2/create-phone-call",
                    headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}, json=payload)
            if response.status_code >= 300:
                raise RuntimeError("Retell HTTP " + str(response.status_code))
            call_id = str((response.json() or {}).get("call_id") or "")
            if not call_id:
                raise RuntimeError("لم يرجع مزود الاتصال معرفًا؛ يلزم التحقق قبل إعادة المحاولة")
            execute("""UPDATE freight_negotiations SET status='awaiting_owner',contact_channel='retell',
                provider_call_id=?,contacted_at=?,last_error=NULL,updated_at=? WHERE shipment_id=?""",
                (call_id, utcnow(), utcnow(), shipment_id))
            log(user_id, "freight_owner_contact_submitted", "shipment", shipment_id, "Provider accepted call: " + call_id)
            return
        if channel != 'whatsapp':
            raise RuntimeError("قناة التواصل المحددة غير مدعومة")
        attempted = True
        result = await send_text_message(item["owner_phone"], _owner_message(item))
        messages = result.get("messages") or []
        provider_id = str(messages[0].get("id") or "") if messages else ""
        if not provider_id:
            raise RuntimeError("لم يرجع مزود الرسائل معرفًا؛ يلزم التحقق قبل إعادة المحاولة")
        execute("""UPDATE freight_negotiations SET status='awaiting_owner',contact_channel='whatsapp',
            provider_message_id=?,contacted_at=?,last_error=NULL,updated_at=? WHERE shipment_id=?""",
            (provider_id, utcnow(), utcnow(), shipment_id))
        log(user_id, "freight_owner_contact_submitted", "shipment", shipment_id, "Provider accepted message: " + provider_id)
    except Exception as exc:
        status = 'contact_blocked' if isinstance(exc, WhatsAppBlocked) else 'contact_uncertain' if attempted else 'contact_failed'
        execute("UPDATE freight_negotiations SET status=?,last_error=?,updated_at=? WHERE shipment_id=?",
                (status, str(exc)[:500], utcnow(), shipment_id))
        log(user_id, status, "shipment", shipment_id, "Contact not verified; automatic retry disabled" if attempted else "Contact configuration needs review")


def sync_retell_negotiation(metadata, custom, summary=""):
    try:
        shipment_id = int(metadata.get("shipment_id"))
    except Exception:
        return False
    if not metadata.get("freight_negotiation"):
        return False
    kind = one('SELECT n.record_kind,s.is_test FROM freight_negotiations n JOIN shipments s ON s.id=n.shipment_id WHERE shipment_id=?', (shipment_id,))
    if kind and (kind.get('record_kind') == 'carrier_offer' or kind.get('is_test')):
        return False
    def number(value):
        match = re.search(r"\d+(?:[.,]\d+)?", str(value or "").replace(",", ""))
        return float(match.group(0)) if match else None
    agreed = number(custom.get("agreed_owner_price") or custom.get("agreed_price"))
    asking = number(custom.get("asking_price"))
    weight = number(custom.get("weight_tons") or custom.get("weight"))
    if agreed and agreed > 150:
        now = utcnow(); driver_price = round(agreed - 150, 2)
        with db() as c:
            if not c.execute('SELECT id FROM shipments WHERE id=%s FOR UPDATE', (shipment_id,)).fetchone():
                return False
            current_kind = c.execute('SELECT record_kind FROM freight_negotiations WHERE shipment_id=%s FOR UPDATE', (shipment_id,)).fetchone()
            if current_kind and current_kind['record_kind'] == 'carrier_offer':
                return False
            if c.execute("SELECT id FROM driver_broadcasts WHERE shipment_id=%s AND status NOT IN ('cancelled','rejected') LIMIT 1", (shipment_id,)).fetchone():
                return True
            c.execute("""UPDATE freight_negotiations SET status='owner_agreed',asking_price=COALESCE(%s,asking_price),
                agreed_owner_price=%s,driver_offer_price=%s,weight_tons=COALESCE(%s,weight_tons),
                unloading_location=COALESCE(NULLIF(%s,''),unloading_location),payment_method=COALESCE(NULLIF(%s,''),payment_method),
                notes=COALESCE(NULLIF(%s,''),notes),agreed_at=%s,updated_at=%s,last_error=NULL WHERE shipment_id=%s""",
                (asking, agreed, driver_price, weight, str(custom.get("unloading_location") or "")[:300],
                 str(custom.get("payment_method") or "")[:200], summary[:3000], now, now, shipment_id))
            c.execute("UPDATE shipments SET revenue=%s,cost=%s,updated_at=%s WHERE id=%s", (agreed, driver_price, now, shipment_id))
        try:
            prepare_driver_offer(shipment_id, None)
        except HTTPException as exc:
            execute("UPDATE freight_negotiations SET last_error=?,updated_at=? WHERE shipment_id=?", (str(exc.detail)[:500], utcnow(), shipment_id))
        return True
    execute("""UPDATE freight_negotiations SET status='needs_review',notes=COALESCE(NULLIF(?,''),notes),updated_at=? WHERE shipment_id=?
        AND record_kind='shipment_request' AND status NOT IN ('driver_offer_pending_approval','driver_accepted','delivered','closed')""",
        (summary[:3000], utcnow(), shipment_id))
    return True


def _valid_phone(value):
    return normalize_phone(value)


def _usable_text(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    invalid = {"-", "—", "غير محدد", "غير معروف", "unknown", "none", "null"}
    return value if len(value) >= 2 and value.lower() not in invalid else ""


def _shipment_requirements(item, agreement=False):
    missing = []
    if not _usable_text(item.get("origin")):
        missing.append("مدينة/موقع التحميل")
    if not _usable_text(item.get("destination")):
        missing.append("مدينة/موقع التنزيل")
    if not _valid_phone(item.get("owner_phone")):
        missing.append("رقم صاحب الشحنة بصيغة دولية")
    if agreement:
        if not item.get("weight_tons") or not math.isfinite(float(item["weight_tons"])) or float(item["weight_tons"]) <= 0:
            missing.append("الوزن")
        if not _usable_text(item.get("unloading_location") or item.get("destination")):
            missing.append("مكان التنزيل")
        if not _usable_text(item.get("payment_method")):
            missing.append("طريقة الدفع")
    return missing


def _require_complete(item, agreement=False):
    if item.get('record_kind') == 'carrier_offer':
        raise HTTPException(409, "هذا عرض ناقل يبحث عن حمولة، وليس طلب نقل من صاحب حمولة")
    missing = _shipment_requirements(item, agreement)
    if missing:
        raise HTTPException(409, "أكمل البيانات أولًا: " + "، ".join(missing))


def prepare_driver_offer(shipment_id, user_id):
    # Lock the shipment so simultaneous agreement submissions share one draft.
    with db() as c:
        item = c.execute("""SELECT s.*,n.record_kind,n.owner_phone,n.agreed_owner_price,n.driver_offer_price,n.weight_tons,n.payment_method,
            n.unloading_location,n.loading_port_status FROM shipments s JOIN freight_negotiations n ON n.shipment_id=s.id
            WHERE s.id=%s FOR UPDATE OF s,n""", (shipment_id,)).fetchone()
        if not item or item.get("agreed_owner_price") is None:
            raise HTTPException(409, "يجب تسجيل اتفاق صاحب الشحنة أولًا")
        _require_complete(item, agreement=True)
        agreed = float(item["agreed_owner_price"])
        if not math.isfinite(agreed) or agreed <= 150:
            raise HTTPException(409, "قيمة الاتفاق غير صالحة لتجهيز العرض")
        existing = c.execute("SELECT id FROM driver_broadcasts WHERE shipment_id=%s AND status NOT IN ('cancelled','rejected') ORDER BY id DESC LIMIT 1", (shipment_id,)).fetchone()
        if existing:
            return existing["id"]
        drivers = c.execute("""SELECT id,driver_name,whatsapp_phone FROM drivers
            WHERE whatsapp_phone IS NOT NULL ORDER BY id""").fetchall()
        valid, seen = [], set()
        for driver in drivers:
            phone = driver_phone(driver.get("whatsapp_phone"))
            if phone and phone not in seen:
                seen.add(phone); valid.append((driver, phone))
        if not valid:
            raise HTTPException(409, "تم حفظ الاتفاق، ولا يوجد سائقون مسجلون بأرقام صالحة")
        price = round(agreed - 150, 2)
        message = offer_message(item)
        now = utcnow()
        bid = c.execute("""INSERT INTO driver_broadcasts(raw_command,message,status,recipient_count,created_by,created_at,updated_at,shipment_id,is_test)
            VALUES(%s,%s,'draft',%s,%s,%s,%s,%s,%s) RETURNING id""",
            ("عرض للشحنة " + item['reference'], message, len(valid), user_id, now, now, shipment_id, bool(item.get('is_test')))).fetchone()['id']
        for driver, phone in valid:
            c.execute("""INSERT INTO driver_broadcast_recipients(broadcast_id,driver_id,driver_name,phone,status)
                VALUES(%s,%s,%s,%s,'pending') ON CONFLICT(broadcast_id,phone) DO NOTHING""", (bid, driver['id'], driver['driver_name'], phone))
        c.execute("UPDATE freight_negotiations SET status='driver_offer_pending_approval',driver_offer_price=%s,updated_at=%s WHERE shipment_id=%s", (price, now, shipment_id))
        c.execute("INSERT INTO shipment_events(shipment_id,event_type,summary,stage,happened_at,created_by) VALUES(%s,%s,%s,%s,%s,%s)",
                  (shipment_id, 'driver_offer_prepared', f"Draft {bid}; margin 150 SAR; {len(valid)} recipients", 'driver_offer_pending_approval', now, user_id))
    log(user_id, 'freight_driver_offer_prepared', 'shipment', shipment_id, f'Draft {bid}; not sent')
    return bid


async def start_driver_broadcast(broadcast_id, user_id=None):
    """Start an already prepared freight offer without a second manual approval.

    The owner agreement is the business trigger; ENABLE_EXTERNAL_ACTIONS remains the
    global kill switch. Claims make this idempotent.
    """
    if os.getenv("ENABLE_EXTERNAL_ACTIONS", "0") != "1":
        return False
    now = utcnow()
    with db() as c:
        claim = c.execute("""UPDATE driver_broadcasts SET status='sending',confirmed_by=COALESCE(confirmed_by,%s),
            confirmed_at=COALESCE(confirmed_at,%s),updated_at=%s
            WHERE id=%s AND status='draft' AND shipment_id IS NOT NULL AND NOT is_test
              AND NOT EXISTS (SELECT 1 FROM shipments s WHERE s.id=shipment_id AND s.is_test) RETURNING id""",
            (user_id, now, now, broadcast_id)).fetchone()
    if not claim:
        return False
    from app.command_assistant import deliver_driver_broadcast
    await deliver_driver_broadcast(broadcast_id)
    return True


def _number_after(pattern, text):
    # Only a directly labelled, unambiguous number is a financial term. Never
    # scan across a line into a shipment reference, phone number or weight.
    text = digits(text).replace("٬", ",").replace("٫", ".")
    matches = list(re.finditer(r"(?<!\w)" + pattern + r"[ \t]*[:：=]?[ \t]*(\d+(?:,\d{3})*(?:\.\d+)?)(?![\d,.])", text, re.I))
    if any(re.match(r"[ \t]*(?:[-–/]|(?:إلى|الى|أو|او)\b)", text[match.end():]) for match in matches):
        return None
    values = {float(match.group(1).replace(",", "")) for match in matches}
    return next(iter(values)) if len(values) == 1 and all(math.isfinite(x) for x in values) else None


def _text_after(pattern, text):
    match = re.search(r"(?<!\w)" + pattern + r"[ \t]*[:：-]?[ \t]*([^\n،;.]{2,200})", text)
    return match.group(1).strip() if match else ""


async def advance_owner_whatsapp_reply(owner_phone, text, shipment_id=None, quoted_message_id=None):
    """Advance only the identified owner's unambiguous pending shipment.

    The receiver passes its verified selection. Recheck identity and state under
    a row lock so two webhook requests cannot overwrite the agreed terms.
    """
    owner_phone = _valid_phone(owner_phone)
    text = str(text or "")
    if not owner_phone:
        return None
    with db() as c:
        pending = c.execute("""SELECT s.*,n.shipment_id,n.owner_phone,n.record_kind,n.asking_price,
            n.weight_tons,n.payment_method,n.unloading_location,n.loading_port_status,n.provider_message_id FROM freight_negotiations n
            JOIN shipments s ON s.id=n.shipment_id
            WHERE n.owner_phone=%s AND n.contact_channel='whatsapp' AND n.status='awaiting_owner'
              AND n.record_kind='shipment_request' ORDER BY s.id FOR UPDATE OF s,n""", (owner_phone,)).fetchall()
        item = select_pending(pending, text, quoted_message_id)
        if item is None:
            return None
        if shipment_id is not None and item['shipment_id'] != shipment_id:
            return None
        sid = item['shipment_id']
        # Questions, rejections and cancellations must not become an agreement.
        if re.search(r"[؟?]|غير\s+(?:متاح[ةه]?|موافق)|(?:لا|لم)\s+(?:أوافق|اوافق|نوافق)|ملغ[ىي]|ملغا[ةه]|تم\s+(?:النقل|التحميل|الحجز)", text):
            return {"shipment_id": sid, "broadcast_id": None, "missing": [], "needs_review": True}
        price_labels = r"(?:السعر(?: النهائي| المعروض)?|اجرة|أجرة|قيمة النقل|سعر النقل)"
        price = _number_after(price_labels, text)
        if re.search(price_labels, text) and (price is None or price <= 150):
            return {"shipment_id": sid, "broadcast_id": None, "missing": ["سعر نهائي واضح أكبر من 150 ريال"]}
        price = price if price is not None else item.get('asking_price')
        weight = _number_after(r"(?:الوزن|وزن(?: الحمولة| البضاعة)?)", text)
        if re.search(r'(?<!\w)(?:الوزن|وزن)', text) and (weight is None or not 0 < weight <= 1000 or re.search(r'(?:الوزن|وزن)[^\n،]*?(?:كجم|كيلو|kg)', text, re.I)):
            weight = 0  # Invalid or unsupported units must request clarification.
        payment = _text_after(r"(?:طريقة الدفع|الدفع)", text)
        port = loading_port_status(text)
        unloading = _text_after(r"(?:مكان التنزيل|موقع التنزيل|التنزيل)", text)
        item.update(weight_tons=weight if weight is not None else item['weight_tons'],
                    payment_method=payment or item['payment_method'],
                    unloading_location=unloading or item['unloading_location'])
        c.execute("""UPDATE freight_negotiations SET asking_price=%s,weight_tons=%s,
            payment_method=%s,unloading_location=%s,loading_port_status=%s,notes=%s,updated_at=%s WHERE shipment_id=%s""",
            (price, item['weight_tons'], item['payment_method'], item['unloading_location'], port or item.get('loading_port_status'), text[:3000], utcnow(), sid))
        missing = _shipment_requirements(item, agreement=True)
        if not price or not math.isfinite(float(price)) or price <= 150:
            missing.insert(0, "السعر النهائي")
        if missing:
            return {"shipment_id": sid, "broadcast_id": None, "missing": missing}
        now = utcnow()
        driver_price = round(price - 150, 2)
        c.execute("""UPDATE freight_negotiations SET status='owner_agreed',agreed_owner_price=%s,
            driver_offer_price=%s,agreed_at=%s,updated_at=%s,last_error=NULL WHERE shipment_id=%s""",
            (price, driver_price, now, now, sid))
        c.execute("UPDATE shipments SET revenue=%s,cost=%s,updated_at=%s WHERE id=%s", (0 if item.get('is_test') else price, 0 if item.get('is_test') else driver_price, now, sid))
    try:
        bid = prepare_driver_offer(sid, None)
    except HTTPException as exc:
        execute("UPDATE freight_negotiations SET last_error=?,updated_at=? WHERE shipment_id=?",
                (str(exc.detail)[:500], utcnow(), sid))
        return {"shipment_id": sid, "broadcast_id": None, "broadcast_sent": False, "missing": [], "blocked": str(exc.detail)}
    if item.get('is_test'):
        return {'shipment_id': sid, 'broadcast_id': bid, 'is_test': True, 'missing': [],
                'broadcast_sent': False, 'blocked': DISCLAIMER + '؛ المسودة تنتظر معاينة واعتماد الاختبار من الإدارة.'}
    await start_driver_broadcast(bid, None)
    broadcast = one("SELECT status,sent_count,failed_count,recipient_count FROM driver_broadcasts WHERE id=?", (bid,))
    return {"shipment_id": sid, "broadcast_id": bid, "missing": [],
            "broadcast_sent": bool(broadcast and broadcast['sent_count']), "broadcast": broadcast,
            "blocked": ("الإرسال الخارجي غير مفعّل؛ بقي العرض مسودة." if broadcast and broadcast['status'] == 'draft'
                        else "لم يرجع مزود واتساب تأكيد قبول الإرسال؛ يلزم مراجعة حالة المستلمين.") if not broadcast or not broadcast['sent_count'] else ""}


def accept_driver_reply(phone, text, connection=None, *, event_id=None, inbound_message_id=None):
    normalized = _valid_phone(phone)
    references = set(re.findall(r"(?<!\w)(?:NQ-\d+|WA-[A-F0-9]{12})(?!\w)", (text or "").upper()))
    if not normalized or len(references) != 1 or not (accepts_offer(text) or accepts_test_offer(text)):
        return False
    reference = next(iter(references))
    with (nullcontext(connection) if connection is not None else db()) as c:
        # All contenders lock the shared broadcast before their own recipient.
        # Locking different recipient rows first can deadlock when the winner
        # closes the other recipients in the same transaction.
        campaign = c.execute("""SELECT b.id broadcast_id,b.shipment_id,b.accepted_driver_id,b.is_test,s.is_test shipment_is_test
            FROM driver_broadcasts b JOIN shipments s ON s.id=b.shipment_id
            WHERE s.reference=%s AND b.status IN ('sending','completed','completed_with_errors','awaiting_driver')
            ORDER BY b.id DESC LIMIT 1 FOR UPDATE OF b""", (reference,)).fetchone()
        if not campaign or campaign['accepted_driver_id']:
            return False
        if bool(campaign['is_test']) != bool(campaign['shipment_is_test']):
            return False
        if campaign['is_test'] and not accepts_test_offer(text):
            return False
        if not campaign['is_test'] and not accepts_offer(text):
            return False
        recovery = c.execute("SELECT id,account_id FROM driver_recovery_batches WHERE broadcast_id=%s", (campaign['broadcast_id'],)).fetchone() if campaign['is_test'] else None
        attempt = None
        if recovery:
            from app.zernio_whatsapp import account_id as recovery_account
            if recovery['account_id'] != recovery_account(): return False
        if recovery:
            attempt = c.execute("""SELECT a.* FROM driver_recovery_attempts a
                WHERE a.batch_id=%s AND a.phone=%s FOR UPDATE""", (recovery['id'], normalized)).fetchone()
        if attempt:
            last_receipt = c.execute('SELECT delivery_status FROM driver_recovery_receipts WHERE attempt_id=%s AND provider_message_id=%s ORDER BY checked_at DESC,id DESC LIMIT 1', (attempt['id'],attempt['provider_message_id'])).fetchone()
            if (attempt['status'] != 'accepted' or not attempt['provider_message_id']
                    or (last_receipt and last_receipt['delivery_status'] in ('failed','deleted'))):
                return False
            recipient = {'recipient_id':attempt['recipient_id'], 'driver_id':attempt['driver_id']}
        else:
            recipient = c.execute("""SELECT id recipient_id,driver_id,provider_account_id,provider_message_id FROM driver_broadcast_recipients
                WHERE broadcast_id=%s AND phone=%s AND status='sent'
                  AND COALESCE(provider_message_id,'')<>'' FOR UPDATE""",
                (campaign['broadcast_id'], normalized)).fetchone()
        if not recipient:
            return False
        if campaign['is_test'] and not attempt and recipient.get('provider_account_id'):
            from app.zernio_whatsapp import account_id as original_account
            if recipient['provider_account_id'] != original_account(): return False
        row = {**campaign, **recipient}
        now = utcnow()
        # Persist the exact successful linkage in the same first-wins transaction.
        # A delivery receipt alone never creates this event or driver consent.
        audit = {'event_id':event_id, 'inbound_message_id':inbound_message_id,
            'broadcast_id':row['broadcast_id'], 'recipient_id':row['recipient_id'],
            'driver_id':row['driver_id'], 'accepted':True, 'is_test':bool(row['is_test']),
            'source':'recovery' if attempt else 'original',
            'recovery_attempt_id':attempt['id'] if attempt else None,
            'provider_message_id':attempt['provider_message_id'] if attempt else recipient['provider_message_id'],
            'account_id':recovery['account_id'] if attempt else recipient.get('provider_account_id'),
            'text':str(text)[:2000]}
        c.execute('''INSERT INTO shipment_events(shipment_id,event_type,summary,stage,happened_at)
            VALUES(%s,%s,%s,%s,%s)''', (row['shipment_id'],
            'driver_test_accepted' if row['is_test'] else 'driver_offer_accepted',
            json.dumps(audit,ensure_ascii=False), 'test_completed' if row['is_test'] else 'driver_assigned', now))
        if row['is_test']:
            c.execute("""UPDATE driver_broadcasts SET status='test_completed',accepted_driver_id=%s,
                accepted_at=%s,updated_at=%s WHERE id=%s AND accepted_driver_id IS NULL""",
                (row['driver_id'], now, now, row['broadcast_id']))
            if recovery:
                # Original send evidence is immutable during recovery. Keep the
                # winner and stop facts in the linked attempts and parent.
                c.execute("""UPDATE driver_recovery_attempts SET
                    status=CASE WHEN id=%s THEN 'test_accepted' WHEN status='pending' THEN 'closed' ELSE status END,
                    replied_at=CASE WHEN id=%s THEN %s ELSE replied_at END WHERE batch_id=%s""",
                    (attempt['id'] if attempt else None, attempt['id'] if attempt else None, now, recovery['id']))
                c.execute("UPDATE driver_recovery_batches SET status='test_completed',completed_at=%s WHERE id=%s", (now,recovery['id']))
            else:
                c.execute("""UPDATE driver_broadcast_recipients SET status=CASE WHEN id=%s THEN 'test_accepted' ELSE 'closed' END,
                    replied_at=CASE WHEN id=%s THEN %s ELSE replied_at END WHERE broadcast_id=%s AND status<>'excluded'""",
                    (row['recipient_id'], row['recipient_id'], now, row['broadcast_id']))
            c.execute("UPDATE freight_negotiations SET status='test_completed',updated_at=%s WHERE shipment_id=%s", (now,row['shipment_id']))
            c.execute("UPDATE shipments SET status='test_completed',revenue=0,cost=0,updated_at=%s WHERE id=%s", (now,row['shipment_id']))
            c.execute("UPDATE shipment_operations SET stage='test_completed',updated_at=%s WHERE shipment_id=%s", (now,row['shipment_id']))
            return True
        c.execute("UPDATE driver_broadcasts SET status='driver_accepted',accepted_driver_id=%s,accepted_at=%s,updated_at=%s WHERE id=%s AND accepted_driver_id IS NULL",
                  (row["driver_id"], now, now, row["broadcast_id"]))
        c.execute("UPDATE driver_broadcast_recipients SET status=CASE WHEN id=%s THEN 'accepted' ELSE 'closed' END,replied_at=CASE WHEN id=%s THEN %s ELSE replied_at END WHERE broadcast_id=%s AND status<>'excluded'",
                  (row["recipient_id"], row["recipient_id"], now, row["broadcast_id"]))
        c.execute("UPDATE freight_negotiations SET status='driver_accepted',updated_at=%s WHERE shipment_id=%s", (now, row["shipment_id"]))
        c.execute("UPDATE shipments SET status='driver_assigned',updated_at=%s WHERE id=%s", (now, row["shipment_id"]))
        c.execute("UPDATE shipment_operations SET stage='driver_assigned',driver_name=(SELECT driver_name FROM drivers WHERE id=%s),driver_phone=(SELECT whatsapp_phone FROM drivers WHERE id=%s),updated_at=%s WHERE shipment_id=%s",
                  (row["driver_id"], row["driver_id"], now, row["shipment_id"]))
    return True


@router.get("/freight-workflow", response_class=HTMLResponse)
def workflow_page(request: Request):
    session(request)
    items = rows("""SELECT s.id,s.reference,s.origin,s.destination,s.status,s.is_test,n.record_kind,n.owner_phone,n.status negotiation_status,
        n.agreed_owner_price,n.driver_offer_price,b.id broadcast_id,b.status broadcast_status,d.driver_name
        FROM shipments s JOIN freight_negotiations n ON n.shipment_id=s.id
        LEFT JOIN LATERAL (SELECT * FROM driver_broadcasts x WHERE x.shipment_id=s.id ORDER BY x.id DESC LIMIT 1) b ON TRUE
        LEFT JOIN drivers d ON d.id=b.accepted_driver_id ORDER BY s.id DESC""")
    from app.transport_status import snapshot, current_status
    with db() as c:
        for item in items:
            broadcast = c.execute('SELECT * FROM driver_broadcasts WHERE id=%s', (item['broadcast_id'],)).fetchone() if item.get('broadcast_id') else None
            evidence = snapshot(c,broadcast)
            item['effective_status'] = current_status(item['status'],item['negotiation_status'],evidence)
    table = "".join(f"<tr><td><a href='/freight-workflow/{x['id']}'>{esc(display_reference(x['reference'],x.get('is_test')))}</a></td><td>{esc(x['origin'])} → {esc(x['destination'])}</td><td dir=ltr>{esc(x['owner_phone'])}</td><td>{esc('عرض ناقل يبحث عن حمولة' if x.get('record_kind') == 'carrier_offer' else x['negotiation_status'])}</td><td>{esc(x['agreed_owner_price'])}</td><td>{esc(x['driver_offer_price'])}</td><td>{esc(x.get('effective_status'))}</td><td>{esc(x.get('driver_name'))}</td></tr>" for x in items)
    return HTMLResponse(_page("إدارة عروض الشحن", f"<h1>إدارة عروض الشحن</h1><p><a href='/dashboard'>الرئيسية</a></p><div class=card><table><tr><th>الشحنة</th><th>المسار</th><th>صاحب الشحنة</th><th>التفاوض</th><th>اتفاق المالك</th><th>عرض السائق</th><th>الإرسال</th><th>السائق المقبول</th></tr>{table or '<tr><td colspan=8>لا توجد شحنات.</td></tr>'}</table></div>"))


def _page(title, body):
    return f"""<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{esc(title)}</title><style>body{{font-family:Arial;background:#07131f;color:#eef6fb;margin:0;padding:24px}}a{{color:#86efac}}.card{{max-width:1100px;margin:14px auto;background:#102536;padding:20px;border-radius:16px;overflow:auto}}input,textarea,button{{width:100%;padding:11px;margin:6px 0;box-sizing:border-box;border-radius:8px;border:1px solid #36586e}}button{{background:#ff7900;color:white;font-weight:bold}}.manual{{display:block;padding:12px;margin:10px 0;border-radius:9px;background:#22c55e;color:#04130a;text-align:center;text-decoration:none;font-weight:bold}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #28475d;text-align:right}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}}.warn{{color:#fde68a}}.good{{color:#86efac}}hr{{border:0;border-top:1px solid #36586e;margin:20px 0}}</style>{body}</html>"""


@router.get("/freight-workflow/{shipment_id}", response_class=HTMLResponse)
def workflow_detail(shipment_id: int, request: Request):
    current = session(request)
    item = one("""SELECT s.*,n.record_kind,n.id negotiation_id,n.owner_phone,n.status negotiation_status,n.asking_price,
        n.agreed_owner_price,n.driver_offer_price,n.weight_tons,n.unloading_location,n.payment_method,n.notes,n.last_error,
        n.provider_message_id,n.provider_call_id,n.contact_channel,n.naqliat_load_id,n.test_owner_contact_status
        FROM shipments s JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?""", (shipment_id,))
    if not item: raise HTTPException(404)
    classification = f"""<h2>تصنيف السجل</h2>
    <p>تصنيف هذا الطلب مستقل عن رقم التواصل؛ يمكن للشخص نفسه عرض عدة شحنات.</p>
    <form method=post action='/freight-workflow/{shipment_id}/classification'>
    <input type=hidden name=csrf value='{esc(current['csrf'])}'>
    <label>نوع السجل <select name=record_kind>
    <option value=shipment_request {'selected' if item['record_kind']=='shipment_request' else ''}>طلب نقل من صاحب حمولة</option>
    <option value=carrier_offer {'selected' if item['record_kind']=='carrier_offer' else ''}>عرض ناقل يبحث عن حمولة</option>
    </select></label><button>حفظ التصنيف</button></form>"""
    if item['record_kind'] == 'carrier_offer':
        return HTMLResponse(_page(item['reference'], f"""<div class=card><h1>{esc(item['reference'])}</h1>
        <p><a href='/freight-workflow'>العودة إلى السجلات</a></p>
        <h2>عرض ناقل يبحث عن حمولة</h2><p>من {esc(item['origin'])} إلى {esc(item['destination'])}</p>
        <p>رقم الناقل: <span dir=ltr>{esc(item['owner_phone'])}</span></p>
        <p>محفوظ كعرض ناقل؛ لا يُرسل له طلب تسعير بصفته صاحب حمولة، ولا يُجهز منه عرض للسائقين.</p>
        {classification}</div>"""))
    broadcast = one("SELECT * FROM driver_broadcasts WHERE shipment_id=? ORDER BY id DESC LIMIT 1", (shipment_id,))
    from app.transport_status import snapshot, evidence_lines, current_status
    with db() as c: transport_evidence = snapshot(c, broadcast)
    effective_status = current_status(item['status'],item['negotiation_status'],transport_evidence)
    source = one("SELECT raw_text,description,capture_method,captured_at FROM naqliat_loads WHERE id=?",
                 (item.get('naqliat_load_id'),)) if item.get('naqliat_load_id') else None
    source_text = ((source or {}).get('raw_text') or (source or {}).get('description') or '').strip()
    owner_states = {
        'ready_to_contact': 'لم يُرسل؛ جاهز لتجهيز التواصل',
        'contact_ready': 'لم يُرسل؛ بانتظار اعتماد التواصل',
        'needs_contact_approval': 'لم يُرسل؛ استكمال البيانات بانتظار اعتماد التواصل',
        'contact_blocked': 'لم يُرسل؛ قناة التواصل تمنع الإرسال',
        'contact_failed': 'تعذر بدء التواصل؛ راجع سبب التوقف',
        'contacting': 'جارٍ التواصل؛ لا تكرر الإرسال',
        'contact_uncertain': 'نتيجة الإرسال غير مؤكدة؛ يلزم التحقق قبل إعادة المحاولة',
    }
    owner_state = ('قبل مزود التواصل الطلب؛ هذا لا يثبت وصوله للمستلم'
                   if item.get('provider_message_id') or item.get('provider_call_id') else
                   owner_states.get(item['negotiation_status'], 'لا يوجد معرّف إرسال موثق في هذا السجل'))
    driver_state = (f"عرض موجود — {effective_status}؛ راجع سجل المستلمين" if broadcast else
                    'لم يُجهز عرض للسائقين بعد؛ يلزم استكمال بيانات الشحنة وتوثيق السعر وطريقة الدفع')
    diagnostics = f"""<section class=card id=contact-diagnostics><h2>تشخيص التواصل</h2>
    <p><b>status:</b> {esc(item.get('negotiation_status'))}</p>
    <p><b>contact_channel:</b> {esc(item.get('contact_channel') or 'غير مسجل')}</p>
    <p><b>provider_message_id:</b> {esc(item.get('provider_message_id') or 'لا يوجد')}</p>
    <p><b>provider_call_id:</b> {esc(item.get('provider_call_id') or 'لا يوجد')}</p>
    <p><b>last_error:</b> {esc(item.get('last_error') or 'لا يوجد')}</p></section>"""
    progress = f"""<section class=card id=shipment-progress><h2>ماذا تم في هذه الشحنة؟</h2>
    <p>الاستلام: محفوظة بالمرجع {esc(item['reference'])}.</p>
    <p>صاحب الشحنة: {esc(owner_state)}.</p><p>السائقون: {esc(driver_state)}.</p></section>"""
    progress += '<section class=card id=transport-evidence><h2>دليل الإرسال والقبول</h2>' + ''.join('<p>' + esc(line) + '</p>' for line in evidence_lines(transport_evidence)) + '</section>'
    if source:
        from app.transport_intake import extract_transport
        extracted = extract_transport(source_text)
        source_html = f"""<section class=card id=source-review><h2>النص الذي وصل من الهاتف</h2>
        <p>وقت الاستلام: {esc(source.get('captured_at'))}. إعادة القراءة تستخدم نفس الشحنة.</p>
        <textarea readonly rows=8 aria-label='النص الأصلي المستلم'>{esc(source_text)}</textarea>
        <p>نتيجة قراءة النص الآن — التحميل: {esc(extracted.get('origin') or 'يحتاج مراجعة')}؛
        التنزيل: {esc(extracted.get('destination') or 'يحتاج مراجعة')}.</p>"""
        if not source_text:
            source_html += '<p class=warn>وصل سجل دون نص قابل للاستخراج؛ لا يمكن معرفة المسار من رقم الهاتف وحده.</p>'
        elif current.get('role') in ('admin', 'transport'):
            source_html += f"""<form method=post action='/freight-workflow/{shipment_id}/reextract'>
            <input type=hidden name=csrf value='{esc(current['csrf'])}'>
            <button>إعادة استخراج البيانات الناقصة من النص المحفوظ</button></form>
            <p>يملأ الحقول الناقصة فقط. راجع النتيجة ثم تابع التواصل من نفس الصفحة.</p>"""
        source_html += '</section>'
    else:
        source_html = ''
    missing_contact = _shipment_requirements(item)
    readiness = ("<p class=good>بيانات المسار والتواصل مكتملة.</p>" if not missing_contact else
                 "<p class=warn>يلزم استكمال: " + esc("، ".join(missing_contact)) + "</p>")
    owner_link = "" if item.get("is_test") else _whatsapp_link(item.get("owner_phone"), _owner_message(item))
    manual_contact = (f"<a class=manual href='{esc(owner_link)}' target='_blank' rel='noopener'>فتح واتساب لصاحب الشحنة برسالة جاهزة</a>"
                      "<p class=warn>هذا الزر يفتح المحادثة فقط؛ راجع الرسالة واضغط إرسال داخل واتساب بنفسك.</p>"
                      if owner_link else "")
    replies = rows("SELECT summary,happened_at FROM shipment_events WHERE shipment_id=? AND event_type='owner_whatsapp_reply' ORDER BY id DESC LIMIT 10", (shipment_id,))
    reply_html = "<h2>ردود صاحب الحمولة عبر واتساب</h2>" + ("".join("<p>" + esc(x['happened_at']) + "</p><p style='white-space:pre-wrap'>" + esc(x['summary']) + "</p>" for x in replies) or "<p>لم يصل رد مرتبط بهذه الشحنة بعد.</p>")
    classification += "<p><a href='/settings/whatsapp/channel'>حالة قناة واتساب وقوالب Meta</a></p>" + reply_html
    diagnostics = f"""<section class=card id=freight-diagnostics><h2>تشخيص مسار النقل</h2>
    <table>
    <tr><th>status</th><td>{esc(item.get('negotiation_status'))}</td></tr>
    <tr><th>contact_channel</th><td>{esc(item.get('contact_channel') or '—')}</td></tr>
    <tr><th>provider_message_id</th><td dir=ltr>{esc(item.get('provider_message_id') or '—')}</td></tr>
    <tr><th>provider_call_id</th><td dir=ltr>{esc(item.get('provider_call_id') or '—')}</td></tr>
    <tr><th>last_error</th><td>{esc(item.get('last_error') or '—')}</td></tr>
    </table></section>"""
    owner_contact_control = f"""<form method=post action='/freight-workflow/{shipment_id}/contact-owner'><input type=hidden name=csrf value='{esc(current['csrf'])}'><button>اعتماد التواصل مع صاحب الشحنة</button></form>"""
    if item.get('is_test'):
        owner_contact_control = '<p>حالة استفسار الاختبار: ' + esc(item.get('test_owner_contact_status')) + '</p>'
        if (current.get('role') == 'admin' and item.get('test_owner_contact_status') in ('not_sent', 'blocked')
                and not item.get('provider_message_id') and item['negotiation_status'] == 'awaiting_owner'):
            owner_contact_control += f"""<form method=post action='/freight-workflow/{shipment_id}/test-owner-inquiry'>
            <input type=hidden name=csrf value='{esc(current['csrf'])}'>
            <input type=hidden name=test_owner_preview value='{owner_inquiry_digest(item)}'>
            <label><input type=checkbox name=test_owner_confirmed value=yes required> راجعت استفسار الاختبار أعلاه ورقم صاحبه وأعتمد إرساله مرة واحدة</label>
            <button>إرسال استفسار الاختبار المعلن لصاحبه</button></form>"""
    controls = diagnostics + progress + source_html + classification + f"""<h2>الاستخراج والتصحيح اليدوي</h2>
    <p>راجع نتيجة الاستخراج. عند نقص المسار يمكنك تجهيز طلب استكمال لصاحب الشحنة إذا كان رقمه صحيحًا.</p>
    <form method=post action='/freight-workflow/{shipment_id}/manual-data'><input type=hidden name=csrf value='{esc(current['csrf'])}'><div class=grid>
    <input name=origin required placeholder='مدينة أو موقع التحميل' value='{esc(item.get('origin'))}'>
    <input name=destination required placeholder='مدينة أو موقع التنزيل' value='{esc(item.get('destination'))}'>
    <input name=owner_phone required dir=ltr placeholder='+9665xxxxxxxx' value='{esc(item.get('owner_phone'))}'>
    <input name=weight_tons type=number min=.01 step=.01 placeholder='الوزن بالطن' value='{esc(item.get('weight_tons'))}'>
    </div><button>حفظ البيانات المصححة يدويًا</button></form>{readiness}{manual_contact}<hr>
    <div class=card><h3>رسالة التواصل المقترحة</h3><p style='white-space:pre-wrap'>{esc(_owner_message(item)) if not item.get('provider_message_id') else 'سبق إرسال الاستفسار؛ لم يُعد إرساله أو تغيير الرسالة السابقة.'}</p></div>
    {owner_contact_control}
    <form method=post action='/freight-workflow/{shipment_id}/agreement'><input type=hidden name=csrf value='{esc(current['csrf'])}'><div class=grid><input name=asking_price type=number step=.01 placeholder='السعر المطلوب' value='{esc(item.get('asking_price'))}'><input name=agreed_owner_price type=number step=.01 required placeholder='السعر المتفق مع صاحب الشحنة' value='{esc(item.get('agreed_owner_price'))}'><input name=weight_tons type=number step=.01 placeholder='الوزن طن' value='{esc(item.get('weight_tons'))}'><input name=unloading_location placeholder='مكان التنزيل' value='{esc(item.get('unloading_location'))}'><input name=payment_method placeholder='طريقة الدفع' value='{esc(item.get('payment_method'))}'></div><textarea name=notes placeholder='ملخص التفاوض'>{esc(item.get('notes'))}</textarea><button>حفظ الاتفاق وتجهيز عرض السائقين ناقص 150 ريال</button></form>"""
    if item.get('is_test'):
        controls = '<h2 class=warn>' + DISCLAIMER + '</h2><p>قيم المحاكاة لا تمثل التزامًا ماليًا. أرسل شروط الاختبار من رقم صاحبه المسجل، أو رد مباشرة على رسالة الاستفسار. لا يُرسل عرض السائقين تلقائيًا.</p>' + controls
    if broadcast:
        controls += f"<p><a href='/commands/broadcast/{broadcast['id']}'>مراجعة العرض وتأكيد الإرسال الجماعي مرة واحدة</a> — الحالة: {esc(broadcast['status'])}</p>"
    return HTMLResponse(_page(item["reference"], f"<div class=card><h1>{esc(item['reference'])}</h1><p>{esc(item['origin'])} → {esc(item['destination'])}</p><p>صاحب الشحنة: <span dir=ltr>{esc(item['owner_phone'])}</span> | الحالة الحالية: {esc(effective_status)}</p><p class=warn>{esc(item.get('last_error'))}</p>{controls}</div>"))


@router.post('/freight-workflow/{shipment_id}/reextract')
async def reextract_saved_source(shipment_id: int, request: Request):
    current = session(request)
    data = form(await request.body())
    if current.get('role') not in ('admin', 'transport') or data.get('csrf') != current['csrf']:
        raise HTTPException(403)
    from app.transport_intake import extract_transport
    with db() as c:
        item = c.execute("""SELECT s.id,s.origin,s.destination,n.* FROM shipments s
            JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=%s FOR UPDATE OF s,n""",
            (shipment_id,)).fetchone()
        if not item:
            raise HTTPException(404, 'الشحنة غير موجودة')
        if (item.get('record_kind') != 'shipment_request' or item.get('provider_message_id') or
            item.get('provider_call_id') or item.get('agreed_owner_price') is not None or
            item['status'] not in ('ready_to_contact', 'contact_ready', 'needs_contact_approval',
                                   'contact_blocked', 'contact_failed', 'needs_manual_data', 'missing_owner_phone') or
            c.execute("SELECT id FROM driver_broadcasts WHERE shipment_id=%s AND status NOT IN ('cancelled','rejected') LIMIT 1",
                      (shipment_id,)).fetchone()):
            raise HTTPException(409, 'بدأ تنفيذ هذا السجل أو تغير تصنيفه؛ راجع بياناته قبل إعادة الاستخراج')
        source = c.execute('SELECT raw_text,description FROM naqliat_loads WHERE id=%s FOR UPDATE',
                           (item.get('naqliat_load_id'),)).fetchone()
        raw = ((source or {}).get('raw_text') or (source or {}).get('description') or '').strip()
        if not raw:
            raise HTTPException(409, 'لم يصل نص قابل للاستخراج مع الالتقاط؛ السجل محفوظ ولم يتغير')
        extracted = extract_transport(raw)
        for key in ('origin', 'destination'):
            if (_usable_text(item.get(key)) and extracted.get(key) and
                _usable_text(item[key]) != extracted[key]):
                raise HTTPException(409, 'النص يتعارض مع المسار المسجل؛ راجع المصدر قبل التعديل')
        updates = {}
        for key in ('origin', 'destination', 'owner_phone', 'weight_tons'):
            existing = (_valid_phone(item.get(key)) if key == 'owner_phone' else
                        item.get(key) if key == 'weight_tons' else _usable_text(item.get(key)))
            if not existing and extracted.get(key):
                updates[key] = extracted[key]
        if not updates:
            raise HTTPException(409, 'لم تُستخرج بيانات جديدة موثوقة؛ راجع النص المعروض. لم يتغير السجل ولم تُرسل رسائل')
        item.update(updates)
        now = utcnow()
        c.execute('UPDATE shipments SET origin=%s,destination=%s,updated_at=%s WHERE id=%s',
                  (item['origin'], item['destination'], now, shipment_id))
        c.execute('UPDATE naqliat_loads SET origin=%s,destination=%s,owner_phone=%s,weight_tons=%s WHERE id=%s',
                  (item['origin'], item['destination'], item.get('owner_phone'), item.get('weight_tons'), item['naqliat_load_id']))
        status = 'needs_contact_approval' if _shipment_requirements(item) else 'contact_ready'
        c.execute('UPDATE freight_negotiations SET owner_phone=%s,weight_tons=%s,status=%s,last_error=NULL,updated_at=%s WHERE shipment_id=%s',
                  (item.get('owner_phone'), item.get('weight_tons'), status, now, shipment_id))
        c.execute("""INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at)
            VALUES(%s,'freight_source_reextracted','shipment',%s,%s,%s)""",
                  (current['user_id'], shipment_id, 'Filled missing fields: ' + ', '.join(sorted(updates)), now))
    return RedirectResponse(f'/freight-workflow/{shipment_id}#source-review', 303)


@router.post("/freight-workflow/{shipment_id}/classification")
async def classify_record(shipment_id: int, request: Request):
    current = session(request)
    data = form(await request.body())
    if data.get('csrf') != current['csrf']:
        raise HTTPException(403)
    kind = data.get('record_kind')
    if kind not in ('shipment_request', 'carrier_offer'):
        raise HTTPException(400, 'تصنيف غير صالح')
    with db() as c:
        item = c.execute("""SELECT s.id,n.* FROM shipments s JOIN freight_negotiations n
            ON n.shipment_id=s.id WHERE s.id=%s FOR UPDATE OF s,n""", (shipment_id,)).fetchone()
        if not item:
            raise HTTPException(404)
        if item['record_kind'] == kind:
            return RedirectResponse(f'/freight-workflow/{shipment_id}', 303)
        if (item.get('provider_call_id') or item.get('provider_message_id') or
            item.get('agreed_owner_price') is not None or item['status'] in
            ('contacting','contact_uncertain','awaiting_owner','driver_accepted','delivered','closed') or
            c.execute("SELECT id FROM driver_broadcasts WHERE shipment_id=%s AND status NOT IN ('cancelled','rejected') LIMIT 1", (shipment_id,)).fetchone()):
            raise HTTPException(409, 'بدأ تنفيذ هذا السجل؛ يلزم مراجعته قبل تغيير التصنيف')
        status = 'carrier_offer' if kind == 'carrier_offer' else 'ready_to_contact'
        c.execute("""UPDATE freight_negotiations SET record_kind=%s,status=%s,
            last_error=NULL,updated_at=NOW() WHERE shipment_id=%s""", (kind, status, shipment_id))
        # Preserve source, reference, phone, route and all other independent loads.
        c.execute("UPDATE shipments SET status=%s,updated_at=NOW() WHERE id=%s",
                  ('carrier_offer' if kind == 'carrier_offer' else 'new', shipment_id))
        c.execute("""INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at)
            VALUES(%s,'freight_classification_updated','shipment',%s,%s,NOW())""",
                  (current['user_id'], shipment_id, kind))
    return RedirectResponse(f'/freight-workflow/{shipment_id}', 303)


@router.post("/freight-workflow/{shipment_id}/manual-data")
async def save_manual_data(shipment_id: int, request: Request):
    current = session(request); data = form(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    item = one("""SELECT s.id,s.is_test,n.record_kind,n.naqliat_load_id FROM shipments s
        JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?""", (shipment_id,))
    if not item: raise HTTPException(404, "الشحنة غير موجودة")
    if item.get('record_kind') == 'carrier_offer':
        raise HTTPException(409, "عرض ناقل؛ لا تعدله كطلب حمولة")
    origin = _usable_text(data.get("origin")); destination = _usable_text(data.get("destination"))
    phone = _valid_phone(data.get("owner_phone"))
    if not origin or not destination:
        raise HTTPException(400, "أدخل موقع التحميل وموقع التنزيل")
    if not phone:
        raise HTTPException(400, "أدخل رقم صاحب الشحنة بالصيغة الدولية مثل +9665xxxxxxxx")
    try:
        weight = float(data["weight_tons"]) if data.get("weight_tons") else None
    except ValueError:
        raise HTTPException(400, "الوزن غير صحيح")
    if weight is not None and (not math.isfinite(weight) or weight <= 0):
        raise HTTPException(400, "الوزن يجب أن يكون أكبر من صفر")
    now = utcnow()
    with db() as c:
        c.execute('SELECT id FROM shipments WHERE id=%s FOR UPDATE', (shipment_id,)).fetchone()
        locked = c.execute('SELECT record_kind,test_owner_contact_status FROM freight_negotiations WHERE shipment_id=%s FOR UPDATE', (shipment_id,)).fetchone()
        if item.get('is_test') and locked and locked['test_owner_contact_status'] not in ('not_sent', 'blocked'):
            raise HTTPException(409, 'بدأ إرسال استفسار الاختبار؛ لا تغيّر صاحبه أو مساره أثناء انتظار النتيجة')
        if locked and locked['record_kind'] == 'carrier_offer':
            raise HTTPException(409, 'هذا عرض ناقل وليس طلب حمولة')
        if c.execute("SELECT id FROM driver_broadcasts WHERE shipment_id=%s AND status NOT IN ('cancelled','rejected') LIMIT 1", (shipment_id,)).fetchone():
            raise HTTPException(409, "يوجد عرض لهذه الشحنة؛ راجع العرض قبل تعديل بيانات الحمولة")
        c.execute("UPDATE shipments SET origin=%s,destination=%s,updated_at=%s WHERE id=%s",
                  (origin, destination, now, shipment_id))
        c.execute("""UPDATE freight_negotiations SET owner_phone=%s,weight_tons=%s,status=%s,
            last_error=NULL,updated_at=%s WHERE shipment_id=%s""", (phone, weight, 'awaiting_owner' if item.get('is_test') else 'ready_to_contact', now, shipment_id))
        if item.get("naqliat_load_id"):
            c.execute("UPDATE naqliat_loads SET origin=%s,destination=%s,owner_phone=%s,weight_tons=%s WHERE id=%s",
                      (origin, destination, phone, weight, item["naqliat_load_id"]))
    log(current["user_id"], "freight_manual_data_updated", "shipment", shipment_id,
        origin + " → " + destination)
    return RedirectResponse(f"/freight-workflow/{shipment_id}", 303)


async def send_test_owner_inquiry(shipment_id, user_id, preview):
    """Single-flight disclosed inquiry; uncertain results never retry themselves."""
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        raise HTTPException(409, 'الإرسال الخارجي غير مفعّل؛ لم تُرسل الرسالة')
    with db() as c:
        # Share one lock order with receipt finalization. A duplicate start must
        # never hold the shipment while finalization holds its negotiation.
        c.execute('SELECT id FROM shipments WHERE id=%s FOR UPDATE', (shipment_id,)).fetchone()
        item = c.execute("""SELECT s.*,n.owner_phone,n.status negotiation_status,n.provider_message_id,
            n.test_owner_contact_status FROM shipments s JOIN freight_negotiations n ON n.shipment_id=s.id
            WHERE s.id=%s FOR UPDATE OF n""", (shipment_id,)).fetchone()
        if not item or not item.get('is_test'):
            raise HTTPException(409, 'هذا الإجراء مخصص لسجل اختبار معلن فقط')
        if (not user_id or not _valid_phone(item.get('owner_phone'))
                or preview != owner_inquiry_digest(item)):
            raise HTTPException(400, 'راجع نص الاختبار ورقم صاحبه من الصفحة الحالية قبل الإرسال')
        if (item['negotiation_status'] != 'awaiting_owner' or item.get('provider_message_id')
                or item['test_owner_contact_status'] not in ('not_sent', 'blocked')):
            raise HTTPException(409, 'بدأ إرسال استفسار الاختبار أو وصلت نتيجته أو تقدم الاختبار؛ لا تكرر الإرسال')
        c.execute("""UPDATE freight_negotiations SET test_owner_contact_status='sending',
            test_owner_approved_by=%s,test_owner_preview_digest=%s,last_error=NULL,updated_at=%s WHERE shipment_id=%s""",
            (user_id, preview, utcnow(), shipment_id))
    try:
        # The existing adapter verifies the configured account and current owner
        # conversation window, or requires an exact approved template match.
        result = await send_text_message(item['owner_phone'], owner_inquiry(item))
        messages = result.get('messages') or []
        receipt = str(messages[0].get('id') or '') if messages else ''
        if not receipt:
            raise RuntimeError('لم يرجع المزود معرفًا؛ تحقق من المحادثة قبل أي محاولة أخرى')
        with db() as c:
            c.execute('SELECT id FROM shipments WHERE id=%s FOR UPDATE', (shipment_id,)).fetchone()
            now = utcnow()
            c.execute("""UPDATE freight_negotiations SET test_owner_contact_status='sent',provider_message_id=%s,
                contact_channel='whatsapp',contacted_at=%s,last_error=NULL,updated_at=%s WHERE shipment_id=%s""",
                (receipt, now, now, shipment_id))
            c.execute("""INSERT INTO shipment_events(shipment_id,event_type,summary,stage,happened_at,created_by)
                VALUES(%s,'test_owner_inquiry_submitted',%s,'test_pending',%s,%s)""",
                (shipment_id, 'اختبار معلن؛ قبول المزود لا يثبت التسليم أو القراءة. Provider ID: ' + receipt, now, user_id))
        return receipt
    except Exception as exc:
        state = 'blocked' if isinstance(exc, WhatsAppBlocked) else 'uncertain'
        execute("""UPDATE freight_negotiations SET test_owner_contact_status=?,last_error=?,updated_at=?
            WHERE shipment_id=? AND test_owner_contact_status='sending'""", (state, str(exc)[:500], utcnow(), shipment_id))
        return None


@router.post('/freight-workflow/{shipment_id}/test-owner-inquiry')
async def test_owner_inquiry_now(shipment_id: int, request: Request):
    current = session(request)
    data = form(await request.body())
    if current.get('role') != 'admin' or data.get('csrf') != current['csrf']:
        raise HTTPException(403)
    if data.get('test_owner_confirmed') != 'yes':
        raise HTTPException(400, 'يلزم اعتماد استفسار الاختبار المعلن صراحة')
    await send_test_owner_inquiry(shipment_id, current['user_id'], data.get('test_owner_preview'))
    return RedirectResponse(f'/freight-workflow/{shipment_id}', 303)


@router.post("/freight-workflow/{shipment_id}/contact-owner")
async def contact_owner_now(shipment_id: int, request: Request, background_tasks: BackgroundTasks):
    current = session(request); data = form(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    item = one("""SELECT s.origin,s.destination,s.is_test,n.record_kind,n.owner_phone FROM shipments s
        JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?""", (shipment_id,))
    if not item: raise HTTPException(404, "الشحنة غير موجودة")
    if item.get('is_test'):
        raise HTTPException(409, DISCLAIMER + '؛ ينتظر الاختبار رسالة واردة من صاحبه ولا يرسل طلب حمولة حقيقية')
    if item.get('record_kind') == 'carrier_offer':
        raise HTTPException(409, "هذا عرض ناقل وليس طلب حمولة")
    if not _valid_phone(item.get('owner_phone')):
        raise HTTPException(409, "يلزم رقم صحيح لصاحب الشحنة لتجهيز التواصل")
    background_tasks.add_task(contact_owner, shipment_id, approved=True, user_id=current['user_id'])
    return RedirectResponse(f"/freight-workflow/{shipment_id}", 303)


@router.post("/freight-workflow/{shipment_id}/agreement")
async def save_agreement(shipment_id: int, request: Request):
    current = session(request); data = form(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    try:
        agreed = float(data.get("agreed_owner_price") or 0)
        asking = float(data["asking_price"]) if data.get("asking_price") else None
        weight = float(data["weight_tons"]) if data.get("weight_tons") else None
    except ValueError:
        raise HTTPException(400, "تحقق من السعر والوزن")
    if not math.isfinite(agreed) or agreed <= 150: raise HTTPException(400, "سعر صاحب الشحنة يجب أن يكون رقمًا أكبر من 150 ريال")
    if (weight is not None and (not math.isfinite(weight) or weight <= 0)) or (asking is not None and (not math.isfinite(asking) or asking < 0)):
        raise HTTPException(400, "تحقق من السعر والوزن")
    item = one("""SELECT s.origin,s.destination,s.is_test,n.record_kind,n.owner_phone FROM shipments s
        JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?""", (shipment_id,))
    if not item: raise HTTPException(404, "الشحنة غير موجودة")
    item.update({"weight_tons": weight, "unloading_location": data.get("unloading_location"),
                 "payment_method": data.get("payment_method")})
    _require_complete(item, agreement=True)
    driver_price = round(agreed - 150, 2)
    now = utcnow()
    with db() as c:
        c.execute('SELECT id FROM shipments WHERE id=%s FOR UPDATE', (shipment_id,)).fetchone()
        locked = c.execute('SELECT record_kind FROM freight_negotiations WHERE shipment_id=%s FOR UPDATE', (shipment_id,)).fetchone()
        if locked and locked['record_kind'] == 'carrier_offer':
            raise HTTPException(409, 'هذا عرض ناقل وليس طلب حمولة')
        existing = c.execute("SELECT id FROM driver_broadcasts WHERE shipment_id=%s AND status NOT IN ('cancelled','rejected') LIMIT 1", (shipment_id,)).fetchone()
        if existing:
            raise HTTPException(409, "يوجد عرض لهذه الشحنة؛ راجع العرض الحالي قبل تعديل الاتفاق")
        c.execute("""UPDATE freight_negotiations SET status='owner_agreed',asking_price=%s,agreed_owner_price=%s,driver_offer_price=%s,
            weight_tons=%s,unloading_location=%s,payment_method=%s,notes=%s,agreed_at=%s,updated_at=%s,last_error=NULL WHERE shipment_id=%s""",
            (asking, agreed, driver_price, weight, data.get("unloading_location"), data.get("payment_method"), data.get("notes"), now, now, shipment_id))
        c.execute("UPDATE shipments SET revenue=%s,cost=%s,updated_at=%s WHERE id=%s", (0 if item.get('is_test') else agreed, 0 if item.get('is_test') else driver_price, now, shipment_id))
    bid = prepare_driver_offer(shipment_id, current["user_id"])
    return RedirectResponse(f"/commands/broadcast/{bid}", 303)


@router.get("/api/v7/freight-workflow")
def workflow_api(request: Request):
    session(request)
    from app.transport_status import snapshot, current_status
    items = rows("SELECT n.*,s.status shipment_status FROM freight_negotiations n JOIN shipments s ON s.id=n.shipment_id ORDER BY n.id DESC LIMIT 200")
    with db() as c:
        for item in items:
            broadcast = c.execute('SELECT * FROM driver_broadcasts WHERE shipment_id=%s ORDER BY id DESC LIMIT 1', (item['shipment_id'],)).fetchone()
            evidence = snapshot(c, broadcast)
            item['transport_evidence'] = evidence
            item['effective_status'] = current_status(item['shipment_status'],item['status'],evidence)
    return {"owner_auto_contact_enabled": os.getenv("ENABLE_EXTERNAL_ACTIONS", "0") == "1",
            "driver_margin_sar": 150, "items": items}

