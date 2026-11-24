# Reference files for the `attribution` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/attribution-models.md

# Attribution Models — The Math, Worked

Six standard models, one journey scored six ways, and data-driven attribution explained without the black box. Use this when the user wants to understand *why* two models disagree, or needs to pick one defensibly.

## The worked journey

A single B2B buyer's path to a $12,000 annual deal, five touches over 38 days:

| # | Day | Touch | Role in the story |
|---|---|---|---|
| T1 | 0 | LinkedIn ad (paid social) | First discovered you — created awareness |
| T2 | 5 | Organic blog post (organic search) | Came back to learn — built interest |
| T3 | 12 | Retargeting ad (paid social) | Nudged back mid-consideration |
| T4 | 30 | Branded search (paid search, branded) | Ready to act — searched your name |
| T5 | 38 | Direct → demo request (direct) | Converted |

The whole point: **the touch that gets credit depends entirely on the model, and each model tells a different story about where your $12k came from.**

## The six models, applied

Credit for the $12,000 deal under each model:

| Touch | Channel | First-touch | Last-touch | Last non-direct | Linear | Time-decay | Position (U) |
|---|---|---|---|---|---|---|---|
| T1 | Paid social | **$12,000** | $0 | $0 | $2,400 | $175 | **$4,800** |
| T2 | Organic | $0 | $0 | $0 | $2,400 | $290 | $800 |
| T3 | Paid social | $0 | $0 | $0 | $2,400 | $575 | $800 |
| T4 | Paid search (branded) | $0 | $0 | **$12,000** | $2,400 | $3,415 | $800 |
| T5 | Direct | $0 | **$12,000** | $0 | $2,400 | **$7,545** | **$4,800** |

*(Time-decay uses a 7-day half-life — weight = 0.5^(days-before-conversion / 7), normalized: shares of ~1.5% / 2.4% / 4.8% / 28.5% / 62.9% (dollars rounded to sum to $12,000). With a 38-day journey the credit concentrates hard on the last two touches — which is exactly why time-decay behaves almost like last-touch on long cycles. Position-based is 40/40/20, the 20% split evenly across T2–T4.)*

**Read the disagreement:**
- **First-touch** hands everything to the **LinkedIn ad** — great for arguing paid social's demand-gen value, blind to what closed it.
- **Last-touch** hands everything to **Direct** — which is really "we don't know," the junk-drawer channel (see SKILL.md §6). This is how top-of-funnel gets defunded.
- **Last non-direct** hands it to **branded search** — but branded search only happened *because* the LinkedIn ad and blog created the demand. Crediting the closing branded click is crediting your own brand for demand someone else's channel created.
- **Linear** spreads it evenly — honest that all five mattered, useless for deciding what to cut (everything looks equally important).
- **Time-decay** favors the recent — reasonable for short cycles, but here it under-credits the LinkedIn ad that started everything.
- **Position-based** credits the **bookends** (discovered + closed) — usually the most defensible single model for B2B, because "what created this deal" and "what closed it" are the two decisions you actually make.

**The takeaway to give the user:** report **first-touch and last-touch side by side**. The LinkedIn-vs-Direct gap *is* the insight — it tells you paid social creates demand that later shows up as direct/branded. No single number captures that; the spread does.

## Data-driven / algorithmic attribution (Shapley), plainly

