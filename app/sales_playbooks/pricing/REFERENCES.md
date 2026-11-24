# Reference files for the `pricing` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/pricing-models.md

# Pricing Models

The eight core ways to structure *how* you charge. This is distinct from the value metric (what unit you charge on) and the tier structure (how you package). Most real products **combine** two or more of these.

## Contents
- The 8 Pricing Models
- Combining Models
- The Value/Price Ratio
- The Low-Price Retention Counterpoint

---

## The 8 Pricing Models

| Model | How it works | Best when | Reference |
|-------|-------------|-----------|-----------|
| **Flat-rate** | One price, one product, everyone pays the same | Simple product, one persona, you want zero pricing friction | Basecamp |
| **Usage-based** | Pay for what you consume (metered) | Value scales directly with volume; consumption is variable and easy to meter | Stripe |
| **Tier-based** | Good-better-best packages at set prices | Distinct segments with different needs and budgets | Kinsta |
| **User-based** | Price per seat/user | Value grows as more people in the org use it (collaboration) | Notion |
| **Feature-based** | Price gated by which capabilities are unlocked | Clear feature tiers map to willingness to pay | Intercom |
| **Credit-based** | Buy a bucket of credits, spend them on actions | Usage is lumpy or bursty; you want prepaid commitment and simple mental accounting | Audible |
| **Outcome-based** | Pay per result delivered (resolution, task completed) | You can measure and attribute the outcome, and the outcome is what the buyer actually wants | Intercom Fin, Zapier |
| **Hybrid** | Deliberate mix (e.g. platform fee + usage, or seats + credits) | A single model under- or over-charges different customers | Drift |

### When to reach for each

- **Flat-rate** — reach for it first if you can. It's the easiest to sell, easiest to understand, easiest to forecast. The tradeoff: you leave money on the table with your biggest customers.
- **Usage-based** — the fairest model when consumption tracks value, but revenue is less predictable and buyers fear a surprise bill. Pair with spend caps or alerts.
- **Tier-based** — the default for self-serve SaaS. Lets one page serve SMB through mid-market.
- **User-based** — only if value genuinely rises with headcount. If it doesn't, seats punish adoption (teams share logins to avoid paying).
- **Feature-based** — powerful for segmentation, but don't gate the feature that delivers your core value; gate the ones that separate casual from serious users.
- **Credit-based** — good for AI/actions-based products where each action has a cost. Credits decouple price from a single unit and make prepayment feel natural.
- **Outcome-based** — the emerging model for AI agents (charge per resolved ticket, per automation run). Highest trust because the buyer only pays when they win — but only viable when the outcome is measurable and clearly attributable to you.
- **Hybrid** — where most mature products end up. A base platform fee for predictability plus a usage/outcome component for upside.

---

## Combining Models

These aren't mutually exclusive. Common combinations:

- **Tiers + per-user** — seats within each package (most B2B SaaS)
- **Platform fee + usage** — predictable base, variable upside (Twilio-style)
- **Seats + credits** — pay per person, then top up credits for heavy actions
- **Feature tiers + outcome** — unlock capabilities by tier, charge per result on top

Pick the primary model from the value metric, then layer a second only if a single model clearly mis-prices a real segment.

---

## The Value/Price Ratio

Aim for roughly a **10:1 value-to-price ratio** (Ryan Kulp): the customer should perceive about **10x more value than they pay**. This is the buffer that makes the purchase feel obvious rather than negotiated, and it leaves headroom to raise prices later as you add value.

If you can't articulate 10x value, the problem is usually the offer or the positioning, not the price point.

---

## The Low-Price Retention Counterpoint

Charging too little is not the safe choice. **Low prices hurt retention** (Patrick Campbell / ProfitWell data, echoed by operators like Josh Pigford of SpyFu and Tyler Tringas): under-priced customers churn *more*, not less, because a low price signals low value and attracts the least-committed, most price-sensitive buyers.

Related: the **discount-asker signal** — customers who negotiate for a discount tend to churn at roughly **2x** the rate of full-price customers. Discounting to close a deal often buys a customer who leaves anyway.

**Implication:** when in doubt, price higher. It's easier to grandfather a price down than to claw one up, and a higher price selects for better-fit, longer-retained customers.


---

# references/pricing-page-teardown.md

# Pricing Page Teardown

