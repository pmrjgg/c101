# Rubric anchors (0-10 per criterion)

Use these anchors literally. Pick the highest score whose every statement is true of the output
at its target size, then apply the caps in section 8. Integers only. Evidence for each score is a
location (pixel box `x0,y0,x1,y1`, SVG element id, PDF page/OCG) plus a measurement or an exact
observation.

Contents: 1 brief fidelity, 2 composition and hierarchy, 3 typography and legibility, 4 colour and
contrast, 5 artefacts, 6 technical spec, 7 consistency with references, 8 caps, 9 per-type
readings, 10 calibration examples.

## 1. Brief fidelity (`fidelity`)

Primary requirements: subject, count, action, setting, medium/style family, framing, intended use.
Secondary: props, wardrobe, time of day, mood nuances, secondary objects, background details.

| Score | Anchor |
|---|---|
| 10 | Every primary and secondary requirement met exactly, including mood and intended use; a stakeholder signs off without comment |
| 9 | All primary and secondary requirements met; one negligible interpretive difference nobody would ask to change |
| 8 | All primary requirements met; at most one secondary detail off, fixable by one small revision |
| 7 | All primary requirements met; two or three secondary details off, or one clearly wrong |
| 6 | One primary requirement weakened (framing tighter than asked, style only partly right) but recognisably the brief |
| 5 | One primary requirement missing or wrong (wrong count, setting or style family) |
| 4 | Two primary requirements wrong |
| 3 | Right subject, wrong treatment overall (medium, mood and framing all off) |
| 2 | Subject only loosely related to the brief |
| 1 | Barely related; a keyword matched |
| 0 | Wrong subject, empty, refusal text, placeholder or missing file |

## 2. Composition and hierarchy (`composition`)

| Score | Anchor |
|---|---|
| 10 | One unmistakable focal point; reading order holds in a squint test; balance and negative space purposeful; copy-safe areas and every intended crop respected |
| 9 | As 10 with one negligible imbalance |
| 8 | Clear focal point and order; one minor issue (slightly tight crop, a tangent, mild clutter) that does not distract at target size |
| 7 | Focal point clear but a secondary element competes, or a tangent or awkward crop is noticeable |
| 6 | Readable but weak: default centring, cramped margins, or the copy-safe area partly occupied |
| 5 | Two competing focal points, or an important element cut by the frame edge |
| 4 | No clear focal point; clutter; the copy-safe area unusable |
| 3 | Subject cut off; unintended tilt of horizon or verticals that reads as an error |
| 2 | Chaotic; the eye has nowhere to land |
| 1 | Composition actively undermines the message |
| 0 | No discernible composition (noise, blank, fragment collage) |

Icons and logos: focal point = the silhouette; balance = optical centring in the viewBox; negative
space = the safe margin (2 px on a 24 px grid) and counters that stay open at small sizes.

## 3. Typography and legibility (`typography`)

| Score | Anchor |
|---|---|
| 10 | Every string exact; glyphs clean; spacing and type hierarchy professional; legible at the smallest target size; type character fits the brand |
| 9 | As 10 with one negligible spacing nit |
| 8 | Strings exact; minor kerning or baseline unevenness visible only when zoomed; legible at target size |
| 7 | Strings exact; spacing or weight issues visible at target size, or the smallest line borderline legible |
| 6 | Strings exact; one line hard to read at target size (too small, busy background) or type style mismatched to the brief |
| 5 | Strings exact but one glyph malformed, or visibly inconsistent letterforms within a word |
| 4 | Any misspelling, missing, extra or substituted character in a required string (cap) |
| 3 | Several errors, or one required string unreadable |
| 2 | Most text garbled |
| 1 | Text present only as glyph-like noise |
| 0 | Required text missing or replaced by pseudo-text |

Read every required string letter by letter on a zoom crop and write what you read in Evidence
(`"SUMMFR SALE" at 410,96,820,170`). In SVG, check `<text>` content and whether the brief wanted
live text (editable) or outlines (logos: outlines, so the mark does not depend on installed fonts).

## 4. Colour and contrast (`colour`)

Measure: brand hex vs sampled or declared colours (delta-E 76, snippet in the checklists
reference); WCAG contrast for every text and UI pair and for graphics needed to understand the
content.

