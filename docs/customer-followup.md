# Customer follow-up: first read-only increment

## Scope

This feature extends the existing FastAPI application. It adds no second CRM,
database, account, provider integration, worker or customer sending queue. A small owner-only delivery audit table is additive; customer source tables are unchanged.
Existing source systems continue recording their events. Refreshing the new
view projects those records without copying them into another customer store.

- `/customer-followup`: private Arabic dashboard for an administrator.
- `/api/v7/customer-followup`: bounded, source-backed JSON evidence register.
- `/api/v7/customer-followup/digest?day=YYYY-MM-DD`: private daily digest preview.
  Its default day is yesterday in Asia/Riyadh. This preview endpoint does not send a notification.

The read model covers CRM accounts/directory/daily prospects, mailbox-owned
prospects and outbound records, imported inbox metadata, campaign attempts,
agent-processed WhatsApp inbound/outbox records, paused conversation receipts,
manual inbox send states, marketing suppressions, and existing CRM tasks/outcomes.
The view includes names, contact addresses, attempt evidence, inbound observations,
existing CRM outcomes and suggested internal review actions. It never qualifies a
lead, creates a price, books a shipment, or changes an opportunity stage.

## Safety and evidence

- Administrator role is checked in every route. Email data also needs the existing
  `manage_gmail` permission and is restricted by explicit mailbox owner ID.
- WhatsApp local evidence is restricted to the configured account. Historical
  campaign rows have no account ID and remain in a separate legacy scope.
- Exact full addresses are normalized. There is no country inference, phone-suffix
  matching, domain-based company matching or automatic identity merge. Conflicting
  names remain visible. Address-level digest counting is not customer counting.
- A provider message ID deduplicates evidence only within the same channel,
  account/mailbox, endpoint and direction. No ID means separate source evidence.
- `sent`, SMTP acceptance and outbox receipts do not establish delivery or read.
  An imported/processed inbound event does not establish a human reply or sale.
  Delivery notices are excluded from inbound reply observations. Drafts, blocked
  entries and `cadence_skipped` are not attempts.
- Suppression and human takeover are separate. Known prohibitions remain visible
  across relevant source scopes. Missing/truncated safety sources result in an
  unknown state and a verification action, never a claim that contact is allowed.
- No customer message bodies, documents, driver data, prices, credentials or raw errors
  are selected. Manual draft references are hashed inside SQL. HTML escapes
  source data and all responses have `Cache-Control: no-store`.
- The new data projection uses one read-only, repeatable-read transaction with a
  per-statement timeout and source savepoints. Existing application middleware may
  still update the authenticated session's last-seen timestamp.

## Coverage limits

Each source is capped at 10,000 rows. Activity reads prefer recent records;
oldest-open CRM due tasks are prioritized. Truncation/unavailable sources are
explicit. Digest numbers are partial observations, not complete campaign totals.
The HTML table shows the first 500 endpoint records and first 100 open CRM tasks;
the private JSON endpoint includes the full bounded result.

Local WhatsApp tables are not the complete provider conversation history. Imported
email timestamps are import times, not verified received times; inbox sync may lag.
Historical inbound observations do not imply an unanswered customer is waiting.
CRM due counts mean tasks open **now** and due by the requested date, not a
reconstructed historical snapshot. Legacy email campaign rows with no explicit
mailbox owner are excluded, not assigned by assumption. Existing Excel reports
are not imported or treated as contact permission.

## Owner morning delivery through the existing worker

The existing `owner_briefing.py` worker continues to own the schedule, day claim,
operations/finance briefing, and original base-only email fallback. No second worker
or schedule is created. `CUSTOMER_FOLLOWUP_DIGEST_ENABLED` defaults to `0`.

When enabled, `CUSTOMER_FOLLOWUP_OWNER_SHA256` must match SHA256 of the normalized
E.164 `WHATSAPP_COMMAND_OWNER` value. The verified recipient and digest pin are
configured outside the repository. The existing owner destination and access
settings are never changed by this feature. Its guard rechecks owner/account,
feature activation and existing external-action/owner-alert stop switches immediately
before dispatch.

The new customer-followup section is appended to the existing WhatsApp morning
briefing only. If WhatsApp is blocked or its result is uncertain, the new section
is never sent by email. The original briefing may retain its existing base-only
fallback. A durable `owner_followup_delivery` day claim prevents repeated sends;
uncertain/prepared outcomes are frozen for human review, not automatically retried.
No transport template is provisioned or repurposed. Successful scheduled delivery
still requires an open service window or an approved exact-matching template.

`/api/v7/customer-followup/digest-status` is admin-only. It shows activation,
masked owner suffix, pin-match result, schedule, account-configuration presence,
and the latest delivery-attempt status. It does not expose the number, pin, account
ID or credentials. `accepted` means provider acceptance, not delivery or read proof.

## Verification and rollout

Run `python -m pytest tests/test_customer_followup.py tests/test_customer_followup_digest.py tests/test_owner_briefing.py -q` and the operational unit
commands in `.github/workflows/operational-tests.yml`. Offline source contracts use synthetic SQLite. `tests/customer_followup_postgres_acceptance.py` also runs real application and source SQL in an isolated local PostgreSQL test schema, with provider/network sends blocked. Neither fixture establishes live provider completeness.

Before an authorized rollout:

1. Reconcile the exact source commit with current main and any private patches.
2. Run the full exact-commit CI, including PostgreSQL integration, on a dedicated
   test database. Inspect real source column availability read-only.
3. Validate a signed-in admin view, a denied non-admin view, mailbox isolation,
   and missing-source states using synthetic test records.
4. Confirm the deployment/publishing scope. Keep real customer data and reports
   out of code, fixtures, commits, logs and public repositories.
5. Deploy only reviewed code when authorized. The owner-delivery audit table is additive.
6. Verify the new routes against production without sending to customers, then verify the exact masked/pinned owner configuration before enabling the digest extension.

Disable the digest extension before rollback. Reverting code requires no deletion of the owner-delivery audit or customer source records, no campaign retry, and no customer-side action.
