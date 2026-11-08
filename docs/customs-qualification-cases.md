# Customs customer qualification, local candidate, 8 November 2026

Baseline supplied for this isolated copy: main `88da155a76c4c54f60bdb579d051e67db3061162`.
No Git metadata, deployment, customer records, production API keys, model calls, messages or authority submissions were used. Existing dependencies are reused from `/tmp`; all HTTP in the new test module is blocked except synthetic `httpx.MockTransport` responses.

## What this qualifies

- **Deterministic runtime:** required lookup gates, fallback text, SABER evidence renderer, narrow action-claim guard, source selector and intake state merging/reset.
- **Mocked orchestration:** model request contains the right current question, history, policy, selected source and tools. This does not prove a model understands the question or follows the policy.
- **Prompt-only:** substantive import/export/transit recommendations, conditional document requirements, customs context recognition and extraction, fee reconciliation and rate-to-product applicability after successful tariff lookup. Numeric percentage membership is now guarded, but is not semantic applicability validation.
- **Not tested:** live-model response quality; actual production deployment; ongoing online SABER reliability; source currency beyond the supplied dated references; actual shipment classification or customs acceptance. Passing tests do not establish that the agent is a licensed broker or an autonomous clearance executor.

## Customer case matrix

| Customer path | Tested observation | Evidence level |
| --- | --- | --- |
| Sea import, Chinese wood arriving Jeddah | Current question retained; wood/quarantine reference and customs policy supplied | Mocked request wiring, not document advice validation |
| Saudi national goods, land export to Oman | Document reference distinguishes land from marine/air documents | Local reference selection and mocked request wiring |
| Re-export previously imported equipment | Article 31 reference supplied, no automatic refund promised by reference | Reference wiring only |
| Transit from Batha to Haditha | Source text requires origin-state declaration and conditional invoice; not an import-market checklist | Reference wiring only |
| Temporary admission for air-freighted exhibition | Conditional suspension rather than blanket exemption in supplied reference | Reference wiring only |
| Correct arrival port from Jeddah to Dammam | Full old exchange followed by latest correction reaches model in order | Mocked wiring, not semantic correction evaluation |
| Correct import to transit and supply exit port | Extracted corrected direction/exit replaces old values; other fields retained | Deterministic merge with mocked extraction |
| New import/export/re-export/transit shipment | Old HS, documents and entry port archived, not reused in new request | Deterministic reset after mocked `new_request=true` |
| Exact SABER HS and keyword product query | Current synthetic description, OR certificate alternatives, additional conditions preserved in direct renderer; one model turn only | Deterministic output with fake official evidence |
| General SABER plus explicit SABER fees | General route and separately dated fee note returned, excludes VAT and shipment-total claim | Deterministic output, mocked empty-query selection |
| Mixed SABER and customs duty | SABER answer retained plus explicit statement no tariff lookup occurred and independent tariff check is needed | Deterministic scoped deferral; not a completed dual lookup |
| Common Arabic/English duty-rate follow-up | Forced tariff tool; prose-only invented rate rejected | Deterministic evidence gate |
| Fabricated certificate, declaration and payment completion | Tested positive assertions rejected; tested negations and procedural conditions preserved | Narrow deterministic pattern guard, not universal semantic security |
| Conditional packing list | Correct cautions selected for model | Prompt-only applicability controls |
| Duplicate-fee aggregate / final total with unknown fees | Numeric aggregate rejected with deterministic unverified-total reply in customs/external-fee contexts | Narrow runtime output gate; not semantic reconciliation |

## Reproduced local fixes

1. **Lookup intent gap.** Before the change, `وكم نسبة الرسم؟`, `ما نسبه الجمارك للأخشاب؟` and `What is the duty rate on timber?` did not force tariff lookup. Added narrowly scoped duty-rate intent forms; supplied prose without evidence now returns the existing unverified reply. Transport routing is unchanged.
2. **Mixed request silently truncated.** SABER returns directly, so a simultaneous tariff question was discarded. The candidate now states explicitly that this answer has not checked the tariff and that SABER does not determine duty/classification. It does not claim to have done a second lookup.
3. **Unsupported completed customs actions passed the filter.** `تم إصدار شهادة سابر لشحنتك`, `تم تقديم البيان الجمركي` and `تم سداد الرسوم الجمركية` were accepted by the ordinary natural-text path. A separate bounded guard rejects these assertion patterns. `لم يتم إصدار…`, `لا نؤكد أنه تم إصدار…`, `إذا تم تقديم…`, and `هل تم سداد…؟` remain permitted. A preceding negated clause cannot exempt a separate positive assertion. This is deliberately not claimed to catch every linguistic paraphrase.
4. **Plural document query missed the source.** `ما الوثائق؟` did not select document-review guidance because `وثيق` does not match `وثائق`. Added `وثائق` and colloquial `وثايق`, with regression coverage.

