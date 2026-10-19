# Editing SVG directly (the default vector manipulation)

With `IMAGE_VECTOR_MANIPULATION_MODEL=claude` (the default) there is no `svg_transform` tool: you
change SVG files yourself with Read and Edit (or a short stdlib script for bulk edits) and check
every change with `svg_inspect`, `svg_render` and, at the end, `svg_optimize`. Text edits are
exact, cheap and leave everything you did not touch byte-identical; a regeneration would redraw
the whole asset.

Shell variables as in SKILL.md (`STACK`, `PY`, `SVG` for svgcheck.py, `IMG` for imgcheck.py).
`J` is the job folder, e.g. `.stack/images/vector/<slug>`.

## 1. The edit loop

1. Keep the original: `mkdir -p $J && cp in.svg $J/00-original.svg`. Every change produces the next
   numbered file (`01-recolour.svg`, `02-layers.svg`); copy, then Edit the copy. Log each step in
   `$J/steps.jsonl` (`{"step":1,"op":"edit","in":"00-original.svg","out":"01-recolour.svg","what":"#D32F2F -> #C62828 (14 fills)"}`).
2. Orient with `mcp__image__svg_inspect {svg_path}`: well-formedness, viewBox and size, element
   and path counts, palette, layers, text elements, embedded rasters, complexity and flagged
   problems. Note the ids you will touch.
3. Read only what you need. Under ~60 KB: Read the file. Larger, or files whose path data sits on
   very long lines: `grep -n -o '<[a-zA-Z:]* [^>]*id="[^"]*"' file.svg | cut -c1-160` to map
   elements and ids, `grep -n 'fill=\|stroke=\|stop-color\|<style' file.svg | cut -c1-160` for paint,
   then Read line ranges.
4. Edit with a unique `old_string` anchored on the element's `id` or a distinctive attribute. Change
   attributes and wrappers rather than path geometry.
5. Check: `svg_inspect` again (still well-formed; counts changed only as intended), then
   `python3 -I "$SVG" check $J/01-recolour.svg` for safety and budgets.
6. Look: `svg_render {svg_path, width: 512}` → Read the PNG. For a before/after, render both at the
   same width and put them on one sheet (`"$PY" "$IMG" sheet $J/cmp.png before.png after.png`). For a
   change that must not alter appearance (restructuring, layerizing), diff the renders:
   `"$PY" "$STACK/.claude/skills/image-editing/scripts/masktool.py" diff before.png after.png` → MAE ~0.
7. Finish: `svg_optimize` only for non-layered deliverables (it may strip editor attributes; see
   [layers](layers.md)), then the budget check.

## 2. Recipes

| Goal | Edit | Watch out |
|---|---|---|
| Recolour one element | change its `fill`/`stroke` attribute or the `fill:`/`stroke:` property inside `style` | the same colour may also live in a gradient `stop-color` or a `<style>` rule |
| Recolour across the file | Edit with `replace_all` on each exact form (`fill="#d32f2f"`, `fill:#d32f2f`, `stop-color="#d32f2f"`), or `python3 -I "$SVG" remap in.svg out.svg --map '#d32f2f=#c62828'` | case variants, short hex (`#d33`), `rgb()` and named colours; confirm with `svg_inspect` palette |
| Change one use of a shared gradient | duplicate the `<linearGradient>` with a new prefixed id, point the element at it | other users of the old id must not change |
| Theme a monochrome icon | `python3 -I "$SVG" currentcolor in.svg out.svg` | renders black in previews; that is expected |
| Move | wrap in `<g transform="translate(dx dy)">…</g>` or extend an existing `transform` | never rewrite path coordinates by hand |
| Scale about a point (cx, cy) | `transform="translate(cx cy) scale(s) translate(-cx -cy)"` | stroke widths scale too; add `vector-effect="non-scaling-stroke"` to keep them |
| Rotate | `transform="rotate(deg cx cy)"` | |
| Mirror horizontally inside width W | `transform="translate(W 0) scale(-1 1)"` | text mirrors too |
| Bring forward or send back | move the element's block later (on top) or earlier (below) in document order, inside the right layer | two Edits (cut, then insert); element count must stay the same |
| Delete an element | remove it, then `grep -n -e 'url(#ID)' -e 'href="#ID"'` for dangling references | removing a `<defs>` child breaks every user |
| Add a shape | write primitives (`<rect>`, `<circle>`, `<line>`, simple `<path d>`) in the target layer | use the file's units and palette |
| Change stroke weight | `stroke-width` on the element or group | check at the smallest render size |
| Crop or pad the canvas | edit `viewBox="minx miny w h"`; padding p: `minx-p miny-p w+2p h+2p`; keep `width`/`height` in the same ratio | an optimiser must never drop the `viewBox` |
| Centre the art | render with a transparent background, measure the bounding box, convert px to user units (factor = viewBox width / render width), then translate | `"$PY" -c "from PIL import Image; print(Image.open('r.png').getchannel('A').getbbox())"` |
| Change text | edit the text node; keep `font-family` with a generic fallback (`, sans-serif`) | fonts differ between renderers and PDF export; logos need outlined text |
| Make a layer | wrap a contiguous run of elements in `<g id="layer-x" inkscape:groupmode="layer" inkscape:label="X">` (declare `xmlns:inkscape` on the root) | non-contiguous elements: `svg_layerize {by: "mapping"}` and compare renders |
| Hide or lock a layer | `style="display:none"`; `sodipodi:insensitive="true"` (declare `xmlns:sodipodi`) | hidden layers stay hidden in browsers and in the PDF default view |
| Rename a layer | change `inkscape:label` and, for Illustrator users, the `id` | ids must stay unique; update references |
| Accessibility | first child `<title id="…-title">`, root `role="img" aria-labelledby="…-title"`; decorative: `aria-hidden="true"` | |

