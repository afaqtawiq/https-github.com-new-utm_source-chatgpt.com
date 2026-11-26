"""خالد — منصات النقل (طلب المالك، 26 نوفمبر 2026)."""
import importlib.util
import os
import pathlib
import subprocess
import sys
import types
from unittest.mock import Mock, patch

import pytest

_storage = types.ModuleType('app.storage')
_storage.db = Mock(side_effect=AssertionError('db'))
_storage.utcnow = Mock()
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec = importlib.util.spec_from_file_location('_tp', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'transport_platforms.py')
    tp = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(tp)

# نص الدعوة كما وصل على واتساب من +966540562522 (26 نوفمبر 2026)
GULF_INVITE = """مرحباً بكم في مكتب شاحنات الخليج للنقل

ندعوكم للتسجيل والانضمام إلى منصتنا الإلكترونية، لتسهيل تقديم طلبات النقل والحصول على عروض الأسعار ومتابعة شحناتكم بكل سهولة وسرعة.

https://app.gulf-transports.com

نشكركم على ثقتكم بنا.

Welcome to Gulf Trucks  Office

We invite you to register and join our online platform for easier transport requests, faster quotations, and convenient shipment tracking.

https://app.gulf-transports.com

Thank you for your trust."""


def test_gulf_trucks_invitation_is_detected():
    found = tp.detect(GULF_INVITE)
    assert found['domain'] == 'app.gulf-transports.com'
    assert found['url'] == 'https://app.gulf-transports.com'
    assert 'شاحنات الخليج' in found['name']


def test_ordinary_links_are_not_platform_invitations():
    assert tp.detect('موقعنا https://www.afaqtwiq.com للتسجيل في خدمات النقل') is None
    assert tp.detect('الموقع على الخريطة https://maps.google.com/?q=jeddah') is None
    assert tp.detect('سجل في النقل https://wa.me/966500000000') is None
    assert tp.detect('شاهد الفيديو https://example.com/video') is None  # no invitation to register
    assert tp.detect('سجل في منصتنا https://example.com') is None      # not about transport
    assert tp.detect('') is None and tp.detect(None) is None


db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')

FLOW = r'''
import json, sys
from app import transport_platforms as tp, agent_runner as ar
from app.storage import db
tp.init(); ar.init()
with db() as c:
    c.execute("DELETE FROM transport_platforms WHERE domain='app.gulf-transports.com'")
    c.execute("DELETE FROM company_profile")
    c.execute("DELETE FROM runner_tasks WHERE kind='platform_signup'")
invite = tp.detect(sys.argv[1])
notice = tp.record(invite, '966540562522', 'text')
assert 'سجّل في منصة app.gulf-transports.com' in notice and '+966540562522' in notice, notice
assert tp.record(invite, '966540562522') is None  # one notice per platform
assert not ar.domain_allowed('https://app.gulf-transports.com/register/')  # not opened before the manager approves
text = tp.signup('app.gulf-transports.com', 'المدير')
assert 'رقم السجل التجاري' in text and 'الرقم الضريبي' in text, text  # company numbers are missing: no task
assert tp.set_profile({'cr_number': '123'}, 'المدير') == 'رقم السجل التجاري 10 أرقام.'
assert tp.set_profile({'vat_number': '123456789012345'}, 'المدير').startswith('الرقم الضريبي')
saved = tp.set_profile({'cr_number': '٤٠٣٠١٢٣٤٥٦', 'vat_number': '300012345600003'}, 'المدير')
assert '4030123456' in saved and 'ناقص' not in saved, saved
text = tp.signup('gulf', 'المدير')
assert 'أنشأت المهمة' in text and 'كلمة المرور' in text, text
assert ar.domain_allowed('https://app.gulf-transports.com/register/')
with db() as c:
    task = c.execute("SELECT * FROM runner_tasks WHERE kind='platform_signup' ORDER BY id DESC LIMIT 1").fetchone()
p = json.loads(task['params_json'])
values = {f['key']: f['value'] for f in p['fields']}
assert values['cr_number'] == '4030123456' and values['legal_name'] and 'submit_label' not in p, p
assert not any('password' in f['key'] for f in p['fields'])
tp.after_task(task['id'], True)
assert tp.find('gulf')['status'] == 'filled'
assert 'أُرسل طلب التسجيل' in tp.mark('gulf', 'submitted', 'المدير')
assert 'شاحنات الخليج' in tp.status_text()
print('OK')
'''


@db_only
def test_invitation_to_signup_flow_on_the_database():
    out = subprocess.run([sys.executable, '-c', FLOW, GULF_INVITE], capture_output=True, text=True, env=os.environ,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.stdout.strip().endswith('OK'), out.stdout + out.stderr
