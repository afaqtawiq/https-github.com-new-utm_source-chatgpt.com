"""Pure brochure policy regressions: no database, providers, or app startup."""
from datetime import datetime, timedelta, timezone
from itertools import permutations
from zoneinfo import ZoneInfo

import pytest

from app.brochure_cadence_policy import FOLLOWUP_DELAY, decision, identity


NOW = datetime(2026, 10, 4, 9, 15, tzinfo=timezone.utc)


def recipient(row_id=1, status='sent', **values):
    return {'id': row_id, 'status': status, **values}


def accepted(row_id=1, when=None, **values):
    return recipient(row_id, sent_at=when or NOW - FOLLOWUP_DELAY,
                     provider_message_id=f'<receipt-{row_id}@example.invalid>', **values)


def test_new_destination_has_one_initial_slot():
    assert decision([], NOW) == ('initial', None)
    assert FOLLOWUP_DELAY == timedelta(hours=168)


@pytest.mark.parametrize('elapsed,stage', [
    (timedelta(0), None),
    (timedelta(days=1), None),
    (FOLLOWUP_DELAY - timedelta(microseconds=1), None),
    (FOLLOWUP_DELAY, 'followup'),
    (FOLLOWUP_DELAY + timedelta(microseconds=1), 'followup'),
    (timedelta(days=365), 'followup'),
])
def test_followup_uses_elapsed_time_not_calendar_day(elapsed, stage):
    result = decision([accepted(when=NOW - elapsed)], NOW)
    assert result[0] == stage
    if stage is None:
        assert result[1] == 'followup_not_due'


def test_future_acceptance_cannot_be_followed_up():
    assert decision([accepted(when=NOW + timedelta(days=1))], NOW)[0] is None


@pytest.mark.parametrize('month,day', [(3, 5), (10, 29)])
def test_timezone_offsets_and_daylight_saving_do_not_shorten_seven_days(month, day):
    first = datetime(2026, month, day, 9, tzinfo=ZoneInfo('America/New_York'))
    first_utc = first.astimezone(timezone.utc)
    assert decision([accepted(when=first)], first_utc + timedelta(hours=168) - timedelta(microseconds=1))[0] is None
    assert decision([accepted(when=first)], first_utc + timedelta(hours=168))[0] == 'followup'
    riyadh_first = first_utc.astimezone(ZoneInfo('Asia/Riyadh'))
    assert decision([accepted(when=riyadh_first)], first_utc + timedelta(hours=168))[0] == 'followup'


@pytest.mark.parametrize('count', [2, 3, 10])
def test_two_or_more_accepted_attempts_permanently_exhaust_sequence(count):
    history = [accepted(i, NOW - timedelta(days=20 + i)) for i in range(1, count + 1)]
    assert decision(history, NOW + timedelta(days=365)) == (None, 'sequence_complete')


@pytest.mark.parametrize('state', ['suppressed', 'cancelled', 'cadence_skipped'])
def test_acceptance_evidence_survives_later_status_changes(state):
    history = [accepted(1), recipient(2, state, provider_message_id='<legacy@example.invalid>')]
    assert decision(history, NOW) == (None, 'sequence_complete')


@pytest.mark.parametrize('values', [
    {'status': 'sent'},
    {'status': 'cancelled', 'provider_message_id': '<legacy@example.invalid>'},
    {'status': 'suppressed', 'provider_message_id': '<legacy@example.invalid>', 'claimed_at': NOW - timedelta(days=30)},
])
def test_missing_accepted_timestamp_never_uses_claim_time_as_success(values):
    assert decision([recipient(**values)], NOW) == (None, 'missing_accepted_timestamp')


@pytest.mark.parametrize('state', ['sending', 'uncertain'])
@pytest.mark.parametrize('has_acceptance', [False, True])
def test_unresolved_outcome_blocks_even_long_after_claim(state, has_acceptance):
    history = [recipient(2, state, claimed_at=NOW - timedelta(days=365))]
    if has_acceptance:
        history.append(accepted(1))
    assert decision(history, NOW) == (None, 'unresolved_previous_attempt')


