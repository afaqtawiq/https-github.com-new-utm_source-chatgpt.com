"""Direct Meta (Facebook Page + Instagram) connection for Afaq — no intermediary platform.

The admin connects once through Meta's own consent screen. The app secret stays in the
server environment (META_APP_SECRET) and is never shown or stored in the database; the
resulting Page token is stored encrypted. Only the Afaq Page and its linked Instagram
business account are accepted.
"""
import json
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.social_content import e, page
from app.social_publishing import admin, cipher
from app.storage import db, log, one, utcnow

router = APIRouter()
GRAPH = 'https://graph.facebook.com/'
DEFAULT_APP_ID = '2538057650013233'
TARGET_IG = 'afaqwaiq'
PAGE_HINTS = ('طويق', 'tuwaiq', 'tawiq')
SCOPES = ('pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement,'
          'pages_read_user_content,pages_manage_metadata,instagram_basic,instagram_content_publish,'
          'instagram_manage_comments,business_management')


class MetaError(Exception):
    """Safe message only: never contains tokens or raw provider bodies."""


def version():
    return os.getenv('META_GRAPH_VERSION', 'v23.0')


def app_id():
    return os.getenv('META_APP_ID', DEFAULT_APP_ID).strip()


def redirect_uri():
    base = os.getenv('PUBLIC_BASE_URL', 'https://gulf-logistics-ai-v7-production.up.railway.app').rstrip('/')
    return base + '/settings/meta/callback'


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS meta_connection(
            id INTEGER PRIMARY KEY CHECK(id=1), page_id TEXT NOT NULL, page_name TEXT NOT NULL,
            page_token_enc TEXT NOT NULL, ig_id TEXT, ig_username TEXT,
            verified_at TIMESTAMPTZ NOT NULL, updated_by BIGINT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS meta_oauth_states(
            state TEXT PRIMARY KEY, user_id BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')


def graph(method, path, token=None, *, params=None, data=None, timeout=40):
    params = dict(params or {})
    if token:
        params['access_token'] = token
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            r = client.request(method, GRAPH + version() + '/' + path.lstrip('/'), params=params, data=data)
        body = r.json()
    except (httpx.HTTPError, ValueError):
        raise MetaError('لم تصل نتيجة مؤكدة من Meta.') from None
    if not r.is_success or not isinstance(body, dict) or 'error' in body:
        err = body.get('error', {}) if isinstance(body, dict) else {}
        raise MetaError('رفضت Meta الطلب (' + str(err.get('code') or r.status_code) + '): ' + str(err.get('message') or '')[:160])
    return body


def credentials():
    """Returns {'page_id','page_name','token','ig_id','ig_username'} or raises MetaError."""
    row = one('SELECT * FROM meta_connection WHERE id=1')
    if not row:
        raise MetaError('اربط صفحة فيسبوك وإنستغرام من إعدادات Meta أولًا.')
    try:
        token = cipher().decrypt(row['page_token_enc'].encode()).decode()
    except Exception:
        raise MetaError('تعذر فتح رمز Meta المشفر؛ أعد الربط.') from None
    return {'page_id': row['page_id'], 'page_name': row['page_name'], 'token': token,
            'ig_id': row['ig_id'], 'ig_username': row['ig_username']}


def connected():
    return bool(one('SELECT 1 x FROM meta_connection WHERE id=1'))


def choose_page(pages):
    forced = os.getenv('META_PAGE_ID', '').strip()
    if forced:
        pages = [p for p in pages if p.get('id') == forced]
    by_ig = [p for p in pages if ((p.get('instagram_business_account') or {}).get('username') or '').lower() == TARGET_IG]
    if len(by_ig) == 1:
        return by_ig[0]
    by_name = [p for p in pages if any(h in (p.get('name') or '').lower() for h in PAGE_HINTS)]
    if len(by_name) == 1:
        return by_name[0]
    raise MetaError('لم أجد صفحة آفاق طويق بشكل قاطع ضمن الصفحات الممنوحة. اختر الصفحة وحساب @' + TARGET_IG + ' في شاشة Meta.')


def complete(code):
    secret = os.getenv('META_APP_SECRET', '').strip()
    if not secret:
        raise MetaError('أضف المتغير META_APP_SECRET في Railway أولًا.')
    short = graph('GET', 'oauth/access_token', params={'client_id': app_id(), 'client_secret': secret,
                                                       'redirect_uri': redirect_uri(), 'code': code})['access_token']
    long_lived = graph('GET', 'oauth/access_token', params={'grant_type': 'fb_exchange_token', 'client_id': app_id(),
                                                           'client_secret': secret, 'fb_exchange_token': short})['access_token']
    pages = graph('GET', 'me/accounts', long_lived,
                  params={'fields': 'id,name,access_token,tasks,instagram_business_account{id,username}', 'limit': 100}).get('data') or []
    chosen = choose_page(pages)
    tasks = set(chosen.get('tasks') or [])
    if tasks and not {'CREATE_CONTENT', 'MODERATE'} <= tasks:
        raise MetaError('حسابك لا يملك صلاحية النشر والإشراف على الصفحة.')
    ig = chosen.get('instagram_business_account') or {}
    return {'page_id': chosen['id'], 'page_name': chosen.get('name') or '', 'token': chosen['access_token'],
            'ig_id': ig.get('id'), 'ig_username': ig.get('username')}


@router.get('/settings/meta', response_class=HTMLResponse)
def settings_page(request: Request):
    admin(request)
    init()
    row = one('SELECT page_id,page_name,ig_id,ig_username,verified_at FROM meta_connection WHERE id=1')
    body = '<div class="nav"><a href="/content-center">مركز المحتوى</a><a href="/settings/social">إعدادات النشر</a><a href="/daily-posters">البوستر اليومي</a></div>'
    body += '<div class="hero"><h1>ربط فيسبوك وإنستغرام مباشرة عبر Meta</h1><p class="muted">تطبيق Meta: <span dir="ltr">' + e(app_id()) + '</span> · النشر والردود من الصفحة وحساب @' + TARGET_IG + ' فقط.</p></div>'
    if row:
        body += ('<div class="card"><b class="ok">متصل</b><p>الصفحة: <b>' + e(row['page_name']) + '</b> <span dir="ltr">(' + e(row['page_id']) + ')</span></p>'
                 '<p>إنستغرام: <b dir="ltr">@' + e(row['ig_username'] or '—') + '</b></p><p class="muted">آخر تحقق: ' + e(row['verified_at']) + '</p></div>')
    if not os.getenv('META_APP_SECRET', '').strip():
        body += ('<div class="card"><b>خطوة مطلوبة منك:</b> انسخ «المفتاح السري للتطبيق» من Meta للمطوّرين ← إعدادات التطبيق ← أساسي، '
                 'وضعه في Railway كمتغير باسم <b dir="ltr">META_APP_SECRET</b>. لا تُدخله هنا.</div>')
    else:
        body += '<div class="card"><a class="btn" href="/settings/meta/connect">' + ('إعادة الربط' if row else 'ربط الصفحة وإنستغرام') + '</a></div>'
    return HTMLResponse(page(body), headers={'Cache-Control': 'no-store'})


@router.get('/settings/meta/connect')
def connect(request: Request):
    session = admin(request)
    init()
    state = secrets.token_urlsafe(24)
    with db() as c:
        c.execute("DELETE FROM meta_oauth_states WHERE created_at < now() - interval '1 hour'")
        c.execute('INSERT INTO meta_oauth_states(state,user_id,created_at) VALUES(%s,%s,%s)', (state, session['user_id'], utcnow()))
    params = {'client_id': app_id(), 'redirect_uri': redirect_uri(), 'state': state, 'response_type': 'code'}
    config = os.getenv('META_LOGIN_CONFIG_ID', '').strip()
    if config:
        params['config_id'] = config
    else:
        params['scope'] = SCOPES
    return RedirectResponse('https://www.facebook.com/' + version() + '/dialog/oauth?' + urlencode(params), 303)


@router.get('/settings/meta/callback', response_class=HTMLResponse)
async def callback(request: Request):
    session = admin(request)
    init()
    q = request.query_params
    state, code = q.get('state') or '', q.get('code') or ''
    with db() as c:
        ok = c.execute("DELETE FROM meta_oauth_states WHERE state=%s AND user_id=%s AND created_at > now() - interval '1 hour' RETURNING state",
                       (state, session['user_id'])).fetchone()
    if not ok or not code:
        return HTMLResponse(page('<div class="card">انتهت جلسة الربط أو أُلغيت. <a href="/settings/meta">ابدأ من جديد</a></div>'), status_code=400)
    try:
        conn = await run_in_threadpool(complete, code)
        encrypted = cipher().encrypt(conn['token'].encode()).decode()
    except MetaError as error:
        return HTMLResponse(page('<div class="card">' + e(str(error)) + ' <a href="/settings/meta">رجوع</a></div>'), status_code=400)
    with db() as c:
        c.execute('''INSERT INTO meta_connection(id,page_id,page_name,page_token_enc,ig_id,ig_username,verified_at,updated_by)
            VALUES(1,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET page_id=excluded.page_id,page_name=excluded.page_name,
            page_token_enc=excluded.page_token_enc,ig_id=excluded.ig_id,ig_username=excluded.ig_username,
            verified_at=excluded.verified_at,updated_by=excluded.updated_by''',
                  (conn['page_id'], conn['page_name'], encrypted, conn['ig_id'], conn['ig_username'], utcnow(), session['user_id']))
    log(session['user_id'], 'meta_connected', 'meta_connection', None,
        json.dumps({'page': conn['page_name'], 'instagram': conn['ig_username']}, ensure_ascii=False))
    return RedirectResponse('/settings/meta', 303)
