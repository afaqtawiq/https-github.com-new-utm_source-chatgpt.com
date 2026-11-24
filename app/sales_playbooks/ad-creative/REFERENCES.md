# Reference files for the `ad-creative` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/creative-review-page.md

# The Creative Review Page

A shareable, self-contained web page that presents generated ad concepts for a client or stakeholder to **review and pick** — the visual upgrade to `INDEX.md`. Where the markdown outputs are built for the operator, the review page is built for the person approving the spend: it shows each concept as an in-feed platform mockup, breaks carousels into a labeled frame-by-frame storyboard, lets them toggle copy variations, and discloses what's grounded in real assets.

The template ships at [assets/creative-review-template.html](../assets/creative-review-template.html). It's one file — inline CSS and JS, no build, no dependencies, no network. Open it locally, host it on any static host (Vercel/Netlify/GitHub Pages), or hand off the `.html` file directly.

## When to produce one

- **Presenting a batch for approval** — after Mode 1 or Mode 3 generation, package the top concepts into a review page instead of (or alongside) `INDEX.md`. Picking 5 of 50 is a *visual* decision; a client shouldn't have to read markdown to make it.
- **Pitching a whitelist / co-branded partnership** — the format the source pattern was built for: show the partner exactly what the ad looks like under each handle, with the rollout mechanics spelled out.
- **A monthly slate review** (Mode 4) — render the slate's concepts so the account-state call and the pick happen off one link.

Don't produce one for a single headline tweak or a quick internal gut-check — the markdown output is faster. Reach for the review page when a human who isn't you needs to choose.

## How it's built

The template renders entirely from a JSON block near the top of the file — `<script type="application/json" id="review-data">`. Populate it from your generated concepts and everything else renders — tabs, previews, storyboard, copy panel. You do not edit the render code below the data block. The annotated model below is shown with `//` comments for readability; **the file itself is strict JSON** — no comments, no trailing commas (see "Populating the data safely").

### Data model

```jsonc
{
  project: {
    brand: "Truvani",              // required
    agency: "Light Labs",          // optional — adds the co-brand line + the default handle fallback (partner label/initials)
    date: "2026-07-12",            // optional
    note: "one-line context"       // optional
  },
  platforms: ["instagram", "facebook"],   // previews to offer; first is the default. Supported: instagram, facebook
  concepts: [                              // each concept is one strategic ANGLE (see SKILL.md "Define Your Angles")
    {
      name: "Heavy-Metal Proof",           // required — the angle name
      tagline: "Lifestyle hero, then the lab results",   // one line, what makes this concept distinct
      handles: [                            // optional. 1 entry = normal post; 2 = whitelist handle toggle
        { name: "truvani", partner: "Paid partnership with lightlabs", initials: "TV" },
        { name: "Light Labs", partner: "Paid partnership with truvani", initials: "LL" }
      ],
      frames: [                             // 1 frame = single ad; multiple = carousel storyboard
        {
          label: "Hook",                    // the frame's job in the narrative arc
          prompt: "Product bag hero on soft pink, gold-lace overlay",  // image description (shown as placeholder if no image)
          image: "images/heavy-metal-01.png",   // optional — URL, relative path, or data URI; omit for text-only concepts
          headline: "Finally — a plant-based protein that's third-party tested for heavy metals.",  // optional per-frame overlay
          headlineTheme: "dark"             // optional: "dark" (default, white text) or "light" (dark text on light imagery)
        }
        // … one object per frame
      ],
      headlines: [                          // selectable variations; the picked one overlays frame 1 in the preview
        "Finally — a plant-based protein that's third-party tested for heavy metals.",
        "We tested our protein for heavy metals. Here's what an independent lab found.",
        "Most protein powders are never tested for heavy metals. Ours is."
      ],
      primaryText: "The caption / body copy.",
      destination: { url: "shop.truvani.com", cta: "Shop now", offer: "72% OFF Protein Starter Kit" },
      rollout: {                            // optional — the mechanics of how this runs (whitelist, launch plan)
        title: "How the whitelist runs",
        steps: ["step 1", "step 2", "…"]
      },
      grounding: "What in this concept is real — the required disclosure. See below."
    }
    // … 2–4 concepts is the sweet spot; more than that and the tabs stop being a decision
  ]
}
```

### The frame storyboard = a carousel narrative arc

A concept's `frames` are its storyboard. Label each frame by the *job it does*, not its content — `Hook`, `The problem`, `The results`, `The ask`. This is the same narrative-arc thinking as the carousel frameworks: a proof-led concept is literally Hook → Problem → Mechanism → Results → Context → Ask. For the five reusable carousel arcs (Value-Stack, Problem-Proof, Hack List, Rant Callout, Demo Walkthrough), see `carousel-frameworks.md` in the **social** skill and pick the arc that fits the angle before writing frames.

### Images vs. placeholders

Every frame renders one of two ways:
- **`image` provided** — the real creative (from the Mode 3 `images/` folder, a hosted URL, or a data URI) fills the frame.
- **`image` omitted** — a styled placeholder shows the frame `label` + `prompt`. This is the intended state for concepts that are copy + image-prompt but not yet rendered to image — the review page is useful *before* images exist, and stays useful as they get filled in.

Ship review pages with placeholders freely; they communicate the concept. Swap in images as they're generated.

## Grounding — the disclosure block is required

Every concept must carry a `grounding` line, and it must be true. This is the same rule as the Grounded Inputs corpus, surfaced to the client: state exactly what is real (which lab panel, which review, which product photography) and, by omission, what is illustrative. The source pattern's line is the model — *"Results are Truvani's actual Light Labs panel (Vanilla, tested Nov 13, 2025). Imagery is Truvani's own product & lifestyle photography."*

Never present invented stats, fabricated test results, or stock imagery as the brand's own. If a concept's proof isn't real yet, the grounding line says so ("Results shown are illustrative pending the lab panel") — a review page that launders fiction as fact is worse than no review page.

## Populating the data safely

The `DATA` lives in a `<script type="application/json" id="review-data">` block — it's inert data (parsed with `JSON.parse`), not executable code, so a value can never run as script. Two rules when you write it:

- **Valid JSON only** — double-quoted keys and strings, no comments, no trailing commas. (The page shows a clear error banner if the JSON is malformed, so a typo fails loud, not silent.)
- **Escape `<` as `\u003c` in every text value.** A value literally containing `</script>` would otherwise close the data block early. Since agents write the JSON, apply this escape mechanically to all string values. All values are HTML-escaped again at render time, so this is defense-in-depth, but the source-level escape is the one that matters — do it.

## Producing and delivering it

1. Copy `assets/creative-review-template.html` into the batch's output folder as `review.html` (e.g. `outputs/YYYY-MM-DD/review.html`).
2. Replace the `DATA` object with the real project — concepts, frames, copy, grounding. Populate `image` paths for any frames you've rendered (keep them relative to the html file so the folder stays portable).
3. Verify it renders: open it in a browser, click through every concept tab, both platform and handle toggles, and each frame in the storyboard.
4. Deliver: hand off the folder (html + `images/`), or host it. For a client link, `vercel deploy` or any static host works — it's a single page with local assets.

Keep the review page next to the markdown outputs, not instead of them: `INDEX.md` and the per-concept files remain the operator's record and the grounding audit trail; `review.html` is the approval surface built on top.

## Common mistakes

- **Too many concepts** — 2–4 tabs is a decision; 10 is a menu nobody finishes. Curate before you present.
- **Unlabeled or content-labeled frames** — label by narrative job (`The proof`), not by what's pictured (`Table screenshot`).
- **Missing or dishonest grounding** — every concept discloses what's real; illustrative proof is labeled illustrative.
- **Editing the render code** — everything is data-driven; if something won't show, it's a `DATA` field, not the JS.
- **Absolute image paths** — keep image paths relative so the output folder can be zipped, moved, or hosted intact.


---

# references/creative-roadmap.md

# The Creative Strategy Loop

Generation (Modes 1–3) answers "make me ads." This reference answers the question that comes first: **which ads are worth making, in what order, at what production cost** — and the retro that turns each month's results into next month's plan. It's the standing operating loop of a creative strategist, run by an agent with a human deciding.

```
Signals → Concepts (evidence-ranked) → Roadmap (tiered, capacity-checked) → Briefs → [Modes 1–3 produce] → Monthly retro → back into the icebox
```

---

## Step 1: Read the Three Signals

Creative direction comes from synthesis across three independent signal sources. One source alone misleads: the account tells you what worked *among things you've tried*, customers tell you why they buy *in their words*, and organic content tells you what the audience *chooses to watch when nobody's paying*.

| Signal | What to pull | How |
|---|---|---|
| **Account performance** | Winners/losers by angle, hook, format; funnel metrics per concept (see [hook-system.md](hook-system.md) diagnostic funnel); fatigue state | `google-ads` / `meta-ads` / `linkedin-ads` / `tiktok-ads` CLIs (see Tool Integrations in SKILL.md) |
| **Customer/brand** | Verbatim pain/desire/objection language; unexpected use cases; who's *actually* buying vs. who's targeted | The Grounded Inputs corpus (`inputs/reviews/`, `inputs/comments/`), sales-call notes, support themes — per **customer-research** |
| **External organic** | What the niche watches unpaid: top organic content, its hooks, formats, vocabulary; competitor ads running long enough to be presumed working | **scraping**, the social listening tooling in **social**, ad libraries, **competitor-profiling** |

**Cadence:** a monthly deep dive (60–90 min, all three sources, feeds the monthly roadmap) plus a weekly ~20-minute refresh (what changed: new winners/losers, new review themes, anything spiking organically). Research beyond what the next decision needs is busywork — every synthesis session should end in concepts, not notes.

**Trust rule:** every insight the agent surfaces must carry its receipt — which review, which ad's metrics, which organic post. An insight without a source doesn't enter the icebox. (Same grounding rules as everything else in this skill.)

---

## Step 2: Turn Signals into Evidence-Ranked Concepts

A **concept** is one testable creative hypothesis: *segment × motivation × angle × format*, with its evidence attached. "UGC for moms" is not a concept; "new-parent insomniacs (per 40+ reviews mentioning 3am feeds) × 'quiet enough to not wake the baby' × before/after demo × POV night-shot video" is.

Rank every concept by the strongest evidence supporting it:

| Tier | Evidence | Weight |
|---|---|---|
| 1 | Your own account: a converting ad with the same angle/segment | Strongest — iterate and extend |
| 2 | Your customers verbatim: recurring review/call language | Strong — build new creative on it |
| 3 | Competitor creative running 60+ days (presumed working) | Good — adapt the angle, never the ad |
| 4 | Organic engagement in the niche (unpaid views/saves on the theme) | Moderate — validate cheaply first |
| 5 | Cross-niche pattern (worked in an adjacent category) | Weak — icebox until corroborated |
| 6 | Team hunch, no external signal | Weakest — low-fi test or drop |

Higher evidence earns roadmap *priority* — an earlier slot in the slate. Production tier is a separate call, set by validation strength, existing assets, capacity, and risk: even a tier-2 customer-language concept starts low-fidelity until it shows a funnel signal. Hunches aren't banned — they're just cheap and last.

---

## Step 3: Branch on Account State

The right creative mix depends on which of two states the account is in. Diagnose before roadmapping — a plan built for the wrong state wastes the month.

**Exploration state** — nothing (or nothing new) is working:
- Go **wide, not deep**: mostly net-new concepts across different segments and angles; keep iterations to a small minority — iterating on losers multiplies losers
- **Redefine "win" per-metric**: with no full-funnel winners, a single-metric improvement (a hold-rate lift, a CPC drop, a CVR bump) on any test is a hit worth pulling on — see the diagnostic funnel
- Iterate **only on hits**; everything else stays exploratory
- Common root causes to check while testing: the creative is boring (safe, seen-before), the message is overcomplicated, the offer/UVP is unclear, or CPMs are punishing a too-narrow audience

**Scaling state** — one or more concepts are converting profitably:
- Go **deep on the winner** while it's open: a winner-led slate of visually-distinct variations of the winning concept (same message, new execution — near-duplicates mostly cannibalize the original's reach and teach you nothing new, so variations must look meaningfully different), plus a remix lane (tonal/emotional re-executions of it) and sub-angle probes drilling *into* the winning segment; tune the split to budget, fatigue speed, and production velocity
- Keep a small exploration allocation alive even mid-scale — winners fatigue, and the next winner is rarely an iteration of the current one
- Speed matters more in this state: a scaling window is finite

---

## Step 4: The Roadmap Artifact

Maintain one living document (suggested: `roadmap.md` beside the Grounded Inputs corpus) with three horizons:

```
## Icebox        — every concept, evidence tier + source attached, nothing scheduled
## This quarter  — 2-4 themes chosen from the icebox (the bets), with why-now
## This month    — the slate: concept | evidence tier | production tier | owner | status
```

Each monthly-slate concept gets a **production tier**:

| Tier | Cost | What it is | Use for |
|---|---|---|---|
| **T1 — Iteration** | Hours | New hook/caption/crop on an existing asset | Extending proven winners |
| **T2 — Remix** | Days | New creative from existing footage/assets/AI generation | Concepts with decent evidence or a first low-fi signal |
| **T3 — Production** | Weeks | Net-new shoot, creators, full build | Only angles with own-account proof or a prior low-fi funnel signal (fidelity ladder in [hook-system.md](hook-system.md)) |

**Capacity check — the rule that keeps roadmaps honest:** count what the team (or the AI pipeline) can produce *at quality* this month, and roadmap to that number. A 20-concept slate against 8 concepts of real capacity doesn't produce 20 ads; it produces 20 compromised ones and a burned-out team. Cut by evidence rank until the slate fits.

From the slate, generate **one brief per concept** (segment, motivation + verbatim source, angle, format, hook matrix rows, production tier, success metric) and hand each to Modes 1–3 for production.

---

## Step 5: The Monthly Creative Retro

Last step of the loop, first input of the next one. One artifact per month (suggested: `retros/YYYY-MM.md`):

```
## Winners     — concept, the funnel numbers, and the WHY (which element earned it)
## Losers      — concept, where in the funnel it died, hypothesis for why
## Metric wins — full-funnel losers with one strong metric (these are leads, not losses)
## Learnings   — pattern-level notes → written back into the icebox as new/revised concepts
## Kills       — concepts retired from the icebox, with reason
## Next slate  — first draft of next month, updated evidence ranks
```

Retro rules:

- **Judge concepts, not ads.** Three executions of one concept failing says the concept is wrong; one failing says the execution was.
- **Read the funnel, not the ROAS column.** The diagnostic funnel says *what* to fix; ROAS alone says only *that* something is broken.
- **Enough data before verdicts** — respect the impression/spend thresholds in Common Mistakes and the **ads** skill's decision systems; a two-day read is a coin flip.
- **Every learning lands somewhere**: icebox update, evidence re-rank, or kill. A retro that changes nothing in the roadmap was a meeting, not a retro.

To run this loop on a schedule (retro on the 1st, weekly refresh Mondays, daily batches via Mode 3), see the creative loops in **marketing-loops**.

---

## Failure Modes

- **Roadmapping without a diagnosis** — a slate built before reading the three signals is a wish list; testing without a diagnosis isn't strategy
- **Iteration-heavy slates in exploration state** — polishing losers while the real problem (angle, offer, audience) goes untested
- **Ignoring capacity** — the plan the team can't produce at quality is a plan to produce slop
- **Evidence-free concepts jumping the queue** — the loudest stakeholder's hunch ships as a T3 shoot while tier-2 customer language sits in the icebox
- **Retro as theater** — winners celebrated, nothing re-ranked, icebox untouched
- **Scaling-state complacency** — 100% of the slate on winner variations; when the winner fatigues, the pipeline is empty


---

# references/generative-tools.md

# Generative AI Tools for Ad Creative

Reference for using AI image generators, video generators, and code-based video tools to produce ad visuals at scale.

---

## When to Use Generative Tools

