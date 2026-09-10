import html
import json
import re
import urllib.parse

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.storage import execute, get_session, log, one, rows, utcnow
from app.whatsapp_integration import send_text_message

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
    execute("""CREATE TABLE IF NOT EXISTS driver_broadcast_recipients(
        id BIGSERIAL PRIMARY KEY,
        broadcast_id BIGINT NOT NULL REFERENCES driver_broadcasts(id) ON DELETE CASCADE,
        driver_id BIGINT REFERENCES drivers(id) ON DELETE SET NULL,
        driver_name TEXT, phone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        provider_message_id TEXT, last_error TEXT, sent_at TIMESTAMPTZ,
        UNIQUE(broadcast_id,phone)
    )""")


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
    text = normalize_text(raw)
    broadcast = re.match(r"^(?:ارسل|ابعث)\s+(?:رسالة\s+)?(?:واتساب|واتس)?\s*(?:الى|ل)?\s*(?:جميع|كل)\s+السائقين\s*(.*)$", text, flags=re.IGNORECASE)
    if broadcast:
        content = re.sub(r"^(?:بخصوص|محتوى|وقل|برسالة)\s+", "", broadcast.group(1).strip())
        return {"action_type": "driver_broadcast", "target": "جميع السائقين", "content": content}
    patterns = (
        ("call", r"^(?:اتصل|اتصال|كلم)\s+(?:على|ب)?\s*(.+)$"),
        ("whatsapp", r"^(?:ارسل|ابعث)\s+(?:رسالة\s+)?(?:واتساب|واتس)\s+(?:الى|ل)?\s*(.+)$"),
        ("email", r"^(?:ارسل|ابعث)\s+(?:رسالة\s+)?(?:ايميل|بريد(?:ا\s+الكترونيا)?)\s+(?:الى|ل)?\s*(.+)$"),
    )
    for action_type, pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            remainder = match.group(1).strip()
            parts = re.split(r"\s+(?:وقل|وقولي|برسالة|بخصوص|محتوى)\s+", remainder, maxsplit=1)
            return {"action_type": action_type, "target": parts[0].strip(" ،,."), "content": parts[1].strip() if len(parts) > 1 else ""}
    navigation = {
        "افتح العملاء": "/accounts", "اعرض العملاء": "/accounts",
        "افتح السائقين": "/drivers", "اعرض السائقين": "/drivers",
        "افتح الفرص": "/opportunities", "اعرض الفرص": "/opportunities",
        "افتح الموافقات": "/approvals", "اعرض الموافقات": "/approvals",
    }
    if text in navigation:
        return {"action_type": "navigate", "target": text, "url": navigation[text], "content": ""}
    return {"action_type": "unknown", "target": "", "content": ""}


def find_contact(target):
    needle = "%" + normalize_text(target) + "%"
    return rows("""SELECT c.*,o.company_name,o.stage FROM sales_contacts c
        JOIN opportunities o ON o.id=c.opportunity_id
        WHERE LOWER(REPLACE(REPLACE(REPLACE(COALESCE(c.name,''),'إ','ا'),'أ','ا'),'آ','ا')) LIKE LOWER(?)
           OR LOWER(REPLACE(REPLACE(REPLACE(COALESCE(o.company_name,''),'إ','ا'),'أ','ا'),'آ','ا')) LIKE LOWER(?)
        ORDER BY c.verified DESC,c.updated_at DESC LIMIT 6""", (needle, needle))


def action_label(kind):
    return {"call": "مكالمة", "whatsapp": "واتساب", "email": "بريد إلكتروني", "driver_broadcast": "واتساب جماعي للسائقين"}.get(kind, kind)


