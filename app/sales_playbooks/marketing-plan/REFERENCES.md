# Reference files for the `marketing-plan` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/aarrr-framework.md

# AARRR Framework — Primer for Plan Sequencing

AARRR (Dave McClure's "pirate metrics") is the spine of every plan produced by this skill. This doc is the primer + the decision rules for when each stage gets prioritized.

## The five stages

| Stage | Question | Common metrics |
|---|---|---|
| **A**cquisition | How do strangers become aware of us? | Visits, MQLs, signup-page sessions, app-store visits, CAC by channel |
| **A**ctivation | Once they try us, do they have an experience that converts? | Signup completion rate, time-to-value, % completing first key action, trial → paid rate |
| **R**etention | Do they stay and deepen? | DAU/WAU/MAU, week-1/4/12 retention, churn |
| **R**eferral | Do retained users bring more users? | Viral coefficient, NPS, ambassador attribution |
| **R**evenue | What do they pay, who pays, how does it compound? | ARPU, LTV, expansion revenue, ARR / MRR |

> **Signup boundary rule.** Signup *intent* (a stranger landing on the signup page) is Acquisition. Signup *completion* and everything after (first key action, trial-to-paid) is Activation. Apply this rule consistently across all docs and the plan template.

## Why AARRR for plan sequencing

Three reasons.

**1. Funnel-stage tagging forces prioritization.** Without AARRR, marketing plans become channel-organized ("here's the SEO plan, here's the social plan, here's the paid plan"). Channels can address multiple stages; tagging by stage instead asks the more useful question: *what stage of the funnel is the binding constraint right now?*

**2. Fix the leak before pouring water in.** The Activation/Retention question ("does the funnel convert at acceptable rates given exposure?") is usually higher leverage than the Acquisition question ("how do we get more exposure?"). AARRR sequencing surfaces this naturally.

**3. The Revenue / Referral conversation is honest.** Most marketing plans bury monetization under "growth" and treat referral as wishful thinking. AARRR forces explicit treatment of both.

## Brand and content — not a stage, cross-cutting

A common mistake: making "Brand" or "Content" the sixth bucket. They're not — they serve every stage.

- **Brand voice** governs every piece of copy across every stage
- **Content** feeds Acquisition (SEO, social), Activation (onboarding copy), Retention (email lifecycle), Referral (ambassador talking points), Revenue (pricing pages, sales material)

In the plan, brand/content shows up as the strategic frame (Section 2) and cross-cutting in Section 11's ops stack — never as its own AARRR section.

## Diagnosing the binding constraint — which AARRR stage is highest leverage?

For every client, one or two AARRR stages will be the binding constraint. The plan sequences moves there first.

**Decision rules:**

### If you don't have any users → start with Acquisition
- Pre-launch / day-0 / waitlist stage
- No funnel data exists
- Leverage = building the first 100 users

### If you have users but they bounce → start with Activation
- Signups happen but activation rate is low
- App Store conversion is poor
- Onboarding completion is broken
- Day 1 → paid rate is much lower than Day 30 → paid (means product converts given time but onboarding doesn't bridge to it)
- Leverage = bridging signup to first felt value

### If activation works but users churn → start with Retention
- Month 1 retention is below category norms
- Activated users stop using within 7–14 days
- LTV is short
- Leverage = lifecycle, deepening engagement, churn prevention

### If retention is strong but growth is slow → start with Referral / Revenue
- Retained users love the product but don't share
- Inbound referrals come in unstructured
- Pricing hasn't been pressure-tested
- ARPU is low for the value delivered
- Leverage = WOM mechanics + pricing optimization (these often cluster)

### If everything works at small scale → start with Acquisition (scaling)
- Funnel is healthy
- Question is just "more"
- This is the "post-fit" scaling problem

## Stage-by-stage strategic patterns

### Acquisition

**The diagnostic question:** Where is the gap between TAM-level awareness and current funnel volume? What channels are saturated by competitors vs. open?

**Common Acquisition moves:**
- SEO content strategy (organic compounding)
- Founder-led channels (LinkedIn, X, Substack for B2B; Instagram/TikTok for D2C)
- Paid acquisition (when budget unlocks)
- App Store / Play Store / marketplace listing optimization
- PR and credibility-anchor amplification
- Events (live, webinar, conference speaking)
- Partnerships (newsletter swaps, integration co-marketing, reseller / agency partners)
- Hardware / commerce surface (Shopify SEO + Amazon for hybrid businesses)
- B2B sales support (case studies, partner pages, vertical content)

**Sequencing principle:** Build the organic compound first (SEO + founder-led + content + PR amplification + ambassadors). Only layer paid on top of a working organic baseline. Premature paid amplifies what's broken.

### Activation

**The diagnostic question:** Where in the user's first session do they decide "this works for me" or "this doesn't"? What stops them from reaching that moment?

**Common Activation moves:**
- Bedrock fixes (broken gates, broken signup steps, broken paywall)
- Onboarding tests / rebuild (often the most leveraged single move)
- App Store listing rewrite (the threshold to the trial)
- Lifecycle Flow ship order (when to ship onboarding emails)
- Paywall structure + trial length
- Free → paid bridge (in-app upsells, soft paywalls)

**Sequencing principle:** Get to first felt value as fast as possible. Everything that adds friction between "user opens app" and "user has the experience that converts them" is a candidate to cut.

### Retention

**The diagnostic question:** Why do users churn? What would have made them stay? What's the "second moment of value" after the first one?

**Common Retention moves:**
- Lifecycle email flows: onboarding, lapsed user re-engagement, post-purchase, win-back
- Subscription / preference centers
- Churn reconciliation (often metric definitions don't match across surfaces)
- Hardware → software activation paths (for hybrid businesses)
- Annual plan defaults / pricing structure (cross-cuts Revenue)
- Support as marketing (high-touch moments that drive stories)
- Community + practitioner networks

**Sequencing principle:** Ship lifecycle flows in the order their content is most stable. Hardware post-purchase flows ship first (they don't reference in-app screens that might change). Onboarding emails ship last (they reference UI that might change). Win-back is a quarterly campaign, not a one-time flow.

### Referral

**The diagnostic question:** Is there inbound referral interest that isn't being captured? What's the share-after-value moment that's natural to the product?

**Common Referral moves:**
- Ambassador / affiliate program (start with inbound interest, not cold recruitment)
- Share-after-value moments built into the product (reflection prompts, milestone celebrations)
- Founder amplification (founder as referrer-zero)
- Long-game expert / Guides / certified-host networks (for category-creating businesses)
- Gifting flows (consumer / hardware)
- Two-sided referrals (reward both referrer and referred)

**Sequencing principle:** Lead with whoever is already raising their hand. If there are 5 inbound ambassadors, launch with those 5 — don't wait for a "complete program." Iterate based on what they tell you.

### Revenue

**The diagnostic question:** Is the company underpricing? Underpackaging? Missing an upsell? What's the "right" price discipline given LTV and brand voice?

**Common Revenue moves:**
- Pricing audit (what's actually charged today vs. listed?)
- Annual plan defaults
- Hardware → software bundling formalization
- Storefront / commerce page optimization
- B2B case studies + sales material
- Long-term value pool flags (data, expansion, enterprise) — flagged not executed

**Sequencing principle:** Run the pricing audit before testing changes. Surprisingly often, the "implied" pricing on the dashboard doesn't match the listed price — discounts, trials, or plan mix distorts the read. Surface the ground truth first.

## How to assign a move to a stage

Some moves clearly belong to one stage. Others span. The rule:

**Assign to the stage where the move's primary measurable impact lands.**

Examples:
- "Rewrite App Store listing in voice" — spans Acquisition (organic discovery) and Activation (threshold to trial). Primary impact = Activation (trial conversion rate). Assign to Activation, mention crossover.
- "Eye mask Shopify page rewrite" — spans Acquisition (organic search for sleep mask) and Revenue (sale conversion). Primary impact = Revenue (transaction). Assign to Revenue, mention crossover.
- "Alex's LinkedIn cadence" — Acquisition (top of funnel for D2C subscribers).
- "Customer.io Flow 6 (eye mask post-purchase)" — Retention (deepens hardware buyer engagement) with crossover to Activation (hardware → app premium activation path).

When in doubt: where would removing this move hurt the most? Assign there.

## When the AARRR breakdown isn't equal

For most clients, the plan won't have equal volume across stages. That's fine — and worth surfacing as a diagnostic.

- **Heavy Acquisition section** = client has product-market fit but top-of-funnel is the bottleneck. Common for early-stage with strong retention metrics.
- **Heavy Activation section** = client has traffic but conversion is broken. Often beta-stage products.
- **Heavy Retention section** = client has churn problem. Often mid-stage products that scaled past PMF without lifecycle infrastructure.
- **Heavy Referral section** = client has loyalty but no WOM mechanics. Often consumer products with passionate users.
- **Heavy Revenue section** = client is underpricing or missing monetization layers. Common for tools transitioning from free to paid.

If a plan ends up evenly distributed across all five stages, the diagnostic was probably weak — re-examine the funnel state intake to find where the binding constraint is.

## A note on the order of presentation

Always present AARRR in order (Acquisition → Activation → Retention → Referral → Revenue) regardless of priority order.

This is for the reader's mental model. Founders expect the funnel to flow top-to-bottom. If Retention is the most-leveraged stage but you lead with Retention, the reader has to context-switch.

To signal priority, use the executive summary (Section 1) — name the biggest bets there. The AARRR breakdown then walks the funnel in order, with the most leverage-positive section being the longest and most-detailed.


---

# references/budget-planning.md

# Budget Planning — Scientific Methods for Setting the Marketing Budget

The problem with most SaaS marketing budgets is that they're pulled out of thin air — a number that hopefully doesn't constrain growth too much, but doesn't anchor in customer-acquisition economics either. The result: when someone asks "why this number?" there's no answer.

Two scientific methods solve this. Use one (not both) in Section 8 (Revenue) and Section 10 (12-month outlook) of every plan.

Excerpted and adapted from *Founding Marketing* by Corey Haines.

## Method 1 — Revenue-Based (5–40% of annual revenue)

**Direction:** budget → revenue goal.

You start with what the company can comfortably spend on marketing, then forecast what revenue that spend can plausibly generate.

### The ranges

| Posture | % of ARR | When to use |
|---|---|---|
| **Conservative (profit-preserving)** | 5% | Established business focused on profit distribution; bootstrapped; founder-paid customer base |
| **Standard growth** | 15–25% | Most healthy SaaS in the seed-to-Series-A range |
| **Aggressive growth (deploying raised capital)** | up to 40% | Recently funded round, mandate to deploy fast, board accepts burn |

For reference: public SaaS companies routinely report sales-and-marketing spend between 20% and 55% of revenue (Zoom historically ran between 20% and 55% across years).

### The math (Conservative example)

Business at $1M ARR, 5% allocation:

- Annual marketing budget: **$50,000**
- Blended CAC: $100 → can acquire **500 new customers**
- ARPC: $50/mo → adds **$300K** to ARR
- Account for 15% annual churn → 85% × $300K = **+$255K net new ARR**
- End-of-year goal: **$1.255M ARR**

### The math (Aggressive example)

Business at $1M ARR, 40% allocation:

- Annual marketing budget: **$400,000**
- Blended CAC: $100 → can acquire **4,000 new customers**
- ARPC: $50/mo → adds **$2.4M** to ARR
- End-of-year goal: **$3.4M ARR**

### Two keys to making this method work

1. **Know your blended CAC** (see "Calculating CAC" below)
2. **Match the allocation percentage to your actual ambition.** A founder running 5% allocation while telling the board they expect to triple revenue is showing two incompatible signals.

## Method 2 — Goal-Based (reverse-engineered from the revenue target)

**Direction:** revenue goal → budget.

You start with the revenue goal and work backward through the unit economics to derive the budget required to hit it. Best for:

- Companies just starting up (no historical CAC baseline yet, working from first principles)
- Companies anticipating outside capital (need to defend the ask)
- Companies using revenue-based financing (Pipe, Capchase, Founderpath)

### The formula

```
Marketing budget = [(New ARR / (ARPC × 12)) × CAC] / annual retention rate
```

### Worked example: $1M ARR → $2M ARR

Step 1 — How much new ARR per customer?
ARPC × 12 = $50 × 12 = **$600 ARR per new customer**

Step 2 — How many new customers do we need?
$1,000,000 / $600 = **1,667 new customers**

Step 3 — What's the raw acquisition cost?
1,667 × $100 CAC = **$166,700**

Step 4 — Account for churn (15% annual = 85% retention)
$166,700 / 0.85 = **$196,118** (round to **$200K**)

When someone asks how you got to the budget, walk them through the four steps. It's defensible.

### Why this formula and not something simpler

The four steps each correspond to a real economic reality:
- Step 1 converts MRR-language into the ARR-language a board talks in
- Step 2 names the customer count, which is what the funnel actually has to deliver
- Step 3 anchors the budget in the cost of acquisition
- Step 4 acknowledges that churned customers don't count toward net new ARR, so the budget needs to cover the gap

### Required buffer

**Always add 10–20% as "experimental budget"** on top of the formula output. CAC is the main dependency; if CAC comes in 50% higher than estimated, the cascading effect is missing the revenue goal. It is much cheaper to overestimate CAC than to underestimate it.

The experimental budget also funds the experiments that find your next channel before your current one plateaus (see `growth-patterns.md` — channel S-curves).

## The VC growth path (3-3-2-2-2 rule)

Once a company has crossed $1M ARR and taken a Series A, the implicit benchmark VCs expect is:

| Year | ARR multiple | Cumulative ARR (from $1M start) |
|---|---|---|
| Year 0 | — | $1M |
| Year +1 | 3× | $3M |
| Year +2 | 3× | $9M |
| Year +3 | 2× | $18M |
| Year +4 | 2× | $36M |
| Year +5 | 2× | $72M |
| Year +6 | 2× | $144M |
| Year +7 | 2× | $288M |

That's the 3-3-2-2-2 rule. Useful when:

- The plan needs to map 12-month and 36-month milestones to VC expectations
- The founder is mid-raise and the board needs to see a plausible path to the next round
- Section 10 (12-month outlook) needs anchoring against an industry benchmark, not just internal ambition

Most companies miss it. That's fine. Knowing the benchmark gives the team a defensible reason to either match it or explicitly choose not to.

## Calculating CAC (blended, not paid-only)

If there's no historical CAC, use a baseline: **one year of revenue from the smallest paid plan.** Deploy the budget, capture actual CAC data, replace the baseline with the measured number for the next planning cycle.

For an established CAC calculation, **CAC must be blended.** Include:

- Marketing salaries (full loaded cost, not just base)
- Advertising spend
- Marketing tech stack costs
- Content production costs (writers, designers, video editors)
- Agency / contractor retainers
- SDR / BDR salaries if doing outbound
- Tools (CRM, marketing automation, analytics)

Then divide by the number of new customers acquired in the period. That blended number is the one to use in either budgeting method.

The mistake to avoid: calculating CAC from paid ad spend alone. A company that "doesn't run ads" still has a CAC — it's just hidden in the content team, the founder's time, the SEO contractor, the conference booth.

## The reality check on forecasting

This whole framework derives a budget and a revenue goal — not a 12-month month-by-month forecast accurate to the dollar.

**Unless the company is publicly traded, all forecasts are educated guesses.** No startup under $100M ARR reliably hits forecasts to the month. The honest framing for the plan:

- The annual goal is a defensible direction-of-travel
- The budget is the resource commitment that makes the goal plausible
- The 90-day roadmap (Section 9) is what's actionable now
- Month-to-month variance is expected; quarterly review is when the plan adjusts

What's actionable: how to deploy the budget, what concrete moves to execute, what to adjust when real data comes in.

What's not actionable: trying to forecast traffic, pipeline, retention curves, conversion rates, and channel mix all down to the decimal point and expecting that forecast to hold. Founders who over-engineer the forecast tend to spend the plan period explaining variance instead of executing.

**Rule for the plan:** the budget number is honest. The annual goal is honest. The month-by-month projection is illustrative.

## How this flows into the plan

| Section | What to include |
|---|---|
| **3 (Current state)** | Current monthly marketing spend broken down by line (paid, tools, content, headcount, retainers). Compute current %-of-ARR allocation. |
| **8 (Revenue)** | The unit-economics table (CAC, ARPC, churn) that feeds whichever budget method you're using. |
| **10 (12-month outlook)** | Apply Method 1 or Method 2 to derive the 12-month budget and the resulting revenue goal. Anchor against the 3-3-2-2-2 rule if Series A+ and VC-backed. |
| **11 (Ops stack)** | Show the budget allocation across the AARRR stages — what % to Acquisition, Activation, etc. The ops-stack mapping informs which line items grow when the next funding tier unlocks. |
| **13 (Open decisions)** | If CAC is unknown or contested, flag it as the highest-impact open decision — every other number depends on it. |

## When to choose which method

- **Method 1 (Revenue-Based)** when the company has historical CAC data, a profit/burn posture, and the question is "given our posture, what's a plausible goal."
- **Method 2 (Goal-Based)** when the company has a specific goal (board mandate, VC milestone, fundraise target) and the question is "what budget do we need to hit it."

For most plans in the seed-to-Series-A range, Method 2 is more useful — it forces the conversation about whether the goal is funded.


---

# references/client-types.md

# Client Types — Variations by Business Model

The 13-section plan structure stays consistent across client types. What changes is the **content emphasis** within each section. This doc names the dominant patterns by client archetype.

## Archetype 1 — B2B SaaS

### Core characteristics
- Subscription revenue
- Often higher ACV ($1K–$100K+ per year)
- Sales-assisted or self-serve depending on tier
- Buyer often different from user (champion vs. end-user)

### AARRR emphasis

**Acquisition heavy:**
- SEO is the dominant top-of-funnel motion (people search for solutions)
- Content marketing (blog, knowledge base, comparison pages) drives MQLs
- LinkedIn for both organic founder presence and paid
- Outbound (cold email + LinkedIn) often complements inbound
- Events (conferences, webinars) for high-ACV products

**Activation:**
- Signup → trial → first key action (PLG products)
- Trial → demo → POC (sales-led products)
- Empty states matter — guide users to first value action

**Retention:**
- Product engagement metrics (DAU, feature adoption)
- Customer success motion (CSM team for higher ACV)
- Lifecycle emails focused on feature discovery, value moments

**Referral:**
- Customer advocacy programs
- Partner / integration co-marketing
- G2 / Capterra reviews
- Champion-to-buyer expansion

**Revenue:**
- Expansion / NRR is often the biggest growth lever
- Tier upgrades, seat expansion, usage-based add-ons

### Skills emphasis
- `cold-email`, `programmatic-seo`, `competitors`, `seo-audit`, `ai-seo`
- `ads` weighted toward LinkedIn + Google
- `emails` for trial nurture + lifecycle
- `pricing` for tier optimization

### Tier-1 budget priority
- SEO + content > everything else
- Founder-led LinkedIn channel
- Customer.io / Mailchimp for nurture
- HARO + investor backchannel for PR

---

## Archetype 2 — D2C Consumer App (Subscription)

### Core characteristics
- Lower ACV ($5–$30/mo typically)
- High volume, lower margin per user
- App Store / Play Store as the primary acquisition surface
- Lifecycle email + push for retention
- Often paid-acquisition-driven once budget unlocks

### AARRR emphasis

**Acquisition:**
- App Store Optimization (ASO) is the highest-leverage non-site asset
- Paid social (Meta, TikTok) often dominant once budget exists
- Apple Search Ads for high-intent App Store traffic
- Influencer + content creators
- PR + endorsements

**Activation:**
- Onboarding is the dominant activation surface
- Time-to-value must be minutes, not hours
- Paywall structure + trial length critical

**Retention:**
- Lifecycle email + push
- In-app reminders (carefully — overuse = churn)
- Subscription preference center
- Win-back campaigns

**Referral:**
- Built-in sharing (share-a-month flow)
- Two-sided referrals
- Influencer / creator ambassadors

**Revenue:**
- Annual plan default is the biggest single move (compresses MRR but improves LTV)
- Tier optimization (Free → Premium → Premium+)
- In-app upsells

### Skills emphasis
- `onboarding`, `paywalls`, `emails`
- `ads`, `ad-creative` (heavy creative iteration)
- `referrals`
- `pricing` for annual default + tier consolidation

### Tier-1 budget priority
- ASO first (highest organic leverage)
- Onboarding rebuild
- Lifecycle email shipping
- Founder-led social if founder is on-camera

---

## Archetype 3 — Hybrid Hardware + Software

### Core characteristics
- Physical product + software companion (e.g., Quietude's eye mask + app)
- Hardware as a distribution wedge (lower price, easier first purchase)
- Software as the LTV (recurring revenue)
- Blended CAC across both surfaces

### AARRR emphasis

**Acquisition:**
- Shopify storefront SEO (hardware product pages target consumer search)
- Amazon listing (high-discovery, takes margin)
- PR amplification (hardware is photogenic — high-profile influencer endorsements move volume)
- Paid social for hardware (Meta + Instagram, eye-catching creative)

**Activation:**
- Two activations to track: hardware unboxing experience + software signup
- Hardware → software activation flow is the bridge
- Concierge setup for high-value hardware buyers

**Retention:**
- Hardware post-purchase lifecycle (different from app onboarding)
- Software companion drives stickiness
- Community / practitioner network around hardware

**Referral:**
- Hardware gifting flows (high WOM for physical products)
- Eye-catching hardware drives organic social sharing
- Reviews on Shopify + Amazon

**Revenue:**
- Blended LTV math is critical (hardware margin + software recurring)
- Bundle strategy (hardware buy → free Premium for X months)
- Annual plan default for software

### Skills emphasis
- `seo-audit` for Shopify product pages
- `emails` for both hardware post-purchase and software lifecycle
- `referrals` with gifting layer
- `pricing` for blended-bundle math
- `ads` with creative-heavy Meta presence

### Tier-1 budget priority
- Shopify product page optimization
- Hardware post-purchase lifecycle ship
- Bundle strategy formalization
- Hardware → app activation audit

---

## Archetype 4 — Marketplace

### Core characteristics
- Two-sided product (supply + demand)
- Network effects matter
- Liquidity is the critical early metric
- Take-rate × GMV is the revenue model

### AARRR emphasis

**Acquisition:**
- Two funnels — supply and demand
- Supply often acquired through outbound / partnership / cold email
- Demand often acquired through SEO / paid / content
- City-by-city programmatic SEO common

**Activation:**
- Supply activation: first listing posted, first response sent
- Demand activation: first purchase / first match / first transaction
- Both sides need their own onboarding

**Retention:**
- Repeat transaction frequency
- Supply utilization (% of listings active)
- Demand habit (DAU / MAU)

**Referral:**
- Supply → supply (refer other providers)
- Demand → demand (refer other buyers)
- Cross-side referrals are weaker

**Revenue:**
- Take-rate optimization
- Premium tier (better matching, lower fees)
- Lead-gen vs. transaction-fee monetization

### Skills emphasis
- `programmatic-seo` for city pages, vertical pages
- `cold-email` for supply-side recruitment
- `referrals` for both sides
- `pricing` for take-rate decisions

### Tier-1 budget priority
- Programmatic SEO build for one side
- Cold outbound to seed supply (or demand, whichever is bottleneck)
- Lifecycle email for both sides

---

## Archetype 5 — Developer Tool / Open Source

### Core characteristics
- Technical buyer (developer or eng leader)
- High bar for content quality (developers are skeptical)
- DevRel matters more than traditional marketing
- Open source layer often funnel into commercial product

### AARRR emphasis

**Acquisition:**
- Technical content + docs SEO
- DevRel (conferences, talks, community)
- GitHub presence + npm/pip/etc. discovery
- Hacker News + Reddit + dev Twitter

**Activation:**
- First build / first integration is the activation event
- Time-to-Hello-World matters
- Documentation = onboarding for dev tools

**Retention:**
- Depth of integration (using more of the product)
- Team adoption (one user → entire org)
- Active project count

**Referral:**
- Star count on GitHub (semi-organic)
- Recommendation in technical forums
- Conference talks mentioning the tool

**Revenue:**
- Free → paid conversion when usage exceeds limits
- Team plans, enterprise tiers
- Support / SLA upsells

### Skills emphasis
- `programmatic-seo` for docs
- Less emphasis on traditional `ads`
- Heavy `content-strategy` + technical content
- `cold-email` to engineering leads at target companies

### Tier-1 budget priority
- Docs + technical content production
- DevRel (founder doing talks)
- GitHub presence
- HN / Reddit / dev community

---

## Archetype 6 — Deep-Tech / Scientific / Clinical

### Core characteristics
- Long sales cycles
- Heavy credibility burden (must prove the science)
- Highly informed buyers (academics, clinicians, researchers)
- Often regulatory considerations

### AARRR emphasis

**Acquisition:**
- Academic publishing + peer-reviewed studies
- Conference speaking (academic + industry)
- Investor / advisor introductions
- PR via credibility hooks

**Activation:**
- Pilot programs / proof-of-concepts
- Concierge setup with high-touch onboarding
- Educational webinars / training

**Retention:**
- Customer success heavily
- Co-publication with customers
- Community of practice

**Referral:**
- Academic / clinical references
- Conference panel features
- Case studies with named institutions

**Revenue:**
- Pilot → paid expansion
- Institutional contracts (multi-seat / multi-year)
- Compliance / certification upsells

### Skills emphasis
- Light traditional marketing
- Heavy `product-marketing`, `sales-enablement`, `pricing`
- `cold-email` to specific researchers / practitioners
- PR + investor marketing

### Tier-1 budget priority
- Academic outreach + conference speaking
- Investor backchannel for institutional warm intros
- Pilot deployment with key customers
- Case study + scientific publication

---

## Archetype 7 — Commerce / DTC (non-subscription)

### Core characteristics
- Physical or digital products sold transactionally
- Average Order Value matters
- Repeat purchase rate is the key retention metric

### AARRR emphasis

**Acquisition:**
- Paid social (Meta, TikTok) often dominant
- Shopify SEO for product pages
- Amazon listings
- Influencer + creator partnerships

**Activation:**
- First purchase is the activation event
- Cart abandonment recovery
- Trust signals on checkout (reviews, returns, shipping)

**Retention:**
- Post-purchase lifecycle
- Loyalty programs
- Email + SMS for repeat purchase

**Referral:**
- Gifting flows
- Refer-a-friend programs
- Reviews + UGC

**Revenue:**
- AOV optimization (bundles, upsells)
- Customer LTV optimization (repeat purchase frequency)
- Subscription option for repeat purchases

### Skills emphasis
- `ads` + `ad-creative` (heavy weight)
- `emails` for post-purchase + abandoned cart
- `referrals` with gifting
- `pricing` for bundles + subscription option

### Tier-1 budget priority
- Shopify storefront optimization
- Email lifecycle ship
- Influencer / UGC seeding
- Paid social testing (if minimal budget exists)

---

## How to use this doc when drafting a plan

When you start drafting Sections 4–8 (AARRR), identify the client's archetype (or hybrid if applicable) and lean into the patterns above.

**Hybrid cases are common.** Quietude is "Hybrid hardware + software" with significant overlap to "Deep-tech / scientific / clinical" (because of the peer-reviewed study + clinical positioning). The plan blends emphases from both archetypes.

When in doubt, lead with the archetype that best fits the *primary monetization model*. Quietude's primary monetization is software subscription (with hardware as the wedge), so the D2C consumer app + hardware-hybrid patterns dominate, with deep-tech credibility moves layered in.

## When the client doesn't fit cleanly

Some clients defy archetype:
- **Content / media businesses** — neither SaaS nor commerce; ad revenue or subscription model
- **Social networks** — own category, network effects dominate
- **Real estate / events** — physical + service model

For these, identify the closest archetype and adjust. Don't force-fit — name the deviation in the plan's Strategic Frame.


---

# references/current-state-rubric.md

# Current State Rubric — 17-Section Scoring Lens

This 17-section rubric is the source of truth for Section 3 ("Current State") of every marketing plan. Score each section 0–5 from available materials, then write a 2–4 sentence "shape interpretation" that names where strengths and gaps cluster.

## How to score

**From rich materials.** When the team has shared decks, prior content audits, a brand voice doc, kickoff transcript, app store and analytics snapshots — score each section from those artifacts. Mark "scored from materials" in the section heading so the team can push back where they have better data.

**From a separately scored audit.** If the team has already run a scored current-state assessment (in any format), ingest those scores directly. Don't redo the work — note the date the rubric was scored and flag any sections where material has shifted since.

Either way, the output is the same: a 17-row scored table, a total out of 85, and a shape paragraph.

## The 17 sections (scored 0–5 each)

### 1. Positioning
**What's scored:** Clarity of category claim, differentiation, alignment across surfaces (homepage, app store, pitch deck, founder messaging).

**Score guide:**
- 0 = No positioning anywhere
- 2 = Inconsistent across surfaces; team can't articulate it on demand
- 4 = Clear, original, mostly consistent; minor surface gaps
- 5 = Distinctive, category-defining, every surface aligned

**Maps to AARRR:** Cross-cutting — feeds every stage.

### 2. Customer research
**What's scored:** Depth and recency of customer research, ICP clarity, voice-of-customer capture.

**Score guide:**
- 0 = No formal research, only founder intuition
- 2 = Some research but stale or one-off
- 4 = Active research practice, customer language captured
- 5 = Continuous research, customer language flows into copy / product / messaging

**Maps to AARRR:** Cross-cutting — feeds especially Acquisition (channel choice) and Activation (onboarding voice).

### 3. Homepage
**What's scored:** Headline clarity, voice alignment, conversion architecture, mobile experience.

**Score guide:**
- 0 = Generic / broken / off-brand
- 2 = Functional but underperforming; voice mostly absent
- 4 = Clear, voice-aligned, converting; minor optimization opportunities
- 5 = Distinctive, converts strongly, fully voice-aligned

**Maps to AARRR:** Acquisition + Activation.

### 4. Sales / product pages
**What's scored:** Existence and quality of dedicated product / pricing / feature pages. Are SKUs documented? Is pricing scannable? Are upsells visible?

**Score guide:**
- 0 = No dedicated pages
- 2 = Pages exist but are stale or off-voice
- 4 = Quality pages for primary products; gaps on secondary
- 5 = Every product, tier, and upsell has a high-converting page

**Maps to AARRR:** Acquisition + Revenue.

### 5. Conversion pages
**What's scored:** Landing pages for specific campaigns, channels, or use cases. `/partner`, `/science`, `/ambassadors`, `/eye-mask` types of pages.

**Score guide:**
- 0 = No conversion pages
- 2 = One or two exist; rest of needed pages missing
- 4 = Most needed conversion pages exist; quality is good
- 5 = Full conversion page library, each high-converting

**Maps to AARRR:** Acquisition + Activation.

### 6. Competitor comparison
**What's scored:** Existence of "vs. {competitor}" pages, comparison content. Does the brand acknowledge alternatives, or pretend they don't exist?

**Score guide:**
- 0 = Nothing — actively avoiding competitor mentions
- 2 = Some content exists but is weak or hidden
- 4 = Solid comparison pages for top 2–3 competitors
- 5 = Comprehensive comparison library; SEO-targeted; high-converting

**Maps to AARRR:** Acquisition (consideration-stage SEO + sales enablement).

### 7. Resources / content
**What's scored:** Blog, knowledge base, science page, whitepapers, research, founder essays, podcast.

**Score guide:**
- 0 = No content surface
- 2 = Blog exists but is stale or thin
- 4 = Active content production; multiple formats
- 5 = Content is a moat — proprietary research, named pillars, daily volume

**Maps to AARRR:** Acquisition.

### 8. Onboarding
**What's scored:** New user onboarding (in-app + email). Time-to-value, completion rate, brand-voice alignment.

**Score guide:**
- 0 = No onboarding flow
- 2 = Onboarding exists but is broken, off-voice, or underperforming
- 4 = Solid onboarding; clear bottlenecks identified
- 5 = Tested, optimized, on-brand; activation rate at category top quartile

**Maps to AARRR:** Activation.

### 9. Email lifecycle
**What's scored:** Existence and quality of lifecycle email programs. Welcome / onboarding / post-purchase / lapsed / win-back.

**Score guide:**
- 0 = No lifecycle email
- 2 = Some flows exist but drafted not live, or live but stale
- 4 = Core flows live and performing; gaps on secondary flows
- 5 = Full lifecycle live, segmented, performing above category benchmarks

**Maps to AARRR:** Retention (+ Activation for onboarding emails).

### 10. Sales material
**What's scored:** Sales decks, one-pagers, demos, case studies, pricing sheets. (For B2B / hybrid companies — for pure D2C, this can be marked N/A or scored low without implication.)

**Score guide:**
- 0 = No sales material
- 2 = Founder uses a deck but other material is thin
- 4 = Solid sales kit; reps can self-serve content
- 5 = Comprehensive material; updated quarterly; objection-handling library exists

**Maps to AARRR:** Acquisition + Revenue (B2B).

### 11. Messaging
**What's scored:** Voice, tone, vocabulary, message hierarchy across surfaces. Is the brand voice documented, consistent, distinctive?

**Score guide:**
- 0 = No voice documented; surfaces inconsistent
- 2 = Voice exists in founder's head but isn't operationalized
- 4 = Documented voice; mostly consistent across surfaces
- 5 = Distinctive voice; documented; every surface respects it; voice is a moat

**Maps to AARRR:** Cross-cutting.

### 12. Pricing
**What's scored:** Pricing structure clarity, packaging logic, recent pressure-testing, listed vs. effective price reconciliation.

**Score guide:**
- 0 = Pricing not pressure-tested in over a year; unclear structure
- 2 = Listed pricing exists but plan mix / discounting muddles the read
- 4 = Clear pricing; recent tests; LTV math known
- 5 = Pricing tested quarterly; packaging optimized; expansion levers known

**Maps to AARRR:** Revenue.

### 13. CRO (conversion rate optimization)
**What's scored:** Test cadence, instrumentation, A/B history, statistical rigor.

**Score guide:**
- 0 = No tests run; no instrumentation
- 2 = Some ad-hoc tests; no statistical rigor
- 4 = Regular test cadence; some wins
- 5 = Continuous testing program; experimentation culture; documented wins

**Maps to AARRR:** Cross-cutting (most impactful at Activation + Revenue).

### 14. GTM launches
**What's scored:** Quality of past launch executions. Product launches, feature launches, campaign launches.

**Score guide:**
- 0 = No structured launches; "soft launches" only
- 2 = Some launches but uneven execution
- 4 = Solid recent launches; playbook exists
- 5 = Repeatable launch motion; Product Hunt #1s; press coverage on demand

**Maps to AARRR:** Acquisition + Activation.

### 15. Ads (paid)
**What's scored:** Paid acquisition state. Active campaigns, channels, CAC tracking, creative quality.

**Score guide:**
- 0 = No paid acquisition
- 2 = Some paid but unstructured / wasteful
- 4 = Paid is firing across 2–3 channels with positive unit economics
- 5 = Sophisticated paid stack; CAC/LTV understood; creative iterated weekly

**Maps to AARRR:** Acquisition.

**Note:** For pre-seed clients with no paid budget, score this 0 *without* treating it as a weakness — it reflects the funding stage, not a marketing failure.

### 16. SEO
**What's scored:** Organic search performance. Domain rating, ranking keywords, organic traffic, content cluster strategy.

**Score guide:**
- 0 = No SEO; new domain or zero-authority
- 2 = Some content but no strategy; ranks for brand only
- 4 = Established content clusters; growing organic traffic; DR 25+
- 5 = SEO is a moat; DR 40+; thousand+ ranking keywords; consistent content production

**Maps to AARRR:** Acquisition.

### 17. Internationalization
**What's scored:** Geographic expansion, language localization, region-specific pricing.

**Score guide:**
- 0 = US/EN only; no international consideration
- 2 = International users exist but aren't served (one language, one currency)
- 4 = Multi-language, region-specific pricing, GTM playbook for new markets
- 5 = International is a strength; multi-region revenue; localized GTM

**Maps to AARRR:** Acquisition.

**Note:** For most early-stage companies, internationalization scores 0–1 and that's appropriate. Don't penalize early-stage companies for not having international playbooks yet.

## How to compute the total + read the shape

**Total = sum of all 17 scores. Out of 85.**

The total matters less than the *shape*. After the scoring table, write a 2–4 sentence "shape interpretation":

> *"High in {strong sections}, low in {weak sections}. That shape is the gap the rest of the plan closes — Sections X (AARRR stage) is the longest because that's where the gap is widest."*

## Common shapes

### "Strong voice / messaging, weak distribution"
- High: Positioning (#1), Customer research (#2), Messaging (#11)
- Low: SEO (#16), Ads (#15), GTM launches (#14)
- Translation: The founder is a strong storyteller but distribution hasn't caught up. Plan emphasizes Acquisition + paid layer prep.

### "Strong acquisition, weak conversion"
- High: SEO (#16), Resources (#7), Ads (#15)
- Low: Homepage (#3), Onboarding (#8), Conversion pages (#5), Pricing (#12)
- Translation: Traffic comes in but doesn't convert. Plan emphasizes Activation + Revenue.

### "Strong conversion, weak retention"
- High: Onboarding (#8), Homepage (#3), Pricing (#12)
- Low: Email lifecycle (#9), CRO (#13)
- Translation: Users sign up and pay but churn. Plan emphasizes Retention.

### "Strong product, weak everything-else"
- High: only Positioning (#1) and Customer research (#2) — the founder knows the customer
- Low: everything operational
- Translation: Pre-marketing stage. Plan is foundation-heavy. First quarter is bedrock fixes.

### "Strong recent revenue, weak compounding"
- High: Ads (#15), Sales material (#10), Pricing (#12)
- Low: SEO (#16), Resources (#7), Referral mechanics
- Translation: Performance marketing carries the business. Plan emphasizes building compounding channels before paid scales further.

## When scores are subjective

Some sections are easier to score from outside than others. Subjectivity tier:

- **Objective (data-driven):** SEO (#16), Ads (#15), Email lifecycle (#9), Onboarding (#8) — backed by analytics
- **Semi-objective:** Pricing (#12), CRO (#13), Conversion pages (#5), Sales material (#10) — visible artifacts to evaluate
- **Subjective (judgment call):** Positioning (#1), Messaging (#11), Customer research (#2), Resources (#7) — interpretive

For subjective sections, write the rationale into the "Note" column so the team can push back if they disagree.

## When a prior scored audit exists

If the team already has scored output from any current-state assessment, ingest those scores directly — don't redo the work. Treat that prior scoring as the ground truth for sections it covers.

If the prior scoring was done weeks ago and material has shifted since (new shipped flows, new content live, repositioning, etc.), note "scored on YYYY-MM-DD; material has shifted since" and update any specific scores you have current evidence for.


---

# references/example-quietude.md

# Example — Quietude Marketing Plan v1

**This is the canonical reference example for the `/marketing-plan` skill.** It's based on a real fCMO engagement for a hybrid hardware-and-software wellness platform. **Names, domains, and identifying details have been changed** — the client is called "Quietude" here, and the team members have been renamed (Alex / Sam / Casey / Devon). The funnel numbers, budget, and structural lessons preserve the shape of the original engagement so the example retains its teaching value.

Use this as the "what good looks like" reference when drafting a new plan. The structure, tone, depth, and operational specificity are the bar to clear.

**Quietude's archetype:** Hybrid hardware + software with deep-tech / clinical credibility layer. See `references/client-types.md` for archetype patterns.

**Funding-stage context:** Pre-seed-close (mid-raise on $3M seed). Tier 1 per `references/funding-stage-unlocks.md`. $0 paid budget; organic + lifecycle + ambassador only.

**What was strong about this plan:**
- Strategic frame (Section 2) leaned on the founder's own meditation-vs-regulation framing as the content pillar
- Current state (Section 3) included the 17-section audit rubric scored against existing materials (no formal audit run)
- 90-day roadmap (Section 9) had owner-assigned moves, not just actions
- Ops stack (Section 11) included a concrete operational proof-point (Customer.io MCP used live by non-technical founder on the kickoff call)
- Tactical idea bank (Section 12) cross-referenced all 139 marketing-ideas to AARRR + Quietude-specific status, including 23 explicit skips with rationale

---

# Quietude — Marketing Plan v1

**Prepared by:** Casey Reed (fCMO)
**For:** Alex, Sam, and the Quietude team
**Date:** 2026-05-27
**Status:** Draft v1 — for team review

## 1. Executive summary

Quietude has built something rare: a clinically validated, brand-coherent, founder-led product in a category that doesn't yet have a name. The opportunity in the next twelve months is not to invent a marketing engine from scratch — it's to **convert the existing organic gravity into a measurable, repeatable funnel**, then layer paid acquisition on top of that funnel once the seed round closes.

**Three big bets, ranked by leverage:**

1. **Fix the leak before pouring water in.** The Day 1 → Day 35 funnel shape (1.34% → 5.46%) tells us the product converts given time and contact. What it's missing is a working first-session moment (the headphone gate is killing conversion) and a lifecycle layer to deliver the contact. These two pieces — onboarding rebuild and Customer.io flows shipped — are the unlock for everything else.
2. **Compound the moats Quietude already has.** Peer-reviewed clinical study, longevity-influencer PR, 15K live event participants, Alex's founder voice — these are link generators, content pillars, and credibility anchors that most wellness brands would kill for. They're under-leveraged. SEO, content, and App Store optimization translate them into search and discovery surface area.
3. **Build the founder-and-fCMO operating system that lets a 4-person team market like a 20-person one.** This is what makes the plan actually executable at Quietude's team size and burn rate — agentic tooling on top of Customer.io, Shopify, App Store, Stripe, GitHub, and the marketing skill library means we ship without hiring.

**What twelve months looks like, plausibly:**

- App goes from beta to GA. Onboarding converts at meaningful lift over today's baseline.
- 4 SEO content pillars staked, with Pillar 1 (Nervous System Regulation) and Pillar 2 (Sleep + Eye Mask) ranking on Tier-1 keywords.
- Full lifecycle live in Customer.io: onboarding, lapsed re-engagement, hardware post-purchase, subscription-center opt-ins.
- Ambassador program live with 15–25 active hosts. First Quietude Guides cert pilot run.
- Eye mask wedge selling at scale via Shopify with a clean hardware → app activation path. Blended CAC measured and tracked.
- Paid acquisition firing post-seed-close at $5–10K/mo initial test budget, scaling to $20–50K/mo if unit economics validate.
- Series A narrative writes itself: clinical evidence + activation lift + lifecycle compounding + first B2B install reference cases.

**The 90-day priorities** (which the rest of this doc operationalizes):

1. Kill the headphones gate. Ship the bedrock fix this week.
2. Run the three-variant onboarding test. Find the activation winner.
3. Ship Customer.io Flows 6 (eye mask post-purchase) and 4 (lapsed user) — hold Flow 2 (onboarding) until app UI stabilizes.
4. Rewrite the App Store listing in Quietude's brand voice. Highest-leverage non-site asset right now.
5. Stake the SEO foundation: consolidate to `quietude.app`, publish Pillar 1 hub + 3 spokes, publish the peer-reviewed psychophysiology study landing page.
6. Launch the ambassador program with the ~5 inbound waiting.

Everything else compounds on top of those six.

---

## 2. Strategic frame

This section distills positioning, ICP, and brand voice into what the team needs to keep in mind while executing. Full detail lives in `marketing-os.md`, `icp.md`, and `sound-philosophy.md`.

### What Quietude is, in one sentence

A nervous system intelligence platform — clinically validated spatial audio + AI reflection companion (Mira) + hardware + venue installations + practitioner network. *"We start with sound. We expand to every sense. We end with cities."*

### The category we're claiming (and defending)

Quietude doesn't fit the meditation app category, the focus audio category, or the sleep tech category. The brand makes a stronger claim: **bottom-up nervous system regulation through spatial audio**, with clinical evidence as proof and somatic credibility as defense.

The category-defining frame, per Alex (2026-05-19): **Meditation is top-down. Quietude is bottom-up.** Meditation uses the mind to command the body — mental kung fu that fails the very people most likely to need help, because the prefrontal cortex is offline when stressed. Quietude enters through the brainstem, before the thinking mind. The body responds before it has to try. (Full content-pillar treatment in `meditation-vs-regulation.md`.)

This is the single most important strategic message. It belongs in App Store copy, onboarding, lifecycle email, SEO content, ambassador talking points, and the seed deck.

### Who we're for (D2C ICP, distilled)

Overstimulated high-achieving professionals, 25–45, urban (Bay Area, NYC, London, Berlin, Austin). Tech workers, founders, creators, academics, designers, consultants. Often neurodivergent (ADHD, HSP, gifted). Sophisticated wellness buyers — already invested heavily in their inner life.

**Their stated problem:** *"I can't shut my brain off. I've tried meditation apps. They don't work."*

**Their real problem:** Overstimulation, not under-motivation. Their gift (quick thinking) became a curse. They need permission to stop optimizing — including their rest.

**What they're actually buying:** the *feeling* of stability, sensory indulgence, beautiful rituals, effortless effectiveness, a luxurious shortcut to the genius they can't access in chaos.

### The business model logic (per seed deck)

**B2B seeds the market. D2C harvests.** A venue install puts Quietude in front of ~20K people/year at ~$17K cost → 5% convert to subs → ~$430K/year per venue. Six compound channels (referral, Guides, content, home hosting, PR, community) make CAC approach zero by Year 3. Year 5: 75% of new subs come from near-zero-cost channels.

**fCMO scope per kickoff: D2C-led.** Alex owns B2B sales through events/network/founder credibility. The fCMO leverage is on the app/hardware D2C side. This plan reflects that split — B2B is acknowledged as the harvest engine but not treated as primary work surface.

### Brand voice (the non-negotiable)

Per Marketing OS:
- **Tone.** Authoritative yet accessible. Intimate yet professional. Revolutionary yet grounded. Authority comes from lived experience, not explanation.
- **Speak from the body, not the mind.** Every sentence restores somatic safety and orientation. Language opens space rather than closing meaning.
- **YES vocabulary:** Aliveness, inner life, nervous system, spatial sound, resonance, somatic safety, embodied clarity, natural rhythm, orientation, initiation, truth-telling.
- **NO vocabulary:** Zen, chill, vibes, "high-vibe," spiritual bypass, meditation clichés, didactic/explainer language, "let me explain why this works."
- **Core method: Initiatory Reflection.** Writing's purpose isn't to explain or convince — it's to shift the reader's internal state. The result should be *"something in me moved,"* not *"I understand this concept."*
- **CTA rule:** Never pressure. "We do not remind. We invite."

This rule constrains every piece of copy across every AARRR stage. When in doubt: rewrite from the body.

---

## 3. Current state

This is what we're starting from — team, budget, what's already in motion, what's stuck, scored against the CF Marketing Audit 17-section rubric.

### Team composition (marketing surface area)

| Person | Role | Marketing surface area |
|---|---|---|
| **Alex** | Co-founder, CEO | Owns: personal LinkedIn, live events, B2B sales, founder narrative, investor relations, brand voice authorship |
| **Sam** | Co-founder, CXO | Owns: clinical/somatic credibility, brand-voice stewardship, somatic angle on copy review, practitioner network |
| **Devon** | Lead Dev | Owns: product/UI build, instrumentation, Customer.io event wiring, App Store deployment |
| **Ed Dorsey** | Design Advisor | Advisory cadence (ex-Apple/Airbnb/Strava) |
| **Emily Babich** | Creative Strategy | Advisory cadence |
| **Matt Mikkelsen** | Field Recording | Audio library, not marketing |
| **Casey Reed** | fCMO | Strategy, lifecycle, SEO, onboarding tests, content, ambassador program, ops stack |

**No dedicated marketing hire yet.** First hire likely post-seed close (Q3 2026 candidate): a lifecycle + content marketing manager who owns Customer.io, SEO content production, and ambassador operations day-to-day.

### Marketing budget (current)

- **Paid acquisition:** $0. Confirmed by Alex, 2026-05-20: *"D2C UA so far: My personal LinkedIn posts, live Quietude events, organic word of mouth, and organic app store discovery."* No paid layer.
- **Tooling stack:** Customer.io subscription, Shopify (eye mask storefront), App Store Connect, GA4 (or pending), Stripe, Notion, Dub.co (ambassador attribution). Estimate ~$500–1,500/mo combined.
- **fCMO retainer:** Casey Reed engagement.
- **PR:** No paid PR. Organic longevity-influencer tailwind, consumer-tech angels + foundation-model lab network.

**Implication:** The 90-day plan must produce gains without any paid lever pulled. Everything in the next 12 weeks is organic, lifecycle, or product-level. Paid is a Q2–Q3 unlock.

### What's already done (acknowledge, then build on)

| Asset | Status | Marketing leverage |
|---|---|---|
| Peer-reviewed peer-reviewed psychophysiology study (2025) | Published | Anchor of clinical authority. Most undermarketed asset Quietude owns. |
| longevity-influencer eye-mask endorsement | Live, generating Shopify sales | Press hook. Underused for landing-page social proof. |
| consumer-tech angels + foundation-model lab investment | Closed | Investor PR opportunity. "Why I invested" Substack/Medium pieces. |
| 15K+ live event participants over a decade | Real | Email list potential, ambassador pool, testimonial bank, B2B reference. |
| Quietude eye mask (5K in stock) | Selling | The wedge product. Hardware → app activation path. |
| 38% 12-month retention (vs. category avg 20%) | Real | Headline metric. Belongs everywhere. |
| Customer.io + Shopify integration | Wired | The lifecycle infrastructure exists. Flows just need to ship. |
| 4 GitHub repos for context + product | Set up | `quietude-context` (shared brain), `quietude-promo`, `quietude-app` (app), `mira` (AI), `quietude-api` |
| Alex's Sound Philosophy doc | Working doc | Linkable position paper once polished and published. |
| ~5 inbound ambassadors waiting | Inbound | Referral program ready to launch — no demand-gen needed for v1. |
| Aurora B2B install (~€250K, July deadline) | In-flight | First flagship venue. Reference case once installed. |
| Notion Knowledge Directory | Live | Internal context. |
| Customer.io MCP (Claude integration) | Validated on kickoff | Non-technical team can ship flows independently. |

### What's in-flight (drafted but not shipped)

| Item | Status | Blocker |
|---|---|---|
| Flow 2 — App Onboarding (8 emails / 14 days) | Draft | App UI in flux; copy references screens that may change |
| Flow 4 — Lapsed User Re-engagement (5 emails / 38 days) | Draft | None — ship-ready |
| Flow 6 — Eye Mask Post-Purchase | Draft | None — ship-ready |
| Onboarding rebuild (3-variant test plan) | Strategy doc done | Eng scoping + headphone-gate removal |
| SEO 90-day plan + keyword research | Done | Awaiting domain consolidation decision + content production start |

### What's stuck (and needs to unstick this quarter)

| Issue | Cost of inaction | Action |
|---|---|---|
| Headphones hard-gate in onboarding | Confirmed conversion drop post-launch | Kill this week (bedrock fix) |
| 4 domains unconsolidated (quietude.app, quietude.space, quietude.audio, quietude.center) | SEO authority fragmenting, transactional email confusion | Consolidate to `quietude.app` per SEO data |
| App Store listing copy not in brand voice | Highest-traffic Quietude surface; off-brand experience for arriving users | Rewrite in voice (Pillar 1) |
| Domain consolidation requires 301 plan + email sender migration | Risk of traffic loss if mishandled | Plan in weeks 1–2, execute weeks 3–4 |
| `quietude-promo` repo hasn't shipped since March 2026 | Marketing site is stale | Confirm whether it's live; rewrite or replace |
| 29% monthly App Store churn vs. 38% 12-month retention claim | Metric definition mismatch confusing the team | Reconcile with Devon + Customer.io data |
| Mira post-session reflection scope unknown | Blocks Variant B and Variant C onboarding tests | Resolve with Devon |

### Audit rubric snapshot (17-section)

Scored 0–5 from materials, using the embedded rubric in `references/current-state-rubric.md`. Marked "scored from materials" rather than "formal audit" — Alex can push back on any score where they have better data.

| # | Section | Score | Note |
|---|---|---|---|
| 1 | Positioning | **4** | Clear, original category claim. The bottom-up frame is the strongest piece. Needs broader external articulation. |
| 2 | Customer research | **4** | Deep founder-led research, decade of live participants. Could be more systematically captured. |
| 3 | Homepage | **2** | `quietude-promo` hasn't shipped since March. Off-brand voice in places. |
| 4 | Sales / product pages | **2** | Eye mask page exists on Shopify but isn't optimized for SEO or sales narrative. No app-product landing page in brand voice. |
| 5 | Conversion pages | **2** | `/partner` exists on `quietude.app`. No `/science`, `/eye-mask`, `/ambassadors`, `/guides` pages live. |
| 6 | Competitor comparison | **1** | Nothing exists. Big SEO + sales opportunity (own "Quietude vs. Calm/Headspace/Brain.fm/Endel" SERPs). |
| 7 | Resources / content | **1** | Sound Philosophy not yet public. peer-reviewed psychophysiology study not yet on a dedicated page. No blog. |
| 8 | Onboarding | **2** | Headphones gate killing conversion. Hold-and-fix project this quarter. |
| 9 | Email lifecycle | **1** | All three flows drafted, none live. Ship-order set. |
| 10 | Sales material | **3** | Seed deck is strong (investor-facing). B2B sales material more founder-led than asset-led. |
| 11 | Messaging | **5** | Alex + Sam have authored the most distinctive brand voice in the wellness category. This is a moat. |
| 12 | Pricing | **3** | $30/mo app, $45 eye mask, $7,500 speakers, $50–200K B2B. Hasn't been pressure-tested for D2C conversion lift. |
| 13 | CRO | **2** | App Store conversion rate trackable but no A/B history. Headphones gate is the obvious first test removal. |
| 14 | GTM / launches | **2** | App in throttled beta. Major launches (eye mask, Mira public) haven't had structured GTM. |
| 15 | Ads | **0** | No paid layer. Reflects the current organic strategy — not a weakness, but the budget unlock means this will move. |
| 16 | SEO | **1** | Current state: 7 organic visits/mo. Plan exists; execution not yet started. |
| 17 | Internationalization | **1** | Finland HQ + global ICP, but EN-only and US-centric copy. Defer until Q4+. |

**Total: 36 / 85 (42%).** The shape matters more than the score: high in Positioning + Messaging + Customer research, low in Conversion pages + Email lifecycle + SEO + Resources + Ads. That's the gap this plan closes.

---

## 4. Acquisition

> *"How do strangers become aware of Quietude?"*

### Current state

100% organic. Four real channels: Alex's personal LinkedIn, live Quietude events, organic word of mouth, organic App Store discovery. Plus passive PR drag from longevity-influencer endorsement + clinical study.

This is good news, not bad. Every dollar of revenue earned to date has been earned without paid acquisition. The bar to exceed it isn't high; the upside on top of an organic base is significant.

### The plan

**Channel 1 — SEO (primary 90-day investment).**
The full 90-day plan lives in `seo/plan.md`. Summary: consolidate to `quietude.app`, target three asymmetric clusters (nervous-system regulation KD 14–32, weighted/blackout sleep mask KD 6–30, WELL + social-wellness-club B2B KD 5–34), publish 4 content pillars. 90-day target: 500–1,500 organic visits/mo, 80+ ranking keywords. 12-month target: 10,000/mo, 1,000+ keywords.

**Channel 2 — App Store optimization (highest-leverage non-site asset).**
The App Store listing is currently the most-visited Quietude URL by Apple's algorithm. Fixing the copy is higher-leverage this quarter than fixing the marketing site. Rewrite in brand voice. Add the meditation-vs-regulation framing. Lead with the clinical anchor. Test screenshot variations.

**Channel 3 — Alex's LinkedIn (productize the channel).**
Today it's ad-hoc founder posting. The next move is structured: a 2–3x/week cadence, post categories that map to the content pillars (nervous system, sound science, founder journey, clinical evidence, behind-the-scenes), trackable links via Dub, follower → email subscriber → app install funnel measured. This is Alex's voice — the channel only works if he's the one writing. fCMO + Typefully scheduling makes the cadence sustainable.

**Channel 4 — PR amplification.**
longevity-influencer tailwind is real but underused on owned surfaces. Add a `/notable-users` or `/in-the-press` page. Pitch the peer-reviewed psychophysiology study to 5 outlets (wellness press: Well+Good, MindBodyGreen; tech-adjacent: Wired with the longevity-influencer hook; mainstream: Outside, Forbes Wellness). HARO/Help-A-B2B-Writer responses citing Quietude's data. Investor PR moments ("Why I invested in Quietude" Substack pieces from consumer-tech angels — push for these with backlinks).

**Channel 5 — Event-to-app instrumentation.**
Live events are the highest-converting ICP exposure Quietude has (15K+ participants, decade of trust). They're un-instrumented. Add: per-event QR code → app install + email capture, post-event lifecycle (Customer.io Flow 7?), event ROI tracking. Goal: turn an event from a one-night conversion moment into a 30-day funnel.

**Channel 6 — Eye mask wedge (consumer entry product).**
5K masks in stock. Shopify storefront exists but isn't optimized. Improvements: SEO-optimize the product page (target "weighted sleep mask," "blackout sleep mask," "silk sleep mask"), add reviews via Judge.me (per kickoff decision), 30-day return policy (US-market expectation, per kickoff), build the listicle ("Quietude vs. Manta vs. Nodpod vs. Lumon"). Consider Amazon listing as a v2 distribution play.

**Channel 7 — B2B venue installs (kept lean per kickoff).**
Alex owns this. Marketing supports with: case studies after each install, `/partner` page rewrite in voice (already exists on quietude.app), Pillar 4 content ("The Missing Sound Feature in WELL"), reciprocal links from partner venues baked into contracts.

**Channel 8 — Paid layer (unlocked post-seed close).**
Held until seed funding lands. Initial test budget: $5–10K/mo split across Apple Search Ads (highest-intent for App Store), Meta (Instagram + Facebook for eye mask), LinkedIn (B2B venue buyers). Don't fire until: (a) onboarding bedrock fix is shipped, (b) Flow 6 is live, (c) at least one Pillar landing page is in voice. Paid amplifies what already works — premature paid amplifies what's broken.

### 90-day acquisition moves

- Weeks 1–2: Domain consolidation decision + 301 plan. App Store listing rewrite first pass.
- Weeks 3–4: Domain 301s executed. GSC migration. SEO Pillar 1 hub drafted.
- Weeks 5–8: Pillar 1 hub + 3 spokes published. Pillar 2 (Eye Mask) hub + listicle published. Alex's LinkedIn cadence operationalized via Typefully. peer-reviewed psychophysiology study lands on dedicated `/science` page.
- Weeks 9–12: Pillar 4 (WELL/B2B) cornerstone published. Sound Philosophy goes public at `/research/sound-philosophy`. First PR push: pitch study + longevity-influencer hook to 5 outlets.

### 12-month acquisition outlook

- Q1 (Months 1–3): Foundation. SEO pillars staked. App Store rewrite shipped. LinkedIn cadence stable. PR push launched.
- Q2 (Months 4–6, post-seed close): Paid acquisition pilot at $5–10K/mo. SEO compounding — Pillar 1 ranking. First B2B install reference case live.
- Q3 (Months 7–9): Paid scales to $20–30K/mo if unit economics hold. All four pillars producing. App GA — new GTM moment.
- Q4 (Months 10–12): Compound channels live. 50+ pieces of pillar content. First Quietude Guides program pilot creating local SEO + earned media.

### Skills + tools

- **Skills:** `seo-audit`, `ai-seo`, `programmatic-seo`, `schema`, `content-strategy`, `competitors`, `launch`, `ads`, `ad-creative`, `social`, `typefully`, `analytics`, `copywriting`, `marketing-website-design`, `free-tools`
- **MCPs / APIs:** Ahrefs API, DataForSEO API, Typefully MCP (LinkedIn scheduling), GA4 MCP (when wired), GitHub MCP (`quietude-promo` repo work), Notion (knowledge directory), Stripe MCP (LTV / paid-CAC math), `agent-browser` (LinkedIn drafting + testing), `defuddle` (research)

---

## 5. Activation

> *"Once someone tries Quietude, do they have an experience that converts?"*

### Current state

Day 1 → paid: **1.34%**. Day 7 → paid: **3.73%**. Day 35 → paid: **5.46%**. *The funnel shape is the signal.* The ~4× lift over 35 days means the product converts given time and contact — both of which the current onboarding undermines and the lifecycle layer doesn't yet provide.

Caveats: app is in throttled beta. Metrics are noisy. Don't optimize against absolutes; optimize against funnel *shape* and *cohort comparison*.

### The plan

**Move 1 — Kill the headphones hard-gate (bedrock fix, this week).**
Confirmed conversion drop after the gate shipped. The fix isn't better copy on the gate — it's removing the gate. Replace with passive headphone detection + soft single-line nudge. No regret change. Full reasoning in `onboarding-recommendation.md`.

**Move 2 — Run the three-variant onboarding test.**
Three variants, each a pure expression of one belief about what drives activation in this ICP:
- **Variant 1 — Trust First.** Bold promise + clinical anchor + testimonial wall + 1-line mechanism. Tests whether the saturated ICP needs framing before they'll invest.
- **Variant 2 — Seen First.** Multi-step diagnostic → AI-generated "we see you" summary → personalized session. Tests whether being accurately named is the conversion event.
- **Variant 3 — Felt First.** Audio starts on app open. ~15 words on screen. The session IS the onboarding. Tests whether the product can carry it cold.

Test sequence (sequential, ~7 weeks to a winner): bedrock baseline → V3 vs. baseline → winner vs. V1 → winner vs. V2. Full system in `onboarding-recommendation.md`.

**Move 3 — App Store listing rewrite.**
Highest-leverage non-site asset. Rewrite in brand voice. Lead with meditation-vs-regulation. Screenshot variations to test. This is also an Acquisition move (organic discovery) but it lives here because it's the threshold to the trial.

**Move 4 — Customer.io Flow 2 (held until UI stable).**
The 8-email / 14-day onboarding sequence is drafted and on-brand. Holding the ship because the emails reference in-app screens that will change during the onboarding rebuild. Once a winning onboarding variant ships, Flow 2 gets a copy refresh against the final UI and goes live.

**Move 5 — Paywall + pricing review (cross-cuts to Revenue).**
What's the current trial structure? Length, paywall trigger, intro pricing? When the funnel shape is "lift over 35 days," extending trial may convert better than aggressively gating earlier. To be audited in Q1.

### 90-day activation moves

- Week 1: Headphones gate removed. Baseline established.
- Weeks 2–3: Variant 3 (Felt First) prototyped, instrumented, shipped to a test cohort.
- Weeks 4–5: Read Variant 3 vs. baseline. Decide ship/iterate. Begin Variant 1 build.
- Weeks 6–7: Variant 1 (Trust First) live.
- Weeks 8–9: Read V1 vs. winner. Begin Variant 2 build.
- Weeks 10–11: Variant 2 (Seen First) live.
- Week 12: Final read. Winning variant scheduled for permanent ship. Flow 2 unblocked.

### 12-month activation outlook

- Q1: Winning variant identified and shipped.
- Q2: Flow 2 ships. Paywall A/B tests start.
- Q3: GA launch — onboarding re-validated at higher traffic. Cohort segmentation by acquisition source (Shopify/eye-mask vs. direct vs. ambassador vs. paid) starts to drive variant forks.
- Q4: Onboarding is no longer the bottleneck. Focus moves to Activation → Retention transition (sessions 2–7).

### Skills + tools

- **Skills:** `onboarding`, `signup`, `cro`, `cro`, `paywalls`, `popups`, `copywriting`, `copy-editing`, `copycraft`, `marketing-website-design`, `ab-testing`, `marketing-psychology`
- **MCPs / APIs:** App Store Connect (manual + `dev-browser` for screenshot automation), GitHub MCP (`quietude-app` app repo for onboarding code), Figma / Pencil MCP (for onboarding screen design), Customer.io MCP (for any in-app/email coordination), GA4 MCP (activation events)

---

## 6. Retention

> *"Once someone converts, do they stay — and deepen?"*

### Current state

**Headline metric (per seed deck): 38% 12-month retention** — nearly double the category average (~20%). This is the strongest single retention signal in the deck and one of the most undermarketed claims Quietude owns.

**App Store snapshot, 2026-05-16:** 145 paid, 42 churned (~29% monthly churn). Definition mismatch with the 38% claim — to reconcile. Possibly: 38% is annual cohort retention (people who paid month 1 and still pay month 12), 29% is gross monthly churn (people who paid this month who didn't pay next month). Both can be true. Need to clarify which metric is reported externally and which is the actual product health signal.

### The plan

**Move 1 — Ship Flow 6 first (Eye Mask Post-Purchase).**
Per kickoff decision and the onboarding-recommendation doc: this is the ship-ready flow. Hardware-anchored, doesn't reference in-app screens, can ship today. Wires the hardware → app activation path (eye mask buyers should get a free 6-month Premium trial — formalize this as part of the flow).

**Move 2 — Ship Flow 4 second (Lapsed User Re-engagement).**
Five emails over 38 days. Language is universal — doesn't depend on app UI state. Ship after Flow 6 is live.

**Move 3 — Hold Flow 2 (Onboarding).**
Eight emails over 14 days. Holds until app UI stabilizes post-onboarding-rebuild. Don't ship copy that will need rewriting in 8 weeks.

**Move 4 — Customer.io subscription center with opt-in topics.**
Per kickoff decision. Topics: events, app updates, somatics & nervous system, eye mask promotions. Users self-segment. Improves deliverability (lower complaint rates) and gives lifecycle a richer segmentation surface.

**Move 5 — Mira post-session reflection (when scoped).**
Most powerful retention move medium-term. After a session, Mira asks *"What did you notice?"* Optional preset chips + free text. Two payoffs: (a) gives Mira priors for personalization on session 2+, (b) reflection responses become a content + segmentation goldmine for the team. Scope question for Devon — does Mira currently support this, or is it new build?

**Move 6 — Hardware → app activation flow.**
The eye-mask-buyer-becomes-Premium-subscriber path is hinted in the seed deck (blended CAC via hardware) but isn't visible in the App Store dashboard. Audit the existing flow: does an eye mask Shopify purchase actually deliver a free Premium code? How is it redeemed? What's the conversion rate? This is foundational to the "B2C wedge" thesis.

**Move 7 — Reconcile the retention metric.**
What's the actual definition of "38% 12-month retention"? Cohort? Plan type (monthly vs. annual)? Survives this even if the answer is uncomfortable — the team and investors need to be talking about the same metric.

**Move 8 — Annual plan as default (cross-cuts to Revenue).**
Industry pattern: defaulting to annual reduces churn anxiety and improves LTV. To test in Q2.

### 90-day retention moves

- Weeks 1–2: Flow 6 (eye mask post-purchase) ships. Address fixes from kickoff review (study link line break, CAN-SPAM footer, founder face-bubble signature, Judge.me reviews).
- Weeks 3–4: Flow 4 (lapsed user re-engagement) ships.
- Weeks 5–6: Customer.io subscription center built and live.
- Weeks 7–8: Hardware → app activation flow audited and documented. Fix any leaks.
- Weeks 9–10: Retention metric reconciliation (with Devon).
- Weeks 11–12: Win-back campaign for churned cohort — test re-activation copy.

### 12-month retention outlook

- Q1: Flows 6 + 4 firing. Subscription center live.
- Q2: Flow 2 ships (post-onboarding-rebuild). Mira post-session reflection in production. Annual plan default tested.
- Q3: GA launch — retention metrics re-baselined at higher volume. Cohort-based lifecycle flows (eye mask vs. direct app install).
- Q4: Full lifecycle compound. Retention is no longer a top-three concern — focus moves to Referral and Revenue.

### Skills + tools

- **Skills:** `emails`, `churn-prevention`, `copywriting`, `copy-editing`, `paywalls`, `ab-testing`
- **MCPs / APIs:** **Customer.io MCP** (validated on kickoff — non-technical team can ship flows), Shopify (eye mask buyers as event source), Stripe MCP (subscription state, churn cohort pulls), GA4 MCP (session events, retention curves)

---

## 7. Referral

> *"Do retained users bring more users — and at what cost?"*

### Current state

~5 inbound ambassadors waiting (per kickoff). Dub.co set up. No formal program yet. WOM happens naturally per Alex's UA breakdown.

This is one of the strongest leading indicators in the business: 5 unaffiliated people have raised their hand asking to bring Quietude to their network *before any program exists*. That signal doesn't show up in apps with weaker product-market fit.

### The plan

**Move 1 — Launch the ambassador program with the 5 inbound.**
Tier 1 of the program. Per-ambassador landing pages (e.g., `quietude.app/with/sarah`). Dub.co tracks attribution. Commission structure to determine (per kickoff, $/sub or rev-share TBD). Soft-launch with the 5 — treat as pilot cohort, gather feedback, refine before opening applications.

**Move 2 — Build the share-after-shift moment.**
The Mira post-session reflection (see Retention) is the natural moment to surface a share prompt. After a user reports a felt shift, offer: *"Want to share Quietude with someone who needs this?"* Single-line, never pushy. Most powerful WOM mechanism: gift-a-month flow where the recipient gets a discounted or free intro.

**Move 3 — Founder amplification (Alex + Sam as ambassador-zero).**
Alex mentioning the fCMO engagement in fundraise pitches (permission granted). Reciprocal mentions in fCMO-side content. Sam's clinical network → practitioner ambassador pool.

**Move 4 — Quietude Guides cert pilot (long-term, Q3+).**
The Guides program is the Phase-2 referral compound (per seed deck). 500–1,000 Guides across 50+ cities by Y3–5. First cert pilot: 3–5 hosts who run live sessions, get a rev-share + co-marketing. Builds local SEO + earned media + ambassador-of-ambassadors flywheel. Hold until paid + lifecycle are firing — Guides is a multi-quarter build.

**Move 5 — Eye mask gifting flow.**
Hardware referral is rare and powerful. *"Send a friend an Quietude eye mask. They get the mask + a free 3-month Premium. You get a credit toward your next thing."* Holiday/gifting peak windows are the test.

### 90-day referral moves

- Weeks 1–4: Ambassador program scoped, commission structure decided, per-ambassador landing page template built, 5 inbound onboarded.
- Weeks 5–8: First ambassador-driven sales tracked via Dub. Attribution and payout flow validated.
- Weeks 9–12: Open applications for next 10–15 ambassadors. Begin Quietude Guides scoping.

### 12-month referral outlook

- Q1: Ambassador program live with 5–10 active.
- Q2: 15–25 active ambassadors. Share-after-shift moment in production (post-Mira reflection).
- Q3: Guides cert pilot launched (3–5 hosts). Eye mask gifting flow live for holiday peak.
- Q4: 50+ ambassadors + 5–10 Guides. Referral driving 15–25% of new D2C subs.

### Skills + tools

- **Skills:** `referrals`, `social`, `copywriting`, `marketing-website-design` (per-ambassador landing pages)
- **MCPs / APIs:** Dub.co (attribution — already in stack), Stripe MCP (commission accounting + payouts), GitHub MCP (landing page deployment in `quietude-promo` or new `quietude-ambassadors` repo), Customer.io MCP (ambassador lifecycle: onboarding, monthly performance digest, payout notification)

---

## 8. Revenue

> *"What do we charge, who pays, and how does that compound?"*

### Current state

| Product | Price | Volume signal |
|---|---|---|
| Quietude App + Mira | ~$30/mo | 145 paid subs (App Store snapshot 2026-05-16) |
| Quietude Eye Mask | ~$45 | 5K in stock, longevity-influencer PR-driven sales |
| Quietude Audio (speakers) | ~$7,500 | Niche, founder-led |
| Quietude Spaces (B2B install) | $50–200K | Aurora flagship in-flight (~€250K), pipeline of 4 venues |
| Quietude Experiences (events) | Varies | 15K+ historical participants |
| Quietude Guides | Rev share | Not yet operational |

**Revenue to date: ~$500K on ~$250K raised.** Capital-efficient. Hardware + B2B + app subs all contributing.

**MRR (App Store snapshot): $592.** Beta-throttled, not steady-state. The implied ~$4/sub/mo against $30/mo list suggests heavy annual plan adoption (which compresses monthly revenue but improves LTV) or significant promotional pricing — to reconcile with Alex.

### The plan

**Move 1 — Pricing audit.**
What's actually being charged today? List price, common plan mix, intro pricing, churn-recovery offers? The $4/sub/mo implied math doesn't tell a clean story — need ground truth before recommending changes.

**Move 2 — Annual plan as default (test).**
Industry pattern, cross-references to Retention. Test in Q2.

**Move 3 — Hardware → app bundling formalized.**
Per partner-event-business framing in the seed deck: blended CAC via hardware → app subscription is the play. Today an eye mask buyer gets... what, exactly? Free Premium? Trial code? Audit + formalize. The eye mask is the wedge; the app is the LTV.

**Move 4 — Eye mask Shopify storefront optimization.**
The current page underperforms what it could. Add: SEO targeting ("weighted sleep mask," "blackout sleep mask"), Judge.me reviews (kickoff decision), 30-day return policy (kickoff decision), upsell flow into Premium app.

**Move 5 — Consider Amazon listing for eye mask.**
Amazon takes margin but is its own discovery engine. Test as v2 distribution if Shopify volume validates.

**Move 6 — B2B install case studies + sales material.**
Alex owns B2B sales but marketing supports with: post-install case studies (Aurora as the flagship), `/partner` page rewrite in voice, Pillar 4 SEO content. Each B2B install is a ~$430K/year recurring + reference-case multiplier.

**Move 7 — Data licensing (long-term, flag for ops stack).**
Per seed deck Y10–15 value pool: $100–160M/yr. Not immediate revenue. Belongs in the 24-month strategic agenda. Flag here so we don't lose sight.

### 90-day revenue moves

- Weeks 1–2: Pricing audit. Reconcile implied vs. listed MRR.
- Weeks 3–4: Hardware → app activation flow audited (also Retention move 6).
- Weeks 5–8: Eye mask Shopify page rewrite + SEO optimization + Judge.me + return policy. Aurora case study scaffolded for post-install.
- Weeks 9–12: Annual plan default test scoped.

### 12-month revenue outlook

- Q1: Pricing audit closes. Hardware → app activation formalized.
- Q2: Annual plan default test live. Eye mask Shopify producing measurable lift.
- Q3: B2B install case studies (1–2) published. GA launch + new pricing tier consideration (e.g., a higher-tier Mira-heavy plan?).
- Q4: Pricing optimized via test results. Hardware → app blended CAC tracked and reported. First numbers on the data-licensing thesis (still very early).

### Skills + tools

- **Skills:** `pricing`, `paywalls`, `sales-enablement`, `revops`, `ab-testing`, `copywriting`
- **MCPs / APIs:** Stripe MCP (pricing tests, subscription analytics, churn cohort, blended CAC math), Customer.io MCP (paywall-related lifecycle), Shopify (eye mask transactions), GA4 MCP (revenue events), Notion (commercial knowledge directory)

---

## 9. 90-day roadmap

Tactical execution layer. Each item is AARRR-tagged so priority is visible.

### Weeks 1–2 — Unblock

| Move | Stage | Owner |
|---|---|---|
| Kill the headphones hard-gate | Activation | Casey + Devon |
| Domain consolidation decision documented | Acquisition | Casey + Alex |
| 301 plan drafted (page-by-page) | Acquisition | Casey |
| App Store listing rewrite — first pass | Activation + Acquisition | Casey + Alex + Sam (voice review) |
| Flow 6 (eye mask post-purchase) ships | Retention | Casey + Customer.io MCP |
| Ambassador program scoping doc | Referral | Casey |
| Pricing audit kicked off | Revenue | Casey + Alex |

### Weeks 3–4 — Foundation

| Move | Stage | Owner |
|---|---|---|
| Domain consolidation 301s executed | Acquisition | Devon + Casey |
| GSC + GA4 stood up on `quietude.app` | Acquisition | Casey |
| SEO Pillar 1 hub drafted (Nervous System Regulation) | Acquisition | Casey |
| `/science` hub built with peer-reviewed psychophysiology study | Acquisition + brand | Casey + Sam |
| Variant 3 (Felt First) onboarding prototyped + tested | Activation | Casey + Devon |
| Flow 4 (lapsed user) ships | Retention | Casey |
| Ambassador program: 5 inbound onboarded | Referral | Casey |
| Hardware → app activation flow audited | Retention + Revenue | Casey + Devon |
| App Store listing rewrite — final + ship | Activation + Acquisition | Alex + Sam + Casey |

### Weeks 5–8 — Velocity

| Move | Stage | Owner |
|---|---|---|
| Pillar 1 hub + 3 spokes published | Acquisition | Casey |
| Pillar 2 hub (Eye Mask) + listicle published | Acquisition | Casey |
| Alex's LinkedIn cadence operationalized (Typefully) | Acquisition | Alex + Casey |
| First PR push: study + longevity-influencer hook to 5 outlets | Acquisition | Casey + Alex |
| Variant 3 read; ship or iterate | Activation | Casey |
| Variant 1 (Trust First) prototyped + tested | Activation | Casey + Devon |
| Customer.io subscription center built | Retention | Casey |
| Eye mask Shopify storefront rewrite (SEO + reviews + return) | Acquisition + Revenue | Casey + Alex |
| First ambassador attribution verified via Dub | Referral | Casey |

### Weeks 9–12 — Compound

| Move | Stage | Owner |
|---|---|---|
| Pillar 4 (WELL/B2B) cornerstone published | Acquisition | Casey |
| 3 more Pillar 1 spokes published | Acquisition | Casey |
| Sound Philosophy published at `/research/sound-philosophy` | Acquisition + brand | Alex + Casey |
| Variant 1 read; begin Variant 2 (Seen First) build (Mira-dependent) | Activation | Casey + Devon |
| Win-back campaign for churned cohort | Retention | Casey |
| Annual plan default test scoped | Revenue | Casey + Alex |
| Open ambassador applications for next 10–15 | Referral | Casey |
| 90-day review + Q2 plan recalibration | Cross-cutting | Casey + Alex |

---

## 10. 12-month outlook

Quarterly milestones with funding-stage capability unlocks named explicitly.

### Q1 — Months 1–3 (Jun–Aug 2026)

**Funding state:** Pre-seed-close. Paid budget = $0. fCMO + founder-led + tool costs only.

**Focus:** Foundation. Plug the leaks. Stake the SEO ground. Get lifecycle firing.

**Outcomes by end of Q1:**
- Headphones gate gone; onboarding winner identified
- All four SEO pillars seeded (hub + first spokes)
- Lifecycle Flows 4 + 6 live
- App Store listing in brand voice
- 5 ambassadors active
- Pricing audit closed
- Domain consolidated

**KPI targets:** Onboarding Day 1 → paid lift of 25–50%. Organic traffic 500–1,500/mo. App Store conversion rate +20%.

### Q2 — Months 4–6 (Sep–Nov 2026)

**Funding state:** Seed close (~Q3 2026 target). First paid budget unlock: $5–10K/mo test.

**Focus:** Validate paid. Scale winning onboarding. Add Flow 2.

**Outcomes by end of Q2:**
- Paid acquisition firing on Apple Search Ads + Meta
- Onboarding winner permanently shipped
- Flow 2 (onboarding emails) shipped
- Mira post-session reflection in production
- 15–25 ambassadors active
- First B2B install reference case (Aurora) published
- Annual plan default tested

**KPI targets:** Paid CAC < $50 blended. Organic traffic 1,500–3,500/mo. Retention curves visibly improving.

### Q3 — Months 7–9 (Dec 2026–Feb 2027)

**Funding state:** Seed deployment. Paid scales to $20–50K/mo if unit economics hold. First marketing hire (lifecycle + content manager).

**Focus:** Scale + diversify. App GA. B2B reference cases compound.

**Outcomes by end of Q3:**
- App GA launched with new GTM moment (PR + ad creative refresh + Pillar 3 spatial-audio-science content cycle)
- First Quietude Guides cert pilot (3–5 hosts)
- All four pillars producing weekly content
- Eye mask gifting flow live for holiday peak
- New marketing hire onboarded

**KPI targets:** Paid + organic blended CAC stabilizing. App GA conversion +50% from beta baseline. Guides pilot validates rev-share + co-marketing model.

### Q4 — Months 10–12 (Mar–May 2027)

**Funding state:** Pre–Series A. Paid scaling continues. Series A pitch in motion.

**Focus:** Compound. Position for Series A.

**Outcomes by end of Q4:**
- Compound channels (organic + ambassador + Guides + lifecycle) producing 50%+ of new subs
- 50+ ambassadors, 5–10 Guides
- 4 SEO pillars + 30+ pieces of content live
- Paid scaling to $50–150K/mo if validated
- Series A narrative: clinical evidence + activation lift + lifecycle compounding + B2B reference case pipeline

**KPI targets:** D2C ARR run-rate trajectory clear. Blended LTV/CAC > 3. Founder narrative + data + reference cases ready for Series A.

---

## 11. Marketing operations stack

This is what makes the plan executable at Quietude's team size. A 4-person founder team + fCMO + agentic tooling can ship the output of a 15–20-person traditional marketing org — because the marketing skill library and MCP integrations do the orchestration.

### The thesis

Every move in the AARRR breakdown above maps to (a) one or more marketing skills that operationalize the work, and (b) one or more MCP/API integrations that let it execute without a dedicated headcount per channel.

The fCMO's job is to:
1. Define the strategy and sequencing (this doc)
2. Run the skills against the right context at the right time
3. Maintain the shared context (`quietude-context`) and tooling so Alex + Sam + future hires can plug in
4. Hand off operational work to humans (or future hires) only where the cost of agentic execution > human execution

### Skills mapped to AARRR stages

| Stage | Primary skills | Supporting skills |
|---|---|---|
| **Acquisition** | `seo-audit`, `ai-seo`, `programmatic-seo`, `schema`, `content-strategy`, `competitors`, `ads`, `ad-creative`, `social`, `typefully` | `launch`, `free-tools`, `analytics`, `cold-email`, `copywriting`, `marketing-website-design` |
| **Activation** | `onboarding`, `signup`, `paywalls`, `cro`, `copywriting`, `copy-editing`, `copycraft` | `marketing-website-design`, `ab-testing`, `marketing-psychology`, `cro`, `popups` |
| **Retention** | `emails`, `churn-prevention` | `copywriting`, `copy-editing`, `ab-testing`, `paywalls` |
| **Referral** | `referrals`, `social` | `copywriting`, `marketing-website-design`, `emails` |
| **Revenue** | `pricing`, `paywalls`, `sales-enablement`, `revops` | `ab-testing`, `copywriting` |
| **Cross-cutting** (brand, intelligence) | `product-marketing`, `customer-research`, `marketing-psychology` | `marketing-ideas`, `diagram-maker` |

### MCPs / APIs mapped to stages

| Stage | Existing connections at Quietude | Tooling layer (Casey's fCMO stack) |
|---|---|---|
| **Acquisition** | App Store Connect (manual), Shopify, GA4 (in progress), Notion | Ahrefs API, DataForSEO API, Typefully MCP, GitHub MCP (`quietude-promo`), `agent-browser`, `defuddle` |
| **Activation** | App Store Connect, Customer.io, Shopify | App Store Connect (via `dev-browser` for screenshot automation), Figma / Pencil MCP, GitHub MCP (`quietude-app` app repo), Stripe MCP |
| **Retention** | **Customer.io (with Claude MCP — validated on kickoff)**, Stripe, Shopify | Customer.io MCP, Stripe MCP, GA4 MCP |
| **Referral** | Dub.co, Stripe | Dub.co, Stripe MCP, GitHub MCP (per-ambassador landing pages), Customer.io MCP |
| **Revenue** | Stripe, Shopify, Customer.io | Stripe MCP, Shopify, GA4 MCP, Notion |
| **Cross-cutting** | Notion, GitHub (`quietude-context`) | Notion, GitHub MCP, `defuddle`, `obsidian-cli` (for Casey's working notes) |

### The Customer.io MCP unlock (concrete example)

Per kickoff call: *"Built live on call — abandoned-cart flow drafted using Customer.io's Claude MCP. Validated that non-technical team can use the skill pattern independently."*

This is the operational proof that the stack works. Alex, who is not a developer, drafted a working lifecycle flow with Claude + Customer.io MCP in real time on a kickoff call. The same pattern applies to: Flow 4 ship (lapsed user re-engagement), subscription center build, win-back campaign, eye mask gifting flow, ambassador lifecycle. The fCMO's role becomes orchestration + brand-voice QA, not hand-cranking each email.

### Capability unlocks by funding stage

| Stage | Headcount | Tooling | Channels live |
|---|---|---|---|
| **Pre-seed-close (now)** | fCMO + founder team | All current tooling + Casey's marketing skill library + MCP layer | Organic only (SEO, content, App Store, LinkedIn, events, WOM, ambassador) |
| **Seed close (~Q3 2026)** | + first marketing hire (lifecycle/content) by end of Q3 | + paid ad accounts (Apple Search Ads, Meta, LinkedIn) | + paid acquisition pilot $5–10K/mo |
| **Seed deployment (Q3–Q4 2026)** | + designer (potentially fractional) | + analytics expansion (Mixpanel or Amplitude if needed) | + paid scaling $20–50K/mo, + Guides cert pilot |
| **Series A (2027)** | + performance marketing lead + content lead | + dedicated tooling spend (~$2–5K/mo software) | + paid scaling $50–150K/mo, + international, + B2B vertical expansion |

The marketing skill library scales these stages. Every channel added doesn't require a 1:1 headcount increase because each skill encodes the workflow.

---

## 12. Tactical idea bank — 139-idea cross-reference

The `marketing-ideas` skill catalogs 139 proven marketing tactics. Sections 4–8 (AARRR) prescribe what we're *doing*. This section maps the full universe of what's *possible* — every idea cross-referenced to the AARRR stage it primarily serves, with Quietude applicability and timing.

This is the exhaustive menu. The plan above is the curated path. When we move to Q2 / Q3 / Series A and unlock new capacity, this is the inventory we pull from.

**Status legend:**

- **Now (Q1)** — already in the 90-day plan OR can run alongside it without new capacity
- **Q2** — post-bedrock-fix, post-foundation; second-quarter layer-ins
- **Q3+** — post-seed-close, post-GA; expansion moves
- **Q4+** — long-game / large-investment moves
- **Skip / off-brand** — incompatible with Quietude's brand voice, business model, or product category

### 12.1 Acquisition ideas (88 mapped)

**Now (Q1):**

| # | Idea | Quietude note |
|---|---|---|
| 1 | Easy Keyword Ranking | SEO plan Tier-1 cluster (nervous system, sleep mask, B2B) targets this directly |
| 2 | SEO Audit | Run `/seo-audit quietude.app` quarterly; publish findings as content |
| 5 | Content Repurposing | Sound Philosophy → essays → LinkedIn posts → newsletter → podcast loop |
| 6 | Proprietary Data Content | peer-reviewed psychophysiology study now; anonymized Quietude HRV / sleep dataset later |
| 7 | Internal Linking | Built into the pillar/spoke structure of the SEO plan |
| 10 | Parasite SEO | Alex's LinkedIn already does this; consider mirror to Substack |
| 12 | Marketing Jiu-Jitsu | Meditation-vs-Regulation IS this — turn "meditation works" assumption against itself |
| 36 | Quora Marketing | Answer "why meditation doesn't work for me" + HRV + somatic questions |
| 37 | Reddit Keyword Research | Mine r/somatic, r/CPTSD, r/HSP, r/ADHD for ICP language (feeds Customer Language #139) |
| 39 | LinkedIn Audience | Alex's channel productized — primary D2C top-of-funnel today |
| 59 | Article Quotes | HARO / Help-A-B2B-Writer for Alex + Sam — easy press wins |
| 70 | Conference Speaking | Alex: WELL Conference, biophilic design events, Mindful Leadership Summit |
| 74 | Press Coverage | Pitch peer-reviewed study + longevity-influencer hook to 5 outlets in Q1 |
| 109 | Public Demos | Live Quietude events ARE this; instrument the in-person → app conversion |
| 114 | Moneyball Marketing | Already practicing — asymmetric SEO keywords, undervalued channels |
| 133 | Investor Marketing | Alex's raise — leverage angel backchannel for PR + intros |

**Q2:**

| # | Idea | Quietude note |
|---|---|---|
| 3 | Glossary Marketing | Sound + nervous system glossary — "what is polyvagal," "what is HRV," "what is somatic listening" |
| 8 | Content Refreshing | Revisit Pillar 1 quarterly with new data and search-intent updates |
| 11 | Competitor Comparison Pages | Quietude vs. Calm / Headspace / Brain.fm / Endel / Wavepaths — high-intent SERPs |
| 13 | Competitive Ad Research | SpyFu + Facebook Ad Library before launching paid |
| 17 | Quiz Marketing | "What's your nervous system profile?" — generates personalization seed + lead capture |
| 25 | Facebook Ads | Eye mask creative + somatic content + retargeting from event attendees |
| 26 | Instagram Ads | Visual product + Reels-native ads (eye mask especially) |
| 28 | LinkedIn Ads | B2B venue buyers + investor-adjacent ICP |
| 31 | Google Ads | Apple Search Ads first (App Store intent); Google for eye mask + B2B |
| 38 | Reddit Marketing | Authentic participation in r/somatic, r/HSP, r/ADHD after content base exists |
| 40 | Instagram Audience | Eye mask + somatic creators; Reels-native |
| 44 | Comment Marketing | Thoughtful comments on Huberman / the partner-event-business / Tim Ferriss / wellness creators |
| 49 | Monthly Newsletters | Either Quietude-branded or sync with Sam's Sam's Substack newsletter |
| 54 | Affiliate Discovery via Backlinks | Find who links to Calm/Headspace/Brain.fm — pitch them on Quietude affiliate program |
| 58 | Newsletter Swaps | the partner-event-business, founder wellness Substacks, Alex's investor network |
| 64 | Community Sponsorship | Somatic newsletters, wellness Substacks, founder communities |
| 65 | Live Webinars | Alex + Sam hosting "Sound + the Nervous System" |
| 101 | Industry Interviews | Alex + Sam interview category experts (becomes seed of Quietude podcast) |
| 102 | Social Screenshots | Mira reflection responses (anonymized, consented) — social proof gold |
| 108 | Changelogs | Public changelog at `quietude.app/changes` — product momentum signal |
| 115 | Curation as Marketing | Curated "field recordings of the year" feature; Quietude Spaces directory |
| 135 | Support as Marketing | Surface customer support / Mira reflection moments as content |
| 138 | Podcast Tours | Alex on Huberman, the partner-event-business, Tim Ferriss, Rich Roll, Rangan Chatterjee |

**Q3+:**

| # | Idea | Quietude note |
|---|---|---|
| 4 | Programmatic SEO | Quietude Guides city pages once Guides program scales |
| 9 | Knowledge Base SEO | When help docs scale enough to have problem-solution coverage |
| 14 | Side Projects | Eventually a free Quietude-adjacent tool that lives outside the app |
| 15 | Engineering as Marketing | HRV interpretation guide; nervous system self-assessment; sound bath finder directory |
| 18 | Calculator Marketing | Sleep latency calculator; overstimulation index |
| 20 | Microsites | For specific GTM moments (e.g., Mira GA launch) |
| 23 | Podcast Advertising | Huberman, Tim Ferriss, Rich Roll, the partner-event-business — host-read most relevant |
| 24 | Pre-targeting Ads | Warm audiences via content before direct-response |
| 29 | Reddit Ads | r/HSP, r/ADHD, r/somatic — high ICP density, low advertiser saturation |
| 30 | Quora Ads | Intent-rich for "why meditation doesn't work" queries |
| 32 | YouTube Ads | Pre-roll on Huberman / Lex Fridman / wellness creator videos |
| 33 | Cross-Platform Retargeting | Standard layer once paid is firing |
| 35 | Community Marketing | Quietude Spaces community (Discord/Circle); host monthly drop-ins |
| 42 | Short Form Video | TikTok / Reels — somatic education + eye mask UGC |
| 55 | Influencer Whitelisting | Run ads through ambassador / Guide accounts for authenticity |
| 57 | Expert Networks | Quietude Guides program IS this — certified hosts who can market |
| 60 | Pixel Sharing | Standard once paid is firing |
| 61 | Shared Slack Channels | Partner venue Slacks (Aurora, Lumen, Stillwater) |
| 63 | Integration Marketing | Apple Health (HRV data), Oura, Whoop — co-marketing |
| 66 | Virtual Summits | Quietude participates or hosts |
| 68 | Local Meetups | Cities with high ICP density (SF, NYC, LA, Austin) |
| 69 | Meetup Sponsorship | Sponsor wellness / biohacking meetups |
| 72 | Conference Sponsorship | Industry conferences once budget unlocks |
| 75 | Fundraising PR | "Quietude raises $3M" moment when seed closes |
| 78 | Product Hunt Launch | Mira public launch moment |
| 79 | Early-Access Referrals | App GA early-access list (cross-references to Referral) |
| 81 | Early Access Pricing | App GA — early-access tier locked in for first cohort |
| 82 | Product Hunt Alternatives | BetaList, Launching Next, AlternativeTo at GA |
| 97 | Playlists as Marketing | Quietude curates Spotify playlists for somatic listening |
| 98 | Template Marketing | Free "nervous system reset" protocol PDFs |
| 100 | Promo Videos | High-quality brand films — Ed Dorsey advises, Matt Mikkelsen field audio |
| 103 | Online Courses | Alex's Sound Philosophy course; Sam's somatic methodology course |
| 107 | Podcasts | Quietude podcast — interview format with category experts and customers |
| 111 | Challenges as Marketing | "21-day nervous system reset" — tasteful, no fitness-bro tone |
| 113 | Controversy as Marketing | Meditation-vs-Regulation IS mild controversy — lean in carefully |
| 126 | YouTube Reviews | Pitch Quietude to wellness YouTubers — Huberman fan-creator tier |
| 127 | YouTube Channel | Sound design behind-the-scenes; Sam session demos |
| 129 | Review Sites | App Store reviews actively managed; Trustpilot for eye mask Shopify |
| 130 | Live Audio | Twitter Spaces / LinkedIn Audio with Alex on sound + body |
| 134 | Certifications | Quietude Guides cert IS this — Q3+ pilot |

**Q4+ / long-game:**

| # | Idea | Quietude note |
|---|---|---|
| 56 | Reseller Programs | Corporate wellness platforms (Modern Health, Lyra) as resellers |
| 67 | Roadshows | Quietude Experiences IS this — eye mask + listening session pop-ups in 3 cities |
| 71 | Conferences | Quietude-hosted "Sound + the Body" — long-game category-defining moment |
| 76 | Documentaries | Alex's story is documentary-grade — long game |
| 77 | Black Friday Promotions | Holiday eye mask + Premium bundle |
| 80 | New Year Promotions | New Year nervous system reset campaign |
| 84 | Giveaways | Eye mask giveaway with brand partner (Wellness Mama tier) |
| 85 | Vacation Giveaways | Quietude + retreat partner giveaway (quietude.center could be venue) |
| 87 | Powered By Marketing | "Sound system by Quietude" badge in B2B venue installs |
| 104 | Book Marketing | Sound Philosophy as a book — long-game positioning anchor |
| 105 | Annual Reports | "State of the Nervous System" — Quietude's data + industry commentary |
| 106 | End of Year Wraps | "Your nervous system year" — Spotify Wrapped equivalent |
| 110 | Awards as Marketing | Quietude founds an award for innovative biophilic acoustic design |
| 116 | Grants as Marketing | Free Quietude subscriptions for therapists, social workers, first responders |
| 119 | OOH Advertising | SF / NYC billboards if Series A budget unlocks |
| 120 | Marketing Stunts | Public sound installation could work — brand-fitting |
| 121 | Guerrilla Marketing | Sound installation in subway / airport — interesting but requires care |
| 131 | International Expansion | Finland HQ + global ICP — Q4 or post-Series A |

**Skip / off-brand for Quietude:**

| # | Idea | Why skip |
|---|---|---|
| 16 | Importers as Marketing | No competitor data to import (consumer wellness, not SaaS) |
| 19 | Chrome Extensions | Off-platform (mobile-first product) |
| 21 | Scanners | No obvious product fit |
| 22 | Public APIs | Not core business |
| 27 | Twitter Ads | Lower priority unless Alex's X presence grows |
| 34 | Click-to-Messenger Ads | Off-brand (no DM-driven sales pattern) |
| 41 | X Audience | Depends on Alex's bandwidth — defer unless he wants to |
| 43 | Engagement Pods | Off-brand |
| 73 | Media Acquisitions | Too capital-intensive at this stage |
| 83 | Twitter Giveaways | Off-brand voice |
| 86 | Lifetime Deals | Brand-conflict — pressures the "no pressure" voice and damages LTV math |
| 88 | Free Migrations | No competitor data to migrate |
| 89 | Contract Buyouts | Not relevant for D2C subs |
| 99 | Graphic Novel Marketing | Off-brand |
| 112 | Reality TV Marketing | Off-brand |
| 117 | Product Competitions | Not a developer product |
| 118 | Cameo Marketing | Off-brand |
| 122 | Humor Marketing | Brand voice is serious; humor would feel off |
| 123 | Open Source as Marketing | Proprietary audio library |
| 125 | App Marketplaces | Not relevant for native consumer app (no app-of-app pattern) |
| 128 | Source Platforms | G2 / Capterra are B2B-focused; D2C uses App Store reviews |
| 132 | Price Localization | Q4+ — tied to international expansion |
| 136 | Developer Relations | Not a dev product |

### 12.2 Activation ideas (7 mapped)

| # | Idea | Status | Quietude note |
|---|---|---|---|
| 124 | App Store Optimization | Now | Q1 priority — listing rewrite in voice (also Acquisition) |
| 90 | One-Click Registration | Now | OAuth (Apple, Google) for app signup — standard activation lift |
| 51 | Onboarding Emails | Q2 | Flow 2 — held until UI stable post-onboarding-rebuild |
| 96 | Onboarding Optimization | Q1-Q2 | The 3-variant test IS this — primary activation work |
| 47 | Founder Welcome Email | Q2 | Personal welcome from Alex or Sam early in Flow 2 |
| 48 | Dynamic Email Capture | Q2 | Smart capture on `quietude.app` — exit intent + scroll depth |
| 95 | Concierge Setup | Q3+ | High-touch onboarding for B2B venue clients + high-value subscribers |

### 12.3 Retention ideas (8 mapped)

| # | Idea | Status | Quietude note |
|---|---|---|---|
| 46 | Reactivation Emails | Now | Flow 4 ships in weeks 3–4 — exactly this |
| 52 | Win-back Emails | Q1 (week 11-12) | Standalone campaign on top of Flow 4 |
| 53 | Trial Reactivation | Q2 | Expired-trial recovery campaign once paywall is firing |
| 45 | Mistake Email Marketing | Q2 | When something genuinely goes wrong, send "oops" — drives engagement |
| 50 | Inbox Placement | Q1 | Subdomain silo strategy (`mail.quietude.app` / `commerce.quietude.app`) addresses this |
| 91 | In-App Upsells | Q2 | Premium upsell points within app (also Revenue) |
| 94 | Offboarding Flows | Q2 | Optimize cancellation flow to retain or learn — feeds churn intel |
| 135 | Support as Marketing | Q2 | Customer support stories surface as content (also Acquisition) |

### 12.4 Referral ideas (5 mapped)

| # | Idea | Status | Quietude note |
|---|---|---|---|
| 62 | Affiliate Program | Now | Ambassador program v1 is exactly this — launched with the 5 inbound |
| 137 | Two-Sided Referrals | Q2 | Reward both referrer and referred — share-after-shift moment + gifting flow |
| 92 | Newsletter Referrals | Q3 | If we launch a newsletter, Sparkloop-style referral mechanic |
| 93 | Viral Loops | Q3 | Built-in share mechanics post-Mira reflection |
| 79 | Early-Access Referrals | Q3 | App GA early-access list referrals (cross-references to Acquisition) |

### 12.5 Revenue ideas (3 mapped — most ideas serve top-of-funnel)

| # | Idea | Status | Quietude note |
|---|---|---|---|
| 91 | In-App Upsells | Q2 | Premium upgrade prompts; eye mask cross-sell from app (also Retention) |
| 132 | Price Localization | Q4+ | Adjust pricing for local purchasing power once international |
| 86 | Lifetime Deals | Skip | Brand-conflict — see Acquisition skip list |

### 12.6 Cross-cutting / brand foundation ideas

| # | Idea | Status | Quietude note |
|---|---|---|---|
| 139 | Customer Language | Now | Mira reflection responses + 7 Ds language = the source-of-truth for customer language across all copy |
| 114 | Moneyball Marketing | Ongoing | Find undervalued channels at every stage — methodology, not a single tactic |

### Idea-bank summary

- **88 ideas applicable to Acquisition** (the dominant stage at Quietude's current stage — makes sense, Quietude's product converts well; the bottleneck is the top of funnel)
- **7 ideas to Activation, 8 to Retention** (smaller because these stages are about depth, not breadth — execute the right few well rather than running a wide tactic menu)
- **5 ideas to Referral** (program-driven, not tactic-driven)
- **3 ideas to Revenue** (most revenue work is pricing strategy, not tactical tricks)
- **2 cross-cutting**
- **23 ideas skipped for brand / business-model fit** — Quietude's category positioning constrains what's available

**What this proves:** the plan is roughly 30% of the available tactical surface area, not 100%. That's appropriate at this stage and budget. As capacity unlocks across Q2 → Q3 → Series A, the cross-reference becomes the inventory we pull from to scale activity without losing strategic coherence.

---

## 13. Measurement, RACI, open decisions, appendix

### Measurement — the metrics that matter

**North star (proposed):**
**Blended-LTV-to-blended-CAC ratio per acquired user**, where:
- Blended LTV combines app subscription revenue + hardware revenue (eye mask + speakers) + any cross-sells, per cohort
- Blended CAC combines paid spend + content production cost + ambassador commissions + lifecycle tool spend, per cohort

This captures the business model: the eye mask wedge isn't free if it costs $X to make, and the app sub isn't expensive to acquire if a Bryan-Johnson-style PR moment is paying for itself.

If a single metric is preferred for team-level focus, fall back to: **monthly new D2C subscribers from non-paid channels.** This isolates the compound channels the long-game strategy depends on.

**Leading indicators by AARRR stage:**

| Stage | Leading indicators |
|---|---|
| Acquisition | Organic visits/mo (overall + per pillar), App Store visit-to-install rate, Alex's LinkedIn engagement → email subscribers, event-to-app conversion rate, ambassador-attributed visits |
| Activation | Day 1 / Day 7 / Day 35 → paid conversion, onboarding session-completion rate, first session Mira reflection completion |
| Retention | 30 / 60 / 90-day retention, monthly churn, Flow 4 reactivation rate, hardware → app activation rate |
| Referral | Ambassador-attributed new subs (Dub), share-after-shift rate, Guides pilot referrals (when live) |
| Revenue | Blended MRR, ARPU, annual plan adoption %, LTV by cohort, eye mask attach rate |

**Review cadence:**
- **Weekly:** fCMO ↔ Alex 30-min sync. AARRR scoreboard + this week's ships.
- **Monthly:** Full metrics review (extended sync, Sam included). Compare against quarterly KPI targets.
- **Quarterly:** Plan recalibration. What's working, what's not, what funding-stage moves we're triggering.

### RACI

| Domain | Responsible | Accountable | Consulted | Informed |
|---|---|---|---|---|
| Strategic plan (this doc) | Casey | Alex | Sam, Emily | Team |
| Brand voice | Alex + Sam | Alex + Sam | Casey | Team |
| App + onboarding implementation | Devon | Alex | Casey | Team |
| Lifecycle flows (Customer.io) | Casey | Alex | Sam (copy QA) | Team |
| SEO content | Casey | Casey | Sam, Alex | Team |
| App Store copy | Casey | Alex | Sam | Team |
| Alex's LinkedIn cadence | Alex | Alex | Casey (orchestration) | Team |
| Events | Alex + Sam | Alex | Casey (instrumentation only) | Team |
| Ambassador program | Casey | Casey | Alex | Team |
| B2B sales | Alex | Alex | Casey (case studies) | Team |
| Pricing | Alex | Alex | Casey | Sam |
| Investor narrative | Alex | Alex | Casey, Sam | Team |
| Quietude Guides program (Q3+) | TBD (likely future hire) | Alex + Sam | Casey | Team |
| Future marketing hire (Q3) | Casey | Alex | Sam | Team |

### Open decisions blocking the plan

Most blocking, ranked by impact:

1. **Canonical domain.** SEO data + this plan recommend `quietude.app`. Needs exec sign-off + 301 execution plan. *Blocks: domain consolidation, SEO foundation, email sender migration.*
2. **Retention metric definition.** Reconcile 38% 12-month retention claim vs. 29% monthly App Store churn. *Blocks: clean dashboards, investor narrative coherence, lifecycle test reads.*
3. **Mira post-session reflection scope.** Does Mira currently support this, or is it new build? *Blocks: Onboarding Variants 1 and 2 (which depend on Mira reflection moment), retention compound moves.*
4. **App UI stability timeline.** When does the headphone-gate-removal + onboarding-rebuild allow Flow 2 to ship without rework risk? *Blocks: Flow 2, full lifecycle, paid acquisition timing.*
5. **GA launch timeline.** When does the throttled beta become GA? *Blocks: paid acquisition scale, Q3 GTM planning.*
6. **Pricing structure ground truth.** What's actually charged today? *Blocks: pricing audit conclusions, annual-plan default test, blended LTV math.*
7. **First marketing hire scope.** Lifecycle + content owner, or something else? When does the JD get written? *Blocks: Q3 capacity plan, succession of fCMO operational work.*
8. **Ambassador commission structure.** $/sub, rev-share, hybrid? *Blocks: ambassador program launch, attribution dashboards.*

### Appendix — deep-dive links

**Published to the team via `Quietude-Inc/quietude-context` GitHub repo:**
- `marketing/seo/plan.md` — Full 90-day SEO + keyword research plan
- `marketing/seo/keyword-shortlist.md` — Tier 1 keyword shortlist
- `marketing/seo/raw/` — Ahrefs + DataForSEO API pulls
- `marketing/onboarding-recommendation.md` — Three-variant onboarding test plan

**Founder-authored strategic context** (in Quietude's internal knowledge base):
- Seed deck — Investor narrative
- Sound Philosophy — Alex's technical/philosophical working doc
- Marketing OS — Brand voice, content rhythm, visual system
- ICP doc — D2C audience profile
- Meditation-vs-Regulation note (2026-05-19) — Central content pillar
- Kickoff call transcript (2026-05-18) — Decisions + open questions
- App Store copy snapshot + voice-gap analysis
- App Store metrics snapshot (2026-05-16)
- Customer.io lifecycle flows inventory

---

*Marketing Plan v1. Prepared by Casey Reed (fCMO), 2026-05-27. For team review and discussion.*


---

# references/funding-stage-unlocks.md

# Funding-Stage Capability Unlocks

Every marketing plan must include explicit "what changes when funding closes / when budget unlocks" reasoning. This makes the plan investor-friendly and operationally honest.

This doc defines the standard tiers. Use them as anchors, adjust for client category and unit economics.

**Related docs:**
- `budget-planning.md` — two scientific methods for setting the actual budget number (Revenue-Based 5–40%, or Goal-Based reverse-engineered from the revenue target), CAC calculation, experimental buffer
- `growth-patterns.md` — the real shape of SaaS growth by phase ($0–10K / $10K–100K / $100K–1M+), linear vs step-function, S-curve layering
- `team-and-agency-model.md` — what each tier means for team composition, the first marketing hire, and the in-house vs outsource ratio

## Why funding stage matters in a marketing plan

Most marketing plans are written as if budget is unconstrained. That's a failure mode for early-stage clients — it produces aspirational lists rather than executable roadmaps.

The fix: tie every recommendation to a budget tier. The plan stays honest about what's executable today, and the team / investors see explicitly what each round of capital unlocks.

This also helps the founder mid-raise: showing what the round buys is investor-narrative material.

## Standard tiers

### Tier 1 — Pre-seed / bootstrapped

**Budget profile:**
- Paid acquisition: $0
- Tooling stack: ~$500–2,000/mo (Customer.io / similar, GA4 free, Stripe fees, Notion, GitHub, basic SaaS)
- Retainers / fCMO: variable (fractional only)
- Headcount: founders + maybe 1–2 multipurpose hires

**Marketing capability:**
- Organic only — SEO, content, App Store organic, founder-led social, events, WOM, ambassador (if inbound exists)
- Limited PR (founder-led pitches, HARO responses)
- No paid layer

**Channels live:** Organic SEO, content, App Store, LinkedIn / X / founder-led social, events, WOM, ambassador

**What a fCMO does:** Strategy + lifecycle + content + SEO + onboarding + community + ambassador. Hands-on with skill library + MCPs doing the operational lift.

**Hires unlocked:** None. The plan must execute with current team + agentic stack.

### Tier 2 — Seed close

**Budget profile:**
- Paid acquisition: $5–15K/mo test budget
- Tooling stack: $1,000–3,000/mo (paid ad accounts, Mixpanel / Amplitude if needed, additional SaaS)
- Retainers / fCMO: continued
- Headcount: + first dedicated marketing hire

**Marketing capability:**
- Above + paid acquisition pilot (Apple Search Ads, Meta, LinkedIn)
- Begin PR push with the funding announcement
- First Product Hunt / GA-style launch

**Channels live:** All Tier 1 + paid acquisition (small) + active PR

**Hires unlocked:**
- Lifecycle + content marketing manager (one person doing both, or split)
- OR dedicated growth / performance marketing manager (if heavy paid focus)

**fCMO shifts:** From hands-on to strategy + ops oversight. Hires the dedicated marketer. Sets up the channel playbooks before paid scales.

### Tier 3 — Seed deployment

**Budget profile:**
- Paid acquisition: $20–50K/mo
- Tooling stack: $2,000–5,000/mo
- Retainers / fCMO: continued
- Headcount: + designer (potentially fractional)

**Marketing capability:**
- Paid scaling across 2–3 channels
- Brand-aligned creative production (designer enables velocity)
- Lifecycle programs fully live across all flows
- First true content production cadence (weekly cadence sustainable)

**Channels live:** All previous + paid scaling + structured launch motion

**Hires unlocked:**
- Designer (brand, creative, web)
- Second marketing manager (if first was lifecycle, second is content; or vice versa)
- Potentially fractional PR if budget allows

**fCMO shifts:** Hands off lifecycle to dedicated owner. Moves to GTM strategy + channel mix optimization + growth analytics.

### Tier 4 — Series A

**Budget profile:**
- Paid acquisition: $50–150K/mo
- Tooling stack: $5,000–10,000/mo
- Retainers / fCMO: may transition to permanent CMO
- Headcount: full marketing team forming

**Marketing capability:**
- Paid scales aggressively across all proven channels
- Brand campaigns become possible
- International consideration begins
- B2B vertical expansion (if applicable)
- Sophisticated CAC/LTV math + attribution

**Channels live:** Full marketing surface area

**Hires unlocked:**
- Performance marketing lead
- Content lead
- Designer (permanent)
- Potentially: PR firm, paid agency, international growth manager
- Series A often the moment the fCMO transitions out or transitions to advisor

**fCMO shifts:** Often the moment of transition — to permanent CMO hire, fCMO becomes advisor.

### Tier 5 — Series B+

**Budget profile:**
- Paid acquisition: $150K+/mo
- Tooling stack: $10,000–25,000/mo
- Headcount: 10+ marketing org

**Marketing capability:**
- Brand campaigns at industry scale
- PR firm partnerships
- Acquisitions as marketing (acquiring newsletters / podcasts in space)
- Conference sponsorship at category level
- Sponsorships at brand level

**Channels live:** Everything available

**Hires unlocked:**
- VP Marketing or CMO
- Brand director
- Growth / performance team (3–5 people)
- Content team (3–5 people)
- Designers (2–3)
- PR director or agency partnership
- International marketing leads (region-specific)

**fCMO involvement:** Typically out of the company by this point — the original fCMO might still be an advisor.

## How to apply tier logic in a plan

### Section 3 (Current state)
- State the client's current tier explicitly: "Current tier: pre-seed / bootstrapped per Tier 1."

### Section 4–8 (AARRR sections)
- Note tier-dependent moves: "Paid layer (Tier 2 unlock — held until seed close)"
- For Tier 1 plans: every move must be executable at current budget tier OR explicitly flagged as future
- For Tier 2+ plans: moves can assume the tier's capability

### Section 10 (12-month outlook)
- Each quarter names the tier that's active: "Q2 — Months 4–6 (post seed close). Funding state: Tier 2."
- Tier transitions trigger plan recalibration moments

### Section 11 (Marketing operations stack)
- Use the table in `references/ops-stack-mapping.md` capability-unlocks section
- Make it client-specific: "Today (Tier 1): {client's current capability}. After seed close (Tier 2): + {what changes}."

## Adjustments by client category

The standard tiers assume a typical software / SaaS / consumer app. Adjust for category:

### Consumer apps (D2C)
- Higher paid acquisition floor — apps need to test CAC against download cost benchmarks (~$2-10 install + 5-15% trial conversion benchmark)
- Tier 2 starts effectively at $10–20K/mo paid (otherwise can't get statistically meaningful reads at app-install CPMs)

### B2B SaaS
- Lower paid acquisition floor — LinkedIn / Google Ads can produce signal at $3–5K/mo
- More weight on content + sales enablement budget
- Often add a sales hire before a content hire

### Hybrid hardware + software
- Hardware revenue can self-fund some marketing (the eye-mask wedge pattern)
- Paid budget should track blended CAC across hardware sales + app subs
- Shopify-side optimization is a Tier 1 priority (cheap leverage)

### Deep-tech / scientific / clinical
- PR + investor marketing carries more weight than paid
- Conference speaking + academic publishing > Meta ads
- Tier 1 can produce significant traction without paid

### Marketplace / two-sided
- Each side has its own AARRR funnel — budget splits accordingly
- Supply-side acquisition often dominates early; demand-side dominates after liquidity

### Open source / developer tools
- DevRel + community + content > paid
- GitHub stars / npm installs are the activation event
- Paid layer often delayed until Series A

## Tier 1 budget detail (most common starting point)

For Tier 1 clients, the marketing budget breakdown typically looks like:

| Line | Typical monthly |
|---|---|
| Customer.io / lifecycle ESP | $100–500 |
| App Store Connect / Google Play | $25 + 30% rev share (Apple/Google take) |
| Stripe | 2.9% + 30¢ per transaction |
| GA4 | Free |
| Notion | $0–100 |
| GitHub | $0–50 |
| Shopify (if hardware) | $39–100 |
| Ahrefs (or similar SEO tool) | $129–399 |
| Typefully (if social cadence) | $13–39 |
| Dub.co (if ambassador tracking) | $0–39 |
| Misc SaaS | $200–500 |
| **Tooling total** | **~$500–1,700/mo** |
| Paid acquisition | $0 |
| fCMO retainer | Variable |

For the plan, this becomes: "Current monthly marketing budget: $X (tooling only, no paid)."

## When to surface tier limits to the founder

If a founder asks for moves that require a future tier:
- Name the requirement: "This is a Tier 2 move (requires $10K+/mo paid budget). Will unlock after seed close per the 12-month outlook in §10."
- Don't refuse — frame the timing

If a founder underestimates what's needed:
- Be honest: "To scale paid acquisition meaningfully, expect Tier 2 budget. Tier 1 can validate organic; Tier 2 validates paid."

If a founder is over-funded for their stage:
- Don't pad budget to match. Recommend the right work for the funnel state, return excess capacity, suggest investment in compounding rather than scaling.

## Tier-skip cases (worth flagging)

Some companies skip tiers:
- **Notable founder** raising larger-than-typical rounds — can jump from Tier 1 to Tier 3 directly
- **Hardware company** with PR moment — can deploy at Tier 3 levels with the right product moment (e.g., a high-profile longevity-influencer endorsement)
- **B2B SaaS post-LOI** with named enterprise contracts — can fund pilot deployment from contract value

If the client is in a tier-skip situation, name it explicitly in the plan rather than forcing them into the standard ladder.


---

# references/growth-patterns.md

# Growth Patterns — The Real Shape of SaaS Growth

The 12-month outlook in every plan (Section 10) describes a trajectory. This doc names the shape of that trajectory honestly — what real SaaS growth looks like, when to expect plateaus, and how to plan for the next leg of growth before the current one stalls.

Excerpted and adapted from *Founding Marketing* by Corey Haines.

## The long, slow SaaS ramp of death

Pitch decks show hockey sticks. Real growth shows a series of S-curves — each representing a distinct phase followed by a plateau that tests resolve and creativity.

### Phase 1 — $0 → $10K ARR (the grueling phase)

The hardest milestone. Every customer is a hard-won victory. Typical time: **6–12 months.** Most companies pivot the product multiple times during this phase.

What it requires:
- Runway long enough to keep experimenting until something clicks
- A financial cushion or additional income sources (often the difference between success and shutdown)
- Tolerance for ambiguity — the product positioning, the pricing, and the channel can all still be wrong at this stage

### Phase 2 — $10K → $100K ARR (the treacherous middle)

The middle ground that kills most promising startups. The average company reaches ~$40K ARR in year one. The danger: enough revenue to prove the concept, not enough to support a team.

The threshold to watch for: **$8–10K MRR.** That's when founders can typically go full-time on the business without other income sources. Until then, careful cash management or side income carries the company through.

Companies that flame out in Phase 2 usually run out of runway just as things start working.

### Phase 3 — $100K → $1M ARR (the acceleration phase)

Where things get interesting. Typical time: nearly 2 years total to reach $1M. But there's an acceleration pattern: **once across $100K, companies often double from $100K → $200K in one-third the time it took to reach the first $100K.**

Why: critical mass kicks in. Word-of-mouth starts working. Early customers become your best salespeople. The product has proven itself, and growth becomes more about execution than experimentation.

This is the phase where the marketing plan's 90-day roadmap (Section 9) starts compounding instead of just covering ground.

## Two real growth patterns (and the exponential myth)

The myth: successful SaaS companies grow exponentially, doubling revenue month over month like clockwork.

The reality: two distinct patterns, often combining at scale to *look* exponential when zoomed out.

### Pattern 1 — Linear growth

Build a predictable revenue machine. Find a channel that works (content, partnerships, paid, outbound) and steadily scale it. Some companies reliably add **$10K MRR per month** through a well-oiled marketing engine.

Less sexy than exponential. Far more sustainable. Crucially, **plannable**: when you know what you can count on adding each month, hiring decisions, product roadmap, and expansion planning all become tractable.

### Pattern 2 — Step-function growth

Periods of plateau followed by sudden jumps. Jumps aren't random — they're triggered by specific events:
- Breaking into a new market segment (e.g., enterprise after starting SMB)
- Launching a major product expansion (new feature line, new tier)
- Cracking a new marketing channel that compounds

Example: one founder saw revenue triple in two months after launching enterprise features — following six months of flat growth.

Key insight for the plan: **each step requires deliberate action and investment.** Steps don't happen by waiting. While standing on the current step, you have to be actively building the next one.

### How they combine

Zoom out far enough and a series of linear phases + step functions can look exponential. That's where the myth comes from. Understanding it's actually a series of plannable shapes changes how you build the plan:

- Don't chase the myth of doubling every month
- Build sustainable linear systems (Sections 4–8 AARRR moves)
- Plan deliberate step functions (Section 10 12-month milestones)

## Layering growth curves — Channel × Product × Market

The secret to sustained growth isn't one perfect channel. It's orchestrating multiple S-curves that work together. Three S-curves to track:

### Channel S-curves

Every marketing channel has its own lifecycle:
- **SEO** — 6–12 months to mature; once it does, steady leads for years. Marathon runner.
- **Paid ads** — quick wins; diminishing returns as you scale.
- **Content marketing** — slow to start, compounds beautifully over time.
- **Partnerships / co-marketing** — episodic; high yield when the right partner aligns.
- **Outbound** — predictable when calibrated; CAC-heavy and plateaus at team capacity.
- **PR** — spike-driven; sustains awareness rather than direct conversion.

**The rule:** start the next channel before the current one plateaus. Riding one channel to its ceiling before investing in the next produces a multi-month growth plateau that takes more effort to break out of than it would have taken to start the next channel earlier.

In the plan: Section 4 (Acquisition) names current channels, planned channels, and skipped channels. The 12-month roadmap (Section 10) sequences when the next channel investment begins.

### Product S-curves

Your core product naturally hits a growth ceiling as you saturate the initial market. Pushing harder on the same features doesn't break through. What does:

- Adding features that target new use cases
- Extending the product line to serve adjacent needs
- Expanding into new market segments (e.g., team collaboration added to a single-user tool — opens a new market)

In the plan: Sections 5 (Activation) and 8 (Revenue) name where the product needs to grow to unlock the next growth tier.

### Market S-curves

Every market segment has its own growth ceiling. Time the expansion into the next segment while the current segment is still showing strong growth. Common patterns:

- SMB → mid-market → enterprise
- Single vertical → adjacent verticals
- Domestic → international

Waiting until a segment is saturated makes the transition harder.

In the plan: Section 2 (Strategic frame) names current segment + future segments. Section 10 (12-month outlook) sequences when expansion moves begin.

### The orchestration

The real magic: while SEO is maturing, you're using paid for quick wins. As those channels mature, you're developing product features that unlock enterprise. Meanwhile, the groundwork for international expansion is being laid for when domestic saturates.

This is the operational thesis behind the AARRR mapping (Sections 4–8) and the 12-month outlook (Section 10): each section is a curve, and the plan sequences them so the next curve is ramping while the current one is still growing.

## The 70/20/10 resource-allocation rule

Layering S-curves only works if the next curve is funded *before* the current one plateaus. The 70/20/10 rule is the budgeting discipline that guarantees it. Split marketing effort and spend across three buckets:

| Bucket | Share | What it covers |
|---|---|---|
| **Current** | **70%** | The initiatives already working — the channels, content, and campaigns driving today's growth. Protect and optimize. |
| **Next** | **20%** | The S-curve you're deliberately building — the channel/product/market bet that becomes the *current* 70% in 2–4 quarters. |
| **Experimental** | **10%** | Unproven bets and small tests. Most fail; the ones that work graduate into the 20%, then the 70%. |

Why it matters for the plan:

- It operationalizes "start the next S-curve before the current one plateaus" — the 20% + 10% *is* the next curve, funded on purpose rather than scrambled for after a plateau hits.
- It maps cleanly onto the **10–20% experimental budget buffer** in `budget-planning.md` — the experimental layer is the 10% here.
- It gives Section 11 (Ops stack) and Section 10 (12-month outlook) a defensible allocation logic instead of dumping the whole budget into what's currently working.

**In the plan:** Section 10 (12-month outlook) names what sits in each bucket now, and what's expected to graduate. Section 11 (Ops stack) shows the 70/20/10 split across the AARRR stages. Adjust the ratio by phase — Phase 1 companies (still hunting for any channel that works) may run closer to 40/30/30; Phase 3 companies with a proven engine can run 80/15/5.

## Weekly tracking cadence and plateau alerts

S-curve plateaus are the single most important thing to catch early — the whole point of layering curves is to shift weight to the next one *before* the current plateau bites. That requires a review rhythm, not an annual look-back.

### The cadence

- **Weekly** — review the leading indicators for each active S-curve (new signups per channel, content velocity, activation rate, MRR added). Weekly is frequent enough to spot a curve flattening while there's still time to act.
- **Monthly** — roll the weeklies up; confirm which bucket (70/20/10) each initiative belongs in and whether anything should graduate or be cut.
- **Quarterly** — the plan itself adjusts (re-sequence Section 10, reallocate the budget).

### Plateau-indicator alerts

Watch for these signals that a curve is topping out — each is a trigger to shift weight toward the next curve, not to push harder on the current one:

- **Week-over-week additions flattening** — the channel is adding the same absolute numbers it did last month despite equal or greater effort (declining marginal return).
- **Rising CAC on a formerly cheap channel** — paying more for the same result is the classic plateau tell.
- **Engagement/activation softening at the top of the funnel** — the audience for this channel/message is saturating.
- **Effort up, output flat** — the team is working harder to hold the line rather than to grow it.

When two or more fire on the same curve, that's the trigger to accelerate the **20% "next" bucket** — the plateau is the moment between two S-curves, and it should already have a successor ramping.

**In the plan:** Section 13 (Measurement) names the weekly leading indicators per S-curve and the specific plateau thresholds that trigger the next move. This turns "watch for plateaus" from a platitude into an operational alert.

## The 3-3-2-2-2 VC growth path

For companies that have crossed $1M ARR and raised institutional capital, the VC benchmark is:

| Year | Multiple | Cumulative ARR (from $1M) |
|---|---|---|
| Year 0 | — | $1M |
| Year +1 | 3× | $3M |
| Year +2 | 3× | $9M |
| Year +3 | 2× | $18M |
| Year +4 | 2× | $36M |
| Year +5 | 2× | $72M |
| Year +6 | 2× | $144M |
| Year +7 | 2× | $288M |

Most companies don't hit this. Useful regardless — anchoring the 12-month outlook against this benchmark forces the plan to either (a) match it and show how, or (b) explicitly defend choosing a slower trajectory.

For non-VC-backed (bootstrapped, founder-funded, profit-focused) companies, this curve doesn't apply. Use linear or step-function targeting instead.

## How this informs the plan

| Section | What to include |
|---|---|
| **3 (Current state)** | Where the company is on each S-curve (channel maturity, product maturity, market saturation). Name the current phase ($0–10K / $10K–100K / $100K–1M / $1M+). |
| **4 (Acquisition)** | Current channels + their position on the S-curve (early / mature / plateauing). Next channel investment with rationale. |
| **5–8 (AARRR)** | Each section names the binding constraint at the current phase. For Phase 2 companies, Activation is usually the leverage point. For Phase 3, Retention + Referral compound the existing growth. |
| **9 (90-day roadmap)** | Linear-pattern moves dominate (predictable additions). Step-function setups (the build-up to a launch, an enterprise tier, a new market segment) live here. |
| **10 (12-month outlook)** | Sequence channel S-curves, product S-curves, market S-curves. Apply the 70/20/10 split (current / next / experimental) so the next curve is funded before the current one plateaus. If VC-backed Series A+, anchor against 3-3-2-2-2. If not, name the linear or step-function targets. |
| **11 (Ops stack)** | Show the 70/20/10 allocation across the AARRR stages — what share protects what's working vs. builds the next curve vs. experiments. |
| **13 (Measurement)** | The north-star metric reflects the current phase (Phase 1 is usually pure new-signup; Phase 3 is usually expansion ARR or NRR). Name the weekly leading indicators per S-curve and the plateau thresholds that trigger the next move. |

## Operational guidance for the planner

- **Don't promise exponential.** If the plan implies doubling every month, the founder will use it against you in 90 days. Linear + step-function is honest.
- **Name the binding constraint.** Phase 1 binding constraint is finding any channel that works. Phase 2 is funding the team. Phase 3 is breaking the ceiling on whichever channel got you here.
- **Plateaus aren't failures.** They're the moment between two S-curves. The plan should anticipate them and stage the next move.
- **Don't conflate "growth" with "growth rate."** A company adding $20K MRR each month for 24 months has built a remarkable machine. The fact that the *percentage* growth rate declines as the base grows is arithmetic, not failure.


---

# references/idea-cross-reference.md

# Idea Cross-Reference — 139 Marketing Ideas Mapped to AARRR

The `marketing-ideas` skill catalogs 139 proven marketing tactics. This doc is the source-of-truth mapping: every idea assigned to a primary AARRR stage, with notes for when it's typically active and what category constraints apply.

The plan's Section 12 ("Tactical idea bank") uses this mapping as the base, then layers client-specific filters: brand voice rules might skip some ideas; funding stage might shift Q-status; client category might rule out others.

## How to read this doc

- **139 unique ideas, 144 entries.** Five ideas cross-cut multiple AARRR stages and appear under each stage they serve (#79 Early-Access Referrals, #86 Lifetime Deals, #91 In-App Upsells, #114 Moneyball Marketing, #117 Product Competitions). Each duplicate row carries a cross-cut note.
- **"Entries" counts rows; idea IDs are unique.** Section header counts reflect rows in this doc, not unique ideas from `marketing-ideas`.
- **Numbers correspond exactly to the `marketing-ideas` skill ordering.** If `marketing-ideas` reorders or expands, update this doc.

## AARRR assignment for all 139 ideas

### Acquisition (116 entries)

These ideas primarily serve top-of-funnel awareness, traffic, and lead generation.

| # | Idea | Category | Typical stage available |
|---|---|---|---|
| 1 | Easy Keyword Ranking | Content & SEO | Now (any stage) |
| 2 | SEO Audit | Content & SEO | Now |
| 3 | Glossary Marketing | Content & SEO | Q2+ |
| 4 | Programmatic SEO | Content & SEO | Q3+ (needs data + template system) |
| 5 | Content Repurposing | Content & SEO | Now (immediate leverage) |
| 6 | Proprietary Data Content | Content & SEO | Now (if data exists) |
| 7 | Internal Linking | Content & SEO | Now |
| 8 | Content Refreshing | Content & SEO | Q2+ (after content base exists) |
| 9 | Knowledge Base SEO | Content & SEO | Q3+ (after help docs exist) |
| 10 | Parasite SEO | Content & SEO | Now |
| 11 | Competitor Comparison Pages | Competitor | Q2+ |
| 12 | Marketing Jiu-Jitsu | Competitor | Now |
| 13 | Competitive Ad Research | Competitor | Pre-paid |
| 14 | Side Projects | Free Tools | Q3+ |
| 15 | Engineering as Marketing | Free Tools | Q3+ |
| 16 | Importers as Marketing | Free Tools | SaaS-specific |
| 17 | Quiz Marketing | Free Tools | Q2+ |
| 18 | Calculator Marketing | Free Tools | Q3+ |
| 19 | Chrome Extensions | Free Tools | Browser-relevant only |
| 20 | Microsites | Free Tools | Q3+ |
| 21 | Scanners | Free Tools | Specific products only |
| 22 | Public APIs | Free Tools | Developer/dev tool products |
| 23 | Podcast Advertising | Paid Ads | Post-budget |
| 24 | Pre-targeting Ads | Paid Ads | Post-budget |
| 25 | Facebook Ads | Paid Ads | Post-budget |
| 26 | Instagram Ads | Paid Ads | Post-budget |
| 27 | Twitter Ads | Paid Ads | Post-budget |
| 28 | LinkedIn Ads | Paid Ads | Post-budget (B2B-strong) |
| 29 | Reddit Ads | Paid Ads | Post-budget |
| 30 | Quora Ads | Paid Ads | Post-budget |
| 31 | Google Ads | Paid Ads | Post-budget |
| 32 | YouTube Ads | Paid Ads | Post-budget |
| 33 | Cross-Platform Retargeting | Paid Ads | Post-paid-firing |
| 34 | Click-to-Messenger Ads | Paid Ads | Niche use cases |
| 35 | Community Marketing | Social & Community | Q3+ |
| 36 | Quora Marketing | Social & Community | Now |
| 37 | Reddit Keyword Research | Social & Community | Now |
| 38 | Reddit Marketing | Social & Community | Q2+ |
| 39 | LinkedIn Audience | Social & Community | Now (B2B + founders) |
| 40 | Instagram Audience | Social & Community | Q2+ |
| 41 | X Audience | Social & Community | Depends on founder bandwidth |
| 42 | Short Form Video | Social & Community | Q3+ |
| 43 | Engagement Pods | Social & Community | Generally off-brand |
| 44 | Comment Marketing | Social & Community | Q2+ |
| 49 | Monthly Newsletters | Email | Q2+ (Acquisition use: subscriber capture) |
| 54 | Affiliate Discovery via Backlinks | Partnerships | Q2+ |
| 55 | Influencer Whitelisting | Partnerships | Post-paid-budget |
| 56 | Reseller Programs | Partnerships | Q4+ |
| 57 | Expert Networks | Partnerships | Q3+ |
| 58 | Newsletter Swaps | Partnerships | Q2+ |
| 59 | Article Quotes (HARO) | Partnerships | Now |
| 60 | Pixel Sharing | Partnerships | Post-paid |
| 61 | Shared Slack Channels | Partnerships | Q3+ |
| 63 | Integration Marketing | Partnerships | Q3+ |
| 64 | Community Sponsorship | Partnerships | Q2+ |
| 65 | Live Webinars | Events | Q2+ |
| 66 | Virtual Summits | Events | Q3+ |
| 67 | Roadshows | Events | Q4+ |
| 68 | Local Meetups | Events | Q3+ |
| 69 | Meetup Sponsorship | Events | Q3+ |
| 70 | Conference Speaking | Events | Now (if founder is speakable) |
| 71 | Conferences (own-hosted) | Events | Q4+ |
| 72 | Conference Sponsorship | Events | Q3+ |
| 73 | Media Acquisitions | PR & Media | Series A+ |
| 74 | Press Coverage | PR & Media | Now (if newsworthy) |
| 75 | Fundraising PR | PR & Media | When fund closes |
| 76 | Documentaries | PR & Media | Q4+ |
| 77 | Black Friday Promotions | Launches | Q4 (seasonal) |
| 78 | Product Hunt Launch | Launches | At GA or major feature |
| 79 | Early-Access Referrals | Launches | Pre-launch or GA |
| 80 | New Year Promotions | Launches | Q1 (seasonal) |
| 81 | Early Access Pricing | Launches | GA |
| 82 | Product Hunt Alternatives | Launches | Same as PH |
| 83 | Twitter Giveaways | Launches | Generally off-brand |
| 84 | Giveaways | Launches | Q3+ |
| 85 | Vacation Giveaways | Launches | Q4+ (seasonal) |
| 86 | Lifetime Deals | Launches | Generally off-brand (damages LTV math) |
| 87 | Powered By Marketing | Product-Led | Q4+ |
| 88 | Free Migrations | Product-Led | SaaS-specific |
| 89 | Contract Buyouts | Product-Led | B2B SaaS only |
| 97 | Playlists as Marketing | Content Formats | Q3+ |
| 98 | Template Marketing | Content Formats | Q3+ |
| 99 | Graphic Novel Marketing | Content Formats | Generally off-brand |
| 100 | Promo Videos | Content Formats | Q3+ |
| 101 | Industry Interviews | Content Formats | Q2+ |
| 102 | Social Screenshots | Content Formats | Q2+ |
| 103 | Online Courses | Content Formats | Q3+ |
| 104 | Book Marketing | Content Formats | Q4+ |
| 105 | Annual Reports | Content Formats | Q4+ |
| 106 | End of Year Wraps | Content Formats | Q4 (seasonal) |
| 107 | Podcasts (own-hosted) | Content Formats | Q3+ |
| 108 | Changelogs | Content Formats | Q2+ |
| 109 | Public Demos | Content Formats | Now |
| 110 | Awards as Marketing | Unconventional | Q4+ |
| 111 | Challenges as Marketing | Unconventional | Q3+ |
| 112 | Reality TV Marketing | Unconventional | Generally off-brand |
| 113 | Controversy as Marketing | Unconventional | Brand-dependent |
| 114 | Moneyball Marketing | Unconventional | Ongoing methodology |
| 115 | Curation as Marketing | Unconventional | Q2+ |
| 116 | Grants as Marketing | Unconventional | Q4+ |
| 117 | Product Competitions | Unconventional | Developer-specific |
| 118 | Cameo Marketing | Unconventional | Generally off-brand |
| 119 | OOH Advertising | Unconventional | Series A+ |
| 120 | Marketing Stunts | Unconventional | Brand-dependent |
| 121 | Guerrilla Marketing | Unconventional | Brand-dependent |
| 122 | Humor Marketing | Unconventional | Brand-dependent |
| 123 | Open Source as Marketing | Platforms | Developer products |
| 125 | App Marketplaces | Platforms | Platform-specific |
| 126 | YouTube Reviews | Platforms | Q3+ |
| 127 | YouTube Channel | Platforms | Q3+ |
| 128 | Source Platforms | Platforms | B2B SaaS only |
| 129 | Review Sites | Platforms | Now |
| 130 | Live Audio | Platforms | Q3+ |
| 131 | International Expansion | International | Q4+ |
| 133 | Investor Marketing | Developer/etc | Now (when raising) |
| 138 | Podcast Tours | Audience-Specific | Q2+ |

### Activation (8 entries)

| # | Idea | Category | Typical stage available |
|---|---|---|---|
| 47 | Founder Welcome Email | Email | Q2+ (Activation use) |
| 48 | Dynamic Email Capture | Email | Q2+ |
| 51 | Onboarding Emails | Email | When UI is stable |
| 90 | One-Click Registration | Product-Led | Now |
| 91 | In-App Upsells | Product-Led | Q2+ (cross-cuts Revenue) |
| 95 | Concierge Setup | Product-Led | Q3+ (high-value users) |
| 96 | Onboarding Optimization | Product-Led | Now |
| 124 | App Store Optimization | Platforms | Now (App Store products) |

### Retention (8 entries)

| # | Idea | Category | Typical stage available |
|---|---|---|---|
| 45 | Mistake Email Marketing | Email | Opportunistic |
| 46 | Reactivation Emails | Email | Now |
| 50 | Inbox Placement | Email | Now (technical setup) |
| 52 | Win-back Emails | Email | Q1+ |
| 53 | Trial Reactivation | Email | Q2+ (when paywall is firing) |
| 94 | Offboarding Flows | Product-Led | Q2+ |
| 135 | Support as Marketing | Developer/etc | Q2+ |
| 134 | Certifications | Developer/etc | Q3+ (cross-cuts Referral) |

### Referral (5 entries)

| # | Idea | Category | Typical stage available |
|---|---|---|---|
| 62 | Affiliate Program | Partnerships | Now (when inbound exists) |
| 79 | Early-Access Referrals | Launches | Pre-launch / GA |
| 92 | Newsletter Referrals | Product-Led | Q3+ (if newsletter exists) |
| 93 | Viral Loops | Product-Led | Q3+ |
| 137 | Two-Sided Referrals | Audience-Specific | Q2+ |

### Revenue (2 entries — most monetization is strategy not tactic)

| # | Idea | Category | Typical stage available |
|---|---|---|---|
| 91 | In-App Upsells | Product-Led | Q2+ (cross-cuts Activation) |
| 132 | Price Localization | International | Q4+ |

> **Skipped from Revenue:** #86 Lifetime Deals appears under Launches (Acquisition section) only. It's generally off-brand for subscription products because it damages LTV math; recommend in Section 12's Skip list with rationale, not in stage totals.

### Cross-cutting / brand foundation (2 entries)

| # | Idea | Category | Typical stage available |
|---|---|---|---|
| 114 | Moneyball Marketing | Unconventional | Ongoing methodology |
| 139 | Customer Language | Audience-Specific | Now (foundational) |

### Developer-specific / dev tool products (2 entries)

| # | Idea | Category | Use when |
|---|---|---|---|
| 117 | Product Competitions | Unconventional | Developer tool products |
| 136 | Developer Relations | Developer/etc | Developer tool products |

## How to apply this to a specific client

For Section 12 of the plan:

### Step 1 — Filter for category fit

For each idea, ask:
- Does this idea apply to the client's category? (e.g., #16 Importers only for SaaS; #19 Chrome Extensions only for browser-relevant; #136 DevRel only for dev tools)
- Skip ideas that don't apply, with a note

### Step 2 — Filter for brand voice

For each idea, ask:
- Does this idea conflict with the client's brand voice?
- Common conflicts:
  - **Lifetime Deals (#86)** — conflicts with premium positioning
  - **Twitter Giveaways (#83)** — often off-brand for serious / clinical / luxury voices
  - **Humor Marketing (#122)** — off-brand for serious / clinical voices
  - **Cameo Marketing (#118)** — off-brand for most voices
  - **Reality TV Marketing (#112)** — off-brand for most voices

If conflict, place in Skip list with explicit rationale.

### Step 3 — Set timing status

For ideas that pass filters, set status:
- **Now (Q1)** — already in 90-day plan OR can run alongside without new capacity
- **Q2** — post-bedrock-fix, post-foundation; second-quarter layer-in
- **Q3+** — post-seed-close, post-GA; expansion moves
- **Q4+** — long-game / large-investment

Use the "Typical stage available" column as the default. Shift earlier if client has unusual capability (e.g., a celebrity founder shifts Conference Speaking #70 from "Now" to "Now and high-leverage").

### Step 4 — Write the client-specific note

Every "Now / Q2 / Q3+" idea gets a one-line client-specific note. Examples:
- For idea #11 Competitor Comparison Pages: "Quietude vs. Calm / Headspace / Brain.fm / Endel / Wavepaths — high-intent SERPs"
- For idea #133 Investor Marketing: "Alex's seed raise — leverage angel backchannel for PR + intros"
- For idea #15 Engineering as Marketing: "HRV interpretation guide; nervous system self-assessment; sound bath finder directory"

### Step 5 — Sum the bank

After all five AARRR tables + skip list:

```markdown
### Idea-bank summary

- {Acquisition count} ideas applicable to Acquisition (the dominant stage at {client}'s current stage)
- {Activation count} to Activation, {Retention count} to Retention
- {Referral count} to Referral
- {Revenue count} to Revenue
- {cross-cutting count} cross-cutting
- {skipped count} ideas skipped for brand / business-model fit

**What this proves:** the plan is roughly X% of the available tactical surface area, not 100%. {appropriate or not for the stage} — as capacity unlocks across Q2 → Q3 → Series A, the cross-reference becomes the inventory to scale activity without losing strategic coherence.
```

## How to maintain this doc

If `marketing-ideas` adds new ideas (it's a living skill — the 139 may become 145 or 160 over time):
1. Read `skills/marketing-ideas/references/ideas-by-category.md` in the `marketingskills` repo
2. Assign each new idea to a primary AARRR stage using the rules above
3. Add to this doc's tables
4. Update SKILL.md's idea-count reference

## Sources

- `skills/marketing-ideas/SKILL.md` (in the `marketingskills` repo)
- `skills/marketing-ideas/references/ideas-by-category.md` (in the `marketingskills` repo)


---

# references/measurement-framework.md

# Measurement Framework — KPIs, North Stars, Cadence

Every plan needs a measurement section that tells the team how to know if the plan is working. This doc is the source for Section 13's measurement subsection.

**Related docs:**
- `growth-patterns.md` — the 3-3-2-2-2 VC growth path (3× in years 1–2, 2× in years 3–7 from $1M ARR) and which phase of SaaS growth the company is in ($0–10K / $10K–100K / $100K–1M+)
- `budget-planning.md` — CAC calculation (blended, not paid-only) and the forecasting reality check (forecasts under $100M ARR are educated guesses, not precise predictions)

## The north-star principle

A north star is one metric that captures the business-model thesis at the highest level. It should:
- Be derivable from the funnel + revenue model
- Move slowly enough to be a strategic compass (not whipsawed by weekly noise)
- Trade off correctly against other metrics — improving the north star should generally improve the business

Don't default to "ARR" or "MRR" alone. Those are outcomes, not norths. Pick something that captures the business model.

## North-star patterns by business model

### B2B SaaS (subscription)
- **Net Revenue Retention (NRR)** — keeps existing customers + expansion in focus
- Alternative: "Logo retention × expansion ARR"
- Why: ARR alone hides churn / lets gross-add growth mask product fit problems

### D2C consumer app (subscription)
- **Blended LTV / blended CAC** — keeps unit economics honest as paid layer scales
- Alternative: "Day-35 paid users from cohort × LTV"
- Why: monthly subscription metrics are volatile; cohort × LTV smooths it

### Hybrid hardware + software (e.g., Quietude)
- **Blended LTV / blended CAC across hardware + software** — captures the wedge thesis
- Alternative: "Hardware-buyers-to-subscriber conversion × blended margin"
- Why: hardware revenue isn't free (cost to make); subscription revenue isn't expensive to acquire if hardware funds it

### Marketplace (two-sided)
- **Liquidity ratio × take-rate** — captures both sides + monetization
- Alternative: "Monthly transacting users × take-rate × repeat frequency"
- Why: GMV alone doesn't capture whether the marketplace is becoming a habit

### Developer tool / open source
- **Weekly active developers × paid-conversion** — captures both adoption and monetization
- Alternative: "Weekly active orgs × seats per org × ARPU"

### Content / media business
- **Daily active readers / listeners × ad revenue per session** — captures both reach and monetization
- Alternative: "Subscriber count × retention × ARPU"

### Commerce (DTC, non-subscription)
- **Repeat purchase rate × AOV × frequency** — captures monetization layered on quality of customer
- Alternative: "Customer LTV / CAC × payback period"

## Leading indicators by AARRR stage

After the north star, every plan needs leading indicators per AARRR stage. These move faster than the north star and trigger investigations.

### Acquisition leading indicators
- Organic visits/month, total + per pillar (SEO health)
- App Store / Play Store visit-to-install rate (ASO health)
- Founder-led social channel growth → email subscriber conversion (LinkedIn / X / Substack funnels)
- Event-to-app conversion rate (event ROI)
- Ambassador-attributed visits (referral funnel)
- Paid CAC by channel (when paid is firing)

### Activation leading indicators
- Day 1 / Day 7 / Day 35 → paid conversion rate
- Onboarding session-completion rate
- First key-action completion (post-signup activation event)
- App Store conversion rate (install → trial → paid)
- Trial → paid conversion rate

### Retention leading indicators
- Day 30 / Day 60 / Day 90 retention
- Monthly churn rate (gross + net)
- Lifecycle email engagement (open / click / unsubscribe by flow)
- Hardware → app activation rate (for hybrid businesses)
- Win-back / reactivation rate

### Referral leading indicators
- Ambassador-attributed new subs (via Dub or similar)
- Share-after-value moment rate (% of users sharing)
- Two-sided referral completion rate
- Guides program referrals (when live)
- NPS score (if surveyed)

### Revenue leading indicators
- ARPU by cohort
- Annual plan adoption %
- Cohort LTV by source
- Plan mix shifts
- Eye-mask / hardware attach rate (for hybrid)
- Expansion revenue (B2B)

## Review cadence

The plan should specify three rhythms:

### Weekly (operational sync)
- **Who:** fCMO ↔ founder (CEO usually)
- **Duration:** 30 min
- **Format:** AARRR scoreboard (current vs. last week numbers across the leading indicators) + this week's ships + blockers
- **Output:** Action items, decisions made

### Monthly (metrics review)
- **Who:** fCMO + founder + extended team (CXO, product lead, designer if applicable)
- **Duration:** 60–90 min
- **Format:** Full metrics review + comparison against quarterly KPI targets + qualitative learnings + idea bank reprioritization
- **Output:** Possible plan adjustments, hire decisions

### Quarterly (plan recalibration)
- **Who:** fCMO + founders + key advisors
- **Duration:** 2–3 hours
- **Format:** Full plan review against 90-day and 12-month outcomes, channel-level analysis, funding-stage transition check, recalibration of next 90 days
- **Output:** Updated plan (could be v2 / v3 document iteration)

## KPI target setting

For each quarter in Section 10, the plan must include 3–5 specific KPI targets. These should be:
- **Specific** — not "improve retention," but "Day 30 retention from 22% → 30%"
- **Measurable** — pull from a wired data source
- **Stretch but plausible** — based on funnel state + historical patterns
- **Decision-triggering** — if missed, what does that mean? (Adjust strategy, kill a channel, etc.)

### KPI target patterns by quarter

**Q1 (foundation quarter):**
- Mostly *bedrock* metrics — fixing leaks. "Headphones-gate conversion drop reverses." "Day 1 → paid +25–50%."
- Some *foundation* metrics — laying tracks. "4 SEO pillars staked." "App Store rewrite shipped."
- Avoid bold growth targets — the foundations aren't in yet

**Q2 (validation quarter):**
- Mostly *validation* metrics — does what we built work? "Paid CAC < $X blended." "Organic traffic 1,500–3,500/mo."
- Some *cohort* metrics — do new cohorts behave better? "Day 7 retention for Q2 cohort vs. Q1."

**Q3 (scaling quarter):**
- Mostly *scaling* metrics — how far does it go? "Paid scaling to $20–30K/mo with CAC steady." "First B2B install reference case live."
- Some *capability* metrics — what new things are live? "First Guides pilot launched."

**Q4 (compound quarter):**
- Mostly *compound* metrics — is the flywheel turning? "50%+ of new subs from non-paid channels." "Ambassador-driven 15–25% of new subs."
- Some *narrative* metrics — does the Series A story write itself? "Blended LTV/CAC > 3."

## Anchoring against the VC growth path

For VC-backed clients past $1M ARR, anchor 12-month and multi-year targets against the **3-3-2-2-2 rule** (3× in years 1 and 2, then 2× in years 3 through 7). Hitting it is rare; most companies don't. Anchoring against it forces the plan to either match it and show how, or explicitly defend choosing a slower trajectory. Full table and context in `growth-patterns.md`.

For non-VC-backed companies (bootstrapped, founder-funded, profit-focused), the 3-3-2-2-2 doesn't apply. Use linear-pattern targets ("$X MRR added per month") or step-function targets ("$Y revenue jump after the enterprise tier launches") instead.

## Forecasting reality check

A plan derives a budget and an annual goal. It does not produce a 12-month month-by-month forecast that's reliably accurate to the dollar.

**Unless the company is publicly traded, all forecasts are educated guesses.** No startup under $100M ARR consistently hits month-by-month forecasts. Quarterly review is when the plan adjusts — not when variance is treated as failure.

What the plan commits to honestly:
- The annual goal is a defensible direction-of-travel
- The budget is the resource commitment that makes the goal plausible
- The 90-day roadmap (Section 9) is what's actionable now
- Month-to-month projection is illustrative, not promised

Founders who over-engineer the forecast end up explaining variance every month instead of executing. The plan should resist this — name the annual target, the quarterly KPIs, and the kill criteria. Don't promise the month.

Full context in `budget-planning.md`.

## Kill criteria

For every channel or initiative, the plan should specify when to stop. Often missing from plans, kill criteria force discipline.

Examples:
- "If a paid channel has CAC > 2× target after 30 days at meaningful spend, pause."
- "If onboarding Variant 3 doesn't show statistically meaningful lift (or directional lift + congruent qualitative signal) after 4 weeks, move to Variant 1."
- "If lifecycle Flow 4 has open rate < 12% after 6 weeks, redo subject lines + audience segmentation."

## Guardrail metrics

Some metrics get a hard guardrail (cannot drop below threshold). Useful for protecting brand or unit economics during aggressive growth.

Examples:
- "Brand voice complaint rate > 1% of customer feedback triggers content review."
- "Paid CAC > $X for two consecutive months pauses paid scaling pending audit."
- "App Store rating drops below 4.5 triggers product review."

## Data sources mapping

The plan should name where each metric comes from. This makes it auditable.

| Metric | Source |
|---|---|
| Organic traffic | GA4 / Ahrefs |
| App Store conversion | App Store Connect |
| Funnel conversion (Day N → paid) | Internal analytics (Mixpanel / Amplitude) or App Store Connect cohort export |
| Retention | Customer.io segments + product analytics |
| MRR / ARR | Stripe (via MCP if wired) |
| Plan mix | Stripe |
| Lifecycle email metrics | Customer.io |
| Ambassador attribution | Dub.co |
| Hardware → app activation | Shopify + App Store + internal join |
| NPS | Survey tool (Customer.io / Typeform / SurveyMonkey) |

## When data isn't wired

If a metric can't currently be measured, flag it in Section 13's open decisions. Example:

> "Hardware → app activation rate not currently visible in the App Store dashboard. Requires Shopify ↔ App Store Connect join. Q1 work item."

A plan with un-measurable goals is a plan that can't be validated. Surface the instrumentation work explicitly.

## Reporting cadence + automation

Where possible, auto-generate the metrics review rather than building it manually each time. Stripe MCP + GA4 MCP + Customer.io MCP can pull most of what's needed.

For Tier 1 clients, a simple weekly metrics email to the team (Markdown table, generated via skills + MCPs) costs nothing and creates discipline.

For Tier 2+ clients, consider a real dashboard (Hex, Metabase, Looker, or internal tool).


---

# references/methodology.md

# Methodology — How a Marketing Plan Gets Made

The three-phase workflow that produces a comprehensive marketing plan. SKILL.md is the orchestration layer; this is the operational detail.

## Phase 1 — INIT (research + intake)

**Goal:** Walk into Phase 2 with enough context to draft every section without guessing.

### Step 1.1 — Set up the plan folder

Canonical file layout for every plan:

```
~/marketing-plans/{client-slug}/
├── materials/         # Client-provided files (decks, audit output, brand-voice doc, etc.)
├── research.md        # Written in Phase 1 (INIT)
├── progress.md        # State machine — see Step 1.1.1 for schema
├── sections/
│   ├── 01.md          # Executive summary (written last, ordered first)
│   ├── 02.md          # Strategic frame
│   ├── ...
│   └── 13.md          # Measurement, RACI, open decisions, appendix
└── final_plan.md      # Compiled deliverable (Phase 3 output)
```

### Step 1.1.1 — `progress.md` state schema

Every plan tracks a single `progress.md` file at the plan root. It's the source of truth for resumption. Schema:

```markdown
# {Client} — Marketing Plan Progress

phase: init | review | finalize | finalized
current_section: <number, only meaningful during review phase>
plan_version: v1
last_updated: YYYY-MM-DD HH:MM

## Sections completed
- [ ] 2. Strategic frame
- [ ] 3. Current state
- [ ] 4. Acquisition
- [ ] 5. Activation
- [ ] 6. Retention
- [ ] 7. Referral
- [ ] 8. Revenue
- [ ] 9. 90-day roadmap
- [ ] 10. 12-month outlook
- [ ] 11. Marketing operations stack
- [ ] 12. Tactical idea bank
- [ ] 13. Measurement, RACI, open decisions, appendix
- [ ] 1. Executive summary (synthesized last)

## Approved artifacts
sections/02.md, sections/03.md, ... (list as they're written)

## Notes
<any open decisions, blockers, or out-of-band context that aren't in research.md>
```

### Step 1.1.2 — Resumption decision tree

On every invocation, check state in this order:

1. **No `{client-slug}/` folder** → fresh plan. Create folder + `materials/` + empty `sections/`. Start INIT (Step 1.2).
2. **Folder exists, no `research.md`** → INIT was interrupted. Resume from Step 1.2.
3. **`research.md` exists, no `progress.md`** → INIT done, REVIEW not started. Create `progress.md`, start REVIEW from Section 2.
4. **`progress.md` exists, `phase: review`** → REVIEW in progress. Resume from `current_section` (or first unchecked box).
5. **`progress.md` exists, `phase: finalize`** → FINALIZE was interrupted. Re-run Phase 3.
6. **`progress.md` exists, `phase: finalized`** → plan is done. **Do not silently overwrite.** Ask the user: *"This plan is finalized (v{N}). Want to (a) revise it as v{N+1}, (b) start a fresh plan in a new folder, or (c) re-open a specific section?"*

Update `phase` and `last_updated` whenever state changes.

### Step 1.2 — Read existing materials

If `materials/` has files, read all of them. Common drops:
- Pitch deck / investor deck
- Positioning doc / brand voice doc
- Customer research / ICP doc
- App Store metrics / analytics snapshot
- Lifecycle email inventory
- Prior audit output (any scored current-state assessment the team has run)
- SEO research (`seo/plan.md`, `seo/keyword-shortlist.md`)
- Kickoff call transcript
- Founder Slack / async notes

Read everything. Capture key facts to `research.md` as you go.

### Step 1.3 — Pull live data where wired

If MCPs/APIs are wired for this client, pull:

- **Ahrefs** → domain rating, organic keywords, backlinks, top pages, ref domains (per `/seo-audit` skill)
- **GA4 MCP** → traffic by channel, conversion events, retention curves
- **Stripe MCP** → MRR, ARR, churn, plan mix, blended LTV by cohort
- **App Store Connect** (manual or `dev-browser`) → install → trial → paid funnel; cohort retention
- **Customer.io MCP** → flow inventory, send / open / click / unsubscribe rates
- **Shopify** → product page conversion, AOV, repeat rate
- **GitHub MCP** → repos inventory, last commit dates, what's stale
- **Notion** → internal knowledge directory if exposed

Don't ask the user to copy/paste data that can be pulled directly.

### Step 1.4 — Conduct structured intake

For every gap in the materials, ask the user. The minimum intake covers ten topics:

#### Intake 1 — Client overview
- What does the company do, in one sentence (founder's words)?
- What's the primary product?
- What other products / SKUs / tiers exist?
- Is the product live, beta, or pre-launch?
- If beta: throttling? GA timeline?

#### Intake 2 — ICP
- Who are you for, in one sentence?
- What do they say they want?
- What do they actually want?
- What's their stated problem? Their real problem?
- Demographics / firmographics: who fits the ICP exactly?

#### Intake 3 — Funnel state today
- What are the current funnel numbers? (signups, activations, paid, retention)
- What's the funnel *shape* — is it bottle-necked at top, middle, or bottom?
- What's the biggest leak?

#### Intake 4 — Funding state
- Current round (pre-seed / seed / Series A / etc.)?
- Total raised to date?
- Current burn / runway?
- Active raise? Closing when?
- Investors of note?
- Permission to mention fCMO engagement in pitches?

#### Intake 5 — Team
- Founders and what each owns (product, marketing, sales, etc.)?
- Other roles on the team and their marketing surface area?
- Advisors who touch marketing?
- Agencies / contractors / fractionals?
- Where are the obvious gaps?
- For the team's current marketing owner (if there is one): is the shape π-shaped (two deep skill sets), T-shaped (one deep, broad), or tactical-only? See `team-and-agency-model.md` for the framework that informs Section 11 RACI and the first-hire recommendation in Section 9.

#### Intake 6 — Budget
- Current monthly marketing spend, broken down: paid acquisition, tools, retainers, headcount?
- Budget tier this maps to (see `funding-stage-unlocks.md`)?
- What budget unlocks when the next round closes?
- Blended CAC if known (including salaries, content costs, tools, retainers — not just paid ad spend). If unknown, flag as the top Section 13 open decision — every revenue projection depends on it.
- ARPC, annual retention rate (or churn rate), so the budget math in `budget-planning.md` can be applied to Section 8 (Revenue) and Section 10 (12-month outlook).

#### Intake 7 — Channels currently active
- Acquisition: organic SEO, paid search, paid social, content, social, partnerships, events, PR, ambassadors, etc. — for each, status (live / paused / never tried)
- Activation: onboarding state, signup flow, paywall, first-session experience, app store listing
- Retention: lifecycle email state, in-app upsells, churn cohort
- Referral: program existence, attribution, inbound interest
- Revenue: pricing structure, plan mix, recent experiments

#### Intake 8 — Already done
What past work should this plan acknowledge?
- Major launches and dates
- PR moments and who covered
- Content pillars / hubs / cornerstone pieces
- Partnerships
- Awards / certifications
- Notable customers / users (if consumer-named users)
- Past advisors / fractionals

#### Intake 9 — In-flight and stuck
- What's drafted but not shipped? Why?
- What's been "almost ready" for months?
- What's blocking each?
- What's broken or actively harmful?

#### Intake 10 — Strategic posture
- The most important thing to fix this quarter (founder's read)
- The most important thing to ignore this quarter (founder's read)
- What investors / board are asking about most
- Any constraints not visible elsewhere (legal, partnership-related, brand-related)

### Step 1.5 — Score current state against the rubric

Use the 17-section rubric in `references/current-state-rubric.md` as your scoring lens. Two modes:

- **From rich materials.** When the team has shared decks, prior content audits, an existing brand voice doc, recent positioning work, or a kickoff call transcript — score from those. Mark "scored from materials" in the section heading.
- **From a separately scored audit.** If the team already has a scored current-state assessment (in any format), ingest those numbers directly. Don't redo the work.

Either way, the output is the scored 17-row table that becomes Section 3 of the plan, followed by a 2–4 sentence "shape interpretation" calling out where strengths and gaps cluster.

### Step 1.6 — Write research.md

Compile everything into `research.md` with this structure:

```markdown
# {Client} — Marketing Plan Research Record

**Date:** YYYY-MM-DD
**Author:** (fCMO / planner name)

## Company snapshot
- One-sentence description
- Stage (pre-seed / seed / Series A / etc.)
- Product status (beta / GA)

## ICP
- Primary ICP
- Stated vs. actual problem
- Demographics / firmographics

## Funnel state today
- Current numbers
- Funnel shape
- Biggest leak

## Funding
- Total raised
- Current round status
- Runway

## Team
- Founders and ownership
- Marketing surface area by person
- Gaps

## Current marketing budget
- $/mo total
- Breakdown
- Tier mapping

## Channels currently active
[By AARRR stage]

## Already done (acknowledge in plan)
[List]

## In-flight and stuck
[List with blockers]

## Strategic posture
- Founder's top priority
- Founder's top de-prioritization
- Investor pressure points
- Constraints

## Current-state rubric scores
[17 section scores using `references/current-state-rubric.md`. If a prior scored audit exists, paste those scores. Otherwise mark "scored from materials."]

## Materials read
[List of files in materials/ + when read]
```

Save. Move to Phase 2.

---

## Phase 2 — REVIEW (section-by-section drafting)

**Goal:** Walk through all 13 sections of the plan template (`references/plan-template.md`), drafting each, getting user confirmation, saving as you go.

### Step 2.1 — Initialize progress.md

Use the schema defined in Step 1.1.1 above. Set `phase: review`, `current_section: 2`, `plan_version: v1`, and stamp `last_updated`.

### Step 2.2 — Walk each section in this order: 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, then 1

Section 1 (Executive Summary) is drafted **last** because it depends on every other section's conclusions. Walk Sections 2 → 13 in numeric order, then synthesize Section 1 from the others. The final compiled `final_plan.md` is always presented in canonical order 1 → 13.

For each section, use the template at `references/plan-template.md` to draft. Then in chat:

1. Present the draft (or key bullets — short sections inline, long sections as bullet outline first)
2. Ask: *"Approve, adjust, or expand?"*
3. Iterate until user confirms
4. Save the confirmed text to `sections/01.md` ... `sections/13.md` (one file per section, zero-padded for sort order). This is the canonical persisted artifact — recovery depends on it.
5. Check the box in `progress.md`
6. Move to next section

### Step 2.3 — Section-specific guidance

**Section 1 (Executive summary)** is synthesized from Sections 2–13 after they're all approved. Draft it last; present it first in the output document.

**Section 3 (Current state)** uses the embedded 17-section rubric in `references/current-state-rubric.md`. If a prior scored audit exists, paste those scores in. If not, score from available materials.

**Sections 4–8 (AARRR)** each follow the same internal structure: current state, the plan (numbered moves), 90-day moves, 12-month outlook, skills + tools. Don't skip the skills + tools sub-section — it's what makes the plan operationally honest.

**Section 11 (Marketing operations stack)** is auto-generatable from `references/ops-stack-mapping.md` plus the specific moves named in Sections 4–8.

**Section 12 (Idea bank)** is auto-generatable from `references/idea-cross-reference.md` plus client-specific filters (skip ideas that conflict with brand voice; status moves based on funding-stage timing).

**Section 13** lives at the end. Open decisions should be ranked by impact. Appendix should reference only files the team can access (warn about machine-local paths).

### Step 2.4 — Brand voice consistency

If the client has documented brand voice rules (captured in research.md / Section 2), every section must respect them. Common voice constraints:
- Vocabulary rules (YES / NO lists)
- CTA rules (e.g., "never pressure")
- Initiatory vs. explanatory framing
- Tone (e.g., authoritative-yet-accessible, intimate-yet-professional)

If a section's draft violates the brand voice, redo it before showing it to the user.

---

## Phase 3 — FINALIZE (compile + verify + publish)

**Goal:** Produce `final_plan.md` and optionally publish to a shared repo.

### Step 3.1 — Compile

Set `phase: finalize` in `progress.md` before starting. Concatenate `sections/01.md` through `sections/13.md` into `final_plan.md` (canonical order 1 → 13, regardless of drafting order). Add:
- Title header with date and "v1" version marker
- "Prepared by / For / Date / Status" frontmatter
- Section anchors that work in Notion paste

### Step 3.2 — Verification pass

Before printing:

- **Cross-reference check** — every marketing-ideas number (e.g., "idea #17") matches the actual idea in `references/idea-cross-reference.md`. Every related-skill mention either exists in the `marketingskills` repo or is documented as an external dependency (see ops-stack-mapping note on cross-marketplace skills).
- **MCP/API check** — every tool mentioned in Section 11 actually exists in the user's stack (per research.md intake) OR is flagged as "future / not yet wired."
- **Path check** — no machine-specific paths (`/Users/...`, `/home/...`) in the output. Replace with descriptive references.
- **Voice check** — final read against brand voice rules. Flag and fix violations.
- **Open-decisions check** — every "TBD" or unanswered question from intake is listed in Section 13's open decisions, not hidden in the body.
- **Acknowledge check** — every item from "already done" in research.md is acknowledged somewhere in the plan.

### Step 3.3 — Print

Output `final_plan.md` to the plan folder. Print a summary to chat:

> *"Marketing Plan v1 saved to `~/marketing-plans/{client-slug}/final_plan.md`. ~X,XXX words across 13 sections. Ready to paste into Notion or share with the team."*

### Step 3.4 — Publish (optional)

Ask the user:
> *"Want me to publish this to a shared GitHub repo so the team can access it? If yes, what's the target repo and path (e.g., `{client-org}/{client-context}/marketing/plan.md`)?"*

If yes:
- Clone (or assume cloned) target repo
- Check out a feature branch or push direct to main per user's preference
- Copy `final_plan.md` to the target path
- Adjust the appendix to use repo-relative paths (not machine paths)
- Commit + push
- Confirm with commit URL

If no: leave it local. Done.

### Step 3.5 — Mark finalized

Set `phase: finalized` in `progress.md` and stamp `last_updated`. This is the terminal state and prevents future `/marketing-plan` invocations from silently overwriting the plan (see Step 1.1.2 case 6).

---

## Resuming a plan

Resumption is governed entirely by the decision tree in Step 1.1.2 above — always check state in that order on every invocation.

If the user says *"start over"* → ask whether they want to delete the existing folder or move it to `archive/` first; don't silently overwrite.
If the user says *"redo Section X"* → uncheck that box in `progress.md`, delete `sections/0X.md`, and re-draft.

## Failure modes to watch for

- **Skipping intake.** A plan written without proper intake is generic and won't survive contact with the founder. Always do the full ten-topic intake unless the user explicitly waives it.
- **Pretending data exists.** If you can't confirm a number (current MRR, retention rate, etc.), don't guess. Mark it `[TBD — to confirm with team]` in the plan and add to open decisions.
- **Ignoring the brand voice.** If the client has a strong voice (most do), every section must respect it. Read the voice rules before drafting any copy-adjacent text.
- **Padding the idea bank.** Section 12 is comprehensive only if it includes the skip list with reasons. Don't pad with ideas that clearly don't fit just to hit the 139.
- **Glossing over uncomfortable metrics.** If churn is high or activation is low, name it in Current State. Founders read past sugar-coating.
- **Forgetting funding-stage logic.** If the client is mid-raise, the plan must explain what changes when the round closes. Skipping this turns a plan into a wish-list.


---

# references/ops-stack-mapping.md

# Marketing Operations Stack — Skills + MCPs per AARRR Stage

This doc maps every marketing-skill and every relevant MCP/API integration to the AARRR stage(s) it primarily serves. It's the source for Section 11 of every plan.

> **Note on scope.** Skills below live in this `marketingskills` repo. A few references point to optional tools from adjacent Claude Code marketplaces (e.g., `vercel:agent-browser`, `compound-engineering:diagram-maker`) — substitute equivalents if not installed. When a plan references a skill or tool that isn't available, fall back to the underlying tactic and call it out in Section 13's open decisions.

## The thesis

A small team + fCMO + agentic tooling = output of a 15–20-person traditional marketing org. The skills + MCPs encode workflows that previously required dedicated headcount per channel.

The plan's Section 11 makes this thesis explicit by:
1. Mapping skills to stages so the founder sees which skills execute which work
2. Mapping MCPs/APIs to stages so the founder sees the tooling layer
3. Naming a concrete operational example that proves the stack works
4. Showing capability unlocks by funding stage (pre-seed → seed → Series A)

## Marketing skills mapped to AARRR

### Acquisition skills

| Skill | What it does | Primary use in Acquisition |
|---|---|---|
| `seo-audit` | Audit site for technical and on-page SEO | Quarterly site health checks |
| `ai-seo` | Optimize content for AI search engines / LLM citation | Future-proof content strategy |
| `programmatic-seo` | Build template-driven SEO pages at scale | Location, comparison, integration page systems |
| `schema` | Add structured data markup | Rich snippets, eligibility for AI citation |
| `content-strategy` | Plan content topics, pillars, cadence | Setting the editorial calendar |
| `competitors` | Build vs-pages and alternative-to-pages | Capture high-intent SERPs against competitors |
| `ads` | Plan and structure paid campaigns | Apple Search Ads, Meta, Google, LinkedIn |
| `ad-creative` | Generate ad variations and creative | Iterate ad creative across platforms |
| `social` | Plan and write social media content | LinkedIn, Twitter/X, Instagram, TikTok |
| `typefully` | Schedule/post tweets, threads, LinkedIn content | Cadence operations for founder-led channels |
| `cold-email` | Write B2B cold outreach + sequences | Outbound for B2B SaaS / hybrid businesses |
| `analytics` | Set up tracking, GA4, conversion events | Funnel instrumentation |
| `free-tools` | Plan engineering-as-marketing free tools | Build tools that generate links + leads |
| `marketing-website-design` | Design marketing sites with intention | Pillar/landing page design |
| `launch` | Plan and execute launches (Product Hunt, GA, feature launches) | GTM moments — strategy + tactical execution |

### Activation skills

| Skill | What it does | Primary use in Activation |
|---|---|---|
| `onboarding` | Optimize user onboarding flows | Onboarding rebuild, activation rate tests |
| `signup` | Optimize signup/registration | Reduce friction at top of activation |
| `cro` | Optimize any marketing page or form | Conversion testing across pages, forms, landing pages |
| `paywalls` | Optimize paywalls and upgrade screens | Trial → paid conversion (also Revenue) |
| `popups` | Optimize popups, modals, slide-ins | Lead capture + activation prompts |
| `copywriting` | Write marketing copy | Onboarding screens, paywall copy, CTAs |
| `copy-editing` | Edit and improve existing copy | Voice / clarity pass before ship |
| `copycraft` | Real-time copy variation overlay | Live copy iteration during reviews |
| `website-copy` | Write full website copy (stage-8 from CF process) | Comprehensive site copy production |
| `ab-testing` | Plan A/B tests | Structure for onboarding variant tests |
| `marketing-psychology` | Apply behavioral science to copy and CRO | Persuasion principles in activation moments |

### Retention skills

| Skill | What it does | Primary use in Retention |
|---|---|---|
| `emails` | Design email sequences | Customer.io / Mailchimp / Resend flow building |
| `churn-prevention` | Build cancellation flows, save offers, win-back | Reduce churn, recover failed payments |
| `copywriting` / `copy-editing` | Email copy production | Lifecycle email content |
| `paywalls` | (cross-cuts) — upgrade prompts in retention emails | Upsell within lifecycle |
| `ab-testing` | Test email variants | Subject line, CTA, timing tests |

### Referral skills

| Skill | What it does | Primary use in Referral |
|---|---|---|
| `referrals` | Plan and launch referral / affiliate / ambassador programs | Core skill for Section 7 |
| `social` | Create ambassador-shareable content | Talking points, post templates |
| `copywriting` | Ambassador / affiliate email copy | Recruitment, onboarding, communication |
| `marketing-website-design` | Per-ambassador landing pages | Attribution surface |
| `emails` | Ambassador lifecycle emails | Onboarding, monthly digest, payout notifications |

### Revenue skills

| Skill | What it does | Primary use in Revenue |
|---|---|---|
| `pricing` | Audit and optimize pricing | Plan tier structure, annual defaults, value metrics |
| `paywalls` | Paywall optimization | Trial → paid, free → paid conversion |
| `sales-enablement` | Build sales decks, one-pagers, demos | B2B sales support material |
| `revops` | Revenue operations, lead lifecycle | Marketing → sales handoff |
| `ab-testing` | Pricing experiments | Test annual default, intro pricing, tier consolidation |

### Cross-cutting / brand foundation skills

| Skill | What it does | Primary use |
|---|---|---|
| `product-marketing` | Set up the `.agents/product-marketing.md` context file (positioning, ICP, voice) | Foundational — run first; every section of the plan references this |
| `customer-research` | Conduct customer interviews + surveys | Section 2 + Section 3 (Current state) |
| `marketing-psychology` | Apply behavioral science | Cross-cuts copy, CRO, paywalls |
| `marketing-ideas` | The 139-idea library | Section 12 of plan (Idea bank) |

## MCPs and APIs mapped to AARRR

### Acquisition tooling

| Tool | What it provides | Wired-at-client check |
|---|---|---|
| **Ahrefs API** | SEO data: keyword research, backlinks, competitor analysis | Required `AHREFS_API_KEY` in `.env` |
| **DataForSEO API** | SERP data, keyword volume, competitor SERP analysis | Required API key |
| **GA4 MCP** | Traffic by channel, conversion events, retention curves | Wired via gcp project + service account |
| **GitHub MCP** | Repo work: marketing site (`site-name-promo` patterns), content authoring | Standard `gh` CLI auth + MCP server |
| **Typefully MCP** | Social posting (LinkedIn, X, Threads, Bluesky) | Typefully account + API key |
| **Google Ads MCP** | Ad account management, campaign creation, performance pulls | Wired post-budget-unlock |
| **agent-browser** | Browser automation (form fills, screenshots, scraping) | CLI install: `npm install -g agent-browser` |
| **dev-browser** | General-purpose browser automation | MCP server install |
| **defuddle** | Clean markdown extraction from web pages | CLI install |
| **Notion** | Internal knowledge directory access | Notion API key |
| **Stripe MCP** | LTV math, paid-CAC reconciliation (cross-cuts to Revenue) | Stripe account + restricted key |

### Activation tooling

| Tool | What it provides |
|---|---|
| **App Store Connect** | Conversion rate by listing variant, install funnel | Usually manual + `dev-browser` for screenshots |
| **GitHub MCP** | Mobile app repo for onboarding code edits |
| **Figma / Pencil MCP** | Onboarding screen design + iteration |
| **Customer.io MCP** | In-app messaging + lifecycle email coordination |
| **Stripe MCP** | Subscription state for paywall logic |
| **GA4 MCP** | Activation events instrumentation |

### Retention tooling

| Tool | What it provides |
|---|---|
| **Customer.io MCP** | The retention infrastructure — flow building, segmentation, sending |
| **Shopify** | Hardware buyer events as lifecycle triggers |
| **Stripe MCP** | Subscription state, churn cohorts, plan changes |
| **GA4 MCP** | Session events, retention curves |
| **Resend / Mailchimp / SendGrid** | Alternatives to Customer.io for different stacks |

### Referral tooling

| Tool | What it provides |
|---|---|
| **Dub.co** | Ambassador attribution, short links, per-ambassador tracking |
| **Stripe MCP** | Commission accounting + payouts via Connect |
| **GitHub MCP** | Per-ambassador landing pages |
| **Customer.io MCP** | Ambassador lifecycle (recruitment → onboarding → monthly digest → payout notifications) |
| **Rewardful / Tolt / Mention Me** | Alternatives to Dub for affiliate management |

### Revenue tooling

| Tool | What it provides |
|---|---|
| **Stripe MCP** | Pricing tests, subscription analytics, churn cohort analysis, blended CAC math |
| **Shopify** | Hardware transactions |
| **GA4 MCP** | Revenue events |
| **Customer.io MCP** | Paywall / pricing-related lifecycle |
| **Notion** | Commercial knowledge directory |

### Cross-cutting tooling

| Tool | What it provides |
|---|---|
| **Notion** | Shared knowledge base |
| **GitHub MCP** | Shared context repo (`{client-org}/{client-context}`) |
| **defuddle** | Research extraction |
| **obsidian-cli** | Working notes for fCMO |
| **Pencil MCP** | Design files |
| **Figma MCP** | Design files (if Figma) |

## Capability unlocks by funding stage

The plan's Section 11 must include this table (or equivalent), specific to the client's current and projected funding stages.

| Stage | Headcount | Tooling | Channels live |
|---|---|---|---|
| **Pre-seed / bootstrapped** | fCMO + founder team | All current tooling + marketing-skills library + MCP layer | Organic only (SEO, content, App Store, founder-led social, events, WOM, ambassador) |
| **Seed close** | + first marketing hire (lifecycle/content owner) | + paid ad accounts (Apple Search Ads, Meta, LinkedIn) + `ads` skill activated | + paid acquisition pilot ($5–15K/mo — see `funding-stage-unlocks.md` for canonical tiers) |
| **Seed deployment** | + designer (potentially fractional) | + analytics expansion (Mixpanel / Amplitude if needed) | + paid scaling ($20–50K/mo) + first launches (PH, GA) |
| **Series A** | + performance marketing lead + content lead | + dedicated tooling spend ($2–5K/mo software) + sponsored event budget | + paid scaling ($50–150K/mo) + international consideration + B2B vertical expansion |
| **Series B+** | Full-stack marketing org (10+ people) | + agency partnerships + PR firm | + brand campaigns + acquisitions + sponsorships at category level |

## The concrete-example test

Section 11 of the plan must include at least one concrete operational example that proves the stack thesis. The example should be:
- A specific event (not abstract claim)
- From this client's actual history if possible (most credible)
- Tied to a non-technical person executing via the stack (proves it works without dedicated engineering)

Examples from real engagements:
- *"On the kickoff call, Alex drafted a working Customer.io abandoned-cart flow live, using Customer.io's Claude MCP. Validated that a non-technical founder can ship lifecycle work using the skill pattern independently."*
- *"In two weeks, the team scaled from 0 to 14 ranking keywords using `programmatic-seo` against the Ahrefs API + GitHub MCP — no dedicated SEO hire required."*
- *"The first email campaign generated a 24% reply rate after `cold-email` skill + GA4 MCP + Stripe MCP gave the team a verified target list of users with high LTV but no recent activity."*

If the client has no such moment in their history yet, frame the example as the *first move* — "Here's the demonstration the team will run in week one to validate the stack:"

## When the stack doesn't apply (yet)

For clients without MCP connections set up, frame Section 11 differently:
- List the skills that DO apply with current tooling
- Name which MCPs would unlock which sections of the plan
- Treat MCP setup as a Q1 priority alongside the bedrock fixes

A plan can't claim the agentic-stack thesis if the stack isn't wired. Be honest about state.


---

# references/plan-template.md

# Plan Template — The 13-Section Structure

The canonical template for every marketing plan generated by this skill. Each section has a purpose, a structure, and inline prompts for what to draft.

The Quietude plan (see `references/example-quietude.md`) is the canonical reference implementation.

---

## Title block

```markdown
# {Client} — Marketing Plan v1

**Prepared by:** {Author / fCMO name}
**For:** {Founders / leadership team}
**Date:** YYYY-MM-DD
**Status:** Draft v1 — for team review
```

---

## Section 1 — Executive summary

**Purpose:** Lift-and-share. A founder should be able to paste this into a board update or investor email without editing.

**Length:** 400–700 words. Tight.

**Structure:**
1. **One-sentence frame.** What does this plan optimize for? Not "more revenue" — something specific to this client at this stage.
2. **Three big bets, ranked by leverage.** Each is a paragraph. Bet = a high-conviction thesis about where the team should focus capital and attention.
3. **What twelve months looks like, plausibly.** Bullet list. The plausible outcome state at end of plan horizon. Investor-readable.
4. **90-day priorities.** Numbered list. The six (give or take) moves that ship in the first quarter.

**Voice notes:**
- Match the client's voice
- Direct, founder-readable, no marketing-speak
- Use names and numbers (specific channels, specific metrics) — not abstractions
- Tradeoffs named explicitly when they matter

---

## Section 2 — Strategic frame

**Purpose:** Distill positioning, ICP, business-model logic, and brand voice into a single page that any team member or new hire can read to orient.

**Length:** 800–1500 words.

**Structure:**

### What {Company} is, in one sentence
Pulled from positioning doc / seed deck / founder language.

### The category we're claiming
Is the company creating a new category, redefining an existing one, or competing in a defined category? Name it. State the category-defining frame in 2–3 sentences. Reference the source (founder's words, ICP doc, etc.).

### Who we're for (ICP, distilled)
Demographics / firmographics + stated problem vs. real problem + what they're actually buying. Tight, 4–6 bullets.

### The business model logic
How does the company make money? What's the customer-acquisition unit economics theory? What's the compounding channel thesis (if any)? Pulled from seed deck / financial model / founder narrative.

### Brand voice (the non-negotiable)
If the client has documented voice rules, list them. YES / NO vocabulary. CTA rules. Tone. Core method (initiatory, explanatory, narrative, etc.). Every other section of the plan must respect these.

**Voice notes:**
- This section is the most "lift from existing materials" — don't invent positioning. Surface what's there.
- If positioning is unclear or contradicted across materials, flag it in Section 13's open decisions.

---

## Section 3 — Current state

**Purpose:** Anchor the plan in reality. What's the team, budget, in-flight work, and stuck work *today*?

**Length:** 1000–2000 words.

**Structure:**

### Team composition (marketing surface area)
Table of every person with marketing surface area:

| Person | Role | Marketing surface area |
|---|---|---|

Be honest about gaps. If there's no dedicated marketing hire yet, name when one becomes necessary and what role (see `references/team-and-agency-model.md` — first hire should be π-shaped strategist titled Manager or Lead, not VP/CMO).

### Marketing budget (current)
- Paid acquisition: $X/mo
- Tooling stack: list with estimated cost
- Retainers / fCMO: list
- Headcount: list
- Blended CAC: $X (must include salaries, content costs, tools, retainers — not just paid spend; see `references/budget-planning.md` for the calculation)
- Current spend as % of ARR: X% (compare against 5–40% range)

State the funding-stage tier this maps to (see `references/funding-stage-unlocks.md`). Implication: what 90-day plan must produce *without* lever pulls that require future budget.

### Phase of SaaS growth
Name the current phase: $0–10K ARR / $10K–100K / $100K–1M / $1M–$10M / $10M+. Each phase has its own binding constraint and dominant growth pattern (see `references/growth-patterns.md`). Section 10 sequences the move into the next phase.

### What's already done (acknowledge, then build on)
Table:

| Asset | Status | Marketing leverage |
|---|---|---|

This is where past launches, PR moments, content pillars, certifications, notable users get acknowledged. **Critical**: don't write a plan that ignores work the team is proud of.

### What's in-flight (drafted but not shipped)
Table:

| Item | Status | Blocker |
|---|---|---|

Be honest about blockers. Where the blocker is "no time" or "no decision," that goes to Section 13's open decisions.

### What's stuck (and needs to unstick this quarter)
Table:

| Issue | Cost of inaction | Action |
|---|---|---|

Stuck things are the most leverage-positive places to focus the first weeks of the 90-day plan.

### Audit rubric snapshot
17-section scored snapshot using the embedded current-state rubric. See `references/current-state-rubric.md` for the full rubric and scoring guides.

If a prior scored audit exists, paste those scores in. Otherwise score from available materials and note "scored from materials" under the heading.

| # | Section | Score | Note |
|---|---|---|---|
| 1 | Positioning | 0–5 | |
| 2 | Customer research | 0–5 | |
| ... | ... | ... | ... |
| 17 | Internationalization | 0–5 | |

**Total: X / 85 (Y%).** Note the *shape* of strength and weakness — that shape is the gap the rest of the plan closes.

**Voice notes:**
- Honest > polished. If the client's metrics are bad, name them. Founders read past sugar-coating.

---

## Section 4 — Acquisition

**Purpose:** Answer "how do strangers become aware of us?" Map every channel: current state, planned moves, skipped (with reason).

**Length:** 1000–1800 words.

**Structure:**

### Current state
Brief. What's working today, what's not, what the data shows about channel mix.

### The plan
Numbered "Moves." Each move is a paragraph (3–6 sentences) describing the channel, the thesis, and the specific work. Common moves:

- **Move 1 — SEO (and content)** — Reference the SEO plan if one exists (`seo/plan.md`). Otherwise: keyword research, pillar/spoke structure, content cadence.
- **Move 2 — App Store / Play Store optimization** (for consumer apps) — Listing rewrite, screenshot tests, ASO keyword targeting.
- **Move 3 — Founder-led channels** — LinkedIn for B2B/SaaS, Twitter/X for tech, Instagram for consumer. Cadence, topics, owners.
- **Move 4 — PR amplification** — What's the credibility anchor? How to amplify it.
- **Move 5 — Events (if applicable)** — Live events, conferences, webinars. Acquisition vs. activation role.
- **Move 6 — Hardware / commerce surface (if applicable)** — Shopify storefront, Amazon, retail.
- **Move 7 — B2B sales support** — Case studies, partner pages, vertical-specific content.
- **Move 8 — Paid layer (when budget unlocks)** — Apple Search Ads, Meta, LinkedIn, Google. Held until specified funding stage.

### 90-day acquisition moves
Week-by-week breakdown of the ships in the first quarter.

### 12-month acquisition outlook
Quarter-by-quarter outcome state (Q1 / Q2 / Q3 / Q4).

### Skills + tools
- **Skills:** list relevant marketing-skills repo skills (`seo-audit`, `ai-seo`, `ads`, `social`, `competitors`, etc.)
- **MCPs / APIs:** list connections (Ahrefs API, GA4 MCP, Typefully MCP, Stripe MCP for LTV math, etc.)

---

## Section 5 — Activation

**Purpose:** Answer "once someone tries us, do they have an experience that converts?"

**Length:** 800–1500 words.

**Structure:** Same as Acquisition (Current state / The plan / 90-day / 12-month / Skills + tools).

**Common moves:**
- Bedrock fixes (broken signup, broken onboarding gates, etc.)
- Onboarding tests / rebuild (often the most leveraged move at this stage)
- App Store listing rewrite (cross-references to Acquisition)
- Lifecycle Flow ship order (when to ship onboarding emails vs. hold for product stability)
- Paywall + pricing review (often Activation × Revenue)

### Skills + tools
`onboarding`, `signup`, `paywalls`, `copywriting`, `marketing-website-design`, `ab-testing`, etc.

---

## Section 6 — Retention

**Purpose:** Answer "once someone converts, do they stay and deepen?"

**Length:** 800–1500 words.

**Structure:** Same as above.

**Common moves:**
- Lifecycle email flows (post-purchase, lapsed user, win-back)
- Subscription / preference centers
- Churn reconciliation (often metric definitions don't match across surfaces)
- Hardware → software activation paths (for hybrid businesses)
- Annual plan default tests (cross-references to Revenue)

### Skills + tools
`emails`, `churn-prevention`, `copywriting`, `paywalls`, etc.

---

## Section 7 — Referral

**Purpose:** Answer "do retained users bring more users, and at what cost?"

**Length:** 500–1200 words.

**Structure:** Same as above.

**Common moves:**
- Ambassador / affiliate program launch (if inbound interest exists, lead with it)
- Share-after-value moments built into product
- Founder amplification (founder as referrer-zero)
- Long-game expert / Guides / certified-host network
- Gifting flows (for consumer / hardware)

### Skills + tools
`referrals`, `social`, `emails` (for ambassador lifecycle), `copywriting`, etc.

---

## Section 8 — Revenue

**Purpose:** Answer "what do we charge, who pays, and how does it compound?"

**Length:** 500–1200 words.

**Structure:** Same as above.

**Common moves:**
- Pricing audit (what's actually charged today vs. listed?)
- Annual plan default tests
- Hardware → software bundling formalization (for hybrid businesses)
- Storefront / commerce page optimization
- B2B case studies + sales material
- Long-term value pools (data licensing, enterprise expansion) — flagged not executed in 12-month plan

### Unit economics
Required table:

| Metric | Value | Note |
|---|---|---|
| ARPC (avg monthly revenue per customer) | $X | Pulled from Stripe / billing |
| Blended CAC | $X | Includes all marketing costs, not just paid |
| Annual retention rate | X% | 1 − annual churn |
| LTV (rough) | $X | ARPC × 12 / annual churn |
| LTV / CAC | X | Health benchmark: > 3 |

These feed the budget math in Section 10. If any of these are unknown, flag in Section 13 as top open decision.

### Skills + tools
`pricing`, `paywalls`, `sales-enablement`, `revops`, `ab-testing`, etc.

---

## Section 9 — 90-day roadmap

**Purpose:** The tactical execution layer. Every move ships within a named week, with an owner.

**Length:** Tables, not prose. Should fit on one printed page if possible.

**Structure:** Four 2–3-week sprints:

### Weeks 1–2 — Unblock
Highest-confidence, lowest-cost changes. Removing things that are broken.

| Move | Stage | Owner |
|---|---|---|

### Weeks 3–4 — Foundation
Pillar/foundational work. Domain consolidation. First content. First flows shipping. First tests live.

### Weeks 5–8 — Velocity
Compounding work begins. Content cadence. Repeat tests. Channel scaling.

### Weeks 9–12 — Compound
Second-order moves. Layered tactics. 90-day review prep.

---

## Section 10 — 12-month outlook

**Purpose:** Quarterly milestones with explicit funding-stage capability unlocks named, anchored against a defensible growth pattern.

**Length:** Four sub-sections, one per quarter. ~250–400 words each. Plus a short framing paragraph at the top naming the budget method and growth pattern.

### Framing (top of Section 10)

State explicitly:
- **Budget method used.** Method 1 (Revenue-Based 5–40% of ARR) or Method 2 (Goal-Based formula). See `references/budget-planning.md`. Show the math.
- **Annual budget total** + the experimental buffer (+10–20%).
- **Resulting end-of-year ARR goal.** Honest forecast, not a guarantee — see the forecasting reality check in `references/measurement-framework.md`.
- **Growth pattern expected.** Linear (predictable $X MRR added per month), step-function (plateau between deliberate jumps), or layered S-curves. For VC-backed Series A+, anchor against 3-3-2-2-2 and show whether the plan matches it or explicitly chooses a different trajectory. See `references/growth-patterns.md`.

### Structure (per quarter)

#### Q{N} — Months {X}–{Y}

**Funding state:** {tier} per `funding-stage-unlocks.md`

**Focus:** One-sentence focus theme for the quarter.

**Outcomes by end of Q{N}:**
- Bulleted outcome list (5–8 items)

**KPI targets:** 3–5 specific numerical targets.

**Channel/Product/Market S-curve position:** Which curves are growing, which are plateauing, which is the next one being staged for this quarter (see `growth-patterns.md` — layering principle).

---

## Section 11 — Marketing operations stack

**Purpose:** The fCMO differentiator. Show how a small team + agentic tooling executes the plan without hiring at every channel.

**Length:** Tables + brief explanation.

**Structure:**

### The thesis
1–2 paragraphs explaining the principle: small team + marketing-skills library + MCP integrations = output of a larger team.

### Skills mapped to AARRR stages

| Stage | Primary skills | Supporting skills |
|---|---|---|
| Acquisition | (list) | (list) |
| Activation | (list) | (list) |
| Retention | (list) | (list) |
| Referral | (list) | (list) |
| Revenue | (list) | (list) |
| Cross-cutting | (list) | (list) |

### MCPs / APIs mapped to stages

| Stage | Existing connections | fCMO tooling layer |
|---|---|---|

### A concrete example
Pick one operational moment that proves the stack works (e.g., "Customer.io MCP let the non-technical founder draft a flow live on the kickoff call"). Anchor the abstract claim in a specific event.

### Capability unlocks by funding stage

| Stage | Headcount | Tooling | Channels live |
|---|---|---|---|
| (current) | (list) | (list) | (list) |
| (next round) | (delta) | (delta) | (delta) |
| ... | ... | ... | ... |

### Team and agency model (RACI)

Apply the principle from `references/team-and-agency-model.md`: strategy in-house, execution often outsourced.

| Function | Owned by (internal strategic role) | Executed by (IC / contractor / agency) |
|---|---|---|
| Growth marketing (demand engine) | | |
| Product marketing (story engine) | | |
| Content marketing (trust engine) | | |

If the team is missing a strategic owner for one of these functions, the first 90-day move (Section 9) should be the hire — Manager or Lead title, π-shaped if possible, not VP/CMO.

If execution capacity is the gap, name the contractor or small niche agency in the right cell rather than the team's existing IC.

Pull from `references/funding-stage-unlocks.md`.

---

## Section 12 — Tactical idea bank

**Purpose:** Cross-reference all 139 ideas from the `marketing-ideas` skill against AARRR stages, with client-specific status.

**Length:** Long — tables can easily total 150+ rows.

**Structure:**

### Intro paragraph
Explain the cross-reference: Sections 4–8 prescribe what's *being done*. This section maps what's *possible*.

### Status legend

- **Now (Q1)** — already in 90-day plan
- **Q2** — post-foundation layer-in
- **Q3+** — post-seed-close or post-GA expansion
- **Q4+** — long-game
- **Skip / off-brand** — incompatible with brand voice or business model

### 12.1 Acquisition ideas

By status (Now / Q2 / Q3+ / Q4+ / Skip), tables of relevant marketing-ideas by number.

| # | Idea | Client note |
|---|---|---|

### 12.2 Activation ideas
### 12.3 Retention ideas
### 12.4 Referral ideas
### 12.5 Revenue ideas
### 12.6 Cross-cutting / brand foundation ideas

### Idea-bank summary
- Counts per AARRR stage
- Counts skipped, with rationale
- What the plan covers as a % of the available tactical surface area
- What this proves about the client's stage

Use `references/idea-cross-reference.md` as the source-of-truth mapping. Apply client-specific filters during draft (brand voice rules out some; funding stage shifts timing of others).

---

## Section 13 — Measurement, RACI, open decisions, appendix

**Purpose:** Operational close. Define how the plan gets measured, who owns what, what's still TBD, and where to find the deeper docs.

**Structure:**

### Measurement — the metrics that matter

**North star (proposed):** One metric that captures the business-model thesis. For Quietude it was blended-LTV-to-blended-CAC; for a B2B SaaS it might be NRR × NPS; for a marketplace, take-rate × monthly transacting users. Make it specific to the company.

**Leading indicators by AARRR stage:** Table:

| Stage | Leading indicators |
|---|---|
| Acquisition | ... |
| Activation | ... |
| Retention | ... |
| Referral | ... |
| Revenue | ... |

**Review cadence:**
- Weekly: who syncs with whom, on what
- Monthly: who reviews what
- Quarterly: plan recalibration trigger

### RACI

| Domain | Responsible | Accountable | Consulted | Informed |
|---|---|---|---|---|

Common domains: strategic plan, brand voice, app/product implementation, lifecycle, SEO content, App Store, founder-led social, events, ambassadors, B2B sales, pricing, investor narrative, future hires.

### Open decisions blocking the plan

Ranked by impact. Each is: name + impact + what's blocked.

1. (highest impact) ...
2. ...
8. (lowest impact) ...

### Appendix — deep-dive links

**Published in this repo / shared with team:** {relative paths to docs in the shared repo}

**Founder-authored strategic context** (internal knowledge base): {names of docs the team has access to outside the plan repo}

**fCMO working drafts** (not yet published): {names + how to access from author}

---

## Closing line

```markdown
*{Client} Marketing Plan v1. Prepared by {Author}, {Date}. For team review and discussion.*
```

---

## Per-section heuristics for "is this section done?"

- **Section 1** — A non-Quietude reader could understand the company's growth thesis from this alone.
- **Section 2** — Brand voice rules are explicit enough that any new copywriter could follow them.
- **Section 3** — All "in-flight" items have an owner and a blocker named.
- **Sections 4–8** — Each move names a skill (`some-skill`) and a tool (Customer.io MCP / Stripe MCP / Ahrefs / etc.).
- **Section 9** — Every row has an owner.
- **Section 10** — Each quarter names the funding stage explicitly.
- **Section 11** — At least one concrete operational example proves the stack thesis.
- **Section 12** — Skip list has rationale, not just absence.
- **Section 13** — North-star is specific to this company (not generic "ARR growth").


---

# references/team-and-agency-model.md

# Team and Agency Model — Hire for Strategy, Outsource Execution

The marketing operations stack (Section 11 of every plan) describes *what* gets done. This doc describes *who does it* — the operating principle, the org shape, the first hire, the agency model, and how it evolves as the company scales.

Excerpted and adapted from *Founding Marketing* by Corey Haines.

## The principle

**Strategy lives in-house. Execution can — and often should — be outsourced.**

Two failure modes are common when founders ignore this:

1. **Hire junior tactician first.** Founder hits a milestone, raises a round, hires a junior to "do marketing" (run ads, write blogs, post on social). Six months later: scattered tactics, no coherent strategy, disappointing results.
2. **Hire expensive agency for strategy.** Burns cash while the internal team struggles to execute on recommendations they don't fully understand. Strategic insight gathers dust; tactical needs go unmet.

The traditional advice — "hire full-time for competitive advantages, only use agencies for commoditized work" — made sense when marketing moved slowly and talent stayed for decades. That world is gone. Full-time hires take months to ramp and years to develop deep expertise. The best agencies and contractors deliver results immediately, with cross-industry pattern recognition you couldn't build in-house affordably.

## What stays in-house

The strategic heart of the marketing operation. Specifically:

- **Strategic direction and vision** — the "why" behind every move
- **Customer and market understanding** — only comes from daily immersion in the business
- **Positioning and deep market knowledge** — represents the company's unique place in the market
- **Core product and service delivery** — the heart of the value proposition
- **Long-term institutional knowledge** — the compound interest of experience

These are not delegatable. An external partner can sharpen the articulation, but the underlying conviction must come from the team.

## What's safe to outsource

External expertise shines in specific contexts:

- **Best-in-class implementation of specialized skills** (paid media operators, technical SEO, video production, designers)
- **Burst capacity** — launch sprints, campaign cycles, one-off content production
- **Well-defined strategies** — when the scope, deliverables, and success metrics are clear
- **Fresh eyes on old problems** — external perspective when the team is too close to see clearly

The trick is *defining* what's being outsourced. Vague briefs ("help us with marketing") produce vague results. Specific briefs ("ship 20 RSAs across 4 ad groups by month-end with the CTR benchmarks in the brief") produce shippable work.

## The three core functions

Every marketing engine has three primary functions. Whether you have a team of 1 or 50, the functions exist — even if one person owns several.

### Growth Marketing — the demand engine

- Optimizes campaigns
- Manages the funnel
- Operates distribution channels
- Runs the marketing tech stack
- Data-driven; constantly testing and measuring

Drives quantitative outcomes: leads, signups, paid traffic, conversion rate, CAC.

### Product Marketing — the story engine

- Transforms product benefits into compelling messages
- Powers product launches
- Equips the sales team
- Owns pricing and packaging communication
- Bridges what's built and why people should care

Drives positioning quality, message-market fit, launch impact, sales enablement.

### Content Marketing — the trust engine

- Maintains the brand voice
- Manages the editorial calendar
- Produces content that reaches and teaches the audience
- Proves impact through customer stories
- Shapes industry conversations through thought leadership
- Supports sales with closing content

Drives organic traffic, brand affinity, thought leadership, trust signals.

These three functions are interconnected. Growth without story is performance with no positioning. Story without distribution is a great pitch nobody hears. Trust without demand capture is brand affinity that doesn't compound into revenue.

## The first marketing hire

The most consequential decision in building the marketing engine isn't about channels or technology — it's who leads.

**The first marketing hire should be a strategist, not a tactician.** Counterintuitive when there's a mountain of tactical work to ship. Essential for sustainable growth.

### Look for π-shaped, not T-shaped

The standard advice is to hire a **T-shaped marketer**: broad knowledge across many areas, deep in one. That's fine for a tactical IC role.

For the first strategic hire, look for **π-shaped**: two deep skill sets, plus broad surface-level competency across the rest. The two depths create unique leverage through their combination.

#### High-leverage combinations

**Product Marketing + Growth Marketing**
- Owns positioning *and* drives distribution
- Crafts the message *and* gets it to market
- No gap between planning and doing
- Best for technical products or complex sales

**Product Marketing + Content Marketing**
- Translates product into compelling stories
- Owns voice and positioning together
- Creates content that compounds
- Best for thought-leadership or education-driven markets

**Growth Marketing + Content Marketing**
- Builds the demand engine and the content that fuels it
- Closes the loop between SEO/social distribution and conversion
- Best for content-led growth motions

The wrong shape for a first hire: deep paid media specialist alone, deep SEO specialist alone, deep designer alone. These are tactical depths; they need a strategic owner above them.

### Title and progression — don't inflate

A common mistake: making the first marketing hire a "CMO" or "VP." Creates problems when you actually need to scale the org, because there's no headroom above them.

The right progression:

| Title | Scope |
|---|---|
| **Manager** | Individual contributor, co-manages freelancers |
| **Lead** | Senior IC, manages freelancers/agencies |
| **Director / Head** | Manages ICs and vendors |
| **VP** | Manages Directors |
| **Chief (CMO)** | Manages VPs |

The first hire is almost always **Marketing Manager** or **Marketing Lead**. They should be able to:

- Define positioning — not just describe what you do, but why it matters
- Identify best channels — from data, not intuition
- Create the messaging framework — consistency across touchpoints
- Build the marketing engine — systems that scale beyond any individual
- Manage external resources — get the most from agencies and contractors

Both strategic *and* hands-on. Comfortable setting direction and rolling up sleeves. Most importantly: a **builder** — creates processes, frameworks, and systems that scale beyond their individual capacity.

## The marketing engine — three components

Think of the marketing organization as an engine. Each part has a specific role; the magic is in how they work together.

### The Fuel — Strategy

What powers everything else. Without good fuel, even the best engine sputters.

- Product marketing creates positioning (foundation of all communication)
- Content marketing develops stories (features → benefits that resonate)
- Brand marketing establishes identity (memorable and meaningful)

Quality of the fuel determines efficiency. Poor positioning, weak stories, inconsistent branding waste energy regardless of execution.

### The Engine — Execution

Where strategy turns into action.

- Growth marketing drives distribution (right message to the right people)
- Demand gen creates opportunities (attention → interest)
- Operations maintains systems (everything running smoothly)

Needs to be well-maintained and properly tuned. Right processes, tools, people in place to execute consistently.

### The Dashboard — Analytics

How you know if you're heading in the right direction.

- Metrics track performance (measuring what matters)
- Attribution shows what works (cause and effect)
- Data informs decisions (evidence over opinion)

Without good instrumentation, flying blind. Need both leading and lagging indicators.

## Working with agencies — selection framework

Not all agencies are created equal. Ranked from most appropriate for early-stage to least:

### Individual contractors
- **Most flexible** — adapt quickly to changing requirements
- **Direct relationship** — no account-management layer
- **Often most cost-effective** — pay for pure expertise
- **Best for** specific skills (paid media op, technical SEO, video editor, designer)

For most pre-Series-A companies, this is the right answer for nearly all outsourced work.

### Small niche agencies
- **Specialized expertise** — deep knowledge in specific areas
- **Personal attention** — often working directly with senior team
- **Often founder-led** — experienced practitioners calling the shots
- **Clear focus** — they know what they're good at
- **Best for** specialized needs with some complexity (full SEO program, lifecycle email program, brand identity work)

### Small generalist agencies
- **Broader capabilities** — handle multiple needs
- **More resources** — team approach to problems
- **Multiple skill sets** — cross-functional
- **Usually more expensive** — paying for convenience
- **Best for** companies needing broader support and willing to pay for the simplicity of fewer relationships

### Large agencies (not recommended for most startups)
- Long contracts, high minimums, junior account teams, slow turnaround
- Useful only when the brand spend is large enough to command senior attention

## Setting agencies up for success

The difference between a successful and failed agency relationship usually comes down to structure and management.

### Before starting

- **Define clear objectives** — what specific outcomes are we seeking?
- **Set realistic timelines** — when do we need to see results?
- **Establish communication channels** — how do we stay aligned?
- **Agree on metrics** — what defines success?
- **Document processes** — how do we work together?

### During engagement

- **Regular check-ins** — weekly tactical, monthly strategic
- **Clear feedback loops** — both ways, positive and constructive
- **Data sharing** — give them what they need to succeed
- **Performance reviews** — measure against agreed metrics
- **Strategy alignment** — ensure they're moving with the business

### Red flags

- **Scope creep beyond core expertise** — trying to do too much
- **High team turnover** — losing institutional knowledge
- **Missed deadlines** — failing to deliver as promised
- **Poor communication** — lack of proactive updates
- **Unclear reporting** — can't demonstrate value

The best agency relationships feel like partnership: they understand the business, care about success, bring expertise you couldn't build in-house affordably. Takes work on both sides — clear expectations, open communication, mutual respect.

## Scaling the model by stage

The right ratio of internal to external resources isn't static. It evolves with stage, needs, and market conditions.

### Early stage (pre-product-market-fit)

**Mode:** discovery and iteration

- **Internal:** 1–2 strategic hires leading the charge (often the founder + one π-shaped marketer)
- **External:** specialized contractors for execution (no long-term commitment)
- **Agency relationships:** project-based, testing approaches before bigger investments
- **North star:** solid foundation while keeping fixed costs low

### Growth stage (post-PMF, scaling what works)

**Mode:** optimization

- **Internal:** small but mighty core strategic team that owns marketing direction
- **External:** balanced mix of contractors and agencies, each chosen for specific expertise
- **Agency relationships:** deeper, longer-term — partners who grow with you
- **North star:** double down on channels and approaches that have proven successful

### Scale stage (multi-channel, multi-segment)

**Mode:** coordination

- **Internal:** larger strategic team focused on coordination and oversight (not execution)
- **External:** specialized agencies, each bringing deep expertise in specific areas of the mix
- **Trusted contractor network:** flexibility for variable workloads and special projects
- **North star:** finding efficiencies, improving processes, maximizing return

The metaphor: a symphony orchestra. The internal team conducts. External partners play their instruments with expertise.

## How this informs the plan

| Section | What to include |
|---|---|
| **3 (Current state)** | Team composition — every person who touches marketing, what they own. Identify where the team is π-shaped vs. T-shaped vs. tactical-only. Flag gaps. |
| **9 (90-day roadmap)** | If the team is missing the strategic owner, the first move is the first marketing hire (Lead or Manager). If the team has strategy but no execution capacity, the first move is the first contractor or specialized agency. |
| **10 (12-month outlook)** | Map team evolution against funding-stage capability unlocks (see `funding-stage-unlocks.md`). When does the second hire come in? When does an agency relationship deepen? |
| **11 (Marketing operations stack)** | RACI is more honest with this model: "owned by" = internal strategic role; "executed by" = internal IC, contractor, or agency. The plan should make it explicit who does what. |
| **13 (Open decisions)** | If "first marketing hire" is open, name it as a top-three decision. If "in-house vs agency" for a specific function is open, frame the tradeoff using this doc's heuristics. |

## Operational guardrails

- **Don't title-inflate the first hire.** It paints the org into a corner.
- **Don't outsource positioning.** Even the best agency can articulate it back to you, but only if the conviction came from the team.
- **Don't full-time hire for a six-month sprint.** Use a contractor. The hidden cost of full-time is the months of ramp + the awkwardness of letting them go if the work doesn't compound.
- **Don't agency-hire to delay a strategy conversation.** Agencies execute; they don't replace strategic owners. If the internal team can't tell the agency what to do, the agency can't help.
- **Don't measure team size as a success metric.** Measure output, not headcount. A 4-person team with the right π-shaped leader and great external partners out-performs a 15-person team without strategic clarity.
