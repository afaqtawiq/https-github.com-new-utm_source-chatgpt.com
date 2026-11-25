"""Read a SABER shipment certificate (شهادة إرسالية / SC) straight from the PDF's own text layer — no model, no website.

Owner, 25 Nov 2026: Faisal answered «لم أتمكن من التحقق من نتيجة سابر الرسمية» to an attached Promate SABER certificate
(CN-26-2651891, 30 pages). The certificate itself carries everything the clearance desk needs: number, issue/expiry,
conformity body, CR, and per product the HS code, model, trademark, product certificate (PC) number or «not subject to
technical regulations», technical regulation, quantity and the commercial invoice it covers. Read-only.
"""
import datetime as dt
import os
import re
import subprocess
import tempfile
import unicodedata

RIYADH = dt.timezone(dt.timedelta(hours=3))
MARKS = re.compile('[‎‏‪-‮⁦-⁩]')


def pdf_pages(data, max_pages=60):
    """Text of each page via pdftotext (bounded: size, pages, time). [] if not a readable PDF."""
    if not data or not data.startswith(b'%PDF') or len(data) > 15 * 1024 * 1024:
        return []
    with tempfile.TemporaryDirectory(prefix='afaq-saber-') as tmp:
        path = os.path.join(tmp, 'c.pdf')
        with open(path, 'wb') as fh:
            fh.write(data)
        try:
            out = subprocess.run(['pdftotext', '-layout', '-enc', 'UTF-8', '-l', str(max_pages), path, '-'],
                                 capture_output=True, timeout=40, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return []
    if out.returncode:
        return []
    return [clean(p) for p in out.stdout.decode('utf-8', 'replace').split('\f') if p.strip()]


def clean(text):
    return MARKS.sub('', unicodedata.normalize('NFKC', text))


def is_saber(text):
    t = clean(text)
    return bool(re.search(r'Shipment (?:Conformity )?certificate for imported products|شهادة إرسالية|Product Conformity Certificate', t, re.I))


def _f(pattern, text):
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ''


def _date(value):
    try:
        return dt.datetime.strptime(value, '%d/%m/%Y').date()
    except ValueError:
        return None


def parse(pages):
    full = '\n'.join(pages)
    head = {
        'number': _f(r'Certificate Number\s+(\S+)', full),
        'type': _f(r'Certificate Type\s+(.+?)(?:\s{2,}|\n)', full),
        'issue': _f(r'Issue Date\s+(\d{2}/\d{2}/\d{4})', full),
        'expiry': _f(r'Expire Date\s+(\d{2}/\d{2}/\d{4})', full),
        'cr': _f(r'Commercial Registration No\.\s+([\d /]+)', full),
        'country': _f(r'Shipment Country\s+(\w[\w ]*)', full),
        'body': _f(r'\.{3,}\s*([^.\n]*?(?:LLC|Ltd|LTD|GmbH|Limited|branch|Co\.)[^.\n]*?)\s*\.{3,}', full),
        'acceptance': _f(r'\.{3,}\s*(\d{3,6})\s*\.{3,}', full),
    }
    products, quantities, licences = [], [], []
    for page in pages:
        hs = _f(r'HS Code\s+(\d{6,12})', page)
        if re.search(r'Product Name', page) and re.search(r'Manufacturer Name|Technical Regulation', page):
            pc = _f(r'Product Certificate No\.\s+(\S+)', page)
            products.append({'hs': hs, 'name': _f(r'Product Name\s+(.+?)(?:\s{2,}|\n)', page),
                             'model': _f(r'Moda?l Name\s+(.+?)(?:\s{2,}|\n)', page), 'trademark': _f(r'Trademark\s+(.+?)(?:\s{2,}|\n)', page),
                             'pc': pc if pc and not pc.lower().startswith(('modal', 'model')) else '',
                             'regulation': _f(r'Technical Regulation\s+(.+?)(?:\s{2,}|\n|$)', page),
                             'manufacturer': _f(r'Manufacturer Name\s+(.+?)(?:\s{2,}|\n)', page),
                             'not_regulated': 'غير خاضع للوائح' in page or 'ليس خاضعًا لأى من اللوائح' in page})
        elif re.search(r'\bQuantity\s+\d', page) and re.search(r'Invoice Number', page):
            inv = re.search(r'Invoices? Currency\s*\n\s*(\S+)\s+(\d{2}/\d{2}/\d{4})\s+([\d.,]+)\s+(.+)', page)
            quantities.append({'hs': hs, 'model': _f(r'Model Name\s+(.+?)(?:\s{2,}|\n)', page), 'quantity': _f(r'Quantity\s+([\d.,]+)', page),
                               'unit': _f(r'Unit\s+(\w+)', page), 'invoice': inv.group(1) if inv else '', 'invoice_date': inv.group(2) if inv else '',
                               'amount': inv.group(3) if inv else '', 'currency': inv.group(4).strip() if inv else ''})
        elif re.search(r'License Number|License Status', page):
            licences.append({'hs': hs, 'model': _f(r'Model Name\s+(.+?)(?:\s{2,}|\n)', page), 'total': _f(r'Total Quantities\s+([\d.,]+)', page),
                             'not_regulated': 'غير خاضع للوائح' in page, 'no_licence': bool(re.search(r'Does not hold a license', page, re.I))})
    return dict(head, products=products, quantities=quantities, licences=licences, pages=len(pages))


def summary(cert, today=None):
    today = today or dt.datetime.now(RIYADH).date()
    exp = _date(cert['expiry'])
    if exp is None:
        validity = 'تاريخ الانتهاء غير مقروء — راجع الأصل'
    elif exp < today:
        validity = f"⛔ منتهية منذ {cert['expiry']}"
    else:
        validity = f"✅ سارية حتى {cert['expiry']} (باقي {(exp - today).days} يوم)"
    out = [f"📄 شهادة سابر — شهادة إرسالية (SC) رقم {cert['number'] or 'غير مقروء'}",
           f"• الحالة: {validity} | الإصدار {cert['issue'] or '—'}",
           f"• جهة المطابقة: {cert['body'] or '—'}" + (f" (رقم القبول {cert['acceptance']})" if cert['acceptance'] else ''),
           f"• السجل التجاري: {cert['cr'] or '—'} | بلد الشحن: {cert['country'] or '—'}",
           f"• عدد المنتجات: {len(cert['products'])} — من {cert['pages']} صفحة"]
    qty = {(q['hs'], q['model'][:12]): q for q in cert['quantities']}
    lic = {l['hs']: l for l in cert['licences']}
    for i, p in enumerate(cert['products'], 1):
        q = next((v for (hs, _), v in qty.items() if hs == p['hs'] and p['model'][:8] in v['model']), None) \
            or next((v for (hs, _), v in qty.items() if hs == p['hs']), None)
        l = lic.get(p['hs'])
        status = (f"شهادة منتج PC {p['pc']}" if p['pc'] else
                  ('غير خاضع للوائح الفنية (إقرار المستورد)' if p['not_regulated'] or (l and l['not_regulated'])
                   else '⚠️ بدون رقم شهادة منتج — تحقق'))
        line = f"{i}. {p['name']} ({p['model'] or '—'}) — بند {p['hs']} — {status}"
        if q and q['quantity']:
            line += f" — الكمية {q['quantity']} {q['unit']}".rstrip()
        if p['regulation']:
            line += f" — اللائحة: {p['regulation'][:60]}"
        out.append(line)
    invoices = sorted({(q['invoice'], q['invoice_date'], q['currency']) for q in cert['quantities'] if q['invoice']})
    if invoices:
        out.append('• الفاتورة التجارية في الشهادة: ' + '، '.join(f'{n} بتاريخ {d} ({c})' for n, d, c in invoices)
                   + ' — طابقها مع الفاتورة وقائمة التعبئة.')
    out.append('مقروءة من نص الملف نفسه. للتأكد من سريانها رسميًا: منصة سابر ← التحقق من الشهادة برقمها.')
    return '\n'.join(out)


def read(data, today=None):
    """Summary text if `data` is a SABER certificate PDF, else ''."""
    pages = pdf_pages(data)
    if not pages or not is_saber(pages[0] + (pages[1] if len(pages) > 1 else '')):
        return ''
    return summary(parse(pages), today)


def latest_text(sender, today=None):
    """The newest SABER certificate this person sent (last 3 days, among his last 15 files)."""
    from app import staff_documents
    from app.storage import db
    staff_documents.init()
    with db() as c:
        rows = c.execute('''SELECT id, filename, data FROM staff_documents WHERE sender=%s AND created_at > NOW() - INTERVAL '3 days'
            ORDER BY id DESC LIMIT 15''', (staff_documents._sender(sender),)).fetchall()
    for r in rows:
        data = bytes(r['data'])
        if data.startswith(b'%PDF'):
            text = read(data, today)
            if text:
                return f"«{r['filename']}»\n" + text
    return ''
