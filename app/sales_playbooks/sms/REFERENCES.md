# Reference files for the `sms` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/compliance.md

# SMS Compliance Reference

Comprehensive compliance reference for SMS marketing across major jurisdictions, opt-in copy templates, and STOP/HELP response templates.

> This is operational guidance, not legal advice. For high-volume programs (50K+ subscribers) or any program with non-trivial revenue, run your compliance setup past a TCPA-experienced attorney.

---

## United States — TCPA

### What it is

The Telephone Consumer Protection Act (1991, amended) regulates marketing calls and texts. The FCC enforces it; private plaintiffs sue under it. Statutory damages: $500–$1,500 **per message**. Class actions easily reach 7–8 figures.

### Consent tiers

| Type | What it covers | How to capture |
|------|---------------|----------------|
| **Express written consent** | Marketing SMS (sales, promotions, offers) | Checkbox + clear disclosure language, captured electronically with timestamp |
| **Express consent (non-written)** | Informational/transactional (delivery, account alerts) | Phone number provided during transaction with awareness it'll be used to text |
| **Established business relationship** | NOT sufficient for marketing SMS | Doesn't apply |

### Express written consent requirements

The opt-in flow must capture all of:

1. The recipient agreed to receive marketing SMS from your brand
2. The recipient understands consent is not a condition of purchase
3. The disclosure showed frequency expectation, message and data rate notice, STOP/HELP instructions, terms link
4. The agreement was electronically recorded with timestamp

### Opt-in disclosure template (compliant)

```
By signing up via text, you agree to receive recurring automated promotional and
personalized marketing text messages (e.g., cart reminders) from [Brand] at the
cell number used when signing up. Consent is not a condition of any purchase.
Reply HELP for help and STOP to cancel. Msg frequency varies. Msg & data rates
may apply. View [Terms](link) and [Privacy](link).
```

Place this **directly adjacent** to the phone number field and submit button. Do not bury it in a footer.

### Quiet hours

- **Federal**: 8am–9pm in the recipient's local time zone
- **Stricter states**: Florida (8am–8pm), Oklahoma (8am–8pm), Washington (8am–8pm)
- **Carrier-recommended**: 9am–8pm recipient-local
- **Practical default**: 9am–8pm recipient-local for safety

Time zone is determined by area code, but area codes lie (people move). Major platforms (Klaviyo, Postscript, Attentive) handle this automatically; verify yours does.

### STOP/HELP handling

**STOP variants you must honor**: STOP, END, CANCEL, UNSUBSCRIBE, QUIT, STOPALL, OPTOUT

**STOP response** (after STOP received):
```
You're unsubscribed from [Brand] alerts. No more messages will be sent. Reply HELP for help.
```

**HELP variants**: HELP, INFO

**HELP response**:
```
[Brand] alerts: For help, visit [URL] or email [support@brand.com]. Msg & data rates may apply. Reply STOP to cancel.
```

**Critical rules**:
- Honor STOP **within seconds**, every time, every keyword variant
- Do not require the recipient to log in or visit a website to opt out
- One STOP confirmation is allowed; do not send additional messages after
- HELP responses do not count as marketing messages and are not subject to quiet hours

### Sample TCPA-compliant footer language by sequence type

- **Opt-in confirmation**: "Reply HELP for help, STOP to cancel. Msg & data rates may apply." — required
- **Recurring promotional**: "Reply STOP to opt out" — required quarterly minimum; carrier-recommended every send
- **Transactional**: Not required by TCPA but carriers expect it; include for safety

---

## United States — A2P 10DLC

### What it is

Application-to-Person 10-Digit Long Code registration, run by The Campaign Registry (TCR). Required for businesses sending SMS through 10DLC numbers (regular long codes) since 2022. Carriers (T-Mobile, AT&T, Verizon) enforce this; unregistered traffic gets throttled or blocked.

### Registration components

1. **Brand registration**
   - Legal entity name, EIN, business type
   - Trust score assigned (Standard or Verified)
   - Higher trust = better throughput, lower fees

2. **Campaign registration** (one per use case)
   - Use case: Marketing, Account Notification, Customer Care, Public Service, Higher Education, Polling and Voting, 2FA, Delivery Notification, etc.
   - Sample message text (must match what you actually send)
   - Opt-in flow description and screenshot
   - Opt-out language
   - Help message language
   - Volume estimate

