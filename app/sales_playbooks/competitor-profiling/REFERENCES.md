# Reference files for the `competitor-profiling` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/templates.md

# Profile Templates

Ready-to-use templates for competitor profile sections and the summary document.

## Contents
- Quick Scan Template
- Summary Comparison Table
- Positioning Map
- Competitive SWOT
- Profile Update Changelog

---

## Quick Scan Template

Abbreviated profile for when speed matters more than depth.

```markdown
# [Competitor Name] — Quick Profile

**URL**: [website]
**Generated**: [date]

## At a Glance

| Metric | Value |
|--------|-------|
| Tagline | [from homepage] |
| Target audience | [inferred from copy] |
| Pricing starts at | [lowest paid tier] |
| Free tier/trial | [yes/no + details] |
| Domain rank | [from DataForSEO] |
| Est. organic traffic | [monthly] |
| Organic keywords (top 10) | [count] |
| Referring domains | [count] |

## Positioning

**Headline**: "[exact homepage headline]"
**Subheadline**: "[exact subheadline]"
**Positioning angle**: [1-2 sentence summary of how they position]

## Pricing Summary

| Tier | Price | Notable Inclusions |
|------|-------|-------------------|
| [tier] | [price] | [key items] |
| [tier] | [price] | [key items] |

## Key Takeaway

[2-3 sentences: what makes this competitor notable, where they're strong, where they're weak]
```

---

## Summary Comparison Table

Use after profiling all competitors to create a side-by-side view.

```markdown
# Competitive Landscape Summary

**Generated**: [date]
**Your product**: [name]
**Competitors profiled**: [count]

## Side-by-Side Comparison

| Dimension | [Your Product] | [Competitor 1] | [Competitor 2] | [Competitor 3] |
|-----------|---------------|----------------|----------------|----------------|
| **Tagline** | [yours] | [theirs] | [theirs] | [theirs] |
| **Target audience** | [yours] | [theirs] | [theirs] | [theirs] |
| **Positioning** | [angle] | [angle] | [angle] | [angle] |
| **Starting price** | $[X]/mo | $[X]/mo | $[X]/mo | $[X]/mo |
| **Free tier** | [yes/no] | [yes/no] | [yes/no] | [yes/no] |
| **Domain rank** | [score] | [score] | [score] | [score] |
| **Est. organic traffic** | [number] | [number] | [number] | [number] |
| **Referring domains** | [count] | [count] | [count] | [count] |
| **G2 rating** | [score] | [score] | [score] | [score] |
| **Key strength** | [one-liner] | [one-liner] | [one-liner] | [one-liner] |
| **Key weakness** | [one-liner] | [one-liner] | [one-liner] | [one-liner] |
```

---

## Positioning Map

Visual representation of where competitors sit along two key dimensions. Choose the two axes most relevant to your market.

### Common Axis Pairs

| Market Type | X-Axis | Y-Axis |
|-------------|--------|--------|
| SaaS tools | Simple → Complex | Cheap → Expensive |
| Developer tools | Low-code → Code-first | Individual → Team |
| B2B platforms | SMB-focused → Enterprise-focused | Point solution → Platform |
| Content tools | Template-driven → Custom | Self-serve → Managed |

### Format

```markdown
## Positioning Map

**Axes**: [X-axis label] vs. [Y-axis label]

                    [Y-axis high label]
                           │
                           │
          [Competitor A]   │    [Competitor B]
                           │
    ───────────────────────┼───────────────────────
    [X-axis low]           │           [X-axis high]
                           │
          [Your Product]   │    [Competitor C]
                           │
                    [Y-axis low label]

### Interpretation
- [1-2 sentences about what the map reveals]
- [where the whitespace / opportunity is]
```

---

## Competitive SWOT

Per-competitor SWOT relative to your product.

