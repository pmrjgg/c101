# Edit recipes

Shell variables as in SKILL.md (`PY`, `MT`, `IMG`). `J` is the job folder
`.stack/images/edits/<YYYYMMDD-HHMM>-<slug>`. Every recipe starts with `image_ops_status` (the ops it needs must be
exposed; otherwise an Open doubt naming the missing `IMAGE_<OP>_*` variables) and
`cp <input> $J/00-original.<ext>`, passes `output_dir: "$J"` to every tool, and ends with the
verification in SKILL.md section 8 and the review loop in section 11.

Fidelity reminders: masked `image_edit` keeps every pixel outside the mask by default
(`preserve_unmasked: true`, 1-2 px feather); `image_remove_background` puts the model's alpha on the
original pixels (`preserve_pixels: true`) and reports drift in `notes`. On OpenRouter masks,
segmentation, background removal and upscaling are approximations (re-renders); see the model
matrix in the image-generation skill.

## 1. Object removal

Ops: SEGMENT (optional), EDIT.

1. Mask: `image_segment {image: $J/00-original.png, prompt: "<the object, singular, with position>"}`
   → copy to `$J/01-mask.png`; or `rect`/`polygon` for geometric targets.
2. `"$PY" "$MT" threshold $J/01-mask.png $J/02-mask.png`, then
   `"$PY" "$MT" grow $J/02-mask.png $J/03-mask-grown.png --px <max(8, 0.015 s)>`. Shadow or
   reflection visible: mask it separately and union (SKILL.md section 6); outside pixels are kept
   exactly, so anything left out of the mask stays in the picture.
3. `overlay` and Read. Fix the mask before spending a model call.
4. `image_edit {image: $J/00-original.png, mask: $J/03-mask-grown.png, instruction: "Fill the masked
   area with <what is behind it>, matching texture, perspective and light; nothing else changes."}`
   → `04-edit.png`. On OpenRouter add the region in words ("the cable crossing the upper left sky").
5. `grow 03-mask-grown.png 04-diffmask.png --px 3`;
   `diff 00-original.png 04-edit.png --mask 04-diffmask.png --max-outside 0.5 --min-inside 2`.

Large removal (more than 15% of the frame): split into 2-3 masks and fill sequentially, each pass
using the previous result as input; one huge fill tends to hallucinate a new object. Above ~40% it is
a regeneration, not an edit: return an Open doubt for `image-generator` with the original as a
reference.

## 2. Localised replacement (object, clothing colour, product swap)

As removal, with grow max(4, 0.008 s) and an instruction naming the new content, position, scale and
lighting. Product swap: pass the packshot in `references` and say "the product from image 2"
(the source is image 1). Count source + mask (OpenRouter) + references against the configured
model's reference limit; Opper Ideogram edit allows 3 references with a mask.

## 3. Text replacement

1. Box the text line: `rect 00-original.png 01-mask.png --box x0,y0,x1,y1` with 4-8 px padding.
2. `image_edit {image, mask: 01-mask.png, instruction: "Change the text in the masked area to
   \"<EXACT TEXT>\" in the same typeface style, weight, colour, size and alignment; keep the
   background material and lighting unchanged."}`. Best on text-strong EDIT models (GPT Image 2.5,
   Ideogram 4.5 edit).
3. Read every character. The server composite keeps the surroundings exact.
4. New text longer than the old: widen the box in the reading direction first, or ask for a smaller
   size explicitly ("smaller, to fit on one line").
5. Still wrong after 3 attempts: keep a blank-sign edit ("remove the text, keep the sign surface")
   and return the string for typesetting.

## 4. Background removal (cutout)

Ops: BG_REMOVAL (SEGMENT optional for repairs).

1. `image_remove_background {image: $J/00-original.png}` → `01-cut.png`. Read `notes`: native matting
   (fal) or approximated re-render, and the alpha drift figure when the alpha was transferred.
2. `imgcheck.py expect 01-cut.png --alpha`; `info` for `alpha_partial_frac`.
3. Read on a contact sheet (checkerboard) next to the original, plus the cutout over a dark and a
   light flat background (`over`) to expose halos.
4. Problems:
   - Halo in the old background colour: defringe (SKILL.md section 9).
   - High drift warning (approximated model reshaped the subject): the alpha does not fit the
     original edges. Rebuild the alpha from a segment mask: `image_segment {prompt: "the <subject>
     including all hair"}`, `threshold`, `feather --px 1.5`, `merge-alpha 00-original.png
     soft-alpha.png 02-cut.png`; compare both and keep the better. Neither good: Open doubt for a
     native matting model (`fal-ai/bria/background/remove`).
   - Holes in the subject (white shirt on a white wall): combine the cutout alpha with a subject
     segment mask by maximum (`ImageChops.lighter`) and `merge-alpha`.
   - Low-contrast background: `image_edit` "replace the background with flat pure green #00FF00,
     keep the subject's every edge and hair strand unchanged" (unmasked, so check the subject), then
     remove the background again.
   - `preserve_pixels: false` returns the model's own RGBA (re-rendered subject): only when the brief
     accepts a re-render.
5. Commercial use: when BG_REMOVAL is `fal-ai/bria/background/remove`, BRIA RMBG 2.0 is trained on
   licensed data; the sidecar names the model that produced the cutout.

## 5. New background behind a subject

1. Cutout (recipe 4) → `cut.png`.
2. Use the background given in the brief, or return an Open doubt for `image-generator` to make one at
   the final aspect, light direction stated to match the subject ("key light from the left, soft"),
   empty area where the subject goes.
