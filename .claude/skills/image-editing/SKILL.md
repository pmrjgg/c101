---
name: image-editing
description: "Image editing through the single image MCP server (mcp__image__image_edit, image_segment, image_remove_background, image_upscale, mask_convert, image_info) - per-operation BYOK configuration (IMAGE_EDIT, IMAGE_SEGMENT, IMAGE_BG_REMOVAL, IMAGE_UPSCALE, no fallbacks) and what OpenRouter, Opper, fal and local adapters can really do (no native masks on OpenRouter, Opper masks via Ideogram or GPT Image edits, approximated segmentation, background removal and upscale), server-side fidelity post-processing (unmasked pixels preserved, alpha transferred onto original pixels), mask creation and conventions, instructions, compositing, pixel-diff verification, layered hand-off, and the review loop with visual-reviewer."
when_to_use: "Before any mcp__image__ edit, segmentation, background-removal or upscale call, when a generated image needs a local fix instead of a regeneration, when a cutout, mask, composite, outpaint, layered hand-off or upscale is required, when you must prove that an edit changed only the intended region, or when an editing operation is not configured."
---

# Image editing

An edit is done when the target region changed as instructed, everything else is unchanged (or
changed only within a stated tolerance), the original is still on disk, every intermediate is
reproducible from the step log, and `visual-reviewer` passed it.

Deep material: [edit recipes](references/edit-recipes.md), [mask conventions](references/mask-conventions.md).
Server configuration, adapters and model listings:
[configuration](../image-generation/references/configuration.md); per-op capabilities by router:
[model matrix](../image-generation/references/model-matrix.md) (both under
`$STACK/.claude/skills/image-generation/references/`).

## 1. Tools and configuration

One MCP server, `image` (tool ids `mcp__image__<tool>`). Each op uses exactly the endpoint and model
tag set in `~/.claude/stack.env` as `IMAGE_<OP>_URL`, `_KEY`, `_MODEL` (optional `_API`, `_PARAMS`);
its tool exists only when the op is configured. There is no fallback to another provider.

| Tool (op) | Required | Optional |
|---|---|---|
| `image_edit` (`IMAGE_EDIT`) | `image`, `instruction` | `mask` (canonical: white = edit, source size), `references` (extra images, "image N" order after the source), `preserve_unmasked` (default true), `n`, `aspect_ratio`, `size`, `output_format`, `output_dir`, `filename_prefix`, `params` |
| `image_segment` (`IMAGE_SEGMENT`; `IMAGE_MASK_*` is a deprecated alias) | `image`, `prompt` | `invert`, `output_dir`, `params` (`strategy`: `render` or `detect` on OpenRouter) |
| `image_remove_background` (`IMAGE_BG_REMOVAL`) | `image` | `preserve_pixels` (default true), `output_dir`, `params` |
| `image_upscale` (`IMAGE_UPSCALE`; `_API=local` = Pillow Lanczos) | `image` | `scale` (2 or 4), `output_dir`, `params` |
| `mask_convert` (local) | `mask`, `to` (`white-edit`, `black-edit`, `alpha-transparent`) | `invert`, output path per the schema |
| `image_info` (local) | `image` | size, mode, has alpha, format, file size |
| `image_ops_status` (local) | none | per op: exposed, adapter, URL host, model tag, missing env names |

Inputs: local paths (project-relative or absolute), http(s) URLs or data URIs. Every model call
returns `{ok, files: [{path, mime, bytes, width, height}], op, adapter, URL host, model, notes,
warnings}` and writes a `<file>.json` sidecar. `notes` and `warnings` carry what you must know: mask
conversions, approximations, fidelity measurements (alpha drift), resizes. The tool's input
schema is authoritative; leave out any parameter it lacks.

What each router can do for these ops (details and tags in the model matrix):