@router.get("/commands", response_class=HTMLResponse)
def commands_page(request: Request):
    current = session(request)
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
<form method=post action=/commands><input type=hidden name=csrf value="{e(current['csrf'])}"><textarea id=command name=command required placeholder="مثال: أرسل واتساب إلى أحمد بخصوص عرض النقل"></textarea><button type=button id=mic>🎙 بدء الاستماع</button><button type=submit>تحليل الأمر</button><div id=status class=muted></div></form></div>
<div class="card examples"><b>أمثلة:</b><br>«اتصل على محمد»<br>«أرسل واتساب إلى شركة النور بخصوص عرض النقل»<br>«أرسل لجميع السائقين شحنة من الرياض إلى جدة»<br>«أرسل بريدًا إلى أحمد بخصوص خدمات التخليص»<br>«افتح السائقين»</div>
<div class="card scroll"><h2>المسودات الأخيرة</h2><table><tr><th>#</th><th>الأمر</th><th>الجهة</th><th>الشركة</th><th>المستلم</th><th>الحالة</th></tr>{item_rows or '<tr><td colspan=6>لا توجد أوامر بعد.</td></tr>'}</table></div></div>
<script>const mic=document.querySelector('#mic'),field=document.querySelector('#command'),status=document.querySelector('#status');const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SpeechRecognition){{mic.disabled=true;status.textContent='التعرف الصوتي غير متاح في هذا المتصفح؛ استخدم Chrome أو اكتب الأمر.'}}else{{const recognition=new SpeechRecognition();recognition.lang='ar-SA';recognition.interimResults=false;recognition.continuous=false;mic.onclick=()=>{{status.textContent='أستمع الآن...';mic.classList.add('listening');recognition.start()}};recognition.onresult=event=>{{field.value=event.results[0][0].transcript;status.textContent='تم التقاط الأمر. راجعه ثم اضغط تحليل الأمر.'}};recognition.onerror=event=>{{status.textContent='تعذر التقاط الصوت: '+event.error}};recognition.onend=()=>mic.classList.remove('listening')}}</script></html>""")


@router.post("/commands")
async def create_command(request: Request):
    current = session(request); data = form(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    raw = (data.get("command") or "").strip()
    if not raw or len(raw) > 1000: raise HTTPException(400, "Command must contain 1-1000 characters")
    parsed = parse_command(raw)
    if parsed["action_type"] == "navigate":
        log(current["user_id"], "command_navigation", summary=raw[:300])
        return RedirectResponse(parsed["url"], 303)
    if parsed["action_type"] == "unknown":
        return HTMLResponse("<html lang=ar dir=rtl><meta charset=utf-8><body style='font-family:Arial;padding:30px'><h2>لم أفهم الأمر.</h2><p>ابدأ بـ: اتصل على، أرسل واتساب إلى، أرسل بريدًا إلى، أو افتح.</p><a href=/commands>عودة</a></body></html>", 400)
    if parsed["action_type"] == "driver_broadcast":
        message = parsed["content"].strip()
        if not message:
            raise HTTPException(400, "اكتب تفاصيل الرسالة الموجهة للسائقين")
        candidates = rows("""SELECT id,driver_name,whatsapp_phone FROM drivers
            WHERE offer_consent=1 AND whatsapp_phone IS NOT NULL ORDER BY id""")
        valid = []
        seen = set()
        for driver in candidates:
            phone = re.sub(r"[\s\-()]", "", str(driver.get("whatsapp_phone") or ""))
            if phone.startswith("00"):
                phone = "+" + phone[2:]
            if re.fullmatch(r"\+[1-9]\d{7,14}", phone) and phone not in seen:
                seen.add(phone)
                valid.append((driver, phone))
        if not valid:
            raise HTTPException(409, "لا يوجد سائقون بأرقام صالحة وموافقة استقبال عروض مسجلة")
        now = utcnow()
        broadcast_id = execute("""INSERT INTO driver_broadcasts(raw_command,message,status,recipient_count,created_by,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)""", (raw, message, "draft", len(valid), current["user_id"], now, now))
        for driver, phone in valid:
            execute("""INSERT INTO driver_broadcast_recipients(broadcast_id,driver_id,driver_name,phone,status)
                VALUES(?,?,?,?,?) ON CONFLICT(broadcast_id,phone) DO NOTHING""", (broadcast_id, driver["id"], driver["driver_name"], phone, "pending"))
        log(current["user_id"], "driver_broadcast_draft_created", "driver_broadcast", broadcast_id, f"Prepared for {len(valid)} consented unique drivers; not sent")
        return RedirectResponse(f"/commands/broadcast/{broadcast_id}", 303)
    matches = find_contact(parsed["target"])
    if len(matches) != 1:
        reason = "لم نجد جهة اتصال مطابقة" if not matches else "وجدنا أكثر من جهة مطابقة؛ اكتب الاسم بشكل أدق"
        return HTMLResponse(f"<html lang=ar dir=rtl><meta charset=utf-8><body style='font-family:Arial;padding:30px'><h2>{e(reason)}</h2><p>الهدف: {e(parsed['target'])}</p><a href=/commands>عودة</a></body></html>", 409)
    contact = matches[0]
    recipient = contact.get("email") if parsed["action_type"] == "email" else contact.get("phone")
    if not recipient: raise HTTPException(409, "Selected contact has no recipient for this channel")
    if parsed["action_type"] in ("call", "whatsapp") and not contact.get("verified"):
        raise HTTPException(409, "Phone contact must be verified before preparing external communication")
    content = parsed["content"] or ("مناقشة احتياج العميل وتحديد الخدمة المناسبة دون تقديم التزام أو سعر نهائي." if parsed["action_type"] == "call" else "مرحبًا، معك فريق آفاق طويق. نرغب في مناقشة احتياجكم اللوجستي وإعداد عرض مناسب بعد تأكيد التفاصيل.")
    now = utcnow()
    action_id = execute("""INSERT INTO command_actions(raw_command,action_type,target_name,contact_id,opportunity_id,recipient,content,status,parsed_payload,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (raw, parsed["action_type"], parsed["target"], contact["id"], contact["opportunity_id"], recipient, content, "draft", json.dumps(parsed, ensure_ascii=False), current["user_id"], now, now))
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
    return {"automatic_external_actions": False, "supported": ["call", "whatsapp", "driver_broadcast", "email", "navigate"], "items": rows("SELECT id,raw_command,action_type,target_name,recipient,status,created_at FROM command_actions ORDER BY id DESC LIMIT 100")}


