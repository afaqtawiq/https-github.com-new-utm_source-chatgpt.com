# Official email CRM linkage

The existing Spacemail mailbox, credentials, permissions, SMTP/IMAP settings and
60-second polling cadence are unchanged. No new external provider or credential
is required. The existing bounded automatic acknowledgement text and eligibility
policy are unchanged; a repeated Message-ID under a new IMAP UID cannot trigger
another acknowledgement.

## Runtime behavior

- New IMAP messages retain valid Message-ID, In-Reply-To, References and canonical
  sender information. Invalid/conflicting reply headers remain review-only
- The existing poller creates local association records only. It never creates
  customers, opportunities, tasks, reply drafts, quotes or external replies
- Exact references must identify approved, sent outbound email, with matching
  sender and recorded mailbox owner. Recognized ancestors must agree on CRM
  opportunity/account. Duplicate provider identities fail closed. The explicit
  reply parent, or latest recognized reference, identifies the outbound task
- Account linkage comes from the matched opportunity. Task linkage requires an
  explicit outbound_message_id, added to followups created by future outreach
- Legacy records missing actual mailbox ownership or threading headers remain
  review-only. They are not guessed from creator, subject, sender domain or name
- A success-finalization race can be reconsidered after the durable outbound
  receipt is saved, limited to unresolved no-exact-thread associations
- No polling path initiates send, and imported/backfilled messages never gain
  automatic custom replies. Existing auto-ack settings are not enabled/reset

## Human workflow

The official inbox shows the linked customer/account/followup. A matched message
can create one blank custom draft via an authenticated, CSRF-protected action.
Repeated clicks return the same draft. Unknown or ambiguous messages stay review
only; there is no guessed destination or automatic customer creation.

The draft uses the existing outbound review, approval and send workflow. The
recipient and source mailbox are fixed; body and subject require human review.
Custom replies never append internal proposal notes. Exact approval identity,
mailbox ownership, send_email permission, MFA step-up, CSRF and the external-action
gate are enforced. Replies use the official sender and original threading headers.

An atomic approved→sending claim precedes SMTP. A timeout or ambiguous provider
result becomes uncertain and cannot be retried by another click. A process stop
after acceptance may leave sending; review provider evidence before any manual
recovery. Provider acceptance is not a delivery receipt.

Official draft content is hidden from other users on outbound lists/API/detail,
mutations and Customer 360. Original official inbox read permissions are retained.
Other mail stores (campaigns, shipping agents, production alerts and auto-acks)
are not automatically treated as sales-opportunity conversations.

## Verification

- python -m pytest tests/test_*.py -q
- AFAAQ_TEST_DATABASE_URL=postgresql://...@localhost/afaaq_test python tests/official_sales_acceptance.py
- Existing PostgreSQL acceptance, including Spacemail and auto-acknowledgements

The new PostgreSQL fixture uses a unique disposable local schema, mocks transport
and blocks external sockets. It covers strict/ambiguous/unknown/legacy linkage,
UID rollover, repeated draft actions, recipient immutability, approval identity,
RBAC, CSRF, MFA, cross-user privacy, concurrent one-send, uncertainty, official
provider recording and wire-level reply headers. No live email is sent by tests.