```markdown
## SWOT: [Competitor] vs. [Your Product]

### Strengths (theirs vs. ours)
- [Where they genuinely outperform us — be honest]

### Weaknesses (theirs vs. ours)
- [Where they fall short compared to us — with evidence]

### Opportunities (for us)
- [Gaps in their offering we can exploit]
- [Segments they're ignoring]
- [Messaging angles they're missing]

### Threats (from them)
- [Areas where they're improving fast]
- [Features they're building that overlap with us]
- [Market moves that could shift perception]
```

---

## Profile Update Changelog

Append to the bottom of any profile when updating it.

```markdown
---

## Change Log

| Date | What Changed | Source |
|------|-------------|--------|
| [date] | Pricing increased from $X to $Y | Pricing page re-scrape |
| [date] | Launched [feature] | Changelog scrape |
| [date] | Domain rank changed from X to Y | DataForSEO re-pull |
| [date] | Added [integration] | Integrations page re-scrape |
```


---

# references/tool-reference.md

# MCP Tool Reference for Competitor Profiling

Quick reference for the Firecrawl and DataForSEO MCP tools used in competitor profiling.

## Contents
- Firecrawl Tools (site scraping)
- DataForSEO Tools (SEO & market data)
- Recommended Execution Order
- Error Handling

---

## Firecrawl Tools

### firecrawl_map
**Purpose**: Discover all URLs on a competitor's site to identify key pages.
**When to use**: First step for every competitor — before scraping individual pages.
**Key output**: List of URLs with their page types/paths.
**Tip**: Look for paths containing `/pricing`, `/features`, `/about`, `/customers`, `/integrations`, `/blog`, `/changelog`.

### firecrawl_scrape
**Purpose**: Extract content from a single page as clean markdown.
**When to use**: After mapping, scrape each key page individually.
**Key output**: Page content in markdown format — headlines, body text, structured data.
**Tip**: Scrape homepage first — it reveals positioning, audience, and social proof in one shot.

### firecrawl_search
**Purpose**: Search the web for specific content about a competitor.
**When to use**: Finding review pages, press coverage, or competitor mentions not on their own site.
**Example queries**:
- `"[Competitor Name]" site:g2.com`
- `"[Competitor Name]" review`
- `"[Competitor Name]" funding OR raised`

### firecrawl_crawl
**Purpose**: Crawl multiple pages from a site in one operation.
**When to use**: Deep profiles where you want to analyze many pages (e.g., all feature pages, all blog posts). More expensive — use selectively.
**Tip**: Set page limits to avoid crawling entire sites. Target specific URL patterns.

### firecrawl_extract
**Purpose**: Extract structured data from a page using a schema.
**When to use**: When you need specific data points in a consistent format (e.g., pricing tier details, feature lists).
**Tip**: Define a clear schema for what you want extracted — more reliable than parsing raw markdown.

---

## DataForSEO MCP Tools

### Domain-Level Intelligence

#### backlinks_summary
**Purpose**: Get domain authority, total backlinks, referring domains, spam score.
**Input**: Target domain (e.g., `competitor.com`)
**Key metrics**: `domain_rank`, `total_backlinks`, `referring_domains`, `backlinks_spam_score`

#### backlinks_referring_domains
**Purpose**: List top referring domains — shows where their link equity comes from.
**Input**: Target domain + limit
**Key metrics**: Per-domain: `rank`, `backlinks`, `domain` name

#### dataforseo_labs_google_domain_rank_overview
**Purpose**: Organic search overview — traffic, keywords, traffic value.
**Input**: Target domain
**Key metrics**: `organic_count` (keywords), `organic_traffic` (estimated monthly), `organic_cost` (traffic value in $)

#### dataforseo_labs_google_ranked_keywords
**Purpose**: What keywords a domain ranks for, with positions.
**Input**: Target domain
**Key metrics**: Per-keyword: `keyword`, `position`, `search_volume`, `url` (ranking page)
**Tip**: Sort by traffic to find their highest-value keywords.

#### dataforseo_labs_google_keywords_for_site
**Purpose**: Keywords relevant to a domain — broader than ranked keywords, includes opportunities.
**Input**: Target domain
**Key metrics**: `keyword`, `search_volume`, `competition`, `cpc`

