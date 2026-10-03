# One-video Runway production

`/runway-studio` prepares a single Gen-4.5 text-to-video request: 5 seconds,
720×1280 (9:16), standard H.264 MP4. It does not add narration, music, a logo,
multiscene editing, scheduled recurring production, or automatic publishing.
Completed output becomes one unapproved YouTube+TikTok content draft. Existing
content approval, scheduling and platform checks remain independent and intact.

## Credit estimate and consent

The server fixes the model, duration, ratio and output format; clients cannot
change them through form fields. The estimate is 60 credits at the official
12 credits/second price reviewed on 2026-10-03. This is an estimate, not a
provider-enforced cap: Runway's direct endpoint returns estimatedCost only after
accepting a task, and has no max-credit input field. The review UI discloses this
before approval. No pricing-page scraping or router configuration is performed.

Preparing a job checks connection metadata and current balance without generation.
The immutable prompt/caption, credential version and fifteen-minute estimate are
saved. Starting requires admin/manage_media permission, enabled MFA, fresh step-up,
CSRF/same-origin validation, ENABLE_EXTERNAL_ACTIONS=1, the exact estimate version,
and explicit approval of the content and 60-credit estimate. Balance is rechecked.
There is no credit purchase, top-up, subscription, or automatic retry.

## Single submission and recovery

The application commits a submitting claim, approval and storage reservation
before its sole paid request. A row lock prevents repeated or concurrent approvals
from submitting twice. Provider task receipts are stored immediately. A missing,
malformed or higher provider estimate keeps a valid receipt and pauses the job;
the UI warns that the accepted request may already have consumed credits.

Timeouts, interruptions, failed receipts and stale submitting claims never return
to a paid-ready state. Operators must review provider history before approving a
different job. The worker can only GET known tasks and download their result;
it has no path to submit a generation. Polls are serialized across replicas and
spaced at least five seconds apart. Pending receipts resume after restart.

Temporary read/download failures can be retried by explicitly refreshing the same
stored task, without generation. Credential replacement blocks old jobs pending
review; the replacement cannot silently redirect an old task to another project.
Cost discrepancies stop completion and are not cleared by a manual refresh.
Definitive failed/cancelled tasks record reported cost and release reservations;
uncertain cases keep reservations.

## Output safety and persistence

Runway task output URLs expire in 24–48 hours. They are never rendered directly.
Only the exact documented HTTPS CloudFront output host is accepted; a new origin
requires review rather than a wildcard allowance. Downloads use no API credentials,
cookies, redirects or environment proxies and are bounded at 14 MiB. Local-only
ffprobe verifies an actual H.264 MP4, exact portrait dimensions, and roughly five
seconds of decoded video. Invalid or unavailable outputs keep the task receipt.

The verified MP4 bytes, random 192-bit export token and content draft commit
together in PostgreSQL. Completion counts actual bytes against the separate
128 MiB Runway export quota; pending work reserves the per-file maximum. This is
an application quota, not a guarantee about database billing. The approval form
discloses the unlisted export link used by later publishing. Exports support GET,
HEAD and byte ranges, and exist only for completed approved jobs. No provider URL
or provider credential appears in the draft, logs or public response.

## Validation and release boundary

Provider tests mock HTTP and validate real locally generated fixture videos.
Full-app acceptance uses isolated PostgreSQL and blocked external sockets to cover
permissions, MFA, CSRF, quote expiry/tampering, balances, key rotation, duplicate
approvals, process interruption, receipts/costs, quota races, download recovery,
exports and unchanged fal/social data. No live key, paid request or post is used.
Live generation quality and actual platform publication still need separate
authorized tests after release.

Official references:
- https://docs.dev.runwayml.com/openapi.json
- https://docs.dev.runwayml.com/guides/models/
- https://docs.dev.runwayml.com/guides/pricing/
- https://docs.dev.runwayml.com/assets/outputs/
