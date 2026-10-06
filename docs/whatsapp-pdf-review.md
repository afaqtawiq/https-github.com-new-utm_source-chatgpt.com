# WhatsApp PDF review and staff receipt context

Based on the deployed manager-inbox release `cdaeb696410c27836edec98558640f7442536e09`. The owner approved publication of the PDF access change; merge/deployment are conditional on passing checks. This package does not create an always-awake connection to an outside assistant.

## Manager PDF access

The existing inbox adds explicit download and local-text-review actions for PDF attachments. Admin session, configured account, private conversation, exact message and attachment index are verified before fetching any bytes. The media identifier comes from the verified attachment's `payload.id` (string or numeric), its canonical same-origin media-proxy URL, or the official resolver response for that exact verified message/index. A canonical URL with an explicit different account is rejected; it is parsed only for identity and never followed.

WhatsApp binary retrieval uses the provider's documented `GET /v1/whatsapp/media/{mediaId}` with the existing server client and account ID. Attachment URLs and refresh URLs are never followed. Only the fixed Zernio origin receives its existing authorization header; no credential is copied to the browser or a media host. Redirects, compressed bodies, non-PDF MIME, bad PDF signatures and oversized responses fail closed. No automatic retry follows an expired or failed binary download.

Limits:
- Download: 20 MiB, 45-second wall limit, identity encoding/raw bytes.
- Local text/OCR review: explicit CSRF-protected POST, 10 MiB and 10 pages, existing text/OCR extraction rules and credential screening.
- Parser worker: one at a time per app process, minimal environment without provider/database credentials, 512 MiB address-space limit, 32 MiB file-size limit, 90-second CPU limit, no core dumps, 100-second parent wall limit and process-group cleanup.
- Output: bounded JSON, at most 150,000 extracted characters, escaped HTML, no-store headers. Download is a PDF attachment with sandbox/nosniff headers.

Resource containment is not a complete security sandbox. The local native PDF/OCR tools must remain patched. Encrypted, expired, unsupported, oversized or unreadable files are reported honestly. OCR is evidence for review, not a verified financial record.

The operation does not send content to an external model, post a ledger entry, archive a file permanently, send WhatsApp messages, create credentials or change permissions. The manager can review the real file and decide the next action.

## Automatic-reply boundary

This release does not change staff/customer automatic replies, caption handling or model context. Those changes and any new external-model document sharing remain separately scoped and unactivated. The manager-only PDF feature can retrieve and inspect the existing business documents without waiting for an automatic-reply expansion.

## Privacy and cost

No new subscription, credential or grant is introduced. Downloads use the existing provider API quota; local text/OCR review uses existing server resources. This package adds no model upload. Any future use of an external model for document summaries needs explicit data-sharing scope and a defensible sensitive-data gate; uncertain documents must remain local/manual rather than relying on a regex-only redaction promise.

## Acceptance and broader-workflow boundary

1. Run the full existing unit and operational/PostgreSQL CI suites on the exact release head.
2. After approved deployment, open a verified existing private conversation and retrieve a known non-sensitive test PDF. Compare its bytes/text to the original, including a scanned page.
3. With separately authorized controlled live testing, send a captionless PDF and one with review intent. Verify one appropriate same-thread acknowledgment, no menu and no operational mutation.
4. Follow up about that PDF. Verify correct scoped context and an honest unread/read state. Verify no other employee's document context is used.
5. A separately authorized reply test must distinguish accepted, delivered and read evidence and must not retry an uncertain send.
6. An actual external-assistant wake, retrieval and correlated reply must be observed before any always-on claim. Existing event-source availability does not establish that connection.

## References

- https://docs.zernio.com/changelog?platform=whatsapp&type=breaking_change (July 22, 2026 WhatsApp binary media endpoint)
- https://docs.zernio.com/messages/get-inbox-conversation-messages
- https://docs.zernio.com/messages/get-message-attachment
- https://docs.zernio.com/platforms/whatsapp/inbox
