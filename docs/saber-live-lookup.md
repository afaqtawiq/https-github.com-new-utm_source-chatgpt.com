# Official SABER lookup in ordinary text responses

Prepared 8 November 2026 against main ea79bdf7b53c39e37c1f31773e891eb5ba3ce311. This change extends the existing application; no new service, credential, database, certificate submission, booking or payment integration.

## Why the earlier guidance was insufficient

The natural customer response offered only tariff_search. That tool queries the GCC customs-duty table, which does not identify Saudi conformity requirements. Static knowledge explicitly warned that no live SABER status had been checked. The earlier tests validated prompt content with mocked answers, not factual classification from an official lookup. An uncertainty warning alone cannot answer a product-specific question.

## Public evidence and example

The official public form at https://saber.sa/Home/HSCodes supports a GET with its observed Tags field. The page supplies the exact HS code, product description, technical regulation, required certificates and additional requirements. It is a website interface, not a documented stable API.

Read-only checks on 8 November 2026:

- The keyword إطارات returned seven rows. Some were lifting machinery on tyres, not tyres themselves. A first-row shortcut would be wrong.
- Exact code 401110100000 returned new pneumatic rubber tyres for passenger cars and station wagons, the Gulf tyre regulation, and quality mark (QM) OR tyre energy-efficiency card. This is a dated source example, not an assigned code for an unspecified shipment.
- Exact code 252520000000 returned mica powder, regulation shown as a dash, and self-declaration. Missing search results must never be treated as this affirmative nonregulated evidence.

SASO's energy-efficiency-card service requires supporting Gulf conformity certification and other product evidence: https://www.saso.gov.sa/ar/eservices/Pages/MainEServicesDetails.aspx?serviceid=418

Shipment certification is a separate step. SASO's announcement describes the requirement before the customs declaration from 1 October 2025 for regulated and nonregulated products within the relevant scope: https://www.saso.gov.sa/ar/mediacenter/news/Pages/saso-news-1483.aspx

## Runtime boundary

Only short general product keywords or an exact twelve-digit HS code may be queried. Never send customer names, contact details, shipment identifiers, documents, credentials or conversation text to the public site. Before any public request, a bounded local read reconstructs the query from an exact contiguous phrase or exact code in the existing public GCC tariff table. Unknown names, shipment identifiers and unverified wording fail closed locally; they are not sent to SABER. A model-selected phrase alone is insufficient.

A fixed HTTPS GET per tool call may follow the one observed official same-path search redirect to an opaque query URL. Off-site, downgraded, extra-parameter or repeated redirects are rejected. No retries, authentication, arbitrary page-link traversal, form submission, certificate action or shared cookies. Network/environment policy is preserved. Strict HTML schema and reflected-query checks, content type, timeout and response/row caps fail closed on site changes or blocked access. The connector returns separate results, no_results, unavailable and invalid_query states. It preserves OR certificate alternatives and candidate rows, and returns source and retrieval time. A successful lookup is evidence, not customs approval or a completed certificate.

For ordinary customer SABER/conformity questions, a model answer without the required tool use is not accepted. Failed or missing official evidence produces a deterministic unverified reply. General process questions can use approved static guidance without sending a query to the website. Other tariff, pricing and conversation paths retain their behavior. Document-review, authorization, private-knowledge and outgoing-message gates are not changed.

Successful results are rendered deterministically from complete official fields, rather than sent to a second model for free-text interpretation. At most three candidate categories are ordered by local word overlap and explicitly remain candidates. The answer includes the source/time and all certificate alternatives and additional requirements. Oversized fields require review instead of truncating exceptions. Synthetic tests prove routing and rendering, not live model query selection. An end-to-end production test on the exact deployed commit remains necessary before calling the real agent fixed.

## Owner/team route

Pure informational SABER questions in the existing command agent reuse the same read-only response flow rather than static customs prose. A bounded async-to-sync bridge supports the existing synchronous handler without passing database handles, staff identity or operational history. Disabled-model, busy, timeout and error outcomes fail closed. Mixed financial, status and action requests retain their existing tool/confirmation routes. This conservative routing does not claim that every arbitrary compound request or document-derived shipment question has acquired live classification.
