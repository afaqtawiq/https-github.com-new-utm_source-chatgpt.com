# Reference files for the `ab-testing` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/sample-size-guide.md

# Sample Size Guide

Reference for calculating sample sizes and test duration.

## Contents
- Sample Size Fundamentals (required inputs, what these mean)
- Sample Size Quick Reference Tables
- Duration Calculator (formula, examples, minimum duration rules, maximum duration guidelines)
- Online Calculators
- Adjusting for Multiple Variants
- Common Sample Size Mistakes
- When Sample Size Requirements Are Too High
- Sequential Testing
- Quick Decision Framework

## Sample Size Fundamentals

### Required Inputs

1. **Baseline conversion rate**: Your current rate
2. **Minimum detectable effect (MDE)**: Smallest change worth detecting
3. **Statistical significance level**: Usually 95% (α = 0.05)
4. **Statistical power**: Usually 80% (β = 0.20)

### What These Mean

**Baseline conversion rate**: If your page converts at 5%, that's your baseline.

**MDE (Minimum Detectable Effect)**: The smallest improvement you care about detecting. Set this based on:
- Business impact (is a 5% lift meaningful?)
- Implementation cost (worth the effort?)
- Realistic expectations (what have past tests shown?)

**Statistical significance (95%)**: Means there's less than 5% chance the observed difference is due to random chance.

**Statistical power (80%)**: Means if there's a real effect of size MDE, you have 80% chance of detecting it.

---

## Sample Size Quick Reference Tables

### Conversion Rate: 1%

| Lift to Detect | Sample per Variant | Total Sample |
|----------------|-------------------|--------------|
| 5% (1% → 1.05%) | 1,500,000 | 3,000,000 |
| 10% (1% → 1.1%) | 380,000 | 760,000 |
| 20% (1% → 1.2%) | 97,000 | 194,000 |
| 50% (1% → 1.5%) | 16,000 | 32,000 |
| 100% (1% → 2%) | 4,200 | 8,400 |

### Conversion Rate: 3%

| Lift to Detect | Sample per Variant | Total Sample |
|----------------|-------------------|--------------|
| 5% (3% → 3.15%) | 480,000 | 960,000 |
| 10% (3% → 3.3%) | 120,000 | 240,000 |
| 20% (3% → 3.6%) | 31,000 | 62,000 |
| 50% (3% → 4.5%) | 5,200 | 10,400 |
| 100% (3% → 6%) | 1,400 | 2,800 |

### Conversion Rate: 5%

| Lift to Detect | Sample per Variant | Total Sample |
|----------------|-------------------|--------------|
| 5% (5% → 5.25%) | 280,000 | 560,000 |
| 10% (5% → 5.5%) | 72,000 | 144,000 |
| 20% (5% → 6%) | 18,000 | 36,000 |
| 50% (5% → 7.5%) | 3,100 | 6,200 |
| 100% (5% → 10%) | 810 | 1,620 |

### Conversion Rate: 10%

| Lift to Detect | Sample per Variant | Total Sample |
|----------------|-------------------|--------------|
| 5% (10% → 10.5%) | 130,000 | 260,000 |
| 10% (10% → 11%) | 34,000 | 68,000 |
| 20% (10% → 12%) | 8,700 | 17,400 |
| 50% (10% → 15%) | 1,500 | 3,000 |
| 100% (10% → 20%) | 400 | 800 |

### Conversion Rate: 20%

| Lift to Detect | Sample per Variant | Total Sample |
|----------------|-------------------|--------------|
| 5% (20% → 21%) | 60,000 | 120,000 |
| 10% (20% → 22%) | 16,000 | 32,000 |
| 20% (20% → 24%) | 4,000 | 8,000 |
| 50% (20% → 30%) | 700 | 1,400 |
| 100% (20% → 40%) | 200 | 400 |

---

## Duration Calculator

### Formula

```
Duration (days) = (Sample per variant × Number of variants) / (Daily traffic × % exposed)
```

### Examples

**Scenario 1: High-traffic page**
- Need: 10,000 per variant (2 variants = 20,000 total)
- Daily traffic: 5,000 visitors
- 100% exposed to test
- Duration: 20,000 / 5,000 = **4 days**

**Scenario 2: Medium-traffic page**
- Need: 30,000 per variant (60,000 total)
- Daily traffic: 2,000 visitors
- 100% exposed
- Duration: 60,000 / 2,000 = **30 days**

**Scenario 3: Low-traffic with partial exposure**
- Need: 15,000 per variant (30,000 total)
- Daily traffic: 500 visitors
- 50% exposed to test
- Effective daily: 250
- Duration: 30,000 / 250 = **120 days** (too long!)

### Minimum Duration Rules

Even with sufficient sample size, run tests for at least:
- **1 full week**: To capture day-of-week variation
- **2 business cycles**: If B2B (weekday vs. weekend patterns)
- **Through paydays**: If e-commerce (beginning/end of month)

### Maximum Duration Guidelines

Avoid running tests longer than 4-8 weeks:
- Novelty effects wear off
- External factors intervene
- Opportunity cost of other tests

---

## Online Calculators

### Recommended Tools

