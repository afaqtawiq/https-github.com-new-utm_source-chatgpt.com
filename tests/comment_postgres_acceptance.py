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
from test_comment_identity import provider_page
from app import comment_identity

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

def verified_claim(database):
    job=s.claim(ACCOUNT,database)
    if job:
        proof=comment_identity.evidence(provider_page(job),job,p.config(ACCOUNT))
        assert proof and s.record_identity(job,proof,database)
    return job

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
    s.enqueue(payload(),db_factory);job=verified_claim(db_factory)
    value=json.loads(os.environ["AFAAQ_COMMENT_ACCOUNTS"])
    value[ACCOUNT]["revision"]=2
    monkeypatch.setenv("AFAAQ_COMMENT_ACCOUNTS",json.dumps(value))
    assert not s.authorized(job,db_factory=db_factory)
    assert s.reserve_send(job,p.REPLIES["thanks"],db_factory) is None

def test_disable_blocks(db_factory,monkeypatch):
    s.enqueue(payload(),db_factory);job=verified_claim(db_factory)
    monkeypatch.setenv("AFAAQ_COMMENTS_ENABLED","0")
    assert not s.reserve_model(job,db_factory)
    assert not s.authorized(job,db_factory=db_factory)

def test_one_outbox_uncertain_reconciliation(db_factory,monkeypatch):
    live(monkeypatch);s.enqueue(payload(),db_factory);job=verified_claim(db_factory)
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
    live(monkeypatch);s.enqueue(payload(),db_factory);job=verified_claim(db_factory)
    assert s.reserve_send(job,p.REPLIES["thanks"],db_factory)
    with db_factory() as c:c.execute("UPDATE afaaq_comment_jobs SET lease_until=NOW()-INTERVAL '1 second'")
    assert s.claim(ACCOUNT,db_factory) is None
    with db_factory() as c:
        assert c.execute("SELECT status FROM afaaq_comment_jobs").fetchone()["status"]=="uncertain"
        assert c.execute("SELECT status FROM afaaq_comment_outbox").fetchone()["status"]=="uncertain"

def test_model_budget(db_factory):
    for i in range(51):
        event=payload();event["id"]=str(i);event["comment"]["id"]=str(i)
        s.enqueue(event,db_factory);job=verified_claim(db_factory)
        assert s.reserve_model(job,db_factory)==(i<50)
        assert not s.reserve_model(job,db_factory)
        s.finish(job,"held",db_factory=db_factory)

def test_rate_reservation_serialized(db_factory,monkeypatch):
    live(monkeypatch);jobs=[]
    for i in range(12):
        event=payload();event["id"]=str(i);event["comment"]["id"]=str(i)
        s.enqueue(event,db_factory);jobs.append(verified_claim(db_factory))
    with ThreadPoolExecutor(max_workers=4) as pool:
        keys=list(pool.map(lambda job:s.reserve_send(job,p.REPLIES["thanks"],db_factory),jobs))
    assert sum(bool(k) for k in keys)==10

def test_unsafe_text_not_persisted(db_factory):
    s.enqueue(payload("password secret 0555555555"),db_factory)
    with db_factory() as c:row=c.execute("SELECT * FROM afaaq_comment_jobs").fetchone()
    assert row["question"]=="" and row["status"]=="held"
    assert s.claim(ACCOUNT,db_factory) is None


def test_expired_processing_never_reclaims(db_factory):
    s.enqueue(payload(),db_factory);job=verified_claim(db_factory)
    assert s.reserve_model(job,db_factory)
    with db_factory() as c:c.execute("UPDATE afaaq_comment_jobs SET lease_until=NOW()-INTERVAL '1 second'")
    assert s.claim(ACCOUNT,db_factory) is None
    with db_factory() as c:
        assert c.execute("SELECT status FROM afaaq_comment_jobs").fetchone()["status"]=="held"

def test_old_revision_cannot_restore_revocation(db_factory,monkeypatch):
    original=os.environ["AFAAQ_COMMENT_ACCOUNTS"]
    s.enqueue(payload(),db_factory);job=verified_claim(db_factory)
    monkeypatch.setenv("AFAAQ_COMMENTS_ENABLED","0")
    assert not s.authorized(job,db_factory=db_factory)
    monkeypatch.setenv("AFAAQ_COMMENTS_ENABLED","1")
    assert not s.authorized(job,db_factory=db_factory)
    assert s.claim(ACCOUNT,db_factory) is None