3. **Phone number assignment** to campaigns

### Throughput tiers (varies by carrier and trust score)

| Trust score + use case | Throughput |
|------------------------|-----------|
| Verified brand, marketing | 75–100+ msg/sec |
| Standard brand, marketing | 4–10 msg/sec |
| Unregistered | 0.1 msg/sec or blocked |

### Common rejections

- Sample message text doesn't match actual sends
- Opt-in flow screenshot doesn't show required disclosure language
- "SHAFT" content (Sex, Hate, Alcohol, Firearms, Tobacco) without explicit use case
- Generic or vague campaign descriptions

**Process time**: 1–7 business days. Plan for this in launch timelines.

---

## EU / UK — GDPR + ePrivacy Directive

### Consent requirements

- **Explicit opt-in**: clear affirmative action (no pre-checked boxes)
- **Specific**: opt-in must be for marketing SMS specifically, separate from generic ToS
- **Informed**: data subject must know who's processing and why
- **Freely given**: can't be bundled with service access

### Mandatory provisions

- Sender identity in every message
- Easy opt-out in every message
- Right to access data (DSARs)
- Right to deletion
- Records of consent kept for the duration of processing + statute of limitations

### Penalty exposure

GDPR fines up to €20M or 4% of global revenue, whichever is higher.

---

## Canada — CASL

### Consent

- **Express consent**: explicit opt-in (same standard as US TCPA express written consent)
- **Implied consent**: existing business relationship within 24 months — limited use, expires

### Every message must include

- Sender identification (legal name + any operating names)
- Mailing address
- Phone, email, or website contact
- Unsubscribe mechanism that works within 10 business days

### Penalty exposure

Up to CAD $10M per violation. Enforced by the CRTC.

---

## Australia — Spam Act 2003

- Express or inferred consent (inferred has narrow application)
- Sender ID required
- Functional unsubscribe required
- Enforced by ACMA

---

## Multi-jurisdictional programs

If you send across US + EU + Canada simultaneously:

- Default to the **strictest** standard across all jurisdictions (US TCPA express written consent + GDPR explicit opt-in)
- Track consent jurisdiction per subscriber
- Default quiet hours to recipient-local 9am–8pm
- Include all required identifiers in every message

---

## Audit-ready compliance checklist

- [ ] A2P 10DLC registration complete (US, if applicable)
- [ ] Opt-in flow includes all required disclosures, adjacent to phone field
- [ ] Disclosure text matches A2P registered sample messages
- [ ] Opt-in event captures: timestamp, IP, page URL, exact disclosure shown
- [ ] STOP/HELP keywords honored across all variants
- [ ] Quiet hours enforced at platform level (recipient-local time)
- [ ] Privacy policy includes SMS section
- [ ] Terms of service include SMS terms
- [ ] Consent records retained per applicable law (typically 4+ years US, longer EU)
- [ ] Process for handling DSARs (EU) and consent revocation
- [ ] Sender identity in every message
- [ ] Compliance footer on every promotional message (recommended) or quarterly minimum (required)
- [ ] Test STOP/HELP from a real phone number quarterly to verify it still works


---

# references/platforms.md

# SMS Platform Reference

Deep-dive on the major SMS marketing platforms — features, pricing, A2P 10DLC support, and integration paths.

> Pricing is approximate and changes regularly. Always confirm at the vendor's site before committing.

---

## Klaviyo SMS

**Best for**: DTC ecom brands already using Klaviyo for email.

### Key features
- Native integration with Klaviyo email and segmentation
- Shared subscriber profile across email + SMS
- Built-in A2P 10DLC registration
- Flow builder shared with email flows
- Conversational SMS (two-way) supported

### Pricing
- Bundled with Klaviyo plans, billed per SMS credit
- US: ~$0.0075–$0.015 per SMS; MMS ~$0.04
- Free tier: 150 SMS credits/month on lower email tiers

### Integration paths
- Direct Shopify, WooCommerce, BigCommerce, Magento integration
- API for custom platforms
- MCP server available