### Competitive Analysis

#### dataforseo_labs_google_competitors_domain
**Purpose**: Find a domain's closest organic competitors by keyword overlap.
**Input**: Target domain
**Key metrics**: `domain`, `avg_position`, `intersections` (shared keywords), `full_domain_rank`
**Tip**: May reveal competitors the user hasn't considered.

#### dataforseo_labs_google_domain_intersection
**Purpose**: Find keywords where two domains both rank — shows direct competition.
**Input**: Two target domains
**Key metrics**: `keyword`, position for each domain, `search_volume`
**Tip**: Use this to compare the user's domain vs. each competitor.

#### dataforseo_labs_google_relevant_pages
**Purpose**: Find a domain's most important pages by organic traffic.
**Input**: Target domain
**Key metrics**: `page`, `metrics` (traffic, keywords per page)
**Tip**: Reveals their content strategy — which pages drive the most value.

### Technology Detection

#### domain_analytics_technologies_domain_technologies
**Purpose**: Detect the technology stack a domain uses.
**Input**: Target domain
**Key metrics**: Technologies grouped by category (CMS, analytics, marketing, payments, etc.)

### Backlink Deep Dive

#### backlinks_backlinks
**Purpose**: List individual backlinks to a domain.
**Input**: Target domain + limit
**Key metrics**: `url_from`, `url_to`, `anchor`, `domain_from_rank`, `is_new`

#### backlinks_bulk_ranks
**Purpose**: Compare domain ranks across multiple domains at once.
**Input**: Array of target domains
**Key metrics**: `domain_rank` per domain
**Tip**: Use this for the summary comparison table.

---

## Recommended Execution Order

### Quick Scan (per competitor)

```
1. firecrawl_map → get site URLs
2. In parallel:
   a. firecrawl_scrape → homepage
   b. firecrawl_scrape → pricing page
   c. dataforseo_labs_google_domain_rank_overview → organic metrics
   d. backlinks_summary → domain authority
3. Synthesize into abbreviated profile
```

### Deep Profile (per competitor)

```
1. firecrawl_map → get site URLs
2. In parallel (batch 1 — scraping):
   a. firecrawl_scrape → homepage
   b. firecrawl_scrape → pricing page
   c. firecrawl_scrape → features page(s)
   d. firecrawl_scrape → about page
   e. firecrawl_scrape → customers/case studies page
   f. firecrawl_scrape → integrations page
3. In parallel (batch 2 — SEO data):
   a. dataforseo_labs_google_domain_rank_overview
   b. dataforseo_labs_google_ranked_keywords
   c. backlinks_summary
   d. backlinks_referring_domains
   e. dataforseo_labs_google_relevant_pages
   f. dataforseo_labs_google_competitors_domain
4. In parallel (batch 3 — optional extras):
   a. domain_analytics_technologies_domain_technologies
   b. firecrawl_search → G2/Capterra reviews
   c. dataforseo_labs_google_domain_intersection (vs. user's domain)
5. Synthesize into full profile
```

### Multi-Competitor (3+ competitors)

```
1. Map all competitor sites in parallel
2. Scrape all homepages in parallel, then pricing pages in parallel
3. Pull domain_rank_overview for all in parallel
4. Pull backlinks_bulk_ranks for all at once
5. Build profiles in sequence (synthesis requires focus)
6. Build summary comparison last
```

---

## Error Handling

| Issue | Action |
|-------|--------|
| Firecrawl scrape returns empty/blocked | Try with `firecrawl_browser_create` for JS-heavy sites |
| Pricing page not found in map | Search for `/pricing`, `/plans`, `/packages` — some sites use different paths |
| DataForSEO returns no data for domain | Domain may be too new or too small — note "insufficient data" in profile |
| Rate limits hit | Space out requests; prioritize highest-value data first |
| Review page scraping blocked | Use `firecrawl_search` to find cached or alternative review sources |
