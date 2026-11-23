import os
import subprocess
import sys

import pytest

db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')

SCRIPT = r'''
import datetime as dt
from app import group_watch as gw, group_dispatch as gd, virtual_office as vo, owner_briefing as ob
from app.storage import db, utcnow
gw.init(); gd.init()
with db() as c: c.execute("DELETE FROM whatsapp_group_messages")
old = utcnow() - dt.timedelta(hours=20)
gw.store('acc', 'g1', 'قروب ميناء جدة', 'm1', 'incoming', '966500000111', 'أبو فهد', 'بيان', 1, old)
gw.store('acc', 'g1', 'قروب ميناء جدة', 'm2', 'incoming', '966500000111', 'أبو فهد', 'نبغى سعر نقل سطحة للرياض', 0, old + dt.timedelta(minutes=2))
asked, sent = [], []
vo.ask = lambda key, text, author, **kw: (asked.append((key, text)) or 'طلبت أسعار من 12 سائق، أقل سعر حتى الآن 1,700')
gd._read_pdfs = lambda burst, limit=3: [{'document_kind': 'customs_declaration', 'pod': 'Jeddah'}]
async def fake(text, urgent=False): sent.append(text); return 'queued'
ob.deliver = fake
assert gd.route('نبغى سعر نقل سطحة') == 'transport' and gd.route('كم بند التعرفة') == 'clearance'
assert gd.run_round() == 1, asked
assert asked[0][0] == 'transport' and 'driver_price_request' in asked[0][1], asked
assert 'خالد' in sent[0] and '1,700' in sent[0], sent
assert gd.run_round() == 0
assert gw.due(utcnow()) == []
print('OK')
'''


@db_only
def test_dispatch():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().endswith('OK'), r.stderr[-2500:] + r.stdout[-800:]
