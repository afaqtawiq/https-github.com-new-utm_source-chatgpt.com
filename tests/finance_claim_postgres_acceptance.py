"""Disposable claim-itemization acceptance. Synthetic data; external egress blocked."""
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
    from app import finance_schema, finance_service as service
    from app.storage import db, one, rows, create_session, utcnow
    from psycopg.errors import RaiseException
    client=TestClient(app,base_url='http://testserver',follow_redirects=False)
    sessions={}
    with db() as c:
        for role in ('admin','finance','sales','viewer','transport','customs'):
            uid=c.execute('INSERT INTO users(email,name,password_hash,role,created_at) VALUES(%s,%s,%s,%s,%s) RETURNING id',
                (role+'@fixture.invalid',role,'not-a-password',role,utcnow())).fetchone()['id']
            sessions[role]={'user_id':uid}
    for role,s in sessions.items():
        sid,csrf,_=create_session(s['user_id']);s.update(id=sid,csrf=csrf)
    def request(role,method,path,**kwargs):
        client.cookies.clear()
        if role:client.cookies.set('gla_session',sessions[role]['id'])
        return client.request(method,path,headers={'Origin':'http://testserver',**kwargs.pop('headers',{})},**kwargs)
    def form(**extra):
        return {'csrf':sessions['admin']['csrf'],'idempotency_key':str(uuid.uuid4()),**extra}
    def post(path,data,role='admin',code=303):
        res=request(role,'POST',path,data=data)
        assert res.status_code==code,(path,res.status_code,res.text[:2000])
        return res
    owner=service.create_party(dict(name='وكيل تجريبي',kind='owner',identity_ref='fixture-owner',confirmed='1'),sessions['admin']['user_id'])
    party=service.create_party(dict(name='عميل اختباري',kind='counterparty',identity_ref='fixture-party',confirmed='1'),sessions['admin']['user_id'])
    fields=form(owner_id=owner,counterparty_id=party,kind='claim',currency='SAR',amount='123.45',document_date='2026-01-02',
        source_amount_raw='123.45',source_ref='Synthetic source',source_locator='Synthetic private file',economic_ref='Synthetic internal event',
        source_role='detail',amount_basis='gross',notes='CONFIDENTIAL_MARGIN_OTHER_CUSTOMER',invoice_ref='DEMO-42',customs_ref='DEMO-24')
    claim=int(post('/finance/documents',fields).headers['location'].split('/')[-1])
    path=f'/finance/documents/{claim}'
    detail_form=form(expected_revision='0',confirmation='1',goods_amount='100',goods_currency='USD',exchange_rate='3.75',
        customs_duty='10',customs_other='0.45',clearance='20',saber='30',zakat='3',registry='10',tax='50',
        source_ref='CONFIDENTIAL_SOURCE',reason='CONFIDENTIAL_REASON')
    for suffix in ('/claim','/claim.pdf'):
        assert request(None,'GET',path+suffix).status_code in (401,303)
        for role in ('sales','viewer','transport','customs'):
            assert request(role,'GET',path+suffix).status_code==403
        assert request('admin','GET',path+suffix).status_code==409
    post(path+'/claim-details',dict(detail_form,csrf='wrong'),code=403)
    post(path+'/claim-details',dict(detail_form,csrf=sessions['finance']['csrf']),'finance',403)
    post(path+'/claim-details',dict(detail_form,tax='51'),code=400)
    post(path+'/claim-details',dict(detail_form,confirmation='0'),code=400)
    post(path+'/claim-details',dict(detail_form,owner_id='999'),code=400)
    assert request('admin','POST',path+'/claim-details',content='csrf=a&csrf=b',headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code==400
    protected=('finance_documents','finance_entries','finance_parties','finance_allocations','shipments','accounts','outbound_messages')
    preserved={t:rows('SELECT * FROM '+t+' ORDER BY id') for t in protected}
    post(path+'/claim-details',detail_form)
    post(path+'/claim-details',detail_form)
    assert one('SELECT COUNT(*) n FROM finance_claim_details')['n']==1
    assert one("SELECT COUNT(*) n FROM finance_audit WHERE action='claim_details_attached'")['n']==1
    for t,data in preserved.items():assert rows('SELECT * FROM '+t+' ORDER BY id')==data,t
    assert request('admin','GET',path+'/claim.pdf').status_code==409
    post(path+'/review',form(confirmation='1'))
    post(path+'/post',form(confirmation='1'))
    preserved={t:rows('SELECT * FROM '+t+' ORDER BY id') for t in protected}
    old_totals=service.dashboard_data()[5]
    revision=one('SELECT * FROM finance_claim_details')['id']
    assert service.detail_data(claim)[0]['claim_details']['id']==revision
    d,detail=service.customer_claim_data(claim)
    assert set(d)=={'id','owner_name','counterparty_name','document_date','invoice_ref','customs_ref','currency'}
    assert 'source_ref' not in detail and 'reason' not in detail
    page=request('finance','GET',path+'/claim')
    assert page.status_code==200 and page.headers['cache-control']=='no-store'
    assert 'CONFIDENTIAL' not in page.text and 'Synthetic private file' not in page.text
    assert '123.45' in page.text and '375.00' in page.text and '10.45' in page.text
    pdf=request('finance','GET',path+'/claim.pdf')
    assert pdf.status_code==200 and pdf.headers['content-type']=='application/pdf'
    assert pdf.headers['content-disposition']==f'attachment; filename="claim-{claim}.pdf"'
    assert pdf.headers['cache-control']=='no-store' and pdf.content.startswith(b'%PDF-')
    assert len(pdf.content)>5000
    post(path+'/claim-details',dict(detail_form,idempotency_key=str(uuid.uuid4())),code=409)
    post(path+'/claim-details',dict(detail_form,reason='Different same key'),code=409)
    correction=dict(detail_form,idempotency_key=str(uuid.uuid4()),expected_revision=str(revision),customs_duty='9',customs_other='1.45',reason='Approved synthetic correction')
    # Concurrent identical requests collapse to one append and one audit.
    def repeat():return service.attach_claim_details(claim,sessions['admin']['user_id'],correction)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids=list(pool.map(lambda _:repeat(),range(2)))
    assert ids[0]==ids[1] and ids[0]!=revision
    post(path+'/claim-details',detail_form)  # old replay cannot override new revision
    assert one('SELECT COUNT(*) n FROM finance_claim_details')['n']==2
    assert one("SELECT COUNT(*) n FROM finance_audit WHERE action='claim_details_attached'")['n']==2
    assert service.detail_data(claim)[0]['claim_details']['id']==ids[0]
    assert service.dashboard_data()[5]==old_totals
    for t,data in preserved.items():assert rows('SELECT * FROM '+t+' ORDER BY id')==data,t
    for sql in ('UPDATE finance_claim_details SET claim_total_minor=1','DELETE FROM finance_claim_details'):
        try:
            with db() as c:c.execute(sql)
            raise AssertionError('Immutable detail accepted change')
        except RaiseException:pass
    before=rows('SELECT * FROM finance_claim_details ORDER BY id')
    finance_schema.init_storage();finance_schema.init_storage()
    assert rows('SELECT * FROM finance_claim_details ORDER BY id')==before
    for t,data in preserved.items():assert rows('SELECT * FROM '+t+' ORDER BY id')==data,t
    with db() as c:c.execute('INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES(%s,%s,0,%s)',('admin','approve_finance',utcnow()))
    post(path+'/claim-details',correction,code=403)
    assert 'حفظ التفصيل المعتمد' not in request('admin','GET',path).text
    with db() as c:c.execute("DELETE FROM role_permissions WHERE role='admin' AND permission='approve_finance'")
    post(path+'/reverse',form(confirmation='1',reason='Synthetic reversal test'))
    assert request('admin','GET',path+'/claim').status_code==409
    assert request('admin','GET',path+'/claim.pdf').status_code==409
    post(path+'/claim-details',correction,code=400)
    assert one('SELECT COUNT(*) n FROM finance_claim_details')['n']==2
    client.close()
    print('PASS: exact totals and FX, append-only revisions, replay/concurrency/stale forms, roles/CSRF/overrides, HTML/PDF download, customer privacy, original evidence and ledger unchanged, reversed downloads blocked, additive rerun; external sends 0.')


def main():
    import psycopg
    from psycopg import sql
    url=os.environ.get('AFAAQ_TEST_DATABASE_URL','');target=urlsplit(url)
    if target.scheme not in ('postgres','postgresql') or target.hostname not in ('localhost','127.0.0.1') or target.path!='/afaaq_test' or target.query or target.fragment:
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema='claim_test_'+secrets.token_hex(6)
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
    print('PASS: claim PostgreSQL acceptance.')


if __name__=='__main__':main()
