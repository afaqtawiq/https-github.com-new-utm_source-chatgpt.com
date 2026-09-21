# Production monitoring

`/production-monitor` configures self-notification for the authenticated administrator. Settings require send-email and media permissions, CSRF and recent MFA. Monitoring is disabled by default and pins the connected Gmail sender and the explicitly chosen recipient. The default stagnation threshold is 15 minutes (configurable from 5 to 120); scans run once per minute inside the web service.

The worker watches approved media and advertisement jobs. Completed advertisement steps reset the progress clock. New failures and stalled active jobs create durable incident records. Failures from before activation are not backfilled automatically; the administrator can explicitly check an existing job. Each job gets at most one delay alert and one failure alert. Recovered progress resolves delay incidents, and completion resolves outstanding incidents. Alerts that are no longer applicable are suppressed before sending.

Email delivery commits a `sending` claim before the Gmail call. Parallel workers cannot send the same notification twice. Timeouts, missing receipts or interrupted delivery become `uncertain` and are never automatically retried. Inspect Gmail Sent before attempting any manual recovery. Disabling the monitor prevents future claims; an already dispatched request cannot be recalled. Disconnected Gmail, changed sender, revoked permissions or disabled external actions keep alerts visible in the app without sending.

Support drafts contain sanitized application errors, progress and allowlisted provider request IDs, without keys, raw provider responses or private media links. The worker never sends support email. The separate support-send route requires the user's review checkbox, CSRF, permission and recent MFA; duplicate submissions share one durable delivery claim.

This monitor does not retry paid generation, change the budget, or resolve external billing restrictions. It cannot deliver alerts while the web service or database is unavailable. Production acceptance should confirm that one real notification reaches the configured mailbox; CI stubs outgoing Gmail calls.
