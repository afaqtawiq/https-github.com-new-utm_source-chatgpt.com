# Owner-message delivery evidence

Provider acceptance does not prove delivery, a reply, an agreement, or current
shipment availability. The original negotiation status and accepted provider
identifiers remain unchanged by reconciliation.

## Existing surfaces

The freight list, shipment detail, `/api/v7/freight-workflow`, and WhatsApp shipment
status read saved owner and driver evidence. They do not query the provider. An
accepted message without a saved check explicitly remains unconfirmed. A failed
receipt projects `owner_delivery_failed`; unknown/deleted receipts project
`owner_delivery_unknown`. These are display states, never retry rights.

An owner reply with exact contact provenance, later agreement, driver evidence, or
actual shipment progress retains priority. Unbound legacy replies stay visible as
historical evidence and cannot suppress a failed/unknown current receipt. No receipt
creates a reply, agreement, driver acceptance, or shipment availability.

## Explicit receipt checking

The existing shipment detail offers one check for an accepted WhatsApp message.
It requires admin/transport role, valid CSRF, the existing `send_whatsapp` permission,
recent MFA, and explicit confirmation disclosing possible provider query charges.
There is no scheduler, automatic polling, or resend.

The existing bounded Zernio parser requires a unique private owner conversation and
an exact outgoing WhatsApp message/account/conversation/ID match. Ambiguous, absent,
conflicting or unavailable observations remain unknown. Legacy contacts without
saved provenance require the same exact provider checks; no record, account, or
historical outcome is hardcoded. New accepted sends retain provider/account/CID
values actually returned by the adapter.

A fingerprint binds the negotiation, owner phone, channel, message ID, provider,
account, conversation and acceptance time. Changed contacts fail closed. A
single-flight advisory lock prevents concurrent metered checks; observation-version
fingerprints reject completed form replay. Provider I/O holds no shipment row lock.
Observations are append-only and ordered by check-start time, not insertion time.

## Reply provenance and concurrency

New replies retain an immutable binding to their saved event, negotiation, accepted
message, contact fingerprint, verified sender/account/conversation and inbound IDs.
Known account/CID changes are rejected. After candidate selection, the signed
receiver locks shipment first, negotiation second, then rechecks before recording.
This matches manual editing and avoids inversion with the event's shipment FK.

Current-attempt precedence requires the exact account and CID recorded at acceptance,
or an exact saved provider receipt proving the same message/phone/account/CID.
Missing provenance is never filled from configuration alone. Legacy unbound replies
are not migrated. Contact changes invalidate earlier bindings for current-attempt
precedence without deleting their history. Timestamp order cannot establish identity:
PostgreSQL NOW() may predate send finalization for a genuinely later-recorded reply.
Actual business progress remains authoritative regardless of legacy reply metadata.

## Additive schema and release

Startup adds three nullable provenance columns, `freight_owner_receipts`, and
`freight_owner_reply_bindings`, with lookup indexes. Existing business values and
historical events are not rewritten. Rollback can leave this additive schema intact.

This change does not fix provider eligibility/billing problems, resend old inquiries,
or certify old shipment availability. Publication/deployment and any live receipt
lookup (including provider query costs) require separate authorization. After an
approved rollout, verify deployed SHA and migration, inspect the existing record
without sending, then use the explicit receipt action only when authorized.

## Validation

- `python -m pytest tests/test_owner_delivery.py tests/test_whatsapp_admin.py tests/test_operational_repair.py tests/test_broadcast_recovery.py tests/test_transport_disclosed.py -q`
- `AFAAQ_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:<port>/afaaq_test python tests/transport_postgres_acceptance.py`

The real PostgreSQL harness uses synthetic providers and blocks live egress. It
covers exact matching, unknown versus failed observations, legacy and unsent rows,
unchanged business data, stale/concurrent forms, chronological ordering, replies
during lookup, all status projections, CSRF/permission/MFA, changed account/CID,
legacy history, missing provenance, exact receipt fallback, fingerprint changes,
and a forced manual-edit/inbound race with shipment-first locks.
