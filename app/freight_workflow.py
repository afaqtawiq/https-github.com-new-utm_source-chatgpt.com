import html
import json
import os
import re
import urllib.parse

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.storage import db, execute, get_session, log, one, rows, utcnow
from app.whatsapp_integration import send_text_message


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
    return (
        "السلام عليكم، معك آفاق طويق للنقل والخدمات اللوجستية.\n"
        f"وصلنا طلب الحمولة رقم {item['reference']} من {item.get('origin') or 'المنشأ'} "
        f"إلى {item.get('destination') or 'الوجهة'}.\n"
        "نرجو تأكيد: السعر المطلوب، الوزن النهائي، موقع التحميل، موقع التنزيل، موعد التحميل وطريقة الدفع."
    )


def _whatsapp_link(phone, message):
    """Create a click-to-chat URL without sending anything through an API."""
    normalized = _valid_phone(phone)
    if not normalized:
        return ""
    return "https://wa.me/" + normalized.lstrip("+") + "?text=" + urllib.parse.quote(message)


async def contact_owner(shipment_id):
    item = one("""SELECT s.*,n.owner_phone,n.status negotiation_status FROM shipments s
        JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?""", (shipment_id,))
    if not item or not item.get("owner_phone"):
        execute("UPDATE freight_negotiations SET status='missing_owner_phone',last_error=?,updated_at=? WHERE shipment_id=?",
                ("رقم صاحب الشحنة غير متوفر", utcnow(), shipment_id))
        return
    missing = _shipment_requirements(item)
    if missing:
        execute("UPDATE freight_negotiations SET status='needs_manual_data',last_error=?,updated_at=? WHERE shipment_id=?",
                ("أكمل البيانات أولًا: " + "، ".join(missing), utcnow(), shipment_id))
        return
    if os.getenv("FREIGHT_AUTO_OWNER_CONTACT", "0") != "1":
        execute("UPDATE freight_negotiations SET status='contact_ready',updated_at=? WHERE shipment_id=?", (utcnow(), shipment_id))
        return
    channel = os.getenv("FREIGHT_OWNER_CONTACT_CHANNEL", "retell").lower()
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
                response = await client.post("https://api.retellai.com/v2/create-phone-call",
                    headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}, json=payload)
            if response.status_code >= 300:
                raise RuntimeError("Retell HTTP " + str(response.status_code))
            call_id = str((response.json() or {}).get("call_id") or "")
            execute("""UPDATE freight_negotiations SET status='awaiting_owner',contact_channel='retell',
                provider_call_id=?,contacted_at=?,last_error=NULL,updated_at=? WHERE shipment_id=?""",
                (call_id, utcnow(), utcnow(), shipment_id))
            return
        result = await send_text_message(item["owner_phone"], _owner_message(item))
        messages = result.get("messages") or []
        provider_id = str(messages[0].get("id") or "") if messages else ""
        execute("""UPDATE freight_negotiations SET status='awaiting_owner',contact_channel='whatsapp',
            provider_message_id=?,contacted_at=?,last_error=NULL,updated_at=? WHERE shipment_id=?""",
            (provider_id, utcnow(), utcnow(), shipment_id))
    except Exception as exc:
        execute("UPDATE freight_negotiations SET status='contact_failed',last_error=?,updated_at=? WHERE shipment_id=?",
                (str(exc)[:500], utcnow(), shipment_id))


