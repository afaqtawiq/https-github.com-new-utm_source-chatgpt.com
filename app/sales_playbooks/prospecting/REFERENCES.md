# Reference files for the `prospecting` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/b2b-prospecting.md

# B2B Prospecting Reference

For when the user sells to non-SaaS B2B — services, agencies, manufacturers, mid-market and enterprise companies, professional services firms.

---

## ICP Signals That Matter (B2B branch)

### Firmographic signals

- **Industry / vertical** — NAICS or SIC codes if precision matters
- **Company size** — headcount band, revenue band, location count
- **Geography** — relevant for time zones, regulations, on-site requirements
- **Business model** — service vs product vs distribution; B2B vs B2B2C
- **Ownership** — independent, PE-backed, public, family-owned — affects buying motion

### Buying signals

- **Trigger events**: new C-level hire, recent acquisition or divestiture, IPO/funding, opening a new location, recent rebrand, expansion announcement
- **Vendor signals**: posting RFPs publicly, switching costs in last quarterly report, contract renewal windows
- **Operational signals**: recent layoffs (cost pressure) or rapid hiring (capacity pressure)
- **News mentions**: launching new initiative, entering new market, regulatory change forcing action
- **PR / press**: anything that signals "this company is changing right now"

### Decay signals

- Multiple bankruptcies or PE-stripped operations
- Negative growth + cost-cutting headlines
- Ownership stagnation (small family-owned, no growth incentive)
- Buyer turnover (3+ Marketing Directors in 2 years)

---

## Discovery Sources (B2B branch)

### Tier 1 — primary discovery

- **Apollo**: best general B2B firmographic + contact discovery
- **ZoomInfo**: enterprise B2B + intent signals (mid-market+)
- **LinkedIn Sales Navigator**: industry + role + signal search; the gold standard for decision-maker mapping (manual)
- **Clay**: when you need custom waterfall lookups (e.g., enrich Apollo records with Hunter + Clearbit)

### Tier 2 — industry-specific directories

- **Crunchbase / Pitchbook**: funded businesses
- **D&B Hoovers**: large traditional B2B firmographics
- **State / national business registries**: for verified incorporation data
- **Industry association membership rosters**: trade groups often publish member lists
- **Trade show exhibitor lists**: signals active participation in a vertical
- **Procurement databases** (Procore for construction, e.g.): vertical-specific signals

### Tier 3 — trigger event monitoring

- **Google Alerts / Feedly**: trigger keywords ("acquired," "hires," "expansion," "raises," "announces")
- **PR Newswire / Business Wire**: company-controlled announcements
- **SEC filings** (public companies): material change disclosures
- **State filings**: new entity formation, dissolution

---

## Qualification Checklist (B2B branch)

- [ ] Industry / vertical matches ICP (use a recognized classification if possible)
- [ ] Company size within range (employees or revenue)
- [ ] Geography fits
- [ ] At least one trigger event in last 90–180 days
- [ ] Decision-maker role exists (CEO, COO, VP Operations, Director of X — match buyer profile)
- [ ] Email contact verifiable (named role > info@ catchall)
- [ ] Source URLs captured for firmographic claims
- [ ] No disqualifiers (closed, acquired-paused, multi-bankrupt, off-ICP)

---

## Output Columns (B2B branch)

Recommended CSV columns:

```csv
score,company,domain,industry,naics_code,size_band,revenue_band,country,city,trigger_event,trigger_date,contact_name,contact_title,contact_email,email_status,linkedin_url,source_urls,why_prospect,confidence,verified_date,notes
```

For chat table, condense to: Score | Company | Industry | Size | Trigger | Contact | Email status | Confidence.

---

## Top Outreach Targets Selection (B2B)

Prioritize for the top 3–5 hot leads:

1. **Trigger event recency** — 30 days beats 6 months
2. **Trigger event specificity** — new CMO hire in your buyer's role beats "company in the news"
3. **Decision-maker access** — named contact with verified email + LinkedIn beats role-only
4. **Vertical fit precision** — exact NAICS match beats "adjacent industry"

Each top target rationale names the trigger and decision-maker: "Hired new VP of Marketing 14 days ago; verified email; mid-market manufacturer matching ICP."

---

## Common Mistakes (B2B)

1. **Treating B2B like SaaS** — funding rounds matter less; PE ownership and acquisition activity matter more.
2. **Trying to verify private company revenue precisely** — most public databases approximate. Use size bands, not point estimates.
3. **Ignoring procurement complexity** at enterprise scale — your prospect contact list may not include the actual approver.
4. **Cold-emailing executive assistants** — they're not the buyer and they will flag your outreach as spam.
5. **Source URL hygiene** — without source lineage, you can't defend a contact under GDPR DSAR or CAN-SPAM challenge.
6. **Stopping at one source** — Apollo can be 60% accurate on small businesses. Cross-verify with LinkedIn or the business website.


---

# references/compliance.md

# Prospecting Compliance Reference

The legal and platform-ToS constraints that apply to prospect list building. Read first, every engagement.

> Operational guidance, not legal advice. For high-volume programs or programs touching EU/UK residents, run your setup past a privacy attorney.

---

## United States — CAN-SPAM (downstream)

CAN-SPAM regulates the cold email **send**, not the list build. But the list build matters because:

