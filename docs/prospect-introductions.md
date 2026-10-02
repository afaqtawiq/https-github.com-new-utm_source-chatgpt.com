# Reviewed prospect introductions

`/sales-prospects` is a manual, mailbox-owner-only workflow for introducing Afaaq's services to a reviewed public company contact. It does not classify a company as a buyer, create an opportunity or account, enroll it in a customer campaign, schedule outreach, or send a quotation.

## Evidence and exclusions

The owner confirms the official source, legal/brand identity, and that the company is not a current customer (including information outside the app). Before draft creation and again before sending, the app verifies the exact email on the official HTTPS source and the visible company identity. A public email is contact evidence only; it never satisfies the separate `verify_public_request` guard.

The address is canonical and unique across prospect records. Existing CRM/directory companies, matching company domains, suppression records, prior outbound contacts, and customer-campaign recipients block introduction. Customer campaign preparation and claiming also exclude prospect records, using the same per-recipient transaction lock. No existing cadence or channel policy is changed.

## Sending

Every introduction follows draft → pending approval → approved → sending → sent/uncertain. Recipient is fixed to its verified source. The exact purpose, prospect, mailbox, recipient, subject, body, and proposal fields are hashed at approval and rechecked before sending. Admin ownership, mailbox permission, send permission, CSRF, MFA enrollment, and the external-action switch are required. Only the official Spacemail sender is allowed.

The owner's approved fresh-code exception applies only to manual `POST /outbound/{id}/send` using the connected Spacemail sender `afaq@shodai.cc`. This route does not require a recent Authenticator code. Middleware and the send handler use the same bounded policy; other senders and every other sensitive route keep their existing MFA rules. Mailbox connection changes, campaign scheduling, WhatsApp, calls, and security settings are not exempt. Login remains password-based, and the existing ten-minute step-up window is unchanged. A compromised authorized session can therefore send already-approved official email without fresh proof of Authenticator possession; exact approval and the other checks above remain mandatory.

The atomic claim allows at most one provider attempt. `sent` means provider accepted, not delivered. A provider exception yields `uncertain`; no automatic retry exists. A missing receipt or a process interruption requires manual investigation rather than another send.

## Replies and stop requests

Safe exact RFC thread ancestry, original recipient, and mailbox ownership associate a reply with the prospect. Ambiguous, legacy, or mismatched mail remains for review. A reply marks the prospect `replied`, without establishing purchase intent. A custom reply is a blank manual draft and requires a new exact approval before sending; the generic automatic acknowledgement is not used for prospect senders.

Explicit stop commands in the author's opening text add an email suppression and mark the prospect `stopped`; quoted introductory footers do not cause a false opt-out. Suppression is checked again before drafting and sending replies. Internal qualification notes can be saved only after an actual linked reply; voluntary current rates are recorded with their units and conditions, without automated quoting or commitments.

## Verification

`tests/test_prospect_intro.py` covers pure identity, exact-address, approval-digest, and stop parsing. `tests/prospect_intro_acceptance.py` uses a disposable localhost PostgreSQL schema and blocked external network with fake SMTP/IMAP. The workflow also runs all pre-existing operational unit and PostgreSQL suites. No live recipient data belongs in this repository.
