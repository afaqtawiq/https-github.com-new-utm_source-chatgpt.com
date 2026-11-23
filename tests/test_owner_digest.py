import os
import subprocess
import sys

import pytest

db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')

SCRIPT = r'''
import asyncio
from app import owner_briefing as ob
from app.storage import db
sent = []
async def fake(text):
    sent.append(text); return 'whatsapp'
ob.send_now = fake
with db() as c:
    ob._outbox(c); c.execute("DELETE FROM owner_outbox")
async def main():
    assert await ob.deliver('المهمة #371 فشلت: المتصفح مغلق') == 'queued'
    await ob.deliver('المهمة #371 فشلت: المتصفح مغلق')
    await ob.deliver('🧾 كشف سلة جاهز: نفذ 514424')
    assert await ob.flush_outbox() == 0          # still within the quiet window
    assert await ob.flush_outbox(force=True) == 3
    await ob.deliver('عاجل', urgent=True)
asyncio.run(main())
assert len(sent) == 2, sent
assert sent[0].startswith('📋 المدير العام — 2 تحديثات') and '×2' in sent[0] and 'نفذ 514424' in sent[0], sent[0]
assert sent[1] == 'عاجل'
print('OK')
'''


@db_only
def test_digest():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().endswith('OK'), r.stderr[-2500:] + r.stdout[-800:]
