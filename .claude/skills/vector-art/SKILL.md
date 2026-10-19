---
name: vector-art
description: "Vector art through the single image MCP server - vector_generate (IMAGE_VECTOR, e.g. Recraft vector models on OpenRouter or fal), image_vectorize (IMAGE_TRACE on fal, local vtracer, or an approximate redraw on OpenRouter), svg_transform only when IMAGE_VECTOR_MANIPULATION names an external model, and the always-present local tools svg_inspect, svg_render, svg_optimize, svg_layers, svg_layerize, layers_compose and export_pdf - per-operation BYOK configuration without fallbacks, choosing hand-written, generated or traced SVG, editing SVG text directly with Read and Edit, cleanup and safety, layered SVG (inkscape groupmode layers that Illustrator imports as layers), layered PDF with Optional Content Groups, budgets, render checks and the review loop with visual-reviewer."
when_to_use: "Before any mcp__image__ vector or SVG tool call, when a deliverable must scale (icon, logo, illustration, plotter or cutter file), when an SVG must be edited, cleaned, validated, layered or exported to PDF, or when a vector operation is not configured."
---

# Vector art

A vector deliverable is done when the SVG is well-formed, safe to inline, scales from its smallest
to its largest use without artefacts, uses the agreed palette, fits its size budget, has the
requested layers (and layered PDF), looks right when rendered, and `visual-reviewer` passed it.

Deep material: [editing SVG directly](references/svg-editing.md), [layered SVG and PDF](references/layers.md),
[SVG cleanup](references/svg-cleanup.md), [tracing](references/tracing.md). Server configuration and
per-router capabilities: [configuration](../image-generation/references/configuration.md) and
[model matrix](../image-generation/references/model-matrix.md) in the image-generation skill.

## 1. Tools and configuration

One MCP server, `image` (tool ids `mcp__image__<tool>`). Model ops use exactly the endpoint and tag
the user set in `~/.claude/stack.env` (`IMAGE_<OP>_URL`, `_KEY`, `_MODEL`, optional `_API`,
`_PARAMS`) and exist only when configured; local tools always exist. No fallbacks.

| Tool | Required | Optional / returns |
|---|---|---|
| `vector_generate` (`IMAGE_VECTOR`) | `prompt` | `style`, `aspect_ratio` or `size`, `n`, `layered` (default false: true layerizes by top-level groups), `output_dir`, `filename_prefix`, `params` |
| `image_vectorize` (`IMAGE_TRACE`; `_API=local` = vtracer) | `image` | `layered` (default false: true gives one layer per colour), `output_dir`, `params` (adapter-native, e.g. vtracer settings locally) |
| `svg_transform` (`IMAGE_VECTOR_MANIPULATION`, only when its model is not `claude`) | `svg_path`, `instruction` | `output_path`; the reply is validated as well-formed SVG |
| `svg_inspect` | `svg_path` | well-formedness, viewBox and size, element and path counts, palette, layers, text elements, embedded rasters, complexity, flagged problems |
| `svg_render` | `svg_path` | `width`, `background` (omit for transparent) → PNG preview you can Read |
| `svg_optimize` | `svg_path` | `precision` (default 2), `output_path` (default `<name>.min.svg`) |
| `svg_layers` | `svg_path` | top-level layers: id, label, visibility, element count, palette |
| `svg_layerize` | `svg_path`, `by` (`color`, `group`, `mapping`) | `mapping` ({layer name: [ids or CSS-like selectors]}), `output_path` |
| `layers_compose` | `layers` ([{source (svg or png), name, opacity?, visible?, x?, y?, width?, height?}], bottom first), `width`, `height` | `output_path` → one layered SVG, rasters embedded in their own layers |
| `export_pdf` | `svg_path` | `output_path`, `layered` (default true: one OCG per top-level layer), `page_size` (`auto`, `A4`, `letter`, `"WxHmm"`) |
| `image_ops_status`, `image_info` | | configuration per op (never keys); raster facts |

Model results carry `ok`, `files`, the op, adapter, URL host, model tag, `notes` and `warnings`
(approximations, ignored or snapped parameters), and
a `<file>.json` sidecar. The tool's input schema is authoritative; leave out what it lacks.

