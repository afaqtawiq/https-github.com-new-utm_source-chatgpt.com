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

    def enqueue(account, message, *, event=None, sender='owner', conversation='conversation', attachment_count=1, payload=None, now=NOW):
        with factory() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (conversation,))
            return store.enqueue(connection, account_id=account, message_id=message,
                event_id=event or 'event-'+message, sender=sender, conversation_id=conversation,
                payload=payload if payload is not None else {'text': 'synthetic sanitized input',
                         'question': 'What does the document say?', 'question_allowed': True,
                         'question_kind': 'document_question', 'attachment_count': attachment_count,
                         'attachments': [{'mime': 'application/pdf'}] if attachment_count else []}, now=now)

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

    def finish(job, status='sent', now=NOW):
        return store.finish_send(job['id'], job['send_token'], status=status,
            provider_message_id='synthetic-provider-'+str(job['id']), db_factory=factory, now=now)

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
    quota_notice = send('independent', NOW+timedelta(seconds=302))
    assert quota_notice and quota_notice['reply_text'] == store.MODEL_BUDGET_NOTICE
    assert quota_notice['model_started_at'] is None and quota_notice['model_completed_at'] is None
    finish(quota_notice, 'uncertain', now=NOW+timedelta(seconds=302))
    assert all(send('independent', NOW+timedelta(seconds=303)) is None for _ in range(2))

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
        {'question_kind': 'unknown'}, {'question_kind': 'unrecognized_kind'},
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
    ordinary_notice = send('ordinary-budget', NOW+timedelta(seconds=302))
    assert ordinary_notice and ordinary_notice['reply_text'] == store.MODEL_BUDGET_NOTICE
    assert ordinary_notice['model_started_at'] is None and ordinary_notice['model_completed_at'] is None
    finish(ordinary_notice, 'uncertain', now=NOW+timedelta(seconds=302))
    assert send('ordinary-budget', NOW+timedelta(seconds=303)) is None

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

    # Same-thread conversation history is persisted text, bounded and fenced to
    # the active target generation. Document/context-bearing records never enter.
    conversation_payload = {**ordinary_payload, 'question_kind': 'conversation'}
    def exchange(account, message, *, question='Prior conversation turn', reply='Actual prior response',
                 when=NOW, status='sent', payload_changes=None, conversation='conversation'):
        payload = {**conversation_payload, 'question': question, **(payload_changes or {})}
        enqueue(account, message, conversation=conversation, payload=payload, now=when)
        job = claim(account, when)
        store.checkpoint_document(job['id'], job['lease_token'], text='', sha256=None,
            status='none', db_factory=factory, now=when)
        store.prepare_reply(job['id'], job['lease_token'], reply_text=reply, db_factory=factory, now=when)
        outgoing = send(account, when)
        store.finish_send(job['id'], outgoing['send_token'], status=status,
            provider_message_id='history-'+str(job['id']), db_factory=factory, now=when)
        return get(job)
    def target_for_history(account, message='target'):
        enqueue(account, message, payload=conversation_payload)
        return claim(account)
    def exchanges(account, target, **kwargs):
        return store.recent_exchanges(account_id=account, sender='owner', conversation_id='conversation',
            before_job_id=target['id'], db_factory=factory, now=NOW, **kwargs)

    settings('conversation-positive')
    conversation_job = target_for_history('conversation-positive')
    store.checkpoint_document(conversation_job['id'], conversation_job['lease_token'], text='', sha256=None,
        status='none', db_factory=factory, now=NOW)
    assert reserve(conversation_job)
    assert store.model_authorized(conversation_job['id'], conversation_job['lease_token'], db_factory=factory, now=NOW)
    store.save_model(conversation_job['id'], conversation_job['lease_token'], reply_text='Conversation response',
        db_factory=factory, now=NOW)
    prepare(conversation_job)
    conversation_send = send('conversation-positive')
    assert store.send_authorized(conversation_job['id'], conversation_send['send_token'], db_factory=factory, now=NOW)
    finish(conversation_send)

    settings('history')
    exchange('history', 'old', when=NOW-timedelta(days=1, seconds=1))
    exchange('history', 'other-conversation', conversation='unrelated')
    history_pairs = [exchange('history', 'pair-'+str(number), question='q'+str(number), reply='r'+str(number))
                     for number in range(6)]
    exchange('history', 'blocked-question', payload_changes={'question_allowed': False})
    exchange('history', 'not-sent', status='uncertain')
    exchange('history', 'url-reply', reply='https://example.invalid/private')
    history_target = target_for_history('history')
    history_rows = exchanges('history', history_target, limit=999, max_age_seconds=999999)
    assert [row['job_id'] for row in history_rows] == [job['id'] for job in history_pairs[-4:]]
    assert all(set(row)=={'job_id','account_id','sender','conversation_id','authorization_generation',
                         'status','created_at','completed_at','question','reply_text'} for row in history_rows)
    for field in ('account_id','sender','conversation_id'):
        scope = {'account_id':'history','sender':'owner','conversation_id':'conversation', field:'unrelated'}
        assert store.recent_exchanges(**scope, before_job_id=history_target['id'], db_factory=factory, now=NOW) == []
    store.update_settings('history', mode='off', db_factory=factory, now=NOW)
    settings('history')
    assert exchanges('history', history_target) == []
    fresh_target = target_for_history('history', 'new-target')
    assert exchanges('history', fresh_target) == []

    settings('history-bounds')
    for number in range(4):
        exchange('history-bounds', str(number), question='q'*1500, reply='r'*2500)
    exchange('history-bounds', 'oversized', question='q'*1501)
    bounds_target = target_for_history('history-bounds')
    bounded = exchanges('history-bounds', bounds_target)
    assert len(bounded)==2 and sum(len(row['question'])+len(row['reply_text']) for row in bounded)==8000
    assert all(row['question']=='q'*1500 and row['reply_text']=='r'*2500 for row in bounded)

    settings('history-document')
    enqueue('history-document', 'pdf')
    history_document = claim('history-document')
    model(history_document)
    prepare(history_document)
    finish(send('history-document'))
    doc_target = target_for_history('history-document')
    assert exchanges('history-document', doc_target) == []

    # The PDF cache remains anchored to the original actual attachment across
    # inherited/meta replies and harmless text turns. Only an explicit document
    # question can serve as the separate one-time rollout followup proof.
    settings('pdf-root-history')
    enqueue('pdf-root-history', 'root-pdf')
    actual_root = claim('pdf-root-history')
    model(actual_root)
    prepare(actual_root)
    finish(send('pdf-root-history'))
    enqueue('pdf-root-history', 'pdf-meta', payload=conversation_payload)
    meta = claim('pdf-root-history')
    checkpoint(meta, source=actual_root['id'])
    assert reserve(meta)
    store.save_model(meta['id'], meta['lease_token'], reply_text='Known contextual meta response',
        diagnostics={'model_success': True}, db_factory=factory, now=NOW)
    prepare(meta)
    finish(send('pdf-root-history'))
    exchange('pdf-root-history', 'thanks', question='Thanks', reply='You are welcome')
    enqueue('pdf-root-history', 'explicit-followup', attachment_count=0)
    final_followup = claim('pdf-root-history')
    original = store.recent_context(account_id='pdf-root-history',sender='owner',conversation_id='conversation',
        before_job_id=final_followup['id'],db_factory=factory,now=NOW)
    assert original['id']==actual_root['id'] and original['context_source_job_id'] is None
    text_pairs = exchanges('pdf-root-history', final_followup)
    assert len(text_pairs)==1 and text_pairs[0]['question']=='Thanks'
    checkpoint(final_followup, source=original['id'])
    assert reserve(final_followup)
    store.save_model(final_followup['id'], final_followup['lease_token'], reply_text='Known explicit document answer',
        diagnostics={'model_success': True}, db_factory=factory, now=NOW)
    prepare(final_followup)
    finish(send('pdf-root-history'))
    try:
        store.update_settings('pdf-root-history',mode='routine', acceptance={'owner_receipt_confirmed':True,
            'document_job_id':actual_root['id'],'followup_job_id':meta['id']},db_factory=factory,now=NOW)
        raise AssertionError('meta PDF reply substituted for explicit document followup')
    except ValueError:
        pass
    store.update_settings('pdf-root-history',mode='routine', acceptance={'owner_receipt_confirmed':True,
        'document_job_id':actual_root['id'],'followup_job_id':final_followup['id']},db_factory=factory,now=NOW)
    original = store.recent_context(account_id='pdf-root-history',sender='owner',conversation_id='conversation',
        db_factory=factory,now=NOW)
    assert original['id']==actual_root['id']

    # A document question with genuinely no source may clarify that absence;
    # it must not downgrade a present/quarantined source to an empty-source call.
    settings('source-absent')
    store.update_settings('source-absent',approved_sha256=[],db_factory=factory,now=NOW)
    absent_payload = {**ordinary_payload,'question_kind':'document_question','question':'What does the file say?'}
    enqueue('source-absent','no-file',payload=absent_payload)
    absent = claim('source-absent')
    store.checkpoint_document(absent['id'],absent['lease_token'],text='',sha256=None,status='none',
        db_factory=factory,now=NOW)
    assert reserve(absent)
    assert store.model_authorized(absent['id'],absent['lease_token'],db_factory=factory,now=NOW)
    store.save_model(absent['id'],absent['lease_token'],reply_text='I have no file here; please attach it.',
        diagnostics={'model_success':True},db_factory=factory,now=NOW)
    prepare(absent)
    absent_send = send('source-absent')
    assert store.send_authorized(absent['id'],absent_send['send_token'],db_factory=factory,now=NOW)
    finish(absent_send)
    assert store.recent_context(account_id='source-absent',sender='owner',conversation_id='conversation',
        db_factory=factory,now=NOW) is None
    for number, change in enumerate(('attachment','hash','quarantined','unavailable')):
        account = 'source-present-'+str(number)
        settings(account)
        payload = dict(absent_payload)
        if change=='attachment':payload.update(attachment_count=1,attachments=[{'mime':'application/pdf'}])
        enqueue(account,'blocked',payload=payload)
        candidate = claim(account)
        store.checkpoint_document(candidate['id'],candidate['lease_token'],text='',
            sha256=SHA if change=='hash' else None,
            status=change if change in ('quarantined','unavailable') else 'none',db_factory=factory,now=NOW)
        assert not reserve(candidate)
        assert get(candidate)['model_started_at'] is None
        assert not store.model_authorized(candidate['id'],candidate['lease_token'],db_factory=factory,now=NOW)

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

    verify_budget_notices(factory)
    verify_recent_attachment_outcome(factory)
    verify_quoted_attachment_context(factory)

    print('PASS: PostgreSQL duplicate event/message aliases, concurrent SKIP LOCKED claims, '
          'conversation serialization, bounded reads/model budgets, crash checkpoints, '
          'no ambiguous send retries, context isolation/freshness, acceptance/stop fencing, and bounded quota notices. '
          'External API calls: 0.')


