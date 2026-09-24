"""Bounded local text/OCR extraction. No network I/O is available in this module."""
import io
import re
import subprocess
import tempfile
import time
import warnings
from pathlib import Path

from PIL import Image
from app.fasah_fields import reject_credentials

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 10
MAX_TEXT = 150000


def extract_document(data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError('الحد الأقصى للمستند 10 ميجابايت.')
    is_pdf = data.startswith(b'%PDF-')
    if not is_pdf and not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff')):
        raise ValueError('الأنواع المتاحة: PDF وPNG وJPEG فقط.')
    deadline = time.monotonic() + 90

    def run(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('انتهت مهلة القراءة. قسّم المستند أو استخدم النص المنسوخ.')
        try:
            result = subprocess.run(args, capture_output=True, timeout=min(25, remaining), check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError('تعذرت القراءة المحلية أو انتهت مهلتها. استخدم النص المنسوخ أو مستندًا أوضح.') from None
        if result.returncode:
            raise ValueError('تعذر قراءة المستند. تأكد أنه سليم وغير محمي بكلمة مرور.')
        return result.stdout.decode('utf-8', errors='replace')

    notes = []
    with tempfile.TemporaryDirectory(prefix='afaq-fasah-') as temporary:
        root = Path(temporary)
        source = root / ('source.pdf' if is_pdf else 'source.png')
        if is_pdf:
            source.write_bytes(data)
            info = run(['pdfinfo', str(source)])
            count = re.search(r'^Pages:\s*(\d+)', info, re.M)
            if not count or re.search(r'^Encrypted:\s*yes', info, re.M):
                raise ValueError('لا يمكن قراءة هذا الملف. ارفع PDF سليمًا غير مشفر.')
            page_count = int(count.group(1))
            if not 1 <= page_count <= MAX_PAGES:
                raise ValueError('الحد الأقصى 10 صفحات لكل ملف. قسّم المستند؛ لا تُهمل الصفحات.')
        else:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(data)) as original:
                        if original.width * original.height > 20000000:
                            raise ValueError('الصورة كبيرة جدًا. الحد 20 مليون بكسل.')
                        original.load()
                        original.convert('RGB').save(source, 'PNG')
            except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise ValueError('تعذر قراءة الصورة أو تجاوزت الحجم الآمن.') from None
            page_count = 1
        pages = []
        languages = None
        for page_number in range(1, page_count + 1):
            text = run(['pdftotext', '-f', str(page_number), '-l', str(page_number), '-layout', '-enc', 'UTF-8', str(source), '-']) if is_pdf else ''
            method = 'نص PDF'
            if len(text.strip()) < 35:
                if languages is None:
                    languages = run(['tesseract', '--list-langs'])
                    if not re.search(r'^eng$', languages, re.M):
                        raise ValueError('محرك القراءة غير جاهز. استخدم النص المنسوخ مؤقتًا.')
                    if not re.search(r'^ara$', languages, re.M):
                        notes.append('القراءة العربية للصور غير متاحة في هذه البيئة؛ راجع النص أو الصقه يدويًا.')
                image_path = source
                if is_pdf:
                    prefix = root / 'page'
                    run(['pdftoppm', '-f', str(page_number), '-l', str(page_number), '-singlefile', '-scale-to', '2500', '-png', str(source), str(prefix)])
                    image_path = root / 'page.png'
                text = run(['tesseract', str(image_path), 'stdout', '-l', 'eng+ara' if re.search(r'^ara$', languages, re.M) else 'eng', '--psm', '3'])
                method = 'OCR — يحتاج مطابقة مع الأصل'
            reject_credentials(text)
            if len(text) + sum(len(p['text']) for p in pages) > MAX_TEXT:
                raise ValueError('النص كبير جدًا. قسّم المستند إلى ملفات أصغر.')
            if not text.strip():
                notes.append('تعذر استخراج نص الصفحة ' + str(page_number) + '؛ راجع الأصل يدويًا.')
            pages.append({'page': page_number, 'text': text.strip(), 'method': method})
        if not any(p['text'] for p in pages):
            raise ValueError('لم يُستخرج نص مقروء. ارفع صورة أوضح أو الصق النص.')
        return pages, notes