| Op | OpenRouter | Opper | fal | local |
|---|---|---|---|---|
| VECTOR | native: `recraft/recraft-v4.1-vector` (~$0.08), `-v4.1-pro-vector` (~$0.30, complex), `-v4-styles-vector` (needs style references) | unverified: `fal/recraft-v3` vector style may return a raster | native: `fal-ai/recraft/v4.1/text-to-vector` | - |
| TRACE | approx: Recraft vector redraw from one reference (not a trace) | none | native: `fal-ai/recraft/vectorize` | vtracer (`IMAGE_TRACE_API=local`) |
| VECTOR_MANIPULATION | chat model via `{URL}/chat/completions` | chat model via `https://api.opper.ai/v3/compat` | - | `claude` (default): you edit the SVG |

Local scripts:

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
SVG="$STACK/.claude/skills/vector-art/scripts/svgcheck.py"; PY="$STACK/.venv/bin/python"
IMG="$STACK/.claude/skills/image-generation/scripts/imgcheck.py"   # contact sheets (Pillow)
python3 -I "$SVG" check out.svg --budget icon     # exit 1 on any ERROR; icon|logo|illustration
python3 -I "$SVG" --help                          # palette, remap, currentcolor, prefix-ids, sanitize, precision, fit
```

Shell variables do not persist between Bash calls: set them in the same command that uses them.

## 2. Preflight

1. `mcp__image__image_ops_status` for VECTOR, TRACE and VECTOR_MANIPULATION. Never read or print
   `~/.claude/stack.env`.
2. Pin the vector spec: `asset type | smallest and largest use | palette (hex, count) | stroke or
   fill style | layers (names, order) or none | outputs (svg, min.svg, layered PDF + page size)`.
3. A needed op is missing: Open doubt naming the variables `image_ops_status` lists, with a
   suggested router and tag; no other provider, no ad-hoc tracer, no direct API call.
   ```
   - [scope|high] IMAGE_TRACE is not configured (image_vectorize not exposed; missing IMAGE_TRACE_URL, IMAGE_TRACE_KEY, IMAGE_TRACE_MODEL) - the client's raster logo cannot be traced - resolve: set IMAGE_TRACE_API=local (vtracer, free) or URL https://queue.fal.run with MODEL fal-ai/recraft/vectorize, then reconnect the image server (/mcp) - route: user
   ```
   Hand-writing SVG is always available, for simple geometry and for edits of existing SVG; it is
   not a stand-in for generation or tracing of art you could not draw by hand.
4. Fidelity class: TRACE on OpenRouter is a redraw, never acceptable for a logo that must stay
   identical (Open doubt for local or fal). VECTOR on Opper: a raster result is a failure (Open doubt
   for OpenRouter or fal Recraft vector).

## 3. Route: hand-write, generate, trace or edit

| Situation | Route | Why |
|---|---|---|
| Simple geometric icon, symbol, badge or diagram (<= ~20 primitives: check, plus, arrow, chevron, badge) | hand-write with Write | exact, smallest, deterministic, free; you control the grid |
| New icon set, logo concept, spot illustration from a description | `vector_generate` | native paths, editable |
| Existing raster logo or mark that must become vector | `image_vectorize` (fal or local) | keeps the design; generation would redesign it |
| Hand-drawn line art, scan, stamp | prep to clean black/white, `image_vectorize` | 1-2 colour traces are crisp and small |
| Flat-colour raster you generated and like | `image_vectorize` after palette reduction | fine when colours are flat and edges hard |
| Change an existing SVG (colours, layout, layers, text, size) | edit the SVG text (section 5) | exact; regeneration would redraw everything |
| Photo or painterly image | usually decline; posterised trace only on request | thousands of paths, large files |
| Wordmark | generate or trace the symbol only; set type from a real font and outline it in a design tool | generated lettering is rarely typographically correct |
| Poster or composition with raster parts | `layers_compose` (vector and PNG layers) → `export_pdf` | editable hand-off |

## 4. Prompting `vector_generate`

```text
<Asset type: flat icon / logo mark / spot illustration> of <subject>, <geometry: built from
circles and rounded rectangles / single continuous line>, <fill style: solid fills, no gradients,
no textures / 2 px uniform outline, no fills>, <n> colours only: <hex list>, centred on a plain
background with even padding, <style anchor: Swiss minimal / playful rounded / technical
line-art>, no text.
```

- Name the palette with hex and a count; unconstrained prompts yield 20-40 near-duplicate colours.
- "No gradients, no textures, no shadows" unless wanted: they explode node counts.
- One subject per call. For a set, get the hero to PASS, then reuse its style and palette sentences
  verbatim.
- `style` is a hint; on OpenRouter Recraft models native styles go through
  `params: {"provider": {"options": {"recraft": {"style": "<style>"}}}}` (or the user's
  `IMAGE_VECTOR_PARAMS`). Recraft `*-styles-vector` models require 1-10 style references; only
  recommend them for VECTOR if the `vector_generate` schema shows a references parameter.
- `layered: true` when the brief wants editable parts; top-level groups become layers, labels may
  be generic: rename them (section 8).
- Logos: 2-3 candidates (`n` or separate calls); icons rarely need more than one round.

## 5. Editing SVG directly (default manipulation)

With `IMAGE_VECTOR_MANIPULATION_MODEL=claude` there is no `svg_transform`; you are the editor.
Full recipes: [svg-editing](references/svg-editing.md).

1. Copy to a numbered file in the job folder; never edit the only copy. Log each step.
2. `svg_inspect` to orient (ids, layers, palette, problems). Read small files whole; for large
   ones Grep element and paint lines with line numbers and Read ranges.
3. Edit with unique anchors (an `id`, a distinctive attribute). Change attributes and wrapper
   transforms, not path geometry: recolour via `fill`/`stroke`/`stop-color`/`<style>`; move, scale,
   rotate, mirror via `<g transform>`; z-order by moving element blocks; canvas via `viewBox`;
   layers by wrapping runs in `inkscape:groupmode="layer"` groups.
4. `svg_inspect` again, `svgcheck check`, then `svg_render` and Read; before/after sheet for visible
   changes, render diff (MAE about 0) for changes that must not alter appearance.
5. More than ~20 similar edits: a stdlib ElementTree script in the scratchpad that registers the
   inkscape, sodipodi and xlink namespaces and writes a new file.
6. Not by hand: boolean path operations, stroke to outline, text to outlines, smoothing noisy
   traces. Use `svg_transform` if it is exposed (then verify structure, layers, palette and the
   render), Inkscape CLI only if installed and approved, or deliver without and say so.

`svg_transform` when exposed: write constraints into the instruction (keep viewBox, ids, layer
groups and labels, palette; no rasters, scripts or external references); after the call check
`svg_inspect`, `svg_layers`, palette and a before/after render; reject a result that broke structure
and continue by hand from the previous file.

## 6. Prepare a raster for tracing

1. Short side >= 1000 px for logos; smaller sources first get an upscale (image-editing; native
   or local UPSCALE only, a regenerating upscale changes a logo).
2. Flatten onto a flat background colour that is not in the artwork; crop to the art with ~5%
   margin.
3. Reduce colours to the target palette before tracing (no dithering); line art to pure black and
   white. Commands: [tracing](references/tracing.md).
4. Read the prepared raster: merged colours that should stay distinct mean the count is too low.

| Input | Colours | Expect |
|---|---|---|
| 1-colour line art, stamp | 2 | < 30 paths, tiny file |
| Flat logo | 2-8 (exact brand count) | < 100 paths |
| Flat illustration | 8-24 | 100-1000 paths |
| Posterised photo | 16-64 | thousands of paths, 200 KB+; confirm the caller wants it |

## 7. Cleanup pipeline (order matters; layer-safe)

```bash
python3 -I "$SVG" check raw.svg                        # 1. baseline report; ERRORs block use
python3 -I "$SVG" sanitize raw.svg 1-safe.svg          # 2. strip script, foreignObject, on*, external refs, editor data
# mcp__image__svg_optimize {svg_path: "1-safe.svg", precision: 2, output_path: "2-opt.svg"}   3. optimise (adds a
#                                                        missing viewBox from numeric width/height)
python3 -I "$SVG" check 2-opt.svg                      # 4. still "no viewBox"? add it by hand (Edit)
python3 -I "$SVG" precision 2-opt.svg 3-prec.svg --digits 2    # 5. only if check still reports too many decimals
python3 -I "$SVG" palette 3-prec.svg                   # 6. inspect colours, then:
python3 -I "$SVG" remap 3-prec.svg 4-pal.svg --merge 24 --max-colors 6
python3 -I "$SVG" currentcolor 4-pal.svg 5-mono.svg    # 7. monochrome UI icons only
python3 -I "$SVG" prefix-ids 5-mono.svg 6-ids.svg --prefix ic-cart   # 8. if inlined next to other SVGs
python3 -I "$SVG" fit 6-ids.svg final.svg --size 24 --pad 2          # 9. icon grids only
python3 -I "$SVG" check final.svg --budget icon        # 10. must pass with no ERROR
```

- Layered deliverables: run steps 1-8 first, layer last (`svg_layerize`, `layered: true`, or by
  hand). `sanitize` removes every Inkscape and Sodipodi attribute and optimisers may too; after any
  rewrite of a layered file run `svg_layers` and re-layerize if layers vanished. On layered files
  `check` warns "editor metadata present": expected, do not sanitize.
- Run `precision` / `svg_optimize` only before `fit`. After `fit`, `check` warns about the
  6-decimal `scale()` in fit's wrapper: expected; rounding it (0.023438 → 0.02) shrinks the art ~15%.
- Never let an optimiser remove `viewBox`; svgo alternative and config: [cleanup](references/svg-cleanup.md).
- Accessibility (inline or standalone): first child `<title>`, `role="img"` and `aria-labelledby` on
  the root; decorative SVGs get `aria-hidden="true"` instead.

## 8. Layered SVG

Conventions (full detail and app behaviour: [layers](references/layers.md)):

- Root declares `xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"` (and `xmlns:sodipodi`
  when locking).