def verify_budget_notices(factory):
    """Actual concurrent transactions for the local-only exhausted-pilot notice.

    These helpers reserve synthetic model attempts but never call a model or a
    messaging provider. The factory is the same isolated disposable DB schema.
    """
    from app import whatsapp_agent_store as store
    payload = {'question': 'How should I organize the handover?', 'question_allowed': True,
               'question_kind': 'operations', 'attachment_count': 0, 'attachments': []}

    def utc(value):
        return (datetime.fromisoformat(value.replace('Z', '+00:00'))
                if isinstance(value, str) else value).astimezone(timezone.utc)

    def configure(account, now=NOW):
        return store.update_settings(account, mode='owner_pilot', pilot_sender='owner',
            approved_sha256=[], db_factory=factory, now=now)

    def row(job):
        return store.get_job(job['id'], db_factory=factory)

    def incoming(account, message, *, now=NOW, created_at=None, conversation=None):
        with factory() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (conversation or message,))
            store.enqueue(connection, account_id=account, message_id=message, event_id='event-'+message,
                sender='owner', conversation_id=conversation or message, payload=payload, now=created_at or now)
        job = store.claim_job(account_id=account, db_factory=factory, now=now)
        assert job is not None
        store.checkpoint_document(job['id'], job['lease_token'], text='', sha256=None,
            status='none', db_factory=factory, now=now)
        return job

    def reserve(job, now=NOW):
        return store.reserve_model(job['id'], job['lease_token'], db_factory=factory, now=now)

    def quota_count(account, now=NOW):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        with factory() as connection:
            return connection.execute("""SELECT COUNT(*) n FROM whatsapp_agent_jobs
                WHERE account_id=%s AND model_started_at>=%s AND model_started_at<%s""",
                (account, start.isoformat(), (start+timedelta(days=1)).isoformat())).fetchone()['n']

    def exhaust(account, now=NOW, limit=10):
        for number in range(quota_count(account, now), limit):
            job = incoming(account, account+'-used-'+now.date().isoformat()+'-'+str(number), now=now)
            assert reserve(job, now)
            # A lost model result consumes the reservation; never regenerate it.
            store.prepare_reply(job['id'], job['lease_token'], terminal_status='uncertain',
                diagnostics={'reason':'synthetic_consumed_reservation'}, db_factory=factory, now=now)
        assert quota_count(account, now) == limit

    def notices(account):
        with factory() as connection:
            return [dict(item) for item in connection.execute("""SELECT account_id,sender,window_start,job_id
                FROM whatsapp_agent_budget_notices WHERE account_id=%s ORDER BY window_start,job_id""",
                (account,)).fetchall()]

    def outboxes(account):
        with factory() as connection:
            return [dict(item) for item in connection.execute("""SELECT o.* FROM whatsapp_agent_outbox o
                JOIN whatsapp_agent_jobs j ON j.id=o.job_id WHERE j.account_id=%s ORDER BY o.job_id""",
                (account,)).fetchall()]

    def send(account, now=NOW):
        return store.claim_send(account_id=account, db_factory=factory, now=now)

    def finish(job, status, now=NOW):
        return store.finish_send(job['id'], job['send_token'], status=status,
            db_factory=factory, now=now)

    def parallel(action, count=8):
        with ThreadPoolExecutor(max_workers=count) as pool:
            return list(pool.map(action, range(count)))

    def assert_notice(job, now=NOW):
        saved = row(job)
        assert saved['reply_text'] == store.MODEL_BUDGET_NOTICE
        assert saved['model_started_at'] is None and saved['model_completed_at'] is None
        diagnostics = saved['diagnostics']
        assert diagnostics['reason'] == diagnostics['model_reason'] == 'daily_model_budget_exhausted'
        assert diagnostics['model_attempted'] is False and diagnostics['model_success'] is False
        assert diagnostics['budget_notice'] == 'local_notice'
        assert utc(diagnostics['budget_notice_window']) == now.replace(hour=0, minute=0, second=0, microsecond=0)
        assert not store.model_authorized(job['id'], job.get('lease_token'), db_factory=factory, now=now)
        return saved

    def assert_duplicate(job, account, now=NOW):
        assert not reserve(job, now)
        saved = row(job)
        assert saved['status'] == 'blocked'
        assert saved['diagnostics']['budget_notice'] == 'already_claimed'
        assert saved['diagnostics']['model_attempted'] is False
        assert saved['diagnostics']['model_success'] is False
        assert saved['model_started_at'] is None and saved['model_completed_at'] is None
        assert quota_count(account, now) == 10

    # Inject a crash after each durable INSERT but before transaction commit.
    # The notice claim and outbox must roll back together, leaving the original
    # processing lease intact and allowing one safe DB retry (no network ran).
    for table in ('whatsapp_agent_budget_notices','whatsapp_agent_outbox'):
        account = 'quota-rollback-'+table.rsplit('_',1)[-1]
        configure(account)
        exhaust(account)
        candidate = incoming(account,'rollback-'+table)
        @contextmanager
        def fail_after_insert():
            with factory() as connection:
                class FaultConnection:
                    dialect = getattr(connection,'dialect',None)
                    def execute(self,statement,args=()):
                        cursor = connection.execute(statement,args)
                        if 'INSERT INTO '+table in statement:
                            raise RuntimeError('synthetic notice transaction crash')
                        return cursor
                yield FaultConnection()
        try:
            store.reserve_model(candidate['id'],candidate['lease_token'],db_factory=fail_after_insert,now=NOW)
            raise AssertionError('fault injector did not interrupt notice transaction')
        except RuntimeError as error:
            assert str(error)=='synthetic notice transaction crash'
        assert not notices(account) and not outboxes(account)
        assert row(candidate)['status']=='processing' and row(candidate)['model_started_at'] is None
        assert quota_count(account)==10
        assert not reserve(candidate)
        assert_notice(candidate)
        assert len(notices(account))==len(outboxes(account))==1

    # Independent incoming conversations still share one account+sender notice.
    account = 'quota-notice-concurrent'
    configure(account)
    exhaust(account)
    def exhausted_incoming(number):
        job = incoming(account, 'quota-conversation-'+str(number))
        assert not reserve(job)
        return job
    requests = parallel(exhausted_incoming, 12)
    saved = [row(job) for job in requests]
    ready = [job for job in saved if job['status']=='ready']
    assert len(ready)==1 and sum(job['status']=='blocked' for job in saved)==11
    first = assert_notice(ready[0])
    assert len(notices(account))==1 and notices(account)[0]['job_id']==first['id']
    assert len(outboxes(account))==1 and outboxes(account)[0]['status']=='ready'
    assert quota_count(account)==10
    assert all(job['model_started_at'] is None and job['model_completed_at'] is None for job in saved)
    claimed = [job for job in parallel(lambda _:send(account),8) if job]
    assert len(claimed)==1 and claimed[0]['id']==first['id']
    assert store.send_authorized(first['id'],claimed[0]['send_token'],db_factory=factory,now=NOW)
    finish(claimed[0],'uncertain')
    assert_duplicate(incoming(account,'after-uncertain'),account)
    assert send(account) is None and len(notices(account))==len(outboxes(account))==1
    assert outboxes(account)[0]['status']=='uncertain'

    # A commit followed by a crash leaves one ready notice. A crash after its
    # send claim becomes uncertain; neither path frees the once/window claim.
    account = 'quota-notice-crash'
    configure(account)
    exhaust(account)
    candidate = incoming(account,'notice-before-crash')
    assert not reserve(candidate)
    assert_notice(candidate)
    later = NOW+timedelta(seconds=301)
    store.recover_expired(account_id=account,db_factory=factory,now=later)
    assert row(candidate)['status']=='ready'
    crashed = send(account,later)
    assert crashed and crashed['id']==candidate['id']
    assert send(account,later+timedelta(seconds=1)) is None
    after_crash = later+timedelta(seconds=301)
    assert send(account,after_crash) is None and row(candidate)['status']=='uncertain'
    assert_duplicate(incoming(account,'after-send-crash',now=after_crash),account,after_crash)
    assert len(notices(account))==len(outboxes(account))==1

    # Authorization changes fence old sends but never release a notice claim.
    account = 'quota-notice-generation'
    configure(account)
    exhaust(account)
    candidate = incoming(account,'notice-before-stop')
    assert not reserve(candidate)
    old_send = send(account)
    store.update_settings(account,mode='off',db_factory=factory,now=NOW)
    configure(account)
    assert not store.send_authorized(old_send['id'],old_send['send_token'],db_factory=factory,now=NOW)
    assert_duplicate(incoming(account,'after-reenable'),account)
    finish(old_send,'blocked')
    assert len(notices(account))==len(outboxes(account))==1 and send(account) is None

    account = 'quota-ready-generation'
    configure(account)
    exhaust(account)
    candidate = incoming(account,'ready-before-change')
    assert not reserve(candidate)
    store.update_settings(account,approved_sha256=[SHA],db_factory=factory,now=NOW)
    assert row(candidate)['status']=='blocked'
    assert_duplicate(incoming(account,'after-config-change'),account)
    assert len(notices(account))==len(outboxes(account))==1

    # An old ready notice expires at UTC midnight, even within normal send TTL.
    start = NOW.replace(hour=0,minute=0,second=0,microsecond=0)
    near_midnight = start+timedelta(days=1,seconds=-5)
    next_window = start+timedelta(days=1)
    account = 'quota-notice-window'
    configure(account,near_midnight)
    exhaust(account,near_midnight)
    expired = incoming(account,'ready-before-midnight',now=near_midnight)
    assert not reserve(expired,near_midnight)
    assert_notice(expired,near_midnight)
    assert send(account,next_window) is None
    assert row(expired)['status']=='blocked'
    assert row(expired)['diagnostics']['reason']=='budget_notice_window_expired'
    assert quota_count(account,next_window)==0
    exhaust(account,next_window)
    renewed = incoming(account,'fresh-new-window-notice',now=next_window)
    assert not reserve(renewed,next_window)
    assert_notice(renewed,next_window)
    assert len(notices(account))==2 and len(outboxes(account))==2
    assert [utc(item['window_start']) for item in notices(account)]==[start,next_window]
    assert row(expired)['status']=='blocked'  # no old job is reopened
    finish(send(account,next_window),'sent',next_window)

    # Even a successfully sent fixed notice is not conversational model history.
    followup = incoming(account,'text-after-budget-notice',now=next_window,
        conversation=row(renewed)['conversation_id'])
    assert store.recent_exchanges(account_id=account,sender='owner',conversation_id=followup['conversation_id'],
        before_job_id=followup['id'],db_factory=factory,now=next_window)==[]
    store.prepare_reply(followup['id'],followup['lease_token'],terminal_status='blocked',db_factory=factory,now=next_window)

    # The final pre-request guard independently fences a notice crossing midnight,
    # despite its otherwise-valid lease. Guard reads do not retry or release it.
    account = 'quota-notice-final-guard'
    configure(account,near_midnight)
    exhaust(account,near_midnight)
    candidate = incoming(account,'claimed-before-midnight',now=near_midnight)
    assert not reserve(candidate,near_midnight)
    outgoing = send(account,near_midnight)
    assert utc(outgoing['lease_until'])>next_window
    assert store.send_authorized(outgoing['id'],outgoing['send_token'],db_factory=factory,now=near_midnight)
    assert not store.send_authorized(outgoing['id'],outgoing['send_token'],db_factory=factory,now=next_window)
    assert row(candidate)['status']=='sending'
    finish(outgoing,'blocked',next_window)
    assert len(notices(account))==1 and len(outboxes(account))==1

    # A delayed old-window job or a future-window timestamp cannot consume the
    # current window's notice. A later genuinely current inbound may claim it.
    account = 'quota-notice-incoming-window'
    current = next_window+timedelta(seconds=20)
    configure(account,current)
    exhaust(account,current)
    for message,created in (('delayed-old-window',near_midnight),
                            ('future-current-window',current+timedelta(seconds=60)),
                            ('future-window',next_window+timedelta(days=1))):
        stale = incoming(account,message,now=current,created_at=created)
        assert not reserve(stale,current)
        assert row(stale)['status']=='blocked'
        assert not notices(account) and not outboxes(account)
    current_notice = incoming(account,'current-window',now=current)
    assert not reserve(current_notice,current)
    assert_notice(current_notice,current)
    assert len(notices(account))==len(outboxes(account))==1
    with factory() as connection:
        stranger = store.enqueue(connection,account_id=account,message_id='other-sender',event_id='other-sender-event',
            sender='not-owner',conversation_id='other-sender-conversation',payload=payload,now=current)
    assert stranger['status']=='blocked'
    assert all(item['sender']=='owner' for item in notices(account))

    # Locally extracting a PDF before the quota check does not turn the fixed
    # notice into document context. No model call or successful PDF answer exists.
    account = 'quota-notice-pdf-context'
    configure(account)
    store.update_settings(account,approved_sha256=[SHA],db_factory=factory,now=NOW)
    exhaust(account)
    pdf_payload = {'question':'What does this document say?','question_allowed':True,
        'question_kind':'document_question','attachment_count':1,'attachments':[{'mime':'application/pdf'}]}
    with factory() as connection:
        store.enqueue(connection,account_id=account,message_id='pdf-at-cap',event_id='pdf-at-cap-event',
            sender='owner',conversation_id='pdf-context-conversation',payload=pdf_payload,now=NOW)
    pdf_notice = store.claim_job(account_id=account,db_factory=factory,now=NOW)
    store.checkpoint_document(pdf_notice['id'],pdf_notice['lease_token'],text=TEXT,sha256=SHA,status='ok',
        db_factory=factory,now=NOW)
    assert not reserve(pdf_notice)
    assert_notice(pdf_notice)
    finish(send(account),'sent')
    assert store.recent_context(account_id=account,sender='owner',conversation_id='pdf-context-conversation',
        db_factory=factory,now=NOW) is None

    # A true successful PDF followed by a quota notice is still not a completed
    # model-understanding pilot, even with exact source linkage and owner receipt.
    account = 'quota-notice-pdf-acceptance'
    configure(account)
    store.update_settings(account,approved_sha256=[SHA],db_factory=factory,now=NOW)
    with factory() as connection:
        store.enqueue(connection,account_id=account,message_id='real-pdf',event_id='real-pdf-event',
            sender='owner',conversation_id='pdf-proof-conversation',payload=pdf_payload,now=NOW)
    document = store.claim_job(account_id=account,db_factory=factory,now=NOW)
    store.checkpoint_document(document['id'],document['lease_token'],text=TEXT,sha256=SHA,status='ok',
        db_factory=factory,now=NOW)
    assert reserve(document)
    store.save_model(document['id'],document['lease_token'],reply_text='Synthetic model document answer',
        diagnostics={'model_success':True},db_factory=factory,now=NOW)
    store.prepare_reply(document['id'],document['lease_token'],db_factory=factory,now=NOW)
    finish(send(account),'sent')
    exhaust(account)
    with factory() as connection:
        store.enqueue(connection,account_id=account,message_id='capped-followup',event_id='capped-followup-event',
            sender='owner',conversation_id='pdf-proof-conversation',
            payload={**pdf_payload,'attachment_count':0,'attachments':[]},now=NOW)
    capped_followup = store.claim_job(account_id=account,db_factory=factory,now=NOW)
    store.checkpoint_document(capped_followup['id'],capped_followup['lease_token'],text=TEXT,sha256=SHA,status='ok',
        context_source_job_id=document['id'],db_factory=factory,now=NOW)
    assert not reserve(capped_followup)
    assert_notice(capped_followup)
    finish(send(account),'sent')
    try:
        store.update_settings(account,mode='routine',acceptance={'owner_receipt_confirmed':True,
            'document_job_id':document['id'],'followup_job_id':capped_followup['id']},db_factory=factory,now=NOW)
        raise AssertionError('fixed local quota notice substituted for a model followup')
    except ValueError:
        pass
    assert store.get_settings(account,db_factory=factory)['mode']=='owner_pilot'

    # The existing fully accepted routine fixture retains its 50-call cap; this
    # owner-pilot-only notice must never be introduced into routine handling.
    account = 'pdf-root-history'
    assert store.get_settings(account,db_factory=factory)['mode']=='routine'
    exhaust(account,limit=50)
    routine = incoming(account,'routine-cap-reached')
    assert not reserve(routine)
    assert row(routine)['status']=='blocked' and row(routine)['model_started_at'] is None
    assert not notices(account)
    assert quota_count(account)==50


