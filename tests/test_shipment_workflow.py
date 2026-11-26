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


TRANSIT_SCRIPT = r'''
from app import shipment_files as sf, shipment_workflow as sw
from app.storage import db
sf._start_flow = lambda bill: None  # no background run/notification in the test
sf.init(); sw.init()
with db() as c:
    c.execute("DELETE FROM shipment_files WHERE bill_no IN ('ETG0138695','TRN-REVIEW-1')")
bl = {'document_kind': 'shipping_document', 'bill_no': 'ETG0138695', 'shipping_line': 'CMA CGM', 'vessel': 'CMA CGM COLUMBIA',
      'consignee': 'AHEMD IMAM FOR GENERAL TRADING', 'consignee_address': 'MUAITHER PLOT NO-53 DOHA QATAR',
      'notify_party': 'AFAQ TAWEEQ CONTRACTING AR RIYAD SAUDI ARABIA', 'marks': 'DEST: QUATR', 'pol': 'DJIBOUTI', 'pod': 'JEDDAH',
      'container_numbers': ['TCNU8381090']}
row = sf.upsert_from_document(bl)
assert (row['movement'], row['destination']) == ('transit', 'QA'), row
assert 'ترانزيت' in sf.card(row) and 'منفذ سلوى' in sf.card(row)
text = sw.run('ETG0138695', 'test')
assert 'لا أجهّز طلب تفويض استيراد' in text and 'بيان عبور' in text and 'منفذ سلوى' in text, text
assert 'التسليم لمستودع العميل' not in text and 'import_requirements' not in text, text
assert 'خروج الشحنة إلى قطر' in sw.arrival_message(sf.find('ETG0138695')[0])
# a later document pointing to Saudi Arabia must not silently flip it: the file goes to review and the flow stops
sf.upsert_from_document(dict(bl, consignee='X TRADING', consignee_address='RIYADH SAUDI ARABIA', marks='', notify_party=''))
assert sf.find('ETG0138695')[0]['movement'] == 'review'
assert 'أوقفت سير الشحنة' in sw.run('ETG0138695', 'test')
# staff settle it
assert 'نوع البيان: ترانزيت' in sf.update('ETG0138695', movement='ترانزيت إلى قطر', actor='test')
assert sf.find('ETG0138695')[0]['movement'] == 'transit'
print('OK')
'''


@db_only
def test_transit_bill_runs_transit_flow():
    out = subprocess.run([sys.executable, '-c', TRANSIT_SCRIPT], capture_output=True, text=True, env=os.environ,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.stdout.strip().endswith('OK'), out.stdout + out.stderr


FILL_SCRIPT = r'''
import json
from app import fasah_ai as ai, agent_runner as ar
from app.storage import db, one, utcnow
ar.init()
user = one('SELECT id FROM users ORDER BY id LIMIT 1')
case = {'title': 'اختبار إدخال فسح ETG', 'fields': {}, 'documents': [{'name': 'inv.txt', 'kind': 'invoice', 'pages': [{'page': 1, 'text': 'INV-77'}]}],
        'context': {'profile': {'transaction': 'transit'}}}
answers = iter([{'items': [{'description': 'coffee'}], 'fields': {'invoice_number': {'value': 'INV-77', 'source': 'inv.txt'}}, 'issues': [],
                'routing': {'consignee_address': 'DOHA QATAR'}, 'coverage': {'all_lines_extracted': True, 'total_invoice_lines': 1}},
               {'items': [{'index': 0, 'code': '090111000000', 'alternatives': []}]}])
ai.ask = lambda *a, **k: next(answers)
ai.tariff_lookup.search_many = lambda *a, **k: [{'code': '090111000000', 'duty': '0%'}]
ai.tariff_lookup.as_prompt = lambda e: e
case['context']['ai'] = ai.analyze(case)
assert case['context']['ai']['coverage']['partial_or_unverified'] is False, case['context']['ai']['coverage']['blockers']
with db() as c:
    c.execute('DELETE FROM runner_tasks WHERE kind=%s', ('fasah_fill',))
    did = c.execute("""INSERT INTO fasah_workspace_drafts(created_by,title,fields_json,documents_json,context_json,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (user['id'], case['title'], '{}', json.dumps(case['documents'], ensure_ascii=False),
        json.dumps(case['context'], ensure_ascii=False), utcnow(), utcnow())).fetchone()['id']
text = ai.fill_by_reference('آخر', 'المدير')
assert 'أنشأت المهمة' in text and 'لا يضغط أي زر' in text, text
with db() as c:
    row = c.execute("SELECT * FROM runner_tasks WHERE kind='fasah_fill' ORDER BY id DESC LIMIT 1").fetchone()
p = json.loads(row['params_json'])
assert p['case_id'] == did and p['fields'][0]['value'] == 'INV-77' and 'submit_label' not in p and 'url' not in p, p
assert 'ترانزيت' in p['movement'] and p['items'][0]['code']
assert 'ما لقيت معاملة' in ai.fill_by_reference('غير-موجودة-xyz')
print('OK')
'''


@db_only
def test_fasah_fill_task_from_workspace_case():
    out = subprocess.run([sys.executable, '-c', FILL_SCRIPT], capture_output=True, text=True, env=os.environ,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.stdout.strip().endswith('OK'), out.stdout + out.stderr
