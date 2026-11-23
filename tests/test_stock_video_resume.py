import os
import subprocess
import sys

import pytest

db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')

SCRIPT = r'''
import time
from app import stock_video as sv
from app.storage import db
sv.init()
with db() as c:
    c.execute("DELETE FROM stock_video_jobs")
    c.execute("INSERT INTO stock_video_jobs(topic,status,created_at) VALUES('قديم','producing',NOW()-INTERVAL '2 days')")
    c.execute("INSERT INTO stock_video_jobs(topic,status,created_at) VALUES('جديد','producing',NOW()-INTERVAL '30 minutes')")
done = []
sv._work = lambda job, topic, actor='', dialect=None: done.append(topic)
sv.resume_interrupted(delay=0)
time.sleep(2)
assert done == ['جديد'], done
t = sv.status_text()
assert 'فشل' in t and 'انقطع الإنتاج' in t, t
print('OK')
'''


@db_only
def test_resume():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().endswith('OK'), r.stderr[-2500:] + r.stdout[-800:]
