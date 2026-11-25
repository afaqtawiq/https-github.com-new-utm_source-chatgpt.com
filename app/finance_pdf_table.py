"""Right-to-left table rows for the finance review PDFs (one cell per column, wrapped inside its own width), so an
accountant can tick every line. Drawn on a finance_monthly_pdf.Report."""
from reportlab.pdfbase import pdfmetrics

from app import finance_claim_pdf as common


def _cell_lines(text, width, font, size):
    return common._wrap(common._text(text, 400), width - 6, font, size)[:4] or ['']


def table(rep, headers, rows, widths, size=8.5, tones=None):
    """headers/rows are lists of strings, right-most column first; widths are fractions summing to 1."""
    total = rep.right - rep.left
    cols = [w * total for w in widths]

    def draw_row(cells, bold=False, shade=None):
        font = common._BOLD if bold else common._FONT
        wrapped = [_cell_lines(t, w, font, size) for t, w in zip(cells, cols)]
        height = max(len(w) for w in wrapped) * (size + 3) + 6
        rep.ensure(height + 4)
        top = rep.y + size + 2
        if shade:
            rep.pdf.setFillColor(shade)
            rep.pdf.rect(rep.left, top - height, total, height, stroke=0, fill=1)
        x = rep.right
        rep.pdf.setStrokeColor(common._BORDER)
        for lines, w in zip(wrapped, cols):
            rep.pdf.rect(x - w, top - height, w, height, stroke=1, fill=0)
            rep.pdf.setFont(font, size)
            rep.pdf.setFillColor(common._INK)
            yy = rep.y
            for line in lines:
                text = common._visual(line)
                while pdfmetrics.stringWidth(text, font, size) > w - 6 and len(text) > 1:
                    text = text[1:]
                rep.pdf.drawRightString(x - 3, yy, text)
                yy -= size + 3
            x -= w
        rep.y -= height

    draw_row(headers, bold=True, shade=common._PALE)
    for i, cells in enumerate(rows):
        draw_row(cells, shade=(tones[i] if tones else None))
    rep.y -= 10
