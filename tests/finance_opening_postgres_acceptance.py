"""Synthetic opening-balance acceptance against an isolated disposable PostgreSQL schema.

This deliberately seeds the pre-opening ledger schema before app bootstrap, then
exercises authenticated HTTP controls and real concurrent transactions. No real
customer records or network/provider actions are used.
"""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier, Event
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Frozen pre-opening schema: do not derive this fixture from the current migration.
LEGACY_DDL = (
    "CREATE TABLE IF NOT EXISTS finance_parties(\n            id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('owner','counterparty')),\n            identity_ref TEXT NOT NULL, confirmed BOOLEAN NOT NULL DEFAULT FALSE,\n            created_by BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL,\n            UNIQUE(kind,identity_ref), CHECK(length(trim(name))>0), CHECK(length(trim(identity_ref))>0))",
    "CREATE TABLE IF NOT EXISTS finance_documents(\n            id BIGSERIAL PRIMARY KEY, owner_id BIGINT NOT NULL REFERENCES finance_parties(id),\n            counterparty_id BIGINT NOT NULL REFERENCES finance_parties(id),\n            kind TEXT NOT NULL CHECK(kind IN ('claim','payable','expense','receipt','payment','receivable_adjustment','payable_adjustment')),\n            currency TEXT NOT NULL DEFAULT '', source_amount NUMERIC(20,8) NOT NULL CHECK(source_amount>0),\n            source_amount_raw TEXT NOT NULL, amount_minor BIGINT, document_date DATE,\n            source_ref TEXT NOT NULL, source_locator TEXT NOT NULL, economic_ref TEXT NOT NULL,\n            source_role TEXT NOT NULL CHECK(source_role IN ('detail','summary')),\n            source_date_raw TEXT NOT NULL DEFAULT '', source_status_raw TEXT NOT NULL DEFAULT '',\n            source_verification TEXT NOT NULL DEFAULT 'recorded' CHECK(source_verification IN ('recorded','independently_verified')),\n            verification_ref TEXT NOT NULL DEFAULT '', source_cached_external BOOLEAN NOT NULL DEFAULT FALSE,\n            invoice_ref TEXT NOT NULL DEFAULT '', customs_ref TEXT NOT NULL DEFAULT '',\n            shipment_id BIGINT REFERENCES shipments(id), amount_basis TEXT NOT NULL CHECK(amount_basis IN ('gross','net','unknown')),\n            notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','reviewed','posted','reversed','void')),\n            supersedes_id BIGINT REFERENCES finance_documents(id),\n            idempotency_key UUID NOT NULL UNIQUE, payload_hash TEXT NOT NULL,\n            created_by BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL,\n            reviewed_by BIGINT REFERENCES users(id), reviewed_at TIMESTAMPTZ, rounding_ack BOOLEAN NOT NULL DEFAULT FALSE,\n            posted_by BIGINT REFERENCES users(id), posted_at TIMESTAMPTZ,\n            reversed_by BIGINT REFERENCES users(id), reversed_at TIMESTAMPTZ, reversal_reason TEXT NOT NULL DEFAULT '',\n            CHECK(owner_id<>counterparty_id), CHECK(amount_minor IS NULL OR amount_minor>=0),\n            CHECK(status NOT IN ('reviewed','posted','reversed') OR (currency<>'' AND document_date IS NOT NULL AND amount_minor>0 AND source_role='detail')))",
    "CREATE TABLE IF NOT EXISTS finance_entries(\n            id BIGSERIAL PRIMARY KEY, document_id BIGINT NOT NULL REFERENCES finance_documents(id),\n            phase TEXT NOT NULL CHECK(phase IN ('posting','reversal')),\n            side TEXT NOT NULL CHECK(side IN ('receivable','payable')), signed_minor BIGINT NOT NULL CHECK(signed_minor<>0),\n            actor_id BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL,\n            UNIQUE(document_id,phase))",
    'CREATE TABLE IF NOT EXISTS finance_allocations(\n            id BIGSERIAL PRIMARY KEY, credit_id BIGINT NOT NULL REFERENCES finance_documents(id),\n            document_id BIGINT NOT NULL REFERENCES finance_documents(id), amount_minor BIGINT NOT NULL CHECK(amount_minor>0),\n            idempotency_key UUID NOT NULL UNIQUE, payload_hash TEXT NOT NULL,\n            created_by BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL,\n            reversed_at TIMESTAMPTZ, CHECK(credit_id<>document_id))',
    'CREATE TABLE IF NOT EXISTS finance_audit(\n            id BIGSERIAL PRIMARY KEY, actor_id BIGINT NOT NULL REFERENCES users(id),\n            action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id BIGINT NOT NULL,\n            detail TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)',
    "CREATE TABLE IF NOT EXISTS finance_entitlement_rules(\n            id BIGSERIAL PRIMARY KEY, owner_id BIGINT NOT NULL REFERENCES finance_parties(id),\n            company_scope TEXT NOT NULL, rate NUMERIC(7,4) NOT NULL CHECK(rate>0 AND rate<=100),\n            basis TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'inactive' CHECK(status='inactive'),\n            idempotency_key UUID NOT NULL UNIQUE, payload_hash TEXT NOT NULL,\n            created_by BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL)",
)


