# fal media production

## User flow

1. Save the separate encrypted fal API key in `/settings/media`.
2. Open `/media-pricing` to validate provider authentication and retrieve current
   prices. This uses the read-only pricing API, never generation or billing.
3. Prepare a request in `/media-studio`: image only, or one image followed by a
   five-second video. Ratios: 9:16 or 16:9. The preset is a representative Saudi
   logistics scene, not a claim to depict an actual company truck.
4. Review the saved prompts, caption and live USD quote. Explicit cost approval
   plus existing MFA, admin permission, CSRF and the external-action gate are
   required for the first paid request. Quotes expire after fifteen minutes.
5. The web service polls durable jobs every fifteen seconds. A video job uses
   its generated image automatically. Completion creates exactly one draft in
   the content center. Video drafts target the existing Afaaq YouTube/TikTok
   review and Zernio scheduling flow. Images are available as assets/drafts;
   automatic YouTube/TikTok image posting is not supported.

## Provider and cost boundaries

Only Seedream 4 text-to-image (one image, safety checker enabled) and Kling 2.5
Turbo Pro image-to-video (five seconds) are accepted. Pricing comes from
`GET https://api.fal.ai/v1/models/pricing` with the exact endpoint IDs. The
application validates currency, units and finite positive rates. Prices are
rechecked before submission and before the video stage; increases beyond the
approved amounts stop that stage. Displayed costs are model generation rates,
not a guarantee about taxes or third-party account billing. There is no automatic
credit purchase or replenishment, and no recurring production authorization.

The initial advertised rates were $0.03/image and $0.35/five-second video; live
quotes are authoritative. No real generation has been used in automated tests.

Credentials stay server-side. Queue receipt URLs must remain on queue.fal.run
with a path matching the submitted model and request ID. Output URLs must be
HTTPS fal.media subdomains or the provider's documented falserverless GCS path.
Remote response bodies and credentials are not included in errors or audit logs.

## Durability and recovery

Each job is committed as `image_submitting` or `video_submitting` before sending
the corresponding paid request. Concurrent approvals/polls use row locks and
state checks. The HTTP client does not retry, and `X-Fal-No-Retry: 1` disables
provider retries. Ambiguous submissions are held for manual provider-history
review. Stale submission claims become `needs_review`, never another submission.
Receipt IDs/URLs and stage results persist in PostgreSQL. Known pending receipts
resume after web process restart; read failures permit an explicit status refresh.
The status-refresh action only polls existing receipts and cannot submit a paid
request directly. A following automatic stage remains covered by the original
image-plus-video cost approval.

Media uses fal's documented `X-Fal-Object-Lifecycle-Preference` with
`expiration_duration_seconds: null` on both stages. This requests non-expiring
provider CDN files for later scheduling and avoids ephemeral application disk.
The user retains control of deletion in fal. This is provider-hosted storage,
not an independent archive; account/provider availability still applies.

## Validation and remaining scope

Unit tests cover prices, trusted URLs, precise output counts/duration, no-retry
and retention headers, and sanitized errors. Full PostgreSQL acceptance covers
MFA/CSRF/permissions, cost approval, concurrent single submissions and completion,
automatic stage handoff, image-only output, changed prices/credentials, expired
quotes, process-interrupted submissions and ambiguous responses. All provider
calls are stubbed in these tests; no spending or live posts occur.

The generated clip is a silent five-second scene. Voice-over, logo compositing
and a longer edited advertisement are separate production steps. Live generation,
visual quality review and a confirmed publishing receipt are required before
claiming end-to-end production acceptance. Other readiness items (voice input,
WhatsApp, web/maps search, Gmail and the freight workflow) retain their own status.

Official contracts consulted:
- https://fal.ai/models/fal-ai/bytedance/seedream/v4/text-to-image/api
- https://fal.ai/models/fal-ai/kling-video/v2.5-turbo/pro/image-to-video/api
- https://fal.ai/docs/documentation/model-apis/inference/queue
- https://fal.ai/docs/platform-apis/v1/models/pricing
- https://fal.ai/docs/documentation/model-apis/media-expiration
