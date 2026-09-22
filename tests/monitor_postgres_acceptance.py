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
