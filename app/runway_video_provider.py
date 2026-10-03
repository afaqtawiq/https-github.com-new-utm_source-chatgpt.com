"""Narrow Runway video boundary: one fixed submission, never a paid retry.

The caller owns authorization, durable receipts, and polling cadence (at least
five seconds). This module never reads credentials or environment proxies.
"""
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

import httpx

from .media_runway import API_VERSION, RunwayError

MODEL = 'gen4.5'
DURATION = 5
RATIO = '720:1280'
# Published 12 credits/second, checked 2026-10-03. An estimate, not a
# provider-enforced spending cap. Never scrape prices or add paid options.
ESTIMATED_CREDITS = 60
PRICING_URL = 'https://docs.dev.runwayml.com/guides/pricing/'
MAX_EXPORT = 14 * 1024 * 1024
API_URL = 'https://api.dev.runwayml.com'
OUTPUT_HOST = 'dnznrvs05pmza.cloudfront.net'
# Exact host documented at https://docs.dev.runwayml.com/assets/outputs/.
# A new host requires review, not a wildcard CloudFront exception.
_UUID4 = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}')
_STATUSES = frozenset(('PENDING', 'THROTTLED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'))
_MAX_JSON = 256 * 1024
_MAX_CREDITS = Decimal(9_007_199_254_740_991)
_API_ERROR = 'لم تصل نتيجة مؤكدة من Runway. لن نكرر طلب التوليد تلقائيًا؛ راجع سجل المهمة.'
_FILE_ERROR = 'لم يجتز ملف Runway فحص فيديو MP4 ‏H.264 عمودي لمدة خمس ثوانٍ وبحجم لا يتجاوز 14 ميبيبايت.'


def validate_prompt(prompt):
    """Return the unchanged prompt after enforcing Runway's UTF-16 limit."""
    try:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError()
        if not 1 <= len(prompt.encode('utf-16-le')) // 2 <= 1000:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise RunwayError('يجب أن يكون وصف الفيديو بين 1 و1000 وحدة UTF-16.') from None
    return prompt


def _task_id(value):
    if not isinstance(value, str) or not _UUID4.fullmatch(value):
        raise RunwayError('معرّف مهمة Runway غير صالح. لن نعيد إرسال طلب التوليد.')
    return value


def _credits(value):
    """Missing/malformed cost is unknown, never zero or the local estimate."""
    raw = value.get('credits') if isinstance(value, dict) else None
    if type(raw) not in (int, float, Decimal):
        return None
    try:
        result = Decimal(str(raw))
        if result.is_finite() and 0 <= result <= _MAX_CREDITS:
            return result
    except (InvalidOperation, ValueError):
        pass
    return None


def _body(response, limit, deadline):
    length = response.headers.get('content-length')
    if length is not None:
        if not re.fullmatch(r'[0-9]{1,12}', length) or int(length) > limit:
            raise ValueError()
    chunks = []
    size = 0
    # Do not request buffered fixed-size chunks: a slow peer could otherwise
    # dribble bytes forever without yielding a chunk for the deadline check.
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > limit or time.monotonic() > deadline:
            raise ValueError()
        chunks.append(chunk)
    if size == 0 or (length is not None and size != int(length)):
        raise ValueError()
    return b''.join(chunks)


def _api_request(key, method, path, payload=None):
    """Only these two operations may carry an API credential."""
    if not ((method == 'POST' and path == '/v1/text_to_video') or
            (method == 'GET' and isinstance(path, str) and
             path.startswith('/v1/tasks/') and _UUID4.fullmatch(path[10:]) and payload is None)):
        raise RunwayError('عملية Runway غير مسموحة.')
    try:
        if not isinstance(key, str) or not 1 <= len(key) <= 4096 or any(
                ord(c) < 33 or ord(c) > 126 for c in key):
            raise ValueError()
        headers = {'Authorization': 'Bearer ' + key, 'X-Runway-Version': API_VERSION,
                   'Accept': 'application/json', 'Accept-Encoding': 'identity'}
        deadline = time.monotonic() + 45
        # HTTPX's default transport has zero retries. No application retry,
        # SDK retry, redirects, proxy environment, or fallback endpoint exists.
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            with client.stream(method, API_URL + path, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    raise ValueError()
                if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                    raise ValueError()
                data = json.loads(_body(response, _MAX_JSON, deadline), parse_float=Decimal)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (httpx.HTTPError, ValueError, TypeError, OverflowError, RecursionError):
        # In particular, a timeout may follow acceptance. Never resubmit.
        raise RunwayError(_API_ERROR) from None


def submit(key, prompt):
    """Submit exactly once and preserve a valid receipt even if cost is unknown."""
    data = _api_request(key, 'POST', '/v1/text_to_video', {
        'model': MODEL, 'promptText': validate_prompt(prompt), 'duration': DURATION,
        'ratio': RATIO, 'outputFormat': 'mp4',
    })
    return {'task_id': _task_id(data.get('id')),
            'estimated_credits': _credits(data.get('estimatedCost'))}


def output_url(value):
    """Allow only the documented HTTPS media origin, never a caller's host."""
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 8192:
            raise ValueError()
        # URL parsers can discard controls or normalize backslashes/authority.
        if any(ord(c) <= 32 or ord(c) >= 127 for c in value) or '\\' in value:
            raise ValueError()
        url = urlsplit(value)
        if (url.scheme != 'https' or url.netloc != OUTPUT_HOST or url.username is not None or
                url.password is not None or url.port is not None or url.fragment or '#' in value):
            raise ValueError()
        if (not url.path.startswith('/') or not url.path.lower().endswith('.mp4') or
                '%' in url.path or any(part in ('.', '..') for part in url.path.split('/'))):
            raise ValueError()
    except (ValueError, TypeError):
        raise RunwayError('رابط نتيجة Runway غير معتمد. يلزم مراجعة مصدر الملف.') from None
    return value


def poll(key, task_id):
    """Read a receipt, exposing no provider failure body or ephemeral URL early."""
    task_id = _task_id(task_id)
    data = _api_request(key, 'GET', '/v1/tasks/' + task_id)
    if data.get('id') != task_id:
        raise RunwayError('لم يطابق معرّف نتيجة Runway مهمة الإنتاج.')
    status = data.get('status')
    if not isinstance(status, str) or status not in _STATUSES:
        raise RunwayError('حالة مهمة Runway غير معروفة. راجع سجل المهمة دون إعادة التوليد.')
    result = {'status': status.lower(), 'cost_credits': None}
    if status in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
        result['cost_credits'] = _credits(data.get('cost'))
    if status == 'SUCCEEDED':
        outputs = data.get('output')
        if not isinstance(outputs, list) or len(outputs) != 1:
            raise RunwayError('لم ترجع مهمة Runway ملف فيديو واحدًا مطابقًا للطلب.')
        result['output_url'] = output_url(outputs[0])
    return result


def download(url):
    """Download ephemeral output immediately; callers may poll for a fresh URL.

    This request never carries a Runway credential, cookie, or caller header.
    Redirects and unknown CDN origins fail closed. Validate before exporting.
    """
    url = output_url(url)
    try:
        deadline = time.monotonic() + 90
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            with client.stream('GET', url, headers={'Accept-Encoding': 'identity'}) as response:
                if response.status_code != 200:
                    raise ValueError()
                if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                    raise ValueError()
                payload = _body(response, MAX_EXPORT, deadline)
        validate_file(payload)
        return payload
    except RunwayError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, OverflowError):
        raise RunwayError('تعذر تنزيل ملف Runway المعتمد. يمكن تحديث نتيجة المهمة دون إعادة التوليد.') from None