Data-driven attribution (Google's DDA, most MTA tools) doesn't use a fixed rule. It asks a counterfactual: **how much does each touch actually change the probability of conversion?** The formal engine is the **Shapley value** from cooperative game theory.

The plain-English version:

- Treat each touch as a "player" on a team that produced the conversion.
- Look across *all* your journeys — converting and non-converting.
- For a given touch, compare conversion rates of journeys that had it vs. otherwise-similar journeys that didn't, across every possible combination of the other touches.
- A touch's credit = its **average marginal lift** to conversion probability across all those combinations.

So if journeys with a retargeting touch convert meaningfully more often than identical journeys without it, retargeting earns real credit. If adding a channel changes nothing, it earns ~zero — even if it appears on every path.

**When it's worth it:**
- You have **volume** — the counterfactuals need enough conversions to be stable. (Google Ads historically gated data-driven attribution behind ~3,000 ad interactions and ~300 conversions in 30 days; it has since relaxed the hard minimums and made data-driven the default model, but the underlying reality is unchanged: below real volume, DDA is noise dressed as science.) Use position-based instead when you're thin.
- Your journeys are **mostly digital and tracked** — Shapley can only weigh touches it was fed. Offline events, dark social, and cookie-lost touches are invisible to it, so a high-word-of-mouth B2B motion will get a confidently-wrong DDA. Pair it with self-reported (SKILL.md §4).

**Its honest limitations:**
- **Black box** — you can't easily explain to a CFO why LinkedIn got 23%. "The model says so" is a weak budget argument on its own.
- **Correlation, not causation** — it models what *co-occurs* with conversion, not what *causes* it. That's why incrementality testing (see `measurement-paradigms.md`) exists: to validate what DDA claims.
- **Garbage in** — inherits every blind spot in your tracking. If half your journeys are "direct," DDA is confidently splitting credit on half-blind data.

## Choosing — a short decision guide

- **Short cycle, few touches, small volume** → last non-direct, plus a self-reported survey. Don't over-model.
- **Long B2B cycle, clear created/closed moments** → position-based as the primary, first-touch + last-touch shown alongside.
- **High volume, mostly-digital, need day-to-day allocation** → data-driven, validated periodically by incrementality.
- **Offline + brand-heavy, real budget** → don't rely on any user-level model; go MMM + incrementality (see `measurement-paradigms.md`).

In every case: **pick one model, stay consistent, and pair it with an out-of-model check.** Model-switching to make a channel look good is the fastest way to lose trust in the whole attribution program.


---

# references/by-business-type.md

# Attribution by Business Type

Attribution defaults differ sharply by business model. The same "which channel drives revenue?" question wants a different source of truth, model, and paradigm depending on how long your cycle is, how many people are involved, and where your budget goes. Two playbooks: B2B SaaS and Ecommerce/DTC. Match the user's product to one (or blend, for PLG-with-sales).

---

## B2B SaaS (long cycle, sales-assisted)

**Shape of the problem:** journeys run weeks to months, span multiple people (champion, economic buyer, users), and include touches that never appear in web analytics — a conference conversation, a sales call, a Slack-community mention, a peer recommendation. Deal values are high and volume is low, so every deal matters and averages are noisy.

**Why single-touch models mislead badly here:** with 15 touches over 3 months across 4 people, "last-touch = direct" and "first-touch = one LinkedIn ad" are both almost useless. The middle — and the offline — is where the deal was actually won.

### The B2B playbook

1. **Source of truth = the CRM**, not any analytics tool. Revenue is real in the CRM (closed-won, ARR); everything else explains where those deals came from. Pipeline and revenue attribution live in **revops** — attribution feeds it the "source" dimension.
2. **Models: first-touch + position-based, shown together.** First-touch values demand creation (which channel *started* the accounts that became pipeline). Position-based credits the created-and-closed bookends, the two decisions you actually make. Last-touch alone will defund your top of funnel — don't lead with it.
3. **Self-reported attribution is your strongest signal, not a nice-to-have.** Ask "How did you first hear about us?" on the **demo request / signup form** and again qualitatively on sales calls. For high word-of-mouth and dark-social-heavy B2B, this catches what tracking structurally can't (podcasts, communities, "my old coworker used you"). Weight it heavily.
4. **Attribute to pipeline stages, not just the conversion.** The useful B2B question isn't "what drove the form fill" — it's "what drove *qualified pipeline* and *closed revenue*." Break down MQL→SQL→closed-won by first-touch channel; a channel that fills forms but never closes is a trap. (Stage mechanics → revops.)
5. **MTA is weakest here; incrementality is awkward but valuable.** Low volume makes data-driven attribution unreliable and geo-tests hard. Use **on/off tests** for big-ticket programs (turn off a channel for a quarter, watch pipeline) and lean on self-reported + first-touch for the rest.
6. **Account-level, not just lead-level.** Attribution should roll touches up to the *account* (all the people at the buying company), or you'll credit whichever individual happened to fill the form. In practice one org is several people signing up with **mixed work *and* personal emails**, so person-level attribution scatters the story across records — match contacts to the account (email domain, enrichment, or your CRM's contact→account link) and attribute at the **account** level. That's where the signal has to land to be useful to a rep working the whole buying committee. Exclude free-mail domains (gmail/yahoo/outlook) from domain matching — they can't identify a company; fall back to enrichment or manual matching for personal-email signups. *(Production emphasis from Tessa Kriesel; the CRM-sync mechanics live in `first-party-tracking.md` Step 5.)*

**Tooling:** CRM (HubSpot/Salesforce) as truth; a product-analytics tool identifying by user/account UUID for first-party first-touch (see `first-party-tracking.md`); self-reported fields written to the CRM; RB2B-style de-anonymization to catch un-formed account visits.