def sync_retell_negotiation(metadata, custom, summary=""):
    try:
        shipment_id = int(metadata.get("shipment_id"))
    except Exception:
        return False
    if not metadata.get("freight_negotiation"):
        return False
    def number(value):
        match = re.search(r"\d+(?:[.,]\d+)?", str(value or "").replace(",", ""))
        return float(match.group(0)) if match else None
    agreed = number(custom.get("agreed_owner_price") or custom.get("agreed_price"))
    asking = number(custom.get("asking_price"))
    weight = number(custom.get("weight_tons") or custom.get("weight"))
    if agreed and agreed > 150:
        now = utcnow(); driver_price = agreed - 150
        execute("""UPDATE freight_negotiations SET status='owner_agreed',asking_price=COALESCE(?,asking_price),
            agreed_owner_price=?,driver_offer_price=?,weight_tons=COALESCE(?,weight_tons),
            unloading_location=COALESCE(NULLIF(?,''),unloading_location),payment_method=COALESCE(NULLIF(?,''),payment_method),
            notes=COALESCE(NULLIF(?,''),notes),agreed_at=?,updated_at=?,last_error=NULL WHERE shipment_id=?""",
            (asking, agreed, driver_price, weight, str(custom.get("unloading_location") or "")[:300],
             str(custom.get("payment_method") or "")[:200], summary[:3000], now, now, shipment_id))
        execute("UPDATE shipments SET revenue=?,cost=?,updated_at=? WHERE id=?", (agreed, driver_price, now, shipment_id))
        try:
            prepare_driver_offer(shipment_id, None)
        except HTTPException as exc:
            execute("UPDATE freight_negotiations SET last_error=?,updated_at=? WHERE shipment_id=?", (str(exc.detail)[:500], utcnow(), shipment_id))
        return True
    execute("UPDATE freight_negotiations SET status='needs_review',notes=COALESCE(NULLIF(?,''),notes),updated_at=? WHERE shipment_id=?",
            (summary[:3000], utcnow(), shipment_id))
    return True


def _valid_phone(value):
    phone = re.sub(r"[\s\-()]", "", str(value or ""))
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    return phone if re.fullmatch(r"\+[1-9]\d{7,14}", phone) else ""


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
        if not item.get("weight_tons") or float(item["weight_tons"]) <= 0:
            missing.append("الوزن")
        if not _usable_text(item.get("unloading_location") or item.get("destination")):
            missing.append("مكان التنزيل")
        if not _usable_text(item.get("payment_method")):
            missing.append("طريقة الدفع")
    return missing


def _require_complete(item, agreement=False):
    missing = _shipment_requirements(item, agreement)
    if missing:
        raise HTTPException(409, "أكمل البيانات أولًا: " + "، ".join(missing))


def prepare_driver_offer(shipment_id, user_id):
    item = one("""SELECT s.*,n.agreed_owner_price,n.driver_offer_price,n.weight_tons,n.payment_method,
        n.unloading_location FROM shipments s JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?""", (shipment_id,))
    if not item or item.get("agreed_owner_price") is None:
        raise HTTPException(409, "يجب تسجيل اتفاق صاحب الشحنة أولًا")
    _require_complete(item, agreement=True)
    existing = one("SELECT id FROM driver_broadcasts WHERE shipment_id=? AND status NOT IN ('cancelled','rejected') ORDER BY id DESC LIMIT 1", (shipment_id,))
    if existing:
        return existing["id"]
    drivers = rows("""SELECT id,driver_name,whatsapp_phone FROM drivers
        WHERE offer_consent=1 AND availability<>'غير متاح' AND whatsapp_phone IS NOT NULL ORDER BY id""")
    valid, seen = [], set()
    for driver in drivers:
        phone = _valid_phone(driver.get("whatsapp_phone"))
        if phone and phone not in seen:
            seen.add(phone); valid.append((driver, phone))
    if not valid:
        raise HTTPException(409, "لا يوجد سائقون متاحون لديهم موافقة استقبال العروض")
    price = float(item["driver_offer_price"])
    message = (
        f"عرض حمولة من آفاق طويق — {item['reference']}\n"
        f"المسار: {item.get('origin') or '—'} → {item.get('destination') or '—'}\n"
        f"الوزن: {item.get('weight_tons') or 'غير محدد'} طن\n"
        f"سعر السائق: {price:,.0f} ريال\n"
        f"التنزيل: {item.get('unloading_location') or item.get('destination') or 'يحدد لاحقًا'}\n"
        f"الدفع: {item.get('payment_method') or 'يحدد لاحقًا'}\n"
        "للرغبة اكتب: موافق " + item["reference"]
    )
    now = utcnow()
    bid = execute("""INSERT INTO driver_broadcasts(raw_command,message,status,recipient_count,created_by,created_at,updated_at,shipment_id)
        VALUES(?,?,?,?,?,?,?,?)""", ("عرض آلي للشحنة " + item["reference"], message, "draft", len(valid), user_id, now, now, shipment_id))
    for driver, phone in valid:
        execute("""INSERT INTO driver_broadcast_recipients(broadcast_id,driver_id,driver_name,phone,status)
            VALUES(?,?,?,?,?) ON CONFLICT(broadcast_id,phone) DO NOTHING""", (bid, driver["id"], driver["driver_name"], phone, "pending"))
    execute("UPDATE freight_negotiations SET status='driver_offer_pending_approval',updated_at=? WHERE shipment_id=?", (now, shipment_id))
    log(user_id, "freight_driver_offer_prepared", "shipment", shipment_id, f"Single-confirmation offer prepared for {len(valid)} drivers")
    return bid


