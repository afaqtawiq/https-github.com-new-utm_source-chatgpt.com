# Fasah Workspace — Safe Assisted Mode

Entry point: `/fasah-workspace`, from the main Afaaq navigation. Available only to `admin` and `customs`. Each employee can access only their own drafts, including administrators.

1. Create an internal draft with a reference.
2. Upload PDF, PNG, or JPEG (10 MiB / 10 pages per file, up to 12 documents), or paste document text.
3. Review candidate values, filename, page, method and evidence. Different candidates remain visible. Select/correct each value, confirm review, then save. Any added source reopens affected reviews. Concurrent edits are rejected instead of overwriting.
4. Open the fixed official Fasah URL in an independent window. Authenticate there manually. Copy individual reviewed fields and paste them manually.
5. The authorized employee verifies the entire declaration and performs official actions in Fasah.

## Boundaries

No Fasah API, server requests, browser control, iframe, proxy, extension, credential form/store, OTP/MFA automation, CAPTCHA handling, official approval/submission endpoint, background Fasah worker, status polling, or email/WhatsApp action exists in this feature. The outgoing link uses `noopener noreferrer`. Its CSP disallows frames and off-origin connections/forms. Existing application authentication, MFA policy and other workflows are unchanged.

Document parsing is local Poppler/Tesseract (English and Arabic), with time, page, byte and image pixel limits. Only explicitly labelled values become candidates; no missing data, HS classification or duties are inferred. Documents are treated as data, never executable instructions. Plain text and source evidence are stored in the existing private application database. Temporary source bytes and rendered pages are deleted after extraction. Pages resembling credentials/verification screens are rejected. Audit logs contain internal actions/IDs, not document values. No original document download/storage is added.

The internal checklist is preparation guidance, not a legal validation or a representation of Fasah's current form schema. Tables with multiple products, unlabelled or ambiguous layouts and poor OCR require manual completion against the originals. The full extracted text remains available for review. Zero missing basic fields never indicates official acceptance or submission. No live customs account or real declaration was used in automated tests.

## Verification

- `python -m pytest tests/test_fasah_workspace.py -q`: labelled Arabic/English extraction, provenance, conflicts, hostile instructions, credential rejection, invalid types/sizes, real PDF and image OCR, safety boundaries.
- `AFAAQ_TEST_DATABASE_URL=postgresql://...@localhost:5432/afaaq_test python tests/fasah_workspace_acceptance.py`: actual application and isolated PostgreSQL schema; upload, persistence, edit/review, concurrency, CSRF, role/owner isolation, removal, escaping, no official action routes.
- Existing operational CI runs both; production deployment requires the checked commit to pass.
