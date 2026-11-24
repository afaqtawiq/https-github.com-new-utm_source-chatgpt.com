# Reference files for the `ai-seo` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/agent-readiness.md

# Agent Readiness — Can an Agent Reach, Navigate, and Parse Your Site?

AI visibility work splits into two layers: what your content says (the rest of this skill) and whether an agent can *get to it at all*. This reference covers the second layer — the access/discovery/parseability audit — plus the emerging shift from agent-*readable* to agent-*actionable* sites.

Two free scoring tools shipped in August 2026 and turned this into a measurable discipline:

| Tool | Run it | Method |
|---|---|---|
| **Is Agentic** (Vercel + Ora) | `npx is-agentic yourdomain.com` or [is-agentic.com](https://is-agentic.com) | 100+ checks; Essential checks carry most of the score; Recommended checks activate only when evidence shows you have that surface (API, MCP server, commerce); not-applicable checks are excluded, not failed; includes an observed agent journey showing where a real agent hit friction |
| **Frase Agent Readiness Checker** | [frase.io/tools/agent-readiness](https://www.frase.io/tools/agent-readiness) | Access / Discovery / Parseability triad; 80+ = agents can reliably use the site, 60–79 = solid with gaps, <60 = real access problems |

Run one before and after any agent-readiness work — the score is a shareable artifact and the failed checks are your worklist. (Both are vendor tools with a product behind them; the *checks* are the value, not the pitch.)

## The three questions

### 1. Access — can an agent get to the page and see real content?

- **Core content in the initial HTML response.** Most agents never execute JavaScript. If the content only exists after client-side rendering, it doesn't exist. This is the #1 essential check in both tools.
- **No bot challenge or firewall block** on the request path. Aggressive bot protection (Cloudflare challenges, WAF rules) that blocks `GPTBot`, `PerplexityBot`, `ClaudeBot`, etc. is self-inflicted invisibility. Audit what your CDN/WAF actually does to those user agents — many sites block them by default without anyone deciding to.
- **Correct HTTP behavior**: real status codes (no soft-404s), stable canonical URLs, recoverable errors.

### 2. Discovery — do your files tell agents what's here?

- **robots.txt with an explicit AI-crawler stance** — name the major AI crawlers and state your policy, rather than leaving it to be assumed (see the bot-access table in SKILL.md for the allow/block list).
- **A sitemap that loads and parses cleanly.**
- **llms.txt at the domain root** (see Machine-Readable Files in SKILL.md).
- **`llms-full.txt`** — the newer companion: your entire site content in one file, so an agent gets everything in a single request instead of crawling. Emerging, cheap to generate alongside llms.txt, and scored as bonus signal by both tools.
- **robots.txt content-usage statements** — an emerging convention for declaring what AI may do with your content (train / cite / summarize), so the answer comes from you instead of being assumed.

### 3. Parseability — once there, can the agent tell what the page is?

- **Valid, substantive structured data** (JSON-LD — see the `schema` skill).
- **A Markdown representation of the page.** This is the newest technique in the stack, two implementations:
  - **Content negotiation**: serve compact Markdown at the *same canonical URL* when the request asks for `Accept: text/markdown`, with a `Vary` header keeping the HTML and Markdown cache entries separate. (This is how Is Agentic serves its own reports — agents get Markdown, browsers get HTML, one URL.)
  - **Link header**: an HTTP `Link` header on the HTML page pointing to a parallel Markdown version — discoverable without guessing URLs.
- Clear document structure — one H1, headings that answer sub-questions, extractable answer blocks (the content-patterns reference).

## Emerging: agent-actionable, not just agent-readable

Reading is becoming table stakes. The next race is whether an agent can *act* on your site — fill the form, book the meeting, start the trial. **WebMCP** is the emerging standard here: a page declares its forms and CTAs as callable tools with input schemas, so an agent doesn't have to reverse-engineer your UI. Early days (label: emerging, not yet a ranking/citation signal), but the direction is clear — if agents are becoming buyers, the site that exposes "start trial" as a structured action wins the agent-mediated conversion that a pretty button loses.

Practical today: make sure your highest-intent actions (signup, pricing, demo booking, contact) work without JavaScript-only flows, have labeled semantic form fields, and return machine-readable confirmation.

## Citation-source volatility (why you diversify)

Third-party citation mixes are **not stable** — they shift overnight with model and retrieval updates, and August 2026 provided the case study: **ChatGPT's query fan-out changes nearly wiped Reddit as a citation source** within days (practitioner-reported by multiple AEO teams; one had been earning 24-hour citations from Reddit at 1M+ impressions/month before the change). Meanwhile the same practitioners report **business-owned websites dominate Gemini citations (~60%)**.

What this means for strategy:

- **Never concentrate AI-visibility work in one third-party surface.** The Presence pillar's list (Wikipedia, Reddit, YouTube, podcasts, review sites, Quora) is a portfolio, not a menu to pick one from. A surface that's 2% of citations today can be 0% after one retrieval update — or vice versa.
- **Owned-site fundamentals hedge the volatility.** Platform deals and retrieval changes reshuffle third-party sources; your own agent-readable site is the one surface no platform can drop you from — and on Gemini it's already the dominant citation class.
- **Treat any citation-share statistic as dated.** The "Reddit = 1.8% of ChatGPT citations" class of stats (including the ones in this skill) are snapshots — check the date, and verify against your own citation monitoring (the DIY monitoring loop in SKILL.md) before betting budget on them.
- **Speed is real**: fresh content on retrieved surfaces can be cited within ~24 hours. AI search rewards freshness faster than classic SEO ever did.

---

*Agent-readiness check taxonomy distilled from Vercel/Ora's Is Agentic (is-agentic.com) and Frase's Agent Readiness Checker (both August 2026, credited); citation-volatility events practitioner-reported (Ashni of Hype Partners (@ashnichrist) and others, August 2026) — labeled accordingly, verify against your own monitoring.*


---

# references/citations-vs-recommendations.md

# Citations vs. Recommendations: The AI Visibility Ladder

Being cited by an AI engine and being recommended by it are **two different outcomes governed by two different systems**. A citation means your page was useful enough to pull information from. A recommendation means the model put your brand on the buyer's shortlist. Optimizing for the first does not automatically earn the second — and for smaller brands, conflating them leads to content strategies that can actively help competitors.

Source note: the analysis and data in this reference draw on Lily Ray's (Amsive) 2026 study of B2B "best [category] software" queries, behavioral studies by Scrunch and SimilarWeb, and commentary by John-Henry Scherck (Growth Plays).

---

## The Visibility Ladder

AI visibility is a ladder, not a binary. Each rung has different selection criteria and different measurement:

| Rung | What it means | What governs it | How to see it |
|---|---|---|---|
| **1. Retrieved** | The model read your content while building its answer, without citing it | Crawlability, parseable structure, query relevance | Mostly invisible; bot logs hint at it |
| **2. Cited** | Your page appears as a source in the answer | Content usefulness: structure, statistics, clarity, freshness | Prompt-tracking tools, AI Overview source lists |
| **3. Mentioned** | Your brand is named in the answer text | Entity recognition + how the web talks about you | Prompt-tracking tools |
| **4. Recommended** | Your product is on the shortlist the buyer actually considers | **Aggregate web consensus** — reviews, forums, analysts, press, video — largely independent of your own content | Prompt tracking + the framing around the mention |

Rungs 1–3 are legitimate signals your content is working, and most prompt-tracking tools report them. But rung 4 is where buying behavior changes, and it's earned differently: **citation is about whether your content is useful to consult; recommendation is mostly a reflection of what the broader web says about you** — whether you published a guide on the topic or not.

There is also a shadow rung: **recommended against**. On detailed, requirements-heavy prompts, models increasingly name products a buyer should *avoid* for their use case, with sources. The downside of weak third-party consensus is no longer just absence from the shortlist — it can be an explicit rule-out. This makes monitoring the *framing* around your mentions (favorable / neutral / hedged / negative), not just counting them, part of the job.

---

## The Self-Promotional Listicle Risk

The common tactic — publish a "best [category] software" guide, rank yourself #1, and let it shape both organic search and AI answers — now has a stage-dependent payoff.

**The data:** Lily Ray (Amsive) analyzed 100 B2B "best [category] software" queries across three dates in spring 2026. Across the dataset, self-promotional listicles earned 323 citations in AI Overviews — and in 224 of them (**69% of the citations**), the answer left the publishing brand out of the recommendations, pointing buyers to competitors instead.

**The mechanism:** the model treats your guide as a source about the *category*. It happily extracts the competitor names, comparisons, and evaluation criteria you compiled — then makes its recommendation from web-wide consensus, where the established players dominate. For an emerging brand, a self-promotional buyer's guide can function as **a vote for your competitors**: you did the research that helps the model describe them.

**The split by stage:**

- **Established category leaders** get both outcomes. Their guides earn citations *and* their brands get recommended — because analysts, review sites, and forum discussions already validate them. For leaders, a definitive buyer's guide is highly advantageous: it shapes how the whole category (competitors included) gets described.
- **Emerging brands** may win the citation and even shape the category's framing, but miss the recommendation. That's not a wasted outcome — influencing how an LLM defines the category and its evaluation criteria is real positioning work — but it is not the shortlist placement the tactic promises.

**What this changes (and doesn't):** genuinely useful buyer's guides still belong in a B2B content strategy at any stage. What changes is the expectation and the investment split. If you're not yet the consensus pick, weight effort toward the offsite signals that actually govern recommendations (below) rather than publishing a plethora of self-ranked listicles.

---

## What Earns Recommendations

Recommendation is a consensus signal. The inputs the models weigh live mostly off your site:

| Channel | Why it moves recommendations | Related skill |
|---|---|---|
| **Review platforms** (G2, Capterra, TrustRadius, app stores) | Third-party validation models treat as evidence of legitimacy | customer-research (review generation loops) |
| **Analyst coverage** (Gartner, Forrester, industry reports) | High-authority category framing; models echo analyst shortlists | public-relations |
| **Communities and forums** (Reddit, HN, Slack/Discord, niche forums) | Unprompted practitioner discussion is heavily retrieved and hard to fake | community-marketing |
| **Earned media and PR** | Independent sources repeating your positioning beyond your own site | public-relations |
| **Video and podcasts** | Increasingly retrieved; transcripts carry brand + category associations | video, social |

The test to apply before investing in another self-ranked guide: *if a model ignored everything on our domain, would the rest of the web still put us on the shortlist?* If not, that gap is the priority. AEO discourse often stops at "are we in the answer?" — the better question is "are we credible enough to be recommended?"

The encouraging flip side: earning an AI recommendation is harder to game than a top search ranking ever was. The durable strategy is the same at every stage — be the best fit for a clear set of buyers, and give those buyers reasons to talk about you in public, where the models can retrieve it.

---

## What a Recommendation Is Worth

Two behavioral studies quantified the gap between rungs:

- **Scrunch** (opt-in panel linking AI conversations to subsequent web behavior, compared against each user's own baseline — observational, not a controlled experiment): a genuine recommendation ("a great option is X") was associated with people searching for, visiting, and evaluating a brand **about twice as often** as a passing mention. For users with no recent observed engagement with the brand, a recommendation was followed within a week by **+182% branded searches, +117% site visits, and +185% product views**.
- **SimilarWeb** (thousands of real user journeys, seven days post-answer): when ChatGPT recommended a brand, it received **roughly 2.5× more new visitors** the following week than the competitors left off the list.

**The attribution blind spot:** in the SimilarWeb data, only about **9%** of those post-recommendation visits arrived as visible AI referral traffic; the largest share arrived via branded search, with direct and other channels making up the rest — indistinguishable from ordinary organic visitors. AI recommendations are already sending real, engaged buyers, but standard attribution underreports the AI touch.

**Measurement triad** (no single signal is complete; together they give a reliable read):

1. **AI prompt tracking** — whether and how you're mentioned/recommended in LLM answers, even when no click ever lands (tools in SKILL.md's Monitoring section). Track the framing around mentions — recommended, neutral, hedged, or recommended-against — not just the count.
2. **Self-reported attribution** — a "how did you hear about us?" field catches buyers whose journey started in an AI chat but arrived via branded search or direct.
3. **Sales call recordings** — buyers' own language often reveals an AI conversation shaped the shortlist long before any form fill.

Also watch **branded search volume** as a proxy: sustained lifts without a matching campaign are increasingly AI-influence showing up under another name.

---

## Applying This

- **Auditing an established brand:** buyer's guides and comparison content are high-leverage — publish the definitive version and shape the category's evaluation criteria.
- **Auditing an emerging brand:** publish the genuinely useful guides your ICP needs, but set expectations (citation and framing, not near-term recommendation) and rebalance investment toward reviews, communities, analysts, and earned media.
- **Reporting:** report the ladder, not a single "AI visibility" number — retrieved/cited/mentioned/recommended plus mention framing. A rising citation count with a flat recommendation rate is a specific, diagnosable gap: the web doesn't yet corroborate your content.
- **Risk check:** for requirements-heavy queries in your category, check whether models recommend *against* you, and trace the sources they cite when they do.


---

# references/content-patterns.md

# AEO and GEO Content Patterns

Reusable content block patterns optimized for answer engines and AI citation.

---

## Contents
- Answer Engine Optimization (AEO) Patterns (Definition Block, Step-by-Step Block, Comparison Table Block, Pros and Cons Block, FAQ Block, Listicle Block)
- Generative Engine Optimization (GEO) Patterns (Statistic Citation Block, Expert Quote Block, Authoritative Claim Block, Self-Contained Answer Block, Evidence Sandwich Block)
- Domain-Specific GEO Tactics (Technology Content, Health/Medical Content, Financial Content, Legal Content, Business/Marketing Content)
- Voice Search Optimization (Question Formats for Voice, Voice-Optimized Answer Structure)

## Answer Engine Optimization (AEO) Patterns

These patterns help content appear in featured snippets, AI Overviews, voice search results, and answer boxes.

### Definition Block

Use for "What is [X]?" queries.

```markdown
## What is [Term]?

[Term] is [concise 1-sentence definition]. [Expanded 1-2 sentence explanation with key characteristics]. [Brief context on why it matters or how it's used].
```

**Example:**
```markdown
## What is Answer Engine Optimization?

Answer Engine Optimization (AEO) is the practice of structuring content so AI-powered systems can easily extract and present it as direct answers to user queries. Unlike traditional SEO that focuses on ranking in search results, AEO optimizes for featured snippets, AI Overviews, and voice assistant responses. This approach has become essential as over 60% of Google searches now end without a click.
```

### Step-by-Step Block

Use for "How to [X]" queries. Optimal for list snippets.

```markdown
## How to [Action/Goal]

[1-sentence overview of the process]

1. **[Step Name]**: [Clear action description in 1-2 sentences]
2. **[Step Name]**: [Clear action description in 1-2 sentences]
3. **[Step Name]**: [Clear action description in 1-2 sentences]
4. **[Step Name]**: [Clear action description in 1-2 sentences]
5. **[Step Name]**: [Clear action description in 1-2 sentences]

[Optional: Brief note on expected outcome or time estimate]
```

**Example:**
```markdown
## How to Optimize Content for Featured Snippets

Earning featured snippets requires strategic formatting and direct answers to search queries.

1. **Identify snippet opportunities**: Use tools like Semrush or Ahrefs to find keywords where competitors have snippets you could capture.
2. **Match the snippet format**: Analyze whether the current snippet is a paragraph, list, or table, and format your content accordingly.
3. **Answer the question directly**: Provide a clear, concise answer (40-60 words for paragraph snippets) immediately after the question heading.
4. **Add supporting context**: Expand on your answer with examples, data, and expert insights in the following paragraphs.
5. **Use proper heading structure**: Place your target question as an H2 or H3, with the answer immediately following.

Most featured snippets appear within 2-4 weeks of publishing well-optimized content.
```

### Comparison Table Block

Use for "[X] vs [Y]" queries. Optimal for table snippets.

```markdown
## [Option A] vs [Option B]: [Brief Descriptor]

| Feature | [Option A] | [Option B] |
|---------|------------|------------|
| [Criteria 1] | [Value/Description] | [Value/Description] |
| [Criteria 2] | [Value/Description] | [Value/Description] |
| [Criteria 3] | [Value/Description] | [Value/Description] |
| [Criteria 4] | [Value/Description] | [Value/Description] |
| Best For | [Use case] | [Use case] |

**Bottom line**: [1-2 sentence recommendation based on different needs]
```

### Pros and Cons Block

Use for evaluation queries: "Is [X] worth it?", "Should I [X]?"

```markdown
## Advantages and Disadvantages of [Topic]

[1-sentence overview of the evaluation context]

### Pros

- **[Benefit category]**: [Specific explanation]
- **[Benefit category]**: [Specific explanation]
- **[Benefit category]**: [Specific explanation]

### Cons

- **[Drawback category]**: [Specific explanation]
- **[Drawback category]**: [Specific explanation]
- **[Drawback category]**: [Specific explanation]

**Verdict**: [1-2 sentence balanced conclusion with recommendation]
```

### FAQ Block

Use for topic pages with multiple common questions. Essential for FAQ schema.

```markdown
## Frequently Asked Questions

### [Question phrased exactly as users search]?

[Direct answer in first sentence]. [Supporting context in 2-3 additional sentences].

### [Question phrased exactly as users search]?

[Direct answer in first sentence]. [Supporting context in 2-3 additional sentences].

### [Question phrased exactly as users search]?

[Direct answer in first sentence]. [Supporting context in 2-3 additional sentences].
```

**Tips for FAQ questions:**
- Use natural question phrasing ("How do I..." not "How does one...")
- Include question words: what, how, why, when, where, who, which
- Match "People Also Ask" queries from search results
- Keep answers between 50-100 words

### Listicle Block

Use for "Best [X]", "Top [X]", "[Number] ways to [X]" queries.

**Caveat for self-promotional listicles:** ranking yourself #1 in your own "best [category]" guide gets the page *cited* far more reliably than it gets your brand *recommended* — for emerging brands, AI answers often harvest the competitor names from the guide and recommend them instead. See [citations-vs-recommendations.md](citations-vs-recommendations.md) before building these at scale.

```markdown
## [Number] Best [Items] for [Goal/Purpose]

[1-2 sentence intro establishing context and selection criteria]

### 1. [Item Name]

[Why it's included in 2-3 sentences with specific benefits]

### 2. [Item Name]

[Why it's included in 2-3 sentences with specific benefits]

### 3. [Item Name]

[Why it's included in 2-3 sentences with specific benefits]
```

---

## Generative Engine Optimization (GEO) Patterns

These patterns optimize content for citation by AI assistants like ChatGPT, Claude, Perplexity, and Gemini.

### Statistic Citation Block

Statistics increase AI citation rates by 15-30%. Always include sources.

```markdown
[Claim statement]. According to [Source/Organization], [specific statistic with number and timeframe]. [Context for why this matters].
```

**Example:**
```markdown
Mobile optimization is no longer optional for SEO success. According to Google's 2024 Core Web Vitals report, 70% of web traffic now comes from mobile devices, and pages failing mobile usability standards see 24% higher bounce rates. This makes mobile-first indexing a critical ranking factor.
```

### Expert Quote Block

Named expert attribution adds credibility and increases citation likelihood.

```markdown
"[Direct quote from expert]," says [Expert Name], [Title/Role] at [Organization]. [1 sentence of context or interpretation].
```

**Example:**
```markdown
"The shift from keyword-driven search to intent-driven discovery represents the most significant change in SEO since mobile-first indexing," says Rand Fishkin, Co-founder of SparkToro. This perspective highlights why content strategies must evolve beyond traditional keyword optimization.
```

### Authoritative Claim Block

Structure claims for easy AI extraction with clear attribution.

```markdown
[Topic] [verb: is/has/requires/involves] [clear, specific claim]. [Source] [confirms/reports/found] that [supporting evidence]. This [explains/means/suggests] [implication or action].
```

**Example:**
```markdown
E-E-A-T is the cornerstone of Google's content quality evaluation. Google's Search Quality Rater Guidelines confirm that trust is the most critical factor, stating that "untrustworthy pages have low E-E-A-T no matter how experienced, expert, or authoritative they may seem." This means content creators must prioritize transparency and accuracy above all other optimization tactics.
```

### Self-Contained Answer Block

Create quotable, standalone statements that AI can extract directly.

```markdown
**[Topic/Question]**: [Complete, self-contained answer that makes sense without additional context. Include specific details, numbers, or examples in 2-3 sentences.]
```

**Example:**
```markdown
**Ideal blog post length for SEO**: The optimal length for SEO blog posts is 1,500-2,500 words for competitive topics. This range allows comprehensive topic coverage while maintaining reader engagement. HubSpot research shows long-form content earns 77% more backlinks than short articles, directly impacting search rankings.
```

### Evidence Sandwich Block

Structure claims with evidence for maximum credibility.

```markdown
[Opening claim statement].

Evidence supporting this includes:
- [Data point 1 with source]
- [Data point 2 with source]
- [Data point 3 with source]

[Concluding statement connecting evidence to actionable insight].
```

---

## Domain-Specific GEO Tactics

Different content domains benefit from different authority signals.

### Technology Content
- Emphasize technical precision and correct terminology
- Include version numbers and dates for software/tools
- Reference official documentation
- Add code examples where relevant

### Health/Medical Content
- Cite peer-reviewed studies with publication details
- Include expert credentials (MD, RN, etc.)
- Note study limitations and context
- Add "last reviewed" dates

### Financial Content
- Reference regulatory bodies (SEC, FTC, etc.)
- Include specific numbers with timeframes
- Note that information is educational, not advice
- Cite recognized financial institutions

### Legal Content
- Cite specific laws, statutes, and regulations
- Reference jurisdiction clearly
- Include professional disclaimers
- Note when professional consultation is advised

### Business/Marketing Content
- Include case studies with measurable results
- Reference industry research and reports
- Add percentage changes and timeframes
- Quote recognized thought leaders

---

## Voice Search Optimization

Voice queries are conversational and question-based. Optimize for these patterns:

### Question Formats for Voice
- "What is..."
- "How do I..."
- "Where can I find..."
- "Why does..."
- "When should I..."
- "Who is..."

### Voice-Optimized Answer Structure
- Lead with direct answer (under 30 words ideal)
- Use natural, conversational language
- Avoid jargon unless targeting expert audience
- Include local context where relevant
- Structure for single spoken response


---

# references/content-types.md

# AI SEO by Content Type

Tactical guidance for optimizing specific content types for AI search citation. These tactics work for non-Google AI engines (ChatGPT, Claude, Perplexity, Copilot) and don't hurt Google AI Overviews / AI Mode.

For the cross-cutting strategy, see [SKILL.md](../SKILL.md).

---

## SaaS Product Pages

**Goal:** Get cited in "What is [category]?" and "Best [category]" queries. (Citation is the realistic goal here; being *recommended* in the answer depends on offsite consensus — see [citations-vs-recommendations.md](citations-vs-recommendations.md).)

**Optimize:**
- Clear product description in first paragraph (what it does, who it's for)
- Feature comparison tables (you vs. category, not just competitors)
- Specific metrics ("processes 10,000 transactions/sec" not "blazing fast")
- Customer count or social proof with numbers
- Pricing transparency (AI cites pages with visible pricing) — add a `/pricing.md` file so AI agents can parse your plans without rendering your page (see "Machine-Readable Files" in the main skill)
- FAQ section addressing common buyer questions

---

## Blog Content

**Goal:** Get cited as an authoritative source on topics in your space.

**Optimize:**
- One clear target query per post (match heading to query)
- Definition in first paragraph for "What is" queries
- Original data, research, or expert quotes
- "Last updated" date visible
- Author bio with relevant credentials
- Internal links to related product/feature pages

---

## Comparison / Alternative Pages

**Goal:** Get cited in "[X] vs [Y]" and "Best [X] alternatives" queries.

**Optimize:**
- Structured comparison tables (not just prose)
- Fair and balanced (AI penalizes obviously biased comparisons)
- Specific criteria with ratings or scores
- Updated pricing and feature data
- Cite the `competitors` skill for building these pages

---

## Documentation / Help Content

**Goal:** Get cited in "How to [X] with [your product]" queries.

**Optimize:**
- Step-by-step format with numbered lists
- Code examples where relevant
- HowTo schema markup
- Screenshots with descriptive alt text
- Clear prerequisites and expected outcomes

---

## Local Business / Ecom (Google emphasis)

Google's AI features pull from product feeds and business profiles for local + ecom queries. Optimize:

- **Merchant Center feeds** kept current with accurate inventory, pricing, attributes
- **Google Business Profile** complete with hours, services, photos, posts, Q&A answered
- **Reviews** — recent + sufficient volume; respond to reviews to signal active management
- **Service area schema** for local services
- **Business Agent** (where available) for conversational customer engagement


---

# references/format-volatility.md

# Format Volatility — Which Content Formats AI Cites (and How Fast That Changes)

Citation-*source* volatility (Reddit wiped overnight, Gemini favoring owned sites) is covered in [agent-readiness.md](agent-readiness.md). This reference covers the second volatility axis: citation-*format* — which page types AI engines retrieve and cite, and the August 2026 evidence that heavily-exploited formats get demoted.

Read this before recommending comparison pages, listicles, or "best X" content for AI visibility. The advice changed materially with ChatGPT 5.6.

## The ChatGPT 5.6 format shift (August 2026)

Data from Peec AI (shared by Tomek Rudzki via Lily Ray, Aug 2026), comparing ChatGPT retrieval behavior before and after the 5.6 launch:

**Fan-out queries** — the modifiers that declined most as a share of ChatGPT's background searches:

- "vs"
- "comparison"
- "top"
- "best"
- "reviews"

At the same time: a surge in `site:` searches and modifiers like **"official"**.

**Citations by page type** — share of total ChatGPT citations:

| Page type | Pre-5.6 | Post-5.6 | Change |
|---|---:|---:|---:|
| Listicles ("Top 10 X," "8 best Y") | 15.77% | 7.80% | **−50.5%** |
| Comparison pages ("X vs Y," alternatives) | 9.08% | 6.17% | **−32.1%** |

The interpretation (Lily Ray's, and it fits the fan-out data): these are exactly the two formats companies scaled for GEO over the prior 18 months, and ChatGPT adjusted retrieval to mitigate the spam. The `site:`/"official" surge points the same direction — **toward primary sources and owned domains, away from aggregator formats**.

## What this changes (and what it doesn't)

**It does NOT mean "stop making comparison pages."** Comparison and best-of content still:

- Converts human buyers (its original job)
- Gets cited by Google AI Overviews (which follow core rankings, not ChatGPT's retrieval)
- Feeds Gemini and Perplexity, which haven't shown the same demotion
- Answers real mid-funnel queries on your own site

**It DOES mean:**

1. **Stop justifying scaled listicle/comparison production with "it wins AI citations."** On ChatGPT — the largest AI answer surface — that rationale lost half its force in one release.
2. **The "official"/primary-source shift favors your owned pages.** Product pages, docs, pricing pages, original research — the pages only you can publish — are rising as the citable class. This compounds the Gemini finding (business-owned sites ≈ 60% of citations).
3. **Format strategy is now per-platform.** Check which engines matter for your category before choosing formats:

| Format | ChatGPT (post-5.6) | Google AIO | Gemini | Perplexity |
|---|---|---|---|---|
| Listicles / best-of | Demoted | Rankings-dependent | OK | OK |
| Comparison / vs pages | Demoted | Rankings-dependent | OK | OK |
| Original research + data | Strong | Strong | Strong | Strong |
| Product/docs/pricing (owned, "official") | **Rising** | Strong | **Dominant** | Strong |
| How-to / guides | Steady | Strong | OK | Strong |

*(Table caveat: the demotion was measured on ChatGPT only. "OK" for Gemini/Perplexity means no demotion has been reported there — not that stability was measured. Any engine can ship its own 5.6-style shift.)*

4. **Treat every number above as a dated snapshot.** Same doctrine as source volatility: these are Aug 2026 measurements of a moving system. Verify against your own citation monitoring before betting budget.

## LinkedIn as a citation surface (from LinkedIn's own AEO guide)

LinkedIn quietly published its own AEO/AI-search guidance (surfaced by Chris Long, Sep 2026). The platform-reported numbers:

- LinkedIn is the **most-cited outlet for professional-topic searches**
- **~60% of LinkedIn citations come from Articles**, ~40% from Posts
- Post URLs use the **first words of the post as the slug**

**Tactics:**

- For professional/B2B topics, LinkedIn Articles are a first-class Presence-pillar surface — treat long-form Articles (not just feed posts) as citable assets with the same extractable structure as blog content.
- **Front-load the target phrase in a post's opening words** — they become the URL slug, which is retrieval surface.
- This is platform-reported data (LinkedIn grading its own homework); weight accordingly, but the Articles > Posts split matches the general pattern that long-form structured content out-cites feed content.

## DIY diagnostic: extract ChatGPT's real fan-out queries

You don't need a tool to see what ChatGPT actually searches for in your niche (method circulating publicly, Aug 2026):

1. Run an important query for your category in ChatGPT (with search).
2. Open DevTools → Network tab, refresh the conversation (URL id after `/c/`).
3. Find the conversation response payload and search it for `queries`.
4. You'll see the literal background searches ChatGPT fanned out to.

**Use it for:** building your query-test list from *real* fan-out behavior instead of guesses; checking whether your category's fan-outs still use "best/vs" modifiers or have shifted to `site:`/"official" patterns; finding sub-topics your content doesn't cover.

**Do not use it for:** auto-generating and mass-publishing an article per fan-out query. That's the exact scaled-content pattern 5.6 demoted (and Google's scaled content abuse policy names). The diagnostic is for coverage planning, not content spam.

## Measurement rigor: AI answers are non-deterministic

A single ChatGPT answer is an anecdote, not a measurement — the same prompt returns different sources run-to-run. (The statistical-rigor framing here is popularized by Initial Commit's AEO audit skill, Josh Pigford, Aug 2026; the practice stands on its own.)

When auditing or monitoring:

- **Run each query 3–5 times per platform**, fresh session each time.
- **Track mention/citation *rate*** ("cited in 3 of 5 runs"), never a yes/no from one run.
- **Report the sample size** with every number ("40% mention rate, n=5") so future-you knows how much to trust it.
- **Compare rates over time, not runs.** A drop from 4/5 to 3/5 is noise; a drop from 4/5 to 0/5 sustained across a month is signal.
- Before diagnosing *why* you're not cited, split causes the way an audit should: **technical** (can't be crawled/parsed — see agent-readiness.md), **comprehension** (AI describes you inaccurately or vaguely), or **trust** (understood but not selected — see citations-vs-recommendations.md).

---

*Sources, all labeled and dated: Peec AI pre/post-5.6 citation data via Tomek Rudzki and Lily Ray (Aug 2026); LinkedIn's AEO guide numbers via Chris Long (Sep 2026, platform-reported); fan-out extraction method as publicly circulated (Aug 2026); measurement-rigor framing credited to Initial Commit's AEO audit skill (Josh Pigford, Aug 2026). All snapshots of a volatile system — verify against your own monitoring.*


---

# references/okf.md

# Open Knowledge Format (OKF)

Google's v0.1 markdown spec for representing site content as an agent-readable bundle. Introduced on the [Google Cloud blog](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing) on 2026-06-12 and shipped inside Knowledge Catalog.

## What it is

OKF is a directory of cross-linked markdown files. Each file has:

- A YAML frontmatter block (`type` required; `title`, `description`, `resource`, `tags`, `timestamp` recommended)
- A standard markdown body
- Standard markdown links to other files in the bundle (which the spec treats as concept relationships)

An optional `index.md` lists the files for progressive disclosure. The bundle can be distributed as a git repo (recommended), a tarball/zip, or a subdirectory of a larger repo.

The [full spec](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/HEAD/okf/SPEC.md) fits on one page. The repo lives under `GoogleCloudPlatform` (the "not an official Google product" disclaimer is Google's standard open-source boilerplate, not a denial — it appears on most of Google's open-source repos including their main AI samples repo).

### A minimal concept file

```markdown
---
type: Article
title: How to Connect the Ahrefs MCP Server to Manus
description: The official MCP servers, why they did not connect, and the fix.
resource: https://yoursite.com/blog/ahrefs-mcp-manus/
tags: [mcp, ahrefs]
---

# How to Connect the Ahrefs MCP Server to Manus

The body of the post, as clean markdown.
```

Add an `index.md` that lists all files so an agent can see the bundle's shape before opening each file, and that is the entire format.

## Honest framing

**Google built OKF for data teams sharing catalog metadata** — BigQuery tables, API endpoints, metrics, playbooks. Most of the spec's examples are data-team artifacts, not blog posts. Google's blog post framing: "improve data sharing" and "standardized documentation" for collaboration across teams.

Pointing OKF at a marketing site is a **clever repurposing** popularized by [Suganthan Mohanadasan](https://suganthan.com/blog/open-knowledge-format/). It's a legitimate use case for the format but not Google's primary one. Frame it accurately when explaining it to founders or marketing teams.

## What it does for AI search today

Nothing immediate. Nothing crawls the web for OKF bundles yet — the spec is weeks old, no AI engine has announced integration, and Knowledge Catalog ingests bundles only for paying enterprise customers' data teams.

Treat OKF as **protocol-layer registration** — the same shape of bet as early `schema.org` adoption was a decade ago. Schema took the better part of ten years to pay off; people who shipped it early are still glad they did.

A secondary benefit that pays off today regardless: **generating the bundle is itself an internal-linking audit**. Suganthan's tool draws every page as a node and every internal link as an edge, so islands and orphans become obvious at a glance.

## Where OKF fits in the agent-readable stack

| Layer | Purpose |
|---|---|
| `sitemap.xml` | Tells a crawler which URLs exist |
| `robots.txt` (with AI bot rules) | Permits or blocks AI crawlers |
| `llms.txt` | Points an agent at the handful of pages you most want read |
| `/pricing.md` | Structured pricing for agent-buyer comparisons |
| **`/okf/` bundle** | Hands over the content itself as cross-linked concepts |
| Schema markup | Per-page structured data (Article, FAQPage, Product, etc.) |

These stack rather than compete. `llms.txt` is a signpost, OKF is the library.

## How to ship one

Three options, ordered by how much effort they take:

### 1. Suganthan's free web tool (recommended for most sites)

[suganthan.com/okf-generator](https://suganthan.com/okf-generator/) — paste a URL or sitemap, crawls up to 100 pages, returns a downloadable bundle. Also draws the resulting page graph so you can spot disconnected pages before publishing.

### 2. WordPress plugin (pending wp.org approval)

Suganthan's plugin (free, GPL, awaiting wp.org approval at time of writing) installs in a minute, serves the bundle at `/okf/`, and rebuilds on every publish or edit so it stays in sync. Direct download link is in [his blog post](https://suganthan.com/blog/open-knowledge-format/). Requires WordPress 6.0+ and PHP 7.4+. Read-only — never edits posts or settings.

### 3. By hand

Only practical for a handful of pages. Each post becomes a markdown file with frontmatter that you cross-link manually. Miserable for a whole site.

## Hosting & discovery

Serve the bundle at `yoursite.com/okf/`, starting with `yoursite.com/okf/index.md`:

- **Static hosts / Cloudflare**: drag and drop
- **WordPress**: Suganthan's plugin handles the serving
- **Static sites with custom paths**: upload the directory to `/okf/`
- **Closed platforms (Wix, Squarespace, most page-builders)**: you usually can't serve files at custom paths — skip OKF entirely

After it's serving, add a line to `llms.txt` pointing to the bundle so agents that read `llms.txt` (today) can discover the bundle (later).

## When to skip

- Site is <10 pages — overhead exceeds payoff
- Site is on a closed platform that won't allow custom paths
- You're not maintaining `llms.txt`, schema markup, or other machine-readable files (OKF compounds with those; alone it does nothing)
- You can't budget the 30 minutes a quarter to refresh the bundle as content changes

## What to watch

OKF is v0.1, weeks old. Worth tracking, not worth obsessing over:

- Whether Google announces OKF support in AI Overviews / Knowledge Graph (currently no signal)
- Whether non-Google engines (ChatGPT, Perplexity, Claude) announce OKF reading
- Whether the spec moves to v1.0 (breaking changes are possible at <1.0)
- Whether Knowledge Catalog adds public ingestion endpoints
- Adoption signals — search GitHub for `okf/index.md` to see who's shipping bundles


---

# references/platform-ranking-factors.md

# How Each AI Platform Picks Sources

Each AI search platform has its own search index, ranking logic, and content preferences. This guide covers what matters for getting cited on each one.

Sources cited throughout: Princeton GEO study (KDD 2024), SE Ranking domain authority study, ZipTie content-answer fit analysis.

---

## The Fundamentals

Every AI platform shares three baseline requirements:

1. **Your content must be in their index** — Each platform uses a different search backend (Google, Bing, Brave, or their own). If you're not indexed, you can't be cited.
2. **Your content must be crawlable** — AI bots need access via robots.txt. Block the bot, lose the citation.
3. **Your content must be extractable** — AI systems pull passages, not pages. Clear structure and self-contained paragraphs win.

Beyond these basics, each platform weights different signals. Here's what matters and where.

---

## Google AI Overviews

Google AI Overviews pull from Google's own index and lean heavily on E-E-A-T signals (Experience, Expertise, Authoritativeness, Trustworthiness). They appear in roughly 45% of Google searches.

**What makes Google AI Overviews different:** They already have your traditional SEO signals — backlinks, page authority, topical relevance. The additional AI layer adds a preference for content with cited sources and structured data. Research shows that including authoritative citations in your content correlates with a 132% visibility boost, and writing with an authoritative (not salesy) tone adds another 89%.

**Importantly, AI Overviews don't just recycle the traditional Top 10.** Only about 15% of AI Overview sources overlap with conventional organic results. Pages that wouldn't crack page 1 in traditional search can still get cited if they have strong structured data and clear, extractable answers.

**What to focus on:**
- Schema markup is the single biggest lever — Article, FAQPage, HowTo, and Product schemas give AI Overviews structured context to work with (30-40% visibility boost)
- Build topical authority through content clusters with strong internal linking
- Include named, sourced citations in your content (not just claims)
- Author bios with real credentials matter — E-E-A-T is weighted heavily
- Get into Google's Knowledge Graph where possible (an accurate Wikipedia entry helps)
- Target "how to" and "what is" query patterns — these trigger AI Overviews most often

**Watch for OKF.** In June 2026 Google introduced the [Open Knowledge Format](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing) — a markdown spec for agent-readable site bundles. There is no confirmed signal that AI Overviews factor it in today, but the spec is published, the GitHub repo lives under `GoogleCloudPlatform`, and it ships inside Knowledge Catalog. For protocol-layer "register early" plays, it has the same shape as early schema.org adoption did a decade ago. See **Machine-Readable Files for AI Agents** in the main `SKILL.md` for how to generate and serve a bundle.

---

## ChatGPT

ChatGPT's web search draws from a Bing-based index. It combines this with its training knowledge to generate answers, then cites the web sources it relied on.

**What makes ChatGPT different:** Domain authority matters more here than on other AI platforms. An SE Ranking analysis of 129,000 domains found that authority and credibility signals account for roughly 40% of what determines citation, with content quality at about 35% and platform trust at 25%. Sites with very high referring domain counts (350K+) average 8.4 citations per response, while sites with slightly lower trust scores (91-96 vs 97-100) drop from 8.4 to 6 citations.

**Freshness is a major differentiator.** Content updated within the last 30 days gets cited about 3.2x more often than older content. ChatGPT clearly favors recent information.

**The most important signal is content-answer fit** — a ZipTie analysis of 400,000 pages found that how well your content's style and structure matches ChatGPT's own response format accounts for about 55% of citation likelihood. This is far more important than domain authority (12%) or on-page structure (14%) alone. Write the way ChatGPT would answer the question, and you're more likely to be the source it cites.

**Where ChatGPT looks beyond your site:** Wikipedia accounts for 7.8% of all ChatGPT citations, Reddit for 1.8%, and Forbes for 1.1%. Brand official sites are cited frequently but third-party mentions carry significant weight.

**What to focus on:**
- Invest in backlinks and domain authority — it's the strongest baseline signal
- Update competitive content at least monthly
- Structure your content the way ChatGPT structures its answers (conversational, direct, well-organized)
- Include verifiable statistics with named sources
- Clean heading hierarchy (H1 > H2 > H3) with descriptive headings

---

## Perplexity

Perplexity always cites its sources with clickable links, making it the most transparent AI search platform. It combines its own index with Google's and runs results through multiple reranking passes — initial relevance retrieval, then traditional ranking factor scoring, then ML-based quality evaluation that can discard entire result sets if they don't meet quality thresholds.

**What makes Perplexity different:** It's the most "research-oriented" AI search engine, and its citation behavior reflects that. Perplexity maintains curated lists of authoritative domains (Amazon, GitHub, major academic sites) that get inherent ranking boosts. It uses a time-decay algorithm that evaluates new content quickly, giving fresh publishers a real shot at citation.

**Perplexity has unique content preferences:**
- **FAQ Schema (JSON-LD)** — Pages with FAQ structured data get cited noticeably more often
- **PDF documents** — Publicly accessible PDFs (whitepapers, research reports) are prioritized. If you have authoritative PDF content gated behind a form, consider making a version public.
- **Publishing velocity** — How frequently you publish matters more than keyword targeting
- **Self-contained paragraphs** — Perplexity prefers atomic, semantically complete paragraphs it can extract cleanly

**What to focus on:**
- Allow PerplexityBot in robots.txt
- Implement FAQPage schema on any page with Q&A content
- Host PDF resources publicly (whitepapers, guides, reports)
- Add Article schema with publication and modification timestamps
- Write in clear, self-contained paragraphs that work as standalone answers
- Build deep topical authority in your specific niche

---

## Microsoft Copilot

Copilot is embedded across Microsoft's ecosystem — Edge, Windows, Microsoft 365, and Bing Search. It relies entirely on Bing's index, so if Bing hasn't indexed your content, Copilot can't cite it.

**What makes Copilot different:** The Microsoft ecosystem connection creates unique optimization opportunities. Mentions and content on LinkedIn and GitHub provide ranking boosts that other platforms don't offer. Copilot also puts more weight on page speed — sub-2-second load times are a clear threshold.

**What to focus on:**
- Submit your site to Bing Webmaster Tools (many sites only submit to Google Search Console)
- Use IndexNow protocol for faster indexing of new and updated content
- Optimize page speed to under 2 seconds
- Write clear entity definitions — when your content defines a term or concept, make the definition explicit and extractable
- Build presence on LinkedIn (publish articles, maintain company page) and GitHub if relevant
- Ensure Bingbot has full crawl access

---

## Claude

Claude uses Brave Search as its search backend when web search is enabled — not Google, not Bing. This is a completely different index, which means your Brave Search visibility directly determines whether Claude can find and cite you.

**What makes Claude different:** Claude is extremely selective about what it cites. While it processes enormous amounts of content, its citation rate is very low — it's looking for the most factually accurate, well-sourced content on a given topic. Data-rich content with specific numbers and clear attribution performs significantly better than general-purpose content.

**What to focus on:**
- Verify your content appears in Brave Search results (search for your brand and key terms at search.brave.com)
- Allow ClaudeBot and anthropic-ai user agents in robots.txt
- Maximize factual density — specific numbers, named sources, dated statistics
- Use clear, extractable structure with descriptive headings
- Cite authoritative sources within your content
- Aim to be the most factually accurate source on your topic — Claude rewards precision

---

## Allowing AI Bots in robots.txt

If your robots.txt blocks an AI bot, that platform can't cite your content. Here are the user agents to allow:

```
User-agent: GPTBot           # OpenAI — powers ChatGPT search
User-agent: ChatGPT-User     # ChatGPT browsing mode
User-agent: PerplexityBot    # Perplexity AI search
User-agent: ClaudeBot        # Anthropic Claude
User-agent: anthropic-ai     # Anthropic Claude (alternate)
User-agent: Google-Extended   # Google Gemini and AI Overviews
User-agent: Bingbot          # Microsoft Copilot (via Bing)
Allow: /
```

**Training vs. search:** Some AI bots are used for both model training and search citation. If you want to be cited but don't want your content used for training, your options are limited — GPTBot handles both for OpenAI. However, you can safely block **CCBot** (Common Crawl) without affecting any AI search citations, since it's only used for training dataset collection.

---

## Where to Start

If you're optimizing for AI search for the first time, focus your effort where your audience actually is:

**Start with Google AI Overviews** — They reach the most users (45%+ of Google searches) and you likely already have Google SEO foundations in place. Add schema markup, include cited sources in your content, and strengthen E-E-A-T signals.

**Then address ChatGPT** — It's the most-used standalone AI search tool for tech and business audiences. Focus on freshness (update content monthly), domain authority, and matching your content structure to how ChatGPT formats its responses.

**Then expand to Perplexity** — Especially valuable if your audience includes researchers, early adopters, or tech professionals. Add FAQ schema, publish PDF resources, and write in clear, self-contained paragraphs.

**Copilot and Claude are lower priority** unless your audience skews enterprise/Microsoft (Copilot) or developer/analyst (Claude). But the fundamentals — structured content, cited sources, schema markup — help across all platforms.

**Actions that help everywhere:**
1. Allow all AI bots in robots.txt
2. Implement schema markup (FAQPage, Article, Organization at minimum)
3. Include statistics with named sources in your content
4. Update content regularly — monthly for competitive topics
5. Use clear heading structure (H1 > H2 > H3)
6. Keep page load time under 2 seconds
7. Add author bios with credentials


---

# references/youtube-ai-citations.md

# YouTube Videos That Get Cited by AI

YouTube is one of the most-cited third-party surfaces in AI answers — Google AI Overviews and Gemini cite it heavily, and ChatGPT/Perplexity lift from it for how-to queries. The core insight that changes how you produce for it:

**Models don't watch your video. They read everything around it.** The citation is earned by the text layer — title, transcript, captions, chapters, description, and comments — not the footage. A mediocre-looking video with a clean, structured text layer beats a beautiful one that's opaque to a crawler.

## The anatomy

Work through these in order of leverage:

### 1. The transcript (the real content)

This is what the model actually reads. Optimize the *spoken words*:

- **Answer questions in complete, liftable sentences.** "The five steps to create an SOP are…" extracts cleanly; a rambling answer spread across three tangents doesn't.
- Script or outline the key answers before recording so each core question gets a clear, structured spoken answer in one place.
- Say the important terms out loud — the product name, the category, the entities you want associated. If it's only on a slide, the model may never see it.

### 2. Accurate captions

Auto-captions are messy — misheard product names, no punctuation, broken sentences — and messy captions are what the model reads if you don't fix them. Upload cleaned captions (or at minimum correct the auto-generated ones). This is the cheapest fix on the list.

### 3. A question-shaped title

Models match the title against the user's prompt. "How to Create SOPs That Scale Your Business" beats a clever title every time. Front-load the question or task; save the branding for the channel.

### 4. Chapters and timestamps

Chapters let the model (and viewers) jump to the exact answer. Structure = extractability: each chapter title is another labeled, liftable claim about what the video covers. Match chapter titles to the sub-questions people actually ask.

### 5. A keyword-rich, structured description

Restate the video's key points *as text* in the description — a short summary, then a bulleted list of what's covered, then resource links. This reinforces the topic and entities in plain crawlable text and gives the model a second, cleaner copy of the answer.

### 6. A pinned comment with the summary

An extra liftable text block: pin a comment with the core answer in numbered steps plus the key links. It's indexed, it's structured, and it survives even when viewers never open the description.

### 7. Thumbnail and engagement

Engagement isn't read directly by LLMs, but it drives the watch signals that lift YouTube ranking — and YouTube ranking feeds what AI systems surface and cite. The thumbnail's job is the click; the text layer's job is the citation.

## Publishing checklist

- [ ] Title is question- or task-shaped and matches a real query
- [ ] Key answers spoken as complete, structured statements
- [ ] Captions uploaded or corrected (product names spelled right)
- [ ] Chapters added, titled by sub-question
- [ ] Description restates the key points in text with a bulleted breakdown
- [ ] Pinned comment carries the summary + links
- [ ] Important entities (brand, category, product) spoken *and* written

## Related

- The same "models read the text layer" logic applies to podcasts: episodes get transcribed and show notes get published, so podcast guesting is earned media that compounds in AI answers — see the `public-relations` skill's podcast guest prep reference.
- For producing the videos themselves, see the `video` skill.

---

*Anatomy pattern from Ross Simmonds / Foundation Inc. ("The Anatomy of a YouTube Video AI Cites," 2026), distilled and extended with credit.*
