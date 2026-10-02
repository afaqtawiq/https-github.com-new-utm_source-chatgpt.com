import html
import json
import os
import re
import urllib.parse

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.storage import db, execute, get_session, log, one, rows, utcnow
from app.discovery import run_discovery_cycle
from app.data_import import _phone
from app.whatsapp_integration import send_text_message
from app.zernio_whatsapp import WhatsAppBlocked, WhatsAppPreflightBlocked, transport_batch, dispatch_guard
from app.transport_test import test_broadcast_context
from app.driver_offer import driver_phone, offer_message, preview_plan, require_valid_audience, require_unattempted

router = APIRouter()


def _init_storage():
    execute("""CREATE TABLE IF NOT EXISTS command_actions(
        id BIGSERIAL PRIMARY KEY,
        raw_command TEXT NOT NULL,
        action_type TEXT NOT NULL,
        target_name TEXT,
        contact_id BIGINT REFERENCES sales_contacts(id) ON DELETE SET NULL,
        opportunity_id BIGINT REFERENCES opportunities(id) ON DELETE SET NULL,
        recipient TEXT,
        content TEXT,
        status TEXT NOT NULL DEFAULT 'draft',
        parsed_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by BIGINT,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )""")
    execute("""CREATE TABLE IF NOT EXISTS driver_broadcasts(
        id BIGSERIAL PRIMARY KEY, raw_command TEXT NOT NULL, message TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft', recipient_count INTEGER NOT NULL DEFAULT 0,
        sent_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0,
        created_by BIGINT, confirmed_by BIGINT, created_at TIMESTAMPTZ NOT NULL,
        confirmed_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL
    )""")
    execute("ALTER TABLE driver_broadcasts ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT FALSE")
    execute("ALTER TABLE driver_broadcasts ADD COLUMN IF NOT EXISTS test_approved_by BIGINT")
    execute("ALTER TABLE driver_broadcasts ADD COLUMN IF NOT EXISTS test_approved_at TIMESTAMPTZ")
    execute("ALTER TABLE driver_broadcasts ADD COLUMN IF NOT EXISTS test_preview_digest TEXT")
    execute("""CREATE TABLE IF NOT EXISTS driver_broadcast_recipients(
        id BIGSERIAL PRIMARY KEY,
        broadcast_id BIGINT NOT NULL REFERENCES driver_broadcasts(id) ON DELETE CASCADE,
        driver_id BIGINT REFERENCES drivers(id) ON DELETE SET NULL,
        driver_name TEXT, phone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        provider_message_id TEXT, last_error TEXT, sent_at TIMESTAMPTZ,
        UNIQUE(broadcast_id,phone)
    )""")
    execute("ALTER TABLE driver_broadcast_recipients ADD COLUMN IF NOT EXISTS provider_account_id TEXT")
    execute("ALTER TABLE driver_broadcast_recipients ADD COLUMN IF NOT EXISTS send_phase TEXT")
    execute("ALTER TABLE driver_broadcast_recipients ADD COLUMN IF NOT EXISTS preflight_diagnostic TEXT")
    execute("ALTER TABLE driver_broadcast_recipients ADD COLUMN IF NOT EXISTS post_attempted_at TIMESTAMPTZ")
    execute("ALTER TABLE driver_broadcast_recipients ADD COLUMN IF NOT EXISTS provider_response_status INTEGER")



_init_storage()


def e(value): return html.escape(str(value or ""))


def form(raw):
    return {key: value[0] for key, value in urllib.parse.parse_qs(raw.decode(), keep_blank_values=True).items()}


def session(request):
    current = get_session(request.cookies.get("gla_session"))
    if not current: raise HTTPException(401)
    return current


ARABIC_DIACRITICS = re.compile(r"[\u064b-\u065f\u0670]")


def normalize_text(value):
    value = ARABIC_DIACRITICS.sub("", (value or "").strip())
    value = value.replace("إ", "ا").replace("أ", "ا").replace("آ", "ا")
    return re.sub(r"\s+", " ", value)