def test_daily_rate_limit(db_factory,monkeypatch):
    live(monkeypatch)
    for i in range(51):
        event=payload();event["id"]=str(i);event["comment"]["id"]=str(i)
        s.enqueue(event,db_factory);job=verified_claim(db_factory)
        key=s.reserve_send(job,p.REPLIES["thanks"],db_factory)
        assert bool(key)==(i<50)
        if key:s.complete_send(job,"sent","reply-"+str(i),db_factory)
        with db_factory() as c:
            c.execute("UPDATE afaaq_comment_outbox SET created_at=NOW()-INTERVAL '2 hours'")

def test_stale_queue_holds(db_factory):
    s.enqueue(payload(),db_factory)
    with db_factory() as c:c.execute("UPDATE afaaq_comment_jobs SET created_at=NOW()-INTERVAL '2 days'")
    assert s.claim(ACCOUNT,db_factory) is None


def test_identity_proof_required_for_model_and_send(db_factory,monkeypatch):
    live(monkeypatch)
    event=payload();del event["comment"]["author"]["isOwnAccount"]
    s.enqueue(event,db_factory);job=s.claim(ACCOUNT,db_factory)
    assert job["author_id"]=="customer"
    assert not s.reserve_model(job,db_factory)
    assert s.reserve_send(job,p.REPLIES["thanks"],db_factory) is None
    proof=comment_identity.evidence(provider_page(job),job,p.config(ACCOUNT))
    assert s.record_identity(job,proof,db_factory)
    assert s.reserve_model(job,db_factory)
    assert s.reserve_send(job,p.REPLIES["thanks"],db_factory)

@pytest.mark.parametrize("case",["own","wrong_account","wrong_post","wrong_comment","changed_text","missing_owner","incomplete_page"])
def test_unverified_identity_never_reserves(db_factory,case):
    event=payload();del event["comment"]["author"]["isOwnAccount"]
    s.enqueue(event,db_factory);job=s.claim(ACCOUNT,db_factory)
    page=provider_page(job);cfg=p.config(ACCOUNT)
    if case=="own":page["comments"][0]["from"]["id"]="owner"
    elif case=="wrong_account":page["meta"]["accountId"]="wrong"
    elif case=="wrong_post":page["meta"]["postId"]="wrong"
    elif case=="wrong_comment":page["comments"][0]["id"]="wrong"
    elif case=="changed_text":page["comments"][0]["message"]="changed"
    elif case=="missing_owner":cfg["youtube_owner_id"]=""
    elif case=="incomplete_page":page["pagination"]["hasMore"]=True
    proof=comment_identity.evidence(page,job,cfg)
    assert proof is None and not s.record_identity(job,proof,db_factory)
    assert not s.reserve_model(job,db_factory)
    s.finish(job,"held","identity_unverified",db_factory=db_factory)
    assert s.enqueue(event,db_factory)["duplicate"]
    assert s.claim(ACCOUNT,db_factory) is None

def test_identity_proof_expiry_and_generation(db_factory,monkeypatch):
    s.enqueue(payload(),db_factory);job=verified_claim(db_factory)
    with db_factory() as c:c.execute("UPDATE afaaq_comment_jobs SET identity_verified_at=NOW()-INTERVAL '61 seconds'")
    assert not s.reserve_model(job,db_factory)
    assert not s.authorized(job,db_factory=db_factory)

def test_absent_ownership_worker_deduplicates(db_factory,monkeypatch):
    import asyncio, httpx
    from app import comment_responder
    live(monkeypatch);monkeypatch.setenv("ZERNIO_API_KEY","synthetic-test-only")
    event=payload();del event["comment"]["author"]["isOwnAccount"]
    result=s.enqueue(event,db_factory)
    calls=[]
    def handler(request):
        calls.append(request.method)
        if request.method=="GET":
            with db_factory() as c:
                job=c.execute("SELECT * FROM afaaq_comment_jobs WHERE id=%s",(result["comment_job_id"],)).fetchone()
            return httpx.Response(200,json=provider_page(job))
        return httpx.Response(200,json={"success":True,"data":{"commentId":"synthetic-reply"}})
    async def classify(question):
        assert calls==["GET"]
        return "shipping"
    assert asyncio.run(comment_responder.tick(db_factory=db_factory,classifier=classify,transport=httpx.MockTransport(handler)))
    assert calls==["GET","GET","POST"]
    assert s.enqueue(event,db_factory)["duplicate"]
    event["id"]="redelivery-alias"
    assert s.enqueue(event,db_factory)["duplicate"]
    assert not asyncio.run(comment_responder.tick(db_factory=db_factory,classifier=classify,transport=httpx.MockTransport(handler)))

