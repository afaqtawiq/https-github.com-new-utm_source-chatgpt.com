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
import urllib.parse

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
        CREATE TABLE shipments(id INTEGER PRIMARY KEY,reference TEXT,origin TEXT,destination TEXT,status TEXT,revenue REAL,cost REAL,updated_at TEXT,is_test INTEGER DEFAULT 0);
        CREATE TABLE freight_negotiations(id INTEGER PRIMARY KEY,shipment_id INTEGER,naqliat_load_id INTEGER,
            record_kind TEXT NOT NULL DEFAULT 'shipment_request',owner_phone TEXT,status TEXT,contact_channel TEXT,provider_call_id TEXT,provider_message_id TEXT,
            asking_price REAL,agreed_owner_price REAL,driver_offer_price REAL,weight_tons REAL,
            unloading_location TEXT,payment_method TEXT,loading_port_status TEXT,notes TEXT,last_error TEXT,contacted_at TEXT,agreed_at TEXT,updated_at TEXT,test_owner_contact_status TEXT DEFAULT 'not_sent',test_owner_approved_by INTEGER,test_owner_preview_digest TEXT);
        CREATE TABLE drivers(id INTEGER PRIMARY KEY,driver_name TEXT,whatsapp_phone TEXT,availability TEXT,offer_consent INTEGER);
        CREATE TABLE driver_broadcasts(id INTEGER PRIMARY KEY,raw_command TEXT,message TEXT,status TEXT,recipient_count INTEGER,
            sent_count INTEGER DEFAULT 0,failed_count INTEGER DEFAULT 0,created_by INTEGER,created_at TEXT,updated_at TEXT,
            shipment_id INTEGER,confirmed_by INTEGER,confirmed_at TEXT,completed_at TEXT,accepted_driver_id INTEGER,accepted_at TEXT,is_test INTEGER DEFAULT 0,test_approved_by INTEGER,test_approved_at TEXT,test_preview_digest TEXT);
        CREATE TABLE driver_broadcast_recipients(id INTEGER PRIMARY KEY,broadcast_id INTEGER,driver_id INTEGER,driver_name TEXT,phone TEXT,
            status TEXT,provider_message_id TEXT,sent_at TEXT,last_error TEXT,replied_at TEXT,send_phase TEXT,preflight_diagnostic TEXT,post_attempted_at TEXT,provider_response_status INTEGER,provider_account_id TEXT,UNIQUE(broadcast_id,phone));
        CREATE TABLE driver_recovery_batches(id INTEGER PRIMARY KEY,broadcast_id INTEGER UNIQUE,account_id TEXT);
        CREATE TABLE shipment_events(id INTEGER PRIMARY KEY,shipment_id INTEGER,event_type TEXT,summary TEXT,stage TEXT,happened_at TEXT,created_by INTEGER);
        CREATE TABLE shipment_operations(shipment_id INTEGER UNIQUE,stage TEXT,driver_name TEXT,driver_phone TEXT,updated_at TEXT);
        INSERT INTO shipments VALUES(1,'NQ-16','الرياض','جدة','new',0,0,'',0);
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
        sql = re.sub(r' FOR UPDATE(?: OF s,n| OF b| OF n)?', '', sql)
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
    ('من الرياض إلى جدة\nموعد التحميل: غداً\nالوزن: 20 طن', ('الرياض', 'جدة')),
    ('من\nالرياض\nإلى\nجدة\nتاريخ التحميل: 2026/09/25', ('الرياض', 'جدة')),
    ('من\nالرياض\nإلى\nجدة\nالوزن: 20 طن', ('الرياض', 'جدة')),
    ('إلى: جدة\nمن: الرياض\nالجوال: 0500000001', ('الرياض', 'جدة')),
    ('من: الرياض\nالي: جدة', ('الرياض', 'جدة')),
    ('من الرياض\nالى جدة', ('الرياض', 'جدة')),
    ('من\nإلى\nالرياض\nجدة', ('', '')),
    ('من\nالرياض\nإلى\nجدة\nمن\nالدمام\nإلى\nمكة', ('', '')),
    ('التحميل: الرياض\nالتنزيل: جدة\nمن الدمام إلى مكة', ('', '')),
    ('من: الرياض\nإلى: جدة\nالتحميل: الدمام\nالتنزيل: مكة', ('', '')),
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
    assert row['status'] == 'needs_manual_data'
    assert row['provider_message_id'] is None
    assert 'مدينة التحميل' in freight._owner_message(database.one('SELECT * FROM shipments'))


def test_disabled_external_actions_preserve_draft(modules):
    _, freight, database = modules
    asyncio.run(freight.contact_owner(1, approved=True))
    assert database.one('SELECT status FROM freight_negotiations')['status'] == 'contact_blocked'