def verify_recent_attachment_outcome(factory):
    """Exercise the PostgreSQL JSONB predicate and both stale-PDF regressions."""
    from app import whatsapp_agent_store as store
    account, sender, conversation = 'attachment-outcome-pg', 'owner', 'attachment-thread'
    store.update_settings(account,mode='owner_pilot',pilot_sender=sender,approved_sha256=[SHA],
        db_factory=factory,now=NOW)
    attachment = {'question':'Review this file','question_allowed':True,'question_kind':'document_question',
        'attachment_count':1,'attachments':[{'mime':'application/pdf','url':'https://private.invalid/not-returned'}]}
    followup = {**attachment,'attachment_count':0,'attachments':[]}

    def enqueue_and_claim(message,payload):
        with factory() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(conversation,))
            store.enqueue(connection,account_id=account,message_id=message,event_id='event-'+message,
                sender=sender,conversation_id=conversation,payload=payload,now=NOW)
        job=store.claim_job(account_id=account,db_factory=factory,now=NOW)
        assert job
        return job

    def completed_read(message,*,document_status='unavailable',outcome='sent',payload=attachment):
        job=enqueue_and_claim(message,payload)
        store.checkpoint_document(job['id'],job['lease_token'],text=TEXT if document_status=='ok' else '',
            sha256=SHA if document_status=='ok' else None,status=document_status,db_factory=factory,now=NOW)
        store.prepare_reply(job['id'],job['lease_token'],reply_text='Synthetic local attachment result',
            db_factory=factory,now=NOW)
        sending=store.claim_send(account_id=account,db_factory=factory,now=NOW)
        store.finish_send(job['id'],sending['send_token'],status=outcome,db_factory=factory,now=NOW)
        return job

    older=completed_read('older-approved-pdf',document_status='ok')
    newer=completed_read('newer-unread-pdf',outcome='uncertain')
    for number in range(32):
        completed_read('attachmentless-followup-'+str(number),payload=followup)
    target=enqueue_and_claim('current-question',followup)
    scope=dict(account_id=account,sender=sender,conversation_id=conversation,before_job_id=target['id'],
               db_factory=factory,now=NOW)
    expected={'id':newer['id'],'document_status':'unavailable'}
    assert store.recent_attachment_outcome(**scope)==expected
    assert store.recent_context(**scope)['id']==older['id']
    # Completed document-checkpoint evidence does not depend on send success,
    # job.completed_at, or whether the local response has even been dispatched.
    with factory() as connection:
        connection.execute("UPDATE whatsapp_agent_jobs SET status='ready',completed_at=NULL WHERE id=%s",(newer['id'],))
    assert store.recent_attachment_outcome(**scope)==expected
    for field in ('account_id','sender','conversation_id'):
        assert store.recent_attachment_outcome(**{**scope,field:'other'}) is None
    store.update_settings(account,mode='off',db_factory=factory,now=NOW)
    assert store.recent_attachment_outcome(**scope) is None


