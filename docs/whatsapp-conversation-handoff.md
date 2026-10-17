# Conversation handoff (review build, not deployed)

Branch: `fix/conversation-operator-handoff`. This patch does not change the global
assistant setting, connect an account, send a real message, or deploy anything.

## Operator flow after an approved deployment

Open an individual conversation in `/whatsapp-inbox`. Its status and explicit
pause/resume button are above the messages. The POST `/whatsapp-inbox/takeover`
requires the existing admin session, `send_whatsapp` permission, recent MFA,
CSRF token, and a fresh verified account/conversation/participant match. A stale
screen cannot overwrite a newer decision. The action and actor are audited.

Pause applies only to that account and conversation. Incoming text and attachment
counts are retained locally; attachments remain accessible through the existing
provider inbox/download path and are not automatically downloaded or approved.
Reviewed manual drafts and document sends retain their existing authorization.
Resume admits new work only; it never replays held messages, canceled jobs, or
uncertain sends. An already submitted provider request cannot be recalled.
A lock timeout or verification error does not confirm a successful pause: refresh
and explicitly retry after checking the displayed state.

## Implementation and race boundaries

- `whatsapp_takeover.py`: durable scoped state, generation, audit, held receipts,
  and PostgreSQL recipient/conversation fences. No change to account-wide mode.
- `whatsapp_takeover_control.py`: admin control and runtime wiring. Existing
  bootstrap initializes tables before enabling the hooks or starting workers.
- Both new assistant and legacy direct replies pass the final fence. Shared
  transport text/template/document sends default to the automatic fence; only
  the existing reviewed inbox sends opt into manual dispatch.
- The ingress generation is captured atomically with receipt handling, overwritten
  by the server rather than trusted from webhook JSON, and retained across queue
  insertion and legacy background threads. Pause/resume invalidates old work.
- Pause cancels only pending/processing/ready agent jobs in the exact scope.
  `sending`/`uncertain` states are not recycled. The final fence is held through
  the provider POST. If the send wins, pause waits for that boundary to finish;
  if pause wins, the send fails closed. New lock waits are bounded to two seconds.
- Lock release uses a separate thread limiter; legacy preparation does not hold
  the send fence across nested sends. Final dispatch authority is rechecked after
  acquiring the fence, including current job/lease checks where applicable.
- Local schema additions are additive. No new credentials, service, broad role,
  automatic resume timer, or external notification is introduced.

## Identity and conversation context

The configured assistant identity is “نيرمين، المساعدة الرقمية لآفاق طويق”,
explicitly an AI assistant, not a human employee. Greeting variants include
نرمين and نيرمين. No customer-specific identity or phone is hardcoded.

Ordinary questions can include screened outgoing context from the verified
account/thread/participant: at most four text messages, 3,000 characters, within
24 hours before the job, from the latest 50 provider messages. Quotes require
an exact unique provider platform-message ID. Webhook quote text is not trusted.
Missing, ambiguous, or older context is not guessed. Attachments and sensitive
text do not enter this ordinary context path; it cannot approve documents or
operational actions. Provider unavailability leaves context unavailable.

## Local validation

All fixtures are synthetic; provider calls are mocked. Real PostgreSQL tests use
random disposable schemas in an explicitly supplied local test database:

```
WHATSAPP_TAKEOVER_TEST_URL=postgresql://postgres@127.0.0.1:55439/company_archive_test \
  /tmp/market-venv/bin/python -m pytest tests/test_whatsapp_takeover.py \
  tests/test_whatsapp_takeover_control.py tests/test_whatsapp_takeover_transport.py \
  tests/test_whatsapp_takeover_thread_context.py tests/test_whatsapp_operator_context.py -q
```

Coverage includes scoped pause/resume, CSRF/permission/MFA, participant/account
changes, stale UI generations, concurrent enqueue/send/pause, first-pause template
races, stale ingress after resume, legacy nested sends, unchanged other scopes,
manual-send availability, and no retry after uncertain outcomes. Existing
assistant/privacy/transport/inbox tests are also run. These results do not prove
that any real customer received a reply or that the production incident stopped.

## Before deployment

Review the PR and independent review findings, then obtain explicit deployment
approval. Verify the deployed revision and migrations in staging, exercise pause
and resume with a synthetic conversation, and inspect the real incident's event
IDs/job states through authorized read-only access before claiming its exact
cause. Do not use the old account-wide “إيقاف المسار الجديد” as a substitute:
that setting can fall back to the legacy responder. Rolling back this patch
removes its pause enforcement, so rollback is not a containment action.

Recorded local results: full `pytest tests -q` passed 4,181 tests plus 32 subtests.
After the final unrelated-account guard correction, the transport suite passed
16 tests (including the new case). Independent review passed its 80 focused
checks and reported no remaining blocker before that small scope correction.
The reviewer is also asked to check the final correction. No live send occurred.
