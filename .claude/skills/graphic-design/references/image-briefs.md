# Image briefs for generators, editors and vectorisers

Model capabilities change monthly. Do not hard-code a model in a brief unless the capability
requires it; state the capability ("needs exact short text", "needs transparent RGBA", "needs 3
reference images for character consistency"); the user's per-operation configuration decides the
model. `image_ops_status` on the `image` server says which operations are configured.

## 1. Structured brief (fill first, then compile)

```yaml
id: webinar-hero-v1
purpose: hero illustration for LinkedIn feed post; headline overlays the left side
placement: 1080x1350 canvas, image occupies right 55%; left 45% must be empty, low-detail
subject: abstract network of glowing nodes and thin connecting lines forming a loose sphere
composition: sphere centred at 70% width, 45% height; bleeds off right edge; generous negative space left
style: clean 3D render, soft depth of field, minimal, no photographic objects
light: soft rim light from upper right, subtle bloom on nodes
palette: background #1A1A2E; nodes #EC4862 and #56B4E9; lines #E6E6F0 at low opacity
text_in_image: none (all text set in layout)
exclusions: no text, no letters, no logos, no people, no busy texture in the left 45%
technical: aspect_ratio 4:5; n 4; seed 1207; transparent_background false; quality high
references: []
acceptance:
  - left 45% luminance variance low enough for white text at 4.5:1 everywhere
  - palette within ΔE(OK) ~0.05 of the listed hexes for dominant colors
  - no text-like artefacts
```

## 2. Compile rules (brief → prompt)

1. Order: subject → setting → composition/framing → style/medium → light → palette → mood →
   exclusions. One idea per sentence; concrete nouns and measurable positions.
2. State positions and space numerically ("subject in the right third", "empty left 45%").
3. Palette as hex values with roles; mention background value explicitly (dark, mid, light).
4. Exclusions as positive constraints where possible ("plain, empty background on the left")
   plus one short "no ..." sentence; long negative lists tend to introduce the listed items.
5. Text: exact strings in double quotes, with case, plus font character ("bold geometric sans");
   keep ≤ ~5 words per string; long copy goes into the layout, never into the generation.
6. References: say what each image contributes ("Image 1 is the product: keep its shape, label and
   cap exactly. Image 2 sets the lighting mood only.").
7. Avoid living artists' names and trademarks; describe the stylistic properties instead
   (medium, line quality, palette, era, movement).
8. Keep the compiled prompt under ~120 words for most models; more words dilute priority.

Compiled from the brief above:

```
Abstract network of glowing nodes connected by thin lines, forming a loose sphere centred at 70%
of the width and slightly above centre, bleeding off the right edge. The left 45% of the image is
plain, dark, empty background. Clean minimal 3D render with soft depth of field. Soft rim light
from the upper right, subtle bloom on the nodes. Background deep navy #1A1A2E, nodes coral pink
#EC4862 and sky blue #56B4E9, faint light-gray lines #E6E6F0. Calm, technical, premium mood.
No text, letters or logos.
```

Tool call (through image-generator, or directly):

```json
{"prompt": "<compiled prompt>", "aspect_ratio": "4:5", "n": 4, "seed": 1207,
 "quality": "high", "transparent_background": false,
 "output_dir": ".stack/out/graphic-design-expert/webinar-hero-v1"}
```

## 3. Placement presets

| Placement | Aspect | Typical pixels | Notes |
|---|---|---|---|
| Feed post (Instagram, LinkedIn portrait) | 4:5 | 1080 × 1350 | keep key content inside centre 1:1 for grid crops |
| Story / Reel / Shorts | 9:16 | 1080 × 1920 | top ~14% and bottom ~20% covered by UI |
| Square | 1:1 | 1080 × 1080 | |
| Open Graph / link preview | 1.91:1 | 1200 × 630 | text ≥ 48 px; center-safe for cropping to 1:1 |
| Slide / video | 16:9 | 1920 × 1080 | 5% title-safe margin |
| Web hero | 16:9 to 21:9 | 1920-2560 wide | design art-direction crops for mobile (4:5) |
| A-series print | 1:1.414 | A4 at 300 ppi 2480 × 3508 | generate near 3:4 or 2:3, then outpaint/crop and upscale; add 3 mm bleed |
| Banner | 3:1 to 4:1 | e.g. 1500 × 500 | generate wider than needed; crop |

Generate at the model's native resolution, edit, then upscale as the last step
(`image_upscale`), then export.

## 4. Genre templates

**Product shot on seamless.** "[Product, with reference image 1 for exact shape and label] standing
on a seamless [color] backdrop, three-quarter view at eye level, 85 mm lens look, f/8, softbox key
light from the left with a white fill card on the right, soft contact shadow, crisp label text
exactly as in the reference." Use references; verify label text character by character; fix
small defects with masked edits (`image_segment` "the label" → `image_edit`).

**Editorial portrait (fictional person).** Subject description (age range, expression, wardrobe),
environment, shot size (head-and-shoulders), lens (85 mm), light (window light, soft, 45° key),
color grade (muted, warm). Never generate a real, identifiable person without documented consent.

**Isometric illustration.** "Isometric illustration, 30° angles, flat colors with one level of
shading, 2 px dark outlines, palette [hexes], white background, no perspective distortion." For
a consistent set, fix seed and reuse the first accepted image as a style reference.

**Flat spot illustration / icon set.** Prefer `vector_generate` {prompt, style}; specify stroke
width, corner radius, fill vs outline, canvas 24 × 24 for icons. Then `svg_optimize`. Validate
with the icon audit in SKILL.md section 7.

**Logo exploration.** Generate directions only as vectors (`vector_generate`) or as sketches;
the final logo is drawn and refined as vector by a human or the vector-artist with clean geometry.
Raster-generated logos are not deliverables.

**Abstract background for text.** Specify where text goes and require low detail and low contrast
there; check contrast at the worst point after placing text; add a scrim if needed.

**Seamless pattern / texture.** "Seamless tileable pattern" in the prompt is not enough; verify by
tiling 2 × 2 and fix seams with masked edits across the borders (offset by half the tile first).

**Transparent cut-out (sticker, product on alpha).** Use `transparent_background: true` (routes to
alpha-capable models) or generate on a flat contrasting background and run
`image_remove_background`. Inspect edges on both black and white backgrounds for halos; hair and
glass need a matting-quality remover.

## 5. Editing instructions (image-editor)

| Defect | Operation |
|---|---|
| Local artefact (hand, text glitch, stray object) | `image_segment` {prompt: "the left hand"} → `image_edit` {instruction: "a relaxed hand with five fingers resting on the table", mask} |
| Wrong color of an object | masked edit with exact hex, or global edit "change the jacket to #2563EB, keep everything else identical" |
| Need more canvas (outpaint) | pad canvas, mask the new area, edit "extend the background naturally" |
| Background swap | `image_remove_background` → composite on new background in layout or `image_edit` with references |
| Resolution | `image_upscale` {scale: 2 or 4} last; check for invented detail in text and faces |
| Raster to vector | `image_vectorize` {mode} → `svg_optimize`; check node count and that shapes are closed |

Edit instructions say what changes AND what must stay identical ("keep composition, lighting and
all other objects unchanged"). Keep the original; write every intermediate to disk.

## 6. Review sheet for generated images

Score 0-2 each; accept at ≥ 9/12 with no 0 on subject or artefacts.

| Check | 2 means |
|---|---|
| Subject accuracy | every must-have detail present and correct |
| Composition | subject placement and copy space as specified |
| Palette | dominant colors match the brief hexes closely |
| Light and style | matches brief; consistent shadows and perspective |
| Artefacts | none: hands, eyes, teeth, text glitches, warped straight lines, duplicated objects, melted edges |
| Fitness in layout | after placing text and logo, the rubric score does not drop |

Common failure → fix:
- Busy area where text goes → add "plain empty background on the left 45%" and lower detail words;
  or edit with a mask "make this area a smooth gradient".
- Colors drift → put hexes earlier in the prompt; use a palette reference image; correct in edit.
- Style inconsistency across a set → fixed seed, same prompt skeleton, first accepted image as reference.
- Text misspelled → shorten, quote exactly, choose a text-capable model, or set text in layout.

## 7. Provenance and rights

- Sidecar JSON next to each output: brief id, compiled prompt, model, provider, seed, references
  (paths and roles), parameters, timestamp, reviewer score. The image-generator agent writes it;
  verify it exists before delivery.
- Check the model's licence for commercial use; record it in the sidecar.
- No real-person likeness without consent, no trademarks or real logos generated, no imitation of
  a named living artist's style; disclose AI generation where the platform or client requires it.
