"""PostgreSQL comment jobs, leases and durable one-attempt outbox."""
import hashlib
import uuid
from app import comment_policy as policy

def database():
    from app.storage import db
    return db()

def init_storage(db_factory=None):
    with (db_factory or database)() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS afaaq_comment_settings(
            account_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
            generation BIGINT NOT NULL DEFAULT 1, revision BIGINT NOT NULL DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS afaaq_comment_jobs(
            id BIGSERIAL PRIMARY KEY, account_id TEXT NOT NULL, post_id TEXT NOT NULL,
            comment_id TEXT NOT NULL, generation BIGINT NOT NULL, fingerprint TEXT NOT NULL,
            question TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
            reply TEXT NOT NULL DEFAULT '', token TEXT, lease_until TIMESTAMPTZ,
            model_started_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(account_id,post_id,comment_id))""")
        c.execute("ALTER TABLE afaaq_comment_jobs ADD COLUMN IF NOT EXISTS author_id TEXT NOT NULL DEFAULT ''")
        c.execute("ALTER TABLE afaaq_comment_jobs ADD COLUMN IF NOT EXISTS identity_verified_at TIMESTAMPTZ")
        c.execute("""CREATE TABLE IF NOT EXISTS afaaq_comment_events(
            event_id TEXT PRIMARY KEY, job_id BIGINT NOT NULL REFERENCES afaaq_comment_jobs(id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS afaaq_comment_outbox(
            job_id BIGINT PRIMARY KEY REFERENCES afaaq_comment_jobs(id), account_id TEXT NOT NULL,
            token TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
            provider_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        c.execute("CREATE INDEX IF NOT EXISTS afaaq_comment_claim_idx ON afaaq_comment_jobs(status,created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS afaaq_comment_rate_idx ON afaaq_comment_outbox(account_id,created_at)")

def settings(c, account, cfg):
    # Every path takes this account lock before job locks. Configuration revocation
    # invalidates both queued and leased jobs before another reservation is made.
    c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("afaaq-comments:" + account,))
    c.execute("""INSERT INTO afaaq_comment_settings(account_id,fingerprint,revision)
        VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""", (account,cfg["fingerprint"],cfg["revision"]))
    row = c.execute("SELECT * FROM afaaq_comment_settings WHERE account_id=%s FOR UPDATE",(account,)).fetchone()
    if row["fingerprint"] != cfg["fingerprint"]:
        if cfg["mode"] != "off" and cfg["revision"] <= row["revision"]:
            return row
        row = c.execute("""UPDATE afaaq_comment_settings SET fingerprint=%s,generation=generation+1,
            revision=GREATEST(revision,%s) WHERE account_id=%s RETURNING *""",
            (cfg["fingerprint"],cfg["revision"],account)).fetchone()
        c.execute("""UPDATE afaaq_comment_jobs SET status='held',reason='configuration_changed',question=''
            WHERE account_id=%s AND status IN ('queued','processing')""",(account,))
    return row

def enqueue(payload, db_factory=None):
    account = (payload.get("account") or {}).get("accountId") if isinstance(payload.get("account"),dict) else None
    cfg = policy.config(account)
    incoming = policy.normalize(payload,cfg)
    with (db_factory or database)() as c:
        s = settings(c,incoming["account_id"],cfg)
        c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",("comment-event:"+incoming["event_id"],))
        event = c.execute("SELECT job_id FROM afaaq_comment_events WHERE event_id=%s",(incoming["event_id"],)).fetchone()
        if event:
            return {"ok":True,"duplicate":True}
        job = c.execute("""INSERT INTO afaaq_comment_jobs
            (account_id,post_id,comment_id,generation,fingerprint,question,status,reason,author_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(account_id,post_id,comment_id) DO NOTHING RETURNING id""",
            (incoming["account_id"],incoming["post_id"],incoming["comment_id"],s["generation"],
             cfg["fingerprint"],incoming["question"],incoming["status"],incoming["reason"],incoming["author_id"])).fetchone()
        duplicate = not job
        if not job:
            job = c.execute("""SELECT id FROM afaaq_comment_jobs
                WHERE account_id=%s AND post_id=%s AND comment_id=%s""",
                (incoming["account_id"],incoming["post_id"],incoming["comment_id"])).fetchone()
        c.execute("INSERT INTO afaaq_comment_events(event_id,job_id) VALUES(%s,%s)",(incoming["event_id"],job["id"]))
    return {"ok":True,"duplicate":duplicate,"comment_job_id":job["id"]}

def claim(account, db_factory=None):
    cfg = policy.config(account)
    with (db_factory or database)() as c:
        s = settings(c,account,cfg)
        c.execute("""UPDATE afaaq_comment_jobs SET status='held',question='',reason='stale_job'
            WHERE account_id=%s AND status='queued' AND created_at<NOW()-INTERVAL '24 hours'""",(account,))
        # A crash after send reservation can have reached the provider.
        c.execute("""UPDATE afaaq_comment_outbox SET status='uncertain'
            WHERE job_id IN (SELECT id FROM afaaq_comment_jobs WHERE account_id=%s
            AND status='sending' AND lease_until<=NOW()) AND status='sending'""",(account,))
        c.execute("""UPDATE afaaq_comment_jobs SET status='uncertain',question='',reason='send_lease_expired'
            WHERE account_id=%s AND status='sending' AND lease_until<=NOW()""",(account,))
        # Never repeat a possibly billed model call after a process crash.
        c.execute("""UPDATE afaaq_comment_jobs SET status='held',question='',reason='processing_lease_expired'
            WHERE account_id=%s AND status='processing' AND lease_until<=NOW()""",(account,))
        if cfg["mode"] == "off" or s["fingerprint"] != cfg["fingerprint"]:
            return None
        row = c.execute("""SELECT * FROM afaaq_comment_jobs WHERE account_id=%s
            AND generation=%s AND status='queued' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1""",
            (account,s["generation"])).fetchone()
        if not row:
            return None
        token = uuid.uuid4().hex
        return c.execute("""UPDATE afaaq_comment_jobs SET status='processing',token=%s,
            lease_until=NOW()+INTERVAL '90 seconds' WHERE id=%s RETURNING *""",(token,row["id"])).fetchone()

def current(c, job, status="processing"):
    cfg = policy.config(job["account_id"])
    s = settings(c,job["account_id"],cfg)
    row = c.execute("""SELECT * FROM afaaq_comment_jobs WHERE id=%s AND token=%s
        AND status=%s AND lease_until>NOW() AND generation=%s AND fingerprint=%s FOR UPDATE""",
        (job["id"],job["token"],status,s["generation"],cfg["fingerprint"])).fetchone()
    return row if cfg["mode"] != "off" else None

def finish(job, status, reason="", reply="", db_factory=None):
    with (db_factory or database)() as c:
        if not current(c,job):
            return False
        c.execute("""UPDATE afaaq_comment_jobs SET status=%s,reason=%s,reply=%s,question=''
            WHERE id=%s""",(status,reason,reply,job["id"]))
    return True

def reserve_model(job, db_factory=None):
    with (db_factory or database)() as c:
        # Separate global budget: max 50 requests/day and 256 output tokens/request.
        c.execute("SELECT pg_advisory_xact_lock(hashtext('afaaq-comment-model-budget'))")
        row = current(c,job)
        if not row or row["model_started_at"] or not identity_current(c,row):
            return False
        count = c.execute("""SELECT count(*) AS n FROM afaaq_comment_jobs
            WHERE model_started_at>NOW()-INTERVAL '24 hours'""").fetchone()["n"]
        if count >= 50:
            return False
        c.execute("UPDATE afaaq_comment_jobs SET model_started_at=NOW() WHERE id=%s",(job["id"],))
    return True

def authorized(job, status="processing", db_factory=None):
    with (db_factory or database)() as c:
        row = current(c,job,status)
        return bool(row and identity_current(c,row))

def identity_current(c, row):
    return bool(c.execute("""SELECT id FROM afaaq_comment_jobs WHERE id=%s AND author_id<>''
        AND identity_verified_at>NOW()-INTERVAL '60 seconds'""",(row["id"],)).fetchone())

def record_identity(job, evidence, db_factory=None):
    with (db_factory or database)() as c:
        row=current(c,job)
        cfg=policy.config(job["account_id"])
        if not row or not isinstance(evidence,dict):
            return False
        expected={k:row[k] for k in ("account_id","post_id","comment_id","author_id")}
        expected.update(owner_id=cfg.get("youtube_owner_id"),
            question_sha256=hashlib.sha256(row["question"].encode()).hexdigest(),
            basis="authenticated_author_id_vs_verified_owner")
        if evidence != expected or not row["author_id"] or row["author_id"] in cfg["owner_ids"]:
            return False
        c.execute("""UPDATE afaaq_comment_jobs SET identity_verified_at=NOW(),reason='identity_verified'
            WHERE id=%s""",(row["id"],))
    return True

def reserve_send(job, reply, db_factory=None):
    with (db_factory or database)() as c:
        row = current(c,job)
        cfg=policy.config(job["account_id"])
        if not row or not identity_current(c,row) or cfg["mode"] != "live" or cfg.get("reply_mode") != "reviewed" or reply not in policy.REPLIES.values():
            return None
        counts = c.execute("""SELECT count(*) AS daily,
            count(*) FILTER (WHERE created_at>NOW()-INTERVAL '1 hour') AS hourly
            FROM afaaq_comment_outbox WHERE account_id=%s AND created_at>NOW()-INTERVAL '24 hours'""",
            (job["account_id"],)).fetchone()
        if counts["hourly"] >= 10 or counts["daily"] >= 50:
            c.execute("UPDATE afaaq_comment_jobs SET status='held',reason='rate_limit',question='' WHERE id=%s",(job["id"],))
            return None
        key = "afaaq-comment-" + hashlib.sha256(
            ("\0".join(job[k] for k in ("account_id","post_id","comment_id"))).encode()).hexdigest()
        c.execute("""INSERT INTO afaaq_comment_outbox(job_id,account_id,token,idempotency_key,status)
            VALUES(%s,%s,%s,%s,'sending')""",(job["id"],job["account_id"],job["token"],key))
        c.execute("""UPDATE afaaq_comment_jobs SET status='sending',reply=%s,question='',
            lease_until=NOW()+INTERVAL '60 seconds' WHERE id=%s""",(reply,job["id"]))
    return key

def complete_send(job, status, provider_id=None, db_factory=None):
    if status not in ("sent","rejected","uncertain","held"):
        raise ValueError("Invalid send result")
    with (db_factory or database)() as c:
        # Completion is evidence recording, not a new send. Preserve evidence even
        # if configuration was revoked while the network request was in flight.
        c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",("afaaq-comments:"+job["account_id"],))
        row = c.execute("SELECT * FROM afaaq_comment_outbox WHERE job_id=%s AND token=%s FOR UPDATE",
                        (job["id"],job["token"])).fetchone()
        if not row or row["status"] not in ("sending","uncertain"):
            return False
        c.execute("UPDATE afaaq_comment_outbox SET status=%s,provider_id=%s WHERE job_id=%s",
                  (status,provider_id,job["id"]))
        c.execute("UPDATE afaaq_comment_jobs SET status=%s,question='' WHERE id=%s",(status,job["id"]))
    return True

def reconcile(job_id, provider_id, evidence, db_factory=None):
    """Positive exact evidence only. No retry or clearing an ambiguous outcome."""
    with (db_factory or database)() as c:
        row = c.execute("""SELECT j.*,o.provider_id FROM afaaq_comment_jobs j
            JOIN afaaq_comment_outbox o ON o.job_id=j.id WHERE j.id=%s""",(job_id,)).fetchone()
        if not row or row["status"] != "uncertain":
            return False
        if (not isinstance(evidence,dict) or evidence.get("account_id") != row["account_id"]
                or evidence.get("post_id") != row["post_id"] or evidence.get("parent_id") != row["comment_id"]
                or evidence.get("message") != row["reply"] or evidence.get("is_owner") is not True
                or not isinstance(provider_id,str) or not provider_id):
            return False
    return complete_send(row,"sent",provider_id,db_factory)

def review_queue(account, db_factory=None):
    if account not in policy.KNOWN:
        raise ValueError("Unapproved account")
    with (db_factory or database)() as c:
        return c.execute("""SELECT id,account_id,post_id,comment_id,status,reason,reply,created_at
            FROM afaaq_comment_jobs WHERE account_id=%s ORDER BY id DESC LIMIT 100""",(account,)).fetchall()

