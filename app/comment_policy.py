"""Fail-closed public comment policy. No CRM, documents or customer history."""
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone

KNOWN = {"6ab019958d284ffb2121d129": "youtube",
         "6ac0910233b5e635f2b5ff6d": "tiktok"}
# TikTok business-app capability has not been verified for the connected account.
SUPPORTED = {"youtube"}
SERVICES = {"clearance": "\u0627\u0644\u062a\u062e\u0644\u064a\u0635 \u0627\u0644\u062c\u0645\u0631\u0643\u064a", "transport": "\u0627\u0644\u0646\u0642\u0644",
            "shipping": "\u0627\u0644\u0634\u062d\u0646", "storage": "\u0627\u0644\u062a\u062e\u0632\u064a\u0646", "door": "\u0627\u0644\u062a\u0648\u0635\u064a\u0644 \u0645\u0646 \u0627\u0644\u0628\u0627\u0628 \u0625\u0644\u0649 \u0627\u0644\u0628\u0627\u0628"}
REPLIES = {
    "thanks": "\u0634\u0643\u0631\u064b\u0627 \u0644\u0643\u060c \u064a\u0633\u0639\u062f\u0646\u0627 \u062a\u0648\u0627\u0635\u0644\u0643 \u0645\u0639 \u0622\u0641\u0627\u0642 \u0637\u0648\u064a\u0642.",
    "pricing": "\u064a\u0633\u0639\u062f\u0646\u0627 \u0645\u0631\u0627\u062c\u0639\u0629 \u0637\u0644\u0628\u0643. \u0623\u0631\u0633\u0644 \u0644\u0646\u0627 \u0639\u0644\u0649 \u0627\u0644\u062e\u0627\u0635 \u0646\u0648\u0639 \u0627\u0644\u0628\u0636\u0627\u0639\u0629 \u0648\u0646\u0642\u0637\u0629 \u0627\u0644\u0627\u0646\u0637\u0644\u0627\u0642 \u0648\u0627\u0644\u0648\u062c\u0647\u0629 \u0648\u0627\u0644\u0645\u0648\u0639\u062f \u0627\u0644\u0645\u0637\u0644\u0648\u0628 \u0644\u0625\u0639\u062f\u0627\u062f \u0639\u0631\u0636 \u0645\u0646\u0627\u0633\u0628.",
    "ai": "\u0646\u0639\u0645\u060c \u0623\u0646\u0627 \u0645\u0633\u0627\u0639\u062f \u0622\u0644\u064a \u0644\u0622\u0641\u0627\u0642 \u0637\u0648\u064a\u0642. \u0627\u0644\u062a\u0641\u0627\u0635\u064a\u0644 \u0627\u0644\u062a\u062c\u0627\u0631\u064a\u0629 \u0648\u0627\u0644\u062a\u0623\u0643\u064a\u062f\u0627\u062a \u064a\u0631\u0627\u062c\u0639\u0647\u0627 \u0641\u0631\u064a\u0642\u0646\u0627.",
    "general": "\u0646\u0642\u062f\u0645 \u0641\u064a \u0622\u0641\u0627\u0642 \u0637\u0648\u064a\u0642 \u062e\u062f\u0645\u0627\u062a \u0627\u0644\u062a\u062e\u0644\u064a\u0635 \u0627\u0644\u062c\u0645\u0631\u0643\u064a \u0648\u0627\u0644\u0646\u0642\u0644 \u0648\u0627\u0644\u0634\u062d\u0646 \u0648\u0627\u0644\u062a\u062e\u0632\u064a\u0646 \u0648\u0627\u0644\u062a\u0648\u0635\u064a\u0644 \u0645\u0646 \u0627\u0644\u0628\u0627\u0628 \u0625\u0644\u0649 \u0627\u0644\u0628\u0627\u0628 \u0641\u064a \u0627\u0644\u0633\u0639\u0648\u062f\u064a\u0629 \u0648\u0627\u0644\u062e\u0644\u064a\u062c. \u0645\u0627 \u0627\u0644\u062e\u062f\u0645\u0629 \u0627\u0644\u062a\u064a \u062a\u062d\u062a\u0627\u062c\u0647\u0627\u061f",
}
for key, value in SERVICES.items():
    REPLIES[key] = "\u0646\u0642\u062f\u0645 \u062e\u062f\u0645\u0629 " + value + " \u0641\u064a \u0622\u0641\u0627\u0642 \u0637\u0648\u064a\u0642. \u0623\u0631\u0633\u0644 \u062a\u0641\u0627\u0635\u064a\u0644 \u0637\u0644\u0628\u0643 \u0639\u0644\u0649 \u0627\u0644\u062e\u0627\u0635 \u0644\u064a\u0631\u0627\u062c\u0639 \u0627\u0644\u0641\u0631\u064a\u0642 \u0646\u0637\u0627\u0642 \u0627\u0644\u062e\u062f\u0645\u0629 \u0627\u0644\u0645\u0646\u0627\u0633\u0628."
