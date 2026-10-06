"""Offline state-machine tests. SQLite only stands in for SQL, not row locking."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import sqlite3
import sys

import pytest
from app import whatsapp_agent_store as store

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
TEXT = 'Synthetic document for queue tests'
SHA = hashlib.sha256(TEXT.encode()).hexdigest()


class SQLiteConnection:
    dialect = 'sqlite'

    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, arguments=()):
        statement = statement.replace('BIGSERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
        return self.connection.execute(statement.replace('%s', '?'), arguments)


@pytest.fixture
def db():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')

    @contextmanager
    def factory():
        with connection:
            yield SQLiteConnection(connection)
    store.init_storage(db_factory=factory)
    yield factory
    connection.close()


def enable(db, account='a', sender='s'):
    return store.update_settings(account, mode='owner_pilot', pilot_sender=sender,
                                 approved_sha256=[SHA], db_factory=db, now=NOW)


def add(db, number=1, *, account='a', sender='s', conversation='c', event=None, attachment_count=1, now=NOW, payload=None):
    with db() as connection:
        return store.enqueue(connection, account_id=account, message_id='m'+str(number),
                             event_id=event or 'e'+str(number), sender=sender,
                             conversation_id=conversation, payload=payload if payload is not None else {'text': 'sanitized', 'question': 'What does the document say?',
                                 'question_allowed': True, 'question_kind': 'document_question', 'attachment_count': attachment_count,
                                 'attachments': [{'mime': 'application/pdf'}] if attachment_count else []}, now=now)


def claim(db, now=NOW):
    return store.claim_job(db_factory=db, now=now)


def checkpoint(db, job, **kwargs):
    return store.checkpoint_document(job['id'], job['lease_token'], text=TEXT,
        sha256=SHA, status='ok', db_factory=db, now=NOW, **kwargs)


def model(db, job):
    checkpoint(db, job)
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    return store.save_model(job['id'], job['lease_token'], reply_text='Generated from synthetic input',
                            diagnostics={'model_success': True}, db_factory=db, now=NOW)


def ready(db, job):
    return store.prepare_reply(job['id'], job['lease_token'], reply_text='Safe reply', db_factory=db, now=NOW)


def sent(db, job, *, generated=False):
    if generated:
        store.prepare_reply(job['id'], job['lease_token'], db_factory=db, now=NOW)
    else:
        ready(db, job)
    sending = store.claim_send(db_factory=db, now=NOW)
    assert sending['id'] == job['id']
    return store.finish_send(job['id'], sending['send_token'], status='sent',
                             provider_message_id='provider-'+str(job['id']), db_factory=db, now=NOW)


def test_import_never_imports_production_storage(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    before = sys.modules.get('app.storage')
    importlib.reload(store)
    assert sys.modules.get('app.storage') is before


def test_schema_initialization_is_repeatable_and_off_is_terminal(db):
    store.init_storage(db_factory=db)
    assert store.get_settings('a', db_factory=db)['mode'] == 'off'
    job = add(db)
    assert job['status'] == 'blocked'
    enable(db)
    assert claim(db) is None
    assert store.claim_send(db_factory=db, now=NOW) is None


def test_message_and_all_event_aliases_are_idempotent(db):
    enable(db)
    first = add(db)
    assert add(db)['id'] == first['id']
    assert add(db, event='second-event')['id'] == first['id']
    assert add(db, 99, event='second-event')['id'] == first['id']
    enable(db, 'other')
    assert add(db, account='other')['id'] != first['id']
    assert len(store.list_jobs(db_factory=db)) == 2
    assert first['idempotency_key'].startswith('wa-agent-')


def test_pilot_blocks_other_sender_without_holding_conversation(db):
    enable(db)
    assert add(db, sender='other')['status'] == 'blocked'
    assert claim(db) is None


def test_no_next_conversation_job_until_prior_terminal(db):
    enable(db)
    first, second = add(db), add(db, 2)
    active = claim(db)
    assert active['id'] == first['id']
    assert claim(db) is None
    ready(db, active)
    assert claim(db) is None
    sending = store.claim_send(db_factory=db, now=NOW)
    assert claim(db) is None
    store.finish_send(active['id'], sending['send_token'], status='sent', db_factory=db, now=NOW)
    assert claim(db)['id'] == second['id']


def test_independent_conversation_can_progress(db):
    enable(db)
    add(db)
    second = add(db, 2, conversation='other')
    assert claim(db)
    assert claim(db)['id'] == second['id']


def test_processing_retry_is_bounded_and_fences_stale_owner(db):
    enable(db)
    first = add(db)
    old = claim(db)
    newer = claim(db, NOW+timedelta(seconds=301))
    assert newer['read_attempts'] == 2
    assert newer['lease_token'] != old['lease_token']
    with pytest.raises(store.StateConflict):
        checkpoint(db, old)
    assert claim(db, NOW+timedelta(seconds=602))['read_attempts'] == 3
    assert claim(db, NOW+timedelta(seconds=903)) is None
    assert store.get_job(first['id'], db_factory=db)['status'] == 'failed'


def test_model_reservation_is_once_and_ambiguous_crash_terminal(db):
    enable(db)
    add(db)
    job = claim(db)
    checkpoint(db, job)
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert not store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert claim(db, NOW+timedelta(seconds=301)) is None
    row = store.get_job(job['id'], db_factory=db)
    assert row['status'] == 'uncertain'
    assert row['diagnostics']['reason'] == 'model_result_unknown'
    assert store.claim_send(db_factory=db, now=NOW+timedelta(seconds=302)) is None


def test_document_cannot_change_after_model_reservation(db):
    enable(db)
    add(db)
    job = claim(db)
    checkpoint(db, job)
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    with pytest.raises(store.StateConflict):
        checkpoint(db, job)
    with pytest.raises(store.StateConflict):
        ready(db, job)


def test_unapproved_pilot_hash_blocks_model(db):
    enable(db)
    store.update_settings('a', approved_sha256=[], db_factory=db, now=NOW)
    add(db)
    job = claim(db)
    checkpoint(db, job)
    assert not store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert store.get_job(job['id'], db_factory=db)['status'] == 'blocked'


def test_model_budget_counts_failed_or_uncertain_reservations(db):
    enable(db)
    for number in range(11):
        add(db, number, conversation=str(number))
        job = claim(db)
        checkpoint(db, job)
        assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW) is (number < 10)
        if number < 10:
            store.prepare_reply(job['id'], job['lease_token'], terminal_status='uncertain', db_factory=db, now=NOW)
    row = store.get_job(job['id'], db_factory=db)
    assert row['diagnostics']['reason'] == 'daily_model_budget_exhausted'


def test_saved_model_recovers_without_second_model_call(db):
    enable(db)
    add(db)
    job = claim(db)
    saved = model(db, job)
    assert saved['model_completed_at'] and saved['reply_text']
    assert claim(db, NOW+timedelta(seconds=301)) is None
    assert store.get_job(job['id'], db_factory=db)['status'] == 'ready'
    sending = store.claim_send(db_factory=db, now=NOW+timedelta(seconds=302))
    assert sending['reply_text'] == saved['reply_text']
    assert sending['idempotency_key'] == job['idempotency_key']


def test_sending_is_durable_before_network_and_never_reclaimed(db):
    enable(db)
    add(db)
    job = claim(db)
    ready(db, job)
    sending = store.claim_send(db_factory=db, now=NOW)
    assert store.get_job(job['id'], db_factory=db)['status'] == 'sending'
    assert store.claim_send(db_factory=db, now=NOW) is None
    assert store.claim_send(db_factory=db, now=NOW+timedelta(seconds=301)) is None
    assert store.get_job(job['id'], db_factory=db)['status'] == 'uncertain'
    with pytest.raises(store.StateConflict):
        store.finish_send(job['id'], sending['send_token'], status='sent', db_factory=db, now=NOW)


@pytest.mark.parametrize('status', ['sent', 'blocked', 'failed', 'uncertain'])
def test_send_outcomes_terminal_and_token_fenced(db, status):
    enable(db)
    add(db)
    job = claim(db)
    ready(db, job)
    sending = store.claim_send(db_factory=db, now=NOW)
    with pytest.raises(store.StateConflict):
        store.finish_send(job['id'], 'wrong', status=status, db_factory=db, now=NOW)
    store.finish_send(job['id'], sending['send_token'], status=status, db_factory=db, now=NOW)
    assert store.get_job(job['id'], db_factory=db)['status'] == status
    assert store.claim_send(db_factory=db, now=NOW+timedelta(days=1)) is None


def test_mode_off_blocks_pending_processing_ready_but_not_sending(db):
    enable(db)
    active = []
    for number in range(4):
        add(db, number, conversation=str(number))
    for _ in range(3):
        active.append(claim(db))
    ready(db, active[0])
    sending = store.claim_send(db_factory=db, now=NOW)
    ready(db, active[1])
    store.update_settings('a', mode='off', db_factory=db, now=NOW)
    assert [j['status'] for j in store.list_jobs(db_factory=db)] == ['blocked', 'blocked', 'blocked', 'sending']
    enable(db)
    assert claim(db) is None
    assert store.claim_send(db_factory=db, now=NOW) is None
    with pytest.raises(store.StateConflict):
        checkpoint(db, active[2])
    store.finish_send(sending['id'], sending['send_token'], status='sent', db_factory=db, now=NOW)


def test_context_requires_exact_scope_and_prior_sent_source(db):
    enable(db)
    add(db)
    job = claim(db)
    checkpoint(db, job)
    assert store.recent_context(account_id='a', sender='s', conversation_id='c', db_factory=db, now=NOW) is None
    sent(db, job)
    scope = dict(account_id='a', sender='s', conversation_id='c', db_factory=db, now=NOW)
    assert store.recent_context(**scope)['id'] == job['id']
    for key in ('account_id', 'sender', 'conversation_id'):
        assert store.recent_context(**{**scope, key: 'other'}) is None
    assert store.recent_context(**scope, before_job_id=job['id']) is None
    add(db, 2)
    following = claim(db)
    checkpoint(db, following, context_source_job_id=job['id'])
    assert store.get_job(following['id'], db_factory=db)['context_source_job_id'] == job['id']
    add(db, 3, conversation='other')
    unrelated = claim(db)
    with pytest.raises(store.StateConflict):
        checkpoint(db, unrelated, context_source_job_id=job['id'])


def test_routine_requires_actual_sent_document_followup_and_owner_receipt(db):
    enable(db)
    with pytest.raises(ValueError):
        store.update_settings('a', mode='routine', db_factory=db, now=NOW)
    add(db)
    first = claim(db)
    model(db, first)
    sent(db, first, generated=True)
    add(db, 2, attachment_count=0)
    second = claim(db)
    checkpoint(db, second, context_source_job_id=first['id'])
    assert store.reserve_model(second['id'], second['lease_token'], db_factory=db, now=NOW)
    store.save_model(second['id'], second['lease_token'], reply_text='Followup answer', diagnostics={'model_success': True}, db_factory=db, now=NOW)
    acceptance = {'owner_receipt_confirmed': True, 'document_job_id': first['id'], 'followup_job_id': second['id']}
    with pytest.raises(ValueError):
        store.update_settings('a', mode='routine', acceptance=acceptance, db_factory=db, now=NOW)
    sent(db, second, generated=True)
    assert store.update_settings('a', mode='routine', acceptance=acceptance, db_factory=db, now=NOW)['mode'] == 'routine'
    assert store.DAILY_MODEL_LIMITS == {'owner_pilot': 10, 'routine': 50}


@pytest.mark.parametrize('kwargs', [{'mode': 'automatic'}, {'mode': 'owner_pilot'},
    {'approved_sha256': ['wrong']}, {'approved_sha256': SHA},
    {'acceptance': {'expected_answer': 'do not store'}}])
def test_invalid_settings_fail_closed(db, kwargs):
    with pytest.raises(ValueError):
        store.update_settings('new', db_factory=db, now=NOW, **kwargs)


def test_context_ttl_does_not_extend_when_reused(db):
    enable(db)
    add(db)
    first = claim(db)
    checkpoint(db, first)
    sent(db, first)
    late = NOW+timedelta(hours=23)
    add(db, 2)
    following = claim(db, late)
    store.checkpoint_document(following['id'], following['lease_token'], text=TEXT, sha256=SHA,
        status='ok', context_source_job_id=first['id'], db_factory=db, now=late)
    row = store.get_job(following['id'], db_factory=db)
    assert row['document_checkpointed_at'] == store.get_job(first['id'], db_factory=db)['document_checkpointed_at']
    store.prepare_reply(following['id'], following['lease_token'], reply_text='Safe reply', db_factory=db, now=late)
    sending = store.claim_send(db_factory=db, now=late)
    store.finish_send(sending['id'], sending['send_token'], status='sent', db_factory=db, now=late)
    assert store.recent_context(account_id='a', sender='s', conversation_id='c',
        db_factory=db, now=NOW+timedelta(hours=25)) is None


def test_revoking_pilot_hash_before_send_blocks_saved_result(db):
    enable(db)
    add(db)
    job = claim(db)
    model(db, job)
    store.prepare_reply(job['id'], job['lease_token'], db_factory=db, now=NOW)
    store.update_settings('a', approved_sha256=[], db_factory=db, now=NOW)
    assert store.claim_send(db_factory=db, now=NOW) is None
    assert store.get_job(job['id'], db_factory=db)['status'] == 'blocked'


def test_pilot_model_requires_actual_safe_extraction(db):
    enable(db)
    add(db)
    job = claim(db)
    store.checkpoint_document(job['id'], job['lease_token'], text='', sha256=SHA,
        status='unavailable', db_factory=db, now=NOW)
    assert not store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)


@pytest.mark.parametrize('failure', ['document_model_failed', 'followup_model_failed', 'no_owner_receipt', 'unapproved_hash'])
def test_routine_rejects_partial_or_failed_acceptance_proof(db, failure):
    enable(db)
    add(db)
    document = claim(db)
    model(db, document)
    store.prepare_reply(document['id'], document['lease_token'],
        diagnostics={'model_success': failure != 'document_model_failed'}, db_factory=db, now=NOW)
    sending = store.claim_send(db_factory=db, now=NOW)
    store.finish_send(sending['id'], sending['send_token'], status='sent', db_factory=db, now=NOW)
    add(db, 2, attachment_count=0)
    followup = claim(db)
    checkpoint(db, followup, context_source_job_id=document['id'])
    assert store.reserve_model(followup['id'], followup['lease_token'], db_factory=db, now=NOW)
    store.save_model(followup['id'], followup['lease_token'], reply_text='Synthetic answer',
        diagnostics={'model_success': failure != 'followup_model_failed'}, db_factory=db, now=NOW)
    sent(db, followup, generated=True)
    acceptance = {'owner_receipt_confirmed': failure != 'no_owner_receipt',
                  'document_job_id': document['id'], 'followup_job_id': followup['id']}
    with pytest.raises(ValueError):
        store.update_settings('a', mode='routine', acceptance=acceptance,
            approved_sha256=[] if failure == 'unapproved_hash' else [SHA], db_factory=db, now=NOW)
    assert store.get_settings('a', db_factory=db)['mode'] == 'owner_pilot'


def test_routine_document_gate_and_text_only_reservation(db):
    enable(db)
    # The routine acceptance gate is exercised separately above. This fixture
    # isolates the post-activation guard without manufacturing model answers.
    with db() as connection:
        connection.execute("UPDATE whatsapp_agent_settings SET mode='routine' WHERE account_id='a'")
    add(db)
    document = claim(db)
    store.checkpoint_document(document['id'], document['lease_token'], text=TEXT,
        sha256='b'*64, status='ok', db_factory=db, now=NOW)
    assert not store.reserve_model(document['id'], document['lease_token'], db_factory=db, now=NOW)
    assert store.get_job(document['id'], db_factory=db)['diagnostics']['reason'] == 'document_provenance_not_approved'
    add(db, 2, payload=operations_payload())
    text_only = claim(db)
    store.checkpoint_document(text_only['id'], text_only['lease_token'], text='',
        sha256=None, status='none', db_factory=db, now=NOW)
    assert store.reserve_model(text_only['id'], text_only['lease_token'], db_factory=db, now=NOW)


def test_routine_revoked_document_provenance_never_sent(db):
    enable(db)
    with db() as connection:
        connection.execute("UPDATE whatsapp_agent_settings SET mode='routine' WHERE account_id='a'")
    add(db)
    job = claim(db)
    model(db, job)
    store.prepare_reply(job['id'], job['lease_token'], db_factory=db, now=NOW)
    with db() as connection:
        connection.execute("UPDATE whatsapp_agent_settings SET approved_sha256='[]' WHERE account_id='a'")
    assert store.claim_send(db_factory=db, now=NOW) is None
    assert store.get_job(job['id'], db_factory=db)['diagnostics']['reason'] == 'document_provenance_not_approved'


def test_model_guard_requires_existing_unexpired_reservation_and_is_read_only(db):
    enable(db)
    add(db)
    job = claim(db)
    checkpoint(db, job)
    assert not store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    before = store.get_job(job['id'], db_factory=db)
    assert store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert store.get_job(job['id'], db_factory=db) == before
    assert not store.model_authorized(job['id'], 'wrong', db_factory=db, now=NOW)
    assert not store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=NOW+timedelta(seconds=300))
    store.save_model(job['id'], job['lease_token'], reply_text='Known response', db_factory=db, now=NOW)
    assert not store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=NOW)


@pytest.mark.parametrize('change', ['off', 'sender', 'hash'])
def test_model_guard_rechecks_current_settings(db, change):
    enable(db)
    add(db)
    job = claim(db)
    checkpoint(db, job)
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    changes = {'off': {'mode': 'off'}, 'sender': {'pilot_sender': 'new-owner'}, 'hash': {'approved_sha256': []}}
    store.update_settings('a', db_factory=db, now=NOW, **changes[change])
    assert not store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=NOW)


@pytest.mark.parametrize('change', ['off', 'sender', 'hash', 'lease', 'wrong_token', 'terminal'])
def test_send_guard_rechecks_state_token_leases_and_settings(db, change):
    enable(db)
    add(db)
    job = claim(db)
    model(db, job)
    store.prepare_reply(job['id'], job['lease_token'], db_factory=db, now=NOW)
    sending = store.claim_send(db_factory=db, now=NOW)
    assert store.send_authorized(job['id'], sending['send_token'], db_factory=db, now=NOW)
    changes = {'off': {'mode': 'off'}, 'sender': {'pilot_sender': 'new-owner'}, 'hash': {'approved_sha256': []}}
    if change in changes:
        store.update_settings('a', db_factory=db, now=NOW, **changes[change])
    elif change == 'terminal':
        store.finish_send(job['id'], sending['send_token'], status='uncertain', db_factory=db, now=NOW)
    token = 'wrong' if change == 'wrong_token' else sending['send_token']
    now = NOW+timedelta(seconds=300) if change == 'lease' else NOW
    assert not store.send_authorized(job['id'], token, db_factory=db, now=now)
    # Guard reads must never recover the sending row or manufacture a retry.
    assert store.get_job(job['id'], db_factory=db)['status'] == ('uncertain' if change == 'terminal' else 'sending')


def test_each_guard_uses_one_joined_snapshot_without_row_locks(db):
    enable(db)
    add(db)
    job = claim(db)
    checkpoint(db, job)
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    statements = []

    @contextmanager
    def observed():
        with db() as connection:
            class ObservedConnection:
                def execute(self, statement, arguments=()):
                    statements.append(statement)
                    return connection.execute(statement, arguments)
            yield ObservedConnection()
    assert store.model_authorized(job['id'], job['lease_token'], db_factory=observed, now=NOW)
    assert len(statements) == 1 and 'JOIN whatsapp_agent_settings' in statements[0]
    assert 'FOR UPDATE' not in statements[0]
    store.save_model(job['id'], job['lease_token'], reply_text='Known result', db_factory=db, now=NOW)
    store.prepare_reply(job['id'], job['lease_token'], db_factory=db, now=NOW)
    sending = store.claim_send(db_factory=db, now=NOW)
    statements.clear()
    assert store.send_authorized(job['id'], sending['send_token'], db_factory=observed, now=NOW)
    assert len(statements) == 1 and 'JOIN whatsapp_agent_outbox' in statements[0]
    assert 'FOR UPDATE' not in statements[0]


def test_sanitized_no_model_failure_reply_can_pass_send_guard(db):
    enable(db)
    add(db)
    job = claim(db)
    store.checkpoint_document(job['id'], job['lease_token'], text='', sha256='b'*64,
        status='quarantined', db_factory=db, now=NOW)
    ready(db, job)
    sending = store.claim_send(db_factory=db, now=NOW)
    assert store.send_authorized(job['id'], sending['send_token'], db_factory=db, now=NOW)


def test_off_on_permanently_fences_claimed_send(db):
    enable(db)
    add(db)
    job = claim(db)
    ready(db, job)
    sending = store.claim_send(db_factory=db, now=NOW)
    generation = sending['authorization_generation']
    assert store.send_authorized(job['id'], sending['send_token'], db_factory=db, now=NOW)
    store.update_settings('a', mode='off', db_factory=db, now=NOW)
    enable(db)
    assert store.get_settings('a', db_factory=db)['authorization_generation'] > generation
    assert not store.send_authorized(job['id'], sending['send_token'], db_factory=db, now=NOW)
    # A request already initiated before the stop may record its known result;
    # it never receives permission for a second request.
    assert store.finish_send(job['id'], sending['send_token'], status='sent', db_factory=db, now=NOW)['status'] == 'sent'


def test_generation_changes_only_for_real_authorization_changes(db):
    first = enable(db)
    assert enable(db)['authorization_generation'] == first['authorization_generation']
    same = store.update_settings('a', accepted_by='owner', db_factory=db, now=NOW)
    assert same['authorization_generation'] == first['authorization_generation']
    changed = store.update_settings('a', approved_sha256=[SHA, 'b'*64], db_factory=db, now=NOW)
    assert changed['authorization_generation'] == first['authorization_generation']+1


def acceptance_pair(db):
    enable(db)
    add(db)
    document = claim(db)
    model(db, document)
    sent(db, document, generated=True)
    add(db, 2, attachment_count=0)
    followup = claim(db)
    checkpoint(db, followup, context_source_job_id=document['id'])
    assert store.reserve_model(followup['id'], followup['lease_token'], db_factory=db, now=NOW)
    store.save_model(followup['id'], followup['lease_token'], reply_text='Known followup',
        diagnostics={'model_success': True}, db_factory=db, now=NOW)
    sent(db, followup, generated=True)
    return document, followup, {'owner_receipt_confirmed': True,
        'document_job_id': document['id'], 'followup_job_id': followup['id']}


@pytest.mark.parametrize('change', ['new_sender', 'same_sender_new_generation', 'document_not_pdf', 'followup_has_attachment'])
def test_acceptance_bound_to_current_pilot_and_actual_message_shapes(db, change):
    document, followup, acceptance = acceptance_pair(db)
    if change == 'new_sender':
        store.update_settings('a', pilot_sender='pilot-b', db_factory=db, now=NOW)
    elif change == 'same_sender_new_generation':
        store.update_settings('a', mode='off', db_factory=db, now=NOW)
        enable(db)
    else:
        import json
        target = document if change == 'document_not_pdf' else followup
        payload = {'attachment_count': 1, 'attachments': [{'mime': 'image/png'}]}
        with db() as connection:
            connection.execute('UPDATE whatsapp_agent_jobs SET payload=%s WHERE id=%s',
                               (json.dumps(payload), target['id']))
    with pytest.raises(ValueError):
        store.update_settings('a', mode='routine', acceptance=acceptance, db_factory=db, now=NOW)


def test_old_job_cannot_reserve_paid_model(db):
    enable(db)
    add(db)
    late = NOW+timedelta(days=2)
    job = claim(db, late)
    store.checkpoint_document(job['id'], job['lease_token'], text=TEXT, sha256=SHA,
        status='ok', db_factory=db, now=late)
    assert not store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=late)
    assert store.get_job(job['id'], db_factory=db)['diagnostics']['reason'] == 'model_job_expired'


def test_recovered_context_checkpoint_cannot_bypass_freshness(db):
    enable(db)
    add(db)
    source = claim(db)
    checkpoint(db, source)
    sent(db, source)
    late = NOW+timedelta(hours=23)
    add(db, 2, attachment_count=0, now=late)
    followup = claim(db, late)
    store.checkpoint_document(followup['id'], followup['lease_token'], text=TEXT, sha256=SHA,
        status='ok', context_source_job_id=source['id'], db_factory=db, now=late)
    after_crash = NOW+timedelta(hours=25)
    reclaimed = claim(db, after_crash)
    assert reclaimed['document_checkpointed_at'] == source['created_at']
    assert not store.reserve_model(reclaimed['id'], reclaimed['lease_token'], db_factory=db, now=after_crash)
    assert store.get_job(reclaimed['id'], db_factory=db)['diagnostics']['reason'] == 'document_context_expired'


def test_guards_reject_context_expiring_inside_active_lease(db):
    enable(db)
    add(db)
    source = claim(db)
    checkpoint(db, source)
    sent(db, source)
    before_expiry = NOW+timedelta(days=1, seconds=-60)
    add(db, 2, attachment_count=0, now=before_expiry)
    followup = claim(db, before_expiry)
    store.checkpoint_document(followup['id'], followup['lease_token'], text=TEXT, sha256=SHA,
        status='ok', context_source_job_id=source['id'], db_factory=db, now=before_expiry)
    assert store.reserve_model(followup['id'], followup['lease_token'], db_factory=db, now=before_expiry)
    assert store.model_authorized(followup['id'], followup['lease_token'], db_factory=db, now=before_expiry)
    after_expiry = NOW+timedelta(days=1, seconds=1)
    assert not store.model_authorized(followup['id'], followup['lease_token'], db_factory=db, now=after_expiry)
    store.save_model(followup['id'], followup['lease_token'], reply_text='Saved before expiry', db_factory=db, now=before_expiry)
    store.prepare_reply(followup['id'], followup['lease_token'], db_factory=db, now=before_expiry)
    sending = store.claim_send(db_factory=db, now=before_expiry)
    assert store.send_authorized(sending['id'], sending['send_token'], db_factory=db, now=before_expiry)
    assert not store.send_authorized(sending['id'], sending['send_token'], db_factory=db, now=after_expiry)


def test_mutation_row_lock_order_is_settings_before_jobs(db):
    import re
    enable(db)
    add(db)
    job = claim(db)
    checkpoint(db, job)
    transactions = []

    @contextmanager
    def observed():
        statements = []
        transactions.append(statements)
        with db() as connection:
            class PostgreSQLLockTrace:
                def execute(self, statement, arguments=()):
                    statements.append(statement)
                    # Keep production lock syntax in the trace, then adapt only
                    # execution. PostgreSQL acceptance checks actual concurrency.
                    statement = re.sub(r' FOR UPDATE(?: OF [a-z,]+)?(?: SKIP LOCKED)?', '', statement)
                    return connection.execute(statement, arguments)
            yield PostgreSQLLockTrace()
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=observed, now=NOW)
    locks = [statement for statement in transactions[0] if 'FOR UPDATE' in statement]
    assert 'whatsapp_agent_settings' in locks[0]
    assert 'whatsapp_agent_jobs' in locks[1]
    store.save_model(job['id'], job['lease_token'], reply_text='Known reply', db_factory=db, now=NOW)
    store.prepare_reply(job['id'], job['lease_token'], db_factory=db, now=NOW)
    transactions.clear()
    assert store.claim_send(db_factory=observed, now=NOW)
    assert len(transactions) == 2  # recovery locks released before settings locks
    locks = [statement for statement in transactions[1] if 'FOR UPDATE' in statement]
    assert 'whatsapp_agent_settings' in locks[0]
    assert 'whatsapp_agent_jobs' in locks[1] and 'whatsapp_agent_outbox' in locks[1]


def test_legacy_schema_migration_fences_unversioned_work(db):
    enable(db)
    job = add(db)
    with db() as connection:
        connection.execute('ALTER TABLE whatsapp_agent_settings DROP COLUMN authorization_generation')
        connection.execute('ALTER TABLE whatsapp_agent_jobs DROP COLUMN authorization_generation')
    store.init_storage(db_factory=db)
    settings = store.get_settings('a', db_factory=db)
    migrated = store.get_job(job['id'], db_factory=db)
    assert settings['authorization_generation'] == 1
    assert migrated['authorization_generation'] == 0 and migrated['status'] == 'blocked'
    store.init_storage(db_factory=db)
    assert claim(db) is None


def test_model_guard_rechecks_job_age_even_with_a_live_reservation(db):
    enable(db)
    add(db)
    before_expiry = NOW+timedelta(days=1, seconds=-60)
    job = claim(db, before_expiry)
    store.checkpoint_document(job['id'], job['lease_token'], text=TEXT, sha256=SHA,
        status='ok', db_factory=db, now=before_expiry)
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=before_expiry)
    assert store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=before_expiry)
    assert not store.model_authorized(job['id'], job['lease_token'], db_factory=db,
        now=NOW+timedelta(days=1, seconds=1))


def legacy(db, number=1, *, account='a', event=None):
    with db() as connection:
        return store.claim_legacy(connection, account_id=account, message_id='m'+str(number),
            event_id=event or 'e'+str(number), sender='s', conversation_id='c', now=NOW)


def test_legacy_claim_is_identity_only_terminal_tombstone(db):
    assert legacy(db)
    rows = store.list_jobs(db_factory=db)
    assert len(rows) == 1
    tombstone = rows[0]
    assert tombstone['status'] == 'blocked' and tombstone['read_attempts'] == 0
    assert tombstone['payload'] == {'legacy_owned': True}
    assert tombstone['diagnostics'] == {'reason': 'legacy_lane_owned'}
    assert not tombstone['document_text'] and not tombstone['reply_text']
    assert store.get_outbox(tombstone['id'], db_factory=db) is None
    assert not legacy(db) and not legacy(db, event='alias')
    enable(db)
    assert add(db, event='durable-alias')['id'] == tombstone['id']
    assert claim(db) is None and store.claim_send(db_factory=db, now=NOW) is None
    assert store.get_job(tombstone['id'], db_factory=db) == tombstone


@pytest.mark.parametrize('phase', ['pending', 'processing', 'ready', 'sending', 'sent'])
def test_legacy_cannot_overwrite_any_durable_owner(db, phase):
    enable(db)
    job = add(db)
    if phase != 'pending':
        job = claim(db)
    if phase in ('ready', 'sending', 'sent'):
        ready(db, job)
    if phase in ('sending', 'sent'):
        sending = store.claim_send(db_factory=db, now=NOW)
    if phase == 'sent':
        store.finish_send(job['id'], sending['send_token'], status='sent', db_factory=db, now=NOW)
    before = store.get_job(job['id'], db_factory=db)
    assert not legacy(db, event='legacy-alias')
    assert store.get_job(job['id'], db_factory=db) == before
    assert len(store.list_jobs(db_factory=db)) == 1
    assert not legacy(db, 999, event='legacy-alias')
    assert len(store.list_jobs(db_factory=db)) == 1


def test_legacy_event_identity_and_account_scope(db):
    assert legacy(db)
    assert not legacy(db, 2, event='e1')
    assert legacy(db, account='other')
    assert len(store.list_jobs(db_factory=db)) == 2


def test_legacy_claim_rolls_back_with_receiver_transaction(db):
    with pytest.raises(RuntimeError):
        with db() as connection:
            assert store.claim_legacy(connection, account_id='a', message_id='m1', event_id='e1',
                sender='s', conversation_id='c', now=NOW)
            raise RuntimeError('receiver event claim failed')
    assert store.list_jobs(db_factory=db) == []
    assert legacy(db)


def test_concurrent_callbacks_choose_only_one_lane():
    from concurrent.futures import ThreadPoolExecutor
    from threading import RLock
    connection = sqlite3.connect(':memory:', check_same_thread=False)
    connection.row_factory = sqlite3.Row
    lock = RLock()

    @contextmanager
    def factory():
        # SQLite adapter serializes transactions; the PG acceptance script tests
        # actual advisory/account row-lock arbitration between concurrent callers.
        with lock, connection:
            yield SQLiteConnection(connection)
    try:
        store.init_storage(db_factory=factory)
        enable(factory)
        def callback(number):
            if number % 2:
                return legacy(factory, event='event-'+str(number))
            return add(factory, event='event-'+str(number))
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(callback, range(12)))
        rows = store.list_jobs(db_factory=factory)
        assert len(rows) == 1
        legacy_wins = sum(result is True for result in results)
        assert legacy_wins == int(rows[0]['payload'] == {'legacy_owned': True})
        assert rows[0]['status'] == ('blocked' if legacy_wins else 'pending')
    finally:
        connection.close()


def test_settings_expected_generation_fences_stale_form_without_mutation(db):
    initial = enable(db)
    expected = initial['authorization_generation']
    changed = store.update_settings('a', pilot_sender='pilot-b', expected_generation=expected,
        db_factory=db, now=NOW)
    assert changed['authorization_generation'] == expected+1
    before = store.get_settings('a', db_factory=db)
    with pytest.raises(store.StateConflict):
        store.update_settings('a', mode='off', accepted_by='stale-tab',
            expected_generation=expected, db_factory=db, now=NOW)
    assert store.get_settings('a', db_factory=db) == before


def test_stale_generation_detects_off_on_even_when_values_match(db):
    initial = enable(db)
    store.update_settings('a', mode='off', db_factory=db, now=NOW)
    current = enable(db)
    with pytest.raises(store.StateConflict):
        store.update_settings('a', mode='off', expected_generation=initial['authorization_generation'],
            db_factory=db, now=NOW)
    assert store.get_settings('a', db_factory=db) == current


def test_concurrent_settings_forms_only_one_generation_can_win():
    from concurrent.futures import ThreadPoolExecutor
    from threading import RLock
    connection = sqlite3.connect(':memory:', check_same_thread=False)
    connection.row_factory = sqlite3.Row
    lock = RLock()

    @contextmanager
    def factory():
        with lock, connection:
            yield SQLiteConnection(connection)
    try:
        store.init_storage(db_factory=factory)
        expected = enable(factory)['authorization_generation']
        def submit(number):
            try:
                return store.update_settings('a', pilot_sender='pilot-'+str(number),
                    expected_generation=expected, db_factory=factory, now=NOW)
            except store.StateConflict:
                return 'stale'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, range(2)))
        assert results.count('stale') == 1
        assert store.get_settings('a', db_factory=factory)['authorization_generation'] == expected+1
    finally:
        connection.close()


def operations_payload(**changes):
    return {'question': 'How can I organize a shipment handover?', 'question_allowed': True,
            'question_kind': 'operations', 'attachment_count': 0, 'attachments': [], **changes}


def ordinary_job(db, number=1, *, payload=None, now=NOW, sender='s'):
    add(db, number, sender=sender, payload=operations_payload() if payload is None else payload, now=now)
    job = claim(db, now)
    if job:
        store.checkpoint_document(job['id'], job['lease_token'], text='', sha256=None,
            status='none', db_factory=db, now=now)
    return job


def test_pilot_screened_operations_text_needs_no_pdf_provenance(db):
    enable(db)
    store.update_settings('a', approved_sha256=[], db_factory=db, now=NOW)
    job = ordinary_job(db)
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert not store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    store.save_model(job['id'], job['lease_token'], reply_text='A screened business response',
        diagnostics={'model_success': True}, db_factory=db, now=NOW)
    store.prepare_reply(job['id'], job['lease_token'], db_factory=db, now=NOW)
    sending = store.claim_send(db_factory=db, now=NOW)
    assert store.send_authorized(job['id'], sending['send_token'], db_factory=db, now=NOW)
    store.finish_send(job['id'], sending['send_token'], status='sent', db_factory=db, now=NOW)
    assert store.get_job(job['id'], db_factory=db)['document_status'] == 'none'
    assert store.recent_context(account_id='a', sender='s', conversation_id='c', db_factory=db, now=NOW) is None
    assert not store.send_authorized(job['id'], sending['send_token'], db_factory=db, now=NOW)


@pytest.mark.parametrize('changes', [
    {'question_allowed': False}, {'question_allowed': 'true'}, {'question_kind': 'unknown'},
    {'question_kind': 'unrecognized_kind'}, {'question': ''}, {'question': None},
    {'attachment_count': 1}, {'attachment_count': False}, {'attachment_count': '0'},
    {'attachments': [{'mime': 'application/pdf'}]}, {'attachments': None},
])
def test_pilot_ordinary_text_rejects_unscreened_or_document_like_payload(db, changes):
    enable(db)
    job = ordinary_job(db, payload=operations_payload(**changes))
    assert not store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert not store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=NOW)
    row = store.get_job(job['id'], db_factory=db)
    assert row['status'] == 'blocked' and row['model_started_at'] is None


@pytest.mark.parametrize('checkpoint_values', [
    {'text': '', 'sha256': None, 'status': 'unavailable'},
    {'text': '', 'sha256': SHA, 'status': 'none'},
    {'text': TEXT, 'sha256': 'b'*64, 'status': 'ok'},
])
def test_ordinary_payload_cannot_bypass_document_provenance(db, checkpoint_values):
    enable(db)
    job = ordinary_job(db)
    store.checkpoint_document(job['id'], job['lease_token'], db_factory=db, now=NOW, **checkpoint_values)
    assert not store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)


def test_ordinary_text_guards_recheck_screened_scope(db):
    import json
    enable(db)
    job = ordinary_job(db)
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    with db() as connection:
        connection.execute('UPDATE whatsapp_agent_jobs SET payload=%s WHERE id=%s',
            (json.dumps(operations_payload(question_allowed=False)), job['id']))
    assert not store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=NOW)
    store.save_model(job['id'], job['lease_token'], reply_text='Previously returned response', db_factory=db, now=NOW)
    store.prepare_reply(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert store.claim_send(db_factory=db, now=NOW) is None
    assert store.get_job(job['id'], db_factory=db)['status'] == 'blocked'


def test_pilot_ordinary_text_keeps_sender_budget_and_uncertain_fencing(db):
    enable(db)
    assert ordinary_job(db, 100, sender='other') is None
    for number in range(11):
        job = ordinary_job(db, number)
        reserved = store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
        assert reserved is (number < 10)
        if reserved:
            store.prepare_reply(job['id'], job['lease_token'], terminal_status='uncertain', db_factory=db, now=NOW)
        assert not store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert store.get_job(job['id'], db_factory=db)['diagnostics']['reason'] == 'daily_model_budget_exhausted'


def test_pilot_ordinary_text_stop_and_crash_do_not_reauthorize(db):
    enable(db)
    first = ordinary_job(db)
    assert store.reserve_model(first['id'], first['lease_token'], db_factory=db, now=NOW)
    assert claim(db, NOW+timedelta(seconds=301)) is None
    assert store.get_job(first['id'], db_factory=db)['status'] == 'uncertain'
    assert not store.model_authorized(first['id'], first['lease_token'], db_factory=db, now=NOW)
    second = ordinary_job(db, 2)
    assert store.reserve_model(second['id'], second['lease_token'], db_factory=db, now=NOW)
    store.save_model(second['id'], second['lease_token'], reply_text='Business response', db_factory=db, now=NOW)
    store.prepare_reply(second['id'], second['lease_token'], db_factory=db, now=NOW)
    sending = store.claim_send(db_factory=db, now=NOW)
    assert store.send_authorized(second['id'], sending['send_token'], db_factory=db, now=NOW)
    store.update_settings('a', mode='off', db_factory=db, now=NOW)
    enable(db)
    assert not store.send_authorized(second['id'], sending['send_token'], db_factory=db, now=NOW)
    assert store.claim_send(db_factory=db, now=NOW+timedelta(seconds=301)) is None
    assert store.get_job(second['id'], db_factory=db)['status'] == 'uncertain'


def test_ordinary_text_success_never_qualifies_as_pdf_acceptance(db):
    enable(db)
    jobs = []
    for number in range(2):
        job = ordinary_job(db, number)
        assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
        store.save_model(job['id'], job['lease_token'], reply_text='Known business response',
            diagnostics={'model_success': True}, db_factory=db, now=NOW)
        store.prepare_reply(job['id'], job['lease_token'], db_factory=db, now=NOW)
        sending = store.claim_send(db_factory=db, now=NOW)
        store.finish_send(job['id'], sending['send_token'], status='sent', db_factory=db, now=NOW)
        jobs.append(job)
    with pytest.raises(ValueError):
        store.update_settings('a', mode='routine', acceptance={'owner_receipt_confirmed': True,
            'document_job_id': jobs[0]['id'], 'followup_job_id': jobs[1]['id']}, db_factory=db, now=NOW)


def history_exchange(db, number, *, question='Remember the loading sequence', reply='Loading order recorded',
                     account='a', sender='s', conversation='c', now=NOW, status='sent', payload_changes=None):
    payload = operations_payload(question=question, question_kind='conversation', **(payload_changes or {}))
    add(db, number, account=account, sender=sender, conversation=conversation, payload=payload, now=now)
    job = store.claim_job(account_id=account, db_factory=db, now=now)
    store.checkpoint_document(job['id'], job['lease_token'], text='', sha256=None,
        status='none', db_factory=db, now=now)
    store.prepare_reply(job['id'], job['lease_token'], reply_text=reply, db_factory=db, now=now)
    sending = store.claim_send(account_id=account, db_factory=db, now=now)
    store.finish_send(job['id'], sending['send_token'], status=status, db_factory=db, now=now)
    return store.get_job(job['id'], db_factory=db)


def history_target(db, number=99, *, account='a', sender='s', conversation='c', now=NOW):
    add(db, number, account=account, sender=sender, conversation=conversation,
        payload=operations_payload(question='What did we just discuss?', question_kind='conversation'), now=now)
    return store.claim_job(account_id=account, db_factory=db, now=now)


def history(db, target, **kwargs):
    return store.recent_exchanges(account_id=target['account_id'], sender=target['sender'],
        conversation_id=target['conversation_id'], before_job_id=target['id'], db_factory=db, now=NOW, **kwargs)


def test_conversation_kind_uses_same_pilot_reservation_and_final_guards(db):
    enable(db)
    job = ordinary_job(db, payload=operations_payload(question_kind='conversation'))
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=NOW)
    store.save_model(job['id'], job['lease_token'], reply_text='A contextual reply', db_factory=db, now=NOW)
    store.prepare_reply(job['id'], job['lease_token'], db_factory=db, now=NOW)
    sending = store.claim_send(db_factory=db, now=NOW)
    assert store.send_authorized(job['id'], sending['send_token'], db_factory=db, now=NOW)
    store.update_settings('a', mode='off', db_factory=db, now=NOW)
    enable(db)
    assert not store.send_authorized(job['id'], sending['send_token'], db_factory=db, now=NOW)


def test_recent_exchanges_returns_actual_minimal_chronological_pairs(db):
    enable(db)
    first = history_exchange(db, 1, question='First business question', reply='First actual answer')
    second = history_exchange(db, 2, question='Second business question', reply='Second actual answer')
    target = history_target(db)
    rows = history(db, target)
    assert [row['job_id'] for row in rows] == [first['id'], second['id']]
    assert rows[0]['question'] == 'First business question' and rows[0]['reply_text'] == 'First actual answer'
    assert set(rows[0]) == {'job_id','account_id','sender','conversation_id','authorization_generation',
                           'status','created_at','completed_at','question','reply_text'}
    assert rows[0]['completed_at'] == NOW.isoformat()
    assert all(row['status'] == 'sent' and row['authorization_generation'] == target['authorization_generation'] for row in rows)
    assert history(db, target, limit=1)[0]['job_id'] == second['id']


@pytest.mark.parametrize('scope', [{'account_id':'other'}, {'sender':'other'}, {'conversation_id':'other'}])
def test_recent_exchanges_rejects_cross_scope_target(db, scope):
    enable(db)
    history_exchange(db, 1)
    target = history_target(db)
    args = {'account_id':'a','sender':'s','conversation_id':'c', **scope}
    assert store.recent_exchanges(**args, before_job_id=target['id'], db_factory=db, now=NOW) == []


def test_recent_exchanges_ignores_other_conversations_and_generations(db):
    enable(db)
    history_exchange(db, 1, conversation='other')
    own = history_exchange(db, 2)
    target = history_target(db)
    assert [row['job_id'] for row in history(db, target)] == [own['id']]
    store.update_settings('a', mode='off', db_factory=db, now=NOW)
    enable(db)
    assert history(db, target) == []
    new_target = history_target(db, 100)
    assert history(db, new_target) == []


@pytest.mark.parametrize('status', ['blocked','failed','uncertain'])
def test_recent_exchanges_excludes_non_sent_outcomes(db, status):
    enable(db)
    history_exchange(db, 1, status=status)
    target = history_target(db)
    assert history(db, target) == []


@pytest.mark.parametrize('change', [
    {'question_allowed':False}, {'question_allowed':'true'}, {'attachment_count':1},
    {'attachments':[{'mime':'application/pdf'}]},
])
def test_recent_exchanges_excludes_blocked_question_and_attachment_shapes(db, change):
    enable(db)
    history_exchange(db, 1, payload_changes=change)
    target = history_target(db)
    assert history(db, target) == []


def test_recent_exchanges_excludes_document_derived_pairs(db):
    enable(db)
    add(db)
    doc = claim(db)
    model(db, doc)
    sent(db, doc, generated=True)
    target = history_target(db)
    assert history(db, target) == []


def test_recent_exchanges_validates_target_and_pair_times(db):
    enable(db)
    old = NOW-timedelta(days=1, seconds=1)
    history_exchange(db, 1, now=old)
    fresh = history_exchange(db, 2)
    target = history_target(db)
    assert [row['job_id'] for row in history(db, target, max_age_seconds=999999)] == [fresh['id']]
    assert store.recent_exchanges(account_id='a',sender='s',conversation_id='c',before_job_id=target['id'],
        db_factory=db,now=NOW+timedelta(seconds=300)) == []
    with db() as connection:
        connection.execute("UPDATE whatsapp_agent_jobs SET status='ready' WHERE id=%s",(target['id'],))
    assert history(db, target) == []


def test_recent_exchanges_excludes_future_or_incomplete_sent_records(db):
    enable(db)
    first = history_exchange(db, 1)
    second = history_exchange(db, 2)
    target = history_target(db)
    with db() as connection:
        connection.execute('UPDATE whatsapp_agent_jobs SET completed_at=NULL WHERE id=%s',(first['id'],))
        connection.execute('UPDATE whatsapp_agent_jobs SET completed_at=%s WHERE id=%s',
                           ((NOW+timedelta(seconds=1)).isoformat(),second['id']))
    assert history(db, target) == []


def test_recent_exchanges_whole_pair_count_and_total_caps(db):
    enable(db)
    for number in range(6):
        history_exchange(db, number, question='q'+str(number), reply='r'+str(number))
    target = history_target(db)
    rows = history(db, target, limit=999)
    assert [row['question'] for row in rows] == ['q2','q3','q4','q5']
    store.prepare_reply(target['id'],target['lease_token'],terminal_status='blocked',db_factory=db,now=NOW)
    for number in range(6,10):
        history_exchange(db, number, question='q'*1500, reply='r'*2500)
    target = history_target(db, 100)
    rows = history(db, target)
    assert len(rows) == 2 and sum(len(row['question'])+len(row['reply_text']) for row in rows) == 8000
    assert all(row['question']=='q'*1500 and row['reply_text']=='r'*2500 for row in rows)


@pytest.mark.parametrize('question,reply', [
    ('q'*1501, 'actual reply'), ('actual question', 'r'*2501),
    ('Read https://example.invalid/private?token=secret', 'actual reply'),
    ('actual question', 'Use provider.example.invalid/path'), ('', 'actual reply'),
])
def test_recent_exchanges_skips_oversized_urls_or_empty_pairs(db, question, reply):
    enable(db)
    history_exchange(db, 1, question=question, reply=reply)
    target = history_target(db)
    assert history(db, target) == []


def test_recent_context_keeps_actual_pdf_root_across_followup_and_harmless_turn(db):
    enable(db)
    add(db)
    original = claim(db)
    model(db, original)
    sent(db, original, generated=True)
    add(db, 2, attachment_count=0)
    inherited = claim(db)
    checkpoint(db, inherited, context_source_job_id=original['id'])
    sent(db, inherited)
    history_exchange(db, 3, question='Thanks', reply='You are welcome')
    target = history_target(db)
    root = store.recent_context(account_id='a',sender='s',conversation_id='c',
        before_job_id=target['id'],db_factory=db,now=NOW)
    assert root['id'] == original['id'] and root['context_source_job_id'] is None
    checkpoint(db, target, context_source_job_id=root['id'])
    assert store.get_job(target['id'],db_factory=db)['context_source_job_id'] == original['id']
    assert store.get_job(target['id'],db_factory=db)['document_checkpointed_at'] == root['document_checkpointed_at']


def test_context_checkpoint_rejects_inherited_non_root_source(db):
    enable(db)
    add(db)
    root = claim(db)
    checkpoint(db, root)
    sent(db, root)
    add(db, 2, attachment_count=0)
    inherited = claim(db)
    checkpoint(db, inherited, context_source_job_id=root['id'])
    sent(db, inherited)
    target = history_target(db)
    with pytest.raises(store.StateConflict):
        checkpoint(db, target, context_source_job_id=inherited['id'])


def test_recent_context_requires_actual_pdf_shape_and_current_hash(db):
    enable(db)
    add(db, payload=operations_payload())
    false_root = claim(db)
    checkpoint(db, false_root)
    sent(db, false_root)
    assert store.recent_context(account_id='a',sender='s',conversation_id='c',db_factory=db,now=NOW) is None
    add(db, 2)
    pdf = claim(db)
    checkpoint(db, pdf)
    sent(db, pdf)
    assert store.recent_context(account_id='a',sender='s',conversation_id='c',db_factory=db,now=NOW)['id'] == pdf['id']
    store.update_settings('a',approved_sha256=[],db_factory=db,now=NOW)
    assert store.recent_context(account_id='a',sender='s',conversation_id='c',db_factory=db,now=NOW) is None


def test_recent_context_separate_pdf_approval_survives_routine_activation(db):
    document, followup, acceptance = acceptance_pair(db)
    store.update_settings('a',mode='routine',acceptance=acceptance,db_factory=db,now=NOW)
    root = store.recent_context(account_id='a',sender='s',conversation_id='c',db_factory=db,now=NOW)
    assert root['id'] == document['id']
    assert root['authorization_generation'] < store.get_settings('a',db_factory=db)['authorization_generation']


@pytest.mark.parametrize('changes', [
    {'question_kind':'conversation'}, {'question_kind':'operations'}, {'question_kind':'greeting'},
    {'question_allowed':False}, {'question_allowed':'true'},
])
def test_pdf_meta_response_cannot_replace_explicit_followup_acceptance(db, changes):
    import json
    document, followup, acceptance = acceptance_pair(db)
    row = store.get_job(followup['id'],db_factory=db)
    with db() as connection:
        connection.execute('UPDATE whatsapp_agent_jobs SET payload=%s WHERE id=%s',
            (json.dumps({**row['payload'], **changes}),followup['id']))
    assert row['context_source_job_id'] == document['id'] and row['model_completed_at']
    with pytest.raises(ValueError):
        store.update_settings('a',mode='routine',acceptance=acceptance,db_factory=db,now=NOW)


def test_source_absent_document_question_can_request_natural_clarification(db):
    enable(db)
    store.update_settings('a', approved_sha256=[], db_factory=db, now=NOW)
    job = ordinary_job(db, payload=operations_payload(question='What does the file say?', question_kind='document_question'))
    assert store.reserve_model(job['id'], job['lease_token'], db_factory=db, now=NOW)
    assert store.model_authorized(job['id'], job['lease_token'], db_factory=db, now=NOW)
    store.save_model(job['id'], job['lease_token'], reply_text='I do not have a file here; please attach it.',
        diagnostics={'model_success': True}, db_factory=db, now=NOW)
    store.prepare_reply(job['id'], job['lease_token'], db_factory=db, now=NOW)
    sending = store.claim_send(db_factory=db, now=NOW)
    assert store.send_authorized(job['id'], sending['send_token'], db_factory=db, now=NOW)
    store.finish_send(job['id'], sending['send_token'], status='sent', db_factory=db, now=NOW)
    result = store.get_job(job['id'], db_factory=db)
    assert result['document_status']=='none' and result['document_sha256'] is None and not result['document_text']
    assert store.recent_context(account_id='a', sender='s', conversation_id='c', db_factory=db, now=NOW) is None
    second = ordinary_job(db,2,payload=operations_payload(question='Is the file available?',question_kind='document_question'))
    assert store.reserve_model(second['id'],second['lease_token'],db_factory=db,now=NOW)
    store.save_model(second['id'],second['lease_token'],reply_text='No file is available yet.',
        diagnostics={'model_success':True},db_factory=db,now=NOW)
    store.prepare_reply(second['id'],second['lease_token'],db_factory=db,now=NOW)
    sending = store.claim_send(db_factory=db,now=NOW)
    store.finish_send(second['id'],sending['send_token'],status='sent',db_factory=db,now=NOW)
    with pytest.raises(ValueError):
        store.update_settings('a', mode='routine', acceptance={'owner_receipt_confirmed':True,
            'document_job_id':job['id'],'followup_job_id':second['id']}, db_factory=db, now=NOW)


@pytest.mark.parametrize('change', ['attachment', 'hash', 'text', 'context', 'quarantined', 'unavailable'])
def test_document_question_source_absent_branch_cannot_hide_any_source(db, change):
    enable(db)
    payload = operations_payload(question='What does the file say?', question_kind='document_question')
    if change == 'attachment':
        payload.update(attachment_count=1, attachments=[{'mime':'application/pdf'}])
    job = ordinary_job(db, payload=payload)
    if change == 'context':
        with db() as connection:
            connection.execute('UPDATE whatsapp_agent_jobs SET context_source_job_id=%s WHERE id=%s',
                               (job['id'],job['id']))
    elif change != 'attachment':
        values = {'text':'','sha256':None,'status':'none'}
        if change == 'hash': values['sha256']=SHA
        elif change == 'text': values.update(text=TEXT,sha256='b'*64)
        else: values['status']=change
        store.checkpoint_document(job['id'],job['lease_token'],db_factory=db,now=NOW,**values)
    assert not store.reserve_model(job['id'],job['lease_token'],db_factory=db,now=NOW)
    assert not store.model_authorized(job['id'],job['lease_token'],db_factory=db,now=NOW)
    assert store.get_job(job['id'],db_factory=db)['model_started_at'] is None


def test_source_absent_document_question_ambiguity_still_never_retries(db):
    enable(db)
    job = ordinary_job(db,payload=operations_payload(question_kind='document_question'))
    assert store.reserve_model(job['id'],job['lease_token'],db_factory=db,now=NOW)
    assert claim(db,NOW+timedelta(seconds=301)) is None
    assert store.get_job(job['id'],db_factory=db)['status']=='uncertain'
    assert not store.model_authorized(job['id'],job['lease_token'],db_factory=db,now=NOW)
    assert store.claim_send(db_factory=db,now=NOW+timedelta(seconds=302)) is None
