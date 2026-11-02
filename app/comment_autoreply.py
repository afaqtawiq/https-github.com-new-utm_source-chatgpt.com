"""Owner-authorised automatic replies to public comments: YouTube/TikTok via Zernio, Facebook/Instagram via Meta.

Enabled only with AFAQ_AUTO_COMMENTS=1 and ENABLE_EXTERNAL_ACTIONS=1. Every 10 minutes the
worker reads the comments of videos the agent published (Zernio post results), and answers each
new top-level comment once. Replies come from the existing guarded drafter/validator; when the
model cannot produce a validated answer, a fixed approved reply is used for clear intents and
everything else (complaints, personal data, links, numbers, unrelated or unsafe text) is held for
the team. Never replies to the channel's own comments, never twice, hourly/daily caps apply.
"""
import asyncio
import json
import os
import re
import uuid
from urllib.parse import parse_qs, quote, urlsplit

import httpx
from starlette.concurrency import run_in_threadpool

from app import comment_policy as policy
from app.storage import db, utcnow

BASE = 'https://zernio.com/api/v1'
HOURLY, DAILY = 10, 50


def enabled():
    return os.getenv('AFAQ_AUTO_COMMENTS', '0') == '1' and os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') == '1'


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS afaq_auto_comment_replies(
            account_id TEXT NOT NULL, comment_id TEXT NOT NULL, post_id TEXT NOT NULL, platform TEXT NOT NULL,
            question TEXT NOT NULL DEFAULT '', reply TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
            provider_id TEXT, created_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(account_id, comment_id))''')


def post_id_from(platform, url):
    u = urlsplit(url or '')
    if platform == 'youtube':
        if u.hostname == 'youtu.be':
            return u.path.strip('/') or None
        v = parse_qs(u.query).get('v')
        if v:
            return v[0]
        m = re.search(r'/shorts/([\w-]{6,})', u.path)
        return m.group(1) if m else None
    if platform == 'tiktok':
        m = re.search(r'/video/(\d+)', u.path)
        return m.group(1) if m else None
    return None


def targets():
    out = []
    with db() as c:
        rows = c.execute("SELECT results_json FROM social_publications WHERE status IN ('published','partial')").fetchall()
    for row in rows:
        try:
            results = json.loads(row['results_json'] or '[]')
        except ValueError:
            continue
        for r in results:
            pid = post_id_from(r.get('platform'), r.get('url'))
            if pid and r.get('accountId') and r.get('status') == 'published':
                out.append((r['platform'], r['accountId'], pid))
    return sorted(set(out))


def budget_ok():
    with db() as c:
        row = c.execute('''SELECT COUNT(*) FILTER (WHERE created_at > now() - interval '1 hour') h,
            COUNT(*) FILTER (WHERE created_at > now() - interval '1 day') d
            FROM afaq_auto_comment_replies WHERE status IN ('sent','uncertain','sending')''').fetchone()
    return row['h'] < HOURLY and row['d'] < DAILY


def claim(account, comment, post, platform, question):
    with db() as c:
        return bool(c.execute('''INSERT INTO afaq_auto_comment_replies(account_id,comment_id,post_id,platform,question,status,created_at)
            VALUES(%s,%s,%s,%s,%s,'drafting',%s) ON CONFLICT DO NOTHING RETURNING comment_id''',
            (account, comment, post, platform, question[:1200], utcnow())).fetchone())


def finish(account, comment, status, reply='', provider_id=None):
    with db() as c:
        c.execute('''UPDATE afaq_auto_comment_replies SET status=%s,reply=%s,provider_id=%s
            WHERE account_id=%s AND comment_id=%s''', (status, reply, provider_id, account, comment))


def owner_answered(comment):
    for r in comment.get('replies') or []:
        if isinstance(r, dict) and (r.get('from') or {}).get('isOwner') is True:
            return True
    return False


async def compose(question):
    from app.comment_responder import model_draft, model_validate
    if policy.screen(question) != 'safe':
        return None
    try:
        draft = await model_draft(question)
        if draft and await model_validate(question, draft) is True:
            return draft
    except Exception:
        pass
    return policy.render(policy.classify_local(question) or '')


async def poll_once():
    from app.social_publishing import connection
    key, _ = await run_in_threadpool(connection)
    stats = {'checked': 0, 'sent': 0, 'held': 0}
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, headers={'Authorization': 'Bearer ' + key}) as c:
        for platform, account, pid in await run_in_threadpool(targets):
            r = await c.get(BASE + '/inbox/comments/' + quote(pid, safe=''), params={'accountId': account, 'limit': 100})
            if not r.is_success:
                print('AUTO_COMMENTS_READ', platform, pid, r.status_code, flush=True)
                continue
            for cm in (r.json() or {}).get('comments') or []:
                if not isinstance(cm, dict) or not cm.get('id'):
                    continue
                author = cm.get('from') or {}
                text = cm.get('message') or cm.get('text') or ''
                if (cm.get('parentId') or cm.get('canReply') is False or cm.get('isHidden') is True
                        or author.get('isOwner') is True or not text.strip() or owner_answered(cm)):
                    continue
                stats['checked'] += 1
                if not await run_in_threadpool(budget_ok):
                    return stats
                if not await run_in_threadpool(claim, account, cm['id'], pid, platform, text):
                    continue
                reply = await compose(text)
                if not reply:
                    await run_in_threadpool(finish, account, cm['id'], 'held')
                    stats['held'] += 1
                    continue
                await run_in_threadpool(finish, account, cm['id'], 'sending', reply)
                status, provider_id = 'uncertain', None
                try:
                    resp = await c.post(BASE + '/inbox/comments/' + quote(pid, safe=''),
                                        headers={'Idempotency-Key': 'afaq-comment-' + uuid.uuid5(uuid.NAMESPACE_URL, account + cm['id']).hex},
                                        json={'accountId': account, 'commentId': cm['id'], 'message': reply})
                    if resp.is_success:
                        data = resp.json()
                        status, provider_id = 'sent', str((data.get('data') or {}).get('commentId') or '')
                    elif resp.status_code in (400, 401, 403, 404, 422):
                        status = 'rejected'
                        print('AUTO_COMMENTS_REPLY', platform, resp.status_code, resp.text[:200], flush=True)
                except Exception as exc:
                    print('AUTO_COMMENTS_REPLY_ERROR', type(exc).__name__, flush=True)
                await run_in_threadpool(finish, account, cm['id'], status, reply, provider_id)
                stats['sent'] += status == 'sent'
    return stats


def meta_comments(conn, graph):
    """Top-level comments on the Afaq Page's and Instagram account's recent posts, as (platform, account, post, id, text)."""
    out = []
    posts = graph('GET', conn['page_id'] + '/posts', conn['token'], params={'fields': 'id', 'limit': 10}).get('data') or []
    for p in posts:
        data = graph('GET', p['id'] + '/comments', conn['token'], params={
            'fields': 'id,message,from,comments.limit(25){from}', 'filter': 'toplevel', 'limit': 50}).get('data') or []
        for cm in data:
            if (cm.get('from') or {}).get('id') == conn['page_id']:
                continue
            if any((r.get('from') or {}).get('id') == conn['page_id'] for r in (cm.get('comments') or {}).get('data') or []):
                continue
            out.append(('facebook', conn['page_id'], p['id'], cm.get('id'), cm.get('message') or ''))
    if conn.get('ig_id'):
        own = (conn.get('ig_username') or '').lower()
        media = graph('GET', conn['ig_id'] + '/media', conn['token'], params={'fields': 'id', 'limit': 10}).get('data') or []
        for m in media:
            data = graph('GET', m['id'] + '/comments', conn['token'], params={
                'fields': 'id,text,username,replies{username}', 'limit': 50}).get('data') or []
            for cm in data:
                if (cm.get('username') or '').lower() == own:
                    continue
                if any((r.get('username') or '').lower() == own for r in (cm.get('replies') or {}).get('data') or []):
                    continue
                out.append(('instagram', conn['ig_id'], m['id'], cm.get('id'), cm.get('text') or ''))
    return out


async def poll_meta_once():
    """Facebook Page + Instagram replies straight through Meta (no intermediary)."""
    from app.meta_connect import MetaError, connected, credentials, graph
    stats = {'checked': 0, 'sent': 0, 'held': 0}
    if not await run_in_threadpool(connected):
        return stats
    conn = await run_in_threadpool(credentials)
    try:
        items = await run_in_threadpool(meta_comments, conn, graph)
    except MetaError as exc:
        print('AUTO_COMMENTS_META_READ', str(exc)[:160], flush=True)
        return stats
    for platform, account, post, cid, text in items:
        if not cid or not text.strip():
            continue
        stats['checked'] += 1
        if not await run_in_threadpool(budget_ok):
            break
        if not await run_in_threadpool(claim, account, cid, post, platform, text):
            continue
        reply = await compose(text)
        if not reply:
            await run_in_threadpool(finish, account, cid, 'held')
            stats['held'] += 1
            continue
        await run_in_threadpool(finish, account, cid, 'sending', reply)
        path = cid + ('/comments' if platform == 'facebook' else '/replies')
        status, provider_id = 'uncertain', None
        try:
            result = await run_in_threadpool(lambda: graph('POST', path, conn['token'], data={'message': reply}))
            status, provider_id = 'sent', str(result.get('id') or '')
        except MetaError as exc:
            status = 'rejected'
            print('AUTO_COMMENTS_META_REPLY', platform, str(exc)[:160], flush=True)
        except Exception as exc:
            print('AUTO_COMMENTS_META_ERROR', type(exc).__name__, flush=True)
        await run_in_threadpool(finish, account, cid, status, reply, provider_id)
        stats['sent'] += status == 'sent'
    return stats


def register_worker(app):
    async def loop():
        await asyncio.sleep(60)
        while True:
            if enabled():
                try:
                    await run_in_threadpool(init)
                    stats = await poll_once()
                    if stats['checked']:
                        print('AUTO_COMMENTS', stats, flush=True)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print('AUTO_COMMENTS_ERROR', type(exc).__name__, str(exc)[:200], flush=True)
                try:
                    meta = await poll_meta_once()
                    if meta['checked']:
                        print('AUTO_COMMENTS_META', meta, flush=True)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print('AUTO_COMMENTS_ERROR', type(exc).__name__, str(exc)[:200], flush=True)
            await asyncio.sleep(600)

    @app.on_event('startup')
    async def start():
        app.state.auto_comment_worker = asyncio.create_task(loop())