| Op | OpenRouter | Opper | fal | local |
|---|---|---|---|---|
| EDIT, instruction | native: generation with the source as first input reference (whole frame re-rendered) | native (`image` field) | native | - |
| EDIT, mask | approx: no mask parameter; the mask goes as an extra reference with "edit only the white region", then the server composites | native on `fal/ideogram-v4.5-edit`, `openai/gpt-image-2.5-sunburst`/`-flare`, `openai/gpt-image-1.5`; 400 on other models | native: `fal-ai/flux-pro/v1/fill` (white = edit), Ideogram edit (black = edit) | - |
| SEGMENT | approx: `render` (image model paints a B/W mask, normalised) or `detect` (vision model boxes, rasterised) | none | native: `fal-ai/sam-3/image` | - |
| BG_REMOVAL | approx: transparent re-render (GPT Image 2.5, Riverflow 2.5 pro) + alpha transfer | approx: GPT Image with `parameters.background=transparent` + alpha transfer | native: `fal-ai/bria/background/remove` | - |
| UPSCALE | approx: regenerate at a 4K tier (content can change) | approx: regenerate large (GPT Image 2 up to 3840, Gemini `4k`) | native: `fal-ai/topaz/upscale/image` | Lanczos (exact, no new detail) |

Local helpers (Pillow, deterministic):

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
PY="$STACK/.venv/bin/python"; MT="$STACK/.claude/skills/image-editing/scripts/masktool.py"
IMG="$STACK/.claude/skills/image-generation/scripts/imgcheck.py"
"$PY" "$MT" --help        # rect, polygon, from-alpha, invert, threshold, grow, feather, convert,
                          # pad, composite, over, split-alpha, merge-alpha, overlay, diff
