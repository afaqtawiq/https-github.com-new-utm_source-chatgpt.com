"""Offline acceptance: application functions + real SQL on SQLite, no live sends.

PostgreSQL row lock clauses are adapted for SQL execution; deployment remains
responsible for exercising PostgreSQL locks under actual concurrent requests.
"""
import asyncio
from contextlib import contextmanager
import datetime
import importlib.util
from pathlib import Path
import re
import sqlite3
import sys
import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logistics_parsing import extract_route, extract_phone, phone, accepts_offer
from app.document_parsing import document_metadata
from app.http_errors import safe_next, operational_http_error


class Result:
    def __init__(self, cursor): self.cursor = cursor
    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row is not None else None
    def fetchall(self): return [dict(row) for row in self.cursor.fetchall()]


class Database:
    def __init__(self):
        self.raw = sqlite3.connect(':memory:', check_same_thread=False)
        self.raw.row_factory = sqlite3.Row
        self.raw.executescript('''
        CREATE TABLE shipments(id INTEGER PRIMARY KEY,reference TEXT,origin TEXT,destination TEXT,status TEXT,revenue REAL,cost REAL,updated_at TEXT);
        CREATE TABLE freight_negotiations(id INTEGER PRIMARY KEY,shipment_id INTEGER,naqliat_load_id INTEGER,
            owner_phone TEXT,status TEXT,contact_channel TEXT,provider_call_id TEXT,provider_message_id TEXT,
            asking_price REAL,agreed_owner_price REAL,driver_offer_price REAL,weight_tons REAL,
            unloading_location TEXT,payment_method TEXT,notes TEXT,last_error TEXT,contacted_at TEXT,agreed_at TEXT,updated_at TEXT);
        CREATE TABLE drivers(id INTEGER PRIMARY KEY,driver_name TEXT,whatsapp_phone TEXT,availability TEXT,offer_consent INTEGER);
        CREATE TABLE driver_broadcasts(id INTEGER PRIMARY KEY,raw_command TEXT,message TEXT,status TEXT,recipient_count INTEGER,
            sent_count INTEGER DEFAULT 0,failed_count INTEGER DEFAULT 0,created_by INTEGER,created_at TEXT,updated_at TEXT,
            shipment_id INTEGER,confirmed_by INTEGER,confirmed_at TEXT,completed_at TEXT,accepted_driver_id INTEGER,accepted_at TEXT);
        CREATE TABLE driver_broadcast_recipients(id INTEGER PRIMARY KEY,broadcast_id INTEGER,driver_id INTEGER,driver_name TEXT,phone TEXT,
            status TEXT,provider_message_id TEXT,sent_at TEXT,last_error TEXT,replied_at TEXT,UNIQUE(broadcast_id,phone));
        CREATE TABLE shipment_events(id INTEGER PRIMARY KEY,shipment_id INTEGER,event_type TEXT,summary TEXT,stage TEXT,happened_at TEXT,created_by INTEGER);
        CREATE TABLE shipment_operations(shipment_id INTEGER UNIQUE,stage TEXT,driver_name TEXT,driver_phone TEXT,updated_at TEXT);
        INSERT INTO shipments VALUES(1,'NQ-16','الرياض','جدة','new',0,0,'');
        INSERT INTO freight_negotiations(id,shipment_id,owner_phone,status,agreed_owner_price,driver_offer_price,weight_tons,payment_method)
            VALUES(1,1,'+966500000001','ready_to_contact',2000,1850,20,'عند التسليم');
        INSERT INTO drivers VALUES(1,'Test Driver','+966500000002','متاح',1);
        INSERT INTO drivers VALUES(2,'Duplicate','+966500000002','متاح',1);
        INSERT INTO drivers VALUES(3,'No consent','+966500000003','متاح',0);
        INSERT INTO drivers VALUES(4,'Unavailable','+966500000004','غير متاح',1);
        INSERT INTO shipment_operations VALUES(1,'new',NULL,NULL,'');
        ''')
        self.raw.commit()

    def query(self, sql, args=()):
        sql = re.sub(r' FOR UPDATE(?: OF s,n)?', '', sql)
        return Result(self.raw.execute(sql.replace('%s', '?'), args))

    @contextmanager
    def db(self):
        with self.raw:
            yield types.SimpleNamespace(execute=self.query)

    def one(self, sql, args=()): return self.query(sql, args).fetchone()
    def rows(self, sql, args=()): return self.query(sql, args).fetchall()
    def execute(self, sql, args=()):
        with self.raw:
            cursor = self.query(sql, args)
            return cursor.cursor.lastrowid if sql.lstrip().upper().startswith('INSERT') else None


