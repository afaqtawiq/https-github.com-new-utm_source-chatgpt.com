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

Saving still provides credential intake only: it does not call fal or spend
credits. `/media-pricing` separately checks authentication and current model
prices without generation. `/media-studio` provides budget-reviewed production
as described in `media-production.md`. A stored key or successful pricing lookup
is not a successful generation or balance test.

Validation: the full application PostgreSQL acceptance exercises authenticated
and unauthenticated requests, roles and explicit permission denial, expired MFA,
CSRF and cross-origin rejection, invalid/oversized input, unavailable encryption,
encrypted insert and replacement, no credential disclosure, no provider calls,
and unchanged Zernio settings and publication records.
