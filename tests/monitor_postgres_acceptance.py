"""Exercise monitoring persistence against disposable CI PostgreSQL only."""
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).parents[1]))
url = os.environ['AFAAQ_TEST_DATABASE_URL']
target = urlsplit(url)
assert target.hostname in {'localhost', '127.0.0.1'} and target.path == '/afaaq_test'
os.environ['DATABASE_URL'] = url
from app.agent_monitor import start_run, update_run, snapshot
rid = start_run()
update_run(rid, 'فحص مصدر الاختبار', 0, 2, {'signals': 0})
assert snapshot()['run']['status'] == 'running'
update_run(rid, 'انتهى مع مصدر متعذر', 2, 2, {'signals': 3, 'opportunities': 0, 'errors': 1}, 'partial')
view = snapshot()
assert view['run']['id'] == rid
assert view['run']['status'] == 'partial'
assert view['run']['finished_at'] is not None
assert view['run']['result']['opportunities'] == 0
assert view['events'][0]['label'] == 'انتهى مع مصدر متعذر'
print('Monitor persistence acceptance passed')

from app import live_activity as live
from app.storage import db
first, second = live.begin('المهمة الأولى'), live.begin('المهمة الثانية')
items, missing = live.current_items()
assert any('المهمة الأولى' in x['label'] and x['status'] == 'running' for x in items)
assert any('المهمة الثانية' in x['label'] and x['status'] == 'running' for x in items)
live.finish(first, 'انتهت الأولى')
live.finish(second, 'انتهت الثانية')
for i in range(10):
    live.finish(live.begin('مهمة'), 'نتيجة')
with db() as c:
    assert c.execute('SELECT COUNT(*) AS n FROM agent_live_operations').fetchone()['n'] == 1
    c.execute("CREATE TABLE monitor_test_jobs(id BIGSERIAL PRIMARY KEY,status TEXT,updated_at TIMESTAMPTZ)")
    c.execute("INSERT INTO monitor_test_jobs(status,updated_at) VALUES('image_pending',NOW())")
live.SOURCES += (('monitor_test_jobs', 'إنتاج الصور التجريبي', 'id', 'status', 'updated_at'),)
items, missing = live.current_items()
assert missing == 0, 'An installed workflow table could not be read'
assert any('إنتاج الصور' in x['label'] and x['status'] == 'waiting' for x in items)
compact = snapshot(compact=True)
assert compact['items']
assert all(set(x) <= {'label','status','at','entity_id'} for x in compact['items'])
print('Concurrent bounded live monitoring acceptance passed')
