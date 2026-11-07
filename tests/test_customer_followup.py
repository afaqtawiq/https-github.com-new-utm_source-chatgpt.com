"""Synthetic, offline evidence projection and SQLite query-contract tests.

SQLite tests exercise queries, bounds and failure recovery, not PostgreSQL locks,
row types, snapshot isolation, production permissions or provider completeness.
"""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import hashlib
from pathlib import Path
import sqlite3
import sys
import types

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app import customer_followup as f

NOW = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)


def record(source='directory:1', name='Synthetic Company', scope='account-one', **kw):
    return {'source': source, 'name': name, 'scope': scope, 'channel': 'whatsapp',
            'recipient': '+966500000001', **kw}


def event(source='job:1', direction='inbound', state='observed', **kw):
    return {**record(source=source), 'direction': direction, 'state': state, 'at': NOW, **kw}


@pytest.mark.parametrize('raw,expected', [('+966 50 000 0001', '+966500000001'),
    ('00966500000001', '+966500000001'), ('966500000001', '+966500000001'),
    ('0500000001', None), ('500000001x', None), ('555@c.us', None), ('', None)])
def test_full_phone_only(raw, expected):
    assert f.endpoint('whatsapp', raw) == expected


@pytest.mark.parametrize('raw,expected', [('Person@Example.com', 'person@example.com'),
    ('Person <person@example.com>', None), ('a@example.com,b@example.com', None),
    ('a@example.com\nsecret', None), ('', None)])
def test_plain_mailbox_only(raw, expected):
    assert f.endpoint('email', raw) == expected


def test_replay_is_idempotent_and_deduplicates_same_provider_id():
    first = event(provider_id='message-one')
    paused_copy = event(source='receipt:1', provider_id='message-one')
    data = f.project([record()], [first, first, paused_copy], now=NOW)
    assert len(data) == 1 and data[0]['inbound_observations'] == 1
    assert data == f.project([record()], [paused_copy, first], now=NOW)
    assert data[0]['human_reply'] == 'not_verified'


def test_scopes_directions_and_missing_ids_are_never_guessed():
    data = f.project([], [event(provider_id='same'), event(source='out:1', direction='outbound',
        state='accepted', provider_id='same'), event(scope='other', provider_id='same')], now=NOW)
    assert len(data) == 2
    assert data[0]['attempts'] + data[1]['attempts'] == 1
    assert sum(x['inbound_observations'] for x in data) == 2
    assert f.project([], [event(source='a'), event(source='b')])[0]['inbound_observations'] == 2


def test_conflicting_names_do_not_silently_rename_contact():
    item = f.project([record(name='Company One'), record(source='account:2', name='Company Two')], [])[0]
    assert item['names'] == ['Company One', 'Company Two']
    assert item['identity_conflict'] and item['next_action'] == 'identity_review'


def test_invalid_identities_remain_source_qualified():
    data = f.project([record(recipient='0500000001'), record(source='account:2', recipient='0500000001')], [])
    assert len(data) == 2 and all(x['invalid_identity'] for x in data)


def test_pause_and_marketing_optout_are_separate_and_win_action_priority():
    r = record()
    item = f.project([r, record(source='x', name='Other')], [], [{**r, 'paused': True}])[0]
    assert item['paused'] and not item['suppressed'] and item['next_action'] == 'paused'
    item = f.project([r], [], [{**r, 'paused': True, 'suppressed': True}])[0]
    assert item['next_action'] == 'suppressed'


@pytest.mark.parametrize('state', ['sent', 'accepted', 'delivered', 'read'])
def test_acceptance_never_claims_delivery_or_conversion(state):
    item = f.project([], [event(direction='outbound', state=f.send_state(state))])[0]
    assert item['attempts'] == 1 and item['delivery'] == 'not_verified'
    assert item['next_action'] == 'waiting_unverified'
    assert 'won' not in item


def test_failures_notices_and_conflicting_evidence():
    item = f.project([], [event(direction='notice', state='failed')])[0]
    assert item['inbound_observations'] == 0 and item['next_action'] == 'delivery_review'
    item = f.project([], [event(direction='outbound', state='accepted', provider_id='x'),
                         event(source='r:2', direction='outbound', state='failed', provider_id='x')])[0]
    assert item['attempts'] == 1 and item['evidence_conflict']


