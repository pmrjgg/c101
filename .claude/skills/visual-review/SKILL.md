---
name: visual-review
description: "Independent quality review of raster images, edits, cutouts, masks, upscales, SVG vectors and layered SVG/PDF deliverables against their brief: a weighted 0-10 rubric with score anchors (brief fidelity, composition and hierarchy, typography and legibility, colour and contrast, artefacts, technical spec, consistency with references), the PASS rule (overall >= threshold, default 8, and no criterion below 6), artefact checklists per output type, render-and-inspect recipes with the image MCP server's local tools, revision instructions that converge (prompt deltas, masked region edits, SVG fixes), stop rules and the review report format. Preloaded by visual-reviewer; load it whenever you judge or iterate on a visual output."
when_to_use: "Scoring an image, vector or layered PDF against a brief; writing revision instructions for image-generator, image-editor or vector-artist; deciding whether an iteration loop continues, reverts or stops; reading a visual-reviewer report or its JSON."
---

# Visual review

A review measures an output against its brief and returns one of three verdicts: **PASS**,
**REVISE** (with instructions the producer can execute without interpretation) or **STOP**
(further rounds are not worth it; deliver the best attempt with the trail). It is evidence, not
taste: every score cites a location and a measurement, every weakness maps to a revision, and the
verdict is computed in code from the scores.

Deep material: [rubric anchors](references/rubric-anchors.md) (0-10 anchors for every criterion,
caps, calibration examples) and [artefact checklists](references/artifact-checklists.md) (per
output type, with the Pillow and pikepdf inspection snippets).

## 1. Protocol at a glance

| # | Step | Output |
|---|---|---|
| 1 | Read `<stack-context>`; create the review directory | `.stack/out/visual-reviewer/<stamp>-<slug>-r<N>/` |
| 2 | `mcp__image__image_ops_status` | which operations are exposed, so every revision is executable |
| 3 | Spec and weights from the brief only, BEFORE opening any output | `<dir>/spec.json`: requirements, profile, weights, N/A criteria |
| 4 | Previous reviews (JSON) | revision ledger, trend, best round so far |
| 5 | Technical pass per file | `image_info` / `svg_inspect` / `svg_layers` / OCG check / sidecar |
| 6 | Look at target size, then zoom | renders, crops, background strips, overlays, side-by-sides |
| 7 | Artefact checklist for the output type | findings: `where - what - measurement` |
| 8 | Score each applicable criterion with anchors, then caps | integer 0-10 + evidence per criterion |
| 9 | Aggregate in code | overall, lowest criterion, pass |
| 10 | Verdict with the stop rules | PASS, REVISE or STOP |
| 11 | Revisions and KEEP list (unless PASS) | ordered, owner + tool + region + verify |
| 12 | Report `.md` + `.json`, reply per output-contract | paths and line anchors |

## 2. Tools

Reviewers use only inspection tools. Argument names follow the schema the `image` server
publishes; the signatures below are the stack's design.

| Tool | Use |
|---|---|
| `mcp__image__image_ops_status()` | per operation: exposed or not, adapter, URL host, model tag, missing env names (never keys) |
| `mcp__image__image_info(image)` | size, mode, has alpha, format, file size of a raster |
| `mcp__image__svg_inspect(svg_path)` | well-formedness, viewBox/size, element and path counts, palette, layers, text elements, embedded rasters, complexity, flagged problems |
| `mcp__image__svg_layers(svg_path)` | top-level layers: id, label, visibility, element count, palette |
| `mcp__image__svg_render(svg_path, width?, background?)` | PNG preview of an SVG; Read the PNG it returns |
| Read | views PNG/JPEG/WebP/GIF (large images are downscaled for viewing, so zoom crops for detail); PDFs with `pages: "1"`; sidecars `<file>.json` |
| Bash with Pillow / pikepdf (stack venv) | crops, background strips, overlays, diffs, alpha and mask statistics, contrast, palette deltas, PDF OCG checks |

```bash
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"   # Pillow, pikepdf, resvg_py
```

