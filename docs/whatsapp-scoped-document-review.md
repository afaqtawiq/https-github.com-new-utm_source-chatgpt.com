# Scoped document review and outgoing privacy checks

## Exact-document admission

In routine mode, a manager can open an eligible original PDF job's **Review selected excerpt** link. The server fetches the canonical attachment through the existing authenticated provider client, verifies its recorded byte digest, and extracts text locally. OCR, incomplete extraction, changed bytes, unavailable files, and historical quarantines without a preserved reason remain outside this path.

The manager selects whole original lines in order. Local screening rejects known secrets, bank/card/identity details, opaque content and document instructions. Ordinary invoice/transaction descriptions are not automatically classified as secrets. This screening is not a guarantee that arbitrary text contains no sensitive data; the manager must review the exact minimized excerpt.

The second page displays the exact text, Anthropic destination, purpose, conversation/sender, original message and byte hash, excerpt hash and expiry. Existing send permission, recent MFA, CSRF and explicit confirmation are required to admit it. Default admission is one hour, bounded by the original document's 24-hour lifetime. Approval is bound to the current authorization generation and only messages enqueued after approval. It does not replay the original or already queued messages, send a reply, consume model budget, change global approved hashes, or alter routine mode.

A new approval replaces prior approvals for that same source. Revocation, expiry, changed generation or modified bindings fail checks at checkpoint, model reservation, send claim and the immediate network boundary. Revocation cannot retract content already transmitted before it occurred. Original quarantine remains unchanged; approved excerpts are independently recorded. Future answers use only the reviewed text and existing no-tools model/output guards.

For an explicit factual total, subtotal, tax or currency question, an approved excerpt can support an attributed monetary fact only when its whole label, amount and currency match a source line. The reply cannot compute tax, convert currency, join values from different lines, infer payment or amount due, or append an action/approval promise. Conflicting or incomplete monetary extraction produces explicit uncertainty. Generic price guards remain unchanged. This bounded text path does not claim complete invoice interpretation or authorize quotes, bookings, financial posting or payment commitments.

## Outgoing attachment diagnostic

A creator-owned terminal PDF draft with a recorded provider receipt offers a privacy diagnostic. It verifies current account, private conversation, participant, outgoing receipt and attachment metadata before classifying the URL. The response contains bounded categories only, never a raw URL, token or body.

The default is metadata-only. An optional anonymous check requires a separate assertion that the exact file is fictional and nonsensitive. It uses a fresh unauthenticated client only for an exact canonical provider media route, follows no redirects, and reads at most 256 bytes. Unknown/external/CDN URLs are not probed. A denial, redirect or network error is inconclusive. Observing a PDF prefix without credentials proves public bytes at that time; a URL's presence alone does not.

Provider receipt validity and URL presence are separate facts. Invalid or mismatched receipts remain uncertain even when a URL exists; valid partial sends remain partial. No diagnostic or uncertain outcome retries a send. No new credentials, grants, subscriptions or model calls are introduced.

## Verification

Tests use synthetic documents/identities and mocked network clients. The operational PostgreSQL suite covers approval races, future-inbound watermarks, replacement/revocation, expiry, generation changes and outbox protection. Live financial documents require their own exact sharing decision; deployment approves no document content.
