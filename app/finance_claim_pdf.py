"""Customer-safe, local-only Arabic claim PDF export.

Only the explicit fields below can reach the PDF. No templates, URLs, images,
notes, ledger rows or internal financial fields are rendered or fetched.
"""
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from io import BytesIO
from pathlib import Path
import re
from threading import Lock
import unicodedata

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .finance_core import CURRENCIES

_DOCUMENT_FIELDS = ('id', 'owner_name', 'counterparty_name', 'document_date',
                    'invoice_ref', 'customs_ref', 'currency')
_DETAIL_FIELDS = ('id', 'goods_amount', 'goods_currency', 'exchange_rate',
                  'goods_value_display', 'claim_total_display',
                  'component_display', 'customs_total_display')
_COMPONENTS = ('customs_duty', 'customs_other', 'clearance', 'saber', 'zakat',
               'registry', 'tax')
_FONT = 'ClaimDejaVuSans'
_BOLD = 'ClaimDejaVuSansBold'
_FONT_LOCK = Lock()
_SHAPER = arabic_reshaper.ArabicReshaper(configuration={
    'delete_harakat': False, 'shift_harakat_position': True,
})
_INK = colors.HexColor('#17354b')
_MUTED = colors.HexColor('#526777')
_ACCENT = colors.HexColor('#11756c')
_PALE = colors.HexColor('#f0f6f7')
_BORDER = colors.HexColor('#d9e3e7')


def _fonts():
    # Fixed application-owned locations only. Never interpret input as a path.
    with _FONT_LOCK:
        if _FONT in pdfmetrics.getRegisteredFontNames() and _BOLD in pdfmetrics.getRegisteredFontNames():
            return
        root = Path('/usr/share/fonts/truetype/dejavu')
        for name, file in ((_FONT, 'DejaVuSans.ttf'), (_BOLD, 'DejaVuSans-Bold.ttf')):
            path = root / file
            if not path.is_file():
                raise RuntimeError('Arabic PDF font is not installed')
            pdfmetrics.registerFont(TTFont(name, str(path)))


def _text(value, limit=250):
    if value is None:
        return '-'
    text = str(value)
    if len(text) > limit:
        raise ValueError('PDF field exceeds the supported length')
    # Remove bidi overrides/isolates and controls so input cannot reorder labels.
    text = ''.join(' ' if unicodedata.category(char).startswith('C') else char for char in text)
    return ' '.join(text.split()) or '-'


def _number(value, *, positive=False):
    if isinstance(value, Decimal):
        # Database NUMERIC values such as Decimal('1E-8') are legitimate fixed
        # precision amounts. Bound them before formatting to avoid large output.
        if not value.is_finite() or value.adjusted() > 13 or value.as_tuple().exponent < -8:
            raise ValueError('Invalid PDF amount')
        raw = format(value, 'f')
    else:
        raw = str(value)
    if not re.fullmatch(r'[0-9]{1,14}(?:\.[0-9]{1,8})?', raw):
        raise ValueError('PDF amounts must be plain decimal strings')
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError('Invalid PDF amount') from exc
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        raise ValueError('Invalid PDF amount')
    return number


def _currency(value):
    code = str(value).upper()
    if code not in CURRENCIES:
        raise ValueError('Unsupported PDF currency')
    return code


def _money(value, currency):
    scale = CURRENCIES[currency]
    quantum = Decimal(1).scaleb(-scale)
    if value != value.quantize(quantum):
        raise ValueError('PDF amount has unsupported currency precision')
    return f'{value:,.{scale}f} {currency}'


def _visual(text):
    return get_display(_SHAPER.reshape(text), base_dir='R')


def _wrap(text, width, font, size):
    """Wrap logical text before shaping; split long references safely too."""
    lines = []
    current = ''
    for word in text.split(' '):
        candidate = (current + ' ' + word).strip()
        if pdfmetrics.stringWidth(_visual(candidate), font, size) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ''
        for char in word:
            candidate = current + char
            if current and pdfmetrics.stringWidth(_visual(candidate), font, size) > width:
                lines.append(current)
                current = char
            else:
                current = candidate
    if current:
        lines.append(current)
    return lines or ['-']