### Compliance
- A2P 10DLC registration handled in-platform
- Toll-free and short code provisioning available (short code adds $1,000+/mo)
- Quiet hours enforced per recipient time zone (configurable)

### Watch out for
- Email + SMS combined billing can spike fast on large lists
- Short code costs are real overhead; only worthwhile for 100K+ active SMS subscribers

---

## Postscript

**Best for**: Shopify-native DTC brands wanting SMS-specific tooling and onboarding support.

### Key features
- Deep Shopify integration (the deepest of any SMS platform)
- Strong abandoned cart and browse abandonment automations
- AI Reply (auto-reply trained on brand voice)
- Conversational SMS / live agent
- Audiences pulled from Shopify customer data

### Pricing
- Tiered plans: Starter (free, 1K msgs/mo), Growth ($100+/mo), Professional, Enterprise
- Pay-per-send adds on top: ~$0.015 per SMS, ~$0.04 per MMS

### Integration paths
- Shopify-first; limited support for non-Shopify
- API + webhooks available

### Compliance
- A2P 10DLC handled in-platform
- Strong opt-in compliance tools (popup builder, keyword opt-in)
- Quiet hours enforced

### Watch out for
- Steep cost increase past Starter tier
- Less useful if you're not on Shopify

---

## Attentive

**Best for**: Mid-market and enterprise DTC brands wanting full-service SMS.

### Key features
- Full-service: dedicated CSM, copy support, strategy
- Conversational SMS at scale
- Concierge sales-via-SMS
- Strong analytics and attribution
- Identity resolution (matching anon site visitors to phone numbers)

### Pricing
- Custom contracts; typically $1K–$10K+/mo + per-send fees
- Annual contracts standard
- Pricing rarely makes sense for <50K SMS subscribers

### Integration paths
- Shopify, BigCommerce, Salesforce Commerce Cloud, custom
- Robust API

### Compliance
- Full A2P 10DLC managed
- Best-in-class compliance tooling and audit support
- Short code provisioning included on most plans

### Watch out for
- Contract terms can lock you in for 12+ months
- Overkill for early-stage brands

---

## Twilio

**Best for**: Custom builds, transactional SMS, B2B SaaS embedding SMS into products, developers.

### Key features
- Raw SMS API
- Pay-per-send pricing, no platform fees
- Massive global coverage (200+ countries)
- Programmable Voice, WhatsApp Business, RCS available alongside
- Studio (visual flow builder) for non-code automation

### Pricing
- US 10DLC SMS: $0.0079 per message
- US toll-free SMS: $0.0079 per message
- US short code SMS: $0.0079 per message + $1,000/mo lease
- MMS: ~$0.02
- Carrier surcharges layered on top (~$0.005 per US 10DLC)
- A2P 10DLC registration: ~$15 brand + $10/mo per campaign

### Integration paths
- API-first (REST + SDKs in Node, Python, Ruby, Go, etc.)
- No native ecom integrations — you build them

### Compliance
- A2P 10DLC registration in-platform but you do the work
- TwilioSendGrid (separate product) handles email-side compliance
- Quiet hours and STOP/HELP handling must be implemented by you

### Watch out for
- You're responsible for compliance — no hand-holding
- No native segmentation, deliverability dashboards, or marketing UI
- Best paired with Customer.io, Segment, or a custom orchestration layer

---

## Brevo (formerly Sendinblue)

**Best for**: EU-based brands, email + SMS combo, SMB-friendly.

### Key features
- Combined email + SMS + WhatsApp on one platform
- EU-headquartered, GDPR-native
- Generous free tier for email; SMS pay-per-send
- Marketing automation flows
- CRM included

### Pricing
- Free tier: 300 emails/day; SMS pay-per-send
- US SMS: ~$0.015 per message
- EU SMS: varies by country, ~€0.04–€0.07

### Integration paths
- Direct integrations: Shopify, WooCommerce, WordPress, Magento
- API + Zapier
- MCP server available

### Compliance
- GDPR + ePrivacy built-in
- A2P 10DLC for US (less polished than dedicated US platforms)

### Watch out for
- US SMS features lag behind Klaviyo/Postscript
- Best if you're EU-first or already on Brevo for email

---