- Each layer is a top-level `<g id="layer-<ascii-slug>" inkscape:groupmode="layer"
  inkscape:label="<Human name>">`, a direct child of `<svg>`; nothing drawable outside layers.
- First layer = bottom of the stack. Shared `<defs>` stay at the root with prefixed ids.
- Hidden: `style="display:none"`; locked: `sodipodi:insensitive="true"`; opacity on the group.
- Inkscape shows labels; Illustrator imports top-level groups as layers named from the `id` (keep
  ids readable ascii slugs); Affinity and Figma show groups. Verify on the user's app when it matters.

Ways to get them: `vector_generate {layered: true}` (by groups), `image_vectorize {layered: true}`
(by colour), `svg_layerize {by: "group" | "color" | "mapping", mapping}`, `layers_compose` (SVG and
PNG sources, raster embedded per layer), or by hand. Verify: `svg_layers` (names, order, counts,
palette per layer), and render before and after layering at the same width, diff MAE about 0.

## 9. Layered PDF

`export_pdf {svg_path, layered: true, page_size: "auto"}`: vector PDF; each top-level layer becomes
an Optional Content Group named by its label, toggleable in Acrobat's Layers panel and OCG-aware
editors; hidden layers start off; a non-layered SVG gives a single-layer PDF. `page_size`: `auto`
(the SVG's size; use mm units for print), `A4`, `letter`, or `"WxHmm"` (add bleed by extending the
background layer and the page, e.g. `"216x303mm"` for A4 plus 3 mm).