def _mp4(payload):
    """Reject non-MP4 containers before invoking a local media parser."""
    if type(payload) is not bytes or not 24 <= len(payload) <= MAX_EXPORT:
        raise ValueError()
    size = int.from_bytes(payload[:4], 'big')
    if payload[4:8] != b'ftyp' or not 16 <= size <= min(len(payload), 1024) or size % 4:
        raise ValueError()
    brands = {payload[8:12], *(payload[i:i + 4] for i in range(16, size, 4))}
    if b'qt  ' in brands or not brands.intersection({b'isom', b'iso2', b'iso5', b'iso6', b'avc1', b'mp41', b'mp42'}):
        raise ValueError()


def validate_file(payload):
    """Decode/count real local H.264 frames and return sanitized export metadata."""
    try:
        _mp4(payload)
        probe = shutil.which('ffprobe', path=os.defpath)
        if not probe:
            raise ValueError()
        with tempfile.TemporaryDirectory(prefix='runway-video-') as directory:
            path = Path(directory) / 'output.mp4'
            path.write_bytes(payload)
            command = [probe, '-v', 'error', '-protocol_whitelist', 'file',
                       '-format_whitelist', 'mov', '-enable_drefs', '0', '-use_absolute_path', '0',
                       '-threads', '1', '-count_frames', '-show_entries',
                       'format=format_name,duration:stream=codec_type,codec_name,width,height,duration,nb_frames,nb_read_frames'
                       ':stream_disposition=attached_pic:stream_tags=rotate:stream_side_data=rotation',
                       '-of', 'json', str(path)]
            completed = subprocess.run(command, capture_output=True, timeout=30, check=False,
                                       env={'PATH': os.defpath, 'LANG': 'C'})
        if completed.returncode != 0 or completed.stderr or len(completed.stdout) > 64 * 1024:
            raise ValueError()
        metadata = json.loads(completed.stdout)
        streams = metadata.get('streams')
        if not isinstance(streams, list) or any(not isinstance(s, dict) for s in streams):
            raise ValueError()
        videos = [s for s in streams if s.get('codec_type') == 'video']
        if len(videos) != 1 or any(s.get('codec_type') not in ('video', 'audio') for s in streams):
            raise ValueError()
        video = videos[0]
        if (video.get('codec_name') != 'h264' or video.get('width') != 720 or
                video.get('height') != 1280 or int(video.get('nb_read_frames', 0)) < 1 or
                int(video.get('nb_read_frames', 0)) != int(video.get('nb_frames', 0)) or
                video.get('disposition', {}).get('attached_pic', 0)):
            raise ValueError()
        rotations = [video.get('tags', {}).get('rotate', 0)]
        rotations += [s.get('rotation', 0) for s in video.get('side_data_list', [])]
        if any(Decimal(str(rotation)) != 0 for rotation in rotations):
            raise ValueError()
        container = metadata.get('format', {})
        if 'mp4' not in container.get('format_name', '').split(','):
            raise ValueError()
        durations = [Decimal(str(container.get('duration'))), Decimal(str(video.get('duration')))]
        if any(not duration.is_finite() or not Decimal('4.8') <= duration <= Decimal('5.3')
               for duration in durations):
            raise ValueError()
        return {'container': 'mp4', 'codec': 'h264', 'width': 720, 'height': 1280,
                'duration': float(durations[0]), 'size': len(payload)}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError,
            InvalidOperation, OverflowError, RecursionError):
        raise RunwayError(_FILE_ERROR) from None
