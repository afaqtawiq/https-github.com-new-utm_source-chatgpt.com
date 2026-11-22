import os
import subprocess
import sys

import pytest

from app import shipment_workflow as sw

db_only = pytest.mark.skipif('afaaq_test' not in os.getenv('DATABASE_URL', ''), reason='needs local afaaq_test')


def test_same_party():
    assert sw.same_party('MADA ALTTATWIR ALLHADITH FOR TRADING (مؤسسة مدى التطوير الحديث للتجارة)', 'مؤسسة مدى التطوير الحديث للتجارة')
    assert sw.same_party('مدى التطوير الحديث', 'مؤسسه مدي التطوير الحديث للتجاره')
    assert not sw.same_party('مؤسسة مدى التطوير الحديث للتجارة', 'شركة الياسمين للتجارة')


SCRIPT = r'''
import datetime as dt, json
from app import shipment_files as sf, shipment_workflow as sw, fasah_authorizations as fa, command_agent as ca
from app.storage import db
sf.init(); sw.init(); fa.init()
with db() as c:
    c.execute("DELETE FROM fasah_authorizations")
    c.execute("UPDATE shipment_files SET steps='{}', docs='[\"bl\"]' WHERE bill_no='280395789'")
    c.execute("CREATE TABLE IF NOT EXISTS whatsapp_admin_audit(id BIGSERIAL PRIMARY KEY, sender TEXT, conversation_id TEXT, created_at TIMESTAMPTZ DEFAULT NOW())")
    c.execute("CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT NOT NULL, conversation_id TEXT NOT NULL, command TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL, consumed BOOLEAN DEFAULT FALSE)")
    c.execute("INSERT INTO whatsapp_admin_audit(sender,conversation_id) VALUES('966500000001','conv1')")
import os; os.environ['WHATSAPP_COMMAND_OWNER'] = '966500000001'
row = sf.find('280395789')[0]
st, line = sw.authorization(row)
assert st == 'unknown', (st, line)
fa.store([{'importer': 'مؤسسة مدى التطوير الحديث للتجارة', 'number': '77', 'end': '2026-01-01', 'status': ''}])
st, line = sw.authorization(row)
assert st == 'expired', (st, line)
msg = sw.authorization_message(row, st)
assert '2513' in msg and 'مؤسسة آفاق طويق للتخليص الجمركي' in msg and 'منتهٍ' in msg
assert sw.missing_docs(row) == ['invoice', 'packing', 'origin']
assert '280395789' in sw.note_document({'document_kind': 'commercial_invoice', 'bill_no': '', 'consignee': 'MADA ALTTATWIR ALLHADITH FOR TRADING'})
ca.CHAT.set(None)
out = sw.run('280395789', 'فيصل')
assert 'تفويض فسح' in out and 'التفويض منتهٍ' in out and 'نفذ ' in out, out
assert 'قائمة التعبئة' in out and 'الفاتورة التجارية، ' not in out.split('ناقص:')[1], out
assert 'تقرير وصول الشحنة' in out, out
assert 'لم يُسجل رقمه بعد' in out
with db() as c:
    codes = c.execute("SELECT command FROM whatsapp_voice_pending WHERE sender='966500000001' AND command LIKE '%%shipment_step%%'").fetchall()
assert len(codes) >= 3, codes
again = sw.run('280395789')
assert 'مجهّز ينتظر' in again, again
print(sf.update('280395789', docs_received='وصلت قائمة التعبئة وشهادة المنشأ')[:20])
assert sw.missing_docs(sf.find('280395789')[0]) == []
print('OK')
'''


@db_only
def test_workflow_run():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=90)
    assert r.stdout.strip().endswith('OK'), r.stderr[-3000:] + r.stdout[-1500:]
