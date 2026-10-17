"""Synthetic PostgreSQL tests: takeover fences and irreversible send boundaries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import threading
import uuid

import pytest
from app import whatsapp_agent_store as store
from app import whatsapp_takeover as takeover


@pytest.fixture
def db(monkeypatch):
    url = os.getenv('WHATSAPP_TAKEOVER_TEST_URL')
    if not url:
        pytest.skip('WHATSAPP_TAKEOVER_TEST_URL is required for PostgreSQL takeover tests')
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    schema = 'takeover_test_' + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))

    @contextmanager
    def factory():
        with psycopg.connect(url, row_factory=dict_row) as c:
            c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            c.execute("SET statement_timeout TO '8s'")
            yield c
    store.init_storage(db_factory=factory)
    takeover.init_storage(db_factory=factory)
    monkeypatch.setattr(store, 'conversation_admission', takeover.admission)
    monkeypatch.setattr(store, 'conversation_inspection', takeover._state)
    store.update_settings('a', mode='owner_pilot', pilot_sender='synthetic-sender', db_factory=factory)
    yield factory
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def pause(db, paused=True, generation=0, account='a', cid='c'):
    return takeover.set_paused(account, cid, paused, 'test-admin', generation,
                               sender='synthetic-sender', db_factory=db)


def enqueue(db, mid='m', account='a', cid='c'):
    with db() as c:
        return store.enqueue(c, account_id=account, conversation_id=cid,
            message_id=mid, event_id='e'+mid, sender='synthetic-sender', payload={'question': 'synthetic'})


def receipt(db, mid='m', event='event', cid='c'):
    return takeover.capture_inbound(account_id='a', conversation_id=cid,
        message_id=mid, event_id=event, sender='synthetic-sender', text='Synthetic inbound',
        attachment_count=1, db_factory=db)


def test_generation_fences_old_work_even_after_resume(db):
    assert takeover.authorization('a', 'c', 0, db_factory=db)
    assert not takeover.authorization('a', 'c', None, db_factory=db)
    assert pause(db)['generation'] == 1
    assert not takeover.authorization('a', 'c', 1, db_factory=db)
    assert pause(db, False, 1)['generation'] == 2
    assert not takeover.authorization('a', 'c', 0, db_factory=db)
    assert takeover.authorization('a', 'c', 2, db_factory=db)
    with pytest.raises(takeover.StateConflict):
        pause(db, generation=1)


@pytest.mark.parametrize('status', ['pending', 'processing', 'ready', 'sending', 'uncertain', 'sent'])
def test_cancel_only_reversible_jobs_and_never_replay(db, status):
    job = enqueue(db)
    other = enqueue(db, 'other', cid='other-conversation')
    with db() as c:
        c.execute('UPDATE whatsapp_agent_jobs SET status=%s WHERE id=%s', (status, job['id']))
        if status in ('ready', 'sending', 'uncertain', 'sent'):
            c.execute('''INSERT INTO whatsapp_agent_outbox(job_id,idempotency_key,status,updated_at)
                VALUES(%s,%s,%s,NOW())''', (job['id'], job['idempotency_key'], status))
    pause(db)
    pause(db, False, 1)
    with db() as c:
        row = c.execute('SELECT * FROM whatsapp_agent_jobs WHERE id=%s', (job['id'],)).fetchone()
        assert row['status'] == ('blocked' if status in ('pending', 'processing', 'ready') else status)
        assert c.execute('SELECT status FROM whatsapp_agent_jobs WHERE id=%s', (other['id'],)).fetchone()['status'] == 'pending'
        outbox = c.execute('SELECT status FROM whatsapp_agent_outbox WHERE job_id=%s', (job['id'],)).fetchone()
        if outbox:
            assert outbox['status'] == ('blocked' if status == 'ready' else status)
    assert enqueue(db)['status'] == row['status']


def test_paused_inbound_retained_deduplicated_after_resume(db):
    assert receipt(db) is False
    pause(db)
    assert receipt(db)
    assert receipt(db, event='event-alias')
    pause(db, False, 1)
    assert receipt(db, event='after-resume')
    assert receipt(db, mid='different-id', event='event-alias')
    assert not receipt(db, mid='fresh', event='fresh-event')
    with db() as c:
        rows = c.execute('SELECT * FROM whatsapp_takeover_receipts').fetchall()
        assert len(rows) == 1 and rows[0]['body'] == 'Synthetic inbound'
        assert rows[0]['attachment_count'] == 1
        assert c.execute('SELECT COUNT(*) AS n FROM whatsapp_agent_jobs').fetchone()['n'] == 0


def test_enqueue_captures_generation_and_blocks_raced_ingress(db):
    assert enqueue(db)['payload']['takeover_generation'] == 0
    pause(db)
    assert enqueue(db, 'during')['status'] == 'blocked'
    pause(db, False, 1)
    after = enqueue(db, 'after')
    assert after['status'] == 'pending'
    assert after['payload']['takeover_generation'] == 2
    assert enqueue(db, 'during')['status'] == 'blocked'


def test_pause_wins_before_send_and_does_not_touch_other_account(db):
    pause(db)
    with takeover.send_guard('a', 'c', 0, db_factory=db) as allowed:
        assert not allowed
    with takeover.send_guard('other-account', 'c', 0, db_factory=db) as allowed:
        assert allowed
    with takeover.send_guard('a', 'other-cid', 0, db_factory=db) as allowed:
        assert allowed


def test_inflight_send_serializes_pause_without_claiming_undo(db):
    entered = threading.Event()
    release = threading.Event()
    pause_started = threading.Event()

    def send():
        with takeover.send_guard('a', 'c', 0, db_factory=db) as allowed:
            assert allowed
            entered.set()
            assert release.wait(5)

    def change():
        pause_started.set()
        return pause(db)

    with ThreadPoolExecutor(2) as pool:
        sending = pool.submit(send)
        assert entered.wait(3)
        pausing = pool.submit(change)
        assert pause_started.wait(3)
        # The pause must not complete while the send owns the transaction fence.
        with pytest.raises(TimeoutError):
            pausing.result(timeout=.15)
        release.set()
        sending.result(timeout=3)
        assert pausing.result(timeout=3)['paused']
    with takeover.send_guard('a', 'c', 0, db_factory=db) as allowed:
        assert not allowed


def test_simultaneous_pause_has_one_winner_and_single_audit(db):
    barrier = threading.Barrier(2)
    def change():
        barrier.wait(timeout=3)
        try:
            return pause(db)['generation']
        except takeover.StateConflict:
            return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(change) for _ in range(2)]
        assert sorted([f.result(timeout=5) for f in futures], key=str) == [1, 'conflict']
    with db() as c:
        rows = c.execute('SELECT * FROM whatsapp_takeover_audit').fetchall()
        assert len(rows) == 1 and rows[0]['actor'] == 'test-admin'
        assert 'body' not in rows[0] and 'sender' not in rows[0]


def test_recipient_lookup_rejects_ambiguous_conversations(db):
    assert takeover.read_recipient_state('a', 'synthetic-sender', db_factory=db) is None
    pause(db)
    assert takeover.read_recipient_state('a', 'synthetic-sender', db_factory=db)['paused']
    pause(db, cid='second')
    with pytest.raises(takeover.StateConflict):
        takeover.read_recipient_state('a', 'synthetic-sender', db_factory=db)


def test_template_snapshot_before_first_pause_cannot_send_after_resume(db):
    assert takeover.read_recipient_state('a', 'synthetic-sender', db_factory=db) is None
    pause(db)
    pause(db, False, 1)
    with takeover.send_guard('a', 'recipient:synthetic-sender', 0,
                             sender='synthetic-sender', db_factory=db) as allowed:
        assert not allowed
    with takeover.send_guard('a', 'c', 2, sender='synthetic-sender', db_factory=db) as allowed:
        assert allowed


def test_template_inflight_first_pause_waits_recipient_fence(db):
    entered = threading.Event()
    release = threading.Event()
    def send():
        with takeover.send_guard('a', 'recipient:synthetic-sender', 0,
                                 sender='synthetic-sender', db_factory=db) as allowed:
            assert allowed
            entered.set()
            assert release.wait(5)
    with ThreadPoolExecutor(2) as pool:
        sending = pool.submit(send)
        assert entered.wait(3)
        pausing = pool.submit(pause, db)
        with pytest.raises(TimeoutError):
            pausing.result(timeout=.15)
        release.set()
        sending.result(timeout=3)
        assert pausing.result(timeout=3)['paused']


def test_stale_ingress_enqueue_blocked_even_after_resume(db):
    pause(db)
    pause(db, False, 1)
    with db() as c:
        job = store.enqueue(c, account_id='a', conversation_id='c', message_id='stale',
            event_id='stale-event', sender='synthetic-sender', payload={
                'takeover_expected_generation': 0, 'takeover_generation': 2})
    assert job['status'] == 'blocked'
    assert job['diagnostics']['reason'] == 'conversation_generation_changed'


@pytest.mark.parametrize('resumed', [False, True])
def test_legacy_claim_paused_or_stale_is_durable_and_cannot_replay(db, resumed):
    pause(db)
    if resumed:
        pause(db, False, 1)
    with db() as c:
        assert not store.claim_legacy(c, account_id='a', conversation_id='c', message_id='legacy',
            event_id='legacy-event', sender='synthetic-sender', takeover_expected_generation=0)
        row = c.execute("SELECT * FROM whatsapp_agent_jobs WHERE message_id='legacy'").fetchone()
        assert row['status'] == 'blocked'
        assert 'conversation_takeover' in row['diagnostics']
    if not resumed:
        pause(db, False, 1)
    with db() as c:
        assert not store.claim_legacy(c, account_id='a', conversation_id='c', message_id='legacy',
            event_id='legacy-retry', sender='synthetic-sender', takeover_expected_generation=2)
        assert store.claim_legacy(c, account_id='a', conversation_id='other', message_id='other',
            event_id='other-event', sender='synthetic-sender', takeover_expected_generation=0)


def test_ingress_generation_snapshot_is_atomic_with_receipt(db):
    kwargs = dict(account_id='a', conversation_id='c', message_id='snapshot',
                  event_id='snapshot-event', sender='synthetic-sender', return_state=True, db_factory=db)
    state = takeover.capture_inbound(**kwargs)
    assert state['generation'] == 0 and state['held'] is False
    pause(db)
    held = takeover.capture_inbound(**kwargs)
    assert held['generation'] == 1 and held['held'] is True
    pause(db, False, 1)
    duplicate = takeover.capture_inbound(**kwargs)
    assert duplicate['generation'] == 2 and duplicate['held'] is True


def test_lock_contention_is_bounded_and_does_not_change_state(db):
    import psycopg.errors
    import time
    entered = threading.Event()
    release = threading.Event()
    def hold():
        with takeover.send_guard('a', 'c', 0, sender='synthetic-sender', db_factory=db) as allowed:
            assert allowed
            entered.set()
            assert release.wait(6)
    with ThreadPoolExecutor(1) as pool:
        holding = pool.submit(hold)
        assert entered.wait(3)
        start = time.monotonic()
        try:
            with pytest.raises(psycopg.errors.LockNotAvailable):
                pause(db)
            assert time.monotonic() - start < 5
        finally:
            release.set()
        holding.result(timeout=3)
    state = takeover.read_state('a', 'c', db_factory=db)
    assert state['generation'] == 0 and state['paused'] is False
    with db() as c:
        assert c.execute('SELECT COUNT(*) AS n FROM whatsapp_takeover_audit').fetchone()['n'] == 0
    assert pause(db)['paused'] is True


def test_legacy_claim_does_not_hold_send_fence_inside_outer_transaction(db):
    # Legacy team handling can dispatch before its database transaction commits.
    # The generation snapshot and final send fence, rather than admission lock,
    # protect that dispatch without self-deadlocking a second DB connection.
    with db() as c:
        assert store.claim_legacy(c, account_id='a', conversation_id='c', message_id='nested',
            event_id='nested-event', sender='synthetic-sender', takeover_expected_generation=0)
        with takeover.send_guard('a', 'c', 0, sender='synthetic-sender', db_factory=db) as allowed:
            assert allowed