## 3. Bulk or structural edits with a script

More than ~20 similar edits, or edits scoped to one layer: a stdlib script in the scratchpad, never
in the project, run with `python3 -I`, writing a new numbered file. Register the namespaces so
prefixes survive (ElementTree drops comments, which is fine).

```python
# recolour_layer.py  usage: python3 -I recolour_layer.py IN OUT "Layer label" "#old" "#new"
import sys, xml.etree.ElementTree as ET
NS = {"svg": "http://www.w3.org/2000/svg", "inkscape": "http://www.inkscape.org/namespaces/inkscape",
      "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd", "xlink": "http://www.w3.org/1999/xlink"}
for p, u in NS.items():
    ET.register_namespace("" if p == "svg" else p, u)
src, out, label, old, new = sys.argv[1:6]
tree = ET.parse(src)
hits = 0
for g in tree.getroot().findall("svg:g", NS):
    if g.get("{%s}label" % NS["inkscape"]) == label:
        for el in g.iter():
            for attr in ("fill", "stroke"):
                if (el.get(attr) or "").lower() == old.lower():
                    el.set(attr, new); hits += 1
tree.write(out, xml_declaration=True, encoding="utf-8")
print(hits, "attributes changed")
```

Then `svg_inspect`, `svg_layers` and a render as in the loop.

## 4. What not to do by hand

| Task | Why | Route |
|---|---|---|
| Boolean union, difference, intersection of paths | needs a geometry kernel | `svg_transform` if exposed (then verify); Inkscape CLI if installed and the caller approves (find the action names in `inkscape --action-list`, e.g. `path-union`); else deliver unmerged and say so |
| Stroke to outline (cutters, logos) | same | as above (`object-stroke-to-path` in Inkscape 1.x; confirm with `--action-list`) |
| Text to outlines | needs the font's outlines | design tool; or set the wordmark separately |
| Smoothing a noisy trace | thousands of nodes | re-trace from a better-prepared raster ([tracing](tracing.md)) |
| A new drawing or a restyle of the whole piece | that is generation | `vector_generate` (IMAGE_VECTOR) |

## 5. `svg_transform` (only when an external model is configured)

Exposed only when `IMAGE_VECTOR_MANIPULATION_MODEL` names a model other than `claude` and its URL
and KEY are set (an OpenAI-compatible chat endpoint; the server appends `/chat/completions` and
validates that the reply is well-formed SVG before writing it). Parameters: `svg_path`,
`instruction`, optional `output_path`.

- Use it for changes that are hard as text edits (restyles across many paths, geometry changes,
  "make the strokes bolder and rounder"). Keep exact, mechanical changes (a recolour, a move, a
  layer rename) as your own edits: they are deterministic.
- Write constraints into the instruction: "keep the viewBox, every id, the top-level layer groups
  and their inkscape:label values, the palette <hex list>; no raster images, no scripts, no external
  references".
- After every call: `svg_inspect` (counts), `svg_layers` (same layers, same order), palette compared
  with the previous step, `svgcheck check` (safety), and a before/after render sheet. A result that
  lost layers or changed what it should not is rejected; continue with hand edits from the previous
  numbered file and note it in the step log.
