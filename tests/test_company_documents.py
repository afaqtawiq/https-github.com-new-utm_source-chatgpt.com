"""Synthetic-only PostgreSQL archive tests. Never reads production DATABASE_URL."""
import hashlib
import io
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from app import company_documents as archive

URL=os.getenv('COMPANY_ARCHIVE_TEST_URL','')
pytestmark=pytest.mark.skipif(not URL,reason='requires explicit isolated PostgreSQL test URL')

@pytest.fixture(scope='module')
def database():
    parsed=urlparse(URL)
    assert parsed.hostname in ('127.0.0.1','localhost') and parsed.path.endswith('_test') and not parsed.query and not parsed.fragment
    name='company_archive_'+uuid4().hex
    with psycopg.connect(URL,hostaddr='127.0.0.1') as c:c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
    @contextmanager
    def connect():
        with psycopg.connect(URL,hostaddr='127.0.0.1',row_factory=dict_row) as c:
            c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(name)))
            yield c
    with connect() as c:
        c.execute('CREATE TABLE users(id BIGSERIAL PRIMARY KEY,role TEXT NOT NULL,is_active INTEGER NOT NULL DEFAULT 1,must_change_password INTEGER NOT NULL DEFAULT 0)')
        c.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY,user_id BIGINT REFERENCES users(id),csrf TEXT NOT NULL,expires_at TIMESTAMPTZ NOT NULL)')
        c.execute(archive.SCHEMA)
    yield connect
    with psycopg.connect(URL,hostaddr='127.0.0.1') as c:c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))

@pytest.fixture
def client(database,monkeypatch):
    monkeypatch.setattr(archive,'database',database);monkeypatch.setattr(archive,'ENABLED',True)
    app=FastAPI();app.include_router(archive.router)
    return TestClient(app)


def login(client,database,role='admin',active=1,change=0,expired=False):
    token='synthetic-'+uuid4().hex;csrf='synthetic-csrf-'+uuid4().hex
    with database() as c:
        uid=c.execute('INSERT INTO users(role,is_active,must_change_password) VALUES(%s,%s,%s) RETURNING id',(role,active,change)).fetchone()['id']
        c.execute("INSERT INTO sessions VALUES(%s,%s,%s,now()+(%s * interval '1 hour'))",(token,uid,csrf,-1 if expired else 1))
    client.cookies.set('gla_session',token)
    return uid,csrf


def sample(fmt='PNG',color=None):
    data=io.BytesIO();Image.new('RGB',(12,12),color or (int(uuid4().hex[:6],16)%255,44,55)).save(data,fmt)
    return data.getvalue()


def upload(client,csrf,content=None,**changes):
    data={'csrf':csrf,'name':'SYNTHETIC COMPANY DOCUMENT','kind':'transport_license','issued_on':'2026-01-01','expires_on':'2027-01-01'};data.update(changes)
    return client.post('/company-documents',data=data,files={'file':('synthetic.png',content or sample(),'image/png')},follow_redirects=False)


def record(database,content):
    with database() as c:return c.execute('SELECT * FROM company_documents WHERE sha256=%s',(hashlib.sha256(content).hexdigest(),)).fetchone()


@pytest.mark.parametrize('role,active,change,expired,status',[('viewer',1,0,False,403),('sales',1,0,False,403),('customs',1,0,False,403),('transport',1,0,False,403),('finance',1,0,False,403),('admin',0,0,False,403),('admin',1,1,False,403),('admin',1,0,True,401)])
def test_all_endpoints_reject_unauthorized(client,database,role,active,change,expired,status):
    _,csrf=login(client,database,role,active,change,expired)
    for response in [client.get('/company-documents'),upload(client,csrf),client.get(f'/company-documents/{uuid4()}/download')]:assert response.status_code==status


def test_anonymous_and_disabled_are_denied_before_upload_parse(client,monkeypatch):
    assert client.get('/company-documents').status_code==401
    assert client.post('/company-documents',content=b'not multipart').status_code==401
    monkeypatch.setattr(archive,'ENABLED',False)
    assert client.get('/company-documents').status_code==404


def test_store_retrieve_original_and_reinitialize_without_loss(client,database):
    uid,csrf=login(client,database);content=sample();assert upload(client,csrf,content).status_code==303
    row=record(database,content);assert bytes(row['content'])==content and row['created_by']==uid and row['status']=='archived_copy'
    archive.init_storage()
    response=client.get(f'/company-documents/{row["id"]}/download')
    assert response.content==content and response.headers['content-type']=='image/png'
    assert response.headers['content-disposition'].startswith('attachment; filename="company-document-')
    assert 'no-store' in response.headers['cache-control'] and response.headers['x-content-type-options']=='nosniff'
    page=client.get('/company-documents');assert 'SYNTHETIC COMPANY DOCUMENT' in page.text and content.hex() not in page.text
    assert 'no-store' in page.headers['cache-control']
    # Revoking the existing administrator role takes effect without logout.
    with database() as c:c.execute("UPDATE users SET role='viewer' WHERE id=%s",(uid,))
    assert client.get(f'/company-documents/{row["id"]}/download').status_code==403