@pytest.mark.parametrize('status', ['draft', 'pending', 'blocked', 'cancelled', 'suppressed', 'skipped', 'cadence_skipped'])
def test_drafts_not_counted_as_attempts(status):
    item = f.project([], [event(direction='outbound', state=f.send_state(status))])[0]
    assert item['attempts'] == 0 and item['next_action'] == 'no_evidence'


def test_day_boundary_uses_riyadh_inclusive_exclusive():
    start, end = f.window(date(2026, 11, 7))
    assert start.isoformat() == '2026-11-06T21:00:00+00:00'
    assert end.isoformat() == '2026-11-07T21:00:00+00:00'
    contacts = f.project([], [event(at=start), event(source='two', at=end),
                             event(source='out', direction='outbound', state='accepted', at=start)])
    d = f.digest({'contacts': contacts, 'crm_followups': [], 'coverage': []}, date(2026, 11, 7))
    assert d['attempted_endpoints'] == d['inbound_endpoints'] == 1


def test_bad_or_naive_dates_are_not_assumed_utc():
    for value in ['bad', '2026-11-07', datetime(2026, 11, 7)]:
        assert f.stamp(value) is None


class SQLite:
    def __init__(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.create_function('md5', 1, lambda v: hashlib.md5(v.encode()).hexdigest())
        self.calls = []

    def execute(self, sql, args=()):
        self.calls.append((sql, args))
        if sql.startswith('SET '):
            return self.c.execute('SELECT 1')
        return self.c.execute(sql.replace('%s', '?'), args)


@pytest.fixture
def db():
    c = SQLite()
    c.c.executescript('''
      CREATE TABLE accounts(id INTEGER,name TEXT,phone TEXT,email TEXT);
      CREATE TABLE customer_directory(id INTEGER,company_name TEXT,phone TEXT,email TEXT);
      CREATE TABLE daily_prospects(id INTEGER,company_name TEXT,phone TEXT,email TEXT);
      CREATE TABLE sales_prospects(id INTEGER,company_name TEXT,recipient TEXT,mail_user_id INTEGER);
      CREATE TABLE customer_campaign_recipients(id INTEGER,channel TEXT,recipient TEXT,company_name TEXT,status TEXT,
        provider_message_id TEXT,sent_at TEXT,claimed_at TEXT,sender_user_id INTEGER);
      CREATE TABLE outbound_messages(id INTEGER,recipient TEXT,status TEXT,provider_message_id TEXT,sent_at TEXT,
        updated_at TEXT,mail_user_id INTEGER,channel TEXT);
      CREATE TABLE spacemail_inbox(id INTEGER,user_id INTEGER,duplicate_of INTEGER,sender_address TEXT,
        notice_kind TEXT,notice_recipient TEXT,message_id TEXT,imported_at TEXT);
      CREATE TABLE whatsapp_agent_jobs(id INTEGER,sender TEXT,message_id TEXT,created_at TEXT,account_id TEXT);
      CREATE TABLE whatsapp_agent_outbox(job_id INTEGER,status TEXT,provider_message_id TEXT,updated_at TEXT);
      CREATE TABLE whatsapp_takeover_receipts(id INTEGER,sender TEXT,message_id TEXT,received_at TEXT,account_id TEXT);
      CREATE TABLE whatsapp_inbox_drafts(token TEXT,recipient TEXT,state TEXT,provider_message_id TEXT,updated_at TEXT,account_id TEXT);
      CREATE TABLE whatsapp_conversation_takeovers(conversation_id TEXT,sender TEXT,paused BOOLEAN,account_id TEXT);
      CREATE TABLE marketing_suppressions(channel TEXT,recipient TEXT);
      CREATE TABLE opportunities(id INTEGER,account_id INTEGER,company_name TEXT,stage TEXT);
      CREATE TABLE sales_followups(id INTEGER,opportunity_id INTEGER,due_at TEXT,status TEXT);
      CREATE TABLE sales_outcomes(opportunity_id INTEGER,outcome TEXT,recorded_at TEXT);
    ''')
    yield c
    c.c.close()


def test_real_query_contract_scope_and_readonly_snapshot(db):
    at = NOW.isoformat()
    db.execute('INSERT INTO accounts VALUES(1,?,?,?)', ('Synthetic Co', '+966500000001', 'one@example.com'))
    db.execute('INSERT INTO outbound_messages VALUES(1,?,?,?,?,?,?,?)', ('one@example.com', 'sent', 'a', at, at, 7, 'email'))
    db.execute('INSERT INTO outbound_messages VALUES(2,?,?,?,?,?,?,?)', ('other@example.com', 'sent', 'b', at, at, 8, 'email'))
    db.execute('INSERT INTO whatsapp_agent_jobs VALUES(1,?,?,?,?)', ('+966500000001', 'wa1', at, 'account-one'))
    db.execute('INSERT INTO whatsapp_takeover_receipts VALUES(1,?,?,?,?)', ('+966500000001', 'wa1', at, 'account-one'))
    db.execute('INSERT INTO whatsapp_agent_jobs VALUES(2,?,?,?,?)', ('+966500000002', 'wa2', at, 'other-account'))
    db.execute('INSERT INTO spacemail_inbox VALUES(1,7,NULL,?,?,?,?,?)', ('one@example.com', 'none', None, 'm', at))
    db.execute('INSERT INTO spacemail_inbox VALUES(2,7,1,?,?,?,?,?)', ('one@example.com', 'none', None, 'm', at))
    db.c.commit()
    before = db.c.total_changes
    @contextmanager
    def factory():
        yield db
    data = f.snapshot(7, 'account-one', True, db_factory=factory, now=NOW)
    assert db.c.total_changes == before
    assert all(x['status'] == 'read' for x in data['coverage'])
    assert not data['complete'] and not data['external_actions']
    assert len(data['contacts']) == 2
    assert sum(x['inbound_observations'] for x in data['contacts']) == 2
    serialized = json.dumps(data, default=str)
    assert 'other@example.com' not in serialized and '+966500000002' not in serialized
    assert any(sql == 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY' for sql, _ in db.calls)


def test_permission_skips_mail_queries_and_denied_campaign_scope(db):
    db.execute('INSERT INTO customer_campaign_recipients VALUES(1,?,?,?,?,?,?,?,?)',
               ('email', 'secret@example.com', 'Secret', 'sent', 'id', NOW.isoformat(), None, 7))
    data = f.load_sources(db, 7, 'a', False)
    assert not data[1]
    assert not any('FROM spacemail_inbox' in sql for sql, _ in db.calls)
    assert next(x for x in data[-1] if x['source'] == 'outbound_messages')['status'] == 'not_authorized_or_configured'


def test_missing_table_recovers_and_limit_is_explicit(db, monkeypatch):
    db.c.execute('DROP TABLE customer_directory')
    db.c.executemany('INSERT INTO accounts VALUES(?,?,?,NULL)', [(n, 'Company', f'+96650000000{n}') for n in (1, 2, 3)])
    monkeypatch.setattr(f, 'LIMIT', 2)
    records, events, holds, crm, opp, coverage = f.load_sources(db, 7, 'a', True)
    assert len(records) == 2
    assert next(x for x in coverage if x['source'] == 'accounts')['status'] == 'truncated'
    assert next(x for x in coverage if x['source'] == 'customer_directory')['status'] == 'unavailable'
    assert next(x for x in coverage if x['source'] == 'opportunities')['status'] == 'read'


def test_campaigns_without_account_never_merge_into_current_account(db):
    db.execute('INSERT INTO customer_campaign_recipients VALUES(1,?,?,?,?,?,?,?,?)',
               ('whatsapp', '+966500000001', 'Co', 'sent', 'same', NOW.isoformat(), None, None))
    records, events, holds, *_ = f.load_sources(db, 7, 'a', True)
    events.append(event(scope='a', direction='outbound', state='accepted', provider_id='same'))
    contacts = f.project(records, events, holds)
    assert len(contacts) == 2
    assert {c['scope'] for c in contacts} == {'a', 'legacy_campaign_unscoped'}


def test_global_suppression_preserved_for_legacy_campaign_scope():
    contacts = f.project([], [event(scope='legacy_campaign_unscoped', direction='outbound', state='accepted')],
                         [{**record(scope='a'), 'suppressed': True}])
    assert all(c['suppressed'] and c['next_action'] == 'suppressed' for c in contacts)


@pytest.mark.parametrize('suppression_known,pauses_known', [(False, True), (True, False), (False, False)])
def test_unknown_safety_state_is_not_false(suppression_known, pauses_known):
    item = f.project([record()], [], suppression_known=suppression_known, pauses_known=pauses_known)[0]
    assert not item['safety_state_complete'] and item['next_action'] == 'safety_review'
    if not suppression_known:
        assert item['suppressed'] is None
    if not pauses_known:
        assert item['paused'] is None


def test_known_stop_survives_incomplete_safety_coverage_and_hold_order():
    rows = [{**record(scope='a'), 'suppressed': True}, {**record(scope='b'), 'paused': True}]
    data = f.project([], [], rows, suppression_known=False, pauses_known=False)
    assert len(data) == 2 and all(x['suppressed'] is True for x in data)
    assert all(x['next_action'] == 'suppressed' for x in data)


@pytest.mark.parametrize('missing', [True, False])
def test_snapshot_propagates_missing_or_truncated_safety(db, monkeypatch, missing):
    db.execute('INSERT INTO accounts VALUES(1,?,?,NULL)', ('Company', '+966500000001'))
    if missing:
        db.c.execute('DROP TABLE marketing_suppressions')
    else:
        monkeypatch.setattr(f, 'LIMIT', 1)
        db.c.executemany('INSERT INTO marketing_suppressions VALUES(?,?)',
                        [('whatsapp', '+966500000002'), ('whatsapp', '+966500000003')])
    @contextmanager
    def factory():
        yield db
    data = f.snapshot(7, 'a', True, db_factory=factory, now=NOW)
    item = next(x for x in data['contacts'] if x['recipient'] == '+966500000001')
    assert item['suppressed'] is None and item['next_action'] == 'safety_review'


def test_bounded_reads_keep_recent_evidence(db, monkeypatch):
    at = NOW.isoformat()
    db.c.executemany('INSERT INTO whatsapp_agent_jobs VALUES(?,?,?,?,?)',
                    [(i, '+966500000001', f'wa{i}', at, 'a') for i in range(1, 4)])
    monkeypatch.setattr(f, 'LIMIT', 2)
    events = f.load_sources(db, 7, 'a', True)[1]
    assert {r['source'] for r in events} == {'wa_job:2', 'wa_job:3'}


def test_manual_tokens_never_returned(db):
    secret = 'synthetic-random-manual-draft-token'
    db.execute('INSERT INTO whatsapp_inbox_drafts VALUES(?,?,?,?,?,?)',
               (secret, '+966500000001', 'sent', 'provider-one', NOW.isoformat(), 'a'))
    data = f.load_sources(db, 7, 'a', True)
    assert secret not in json.dumps(data, default=str)
    assert data[1][0]['source'] == 'wa_manual:' + hashlib.md5(secret.encode()).hexdigest()


def test_admin_authority_and_mail_permission(monkeypatch):
    state = {'session': None, 'mail': False}
    monkeypatch.setitem(sys.modules, 'app.storage', types.SimpleNamespace(get_session=lambda token: state['session']))
    monkeypatch.setitem(sys.modules, 'app.fine_permissions', types.SimpleNamespace(has_permission=lambda s, p: state['mail']))
    request = types.SimpleNamespace(cookies={})
    with pytest.raises(HTTPException) as err:
        f.authority(request)
    assert err.value.status_code == 401
    state['session'] = {'role': 'sales', 'user_id': 7}
    with pytest.raises(HTTPException) as err:
        f.authority(request)
    assert err.value.status_code == 403
    state['session']['role'] = 'admin'
    assert f.authority(request)[1] is False


def test_routes_escape_data_do_not_cache_and_have_no_mutation(monkeypatch):
    data = {'contacts': f.project([record(name='<script>alert(1)</script>')], []),
            'crm_followups': [], 'coverage': [], 'external_actions': False}
    monkeypatch.setattr(f, 'request_data', lambda r: data)
    app = FastAPI()
    app.include_router(f.router)
    with TestClient(app) as client:
        page = client.get('/customer-followup')
        assert page.status_code == 200 and '&lt;script&gt;' in page.text and '<script>' not in page.text
        assert page.headers['cache-control'] == 'no-store'
        assert client.get('/api/v7/customer-followup').json()['external_actions'] is False
        assert client.get('/api/v7/customer-followup/digest?day=2026-11-07').json()['timezone'] == 'Asia/Riyadh'
        assert client.post('/api/v7/customer-followup').status_code == 405


def test_source_has_no_provider_or_mutation_entrypoint():
    source = Path(f.__file__).read_text()
    assert 'INSERT INTO' not in source and 'UPDATE ' not in source and 'DELETE FROM' not in source
    assert 'import httpx' not in source and 'import requests' not in source
    assert '@router.post' not in source and 'register_worker' not in source
