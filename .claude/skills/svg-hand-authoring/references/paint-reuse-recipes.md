# Paint, reuse, theming and animation recipes

Companion to the svg-hand-authoring SKILL.md. Shell variables as there (`SVG` = svgcheck.py,
`GEO` = svggeom.py). The standalone SVG snippets pass `svgcheck check` and the fragments were checked
inside a test document (rendered with resvg); render-check after adapting them.

## 1. Defaults that decide what you see

| Element | Attribute | Default | Consequence |
|---|---|---|---|
| `linearGradient`, `radialGradient` | `gradientUnits` | `objectBoundingBox` | coordinates are fractions of the painted element's bbox (stroke excluded); a zero-height or zero-width bbox (horizontal or vertical line) ignores the gradient |
| `linearGradient` | `x1 y1 x2 y2` | `0% 0% 100% 0%` | left to right; vertical needs `x2="0" y2="1"` |
| `radialGradient` | `cx cy r`, `fx fy` | `50% 50% 50%`, focus = centre | move `fx fy` for an off-centre highlight |
| gradients | `spreadMethod` | `pad` | `reflect` / `repeat` for stripes beyond the vector |
| `pattern` | `patternUnits` / `patternContentUnits` | `objectBoundingBox` / `userSpaceOnUse` | tile size is a bbox fraction while tile content is in user units: set `patternUnits="userSpaceOnUse"` for fixed-size tiles |
| `clipPath` | `clipPathUnits` | `userSpaceOnUse` | clip geometry in the user space of the referencing element |
| `mask` | `maskUnits` / `maskContentUnits` | `objectBoundingBox` / `userSpaceOnUse` | mask region x/y/width/height default -10% -10% 120% 120% of the bbox: content outside is cut |
| `mask` | `mask-type` (CSS) | `luminance` | white shows, black hides; `mask-type="alpha"` uses alpha only |
| `filter` | `filterUnits` / `primitiveUnits` | `objectBoundingBox` / `userSpaceOnUse` | region default -10% -10% 120% 120%: blurs and drop shadows wider than 10% of the bbox are clipped |
| `symbol` | `preserveAspectRatio` | `xMidYMid meet` | `<use width height>` with another ratio letterboxes instead of stretching |
| `use` | `width`, `height` | unset: the symbol fills 100 % of the viewport | only meaningful when the target is a `symbol` or `svg` (with a viewBox) |

## 2. Gradients and clip paths

```xml
<defs>
  <!-- vertical sky, bbox units: follows whatever shape uses it -->
  <linearGradient id="sp-sky" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#9fd3ff"/><stop offset="1" stop-color="#eaf6ff"/>
  </linearGradient>
  <!-- one gradient across several shapes, or on a straight stroke: user space -->
  <linearGradient id="sp-rule" gradientUnits="userSpaceOnUse" x1="2" y1="0" x2="22" y2="0">
    <stop offset="0" stop-color="#e11d48"/><stop offset="1" stop-color="#7c3aed"/>
  </linearGradient>
  <!-- off-centre highlight on a ball -->
  <radialGradient id="sp-ball" cx="0.5" cy="0.5" r="0.5" fx="0.35" fy="0.3">
    <stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#2563eb"/>
  </radialGradient>
  <clipPath id="sp-frame"><rect width="160" height="100" rx="12"/></clipPath>
  <!-- soft fade: luminance mask, explicit region in user space -->
  <linearGradient id="sp-fadegrad" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0.6" stop-color="#fff"/><stop offset="1" stop-color="#000"/>
  </linearGradient>
  <mask id="sp-fade" maskUnits="userSpaceOnUse" x="0" y="0" width="160" height="100">
    <rect width="160" height="100" fill="url(#sp-fadegrad)"/>
  </mask>
</defs>
<path d="M2 12H22" stroke="url(#sp-rule)" stroke-width="2"/>   <!-- bbox units would paint nothing -->
<g clip-path="url(#sp-frame)">…</g>
<g mask="url(#sp-fade)">…</g>
```

