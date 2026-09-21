"""Admin-reviewed video scheduling, using a separate encrypted social credential.

Zernio runs the schedule. The app never retries an ambiguous create request and
does not use the existing ZERNIO_API_KEY (reserved for the WhatsApp integration).
"""
import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import uuid

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.storage import db, execute, log, one, utcnow
from app.social_content import auth, e, page, parse
from app.social_zernio import (PLATFORMS, RIYADH, TARGETS, PublishingError, creator_info,
                               identifier, make_payload, media_url, provider_request,
                               publication_result, verified_accounts)

router = APIRouter()
STATES = {'submitting': 'أُرسل الطلب؛ تحقق من نتيجته قبل أي محاولة أخرى',
          'scheduled': 'مجدول لدى Zernio', 'publishing': 'جارٍ النشر',
          'published': 'تم النشر على جميع الحسابات المختارة', 'partial': 'نجح النشر جزئيًا — راجع Zernio',
          'failed': 'فشل النشر لدى المنصة', 'cancelled': 'أُلغي في Zernio',
          'needs_review': 'نتيجة غير مؤكدة — راجع Zernio قبل إعادة المحاولة'}


def init_publishing():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS social_publishing_settings(
            id INTEGER PRIMARY KEY CHECK(id=1), api_key_enc TEXT NOT NULL,
            accounts_json TEXT NOT NULL, verified_at TIMESTAMPTZ NOT NULL, updated_by BIGINT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS social_publications(
            id BIGSERIAL PRIMARY KEY, content_id BIGINT NOT NULL UNIQUE REFERENCES social_content(id),
            request_id TEXT NOT NULL UNIQUE, provider_post_id TEXT,
            status TEXT NOT NULL, scheduled_at TIMESTAMPTZ NOT NULL,
            payload_json TEXT NOT NULL, results_json TEXT NOT NULL DEFAULT '[]', last_error TEXT,
            approved_by BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')


init_publishing()


def admin(request):
    session = auth(request)
    if session.get('role') != 'admin':
        raise HTTPException(403, 'إعداد الربط وجدولة النشر متاحان للإدارة فقط.')
    return session


def csrf(session, data):
    expected = session.get('csrf') or ''
    if not expected or not secrets.compare_digest(str(data.get('csrf') or ''), expected):
        raise HTTPException(403, 'أعد فتح النموذج ثم حاول مجددًا.')


def cipher():
    raw = os.getenv('TOKEN_ENCRYPTION_KEY', '').strip()
    if not raw:
        raise PublishingError('تشفير إعدادات الربط غير مهيأ على الخادم.')
    key = hashlib.sha256(('afaaq-social-publishing:' + raw).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def connection():
    row = one('SELECT * FROM social_publishing_settings WHERE id=1')
    if not row:
        raise PublishingError('أكمل إعداد ربط Zernio في إعدادات النشر أولًا.')
    try:
        return cipher().decrypt(row['api_key_enc'].encode()).decode(), json.loads(row['accounts_json'])
    except (InvalidToken, ValueError):
        raise PublishingError('تعذر فتح إعداد الربط المشفر. أعد حفظ مفتاح الربط.') from None


def connection_status():
    row = one('SELECT accounts_json,verified_at FROM social_publishing_settings WHERE id=1')
    return {'configured': bool(row), 'accounts': json.loads(row['accounts_json']) if row else {},
            'verified_at': row['verified_at'] if row else None}


def publication(content_id):
    return one('SELECT * FROM social_publications WHERE content_id=?', (content_id,))


def selected_platforms(item):
    platforms = PLATFORMS.get(item.get('platform'))
    if not platforms or item.get('content_type') not in ('video', 'reel'):
        raise PublishingError('الجدولة متاحة لمسودة فيديو أو ريلز مخصصة لـ YouTube أو TikTok أو كليهما.')
    return platforms


def checked_connection(platforms):
    key, saved = connection()
    live = verified_accounts(key, platforms)
    if any(saved.get(p) != live[p] for p in platforms):
        raise PublishingError('تغير اتصال الحساب. راجع إعدادات الربط واحفظها مجددًا قبل الجدولة.')
    return key, live


def message_page(message, status=400):
    return HTMLResponse(page('<div class="card"><p>' + e(message) +
                             '</p><a class="btn" href="/content-center">مركز المحتوى</a> '
                             '<a class="btn" href="/settings/social">إعدادات النشر</a></div>'), status_code=status)


def hidden_csrf(session):
    return '<input type="hidden" name="csrf" value="' + e(session['csrf']) + '">'


def select(name, label, options):
    return '<label>' + e(label) + '<select required name="' + e(name) + '"><option value="">اختر…</option>' + ''.join(
        '<option value="' + e(value) + '">' + e(text) + '</option>' for value, text in options) + '</select></label>'


@router.get('/settings/social', response_class=HTMLResponse)
def settings_page(request: Request):
    session = admin(request)
    status = connection_status()
    body = '<div class="nav"><a href="/content-center">مركز المحتوى</a><a href="/settings/media">إعدادات الإنتاج</a></div><div class="hero"><h1>ربط النشر لآفاق طويق</h1>'
    body += '<p>YouTube: <b dir="ltr">@afaqtaw</b> · TikTok: <b dir="ltr">@afaqtawaiq6</b></p></div>'
    if status['configured']:
        body += '<div class="card"><b class="ok">مفتاح الربط محفوظ ومشفّر</b><p>آخر تحقق: ' + e(status['verified_at']) + '</p></div>'
    else:
        body += '<div class="card">الحسابات متصلة في Zernio، ويلزم حفظ مفتاح ربطها هنا لتشغيل الجدولة من الوكيل.</div>'
    body += '<div class="card"><p>أنشئ مفتاحًا من حساب Zernio الذي يحتوي حسابَي آفاق، وأدخله هنا. يتحقق النظام من الحسابين وصلاحية النشر قبل الحفظ.</p>'
    body += '<p><a target="_blank" rel="noopener" href="https://zernio.com/dashboard/api-keys">فتح مفاتيح الربط في Zernio</a></p>'
    body += '<form method="post" action="/settings/social">' + hidden_csrf(session)
    body += '<label>مفتاح ربط Zernio<input name="api_key" type="password" autocomplete="off" required maxlength="512"></label><button class="btn">التحقق وحفظ الربط</button></form></div>'
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        body += '<div class="card">الإرسال الخارجي متوقف على الخادم؛ تبقى المسودات متاحة.</div>'
    return HTMLResponse(page(body), headers={'Cache-Control': 'no-store'})


@router.post('/settings/social')
async def save_settings(request: Request):
    session = admin(request)
    if len(await request.body()) > 4096:
        raise HTTPException(413)
    data = parse(await request.body())
    csrf(session, data)
    key = data.get('api_key', '').strip()
    if not 16 <= len(key) <= 512 or any(ch.isspace() for ch in key):
        return message_page('أدخل مفتاح ربط صالحًا من Zernio.')
    try:
        encryption = cipher()
        accounts = await run_in_threadpool(verified_accounts, key)
        encrypted = encryption.encrypt(key.encode()).decode()
    except PublishingError as error:
        return message_page(str(error))
    execute('''INSERT INTO social_publishing_settings(id,api_key_enc,accounts_json,verified_at,updated_by)
        VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET api_key_enc=excluded.api_key_enc,
        accounts_json=excluded.accounts_json,verified_at=excluded.verified_at,updated_by=excluded.updated_by''',
        (encrypted, json.dumps(accounts), utcnow(), session['user_id']))
    log(session['user_id'], 'social_connection_verified', 'social_publishing', None, 'Verified Afaaq YouTube and TikTok')
    return RedirectResponse('/settings/social', 303)


@router.get('/content-center/{content_id}/schedule', response_class=HTMLResponse)
def schedule_page(content_id: int, request: Request):
    session = admin(request)
    item = one('SELECT * FROM social_content WHERE id=?', (content_id,))
    if not item:
        raise HTTPException(404)
    if item['status'] != 'approved' or publication(content_id):
        return message_page('هذه المسودة غير معتمدة، أو سبق إرسال طلب نشر لها.', 409)
    try:
        platforms = selected_platforms(item)
        url = media_url(item.get('media_url'))
        key, accounts = checked_connection(platforms)
        creator = creator_info(key, accounts['tiktok']['accountId']) if 'tiktok' in platforms else None
    except PublishingError as error:
        return message_page(str(error))
    body = '<div class="nav"><a href="/content-center/' + str(content_id) + '">العودة للمسودة</a></div><div class="hero"><h1>مراجعة وجدولة الفيديو</h1><p>'
    body += ' · '.join(e(p) + ': <b dir="ltr">@' + e(TARGETS[p]) + '</b>' for p in platforms) + '</p></div>'
    body += '<div class="card"><h2>' + e(item['title']) + '</h2><p style="white-space:pre-wrap">' + e(item['body']) + '</p>'
    body += '<video controls preload="none" referrerpolicy="no-referrer" style="max-width:100%;max-height:480px" src="' + e(url) + '"></video></div>'
    body += '<div class="card"><form method="post" action="/content-center/' + str(content_id) + '/schedule">' + hidden_csrf(session)
    body += '<input type="hidden" name="version" value="' + e(item['updated_at']) + '">'
    scheduled = item.get('scheduled_at')
    value = scheduled.astimezone(RIYADH).strftime('%Y-%m-%dT%H:%M') if isinstance(scheduled, dt.datetime) else ''
    body += '<label>موعد النشر — بتوقيت الرياض<input type="datetime-local" name="scheduled_at" required value="' + e(value) + '"></label><p class="muted">اختر موعدًا بعد خمس دقائق على الأقل. تتولى Zernio النشر في الموعد؛ وتُراجع الحالة من صفحة المسودة.</p>'
    body += select('synthetic', 'هل يتضمن الفيديو مشاهد أو صوتًا واقعيًا مولدًا بالذكاء الاصطناعي؟', [('yes', 'نعم'), ('no', 'لا')])
    if 'youtube' in platforms:
        body += select('youtube_visibility', 'ظهور فيديو يوتيوب عند الموعد', [('public', 'عام'), ('unlisted', 'غير مدرج'), ('private', 'خاص')])
        body += select('made_for_kids', 'هل الفيديو موجه للأطفال؟', [('yes', 'نعم'), ('no', 'لا')])
    if creator is not None:
        body += '<h2>TikTok</h2>' + select('tiktok_privacy', 'ظهور فيديو تيك توك', [(x['value'], x.get('label', x['value'])) for x in creator.get('privacyLevels', [])])
        interactions = creator.get('postingLimits', {}).get('interactionSettings', {})
        for field, label in [('allow_comment', 'السماح بالتعليقات'), ('allow_duet', 'السماح بالدويتو'), ('allow_stitch', 'السماح بدمج الفيديو')]:
            options = [('no', 'لا')]
            if isinstance(interactions.get(field), dict) and interactions[field].get('enabled') is True:
                options.insert(0, ('yes', 'نعم'))
            body += select(field, label, options)
        body += select('commercial_content', 'الإفصاح عن المحتوى التجاري', [(x['value'], {'none': 'غير تجاري', 'brand_organic': 'ترويج علامتي — آفاق طويق', 'brand_content': 'شراكة إعلانية مدفوعة'}.get(x['value'], x['value'])) for x in creator.get('commercialContentTypes', [])])
    body += '<p><label><input style="width:auto" type="checkbox" name="preview_confirmed" value="yes" required> شاهدت الفيديو وراجعت النص والحسابات والموعد، وأملك حقوق نشر الفيديو والموسيقى وأوافق صراحةً على نشره بهذه الإعدادات.</label></p><button class="btn">تأكيد وجدولة النشر</button></form></div>'
    return HTMLResponse(page(body), headers={'Cache-Control': 'no-store'})


@router.post('/content-center/{content_id}/schedule')
async def schedule_post(content_id: int, request: Request):
    session = admin(request)
    data = parse(await request.body())
    csrf(session, data)
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        return message_page('الإرسال الخارجي متوقف على الخادم.', 409)
    item = one('SELECT * FROM social_content WHERE id=?', (content_id,))
    if not item:
        raise HTTPException(404)
    if item['status'] != 'approved' or publication(content_id):
        return message_page('المحتوى غير معتمد أو سبق إرسال طلب نشر له. لن يتكرر الإرسال.', 409)
    try:
        platforms = selected_platforms(item)
        key, accounts = await run_in_threadpool(checked_connection, platforms)
        creator = await run_in_threadpool(creator_info, key, accounts['tiktok']['accountId']) if 'tiktok' in platforms else None
        request_id = str(uuid.uuid4())
        # Commit the one-per-content claim BEFORE making a publishing request.
        with db() as c:
            locked = c.execute('''SELECT c.* FROM social_content c JOIN approvals a ON a.id=c.approval_id
                WHERE c.id=%s AND c.status='approved' AND a.status='approved'
                AND a.kind='social_publish' AND a.entity_type='social_content' AND a.entity_id=c.id
                FOR UPDATE OF c,a''', (content_id,)).fetchone()
            if not locked or str(locked['updated_at']) != data.get('version'):
                raise PublishingError('تغيرت المسودة أو موافقتها. افتح المراجعة مرة أخرى.')
            payload = make_payload(dict(locked), accounts, data, creator)
            claim = c.execute('''INSERT INTO social_publications(content_id,request_id,status,scheduled_at,
                payload_json,approved_by,created_at,updated_at) VALUES(%s,%s,'submitting',%s,%s,%s,%s,%s)
                ON CONFLICT(content_id) DO NOTHING RETURNING id''',
                (content_id, request_id, payload['scheduledFor'], json.dumps(payload), session['user_id'], utcnow(), utcnow())).fetchone()
            if not claim:
                raise PublishingError('سبق إرسال طلب نشر لهذه المسودة. لن يتكرر الإرسال.')
            c.execute("UPDATE social_content SET status='submitting',updated_at=%s WHERE id=%s", (utcnow(), content_id))
    except PublishingError as error:
        return message_page(str(error), 409)
    try:
        response = await run_in_threadpool(provider_request, key, 'POST', '/posts', payload=payload, request_id=request_id)
        post_id, state, results = publication_result(response, payload['platforms'])
    except PublishingError as error:
        state, post_id, results = 'needs_review', None, []
        save_result(content_id, post_id, state, results, str(error))
    else:
        save_result(content_id, post_id, state, results)
    log(session['user_id'], 'social_schedule_requested', 'social_content', content_id, state)
    return RedirectResponse('/content-center/' + str(content_id), 303)


def save_result(content_id, post_id, state, results, error=None):
    now = utcnow()
    with db() as c:
        c.execute('''UPDATE social_publications SET provider_post_id=COALESCE(%s,provider_post_id),status=%s,
            results_json=%s,last_error=%s,updated_at=%s WHERE content_id=%s''',
            (post_id, state, json.dumps(results), error, now, content_id))
        c.execute('''UPDATE social_content SET status=%s,published_at=CASE WHEN %s='published'
            THEN COALESCE(published_at,%s) ELSE NULL END,updated_at=%s WHERE id=%s''',
            (state, state, now, now, content_id))


@router.post('/content-center/{content_id}/sync-publication')
async def sync_publication(content_id: int, request: Request):
    session = admin(request)
    data = parse(await request.body())
    csrf(session, data)
    record = publication(content_id)
    if not record or not record['provider_post_id']:
        return message_page('لا يوجد معرّف نشر مؤكد. راجع قائمة المنشورات في Zernio؛ لن يُعاد الإرسال.', 409)
    try:
        key, _ = connection()
        response = await run_in_threadpool(provider_request, key, 'GET', '/posts/' + identifier(record['provider_post_id']))
        post_id, state, results = publication_result(response, json.loads(record['payload_json'])['platforms'])
        if post_id != record['provider_post_id']:
            raise PublishingError('لم يطابق الرد معرّف النشر المحفوظ.')
        save_result(content_id, post_id, state, results)
    except PublishingError as error:
        return message_page(str(error), 409)
    return RedirectResponse('/content-center/' + str(content_id), 303)


def publication_panel(content_id, session):
    record = publication(content_id)
    if not record:
        return ''
    body = '<div class="card"><h2>متابعة النشر</h2><p>' + e(STATES.get(record['status'], record['status'])) + '</p>'
    body += '<p>الموعد بتوقيت الرياض: ' + e(record['scheduled_at'].astimezone(RIYADH)) + '</p>'
    if record['provider_post_id']:
        body += '<p>مرجع Zernio: <span dir="ltr">' + e(record['provider_post_id']) + '</span></p>'
    if record['last_error']:
        body += '<p>' + e(record['last_error']) + '</p>'
    for result in json.loads(record['results_json']):
        body += '<p>' + e(result['platform']) + ': ' + e(result['status'])
        if result.get('url'):
            body += ' <a target="_blank" rel="noopener" href="' + e(result['url']) + '">فتح الفيديو</a>'
        body += '</p>'
    if session.get('role') == 'admin' and record['provider_post_id']:
        body += '<form method="post" action="/content-center/' + str(content_id) + '/sync-publication">' + hidden_csrf(session) + '<button class="btn">تحديث نتيجة النشر</button></form>'
    body += '<p><a target="_blank" rel="noopener" href="https://zernio.com/dashboard/posts-all">فتح Zernio لمراجعة الطلب أو إلغاء الجدولة</a></p></div>'
    return body