5. **Positive clearance guarantees.** The tested `أضمن لك الفسح خلال يومين` claim and direct `نضمن لكم الإفراج` forms are rejected by a separate bounded guard. Tested `لا أضمن الفسح`, `لن نضمن لكم الإفراج`, and procedural `ضمان جمركي` remain permitted. Other paraphrases are not universally validated.
6. **Unsupported numeric percentage after evidence.** In the two-turn mocked tariff flow, evidence contained `5%` while model text claimed `99%`. The candidate now rejects percentage values absent from the combined supplied evidence/approved guidance and returns the unverified tariff response. Arabic digits, Arabic decimal punctuation and `5.0%` normalize numerically. This is a narrow membership gate: a known VAT rate could still be applied to the wrong item, known duty rate or tax context. It is not a validated tariff decision or amount calculator.

7. **Unverified shipment aggregates.** With no structured verified fee ledger in this lane, numeric aggregate claims in customs/carrier/agent/port/inspection/appointment/SABER fee contexts now return a deterministic unverified-total reply. Both reproduced unsafe responses below fail closed through `natural.reply`. Tested individual fees remain unchanged. A partial aggregate must be explicitly labelled partial and accompanied by nonfinal/unknown-component language; negated numeric total claims are preserved. Explicit transport-only queries are excluded, including port routes and customs-fee exclusion disclaimers in the response. Bounded preceding user questions can establish context for a short fee follow-up, but not override a new transport-only request.

Only production files changed for these fixes are `app/whatsapp_natural.py` and `app/customs_case_guidance.py`. Approved transport/features/prices, tool authorizations and intake production code are unchanged. The existing mixed-SABER assertion in `tests/test_customs_first.py` now checks the unchanged unverified prefix and the explicit tariff deferral. `tests/test_saber_knowledge.py` explicitly expects the exact general SABER answer plus this boundary only for its two customs-code/duty-premise fixtures; the other four cases retain exact original general output. Source, policy, single-turn and tool checks remain, with required SABER tool choice asserted.

## Fee regression results and remaining limitations

Both former expected failures are now ordinary passing runtime regressions. Neither result means that arbitrary fee arithmetic is verified:

- **Duplicate pass-through aggregate:** the model fixture returns `الوكيل 100 شامل المناولة 100، الإجمالي 200 ريال`. In an explicit customs/agent/port cost request, `natural.reply` returns the deterministic total-unverified reply, not this aggregate.
- **Unknown final total:** the fixture returns `الإجمالي النهائي 700 ريال، رسوم الميناء غير معروفة`. The same runtime path returns the deterministic total-unverified reply.
- **Individual/partial fees:** tested `أتعاب آفاق 700 ريال للحاوية وفق العرض المعتمد ولا تشمل رسوم الجهات الأخرى` is preserved, as is `المجموع الجزئي 100 ريال، رسوم أخرى غير معروفة وهذا ليس إجمالي الشحنة`. This is preservation of response form, not verification of the supplied values or arithmetic.
- **Negation:** `لا أؤكد إجمالي 700 ريال قبل مراجعة الرسوم` is preserved. That does not exempt a separate following asserted numeric total.
- **Transport protection:** `كم نقل فقط من ميناء جدة إلى الرياض لحاويتين؟` retains its synthetic total response even if the answer excludes port/customs fees. Approved price data itself was not edited.
- **Remaining semantic counterexample:** `الوكيل 100 شامل المناولة، أضف مناولة 100 ريال` has no detected numeric aggregate and is not blocked by this new guard. The test records this limit explicitly. It does not establish correct inclusion, duplication, provider, VAT, tax basis or currency treatment.
- **Remaining language limits:** aggregate and guarantee guards cover the tested bounded phrasing, not every paraphrase, number written as words, implicit aggregate or misleading item attribution. Unknown/final-total completeness is not semantically solved. Source guidance and numeric membership still cannot verify regulatory applicability.

### Safe follow-up options, not implemented here

