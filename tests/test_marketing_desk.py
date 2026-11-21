import os
import subprocess
import sys

import pytest

from app.marketing_desk import SEGMENTS, ROTATION, _digits

db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')


def test_basics():
    assert _digits('0551234567') == '966551234567' and _digits('+86 21 1234 5678') == '862112345678' and _digits('x') == ''
    assert set(ROTATION) <= set(SEGMENTS)
    from app.daily_prospects import classify
    assert classify('شركة الأفق للشحن الدولي', 'شركات الشحن ووكلاء الشحن — فريت', '')[0] == 'forwarder'


SCRIPT = r'''
import uuid
from app import data_import, marketing_desk as md
from app.storage import db
tag = uuid.uuid4().hex[:6]
items = [{'company': 'شركة تجربة الشحن ' + tag, 'city': 'جدة', 'activity': 'شحن', 'phone': '05' + tag[:0] + '5' + str(int(tag, 16) % 10**7).zfill(7), 'email': '', 'source': 'https://x'},
         {'company': 'بلا تواصل ' + tag, 'phone': '', 'email': ''}]
added, skipped = md.store('forwarder', items)
assert len(added) == 1 and skipped == 1, (added, skipped)
added, skipped = md.store('forwarder', items[:1])
assert not added and skipped == 1
t = md.report(1)
assert 'عملاء جدد من البحث: ' in t, t
print('OK')
'''


@db_only
def test_store_and_report():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().endswith('OK'), r.stderr[-2500:] + r.stdout[-500:]


def test_uae_carriers_back_in_outreach(monkeypatch):
    from app import daily_prospects as dp
    key, label, score, pitch = dp.classify('Mega Al Sahar Cargo', 'FTL Dubai to Saudi Arabia', '')
    assert key == 'uae_carrier' and score == 45 and 'البطحاء' in pitch
    assert 'uae' in SEGMENTS and ROTATION[0] == 'uae'
