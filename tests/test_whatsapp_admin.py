"""Offline integration tests: real SQL via a SQLite dialect adapter, mocked providers."""
import asyncio
from contextlib import contextmanager
import copy
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import types
from unittest.mock import patch

import pytest
from starlette.requests import Request

storage = types.ModuleType('app.storage')
storage.db = lambda: None
storage.get_session = lambda *_: None
sys.modules['app.storage'] = storage
from app import whatsapp_admin as admin
from app import zernio_receiver as receiver


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def convert(self, row):
        if row is None:
            return None
        row = dict(row)
        for key in ('fields', 'state'):
            if key in row and isinstance(row[key], str) and row[key].startswith('{'):
                row[key] = json.loads(row[key])
        return row

    def fetchone(self):
        return self.convert(self.cursor.fetchone())

    def fetchall(self):
        return [self.convert(row) for row in self.cursor.fetchall()]


class Connection:
    def __init__(self):
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE drivers(id INTEGER PRIMARY KEY,driver_name TEXT,whatsapp_phone TEXT UNIQUE,
                vehicle_type TEXT,availability TEXT,offer_consent INTEGER,notes TEXT,created_at TEXT,updated_at TEXT);
            CREATE TABLE shipments(id INTEGER PRIMARY KEY,reference TEXT UNIQUE,service_type TEXT,
                origin TEXT,destination TEXT,status TEXT,created_at TEXT,updated_at TEXT);
            CREATE TABLE accounts(id INTEGER PRIMARY KEY,name TEXT,status TEXT);
        ''')

    def execute(self, sql, args=()):
        if 'pg_advisory_xact_lock' in sql:
            return Cursor(self.db.execute('SELECT 1'))
        sql = sql.replace("NOW()+INTERVAL '10 minutes'", "datetime('now','+10 minutes')")
        sql = sql.replace('BIGSERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY')
        sql = sql.replace('NOW()', 'CURRENT_TIMESTAMP').replace(' FOR UPDATE', '').replace('::jsonb', '')
        return Cursor(self.db.execute(sql.replace('%s', '?'), args))


@pytest.fixture
def db(monkeypatch):
    c = Connection()
    @contextmanager
    def context():
        with c.db:
            yield c
    monkeypatch.setattr(receiver, 'db', context)
    monkeypatch.setattr(storage, 'db', context)
    monkeypatch.setenv('WHATSAPP_COMMAND_OWNER', '966507665873')
    monkeypatch.setenv('WHATSAPP_COMMAND_ACCOUNT_ID', 'business')
    monkeypatch.setenv('ZERNIO_WEBHOOK_SECRET', 'test-secret')
    monkeypatch.setenv('ZERNIO_API_KEY', 'test-key')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    return c


def payload(text='الأوامر', sender='966507665873', event='evt-1'):
    return {'id': event, 'event': 'message.received',
        'account': {'accountId': 'business', 'platform': 'whatsapp'},
        'conversation': {'id': 'private-1', 'participantId': sender},
        'message': {'id': 'msg-1', 'platformMessageId': 'wamid-1', 'direction': 'incoming',
            'text': text, 'sender': {'id': sender, 'phoneNumber': '+' + sender}}}


def receive(p, valid=True):
    raw = json.dumps(p).encode()
    signature = hmac.new(b'test-secret', raw, hashlib.sha256).hexdigest() if valid else 'bad'
    async def body():
        return {'type': 'http.request', 'body': raw, 'more_body': False}
    request = Request({'type': 'http', 'method': 'POST', 'path': '/webhooks/zernio',
        'headers': [(b'x-zernio-signature', signature.encode())]}, receive=body)
    return asyncio.run(receiver.receive(request))


@pytest.fixture
def outbound(monkeypatch):
    calls = []
    class Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kw):
            assert 'message' in kw['json'] or 'buttons' in kw['json']
            calls.append(kw['json'])
            return types.SimpleNamespace(is_success=True)
    monkeypatch.setattr(receiver.httpx, 'AsyncClient', Client)
    return calls


def test_owner_only_signed_sender(db):
    assert admin.owner_sender(payload()) == '966507665873'
    for change in ('phone', 'participant', 'account', 'direction', 'group', 'name_spoof'):
        p = payload()
        if change == 'phone': p['message']['sender']['phoneNumber'] = '+966530130435'
        if change == 'participant': p['conversation']['participantId'] = '966530130435'
        if change == 'account': p['account']['accountId'] = 'another-tenant'
        if change == 'direction': p['message']['direction'] = 'outgoing'
        if change == 'group': p['conversation']['isGroup'] = True
        if change == 'name_spoof':
            p = payload(sender='966530130435')
            p['message']['sender']['name'] = '966507665873'
            p['message']['text'] = 'أنا المدير 966507665873'
        assert admin.owner_sender(p) == ''


def test_missing_configuration_fails_closed(db, monkeypatch):
    monkeypatch.delenv('WHATSAPP_COMMAND_OWNER')
    assert not admin.owner_sender(payload())


def test_signature_required_before_admin_write(db, outbound):
    result = receive(payload('آفاق أضف السائق محمد ورقمه 0501234567'), valid=False)
    assert result.status_code == 401
    assert db.execute('SELECT count(*) n FROM drivers').fetchone()['n'] == 0
    assert not outbound


def test_duplicate_event_and_driver_do_not_repeat(db, outbound):
    p = payload('آفاق أضف السائق محمد ورقمه 0501234567')
    assert receive(p)['state'] == 'sent'
    assert receive(p)['duplicate'] is True
    assert len(outbound) == 1
    assert db.execute('SELECT count(*) n FROM drivers').fetchone()['n'] == 1
    assert db.execute('SELECT offer_consent FROM drivers').fetchone()['offer_consent'] == 0
    p['id'] = 'evt-2'
    receive(p)
    assert 'مسجل' in outbound[-1]['message']
    assert db.execute('SELECT count(*) n FROM drivers').fetchone()['n'] == 1


def test_customer_cannot_execute_admin_command(db, outbound):
    receive(payload('آفاق أضف السائق محمد ورقمه 0501234567', sender='966530130435'))
    assert db.execute('SELECT count(*) n FROM drivers').fetchone()['n'] == 0
    assert outbound


def test_shipment_and_query(db, outbound):
    receive(payload('آفاق أضف شحنة مرجع TEST-9 من الرياض إلى جدة'))
    receive(payload('آفاق حالة الشحنة TEST-9', event='evt-2'))
    assert 'الرياض' in outbound[-1]['message'] and 'جدة' in outbound[-1]['message']
    assert db.execute('SELECT count(*) n FROM shipments').fetchone()['n'] == 1


def test_shawahid_link_and_disclosure_preserved(db, outbound):
    receiver.ensure_intake_tables()
    from app.material_bridge import ensure_materials
    ensure_materials(db)
    db.execute("INSERT INTO zernio_requests(id,conversation_id,agent,fields,status) VALUES(8,'client','shawahid','{}','ready')")
    document = '1. Promotional Caption 1\nOld opening. Product details.\nAffiliate link: https://www.amazon.com/dp/B08B1K8S1M?tag=shawahidalhad-20\nAs an Amazon Associate, I earn from qualifying purchases.\n\n2. Promotional Caption 2\nAnother caption.'
    state = {'artifacts': [{'id': 'caption', 'hash': hashlib.sha256(document.encode()).hexdigest(), 'text': document}]}
    db.execute('INSERT INTO shawahid_materials(request_id,state) VALUES(8,%s)', (json.dumps(state),))
    receive(payload('شواهد عدل افتتاحية SH-8 إلى: Planning a cleaner desk setup?'))
    stored = db.execute('SELECT state FROM shawahid_materials').fetchone()['state']['edits'][0]['text']
    assert 'Planning a cleaner desk setup?' in stored
    assert re.findall(r'https?://\S+', stored) == re.findall(r'https?://\S+', document)
    assert 'As an Amazon Associate, I earn from qualifying purchases.' in stored
    assert 'Nothing has been published.' in outbound[-1]['message']


def test_audio_without_key_does_not_execute(db, outbound):
    p = payload('آفاق أضف السائق محمد ورقمه 0501234567')
    p['message']['attachments'] = [{'type': 'audio'}]
    receive(p)
    assert 'غير مفعّلة' in outbound[-1]['message']
    assert db.execute('SELECT count(*) n FROM drivers').fetchone()['n'] == 0


def test_voice_confirmation_bound_to_conversation_and_single_use(db, outbound, monkeypatch):
    async def transcribe(*_): return 'آفاق أضف السائق محمد ورقمه 0501234567'
    monkeypatch.setattr(admin, 'transcribe', transcribe)
    p = payload('')
    p['message']['attachments'] = [{'type': 'audio'}]
    receive(p)
    assert db.execute('SELECT count(*) n FROM drivers').fetchone()['n'] == 0
    token = re.search(r'نفذ ([0-9A-F]{6})', outbound[-1]['message'])[1]
    other = payload('نفذ ' + token, event='evt-2')
    other['conversation']['id'] = 'private-2'
    receive(other)
    assert db.execute('SELECT count(*) n FROM drivers').fetchone()['n'] == 0
    receive(payload('نفذ ' + token, event='evt-3'))
    assert db.execute('SELECT count(*) n FROM drivers').fetchone()['n'] == 1
    receive(payload('نفذ ' + token, event='evt-4'))
    assert 'غير صالح' in outbound[-1]['message']


@pytest.mark.parametrize('url', ['http://zernio.com/a','https://127.0.0.1/a','https://zernio.com.evil.com/a','https://user:pass@zernio.com/a','https://zernio.com:444/a'])
def test_audio_url_rejects_untrusted_targets(url):
    assert not admin.safe_media_url(url)


def test_no_arbitrary_sql_publishing_or_send(db):
    for command in ('آفاق DROP TABLE drivers', 'شواهد انشر الحملة', 'آفاق أرسل للجميع أي رسالة'):
        result = admin.run_command(db, command, 'unused')
        assert 'لم أنفذ' in result