| Need | Tool Category | Best Fit |
|------|---------------|----------|
| Static ad images (banners, social) | Image generation | ChatGPT Images 2.0, Nano Banana Pro, Flux, Ideogram |
| Ad images with text overlays | Image generation (text-capable) | Ideogram, Nano Banana Pro |
| Short video ads (6-30 sec) | Video generation | Veo, Kling, Runway, Sora, Seedance |
| Video ads with voiceover | Video gen + voice | Veo/Sora (native), or Runway + ElevenLabs |
| Voiceover tracks for ads | Voice generation | ElevenLabs, OpenAI TTS, Cartesia |
| Multi-language ad versions | Voice generation | ElevenLabs, PlayHT |
| Brand voice cloning | Voice generation | ElevenLabs, Resemble AI |
| Product mockups and variations | Image generation + references | Flux (multi-image reference) |
| Templated video ads at scale | Code-based video | Remotion |
| Personalized video (name, data) | Code-based video | Remotion |
| Brand-consistent variations | Image gen + style refs | Flux, Ideogram, Nano Banana Pro |

---

## Image Generation

### Nano Banana Pro (Gemini)

Google DeepMind's image generation model, available through the Gemini API.

**Best for:** High-quality ad images, product visuals, text rendering
**API:** Gemini API (Google AI Studio, Vertex AI)
**Pricing:** ~$0.04/image (Gemini 2.5 Flash Image), ~$0.24/4K image (Nano Banana Pro)

**Strengths:**
- Strong text rendering in images (logos, headlines)
- Native image editing (modify existing images with prompts)
- Available through the same Gemini API used for text generation
- Supports both generation and editing in one model

**Ad creative use cases:**
- Generate social media ad images from text descriptions
- Create product mockup variations
- Edit existing ad images (swap backgrounds, change colors)
- Generate images with headline text baked in

**API example:**
```bash
# Using the Gemini API for image generation
curl -X POST "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent" \
  -H "Content-Type: application/json" \
  -H "x-goog-api-key: $GEMINI_API_KEY" \
  -d '{
    "contents": [{"parts": [{"text": "Create a clean, modern social media ad image for a project management tool. Show a laptop with a kanban board interface. Bright, professional, 16:9 ratio."}]}],
    "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
  }'
```

