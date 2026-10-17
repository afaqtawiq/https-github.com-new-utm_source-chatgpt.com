"""Durable, conversation-scoped human takeover. No provider calls or import-time DB access.

Callers authenticate webhook/admin identities. A send_guard must surround the final
provider call; pause obtains the same lock and cannot revoke an already-started send.
Paused receipts are retained for staff, never queued or replayed on resume.
"""
from contextlib import contextmanager
import hashlib
import json

from app import whatsapp_agent_store as store

database = store.database
StateConflict = store.StateConflict
DDL = (
    '''CREATE TABLE IF NOT EXISTS whatsapp_conversation_takeovers (
        account_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
        sender TEXT NOT NULL, paused BOOLEAN NOT NULL DEFAULT FALSE, generation BIGINT NOT NULL DEFAULT 0,
        updated_by TEXT, updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(account_id,conversation_id))''',
    '''CREATE TABLE IF NOT EXISTS whatsapp_takeover_audit (
        id BIGSERIAL PRIMARY KEY, account_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
        generation BIGINT NOT NULL, paused BOOLEAN NOT NULL, actor TEXT NOT NULL,
        happened_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS whatsapp_takeover_receipts (
        id BIGSERIAL PRIMARY KEY, account_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
        message_id TEXT NOT NULL, sender TEXT NOT NULL, body TEXT NOT NULL,
        attachment_count INTEGER NOT NULL, generation BIGINT NOT NULL,
        received_at TIMESTAMPTZ NOT NULL, UNIQUE(account_id,message_id))''',
    '''CREATE TABLE IF NOT EXISTS whatsapp_takeover_receipt_events (
        account_id TEXT NOT NULL, event_id TEXT NOT NULL,
        receipt_id BIGINT NOT NULL REFERENCES whatsapp_takeover_receipts(id),
        PRIMARY KEY(account_id,event_id))''',
)


def init_storage(*, db_factory=None):
    with (db_factory or database)() as connection:
        for statement in DDL:
            connection.execute(statement)


def lock_key(account_id, conversation_id):
    for name, value in [('account_id', account_id), ('conversation_id', conversation_id)]:
        store._identifier(value, name)
    value = json.dumps(['wa-takeover', account_id, conversation_id], separators=(',', ':'))
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], 'big', signed=True)


def lock(connection, account_id, conversation_id):
    # Bound contention so waiting requests cannot indefinitely exhaust the worker
    # pool needed to release an in-flight provider send's fence. No retry here.
    connection.execute("SET LOCAL lock_timeout = '2s'")
    connection.execute('SELECT pg_advisory_xact_lock(%s)', (lock_key(account_id, conversation_id),))


def _state(connection, account_id, conversation_id):
    row = connection.execute('''SELECT * FROM whatsapp_conversation_takeovers
        WHERE account_id=%s AND conversation_id=%s''', (account_id, conversation_id)).fetchone()
    return dict(row) if row else dict(account_id=account_id, conversation_id=conversation_id,
                                     paused=False, generation=0)


def read_state(account_id, conversation_id, *, db_factory=None):
    lock_key(account_id, conversation_id)
    with (db_factory or database)() as connection:
        return _state(connection, account_id, conversation_id)



def read_recipient_state(account_id, sender, *, db_factory=None):
    store._identifier(account_id, 'account_id')
    store._identifier(sender, 'sender')
    with (db_factory or database)() as connection:
        rows = connection.execute("""SELECT * FROM whatsapp_conversation_takeovers
            WHERE account_id=%s AND sender=%s""", (account_id, sender)).fetchall()
        if len(rows) > 1:
            raise StateConflict('ambiguous recipient conversation; refuse automatic send')
        return dict(rows[0]) if rows else None


