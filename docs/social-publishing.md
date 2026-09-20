# Afaaq video publishing

Verified targets: YouTube `@afaqtaw` and TikTok `@afaqtawaiq6`.

The integration schedules approved video/reel drafts through Zernio. Zernio
executes the schedule; the application does not need an additional cron job.
An existing draft or approval is never submitted by deployment or startup.

## Setup after deployment

1. Keep both channels connected in the dedicated Afaaq Zernio account.
2. Sign in to the Afaaq application as an administrator. The existing MFA and
   recent step-up requirements also apply to saving this connection and scheduling.
3. Open `/settings/social`. Create a Zernio API key with access to the account,
   account-health/creator-info reads and publishing operations for the profile
   containing these channels. Enter the key directly into the application form.
4. The application verifies both handles and posting permissions, then encrypts
   the key in PostgreSQL using `TOKEN_ENCRYPTION_KEY`. Do not paste keys in chat,
   source control, logs or issue bodies. Keep the encryption key stable.
5. `ENABLE_EXTERNAL_ACTIONS=1` must already be explicitly authorized and enabled
   before scheduling. The connection can be verified while sending is disabled.

The existing `ZERNIO_API_KEY` belongs to the WhatsApp integration. This publishing
integration never reads, changes or falls back to it.

## Workflow

Create a video/reel draft for YouTube, TikTok or the explicit YouTube+TikTok target.
Use a public, directly downloadable HTTPS MP4/MOV/WebM file that remains available
through publication. Submit the draft for approval and approve it as administrator.
Open the review/schedule screen, watch the video, select platform privacy, child
audience and AI/commercial disclosures, explicitly select TikTok interactions,
and confirm the preview and permission to publish. Times without an offset mean
Asia/Riyadh. The server rejects schedules less than five minutes in the future.

Old `All` drafts retain their meaning and are not automatically mapped to two
platforms. Create a specifically targeted draft for API scheduling.

The database claims each content item once before calling Zernio, with a unique
request ID and an immutable request snapshot. The provider's five-minute
idempotency window supplements the permanent local one-request constraint.
Timeouts and ambiguous responses remain `needs_review`; they are never resent
automatically. Review such requests in Zernio before any further action.

Use **Update publishing result** on the content page to retrieve the provider's
latest result. A scheduled receipt is not a published receipt. Partial failures
remain partial, and all targets must explicitly report published before the app
marks the content published. Edit/cancel an existing provider schedule in Zernio.
The app does not claim that the browser connection alone is a live posting test.

## Verification

`python -m pytest tests/test_social_publishing.py tests/test_operational_repair.py tests/test_whatsapp_admin.py -q`

`tests/postgres_acceptance.py` invokes the social route acceptance suite in a
disposable local PostgreSQL database. It checks encryption and WhatsApp key
isolation, handle mismatch, MFA/CSRF, global sending gate, explicit preview,
concurrent single submission, partial results, and ambiguous-response no-retry.
Provider calls are stubbed; no live posts are created.

Contract sources checked on 2026-09-20:

- https://docs.zernio.com/api/openapi
- https://docs.zernio.com/platforms/youtube
- https://docs.zernio.com/platforms/tiktok
- https://docs.zernio.com/accounts/list-accounts
- https://docs.zernio.com/accounts/get-account-health
