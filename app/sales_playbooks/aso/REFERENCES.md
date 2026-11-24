# Reference files for the `aso` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/apple-specs.md

# Apple App Store — Official Specs & Guidelines

All data from developer.apple.com as of March 2026.

## Character Limits

| Field                   | Limit            | Indexed for Search?      | Notes                                                    |
| ----------------------- | ---------------- | ------------------------ | -------------------------------------------------------- |
| App Name                | 30 chars (min 2) | Yes                      | Must be unique; no trademarks, competitor names, pricing |
| Subtitle                | 30 chars         | Yes                      | No unverifiable claims                                   |
| Keywords                | 100 bytes        | Yes (hidden)             | Commas, no spaces between terms                          |
| Description             | 4,000 chars      | **No**                   | Plain text only, no HTML                                 |
| Promotional Text        | 170 chars        | **No** (Apple confirmed) | Updatable without new version                            |
| What's New              | 4,000 chars      | No                       | Required for all versions after first                    |
| IAP Name                | 35 chars         | Yes                      | Appears in search                                        |
| IAP Description         | 55 chars         | No                       |                                                          |
| In-App Event Name       | 30 chars         | Yes                      | Title case required                                      |
| In-App Event Short Desc | 50 chars         | Yes                      | Sentence case                                            |
| In-App Event Long Desc  | 120 chars        | No                       | Sentence case                                            |

**Keywords field is 100 bytes, not 100 characters.** Non-Latin scripts (Arabic,
Chinese, Japanese, Korean) use 2-3 bytes per character, reducing effective
keyword count significantly.

## Screenshot Specs

| Device           | Required?     | Count | Dimensions (portrait)      |
| ---------------- | ------------- | ----- | -------------------------- |
| 6.9" iPhone      | **Required**  | 1-10  | 1260 x 2736                |
| 13" iPad         | **Required**  | 1-10  | 2064 x 2752                |
| Mac              | If applicable | 1-10  | Up to 2880 x 1800 (16:10)  |
| Apple Watch      | If applicable | 1-10  | Varies by model            |
| Apple TV         | If applicable | 1-10  | 1920 x 1080 or 3840 x 2160 |
| Apple Vision Pro | If applicable | 1-10  | 3840 x 2160                |

- Formats: JPEG, PNG
- Apple auto-scales from required base sizes to smaller devices

## App Preview Video Specs

- **Count:** Up to 3 per app
- **Duration:** 15-30 seconds
- **Max file size:** 500 MB
- **Codecs:** H.264 (10-12 Mbps, up to 30fps) or ProRes 422 HQ
- **Audio:** Stereo, 256 kbps AAC or PCM, 44.1/48 kHz
- **Formats:** .mov, .m4v, .mp4
- **Behavior:** Autoplays muted on product page (iOS 11+)

## Custom Product Pages (CPPs)

- **Max:** 70 additional pages (plus 1 default)
- **Customizable:** Screenshots, promotional text, app previews, deep links (iOS 18+)
- **Keywords:** Each keyword combo must be unique to a single CPP
- **Review:** Submitted to App Review independently of app updates
- **Organic search:** CPPs appear in organic search results since July 2025
- **Performance:** +2.5 percentage points higher conversion on average vs default

## Product Page Optimization (A/B Testing)

- **Treatments:** Up to 3 vs original
- **Testable:** App icons, screenshots, app preview videos
- **NOT testable:** Title, subtitle, description, keywords
- **Concurrent tests:** 1 per app
- **Max duration:** 90 days
- **Icon constraint:** All icon variants must be in the published app binary
- **Confidence:** Apple recommends 90% threshold (Bayesian method)
- **Cannot modify** a test once started

## In-App Events

- **Max approved:** 15 in App Store Connect at once
- **Max published:** 10 on App Store simultaneously
- **Max duration:** 31 days per event
- **Pre-event promotion:** Up to 14 days before start
- **Badge types:** Challenge, Competition, Live Event, Major Update, New Season, Premiere, Special Event

