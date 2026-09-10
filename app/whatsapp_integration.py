import hashlib
import hmac
import json
import os

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

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
    from app.shipment_automation import process_owner_webhook
    await process_owner_webhook(payload)
    return {"received": True}


@router.get("/api/v7/whatsapp/status")
def whatsapp_status():
    return {
        "configured": bool(
            os.getenv("WHATSAPP_ACCESS_TOKEN")
            and os.getenv("WHATSAPP_PHONE_NUMBER_ID")
            and os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID")
            and os.getenv("WHATSAPP_VERIFY_TOKEN")
            and os.getenv("WHATSAPP_APP_SECRET")
        ),
        "webhook": "/webhooks/whatsapp",
        "phone_number_id": os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
        "business_account_id": os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", ""),
        "recent_events": rows(
            "SELECT id,event_key,received_at FROM whatsapp_webhook_events ORDER BY id DESC LIMIT 10"
        ),
    }


async def send_text_message(recipient: str, message: str) -> dict:
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
