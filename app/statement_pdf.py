"""Account statement as a PDF sent to the requester on WhatsApp (owner request, 16 Nov 2026).

The same numbers as the printable statement page (app.statement_import.statement), drawn locally with reportlab — no
URLs, images or fetched content. The file goes ONLY to the verified team member who asked for it, in his own command
chat; a statement for a customer still needs the manager's own forwarding.
"""
import datetime as dt
import hashlib
import secrets
from io import BytesIO

COLUMNS = (('type', 'نوع البيان'), ('invoice_no', 'رقم الفاتورة'), ('invoice', 'قيمة الفاتورة'), ('fees', 'رسوم جمركية'),
           ('clearance', 'تخليص'), ('saber', 'سابر'), ('zakat', 'زكاة'), ('registry', 'سجل تجاري'), ('tax', 'ضريبة 15%'))
TEXT_COLUMNS = ('type', 'invoice_no')


def _shown(value):
    try:
        return float(str(value).replace(',', '')) != 0
    except (TypeError, ValueError):
        return bool(value)


def _money(value):
    try:
        return f"{float(str(value).replace(',', '')):,.2f}"
    except (TypeError, ValueError):
        return str(value or '')


def build(s):
    """PDF bytes for one statement dict (statement_import.statement)."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfgen import canvas
    from app import finance_claim_pdf as base
    base._fonts()
    font, bold = base._FONT, base._BOLD

    def ar(text):
        return get_display(arabic_reshaper.reshape(str(text if text is not None else '')))

    cols = [(k, t) for k, t in COLUMNS if any(_shown(l.get(k)) for l in s['lines'])]
    heads = ['#', 'رقم البيان', 'التاريخ'] + [t for _, t in cols] + ['النصيب' if s.get('payable') else 'الإجمالي']
    weights = [0.5, 1.3, 1.4] + [1.6 if k in TEXT_COLUMNS else 1.3 for k, _ in cols] + [1.5]
    width, height = landscape(A4)
    margin = 28
    unit = (width - 2 * margin) / sum(weights)
    widths = [w * unit for w in weights]
    out = BytesIO()
    pdf = canvas.Canvas(out, pagesize=landscape(A4))
    pdf.setTitle('Account statement')
    ink, pale, border = colors.HexColor('#17354b'), colors.HexColor('#f0f6f7'), colors.HexColor('#d9e3e7')

    def row(y, cells, face=font, fill=None, size=9):
        x = width - margin  # right-to-left table
        for w, cell in zip(widths, cells):
            x -= w
            if fill is not None:
                pdf.setFillColor(fill)
                pdf.rect(x, y - 5, w, 18, stroke=0, fill=1)
            pdf.setStrokeColor(border)
            pdf.rect(x, y - 5, w, 18, stroke=1, fill=0)
            pdf.setFillColor(ink)
            text = ar(cell)
            fit = size
            while fit > 5 and pdfmetrics.stringWidth(text, face, fit) > w - 6:
                fit -= 0.5
            pdf.setFont(face, fit)
            pdf.drawCentredString(x + w / 2, y, text)

    def header(page):
        pdf.setFillColor(ink)
        pdf.setFont(bold, 16)
        pdf.drawRightString(width - margin, height - 40, ar(f"كشف حساب {s['party']} — {s['month']}"))
        pdf.setFont(font, 9)
        pdf.drawRightString(width - margin, height - 56, ar('مؤسسة آفاق طويق للتخليص الجمركي — ترخيص 2513'))
        pdf.drawString(margin, height - 40, ar(f"صفحة {page} — صدر {dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).strftime('%Y-%m-%d %H:%M')}"))
        row(height - 84, heads, bold, pale)
        return height - 102

    page = 1
    y = header(page)
    for i, line in enumerate(s['lines'], 1):
        if y < 96:
            pdf.showPage()
            page += 1
            y = header(page)
        cells = [i, line.get('number'), line.get('date')]
        cells += [(str(line.get(k) or '') if k in TEXT_COLUMNS else (_money(line.get(k)) if _shown(line.get(k)) else '')) for k, _ in cols]
        row(y, cells + [_money(line.get('amount'))])
        y -= 18
    if y < 120:
        pdf.showPage()
        page += 1
        y = header(page)
    pdf.setFont(bold, 11)
    pdf.setFillColor(ink)
    label = 'نصيب ' + s['party'] if s.get('payable') else 'إجمالي المطالبة'
    y -= 14
    for text in (f"عدد البيانات: {len(s['lines'])}", f"{label}: {s['total']:,.2f} ريال",
                 f"السداد خلال الشهر: {s['paid']:,.2f} ريال ({len(s['payments'])} دفعة)",
                 f"الصافي عن الشهر: {s['total'] - s['paid']:,.2f} ريال"):
        pdf.drawRightString(width - margin, y, ar(text))
        y -= 17
    pdf.setFont(font, 8)
    pdf.drawRightString(width - margin, max(y - 4, 30), ar('من القيود المسجلة (مسودات) قبل الترحيل.'))
    pdf.save()
    return out.getvalue()


def filename(s):
    names = {'الياسمين': 'Yasmen', 'عمران': 'Omran', 'سلة الرحائب': 'Salla'}
    return f"Afaq-Statement-{names.get(s['party'], 'Account')}-{s['month']}.pdf"


async def send(recipient, conversation, s):
    """Send one statement PDF to the requester's own chat. Returns True when the provider accepted it."""
    from starlette.concurrency import run_in_threadpool
    from app import zernio_whatsapp as z
    content = await run_in_threadpool(build, s)
    key = 'wa-document-' + hashlib.sha256(content + str(conversation).encode() + secrets.token_bytes(8)).hexdigest()
    caption = f"كشف حساب {s['party']} — {s['month']} — {len(s['lines'])} بيان — {s['total']:,.2f} ريال"
    with z.dispatch_guard(lambda: None):
        result = await z.send_document(recipient, content, filename(s), caption, expected_account=z.account_id(),
                                       expected_conversation=str(conversation), idempotency_key=key)
    return isinstance(result, dict) and result.get('status') == 'sent'


def send_to_requester(chat, statements):
    """Sync wrapper for the command agent. chat = (sender, conversation_id). Returns (sent parties, failed parties)."""
    from app.transport_desk import run_async
    sent, failed = [], []
    for s in statements:
        if not s.get('lines'):
            continue
        try:
            ok = run_async(lambda s=s: send(chat[0], chat[1], s), timeout=90)
        except Exception as exc:
            print('STATEMENT_PDF', s.get('party'), type(exc).__name__, str(exc)[:160], flush=True)
            ok = False
        (sent if ok else failed).append(s['party'])
    return sent, failed
