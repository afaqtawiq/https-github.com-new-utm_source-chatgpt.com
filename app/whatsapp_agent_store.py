"""Durable, fail-closed WhatsApp agent queue and transactional outbox.

No database (or application storage) is imported at module import time. Every
operation except ``enqueue`` owns and commits its transaction before returning.
``enqueue`` uses the caller's webhook transaction: no network work belongs there.
A db_factory is a context-manager factory yielding a psycopg-style connection.
All input payloads, document text and diagnostics must already be sanitized.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets

LEASE_SECONDS = 300
MAX_READ_ATTEMPTS = 3
DOCUMENT_REVIEW_TTL_SECONDS = 3600
MAX_DOCUMENT_REVIEW_TTL_SECONDS = 86400
DAILY_MODEL_LIMITS = {"owner_pilot": 10, "routine": 50}
MODEL_BUDGET_NOTICE = ('وصلت رسالتك. وصلنا للحد اليومي للفهم الآلي في التجربة؛ '
                       'يتجدد الساعة ٣ صباحًا بتوقيت السعودية. أرسل سؤالك من جديد بعد ذلك، '
                       'لأن الرسائل المتوقفة لا تُعاد تلقائيًا.')
TERMINAL = frozenset({"sent", "blocked", "uncertain", "failed"})
MODES = frozenset({"off", "owner_pilot", "routine"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNSET = object()


class StateConflict(RuntimeError):
    """A lease, checkpoint or state is stale; do not repeat external work."""


@contextmanager
def database():
    from app.storage import db  # Deliberately lazy: importing this module is safe.
    with db() as connection:
        yield connection


def _time(now=None):
    value = now or datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


def _stamp(value):
    return _time(value).isoformat()


def _json(value, limit=262144):
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError("sanitized data exceeds storage limit")
    return encoded


def _row(row):
    if row is None:
        return None
    result = dict(row)
    for name, fallback in (("payload", {}), ("diagnostics", {}),
                           ("approved_sha256", []), ("acceptance", {})):
        if name in result and isinstance(result[name], str):
            result[name] = json.loads(result[name])
        elif name in result and result[name] is None:
            result[name] = fallback
    return result


def _lock(connection, *, skip=False, of=None):
    # SQLite is only supported by the injected, single-process test adapter.
    if getattr(connection, "dialect", None) == "sqlite":
        return ""
    return " FOR UPDATE" + (" OF " + of if of else "") + (" SKIP LOCKED" if skip else "")


def _identifier(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(name + " must be a nonempty bounded string")
    return value


def _sha(value, *, optional=False):
    if optional and not value:
        return None
    if not isinstance(value, str) or not _SHA256.fullmatch(value.lower()):
        raise ValueError("invalid SHA-256")
    return value.lower()


def _diagnostics(previous, addition):
    merged = dict(previous or {})
    if addition:
        if not isinstance(addition, dict):
            raise ValueError("diagnostics must be a sanitized object")
        merged.update(addition)
    return _json(merged, 32768)


DDL = (
    """CREATE TABLE IF NOT EXISTS whatsapp_agent_settings (
        account_id TEXT PRIMARY KEY, authorization_generation BIGINT NOT NULL DEFAULT 1,
        mode TEXT NOT NULL DEFAULT 'off' CHECK (mode IN ('off','owner_pilot','routine')),
        pilot_sender TEXT, approved_sha256 TEXT NOT NULL DEFAULT '[]',
        acceptance TEXT NOT NULL DEFAULT '{}', accepted_at TIMESTAMPTZ,
        accepted_by TEXT, updated_at TIMESTAMPTZ NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS whatsapp_agent_jobs (
        id BIGSERIAL PRIMARY KEY, account_id TEXT NOT NULL, message_id TEXT NOT NULL,
        event_id TEXT NOT NULL, sender TEXT NOT NULL, conversation_id TEXT NOT NULL,
        authorization_generation BIGINT NOT NULL DEFAULT 0,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK
          (status IN ('pending','processing','ready','sending','sent','blocked','uncertain','failed')),
        read_attempts INTEGER NOT NULL DEFAULT 0 CHECK (read_attempts BETWEEN 0 AND 3),
        lease_token TEXT, lease_until TIMESTAMPTZ,
        document_text TEXT, document_sha256 TEXT, document_status TEXT,
        document_checkpointed_at TIMESTAMPTZ,
        context_source_job_id BIGINT REFERENCES whatsapp_agent_jobs(id),
        review_id TEXT,
        model_started_at TIMESTAMPTZ, model_completed_at TIMESTAMPTZ,
        reply_text TEXT, diagnostics TEXT NOT NULL DEFAULT '{}',
        idempotency_key TEXT NOT NULL UNIQUE,
        created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ,
        UNIQUE(account_id, message_id))""",
    """CREATE TABLE IF NOT EXISTS whatsapp_agent_events (
        account_id TEXT NOT NULL, event_id TEXT NOT NULL,
        job_id BIGINT NOT NULL REFERENCES whatsapp_agent_jobs(id),
        PRIMARY KEY(account_id,event_id))""",
    """CREATE TABLE IF NOT EXISTS whatsapp_agent_outbox (
        job_id BIGINT PRIMARY KEY REFERENCES whatsapp_agent_jobs(id),
        idempotency_key TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK (status IN ('ready','sending','sent','blocked','uncertain','failed')),
        send_token TEXT, send_started_at TIMESTAMPTZ, lease_until TIMESTAMPTZ,
        provider_message_id TEXT, diagnostics TEXT NOT NULL DEFAULT '{}',
        updated_at TIMESTAMPTZ NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS whatsapp_agent_budget_notices (
        account_id TEXT NOT NULL, sender TEXT NOT NULL, window_start TIMESTAMPTZ NOT NULL,
        job_id BIGINT NOT NULL UNIQUE REFERENCES whatsapp_agent_jobs(id),
        PRIMARY KEY(account_id,sender,window_start))""",
    """CREATE TABLE IF NOT EXISTS whatsapp_agent_document_reviews (
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL, sender TEXT NOT NULL,
        conversation_id TEXT NOT NULL, source_job_id BIGINT NOT NULL REFERENCES whatsapp_agent_jobs(id),
        message_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
        reviewed_text TEXT NOT NULL, reviewed_text_sha256 TEXT NOT NULL,
        extraction_sha256 TEXT, authorization_generation BIGINT NOT NULL,
        creator_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('staged','approved','revoked','expired')),
        created_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
        approved_at TIMESTAMPTZ, approved_text_sha256 TEXT,
        approved_through_job_id BIGINT, revoked_at TIMESTAMPTZ)""",
    "CREATE INDEX IF NOT EXISTS whatsapp_agent_claim_idx ON whatsapp_agent_jobs(status,id)",
    "CREATE INDEX IF NOT EXISTS whatsapp_agent_scope_idx ON whatsapp_agent_jobs(account_id,sender,conversation_id,id)",
    "CREATE INDEX IF NOT EXISTS whatsapp_agent_budget_idx ON whatsapp_agent_jobs(account_id,model_started_at)",
    "CREATE INDEX IF NOT EXISTS whatsapp_agent_send_idx ON whatsapp_agent_outbox(status,job_id)",
    "CREATE INDEX IF NOT EXISTS whatsapp_agent_review_scope_idx ON whatsapp_agent_document_reviews(account_id,sender,conversation_id,source_job_id)",
)


def init_storage(*, db_factory=None):
    with (db_factory or database)() as connection:
        for statement in DDL:
            connection.execute(statement)
        # Existing installations fail closed: settings migrate to generation 1,
        # historical jobs to 0. Freshly enqueued jobs capture the current value.
        for table, default in (("whatsapp_agent_settings", 1), ("whatsapp_agent_jobs", 0)):
            if getattr(connection, "dialect", None) == "sqlite":
                names = {row["name"] for row in connection.execute("PRAGMA table_info(" + table + ")").fetchall()}
                if "authorization_generation" not in names:
                    connection.execute("ALTER TABLE " + table +
                        " ADD COLUMN authorization_generation BIGINT NOT NULL DEFAULT " + str(default))
            else:
                connection.execute("ALTER TABLE " + table +
                    " ADD COLUMN IF NOT EXISTS authorization_generation BIGINT NOT NULL DEFAULT " + str(default))
        if getattr(connection, "dialect", None) == "sqlite":
            names = {row["name"] for row in connection.execute("PRAGMA table_info(whatsapp_agent_jobs)").fetchall()}
            if "review_id" not in names:
                connection.execute("ALTER TABLE whatsapp_agent_jobs ADD COLUMN review_id TEXT")
        else:
            connection.execute("ALTER TABLE whatsapp_agent_jobs ADD COLUMN IF NOT EXISTS review_id TEXT")
        stamp = _stamp(None)
        connection.execute("""UPDATE whatsapp_agent_jobs SET status='blocked',
            lease_token=NULL,lease_until=NULL,updated_at=%s,completed_at=%s
            WHERE status IN ('pending','processing','ready') AND EXISTS (
              SELECT 1 FROM whatsapp_agent_settings s WHERE s.account_id=whatsapp_agent_jobs.account_id
                AND s.authorization_generation<>whatsapp_agent_jobs.authorization_generation)""", (stamp, stamp))
        connection.execute("""UPDATE whatsapp_agent_outbox SET status='blocked',lease_until=NULL,
            updated_at=%s WHERE status='ready' AND EXISTS (
              SELECT 1 FROM whatsapp_agent_jobs j WHERE j.id=whatsapp_agent_outbox.job_id AND j.status='blocked')""", (stamp,))


def _settings(connection, account_id, *, now=None, lock=False):
    connection.execute("""INSERT INTO whatsapp_agent_settings(account_id,updated_at)
        VALUES(%s,%s) ON CONFLICT(account_id) DO NOTHING""", (account_id, _stamp(now)))
    return _row(connection.execute(
        "SELECT * FROM whatsapp_agent_settings WHERE account_id=%s" +
        (_lock(connection) if lock else ""), (account_id,)).fetchone())


def get_settings(account_id, *, db_factory=None):
    _identifier(account_id, "account_id")
    with (db_factory or database)() as connection:
        return _settings(connection, account_id)


def update_settings(account_id, *, mode=None, pilot_sender=_UNSET,
                    approved_sha256=None, acceptance=None, accepted_at=_UNSET,
                    accepted_by=_UNSET, expected_generation=None, db_factory=None, now=None):
    """Save explicit authorization metadata; this function never invents approval.

    approved_sha256 describes synthetic input provenance only. No expected answer,
    fixed document text, prompt or response is stored in settings.
    """
    _identifier(account_id, "account_id")
    if expected_generation is not None and (type(expected_generation) is not int or expected_generation < 0):
        raise ValueError("expected_generation must be a nonnegative integer")
    if mode is not None and mode not in MODES:
        raise ValueError("invalid mode")
    if approved_sha256 is not None:
        if not isinstance(approved_sha256, (list, tuple)) or len(approved_sha256) > 100:
            raise ValueError("approved_sha256 must be a bounded list")
        approved_sha256 = sorted({_sha(value) for value in approved_sha256})
    if acceptance is not None:
        if not isinstance(acceptance, dict):
            raise ValueError("acceptance must be an object")
        if set(acceptance) - {"owner_receipt_confirmed", "document_job_id", "followup_job_id",
                              "confirmed_at", "confirmed_by"}:
            raise ValueError("unsupported acceptance field")
    with (db_factory or database)() as connection:
        settings = _settings(connection, account_id, now=now, lock=True)
        if expected_generation is not None and settings["authorization_generation"] != expected_generation:
            raise StateConflict("settings authorization changed; reload before submitting")
        original = dict(settings)
        settings["mode"] = mode if mode is not None else settings["mode"]
        if pilot_sender is not _UNSET:
            settings["pilot_sender"] = _identifier(pilot_sender, "pilot_sender") if pilot_sender else None
        if approved_sha256 is not None:
            settings["approved_sha256"] = approved_sha256
        if acceptance is not None:
            settings["acceptance"] = acceptance
        if accepted_at is not _UNSET:
            settings["accepted_at"] = _stamp(accepted_at) if accepted_at else None
        if accepted_by is not _UNSET:
            settings["accepted_by"] = _identifier(str(accepted_by), "accepted_by") if accepted_by is not None else None
        if settings["mode"] == "owner_pilot" and not settings["pilot_sender"]:
            raise ValueError("owner_pilot requires a pilot_sender")
        changed = any(settings[key] != original[key] for key in
                      ("mode", "pilot_sender", "approved_sha256"))
        if settings["mode"] == "routine":
            if original["mode"] != "routine":
                _validate_acceptance(connection, account_id, settings)
            elif (changed or settings["acceptance"] != original["acceptance"]):
                raise ValueError("routine authorization changes require a new owner pilot")
        settings["authorization_generation"] += int(changed)
        connection.execute("""UPDATE whatsapp_agent_settings SET mode=%s,pilot_sender=%s,
            approved_sha256=%s,acceptance=%s,accepted_at=%s,accepted_by=%s,updated_at=%s,
            authorization_generation=%s WHERE account_id=%s""", (settings["mode"], settings["pilot_sender"],
            _json(settings["approved_sha256"]), _json(settings["acceptance"], 16384),
            settings["accepted_at"], settings["accepted_by"], _stamp(now),
            settings["authorization_generation"], account_id))
        if changed or settings["mode"] == "off":
            # An explicit stop is final for previously queued work. Sending has
            # already crossed the irreversible boundary and is not reclaimed.
            jobs = connection.execute("""SELECT * FROM whatsapp_agent_jobs WHERE account_id=%s
                AND status IN ('pending','processing','ready') ORDER BY id""" + _lock(connection),
                (account_id,)).fetchall()
            for raw in jobs:
                _terminal(connection, _row(raw), "blocked", now,
                          {"reason": "mode_disabled" if settings["mode"] == "off" else "authorization_changed"})
        return _settings(connection, account_id, now=now)


def _validate_acceptance(connection, account_id, settings):
    acceptance = settings["acceptance"]
    if acceptance.get("owner_receipt_confirmed") is not True:
        raise ValueError("routine requires owner receipt confirmation")
    ids = [acceptance.get("document_job_id"), acceptance.get("followup_job_id")]
    if any(type(value) is not int or value <= 0 for value in ids):
        raise ValueError("routine requires document and followup job ids")
    document, followup = (_job(connection, value) for value in ids)
    if (not document or not followup or document["id"] >= followup["id"] or
        document["account_id"] != account_id or followup["account_id"] != account_id or
        document["sender"] != settings["pilot_sender"] or followup["sender"] != settings["pilot_sender"] or
        document["authorization_generation"] != settings["authorization_generation"] or
        followup["authorization_generation"] != settings["authorization_generation"] or
        not _pdf_payload(document["payload"]) or not _followup_payload(followup["payload"]) or
        followup["payload"].get("question_allowed") is not True or
        followup["payload"].get("question_kind") != "document_question" or
        document["context_source_job_id"] is not None or
        document.get("review_id") is not None or followup.get("review_id") is not None or
        document["status"] != "sent" or followup["status"] != "sent" or
        document["document_status"] != "ok" or not document["document_text"] or
        not document["document_sha256"] or not document["model_completed_at"] or
        not followup["model_completed_at"] or
        document["diagnostics"].get("model_success") is not True or
        followup["diagnostics"].get("model_success") is not True or
        document["document_sha256"] not in settings["approved_sha256"] or
        followup["context_source_job_id"] != document["id"] or
        any(document[key] != followup[key] for key in ("sender", "conversation_id"))):
        raise ValueError("routine requires a sent document and its scoped sent followup")


def _pdf_payload(payload):
    """Recognize declared PDFs or the exact normalized absent-MIME file candidate.

    Candidate metadata never proves PDF content: usable status, approved byte
    digest and successful local parsing/checkpoint gates remain mandatory.
    """
    attachments = payload.get("attachments")
    if not (type(payload.get("attachment_count")) is int and payload["attachment_count"] == 1 and
            isinstance(attachments, list) and len(attachments) == 1 and isinstance(attachments[0], dict)):
        return False
    attachment = attachments[0]
    return ((attachment.get("mime") == "application/pdf" and attachment.get("kind") in (None, "file", "absent")) or
            (attachment.get("mime") == "unknown" and attachment.get("kind") == "file" and
             attachment.get("mime_status") == "absent"))


def _followup_payload(payload):
    return type(payload.get("attachment_count")) is int and payload["attachment_count"] == 0 and payload.get("attachments") == []


def _review(connection, review_id, *, lock=False):
    row = _row(connection.execute("SELECT * FROM whatsapp_agent_document_reviews WHERE id=%s" +
                (_lock(connection) if lock else ""), (review_id,)).fetchone())
    if row:
        row.update(review_id=row["id"], text=row["reviewed_text"], text_sha256=row["reviewed_text_sha256"])
    return row


def _review_source_valid(source, settings, now):
    """Known original PDF only; a successful local re-read is supplied by staging.

    Quarantine for unknown provenance is reviewable. Failed reading, uncertain
    extraction and detected sensitive content are not eligible for this path.
    """
    if (not source or source.get("context_source_job_id") is not None or source.get("review_id") or
        source["authorization_generation"] != settings["authorization_generation"] or
        not _enabled(settings, source) or not _pdf_payload(source["payload"]) or
        not isinstance(source.get("document_sha256"), str) or
        not _SHA256.fullmatch(source["document_sha256"]) or
        not source.get("document_checkpointed_at") or
        not ((source["status"] == "sent" and source["document_status"] == "ok") or
             (source["status"] in TERMINAL and source["document_status"] == "quarantined" and
              source["diagnostics"].get("document_reason", source["diagnostics"].get("reason")) ==
              "unapproved_document_provenance"))):
        return False
    current, cutoff = _time(now), _time(now) - timedelta(days=1)
    return all(cutoff < _time(source[key]) <= current for key in
               ("created_at", "document_checkpointed_at"))


def _screen_review_text(text, source_sha256):
    # The exact provenance grant is local to this manager-reviewed excerpt.
    # It never changes account settings or approves other text from this PDF.
    from app import whatsapp_agent_privacy as privacy
    decision = privacy.screen_reviewed_document(text, source_sha256, [source_sha256])
    return bool(decision.allowed and decision.safe_text == text)


def _review_scope(review, source, settings, now):
    if (not review or not _review_source_valid(source, settings, now) or
        review["authorization_generation"] != settings["authorization_generation"] or
        review["source_job_id"] != source["id"] or
        review["source_sha256"] != source["document_sha256"] or
        any(review[key] != source[key] for key in
            ("account_id", "sender", "conversation_id", "message_id")) or
        not _time(review["created_at"]) <= _time(now) < _time(review["expires_at"]) or
        _time(review["expires_at"]) > min(_time(review["created_at"]) + timedelta(days=1),
            _time(source["created_at"]) + timedelta(days=1),
            _time(source["document_checkpointed_at"]) + timedelta(days=1)) or
        hashlib.sha256(review["reviewed_text"].encode()).hexdigest() != review["reviewed_text_sha256"]):
        return False
    return _screen_review_text(review["reviewed_text"], review["source_sha256"])


def _review_valid(review, source, settings, target, now, *, checkpoint=True):
    if (not _review_scope(review, source, settings, now) or review["status"] != "approved" or
        not review["approved_at"] or review["approved_through_job_id"] is None or
        review["approved_text_sha256"] != review["reviewed_text_sha256"] or
        not _time(review["created_at"]) <= _time(review["approved_at"]) <= _time(now) or
        target["id"] <= max(source["id"], review["approved_through_job_id"]) or
        not _time(review["approved_at"]) <= _time(target["created_at"]) <= _time(now) or
        target["authorization_generation"] != review["authorization_generation"] or
        any(target[key] != review[key] for key in ("account_id", "sender", "conversation_id")) or
        not _followup_payload(target["payload"]) or target["payload"].get("question_allowed") is not True):
        return False
    return not checkpoint or (
        target.get("review_id") == review["id"] and target["context_source_job_id"] == source["id"] and
        target["document_status"] == "ok" and target["document_sha256"] == review["source_sha256"] and
        target["document_text"] == review["reviewed_text"] and
        target["document_checkpointed_at"] is not None and
        _time(target["document_checkpointed_at"]) == _time(source["document_checkpointed_at"]))


def _review_permitted(connection, job, settings, now):
    if not job.get("review_id"):
        return False
    review = _review(connection, job["review_id"])
    source = _job(connection, review["source_job_id"]) if review else None
    return _review_valid(review, source, settings, job, now)


def _review_settings(connection, account_id, generation, now):
    _identifier(account_id, "expected_account")
    if type(generation) is not int or generation < 1:
        raise ValueError("expected_generation must be a positive integer")
    settings = _settings(connection, account_id, now=now, lock=True)
    if settings["authorization_generation"] != generation:
        raise StateConflict("settings authorization changed; reload before submitting")
    return settings


def stage_document_review(source_job_id, creator_id, text, *, expected_account,
                          expected_generation, verified_source_sha256, extraction_sha256=None,
                          ttl_seconds=DOCUMENT_REVIEW_TTL_SECONDS, db_factory=None, now=None):
    """Stage exact locally verified nonsensitive excerpts without admitting them.

    The caller must locally fetch and parse the canonical original attachment,
    verify its byte digest, and establish that text contains only ordered whole
    lines of that extraction. This function independently checks DLP and scope.
    No source job, existing inbound message or global hash approval is changed.
    """
    _identifier(creator_id, "creator_id")
    if type(source_job_id) is not int or source_job_id <= 0:
        raise ValueError("source_job_id must be positive")
    verified_source_sha256 = _sha(verified_source_sha256)
    extraction_sha256 = _sha(extraction_sha256, optional=True)
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_DOCUMENT_REVIEW_TTL_SECONDS:
        raise ValueError("review TTL must be between one second and 24 hours")
    if not isinstance(text, str) or not _screen_review_text(text, verified_source_sha256):
        raise ValueError("review text must be exact, bounded and pass local privacy checks")
    now = _time(now)
    with (db_factory or database)() as connection:
        settings = _review_settings(connection, expected_account, expected_generation, now)
        source = _job(connection, source_job_id, lock=True)
        if (not _review_source_valid(source, settings, now) or source["account_id"] != expected_account or
            source["document_sha256"] != verified_source_sha256):
            raise StateConflict("original PDF scope, provenance or availability changed")
        expires_at = min(now + timedelta(seconds=ttl_seconds),
                         _time(source["created_at"]) + timedelta(days=1),
                         _time(source["document_checkpointed_at"]) + timedelta(days=1))
        review_id = secrets.token_hex(32)
        connection.execute("""INSERT INTO whatsapp_agent_document_reviews
            (id,account_id,sender,conversation_id,source_job_id,message_id,source_sha256,
             reviewed_text,reviewed_text_sha256,extraction_sha256,authorization_generation,
             creator_id,status,created_at,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'staged',%s,%s)""",
            (review_id, source["account_id"], source["sender"], source["conversation_id"], source["id"],
             source["message_id"], verified_source_sha256, text, hashlib.sha256(text.encode()).hexdigest(),
             extraction_sha256, expected_generation, creator_id, _stamp(now), _stamp(expires_at)))
        return _review(connection, review_id)


def get_document_review(review_id, creator_id, *, db_factory=None, now=None):
    """Private exact review for its creator, never a diagnostics projection."""
    _identifier(review_id, "review_id")
    _identifier(creator_id, "creator_id")
    with (db_factory or database)() as connection:
        connection.execute("""UPDATE whatsapp_agent_document_reviews SET status='expired'
            WHERE id=%s AND creator_id=%s AND status IN ('staged','approved') AND expires_at<=%s""",
            (review_id, creator_id, _stamp(now)))
        review = _review(connection, review_id)
        return review if review and review["creator_id"] == creator_id else None


def approve_document_review(review_id, creator_id, *, expected_account, expected_generation,
                            expected_text_sha256, expected_source_sha256, db_factory=None, now=None):
    """Approve only the exact staged content/scope shown by the manager UI.

    Settings-row serialization captures an inbound high-watermark atomically:
    even already queued messages with the same timestamp cannot use this grant.
    """
    _identifier(review_id, "review_id")
    _identifier(creator_id, "creator_id")
    expected_text_sha256, expected_source_sha256 = _sha(expected_text_sha256), _sha(expected_source_sha256)
    now = _time(now)
    with (db_factory or database)() as connection:
        settings = _review_settings(connection, expected_account, expected_generation, now)
        review = _review(connection, review_id, lock=True)
        source = _job(connection, review["source_job_id"]) if review else None
        if (not review or review["creator_id"] != creator_id or review["account_id"] != expected_account or
            review["status"] != "staged" or review["reviewed_text_sha256"] != expected_text_sha256 or
            review["source_sha256"] != expected_source_sha256 or not _review_scope(review, source, settings, now)):
            raise StateConflict("review is no longer the exact current staged document")
        watermark = connection.execute("SELECT COALESCE(MAX(id),0) AS n FROM whatsapp_agent_jobs").fetchone()["n"]
        # A new exact excerpt replaces this source's earlier admissions. Old
        # content cannot silently return when the newest review is revoked.
        connection.execute("""UPDATE whatsapp_agent_document_reviews SET status='revoked',revoked_at=%s
            WHERE source_job_id=%s AND account_id=%s AND sender=%s AND conversation_id=%s
              AND authorization_generation=%s AND status='approved' AND id<>%s""",
            (_stamp(now), review["source_job_id"], review["account_id"], review["sender"],
             review["conversation_id"], expected_generation, review_id))
        connection.execute("""UPDATE whatsapp_agent_document_reviews SET status='approved',
            approved_at=%s,approved_text_sha256=%s,approved_through_job_id=%s WHERE id=%s""",
            (_stamp(now), expected_text_sha256, watermark, review_id))
        return _review(connection, review_id)


def revoke_document_review(review_id, creator_id, *, expected_account, expected_generation,
                           db_factory=None, now=None):
    """Fence later model/send admissions; an already in-flight call cannot be undone."""
    _identifier(review_id, "review_id")
    _identifier(creator_id, "creator_id")
    with (db_factory or database)() as connection:
        _review_settings(connection, expected_account, expected_generation, now)
        review = _review(connection, review_id, lock=True)
        if not review or review["creator_id"] != creator_id or review["account_id"] != expected_account:
            raise StateConflict("review is not owned by this manager and account")
        if review["status"] in {"staged", "approved"}:
            connection.execute("""UPDATE whatsapp_agent_document_reviews SET status='revoked',revoked_at=%s
                WHERE id=%s""", (_stamp(now), review_id))
        return _review(connection, review_id)


# Explicit projection makes source, review, settings and active job one statement
# snapshot in the immediate network guards, including under READ COMMITTED.
_REVIEW_FIELDS = ("id", "account_id", "sender", "conversation_id", "source_job_id", "message_id",
    "source_sha256", "reviewed_text", "reviewed_text_sha256", "authorization_generation", "creator_id",
    "status", "created_at", "expires_at", "approved_at", "approved_text_sha256", "approved_through_job_id")
_SOURCE_FIELDS = ("id", "account_id", "sender", "conversation_id", "message_id", "authorization_generation",
    "status", "document_status", "document_sha256", "context_source_job_id", "review_id", "payload",
    "diagnostics", "created_at", "document_checkpointed_at")
_REVIEW_PROJECTION = ",".join(["r." + key + " AS r_" + key for key in _REVIEW_FIELDS] +
                              ["src." + key + " AS src_" + key for key in _SOURCE_FIELDS])
_REVIEW_JOINS = """ LEFT JOIN whatsapp_agent_document_reviews r ON r.id=j.review_id
    LEFT JOIN whatsapp_agent_jobs src ON src.id=r.source_job_id """


def _joined_review_permitted(row, now, *, checkpoint=True):
    if not row or not row.get("r_id"):
        return False
    review = {key: row["r_" + key] for key in _REVIEW_FIELDS}
    source = _row({key: row["src_" + key] for key in _SOURCE_FIELDS}) if row.get("src_id") else None
    settings = {**row, "authorization_generation": row["current_generation"]}
    return _review_valid(review, source, settings, row, now, checkpoint=checkpoint)


def find_review_context(*, account_id, sender, conversation_id, before_job_id,
                        message_id=None, db_factory=None, now=None):
    """Return an approved excerpt only for a future active inbound in exact scope."""
    for name, value in (("account_id", account_id), ("sender", sender), ("conversation_id", conversation_id)):
        _identifier(value, name)
    if type(before_job_id) is not int or before_job_id <= 0:
        raise ValueError("before_job_id must identify the current processing job")
    scope, args = "", [before_job_id, account_id, sender, conversation_id, _stamp(now), _stamp(now)]
    if message_id is not None:
        _identifier(message_id, "message_id")
        scope = " AND r.message_id=%s"
        args.append(message_id)
    with (db_factory or database)() as connection:
        rows = connection.execute("""SELECT j.*,s.mode,s.pilot_sender,s.approved_sha256,
            s.authorization_generation AS current_generation,""" + _REVIEW_PROJECTION + """
            FROM whatsapp_agent_jobs j JOIN whatsapp_agent_settings s ON s.account_id=j.account_id
            JOIN whatsapp_agent_document_reviews r ON r.account_id=j.account_id
              AND r.sender=j.sender AND r.conversation_id=j.conversation_id
            JOIN whatsapp_agent_jobs src ON src.id=r.source_job_id
            WHERE j.id=%s AND j.account_id=%s AND j.sender=%s AND j.conversation_id=%s
              AND j.status='processing' AND j.lease_until>%s
              AND r.status='approved' AND r.expires_at>%s""" + scope +
            " ORDER BY r.source_job_id DESC,r.approved_at DESC,r.id DESC", tuple(args)).fetchall()
    for raw in rows:
        row = _row(raw)
        if _joined_review_permitted(row, now, checkpoint=False):
            return {"id": row["r_source_job_id"], "source_job_id": row["r_source_job_id"],
                    "message_id": row["r_message_id"], "document_text": row["r_reviewed_text"],
                    "document_sha256": row["r_source_sha256"], "document_status": "ok",
                    "document_checkpointed_at": row["src_document_checkpointed_at"],
                    "review_id": row["r_id"], "reviewed_text_sha256": row["r_reviewed_text_sha256"],
                    "approved_hashes": [row["r_source_sha256"]]}
    return None


def enqueue(connection, *, account_id, message_id, event_id, sender,
            conversation_id, payload, now=None):
    """Enqueue in caller transaction; duplicates return the original immutable job.

    A short account settings row lock serializes inserts, including event aliases,
    so committed ordering is stable even for concurrent webhook transactions.
    """
    for name, value in (("account_id", account_id), ("message_id", message_id),
                        ("event_id", event_id), ("sender", sender),
                        ("conversation_id", conversation_id)):
        _identifier(value, name)
    if not isinstance(payload, dict):
        raise ValueError("payload must be a sanitized object")
    encoded = _json(payload)
    settings = _settings(connection, account_id, now=now, lock=True)
    old = connection.execute("""SELECT j.* FROM whatsapp_agent_events e
        JOIN whatsapp_agent_jobs j ON j.id=e.job_id
        WHERE e.account_id=%s AND e.event_id=%s""", (account_id, event_id)).fetchone()
    if old:
        return _row(old)
    stamp = _stamp(now)
    # Stable per account/message, independent of webhook retries or lease owners.
    key = "wa-agent-" + hashlib.sha256(_json([account_id, message_id]).encode()).hexdigest()
    connection.execute("""INSERT INTO whatsapp_agent_jobs
        (account_id,message_id,event_id,sender,conversation_id,payload,idempotency_key,created_at,updated_at,authorization_generation)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(account_id,message_id) DO NOTHING""",
        (account_id, message_id, event_id, sender, conversation_id, encoded, key, stamp, stamp, settings["authorization_generation"]))
    job = _row(connection.execute("SELECT * FROM whatsapp_agent_jobs WHERE account_id=%s AND message_id=%s",
                                  (account_id, message_id)).fetchone())
    connection.execute("""INSERT INTO whatsapp_agent_events(account_id,event_id,job_id)
        VALUES(%s,%s,%s) ON CONFLICT(account_id,event_id) DO NOTHING""", (account_id, event_id, job["id"]))
    if job["status"] == "pending" and not _enabled(settings, job):
        _terminal(connection, job, "blocked", now, {"reason": "mode_or_sender_not_enabled"})
        job = _job(connection, job["id"])
    return job


def _job(connection, job_id, *, lock=False):
    return _row(connection.execute("SELECT * FROM whatsapp_agent_jobs WHERE id=%s" +
                (_lock(connection) if lock else ""), (job_id,)).fetchone())


def _leased(connection, job_id, lease_token, now=None):
    job = _job(connection, job_id, lock=True)
    if (not job or job["status"] != "processing" or not lease_token or
            job["lease_token"] != lease_token or not job["lease_until"] or
            _time(job["lease_until"]) <= _time(now)):
        raise StateConflict("processing lease expired or no longer owned")
    return job


def _enabled(settings, job):
    return settings["mode"] == "routine" or (
        settings["mode"] == "owner_pilot" and settings["pilot_sender"] == job["sender"])


def _terminal(connection, job, status, now, diagnostics=None):
    if status not in TERMINAL:
        raise ValueError("invalid terminal status")
    data = _diagnostics(job["diagnostics"], diagnostics)
    connection.execute("""UPDATE whatsapp_agent_jobs SET status=%s,diagnostics=%s,
        lease_token=NULL,lease_until=NULL,updated_at=%s,completed_at=%s WHERE id=%s""",
        (status, data, _stamp(now), _stamp(now), job["id"]))
    connection.execute("""UPDATE whatsapp_agent_outbox SET status=%s,diagnostics=%s,
        lease_until=NULL,updated_at=%s WHERE job_id=%s""", (status, data, _stamp(now), job["id"]))


def _make_ready(connection, job, now):
    if not job.get("reply_text"):
        raise StateConflict("durable reply text required before outbox creation")
    connection.execute("""INSERT INTO whatsapp_agent_outbox(job_id,idempotency_key,status,updated_at)
        VALUES(%s,%s,'ready',%s) ON CONFLICT(job_id) DO NOTHING""",
        (job["id"], job["idempotency_key"], _stamp(now)))
    connection.execute("""UPDATE whatsapp_agent_jobs SET status='ready',lease_token=NULL,
        lease_until=NULL,updated_at=%s WHERE id=%s""", (_stamp(now), job["id"]))


def _recover(connection, now, account_id=None):
    args = [_stamp(now)]
    scope = ""
    if account_id is not None:
        scope = " AND account_id=%s"
        args.append(account_id)
    rows = connection.execute("""SELECT * FROM whatsapp_agent_jobs
        WHERE status IN ('processing','sending') AND lease_until<=%s""" + scope +
        " ORDER BY id LIMIT 100" + _lock(connection, skip=True), tuple(args)).fetchall()
    for raw in rows:
        job = _row(raw)
        if job["status"] == "sending":
            _terminal(connection, job, "uncertain", now, {"reason": "send_lease_expired"})
        elif job["model_started_at"] and not job["model_completed_at"]:
            _terminal(connection, job, "uncertain", now, {"reason": "model_result_unknown"})
        elif job["model_completed_at"] and job["reply_text"]:
            _make_ready(connection, job, now)
        elif job["read_attempts"] >= MAX_READ_ATTEMPTS:
            _terminal(connection, job, "failed", now, {"reason": "read_attempts_exhausted"})
        else:
            connection.execute("""UPDATE whatsapp_agent_jobs SET status='pending',
                lease_token=NULL,lease_until=NULL,updated_at=%s WHERE id=%s""", (_stamp(now), job["id"]))
    return len(rows)


def recover_expired(*, account_id=None, db_factory=None, now=None):
    with (db_factory or database)() as connection:
        return _recover(connection, _time(now), account_id)


_ORDER = """NOT EXISTS (SELECT 1 FROM whatsapp_agent_jobs earlier
    WHERE earlier.account_id=j.account_id AND earlier.sender=j.sender
      AND earlier.conversation_id=j.conversation_id AND earlier.id<j.id
      AND earlier.status NOT IN ('sent','blocked','uncertain','failed'))"""
_ELIGIBLE = """(s.mode='routine' OR (s.mode='owner_pilot' AND s.pilot_sender=j.sender))
    AND j.authorization_generation=s.authorization_generation"""


def claim_job(*, account_id=None, db_factory=None, now=None):
    """Claim one earliest eligible job, serializing the entire conversation flow."""
    now = _time(now)
    with (db_factory or database)() as connection:
        _recover(connection, now, account_id)
        args = () if account_id is None else (account_id,)
        scope = "" if account_id is None else " AND j.account_id=%s"
        raw = connection.execute("""SELECT j.* FROM whatsapp_agent_jobs j
            JOIN whatsapp_agent_settings s ON s.account_id=j.account_id
            WHERE j.status='pending' AND j.read_attempts<3 AND """ + _ELIGIBLE +
            " AND " + _ORDER + scope + " ORDER BY j.id LIMIT 1" +
            _lock(connection, skip=True, of="j"), args).fetchone()
        if not raw:
            return None
        job = _row(raw)
        connection.execute("""UPDATE whatsapp_agent_jobs SET status='processing',read_attempts=read_attempts+1,
            lease_token=%s,lease_until=%s,updated_at=%s WHERE id=%s""",
            (secrets.token_hex(24), _stamp(now + timedelta(seconds=LEASE_SECONDS)), _stamp(now), job["id"]))
        return _job(connection, job["id"])


def checkpoint_document(job_id, lease_token, *, text, sha256, status, diagnostics=None,
                        context_source_job_id=None, review_id=None, db_factory=None, now=None):
    if not isinstance(text, str) or len(text) > 100000:
        raise ValueError("safe document text must be a bounded string")
    _identifier(status, "document status")
    sha256 = _sha(sha256, optional=not bool(text))
    with (db_factory or database)() as connection:
        settings = None
        if review_id is not None:
            _identifier(review_id, "review_id")
            initial = _job(connection, job_id)
            if not initial:
                raise StateConflict("job does not exist")
            settings = _settings(connection, initial["account_id"], now=now, lock=True)
        job = _leased(connection, job_id, lease_token, now)
        if job["model_started_at"]:
            raise StateConflict("document checkpoint is immutable after model reservation")
        checkpointed_at = _stamp(now)
        if review_id is not None:
            review = _review(connection, review_id)
            source = _job(connection, context_source_job_id) if context_source_job_id is not None else None
            candidate = {**job, "review_id": review_id, "context_source_job_id": context_source_job_id,
                         "document_text": text, "document_sha256": sha256, "document_status": status,
                         "document_checkpointed_at": source["document_checkpointed_at"] if source else None}
            if not _review_valid(review, source, settings, candidate, now):
                raise StateConflict("review no longer authorizes this exact future document context")
            checkpointed_at = source["document_checkpointed_at"]
        elif context_source_job_id is not None:
            source = _job(connection, context_source_job_id)
            if (not source or source["id"] >= job["id"] or source["status"] != "sent" or
                any(source[key] != job[key] for key in ("account_id", "sender", "conversation_id")) or
                source["document_status"] != "ok" or source["document_text"] != text or
                source["document_sha256"] != sha256 or source["context_source_job_id"] is not None or
                not _pdf_payload(source["payload"])):
                raise StateConflict("context source is not a prior matching sent document")
            if _time(source["document_checkpointed_at"]) <= _time(now) - timedelta(days=1):
                raise StateConflict("context source has expired")
            checkpointed_at = source["document_checkpointed_at"]
        connection.execute("""UPDATE whatsapp_agent_jobs SET document_text=%s,document_sha256=%s,
            document_status=%s,document_checkpointed_at=%s,context_source_job_id=%s,review_id=%s,
            diagnostics=%s,updated_at=%s WHERE id=%s""", (text, sha256, status, checkpointed_at,
            context_source_job_id, review_id, _diagnostics(job["diagnostics"], diagnostics), _stamp(now), job_id))
        return _job(connection, job_id)


def reserve_model(job_id, lease_token, *, db_factory=None, now=None):
    """Reserve at most one model attempt. False means never invoke the model.

    Budget count and reservation are serialized per account. A lost response is
    terminal uncertain after lease recovery, never another paid model attempt.
    """
    now = _time(now)
    with (db_factory or database)() as connection:
        initial = _job(connection, job_id)
        if not initial:
            raise StateConflict("job does not exist")
        # Always settings -> job when both locks are needed, matching settings
        # disable/enqueue. This avoids a disable/reservation lock-order cycle.
        settings = _settings(connection, initial["account_id"], now=now, lock=True)
        job = _leased(connection, job_id, lease_token, now)
        if job["model_started_at"]:
            return False
        if not _enabled(settings, job) or job["authorization_generation"] != settings["authorization_generation"]:
            _terminal(connection, job, "blocked", now, {"reason": "mode_or_sender_not_enabled"})
            return False
        if not job["document_checkpointed_at"]:
            raise StateConflict("document/context must be checkpointed before model reservation")
        cutoff = now - timedelta(days=1)
        if _time(job["created_at"]) <= cutoff:
            _terminal(connection, job, "blocked", now, {"reason": "model_job_expired"})
            return False
        if job["context_source_job_id"] is not None and _time(job["document_checkpointed_at"]) <= cutoff:
            _terminal(connection, job, "blocked", now, {"reason": "document_context_expired"})
            return False
        if not _model_input_permitted(job, settings,
                review_authorized=_review_permitted(connection, job, settings, now)):
            has_document = bool(job["document_sha256"] or job["document_text"]) or job["context_source_job_id"] is not None
            reason = (("pilot_provenance_not_approved" if settings["mode"] == "owner_pilot" else "document_provenance_not_approved")
                      if has_document else "ordinary_text_not_eligible")
            _terminal(connection, job, "blocked", now, {"reason": reason})
            return False
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        count = connection.execute("""SELECT COUNT(*) AS n FROM whatsapp_agent_jobs
            WHERE account_id=%s AND model_started_at>=%s AND model_started_at<%s""",
            (job["account_id"], _stamp(start), _stamp(start + timedelta(days=1)))).fetchone()["n"]
        if count >= DAILY_MODEL_LIMITS[settings["mode"]]:
            _budget_exhausted(connection, job, settings, start, now)
            return False
        connection.execute("UPDATE whatsapp_agent_jobs SET model_started_at=%s,updated_at=%s WHERE id=%s",
                           (_stamp(now), _stamp(now), job_id))
        return True


def _budget_exhausted(connection, job, settings, start, now):
    """Claim and persist one local owner notice in the quota transaction.

    The claim is never released after uncertain/blocked delivery or mode changes.
    Existing blocked jobs are never reopened. A new inbound window is required.
    """
    diagnostics = {"reason": "daily_model_budget_exhausted",
                   "model_reason": "daily_model_budget_exhausted",
                   "model_attempted": False, "model_success": False}
    if (settings['mode'] != 'owner_pilot' or settings['pilot_sender'] != job['sender']
            or not start <= _time(job['created_at']) <= now):
        _terminal(connection, job, 'blocked', now, diagnostics)
        return
    claimed = connection.execute("""INSERT INTO whatsapp_agent_budget_notices
        (account_id,sender,window_start,job_id) VALUES(%s,%s,%s,%s)
        ON CONFLICT(account_id,sender,window_start) DO NOTHING RETURNING job_id""",
        (job['account_id'], job['sender'], _stamp(start), job['id'])).fetchone()
    if not claimed:
        diagnostics['budget_notice'] = 'already_claimed'
        _terminal(connection, job, 'blocked', now, diagnostics)
        return
    diagnostics.update(budget_notice='local_notice', budget_notice_window=_stamp(start))
    job['reply_text'] = MODEL_BUDGET_NOTICE
    connection.execute("""UPDATE whatsapp_agent_jobs SET reply_text=%s,diagnostics=%s WHERE id=%s""",
                       (job['reply_text'], _diagnostics(job['diagnostics'], diagnostics), job['id']))
    _make_ready(connection, job, now)


def _budget_notice_current(job, now, *, mode):
    if job.get('diagnostics', {}).get('budget_notice') != 'local_notice':
        return True
    try:
        start = _time(job['diagnostics']['budget_notice_window'])
    except (KeyError, TypeError, ValueError):
        return False
    return (mode == 'owner_pilot' and start == start.replace(hour=0, minute=0, second=0, microsecond=0)
            and start <= _time(now) < start + timedelta(days=1))


def save_model(job_id, lease_token, *, reply_text, diagnostics=None, db_factory=None, now=None):
    _reply(reply_text)
    with (db_factory or database)() as connection:
        job = _leased(connection, job_id, lease_token, now)
        if not job["model_started_at"] or job["model_completed_at"]:
            raise StateConflict("model result requires an uncompleted reservation")
        connection.execute("""UPDATE whatsapp_agent_jobs SET reply_text=%s,model_completed_at=%s,
            diagnostics=%s,updated_at=%s WHERE id=%s""", (reply_text, _stamp(now),
            _diagnostics(job["diagnostics"], diagnostics), _stamp(now), job_id))
        return _job(connection, job_id)


def _reply(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 12000:
        raise ValueError("reply text must be nonempty and bounded")


def prepare_reply(job_id, lease_token, *, reply_text=None, terminal_status=None,
                  diagnostics=None, db_factory=None, now=None):
    with (db_factory or database)() as connection:
        job = _leased(connection, job_id, lease_token, now)
        if terminal_status is not None:
            if terminal_status not in {"blocked", "failed", "uncertain"}:
                raise ValueError("invalid processing terminal status")
            _terminal(connection, job, terminal_status, now, diagnostics)
            return _job(connection, job_id)
        if job["model_started_at"] and not job["model_completed_at"]:
            raise StateConflict("model reservation has no durable result")
        if reply_text is not None:
            _reply(reply_text)
            if job["model_completed_at"] and reply_text != job["reply_text"]:
                raise StateConflict("saved model result cannot be replaced")
            job["reply_text"] = reply_text
        _reply(job["reply_text"])
        connection.execute("UPDATE whatsapp_agent_jobs SET reply_text=%s,diagnostics=%s WHERE id=%s",
                           (job["reply_text"], _diagnostics(job["diagnostics"], diagnostics), job_id))
        _make_ready(connection, job, now)
        return _job(connection, job_id)


def claim_send(*, account_id=None, db_factory=None, now=None):
    """Commit ready -> sending BEFORE making a network request. Never reclaim it."""
    now = _time(now)
    # Release recovery locks before acquiring settings, preserving lock order.
    recover_expired(account_id=account_id, db_factory=db_factory, now=now)
    with (db_factory or database)() as connection:
        scope = "" if account_id is None else " AND j.account_id=%s"
        args = () if account_id is None else (account_id,)
        raw = connection.execute("""SELECT j.* FROM whatsapp_agent_jobs j
            JOIN whatsapp_agent_outbox o ON o.job_id=j.id
            JOIN whatsapp_agent_settings s ON s.account_id=j.account_id
            WHERE j.status='ready' AND o.status='ready' AND """ + _ELIGIBLE +
            " AND " + _ORDER + scope + " ORDER BY j.id LIMIT 1", args).fetchone()
        if not raw:
            return None
        candidate = _row(raw)
        settings = _settings(connection, candidate["account_id"], now=now, lock=True)
        # Recheck while locked: another worker may already have sent this row.
        raw = connection.execute("""SELECT j.* FROM whatsapp_agent_jobs j
            JOIN whatsapp_agent_outbox o ON o.job_id=j.id
            WHERE j.id=%s AND j.status='ready' AND o.status='ready'""" +
            _lock(connection, skip=True, of="j,o"), (candidate["id"],)).fetchone()
        if not raw:
            return None
        job = _row(raw)
        if not _enabled(settings, job) or job["authorization_generation"] != settings["authorization_generation"]:
            _terminal(connection, job, "blocked", now, {"reason": "mode_or_sender_not_enabled"})
            return None
        if not _budget_notice_current(job, now, mode=settings['mode']):
            _terminal(connection, job, 'blocked', now, {'reason': 'budget_notice_window_expired'})
            return None
        if (job["model_started_at"] or job.get("review_id")) and not _model_input_permitted(job, settings,
                review_authorized=_review_permitted(connection, job, settings, now)):
            has_document = bool(job["document_sha256"] or job["document_text"]) or job["context_source_job_id"] is not None
            reason = (("pilot_provenance_not_approved" if settings["mode"] == "owner_pilot" else "document_provenance_not_approved")
                      if has_document else "ordinary_text_not_eligible")
            _terminal(connection, job, "blocked", now, {"reason": reason})
            return None
        token = secrets.token_hex(24)
        until = _stamp(now + timedelta(seconds=LEASE_SECONDS))
        connection.execute("""UPDATE whatsapp_agent_outbox SET status='sending',send_token=%s,
            send_started_at=%s,lease_until=%s,updated_at=%s WHERE job_id=%s""",
            (token, _stamp(now), until, _stamp(now), job["id"]))
        connection.execute("""UPDATE whatsapp_agent_jobs SET status='sending',lease_token=NULL,
            lease_until=%s,updated_at=%s WHERE id=%s""", (until, _stamp(now), job["id"]))
        result = _job(connection, job["id"])
        result["send_token"] = token
        return result


def finish_send(job_id, send_token, *, status, provider_message_id=None,
                diagnostics=None, db_factory=None, now=None):
    if status not in TERMINAL:
        raise ValueError("send outcome must be sent, blocked, uncertain or failed")
    with (db_factory or database)() as connection:
        job = _job(connection, job_id, lock=True)
        outbox = connection.execute("SELECT * FROM whatsapp_agent_outbox WHERE job_id=%s" +
                                    _lock(connection), (job_id,)).fetchone()
        if (not job or not outbox or job["status"] != "sending" or
                outbox["status"] != "sending" or not send_token or outbox["send_token"] != send_token):
            raise StateConflict("send is terminal or no longer owned; never resend")
        if provider_message_id is not None:
            _identifier(provider_message_id, "provider_message_id")
        _terminal(connection, job, status, now, diagnostics)
        connection.execute("UPDATE whatsapp_agent_outbox SET provider_message_id=%s WHERE job_id=%s",
                           (provider_message_id, job_id))
        return _job(connection, job_id)


def recent_context(*, account_id, sender, conversation_id, before_job_id=None,
                   message_id=None, max_age_seconds=86400, db_factory=None, now=None):
    """Return the latest original approved PDF, never an inherited followup.

    This separately approved document cache uses current sender/scope, current
    digest approval and the original read timestamp. A routine-mode transition
    does not discard a still-approved PDF solely because its generation changed.
    An explicit message_id is an exact stored platform-ID lookup, never an event
    alias or a fallback to latest. That quote path additionally requires a current
    active target and same-generation source, like recent_attachment_outcome.
    """
    current = _time(now)
    max_age_seconds = max(1, min(int(max_age_seconds), 86400))
    stamp, cutoff = _stamp(current), _stamp(current-timedelta(seconds=max_age_seconds))
    args = [account_id, sender, conversation_id, cutoff, stamp]
    scope = ""
    if before_job_id is not None:
        scope = " AND j.id<%s"
        args.append(before_job_id)
    if message_id is not None:
        _identifier(message_id, "message_id")
        if type(before_job_id) is not int or before_job_id <= 0:
            raise ValueError("quoted context requires the current processing before_job_id")
        scope += """ AND j.message_id=%s AND j.authorization_generation=s.authorization_generation
            AND j.created_at>%s AND j.created_at<=%s
            AND EXISTS (SELECT 1 FROM whatsapp_agent_jobs target WHERE target.id=%s
              AND target.account_id=j.account_id AND target.sender=j.sender
              AND target.conversation_id=j.conversation_id
              AND target.authorization_generation=s.authorization_generation
              AND target.status='processing' AND target.lease_until>%s
              AND target.created_at>%s AND target.created_at<=%s)"""
        args.extend((message_id, cutoff, stamp, before_job_id, stamp, cutoff, stamp))
    with (db_factory or database)() as connection:
        rows = connection.execute("""SELECT j.*,s.approved_sha256
            FROM whatsapp_agent_jobs j JOIN whatsapp_agent_settings s ON s.account_id=j.account_id
            WHERE j.account_id=%s AND j.sender=%s AND j.conversation_id=%s AND j.status='sent'
              AND NOT EXISTS (SELECT 1 FROM whatsapp_agent_budget_notices n WHERE n.job_id=j.id)
              AND j.document_status='ok' AND j.document_text<>'' AND j.document_sha256 IS NOT NULL
              AND j.context_source_job_id IS NULL
              AND j.document_checkpointed_at>%s AND j.document_checkpointed_at<=%s
              AND (s.mode='routine' OR (s.mode='owner_pilot' AND s.pilot_sender=j.sender))""" +
            scope + " ORDER BY j.id DESC LIMIT 32", tuple(args)).fetchall()
    for raw in rows:
        row = _row(raw)
        approved = row.pop("approved_sha256")
        if row["document_sha256"] in approved and _pdf_payload(row["payload"]):
            return row
    return None


def _original_attachment_predicate(connection):
    """Filter sanitized attachment metadata in SQL, before any row limit."""
    if getattr(connection, "dialect", None) == "sqlite":
        return """json_type(j.payload,'$.attachment_count')='integer'
            AND json_extract(j.payload,'$.attachment_count')>0
            AND json_type(j.payload,'$.attachments')='array'
            AND EXISTS (SELECT 1 FROM json_each(j.payload,'$.attachments') attachment
              WHERE attachment.type='object' AND attachment.value<>'{}')"""
    return """CASE WHEN jsonb_typeof(j.payload::jsonb->'attachment_count')='number'
            AND (j.payload::jsonb->>'attachment_count') ~ '^[0-9]+$'
          THEN (j.payload::jsonb->>'attachment_count')::numeric>0 ELSE FALSE END
        AND EXISTS (SELECT 1 FROM jsonb_array_elements(
          CASE WHEN jsonb_typeof(j.payload::jsonb->'attachments')='array'
            THEN j.payload::jsonb->'attachments' ELSE '[]'::jsonb END) attachment(value)
          WHERE jsonb_typeof(attachment.value)='object' AND attachment.value<>'{}'::jsonb)"""


def recent_attachment_outcome(*, account_id, sender, conversation_id, before_job_id,
                              message_id=None, max_age_seconds=86400, db_factory=None, now=None):
    """Return the latest original completed attachment checkpoint's ID/status.

    The active target and source must share the current enabled authorization
    generation, exact conversation scope and recent non-future timestamps. The
    read outcome is authoritative independently of outgoing reply delivery: an
    uncertain/failed/blocked reply must not resurrect an older successful PDF.
    Only metadata is selected; document content, captions and URLs never leave
    this helper. Callers must compare source IDs with their approved PDF cache.
    A supplied message_id matches only that stored platform ID, never an event
    alias, and an unknown quote returns None without falling back to latest.
    """
    for name, value in (("account_id", account_id), ("sender", sender),
                        ("conversation_id", conversation_id)):
        _identifier(value, name)
    if type(before_job_id) is not int or before_job_id <= 0:
        raise ValueError("before_job_id must identify the current processing job")
    current = _time(now)
    max_age_seconds = max(1, min(int(max_age_seconds), 86400))
    stamp, cutoff = _stamp(current), _stamp(current - timedelta(seconds=max_age_seconds))
    args = [before_job_id, account_id, sender, conversation_id, stamp, cutoff, stamp,
            cutoff, stamp, cutoff, stamp]
    message_filter = ""
    if message_id is not None:
        _identifier(message_id, "message_id")
        message_filter = " AND j.message_id=%s"
        args.append(message_id)
    with (db_factory or database)() as connection:
        raw = connection.execute("""SELECT j.id,j.document_status
            FROM whatsapp_agent_jobs j
            JOIN whatsapp_agent_settings s ON s.account_id=j.account_id
            JOIN whatsapp_agent_jobs target ON target.id=%s
              AND target.account_id=j.account_id AND target.sender=j.sender
              AND target.conversation_id=j.conversation_id
            WHERE j.account_id=%s AND j.sender=%s AND j.conversation_id=%s
              AND target.authorization_generation=s.authorization_generation
              AND target.status='processing' AND target.lease_until>%s
              AND target.created_at>%s AND target.created_at<=%s
              AND j.id<target.id AND j.created_at>%s AND j.created_at<=%s
              AND j.document_checkpointed_at>%s AND j.document_checkpointed_at<=%s
              AND j.context_source_job_id IS NULL
              AND j.document_status IN ('ok','quarantined','unavailable')
              AND """ + _ELIGIBLE + " AND " + _original_attachment_predicate(connection) +
            message_filter + " ORDER BY j.id DESC LIMIT 1", tuple(args)).fetchone()
    return {"id": raw["id"], "document_status": raw["document_status"]} if raw else None


MAX_EXCHANGES = 4
MAX_EXCHANGE_QUESTION_CHARS = 1500
MAX_EXCHANGE_REPLY_CHARS = 2500
MAX_EXCHANGE_TOTAL_CHARS = 8000
_HISTORY_URL = re.compile(r"(?:[a-z][a-z0-9+.-]{1,20}://|\bwww\.|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,63}\b)", re.I)


def recent_exchanges(*, account_id, sender, conversation_id, before_job_id,
                     limit=MAX_EXCHANGES, max_age_seconds=86400, db_factory=None, now=None):
    """Return small, whole, text-only sent pairs for this active target job.

    Scope and generation are checked with the actual target and current settings
    in one SQL snapshot. Document-derived pairs are deliberately excluded: PDF
    context has its own provenance-bound path. Caller must re-screen both texts
    before use; the flags here are eligibility metadata, not content validation.
    Returned pairs are chronological, with ISO UTC times and no provider/media
    metadata. Oversized or URL-bearing pairs are skipped, never truncated.
    """
    for name, value in (("account_id", account_id), ("sender", sender),
                        ("conversation_id", conversation_id)):
        _identifier(value, name)
    if type(before_job_id) is not int or before_job_id <= 0:
        raise ValueError("before_job_id must identify the current processing job")
    limit = max(1, min(int(limit), MAX_EXCHANGES))
    max_age_seconds = max(1, min(int(max_age_seconds), 86400))
    stamp = _stamp(now)
    cutoff = _stamp(_time(now) - timedelta(seconds=max_age_seconds))
    with (db_factory or database)() as connection:
        rows = connection.execute("""SELECT j.id AS job_id,j.account_id,j.sender,j.conversation_id,
            j.authorization_generation,j.status,j.created_at,j.completed_at,j.reply_text,j.payload
            FROM whatsapp_agent_jobs j
            JOIN whatsapp_agent_settings s ON s.account_id=j.account_id
            JOIN whatsapp_agent_jobs target ON target.id=%s
              AND target.account_id=j.account_id AND target.sender=j.sender
              AND target.conversation_id=j.conversation_id
            WHERE j.account_id=%s AND j.sender=%s AND j.conversation_id=%s
              AND target.authorization_generation=s.authorization_generation
              AND target.status='processing' AND target.lease_until>%s
              AND target.created_at>%s AND target.created_at<=%s
              AND j.id<target.id AND j.status='sent'
              AND NOT EXISTS (SELECT 1 FROM whatsapp_agent_budget_notices n WHERE n.job_id=j.id)
              AND j.created_at>%s AND j.created_at<=%s
              AND j.completed_at>%s AND j.completed_at<=%s
              AND j.document_status='none'
              AND (j.document_text IS NULL OR j.document_text='')
              AND j.document_sha256 IS NULL AND j.context_source_job_id IS NULL
              AND """ + _ELIGIBLE + " ORDER BY j.id DESC LIMIT 32",
            (before_job_id, account_id, sender, conversation_id, stamp, cutoff, stamp,
             cutoff, stamp, cutoff, stamp)).fetchall()
    result, total = [], 0
    for raw in rows:
        row = _row(raw)
        payload = row.pop("payload")
        question, reply = payload.get("question"), row["reply_text"]
        if (payload.get("question_allowed") is not True or not _followup_payload(payload) or
            not isinstance(question, str) or not question.strip() or
            not isinstance(reply, str) or not reply.strip() or
            len(question) > MAX_EXCHANGE_QUESTION_CHARS or len(reply) > MAX_EXCHANGE_REPLY_CHARS or
            _HISTORY_URL.search(question) or _HISTORY_URL.search(reply)):
            continue
        size = len(question) + len(reply)
        if total + size > MAX_EXCHANGE_TOTAL_CHARS:
            break
        row["question"] = question
        row["created_at"], row["completed_at"] = _stamp(row["created_at"]), _stamp(row["completed_at"])
        result.append(row)
        total += size
        if len(result) >= limit:
            break
    return list(reversed(result))


def get_job(job_id, *, db_factory=None):
    with (db_factory or database)() as connection:
        return _job(connection, job_id)


def list_jobs(*, account_id=None, limit=50, db_factory=None):
    limit = max(1, min(int(limit), 200))
    args = (limit,) if account_id is None else (account_id, limit)
    scope = "" if account_id is None else " WHERE account_id=%s"
    with (db_factory or database)() as connection:
        return [_row(row) for row in connection.execute("SELECT * FROM whatsapp_agent_jobs" +
                    scope + " ORDER BY id DESC LIMIT %s", args).fetchall()]


def get_outbox(job_id, *, db_factory=None):
    with (db_factory or database)() as connection:
        return _row(connection.execute("SELECT * FROM whatsapp_agent_outbox WHERE job_id=%s",
                                       (job_id,)).fetchone())


def _model_input_permitted(job, settings, *, review_authorized=False):
    """Distinguish approved document evidence from screened no-document text.

    The source-absent exception cannot reinterpret any attached document or
    inherited context as ordinary text. A document question with no source may
    ask the model to clarify absence, never fabricate a document or supply the
    PDF/followup evidence required for routine activation.
    """
    has_document = bool(job["document_text"] or job["document_sha256"]) or job["context_source_job_id"] is not None
    if job.get("review_id"):
        return bool(review_authorized)
    if has_document:
        return (job["document_status"] == "ok" and bool(job["document_text"]) and
                job["document_sha256"] in settings["approved_sha256"])
    payload = job.get("payload") or {}
    question = payload.get("question")
    return (job["document_status"] == "none" and _followup_payload(payload) and
            payload.get("question_allowed") is True and payload.get("question_kind") in {"operations", "conversation", "document_question"} and
            isinstance(question, str) and bool(question.strip()))


def _guard_permitted(row, *, model, review_authorized=False):
    if not row or not _enabled(row, row):
        return False
    if model or row["model_started_at"] or row.get("review_id"):
        return _model_input_permitted(row, row, review_authorized=review_authorized)
    # Local safe failure replies are permitted without a model reservation;
    # rejected attachment hashes alone do not become document content.
    return not row["document_text"] or (
        row["document_status"] == "ok" and row["document_sha256"] in row["approved_sha256"])


def model_authorized(job_id, lease_token, *, db_factory=None, now=None):
    """Read guard immediately before one reserved model request; never reserves.

    One joined SELECT gives a single statement snapshot at READ COMMITTED. No
    settings/job locks are acquired in the opposite order to mutation paths.
    Authorization is a point-in-time check, not a lock held across network I/O.
    """
    if not lease_token:
        return False
    with (db_factory or database)() as connection:
        row = _row(connection.execute("""SELECT j.*,s.mode,s.pilot_sender,s.approved_sha256,
            s.authorization_generation AS current_generation,""" + _REVIEW_PROJECTION + """
            FROM whatsapp_agent_jobs j
            JOIN whatsapp_agent_settings s ON s.account_id=j.account_id""" + _REVIEW_JOINS + """
            WHERE j.id=%s AND j.status='processing' AND j.lease_token=%s
              AND j.authorization_generation=s.authorization_generation
              AND j.lease_until>%s AND j.model_started_at IS NOT NULL
              AND j.created_at>%s
              AND (j.context_source_job_id IS NULL OR j.document_checkpointed_at>%s)
              AND j.model_completed_at IS NULL""",
            (job_id, lease_token, _stamp(now), _stamp(_time(now)-timedelta(days=1)),
             _stamp(_time(now)-timedelta(days=1)))).fetchone())
        return bool(_guard_permitted(row, model=True,
            review_authorized=_joined_review_permitted(row, now)))


def send_authorized(job_id, send_token, *, db_factory=None, now=None):
    """Read guard immediately before the one outbox request; never reclaims it.

    The settings, job and outbox are read in one statement snapshot. Both leases
    must be unexpired, and the durable send token must still own ``sending``.
    A False result must not result in network I/O or an automatic send retry.
    """
    if not send_token:
        return False
    with (db_factory or database)() as connection:
        row = _row(connection.execute("""SELECT j.*,s.mode,s.pilot_sender,s.approved_sha256,
            s.authorization_generation AS current_generation,""" + _REVIEW_PROJECTION + """
            FROM whatsapp_agent_jobs j
            JOIN whatsapp_agent_settings s ON s.account_id=j.account_id
            JOIN whatsapp_agent_outbox o ON o.job_id=j.id""" + _REVIEW_JOINS + """
            WHERE j.id=%s AND j.status='sending' AND o.status='sending'
              AND j.authorization_generation=s.authorization_generation
              AND o.send_token=%s AND j.lease_until>%s AND o.lease_until>%s
              AND (j.context_source_job_id IS NULL OR j.document_checkpointed_at>%s)""",
            (job_id, send_token, _stamp(now), _stamp(now),
             _stamp(_time(now)-timedelta(days=1)))).fetchone())
        return bool(row and _budget_notice_current(row, now, mode=row['mode'])
                    and _guard_permitted(row, model=False,
                        review_authorized=_joined_review_permitted(row, now)))


def claim_legacy(connection, *, account_id, message_id, event_id, sender,
                 conversation_id, now=None):
    """Claim identity ownership for the legacy lane, never agent work.

    Call inside the receiver's existing conversation-advisory transaction, before
    claiming its legacy event. The same settings lock as enqueue serializes both
    message and event ownership across lanes. Only identity, not body/URLs, is
    retained. False means another lane/event already owns this message.
    """
    for name, value in (("account_id", account_id), ("message_id", message_id),
                        ("event_id", event_id), ("sender", sender),
                        ("conversation_id", conversation_id)):
        _identifier(value, name)
    settings = _settings(connection, account_id, now=now, lock=True)
    if connection.execute("""SELECT job_id FROM whatsapp_agent_events
        WHERE account_id=%s AND event_id=%s""", (account_id, event_id)).fetchone():
        return False
    existing = connection.execute("""SELECT id FROM whatsapp_agent_jobs
        WHERE account_id=%s AND message_id=%s""", (account_id, message_id)).fetchone()
    if existing:
        # Remember the alias without touching the existing job or its state.
        connection.execute("""INSERT INTO whatsapp_agent_events(account_id,event_id,job_id)
            VALUES(%s,%s,%s) ON CONFLICT(account_id,event_id) DO NOTHING""",
            (account_id, event_id, existing["id"]))
        return False
    stamp = _stamp(now)
    key = "wa-agent-" + hashlib.sha256(_json([account_id, message_id]).encode()).hexdigest()
    inserted = connection.execute("""INSERT INTO whatsapp_agent_jobs
        (account_id,message_id,event_id,sender,conversation_id,payload,status,diagnostics,
         idempotency_key,authorization_generation,created_at,updated_at,completed_at)
        VALUES(%s,%s,%s,%s,%s,%s,'blocked',%s,%s,%s,%s,%s,%s)
        ON CONFLICT(account_id,message_id) DO NOTHING RETURNING id""",
        (account_id, message_id, event_id, sender, conversation_id,
         _json({"legacy_owned": True}), _json({"reason": "legacy_lane_owned"}), key,
         settings["authorization_generation"], stamp, stamp, stamp)).fetchone()
    if not inserted:
        return False
    connection.execute("""INSERT INTO whatsapp_agent_events(account_id,event_id,job_id)
        VALUES(%s,%s,%s)""", (account_id, event_id, inserted["id"]))
    return True