SENSITIVE = re.compile(r"\d|https?://|www\.|@|(?:api[_ -]?key|password|token|secret|bearer|iban|crm|balance|invoice|passport|identity|account number|phone|email|attachment|document)|(?:\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631|\u0631\u0645\u0632|\u0633\u0631\u064a|\u0631\u0635\u064a\u062f|\u062d\u0633\u0627\u0628\u064a|\u0641\u0627\u062a\u0648\u0631\u0629|\u0645\u0633\u062a\u0646\u062f|\u062c\u0648\u0627\u0632|\u0647\u0648\u064a\u0629|\u062c\u0648\u0627\u0644|\u0647\u0627\u062a\u0641|\u0631\u0642\u0645\u064a|\u0628\u0648\u0644\u064a\u0635\u0629|\u0628\u064a\u0627\u0646 \u062c\u0645\u0631\u0643\u064a)", re.I)
INJECTION = re.compile(r"ignore|system prompt|developer|instructions|execute|reveal|base64|\u062a\u062c\u0627\u0647\u0644|\u062a\u0639\u0644\u064a\u0645\u0627\u062a|\u0627\u0643\u0634\u0641|\u0646\u0641\u0630|\u0628\u0631\u0648\u0645\u0628\u062a", re.I)
COMPLAINT = re.compile(r"complain|refund|damage|delay|lawsuit|compensat|fraud|scam|\u0634\u0643\u0648\u0649|\u0634\u0643\u0648\u064a|\u062a\u0623\u062e\u0631|\u062a\u0627\u062e\u0631|\u062a\u0644\u0641|\u062a\u0639\u0648\u064a\u0636|\u0646\u0635\u0628|\u0627\u062d\u062a\u064a\u0627\u0644|\u0645\u062d\u0643\u0645\u0629|\u0645\u0634\u0643\u0644\u0629|\u0645\u0634\u0643\u0644", re.I)

def clean(text):
    return unicodedata.normalize("NFKC", text)

