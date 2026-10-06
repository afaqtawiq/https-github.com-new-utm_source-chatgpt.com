# Manager WhatsApp inbox (prepared locally, not deployed)

## Purpose and boundary

Use Afaaq's existing server-side Zernio WhatsApp connection for manager-requested reading and reviewed text replies without depending on WhatsApp Web. This is not an unattended connection to an outside personal assistant and does not create any new credential, grant, webhook, notification subscription, or autonomous reply authority.

The current signed receiver already routes owner/staff messages before customer intake and stores operational/staff context. It accepts `message.received`, but ignores other lifecycle events; it is not a general inbox mirror. This patch reads the provider's stored conversation/message history directly, including observed per-message delivery state. Existing auto-reply/intake behavior and employee permissions are unchanged.

## Prepared behavior

- `/whatsapp-inbox`: admin-only, account-filtered private conversations, cursor paging, then message history. Reading does not mark messages read or issue read receipts.
- Text and delivery state are escaped and displayed as data, never dispatched as instructions. Provider acceptance, sending, delivery, reading, failure and unknown evidence remain distinct.
- Attachment filename/type/MIME metadata is shown. Attachment URLs are not exposed or automatically fetched; content viewing and archival are not implemented.
- A selected conversation can create an immutable local text draft with its provider-verified number, original account/thread, author and text. No customer, driver, CRM, or marketing enrollment occurs.
- Draft approval requires the same admin who created it, explicit confirmation, CSRF, `send_whatsapp`, and recent MFA. Identity/authority is rechecked immediately before the existing adapter POST.
- Atomic draft-to-sending claim is committed before provider I/O. Repeat submissions cannot reclaim any attempted draft. A process crash retains `sending`; ambiguous provider/network outcomes remain `uncertain`, with no automatic retry.
- The adapter revalidates account, conversation and a recent inbound window; messages claiming a different account/thread/platform cannot prove the window. Approved inbox replies must match the original conversation. Outside the 24-hour window this composer blocks, without silently substituting a template. The pre-existing exact-approved-template workflow remains available separately.

## Intentional limits

- Existing conversation required. This patch does not initiate arbitrary new contacts or add general-purpose templates.
- Text replies only. Secure attachment content viewing and sending are separate work.
- No background polling, no outside assistant wake, no persistent assistant credential.
- No guarantee of uninterrupted provider availability or historical WhatsApp Web/group visibility. Coexistence groups are outside this path.
- No price-table changes, invoice retrieval, shipment contact, or receipt-related send was performed by preparing this patch.

## Code and local verification

Six files: app/whatsapp_inbox.py, app/zernio_whatsapp.py, app/bootstrap.py, tests/test_whatsapp_inbox.py, .github/workflows/operational-tests.yml, and this document.

Existing bootstrap, adapter, receiver and team files were verified byte-for-byte against source blobs at main commit `d08ebee32fd9be70105f5e56b8e361f706d8fc47` before edits. The local recovered checkout carries a different commit identity, so publication must apply only these reviewed changes on current main.

Focused tests cover manager access, account/group/thread filtering, escaped text and nonexposed media URLs, complete Arabic draft length, immutable recipient/body, confirmation/CSRF/MFA/permission, actual middleware MFA return path, revocation during preflight, repeated submissions, wrong creator, closed window, stale account/thread, uncertain outcomes, and partial/paginated provider reads. Tests use fake providers and in-memory draft storage only.

Final validation: the complete existing Python CI unit list, including the new inbox tests, passed with 1,878 tests and 32 subtests (one dependency deprecation warning). Independent focused review passed 120 tests with no remaining concrete blockers. Compile checks and git diff --check passed. PostgreSQL acceptance/concurrency tests still require an isolated PostgreSQL environment. Production integration and a real authenticated inbox/read/reply test are not performed. Local browser visual QA was attempted but the container denied browser socket creation; no visual pass is claimed.

## Activation gates

1. Owner approval of publication of exactly the six patch files and the desired deployment step; no previous PR authorization is reused.
2. Apply on current main, run full CI including existing PostgreSQL acceptance, and obtain review before merge/deployment.
3. After authorized deployment, verify manager login, real private conversation history and media metadata, account identity and provider-reported delivery status. No live send is needed for read verification.
4. For an actual test reply, obtain approval for exact recipient and text, then use the immutable preview and existing MFA. Verify the provider message ID and observed delivery state separately.
5. Any supported external-assistant connector/grant or webhook changes require their own explicit per-action authorization. Do not describe this inbox patch as an always-awake personal assistant.

## Primary provider references

- https://docs.zernio.com/platforms/whatsapp/inbox
- https://docs.zernio.com/messages/list-inbox-conversations
- https://docs.zernio.com/messages/get-inbox-conversation-messages
- https://docs.zernio.com/platforms/whatsapp/connection
