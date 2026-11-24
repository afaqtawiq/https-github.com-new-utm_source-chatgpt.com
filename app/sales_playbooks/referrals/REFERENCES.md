# Reference files for the `referrals` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/affiliate-programs.md

# Affiliate Program Design

Detailed guidance for building and managing affiliate programs.

## Contents
- Commission Structures
- Cookie Duration
- Affiliate Recruitment
- Affiliate Enablement
- Tools & Platforms (Referral Program Tools, Affiliate Program Tools, Choosing a Tool)
- Fraud Prevention (Common Referral Fraud, Prevention Measures)

## Commission Structures

**Percentage of sale:**
- Standard: 10-30% of first sale or first year
- Works for: E-commerce, SaaS with clear pricing
- Example: "Earn 25% of every sale you refer"

**Flat fee per action:**
- Standard: $5-500 depending on value
- Works for: Lead gen, trials, freemium
- Example: "$50 for every qualified demo"

**Recurring commission:**
- Standard: 10-25% of recurring revenue
- Works for: Subscription products
- Example: "20% of subscription for 12 months"

**Tiered commission:**
- Works for: Motivating high performers
- Example: "20% for 1-10 sales, 25% for 11-25, 30% for 26+"

---

## Cookie Duration

How long after click does affiliate get credit?

| Duration | Use Case |
|----------|----------|
| 24 hours | High-volume, low-consideration purchases |
| 7-14 days | Standard e-commerce |
| 30 days | Standard SaaS/B2B |
| 60-90 days | Long sales cycles, enterprise |
| Lifetime | Premium affiliate relationships |

---

## Affiliate Recruitment

### Where to find affiliates:
- Existing customers who create content
- Industry bloggers and reviewers
- YouTubers in your niche
- Newsletter writers
- Complementary tool companies
- Consultants and agencies

### Outreach template:
```
Subject: Partnership opportunity — [Your Product]

Hi [Name],

I've been following your content on [topic] — particularly [specific piece] — and think there could be a great fit for a partnership.

[Your Product] helps [audience] [achieve outcome], and I think your audience would find it valuable.

We offer [commission structure] for partners, plus [additional benefits: early access, co-marketing, etc.].

Would you be open to learning more?

[Your name]
```

---

## Affiliate Enablement

Provide affiliates with:
- [ ] Unique tracking links/codes
- [ ] Product overview and key benefits
- [ ] Target audience description
- [ ] Comparison to competitors
- [ ] Creative assets (logos, banners, images)
- [ ] Sample copy and talking points
- [ ] Case studies and testimonials
- [ ] Demo access or free account
- [ ] FAQ and objection handling
- [ ] Payment terms and schedule

---

## Tools & Platforms

### Referral Program Tools

**Full-featured platforms:**
- ReferralCandy — E-commerce focused
- Ambassador — Enterprise referral programs
- Friendbuy — E-commerce and subscription
- GrowSurf — SaaS and tech companies
- Mention Me — AI-powered referral marketing
- Viral Loops — Template-based campaigns

**Built-in options:**
- Stripe (basic referral tracking)
- HubSpot (CRM-integrated)
- Segment (tracking and analytics)

### Affiliate Program Tools

**Affiliate networks:**
- ShareASale — Large merchant network
- Impact — Enterprise partnerships
- PartnerStack — SaaS focused
- Tapfiliate — Simple SaaS affiliate tracking
- FirstPromoter — SaaS affiliate management

**Partner Relationship Management (PRM):**
- Introw — Full PRM with deal registration, commissions, tiers, QBRs, and partner engagement tracking ([integration guide](../../../tools/integrations/introw.md))

**Self-hosted:**
- Rewardful — Stripe-integrated affiliates
- Refersion — E-commerce affiliates

### Choosing a Tool

Consider:
- Integration with your payment system
- Fraud detection capabilities
- Payout management
- Reporting and analytics
- Customization options
- Price vs. program scale

---

## Fraud Prevention

### Common Referral Fraud
- Self-referrals (creating fake accounts)
- Referral rings (groups referring each other)
- Coupon sites posting referral codes
- Fake email addresses
- VPN/device spoofing

### Prevention Measures

**Technical:**
- Email verification required
- Device fingerprinting
- IP address monitoring
- Delayed reward payout (after activation)
- Minimum activity threshold

**Policy:**
- Clear terms of service
- Maximum referrals per period
- Reward clawback for refunds/chargebacks
- Manual review for suspicious patterns