**Event card image:** 16:9, min 1920x1080, max 3840x2160
**Event details image:** 9:16, min 1080x1920, max 2160x3840

**Not suitable:** Repetitive daily tasks, price promotions without new content, general awareness campaigns.

## Ratings & Reviews

- **SKStoreReviewController:** Max 3 prompts per 365-day period
- System controls display frequency (may show fewer than 3)
- Do not use custom buttons to request reviews
- Developers can respond to all reviews in App Store Connect
- Summary rating is territory-specific

## Metadata Rejection Triggers (App Review Guidelines)

| Guideline | Rejection Trigger                                                         |
| --------- | ------------------------------------------------------------------------- |
| 2.3.1     | Hidden features, misleading marketing, false pricing                      |
| 2.3.2     | Not disclosing IAPs in description/screenshots                            |
| 2.3.3     | Screenshots that don't show app in use (only splash/login)                |
| 2.3.4     | Preview videos using non-app content                                      |
| 2.3.5     | Wrong category selected                                                   |
| 2.3.7     | Keyword stuffing: trademarks, competitor names, pricing, irrelevant terms |
| 2.3.8     | Metadata not appropriate for all audiences (must be 4+ rated)             |
| 2.3.10    | Other platform names/imagery (Android, etc.) in metadata                  |
| 2.3.12    | Generic What's New for significant changes                                |
| 2.3.13    | Inaccurate in-app event metadata                                          |

Sources: developer.apple.com/app-store/product-page/,
developer.apple.com/app-store/search/,
developer.apple.com/app-store/review/guidelines/


---

# references/benchmarks.md

# ASO Benchmarks & Conversion Data

Industry data from AppTweak, SplitMetrics, Sensor Tower, and others. Updated March 2026.

## Conversion Rate Benchmarks by Category

**Average CVR (page view to install):**

- iOS overall: **25.0%**
- Google Play overall: **27.3%**

| Category          | iOS CVR        | Google Play CVR |
| ----------------- | -------------- | --------------- |
| Navigation        | 115%\*         | --              |
| Auto & Vehicles   | --             | 70.5%           |
| Business          | 66.7%          | --              |
| Music (Games)     | --             | 45.0%           |
| Utilities & Tools | --             | 36.8%           |
| Shopping          | --             | 27.7%           |
| Health & Fitness  | --             | 23.2%           |
| Finance           | --             | 19.7%           |
| Food & Drink      | --             | 13.1%           |
| Games (Board)     | 1.2%           | 7.3%            |
| Games (overall)   | 3-5% realistic | --              |

\*Above 100% = some users install from search without visiting product page.

Source: AppTweak 2025 Benchmarks Report (H1 2024 data, US market)

## Rating Impact on Conversion

| Rating Change              | Conversion Impact                       |
| -------------------------- | --------------------------------------- |
| 3.0 to 4.0 stars           | **+89%**                                |
| 4.0 to 4.5 stars           | **+20-30%**                             |
| 4.3 to 4.6 stars           | **+22-28%** (Finance, Health)           |
| 0.4-star gap vs competitor | **~25% lost installs** from same search |
| 3-star vs 5-star app       | **50% fewer conversions** for 3-star    |

**Critical thresholds:**

- **4.0 stars** = minimum for Apple featuring, user trust, conversion viability
- **4.5+ stars** = optimal zone. Sweet spot: 4.1-4.9
- **5.0 stars** can look suspicious to users
- **Below 3.5** = sharp visibility drop on both stores
- **79% of users** check ratings before downloading
- **50% reject** apps below 3 stars

Sources: AppFollow, MobileAction, Sensor Tower, Troof.ai

## Preview Video Impact

**iOS:** +20-40% conversion lift (video autoplays on product page)
**Google Play:** Minimal lift (only ~6% of visitors tap to play)

- Autoplay introduced in iOS 11 caused **+47% conversion jump**
- Users who watch video are **2x more likely to install**
- Average watch time: **4-6.5 seconds** (first 5 seconds are critical)
- 50%+ of viewers watch to the end

