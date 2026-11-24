# Reference files for the `content-strategy` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/content-distribution.md

# Content Distribution Spine

The "distribute" half of content strategy. Creating a great piece is table stakes; the leverage is in getting it seen. This reference expands the **Create Once, Distribute Twice** section of the skill.

Cross-links: ORB channel-type playbook lives in **launch**; atomization/repurposing workflows (podcast → clips, blog → thread) live in **social**. This file consolidates the strategy that ties them together—don't re-derive ORB from scratch here.

## Create Once, Distribute Twice

One exceptional piece, reformatted across channels—not a fresh piece per platform. The math is simple: a flagship piece plus ten repurposed cuts reaches far more people than eleven mediocre native posts, at a fraction of the effort.

The discipline is **designing the piece to be distributed**:
- Write subheads that read as standalone social posts.
- Structure sections modularly so they can be lifted out and stand alone.
- Pre-identify the pull quotes, stats, and frames you'll turn into graphics or short clips.
- Know the atomized outputs before you write, so the source piece contains them.

Treat the flagship as the master; every channel gets a cut derived from it.

## The ORB Framework as a Funnel

Own, Rent, Borrow—read as a discovery → engagement → conversion funnel:

| Layer | Channels | Funnel role | You control |
|---|---|---|---|
| **Borrowed** | Podcasts, guest posts, partnerships, PR, other people's audiences | Discovery / breakthrough | Nothing—it's a loan |
| **Rented** | Social platforms, ad networks, marketplaces | Engagement / reach | The content, not the audience or algorithm |
| **Owned** | Email list, blog, community, app | Conversion / retention | Everything—the durable asset |

The strategic move: use borrowed and rented reach to funnel strangers into owned channels where you can convert and retain them. Borrowed and rented are rented land; owned is the only asset you keep.

## The Ownership Paradox

Most teams invert the priority: they spend ~90% of effort on borrowed and rented channels they don't control, and neglect the owned assets that actually convert. The paradox is that the channels getting the least attention (email, blog, community) are the ones that compound and can't be revoked. Rebalance toward owned as the destination for all upstream effort.

## Failure Modes

- **Spray-and-pray** — publishing across every platform with no flagship and no repurposing system. Effort scatters; nothing compounds; each post starts from zero.
- **Platform dependency** — building your audience on rented land. Facebook organic reach collapsed from ~20% to under 2% as the platform monetized. Any rented channel can throttle, deprioritize, or de-platform you with no recourse. The lesson isn't "avoid rented"—it's "never let rented be the endpoint."

## Platform Half-Lives

Content decays at wildly different rates by channel. Match the piece to the channel's shelf life:

| Channel | Rough half-life | Implication |
|---|---|---|
| Twitter/X post | Minutes–hours | Post often; repost; thread for reach |
| Instagram / Facebook | ~a day | Frequent cadence; stories are ephemeral by design |
| LinkedIn post | ~a day, longer for strong performers | Fewer, higher-effort posts |
| TikTok / Reels / Shorts | Days–weeks (algorithmic resurfacing) | Evergreen hooks can re-surface long after posting |
| YouTube video | Months–years | Search-driven; compounds like a blog post |
| Blog post / SEO | Years | The long tail; the compounding asset |
| Email | Sent once, but archived / repurposable | One-shot attention; harvest into other formats |

Short half-life channels reward frequency and repetition; long half-life channels reward depth and evergreen framing. Owned, long-half-life formats (blog, YouTube, email archive) are where distribution effort compounds.

## The Content Distribution Flywheel

Distribution isn't a linear checklist—it's a loop that feeds itself:

1. **Create** one exceptional flagship piece (guide, video, podcast, original research), with distribution hooks built in.
2. **Atomize** it into channel-native cuts—clips, threads, carousels, quote graphics, email, subhead-posts.
3. **Distribute** across owned → rented → borrowed, routing everything back to owned.
4. **Engage** with the responses; capture the questions, objections, and reactions.
5. **Feed back** — the engagement surfaces the next flagship topic (what resonated, what got asked), and top-performing atoms signal what to make more of.

Each turn of the loop lowers the cost of the next piece (you learn what lands) and grows the owned audience that amplifies it. The flywheel is why consistent distributors pull away from one-off publishers over time.

## Atomization Checklist (per flagship)