@router.get("/commands/broadcast/{broadcast_id}", response_class=HTMLResponse)
def broadcast_review(broadcast_id: int, request: Request):
    current = session(request)
    broadcast = one("SELECT * FROM driver_broadcasts WHERE id=?", (broadcast_id,))
    if not broadcast:
        raise HTTPException(404)
    recipients = rows("SELECT driver_name,phone,status,last_error FROM driver_broadcast_recipients WHERE broadcast_id=? ORDER BY id", (broadcast_id,))
    table = "".join(f"<tr><td>{e(x['driver_name'])}</td><td dir=ltr>{e(x['phone'])}</td><td>{e(x['status'])}</td><td>{e(x.get('last_error'))}</td></tr>" for x in recipients)
    confirm = ""
    if broadcast["status"] == "draft":
        confirm = f"""<form method=post action=/commands/broadcast/{broadcast_id}/send><input type=hidden name=csrf value="{e(current['csrf'])}"><label><input type=checkbox name=confirmed value=yes required> راجعت نص الرسالة وعدد المستلمين وأؤكد الإرسال مرة واحدة للجميع</label><button>إرسال للجميع</button></form>"""
    return HTMLResponse(f"""<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>مراجعة حملة السائقين</title><style>body{{font-family:Arial;background:#07131f;color:#eef6fb;padding:24px}}.card{{max-width:950px;margin:14px auto;background:#102536;padding:22px;border-radius:16px}}button{{padding:12px 18px;background:#ef4444;color:white;border:0;border-radius:9px;font-weight:bold}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;border-bottom:1px solid #28475d;text-align:right}}input[type=checkbox]{{width:auto}}.msg{{white-space:pre-wrap;background:#081925;padding:14px;border-radius:10px}}</style><div class=card><h1>مراجعة الإرسال الجماعي</h1><p><b>الحالة:</b> {e(broadcast['status'])} | <b>المستلمون:</b> {broadcast['recipient_count']} | <b>نجح:</b> {broadcast['sent_count']} | <b>فشل:</b> {broadcast['failed_count']}</p><div class=msg>{e(broadcast['message'])}</div><p>تشمل القائمة فقط السائقين ذوي موافقة استقبال العروض، مع استبعاد الأرقام غير الصالحة والمكررة.</p>{confirm}</div><div class=card><table><tr><th>السائق</th><th>الرقم</th><th>الحالة</th><th>الخطأ</th></tr>{table}</table><p><a style="color:#86efac" href=/commands>العودة لمساعد الأوامر</a></p></div></html>""")


async def deliver_driver_broadcast(broadcast_id):
    campaign = one("SELECT * FROM driver_broadcasts WHERE id=?", (broadcast_id,))
    if not campaign or campaign["status"] != "sending":
        return
    recipients = rows("SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=? AND status='pending' ORDER BY id", (broadcast_id,))
    sent = failed = 0
    for recipient in recipients:
        try:
            result = await send_text_message(recipient["phone"], campaign["message"])
            messages = result.get("messages") or []
            provider_id = str(messages[0].get("id") or "") if messages else ""
            execute("UPDATE driver_broadcast_recipients SET status='sent',provider_message_id=?,sent_at=? WHERE id=?", (provider_id, utcnow(), recipient["id"]))
            sent += 1
        except Exception as exc:
            execute("UPDATE driver_broadcast_recipients SET status='failed',last_error=? WHERE id=?", (str(exc)[:300], recipient["id"]))
            failed += 1
        execute("UPDATE driver_broadcasts SET sent_count=?,failed_count=?,updated_at=? WHERE id=?", (sent, failed, utcnow(), broadcast_id))
    final_status = "completed" if not failed else "completed_with_errors"
    execute("UPDATE driver_broadcasts SET status=?,completed_at=?,updated_at=? WHERE id=?", (final_status, utcnow(), utcnow(), broadcast_id))


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
    campaign = one("SELECT * FROM driver_broadcasts WHERE id=?", (broadcast_id,))
    if not campaign or campaign["status"] != "draft":
        raise HTTPException(409, "Campaign is not ready for confirmation")
    now = utcnow()
    execute("UPDATE driver_broadcasts SET status='sending',confirmed_by=?,confirmed_at=?,updated_at=? WHERE id=?", (current["user_id"], now, now, broadcast_id))
    log(current["user_id"], "driver_broadcast_confirmed", "driver_broadcast", broadcast_id, f"Single confirmation accepted for {campaign['recipient_count']} recipients")
    background_tasks.add_task(deliver_driver_broadcast, broadcast_id)
    return RedirectResponse(f"/commands/broadcast/{broadcast_id}", 303)