**Evan Miller's Calculator**
https://www.evanmiller.org/ab-testing/sample-size.html
- Simple interface
- Bookmark-worthy

**Optimizely's Calculator**
https://www.optimizely.com/sample-size-calculator/
- Business-friendly language
- Duration estimates

**AB Test Guide Calculator**
https://www.abtestguide.com/calc/
- Includes Bayesian option
- Multiple test types

**VWO Duration Calculator**
https://vwo.com/tools/ab-test-duration-calculator/
- Duration-focused
- Good for planning

---

## Adjusting for Multiple Variants

With more than 2 variants (A/B/n tests), you need more sample:

| Variants | Multiplier |
|----------|------------|
| 2 (A/B) | 1x |
| 3 (A/B/C) | ~1.5x |
| 4 (A/B/C/D) | ~2x |
| 5+ | Consider reducing variants |

**Why?** More comparisons increase chance of false positives. You're comparing:
- A vs B
- A vs C
- B vs C (sometimes)

Apply Bonferroni correction or use tools that handle this automatically.

---

## Common Sample Size Mistakes

### 1. Underpowered tests
**Problem**: Not enough sample to detect realistic effects
**Fix**: Be realistic about MDE, get more traffic, or don't test

### 2. Overpowered tests
**Problem**: Waiting for sample size when you already have significance
**Fix**: This is actually fine—you committed to sample size, honor it

### 3. Wrong baseline rate
**Problem**: Using wrong conversion rate for calculation
**Fix**: Use the specific metric and page, not site-wide averages

### 4. Ignoring segments
**Problem**: Calculating for full traffic, then analyzing segments
**Fix**: If you plan segment analysis, calculate sample for smallest segment

### 5. Testing too many things
**Problem**: Dividing traffic too many ways
**Fix**: Prioritize ruthlessly, run fewer concurrent tests

---

## When Sample Size Requirements Are Too High

Options when you can't get enough traffic:

1. **Increase MDE**: Accept only detecting larger effects (20%+ lift)
2. **Lower confidence**: Use 90% instead of 95% (risky, document it)
3. **Reduce variants**: Test only the most promising variant
4. **Combine traffic**: Test across multiple similar pages
5. **Test upstream**: Test earlier in funnel where traffic is higher
6. **Don't test**: Make decision based on qualitative data instead
7. **Longer test**: Accept longer duration (weeks/months)

---

## Sequential Testing

If you must check results before reaching sample size:

### What is it?
Statistical method that adjusts for multiple looks at data.

### When to use
- High-risk changes
- Need to stop bad variants early
- Time-sensitive decisions

### Tools that support it
- Optimizely (Stats Accelerator)
- VWO (SmartStats)
- PostHog (Bayesian approach)

### Tradeoff
- More flexibility to stop early
- Slightly larger sample size requirement
- More complex analysis

---

## Quick Decision Framework

### Can I run this test?

```
Daily traffic to page: _____
Baseline conversion rate: _____
MDE I care about: _____

Sample needed per variant: _____ (from tables above)
Days to run: Sample / Daily traffic = _____

If days > 60: Consider alternatives
If days > 30: Acceptable for high-impact tests
If days < 14: Likely feasible
If days < 7: Easy to run, consider running longer anyway
```


---

# references/test-templates.md

# A/B Test Templates Reference

Templates for planning, documenting, and analyzing experiments.

## Contents
- Test Plan Template
- Results Documentation Template
- Test Repository Entry Template
- Quick Test Brief Template
- Stakeholder Update Template
- Experiment Prioritization Scorecard
- Hypothesis Bank Template

## Test Plan Template

```markdown
# A/B Test: [Name]

## Overview
- **Owner**: [Name]
- **Test ID**: [ID in testing tool]
- **Page/Feature**: [What's being tested]
- **Planned dates**: [Start] - [End]

## Hypothesis

Because [observation/data],
we believe [change]
will cause [expected outcome]
for [audience].
We'll know this is true when [metrics].

## Test Design

| Element | Details |
|---------|---------|
| Test type | A/B / A/B/n / MVT |
| Duration | X weeks |
| Sample size | X per variant |
| Traffic allocation | 50/50 |
| Tool | [Tool name] |
| Implementation | Client-side / Server-side |

## Variants

### Control (A)
[Screenshot]
- Current experience
- [Key details about current state]

### Variant (B)
[Screenshot or mockup]
- [Specific change #1]
- [Specific change #2]
- Rationale: [Why we think this will win]

## Metrics

### Primary
- **Metric**: [metric name]
- **Definition**: [how it's calculated]
- **Current baseline**: [X%]
- **Minimum detectable effect**: [X%]

### Secondary
- [Metric 1]: [what it tells us]
- [Metric 2]: [what it tells us]
- [Metric 3]: [what it tells us]

### Guardrails
- [Metric that shouldn't get worse]
- [Another safety metric]

## Segment Analysis Plan
- Mobile vs. desktop
- New vs. returning visitors
- Traffic source
- [Other relevant segments]

## Success Criteria
- Winner: [Primary metric improves by X% with 95% confidence]
- Loser: [Primary metric decreases significantly]
- Inconclusive: [What we'll do if no significant result]

## Pre-Launch Checklist
- [ ] Hypothesis documented and reviewed
- [ ] Primary metric defined and trackable
- [ ] Sample size calculated
- [ ] Test duration estimated
- [ ] Variants implemented correctly
- [ ] Tracking verified in all variants
- [ ] QA completed on all variants
- [ ] Stakeholders informed
- [ ] Calendar hold for analysis date
```