def parse_command(raw):
    text = normalize_text(raw).strip(" .،؟!")
    text = re.sub(r"^(?:افاق(?: طويق)?)\s+", "", text)
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    if any(word in text for word in ("سائق", "السائق", "سايق", "السايق")):
        phone_match = re.search(r"(?:\+?966|00966|0)?5[0-9\s()\-]{8,13}", text)
        add_intent = any(word in text for word in (
            "اضف", "سجل", "احفظ", "اسم السائق", "اسم السايق", "بيانات السائق", "بيانات السايق"
        ))
        if phone_match and add_intent:
            phone = phone_match.group(0).strip()
            prefix = text[:phone_match.start()]
            name = re.sub(
                r"^(?:اضف|سجل|احفظ)?\s*(?:اسم\s+)?(?:السائق|سائق|السايق|سايق)\s*",
                "", prefix,
            )
            name = re.sub(
                r"\s*(?:و?رقم\s+جواله|و?رقم\s+جوال|ورقمه|ورقم|رقمه|رقم|و?جواله|جوال|هاتفه|هاتف)\s*$",
                "", name,
            ).strip(" :،,.")
            vehicle_match = re.search(r"(?:ومركبته|مركبته|نوع المركبة|المركبة)\s+(.+)$", text[phone_match.end():])
            if name:
                return {
                    "action_type": "add_driver",
                    "target": name,
                    "phone": phone,
                    "vehicle_type": (vehicle_match.group(1) if vehicle_match else "غير محدد").strip(),
                    "content": "",
                }
    broadcast = re.match(r"^(?:ارسل|ابعث)\s+(?:رسالة\s+)?(?:واتساب|واتس)?\s*(?:الى|ل)?\s*(?:جميع|كل)\s+السائقين\s*(.*)$", text, flags=re.IGNORECASE)
    if broadcast:
        content = re.sub(r"^(?:بخصوص|محتوى|وقل|برسالة)\s+", "", broadcast.group(1).strip())
        return {"action_type": "driver_broadcast", "target": "جميع السائقين", "content": content}
    patterns = (
        ("call", r"^(?:اتصل|اتصال|كلم)\s+(?:على|ب)?\s*(.+)$"),
        ("whatsapp", r"^(?:ارسل|ابعث)\s+(?:رسالة\s+)?(?:واتساب|واتس)\s+(?:الى|ل)?\s*(.+)$"),
        ("email", r"^(?:ارسل|ابعث)\s+(?:رسالة\s+)?(?:ايميل|ايميلًا|بريد(?:ا\s+الكترونيا)?)\s+(?:الى|ل)?\s*(.+)$"),
    )
    for action_type, pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            remainder = match.group(1).strip()
            parts = re.split(r"\s+(?:وقل|وقولي|برسالة|بخصوص|محتوى)\s+", remainder, maxsplit=1)
            return {"action_type": action_type, "target": parts[0].strip(" ،,."), "content": parts[1].strip() if len(parts) > 1 else ""}
    if any(phrase in text for phrase in (
        "شغل البحث", "شغل اكتشاف الفرص", "ابحث عن فرص", "اكتشف فرص",
        "حدث الفرص", "نفذ دورة البحث", "تعامل مع عشر فرص", "تعامل مع 10 فرص"
    )):
        return {"action_type": "run_discovery", "target": "محرك اكتشاف الفرص", "content": ""}
    contact_request = re.match(
        r"^(?:تواصل|راسل)\s+(?:مع\s+)?(?:العميل\s+)?(.+?)(?:\s+(?:بخصوص|وقل|محتوى)\s+(.+))?$",
        text, flags=re.IGNORECASE,
    )
    if contact_request:
        return {
            "action_type": "auto_contact",
            "target": contact_request.group(1).strip(" ،,."),
            "content": (contact_request.group(2) or "").strip(),
        }
    navigation = {
        "الرئيسية": "/dashboard", "افتح الرئيسية": "/dashboard", "اعرض الرئيسية": "/dashboard",
        "افتح العملاء": "/accounts", "اعرض العملاء": "/accounts", "العملاء": "/accounts",
        "افتح السائقين": "/drivers", "اعرض السائقين": "/drivers", "السائقين": "/drivers",
        "افتح الفرص": "/opportunities", "اعرض الفرص": "/opportunities", "الفرص": "/opportunities",
        "افتح العشر فرص": "/opportunities", "اعرض العشر فرص": "/opportunities",
        "افتح الموافقات": "/approvals", "اعرض الموافقات": "/approvals", "الموافقات": "/approvals",
        "افتح الشحنات": "/shipments", "اعرض الشحنات": "/shipments", "الشحنات": "/shipments",
        "افتح وكلاء الملاحة": "/shipping-agents", "اعرض وكلاء الملاحة": "/shipping-agents",
        "افتح سابر": "/saber", "اعرض سابر": "/saber",
        "افتح المحتوى": "/content-center", "افتح صناعة المحتوى": "/content-center",
        "افتح اكتشاف الفرص": "/discovery", "اعرض اكتشاف الفرص": "/discovery",
        "افتح مساعد المبيعات": "/sales-copilot", "اعرض مساعد المبيعات": "/sales-copilot",
        "افتح مسار المبيعات": "/pipeline", "اعرض مسار المبيعات": "/pipeline",
        "افتح السجل": "/activity", "اعرض السجل": "/activity",
    }
    if text in navigation:
        return {"action_type": "navigate", "target": text, "url": navigation[text], "content": ""}
    return {"action_type": "unknown", "target": "", "content": ""}

