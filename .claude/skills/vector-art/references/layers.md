# Layered SVG and layered PDF

Layered deliverables let a designer open the file and find named, ordered, toggleable parts:
Background, Illustration, Text, and so on. This stack writes Inkscape-native layers in SVG (which
Illustrator and other editors import as layers or top-level groups) and turns each layer into a PDF
Optional Content Group (OCG) on export. All tools here are local and free:
`svg_layers`, `svg_layerize`, `layers_compose`, `export_pdf`, plus `svg_inspect` and `svg_render`.

## 1. Markup

```xml
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
     viewBox="0 0 1200 800" width="1200" height="800">
  <title>Spring poster</title>
  <defs>
    <linearGradient id="poster-sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#BFE3F2"/><stop offset="1" stop-color="#F6F1E7"/>
    </linearGradient>
  </defs>
  <g id="layer-background" inkscape:groupmode="layer" inkscape:label="Background">
    <rect width="1200" height="800" fill="url(#poster-sky)"/>
  </g>
  <g id="layer-illustration" inkscape:groupmode="layer" inkscape:label="Illustration">…</g>
  <g id="layer-text" inkscape:groupmode="layer" inkscape:label="Text">…</g>
  <g id="layer-guides" inkscape:groupmode="layer" inkscape:label="Guides"
     style="display:none" sodipodi:insensitive="true">…</g>
</svg>
```

| Rule | Why |
|---|---|
| Layers are direct children of the root `<svg>` | editors treat only top-level groups as layers |
| Nothing drawable at the top level outside layers (only `<defs>`, `<title>`, `<desc>`, `<style>`, `<metadata>`) | stray elements become an unnamed extra layer or get lost on import |
| Document order is stacking order: the first layer is the bottom | SVG paints in order; Inkscape and Illustrator show it reversed (top of the panel = last) |
| `id="layer-<ascii-slug>"` plus `inkscape:label="<Human name>"` | Inkscape shows the label; Illustrator names imported layers from the `id` |
| Shared paint servers, clip paths, symbols and filters in the root `<defs>`, ids prefixed | references are document-wide; collisions swap gradients silently |
| Hidden: `style="display:none"` on the layer | Inkscape convention; also hidden in browsers and off by default in the PDF |
| Locked: `sodipodi:insensitive="true"` | Inkscape lock; other editors ignore it |
| Layer opacity: `opacity="0.6"` on the layer group | becomes group opacity in other editors |
| Sublayers: nested `<g inkscape:groupmode="layer">` | Inkscape sublayers; elsewhere nested groups |
| Prefer no `transform` on layer groups | editors cope, but later edits and PDF placement get harder |
| Conventional names | Background, Illustration or Shapes, Subject, Details, Shadows, Highlights, Text, Annotations or Guides (hidden) |

## 2. Getting layers

| Starting point | Tool call | Result and checks |
|---|---|---|
| New generated SVG | `vector_generate {prompt, layered: true}` | layerized by top-level groups; labels may be generic (`Layer 1`): rename them by hand; check with `svg_layers` |
| Traced raster | `image_vectorize {image, layered: true}` | one layer per colour: right for screen printing, vinyl and laser work; colours that should be grouped by meaning can be remapped with `svg_layerize {by: "mapping"}` |
| Existing SVG with meaningful groups | `svg_layerize {svg_path, by: "group"}` | each top-level group becomes a layer |
| Existing flat SVG, colour separations | `svg_layerize {svg_path, by: "color"}` | one layer per fill colour; if same-colour shapes interleave in depth with other colours, grouping can change stacking: compare renders |
| Existing SVG, named parts | `svg_layerize {svg_path, by: "mapping", mapping: {"Background": ["#bg"], "Mark": ["#mark", "#mark-shadow"], "Wordmark": ["text", "#wordmark"]}}` | ids or CSS-like selectors per layer, in bottom-to-top order; check `svg_layers` for elements nobody claimed |
| Raster and vector parts together | `layers_compose {layers: [{source: "photo.png", name: "Photo"}, {source: "logo.svg", name: "Logo", x: 880, y: 40, width: 280, height: 120}, {source: "grain.png", name: "Grain", opacity: 0.3, visible: false}], width: 1200, height: 800}` | one layered SVG; raster sources embedded as `<image>` data URIs in their own layer (large files; `svg_inspect` reports embedded rasters) |
| By hand | Edit: wrap runs of elements in layer groups | [svg-editing](svg-editing.md) recipe "Make a layer" |