## SimpleTexting

**Best for**: SMB, services businesses, simple campaign blasts, low-volume.

### Key features
- Easy-to-use UI
- Keyword opt-in for grassroots list building
- Built-in landing pages for opt-in
- Simple automation

### Pricing
- Plans start ~$30/mo for 500 credits, scaling up
- US SMS only

### Integration paths
- Zapier, Make, native to a few apps
- API available but basic

### Compliance
- A2P 10DLC handled
- TCPA tooling

### Watch out for
- Limited automation depth vs Klaviyo/Postscript
- Best for low-complexity, low-volume use cases (gyms, salons, real estate)

---

## Plivo

**Best for**: Custom SMS builds where per-send cost matters; Twilio-style API at a lower price point.

### Key features
- Direct Twilio competitor with similar surface area
- Powerpack for bulk sending with sticky sender across number pools
- A2P 10DLC handled in-platform
- WhatsApp, voice available alongside SMS
- SDKs for major languages

### Pricing
- US 10DLC SMS: ~$0.0055/msg (typically 20–30% under Twilio)
- US short code SMS: similar + monthly lease
- MMS: ~$0.02
- Phone number rental: ~$0.80/mo local, ~$1/mo toll-free

### Integration paths
- API-first (REST + SDKs)
- No native ecom integrations — you build them

### Compliance
- A2P 10DLC managed in-platform
- Compliance plumbing (STOP/HELP, quiet hours) is your responsibility — same model as Twilio

### Watch out for
- Smaller ecosystem than Twilio (fewer ancillary products, integrations, community resources)
- WhatsApp tooling less mature

---

## AudienceTap

**Best for**: DTC brands wanting AI-forward creative tooling or on-pack QR opt-in as a primary acquisition channel.

> Newer platform — verify current capabilities, pricing, and API surface before committing.

### Key features
- SMS + email on one platform (similar combined model to Klaviyo)
- AI creative generation (SMS copy, subject lines, image variants)
- On-pack QR code opt-in: insert cards in shipped orders that drive SMS list growth
- Shopify, BigCommerce, headless commerce integrations
- A2P 10DLC managed in-platform
- Identity resolution and segmentation

### Pricing
- Tiered by subscriber count + send volume
- Per-send pricing comparable to other DTC SMS platforms

### Integration paths
- API access on Growth+ tiers
- Direct ecom integrations
- Webhooks for events

### Compliance
- A2P 10DLC handled in-platform
- TCPA tooling — verify enterprise-scale depth before committing for large lists

### Watch out for
- Newer entrant — fewer reference customers, less battle-tested at high volume than incumbents
- Some features rolled out recently — confirm what's GA vs beta before relying on them

---

## Customer.io

**Best for**: B2B SaaS, behavior-based automation, multi-channel orchestration (email + SMS + push).

### Key features
- Trigger SMS off product events (signup, milestone, churn risk)
- Powerful audience segmentation
- Workflow builder
- Real-time data sync via API/webhooks

### Pricing
- Plans start ~$150/mo, scaling with profile count
- SMS via Twilio integration or native (varies)

### Integration paths
- API-first
- Direct integrations with Segment, Heap, Mixpanel, etc.

### Compliance
- A2P 10DLC via Twilio if using native integration
- Granular subscription/consent management

### Watch out for
- Less ecom-tailored than Klaviyo/Postscript
- Best for product-led SaaS or apps with deep event tracking

---

## Quick selection table

| Stack / Goal | Recommended | Why |
|--------------|------------|-----|
| Shopify ecom, already on Klaviyo | **Klaviyo SMS** | One platform, one subscriber profile |
| Shopify ecom, SMS-first focus | **Postscript** | Deepest Shopify + SMS-specific features |
| Mid-market ecom, want concierge support | **Attentive** | Full-service team + tooling |
| Custom platform, B2B SaaS, transactional | **Twilio** | API-first, full control |
| Custom build, cost-sensitive | **Plivo** | ~20–30% cheaper than Twilio per send |
| DTC wanting AI creative or on-pack QR opt-in | **AudienceTap** | AI-forward; insert-card opt-in is unique |
| EU-based SMB | **Brevo** | GDPR-native, EU-friendly pricing |
| Local services SMB, simple campaigns | **SimpleTexting** | Easy UI, low overhead |
| Product-led SaaS with event tracking | **Customer.io** | Behavior-based triggers |

