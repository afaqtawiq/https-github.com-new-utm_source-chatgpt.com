# Combined Sara and transport readiness verification

## Scope

Verified locally on 2026-10-03, starting at main commit
`30c6a44576794487e7936c653d2e5519d2478a72` in a separate worktree.
The original component worktrees were preserved.

- Transport component: `d176188de2631064485aea34c9cf56544a884df7`,
  cherry-picked without conflicts as `9d3c87a`.
- Sara component: frozen patch SHA-256
  `57e7617d4b756c379c005f660c8ee32a5ed31952e5e198b8749916ea718e4faa`,
  confirmed by its author before applying. It applied without conflicts.
- No integration code changes were needed. No push, remote PR, merge,
  deployment, live provider sends, authentication changes, or production
  database writes were performed by this verification.

## Automated results

Environment: Python 3.12.14 and disposable local PostgreSQL 17.11 with a
UTF-8 `afaaq_test` database. The repository CI configuration targets
PostgreSQL 16; this local result is not a remote CI result.

1. `python -m pytest tests -q`: **1,016 passed, 7 subtests passed**.
2. Repeated the entire unit suite with non-loopback socket connections
   rejected: **1,016 passed, 7 subtests passed**, zero external connection
   attempts. Runtime 44.26 seconds. The sole warning is the existing
   Starlette/AnyIO `BlockingPortal` deprecation.
3. All **nine** configured PostgreSQL acceptance scripts passed, in this
   order, using the same fresh local database and an external-socket guard:
   - `tests/postgres_acceptance.py`
   - `tests/monitor_postgres_acceptance.py`
   - `tests/marketing_postgres_acceptance.py`
   - `tests/repair_20260924_acceptance.py`
   - `tests/fasah_workspace_acceptance.py`
   - `tests/transport_postgres_acceptance.py`
   - `tests/official_sales_acceptance.py`
   - `tests/prospect_intro_acceptance.py`
   - `tests/mail_review_acceptance.py`
4. `python -m compileall -q app tests` and `git diff --check`: **passed**.

Providers, receipts, email, and WhatsApp interactions were simulated. The
transport script also exercises disclosed-TEST, recovery, and concurrent
first-wins acceptance checks. The mailbox script exercises safe HTML text,
delivery notices, exact versus manual references, reviewed/reopened tasks,
legacy content refresh, opt-out handling, ownership, RBAC, and CSRF.

## Browser and visual coverage

The mail-review and transport PostgreSQL scripts were repeated successfully
while capturing 11 actual HTML responses from synthetic fixtures: inbox
detail, sales-today, sales-review, review detail, and freight recovery states.

The cloud browser rejected the local fixture URL with
`net::ERR_BLOCKED_BY_CLIENT`. Browser screenshots, rendered layout, mobile
layout, and interactive browser form behavior were **not verified**.
HTTP route/form and state-transition assertions passed in the acceptance
tests; captured HTML alone is not a visual-browser pass.

## Remaining release gates

- Publication and deployment need separate explicit authorization.
- Verify CI against the exact published commit if publication is approved.
- Refresh and inspect the actual Naqel, Sunbulah, and SMSA source entries
  only after an authorized deployment; do not infer delivery from SMTP
  acceptance or treat a delivery notice as a customer reply.
- Genuine driver acceptance and a cooperative-recipient Sara end-to-end
  test remain external acceptance gates. No synthetic fixture establishes
  that they happened in production.
- Sara follow-up sending and qualification remain manual and separately
  approved; this verification does not establish autonomous sales readiness.