def find_contact(target):
    needle = "%" + normalize_text(target) + "%"
    matches = rows("""SELECT c.*,o.company_name,o.stage FROM sales_contacts c
        JOIN opportunities o ON o.id=c.opportunity_id
        WHERE LOWER(REPLACE(REPLACE(REPLACE(COALESCE(c.name,''),'إ','ا'),'أ','ا'),'آ','ا')) LIKE LOWER(?)
           OR LOWER(REPLACE(REPLACE(REPLACE(COALESCE(o.company_name,''),'إ','ا'),'أ','ا'),'آ','ا')) LIKE LOWER(?)
        ORDER BY c.verified DESC,c.updated_at DESC LIMIT 6""", (needle, needle))
    if matches:
        return matches
    registered = rows("""SELECT 'account' source_kind,id,name company_name,
               COALESCE(phone,'') phone,COALESCE(email,'') email
        FROM accounts WHERE name ILIKE ?
        UNION ALL
        SELECT 'directory' source_kind,id,company_name,
               COALESCE(phone,'') phone,COALESCE(email,'') email
        FROM customer_directory WHERE company_name ILIKE ?
        LIMIT 6""", (needle, needle))
    materialized = []
    for customer in registered:
        source_url = f"internal://customer/{customer['source_kind']}/{customer['id']}"
        opportunity = one("SELECT * FROM opportunities WHERE source_url=? ORDER BY id LIMIT 1", (source_url,))
        if not opportunity:
            now = utcnow()
            opportunity_id = execute("""INSERT INTO opportunities(
                company_name,source_url,signal,score,stage,estimated_value,currency,owner,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                customer["company_name"], source_url, "طلب تواصل مباشر من مساعد الأوامر",
                65, "qualified", 0, "SAR", "مساعد الأوامر", now, now,
            ))
            opportunity = one("SELECT * FROM opportunities WHERE id=?", (opportunity_id,))
        contact = one("""SELECT * FROM sales_contacts
            WHERE opportunity_id=? AND (COALESCE(phone,'')=? OR COALESCE(email,'')=?)
            ORDER BY id LIMIT 1""", (
                opportunity["id"], customer["phone"], customer["email"],
            ))
        if not contact:
            now = utcnow()
            contact_id = execute("""INSERT INTO sales_contacts(
                opportunity_id,name,email,phone,source_url,verified,notes,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""", (
                opportunity["id"], customer["company_name"], customer["email"], customer["phone"],
                source_url, 0, "أُنشئت من سجل العميل عند طلب التواصل", now, now,
            ))
            contact = one("SELECT * FROM sales_contacts WHERE id=?", (contact_id,))
        contact["company_name"] = opportunity["company_name"]
        contact["stage"] = opportunity["stage"]
        materialized.append(contact)
    return materialized

def action_label(kind):
    return {"call": "مكالمة", "whatsapp": "واتساب", "email": "بريد إلكتروني", "auto_contact": "تواصل مع عميل", "add_driver": "إضافة سائق", "driver_broadcast": "واتساب جماعي للسائقين"}.get(kind, kind)


@router.get("/commands", response_class=HTMLResponse)
def commands_page(request: Request):
    current = get_session(request.cookies.get("gla_session"))
    if not current:
        return RedirectResponse("/login", 303)
    items = rows("""SELECT a.*,c.name contact_name,o.company_name FROM command_actions a
        LEFT JOIN sales_contacts c ON c.id=a.contact_id
        LEFT JOIN opportunities o ON o.id=a.opportunity_id ORDER BY a.id DESC LIMIT 50""")
    item_rows = "".join(f"""<tr><td>{x['id']}</td><td>{e(action_label(x['action_type']))}</td>
        <td>{e(x.get('contact_name') or x.get('target_name'))}</td><td>{e(x.get('company_name'))}</td>
        <td dir=ltr>{e(x.get('recipient'))}</td><td>{e(x['status'])}</td></tr>""" for x in items)
    return HTMLResponse(f"""<!doctype html><html lang=ar dir=rtl><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>مساعد الأوامر</title>
<style>body{{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}}.w{{max-width:1100px;margin:auto;padding:24px}}.card{{background:#102536;border:1px solid #28475d;border-radius:18px;padding:20px;margin:14px 0}}textarea{{width:100%;min-height:120px;box-sizing:border-box;padding:14px;border-radius:12px;border:1px solid #36586e;background:#081925;color:white;font-size:18px}}button,.btn{{border:0;border-radius:10px;padding:12px 16px;margin:7px 3px;background:#22c55e;color:#04130a;font-weight:bold;cursor:pointer;text-decoration:none;display:inline-block}}#mic{{background:#2563eb;color:white}}#mic.listening{{background:#ef4444}}.muted{{color:#aac0cf}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #28475d;text-align:right}}.scroll{{overflow:auto}}.examples{{line-height:2}}</style>
<div class=w><a class=btn href=/dashboard>الرئيسية</a><h1>مساعد الأوامر الصوتية والكتابية</h1>
<div class=card><p class=muted>قل الأمر أو اكتبه. التنقل ينفذ مباشرة، أما الاتصال أو واتساب أو البريد فينشئ مسودة للمراجعة ولا يرسل شيئًا تلقائيًا.</p>
<form method=post action=/commands><input type=hidden name=csrf value="{e(current['csrf'])}"><textarea id=command name=command required placeholder="مثال: أرسل واتساب إلى أحمد بخصوص عرض النقل"></textarea><button type=button id=mic>🎙 بدء الاستماع</button><button type=submit>تنفيذ الأمر</button><div id=status class=muted></div></form></div>
<div class="card examples"><b>أمثلة:</b><br>«اتصل على محمد»<br>«أرسل واتساب إلى شركة النور بخصوص عرض النقل»<br>«أرسل لجميع السائقين شحنة من الرياض إلى جدة»<br>«أرسل بريدًا إلى أحمد بخصوص خدمات التخليص»<br>«افتح السائقين»<br>«شغّل البحث عن فرص»<br>«اعرض الشحنات»<br>«افتح وكلاء الملاحة»<br>«أضف السائق محمد ورقمه 0501234567»<br>«تواصل مع العميل شركة النور بخصوص خدمات التخليص»</div>
<div class="card scroll"><h2>المسودات الأخيرة</h2><table><tr><th>#</th><th>الأمر</th><th>الجهة</th><th>الشركة</th><th>المستلم</th><th>الحالة</th></tr>{item_rows or '<tr><td colspan=6>لا توجد أوامر بعد.</td></tr>'}</table></div></div>
<script>const mic=document.querySelector('#mic'),field=document.querySelector('#command'),status=document.querySelector('#status');const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SpeechRecognition){{mic.disabled=true;status.textContent='التعرف الصوتي غير متاح في هذا المتصفح؛ استخدم Chrome أو اكتب الأمر.'}}else{{const recognition=new SpeechRecognition();recognition.lang='ar-SA';recognition.interimResults=false;recognition.continuous=false;mic.onclick=()=>{{status.textContent='أستمع الآن...';mic.classList.add('listening');recognition.start()}};recognition.onresult=event=>{{field.value=event.results[0][0].transcript;status.textContent='تم التقاط الأمر، جارٍ تنفيذه...';setTimeout(()=>field.form.requestSubmit(),650)}};recognition.onerror=event=>{{status.textContent='تعذر التقاط الصوت: '+event.error}};recognition.onend=()=>mic.classList.remove('listening')}}</script></html>""")


@router.post("/commands")
async def create_command(request: Request):
    current = get_session(request.cookies.get("gla_session"))
    if not current:
        return RedirectResponse("/login", 303)
    data = form(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    raw = (data.get("command") or "").strip()
    if not raw or len(raw) > 1000: raise HTTPException(400, "Command must contain 1-1000 characters")
    parsed = parse_command(raw)
    if parsed["action_type"] == "navigate":
        log(current["user_id"], "command_navigation", summary=raw[:300])
        return RedirectResponse(parsed["url"], 303)
    if parsed["action_type"] == "run_discovery":
        log(current["user_id"], "command_discovery_started", summary=raw[:300])
        tasks = BackgroundTasks()
        tasks.add_task(run_discovery_cycle)
        response = RedirectResponse("/discovery", 303)
        response.background = tasks
        return response
    if parsed["action_type"] == "unknown":
        return HTMLResponse("<html lang=ar dir=rtl><meta charset=utf-8><body style='font-family:Arial;padding:30px'><h2>لم أفهم الأمر.</h2><p>جرّب: أضف السائق محمد ورقمه 0501234567، تواصل مع العميل شركة النور، شغّل البحث، أو افتح الشحنات.</p><a href=/commands>عودة</a></body></html>", 400)
    if parsed["action_type"] == "add_driver":
        if current.get("role") != "admin":
            raise HTTPException(403, "إضافة السائقين تتطلب صلاحية الإدارة")
        phone = _phone(parsed.get("phone"), "966")
        if not phone:
            raise HTTPException(400, "رقم الجوال غير صالح؛ اذكر رقمًا سعوديًا أو خليجيًا كاملًا")
        existing = one("SELECT id,driver_name FROM drivers WHERE whatsapp_phone=?", (phone,))
        if existing:
            return HTMLResponse(f"<html lang=ar dir=rtl><meta charset=utf-8><body style='font-family:Arial;padding:30px'><h2>السائق مسجل مسبقًا</h2><p>{e(existing['driver_name'])} — <span dir=ltr>{e(phone)}</span></p><a href=/drivers>فتح قائمة السائقين</a></body></html>", 409)
        now = utcnow()
        driver_id = execute("""INSERT INTO drivers(
            driver_name,whatsapp_phone,vehicle_type,capacity,current_city,preferred_routes,
            availability,company_name,offer_consent,consent_date,notes,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,NULL,?,?,?)""", (
            parsed["target"], phone, parsed.get("vehicle_type") or "غير محدد", "", "", "",
            "متاح", "", 1, "أُضيف بواسطة مساعد الأوامر؛ مسجل لاستقبال عروض الحمولات",
            now, now,
        ))
        log(current["user_id"], "command_driver_created", "driver", driver_id, raw[:300])
        return RedirectResponse("/drivers?q=" + urllib.parse.quote(parsed["target"]), 303)
    if parsed["action_type"] == "driver_broadcast":
        message = parsed["content"].strip()
        if not message:
            raise HTTPException(400, "اكتب تفاصيل الرسالة الموجهة للسائقين")
        candidates = rows("""SELECT id,driver_name,whatsapp_phone FROM drivers
            WHERE whatsapp_phone IS NOT NULL ORDER BY id""")
        valid = []
        seen = set()
        for driver in candidates:
            phone = driver_phone(driver.get('whatsapp_phone'))
            if phone and phone not in seen:
                seen.add(phone)
                valid.append((driver, phone))
        if not valid:
            raise HTTPException(409, "لا يوجد سائقون مسجلون بأرقام صالحة")
        now = utcnow()
        broadcast_id = execute("""INSERT INTO driver_broadcasts(raw_command,message,status,recipient_count,created_by,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)""", (raw, message, "draft", len(valid), current["user_id"], now, now))
        for driver, phone in valid:
            execute("""INSERT INTO driver_broadcast_recipients(broadcast_id,driver_id,driver_name,phone,status)
                VALUES(?,?,?,?,?) ON CONFLICT(broadcast_id,phone) DO NOTHING""", (broadcast_id, driver["id"], driver["driver_name"], phone, "pending"))
        log(current["user_id"], "driver_broadcast_draft_created", "driver_broadcast", broadcast_id, f"Prepared for {len(valid)} registered unique drivers; not sent")
        return RedirectResponse(f"/commands/broadcast/{broadcast_id}", 303)
    matches = find_contact(parsed["target"])
    if len(matches) != 1:
        reason = "لم نجد جهة اتصال مطابقة" if not matches else "وجدنا أكثر من جهة مطابقة؛ اكتب الاسم بشكل أدق"
        return HTMLResponse(f"<html lang=ar dir=rtl><meta charset=utf-8><body style='font-family:Arial;padding:30px'><h2>{e(reason)}</h2><p>الهدف: {e(parsed['target'])}</p><a href=/commands>عودة</a></body></html>", 409)
    contact = matches[0]
    auto_selected = parsed["action_type"] == "auto_contact"
    if auto_selected:
        if contact.get("verified") and contact.get("phone"):
            parsed["action_type"] = "whatsapp"
        elif contact.get("email"):
            parsed["action_type"] = "email"
        elif contact.get("phone"):
            parsed["action_type"] = "whatsapp"
            parsed["requires_phone_verification"] = True
        else:
            raise HTTPException(409, "العميل مسجل لكن لا توجد له وسيلة تواصل")
    recipient = contact.get("email") if parsed["action_type"] == "email" else contact.get("phone")
    if not recipient: raise HTTPException(409, "Selected contact has no recipient for this channel")
    if parsed["action_type"] in ("call", "whatsapp") and not contact.get("verified") and not auto_selected:
        raise HTTPException(409, "رقم العميل يحتاج تحقق قبل تجهيز الاتصال المباشر")
    content = parsed["content"] or ("مناقشة احتياج العميل وتحديد الخدمة المناسبة دون تقديم التزام أو سعر نهائي." if parsed["action_type"] == "call" else "مرحبًا، معك فريق آفاق طويق. نرغب في مناقشة احتياجكم اللوجستي وإعداد عرض مناسب بعد تأكيد التفاصيل.")
    now = utcnow()
    action_id = execute("""INSERT INTO command_actions(raw_command,action_type,target_name,contact_id,opportunity_id,recipient,content,status,parsed_payload,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (raw, parsed["action_type"], parsed["target"], contact["id"], contact["opportunity_id"], recipient, content, ("needs_verification" if parsed.get("requires_phone_verification") else "draft"), json.dumps(parsed, ensure_ascii=False), current["user_id"], now, now))
    log(current["user_id"], "command_draft_created", "command_action", action_id, f"{parsed['action_type']} draft prepared; no external action")
    return RedirectResponse(f"/commands/{action_id}", 303)


@router.get("/commands/{action_id}", response_class=HTMLResponse)
def command_review(action_id: int, request: Request):
    session(request)
    action = one("""SELECT a.*,c.name contact_name,o.company_name FROM command_actions a
        LEFT JOIN sales_contacts c ON c.id=a.contact_id LEFT JOIN opportunities o ON o.id=a.opportunity_id WHERE a.id=?""", (action_id,))
    if not action: raise HTTPException(404)
    return HTMLResponse(f"""<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><title>مراجعة الأمر</title><body style="font-family:Arial;background:#07131f;color:#eef6fb;padding:28px"><div style="max-width:760px;margin:auto;background:#102536;padding:24px;border-radius:16px"><h1>تم تجهيز المسودة فقط</h1><p><b>القناة:</b> {e(action_label(action['action_type']))}</p><p><b>الجهة:</b> {e(action.get('contact_name'))} — {e(action.get('company_name'))}</p><p><b>المستلم:</b> <span dir=ltr>{e(action.get('recipient'))}</span></p><p><b>المحتوى/الهدف:</b></p><div style="white-space:pre-wrap;background:#081925;padding:14px;border-radius:10px">{e(action.get('content'))}</div><p style="color:#fde68a">لم تُرسل رسالة ولم تبدأ مكالمة. التنفيذ يحتاج مراجعة وموافقة منفصلة.</p><a style="color:#86efac" href=/commands>العودة إلى مساعد الأوامر</a></div></body></html>""")


@router.get("/api/v7/commands")
def command_api(request: Request):
    session(request)
    return {"automatic_external_actions": False, "supported": ["add_driver", "call", "whatsapp", "auto_contact", "driver_broadcast", "email", "navigate", "run_discovery"], "items": rows("SELECT id,raw_command,action_type,target_name,recipient,status,created_at FROM command_actions ORDER BY id DESC LIMIT 100")}


def _preview_message(connection, campaign):
    if not campaign.get('shipment_id'):
        return campaign['message']
    item = connection.execute("""SELECT s.*,n.agreed_owner_price,n.weight_tons,n.payment_method,
        n.unloading_location,n.loading_port_status FROM shipments s
        JOIN freight_negotiations n ON n.shipment_id=s.id WHERE s.id=%s""", (campaign['shipment_id'],)).fetchone()
    if not item or bool(item.get('is_test')) != bool(campaign.get('is_test')):
        raise HTTPException(409, 'علامة الاختبار لا تطابق الشحنة')
    if item.get('agreed_owner_price') is None or not item.get('weight_tons') or not item.get('payment_method'):
        raise HTTPException(409, 'بيانات العرض غير مكتملة؛ لا يمكن تحديثه أو إرساله')
    return offer_message(item)


def _validate_before_send(connection, campaign):
    recipients = connection.execute('SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=%s ORDER BY id', (campaign['id'],)).fetchall()
    if campaign['status'] == 'draft':
        require_unattempted(campaign, recipients)
    require_valid_audience(campaign, recipients)
    if _preview_message(connection, campaign) != campaign['message']:
        raise HTTPException(409, 'تغيرت تفاصيل التحميل؛ حدّث معاينة المسودة واعتمد النص الحالي قبل الإرسال')


@router.post('/commands/broadcast/{broadcast_id}/refresh-preview')
async def refresh_broadcast_preview(broadcast_id: int, request: Request):
    current = session(request)
    data = form(await request.body())
    if current.get('role') != 'admin' or data.get('csrf') != current['csrf']:
        raise HTTPException(403)
    if data.get('refresh_confirmed') != 'yes':
        raise HTTPException(400, 'راجع المعاينة والاستبعادات واعتمد تحديث المسودة دون إرسال')
    with db() as c:
        campaign = c.execute('SELECT * FROM driver_broadcasts WHERE id=%s FOR UPDATE', (broadcast_id,)).fetchone()
        if not campaign:
            raise HTTPException(404)
        if not campaign.get('is_test'):
            raise HTTPException(409, 'تحديث المعاينة هذا مخصص لمسودات الاختبار المعلن فقط')
        recipients = c.execute('SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=%s ORDER BY id FOR UPDATE', (broadcast_id,)).fetchall()
        plan = preview_plan(campaign, recipients, _preview_message(c, campaign))
        if data.get('refresh_preview') != plan['digest']:
            raise HTTPException(409, 'تغيرت المعاينة؛ أعد مراجعة المسودة قبل تحديثها')
        if plan['changed']:
            for row in plan['excluded']:
                if row['status'] == 'pending':
                    c.execute("UPDATE driver_broadcast_recipients SET status='excluded',last_error=%s WHERE id=%s AND status='pending'", (row['reason'], row['id']))
            now = utcnow()
            c.execute("""UPDATE driver_broadcasts SET message=%s,recipient_count=%s,
                test_approved_by=NULL,test_approved_at=NULL,test_preview_digest=NULL,
                confirmed_by=NULL,confirmed_at=NULL,updated_at=%s WHERE id=%s""",
                (plan['message'], len(plan['active']), now, broadcast_id))
            if campaign.get('shipment_id'):
                summary = json.dumps({'broadcast_id':broadcast_id, 'eligible_count':len(plan['active']),
                    'excluded':[{'recipient_id':r['id'],'phone':r['phone'],'reason':r['reason']} for r in plan['excluded']],
                    'message_changed':plan['message'] != campaign['message'], 'preview_digest':plan['digest']}, ensure_ascii=False)
                c.execute("""INSERT INTO shipment_events(shipment_id,event_type,summary,stage,happened_at,created_by)
                    VALUES(%s,'driver_preview_refreshed',%s,'driver_offer_pending_approval',%s,%s)""",
                    (campaign['shipment_id'], summary, now, current['user_id']))
    if plan['changed']:
        log(current['user_id'], 'driver_preview_refreshed', 'driver_broadcast', broadcast_id,
            f"{len(plan['active'])} eligible; {len(plan['excluded'])} excluded; approvals cleared; no send")
    return RedirectResponse(f'/commands/broadcast/{broadcast_id}', 303)


@router.get("/commands/broadcast/{broadcast_id}", response_class=HTMLResponse)
def broadcast_review(broadcast_id: int, request: Request):
    current = session(request)
    broadcast = one("SELECT * FROM driver_broadcasts WHERE id=?", (broadcast_id,))
    if not broadcast:
        raise HTTPException(404)
    test_context = test_broadcast_context(broadcast)
    recipients = rows("SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=? ORDER BY id", (broadcast_id,))
    validation, needs_refresh = '', False
    if broadcast['status'] == 'draft':
        try:
            with db() as c:
                plan = preview_plan(broadcast, recipients, _preview_message(c, broadcast))
            needs_refresh = plan['changed'] or not plan['active']
            if not plan['active']:
                validation = '<p>لا يوجد مستلمون صالحون للإرسال في هذه المسودة.</p>'
            if plan['changed'] and not broadcast.get('is_test'):
                validation += '<p>راجع بيانات المسودة قبل الإرسال؛ التحديث المباشر هنا مخصص للاختبار المعلن.</p>'
            if plan['changed'] and broadcast.get('is_test'):
                reasons = ''.join('<li dir=ltr>' + e(r['phone']) + ' — ' + e(r['reason']) + '</li>' for r in plan['excluded'])
                validation = f"""<h2>تحديث معاينة المسودة دون إرسال</h2><p>المستلمون الصالحون بعد التحقق: {len(plan['active'])} · المستبعدون: {len(plan['excluded'])}</p>
                <div class=msg>{e(plan['message'])}</div><ul>{reasons}</ul>
                <form method=post action=/commands/broadcast/{broadcast_id}/refresh-preview>
                <input type=hidden name=csrf value='{e(current['csrf'])}'><input type=hidden name=refresh_preview value='{plan['digest']}'>
                <label><input type=checkbox name=refresh_confirmed value=yes required> راجعت النص والاستبعادات وأعتمد تحديث هذه المسودة دون إرسال</label>
                <button>تحديث المعاينة واستبعاد الأرقام غير الصالحة</button></form>"""
        except HTTPException as exc:
            needs_refresh = True
            validation = '<p>' + e(exc.detail) + '</p>'
    manual_link = (lambda x: 'مستبعد أو ينتظر تحديث المعاينة' if x['status'] == 'excluded' or needs_refresh else 'يتطلب اعتماد الاختبار أدناه' if test_context else
                   f"<a class=wa target=_blank rel=noopener href='https://wa.me/{e(str(x['phone']).lstrip('+'))}?text={urllib.parse.quote(broadcast['message'])}'>فتح واتساب</a>")
    table = "".join(
        f"<tr><td>{e(x['driver_name'])}</td><td dir=ltr>{e(x['phone'])}</td><td>{e(x['status'])}</td>"
        f"<td>{manual_link(x)}</td>"
        f"<td>{e(x.get('last_error'))}<p>المرحلة: {e(x.get('send_phase'))} · HTTP: {e(x.get('provider_response_status'))}</p><pre>{e(x.get('preflight_diagnostic'))}</pre></td></tr>" for x in recipients
    )
    recovery = (f'<p><a style="color:#86efac" href=/commands/broadcast/{broadcast_id}/recovery>استعادة الاختبار مع حفظ السجل السابق</a></p>' if broadcast.get('is_test') and broadcast['status'] in ('completed_with_errors', 'test_completed') else '')
    confirm = ""
    test_fields = (f"<h2>{e(test_context['disclaimer'])}</h2><p>الأسعار والأوزان بيانات محاكاة، ولا يوجد التزام نقل أو دفع.</p>"
                   f"<input type=hidden name=test_preview value='{e(test_context['digest'])}'>"
                   "<label><input type=checkbox name=test_confirmed value=yes required> أعتمد إرسال الاختبار المعلن بهذا النص إلى المستلمين المعروضين فقط</label>" if test_context else '')
    if broadcast["status"] == "draft" and not needs_refresh:
        confirm = f"""<form method=post action=/commands/broadcast/{broadcast_id}/send><input type=hidden name=csrf value="{e(current['csrf'])}">{test_fields}<label><input type=checkbox name=confirmed value=yes required> راجعت نص الرسالة وعدد المستلمين وأؤكد الإرسال مرة واحدة للجميع</label><button>إرسال للجميع</button></form>"""
    return HTMLResponse(f"""<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>مراجعة حملة السائقين</title><style>body{{font-family:Arial;background:#07131f;color:#eef6fb;padding:24px}}.card{{max-width:950px;margin:14px auto;background:#102536;padding:22px;border-radius:16px;overflow:auto}}button{{padding:12px 18px;background:#ef4444;color:white;border:0;border-radius:9px;font-weight:bold}}.wa{{display:inline-block;padding:7px 10px;border-radius:8px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:bold;white-space:nowrap}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;border-bottom:1px solid #28475d;text-align:right}}input[type=checkbox]{{width:auto}}.msg{{white-space:pre-wrap;background:#081925;padding:14px;border-radius:10px}}</style><div class=card><h1>مراجعة حملة السائقين</h1><p><b>الحالة:</b> {e(broadcast['status'])} | <b>المستلمون:</b> {broadcast['recipient_count']} | <b>قبل المزود:</b> {broadcast['sent_count']} | <b>فشل/غير مؤكد:</b> {broadcast['failed_count']}</p><p>قبول المزود لا يثبت تسليم الرسالة أو قراءتها. قد يظهر فشل التسليم لاحقًا لدى المزود.</p><div class=msg>{e(broadcast['message'])}</div><p>تشمل القائمة جميع السائقين المسجلين، مع استبعاد الأرقام غير الصالحة والمكررة.</p><p style="color:#fde68a">يمكنك استخدام «فتح واتساب» لكل سائق يدويًا حتى يكتمل ربط WhatsApp Business API. فتح الرابط لا يعني أن الرسالة أُرسلت.</p>{validation}{confirm}{recovery}</div><div class=card><table><tr><th>السائق</th><th>الرقم</th><th>الحالة</th><th>إرسال يدوي</th><th>الخطأ</th></tr>{table}</table><p><a style="color:#86efac" href=/commands>العودة لمساعد الأوامر</a></p></div></html>""")


async def deliver_driver_broadcast(broadcast_id):
    # Lazy account-scoped transport context; mock/non-Zernio senders open no client.
    async with transport_batch():
        await _deliver_driver_broadcast(broadcast_id)


def _record_dispatch_boundary(broadcast_id, recipient_id, expected_message, expected_phone):
    # Recheck after any preflight backoff. Once this marker is committed the
    # outcome may be uncertain and must never enter preflight-only recovery.
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        raise HTTPException(409, 'الإرسال الخارجي غير مفعّل؛ أوقفت المحاولة قبل إرسال الرسالة')
    with db() as c:
        campaign = c.execute('SELECT * FROM driver_broadcasts WHERE id=%s FOR UPDATE', (broadcast_id,)).fetchone()
        recipient = c.execute('SELECT * FROM driver_broadcast_recipients WHERE id=%s FOR UPDATE', (recipient_id,)).fetchone()
        if (not campaign or campaign['status'] != 'sending' or campaign.get('accepted_driver_id')
                or campaign.get('accepted_at') or not recipient or recipient['status'] != 'sending'
                or recipient.get('provider_message_id') or recipient.get('post_attempted_at')
                or campaign['message'] != expected_message or recipient['phone'] != expected_phone):
            raise HTTPException(409, 'توقف الإرسال: تغيرت الحملة أو بدأت محاولة هذا المستلم')
        _validate_before_send(c, campaign)
        test_broadcast_context(campaign, approved=True)
        c.execute("UPDATE driver_broadcast_recipients SET post_attempted_at=%s,send_phase='dispatching' WHERE id=%s", (utcnow(),recipient_id))


async def _deliver_driver_broadcast(broadcast_id):
    campaign = one("SELECT * FROM driver_broadcasts WHERE id=?", (broadcast_id,))
    if not campaign or campaign["status"] != "sending":
        return
    # Defense in depth: direct/background calls cannot bypass test approval.
    try:
        test_broadcast_context(campaign, approved=True)
    except HTTPException:
        execute("UPDATE driver_broadcasts SET status='test_blocked',updated_at=? WHERE id=? AND status='sending'", (utcnow(), broadcast_id))
        return
    try:
        with db() as c:
            _validate_before_send(c, campaign)
    except HTTPException:
        execute("UPDATE driver_broadcasts SET status='validation_blocked',updated_at=? WHERE id=? AND status='sending'", (utcnow(), broadcast_id))
        return
    recipients = rows("SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=? AND status='pending' ORDER BY id", (broadcast_id,))
    for recipient in recipients:
        current_campaign = one("SELECT * FROM driver_broadcasts WHERE id=?", (broadcast_id,))
        try:
            test_broadcast_context(current_campaign, approved=True)
            with db() as c:
                _validate_before_send(c, current_campaign)
        except HTTPException:
            execute("UPDATE driver_broadcasts SET status='test_blocked',updated_at=? WHERE id=? AND status='sending'", (utcnow(), broadcast_id))
            return
        with db() as c:
            claim = c.execute("""UPDATE driver_broadcast_recipients SET status='sending',send_phase='preflight'
                WHERE id=%s AND status='pending' AND EXISTS(
                SELECT 1 FROM driver_broadcasts WHERE id=%s AND status='sending') RETURNING id""",
                (recipient['id'], broadcast_id)).fetchone()
        if not claim:
            continue
        try:
            with dispatch_guard(lambda: _record_dispatch_boundary(broadcast_id, recipient['id'], campaign['message'], recipient['phone'])):
                result = await send_text_message(recipient["phone"], campaign["message"])
            messages = result.get("messages") or []
            provider_id = str(messages[0].get("id") or "") if messages else ""
            if not provider_id:
                raise RuntimeError('لم يرجع مزود الرسائل معرفًا؛ يلزم التحقق قبل إعادة المحاولة')
            provider_account = result.get('account_id') if result.get('provider') == 'zernio' else None
            execute("UPDATE driver_broadcast_recipients SET status=CASE WHEN status='sending' THEN 'sent' ELSE status END,provider_message_id=?,sent_at=?,send_phase='accepted',provider_response_status=?,provider_account_id=? WHERE id=?", (provider_id, utcnow(), result.get('http_status'), provider_account, recipient["id"]))
        except Exception as exc:
            preflight = isinstance(exc, WhatsAppPreflightBlocked)
            diagnostic = json.dumps({key:value for key,value in exc.diagnostic.items() if key in
                {'phase','endpoint','http_status','error_category','attempts','retryable','rate_limit',
                 'rate_remaining','rate_reset_unix','retry_after_seconds'}}, ensure_ascii=False) if preflight else None
            response = getattr(exc, 'response', None)
            response_status = getattr(exc, 'http_status', None) or getattr(response, 'status_code', None)
            evidence = one('SELECT post_attempted_at FROM driver_broadcast_recipients WHERE id=?', (recipient['id'],)) or {}
            blocked_phase = 'post_rejected' if evidence.get('post_attempted_at') or response_status is not None else 'preflight_blocked'
            phase = 'preflight_failed' if preflight else blocked_phase if isinstance(exc, WhatsAppBlocked) else 'uncertain'
            execute("""UPDATE driver_broadcast_recipients SET status=?,last_error=?,send_phase=?,
                preflight_diagnostic=?,provider_response_status=? WHERE id=? AND status='sending'""",
                ('failed' if isinstance(exc, WhatsAppBlocked) else 'uncertain', str(exc)[:300],
                 phase, diagnostic, response_status, recipient['id']))
    counts = one("""SELECT COUNT(*) FILTER (WHERE provider_message_id IS NOT NULL AND provider_message_id<>'') sent,
        COUNT(*) FILTER (WHERE status IN ('failed','uncertain')) failed,
        COUNT(*) FILTER (WHERE status IN ('pending','sending')) pending FROM driver_broadcast_recipients WHERE broadcast_id=?""", (broadcast_id,))
    final_status = ('sending' if counts['pending'] else
                    ('completed_with_errors' if counts['failed'] else
                     ('awaiting_driver' if campaign.get('shipment_id') else 'completed')))
    execute("""UPDATE driver_broadcasts SET status=CASE WHEN status='sending' THEN ? ELSE status END,
        sent_count=?,failed_count=?,completed_at=?,updated_at=? WHERE id=?""",
        (final_status, counts['sent'], counts['failed'], None if counts['pending'] else utcnow(), utcnow(), broadcast_id))


@router.post("/commands/broadcast/{broadcast_id}/send")
async def send_broadcast(broadcast_id: int, request: Request, background_tasks: BackgroundTasks):
    current = session(request)
    data = form(await request.body())
    if current.get("role") != "admin":
        raise HTTPException(403, "Admin role required")
    if data.get("csrf") != current["csrf"]:
        raise HTTPException(403)
    if data.get("confirmed") != "yes":
        raise HTTPException(400, "Single final confirmation is required")
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        raise HTTPException(409, 'الإرسال الخارجي غير مفعّل؛ بقي العرض مسودة')
    campaign = one("SELECT * FROM driver_broadcasts WHERE id=?", (broadcast_id,))
    if not campaign or campaign["status"] != "draft":
        raise HTTPException(409, "Campaign is not ready for confirmation")
    now = utcnow()
    with db() as c:
        campaign = c.execute('SELECT * FROM driver_broadcasts WHERE id=%s FOR UPDATE', (broadcast_id,)).fetchone()
        if not campaign or campaign['status'] != 'draft':
            raise HTTPException(409, 'تم اعتماد هذا العرض مسبقًا')
        _validate_before_send(c, campaign)
        test_context = test_broadcast_context(campaign)
        if test_context and (data.get('test_confirmed') != 'yes' or data.get('test_preview') != test_context['digest']):
            raise HTTPException(400, 'راجع معاينة الاختبار الحالية ثم اعتمد إرسال الاختبار صراحة')
        claim = c.execute("""UPDATE driver_broadcasts SET status='sending',confirmed_by=%s,confirmed_at=%s,updated_at=%s,
            test_approved_by=%s,test_approved_at=%s,test_preview_digest=%s
            WHERE id=%s AND status='draft' RETURNING id""",
            (current['user_id'], now, now, current['user_id'] if test_context else None,
             now if test_context else None, test_context['digest'] if test_context else None, broadcast_id)).fetchone()
    if not claim:
        raise HTTPException(409, 'تم اعتماد هذا العرض مسبقًا')
    log(current["user_id"], "driver_broadcast_confirmed", "driver_broadcast", broadcast_id, f"Single confirmation accepted for {campaign['recipient_count']} recipients")
    background_tasks.add_task(deliver_driver_broadcast, broadcast_id)
    return RedirectResponse(f"/commands/broadcast/{broadcast_id}", 303)

