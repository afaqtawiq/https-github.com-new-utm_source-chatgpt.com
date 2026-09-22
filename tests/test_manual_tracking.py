"""Manual evidence workflow: matching, recipient isolation and at-most-once sending."""
import asyncio
import io
from contextlib import contextmanager
import json
import os
import sys
import types
from urllib.parse import urlencode

import httpx
import pytest
from starlette.requests import Request
from starlette.datastructures import UploadFile

os.environ.setdefault('DATABASE_URL', 'postgresql://unused/unused')
from test_whatsapp_admin import Connection, Cursor
from app import manual_tracking as tracking


class JsonCursor(Cursor):
    def convert(self, row):
        row = super().convert(row)
        if row:
            for key in ('details', 'containers'):
                if isinstance(row.get(key), str): row[key] = json.loads(row[key])
        return row


class TrackingConnection(Connection):
    def execute(self, sql, args=()):
        return JsonCursor(super().execute(sql, args).cursor)


@pytest.fixture
def setup(monkeypatch):
    c = TrackingConnection()
    c.execute('''CREATE TABLE zernio_requests(id INTEGER PRIMARY KEY,conversation_id TEXT,
        agent TEXT,fields TEXT)''')
    c.execute('''CREATE TABLE zernio_request_messages(event_id TEXT PRIMARY KEY,
        request_id INTEGER,body TEXT,reply TEXT)''')
    c.execute("INSERT INTO zernio_requests VALUES(1,'customer-conversation','afaaq',%s)",
              (json.dumps({'_whatsapp_account_id':'verified-business'}),))
    c.execute("INSERT INTO zernio_requests VALUES(2,'other-conversation','shawahid','{}')")
    @contextmanager
    def db():
        with c.db: yield c
    monkeypatch.setattr(tracking, 'db', db)
    monkeypatch.setattr(tracking, 'get_session', lambda _: {'role':'admin','csrf':'csrf','user_id':1})
    monkeypatch.setenv('ZERNIO_API_KEY', 'test')
    tracking.ensure_tables()
    details = dict(container='ABCD1234567',carrier='Example Carrier',port='Jeddah',
                   eta='2026-09-26T04:00',status='departed',source_url='https://example.org/tracking')
    c.execute('''INSERT INTO afaaq_tracking_updates(id,request_id,file_hash,media_type,content,
        evidence,containers,details,created_by) VALUES(1,1,'hash','application/pdf',%s,'evidence',%s,%s,1)''',
        (b'%PDF-example',json.dumps(['ABCD1234567']),json.dumps(details)))
    c.db.commit()
    return c, details


def request(details):
    body = urlencode(dict(details, csrf='csrf', verified='yes')).encode()
    async def receive(): return {'type':'http.request','body':body,'more_body':False}
    return Request({'type':'http','method':'POST','path':'/tracking-updates/1/send',
        'headers':[(b'content-type',b'application/x-www-form-urlencoded'),(b'cookie',b'gla_session=test')]},receive)


def provider(monkeypatch, calls, status=200, timeout=False):
    class Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kw):
            calls.append((url,kw))
            if timeout: raise httpx.ReadTimeout('timeout')
            return httpx.Response(status)
    monkeypatch.setattr(tracking.httpx, 'AsyncClient', Client)


def test_send_bound_to_request_and_deduplicated(setup,monkeypatch):
    c, details = setup
    calls = []
    provider(monkeypatch,calls)
    asyncio.run(tracking.send(1, request(details)))
    asyncio.run(tracking.send(1, request(details)))
    assert len(calls)==1
    assert '/customer-conversation/messages' in calls[0][0]
    assert calls[0][1]['json']['accountId']=='verified-business'
    assert '2026-09-26 04:00' in calls[0][1]['json']['message']
    assert c.execute('SELECT state FROM afaaq_tracking_updates').fetchone()['state']=='accepted'
    assert c.execute('SELECT count(*) n FROM zernio_request_messages').fetchone()['n']==1


@pytest.mark.parametrize('status,timeout,expected',[(400,False,'rejected'),(500,False,'uncertain'),(200,True,'uncertain')])
def test_failed_send_never_retried(setup,monkeypatch,status,timeout,expected):
    c, details = setup
    calls=[]
    provider(monkeypatch,calls,status,timeout)
    asyncio.run(tracking.send(1,request(details)))
    asyncio.run(tracking.send(1,request(details)))
    assert len(calls)==1
    assert c.execute('SELECT state FROM afaaq_tracking_updates').fetchone()['state']==expected


def test_container_mismatch_blocks_network(setup,monkeypatch):
    c, details=setup
    calls=[]
    provider(monkeypatch,calls)
    details['container']='XXXX7654321'
    with pytest.raises(tracking.HTTPException) as error: asyncio.run(tracking.send(1,request(details)))
    assert error.value.status_code==400 and not calls
    assert c.execute('SELECT state FROM afaaq_tracking_updates').fetchone()['state']=='draft'


def test_shawahid_cannot_be_target(setup,monkeypatch):
    c, details=setup
    c.execute('UPDATE afaaq_tracking_updates SET request_id=2 WHERE id=1')
    with pytest.raises(tracking.HTTPException) as error: asyncio.run(tracking.send(1,request(details)))
    assert error.value.status_code==404


def test_unauthorized_and_csrf(setup,monkeypatch):
    _,details=setup
    monkeypatch.setattr(tracking,'get_session',lambda _: {'role':'viewer','csrf':'csrf'})
    with pytest.raises(tracking.HTTPException) as error: asyncio.run(tracking.send(1,request(details)))
    assert error.value.status_code==403
    monkeypatch.setattr(tracking,'get_session',lambda _: {'role':'admin','csrf':'different'})
    with pytest.raises(tracking.HTTPException) as error: asyncio.run(tracking.send(1,request(details)))
    assert error.value.status_code==403


def test_eta_only_from_planned_event():
    assert tracking.suggestions('Bill date 31-AUG-2026 12:00 PM')['eta']==''
    data=tracking.suggestions('CMA CGM VESSEL DEPARTURE\nSaturday, 26-SEP-2026 04:00 AM PLANNED VESSEL ARRIVAL')
    assert data['eta']=='2026-09-26T04:00' and data['status']=='departed'


def test_invalid_format():
    with pytest.raises(ValueError): tracking.media_type(b'<html>not a PDF</html>')


def test_upload_matches_and_deduplicates(setup,monkeypatch):
    c,_=setup
    monkeypatch.setattr(tracking,'extract',lambda raw: 'CMA CGM ABCD1234567')
    def upload():
        return tracking.upload(1,request({}),'csrf',
            UploadFile(io.BytesIO(b'%PDF-newtracking')), UploadFile(io.BytesIO(b'%PDF-bill')))
    first=asyncio.run(upload())
    second=asyncio.run(upload())
    assert first.headers['location']==second.headers['location']
    assert c.execute('SELECT count(*) n FROM afaaq_tracking_updates').fetchone()['n']==2


def test_upload_mismatch_creates_nothing(setup,monkeypatch):
    c,_=setup
    monkeypatch.setattr(tracking,'extract',lambda raw: 'ABCD1234567' if b'tracking' in raw else 'XXXX7654321')
    with pytest.raises(tracking.HTTPException) as error:
        asyncio.run(tracking.upload(1,request({}),'csrf',
            UploadFile(io.BytesIO(b'%PDF-tracking')),UploadFile(io.BytesIO(b'%PDF-bill'))))
    assert error.value.status_code==422
    assert c.execute('SELECT count(*) n FROM afaaq_tracking_updates').fetchone()['n']==1
