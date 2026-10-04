"""Local PostgreSQL acceptance. Synthetic records; block non-loopback egress."""
import csv
import io
import os
from pathlib import Path
import re
import secrets
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import carrier_directory as directory
    from app.storage import db, one, rows, create_session, utcnow
    client=TestClient(app,base_url='http://testserver',follow_redirects=False)
    now=utcnow()
    sessions={}
    with db() as c:
        for role in ('admin','transport','sales','viewer','finance','customs'):
            uid=c.execute('INSERT INTO users(email,name,password_hash,role,created_at) VALUES(%s,%s,%s,%s,%s) RETURNING id',(role+'@fixture.invalid',role,'not-a-password',role,now)).fetchone()['id']
            sessions[role]=(uid,)
        driver=c.execute("INSERT INTO drivers(driver_name,whatsapp_phone,vehicle_type,company_name,offer_consent,notes,created_at,updated_at) VALUES('Legacy Fixture','+966500000001','unknown','Old free text',1,'Preserve raw',%s,%s) RETURNING *",(now,now)).fetchone()
    for role, (uid,) in sessions.items():
        sid,csrf,_=create_session(uid);sessions[role]={'id':sid,'csrf':csrf,'user_id':uid}
    def request(role,method,path,**kwargs):
        client.cookies.clear()
        if role: client.cookies.set('gla_session',sessions[role]['id'])
        return client.request(method,path,headers={'Origin':'http://testserver'},**kwargs)
    def form(role='admin',**extra):
        return {'csrf':sessions[role]['csrf'],**extra}
    def record(**extra):
        return {'company_name':'Fixture Carrier','country':'SA','phone':'0500000001','email':'dispatch@fixture.invalid',
                'website':'https://fixture.invalid','source_url':'https://fixture.invalid/contact','verification_status':'public_contact_verified','verified_on':'2026-01-01',**extra}
    initial_counts={table:one('SELECT COUNT(*) n FROM '+table)['n'] for table in ('drivers','accounts','customer_directory','driver_broadcasts','outbound_messages')}
    for path in ('/carriers','/api/v7/carriers','/carriers/export.csv','/carriers/import','/drivers/export.csv'):
        assert request(None,'GET',path).status_code in (303,401)
        for role in ('sales','viewer','finance','customs'):
            assert request(role,'GET',path).status_code==403,(role,path)
    for path in ('/carriers','/api/v7/carriers','/carriers/export.csv'):
        assert request('transport','GET',path).status_code==200
    assert request('transport','GET','/carriers/import').status_code==403
    assert request('transport','POST','/carriers/new',data=form('transport',**record())).status_code==403
    assert request('admin','POST','/carriers/new',data=record()).status_code==403
    created=request('admin','POST','/carriers/new',data=form(**record()))
    assert created.status_code==303,created.text
    carrier=one('SELECT * FROM carrier_companies')
    assert carrier['phone']==driver['whatsapp_phone'] and carrier['contact_consent']=='unknown'
    assert one('SELECT * FROM drivers WHERE id=%s',(driver['id'],))==driver
    assert request('admin','POST','/carriers/new',data=form(**record(company_name=' FIXTURE   CARRIER '))).status_code==409
    assert request('admin','POST','/carriers/new',data=form(**record(company_name='Separate Company'))).status_code==409
    assert request('admin','POST','/carriers/new',data=form(**record(company_name='Separate Company'),confirm_shared_contact='yes')).status_code==303
    assert one('SELECT COUNT(*) n FROM carrier_companies')['n']==2
    page=request('admin','GET','/drivers').text
    assert 'Legacy Fixture' in page and 'بانتظار تصنيف الإدارة' in page
    assert 'شركات النقل' in page and '/carriers' in request('admin','GET','/dashboard').text
    assert request('admin','GET','/drivers?record_type=independent_driver').status_code==200
    assert 'Legacy Fixture' not in request('admin','GET','/drivers?record_type=independent_driver').text
    assert request('transport','POST',f"/drivers/{driver['id']}/classify",data=form('transport',record_type='carrier_company')).status_code==403
    assert request('admin','POST',f"/drivers/{driver['id']}/classify",data={'record_type':'carrier_company'}).status_code==403
    assert request('admin','POST',f"/drivers/{driver['id']}/classify",data=form(record_type='independent_driver',carrier_company_id=carrier['id'])).status_code==400
    result=request('admin','POST',f"/drivers/{driver['id']}/classify",data=form(record_type='carrier_company',carrier_company_id=carrier['id']))
    assert result.status_code==303,result.text
    current=one('SELECT * FROM drivers WHERE id=%s',(driver['id'],))
    for key in driver:
        if key not in ('record_type','carrier_company_id','classified_by','classified_at'): assert current[key]==driver[key],key
    assert current['record_type']=='carrier_company' and current['carrier_company_id']==carrier['id']
    assert 'Legacy Fixture' in request('admin','GET','/drivers').text
    directory.init_storage();directory.init_storage()
    assert one('SELECT * FROM drivers WHERE id=%s',(driver['id'],))==current
    assert request('admin','POST',f"/carriers/{carrier['id']}/edit",data=form(**record(),contact_consent='granted')).status_code==400
    updated=request('admin','POST',f"/carriers/{carrier['id']}/edit",data=form(**record(),contact_consent='granted',consent_evidence='Synthetic explicit agreement',consent_date='2026-01-01',quote_notes='Manager-only synthetic rate note',confirm_shared_contact='yes'))
    assert updated.status_code==303,updated.text
    for path in ('/api/v7/carriers',f"/carriers/{carrier['id']}",'/carriers/export.csv'):
        text=request('transport','GET',path).text
        assert 'Manager-only synthetic' not in text and 'Synthetic explicit agreement' not in text
    assert 'Manager-only synthetic' in request('admin','GET','/carriers/export.csv').text
    assert 'contact_consent' not in request('admin','GET','/carriers/template.csv').text
    print('PASS: roles/CSRF, separate entities, manual classification and linkage, legacy preservation, quote privacy, additive migration.')

    def upload(content,role='admin'):
        return request(role,'POST','/carriers/import/preview',data=form(role),files={'file':('companies.csv',content.encode(),'text/csv')})
    content='company_name,country,phone,email,contact_consent\nImport One,SA,0500000002,one@fixture.invalid,granted\nImport One,SA,+966500000002,one@fixture.invalid,granted\nImport Bad,SA,bad,,\nShared Contact,SA,0500000001,,\nImport Two,AE,0500000003,two@fixture.invalid,granted\n'
    preview=upload(content)
    assert preview.status_code==200,preview.text
    batch=re.search(r'/carriers/import/([^/]+)/commit',preview.text)[1]
    assert one('SELECT COUNT(*) n FROM carrier_companies')['n']==2
    assert request('transport','POST',f'/carriers/import/{batch}/commit',data=form('transport')).status_code==403
    assert request('admin','POST',f'/carriers/import/{batch}/commit',data={}).status_code==403
    # Other admin cannot commit an import that they do not own.
    uid=sessions['admin']['user_id'];sid,token,_=create_session(uid)
    with db() as c:
        c.execute("UPDATE carrier_import_batches SET user_id=%s WHERE id=%s",(sessions['transport']['user_id'],batch))
    assert request('admin','POST',f'/carriers/import/{batch}/commit',data=form()).status_code==404
    with db() as c: c.execute('UPDATE carrier_import_batches SET user_id=%s WHERE id=%s',(uid,batch))
    first=request('admin','POST',f'/carriers/import/{batch}/commit',data=form())
    assert first.status_code==200,first.text
    snapshot=rows('SELECT * FROM carrier_companies ORDER BY id')
    # Avoid TestClient context startup: workers are outside this test's scope.
    def concurrent_repeat(_):
        isolated=TestClient(app,base_url='http://testserver',follow_redirects=False)
        try:
            isolated.cookies.set('gla_session',sessions['admin']['id'])
            return isolated.post(f'/carriers/import/{batch}/commit',data=form(),headers={'Origin':'http://testserver'}).status_code
        finally:
            isolated.close()
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(concurrent_repeat,range(3)))==[200,200,200]
    repeated=request('admin','POST',f'/carriers/import/{batch}/commit',data=form())
    assert repeated.status_code==200 and rows('SELECT * FROM carrier_companies ORDER BY id')==snapshot
    receipt=one('SELECT * FROM carrier_import_batches WHERE id=%s',(batch,))
    assert receipt['inserted_count']==2 and receipt['skipped_count']==3
    assert all(item['contact_consent']=='unknown' for item in snapshot if item['company_name'].startswith('Import'))
    assert one("SELECT COUNT(*) n FROM activity WHERE action='carrier_import'")['n']==1
    # Preview-time state is stale-safe at commit; no overwrite, silent merge or second registration.
    p=upload('company_name,country,phone\nRacing Company,SA,0500000004\n')
    race=re.search(r'/carriers/import/([^/]+)/commit',p.text)[1]
    assert request('admin','POST','/carriers/new',data=form(**record(company_name='Manual Winner',phone='0500000004',email='',website=''))).status_code==303
    assert request('admin','POST',f'/carriers/import/{race}/commit',data=form()).status_code==200
    assert one('SELECT inserted_count FROM carrier_import_batches WHERE id=%s',(race,))['inserted_count']==0
    # A skipped duplicate's unused contact must not suppress another valid company.
    p=upload('company_name,country,phone\nUnique A,SA,0500000005\nUnique A,SA,0500000006\nUnique B,SA,0500000006\n')
    dedup=re.search(r'/carriers/import/([^/]+)/commit',p.text)[1]
    assert request('admin','POST',f'/carriers/import/{dedup}/commit',data=form()).status_code==200
    assert one('SELECT inserted_count FROM carrier_import_batches WHERE id=%s',(dedup,))['inserted_count']==2
    assert one("SELECT phone FROM carrier_companies WHERE company_name='Unique B'")['phone']=='+966500000006'
    p=upload('company_name,country,phone\nFixture Carrier,SA,0500000007\nNew From Unused Contact,SA,0500000007\n')
    existing_dedup=re.search(r'/carriers/import/([^/]+)/commit',p.text)[1]
    assert request('admin','POST',f'/carriers/import/{existing_dedup}/commit',data=form()).status_code==200
    assert one('SELECT inserted_count FROM carrier_import_batches WHERE id=%s',(existing_dedup,))['inserted_count']==1
    assert one("SELECT phone FROM carrier_companies WHERE company_name='New From Unused Contact'")['phone']=='+966500000007'
    assert upload('driver_name,whatsapp_phone\nSome Driver,+966500000099\n').status_code==400
    for table,count in initial_counts.items(): assert one('SELECT COUNT(*) n FROM '+table)['n']==count,table
    exported=request('admin','GET','/carriers/export.csv?country=AE').text
    exported_rows=list(csv.DictReader(io.StringIO(exported.lstrip('\ufeff'))))
    assert len(exported_rows)==1 and exported_rows[0]['company_name']=='Import Two' and exported_rows[0]['entity_type']=='carrier_company'
    assert 'Legacy Fixture' not in exported
    drivers=request('admin','GET','/drivers/export.csv').text
    assert 'Legacy Fixture' in drivers and 'Import One' not in drivers and 'record_type' in drivers
    print('PASS: preview/commit ownership, duplicate/idempotent imports, stale conflict recheck, separate filtered CSVs, unknown consent, no driver/customer/outbound additions.')
    client.close()


