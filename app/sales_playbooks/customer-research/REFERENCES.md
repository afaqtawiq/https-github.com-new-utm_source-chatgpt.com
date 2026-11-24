# Reference files for the `customer-research` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/interviews-and-surveys.md

# Customer Research — Interviews & Surveys (Primary Research)

Going to the source. Mode 2 mines what customers already said in public; this is Mode 3 — you *ask*. Customer research is your marketing cheat code, and the highest-signal version is talking to customers directly.

Three primary-research pillars, best used together:
1. **Video calls** — deep, unstructured, follow-the-thread (this file)
2. **Surveys** — broad, quantified, benchmarkable (this file)
3. **Online sleuthing** — Sales Safari and watering-hole mining (see `references/source-guides.md`)

---

## The First Rule of Customer Research

> The first rule of customer research: you do not talk about customer research.

Keep it casual. The moment a customer thinks they're in "a research study" they perform — they give you the polished, socially-acceptable answer instead of the real one. Frame calls as a chat, not an interview. Don't lead. Don't pitch. Don't defend the product. You're there to listen and learn how they actually think, talk, and decide.

**Prove yourself wrong, not right.** The point of research is not validation — it's disconfirmation. Go in trying to *break* your assumptions, not confirm them. If you only look for evidence you're right, you'll find it, and it'll be worthless.

- **Dropbox example**: the team assumed users would care most about sync *speed*. Research aimed at disproving the assumption revealed users cared more that files were *reliably there and safe* than about raw speed. Chasing the confirmation would have optimized the wrong thing.
- Ask questions that could return an answer you don't want to hear. If none of your questions can prove you wrong, rewrite them.

---

## Sales Safari (Amy Hoy)

Amy Hoy's **Sales Safari**: go where your audience already congregates and observe them in the wild, without interrupting. It's structured online sleuthing — read threads, reviews, comments, and forum posts to mine four things:

| Mine for | What you're capturing |
|----------|-----------------------|
| **Pains** | The problems, frustrations, and workarounds they describe unprompted |
| **Jargon** | The exact words, phrases, and shorthand they use — copy gold |
| **Recommendations** | What they tell each other to buy, try, or avoid |
| **Worldview** | Their beliefs, biases, and how they see themselves and the problem |

Safari is passive (you observe) where interviews are active (you ask). Run it first: it tells you what to ask about, and in whose words. For per-platform search operators and extraction tips, see `references/source-guides.md`.

---

## Customer Interviews (Video Calls)

### Recruit your best customers

Don't interview whoever answers first. Interview the customers you want *more of*. Segment your CRM and prioritize by:

- **High deal size** — the accounts worth the most
- **Short sales cycle** — they "got it" fast; their language converts fast
- **Low churn / high retention** — they got real, lasting value

Recruitment methods, in order of leverage:
1. **Segment the CRM** by the three signals above and pull a shortlist
2. **Ask sales and CS for referrals** — they know who loves the product and who articulates why
3. **Always close every call with**: *"Who else should we talk to?"* — the single most reliable way to compound your interview pipeline

### Incentives

- **$50 per call** (~30 min); **$5 per survey response**
- Aim for **10 calls, be happy with 5.** Signal saturates fast — by call 5-6 you'll hear the same themes repeat. Don't stall the project waiting for a perfect sample.
- Offer the incentive up front; it dramatically lifts response rate and shows you value their time. Gift cards work fine.

### Outreach email template

Keep it short, casual, specific, and low-commitment. Not a "research study."

```
Subject: Quick favor — 30 min, on us

Hi [First name],

I'm [name] from [company]. I'm trying to get better at helping customers
like you, and I'd love to steal 30 minutes to hear how [product area] is
actually working for you — what's good, what's annoying, what you wish
were different. No pitch, no agenda.

As a thank you I'll send you a $50 [Amazon/Visa] gift card.

Are you free [day] or [day] this week? Here's my calendar: [link]

Thanks either way,
[Name]
```

Notes:
- "No pitch, no agenda" and "what's annoying" signal you actually want the truth.
- One clear ask, two concrete time options, a booking link. Remove friction.
- Never say "customer research study."

---

## Keep Asking Why (5-Why Laddering)

The first answer is never the real answer. **Keep Asking Why** — ladder each response down 3-5 levels until you hit the root motivation, the business outcome, or the emotional driver. Surface answers are features; the bottom of the ladder is why they pay and why they stay.

**Worked example** — laddering a churn signal to NRR:

- **Q: Why did you downgrade your plan last quarter?**
  - "We weren't using the advanced reports."