For each major piece, produce (see **social** for the platform-native execution):
- [ ] 3–5 standalone social posts from the subheads/key points
- [ ] 1 thread (Twitter/X) or carousel (LinkedIn/Instagram) of the core argument
- [ ] 2–4 short-form video clips (if source is video/podcast)
- [ ] 1–2 quote or stat graphics
- [ ] 1 email to the owned list linking the flagship
- [ ] Repost/reshare schedule across the piece's half-life (don't post once and move on)

## Related

- **launch** — ORB channel-type playbook and launch-day distribution
- **social** — atomization/repurposing workflows and platform-native execution
- **emails** — the owned channel that converts distributed attention
- **ai-seo** — making owned content citable by LLMs (another distribution surface)


---

# references/headless-cms.md

# Headless CMS Guide

Reference for choosing, modeling, and implementing a headless CMS for marketing content.

## When to Use This Reference

Use this when selecting a CMS for a new project, designing content models for marketing sites, setting up editorial workflows, or connecting CMS content to programmatic pages.

---

## Headless vs Traditional CMS

A headless CMS separates content management from presentation. Content is stored in a structured backend and delivered via API to any frontend.

### When Headless Makes Sense

- Multiple frontends consume the same content (web, mobile, email)
- Developers want full control over the frontend stack
- Content needs to be reused across channels
- You're building with a modern framework (Next.js, Remix, Astro)
- Marketing needs structured, reusable content blocks

### When Traditional Works Better

- Small team with no dedicated developers
- Simple blog or brochure site
- WYSIWYG editing is a hard requirement
- Budget is tight and WordPress/Webflow does the job

### Decision Checklist

| Factor | Headless | Traditional |
|--------|----------|-------------|
| Multi-channel delivery | Yes | Limited |
| Developer control | Full | Constrained |
| Non-technical editing | Requires setup | Built-in |
| Time to launch | Longer | Faster |
| Content reuse | Native | Manual |
| Hosting flexibility | Any frontend | Platform-dependent |

---

## Content Modeling for Marketing

### Core Principles

1. **Think in types, not pages.** A "Landing Page" is a content type with fields — not an HTML file. This lets you reuse components across pages.
2. **Separate content from presentation.** Store the headline text, not the styled headline. Presentation belongs in the frontend.
3. **Design for reuse.** If testimonials appear on 5 pages, create a Testimonial type and reference it — don't duplicate.
4. **Keep models flat.** Deeply nested structures are hard to query and maintain. Prefer references over nesting.

### Common Marketing Content Types

| Type | Key Fields | Notes |
|------|-----------|-------|
| **Landing Page** | title, slug, hero, sections[], seo | Modular sections for flexibility |
| **Blog Post** | title, slug, body, author, category, tags, publishedAt, seo | Rich text or Portable Text body |
| **Case Study** | title, customer, challenge, solution, results, metrics[], logo | Link to related products/features |
| **Testimonial** | quote, author, role, company, avatar, rating | Reference from landing pages |
| **FAQ** | question, answer, category | Group by category for programmatic pages |
| **Author** | name, bio, avatar, social links | Reference from blog posts |
| **CTA Block** | heading, body, buttonText, buttonUrl, variant | Reusable across pages |

### SEO Fields Checklist

Every page-level content type needs:

- `metaTitle` — 50-60 characters
- `metaDescription` — 150-160 characters
- `ogImage` — 1200x630px social preview
- `slug` — URL path segment
- `canonicalUrl` — optional override
- `noIndex` — boolean for excluding from search
- `structuredData` — optional JSON-LD override

---

## Editorial Workflows

### Draft → Review → Publish Cycle

1. **Draft** — Author creates or edits content
2. **Review** — Editor reviews for accuracy, brand voice, SEO
3. **Approve** — Stakeholder signs off
4. **Schedule** — Set publish date/time
5. **Publish** — Content goes live via API

### Preview APIs

All major headless CMS platforms support draft previews:

- **Sanity**: Real-time preview with `useLiveQuery` or Presentation tool
- **Contentful**: Preview API (`preview.contentful.com`) with separate access token
- **Strapi**: Draft & Publish system with `status=draft` query parameter (v5; replaces v4's `publicationState`)

Set up a preview route in your frontend (e.g., `/api/preview`) that authenticates and renders draft content.

### Roles and Permissions

| Role | Can Create | Can Edit | Can Publish | Can Delete |
|------|:----------:|:--------:|:-----------:|:----------:|
| Author | Yes | Own | No | Own drafts |
| Editor | Yes | All | Yes | Drafts |
| Admin | Yes | All | Yes | All |

Exact permission models vary by platform. Sanity uses role-based access. Contentful has space-level roles. Strapi has granular RBAC.

---

## Platform Comparison

| Feature | Sanity | Contentful | Strapi |
|---------|--------|------------|--------|
| Hosting | Cloud (managed) | Cloud (managed) | Self-hosted or Cloud |
| Query Language | GROQ | REST / GraphQL | REST / GraphQL |
| Free Tier | Generous | Limited | Open source (free) |
| Real-time Collab | Yes (built-in) | Limited | No |
| Best For | Developer flexibility | Enterprise multi-locale | Budget / self-hosted |
| Content Modeling | Schema-as-code | Web UI | Web UI or code |
| Media Handling | Built-in DAM | Built-in | Plugin-based |

### Sanity

**Strengths**: GROQ query language is powerful and flexible. Schema defined in code (version-controlled). Real-time collaborative editing. Portable Text for rich content. Generous free tier.

**Considerations**: Steeper learning curve for non-developers. Studio customization requires React knowledge. Vendor lock-in on GROQ queries.

**Marketing fit**: Best when developers and marketers collaborate closely. Strong for content-heavy sites with complex models.

### Contentful

**Strengths**: Mature enterprise platform. Excellent multi-locale support. Strong ecosystem of integrations. Composable content with Studio. Well-documented APIs.

**Considerations**: Pricing scales with content types and locales. Two separate APIs (Delivery and Management). Rate limits can be tight on lower plans.

**Marketing fit**: Best for enterprises with multi-market content needs. Good when you need established vendor reliability.

### Strapi

**Strengths**: Open source, self-hosted option. Full control over data. No per-seat pricing. Customizable admin panel. Plugin ecosystem. REST by default, GraphQL via plugin.

**Considerations**: Self-hosting means you handle infrastructure. Smaller ecosystem than Sanity/Contentful. V5 migration can be significant from V4.

**Marketing fit**: Best for teams with DevOps capability who want full control and no vendor lock-in. Good for budget-conscious projects.

### Others Worth Knowing

- **Hygraph** — GraphQL-native, strong for federation and multi-source content
- **Keystatic** — Git-based, good for developer-content hybrid workflows
- **Payload** — TypeScript-first, self-hosted, code-configured like Sanity
- **Builder.io** — Visual editor with headless backend, good for non-technical marketers
- **Prismic** — Slice-based content modeling, strong Next.js integration

---

## Integration with Marketing Skills

### Programmatic SEO

Use CMS as the data source for programmatic pages. Store structured data (FAQs, comparisons, city pages) as content types and generate pages from queries. See **programmatic-seo** skill.

### Copywriting

CMS content models enforce consistent structure. Define fields that match your copy frameworks (headline, subheadline, social proof, CTA). See **copywriting** skill.

### Site Architecture

URL structure, navigation hierarchy, and internal linking all depend on how content is organized in the CMS. Plan your content model and site architecture together. See **site-architecture** skill.

### Email Sequences

Pull CMS content into email templates for consistent messaging across web and email. Case studies, testimonials, and blog posts can feed email nurture sequences. See **emails** skill.

---

## Implementation Checklist

- [ ] Define content types based on page types and reusable blocks
- [ ] Add SEO fields to every page-level content type
- [ ] Set up preview/draft mode in your frontend
- [ ] Configure roles and permissions for your team
- [ ] Create sample content for each type before building frontend
- [ ] Set up webhook notifications for content changes (rebuild triggers)
- [ ] Document content guidelines for editors (field descriptions, character limits)
- [ ] Test content delivery performance (CDN, caching, ISR)
- [ ] Plan migration strategy if moving from existing CMS

---

## Relevant Integration Guides

- [Sanity](../../../tools/integrations/sanity.md) — GROQ queries, mutations, CLI
- [Contentful](../../../tools/integrations/contentful.md) — Delivery/Management APIs, publishing
- [Strapi](../../../tools/integrations/strapi.md) — REST CRUD, filters, document API
