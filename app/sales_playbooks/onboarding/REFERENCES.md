# Reference files for the `onboarding` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/activation-models.md

# Activation Models

The activation model is *how* you let a user experience value before they pay. It shapes signup volume, conversion, and the entire onboarding path. Pick the model before you design the flow.

## The 5 activation models

### 1. Freemium
A free tier that never expires, with paid tiers for more capacity or features.

- Best when: the free tier delivers real value *and* naturally hits limits that motivate upgrading.
- Risk: give away too much and users never need to pay (see Evernote below).

### 2. Free trial
Full (or near-full) access for a fixed window: **3, 7, 14, or 30 days**.

- Shorter trials create urgency and force faster time-to-value; longer trials suit complex products with longer setup.
- **Credit-card requirement is the key lever**: requiring a card up front **cuts signups by 50–70%**, but the users who do sign up **convert 2–3× better**. Fewer, higher-intent leads vs. more, lower-intent leads — choose based on your funnel goals.

### 3. Paid trial
A low-cost paid entry, typically **$7–10 for 7 days**.

- Filters out tire-kickers while lowering the barrier vs. full price.
- Signals seriousness on both sides and pre-collects payment details.

### 4. Money-back guarantee
Charge full price up front, with a no-questions refund window.

- Removes purchase risk without giving anything away for free.
- Works when the product delivers value quickly enough to beat the refund window.

### 5. Consultation / white-glove
A human conversation (demo, call, or hands-on setup) gates access — the **Superhuman** model.

- Best for high-touch, high-price, or complex products where a human ensures the user reaches value.
- Doesn't scale cheaply, but converts and retains well when done right.

## Model-Market Fit

**Model-Market Fit (Brian Balfour): "your market dictates your model."**

You don't get to freely choose your activation model — your market chooses it for you. Price point, buyer sophistication, sales complexity, time-to-value, and competitor norms all constrain what will work. A self-serve $20/mo tool and a $50k enterprise platform cannot use the same model. Match the model to the market before optimizing the onboarding inside it.

## The Evernote vs. Notion parable

Two lessons on how much to give away:

- **Evernote — gave away too much free.** The free tier was generous enough that most users never needed to upgrade. Free was a destination, not a doorway. Growth without matching monetization.
- **Notion — hook, then limit.** Let users experience real value, then hit meaningful limits (blocks, members, features) that create a natural, well-timed reason to pay.

The principle: **the free experience should hook, not satisfy.** Give enough value to prove the product and build the habit — but structure the limits so that continued value requires upgrading.

## Choosing

1. Start from your market (Model-Market Fit), not your preference.
2. Decide the card-vs-no-card tradeoff explicitly: volume of leads vs. quality of leads.
3. Design the free/trial experience to hook and then limit — never to fully satisfy.
4. Whatever the model, the onboarding inside it still needs the shortest possible path to value (see [minimum-path-to-value.md](minimum-path-to-value.md)).


---

# references/experiments.md

# Onboarding Experiment Ideas

Comprehensive list of A/B tests and experiments for user onboarding and activation.

## Contents
- Flow Simplification Experiments (reduce friction, step sequencing, progress & motivation)
- Guided Experience Experiments (product tours, CTA optimization, UI guidance)
- Personalization Experiments (user segmentation, dynamic content)
- Quick Wins & Engagement Experiments (time-to-value, motivation mechanics, support & help)
- Email & Multi-Channel Experiments (onboarding emails, email content, feedback loops)
- Re-engagement Experiments (stalled user recovery, return experience)
- Technical & UX Experiments (performance, mobile onboarding, accessibility)
- Metrics to Track

## Flow Simplification Experiments

### Reduce Friction

| Test | Hypothesis |
|------|------------|
| Email verification timing | During vs. after onboarding |
| Empty states vs. dummy data | Pre-populated examples |
| Pre-filled templates | Accelerate setup with templates |
| OAuth options | Faster account linking |
| Required step count | Fewer required steps |
| Optional vs. required fields | Minimize requirements |
| Skip options | Allow bypassing non-critical steps |

### Step Sequencing

| Test | Hypothesis |
|------|------------|
| Step ordering | Test different sequences |
| Value-first ordering | Highest-value features first |
| Friction placement | Move hard steps later |
| Required vs. optional balance | Ratio of required steps |
| Single vs. branching paths | One path vs. personalized |
| Quick start vs. full setup | Minimal path to value |

