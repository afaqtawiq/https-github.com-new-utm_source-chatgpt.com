# Guarded public comment replies (draft, disabled)

This change adds an isolated comment lane after the existing Zernio signature check. It never calls WhatsApp send paths or sends unsolicited DMs. No deployment, webhook subscription, credential, or account configuration was changed.

## Scope and deliberate limits

Only the known YouTube account 6ab019958d284ffb2121d129 can be configured. TikTok 6ac0910233b5e635f2b5ff6d remains blocked until its Business-app comment capability is verified; the prior read failed. Instagram and Facebook have no verified Zernio inbox account IDs and are not accepted. Publishing connections are not comment permissions.

Absent webhook ownership now queues identity verification only. The provider schema puts isOwnAccount under comment.author; absence is still unknown, never false. Before any model request, the authenticated GET /v1/inbox/comments/{videoId}?accountId=... must match account, platform, video, comment, original author ID and exact unchanged text. The adapter compares the returned stable author ID against an independently verified configured YouTube owner ID. Missing from.isOwner is resolved by that explicit ID evidence; any true, malformed or conflicting flag blocks the job. The configured owner and all known own/echo IDs always block.

The read must explicitly show youtube, canReply=true, isHidden=false and a null/empty parentId, with a complete page (hasMore=false, no next cursor, at most 100 entries), exactly one target match, and meta.lastUpdated no older than ten minutes. Missing fields, stale/future cache, an absent comment, pagination limits or mismatched identity hold the job. No cursor guessing, fallback or polling is used. The same scoped read is repeated before sending. Proof is fenced to the job, lease and configuration generation, expires after 60 seconds, and is required by both model and send reservations. Old jobs without author identity remain ineligible. This resolves the webhook-flag gap where the authenticated read supplies complete evidence; it does not claim every real YouTube response supplies those optional eligibility fields. Live schema verification remains a prerequisite.

Own comments, replies, live/ad comments, stale events, unsupported accounts and sensitive content are held. Held jobs are never automatically released or retried merely because a cached page later changes.

The default reply_mode=reviewed retains fixed approved wording. The new reply_mode=contextual_auto generates a specific natural Arabic answer for low-risk service questions and automatically publishes only after deterministic checks and an independent stateless semantic model review approve it. It does not force human review of every valid contextual answer. It uses only the five approved public services; questions involving special cargo, particular routes, availability, money, deadlines, guarantees, operational actions, sensitive details, complaints, unsafe instructions or uncertainty must hold. A general service fact is not evidence of a particular shipment's eligibility.

The first filter rejects risky input and output patterns, requires a service-specific answer with no additional service category, and rejects links/numbers/identifiers and suspicious formatting. The independent reviewer sees only the bounded public question, candidate and approved fact list, never the generation conversation or private company/customer context. Only an exact boolean approval in the expected JSON object on a complete response passes. Any failure, uncertainty or timeout holds with no send. The worker records a hash of the exact approved text under the current lease/generation and fresh identity proof. The outbox rechecks both deterministic validation and that hash; changing text invalidates approval. Identity is read again before send, and normal rate/idempotency/kill-switch protections remain.

The optional contextual_draft mode remains review-only for operators who choose it. No manual send endpoint is introduced. The code has no CRM, document, private history or tools. The deterministic screen is conservative rather than comprehensive. Independent model review is probabilistic, not proof that all unsupported claims or subtle injections will be caught. Synthetic tests establish control flow and representative blocking, not real-model Arabic quality or semantic safety. An owner-approved real-model dry-run evaluation on representative Arabic, dialect, adversarial and unsupported-scope cases is required before a live pilot; no paid model calls were made here.

## Configuration and readiness

Defaults are off. GET /comment-assistant/readiness requires an authenticated administrator and reports configuration presence only, not operational authorization. Existing login/CSRF/MFA middleware is unchanged; there is no new settings mutation endpoint.

Future operator configuration requires AFAAQ_COMMENTS_ENABLED=1 and AFAAQ_COMMENT_ACCOUNTS JSON keyed by the approved account, with platform=youtube, mode=dry_run or live, verified profile_id, owner_ids (known own/echo platform identities), youtube_owner_id, owner_verification_ref (a non-secret reference to independently reviewed owner evidence), reply_mode=reviewed, contextual_draft or contextual_auto, and a positive integer revision. The YouTube owner ID must be included in owner_ids; neither a handle nor a Zernio account ID is a channel author ID. Increase revision for every scope/mode change and after disabling. Database generations and monotonic revisions prevent an older live configuration from restoring revoked work. All deployed workers must receive the intended configuration; a stale disabled worker can keep the lane safely disabled. Never reuse a prior revision.

The existing ai_intake.py source uses ANTHROPIC_API_KEY and INTAKE_MODEL. The initial separate AFAAQ_COMMENT_MODEL_KEY was intended to isolate billing/configuration, but isolation does not require another credential. That new-key requirement has been removed. This lane reuses the same supported server-side Anthropic credential and model setting (optional AFAAQ_COMMENT_MODEL overrides the model name only). It does not import ai_intake.ask, its prompt, private history, tariff data or tool access. No secret values were read for this implementation. Missing existing credentials hold work. Dry-run now performs the scoped authenticated Zernio identity read before any model work and may incur normal model usage; it never posts a comment. Tests use synthetic credentials and MockTransport only.

Limits: 50 reserved model calls per rolling day, 256 output tokens and 1200 question characters plus a candidate of at most 480 characters for semantic review, and fixed prompts; 10 sends per rolling hour and 50/day per account. Model version selection affects dollar cost; choose a budget-approved model before activation. No paid model calls were made for implementation.

