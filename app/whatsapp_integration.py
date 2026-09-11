import hashlib
import hmac
import base64
import json
import os

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response

from app.storage import execute, rows, utcnow


router = APIRouter()

WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v23.0")


def _init_storage():
    execute(
        """CREATE TABLE IF NOT EXISTS whatsapp_webhook_events(
        id BIGSERIAL PRIMARY KEY,
        event_key TEXT UNIQUE NOT NULL,
        payload JSONB NOT NULL,
        received_at TIMESTAMPTZ NOT NULL
        )"""
    )


_init_storage()


def _verify_signature(raw: bytes, signature: str | None) -> bool:
    secret = os.getenv("WHATSAPP_APP_SECRET", "")
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], expected)


def _twilio_signature(url: str, params: dict, signature: str | None) -> bool:
    """Validate Twilio form webhooks without exposing the Auth Token."""
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not token or not signature:
        return False
    source = url + "".join(key + str(params[key]) for key in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), source.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(signature, expected)


def _twilio_public_url(request: Request) -> str:
    base = os.getenv("TWILIO_WEBHOOK_BASE_URL", "").rstrip("/")
    return (base + request.url.path) if base else str(request.url)


@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
def verify_webhook(
    mode: str | None = Query(None, alias="hub.mode"),
    token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
):
    expected = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    if mode != "subscribe" or not expected or not hmac.compare_digest(token or "", expected):
        raise HTTPException(403, "Webhook verification failed")
    return challenge or ""


@router.post("/webhooks/whatsapp")
async def receive_webhook(request: Request):
    raw = await request.body()
    if not _verify_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    event_key = hashlib.sha256(raw).hexdigest()
    execute(
        "INSERT INTO whatsapp_webhook_events(event_key,payload,received_at) VALUES(?,?,?) ON CONFLICT(event_key) DO NOTHING",
        (event_key, json.dumps(payload), utcnow()),
    )
    # Match inbound driver acceptance to the open shipment offer. The first
    # valid acceptance wins atomically; later replies cannot replace it.
    try:
        from app.freight_workflow import accept_driver_reply
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                for message in value.get("messages") or []:
                    sender = str(message.get("from") or "")
                    body = str((message.get("text") or {}).get("body") or "")
                    if sender and body:
                        accept_driver_reply("+" + sender.lstrip("+"), body)
    except Exception:
        # Webhook acknowledgement must not be lost because a message was not
        # relevant to a freight offer or an optional table is unavailable.
        pass
    return {"received": True}


@router.post("/webhooks/twilio/whatsapp")
async def receive_twilio_whatsapp(request: Request):
    form = dict(await request.form())
    if not _twilio_signature(_twilio_public_url(request), form, request.headers.get("x-twilio-signature")):
        raise HTTPException(401, "Invalid Twilio signature")
    message_sid = str(form.get("MessageSid") or form.get("SmsMessageSid") or "")
    event_key = "twilio:" + (message_sid or hashlib.sha256(str(sorted(form.items())).encode()).hexdigest())
    execute(
        "INSERT INTO whatsapp_webhook_events(event_key,payload,received_at) VALUES(?,?,?) ON CONFLICT(event_key) DO NOTHING",
        (event_key, json.dumps({"provider": "twilio", **form}), utcnow()),
    )
    sender = str(form.get("From") or "").replace("whatsapp:", "")
    body = str(form.get("Body") or "")
    try:
        from app.freight_workflow import accept_driver_reply
        if sender and body:
            accept_driver_reply(sender, body)
    except Exception:
        pass
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")


@router.get("/api/v7/whatsapp/status")
def whatsapp_status():
    provider = os.getenv("WHATSAPP_PROVIDER", "meta").lower()
    twilio_ready = bool(os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN") and os.getenv("TWILIO_WHATSAPP_FROM"))
    meta_ready = bool(os.getenv("WHATSAPP_ACCESS_TOKEN") and os.getenv("WHATSAPP_PHONE_NUMBER_ID") and os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID") and os.getenv("WHATSAPP_VERIFY_TOKEN") and os.getenv("WHATSAPP_APP_SECRET"))
    return {
        "provider": provider,
        "configured": twilio_ready if provider == "twilio" else meta_ready,
        "webhook": "/webhooks/twilio/whatsapp" if provider == "twilio" else "/webhooks/whatsapp",
        "twilio_ready": twilio_ready,
        "meta_ready": meta_ready,
        "phone_number_id": os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
        "business_account_id": os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", ""),
        "recent_events": rows(
            "SELECT id,event_key,received_at FROM whatsapp_webhook_events ORDER BY id DESC LIMIT 10"
        ),
    }


async def send_text_message(recipient: str, message: str) -> dict:
    if os.getenv("WHATSAPP_PROVIDER", "meta").lower() == "twilio":
        return await _send_twilio_message(recipient, message)
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    if not token or not phone_number_id:
        raise RuntimeError("WhatsApp Cloud API is not configured")
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": message},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    response.raise_for_status()
    return response.json()


async def _send_twilio_message(recipient: str, message: str) -> dict:
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    sender = os.getenv("TWILIO_WHATSAPP_FROM", "")
    if not sid or not token or not sender:
        raise RuntimeError("Twilio WhatsApp is not configured")
    sender = sender if sender.startswith("whatsapp:") else "whatsapp:" + sender
    target = recipient if recipient.startswith("whatsapp:") else "whatsapp:" + recipient
    async with httpx.AsyncClient(timeout=20, auth=(sid, token)) as client:
        response = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={"From": sender, "To": target, "Body": message},
        )
    response.raise_for_status()
    payload = response.json()
    return {"messages": [{"id": payload.get("sid", "")}], "provider": "twilio", "raw": payload}
