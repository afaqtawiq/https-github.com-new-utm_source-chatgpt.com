"""Signed Zernio WhatsApp intake. Separate from browser/session authentication."""
import asyncio
import hashlib
import hmac
import json
import os
import re
from urllib.parse import quote
import httpx
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from app.storage import db, get_session
from fastapi.responses import HTMLResponse, RedirectResponse
from html import escape

router = APIRouter()

def valid_signature(raw, signature, secret):
    return bool(secret and signature and hmac.compare_digest(
        hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), signature))

def control_text(text):
    text = re.sub(r"[\u064b-\u065f\u0670ـ]", "", text.casefold())
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())

def is_menu_request(text):
    return control_text(text) in {
        "hi", "hello", "hey", "start", "menu", "restart", "back",
        "مرحبا", "اهلا", "أهلا", "السلام عليكم", "السلام عليكم ورحمة الله وبركاته",
        "القائمة", "القائمة الرئيسية", "البداية", "ابدأ", "ابدا", "رجوع"}

def explicit_agent(text, interactive=""):
    if interactive == "route_afaaq": return "afaaq"
    if interactive == "route_shawahid": return "shawahid"
    value = control_text(text)
    if value in {"آفاق طويق", "افاق طويق", "آفاق", "افاق", "afaaq", "afaaq tuwaiq"}:
        return "afaaq"
    if value in {"شواهد الهدف", "شواهد", "shawahid", "shawahid alhadaf", "shawahid al hadaf"}:
        return "shawahid"
    return None

def choose_agent(text, interactive="", previous=None):
    selected = explicit_agent(text, interactive)
    if selected: return selected
    if is_menu_request(text): return None
    return previous if previous in ("afaaq", "shawahid") else None

def response_body(agent):
    if agent == "afaaq":
        return {"message":"مرحبًا بك في آفاق طويق للتخليص الجمركي والنقل والشحن والتخزين. أرسل الخدمة المطلوبة، نقطة الانطلاق والوجهة، نوع البضاعة والوزن والموعد المتوقع. الأسعار والحجوزات تحتاج مراجعة قبل اعتمادها."}
    if agent == "shawahid":
        return {"message":"Welcome to Shawahid Alhadaf. What would you like to achieve? Please share your business, target audience, required service, budget range, and deadline."}
    return {"message":"Welcome. Choose your team / اختر الجهة المطلوبة:", "buttons":[
        {"type":"postback","title":"Shawahid Alhadaf","payload":"route_shawahid"},
        {"type":"postback","title":"آفاق طويق","payload":"route_afaaq"}]}

