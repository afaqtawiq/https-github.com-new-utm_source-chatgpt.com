# English morning brochure

## Prepared change

Adds one English edition each day at 09:00 Asia/Riyadh using the same approved brand assets, contact numbers and seven service topics as the Arabic edition. It does not change the existing Arabic poster, its 19:00 schedule, records or media URLs. It does not change the separate existing daily video preparation/publishing automation.

The English edition uses a separate database table and media URL namespace. The daily row is claimed atomically before rendering or contacting any provider. A repeated tick, multiple worker processes or a restart cannot claim that English day again. Unknown provider outcomes require review rather than an automatic resend.

The English morning window ends at 12:00 Riyadh. A deployment or restart after noon does not publish a missed English brochure that evening. The worker checks approximately every five minutes, so 09:00 is the nominal start rather than a guaranteed second-exact delivery time.

## Channels

- Facebook page «افاق طويق للتخليص والنقل» (1612204139054385): JPG via the existing Meta connection.
- Instagram @afaqwaiq: the same JPG via the existing Meta connection.
- YouTube @afaqtaw and TikTok @afaqt79: an 8-second vertical MP4 via the existing Zernio connection, with account verification at submission.
- X and LinkedIn: saved drafts only, as in the existing Arabic workflow.

TikTok is skipped and reported as partial if its current posting options do not permit the existing public commercial-brand settings. Accepted or publishing provider jobs are shown as pending, not as confirmed publication. A read-only status synchronization updates final receipts without resubmitting.

## Activation after review

1. Review the local English previews and code. If publishing the patch to the existing public GitHub repository is approved, publish only the six changed source/test/document/workflow files, not local research, logs, previews or unrelated files.
2. Run the applicable repository CI and confirm that the reviewed commit is the deployment source.
3. Deploy through the existing approved production flow. Main is connected to Railway and deployments currently do not wait for checks automatically, so do not merge before CI success.
4. Set only `AFAQ_DAILY_POSTER_EN=1` and `POSTER_EN_HOUR=9` on the existing application service. Keep `AFAQ_DAILY_POSTER`, `POSTER_HOUR` and the existing `ENABLE_EXTERNAL_ACTIONS` value unchanged. The English flag defaults to off until activation.
5. Inspect the English admin page `/daily-posters-en`, confirm the Arabic admin page still says 19:00 and verify that no immediate late-day post occurs.
6. Verify the first morning's actual platform receipts and do not claim all channels succeeded from an accepted request or a `publishing` status.

Disabling `AFAQ_DAILY_POSTER_EN` stops the English worker alone. Keep its audit records; do not delete a claim to retry an uncertain publication. A failure must be checked against the relevant platform before any manual recovery.

## Cost and verification limits

Rendering uses the already-installed Pillow and FFmpeg tools, the existing official logo and existing Cairo fonts. It does not call an AI generation service, purchase credits, add subscriptions, create credentials or expand permissions. One local sample MP4 was 2,414,598 bytes. There is additional usage of the existing hosting, database storage, network and publishing provider. The exact incremental bill and remaining provider quota were not exposed by the inspected sources and are not guaranteed to be zero.

Verification is offline: test doubles for storage/provider flows, actual local image rendering and actual FFmpeg encoding. The CI PostgreSQL acceptance test uses a disposable local schema and fake providers to check eight concurrent claims, Arabic isolation, additive migration, media routes and saved drafts. Production database migration, real platform delivery and live English enablement require deployment verification. No production setting, public repository file or social post was changed during preparation.
