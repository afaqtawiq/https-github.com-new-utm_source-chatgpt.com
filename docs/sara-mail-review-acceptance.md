# Sara: source-backed mailbox review readiness

## Prepared change (not deployed)

- `/sales-today` now shows an owned-mailbox review summary in addition to opportunity tasks. `/sales-review` includes actual imported mail and accepted prospect introductions awaiting a reply, with a clearly internal three-day review date rather than a resend schedule.
- Inbox detail URLs keep the actual source reachable even after it leaves the latest 50 messages.
- HTML-only mail is displayed as escaped plain text. Scripts, embedded/remote images, links, attachments, and tracking content are never fetched or rendered.
- Structured delivery-status notices distinguish a server-reported failure from a server-reported delay. Ambiguous notices stay generic. A notice references an outgoing record only when its exact original Message-ID and recipient match one approved, owned official-mail record. This is a reference to evidence, not proof of delivery or a customer reply.
- A reviewer can record a note, set an internal review date, close/reopen the review, and attach an explicitly manual outgoing-message reference. That reference cannot grant reply-draft authorization, change `contacted` to `replied`, qualify a prospect, or bypass approval.
- Existing strict thread matching and official reply approval remain in force. Delivery notices cannot create reply drafts. The new queue has no sender, campaign scheduler, or AI generation.
- Normal read-only IMAP sync refreshes content metadata for up to 20 already imported messages per pass while preserving UID identity, original import time, saved review decisions, and reply eligibility. If refreshed HTML reveals an explicit opt-out on an already exact, owned prospect thread, existing stop/suppression protection is applied; ordinary legacy mail does not advance a sales stage. New mail remains limited to 50 imports per pass. Existing messages are not duplicated or marked read.

## Verification

Run with the project dependencies:

```
python -m pytest tests -q
AFAAQ_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/afaaq_test python tests/mail_review_acceptance.py
```

The new PostgreSQL acceptance creates and drops only its own schema in a local disposable `afaaq_test` database; external socket connections are rejected. It checks HTML escaping, source links, DSN identity/recipient ambiguity, manual references versus safe reply proof, legacy HTML refresh, duplicate UIDs, review/reopen idempotency, ownership, role permissions, CSRF, no invented CRM rows, and no real sends.

Existing official-sales and prospect-introduction acceptance suites are also required. All existing operational CI suites must pass after integration; focused tests alone do not certify the whole release.

## Release / real-world acceptance gates

1. Review and approve deployment separately. This change has not modified the live mailbox, imported real contacts, sent messages, or altered live campaigns.
2. After deployment, confirm current-mail sync is healthy and inspect the actual source entries for Naqel, Sunbulah, and SMSA. Existing HTML previews refresh in bounded batches. A message absent from the current IMAP UIDVALIDITY cannot be rehydrated from that identity; use the preserved source or mailbox to inspect it.
3. If Naqel lacks an exact original thread reference or has a different sender, retain manual review status. A manually chosen related record is not evidence of a verified customer reply.
4. A Sunbulah delay and SMSA full-mailbox notice require recipient/server follow-up decisions. Do not automatically retry, substitute another address, or mark them delivered. SMTP acceptance remains acceptance only.
5. Full Sara end-to-end readiness still requires a separately authorized cooperative-recipient test: accepted outgoing message → confirmed actual receipt → exact linked response → reviewed reply draft → approval/send → confirmed receipt. This patch does not claim that production test passed.
6. Automatic prospect follow-up and qualification remain off. Moving to Fasah preparation does not imply Sara is a fully autonomous sales agent or authorize an official Fasah submission.

## UI / data boundaries

- Mail review access is admin + `manage_gmail`, scoped to the current mailbox owner. Sending permission is still separately required by the existing draft/approval flow.
- GET requests derive the review list without creating tasks. Review POSTs require CSRF and a nonempty internal note, and are audited.
- At most 200 open inbox sources and 200 waiting introductions are displayed, ordered by review due time, with an explicit truncation warning. Closing reviewed items reveals subsequent entries; completed reviews remain accessible and reopenable.
- Manual review due times are explicitly UTC in the form. They trigger no external action.
