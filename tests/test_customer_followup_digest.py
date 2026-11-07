"""Offline owner-only briefing tests. No real phone, DB or provider calls."""
import asyncio
from contextlib import contextmanager
from datetime import date
import hashlib
import sys
import types

import pytest
import app
from app import customer_followup_digest as d

PHONE = '+12025550101'
DAY = date(2026, 11, 8)


@pytest.fixture
def rig(monkeypatch):
    calls = {'original': [], 'email': [], 'wa': [], 'records': [], 'claims': 0}
    monkeypatch.setenv('WHATSAPP_COMMAND_OWNER', PHONE)
    monkeypatch.setenv('ZERNIO_WHATSAPP_ACCOUNT_ID', 'fixture-account')
    monkeypatch.setenv('CUSTOMER_FOLLOWUP_DIGEST_ENABLED', '1')
    monkeypatch.setenv('CUSTOMER_FOLLOWUP_OWNER_SHA256', hashlib.sha256(PHONE.encode()).hexdigest())
    async def original(text):
        calls['original'].append(text)
        return 'original'
    async def email(text):
        calls['email'].append(text)
        return 'email'
    class Blocked(Exception):
        pass
    @contextmanager
    def guard(callback):
        calls['guard'] = callback
        yield
    async def send(recipient, text, **kwargs):
        calls['guard']()
        calls['wa'].append((recipient, text, kwargs))
        if calls.get('send_error'):
            raise calls['send_error']
        return calls.get('receipt', {'messages': [{'id': 'fixture-receipt'}]})
    ob = types.SimpleNamespace(deliver=original, deliver_email=email, enabled=lambda: calls.get('enabled', True))
    wa = types.SimpleNamespace(send=send, dispatch_guard=guard, WhatsAppBlocked=Blocked)
    monkeypatch.setitem(sys.modules, 'app.owner_briefing', ob)
    monkeypatch.setitem(sys.modules, 'app.zernio_whatsapp', wa)
    monkeypatch.setattr(app, 'owner_briefing', ob, raising=False)
    monkeypatch.setattr(app, 'zernio_whatsapp', wa, raising=False)
    def claim(day, owner_hash):
        calls['claims'] += 1
        return calls.get('claim_success', True)
    monkeypatch.setattr(d, 'claim', claim)
    monkeypatch.setattr(d, 'record', lambda *args: calls['records'].append(args))
    monkeypatch.setattr(d, 'summary', lambda today: 'SYNTHETIC FOLLOWUP SUMMARY')
    calls['blocked_type'] = Blocked
    return calls


def run():
    return asyncio.run(d.deliver_morning('ORIGINAL BRIEFING', DAY))


def test_disabled_preserves_existing_briefing(rig, monkeypatch):
    monkeypatch.delenv('CUSTOMER_FOLLOWUP_DIGEST_ENABLED')
    assert run() == 'original'
    assert rig['original'] == ['ORIGINAL BRIEFING'] and not rig['wa'] and not rig['claims']


@pytest.mark.parametrize('value', ['', '0' * 64, 'garbage'])
def test_missing_or_wrong_pin_never_adds_summary(rig, monkeypatch, value):
    monkeypatch.setenv('CUSTOMER_FOLLOWUP_OWNER_SHA256', value)
    assert run() == 'original'
    assert not rig['wa'] and not rig['claims']


def test_exact_existing_owner_pin_and_one_combined_message(rig):
    assert run() == 'whatsapp'
    assert len(rig['wa']) == 1 and not rig['email'] and not rig['original']
    target, text, kwargs = rig['wa'][0]
    assert target == PHONE and 'ORIGINAL BRIEFING' in text and 'SYNTHETIC FOLLOWUP SUMMARY' in text
    assert kwargs['expected_account'] == 'fixture-account'
    assert kwargs['idempotency_key'].startswith('wa-agent-')
    assert rig['records'][-1][1:] == ('accepted', 'fixture-receipt', 'provider_acceptance_not_delivery')


def test_formatting_normalization_does_not_change_identity(rig, monkeypatch):
    monkeypatch.setenv('WHATSAPP_COMMAND_OWNER', '001 202 555 0101')
    assert d.configuration()['owner_matches_verified_recipient']


