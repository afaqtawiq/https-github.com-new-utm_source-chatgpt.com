"""Signed Zernio WhatsApp intake. Separate from browser/session authentication."""
import hashlib
import hmac
import json
import os
import re
from urllib.parse import quote
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.storage import db

router = APIRouter()

def valid_signature(raw, signature, secret):
    return bool(secret and signature and hmac.compare_digest(
        hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), signature))

def choose_agent(text, interactive="", previous=None):
    if interactive == "route_afaaq": return "afaaq"
    if interactive == "route_shawahid": return "shawahid"
    if re.search(r"آفاق|افاق|طويق|تخليص|جمرك|شحن|نقل|تخزين|customs|clearance|shipping|freight|logistics", text, re.I): return "afaaq"
    if re.search(r"شواهد|تسويق|محتوى|أفلييت|shawahid|marketing|content|affiliate|automation", text, re.I): return "shawahid"
    return previous

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
    return {"receiver":"zernio", "requires_signature":True,
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
    with db() as c:
        claim = c.execute("INSERT INTO zernio_reply_events(event_id,conversation_id,state) VALUES(%s,%s,'sending') ON CONFLICT DO NOTHING RETURNING event_id",(event_id,conversation_id)).fetchone()
        if not claim: return {"ok":True,"duplicate":True}
        previous = c.execute("SELECT agent FROM zernio_conversation_agents WHERE conversation_id=%s",(conversation_id,)).fetchone()
        agent = choose_agent(str(message.get("text") or ""), str(metadata.get("interactiveId") or ""), previous["agent"] if previous else None)
        if agent:
            c.execute("INSERT INTO zernio_conversation_agents(conversation_id,agent) VALUES(%s,%s) ON CONFLICT(conversation_id) DO UPDATE SET agent=EXCLUDED.agent,updated_at=NOW()", (conversation_id,agent))
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.post("https://zernio.com/api/v1/inbox/conversations/"+quote(conversation_id,safe="")+"/messages",
                headers={"Authorization":"Bearer "+key,"Idempotency-Key":"shawahid-"+event_id},
                json={"accountId":account_id, **response_body(agent)})
        state = "sent" if result.is_success else "rejected"
    except httpx.HTTPError:
        state = "uncertain"
    with db() as c:
        c.execute("UPDATE zernio_reply_events SET state=%s,updated_at=NOW() WHERE event_id=%s",(state,event_id))
    # An uncertain send is never retried automatically; reconcile with provider first.
    return {"ok":state=="sent","state":state,"agent":agent,"retry_automatically":False}
