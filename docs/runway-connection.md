# Runway Developer API connection

`/settings/runway` is a separate administrator-only connection page, linked from
the content center and media settings. It requires `manage_media`. Saving and
checking require enabled MFA, a recent step-up, same-origin submission, and CSRF.
The user enters their own Runway project key in the password field after MFA.

The key is stored in the new `runway_provider_settings` table, encrypted using a
separate `afaaq-media-runway:` derivation of `TOKEN_ENCRYPTION_KEY`. It is never
rendered, logged, returned from status, or placed in URLs. GET requests query only
credential-free metadata and do not contact Runway. Replacing a key clears prior
verification. The existing fal table, credentials, production jobs, workers, and
publication flow are unchanged.

The explicit check posts to `/settings/runway/check`. The server makes one
read-only `GET https://api.dev.runwayml.com/v1/organization` with API version
`2024-11-06`, no redirects, no proxy environment, and no retries. It accepts only a
nonnegative integer `creditBalance`; upstream bodies and errors are not echoed.
Only the check time and balance are stored. Failure clears previous verification;
a result for a replaced credential cannot update the new credential's status.
The displayed balance is a timestamped snapshot, not a spending guarantee.

Developer API project credits and Runway web-app credits are separate balances.
This page verifies only the Developer API project belonging to the user-entered
key; a balance from another connection is not automatically the same project.
It does not transfer credits or select a web-app workspace.

## Scope and remaining production work

This release supports secure credential intake and read-only connection/balance
verification only. It has no generation, purchase, replenishment, scheduler, or
Runway task submission method. The existing media and cinematic studios still
use fal. No Runway model is selected or promised by this connection check.

Producing Afaaq content using these credits requires a separate explicitly
approved generation integration: current model/pricing selection, cost review,
durable single-submission task receipts and polling, safe output validation and
storage, content drafts, and a live cost-approved quality review. A verified key
is not generation acceptance.

## Validation

`tests/test_media_runway.py` mocks HTTP. `tests/runway_settings_acceptance.py`
runs through `tests/postgres_acceptance.py` on the disposable PostgreSQL fixture.
It checks authorization, expired/disabled MFA, CSRF/origin, invalid/oversized input,
encryption/domain isolation, no secret display or logging, zero credit display,
failed/replaced credentials, replacement during a check, and unchanged fal/social
data and job counts. No real provider requests or spending are used in tests.

Official contracts:
- https://docs.dev.runwayml.com/api/
- https://docs.dev.runwayml.com/api-details/versioning/
- https://github.com/runwayml/sdk-python/blob/main/src/runwayml/types/organization_retrieve_response.py
- https://docs.dev.runwayml.com/usage/workspace-reporting/