def seed_legacy_ledger():
    """Create actual old-schema evidence before the new finance migration runs."""
    from app.storage import db, init_db, rows, utcnow

    init_db(os.environ['ADMIN_EMAIL'], os.environ['ADMIN_PASSWORD'])
    now = utcnow()
    with db() as c:
        for ddl in LEGACY_DDL:
            c.execute(ddl)
        actor = c.execute('SELECT id FROM users WHERE email=%s',
                          (os.environ['ADMIN_EMAIL'],)).fetchone()['id']
        ids = []
        for kind in ('owner', 'counterparty'):
            ids.append(c.execute('''INSERT INTO finance_parties
                (name,kind,identity_ref,confirmed,created_by,created_at)
                VALUES(%s,%s,%s,TRUE,%s,%s) RETURNING id''',
                ('Synthetic legacy '+kind, kind, 'legacy-'+kind, actor, now)).fetchone()['id'])
        docs = []
        for kind, amount, minor, status, currency in (
            ('claim', '125.12500000', 12513, 'posted', 'SAR'),
            ('receipt', '25.00000000', 2500, 'posted', 'SAR'),
            ('payable', '73.00000000', 7300, 'reviewed', 'EUR'),
            ('claim', '10.00000000', 1000, 'reversed', 'USD'),
        ):
            index = len(docs)+1
            doc = c.execute('''INSERT INTO finance_documents
                (owner_id,counterparty_id,kind,currency,source_amount,source_amount_raw,
                 amount_minor,document_date,source_ref,source_locator,economic_ref,
                 source_role,source_date_raw,source_status_raw,source_verification,
                 verification_ref,source_cached_external,invoice_ref,customs_ref,
                 amount_basis,notes,status,idempotency_key,payload_hash,created_by,
                 created_at,reviewed_by,reviewed_at,rounding_ack,posted_by,posted_at,
                 reversed_by,reversed_at,reversal_reason)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'detail',%s,%s,
                    'independently_verified',%s,TRUE,%s,%s,'gross',%s,%s,%s,%s,
                    %s,%s,%s,%s,TRUE,%s,%s,%s,%s,%s) RETURNING id''',
                (*ids, kind, currency, Decimal(amount), amount+' synthetic original', minor,
                 date(2033, 12, 1), 'synthetic-legacy.xlsx', 'Legacy!A'+str(index),
                 'legacy-event-'+str(index), '2033-12-01 raw', 'synthetic original status',
                 'Synthetic legacy independent source '+str(index), 'legacy-invoice-'+str(index),
                 'legacy-customs-'+str(index), 'Synthetic legacy note '+str(index), status,
                 str(uuid.uuid4()), 'synthetic-legacy-hash-'+str(index), actor, now, actor, now,
                 actor if status != 'reviewed' else None, now if status != 'reviewed' else None,
                 actor if status == 'reversed' else None, now if status == 'reversed' else None,
                 'Synthetic legacy correction' if status == 'reversed' else '')).fetchone()['id']
            # Preserve the exact pre-opening create fingerprint for a real
            # idempotent replay after migration, not just a placeholder hash.
            legacy_row = c.execute('SELECT * FROM finance_documents WHERE id=%s', (doc,)).fetchone()
            legacy_payload = {key: legacy_row[key] for key in (
                'owner_id', 'counterparty_id', 'kind', 'currency', 'source_amount',
                'source_amount_raw', 'amount_minor', 'document_date', 'source_ref',
                'source_locator', 'economic_ref', 'source_role', 'source_date_raw',
                'source_status_raw', 'source_verification', 'verification_ref',
                'source_cached_external', 'invoice_ref', 'customs_ref', 'shipment_id',
                'amount_basis', 'notes')}
            digest = hashlib.sha256(json.dumps(legacy_payload, sort_keys=True,
                ensure_ascii=False, default=str).encode()).hexdigest()
            c.execute('UPDATE finance_documents SET payload_hash=%s WHERE id=%s', (digest, doc))
            docs.append(doc)
            if status in ('posted', 'reversed'):
                signed = -minor if kind == 'receipt' else minor
                for phase, value in [('posting', signed)]+([('reversal', -signed)] if status == 'reversed' else []):
                    c.execute('''INSERT INTO finance_entries
                        (document_id,phase,side,signed_minor,actor_id,created_at)
                        VALUES(%s,%s,'receivable',%s,%s,%s)''', (doc, phase, value, actor, now))
            c.execute('''INSERT INTO finance_audit
                (actor_id,action,entity_type,entity_id,detail,created_at)
                VALUES(%s,'document_created','document',%s,%s,%s)''',
                (actor, doc, json.dumps({'synthetic_original': index, 'source_amount': amount}), now))
        c.execute('''INSERT INTO finance_allocations
            (credit_id,document_id,amount_minor,idempotency_key,payload_hash,created_by,created_at)
            VALUES(%s,%s,1000,%s,'synthetic-legacy-allocation',%s,%s)''',
            (docs[1], docs[0], str(uuid.uuid4()), actor, now))
        c.execute('''INSERT INTO finance_entitlement_rules
            (owner_id,company_scope,rate,basis,idempotency_key,payload_hash,created_by,created_at)
            VALUES(%s,'Synthetic legacy inactive scope',30,'Synthetic unconfirmed basis',
                   %s,'synthetic-legacy-rule',%s,%s)''', (ids[0], str(uuid.uuid4()), actor, now))
    tables = ('finance_parties', 'finance_documents', 'finance_entries', 'finance_allocations',
              'finance_audit', 'finance_entitlement_rules')
    return {table: rows('SELECT * FROM '+table+' ORDER BY id') for table in tables}


