import os
import subprocess
import sys

import pytest

from app import ops_watch as ow

db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')


def test_health_alerts_once_and_waits_for_transient(monkeypatch):
    ow._last_alert.update(t=0.0, kind=''); ow._failures['n'] = 0
    monkeypatch.setattr(ow, 'probe', lambda: 'credit')
    assert 'رصيد Anthropic' in ow.health_tick(now=1000)
    assert ow.health_tick(now=2000) == ''            # deduped
    assert 'رصيد' in ow.health_tick(now=1000 + 7 * 3600)  # repeated after 6 h
    monkeypatch.setattr(ow, 'probe', lambda: '')
    assert ow.health_tick(now=99999) == '' and ow._failures['n'] == 0
    monkeypatch.setattr(ow, 'probe', lambda: 'network')
    assert ow.health_tick(now=100000) == '' and ow.health_tick(now=100001) == ''
    assert 'تفشل' in ow.health_tick(now=100002)


SCRIPT = r'''
import datetime as dt, json
from app import shipment_tracking as st, ops_watch as ow
from app.storage import db, utcnow
st.init()
with db() as c:
    c.execute("DELETE FROM shipment_tracks WHERE ref IN ('T280395789','TOLD1')")
    c.execute("INSERT INTO shipment_tracks(ref,ref_type,vessel,voyage,pod,eta,containers,created_at) VALUES('T280395789','bl','MAERSK CHARLESTON','641W','Jeddah',%s,%s,%s)",
              (utcnow() + dt.timedelta(hours=20), json.dumps(['A','B','C','D','E']), utcnow()))
    c.execute("INSERT INTO shipment_tracks(ref,ref_type,eta,created_at) VALUES('TOLD1','bl',%s,%s)", (utcnow() + dt.timedelta(days=5), utcnow()))
t = ow.arrivals_text()
assert 'T280395789' in t and '5 حاوية' in t and 'TOLD1' not in t, t
print('OK')
'''


@db_only
def test_arrivals():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().endswith('OK'), r.stderr[-2500:] + r.stdout[-500:]