**Takeaway:** Video is high-ROI on iOS, low-ROI on Google Play.

Sources: StoreMaven, SplitMetrics, Leanplum

## Screenshot Impact

- **90% of users** do not scroll past the 3rd screenshot
- Average scroll rate: only **17%**
- Users spend **6-10 seconds** scanning before deciding
- **First screenshot decides everything**
- Well-designed screenshots lift conversion **20-35%**
- A/B test winners see **10-25% improvement**
- **Optimal count:** 4-5 for utility apps, 5-6 for complex apps
- More than 6: diminishing returns, can cause decision paralysis
- Top 200 apps update screenshots **2-4 times/year**
- Top Google Play games update visuals **up to 8x/year**
- **57% of top games** A/B tested screenshots at least 2x in 2024

Sources: AppTweak, ASOMobile, Sensor Tower

## Custom Product Pages (Apple CPPs)

- Average conversion lift: **+5.9% for apps**, **+3.5% for games**
- Best cases: up to **+8.6%**
- Organic referral: **+2.5 percentage points** (156% lift vs 1.6% baseline)
- Apple Ads CPP CVR: **55.8% in 2024** (up from 42.1% in 2023)
- **Only 31% of apps** and **26% of games** use CPPs (low adoption = opportunity)
- Screenshot reordering alone produced **+16.6% installs** in one case

Sources: AppTweak, SplitMetrics, MobileAction

## Custom Store Listings (Google Play CSLs)

- Up to **50 custom versions** per app
- Case study (Lockwood/Avakin Life): **+57% CVR** over 2 months
- Can target inactive/churned users (28+ days no activity)

Source: Phiture, MobileAction

## In-App Events (Apple)

- **55% of top 200 apps** use them regularly
- +**15-20% more impressions** from editorial/browse placements
- One case: **+124% surge** in total impressions
- One case: **+50% impressions AND first-time downloads**
- Search CVR uptick: **+10.3%**
- Re-downloads increase: **+15.5%**
- **Boost is short-lived** -- KPIs drop to baseline when event ends
- Optimal: **2-4 active events per month**

Sources: Phiture, AppTweak, Appalize

## Promotional Content (Google Play)

- Apps with featuring see **2x explore acquisitions** (official Google)
- +2% 28-day active users and +4% revenue on average

Source: Google Play Console documentation

## A/B Test Impact Thresholds

| Improvement | Classification                     |
| ----------- | ---------------------------------- |
| >10%        | Strong winner -- apply immediately |
| 5-10%       | Meaningful winner                  |
| 2-5%        | Marginal winner                    |
| <2%         | Noise -- not significant           |

Source: SplitMetrics, MobileAction


---

# references/google-play-specs.md

# Google Play Store — Official Specs & Guidelines

All data from support.google.com and developer.android.com as of March 2026.

## Character Limits

| Field             | Limit       | Indexed?               | Notes                                 |
| ----------------- | ----------- | ---------------------- | ------------------------------------- |
| App Title         | 30 chars    | Yes (strongest signal) | Reduced from 50 in Sept 2021          |
| Short Description | 80 chars    | Yes                    | Visible without expanding             |
| Full Description  | 4,000 chars | **Yes (heavily)**      | Google NLP indexes entire text        |
| Developer Name    | 64 chars    | Partial                | Same emoji/caps restrictions as title |

## Prohibited in Metadata (enforced since Sept 2021)

**Title, Icon, Developer Name:**

- Emojis, emoticons, repeated special characters
- ALL CAPS (unless registered brand)
- Performance claims: "top," "best," "#1," "free," "no ads"
- Misleading store performance or endorsement
- Calls-to-action: "update now," "download now"

**Short Description:**

- Same performance claims as title
- Calls-to-action
- Unattributed testimonials

**Screenshots, Feature Graphic, Video:**

- Time-sensitive taglines
- Calls-to-action ("Download now," "Play now")
- Must authentically showcase app functionality

