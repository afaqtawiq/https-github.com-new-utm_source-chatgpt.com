import datetime as dt
import os
import subprocess
import sys

import pytest

from app.fasah_authorizations import _date, _norm

pytestmark_db = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')


def test_dates_and_names():
    assert _date('31/12/2026') == dt.date(2026, 12, 31) and _date('2026-01-05') == dt.date(2026, 1, 5) and _date('x') is None
    assert _norm('شركة بروميت') in _norm('شركة بروميت للتجارة')


SCRIPT = r'''
import datetime as dt
from app import fasah_authorizations as fa, agent_runner
from app.storage import db
agent_runner.init(); fa.init()
with db() as c:
    c.execute('DELETE FROM fasah_authorizations')
    c.execute("DELETE FROM runner_tasks WHERE kind='fasah_authorizations'")
today = dt.date.today()
fa.store([{'importer': 'شركة بروميت للتجارة', 'number': 'A1', 'end': (today + dt.timedelta(days=10)).isoformat(), 'status': 'ساري'},
          {'importer': 'مؤسسة سلة الرحائب', 'number': 'A2', 'end': (today + dt.timedelta(days=200)).isoformat()}], 1)
t = fa.answer('بروميت')
assert 'بروميت' in t and 'باقي 10 يوم' in t and 'الرحائب' not in t and 'أنشأت المهمة' not in t, t
t = fa.answer('شركة غير موجودة')
assert 'ما لقيت' in t and 'أنشأت المهمة' in t, t
t = fa.answer('شركة غير موجودة')
assert 'يقرأ قائمة التفاويض الآن' in t, t
assert 'بروميت' in fa.expiring_text() and 'الرحائب' not in fa.expiring_text()
print('OK')
'''


@pytestmark_db
def test_answer_and_refresh():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().endswith('OK'), r.stderr[-2000:] + r.stdout[-500:]
