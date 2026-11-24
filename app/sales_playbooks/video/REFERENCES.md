# Reference files for the `video` playbook

Each section below is one file from this playbook's `references/` folder. When GUIDE.md cites `references/<file>`, read the matching section here.


---

# references/ai-video-prompting.md

# AI Video Prompting Guide

How to write effective prompts for AI video generation models (Veo, Runway, Kling, Pika).

---

## Prompt Structure

A strong video prompt follows this formula:

```
[Subject] + [Action] + [Camera movement] + [Visual style] + [Lighting/mood] + [Technical specs]
```

### Example Prompts by Use Case

**Product hero shot:**
```
A sleek laptop on a minimal white desk, screen glowing with a dashboard UI,
camera slowly orbits 180 degrees around the desk,
soft volumetric lighting from the left, shallow depth of field,
cinematic commercial aesthetic, 4K
```

**Lifestyle B-roll:**
```
A woman in a modern co-working space smiling while looking at her phone,
natural window light, candid documentary feel,
camera handheld with subtle movement, warm color grading
```

**Abstract/brand:**
```
Flowing liquid gold particles forming the shape of a network graph,
dark background, particles catch light as they move,
slow-motion macro photography style, dramatic rim lighting
```

**SaaS explainer scene:**
```
An overhead shot of a team around a conference table pointing at charts,
camera slowly pushes in, bright modern office,
clean corporate style, even lighting, 1080p
```

---

## Camera Movement Vocabulary

Use these terms — video models understand them:

| Term | Effect |
|------|--------|
| **Static** | Locked camera, no movement |
| **Pan left/right** | Camera rotates horizontally |
| **Tilt up/down** | Camera rotates vertically |
| **Dolly in/out** | Camera moves toward/away from subject |
| **Orbit** | Camera circles around subject |
| **Tracking shot** | Camera follows moving subject |
| **Crane/aerial** | Camera rises or descends |
| **Handheld** | Subtle shake, documentary feel |
| **Zoom** | Lens zoom (different from dolly) |
| **Slow push** | Gradual dolly in — builds tension/focus |

---

## Style Keywords

### Cinematic
- "cinematic color grading"
- "anamorphic lens flare"
- "shallow depth of field"
- "film grain"
- "35mm film"

### Commercial/Corporate
- "clean commercial lighting"
- "bright and airy"
- "professional corporate aesthetic"
- "even, diffused lighting"

### Documentary
- "handheld documentary style"
- "natural lighting"
- "candid, unposed"
- "observational camera"

### Social/Trendy
- "vertical 9:16"
- "fast-paced cuts"
- "bold text overlays"
- "high contrast, saturated colors"

---

## Model-Specific Tips

### Veo (Google)

- Excels at photorealism and complex scenes
- Supports audio generation synced to video
- Best with detailed, descriptive prompts
- Specify "high resolution" or "1080p" for best quality
- Can handle multiple subjects and scene transitions

### Runway Gen-4

- Strong motion control — specify camera movements precisely
- Best temporal consistency (subjects stay consistent across frames)
- Use motion brush for specific area animation
- Image-to-video works well — provide a reference frame
- Keep prompts under 100 words for best results

### Kling

- Can generate up to 2 minutes (much longer than others)
- Good for longer narrative sequences
- More affordable for bulk generation
- Quality drops slightly at longer durations
- Best with simpler scenes and fewer subjects

### Pika

- Fastest generation time (under 2 minutes)
- Good for quick iterations and experimentation
- Effects mode adds motion to still images
- Best for short clips (5-15 seconds)
- Less control over camera movement

---

## Common Prompt Mistakes

| Mistake | Why It Fails | Fix |
|---------|-------------|-----|
| "A person using our app" | Too vague, no visual detail | Describe the person, setting, lighting, camera |
| Including text/logos | AI can't render readable text | Add text in post via Hyperframes/CapCut |
| "Make it viral" | Not a visual instruction | Describe the visual style you want |
| Extremely long prompts (200+ words) | Models lose focus | Keep to 50-100 words, be specific |
| No camera direction | Random/static camera | Always specify movement or "static" |
| "Realistic" alone | Not specific enough | "Photorealistic, natural lighting, shot on RED camera" |