def test_real_owner_preview_manual_link_and_outbound_share_complete_v4_body(modules, monkeypatch):
    from html import unescape
    from app.transport_owner import inquiry
    from app.zernio_whatsapp import required_templates, template_parameters
    _, freight, database = modules
    database.execute("UPDATE shipments SET origin='جدة',destination='دبي'")
    monkeypatch.setattr(freight, 'session', lambda _: {'user_id': 1, 'role': 'admin', 'csrf': 'safe-csrf'})
    message = inquiry('جدة', 'دبي')
    before = database.one('SELECT * FROM freight_negotiations')
    preview = freight.workflow_detail(1, types.SimpleNamespace()).body.decode()
    assert message in unescape(preview)
    link = unescape(re.search(r"href='(https://wa.me/[^']+)'", preview).group(1))
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(link).query)['text'] == [message]
    assert database.one('SELECT * FROM freight_negotiations') == before
    calls = []
    async def send(recipient, body):
        calls.append((recipient, body))
        return {'messages': [{'id': 'local-owner-receipt'}]}
    monkeypatch.setattr(freight, 'send_text_message', send)
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '1')
    monkeypatch.setenv('FREIGHT_OWNER_CONTACT_CHANNEL', 'whatsapp')
    asyncio.run(freight.contact_owner(1, approved=True))
    asyncio.run(freight.contact_owner(1, approved=True))
    assert calls == [('+966500000001', message)]
    template = next(t for t in required_templates() if t['name'] == 'afaaq_transport_owner_inquiry_v4_ar')
    assert template_parameters(template, calls[0][1]) == ['جدة', 'دبي']
    sent_preview = freight.workflow_detail(1, types.SimpleNamespace()).body.decode()
    assert 'سبق إرسال الاستفسار؛ لم يُعد إرساله أو تغيير الرسالة السابقة.' in sent_preview
    assert database.one('SELECT status FROM freight_negotiations')['status'] == 'awaiting_owner'


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
    assert offer['status'] == 'draft' and offer['recipient_count'] == 3
    assert {r['phone'] for r in database.rows('SELECT phone FROM driver_broadcast_recipients')} == {'+966500000002', '+966500000003', '+966500000004'}
    assert '1,850.00' in offer['message']
    assert database.one('SELECT count(*) n FROM shipment_events')['n'] == 1
    assert database.one('SELECT count(*) n FROM driver_broadcast_recipients')['n'] == 3


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
    assert len(calls) == 3
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
    assert row['sent_count'] == 0 and row['failed_count'] == 3
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



def test_unsent_driver_cannot_accept(modules):
    commands, freight, database = modules
    freight.prepare_driver_offer(1, 1)
    database.execute("UPDATE driver_broadcasts SET status='sending'")
    assert not freight.accept_driver_reply('+966500000002', 'موافق NQ-16')
    assert database.one('SELECT accepted_driver_id FROM driver_broadcasts')['accepted_driver_id'] is None


def test_whatsapp_preflight_block_is_retryable_not_uncertain(modules, monkeypatch):
    commands, freight, database = modules
    from app.zernio_whatsapp import WhatsAppBlocked
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '1')
    monkeypatch.setenv('FREIGHT_AUTO_OWNER_CONTACT', '1')
    monkeypatch.setenv('FREIGHT_OWNER_CONTACT_CHANNEL', 'whatsapp')
    async def blocked(*args):
        raise WhatsAppBlocked('قالب قيد المراجعة؛ لم ترسل الرسالة')
    monkeypatch.setattr(freight, 'send_text_message', blocked)
    asyncio.run(freight.contact_owner(1, approved=True, user_id=1))
    assert database.one('SELECT status FROM freight_negotiations')['status'] == 'contact_blocked'


@pytest.fixture
def owner_loop(modules, monkeypatch):
    commands, freight, database = modules
    monkeypatch.setitem(sys.modules, 'app.command_assistant', commands)
    database.execute("UPDATE freight_negotiations SET status='awaiting_owner',contact_channel='whatsapp',asking_price=NULL,agreed_owner_price=NULL,driver_offer_price=NULL,payment_method=NULL,weight_tons=NULL")
    calls = []
    async def send(*args):
        calls.append(args)
        return {'messages': [{'id': 'simulated-' + str(len(calls))}]}
    monkeypatch.setattr(commands, 'send_text_message', send)
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '1')
    return freight, database, calls


