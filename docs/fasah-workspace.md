# Fasah Workspace — Safe Assisted Mode

Entry point: `/fasah-workspace`, from the main Afaaq navigation. Available only to `admin` and `customs`. Each employee can access only their own drafts, including administrators.

1. Create an internal draft with a reference.
2. Upload PDF, PNG, or JPEG (10 MiB / 10 pages per file, up to 12 documents), or paste document text.
3. The top inventory shows every uploaded filename, assigned type, page count, content type hints and review warnings. Correct a type without uploading again. A file containing multiple documents can cover multiple requirements after explicit original-document review (for example, an invoice on page 3 of an origin certificate). Zero extracted fields never means an upload is absent. Names alone are hints, and detected draft/unofficial copies cannot be marked reviewed.
4. Fill the case profile and press **فحص اكتمال المستندات**. Each requirement has a separate upload-presence column and one of **مكتمل / ناقص / غير مطلوب / يحتاج مراجعة**, with reason and source. Unknown requirements are never called missing or waived. Type/route/goods changes invalidate prior requirement and commodity-scope decisions. Additional certificates are named separately and linked to individual documents. Removing a linked file makes its required item missing again. All commodity requirements must be reviewed before the internal checklist can be complete.
5. Review candidate values, filename, page, method and evidence. Different candidates remain visible. Select/correct each value, confirm review, then save. Any added source reopens affected reviews. Concurrent edits are rejected instead of overwriting. Placeholder values and malformed weights/table headers are rejected as extraction candidates; existing such values remain visible with warnings and cannot be confirmed or copied until corrected and saved.
4. Open the fixed official Fasah URL in an independent window. Authenticate there manually. Copy individual reviewed fields and paste them manually.
5. The authorized employee verifies the entire declaration and performs official actions in Fasah.

## Boundaries

No Fasah API, server requests, browser control, iframe, proxy, extension, credential form/store, OTP/MFA automation, CAPTCHA handling, official approval/submission endpoint, background Fasah worker, status polling, or email/WhatsApp action exists in this feature. The outgoing link uses `noopener noreferrer`. Its CSP disallows frames and off-origin connections/forms. Existing application authentication, MFA policy and other workflows are unchanged.

Document parsing is local Poppler/Tesseract (English and Arabic), with time, page, byte and image pixel limits. Only explicitly labelled values become candidates; no missing data, HS classification or duties are inferred. Documents are treated as data, never executable instructions. Plain text and source evidence are stored in the existing private application database. Temporary source bytes and rendered pages are deleted after extraction. Pages resembling credentials/verification screens are rejected. Audit logs contain internal actions/IDs, not document values. No original document download/storage is added.

The internal checklist is preparation guidance, not a legal validation or a representation of Fasah's current form schema. Tables with multiple products, unlabelled or ambiguous layouts and poor OCR require manual completion against the originals. The full extracted text remains available for review. Zero missing basic fields never indicates official acceptance or submission. No live customs account or real declaration was used in automated tests.

Automatic document rules are deliberately limited to supported commercial-import cases: invoice, sea/air transport document, and the origin-certificate condition for a verified fixed origin indication. Source checked 2026-09-24: https://zatca.gov.sa/ar/RulesRegulations/Taxes/Pages/customs-bussiness/import-pages/Import-Instructions.aspx . Land-route documents, packing lists, other transaction types and commodity-specific permits require a documented case decision. UAE dispatch alone never imposes a document requirement. This is not an exhaustive regulatory rules engine. Rules outside that scope remain `needs review`; a reviewer can record a justified case-specific requirement or exemption, with a reference. Stored source text is escaped and is not rendered as arbitrary external links.

An additive `context_json` column preserves existing drafts and documents. Existing uploads default to unreviewed; no retroactive review or reclassification is silently saved. Every new mutation preserves owner/role authorization, CSRF, bounded form parsing, optimistic revisions and action-only audit logging. Checklist results are recalculated from current documents on every page load, and any change clears the previous explicit-check timestamp.

## Verification

- `python -m pytest tests/test_fasah_workspace.py -q`: labelled Arabic/English extraction, provenance, conflicts, hostile instructions, credential rejection, invalid types/sizes, real PDF and image OCR, safety boundaries.
- `AFAAQ_TEST_DATABASE_URL=postgresql://...@localhost:5432/afaaq_test python tests/fasah_workspace_acceptance.py`: actual application and isolated PostgreSQL schema; upload, persistence, edit/review, concurrency, CSRF, role/owner isolation, removal, escaping, no official action routes.
- Existing operational CI runs both; production deployment requires the checked commit to pass.
