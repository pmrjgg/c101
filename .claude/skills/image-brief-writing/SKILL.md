---
name: image-brief-writing
description: "Art-direction briefs for image models: structured YAML brief fields, compiling to a ranked prose prompt, capability-based routing with an image_ops_status preflight, reference roles, copy-safe zones, placement presets, genre templates, photo and lighting vocabulary, edit briefs, a 12-point review sheet, variant strategy and provenance. Load when directing image-generator, image-editor or vector-artist, or when writing image prompts yourself."
when_to_use: "Before any mcp__image__ generation or edit call, or before briefing image-generator, image-editor or vector-artist; when a generated image misses its brief (busy copy area, colour drift, misspelled text, style drift across a set); planning seeds and variants; writing an edit instruction; recording provenance and rights for generated images."
---

# Image brief writing

A brief is precise enough that two different models would produce recognisably the same picture,
and every acceptance item can be checked on the output. Order of work: structured brief → compiled
prompt → capability check → generate n = 4 → 12-point sheet → edit the best (do not reroll) →
`visual-reviewer` PASS → provenance.

Deep material: [genre templates](references/genre-templates.md) (full prompt skeletons and checks
per genre) | [vocabulary](references/vocabulary.md) (shot sizes, lenses, lighting, light quality,
colour grades, illustration media and styles).

Local helpers used below (Pillow scripts shipped with sibling skills):

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
PY="$STACK/.venv/bin/python"; IMG="$STACK/.claude/skills/image-generation/scripts/imgcheck.py"
MT="$STACK/.claude/skills/image-editing/scripts/masktool.py"
```

Shell variables do not persist between Bash calls: repeat these lines in every call.

## 1. Structured brief (fill first)

| Field | Content |
|---|---|
| `id` | slug plus version: `webinar-hero-v1` |
| `purpose` | what the image must do, where it appears, what overlays it |
| `placement` | canvas pixels, the region the image occupies, the copy-safe area in numbers |
| `subject` | who or what, count, pose, expression, material; details that must be exactly right |
| `composition` | shot size, angle, subject position as % of width and height, negative space |
| `style` | photo (camera, lens mm, aperture, digital or film look) or illustration (medium, line weight, shading, movement or era) |
| `light` | key direction, hard or soft, time of day, colour temperature |
| `palette` | 3-5 hex values with roles; background value relative to the overlay text |
| `text_in_image` | exact strings in quotes, or `none` (prefer setting text in the layout) |
| `exclusions` | what must not appear |
| `technical` | aspect ratio, size tier or WxH, n, seed, transparency (selects the op), quality |
| `references` | `[{path, role}]`, role = identity, product, style, composition or palette |
| `acceptance` | measurable checks: contrast in the copy area, palette distance, no text artefacts |

```yaml
id: webinar-hero-v1
purpose: hero illustration for a LinkedIn feed post; headline overlays the left side
placement: 1080x1350 canvas, image occupies the right 55%; left 45% must be empty, low-detail
subject: abstract network of glowing nodes and thin connecting lines forming a loose sphere
composition: sphere centred at 70% width, 45% height; bleeds off the right edge; generous negative space left
style: clean 3D render, soft depth of field, minimal, no photographic objects
light: soft rim light from upper right, subtle bloom on nodes
palette: background #1A1A2E; nodes #EC4862 and #56B4E9; lines #E6E6F0 at low opacity
text_in_image: none (all text set in layout)
exclusions: no text, no letters, no logos, no people, no busy texture in the left 45%
technical: aspect_ratio 4:5; size 2K; n 4; seed 1207
references: []
acceptance:
  - white headline over the left 45% reaches 4.5:1 at the worst point
  - dominant colours within ΔE(OKLab) ~0.05 of the listed hexes
  - no text-like artefacts