def test_owner_whatsapp_complete_loop_receipts_margin_and_duplicates(owner_loop):
    freight, database, calls = owner_loop
    result = asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', 'NQ-16\nالسعر النهائي: ٢٬٥٠٠\nالوزن: ٢٠٫٥ طن\nالدفع: عند التسليم'))
    assert result['broadcast_sent'] and result['broadcast']['sent_count'] == 3
    assert len(calls) == 3 and '2,350.00' in calls[0][1]
    assert database.one('SELECT revenue,cost FROM shipments') == {'revenue': 2500, 'cost': 2350}
    assert asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', 'السعر: 3000\nالوزن: 30 طن\nالدفع: نقدا')) is None
    assert len(calls) == 3
    assert freight.accept_driver_reply('+966500000002', 'موافق NQ-16')
    assert not freight.accept_driver_reply('+966500000003', 'موافق NQ-16')
    assert database.one('SELECT status FROM shipments')['status'] == 'driver_assigned'


def test_owner_whatsapp_partial_fields_preserve_price(owner_loop):
    freight, database, calls = owner_loop
    first = asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', 'السعر: 2000'))
    assert set(first['missing']) == {'الوزن', 'طريقة الدفع'} and not calls
    assert database.one('SELECT asking_price,agreed_owner_price FROM freight_negotiations') == {'asking_price': 2000, 'agreed_owner_price': None}
    result = asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', 'الوزن: 20 طن\nالدفع: عند التسليم'))
    assert result['broadcast_sent'] and len(calls) == 3


@pytest.mark.parametrize('text', [
    'السعر ليس 2000 ريال، لا أوافق', 'السعر؟ الوزن: 2000 كجم', 'مطلوب 400 كيلو',
    'السعر: 2000 أو 3000\nالوزن: 20 طن\nالدفع: نقدا',
    'السعر: 2000-3000\nالوزن: 20 طن\nالدفع: نقدا',
    'السعر: -2000\nالوزن: 20 طن\nالدفع: نقدا',
    'السعر: 2000\nالوزن: 2000 كجم\nالدفع: نقدا',
    'غير متاحة\nالسعر: 2000\nالوزن: 20 طن\nالدفع: نقدا',
    'السعر: 2000\nالسعر: 3000\nالوزن: 20 طن\nالدفع: نقدا',
])
def test_owner_whatsapp_ambiguous_terms_never_broadcast(owner_loop, text):
    freight, database, calls = owner_loop
    result = asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', text))
    assert not result.get('broadcast_id') and not calls
    assert database.one('SELECT status FROM freight_negotiations')['status'] == 'awaiting_owner'


def test_owner_whatsapp_disabled_sends_truthful_draft(owner_loop, monkeypatch):
    freight, database, calls = owner_loop
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '0')
    result = asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', 'السعر: 2000\nالوزن: 20 طن\nالدفع: نقدا'))
    assert result['broadcast_id'] and not result['broadcast_sent'] and result['blocked']
    assert result['broadcast']['status'] == 'draft' and not calls


def test_owner_whatsapp_ignores_other_shipments_and_carriers(owner_loop):
    freight, database, calls = owner_loop
    text = 'السعر: 2000\nالوزن: 20 طن\nالدفع: نقدا'
    assert asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', 'NQ-99 ' + text)) is None
    assert asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', 'NQ-16 NQ-99 ' + text)) is None
    assert asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', text, shipment_id=99)) is None
    database.execute("UPDATE freight_negotiations SET record_kind='carrier_offer'")
    assert asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', text)) is None
    assert not calls


def test_incomplete_route_blocks_approved_provider_call(modules, monkeypatch):
    _, freight, database = modules
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '1')
    database.execute("UPDATE shipments SET origin='غير محدد'")
    asyncio.run(freight.contact_owner(1, approved=True))
    assert database.one('SELECT status FROM freight_negotiations')['status'] == 'needs_manual_data'


def test_driver_cannot_accept_two_references(owner_loop):
    freight, database, calls = owner_loop
    asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', 'السعر: 2000\nالوزن: 20 طن\nالدفع: نقدا'))
    assert not freight.accept_driver_reply('+966500000002', 'موافق NQ-16 NQ-99')


def test_workflow_api_reports_effective_contact_gate(modules, monkeypatch):
    _, freight, database = modules
    monkeypatch.setattr(freight, 'session', lambda request: {'user_id': 1})
    monkeypatch.setenv('FREIGHT_AUTO_OWNER_CONTACT', '0')
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '1')
    assert freight.workflow_api(None)['owner_auto_contact_enabled'] is True
    monkeypatch.setenv('FREIGHT_AUTO_OWNER_CONTACT', '1')
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '0')
    assert freight.workflow_api(None)['owner_auto_contact_enabled'] is False


