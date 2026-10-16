"""YouTube identity evidence from one authenticated, fully scoped provider read.

Never infer an absent flag is false. A missing isOwner flag is resolved only by
exact stable author-ID comparison with a separately verified configured owner.
"""
import hashlib
from urllib.parse import quote
from datetime import datetime, timezone
import httpx

def evidence(data, job, cfg):
    if (cfg.get("platform") != "youtube" or not cfg.get("youtube_owner_id")
            or not cfg.get("owner_verification_ref") or cfg["youtube_owner_id"] not in cfg.get("owner_ids", [])):
        return None
    if not isinstance(data,dict):
        return None
    meta, paging, comments = (data.get(k) for k in ("meta","pagination","comments"))
    if not isinstance(meta,dict) or not isinstance(paging,dict) or not isinstance(comments,list):
        return None
    if (meta.get("accountId") != job["account_id"] or meta.get("platform") != "youtube"
            or meta.get("postId") != job["post_id"] or paging.get("hasMore") is not False
            or paging.get("cursor") not in (None,"") or len(comments)>100):
        return None
    # Provider cache is documented as up to ten minutes. Missing freshness
    # evidence, older cache or future data cannot verify a current target.
    try:
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(meta["lastUpdated"].replace("Z","+00:00"))).total_seconds()
        if not -60 <= age <= 600:
            return None
    except (ValueError,TypeError,KeyError,AttributeError):
        return None
    if any(not isinstance(c,dict) for c in comments):
        return None
    matches=[c for c in comments if c.get("id")==job["comment_id"]]
    if len(matches)!=1:
        return None
    target=matches[0]
    author=target.get("from")
    if (not isinstance(author,dict) or not isinstance(author.get("id"),str) or not author["id"]
            or author["id"] != job.get("author_id") or author["id"] in cfg["owner_ids"]
            or author["id"] == cfg["youtube_owner_id"]):
        return None
    if "isOwner" in author and author["isOwner"] is not False:
        return None
    if (target.get("platform") != "youtube" or target.get("canReply") is not True
            or target.get("isHidden") is not False or "parentId" not in target
            or target["parentId"] not in (None,"") or target.get("message") != job["question"]):
        return None
    return {"account_id":job["account_id"],"post_id":job["post_id"],"comment_id":job["comment_id"],
            "author_id":author["id"],"owner_id":cfg["youtube_owner_id"],
            "question_sha256":hashlib.sha256(job["question"].encode()).hexdigest(),
            "basis":"authenticated_author_id_vs_verified_owner"}

async def verify(client, job, cfg):
    # No pagination, polling, guessed cursor or direct-platform fallback.
    response=await client.get("https://zernio.com/api/v1/inbox/comments/"+quote(job["post_id"],safe=""),
                              params={"accountId":job["account_id"],"limit":100})
    response.raise_for_status()
    if len(response.content)>1024*1024:
        return None
    return evidence(response.json(),job,cfg)