def accept_driver_reply(phone, text):
    normalized = _valid_phone(phone)
    match = re.search(r"NQ-\d+", (text or "").upper())
    if not normalized or not match or not re.search(r"(?:موافق|اقبل|جاهز|نعم)", text or "", re.I):
        return False
    reference = match.group(0)
    with db() as c:
        row = c.execute("""SELECT r.id recipient_id,r.driver_id,b.id broadcast_id,b.shipment_id,b.accepted_driver_id
            FROM driver_broadcast_recipients r JOIN driver_broadcasts b ON b.id=r.broadcast_id
            JOIN shipments s ON s.id=b.shipment_id
            WHERE r.phone=%s AND s.reference=%s AND b.status IN ('sending','completed','completed_with_errors','awaiting_driver')
            ORDER BY b.id DESC LIMIT 1 FOR UPDATE""", (normalized, reference)).fetchone()
        if not row or row["accepted_driver_id"]:
            return False
        now = utcnow()
        c.execute("UPDATE driver_broadcasts SET status='driver_accepted',accepted_driver_id=%s,accepted_at=%s,updated_at=%s WHERE id=%s AND accepted_driver_id IS NULL",
                  (row["driver_id"], now, now, row["broadcast_id"]))
        c.execute("UPDATE driver_broadcast_recipients SET status=CASE WHEN id=%s THEN 'accepted' ELSE 'closed' END,replied_at=CASE WHEN id=%s THEN %s ELSE replied_at END WHERE broadcast_id=%s",
                  (row["recipient_id"], row["recipient_id"], now, row["broadcast_id"]))
        c.execute("UPDATE freight_negotiations SET status='driver_accepted',updated_at=%s WHERE shipment_id=%s", (now, row["shipment_id"]))
        c.execute("UPDATE shipments SET status='driver_assigned',updated_at=%s WHERE id=%s", (now, row["shipment_id"]))
        c.execute("UPDATE shipment_operations SET stage='driver_assigned',driver_name=(SELECT driver_name FROM drivers WHERE id=%s),driver_phone=(SELECT whatsapp_phone FROM drivers WHERE id=%s),updated_at=%s WHERE shipment_id=%s",
                  (row["driver_id"], row["driver_id"], now, row["shipment_id"]))
    return True


@router.get("/freight-workflow", response_class=HTMLResponse)
def workflow_page(request: Request):
    session(request)
    items = rows("""SELECT s.id,s.reference,s.origin,s.destination,s.status,n.owner_phone,n.status negotiation_status,
        n.agreed_owner_price,n.driver_offer_price,b.status broadcast_status,d.driver_name
        FROM shipments s JOIN freight_negotiations n ON n.shipment_id=s.id
        LEFT JOIN LATERAL (SELECT * FROM driver_broadcasts x WHERE x.shipment_id=s.id ORDER BY x.id DESC LIMIT 1) b ON TRUE
        LEFT JOIN drivers d ON d.id=b.accepted_driver_id ORDER BY s.id DESC""")
    table = "".join(f"<tr><td><a href='/freight-workflow/{x['id']}'>{esc(x['reference'])}</a></td><td>{esc(x['origin'])} → {esc(x['destination'])}</td><td dir=ltr>{esc(x['owner_phone'])}</td><td>{esc(x['negotiation_status'])}</td><td>{esc(x['agreed_owner_price'])}</td><td>{esc(x['driver_offer_price'])}</td><td>{esc(x.get('broadcast_status'))}</td><td>{esc(x.get('driver_name'))}</td></tr>" for x in items)
    return HTMLResponse(_page("إدارة عروض الشحن", f"<h1>إدارة عروض الشحن</h1><p><a href='/dashboard'>الرئيسية</a></p><div class=card><table><tr><th>الشحنة</th><th>المسار</th><th>صاحب الشحنة</th><th>التفاوض</th><th>اتفاق المالك</th><th>عرض السائق</th><th>الإرسال</th><th>السائق المقبول</th></tr>{table or '<tr><td colspan=8>لا توجد شحنات.</td></tr>'}</table></div>"))