Clip versus mask: a clip is pure geometry (hard, anti-aliased edge, cheap, paint ignored); a mask is
an image (soft fades, partial transparency, costlier, and converters to PDF or print often rasterise
or drop it). Use the clip whenever the edge is hard.

Shadows in icons: an offset copy of the shape in a darker colour beats `<filter>`; filters cost a
full-resolution raster pass at every size and print pipelines approximate them.

## 3. Symbol sprite builder (stdlib)

Turns single-icon files into one sprite; each icon's ids are prefixed with its symbol id so two icons
that both define `id="g"` stay distinct; the root paint attributes move onto the `<symbol>` (they
inherit to the children); titles are dropped because the label belongs at the use site.

```python
# build_sprite.py  usage: python3 -I build_sprite.py OUT.svg PREFIX icon1.svg icon2.svg ...
import os, re, sys, xml.etree.ElementTree as ET
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)
PAINT = ("fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "fill-rule")
out, prefix, files = sys.argv[1], sys.argv[2], sys.argv[3:]
sprite = ET.Element("{%s}svg" % SVG, {"aria-hidden": "true", "width": "0", "height": "0",
                                     "style": "position:absolute;overflow:hidden"})
for path in files:
    root = ET.parse(path).getroot()
    name = "%s-%s" % (prefix, os.path.splitext(os.path.basename(path))[0])
    sym = ET.SubElement(sprite, "{%s}symbol" % SVG, {"id": name, "viewBox": root.get("viewBox", "0 0 24 24")})
    for k in PAINT:
        if root.get(k):
            sym.set(k, root.get(k))
    ids = {el.get("id") for el in root.iter() if el.get("id")}
    ren = lambda v: re.sub(r"url\(#([^)]+)\)", lambda m: "url(#%s-%s)" % (name, m.group(1)) if m.group(1) in ids else m.group(0), v)
    for child in list(root):
        if child.tag in ("{%s}title" % SVG, "{%s}desc" % SVG, "{%s}metadata" % SVG):
            continue
        for el in child.iter():
            for k, v in list(el.attrib.items()):
                if k == "id":
                    el.set(k, "%s-%s" % (name, v))
                elif k in ("href", "{http://www.w3.org/1999/xlink}href") and v[1:] in ids:
                    el.set(k, "#%s-%s" % (name, v[1:]))
                elif "url(#" in v:
                    el.set(k, ren(v))
        sym.append(child)
ET.ElementTree(sprite).write(out, encoding="utf-8")
print(out, len(files), "symbols")
```

Run it on sanitized inputs only (`svgcheck sanitize` first), then `svgcheck check sprite.svg`: the
"no viewBox" warning is expected for the hidden sprite root. The script does not rewrite `#id`
selectors inside `<style>` blocks: keep icon CSS in the page or prefix by hand.

```html
<!-- once per page, hidden without display:none (that can stop gradients, clips and masks
     defined inside it from rendering in some browsers) -->
<svg aria-hidden="true" width="0" height="0" style="position:absolute;overflow:hidden">…symbols…</svg>
<!-- decorative next to text -->
<svg class="icon" aria-hidden="true"><use href="#ic-cloud-upload"/></svg> Upload
<!-- meaningful on its own -->
<svg class="icon" role="img" aria-labelledby="up-t"><title id="up-t">Upload</title><use href="#ic-cloud-upload"/></svg>
<!-- icon-only control: the label sits on the control -->
<button type="button" aria-label="Upload"><svg class="icon" aria-hidden="true"><use href="#ic-cloud-upload"/></svg></button>
<!-- external sprite: same origin only, the browser may refuse cross-origin <use> -->
<svg class="icon" aria-hidden="true"><use href="/static/icons.svg#ic-cloud-upload"/></svg>
```

