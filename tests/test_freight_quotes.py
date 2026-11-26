"""سلطان — دليل وكلاء الملاحة وطلبات عروض الأسعار (طلب المالك، 26 نوفمبر 2026)."""
import os
import subprocess
import sys

import pytest

db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')

FLOW = r'''
import app.shipping_agents  # seeds the registered Jeddah directory
from app import freight_quotes as fq
from app.storage import db
names = fq.directory_text('')
assert '39' in names or 'وكيلًا مسجلًا' in names, names
assert 'CMA CGM' in names and 'MSC' in names and 'Maersk Line' in names
msc = fq.directory_text('MSC')
assert '@' in msc and 'MSC' in msc, msc
assert 'ميناء الشحن' in fq.prepare({'pod': 'جدة', 'size': '40'}, lambda a: 'X')
saved = {}
def code(action):
    saved['a'] = action
    return 'ABC123'
text = fq.prepare({'pol': 'Shanghai', 'pod': 'Jeddah', 'size': '40HC', 'count': '2', 'commodity': 'furniture', 'agents': 'الكل'}, code)
assert 'نفذ ABC123' in text and 'لا يُرسل شيء قبل موافقتك' in text, text
emails = saved['a']['emails']
assert 0 < len(emails) <= fq.MAX_BATCH and all('@' in e['to'] for e in emails)
assert "2 x 40' HC" in emails[0]['subject'] and 'Shanghai' in emails[0]['body'] and 'ميناء الوصول: Jeddah' in emails[0]['body']
text = fq.prepare({'pol': 'Shanghai', 'pod': 'Jeddah', 'size': '20', 'agents': 'MSC, Maersk, CMA'}, code)
assert {e['agent'] for e in saved['a']['emails']} == {'MSC', 'Maersk Line'}, saved['a']['emails']
assert 'بدون بريد في الدليل' in text and 'CMA CGM (https://mycustomerservice.cma-cgm.com/)' in text, text
sent = []
with db() as c:
    c.execute('DELETE FROM freight_quote_requests') if c.execute("SELECT to_regclass('freight_quote_requests') t").fetchone()['t'] else None
    out = fq.execute(c, saved['a'], 'المدير', lambda to, s, b: sent.append(to))
assert len(sent) == 2 and 'أُرسل طلب عرض السعر إلى 2' in out, out
assert 'MSC' in fq.requests_text()
print('OK')
'''


@db_only
def test_directory_and_quote_requests_on_the_database():
    out = subprocess.run([sys.executable, '-c', FLOW], capture_output=True, text=True, env=os.environ,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.stdout.strip().endswith('OK'), out.stdout + out.stderr