def _page(title, body):
    return f"""<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{esc(title)}</title><style>body{{font-family:Arial;background:#07131f;color:#eef6fb;margin:0;padding:24px}}a{{color:#86efac}}.card{{max-width:1100px;margin:14px auto;background:#102536;padding:20px;border-radius:16px;overflow:auto}}input,textarea,button{{width:100%;padding:11px;margin:6px 0;box-sizing:border-box;border-radius:8px;border:1px solid #36586e}}button{{background:#ff7900;color:white;font-weight:bold}}.manual{{display:block;padding:12px;margin:10px 0;border-radius:9px;background:#22c55e;color:#04130a;text-align:center;text-decoration:none;font-weight:bold}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #28475d;text-align:right}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}}.warn{{color:#fde68a}}.good{{color:#86efac}}hr{{border:0;border-top:1px solid #36586e;margin:20px 0}}</style>{body}</html>"""


@router.get("/freight-workflow/{shipment_id}", response_class=HTMLResponse)
def workflow_detail(shipment_id: int, request: Request):
    current = session(request)
    item = one("""SELECT s.*,n.id negotiation_id,n.owner_phone,n.status negotiation_status,n.asking_price,
        n.agreed_owner_price,n.driver_offer_price,n.weight_tons,n.unloading_location,n.payment_method,n.notes,n.last_error
        FROM shipments s JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?""", (shipment_id,))
    if not item: raise HTTPException(404)
    broadcast = one("SELECT * FROM driver_broadcasts WHERE shipment_id=? ORDER BY id DESC LIMIT 1", (shipment_id,))
    missing_contact = _shipment_requirements(item)
    readiness = ("<p class=good>بيانات المسار والتواصل مكتملة.</p>" if not missing_contact else
                 "<p class=warn>يلزم استكمال: " + esc("، ".join(missing_contact)) + "</p>")
    owner_link = _whatsapp_link(item.get("owner_phone"), _owner_message(item)) if not missing_contact else ""
    manual_contact = (f"<a class=manual href='{esc(owner_link)}' target='_blank' rel='noopener'>فتح واتساب لصاحب الشحنة برسالة جاهزة</a>"
                      "<p class=warn>هذا الزر يفتح المحادثة فقط؛ راجع الرسالة واضغط إرسال داخل واتساب بنفسك.</p>"
                      if owner_link else "")
    controls = f"""<h2>الاستخراج والتصحيح اليدوي</h2>
    <p>راجع نتيجة OCR وصحح أي حقل قبل بدء التواصل.</p>
    <form method=post action='/freight-workflow/{shipment_id}/manual-data'><input type=hidden name=csrf value='{esc(current['csrf'])}'><div class=grid>
    <input name=origin required placeholder='مدينة أو موقع التحميل' value='{esc(item.get('origin'))}'>
    <input name=destination required placeholder='مدينة أو موقع التنزيل' value='{esc(item.get('destination'))}'>
    <input name=owner_phone required dir=ltr placeholder='+9665xxxxxxxx' value='{esc(item.get('owner_phone'))}'>
    <input name=weight_tons type=number min=.01 step=.01 placeholder='الوزن بالطن' value='{esc(item.get('weight_tons'))}'>
    </div><button>حفظ البيانات المصححة يدويًا</button></form>{readiness}{manual_contact}<hr>
    <form method=post action='/freight-workflow/{shipment_id}/contact-owner'><input type=hidden name=csrf value='{esc(current['csrf'])}'><button>التواصل مع صاحب الشحنة الآن</button></form>
    <form method=post action='/freight-workflow/{shipment_id}/agreement'><input type=hidden name=csrf value='{esc(current['csrf'])}'><div class=grid><input name=asking_price type=number step=.01 placeholder='السعر المطلوب' value='{esc(item.get('asking_price'))}'><input name=agreed_owner_price type=number step=.01 required placeholder='السعر المتفق مع صاحب الشحنة' value='{esc(item.get('agreed_owner_price'))}'><input name=weight_tons type=number step=.01 placeholder='الوزن طن' value='{esc(item.get('weight_tons'))}'><input name=unloading_location placeholder='مكان التنزيل' value='{esc(item.get('unloading_location'))}'><input name=payment_method placeholder='طريقة الدفع' value='{esc(item.get('payment_method'))}'></div><textarea name=notes placeholder='ملخص التفاوض'>{esc(item.get('notes'))}</textarea><button>حفظ الاتفاق وتجهيز عرض السائقين ناقص 150 ريال</button></form>"""
    if broadcast:
        controls += f"<p><a href='/commands/broadcast/{broadcast['id']}'>مراجعة العرض وتأكيد الإرسال الجماعي مرة واحدة</a> — الحالة: {esc(broadcast['status'])}</p>"
    return HTMLResponse(_page(item["reference"], f"<div class=card><h1>{esc(item['reference'])}</h1><p>{esc(item['origin'])} → {esc(item['destination'])}</p><p>صاحب الشحنة: <span dir=ltr>{esc(item['owner_phone'])}</span> | الحالة: {esc(item['negotiation_status'])}</p><p class=warn>{esc(item.get('last_error'))}</p>{controls}</div>"))


