# Mask conventions and conversions

The canonical mask in this stack is a single-channel PNG, same width and height as the image,
white (255) = edit, black (0) = keep. `image_segment` returns canonical masks; `masktool.py` makes
and refines canonical masks; `image_edit` takes canonical masks and the server converts them to
whatever the configured adapter and model expect, reporting the conversion in `notes`. Never
pre-convert a mask you hand to `image_edit`.

Convert only at the edge: a mask going to a tool outside the server (a design app, someone else's
pipeline) or a mask you received in another convention. Use the local tool
`mcp__image__mask_convert {mask, to: white-edit|black-edit|alpha-transparent, invert?}` or
`masktool.py convert`.

## How each adapter receives your mask (verified 2026-10-19)

| Adapter / model | What is sent | Pixel-exact inside? | Notes |
|---|---|---|---|
| OpenRouter (any image model) | no mask parameter exists; the server sends the mask as an extra input reference with an explicit "edit only the white region of the mask image" instruction | no: the model interprets a picture | needs reference capacity for source + mask; the server's composite keeps everything outside the mask |
| Opper `fal/ideogram-v4.5-edit` | `mask` field (documented mask support; up to 3 references with a mask) | guided | Opper does not document the convention; the server sends the convention it was built for and says so in `notes`; test with the overlay before relying on edges |
| Opper GPT Image edit models (`openai/gpt-image-2.5-sunburst`, `-flare`, `gpt-image-1.5`) | `mask` field; upstream OpenAI convention: PNG with alpha, transparent = edit, same size | guided, not pixel-exact; the whole frame can shift | composite keeps the outside |
| Opper other models | refused (400 when a mask is sent) | - | configure a mask-capable model |
| OpenAI-compatible `/images/edits` | multipart `mask`: PNG with alpha, transparent (alpha 0) = edit, same size and format as the image (under 50 MB) | guided | applies to the first image when several are sent |
| fal `fal-ai/flux-pro/v1/fill` | `mask_url`: white = inpaint, black = keep | strict | best for removals and outpainting |
| fal Ideogram edit | black = edit, white = preserve | guided; `edit_precision` high copies unchanged pixels | |
| fal Qwen inpaint | white = edit | | cheap, lower fidelity |
| Gemini (Nano Banana), Seedream, FLUX 3 | no mask parameter | - | on OpenRouter they get the mask-as-reference treatment; otherwise describe the region in words |

## Conversions

```bash
# MCP (preferred, no Python needed)
mcp__image__mask_convert {mask: "m.png", to: "alpha-transparent"}     # RGBA, alpha 0 = edit
mcp__image__mask_convert {mask: "m.png", to: "black-edit"}            # Ideogram style
mcp__image__mask_convert {mask: "keep.png", to: "white-edit", invert: true}
# Local helper (same conventions)
"$PY" "$MT" convert mask.png openai-mask.png --to alpha-transparent --image photo.png
"$PY" "$MT" convert mask.png ideogram-mask.png --to black-edit
"$PY" "$MT" convert mask.png same.png --to white-edit        # normalise any L/RGB mask
"$PY" "$MT" invert keep-mask.png edit-mask.png               # a mask drawn with the opposite meaning
```

Reading an unknown mask: `image_info` (or `imgcheck.py info m.png`). If the mode is RGBA and the RGB
is uniform, it is an OpenAI-style alpha mask (transparent = edit). If it is L or RGB, look at it next
to the image (`masktool overlay`) and decide which colour covers the target, then convert to
canonical before using it.

## What `image_segment` returns

| Adapter / strategy | Mask quality | Use for |
|---|---|---|
| fal `fal-ai/sam-3/image` | true object outlines; instances merged | everything, including cutout repairs |
| OpenRouter `render` (default) | the image model paints a black/white mask; the server thresholds and resizes it to the source size | removals and replacements with generous growth; check the overlay every time |
| OpenRouter `detect` (`IMAGE_SEGMENT_PARAMS='{"strategy":"detect"}'`, a vision model such as `moondream/moondream3.1-9b-a2b`) | rectangles from normalised boxes | text boxes, rough removals; never cutouts |
| Opper | not available | configure SEGMENT elsewhere |

`invert: true` selects everything except the prompted object.

## Size and format pitfalls

| Pitfall | Effect | Prevention |
|---|---|---|
| Mask made on a resized preview | rejected, or the edit lands offset | build masks from `00-original`; compare sizes with `image_info` |
| JPEG mask | compression noise creates speckled partial edits | always PNG; `threshold` before use |
| Anti-aliased mask to a fill model | grey edge pixels become half-edits and seams | `threshold --t 128` for the edit call; feathering is done by the server composite (1-2 px) or your own composite |
| EXIF orientation on the source photo | mask drawn on the rotated view does not match stored pixels | normalise once: `"$PY" -c "from PIL import Image, ImageOps; ImageOps.exif_transpose(Image.open('in.jpg')).save('00-original.png')"` and work from the PNG |
| Mask touches the image border on a removal | the model has no context on that side | accept, or extend the canvas with `pad` first |
| Mask covers more than ~40% of the frame | it is a regeneration, not an edit | Open doubt for `image-generator` with the original as a reference |
| All-black mask | nothing to edit; some adapters error | check the overlay; `invert` if drawn the other way |

## Mask sizing heuristics

s = short side in px.

| Target | Grow | Why |
|---|---|---|
| Thin structure (wire, hair strand, scratch) | max(6, 0.01 s) | covers anti-aliasing and halo |
| Solid object removal | max(8, 0.015 s) | covers contact shadow and reflection |
| Person removal | max(12, 0.02 s) plus their shadow as a second mask (union) | shadows betray removals |
| Text line | 4-8 px padding around the glyph box | room for ascenders and descenders |
| Face or hand fix | 8 px around the defect, never the whole face unless identity may change | limits identity drift |
| Any approximated mask (OpenRouter `render`, `detect`) | add max(6, 0.01 s) on top of the above | rough edges; the server keeps everything outside exactly |
