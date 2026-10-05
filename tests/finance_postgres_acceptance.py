"""Disposable synthetic PostgreSQL finance acceptance. Blocks all external egress."""
import csv
import io
import json
import os
from pathlib import Path
import secrets
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import finance_core as core, finance_schema, finance_service as service
    from app.storage import db, one, rows, create_session, utcnow
    from psycopg.errors import RaiseException
    client=TestClient(app,base_url='http://testserver',follow_redirects=False)
    sessions={}
    with db() as c:
        for role in ('admin','finance','sales','viewer','transport','customs'):
            uid=c.execute('INSERT INTO users(email,name,password_hash,role,created_at) VALUES(%s,%s,%s,%s,%s) RETURNING id',(role+'@fixture.invalid',role,'not-a-password',role,utcnow())).fetchone()['id']
            sessions[role]={'user_id':uid}
    for role,s in sessions.items():
        sid,csrf,_=create_session(s['user_id']);s.update(id=sid,csrf=csrf)
    def request(role,method,path,**kwargs):
        client.cookies.clear()
        if role:client.cookies.set('gla_session',sessions[role]['id'])
        headers={'Origin':'http://testserver',**kwargs.pop('headers',{})}
        return client.request(method,path,headers=headers,**kwargs)
    def form(role='admin',**extra):
        return {'csrf':sessions[role]['csrf'],'idempotency_key':str(uuid.uuid4()),**extra}
    def post(path,data,role='admin',code=303):
        res=request(role,'POST',path,data=data)
        assert res.status_code==code,(path,res.status_code,res.text[:1500])
        return res
    def make_party(name,kind,ref):
        post('/finance/parties',form(name=name,kind=kind,identity_ref=ref,confirmed='1'))
        return one('SELECT id FROM finance_parties WHERE identity_ref=%s',(ref,))['id']
    protected=('accounts','shipments','drivers','outbound_messages','customer_directory','driver_broadcasts')
    original={t:rows('SELECT * FROM '+t+' ORDER BY id') for t in protected}
    assert one('SELECT COUNT(*) n FROM finance_documents')['n']==0
    for path in ('/finance','/api/v7/finance','/finance/documents/1','/finance/statement?owner_id=1&counterparty_id=2&currency=SAR','/finance/statement.csv?owner_id=1&counterparty_id=2&currency=SAR'):
        assert request(None,'GET',path).status_code in (401,303)
        for role in ('sales','viewer','transport','customs'):assert request(role,'GET',path).status_code==403
    assert request('finance','GET','/finance').status_code==200
    assert request('finance','GET','/finance').headers['cache-control']=='no-store'
    assert request('finance','GET','/api/v7/finance').headers['cache-control']=='no-store'
    assert 'المحاسبة والمالية' in request('admin','GET','/dashboard').text
    post('/finance/parties',form('finance',name='No authority',kind='owner',identity_ref='denied',confirmed='1'),'finance',403)
    post('/finance/parties',{'name':'Bad CSRF'},code=403)
    post('/finance/parties',{'csrf':'رمز'},code=403)
    post('/finance/parties',form(name='x'*25000),code=413)
    assert request('admin','POST','/finance/parties',content='csrf=a&csrf=b',headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code==400

    owner=make_party('Fixture Owner <script>alert(1)</script>','owner','owner-001')
    party=make_party('=Fixture debtor','counterparty','counterparty-001')
    other=make_party('Another creditor','counterparty','counterparty-002')
    post('/finance/parties',form(name='Same reference',kind='owner',identity_ref='owner-001',confirmed='1'),code=409)
    sequence=0
    def draft(kind='claim',amount='100.00',currency='SAR',**extra):
        nonlocal sequence
        sequence+=1
        fields=dict(owner_id=owner,counterparty_id=party,kind=kind,currency=currency,amount=amount,document_date='2026-01-01',
            source_ref='synthetic.xlsx',source_locator='Sheet!A'+str(sequence),economic_ref='event-'+str(sequence),source_role='detail',amount_basis='gross',
            source_status_raw='source-only',notes='<img src=x onerror=alert(1)>')
        fields.update(extra)
        data=form('finance',**fields)
        res=post('/finance/documents',data,'finance')
        doc_id=int(res.headers['location'].rsplit('/',1)[1])
        return doc_id,data
    def review(doc_id,**extra):
        return post(f'/finance/documents/{doc_id}/review',form('finance',confirmation='1',**extra),'finance')
    def post_doc(doc_id):
        return post(f'/finance/documents/{doc_id}/post',form(confirmation='1'))
    def posted(kind='claim',amount='100.00',currency='SAR',**extra):
        doc_id,_=draft(kind,amount,currency,**extra);review(doc_id);post_doc(doc_id);return doc_id

    def read_totals():
        # Every totals read must leave source evidence, journal, allocations and
        # audit untouched; totals must reconcile to all per-party balances.
        tables=('finance_parties','finance_documents','finance_entries','finance_allocations','finance_audit','finance_entitlement_rules')
        before={table:rows('SELECT * FROM '+table+' ORDER BY id') for table in tables}
        dashboard=service.dashboard_data()
        assert len(dashboard)==6
        totals=dashboard[5]
        indexed={(item['owner_id'],item['currency']):item for item in totals}
        assert len(indexed)==len(totals),'duplicate owner/currency total'
        grouped={}
        for balance in dashboard[2]:
            key=(balance['owner_id'],balance['currency'])
            expected=grouped.setdefault(key,[0,0])
            expected[0]+=int(balance['receivable_minor'])
            expected[1]+=int(balance['payable_minor'])
        assert set(indexed)==set(grouped)
        debt_counts={(item['owner_id'],item['currency']):item['n'] for item in rows('''
            SELECT owner_id,currency,COUNT(DISTINCT id) n FROM finance_documents
            WHERE status='posted' AND kind IN ('payable','expense') GROUP BY owner_id,currency''')}
        owner_names={item['id']:item['name'] for item in dashboard[0] if item['kind']=='owner'}
        response=request('finance','GET','/api/v7/finance')
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        payload=response.json()
        api_totals={(item['owner_id'],item['currency']):item for item in payload['totals']}
        assert len(api_totals)==len(payload['totals']) and set(api_totals)==set(indexed)
        assert payload['scope']=='operational_subledger' and payload['external_actions'] is False
        for key,item in indexed.items():
            receivable,payable=grouped[key]
            assert item['owner_name']==owner_names[key[0]]
            assert item['payable_document_count']==debt_counts.get(key,0)
            assert type(item['payable_document_count']) is int
            assert api_totals[key]['payable_document_count']==item['payable_document_count']
            assert api_totals[key]['owner_name']==item['owner_name']
            for field,value in (('receivable',receivable),('payable',payable),('net',receivable-payable)):
                assert type(item[field+'_minor']) is int and item[field+'_minor']==value,(key,field,item)
                assert item[field+'_display']==core.display_minor(value,key[1])
                assert type(api_totals[key][field+'_minor']) is str
                assert api_totals[key][field+'_minor']==str(value)
                assert api_totals[key][field+'_display']==item[field+'_display']
        page=request('finance','GET','/finance')
        assert page.status_code==200 and page.headers['cache-control']=='no-store'
        if indexed:
            for label in ('إجمالي الأرصدة المستحقة','إجمالي الديون المسجلة','صافي الرصيد المسجل'):
                assert label in page.text
        for table,snapshot in before.items():
            assert rows('SELECT * FROM '+table+' ORDER BY id')==snapshot,(table,'totals read changed ledger')
        return indexed

    assert read_totals()=={}
    unknown,unknown_data=draft(currency='',document_date='',source_date_raw='2026-01-??')
    d=one('SELECT * FROM finance_documents WHERE id=%s',(unknown,))
    assert d['document_date'] is None and d['currency']=='' and d['amount_minor'] is None and d['source_date_raw']=='2026-01-??'
    post(f'/finance/documents/{unknown}/review',form('finance',confirmation='1'),'finance',400)
    post(f'/finance/documents/{unknown}/post',form(confirmation='1'),code=409)
    summary,_=draft(source_role='summary')
    post(f'/finance/documents/{summary}/review',form('finance',confirmation='1'),'finance',400)
    cached,_=draft(source_cached_external='1',source_status_raw='Matched')
    post(f'/finance/documents/{cached}/review',form('finance',confirmation='1'),'finance',400)
    assert one('SELECT source_verification FROM finance_documents WHERE id=%s',(cached,))['source_verification']=='recorded'
    missing_evidence,_=draft(source_cached_external='1',source_verification='independently_verified')
    post(f'/finance/documents/{missing_evidence}/review',form('finance',confirmation='1'),'finance',400)
    with_evidence,_=draft(source_cached_external='1',source_verification='independently_verified',verification_ref='Synthetic independent receipt')
    review(with_evidence)
    tiny,_=draft(amount='0.004')
    post(f'/finance/documents/{tiny}/review',form('finance',confirmation='1'),'finance',400)
    rounded,data=draft(amount='100.00567891')
    assert post('/finance/documents',data,'finance').headers['location'].endswith('/'+str(rounded))
    bad=dict(data,amount='100.01');post('/finance/documents',bad,'finance',409)
    bad=dict(data,idempotency_key=str(uuid.uuid4()));post('/finance/documents',bad,'finance',409)
    post(f'/finance/documents/{rounded}/review',form('finance',confirmation='1'),'finance',400)
    review(rounded,rounding_ack='1')
    post(f'/finance/documents/{rounded}/post',form('finance',confirmation='1'),'finance',403)
    post(f'/finance/documents/{rounded}/post',form(),code=400)
    assert read_totals()=={},'draft and reviewed documents must not become recorded totals'
    post_doc(rounded);post_doc(rounded)
    d=one('SELECT * FROM finance_documents WHERE id=%s',(rounded,))
    assert str(d['source_amount'])=='100.00567891' and d['amount_minor']==10001 and d['rounding_ack']
    assert one('SELECT COUNT(*) n FROM finance_entries WHERE document_id=%s',(rounded,))['n']==1
    duplicate,_=draft(economic_ref=d['economic_ref'])
    review(duplicate);post(f'/finance/documents/{duplicate}/post',form(confirmation='1'),code=409)
    page=request('admin','GET',f'/finance/documents/{rounded}').text
    assert '<img src=x' not in page and '&lt;img' in page and '100.00567891' in page
    page=request('admin','GET','/finance').text
    assert '<script>alert(1)' not in page and '&lt;script&gt;' in page
    claim=posted(amount='100.00',invoice_ref='invoice-synthetic')
    credit=posted('receipt','80.00')
    payable=posted('payable','70.00')
    payment=posted('payment','20.00')
    adjustment=posted('receivable_adjustment','10.00')
    usd=posted(amount='10.00',currency='USD')
    foreign_party=posted(amount='10.00',counterparty_id=other)
    noncash=posted('payable_adjustment','5.00')
    expenses=posted('expense','7.00')
    duplicate_expense,_=draft('expense',economic_ref=one('SELECT economic_ref FROM finance_documents WHERE id=%s',(payable,))['economic_ref'])
    review(duplicate_expense);post(f'/finance/documents/{duplicate_expense}/post',form(confirmation='1'),code=409)
    draft('payable','999.00')
    reviewed_expense,_=draft('expense','888.00');review(reviewed_expense)
    initial_totals=read_totals()
    assert set(initial_totals)=={(owner,'SAR'),(owner,'USD')}
    sar=initial_totals[(owner,'SAR')]
    assert (sar['receivable_minor'],sar['payable_minor'],sar['net_minor'],sar['payable_document_count'])==(12001,5200,6801,2)
    assert (sar['receivable_display'],sar['payable_display'],sar['net_display'])==('120.01','52.00','68.01')
    assert initial_totals[(owner,'USD')]['receivable_minor']==1000
    assert initial_totals[(owner,'USD')]['payable_minor']==0
    assert initial_totals[(owner,'USD')]['net_minor']==1000
    assert initial_totals[(owner,'USD')]['payable_document_count']==0
    query=f'owner_id={owner}&counterparty_id={party}&currency=SAR'
    ownerrow,partyrow,entries,balance=service.statement_data(owner,party,'SAR','receivable')
    assert balance=='110.01',balance
    payable_statement=service.statement_data(owner,party,'SAR','payable')
    assert payable_statement[3]=='52.00'
    assert payable_statement[2][0]['credit_display']=='70.00' and payable_statement[2][0]['debit_display']=='0.00'
    assert payable_statement[2][1]['debit_display']=='20.00'
    assert service.statement_data(owner,party,'USD','receivable')[3]=='10.00'
    for side in ('receivable','payable'):
        assert request('finance','GET','/finance/statement?'+query+'&side='+side).status_code==200
    exported=request('admin','GET','/finance/statement.csv?'+query).content.decode('utf-8-sig')
    exported_rows=list(csv.DictReader(io.StringIO(exported)))
    assert exported_rows[0]['counterparty']=="'=Fixture debtor" and all(r['currency']=='SAR' for r in exported_rows)
    assert exported_rows[-1]['balance']=='110.01'
    assert request('admin','GET','/finance/statement?'+query.replace('SAR','ZZZ')).status_code==400
    before_entries=rows('SELECT * FROM finance_entries ORDER BY id')
    allocation=form(credit_id=credit,document_id=claim,amount='30.00')
    post('/finance/allocations',allocation);post('/finance/allocations',allocation)
    assert one('SELECT COUNT(*) n FROM finance_allocations')['n']==1
    assert rows('SELECT * FROM finance_entries ORDER BY id')==before_entries
    assert read_totals()==initial_totals,'allocation is not another receipt or journal movement'
    post('/finance/allocations',dict(allocation,amount='31.00'),code=409)
    post('/finance/allocations',form(credit_id=credit,document_id=usd,amount='1.00'),code=400)
    post('/finance/allocations',form(credit_id=credit,document_id=foreign_party,amount='1.00'),code=400)
    post('/finance/allocations',form(credit_id=credit,document_id=payable,amount='1.00'),code=400)
    post('/finance/allocations',form(credit_id=credit,document_id=claim,amount='0.001'),code=400)
    post('/finance/allocations',form('finance',credit_id=credit,document_id=claim,amount='1.00'),'finance',403)
    def concurrent_allocate(_):
        isolated=TestClient(app,base_url='http://testserver',follow_redirects=False)
        try:
            isolated.cookies.set('gla_session',sessions['admin']['id'])
            return isolated.post('/finance/allocations',data=form(credit_id=credit,document_id=claim,amount='40.00'),headers={'Origin':'http://testserver'}).status_code
        finally:isolated.close()
    with ThreadPoolExecutor(max_workers=3) as pool:statuses=list(pool.map(concurrent_allocate,range(3)))
    assert sorted(statuses)==[303,409,409],statuses
    assert one('SELECT SUM(amount_minor) n FROM finance_allocations WHERE credit_id=%s AND reversed_at IS NULL',(credit,))['n']==7000
    assert read_totals()==initial_totals,'multiple allocations must not be deducted from totals'
    reason='Fixture error; source preserved'
    post(f'/finance/documents/{credit}/reverse',form(reason=reason),code=400)
    post(f'/finance/documents/{credit}/reverse',form(reason=reason,confirmation='1'))
    post(f'/finance/documents/{credit}/reverse',form(reason=reason,confirmation='1'))
    assert one('SELECT COUNT(*) n FROM finance_entries WHERE document_id=%s',(credit,))['n']==2
    assert one('SELECT COUNT(*) n FROM finance_allocations WHERE reversed_at IS NULL')['n']==0
    assert service.detail_data(credit)[0]['remaining_display']=='0.00'
    assert service.detail_data(claim)[0]['remaining_display']=='100.00'
    assert service.statement_data(owner,party,'SAR','receivable')[3]=='190.01'
    assert sum(e['phase']=='reversal' for e in service.statement_data(owner,party,'SAR','receivable')[2])==1
    reversed_totals=read_totals()
    assert reversed_totals[(owner,'SAR')]['receivable_minor']==20001
    assert reversed_totals[(owner,'SAR')]['payable_minor']==5200
    assert reversed_totals[(owner,'SAR')]['net_minor']==14801
    assert reversed_totals[(owner,'SAR')]['payable_document_count']==2
    post('/finance/allocations',form(credit_id=credit,document_id=claim,amount='1.00'),code=409)
    post(f'/finance/documents/{unknown}/void',form(reason='Incomplete source replaced'))
    assert one('SELECT status FROM finance_documents WHERE id=%s',(unknown,))['status']=='void'
    assert service.statement_data(owner,party,'SAR','receivable')[3]=='190.01'
    # Correct a voided source without changing its original evidence or inventing a locator.
    replacement=dict(unknown_data,idempotency_key=str(uuid.uuid4()),currency='SAR',document_date='2026-01-01')
    result=post('/finance/documents',replacement,'finance')
    replacement_id=int(result.headers['location'].rsplit('/',1)[1])
    replaced=one('SELECT * FROM finance_documents WHERE id=%s',(replacement_id,))
    assert replaced['supersedes_id']==unknown and replaced['source_locator']==unknown_data['source_locator']
    assert one('SELECT currency FROM finance_documents WHERE id=%s',(unknown,))['currency']==''
    review(replacement_id,reason='Document source independently checked')
    assert 'Document source independently checked' in one("SELECT detail FROM finance_audit WHERE entity_id=%s AND action='document_reviewed'",(replacement_id,))['detail']
    # Evidence, entries and audit are immutable even if a programming error tries SQL writes.
    for sql in ("UPDATE finance_documents SET source_amount=5 WHERE id="+str(claim),
                'DELETE FROM finance_documents WHERE id='+str(claim),
                'DELETE FROM finance_entries WHERE document_id='+str(claim),
                "UPDATE finance_audit SET detail='changed'",'DELETE FROM finance_parties WHERE id='+str(owner)):
        try:
            with db() as c:c.execute(sql)
            raise AssertionError('Immutable table accepted mutation')
        except RaiseException:pass
    rule=form(owner_id=owner,company_scope='Explicit future fixture scope',rate='30',basis='Unconfirmed source basis; no calculation')
    post('/finance/rules',rule);post('/finance/rules',rule)
    assert one('SELECT COUNT(*) n FROM finance_entitlement_rules')['n']==1
    assert one('SELECT status FROM finance_entitlement_rules')['status']=='inactive'
    assert len(rows('SELECT * FROM finance_entries'))==len(before_entries)+1
    # Counts refer to distinct active debt documents, never payments, adjustments
    # or reversed posting/reversal rows. Negative debts are not clamped to zero.
    for doc_id in (payable,expenses):
        post(f'/finance/documents/{doc_id}/reverse',form(reason=reason,confirmation='1'))
    no_debts=read_totals()[(owner,'SAR')]
    assert (no_debts['receivable_minor'],no_debts['payable_minor'],no_debts['net_minor'],no_debts['payable_document_count'])==(20001,-2500,22501,0)
    assert no_debts['payable_display']=='-25.00'
    for doc_id in (payment,noncash):
        post(f'/finance/documents/{doc_id}/reverse',form(reason=reason,confirmation='1'))
    assert read_totals()[(owner,'SAR')]['payable_display']=='0.00'
    # Equal display names must not merge owners; equal currencies must not merge
    # ledgers. Payment-only and over-received pairs retain their negative sides.
    owner2=make_party('Fixture Owner <script>alert(1)</script>','owner','owner-002')
    posted('receipt','3.00',owner_id=owner2)
    posted('payment','4.00',owner_id=owner2)
    posted('claim','2.00',currency='USD',owner_id=owner2)
    posted('claim','0.125',currency='KWD',owner_id=owner2)
    posted('receipt','0.125',currency='KWD',owner_id=owner2)
    posted('payable','12',currency='JPY',owner_id=owner2)
    posted('payment','12',currency='JPY',owner_id=owner2)
    separated=read_totals()
    assert set(separated)=={(owner,'SAR'),(owner,'USD'),(owner2,'SAR'),(owner2,'USD'),(owner2,'KWD'),(owner2,'JPY')}
    assert (separated[(owner2,'SAR')]['receivable_minor'],separated[(owner2,'SAR')]['payable_minor'],separated[(owner2,'SAR')]['net_minor'])==(-300,-400,100)
    assert separated[(owner2,'SAR')]['payable_document_count']==0
    assert separated[(owner2,'USD')]['net_display']=='2.00' and separated[(owner,'USD')]['net_display']=='10.00'
    assert all(separated[(owner2,'KWD')][side+'_display']=='0.000' for side in ('receivable','payable','net'))
    assert all(separated[(owner2,'JPY')][side+'_display']=='0' for side in ('receivable','payable','net'))
    assert separated[(owner2,'JPY')]['payable_document_count']==1,'settled posted payable is still a registered debt document'
    # The latest-document preview is capped at 200. Older journal balances must
    # remain in totals even when every displayed document is an unposted draft.
    for _ in range(201):draft(amount='1.00')
    preview=service.dashboard_data()[1]
    assert len(preview)==200 and all(item['status']=='draft' for item in preview)
    assert read_totals()==separated,'totals must use the journal, not the latest 200 documents'
    # Correct only the display name of the existing owner. All original rows,
    # monetary values, source evidence, links and prior audit events survive.
    rename_path=f'/finance/owners/{owner}/display-name'
    preserved_tables=('finance_parties','finance_documents','finance_entries','finance_allocations','finance_entitlement_rules')
    preserved={t:rows('SELECT * FROM '+t+' ORDER BY id') for t in preserved_tables}
    old_audit=rows('SELECT * FROM finance_audit ORDER BY id')
    old_totals=read_totals()
    original_name=one('SELECT name FROM finance_parties WHERE id=%s',(owner,))['name']
    new_name='وكيل حساب اختباري <script>not executable</script>'
    rename=form(name=new_name,expected_revision='0',reason='Synthetic approval: sector display name only',confirmation='1')
    for role in ('finance','sales','viewer','transport','customs'):
        post(rename_path,dict(rename,csrf=sessions[role]['csrf']),role,403)
    assert request(None,'POST',rename_path,data=rename).status_code in (401,303)
    post(rename_path,dict(rename,csrf='wrong'),code=403)
    for extra in ({'name':''},{'name':'x'*201},{'name':'bad\x00name'},{'reason':''},{'reason':'x'*1001},
                  {'confirmation':''},{'expected_revision':'-1'},{'expected_revision':'abc'},
                  {'expected_revision':'١'},{'kind':'counterparty'},{'owner_id':owner2},
                  {'identity_ref':'rewritten'},{'confirmed':'0'},{'amount':'1'},{'idempotency_key':'invalid'}):
        post(rename_path,dict(rename,**extra),code=400)
    post(rename_path,dict(rename,expected_revision='1'),code=409)
    post(rename_path,dict(rename,name=original_name),code=400)
    post(f'/finance/owners/{party}/display-name',rename,code=400)
    post('/finance/owners/999999999/display-name',rename,code=400)
    assert rows('SELECT * FROM finance_owner_name_changes')==[]
    post(rename_path,rename);post(rename_path,rename)
    changes=rows('SELECT * FROM finance_owner_name_changes')
    assert len(changes)==1 and changes[0]['owner_id']==owner
    assert changes[0]['previous_name']==original_name and changes[0]['name']==new_name
    assert changes[0]['created_by']==sessions['admin']['user_id'] and changes[0]['reason']==rename['reason']
    new_audit=rows('SELECT * FROM finance_audit ORDER BY id')
    assert new_audit[:-1]==old_audit and len(new_audit)==len(old_audit)+1
    event=new_audit[-1]
    assert (event['action'],event['entity_type'],event['entity_id'])==('owner_display_name_changed','party',owner)
    assert json.loads(event['detail'])==dict(previous_name=original_name,name=new_name,reason=rename['reason'],previous_revision=0)
    resolved=one('SELECT * FROM finance_party_display WHERE id=%s',(owner,))
    assert resolved['name']==new_name and resolved['name_revision']==changes[0]['id']
    post(rename_path,dict(rename,name='Different payload'),code=409)
    post(rename_path,dict(rename,idempotency_key=str(uuid.uuid4()),name='Stale form'),code=409)
    for t,data in preserved.items():assert rows('SELECT * FROM '+t+' ORDER BY id')==data,t
    new_totals=read_totals()
    assert set(new_totals)==set(old_totals)
    for key,old in old_totals.items():
        assert new_totals[key]==dict(old,owner_name=new_name) if key[0]==owner else new_totals[key]==old
    api_data=request('admin','GET','/api/v7/finance').json()
    assert next(p for p in api_data['parties'] if p['id']==owner)['name']==new_name
    assert all(d['owner_name']==new_name for d in api_data['documents'] if d['owner_id']==owner)
    assert service.detail_data(claim)[0]['owner_name']==new_name
    statement_path=f'/finance/statement?owner_id={owner}&counterparty_id={party}&currency=SAR'
    for path in ('/finance',f'/finance/documents/{claim}',statement_path):
        output=request('admin','GET',path).text
        assert 'وكيل حساب اختباري &lt;script&gt;not executable&lt;/script&gt;' in output
        assert new_name not in output,'name must be HTML escaped'
    csv_rows=list(csv.reader(io.StringIO(request('admin','GET',statement_path.replace('/statement?','/statement.csv?')).content.decode('utf-8-sig'))))
    assert len(csv_rows)>1 and all(row[0]==new_name for row in csv_rows[1:])
    for sql in ("UPDATE finance_owner_name_changes SET name='overwrite'",
                'DELETE FROM finance_owner_name_changes',"UPDATE finance_parties SET name='overwrite' WHERE id="+str(owner)):
        try:
            with db() as c:c.execute(sql)
            raise AssertionError('Immutable financial name history accepted mutation')
        except RaiseException:pass
    # A second correction uses the latest revision; an old replay cannot undo it.
    next_rename=form(name='Synthetic sector display',expected_revision=str(changes[0]['id']),reason='Synthetic second correction',confirmation='1')
    post(rename_path,next_rename);post(rename_path,rename)
    assert one('SELECT name FROM finance_party_display WHERE id=%s',(owner,))['name']==next_rename['name']
    assert one('SELECT COUNT(*) n FROM finance_owner_name_changes')['n']==2
    # Explicit denied admin approval applies to the new endpoint as well.
    with db() as c:
        c.execute('INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES(%s,%s,0,%s)',('admin','approve_finance',utcnow()))
    post(rename_path,next_rename,code=403)
    assert '/display-name' not in request('admin','GET','/finance').text
    with db() as c:c.execute("DELETE FROM role_permissions WHERE role='admin' AND permission='approve_finance'")
    # Re-runnable additive migration and exact preservation of operational tables.
    snapshot=rows('SELECT * FROM finance_documents ORDER BY id')
    finance_schema.init_storage();finance_schema.init_storage()
    assert rows('SELECT * FROM finance_documents ORDER BY id')==snapshot
    assert one('SELECT name FROM finance_party_display WHERE id=%s',(owner,))['name']==next_rename['name']
    assert rows('SELECT * FROM finance_parties ORDER BY id')==preserved['finance_parties']
    for table,data in original.items():assert rows('SELECT * FROM '+table+' ORDER BY id')==data,table
    # Explicit deny overrides role; a grant never expands unsupported roles.
    with db() as c:
        c.execute('INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES(%s,%s,0,%s)',('finance','view_finance',utcnow()))
    assert request('finance','GET','/finance').status_code==403
    with db() as c:
        c.execute('INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES(%s,%s,1,%s)',('sales','view_finance',utcnow()))
    assert request('sales','GET','/finance').status_code==403
    with db() as c:c.execute('UPDATE users SET is_active=0 WHERE id=%s',(sessions['admin']['user_id'],))
    assert request('admin','GET','/finance').status_code in (303,403)
    client.close()
    print('PASS: roles/CSRF/permission overrides, source precision, unknown blocking, duplicates, per-currency/side statements, owner/currency totals and exact API strings, debt counts, allocations/reversals/negative/zero balances, 200-document cap independence, immutable read-only totals, XSS/CSV, inactive rules, additive migrations, no original overwrite; external sends 0.')


def main():
    import psycopg
    from psycopg import sql
    url=os.environ.get('AFAAQ_TEST_DATABASE_URL','');target=urlsplit(url)
    if target.scheme not in ('postgres','postgresql') or target.hostname not in ('localhost','127.0.0.1') or target.path!='/afaaq_test' or target.query or target.fragment:
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema='finance_test_'+secrets.token_hex(6)
    with psycopg.connect(url,autocommit=True) as c:c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect=socket.socket.connect
    def local_only(sock,address):
        if isinstance(address,tuple) and address[0] not in ('localhost','127.0.0.1','::1'):raise AssertionError('External network blocked in finance acceptance')
        return connect(sock,address)
    try:
        env={'DATABASE_URL':url+'?'+urlencode({'options':'-c search_path='+schema+' -c statement_timeout=30000 -c lock_timeout=15000'},quote_via=quote),
             'DISCOVERY_AUTO_ENABLED':'0','ENABLE_EXTERNAL_ACTIONS':'0','ADMIN_EMAIL':'bootstrap@fixture.invalid','ADMIN_PASSWORD':secrets.token_urlsafe(32),'BROWSER_COOKIE_SECURE':'0'}
        with patch.dict(os.environ,env),patch.object(socket.socket,'connect',local_only):run()
    finally:
        with psycopg.connect(url,autocommit=True) as c:c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: finance PostgreSQL acceptance.')


if __name__=='__main__':main()