---

## Prompting Workflow

1. **Reference first** — find a real video that looks like what you want
2. **Describe it** — break down: subject, action, camera, style, mood
3. **Generate 3-4 variations** — same concept, different angles or styles
4. **Iterate on the best** — refine the prompt based on results
5. **Composite** — combine AI footage with programmatic text/overlays

---

## Aspect Ratios

Always specify in your prompt or generation settings:

| Platform | Ratio | Resolution |
|----------|-------|-----------|
| YouTube | 16:9 | 1920x1080 or 3840x2160 |
| TikTok/Reels/Shorts | 9:16 | 1080x1920 |
| Instagram Feed | 1:1 or 4:5 | 1080x1080 or 1080x1350 |
| Website hero | 16:9 | 1920x1080 |
| LinkedIn | 16:9 or 1:1 | 1920x1080 |

---

## Cost Optimization

- **Iterate at low resolution** — upscale only the final version
- **Use Kling for drafts** — cheapest per second, switch to Veo/Runway for finals
- **Image-to-video** — providing a reference frame saves generation credits and gives better results
- **Batch similar prompts** — models often offer volume discounts
- **Cache and reuse** — B-roll clips can be reused across multiple videos


---

# references/edit-anatomy.md

# Reverse-Engineering an Edit (The Beat Sheet)

A viral short-form video usually isn't winning on the footage — it's winning on the *edit*: the cut rhythm, the caption style, the punch-ins, the on-screen text landing on the exact word, the b-roll cutaways, the sound design. This reference turns a reference edit you admire into a **reusable edit spec** — a beat sheet you (or an editing tool) can execute against your own footage — without copying a single frame of theirs.

This is the tool-agnostic half of "copy any viral edit": the *decomposition*. The generation is whatever you edit with afterward — CapCut, Premiere, Remotion/Hyperframes, or an AI restyle tool. The spec is the deliverable.

## When to use it

- A competitor's or creator's edit keeps stopping your scroll and you want to understand *why* and replicate the technique
- You have raw footage (a talking-head clip, a demo) and a reference edit whose style you want to match
- You're briefing an editor or a template and need the edit decisions written down, not vibes

Don't use it to copy someone's actual creative — this extracts the *editing grammar* (structure, rhythm, caption treatment), not the script, footage, or brand. Same rule as mining organic content for vocabulary in the hook system: take the technique, never the creative.

## Step 1 — Pull the reference so you can actually read the edit

You cannot decompose an edit from a description of it. Get the frames and the timing:

- **watch-video** (visual or multimodal mode) — extracts the transcript *and* samples frames at the cut points, so you can read on-screen text, caption style, and shot changes. This is the primary tool.
- **social-fetch** — pull the post for the caption, engagement, and the media URL when the reference is a specific tweet/Reel/TikTok.
- Screenshots of key frames also work if the user supplies them — you need the visual, not just the words.

Note the total duration and roughly how many cuts there are before you start — cuts-per-second is the single most telling number about an edit's energy.

## Step 2 — Extract the anatomy, beat by beat

Walk the reference from 0:00 and log every editing decision. The dimensions that define a short-form edit:

| Dimension | What to read off the reference |
|---|---|
| **Shot & framing** | Talking head / screen recording / b-roll / text card; close-up vs. wide; headroom, rule-of-thirds, or dead-center |
| **Cut rhythm** | Where each cut lands and how fast (cuts-per-second); is it on the beat, on the word, or on the breath? |
| **On-screen text** | The words, when each appears/disappears, and *where* on the frame (top-third caption vs. big centered statement) |
| **Caption style** | Font, weight, color, outline/box, and animation (word-by-word pop, karaoke highlight, whole-line) |
| **Motion** | Punch-ins / zoom pushes, shakes, whip-transitions, speed ramps — where and how aggressive |
| **B-roll & overlays** | Cutaways, stickers, arrows, emoji, screenshots, meme inserts — what's laid over the base footage and when |
| **Sound design** | Music choice and where it hits, SFX (whooshes, dings, risers), and deliberate silence before a beat |
| **Hook (first 2s)** | The single most-copied element — what's on screen and said in the opening two seconds, before anyone's committed |
| **Pacing curve** | Does it stay frantic, or fast-hook → slower-body → fast-CTA? Map the energy over the runtime |

Read the *pattern*, not just the instances: "a hard cut + punch-in on every new sentence," "caption is one word at a time, yellow, karaoke-highlighted, bottom third," "a whoosh SFX on every scene change." Patterns are what make an edit replicable; a list of 40 individual cuts is not.

## Step 3 — Write the beat sheet

Two artifacts: a per-beat table and a short style summary.

**The beat sheet** — one row per beat (a beat = a cut or a distinct edit event):

```
| Beat | Time      | Shot            | On-screen text        | Caption style        | Transition / motion   | Audio            |
|------|-----------|-----------------|-----------------------|----------------------|-----------------------|------------------|
| 1    | 0:00–0:02 | CU talking head | "STOP doing this"     | word-pop, yellow, ctr| hard in, slow push    | music in + riser |
| 2    | 0:02–0:04 | screen record   | (caption only)        | karaoke, white, btm  | hard cut + whoosh     | click SFX        |
| …    |           |                 |                       |                      |                       |                  |
```

**The style summary** — the 3–5 *signature moves* that make this edit recognizable, stated so they're reusable:
- e.g. "Every sentence gets a hard cut + a 5% punch-in." / "Captions are one word at a time, bottom-third, karaoke-highlighted." / "A whoosh SFX on every cut; music drops out for 0.5s before the CTA." / "The hook is a bold centered statement on frame 1, no logo."

The signature moves are the real deliverable — someone can apply those five rules to any footage and get the style. The table is the detailed backup.

## Step 4 — Review once, then execute

Show the beat sheet before anyone edits anything — the same review-once gate as the ad-creative creative review page. The reviewer checks two things:

- **The on-screen text says what you want** (mapped to your message, not the reference's)
- **The scene changes land where you want them** (your footage's beats, not a blind copy of the reference's timing)

Approve, then execute the spec with your footage:
- **Remotion / Hyperframes** — when you want the edit templated and data-driven (see the programmatic-video section in SKILL.md); the beat sheet *is* the composition spec.
- **CapCut / Premiere / an editor** — hand off the beat sheet + style summary as the brief.
- **An AI restyle tool** — feed the style summary as the target style.

## Originality guardrail

You are copying the *edit*, not the content. The beat sheet describes technique (cut rhythm, caption treatment, motion, sound design) applied to **your** footage and **your** message. General editing techniques and style cues are usually reusable — U.S. copyright protects expression, not procedures or methods (17 U.S.C. §102(b)) — but the reference's specific creative expression is not, and closely reproducing a finished video's exact selection and arrangement of choices can still create risk. So copy the grammar, not the finished work: use your own footage, message, script, voiceover, licensed music/SFX/samples, and brand elements. If the reference's "style" is really a specific bit or sketch, that's their creative — draw inspiration, don't reproduce it.

## Common mistakes

- **Describing instead of reading** — you can't extract caption style or cut timing from the transcript alone; pull the frames (watch-video).
- **Logging instances, not patterns** — 40 cut timestamps isn't a spec; "hard cut + punch-in per sentence" is.
- **Copying the reference's timing onto different footage** — beats land on *your* words and *your* cuts; the reference gives you the grammar, not the calendar.
- **Skipping the hook** — the first 2 seconds carry most of the retention; decode them in the most detail.
- **Reproducing the creative** — matching the edit is fine; re-shooting their exact bit, script, or using their footage/music/SFX is not.
