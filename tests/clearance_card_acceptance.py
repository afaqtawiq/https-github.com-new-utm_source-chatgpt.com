"""Stages 1-3 (case card, document cross-check with page/line, fee ledger) through the real app on isolated
PostgreSQL. MOCK level: no model call is made (the saved analysis is injected), no external service, nothing sent."""
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
url = os.environ['AFAAQ_TEST_DATABASE_URL']
assert urlsplit(url).hostname in {'localhost', '127.0.0.1'} and urlsplit(url).path == '/afaaq_test'
import psycopg
schema = 'clear_card_' + secrets.token_hex(5)
with psycopg.connect(url, autocommit=True) as connection:
    connection.execute('CREATE SCHEMA ' + schema)
os.environ.update(DATABASE_URL=url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
                  DISCOVERY_AUTO_ENABLED='0', ENABLE_EXTERNAL_ACTIONS='0', ANTHROPIC_API_KEY='',
                  ADMIN_EMAIL='card@example.invalid', ADMIN_PASSWORD=secrets.token_urlsafe(24))
INVOICE = '''COMMERCIAL INVOICE
Invoice No: INV-5001
Importer: Afaq Test Trading
Supplier: Ningbo Test Furniture Co
Gross Weight: 12,500 KG
Total Packages: 120 CTNS
Container No: MSCU1234567
Country of Origin: China
Currency: USD
Office chair model A   120   PCS   3,600.00
Invoice Total: 3,600.00'''
BL = '''BILL OF LADING
B/L No: MEDU998877
Consignee: Afaq Test Trading
Port of Discharge: Jeddah Islamic Port
Gross Weight: 12.5 T
Total Packages: 118 CTNS
Container No: MSCU1234567 / MSCU7654321'''
PACKING = '''PACKING LIST
Invoice No: INV-5001
Office chair model A   120 CTNS
Gross Weight: 12,500 KG
Net Weight: 11,900 KG'''
try:
    from app.bootstrap import app
    from app.storage import one, create_session
    from app import clearance_card, fasah_ai, fee_ledger
    from fastapi.testclient import TestClient
    client = TestClient(app, follow_redirects=False)
    uid = one("SELECT id FROM users WHERE email='card@example.invalid'")['id']
    sid, csrf, _ = create_session(uid)
    client.cookies.set('gla_session', sid)
    client.headers['origin'] = 'http://testserver'
    created = client.post('/fasah-workspace', data={'title': 'كراسي مكتبية — جدة', 'csrf': csrf})
    path = created.headers['location']; case_id = int(path.rsplit('/', 1)[-1])
    rev = lambda: one('SELECT revision FROM fasah_workspace_drafts WHERE id=?', (case_id,))['revision']
    def draft():
        from app import fasah_workspace as ws
        row = one('SELECT * FROM fasah_workspace_drafts WHERE id=?', (case_id,))
        row['fields'] = json.loads(row['fields_json']); row['documents'] = json.loads(row['documents_json'])
        row['context'] = json.loads(row['context_json']); return row
    for kind, name, text in (('invoice', 'invoice.txt', INVOICE), ('transport', 'bl.txt', BL), ('packing', 'packing.txt', PACKING)):
        assert client.post(path + '/text', data={'csrf': csrf, 'revision': rev(), 'kind': kind, 'name': name, 'text': text}).status_code == 303
    assert client.post(path + '/profile', data={'csrf': csrf, 'revision': rev(), 'transaction': 'commercial_import', 'mode': 'sea',
                                                 'origin_marking': '', 'goods': 'كراسي مكتبية', 'dispatch_country': 'الصين'}).status_code == 303

    # 1) The existing case page now links the card; the card renders (escaped) with states and the next step.
    assert '/card' in client.get(path).text
    page = client.get(path + '/card')
    assert page.status_code == 200 and 'بطاقة المعاملة' in page.text and page.headers['cache-control'] == 'no-store'
    card = clearance_card.build(draft())
    assert card['shipment_type'] == 'استيراد تجاري — بحري' and card['goods'] == 'كراسي مكتبية'
    states = {r['key']: r['state'] for r in card['requirements']}
    assert states['origin'] == 'conditional' and states['invoice'] == 'verify' and states['packing'] == 'conditional', states
    assert card['overall'] == 'فيه تعارض' and card['analysis'] == 'none'

    # 2) Conflicts between invoice / B/L / packing list, each bound to document + page + line.
    conflicts = {c['field']: c for c in card['cross_check']['conflicts']}
    assert 'packages' in conflicts and '118' in conflicts['packages']['message'] and '120' in conflicts['packages']['message']
    assert 'bl.txt ص1 س6' in conflicts['packages']['message'], conflicts['packages']['message']
    assert 'gross_weight' not in conflicts, 'same weight in KG and T must not be a conflict'
    assert 'containers' in conflicts and 'MSCU7654321' in conflicts['containers']['message']
    assert any(s['line'] == 2 and s['document'] == 'invoice.txt' for s in card['cross_check']['fields']['invoice_number'])

    # 3) Injected saved analysis (as the model would return) → item quantities/values linked to the line.
    case = draft()
    ai = {'items': [{'source_index': 0, 'description': 'Office chair model A', 'quantity': '120', 'value': '3,600.00'},
                    {'source_index': 1, 'description': 'Desk lamp', 'quantity': '77', 'value': None}],
          'source_fingerprint': fasah_ai.source_fingerprint(case), 'fields_fingerprint': clearance_card.fields_fingerprint(case),
          'coverage': {}}
    case['context']['ai'] = ai
    from app import fasah_workspace as ws
    session = {'user_id': uid, 'csrf': csrf}
    ws.persist(case, session, case['revision'], 'test_inject_analysis')
    card = clearance_card.build(draft())
    assert card['analysis'] == 'fresh'
    ev = {(i['index'], k): v for i in card['cross_check']['items'] for k, v in i['evidence'].items()}
    assert ev[(0, 'quantity')]['status'] in ('linked', 'ambiguous') and ev[(0, 'quantity')]['where'][0]['line'] == 10
    assert ev[(1, 'quantity')]['status'] == 'not_found'

    # 4) Port corrected after analysis → analysis stale, card asks to re-analyse, FASAH copy is blocked.
    fields = draft()['fields']
    values = {'csrf': csrf, 'revision': rev(), **{'value_' + k: f['value'] for k, f in fields.items()}}
    values['value_arrival_port'] = 'ميناء الملك عبدالعزيز بالدمام'
    assert client.post(path + '/fields', data=values).status_code == 303
    case = draft()
    card = clearance_card.build(case)
    assert card['analysis'] == 'stale' and card['next_step'].startswith('أعد تحليل المستندات') and card['port'].startswith('ميناء الملك')
    assert fasah_ai.current_coverage(case, case['context']['ai'])['stale_sources'] is True
    # Old analyses without the new fields fingerprint keep their previous behaviour (no forced invalidation).
    old = dict(case['context']['ai']); old.pop('fields_fingerprint'); old['source_fingerprint'] = fasah_ai.source_fingerprint(case)
    assert fasah_ai.current_coverage(case, old)['stale_sources'] is False
    case['context']['ai'] = old
    assert clearance_card.analysis_state(case)[0] == 'unknown'

    # 5) Fee ledger: providers separated, duplicates refused, included lines not double-counted, no invented total.
    def fee(**kw):
        return client.post(path + '/card/fees', data={'csrf': csrf, 'revision': rev(), 'currency': 'SAR', 'vat': 'unknown',
                                                      'source_kind': 'manual', 'status': 'needs_verification', **kw})
    assert fee(category='afaq_fee', description='أتعاب التخليص للحاوية', amount='700', vat='excluded', vat_rate='15',
               source_kind='quote', source_ref='ATQ-10', status='confirmed').status_code == 303
    dup = fee(category='afaq_fee', description='أتعاب التخليص', amount='700', source_kind='quote', source_ref='ATQ 10')
    assert dup.status_code == 200 and 'مسجل مسبقًا' in dup.text
    assert fee(category='customs', description='رسوم جمركية 5%', amount='').status_code == 303
    assert fee(category='agent', description='إذن تسليم شامل المناولة', amount='450', vat='included', source_kind='agent',
               source_ref='DO-77', status='confirmed').status_code == 303
    parent = one("SELECT id FROM clearance_fee_items WHERE source_ref='DO-77'")['id']
    assert fee(category='port', description='مناولة', amount='100', vat='included', source_kind='port', source_ref='PT-1',
               status='confirmed', included_in=str(parent)).status_code == 303
    assert 'المبلغ غير واضح' in fee(category='port', description='x', amount='مية').text
    s = fee_ledger.summary(case_id)
    assert s['final_total'] is None and any('تحتاج تحقق' in r or 'يحتاج تحقق' in r for r in s['not_final_reasons'])
    assert s['subtotals']['afaq_fee|SAR'] == fee_ledger.Decimal('700.00') and 'port|SAR' not in s['subtotals']
    text = fee_ledger.text(case_id)
    assert 'لا يوجد إجمالي نهائي' in text and 'ضمن البند' in text and 'أتعاب آفاق طويق' in text and 'الوكيل الملاحي' in text
    # A "confirmed" line without a source reference is stored as needs-verification.
    rid, _ = fee_ledger.add(case_id, {'category': 'saber', 'description': 'شهادة إرسالية', 'amount': '500', 'vat': 'included',
                                      'source_kind': 'saber', 'status': 'confirmed'}, 'test')
    assert one('SELECT status FROM clearance_fee_items WHERE id=?', (rid,))['status'] == 'needs_verification'
    # Resolve: remove the unknown customs line and the unsourced SABER line → a final total appears (700+15% VAT + 450).
    fee_ledger.deactivate(case_id, one("SELECT id FROM clearance_fee_items WHERE category='customs'")['id'])
    fee_ledger.deactivate(case_id, rid)
    s = fee_ledger.summary(case_id)
    assert s['final_total'] == fee_ledger.Decimal('1255.00') and s['final_currency'] == 'SAR', s
    # Mixed currency → no total.
    fee_ledger.add(case_id, {'category': 'transport', 'description': 'نقل', 'amount': '100', 'currency': 'USD', 'vat': 'exempt',
                             'source_kind': 'transport', 'source_ref': 'TR-1', 'status': 'confirmed'}, 'test')
    assert fee_ledger.summary(case_id)['final_total'] is None

    # 6) Responsible + due date saved without touching documents/fields (analysis fingerprint unchanged).
    before = fasah_ai.source_fingerprint(draft()), clearance_card.fields_fingerprint(draft())
    assert client.post(path + '/card/owner', data={'csrf': csrf, 'revision': rev(), 'owner': 'ناصر', 'due': '2026-11-12'}).status_code == 303
    after = draft()
    assert (fasah_ai.source_fingerprint(after), clearance_card.fields_fingerprint(after)) == before
    card = clearance_card.build(after)
    assert card['owner'] == 'ناصر' and card['due'] == '2026-11-12'
    assert client.post(path + '/card/owner', data={'csrf': 'bad', 'revision': rev(), 'owner': 'x'}).status_code == 403
    api = client.get('/api/v7/clearance-card/' + str(case_id))
    assert api.status_code == 200 and api.json()['owner'] == 'ناصر'
    # Another employee cannot read this case card.
    from app.storage import execute, utcnow
    execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('o@example.invalid','o','x','customs',?)", (utcnow(),))
    other = one("SELECT id FROM users WHERE email='o@example.invalid'")['id']
    osid, _, _ = create_session(other)
    client.cookies.set('gla_session', osid)
    assert client.get(path + '/card').status_code == 404
    print('PASS: case card states/next step, cross-document conflicts with page/line, stale analysis on port change, fee ledger.')
finally:
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute('DROP SCHEMA ' + schema + ' CASCADE')