@pytest.fixture
def modules(monkeypatch):
    storage = types.ModuleType('app.storage')
    @contextmanager
    def startup_db():
        yield types.SimpleNamespace(execute=lambda *a, **k: types.SimpleNamespace(fetchone=lambda: None, fetchall=lambda: []))
    storage.db = startup_db
    for name in ('execute', 'get_session', 'log', 'one'):
        setattr(storage, name, lambda *a, **k: None)
    storage.rows = lambda *a, **k: []
    storage.utcnow = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    monkeypatch.setitem(sys.modules, 'app.storage', storage)
    data_import = types.ModuleType('app.data_import')
    data_import._phone = lambda value, country='966': phone(value)
    monkeypatch.setitem(sys.modules, 'app.data_import', data_import)
    whatsapp = types.ModuleType('app.whatsapp_integration')
    async def no_send(*a, **k): raise AssertionError('Unexpected external send')
    whatsapp.send_text_message = no_send
    monkeypatch.setitem(sys.modules, 'app.whatsapp_integration', whatsapp)
    loaded = []
    for filename in ('command_assistant', 'freight_workflow'):
        spec = importlib.util.spec_from_file_location('test_' + filename, Path(__file__).parents[1] / 'app' / (filename + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded.append(module)
    database = Database()
    for module in loaded:
        for name in ('db', 'one', 'rows', 'execute'):
            monkeypatch.setattr(module, name, getattr(database, name))
    for key in ('ENABLE_EXTERNAL_ACTIONS', 'FREIGHT_AUTO_OWNER_CONTACT'):
        monkeypatch.delenv(key, raising=False)
    return (*loaded, database)


@pytest.mark.parametrize('command,action,target', [
    ('أضف السائق محمد ورقمه 0501234567', 'add_driver', 'محمد'),
    ('آفاق أضف السايق محمد علي ورقم جواله ٠٥٠١٢٣٤٥٦٧', 'add_driver', 'محمد علي'),
    ('أرسل واتساب إلى شركة النور بخصوص عرض النقل', 'whatsapp', 'شركة النور'),
    ('تواصل مع العميل شركة النور بخصوص التخليص', 'auto_contact', 'شركة النور'),
    ('اتصل على محمد', 'call', 'محمد'),
    ('أرسل لجميع السائقين بخصوص حمولة من الرياض إلى جدة', 'driver_broadcast', 'جميع السائقين'),
    ('افتح الشحنات', 'navigate', 'افتح الشحنات'),
])
def test_real_arabic_commands(modules, command, action, target):
    result = modules[0].parse_command(command)
    assert (result['action_type'], result['target']) == (action, target)


@pytest.mark.parametrize('text,expected', [
    ('مدينة التحميل\nالرياض\nمدينة التنزيل\nجدة\nالوزن: 20 طن', ('الرياض', 'جدة')),
    ('التنزيل: جدة\nالتحميل: الرياض', ('الرياض', 'جدة')),
    ('من الرياض إلى جدة\nالوزن: 20 طن', ('الرياض', 'جدة')),
    ('المسار: الرياض → جدة\nالسعر: 2000', ('الرياض', 'جدة')),
    ('جدة الرياض الدمام', ('', '')),
    ('من الرياض إلى جدة\nمن الدمام إلى مكة', ('', '')),
])
def test_route_extraction(text, expected): assert extract_route(text) == expected


def test_local_arabic_phone_and_ambiguity():
    assert extract_phone('جوال ٠٥٠١٢٣٤٥٦٧') == '+966501234567'
    assert extract_phone('0501234567 أو 0507654321') == ''


@pytest.mark.parametrize('text,expected', [('موافق NQ-16', True), ('نعم NQ-16', True),
    ('غير موافق NQ-16', False), ('موافق NQ-16 بسعر 2500', False), ('هل أنت موافق NQ-16؟', False)])
def test_unambiguous_driver_acceptance(text, expected): assert accepts_offer(text) == expected


def test_bill_is_not_booking_or_container():
    assert document_metadata('BOOKING NO: BOOK123456\nContainer MSCU1234567')[1] == ''
    assert document_metadata('BILL OF LADING NO:\nMEDUAA123456\nMSCU1234567')[1:] == ('MEDUAA123456', 'MSCU1234567')
    assert document_metadata('B/L NUMBER: MSCU1234567')[1] == ''


def test_incomplete_route_prepares_contact_without_sending(modules):
    _, freight, database = modules
    database.execute("UPDATE shipments SET origin='',destination='غير محدد'")
    asyncio.run(freight.contact_owner(1))
    row = database.one('SELECT * FROM freight_negotiations')
    assert row['status'] == 'needs_contact_approval'
    assert row['provider_message_id'] is None
    assert 'مدينة التحميل' in freight._owner_message(database.one('SELECT * FROM shipments'))


def test_disabled_external_actions_preserve_draft(modules):
    _, freight, database = modules
    asyncio.run(freight.contact_owner(1, approved=True))
    assert database.one('SELECT status FROM freight_negotiations')['status'] == 'contact_blocked'


def test_contact_idempotency_and_unknown_outcome(modules, monkeypatch):
    _, freight, database = modules
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '1')
    monkeypatch.setenv('FREIGHT_AUTO_OWNER_CONTACT', '1')
    monkeypatch.setenv('FREIGHT_OWNER_CONTACT_CHANNEL', 'whatsapp')
    calls = []
    async def send(*args):
        calls.append(args)
        return {}  # Provider response did not prove acceptance.
    monkeypatch.setattr(freight, 'send_text_message', send)
    asyncio.run(freight.contact_owner(1, approved=True))
    asyncio.run(freight.contact_owner(1, approved=True))
    assert len(calls) == 1
    assert database.one('SELECT status FROM freight_negotiations')['status'] == 'contact_uncertain'


def test_complete_agreement_prepares_one_offer_with_correct_margin(modules):
    _, freight, database = modules
    first = freight.prepare_driver_offer(1, 1)
    assert freight.prepare_driver_offer(1, 1) == first
    offer = database.one('SELECT * FROM driver_broadcasts')
    assert offer['status'] == 'draft' and offer['recipient_count'] == 1
    assert '1,850.00' in offer['message']
    assert database.one('SELECT count(*) n FROM shipment_events')['n'] == 1
    assert database.one('SELECT count(*) n FROM driver_broadcast_recipients')['n'] == 1


def test_invalid_price_never_creates_offer(modules):
    _, freight, database = modules
    database.execute('UPDATE freight_negotiations SET agreed_owner_price=150')
    with pytest.raises(HTTPException): freight.prepare_driver_offer(1, 1)
    assert database.one('SELECT count(*) n FROM driver_broadcasts')['n'] == 0


def test_broadcast_single_send_and_first_driver_acceptance(modules, monkeypatch):
    commands, freight, database = modules
    bid = freight.prepare_driver_offer(1, 1)
    database.execute("UPDATE driver_broadcasts SET status='sending'")
    calls = []
    async def send(*args):
        calls.append(args)
        return {'messages': [{'id': 'mock-provider-id'}]}
    monkeypatch.setattr(commands, 'send_text_message', send)
    asyncio.run(commands.deliver_driver_broadcast(bid))
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert len(calls) == 1
    assert not freight.accept_driver_reply('+966500000002', 'غير موافق NQ-16')
    assert freight.accept_driver_reply('+966500000002', 'موافق NQ-16')
    assert not freight.accept_driver_reply('+966500000002', 'موافق NQ-16')
    assert database.one('SELECT status FROM shipments')['status'] == 'driver_assigned'


def test_missing_provider_id_is_not_sent(modules, monkeypatch):
    commands, freight, database = modules
    bid = freight.prepare_driver_offer(1, 1)
    database.execute("UPDATE driver_broadcasts SET status='sending'")
    async def send(*args): return {}
    monkeypatch.setattr(commands, 'send_text_message', send)
    asyncio.run(commands.deliver_driver_broadcast(bid))
    row = database.one('SELECT * FROM driver_broadcasts')
    assert row['sent_count'] == 0 and row['failed_count'] == 1
    assert row['status'] == 'completed_with_errors'


def test_browser_login_redirect_keeps_api_unauthorized():
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, operational_http_error)
    @app.get('/naqliat')
    @app.get('/api/v7/naqliat/loads')
    def protected(): raise HTTPException(401, 'Login required')
    client = TestClient(app)
    result = client.get('/naqliat', headers={'accept': 'text/html'}, follow_redirects=False)
    assert result.status_code == 303 and result.headers['location'] == '/login?next=%2Fnaqliat'
    assert client.get('/api/v7/naqliat/loads', headers={'accept': 'text/html'}).status_code == 401
    assert client.get('/naqliat', headers={'accept': 'application/json'}).status_code == 401


@pytest.mark.parametrize('target', ['https://evil.example', '//evil.example', '/\\evil.example', '/login', '/\nevil'])
def test_login_return_target_stays_local(target): assert safe_next(target) == '/dashboard'


def test_manual_search_links_are_explicitly_marked(monkeypatch):
    from app.search_connectors import brave_search_candidates
    monkeypatch.delenv('BRAVE_SEARCH_API_KEY', raising=False)
    items, _ = brave_search_candidates()
    assert items and all(item['manual_search'] for item in items)