def test_disclosed_workflow_requires_explicit_approval_and_never_assigns_real_driver(modules, monkeypatch):
    commands, freight, database = modules
    from app.transport_test import DISCLAIMER, display_reference, test_broadcast_context
    storage = sys.modules['app.storage']
    for name in ('db', 'one', 'rows', 'execute'):
        monkeypatch.setattr(storage, name, getattr(database, name))
    database.execute("UPDATE shipments SET is_test=1,status='test_pending'")
    database.execute("UPDATE freight_negotiations SET status='awaiting_owner',contact_channel='whatsapp',agreed_owner_price=NULL")
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '1')
    calls = []
    async def send(*args):
        calls.append(args)
        return {'messages': [{'id': 'simulated-test-receipt'}]}
    monkeypatch.setattr(commands, 'send_text_message', send)
    terms = 'NQ-16\nالسعر النهائي: 2000\nالوزن: 20\nالتنزيل: الشارقة\nطريقة الدفع: محاكاة'
    result = asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', terms, shipment_id=1))
    assert result['is_test'] and result['broadcast_sent'] is False
    bid = result['broadcast_id']
    assert not calls and not asyncio.run(freight.start_driver_broadcast(bid))
    campaign = database.one('SELECT * FROM driver_broadcasts WHERE id=?', (bid,))
    assert campaign['message'].count(DISCLAIMER) == 2
    assert database.one('SELECT revenue,cost FROM shipments') == {'revenue': 0, 'cost': 0}
    database.execute("UPDATE driver_broadcasts SET status='sending' WHERE id=?", (bid,))
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert not calls
    assert database.one('SELECT status FROM driver_broadcasts')['status'] == 'test_blocked'
    database.execute("UPDATE driver_broadcasts SET status='draft' WHERE id=?", (bid,))
    current = {'user_id': 1, 'role': 'admin', 'csrf': 'test-csrf'}
    monkeypatch.setattr(commands, 'session', lambda _: current)
    def request(data):
        async def body(): return urllib.parse.urlencode(data).encode()
        return types.SimpleNamespace(body=body)
    from fastapi import BackgroundTasks
    with pytest.raises(HTTPException):
        asyncio.run(commands.send_broadcast(bid, request({'csrf':'test-csrf','confirmed':'yes'}), BackgroundTasks()))
    digest = test_broadcast_context(campaign)['digest']
    tasks = BackgroundTasks()
    asyncio.run(commands.send_broadcast(bid, request({'csrf':'test-csrf','confirmed':'yes','test_confirmed':'yes','test_preview':digest}), tasks))
    asyncio.run(tasks())
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert len(calls) == 3
    assert not freight.accept_driver_reply('+966500000002', 'موافق NQ-16')
    assert freight.accept_driver_reply('+966500000002', 'موافق ' + display_reference('NQ-16', True))
    assert not freight.accept_driver_reply('+966500000003', 'موافق ' + display_reference('NQ-16', True))
    assert database.one('SELECT status,revenue,cost FROM shipments') == {'status':'test_completed','revenue':0,'cost':0}
    assert database.one('SELECT stage,driver_name,driver_phone FROM shipment_operations') == {'stage':'test_completed','driver_name':None,'driver_phone':None}


@pytest.mark.parametrize('mode,state,receipt', [('success','sent','owner-receipt'), ('missing','uncertain',None), ('timeout','uncertain',None), ('blocked','blocked',None)])
def test_disclosed_owner_inquiry_preserves_real_receipt_and_blocks_duplicate_send(modules, monkeypatch, mode, state, receipt):
    _, freight, database = modules
    from app.transport_test import DISCLAIMER, owner_inquiry_digest
    from app.zernio_whatsapp import WhatsAppBlocked
    database.execute("UPDATE shipments SET is_test=1,status='test_pending'")
    database.execute("UPDATE freight_negotiations SET status='awaiting_owner',contact_channel='whatsapp',agreed_owner_price=NULL")
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '1')
    calls = []
    async def send(number, message):
        calls.append((number, message))
        if mode == 'blocked': raise WhatsAppBlocked('No verified window or matching approved template')
        if mode == 'timeout': raise TimeoutError('uncertain')
        return {'messages': [{'id':'owner-receipt'}]} if mode == 'success' else {'messages': []}
    monkeypatch.setattr(freight, 'send_text_message', send)
    item = database.one('SELECT s.*,n.owner_phone FROM shipments s JOIN freight_negotiations n ON n.shipment_id=s.id')
    digest = owner_inquiry_digest(item)
    assert asyncio.run(freight.send_test_owner_inquiry(1, 1, digest)) == receipt
    result = database.one('SELECT test_owner_contact_status,provider_message_id,status FROM freight_negotiations')
    assert result == {'test_owner_contact_status':state,'provider_message_id':receipt,'status':'awaiting_owner'}
    assert len(calls) == 1 and calls[0][1].startswith(DISCLAIMER)
    assert 'NQ-16' not in calls[0][1] and 'الرياض إلى جدة' in calls[0][1]
    assert not database.rows('SELECT * FROM driver_broadcasts')
    if mode != 'blocked':
        with pytest.raises(HTTPException): asyncio.run(freight.send_test_owner_inquiry(1, 1, digest))
        assert len(calls) == 1
    assert database.one('SELECT COUNT(*) n FROM shipment_events')["n"] == (1 if receipt else 0)


