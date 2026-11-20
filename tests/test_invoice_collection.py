import os
import subprocess
import sys

import pytest

from app import invoice_collection as ic

db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')


def test_message_matches_template_body():
    import datetime as dt
    row = {'contact_name': 'أبو خالد', 'customer': 'مؤسسة الوثبة', 'invoice_no': '3613', 'invoice_date': dt.date(2026, 10, 27), 'amount': 7131.55}
    text = ic.message(row)
    assert '3613' in text and '7,131.55' in text and '2026-10-27' in text and 'أبو خالد' in text
    from app.zernio_whatsapp import template_parameters
    spec = ic.template_spec()
    params = template_parameters({'components': [{'type': 'BODY', 'text': spec['components'][0]['text']}]}, text)
    assert params is not None


SCRIPT = r'''
from app import invoice_collection as ic
from app.storage import db
ic.init()
with db() as c:
    c.execute("DELETE FROM invoice_collections WHERE invoice_no='T3613'")
row = ic.add('T3613', 'مؤسسة الوثبة السريعة', '7,131.55', '0551234567', 'أبو خالد', '2026-10-27')
assert row['phone'] == '966551234567' and float(row['amount']) == 7131.55
assert 'T3613' in ic.open_text()
assert 'مسددة' in ic.mark_paid('T3613') and 'T3613' not in ic.open_text()
assert 'مغلقة' in ic.send('T3613')
print('OK')
'''


@db_only
def test_register_and_close():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().endswith('OK'), r.stderr[-2500:] + r.stdout[-500:]