- **Why weren't you using them?**
  - "Nobody on the team knew how to build one."
- **Why didn't anyone learn?**
  - "The person who set us up left, and onboarding never got re-run for the new hires."
- **Why did that matter enough to downgrade?**
  - "Without the reports, my boss couldn't see the ROI, so at renewal it looked like an easy cost to cut."
- **Why is that the real risk?**
  - "If leadership can't see value, we churn — and if we *had* seen it, we'd probably have added seats, not cut them."

The surface answer was "we don't use reports." The root is an **onboarding gap that quietly converts an expansion (NRR up) into a contraction or churn (NRR down)**. You can't fix "they don't use reports." You can fix re-onboarding new hires and surfacing ROI to the buyer — which is the difference between contraction and net revenue retention.

**Pain points vs. passion points.** Ladder for both. Pain points are what's broken and what they'll pay to escape. Passion points are what they love, brag about, and would be "very disappointed" to lose. Passion points drive retention and referrals; pains drive acquisition. Capture both in their words.

---

## Surveys

### The PMF Survey (Sean Ellis / Superhuman)

The single most useful survey question, from Sean Ellis and popularized by Superhuman's Rahul Vohra:

> **"How would you feel if you could no longer use [product]?"**
> - Very disappointed
> - Somewhat disappointed
> - Not disappointed
> - N/A — I no longer use it

**The 40% benchmark**: if **40% or more** of users answer **"very disappointed,"** you likely have product/market fit. Below 40%, keep iterating. **Superhuman reached 58%** by engineering their roadmap around this metric — segmenting on the "very disappointed" cohort, doubling down on what that cohort loved, and converting the "somewhat disappointed" fence-sitters.

Run it as a recurring pulse, not once. Follow the core question with:
- *"What type of person do you think would most benefit from [product]?"* (sharpens ICP)
- *"What is the main benefit you receive from [product]?"* (your positioning, in their words)
- *"How can we improve [product] for you?"* (roadmap fuel from fence-sitters)

Segment every answer by the "very disappointed" cohort vs. the rest — that cohort is your true market.

### Survey design guardrails

- Keep it short — every extra question drops completion.
- Prefer open-ended for language mining; multiple-choice answers are artifacts of the options you gave.
- Don't lead. A question that telegraphs the answer you want returns the answer you want, not the truth.
- $5/response incentive lifts completion; deliver it on submit.

---

## Case Anchors

- **Airbnb (host photography)**: research revealed listings failed because the *photos* were bad, not the pricing or copy. Airbnb sent photographers to shoot host homes — a fix nobody would have guessed without talking to the market. Research points at problems you can't see from inside.
- **Dropbox (confirmation bias)**: assumed sync speed mattered most; disconfirming research showed reliability/safety of files mattered more. Prove yourself wrong.
- **Superhuman (PMF survey)**: engineered the roadmap around the "very disappointed" metric, 40% → 58%.

---

## Where This Fits

- **Analyze what you gather** with the Mode 1 extraction framework in `SKILL.md` (jobs to be done, pains, triggers, outcomes, language, alternatives) and the confidence guardrails.
- **Mine public sources** (the passive Safari half) via `references/source-guides.md`.
- Interview + survey signal is **first-party and high-confidence** — weight it above scraped online sources when they conflict.


---

# references/source-guides.md

# Customer Research — Source Guides

Detailed, source-by-source playbooks for gathering customer intelligence from online watering holes.

---

## Reddit Research

### Finding the Right Subreddits

Start by identifying where your ICP spends time, not where your product is discussed.