def test_disclosed_owner_inquiry_checks_role_csrf_preview_and_real_record(modules, monkeypatch):
    _, freight, database = modules
    from app.transport_test import owner_inquiry_digest
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS','1')
    async def forbidden(*args): raise AssertionError('Unauthorized owner send')
    monkeypatch.setattr(freight, 'send_text_message', forbidden)
    with pytest.raises(HTTPException): asyncio.run(freight.send_test_owner_inquiry(1,1,'irrelevant'))
    database.execute("UPDATE shipments SET is_test=1,status='test_pending'")
    database.execute("UPDATE freight_negotiations SET status='awaiting_owner'")
    item = database.one('SELECT s.*,n.owner_phone FROM shipments s JOIN freight_negotiations n ON n.shipment_id=s.id')
    digest = owner_inquiry_digest(item)
    async def body(): return urllib.parse.urlencode({'csrf':'csrf','test_owner_confirmed':'yes','test_owner_preview':digest}).encode()
    request = types.SimpleNamespace(body=body)
    monkeypatch.setattr(freight,'session',lambda _: {'role':'transport','user_id':1,'csrf':'csrf'})
    with pytest.raises(HTTPException) as exc: asyncio.run(freight.test_owner_inquiry_now(1,request))
    assert exc.value.status_code == 403
    monkeypatch.setattr(freight,'session',lambda _: {'role':'admin','user_id':1,'csrf':'different'})
    with pytest.raises(HTTPException) as exc: asyncio.run(freight.test_owner_inquiry_now(1,request))
    assert exc.value.status_code == 403
    database.execute("UPDATE freight_negotiations SET owner_phone='+966500000005'")
    with pytest.raises(HTTPException) as exc: asyncio.run(freight.send_test_owner_inquiry(1,1,digest))
    assert exc.value.status_code == 400
    assert database.one('SELECT test_owner_contact_status FROM freight_negotiations')['test_owner_contact_status'] == 'not_sent'


def test_reference_free_test_owner_saves_initial_terms_without_inventing_weight(owner_loop):
    freight, database, calls = owner_loop
    database.execute("UPDATE shipments SET is_test=1,status='test_pending'")
    result = asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001',
        'السعر: 2000\nطريقة الدفع: محاكاة\nالتحميل من داخل الميناء', shipment_id=1))
    assert 'الوزن' in result['missing'] and not calls
    assert database.one('SELECT asking_price,weight_tons,loading_port_status,unloading_location FROM freight_negotiations') == {
        'asking_price':2000,'weight_tons':None,'loading_port_status':'inside','unloading_location':None}
    assert not database.rows('SELECT * FROM driver_broadcasts')


def test_workflow_rechecks_quote_under_lock(owner_loop):
    freight, database, calls = owner_loop
    database.execute("UPDATE freight_negotiations SET provider_message_id='current-receipt'")
    terms = 'السعر: 2000\nالوزن: 20\nالدفع: عند التسليم'
    assert asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', terms,
        shipment_id=1, quoted_message_id='stale-receipt')) is None
    assert not calls and database.one('SELECT asking_price FROM freight_negotiations')['asking_price'] is None
    assert asyncio.run(freight.advance_owner_whatsapp_reply('+966500000001', terms,
        shipment_id=1, quoted_message_id='current-receipt'))['broadcast_sent']


def legacy_driver_draft(modules, monkeypatch):
    commands, freight, database = modules
    for name in ('db','one','rows','execute'):
        monkeypatch.setattr(sys.modules['app.storage'], name, getattr(database, name))
    database.execute("UPDATE shipments SET is_test=1,status='test_pending'")
    bid = freight.prepare_driver_offer(1, 1)
    # Simulate the legacy UNSENT audience, not a new or changed driver record.
    for index, number in enumerate(('+966055504207','+966050850729'), 100):
        database.execute("INSERT INTO driver_broadcast_recipients(broadcast_id,driver_id,driver_name,phone,status) VALUES(?,?,?,?,'pending')", (bid,index,'Legacy invalid',number))
    database.execute('UPDATE driver_broadcasts SET recipient_count=5 WHERE id=?', (bid,))
    database.execute("UPDATE freight_negotiations SET loading_port_status='inside'")
    current = {'user_id':1,'role':'admin','csrf':'safe-csrf'}
    monkeypatch.setattr(commands, 'session', lambda _: current)
    return commands, freight, database, bid, current


