import os
import subprocess
import sys

import pytest

db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')

SCRIPT = r'''
import datetime as dt
from app import shipment_files as sf
from app.storage import db
sf.init()
t = sf.lookup_text('280395789')
assert 'ADEL' in t and '+966540844446' in t and 'TCNU2747285' in t and 'السفينة قادمة' in t, t
assert 'مدى التطوير' in sf.lookup_text('مدى التطوير')
assert '280395806' in sf.lookup_text('MRSU7003986')
with db() as c:
    c.execute("DELETE FROM shipment_files WHERE bill_no='TESTBL1'")
r = sf.upsert_from_document({'bill_no': 'TEST-BL1', 'consignee': 'شركة تجربة', 'consignee_phone': '0551112222',
                             'container_numbers': ['ABCU1234567'], 'eta': '2026-12-01', 'shipping_line': 'MSC'})
assert r['phone'] == '966551112222' and r['eta'] is not None
r = sf.upsert_from_document({'bill_no': 'TESTBL1', 'container_numbers': ['ABCU7654321'], 'consignee_email': 'a@b.com'})
assert 'ABCU7654321' in r['containers'] and 'ABCU1234567' in r['containers'] and r['email'] == 'a@b.com'
u = sf.update('TESTBL1', declaration_no='445566', actor='فيصل')
assert 'البيان مقدّم' in u and '445566' in u, u
assert 'تم الفسح' in sf.update('TESTBL1', stage='released')
sf.from_tracking('TESTBL1', {'arrived': True, 'eta': None, 'vessel': 'X'})
assert 'لوحة الشحنات' in sf.board_text()
print('OK')
'''


@db_only
def test_shipment_files():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().endswith('OK'), r.stderr[-2500:] + r.stdout[-500:]
