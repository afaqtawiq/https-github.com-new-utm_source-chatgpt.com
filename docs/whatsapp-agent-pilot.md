# WhatsApp document pilot and durable replies

This release adds a recoverable document-reading and reply lane to the existing Afaaq WhatsApp channel. It starts OFF. It does not connect an external personal-assistant conversation or create credentials, subscriptions, billing actions, or new staff privileges.

## Owner-only activation and acceptance

After deployment, an existing administrator opens `/whatsapp-assistant`, completes the existing MFA step-up when requested, and configures the verified test sender plus the SHA-256 of the exact delivered, locally reviewed synthetic PDF. The sender number and digest are runtime data, not source-code constants. The digest approves provenance only. No expected document facts or answers enter the application or model prompt.

Pilot mode replies only to that verified private sender on the configured WhatsApp account. The test is one readiness message, one PDF with a document question, and one follow-up question. The administrator checks `/whatsapp-assistant/jobs/{id}` for actual downloaded-byte SHA, extracted-text SHA, document state, model outcome, source job, inbound identity and provider reply ID. `sent` means provider acceptance, not delivery or reading.

Routine activation requires two current-generation, same-account/sender/conversation jobs: an actual single-PDF read with safe text and approved digest, and an attachment-free follow-up linked to that exact document. Both need successful persisted model results and accepted replies. The owner must separately confirm receiving the replies and their correctness before the administrator submits the acceptance form. Checking a provider acceptance status alone does not supply that confirmation.

Every configuration mutation is account/generation bound and requires administrator session, CSRF, send permission and recent MFA. OFF or reconfiguration permanently fences old unsent claims, even after OFF then ON. The pilot allowlist grants no operational/admin role.

## Durable processing

The signed receiver validates account, private sender, participant and message identity, then commits a message/event-deduplicated job before returning. It performs no download, OCR, model request or send in that transaction. New and legacy lanes share account/message ownership so mode transitions and new event aliases cannot cause both components to reply.

A leased worker processes each conversation in order. It checkpoints document identity and approved extracted text, reserves at most one model attempt, persists the model result, and commits a separate outbox claim before the only send attempt. Read-only phases have bounded recovery. Model responses lost after reservation and sends interrupted after their irreversible boundary become `uncertain`; they never regenerate or resend automatically.

States: `pending`, `processing`, `ready`, `sending`, `sent`, `blocked`, `uncertain`, `failed`. Document states include `ok`, `quarantined`, `unavailable` and `none`. Processing/send leases are bounded; inherited document context and model jobs expire after 24 hours. The existing account/thread/window and exact-template safeguards remain in the send adapter, and this reply lane requires an open original conversation rather than substituting a template.

## Document privacy and local review

A PDF's approved digest must be calculated from bytes actually received. Unknown digests are quarantined locally; passing a keyword scan cannot establish that an arbitrary document is safe. Sensitive/uncertain content, captions and history are denied before external model use. OCR or incomplete extraction is quarantined unless separately reviewed; the automatic lane currently accepts complete text-PDF extraction only. A harmless sentence mentioning financial data can therefore be conservatively held even when it negates that data.

The worker uses the existing fixed-origin provider media API, never a supplied arbitrary URL. Fresh signed attachment identity and privacy-safe shape diagnostics are retained without raw private URLs, filenames, credentials or document bodies from rejected content. Existing bounded local PDF extraction runs outside the webhook lock. An administrator can download a quarantined original for local review through the job page; quarantine is not financial posting or archival approval.

Only necessary, provenance-approved nonsensitive document text and structurally screened questions reach the existing Anthropic model. Raw captions/history are not blindly forwarded. Routine general-service questions use a minimal digest-pinned public knowledge excerpt that excludes prices, authentication instructions and unsupported commitments. Unknown questions are clarified locally.

The model has no tools or operational dispatcher. Its prompt and conservative output checks require descriptive facts and reject commitments, secrets, unsupported identifiers and links. These controls are defenses, not mathematical proof of semantic truth. Actual pilot answers still need owner verification against the original file.

The model-attempt ceilings are 10 per account/day in pilot and 50 in routine, counting reservations rather than only successful calls. Each request has bounded input/output and no automatic retry. The application performs no credit purchase or refill action; provider failure/insufficient credit is handled as a failure, not a reason to buy anything.

## Existing roles and scope

OFF leaves the existing reply behavior in place, with identity-only duplicate ownership bookkeeping. After routine activation, known staff list/status and canonical add-driver/add-shipment requests retain the existing local role-protected handlers. A trusted receiver context disables both legacy model entrypoints in that delegation, preventing matcher drift from forwarding raw commands/history. Ambiguous commands and generic send requests are clarified or left for existing reviewed workflows, never treated as new automatic action authority.

This release does not negotiate or approve new prices, book transport, post financial entries, send unrelated onward messages, read old unavailable attachments by guessing IDs, or modify shipment pricing. The previous metadata-only staff acknowledgment draft is not included. A successful synthetic pilot proves this pipeline, not that every real invoice/receipt is safe or readable.

## Verification

Unit coverage includes actual local synthetic PDF extraction, source-linked follow-ups, privacy holds, signature boundary, account/sender/group checks, duplicate aliases and both lane orderings, model/send crash boundaries, OFF/ON generation fencing, stale configuration forms, current-pilot proof, context expiry, callback authorization, model output commitments and retained legacy roles. The dedicated PostgreSQL acceptance script runs only against disposable localhost `afaaq_test`, creates/removes its own schema and forbids external network calls while testing concurrent claims, budgets, stop races and ownership.

Before merge, run the full unit suite and every exact-head operational/PostgreSQL CI stage. Deployment is not live acceptance. Keep OFF until authorized runtime setup; keep owner-only until the controlled incoming text/PDF/follow-up and owner-confirmed reply evidence succeed. No production test send is part of unit/CI verification.
