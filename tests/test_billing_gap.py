import os
import subprocess
import sys

import pytest

db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')

SCRIPT = r'''
from app import fasah_tracking, billing_rules, billing_gap
from app.storage import db
fasah_tracking.init(); billing_rules.init()
with db() as c:
    c.execute("DELETE FROM fasah_status"); c.execute("DELETE FROM billing_declarations")
rows = [{'رقم البيان': '1001', 'التاريخ': '2026-11-03', 'التفاصيل': 'سلة الرحائب - مفسوح'},
        {'رقم البيان': '1002', 'التاريخ': '05/11/2026', 'التفاصيل': 'سلة الرحائب - بانتظار السداد'},
        {'رقم البيان': '1003', 'التاريخ': '2026-11-07', 'التفاصيل': 'مؤسسة مدى التطوير - مفسوح'},
        {'رقم البيان': '0999', 'التاريخ': '2026-10-30', 'التفاصيل': 'سلة الرحائب'}]
fasah_tracking.ingest(rows, 'import')
with db() as c:
    c.execute("INSERT INTO billing_declarations(number,kind,items_json,status,created_at) VALUES('1001','import','[]','recorded',NOW())")
t = billing_gap.report('2026-11')
assert 'بيانات الشهر في فسح: 3' in t and 'مسجلة في الحسابات: 1' in t, t
assert 'عميل بسعر ثابت (مدى التطوير)' in t and '1003' in t and 'لم يقرأ جهاز العمل' in t and '1002' in t, t
items = billing_rules.compute({'number': '1003', 'kind': 'import', 'party': 'مؤسسة مدى التطوير الحديث للتجارة'})
assert len(items) == 1 and str(items[0]['amount']) == '1100.00' and items[0]['party'] == 'مدى التطوير', items
assert 'مدى التطوير' in billing_rules.all_parties()
print('OK')
'''


@db_only
def test_billing_gap():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().endswith('OK'), r.stderr[-2500:] + r.stdout[-1500:]