### Progress & Motivation

| Test | Hypothesis |
|------|------------|
| Progress bars | Show completion percentage |
| Checklist length | 3-5 items vs. 5-7 items |
| Gamification | Badges, rewards, achievements |
| Completion messaging | "X% complete" visibility |
| Starting point | Begin at 20% vs. 0% |
| Celebration moments | Acknowledge completions |

---

## Guided Experience Experiments

### Product Tours

| Test | Hypothesis |
|------|------------|
| Interactive tours | Tools like Navattic, Storylane |
| Tooltip vs. modal guidance | Subtle vs. attention-grabbing |
| Video tutorials | For complex workflows |
| Self-paced vs. guided | User control vs. structured |
| Tour length | Shorter vs. comprehensive |
| Tour triggering | Automatic vs. user-initiated |

### CTA Optimization

| Test | Hypothesis |
|------|------------|
| CTA text variations | Action-oriented copy testing |
| CTA placement | Position within screens |
| In-app tooltips | Feature discovery prompts |
| Sticky CTAs | Persist during onboarding |
| CTA contrast | Visual prominence |
| Secondary CTAs | "Learn more" vs. primary only |

### UI Guidance

| Test | Hypothesis |
|------|------------|
| Hotspot highlights | Draw attention to key features |
| Coachmarks | Contextual tips |
| Feature announcements | New feature discovery |
| Contextual help | Help where users need it |
| Search vs. guided | Self-service vs. directed |

---

## Personalization Experiments

### User Segmentation

| Test | Hypothesis |
|------|------------|
| Role-based onboarding | Different paths by role |
| Goal-based paths | Customize by stated goal |
| Role-specific dashboards | Relevant default views |
| Use-case question | Personalize based on answer |
| Industry-specific paths | Vertical customization |
| Experience-based | Beginner vs. expert paths |

### Dynamic Content

| Test | Hypothesis |
|------|------------|
| Personalized welcome | Name, company, role |
| Industry examples | Relevant use cases |
| Dynamic recommendations | Based on user answers |
| Template suggestions | Pre-filled for segment |
| Feature highlighting | Relevant to stated goals |
| Benchmark data | Industry-specific metrics |

---

## Quick Wins & Engagement Experiments

### Time-to-Value

| Test | Hypothesis |
|------|------------|
| First quick win | "Complete your first X" |
| Success messages | After key actions |
| Progress celebrations | Milestone moments |
| Next step suggestions | After each completion |
| Value demonstration | Show what they achieved |
| Outcome preview | What success looks like |

### Motivation Mechanics

| Test | Hypothesis |
|------|------------|
| Achievement badges | Gamification elements |
| Streaks | Consecutive day engagement |
| Leaderboards | Social comparison (if appropriate) |
| Rewards | Incentives for completion |
| Unlock mechanics | Features revealed progressively |

### Support & Help

| Test | Hypothesis |
|------|------------|
| Free onboarding calls | For complex products |
| Contextual help | Throughout onboarding |
| Chat support | Availability during onboarding |
| Proactive outreach | For stuck users |
| Self-service resources | Help docs, videos |
| Community access | Peer support early |

---

## Email & Multi-Channel Experiments

### Onboarding Emails

| Test | Hypothesis |
|------|------------|
| Founder welcome email | Personal vs. generic |
| Behavior-based triggers | Action/inaction based |
| Email timing | Immediate vs. delayed |
| Email frequency | More vs. fewer touches |
| Quick tips format | Short actionable content |
| Video in email | More engaging format |

### Email Content

| Test | Hypothesis |
|------|------------|
| Subject lines | Open rate optimization |
| Personalization depth | Name vs. behavior-based |
| CTA prominence | Single clear action |
| Social proof inclusion | Testimonials in email |
| Urgency messaging | Trial reminders |
| Plain text vs. designed | Format testing |

### Feedback Loops

| Test | Hypothesis |
|------|------------|
| NPS during onboarding | When to ask |
| Blocking question | "What's stopping you?" |
| NPS follow-up | Actions based on score |
| In-app feedback | Thumbs up/down on features |
| Survey timing | When to request feedback |
| Feedback incentives | Reward for completing |

---

## Re-engagement Experiments

### Stalled User Recovery