**Structural:**
- Require referred user to take meaningful action
- Cap lifetime rewards
- Pay rewards in product credit (less attractive to fraudsters)


---

# references/program-examples.md

# Referral Program Examples

Real-world examples of successful referral programs.

## Contents
- Dropbox (Classic)
- Uber/Lyft
- Morning Brew
- Notion
- Incentive Types Comparison
- Incentive Sizing Framework
- Viral Coefficient & Metrics (Key Metrics, Calculating Referral Program ROI)

## Dropbox (Classic)

**Program:** Give 500MB storage, get 500MB storage

**Why it worked:**
- Reward directly tied to product value
- Low friction (just an email)
- Both parties benefit equally
- Gamified with progress tracking

---

## Uber/Lyft

**Program:** Give $10 ride credit, get $10 when they ride

**Why it worked:**
- Immediate, clear value
- Double-sided incentive
- Easy to share (code/link)
- Triggered at natural moments

---

## Morning Brew

**Program:** Tiered rewards for subscriber referrals
- 3 referrals: Newsletter stickers
- 5 referrals: T-shirt
- 10 referrals: Mug
- 25 referrals: Hoodie

**Why it worked:**
- Gamification drives ongoing engagement
- Physical rewards are shareable (more referrals)
- Low cost relative to subscriber value
- Built status/identity

---

## Notion

**Program:** $10 credit per referral (education)

**Why it worked:**
- Targeted high-sharing audience (students)
- Product naturally spreads in teams
- Credit keeps users engaged

---

## Incentive Types Comparison

| Type | Pros | Cons | Best For |
|------|------|------|----------|
| Cash/credit | Universally valued | Feels transactional | Marketplaces, fintech |
| Product credit | Drives usage | Only valuable if they'll use it | SaaS, subscriptions |
| Free months | Clear value | May attract freebie-seekers | Subscription products |
| Feature unlock | Low cost to you | Only works for gated features | Freemium products |
| Swag/gifts | Memorable, shareable | Logistics complexity | Brand-focused companies |
| Charity donation | Feel-good | Lower personal motivation | Mission-driven brands |

---

## Incentive Sizing Framework

**Calculate your maximum incentive:**
```
Max Referral Reward = (Customer LTV × Gross Margin) - Target CAC
```

**Example:**
- LTV: $1,200
- Gross margin: 70%
- Target CAC: $200
- Max reward: ($1,200 × 0.70) - $200 = $640

**Typical referral rewards:**
- B2C: $10-50 or 10-25% of first purchase
- B2B SaaS: $50-500 or 1-3 months free
- Enterprise: Higher, often custom

---

## Viral Coefficient & Metrics

### Key Metrics

**Viral coefficient (K-factor):**
```
K = Invitations × Conversion Rate

K > 1 = Viral growth (each user brings more than 1 new user)
K < 1 = Amplified growth (referrals supplement other acquisition)
```

**Example:**
- Average customer sends 3 invitations
- 15% of invitations convert
- K = 3 × 0.15 = 0.45

**Referral rate:**
```
Referral Rate = (Customers who refer) / (Total customers)
```

Benchmarks:
- Good: 10-25% of customers refer
- Great: 25-50%
- Exceptional: 50%+

**Referrals per referrer:**

Benchmarks:
- Average: 1-2 referrals per referrer
- Good: 2-5
- Exceptional: 5+

### Calculating Referral Program ROI

```
Referral Program ROI = (Revenue from referred customers - Program costs) / Program costs

Program costs = Rewards paid + Tool costs + Management time
```

**Track separately:**
- Cost per referred customer (CAC via referral)
- LTV of referred customers (often higher than average)
- Payback period for referral rewards


---

# references/viral-mechanisms.md

# Viral Mechanisms

Virality can be **engineered through product design**, not just bought with reward programs. But don't force it — decide *whether* virality fits your product before building anything.

## Contents
- Viral Potential Spectrum (the diagnostic)
- The 7 Viral Mechanisms
- Referral Best Practices (presentation, timing, friction)
- Affiliate Mechanics (buyout clauses, the 20/80 power law, launch tactics)

---

## Viral Potential Spectrum

Before engineering virality, place your product on the spectrum. **Don't force virality where it doesn't naturally fit.**

**Natural viral potential (build for it):**
- **Collaboration tools** — value grows when you invite others (docs, whiteboards, project management)
- **Communication tools** — you can't use them alone (email, scheduling, messaging)
- **User-facing outputs** — every use produces something others see (design, video, forms, links)

