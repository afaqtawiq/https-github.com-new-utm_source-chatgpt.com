"""Fixed fal models and sanitized provider boundary; never retry submissions."""
from decimal import Decimal, InvalidOperation, ROUND_UP
import json
import re
from urllib.parse import urlsplit

import httpx

IMAGE_MODEL = 'fal-ai/bytedance/seedream/v4/text-to-image'
VIDEO_MODEL = 'fal-ai/kling-video/v2.5-turbo/pro/image-to-video'
MODELS = {'image': IMAGE_MODEL, 'video': VIDEO_MODEL}
QUEUE = 'https://queue.fal.run/'
PRICING = 'https://api.fal.ai/v1/models/pricing'


class MediaError(ValueError):
    pass


def call(key, method, url, *, payload=None, params=None):
    headers = {'Authorization': 'Key ' + key}
    if method == 'POST':
        headers.update({'X-Fal-No-Retry': '1',
                        'X-Fal-Object-Lifecycle-Preference': json.dumps({'expiration_duration_seconds': None})})
    try:
        with httpx.Client(timeout=40, follow_redirects=False) as client:
            response = client.request(method, url, headers=headers, json=payload, params=params)
        if response.status_code not in (200, 201, 202):
            if response.status_code in (401, 403):
                raise MediaError('رفضت fal.ai صلاحية المفتاح. راجع مفتاح الحساب وصلاحية API.')
            if response.status_code == 402:
                raise MediaError('الرصيد غير كافٍ لدى fal.ai. راجع رصيد الحساب.')
            raise MediaError('تعذر إتمام الطلب لدى fal.ai (HTTP ' + str(response.status_code) + ').')
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except MediaError:
        raise
    except (httpx.HTTPError, ValueError):
        raise MediaError('لم تصل نتيجة مؤكدة من fal.ai. لن نكرر طلب التوليد تلقائيًا.') from None


def prices(key):
    data = call(key, 'GET', PRICING, params={'endpoint_id': IMAGE_MODEL + ',' + VIDEO_MODEL})
    if not isinstance(data.get('prices'), list):
        raise MediaError('تعذر قراءة الأسعار من fal.ai. لم يبدأ التوليد.')
    result = {}
    for stage, model in MODELS.items():
        matches = [p for p in data.get('prices', []) if isinstance(p, dict) and p.get('endpoint_id') == model]
        if len(matches) != 1 or matches[0].get('currency') != 'USD':
            raise MediaError('تعذر التحقق من تكلفة الإنتاج بالدولار. لم يبدأ التوليد.')
        entry = matches[0]
        units = {'image': 1} if stage == 'image' else {'second': 5, 'video': 1}
        if entry.get('unit') not in units:
            raise MediaError('تغيرت وحدة تسعير النموذج. يلزم مراجعة التكلفة قبل التشغيل.')
        try:
            amount = Decimal(str(entry['unit_price'])) * units[entry['unit']]
            if not amount.is_finite() or amount <= 0 or amount > 20:
                raise ValueError()
            result[stage] = amount.quantize(Decimal('.000001'), rounding=ROUND_UP)
        except (KeyError, InvalidOperation, ValueError):
            raise MediaError('تعذر حساب تكلفة الإنتاج. لم يبدأ التوليد.') from None
    return result


def asset_url(value, stage):
    if not isinstance(value, str) or len(value) > 4096:
        raise MediaError('لم تُرجع fal.ai رابط ملف صالحًا.')
    try:
        u = urlsplit(value)
        host = u.hostname or ''
        if u.scheme != 'https' or u.username or u.password or u.port not in (None, 443) or u.fragment:
            raise ValueError()
        allowed = host == 'fal.media' or host.endswith('.fal.media')
        allowed |= host == 'storage.googleapis.com' and u.path.startswith('/falserverless/')
        if not allowed or '..' in u.path or '%' in u.path:
            raise ValueError()
        extensions = ('.mp4', '.mov', '.webm') if stage == 'video' else ('.png', '.jpg', '.jpeg', '.webp')
        if not u.path.lower().endswith(extensions):
            raise ValueError()
    except ValueError:
        raise MediaError('رابط النتيجة غير معتمد. راجع الملف في لوحة fal.ai.') from None
    return value


def queue_url(value, model, request_id, status=False):
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,128}', request_id):
        raise MediaError('معرّف مهمة fal.ai غير صالح؛ راجع لوحة المنصة.')
    try:
        u = urlsplit(value)
        parts = model.split('/')
        roots = {'/'.join(parts[:count]) for count in range(2, len(parts) + 1)}
        suffixes = ['/status'] if status else ['', '/response']
        paths = {'/' + root + '/requests/' + request_id + suffix for root in roots for suffix in suffixes}
        if u.scheme != 'https' or u.netloc != 'queue.fal.run' or u.path not in paths or u.query or u.fragment:
            raise ValueError()
    except (TypeError, ValueError):
        raise MediaError('عنوان متابعة fal.ai غير صالح؛ لن يُرسل المفتاح إلى عنوان آخر.') from None
    return value


def submit(key, stage, prompt, *, ratio='9:16', image_url=None):
    model = MODELS[stage]
    if stage == 'image':
        payload = {'prompt': prompt, 'image_size': 'portrait_16_9' if ratio == '9:16' else 'landscape_16_9',
                   'num_images': 1, 'max_images': 1, 'enable_safety_checker': True}
    else:
        payload = {'prompt': prompt, 'image_url': asset_url(image_url, 'image'), 'duration': '5',
                   'negative_prompt': 'distorted truck, sliding wheels, impossible motion, flicker, illegible text', 'cfg_scale': 0.5}
    data = call(key, 'POST', QUEUE + model, payload=payload)
    rid = data.get('request_id')
    return {'request_id': rid,
            'status_url': queue_url(data.get('status_url'), model, rid, status=True),
            'response_url': queue_url(data.get('response_url'), model, rid)}


def result(key, stage, receipt):
    model = MODELS[stage]
    rid = receipt['request_id']
    status = call(key, 'GET', queue_url(receipt['status_url'], model, rid, status=True))
    if status.get('request_id', rid) != rid:
        raise MediaError('لم يطابق معرّف النتيجة طلب الإنتاج.')
    if status.get('status') in ('IN_QUEUE', 'IN_PROGRESS'):
        return None
    if status.get('status') != 'COMPLETED' or status.get('error') or status.get('error_type'):
        raise MediaError('تعذر إكمال التوليد لدى fal.ai. راجع سجل المهمة قبل إنشاء طلب جديد.')
    data = call(key, 'GET', queue_url(receipt['response_url'], model, rid))
    if stage == 'image':
        images = data.get('images')
        if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
            raise MediaError('لم تُرجع fal.ai صورة واحدة مطابقة للطلب.')
        return asset_url(images[0].get('url'), stage)
    video = data.get('video')
    return asset_url(video.get('url') if isinstance(video, dict) else None, stage)
