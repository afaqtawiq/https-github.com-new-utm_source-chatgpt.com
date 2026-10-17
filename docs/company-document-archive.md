# Private company document archive — review build

This feature is disabled by default (`COMPANY_DOCUMENTS_ENABLED=0`). This PR does
not deploy, enable the feature, import real files, or change WhatsApp conversation
state. The marketplace remains a separate branch.

## Scope and operator flow

Existing active administrators can open `/company-documents`, choose a company
document category, enter a name and optional issue/expiry dates, and upload one
original PDF, PNG, or JPEG up to 10 MiB. Categories cover transport/customs
licenses, commercial registration, national address, tax certificate, and other
company documents. The application does not seed any real company identifiers.

Each file is an **unverified archival copy**. Storage does not certify validity,
expiry, regulatory approval, or authenticity. There is no OCR, AI processing,
automatic sending, public sharing, or connection to customer document tables.
Dates are recorded as supplied; this version has no expiry alerts.

The page displays the latest 200 records and provides an authenticated original
file download. It is not a searchable or paginated document-management system.

## Storage and access boundaries

- Original bytes and SHA-256 fingerprints are stored in the existing PostgreSQL
  database using additive company-only tables. No new storage service, keys,
  environment credentials, or permanent disk archive is provisioned.
- Exact duplicates are detected atomically by fingerprint. They do not replace
  an existing file or its name/dates. Different bytes create a new record.
- Database triggers prevent updates/deletion of documents and audit entries.
  No edit/delete endpoint is provided. Administrative retention or correction
  procedures require a separately reviewed change; do not upload customer files.
- Every endpoint rechecks the active existing admin session. Upload checks both
  the existing application origin protection and its CSRF token. Authority is
  rechecked after file validation. No permissions or roles are expanded.
- Downloads verify the fingerprint and use a generated attachment filename,
  `no-store`, and `nosniff`; there are no public object URLs or inline previews.
- Audit records contain actor ID, action, internal document ID and time only.
  They contain no filenames, content, document identifiers, or hashes.
- File inspection is local. PDF structure is checked with existing `pdfinfo` in
  a private temporary directory, removed afterward; multipart temporary files
  are closed after parsing. Images are validated and capped at 20 million pixels.
  This is format validation, not a malware-scanning guarantee.

## Validation

Use an explicitly local disposable test database, never production DATABASE_URL:

```
COMPANY_ARCHIVE_TEST_URL=postgresql://postgres@127.0.0.1:55439/company_archive_test \
  /tmp/market-venv/bin/python -m pytest tests/test_company_documents.py -q
COMPANY_ARCHIVE_TEST_URL=postgresql://postgres@127.0.0.1:55439/company_archive_test \
  /tmp/market-venv/bin/python tests/company_archive_postgres_acceptance.py
```

Tests create random isolated schemas and remove them afterward. All documents,
accounts and names are synthetic. Coverage includes anonymous and non-admin
access, inactive/expired/revoked sessions, CSRF/origin, type/size/parser limits,
concurrent duplicate uploads, no overwrite, immutable audit, integrity failure,
customer-store isolation, HTML escaping, exact original retrieval, persistence
across reinitialization, disabled routes and integration with the full app.
CI runs both suites with its local PostgreSQL service.

## Before activation

Review and approve deployment separately, verify existing database backup/restore
and storage capacity for the expected archive size, then explicitly enable the
flag only in the intended environment. Startup creates the additive tables before
serving requests. Upload real company files only after that authorization.

To hide the archive, disable the flag and restart through the normal deployment
path. Existing rows remain intact. Rolling back code needs no table deletion;
never drop the archive tables as part of a rollback. This PR does not execute
these activation or rollback actions.