Shell variables do not persist between Bash calls: put the `PY=` line in every command that uses it.
Never call the producing tools (`image_generate`, `image_generate_with_references`, `image_edit`,
`image_generate_transparent`, `image_segment`, `image_remove_background`, `image_upscale`,
`vector_generate`, `image_vectorize`, `svg_transform`, `svg_layerize`, `layers_compose`,
`export_pdf`, `svg_optimize`, `mask_convert`): the reviewer judges, the producer fixes. If the
`image` server is not connected, use the Pillow and `resvg_py` fallbacks in the checklists
reference, say so in Evidence, and return an Open doubt because feasibility is then unknown.

## 3. The rubric

| Key | Criterion | Covers | N/A when |
|---|---|---|---|
| `fidelity` | Brief fidelity | subject, count, action, setting, style/medium, framing, mood, required and excluded elements, intended use | never |
| `composition` | Composition and hierarchy | focal point, reading order, balance, cropping, negative space, copy-safe areas, crop safety | masks, upscales (the source's composition is kept) |
| `typography` | Typography and legibility | exact strings, spelling, glyph integrity, spacing, type hierarchy, legibility at target size, live text vs outlines | no text requested and none required (stray glyphs are `artefacts`) |
| `colour` | Colour and contrast | palette vs brief/brand hex, harmony, tonal range, casts, WCAG contrast for text, UI and key graphics | masks |
| `artefacts` | Artefacts | anatomy, garbling, seams, duplicates, smears, banding, halos, chopped edges, mask speckles, jaggies, hairline gaps, tracing noise | never |
| `technical` | Technical spec | format, dimensions/aspect (2% tolerance), alpha, size budget, SVG validity and safety, viewBox, node count, palette size, layers, PDF OCGs and page size, mask convention, sidecar | never |
| `references` | Consistency with references | identity/product likeness, style refs, set consistency, faithfulness to a source image (edits, cutouts, upscales: unmasked pixels unchanged) | no reference and no source image |

**Weight profiles** (percent; `-` = N/A for that type unless the brief makes it relevant; N/A
criteria drop out of both sums). JSON and workflow keys: `default`, `photoreal`, `illustration`,
`typography-logo`, `icon-vector`, `cutout`, `mask`, `edit`, `upscale`.

| Profile | fidelity | composition | typography | colour | artefacts | technical | references |
|---|---|---|---|---|---|---|---|
| default | 25 | 15 | 10 | 10 | 15 | 15 | 10 |
| photoreal | 25 | 15 | 5 | 10 | 20 | 10 | 15 |
| illustration | 25 | 20 | 5 | 15 | 15 | 10 | 10 |
| typography / logo | 20 | 15 | 25 | 10 | 10 | 15 | 5 |
| icon / vector | 20 | 15 | 5 | 15 | 15 | 25 | 5 |
| cutout (RGBA) | 15 | 5 | - | 5 | 35 | 25 | 15 |
| mask | 30 | - | - | - | 30 | 30 | 10 |
| edit / inpaint | 25 | 10 | 5 | 10 | 20 | 10 | 20 |
| upscale | 10 | - | 5 | 10 | 35 | 20 | 20 |

Rules:
- Pick the profile from the deliverable, not from the tool that made it (a logo generated by
  `image_generate` is `typography / logo`). Layered SVG/PDF deliverables use their content profile
  with `technical` +10. Each file of a mixed deliverable (PNG + SVG + PDF) is scored with its own
  profile; the deliverable passes only when every required file passes.
- A brief may set its own weights or threshold; use them and record them.
- Weights, profile and threshold are fixed in round 1 and reused every round. Never change them to
  make an output pass.

## 4. Scoring

Generic anchors (criterion-specific anchors for every value 0-10 are in
[rubric-anchors.md](references/rubric-anchors.md)):

| Score | Meaning |
|---|---|
| 10 | Nothing to fix even after zooming every risk region; exceeds the brief |
| 8 | Client-ready: minor issues only visible when zoomed, none at target size |
| 6 | Usable with caveats: one clear issue at target size, or several minor ones |
| 4 | Rejected by any careful client: an obvious defect or a hard-gate failure |
| 2 | Barely related to what was asked, or broken in most of the image |
| 0 | Missing, wrong subject, corrupt, invalid or unsafe file |

Odd scores sit between the neighbouring anchors: all of the lower one, part of the upper one.

- **Integers only.** Start at the anchor that matches the worst true statement, not the overall
  impression.
- **Target size decides severity.** Zoom to find defects, then judge them at the size the output
  will be used (thumbnail, 1080 px social post, 24 px icon, A4 print at 300 dpi). Print, hero and
  zoomable deliverables are judged at 100%.
- **Caps** (hard gates) override the anchors: score = min(anchor score, cap). Most used caps:
  required text misspelled -> `typography` <= 4; excluded element present or wrong subject count ->
  `fidelity` <= 5 (unrequested real-person likeness or trademark <= 3, wrong subject <= 2); obvious
  anatomy error, watermark or seam -> `artefacts` <= 4;
  dimensions or aspect beyond 2% -> `technical` <= 4; alpha required but absent -> `technical` <= 2;
  invalid or unsafe SVG -> `technical` = 0; layered requested but not layered -> `technical` <= 4;
  pixels changed outside an edit mask -> `references` <= 4; required text pair fails WCAG AA ->
  `colour` <= 5. Full table in the anchors reference.
- **Evidence per score**: location (pixel box `x0,y0,x1,y1` in the reviewed file, SVG element id,
  PDF page/OCG) plus a measurement or an exact observation. A score below 8 names at least one
  defect and maps to at least one revision. A 9 or 10 states which risk regions were zoomed.
- **Pixels, not prompts.** Score `fidelity` from the brief and the image before reading the
  sidecar prompt; read the prompt afterwards to diagnose causes and write deltas.
- **Variants.** Score every variant; rank by overall; write revisions for the best one only.

## 5. Aggregation and the PASS rule

```
overall = round( sum(w_i * s_i) / sum(w_i), 2 )      over applicable criteria only
PASS    = overall >= threshold (default 8.0)  AND  every applicable s_i >= 6
```

Compute it in code, never mentally:

```bash
python3 -I - <<'EOF'
import json
s = {"fidelity": 8, "composition": 8, "typography": None, "colour": 9, "artefacts": 6, "technical": 10, "references": 7}
w = {"fidelity": 25, "composition": 15, "typography": 5, "colour": 10, "artefacts": 20, "technical": 10, "references": 15}
T = 8.0
a = {k: v for k, v in s.items() if v is not None}
o = round(sum(w[k] * a[k] for k in a) / sum(w[k] for k in a), 2); lo = min(a, key=a.get)
print(json.dumps({"overall": o, "lowest": [lo, a[lo]], "pass": o >= T and a[lo] >= 6}))
EOF
```

Worked example (photoreal, no text, so `typography` N/A): weights sum 95, weighted sum 735,
overall 7.74, lowest `artefacts` 6 -> REVISE. Fixing the hand defect (`artefacts` 6 -> 8) gives
775 / 95 = 8.16 with lowest 7 -> PASS. A single 5 fails the round however high the overall is.

Borderline: an overall within 0.3 of the threshold, or a verdict decided by one subjective
criterion, lowers Confidence and is stated in Open doubts (the caller may ask for a second blind
review).

## 6. Rendering and inspection

| Output | Look at |
|---|---|
| Raster | Read the file; then Read 2-4x nearest-neighbour crops of every risk region (faces, hands, text, edges, horizon, seams); for more than 2 variants, one contact sheet first |
| SVG | `svg_render` at each target width plus 1024 (2048 for detailed illustrations); icons at 16, 24, 32, 48 and 256; logos at 16, 32, 64 and 512; on light and dark backgrounds when used on both |
| RGBA cutout | strip over black, white, magenta, green and the intended background; zoom the hair, glass and shadow edges |
| Mask | red overlay on the source; histogram (binary?), coverage, speckles; size equals the source |
| Edit, upscale, cutout | side by side with the source at the same scale; outside-mask diff for edits |
| Layered SVG | `svg_layers`; one render per layer (layer-split snippet) plus the full render |
| Layered PDF | OCG check (pikepdf snippet); Read the PDF page (`pages: "1"`) or `sips -s format png f.pdf --out f.png` on macOS; compare with `svg_render` of the source SVG |
| References | side-by-side sheet: output next to each reference at the same height |

Core snippets (write every artefact into the review directory, never next to the deliverable):

```bash
# zoom crop: IN OUT x0,y0,x1,y1 FACTOR
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I -c "import sys;from PIL import Image as I;im=I.open(sys.argv[1]);c=im.crop(tuple(map(int,sys.argv[3].split(','))));k=int(sys.argv[4]);c.resize((c.width*k,c.height*k),I.NEAREST).save(sys.argv[2])" in.png <review-dir>/zoom-hand.png 1312,640,1490,812 3
```

```bash
# WCAG contrast: FILE (or -) and two colours, each '#rrggbb' or a sample box x0,y0,x1,y1 (median colour)
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I - poster.png 120,860,180,890 '#ffffff' <<'EOF'
import sys
from PIL import Image, ImageStat
im = Image.open(sys.argv[1]).convert("RGB") if sys.argv[1] != "-" else None
def rgb(a):
    return [int(a[i:i + 2], 16) for i in (1, 3, 5)] if a.startswith("#") else ImageStat.Stat(im.crop(tuple(map(int, a.split(","))))).median[:3]
def lum(c):
    c = [v / 255 for v in c]; c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
hi, lo = sorted((lum(rgb(sys.argv[2])), lum(rgb(sys.argv[3]))), reverse=True); r = (hi + 0.05) / (lo + 0.05)
print("%.2f:1 AA-text %s AA-large/graphics %s AAA-text %s" % (r, r >= 4.5, r >= 3, r >= 7))
EOF
```

WCAG 2.x thresholds: 4.5:1 normal text, 3:1 large text (>= 24 px regular or >= 18.66 px bold) and
non-text graphics needed to understand the content (1.4.11), 7:1 for AAA text. Sample text colour
from the glyph interior, background from right beside the glyph; on busy photos take the worst
local background. Background strips, alpha and halo statistics, mask statistics, edit diffs, palette
delta-E, layer splits, the PDF OCG check and the `resvg_py` fallback render are in
[artifact-checklists.md](references/artifact-checklists.md#inspection-snippets).

## 7. Artefact checklists (summary)

Run the full list for the output type from [artifact-checklists.md](references/artifact-checklists.md).

| Type | Highest-yield checks |
|---|---|
| Photoreal | hands and fingers, eyes and teeth, text on objects, reflections and shadows agreeing with the light, straight lines, duplicated objects, skin plasticity |
| Illustration | style consistency across the frame, line weight, stray marks, perspective, unintended text |
| Typography / logos | every string letter by letter, kerning, glyph shapes, legibility at the smallest size, outlines vs live text, clear space |
| Cutouts (RGBA) | halos on dark and light backgrounds, chopped hair, residual background haze, holes, alpha bbox touching the edge |
| Masks | binary, same size as source, covers the whole target plus margin, no speckles or holes, correct convention (white = edit) |
| SVG / vector | validity and safety, viewBox and aspect, node and path count vs budget, palette vs brand hex and near-duplicates, live text, embedded rasters, hairline gaps |
| Layered SVG | top-level `inkscape:groupmode="layer"` groups with labels, nothing outside layers, z-order, no empty layers, names match the brief |
| Layered PDF | `/OCProperties` lists one OCG per SVG layer with the same labels and order, content bound to OCGs, `/OFF` only for hidden layers, vector pages, page size |

## 8. Revision instructions that converge

A revision is a change the producer can apply literally. Fields (JSON keys in section 10):
`id`, `severity` (blocking: fixes a criterion < 6 or a cap; major: needed to reach the threshold;
minor: polish), `criterion`, `action`, `owner` (agent), `tool`, `op` (`IMAGE_<OP>`), `target`
file, `region` or element, `instruction` (exact text), `keep`, `expected` (criterion -> score),
`verify` (the check that proves it worked).

**Choose the action from the defect's scope:**

| Defect scope | Action | Owner and tool |
|---|---|---|
| Global: wrong subject, framing, style, light, palette family | `prompt-delta` | `image-generator`: `image_generate`, `image_generate_with_references`, `image_generate_transparent`; `vector-artist`: `vector_generate` |
| Local, in an otherwise good image (overall >= 7, defect area < ~25%) | `region-edit` + `mask` | `image-editor`: `image_edit` with a mask (from `image_segment` or a drawn rect/ellipse/polygon) |
| Cutout edges, residual background | `cutout-fix` | `image-editor`: `image_remove_background`, mask grow/feather, re-composite |
| Resolution or sharpness below spec | `upscale` | `image-editor`: `image_upscale` |
| Wrong size, aspect, format, background, n, seed | `param` | the producer: same prompt, changed parameter |
| SVG structure, palette, viewBox, layers, safety, node count | `svg-fix` | `vector-artist`: Read/Edit of the SVG text (`svg_transform` only when exposed), `svg_optimize`, `svg_layerize`, `layers_compose`, `export_pdf` |
| The approach cannot reach the brief | `pipeline` | the caller: e.g. text-free raster + live type layer, trace instead of generate, compose layers |

**Prompt deltas** are edits to the exact previous prompt (read it from the sidecar), never a
rewrite:

```
R2 [major] composition - prompt-delta - image-generator / image_generate (IMAGE_GEN)
Base: prompt in .stack/images/20261019/02-hero.png.json
ADD (first sentence): "Wide shot, camera at eye level, the woman on the left third, empty wall on the right for copy."
REPLACE: "a few plants" -> "two potted plants"
REMOVE: "dramatic"
KEEP: every other word; aspect_ratio 16:9; seed 4242 if the adapter honours it
Expected: composition 6 -> 8   Verify: right 40% of the frame free of objects in the render
```

Rules: at most 3 deltas per revision; the most important constraint first; counts as numerals;
exact text strings in double quotes and at most ~5 words; describe what fills a space rather than
"no X" (one explicit exclusion at the end is fine); never contradict a previous round's delta
without saying it reverts it.

**Region edits and mask suggestions:**

```
R1 [blocking] artefacts - region-edit - image-editor / image_edit (IMAGE_EDIT)
Target: 02-hero.png (2048x1152). Region: ellipse in box 1312,640,1490,812 (left hand).
Mask: white = edit; image_segment "the woman's left hand" if exposed, else drawn ellipse; grow 16 px, feather 2 px.
Instruction: "a relaxed left hand with five fingers resting on the table edge, same skin tone and window light"
Keep: everything outside the mask (unmasked pixels are preserved by the server)
Expected: artefacts 6 -> 8   Verify: zoom shows 5 fingers; outside-mask mean abs diff < 1.0
```

| Defect | Mask shape | Grow | Feather |
|---|---|---|---|
| Hand, fingers, ear, small object | ellipse or segment prompt | 12-24 px | 2 px |
| Text line on a sign or label | rectangle around the line | 8 px | 0-1 px |
| Face detail (eyes, teeth) | ellipse | 8 px | 2 px |
| Hair edge, halo on a cutout | alpha band (edge ring of the cutout) | 4-8 px | 1 px |
| Background replacement | segment the subject, invert | -2 px (keep subject edge) | 1-2 px |

Masks use the canonical convention (single-channel PNG, source size, white = edit); the server
converts per adapter. Give coordinates in the reviewed file's pixel space.

**SVG fixes** are element-level edits:

```
R3 [blocking] technical - svg-fix - vector-artist / Read+Edit (svg_transform not exposed)
Target: logo.svg
1. root <svg>: keep viewBox="0 0 512 512"; remove width="2000" height="2000"
2. fill "#3a80f0" -> "#3b82f6" (brand) on #mark-ring and all 7 other occurrences (dE76 2.3)
3. move #wordmark into <g id="layer-text" inkscape:groupmode="layer" inkscape:label="Text">
4. delete <image id="image0"> (embedded 412 KB raster passed off as vector)
5. svg_optimize precision 2, then export_pdf layered=true
Expected: technical 3 -> 9, colour 6 -> 9   Verify: svg_inspect 0 rasters, palette {#0f172a,#3b82f6,#ffffff}; OCGs [Background, Mark, Text]
```

**KEEP list**: name what scored >= 8 and must not regress ("keep the warm window light", "keep
the 3-colour palette", "keep the layer names"). Producers apply revisions and leave KEEP items
untouched.

**Ledger and strategy ladder.** Before writing revisions, read the previous rounds' revisions and
their outcome. A defect that survived one strategy gets the next rung, never the same instruction
again:

| Persistent defect | Rung 1 | Rung 2 | Rung 3 |
|---|---|---|---|
| Garbled raster text | shorten and quote the string | region-edit of the text line | pipeline: text-free raster + live text layer (`layers_compose`) |
| Anatomy (hands, faces) | prompt delta: simpler or occluded pose | region-edit with mask | STOP with Open doubt (model choice) |
| Composition / framing | framing sentence first + aspect | `image_generate_with_references` with the best round as layout ref | pipeline: compose layers |
| Identity or product drift | fewer, better refs; identity sentence first | region-edit of face or label with the ref | STOP with Open doubt |
| Cutout halos, chopped hair | `image_remove_background` on the original | mask band grow/feather + re-composite | regenerate with `image_generate_transparent` |
| SVG palette off | svg-fix remap to exact hex | regenerate with the palette in the prompt + svg-fix | - |
| Trace too complex | `svg_optimize` + palette reduction | re-trace from a flat, cleaner (upscaled) source | hand-redraw the simple shapes |

**Feasibility.** Every revision's `op` must be exposed in `image_ops_status`. When the best fix
needs a missing op, give the best feasible alternative as the revision and add an Open doubt such
as `[scope|med] masked edit needs IMAGE_EDIT - set IMAGE_EDIT_URL, IMAGE_EDIT_KEY, IMAGE_EDIT_MODEL
in ~/.claude/stack.env, then reconnect the image server via /mcp - route: user`. Never suggest a
different provider or a fallback model; changing a model tag is the user's decision.

| Vague (never) | Convergent |
|---|---|
| "Improve the composition" | "ADD first: 'subject on the left third, right 40% empty'; expected composition 6 -> 8" |
| "Fix the hands" | "region-edit ellipse 1312,640,1490,812, grow 16, feather 2, instruction '...five fingers...'" |
| "Colours feel off" | "#3a80f0 -> #3b82f6 on 8 elements (dE76 2.3 from brand)" |
| "Text is not great" | "'SUMMER SALE' renders as 'SUMMFR SALE' at 410,96,820,170: region-edit the line, quote the string" |
| "Looks great!" | nothing: PASS needs no adjectives, only scores and evidence |

## 9. Stop rules

| Condition (checked in this order) | Verdict | Recommendation |
|---|---|---|
| PASS rule met | PASS | deliver this output |
| `budget="hard"` | STOP | deliver best so far; minimal review only |
| Brief contradictory or unachievable with exposed ops | STOP | scope doubt to the caller; name the missing env vars |
| round >= maxRounds (default 4) | STOP | deliver best so far with the trail |
| Same blocking defect after two different strategies | STOP | Open doubt: model choice or human decision |
| Best overall rose < 0.3 in each of the last two rounds (plateau) | STOP | deliver best; say what would change the outcome |
| `budget="soft"` | STOP | deliver best so far; exception: REVISE with that single fix when PASS is one cheap local fix away (one region edit or one SVG text edit, no regeneration) |
| Overall < best - 0.5 (regression) | REVISE | revert to the best round's inputs and use the next ladder rung |
| Otherwise | REVISE | apply the revisions |

**Best so far**: highest overall among rounds with no criterion < 6; if none, highest overall;
ties go to fewer blocking revisions, then the later round. The reviewer recommends; the producer
or the `visual-iterate` workflow enforces the round count and the plateau (the workflow applies
these same rules in code and honours an early STOP).

## 10. Report format

Files: `.stack/out/visual-reviewer/<YYYYMMDD-HHMM>-<slug>-r<N>.md`, the sibling `.json`, and the
directory `<same stem>/` for renders, crops and `spec.json`. When the caller names report paths
(the `visual-iterate` workflow passes `.stack/out/visual-iterate/<slug>/review-round-<N>.md`), use
those instead, with the same `.json` sibling and `<stem>/` directory. Never overwrite (`-2`, `-3`).

```markdown
# Visual review - <slug>, round <N>/<maxRounds>
## Summary
Verdict: REVISE - overall 7.74 / threshold 8.00 - lowest artefacts 6 - best so far: round 2 (7.74)
Profile photoreal (typography N/A). Ops exposed: GEN, REF, EDIT. Missing: SEGMENT.
Blocking: R1. Next owner: image-editor.
## Spec            | # | requirement (from the brief) | check | result |
## Scores          | criterion | weight | score | cap | evidence |   (last row: overall, computed)
## Findings        per output: checklist id - location - observation - measurement - criterion
## Revisions       one block per revision, grammar of section 8, blocking first
## Keep
## Trend           | round | output | overall | lowest | verdict | change applied |
## Stop recommendation   rule that fired, best round, what would change the outcome
## Inspection artefacts  renders, crops, strips, overlays (paths)
```

```json
{"schema": "visual-review/1", "slug": "", "round": 2, "max_rounds": 4, "threshold": 8.0,
 "profile": "photoreal", "outputs": [{"path": "", "type": "photoreal", "sidecar": ""}],
 "ops": {"exposed": ["GEN", "REF", "EDIT"], "missing": {"SEGMENT": ["IMAGE_SEGMENT_URL", "IMAGE_SEGMENT_KEY", "IMAGE_SEGMENT_MODEL"]}},
 "weights": {"fidelity": 25, "composition": 15, "typography": null, "colour": 10, "artefacts": 20, "technical": 10, "references": 15},
 "scores": {"fidelity": {"score": 8, "cap": null, "evidence": ""}, "typography": null},
 "overall": 7.74, "lowest": {"criterion": "artefacts", "score": 6}, "pass": false, "verdict": "REVISE",
 "revisions": [{"id": "R1", "severity": "blocking", "criterion": "artefacts", "action": "region-edit",
   "owner": "image-editor", "tool": "image_edit", "op": "IMAGE_EDIT", "target": "",
   "region": {"box": [1312, 640, 1490, 812], "shape": "ellipse"}, "mask": {"source": "drawn", "grow_px": 16, "feather_px": 2},
   "instruction": "", "keep": "", "expected": {"artefacts": 8}, "verify": ""}],
 "keep": [], "trend": [{"round": 1, "overall": 7.1, "lowest": 5, "verdict": "REVISE"}, {"round": 2, "overall": 7.74, "lowest": 6, "verdict": "REVISE"}],
 "best": {"round": 2, "path": "", "overall": 7.74},
 "stop": {"recommend": "continue", "rule": "none", "reason": ""}, "artefacts_dir": ""}
```

`scores` lists all seven keys (`null` when N/A). Validate with `python3 -I -m json.tool <file> >/dev/null`.
When the caller or a workflow supplies its own schema (the `visual-iterate` workflow asks for
`scores`, `profile`, `overall`, `pass`, `verdict`, `revisions`, `best_path`, `not_applicable`,
`blockers`, `keep`, `report`), its field names win: scores as plain numbers keyed by the seven
criterion keys above (`null` when N/A), cap failures in `blockers`, and each revision as one line
`R1 [blocking] image-editor/image_edit (IMAGE_EDIT): <instruction> | region <box> | mask grow 16 feather 2 | keep <...> | verify <check>`.

## 11. Worked example (round 2 of a hero image)

Brief: 2048x1152 photoreal hero, woman reading by a window, warm light, right 40% empty for copy,
two references (her face, the brand mug). Profile photoreal; no text -> `typography` N/A.
`image_info`: 2048x1152 RGB PNG -> technical 10. Subject, light and mood on brief -> fidelity 8;
warm palette, no clipping -> colour 9. Zoom of 1312,640,1490,812: six fingers -> `artefacts` capped
at 4. Mug label and face match the references -> references 8. A lamp at 1580,210,1790,700 fills
the copy area -> composition 6. Overall 680 / 95 = 7.16, lowest 4 -> REVISE.
R1 [blocking] region-edit of the hand (box above, grow 16, feather 2). R2 [major] region-edit
removing the lamp (box 1580,210,1790,700) rather than regenerating, because KEEP covers the face,
light and mug. Expected after both: artefacts 8, composition 8 -> overall 8.32 -> PASS next round.

## 12. Reviewer failure modes

| Failure | Guard |
|---|---|
| Leniency drift across rounds | anchors and caps applied literally; compare with the previous round's evidence |
| Anchoring on the prompt or the producer's claims | spec from the brief before looking; pixels before sidecar |
| Judging a downscaled preview | zoom crops of every risk region; render SVGs at target sizes |
| Mental arithmetic | overall and pass computed by the snippet |
| Scoring an N/A criterion (or N/A-ing a weak one) | N/A only per the table in section 3 |
| Moving goalposts | weights, profile and threshold fixed in round 1 |
| Too many changes per round | at most 3 major revisions; blocking first; KEEP list |
| Repeating a failed instruction | ledger plus strategy ladder |
| Recommending an unconfigured op | check `image_ops_status`; name the env vars instead |
