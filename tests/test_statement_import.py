import io
import openpyxl
from app import statement_import as si


def test_xlsx_to_table_text():
    book = openpyxl.Workbook(); ws = book.active
    ws.append(['رقم البيان', 'التاريخ', 'قيمة الفاتورة', 'المصدر'])
    ws.append([415169, '2026-10-30', 20500, 'الياسمين'])
    buf = io.BytesIO(); book.save(buf)
    text = si.table_text(buf.getvalue())
    assert '415169' in text and 'الياسمين' in text


def test_csv_to_table_text():
    text = si.table_text('رقم,قيمة\n411523,9000\n'.encode())
    assert '411523\t9000' in text