def test_blocked_summary_never_reaches_email_or_second_wa_attempt(rig):
    rig['send_error'] = rig['blocked_type']('closed window')
    assert run() == 'email'
    assert rig['email'] == ['ORIGINAL BRIEFING'] and len(rig['wa']) == 1
    assert rig['records'][-1][1] == 'blocked'


def test_unknown_send_outcome_does_not_retry(rig):
    rig['send_error'] = TimeoutError('uncertain')
    assert run() == 'email'
    assert len(rig['wa']) == 1 and not rig['original']
    assert rig['records'][-1][1] == 'uncertain'


def test_missing_receipt_is_not_accepted(rig):
    rig['receipt'] = {'messages': []}
    assert run() == 'whatsapp'
    assert rig['records'][-1][1:4] == ('uncertain', None, 'receipt_missing')


def test_duplicate_day_does_not_send(rig):
    rig['claim_success'] = False
    assert run() == 'followup_already_claimed'
    assert not rig['wa'] and not rig['email'] and not rig['original']


def test_generation_failure_preserves_base_only(rig, monkeypatch):
    def fail(day):
        raise RuntimeError('private details must not be recorded')
    monkeypatch.setattr(d, 'summary', fail)
    assert run() == 'original'
    assert rig['records'][-1][1:4] == ('generation_failed', None, 'snapshot_unavailable')
    assert not rig['wa']


def test_guard_rechecks_owner_without_disclosing_it(rig, monkeypatch):
    def change(day):
        monkeypatch.setenv('WHATSAPP_COMMAND_OWNER', '+12025550102')
        return 'SYNTHETIC FOLLOWUP SUMMARY'
    monkeypatch.setattr(d, 'summary', change)
    assert run() == 'email' and not rig['wa']
    assert rig['records'][-1][1] == 'blocked'


def test_persistence_failure_after_acceptance_cannot_trigger_fallback(rig, monkeypatch):
    monkeypatch.setattr(d, 'record', lambda *args: (_ for _ in ()).throw(RuntimeError('db unavailable')))
    with pytest.raises(RuntimeError):
        run()
    assert len(rig['wa']) == 1 and not rig['email'] and not rig['original']


def test_status_masks_phone_and_does_not_expose_pin(rig, monkeypatch):
    class Connection:
        def execute(self, *args):
            return self
        def fetchone(self):
            return None
    @contextmanager
    def db():
        yield Connection()
    monkeypatch.setitem(sys.modules, 'app.storage', types.SimpleNamespace(db=db))
    data = d.public_status()
    assert data['owner_suffix'] == '101' and data['owner_matches_verified_recipient']
    assert PHONE not in str(data) and hashlib.sha256(PHONE.encode()).hexdigest() not in str(data)
    assert data['new_section_email_fallback'] is False


def test_global_stop_at_entry_sends_nothing(rig):
    rig['enabled'] = False
    assert run() == 'disabled'
    assert not rig['claims'] and not rig['wa'] and not rig['email'] and not rig['original']


def test_global_stop_during_generation_blocks_dispatch_and_fallback(rig, monkeypatch):
    def stop(day):
        rig['enabled'] = False
        return 'SYNTHETIC FOLLOWUP SUMMARY'
    monkeypatch.setattr(d, 'summary', stop)
    assert run() == 'disabled'
    assert not rig['wa'] and not rig['email'] and rig['records'][-1][1] == 'blocked'


def test_account_change_blocks_dispatch(rig, monkeypatch):
    def change(day):
        monkeypatch.setenv('ZERNIO_WHATSAPP_ACCOUNT_ID', 'different-account')
        return 'SYNTHETIC FOLLOWUP SUMMARY'
    monkeypatch.setattr(d, 'summary', change)
    assert run() == 'email' and not rig['wa']
    assert rig['records'][-1][1] == 'blocked'


def test_all_activity_sources_unavailable_does_not_generate_zero_digest(monkeypatch):
    monkeypatch.setitem(sys.modules, 'app.prospect_autopilot', types.SimpleNamespace(system_user=lambda: 1))
    monkeypatch.setitem(sys.modules, 'app.fine_permissions', types.SimpleNamespace(has_permission=lambda *args: True))
    monkeypatch.setattr(d, 'snapshot', lambda *args: {'coverage': [
        {'source': 'accounts', 'status': 'read'}, {'source': 'whatsapp_agent_jobs', 'status': 'unavailable'}]})
    with pytest.raises(RuntimeError, match='source_evidence_unavailable'):
        d.summary(DAY)