| Score | Anchor |
|---|---|
| 10 | Palette exactly on brief (SVG exact hex; raster dE <= 2); harmonious roles; full, intentional tonal range; every text/UI pair passes the target WCAG level with margin |
| 9 | As 10; one pair passes by a small margin or one tonal nit |
| 8 | Palette on brief with minor drift (raster dE 2-5) or a slight cast; all required contrast passes |
| 7 | Noticeable drift or cast; or a needed non-text graphic below 3:1 |
| 6 | Palette recognisably on brand but one role colour off; or a large-text pair only just at 3:1 |
| 5 | A required text pair fails AA (cap); or visible banding or clipped highlights in a key area |
| 4 | Wrong palette family; several contrast failures |
| 3 | Colour undermines the message (garish, muddy) or a strong unintended cast |
| 2 | Palette contradicts the brief (warm asked, cold delivered) and contrast broadly fails |
| 1 | Broken colour (posterisation, channel swap) |
| 0 | Corrupt colour making the output unusable (inverted, wrong colour space interpretation) |

## 5. Artefacts (`artefacts`)

Generation and processing defects. Severity is judged at the target size after finding defects
with zoom crops.

| Score | Anchor |
|---|---|
| 10 | Nothing found in zoomed inspection of every risk region on the type's checklist |
| 9 | One trivial defect visible only at 3-4x zoom in a non-focal area |
| 8 | Minor defects visible only when zoomed; none at target size |
| 7 | One minor defect visible at target size in a non-focal area |
| 6 | One clear defect at target size in a non-focal area, or several minor ones |
| 5 | A defect in the focal area a viewer would notice (soft halo on the target background, odd fingernail, slight smear on a face) |
| 4 | Obvious defect (cap): extra, missing or fused fingers, wrong limb count, unrequested text or watermark, chopped subject edge, visible seam or tiling, duplicated object |
| 3 | Several obvious defects, or one that breaks the image (melted face, deformed product) |
| 2 | Defects dominate |
| 1 | Mostly artefact |
| 0 | Corrupted output (truncated file, noise, solid colour) |

Vectors: hairline gaps between adjacent shapes, slivers, self-intersections, broken or uneven
strokes, tracing noise (stair-stepped curves, hundreds of tiny specks) count here.

## 6. Technical spec (`technical`)

Machine-checkable items. List each one in the spec table with its check and result.

| Score | Anchor |
|---|---|
| 10 | Every item passes with margin; no junk metadata; sidecars complete |
| 9 | All pass; one item close to its limit (size budget >= 90%) |
| 8 | All required items pass; one nicety missing (`<title>`, precision above 2 decimals, unprefixed ids in a standalone file) |
| 7 | One required item marginal (aspect inside tolerance but off the requested grid; size budget exceeded by <= 25%) |
| 6 | One required item fails but is fixable without regeneration (missing viewBox, fixed width/height on an icon, size budget exceeded by <= 50%, unlabelled but correct layers) |
| 5 | Two such fixable failures, or node count 2-4x the budget |
| 4 | Dimensions or aspect beyond 2%; layered requested but not layered; non-binary mask where binary was required (cap) |
| 3 | Embedded raster passed off as vector; layered PDF requested but no `/OCProperties` (cap) |
| 2 | Alpha required but absent or fully opaque; wrong format for the use (JPEG where alpha or vector was needed) (cap) |
| 1 | Several fatal failures |
| 0 | Invalid or unsafe file: malformed SVG/PDF, unreadable raster, `<script>`, `<foreignObject>`, `on*=` handlers, external or `javascript:` references (cap) |