def refresh_request(data):
    async def body(): return urllib.parse.urlencode(data).encode()
    return types.SimpleNamespace(body=body)


def refresh_plan(commands, database, bid):
    from app.driver_offer import preview_plan
    campaign = database.one('SELECT * FROM driver_broadcasts WHERE id=?', (bid,))
    recipients = database.rows('SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=? ORDER BY id', (bid,))
    with database.db() as c:
        return preview_plan(campaign, recipients, commands._preview_message(c, campaign))


def test_refresh_draft_excludes_invalid_audits_and_clears_approval_without_send(modules, monkeypatch):
    commands, freight, database, bid, current = legacy_driver_draft(modules, monkeypatch)
    before_drivers = database.rows('SELECT * FROM drivers')
    before_financials = database.one('SELECT revenue,cost,origin FROM shipments')
    from app.transport_test import test_broadcast_context
    old_campaign = database.one('SELECT * FROM driver_broadcasts WHERE id=?', (bid,))
    old_digest = test_broadcast_context(old_campaign)['digest']
    database.execute("UPDATE driver_broadcasts SET test_approved_by=1,test_approved_at='prior',test_preview_digest=? WHERE id=?", (old_digest,bid))
    plan = refresh_plan(commands, database, bid)
    assert len(plan['active']) == 3 and len(plan['excluded']) == 2
    preview = commands.broadcast_review(bid, types.SimpleNamespace()).body.decode()
    assert 'refresh-preview' in preview and 'داخل الميناء' in preview
    assert f'action=/commands/broadcast/{bid}/send' not in preview
    response = asyncio.run(commands.refresh_broadcast_preview(bid, refresh_request({'csrf':'safe-csrf','refresh_confirmed':'yes','refresh_preview':plan['digest']})))
    assert response.status_code == 303
    campaign = database.one('SELECT * FROM driver_broadcasts WHERE id=?', (bid,))
    assert campaign['recipient_count'] == 3 and campaign['status'] == 'draft'
    assert campaign['test_approved_by'] is None and campaign['test_preview_digest'] is None
    assert campaign['sent_count'] == campaign['failed_count'] == 0
    excluded = database.rows("SELECT * FROM driver_broadcast_recipients WHERE status='excluded'")
    assert len(excluded) == 2 and all(r['last_error'].startswith('invalid_saudi_trunk_prefix:') for r in excluded)
    assert all(r['provider_message_id'] is None and r['sent_at'] is None for r in excluded)
    assert database.rows('SELECT * FROM drivers') == before_drivers
    assert database.one('SELECT revenue,cost,origin FROM shipments') == before_financials
    assert database.one("SELECT COUNT(*) n FROM shipment_events WHERE event_type='driver_preview_refreshed'")['n'] == 1
    assert test_broadcast_context(campaign)['digest'] != old_digest
    from fastapi import BackgroundTasks
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS','1')
    with pytest.raises(HTTPException):
        asyncio.run(commands.send_broadcast(bid,refresh_request({'csrf':'safe-csrf','confirmed':'yes','test_confirmed':'yes','test_preview':old_digest}),BackgroundTasks()))
    # A second application of the same reviewed plan is stale, not a resend.
    with pytest.raises(HTTPException):
        asyncio.run(commands.refresh_broadcast_preview(bid,refresh_request({'csrf':'safe-csrf','refresh_confirmed':'yes','refresh_preview':plan['digest']})))


@pytest.mark.parametrize('change', ['sent','sending','uncertain','failed','provider','sent_at','replied_at','post_attempted_at','provider_response_status','confirmed','completed','accepted'])
def test_refresh_never_mutates_attempted_campaign(modules, monkeypatch, change):
    commands, _, database, bid, _ = legacy_driver_draft(modules, monkeypatch)
    plan = refresh_plan(commands,database,bid)
    if change in ('sent','sending','uncertain','failed'):
        database.execute('UPDATE driver_broadcast_recipients SET status=? WHERE id=1', (change,))
    elif change in ('provider','sent_at','replied_at','post_attempted_at','provider_response_status'):
        column = {'provider':'provider_message_id','sent_at':'sent_at','replied_at':'replied_at','post_attempted_at':'post_attempted_at','provider_response_status':'provider_response_status'}[change]
        database.execute('UPDATE driver_broadcast_recipients SET '+column+"='evidence' WHERE id=1")
    else:
        column = {'confirmed':'confirmed_at','completed':'completed_at','accepted':'accepted_at'}[change]
        database.execute('UPDATE driver_broadcasts SET '+column+"='evidence' WHERE id=?", (bid,))
    before = database.rows('SELECT * FROM driver_broadcast_recipients')
    with pytest.raises(HTTPException):
        asyncio.run(commands.refresh_broadcast_preview(bid,refresh_request({'csrf':'safe-csrf','refresh_confirmed':'yes','refresh_preview':plan['digest']})))
    assert database.rows('SELECT * FROM driver_broadcast_recipients') == before