@router.post("/freight-workflow/{shipment_id}/manual-data")
async def save_manual_data(shipment_id: int, request: Request):
    current = session(request); data = form(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    item = one("""SELECT s.id,n.naqliat_load_id FROM shipments s
        JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?""", (shipment_id,))
    if not item: raise HTTPException(404, "الشحنة غير موجودة")
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
    if weight is not None and weight <= 0:
        raise HTTPException(400, "الوزن يجب أن يكون أكبر من صفر")
    now = utcnow()
    with db() as c:
        c.execute("UPDATE shipments SET origin=%s,destination=%s,updated_at=%s WHERE id=%s",
                  (origin, destination, now, shipment_id))
        c.execute("""UPDATE freight_negotiations SET owner_phone=%s,weight_tons=%s,status='ready_to_contact',
            last_error=NULL,updated_at=%s WHERE shipment_id=%s""", (phone, weight, now, shipment_id))
        if item.get("naqliat_load_id"):
            c.execute("UPDATE naqliat_loads SET origin=%s,destination=%s,owner_phone=%s,weight_tons=%s WHERE id=%s",
                      (origin, destination, phone, weight, item["naqliat_load_id"]))
    log(current["user_id"], "freight_manual_data_updated", "shipment", shipment_id,
        origin + " → " + destination)
    return RedirectResponse(f"/freight-workflow/{shipment_id}", 303)


@router.post("/freight-workflow/{shipment_id}/contact-owner")
async def contact_owner_now(shipment_id: int, request: Request, background_tasks: BackgroundTasks):
    current = session(request); data = form(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    item = one("""SELECT s.origin,s.destination,n.owner_phone FROM shipments s
        JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?""", (shipment_id,))
    if not item: raise HTTPException(404, "الشحنة غير موجودة")
    _require_complete(item)
    background_tasks.add_task(contact_owner, shipment_id)
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
    if agreed <= 150: raise HTTPException(400, "سعر صاحب الشحنة يجب أن يكون أكبر من 150 ريال")
    item = one("""SELECT s.origin,s.destination,n.owner_phone FROM shipments s
        JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=?""", (shipment_id,))
    if not item: raise HTTPException(404, "الشحنة غير موجودة")
    item.update({"weight_tons": weight, "unloading_location": data.get("unloading_location"),
                 "payment_method": data.get("payment_method")})
    _require_complete(item, agreement=True)
    driver_price = agreed - 150
    now = utcnow()
    execute("""UPDATE freight_negotiations SET status='owner_agreed',asking_price=?,agreed_owner_price=?,driver_offer_price=?,
        weight_tons=?,unloading_location=?,payment_method=?,notes=?,agreed_at=?,updated_at=?,last_error=NULL WHERE shipment_id=?""",
        (asking, agreed, driver_price, weight, data.get("unloading_location"), data.get("payment_method"), data.get("notes"), now, now, shipment_id))
    execute("UPDATE shipments SET revenue=?,cost=?,updated_at=? WHERE id=?", (agreed, driver_price, now, shipment_id))
    bid = prepare_driver_offer(shipment_id, current["user_id"])
    return RedirectResponse(f"/commands/broadcast/{bid}", 303)


@router.get("/api/v7/freight-workflow")
def workflow_api(request: Request):
    session(request)
    return {"owner_auto_contact_enabled": os.getenv("FREIGHT_AUTO_OWNER_CONTACT", "0") == "1",
            "driver_margin_sar": 150,
            "items": rows("SELECT * FROM freight_negotiations ORDER BY id DESC LIMIT 200")}