def run():
    legacy = seed_legacy_ledger()
    from fastapi.testclient import TestClient
    from psycopg.errors import RaiseException
    from app.bootstrap import app
    from app import finance_core as core, finance_schema, finance_service as service
    from app.storage import db, one, rows, create_session, utcnow

    for table, originals in legacy.items():
        upgraded = rows('SELECT * FROM '+table+' ORDER BY id')
        assert len(upgraded) == len(originals), (table, 'legacy row count changed')
        for before, after in zip(originals, upgraded):
            assert all(after[key] == value for key, value in before.items()), (table, before['id'])
            if table == 'finance_documents':
                assert 'opening_cutoff' not in before
                assert after['opening_cutoff'] is None and after['opening_confirmation_ref'] == ''
                assert not after['opening_review_ack']
    assert service.statement_data(legacy['finance_parties'][0]['id'],
                                  legacy['finance_parties'][1]['id'], 'SAR', 'receivable')[3] == '100.13'
    print('PASS: real pre-opening schema migrates without changing legacy documents, amounts, IDs, entries, allocations, rules or audit.')

    client = TestClient(app, base_url='http://testserver', follow_redirects=False)
    sessions = {}
    with db() as c:
        for role in ('admin', 'finance', 'sales', 'viewer', 'transport', 'customs'):
            uid = c.execute('''INSERT INTO users(email,name,password_hash,role,created_at)
                VALUES(%s,%s,'not-a-password',%s,%s) RETURNING id''',
                ('opening-'+role+'@fixture.invalid', 'Synthetic '+role, role, utcnow())).fetchone()['id']
            sessions[role] = {'user_id': uid}
        shipment = c.execute('''INSERT INTO shipments
            (reference,service_type,revenue,cost,currency,created_at,updated_at)
            VALUES('SYNTHETIC-OPENING-SHIPMENT','synthetic',0,0,'SAR',%s,%s) RETURNING id''',
            (utcnow(), utcnow())).fetchone()['id']
    for session in sessions.values():
        sid, csrf, _ = create_session(session['user_id'])
        session.update(id=sid, csrf=csrf)
    protected = ('accounts', 'shipments', 'drivers', 'outbound_messages', 'customer_directory',
                 'driver_broadcasts', 'sales_outcomes')
    original = {table: rows('SELECT * FROM '+table+' ORDER BY id') for table in protected}

    def request(role, method, path, **kwargs):
        client.cookies.clear()
        if role:
            client.cookies.set('gla_session', sessions[role]['id'])
        return client.request(method, path, headers={'Origin': 'http://testserver'}, **kwargs)

    def form(role='admin', **extra):
        return {'csrf': sessions[role]['csrf'], 'idempotency_key': str(uuid.uuid4()), **extra}

    def post(path, data, role='admin', code=303):
        response = request(role, 'POST', path, data=data)
        assert response.status_code == code, (path, response.status_code, response.text[:1800])
        return response

    # The old request/key must still replay successfully after empty opening
    # fields were added; no extra source row, audit event or entry is created.
    legacy_doc = legacy['finance_documents'][0]
    legacy_form = {key: legacy_doc[key] for key in (
        'owner_id', 'counterparty_id', 'kind', 'currency', 'source_amount_raw',
        'document_date', 'source_ref', 'source_locator', 'economic_ref', 'source_role',
        'source_date_raw', 'source_status_raw', 'source_verification', 'verification_ref',
        'invoice_ref', 'customs_ref', 'amount_basis', 'notes')}
    legacy_form.update(amount=str(legacy_doc['source_amount']), source_cached_external='1',
                       idempotency_key=str(legacy_doc['idempotency_key']), csrf=sessions['finance']['csrf'])
    replayed = post('/finance/documents', legacy_form, 'finance')
    assert replayed.headers['location'].endswith('/'+str(legacy_doc['id']))
    assert one('SELECT COUNT(*) n FROM finance_documents')['n'] == len(legacy['finance_documents'])
    assert rows('SELECT * FROM finance_audit ORDER BY id') == legacy['finance_audit']

    sequence = 0

    def party(kind='counterparty'):
        nonlocal sequence
        sequence += 1
        ref = 'synthetic-opening-'+kind+'-'+str(sequence)
        post('/finance/parties', form(name='Synthetic '+kind+' '+str(sequence), kind=kind,
                                     identity_ref=ref, confirmed='1'))
        return one('SELECT id FROM finance_parties WHERE identity_ref=%s', (ref,))['id']

    owner, counterparty = party('owner'), party()
    cutoff = '2034-03-31'
    approval_ref = '=Synthetic owner net approval OPEN-001 through '+cutoff+' <script>synthetic</script>'

    def draft(kind='opening_receivable', amount='321.98765432', currency='SAR', **extra):
        nonlocal sequence
        sequence += 1
        opening = kind in ('opening_receivable', 'opening_payable')
        fields = dict(owner_id=owner, counterparty_id=counterparty, kind=kind, amount=amount,
                      currency=currency, document_date=cutoff if opening else '2034-04-01',
                      source_ref='synthetic-opening.xlsx', source_locator='Synthetic!A'+str(sequence),
                      economic_ref='synthetic-opening-event-'+str(sequence),
                      source_role='summary' if opening else 'detail', amount_basis='net' if opening else 'gross',
                      source_status_raw='Synthetic cached source', source_date_raw='Synthetic date evidence',
                      notes='Synthetic opening evidence; never an invoice or cash receipt')
        if opening:
            fields.update(opening_cutoff=cutoff, opening_confirmation_ref=approval_ref,
                          source_cached_external='1', source_verification='recorded')
        fields.update(extra)
        data = form('finance', **fields)
        response = post('/finance/documents', data, 'finance')
        return int(response.headers['location'].rsplit('/', 1)[1]), data

    def review(doc_id, code=303, role='finance', **extra):
        return post(f'/finance/documents/{doc_id}/review',
                    form(role, confirmation='1', **extra), role, code)

    def post_doc(doc_id, code=303, role='admin', **extra):
        return post(f'/finance/documents/{doc_id}/post',
                    form(role, confirmation='1', **extra), role, code)

    def reverse(doc_id, code=303, **extra):
        return post(f'/finance/documents/{doc_id}/reverse',
                    form(confirmation='1', reason='Synthetic correction with original preserved', **extra), code=code)

    def posted(kind='claim', amount='10.00', **extra):
        doc_id, _ = draft(kind, amount, **extra)
        acknowledgements = {'opening_ack': '1'} if kind in ('opening_receivable', 'opening_payable') else {}
        review(doc_id, **acknowledgements)
        post_doc(doc_id, **acknowledgements)
        return doc_id

    def unchanged_after_rejection(doc_id, action):
        before = one('SELECT * FROM finance_documents WHERE id=%s', (doc_id,))
        entries = rows('SELECT * FROM finance_entries ORDER BY id')
        audit = rows('SELECT * FROM finance_audit ORDER BY id')
        action()
        assert one('SELECT * FROM finance_documents WHERE id=%s', (doc_id,)) == before
        assert rows('SELECT * FROM finance_entries ORDER BY id') == entries
        assert rows('SELECT * FROM finance_audit ORDER BY id') == audit

    def assert_total(owner_id, currency, receivable, payable, debt_documents):
        # Openings are approved net balances on an explicit side. Read-only
        # totals must preserve that side and never settle allocations twice.
        before = {table: rows('SELECT * FROM '+table+' ORDER BY id') for table in legacy}
        dashboard = service.dashboard_data()
        assert len(dashboard) == 6
        matching = [item for item in dashboard[5]
                    if (item['owner_id'], item['currency']) == (owner_id, currency)]
        assert len(matching) == 1, (owner_id, currency, dashboard[5])
        total = matching[0]
        assert total['owner_name'] == one('SELECT name FROM finance_parties WHERE id=%s', (owner_id,))['name']
        assert type(total['payable_document_count']) is int and total['payable_document_count'] == debt_documents
        api_response = request('finance', 'GET', '/api/v7/finance')
        assert api_response.status_code == 200 and api_response.headers['cache-control'] == 'no-store'
        api_total = next(item for item in api_response.json()['totals']
                         if (item['owner_id'], item['currency']) == (owner_id, currency))
        assert api_total['owner_name'] == total['owner_name']
        assert api_total['payable_document_count'] == debt_documents
        balances = [item for item in dashboard[2]
                    if (item['owner_id'], item['currency']) == (owner_id, currency)]
        for field, expected in (('receivable', receivable), ('payable', payable), ('net', receivable-payable)):
            assert type(total[field+'_minor']) is int and total[field+'_minor'] == expected, (field, total)
            assert total[field+'_display'] == core.display_minor(expected, currency)
            assert type(api_total[field+'_minor']) is str and api_total[field+'_minor'] == str(expected)
            assert api_total[field+'_display'] == total[field+'_display']
            if field != 'net':
                assert sum(item[field+'_minor'] for item in balances) == expected
        for table, snapshot in before.items():
            assert rows('SELECT * FROM '+table+' ORDER BY id') == snapshot, (table, 'totals read changed source or ledger')
        return total

    legacy_owner = legacy['finance_parties'][0]['id']
    assert_total(legacy_owner, 'SAR', 10013, 0, 0)
    assert_total(legacy_owner, 'USD', 0, 0, 0)
    assert not any(item['owner_id'] == legacy_owner and item['currency'] == 'EUR'
                   for item in service.dashboard_data()[5]), 'reviewed legacy payable entered totals'

    for path in ('/finance', '/api/v7/finance',
                 f'/finance/statement?owner_id={owner}&counterparty_id={counterparty}&currency=SAR',
                 f'/finance/statement.csv?owner_id={owner}&counterparty_id={counterparty}&currency=SAR'):
        assert request(None, 'GET', path).status_code in (401, 303)
        for role in ('sales', 'viewer', 'transport', 'customs'):
            assert request(role, 'GET', path).status_code == 403
    assert request('finance', 'GET', '/finance').status_code == 200
    assert request('finance', 'GET', '/finance').headers['cache-control'] == 'no-store'

    # Malformed cutoff syntax is rejected at intake; incomplete facts may remain
    # as immutable drafts but never pass review or affect balances.
    for opening_kind in ('opening_receivable', 'opening_payable'):
        for invalid in ('2034/03/31', '2034-02-30'):
            post('/finance/documents', form('finance', kind=opening_kind, amount='10',
                 currency='SAR', opening_cutoff=invalid, source_role='summary', amount_basis='net'), 'finance', 400)
        for extra in ({'opening_cutoff': ''}, {'opening_confirmation_ref': ''},
                      {'opening_confirmation_ref': '   '}, {'document_date': '2034-03-30'},
                      {'document_date': ''}, {'currency': ''}, {'source_role': 'detail'},
                      {'amount_basis': 'gross'}, {'amount_basis': 'unknown'},
                      {'invoice_ref': 'synthetic-invoice'}, {'customs_ref': 'synthetic-customs'},
                      {'shipment_id': shipment}, {'source_verification': 'independently_verified', 'verification_ref': ''}):
            invalid_id, _ = draft(opening_kind, amount='10.00', **extra)
            unchanged_after_rejection(invalid_id, lambda: review(invalid_id, code=400, opening_ack='1'))
            post_doc(invalid_id, code=409, opening_ack='1')
    ordinary_cached, _ = draft('claim', '10.00', source_cached_external='1', source_verification='recorded')
    review(ordinary_cached, code=400)
    ordinary_summary, _ = draft('claim', '10.00', source_role='summary')
    review(ordinary_summary, code=400)

    # Review old detail first, then establish opening: post must recheck cutoff,
    # including receipts and noncash adjustments that would double-settle history.
    prereviewed = []
    for kind in ('claim', 'receipt', 'receivable_adjustment'):
        old_id, _ = draft(kind, '9.00', document_date=cutoff)
        review(old_id)
        prereviewed.append(old_id)
    opening, opening_data = draft(source_amount_raw='321.98765432 synthetic authorized net')
    assert post('/finance/documents', opening_data, 'finance').headers['location'].endswith('/'+str(opening))
    post('/finance/documents', dict(opening_data, opening_cutoff='2034-03-30'), 'finance', 409)
    post('/finance/documents', dict(opening_data, opening_confirmation_ref='different synthetic approval'), 'finance', 409)
    post('/finance/documents', dict(opening_data, idempotency_key=str(uuid.uuid4())), 'finance', 409)
    for role in ('sales', 'viewer', 'transport', 'customs'):
        post('/finance/documents', dict(opening_data, csrf=sessions[role]['csrf']), role, 403)
        review(opening, role=role, code=403, opening_ack='1', rounding_ack='1')
        post_doc(opening, role=role, code=403, opening_ack='1')
    post(f'/finance/documents/{opening}/review', {'confirmation': '1', 'opening_ack': '1'}, 'finance', 403)
    unchanged_after_rejection(opening, lambda: review(opening, code=400, rounding_ack='1'))
    unchanged_after_rejection(opening, lambda: review(opening, code=400, opening_ack='1'))
    review(opening, opening_ack='1', rounding_ack='1', reason='Synthetic net and cutoff confirmed')
    review(opening, opening_ack='1', rounding_ack='1')
    assert not any(item['owner_id'] == owner for item in service.dashboard_data()[5]), 'reviewed opening entered totals'
    post_doc(opening, role='finance', code=403, opening_ack='1')
    post(f'/finance/documents/{opening}/post', form(opening_ack='1'), code=400)
    unchanged_after_rejection(opening, lambda: post_doc(opening, code=400))
    post_doc(opening, opening_ack='1', reason='Synthetic administrative opening approval')
    post_doc(opening, opening_ack='1')
    saved = one('SELECT * FROM finance_documents WHERE id=%s', (opening,))
    assert saved['source_amount'] == Decimal('321.98765432') and saved['amount_minor'] == 32199
    assert saved['source_amount_raw'] == opening_data['source_amount_raw']
    assert saved['source_verification'] == 'recorded' and saved['verification_ref'] == ''
    assert saved['source_cached_external'] and saved['opening_review_ack'] and saved['rounding_ack']
    assert str(saved['document_date']) == str(saved['opening_cutoff']) == cutoff
    assert saved['opening_confirmation_ref'] == approval_ref
    assert saved['reviewed_by'] == sessions['finance']['user_id'] and saved['posted_by'] == sessions['admin']['user_id']
    assert saved['kind'] == 'opening_receivable' and saved['source_role'] == 'summary' and saved['amount_basis'] == 'net'
    assert not saved['invoice_ref'] and not saved['customs_ref'] and saved['shipment_id'] is None
    assert core.KINDS['opening_receivable'] == ('receivable', 1)
    entry = rows('SELECT * FROM finance_entries WHERE document_id=%s', (opening,))
    assert len(entry) == 1 and entry[0]['signed_minor'] == 32199 and entry[0]['side'] == 'receivable'
    assert service.statement_data(owner, counterparty, 'SAR', 'receivable')[3] == '321.99'
    assert service.statement_data(owner, counterparty, 'SAR', 'payable')[3] == '0.00'
    opening_total = assert_total(owner, 'SAR', 32199, 0, 0)
    assert (opening_total['receivable_display'], opening_total['payable_display'], opening_total['net_display']) == ('321.99', '0.00', '321.99')
    opening_dashboard = request('finance', 'GET', '/finance')
    assert opening_dashboard.status_code == 200
    for label in ('إجمالي الأرصدة المستحقة', 'إجمالي الديون المسجلة', 'صافي الرصيد المسجل'):
        assert label in opening_dashboard.text
    opening_audit = rows("SELECT * FROM finance_audit WHERE entity_type='document' AND entity_id=%s ORDER BY id", (opening,))
    assert [row['action'] for row in opening_audit] == ['document_created', 'document_reviewed', 'document_posted']
    for row in opening_audit:
        detail = json.loads(row['detail'])
        assert detail['opening_cutoff'] == cutoff and detail['opening_confirmation_ref'] == approval_ref
    assert json.loads(opening_audit[0]['detail'])['source_verification'] == 'recorded'
    assert json.loads(opening_audit[1]['detail'])['opening_review_ack'] is True
    assert json.loads(opening_audit[2]['detail'])['kind'] == 'opening_receivable'

    # Cutoff is inclusive, checked both before review and again at post.
    for old_id in prereviewed:
        unchanged_after_rejection(old_id, lambda: post_doc(old_id, code=409))
    for kind in ('claim', 'receipt', 'receivable_adjustment'):
        for old_date in ('2034-03-30', cutoff):
            old_id, _ = draft(kind, '9.00', document_date=old_date)
            unchanged_after_rejection(old_id, lambda: review(old_id, code=409))
    duplicate, _ = draft(amount='10.00')
    review(duplicate, code=409, opening_ack='1')

    # Same pair/currency isolation: old payables, other currencies, other owners
    # and other counterparties remain independent of this receivable cutoff.
    payable = posted('payable', '73.00', document_date='2034-03-01')
    posted('claim', '5.00', currency='USD', document_date='2034-03-01')
    another_owner = party('owner')
    posted('claim', '6.00', owner_id=another_owner, document_date='2034-03-01')
    posted('claim', '7.00', counterparty_id=party(), document_date='2034-03-01')
    receipt = posted('receipt', '40.00')
    claim = posted('claim', '80.00')
    adjustment = posted('receivable_adjustment', '10.00')
    assert service.statement_data(owner, counterparty, 'SAR', 'receivable')[3] == '351.99'
    assert service.statement_data(owner, counterparty, 'SAR', 'payable')[3] == '73.00'
    before_allocation_total = assert_total(owner, 'SAR', 35899, 7300, 1)
    assert_total(owner, 'USD', 500, 0, 0)
    assert_total(another_owner, 'SAR', 600, 0, 0)
    before_allocation = rows('SELECT * FROM finance_entries ORDER BY id')
    allocation = form(credit_id=receipt, document_id=opening, amount='25.00')
    post('/finance/allocations', allocation)
    post('/finance/allocations', allocation)
    assert one('SELECT COUNT(*) n FROM finance_allocations WHERE document_id=%s', (opening,))['n'] == 1
    assert rows('SELECT * FROM finance_entries ORDER BY id') == before_allocation
    assert assert_total(owner, 'SAR', 35899, 7300, 1) == before_allocation_total
    assert service.detail_data(opening)[0]['remaining_display'] == '296.99'
    assert service.detail_data(receipt)[0]['remaining_display'] == '15.00'
    assert any(item['id'] == opening for item in service.detail_data(receipt)[3])
    assert any(item['id'] == receipt for item in service.detail_data(opening)[3])
    post('/finance/allocations', dict(allocation, amount='26.00'), code=409)
    post('/finance/allocations', form(credit_id=receipt, document_id=opening, amount='16.00'), code=409)
    receipt_page = request('admin', 'GET', f'/finance/documents/{receipt}').text
    assert f'value="{opening}"' in receipt_page, 'opening absent from receipt allocation selector'
    opening_page = request('admin', 'GET', f'/finance/documents/{opening}').text
    assert 'action="/finance/allocations"' in opening_page
    assert f'name="document_id" value="{opening}"' in opening_page
    assert 'name="credit_id"' in opening_page and f'value="{receipt}"' in opening_page

    query = f'owner_id={owner}&counterparty_id={counterparty}&currency=SAR'
    statement = request('finance', 'GET', '/finance/statement?'+query)
    assert statement.status_code == 200 and 'رصيد افتتاحي مدين' in statement.text and cutoff in statement.text
    assert statement.headers['cache-control'] == 'no-store'
    assert '<script>synthetic</script>' not in statement.text
    exported = request('finance', 'GET', '/finance/statement.csv?'+query)
    assert exported.status_code == 200 and exported.headers['cache-control'] == 'no-store'
    exported_rows = list(csv.DictReader(io.StringIO(exported.content.decode('utf-8-sig'))))
    opening_row = next(row for row in exported_rows if row['document_id'] == str(opening))
    assert opening_row['kind'] == 'opening_receivable' and opening_row['opening_cutoff'] == cutoff
    assert opening_row['opening_confirmation_ref'] == "'"+approval_ref
    assert opening_row['debit'] == '321.99' and opening_row['credit'] == '0.00'
    assert opening_row['source_amount_raw'] == opening_data['source_amount_raw']
    assert all(row['opening_cutoff'] == '' for row in exported_rows if row['document_id'] != str(opening))
    assert exported_rows[-1]['balance'] == '351.99'
    detail_page = request('admin', 'GET', f'/finance/documents/{opening}').text
    assert '<script>synthetic</script>' not in detail_page and '&lt;script&gt;synthetic' in detail_page
    assert '321.98765432' in detail_page and cutoff in detail_page
    api = request('finance', 'GET', '/api/v7/finance').json()
    api_opening = next(item for item in api['documents'] if item['id'] == opening)
    assert api_opening['kind'] == 'opening_receivable' and api_opening['side'] == 'receivable'
    assert api_opening['source_amount'] == '321.98765432' and api_opening['opening_cutoff'] == cutoff
    assert api['external_actions'] is False

    # Opening cannot be undone while any later receivable document is active,
    # even if a remaining document is a noncash adjustment rather than a claim.
    for subsequent, expected_receivable in ((claim, 27899), (receipt, 31899), (adjustment, 32899)):
        unchanged_after_rejection(opening, lambda: reverse(opening, code=409))
        reverse(subsequent)
        assert_total(owner, 'SAR', expected_receivable, 7300, 1)
    assert one('SELECT COUNT(*) n FROM finance_allocations WHERE document_id=%s AND reversed_at IS NULL', (opening,))['n'] == 0
    assert service.detail_data(opening)[0]['remaining_display'] == '321.99'
    reverse(opening)
    reverse(opening)
    assert service.statement_data(owner, counterparty, 'SAR', 'receivable')[3] == '0.00'
    assert one('SELECT status FROM finance_documents WHERE id=%s', (payable,))['status'] == 'posted'
    assert one('SELECT COUNT(*) n FROM finance_entries WHERE document_id=%s', (opening,))['n'] == 2
    reversed_total = assert_total(owner, 'SAR', 700, 7300, 1)
    assert reversed_total['net_display'] == '-66.00'
    corrected_data = dict(opening_data, idempotency_key=str(uuid.uuid4()), amount='322.01',
                          source_amount_raw='322.01 synthetic corrected authorized net',
                          opening_confirmation_ref='Synthetic corrected owner approval OPEN-002')
    corrected_response = post('/finance/documents', corrected_data, 'finance')
    corrected = int(corrected_response.headers['location'].rsplit('/', 1)[1])
    review(corrected, opening_ack='1')
    post_doc(corrected, opening_ack='1')
    corrected_saved = one('SELECT * FROM finance_documents WHERE id=%s', (corrected,))
    assert corrected_saved['supersedes_id'] == opening
    assert corrected_saved['source_ref'] == saved['source_ref'] and corrected_saved['source_locator'] == saved['source_locator']
    assert service.statement_data(owner, counterparty, 'SAR', 'receivable')[3] == '322.01'
    assert_total(owner, 'SAR', 32901, 7300, 1)
    after_reverse = one('SELECT * FROM finance_documents WHERE id=%s', (opening,))
    for field in ('kind', 'source_amount', 'source_amount_raw', 'source_ref', 'source_locator', 'source_status_raw',
                  'source_date_raw', 'source_verification', 'source_cached_external', 'verification_ref',
                  'opening_cutoff', 'opening_confirmation_ref', 'opening_review_ack', 'reviewed_by', 'reviewed_at'):
        assert after_reverse[field] == saved[field], field
    assert rows('SELECT * FROM finance_audit WHERE id=ANY(%s) ORDER BY id', ([row['id'] for row in opening_audit],)) == opening_audit
    print('PASS: explicit review/admin approval, exact net source, cached provenance, cutoff/history guards, opening-only and owner/currency totals, exact API strings, partial allocation without double settlement, read-only source/journal preservation, statement HTML/CSV, reversal and corrected opening.')

    # Payable openings use the same evidence and approvals, but increase debt.
    # Keep this owner isolated so the committed receivable totals cases above
    # continue to assert exactly their original amounts and currency boundaries.
    payable_owner, payable_pair = party('owner'), party()
    payable_scope = dict(owner_id=payable_owner, counterparty_id=payable_pair)
    payable_kinds = ('payable', 'expense', 'payment', 'payable_adjustment')
    prereviewed_payables = []
    for kind in payable_kinds:
        old_id, _ = draft(kind, '9.00', document_date=cutoff, **payable_scope)
        review(old_id)
        prereviewed_payables.append(old_id)
    opening_payable, payable_data = draft('opening_payable', '210.12500000',
        source_amount_raw='-210.12500000 synthetic original credit balance', **payable_scope)
    assert post('/finance/documents', payable_data, 'finance').headers['location'].endswith('/'+str(opening_payable))
    for changed in ({'opening_cutoff': '2034-03-30'}, {'opening_confirmation_ref': 'Different synthetic approval'},
                    {'source_amount_raw': '210.12500000 sign removed'}):
        post('/finance/documents', dict(payable_data, **changed), 'finance', 409)
    unchanged_after_rejection(opening_payable, lambda: review(opening_payable, code=400, rounding_ack='1'))
    unchanged_after_rejection(opening_payable, lambda: review(opening_payable, code=400, opening_ack='1'))
    review(opening_payable, opening_ack='1', rounding_ack='1')
    review(opening_payable, opening_ack='1', rounding_ack='1')
    assert not any(item['owner_id'] == payable_owner for item in service.dashboard_data()[5])
    post_doc(opening_payable, role='finance', code=403, opening_ack='1')
    unchanged_after_rejection(opening_payable, lambda: post_doc(opening_payable, code=400))
    post_doc(opening_payable, opening_ack='1')
    post_doc(opening_payable, opening_ack='1')
    payable_saved = one('SELECT * FROM finance_documents WHERE id=%s', (opening_payable,))
    assert payable_saved['source_amount'] == Decimal('210.12500000') and payable_saved['amount_minor'] == 21013
    assert payable_saved['source_amount_raw'] == payable_data['source_amount_raw']
    assert payable_saved['source_verification'] == 'recorded' and payable_saved['verification_ref'] == ''
    assert payable_saved['source_cached_external'] and payable_saved['opening_review_ack'] and payable_saved['rounding_ack']
    assert str(payable_saved['document_date']) == str(payable_saved['opening_cutoff']) == cutoff
    assert payable_saved['opening_confirmation_ref'] == approval_ref
    assert payable_saved['kind'] == 'opening_payable' and payable_saved['source_role'] == 'summary'
    assert payable_saved['amount_basis'] == 'net' and not payable_saved['invoice_ref'] and not payable_saved['customs_ref']
    assert payable_saved['shipment_id'] is None and core.KINDS['opening_payable'] == ('payable', 1)
    payable_entries = rows('SELECT * FROM finance_entries WHERE document_id=%s', (opening_payable,))
    assert len(payable_entries) == 1 and payable_entries[0]['side'] == 'payable' and payable_entries[0]['signed_minor'] == 21013
    payable_audit = rows("SELECT * FROM finance_audit WHERE entity_type='document' AND entity_id=%s ORDER BY id", (opening_payable,))
    assert [row['action'] for row in payable_audit] == ['document_created', 'document_reviewed', 'document_posted']
    for row in payable_audit:
        detail = json.loads(row['detail'])
        assert detail['opening_cutoff'] == cutoff and detail['opening_confirmation_ref'] == approval_ref
    assert json.loads(payable_audit[0]['detail'])['source_amount_raw'] == payable_data['source_amount_raw']
    assert json.loads(payable_audit[0]['detail'])['source_verification'] == 'recorded'
    assert json.loads(payable_audit[1]['detail'])['opening_review_ack'] is True
    assert_total(payable_owner, 'SAR', 0, 21013, 1)

    for old_id in prereviewed_payables:
        unchanged_after_rejection(old_id, lambda: post_doc(old_id, code=409))
    for kind in payable_kinds:
        for old_date in ('2034-03-30', cutoff):
            old_id, _ = draft(kind, '9.00', document_date=old_date, **payable_scope)
            unchanged_after_rejection(old_id, lambda: review(old_id, code=409))
    duplicate_payable, _ = draft('opening_payable', '10.00', **payable_scope)
    unchanged_after_rejection(duplicate_payable, lambda: review(duplicate_payable, code=409, opening_ack='1'))

    # A payable cutoff never blocks receivable history. Once reversed, that
    # history does not prohibit a separate receivable opening on the same pair.
    for kind in ('claim', 'receipt', 'receivable_adjustment'):
        independent = posted(kind, '7.00', document_date=cutoff, **payable_scope)
        assert service.statement_data(payable_owner, payable_pair, 'SAR', 'payable')[3] == '210.13'
        reverse(independent)
    coexist_receivable = posted('opening_receivable', '65.00', **payable_scope)
    assert_total(payable_owner, 'SAR', 6500, 21013, 1)
    independent_currency = posted('payable', '5.00', currency='USD', document_date=cutoff, **payable_scope)
    assert_total(payable_owner, 'USD', 0, 500, 1)
    assert one('SELECT status FROM finance_documents WHERE id=%s', (independent_currency,))['status'] == 'posted'
    later_payable = posted('payable', '25.00', **payable_scope)
    later_expense = posted('expense', '15.00', **payable_scope)
    later_payment = posted('payment', '40.00', **payable_scope)
    payable_adjustment = posted('payable_adjustment', '10.00', **payable_scope)
    payable_before_allocation = assert_total(payable_owner, 'SAR', 6500, 20013, 3)
    entries_before_payable_allocation = rows('SELECT * FROM finance_entries ORDER BY id')
    payment_allocation = form(credit_id=later_payment, document_id=opening_payable, amount='25.00')
    post('/finance/allocations', payment_allocation)
    post('/finance/allocations', payment_allocation)
    post('/finance/allocations', form(credit_id=payable_adjustment, document_id=opening_payable, amount='5.00'))
    assert one('SELECT COUNT(*) n FROM finance_allocations WHERE document_id=%s', (opening_payable,))['n'] == 2
    assert rows('SELECT * FROM finance_entries ORDER BY id') == entries_before_payable_allocation
    assert assert_total(payable_owner, 'SAR', 6500, 20013, 3) == payable_before_allocation
    assert service.detail_data(opening_payable)[0]['remaining_display'] == '180.13'
    assert service.detail_data(later_payment)[0]['remaining_display'] == '15.00'
    assert service.detail_data(payable_adjustment)[0]['remaining_display'] == '5.00'
    assert any(item['id'] == opening_payable for item in service.detail_data(later_payment)[3])
    assert {later_payment, payable_adjustment}.issubset({item['id'] for item in service.detail_data(opening_payable)[3]})
    post('/finance/allocations', dict(payment_allocation, amount='26.00'), code=409)
    post('/finance/allocations', form(credit_id=later_payment, document_id=opening_payable, amount='16.00'), code=409)
    post('/finance/allocations', form(credit_id=later_payment, document_id=coexist_receivable, amount='1.00'), code=400)
    payment_page = request('admin', 'GET', f'/finance/documents/{later_payment}').text
    assert f'value="{opening_payable}"' in payment_page
    payable_page = request('admin', 'GET', f'/finance/documents/{opening_payable}').text
    assert f'name="document_id" value="{opening_payable}"' in payable_page and f'value="{later_payment}"' in payable_page

    payable_query = urlencode(dict(**payable_scope, currency='SAR', side='payable'))
    payable_statement = request('finance', 'GET', '/finance/statement?'+payable_query)
    assert payable_statement.status_code == 200 and cutoff in payable_statement.text
    assert '<script>synthetic</script>' not in payable_statement.text
    payable_export = request('finance', 'GET', '/finance/statement.csv?'+payable_query)
    assert payable_export.status_code == 200 and payable_export.headers['cache-control'] == 'no-store'
    payable_export_rows = list(csv.DictReader(io.StringIO(payable_export.content.decode('utf-8-sig'))))
    payable_opening_row = next(row for row in payable_export_rows if row['document_id'] == str(opening_payable))
    payment_row = next(row for row in payable_export_rows if row['document_id'] == str(later_payment))
    assert payable_opening_row['kind'] == 'opening_payable' and payable_opening_row['opening_cutoff'] == cutoff
    assert payable_opening_row['opening_confirmation_ref'] == "'"+approval_ref
    assert payable_opening_row['source_amount_raw'] == "'"+payable_data['source_amount_raw']
    assert payable_opening_row['debit'] == '0.00' and payable_opening_row['credit'] == '210.13'
    assert payment_row['debit'] == '40.00' and payment_row['credit'] == '0.00'
    assert payable_export_rows[-1]['balance'] == '200.13'
    payable_api = next(item for item in request('finance', 'GET', '/api/v7/finance').json()['documents'] if item['id'] == opening_payable)
    assert payable_api['kind'] == 'opening_payable' and payable_api['side'] == 'payable'
    assert payable_api['source_amount'] == '210.12500000' and payable_api['source_amount_raw'] == payable_data['source_amount_raw']

    for subsequent, expected_payable, debt_count in ((later_payable, 17513, 2), (later_expense, 16013, 1),
                                                    (later_payment, 20013, 1), (payable_adjustment, 21013, 1)):
        unchanged_after_rejection(opening_payable, lambda: reverse(opening_payable, code=409))
        reverse(subsequent)
        assert_total(payable_owner, 'SAR', 6500, expected_payable, debt_count)
    assert one('SELECT COUNT(*) n FROM finance_allocations WHERE document_id=%s AND reversed_at IS NULL', (opening_payable,))['n'] == 0
    assert service.detail_data(opening_payable)[0]['remaining_display'] == '210.13'
    reverse(opening_payable)
    reverse(opening_payable)
    assert one('SELECT status FROM finance_documents WHERE id=%s', (coexist_receivable,))['status'] == 'posted'
    assert one('SELECT COUNT(*) n FROM finance_entries WHERE document_id=%s', (opening_payable,))['n'] == 2
    assert_total(payable_owner, 'SAR', 6500, 0, 0)
    payable_reversal = service.statement_data(payable_owner, payable_pair, 'SAR', 'payable')[2][-1]
    assert payable_reversal['debit_display'] == '210.13' and payable_reversal['credit_display'] == '0.00'
    corrected_payable_data = dict(payable_data, idempotency_key=str(uuid.uuid4()), amount='211.00',
        source_amount_raw='-211.00 synthetic corrected credit balance',
        opening_confirmation_ref='Synthetic corrected liability approval OPEN-P-002')
    corrected_payable_response = post('/finance/documents', corrected_payable_data, 'finance')
    corrected_payable = int(corrected_payable_response.headers['location'].rsplit('/', 1)[1])
    review(corrected_payable, opening_ack='1')
    post_doc(corrected_payable, opening_ack='1')
    corrected_payable_saved = one('SELECT * FROM finance_documents WHERE id=%s', (corrected_payable,))
    assert corrected_payable_saved['supersedes_id'] == opening_payable
    assert corrected_payable_saved['source_ref'] == payable_saved['source_ref'] and corrected_payable_saved['source_locator'] == payable_saved['source_locator']
    assert corrected_payable_saved['source_amount'] == Decimal('211.00')
    assert corrected_payable_saved['source_amount_raw'] == corrected_payable_data['source_amount_raw']
    assert_total(payable_owner, 'SAR', 6500, 21100, 1)
    reverse(coexist_receivable)  # The still-posted payable opening is independent.
    assert_total(payable_owner, 'SAR', 0, 21100, 1)
    payable_after_reverse = one('SELECT * FROM finance_documents WHERE id=%s', (opening_payable,))
    for field in ('kind', 'source_amount', 'source_amount_raw', 'source_ref', 'source_locator', 'source_status_raw',
                  'source_date_raw', 'source_verification', 'source_cached_external', 'verification_ref',
                  'opening_cutoff', 'opening_confirmation_ref', 'opening_review_ack', 'reviewed_by', 'reviewed_at'):
        assert payable_after_reverse[field] == payable_saved[field], field
    assert rows('SELECT * FROM finance_audit WHERE id=ANY(%s) ORDER BY id', ([row['id'] for row in payable_audit],)) == payable_audit
    print('PASS: payable opening preserves signed source evidence, adds debt, uses credit/debit statement polarity, coexists by side, blocks historical liabilities/settlements, allocates without double reduction, and corrects without rewriting history.')

    # Any posted history on the SAME side prevents a fresh opening. Rechecking
    # at post catches the case where opening review happened before that history.
    side_cases = (('opening_receivable', 'receivable', ('claim', 'receipt', 'receivable_adjustment')),
                  ('opening_payable', 'payable', payable_kinds))
    for opening_kind, side, historical_kinds in side_cases:
        for kind in historical_kinds:
            pair = party()
            candidate, _ = draft(opening_kind, amount='90.00', counterparty_id=pair)
            review(candidate, opening_ack='1')
            existing = posted(kind, '12.00', counterparty_id=pair)
            unchanged_after_rejection(candidate, lambda: post_doc(candidate, code=409, opening_ack='1'))
            later_candidate, _ = draft(opening_kind, amount='90.00', counterparty_id=pair)
            review(later_candidate, code=409, opening_ack='1')
            reverse(existing)
            post_doc(candidate, opening_ack='1')

    def concurrent_posts(ids, acknowledgements):
        barrier = Barrier(len(ids))
        def submit(index):
            isolated = TestClient(app, base_url='http://testserver', follow_redirects=False)
            isolated.cookies.set('gla_session', sessions['admin']['id'])
            try:
                barrier.wait(timeout=15)
                result = isolated.post(f'/finance/documents/{ids[index]}/post',
                    data=form(confirmation='1', **acknowledgements[index]), headers={'Origin': 'http://testserver'})
                return result.status_code
            finally:
                isolated.close()
        with ThreadPoolExecutor(max_workers=len(ids)) as pool:
            return list(pool.map(submit, range(len(ids))))

    for opening_kind, side, historical_kinds in side_cases:
        pair = party()
        duplicates = [draft(opening_kind, amount='90.00', counterparty_id=pair)[0] for _ in range(3)]
        for item in duplicates:
            review(item, opening_ack='1')
        statuses = concurrent_posts(duplicates, [{'opening_ack': '1'}]*3)
        assert sorted(statuses) == [303, 409, 409], (opening_kind, statuses)
        assert one("SELECT COUNT(*) n FROM finance_documents WHERE counterparty_id=%s AND status='posted'", (pair,))['n'] == 1
        assert one('SELECT COUNT(*) n FROM finance_entries e JOIN finance_documents d ON d.id=e.document_id WHERE d.counterparty_id=%s', (pair,))['n'] == 1
        winner = duplicates[statuses.index(303)]
        assert concurrent_posts([winner]*3, [{'opening_ack': '1'}]*3) == [303, 303, 303]
        assert one('SELECT COUNT(*) n FROM finance_entries WHERE document_id=%s', (winner,))['n'] == 1
        assert one("SELECT COUNT(*) n FROM finance_audit WHERE entity_type='document' AND entity_id=%s AND action='document_posted'", (winner,))['n'] == 1

        for kind in historical_kinds:
            pair = party()
            candidate, _ = draft(opening_kind, amount='90.00', counterparty_id=pair)
            historical, _ = draft(kind, '12.00', counterparty_id=pair, document_date=cutoff)
            review(candidate, opening_ack='1')
            review(historical)
            statuses = concurrent_posts([candidate, historical], [{'opening_ack': '1'}, {}])
            assert sorted(statuses) == [303, 409], (kind, statuses)
            assert one("SELECT COUNT(*) n FROM finance_documents WHERE counterparty_id=%s AND status='posted'", (pair,))['n'] == 1
            expected = '90.00' if statuses[0] == 303 else '12.00' if core.KINDS[kind][1] > 0 else '-12.00'
            assert service.statement_data(owner, pair, 'SAR', side)[3] == expected

    # The uniqueness gate includes side, so concurrent openings for the same
    # pair and currency on different sides must both succeed exactly once.
    pair = party()
    both_sides = [draft(kind, '14.00', counterparty_id=pair)[0]
                  for kind in ('opening_receivable', 'opening_payable')]
    for item in both_sides:
        review(item, opening_ack='1')
    assert concurrent_posts(both_sides, [{'opening_ack': '1'}]*2) == [303, 303]
    assert one("SELECT COUNT(*) n FROM finance_documents WHERE counterparty_id=%s AND status='posted'", (pair,))['n'] == 2
    for side in ('receivable', 'payable'):
        assert service.statement_data(owner, pair, 'SAR', side)[3] == '14.00'

    # The same transaction-scoped advisory lock actually serializes review, post,
    # and reverse; a second connection holding that key must block each action.
    def under_global_lock(action):
        entered = Event()
        original_lock = service.lock
        def observed_lock(connection):
            entered.set()
            original_lock(connection)
            held = connection.execute('''SELECT COUNT(*) n FROM pg_locks
                WHERE locktype='advisory' AND pid=pg_backend_pid() AND objid=%s
                AND mode='ExclusiveLock' AND granted''', (finance_schema.LOCK_KEY,)).fetchone()['n']
            assert held == 1
        with patch.object(service, 'lock', observed_lock), ThreadPoolExecutor(max_workers=1) as pool:
            with db() as holder:
                holder.execute('SELECT pg_advisory_xact_lock(%s)', (finance_schema.LOCK_KEY,))
                result = pool.submit(action)
                assert entered.wait(timeout=15), 'mutation never attempted the shared transaction lock'
                assert not result.done(), 'mutation bypassed the held global lock'
            result.result(timeout=30)
    for opening_kind in ('opening_receivable', 'opening_payable'):
        lock_doc, _ = draft(opening_kind, amount='11.00', counterparty_id=party())
        under_global_lock(lambda: review(lock_doc, opening_ack='1'))
        under_global_lock(lambda: post_doc(lock_doc, opening_ack='1'))
        under_global_lock(lambda: reverse(lock_doc))
    print('PASS: concurrent duplicate openings/idempotent retries, competing historical postings, and shared transaction lock on review/post/reverse.')

    for immutable_opening in (corrected, corrected_payable):
        for sql, args in (
            ('UPDATE finance_documents SET opening_cutoff=%s WHERE id=%s', ('2034-04-01', immutable_opening)),
            ('UPDATE finance_documents SET opening_confirmation_ref=%s WHERE id=%s', ('tampered synthetic approval', immutable_opening)),
            ('UPDATE finance_documents SET source_amount=%s WHERE id=%s', (Decimal('1.00'), immutable_opening)),
            ('UPDATE finance_documents SET source_amount_raw=%s WHERE id=%s', ('1.00 sign and source altered', immutable_opening)),
            ('UPDATE finance_documents SET source_verification=%s WHERE id=%s', ('independently_verified', immutable_opening)),
            ('DELETE FROM finance_documents WHERE id=%s', (immutable_opening,)),
            ('DELETE FROM finance_entries WHERE document_id=%s', (immutable_opening,)),
            ("UPDATE finance_audit SET detail='tampered synthetic audit' WHERE entity_id=%s", (immutable_opening,)),
        ):
            try:
                with db() as c:
                    c.execute(sql, args)
                raise AssertionError('Immutable opening evidence accepted mutation: '+sql)
            except RaiseException:
                pass

    snapshots = {table: rows('SELECT * FROM '+table+' ORDER BY id') for table in legacy}
    finance_schema.init_storage()
    finance_schema.init_storage()
    for table, snapshot in snapshots.items():
        assert rows('SELECT * FROM '+table+' ORDER BY id') == snapshot, (table, 'migration changed ledger')
    for table, snapshot in original.items():
        assert rows('SELECT * FROM '+table+' ORDER BY id') == snapshot, (table, 'operational data changed')
    with db() as c:
        c.execute('''INSERT INTO role_permissions(role,permission,allowed,updated_at)
            VALUES('finance','view_finance',0,%s)''', (utcnow(),))
    assert request('finance', 'GET', f'/finance/documents/{corrected}').status_code == 403
    with db() as c:
        c.execute('''INSERT INTO role_permissions(role,permission,allowed,updated_at)
            VALUES('sales','approve_finance',1,%s)''', (utcnow(),))
    post_doc(corrected, role='sales', code=403, opening_ack='1')
    with db() as c:
        c.execute('UPDATE users SET is_active=0 WHERE id=%s', (sessions['admin']['user_id'],))
    assert request('admin', 'GET', '/finance').status_code in (303, 403)
    client.close()
    print('PASS: RBAC/CSRF/explicit denies, immutable opening source/approval/cutoff/audit, repeated additive migrations, no revenue/receipt fabrication or operational overwrite; external sends 0.')


def main():
    import psycopg
    from psycopg import sql

    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    target = urlsplit(url)
    if (target.scheme not in ('postgres', 'postgresql')
            or target.hostname not in ('localhost', '127.0.0.1')
            or target.path != '/afaaq_test' or target.query or target.fragment):
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema = 'finance_opening_test_'+secrets.token_hex(6)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect = socket.socket.connect
    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1'):
            raise AssertionError('External network blocked in opening-balance acceptance')
        return connect(sock, address)
    try:
        env = {
            'DATABASE_URL': url+'?'+urlencode({'options': '-c search_path='+schema+' -c statement_timeout=30000 -c lock_timeout=15000'}, quote_via=quote),
            'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0',
            'ADMIN_EMAIL': 'opening-bootstrap@fixture.invalid',
            'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0',
        }
        with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', local_only):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: opening-balance PostgreSQL acceptance.')


if __name__ == '__main__':
    main()
