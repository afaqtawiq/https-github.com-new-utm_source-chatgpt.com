import datetime as dt
import importlib
import os
import unittest

os.environ.setdefault('DATABASE_URL', 'postgresql://unused@localhost/unused')


class PortTerminalsTest(unittest.TestCase):
    def setUp(self):
        self.pt = importlib.import_module('app.port_terminals')

    def test_free_days_then_tiers(self):
        d = dt.date(2026, 11, 1)
        s = self.pt.storage(d, '40', dt.date(2026, 11, 3))
        self.assertEqual((s['days'], s['chargeable'], s['cost'], s['next']), (3, 0, 0, 450))
        self.assertEqual(s['free_until'], dt.date(2026, 11, 3))
        s = self.pt.storage(d, '40', dt.date(2026, 11, 12))            # 12 days: 7x450 + 2x500
        self.assertEqual((s['chargeable'], s['cost'], s['next']), (9, 4150, 500))
        s = self.pt.storage(d, '20', dt.date(2026, 11, 17))            # 17 days: 7x350 + 5x400 + 2x500
        self.assertEqual(s['cost'], 2450 + 2000 + 1000)
        self.assertEqual(self.pt.storage(d, None, dt.date(2026, 11, 4))['cost'], 450)   # unknown size counts as 40ft

    def test_text_and_knowledge(self):
        d = dt.date(2026, 11, 1)
        self.assertIn('داخل الأيام المجانية', self.pt.storage_text(d, '40', dt.date(2026, 11, 2)))
        text = self.pt.storage_text(d, '40', dt.date(2026, 11, 12), 'MSCU1234567')
        self.assertIn('4,150', text)
        self.assertIn('غير غرامة الوكيل الملاحي', text)
        for needle in ('920007025', 'portal.rsgt.com', 'dpworld.sa', '0533345029', '350', '450', 'غير غرامة تأخير'):
            self.assertIn(needle, self.pt.KNOWLEDGE)
        self.assertNotIn('IBAN', self.pt.KNOWLEDGE)


if __name__ == '__main__':
    unittest.main()