Verify: list the OCGs (`pikepdf` one-liner in [layers](references/layers.md)), Read the PDF and
compare it with `svg_render` of the same SVG. Converters drop or approximate filters, masks, blend
modes, complex CSS and fonts: simplify the SVG (shapes instead of filters, presentation attributes
instead of CSS, outlined type) and export again. PDF output is RGB; CMYK and spot colours belong to a
design tool or the print shop.

## 10. Budgets and gates

| Asset | Max bytes | Max paths | Max decimals | Colours |
|---|---|---|---|---|
| UI icon (16-48 px use) | 4 KB | 40 | 2 | 1 (`currentColor`) or the 2-3 brand colours |
| Logo / mark | 20 KB | 150 | 3 | brand count exactly |
| Spot illustration | 150 KB | 2,500 | 3 | <= 24 |
| Layered poster or composition | as briefed; say the size | as briefed | 3 | as briefed |

`check --budget icon|logo|illustration` warns on these. Hard gates (block delivery): well-formed,
root `<svg>` in the SVG namespace, `viewBox` present and valid, no `<script>`, `<foreignObject>`,
event handlers or external references, no duplicate ids, no embedded raster unless the brief allows
it (layered compositions with photo layers do).

## 11. Render check

Validation does not prove it looks right: `svg_render {svg_path, width: 512}` → Read the PNG.
Icons and logos also at the smallest real use (`width: 32`): thin strokes must not vanish, counters
must stay open, details below ~1/32 of the height become noise. Use `background: "#FFFFFF"` (or the
brand background) to judge light art; `currentColor` icons render black, as expected. Several
candidates or sizes: one contact sheet (`"$PY" "$IMG" sheet sheet.png a.png b.png c.png`), one Read.