def ensure_tables():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS zernio_reply_events(
            event_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
            state TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        c.execute("""CREATE TABLE IF NOT EXISTS zernio_conversation_agents(
            conversation_id TEXT PRIMARY KEY, agent TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")

@router.get("/webhooks/zernio")
async def health():
    return {"receiver":"zernio", "routing_version":"owner-commands-v1", "requires_signature":True,
            "owner_commands_configured":bool(os.getenv("WHATSAPP_COMMAND_OWNER") and os.getenv("WHATSAPP_COMMAND_ACCOUNT_ID")),
            "voice_commands_configured":bool(os.getenv("OPENAI_API_KEY")),
            "configured":bool(os.getenv("ZERNIO_API_KEY") and os.getenv("ZERNIO_WEBHOOK_SECRET"))}

@router.post("/webhooks/zernio")
async def receive(request: Request):
    raw = await request.body()
    if len(raw) > 1048576:
        return JSONResponse({"error":"Payload too large"}, status_code=413)
    secret = os.getenv("ZERNIO_WEBHOOK_SECRET", "")
    signature = request.headers.get("x-zernio-signature") or request.headers.get("x-late-signature") or ""
    if not secret:
        return JSONResponse({"error":"Receiver configuration missing"}, status_code=503)
    if not valid_signature(raw, signature, secret):
        return JSONResponse({"error":"Invalid webhook signature"}, status_code=401)
    try:
        p = json.loads(raw)
        if not isinstance(p, dict): raise ValueError()
    except (ValueError, TypeError):
        return JSONResponse({"error":"Invalid payload"}, status_code=400)
    if p.get("event") == "webhook.test":
        return {"ok":True,"test":True}
    if p.get("event") != "message.received":
        return {"ok":True,"ignored":"not_inbound_message"}
    metadata = p.get("metadata") or {}
    account = p.get("account") or {}
    message = p.get("message") or {}
    if metadata.get("standby") or message.get("direction") in ("outbound", "outgoing"):
        return {"ok":True,"ignored":"standby_or_outbound"}
    if account.get("platform") != "whatsapp":
        return {"ok":True,"ignored":"not_whatsapp"}
    key = os.getenv("ZERNIO_API_KEY", "")
    if not key:
        return JSONResponse({"error":"Zernio API key not configured"}, status_code=503)
    event_id = p.get("id")
    conversation_id = (p.get("conversation") or {}).get("id")
    account_id = account.get("accountId") or account.get("id")
    if not all(isinstance(x,str) and 0 < len(x) <= 255 for x in (event_id,conversation_id,account_id)):
        return JSONResponse({"error":"Missing event or conversation identifiers"}, status_code=400)
    ensure_tables()
    ensure_intake_tables()
    from app.whatsapp_admin import owner_sender, admin_reply
    sender = owner_sender(p)
    def prepare_reply():
        with db() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (conversation_id,))
            claim = c.execute("INSERT INTO zernio_reply_events(event_id,conversation_id,state) VALUES(%s,%s,'sending') ON CONFLICT DO NOTHING RETURNING event_id",(event_id,conversation_id)).fetchone()
            if not claim: return None
            if sender:
                agent = "owner"
                reply = asyncio.run(admin_reply(c, p, sender))
            else:
                previous = c.execute("SELECT agent FROM zernio_conversation_agents WHERE conversation_id=%s",(conversation_id,)).fetchone()
                text = str(message.get("text") or "")
                interactive = str(metadata.get("interactiveId") or "")
                selection = explicit_agent(text, interactive) is not None
                agent = choose_agent(text, interactive, previous["agent"] if previous else None)
                if agent:
                    c.execute("INSERT INTO zernio_conversation_agents(conversation_id,agent) VALUES(%s,%s) ON CONFLICT(conversation_id) DO UPDATE SET agent=EXCLUDED.agent,updated_at=NOW()", (conversation_id,agent))
                else:
                    c.execute("DELETE FROM zernio_conversation_agents WHERE conversation_id=%s", (conversation_id,))
                reply = intake_reply(c, agent, conversation_id, event_id, text, selection, message)
        return agent, reply
    prepared = await run_in_threadpool(prepare_reply)
    if prepared is None:
        return {"ok":True,"duplicate":True}
    agent, reply = prepared
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.post("https://zernio.com/api/v1/inbox/conversations/"+quote(conversation_id,safe="")+"/messages",
                headers={"Authorization":"Bearer "+key,"Idempotency-Key":"shawahid-"+event_id},
                json={"accountId":account_id, **reply})
        state = "sent" if result.is_success else "rejected"
    except httpx.HTTPError:
        state = "uncertain"
    with db() as c:
        c.execute("UPDATE zernio_reply_events SET state=%s,updated_at=NOW() WHERE event_id=%s",(state,event_id))
    # An uncertain send is never retried automatically; reconcile with provider first.
    return {"ok":state=="sent","state":state,"agent":agent,"retry_automatically":False}


# Stateful intake: customer information is collected explicitly, never guessed.
FIELDS = {
    "afaaq": [("service", "ما الخدمة المطلوبة؟"), ("route", "ما نقطة الانطلاق والوجهة أو المنفذ الجمركي؟"),
              ("cargo", "ما نوع البضاعة والوزن أو الكمية؟"), ("deadline", "ما الموعد المطلوب؟")],
    "shawahid": [("service", "What marketing service do you need?"),
                 ("business", "What is your business and target audience?"),
                 ("budget", "What is your budget range? You may say undecided."),
                 ("deadline", "What is your deadline?")]
}

def ensure_intake_tables():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS zernio_requests(
            id BIGSERIAL PRIMARY KEY, conversation_id TEXT NOT NULL, agent TEXT NOT NULL,
            fields JSONB NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'collecting',
            pending_field TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(conversation_id,agent))""")
        c.execute("""CREATE TABLE IF NOT EXISTS zernio_request_messages(
            event_id TEXT PRIMARY KEY, request_id BIGINT NOT NULL REFERENCES zernio_requests(id),
            body TEXT NOT NULL, reply TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")

def explicit_updates(agent, text):
    """Only labelled customer fields are updates; prose is never a budget."""
    labels = {key: key for key, _ in FIELDS[agent]}
    labels.update({"الميزانية": "budget", "الموعد": "deadline",
                   "الخدمة": "service", "النشاط": "business", "التعديل": "revision",
                   "revision": "revision"})
    allowed = {key for key, _ in FIELDS[agent]} | {"revision"}
    pattern = r"(?im)^\s*(" + "|".join(map(re.escape, labels)) + r")\s*:\s*"
    matches = list(re.finditer(pattern, text))
    updates = {}
    for index, match in enumerate(matches):
        key = labels[match.group(1).casefold()]
        value = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)].strip()
        if key in allowed and value:
            updates[key] = value[:12000]
    return updates


def next_reply(agent, fields, pending, text, selection=False):
    fields = dict(fields)
    normalized = text.strip()
    control = normalized.casefold()
    status_query = control in ("status", "حالة الطلب", "متابعة", "الحالة")
    updates = explicit_updates(agent, normalized) if not selection and not status_query else {}
    if updates:
        fields.update(updates)
    elif pending and normalized and not selection and not status_query and not is_menu_request(text):
        fields[pending] = normalized[:12000]
    missing = [(key, question) for key, question in FIELDS[agent] if not fields.get(key)]
    if missing:
        key, question = missing[0]
        return fields, key, "collecting", question
    if normalized and not selection and not status_query and not pending:
        if updates:
            changes = "\n".join(key + ": " + value for key, value in updates.items())
            reply = (("تم تحديث طلبك الحالي:\n" if agent == "afaaq" else "Your existing request has been updated:\n") + changes)
        else:
            fields["latest_follow_up"] = normalized[:12000]
            reply = ("تم حفظ رسالتك الإضافية مع طلبك الحالي للمراجعة." if agent == "afaaq"
                     else "Your follow-up has been saved with your existing request for review.")
        reply += ("\nلم يتم النشر أو تأكيد دفع أو حجز. التعديلات على المواد تحتاج مراجعة."
                  if agent == "afaaq" else
                  "\nNo publishing, payment or booking has been authorized by this update. Creative revisions are recorded for review; revised materials are not yet generated.")
        return fields, None, "ready_for_review", reply
    summary = "\n".join(key + ": " + str(fields[key]) for key, _ in FIELDS[agent])
    if agent == "afaaq":
        reply = "تم حفظ تفاصيل طلبك للمراجعة:\n" + summary + "\nلم يتم تأكيد سعر أو حجز أو دفع. أي تفاصيل إضافية ترسلها ستُحفظ مع الطلب."
    else:
        reply = "Your request is saved for review:\n" + summary + "\nNo price, booking or payment has been confirmed. Further messages will be added to your request."
    return fields, None, "ready_for_review", reply

def intake_reply(c, agent, conversation_id, event_id, text, selection, message):
    if agent not in FIELDS:
        return response_body(agent)
    c.execute("""INSERT INTO zernio_requests(conversation_id,agent)
        VALUES(%s,%s) ON CONFLICT DO NOTHING""", (conversation_id,agent))
    row = c.execute("""SELECT * FROM zernio_requests WHERE conversation_id=%s
        AND agent=%s FOR UPDATE""", (conversation_id,agent)).fetchone()
    # All initial context is retained, but not incorrectly assigned to an unasked field.
    ref = ("AF-" if agent == "afaaq" else "SH-") + str(row["id"])
    references = re.findall(r"(?i)\b(?:SH|AF)-\d+\b", text)
    if any(value.upper() != ref for value in references):
        reply = ref + "\n" + ("رقم الطلب المذكور لا يطابق طلبك الحالي؛ لم يتم إجراء تعديلات."
                               if agent == "afaaq" else
                               "The request reference does not match your current request. No changes were made.")
        c.execute("""INSERT INTO zernio_request_messages(event_id,request_id,body,reply)
            VALUES(%s,%s,%s,%s)""", (event_id,row["id"],text[:20000],reply))
        return {"message": reply}
    fields, pending, status, reply = next_reply(agent, row["fields"], row["pending_field"], text, selection)
    if agent == "shawahid" and not selection and explicit_updates(agent, text).get("revision"):
        from app.material_bridge import material_reply
        reply = material_reply(c, row["id"], event_id, fields["revision"])
        if explicit_updates(agent, text).get("budget"):
            reply = "Budget updated: " + fields["budget"] + "\n\n" + reply
    if not text.strip() and not selection:
        reply = ("يرجى إرسال التفاصيل كتابةً؛ المرفقات لم تُحلّل تلقائيًا. " if agent=="afaaq"
                 else "Please send the details as text; attachments are not automatically analyzed. ") + reply
    ref = ("AF-" if agent=="afaaq" else "SH-") + str(row["id"])
    reply = ref + "\n" + reply
    c.execute("""UPDATE zernio_requests SET fields=%s::jsonb,pending_field=%s,
        status=%s,updated_at=NOW() WHERE id=%s""",
        (json.dumps(fields,ensure_ascii=False),pending,status,row["id"]))
    c.execute("""INSERT INTO zernio_request_messages(event_id,request_id,body,reply)
        VALUES(%s,%s,%s,%s)""", (event_id,row["id"],text[:20000],reply))
    return {"message":reply}

@router.get("/whatsapp-requests", response_class=HTMLResponse)
def requests_page(request: Request):
    session = get_session(request.cookies.get("gla_session"))
    if not session:
        return RedirectResponse("/login",303)
    if session.get("role") != "admin":
        return HTMLResponse("Administrator access required",status_code=403)
    ensure_intake_tables()
    agent = request.query_params.get("agent","")
    with db() as c:
        items = c.execute("""SELECT * FROM zernio_requests
            WHERE (%s='' OR agent=%s) ORDER BY updated_at DESC LIMIT 100""",(agent,agent)).fetchall()
        cards = []
        for item in items:
            messages = c.execute("""SELECT m.*,e.state FROM zernio_request_messages m
                LEFT JOIN zernio_reply_events e ON e.event_id=m.event_id
                WHERE request_id=%s ORDER BY m.created_at DESC LIMIT 50""",(item["id"],)).fetchall()
            ref = ("AF-" if item["agent"]=="afaaq" else "SH-")+str(item["id"])
            history = "".join("<details><summary>"+escape(str(m["created_at"]))+" — "+escape(m["state"] or "pending")+"</summary><pre>"+escape(m["body"])+"</pre><pre>"+escape(m["reply"])+"</pre></details>" for m in reversed(messages))
            cards.append("<section><h2>"+ref+" — "+escape(item["agent"])+"</h2><p>"+escape(item["status"])+"</p><pre>"+escape(json.dumps(item["fields"],ensure_ascii=False,indent=2))+"</pre>"+history+"</section>")
    return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>طلبات واتساب</title><style>body{font:17px Tahoma;background:#0b2031;color:#fff;padding:24px}a{color:#ffd978;margin:12px}section{padding:20px;border:1px solid #496071;border-radius:12px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}details{padding:8px}</style><h1>طلبات واتساب — شواهد وآفاق</h1><p>جمع متطلبات ومراجعة فقط؛ لا تأكيد دفع أو تنفيذ تجاري. آخر 100 طلب و50 رسالة لكل طلب.</p><nav><a href="/dashboard">الرئيسية</a><a href="?agent=shawahid">شواهد</a><a href="?agent=afaaq">آفاق</a><a href="/whatsapp-requests">الجميع</a></nav>'+("".join(cards) or "<p>لا توجد طلبات بعد. تُسجل الرسائل الجديدة بعد تفعيل هذه النسخة.</p>")+"</html>",headers={"Cache-Control":"no-store"})

@router.get("/api/shawahid/intake-feed")
def intake_feed(request: Request):
    import time
    stamp = request.headers.get("x-intake-time", "")
    signature = request.headers.get("x-intake-signature", "")
    after = request.query_params.get("after", "0")
    secret = os.getenv("SHAWAHID_INTAKE_SECRET", "")
    try:
        fresh = abs(time.time() - int(stamp)) <= 120
        cursor = max(0, int(after))
    except ValueError:
        return JSONResponse({"error":"Invalid request"},status_code=401)
    signed = ("shawahid-intake-v1:" + stamp + ":" + str(cursor)).encode()
    if not fresh or not valid_signature(signed, signature, secret):
        return JSONResponse({"error":"Invalid signature"},status_code=401)
    ensure_intake_tables()
    with db() as c:
        rows = c.execute("SELECT id,fields,status,updated_at FROM zernio_requests WHERE agent='shawahid' AND id>%s ORDER BY id LIMIT 100",(cursor,)).fetchall()
    return JSONResponse({"requests":[{"id":r["id"],"fields":r["fields"],"status":r["status"],"updatedAt":str(r["updated_at"])} for r in rows]},headers={"Cache-Control":"no-store"})

from app.material_bridge import router as material_router
router.include_router(material_router)