---

## Results Documentation Template

```markdown
# A/B Test Results: [Name]

## Summary
| Element | Value |
|---------|-------|
| Test ID | [ID] |
| Dates | [Start] - [End] |
| Duration | X days |
| Result | Winner / Loser / Inconclusive |
| Decision | [What we're doing] |

## Hypothesis (Reminder)
[Copy from test plan]

## Results

### Sample Size
| Variant | Target | Actual | % of target |
|---------|--------|--------|-------------|
| Control | X | Y | Z% |
| Variant | X | Y | Z% |

### Primary Metric: [Metric Name]
| Variant | Value | 95% CI | vs. Control |
|---------|-------|--------|-------------|
| Control | X% | [X%, Y%] | — |
| Variant | X% | [X%, Y%] | +X% |

**Statistical significance**: p = X.XX (95% = sig / not sig)
**Practical significance**: [Is this lift meaningful for the business?]

### Secondary Metrics

| Metric | Control | Variant | Change | Significant? |
|--------|---------|---------|--------|--------------|
| [Metric 1] | X | Y | +Z% | Yes/No |
| [Metric 2] | X | Y | +Z% | Yes/No |

### Guardrail Metrics

| Metric | Control | Variant | Change | Concern? |
|--------|---------|---------|--------|----------|
| [Metric 1] | X | Y | +Z% | Yes/No |

### Segment Analysis

**Mobile vs. Desktop**
| Segment | Control | Variant | Lift |
|---------|---------|---------|------|
| Mobile | X% | Y% | +Z% |
| Desktop | X% | Y% | +Z% |

**New vs. Returning**
| Segment | Control | Variant | Lift |
|---------|---------|---------|------|
| New | X% | Y% | +Z% |
| Returning | X% | Y% | +Z% |

## Interpretation

### What happened?
[Explanation of results in plain language]

### Why do we think this happened?
[Analysis and reasoning]

### Caveats
[Any limitations, external factors, or concerns]

## Decision

**Winner**: [Control / Variant]

**Action**: [Implement variant / Keep control / Re-test]

**Timeline**: [When changes will be implemented]

## Learnings

### What we learned
- [Key insight 1]
- [Key insight 2]

### What to test next
- [Follow-up test idea 1]
- [Follow-up test idea 2]

### Impact
- **Projected lift**: [X% improvement in Y metric]
- **Business impact**: [Revenue, conversions, etc.]
```

---

## Test Repository Entry Template

For tracking all tests in a central location:

```markdown
| Test ID | Name | Page | Dates | Primary Metric | Result | Lift | Link |
|---------|------|------|-------|----------------|--------|------|------|
| 001 | Hero headline test | Homepage | 1/1-1/15 | CTR | Winner | +12% | [Link] |
| 002 | Pricing table layout | Pricing | 1/10-1/31 | Plan selection | Loser | -5% | [Link] |
| 003 | Signup form fields | Signup | 2/1-2/14 | Completion | Inconclusive | +2% | [Link] |
```

---

## Quick Test Brief Template

For simple tests that don't need full documentation:

```markdown
## [Test Name]

**What**: [One sentence description]
**Why**: [One sentence hypothesis]
**Metric**: [Primary metric]
**Duration**: [X weeks]
**Result**: [TBD / Winner / Loser / Inconclusive]
**Learnings**: [Key takeaway]
```

---

## Stakeholder Update Template

```markdown
## A/B Test Update: [Name]

**Status**: Running / Complete
**Days remaining**: X (or complete)
**Current sample**: X% of target

### Preliminary observations
[What we're seeing - without making decisions yet]

### Next steps
[What happens next]

### Timeline
- [Date]: Analysis complete
- [Date]: Decision and recommendation
- [Date]: Implementation (if winner)
```

---

## Experiment Prioritization Scorecard

For deciding which tests to run:

| Factor | Weight | Test A | Test B | Test C |
|--------|--------|--------|--------|--------|
| Potential impact | 30% | | | |
| Confidence in hypothesis | 25% | | | |
| Ease of implementation | 20% | | | |
| Risk if wrong | 15% | | | |
| Strategic alignment | 10% | | | |
| **Total** | | | | |

Scoring: 1-5 (5 = best)

---

## Hypothesis Bank Template

For collecting test ideas:

```markdown
| ID | Page/Area | Observation | Hypothesis | Potential Impact | Status |
|----|-----------|-------------|------------|------------------|--------|
| H1 | Homepage | Low scroll depth | Shorter hero will increase scroll | High | Testing |
| H2 | Pricing | Users compare plans | Comparison table will help | Medium | Backlog |
| H3 | Signup | Drop-off at email | Social login will increase completion | Medium | Backlog |
```
