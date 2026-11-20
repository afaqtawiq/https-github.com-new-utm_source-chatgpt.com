import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')

SCRIPT = """import asyncio, os, sys, types
""" + 'from app import load_broadcast as lb\nfrom app.storage import db, utcnow\nlb.init()\nsent = []\nfake = types.SimpleNamespace(WhatsAppBlocked=type(\'B\', (Exception,), {}))\nasync def send(phone, text):\n    sent.append(phone)\nfake.send = send\nsys.modules[\'app.zernio_whatsapp\'] = fake\nos.environ[\'LOAD_BROADCAST_DELAY\'] = \'0\'\nos.environ[\'LOAD_BROADCAST_STOP_AFTER\'] = \'2\'\nwith db() as c:\n    bid = c.execute(\'\'\'INSERT INTO load_broadcasts(origin,destination,weight,driver_price,unloading,payment,audience,message,status,created_at)\n        VALUES(\'جدة\',\'الرياض\',\'27\',\'5000\',\'الرياض\',\'حسب الاتفاق\',\'all\',\'x\',\'sending\',%s) RETURNING id\'\'\', (utcnow(),)).fetchone()[\'id\']\n    for i in range(6):\n        c.execute("INSERT INTO load_broadcast_recipients(broadcast_id,phone,status) VALUES(%s,%s,%s)",\n                  (bid, f\'96650000{bid:03d}{i}\', \'accepted\' if i < 2 else \'pending\'))\nasyncio.run(lb.send_all(bid))\nassert sent == []\ntext = lb.status_text(f\'AFT-{bid}\')\nassert \'توقف الإرسال تلقائيًا\' in text and \'متبقي 0\' in text and \'وافق 2\' in text\nwith db() as c:\n    c.execute("UPDATE load_broadcasts SET status=\'sending\' WHERE id=%s", (bid,))\nlb.interrupted_on_startup()\nassert \'انقطع بإعادة تشغيل\' in lb.status_text(f\'AFT-{bid}\')\nassert \'غير جارٍ\' in lb.stop(f\'AFT-{bid}\')\n' + """
print('OK')
"""


def test_stops_after_acceptances_and_reports_interrupted():
    # Fresh interpreter: other test modules replace app.storage in sys.modules.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().endswith('OK'), r.stderr[-2000:]