```css
.icon { width: 1.5rem; height: 1.5rem; color: inherit; }        /* currentColor follows text */
.icon--accent { --icon-accent: #e11d48; }                         /* reaches into the use clone */
```

## 4. Theming recipes

Two-tone icon for inline use on the web: the main paint is `currentColor`, the accent a custom
property with a fallback, set through CSS (a `style` attribute or a class rule):

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <circle cx="12" cy="12" r="9"/>
  <circle cx="12" cy="12" r="3.5" style="fill:var(--icon-accent,#e11d48);stroke:none"/>
</svg>
```

- Inside `<img>` or a CSS background the page's `color` and custom properties do not reach the file:
  `currentColor` renders black and the accent uses its fallback (browsers).
- Non-browser renderers do not implement `var()`: resvg (behind `svg_render`) painted all three
  forms (`style`, class rule over a literal `fill`, `fill="var(...)"`) black in a test. Files that
  also go to `svg_render`, `export_pdf` or a design tool keep literal colours; preview a web file
  through a copy with the fallbacks substituted:
  `sed -E 's/var\(--[A-Za-z0-9-]+, *(#[0-9A-Fa-f]{3,8})\)/\1/g' icon.svg > preview.svg`.

Adaptive favicon (SVG favicons: Chrome and Edge 80+, Firefox 41+, Safari 26+; browsers may only
pick up a colour-scheme change on reload):

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <style>
    .fg { fill: #0f172a }
    @media (prefers-color-scheme: dark) { .fg { fill: #f8fafc } }
  </style>
  <path class="fg" d="M3 16A13 13 0 1 1 29 16A13 13 0 1 1 3 16ZM9 16A7 7 0 1 0 23 16A7 7 0 1 0 9 16Z"/>
</svg>
```

```html
<link rel="icon" href="/favicon.ico" sizes="32x32">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">   <!-- 180x180 PNG, opaque background -->
```

## 5. Animation snippets

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
     stroke-width="2" stroke-linecap="round" role="img" aria-labelledby="ld-t">
  <title id="ld-t">Loading</title>
  <style>
    .spin { transform-box: fill-box; transform-origin: center; animation: ld-spin 1s linear infinite }
    .draw { animation: ld-draw .8s ease-out }
    @keyframes ld-spin { to { transform: rotate(1turn) } }
    @keyframes ld-draw { from { stroke-dasharray: 1; stroke-dashoffset: 1 }
                         to   { stroke-dasharray: 1; stroke-dashoffset: 0 } }
    @media (prefers-reduced-motion: reduce) { .spin, .draw { animation: none } }
  </style>
  <path class="spin" d="M21 12A9 9 0 1 1 12 3"/>
  <path class="draw" pathLength="1" d="M8 12.5 10.5 15 16 9.5"/>
</svg>
```

- `transform-box: fill-box` makes `transform-origin: center` the element's own bbox centre; without
  it the origin is the viewBox origin and the arc swings around the top-left corner.
- `pathLength="1"` normalises dash lengths (path, circle, ellipse, line, polyline, polygon, rect), so
  one keyframe pair draws any path; the alternative is `getTotalLength()` in script.
- Keep the dash properties inside the keyframes: the un-animated state (static renderers, reduced
  motion, the end of the run) is then the plain, complete stroke. resvg ignores `pathLength` for
  dashes, so a static `stroke-dasharray: 1` previews as a dashed line in `svg_render`.
- Keyframe names share the page's namespace when inlined: prefix them like ids.
- SMIL, when the file must animate without CSS (it also runs inside `<img>`):
  `<animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="1s" repeatCount="indefinite"/>`.
  SMIL has no reduced-motion hook; prefer CSS when motion must be optional. Never animate `href`
  (`svgcheck check` reports it as an injection vector).
- Animate `transform` and `opacity`; animating `d`, filters or masks repaints the whole subtree.
  The reduced-motion state and the static rendering must show the complete icon.
