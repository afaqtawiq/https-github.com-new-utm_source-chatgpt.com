"""Direct PostgreSQL query contracts; called by the isolated acceptance runner.

All fixtures are synthetic. Quote scope/age/consent are enforced by the same
recent_exchanges -> filter_history -> quoted_text_exchange chain as the worker.
No model or provider is called, and no application bootstrap is imported.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from unittest.mock import patch

from app import whatsapp_agent_store as store
from app import whatsapp_dialogue as dialogue

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def verify_context_queries(factory):
    passed = []

    def check(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        passed.append(name)

    @contextmanager
    def changed(table, key, value, **changes):
        # Table/column names below are fixed test code, never external input.
        with factory() as c:
            previous = c.execute('SELECT * FROM ' + table + ' WHERE ' + key + '=%s', (value,)).fetchone()
            c.execute('UPDATE ' + table + ' SET ' + ','.join(k + '=%s' for k in changes) +
                      ' WHERE ' + key + '=%s', (*changes.values(), value))
        try:
            yield
        finally:
            with factory() as c:
                c.execute('UPDATE ' + table + ' SET ' + ','.join(k + '=%s' for k in changes) +
                          ' WHERE ' + key + '=%s', (*(previous[k] for k in changes), value))

    class Fixture:
        def __init__(self, name):
            self.account = 'query-contract-' + name
            self.serial = 0
            store.update_settings(self.account, mode='owner_pilot', pilot_sender='owner', now=NOW,
                                  db_factory=factory)

        def enqueue(self, *, count=0, when=NOW, conversation='thread'):
            self.serial += 1
            with factory() as c:
                return store.enqueue(c, account_id=self.account, sender='owner', conversation_id=conversation,
                    message_id='synthetic-message-' + str(self.serial),
                    event_id='synthetic-event-' + str(self.serial), now=when,
                    payload={'question':'Synthetic question', 'question_allowed':True,
                             'question_kind':'conversation', 'attachment_count':count,
                             'attachments':[{'mime':'application/pdf'}] if count else []})

        def target(self):
            row = self.enqueue()
            job = store.claim_job(account_id=self.account, db_factory=factory, now=NOW)
            assert job and job['id'] == row['id']
            return job

        def source(self, *, count=0, status='none', when=NOW, conversation='thread'):
            row = self.enqueue(count=count, when=when, conversation=conversation)
            job = store.claim_job(account_id=self.account, db_factory=factory, now=when)
            assert job and job['id'] == row['id']
            store.checkpoint_document(job['id'], job['lease_token'], text='', sha256=None,
                                      status=status, db_factory=factory, now=when)
            store.prepare_reply(job['id'], job['lease_token'], reply_text='Synthetic reply',
                                db_factory=factory, now=when)
            out = store.claim_send(account_id=self.account, db_factory=factory, now=when)
            assert out and out['id'] == job['id']
            store.finish_send(job['id'], out['send_token'], status='sent',
                              provider_message_id='synthetic-receipt-' + str(job['id']),
                              db_factory=factory, now=when)
            return store.get_job(job['id'], db_factory=factory)

        def scope(self, target):
            return dict(account_id=self.account, sender='owner', conversation_id='thread',
                        before_job_id=target['id'], db_factory=factory, now=NOW)

        def evidence(self, target, **changes):
            return store.recent_attachment_evidence(**(self.scope(target) |
                {'lease_token':target['lease_token']} | changes))

        def history(self, target, **changes):
            records = store.recent_exchanges(**(self.scope(target) | changes))
            return dialogue.filter_history(records, target)

    with patch.object(store, 'database', factory), patch.object(store, '_time', wraps=store._time) as clock:
        # Consent filtering calls _time without an explicit now, so pin that
        # default while retaining parsing/conversion of fixture timestamps.
        original_time = clock._mock_wraps
        clock.side_effect = lambda value=None: original_time(NOW if value is None else value)
        f = Fixture('metadata')
        sources = [f.source(count=n, status=s) for n, s in
                   [(1, 'quarantined'), (2, 'unavailable'), (3, 'quarantined')]]
        # A read status alone is metadata; no PDF contents are returned.
        with factory() as c:
            c.execute("UPDATE whatsapp_agent_jobs SET document_status='ok' WHERE id=%s", (sources[0]['id'],))
        target = f.target()
        expected = {'count':6, 'partial':False, 'order':'oldest_to_newest', 'events':[
            {'count':1, 'status':'previously_read'}, {'count':2, 'status':'unreadable'},
            {'count':3, 'status':'held_for_review'}]}
        check('metadata counts, status order and exact projection', f.evidence(target), expected)
        for key in ('account_id', 'sender', 'conversation_id'):
            check('metadata wrong ' + key, f.evidence(target, **{key:'other'}), None)
        for token in ('wrong', '', None):
            check('metadata lease ' + repr(token), f.evidence(target, lease_token=token), None)
        newest = f.enqueue(count=5)
        with factory() as c:
            c.execute("UPDATE whatsapp_agent_jobs SET document_status='quarantined',document_checkpointed_at=%s WHERE id=%s",
                      (NOW.isoformat(), newest['id']))
        check('metadata excludes newer message IDs', f.evidence(target), expected)
        with changed('whatsapp_agent_jobs', 'id', target['id'], document_status='quarantined',
                     document_checkpointed_at=NOW.isoformat(), payload=json.dumps({'attachment_count':7,'attachments':[{'mime':'application/pdf'}]})):
            check('metadata excludes current message', f.evidence(target), expected)

        single = Fixture('metadata-fences')
        source = single.source(count=1, status='quarantined')
        current = single.target()
        valid = single.evidence(current)
        for row, label in ((source, 'source'), (current, 'target')):
            for column in ('created_at', 'document_checkpointed_at') if label == 'source' else ('created_at',):
                for suffix, stamp in [('cutoff', NOW-timedelta(days=1)), ('future', NOW+timedelta(microseconds=1))]:
                    with changed('whatsapp_agent_jobs', 'id', row['id'], **{column:stamp.isoformat()}):
                        check('metadata ' + label + ' ' + column + ' ' + suffix, single.evidence(current), None)
                with changed('whatsapp_agent_jobs', 'id', row['id'], **{column:(NOW-timedelta(days=1)+timedelta(microseconds=1)).isoformat()}):
                    check('metadata ' + label + ' ' + column + ' inside age', single.evidence(current), valid)
            with changed('whatsapp_agent_jobs', 'id', row['id'], authorization_generation=0):
                check('metadata ' + label + ' generation', single.evidence(current), None)
        for changes in ({'lease_until':NOW.isoformat()}, {'status':'ready'}):
            with changed('whatsapp_agent_jobs', 'id', current['id'], **changes):
                check('metadata inactive target ' + next(iter(changes)), single.evidence(current), None)
        with changed('whatsapp_agent_jobs', 'id', source['id'], context_source_job_id=current['id']):
            check('metadata excludes inherited document', single.evidence(current), None)
        with changed('whatsapp_agent_settings', 'account_id', single.account, mode='off'):
            check('metadata disabled account', single.evidence(current), None)
        with changed('whatsapp_agent_jobs', 'id', source['id'], created_at=(NOW-timedelta(seconds=60)).isoformat()):
            check('metadata custom age boundary', single.evidence(current, max_age_seconds=60), None)
            check('metadata custom age inside', single.evidence(current, max_age_seconds=61), valid)
        with changed('whatsapp_agent_jobs', 'id', source['id'], created_at=(NOW-timedelta(days=1)).isoformat()):
            check('metadata age cannot exceed one day', single.evidence(current, max_age_seconds=999999), None)

        window = Fixture('metadata-window')
        rows = [window.source(count=i+1, status='quarantined') for i in range(13)]
        # Text/document followups must be filtered BEFORE the SQL row limit.
        for _ in range(33):
            window.source()
        end = window.target()
        result = window.evidence(end)
        check('metadata 13 events selects latest 12 chronologically', result,
              {'count':sum(range(2,14)), 'partial':True, 'order':'oldest_to_newest',
               'events':[{'count':i,'status':'held_for_review'} for i in range(2,14)]})
        with changed('whatsapp_agent_jobs', 'id', rows[0]['id'], document_status='none'):
            check('metadata exact 12 is not partial', window.evidence(end), result | {'partial':False})

        quotes = Fixture('quotes')
        pairs = [quotes.source(when=NOW-timedelta(seconds=10-i)) for i in range(6)]
        foreign = quotes.source(conversation='other-thread')
        other = Fixture('other-account').source()
        pdf = quotes.source(count=1, status='quarantined')
        end = quotes.target()
        history = quotes.history(end)
        check('text history latest four in chronological order', [r['job_id'] for r in history], [r['id'] for r in pairs[-4:]])
        def resolve(message, **changes):
            return store.quoted_text_exchange(quotes.history(end, **changes), message)
        selected = pairs[-1]
        expected_pair = [history[-1]]
        check('exact inbound text quote', resolve(selected['message_id']), expected_pair)
        receipt = 'synthetic-receipt-' + str(selected['id'])
        check('exact outbound sent text quote', resolve(receipt), expected_pair)
        for label, message in [('unknown','unknown'), ('event alias',selected['event_id']),
                               ('wildcard','synthetic-message-%'), ('old outside count',pairs[0]['message_id']),
                               ('other conversation',foreign['message_id']),
                               ('other account receipt','synthetic-receipt-' + str(other['id'])),
                               ('PDF inbound',pdf['message_id']), ('PDF outbound','synthetic-receipt-' + str(pdf['id'])),
                               ('empty',''), ('null',None)]:
            check('quote rejects ' + label, resolve(message), ())
        for key in ('account_id','sender','conversation_id'):
            check('quote wrong ' + key, resolve(receipt, **{key:'other'}), ())
        with changed('whatsapp_agent_outbox', 'job_id', selected['id'], status='uncertain'):
            check('quote rejects unsent receipt', resolve(receipt), ())
            check('inbound quote does not need outbound receipt match', resolve(selected['message_id']), expected_pair)
        with changed('whatsapp_agent_outbox', 'job_id', pairs[-2]['id'], provider_message_id=receipt):
            check('ambiguous receipt never selects a source', resolve(receipt), ())
        for column in ('created_at','completed_at'):
            for label, stamp in [('cutoff',NOW-timedelta(days=1)), ('future',NOW+timedelta(microseconds=1))]:
                with changed('whatsapp_agent_jobs', 'id', selected['id'], **{column:stamp.isoformat()}):
                    check('quote ' + column + ' ' + label, resolve(receipt), ())
        check('quote obeys custom age', resolve(receipt, max_age_seconds=5), ())
        check('quote custom age includes recent source', resolve(receipt, max_age_seconds=6), expected_pair)
        for row, label in ((selected,'source'), (end,'target')):
            with changed('whatsapp_agent_jobs', 'id', row['id'], authorization_generation=0):
                check('quote ' + label + ' generation', resolve(receipt), ())
        with changed('whatsapp_agent_jobs', 'id', end['id'], lease_until=NOW.isoformat()):
            check('quote target lease expired', resolve(receipt), ())

        # An actual grant is attached to a derived text exchange. Revocation
        # removes that exchange before quote resolution, but not attachment
        # receipt metadata, which carries no administrative text permission.
        with patch.dict(os.environ, {dialogue.SHARING_FLAG:'1'}):
            with factory() as c:
                c.execute('CREATE TABLE IF NOT EXISTS users(id BIGINT PRIMARY KEY,role TEXT,is_active INTEGER)')
                c.execute('CREATE TABLE IF NOT EXISTS user_mfa(user_id BIGINT PRIMARY KEY,mfa_enabled INTEGER)')
                c.execute("INSERT INTO users VALUES(77,'admin',1) ON CONFLICT(id) DO NOTHING")
                c.execute('INSERT INTO user_mfa VALUES(77,1) ON CONFLICT(user_id) DO NOTHING')
                permission = dialogue.grant_permission(c, {'token':'synthetic-consent-query',
                    'account_id':quotes.account,'recipient':'owner','conversation_id':'thread',
                    'created_by':77,'state':'draft','body':'هل موعد الاجتماع مناسب؟'},
                    77, scope_kind='conversation', now=NOW)
                c.execute('UPDATE whatsapp_agent_jobs SET diagnostics=%s WHERE id=%s',
                          (json.dumps({'administrative_permission_ids':[permission]}), selected['id']))
            before = quotes.evidence(end)
            check('quote with active administrative grant', resolve(receipt), expected_pair)
            with factory() as c:
                dialogue.revoke_permission(c, permission, account_id=quotes.account, actor_id=77, now=NOW)
            check('quote derived from revoked grant excluded', resolve(receipt), ())
            check('revocation leaves independent ordinary quote', bool(resolve(pairs[-2]['message_id'])), True)
            check('revocation does not authorize or erase attachment metadata', quotes.evidence(end), before)

    print('PASS: direct PostgreSQL context queries: ' + str(len(passed)) + ' named checks; external calls: 0.')
    for name in passed:
        print('  PASS: ' + name)