```

## 2. Preflight

1. `mcp__image__image_ops_status`. List the ops the job needs (section 4 table). Never read or print
   `~/.claude/stack.env`.
2. A needed op is not exposed: return an Open doubt naming exactly the missing variables, with a
   suggested router and tag; do not improvise with another provider, MCP server, direct API call
   or a local stand-in for a model op. Deterministic local steps that are part of this workflow
   (crop, pad, geometric masks, composite, threshold) are fine.
   ```
   - [scope|high] IMAGE_BG_REMOVAL is not configured (image_remove_background not exposed; missing IMAGE_BG_REMOVAL_URL, IMAGE_BG_REMOVAL_KEY, IMAGE_BG_REMOVAL_MODEL) - the product cutout cannot be made - resolve: set them in ~/.claude/stack.env, e.g. https://queue.fal.run with fal-ai/bria/background/remove, then reconnect the image server (/mcp) - route: user
   ```
3. Note the fidelity class of each configured op (native or approx). For an approximated op, plan
   tighter verification and say in Evidence that the result is a re-render. If the approximation
   cannot meet the brief (a pixel-exact logo cutout through a re-render, a trace-level upscale of
   text), say so with an Open doubt recommending a native tag instead of looping.
4. Masked EDIT on OpenRouter needs reference capacity for source + mask (+ your references): models
   limited to 0-1 references (Recraft, MAI 2.5) cannot do it. Opper Ideogram edit: up to 4
   references, 3 when a mask is sent.

## 3. Ground rules

1. Never modify or overwrite the input. First action of every job (`<job>` =
   `.stack/images/edits/<YYYYMMDD-HHMM>-<slug>`, made once with `date +%Y%m%d-%H%M`):
   `mkdir -p <job> && cp -n <input> <job>/00-original.<ext>`.
   Photos with EXIF rotation: normalise once to `00-original.png` (mask-conventions reference).
2. Pass `output_dir: "<job>"` on every call so outputs and sidecars land in the
   job folder. Number what you keep (`01-mask.png`, `02-mask-grown.png`, `03-edit.png`); one
   operation per numbered file.
3. Append one JSON line per step to `<job>/steps.jsonl`:
   `{"step":3,"op":"image_edit","in":["00-original.png","02-mask-grown.png"],"out":"03-edit.png","instruction":"...","adapter":"opper","model":"fal/ideogram-v4.5-edit","notes":"..."}`.
4. One semantic change per edit call. "Remove the cable and make it sunset" is two calls.
5. Work at the original resolution. Upscale last, only after the content is accepted.
6. Real people: no edits that change identity, age, body or expression of an identifiable person
   unless the caller states consent; never alter documents, IDs, receipts or screenshots to look
   like something they are not.

## 4. Pick the operation

| Goal | Operations | Notes |
|---|---|---|
| Global change (time of day, season, restyle, grade) | `image_edit` without mask | whole frame re-rendered on every router; verify structure, not pixels |
| Change one object or region, rest identical | mask + `image_edit` (`preserve_unmasked` true) | the server guarantees untouched pixels outside the mask; inside quality depends on mask support (native vs approx) |
| Remove an object | mask (`image_segment` or geometric), grow, `image_edit` with mask | the instruction describes what fills the hole, not the object |
| Replace text on a sign or label | box mask + `image_edit` | text-strong models (GPT Image 2.5, Ideogram); quote the exact string |
| Cut out a subject to RGBA | `image_remove_background` | native matting on fal; approx elsewhere (section 5) |
| New background behind a subject | cutout, background (given, or an Open doubt for `image-generator`), `masktool over` | deterministic; better than "replace the background" edits, which drift the subject |
| Extend the canvas (outpaint, new ratio) | `masktool pad`, `image_edit` with the pad mask, composite with a wide feather | recipe 6 |
| Add an object from a reference | `image_edit` with `references` and a placement mask | counts against the model's reference limit |
| Fix hands, faces, small artefacts | tight mask + `image_edit` | mask the defect plus 8 px |
| Enlarge for print or retina | `image_upscale` | native, local or approx: section 9 |
| Hand-off as layers (each element editable) | cutouts per element → `layers_compose` (raster layers in a layered SVG) → `export_pdf` (layered PDF) | vector-art skill, layers section; there is no PSD output |

Step lists: [edit recipes](references/edit-recipes.md).

## 5. Fidelity post-processing (done by the server, verified by you)

Deterministic local steps that keep approximate models from damaging what must not change. They are
not provider fallbacks.

- **Masked edit, `preserve_unmasked: true` (default).** The server resizes the model's result to the
  source size and composites `out = src*(1-m) + result*m` with the canonical mask feathered 1-2 px.
  Pixels outside the mask (beyond the feather band) are the original pixels. Consequences:
  - A mask that is too tight leaves the edge, halo or shadow of a removed object: grow it (section 6).
  - Light changes cannot spill outside the mask: an added lamp will not light the wall unless the
    wall is masked; do a second, wider masked pass or an unmasked harmonise pass.
  - Set `preserve_unmasked: false` only when you will composite yourself with a different feather
    (outpaint joins, 8-16 px) or when the brief wants the model's global harmonisation.
- **Background removal, `preserve_pixels: true` (default).** If the model returns RGBA of the same
  composition, the server keeps only its alpha and applies it to the original RGB, then measures
  drift (mean absolute RGB difference inside the alpha). `notes` warns when drift is high: the model
  moved or reshaped the subject, so the alpha no longer fits the original pixels (halos, clipped
  edges). Inspect the edges; if they fail, the configured model is unsuitable for this subject:
  Open doubt for native matting (fal BRIA). `preserve_pixels: false` returns the model's own
  re-rendered subject; use it only when a re-render is acceptable.
- **Local adapters** (`IMAGE_UPSCALE_API=local`, `IMAGE_TRACE_API=local`) are explicit user choices,
  never automatic.

Edits always come back at the source size when `preserve_unmasked` applied; a different size in
`image_info` means it did not (check `notes`).

## 6. Masks

Canonical convention everywhere: single-channel PNG, same size as the image, white = edit, black =
keep. Pass canonical masks to `image_edit`; the server converts per adapter (OpenAI-compatible and
GPT Image alpha-transparent, FLUX Fill white, Ideogram black, OpenRouter as a reference image). Use
`mask_convert` (or `masktool convert`) only for masks you hand to something outside the server or
masks you received in another convention. Details: [mask conventions](references/mask-conventions.md).

Creation, in order of preference:

| Situation | How |
|---|---|
| Nameable object ("the red car", "the power lines") | `image_segment {image, prompt}` → white-on-black L PNG at source size; `invert: true` selects everything else. Native on fal (SAM 3); approximate on OpenRouter (`render` edges are rough, `detect` gives rectangles) |
| Rectangular region (text line, sign, sky band) | `"$PY" "$MT" rect IMG out.png --box x0,y0,x1,y1` |
| Round region | `rect ... --ellipse` |
| Irregular region with known corners | `polygon IMG out.png --points 120,40 380,60 360,300 100,280` |
| Everything except an existing cutout's subject | `from-alpha cutout.png bg-mask.png` |
| The subject of an existing cutout | `from-alpha cutout.png subj-mask.png --keep-subject` |
| Union (object + its shadow) | `"$PY" -c "from PIL import Image, ImageChops as C; C.lighter(Image.open('a.png').convert('L'), Image.open('b.png').convert('L')).save('ab.png')"` |

Without SEGMENT, geometric masks are a normal tool; a shape too complex for a polygon (hair,
foliage) is an Open doubt naming `IMAGE_SEGMENT_*`. Find coordinates by Reading the image (pixel
size from `image_info`); state them in the step log. Phrase segment prompts as singular noun phrases
with a disambiguator ("the leftmost chair").

Refinement (s = short side in px):

| Use | Grow | Feather | Hard? |
|---|---|---|---|
| Object removal | +max(8, 0.015 s) px: covers halo and contact shadow | none (the server feathers 1-2 px) | yes (`threshold`) |
| Object replacement | +max(4, 0.008 s) | none | yes |
| Text replacement | box with 4-8 px padding | none | yes |
| Approximate segment masks (OpenRouter `render`) | +max(6, 0.01 s) extra, edges are rough | none | yes |
| Manual composite of an outpaint join | `pad --overlap 16..32` | 8-16 px | no |

Always check a mask before spending a model call:
`"$PY" "$MT" overlay 00-original.png 02-mask-grown.png 02-overlay.png`, then Read `02-overlay.png`.
Red must cover the whole target and nothing that must survive.

## 7. Write the instruction

Pattern: `<verb> <target> <to what>; keep <what must not change> unchanged.`

| Edit | Good instruction |
|---|---|
| Removal | "Fill the masked area with the continuation of the brick wall and the pavement, matching texture, perspective and light; nothing else changes." |
| Replacement | "Replace the mug in the masked area with a clear glass of iced coffee with a paper straw, same position and scale, lit from the left like the rest of the scene." |
| Text | "Change the sign text to \"OPEN DAILY 8-18\" in the same white condensed sans-serif, same size and alignment; keep the sign and wall unchanged." |
| Global | "Turn the scene into late-afternoon golden light with long shadows to the right; keep every object, person and the composition identical." |
| Reference insert | "Place the lamp from image 2 on the side table in the masked area, matching the room's perspective and warm light; keep everything else identical." |

On OpenRouter (mask sent as a reference image) also name the region in words ("the mug on the left
of the table, inside the white area of the mask image"); the model sees the mask only as a picture.
Avoid: "remove X" alone (models redraw X smaller); negations as the only content; several targets
per call; style words on a local fix.

## 8. Verify every step

1. Size: `image_info` (or `imgcheck.py info`) on input and output; equal sizes expected.
2. Containment: build a diff mask that excludes the feather band, then diff:
   `"$PY" "$MT" grow 02-mask-grown.png 02-diffmask.png --px 3`;
   `"$PY" "$MT" diff 00-original.png 03-edit.png --mask 02-diffmask.png --max-outside 0.5 --min-inside 2`.
   - `outside.mae` <= 0.5 (0..255 scale); exactly 0.0 when the server composite applied.
   - `inside.mae` >= 2: lower means a no-op; retry with a firmer instruction.
   - Unmasked edits: outside MAE of 2-8 is normal re-rendering; compare structure visually instead.
3. Visual: `"$PY" "$IMG" sheet 05-review.png 00-original.png 03-edit.png 02-overlay.png --cols 3`, Read
   it: seams at the mask border, light and perspective continuity, texture repetition, ghosts.
4. Cutouts: `imgcheck.py expect cut.png --alpha`, then `info`: `alpha_partial_frac` above ~0.05 on a
   hard-edged product means a soft, fringed matte; Read on the checkerboard sheet for halos; read
   the drift warning in `notes`.
5. Text edits: read every character of the new string.

Iteration cap per step: 3 attempts, then the review loop decides (section 11).

## 9. Compositing, alpha and upscaling

- Manual pixel-exact composite (custom feather, or `preserve_unmasked: false`):
  `composite ORIG EDITED MASK OUT` takes EDITED inside the feathered mask and ORIG elsewhere.
- Subject onto a new background: `over cut.png bg.png out.png --scale 0.6 --x 420 --y 180`. Match
  light direction and colour temperature; if they disagree, one light harmonise `image_edit` on the
  composite, then put the original subject back on top if it drifted (recipe 5).
- Defringe a halo: `split-alpha`, `grow a.png a1.png --px -1`, `feather a1.png a2.png --px 0.8`,
  `merge-alpha rgb.png a2.png cut-clean.png`.
- Upscaling, by UPSCALE fidelity:

| Configured | Opaque image | RGBA image |
|---|---|---|
| native (fal Topaz) | `image_upscale {scale: 2 or 4}`; one 4x pass beats two 2x passes | `split-alpha` → upscale the RGB → `merge-alpha` (alpha resized with Lanczos) |
| local (Lanczos) | exact enlargement, no new detail: fine for flat graphics and screens, soft for photos at 4x | Lanczos keeps alpha; check edges |
| approx (OpenRouter, Opper) | a regeneration: text, faces and texture may change; size is the model's tier, not exactly `scale`; review at 100% crops | content may shift, so the old alpha no longer fits: re-matte with `image_remove_background` after upscaling, or ask for a native/local upscaler |

Print targets: inches x 300 dpi (a 3000 px side prints at 10 in / 25 cm). Check a 100% crop
(`"$PY" -c "from PIL import Image; Image.open('up.png').crop((x,y,x+800,y+800)).save('crop.png')"`)
for invented texture on faces and reshaped letters.

## 10. Layered hand-off

When the brief asks for editable layers: produce each element as its own RGBA file (cutouts, or
`image_generate_transparent` via image-generator), keep a `layers.json` (file, x, y, scale, order),
then `layers_compose {layers: [{source, name, opacity?, visible?, x, y, width?, height?}, ...],
width, height}` → layered SVG (raster sources embedded in their own layer), and
`export_pdf {svg_path, layered: true}` → PDF whose layers are toggleable Optional Content Groups.
Order is bottom to top. Verify with `svg_layers` and by Reading the PDF. Layer conventions and
checks: vector-art skill.

## 11. Review loop with visual-reviewer

Rubric, anchors, revision grammar and stop rules live in the `visual-review` skill that
`visual-reviewer` loads; you supply evidence, apply its revisions and enforce the round count.

1. Self-check first: section 8 numbers and the review sheet. Fix mask or instruction problems
   before asking for a review.
2. Spawn `visual-reviewer` (Agent, `run_in_background: false`) per round:
   ```
   Goal: review this edit against the brief; verdict PASS, REVISE or STOP with revisions.
   Brief: <what had to change, what had to stay unchanged>
   Original: 00-original.png   Result(s): <paths>   Mask + overlay: <paths>   Steps: steps.jsonl
   Measurements: diff JSON (outside/inside MAE), alpha drift from notes, sizes
   Produced by: op=EDIT adapter=<...> model=<tag> (native mask | approximated mask)
   Round <k> of 4. Previous review JSON: <path or none>. Threshold 8, no criterion below 6.
   ```
   It writes `.stack/out/visual-reviewer/<stamp>-<slug>-r<k>.md` and `.json` and replies with the
   paths.
3. PASS (overall >= threshold, default 8, every applicable criterion >= 6): deliver.
4. REVISE: apply the revisions in order, blocking first, respecting the KEEP list. `region-edit`
   comes with a region (box or shape) and mask advice (`grow_px`, `feather_px`): build that mask
   with masktool or `image_segment`, run `image_edit`, run the revision's `verify` check.
   `cutout-fix` and `upscale` map to section 9 and the recipes; `prompt-delta` revisions owned by
   `image-generator` (the content needs regenerating) go back to your caller as an Open doubt with
   the revision id. A revision needing an unexposed op: Open doubt naming its env vars.
5. STOP or your own limits: 4 rounds; `budget="hard"`; `budget="soft"` unless one cheap local fix is
   left; plateau (best overall up < 0.3 in each of the last two rounds); the same blocking defect after two
   strategies on an approximated op (Open doubt recommending a native tag). Regression (overall
   below the best by more than 0.5): restart the next attempt from the best round's file. Deliver
   the best round (highest overall with no criterion < 6, else highest overall).
6. Trail: `<job>/review-trail.jsonl`, one line per round (files, review JSON path, overall, lowest,
   verdict, change applied); the Result lists rounds, scores, the chosen file and unapplied revisions.
7. Cannot spawn (`remaining_depth="0"`, policy denial, or you are the produce stage of the
   `visual-iterate` workflow): self-review with the same criteria plus the diff numbers, mark it
   `self-review`, and unless a workflow reviews you add an Open doubt recommending a
   `visual-reviewer` pass. The main thread can run the whole loop with
   `Workflow name=visual-iterate args={brief, kind: "image", mode: "edit", source: "<path>"}`.

## 12. Worked example

Brief: "Remove the overhead power line from beach.jpg (4000x2667) and widen it to 16:9 for a banner.
Keep the people untouched."

1. `image_ops_status`: SEGMENT on fal (`fal-ai/sam-3/image`, native), EDIT on Opper
   (`fal/ideogram-v4.5-edit`, native masks). Copy to `00-original.jpg`.
2. `image_segment {image: 00-original.jpg, prompt: "the overhead power line and its poles"}` →
   `01-mask.png`; `threshold`; `grow --px 40` (0.015 x 2667) → `02-mask-grown.png`. Overlay Read:
   covers line and pole tops, misses the people.
3. `image_edit {image: 00-original.jpg, mask: 02-mask-grown.png, instruction: "Fill the masked area
   with the continuation of the clear late-afternoon sky and distant headland, matching gradient
   and haze; nothing else changes."}` → `03-edit.png`; `notes`: mask converted to the model's
   convention, unmasked pixels preserved.
4. `grow --px 3` → diff mask; `diff ... --max-outside 0.5 --min-inside 2` → outside 0.00, inside
   21.7. Sheet Read: no ghost line, sky continuous.
5. Widen to 16:9 at the same height: W = 2667 x 16/9 = 4741; `pad 03-edit.png 05-padded.png
   05-padmask.png --left 371 --right 370 --overlap 24`.
6. `image_edit {image: 05-padded.png, mask: 05-padmask.png, preserve_unmasked: false, instruction:
   "Extend the beach, sea and sky naturally to the left and right edges, same light and horizon
   height; do not add people or objects."}` → `06-outpaint.png`; `feather 05-padmask.png
   06-feather.png --px 12`; `composite 05-padded.png 06-outpaint.png 06-feather.png 07-banner.png`.
7. `expect 07-banner.png --aspect 16:9`; diff against `05-padded.png` with the pad mask grown 12 px:
   outside under 0.5. `visual-reviewer` round 1: overall 8.4, lowest 7, PASS (seams invisible, people intact).
8. Report `07-banner.png`, diff results, `steps.jsonl` and the review trail; original untouched.

## 13. Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Tool absent, or "not configured" error | op not configured / server not reconnected | `image_ops_status`; Open doubt naming the variables |
| 400 when sending a mask (Opper) | model has no mask support | Open doubt: `fal/ideogram-v4.5-edit` or GPT Image 2.5 for IMAGE_EDIT |
| Masked edit on OpenRouter changes the wrong thing inside the mask | model reads the mask only as a picture | name the region in words; smaller, simpler masks; or recommend a native mask router |
| Ghost edge or shadow of a removed object | mask too tight; outside pixels are preserved exactly | grow the mask; union the shadow |
| Removed object reappears smaller | instruction named the object | describe the fill content |
| Seam at the mask border | lighting mismatch, 1-2 px server feather too hard | widen the mask into a uniform area; or `preserve_unmasked: false` + manual 4-8 px feather |
| Output size differs from the source | preservation not applied (see `notes`) | resize and composite manually; report it |
| Cutout halo or clipped edges, drift warning in `notes` | approximated BG removal re-rendered the subject | defringe; segment-based alpha (recipe 4); else Open doubt for native matting |
| Segment mask covers the wrong instance | ambiguous prompt; `detect` boxes | add position words; or draw `rect`/`polygon` |
| Mask size mismatch | mask made on a resized copy | rebuild masks from `00-original` |
| Upscaled RGBA lost transparency or alpha no longer fits | upscaler outputs RGB, or regenerated content moved | split/merge for native or local; re-matte after an approximated upscale |
| Text still misspelled after 3 tries | model limit | keep the blank-sign edit and return the text for typesetting, with an Open doubt |

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `photo-retouch-composite` | an edit or composite must look photographically real |
