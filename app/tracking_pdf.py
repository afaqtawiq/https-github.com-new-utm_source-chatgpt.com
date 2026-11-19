"""Shipment tracking result as a one-page Arabic PDF (owner request, 19 Nov 2026: «إرسال النتيجة ملف بي دي اف»).

Drawn locally with reportlab from the tracking result only (no fetched content, no images). Sent to the person who
asked, in his own WhatsApp chat.
"""
import datetime as dt
import hashlib
import secrets
from io import BytesIO

RIYADH = dt.timezone(dt.timedelta(hours=3))


def _d(value):
    if not value:
        return '—'
    if isinstance(value, dt.datetime):
        return value.astimezone(RIYADH).strftime('%d/%m/%Y')
    return str(value)


def build(ref, info, source):
    import arabic_reshaper
    from bidi.algorithm import get_display
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfgen import canvas
    from app import finance_claim_pdf as base
    base._fonts()
    font, bold = base._FONT, base._BOLD

    def ar(text):
        return get_display(arabic_reshaper.reshape(str(text if text is not None else '')))

    width, height = A4
    margin = 40
    out = BytesIO()
    pdf = canvas.Canvas(out, pagesize=A4)
    pdf.setTitle('Shipment tracking ' + ref)
    ink, pale, border = colors.HexColor('#17354b'), colors.HexColor('#f0f6f7'), colors.HexColor('#d9e3e7')
    pdf.setFillColor(ink)
    pdf.setFont(bold, 18)
    pdf.drawRightString(width - margin, height - 56, ar('تقرير تتبع شحنة'))
    pdf.setFont(font, 10)
    pdf.drawRightString(width - margin, height - 74, ar('مؤسسة آفاق طويق للتخليص الجمركي والنقل'))
    pdf.drawString(margin, height - 56, ar('صدر ' + dt.datetime.now(RIYADH).strftime('%Y-%m-%d %H:%M')))
    status = 'وصلت وتفرغت' if info.get('arrived') else ('في الطريق' if info.get('etd') or info.get('vessel') else 'بانتظار التحميل / غير مؤكد')
    rows = [('رقم المرجع', ref), ('الخط الملاحي', info.get('carrier') or '—'), ('الحالة', status),
            ('السفينة / الرحلة', ' / '.join(x for x in (info.get('vessel'), info.get('voyage')) if x) or '—'),
            ('ميناء التحميل', info.get('pol') or '—'), ('تاريخ التحميل / المغادرة', _d(info.get('etd'))),
            ('ميناء التفريغ', info.get('pod') or '—'),
            ('التفريغ الفعلي' if info.get('arrived') else 'الوصول المتوقع (ETA)', _d(info.get('eta'))),
            ('آخر حدث مؤكد', info.get('last_event') or '—')]
    containers = [c.get('number') if isinstance(c, dict) else str(c) for c in info.get('containers') or []]
    if containers:
        rows.append(('الحاويات', '، '.join(x for x in containers[:12] if x)))
    y = height - 120
    label_w, value_w = 150, width - 2 * margin - 150
    for label, value in rows:
        text = ar(value)
        size = 11
        while size > 7 and pdfmetrics.stringWidth(text, font, size) > value_w - 12:
            size -= 0.5
        pdf.setFillColor(pale)
        pdf.rect(width - margin - label_w, y - 8, label_w, 26, stroke=0, fill=1)
        pdf.setStrokeColor(border)
        pdf.rect(width - margin - label_w, y - 8, label_w, 26, stroke=1, fill=0)
        pdf.rect(margin, y - 8, value_w, 26, stroke=1, fill=0)
        pdf.setFillColor(ink)
        pdf.setFont(bold, 10.5)
        pdf.drawRightString(width - margin - 8, y, ar(label))
        pdf.setFont(font, size)
        pdf.drawRightString(margin + value_w - 8, y, text)
        y -= 26
    pdf.setFont(font, 9)
    pdf.drawRightString(width - margin, y - 18, ar('المصدر: ' + source))
    pdf.drawRightString(width - margin, y - 34, ar('المواعيد من الخط الملاحي وقد تتغير؛ الوكيل يتابعها ويبلغ عند تغيرها.'))
    pdf.save()
    return out.getvalue()


def filename(ref):
    return f'Afaq-Tracking-{"".join(ch for ch in ref if ch.isalnum())[:30]}.pdf'


async def send(chat, ref, info, source):
    """Send the PDF to chat = (sender, conversation). Returns True when WhatsApp accepted it."""
    from starlette.concurrency import run_in_threadpool
    from app import zernio_whatsapp as z
    content = await run_in_threadpool(build, ref, info, source)
    key = 'wa-document-' + hashlib.sha256(content + str(chat[1]).encode() + secrets.token_bytes(8)).hexdigest()
    caption = f'تقرير تتبع {ref}' + (f" — الوصول {_d(info.get('eta'))}" if info.get('eta') else '')
    with z.dispatch_guard(lambda: None):
        result = await z.send_document(chat[0], content, filename(ref), caption, expected_account=z.account_id(),
                                       expected_conversation=str(chat[1]), idempotency_key=key)
    return isinstance(result, dict) and result.get('status') in ('sent', 'accepted', 'public_link_warning')
