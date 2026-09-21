# Afaaq media credential setup

`GET /settings/media` is linked from the content center and social settings. An
administrator with `manage_media` permission can enter a fal API key after the
existing MFA step-up. The form is withheld until verification so an expired
session is discovered before the user pastes a credential.

`POST /settings/media` requires the same permission, recent MFA and the session
CSRF token. It saves the credential encrypted with Fernet using a separate
`afaaq-media-fal:` derivation of `TOKEN_ENCRYPTION_KEY`. The single provider row
and its credential-free audit entry are committed together. GET and redirect
responses use `Cache-Control: no-store`; no response renders the saved credential.
No Runway, Zernio or WhatsApp setting is read or changed by this setup.

This release only provides secure credential intake. It does not call fal, test
provider authorization or balance, generate media, spend credits, schedule or
publish anything. The page explicitly identifies that remaining work. A stored
key is not a successful generation test. The next integration needs an approved
spending limit, generation task tracking and durable output storage before a
real production test.

Validation: the full application PostgreSQL acceptance exercises authenticated
and unauthenticated requests, roles and explicit permission denial, expired MFA,
CSRF and cross-origin rejection, invalid/oversized input, unavailable encryption,
encrypted insert and replacement, no credential disclosure, no provider calls,
and unchanged Zernio settings and publication records.