def test_contextual_mode_has_no_send_reservation(db_factory,monkeypatch):
    live(monkeypatch)
    value=json.loads(os.environ["AFAAQ_COMMENT_ACCOUNTS"])
    value[ACCOUNT]["reply_mode"]="contextual_draft"
    monkeypatch.setenv("AFAAQ_COMMENT_ACCOUNTS",json.dumps(value))
    s.enqueue(payload(),db_factory);job=verified_claim(db_factory)
    assert s.reserve_send(job,p.REPLIES["thanks"],db_factory) is None


@pytest.mark.parametrize('approved',[True,False])
def test_contextual_full_worker_durable_send(db_factory,monkeypatch,approved):
    import asyncio, httpx
    from app import comment_responder as worker
    contextual_mode(monkeypatch);monkeypatch.setenv('ZERNIO_API_KEY','synthetic')
    event=payload();s.enqueue(event,db_factory)
    calls=[]
    def handler(request):
        calls.append(request.method)
        if request.method=='GET':
            with db_factory() as c:job=c.execute('SELECT * FROM afaaq_comment_jobs').fetchone()
            return httpx.Response(200,json=provider_page(job))
        assert approved
        assert json.loads(request.content)['message']=='Shipping is one of our services.'
        return httpx.Response(200,json={'success':True,'data':{'commentId':'synthetic'}})
    async def draft(q):return 'Shipping is one of our services.'
    async def validate(q,r):return approved
    assert asyncio.run(worker.tick(db_factory=db_factory,drafter=draft,validator=validate,transport=httpx.MockTransport(handler)))
    assert calls==(['GET','GET','POST'] if approved else ['GET'])
    with db_factory() as c:
        row=c.execute('SELECT * FROM afaaq_comment_jobs').fetchone()
        assert row['status']==('sent' if approved else 'held')
        assert row['model_call_units']==2
        assert c.execute('SELECT count(*) AS n FROM afaaq_comment_outbox').fetchone()['n']==int(approved)
    assert s.enqueue(event,db_factory)['duplicate']
    assert s.claim(ACCOUNT,db_factory) is None

def contextual_mode(monkeypatch):
    live(monkeypatch)
    value=json.loads(os.environ['AFAAQ_COMMENT_ACCOUNTS'])
    value[ACCOUNT]['reply_mode']='contextual_auto'
    monkeypatch.setenv('AFAAQ_COMMENT_ACCOUNTS',json.dumps(value))

def test_contextual_send_requires_exact_validated_text(db_factory,monkeypatch):
    contextual_mode(monkeypatch)
    s.enqueue(payload(),db_factory);job=verified_claim(db_factory)
    reply='Shipping is one of our services.'
    assert s.reserve_send(job,reply,db_factory) is None
    assert not s.record_validation(job,reply,db_factory)
    assert s.reserve_model(job,db_factory)
    assert not s.record_validation(job,'Shipping is free.',db_factory)
    assert s.record_validation(job,reply,db_factory)
    assert s.reserve_send(job,reply+' Please share details privately.',db_factory) is None
    assert s.reserve_send(job,reply,db_factory)
    assert s.reserve_send(job,reply,db_factory) is None

def test_contextual_two_call_budget(db_factory,monkeypatch):
    contextual_mode(monkeypatch)
    for i in range(26):
        event=payload();event['id']=str(i);event['comment']['id']=str(i)
        s.enqueue(event,db_factory);job=verified_claim(db_factory)
        assert s.reserve_model(job,db_factory)==(i<25)
        assert not s.reserve_model(job,db_factory)
        s.finish(job,'held',db_factory=db_factory)

@pytest.mark.parametrize('change',['disable','expire','revision'])
def test_contextual_validation_cannot_bypass_fences(db_factory,monkeypatch,change):
    contextual_mode(monkeypatch)
    s.enqueue(payload(),db_factory);job=verified_claim(db_factory)
    reply='Shipping is one of our services.'
    assert s.reserve_model(job,db_factory) and s.record_validation(job,reply,db_factory)
    if change=='disable':monkeypatch.setenv('AFAAQ_COMMENTS_ENABLED','0')
    elif change=='expire':
        with db_factory() as c:c.execute("UPDATE afaaq_comment_jobs SET identity_verified_at=NOW()-INTERVAL '61 seconds'")
    else:
        value=json.loads(os.environ['AFAAQ_COMMENT_ACCOUNTS']);value[ACCOUNT]['revision']=2
        monkeypatch.setenv('AFAAQ_COMMENT_ACCOUNTS',json.dumps(value))
    assert s.reserve_send(job,reply,db_factory) is None

if __name__=="__main__":
    if not os.environ.get("AFAAQ_TEST_DATABASE_URL"):
        raise SystemExit("AFAAQ_TEST_DATABASE_URL required; no production fallback")
    raise SystemExit(pytest.main([__file__,"-q"]))

