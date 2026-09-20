"""Zernio publishing contract; no credentials or remote responses are logged."""
import datetime as dt
import ipaddress
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

API = 'https://zernio.com/api/v1'
TARGETS = {'youtube': 'afaqtaw', 'tiktok': 'afaqtawaiq6'}
PLATFORMS = {'YouTube': ('youtube',), 'TikTok': ('tiktok',), 'YouTube+TikTok': ('youtube', 'tiktok')}
RIYADH = ZoneInfo('Asia/Riyadh')


class PublishingError(Exception):
    """Only safe, application-owned messages leave the provider boundary."""


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{24}', value):
        raise PublishingError('معرّف النشر غير صالح؛ راجع الربط في Zernio.')
    return value


def provider_request(key, method, path, *, payload=None, request_id=None):
    headers = {'Authorization': 'Bearer ' + key}
    if request_id:
        headers['x-request-id'] = request_id
    try:
        with httpx.Client(timeout=45, follow_redirects=False) as client:
            response = client.request(method, API + path, headers=headers, json=payload)
        # Do not expose response bodies: some providers include credential context.
        if response.status_code not in (200, 201, 207):
            raise PublishingError('تعذر إتمام الطلب لدى Zernio (HTTP ' + str(response.status_code) + '). راجع لوحة Zernio.')
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (httpx.HTTPError, ValueError):
        raise PublishingError('لم تصل نتيجة مؤكدة من Zernio. راجع لوحة النشر قبل أي محاولة أخرى.') from None


def handle(value):
    return str(value or '').strip().lstrip('@').lower()


def verified_accounts(key, required=tuple(TARGETS)):
    data = provider_request(key, 'GET', '/accounts')
    accounts = data.get('accounts')
    if not isinstance(accounts, list):
        raise PublishingError('تعذر قراءة الحسابات المتصلة.')
    verified = {}
    for platform in required:
        matches = [a for a in accounts if isinstance(a, dict) and a.get('platform') == platform
                   and handle(a.get('username')) == TARGETS[platform] and a.get('isActive') is True]
        if len(matches) != 1:
            raise PublishingError('يلزم ربط حساب ' + platform + ' @' + TARGETS[platform] + ' في حساب Zernio المخصص لآفاق.')
        account_id = identifier(matches[0].get('_id'))
        health = provider_request(key, 'GET', '/accounts/' + account_id + '/health')
        if (health.get('platform') != platform or handle(health.get('username')) != TARGETS[platform]
                or health.get('accountId') != account_id
                or health.get('tokenStatus', {}).get('valid') is not True
                or health.get('permissions', {}).get('canPost') is not True):
            raise PublishingError('صلاحية النشر غير جاهزة للحساب @' + TARGETS[platform] + '. أعد ربطه في Zernio.')
        verified[platform] = {'accountId': account_id, 'username': TARGETS[platform]}
    return verified


def media_url(value):
    value = str(value or '').strip()
    try:
        u = urlsplit(value)
        host = u.hostname or ''
        port = u.port
    except ValueError:
        raise PublishingError('رابط الفيديو غير صالح.') from None
    if (u.scheme != 'https' or not host or u.username or u.password or u.fragment
            or port not in (None, 443) or '.' not in host
            or host.endswith(('.localhost', '.local', '.internal'))):
        raise PublishingError('أدخل رابط HTTPS عامًا ومباشرًا لملف الفيديو.')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if host == 'localhost' or (address and not address.is_global):
        raise PublishingError('يلزم رابط فيديو عام.')
    if not u.path.lower().endswith(('.mp4', '.mov', '.webm')):
        raise PublishingError('استخدم رابط ملف MP4 أو MOV أو WebM مباشر، وليس رابط صفحة مشاهدة.')
    return value


def schedule_time(value, now=None):
    try:
        result = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        raise PublishingError('حدد موعد نشر صحيحًا بتوقيت الرياض.') from None
    if result.tzinfo is None:
        result = result.replace(tzinfo=RIYADH)
    result = result.astimezone(dt.timezone.utc)
    if result < (now or dt.datetime.now(dt.timezone.utc)) + dt.timedelta(minutes=5):
        raise PublishingError('اختر موعدًا بعد خمس دقائق على الأقل؛ الموعد الماضي لا يتحول إلى نشر فوري.')
    return result


def creator_info(key, account_id):
    return provider_request(key, 'GET', '/accounts/' + identifier(account_id) + '/tiktok/creator-info?mediaType=video')