---

## A2P 10DLC: what your platform should handle

Whatever you pick, confirm your platform handles:

- [ ] Brand and campaign registration with TCR
- [ ] Sample message text aligned with what you actually send
- [ ] Opt-in flow documentation submitted to carriers
- [ ] Trust score visibility (and a path to improve it)
- [ ] Throughput appropriate to your list size and send frequency
- [ ] STOP/HELP keyword handling
- [ ] Quiet hours by recipient time zone
- [ ] Suppression list management
- [ ] Consent record retention with timestamps

All major platforms above handle these. Twilio does the lowest-level work and pushes more responsibility onto you.


---

# references/sequence-templates.md

# SMS Sequence Templates

Full copy templates with character counts, timing, and segmentation logic for every major SMS flow.

> Character counts shown assume GSM-7 encoding. Emojis force UCS-2 (70 chars/segment instead of 160). All templates use `[Brand]`, `[FirstName]`, and `[short.link]` as substitution tokens.

---

## Welcome / Opt-In Confirmation

### Send 1 — Immediate (after opt-in)

```
From [Brand]: Welcome! Here's your 10% off code: WELCOME10. Shop now: [short.link]
Reply STOP to opt out, HELP for help. Msg & data rates may apply.
```
~155 chars / 1 segment (just). Footer required on first send.

### Send 2 — 24 hours later (optional)

```
From [Brand]: Don't forget your code WELCOME10 — expires in 48hrs. Top picks: [short.link]
```
~108 chars / 1 segment.

### Send 3 — 7 days later (optional, conditional on no purchase)

```
From [Brand]: Last chance for 10% off with WELCOME10. Expires tonight at midnight: [short.link]
```
~107 chars / 1 segment.

---

## Abandoned Cart (highest-ROI flow for ecom)

### Send 1 — 30 minutes after abandon

```
From [Brand]: Hey [FirstName], you left something behind! Your cart's here: [short.link]
```
~95 chars / 1 segment.

### Send 2 — 4 hours after abandon (if no purchase)

```
From [Brand]: Items in your cart are selling fast. Reserved for you for 24hrs: [short.link]
```
~98 chars / 1 segment.

### Send 3 — 24 hours after abandon (if no purchase, discount allowed)

```
From [Brand]: Still thinking? Here's 10% off to seal the deal: SAVE10. Shop: [short.link]
```
~99 chars / 1 segment.

**Notes**:
- Discount on Send 1 trains customers to abandon. Reserve for Send 2 or 3.
- Exclude customers who abandoned <$X in cart value or repeat abandoners (gaming the discount).
- Stop sequence on purchase, opt-out, or 48 hours elapsed.

---

## Browse Abandonment

### Send 1 — 1 hour after browse (single product or category)

```
From [Brand]: Still thinking about [product]? Take another look: [short.link]
```
~84 chars / 1 segment.

**Notes**:
- Trigger only after meaningful browse signal (3+ product views or 2+ min on product page).
- Exclude if a purchase happened on a different product.

---

## Post-Purchase Flow

### Send 1 — Immediately after purchase (transactional, separate consent)

```
From [Brand]: Order #12345 confirmed! We'll text shipping updates here. Track: [short.link]
```
~95 chars / 1 segment.

### Send 2 — Day of shipment

```
From [Brand]: Your order's on the way. Estimated delivery: [date]. Track: [short.link]
```
~92 chars / 1 segment.

### Send 3 — Day of delivery

```
From [Brand]: Your order should arrive today! Questions? Reply or visit [short.link]
```
~88 chars / 1 segment.

### Send 4 — 2 days after delivery (marketing consent required)

```
From [Brand]: How are you liking your [product]? Share a review for 15% off next order: [short.link]
```
~108 chars / 1 segment.

### Send 5 — 14 days after delivery (cross-sell, marketing consent)

```
From [Brand]: Goes great with your [product]: [related-item]. 10% off bundle: [short.link]
```
~99 chars / 1 segment.

---

## Win-Back (Lapsed Customers)

