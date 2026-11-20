import os
import subprocess
import sys

import pytest

from app.expenses_desk import _amount, _currency

db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')


def test_parsing():
    assert str(_amount('١٠٠ دولار')) == '100' and str(_amount('1,250.50')) == '1250.50'
    assert _currency('دولار') == 'USD' and _currency('') == 'SAR' and _currency('aed') == 'AED'


SCRIPT = r'''
import uuid
from app.storage import db, utcnow
from app import finance_schema, expenses_desk
finance_schema.init_storage()
with db() as c:
    u = c.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if not u:
        u = c.execute("INSERT INTO users(username,password_hash,role,is_active,created_at) VALUES(%s,'x','admin',TRUE,%s) RETURNING id", ('exp-test-'+uuid.uuid4().hex[:6], utcnow())).fetchone()
    uid = u['id']
    if not c.execute("SELECT 1 FROM finance_parties WHERE kind='owner' AND confirmed").fetchone():
        c.execute("INSERT INTO finance_parties(name,kind,identity_ref,confirmed,created_by,created_at) VALUES('آفاق طويق','owner','OWNER-TEST',TRUE,%s,%s)", (uid, utcnow()))
t = expenses_desk.record('Anthropic', '100', uid, currency='USD', description='رصيد Anthropic API', method='بطاقة')
assert 'مصروف رقم' in t and 'سداد رقم' in t and '100.00 USD' in t, t
t2 = expenses_desk.record('Anthropic', '100', uid, currency='USD', description='رصيد Anthropic API', method='بطاقة')
assert 'مصروف رقم' in t2, t2  # idempotent replay, no duplicate
with db() as c:
    n = c.execute("SELECT COUNT(*) n FROM finance_documents d JOIN finance_parties p ON p.id=d.counterparty_id WHERE p.name='Anthropic'").fetchone()['n']
assert n == 2, n
assert 'Anthropic' in expenses_desk.recent_text()
print('OK')
'''


@db_only
def test_record_expense_and_payment():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().endswith('OK'), r.stderr[-2500:] + r.stdout[-500:]
