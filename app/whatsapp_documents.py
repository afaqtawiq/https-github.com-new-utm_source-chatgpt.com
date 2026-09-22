"""Read customer shipping attachments without treating document text as commands.

Arrival dates require a tracking source; bill issue dates are never ETAs.
"""
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

import httpx

from app.document_parsing import document_metadata


def document_indexes(message):
    return [i for i, a in enumerate(message.get('attachments') or [])
            if isinstance(a, dict) and (a.get('type') in ('document', 'file', 'image')
            or a.get('mimeType') in ('application/pdf', 'image/jpeg', 'image/png', 'image/webp'))]


def summarize(text):
    # Match carrier names, not container-owner prefixes (leased boxes differ).
    names = ('CMA CGM', 'MAERSK', 'MEDITERRANEAN SHIPPING', 'COSCO',
             'HAPAG-LLOYD', 'EVERGREEN', 'OOCL', 'OCEAN NETWORK EXPRESS',
             'PACIFIC INTERNATIONAL LINES', 'FOLK MARITIME', 'SEALEAD')
    upper = re.sub(r'\s+', ' ', text.upper())
    matches = [name for name in names if name in upper]
    carrier = matches[0] if len(matches) == 1 else ''
    _, bill, containers = document_metadata(text, carrier)
    data = {'carrier': carrier, 'bill': bill, 'containers': containers,
            'tracking_status': 'not_verified', 'eta': None}
    if not bill and not containers:
        return data, 'لم أتمكن من قراءة رقم البوليصة أو الحاوية بوضوح. أرسل ملف البوليصة الأصلي أو صورة أوضح.'
    lines = ['استلمنا مستند الشحنة.',
             'شركة الملاحة: ' + (carrier or 'تحتاج تأكيدًا من البوليصة'),
             'رقم البوليصة: ' + (bill or 'غير واضح'),
             'الحاويات: ' + (containers or 'غير ظاهرة'),
             'حالة الشحنة وموعد الوصول: لم يتم التحقق من التتبع بعد.']
    if 'DRAFT' in upper:
        lines.append('المستند مسودة بوليصة.')
    if carrier == 'CMA CGM':
        lines.append('صفحة التتبع: https://www.cma-cgm.com/ebusiness/tracking')
    return data, '\n'.join(lines)


async def read_attachment(payload, index):
    from app.whatsapp_admin import safe_media_url
    from app.shipping_agents import extract_document_text
    message, account = payload['message'], payload['account']
    message_id = message.get('platformMessageId')
    if not message_id:
        raise ValueError('Missing provider message id')
    path = '/inbox/conversations/' + quote(payload['conversation']['id'], safe='')
    path += '/messages/' + quote(message_id, safe='') + f'/attachments/{index}'
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.get('https://zernio.com/api/v1' + path,
            params={'accountId': account.get('accountId') or account['id'], 'format': 'json'},
            headers={'Authorization': 'Bearer ' + os.environ['ZERNIO_API_KEY']})
        response.raise_for_status()
        url = response.json().get('url')
        if not safe_media_url(url):
            raise ValueError('Unsupported attachment host')
        chunks, size = [], 0
        async with client.stream('GET', url) as media:
            media.raise_for_status()
            async for chunk in media.aiter_bytes():
                size += len(chunk)
                if size > 10 * 1024 * 1024:
                    raise ValueError('Attachment exceeds 10 MB')
                chunks.append(chunk)
    content = b''.join(chunks)
    if content.startswith(b'%PDF-'):
        suffix, mime = '.pdf', 'application/pdf'
    elif content.startswith(b'\xff\xd8\xff'):
        suffix, mime = '.jpg', 'image/jpeg'
    elif content.startswith(b'\x89PNG\r\n\x1a\n'):
        suffix, mime = '.png', 'image/png'
    elif content.startswith(b'RIFF') and content[8:12] == b'WEBP':
        suffix, mime = '.webp', 'image/webp'
    else:
        raise ValueError('Unsupported document signature')
    with tempfile.TemporaryDirectory(prefix='wa-bill-') as directory:
        path = Path(directory) / ('document' + suffix)
        path.write_bytes(content)
        text = extract_document_text(path, mime)
    return summarize(text)