A structured way to score a live pricing page and return prioritized fixes. It grades **two axes**: the classic **human buyer experience**, and — the newer, higher-leverage lens — **AI-agent readiness**: whether the LLMs and agents that increasingly shortlist and compare tools can actually read, quote, and recommend your pricing.

> **Framework credit:** the two-axis structure and especially the AI-agent-readiness lens are adapted from **Kyle Poyar's** (Growth Unhinged) pricing-page teardown. Learn-from-only — this rubric is authored independently; credit the framing to Poyar.

## Why the second axis matters now

Buyers increasingly ask ChatGPT, Perplexity, and Claude *"what's the best [category] tool and what does it cost?"* before they ever hit your site. If your price is trapped in an image, rendered only by JavaScript, or missing from the page's text, a text-fetching agent often can't read it — some agents render JS or fall back to vision/OCR, but many don't, so don't count on it. And a "Contact us" tier gives an agent no public number to quote at all. When the agent can't read your price, it recommends and quotes the competitor whose pricing it *can*. This axis is the pricing-page complement to `ai-seo` and `schema` — neither *guarantees* a citation, but a page a fetcher can't parse makes one much less likely.

**The 30-second test — the "paste test":** give the pricing URL to a **browsing-capable** AI (Perplexity, ChatGPT with search, or Claude with web) — or paste the page's *rendered* text — and ask *"What are the plans and prices?"* If it can't answer correctly and completely, agents fetching your page the same way will struggle too. It's a heuristic, not proof every agent fails (some render JS or use vision), but a clean miss is a real finding worth fixing.

## The rubric

Score each dimension **Pass / Partial / Gap** (or 1–5 if you want a number). Two sub-scores (one per axis) plus a prioritized fix list is the deliverable — not a single vanity number.

### Axis 1 — Human buyer experience

| # | Dimension | Passing looks like | Common gaps |
|---|---|---|---|
| 1 | **Value-prop clarity** | Above the fold: what you get + why it's worth it, in the buyer's words | Feature list with no outcome; "flexible plans for every team" |
| 2 | **Plan clarity / differentiation** | Obvious which plan is for whom and exactly how they differ | Feature-soup tables; tiers that blur together; no "who it's for" |
| 3 | **Cognitive load** | A buyer can decide in <30s | Too many tiers (5+), unexplained jargon, decision paralysis |
| 4 | **Trust signals** | Logos, testimonials, security/compliance, a guarantee near the CTA | No proof; trust content buried below the fold |
| 5 | **Pricing psychology** | A recommended/anchor tier, sensible anchoring, coherent charm vs. round pricing | No recommended tier; highest price hidden last; random price endings |
| 6 | **Transparency** | The actual price is shown; what's in/out is clear; no surprise fees | "Contact us" on every tier; hidden overages; usage limits omitted |

### Axis 2 — AI-agent readiness (the novel lens)

| # | Dimension | Passing looks like | Common gaps |
|---|---|---|---|
| 7 | **Machine-readable pricing** | The real numbers are in the page's HTML/text | Price in an image/SVG, JS-only render, or a PDF — text-fetching crawlers get nothing reliable; "Contact sales" leaves no public number to quote |
| 8 | **FAQ / objection coverage** | Extractable answers to "does it do X," "what's the limit," "can I cancel," "is there a free trial" | No FAQ, or answers only in a support portal an agent won't reach |
| 9 | **Per-tier depth in text** | Each plan's inclusions, limits, and quotas stated in words | Differences shown only as checkmark columns in an image; limits unnamed |
| 10 | **Structured data & extractability** | `Product`/`Offer` schema markup, clean semantic HTML, AI search/agent bots allowed to crawl (`llms.txt` is a nice-to-have, not yet a standard) | No schema; pricing behind auth/interaction; AI *search* bots blocked in robots.txt |

Dimensions 7 and 10 hand off to **`schema`** (Product/Offer JSON-LD) and **`ai-seo`** (extractability, AI-bot access, `llms.txt`) for implementation.

## How to run it