- You must be able to identify the source of every email address you contact (required if challenged)
- The "from" line and email content rules apply at send time — but you can't lie about how you got the contact
- Opt-out requests must be honored within 10 business days and tracked

**For prospecting specifically**: capture and retain the source URL + date for every contact you add to a list. CAN-SPAM doesn't require it explicitly, but defending your sender practices does.

---

## EU / UK — GDPR

The strictest applicable framework. Triggers when:

- Your prospect resides in EU/UK
- You're processing personal data (any identifiable info, including business emails tied to a named person)

### Lawful bases for cold B2B outreach

You have three credible options:

1. **Legitimate interest** (most common for B2B). Requires:
   - The contact is in a business role likely to be interested in your offer
   - The data was collected from a public, business-context source
   - You provide a clear opt-out
   - You can articulate the legitimate interest test in writing

2. **Consent** — typically not feasible for cold outreach (you don't have consent before first contact)

3. **Existing customer relationship** — only applies to current customers, not prospects

### What you must do

- Capture **source + date + lawful basis** for every contact
- Honor data subject access requests (DSARs) — you must be able to disclose, correct, or delete on request
- Include a privacy notice / opt-out in the first outreach
- Don't store personal data longer than necessary for the legitimate interest

### What disqualifies a list

- Bulk-scraped LinkedIn data — explicit ToS violation + GDPR risk
- Email addresses purchased from a list broker without source provenance
- "Anyone @ this domain" guessed emails sent without verification (multiplies risk + bounces)

---

## Canada — CASL

Stricter than CAN-SPAM. Cold B2B outreach requires:

- **Express consent** (explicit opt-in) — typically not present for cold prospecting
- **OR implied consent** — existing business relationship within 24 months, OR business address publicly published on the company's own site for the purpose of receiving such communications

**Practical implication for Canadian prospects**: relying on the publicly-published-address exception is the most defensible cold prospecting basis in Canada. You must include sender identification, mailing address, and an unsubscribe mechanism in every message.

---

## Platform Terms of Service

### LinkedIn

- **Sales Navigator** as a research tool: fine
- **Scraping LinkedIn at any scale**: explicit ToS violation. Banned accounts are permanent. Don't.
- **Apollo, Clay, and ZoomInfo** claim LinkedIn-overlap data through various legitimate channels — verify their data sources before assuming compliance
- **InMail and Connection Requests**: governed by LinkedIn's own messaging rules, not by CAN-SPAM/GDPR (because LinkedIn-internal)

### Google Maps

- ToS prohibits bulk extraction or productizing Maps data
- Browser-assisted research as a discovery aid: acceptable
- Storing Place IDs or large structured Maps data in your CRM: explicit ToS prohibition
- Use Maps to **find** local businesses, then cross-source from the business's own site for the data you retain

### Apollo / ZoomInfo / Clearbit

- All have their own ToS limiting reselling, downstream sharing, and use cases
- Read your contract — typically you can use the data for your own outreach but not productize it
- Don't share extracts publicly (e.g., on a leaderboard, in a public report)

### Crunchbase

- Free tier is read-only for personal use
- Paid tier permits broader use within contractual scope
- API access requires paid Pro+ tier

---

## Anti-Patterns (Don't Do These)

1. **Bulk-scraping LinkedIn / Google Maps / Yelp**. Browser-assisted research is OK; automated scrapers pointed at these platforms are not. **Firecrawl and Browserbase are fine for an individual prospect's own website** (the URL you found through manual discovery) — not for the platforms hosting prospects.
2. **Buying lists from random vendors** without source provenance. You inherit their legal exposure.
3. **Guessing emails and sending unverified**. Bounce rates over 2% destroy sender reputation; legally, you can't claim a "legitimate interest" basis for an email you fabricated.
4. **Harvesting personal email addresses** (Gmail, personal Outlook, etc.) from public profiles. Personal addresses raise GDPR risk significantly.
5. **Storing data you don't need**. Minimize retention. Don't keep prospect lists forever — GDPR right to deletion applies.
6. **Skipping the lawful basis documentation**. If challenged, you need to show your work. Capture source URL + collection date for every contact.
7. **Reselling prospect lists**. You may not have the right to share them downstream. Read your data provider contracts.
8. **CAPTCHA bypass / login wall bypass**. Even if technically possible, this signals bot behavior and violates virtually every ToS.

---

## Quick Audit Checklist

Before shipping a list to the user (or downstream to cold-email):

- [ ] Every contact has a source URL + collection date
- [ ] No contacts sourced from scraped LinkedIn data
- [ ] No Google Maps Place IDs or large Maps-structured data retained
- [ ] Lawful basis documented (legitimate interest test for B2B, or relevant alternative)
- [ ] Email addresses validated (deliverability check before outreach)
- [ ] Personal addresses (Gmail, etc.) flagged or excluded
- [ ] Source provider contracts permit the intended use case
- [ ] Retention plan documented (when to delete)
- [ ] First outreach will include unsubscribe + privacy notice (downstream concern for cold-email skill, but mention it now)


---

# references/data-sources.md

# Prospecting Data Sources

Tool selection guide for prospecting across all three branches.

---

## Tool selection by goal

| Goal | Primary tools | Notes |
|------|--------------|-------|
| **Build initial firmographic list (B2B / SaaS)** | Apollo, ZoomInfo, Clay | Apollo for breadth, ZoomInfo for enterprise + intent, Clay for custom workflows |
| **Decision-maker mapping** | LinkedIn Sales Navigator (manual), Apollo, ZoomInfo | Sales Nav is the gold standard. Never bulk scrape it. |
| **Tech stack qualification (SaaS)** | BuiltWith, Wappalyzer | BuiltWith has wider coverage + paid plans for bulk; Wappalyzer is lighter + free for small use |
| **Funding signals (SaaS)** | Crunchbase, Pitchbook | Crunchbase free tier sufficient for early signals; Pitchbook for deeper investor data |
| **Email pattern discovery** | Hunter, Snov, Apollo | Pattern guessing — followed by verification |
| **Email deliverability verification** | Truelist, Hunter, NeverBounce, ZeroBounce | Always verify before adding to outreach lists |
| **Visitor identification (warm intent)** | RB2B, Clearbit Reveal | Anonymous traffic → company identification |
| **Intent data** | ZoomInfo Intent, 6sense, Bombora | Pre-warmed signals; mid-market+ pricing |
| **Trigger event monitoring** | Google Alerts, Feedly, LinkedIn Sales Nav alerts | Free options are sufficient for most |
| **Local business discovery** | Google Maps (manual), Yelp, Facebook Pages | Browser-assisted, not bulk-extracted |

---

## Apollo

**Use for**: General B2B / SaaS firmographic + contact data. Best starting point if you don't already have a list.

**Strengths**:
- Large database (>200M contacts, >60M companies)
- Strong filtering UI (industry, size, technologies, signals)
- Integrated email + LinkedIn finder
- Pay-as-you-go and tiered plans

**Watch out for**:
- Data freshness varies — re-verify before scoring as "Hot"
- Email accuracy ~60–80% — always validate
- Bulk export limits apply

**Integration**: see [apollo.md](../../../tools/integrations/apollo.md)

---

## Clay

**Use for**: Multi-source enrichment, waterfall lookups, custom scoring logic. When list quality matters more than list size.

**Strengths**:
- Waterfall logic: try Apollo first → fallback to ZoomInfo → fallback to Clearbit
- 100+ data provider integrations
- AI-powered enrichment (LLM-driven extraction from URLs)
- Custom columns + scoring formulas
- Native MCP server

**Watch out for**:
- Per-credit pricing can spike on large lists
- Complexity overhead — easy to over-engineer workflows

**Integration**: see [clay.md](../../../tools/integrations/clay.md)

---

## ZoomInfo

**Use for**: Enterprise B2B + intent data. Mid-market+ buyer profiles.

**Strengths**:
- Enterprise-grade firmographic depth
- Intent signals (companies searching topics relevant to your offer)
- Best-in-class for >$50K ACV B2B sales
- Native MCP server

**Watch out for**:
- Expensive ($15K+/yr starter)
- Overkill for SMB prospecting
- Locked into multi-year contracts typically

**Integration**: see [zoominfo.md](../../../tools/integrations/zoominfo.md)

---

## Clearbit

**Use for**: Email → company enrichment, anonymous visitor identification (Clearbit Reveal).

**Strengths**:
- Strong company enrichment (industry, size, funding, tech stack)
- Email lookup by domain
- Reveal: identify anonymous site visitors at company level
- API-first

**Watch out for**:
- HubSpot acquisition (2023) — bundled into HubSpot Breeze Intelligence now
- Standalone API still available but pricing/access depends on tier

**Integration**: see [clearbit.md](../../../tools/integrations/clearbit.md)

---

## Hunter / Snov

**Use for**: Email pattern discovery + lightweight verification on small lists.

**Hunter strengths**:
- Domain-based email discovery
- Built-in deliverability verification
- Free tier reasonable for occasional use

**Snov strengths**:
- Email finder + drip campaigns (overlap with outreach tooling)
- Bulk verification
- Cheaper than Hunter at scale

**Watch out for**:
- Both are pattern-guessing tools — accuracy depends on the target company's email pattern being inferable
- Always run results through a dedicated validator (Truelist or similar) before outreach

**Integrations**: see [hunter.md](../../../tools/integrations/hunter.md), [snov.md](../../../tools/integrations/snov.md)

---

## Truelist

**Use for**: Email deliverability validation before adding contacts to outreach lists. Critical safety step.

**Strengths**:
- Single-email sync verification (`/api/v1/verify_inline`) + bulk async (`/api/v1/verify`)
- Returns `email_state` (ok / email_invalid / risky / unknown / accept_all) + `email_sub_state` (email_ok / is_disposable / is_role / unknown_error / failed_smtp_check) + did-you-mean typo suggestions
- Catches catch-all domains, role accounts, spam traps, disposable providers
- Official MCP server for agent-driven workflows (Claude, Cursor, VS Code)
- Official SDKs in 7 languages + framework integrations (Django, Laravel, Next.js, Rails, React, Svelte, Vue, WordPress)
- Native integrations with Mailchimp, Klaviyo, HubSpot, Zapier, Make, n8n, Clay, Salesforce, more
- Pay-per-email pricing

**Why this matters**: Cold email reputation craters when bounce rates exceed 2%. Validating before sending is non-negotiable. Apollo/ZoomInfo/Hunter data is often 60–80% accurate — Truelist catches the rest.

**Integration**: see [truelist.md](../../../tools/integrations/truelist.md)

---

## LinkedIn Sales Navigator

**Use for**: Manual decision-maker discovery. The gold standard for B2B / SaaS prospecting but only when used as a research tool.

**Strengths**:
- Most accurate decision-maker data in the industry
- Real-time job changes, posts, signals
- Lead lists, alerts, saved searches
- Inmail credits (separate channel from cold email)

**Hard rules**:
- **Never bulk scrape**. LinkedIn aggressively bans scrapers. Account ban risk is real and permanent.
- Use Sales Nav as a research interface — open profiles, read, take notes, capture key data manually.
- Apollo and other tools claim LinkedIn data via partnerships / public mirroring — verify the source legitimacy before assuming compliance.

**Integration**: no MCP or API access at consumer level. Manual research only.

---

## BuiltWith / Wappalyzer

**Use for**: Tech stack qualification (SaaS branch).

**BuiltWith**:
- ~50K+ technologies tracked
- API + bulk lookups (paid)
- Historical data (when stack changed)

**Wappalyzer**:
- Free browser extension; paid API
- Lighter coverage than BuiltWith
- Faster for one-off lookups

Cross-reference both for high-confidence tech stack signals.

---

## Crunchbase

**Use for**: Funding signals (SaaS branch).

**Strengths**:
- Free tier shows recent funding events
- Paid (Pro / Enterprise) unlocks alerts and deep history
- API access for paid users

**Watch out for**:
- Coverage is best for VC-backed companies; bootstrapped + small businesses underrepresented
- Self-reported data — verify funding amounts independently

---

## GitHub (stargazers / forks / watchers)

**Use for**: Developer-intent prospecting. Especially powerful for dev-tool SaaS — stargazers of competitor or category-defining repos are in-market signal.

**Strengths**:
- Public API, no scraping concerns
- High signal quality (a starred repo = explicit interest)
- Forks are an even stronger signal (intent to modify, not just bookmark)
- Bundled `github-prospects.js` CLI handles pagination + enrichment + CSV output
- Free with 5,000 req/hr authenticated rate limit

**Watch out for**:
- Only ~5–20% of users publish email — pair with Apollo/Clay/Hunter for enrichment
- Very-popular repos (100K+ stars) are mostly noise; smaller targeted repos (5K–25K) give better signal density
- Most prospects are individuals, not company contacts directly — need to figure out their company from `company` field or LinkedIn

**Integration**: see [github.md](../../../tools/integrations/github.md)

---

## Firecrawl / Browserbase (single-target site research)

**Use for**: Programmatically extracting content from a **prospect's own website** that you already found via discovery on platforms like Google Maps, Yelp, or LinkedIn. Not for scraping those platforms themselves.

### Firecrawl

- **Best for**: "Just give me the page as markdown" — Local SMB website status checks, B2B company about/team page extraction, structured field extraction
- **Strengths**: Low overhead, returns clean LLM-ready markdown, handles most JS-rendered sites, has an MCP server
- **API + MCP + SDKs**: Node, Python, Go, Rust

### Browserbase

- **Best for**: When you need real Chromium — JS-heavy pages, cookie consent dialogs, form submission to reach a contact page, session state
- **Strengths**: Full browser control via Playwright/Puppeteer; Stagehand provides AI-friendly natural-language extraction; session recordings for debugging
- **API + MCP (Stagehand) + SDKs**: Node, Python

### Critical compliance line

Both tools can technically point at any URL. The hard rule:

- ✓ **OK**: extracting content from a single business's own website (`joescoffeeshop.com`) that you found through manual discovery
- ✗ **NOT OK**: pointing them at `google.com/maps`, LinkedIn search results, Yelp listings, or any platform whose ToS prohibits bulk extraction

Discovery happens on platforms (manual browser-assisted research). Extraction happens on individual public business sites.

**Integrations**: see [firecrawl.md](../../../tools/integrations/firecrawl.md), [browserbase.md](../../../tools/integrations/browserbase.md)

---

## RB2B / Clearbit Reveal

**Use for**: Identifying anonymous site visitors as warm intent signals.

**Strengths**:
- Pixel-based visitor → company identification
- High-intent: they came to your site, they're already in research mode
- Slack / email alerts on key visits

**Watch out for**:
- Privacy/GDPR considerations — verify your privacy policy disclosures
- Person-level identification raises higher concerns than company-level

**Integration**: see [rb2b.md](../../../tools/integrations/rb2b.md)

---

## Free / browser-only fallbacks

When the user has no paid tools, lean on:

- **Google Search** — exact business name + city + role searches
- **LinkedIn** (manual, no scraping) — company pages, employee lookups
- **Crunchbase free tier** — funding events
- **Wappalyzer browser extension** — tech stack at a glance
- **Hunter.io free tier** — 25 lookups/month
- **Google Maps** — for Local SMB discovery
- **Business websites + About pages** — primary source for any claim
- **News sites + press releases** — trigger event monitoring via Google Alerts

Slower than tooled-up workflows, but produces high-quality smaller lists if the user is willing to do the work.

---

## Sequencing recommendations

A typical full-stack prospecting workflow:

1. **Define ICP** from product-marketing context (no tools needed)
2. **Initial list** from Apollo or ZoomInfo (firmographic filter)
3. **Enrich** with Clay (waterfall: tech stack, funding, trigger events)
4. **Decision-maker mapping** in LinkedIn Sales Nav (manual)
5. **Email pattern discovery** with Hunter or Apollo's built-in
6. **Email validation** with Truelist before final list
7. **Hand off** to cold-email skill for outreach copy

Adapt this sequence based on which tools the user actually has.


---

# references/demand-signals.md

# Demand-Signal Discovery (Find Your First Customers)

The other three branches build a list from who *fits* (firmographics, technographics, proximity). This branch builds a list from who is *already showing the pain* — the early-stage motion where you have a product and a hunch but no customer base yet, and you need your first ten real conversations. You are not filtering a database; you are mining recent public discourse for people describing the exact problem you solve, then linking every prospect to the evidence.

Use this branch when the user is pre-product-market-fit, launching something new, or looking for **design partners, beta users, or first customers** rather than a scaled outbound list. It reuses the shared five phases and every compliance guardrail in SKILL.md; what changes is where you look, how you score, and what you ship.

Pattern credit: the framework here is re-expressed from the open-source `first-customer-finder` Codex skill (Kappaemme, MIT), extended with our live-recency tooling.

## What makes this branch different

| | List-building branches (SaaS / B2B / SMB) | Demand-signal discovery |
|---|---|---|
| Starts from | A firmographic ICP | A described problem |
| Sources | Contact databases (Apollo, ZoomInfo, Clay) | Public discourse (forums, reviews, issues, posts) |
| Contact step | Enrich + verify email deliverability | None — reach them where they already posted |
| Wins on | Coverage at scale | 10 strong evidence-backed matches over a long list |
| Output | A scored lead sheet | An evidence report + manual outreach plan |

A prospect here without a cited pain, need, or timing signal is a speculative fit — it does **not** belong in the primary shortlist. Evidence is the entry ticket.

## Step 1 — Product brief (before any searching)

Define, specifically enough to *reject* weak matches:

- product and the promised outcome
- primary user and the economic buyer (often different)
- the urgent job to be done
- the current alternative or workaround being replaced
- the likely adoption trigger (what makes now the moment)
- geography / language constraint
- clear disqualifiers

Don't start broad collection until the brief is sharp. Pull from `.agents/product-marketing.md` if it exists.

## Step 2 — Mine the five signal buckets

Search several angles, not one query repeated. Adapt wording to how the audience actually talks (mine their vocabulary from organic content first — see the ad-creative hook-system's organic-language note for the same idea).

1. **Explicit demand** — "looking for," "recommend a tool for," "alternative to [X]," "does anything exist that," "how do you all handle."
2. **Pain** — "takes hours," "so manual," "hate that," "keeps breaking," "biggest frustration with," "why is there no."
3. **Workaround** — spreadsheets, copy-paste, a VA, a Zapier chain, a script, a template, any repeated manual step that your product would replace.
4. **Switching** — cancellation, migration, "moving off [competitor]," a missing feature, a pricing complaint, competitor frustration.
5. **Timing** — a public launch, a new hire for the relevant function, expansion, a new workflow or regulation, an integration announcement — a *current* event that makes the product relevant now.

**Use our live-recency edge.** A generic skill relies on whatever a web search surfaces; you have better:
- **last30days** — Reddit, Hacker News, X, YouTube, and web signals from the last 30 days. This is the single highest-value tool for this branch: recency *is* the timing signal.
- **social-fetch** — pull the full content of a specific post/thread you find, normalized.
- **scraping** / **Firecrawl** / **Browserbase** — read the original public page (a forum thread, a GitHub issue, a review), never qualify from a search snippet alone.
- **deep-research** — for a multi-source sweep with adversarial verification when the wedge is broad.
- **competitor-profiling** / **customer-research** — competitor switching signals and review-mining for the pain language.

## Step 3 — Source mix (public only)

Forums and public community threads · public social posts and replies · product and app-marketplace reviews · GitHub issues and feature requests · public company pages, job posts, changelogs, launch announcements · "looking for a tool" posts and directories.

Avoid private groups, gated communities, data brokers, leaked datasets, and any source whose terms prohibit access — the same compliance guardrails as every other branch (see SKILL.md), including the no-sensitive-traits rule.

**Business/professional context only.** Qualify and reach out only where someone is posting in a professional or business capacity about a work problem (a founder in an indie-hackers thread, a developer in a GitHub issue, an ops lead in a subreddit for their role). Exclude personal-distress contexts entirely — health, financial hardship, addiction, grief, or any consumer support forum where people are venting personal problems, even if your product is tangentially relevant. When the motion is genuinely consumer (B2C), a public pain post is not on its own a lawful basis for cold outreach — reach people through the channel's own norms (reply publicly where replying is expected) and never DM a stranger off a personal post.

Quote minimally, paraphrase by default, and link every material pain or timing signal.

## Step 4 — Score on demand-fit (not ICP-fit)

The list-building branches score Hot/Warm/Cold on ICP fit. This branch scores 0–100 on **demand fit** — how strongly the evidence says this specific prospect wants this specific thing now. Score each dimension 0–5:

| Dimension | Weight | What it measures |
|---|---|---|
| **Pain strength** | 25% | Directness, severity, repetition, and cost of the stated problem |
| **Product fit** | 25% | How directly your product solves the evidenced job |
| **Timing** | 20% | Freshness + a current trigger present |
| **Public reachability** | 15% | A natural, relevant public/professional contact path exists |
| **Evidence quality** | 15% | Specificity, source reliability, confidence the signal is really theirs |

```
score = pain/5*25 + fit/5*25 + timing/5*20 + reachability/5*15 + evidence/5*15
```

| Band | Meaning |
|---|---|
| **80–100** | Strong first-customer candidate |
| **65–79** | Promising — validate fast |
| **50–64** | Plausible but missing a material signal |
| **Below 50** | Do not include in the primary shortlist |

An old explicit request can still count — but lower the timing score and label the date. A company that merely matches the industry with no evidenced trigger is *not* a qualified prospect here.

### Prospect stages

- **High intent** — publicly requesting a solution or actively switching
- **Problem aware** — clearly describing the pain or an expensive workaround
- **Trigger present** — a current business event makes the product relevant
- **Potential fit** — ICP match, incomplete evidence → keep *outside* the primary shortlist

### Evidence ledger (per qualified prospect)

Displayed name (company/project/public professional) · source title + URL · visible publication date or "date unavailable" · source type · the concise pain/timing signal · observed evidence vs. inference (label which) · score breakdown · freshness warning when the signal is stale.

## Step 5 — Draft outreach, never send it

Recommend the most natural channel *already associated with the source*, and only where a reply is a normal part of that channel (reply in the public thread, respond via a public professional profile). Don't turn a public post into a private DM the poster didn't invite, and never contact someone off a personal-distress post. Draft one opener, under ~90 words, in this shape:

1. mention the public context naturally
2. connect it to the exact problem
3. explain the product in one sentence
4. ask one low-friction question

Never claim familiarity you don't have, never fabricate personal details, and never auto-send: no messages, connects, follows, comments, form submissions, or CRM records unless the user separately authorizes that action. This is the manual/gated posture from the marketing-loops guardrails.

## Step 6 — Ship the evidence report

Lead with the most actionable evidence, in this order:

1. **Verdict** — does the product have reachable early-customer signal, or not yet? (An honest "not yet, here's why" is a valid answer.)
2. **ICP** — buyer, job, trigger, disqualifiers.
3. **Top prospect** — the single strongest evidence-backed candidate and why now.
4. **Prospect shortlist** — per prospect: source, pain signal, demand-fit score, stage, why-now, channel, opener.
5. **Repeated patterns** — pains and triggers recurring across prospects (these are your positioning and messaging gold).
6. **Seven-day manual outreach plan** — a low-volume validation sequence (e.g., contact the top 3 with one source-based question; share a mockup only after they confirm the pain; target three conversations and one design-partner commitment).
7. **Limits** — what evidence is missing and what must be confirmed through real conversations.

For a shareable standalone HTML version of this report, the JSON→HTML generator pattern in ad-creative's [creative-review-page.md](../../ad-creative/references/creative-review-page.md) is the model (escape every value; keep it self-contained).

## The honesty rules (non-negotiable)

- Every primary prospect links to at least one real public signal. No signal, no shortlist.
- Label the output **"potential customer based on public signals"** — never "interested," "will buy," or "has consented."
- Prefer ten strong matches over a long generic list. Make uncertainty and stale evidence visible.
- Personalize from the cited source, not from invented assumptions.
- Treat the shortlist as a research hypothesis to validate through conversations, not a customer database.


---

# references/local-prospecting.md

# Local SMB Prospecting Reference

For when the user sells to local small businesses — shops, gyms, restaurants, salons, clinics, professional services, contractors, real estate, fitness studios, dental practices.

Adapted from and generalized beyond the local-client-prospector pattern (browser-assisted discovery + website status classification + proximity scoring).

---

## ICP Signals That Matter (Local SMB branch)

### Operational signals

- **Active business** — Google Business Profile updated, recent reviews, recent hours updates
- **Recent activity** — open right now, regular hours posted, recent photos uploaded by owner
- **Customer engagement** — owner responding to reviews, posts on social, active calendar (for service businesses)

### Online presence signals (the core SMB qualification axis)

The reference local-client-prospector skill uses **website status** as the primary qualification — port this directly. Four classifications:

| Status | Definition | Typical outcome |
|--------|-----------|-----------------|
| **No site found** | No credible standalone website after cross-checked search | **Hot prospect** for web/marketing service |
| **Social only** | Facebook, Instagram, WhatsApp, Linktree, booking portal, marketplace page only — no standalone site | **Hot prospect** for web/marketing service |
| **Weak site** | Standalone site exists but outdated, broken, very thin, non-mobile-friendly, or missing clear contact/conversion flow | **Warm prospect** for refresh / rebuild service |
| **Has site** | Credible, modern standalone site exists | **Low prospect** unless other signals apply (e.g., poor SEO, weak conversion design) |

### Proximity signals

- **Distance** from the user's location or service area
- **Density** — clusters of similar businesses in one area = neighborhood targeting opportunity
- **Travel time** — useful when in-person discovery, install, or service delivery is required

### Decay signals

- Closed permanently (Google Maps banner)
- Reviews paused or business listing reported as closed
- Last activity (review, post) >12 months ago

---

## Discovery Sources (Local SMB branch)

### Primary

- **Google Maps** (browser, manual) — search "category near [location]" and walk the visible results. Cross-check details. Don't bulk-extract.
- **Yelp** — secondary verification; complementary categories
- **Bing Local / Apple Maps** — different coverage on smaller businesses
- **Facebook Pages search** — many SMBs are Facebook-only

### Cross-verification

- **Business's own website** (if any)
- **Industry directories** (e.g., Healthgrades for medical, OpenTable for restaurants, Avvo for legal)
- **Local Chamber of Commerce listings**
- **State business registries** for incorporation status
- **Search results for "[business name] [city]"** to discover non-Maps presence

---

## Browser Research Workflow

1. Open a browser and search Google Maps for the category near `base_location`
2. Build a candidate list from visible local results, search results, and public directories
3. For each candidate, inspect public sources to fill required fields
4. Search the exact business name plus city/town to check whether a standalone website exists
5. Classify website status per the table above
6. Mark confidence: High (2+ sources), Medium (1 source + consistent evidence), Low (incomplete/ambiguous)

When the user explicitly asks for subagents AND subagents are available, split candidates into non-overlapping batches and ask each subagent to verify only website/social/contact status. Don't use subagents for the primary search if it slows progress.

### Optional: programmatic verification with Firecrawl or Browserbase

Once you have a candidate's website URL (found via manual Maps/Yelp discovery), you can speed up website-status classification by hitting the URL programmatically:

- **Firecrawl** for simple "is this site live, modern, mobile-friendly, conversion-flow-equipped" reads — returns clean markdown you can inspect
- **Browserbase** when the candidate site requires JS rendering, has a cookie consent dialog, or you need session state

**Strict line**: use these on the individual business's URL. **Don't** point them at Google Maps, Yelp, or any platform whose ToS prohibits bulk extraction — discovery stays manual.

See [data-sources.md](data-sources.md) for setup details.

---

## Qualification Checklist (Local SMB branch)

- [ ] Business is active (recent reviews or activity in last 6 months)
- [ ] Category matches user's service offering
- [ ] Distance / proximity within target radius
- [ ] Website status classified
- [ ] Phone or contact channel verified
- [ ] At least one cross-source confirms business operates at the listed address
- [ ] Not a duplicate / chain location / out-of-scope category
- [ ] Not closed permanently

---

## Lead Scoring (Local SMB)

Use this simple rubric (matches local-client-prospector pattern):

| Score | Criteria |
|-------|----------|
| **Hot** | No site found OR social-only + phone present + active business + within target radius |
| **Warm** | Weak site, poor online presentation, or marketplace/booking-page only |
| **Cold** | Good website already present OR low confidence |
| **Skip** | Closed, duplicate, outside radius, irrelevant category, or not a business prospect |

---

## Output Columns (Local SMB branch)

Chat table (≤15 rows):

```
| Score | Business | Category | Area | Distance | Website status | Website/Social | Phone | Why it's a prospect | Confidence |
```

CSV:

```csv
score,business,category,area,distance_km,website_status,website_url,social_urls,phone,email,source_urls,why_prospect,confidence,verified_date,notes
```

Rules:
- Keep "Why it's a prospect" short and actionable
- Use `Not found` instead of leaving blank fields
- Include source links sparingly, not all of them
- After the table, add **Best first outreach targets** with the top 3 leads and one practical reason each
- If confidence is low, state exactly what remains uncertain

---

## Top Outreach Targets Selection (Local SMB)

Prioritize for the top 3 hot leads:

1. **No site / social only + phone present** = clearest service opportunity
2. **High review count** = active, established business with real customers
3. **Owner-responded reviews** = engaged owner = more likely to evaluate a vendor
4. **Industry alignment with your service specialty** beats generic category match

Each top target rationale should be one sentence naming the gap and the signal: "No standalone website (cross-checked); 80+ Google reviews with owner replies; 2 km from target area."

---

## Compliance Notes (Local SMB-specific)

The local branch is the most scraping-sensitive of the three motions. Specifically:

- **Google Maps Terms of Service** prohibit bulk extraction. Treat browser visits as research, not as data acquisition.
- **Don't store full Google Maps Place IDs in your CRM** — the ToS limits storage of Maps data.
- **Public business contact channels only**: published phone, contact form, info@ email. Don't reach individual employees through their personal channels.
- **Owner/operator name when published on the business's own site** is OK to use. If you only got it from LinkedIn, mark the source.

---

## Common Mistakes (Local SMB)

1. **Bulk-scraping Google Maps** — fastest way to violate ToS and lose the research channel.
2. **Treating Google Maps data as truth** — listings go stale. Cross-check hours, status, and reviews.
3. **Skipping the website status cross-check** — finding "no site" on Maps doesn't mean no site exists; do an exact-name web search before classifying.
4. **Targeting only the largest businesses** — they're already covered by other providers. The 2–5 employee SMBs are the under-served opportunity.
5. **Generic outreach to all hot leads** — local SMBs respond better to outreach that names their specific gap ("I noticed your menu isn't visible on mobile") than generic pitches.
6. **Ignoring chains and franchises** as Skip — sometimes the franchisee is the buyer and they have local marketing authority. Verify before skipping.


---

# references/saas-prospecting.md

# SaaS Prospecting Reference

For when the user sells SaaS or digital services to other SaaS companies / digital businesses.

---

## ICP Signals That Matter (SaaS branch)

Beyond standard firmographics (industry, size, geography), SaaS prospects are qualified by:

### Technographic signals

- **Tech stack** — do they use complementary tools (your integration target) or competing tools (a switch opportunity)?
- **Recent stack changes** — adding/removing tools signals active vendor evaluation
- **Custom-built vs off-the-shelf** — DIY tooling often means a buyer who'd benefit from your product
- **Free/freemium plan signals** — using a free competitor means they may be ready to upgrade

### Growth signals

- **Funding round** — Series A / B / C in last 6 months = budget + new hires + tool needs
- **Headcount growth** — 10%+ growth in last quarter signals scaling pressure
- **Hiring signals** — specific role openings (e.g., "Head of RevOps" → ICP for revops tooling)
- **Product velocity** — frequent shipping, new features, blog posts = healthy growth motion
- **Open positions for your buyer's role** — if you sell to Marketing Ops and they're hiring one, that's a signal

### Decay signals (downgrade scoring)

- Layoffs in target department
- Funding round >2 years ago with no follow-up
- Product hasn't shipped in 6+ months
- Team page shows founders only (very early — may not have budget)

---

## Discovery Sources (SaaS branch)

Combine 2+ sources for cross-verification.

### Tier 1 — primary discovery

- **Apollo**: firmographic + technographic + contact data. Good for building large initial lists.
- **Clay**: waterfall enrichment, custom scoring, multi-source merges. Best for high-quality smaller lists.
- **ZoomInfo**: enterprise-grade firmographic + intent signals. Expensive; mid-market+.
- **LinkedIn Sales Navigator**: decision-maker mapping. Use manually, never bulk scrape.

### Tier 2 — technographic / growth signals

- **BuiltWith**: tech stack lookups, find sites using specific tools
- **Wappalyzer**: free browser extension + API; lighter tech stack signal
- **Crunchbase**: funding rounds, headcount, founders
- **Pitchbook**: deeper investor data (enterprise/paid)
- **ProductHunt**: recent launches, builder audience
- **Hacker News / Show HN**: technical builders launching products

### Tier 3 — buying signals

- **Job boards** (LinkedIn Jobs, Indeed, AngelList): role openings as signals
- **RB2B / Clearbit Reveal**: visitor identification (warm anonymous traffic)
- **GitHub stars/forks of competitor or adjacent repos**: developer-level intent signal (see `tools/integrations/github.md` and the `github-prospects.js` CLI). Especially strong for dev-tool SaaS — a developer who starred `vercel/next.js` last week is in-market for adjacent Next.js infrastructure.
- **Recent blog posts / changelog**: product direction signals
- **G2 reviews mentioning competitor switches**: explicit dissatisfaction signal

#### GitHub prospecting pattern (when audience is developers)

For dev-tool SaaS, GitHub is one of the highest-quality discovery channels:

1. Identify 3–5 "anchor" repos: your direct competitors, your category leader, complementary tools your buyer uses
2. Pull stargazers (or forks for stronger intent) via `node tools/clis/github-prospects.js stargazers <owner/repo> --enrich --with-company --format csv`
3. Filter to users with `company` set — these are the easiest to enrich downstream
4. Pair with Apollo/Clay/Hunter to lookup email by name + company
5. Validate with Truelist before adding to outreach list

Tradeoffs: GitHub yields email for only ~5–20% of users directly. The strength is the signal quality — a stargazer of a niche dev tool is genuinely in-market in a way Apollo firmographics alone can't tell you.

---

## Qualification Checklist (SaaS branch)

For each candidate, verify:

- [ ] Industry vertical matches ICP
- [ ] Company size (headcount) within range
- [ ] Tech stack includes (or notably excludes) a target technology
- [ ] Funding stage matches buyer maturity
- [ ] At least one growth signal in last 90 days (funding, hiring, product velocity)
- [ ] Decision-maker role exists at the company (named or inferable from job listings)
- [ ] Email contact verifiable
- [ ] No disqualifiers (closed, acquired-and-paused, layoffs, ICP miss)

---

## Output Columns (SaaS branch)

Recommended CSV columns:

```csv
score,company,domain,industry,size_band,country,funding_stage,last_round_date,tech_stack_match,signal,signal_date,contact_name,contact_title,contact_email,email_status,linkedin_url,source_urls,why_prospect,confidence,verified_date,notes
```

For chat table, condense to: Score | Company | Industry | Size | Signal | Contact | Email status | Confidence.

---

## Top Outreach Targets Selection (SaaS)

Prioritize for the top 3–5 hot leads:

1. **Strongest signal recency** — funding 30 days ago beats funding 9 months ago
2. **Tech stack match strength** — known integration partner beats inferred fit
3. **Decision-maker named with verified email** — beats role-pattern-guessed email
4. **Multi-source confidence** — both Apollo + Crunchbase agree beats one source

Each top target gets a one-sentence outreach rationale that names the specific signal: "Raised Series B 30 days ago; hiring Head of RevOps; verified VP of Ops email."

---

## Common Mistakes (SaaS)

1. **Buying lists from Apollo wholesale** without re-verifying email and re-checking firmographics. Stale data is the norm.
2. **Treating tech stack data as 100% accurate**. BuiltWith and Wappalyzer miss things; Clay's waterfalls miss things. Cross-check.
3. **Targeting Series C+ for early-stage SaaS sellers**. The buyer profile is wrong — too many procurement hoops, too much red tape.
4. **Targeting Series Pre-Seed seed** for products requiring meaningful budget. They have neither budget nor evaluator bandwidth.
5. **Ignoring intent data when it exists** (ZoomInfo Intent, 6sense, etc.) — pre-warm signals beat cold every time.