**Discovery methods:**
- Search `site:reddit.com "[job title] tools"` or `site:reddit.com "[problem category] software"`
- Use [subreddit search tools](https://www.reddit.com/subreddits/search) with problem-space keywords
- Look at what subreddits show up in Google results when you search ICP problems
- Check what subreddits competitors' customers mention in reviews

**Common high-value subreddits by category:**
- B2B SaaS: r/sales, r/marketing, r/entrepreneur, r/startups, r/smallbusiness
- Dev tools: r/programming, r/devops, r/webdev, r/cscareerquestions
- Analytics/data: r/analytics, r/dataengineering, r/BusinessIntelligence
- Marketing: r/PPC, r/SEO, r/emailmarketing, r/content_marketing
- HR/recruiting: r/recruiting, r/humanresources, r/jobs
- Finance/ops: r/accounting, r/financialplanning, r/projectmanagement

### Search Operators

```
site:reddit.com/r/[subreddit] "[keyword]"
site:reddit.com "[problem]" "recommend" OR "suggestion" OR "alternative"
site:reddit.com "[competitor name]" "vs" OR "alternative" OR "switched"
```

### What to Look For

**High-signal post types:**
- "What tools do you use for X?" → reveals alternatives and vocab
- "Frustrated with [competitor], looking for alternatives" → reveals pain and switching triggers
- "How do you handle X?" → reveals workflow and workarounds
- "Is [your category] worth it?" → reveals objections and evaluation criteria
- Complaint threads about competitors → reveals gaps you might fill

**What to extract:**
- The exact problem described in the post
- Top-voted solutions (what do practitioners actually recommend?)
- Complaints about existing solutions in comments
- The language used — note specific words and phrases
- Upvote patterns — consensus vs. controversy

### Tools
- Reddit's native search (limited but fast)
- Google: `site:reddit.com [query]` (better results)
- Pullpush.io — search archived Reddit posts (good for older threads)

---

## G2 and Review Site Mining

### Your Own Product Reviews

Read in this order for maximum signal:

1. **3-star reviews** — these are the most honest. Customer liked it enough to stay but felt something was missing.
2. **1-star reviews** — understand the failure modes. Separate product issues from support/onboarding issues.
3. **5-star reviews** — extract the "what they love" language. These are your proof points.
4. **4-star reviews** — often contain "the only thing I wish…" buried in praise.

**What to extract:**
- What they say they use it *for* (the job to be done)
- What they say is hardest or most frustrating
- What they compare it to ("coming from [X]", "better than [Y]")
- Industry and role signals in reviewer profiles

### Competitor Reviews on G2

The 4-star competitor reviews are gold — customers who like the product but still have complaints.

**G2 structure to exploit:**
- "What do you like best?" → their strengths (your battlecard intel)
- "What do you dislike?" → their weaknesses (your opportunities)
- "What problems are you solving?" → the job to be done

**Capterra** has similar structure. **Trustpilot** skews B2C. **AppSumo** reviews are useful for SMB/prosumer SaaS.

### Review Mining Template

For each competitor's 4-star reviews, extract:

| Category | Notes |
|----------|-------|
| Job to be done | Why do they use the product? |
| Top praise | What do they love (and might be hard for you to match)? |
| Top complaint | What frustrates them? |
| Switching context | Did they mention switching from something else? |
| Unmet need | "I wish it could…" or "It would be better if…" |

---

## Indie Hackers and Product Hunt

### Indie Hackers

Strong signal for founder/builder/SMB ICP.

**Where to look:**
- "Ask IH" posts: questions about problems your product solves
- Milestone posts: when founders describe their stack, they reveal tool preferences and pain
- Comment threads on product launches in your category

**Search:** `site:indiehackers.com "[problem]"` or use IH's native search.

### Product Hunt

**Discussion tabs** on competing products are a research goldmine:
- Questions asked = pre-sales concerns = objections
- Comments = early adopter reactions = leading indicators of reception
- "Alternatives to X" collections reveal the competitive landscape as users see it

---

## Hacker News

Strong signal for technical/developer ICP. Skews toward builders and skeptics.

**High-value searches:**
- `site:news.ycombinator.com "[competitor or category]"`
- HN "Ask HN: best tools for X" threads
- "Show HN" posts for competitors — read the skeptical comments

**What's different about HN:**
- Users are more likely to critique underlying architecture and business model
- Strong opinions about pricing models (especially anything subscription-based)
- First principles objections you might not hear elsewhere

---

## LinkedIn Research

### Posts and Comments

Search for posts by practitioners describing their workflows:
- "[Role] at [company size]" + problem keyword
- "We used to [old way] but now we [new way]" stories
- Posts asking for tool recommendations get comments from active buyers

### Job Postings

A job posting is a company's admission of a pain point.

**What to look for:**
- What tools are listed as "nice to have" vs. "required"? (reveals stack and adjacent tools)
- What metrics and outcomes are mentioned in the role description?
- What does the role spend most of its time doing? (reveals the job to be done)

**Search:** `site:linkedin.com/jobs "[role title]" "[relevant tool or category]"`

---

## YouTube Comments

### Finding High-Signal Videos

- Tutorial videos for problems your product solves
- "Best tools for X in [year]" roundup videos
- Competitor product demos and walkthroughs

**What to look for in comments:**
- "Does this work for [specific use case]?" → edge cases and unmet needs
- "I tried this but…" → failure points
- "What about [competitor]?" → active evaluation
- Timestamps with questions → confusion points in the workflow

---

## Twitter / X Research

### Search Operators

```
"[competitor]" -filter:replies min_faves:10
"[problem keyword]" "anyone know" OR "recommend" OR "alternative"
"[category] is broken" OR "frustrated with [category]"
```

### What to Find

- Real-time complaints about competitors
- Practitioners discussing their stack
- Influencers/thought leaders your ICP follows (useful for distribution)

---

## Blog Post and Forum Research

### Comparison Content

Google: `"[competitor 1] vs [competitor 2]"` or `"best [category] software [year]"`

Read the comments on these posts — people who find comparison content are actively evaluating. Their comments are questions your sales process should answer.

### Niche Communities

- **Slack communities**: Many industries have public or semi-public Slack groups. Search "[industry] Slack community".
- **Discord servers**: Growing for developer and creator communities.
- **Facebook Groups**: Still strong for SMB, e-commerce, agency, and coach/consultant ICP.
- **Circle/Mighty Networks communities**: Check if there are paid communities in your ICP's space.

---

## B2C and Consumer App Research

B2C research requires different sources than B2B SaaS. Consumer buyers don't congregate on LinkedIn or G2 — they leave traces in app stores, social media, and communities built around the activity your product serves.

### App Store Reviews (iOS App Store / Google Play)

One of the richest unfiltered sources for mobile/consumer products.

**Read in this order:**
1. **1-2 star reviews** — failure modes, unmet expectations, frustration peaks
2. **3-star reviews** — honest tradeoffs and "it's good but…" feedback
3. **5-star reviews** — what they love in their own words (proof points and positioning)

**What to extract:**
- What job they hired the app to do ("I use this to…")
- The moment it stopped working for them
- What they compared it to or switched from
- Emotional language — "I love how…", "I'm so frustrated that…"

**Search tip:** Sort by "Most Recent" to get fresh signal, then "Most Critical" for pain themes.

### Amazon Reviews (for physical products or software with Amazon presence)

Same priority order as app stores: 3-star reviews first.

**G2 analog for consumer SaaS**: Trustpilot, Sitejabber, and product-specific review aggregators.

### Reddit Consumer Communities

B2C Reddit is highly vertical — go to the hobby/lifestyle subreddit, not the general ones.

**Examples by product type:**
- Fitness apps: r/running, r/loseit, r/fitness, r/MyFitnessPal
- Personal finance: r/personalfinance, r/financialindependence, r/ynab
- Productivity/notes: r/productivity, r/Notion, r/ObsidianMD
- Travel: r/travel, r/solotravel, r/digitalnomad
- Parenting: r/Parenting, r/beyondthebump, r/daddit

**Search pattern:** `site:reddit.com/r/[community] "[app name OR problem]"`

### TikTok and Instagram Comments

High-signal for consumer products with visual/lifestyle appeal.

**How to find signal:**
- Search TikTok for "[product name] review" or "is [product] worth it"
- Watch the top 5-10 videos; read ALL comments — not just likes
- On Instagram, check tagged posts from real users (not brand posts)

**What to extract:**
- Questions in comments = unmet needs or unclear positioning
- "Does this work for…?" = jobs they want to hire it for
- "I switched from X" comments = switching triggers
- Complaints about price, missing features, or broken promises

### YouTube Comments (Consumer)

Same approach as B2B but different video types:

- "X app honest review" or "X app after 6 months"
- "Best [category] apps [year]" comparison videos
- Unboxing or "setup" videos for hardware/physical products

Comments on review videos are especially valuable — these are people actively in the consideration phase.

### Consumer Community Platforms

- **Facebook Groups**: Still dominant for many consumer verticals (parenting, fitness, local services, hobbies)
- **Discord servers**: Growing for gaming, creator tools, productivity, crypto, lifestyle communities
- **Nextdoor**: Useful for local service businesses
- **Quora**: Long-form questions reveal decision anxiety and evaluation criteria

---

## SparkToro (Audience Intelligence)

SparkToro is a behavioral audience research tool. Instead of mining individual posts and comments, it aggregates clickstream, search, and social data to show what your audience does at scale — what they read, watch, listen to, follow, and search for.

### When to Use SparkToro vs. Manual Research

- **SparkToro first** when you need to understand where your ICP spends time, what content they consume, and which influencers they follow — it answers these questions in seconds with aggregated data
- **Manual research first** (Reddit, G2, communities) when you need raw language, exact quotes, emotional context, and the "why" behind behavior
- **Best together**: Use SparkToro to identify which podcasts, subreddits, and websites matter, then go mine those sources manually for voice-of-customer language

### Key Queries to Run

**By competitor:**
- "People who follow @competitor" — reveals shared audience affinities
- "People who visit competitor.com" — shows what else they consume

**By audience description:**
- "People who frequently talk about [topic]" — finds audience behaviors
- "People whose bio contains [job title]" — profiles a role-based segment

**By your own audience:**
- "People who visit yourdomain.com" — understand your actual audience
- Compare against competitor audience profiles to find gaps

### What to Extract

| Data Type | What It Tells You | Use It For |
|-----------|------------------|------------|
| Top websites visited | Where your audience reads | Content partnerships, guest posting targets |
| Top podcasts | What they listen to | Podcast guesting, sponsorship decisions |
| Top YouTube channels | What they watch | Video content strategy, ad placements |
| Top subreddits | Where they discuss | Community participation, Reddit ad targeting |
| Search keywords | What they Google | SEO and content topic planning |
| AI prompt topics | What they ask AI tools | Emerging content opportunities |
| Social accounts followed | Who influences them | Influencer partnerships, co-marketing |
| Demographics | Who they are | Persona building, ad targeting |

### Source Weighting

SparkToro data is aggregated and anonymized — it shows patterns, not individual opinions. Treat it as:
- **High confidence** for behavioral data (what they visit, follow, search for)
- **Medium confidence** for demographic data (self-reported, may be incomplete)
- **Not a substitute** for qualitative research (doesn't capture language, emotions, or the "why")

### Limitations

- Free tier: 5 reports/month, shallow results (top 5–10)
- No public API — all research done through web interface
- Skews English-language, US-centric
- Shows what audiences do, not why — pair with qualitative sources

See [tools/integrations/sparktoro.md](../../../tools/integrations/sparktoro.md) for full tool details and pricing.

---

## Organizing Your Research

Use a simple tagging system across all sources:

| Tag | Meaning |
|-----|---------|
| `#pain` | A problem or frustration |
| `#trigger` | An event that prompted the search |
| `#outcome` | What success looks like |
| `#language` | Exact phrases worth using in copy |
| `#alternative` | Another solution they considered or use |
| `#objection` | Reason to hesitate or not buy |
| `#competitor` | Anything about a competing product |

Keep a running doc with columns: Source | Date | Quote | Tags | Notes

After 20-30 entries, patterns will emerge. Look for quotes that appear in multiple unrelated sources — those are your highest-confidence insights.

---

## Source Reliability and Confidence Scoring

Not all sources carry equal weight. Use this guide when assigning confidence labels.

### Source Weighting

| Source | Signal Strength | Bias to Note |
|--------|----------------|--------------|
| Customer interviews (unprompted) | Very high | Small sample; selection bias toward engaged customers |
| Win/loss interviews | High | Recent memory only; rationalization common |
| App store / G2 reviews | High | Skews toward strong opinions (love or hate) |
| Reddit / community posts | Medium-high | Skews technical, skeptical, vocal minorities |
| Support tickets | Medium | Skews toward problems; silent majority not represented |
| Survey (open-ended) | Medium | Primed by question framing |
| Survey (multiple choice) | Low-medium | Artifacts of the options you provided |
| NPS verbatims | Medium | Correlates with score; prompted by the survey moment |
| YouTube/TikTok comments | Medium | Skews toward engaged viewers; social performance |
| SparkToro audience data | Medium-high | Aggregated behavioral data; strong for "what" but not "why" |
| Job postings | Low-medium | Aspirational, not necessarily reflective of current pain |

### Confidence Labels in Practice

When presenting insights, lead with confidence:

```
[HIGH CONFIDENCE] Customers feel overwhelmed by manual reporting — appears in 12 of 20 interviews,
4 Reddit threads, and is the #1 complaint in 3-star G2 reviews. Consistent across SMB and mid-market.

[MEDIUM CONFIDENCE] Customers compare us to spreadsheets more than to direct competitors —
mentioned in 6 interviews and 3 Reddit threads, but not yet seen in review data.

[LOW CONFIDENCE] Enterprise buyers may have procurement concerns — mentioned by 2 interviewees
from companies 500+. Needs more signal before acting on it.
```

### Recency Window

- **Use as primary source**: Data from the last 12 months
- **Use with caution**: 12-24 months (product and market may have shifted)
- **Use only for baseline context**: 2+ years old

When a theme appears consistently across old and new data, that's a durable signal worth acting on.
