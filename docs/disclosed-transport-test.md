# Disclosed transport test

New captures submitted through **Save for test** (`/naqliat/manual`, `capture_method=manual_test`) are persistently marked as tests. Their fingerprint is separate from an identical real capture. Existing records are not reclassified or modified by this migration.

The test owner must send the test's exact NQ reference with the simulated price, weight, unloading location and payment terms. Identity/account/private-conversation checks remain in force. The owner may also be the administrator; administrator commands remain commands. Test creation does not send an owner enquiry, and complete owner terms prepare a draft without automatically broadcasting.

The driver preview prominently uses **اختبار للنظام فقط، لا توجد حمولة فعلية ولا حاجة للتحرك** inside the approved template's first reference parameter, including the repeated acceptance instruction. An administrator must review and explicitly approve the test, exact message and displayed recipient list. Existing role, CSRF, MFA and outbound controls remain in force. Changed disclosure or audience invalidates approval. Direct delivery cannot bypass approval, and manual-send links are suppressed in test previews.

Only a registered, actually sent recipient with a provider receipt may reply with the exact disclosed acceptance instruction. Administrator identity never becomes a driver identity. The first valid test reply records `test_completed`; it does not assign an operational driver, create shipment revenue/cost, or enter business-shipment KPIs. A provider receipt means acceptance of the request, not proof of delivery or reading. Uncertain sends are not retried automatically.

Tests use synthetic identities and mocked providers. `tests/transport_postgres_acceptance.py` runs additional isolated PostgreSQL checks in `transport_disclosed_acceptance.py`, including signed owner/admin correlation, duplicate/racing approval and delivery, receipt handling, and unchanged real records. This change alone sends no test messages and authorizes no production test.