def test_duplicate_concurrent_uploads_do_not_overwrite_original(client,database):
    uid,csrf=login(client,database);content=sample()
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:upload(client,csrf,content).status_code,range(2)))
    assert results==[303,303]
    original=record(database,content)
    assert upload(client,csrf,content,name='Changed name',expires_on='2028-01-01').status_code==303
    assert record(database,content)==original
    with database() as c:
        events=c.execute('SELECT action FROM company_document_audit WHERE document_id=%s',(original['id'],)).fetchall()
    assert [r['action'] for r in events].count('upload')==1
    assert [r['action'] for r in events].count('duplicate')==2


def test_csrf_metadata_and_dates(client,database):
    _,csrf=login(client,database)
    assert upload(client,'bad').status_code==403
    for fields in [{'name':'x'},{'kind':'customer_invoice'},{'expires_on':'2025-01-01'},{'issued_on':'wrong'}]:assert upload(client,csrf,**fields).status_code==422
    malicious='<script>alert("x")</script>'
    assert upload(client,csrf,name=malicious).status_code==303
    page=client.get('/company-documents');assert malicious not in page.text and '&lt;script&gt;' in page.text


@pytest.mark.parametrize('filename,mime,content',[('../secret.png','image/png',b'bad'),('x.html','text/html',b'<script>x</script>'),('x.pdf','application/pdf',b'%PDF-not-really\n%%EOF'),('x.png','image/png',b'not-an-image')])
def test_invalid_types_and_unsafe_names(client,database,filename,mime,content):
    _,csrf=login(client,database)
    response=client.post('/company-documents',data={'csrf':csrf,'name':'SYNTHETIC','kind':'other','issued_on':'','expires_on':''},files={'file':(filename,content,mime)})
    assert response.status_code in (400,415,422)


def test_pdf_and_jpeg_originals_are_preserved(client,database):
    _,csrf=login(client,database)
    for fmt,mime,suffix in [('PDF','application/pdf','pdf'),('JPEG','image/jpeg','jpg')]:
        content=sample(fmt)
        response=client.post('/company-documents',data={'csrf':csrf,'name':'SYNTHETIC','kind':'tax_certificate','issued_on':'','expires_on':''},files={'file':('test.'+suffix,content,mime)},follow_redirects=False)
        assert response.status_code==303,response.text
        row=record(database,content)
        assert client.get(f'/company-documents/{row["id"]}/download').content==content


def test_size_bound(client,database):
    _,csrf=login(client,database)
    assert upload(client,csrf,b'x'*(archive.MAX_BYTES+1)).status_code==413


def test_customer_store_is_never_accessed_or_downloaded(client,database):
    _,csrf=login(client,database);customer_id=uuid4()
    with database() as c:
        c.execute('CREATE TABLE IF NOT EXISTS synthetic_customer_documents(id UUID PRIMARY KEY,content BYTEA)')
        c.execute('INSERT INTO synthetic_customer_documents VALUES(%s,%s)',(customer_id,b'CUSTOMER_PRIVATE_SENTINEL'))
    assert client.get(f'/company-documents/{customer_id}/download').status_code==404
    assert 'CUSTOMER_PRIVATE_SENTINEL' not in client.get('/company-documents').text
    source=Path(archive.__file__).read_text()
    for table in ('fasah_documents','shipment_documents','shipping_agent_documents','saber_documents'):assert table not in source


def test_no_edit_delete_and_audit_does_not_contain_sensitive_metadata(client,database):
    uid,csrf=login(client,database);content=sample();assert upload(client,csrf,content).status_code==303
    row=record(database,content)
    for method in ('delete','patch','put'):assert getattr(client,method)(f'/company-documents/{row["id"]}/download').status_code==405
    with pytest.raises(psycopg.Error):
        with database() as c:c.execute('DELETE FROM company_documents WHERE id=%s',(row['id'],))
    with pytest.raises(psycopg.Error):
        with database() as c:c.execute("UPDATE company_documents SET name='overwrite' WHERE id=%s",(row['id'],))
    with database() as c:events=c.execute('SELECT * FROM company_document_audit WHERE actor_id=%s',(uid,)).fetchall()
    assert all(set(e)=={'id','document_id','actor_id','action','created_at'} for e in events)
    assert 'SYNTHETIC COMPANY DOCUMENT' not in str(events) and row['sha256'] not in str(events)
    assert record(database,content)['content']==row['content']