**Docs:** [Gemini Image Generation](https://ai.google.dev/gemini-api/docs/image-generation)

---

### Flux (Black Forest Labs)

Open-weight image generation models with API access through Replicate and BFL's native API.

**Best for:** Photorealistic images, brand-consistent variations, multi-reference generation
**API:** Replicate, BFL API, fal.ai
**Pricing:** ~$0.01-0.06/image depending on model and resolution

**Model variants:**
| Model | Speed | Quality | Cost | Best For |
|-------|-------|---------|------|----------|
| Flux 2 Pro | ~6 sec | Highest | $0.015/MP | Final production assets |
| Flux 2 Flex | ~22 sec | High + editing | $0.06/MP | Iterative editing |
| Flux 2 Dev | ~2.5 sec | Good | $0.012/MP | Rapid prototyping |
| Flux 2 Klein | Fastest | Good | Lowest | High-volume batch generation |

**Strengths:**
- Multi-image reference (up to 8 images) for consistent identity across ads
- Product consistency — same product in different contexts
- Style transfer from reference images
- Open-weight Dev model for self-hosting

**Ad creative use cases:**
- Generate 50+ ad variations with consistent product/person identity
- Create product-in-context images (your SaaS on different devices)
- Style-match to existing brand assets using reference images
- Rapid A/B test image variations

**Docs:** [Replicate Flux](https://replicate.com/black-forest-labs/flux-2-pro), [BFL API](https://docs.bfl.ml/)

---

### Ideogram

Specialized in typography and text rendering within images.

**Best for:** Ad banners with text, branded graphics, social ad images with headlines
**API:** Ideogram API, Runware
**Pricing:** ~$0.06/image (API), ~$0.009/image (subscription)

**Strengths:**
- Best-in-class text rendering (~90% accuracy vs ~30% for most tools)
- Style reference system (upload up to 3 reference images)
- 4.3 billion style presets for consistent brand aesthetics
- Strong at logos and branded typography

**Ad creative use cases:**
- Generate ad banners with headline text directly in the image
- Create social media graphics with branded text overlays
- Produce multiple design variations with consistent typography
- Generate promotional materials without needing a designer for each iteration

**Docs:** [Ideogram API](https://developer.ideogram.ai/), [Ideogram](https://ideogram.ai/)

---

### Other Image Tools

| Tool | Best For | API Status | Notes |
|------|----------|------------|-------|
| **DALL-E 3** (OpenAI) | General image generation | Official API | Integrated with ChatGPT, good text rendering |
| **Midjourney** | Artistic, high-aesthetic images | No official public API | Discord-based; unofficial APIs exist but risk bans |
| **Stable Diffusion** | Self-hosted, customizable | Open source | Best for teams with GPU infrastructure |

---

## Video Generation

### Google Veo

Google DeepMind's video generation model, available through the Gemini API and Vertex AI.

**Best for:** High-quality video ads with native audio, vertical video for social
**API:** Gemini API, Vertex AI
**Pricing:** ~$0.15/sec (Veo 3.1 Fast), ~$0.40/sec (Veo 3.1 Standard)

**Capabilities:**
- Up to 60 seconds at 1080p
- Native audio generation (dialogue, sound effects, ambient)
- Vertical 9:16 output for Stories/Reels/Shorts
- Upscale to 4K
- Text-to-video and image-to-video

**Ad creative use cases:**
- Generate short video ads (15-30 sec) from text descriptions
- Create vertical video ads for TikTok, Reels, Shorts
- Produce product demos with voiceover
- Generate multiple video variations from the same prompt with different styles

**Docs:** [Veo on Vertex AI](https://cloud.google.com/vertex-ai/generative-ai/docs/video/overview)

---

### Kling (Kuaishou)

Video generation with simultaneous audio-visual generation and camera controls.

**Best for:** Cinematic video ads, longer-form content, audio-synced video
**API:** Kling API, PiAPI, fal.ai
**Pricing:** ~$0.09/sec (via fal.ai third-party)

**Capabilities:**
- Up to 3 minutes at 1080p/30-48fps
- Simultaneous audio-visual generation (Kling 2.6)
- Text-to-video and image-to-video
- Motion and camera controls

**Ad creative use cases:**
- Longer product explainer videos
- Cinematic brand videos with synchronized audio
- Animate product images into video ads

**Docs:** [Kling AI Developer](https://klingai.com/global/dev/model/video)

---

### Runway

Video generation and editing platform with strong controllability.

**Best for:** Controlled video generation, style-consistent content, editing existing footage
**API:** Runway Developer Portal

**Capabilities:**
- Gen-4: Character/scene consistency across shots
- Motion brush and camera controls
- Image-to-video with reference images
- Video-to-video style transfer

**Ad creative use cases:**
- Generate video ads with consistent characters/products across scenes
- Style-transfer existing footage to match brand aesthetics
- Extend or remix existing video content

**Docs:** [Runway API](https://docs.dev.runwayml.com/)

---

### Sora 2 (OpenAI)

OpenAI's video generation model with synchronized audio.

**Best for:** High-fidelity video with dialogue and sound
**API:** OpenAI API
**Pricing:** Free tier available; Pro from $0.10-0.50/sec depending on resolution

**Capabilities:**
- Up to 60 seconds with synchronized audio
- Dialogue, sound effects, and ambient audio
- sora-2 (fast) and sora-2-pro (quality) variants
- Text-to-video and image-to-video

**Ad creative use cases:**
- Video testimonials and talking-head style ads
- Product demo videos with narration
- Narrative brand videos

**Docs:** [OpenAI Video Generation](https://platform.openai.com/docs/guides/video-generation)

---

### Seedance 2.0 (ByteDance)

ByteDance's video generation model with simultaneous audio-visual generation and multimodal inputs.

**Best for:** Fast, affordable video ads with native audio, multimodal reference inputs
**API:** BytePlus (official), Replicate, WaveSpeedAI, fal.ai (third-party); OpenAI-compatible API format
**Pricing:** ~$0.10-0.80/min depending on resolution (estimated 10-100x cheaper than Sora 2 per clip)

**Capabilities:**
- Up to 20 seconds at up to 2K resolution
- Simultaneous audio-visual generation (Dual-Branch Diffusion Transformer)
- Text-to-video and image-to-video
- Up to 12 reference files for multimodal input
- OpenAI-compatible API structure

**Ad creative use cases:**
- High-volume short video ad production at low cost
- Video ads with synchronized voiceover and sound effects in one pass
- Multi-reference generation (feed product images, brand assets, style references)
- Rapid iteration on video ad concepts

**Docs:** [Seedance](https://seed.bytedance.com/en/seedance2_0)

---

### Higgsfield

Full-stack video creation platform with cinematic camera controls.

**Best for:** Social video ads, cinematic style, mobile-first content
**Platform:** [higgsfield.ai](https://higgsfield.ai/)

**Capabilities:**
- 50+ professional camera movements (zooms, pans, FPV drone shots)
- Image-to-video animation
- Built-in editing, transitions, and keyframing
- All-in-one workflow: image gen, animation, editing

**Ad creative use cases:**
- Social media video ads with cinematic feel
- Animate product images into dynamic video
- Create multiple video variations with different camera styles
- Quick-turn video content for social campaigns

---

### Video Tool Comparison

| Tool | Max Length | Audio | Resolution | API | Best For |
|------|-----------|-------|------------|-----|----------|
| **Veo 3.1** | 60 sec | Native | 1080p/4K | Gemini | Vertical social video |
| **Kling 2.6** | 3 min | Native | 1080p | Third-party | Longer cinematic |
| **Runway Gen-4** | 10 sec | No | 1080p | Official | Controlled, consistent |
| **Sora 2** | 60 sec | Native | 1080p | Official | Dialogue-heavy |
| **Seedance 2.0** | 20 sec | Native | 2K | Official + third-party | Affordable high-volume |
| **Higgsfield** | Varies | Yes | 1080p | Web-based | Social, mobile-first |

---

## Voice & Audio Generation

For layering realistic voiceovers onto video ads, adding narration to product demos, or generating audio for Remotion-rendered videos. These tools turn ad scripts into natural-sounding voice tracks.

### When to Use Voice Tools

Many video generators (Veo, Kling, Sora, Seedance) now include native audio. Use standalone voice tools when you need:

- **Voiceover on silent video** — Runway Gen-4 and Remotion produce silent output
- **Brand voice consistency** — Clone a specific voice for all ads
- **Multi-language versions** — Same ad script in 20+ languages
- **Script iteration** — Re-record voiceover without reshooting video
- **Precise control** — Exact timing, emotion, and pacing

---

### ElevenLabs

The market leader in realistic voice generation and voice cloning.

**Best for:** Most natural-sounding voiceovers, brand voice cloning, multilingual
**API:** REST API with streaming support
**Pricing:** ~$0.12-0.30 per 1,000 characters depending on plan; starts at $5/month

**Capabilities:**
- 29+ languages with natural accent and intonation
- Voice cloning from short audio clips (instant) or longer recordings (professional)
- Emotion and style control
- Streaming for real-time generation
- Voice library with hundreds of pre-built voices

**Ad creative use cases:**
- Generate voiceover tracks for video ads
- Clone your brand spokesperson's voice for all ad variations
- Produce the same ad in 10+ languages from one script
- A/B test different voice styles (authoritative vs. friendly vs. urgent)

**API example:**
```bash
curl -X POST "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}" \
  -H "xi-api-key: $ELEVENLABS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Stop wasting hours on manual reporting. Try DataFlow free for 14 days.",
    "model_id": "eleven_multilingual_v2",
    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
  }' --output voiceover.mp3
```

**Docs:** [ElevenLabs API](https://elevenlabs.io/docs/api-reference/text-to-speech)

---

### OpenAI TTS

Simple, affordable text-to-speech built into the OpenAI API.

**Best for:** Quick voiceovers, cost-effective at scale, simple integration
**API:** OpenAI API (same SDK as GPT/DALL-E)
**Pricing:** $15/million chars (standard), $30/million chars (HD); ~$0.015/min with gpt-4o-mini-tts

**Capabilities:**
- 13 built-in voices (no custom cloning)
- Multiple languages
- Real-time streaming
- HD quality option
- Simple API — same SDK you already use for GPT

**Ad creative use cases:**
- Fast, cheap voiceover for draft/test ad versions
- High-volume narration at low cost
- Prototype ad audio before investing in premium voice

**Docs:** [OpenAI TTS](https://platform.openai.com/docs/guides/text-to-speech)

---

### Cartesia Sonic

Ultra-low latency voice generation built for real-time applications.

**Best for:** Real-time voice, lowest latency, emotional expressiveness
**API:** REST + WebSocket streaming
**Pricing:** Starts at $5/month; pay-as-you-go from $0.03/min

**Capabilities:**
- 40ms time-to-first-audio (fastest in class)
- 15+ languages
- Nonverbal expressiveness: laughter, breathing, emotional inflections
- Sonic Turbo for even lower latency
- Streaming API for real-time generation

**Ad creative use cases:**
- Real-time ad preview during creative iteration
- Interactive demo videos with dynamic narration
- Ads requiring natural laughter, sighs, or emotional reactions

**Docs:** [Cartesia Sonic](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest)

---

### Voicebox (Open Source)

Free, local-first voice synthesis studio powered by Qwen3-TTS. The open-source alternative to ElevenLabs.

**Best for:** Free voice cloning, local/private generation, zero-cost batch production
**API:** Local REST API at `http://localhost:8000`
**Pricing:** Free (MIT license). Runs entirely on your machine.
**Stack:** Tauri (Rust) + React + FastAPI (Python)

**Capabilities:**
- Voice cloning from short audio samples via Qwen3-TTS
- Multi-language support (English, Chinese, more planned)
- Multi-track timeline editor for composing conversations
- 4-5x faster inference on Apple Silicon via MLX Metal acceleration
- Local REST API for programmatic generation
- No cloud dependency — all processing on-device

**Ad creative use cases:**
- Free voice cloning for brand spokesperson across all ad variations
- Batch generate voiceovers without per-character costs
- Private/local generation when ad content is sensitive or pre-launch
- Prototype voice variations before committing to a paid service

**API example:**
```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"text": "Stop wasting hours on manual reporting.", "profile_id": "abc123", "language": "en"}'
```

**Install:** Desktop apps for macOS and Windows at [voicebox.sh](https://voicebox.sh), or build from source:
```bash
git clone https://github.com/jamiepine/voicebox.git
cd voicebox && make setup && make dev
```

**Docs:** [GitHub](https://github.com/jamiepine/voicebox)

---

### Other Voice Tools

| Tool | Best For | Differentiator | API |
|------|----------|---------------|-----|
| **PlayHT** | Large voice library, low latency | 900+ voices, <300ms latency, ultra-realistic | [play.ht](https://play.ht/) |
| **Resemble AI** | Enterprise voice cloning | On-premise deployment, real-time speech-to-speech | [resemble.ai](https://www.resemble.ai/) |
| **WellSaid Labs** | Ethical, commercial-safe voices | Voices from compensated actors, safe for commercial use | [wellsaid.io](https://www.wellsaid.io/) |
| **Fish Audio** | Budget-friendly, emotion control | ~50-70% cheaper than ElevenLabs, emotion tags | [fish.audio](https://fish.audio/) |
| **Murf AI** | Non-technical teams | Browser-based studio, 200+ voices | [murf.ai](https://murf.ai/) |
| **Google Cloud TTS** | Google ecosystem, scale | 220+ voices, 40+ languages, enterprise SLAs | [Google TTS](https://cloud.google.com/text-to-speech) |
| **Amazon Polly** | AWS ecosystem, cost | Neural voices, SSML control, cheap at volume | [Amazon Polly](https://aws.amazon.com/polly/) |

---

### Voice Tool Comparison

| Tool | Quality | Cloning | Languages | Latency | Price/1K chars |
|------|---------|---------|-----------|---------|----------------|
| **ElevenLabs** | Best | Yes (instant + pro) | 29+ | ~200ms | $0.12-0.30 |
| **OpenAI TTS** | Good | No | 13+ | ~300ms | $0.015-0.030 |
| **Cartesia Sonic** | Very good | No | 15+ | ~40ms | ~$0.03/min |
| **PlayHT** | Very good | Yes | 140+ | <300ms | ~$0.10-0.20 |
| **Fish Audio** | Good | Yes | 13+ | ~200ms | ~$0.05-0.10 |
| **WellSaid** | Very good | No (actor voices) | English | ~300ms | Custom pricing |
| **Voicebox** | Good | Yes (local) | 2+ | Local | Free (open source) |

### Choosing a Voice Tool

```
Need voiceover for ads?
├── Need to clone a specific brand voice?
│   ├── Best quality → ElevenLabs
│   ├── Enterprise/on-premise → Resemble AI
│   └── Budget-friendly → Fish Audio, PlayHT
├── Need multilingual (same ad, many languages)?
│   ├── Most languages → PlayHT (140+)
│   └── Best quality → ElevenLabs (29+)
├── Need free / open source / local?
│   └── Voicebox (MIT, runs on your machine)
├── Need cheap, fast, good-enough?
│   └── OpenAI TTS ($0.015/min)
├── Need commercially-safe licensing?
│   └── WellSaid Labs (actor-compensated voices)
└── Need real-time/interactive?
    └── Cartesia Sonic (40ms TTFA)
```

### Workflow: Voice + Video

```
1. Write ad script (use ad-creative skill for copy)
2. Generate voiceover with ElevenLabs/OpenAI TTS
3. Generate or render video:
   a. Silent video from Runway/Remotion → layer voice track
   b. Or use Veo/Sora/Seedance with native audio (skip separate VO)
4. Combine with ffmpeg if layering separately:
   ffmpeg -i video.mp4 -i voiceover.mp3 -c:v copy -c:a aac output.mp4
5. Generate variations (different scripts, voices, or languages)
```

---

## Code-Based Video: Remotion

For templated, data-driven video ads at scale, Remotion is the best option. Unlike AI video generators that produce unique video from prompts, Remotion uses React code to render deterministic, brand-perfect video from templates and data.

**Best for:** Templated ad variations, personalized video, brand-consistent production
**Stack:** React + TypeScript
**Pricing:** Free for individuals/small teams; commercial license required for 4+ employees
**Docs:** [remotion.dev](https://www.remotion.dev/)

### Why Remotion for Ads

| AI Video Generators | Remotion |
|---------------------|----------|
| Unique output each time | Deterministic, pixel-perfect |
| Prompt-based, less control | Full code control over every frame |
| Hard to match brand exactly | Exact brand colors, fonts, spacing |
| One-at-a-time generation | Batch render hundreds from data |
| No dynamic data insertion | Personalize with names, prices, stats |

### Ad Creative Use Cases

**1. Dynamic product ads**
Feed a JSON array of products and render a unique video ad for each:
```tsx
// Simplified Remotion component for product ads
export const ProductAd: React.FC<{
  productName: string;
  price: string;
  imageUrl: string;
  tagline: string;
}> = ({productName, price, imageUrl, tagline}) => {
  return (
    <AbsoluteFill style={{backgroundColor: '#fff'}}>
      <Img src={imageUrl} style={{width: 400, height: 400}} />
      <h1>{productName}</h1>
      <p>{tagline}</p>
      <div className="price">{price}</div>
      <div className="cta">Shop Now</div>
    </AbsoluteFill>
  );
};
```

**2. A/B test video variations**
Render the same template with different headlines, CTAs, or color schemes:
```tsx
const variations = [
  {headline: "Save 50% Today", cta: "Get the Deal", theme: "urgent"},
  {headline: "Join 10K+ Teams", cta: "Start Free", theme: "social-proof"},
  {headline: "Built for Speed", cta: "Try It Now", theme: "benefit"},
];
// Render all variations programmatically
```

**3. Personalized outreach videos**
Generate videos addressing prospects by name for cold outreach or sales.

**4. Social ad batch production**
Render the same content across different aspect ratios:
- 1:1 for feed
- 9:16 for Stories/Reels
- 16:9 for YouTube

### Remotion Workflow for Ad Creative

```
1. Design template in React (or use AI to generate the component)
2. Define data schema (products, headlines, CTAs, images)
3. Feed data array into template
4. Batch render all variations
5. Upload to ad platform
```

### Getting Started

```bash
# Create a new Remotion project
npx create-video@latest

# Render a single video
npx remotion render src/index.ts MyComposition out/video.mp4

# Batch render from data
npx remotion render src/index.ts MyComposition --props='{"data": [...]}'
```

---

## Choosing the Right Tool

### Decision Tree

```
Need video ads?
├── Templated, data-driven (same structure, different data)
│   └── Use Remotion
├── Unique creative from prompts (exploratory)
│   ├── Need dialogue/voiceover? → Sora 2, Veo 3.1, Kling 2.6, Seedance 2.0
│   ├── Need consistency across scenes? → Runway Gen-4
│   ├── Need vertical social video? → Veo 3.1 (native 9:16)
│   ├── Need high volume at low cost? → Seedance 2.0
│   └── Need cinematic camera work? → Higgsfield, Kling
└── Both → Use AI gen for hero creative, Remotion for variations

Need image ads?
├── Need text/headlines in image? → Ideogram
├── Need product consistency across variations? → Flux (multi-ref)
├── Need quick iterations on existing images? → Nano Banana Pro
├── Need highest visual quality? → Flux Pro, Midjourney
└── Need high volume at low cost? → Flux Klein, Nano Banana
```

### Cost Comparison for 100 Ad Variations

| Approach | Tool | Approximate Cost |
|----------|------|-----------------|
| 100 static images | Nano Banana Pro | ~$4-24 |
| 100 static images | Flux Dev | ~$1-2 |
| 100 static images | Ideogram API | ~$6 |
| 100 × 15-sec videos | Veo 3.1 Fast | ~$225 |
| 100 × 15-sec videos | Remotion (templated) | ~$0 (self-hosted render) |
| 10 hero videos + 90 templated | Veo + Remotion | ~$22 + render time |

### Recommended Workflow for Scaled Ad Production

1. **Generate hero creative** with AI (Nano Banana, Flux, Veo) — high-quality, exploratory
2. **Build templates** in Remotion based on winning creative patterns
3. **Batch produce variations** with Remotion using data (products, headlines, CTAs)
4. **Iterate** — use AI tools for new angles, Remotion for scale

This hybrid approach gives you the creative exploration of AI generators and the consistency and scale of code-based rendering.

---

## Platform-Specific Image Specs

When generating images for ads, request the correct dimensions:

| Platform | Placement | Aspect Ratio | Recommended Size |
|----------|-----------|-------------|-----------------|
| Meta Feed | Single image | 1:1 | 1080x1080 |
| Meta Stories/Reels | Vertical | 9:16 | 1080x1920 |
| Meta Carousel | Square | 1:1 | 1080x1080 |
| Google Display | Landscape | 1.91:1 | 1200x628 |
| Google Display | Square | 1:1 | 1200x1200 |
| LinkedIn Feed | Landscape | 1.91:1 | 1200x627 |
| LinkedIn Feed | Square | 1:1 | 1200x1200 |
| TikTok Feed | Vertical | 9:16 | 1080x1920 |
| Twitter/X Feed | Landscape | 16:9 | 1200x675 |
| Twitter/X Card | Landscape | 1.91:1 | 800x418 |

Include these dimensions in your generation prompts to avoid needing to crop or resize.


---

# references/hook-system.md

# The Hook System

The first three seconds decide whether the rest of the ad exists. Hooks are the highest-leverage unit of paid creative work — and hook *diversity* is what earns incremental learning: distinct hooks reach distinct pockets of the audience, while near-identical openings mostly re-test what you already know about the same one. This reference is a complete system for generating, diagnosing, and iterating hooks — not a list of one-liners.

Use it inside Mode 1/3 generation (hooks for new concepts), Mode 2 iteration (diagnosing why an ad underperforms), and the creative strategy loop in [creative-roadmap.md](creative-roadmap.md).

---

## A Hook Is Three Components, Not a Line

In video, the hook is the simultaneous combination of:

| Component | What it is | Job |
|---|---|---|
| **Visual action** | What is literally happening on screen in seconds 0–3 | Stop the thumb |
| **Spoken line** | The first words of VO or dialogue | Open the loop |
| **Caption text** | On-screen header/overlay text | Anchor the claim for sound-off viewers |

**The no-duplication rule:** the three components must complement, never repeat. If the VO says "I stopped paying $200/mo for my gym" while the caption reads "I stopped paying $200/mo" over a static talking head, two of the three slots are wasted. Strong hooks split the work — visual shows the cancellation email, VO says the line, caption names the alternative. When writing hooks, write all three columns explicitly; a hook spec with one column filled in is a third of a hook.

Static ads collapse this to two components (visual + headline) — the same rule applies: the headline must not caption the image.

---

## The Generation Pipeline

Work top-down; hooks written without the upstream steps read like everyone else's ads.

```
Segment → Motivation → Format → Hook (three components)
```

1. **Segment** — which specific buyer this hook addresses. Not the whole ICP: a slice with a shared situation (from the Grounded Inputs corpus: reviews, comments, sales-call language). The narrower the segment, the sharper the hook.
2. **Motivation** — the single pain, desire, or objection that moves this segment, in *their* words. Pull verbatim phrases from reviews and comments; the corpus language always outperforms marketing paraphrase.
3. **Format** — the delivery vehicle: street interview, POV selfie, screen recording, unboxing, side-by-side demo, text-on-screen static, founder-to-camera, reaction stitch. Pick the format *before* writing the line — the same motivation reads completely differently as a street-interview answer vs. a confession-to-camera.
4. **Hook** — now write the three components for this segment × motivation × format cell.

**Output as a hook matrix** so coverage is visible:

```
| # | Segment | Motivation (verbatim source) | Format | Visual action | Spoken line | Caption |
```

Generate across the matrix, not down a single column — ten hooks for ten segment×motivation cells beat thirty rewordings of one cell. This is the same angle-diversity principle as the static template library: matrix diversity is audience diversity.

---

## Hook Opening Moves

A menu of proven opening structures. Cycle through them like the static templates — don't cluster on favorites:

| Move | Shape | Watch out |
|---|---|---|
| **Curiosity gap** | Withhold the noun: "Nobody tells you what actually causes this" | Must pay off within the ad or it's clickbait that poisons CVR |
| **Bold claim** | A specific, falsifiable statement: "This replaced my entire morning routine" | Needs substantiation on screen or in the on-ramp |
| **First-person confession** | "I was doing [common thing] completely wrong" | Reads fake without lived-in detail |
| **Contrast / before-after** | Two states shown or named in the first beat | The transformation must be visually honest — see compliance notes in SKILL.md |
| **Relatability / POV** | Mirror a hyper-specific situation: "POV: it's 3pm and you're on your fourth coffee" | Specificity is the entire mechanic; generic POV is invisible |
| **Question** | Ask the exact question the buyer types into search or ChatGPT | Use their phrasing verbatim from the corpus |
| **Countdown / gamified** | A timer or on-screen challenge that promises a payoff at the end | Payoff must exist; hold-rate collapses on cheats |
| **Proof-first** | Lead with the receipt — the result screenshot, the stat, the demo money-shot | Strongest when the proof brags by itself |

---

## The Diagnostic Funnel

Each metric in the delivery funnel isolates a different component. When an ad underperforms, read the funnel to find *which part* to fix instead of scrapping the whole ad:

| Stage | Metric | If it's weak, the problem is | Fix |
|---|---|---|---|
| Stop | Thumbstop / 3-sec view rate | **Visual action** (and caption) | New visual opening; same everything else |
| Stay | Hold rate (3s → 15s / 50% view) | **The on-ramp** — what follows the hook | Rework seconds 3–15, not the hook |
| Click | CTR | Desire/offer clarity mid-ad | Sharpen the promise, CTA, or proof |
| Convert | CVR post-click | Congruence — the page doesn't continue the ad | Fix the landing page or the claim, per **cro** |

Two rules this table enforces:

- **A great thumbstop is not a great ad.** A clickbait visual that attracts the wrong viewers shows up as high thumbstop + collapsed hold/CVR. Read the whole funnel before declaring a winning hook.
- **One component per iteration.** Change the visual OR the on-ramp OR the offer framing per test cycle — matching the one-variable rule in Common Mistakes.

---

## The On-Ramp Rule

The on-ramp is seconds ~3–15: the bridge from hook to body. **A good on-ramp logically extends the hook's premise; a bad one pivots to a product pitch that abandons it.** If the hook promises "what actually causes this," the next beat must start explaining the cause — not introduce the brand story.

Corollary: **every hook test is also an on-ramp test.** Swapping a new hook onto an existing ad body usually breaks the premise-bridge; when testing hooks, re-write the on-ramp to match each one. Hold rate is the on-ramp's metric — diagnose it separately from thumbstop.

---

## Fidelity Laddering

Match production cost to evidence strength (production tiers are defined in [creative-roadmap.md](creative-roadmap.md)):

- **Hunches ship low-fidelity within a day or two:** statics, text-on-screen video, voiceover-over-b-roll, remixes of existing footage. The goal is a cheap signal on the *angle*, not a polished ad.
- **Validated angles earn high-fidelity:** creator shoots, street interviews, staged demos. Only spend production budget on hooks whose low-fi version already showed a funnel signal (even a single-metric win — a hold-rate spike on an ugly static is evidence).

Testing a hunch with an expensive shoot and testing a proven angle with a throwaway static are both mistakes — the ladder runs in one direction.

---

## Grounding Rules (inherited, non-negotiable)

Hooks inherit every grounding rule from SKILL.md: every hook cites the corpus source its motivation came from; no invented claims, stats, or testimonials; verbatim customer language over paraphrase. Additionally, mine **organic content in the niche** (top-performing TikToks/Reels/posts, via the **scraping** skill or the social listening tooling in **social**) for the audience's actual vocabulary — the words the niche uses ("GLP-1" vs. the clinical term, the slang for the pain) belong in the caption and spoken line. Organic mining is language research, not copying: take the vocabulary and the visual conventions, never a creator's specific creative.

---

## Common Failure Modes

- **Thirty rewordings of one cell** — variation without matrix coverage; diversity of segment×motivation is the point
- **Components duplicating each other** — three slots saying one thing
- **Hook tested, on-ramp inherited** — premise-bridge broken, hold rate blamed on the hook
- **Funnel read stops at thumbstop** — clickbait winners scale into CVR craters
- **Polished hunches** — high-fidelity production spent on unvalidated angles
- **Marketing-voice captions** — the corpus and the niche's organic content define the vocabulary; "revolutionary formula" appears in neither


---

# references/imessage-video-ads.md

# iOS-Native Reveal Video Ads (iMessage, ChatGPT, Apple Notes, AirDrop)

A family of 9:16 social-native video formats that recreate a familiar iOS surface in real time and let the brand emerge inside it. The flagship is the **iMessage chat reveal** — someone sends a screenshot of a result or product, a friend reacts and asks what it is, and the conversation reveals the brand, usually with a promo code. Message bubbles pop in over ~15–22 seconds with authentic send/receive sounds, then a static brand end card lands the CTA. The same architecture powers **ChatGPT reveals**, **Apple Notes reveals**, and **AirDrop reveals** — covered in [Other iOS-Native Reveal Surfaces](#other-ios-native-reveal-surfaces) below.

The format works because it borrows the most-read UI on earth. A chat thread is a familiar, high-attention dramatization — it mirrors how real recommendations happen, so the viewer leans in instead of scrolling past. The CTA arrives conversationally ("use code FREEPACK") instead of as a hard sell, which keeps the ad-skip reflex from firing until the pitch has already landed. Run it only as a clearly labeled paid placement (Meta's "Sponsored" tag does the disclosure work); never seed it organically as if it were a real leaked conversation.

Credit: this reference distills the format popularized by Shiv Sakhuja and the Gooseworks team ([@shivsakhuja](https://x.com/shivsakhuja), [gooseworks-ai/gooseworks-ads-skills](https://github.com/gooseworks-ai/gooseworks-ads-skills)), who report the format performing strongly on Meta.

---

## When to Use This Format

**Good fit:**
- Reaction/discovery ads where the punchline is the recipient's curiosity ("wait, what app is that?")
- Promo-code offers — the conversational delivery feels far less ad-like than a code on a slate
- Products with a screenshot-able result: a number, a dashboard, a receipt, a before/after
- UGC-style angles when you don't have UGC creators on tap

**Poor fit:**
- Considered B2B purchases where a casual text exchange undercuts credibility
- Products with nothing visual or numeric to screenshot (fix the hook first, not the format)
- Brands whose compliance review can't approve dramatized conversations (regulated industries — check first)

**Platform fit:** Built for Meta Reels/Stories placements (9:16, 1080×1920) with a 1:1 center-crop variant for feed. Works on TikTok and YouTube Shorts with the same master file.

---

## Compliance and Grounding

This is a **dramatization** — a scripted conversation, not a real one. That's a standard, legitimate ad device, but two rules keep it honest and on the right side of FTC guidance:

1. **Every claim in the thread must be true of the product.** The race time, the savings math, the "5 minutes a day" — ground each one in a real customer result, review, or verifiable product fact, exactly as the Grounded Inputs rules in SKILL.md require. The conversation is fictional; the facts inside it can't be.
2. **Don't present the thread as a real testimonial.** No real customer names, no "this is an actual text from a customer" framing, no fabricated endorsements. The format persuades through recognizability, not through pretending to be found footage.

If a claim needs a disclaimer on your landing page, it needs one on this ad too.

---

## Concept Angles

Most iMessage ads fit one of six angles. Pick the angle before writing any copy — the most common failure mode ("script is fine but the ad feels off") is an angle mismatch, not bad lines. The strongest hooks share one of three traits: a specific number, a small act of self-trust, or a physically novel product mechanic.

| Angle | The hook attachment | The reveal |
|---|---|---|
| **Result-as-screenshot** | A number that brags by itself — race time, app summary, dashboard stat | "X minutes a day. that's it." |
| **Setup flex** | A photo of your space — tiny apartment gym, race-kit corner, desk setup | "this is the whole setup" |
| **Cancellation moment** | A confirmation receipt — gym cancellation email, "subscription cancelled" page | "$X/mo → $Y/mo. do the math" |
| **Feature-as-punchline** | A short clip of the product mechanic in motion | The mechanic *is* the brand |
| **Friend-asks-friend (inverse)** | The *peer* opens with the wow — "how are you doing this 😭" | *You* reply with the brand |
| **Receipt-as-hook** | A mundane financial document — statement, App Store receipt | A small act of self-trust |

---

## Anatomy of the Ad

```
0:00  Hook attachment lands (the screenshot the whole chat is about)
      ↓ short reactions, 250–450ms apart ("bro no way" / "wait is that real")
0:06  The question — "what app is that??"
      ↓ typing indicator … then the brand-name reply
0:12  The pitch, in texting voice — one or two bubbles max
0:15  The code — "use FREEPACK, first pack's free" (code renders link-underlined)
0:17  Beat of silence, then the closer — "bet" / "ok downloading"
0:18  300ms crossfade → static brand end card: logo, code, tagline (~3s)
```

**Script rules:**

- **8–14 bubbles total.** Shorter reads thin; longer loses the scroll-past viewer.
- **Write in real texting voice.** Lowercase, fragments, one emoji max per message, no marketing adjectives. Read it aloud as two friends — any bubble that sounds like ad copy gets cut.
- **The brand appears once, late.** The thread is about the *result* until someone asks. Naming the brand in bubble two kills the reveal.
- **Pacing has rhythm, not a metronome.** One-word reactions fire 250–450ms apart; sentence replies get 600–900ms of air after them; leave ~600ms of silence before the final reaction so it lands.
- **Typing indicators go before sentence-length peer replies**, optional before short reactions. The indicator appearing is silent (see SFX rules below).
- **The promo code goes inside a bubble**, styled with iOS's link-detection underline, *and* on the end card. Conversational delivery first, reinforcement second.

---

## Production Routes

Three ways to produce it, in order of control:

### Route 1: Off-the-shelf skill (fastest)

Gooseworks distributes their pipeline as an installable agent skill — `npx gooseworks install --all`, then invoke the goose-ads skill from your agent. It handles rendering, recording, SFX, and stitching end to end. Use this to validate the format before building anything custom. (Their ads-skills source repo is public but carries no open-source license — treat it as reference reading, not code to vendor.)

### Route 2: Code-based pipeline (full control)

The architecture that produces a convincing result: render the chat as HTML/CSS mimicking the iMessage UI, drive the animation with a timeline script, record it headlessly with Playwright, and assemble audio + end card with ffmpeg.

1. **Script as data.** Store the thread as JSON: participants (peer name, initials, avatar color), ordered messages (`from`, `text`, attachment paths, typing-indicator flags), theme, header. The script is reviewable and re-renderable without touching code.
2. **Render the chat UI in HTML/CSS.** Dark theme reads most native. Two variants: full-bleed chat, or the chat inside an iPhone frame (status bar + Dynamic Island) over a brand-relevant background photo — the framed variant reads more native in-feed and is the better default.
3. **Animate with a timeline, record in ONE continuous session.** All bubbles exist in the DOM but hidden (`display: none` — not `opacity: 0`, or the thread pre-allocates space and never "grows"). A driver script walks a timeline array revealing each bubble, driving the composer, and auto-scrolling. Never record scene-by-scene and concat — every page reload causes a visible micro-flicker.
4. **Type the composer for every sent bubble.** The typed text must exactly equal the sent text (a mismatch reads fake on second watch). Pace ~12–15 chars/sec with ±30% per-character jitter so it feels like thumbs, not a script.
5. **Record at native output resolution.** Set both the Playwright `viewport` *and* `recordVideo.size` to 1080×1920 — if you omit `recordVideo.size`, Playwright records a scaled-down video by default. Recording small and upscaling ships soft, blurry bubble text.
6. **Layer audio with ffmpeg.** SFX cues computed deterministically from the same timeline that drove the recording, so sounds land exactly on bubble pops.
7. **Stitch: chat → 300ms crossfade → static end card.** ffmpeg's `xfade` requires both inputs to match in resolution, pixel format, and frame rate — render the end card to a fixed-frame MP4 at the same specs as the chat recording before fading. Export the 9:16 master plus a 1:1 center crop.

### Route 3: Remotion (templated scale)

Once a winning script structure emerges, rebuild it as a Remotion composition (see [generative-tools.md](generative-tools.md)) with the thread JSON as props. Then variations — new hooks, new codes, new personas — are data changes, not re-productions. Right move at the "we're testing 10 script variants a week" stage, not for the first ad.

---

## Craft Rules (the details that sell the illusion)

These are the difference between "feels like a real chat" and "feels like a mockup":

- **The real send/receive sounds, never generic notification sounds.** The iMessage feel is mostly the audio. BigSoundBank hosts recordings of Apple's message sounds under CC0: send whoosh (`bigsoundbank.com/UPLOAD/mp3/1313.mp3`, ~0.5s) and receive tritone (`bigsoundbank.com/UPLOAD/mp3/1111.mp3` — trim to ~1.4s with a 400ms fade). Normalize loud (≈ -9 LUFS) so they cut through the music. Note the recordings being CC0 doesn't mean Apple has licensed its sound marks or UI trade dress — this is standard practice in the format, but regulated brands and risk-averse legal teams should review the iMessage mimicry as a whole; a generic chat-app skin (neutral bubbles, non-Apple sounds) is the fallback that keeps the mechanic.
- **No sound on the typing indicator.** iOS is silent when someone starts typing. Play the receive sound only when the actual bubble replaces the dots. This is the single most common tell.
- **Music bed: quiet lofi/hip-hop instrumental.** ~30% volume, highpass around 60Hz to clear room for the SFX, fade out ~1.5s before the code reveal so the CTA lands in relative silence.
- **Static end card — no zoom, no Ken Burns drift.** The brand slate must land hard; a drifting end card reads as filler.
- **Real brand logo SVG on the end card, never CSS-styled text.** Font-approximated wordmarks look amateur even when close. Pull the official SVG from the brand's press kit, Wikimedia, or brandfetch.com.
- **Hook screenshots: mimic the real app's UI, don't AI-generate it.** AI-generated app UIs ship garbled chrome that reads as slop. Build a small HTML page copying the actual app's brand colors, typography, and layout conventions (the Strava-orange strip, the "Public · 2h ago" timestamp) and screenshot it. Reserve AI image generation for *photographic* hooks — a beach photo, a lifestyle shot, the framed variant's background.
- **Audio mixing gotcha:** ffmpeg's `amix` divides volume by input count by default — pass `normalize=0` or the whole mix comes out mysteriously quiet. Then run the mix through a limiter with the ceiling just under full scale (e.g. `alimiter=limit=0.95`, ≈ -0.4 dB) so it's loud without clipping.

---

## Quality Checklist

Before shipping:

- [ ] Every factual claim in the thread traces to a real review, result, or product fact (Grounded Inputs)
- [ ] Script reads as real texting voice when read aloud — no marketing adjectives in bubbles
- [ ] Brand name appears only after the peer asks
- [ ] No sound on any typing indicator; receive SFX fires when the text bubble lands
- [ ] SFX land exactly on bubble pops (spot-check first and last)
- [ ] Every sent bubble had a full composer drive; typed text equals sent text
- [ ] No micro-flicker anywhere in the chat — the only cut is chat → end card (300ms crossfade)
- [ ] Promo code is link-underlined in its bubble and repeated on the end card
- [ ] End card is static with the real logo SVG
- [ ] Master is native 1080×1920; 1:1 variant is a crop, not a squeeze
- [ ] Final bubble gets ~600–800ms of air before the crossfade
- [ ] Audio is limited just under full scale (no clipping); music never fights the SFX

---

## Iterating the Format

Treat the thread as the variable and the pipeline as fixed. Test in this order — hook first, everything else after:

1. **Hook attachment** — the screenshot is the thumbnail and the first 2 seconds; it decides the scroll-stop
2. **Angle** — result-flex vs. cancellation vs. inverse changes who the viewer identifies with
3. **Code reveal phrasing** — "first pack's free with FREEPACK" vs. "FREEPACK gets you one free"
4. **Peer persona** — name, avatar, and texting style shift the perceived audience
5. **Length** — try a 12-bubble and an 8-bubble cut of the same script

The same architecture extends to further surfaces too — WhatsApp, Slack, a search box — same timeline-driven recording, different UI shell.

---

## Other iOS-Native Reveal Surfaces

Everything above about production (UI mockup → timeline-driven continuous recording → deterministic SFX cues → static end card), grounding, and disclosure carries over unchanged. What changes per surface is the *persuasion mechanic* and a handful of craft details.

| Surface | Persuasion mechanic | Reach for it when |
|---|---|---|
| **iMessage** | A friend's recommendation — social proof through dialogue | The product is discovered through results people share ("what app is that?") |
| **ChatGPT** | An authoritative answer to the viewer's own question | The problem is question-shaped — something people would literally type into ChatGPT |
| **Apple Notes** | A private confession made public — first-person, no dialogue | The angle is transformation or realization ("things nobody told me about 45") |
| **AirDrop** | A spontaneous peer share — "someone nearby thought this was worth sending you *right now*," with a built-in accept/decline decision | The product is something people pass to each other (a deal, a link, a find, a file) and the accept-tap can *be* the reveal |

The strongest signal for choosing: which of these surfaces already fills your audience's day. Recommendation products want iMessage; advice-seeking problems want ChatGPT; identity/transformation stories want Notes; and anything people spontaneously pass to each other wants AirDrop.

### ChatGPT Reveal

The viewer identifies with the *asker*. The typed question is the hook and must be the target customer's verbatim question — awkward phrasing and all ("why is my stomach so bloated all of a sudden at 47?"). The streaming answer names the problem's real mechanism, then the solution category; the brand lands in the answer's recommendation or in a typed follow-up ("what's the best one?").

**Craft details:**
- **Stream the answer in word chunks**, not character-by-character (that's typing, not generation) and not whole paragraphs at once. A subtle tick underneath the stream and a clean stop when the response completes; no iMessage tritones anywhere.
- **Type the question like thumbs, stream the answer like a model.** Two distinct rhythms — the contrast is what reads as "real ChatGPT."
- **Keep the answer scannable:** short paragraphs, a bolded phrase or a short list, exactly the way ChatGPT actually formats. A wall of text breaks the illusion and loses the viewer.
- OpenAI's interface is their trade dress — same legal-review posture as the Apple UI mimicry note above, with a generic "AI assistant" skin as the fallback.

**Compliance — stricter here than anywhere else in this family.** The "answer" is your ad copy wearing a lab coat: an authority costume. Every claim in it needs the same substantiation as a claim in your own voice, and the format's borrowed authority raises the bar, not lowers it. Do not put health, medical, or financial advice in a fabricated AI answer without legal review — that's the highest-risk version of this format. And never present the exchange as a real, unprompted ChatGPT output endorsing your product; it's a dramatization, same as the iMessage thread.

### Apple Notes Reveal

A different genre from the chat formats: **confession, not conversation.** The viewer watches someone type a private note — a list of realizations, a "things I wish I knew" entry — with the keyboard visible. The note's title is the hook and does the job slide 1 does in a carousel ("Things nobody told me about 45."). The product appears as one item in the list, named the way a person would actually write it to themselves — not the way a brand would.

**Craft details:**
- **Audio is keyboard taps only.** No chat SFX, no receive tones — a note has no other party. A quiet music bed still works underneath.
- **Type at real thumb pace with jitter**, same as the iMessage composer rule. One typo-and-correction reads as human; several read as staged.
- **Get the Notes chrome right:** title styled larger than body, the formatting bar above the keyboard, iOS-yellow accents. Same HTML-mimicry approach — and the same Apple trade-dress review note and generic-notes-app fallback — as everything else here.
- **Fit the note to the frame.** Write short enough that the whole note fits without scrolling, or scroll once, deliberately, late.
- **First person or it doesn't work.** The moment the note reads like ad copy ("[Brand] changed everything!"), the intimacy that makes the format convert is gone. The product mention should be the *least* enthusiastic line in the note.

The grounding rule hits differently here: the confession is a dramatization of a *composite, true* customer story — pull the realizations from real reviews and interviews (the Grounded Inputs corpus), and keep any numbers or outcomes to documented ones.

### AirDrop Reveal

The one interaction-native format in the family: the hook is an **incoming AirDrop request**, and the **Accept tap is the reveal**. The viewer watches from the *receiver's* POV — a translucent AirDrop card slides up, "[Sender] would like to share [preview]," with a gray Decline and a blue Accept. The curiosity is structural ("what is this and who's sending it?") and the accept/decline choice is a built-in micro-conversion beat baked into iOS itself. Tapping Accept transfers the item — and *that's* where the product, the offer, or the result lands.

**Craft details:**
- **The preview thumbnail is the hook.** It's the one image on the AirDrop card before Accept, so it has to earn the tap — same job as the iMessage screenshot attachment. Make it the result, the product money-shot, or the offer.
- **Cast the sender name like a real share.** "Sarah's iPhone," "Mom," "Jordan's MacBook" reads native; a brand name in the sender slot reads like an ad — save brand-as-sender for the reveal, not the incoming card.
- **The transfer progress ring is the signature motion — don't skip it.** Incoming card → a beat of hesitation ("accept?") → the Accept tap → the circular progress fills → the item lands + end card. That progress-ring beat is what makes it read as a real AirDrop and not a cut.
- **Audio is the AirDrop swoosh / received tone**, not the iMessage tritones. Same CC0-Apple-sounds sourcing and the same Apple trade-dress review note as the rest of the family, with a generic "nearby share" skin as the fallback.
- **Keep it short and get the material right.** The card's blur/translucency and the gray Decline / blue Accept button pair are the recognizable cues; a flat opaque sheet breaks the illusion. The whole beat is faster than the chat formats — the interaction *is* the ad.
- **Receiver POV by default; sender POV as the flex.** Receiving reads as discovery ("someone sent me this"); sending reads as a recommendation you're making ("had to AirDrop this to the group") — use sender POV when the angle is advocacy rather than discovery.

Grounding is the same family rule: it's a dramatization of a share, not a claim that a real person actually AirDropped your product. Every claim on the transferred item is substantiated per the Grounded Inputs rules, and the exchange is never presented as a real, unprompted endorsement.


---

# references/meta-creative-formats.md

# Meta Creative Format Taxonomy — Which Format to Make Next

A prioritized S→F catalog of ~51 Meta ad creative formats, built as a **decision aid for "which format do I make next,"** not an encyclopedia. Use it to pick a format before you brief it, and to stop pouring hours into formats that structurally can't do the job you need.

Distilled from Dara Denney's public tier list (10 yrs on Meta, teams that shipped ~20,000 creatives), re-expressed in this skill's voice — patterns credited, descriptions not copied.

## The one question that ranks everything

For any format, ask: **is this a *unicorn scaler* or a *supporting cast member*?**

- **Unicorn scaler** — punctures *cold, net-new* audiences and holds up as you scale spend. These are rare and worth disproportionate investment.
- **Supporting cast** — converts people already in the mid/low funnel. Useful, necessary, but it will *not* open new audiences no matter how much you spend on it.

That distinction is the whole ranking. A format isn't "bad" for being supporting cast — it's bad only when you expect it to scale into cold audiences and it structurally can't. **Build a portfolio:** a few unicorn scalers doing the puncturing, a bench of supporting cast doing the converting.

## Why creator-fronted formats top the list (Andromeda)

Meta's **Andromeda algorithm is persona-based** — it targets *personas*, not just interests. Creator-fronted formats win because they reach a persona *natively*: through a creator that persona already follows and trusts. The seed audience for a partnership ad literally starts from the creator's own audience. That's why founder content, partnership ads, and authority ads dominate the top — the format is doing the targeting.

**Practical signal to watch:** track rolling month-over-month *reach*. When it falls, you've saturated your current audience — deploy creator-fronted formats (especially partnership ads) to restore net-new reach.

## Production complexity legend

- **Low** — copy + one asset; you can make it today (statics, founder's letter, text-driven).
- **Med** — needs a creator, a shoot, a script, or an edit (yapper, green-screen, VSL script).
- **High** — multi-party, rights, or heavy production (celebrity, warehouse shoot, AI animation, press).

---

## S-tier — unicorn scalers (invest here first)

| Format | Funnel role | Complexity | When to use / when to skip |
|---|---|---|---|
| **Founder content** | Cold scaler | Low–Med | The reliable *first* winner at any production level. Tell the story of *why* you built the brand — you auto-connect with same-problem buyers. **Use** early, when you have no proven creative yet. Rarely a skip. |
| **Partnership ads** | Cold scaler | Med | **#1 investment priority.** "Making or breaking brands on Meta right now"; not running them is "a butter knife to a gunfight." Best path to personas + net-new reach. **Use** always, and deploy when rolling reach drops. Skip only if you genuinely can't source creators. See #529. |
| **VSL (video sales letter)** | Cold scaler | Med–High | Top-tier for anything that needs upfront **education** — health, wellness, fitness, complex mechanisms. **Use** when the buyer must understand *why it works* before buying. **Skip** for impulse/low-consideration products. Build the copywriting craft; the script is the ad. |

**S-tier tactic:** when you contract creators for partnership ads, *also* have each shoot a few low-fi creator statics (how they'd post a Story for the brand). Builds a mini-funnel per creator for near-zero marginal cost.

---

## A-tier — scales up nicely

Cold-capable with the right inputs; the next tier to test once your S-tier is running.

| Format | Funnel role | Complexity | When to use / when to skip |
|---|---|---|---|
| **Amateur investigation** | Cold scaler | Med | A creator "investigates" your product/niche (e.g. visiting competitors). Fresh, high-engagement. **Use** in categories where skepticism is the barrier. |
| **Yapper ads** | Cold scaler | Med | Creator yaps to camera with personal storytelling. **High ceiling, hard to nail** — needs the *right* creator + script + setting. **Skip** if you can't cast well; a mediocre yapper flops. |
| **David & Goliath** | Cold-capable | Low–Med | Position the brand as David vs. a big incumbent/obstacle; storytelling makes people root for you. **Use** when there's a clear villain (legacy category, bloated competitor). |
| **Grid-style statics** | Cold-capable | Low | Multi-product / SKU / bundle grid. Easy to make, was a top performer at a 9-figure brand. **Lowest-hanging fruit to test** — make some this week. |
| **Authority ads** | Cold scaler | Med | A doctor/dermatologist/expert fronts it. **Use** in hyper-competitive, trust-gated niches (supplements, beauty). Adds validation + creative diversity beyond UGC. |
| **Green-screen commentary** | Cold-capable | Med | Creator composited over content, commenting. **Use** in apparel especially, with an educational angle. |
| **Catalog / DPA** | Cold-capable | Low–Med | **Under-used truth:** not just retargeting — can run top-of-funnel/cold prospecting (DABA). Most brands leave this on the table. **Use** with a real catalog; currently a top performer for some accounts. |

---

## B-tier — solid supporting cast

Convert mid-funnel reliably; occasionally sneak into the top rotation with great messaging. Don't expect them to open cold audiences. Most are **Low** complexity (statics) unless noted.

TikTok love letter · Real short *(top-of-funnel support, Med)* · Callout ads · Before/after *(mid-funnel; watch claims)* · Progression *(mid-funnel)* · Tweet/Reddit statics *(great as the **first frame**; good in the $100k–250k spend range)* · Headline ads *(OG print-era; needs **amazing** messaging, pairs with callouts)* · Us-vs-them *(mid-funnel; sneaks into the top 8)* · Hot-girl IG stories *(mirror selfies / flat-lays)* · Creator low-fi statics *(the partnership tactic above)* · Objection-handling *(works fast, often top-15)* · Founder's letter static *(cranks during sales)* · Conversation ads *(Med; hard to execute)* · Educational infographics *(masquerades as content; under-used)* · Mood board *(apparel)* · Comment-reply · Challenging-your-beliefs *(Med; needs B-roll + known persona beliefs)* · Ugly / handwriting / post-it *(crush during sales periods)*

---

## C-tier — situational / operationally complex

Can win in narrow conditions but cost more than they return for most accounts. Reach for these only when the specific condition applies.

AI animation *(Pixar/claymation; High — hits net-new pockets initially, rarely holds long-term)* · Statistics ads *(luxury/retail + awareness/traffic objectives, **not** D2C ROI)* · Celebrity *(High; can crank or be a money pit)* · AI avatar *(has scaled **with** legal disclaimers, but phasing out as brands pick real creators)* · Warehouse *(High; great for sales, complex to shoot)* · Street interview *(often better to **fake/recreate** than capture live)* · Duet/reaction/stitch *(needs rights from the original creator)* · ASMR *(pet/beauty; needs specific ASMR creators)* · Regular UGC *(still works, but **general fatigue** on manufactured problem-solution VO + B-roll UGC)*

---

## D-tier — rarely moves the needle

Breaking-news ads *(born to replace unreliable press)* · AI billboard *(overdone/cheesy; only lands with punchy/taboo language in supplements)* · GRWM / day-in-my-life *(organic-native; doesn't scale on paid unless the product fits a morning routine)*

---

## E-tier — mostly skip

Text-only *(usually executed with bland AI copy; exception: founder's letter during sales)* · Testimonial statics *(marketers execute them badly — only worth it with golden-nugget testimonials)* · Listicles *(worked a year or two ago, dead lately)* · Carousel *(juice rarely worth the squeeze — multiple assets, unknown payoff)*

---

## F-tier — don't bother

Explicitly de-prioritized. These aren't just weak — they cost real time/rights and reliably underperform.

- **Press ads** — a rights/permissions nightmare now (Vogue et al. will come after you). Was a champion format years ago; the ground shifted.
- **Podcast ads** — a waste unless a **founder is on an actually well-known show**. Renting a studio or AI-generating a fake podcast clip doesn't pay off.
- **Notes-app / UX fake-native ads** — everywhere on guru reels, but **they do not convert**. The familiar UI makes *everyone* stop, so they fail to qualify the right people and **confuse the algorithm**. Skip regardless of how tempting the "native" look is.

---

## Cross-cutting principles

- **Portfolio, not silver bullet.** Only founder / partnership / authority / investigation / VSL / grid-static reliably scale cold. Everything else is a converter — staff both roles.
- **Andromeda is persona-based** → creator-fronted formats win because the format *is* the targeting.
- **Fake it when honest capture is painful** — street interviews and duet reactions can be recreated; don't wait for the perfect real moment.
- **Fatigue is real** on over-taught formats (manufactured UGC, notes-app, AI billboards). **Freshness itself is an edge** — a novel-but-honest format out-punches a saturated "best practice."

---

## Where the details live

This file is the **format map** — priority and selection. The *how-to-build* lives elsewhere:

- **Static formats** (grid, us-vs-them, headline, callout, before/after, founder's letter, FAQ, tweet/Reddit, etc.) → structural templates with copy slots in [static-ad-templates.md](static-ad-templates.md).
- **Video formats** (VSL, yapper, green-screen, UGC reaction, faceless/motion, iOS-native reveals) → the vertical-video production spec + creator-format library in [short-form-video-specs.md](short-form-video-specs.md), the motion-style pipeline in [motion-video-ads.md](motion-video-ads.md), and the iOS-native reveals in [imessage-video-ads.md](imessage-video-ads.md).
- **Deciding which specific concepts to make** (evidence-ranked, account-state-aware) → the Creative Strategy Loop in [creative-roadmap.md](creative-roadmap.md).
- **Kill/keep/scale math** once these are live → `ads` skill's [meta-decision-system.md](../../ads/references/meta-decision-system.md).

*Tier list and the unicorn-vs-supporting-cast framing adapted from Dara Denney's "I Ranked 51 Meta Ad Creative Types (Tier List)"; yapper/investigation craft informed by Oren John. Patterns credited, descriptions re-expressed. Tiers reflect a point in time — Meta's algorithm and format fatigue shift; re-verify against current account data.*


---

# references/motion-video-ads.md

# Motion-Style Video Ads (Faceless, Fully Generated)

> Format popularized by Borja ([@borjafat](https://x.com/borjafat)) and the open `super-video-maker` motion-collage recipe by [Bomx](https://github.com/Bomx/super-video-maker-skill); this guide is an original re-expression of the method, extended with a multi-style library and production lessons from building and shipping it end-to-end.

Produce a 15–45s faceless video ad or explainer from nothing but a concept: a styled
poster still (image model) → brought to life with subtle motion (image-to-video model)
→ narrated (TTS) → word-timed captions. No footage, no presenter, no editor. Cost per
finished video is roughly $3–6 in API calls; wall-clock ~15 minutes.

The format works because the *still* carries the idea (one literal, slightly surreal
visual per beat) and the *motion* only makes it breathe. Resist the urge to make the
video do the storytelling — this is animated poster design, not filmmaking.

## When to use

- Concept/explainer ads: one idea made concrete ("your CRM is a junk drawer")
- Top-of-funnel social video (9:16 Reels/Shorts/TikTok, 4:5 and 1:1 feed)
- Brand-response hybrids where a distinctive owned style beats stock UGC
- NOT for: demo/proof ads (screen recordings win), testimonial/UGC formats,
  anything requiring a real product shot as evidence

## Pipeline (provider-agnostic)

1. **Script** 3–6 beats, 20–45s of VO. One idea per beat. Calm and specific beats
   hype. End on a single CTA line.
2. **Poster stills** — one per beat, using a *style formula* (below). Generate beat 1,
   approve it, then pass it as a reference image for every later beat so the set reads
   as one series. Fix garbled label text by regenerating with a shorter phrase.
3. **Animate** each approved still with an image-to-video model (5–8s per beat).
   Motion belongs to the objects in the frame; the composition must not change.
4. **VO + captions**: one continuous TTS take, transcribe with word timestamps
   (whisper), cut beats at sentence boundaries, burn 2–3-word caption groups.
5. **Assemble**: concat beats trimmed to their VO spans (hold the last frame to pad),
   loudness-normalize to `I=-16:TP=-1.5:LRA=11`, export per-placement aspect.

**Provider options** (any combination works; the recipe is model-agnostic):

| Stage | One-key Gemini path | Alternatives |
|---|---|---|
| Stills | Nano Banana Pro (`gemini-3-pro-image-preview`) — excellent label typography | GPT-Image, Flux, Ideogram |
| Motion | Veo 3.1 fast image-to-video (note: 1080p requires 8s clips) | Seedance 2.0 via fal.ai, Kling, Runway |
| VO | Gemini TTS (calm voices: Charon/Kore) | ElevenLabs, OpenAI TTS |
| Captions | whisper word timings + PIL/ASS burn-in | CapCut, platform auto-captions |

## The style library

Five proven looks. Each is a fill-in-the-slots prompt formula; keep ONE style per
campaign so the account builds a recognizable visual identity. All five animate well.

### A. Screen-print collage (editorial, "In a Nutshell" docu energy)
> Flat screen-print collage poster, single saturated `<COLOR>` background, subtle newsprint grain. Centerpiece: a black-and-white halftone cutout of `<SUBJECT DOING THE LITERAL CONCEPT>`, treated as a paper sticker with a thin white die-cut outline, slightly torn edges, and a soft drop shadow. Visible halftone dot texture, vintage editorial photo feel, grayscale subject. Accent cutouts: 2–4 flat shapes (cream circle sun, black zigzag, scattered dots). A torn-paper label near the bottom with the words "`<LABEL>`" in bold condensed uppercase newspaper type. Matte printed risograph aesthetic, limited palette. No gradients, no glow, no 3D, no photorealism, no extra text.

### B. Flat vector explainer (clean, techy, infinitely brandable)
> Flat vector explainer illustration in the style of a premium animated science channel: a friendly simplified `<SUBJECT>`, bold flat shapes with clean rounded edges, solid `<BRAND COLOR>` background, limited palette of `<2-3 ACCENTS>`, flat geometric accents, soft long shadows, completely flat 2D design. A clean rectangular banner near the bottom reads "`<LABEL>`" in bold geometric sans-serif uppercase. No outlines, no 3D, no photorealism, no texture, no extra text.

### C. Papercraft diorama (warm, tactile, premium-crafty)
> Layered papercraft diorama: `<SUBJECT>`, every element hand-cut from colored construction paper with visible paper thickness and real drop shadows between layers, `<COLOR>` paper background with cut-paper accents, tactile handmade craft feel with slightly imperfect scissor cuts. A cut-paper banner near the bottom reads "`<LABEL>`" in chunky cut-out paper letters. Soft studio lighting on the paper layers. No digital gradients, no photorealistic humans, no extra text.

### D. Pop-art comic (loud, scroll-stopping, promo-friendly)
> Vintage pop-art comic panel: `<SUBJECT>`, bold black ink outlines, Ben-Day halftone dots shading, flat process colors (`<PALETTE>`), comic starburst accents, thick panel border, aged newsprint paper texture. A comic caption box near the bottom reads "`<LABEL>`" in bold comic lettering. 1960s printed comic aesthetic, slight ink misregistration. No 3D, no photorealism, no gradients, no extra text.

### E. Claymation (charming, high pattern-interrupt)
> Stop-motion claymation scene: a charming handmade plasticine `<SUBJECT>`, visible fingerprints and clay texture, `<COLOR>` clay backdrop and floor, chunky clay props, warm soft studio lighting like a stop-motion film set, shallow depth of field. A small clay sign near the bottom reads "`<LABEL>`" in hand-molded clay letters. Handcrafted miniature feel. No 2D illustration, no photorealistic humans, no extra text.

## Brand-flexible styles (token-driven)

The five looks above are *characterful* — they impose their own palette. This second
tier is *brand-first*: each style is defined by *slots*, so any company's tokens drop
in and the output reads as that brand's own design system.

**The brand slots contract.** Before generating, resolve these from the brand's
guidelines (or `.agents/product-marketing.md`):

- `FIELD` — the neutral ground (brand white/off-white, or brand dark)
- `INK` — the drawing/type color (brand gray/charcoal, near-black)
- `ACCENT` — ONE brand color or gradient, used sparingly (a rule, a beam, a square)
- `TYPE FEEL` — the brand's typographic voice ("clean modern grotesque sans", "geometric sans", "mono captions")
- Any per-brand constraints (e.g. "gradients only on borders/edges, never fills")

Keep the accent genuinely scarce — one element per frame. Scarcity is what makes
these read as designed rather than generated.

### F. Monoline editorial (the most universally brandable)
> Minimal editorial monoline illustration poster: `<SUBJECT>`, drawn entirely in elegant thin single-weight `<INK>` lines on a clean `<FIELD>` background, the style of a premium tech company blog illustration. Sparse composition with generous whitespace, a few small monoline accent details, and ONE restrained `<ACCENT>` element: `<a thin accent underline sweep / a small accent arc>`. A small caption near the bottom reads "`<LABEL>`" in `<TYPE FEEL>`, `<INK>`, letterspaced uppercase, with a thin `<ACCENT>` underline. Precise, technical, refined. No fills except the single accent, no gradients, no 3D, no photorealism, no texture, no extra text.

### G. Swiss typographic (type IS the visual — any brand with a font and a color)
> Swiss International Typographic Style poster: the words "`<LABEL>`" set enormous in a bold `<TYPE FEEL>`, `<INK>` on a `<FIELD>` background, filling the upper two thirds with tight leading and cropped edges. A small black-and-white photographic cutout of `<SUBJECT>` sits on a thin baseline grid in the lower third, aligned to an asymmetric grid with one thin `<ACCENT>` rule line and a small `<ACCENT>` square as the only color. Visible faint grid lines, precise margins, mathematical composition. Flat, printed, matte. No gradients, no 3D, no decoration, no extra text beyond the label and one small letterspaced caption line.

### H. Wireglow (dark keynote — dev-tool / dark-mode brands)
> Dark minimal tech-keynote poster: `<SUBJECT>` rendered as an elegant thin light-gray wireframe line drawing on a near-black `<FIELD>` background with subtle film grain. From `<the focal object>` emanates a soft narrow beam of glowing `<ACCENT>` gradient light, the only color, feathered and atmospheric. Faint thin concentric geometric guide circles. A caption near the bottom reads "`<LABEL>`" in `<TYPE FEEL>`, light gray, letterspaced uppercase, with a hairline gradient rule beneath it. Restrained, premium, technical. No photorealism, no 3D render look, no busy elements, no extra text.

### I. Duotone screenprint (photo brands — editorial punch from two tokens)
> Bold duotone screenprint photo poster: a dramatic photograph of `<SUBJECT>`, reproduced as a two-color screenprint — `<INK>` for the shadows and `<ACCENT>` for the highlights — on an off-white `<FIELD>` paper background with visible coarse halftone grain and slight ink misregistration. Strong diagonal composition, the figure large and cropped. A wide solid `<INK>` bar near the bottom carries the words "`<LABEL>`" reversed out in bold condensed `<TYPE FEEL>` uppercase, with a small `<ACCENT>` square bullet. Editorial poster energy, matte printed feel. No gradients beyond the duotone, no 3D, no extra text.

**Motion notes for this tier**: F/G animate as drawing motions (lines extend, the accent
sweep draws itself, type settles by a few pixels); H animates as beam pulse + slow
wireframe rotation feel; I as grain shimmer + slow push. Same hard rules apply — motion
belongs to existing elements, composition never changes.

## Motion prompt formula

> Subtle living-`<style>` motion of the existing elements only. `<ONE literal motion tied to the concept: the pile inflates / the arrow creeps higher / the megaphone trembles with each shout>`. `<Secondary ambient motion: accents drift, gentle push-in>`. Every element that is visible now is the only thing that ever appears; the composition stays exactly as it is. Everything stays `<style descriptor: a flat printed collage / flat 2D vector / cut paper / printed comic / handmade clay>`. No camera whip, no scene change, no morphing, no added text.

## Hard-earned gotchas

- **Video models love adding photoreal "maker hands"** reaching into frame, especially
  on pressing/handling motions — and *negative prompts make it worse* ("no hands" is an
  attention trap). Never mention hands; describe motion as belonging to the objects,
  and include "the composition stays exactly as it is."
- **Always QC each clip's final 2 seconds** — that's where intruding objects and style
  drift appear. Trim before them or regenerate; never ship a "realified" frame.
- **One dominant motion per beat.** Two motions read as chaos at feed speed.
- **TTS + whisper disagree on sound-alikes** ("laws" → "loss"). Read the transcript
  against the script before burning captions; prefer phoneme-unambiguous CTA wording.
- **Keep captions clear of the label band** (captions ~60% height, label ~80%).
  Clamp caption groups so two never overlap; shrink-to-fit long groups.
- **Ad-specific**: put the brand/label in the poster itself (it survives sound-off
  autoplay), front-load the concept in beat 1 (the 3-second hook is the poster), and
  export 9:16 + 4:5 + 1:1 from the same beats by regenerating stills per aspect
  rather than cropping.

## Compliance

Fully synthetic characters — no likeness/UGC disclosure issues, but check platform
AI-content disclosure requirements (Meta and TikTok label AI-generated media).
Don't fabricate statistics or testimonials in the VO; ground every claim.


---

# references/platform-specs.md

# Platform Specs Reference

Complete character limits, format requirements, and best practices for each ad platform.

---

## Google Ads

### Responsive Search Ads (RSAs)

| Element | Character Limit | Required | Notes |
|---------|----------------|----------|-------|
| Headline | 30 chars | 3 minimum, 15 max | Any 3 may be shown together |
| Description | 90 chars | 2 minimum, 4 max | Any 2 may be shown together |
| Display path 1 | 15 chars | Optional | Appears after domain in URL |
| Display path 2 | 15 chars | Optional | Appears after path 1 |
| Final URL | No limit | Required | Landing page URL |

**Combination rules:**
- Google selects up to 3 headlines and 2 descriptions to show
- Headlines appear separated by " | " or stacked
- Any headline can appear in any position unless pinned
- Pinning reduces Google's ability to optimize — use sparingly

**Pinning strategy:**
- Pin your brand name to position 1 if brand guidelines require it
- Pin your strongest CTA to position 2 or 3
- Leave most headlines unpinned for machine learning

**Headline mix recommendation (15 headlines):**
- 3-4 keyword-focused (match search intent)
- 3-4 benefit-focused (what they get)
- 2-3 social proof (numbers, awards, customers)
- 2-3 CTA-focused (action to take)
- 1-2 differentiators (why you over competitors)
- 1 brand name headline

**Description mix recommendation (4 descriptions):**
- 1 benefit + proof point
- 1 feature + outcome
- 1 social proof + CTA
- 1 urgency/offer + CTA (if applicable)

### Performance Max

| Element | Character Limit | Notes |
|---------|----------------|-------|
| Headline | 30 chars (5 required) | Short headlines for various placements |
| Long headline | 90 chars (5 required) | Used in display, video, discover |
| Description | 90 chars (1 required, 5 max) | Accompany various ad formats |
| Business name | 25 chars | Required |

### Display Ads

| Element | Character Limit |
|---------|----------------|
| Headline | 30 chars |
| Long headline | 90 chars |
| Description | 90 chars |
| Business name | 25 chars |

---

## Meta Ads (Facebook & Instagram)

### Single Image / Video / Carousel

| Element | Recommended | Maximum | Notes |
|---------|-------------|---------|-------|
| Primary text | 125 chars | 2,200 chars | Text above image; truncated after ~125 |
| Headline | 40 chars | 255 chars | Below image; truncated after ~40 |
| Description | 30 chars | 255 chars | Below headline; may not show |
| URL display link | 40 chars | N/A | Optional custom display URL |

**Placement-specific notes:**
- **Feed**: All elements show; primary text most visible
- **Stories/Reels**: Primary text overlaid; keep under 72 chars
- **Right column**: Only headline visible; skip description
- **Audience Network**: Varies by publisher

**Best practices:**
- Front-load the hook in primary text (first 125 chars)
- Use line breaks for readability in longer primary text
- Emojis: test, but don't overuse — 1-2 per ad max
- Questions in primary text increase engagement
- Headline should be a clear CTA or value statement

### Lead Ads (Instant Form)

| Element | Limit |
|---------|-------|
| Greeting headline | 60 chars |
| Greeting description | 360 chars |
| Privacy policy text | 200 chars |

---

## LinkedIn Ads

### Single Image Ad

| Element | Recommended | Maximum | Notes |
|---------|-------------|---------|-------|
| Intro text | 150 chars | 600 chars | Above the image; truncated after ~150 |
| Headline | 70 chars | 200 chars | Below the image |
| Description | 100 chars | 300 chars | Only shows on Audience Network |

### Carousel Ad

| Element | Limit |
|---------|-------|
| Intro text | 255 chars |
| Card headline | 45 chars |
| Card count | 2-10 cards |

### Message Ad (InMail)

| Element | Limit |
|---------|-------|
| Subject line | 60 chars |
| Message body | 1,500 chars |
| CTA button | 20 chars |

### Text Ad

| Element | Limit |
|---------|-------|
| Headline | 25 chars |
| Description | 75 chars |

**LinkedIn-specific guidelines:**
- Professional tone, but not boring
- Use job-specific language the audience recognizes
- Statistics and data points perform well
- Avoid consumer-style hype ("Amazing!" "Incredible!")
- First-person testimonials from peers resonate

---

## TikTok Ads

### In-Feed Ads

| Element | Recommended | Maximum | Notes |
|---------|-------------|---------|-------|
| Ad text | 80 chars | 100 chars | Above the video |
| Display name | N/A | 40 chars | Brand name |
| CTA button | Platform options | Predefined | Select from TikTok's options |

### Spark Ads (Boosted Organic)

| Element | Notes |
|---------|-------|
| Caption | Uses original post caption |
| CTA button | Added by advertiser |
| Display name | Original creator's handle |

**TikTok-specific guidelines:**
- Native content outperforms polished ads
- First 2 seconds determine if they watch
- Use trending sounds and formats
- Text overlay is essential (most watch with sound off)
- Vertical video only (9:16)

---

## Twitter/X Ads

### Promoted Tweets

| Element | Limit | Notes |
|---------|-------|-------|
| Tweet text | 280 chars | Full tweet with image/video |
| Card headline | 70 chars | Website card |
| Card description | 200 chars | Website card |

### Website Cards

| Element | Limit |
|---------|-------|
| Headline | 70 chars |
| Description | 200 chars |

**Twitter/X-specific guidelines:**
- Conversational, casual tone
- Short sentences work best
- One clear message per tweet
- Hashtags: 1-2 max (0 is often better for ads)
- Threads can work for consideration-stage content

---

## Character Counting Tips

- **Spaces count** as characters on all platforms
- **Emojis** count as 1-2 characters depending on platform
- **Special characters** (|, &, etc.) count as 1 character
- **URLs** in body text count against limits
- **Dynamic keyword insertion** (`{KeyWord:default}`) can exceed limits — set safe defaults
- Always verify in the platform's ad preview before launching

---

## Multi-Platform Creative Adaptation

When creating for multiple platforms simultaneously, start with the most restrictive format:

1. **Google Search headlines** (30 chars) — forces the tightest messaging
2. **Expand to Meta headlines** (40 chars) — add a word or two
3. **Expand to LinkedIn intro text** (150 chars) — add context and proof
4. **Expand to Meta primary text** (125+ chars) — full hook and value prop

This cascading approach ensures your core message works everywhere, then gets enriched for platforms that allow more space.


---

# references/short-form-video-specs.md

# Short-Form Vertical Video — Production Spec & Creator Formats

The platform-craft layer beneath any 9:16 video for TikTok, Reels, or Shorts — the constraints that decide whether a good idea survives contact with the feed — plus a tiered library of creator/UGC and founder formats that consistently perform for growth and paid.

Part 1 (the spec) applies to **every** vertical video this skill produces — the iMessage reveals in [imessage-video-ads.md](imessage-video-ads.md), the motion ads in [motion-video-ads.md](motion-video-ads.md), and the creator formats below. Part 2 is the format library.

---

## Part 1 — The Vertical Video Spec

### Canvas
- **1080×1920 (9:16), 30fps, MP4.** Footage of any resolution/orientation is center-cropped to fill (`object-fit: cover`) — mixed source resolutions are fine.

### Safe zones (the single most-missed constraint)
Platform UI covers the frame edges — the action rail, caption stack, music button, and account row all sit *on top of* your video. Text or key visuals in those bands get covered. Keep everything inside the **cross-platform safe band** — the worst case of TikTok and IG Reels margins on a 1080×1920 canvas:

| Edge | Keep clear | Why |
|---|---|---|
| **Top** | 220px | TikTok tabs + IG account row |
| **Bottom** | 500px | Caption / music / CTA stack (both platforms) |
| **Left** | 180px | Symmetry with right |
| **Right** | 180px | Action rail (like/comment/share/music) |

**Result: a 720×1200 centered text band, from y=220 to y=1420.** Compose all captions and load-bearing visuals inside it. Preview against a safe-zone overlay before a big push. (These numbers drift with app updates — re-verify occasionally; they're a well-sourced worst-case, not a permanent law.)

### Caption style (classic TikTok)
White fill, black outline, **no background pill** — the native look that reads as organic, not as an ad:

```css
color: #fff;
font-family: "TikTok Sans", sans-serif;  /* or a close variable sans; embed it, don't assume it's installed */
font-weight: 700;
paint-order: stroke fill;                  /* stroke behind fill — keeps glyphs crisp */
-webkit-text-stroke: 8px #000;
text-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
```

- **Captions are static** — no entrance/exit transitions. A caption is at full visibility on the first frame of its window, and its window matches its video segment exactly (same start, same end). Animated captions read as "made by a brand."
- **Auto-size to fit the band.** Start at ~58px and shrink in ~2px steps until the text fits the safe band (fit box ~1150px tall), floor ~26px. Never overflow the band, never clip mid-glyph. Long wall-of-text hooks are a *supported* input, not a failure case — they just shrink. Re-measure after the font actually loads (`document.fonts.ready`) so sizing uses the real face, not a fallback.

### Audio defaults (and the organic-vs-baked decision)
- **Mute clip audio by default; let one music track carry the sound.** Per-clip audio is opt-in (e.g., keep a creator's voice at full, mute B-roll).
- **Fade music out over the final ~0.8s** — a hard cut to silence reads as broken.
- **The organic call:** for organic TikTok/Reels, often post **without baked-in music** and attach the trending sound *in-app* — the platform's algorithm rewards native/trending audio, and an in-app sound is discoverable/attachable by others. **Bake the music in** for paid ads and anywhere you can't attach a native sound (some cross-posting, some platforms). This one decision meaningfully affects organic reach.

### Determinism (if you generate programmatically)
Renders must be reproducible: no clocks (`Date.now()`), no `Math.random()`, no network fetches at render time. Same inputs → same MP4, every time. (Applies whether you're on Remotion, HyperFrames, or an ffmpeg pipeline — see the `video` skill for framework choice.)

---

## Part 2 — Creator Format Library

UGC- and creator-driven short-form formats that reliably perform for growth and paid. Each is a *structure*, not a script — feed it your own footage and hook. All obey Part 1.

**Tiers** rank a format on one axis: does it *scale a cold ad into net-new audiences* (a "unicorn scaling" format), or does it just *convert people already in mid/low funnel* (a "supporting cast" format)? **S** = the rare formats that both scale cold and carry heavy education. **A** = scales up well. **B** = solid supporting cast under the right conditions. **C** = situational or operationally complex (rights, specific talent, or better faked than captured). Build a *portfolio* across tiers — don't expect every format to scale. Meta's persona-based delivery is why creator-fronted formats (Yapper, Investigation, Authority, VSL) rank so high: they reach personas natively through the creators those personas already follow. For the full 51-format taxonomy and where each sits, see [meta-creative-formats.md](meta-creative-formats.md) (companion reference) and the tier/portfolio logic in [ads/references/meta-decision-system.md](../../ads/references/meta-decision-system.md).

### Format 1 — Reaction + Demo (hard cut) · A
**Shape:** creator reaction clip with a hook caption → **hard cut** to an app/product demo screen recording. ~9–12s total.

```
[ reaction · ~3s · hook caption ] → [ demo · full length · optional payoff caption ]
```

- **When:** you have (or can get) a genuine-feeling creator reaction and a crisp demo. The workhorse UGC format for apps/tools.
- **The hook caption** rides the reaction segment and does all the selling — it's the ad. Write it as the reaction's inner monologue ("i was about to hit it and this app talked me out of it"), not a product claim.
- **The hard cut is the mechanic** — no transition. Reaction earns attention, cut delivers the payoff. Optional second caption on the demo lands the result ("12/12 cravings resisted").
- Sourcing: real UGC reactions are the input bottleneck; the format is only as good as the reaction's authenticity.

### Format 2 — "No Yapping" Split-Screen Tutorial · B
**Shape:** silent, fast tutorial. Fullscreen intro → **50/50 split** (typing/action on one half, live result on the other), step captions at the seam. The "…but no yapping" promise = pure value, no talking.

```
[ intro · fullscreen · hook ] → [ split: input | output · ordered step captions at the seam ]
```

- **When:** a how-to where *showing* beats *narrating* — setup flows, prompt walkthroughs, tool tutorials. The silence is the selling point (people watch muted; "no yapping" filters for high-intent).
- **Captions carry the steps** — ordered, static, one per beat, placed at the split seam so both halves stay visible. Auto-size per Part 1.
- No voiceover; music-only (see the organic-sound note). Pace tight — dead air kills retention.

### Format 3 — Greenscreen Reaction · A
**Shape:** one video plays fullscreen; the creator is **cut out of their background** (greenscreen/segmentation) and composited on top — reacting to or narrating over the underlying content. Optionally start centered, then shrink/drag into a corner so the underlying video takes over.

```
[ fullscreen video (e.g. a screen recording / another post) + creator cutout overlay · optional hook text ]
```

- **When:** reacting to a competitor's post, a trend, a screen recording, or your own product — the TikTok-native "let me react to this" format. Reads as commentary, which the algorithm and audience treat as organic.
- **Both soundtracks can coexist** (underlying video + creator), unlike the mute-by-default rule — the reaction voice is the point here.
- The corner-drag move (creator starts big to establish presence, then shrinks to let the content breathe) is the signature beat.

### Format 4 — Yapper · A
**Shape:** one creator talks straight to camera, telling a personal story that lands on your product. No cuts required — the story *is* the ad. ~20–60s.

```
[ creator talking to camera · hook line first · personal story → product as the resolution ]
```

- **When:** you have the *right* creator (a person who reads as one level above the viewer, excited and specific) and a *scripted* story with a real narrative arc. Hard to nail — needs creator + script + setting all working — but scales into cold audiences when it lands.
- **Mechanics:** open on a strong take or a story hook ("I almost cancelled this app three times"), not a product claim. Structure as hook → story → the product entering as the turn, never as a feature list. Captions on (Part 1 style); low-fi setting (car, walk, one spot) reads native. Flat energy kills it — the delivery carries the format.
- Casting is the bottleneck: the format fails on the wrong creator far more than on the wrong script.

### Format 5 — Amateur Investigation · A
**Shape:** a creator "investigates" your product, niche, or a question on the viewer's behalf — visiting places, comparing options, testing claims. The discovery arc is the retention engine.

```
[ creator sets up the question · goes and investigates (real footage) · lands on your product as the finding ]
```

- **When:** your product wins on comparison or holds up to scrutiny — the investigation earns the recommendation instead of asserting it. Scales cold because it plays as content, not an ad.
- **Mechanics:** frame a genuine question ("are dealership warranties actually worth it?"), let the creator do legwork on camera, and let your product surface as the *conclusion the investigation reached* — not a sponsor slot. Real-world capture (locations, comparisons) is the credibility.

### Format 6 — David & Goliath · A
**Shape:** position the brand as the underdog (David) against a big industry, incumbent, or broken status quo (Goliath). Root-for-you storytelling.

```
[ name the Goliath (the villain / broken norm) · the brand's fight against it · why you win / how you're different ]
```

- **When:** you have a real antagonist — a bloated incumbent, an industry practice that rips people off, a category default that's worse than yours. The story makes the viewer *want* you to win.
- **Mechanics:** make the Goliath concrete and the stakes emotional; the brand's origin ("we built this because X was broken") powers it. Pairs naturally with founder delivery. Don't manufacture a villain that isn't real — the format lives or dies on a genuine antagonist.

### Format 7 — Authority · A
**Shape:** a credentialed expert — doctor, dermatologist, engineer, practitioner — presents or endorses the product on the strength of their expertise.

```
[ expert on camera (credentials clear) · the problem in their domain · why this product is the right answer ]
```

- **When:** hyper-competitive, trust-gated niches (supplements, skincare, health, anything regulated) where a credential does the persuading UGC can't. Adds validation and creative diversity beyond creator UGC.
- **Mechanics:** the expert must be real and the claims must be true and substantiated — this format sits closest to regulatory risk. Route health/medical/financial claims through legal review; never fabricate credentials or put words in an expert's mouth. Follows the skill's Grounded Inputs rules strictly.

### Format 8 — VSL (Video Sales Letter) · S
**Shape:** long-form (60s to several minutes) direct-response video that educates before it sells — problem → mechanism → proof → offer.

```
[ hook + problem · why it happens (the mechanism) · the solution + proof · the offer + CTA ]
```

- **When:** the sale needs *upfront education* — health, wellness, fitness, finance, anything where the buyer must understand the mechanism before they'll convert. One of the few formats that both scales cold and carries heavy teaching, hence S-tier.
- **Mechanics:** the craft is in the script — a tight problem hook, a believable mechanism, stacked proof, and a clear offer. Retention is engineered beat by beat (open loops, "but here's the thing" turns). Captions throughout; a real person or voiceover-over-broll both work. This is a writing discipline first — invest in the script.

### Format 9 — Green-Screen Commentary · A
**Shape:** the creator talks *over* full-frame imagery — screenshots, product shots, charts, a competitor's page — pairing an educational take with the visual it references. (Distinct from Format 3's reaction: this is a *teaching* overlay, not a reaction to a post.)

```
[ creator cutout + full-frame reference imagery behind them · educational narration keyed to what's on screen ]
```

- **When:** apparel, and anything with an educational angle where *showing the thing while explaining it* beats talking alone. Reads as commentary/teaching, which delivery treats as organic.
- **Mechanics:** swap the background imagery to match each beat of the narration (the visual should always illustrate the current point). Creator voice carries; keep the take genuinely useful, not a disguised pitch.

### Format 10 — Conversation · B
**Shape:** two people in a real exchange — interview, dialogue, back-and-forth — where the product surfaces naturally in the conversation.

```
[ two people talking · a real question/answer exchange · product enters as part of the dialogue ]
```

- **When:** you can stage a genuine-feeling two-person dynamic and the product fits a natural conversational moment. Solid supporting cast; converts more than it scales cold.
- **Mechanics:** hard to execute — the chemistry and the naturalness are the whole thing; scripted-sounding dialogue kills it. Best when the exchange surfaces a real objection and answers it in-flow.

### Format 11 — Duet / Reaction · C (rights needed)
**Shape:** react to, duet, or stitch another creator's video — your commentary alongside or after their clip.

```
[ original creator's clip · your reaction / duet / stitch responding to it ]
```

- **When:** there's a specific post worth responding to and it earns net-new pockets of audience. Situational.
- **Mechanics:** **you need rights** from the original creator to use their footage in a paid ad — this is the operational gate, not the creative. Without cleared rights, don't run it as an ad.

### Format 12 — ASMR · C
**Shape:** sensory-forward, sound-led video — tapping, unboxing, application, texture — with the product as the sensory object.

```
[ close-up sensory action · product-forward · ASMR audio carries (no VO) ]
```

- **When:** pet, beauty, food, or tactile products where the sensory experience *is* the appeal. Situational and needs the right ASMR-native creator.
- **Mechanics:** breaks the mute-by-default rule — the audio is the point; capture it clean. Requires talent who actually shoots ASMR; a generalist creator can't fake the sensory craft.

### Format 13 — Street Interview · C ("often better to fake")
**Shape:** person-on-the-street questions — real or recreated — capturing candid reactions to your product or category question.

```
[ on-the-street setup · question to passersby · candid answers → your angle ]
```

- **When:** you want the credibility of unscripted public reaction. Situational and operationally heavy to capture honestly.
- **Mechanics:** honest capture is painful (releases, dead takes, weather, luck), so this format is **often better staged/recreated** with the same visual language — the recreated version is faster, controllable, and reads the same. If you do stage it, keep the claims real (Grounded Inputs still apply).

### Founder / Organic Vlog Structures

For **founder-led video ads** and organic-native brand content, four narrative structures (Oren John) give a founder something to *say*, and a shooting + edit system makes it fast to produce. These aren't a separate tier — they're the story arc *inside* a Yapper, Investigation, or vlog. Founder's content is typically a brand's *first* top performer: telling the story of *why* you built the brand auto-connects with same-problem buyers.

**The four structures (pick the arc, then shoot to it):**
- **Hero's journey** — run whatever's happening in the business through: problem → backstory → attempt → failure → epiphany → breakthrough → cliffhanger. The reframe matters more than the events. Lets you post *less* — one great story-vlog a week can beat daily content because people follow the journey. (For this arc specifically, it's fine to run the raw situation through an LLM *for the outline only* — feed brand/persona context, ask for a 60–90s hero's-journey outline — then write the words yourself.)
- **Math** — money as the lever: a cost breakdown or a fixed-budget challenge ("$200 on Meta ads — here's what happened"). *Unexpectedly cheap* outperforms expensive; the affordability question creates intrinsic curiosity. Don't use luxury as the hook — it doesn't scale and reads as a flex.
- **Shiny object** — anchor on something visually novel the viewer hasn't seen and that you have *access* to (your factory, a machine, a craft process, a trade show). Never money/luxury as the shiny object.
- **Niche guide with expertise** — narrate the real world through your professional lens ("what I'd avoid as an interior designer," filmed in the store). A *learner* POV works too — just be honest which you are. Getting out into the world is the cheat code while everyone else yaps in their car.

**The three-capture shooting system** (makes any of the above fast):
- Film every moment **three ways — close / medium / wide (0.5x)** — to maximize usable footage from any moment.
- **2–3 second clips only** — many small clips, never long roaming takes (easy timeline assembly).
- **Motion rule:** if the subject is moving, hold the phone static; if nothing's moving, add a slow push-in or side-slide.
- Do the activity first, then run back through at the end (~5 min) grabbing three angles of 10–12 things — less interrupting.
- One phone folder per trip; **favorite your single best "hook shot"** so the opener is pre-chosen. Get **≥5 shots of yourself** — you're the through-line.

**The 0.5–1s cut formula** (the edit): every shot is **0.5–1 second** — a 45-second voiceover becomes ~45 one-second shots. Record the voiceover/talk track first, lay clips under it, reorder, trim. Cut in CapCut or Instagram's Edits app — don't reach for Premiere/DaVinci. This cut cadence is the vlog-speed cousin of Format 1's hard cut, and it's what makes the footage read as energetic rather than slow.

---

*Vertical-video spec (safe-zone band, caption recipe, auto-sizing, organic-vs-baked audio) and the first three creator formats are distilled from Daniel Hangan's `reelclaw-templates` (built on HeyGen's HyperFrames; TikTok Sans redistributed under SIL OFL 1.1) — patterns credited, no code vendored. The tiered format library (Yapper, Investigation, David & Goliath, Authority, VSL, and the tier logic) is adapted from Dara Denney's Meta creative-type tier list; the founder / organic-vlog structures, three-capture shooting system, and 0.5–1s cut formula are adapted from Oren John's vlog + yapping playbooks — sources credited, expressed originally. Safe-zone numbers are a cross-platform worst case; re-verify against current app UI. For framework/tooling choices to actually render these, see the `video` skill.*


---

# references/static-ad-templates.md

# Static Ad Template Library

Structural templates for static (image) ad creative. Each is a layout framework with slots for brand-specific copy — the structure is proven; the inputs make it yours.

Use these when generating static ad concepts at volume (Meta, Instagram, LinkedIn, display). Cycle through **all** templates rather than clustering on 2-3 favorites: template diversity is angle diversity, and the winner is usually not the one you'd have picked by hand.

## Unicorn Scaler vs. Supporting Cast (read tiers this way)

Each template carries a **tier (S–F)** and a **funnel role**, distilled from Dara Denney's ranking of 51 Meta creative formats. The organizing question behind the tiers isn't "does it work" but **"is this a *unicorn scaler* that punctures net-new cold audiences, or a *supporting-cast member* that converts people already in mid/low-funnel?"**

- **Unicorn scalers** (S/A) reliably scale into cold, net-new audiences. Only a handful do this — reach for these first when you need fresh reach.
- **Supporting cast** (B/C) mostly convert mid-funnel. This is not a demotion: a B-tier template can still be your best converter for warm traffic. **Don't kill a good supporting-cast format for failing to scale cold — that was never its job.** Build a portfolio.
- **Decayed** (D–F) formats have fatigued, carry rights/compliance risk, or "do not convert" anymore. Flagged inline so you don't waste a batch on them.

Read tiers as *priority-of-reach*, not *quality*. When cold-scaling is the goal, weight the batch toward S/A. When feeding mid-funnel and retargeting, the B-tier supporting cast is exactly right.

The tiers here cover **statics only**. For the full S–F map across *all* Meta creative formats — including the video/UGC/partnership formats that dominate the top of the ranking (partnership ads, VSLs, yapper ads, authority ads) — see `references/meta-creative-formats.md`, the format map. This library is the static slice of that larger picture.

## How to Use This Library

1. **Ground first.** Read the inputs corpus (winning ads, reviews, ad comments, brand voice) before generating anything. See "Grounded Inputs" in SKILL.md.
2. **Cycle templates, weighted by tier.** For a batch of N concepts, spread across the full template set. When the goal is cold net-new reach, weight toward the S/A tiers (Founder Message, Origin Story, Grid Static); when feeding mid-funnel and retargeting, the B-tier supporting cast is exactly right. Skip the decayed D–F formats unless you have a specific reason.
3. **Fill slots from source material.** Every variation pulls its copy from a real review, a winning ad pattern, or an ad comment — and cites which one.
4. **Write the visual description.** Each concept includes enough visual direction that a designer or image-generation tool can produce it without guessing.

## Generation Rules

- Every variation must include: **template name, headline copy, body copy, visual description, source grounding**
- Source grounding = which review, winning ad, or comment this concept is based on
- Never produce a variation without source grounding — no invented claims, stats, or testimonials
- Pull copy directly from customer language whenever possible; don't paraphrase reviews into marketing-speak
- Match the brand voice doc on tone, not generic direct-response voice
- Real names, real stats, real quotes only — fabricated social proof is a compliance and trust violation

---

## The Templates

Each template is tagged **Tier** (S–F priority-of-reach) and **Role** (cold-scaler vs. supporting cast). See the framing note above.

### 1. Headline Statement

Bold one-line claim. Single product hero shot. Minimal background. The headline does all the work.

- **Tier**: B — **Role**: mid-funnel supporting cast. OG print-era format; only cranks with *amazing* messaging, and pairs best with a Callout treatment (see below).
- **Structure**: One dominant text line (60%+ of visual weight), product image, logo small
- **Copy slot**: One claim specific enough to stop the scroll
- **DTC example**: "The last greens powder you'll ever buy."
- **SaaS example**: "Close your books in 3 days, not 3 weeks."
- **Source it from**: Your strongest winning-ad hook or the most repeated benefit in reviews

### 2. Us vs. Them

Side-by-side comparison. Competitor or "old way" on the left (grayed out), your product on the right (full color). 4-6 comparison rows.

- **Tier**: B — **Role**: mid-funnel supporting cast. "Us vs. them" reliably sneaks into a brand's top 8; converts well for people already weighing you against an alternative, but rarely the format that opens cold net-new reach.
- **Structure**: Two columns, check/cross marks per row, your side visually alive
- **Copy slot**: Comparison rows — each row a real differentiator, not filler
- **DTC example**: "Their multivitamin: 13 ingredients. Ours: 60."
- **SaaS example**: "Spreadsheets: 6 hours a week. Us: 6 minutes."
- **Source it from**: Reviews that mention switching, or comments comparing you to a competitor

### 3. Stat Callout

One dominant number takes up 60% of the visual. Supporting context below.

- **Tier**: C — **Role**: situational supporting cast. Statistics statics work for luxury/retail brands and awareness/traffic objectives, but under-deliver on direct-response D2C ROI. Use when the number *is* the differentiator, not as a default.
- **Structure**: Giant stat, one line of context, product or logo anchor
- **Copy slot**: A real, defensible number — measurement beats superlative
- **DTC example**: "97% of users feel a difference in 14 days."
- **SaaS example**: "11 hours saved per rep, per week."
- **Source it from**: Case studies, product analytics, or survey data — never invent the number

### 4. Review Card

A five-star testimonial styled as a screenshotted product review. Reviewer name, star rating, date.

- **Tier**: E — **Role**: decayed. Testimonial statics mostly disappoint ("marketers are bad at them") *unless* the review is a genuine golden-nugget — a specific, surprising, verbatim line that couldn't be invented. Skip generic 5-star praise; reserve this for the one review that stops you cold.
- **Structure**: Looks like a native review UI (G2, Trustpilot, Amazon, App Store — match where your buyers read reviews)
- **Copy slot**: A real review, verbatim — the artifact's credibility is its realism
- **DTC example**: A Trustpilot card: "I've tried 6 of these. This is the only one I reordered."
- **SaaS example**: A G2-styled card: "Killed 4 tools and replaced them with this."
- **Source it from**: `inputs/reviews/` verbatim — with permission where the platform requires it

### 5. Testimonial Stack

Three customer quotes arranged vertically, photo + name + one-line quote each.

- **Tier**: E — **Role**: decayed (same class as Review Card). A stack of testimonials is still a stack of testimonials — only worth the slot if all three quotes are golden-nugget specific and each covers a *different* objection. If they're interchangeable praise, cut it.
- **Structure**: Three short rows; quotes must be scannable in 2 seconds each
- **Copy slot**: Three quotes covering *different* objections or benefits — not the same praise three times
- **DTC example**: Three customers on results, taste, and convenience
- **SaaS example**: Three roles (IC, manager, exec) each praising their own outcome
- **Source it from**: Reviews — pick for coverage, not just enthusiasm

### 6. Before / After

Split image with arrow between. Transformation framing — product results, workflow, or visual proof.

- **Tier**: B — **Role**: mid-funnel supporting cast. Before/afters (and their cousin, progression ads) convert well for people already problem-aware; they show the payoff but rarely open cold reach on their own.
- **Structure**: Two panels, arrow or divider, minimal copy labeling each state
- **Copy slot**: Label the states in the customer's words ("Sunday-night spreadsheet dread" → "Reports send themselves")
- **DTC example**: Skin, energy, space — the classic visual transformation
- **SaaS example**: Cluttered 6-tab workflow → one clean dashboard
- **Compliance note**: Before/after claims are regulated in health, finance, and beauty — verify platform policy before using
- **Source it from**: Transformation language in reviews ("I used to X, now I Y")

### 7. Problem / Solution

Pain point on top (text or image), product as the answer below.

- **Tier**: B — **Role**: mid-funnel supporting cast. Close kin to objection-handling, which "works fast" and lands in most brands' top 15. Strongest when the pain is phrased in the customer's exact words.
- **Structure**: Two zones — tension above, relief below
- **Copy slot**: The pain in the customer's exact words, then the product's one-line answer
- **DTC example**: "Tired of 6 supplements every morning?" → one scoop visual
- **SaaS example**: "Your CRM knows nothing about product usage." → integration screenshot
- **Source it from**: The most common pain phrasing in `inputs/reviews/` — verbatim beats paraphrase

### 8. Founder Message

Handwritten-style or plain-text note from the founder. Conversational, personal tone.

- **Tier**: S — **Role**: unicorn cold-scaler. Founder content is the single most reliable *first* top performer at any production level — telling the story of *why* you built the brand auto-connects with same-problem cold audiences. The static "founder's letter" variant cranks hard during sales periods. Reach for this first.
- **Structure**: Note-style layout, founder name/photo, no product glamour shot
- **Copy slot**: "I built this because..." — one honest paragraph, no marketing polish
- **DTC example**: "Hey — I made this because every 'healthy' snack was secretly candy."
- **SaaS example**: "I ran RevOps for 6 years. This is the tool I kept wishing existed."
- **Source it from**: The actual founding story — this template collapses if fabricated

### 9. Feature Spotlight (Ingredient Spotlight)

Product hero in the center, 4-6 callout boxes around the edges highlighting key components.

- **Tier**: B — **Role**: mid-funnel supporting cast. This is a *callout* treatment — one of the most reliable static levers; pairs with Headline Statement. When the callouts teach rather than sell, it tips into educational-infographic territory (also B, below).
- **Structure**: Center image, radiating callouts, each callout 3-6 words
- **Copy slot**: The components buyers actually ask about — not your full feature list
- **DTC example**: Product bottle with callouts per key ingredient and what it does
- **SaaS example**: Dashboard screenshot with callouts on the 4 features reviews mention most
- **Source it from**: Which features/ingredients appear most in reviews and comments

### 10. Press Mention

"As seen in" with publication logos and a pull quote.

- **Tier**: F — **Role**: decayed, avoid. Press statics were champions years ago; they're now a rights/permissions nightmare — major outlets (Vogue et al.) actively pursue unlicensed logo use. The legal exposure outweighs the lift. If you have genuine, licensed coverage, a single quote inside another format is safer than a logo wall. Default: don't build these.
- **Structure**: Logo row + one strong quote + product anchor
- **Copy slot**: A real quote from real coverage
- **DTC example**: "The category's first genuinely new idea in years." — [publication]
- **SaaS example**: Analyst or industry-newsletter quote with the outlet's logo
- **Compliance note**: Only use logos of outlets that actually covered you; check their logo-usage terms
- **Source it from**: Actual press, podcasts, newsletters, or analyst mentions

### 11. Lifestyle Hero

Product in use in a real environment. Minimal copy. Aspirational, not salesy.

- **Tier**: B — **Role**: mid-funnel supporting cast. The organic-native look (mirror-selfie / flat-lay / "hot-girl IG story" energy for consumer brands) reads native and supports well, but doesn't reliably open cold reach by itself. For apparel specifically, see the Mood Board variant below.
- **Structure**: One photograph does the work; a short line and logo at most
- **Copy slot**: 5-8 words, identity-flavored ("Mornings, handled.")
- **DTC example**: Product on a kitchen counter mid-routine
- **SaaS example**: The tool on-screen in a real work moment (standup, close call, ship day)
- **Source it from**: Winning ads' visual patterns; identity language in reviews

### 12. Numbered List

"5 reasons [audience] are switching to [brand]." Icons next to each point.

- **Tier**: E — **Role**: decayed. Listicle statics worked a year or two ago and have gone flat lately. If you must, an *educational infographic* (below) is the healthier evolution of the same "teach in one frame" instinct. Don't lead a batch with this.
- **Structure**: Numbered rows, icon + short line each, product anchor at bottom
- **Copy slot**: Each reason a distinct angle — pain, outcome, proof, differentiator, price
- **DTC example**: "5 reasons runners switched to [brand] this year"
- **SaaS example**: "4 reasons finance teams are leaving [legacy tool]"
- **Source it from**: Aggregate the most common switching reasons across reviews

### 13. FAQ Card

A common objection as the question, answered directly.

- **Tier**: B — **Role**: mid-funnel supporting cast. This is objection-handling in static form — one of the fastest-working supporting formats, top-15 for most brands. The objection *as customers phrase it* is the whole hook.
- **Structure**: Question prominent, answer concise, product anchor
- **Copy slot**: The objection *as customers phrase it* — the recognition is the hook
- **DTC example**: "But does it work for sensitive skin? Yes — and here's why."
- **SaaS example**: "Will this survive our security review? SOC 2 Type II, SSO, EU hosting."
- **Source it from**: `inputs/comments/` — the objections people post publicly under your ads

### 14. Competitor Callout

Name a specific competitor (or the category default) and explain the difference. Bold but factual.

- **Tier**: B — **Role**: mid-funnel supporting cast. A sharper "us vs. them" / callout hybrid; converts comparison-shoppers already in your consideration set. Great for warm/mid-funnel, not a cold-reach opener.
- **Structure**: Their name vs. yours, one clear axis of difference
- **Copy slot**: A difference you can defend with facts — comparative claims invite scrutiny
- **DTC example**: "Like [competitor], minus the 14g of sugar."
- **SaaS example**: "[Competitor] charges per seat. We don't."
- **Compliance note**: Comparative advertising must be truthful and substantiatable; some platforms restrict naming competitors
- **Source it from**: Competitor mentions in reviews and comments — customers name the alternative for you

### 15. Origin Story

Founder photo with the why-we-built-this narrative. Longer copy than other formats.

- **Tier**: S — **Role**: unicorn cold-scaler (same founder-content family as Founder Message). The specific origin moment auto-connects with same-problem cold audiences; this is the one long-copy static that reliably opens net-new reach. Pairs well with warm/retargeting too.
- **Structure**: Portrait or team photo, 2-3 short paragraphs, product secondary
- **Copy slot**: The specific moment or frustration that started it — specificity is the credibility
- **DTC example**: "We spent 2 years and 47 batches getting this right. Here's why."
- **SaaS example**: "We were the customer. The tool we needed didn't exist, so we built it."
- **Source it from**: The real story — pairs with warm/retargeting audiences better than cold

### 16. Grid Static (Multi-SKU / Bundle)

A tidy grid of your product line, a bundle, or a collection — one clean frame, multiple SKUs. Optional "shop the set" line.

- **Tier**: A — **Role**: cold-scaler. Easy to make and a proven low-hanging-fruit test — a top performer at a 9-figure brand. Scales because it shows range and lets a cold viewer self-select the SKU that fits them. First static to try when you have more than one product.
- **Structure**: 4–9 product tiles on a neutral ground, consistent lighting/crop, small logo + optional bundle price
- **Copy slot**: Minimal — a collection name or a "build your bundle" line; the products do the talking
- **DTC example**: A 3×3 grid of every flavor with a "Try the whole lineup" bundle price
- **SaaS example**: A grid of the plan's included tools/integrations — "one subscription, all of it"
- **Source it from**: Which SKUs/bundles reviews and comments cluster around; lead with the requested combinations

### 17. Callout

Product hero with 3–5 short labels pointing at specific parts — the "what makes this different" annotated directly on the image.

- **Tier**: B — **Role**: mid-funnel supporting cast. One of the most durable static levers; pairs with Headline Statement and underpins Feature Spotlight. Cheap to iterate, reads fast.
- **Structure**: Center product, leader lines to 3–5 labels, each label 2–5 words
- **Copy slot**: The attributes buyers actually ask about — not spec-sheet filler
- **DTC example**: A shoe with callouts on the sole, the material, the weight
- **SaaS example**: A dashboard screenshot with callouts on the three features reviews cite most
- **Source it from**: The features/attributes that recur in reviews and ad comments

### 18. Mood Board (Apparel)

A curated collage — product, texture, setting, palette — assembled like a Pinterest board. Identity over information.

- **Tier**: B — **Role**: mid-funnel supporting cast, apparel/lifestyle. Great for fashion and home brands where the *vibe* is the product; sells the world the buyer is opting into.
- **Structure**: 3–6 tiles mixing product shots, fabric/texture, and aspirational scene; cohesive palette
- **Copy slot**: A short identity line at most ("Quiet luxury, everyday.")
- **DTC example**: A capsule wardrobe laid out with the season's palette and a location shot
- **SaaS example**: Rarely applicable — use Lifestyle Hero instead unless the brand sells an aesthetic
- **Source it from**: Winning ads' visual language; identity/aesthetic words in reviews

### 19. Educational Infographic

A single frame that *teaches* something true — a mechanism, a comparison, a "how it works" — styled to read as content, not an ad.

- **Tier**: B — **Role**: mid-funnel supporting cast, and under-used. It masquerades as content, so it earns attention the hard-sell formats don't. The healthier evolution of the (now-decayed) Listicle.
- **Structure**: A diagram, cycle, or labeled cross-section; minimal brand until the anchor
- **Copy slot**: One genuine, checkable teaching point — never a fabricated stat or mechanism
- **DTC example**: "How [ingredient] actually gets absorbed" as a simple three-step diagram
- **SaaS example**: A "before vs. after your stack" workflow map showing where the tool slots in
- **Compliance note**: Educational framing raises the bar on truth — every claim in the graphic must be substantiatable
- **Source it from**: The mechanism questions in comments ("but how does it work?") and documented product facts

### 20. Challenging Your Beliefs

Leads with a contrarian statement that names a limiting belief the persona holds, then flips it. Confrontational hook, resolved below.

- **Tier**: B — **Role**: mid-funnel supporting cast. Works when you genuinely know the persona's limiting beliefs; needs a specific, earned reframe (in video it wants B-roll — as a static it wants a crisp visual contrast).
- **Structure**: Bold belief-statement up top, the flip below, product as the proof
- **Copy slot**: The exact false belief in the customer's words, then the correction
- **DTC example**: "You don't need more protein. You need protein you'll actually take."
- **SaaS example**: "Your problem isn't more dashboards. It's that nobody reads them."
- **Source it from**: Objections and misconceptions surfaced in comments and reviews

### 21. Tweet / Reddit Screenshot

A single tweet or Reddit post styled as a native screenshot — real social proof as the creative, strongest when used as the *first frame*.

- **Tier**: B — **Role**: mid-funnel supporting cast; especially effective as a hook/first frame. Sweet spot around the $100k–250k monthly spend range where fresh angles matter.
- **Structure**: A pixel-accurate tweet/Reddit card — avatar, handle, timestamp, engagement counts
- **Copy slot**: A real post, verbatim — an unprompted mention or your own best-performing organic line
- **DTC example**: A screenshotted Reddit comment: "been using [X] for 3 months, actually works"
- **SaaS example**: A tweet from a real user describing the exact outcome
- **Compliance note**: Use real posts with permission where required; never fabricate a social screenshot — a faked tweet is a trust and platform violation
- **Source it from**: Real social mentions, your own organic posts, or `inputs/comments/`

### 22. Ugly / Handwriting / Post-it

Deliberately low-polish — handwritten note, sticky note, or plain-text-on-a-photo. The anti-designed look reads native and urgent.

- **Tier**: B — **Role**: supporting cast, and a sales-period specialist. These crush during sales/promo windows precisely because they look thrown-together and time-sensitive. Rotate in for BFCM, launches, and flash sales; don't run them as an always-on default.
- **Structure**: One scrappy element (post-it, marker note, screenshot) over product or plain ground
- **Copy slot**: A blunt, human line — the offer or the reason, in plain words
- **DTC example**: A post-it reading "40% off ends tonight — don't forget" slapped on the product
- **SaaS example**: A "note to self: cancel the other tool" scrawl before the switch
- **Source it from**: The offer itself; the plain way a customer would remind a friend

---

## Per-Concept Output Format

Each generated concept follows this structure:

```markdown
## Concept [N]: [Template Name]

**Headline**: [the headline copy]
**Body**: [supporting copy, if the template uses it]
**Visual**: [layout description specific enough to design or generate from]
**Image prompt**: [prompt for the image tool, if generating — see generative-tools.md]
**Grounded in**: [which review / winning ad / comment this traces to, quoted or named]
```

Record each concept's **tier** alongside its template so the reviewer sees the funnel role at a glance. For a batch, add an `INDEX.md` listing every concept with its template type, tier, and grounding source, so the reviewer can scan 50 concepts in two minutes.

## Batch Distribution

For a standard 50-concept batch: spread variations across the template set, but let tier and funnel goal shape the weighting rather than distributing evenly. For a cold-reach batch, over-index on the S/A tiers (Founder Message, Origin Story, Grid Static); for a warm/retargeting batch, lean on the B-tier supporting cast (Callout, FAQ Card, Before/After, Competitor Callout). Skip the D–F decayed formats (Press Mention, Testimonial statics, Numbered List) unless you have a specific reason. If performance data shows certain templates consistently winning for this brand, shift to 60% proven templates / 40% full-cycle coverage — but never drop coverage to zero. Fatigue is why you're generating daily; the template that's tired next month is the one you're scaling today.
