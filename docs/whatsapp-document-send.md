# Manager PDF sends

The manager inbox supports a separate document draft, review and send flow. Uploading a PDF does not send it. The preview binds the private staged bytes, SHA256, filename, optional caption, current business account, verified individual conversation and recipient. No customer or campaign record is created.

A send requires the same creator's manager session, `send_whatsapp` permission, recent MFA step-up, CSRF and explicit hash/recipient/account confirmation. The existing provider account and latest incoming message must still establish an open 24-hour reply window immediately before dispatch. This route does not send templates, groups, background messages or new conversations.

Files are bounded to 20 MiB and parsed locally as PDFs. Draft review and send authorization expires after one hour, with a per-creator staging limit. File bytes are removed on terminal outcomes or the next cleanup of expired drafts; expiration does not promise immediate physical deletion. Audit metadata remains. This is application-level deletion, not a claim about database backup retention. Documents are never sent to a model by this feature.

The provider request uses direct multipart `attachment` bytes, `accountId` and optional `message`, with the uploaded filename. It does not use public upload-direct or an attachment URL. The generic provider format list omits PDF while the WhatsApp-specific document capability includes it; live PDF interoperability must be verified separately. The shared response schema permits an attachment public URL when available, without distinguishing upload methods. An authorization decision for confidential files must account for that uncertainty before transmission.

The durable draft is claimed before the single external request. Repeated confirmation, timeout, process interruption, ambiguous provider response and partial outcomes cannot trigger an automatic retry. `accepted` means provider acceptance, not delivery. `sending`, `uncertain`, `partial` and `public_link_warning` require investigation; a public-link warning is post-send evidence and cannot undo disclosure. Raw returned URLs and provider bodies are not retained or displayed.

Validation uses synthetic fixtures and mocked provider responses, plus disposable PostgreSQL concurrency checks. Production credentials, customer documents, phone numbers and document hashes must never be added to repository fixtures.
