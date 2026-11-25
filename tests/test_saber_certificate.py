"""SABER shipment certificate read from its own text layer (synthetic certificate, no customer data)."""
import datetime as dt
from io import BytesIO

from app import saber_certificate as s

HEAD = ('Shipment certificate for imported products (commercial products)\n'
        'We ...... Example Conformity LLC - Dubai branch ...... acceptance ...... 01234 ......\n'
        'Certificate Number      CN-26-0000001      Issue Date     24/11/2026      Expire Date     22/02/2027\n'
        'Certificate Type      Shipment Conformity Certificate for Imported Products      Commercial Registration No.     1010000000\n'
        'Shipment Country     China\n')


def pages():
    return [
        HEAD + 'Product Certificate No.     64508-063-26-0000001\nModal Name      KB-1      Trademark     Brand\n'
               'Product Name      Keyboard\nHS Code      847160000002\nTechnical Regulation      Technical Regulation for IT Devices\n'
               'Manufacturer Name      Maker Ltd\n',
        'منتج غير خاضع للوائح الفنية\n' + HEAD + 'Modal Name      PS-15      Trademark     Brand\nProduct Name      Projection screens\n'
               'HS Code      901060000000\nManufacturer Name      Maker Ltd\n',
        HEAD + 'HS Code       847160000002\nProduct Name      Model Name      KB-1\nQuantity      1108      Unit      UNIT\n'
               'Product invoices supplement\nInvoice Number    Invoice Date    The amount of the item on the invoice   Invoices Currency\n'
               '   06112026462      06/11/2026      23676      US Dollar\n',
    ]


def test_parse_and_summary():
    cert = s.parse(pages())
    assert cert['number'] == 'CN-26-0000001' and cert['expiry'] == '22/02/2027' and cert['acceptance'] == '01234'
    assert 'Example Conformity LLC' in cert['body']
    assert [p['hs'] for p in cert['products']] == ['847160000002', '901060000000']
    assert cert['products'][0]['pc'] == '64508-063-26-0000001' and cert['products'][1]['not_regulated']
    text = s.summary(cert, dt.date(2026, 11, 25))
    assert '✅ سارية حتى 22/02/2027 (باقي 89 يوم)' in text
    assert 'Keyboard (KB-1) — بند 847160000002 — شهادة منتج PC 64508-063-26-0000001 — الكمية 1108 UNIT' in text
    assert 'Projection screens (PS-15) — بند 901060000000 — غير خاضع للوائح الفنية' in text
    assert '06112026462 بتاريخ 06/11/2026' in text
    assert '⛔ منتهية' in s.summary(cert, dt.date(2027, 3, 1))


def test_reads_a_real_pdf_text_layer_and_ignores_other_pdfs():
    from reportlab.pdfgen import canvas

    def pdf(lines):
        out = BytesIO()
        c = canvas.Canvas(out)
        y = 800
        for line in lines:
            c.drawString(30, y, line)
            y -= 16
        c.save()
        return out.getvalue()
    saber = pdf(['Shipment certificate for imported products (commercial products)', 'Certificate Number    CN-26-0000002',
                 'Issue Date    01/11/2026', 'Expire Date    01/02/2027', 'Product Name    Mouse', 'HS Code    847160000001',
                 'Technical Regulation    IT', 'Manufacturer Name    Maker'])
    text = s.read(saber, dt.date(2026, 11, 25))
    assert 'CN-26-0000002' in text and 'Mouse' in text and '847160000001' in text
    assert s.read(pdf(['PACKING LIST', 'Invoice Number 123'])) == ''
    assert s.read(b'not a pdf') == ''