def make_payload(item, accounts, form, creator=None, now=None):
    platforms = PLATFORMS.get(item.get('platform'))
    if not platforms or item.get('content_type') not in ('video', 'reel'):
        raise PublishingError('الجدولة متاحة للفيديو والريلز على YouTube وTikTok فقط. أنشئ مسودة بهذه الخيارات.')
    if form.get('preview_confirmed') != 'yes':
        raise PublishingError('راجع الفيديو والنص والحسابات ثم أكد موافقتك على النشر.')
    scheduled = schedule_time(form.get('scheduled_at'), now)
    body, title = str(item.get('body') or '').strip(), str(item.get('title') or '').strip()
    if not body or not title or len(title) > 100 or len(body) > (2200 if 'tiktok' in platforms else 5000):
        raise PublishingError('العنوان مطلوب وبحد أقصى 100 حرف؛ النص حتى 2200 حرف لتيك توك و5000 ليوتيوب.')
    synthetic = form.get('synthetic')
    if synthetic not in ('yes', 'no'):
        raise PublishingError('حدد هل يحتوي الفيديو على مشاهد أو صوت واقعي مولّد بالذكاء الاصطناعي.')
    payload = {'content': body, 'title': title, 'mediaItems': [{'type': 'video', 'url': media_url(item.get('media_url'))}],
               'platforms': [], 'scheduledFor': scheduled.isoformat(), 'timezone': 'Asia/Riyadh',
               'publishNow': False, 'metadata': {'afaaqContentId': str(item['id'])}}
    for platform in platforms:
        account = accounts.get(platform, {})
        if account.get('username') != TARGETS[platform]:
            raise PublishingError('الحساب المحدد لا يطابق حساب آفاق المعتمد.')
        entry = {'platform': platform, 'accountId': identifier(account.get('accountId'))}
        if platform == 'youtube':
            visibility, kids = form.get('youtube_visibility'), form.get('made_for_kids')
            if visibility not in ('public', 'private', 'unlisted') or kids not in ('yes', 'no'):
                raise PublishingError('حدد ظهور الفيديو وما إذا كان موجّهًا للأطفال.')
            entry['platformSpecificData'] = {'title': title, 'visibility': visibility,
                                            'madeForKids': kids == 'yes', 'containsSyntheticMedia': synthetic == 'yes'}
        payload['platforms'].append(entry)
    if 'tiktok' in platforms:
        if not isinstance(creator, dict) or creator.get('creator', {}).get('canPostMore') is not True:
            raise PublishingError('تيك توك لا يؤكد إمكانية النشر الآن. راجع حد النشر وحالة الحساب.')
        privacy = form.get('tiktok_privacy')
        allowed = {x.get('value') for x in creator.get('privacyLevels', []) if isinstance(x, dict)}
        if privacy not in allowed:
            raise PublishingError('اختر ظهورًا متاحًا لحساب تيك توك.')
        settings = {'privacy_level': privacy, 'content_preview_confirmed': True, 'express_consent_given': True,
                    'videoMadeWithAi': synthetic == 'yes'}
        toggles = creator.get('postingLimits', {}).get('interactionSettings', {})
        for field in ('allow_comment', 'allow_duet', 'allow_stitch'):
            value = form.get(field)
            if value not in ('yes', 'no') or not isinstance(toggles.get(field), dict):
                raise PublishingError('حدد إعدادات التعليقات والدويتو والدمج لتيك توك.')
            if value == 'yes' and toggles[field].get('enabled') is not True:
                raise PublishingError('إحدى خيارات التفاعل غير متاحة لهذا الحساب.')
            settings[field] = value == 'yes'
        commercial = form.get('commercial_content')
        if commercial not in {x.get('value') for x in creator.get('commercialContentTypes', []) if isinstance(x, dict)}:
            raise PublishingError('حدد نوع الإفصاح التجاري المتاح لحساب تيك توك.')
        if commercial == 'brand_content' and privacy == 'SELF_ONLY':
            raise PublishingError('المحتوى الإعلاني بالشراكة لا يمكن أن يكون خاصًا على تيك توك.')
        settings['commercialContentType'] = commercial
        payload['tiktokSettings'] = settings
    return payload


def publication_result(data, expected):
    post = data.get('post') or data.get('existingPost')
    if not isinstance(post, dict):
        raise PublishingError('لم يصل معرّف طلب نشر موثوق. راجع Zernio قبل إعادة المحاولة.')
    post_id = identifier(post.get('_id'))
    platforms = post.get('platforms')
    if not isinstance(platforms, list):
        raise PublishingError('نتيجة النشر لا تتضمن الحسابات المستهدفة.')
    expected_pairs = {(p['platform'], p['accountId']) for p in expected}
    actual, results = set(), []
    for p in platforms:
        account = p.get('accountId')
        account_id = account.get('_id') if isinstance(account, dict) else account
        actual.add((p.get('platform'), account_id))
        url = p.get('platformPostUrl') or ''
        u = urlsplit(url)
        allowed_hosts = {'youtube': {'www.youtube.com', 'youtube.com', 'youtu.be'}, 'tiktok': {'www.tiktok.com', 'tiktok.com'}}
        if u.scheme != 'https' or u.hostname not in allowed_hosts.get(p.get('platform'), set()) or u.username or u.password:
            url = ''
        results.append({'platform': p.get('platform'), 'accountId': account_id, 'status': str(p.get('status') or 'unknown'), 'url': url})
    if actual != expected_pairs or len(platforms) != len(expected_pairs):
        raise PublishingError('حسابات نتيجة النشر لا تطابق الحسابات المعتمدة؛ يلزم فحص Zernio.')
    state = post.get('status')
    if state not in ('scheduled', 'publishing', 'published', 'partial', 'failed', 'cancelled'):
        state = 'needs_review'
    if state == 'published' and not all(p['status'] == 'published' for p in results):
        state = 'needs_review'
    return post_id, state, results
