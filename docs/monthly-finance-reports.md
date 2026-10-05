# Monthly finance reporting

These reports are manual, authenticated preparation tools. They never send a customer message, post profit, transfer money, or change ledger balances.

## Customer statement

`GET /finance/monthly-statement` and `.pdf` accept `owner_id`, `counterparty_id`, `currency`, `start`, and `end` (ISO dates, maximum 366-day interval).

- Opening balance is the sum of journal movements strictly before `start`, not the original opening entry alone
- Posting movements use the financial document's date. Reversals use their recorded date in Asia/Riyadh and never rewrite the original document's period
- The period separately shows claims, receipts, noncash adjustments, opening-balance movements, reversals, and closing balance
- Allocations link evidence only; receipts are not deducted twice
- One owner/customer/currency/receivable ledger per report, from a repeatable-read snapshot
- Customer output uses explicit allowlists. No source paths, audit, private notes, internal Zakat calculations, costs, margins, allocations, or partner shares
- Claim detail is taken from its current approved structured revision. Missing original goods amount/currency, exchange rate, registry or tax details are explicitly marked missing, never reconstructed
- PDF rendering embeds local Arabic fonts and makes no remote requests. It is a financial statement, not a tax invoice or independent confirmation of payment

## Internal monthly draft close

`GET /finance/monthly-closing` and `.pdf` accept `owner_id` and `month` (`YYYY-MM`). Require both `view_finance` and `view_profit` on an active admin/finance account. Mutations additionally require admin `approve_finance` and CSRF.

The close enumerates recorded claims and expense documents in the month. Pending documents, undated financial documents, reversals, and unclassified payable/adjustment documents conservatively block a complete proposal. Opening balances and receipts/payments never become income or expenses.

Every claim must be explicitly mapped into shared service income, agency-only income, Saber revenue, reserved tax, and pass-through funds; their sum must reconcile the claim. Goods value is informational and excluded. Approved claim tax/Saber/goods details constrain the mapping, and customs charges cannot be moved out of pass-throughs.

Actual costs are reported only once through independent expense documents. An optional owner-approved fixed Saber cost may instead be stored on a claim as report-only evidence, with an explicit approval and source reference. It reduces only the agency pool, does not create a payable/payment, and never implies the shipment was paid. A linked agency expense alongside a fixed Saber cost blocks the proposal until reconciled, including a later-month expense. Actual costs allocate to shared activity or the agency's own activity; claim-side actual-cost fields must be explicitly zero. Fixed report-only Saber cost is a separate field. An expense record does not assert payment. Pending costs remain incomplete; blank is not zero. A related claim can be linked only within the same owner and currency.

- Shared net income after actual shared expenses produces a draft 50/50 agency/partner proposal
- Saber revenue and its agency-side actual costs stay wholly in the agency pool
- Tax reserves and pass-through funds are excluded from profit
- Loss allocation remains unresolved and blocks distribution proposals
- Currency pools never mix
- An odd minor unit goes to the partner in the displayed proposal; the report discloses this rounding policy
- No manager-share rule, transit rule, fee formula, Zakat treatment, or customer identity is inferred

Report annotations and completeness reviews are append-only and audited. They do not update source documents or journal entries. Mutations use idempotency keys, shared financial locking, and expected revisions. Completeness is anchored to the current document/reversal/classification/claim-detail snapshot; any change requires a new review. A changed claim-detail revision also requires reclassification.

The report remains DRAFT even when inputs reconcile and completeness has been reviewed. It does not authorize any distribution or send.

## Verification

Synthetic unit tests: `tests/test_finance_monthly_reports.py`, `tests/test_finance_closing_core.py`.

Disposable PostgreSQL acceptance: `tests/finance_monthly_postgres_acceptance.py`, with `AFAAQ_TEST_DATABASE_URL` restricted to a localhost `afaaq_test` database. The test creates/drops only its random schema, blocks external network calls, and verifies original finance and operational tables remain unchanged by report annotations and reads.
