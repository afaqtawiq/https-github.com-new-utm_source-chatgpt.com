"""Synthetic customer-PDF tests. No database or external financial data."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import finance_claim_pdf as exporter


def fixture():
    document = dict(id=41, owner_name='مكتب المثال للتخليص الجمركي',
        counterparty_name='شركة العميل التجريبي للتجارة', document_date='2026-10-05',
        invoice_ref='TEST-INV-0041', customs_ref='TEST-CUSTOMS-0099', currency='SAR')
    detail = dict(id=1, goods_amount='2500.00', goods_currency='EUR',
        exchange_rate='4.00', goods_value_display='10000.00',
        claim_total_display='1840.00', customs_total_display='575.00',
        component_display=dict(customs_duty='500.00', customs_other='75.00',
            clearance='600.00', saber='300.00', zakat='0.00', registry='125.00', tax='240.00'))
    return document, detail


def capture(document, detail):
    drawn = []
    original = exporter.canvas.Canvas.drawString
    original_right = exporter.canvas.Canvas.drawRightString

    def record(self, x, y, text, *args, **kwargs):
        drawn.append((x, y, text))
        return original(self, x, y, text, *args, **kwargs)

    def record_right(self, x, y, text, *args, **kwargs):
        drawn.append((x, y, text))
        return original_right(self, x, y, text, *args, **kwargs)

    with patch.object(exporter.canvas.Canvas, 'drawString', record), \
            patch.object(exporter.canvas.Canvas, 'drawRightString', record_right):
        pdf = exporter.render_pdf(document, detail)
    return pdf, drawn


class ClaimPdfTests(unittest.TestCase):
    def test_complete_arabic_claim_with_embedded_fonts(self):
        document, detail = fixture()
        pdf, drawn = capture(document, detail)
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertIn(b'/FontFile2', pdf)
        self.assertLess(len(pdf), 150000)
        text = [row[2] for row in drawn]
        for label in ('مطالبة مالية', 'الجمارك', 'الرسوم الجمركية', 'رسوم جمركية أخرى',
                      'التخليص الجمركي', 'سابر', 'الزكاة', 'السجل التجاري', 'الضريبة',
                      'إجمالي المطالبة', 'الإجمالي لا يشمل قيمة البضاعة', 'مرجع التفصيل',
                      'هذه مطالبة مالية وليست فاتورة ضريبية أو إثبات سداد'):
            self.assertIn(exporter._visual(label), text)
        for value in ('TEST-INV-0041', 'TEST-CUSTOMS-0099', '2,500.00 EUR',
                      '1 EUR = 4.00 SAR', '10,000.00 SAR', '575.00 SAR', '1,840.00 SAR'):
            self.assertIn(value, text)
        # Every customer-visible baseline remains within the A4 page margins.
        self.assertTrue(all(20 <= y <= 810 for _, y, _ in drawn))

    def test_detail_version_is_visible(self):
        document, detail = fixture()
        detail['id'] = 24680
        _, drawn = capture(document, detail)
        self.assertIn('24680', [row[2] for row in drawn])

    def test_allowlist_ignores_internal_fields_without_network_access(self):
        document, detail = fixture()
        baseline = exporter.render_pdf(document, detail)
        original = deepcopy((document, detail))
        for target in (document, detail):
            target.update(notes='PRIVATE-NOTES', audit='PRIVATE-AUDIT',
                cost='PRIVATE-COST', profit='PRIVATE-PROFIT',
                source_ref='PRIVATE-SOURCE', customer='UNRELATED-CUSTOMER',
                image='https://fixture.invalid/logo.png', bank_account='PRIVATE-BANK')
        detail['component_display']['profit'] = 'PRIVATE-PROFIT'
        with patch('socket.socket', side_effect=AssertionError('Network access forbidden')):
            pdf = exporter.render_pdf(document, detail)
        self.assertEqual(pdf, baseline)
        # Export does not change its source document or detail.
        clean_document, clean_detail = original
        expected = deepcopy((document, detail))
        exporter.render_pdf(document, detail)
        self.assertEqual((document, detail), expected)
        self.assertEqual(clean_document['id'], document['id'])
        self.assertEqual(clean_detail['goods_amount'], detail['goods_amount'])

    def test_missing_components_fail_closed(self):
        for key in exporter._COMPONENTS:
            document, detail = fixture()
            del detail['component_display'][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                exporter.render_pdf(document, detail)

    def test_inconsistent_totals_and_goods_conversion_fail_closed(self):
        for key, value in (('claim_total_display', '11840.00'),
                           ('customs_total_display', '999.00'),
                           ('goods_value_display', '9000.00')):
            document, detail = fixture()
            detail[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                exporter.render_pdf(document, detail)

    def test_invalid_decimal_inputs_fail_closed(self):
        for raw in ('NaN', 'Infinity', '-1', '1e3', '1,000', '<img src=x>', '', None,
                    '1.123456789', '9' * 1000, True):
            document, detail = fixture()
            detail['goods_amount'] = raw
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                exporter.render_pdf(document, detail)

    def test_currency_precision_is_preserved(self):
        for currency, amount in (('JPY', '1'), ('KWD', '1.001')):
            document, detail = fixture()
            document['currency'] = currency
            detail.update(goods_currency=currency, goods_amount=amount, exchange_rate='1',
                          goods_value_display=amount, claim_total_display=amount,
                          customs_total_display=amount)
            detail['component_display'] = {key: '0' for key in exporter._COMPONENTS}
            detail['component_display']['customs_duty'] = amount
            _, drawn = capture(document, detail)
            self.assertIn(amount + ' ' + currency, [row[2] for row in drawn])

    def test_database_decimal_small_exchange_rate(self):
        document, detail = fixture()
        detail.update(goods_amount=Decimal('1000000.00'),
                      exchange_rate=Decimal('0.00000001'), goods_value_display='0.01')
        _, drawn = capture(document, detail)
        self.assertIn('1 EUR = 0.00000001 SAR', [row[2] for row in drawn])
        for value in (Decimal('NaN'), Decimal('Infinity'), Decimal('1E+999999999'),
                      Decimal('1E-999999999')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                exporter._number(value)

    def test_unsupported_currency_and_fraction_fail_closed(self):
        document, detail = fixture()
        document['currency'] = 'INVALID'
        with self.assertRaises(ValueError):
            exporter.render_pdf(document, detail)
        document, detail = fixture()
        detail['goods_amount'] = '2500.001'
        detail['goods_value_display'] = '10000.00'
        with self.assertRaises(ValueError):
            exporter.render_pdf(document, detail)

    def test_long_fields_paginate_and_no_unsafe_control_characters(self):
        document, detail = fixture()
        for key in ('owner_name', 'counterparty_name', 'invoice_ref', 'customs_ref'):
            document[key] = ('اختبار المطالبة المالية ' * 11)[:250]
        pdf, drawn = capture(document, detail)
        self.assertIn(b'/Count 2', pdf)
        self.assertTrue(all(20 <= y <= 810 for _, y, _ in drawn))
        self.assertEqual(exporter._text('A\u202eB\u2066C\x00D\nE'), 'A B C D E')
        with self.assertRaises(ValueError):
            exporter._text('x' * 251)

    def test_html_is_literal_text_and_not_an_active_pdf_link(self):
        document, detail = fixture()
        document['invoice_ref'] = '<img src="https://fixture.invalid/x">'
        pdf, drawn = capture(document, detail)
        self.assertIn(exporter._visual(document['invoice_ref']), [row[2] for row in drawn])
        self.assertNotIn(b'/Annots', pdf)
        self.assertNotIn(b'/JavaScript', pdf)
        self.assertNotIn(b'/EmbeddedFiles', pdf)


if __name__ == '__main__':
    unittest.main()
