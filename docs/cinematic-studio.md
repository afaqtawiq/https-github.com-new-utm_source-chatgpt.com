# Cinematic advertisement studio

Release 7.6 adds `/advert-studio` alongside the existing single-scene studio. An editable five-scene storyboard produces four moving scenes and a branded closing card, with Arabic male narration and native 1080×1920 and 1920×1080 exports. Each voice segment is shared across both versions. The first vertical scene can reuse a completed studio video. No official logo is bundled: upload an approved PNG/JPEG/WebP, or review the clearly labeled text identity preview.

## Approval and spending

Preparing the storyboard fetches current fal prices without generating anything. Quotes expire after 15 minutes and bind the approval to the exact quote timestamp and saved encrypted credential version. Generation requires administrator access, CSRF, recent MFA, the external-actions gate, and explicit cost approval. The voice ceiling conservatively charges at least 1,000 character units per segment, using UTF-8 byte length if larger. Current prices are rechecked before every paid step; increases stop the job.

Paid submissions have a committed PostgreSQL claim before the API call. Concurrent workers cannot submit the same step twice. Ambiguous submissions and stale claims require review and are never retried automatically. Completed provider assets and receipts remain available for investigation. Never resolve uncertain paid work by resetting a step to ready.

## Media and recovery

MiniMax Speech 02 HD uses `Arabic_FriendlyGuy`, Arabic language boost, speed 1.08 and pitch -2. Live speech quality and pronunciation still require human review. FFmpeg joins the scenes, normalized narration, original quiet transition effects, Arabic text and the closing card. No third-party music is bundled. RAQM-enabled Pillow and Arabic fonts are required. Audio longer than the scene limit stops rendering instead of cutting the voice; total output is checked against the duration limit.

Downloads are restricted to validated fal assets, with bounded sizes, no redirects and no credential forwarding. Rendering uses local files only. PostgreSQL stores final MP4 bytes so deploys do not erase them. Each export is capped at 14 MiB; approval reserves space under a shared 128 MiB export quota. These limits are an application quota, not a guarantee of free database disk space. Export URLs use unguessable tokens and support GET, HEAD and byte ranges.

Only one renderer runs at a time across replicas. If rendering fails after generation is complete, the review page can requeue the montage without new paid generation. Failed or uncertain jobs retain storage reservations until an operator reviews them; the studio does not silently discard records or assets.

Completion creates separate unapproved content drafts: vertical for YouTube and TikTok, horizontal for YouTube. Publishing continues through the existing independent content approval and scheduling flow. This release does not connect new social accounts or enable automatic publishing.

## Verification

Unit tests include real FFmpeg audio/video rendering at both native dimensions. PostgreSQL acceptance covers quote changes, MFA/CSRF, parallel approvals and submissions, ambiguous-response handling, stage price increases, quota and expiry, logo snapshots, durable exports, range serving and montage recovery. Provider calls are stubbed in tests: no live generation is billed. Live acceptance requires one priced, approved advertisement followed by visual and audio review.

Official references:

- https://fal.ai/models/fal-ai/minimax/speech-02-hd/api
- https://platform.minimax.io/docs/faq/system-voice-id
- https://fal.ai/docs/documentation/model-apis/fal-cdn