3. `"$PY" "$MT" over cut.png bg.png 03-comp.png --scale <s> --x <x> --y <y>`.
4. Contact shadow and harmonisation: `image_edit {image: 03-comp.png, instruction: "Add a soft,
   realistic contact shadow under the <subject> consistent with light from the left, and harmonise
   its colour temperature with the scene; keep the <subject>'s shape, colours and details
   unchanged."}` → `04-harmonised.png` (unmasked: the whole frame is re-rendered).
5. Verify the subject did not drift. Build a subject mask on the composite's canvas:
   ```bash
   "$PY" -c "from PIL import Image; Image.new('RGBA', Image.open('bg.png').size, (0,0,0,0)).save('$J/blank.png')"
   "$PY" "$MT" over cut.png $J/blank.png $J/placed.png --scale <s> --x <x> --y <y>
   "$PY" "$MT" from-alpha $J/placed.png $J/subj.png --keep-subject
   "$PY" "$MT" diff $J/03-comp.png $J/04-harmonised.png --mask $J/subj.png
   ```
   `inside.mae` above ~6 means the subject was redrawn: put the original subject back on top with
   `over cut.png 04-harmonised.png 05-final.png` at the same scale and position (the new shadow and
   grade around it stay).

## 6. Outpainting / changing the aspect ratio

Target ratio R = W'/H'. Keep the height when widening: W' = round(H x R), pad (W' - W) split between
left and right; keep the width when making taller: H' = round(W / R).

1. `pad 00-original.png 01-padded.png 01-padmask.png --left L --right R --overlap 24 --fill edge`.
   `--fill edge` pre-fills with a blurred stretch, a colour prior for the model (and the content an
   OpenRouter model sees as image 1).
2. `image_edit {image: 01-padded.png, mask: 01-padmask.png, preserve_unmasked: false, instruction:
   "Extend the scene naturally into the masked borders: <what continues: sky, floor, table>, same
   light, horizon at the same height; do not add new subjects."}` → `02-out.png`.
3. Wide join: `feather 01-padmask.png 03-feather.png --px 12`;
   `composite 01-padded.png 02-out.png 03-feather.png 04-final.png`.
   (With `preserve_unmasked: true` the server would composite with a 1-2 px feather, which can show
   a seam in skies and gradients.)
4. Check `expect --aspect`, horizon continuity, no mirrored duplicates. Extensions wider than 50% of
   the original: two steps of 25%.

## 7. Global edit (relight, season, restyle)

1. `image_edit {image, instruction: "<global change>; keep every object, person, text and the
   composition identical."}` without a mask (GPT Image 2.5, Nano Banana 2.1, FLUX Kontext, Krea K3
   edit are good instruction editors).
2. Pixel diffs are large by design; compare object positions on a side-by-side sheet. For
   identity-sensitive content (faces, products, logos), mask the subject and composite the original
   subject back if it drifted (recipe 5 step 5).

## 8. Upscaling

1. Only accepted content. Scale 2 for screens, 4 for print.
2. Print pixels = inches x 300 dpi.
3. By fidelity class (`image_ops_status` adapter for UPSCALE):
   - native (fal Topaz): `image_upscale {image, scale: 4}`; one 4x pass beats two 2x passes.
   - local (Lanczos): exact and soft; good for flat art and UI, weak for photos at 4x.
   - approx (OpenRouter/Opper regeneration): content can change; check faces, text and logos at
     100% crops; the output size is the model's tier (crop or resize to the exact target locally).
4. RGBA: native/local → `split-alpha cut.png rgb.png a.png`, upscale `rgb.png`, `merge-alpha <up>
   a.png cut@2x.png`. Approx → upscale, then re-matte with `image_remove_background` (the old alpha
   no longer fits moved content).
5. Text-heavy images whose letters got reshaped: keep the original resolution and say so, or
   recommend a native upscaler in an Open doubt.

## 9. Compositing several elements, with a layered hand-off

1. Take each element as a transparent asset (from the brief, from `image-generator` via
   `image_generate_transparent`, or a cutout per recipe 4; ask for missing ones as an Open doubt).
2. Place back to front with `over`, one file per step, and record `layers.json`
   (`[{"source":"bg.png","name":"Background","x":0,"y":0,"scale":1}, ...]`) so the comp is
   reproducible.
3. Finish with one harmonise `image_edit` (recipe 5 step 4) and put any drifted hero element back on
   top.
4. Editable deliverable: `layers_compose {layers: [{source: "bg.png", name: "Background"},
   {source: "cut.png", name: "Product", x: 420, y: 180, width: 960, height: 1280},
   {source: "shadow.png", name: "Shadow", opacity: 0.6}], width: 1920, height: 1080}` → layered SVG
   with each raster in its own layer, then `export_pdf {svg_path, layered: true}`. Check with
   `svg_layers` (names, order) and Read the PDF. Raster layers make large files; say the size.

## 10. Working with approximated operations

When `image_ops_status` shows OpenRouter or Opper for SEGMENT, BG_REMOVAL or UPSCALE, or OpenRouter
for masked EDIT:

| Op | What to expect | Extra checks |
|---|---|---|
| SEGMENT `render` | rough, sometimes offset edges; may miss thin parts | overlay Read; grow more; intersect with a polygon of the area (`ImageChops.multiply`) to remove spill |
| SEGMENT `detect` | rectangles | use only for removals or text boxes, never cutouts |
| masked EDIT (OpenRouter) | inside content can ignore the mask's shape; outside preserved by the server | name the region in words; smaller masks; check inside content carefully |
| BG_REMOVAL | alpha from a re-render, transferred onto original pixels | drift figure in `notes`; edges on dark and light backgrounds |
| UPSCALE | regeneration at the model's tier | 100% crops of faces, text, fine texture; the exact size |

If an approximation fails the review twice on the same criterion, stop: return the best attempt and an
Open doubt recommending the native tag (fal) for that op.