def test_old_invalid_draft_cannot_send_or_bypass_through_worker(modules, monkeypatch):
    commands, _, database, bid, _ = legacy_driver_draft(modules, monkeypatch)
    from app.transport_test import test_broadcast_context
    from fastapi import BackgroundTasks
    campaign = database.one('SELECT * FROM driver_broadcasts WHERE id=?',(bid,))
    digest = test_broadcast_context(campaign)['digest']
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS','1')
    with pytest.raises(HTTPException):
        asyncio.run(commands.send_broadcast(bid,refresh_request({'csrf':'safe-csrf','confirmed':'yes','test_confirmed':'yes','test_preview':digest}),BackgroundTasks()))
    database.execute("UPDATE driver_broadcasts SET status='sending',test_approved_by=1,test_approved_at='approved',test_preview_digest=? WHERE id=?",(digest,bid))
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert database.one('SELECT status FROM driver_broadcasts WHERE id=?',(bid,))['status'] == 'validation_blocked'
    assert all(r['status']=='pending' for r in database.rows('SELECT status FROM driver_broadcast_recipients'))


@pytest.mark.parametrize('role,csrf,confirmed,digest', [('transport','safe-csrf','yes','valid'),('admin','wrong','yes','valid'),('admin','safe-csrf','','valid'),('admin','safe-csrf','yes','stale')])
def test_refresh_requires_role_csrf_explicit_and_current_preview(modules,monkeypatch,role,csrf,confirmed,digest):
    commands, _, database, bid, current = legacy_driver_draft(modules,monkeypatch)
    plan = refresh_plan(commands,database,bid)
    current['role'] = role
    before = database.rows('SELECT * FROM driver_broadcast_recipients')
    with pytest.raises(HTTPException):
        asyncio.run(commands.refresh_broadcast_preview(bid,refresh_request({'csrf':csrf,'refresh_confirmed':confirmed,'refresh_preview':plan['digest'] if digest=='valid' else digest})))
    assert database.rows('SELECT * FROM driver_broadcast_recipients') == before


def test_refresh_is_limited_to_disclosed_test_drafts(modules,monkeypatch):
    commands, _, database, bid, _ = legacy_driver_draft(modules,monkeypatch)
    plan = refresh_plan(commands,database,bid)
    database.execute('UPDATE driver_broadcasts SET is_test=0 WHERE id=?',(bid,))
    database.execute('UPDATE shipments SET is_test=0')
    before = database.rows('SELECT * FROM driver_broadcast_recipients')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(commands.refresh_broadcast_preview(bid,refresh_request({'csrf':'safe-csrf','refresh_confirmed':'yes','refresh_preview':plan['digest']})))
    assert exc.value.status_code == 409
    assert database.rows('SELECT * FROM driver_broadcast_recipients') == before
    assert 'name=refresh_preview' not in commands.broadcast_review(bid,types.SimpleNamespace()).body.decode()


def test_preflight_diagnostics_are_sanitized_and_never_dispatch(modules,monkeypatch):
    commands, freight, database = modules
    from app.zernio_whatsapp import WhatsAppPreflightBlocked
    bid = freight.prepare_driver_offer(1,1)
    database.execute("UPDATE driver_broadcasts SET status='sending' WHERE id=?",(bid,))
    calls=[]
    async def fail(*args):
        calls.append(args)
        raise WhatsAppPreflightBlocked({'phase':'preflight','endpoint':'accounts','http_status':429,
            'error_category':'http_error','attempts':3,'retryable':True,'rate_remaining':0,
            'authorization':'must-not-persist'},retryable=True)
    monkeypatch.setattr(commands,'send_text_message',fail)
    asyncio.run(commands.deliver_driver_broadcast(bid))
    recipients=database.rows('SELECT * FROM driver_broadcast_recipients')
    assert len(calls)==3 and all(r['status']=='failed' and r['send_phase']=='preflight_failed' for r in recipients)
    assert all(r['post_attempted_at'] is None and r['provider_response_status'] is None and r['provider_message_id'] is None for r in recipients)
    assert all('429' in r['preflight_diagnostic'] and 'must-not-persist' not in r['preflight_diagnostic'] for r in recipients)
    snapshot=database.rows('SELECT * FROM driver_broadcast_recipients')
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert len(calls)==3 and database.rows('SELECT * FROM driver_broadcast_recipients')==snapshot