1. **Load context** — read `.agents/product-marketing.md` (ICP, positioning) so "clarity" is judged against the *right* buyer.
2. **Fetch the page as an agent would** — get the rendered text/HTML, not a screenshot. Note immediately whether prices appear in the text (that's dimension 7).
3. **Run the paste test** — ask an LLM for the plans and prices from the URL; record what it gets wrong or misses.
4. **Score all 10 dimensions** Pass/Partial/Gap with a one-line reason each.
5. **Prioritize fixes** by impact × effort. AI-readiness gaps are often *high impact, low effort* (add text prices, add Offer schema) — surface those first.

## Output template

```markdown
# Pricing Page Teardown — [url] — [date]

## Scores
- Human buyer experience: [X/6 passing]
- AI-agent readiness:      [X/4 passing]

## Paste test
[What an LLM returned for "plans and prices" — and what it got wrong/missed]

## Dimension-by-dimension
| # | Dimension | Verdict | Note |
|---|-----------|---------|------|
| 1 | Value-prop clarity | Pass/Partial/Gap | ... |
| … | … | … | … |

## Prioritized fixes (impact × effort)
1. [High/low] — [fix] — [why it matters] — [→ schema / ai-seo / cro if handing off]
2. ...

## The one thing
[The single highest-leverage fix — often "put your actual prices in text + add Offer schema so AI can quote you."]
```

## Common failure patterns

- **The image-price** — a beautiful pricing graphic with the numbers baked in. Humans love it; text-fetching agents (and screen readers) usually can't read it. Put prices in text; the image can stay as decoration.
- **"Contact us" everywhere** — sometimes right for true enterprise, but if *all* tiers hide price, both humans and agents bounce to a competitor with numbers. Show at least a starting price or a representative range.
- **Checkmark-only tables** — feature differences shown only as ✓/✗ columns in an image or icon font. State the actual limits and inclusions in words.
- **JS-only render / auth wall** — if the price only appears after interaction or login, most fetchers won't see it (only JS-rendering agents might).
- **Blocked AI *search* bots** — the crawlers that feed AI *answers* are the search agents, not the training crawlers: OpenAI's `OAI-SearchBot`, Anthropic's `Claude-SearchBot` / `Claude-User`, Perplexity's `PerplexityBot`. Blocking `GPTBot` only opts out of model *training*, not ChatGPT Search — so check which bots your robots.txt actually blocks. (Bot access is `ai-seo`'s domain — hand it off there.)

## Related
- `schema` — Product/Offer JSON-LD so machines read your tiers and prices.
- `ai-seo` — extractability, AI-bot access, `llms.txt`, getting cited by AI answers.
- `cro` — converting the human once the page is clear.
- `copywriting` — the value-prop and tier copy the teardown flags.


---

# references/research-methods.md

# Pricing Research Methods

## Contents
- Van Westendorp Price Sensitivity Meter (The Four Questions, How to Analyze, Survey Tips, Sample Output)
- MaxDiff Analysis (How It Works, Example Survey Question, Analyzing Results, Using MaxDiff for Packaging)
- Willingness to Pay Surveys
- Usage-Value Correlation Analysis

## Van Westendorp Price Sensitivity Meter

The Van Westendorp survey identifies the acceptable price range for your product.

### The Four Questions

Ask each respondent:
1. "At what price would you consider [product] to be so expensive that you would not consider buying it?" (Too expensive)
2. "At what price would you consider [product] to be priced so low that you would question its quality?" (Too cheap)
3. "At what price would you consider [product] to be starting to get expensive, but you still might consider it?" (Expensive/high side)
4. "At what price would you consider [product] to be a bargain—a great buy for the money?" (Cheap/good value)

### How to Analyze

1. Plot cumulative distributions for each question
2. Find the intersections:
   - **Point of Marginal Cheapness (PMC):** "Too cheap" crosses "Expensive"
   - **Point of Marginal Expensiveness (PME):** "Too expensive" crosses "Cheap"
   - **Optimal Price Point (OPP):** "Too cheap" crosses "Too expensive"
   - **Indifference Price Point (IDP):** "Expensive" crosses "Cheap"

**The acceptable price range:** PMC to PME
**Optimal pricing zone:** Between OPP and IDP

### Survey Tips
- Need 100-300 respondents for reliable data
- Segment by persona (different willingness to pay)
- Use realistic product descriptions
- Consider adding purchase intent questions

### Sample Output

```
Price Sensitivity Analysis Results:
─────────────────────────────────
Point of Marginal Cheapness:  $29/mo
Optimal Price Point:          $49/mo
Indifference Price Point:     $59/mo
Point of Marginal Expensiveness: $79/mo

Recommended range: $49-59/mo
Current price: $39/mo (below optimal)
Opportunity: 25-50% price increase without significant demand impact
```

---

## MaxDiff Analysis (Best-Worst Scaling)

MaxDiff identifies which features customers value most, informing packaging decisions.

### How It Works

