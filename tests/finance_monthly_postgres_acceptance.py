"""Isolated monthly reports acceptance. Synthetic data; external egress blocked."""
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
    from app import finance_service as ledger, finance_closing_service as closing, finance_monthly_service as monthly, finance_schema
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
        return client.request(method,path,headers={'Origin':'http://testserver',**kwargs.pop('headers',{})},**kwargs)
    def form(**extra):return dict(csrf=sessions['admin']['csrf'],idempotency_key=str(uuid.uuid4()),**extra)
    def post(path,data,role='admin',code=303):
        res=request(role,'POST',path,data=data)
        assert res.status_code==code,(path,res.status_code,res.text[:2000])
        return res
    actor=sessions['admin']['user_id']
    owner=ledger.create_party(dict(name='وكيل تجريبي',kind='owner',identity_ref='OWNER-PRIVATE',confirmed='1'),actor)
    party=ledger.create_party(dict(name='عميل تجريبي',kind='counterparty',identity_ref='CUSTOMER-PRIVATE',confirmed='1'),actor)
    sequence=0
    def doc(kind,amount,day='2026-10-03',currency='SAR',posted=True):
        nonlocal sequence
        sequence+=1
        payload=form(owner_id=owner,counterparty_id=party,kind=kind,currency=currency,amount=amount,document_date=day,
            source_ref='CONFIDENTIAL-SOURCE',source_locator='CONFIDENTIAL-LOCATOR-'+str(sequence),economic_ref='CONFIDENTIAL-EVENT-'+str(sequence),
            source_role='detail',amount_basis='gross',notes='CONFIDENTIAL-COST-PROFIT',invoice_ref='DEMO-'+str(sequence),customs_ref='DEMO-CUSTOMS-'+str(sequence))
        if kind=='opening_receivable':payload.update(source_role='summary',amount_basis='net',opening_cutoff=day,opening_confirmation_ref='CONFIDENTIAL-OPENING',invoice_ref='',customs_ref='')
        id=ledger.create_document(payload,actor)
        if posted:
            ledger.review_document(id,actor,form(confirmation='1',opening_ack='1'))
            ledger.post_document(id,actor,form(confirmation='1',opening_ack='1',reason='DEMO-OPENING-APPROVAL'))
        return id
    opening=doc('opening_receivable','1000','2026-09-29')
    claim=doc('claim','920')
    receipt=doc('receipt','100','2026-10-04')
    expense=doc('expense','200','2026-10-05')
    ledger.create_allocation(form(credit_id=receipt,document_id=claim,amount='100'),actor)
    ledger.attach_claim_details(claim,actor,form(expected_revision='0',confirmation='1',goods_amount='1000',goods_currency='AED',exchange_rate='1.02',
        customs_duty='0',customs_other='0',clearance='0',saber='0',zakat='0',registry='800',tax='120',source_ref='CONFIDENTIAL-DETAIL',reason='CONFIDENTIAL-REASON'))
    stmt_path=f'/finance/monthly-statement?owner_id={owner}&counterparty_id={party}&currency=SAR&start=2026-10-01&end=2026-10-31'
    close_path=f'/finance/monthly-closing?owner_id={owner}&month=2026-10'
    for path in (stmt_path,stmt_path.replace('statement?','statement.pdf?'),close_path,close_path.replace('closing?','closing.pdf?')):
        assert request(None,'GET',path).status_code in (401,303)
        for role in ('sales','viewer','transport','customs'):assert request(role,'GET',path).status_code==403
        for role in ('admin','finance'):
            res=request(role,'GET',path);assert res.status_code==200,(path,res.text[:500])
            assert res.headers['cache-control']=='no-store'
            assert res.headers['x-robots-tag']=='noindex, nofollow'
    res=request('finance','GET',stmt_path)
    assert 'CONFIDENTIAL' not in res.text and '800.00' in res.text and '120.00' in res.text
    stmt=monthly.statement_data(owner,party,'SAR','2026-10-01','2026-10-31')
    assert stmt['opening_minor']==100000 and stmt['claims_minor']==92000 and stmt['receipts_minor']==10000 and stmt['closing_minor']==182000
    assert monthly.statement_data(owner,party,'SAR','2026-11-01','2026-11-30')['opening_minor']==182000
    assert monthly.statement_data(owner,party,'USD','2026-10-01','2026-10-31')['closing_minor']==0
    assert request('admin','GET',stmt_path.replace('2026-10-31','2025-01-01')).status_code==400
    protected=('finance_documents','finance_entries','finance_allocations','finance_parties','shipments','accounts','outbound_messages')
    preserved={t:rows('SELECT * FROM '+t+' ORDER BY id') for t in protected}
    data=closing.report_data(owner,'2026-10')
    assert not data['ready_for_distribution'] and data['currencies'][0]['profit_minor'] is None
    def mapping(**extra):
        p=form(expected_revision='0',expected_detail_revision='0',confirmation='1',basis_status='confirmed',basis_ref='DEMO-BASIS',allocation_ref='DEMO-ALLOCATION',costs_complete='1',reason='DEMO-EVIDENCE')
        p.update({k:'0' for k in closing.AMOUNTS});p.update(extra);return p
    claim_map=mapping(expected_detail_revision=str(one('SELECT id FROM finance_claim_details')['id']),shared_service_income_minor='800',tax_reserve_minor='120',goods_value_minor='1020')
    expense_map=mapping(shared_actual_cost_minor='200',related_document_id=str(claim))
    path=f'/finance/documents/{claim}/closing-input'
    post(path,dict(claim_map,csrf='wrong'),code=403)
    post(path,dict(claim_map,csrf=sessions['finance']['csrf']),'finance',403)
    post(path,dict(claim_map,confirmation='0'),code=400)
    post(path,dict(claim_map,owner_id='99'),code=400)
    post(path,dict(claim_map,shared_service_income_minor='1e3'),code=400)
    assert request('admin','POST',path,content='csrf=x&csrf=y',headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code==400
    def repeat():return closing.save_input(claim,actor,claim_map)
    with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(lambda _:repeat(),range(2)))
    assert ids[0]==ids[1]
    assert one('SELECT COUNT(*) n FROM finance_closing_inputs')['n']==1
    post(path,claim_map)
    post(path,dict(claim_map,reason='changed same key'),code=409)
    post(path,dict(claim_map,idempotency_key=str(uuid.uuid4())),code=409)
    post(f'/finance/documents/{expense}/closing-input',expense_map)
    data=closing.report_data(owner,'2026-10')
    assert not data['ready_for_distribution']
    def review(r):return form(expected_revision=str(r['review_revision']),snapshot_hash=r['snapshot_hash'],income_complete='1',expenses_complete='1',mapping_complete='1',confirmation_ref='DEMO-MONTH-COMPLETE',confirmation='1')
    review_path=f'/finance/monthly-closing/{owner}/2026-10/review'
    month_review=review(data);post(review_path,month_review);post(review_path,month_review)
    data=closing.report_data(owner,'2026-10');assert data['status']=='draft' and data['ready_for_distribution']
    bucket=data['currencies'][0]
    assert bucket['profit_minor']==60000 and bucket['agency_share_minor']==30000 and bucket['partner_share_minor']==30000
    assert one('SELECT COUNT(*) n FROM finance_closing_reviews')['n']==1
    for table,before in preserved.items():assert rows('SELECT * FROM '+table+' ORDER BY id')==before,table
    with db() as c:c.execute('INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES(%s,%s,0,%s)',('finance','view_profit',utcnow()))
    assert request('finance','GET',close_path).status_code==403
    assert request('finance','GET',close_path.replace('closing?','closing.pdf?')).status_code==403
    assert 'closing_input_saved' not in request('finance','GET','/finance').text
    assert 'DEMO-ALLOCATION' not in request('finance','GET',f'/finance/documents/{claim}').text
    assert '/finance/monthly-closing' not in request('finance','GET','/finance').text
    # Owner-approved fixed Saber cost affects only reporting and the agency pool.
    fixed_claim=doc('claim','1000')
    fixed_map=mapping(saber_revenue_minor='1000',saber_fixed_cost_minor='250',saber_fixed_cost_approved='1',saber_fixed_cost_ref='DEMO-OWNER-FIXED-COST')
    ledger_before=rows('SELECT * FROM finance_entries ORDER BY id')
    post(f'/finance/documents/{fixed_claim}/closing-input',fixed_map)
    assert rows('SELECT * FROM finance_entries ORDER BY id')==ledger_before
    data=closing.report_data(owner,'2026-10');post(review_path,review(data))
    data=closing.report_data(owner,'2026-10');bucket=data['currencies'][0]
    assert data['ready_for_distribution'] and bucket['saber_fixed_cost_minor']==25000
    assert bucket['profit_minor']==135000 and bucket['agency_share_minor']==105000 and bucket['partner_share_minor']==30000
    # A later agency expense linked to that claim cannot duplicate the fixed cost.
    later_cost=doc('expense','250',day='2026-11-01')
    post(f'/finance/documents/{later_cost}/closing-input',mapping(agency_only_actual_cost_minor='250',related_document_id=str(fixed_claim)))
    assert any('سبق اعتماد تكلفة سابر ثابتة' in b for b in closing.report_data(owner,'2026-11')['blockers'])
    revised=dict(claim_map,idempotency_key=str(uuid.uuid4()),expected_revision=str(ids[0]),costs_complete='0')
    post(path,revised)
    data=closing.report_data(owner,'2026-10');assert not data['ready_for_distribution'] and not data['review_current']
    assert data['currencies'][0]['profit_minor'] is None
    post(review_path,dict(month_review,idempotency_key=str(uuid.uuid4())),code=409)
    # Old input replay cannot overwrite the new pending-cost revision.
    post(path,claim_map);assert not closing.report_data(owner,'2026-10')['ready_for_distribution']
    for table in ('finance_closing_inputs','finance_closing_reviews'):
        before=rows('SELECT * FROM '+table+' ORDER BY id')
        for sql in ('UPDATE '+table+' SET created_at=NOW()','DELETE FROM '+table):
            try:
                with db() as c:c.execute(sql)
                raise AssertionError('Immutable report audit was changed')
            except RaiseException:pass
        finance_schema.init_storage();finance_schema.init_storage()
        assert rows('SELECT * FROM '+table+' ORDER BY id')==before
    # New authoritative claim detail invalidates both mapping and completeness.
    detail_id=one('SELECT id FROM finance_claim_details ORDER BY id DESC LIMIT 1')['id']
    ledger.attach_claim_details(claim,actor,form(expected_revision=str(detail_id),confirmation='1',goods_amount='1000',goods_currency='AED',exchange_rate='1.02',
        customs_duty='0',customs_other='0',clearance='0',saber='0',zakat='0',registry='820',tax='100',source_ref='CONFIDENTIAL-NEW-DETAIL',reason='DEMO-CHANGE'))
    data=closing.report_data(owner,'2026-10')
    assert any('تغير تفصيل المطالبة' in b for b in data['blockers'])
    post(path,dict(revised,idempotency_key=str(uuid.uuid4())),code=409)
    latest=one('SELECT id FROM finance_closing_inputs WHERE document_id=%s ORDER BY id DESC LIMIT 1',(claim,))['id']
    newdetail=one('SELECT id FROM finance_claim_details ORDER BY id DESC LIMIT 1')['id']
    # A complete gross total cannot hide known tax within shared service income.
    bad_map=dict(revised,idempotency_key=str(uuid.uuid4()),expected_revision=str(latest),expected_detail_revision=str(newdetail),shared_service_income_minor='920',tax_reserve_minor='0')
    post(path,bad_map,code=400)
    # Undated evidence also changes the snapshot and blocks completion.
    undated=doc('expense','3',day='',posted=False)
    assert any('دون تاريخ' in b for b in closing.report_data(owner,'2026-10')['blockers'])
    # Non-posted documents, unclassified payables and reversals block closure.
    pending=doc('claim','10',posted=False)
    assert any('غير مرحّل' in b for b in closing.report_data(owner,'2026-10')['blockers'])
    payable=doc('payable','5')
    assert any('تحديد أثرها' in b for b in closing.report_data(owner,'2026-10')['blockers'])
    ledger.reverse_document(claim,actor,form(confirmation='1',reason='DEMO-REVERSAL'))
    assert not closing.report_data(owner,'2026-10')['ready_for_distribution']
    post(path,revised,code=400)
    with db() as c:c.execute('INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES(%s,%s,0,%s)',('admin','view_profit',utcnow()))
    assert request('admin','GET',close_path).status_code==403
    post(review_path,month_review,code=403)
    with db() as c:c.execute("DELETE FROM role_permissions WHERE role='admin' AND permission='view_profit'")
    # Fine permission overrides and forced password change apply to every report.
    with db() as c:c.execute('INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES(%s,%s,0,%s)',('admin','approve_finance',utcnow()))
    post(review_path,month_review,code=403)
    assert '/review"' not in request('admin','GET',close_path).text
    with db() as c:c.execute('INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES(%s,%s,0,%s)',('finance','view_finance',utcnow()))
    assert request('finance','GET',stmt_path).status_code==403
    with db() as c:c.execute('UPDATE users SET must_change_password=1 WHERE id=%s',(actor,))
    assert request('admin','GET',close_path).status_code in (303,403)
    client.close()
    print('PASS: monthly date cutoffs, receipt allocations, currency isolation, safe HTML/PDF, draft profit mapping, missing costs, stale completeness, replay/concurrency, roles/CSRF/permission overrides, immutable audited inputs, unchanged ledger and operations, no external sends.')


