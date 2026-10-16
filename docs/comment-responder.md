# Guarded public comment replies (draft, disabled)

This change adds an isolated comment lane after the existing Zernio signature check. It never calls WhatsApp send paths or sends unsolicited DMs. No deployment, webhook subscription, credential, or account configuration was changed.

## Scope and deliberate limits

Only the known YouTube account 6ab019958d284ffb2121d129 can be configured. TikTok 6ac0910233b5e635f2b5ff6d remains blocked until its Business-app comment capability is verified; the prior read failed. Instagram and Facebook have no verified Zernio inbox account IDs and are not accepted. Publishing connections are not comment permissions.

Unknown author ownership is held. The provider schema puts isOwnAccount under comment.author; absence is explicitly unknown. YouTube deliveries may omit it, so this draft must not be represented as an activated YouTube responder. A later verified identity adapter or actual false ownership evidence is required before a pilot can reply. Own comments, replies, live/ad comments, stale events, unsupported accounts, and sensitive content are held. Held comments are not automatically released on activation.

The model classifies a screened public comment into a bounded intent. Public wording comes from reviewed Arabic responses for the five approved service types, pricing, thanks, or AI disclosure. This is deliberately constrained contextual selection, not unrestricted generated public prose. It has no CRM, document, conversation history, tool access, or shared WhatsApp model settings. Sensitive/complaint/injection/uncertain cases require a human. The local screen is conservative, not a comprehensive PII detector. No user text is interpolated into public replies.

## Configuration and readiness

Defaults are off. GET /comment-assistant/readiness requires an authenticated administrator and reports configuration presence only, not operational authorization. Existing login/CSRF/MFA middleware is unchanged; there is no new settings mutation endpoint.

Future operator configuration requires AFAAQ_COMMENTS_ENABLED=1 and AFAAQ_COMMENT_ACCOUNTS JSON keyed by the approved account, with platform=youtube, mode=dry_run or live, verified profile_id, owner_ids (platform author identities), and a positive integer revision. Increase revision for every scope/mode change and after disabling. Database generations and monotonic revisions prevent an older live configuration from restoring revoked work. All deployed workers must receive the intended configuration; a stale disabled worker can keep the lane safely disabled. Never reuse a prior revision.

AFAAQ_COMMENT_MODEL_KEY and AFAAQ_COMMENT_MODEL are isolated classifier settings. Missing values hold non-local intents. Do not copy credentials into source or test fixtures. Existing ZERNIO_API_KEY is used only by the live comment transport. Dry-run makes no comment-provider requests, but may call the separately configured model: use synthetic injected classifiers in tests.

Limits: 50 reserved model calls per rolling day, 256 output tokens and 1200 input characters per call; 10 sends per rolling hour and 50/day per account. Model version selection affects dollar cost; choose a budget-approved model before activation. No paid model calls were made for implementation.

## Delivery and recovery

Persist jobs and event aliases before returning 2xx. Dedupe both event IDs and account/post/comment identity. Lease and account advisory locks serialize workers and rate reservations. Persist the outbox before network I/O; recheck configuration, generation and lease immediately before sending. A timeout, 5xx, 409, malformed success or crash after reservation becomes uncertain. There is no automatic send retry. An empty provider read is inconclusive. Terminal holds require human review and are never silently requeued.

The reconcile helper records only positive evidence with exact account/post/parent/text/owner match and provider reply ID; it does not send. An operator must obtain evidence through an authenticated scoped provider read and review it, never from a customer assertion. Revocation prevents future requests but cannot recall a request already in flight.

## Required activation acceptance (not performed)

1. Confirm owner authorization for one account and one test post; verify provider account/profile and own author IDs, inbox access, comment read/reply permissions, and absence of conflicting reply automation.
2. Preserve existing webhook settings, especially WhatsApp. Subscribe only through a separately approved change, using the existing signed receiver and its secret without disclosure.
3. Deliver a real signed non-own synthetic comment. Verify event and parent identity, timestamp, ownership flag, durable job and dry-run reply. If ownership is absent, hold and implement/test a trusted verification adapter before proceeding.
4. With explicit approval and a new revision, allow one live test on that post. Confirm exactly one public reply under the intended comment, exact account identity, and successful provider evidence. Test a complaint and own reply: neither should send.
5. Replay the same event and a different event for the same comment. Confirm no second send. Disable with a new revision and verify queued/leased work cannot send. Review rate, crash and uncertain-send evidence.
6. Only after owner acceptance may another approved change expand operation. This PR does not activate any channel.

## Provider references

- https://docs.zernio.com/webhooks (signature, persistence before acknowledgement, stable event IDs)
- https://docs.zernio.com/webhooks/inbox (comment schema and unknown ownership)
- https://docs.zernio.com/comments/get-inbox-post-comments (scoped reads, caching, TikTok Business requirement)
- https://docs.zernio.com/comments/reply-to-inbox-post (reply identity, idempotency and ambiguous failures)

## Tests

Local: focused policy, synthetic HTTP worker and signed-receiver tests; existing WhatsApp regression tests. Real PostgreSQL tests run through the existing GitHub Actions PostgreSQL 16 service using random isolated schemas and AFAAQ_TEST_DATABASE_URL only. CI adds the focused suite and concurrency/dedup/generation/outbox/rate/model budget acceptance before existing PostgreSQL regression steps. Final run counts and limitations are reported in the PR, not inferred from the existence of this workflow.

