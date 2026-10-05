# Itemized customer claims

Finance document details include a separate, structured claim breakdown. It is a presentation supplement, not a new accounting entry or a tax invoice.

## Recording detail

On an active claim with a confirmed currency, an administrator with `approve_finance` can enter:

- Original goods invoice value and its currency
- Documented exchange rate into the claim currency (1 for the same currency)
- Customs duty and other customs fees, shown as a customs subtotal with both parts disclosed
- Clearance, Saber, zakat, commercial registry, and tax amounts
- Source reference, approval/correction reason, and confirmation

Every component is required, including explicit zero amounts. No fee, tax rate, exchange rate, or document source text is inferred. Goods are converted with exact decimal arithmetic and HALF_UP rounding to the claim currency; goods never enter the claimed total. Component precision must already match the currency. The component sum must equal the existing document amount exactly.

Corrections append a new detail revision and a document audit event. Old detail revisions and original financial evidence remain immutable. Replayed identical requests do not duplicate data; a changed payload using the same request key or an outdated revision is rejected. Attaching details does not change documents, journal entries, allocations, or balances.

## Customer view and PDF

A posted active claim with approved detail exposes:

- `/finance/documents/{id}/claim` for customer-safe HTML preview
- `/finance/documents/{id}/claim.pdf` for an actual PDF attachment download

Both require existing finance read authorization and return `Cache-Control: no-store`. The customer projection is allowlisted: claimant, customer, document date, original invoice reference, customs declaration, currency, goods information, components, total, and detail revision. Internal notes, source paths, approval reasons, audit data, costs, margins, and other customers are not included. Neither endpoint sends anything externally or creates a public sharing link. A saved PDF can be sent manually after the user reviews it. Reversed, voided, draft, reviewed-only, or missing-detail claims cannot export a customer PDF.

PDF generation runs locally with embedded Arabic fonts. It performs independent sum and currency checks, strips control characters, wraps long identifiers, and paginates long metadata. It neither fetches remote content nor interprets input as markup or a filesystem path.

## Deployment and checks

The schema adds only the `finance_claim_details` table, index, and immutability trigger. Initialization is rerunnable. It does not backfill or modify historical claims. Record approved production detail through the authenticated form after deployment; do not include real financial sources or claim fixtures in the repository.

Focused tests: `test_finance_claim_core.py`, `test_finance_claim_pdf.py`, and `finance_claim_postgres_acceptance.py`. The PostgreSQL acceptance runner requires a disposable local `afaaq_test` database, isolates a new schema, blocks external network access, and verifies original ledger rows and balances remain unchanged. Existing finance and opening-balance acceptance must also pass.
