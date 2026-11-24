# Reference files for the `marketing-loops` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/loop-catalog.md

# Marketing Loop Catalog

A library of repeatable marketing loops with thorough coverage across the funnel. Each is a complete, adaptable spec. Pick the closest match, then tune the cadence, thresholds, state handling, and human checkpoints to the user's product, stage, and tooling.

Every loop lists nine parts: **Check cadence · Acts when · Purpose · Skills used · Loop body · Self-check · State / idempotency · Stop / bail-out · Output**. See `SKILL.md` for the anatomy, the cadence rule, and when not to loop.

Two rules that apply to every entry:
- **Most runs should do nothing.** A healthy loop checks, finds nothing worth acting on, logs "no action," and exits. Loops that act every run are usually acting on noise.
- **State prevents harm.** Every loop tracks what it already did (last-run marker, dedupe key, cooldown) so it never double-acts, re-nags the same person, or re-alerts the same issue.

Loops are grouped by function. Naming follows the "The X loop" convention.

---

## SEO & Content

### The keyword-gap loop
- **Check cadence**: Weekly
- **Acts when**: A striking-distance keyword (positions 5–20) or a rising query has no adequate page.
- **Purpose**: Surface new ranking opportunities before competitors take them.
- **Skills used**: `seo-audit`, `programmatic-seo`, `content-strategy`
- **Loop body**:
  1. Pull ranking + impression data (Search Console / rank tracker).
  2. Diff vs. last run: new striking-distance keywords, rising queries with no matching page.
  3. Classify each gap: quick on-page win / net-new page / programmatic template candidate.
  4. Draft briefs for the top 3.
- **Self-check**: Movement real vs. seasonal? Compare to the same period last month, not just last week.
- **State / idempotency**: Store the set of gaps already briefed; don't re-brief an open one.
- **Stop / bail-out**: No gap clears a minimum impression threshold → log "no action." Halt on data-source outage rather than acting on partial data.
- **Output**: Up to 3 content briefs staged for review + a one-line movement summary.

### The ranking-drop watch loop
- **Check cadence**: Weekly
- **Acts when**: A priority keyword or page drops more than N positions vs. baseline.
- **Purpose**: Catch and diagnose SEO regressions before they compound.
- **Skills used**: `seo-audit`, `analytics`
- **Loop body**:
  1. Track positions for priority keywords/pages.
  2. Flag material drops; diff what changed (content, links, SERP layout, algo-update timing).
  3. Diagnose likely cause + propose a fix.
- **Self-check**: Rule out a SERP-feature change or one-off volatility before declaring a real loss.
- **State / idempotency**: Remember which drops are already open as issues; update rather than re-file.
- **Stop / bail-out**: No material drop → log "stable." Escalate suspected algo hits to a human rather than mass-editing.
- **Output**: A regression report with a recommended fix.

### The content-decay loop
- **Check cadence**: Monthly
- **Acts when**: A page's traffic/rankings declined materially over the trailing 90 days.
- **Purpose**: Refresh decaying content before it slides out of rankings.
- **Skills used**: `copy-editing`, `seo-audit`, `content-strategy`
- **Loop body**:
  1. Find pages with declining trailing-90-day traffic/rankings.
  2. Pick the highest-value decayers.
  3. Draft a refresh plan (update stats, expand thin sections, fix intent match, re-link).
- **Self-check**: Decay from the page itself, or from a SERP/seasonality shift? Refresh only what a refresh can fix.
- **State / idempotency**: Track last-refresh date per page; don't re-queue a page refreshed within the cooldown.
- **Stop / bail-out**: No meaningful decayers → skip.
- **Output**: A prioritized refresh list with per-page plans.

### The internal-linking loop
- **Check cadence**: On new/updated content, or weekly
- **Acts when**: A published page has fewer relevant internal links (in or out) than it should.
- **Purpose**: Distribute link equity and help new content get discovered and rank.
- **Skills used**: `seo-audit`, `site-architecture`, `content-strategy`
- **Loop body**:
  1. Identify recently published/updated pages.
  2. Find relevant existing pages that should link to them (and vice versa).
  3. Draft the specific link insertions with anchor text.
- **Self-check**: Is each link contextually relevant, or link-stuffing? Skip forced links.
- **State / idempotency**: Track which page pairs are already linked; never suggest a duplicate.
- **Stop / bail-out**: No relevant link targets → skip. Stage edits for review; don't mass-edit live pages autonomously.
- **Output**: A list of specific internal-link edits.

### The programmatic-SEO quality loop
- **Check cadence**: Monthly
- **Acts when**: Template pages show indexation gaps, thin content, duplication, or cannibalization.
- **Purpose**: Keep large templated page sets healthy so they don't drag the whole domain.
- **Skills used**: `programmatic-seo`, `seo-audit`
- **Loop body**:
  1. Sample the template page set; check indexation, word/data uniqueness, and query overlap.
  2. Flag thin, duplicate, cannibalizing, or deindexed pages.
  3. Recommend fix, consolidate, noindex, or prune.
- **Self-check**: Is low traffic a quality problem or just low demand? Don't prune pages that serve real long-tail intent.
- **State / idempotency**: Track pages already flagged/actioned; re-check only on the next cycle.
- **Stop / bail-out**: Set healthy → log and skip. Escalate mass-noindex/prune decisions to a human.
- **Output**: A quality report with per-bucket actions.

### The content-repurposing loop
- **Check cadence**: Weekly
- **Acts when**: A long-form asset (post/video/podcast) hasn't been repurposed yet.
- **Purpose**: Turn every long-form asset into a week of channel-native content.
- **Skills used**: `social`, `content-strategy`, `copywriting`
- **Loop body**:
  1. Find the newest un-repurposed asset.
  2. Extract the 3–5 strongest ideas.
  3. Draft channel-native versions (LinkedIn post, X thread, short-form script).
  4. Stage in the scheduling queue.
- **Self-check**: Does each piece stand alone, or read like a link-dump? Rewrite anything that only works with the original open.
- **State / idempotency**: Mark assets as repurposed; never re-process one.
- **Stop / bail-out**: Nothing new published → skip.
- **Output**: Drafts in the social queue for approval.

### The content-calendar refill loop
- **Check cadence**: Weekly
- **Acts when**: The editorial pipeline has fewer than N weeks of planned content queued.
- **Purpose**: Keep the content pipeline from running dry.
- **Skills used**: `content-strategy`, `marketing-ideas`, `seo-audit`
- **Loop body**:
  1. Count planned/drafted pieces remaining in the calendar.
  2. If below the buffer, generate new topic ideas from the keyword-gap output, customer questions, and pillar plan.
  3. Prioritize and slot them.
- **Self-check**: Do new topics map to real search demand or audience questions, not just "content for content's sake"?
- **State / idempotency**: Dedupe proposed topics against the existing calendar and published archive.
- **Stop / bail-out**: Pipeline above buffer → skip.
- **Output**: New prioritized topics added to the calendar.

---

## Paid

### The ad-fatigue loop
- **Check cadence**: Every 2–3 days
- **Acts when**: An ad shows rising frequency + declining CTR/CVR past a real significance bar.
- **Purpose**: Refresh creative before CPA drifts up as ads fatigue.
- **Skills used**: `ads`, `ad-creative`, `analytics`
- **Loop body**:
  1. Pull per-ad metrics: CTR, frequency, CPA, spend, trend vs. baseline.
  2. Flag fatiguing ads and clear winners.
  3. Generate 3–5 fresh variants off the winning angle.
  4. Stage variants; recommend budget shift fatigued → winning.
