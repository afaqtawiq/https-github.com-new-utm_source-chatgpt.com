# Reference files for the `free-tools` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/tool-benchmarks.md

# Free Tool Case Benchmarks

Real free tools and the numbers they produced. Use these to set expectations, justify the build, and pattern-match your concept against what actually worked.

## Framing: "Your product is my marketing opportunity"

Bezos's line was **"your margin is my opportunity"** — where a competitor monetizes something, undercut it. The engineering-as-marketing version is **"your product is my marketing opportunity."** Take a capability others sell, build a simple free version, and turn it into an acquisition channel. Unsplash gave away the stock photos that Getty charged for — and Getty ended up acquiring it.

## Case Library

| Tool | Company | Build cost | Result |
|------|---------|-----------|--------|
| Unsplash | Crew | 3 hrs, leftover redesign photos | 11M monthly visitors; acquired by Getty |
| Website Grader | HubSpot | 2 engineers, 2 weeks | 250K leads, 98% auto-qualification, $6M revenue |
| Forecasting | Baremetrics | — | 35% trial conversion |
| Headline Analyzer | CoSchedule | — | ~20% of users convert to subscribers |
| Keyword Explorer | Moz | — | 40% trial conversion, CAC down 65% |
| Salary Calculator | Buffer | — | 1.5M visitors, 12% signup rate |
| Hatchful | Shopify | — | 25% trial conversion |

## What each case teaches

- **Crew → Unsplash** — The anchor case. A near-zero-cost byproduct (leftover photos from a redesign, ~3 hrs to ship) became a top-of-funnel giant. Give away what others charge for; the reach compounds.
- **HubSpot Website Grader** — Small build (2 engineers, 2 weeks), enormous return. Proof that an analyzer/grader can double as a lead engine *and* a qualification engine — 98% of leads auto-qualified because the tool's inputs revealed fit.
- **Baremetrics Forecasting** — A tool adjacent to the core product (revenue analytics) that converts trials at 35% because using it makes the paid product's value obvious.
- **CoSchedule Headline Analyzer** — Repeat-use analyzer with a low-friction path to subscription (~20%). High recurring usage keeps the brand in front of the audience.
- **Moz Keyword Explorer** — A free surface of the paid product itself: 40% trial conversion and a 65% drop in CAC because the tool *is* the demo.
- **Buffer Salary Calculator** — Not adjacent to the product at all, but massively shareable: 1.5M visitors, 12% signup. Pure reach + brand play that still converts.
- **Shopify Hatchful** — A generator (logo maker) that feeds the core product's onboarding, converting trials at 25%.

## How to use these benchmarks

- **Set expectations**: Analyzer/grader tools tend to convert visitors to leads well and qualify them; calculators skew toward reach and share-worthiness; generators feed onboarding.
- **Justify the build**: Compare your expected lead value × volume against these ratios before committing engineering time.
- **Pattern-match**: Find the case closest to your concept (adjacent-to-product vs pure-reach) and borrow its gating and distribution approach.


---

# references/tool-types.md

# Free Tool Types Reference

Detailed guide to each type of marketing tool you can build.

## Contents
- Calculators
- Generators
- Analyzers/Auditors
- Testers/Validators
- Libraries/Resources
- Interactive Educational
- Tool Concept Examples by Industry (SaaS product, agency/services, e-commerce, developer tools, finance)

## Calculators

**Best for**: Decisions involving numbers, comparisons, estimates

**Examples**:
- ROI calculator
- Savings calculator
- Cost comparison tool
- Salary calculator
- Tax estimator
- Pricing estimator
- Compound interest calculator
- Break-even calculator

**Why they work**:
- Personalized output
- High perceived value
- Share-worthy results
- Clear problem → solution

**Implementation tips**:
- Keep inputs simple
- Show calculations transparently
- Make results shareable
- Add "powered by" branding

---

## Generators

**Best for**: Creating something useful quickly

**Examples**:
- Policy generator (privacy, terms)
- Template generator
- Name/tagline generator
- Email subject line generator
- Resume builder
- Color palette generator
- Logo maker
- Contract generator

**Why they work**:
- Tangible output
- Saves time
- Easily shared
- Repeat usage

**Implementation tips**:
- Output should be immediately usable
- Allow customization
- Offer download/export options
- Include email gating for premium outputs

---

## Analyzers/Auditors

**Best for**: Evaluating existing work or assets

**Examples**:
- Website grader
- SEO analyzer
- Email subject tester
- Headline analyzer
- Security checker
- Performance auditor
- Accessibility checker
- Code quality analyzer

**Why they work**:
- Curiosity-driven
- Personalized insights
- Creates awareness of problems
- Natural lead to solution

**Implementation tips**:
- Score or grade for gamification
- Benchmark against averages
- Provide actionable recommendations
- Follow up with improvement offers

---

## Testers/Validators

**Best for**: Checking if something works

**Examples**:
- Meta tag preview
- Email rendering test
- Mobile-friendly test
- Speed test
- DNS checker
- SSL certificate checker
- Redirect checker
- Broken link finder

**Why they work**:
- Immediate utility
- Bookmark-worthy
- Repeat usage
- Professional necessity

**Implementation tips**:
- Fast results are essential
- Show pass/fail clearly
- Provide fix instructions
- Integrate with your product where relevant

---

## Libraries/Resources

**Best for**: Reference material

**Examples**:
- Icon library
- Template library
- Code snippet library
- Example gallery
- Industry directory
- Resource list
- Swipe file collection
- Font pairing tool

**Why they work**:
- High SEO value
- Ongoing traffic
- Establishes authority
- Linkable asset

**Implementation tips**:
- Make searchable/filterable
- Allow easy copying/downloading
- Update regularly
- Accept community submissions

---

## Interactive Educational

**Best for**: Learning/understanding

**Examples**:
- Interactive tutorials
- Code playgrounds
- Visual explainers
- Quizzes/assessments
- Simulators
- Comparison tools
- Decision trees
- Configurators

**Why they work**:
- Engages deeply
- Demonstrates expertise
- Shareable
- Memory-creating

**Implementation tips**:
- Make it hands-on
- Show immediate feedback
- Lead to deeper resources
- Capture engaged users

---

## Tool Concept Examples by Industry

### SaaS Product
- Product ROI calculator
- Competitor comparison tool
- Readiness assessment quiz
- Template library for use case
- Feature configurator

### Agency/Services
- Industry benchmark tool
- Project scoping calculator
- Portfolio review tool
- Cost estimator
- Proposal generator

### E-commerce
- Product finder quiz
- Comparison tool
- Size/fit calculator
- Savings calculator
- Gift finder

### Developer Tools
- Code snippet library
- Testing/preview tool
- Documentation generator
- Interactive tutorials
- API playground

### Finance
- Financial calculators
- Investment comparison
- Budget planner
- Tax estimator
- Loan calculator
