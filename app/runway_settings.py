"""Isolated, encrypted Runway credential intake and explicit read-only verification."""
import base64
import hashlib
import os
from urllib.parse import parse_qs

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.media_runway import RunwayError, organization_balance
from app.media_settings import media_admin
from app.mfa_stepup import mfa_state, recent_stepup
from app.social_content import e, page
from app.social_publishing import csrf, hidden_csrf
from app.storage import db, one, utcnow

router = APIRouter()
SETTINGS_PATH = '/settings/runway'
NO_STORE = {'Cache-Control': 'no-store'}


def init_runway_settings():
    # A new table only: never alter or replace fal credentials or media jobs.
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS runway_provider_settings(
            id INTEGER PRIMARY KEY CHECK(id=1), api_key_enc TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL, updated_by BIGINT NOT NULL,
            checked_at TIMESTAMPTZ, verified_at TIMESTAMPTZ,
            credit_balance BIGINT CHECK(credit_balance >= 0))''')


init_runway_settings()


def runway_cipher():
    raw = os.getenv('TOKEN_ENCRYPTION_KEY', '').strip()
    if not raw:
        raise RunwayError('تشفير ربط Runway غير مهيأ على الخادم. لم يتم حفظ المفتاح.')
    digest = hashlib.sha256(('afaaq-media-runway:' + raw).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def connection_status():
    """Status rendering must never retrieve or decrypt the saved credential."""
    row = one('SELECT updated_at,checked_at,verified_at,credit_balance FROM runway_provider_settings WHERE id=1')
    return {'configured': bool(row), 'verified_at': row['verified_at'] if row else None,
            'updated_at': row['updated_at'] if row else None,
            'checked_at': row['checked_at'] if row else None,
            'credit_balance': row['credit_balance'] if row else None,
            'generation_enabled': False}


def credential():
    row = one('SELECT api_key_enc,updated_at FROM runway_provider_settings WHERE id=1')
    if not row:
        raise RunwayError('احفظ مفتاح Runway Developer API أولًا.')
    try:
        return runway_cipher().decrypt(row['api_key_enc'].encode()).decode(), row['updated_at']
    except (InvalidToken, UnicodeError):
        raise RunwayError('تعذر فتح مفتاح Runway المشفر. أعد حفظه من هذه الصفحة.') from None


def require_stepup(session):
    state = mfa_state(session['user_id'])
    if not state or not state.get('mfa_enabled') or not recent_stepup(session['id']):
        raise HTTPException(428, 'أكمل التحقق الثنائي الحديث قبل إعداد ربط Runway أو فحصه.', headers=NO_STORE)


async def form_data(request, session):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 4096:
            raise HTTPException(413, headers=NO_STORE)
    try:
        fields = parse_qs(raw.decode(), keep_blank_values=True, max_num_fields=8)
    except (UnicodeError, ValueError):
        raise HTTPException(400, 'تعذر قراءة النموذج. أعد فتح الصفحة.', headers=NO_STORE) from None
    if any(len(values) != 1 for values in fields.values()):
        raise HTTPException(400, 'النموذج يحتوي حقولًا مكررة.', headers=NO_STORE)
    data = {key: values[0] for key, values in fields.items()}
    if not data.get('csrf', '').isascii():
        raise HTTPException(403, 'أعد فتح النموذج ثم حاول مجددًا.', headers=NO_STORE)
    csrf(session, data)
    return data


def settings_response(session, *, error=None, status_code=200):
    saved = connection_status()
    body = '<div class="nav"><a href="/content-center">مركز المحتوى</a><a href="/settings/media">إعداد fal.ai</a><a href="/readiness">الجاهزية</a></div>'
    body += '<div class="hero"><h1>ربط Runway Developer API</h1><p>آفاق طويق · إعداد الاتصال وفحص رصيد المشروع</p></div>'
    if error:
        body += '<div class="card" role="alert">' + e(error) + '</div>'
    if saved['configured']:
        body += '<div class="card"><b class="ok">مفتاح Runway محفوظ ومشفّر</b><p>آخر حفظ: ' + e(saved['updated_at']) + '</p>'
        if saved['verified_at']:
            body += '<p><b>نجح فحص الاتصال والرصيد</b></p><p>رصيد Developer API وقت الفحص: <b>' + e(str(saved['credit_balance'])) + ' credits</b></p><p>وقت الفحص: ' + e(saved['verified_at']) + '</p>'
        elif saved['checked_at']:
            body += '<p>لم ينجح الفحص الأخير. لا توجد نتيجة رصيد معتمدة.</p>'
        else:
            body += '<p>لم يُفحص الاتصال بعد. حفظ المفتاح لا يؤكد صلاحيته أو رصيده.</p>'
        body += '</div>'
    else:
        body += '<div class="card">لم يتم حفظ مفتاح Runway Developer API بعد.</div>'
    body += '<div class="card"><h2>نطاق الربط</h2><p>رصيد Developer API منفصل عن رصيد تطبيق Runway. هذا الفحص يخص المشروع المرتبط بالمفتاح الذي أدخلته؛ لا يفترض تطابقه مع أي اتصال آخر. يُفحص الرصيد عند طلبك فقط وقد يتغير بعد الفحص.</p>'
    body += '<p>توليد المحتوى عبر Runway غير مفعّل في هذا الإصدار. فحص الاتصال لا ينشئ صورة أو فيديو ولا يشتري رصيدًا. استوديو fal.ai الحالي مستقل ولا يتغير.</p></div>'
    state = mfa_state(session['user_id'])
    if not state or not state.get('mfa_enabled'):
        body += '<div class="card"><p>فعّل التحقق الثنائي لإعداد الربط.</p><a class="btn" href="/mfa">إعداد التحقق الثنائي</a></div>'
    elif not recent_stepup(session['id']):
        body += '<div class="card"><p>أكمل التحقق لفتح خانة المفتاح وفحص الاتصال.</p><a class="btn" href="/mfa/step-up?next=/settings/runway">التحقق عبر Authenticator</a></div>'
    else:
        body += '<div class="card"><h2>' + ('استبدال المفتاح' if saved['configured'] else 'حفظ المفتاح') + '</h2>'
        body += '<p>أدخل مفتاح مشروع Runway Developer API بنفسك هنا فقط. سيُحفظ مشفرًا في خادم آفاق لاستعمال الربط؛ لا تشاركه في المحادثة. الحفظ لا يرسل طلبًا إلى Runway. زر الفحص يستخدمه من الخادم للتحقق لدى api.dev.runwayml.com.</p>'
        body += '<form method="post" action="/settings/runway">' + hidden_csrf(session)
        body += '<label for="runway-api-key">مفتاح Runway<input id="runway-api-key" name="api_key" type="password" dir="ltr" autocomplete="off" spellcheck="false" autocapitalize="none" required minlength="16" maxlength="512"></label>'
        body += '<button class="btn">حفظ مفتاح Runway</button></form></div>'
        if saved['configured']:
            body += '<div class="card"><form method="post" action="/settings/runway/check">' + hidden_csrf(session)
            body += '<button class="btn">فحص الاتصال والرصيد — دون توليد</button></form></div>'
    return HTMLResponse(page(body), status_code=status_code, headers=NO_STORE)


@router.get(SETTINGS_PATH, response_class=HTMLResponse)
def settings_page(request: Request):
    return settings_response(media_admin(request))


@router.post(SETTINGS_PATH)
async def save_settings(request: Request):
    session = media_admin(request)
    require_stepup(session)
    data = await form_data(request, session)
    key = data.get('api_key', '').strip()
    if not 16 <= len(key) <= 512 or any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
        return settings_response(session, error='أدخل مفتاح Runway الكامل دون مسافات داخلية.', status_code=400)
    try:
        encrypted = runway_cipher().encrypt(key.encode()).decode()
    except RunwayError as error:
        return settings_response(session, error=str(error), status_code=503)
    now = utcnow()
    with db() as c:
        c.execute('''INSERT INTO runway_provider_settings(id,api_key_enc,updated_at,updated_by)
            VALUES(1,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET
            api_key_enc=excluded.api_key_enc,updated_at=excluded.updated_at,updated_by=excluded.updated_by,
            checked_at=NULL,verified_at=NULL,credit_balance=NULL''', (encrypted, now, session['user_id']))
        c.execute('''INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at)
            VALUES(%s,'runway_credential_saved','runway_provider',1,%s,%s)''',
            (session['user_id'], 'Saved encrypted Runway credential; no provider call or generation.', now))
    return RedirectResponse(SETTINGS_PATH, 303, headers=NO_STORE)


@router.post(SETTINGS_PATH + '/check')
async def check_connection(request: Request):
    session = media_admin(request)
    require_stepup(session)
    await form_data(request, session)
    version = connection_status()['updated_at']
    try:
        key, version = credential()
    except RunwayError as error:
        if version:
            record_check(session, version, None, failed=True)
        return settings_response(session, error=str(error), status_code=400)
    balance, failure = None, None
    try:
        balance = await run_in_threadpool(organization_balance, key)
    except RunwayError as error:
        failure = str(error)
    updated = record_check(session, version, balance, failed=bool(failure))
    if not updated:
        return settings_response(session, error='تغير المفتاح أثناء الفحص. أعد فحص المفتاح الحالي.', status_code=409)
    if failure:
        return settings_response(session, error=failure, status_code=502)
    return RedirectResponse(SETTINGS_PATH, 303, headers=NO_STORE)


def record_check(session, version, balance, *, failed):
    """Record only status and timestamp, conditional on the same saved credential."""
    now = utcnow()
    with db() as c:
        # A response for an old key must never verify or invalidate its replacement.
        updated = c.execute('''UPDATE runway_provider_settings SET checked_at=%s,verified_at=%s,credit_balance=%s
            WHERE id=1 AND updated_at=%s RETURNING id''', (now, None if failed else now, balance, version)).fetchone()
        if updated:
            c.execute('''INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at)
                VALUES(%s,'runway_connection_checked','runway_provider',1,%s,%s)''',
                (session['user_id'], 'Runway connection verification ' + ('failed' if failed else 'succeeded') + '; no generation.', now))
    return bool(updated)