## Screenshot Specs

| Device     | Min   | Max   | Aspect Ratio | Min Resolution | Max Long Edge |
| ---------- | ----- | ----- | ------------ | -------------- | ------------- |
| Phone      | **2** | **8** | 9:16 or 16:9 | 320px any side | 3,840px       |
| 7" Tablet  | 4     | 8     | 9:16 or 16:9 | 1,080px short  | 7,680px       |
| 10" Tablet | 4     | 8     | 9:16 or 16:9 | 1,080px short  | 7,680px       |
| Chromebook | 4     | 8     | 9:16 or 16:9 | 1,080px short  | 7,680px       |
| Wear OS    | 1     | 8     | **1:1**      | 384x384        | 3,840px       |
| Android TV | 1     | 8     | **16:9**     | 1,920x1,080    | 3,840px       |

- **Recommended phone size:** 1080x1920 (portrait)
- **Format:** JPEG or 24-bit PNG (no alpha)
- **Max file size:** 8 MB each

**Note:** Google Play max is 8 screenshots per device, not 10 like Apple.

## Feature Graphic

- **Dimensions:** 1024 x 500 px (exact, required)
- **Format:** JPEG or 24-bit PNG (no alpha)
- Displayed at top of listing and in featured placements

## App Icon

- **Dimensions:** 512 x 512 px
- **Format:** 32-bit PNG (with alpha)
- **Max file size:** 1,024 KB
- **Shape:** Full square (Google applies 30% corner radius automatically)
- **Prohibited:** Ranking claims, download counts, deal text, emoji

## Preview Video

- **Format:** YouTube URL (public or unlisted)
- **Duration:** 30 seconds to 2 minutes recommended
- No ads, no monetization, must be embeddable, not age-restricted
- **Does NOT autoplay** (only ~6% of visitors tap to play)

## Store Listing Experiments (A/B Testing)

- **Variants:** Up to 3 per experiment (plus control)
- **Testable:** Icon, feature graphic, screenshots, video, short description, full description
- **Concurrent:** Cannot run more than 1 default graphics experiment simultaneously
- **Audience:** Signed-in Google Play users only
- **Metrics:** First-time installers + retained first-time installers (1-day retention)
- **Duration:** Run at least 7 days (weekday/weekend variance)
- **Localized:** Test across up to 5 languages simultaneously

## Custom Store Listings

- **Max:** 50 per app (100 for Play partners)
- **Customizable:** Title, short/full description, icon, screenshots, feature graphic, video
- **Targeting:** Country/region, pre-registration, install state, Google Ads campaigns, inactive/churned users (28+ days)
- **2025 addition:** Gemini AI auto-generates text for CSLs in Play Console

## Promotional Content (LiveOps)

| Type              | Description                    | Duration             |
| ----------------- | ------------------------------ | -------------------- |
| Offers            | Discounts, free items, bundles | Up to 28 days        |
| Events            | Time-limited in-app events     | Must have time limit |
| Major Update      | Significant new features       | Max 1 week           |
| Crossover (games) | Cross-game/IP collaboration    | Varies               |

- Submit **4+ days** before start (standard review)
- Submit **14+ days** before for featuring requests
- **Impact:** "Over twice as many explore acquisitions during featuring" (official Google)

## Android Vitals — Ranking Thresholds

Apps exceeding these thresholds get **reduced visibility** in search and recommendations.

| Metric                       | Overall Threshold | Per-Device Threshold |
| ---------------------------- | ----------------- | -------------------- |
| User-Perceived Crash Rate    | **1.09%**         | 8%                   |
| User-Perceived ANR Rate      | **0.47%**         | 8%                   |
| Excessive Partial Wake Locks | 5%                | N/A                  |

**Consequences:** Reduced search visibility, warning labels on listing, quality alerts to users before install.
**Recovery:** Google checks daily using 28-day rolling average.

## Search Ranking — Official Factors

Google confirms these affect ranking:

1. **Metadata relevance** — Title carries most weight. NLP scans title + short desc + full desc.
2. **App quality** — Android Vitals (crash/ANR rates)
3. **Ratings and reviews** — Star rating + review text. 85% of featured apps have 4.0+
4. **Install volume and velocity** — Total installs + daily/weekly frequency
5. **Engagement and retention** — Session frequency, duration, retention rates
6. **Update frequency** — Regular updates signal active maintenance
7. **Localization** — Regional keyword/visual adaptation. 59% of US apps localize titles.

Sources: support.google.com/googleplay/android-developer/answer/4448378,
support.google.com/googleplay/android-developer/answer/9898842,
developer.android.com/topic/performance/vitals


---

# references/report-template.md

# ASO Audit Report Template

Use this structure for all ASO audit reports.

---

## Header

```
# ASO Audit: {App Name}
**Store:** {Apple App Store / Google Play}
**URL:** {listing URL}
**Audit date:** {date}
**Brand tier:** {Dominant / Established / Challenger} — {one-line justification}
**Overall Score:** {score}/100 (Grade: {A/B/C/D/F})
```

---

## Score Card

```
| Dimension | Score | Grade | Key Issue |
|-----------|-------|-------|-----------|
| Title & Subtitle | X/10 | {grade} | {one-line summary} |
| Description | X/10 | {grade} | {one-line summary} |
| Visual Assets | X/10 | {grade} | {one-line summary} |
| Ratings & Reviews | X/10 | {grade} | {one-line summary} |
| Metadata & Freshness | X/10 | {grade} | {one-line summary} |
| Conversion Signals | X/10 | {grade} | {one-line summary} |
| **OVERALL** | **{weighted}/100** | **{grade}** | |
```

Grade scale per dimension: 9-10 = A, 7-8 = B, 5-6 = C, 3-4 = D, 1-2 = F

---

## Top 3 Quick Wins

Highest-impact changes that take under 1 hour:

```
### 1. {Action verb} — {specific change}
**Impact:** {High/Medium} | **Effort:** {<15 min / <30 min / <1 hour}
**Current:** {what it is now}
**Recommended:** {exact replacement, with character count}
**Why:** {one sentence explaining the impact}

### 2. ...
### 3. ...
```

---

## Detailed Findings

### Title & Subtitle Analysis

```
**Current title:** "{title}" ({X}/30 chars used)
**Current subtitle/short desc:** "{subtitle}" ({X}/30 or /80 chars used)

**Issues found:**
- {issue 1}
- {issue 2}

**Recommended title:** "{new title}" ({X}/30 chars) — {rationale}
**Recommended subtitle:** "{new subtitle}" ({X}/30 or /80 chars) — {rationale}
```

### Description Analysis

```
**First 3 lines (above fold):**
> {quoted text}

**Issues found:**
- {issue 1}
- {issue 2}

**Keyword density (Google Play only):** {X}% — target: 2-3%
**Top keywords found:** {keyword1} (Xn), {keyword2} (Xn), ...
**Missing high-value keywords:** {keyword1}, {keyword2}, ...

**Recommended first 3 lines:**
> {rewritten text}
```

### Visual Assets Analysis

```
**Screenshots:** {count} ({store} shows first {3/all} in search)
**Preview video:** {Yes/No}
**Icon assessment:** {description}
**Feature graphic (Google Play):** {Yes/No}

**Screenshot audit:**
1. {screenshot 1 description} — {pass/issue}
2. {screenshot 2 description} — {pass/issue}
...

**Recommendations:**
- {specific visual change 1}
- {specific visual change 2}
```

### Ratings & Reviews Analysis

```
**Average rating:** {X.X} stars ({count} ratings)
**Recent review sentiment:** {Positive/Mixed/Negative}
**Common complaints:** {theme1}, {theme2}
**Developer responses:** {Yes, active / Sporadic / None}

**Recommendations:**
- {specific action 1}
- {specific action 2}
```

### Metadata & Freshness

