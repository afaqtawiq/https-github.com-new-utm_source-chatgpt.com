# FASAH AI accuracy gates (validation record, 8 November 2026)

- Classifications, duty rates and alternatives are validated against candidates for the original invoice-line index, not the invoice-wide union. Invalid, non-integer, boolean, out-of-range and duplicate classification indices cannot bind to a line. Rates come from the matching tariff record. Invalid extraction rows retain their original index gap and trigger a blocker.
- Source text exceeding 60,000 characters is rejected before model access. More than 30 returned rows is rejected, not sliced. Exactly 30 rows triggers a coverage blocker because a capped extraction cannot establish that more rows were not omitted.
- Extraction requests include model-reported total line count and completeness. Missing/inconsistent/partial attestations, malformed rows, missing classifications, invalid selected codes/alternatives, document reading notes, blank pages and extraction issues trigger explicit review blockers. Truncated or otherwise non-final model output is rejected even if it happens to contain valid JSON.
- Coverage records distinguish available source documents/pages/text, rows returned/processed, and model-reported line total. Available page count is not a verified original-document page count. Model attestations never establish whole-invoice review: `whole_invoice_review_verified` remains false and original-document review is always required.
- The UI displays limits and coverage warnings. Partial and legacy results disable assisted-entry launch and produce a refusal rather than full-entry instructions. Failed reruns do not display previous results as the new answer. Manual field copies remain preliminary evidence for the broker, not a complete declaration.
- Existing no-submit/no-pay instructions, authorization, CSRF, revision and persistence checks are retained. Originals and permissions are untouched. The initial local validation did not publish or deploy; subsequent release status is recorded in the pull request and deployment history.

Initial local verification: 26 focused synthetic tests (mocked model, workspace and tariff reads) plus existing workspace/tracking unit tests: 49 passed. Python compilation passed. No live model/customer data, external messages, or production database calls. PostgreSQL acceptance and real-browser/model evaluation are not claimed by this focused check.

## Review follow-up

- A null, blank or otherwise unresolved selected classification now blocks assisted entry even when extraction counts match and tariff search returns no candidates. Alternatives alone do not establish a selected classification.
- Saved analysis carries a SHA-256 digest of ordered source-document identities, original-file SHA-256 fingerprints, names/types, extracted page evidence and reading notes. Rendering and prompt generation recompute it. Added/removed/replaced documents, changed OCR/page text, changed file fingerprints and missing legacy bindings mark the result stale and disable assisted-entry launch. Merely incrementing the case revision does not invalidate unchanged evidence.
- The binding confirms only that available evidence is unchanged. It does not certify document authenticity, complete OCR coverage, original-document review or official clearance.
- Follow-up verification: 47 focused synthetic tests and 23 existing workspace/tracking tests passed (70 total). Compilation passed. That local follow-up used no live services and did not deploy.

- Stale/unbound evidence also disables every individual field/item copy button. Current evidence retains manual copy controls even when coverage requires review. Four HTML regression cases cover current, current-partial, changed and unbound sources. Final focused/workspace/tracking run: 74 tests passed.