def _prepared(document, detail):
    if not isinstance(document, Mapping) or not isinstance(detail, Mapping):
        raise ValueError('PDF input must be a document and claim detail')
    doc = {key: document.get(key) for key in _DOCUMENT_FIELDS}
    item = {key: detail.get(key) for key in _DETAIL_FIELDS}
    currency = _currency(doc['currency'])
    goods_currency = _currency(item['goods_currency'])
    components = item['component_display']
    if not isinstance(components, Mapping) or any(key not in components for key in _COMPONENTS):
        raise ValueError('All claim components are required for PDF export')
    amounts = {key: _number(components[key]) for key in _COMPONENTS}
    goods = _number(item['goods_amount'], positive=True)
    rate = _number(item['exchange_rate'], positive=True)
    goods_value = _number(item['goods_value_display'])
    customs = _number(item['customs_total_display'])
    total = _number(item['claim_total_display'], positive=True)
    with localcontext() as context:
        context.prec = 60
        if customs != amounts['customs_duty'] + amounts['customs_other'] or total != sum(amounts.values()):
            raise ValueError('PDF claim totals do not reconcile')
        converted = (goods * rate).quantize(Decimal(1).scaleb(-CURRENCIES[currency]), rounding=ROUND_HALF_UP)
        if goods_value != converted or (goods_currency == currency and rate != 1):
            raise ValueError('PDF goods conversion does not reconcile')
    money = {key: _money(value, currency) for key, value in amounts.items()}
    return {
        'document': {key: _text(value) for key, value in doc.items()},
        'detail_id': _text(item['id']),
        'currency': currency, 'goods_currency': goods_currency,
        'goods': _money(goods, goods_currency),
        'rate': format(rate, 'f'), 'goods_value': _money(goods_value, currency),
        'components': money, 'customs': _money(customs, currency),
        'total': _money(total, currency),
    }