**The B2B trap to name for the user:** branded search and direct will look like your best "channels" because that's where researched buyers convert. They're not channels — they're where demand *created elsewhere* cashes out. Segment branded vs. non-branded search and treat a big direct share as evidence your top-of-funnel is working, not as a channel to invest in.

---

## Ecommerce / DTC (short cycle, self-serve)

**Shape of the problem:** journeys are fast (minutes to a few days), high-volume, and almost entirely digital and self-serve. Budget concentrates in paid social + paid search + email/SMS. The conversion is a purchase you fully control (your checkout or a hosted one). The dominant lie is **platform over-attribution** — Meta and Google each claiming the same sales.

### The DTC playbook

1. **Source of truth = your store/backend** (Shopify, your payments system) — the count of actual orders. Platform-reported conversions get de-duped *against* that total; they never define it and are never summed.
2. **Distrust platform ROAS by default.** Post-iOS ATT, platforms model and estimate conversions, count view-through, and use generous windows — reported ROAS runs well above incremental ROAS. Use it for in-platform optimization (it's fine for the algorithm) but not for cross-channel budget truth.
3. **Last-touch is defensible for quick-turn, impulse SKUs** — the closing click really is most of the story for a $30 impulse buy. It gets dangerous as consideration lengthens (higher AOV, considered purchases), where it over-credits retargeting and branded search.
4. **MMM once spend is material.** When you're spending real money across paid social, search, and offline (podcasts, TV, influencers, OOH), MMM is how you allocate — it's the only paradigm that sees the untrackable channels and the saturation curves. Below ~six figures/month of blended spend, MMM is overkill; good UTMs + a survey do more.
5. **Incrementality on your biggest channels — especially the "always credited" ones.** Geo-holdouts and on/off tests earn their keep on retargeting, branded search, and Meta prospecting, which platform reporting flatters most. Incremental CPA (spend ÷ *incremental* orders) is the number that should move budget. (See `measurement-paradigms.md`.)
6. **Post-purchase survey to catch the dark-social + brand demand.** A one-question "How did you hear about us?" on the order-confirmation page consistently reveals that podcasts, TikTok organic, and word-of-mouth drive far more than pixels credit — because those touches convert later as "direct" or branded search. Kickstarter-era DTC brands run this as standard for exactly this reason.

**Tooling:** store/backend as truth; platform pixels + CAPI for optimization (setup → ads `conversion-tracking.md`); Supermetrics/Coupler to pull platform numbers into one place for de-duping; a post-purchase survey app; MMM tooling (Robyn/Meridian or a vendor) once spend justifies it.

**The DTC trap to name for the user:** summing platform-reported conversions. If Meta claims 100 and Google claims 80 but you had 120 orders, you do **not** have 180 conversions — you have 120 with overlapping claims. Anchor on the 120 and allocate the overlap with incrementality, not by trusting whichever platform shouts loudest.

---

## Blended / PLG-with-sales

Many modern SaaS businesses are both: self-serve signups *and* a sales-assisted motion for larger accounts. Blend the playbooks:

- Use the **DTC approach for the self-serve funnel** (fast, high-volume, first-party first-touch → conversion, defensible last-non-direct + survey).
- Use the **B2B approach for the sales-assisted funnel** (CRM as truth, position-based, pipeline-stage attribution, self-reported at demo).
- **Alias identities across the two** so a self-serve signup who later becomes a sales-assisted expansion keeps one journey (email↔UUID alias at signup — see `first-party-tracking.md`).
- Report them **separately.** Blending a $50 self-serve signup and a $50k enterprise deal into one "attribution" number hides both stories.


---

# references/first-party-tracking.md

# First-Party Attribution — The Own-Your-Attribution Runbook

How to instrument and stitch attribution yourself when you control the site/app. This is the build track (Pillar B). It's distilled from real production builds and kept tool-agnostic — **PostHog + SavvyCal are the worked example**, but the pattern maps to any product-analytics tool with `identify()`/merge (Segment, Amplitude, GA4 user-id) and any third-party conversion domain with a metadata passthrough + webhook (Calendly, Cal.com, Stripe Checkout, Typeform).

The core method — closing the `identify()` gap so conversions join to anonymous browsing history — is **adapted from Tessa Kriesel's PostHog attribution approach**. Several of the production refinements that make this operate at scale are also hers, credited inline: the full-touch-path capture that feeds the model track (Step 4), the CRM last-mile with source/confidence/basis and a Paid-vs-Organic read (Step 5), the account rollup, and the "expect ~zero until the stitch is verified, with a campaign-window fallback + backfill" window (Cross-subdomain stitching). Credit where due.

## The one idea

First-party attribution joins **anonymous browsing** to the **eventual conversion**:

```
anonymous visitor          identify() at conversion         breakdown
─────────────────          ────────────────────────         ─────────
distinct_id = anon_uuid    identify(email)                  conversion event
$initial_utm_source=...  → merges anon history        →     by $initial_utm_source
$initial_referrer=...      into person(email)               = "where do customers come from"
```

Everything below serves that join. If `identify()` never fires, every customer looks like they appeared from nowhere — that's *the gap*.

## Step 0 — Audit before you build

The most expensive mistake is rebuilding attribution that already works. Many SaaS apps already `identify()` at signup and already carry first-touch on person profiles. **Check the live data first:**

- Do person profiles carry `$initial_utm_source` / `$initial_referring_domain`?
- Does a conversion event (`Signed up`, `Converted to paid`) break down *cleanly* by channel, or is everything "Direct"?
- Is identity keyed by **email** or by an internal **UUID**? (This changes every guard below.)
- Does cross-subdomain stitching work (marketing site → app.yourdomain.com)?

Only instrument the **specific conversions that are genuinely un-joined**. In one real audit the self-serve funnel was already solved end-to-end; the *only* gap was a booking on a third-party domain. Don't touch what works.

## Step 1 — Identify at each real conversion

At every conversion moment, call `identify()` with a stable id, and set person properties:

```js
// Normalize before use as a distinct_id — analytics tools match exact strings,
// so "Corey@x.com" and "corey@x.com" split into two people otherwise.
export function identifyUser(email) {
  const normalized = email.trim().toLowerCase();
  window.posthog?.identify(normalized, { email: normalized });
}
```

With `person_profiles: 'identified_only'`, this is the moment the person is created and their first-touch props are stamped. Fire it on form success, signup, first purchase — any moment you learn who the anonymous visitor actually is.

## Step 2 — Stitch conversions on a domain you don't own

When the conversion completes on a third-party domain (a booking tool, hosted checkout), you can't run your analytics there. Smuggle the anonymous id through the tool's **metadata passthrough**, then merge it back in the **webhook**.

### 2a — Capture-phase link decorator

One document-level listener rewrites every outbound booking link at click time — no per-CTA edits, and it covers plain clicks, keyboard activation, and middle-click (`auxclick`):

```js
// Append the anonymous distinct_id to any SavvyCal link at click time.
function decorate(e) {
  const anchor = e.target?.closest?.("a[href]");
  if (!(anchor instanceof HTMLAnchorElement)) return;

  let url;
  try { url = new URL(anchor.href); } catch { return; }
  const host = url.hostname;
  if (host !== "savvycal.com" && !host.endsWith(".savvycal.com")) return;

  const distinctId = getPostHogDistinctId();   // anonymous-only — see guard
  if (!distinctId) return;                       // fail closed

  url.searchParams.set("metadata[ph_distinct_id]", distinctId);
  anchor.href = url.toString();
}
document.addEventListener("click", decorate, true);    // capture phase
document.addEventListener("auxclick", decorate, true);
```

For an **inline embed** (e.g. `/demo` with an embedded calendar), pass the same id in the embed's metadata config instead; poll briefly (~2s) for the id on fresh visits, but never block the calendar from rendering.

### 2b — Read the anonymous id safely

The SDK stub queues calls before it loads, so `get_distinct_id()` returns undefined early — fall back to the tool's own cookie:

```js
export function getPostHogDistinctId() {
  if (typeof window === "undefined") return null;

  // Prefer the loaded SDK.
  try {
    if (window.posthog?.__loaded) {
      const id = window.posthog.get_distinct_id();
      if (id) return isAnonymousDistinctId(id) ? id : null;
    }
  } catch {}

  // Fall back to PostHog's cookie before the SDK finishes loading.
  try {
    const prefix = `ph_${POSTHOG_API_KEY}_posthog=`;
    const cookie = document.cookie.split(/;\s*/).find(c => c.startsWith(prefix));
    if (!cookie) return null;
    const parsed = JSON.parse(decodeURIComponent(cookie.slice(prefix.length)));
    return typeof parsed.distinct_id === "string" && isAnonymousDistinctId(parsed.distinct_id)
      ? parsed.distinct_id : null;
  } catch { return null; }
}
```

### 2c — Merge in the webhook

The third-party tool returns your metadata in its `booking.created` (or `checkout.completed`) webhook. Fire an identity merge + a conversion event to your analytics ingestion endpoint:

```js
// Normalize the booking email the same way the app does (Step 1), or the
// booking person will split from the app-side identity for the same user.
const userId = email.trim().toLowerCase();

const events = [];
if (anonId) {
  events.push({
    event: "$identify",
    distinct_id: userId,                                  // the known person
    properties: { $anon_distinct_id: anonId, $set: { email: userId, name } },  // merge the journey
  });
}
events.push({
  event: "discovery_call_booked",
  distinct_id: userId,
  properties: { booking_id, journey_linked: Boolean(anonId) },  // track the fallback rate
});

await fetch(`${POSTHOG_HOST}/batch/`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ api_key: POSTHOG_API_KEY, batch: events }),
  signal: AbortSignal.timeout(3000),   // bound it; never hang the webhook
});
```

When no id survives (link bypassed the decorator, e.g. a booking link inside a generated email/PDF), fall back to **email-only capture** with `journey_linked: false`. You still get the conversion; you just don't get the journey for that one.

**First-touch survival caveat (PostHog specifics):** the `$anon_distinct_id` merge carries the anonymous person's *event* history, but with `person_profiles: 'identified_only'` the anonymous visitor may never have had a person profile, so their `$initial_*` first-touch props aren't guaranteed to land on the merged person. Two robust fixes: call `posthog.createPersonProfile()` client-side *before* the visitor navigates off to the third-party domain (so the profile and its `$initial_*` exist to merge into), **or** capture the first-touch values client-side and pass them through the same metadata passthrough, then re-assert them in the webhook with `$set_once` (`$set_once` never overwrites an existing value, so it's safe). Without one of these, you can get the booking joined to the journey's *events* but a blank `$initial_utm_source` on the person — verify on a real booking. ([posthog-js#1524](https://github.com/PostHog/posthog-js/issues/1524).)

## Step 3 — The guardrails (do not skip)

### Anonymity guard — fail closed

Only ever smuggle the *anonymous* id. After `identify()`, the current `distinct_id` becomes the user's email/UUID — leaking that into a third-party URL, or merging on it in the webhook, folds unrelated people together and leaks PII.

**Pick the guard that matches your identity model — the two are not interchangeable.** The `@`-check below is *only* safe when your app identifies by **email**; do not copy it into a UUID-identity app.

```js
// EMAIL-IDENTITY apps only. True only for ids safe to smuggle: reject
// email-shaped values (an identified email) and cap length.
export function isAnonymousDistinctId(id) {
  return id.length > 0 && id.length <= 100 && !id.includes("@");
}
```

**If the app identifies by UUID, not email**, the `@` check is useless — an identified UUID would pass it and leak. Instead test that the current `distinct_id` still equals the `device_id` (calling `identify()` changes `distinct_id` but leaves `device_id`), and **fail closed** when `device_id` is unreadable:

```js
// UUID-identity variant: only anonymous when distinct_id still == device_id.
function isAnonymous(posthog) {
  const did = posthog.get_distinct_id?.();
  const dev = posthog.get_property?.("$device_id");
  if (!did || !dev) return false;   // ambiguous → treat as identified, send nothing
  return did === dev;
}
```

The rule in one line: **when identity is ambiguous, send nothing.** A missing journey is a data gap; a wrong merge is corruption.

### First-touch data quality — the cheapest big win

Redirects overwrite the true first touch, inflating "Direct"/"Referral" and hiding real acquisition. Exclude these from referrer/channel classification (usually a *settings* change in the analytics tool, not code):

- **OAuth / checkout redirects:** `accounts.google.com`, `login.microsoftonline.com`, `login.live.com`, `checkout.stripe.com`
- **Self / subdomain referrals:** `yourdomain.com`, `app.yourdomain.com`, `auth.yourdomain.com`
- **Dev/internal traffic:** `localhost`, `127.0.0.1`, test accounts

This is the **highest-trust-per-effort** fix in the whole runbook — no deploy, immediate accuracy gain. Do it first.

### Cross-subdomain stitching

Marketing site → app on a subdomain must share **one analytics project** and a **cross-subdomain cookie** (PostHog's `cross_subdomain_cookie` default handles `yourdomain.com` → `app.yourdomain.com`). Verify the journey survives the handoff, or every signup looks like it started at the app.

**Expect near-zero numbers until the stitch is verified in prod — don't panic.** (Production note from Tessa Kriesel.) Before the cross-subdomain stitch is confirmed live, first-party attribution reads *basically nothing* — journeys break at the handoff and everything looks like direct. It flips from ~0 to real numbers the week the stitch actually ships. Two things get you through that window:

- **A campaign-window heuristic fallback.** When a signup has no linked journey, attribute it to the campaign/channel that was live during its signup window — but only when **date + landing page + active UTMs uniquely narrow it to one source**. With overlapping campaigns, evergreen ads, email sends, branded/direct demand, or a shared landing page, the window can't isolate the cause — mark those `unknown` / low-confidence rather than falsely crediting whatever was live. Used narrowly, it's a real signal while the stitch stabilizes and beats a blank; used bluntly, it manufactures false attribution.
- **Backfill only the pre-stitch records that are actually missing a source.** Many pre-stitch signups already have verified or self-reported attribution — **never overwrite a higher-confidence source with the heuristic.** Backfill only the blanks (campaign-window or self-reported), tag them as such, and keep the heuristic-backfilled history visually separate from verified trends so you don't read a cliff on launch day as a real shift.

Mark these fallback-attributed conversions with a lower-confidence `basis` (see Step 5) so you never confuse a heuristic guess with a verified journey.

### Harden the webhook

- Verify the provider's **signature** (`SAVVYCAL_WEBHOOK_SECRET` etc.).
- **Validate** the smuggled id (string, ≤100 chars, no `@`) before merging.
- Run the analytics call **after** any business-critical work, bounded by a timeout, **non-fatal** on failure.
- **Log the booking id, never the email.**

## Step 4 — Report

- **Config check:** many tools default to *last-touch* (PostHog's Marketing Analytics scene does). First-party attribution wants first-touch — build insights on `$initial_*` explicitly, or switch the default.
- **The payoff insight:** conversion event broken down by `$initial_utm_source` / `$initial_referring_domain` — "where does every signup/booking come from."
- **Channel → revenue:** conversion event by channel, joined to revenue/MRR person properties. Note: some tools compute revenue props *at ingest* (person-on-events), so historical events may read 0 — use the persons table for current MRR, or tier by plan.
- **Track your own coverage:** the `journey_linked: false` rate tells you how many conversions bypassed the stitch. Watch it after launch.
- **Store the full touch path, not just `$initial_*`.** (Refinement from Tessa Kriesel.) First-touch alone lets you break conversions down by *first* channel — but it can't run the multi-touch models from the interpretation track (SKILL.md §2: position-based, linear, time-decay). If you also persist the **ordered sequence of touches** per person (channel + timestamp for each, e.g. an events-table query or a `touch_path` array on the person), the build track *feeds* the interpretation track: you can now score the same journey six ways on your own data instead of only reading about the models. This is what makes Pillar A and Pillar B shake hands — capture first-touch to ship, capture the full path to model.

## Step 5 — The last mile: get attribution into the CRM

(This whole step is a production refinement from Tessa Kriesel — it's the thing that turned first-party attribution from a dashboard into an operating signal.)

A channel breakdown living in your analytics tool is a *report*. The thing sales and lifecycle actually act on is **attribution written onto the record in the CRM**, per account. Sync it out:

- **A `source` field, plus `source_confidence` and `source_basis`.** Don't write a bare channel — write the channel *and how you know it*. `basis` is the **evidence type**: `journey_linked` (verified stitch), `self_reported` (survey), or `campaign_window` (the heuristic fallback above). `confidence` is computed from **evidence quality, not just the basis** — a journey_linked touch with clean UTMs is high, the same touch with dirty/missing UTMs is lower, and a *specific* self-report can be high while a vague one is low. Sales treats a high-confidence source very differently from a low-confidence guess — give them both fields or they'll distrust the whole thing.
- **A Paid-vs-Organic read off the medium.** The single most-used cut in practice: mark a touch **`paid`** only from explicit paid mediums (`cpc`, `ppc`, `paid-social`, `display`, `paid`), and classify the rest into a small, configurable taxonomy rather than a blunt "organic" — `owned` (email, push, SMS — though a sponsored newsletter is *paid*), `earned` (organic search/social, referral — but a partner/affiliate referral is closer to paid), `direct` (no medium — unknown, not organic), `unknown`. The fast operational question a rep or nurture flow needs is really **paid vs non-paid** (did this account cost acquisition dollars) — get that boundary right and keep the finer buckets configurable.
- **Roll up to the account, not just the contact** (B2B) — see the account-rollup note below and in `by-business-type.md`.
- **Hand the record off to revops.** Once the source/confidence/basis + paid/organic live on the account, how pipeline and lifecycle *use* them (routing, lead scoring, nurture branching, revenue attribution reporting) is the **revops** skill's job. This runbook's job is to get a trustworthy, labeled source onto the record.

**Account rollup (B2B).** One org is several people signing up with mixed work *and* personal emails, so person-level attribution scatters the story across records. Roll each person's source up to the **account** and attribute at the account level — that's where the signal has to land to be useful to a salesperson working the whole buying committee. Match on email domain, **but exclude free-mail domains** (`gmail.com`, `yahoo.com`, `outlook.com`, …) — those can't identify a company, so a domain match would collapse unrelated people into one bogus account. For personal-email signups, fall back to enrichment, your CRM's contact→account link, or manual matching.

## Verification checklist

- Click a booking CTA → URL shows `metadata[<id_param>]=<anon-uuid>`.
- In console: `posthog.identify('test@x.com')` → click again → the param must **NOT** appear (guard works). `posthog.reset()` after.
- Hand-POST a webhook `/batch/` payload → expect `{"status":"Ok"}`, person appears merged.
- Post-ship: first real webhook log shows `journey_linked: true`.
- Confirm first-touch survives cross-subdomain: start on marketing site, sign up in app, check the person carries the original `$initial_utm_source`.

## Adapting to other stacks

| Piece | PostHog (worked example) | Generalizes to |
|---|---|---|
| Anonymous id | `distinct_id` / `$device_id` | Segment `anonymousId`, Amplitude `deviceId`, GA4 client_id |
| Merge call | `$identify` + `$anon_distinct_id` | Segment `identify` (known `userId`, same `anonymousId`) + `alias` where needed; Amplitude `setUserId` on the session that still holds the anonymous `deviceId` (the stitch is deviceId↔userId — Amplitude's Identify API only sets user *properties*, it does not merge); GA4 `user_id` on the same `client_id` |
| Ingestion | `/batch/` | Segment HTTP API, Amplitude HTTP v2, GA4 Measurement Protocol |
| Third-party passthrough | SavvyCal `metadata[...]` | Calendly UTM/`salesforce_uuid`, Cal.com metadata, Stripe `client_reference_id`/metadata |
| First-touch props | `$initial_*` | Segment/Amplitude first-touch, GA4 first_user_* dimensions |

The shape never changes: **grab the anonymous id → carry it across the boundary → merge on the far side → break the conversion down by first-touch.**


---

# references/measurement-paradigms.md

# Measurement Paradigms — MTA vs. MMM vs. Incrementality

Attribution *models* (see `attribution-models.md`) split credit *within* your tracked data. They can't tell you what would have happened anyway. That's what these three paradigms are for — increasingly rigorous, increasingly expensive ways to get closer to causality. Use this reference to help a user pick, and to explain how a test *reads* (not how to run the statistics).

## The three, compared

| | **MTA** (multi-touch) | **MMM** (media mix modeling) | **Incrementality** (experiments) |
|---|---|---|---|
| **Approach** | Bottom-up: stitch user-level touches, apply a model | Top-down: regress outcomes vs. spend/factors over time | Controlled: withhold exposure from a group, measure the difference |
| **Answers** | "Which touchpoints are on converting journeys?" | "What's each channel's aggregate contribution?" | "Did this channel *cause* lift I wouldn't have gotten?" |
| **Granularity** | Per user, per touch | Per channel, per week | Per test (one channel/tactic at a time) |
| **Data needed** | Clean cross-device user-level tracking | 2–3 yrs weekly data + spend variation | Ability to withhold + enough volume for significance |
| **Reacts** | Real-time | Slowly (weeks/quarters) | Per test cycle |
| **Handles offline/brand** | No | Yes | Yes (if you can split exposure) |
| **Privacy-durable** | Weak (cookie/ID loss) | Strong (aggregate) | Strong (aggregate) |
| **Cost/effort** | Low–medium | High | Medium–high |

## MTA — multi-touch attribution

**What it is:** the user-level approach most marketers mean by "attribution" — join a person's touches, apply first/linear/position/data-driven credit.

**Where it shines:** day-to-day, tactical decisions. "Is this campaign showing up on converting journeys?" Fast, granular, cheap if your tracking exists.

**Why it's structurally weakening:** MTA depends on tracking one person across touches and devices, and that data keeps eroding — Safari/Firefox ITP-style cookie limits, iOS ATT, browser consent gating, ad blockers, and ordinary cross-device behavior (research on mobile, buy on desktop). (Chrome's third-party-cookie deprecation was announced, then walked back, so "cookies are going away" is no longer the clean story — but everything else on that list already limits user-level tracking today.) MTA doesn't announce the gap: it silently under-measures anything it can't follow (dumping it into direct) and over-measures what it *can* see. So treat MTA as **incomplete and directionally biased** — not a clean lower bound (its retargeting/branded numbers are often *over*-stated) — and never the sole basis for a big reallocation.

**Use it for:** ongoing optimization and trend-watching — never as the sole basis for a big budget reallocation.

## MMM — media/marketing mix modeling

**What it is:** a top-down statistical model (historically regression; modern open-source options like Meta's Robyn or Google's Meridian) that explains an outcome (revenue, signups) as a function of spend per channel plus controls (seasonality, promotions, price, macro). It never looks at individuals — it's all aggregate time-series, which is exactly why privacy changes don't touch it.

**What it uniquely gives you:**
- **Offline + brand + hard-to-track channels** — TV, podcasts, OOH, PR, organic — because it works on aggregate spend and outcomes, not clicks.
- **Diminishing returns / saturation curves** — where the next dollar in a channel stops paying off.
- **A portfolio view** — how the whole mix drives the outcome, not credit for one journey.

**What it costs and where it's weak:**
- Needs **2–3 years of weekly data** and **real variation in spend** — if you always spend the same on Meta, the model can't learn Meta's effect. You sometimes have to deliberately vary budgets to feed it.
- **Correlational and slow** — it sees what moved together historically; it reacts in quarters, not days. It can't tell you what to do with tomorrow's campaign.
- **Sensitive to specification** — garbage controls, garbage coefficients. It's a real modeling exercise, not a dashboard toggle.

**Use it for:** annual/quarterly budget allocation across a material, multi-channel (esp. offline-inclusive) spend. Validate its coefficients with incrementality tests — MMM says "Meta contributed X"; a holdout proves whether that's causal.

## Incrementality — the experiments

**What it is:** the only paradigm that measures *causality* directly. Split your audience into an **exposed** group and a **withheld/control** group; the difference in outcomes is the **incremental lift** — conversions you got *because of* the channel, not ones that would have happened anyway.

**Common designs:**
- **Geo holdout / geo-lift** — run the channel in some regions, hold it out of comparable ones; compare outcomes. The workhorse for channels you can't split at the user level. *(Meta's GeoLift, Google's geo experiments.)*
- **PSA tests** — the control group is shown a *public-service ad* in your ad's place, so both groups are equally targeted and "ad-exposed"; the only difference is whether they saw *your* ad. Isolates ad effect from audience-quality bias (the exposed group isn't just "people the algorithm judged likely to convert").
- **Ghost ads** — the control group is *held out of the auction* but the platform logs the ad that *would* have served them (no placeholder is shown); you compare converters among the would-have-been-exposed vs. actually-exposed. Cleaner and cheaper than PSAs (no wasted PSA spend), and the modern default where the platform supports it.
- **Intent-to-treat / on-off (pulse) tests** — turn a channel fully off for a defined window, watch what happens to total conversions. Crude but revealing, especially for "is branded search paid cannibalizing organic?"
- **Holdout audiences** — withhold a random % from a retargeting or email program; the delta is the program's true lift.

### How to *read* a test (not run the stats)

You don't need to compute significance by hand, but you must read a result honestly:

1. **Lift = exposed rate − control rate.** If exposed geos converted at 4.2% and control at 3.6%, incremental lift is ~0.6pp — the rest of that 4.2% would have converted anyway. This is why last-click ROAS is almost always *overstated*: it counts the whole 4.2%.
2. **Check the confidence interval / significance.** "5% lift, but the interval spans −2% to +12%" means you learned nothing — the test was underpowered. Insist on enough volume/duration before believing a point estimate.
3. **Watch for contamination.** Control users who were reached anyway (cross-device, spillover between geos) shrink the measured gap. A "no lift" result can be a leaky test, not a dead channel.
4. **Translate to a decision.** Incremental CPA = spend ÷ *incremental* conversions (not total). This is the number that should drive budget — and it's usually worse than the platform's reported CPA, which is the point.

**Use it for:** the highest-stakes questions and the tiebreakers — "does retargeting actually do anything?", "is branded-search paid just buying clicks we'd get free?", "which of our two biggest channels is really driving growth?" You can only test a few things at a time, so spend those tests on the decisions that matter most.

## Putting them together (the mature stack)

They're layers, not competitors:

- **MTA** for daily/weekly tactical optimization and trend-watching — cheap, granular, directional.
- **MMM** for quarterly/annual portfolio allocation across the full mix including offline — durable, holistic.
- **Incrementality** as the **calibration and tiebreaker** — the ground-truth that keeps MTA and MMM honest, run on your biggest bets.

**Scale to the user:** most SMBs need good UTMs + last-non-direct + a self-reported survey + the occasional on/off test — not an MMM. Bring MMM in when offline/brand spend is material and MTA visibly can't see it. Bring in formal incrementality when a single channel's budget is big enough that being wrong about it is expensive. Match the rigor to the size of the decision.