```
**Last updated:** {date} ({X days/months ago})
**Localizations:** {count} languages
**Category:** {current category}
**In-app events/LiveOps:** {Yes/No}

**Recommendations:**
- {specific action 1}
- {specific action 2}
```

### Conversion Signals

```
**Price model:** {Free / Freemium / Paid}
**IAP count:** {count}
**Downloads (Google Play):** {range}
**Social proof visible:** {awards, press, badges — or "none"}

**Recommendations:**
- {specific action 1}
- {specific action 2}
```

---

## Keyword Suggestions

```
| Keyword | Rationale | Where to Place | Priority |
|---------|-----------|----------------|----------|
| {keyword} | {why this keyword} | {title/subtitle/description/keyword field} | {High/Med/Low} |
| ... | ... | ... | ... |
```

Note: Without paid ASO tools, exact search volume is unavailable. These
suggestions are based on category analysis, competitor metadata, and semantic
relevance. Validate with AppTweak, Sensor Tower, or MobileAction for volume data.

---

## Competitor Comparison (if applicable)

```
| Metric | {Your App} | {Competitor 1} | {Competitor 2} |
|--------|-----------|----------------|----------------|
| Title keywords | ... | ... | ... |
| Rating | ... | ... | ... |
| Screenshots | ... | ... | ... |
| Video | ... | ... | ... |
| Description keywords | ... | ... | ... |
| Last updated | ... | ... | ... |
| Overall ASO score | ... | ... | ... |
```

---

## Priority Action Plan

Ordered by impact (high to low), grouped by effort:

```
### Do This Week (Quick Wins)
1. {action} — {expected impact}
2. {action} — {expected impact}

### Do This Month (Medium Effort)
3. {action} — {expected impact}
4. {action} — {expected impact}

### Plan for Next Quarter (High Effort)
5. {action} — {expected impact}
6. {action} — {expected impact}
```

---

## Limitations

Always include this section:

> **What this audit cannot measure without paid ASO tools:**
>
> - Exact keyword search volume and difficulty scores
> - Historical keyword ranking positions
> - Download and revenue estimates
> - Apple keyword field contents (hidden from public view)
> - Install conversion rate data (only available to app owner in console)
> - A/B test results from previous experiments
>
> For these data points, consider using AppTweak ($69/mo), Sensor Tower, or
> MobileAction ($69/mo).


---

# references/scoring-criteria.md

# ASO Scoring Criteria

Score each dimension 0-10 using the rubrics below.
**Apply brand maturity tier adjustments** from Phase 1.5 of the main skill.

---

## Brand Maturity Adjustments (apply to all dimensions)

Before scoring, determine the app's tier: **Dominant**, **Established**, or **Challenger**.

**Dominant apps (Instagram, Uber, Spotify, WhatsApp, Netflix):**

- Brand-only titles score 8+ (the brand IS the keyword)
- Lifestyle/brand screenshots score same as captioned UI screenshots
- Generic What's New at weekly+ cadence scores 8+
- Missing in-app events for utility apps is not a penalty
- Description scored on conversion quality only, not keyword presence
- Localization scored relative to actual market footprint
- Missing preview video is acceptable if brand awareness is near-universal

**Established apps (Duolingo, Strava, Notion, Calm, Cash App):**

- Brand-first titles with 1-2 keywords score normally
- Strategic description/visual choices get benefit of the doubt
- All other dimensions scored normally

**Challenger apps (most apps):**

- Scored strictly against textbook ASO — every character and feature matters

**Key principle:** Before docking points, ask: "Is this a mistake or a data-informed
choice by a team with more information than I have?"

---

## 1. Title & Subtitle (Weight: 20%)

**Challenger rubric:**