## 12. Review loop with visual-reviewer

Rubric, anchors, revision grammar and stop rules live in the `visual-review` skill that
`visual-reviewer` loads; you supply evidence, apply its revisions and enforce the round count.

1. Self-check first: `svgcheck check`, `svg_inspect`, `svg_layers` (when layered), renders at two
   sizes, PDF Read (when exported). Fix gate failures before review.
2. Spawn `visual-reviewer` (Agent, `run_in_background: false`) per round:
   ```
   Goal: review this vector deliverable against the brief; verdict PASS, REVISE or STOP with revisions.
   Brief: <the vector spec from section 2>
   Files: <final.svg>, renders <512 px and smallest-use PNGs>, <layered PDF if any>
   Facts: svg_inspect summary (paths, palette, bytes), svg_layers list, svgcheck result
   Produced by: op=VECTOR|TRACE, or hand-written / edited; adapter and model tag
   Round <k> of 4. Previous review JSON: <path or none>. Threshold 8, no criterion below 6.
   ```
   It writes `.stack/out/visual-reviewer/<stamp>-<slug>-r<k>.md` and `.json` and replies with the
   paths.
3. PASS (overall >= threshold, default 8, every applicable criterion >= 6): deliver.
4. REVISE: apply the revisions in order, blocking first, respecting the KEEP list. `svg-fix`
   revisions name elements, attributes or layers: apply them by hand (section 5) or with
   `svg_layerize` / `layers_compose` / `export_pdf` as stated, then run the revision's `verify`
   check. `prompt-delta` revisions edit the exact previous `vector_generate` prompt from the sidecar
   (at most 3 changes). `pipeline` (e.g. trace instead of generate, live type layer) goes back to the
   caller as a scope Open doubt. A revision needing an unexposed op: Open doubt naming its env vars.
5. STOP or your own limits: 4 rounds; `budget="hard"`; `budget="soft"` unless one SVG text edit is
   left; plateau (best overall up < 0.3 in each of the last two rounds); the same blocking defect after two
   strategies (Open doubt: better tag, or a hand-drawn rebuild). Regression (overall below the best by
   more than 0.5): continue from the best round's file. Deliver the best round (highest overall with
   no criterion < 6, else highest overall).
6. Trail: `<job>/review-trail.jsonl`, one line per round (files, review JSON path, overall, lowest,
   verdict, change applied); the Result lists rounds, scores, the chosen file and unapplied revisions.
7. Cannot spawn (`remaining_depth="0"`, policy denial, or you are the produce stage of the
   `visual-iterate` workflow): self-review with the same criteria (brief fidelity, composition,
   typography, colour and contrast, artefacts such as jaggies, gaps and stray nodes, technical spec
   including validity, layers and node count), mark it `self-review`, and unless a workflow reviews
   you add an Open doubt recommending a `visual-reviewer` pass. The main thread can run the whole
   loop with `Workflow name=visual-iterate args={brief, kind: "vector", output: {layered: true, pdf: true}}`.

## 13. Worked example: layered badge with a print PDF

Brief: "Badge logo for 'Harbor Coffee': cup inside a circular badge, 3 colours (#1F3A5F, #F2E8D5,
#C8553D), editable layers Background, Badge, Cup, Text; SVG for web and a layered A6 PDF for print."

1. `image_ops_status`: VECTOR exposed (openrouter, `recraft/recraft-v4.1-vector`), VECTOR_MANIPULATION
   `claude`. Spec pinned.