1. List 8-15 features you could include
2. Show respondents sets of 4-5 features at a time
3. Ask: "Which is MOST important? Which is LEAST important?"
4. Repeat across multiple sets until all features compared
5. Statistical analysis produces importance scores

### Example Survey Question

```
Which feature is MOST important to you?
Which feature is LEAST important to you?

□ Unlimited projects
□ Custom branding
□ Priority support
□ API access
□ Advanced analytics
```

### Analyzing Results

Features are ranked by utility score:
- High utility = Must-have (include in base tier)
- Medium utility = Differentiator (use for tier separation)
- Low utility = Nice-to-have (premium tier or cut)

### Using MaxDiff for Packaging

| Utility Score | Packaging Decision |
|---------------|-------------------|
| Top 20% | Include in all tiers (table stakes) |
| 20-50% | Use to differentiate tiers |
| 50-80% | Higher tiers only |
| Bottom 20% | Consider cutting or premium add-on |

---

## Willingness to Pay Surveys

**Direct method (simple but biased):**
"How much would you pay for [product]?"

**Better: Gabor-Granger method:**
"Would you buy [product] at [$X]?" (Yes/No)
Vary price across respondents to build demand curve.

**Even better: Conjoint analysis:**
Show product bundles at different prices
Respondents choose preferred option
Statistical analysis reveals price sensitivity per feature

---

## Usage-Value Correlation Analysis

### 1. Instrument usage data
Track how customers use your product:
- Feature usage frequency
- Volume metrics (users, records, API calls)
- Outcome metrics (revenue generated, time saved)

### 2. Correlate with customer success
- Which usage patterns predict retention?
- Which usage patterns predict expansion?
- Which customers pay the most, and why?

### 3. Identify value thresholds
- At what usage level do customers "get it"?
- At what usage level do they expand?
- At what usage level should price increase?

### Example Analysis

```
Usage-Value Correlation Analysis:
─────────────────────────────────
Segment: High-LTV customers (>$10k ARR)
Average monthly active users: 15
Average projects: 8
Average integrations: 4

Segment: Churned customers
Average monthly active users: 3
Average projects: 2
Average integrations: 0

Insight: Value correlates with team adoption (users)
        and depth of use (integrations)

Recommendation: Price per user, gate integrations to higher tiers
```


---

# references/tier-structure.md

# Tier Structure and Packaging

## Contents
- How Many Tiers?
- Good-Better-Best Framework
- Tier Differentiation Strategies
- Example Tier Structure
- Packaging for Personas (Identifying Pricing Personas, Persona-Based Packaging)
- Freemium vs. Free Trial (When to Use Freemium, When to Use Free Trial, Hybrid Approaches)
- Enterprise Pricing (When to Add Custom Pricing, Enterprise Tier Elements, Enterprise Pricing Strategies)

## How Many Tiers?

**2 tiers:** Simple, clear choice
- Works for: Clear SMB vs. Enterprise split
- Risk: May leave money on table

**3 tiers:** Industry standard
- Good tier = Entry point
- Better tier = Recommended (anchor to best)
- Best tier = High-value customers

**4+ tiers:** More granularity
- Works for: Wide range of customer sizes
- Risk: Decision paralysis, complexity

---

## Good-Better-Best Framework

**Good tier (Entry):**
- Purpose: Remove barriers to entry
- Includes: Core features, limited usage
- Price: Low, accessible
- Target: Small teams, try before you buy

**Better tier (Recommended):**
- Purpose: Where most customers land
- Includes: Full features, reasonable limits
- Price: Your "anchor" price
- Target: Growing teams, serious users

**Best tier (Premium):**
- Purpose: Capture high-value customers
- Includes: Everything, advanced features, higher limits
- Price: Premium (often 2-3x "Better")
- Target: Larger teams, power users, enterprises

---

## Tier Differentiation Strategies

**Feature gating:**
- Basic features in all tiers
- Advanced features in higher tiers
- Works when features have clear value differences

**Usage limits:**
- Same features, different limits
- More users, storage, API calls at higher tiers
- Works when value scales with usage

**Support level:**
- Email support → Priority support → Dedicated success
- Works for products with implementation complexity

**Access and customization:**
- API access, SSO, custom branding
- Works for enterprise differentiation

---

## Example Tier Structure