## Delivery and recovery

Persist jobs and event aliases before returning 2xx. Dedupe both event IDs and account/post/comment identity. Lease and account advisory locks serialize workers and rate reservations. Persist the outbox before network I/O; recheck configuration, generation and lease immediately before sending. A timeout, 5xx, 409, malformed success or crash after reservation becomes uncertain. There is no automatic send retry. An empty provider read is inconclusive. Terminal holds require human review and are never silently requeued.

The reconcile helper records only positive evidence with exact account/post/parent/text/owner match and provider reply ID; it does not send. An operator must obtain evidence through an authenticated scoped provider read and review it, never from a customer assertion. Revocation prevents future requests but cannot recall a request already in flight.

## Required activation acceptance (not performed)

1. Confirm owner authorization for one account and one test post; verify provider account/profile and own author IDs, inbox access, comment read/reply permissions, and absence of conflicting reply automation.
2. Preserve existing webhook settings, especially WhatsApp. Subscribe only through a separately approved change, using the existing signed receiver and its secret without disclosure.
3. Deliver a real signed non-own synthetic comment. Verify event and parent identity, timestamp, ownership flag, durable job and dry-run reply. With the webhook ownership flag absent, confirm the trusted read establishes the configured channel-owner/author distinction and all eligibility fields; missing evidence must hold. Confirm no model call occurs before the durable identity checkpoint.
4. With explicit approval and a new revision, allow one live test on that post. Confirm exactly one public reply under the intended comment, exact account identity, and successful provider evidence. Test a complaint and own reply: neither should send.
5. Replay the same event and a different event for the same comment. Confirm no second send. Disable with a new revision and verify queued/leased work cannot send. Review rate, crash and uncertain-send evidence.
6. Only after owner acceptance may another approved change expand operation. This PR does not activate any channel.

## Provider references

- https://docs.zernio.com/webhooks (signature, persistence before acknowledgement, stable event IDs)
- https://docs.zernio.com/webhooks/inbox (comment schema and unknown ownership)
- https://docs.zernio.com/comments/get-inbox-post-comments (scoped reads, caching, TikTok Business requirement)
- https://docs.zernio.com/comments/reply-to-inbox-post (reply identity, idempotency and ambiguous failures)

## Tests

Local: focused policy, identity adapter, synthetic HTTP worker/model and signed-receiver tests; existing WhatsApp regression tests. Real PostgreSQL tests run through the existing GitHub Actions PostgreSQL 16 service using random isolated schemas and AFAAQ_TEST_DATABASE_URL only. CI adds the focused suite and concurrency/dedup/generation/outbox/rate/model budget acceptance before existing PostgreSQL regression steps. Final run counts and limitations are reported in the PR, not inferred from the existence of this workflow.


## Exact minimum future configuration and cost implications

Keep AFAAQ_COMMENTS_ENABLED unset or 0 for this draft. No runtime settings were changed. For a separately approved dry-run, the server needs its existing DATABASE_URL, ZERNIO_WEBHOOK_SECRET and ZERNIO_API_KEY (with inbox/comment read access to this account), plus the existing ANTHROPIC_API_KEY and INTAKE_MODEL for model work. Do not create or paste new credentials. AFAAQ_COMMENT_MODEL is optional; absent it uses INTAKE_MODEL and the repository's existing default model name.

AFAAQ_COMMENT_ACCOUNTS must contain only verified values, for example this non-operational template:

```json
{
  "6ab019958d284ffb2121d129": {
    "platform": "youtube",
    "mode": "dry_run",
    "reply_mode": "contextual_auto",
    "profile_id": "<verified Zernio profile ID>",
    "youtube_owner_id": "<independently verified YouTube channel author ID>",
    "owner_ids": ["<same verified channel author ID>"],
    "owner_verification_ref": "<non-secret reference to reviewed account/channel evidence>",
    "revision": 3
  }
}
```

Revision 3 is illustrative: use a strictly newer revision than any stored for the account. Verify the owner channel ID from an independently authenticated account/channel record, never the triggering comment, username or display name. Only after approval set AFAAQ_COMMENTS_ENABLED=1 for that dry-run. No settings mutation endpoint or automatic credential provisioning exists.

Webhook scope: event comment.received, accountId 6ab019958d284ffb2121d129 and its independently verified profile only, to the existing HTTPS /webhooks/zernio receiver signed with the existing configured webhook secret. Preserve existing WhatsApp events, subscriptions and secrets. Confirm inbox access and permission to receive comments on the chosen tracked video; later public sending additionally requires comment-reply permission. A successful publishing connection or green CI is not that evidence.

Architecture/cost: reuse avoids a new provider or separate paid subscription requirement, but comment model calls still consume the existing provider balance. The isolated cap is 50 reserved calls per rolling day, at most 1200 question characters plus the fixed prompt (and at most 480 candidate characters for semantic review) and 256 output tokens per call, with no retries of uncertain model calls. Actual currency cost depends on the existing selected model and account pricing; no estimate or free-use claim is made. Contextual automatic replies reserve two calls atomically before generation, including semantic review; this allows at most 25 such jobs per rolling day when the entire 50-call budget is available. Unused reservations remain charged against the cap after rejection or a crash. Contextual drafts use one call per eligible comment; reviewed mode can answer simple local intents without a model call. A dry-run can incur these costs after future activation; no live model calls were made during development.

The contextual_auto implementation is available for review but remains disabled. Enabling dry-run, making paid quality-evaluation calls, changing to live, merging or deploying requires separate owner authorization. Switching modes requires a new revision and never bypasses identity, validation or delivery controls.