def main():
    import psycopg
    from psycopg import sql
    url=os.environ.get('AFAAQ_TEST_DATABASE_URL','');target=urlsplit(url)
    if target.scheme not in ('postgres','postgresql') or target.hostname not in ('localhost','127.0.0.1') or target.path!='/afaaq_test' or target.query or target.fragment:
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema='carrier_test_'+secrets.token_hex(6)
    with psycopg.connect(url,autocommit=True) as c: c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect=socket.socket.connect
    def local_only(sock,address):
        if isinstance(address,tuple) and address[0] not in ('localhost','127.0.0.1','::1'): raise AssertionError('External network blocked in company-directory acceptance')
        return connect(sock,address)
    try:
        env={'DATABASE_URL':url+'?'+urlencode({'options':'-c search_path='+schema+' -c statement_timeout=30000 -c lock_timeout=15000'},quote_via=quote),
             'DISCOVERY_AUTO_ENABLED':'0','ENABLE_EXTERNAL_ACTIONS':'0','ADMIN_EMAIL':'bootstrap@fixture.invalid','ADMIN_PASSWORD':secrets.token_urlsafe(32),'BROWSER_COOKIE_SECURE':'0'}
        with patch.dict(os.environ,env),patch.object(socket.socket,'connect',local_only): run()
    finally:
        with psycopg.connect(url,autocommit=True) as c: c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: carrier directory PostgreSQL acceptance; external sends 0.')


if __name__=='__main__':main()