Verification after any layering step:

1. `svg_layers {svg_path}` → id, label, visibility, element count and palette per layer, in order.
   Expected names, order and counts; no empty layer; no stray top-level elements (`svg_inspect`).
2. Appearance unchanged: `svg_render` the file before and after at the same width, then
   `masktool.py diff before.png after.png`: MAE about 0. A visible change means the layering
   reordered overlapping shapes; fix the mapping or reorder by hand.
3. Rewrites strip layers: `svgcheck.py sanitize` removes every Inkscape and Sodipodi attribute, and
   optimisers may too. Run sanitize and `svg_optimize` before layering, not after; whenever
   something rewrote a layered file, run `svg_layers` again and re-layerize if the layers vanished.
   `svgcheck.py check` warns "editor metadata present" on layered files: expected, do not sanitize.

## 3. How editors open the layers

Behaviour as commonly reported; versions differ, so verify on the user's application when the
hand-off matters and say what you checked.

| Application | Opens as | Notes |
|---|---|---|
| Inkscape 1.x | native layers with labels, visibility, lock, sublayers | reference implementation |
| Adobe Illustrator | top-level groups as layers named from the `id`; nested groups stay groups | Inkscape attributes are ignored; hidden state may not carry over; ids with spaces or punctuation get escaped, so keep them ascii slugs |
| Affinity Designer / Studio | top-level groups as layer groups | |
| Figma | frames and groups in the layer panel, named from ids | no hidden or locked state |
| Browsers, `<img>` | no layer semantics; `display:none` layers stay invisible | deliver web SVGs without hidden layers |

When the user needs Illustrator layers that are certain, also deliver the layered PDF (section 4):
Illustrator and Acrobat both understand OCGs.

## 4. Layered PDF with `export_pdf`

`export_pdf {svg_path, output_path?, layered: true, page_size: "auto"}` writes a vector PDF. With
`layered: true` every top-level SVG layer becomes an Optional Content Group named by its label, with
its content wrapped in marked content, listed in the document's `/OCProperties`; viewers show them in
a Layers panel (Acrobat and Reader; most OCG-aware editors; browser viewers often ignore them). A
non-layered SVG, or `layered: false`, gives an ordinary single-layer PDF.

| `page_size` | Use |
|---|---|
| `auto` (default) | page = the SVG's own size; give the SVG physical units (`width="210mm" height="297mm"`) for print |
| `A4`, `letter` | standard sheets; check placement and scaling in the rendered PDF |
| `"WxHmm"`, e.g. `"216x303mm"` | custom trim, or trim plus 3 mm bleed on each side (extend the background layer into the bleed in the SVG first) |

Verify every PDF:

```bash
# Layers (OCGs) present, in order, with their names
"$PY" -c "import sys, pikepdf; p = pikepdf.open(sys.argv[1]); oc = p.Root.get('/OCProperties'); print([str(g.Name) for g in oc.OCGs] if oc else 'no OCGs')" out.pdf
```

Then Read the PDF (first page) and compare with the `svg_render` of the same SVG side by side.
If pikepdf is missing from the stack venv, say the OCG check was not run.

SVG-to-PDF conversion has known gaps; look for them in the comparison and simplify the SVG before
exporting rather than accepting a broken PDF:

| Feature | Typical problem | Fix before export |
|---|---|---|
| Filters (blur, drop shadow) | dropped or rasterised | replace with shapes (offset darker copy, gradient) or put a PNG shadow in its own layer via `layers_compose` |
| Masks, complex clip paths | lost or approximated | flatten the masked artwork; use simple clip paths |
| Blend modes, `mix-blend-mode` | ignored | pre-mix the colours |
| CSS in `<style>` with complex selectors | partly applied | move paint to presentation attributes on elements |
| `<text>` | font substitution changes metrics | outline type in a design tool, or accept and tell the caller which fonts to install |
| CMYK, spot colours, overprint | not produced (RGB only) | hand the layered PDF to a design tool or print shop for separation |

Deliver the PDF next to the layered SVG; the SVG stays the editable master.
