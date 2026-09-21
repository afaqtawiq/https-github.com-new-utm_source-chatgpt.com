"""Encrypted fal credential intake. Saving never invokes a paid generation."""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.fine_permissions import has_permission
from app.mfa_stepup import mfa_state, recent_stepup
from app.social_content import auth, e, page, parse
from app.social_publishing import csrf, hidden_csrf
from app.storage import db, one, utcnow

router = APIRouter()
SETTINGS_PATH = '/settings/media'


def init_media_settings():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS media_provider_settings(
            id INTEGER PRIMARY KEY CHECK(id=1),
            provider TEXT NOT NULL CHECK(provider='fal'),
            api_key_enc TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL, updated_by BIGINT NOT NULL)''')


init_media_settings()


def media_admin(request):
    session = auth(request)
    if session.get('role') != 'admin' or not has_permission(session, 'manage_media'):
        raise HTTPException(403, 'إعداد إنتاج الصور والفيديو متاح للإدارة فقط.')
    return session


def media_cipher():
    raw = os.getenv('TOKEN_ENCRYPTION_KEY', '').strip()
    if not raw:
        raise ValueError('تشفير مفتاح الإنتاج غير مهيأ على الخادم. لم يتم حفظ المفتاح.')
    key = hashlib.sha256(('afaaq-media-fal:' + raw).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def media_connection():
    """Server-only credential access for the future generation integration."""
    row = one("SELECT api_key_enc FROM media_provider_settings WHERE id=1 AND provider='fal'")
    if not row:
        raise ValueError('لم يتم حفظ مفتاح fal.ai بعد.')
    try:
        return media_cipher().decrypt(row['api_key_enc'].encode()).decode()
    except InvalidToken:
        raise ValueError('تعذر فتح مفتاح الإنتاج المشفر. أعد حفظه من إعدادات الإنتاج.') from None


def settings_response(session, *, error=None, status_code=200):
    # Never retrieve the credential when rendering its status.
    saved = one('SELECT updated_at FROM media_provider_settings WHERE id=1')
    body = '<div class="nav"><a href="/content-center">مركز المحتوى</a><a href="/settings/social">إعدادات النشر</a></div>'
    body += '<div class="hero"><h1>إعداد إنتاج الصور والفيديو</h1><p>fal.ai · آفاق طويق</p></div>'
    if error:
        body += '<div class="card" role="alert">' + e(error) + '</div>'
    if saved:
        body += '<div class="card"><b class="ok">مفتاح fal.ai محفوظ ومشفّر</b><p>آخر حفظ: ' + e(saved['updated_at']) + '</p></div>'
    else:
        body += '<div class="card">لم يتم حفظ مفتاح fal.ai بعد.</div>'
    body += '<div class="card"><h2>حالة الإنتاج</h2><p>لم يُختبر المفتاح لدى fal.ai بعد. إنتاج الصور والفيديو لم يُفعّل بعد.</p>'
    body += '<p>حفظ المفتاح لا ينشئ محتوى ولا يستهلك رصيدًا. يُحدَّد سقف الإنفاق قبل تشغيل الإنتاج.</p></div>'
    state = mfa_state(session['user_id'])
    if not state or not state.get('mfa_enabled'):
        body += '<div class="card"><p>فعّل التحقق الثنائي لحفظ مفتاح الإنتاج.</p><a class="btn" href="/mfa">إعداد التحقق الثنائي</a></div>'
    elif not recent_stepup(session['id']):
        body += '<div class="card"><p>أكمل التحقق لفتح خانة المفتاح.</p><a class="btn" href="/mfa/step-up?next=/settings/media">التحقق عبر Authenticator</a></div>'
    else:
        body += '<div class="card"><p>الصق قيمة المفتاح الكاملة من fal.ai في الخانة أدناه.</p>'
        body += '<form method="post" action="/settings/media">' + hidden_csrf(session)
        body += '<label for="fal-api-key">مفتاح fal.ai<input id="fal-api-key" name="api_key" type="password" dir="ltr" autocomplete="off" spellcheck="false" autocapitalize="none" required minlength="16" maxlength="512"></label>'
        body += '<button class="btn">حفظ مفتاح الإنتاج</button></form></div>'
    return HTMLResponse(page(body), status_code=status_code, headers={'Cache-Control': 'no-store'})


@router.get(SETTINGS_PATH, response_class=HTMLResponse)
def media_settings_page(request: Request):
    return settings_response(media_admin(request))


@router.post(SETTINGS_PATH)
async def save_media_settings(request: Request):
    session = media_admin(request)
    raw = await request.body()
    if len(raw) > 4096:
        raise HTTPException(413)
    try:
        data = parse(raw)
    except (UnicodeError, ValueError):
        return settings_response(session, error='تعذر قراءة النموذج. أعد فتح الصفحة.', status_code=400)
    csrf(session, data)
    key = data.get('api_key', '').strip()
    if not 16 <= len(key) <= 512 or any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
        return settings_response(session, error='أدخل قيمة مفتاح fal.ai كاملة دون مسافات داخلية.', status_code=400)
    try:
        encrypted = media_cipher().encrypt(key.encode()).decode()
    except ValueError as error:
        return settings_response(session, error=str(error), status_code=503)
    now = utcnow()
    with db() as c:
        c.execute('''INSERT INTO media_provider_settings(id,provider,api_key_enc,updated_at,updated_by)
            VALUES(1,'fal',%s,%s,%s) ON CONFLICT(id) DO UPDATE SET
            api_key_enc=excluded.api_key_enc,updated_at=excluded.updated_at,updated_by=excluded.updated_by''',
            (encrypted, now, session['user_id']))
        c.execute('''INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at)
            VALUES(%s,'media_credential_saved','media_provider',1,%s,%s)''',
            (session['user_id'], 'Saved encrypted fal credential; generation remains unavailable; no provider call.', now))
    return RedirectResponse(SETTINGS_PATH, 303, headers={'Cache-Control': 'no-store'})
