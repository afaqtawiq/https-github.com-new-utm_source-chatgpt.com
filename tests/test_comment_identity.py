import asyncio
import copy
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
import httpx
import pytest
from app import comment_identity as identity, comment_policy as policy, comment_responder as worker
from test_comment_responder import ACCOUNT, configured, payload, prepare_worker

def identity_job():
    return {"id":1,"account_id":ACCOUNT,"post_id":"post","comment_id":"comment",
            "author_id":"customer","question":"Do you offer shipping?","token":"lease"}

def provider_page(job=None):
    job=job or identity_job()
    return {"meta":{"accountId":job["account_id"],"platform":"youtube","postId":job["post_id"],
                    "lastUpdated":datetime.now(timezone.utc).isoformat()},
            "pagination":{"hasMore":False},
            "comments":[{"id":job["comment_id"],"platform":"youtube","message":job["question"],
                "from":{"id":job["author_id"]},"parentId":None,"isHidden":False,"canReply":True}]}

def test_absent_read_flag_resolved_by_independent_owner(configured):
    proof=identity.evidence(provider_page(),identity_job(),configured)
    assert proof["author_id"]=="customer"
    assert proof["owner_id"]=="owner"
    assert proof["basis"]=="authenticated_author_id_vs_verified_owner"

@pytest.mark.parametrize("case",["owner","true_flag","null_flag","string_flag","missing_author","different_author",
    "missing_meta","wrong_account","wrong_platform","wrong_post","wrong_comment","wrong_comment_platform",
    "changed_text","hidden","missing_hidden","cannot_reply","missing_can_reply","reply","missing_parent",
    "missing_pagination","more_pages","cursor","absent_comment","duplicate_comment","missing_freshness",
    "old_cache","future_cache","unknown_owner","unverified_owner","conflicting_owner","oversized_page"])
def test_ambiguous_evidence_holds(configured,case):
    data=provider_page();job=identity_job();cfg=dict(configured)
    comment=data["comments"][0]
    if case=="owner":comment["from"]["id"]=job["author_id"]="owner"
    elif case=="true_flag":comment["from"]["isOwner"]=True
    elif case=="null_flag":comment["from"]["isOwner"]=None
    elif case=="string_flag":comment["from"]["isOwner"]="false"
    elif case=="missing_author":del comment["from"]["id"]
    elif case=="different_author":comment["from"]["id"]="other"
    elif case=="missing_meta":del data["meta"]
    elif case=="wrong_account":data["meta"]["accountId"]="other"
    elif case=="wrong_platform":data["meta"]["platform"]="tiktok"
    elif case=="wrong_post":data["meta"]["postId"]="other"
    elif case=="wrong_comment":comment["id"]="other"
    elif case=="wrong_comment_platform":comment["platform"]="tiktok"
    elif case=="changed_text":comment["message"]="changed"
    elif case=="hidden":comment["isHidden"]=True
    elif case=="missing_hidden":del comment["isHidden"]
    elif case=="cannot_reply":comment["canReply"]=False
    elif case=="missing_can_reply":del comment["canReply"]
    elif case=="reply":comment["parentId"]="parent"
    elif case=="missing_parent":del comment["parentId"]
    elif case=="missing_pagination":del data["pagination"]
    elif case=="more_pages":data["pagination"]["hasMore"]=True
    elif case=="cursor":data["pagination"]["cursor"]="opaque-next"
    elif case=="absent_comment":data["comments"]=[]
    elif case=="duplicate_comment":data["comments"].append(dict(comment))
    elif case=="missing_freshness":del data["meta"]["lastUpdated"]
    elif case=="old_cache":data["meta"]["lastUpdated"]=(datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat()
    elif case=="future_cache":data["meta"]["lastUpdated"]=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
    elif case=="unknown_owner":cfg["youtube_owner_id"]=""
    elif case=="unverified_owner":cfg["owner_verification_ref"]=""
    elif case=="conflicting_owner":cfg["youtube_owner_id"]="different"
    elif case=="oversized_page":data["comments"]*=101
    assert identity.evidence(data,job,cfg) is None

def test_conflicting_false_owner_is_never_external(configured):
    job=identity_job();job["author_id"]="owner"
    data=provider_page(job);data["comments"][0]["from"]["isOwner"]=False
    assert identity.evidence(data,job,configured) is None

def test_unknown_webhook_owner_queues_verification_only(configured):
    event=payload();del event["comment"]["author"]["isOwnAccount"]
    row=policy.normalize(event,configured)
    assert row["status"]=="queued" and row["reason"]=="identity_verification_required"
    assert row["author_id"]=="customer"

@pytest.mark.parametrize("verified",[True,False])
def test_worker_identity_before_model(configured,monkeypatch,verified):
    job=prepare_worker(monkeypatch,configured)
    job["question"]="Do you offer shipping?"
    order=[]
    monkeypatch.setattr(worker.store,"reserve_model",Mock(return_value=True))
    async def classifier(question):
        order.append("model")
        assert order[0]=="read"
        return "shipping"
    def handler(request):
        if request.method=="GET":
            order.append("read")
            return httpx.Response(200,json=provider_page(job) if verified else {"comments":[]})
        order.append("send")
        return httpx.Response(200,json={"success":True,"data":{"commentId":"reply"}})
    asyncio.run(worker.tick(classifier=classifier,transport=httpx.MockTransport(handler)))
    if verified:
        assert order==["read","model","read","send"]
    else:
        assert order==["read"]
        worker.store.reserve_model.assert_not_called()
        worker.store.reserve_send.assert_not_called()

def test_contextual_generation_is_review_only(configured,monkeypatch):
    job=prepare_worker(monkeypatch,configured)
    cfg=dict(configured,mode="live",reply_mode="contextual_draft")
    monkeypatch.setattr(policy,"config",lambda _:cfg)
    monkeypatch.setattr(worker.store,"reserve_model",Mock(return_value=True))
    async def drafter(question):return "Synthetic natural draft"
    def handler(request):
        assert request.method=="GET"
        return httpx.Response(200,json=provider_page(job))
    asyncio.run(worker.tick(drafter=drafter,transport=httpx.MockTransport(handler)))
    assert worker.store.finish.call_args.args[2]=="contextual_draft_review"
    assert worker.store.finish.call_args.args[3]=="Synthetic natural draft"
    worker.store.reserve_send.assert_not_called()

def test_existing_model_configuration_without_new_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY","synthetic-existing-key")
    monkeypatch.setenv("INTAKE_MODEL","synthetic-existing-model")
    monkeypatch.delenv("AFAAQ_COMMENT_MODEL",raising=False)
    monkeypatch.delenv("AFAAQ_COMMENT_MODEL_KEY",raising=False)
    requests=[]
    original=httpx.AsyncClient
    def handler(request):
        import json
        body=json.loads(request.content);requests.append(body)
        assert request.headers["x-api-key"]=="synthetic-existing-key"
        assert body["model"]=="synthetic-existing-model" and body["max_tokens"]==256
        assert "tools" not in body
        assert body["messages"]==[{"role":"user","content":"Do you offer shipping?"}]
        return httpx.Response(200,json={"content":[{"type":"text","text":"shipping"}]})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    assert asyncio.run(worker.model_intent("Do you offer shipping?"))=="shipping"
    assert len(requests)==1

