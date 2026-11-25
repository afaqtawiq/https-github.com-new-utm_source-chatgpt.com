"""Team documents: the webhook is answered at once, the message is saved, processed in the background, and resumed after
a restart without a second answer (owner, 25 Nov 2026: Promate documents lost — 499 timeouts + restart)."""
import asyncio
import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace

from app import zernio_receiver as zr
from app.storage import db


def request_for(payload):
    raw = json.dumps(payload).encode()

    async def body():
        return raw
    return SimpleNamespace(body=body, headers={'x-zernio-signature': hmac.new(b'test-secret', raw, hashlib.sha256).hexdigest()})


def payload(event_id, attachments=True):
    return {'id': event_id, 'event': 'message.received', 'account': {'id': 'acc-1', 'platform': 'whatsapp'},
            'conversation': {'id': 'conv-bg'},
            'message': {'id': 'm-' + event_id, 'direction': 'incoming', 'text': '',
                        'attachments': [{'type': 'document', 'url': 'https://example.invalid/a.pdf'}] if attachments else []}}


def test_team_document_is_queued_processed_and_resumed_once(monkeypatch):
    monkeypatch.setenv('ZERNIO_WEBHOOK_SECRET', 'test-secret')
    monkeypatch.setenv('ZERNIO_API_KEY', 'k')
    monkeypatch.setattr(zr, 'ensure_tables', lambda: None)
    monkeypatch.setattr(zr, 'ensure_intake_tables', lambda: None)
    monkeypatch.setattr(zr, 'takeover_inbound', None)
    monkeypatch.setattr(zr, 'durable_inbound', lambda p: {'legacy_local_only': True, 'team_agent': True})
    calls = []

    async def slow_process(p, takeover, legacy):
        await asyncio.sleep(0.05)
        calls.append(p['id'])
        return {'ok': True, 'state': 'sent'}
    monkeypatch.setattr(zr, 'process', slow_process)
    spawned = []
    monkeypatch.setattr(zr, '_spawn', lambda event_id: spawned.append(event_id))
    ev = 'bg-' + uuid.uuid4().hex[:10]

    # 1) The webhook answers immediately; nothing is processed inside the request.
    result = asyncio.run(zr.receive(request_for(payload(ev))))
    assert result == {'ok': True, 'queued': True, 'background': True} and spawned == [ev] and calls == []
    # Provider retry of the same event: not queued twice.
    assert asyncio.run(zr.receive(request_for(payload(ev)))) == {'ok': True, 'duplicate': True}

    # 2) "Restart": the job was never run → it is found as unfinished and run once.
    assert ev in zr.unfinished_jobs(min_age_seconds=0)
    assert asyncio.run(zr.run_job(ev)) == {'ok': True, 'state': 'sent'} and calls == [ev]
    assert ev not in zr.unfinished_jobs(min_age_seconds=0)
    assert asyncio.run(zr.run_job(ev)) is None and calls == [ev]   # done → never processed again
    with db() as c:
        assert c.execute('SELECT state FROM zernio_inbound_jobs WHERE event_id=%s', (ev,)).fetchone()['state'] == 'done'

    # 3) A job interrupted mid-way (state running) is resumed; a failing one stops after 3 attempts.
    ev2 = 'bg-' + uuid.uuid4().hex[:10]
    asyncio.run(zr.receive(request_for(payload(ev2))))

    async def boom(p, takeover, legacy):
        raise RuntimeError('model down')
    monkeypatch.setattr(zr, 'process', boom)
    with db() as c:
        c.execute("UPDATE zernio_inbound_jobs SET state='running' WHERE event_id=%s", (ev2,))
    assert ev2 in zr.unfinished_jobs(min_age_seconds=0)
    assert asyncio.run(zr.run_job(ev2)) is None
    with db() as c:
        row = c.execute('SELECT state, attempts FROM zernio_inbound_jobs WHERE event_id=%s', (ev2,)).fetchone()
    assert row['state'] == 'failed' and row['attempts'] == 1


def test_text_and_customer_messages_keep_the_direct_path(monkeypatch):
    monkeypatch.setenv('ZERNIO_WEBHOOK_SECRET', 'test-secret')
    monkeypatch.setenv('ZERNIO_API_KEY', 'k')
    monkeypatch.setattr(zr, 'ensure_tables', lambda: None)
    monkeypatch.setattr(zr, 'ensure_intake_tables', lambda: None)
    monkeypatch.setattr(zr, 'takeover_inbound', None)
    seen = []

    async def direct(p, takeover, legacy):
        seen.append((p['id'], legacy))
        return {'ok': True, 'direct': True}
    monkeypatch.setattr(zr, 'process', direct)
    monkeypatch.setattr(zr, 'durable_inbound', lambda p: {'legacy_local_only': True, 'team_agent': True})
    assert asyncio.run(zr.receive(request_for(payload('t-1', attachments=False)))) == {'ok': True, 'direct': True}
    monkeypatch.setattr(zr, 'durable_inbound', lambda p: {'legacy_local_only': True})   # not a team member
    assert asyncio.run(zr.receive(request_for(payload('t-2')))) == {'ok': True, 'direct': True}
    assert seen == [('t-1', False), ('t-2', True)]
