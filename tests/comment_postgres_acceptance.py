"""PostgreSQL acceptance: isolated random schema on explicit test database only."""
import os, sys, uuid, json
from pathlib import Path
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest
from app import comment_store as s, comment_policy as p
from test_comment_responder import ACCOUNT, payload, configured

@pytest.fixture
def db_factory(configured):
    url=os.environ["AFAAQ_TEST_DATABASE_URL"]
    schema="comment_test_"+uuid.uuid4().hex
    with psycopg.connect(url,autocommit=True) as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    @contextmanager
    def database():
        with psycopg.connect(url,row_factory=dict_row) as c:
            c.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            yield c
    try:
        s.init_storage(database)
        yield database
    finally:
        with psycopg.connect(url,autocommit=True) as c:
            c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

def live(monkeypatch):
    value=json.loads(os.environ["AFAAQ_COMMENT_ACCOUNTS"])
    value[ACCOUNT]["mode"]="live"
    monkeypatch.setenv("AFAAQ_COMMENT_ACCOUNTS",json.dumps(value))

def test_durable_dedup_and_concurrency(db_factory):
    event=payload()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:s.enqueue(event,db_factory),range(8)))
    assert sum(not r["duplicate"] for r in results)==1
    event["id"]="alias"
    assert s.enqueue(event,db_factory)["duplicate"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims=list(pool.map(lambda _:s.claim(ACCOUNT,db_factory),range(4)))
    assert sum(bool(x) for x in claims)==1

def test_changed_generation_blocks(db_factory,monkeypatch):
    s.enqueue(payload(),db_factory);job=s.claim(ACCOUNT,db_factory)
    value=json.loads(os.environ["AFAAQ_COMMENT_ACCOUNTS"])
    value[ACCOUNT]["revision"]=2
    monkeypatch.setenv("AFAAQ_COMMENT_ACCOUNTS",json.dumps(value))
    assert not s.authorized(job,db_factory=db_factory)
    assert s.reserve_send(job,p.REPLIES["thanks"],db_factory) is None

def test_disable_blocks(db_factory,monkeypatch):
    s.enqueue(payload(),db_factory);job=s.claim(ACCOUNT,db_factory)
    monkeypatch.setenv("AFAAQ_COMMENTS_ENABLED","0")
    assert not s.reserve_model(job,db_factory)
    assert not s.authorized(job,db_factory=db_factory)

def test_one_outbox_uncertain_reconciliation(db_factory,monkeypatch):
    live(monkeypatch);s.enqueue(payload(),db_factory);job=s.claim(ACCOUNT,db_factory)
    reply=p.REPLIES["thanks"]
    assert s.reserve_send(job,reply,db_factory)
    assert s.reserve_send(job,reply,db_factory) is None
    s.complete_send(job,"uncertain",db_factory=db_factory)
    assert s.claim(ACCOUNT,db_factory) is None
    assert not s.reconcile(job["id"],"provider",{},db_factory)
    evidence={"account_id":ACCOUNT,"post_id":job["post_id"],"parent_id":job["comment_id"],
              "message":reply,"is_owner":True}
    assert s.reconcile(job["id"],"provider",evidence,db_factory)
    with db_factory() as c:
        assert c.execute("SELECT status FROM afaaq_comment_outbox").fetchone()["status"]=="sent"

def test_send_crash_never_retries(db_factory,monkeypatch):
    live(monkeypatch);s.enqueue(payload(),db_factory);job=s.claim(ACCOUNT,db_factory)
    assert s.reserve_send(job,p.REPLIES["thanks"],db_factory)
    with db_factory() as c:c.execute("UPDATE afaaq_comment_jobs SET lease_until=NOW()-INTERVAL '1 second'")
    assert s.claim(ACCOUNT,db_factory) is None
    with db_factory() as c:
        assert c.execute("SELECT status FROM afaaq_comment_jobs").fetchone()["status"]=="uncertain"
        assert c.execute("SELECT status FROM afaaq_comment_outbox").fetchone()["status"]=="uncertain"

def test_model_budget(db_factory):
    for i in range(51):
        event=payload();event["id"]=str(i);event["comment"]["id"]=str(i)
        s.enqueue(event,db_factory);job=s.claim(ACCOUNT,db_factory)
        assert s.reserve_model(job,db_factory)==(i<50)
        assert not s.reserve_model(job,db_factory)
        s.finish(job,"held",db_factory=db_factory)

def test_rate_reservation_serialized(db_factory,monkeypatch):
    live(monkeypatch);jobs=[]
    for i in range(12):
        event=payload();event["id"]=str(i);event["comment"]["id"]=str(i)
        s.enqueue(event,db_factory);jobs.append(s.claim(ACCOUNT,db_factory))
    with ThreadPoolExecutor(max_workers=4) as pool:
        keys=list(pool.map(lambda job:s.reserve_send(job,p.REPLIES["thanks"],db_factory),jobs))
    assert sum(bool(k) for k in keys)==10

def test_unsafe_text_not_persisted(db_factory):
    s.enqueue(payload("password secret 0555555555"),db_factory)
    with db_factory() as c:row=c.execute("SELECT * FROM afaaq_comment_jobs").fetchone()
    assert row["question"]=="" and row["status"]=="held"
    assert s.claim(ACCOUNT,db_factory) is None


def test_expired_processing_never_reclaims(db_factory):
    s.enqueue(payload(),db_factory);job=s.claim(ACCOUNT,db_factory)
    assert s.reserve_model(job,db_factory)
    with db_factory() as c:c.execute("UPDATE afaaq_comment_jobs SET lease_until=NOW()-INTERVAL '1 second'")
    assert s.claim(ACCOUNT,db_factory) is None
    with db_factory() as c:
        assert c.execute("SELECT status FROM afaaq_comment_jobs").fetchone()["status"]=="held"

def test_old_revision_cannot_restore_revocation(db_factory,monkeypatch):
    original=os.environ["AFAAQ_COMMENT_ACCOUNTS"]
    s.enqueue(payload(),db_factory);job=s.claim(ACCOUNT,db_factory)
    monkeypatch.setenv("AFAAQ_COMMENTS_ENABLED","0")
    assert not s.authorized(job,db_factory=db_factory)
    monkeypatch.setenv("AFAAQ_COMMENTS_ENABLED","1")
    assert not s.authorized(job,db_factory=db_factory)
    assert s.claim(ACCOUNT,db_factory) is None

def test_daily_rate_limit(db_factory,monkeypatch):
    live(monkeypatch)
    for i in range(51):
        event=payload();event["id"]=str(i);event["comment"]["id"]=str(i)
        s.enqueue(event,db_factory);job=s.claim(ACCOUNT,db_factory)
        key=s.reserve_send(job,p.REPLIES["thanks"],db_factory)
        assert bool(key)==(i<50)
        if key:s.complete_send(job,"sent","reply-"+str(i),db_factory)
        with db_factory() as c:
            c.execute("UPDATE afaaq_comment_outbox SET created_at=NOW()-INTERVAL '2 hours'")

def test_stale_queue_holds(db_factory):
    s.enqueue(payload(),db_factory)
    with db_factory() as c:c.execute("UPDATE afaaq_comment_jobs SET created_at=NOW()-INTERVAL '2 days'")
    assert s.claim(ACCOUNT,db_factory) is None

if __name__=="__main__":
    if not os.environ.get("AFAAQ_TEST_DATABASE_URL"):
        raise SystemExit("AFAAQ_TEST_DATABASE_URL required; no production fallback")
    raise SystemExit(pytest.main([__file__,"-q"]))

