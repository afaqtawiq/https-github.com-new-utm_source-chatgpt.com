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


def test_china_partner_campaign():
    from app import daily_prospects as dp
    from app.prospect_autopilot import china_message, CHINA_SUBJECT
    assert dp.classify('Shenzhen Star Logistics', 'وكلاء شحن وموردون في الصين يشحنون للسعودية — forwarder', 'Shenzhen')[0] == 'china_partner'
    assert dp.classify('يوبي للإستيراد من الصين', 'استيراد من الصين / وسيط توريد', 'الرياض')[0] == 'china'
    t = china_message('Star')
    assert 'FASAH' in t and '清关' in t and '2513' in t and '沙特' in CHINA_SUBJECT
    assert ROTATION.count('china') == 2


def test_lead_contacts_are_verified_on_the_company_site(monkeypatch):
    """Owner, 24 Nov 2026: Reem must work like the lead finder in Claude — contacts only from the company's own site."""
    import asyncio
    import httpx as _httpx
    from app import marketing_desk as md
    pages = {
        'https://good.ae': '<html>Welcome</html>',
        'https://good.ae/contact': '<html>Call +971 50 123 4567 or mail sales@good.ae <img src="a@2x.png"></html>',
        'https://nosite.ae': '<html>nothing</html>',
    }

    def handler(request):
        url = str(request.url).rstrip('/')
        if url in pages:
            return _httpx.Response(200, text=pages[url], headers={'content-type': 'text/html'})
        return _httpx.Response(404, text='no')
    real = _httpx.AsyncClient
    monkeypatch.setattr(md.httpx, 'AsyncClient', lambda **kw: real(transport=_httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != 'transport'}))
    out = asyncio.run(md.verify([
        {'company': 'Good Cargo', 'website': 'good.ae', 'phone': '+971 55 999 0000', 'email': 'fake@good.ae'},
        {'company': 'No Contacts', 'website': 'https://nosite.ae', 'phone': '+971 50 000 0000'},
        {'company': 'No Site', 'phone': '+971 50 111 1111'}]))
    good, none, nosite = out
    assert good['verified'] and good['phone'] == '971501234567' and good['email'] == 'sales@good.ae' and good['source'].endswith('/contact')
    assert not none['verified'] and not nosite['verified']
    assert md.parse_items('Here: ```json\n[{"company":"A","phone":"+971500000000"}]\n``` [1]') == [{'company': 'A', 'phone': '+971500000000'}]
