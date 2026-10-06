"""Run durable queue acceptance against ONLY disposable localhost/afaaq_test.

Usage: AFAAQ_TEST_DATABASE_URL=postgresql://...@localhost/afaaq_test \
       python tests/whatsapp_agent_postgres_acceptance.py
Creates an isolated random schema, then removes that schema. No application
bootstrap, DATABASE_URL, model API, provider API, or external network is used.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import secrets
import socket
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
TEXT = 'Synthetic PostgreSQL concurrency and checkpoint test'
SHA = hashlib.sha256(TEXT.encode()).hexdigest()


def verify(factory):
    from app import whatsapp_agent_store as store
    store.init_storage(db_factory=factory)
    store.init_storage(db_factory=factory)

    def settings(account):
        return store.update_settings(account, mode='owner_pilot', pilot_sender='owner',
            approved_sha256=[SHA], db_factory=factory, now=NOW)

    def enqueue(account, message, *, event=None, sender='owner', conversation='conversation', attachment_count=1, payload=None):
        with factory() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (conversation,))
            return store.enqueue(connection, account_id=account, message_id=message,
                event_id=event or 'event-'+message, sender=sender, conversation_id=conversation,
                payload=payload if payload is not None else {'text': 'synthetic sanitized input', 'attachment_count': attachment_count,
                         'attachments': [{'mime': 'application/pdf'}] if attachment_count else []}, now=NOW)

    def claim(account, now=NOW):
        return store.claim_job(account_id=account, db_factory=factory, now=now)

    def checkpoint(job, now=NOW, source=None):
        return store.checkpoint_document(job['id'], job['lease_token'], text=TEXT, sha256=SHA,
            status='ok', context_source_job_id=source, db_factory=factory, now=now)

    def reserve(job, now=NOW):
        return store.reserve_model(job['id'], job['lease_token'], db_factory=factory, now=now)

    def model(job):
        checkpoint(job)
        assert reserve(job)
        return store.save_model(job['id'], job['lease_token'], reply_text='Synthetic generated reply',
            diagnostics={'model_success': True}, db_factory=factory, now=NOW)

    def prepare(job, text=None):
        return store.prepare_reply(job['id'], job['lease_token'], reply_text=text,
            db_factory=factory, now=NOW)

    def send(account, now=NOW):
        return store.claim_send(account_id=account, db_factory=factory, now=now)

    def finish(job, status='sent'):
        return store.finish_send(job['id'], job['send_token'], status=status,
            provider_message_id='synthetic-provider-'+str(job['id']), db_factory=factory, now=NOW)

    def get(job):
        return store.get_job(job['id'], db_factory=factory)

    def parallel(action, count=8):
        with ThreadPoolExecutor(max_workers=count) as pool:
            return list(pool.map(action, range(count)))

    def legacy(account, message, *, event=None, conversation='conversation'):
        with factory() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (conversation,))
            return store.claim_legacy(connection, account_id=account, message_id=message,
                event_id=event or 'legacy-'+message, sender='owner',
                conversation_id=conversation, now=NOW)

    # Cross-lane ownership survives OFF legacy E1 -> enabled durable alias E2.
    assert legacy('legacy-first', 'one', event='legacy-E1')
    settings('legacy-first')
    owned = enqueue('legacy-first', 'one', event='durable-E2')
    assert owned['status'] == 'blocked' and owned['payload'] == {'legacy_owned': True}
    assert claim('legacy-first') is None
    assert not legacy('legacy-first', 'one', event='legacy-E3')

    # Opposite ordering: legacy never changes a queued/processing/sending owner.
    settings('durable-first')
    owned = enqueue('durable-first', 'one', event='durable-E1')
    assert not legacy('durable-first', 'one', event='legacy-E2')
    assert get(owned)['status'] == 'pending'
    active = claim('durable-first')
    assert not legacy('durable-first', 'one', event='legacy-E3')
    assert get(active)['status'] == 'processing'
    prepare(active, 'One durable reply')
    sending = send('durable-first')
    assert not legacy('durable-first', 'one', event='legacy-E4')
    assert get(sending)['status'] == 'sending'
    finish(sending)

    # Actual concurrent transactions arbitrate one owner with no body retention.
    settings('lane-race')
    def competing_lane(number):
        if number % 2:
            return legacy('lane-race', 'one', event='legacy-'+str(number))
        return enqueue('lane-race', 'one', event='durable-'+str(number))
    results = parallel(competing_lane, 12)
    rows = store.list_jobs(account_id='lane-race', db_factory=factory)
    assert len(rows) == 1
    won_legacy = sum(result is True for result in results)
    assert won_legacy == int(rows[0]['payload'] == {'legacy_owned': True})
    assert rows[0]['status'] == ('blocked' if won_legacy else 'pending')
    store.update_settings('lane-race', mode='off', db_factory=factory, now=NOW)

    # OFF ingestion is final and cannot replay after activation.
    stopped = enqueue('off', 'message')
    assert stopped['status'] == 'blocked'
    settings('off')
    assert claim('off') is None

    # Same message, twelve separate event aliases, one durable job.
    settings('dedupe')
    duplicates = parallel(lambda number: enqueue('dedupe', 'one', event='alias-'+str(number)), 12)
    assert len({row['id'] for row in duplicates}) == 1
    assert enqueue('dedupe', 'different', event='alias-11')['id'] == duplicates[0]['id']
    with factory() as connection:
        assert connection.execute("SELECT COUNT(*) n FROM whatsapp_agent_events WHERE account_id='dedupe'").fetchone()['n'] == 12
    store.update_settings('dedupe', mode='off', db_factory=factory, now=NOW)

    # SKIP LOCKED: never two owners and never claim a same-conversation successor.
    settings('ordered')
    first, second = enqueue('ordered', 'first'), enqueue('ordered', 'second')
    claims = [row for row in parallel(lambda _: claim('ordered')) if row]
    assert len(claims) == 1 and claims[0]['id'] == first['id']
    active = claims[0]
    prepare(active, 'Safe pre-model reply')
    assert claim('ordered') is None
    sends = [row for row in parallel(lambda _: send('ordered')) if row]
    assert len(sends) == 1
    assert get(active)['status'] == 'sending'  # committed before any fake network
    assert claim('ordered') is None
    finish(sends[0])
    assert claim('ordered')['id'] == second['id']
    store.update_settings('ordered', mode='off', db_factory=factory, now=NOW)

    # Independent conversations allow parallel work without duplicate leases.
    settings('independent')
    for number in range(12):
        enqueue('independent', str(number), conversation='c'+str(number))
    independent = [row for row in parallel(lambda _: claim('independent'), 12) if row]
    assert len(independent) == 12 and len({row['id'] for row in independent}) == 12
    for job in independent:
        checkpoint(job)
    # Reservation count serialized by settings row: exactly ten, including loss.
    reservations = parallel(lambda number: reserve(independent[number]), 12)
    assert sum(reservations) == 10
    assert claim('independent', NOW+timedelta(seconds=301)) is None
    assert [get(job)['status'] for job in independent].count('uncertain') == 10
    assert all(send('independent', NOW+timedelta(seconds=302)) is None for _ in range(2))

    # Read retries limited to 3, previous worker token fenced.
    settings('reads')
    original = enqueue('reads', 'read')
    first_claim = claim('reads')
    assert claim('reads', NOW+timedelta(seconds=301))['read_attempts'] == 2
    try:
        checkpoint(first_claim)
        raise AssertionError('stale lease accepted')
    except store.StateConflict:
        pass
    assert claim('reads', NOW+timedelta(seconds=602))['read_attempts'] == 3
    assert claim('reads', NOW+timedelta(seconds=903)) is None
    assert get(original)['status'] == 'failed'

    # Saved model recovers into outbox; reserved-without-result above never did.
    settings('checkpoint')
    enqueue('checkpoint', 'saved')
    job = claim('checkpoint')
    saved = model(job)
    assert claim('checkpoint', NOW+timedelta(seconds=301)) is None
    assert get(job)['status'] == 'ready'
    sending = send('checkpoint', NOW+timedelta(seconds=302))
    assert sending['reply_text'] == saved['reply_text']
    assert sending['idempotency_key'] == job['idempotency_key']
    assert send('checkpoint', NOW+timedelta(seconds=603)) is None
    assert get(job)['status'] == 'uncertain'
    assert store.get_outbox(job['id'], db_factory=factory)['status'] == 'uncertain'
    assert send('checkpoint', NOW+timedelta(days=2)) is None

    # Successful actual document, scoped followup and owner receipt gate routine.
    settings('context')
    enqueue('context', 'document')
    document = claim('context')
    model(document)
    prepare(document)
    finish(send('context'))
    scope = dict(account_id='context', sender='owner', conversation_id='conversation',
                 db_factory=factory, now=NOW)
    assert store.recent_context(**scope)['id'] == document['id']
    for field in ('account_id', 'sender', 'conversation_id'):
        assert store.recent_context(**{**scope, field: 'unrelated'}) is None
    assert store.recent_context(**{**scope, 'now': NOW+timedelta(days=2)}) is None
    enqueue('context', 'followup', attachment_count=0)
    followup = claim('context')
    checkpoint(followup, source=document['id'])
    assert reserve(followup)
    store.save_model(followup['id'], followup['lease_token'], reply_text='Synthetic followup answer',
        diagnostics={'model_success': True}, db_factory=factory, now=NOW)
    prepare(followup)
    finish(send('context'))
    acceptance = dict(owner_receipt_confirmed=True, document_job_id=document['id'], followup_job_id=followup['id'])
    assert store.update_settings('context', mode='routine', acceptance=acceptance,
        db_factory=factory, now=NOW)['mode'] == 'routine'

    # An explicit stop fences leases and never replays ready/pending work.
    settings('stop')
    for number in range(4):
        enqueue('stop', str(number), conversation='c'+str(number))
    processing = [claim('stop') for _ in range(3)]
    prepare(processing[0], 'First reply')
    sending = send('stop')
    prepare(processing[1], 'Second reply')
    store.update_settings('stop', mode='off', db_factory=factory, now=NOW)
    statuses = [row['status'] for row in store.list_jobs(account_id='stop', db_factory=factory)]
    assert statuses == ['blocked', 'blocked', 'blocked', 'sending']
    settings('stop')
    assert claim('stop') is None and send('stop') is None
    finish(sending)

    # Concurrent disable/reserve has a single lock order, no deadlock or revival.
    for number in range(5):
        account = 'race-'+str(number)
        settings(account)
        enqueue(account, 'race')
        job = claim(account)
        checkpoint(job)
        def race(index):
            if index:
                return store.update_settings(account, mode='off', db_factory=factory, now=NOW)
            try:
                return reserve(job)
            except store.StateConflict:
                return False
        parallel(race, 2)
        assert get(job)['status'] == 'blocked'
    # Single-snapshot guards race safely with stop; no locks are held over I/O.
    for number in range(3):
        account = 'guard-race-'+str(number)
        settings(account)
        enqueue(account, 'guarded')
        job = claim(account)
        checkpoint(job)
        assert reserve(job)
        def model_guard_race(index):
            if index:
                return store.update_settings(account, mode='off', db_factory=factory, now=NOW)
            return store.model_authorized(job['id'], job['lease_token'], db_factory=factory, now=NOW)
        parallel(model_guard_race, 2)
        assert not store.model_authorized(job['id'], job['lease_token'], db_factory=factory, now=NOW)
        settings(account)
        assert not store.model_authorized(job['id'], job['lease_token'], db_factory=factory, now=NOW)

        enqueue(account, 'send-guarded')
        outgoing = claim(account)
        prepare(outgoing, 'Sanitized local response')
        sending = send(account)
        assert store.send_authorized(sending['id'], sending['send_token'], db_factory=factory, now=NOW)
        def send_guard_race(index):
            if index:
                return store.update_settings(account, mode='off', db_factory=factory, now=NOW)
            return store.send_authorized(sending['id'], sending['send_token'], db_factory=factory, now=NOW)
        parallel(send_guard_race, 2)
        assert not store.send_authorized(sending['id'], sending['send_token'], db_factory=factory, now=NOW)
        settings(account)
        assert not store.send_authorized(sending['id'], sending['send_token'], db_factory=factory, now=NOW)
        assert get(sending)['status'] == 'sending'
        finish(sending, 'blocked')

    # Pilot evidence cannot authorize another pilot or a later authorization epoch.
    store.update_settings('context', mode='off', db_factory=factory, now=NOW)
    settings('context')
    try:
        store.update_settings('context', mode='routine', acceptance=acceptance, db_factory=factory, now=NOW)
        raise AssertionError('old-generation pilot evidence accepted')
    except ValueError:
        pass
    # Owner-pilot ordinary business text uses the same capped no-tools lane
    # without requiring a document. All input metadata is synthetic here.
    ordinary_payload = {'question': 'How can I organize a shipment handover?',
        'question_allowed': True, 'question_kind': 'operations',
        'attachment_count': 0, 'attachments': []}
    settings('ordinary')
    store.update_settings('ordinary', approved_sha256=[], db_factory=factory, now=NOW)
    ordinary_jobs = []
    for number in range(2):
        enqueue('ordinary', 'question-'+str(number), payload=ordinary_payload)
        job = claim('ordinary')
        store.checkpoint_document(job['id'], job['lease_token'], text='', sha256=None,
            status='none', db_factory=factory, now=NOW)
        assert reserve(job)
        assert store.model_authorized(job['id'], job['lease_token'], db_factory=factory, now=NOW)
        assert not reserve(job)
        store.save_model(job['id'], job['lease_token'], reply_text='Synthetic business response',
            diagnostics={'model_success': True}, db_factory=factory, now=NOW)
        prepare(job)
        outgoing = send('ordinary')
        assert store.send_authorized(job['id'], outgoing['send_token'], db_factory=factory, now=NOW)
        finish(outgoing)
        ordinary_jobs.append(job)
    assert store.recent_context(account_id='ordinary', sender='owner', conversation_id='conversation',
        db_factory=factory, now=NOW) is None
    try:
        store.update_settings('ordinary', mode='routine', acceptance={'owner_receipt_confirmed': True,
            'document_job_id': ordinary_jobs[0]['id'], 'followup_job_id': ordinary_jobs[1]['id']},
            db_factory=factory, now=NOW)
        raise AssertionError('ordinary text replaced PDF pilot acceptance')
    except ValueError:
        pass
    assert enqueue('ordinary', 'other-sender', sender='other', payload=ordinary_payload)['status'] == 'blocked'

    changes = [{'question_allowed': False}, {'question_allowed': 'true'},
        {'question_kind': 'unknown'}, {'question_kind': 'document_question'},
        {'attachment_count': 1}, {'attachments': [{'mime': 'application/pdf'}]},
        {'question': ''}]
    for number, change in enumerate(changes):
        account = 'ordinary-negative-'+str(number)
        settings(account)
        enqueue(account, 'question', payload={**ordinary_payload, **change})
        job = claim(account)
        store.checkpoint_document(job['id'], job['lease_token'], text='', sha256=None,
            status='none', db_factory=factory, now=NOW)
        assert not reserve(job)
        assert not store.model_authorized(job['id'], job['lease_token'], db_factory=factory, now=NOW)
        assert get(job)['model_started_at'] is None
    settings('ordinary-unapproved-document')
    enqueue('ordinary-unapproved-document', 'question', payload=ordinary_payload)
    job = claim('ordinary-unapproved-document')
    store.checkpoint_document(job['id'], job['lease_token'], text=TEXT, sha256='b'*64,
        status='ok', db_factory=factory, now=NOW)
    assert not reserve(job)

    # Concurrent ordinary questions share the same ten-reservation pilot budget;
    # ambiguous crashes consume their reservation and never cause regeneration.
    settings('ordinary-budget')
    ordinary_active = []
    for number in range(12):
        enqueue('ordinary-budget', str(number), conversation='c'+str(number), payload=ordinary_payload)
        job = claim('ordinary-budget')
        store.checkpoint_document(job['id'], job['lease_token'], text='', sha256=None,
            status='none', db_factory=factory, now=NOW)
        ordinary_active.append(job)
    ordinary_reservations = parallel(lambda index: reserve(ordinary_active[index]), 12)
    assert sum(ordinary_reservations) == 10
    assert claim('ordinary-budget', NOW+timedelta(seconds=301)) is None
    assert [get(job)['status'] for job in ordinary_active].count('uncertain') == 10
    assert all(not store.model_authorized(job['id'], job['lease_token'], db_factory=factory, now=NOW)
               for job in ordinary_active)
    assert send('ordinary-budget', NOW+timedelta(seconds=302)) is None

    # OFF/ON permanently fences ordinary output just like document output.
    enqueue('ordinary', 'stop-question', payload=ordinary_payload)
    job = claim('ordinary')
    store.checkpoint_document(job['id'], job['lease_token'], text='', sha256=None,
        status='none', db_factory=factory, now=NOW)
    assert reserve(job)
    store.save_model(job['id'], job['lease_token'], reply_text='Synthetic known result', db_factory=factory, now=NOW)
    prepare(job)
    outgoing = send('ordinary')
    assert store.send_authorized(job['id'], outgoing['send_token'], db_factory=factory, now=NOW)
    store.update_settings('ordinary', mode='off', db_factory=factory, now=NOW)
    settings('ordinary')
    assert not store.send_authorized(job['id'], outgoing['send_token'], db_factory=factory, now=NOW)
    assert send('ordinary', NOW+timedelta(seconds=301)) is None
    assert get(job)['status'] == 'uncertain'

    # Stale UI tabs cannot overwrite a concurrent authorization reconfiguration.
    generation = settings('settings-cas')['authorization_generation']
    def submit_settings(number):
        try:
            return store.update_settings('settings-cas', pilot_sender='pilot-'+str(number),
                expected_generation=generation, db_factory=factory, now=NOW)
        except store.StateConflict:
            return 'stale'
    submissions = parallel(submit_settings, 2)
    assert submissions.count('stale') == 1
    current = store.get_settings('settings-cas', db_factory=factory)
    assert current['authorization_generation'] == generation+1
    try:
        store.update_settings('settings-cas', mode='off', expected_generation=generation,
            db_factory=factory, now=NOW)
        raise AssertionError('stale settings overwrite accepted')
    except store.StateConflict:
        pass
    assert store.get_settings('settings-cas', db_factory=factory) == current

    print('PASS: PostgreSQL duplicate event/message aliases, concurrent SKIP LOCKED claims, '
          'conversation serialization, bounded reads/model budgets, crash checkpoints, '
          'no ambiguous send retries, context isolation/freshness, acceptance and stop fencing. '
          'External API calls: 0.')


def main():
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    target = urlsplit(url)
    if (target.scheme not in ('postgres', 'postgresql') or
        target.hostname not in ('localhost', '127.0.0.1') or target.path != '/afaaq_test' or
        target.query or target.fragment):
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema = 'whatsapp_agent_test_' + secrets.token_hex(8)
    original_connect = socket.socket.connect

    def only_local(sock, address):
        if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1'):
            raise AssertionError('External network forbidden in acceptance tests')
        return original_connect(sock, address)

    @contextmanager
    def factory():
        with psycopg.connect(url, row_factory=dict_row) as connection:
            connection.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            connection.execute("SET LOCAL lock_timeout='10s'")
            connection.execute("SET LOCAL statement_timeout='20s'")
            yield connection

    with patch.object(socket.socket, 'connect', only_local):
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            try:
                verify(factory)
            finally:
                connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