```

Missing purpose, placement or must-be-right details is an Open doubt to the caller, not a guess.

## 2. Compile the prompt

1. Order: subject → setting → composition and framing → style and medium → light → palette →
   mood → exclusions. One idea per sentence, concrete nouns.
2. Positions and empty space as numbers ("centred at 70% of the width", "the left 45% is plain").
3. Palette as hex with roles, and the background value stated (dark, mid, light).
4. Exclusions as positive constraints ("plain, empty background on the left") plus one short
   "No text, letters or logos." sentence. These models take no negative prompt; long "no" lists
   tend to introduce what they name.
5. Text in image: exact strings in double quotes with case, at most ~5 words each, the font's
   character ("bold geometric sans") and placement; long copy goes into the layout.
6. References by position, one role each: "Image 1 is the product: keep its shape, label and cap
   exactly. Image 2 sets the lighting mood only."
7. No living artists' names, trademarks or real people: describe medium, line quality, palette,
   era or movement instead.
8. Length under ~120 words. GPT Image and Gemini-family models use 80-120 words well; FLUX and
   Seedream dilute after ~40 words, so put subject, light and style first for them.

Compiled from the brief (85 words):

```text
Abstract network of glowing nodes connected by thin lines, forming a loose sphere centred at 70%
of the width and slightly above centre, bleeding off the right edge. The left 45% of the image is
plain, dark, empty background. Clean minimal 3D render with soft depth of field. Soft rim light
from the upper right, subtle bloom on the nodes. Background deep navy #1A1A2E, nodes coral pink
#EC4862 and sky blue #56B4E9, faint light-gray lines #E6E6F0. Calm, technical, premium mood.
No text, letters or logos.
```

## 3. Capability, not model

The `image` MCP server sends each operation to exactly the endpoint and model tag the user
configured (never read their env file); there is no per-call model choice and no fallback. A
brief therefore names the capability; the op follows from it.

| Capability needed | Op and tool | Check the configured tag for (model matrix, `image-generation` skill) |
|---|---|---|
| text to image | GEN `image_generate` | aspect and size vocabulary, seed support |
| keep a product, character or style from N references | REF `image_generate_with_references` | reference limit (e.g. 16 GPT Image, 14 Gemini, 10 FLUX 3) |
| RGBA output | `image_generate_transparent` | native alpha (GPT Image 2.5 flare or sunburst) |
| exact short text in image | GEN | text-strong tags (GPT Image 2.5, Ideogram 4.5) |
| extreme ratio (beyond 3:1) | GEN / REF | Nano Banana 2.1 reaches 8:1 and 1:8; GPT Image stops at 3:1 |
| local fix, rest identical | EDIT `image_edit` + mask | native mask or approximated (image-editing skill) |
| SVG icon, logo direction, flat illustration | VECTOR `vector_generate` | Recraft vector tags |
| raster to SVG | TRACE `image_vectorize` | native, local vtracer or approximated redraw |

Preflight once per task, before promising the caller any model or capability:
`mcp__image__image_ops_status` lists per op whether it is exposed, the adapter, URL host and
model tag, and the env names that are missing. (Older stack documents call
this `image_providers` and route through `config/image-models.json`; the current server documents
its ops in `config/image-ops.json` and the user's configuration decides the model.) A needed op
that is missing, or a tag that cannot do the job, becomes an Open doubt naming the variables and
a tag that fits; never substitute another op silently.

Delegation: `image-generator` for raster generation, `image-editor` for edits, masks, background
removal and upscales, `vector-artist` for SVG. Each brief carries the YAML, the compiled prompt,
the output directory, n inside one tool call (never one agent per variant), the acceptance
checks and the review threshold. Spawn with `run_in_background: false` (you need the files); the
child's final message lists every output path and its sidecar. Only independent concept
directions go out as parallel Agent calls in one message.

## 4. Placement presets

| Placement | Aspect | Pixels | Notes |
|---|---|---|---|
| Feed post | 4:5 | 1080 x 1350 | keep key content inside the centred 3:4 area (profile-grid crop) |
| Story / Reel / Shorts | 9:16 | 1080 x 1920 | top ~14% and bottom ~20% under UI; ads: bottom 35% |
| Square | 1:1 | 1080 x 1080 | |
| Open Graph / link | 1.91:1 | 1200 x 630 | text >= 48 px; centre-safe for a square crop |
| Slide / video | 16:9 | 1920 x 1080 | 5% title-safe margin |
| Web hero | 16:9 to 21:9 | 1920-2560 wide | plan a 4:5 art-direction crop for mobile |
| A-series print | 1:1.414 | A4 at 300 ppi = 2480 x 3508 | generate near 5:7, 3:4 or 2:3, then crop or outpaint and upscale; add 3 mm bleed |
| Banner | 3:1 to 4:1 | e.g. 1500 x 500 | generate wider than needed and crop |

Generate at the model's native resolution, edit, upscale as the last step (`image_upscale`),
then export. Multi-placement kits: one master, derived per placement (sibling
`social-asset-kit`).

## 5. Genre templates

| Genre | Route | Prompt core | Check |
|---|---|---|---|
| Product on seamless | REF with the product | three-quarter view at eye level, 85 mm look, f/8, softbox key left, white fill card right, soft contact shadow, label exactly as image 1 | label text character by character; small defects by masked edit |
| Editorial portrait (fictional person) | GEN | age range, expression, wardrobe, head-and-shoulders, 85 mm, soft window light at 45°, muted warm grade | hands, eyes, teeth; never a real identifiable person without documented consent |
| Isometric illustration | GEN, then REF for the set | isometric 30° angles, flat colours with one shading level, 2 px dark outlines, palette hexes, white background | angles consistent; fix seed, first accepted image as style reference |
| Flat spot illustration or icon | VECTOR | stroke width, corner radius, fill or outline, 24 x 24 canvas for icons | `svg_optimize`, then the icon audit (sibling `icon-system-design`) |
| Logo exploration | VECTOR or sketches only | directions, not finals | raster-generated logos are never deliverables; `vector-artist` draws the final |
| Abstract background for text | GEN | where text goes, low detail and low contrast there | worst-point contrast after placing text; scrim if needed |
| Seamless pattern | GEN, then EDIT | motif, scale, density, "seamless tileable" | 2 x 2 tile test and half-offset seam fix (below) |
| Transparent cut-out | `image_generate_transparent`, or GEN on a flat contrasting colour + `image_remove_background` | isolated subject, soft even light, no ground | edges on black and on white; hair and glass need matting-quality removal |

"Seamless" in a prompt is not proof. Test and fix:

```bash
"$PY" -I -c "
from PIL import Image, ImageChops
t = Image.open('tile.png'); w, h = t.size
g = Image.new(t.mode, (2 * w, 2 * h)); [g.paste(t, (x, y)) for x in (0, w) for y in (0, h)]
g.save('tile-2x2.png')                                   # Read it: seams show as a cross of lines
ImageChops.offset(t, w // 2, h // 2).save('tile-offset.png')   # seams move to the centre lines"
```

Mask a band about 6% of the tile wide along both centre lines of `tile-offset.png`, edit
"continue the pattern seamlessly across the masked bands; same motif scale and colours", offset
by half again (two half offsets restore the original alignment) and repeat the 2 x 2 test.

## 6. Photography and lighting vocabulary that moves results

| Shot size | Frame |
|---|---|
| extreme close-up | a detail: eyes, a product feature |
| close-up | face or the product filling the frame |
| medium close-up | head and shoulders |
| medium shot | waist up |
| full shot | whole body or object with a little space |
| wide / establishing | subject small in its environment |

| Lens look (full-frame) | Effect | Aperture look | Effect |
|---|---|---|---|
| 14-24 mm | expansive, edge stretch | f/1.4-2.8 | shallow depth of field, soft bokeh |
| 35 mm | environmental, reportage | f/4-5.6 | subject sharp, background soft |
| 50 mm | natural perspective | f/8-11 | front-to-back sharp: product, architecture |
| 85 mm | flattering portrait compression | f/16 | maximum depth, star-shaped highlights |
| 100 mm macro | close detail | | |
| 135-200 mm | compressed, isolated background | | |

| Light | Description to write |
|---|---|
| Rembrandt | key 45° to the side and above; small triangle of light on the shadow cheek |
| butterfly (Paramount) | key high and in front; small shadow under the nose; beauty |
| split | key at 90°; half the face lit; dramatic |
| rim / back light | light behind the subject outlining its edge; separates it from the background |
| softbox key + fill card | large soft source on one side, white bounce card on the other; product standard |
| high-key / low-key | bright and low-contrast / dark with deep shadows |
| time of day | golden hour (low, warm, long shadows), blue hour (cool twilight), overcast (soft, shadowless), midday (hard, short shadows) |
| colour temperature | tungsten ~3200 K warm, daylight ~5500 K neutral, shade ~7000 K cool |
| grade | teal-and-orange, bleach bypass (desaturated, contrasty), matte lifted blacks, split-toned warm highlights and cool shadows, pastel high-key |

Describe film or camera looks by their properties ("soft contrast, warm skin, fine grain") rather
than by product names. More: [vocabulary](references/vocabulary.md).

## 7. Edit briefs

Every instruction says what changes and what must stay identical:
`<verb> <target> <to what>; keep <everything else> unchanged.` Keep the original; write every
intermediate to disk; one semantic change per call.

| Defect | Operation | Instruction |
|---|---|---|
| local artefact (hand, glitch, stray object) | mask by `image_segment` or `masktool rect`, grow, `image_edit` with mask | "a relaxed hand with five fingers resting on the table; nothing else changes" |
| object in the wrong colour | masked `image_edit` with the hex | "change the jacket to #2563EB; keep folds, shading and everything else identical" |
| busy copy area | mask the area, `image_edit` | "fill the masked area with the plain continuation of the navy background; nothing else changes" |
| more canvas (outpaint) | `masktool pad`, `image_edit` with the pad mask, feather and composite | "extend the background naturally; add no objects or text" |
| background swap | `image_remove_background`, composite on the new ground | deterministic composite beats "replace the background" edits, which drift the subject |
| misspelled text | box mask, `image_edit` with the exact quoted string on a text-strong model; or blank it and typeset | read every character |
| resolution | `image_upscale` with `scale` 2 or 4, last | check invented detail in text and faces at 100% |
| raster to vector | `image_vectorize`, then `svg_optimize` | node count, closed shapes |

Mask conventions, grow amounts and verification diffs: sibling `image-editing`.

## 8. Review sheet (12 points)

Score each candidate 0-2 per check. Accept at >= 9/12 with no 0 on subject accuracy or artefacts;
the formal PASS is `visual-reviewer`'s 0-10 rubric (threshold 8) on the accepted candidate.

| Check | 2 means | 0 means |
|---|---|---|
| Subject accuracy | every must-have detail present and correct | wrong subject or a must-have missing |
| Composition | placement and copy space as specified | copy area blocked or subject cropped |
| Palette | dominant colours close to the brief hexes | palette ignored |
| Light and style | as briefed; shadows and perspective consistent | different style or light |
| Artefacts | none: hands, eyes, teeth, text glitches, warped straight lines, duplicates, melted edges | an artefact in the focal area |
| Fitness in layout | with text and logo placed, the layout rubric does not drop | the layout breaks |

Palette distance, measured (dominant colours vs brief hexes in OKLab):

```bash
"$PY" -I - candidate.png '#1A1A2E' '#EC4862' '#56B4E9' <<'EOF'
import sys, math
from PIL import Image
def lin(c): return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
def oklab(rgb):
    r, g, b = (lin(v / 255) for v in rgb)
    l, m, s = ((0.4122214708*r + 0.5363325363*g + 0.0514459929*b) ** (1/3), (0.2119034982*r + 0.6806995451*g + 0.1073969566*b) ** (1/3),
               (0.0883024619*r + 0.2817188376*g + 0.6299787005*b) ** (1/3))
    return (0.2104542553*l + 0.7936177850*m - 0.0040720468*s, 1.9779984951*l - 2.4285922050*m + 0.4505937099*s,
            0.0259040371*l + 0.7827717662*m - 0.8086757660*s)
brief = [tuple(int(h.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)) for h in sys.argv[2:]]
q = Image.open(sys.argv[1]).convert('RGB').resize((256, 256)).quantize(6); pal = q.getpalette()
for n, i in sorted(q.getcolors(), reverse=True):
    c = tuple(pal[3 * i:3 * i + 3]); d, hx = min((math.dist(oklab(c), oklab(b)), b) for b in brief)
    print('#%02X%02X%02X %5.1f%%  nearest #%02X%02X%02X  dE_ok %.3f' % (*c, 100 * n / 65536, *hx, d))
EOF
```

| Failure | Fix |
|---|---|
| busy area where text goes | "plain empty background on the left 45%", fewer detail words; or a masked edit to a smooth gradient |
| colours drift | hexes earlier in the prompt; a palette reference image; correct by masked edit |
| style inconsistent across a set | fixed seed, same prompt skeleton, first accepted image as style reference |
| text misspelled | shorten, quote exactly, text-capable tag, or set the text in the layout |
| subject too small or too big | state its share of the frame ("fills 60% of the height") |
| anatomy or perspective errors | simpler pose or composition; masked fix; never ship a visible error |

## 9. Variant strategy

1. Explore: `n: 4` (the tool's maximum per call), no seed, cheaper quality where the tag offers it.
2. Score all four with the sheet; keep the best; note its seed from the sidecar.
3. Refine: same seed (tags that ignore seeds, such as GPT Image, say so in `warnings`), change one
   factor per round (one prompt delta, one parameter, or one reference), `n: 2`.
4. Local defects go to edits (section 7), not to new rolls.
5. Stop after 3 rounds without a sheet gain, or at 4 rounds / 12 generations per deliverable;
   deliver the best and name the capability gap (exact text, hands, brand-exact logo, ratio,
   alpha) with a tag that has it, as an Open doubt.

## 10. Provenance and rights

The router writes `<file>.json` beside every output (op, adapter, URL host, model tag, prompt,
params including seed, inputs, created). Add the brief's fields under `agent`:

```bash
"$PY" "$IMG" sidecar out/webinar-hero-v1-3.png --set brief_id=webinar-hero-v1 --set seed=1207 \
  --set target='{"op": "GEN", "model": "google/gemini-nano-banana-2.1"}' --set references='[]' \
  --set licence="<model output terms URL, commercial use yes/no, date checked>" \
  --set review='{"sheet": 11, "visual_reviewer": 8.4, "verdict": "PASS"}'
```

Fields: brief id, compiled prompt (the router keeps it), op and model tag (the alias and the
target that answered), seed, references with roles, licence of the model's output for the use,
reviewer scores. Rights: no real-person likeness without documented consent; never generate a
real logo or trademark (composite the supplied vector); no imitation of a named living artist;
disclose AI generation where the platform or client requires it (platform AI labels, content
credentials).

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| copy area busy or high-contrast | composition described in adjectives | numeric empty area plus a measured acceptance check |
| prompt over 150 words, results muddled | every idea at equal weight | rank by the compile order; cut to < 120 words (< 40 for FLUX/Seedream cores) |
| the excluded object appears | long negative list | positive description plus one short "No ..." sentence |
| references blended into mush | roles unstated, too many style references | one role per reference, at most two style references |
| a model named in the brief is not what ran | model choice assumed per call | capability in the brief; `image_ops_status`; Open doubt if the tag is wrong |
| endless rerolls | no stop rule, defects fixed by regeneration | sheet, one factor per round, edits for local defects, stop after 3 flat rounds |
| generated logo or real face shipped | rights not checked | supplied vectors, fictional people, review gate |

## 12. Worked example: the webinar hero

1. Brief: the YAML of section 1; compiled prompt of section 2 (85 words).
2. Preflight: `image_ops_status` → GEN exposed via openrouter with `google/gemini-nano-banana-2.1`
   (honours seeds, 4:5 supported); no references, so REF is not needed.
3. Call (through `image-generator`, or directly):

```json
{"prompt": "<compiled prompt>", "aspect_ratio": "4:5", "size": "2K", "n": 4, "seed": 1207,
 "output_dir": ".stack/out/graphic-design-expert/webinar-hero-v1", "filename_prefix": "webinar-hero-v1"}
```

4. Sheet on the contact sheet (`imgcheck.py sheet`):

| Check | v1 | v2 | v3 | v4 |
|---|---|---|---|---|
| Subject accuracy | 2 | 2 | 2 | 1 |
| Composition | 1 | 2 | 1 | 1 |
| Palette | 2 | 1 | 2 | 2 |
| Light and style | 2 | 2 | 2 | 1 |
| Artefacts | 2 | 0 | 2 | 2 |
| Fitness in layout | 1 | 1 | 2 | 1 |
| Total | 10 | 8 (rejected: letter-like glyphs) | **11** | 8 |

5. The one defect in v3: a cluster of coral nodes at x 400-470, y 610-690 sits inside the left
   45% where the white headline goes; white on #EC4862 is 3.70:1, below 4.5. Edit brief for
   `image-editor`: copy v3 to `00-original.png`, then `"$PY" "$MT" rect 00-original.png
   01-mask.png --box 384,594,486,706` (the cluster grown by 16 px = max(8, 0.015 x 1080);
   overlay-check it with `masktool overlay`), then

```json
{"image": "00-original.png", "mask": "01-mask.png", "preserve_unmasked": true,
 "instruction": "Fill the masked area with the plain continuation of the deep navy #1A1A2E background and its soft falloff; keep the sphere, all other nodes, lines and lighting unchanged."}
```

   Verify: `masktool diff` outside MAE <= 0.5 and inside >= 2; worst-point contrast for the
   white headline box (60, 600)-(480, 760) (`kitcheck.py contrast` from sibling
   `social-asset-kit`) must reach 4.5:1, and plain #1A1A2E gives 17.06:1; palette check
   unchanged; sheet 12/12; `visual-reviewer` PASS (threshold 8).
6. Sidecar written (section 10), the trail kept, the hero handed to the layout (sibling
   `layout-grids-posters-editorial`).

Related: `image-generation`, `image-editing`, `vector-art`, `visual-review`, `social-asset-kit`,
`photo-retouch-composite`, `logo-design-process`, `layout-grids-posters-editorial`,
hub `graphic-design`.