### Send 1 — 60-90 days after last purchase

```
From [Brand]: [FirstName], we miss you! Picks we think you'll love: [short.link]
```
~84 chars / 1 segment.

### Send 2 — 14 days later (if no purchase)

```
From [Brand]: Come back for 15% off your next order: COMEBACK15. Expires in 7 days: [short.link]
```
~106 chars / 1 segment.

### Send 3 — 14 days after Send 2 (final, if no purchase)

```
From [Brand]: Last chance — 20% off ends tonight: COMEBACK20. We'll stop texting if you'd rather: reply STOP. [short.link]
```
~130 chars / 1 segment.

**Notes**:
- After Send 3 with no engagement, suppress for 90 days minimum.
- After two full win-back cycles with no engagement, sunset (remove from active list).

---

## Promotional / Campaign Sends

### Flash sale (single send)

```
From [Brand]: 24-HOUR FLASH: 25% off everything with FLASH25. Ends midnight: [short.link]
```
~94 chars / 1 segment.

### Limited drop / launch

```
From [Brand]: New drop just landed: [product-name]. Limited stock, members get early access: [short.link]
```
~115 chars / 1 segment.

### Holiday / BFCM (2-send sequence)

Send 1 — Day of launch:
```
From [Brand]: Black Friday is LIVE — up to 50% off sitewide. Shop now: [short.link]
```
~92 chars / 1 segment.

Send 2 — Day of (or evening, expiration push):
```
From [Brand]: Last 6 hours of BFCM savings. Don't miss out: [short.link]
```
~73 chars / 1 segment.

---

## Transactional / Account Notifications

### Order confirmation

```
[Brand]: Order #12345 confirmed. Total $XX.XX. Track at [short.link]. Reply HELP for help.
```

### Shipping update

```
[Brand]: Your order #12345 shipped! Track: [short.link]. ETA [date].
```

### Delivery confirmation

```
[Brand]: Order #12345 delivered. Enjoy! Issues? Reply or [support-link].
```

### Auth code (2FA)

```
[Brand] verification code: 123456. Expires in 10 min. Do not share.
```

### Account alert

```
[Brand]: Sign-in from new device in [location]. Wasn't you? Secure: [short.link]
```

---

## Re-Engagement / Reactivation (Subscribers Who've Gone Cold)

For SMS subscribers who haven't engaged with any send in 60+ days.

### Send 1 — Soft reactivation

```
From [Brand]: We've missed you, [FirstName]! Here's what's new: [short.link]
```
~80 chars / 1 segment.

### Send 2 — Confirm interest (if no engagement)

```
From [Brand]: Want to keep hearing from us? Reply YES to stay on the list, or STOP to opt out.
```
~98 chars / 1 segment.

After no reply: suppress for 60 days, then remove from active list. This protects opt-out rate metrics and reduces wasted spend.

---

## Replenishment (Consumables Ecom)

For products with predictable usage cycles (skincare, supplements, coffee, pet food).

### Send 1 — At expected reorder window (e.g., 28 days for a 30-day supply)

```
From [Brand]: Running low on [product]? Reorder in one tap: [short.link]
```
~73 chars / 1 segment.

### Send 2 — 7 days later (if no purchase)

```
From [Brand]: Don't run out! 10% off your reorder of [product]: REFILL10 [short.link]
```
~92 chars / 1 segment.

---

## VIP / Loyalty Members

Higher frequency, exclusive offers, early access — different cadence rules apply but quiet hours and STOP still required.

### Early access

```
From [Brand]: VIPs get the new drop 24hrs early. Yours now: [short.link]
```
~72 chars / 1 segment.

### Loyalty milestone

```
From [Brand]: You've reached Gold status! Your perks: 15% off + free shipping. [short.link]
```
~95 chars / 1 segment.

---

## Segmentation rules across all flows

- **Suppress** customers in active sequences from promotional sends (no double-tap)
- **Suppress** opted-out subscribers from everything (platform handles this)
- **Frequency cap**: max 4–6 marketing sends/week per subscriber (lower for newer subscribers)
- **Quiet hours**: 9am–8pm recipient-local time
- **Cool-off**: After a discount-driven purchase, suppress promotional sends for 14 days