| Score | Criteria                                                                                                                                                                |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 9-10  | Brand + high-value keyword in title, complementary keywords in subtitle, no word repetition across fields, near max character usage, instantly communicates app purpose |
| 7-8   | Good keyword presence, minor character waste (5+ unused chars), clear purpose                                                                                           |
| 5-6   | Has keywords but poor placement, some repetition between fields, purpose somewhat clear                                                                                 |
| 3-4   | Title is brand-only or generic, subtitle missing or weak, poor character usage                                                                                          |
| 1-2   | No keyword strategy, title doesn't communicate purpose, major character waste                                                                                           |
| 0     | Cannot assess (data unavailable)                                                                                                                                        |

**Dominant/Established adjustment:** Brand-only titles (e.g., "Instagram") are
valid if the brand has high search volume. Score 8+ for Dominant apps where
brand recognition eliminates the need for generic keywords. Evaluate whether
unused characters represent waste or intentional simplicity.

**Check for:**

- Characters used vs limit (title: 30, subtitle/short desc: 30/80). "Near max" = within 3 chars of the limit (27+/30, 77+/80)
- Primary keyword in title
- Keyword duplication between title and subtitle
- Whether app purpose is immediately clear
- Unnecessary words (articles, prepositions) consuming space
- Special characters or claims ("#1", "best") that risk rejection (Apple)

---

## 2. Description (Weight: 15%)

### Apple App Store

| Score | Criteria                                                                                                                                               |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 9-10  | First 3 lines hook with clear value prop, structured with features/benefits/social proof/CTA, promotional text actively used, compelling and scannable |
| 7-8   | Good opening, decent structure, could improve scannability or CTA                                                                                      |
| 5-6   | Generic opening ("Welcome to..."), some structure, missing CTA or social proof                                                                         |
| 3-4   | Wall of text, no clear value prop above fold, no promotional text                                                                                      |
| 1-2   | Minimal or boilerplate description, no effort                                                                                                          |
| 0     | Cannot assess                                                                                                                                          |

### Google Play

| Score | Criteria                                                                                                                                     |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 9-10  | Keywords in first 3 sentences, 2-3% natural density throughout, HTML formatting used, structured sections, strong CTA, keywords feel natural |
| 7-8   | Good keyword presence, some structure, density slightly off (1-2% or 3-4%)                                                                   |
| 5-6   | Keywords present but sparse (<1%) or stuffed (>5%), weak structure                                                                           |
| 3-4   | No keyword strategy visible, poor formatting, wall of text                                                                                   |
| 1-2   | Minimal description, no keywords, no structure                                                                                               |
| 0     | Cannot assess                                                                                                                                |

**Check for:**

- First 3 lines quality (visible before "Read More")
- Feature-benefit framing (not just feature lists)
- Social proof (downloads, awards, press mentions)
- Call to action
- Keyword density (Google Play only - count target keywords / total words)
- HTML formatting usage (Google Play)
- Promotional text presence and quality (Apple)

---

## 3. Visual Assets (Weight: 25%)

| Score | Criteria                                                                                                                                                                      |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 9-10  | 8-10 screenshots with clear messaging/captions, preview video present, screenshots tell a story in sequence, each communicates one benefit, icon is distinctive and memorable |
| 7-8   | 6-7 screenshots with captions, good icon, no video OR good video but some screenshot messaging unclear                                                                        |
| 5-6   | 5+ screenshots but weak/no captions, basic icon, no video, screenshots are UI dumps                                                                                           |
| 3-4   | 3-4 screenshots, no captions, generic icon, no storytelling                                                                                                                   |
| 1-2   | Fewer than 3 screenshots, or screenshots are raw unedited UI, poor icon                                                                                                       |
| 0     | Cannot assess                                                                                                                                                                 |

**Check for:**

- Screenshot count (minimum 5, ideal 8-10)
- Caption/overlay text on screenshots (one message per screen, 5-7 words max)
- First 3 screenshots (highest conversion impact on Apple)
- Preview video presence and quality
- Icon distinctiveness (no text in icon, bold shapes, stands out)
- Feature graphic presence (Google Play - mandatory for featured placements)
- Screenshot storytelling flow (do they tell a coherent story?)
- Localized visual assets (for non-English markets)
- Caption keywords (Apple - indexed since June 2025)