def set_paused(account_id, conversation_id, paused, actor, expected_generation, *, sender, db_factory=None):
    if type(paused) is not bool or type(expected_generation) is not int or expected_generation < 0:
        raise ValueError('explicit boolean and nonnegative generation required')
    actor = store._identifier(str(actor), 'actor')
    sender = store._identifier(sender, 'sender')
    with (db_factory or database)() as connection:
        lock(connection, account_id, 'recipient:' + sender)
        lock(connection, account_id, conversation_id)
        state = _state(connection, account_id, conversation_id)
        if state['generation'] != expected_generation:
            raise StateConflict('conversation state changed; refresh before acting')
        now = store._time()
        generation = state['generation'] + 1
        connection.execute('''INSERT INTO whatsapp_conversation_takeovers
            (account_id,conversation_id,sender,paused,generation,updated_by,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(account_id,conversation_id)
            DO UPDATE SET sender=EXCLUDED.sender,paused=EXCLUDED.paused,generation=EXCLUDED.generation,
                updated_by=EXCLUDED.updated_by,updated_at=EXCLUDED.updated_at''',
            (account_id, conversation_id, sender, paused, generation, actor, now))
        connection.execute('''INSERT INTO whatsapp_takeover_audit
            (account_id,conversation_id,generation,paused,actor,happened_at)
            VALUES(%s,%s,%s,%s,%s,%s)''', (account_id, conversation_id, generation, paused, actor, now))
        # Both transitions invalidate work created before the explicit action.
        # Sending/uncertain are deliberately untouched; never infer failed delivery.
        jobs = connection.execute('''SELECT * FROM whatsapp_agent_jobs
            WHERE account_id=%s AND conversation_id=%s
            AND status IN ('pending','processing','ready') ORDER BY id FOR UPDATE''',
            (account_id, conversation_id)).fetchall()
        for raw in jobs:
            store._terminal(connection, store._row(raw), 'blocked', now,
                            {'reason': 'conversation_takeover', 'takeover_generation': generation})
        return _state(connection, account_id, conversation_id)


def authorization(account_id, conversation_id, generation, *, db_factory=None):
    state = read_state(account_id, conversation_id, db_factory=db_factory)
    return type(generation) is int and not state['paused'] and generation == state['generation']


@contextmanager
def send_guard(account_id, conversation_id, generation, *, sender=None, db_factory=None):
    """Hold recipient then conversation fences through the final external send.

    For templates without a provider conversation, use ``recipient:<sender>`` as
    conversation_id. The recipient fence also blocks a concurrent first pause.
    """
    with (db_factory or database)() as connection:
        recipient_rows = []
        if sender is not None:
            store._identifier(sender, 'sender')
            lock(connection, account_id, 'recipient:' + sender)
            recipient_rows = connection.execute("""SELECT * FROM whatsapp_conversation_takeovers
                WHERE account_id=%s AND sender=%s""", (account_id, sender)).fetchall()
        lock(connection, account_id, conversation_id)
        state = _state(connection, account_id, conversation_id)
        allowed = type(generation) is int and not state['paused'] and generation == state['generation']
        if len(recipient_rows) > 1:
            allowed = False
        elif recipient_rows:
            recipient = recipient_rows[0]
            allowed = allowed and recipient['conversation_id'] == conversation_id and not recipient['paused']
            allowed = allowed and recipient['generation'] == generation
        yield allowed


def capture_inbound(*, account_id, conversation_id, message_id, event_id, sender,
                    text='', attachment_count=0, return_state=False, db_factory=None):
    """Return True for held receipts (including retries after resume).

    IDs must come from a validated incoming webhook. Persist only bounded message
    text and attachment count; never bearer media URLs, credentials, or raw payload.
    """
    for name, value in [('message_id', message_id), ('event_id', event_id), ('sender', sender)]:
        store._identifier(value, name)
    if not isinstance(text, str) or type(attachment_count) is not int or attachment_count < 0:
        raise ValueError('invalid receipt')
    with (db_factory or database)() as connection:
        lock(connection, account_id, conversation_id)
        old = connection.execute('''SELECT r.id FROM whatsapp_takeover_receipts r
            WHERE r.account_id=%s AND (r.message_id=%s OR r.id IN
                (SELECT receipt_id FROM whatsapp_takeover_receipt_events
                 WHERE account_id=%s AND event_id=%s))''',
            (account_id, message_id, account_id, event_id)).fetchone()
        state = _state(connection, account_id, conversation_id)
        if not old and not state['paused']:
            return dict(state, held=False) if return_state else False
        if old:
            receipt_id = old['id']
        else:
            receipt_id = connection.execute('''INSERT INTO whatsapp_takeover_receipts
                (account_id,conversation_id,message_id,sender,body,attachment_count,generation,received_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(account_id,message_id)
                DO UPDATE SET message_id=EXCLUDED.message_id RETURNING id''',
                (account_id, conversation_id, message_id, sender, text[:16000],
                 min(attachment_count, 100), state['generation'], store._time())).fetchone()['id']
        connection.execute('''INSERT INTO whatsapp_takeover_receipt_events(account_id,event_id,receipt_id)
            VALUES(%s,%s,%s) ON CONFLICT(account_id,event_id) DO NOTHING''',
            (account_id, event_id, receipt_id))
        return dict(state, held=True) if return_state else True


def admission(connection, account_id, conversation_id):
    """Store enqueue hook: fence before the account-settings/job locks."""
    lock(connection, account_id, conversation_id)
    return _state(connection, account_id, conversation_id)
