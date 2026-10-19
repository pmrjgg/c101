---
name: graphic-design
description: "Graphic design and art-direction pack: brief intake, composition and visual hierarchy, layout grids and spacing systems, typography (modular scales, measure, leading, pairing), color theory with OKLCH palettes and WCAG 2.2 contrast math, brand systems and design tokens, iconography grids, print versus screen production, a scored critique rubric, and precise image briefs mapped to the image MCP server's per-operation tools. Load for any layout, brand, typography, color, icon, poster, slide, UI-visual or generated-image direction task."
when_to_use: "Designing or critiquing a layout, brand system, palette, type system, icon set or marketing visual; checking contrast and accessibility; preparing print or screen deliverables; writing or reviewing prompts and briefs for image generators, editors and vectorisers."
---

# Graphic design

Design decisions must be defensible in one sentence each ("the headline is 3 steps up the scale
because it is the only entry point"). This skill turns taste into checkable rules: measured
contrast, a declared grid, a declared type scale, a scored critique, and image briefs precise
enough that two generators would produce recognisably the same picture.

## 0. Process and triage

1. Intake the brief (section 1). Missing purpose, audience or format → Open doubt, not a guess.
2. Constraints: brand assets, mandatory copy, sizes, color space, accessibility level, deadline.
3. Concept: 2-3 directions, each one sentence + a thumbnail description or a quick generation.
4. System: grid, type scale, palette tokens, spacing scale, imagery style (sections 2-7).
5. Produce: layout, assets (delegated generation/editing/vectorising, section 10).
6. Critique with the rubric (section 9), fix, re-score.
7. Hand off: exports, specs, tokens, source files, accessibility report.

| Request | Sections |
|---|---|
| Poster, social post, ad, slide | 1, 2, 3, 4, 5, 9, 10 |
| Brand identity / style guide | 4, 5, 6, 7, [color and accessibility](references/color-and-accessibility.md) |
| UI visual polish, dashboard look | 2, 3, 4, 5, [typography](references/typography.md) |
| Icon set | 7 |
| Print collateral | 3, 8, [color and accessibility](references/color-and-accessibility.md) section 5 |
| Generated imagery | 10, [image briefs](references/image-briefs.md) |
| Review of an existing design | 9 |

## 1. Brief intake checklist

| Field | Question | Example |
|---|---|---|
| Purpose | what must the viewer do or remember? | register for a webinar by 12 Nov |
| Audience | who, where, in what state of attention? | developers scrolling LinkedIn on phones |
| Message hierarchy | 1 primary message, ≤ 2 secondary, the rest is detail | headline, date, CTA; speaker names |
| Format | medium, pixel or mm size, aspect, safe zones | 1080×1350 px (4:5) feed post |
| Brand | logo files, palette, fonts, voice, do/don't | SVG logo, tokens.json, Inter + Source Serif |
| Mandatory | legal lines, logos, partner marks | partner logo ≥ 120 px wide |
| Accessibility | WCAG level, alt text, motion limits | AA, alt text required |
| Deliverables | formats, color space, variants | PNG sRGB + 3 size variants + editable source |
| Success check | how will we know it works? | CTR vs last campaign; legible at 50% zoom |

## 2. Composition and visual hierarchy

Hierarchy levers, strongest first in most contexts: **size**, **contrast** (value, then
saturation), **position** (top-left in LTR scripts, optical centre slightly above geometric),
**isolation** (whitespace around an element), **weight**, **color hue**, **motion** (screens only).

Rules:
- One focal point per view. Count entry points with the squint test (blur the design ~8-10 px or
  view at 25% size): what you see first must be the primary message; if two things compete, demote one.
- Three levels of emphasis are readable (primary, secondary, body); five is noise.
- Group by proximity before adding boxes or lines (Gestalt: proximity, similarity, common region,
  continuity, closure, figure-ground). Space within a group < space between groups (ratio ≥ 1:2).
- Align everything to something: edges and baselines on the grid; optical alignment for round
  and pointed shapes (overshoot ~1-3% of size for circles and triangles).
- Balance: symmetric for formal/institutional, asymmetric with a counterweight for dynamic layouts;
  large light shapes balance small dark ones.
- Reading patterns: Z-pattern for sparse layouts (posters, landing heroes), F-pattern for text-heavy
  screens; put the CTA at the terminal point of the pattern.
- Whitespace is an active element; cramped margins read as cheap. Default outer margin
  ≥ 5% of the short side for posters and social, more for luxury positioning.

## 3. Grids and spacing

Column width for n columns, outer margin M, gutter G, canvas width W:

```
column = (W - 2M - (n - 1) G) / n
```

Worked: W = 1440 px, n = 12, G = 24, M = 72 → (1440 - 144 - 264)/12 = 86 px columns.
A 1080 px social post: n = 6, G = 24, M = 64 → (1080 - 128 - 120)/6 = 138.7 px; snap M to 60 for
exact 140 px columns.

| Grid | Use |
|---|---|
| Manuscript (single column) | long reading, books, articles |
| Column grid (4/8/12 columns) | web, editorial, dashboards (12 divides by 2, 3, 4, 6) |
| Modular grid (columns × rows) | posters, catalogues, complex editorial |
| Baseline grid (body leading, e.g. 24 px) | multi-column text alignment, print |
| Hierarchical / custom | landing pages and one-off compositions; still declare the key lines |

Spacing scale: base 4 or 8 px; steps 4, 8, 12, 16, 24, 32, 48, 64, 96, 128. Use only scale values;
an off-scale 13 px gap is a defect in critique. Responsive breakpoints: design content-first, then
typical widths 360-430 (phones), 768 (tablet), 1024-1280 (laptop), 1440+ (desktop); columns
4 / 8 / 12; margins 16-24 / 32 / 64-80 px.

## 4. Typography

Modular scale: size_k = base × r^k.

| Ratio | Name | Steps from 16 px | Use |
|---|---|---|---|
| 1.125 | major second | 16, 18, 20.3, 22.8, 25.6 | dense UI |
| 1.200 | minor third | 16, 19.2, 23, 27.6, 33.2 | apps, docs |
| 1.250 | major third | 16, 20, 25, 31.3, 39.1, 48.8 | websites, general default |
| 1.333 | perfect fourth | 16, 21.3, 28.4, 37.9, 50.5 | editorial, marketing |
| 1.500 | perfect fifth | 16, 24, 36, 54, 81 | posters, landing heroes |
| 1.618 | golden | 16, 25.9, 41.9, 67.8 | display-heavy, few levels |

Rules of thumb that hold up in production:
- Measure (line length) 45-75 characters, ~66 ideal for body; 30-40 for narrow columns and mobile.
- Leading: body 1.4-1.6 × size (longer lines need more); headings 1.05-1.25; all-caps and display
  sizes tighter.
- Tracking: display sizes negative (-1% to -3%); all-caps and small labels positive (+5% to +12%);
  body 0.
- Sizes: web body ≥ 16 px; UI labels ≥ 12 px; print body 9-12 pt; captions ≥ 7-8 pt; signage by
  viewing distance (cap height ≈ distance / 250 to 1/300 for comfortable reading; check the font's
  own guidance).
- Two families maximum (often one superfamily is enough); 3-4 weights total; pair by contrast in
  classification (serif + sans) with similar x-height and proportions; never pair two similar
  sans-serifs.
- Numerals: tabular lining for tables and prices (`font-variant-numeric: tabular-nums`); old-style
  in running text where the font supports it.
- Rag and breaks: no widows/orphans in headings and pull quotes; balance headline lines
  (`text-wrap: balance`); avoid justified text without hyphenation.
- Licensing: confirm desktop, web, app-embedding and broadcast rights for every font; prefer open
  licences (OFL) when the brief allows.

Details, pairing catalogue and CSS patterns: [typography](references/typography.md).

## 5. Color

Build palettes in a perceptual space (OKLCH): fix hue and chroma per brand color, step lightness
for tints and shades; HSL lightness is not perceptual (yellow and blue at the same HSL L look
nothing alike).

Roles before hues: background, surface, text (primary, secondary), border, brand primary, accent,
semantic (success, warning, danger, info), focus ring, data-viz categorical set. Proportion guide:
~60% neutral ground, ~30% secondary, ~10% accent (the 60-30-10 rule as a starting point).

WCAG 2.2 contrast (sRGB channels c in 0..1):

```
linear(c) = c ≤ 0.04045 ? c/12.92 : ((c + 0.055)/1.055)^2.4
L = 0.2126 R + 0.7152 G + 0.0722 B          (on linearised channels)
contrast = (L_lighter + 0.05) / (L_darker + 0.05)        range 1..21
```

| Criterion | Requirement |
|---|---|
| 1.4.3 Contrast minimum (AA) | text 4.5:1; large text 3:1 (≥ 24 px regular or ≥ 18.66 px bold) |
| 1.4.6 Contrast enhanced (AAA) | 7:1; large text 4.5:1 |
| 1.4.11 Non-text contrast (AA) | UI component boundaries, focus indicators, meaningful graphics 3:1 against adjacent colors |
| 1.4.1 Use of color (A) | color is never the only carrier of meaning (add icon, label, pattern) |
| 2.5.8 Target size minimum (AA, new in 2.2) | pointer targets ≥ 24 × 24 CSS px or sufficient spacing |

Measured reference pairs (computed with the formula above):

| Foreground on background | Ratio | Verdict |
|---|---|---|
| #767676 on #FFFFFF | 4.54 | AA text (the lightest neutral gray that passes on white) |
| #777777 on #FFFFFF | 4.48 | fails AA text |
| #6B7280 on #FFFFFF | 4.83 | AA text |
| #9CA3AF on #FFFFFF | 2.54 | placeholder-style gray: fails text and non-text |
| #2563EB on #FFFFFF | 5.17 | AA text, link color OK |
| #F59E0B on #FFFFFF | 2.15 | amber on white fails; use on dark |
| #F59E0B on #111827 | 8.26 | AAA |
| #E94560 on #1A1A2E | 4.46 | fails AA body text by 0.04: raise OKLCH L from 0.633 to 0.64 (#EC4862, 4.59) |
| #FFFFFF on #E94560 | 3.83 | large text / buttons with ≥ 18.66 px bold only |

Color vision deficiency: about 8% of men and 0.5% of women of Northern European ancestry have a
red-green deficiency. Simulate (protan, deutan, tritan) and check that categories remain
distinguishable by lightness as well as hue. Dark mode is a separate palette, not an inversion:
reduce chroma, avoid pure black (#000) behind pure white text for long reading, re-check every pair.

Print color, CMYK conversion, rich black and spot colors: [color and accessibility](references/color-and-accessibility.md).

## 6. Brand systems

Components of a working brand system (deliver as files, not only a PDF):
1. Logo suite: primary, horizontal/stacked lockups, mark only, monochrome and reversed versions;
   clear space (e.g. = cap height of the wordmark or x of the mark) and minimum size (e.g. 24 px /
   10 mm wide for the mark); misuse examples.
2. Color tokens in three tiers: primitive (`blue-600: oklch(0.55 0.2 260)`) → semantic
   (`color-action-primary: {blue-600}`) → component (`button-primary-bg: {color-action-primary}`).
   Ship as DTCG-format `.tokens.json` plus CSS custom properties.
3. Typography: families, weights, scale tokens, line-heights, usage table per role.
4. Grid and spacing tokens.
5. Imagery: photography direction (light, palette, cropping, people), illustration style,
   generated-image rules (allowed models, mandatory review, disclosure if required).
6. Iconography (section 7), data-viz palette, motion principles if relevant.
7. Voice and tone, with example headlines.
8. Accessibility statement: contrast-checked pairings table.

Consistency test: hide the logo; is the piece still recognisably the brand? If not, the system
relies on the logo alone.

## 7. Iconography

| Parameter | Default |
|---|---|
| Canvas | 24 × 24 px with 2 px padding (20 × 20 live area); also design 16 and 20 if used small |
| Stroke | 1.5 or 2 px, consistent across the set; round or square caps/joins, chosen once |
| Keylines | circle ≈ 20 px, square ≈ 18 px, portrait/landscape rectangles 16 × 20 / 20 × 16 for optical equality |
| Corner radius | one value (e.g. 2 px) for outer corners |
| Pixel fit | align strokes to the pixel grid at the primary size (odd stroke widths on half pixels) |
| Metaphor | conventional over clever (magnifier = search); test recognition without labels |
| Export | SVG with `viewBox="0 0 24 24"`, `fill="none"`/`stroke="currentColor"` (or fill-based set), no transforms, no embedded raster, IDs stripped, run through `svg_optimize` / svgo |

Consistency audit: overlay all icons at the same size; stroke weights, cap styles, corner radii,
visual mass and perspective must match. Filled and outlined variants are separate sets.

## 8. Print versus screen

| Aspect | Print | Screen |
|---|---|---|
| Units | mm/pt; type in pt | px/rem; type in px or rem |
| Resolution | 300 ppi at final size (A4 = 2480 × 3508 px); 150 ppi for large-format viewed far | 1× design with 2×/3× assets; vectors where possible |
| Color | CMYK (profile from the printer: FOGRA39/FOGRA51, GRACoL), spot (Pantone) | sRGB by default, Display P3 for wide gamut |
| Bleed and safety | 3 mm bleed (0.125 in in US), 3-5 mm safe zone inside trim | platform safe zones (UI overlays on social, notches) |
| Black | rich black for large areas (e.g. C60 M40 Y40 K100), 100K for small text | #000 rarely; near-black #111-#1A1A1A |
| Files | PDF/X-4 (fonts embedded, transparency live) or PDF/X-1a when demanded | SVG, PNG, WebP/AVIF, PDF for documents |
| Proofing | hard proof or calibrated soft proof; check total ink and overprint | check on real devices, light and dark mode |

## 9. Critique rubric

Score each criterion 0-3 (0 absent/broken, 1 weak, 2 good, 3 excellent). Report the table, the
total out of 30, and the top three fixes ordered by impact. A design ships at ≥ 22 with no zero.

| Criterion | 3 means |
|---|---|
| Fit to brief | primary message and action unmistakable for the stated audience and medium |
| Hierarchy | squint test shows one focal point, then the intended reading order |
| Composition | balanced, purposeful whitespace, consistent alignment to a declared grid |
| Typography | declared scale, correct measure and leading, ≤ 2 families, clean rag |
| Color | palette roles clear, brand-consistent, harmonious |
| Accessibility | all text and UI pairs pass the target WCAG level (measured), meaning not color-only |
| Consistency | spacing on scale, components and icons uniform, brand system respected |
| Legibility at size | readable at actual display size and distance (phone at arm's length, poster at 3 m) |
| Craft | no misalignments, widows, rasterised text, artefacts, inconsistent radii |
| Distinctiveness | memorable, not template-generic, appropriate to the brand |

Critique format, one line per issue: **observation** (where, measured) → **principle** → **fix**.
Example: "CTA text #FFFFFF on #E94560 at 16 px regular measures 3.83:1 → 1.4.3 needs 4.5:1 for
text under 18.66 px bold → darken the button fill to OKLCH L ≤ 0.59 at the same hue and chroma
(#D63151 gives 4.76:1), or set the label ≥ 18.66 px bold (3:1 suffices)."

## 10. Image briefs and generator direction

Write the brief as structured fields first, then compile it into the prompt. Template and genre
examples: [image briefs](references/image-briefs.md).

| Field | Content |
|---|---|
| Purpose and placement | where the image goes, what text overlays it, crop-safe area |
| Subject | who/what, count, pose, expression, wardrobe/material, exact details that must be right |
| Composition | shot size, angle, subject position (e.g. right third), negative space for copy (e.g. left 40% clean) |
| Style | photo (camera, lens mm, aperture, film/digital look) or illustration (medium, line weight, shading, reference artists' movements, not living artists' names) |
| Light | key direction, quality (hard/soft), time of day, color temperature |
| Palette | 3-5 hex values with roles; background value relative to overlay text |
| Text in image | exact strings in quotes, font character; prefer adding final text in layout instead |
| Exclusions | what must not appear (extra fingers, logos, watermarks, text artefacts) |
| Technical | aspect ratio, size, transparent background, n variants, seed, model capability needed |

Mapping to tools (call through the delegated agents, or directly when you hold the MCP servers):
- `mcp__image__image_generate` {prompt, aspect_ratio, size, n, quality, seed, output_dir};
  `image_generate_with_references` adds references[] for style/character/product consistency (say in
  the prompt what each reference is for: "image 1: product shape and label; image 2: lighting mood");
  `image_generate_transparent` for RGBA assets.
- `image_edit` {image, instruction, mask, references[]} for local changes; `image_segment` {image,
  prompt} builds a mask by description; `image_remove_background`; `image_upscale` {image, scale} last.
- `vector_generate` {prompt, style} for logos/icons/flat illustration; `image_vectorize` {image} to
  trace a raster; `svg_optimize` {svg_path} before delivery; `svg_layerize` and `export_pdf` for
  layered SVG / layered PDF deliverables.
- Each operation runs on the one endpoint and model the user configured for it in
  `~/.claude/stack.env` (no fallbacks), and its tool is listed only when configured:
  `image_ops_status` says which are available and names the missing variables. Model choice
  guidance lives in the image-generation skill.

Delegation: brief `image-generator` for raster generation, `image-editor` for edits, masks,
background removal and upscaling, `vector-artist` for SVG work. Each brief includes the structured
fields, the output path under your out_dir, the number of variants (n inside one tool call, not one
agent per variant), and the acceptance checks below. The review loop needs the files, so call Agent
with `run_in_background: false`; the child's final message must list every output path and its
sidecar. Only independent concept directions go out as parallel Agent calls in one message.

Review loop: generate n = 4 → score each against the brief fields (subject accuracy, composition
and copy space, palette match, artefacts, text accuracy) → pick or edit the best (masked edits
for local defects, not regeneration) → place in the layout and re-run the rubric. Stop after 3
rounds without improvement and report the blocker (usually a capability gap: exact text, hands,
brand-exact logos). Never place a generated imitation of a real logo; composite the supplied
vector logo instead.

## 11. Worked example: webinar promo (1080 × 1350)

Brief: developers, LinkedIn feed, register by 12 Nov. Grid: 6 columns, M = 60, G = 24 (140 px
columns); type: Inter, scale 1.333 from 18 px → 18 / 24 / 32 / 43 / 57 / 76; headline 76 px bold,
-2% tracking, 2 lines max, balanced; date 32 px; CTA 24 px bold in a 56 px tall button.
Palette: background #1A1A2E, text #FFFFFF (17.06:1). Brand pink #E94560 (OKLCH 0.633 0.199 15.7)
cannot serve both roles: as text on the navy it needs L ≥ 0.64 (#EC4862, 4.59:1), as a button fill
behind white text it needs L ≤ 0.59 (#D63151, 4.76:1). Ship two semantic tokens
(`accent-on-dark`, `accent-fill`) from one primitive hue. Image: generated abstract network
illustration, right 55% of canvas, left 45% kept empty for copy; brief compiled per section 10 with
`aspect_ratio: "4:5"`, n = 4, fixed seed for reproducibility. Critique round 1 scored 21/30
(hierarchy 1: illustration as bright as headline); fix: drop illustration exposure and chroma,
round 2 scored 25/30. Deliver PNG sRGB, source file, alt text, contrast table.

## Quality gate before returning

- [ ] Brief fields complete or open doubts raised.
- [ ] Grid, type scale, spacing scale and palette tokens declared in the output.
- [ ] Every text/background pair measured; ratios listed with pass/fail at the target level.
- [ ] Rubric table with total and top fixes; no criterion scored 0.
- [ ] Generated assets: prompt, model, seed and references saved next to each file (sidecar).
- [ ] Deliverables in the right color space, size and format; fonts licensed for the use.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `design-tokens-dtcg` | creating, migrating, validating or releasing a token set |
| `icon-system-design` | designing, extending or auditing an icon set |
| `image-brief-writing` | directing image-generator, image-editor or vector-artist, or when writing image prompts yourself |
| `layout-grids-posters-editorial` | composing, critiquing or producing any layout |
| `logo-design-process` | creating, refining or auditing a logo, monogram or wordmark |
| `oklch-palette-ramps` | building, extending or fixing a palette |
| `social-asset-kit` | producing a multi-format campaign, ad set or launch kit |
| `type-scale-systems` | defining, implementing or auditing a type system for screen or print |
| `ui-mockup-hifi` | designing, presenting or reviewing app or web screens |