---

## 4. Ratings & Reviews (Weight: 20%)

| Score | Criteria                                                                                               |
| ----- | ------------------------------------------------------------------------------------------------------ |
| 9-10  | 4.5+ stars, 10K+ ratings, recent reviews positive, developer responds to negatives, steady review flow |
| 7-8   | 4.0-4.4 stars, 1K+ ratings, mostly positive recent reviews, some developer responses                   |
| 5-6   | 3.5-3.9 stars, 500+ ratings, mixed recent reviews, no developer responses                              |
| 3-4   | 3.0-3.4 stars, <500 ratings, negative themes in recent reviews                                         |
| 1-2   | Below 3.0 stars, few ratings, no developer engagement, visible complaints                              |
| 0     | No ratings yet or cannot assess                                                                        |

**Check for:**

- Average rating (target: 4.0+ minimum, 4.5+ ideal)
- Total rating count
- Recent review sentiment (last 5-10 visible reviews)
- Common complaint themes (bugs, crashes, pricing, UX)
- Developer response presence and quality
- Rating trend (improving or declining, if visible)
- Review recency (fresh reviews signal active user base)

---

## 5. Metadata & Freshness (Weight: 10%)

| Score | Criteria                                                                                                                  |
| ----- | ------------------------------------------------------------------------------------------------------------------------- |
| 9-10  | Updated within last month, 10+ localizations, optimal category choice, in-app events/LiveOps active, data safety complete |
| 7-8   | Updated within 2 months, 5+ localizations, good category, data safety present                                             |
| 5-6   | Updated within 3 months, 2-4 localizations, acceptable category                                                           |
| 3-4   | Updated 3-6 months ago, 1-2 localizations, possibly wrong category                                                        |
| 1-2   | Not updated in 6+ months, single language, poor category choice                                                           |
| 0     | Cannot assess                                                                                                             |

**Check for:**

- Last update date and recency
- Number of supported languages/localizations
- Category selection (is it the best fit? less competitive alternative?)
- In-app events (Apple) or promotional content (Google) presence
- Data safety / privacy nutrition label completeness
- Age rating appropriateness
- Version history quality (do release notes communicate value?)
- What's New text quality

---

## 6. Conversion Signals (Weight: 10%)

| Score | Criteria                                                                                                                                                          |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 9-10  | Clear value before download, transparent pricing/IAP, social proof visible (press, awards), download range suggests strong traction, developer credibility strong |
| 7-8   | Good value communication, pricing clear, some social proof                                                                                                        |
| 5-6   | Value prop exists but weak, pricing unclear or IAP heavy, limited social proof                                                                                    |
| 3-4   | Unclear what user gets, confusing pricing, no social proof, low downloads visible                                                                                 |
| 1-2   | No value communication, suspicious pricing, app looks abandoned                                                                                                   |
| 0     | Cannot assess                                                                                                                                                     |

**Check for:**

- Price transparency (free, freemium, paid - is it clear?)
- In-app purchase list quality (do IAP names communicate value?)
- Download range (Google Play - 10K+, 100K+, 1M+ signals trust)
- Developer name/brand recognition
- "Editors' Choice" or featured badges
- Press mentions or awards in description
- Related apps from same developer (portfolio trust signal)
- Privacy practices transparency

---

## Calculating Final Score

```
Final Score = (Title * 0.20) + (Description * 0.15) + (Visuals * 0.25)
            + (Ratings * 0.20) + (Metadata * 0.10) + (Conversion * 0.10)

Scale to 100: Final Score * 10
```

**Example:** Title: 7, Description: 6, Visuals: 8, Ratings: 9, Metadata: 5, Conversion: 7

```
(7 * 0.20) + (6 * 0.15) + (8 * 0.25) + (9 * 0.20) + (5 * 0.10) + (7 * 0.10)
= 1.4 + 0.9 + 2.0 + 1.8 + 0.5 + 0.7
= 7.3 → 73/100 → Grade: B
```