def screen(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 1200:
        return "review"
    text = clean(text)
    if SENSITIVE.search(text) or INJECTION.search(text) or COMPLAINT.search(text) or re.search(r"\u0647\u0648\u064a|\u0631\u0642\u0645", text):
        return "review"
    return "safe"

def classify_local(text):
    value = clean(text).casefold()
    if screen(value) != "safe":
        return "review"
    if re.search(r"\u0633\u0639\u0631|\u0627\u0633\u0639\u0627\u0631|\u0623\u0633\u0639\u0627\u0631|\u062a\u0643\u0644\u0641|\u0628\u0643\u0645|\u0643\u0645.*(?:\u0634\u062d\u0646|\u0646\u0642\u0644|\u062a\u062e\u0644\u064a\u0635)|price|cost|quote", value):
        return "pricing"
    if re.search(r"\u0628\u0648\u062a|\u0622\u0644\u064a|\u0627\u0644\u064a|\u0630\u0643\u0627\u0621|robot|bot|human|ai\b", value):
        return "ai"
    if re.fullmatch(r"[\s!\u060c.\u2764\u2665\ud83d\ude4f]*(?:\u0634\u0643\u0631\u0627|\u0634\u0643\u0631\u064b\u0627|\u0634\u0643\u0631\u0627\u064b|\u0645\u0634\u0643\u0648\u0631|\u064a\u0639\u0637\u064a\u0643\u0645 \u0627\u0644\u0639\u0627\u0641\u064a\u0629|thanks|thank you)[\s!\u060c.\u2764\u2665\ud83d\ude4f]*", value):
        return "thanks"
    return None

def config(account):
    """Operator-managed deployment configuration. Empty/invalid means disabled."""
    try:
        raw = json.loads(os.getenv("AFAAQ_COMMENT_ACCOUNTS", "{}"))
        entry = raw.get(account, {})
        platform = KNOWN.get(account)
        if (os.getenv("AFAAQ_COMMENTS_ENABLED") != "1" or platform not in SUPPORTED
                or entry.get("platform") != platform or entry.get("mode") not in ("dry_run", "live")
                or not isinstance(entry.get("profile_id"), str) or not entry["profile_id"]
                or type(entry.get("revision")) is not int or entry["revision"] < 1
                or not isinstance(entry.get("owner_ids"), list) or not entry["owner_ids"]
                or any(not isinstance(x, str) or not x for x in entry["owner_ids"])):
            return {"mode": "off", "fingerprint": "off", "revision": 0}
        result = {k: entry[k] for k in ("platform", "mode", "profile_id", "revision", "owner_ids")}
        result["fingerprint"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        return result
    except (ValueError, TypeError, AttributeError, KeyError):
        return {"mode": "off", "fingerprint": "off", "revision": 0}

def normalize(payload, cfg):
    def identifier(value):
        if not isinstance(value, str) or not 0 < len(value) <= 255 or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid comment identity")
        return value
    account, comment, post = (payload.get(k) for k in ("account", "comment", "post"))
    if not all(isinstance(x, dict) for x in (account, comment, post)):
        raise ValueError("Invalid comment envelope")
    row = {"event_id": identifier(payload.get("id")),
           "account_id": identifier(account.get("accountId")),
           "post_id": identifier(comment.get("platformPostId")),
           "comment_id": identifier(comment.get("id")), "question": "", "reason": "", "status": "queued"}
    author = comment.get("author") or {}
    if not isinstance(author, dict):
        author = {}
    reason = ""
    try:
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(payload["timestamp"].replace("Z","+00:00"))).total_seconds()
        fresh = -300 <= age <= 86400
    except (KeyError, ValueError, TypeError, AttributeError):
        fresh = False
    if not fresh:
        reason = "stale_event"
    elif payload.get("test") is not None:
        reason = "test_event"
    elif cfg["mode"] == "off":
        reason = "disabled_or_unsupported"
    elif account.get("platform") != cfg["platform"] or comment.get("platform") != cfg["platform"] or account.get("profileId") != cfg["profile_id"]:
        reason = "account_scope"
    elif author.get("isOwnAccount") is True or author.get("id") in cfg["owner_ids"]:
        reason = "own_comment"
    elif author.get("isOwnAccount") is not False:
        reason = "unknown_author"
    elif not isinstance(author.get("id"), str) or not author["id"]:
        reason = "unknown_author"
    elif comment.get("parentCommentId") or comment.get("isReply") is not False or comment.get("isLive") or comment.get("ad"):
        reason = "unsupported_comment_context"
    elif screen(comment.get("text")) != "safe":
        reason = "human_review"
    if reason:
        row.update(status="held", reason=reason)
    else:
        row["question"] = clean(comment["text"]).strip()
    return row

def render(intent):
    # Model-generated prose never reaches the public surface.
    return REPLIES.get(intent)