```
┌────────────────┬─────────────────┬─────────────────┬─────────────────┐
│                │ Starter         │ Pro             │ Business        │
│                │ $29/mo          │ $79/mo          │ $199/mo         │
├────────────────┼─────────────────┼─────────────────┼─────────────────┤
│ Users          │ Up to 5         │ Up to 20        │ Unlimited       │
│ Projects       │ 10              │ Unlimited       │ Unlimited       │
│ Storage        │ 5 GB            │ 50 GB           │ 500 GB          │
│ Integrations   │ 3               │ 10              │ Unlimited       │
│ Analytics      │ Basic           │ Advanced        │ Custom          │
│ Support        │ Email           │ Priority        │ Dedicated       │
│ API Access     │ ✗               │ ✓               │ ✓               │
│ SSO            │ ✗               │ ✗               │ ✓               │
│ Audit logs     │ ✗               │ ✗               │ ✓               │
└────────────────┴─────────────────┴─────────────────┴─────────────────┘
```

---

## Packaging for Personas

### Identifying Pricing Personas

Different customers have different:
- Willingness to pay
- Feature needs
- Buying processes
- Value perception

**Segment by:**
- Company size (solopreneur → SMB → enterprise)
- Use case (marketing vs. sales vs. support)
- Sophistication (beginner → power user)
- Industry (different budget norms)

### Persona-Based Packaging

**Step 1: Define personas**

| Persona | Size | Needs | WTP | Example |
|---------|------|-------|-----|---------|
| Freelancer | 1 person | Basic features | Low | $19/mo |
| Small Team | 2-10 | Collaboration | Medium | $49/mo |
| Growing Co | 10-50 | Scale, integrations | Higher | $149/mo |
| Enterprise | 50+ | Security, support | High | Custom |

**Step 2: Map features to personas**

| Feature | Freelancer | Small Team | Growing | Enterprise |
|---------|------------|------------|---------|------------|
| Core features | ✓ | ✓ | ✓ | ✓ |
| Collaboration | — | ✓ | ✓ | ✓ |
| Integrations | — | Limited | Full | Full |
| API access | — | — | ✓ | ✓ |
| SSO/SAML | — | — | — | ✓ |
| Audit logs | — | — | — | ✓ |
| Custom contract | — | — | — | ✓ |

**Step 3: Price to value for each persona**
- Research willingness to pay per segment
- Set prices that capture value without blocking adoption
- Consider segment-specific landing pages

---

## Freemium vs. Free Trial

### When to Use Freemium

**Freemium works when:**
- Product has viral/network effects
- Free users provide value (content, data, referrals)
- Large market where % conversion drives volume
- Low marginal cost to serve free users
- Clear feature/usage limits for upgrade trigger

**Freemium risks:**
- Free users may never convert
- Devalues product perception
- Support costs for non-paying users
- Harder to raise prices later

### When to Use Free Trial

**Free trial works when:**
- Product needs time to demonstrate value
- Onboarding/setup investment required
- B2B with buying committees
- Higher price points
- Product is "sticky" once configured

**Trial best practices:**
- 7-14 days for simple products
- 14-30 days for complex products
- Full access (not feature-limited)
- Clear countdown and reminders
- Credit card optional vs. required trade-off

**Credit card upfront:**
- Higher trial-to-paid conversion (40-50% vs. 15-25%)
- Lower trial volume
- Better qualified leads

### Hybrid Approaches

**Freemium + Trial:**
- Free tier with limited features
- Trial of premium features
- Example: Zoom (free 40-min, trial of Pro)

**Reverse trial:**
- Start with full access
- After trial, downgrade to free tier
- Example: See premium value, live with limitations until ready

---

## Enterprise Pricing

### When to Add Custom Pricing

Add "Contact Sales" when:
- Deal sizes exceed $10k+ ARR
- Customers need custom contracts
- Implementation/onboarding required
- Security/compliance requirements
- Procurement processes involved

### Enterprise Tier Elements

**Table stakes:**
- SSO/SAML
- Audit logs
- Admin controls
- Uptime SLA
- Security certifications

**Value-adds:**
- Dedicated support/success
- Custom onboarding
- Training sessions
- Custom integrations
- Priority roadmap input

### Enterprise Pricing Strategies

**Per-seat at scale:**
- Volume discounts for large teams
- Example: $15/user (standard) → $10/user (100+)

**Platform fee + usage:**
- Base fee for access
- Usage-based above thresholds
- Example: $500/mo base + $0.01 per API call

**Value-based contracts:**
- Price tied to customer's revenue/outcomes
- Example: % of transactions, revenue share