2. `vector_generate {prompt: "Flat logo badge: a coffee cup inside a circular badge ring, built from
   circles and rounded shapes, solid fills, no gradients, 3 colours only: #1F3A5F, #F2E8D5,
   #C8553D, centred with even padding, Swiss minimal, no text.", aspect_ratio: "1:1", n: 2}`.
   Renders at 512 and 64, sheet Read: candidate 2 cleaner (38 paths, 3 colours).
3. Cleanup steps 1-6 (no `fit`, no `currentcolor`): 11 KB, palette exactly 3 colours after
   `remap --merge 20 --max-colors 3`.
4. Text by hand: add `<text x="200" y="330" text-anchor="middle" font-family="Montserrat, sans-serif"
   font-weight="700" font-size="28" fill="#1F3A5F">HARBOR COFFEE</text>` (Edit), render, check spacing.
5. `svg_inspect` shows the shapes have no ids: add them by hand (`id="bg"`, `id="ring"`, ...), then
   `svg_layerize {by: "mapping", mapping: {"Background": ["#bg"], "Badge":
   ["#ring", "#ring-inner"], "Cup": ["#cup", "#steam"], "Text": ["text"]}}` → `05-layered.svg`;
   `svg_layers` shows 4 layers in order; render diff against step 4: MAE 0.0.
6. `export_pdf {svg_path: "05-layered.svg", layered: true, page_size: "105x148mm"}`; OCG check lists
   Background, Badge, Cup, Text; PDF Read matches the render (font substituted: noted for the
   caller, outlined type recommended for print).
7. `visual-reviewer` round 1: overall 7.6, typography 5 ("tracking too tight, text crowds the
   ring"); R1 [blocking] svg-fix on `<text>`: `letter-spacing="2"`, `font-size="24"`. Edit, re-render,
   re-export, verify. Round 2: overall 8.4, lowest 7, PASS.
8. Deliver `05-layered.svg` (no `.min.svg`: optimisation already ran in step 3, and optimising the
   layered file could strip its layer attributes), the PDF, the review trail and the font note.

## 14. Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Tool missing or "not configured" | op not set, or server not reconnected | `image_ops_status`; Open doubt naming the variables |
| `vector_generate` returns PNG/WebP | configured model is raster-only (e.g. Bria vector on Opper) | Open doubt: a Recraft `*-vector` tag on OpenRouter or fal |
| Trace looks redesigned | TRACE is OpenRouter's redraw approximation | Open doubt for `IMAGE_TRACE_API=local` or fal Recraft vectorize |
| Hundreds of tiny paths, speckles | noisy or JPEG source, too many colours | upscale, denoise, quantise before tracing; fewer colours |
| Hairline gaps between shapes | cut-out shapes with anti-aliasing seams | 0.25-0.5 px stroke in the fill colour; stacked mode on the local tracer |
| Colours slightly off-brand | tracer sampled anti-aliased edges | `remap --map '#d32f2f=#d42f2e'` to exact brand hex |
| Layers gone after a cleanup step | sanitize or optimise stripped Inkscape attributes | clean first, layer last; re-run `svg_layerize` |
| Layer order or appearance changed after layerize | same-colour shapes interleaved in depth | `by: "mapping"` with explicit order, or reorder by hand; render diff to confirm |
| PDF lacks layers | SVG had no top-level layer groups, or `layered: false` | layerize, export again; check OCGs |
| PDF looks different from the SVG | unsupported filters, masks, blend modes, CSS or fonts | simplify the SVG (section 9) and re-export |
| Icon blurry at 16-24 px | coordinates off the pixel grid | integers or .5 for odd stroke widths; `precision --digits 1` |
| Fit squashed the artwork | source viewBox had large empty margins | crop the viewBox to the art, then `fit` |
| SVG renders empty | missing namespace, wrong viewBox, no paint | `svg_inspect`; inspect the root and the first shape's paint |
| `svg_transform` result lost ids or layers | external model rewrote the structure | reject; continue by hand from the previous file |
| Inline SVGs on one page interfere | id collisions | `prefix-ids` with a unique prefix per file |
| `check` refuses the file: ENTITY | XML entity declarations | treat as hostile; rebuild from a clean source |
| Generated logo has garbled lettering | model limitation | remove text from the prompt; set type separately |

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `svg-hand-authoring` | writing or editing SVG source directly instead of generating or tracing it |