def render_pdf(document, detail) -> bytes:
    """Render an itemized financial claim, with goods excluded from the total.

    Raises ValueError for incomplete/inconsistent input; returns PDF bytes only.
    Callers remain responsible for access control and no-store response headers.
    """
    data = _prepared(document, detail)
    _fonts()
    doc = data['document']
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=A4, pageCompression=1, invariant=1)
    pdf.setTitle('Customer financial claim')
    pdf.setAuthor('')
    pdf.setSubject('Itemized customer financial claim')
    pdf.setCreator('Customer claim PDF export')
    width, height = A4
    left, right = 42, width - 42
    usable = right - left

    def rtl(text, x, y, size=11, bold=False, color=_INK):
        pdf.setFont(_BOLD if bold else _FONT, size)
        pdf.setFillColor(color)
        pdf.drawRightString(x, y, _visual(text))

    def ltr(text, x, y, size=11, bold=False, color=_INK):
        pdf.setFont(_BOLD if bold else _FONT, size)
        pdf.setFillColor(color)
        pdf.drawString(x, y, text)

    owner_lines = _wrap(doc['owner_name'], usable, _BOLD, 17)

    def header(continued=False):
        cursor = height - 51
        for line in owner_lines:
            rtl(line, right, cursor, size=17, bold=True)
            cursor -= 23
        cursor -= 9
        rtl('مطالبة مالية', right, cursor, size=22, bold=True)
        cursor -= 18
        pdf.setStrokeColor(_ACCENT)
        pdf.setLineWidth(2)
        pdf.line(left, cursor, right, cursor)
        cursor -= 26
        if continued:
            reference = 'رقم المطالبة: ' + doc['id'] + ' | مرجع التفصيل: ' + data['detail_id']
            for line in _wrap(reference, usable, _FONT, 10):
                rtl(line, right, cursor, size=10, color=_MUTED)
                cursor -= 15
            cursor -= 12
        return cursor

    y = header()

    for label, value in (
        ('العميل', doc['counterparty_name']),
        ('رقم المطالبة', doc['id']),
        ('مرجع التفصيل', data['detail_id']),
        ('تاريخ المطالبة', doc['document_date']),
        ('رقم الفاتورة', doc['invoice_ref']),
        ('رقم البيان الجمركي', doc['customs_ref']),
    ):
        lines = _wrap(value, usable - 145, _FONT, 10)
        if y - len(lines) * 15 < 55:
            pdf.showPage()
            y = header(continued=True)
        rtl(label, right, y, size=10, color=_MUTED)
        for line in lines:
            rtl(line, right - 145, y, size=10)
            y -= 15
        y -= 7

    if y < 235:
        pdf.showPage()
        y = header(continued=True)
    y -= 7
    rtl('قيمة البضاعة والتحويل', right, y, size=12, bold=True)
    y -= 14
    box_top = y
    pdf.setFillColor(_PALE)
    pdf.roundRect(left, box_top - 106, usable, 106, radius=7, stroke=0, fill=1)
    y -= 25
    rtl('قيمة فاتورة البضاعة الأصلية', right - 13, y, size=10)
    ltr(data['goods'], left + 13, y, size=10)
    y -= 25
    rtl('سعر الصرف', right - 13, y, size=10)
    ltr(f"1 {data['goods_currency']} = {data['rate']} {data['currency']}", left + 13, y, size=10)
    y -= 25
    rtl('قيمة البضاعة بعملة المطالبة', right - 13, y, size=10)
    ltr(data['goods_value'], left + 13, y, size=10, bold=True)
    y = box_top - 106 - 22
    rtl('قيمة البضاعة للبيان فقط، ولا تدخل في إجمالي المطالبة', right, y, size=9, color=_MUTED)
    y -= 31

    # Keep the entire six-line breakdown, customs sub-lines, and total together.
    if y < 382:
        pdf.showPage()
        y = header(continued=True)
    rtl('تفاصيل المبالغ المطلوبة', right, y, size=12, bold=True)
    y -= 25
    rtl('البند', right - 12, y, size=10, color=_MUTED)
    ltr(data['currency'], left + 12, y, size=10, color=_MUTED)
    y -= 13
    pdf.setStrokeColor(_BORDER)
    pdf.setLineWidth(0.7)
    pdf.line(left, y, right, y)
    y -= 21
    rows = (
        ('الجمارك', data['customs'], False),
        ('الرسوم الجمركية', data['components']['customs_duty'], True),
        ('رسوم جمركية أخرى', data['components']['customs_other'], True),
        ('التخليص الجمركي', data['components']['clearance'], False),
        ('سابر', data['components']['saber'], False),
        ('الزكاة', data['components']['zakat'], False),
        ('السجل التجاري', data['components']['registry'], False),
        ('الضريبة', data['components']['tax'], False),
    )
    for label, amount, sub in rows:
        rtl(label, right - (27 if sub else 12), y, size=9 if sub else 11,
            color=_MUTED if sub else _INK)
        ltr(amount, left + 12, y, size=9 if sub else 11, color=_MUTED if sub else _INK)
        y -= 21 if sub else 28
    y -= 1
    # Fail closed rather than producing a clipped or misleading claim.
    if y < 91:
        raise ValueError('Claim fields are too long for the PDF layout')
    pdf.setFillColor(_INK)
    pdf.roundRect(left, y - 34, usable, 47, radius=7, stroke=0, fill=1)
    rtl('إجمالي المطالبة', right - 13, y - 6, size=13, bold=True, color=colors.white)
    ltr(data['total'], left + 13, y - 6, size=13, bold=True, color=colors.white)
    rtl('الإجمالي لا يشمل قيمة البضاعة', right, y - 54, size=9, color=_MUTED)
    rtl('هذه مطالبة مالية وليست فاتورة ضريبية أو إثبات سداد', right, y - 70, size=8, color=_MUTED)
    pdf.showPage()
    pdf.save()
    return stream.getvalue()
