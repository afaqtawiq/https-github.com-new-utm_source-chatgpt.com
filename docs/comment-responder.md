# Guarded public comment replies (draft, disabled)

This change adds an isolated comment lane after the existing Zernio signature check. It never calls WhatsApp send paths or sends unsolicited DMs. No deployment, webhook subscription, credential, or account configuration was changed.

## Scope and deliberate limits

Only the known YouTube account 6ab019958d284ffb2121d129 can be configured. TikTok 6ac0910233b5e635f2b5ff6d remains blocked until its Business-app comment capability is verified; the prior read failed. Instagram and Facebook have no verified Zernio inbox account IDs and are not accepted. Publishing connections are not comment permissions.

Absent webhook ownership now queues identity verification only. The provider schema puts isOwnAccount under comment.author; absence is still unknown, never false. Before any model request, the authenticated GET /v1/inbox/comments/{videoId}?accountId=... must match account, platform, video, comment, original author ID and exact unchanged text. The adapter compares the returned stable author ID against an independently verified configured YouTube owner ID. Missing from.isOwner is resolved by that explicit ID evidence; any true, malformed or conflicting flag blocks the job. The configured owner and all known own/echo IDs always block.

The read must explicitly show youtube, canReply=true, isHidden=false and a null/empty parentId, with a complete page (hasMore=false, no next cursor, at most 100 entries), exactly one target match, and meta.lastUpdated no older than ten minutes. Missing fields, stale/future cache, an absent comment, pagination limits or mismatched identity hold the job. No cursor guessing, fallback or polling is used. The same scoped read is repeated before sending. Proof is fenced to the job, lease and configuration generation, expires after 60 seconds, and is required by both model and send reservations. Old jobs without author identity remain ineligible. This resolves the webhook-flag gap where the authenticated read supplies complete evidence; it does not claim every real YouTube response supplies those optional eligibility fields. Live schema verification remains a prerequisite.

Own comments, replies, live/ad comments, stale events, unsupported accounts and sensitive content are held. Held jobs are never automatically released or retried merely because a cached page later changes.

The default reply_mode=reviewed classifies screened public comments into bounded intents and selects reviewed Arabic wording. One fixed reply per intent is a real limitation and does not fully meet a request for natural contextual writing. The optional reply_mode=contextual_draft uses the existing model provider to generate a short natural Arabic draft grounded only in the five verified services and Saudi/Gulf scope. Every such draft is held for human review; both the worker and durable outbox prohibit sending it automatically, even when mode=live. No draft approval/send endpoint is introduced. This offers contextual writing without silently substituting canned replies or claiming unrestricted generation is ready for automatic publication. It has no CRM, document, conversation history, tool access, or shared WhatsApp model settings. Sensitive/complaint/injection/uncertain cases require a human. The local screen is conservative, not a comprehensive PII detector. No user text is interpolated into public replies.

## Configuration and readiness

Defaults are off. GET /comment-assistant/readiness requires an authenticated administrator and reports configuration presence only, not operational authorization. Existing login/CSRF/MFA middleware is unchanged; there is no new settings mutation endpoint.

Future operator configuration requires AFAAQ_COMMENTS_ENABLED=1 and AFAAQ_COMMENT_ACCOUNTS JSON keyed by the approved account, with platform=youtube, mode=dry_run or live, verified profile_id, owner_ids (known own/echo platform identities), youtube_owner_id, owner_verification_ref (a non-secret reference to independently reviewed owner evidence), reply_mode=reviewed or contextual_draft, and a positive integer revision. The YouTube owner ID must be included in owner_ids; neither a handle nor a Zernio account ID is a channel author ID. Increase revision for every scope/mode change and after disabling. Database generations and monotonic revisions prevent an older live configuration from restoring revoked work. All deployed workers must receive the intended configuration; a stale disabled worker can keep the lane safely disabled. Never reuse a prior revision.

The existing ai_intake.py source uses ANTHROPIC_API_KEY and INTAKE_MODEL. The initial separate AFAAQ_COMMENT_MODEL_KEY was intended to isolate billing/configuration, but isolation does not require another credential. That new-key requirement has been removed. This lane reuses the same supported server-side Anthropic credential and model setting (optional AFAAQ_COMMENT_MODEL overrides the model name only). It does not import ai_intake.ask, its prompt, private history, tariff data or tool access. No secret values were read for this implementation. Missing existing credentials hold work. Dry-run now performs the scoped authenticated Zernio identity read before any model work and may incur normal model usage; it never posts a comment. Tests use synthetic credentials and MockTransport only.

Limits: 50 reserved model calls per rolling day, 256 output tokens and 1200 input characters per call; 10 sends per rolling hour and 50/day per account. Model version selection affects dollar cost; choose a budget-approved model before activation. No paid model calls were made for implementation.

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
    "reply_mode": "contextual_draft",
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

Architecture/cost: reuse avoids a new provider or separate paid subscription requirement, but comment model calls still consume the existing provider balance. The isolated cap is 50 reserved calls per rolling day, at most 1200 input characters plus the fixed prompt and 256 output tokens per call, with no retries of uncertain model calls. Actual currency cost depends on the existing selected model and account pricing; no estimate or free-use claim is made. Contextual drafts use one call per eligible comment; reviewed mode can answer simple local intents without a model call. A dry-run can incur these costs after future activation; no live model calls were made during development.

Natural drafts remain review-only. Automatic publication of generated prose would require a separately reviewed approval or grounding/output-validation design and explicit authorization; changing a mode does not bypass this boundary. No merge, deployment or activation is authorized by this change.