def main():
    import psycopg
    from psycopg import sql
    url=os.environ.get('AFAAQ_TEST_DATABASE_URL','');target=urlsplit(url)
    if target.scheme not in ('postgres','postgresql') or target.hostname not in ('localhost','127.0.0.1') or target.path!='/afaaq_test' or target.query or target.fragment:
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema='monthly_test_'+secrets.token_hex(6)
    with psycopg.connect(url,autocommit=True) as c:c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect=socket.socket.connect
    def local_only(sock,address):
        if isinstance(address,tuple) and address[0] not in ('localhost','127.0.0.1','::1'):raise AssertionError('External network blocked')
        return connect(sock,address)
    try:
        env={'DATABASE_URL':url+'?'+urlencode({'options':'-c search_path='+schema+' -c statement_timeout=30000 -c lock_timeout=15000'},quote_via=quote),
             'DISCOVERY_AUTO_ENABLED':'0','ENABLE_EXTERNAL_ACTIONS':'0','ADMIN_EMAIL':'bootstrap@fixture.invalid','ADMIN_PASSWORD':secrets.token_urlsafe(32),'BROWSER_COOKIE_SECURE':'0'}
        with patch.dict(os.environ,env),patch.object(socket.socket,'connect',local_only):run()
    finally:
        with psycopg.connect(url,autocommit=True) as c:c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: monthly PostgreSQL acceptance.')

if __name__=='__main__':main()