**Limited viral potential (don't force it):**
- **Backend / infrastructure** — invisible to end users
- **Competitive-advantage tools** — users *hide* that they use them (their edge)
- **Internal-only tools** — never leave the org
- **Infrastructure** — plumbing no one talks about

If you're on the limited end, invest in referral programs, content, and partnerships instead of embedding viral loops that won't fire.

---

## The 7 Viral Mechanisms

Most are **non-incentive** — the loop is built into the product, not paid for.

### 1. "Powered By" Badges
A small attributed badge on user-facing output ("Powered by [Product]"). Every page/form/widget a customer ships becomes an ad. Often free-tier only (paid tier removes it).

### 2. Exposure Loops
The product's normal use exposes it to non-users.
- **Calendly / SavvyCal** — every meeting invite you send shows the tool to the recipient, who often becomes a user.
- **Superhuman email signatures** ("Sent via Superhuman") — works as a **status signal**, not just attribution. The signature signaled early-adopter status, so recipients *wanted* it. Exposure loops are strongest when using the product confers status.

### 3. Social Sharing
Make output natively shareable with a branded hook.
- **#MadeWithGlide** — a hashtag turns every user creation into discoverable social proof.
- One-tap "share to X/LinkedIn" on any milestone, result, or artifact.

### 4. Embed Options
Let users embed their content elsewhere; the embed carries your brand and a link back.
- **Notion, Figma, Loom** — embedded docs, designs, and videos spread the product to every viewer on every host site.

### 5. Watermarks / Mandatory Badges
Like "Powered By" but harder to remove — baked into the output itself.
- **OpusClips** watermark on generated clips.
- **"Made in Webflow"** badge on free-plan sites.
Free tier carries the mark; paid tier removes it. The free users become the distribution.

### 6. Referral Programs
Explicit incentives for referring. Covered in detail in [program-examples.md](program-examples.md) and below. The one *incentive-driven* mechanism on this list — use it when the product itself doesn't naturally spread.

### 7. Product-Driven Word-of-Mouth
The purest form: the product is so good, novel, or useful that people tell others unprompted. Not a mechanism you bolt on — it's earned through the product experience. Engineering the other six makes this easier to trigger.

---

## Referral Best Practices

Detail beyond the core referral loop (trigger → share → convert → reward).

### Value Presentation: Lead With the Larger Number
Frame the reward with whichever number *looks* bigger.
- On a $25 product, say **"$10 off"** — not "40% off."
- On a $500 product, say **"20% off"** — not "$100 off" if the percentage frames better... but usually the absolute dollar figure wins for smaller prices.
- Rule of thumb: **under ~$100, lead with the dollar amount; over ~$100, test the percentage.** Always pick the bigger-*feeling* number.

### Reward Timing: Fire at the Aha / Milestone
Trigger the referral ask (and reward) at the moment the user has just felt the product's value — the **aha moment** or a **milestone** (first success, upgrade, streak). Motivation to share peaks right after value is experienced, not at signup.

### Double-Sided Rewards
Both referrer and referred get value. Higher conversion than single-sided, and gives the referrer a generous, non-selfish reason to share ("here's $10 for you too").

### Friction Reduction
Every extra step kills share rate.
- **One-click sharing** — pre-generated link, no form.
- **Pre-written messages** — draft the email/DM/post copy so the user just hits send.
- In-product placement at the trigger moment, not buried in settings.

---

## Affiliate Mechanics

Detail deferred from the partnerships side — for building an affiliate motion into a referral/partner strategy.

### Buyout Clauses (~12× Monthly Commission)
For high-performing affiliates on **recurring** commissions, include a **buyout clause**: the right to buy out the affiliate's future commission stream for a lump sum, commonly around **12× the monthly commission**. Protects margin on a customer the affiliate referred once but earns on forever, and gives the affiliate an attractive cash-out.

### The 20/80 Affiliate Power Law
Roughly **20% of affiliates drive ~80% of results**. Don't spread effort evenly across a long tail of dormant sign-ups. **Identify super-promoters and invest in them** — higher tiers, custom assets, co-marketing, direct relationship, early access. Recruiting 1,000 passive affiliates is worth less than activating 10 great ones.

### Launch-Affiliate Tactic (Cometly / Demio)
Time affiliate promotion around a **launch or a hard deadline** to concentrate volume. Cometly drove **$251K on a single launch day** by mobilizing affiliates simultaneously; Demio ran launch-window affiliate pushes. The mechanic: give affiliates a shared date, shared assets, and a reason for their audience to act *now* (bonus, cohort, closing offer) so promotion stacks instead of trickling.