- **Self-check**: Enough spend, impressions, and conversions to read CPA past the attribution window, and the ad is out of the learning phase. Rising frequency alone with thin conversion data is not fatigue evidence — wait.
- **State / idempotency**: Track per-ad last-refresh date; don't regenerate variants for an ad refreshed within the cooldown.
- **Stop / bail-out**: Never auto-shift budget or publish without a human checkpoint unless spend caps + an allowlist are explicitly authorized. Halt if daily spend exceeds its cap.
- **Output**: Staged creative drafts + a recommended budget move.

### The daily-creative-drop loop
- **Check cadence**: Daily (early morning, so the batch is ready when the media buyer sits down)
- **Acts when**: The grounded inputs corpus exists and the required inputs are populated — `inputs/winning-ads/` and `inputs/reviews/` (required; `inputs/comments/` and `brand/` strongly recommended, matching ad-creative's grounding rules). If a required input is empty, the loop asks for inputs instead of generating.
- **Purpose**: Keep creative volume ahead of fatigue — a standing batch of fresh static concepts to test, so scaling never stalls waiting on production.
- **Skills used**: `ad-creative` (Mode 3 + static ad template library), `customer-research`
- **Loop body**:
  1. Read the inputs corpus: `inputs/winning-ads/`, `inputs/reviews/`, `inputs/comments/`, and `brand/`.
  2. Generate the batch (e.g., 50 concepts) cycling all 15 static templates, 3-4 variations each, every concept grounded in a cited source.
  3. Generate images if an image tool is configured; otherwise deliver concepts + image prompts.
  4. Save to `outputs/YYYY-MM-DD/` with an `INDEX.md` (template type + grounding per concept).
- **Self-check**: Are concepts actually grounded (spot-check citations against sources)? Is template coverage spread across the library, not clustered on 2-3? Does copy match the brand voice doc rather than generic DR voice?
- **State / idempotency**: One batch per day — skip if today's output folder already exists. Track angle/headline hashes across recent batches to avoid regenerating near-duplicates of concepts already delivered.
- **Stop / bail-out**: Missing or empty required inputs → stop and request them; never generate ungrounded. Human picks the 5-10 to upload — this loop stages creative and **never publishes to the ad account**. If batches go unreviewed for a week, pause and ask whether to continue (unpicked batches are a vanity loop).
- **Output**: A dated folder of grounded static ad concepts + index, ready for human selection.
- **Input freshness (companion cadence)**: Weekly, refresh `inputs/winning-ads/` with anything that scaled and prune stale examples; monthly, refresh `inputs/reviews/` and `inputs/comments/` and re-check the voice doc. Stale inputs are this loop's failure mode — output quality tracks input freshness, not run count.

### The monthly-creative-retro loop
- **Check cadence**: Monthly (first business day, reading the prior month)
- **Acts when**: The account had meaningful creative activity last month — new concepts launched with enough delivery to judge (respect the impression/spend thresholds in `ads`). If nothing launched or nothing cleared thresholds, note that and skip.
- **Purpose**: Close the creative strategy loop — turn last month's results into next month's evidence-ranked slate, so the roadmap learns instead of drifting.
- **Skills used**: `ad-creative` (Mode 4 + creative-roadmap reference), `ads` (decision thresholds), `analytics`
- **Loop body**:
  1. Pull last month's ad performance via the platform CLIs; map results to the month's roadmap concepts.
  2. Draft the retro artifact (`retros/YYYY-MM.md`): winners with the why, losers with funnel-stage diagnosis, single-metric wins, learnings, kills.
  3. Update the roadmap: re-rank icebox evidence, write learnings in as new/revised concepts, draft next month's capacity-checked slate.
  4. Flag the account-state call (exploration vs. scaling) for human confirmation — the mix recommendation depends on it.
- **Self-check**: Are verdicts on concepts (not single executions)? Did every learning land somewhere — icebox update, re-rank, or kill? Did anything clear thresholds, or is this month a skip?
- **State / idempotency**: One retro per month — skip if `retros/YYYY-MM.md` exists. The roadmap file is the shared state; never fork it.
- **Stop / bail-out**: Stages analysis and a draft slate only — the human approves the slate and the account-state call; the loop **never launches or pauses ads**. If retros go unread for two cycles, pause and ask.
- **Output**: The monthly retro artifact + an updated roadmap with a draft slate for the coming month.

### The paid-search query-mining loop
- **Check cadence**: Weekly
- **Acts when**: Search-term reports reveal wasted spend or new intent.
- **Purpose**: Continuously refine keywords, negatives, and landing-page mapping.
- **Skills used**: `ads`, `analytics`
- **Loop body**:
  1. Pull the search-terms report.
  2. Identify irrelevant terms (→ negatives), high-performing terms (→ new exact-match), and terms whose landing page is a poor match.
  3. Stage keyword/negative changes and landing-page notes.
- **Self-check**: Enough clicks/conversions per term to justify a change? Don't negate on a single click.
- **State / idempotency**: Track already-added negatives/keywords; never re-add.
- **Stop / bail-out**: No terms clear thresholds → skip. Stage changes for review before pushing to the account.
- **Output**: A staged list of negatives, new keywords, and LP mismatches.

### The retargeting-hygiene loop
- **Check cadence**: Weekly
- **Acts when**: Audiences are stale, too small, over-frequent, or missing exclusions.
- **Purpose**: Keep retargeting efficient and non-annoying.
- **Skills used**: `ads`, `analytics`
- **Loop body**:
  1. Review retargeting audiences: size, recency, frequency, exclusions, creative sequencing.
  2. Flag issues (converters not excluded, audiences too small to serve, frequency too high).
  3. Recommend fixes.
- **Self-check**: Is the audience actually underperforming, or just small-but-valuable? Don't kill high-intent segments for size.
- **State / idempotency**: Track which audiences were already fixed this cycle.
- **Stop / bail-out**: All healthy → skip. Human-approve audience deletions.
- **Output**: A hygiene report with recommended audience changes.

### The landing-page regression loop
- **Check cadence**: Weekly (or on deploy)
- **Acts when**: A top acquisition page regresses on conversion, speed, tracking, or form function.
- **Purpose**: Catch silent breakage on the pages that receive paid/organic traffic.
- **Skills used**: `cro`, `analytics`
- **Loop body**:
  1. Monitor top acquisition pages: conversion rate, load speed, form submits, tracking fires.
  2. Flag regressions vs. baseline; correlate with recent deploys/changes.
  3. Diagnose and propose a fix.
- **Self-check**: Rule out tracking breakage vs. a real conversion drop before raising an alarm — and vice versa.
- **State / idempotency**: Track open regressions; update rather than re-file.
- **Stop / bail-out**: No regression → log "stable." Escalate a live-revenue-page break immediately, don't wait for the next run.
- **Output**: A regression alert with cause + fix.

---

## Earned, Social & Partnerships

### The newsjacking loop
- **Check cadence**: Daily
- **Acts when**: A trending story matches the brand's space, clears newsworthiness + fit, **and** passes the veto list.
- **Purpose**: Ride relevant news with a timely angle before the window closes.
- **Skills used**: `public-relations`, `social`
- **Loop body**:
  1. Scan news/HN/Reddit/X for stories intersecting the product's space.
  2. Score newsworthiness + fit + reach.
  3. Run the veto list. For a surviving top story, draft an angle (post, pitch, or commentary).
- **Self-check**: Is the angle genuinely additive, or forced? Kill forced takes — they cost credibility.
- **Veto list (skip immediately)**: tragedies, deaths, disasters, active crises; politically or socially charged stories unless the brand explicitly takes such stances; legal/medical/financial-sensitive topics; anything sourced from an unverified/single unreliable source.
- **State / idempotency**: Dedupe on story ID; one angle per story; never re-pitch a covered story.
- **Stop / bail-out**: Any veto trip → skip. Always require human approval before pitching/posting. Most days will skip — that's correct.
- **Output**: A staged post/pitch for human approval, or nothing.

### The social-listening loop
- **Check cadence**: Daily
- **Acts when**: A thread/mention clears the ICP-fit + intent + reach score.
- **Purpose**: Surface the highest-value conversations to engage in, instead of scrolling feeds.
- **Skills used**: `social` (see its `references/listening.md`), `community-marketing`
- **Loop body**:
  1. Pull mentions and relevant threads across configured sources.
  2. Score by ICP fit, intent, reach, and comment opportunity.
  3. Draft comments/replies for the top handful.
- **Self-check**: Would a human recognize each reply as genuinely useful, not promotional?
- **State / idempotency**: Track already-engaged threads; never double-reply. Respect a per-account interaction cooldown.
- **Stop / bail-out**: Nothing clears the threshold → skip. Stage replies for human post (don't auto-post — bot-detection + brand risk).
- **Output**: A short list of threads with drafted, on-brand replies.

### The community-engagement loop
- **Check cadence**: Daily
- **Acts when**: A target community (subreddit/Slack/Discord/forum) has a relevant thread where a helpful, non-promotional reply fits.
- **Purpose**: Build durable presence and trust in the communities where the ICP lives.
- **Skills used**: `community-marketing`, `social`
- **Loop body**:
  1. Scan configured communities for relevant threads/questions.
  2. Score for genuine help opportunity (not just keyword match).
  3. Draft value-first replies; note any that warrant a longer resource.
- **Self-check**: Does the reply lead with help and respect community norms? Self-promo ratio stays low.
- **State / idempotency**: Track engaged threads + per-community posting cadence to avoid over-posting.
- **Stop / bail-out**: No genuine-help opportunity → skip. Stage for human review where communities are strict about vendors.
- **Output**: Drafted community replies + resource ideas.

### The competitor-watch loop
- **Check cadence**: Weekly
- **Acts when**: A competitor makes a substantive pricing, positioning, product, or messaging change.
- **Purpose**: Catch competitor moves early enough to respond.
- **Skills used**: `competitor-profiling`, `competitors`, `product-marketing`
- **Loop body**:
  1. Fetch competitor pricing pages, homepages, changelogs, recent posts.
  2. Diff vs. last snapshot.
  3. Summarize meaningful changes; flag anything needing a response (comparison-page update, counter-messaging).
- **Self-check**: Substantive vs. cosmetic? Don't raise a copy tweak as a strategic shift.
- **State / idempotency**: Store per-competitor snapshots; diff against the last, and don't re-flag a known change.
- **Stop / bail-out**: No meaningful diffs → log "no change."
- **Output**: A change digest + recommended responses.

### The backlink-prospecting loop
- **Check cadence**: Weekly
- **Acts when**: New relevant link/guest-post/mention targets appear (or the pipeline is thin).
- **Purpose**: Keep a steady flow of link-building and earned-mention opportunities.
- **Skills used**: `public-relations`, `seo-audit`
- **Loop body**:
  1. Find new prospects: sites linking to competitors, relevant roundups, unlinked brand mentions, resource pages.
  2. Qualify by relevance + authority.
  3. Draft outreach angles for the top targets.
- **Self-check**: Is the target genuinely relevant, or a low-quality link that could hurt? Skip spammy sites.
- **State / idempotency**: Track already-contacted targets + outcomes; respect a follow-up cadence, don't re-pitch cold.
- **Stop / bail-out**: No qualified new targets → skip. Human-approve outreach sends.
- **Output**: A qualified prospect list with drafted outreach.

### The directory-submission loop
- **Check cadence**: Monthly
- **Acts when**: A relevant new directory/launch platform/marketplace exists that the product isn't listed on.
- **Purpose**: Steadily expand distribution and referral/SEO footprint via directories.
- **Skills used**: `directory-submissions`
- **Loop body**:
  1. Check for new/relevant directories, launch sites, and marketplaces.
  2. Qualify by relevance, authority, and audience fit.
  3. Prepare listing copy/assets for the top ones.
- **Self-check**: Real audience/SEO value, or a link farm? Skip low-quality directories.
- **State / idempotency**: Maintain a submitted-directories list; never resubmit.
- **Stop / bail-out**: No worthwhile new directories → skip.
- **Output**: Prepared listings staged for submission.

### The partner-pipeline loop
- **Check cadence**: Monthly
- **Acts when**: A viable co-marketing, integration, affiliate, or newsletter-swap opportunity surfaces (or the pipeline is thin).
- **Purpose**: Keep a fresh pipeline of partnership and co-marketing opportunities.
- **Skills used**: `co-marketing`, `referrals`
- **Loop body**:
  1. Scan for potential partners (complementary tools, aligned audiences, active newsletters, integration targets).
  2. Qualify by audience overlap + reach + fit.
  3. Draft partnership/swap outreach for the top prospects.
- **Self-check**: Real audience overlap and mutual value, or a one-sided ask? Skip mismatches.
- **State / idempotency**: Track contacted partners + status; respect follow-up cadence.
- **Stop / bail-out**: No qualified opportunities → skip. Human-approve outreach.
- **Output**: A qualified partner list with drafted outreach.

---

## Activation

### The onboarding drop-off loop
- **Check cadence**: Weekly
- **Acts when**: An onboarding step's drop exceeds benchmark or regresses vs. last period.
- **Purpose**: Find and fix the biggest leak between signup and first value.
- **Skills used**: `onboarding`, `analytics`, `cro`
- **Loop body**:
  1. Pull the activation funnel step-by-step (signup → key action → aha).
  2. Identify the worst-dropping step vs. benchmark and last period.
  3. Diagnose likely cause; propose one focused fix + how to measure it.
- **Self-check**: Enough new users through the funnel for step rates to be significant?
- **State / idempotency**: Track which fixes were already proposed/shipped; measure their effect before re-touching.
- **Stop / bail-out**: Sample too small → widen window or skip.
- **Output**: One prioritized activation fix with a measurement plan.

### The signup-funnel-leak loop
- **Check cadence**: Weekly
- **Acts when**: A signup/checkout step regresses vs. baseline.
- **Purpose**: Keep the signup/checkout path converting as the site changes.
- **Skills used**: `signup`, `cro`, `analytics`, `ab-testing`
- **Loop body**:
  1. Pull conversion by step across the signup/checkout flow.
  2. Compare to baseline; flag regressions (a deploy or copy change may have hurt it).
  3. Draft a hypothesis + test for the worst step (hand test execution to `ab-testing`).
- **Self-check**: Rule out tracking breakage before declaring a real drop.
- **State / idempotency**: Track open regressions + running tests; don't start a conflicting test.
- **Stop / bail-out**: No regression and no test-worthy idea → skip.
- **Output**: A prioritized experiment brief for `ab-testing`.

### The lead-capture-asset loop
- **Check cadence**: Monthly
- **Acts when**: A lead magnet, free tool, or opt-in underperforms on capture rate.
- **Purpose**: Keep top-of-funnel capture assets (lead magnets + free tools) converting visitors to leads.
- **Skills used**: `lead-magnets`, `free-tools`, `cro`, `popups`
- **Loop body**:
  1. Pull view → capture conversion for each lead magnet, free tool, and opt-in.
  2. Flag underperformers vs. benchmark; diagnose (offer, placement, form friction, targeting).
  3. Propose a fix or refresh (new angle, better placement, reduced friction).
- **Self-check**: Enough traffic per asset for the capture rate to be meaningful?
- **State / idempotency**: Track last-optimized date per asset; cooldown before re-touching.
- **Stop / bail-out**: All assets healthy → skip.
- **Output**: A prioritized fix per underperforming asset.

### The feature-adoption loop
- **Check cadence**: Weekly
- **Acts when**: A sticky/valuable feature is underused by a segment that would benefit.
- **Purpose**: Drive adoption of the features that correlate with retention.
- **Skills used**: `onboarding`, `emails`, `analytics`
- **Loop body**:
  1. Identify high-retention-correlated features and the segments not using them.
  2. Pick the highest-leverage feature × segment.
  3. Draft an in-app nudge or email to drive adoption.
- **Self-check**: Is the feature genuinely valuable to that segment, or would the nudge be noise? Don't push features people rationally skip.
- **State / idempotency**: Track who's already been nudged for which feature; enforce a cooldown; suppress adopters.
- **Stop / bail-out**: No clear feature × segment gap → skip.
- **Output**: A staged adoption nudge.

---

## Retention

### The churn-signal loop
- **Check cadence**: Daily (or on-trigger)
- **Acts when**: An account newly crosses a churn-risk threshold and isn't already in an intervention.
- **Purpose**: Intervene inside the short window before an at-risk account leaves.
- **Skills used**: `churn-prevention`, `analytics`, `emails`
- **Loop body**:
  1. Score accounts on churn-risk signals (usage decline, seat drop, dunning, support escalations).
  2. Segment newly at-risk accounts.
  3. Match each to the right intervention (re-engagement email, CS outreach, offer); stage it.
- **Self-check**: Is the "drop" a real trend or a weekend/holiday dip? Compare to the account's own baseline.
- **State / idempotency**: Never re-trigger on an account already in an active intervention; enforce a cooldown between attempts.
- **Stop / bail-out**: No newly at-risk accounts → skip. Escalate high-value accounts to a human rather than auto-emailing.
- **Output**: A prioritized at-risk list with staged interventions.

### The lifecycle-email-refresh loop
- **Check cadence**: Monthly
- **Acts when**: A sequence email underperforms on real engagement or contains stale content.
- **Purpose**: Keep automated sequences performing as the product and audience evolve.
- **Skills used**: `emails`, `analytics`, `copy-editing`
- **Loop body**:
  1. Pull per-email performance — clicks, conversions, replies, unsubscribes, spam complaints, bounces (**not opens** — open tracking is unreliable post-privacy-changes).
  2. Flag weak performers and stale references (old features, dates, pricing).
  3. Draft rewrites or subject-line tests for the bottom performers.
- **Self-check**: Enough sends per email for rates to be meaningful?
- **State / idempotency**: Track last-revised date per email; cooldown before re-testing.
- **Stop / bail-out**: All sequences healthy → skip. **Pause and escalate any sequence with rising complaint/bounce rates — that's a deliverability emergency, not a copy tweak.**
- **Output**: Staged email rewrites + subject-line tests.

### The re-engagement loop
- **Check cadence**: Weekly
- **Acts when**: A user newly crosses the inactivity threshold.
- **Purpose**: Win back dormant users before they're gone for good.
- **Skills used**: `emails`, `sms`, `offers`
- **Loop body**:
  1. Identify users newly crossing the inactivity threshold.
  2. Pick the win-back angle (new feature, offer, "we miss you," sunset warning).
  3. Draft the message; set suppression so they aren't re-hit next week.
- **Self-check**: Truly dormant, or just low-frequency-by-design users? Don't nag healthy accounts.
- **State / idempotency**: Track win-back attempts per user; suppress after each send for the cooldown.
- **Stop / bail-out**: After N unsuccessful attempts, move to sunset — not another email.
- **Output**: A staged win-back message + updated suppression list.

### The email-deliverability loop
- **Check cadence**: Weekly
- **Acts when**: Bounce, complaint, or unsubscribe rates rise, or list-hygiene decays.
- **Purpose**: Protect sender reputation and inbox placement.
- **Skills used**: `emails`, `analytics`
- **Loop body**:
  1. Monitor bounces, spam complaints, unsubscribes, domain/DKIM/SPF/DMARC health, and inbox-placement signals.
  2. Flag rising problem rates or authentication issues.
  3. Recommend actions: suppress hard bounces, sunset chronically unengaged, fix auth, throttle.
- **Self-check**: Is a spike a one-off send or a trend? Correlate with recent campaigns.
- **State / idempotency**: Track already-suppressed addresses + last hygiene sweep date.
- **Stop / bail-out**: All metrics healthy → log and skip. **Escalate a complaint-rate spike immediately** — reputation damage compounds fast.
- **Output**: A deliverability report + a suppression/hygiene action list.

### The voice-of-customer loop
- **Check cadence**: Weekly
- **Acts when**: New feedback (NPS, surveys, support tickets, reviews, calls) has arrived.
- **Purpose**: Route feedback to the right action **and** mine it for marketing inputs.
- **Skills used**: `customer-research`, `churn-prevention`, `referrals`, `copywriting`
- **Loop body**:
  1. Collect new feedback across sources.
  2. Route: detractors/at-risk → save motion (`churn-prevention`); promoters → referral/review ask (`referrals`); recurring pain/desire → experiment + copy inputs.
  3. Extract verbatim customer language for copy, FAQ, and objection-handling.
- **Self-check**: Is a theme a real pattern or one loud voice? Require a minimum count before acting on it.
- **State / idempotency**: Track processed feedback IDs; never double-route the same item.
- **Stop / bail-out**: No new feedback → skip. Escalate sensitive/legal complaints to a human.
- **Output**: Routed actions + a language/insight digest for marketing.

---

## Revenue

### The trial-conversion loop
- **Check cadence**: Daily
- **Acts when**: A trial user reaches a conversion-relevant moment (mid-trial, near-expiry, activated-but-not-paid).
- **Purpose**: Move more trials to paid with well-timed nudges.
- **Skills used**: `emails`, `paywalls`, `analytics`, `offers`
- **Loop body**:
  1. Segment active trials by stage and activation level.
  2. Match each to the right nudge (value recap, use-case tip, near-expiry push, offer).
  3. Stage the nudge.
- **Self-check**: Is the user activated enough for a paid push to land, or do they need more value first?
- **State / idempotency**: Track nudges sent per trial; enforce cadence; suppress converters.
- **Stop / bail-out**: No trials at an actionable stage → skip. Don't over-message a single trial.
- **Output**: Staged, stage-appropriate trial nudges.

### The PQL / upgrade-intent loop
- **Check cadence**: Daily
- **Acts when**: A free/trial user shows product-qualified buying intent (usage limits, key-feature use, team invites).
- **Purpose**: Catch high-intent users and stage upgrade outreach at the right moment.
- **Skills used**: `analytics`, `sales-enablement`, `revops`
- **Loop body**:
  1. Score free/trial users on PQL signals.
  2. Surface newly qualified users.
  3. Stage the right motion (in-app upgrade prompt, sales-assist for high-value, targeted email).
- **Self-check**: Is the signal genuine buying intent or incidental usage? Calibrate the threshold to avoid false positives.
- **State / idempotency**: Track already-actioned PQLs; don't re-route within the cooldown.
- **Stop / bail-out**: No newly qualified users → skip. Route high-value accounts to a human, don't auto-close.
- **Output**: A prioritized PQL list with staged motions.

### The pricing-page-experiment loop
- **Check cadence**: Monthly (tests run longer)
- **Acts when**: No test is running on the page and there's a worthwhile hypothesis — or a running test has concluded.
- **Purpose**: Improve pricing-page conversion **and revenue quality**, continuously.
- **Skills used**: `pricing`, `ab-testing`, `cro`
- **Loop body**:
  1. Review pricing-page conversion, plan mix, and revenue-per-visitor.
  2. Generate one pricing/packaging/copy hypothesis, or read a concluded test.
  3. Hand design/analysis to `ab-testing`; promote a clean winner.
- **Self-check**: Judge winners on **revenue per visitor, plan mix, refunds, downgrades, churn, and support load — not conversion rate alone.** Is the running test statistically done before you call it?
- **State / idempotency**: Track the running test + concluded-test log; never start a conflicting test on the same page.
- **Stop / bail-out**: A test is in flight → hold. **Do not promote a variant that lifts conversion but lowers revenue-per-visitor or raises refunds/churn.**
- **Output**: A test result + next hypothesis.

### The paywall-optimization loop
- **Check cadence**: Monthly
- **Acts when**: No paywall test is running and there's a hypothesis — or one has concluded.
- **Purpose**: Improve in-app upgrade conversion without degrading revenue quality.
- **Skills used**: `paywalls`, `ab-testing`, `analytics`
- **Loop body**:
  1. Pull paywall view → upgrade conversion and bounce points.
  2. Form one hypothesis (trigger timing, framing, plan anchor), or read a concluded test.
  3. Hand execution to `ab-testing`.
- **Self-check**: Segment by plan/cohort — an aggregate number can hide a segment that's tanking. Watch refunds/downgrades alongside conversion.
- **State / idempotency**: Track running/concluded tests; no conflicting tests.
- **Stop / bail-out**: Test in flight → hold. Don't promote a conversion win that raises refunds or churn.
- **Output**: A test result + next hypothesis.

### The expansion / upsell loop
- **Check cadence**: Weekly
- **Acts when**: An existing paid account hits an expansion signal (usage near limits, added seats, new use case).
- **Purpose**: Grow revenue from existing customers via well-timed upsell/cross-sell.
- **Skills used**: `revops`, `sales-enablement`, `emails`
- **Loop body**:
  1. Score paid accounts on expansion signals.
  2. Surface newly expansion-ready accounts.
  3. Stage the right motion (usage-based upgrade prompt, CSM outreach, cross-sell offer).
- **Self-check**: Is the account healthy enough that an upsell won't sour the relationship? Don't upsell an at-risk account — that's a churn loop's job.
- **State / idempotency**: Track upsell touches per account; enforce cadence.
- **Stop / bail-out**: No expansion-ready accounts → skip. Route strategic accounts to a human.
- **Output**: A prioritized expansion list with staged motions.

### The failed-payment / dunning loop
- **Check cadence**: Daily
- **Acts when**: A payment fails or a card is about to expire.
- **Purpose**: Recover involuntary churn — often the highest-ROI retention work.
- **Skills used**: `revops`, `emails`
- **Loop body**:
  1. Detect failed payments and upcoming card expirations.
  2. Trigger the dunning sequence (retry schedule + escalating update-card messaging).
  3. Route persistent failures to a human/CS.
- **Self-check**: Is the failure involuntary (card issue) vs. an intentional cancel? Don't dun someone who chose to leave.
- **State / idempotency**: Track dunning stage per account; follow the retry schedule; stop on recovery.
- **Stop / bail-out**: After the final retry, escalate/deactivate per policy — don't loop forever.
- **Output**: An active dunning queue + recovery status.

---

## Referral & Advocacy

### The referral-nudge loop
- **Check cadence**: Weekly
- **Acts when**: A user hits a "happy moment" (milestone, positive NPS) and hasn't been asked recently.
- **Purpose**: Ask for referrals when users are most delighted.
- **Skills used**: `referrals`, `emails`
- **Loop body**:
  1. Identify users who just hit a happy moment and aren't in the ask-cooldown.
  2. Match to the right ask (share link, incentive, review request).
  3. Stage the ask.
- **Self-check**: Genuinely a happy moment, or just any event? A bad-timing ask erodes goodwill.
- **State / idempotency**: Enforce a cooldown — never ask the same user twice in the window.
- **Stop / bail-out**: No one at a happy moment → skip.
- **Output**: A staged, well-timed referral ask.

### The review-and-UGC-harvest loop
- **Check cadence**: Weekly
- **Acts when**: New reviews, testimonials, or user-generated content have appeared.
- **Purpose**: Keep a steady flow of social proof and route it into marketing.
- **Skills used**: `social`, `referrals`, `sales-enablement`, `cro`
- **Loop body**:
  1. Collect new reviews/testimonials/UGC/mentions since last run.
  2. Sort by strength and relevance.
  3. Draft where each should go (site proof section, ad, social post, sales deck).
  4. Flag anything negative for a human response.
- **Self-check**: Is it genuinely strong and on-message? Don't force weak proof into prime placement.
- **State / idempotency**: Track already-harvested items; never re-use the same one twice.
- **Stop / bail-out**: **Verify consent and platform ToS before public reuse; add FTC-required disclosure for incentivized content.** No verifiable consent, or platform prohibits reuse → don't use. Negative/sensitive → escalate to a human, don't auto-publish.
- **Output**: New proof assets routed to their destinations.

### The review-site-management loop
- **Check cadence**: Weekly
- **Acts when**: New reviews land on G2/Capterra/app stores, or listings drift out of date.
- **Purpose**: Maintain reputation and conversion on third-party review platforms.
- **Skills used**: `sales-enablement`, `social`, `cro`
- **Loop body**:
  1. Track new reviews across review sites/app stores.
  2. Draft responses (thank promoters, address detractors constructively).
  3. Flag listing updates needed (screenshots, features, pricing).
- **Self-check**: Is the response specific and non-defensive? Never argue publicly with a reviewer.
- **State / idempotency**: Track responded reviews; never double-respond.
- **Stop / bail-out**: No new reviews/updates → skip. Human-approve responses to negative/legal-sensitive reviews.
- **Output**: Drafted responses + a listing-update checklist.

### The case-study-sourcing loop
- **Check cadence**: Monthly
- **Acts when**: A customer hits case-study-worthy success (strong results, milestone, enthusiastic feedback).
- **Purpose**: Keep a pipeline of case studies and customer stories.
- **Skills used**: `sales-enablement`, `customer-research`, `referrals`
- **Loop body**:
  1. Identify customers with standout results/engagement.
  2. Qualify for a case study (results, willingness, logo value).
  3. Draft the outreach + interview questions.
- **Self-check**: Are the results real and attributable, or coincidental? Verify before pitching a story.
- **State / idempotency**: Track approached customers + status; respect a no-repeat cooldown.
- **Stop / bail-out**: No qualified candidates → skip. Human-approve customer outreach.
- **Output**: A candidate list with drafted outreach.

---

## Ongoing Ops / Meta

### The weekly-marketing-review loop
- **Check cadence**: Weekly (Mon 9am)
- **Acts when**: Always runs — this is the heartbeat. It "acts" by flagging the week's notable movers.
- **Purpose**: One standing full-funnel pulse so nothing drifts unnoticed.
- **Skills used**: `analytics`, `marketing-plan`, `marketing-ideas`
- **Loop body**:
  1. Pull top-line AARRR metrics vs. last week and vs. plan.
  2. Flag the biggest mover (good and bad) per stage.
  3. Tie each flag to the loop or skill that should act on it; surface 1–2 experiment ideas.
- **Self-check**: Distinguish trend from noise before raising an alarm.
- **State / idempotency**: Store each week's snapshot for accurate week-over-week deltas.
- **Stop / bail-out**: Manual disable + error-halt. On a data-source outage, report "stale data," never fabricated movement. (Not "n/a" — even the heartbeat needs an off switch and an error path.)
- **Output**: A one-page weekly digest with owners/next actions.

### The experiment-backlog loop
- **Check cadence**: Weekly
- **Acts when**: New hypotheses exist to log, the backlog needs re-ranking, or a test slot is free.
- **Purpose**: Keep the experiment pipeline full and prioritized. **Thin wrapper — defer all test design, statistical analysis, and velocity management to `ab-testing`.**
- **Skills used**: `ab-testing` (owner), `cro`, `analytics`
- **Loop body**:
  1. Harvest new hypotheses from the week (data, research, competitors, support, other loops).
  2. Re-rank the backlog with ICE.
  3. If a slot is free, hand the top idea to `ab-testing`; if a test concluded there, log the learning.
- **Self-check**: Is the top idea actually testable with current traffic, or ICE-inflated?
- **State / idempotency**: Dedupe incoming hypotheses against the backlog; track which tests are live.
- **Stop / bail-out**: Backlog full and a test running → just log new ideas. Don't duplicate `ab-testing`'s job.
- **Output**: An updated, ranked backlog (the source of record lives with `ab-testing`).

### The analytics-anomaly loop
- **Check cadence**: Daily
- **Acts when**: A tracked metric breaks its expected band (spike or drop beyond normal variance).
- **Purpose**: Catch anything breaking — good or bad — before it runs for days unnoticed.
- **Skills used**: `analytics`
- **Loop body**:
  1. Check key metrics (traffic, signups, conversion, revenue, spend) against their normal range.
  2. Flag anomalies; separate "real event" from "tracking artifact."
  3. Route each to the responsible loop/owner for diagnosis.
- **Self-check**: Is the anomaly real or a tracking/seasonality artifact? Check for known causes (holiday, launch, deploy) before alarming.
- **State / idempotency**: Track already-alerted anomalies; don't re-alert the same ongoing one daily.
- **Stop / bail-out**: All metrics in-band → silent (no alert = good). Escalate a revenue/spend anomaly immediately.
- **Output**: An anomaly alert routed to an owner, or nothing.

### The brand-mention / reputation loop
- **Check cadence**: Daily
- **Acts when**: A meaningful brand mention appears anywhere (not just where you're listening for engagement).
- **Purpose**: Monitor and protect reputation; respond where it matters.
- **Skills used**: `social`, `public-relations`
- **Loop body**:
  1. Scan the open web/social/forums for brand mentions.
  2. Classify sentiment + reach + risk.
  3. Route: positive → amplify/thank; negative/risky → drafted response for human review; unlinked mention → backlink-prospecting.
- **Self-check**: Does a negative mention need a response, or would engaging amplify it? Judge reach + legitimacy.
- **State / idempotency**: Dedupe on mention ID; track handled mentions.
- **Stop / bail-out**: No meaningful mentions → skip. **Always human-approve responses to negative/crisis mentions** — never auto-reply to a complaint.
- **Output**: A mention digest with routed actions.

### The tracking-QA loop
- **Check cadence**: Weekly (and on deploy / campaign launch)
- **Acts when**: Analytics, pixels, UTMs, or conversion events are missing, misfiring, or misconfigured.
- **Purpose**: Keep the measurement layer trustworthy — every other loop depends on it.
- **Skills used**: `analytics`
- **Loop body**:
  1. Verify key events fire correctly, pixels are present, UTMs are consistent, and conversions attribute.
  2. Flag broken/missing/duplicate tracking, especially after deploys or new campaigns.
  3. Recommend fixes.
- **Self-check**: Is it truly broken, or an expected change? Confirm against a known-good baseline.
- **State / idempotency**: Track open tracking issues; update rather than re-file.
- **Stop / bail-out**: All tracking healthy → log "clean." **Escalate a broken revenue/conversion event immediately** — every downstream loop is blind until it's fixed.
- **Output**: A tracking-QA report with prioritized fixes.

### The campaign-postmortem loop
- **Check cadence**: On campaign end (event-based)
- **Acts when**: A campaign (launch, promo, seasonal push) concludes.
- **Purpose**: Capture results, lessons, and reusable assets so each campaign compounds.
- **Skills used**: `analytics`, `marketing-plan`
- **Loop body**:
  1. Pull final campaign results vs. goals.
  2. Capture what worked, what didn't, and why; save reusable assets (copy, creative, workflows).
  3. Feed learnings into the experiment backlog and the next plan; log follow-ups.
- **Self-check**: Are conclusions supported by the data, or hindsight narrative? Separate correlation from cause.
- **State / idempotency**: One postmortem per campaign; don't re-run on an already-documented campaign.
- **Stop / bail-out**: No concluded campaign → skip.
- **Output**: A postmortem doc + backlog/plan inputs.

---

## Adapting and authoring loops

To adapt a loop: keep all nine anatomy parts, swap skills/thresholds for the user's stack, and re-tune cadence to signal speed. To author a brand-new one: use `loop-template.md` (copy-paste template + fill-in prompts + worked example + ship checklist). Either way, do not ship a loop until every part is filled — especially **State / idempotency**, **Self-check**, and **Stop / bail-out**. A loop without those isn't a system; it's a way to do the wrong thing on a schedule, repeatedly, to the same people.


---

# references/loop-guardrails.md

# Loop Guardrails & Compliance

Loops act on a schedule, often on customer data, sometimes with money or a public voice. This reference consolidates the safety rules that keep autonomous loops from doing harm. Apply it to every loop that sends, spends, publishes, or touches personal data.

## The two-tier action model

Classify every action a loop can take:

**Tier 1 — Autonomous-safe** (a loop may do these unattended):
read data, analyze, diff, score, **draft**, and **stage** work for review.

**Tier 2 — Gated** (require a human checkpoint by default):
**spend** money, **shift budget**, **send** messages, **publish** anything public, **delete/suppress** records, **change** live account settings.

A Tier-2 action may run without a per-action human check only if the user has **explicitly authorized** it *and* it's bounded by caps + an allowlist (below). Absent that, the loop stages a draft and a human approves.

## Spend guardrails (ad-fatigue, paid-search, retargeting, expansion)

- **Hard caps**: a daily/weekly spend ceiling the loop can never exceed; halt and alert if approached.
- **Per-run change limit**: cap how much budget can move in one run (e.g., ≤20%), so a bad read can't reallocate everything.
- **Allowlist**: only specified accounts/campaigns are eligible for autonomous changes; everything else is staged.
- **Directional guardrails**: judge paid changes on revenue/ROAS, not just CTR/CPA — never optimize a proxy metric into a revenue loss.

## Publish & send guardrails (email, social, PR, community, reviews)

- **Default to a staging queue** + human approval for anything public or outbound. Auto-*drafting* is fine; auto-*publishing* is not, unless explicitly authorized.
- **Volume caps**: per-run and per-recipient limits so a loop can't blast a list or over-post a channel.
- **Suppression first**: always check suppression/unsubscribe/do-not-contact lists before sending.
- **No auto-posting where detection/ToS bites**: owned social, press pitches, and community replies are staged for a human (bot detection + brand risk).

## Compliance

Match each rule to the loops it governs:

- **CAN-SPAM / CASL (email/SMS loops — lifecycle, re-engagement, churn, trial, dunning, referral)**: honor unsubscribes immediately and permanently; include a working unsubscribe + physical address; identify the sender; don't email/text without a lawful basis or consent; scrub against suppression every send.
- **GDPR / CCPA (any loop touching personal data)**: process on a lawful basis; get consent for EU marketing; honor deletion and opt-out requests; minimize data pulled and retained; don't repurpose data beyond its collected purpose.
- **FTC (review-and-UGC-harvest, referral, social)**: disclose material connections and incentives (#ad, "I was compensated"); only use testimonials with permission; no fabricated or cherry-picked-to-mislead claims.
- **Platform ToS (social-listening, community-engagement, review-site-management, scraping-based loops)**: respect rate limits and automation rules; follow review-platform response policies; don't scrape or auto-act where prohibited.

When a loop can't confirm consent, permission, or ToS-compatibility, its stop condition is **don't act** — stage for a human instead.

## PII handling

- Don't log raw PII in loop **state** or **run logs** — use internal IDs or hashes.
- Pull the minimum personal data needed to make the decision; don't hoard it in state.
- Keep exports and drafts out of shared/synced locations unless intended.

## Always-escalate list

These never run fully autonomously — route to a human regardless of authorization:

- Negative or crisis brand mentions; responses to complaints or legal/medical/financial-sensitive issues.
- Newsjacking angles (see the veto list in the catalog) — human approval before any pitch/post.
- High-value or strategic accounts (enterprise, at-risk logos).
- Anomalies in **revenue** or **ad spend** — flag immediately, don't self-correct.
- Anything that would delete data or contact a large audience at once.

## Kill switch

Every scheduled loop needs a manual off switch, and you should know how to stop **all** loops fast (disable the schedule / cron, or a global flag the loop bodies check). Document it where the loops are scheduled. A loop you can't stop quickly is a liability.

## Pre-launch guardrail checklist

Before scheduling any loop that sends, spends, publishes, or touches personal data:

- [ ] Every action is classified Tier 1 (auto) or Tier 2 (gated).
- [ ] Tier-2 actions are staged for approval — or bounded by explicit authorization + caps + allowlist.
- [ ] Spend loops have a hard cap and a per-run change limit.
- [ ] Send loops check suppression/unsubscribe and have volume caps.
- [ ] Applicable compliance rules (CAN-SPAM/GDPR/FTC/ToS) are satisfied, with "don't act" as the fallback.
- [ ] No raw PII in state or logs.
- [ ] The always-escalate cases route to a human.
- [ ] There's a documented kill switch.


---

# references/loop-orchestration.md

# Loop Orchestration & Rollout

Loops aren't independent scripts — they compose into a marketing operating system. This reference covers how they fit together and the order to adopt them so you never build 43 at once.

## The system view

Loops fall into four layers. Data flows down and learnings flow back up.

```
SENSING        analytics-anomaly · tracking-QA · weekly-marketing-review
                  │  (detect what changed; trust the numbers first)
                  ▼
DIAGNOSTIC     per-stage watchers — onboarding drop-off, churn-signal,
               ranking-drop, landing-page regression, ad-fatigue, …
                  │  (figure out what to do about it)
                  ▼
ACTION         staged drafts, nudges, outreach, budget moves
                  │  (mostly human-checkpointed)
                  ▼
LEARNING       experiment-backlog · campaign-postmortem · voice-of-customer
                  │  (capture what worked)
                  └──────────────► feeds back into SENSING & DIAGNOSTIC
```

Key connective tissue:
- **weekly-marketing-review is the router.** It reads top-line metrics and dispatches each notable mover to the loop that owns it. It's the one loop that sees the whole board.
- **tracking-QA + analytics-anomaly are the foundation.** Every other loop reads from analytics. If tracking is broken, every downstream loop acts on lies. These come first.
- **experiment-backlog is the sink.** Hypotheses generated by many loops (signup-leak, pricing, onboarding, voice-of-customer) converge here, then hand off to `ab-testing`. Don't let each loop run its own tests.
- **voice-of-customer is a source.** Customer language it mines feeds copy for ad-fatigue, lifecycle-email, landing-page, and pricing loops.
- **campaign-postmortem closes the loop.** Its learnings become next quarter's hypotheses and plan inputs.

Avoid duplicate ownership: when two loops could act on the same signal, one owns the action and the other just flags. (E.g., an at-risk account belongs to churn-signal, not expansion/upsell — never upsell an account that's churning.)

## Rollout path (adopt in this order)

Add a loop only when the loops before it are running and earning their keep. Each stage assumes the previous one is solid.

**Stage 0 — Foundation (trust the data + see the board).**
`tracking-QA`, `weekly-marketing-review`.
You cannot run any loop responsibly on untrustworthy data or without a full-funnel pulse. This is non-negotiable and comes first.

**Stage 1 — Plug the leaks (highest ROI, protects existing revenue).**
`failed-payment/dunning`, `churn-signal`, `lifecycle-email-refresh`.
Recovering customers you already have is cheaper than acquiring new ones. Dunning alone often pays for the whole system.

**Stage 2 — Convert what you already get (fix the bucket before adding water).**
`onboarding drop-off`, `signup-funnel-leak`, `trial-conversion`.
More traffic into a leaky funnel is waste. Seal activation and conversion next.

**Stage 3 — Grow the top (now scale acquisition).**
`keyword-gap`, `content-repurposing`, `ad-fatigue`, `social-listening`, `analytics-anomaly`.
With the bucket sealed, turn on demand generation and the safety-net anomaly watcher.

**Stage 4 — Optimize monetization.**
`pricing-page-experiment`, `paywall-optimization`, `PQL/upgrade-intent`, `expansion/upsell`.
Once volume is healthy, tune revenue per user — judged on revenue quality, not conversion alone.

**Stage 5 — Compounding & advocacy.**
`referral-nudge`, `review-and-UGC-harvest`, `review-site-management`, `case-study-sourcing`, `partner-pipeline`, `brand-mention/reputation`, `experiment-backlog`, `campaign-postmortem`.
The flywheel: happy customers and earned media that feed back into acquisition, plus the learning loops that make everything compound.

The remaining catalog loops (content-decay, internal-linking, programmatic-SEO quality, content-calendar refill, paid-search query-mining, retargeting-hygiene, landing-page regression, community-engagement, competitor-watch, backlink-prospecting, directory-submission, feature-adoption, lead-capture-asset, email-deliverability, voice-of-customer) slot into the stage that matches their function as each channel becomes a priority.

## Rollout rules

- **One at a time.** Prove a loop earns its keep (someone acts on its output, it moves its metric) before adding the next.
- **Foundation before growth.** Acquisition loops before solid tracking + retention = pouring water into a leaky bucket.
- **Cap the total.** If you're running more loops than you can review the output of, you have vanity loops. Retire the ones nobody acts on.
- **Re-audit quarterly.** Recalibrate thresholds, kill dead loops, promote the ones that consistently drive action.


---

# references/loop-state.md

# Loop State & Run Logging

Idempotency is only real if the loop can remember what it already did between runs. This reference defines where that state lives and how to log runs — so loops don't double-act, re-nag the same people, or re-alert the same issue.

## Where state lives

Persist each loop's state in a file under `.agents/loops/` — the same `.agents/` convention this repo uses for `product-marketing.md` and `listening-sources.md`. One state file per loop:

```
.agents/loops/<loop-name>.json     # the loop's memory
.agents/loops/<loop-name>.log      # append-only run log
```

If your scheduler or platform provides its own dedupe/cursor storage, use that instead — the point is durable state, not the specific file. Never keep state only in memory; a loop that forgets on restart will repeat itself.

## What to store

A state file holds whatever the loop needs to not repeat itself:

```json
{
  "loop": "churn-signal",
  "last_run": "2026-07-01T09:00:00Z",
  "cursor": "2026-06-30T23:59:59Z",        // watermark — only process items newer than this
  "handled": ["acct_1042", "acct_1077"],    // dedupe keys already acted on
  "cooldowns": {                             // entity -> next-eligible timestamp
    "acct_1042": "2026-07-15T00:00:00Z"
  },
  "in_flight": ["exp_pricing_v3"],           // actions/tests currently open
  "counters": { "acct_1042_attempts": 2 }    // e.g. dunning/win-back attempt counts
}
```

- **cursor / watermark** — the high-water mark of what's been processed (a timestamp or last ID). The loop only looks at items past it.
- **handled** — dedupe keys for items already acted on, so re-runs skip them.
- **cooldowns** — per-entity suppression windows so you never re-contact someone inside the window.
- **in_flight** — open items (running tests, active interventions) so the loop doesn't start a conflicting one.
- **counters** — attempt counts that drive stop conditions (e.g., "after 2 win-back emails, stop").

Keep state small and prune it: expire old `handled`/`cooldown` entries once they're past their window.

## Idempotency patterns

- **Watermark**: process only items newer than `cursor`; advance `cursor` at the end of a successful run. Safe to re-run — it won't reprocess.
- **Dedupe set**: before acting on an item, check its key against `handled`; add it after acting.
- **Cooldown map**: before contacting an entity, check `cooldowns[entity]`; set it after contact.
- **In-flight guard**: before starting an action that shouldn't overlap (a test, an intervention), check `in_flight`.

## Run logging

Append one line per run, whether or not it acted. This is the audit trail and the vanity-loop detector.

```
2026-07-01T09:00Z  checked=312  acted=2   note="2 accounts newly at-risk, interventions staged"
2026-07-02T09:00Z  checked=298  acted=0   note="no action"
2026-07-03T09:00Z  checked=305  acted=0   note="no action"
```

Log at minimum: timestamp, how many items checked, how many acted on, and a short note. Use it to answer two questions:
- **Is it a vanity loop?** If every run is `acted=0` for weeks and nobody misses it — or it acts every run (a sign it's chasing noise) — reconsider it.
- **Did it double-act?** Two runs acting on the same entity means the dedupe/cooldown state isn't working.

## Resetting & backfilling safely

- To **reset** a loop, clear its `cursor`/`handled` — but keep `cooldowns` so a reset doesn't spam people who were recently contacted.
- On **first run** (no state yet), set the watermark to "now" rather than processing all history, or you'll blast every historical item. If you genuinely want a backfill, do a dry run first (log what it *would* do, act on nothing) and respect cooldowns.
- Never log raw PII in state or run logs — use IDs or hashes (see `loop-guardrails.md`).


---

# references/loop-template.md

# Loop Template

A copy-paste template for authoring your own marketing loop. Fill every one of the nine parts — a loop missing its **state/idempotency**, **self-check**, or **stop/bail-out** isn't a system, it's a way to do the wrong thing on a schedule.

Before you start, sanity-check that this *should* be a loop at all (see "When NOT to loop" in `SKILL.md`): it's recurring, signal-driven, and doesn't require human judgment to set strategy or creative direction each run.

---

## Blank template (copy this)

```markdown
### The <name> loop
- **Check cadence**: <how often it looks — match to how fast the signal changes, not how often you'd like an update>
- **Acts when**: <the action condition — what must be true to actually DO something vs. just check and skip. Most runs should skip.>
- **Purpose**: <the ONE outcome this loop exists to move>
- **Skills used**: <which marketing skills the loop orchestrates each run>
- **Loop body**:
  1. <step — usually: pull data / diff vs. last run>
  2. <step — identify what, if anything, crossed the action condition>
  3. <step — draft or stage the response>
- **Self-check**: <the verification done BEFORE acting — is the signal real vs. noise/seasonality/tracking bug? Is the sample big enough to be significant?>
- **State / idempotency**: <what it remembers between runs — last-run marker, dedupe key, cooldown window, "already handled" set — so it doesn't double-act or re-nag the same people>
- **Stop / bail-out**: <when it skips, halts, escalates to a human, or disables itself — plus what it does on error. Include a human checkpoint before anything that spends money or publishes.>
- **Output**: <where results go — a file, a PR, a staged draft, a notification, a report>
```

---

## Fill-in prompts (answer these, in order)

1. **What outcome does this protect or grow?** (rankings, ad efficiency, activation, retention, revenue, referrals) → *Purpose*
2. **How fast does that signal actually change?** (hours / days / weeks / months) → *Check cadence*
3. **What has to be true before it's worth acting?** (a threshold crossed, a new item appeared, a regression vs. baseline) → *Acts when*
4. **What data does it read and what does it produce each run?** → *Loop body* + *Output*
5. **What would make it act on a false signal?** (noise, seasonality, a tracking break, too-small a sample) → *Self-check*
6. **What must it remember so it doesn't repeat itself?** (dedupe key, cooldown, last-run marker) → *State / idempotency*
7. **When should it stop, skip, or hand off to a human?** (no action needed, error, spend/publish decision, N failed attempts) → *Stop / bail-out*

If you can't answer 5, 6, and 7 concretely, the loop isn't ready to run.

---

## Worked example (blank → filled)

Say you sell a freemium API tool and want to stop losing signups who never make their first API call.

```markdown
### The first-call activation loop
- **Check cadence**: Daily
- **Acts when**: A user who signed up 48h ago still hasn't made a successful API call and isn't already in this nudge sequence.
- **Purpose**: Increase the share of new signups that reach first value (first successful API call).
- **Skills used**: `onboarding`, `emails`, `analytics`
- **Loop body**:
  1. Pull signups from ~48h ago and their first-call status.
  2. Filter to those with zero successful calls and no active nudge.
  3. Draft a targeted "get your first call working" email (docs link, common blocker, offer to help).
- **Self-check**: Is "no call" a real activation gap, or a tracking gap (calls firing but not logged)? Confirm against server logs before emailing.
- **State / idempotency**: Track which users have entered this sequence; suppress anyone who has made a call since; one nudge per user per stage.
- **Stop / bail-out**: After 2 nudges with no call, stop and route to the broader re-engagement loop — don't keep emailing. Skip the run entirely if the events pipeline looks stale.
- **Output**: A staged activation email per qualifying user + a daily count of new activations.
```

Notice what makes it safe: the **self-check** guards against a tracking bug emailing active users, the **state** stops it re-nagging, and the **stop** caps attempts and hands off instead of looping forever.

---

## Ship checklist

Before you schedule a new loop, confirm:

- [ ] All nine parts are filled — especially self-check, state, and stop.
- [ ] Cadence matches signal speed (you're not checking daily for a weekly-moving signal).
- [ ] It's designed so **most runs do nothing** — it acts only on a real condition.
- [ ] Anything that **spends money or publishes** has a human checkpoint (unless caps + an allowlist are explicitly authorized).
- [ ] State prevents double-acting and re-nagging the same people.
- [ ] There's an error path (stale data → report "stale," don't fabricate movement) and a manual off switch.
- [ ] For scheduling mechanics, see the "Scheduling a loop" section in `SKILL.md`.

Once it runs, give it a few cycles and ask the "is this a vanity loop?" question: if nobody acts on the output, delete it.