Default budgets when the brief sets none (the vector-art skill's `svgcheck.py --budget` values):
icon <= 4 KB, <= 40 paths, <= 2 decimals; logo <= 20 KB, <= 150 paths, <= 3 decimals;
illustration <= 150 KB, <= 2,500 paths, <= 3 decimals; raster <= 8 MB.

## 7. Consistency with references (`references`)

References are identity, product, style or layout images given in the brief; for edits, cutouts
and upscales the source image is the reference. Sets (icons, a campaign) are references for each
other.

| Score | Anchor |
|---|---|
| 10 | Identity or product indistinguishable; style matches; edits change nothing outside the mask (outside mean abs diff < 0.5, changed fraction < 0.1%) |
| 9 | Same identity or product; negligible differences |
| 8 | Clearly the same; small detail drift visible when zoomed (hair parting, label letter shape) |
| 7 | Same identity; one noticeable deviation (eye colour shade, product proportions ~5% off) |
| 6 | Recognisably the same but a stakeholder would comment; a set member with one stroke or radius inconsistency |
| 5 | Partial drift: product shape or label layout differs; style only partly matched; outside-mask mean 1-3 |
| 4 | Identity drift (a different person or product variant); outside-mask change visible: mean > 3 or changed fraction > 0.5% (cap) |
| 3 | Only the category matches (a bottle, not their bottle) |
| 2 | Reference ignored except its colours |
| 1 | Contradicts the reference |
| 0 | Reference fully ignored |

Measure outside-mask drift with the mask grown by 3 px, because the server feathers the
composite by 1-2 px at the boundary.

## 8. Caps (hard gates)

Score = min(anchor score, cap). Several caps can apply; the lowest wins.

| Condition | Criterion | Cap |
|---|---|---|
| Output missing or unreadable | - | review `Status: blocked`, no scores |
| Wrong subject | fidelity | 2 |
| Unrequested real-person likeness, trademark or logo | fidelity | 3 |
| Wrong count of a key subject, or an element the brief excluded is present | fidelity | 5 |
| Required string misspelled, missing or with an extra character | typography | 4 |
| Required text pair fails WCAG AA at its size | colour | 5 |
| Obvious anatomy error, watermark, unrequested text, seam, duplicated object | artefacts | 4 |
| Halo or fringe visible on the intended background at target size | artefacts | 5 |
| Dimensions or aspect beyond 2% of the spec | technical | 4 |
| Layered requested, single layer delivered (or layers unlabelled and wrong) | technical | 4 |
| Binary mask required, mask has > 1% grey pixels | technical | 4 |
| Embedded raster in an SVG delivered as vector (not requested) | technical | 3 |
| Layered PDF requested, no `/OCProperties` or OCG names unrelated to the SVG layers | technical | 3 |
| Alpha required, no alpha channel or alpha fully opaque | technical | 2 |
| Invalid or unsafe SVG/PDF | technical | 0 |
| Edit changed pixels outside the mask (grown 3 px): mean > 3 or changed > 0.5% | references | 4 |
| Identity of a provided person or product not preserved | references | 4 |

## 9. Per-type readings

| Type | `fidelity` means | `references` means | Notes |
|---|---|---|---|
| Photoreal | subject, action, setting, light, lens/framing | identity, product, style refs | anatomy and physics dominate artefacts |
| Illustration | subject, style family, medium, mood | style refs, character sheets | consistency of line and shading across the frame |
| Typography / logo | the concept, the exact name, the mark type (wordmark, lettermark, symbol) | brand guide, existing marks | test at 16 and 32 px; clear space |
| Icon / vector | metaphor, grid, stroke spec | the rest of the set | technical carries the most weight |
| Cutout | the whole subject kept, nothing of the background left | the source pixels (alpha transferred onto original pixels) | edges decide artefacts |
| Mask | the right region selected (the intended object, all of it, nothing else) | alignment with the source | binary, same size, white = edit |
| Edit / inpaint | the instruction executed exactly inside the region | everything outside the mask unchanged | judge seam blending at the mask boundary |
| Upscale | no invented content; target size reached | faithful to the source at matched scale | over-sharpening, ringing and waxy texture are artefacts |
| Layered SVG/PDF | content profile + the layer plan of the brief | layer names and order of the brief or source | technical +10 weight |

## 10. Calibration examples

**A. Poster, typography profile.** "SUMMER SALE" renders as "SUMMFR SALE"; everything else
excellent (fidelity 9, composition 9, colour 9, artefacts 8, technical 9, references 9). The
misspelling caps `typography` at 4 -> the round fails on the per-criterion rule whatever the
overall. Revision: region-edit of the text line, or pipeline: text-free background plus live text
layer.

**B. Product cutout, cutout profile.** Clean subject, but the strip over black shows a 2-3 px light
fringe along the left edge (ring luma 214 vs interior 61) -> `artefacts` 5 (cap applies when the
intended background is dark). Alpha transferred onto original pixels; drift note in the sidecar
says mean RGB drift 0.8 -> references 9. technical 10 (RGBA PNG, source size). Overall with
weights 15/5/5/35/25/15 over fidelity 9, composition 8, colour 9, artefacts 5, technical 10,
references 9: (135+40+45+175+250+135)/100 = 7.80 -> REVISE: cutout-fix with an alpha-band mask,
grow 4 px, feather 1 px.

**C. Icon set member, icon / vector profile.** svg_inspect: valid, viewBox 0 0 24 24, 6 elements,
palette `currentColor`; stroke-width 1.5 while the set uses 2 -> references 6; render at 24 px shows
a closed counter in the "e"-like loop -> artefacts 6; everything else 9. Passes only if overall >= 8:
weights 20/15/15/15/25/5 (typography N/A) over 9, 9, 9, 6, 9, 6 -> (180+135+135+90+225+30)/95 = 8.37,
lowest 6 -> PASS, with the two fixes listed as minor revisions for the caller's discretion.

**D. Masked edit, edit profile.** The new lamp looks right, but the outside-mask diff (mask grown
3 px) reports mean 4.2 and 1.9% changed: the adapter regenerated the whole frame and the
composite was skipped. `references` capped at 4 -> REVISE: re-run `image_edit` with the mask and
`preserve_unmasked` left at its default (true); verify outside mean < 1.0.