| Test | Hypothesis |
|------|------------|
| Re-engagement email timing | When to send |
| Personal outreach | Human vs. automated |
| Simplified path | Reduced steps for returners |
| Incentive offers | Discount or extended trial |
| Problem identification | Ask what's blocking |
| Demo offer | Live walkthrough |

### Return Experience

| Test | Hypothesis |
|------|------------|
| Welcome back message | Acknowledge return |
| Progress resume | Pick up where left off |
| Changed state | What happened while away |
| Re-onboarding | Fresh start option |
| Urgency messaging | Trial time remaining |

---

## Technical & UX Experiments

### Performance

| Test | Hypothesis |
|------|------------|
| Load time optimization | Faster = higher completion |
| Progressive loading | Perceived performance |
| Offline capability | Mobile experience |
| Error handling | Graceful failure recovery |

### Mobile Onboarding

| Test | Hypothesis |
|------|------------|
| Touch targets | Size and spacing |
| Swipe navigation | Mobile-native patterns |
| Screen count | Fewer screens needed |
| Input optimization | Mobile-friendly forms |
| Permission timing | When to ask |

### Accessibility

| Test | Hypothesis |
|------|------------|
| Screen reader support | Accessibility impact |
| Keyboard navigation | Non-mouse users |
| Color contrast | Visibility |
| Font sizing | Readability |

---

## Metrics to Track

For all experiments, measure:

| Metric | Description |
|--------|-------------|
| Activation rate | % reaching activation event |
| Time to activation | Hours/days to first value |
| Step completion rate | % completing each step |
| Drop-off points | Where users abandon |
| Return rate | Users who come back |
| Day 1/7/30 retention | Engagement over time |
| Feature adoption | Which features get used |
| Support requests | Volume during onboarding |


---

# references/minimum-path-to-value.md

# Minimum Path to Value (MPTV)

**Minimum Path to Value (MPTV)** — the least number of steps to experience *enough* value to make a confident decision.

Not the fastest path to *any* value, and not the full feature tour. It's the shortest route to a moment that's convincing enough for the user to decide "yes, this is for me." Everything else waits.

## Why fewer steps win: Hick's Law

**Hick's Law** — the time and effort to make a decision grows with the number and complexity of choices. Every step, field, and option in onboarding is another decision. More decisions = more hesitation, more drop-off.

MPTV is the deliberate application of Hick's Law to onboarding: strip the path down to the fewest decisions required to reach value.

## The abandonment reality

You have far less time and patience than you think:

- **40–60% of users who sign up for a free trial abandon after a single session** — and never return.
- **75–80% of trial abandonment happens within the first day.**

The decision to stick or bail is made almost immediately. If value isn't reached in the first session, most users are already gone. MPTV exists because the window is that small.

## The process: inventory → remove → reconstruct

Build (or fix) your MPTV in three passes:

1. **Take inventory.** List *every* step between signup and value — every screen, form field, click, confirmation, permission prompt, and empty state. Be exhaustive and honest. Most teams underestimate their own step count by half.

2. **Remove the nonessential.** For each step ask: does the user *have* to do this to reach value right now? If not, cut it, defer it, pre-fill it, or make it skippable. Default to removal. Configuration, profile completeness, advanced settings, and "nice to know" education are almost never essential to first value.

3. **Reconstruct / iterate.** Rebuild the path with only what survived, in value-first order. Then measure and iterate — the first reconstruction is a hypothesis, not a finish line. Watch where users still stall and cut again.

## Benchmark patterns

Products with famously short paths to value:

| Product | MPTV pattern |
|---------|--------------|
| **Stripe** | Get a working payment integration in **~7 lines of code / ~60% activation** — value (a real charge) before any account polish. |
| **Calendly** | **3-step** setup to a shareable, working booking link. Value is a link you can send immediately. |
| **Notion** | **Progressive disclosure** — starts nearly empty, reveals features only as the user needs them. The path to first value (a written page) is trivial; depth unfolds later. |

The pattern across all three: reach a real, usable outcome fast, and hide complexity until it's asked for.

## Applying it

- Define the value moment first (the aha moment — see SKILL.md). MPTV is the path *to* that moment.
- Count your current steps before optimizing. You can't remove what you haven't inventoried.
- Treat every retained step as guilty until proven essential.
- Measure step-completion and time-to-value after each reconstruction; the abandonment stats mean your margin for error is one session.