@pytest.mark.parametrize('outcome',['timeout','invalid_json'])
def test_post_boundary_timeout_remains_uncertain_and_is_never_retried(modules,monkeypatch,outcome):
    commands, freight, database = modules
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS','1')
    from app import zernio_whatsapp as z
    bid = freight.prepare_driver_offer(1,1)
    database.execute("UPDATE driver_broadcasts SET status='sending' WHERE id=?",(bid,))
    calls=[]
    async def uncertain(*args):
        guard=z._dispatch_guard.get()
        assert guard
        guard()
        calls.append(args)
        if outcome == 'invalid_json': raise z.WhatsAppSendUncertain(200)
        raise TimeoutError('unknown after POST')
    monkeypatch.setattr(commands,'send_text_message',uncertain)
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert len(calls)==3
    recipients=database.rows('SELECT * FROM driver_broadcast_recipients')
    assert all(r['status']=='uncertain' and r['send_phase']=='uncertain' and r['post_attempted_at'] for r in recipients)
    assert all(r['preflight_diagnostic'] is None for r in recipients)
    assert all(r['provider_response_status'] == (200 if outcome=='invalid_json' else None) for r in recipients)
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert len(calls)==3


def test_acceptance_during_preflight_stops_dispatch_at_final_guard(modules,monkeypatch):
    commands, freight, database = modules
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS','1')
    from app import zernio_whatsapp as z
    bid=freight.prepare_driver_offer(1,1)
    database.execute("UPDATE driver_broadcasts SET status='sending' WHERE id=?",(bid,))
    dispatched=[]
    async def wait_then_cancel(*args):
        database.execute("UPDATE driver_broadcasts SET status='test_completed',accepted_driver_id=1 WHERE id=?",(bid,))
        database.execute("UPDATE driver_broadcast_recipients SET status='closed' WHERE broadcast_id=?",(bid,))
        z._dispatch_guard.get()()
        dispatched.append(args)
        return {'messages':[{'id':'must-not-happen'}]}
    monkeypatch.setattr(commands,'send_text_message',wait_then_cancel)
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert not dispatched
    assert all(r['post_attempted_at'] is None and r['provider_message_id'] is None for r in database.rows('SELECT * FROM driver_broadcast_recipients'))
    assert database.one('SELECT status FROM driver_broadcasts')['status']=='test_completed'


def test_provider_accepted_receipts_are_immutable_even_when_delivery_later_failed(modules,monkeypatch):
    commands, freight, database = modules
    bid=freight.prepare_driver_offer(1,1)
    database.execute("UPDATE driver_broadcasts SET status='completed_with_errors',sent_count=1,failed_count=2 WHERE id=?",(bid,))
    database.execute("UPDATE driver_broadcast_recipients SET status='sent',provider_message_id='accepted-receipt',sent_at='before',send_phase='accepted',last_error='Business eligibility payment issue 131042' WHERE id=1")
    database.execute("UPDATE driver_broadcast_recipients SET status='failed',last_error='تعذر التحقق من إعداد واتساب لدى Zernio؛ لم تُرسل الرسالة' WHERE id<>1")
    before=database.rows('SELECT * FROM driver_broadcast_recipients')
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert database.rows('SELECT * FROM driver_broadcast_recipients')==before


def test_dispatch_guard_rejects_changed_message_after_preflight(modules,monkeypatch):
    commands, freight, database = modules
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS','1')
    from app import zernio_whatsapp as z
    bid=freight.prepare_driver_offer(1,1)
    database.execute("UPDATE driver_broadcasts SET status='sending' WHERE id=?",(bid,))
    posts=[]
    async def changed(*args):
        database.execute("UPDATE driver_broadcasts SET message=message || ' changed' WHERE id=?",(bid,))
        z._dispatch_guard.get()()
        posts.append(args)
        return {'messages':[{'id':'must-not-happen'}]}
    monkeypatch.setattr(commands,'send_text_message',changed)
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert not posts
    assert all(r['post_attempted_at'] is None and r['provider_message_id'] is None for r in database.rows('SELECT * FROM driver_broadcast_recipients'))


def test_dispatch_guard_rechecks_external_action_switch_after_wait(modules,monkeypatch):
    commands, freight, database = modules
    from app import zernio_whatsapp as z
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS','1')
    bid=freight.prepare_driver_offer(1,1)
    database.execute("UPDATE driver_broadcasts SET status='sending' WHERE id=?",(bid,))
    posts=[]
    async def disabled_after_wait(*args):
        monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS','0')
        z._dispatch_guard.get()()
        posts.append(args)
    monkeypatch.setattr(commands,'send_text_message',disabled_after_wait)
    asyncio.run(commands.deliver_driver_broadcast(bid))
    assert not posts
    assert all(r['post_attempted_at'] is None for r in database.rows('SELECT * FROM driver_broadcast_recipients'))