@pytest.mark.parametrize('state', ['bounced', 'rejected', 'replied'])
def test_failure_or_reply_never_creates_an_initial_or_followup_slot(state):
    row = recipient(2, state, claimed_at=NOW - timedelta(days=30))
    assert decision([row], NOW) == (None, 'previous_failure_or_reply')
    assert decision([accepted(1), row], NOW) == (None, 'previous_failure_or_reply')


@pytest.mark.parametrize('state', ['pending', 'blocked'])
def test_existing_queue_reserves_destination_across_campaigns(state):
    assert decision([recipient(1, state)], NOW) == (None, 'already_queued')
    assert decision([accepted(1), recipient(2, state)], NOW) == (None, 'already_queued')


@pytest.mark.parametrize('state', ['pending', 'blocked'])
def test_oldest_legacy_queue_wins_without_later_duplicates_blocking_it(state):
    rows = [recipient(10, state), recipient(20, state)]
    assert decision(rows, NOW, current_id=10) == ('initial', None)
    assert decision(rows, NOW, current_id=20) == (None, 'already_queued')
    assert decision([accepted(1), *rows], NOW, current_id=10) == ('followup', None)


def test_own_inflight_claim_is_excluded_but_another_claim_fences_delivery():
    own = recipient(10, 'sending', claimed_at=NOW)
    assert decision([own], NOW, current_id=10) == ('initial', None)
    assert decision([accepted(1), own], NOW, current_id=10) == ('followup', None)
    assert decision([own, recipient(11, 'sending')], NOW, current_id=10) == (None, 'unresolved_previous_attempt')


@pytest.mark.parametrize('state', ['cancelled', 'suppressed', 'excluded_prospect', 'cadence_skipped'])
def test_known_never_sent_terminal_rows_do_not_consume_a_send_slot(state):
    # Active opt-out/roster eligibility is enforced by the DB audience guard.
    assert decision([recipient(1, state)], NOW) == ('initial', None)


def test_input_order_does_not_change_queue_priority_or_final_limit():
    rows = [accepted(1), recipient(10, 'pending'), recipient(20, 'pending')]
    for history in permutations(rows):
        assert decision(history, NOW, current_id=10) == ('followup', None)
        assert decision(history, NOW, current_id=20) == (None, 'already_queued')


def test_policy_does_not_mutate_history():
    rows = [accepted(1), recipient(10, 'pending')]
    before = [dict(row) for row in rows]
    decision(rows, NOW, current_id=10)
    assert rows == before


@pytest.mark.parametrize('state', ['legacy_unknown', 'retrying', 'delivered', 'failed', '', None])
def test_unknown_status_fails_closed_instead_of_assuming_no_send(state):
    assert decision([recipient(1, state, claimed_at=NOW - timedelta(days=30))], NOW)[0] is None


def test_current_row_with_receipt_is_not_reopened_as_a_new_initial():
    # A legacy/manual status reset must not erase persisted acceptance evidence.
    current = recipient(10, 'pending', provider_message_id='<accepted@example.invalid>', sent_at=NOW - timedelta(days=30))
    assert decision([current], NOW, current_id=10)[0] is None


@pytest.mark.parametrize('value', ['Sales@Example.com', ' sales@example.com ', 'SALES@EXAMPLE.COM'])
def test_email_identity_normalizes_case_and_outer_whitespace(value):
    assert identity('email', value) == 'sales@example.com'


@pytest.mark.parametrize('value', [None, '', 'Company <sales@example.com>',
                                  'a@example.com,b@example.com',
                                  'a@example.com\r\nBcc:other@example.com', 'not-an-email'])
def test_invalid_email_is_not_an_identity(value):
    assert identity('email', value) == ''


@pytest.mark.parametrize('value', ['0501234567', '+966501234567', '966501234567',
                                  '00966501234567', '+966 (50) 123-4567', '٠٥٠١٢٣٤٥٦٧'])
def test_whatsapp_identity_normalizes_legacy_phone_variants(value):
    assert identity('whatsapp', value) == '+966501234567'


@pytest.mark.parametrize('channel,value', [('sms', '+966501234567'), ('EMAIL', 'a@example.com'),
                                          ('whatsapp', '+9660501234567'), ('whatsapp', None),
                                          ('whatsapp', 'not a phone'), ('email', '+966501234567')])
def test_invalid_or_unknown_channel_identity_is_rejected(channel, value):
    assert identity(channel, value) == ''