- For costs, introduce a typed, source-backed item ledger with provider/reference identity, inclusion relationship, VAT status, currency and unknown components. Compute confirmed subtotals deterministically, reject duplicate charge relationships, and prohibit final-total wording while unresolved items remain. The new bounded numeric-aggregate deferral is an interim fail-closed control, not this ledger. Expand structured reconciliation before allowing verified shipment-wide totals. Do not treat a word blacklist as this validator.
- For tariff replies, render candidate code, description, conditions and duty directly from validated evidence, or validate structured selected candidate IDs before rendering. Do not derive tariff rates from SABER; maintain the dated cached-source limitation.
- For further guarantee paraphrases/conditional documents, assess narrow deterministic no-guarantee and request-specific document-status responses where appropriate; assess more paraphrases with a separately authorized live-model evaluation before expanding quality claims.
- A future dual SABER/tariff workflow should independently retrieve and label both sources, preserve certificate rendering and fail closed for either unavailable source. The present deferral is safe but incomplete service coverage.

## Local test command

```sh
PYTHONPATH=/tmp/jeddah-transit-test-deps:/tmp/afaq-saber-test-deps \
DATABASE_URL=postgresql://unit-test-only.invalid/no-network ANTHROPIC_API_KEY='' \
python -m pytest -q tests/test_customs_qualification.py tests/test_customs_first.py \
 tests/test_customs_case_guidance.py tests/test_saber_natural_lookup.py tests/test_saber_answers.py \
 tests/test_saber_knowledge.py
```

Result: **183 passed, no failures or expected failures**, one dependency deprecation warning. This is a focused set, not the repository-wide suite. The default Python lacked pytest; no dependency installation was needed.


## Document qualification and operational effect

The companion synthetic document tests exercise the real local PDF extractor with a readable/blank-page file, a completely blank file, a corrupt PDF, and a 31-line invoice. Extraction and classification model responses are mocked separately. No customer files or live model calls are used.

Case profile and document identity/text are now bound to the saved analysis fingerprint. Changing the profile or source makes the result stale and disables code copying and downstream entry preparation. **Previously saved analysis fingerprints will also be stale after this change and must be regenerated.** Source documents and saved results are not deleted. This invalidation is not profile-aware classification: extraction receives documents only, and classification receives items/candidates only. The case profile is not sent to either model in this patch; reanalysis alone does not establish requirements specific to the selected customs regime or transport mode.

Quantities and invoice totals require whole numeric-token evidence, normalized for Arabic digits and well-formed decimal/thousands separators with exact Decimal comparison. Unknown header sources and unsupported currency values are blockers. Ambiguous formats fail closed. These checks establish lexical presence only, not line-level attribution or cross-document reconciliation. A wrong number appearing elsewhere in the document can still pass. The interface continues to require original-document review.

Downstream document values are JSON-quoted as untrusted data. The interface now explicitly says that the no-submit/no-payment instruction is not a technical enforcement guarantee and requires monitoring. Existing launch controls and no-submit/no-payment prompt restrictions remain unchanged.

## Separate direct public-source checks

On 8 November 2026, an anonymous lookup with the unchanged SABER lookup and renderer retrieved official results for two public HS queries: 252520000000 (self-declaration) and 320649000001 (paint/varnish regulation, QM or product COC and an additional environmental-performance requirement). The latter initially failed to fetch and correctly returned no certificate/exemption conclusion before one bounded retry succeeded. These results do not classify an actual shipment and are not guaranteed to remain current.

Sources: https://saber.sa/Home/HSCodes?Tags=252520000000 and https://saber.sa/Home/HSCodes?Tags=320649000001 .

This direct check did not exercise the production tariff-vocabulary database gate, customer delivery, or a live model. It complements, rather than replaces, synthetic integration tests.


## Consolidated verification

- Repository-wide local unit suite: 4,791 passed, 46 environment-dependent skips, 32 subtests passed. No expected failures. Two existing SABER exact-response assertions were updated to require the intended boundary disclaimer while retaining source/tool checks.
- Independent review: no blocking findings in the three scoped production files; 491 tests passed, including 241 transport/pricing/document-transport/takeover regressions.
- Final document-focused suite after wording clarification: 106 passed.
- Compilation passed. Approved knowledge/pricing, transport implementation, privacy policy, and SABER lookup/renderer source are unchanged.
- New qualification tests are included in the existing operational CI workflow. Remote PostgreSQL/runner acceptance and release checks are separate gates and must be recorded on the pull request for the exact published commit; this file reports local qualification only.

No result above certifies comprehensive regulatory coverage, real-model judgment, invoice reconciliation, a current official tariff ruling, or autonomous clearance readiness.