def verify_quoted_attachment_context(factory):
    """Exact platform-ID quote lookup and absent-MIME parsed-file eligibility."""
    from app import whatsapp_agent_store as store
    account,sender,conversation='quoted-attachment-pg','owner','quoted-thread'
    store.update_settings(account,mode='owner_pilot',pilot_sender=sender,approved_sha256=[SHA],
        db_factory=factory,now=NOW)
    candidate={'question':'Review this file','question_allowed':True,'question_kind':'document_question',
        'attachment_count':1,'attachments':[{'mime':'unknown','kind':'file','mime_status':'absent'}]}
    followup={**candidate,'attachment_count':0,'attachments':[]}
    assert store._pdf_payload(candidate)
    for kind in ('image','audio','share'):
        assert not store._pdf_payload({**candidate,'attachments':[{'mime':'application/pdf','kind':kind}]})

    def enqueue(message,payload,event=None):
        with factory() as connection:
            return store.enqueue(connection,account_id=account,message_id=message,event_id=event or 'event-'+message,
                sender=sender,conversation_id=conversation,payload=payload,now=NOW)
    def claim():return store.claim_job(account_id=account,db_factory=factory,now=NOW)
    def finish(job,status):
        sending=store.claim_send(account_id=account,db_factory=factory,now=NOW)
        assert sending and sending['id']==job['id']
        store.finish_send(job['id'],sending['send_token'],status=status,db_factory=factory,now=NOW)

    enqueue('platform-source-id',candidate)
    source=claim()
    store.checkpoint_document(source['id'],source['lease_token'],text=TEXT,sha256=SHA,status='ok',
        db_factory=factory,now=NOW)
    assert store.reserve_model(source['id'],source['lease_token'],db_factory=factory,now=NOW)
    store.save_model(source['id'],source['lease_token'],reply_text='Synthetic verified PDF answer',
        diagnostics={'model_success':True},db_factory=factory,now=NOW)
    store.prepare_reply(source['id'],source['lease_token'],db_factory=factory,now=NOW)
    finish(source,'sent')
    enqueue('platform-newer-failure',candidate)
    newer=claim()
    store.checkpoint_document(newer['id'],newer['lease_token'],text='',sha256=None,status='unavailable',
        db_factory=factory,now=NOW)
    store.prepare_reply(newer['id'],newer['lease_token'],reply_text='Synthetic local read failure',
        db_factory=factory,now=NOW)
    finish(newer,'uncertain')
    assert enqueue('platform-source-id',candidate,event='raw-envelope-alias')['id']==source['id']
    enqueue('platform-current-target',followup)
    target=claim()
    scope=dict(account_id=account,sender=sender,conversation_id=conversation,before_job_id=target['id'],
               db_factory=factory,now=NOW)
    assert store.recent_attachment_outcome(**scope)=={'id':newer['id'],'document_status':'unavailable'}
    quoted={**scope,'message_id':'platform-source-id'}
    assert store.recent_attachment_outcome(**quoted)=={'id':source['id'],'document_status':'ok'}
    assert store.recent_context(**quoted)['id']==source['id']
    assert store.recent_context(**{**scope,'message_id':'platform-newer-failure'}) is None
    for unknown in ('unknown-platform-id','event-platform-source-id','raw-envelope-alias','platform-%'):
        assert store.recent_attachment_outcome(**{**scope,'message_id':unknown}) is None
        assert store.recent_context(**{**scope,'message_id':unknown}) is None
    for field in ('account_id','sender','conversation_id'):
        assert store.recent_attachment_outcome(**{**quoted,field:'other'}) is None
        assert store.recent_context(**{**quoted,field:'other'}) is None
    # Both quote helpers reject stale source timing without latest-source fallback.
    with factory() as connection:
        connection.execute('UPDATE whatsapp_agent_jobs SET document_checkpointed_at=%s WHERE id=%s',
            ((NOW-timedelta(days=1)).isoformat(),source['id']))
    assert store.recent_attachment_outcome(**quoted) is None and store.recent_context(**quoted) is None
    with factory() as connection:
        connection.execute('UPDATE whatsapp_agent_jobs SET document_checkpointed_at=%s WHERE id=%s',(NOW.isoformat(),source['id']))
    store.update_settings(account,mode='off',db_factory=factory,now=NOW)
    store.update_settings(account,mode='owner_pilot',pilot_sender=sender,approved_sha256=[SHA],db_factory=factory,now=NOW)
    assert store.recent_attachment_outcome(**quoted) is None and store.recent_context(**quoted) is None
    enqueue('new-generation-target',followup)
    current=claim()
    current_quote={**quoted,'before_job_id':current['id']}
    assert store.recent_attachment_outcome(**current_quote) is None and store.recent_context(**current_quote) is None


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
