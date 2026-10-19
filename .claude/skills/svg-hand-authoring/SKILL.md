---
name: svg-hand-authoring
description: "Hand-written SVG craft for icons and illustrations: viewBox and coordinate maths, path grammar including arcs, primitives versus paths, generated geometry, stroke versus outlined fill, fill rules, symbols and sprites, gradients and clip paths with prefixed ids, CSS theming, lightweight animation, and accessible, safe embedding. Load when writing or editing SVG source directly instead of generating or tracing it."
when_to_use: "Writing or editing .svg files or inline <svg> by hand: 24-grid icons, badges, diagrams, spot illustrations, <symbol>/<use> sprites, dark-mode SVG favicons, path d strings with A arcs. Symptoms: an arc bulging the wrong way, a ring whose hole fills in, a gradient missing on a straight line, strokes growing under a transform, icons blurry at 16-24 px, id collisions between inlined SVGs, animation ignoring reduced motion, strokes to convert to fills for a cutter."
---

# SVG hand-authoring

Hand-write when the art is constructible (vector-art's routing hands icons, badges and diagrams of
up to ~20 primitives, and every edit of an existing SVG, to hand-writing); generate or trace art you
cannot construct.
Done means: well-formed, safe, on the grid, themeable, accessible, `svgcheck check --budget` without
ERROR, and correct when rendered at its smallest and largest use.

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
SVG="$STACK/.claude/skills/vector-art/scripts/svgcheck.py"         # check sanitize prefix-ids precision fit ...
GEO="$STACK/.claude/skills/svg-hand-authoring/scripts/svggeom.py"  # polygon star circle ring arc points rrect pill rpoly cross snap
PY="$STACK/.venv/bin/python"; IMG="$STACK/.claude/skills/image-generation/scripts/imgcheck.py"
python3 -I "$GEO" --help; python3 -I "$SVG" check icon.svg --budget icon     # exit 1 on any ERROR
```

Render: `mcp__image__svg_render {svg_path, width}` (resvg), or locally `resvg -w 32 in.svg out.png`,
`rsvg-convert -w 32 -o out.png in.svg`, macOS `qlmanage -t -s 64 -o outdir in.svg` (writes
`outdir/in.svg.png`). Variables do not persist between Bash calls; set them in the same command.
Recipes for paint servers, sprites, favicons and animation: [paint and reuse recipes](references/paint-reuse-recipes.md).

## 1. Coordinate system

`viewBox="min-x min-y w h"` defines the user units; with the default `meet` the scale is
`s = min(W_px / w, H_px / h)` and the art is centred in the spare axis.

| 24-grid icon rendered at | 16 px | 20 px | 24 px | 32 px | 48 px |
|---|---|---|---|---|---|
| 1 user unit | 0.67 px | 0.83 px | 1 px | 1.33 px | 2 px |
| stroke-width 2 | 1.33 px | 1.67 px | 2 px | 2.67 px | 4 px |
| detail of 0.5 unit | 0.33 px (gone) | 0.42 px | 0.5 px | 0.67 px | 1 px |

| `preserveAspectRatio` | Effect | Use |
|---|---|---|
| `xMidYMid meet` (default) | whole viewBox visible, centred, letterboxed | icons, logos, illustrations |
| `xMidYMid slice` | viewport covered, overflow cropped | hero backgrounds, patterns |
| `none` | stretched to the viewport | never for art: circles become ellipses, strokes uneven |
| `xMinYMin meet` ... `xMaxYMax meet` | aligned to an edge | art pinned to a corner of a wider box |

- Pad or crop by editing the viewBox: padding p gives `min-x-p min-y-p w+2p h+2p`; never by moving
  every coordinate.
- Omit `width`/`height` for responsive use: inline SVG then follows CSS and the viewBox ratio. An
  `<img>` of such a file has a ratio but no intrinsic size, so give the `<img>` a CSS size (otherwise
  the CSS default object size, 300x150 fitted to the ratio, applies). Keep `width`/`height` for
  fixed-size consumers (email, rasterisers that default to them, print in `mm`).
- Transforms scale everything, stroke width included: `scale(2)` turns stroke 1 into 2, non-uniform
  scales make strokes uneven. `vector-effect="non-scaling-stroke"` measures the stroke in screen
  pixels instead, so it no longer grows with the icon: right for charts and maps at variable zoom,
  wrong for icons. resvg (`svg_render`) ignored it in a test (stroke still scaled): check in a browser.

## 2. Path grammar

| Command | Parameters | Meaning |
|---|---|---|
| `M` / `m` | x y | move; extra pairs after M are implicit L |
| `L` / `l`, `H` / `h`, `V` / `v` | x y, x, y | straight line, horizontal, vertical |
| `C` / `c` | x1 y1 x2 y2 x y | cubic Bezier with two control points |
| `S` / `s` | x2 y2 x y | cubic whose first control point mirrors the previous one (smooth joins) |
| `Q` / `q`, `T` / `t` | x1 y1 x y, x y | quadratic, and its smooth continuation |
| `A` / `a` | rx ry rot large-arc sweep x y | elliptical arc to x y |
| `Z` / `z` | none | close to the subpath start (joins the stroke; no cap there) |

Uppercase is absolute, lowercase relative to the current point. Arcs, verified with renders of the
chord (8,12) to (16,12) and r = 5 (the two candidate centres are (12,9) and (12,15)):

| `A5 5 0 large sweep 16 12` | Arc drawn | Extreme point |
|---|---|---|
| `0 1` | short arc, clockwise on screen | bulges up to (12,10) |
| `0 0` | short arc, counter-clockwise | bulges down to (12,14) |
| `1 1` | long arc, clockwise | up and around to (12,4) |
| `1 0` | long arc, counter-clockwise | down and around to (12,20) |

- sweep 1 = increasing angle = clockwise on screen (y points down); large-arc 1 = the arc over 180.
- A radius too small for the chord is scaled up until the arc is a half circle (`A1 1 0 0 1 16 12`
  from (8,12) still reaches (12,8)); `rx` or `ry` of 0 draws a straight line.
- An arc whose end equals its start draws nothing: a circle needs two halves.

| Shape | Path |
|---|---|
| circle c(12,12) r 9 | `M3 12A9 9 0 1 1 21 12A9 9 0 1 1 3 12Z` (clockwise); `M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0Z` (relative, counter-clockwise: the hole of a ring) |
| rounded rect 18x14 at (3,5), r 3 | `M6 5H18A3 3 0 0 1 21 8V16A3 3 0 0 1 18 19H6A3 3 0 0 1 3 16V8A3 3 0 0 1 6 5Z` |
| pill 16x6 at (4,9) | `M7 9H17A3 3 0 0 1 17 15H7A3 3 0 0 1 7 9Z` |

Precision: 2 decimals for icons (0.01 unit on a 24 grid is invisible at icon sizes), 1-2 for
illustrations, at most 3 for logos (`svgcheck` budgets). Round coordinates, never radii towards a
smaller value: a radius below half the chord is silently enlarged and the curve changes.

## 3. Primitives versus paths

| Element | Keep it when | Notes |
|---|---|---|
| `<rect x y width height rx>` | frames, bars, buttons, backgrounds | `rx` alone rounds all corners; per-corner radii need a path |
| `<circle>`, `<ellipse>` | dots, rings, knobs | `r` and `cx` are readable and animatable |
| `<line>`, `<polyline>` | strokes only | a fill on a polyline closes it implicitly; use a polygon or path |
| `<polygon>` | closed straight shapes | |
| `<path>` | curves, arcs, compound shapes, holes | one element, one fill-rule |

Convert to `<path>` only when a step needs it: boolean union or difference (a geometry tool such as
Inkscape's path actions, never by hand; vector-art lists the routes), one-path-per-glyph pipelines
(icon fonts, picosvg), shape morphing (same command structure on both ends), or stroke outlining. Otherwise primitives stay smaller, readable and easy to
edit. `svgcheck check` budgets count `<path>` elements only.

## 4. Generated geometry with stdlib Python

| Need | Formula |
|---|---|
| point at angle t (degrees, 0 = 3 o'clock, clockwise) | (cx + r cos t, cy + r sin t) |
| regular N-gon, vertex at the top | t_i = -90 + 360 i / N |
| star with N points | alternate r_out and r_in every 180 / N degrees; regular pentagram r_in = r_out cos72 / cos36 = 0.382 r_out |
| arc flags from angles a0 to a1 | large = abs(a1 - a0) > 180; sweep = a1 > a0 |
| fillet radius r in a corner of interior angle theta | tangent length t = r / tan(theta / 2); tangent points P + u t and P + v t |
| circle-circle crossing (cloud lobes) | a = (r0^2 - r1^2 + d^2) / 2d, h = sqrt(r0^2 - a^2) |
| crisp edges at 1x | odd stroke width: coordinates on .5; even width and fills: integers |

`svggeom.py` implements these (importable functions or CLI); outputs below are real:

```bash
python3 -I "$GEO" polygon 12 12 9 6      # M12 3L19.79 7.5L19.79 16.5L12 21L4.21 16.5L4.21 7.5Z
python3 -I "$GEO" star 12 12 10 3.82 5   # regular five-point star
python3 -I "$GEO" ring 12 12 9 5         # outer clockwise + inner counter-clockwise: a hole under any fill-rule
python3 -I "$GEO" arc 10 10 6 166.6 356.5   # M4.16 11.39A6 6 0 1 1 15.99 9.63
python3 -I "$GEO" points 12 12 9 0 45 90    # 21,12 18.36,18.36 12,21
python3 -I "$GEO" rpoly 2 12,3 21,20 3,20   # triangle with r 2 fillets (errors if r does not fit)
python3 -I "$GEO" cross 6.5 14 3.5 10 10 6  # 4.16,11.39 at 228.1 / 166.6 degrees, and the lower crossing
python3 -I "$GEO" snap 1 3 3.2 11.7         # 3.5 3.5 11.5 (stroke 1); "snap 2" gives 3 3 12
```

For bespoke shapes import it (`sys.path.insert(0, "$(dirname "$GEO")")`, then `import svggeom as g`)
and chain `g.arc_to(...)` segments into one `d` string (section 12); keep its 2-decimal output rather
than re-rounding later.

## 5. Strokes

| Property | Values | Rule |
|---|---|---|
| `stroke-linecap` | `butt` (default), `round`, `square` | round and square extend each open end by w/2: keep line ends w/2 inside the live area |
| `stroke-linejoin` | `miter` (default), `round`, `bevel` | icon systems: round caps and joins, consistent everywhere |
| `stroke-miterlimit` | default 4 | miter length / w = 1 / sin(theta / 2); joins sharper than 2 asin(1/4) = 28.96 degrees are bevelled; raise to 8-10 for sharp chevrons, or use round joins |
| SVG 2 `arcs`, `miter-clip` joins | | little renderer support; do not use |

Strokes are centred on the geometry (half inside, half outside); `stroke-alignment` never shipped.
Inside stroke: inset the geometry by w/2, or clip the shape to itself and double the width.
Outside stroke: `paint-order="stroke"` with double width (the fill covers the inner half), or an
offset shape.

| Deliverable | Strokes or outlined fills |
|---|---|
| UI icon set | strokes: themeable width, crisp; one width per set (2 on a 24 grid) |
| logo, mark | outlined fills: identical in every renderer, no stroke-width surprises when scaled |
| vinyl or laser cutter, embroidery, icon font, single-path glyph | outlined fills |
| pen plotter | strokes as centre lines, no fills: do not outline |

Outline strokes with a geometry tool, never by hand-editing points:

```bash
picosvg --output_file out.svg in.svg     # strokes and clip paths to filled paths, <use> materialised,
                                         # absolute coordinates; <text> needs --allow_text (passed through)
inkscape --batch-process --actions='select-all;object-stroke-to-path;export-filename:out.svg;export-do' in.svg
python3 -I "$SVG" sanitize out.svg clean.svg && python3 -I "$SVG" precision clean.svg final.svg --digits 2
```

Both tools must be installed, or fetched only with the caller's approval (`uvx picosvg` pulls
skia-pathops). The Inkscape action names exist in Inkscape 1.x; confirm with
`inkscape --action-list | grep -i stroke`; strokes inside groups may need ungrouping first, and if the
output still has strokes the installed version needs its GUI for that action: use picosvg. Verify by
rendering the stroked and outlined files at 512 px: `masktool diff` MAE near 0.

## 6. Fill rules

| `fill-rule` | Inside when | Holes |
|---|---|---|
| `nonzero` (default) | winding number is not 0 | only where the inner subpath winds opposite to the outer |
| `evenodd` | a ray crosses an odd number of edges | every nested subpath, whatever its direction; overlaps of one shape also turn into holes |

Verified with resvg: a ring drawn as two same-direction circles fills its hole under `nonzero`;
reversing the inner circle (flip its sweep flags, or reverse a polygon's point order) or switching
to `evenodd` opens it. Prefer opposite winding with `nonzero` for counters in letters, rings and
cutouts: it also survives pipelines that only know nonzero (TrueType outlines, many icon-font and
CNC converters). Reach for `evenodd` only for single-path artwork without overlaps.

## 7. Reuse: defs, symbols, sprites and ids

- `<defs>` holds gradients, clip paths, masks and symbols; nothing in it renders by itself.
- `<symbol id="ic-x" viewBox="0 0 24 24">` + `<use href="#ic-x" x y width height>`: width and
  height only work on a `symbol` or `svg` target; the symbol keeps its own aspect ratio (`meet`).
- Attributes on the referenced element win over the `<use>` element's: leave `fill`/`stroke` unset
  in the symbol (or `currentColor`) so each `<use>` can set them. Inherited properties (`color`,
  `fill`, custom properties) flow into the clone; page selectors do not reach inside it.
- External sprites (`href="/icons.svg#ic-x"`) work same-origin only; there is no CORS opt-in for
  `<use>`, and `data:` URIs in `href` are deprecated.
- `href` (SVG 2) works in every current browser (Safari since 12.1, iOS 12.2); add
  `xlink:href` (with `xmlns:xlink` declared) only for a legacy tool that needs it; if both are
  present, `href` wins.
- Inlined SVGs share one id space: two icons with `id="g"` make `url(#g)` resolve to whichever came
  first. Name ids `<file-prefix>-<role>` while writing (`ic-upload-grad`), or run
  `python3 -I "$SVG" prefix-ids in.svg out.svg --prefix ic-upload`; it rewrites `id`, `url(#...)`,
  `href="#..."` and `#id` selectors in `<style>`, but not `aria-labelledby`/`aria-describedby`
  (verified): fix those by hand.
- Sprite builder (stdlib) and markup: [recipes](references/paint-reuse-recipes.md) section 3.

## 8. Paint: gradients, patterns, clips, masks, filters

| Choice | Use | Watch out |
|---|---|---|
| `gradientUnits="objectBoundingBox"` (default) | gradient follows each shape's bbox (0..1) | horizontal or vertical lines have a zero-height bbox: the gradient is ignored (verified: nothing painted) |
| `gradientUnits="userSpaceOnUse"` | one gradient across several shapes; strokes on straight lines | coordinates are absolute; move the gradient with the art |
| `pattern` | hatching, dots, textures | `patternUnits` defaults to bbox fractions; set `userSpaceOnUse` for fixed tiles; rotate with `patternTransform` |
| `clipPath` | hard-edged crops (frames, rounded corners) | geometry only, paint ignored; cheap |
| `mask` | soft fades, partial transparency | luminance by default (`mask-type="alpha"` for alpha); region -10%/120% of the bbox crops anything larger |
| `filter` (blur, drop shadow) | rarely, on illustrations | full raster pass at every size; default region -10%/120% clips wide blurs; PDF and print pipelines drop or rasterise filters, masks and blend modes |

Gradient stops: `offset` 0..1 ascending, `stop-color`, `stop-opacity`. Every gradient, clip, mask
and filter id carries the file prefix. Defaults and examples: [recipes](references/paint-reuse-recipes.md) section 1-2.

## 9. Theming

| Technique | Works in | Notes |
|---|---|---|
| `fill`/`stroke="currentColor"` | inline SVG, `<use>` clones | follows CSS `color`; renders black in `<img>`, backgrounds and previews (expected) |
| CSS custom property `style="fill:var(--icon-accent,#e11d48)"` | inline SVG in browsers | always give a fallback; resvg (`svg_render`) painted `var()` black in a test, so assume non-browser tools do not resolve it |
| `<style>` with `@media (prefers-color-scheme: dark)` | standalone files, favicons | the media query travels inside the file |

Two-tone icons: primary `currentColor`, accent through a custom property. Files that also go through
`svg_render`, `export_pdf` or a design tool keep literal colours. Favicon: an SVG with an internal
dark-mode rule, plus `favicon.ico` and a 180x180 `apple-touch-icon.png` (SVG favicons: Chrome and
Edge 80+, Firefox 41+, Safari 26+). Full markup in the recipes, section 4.

## 10. Animation

- CSS transforms on SVG elements default to `transform-box: view-box` (origin at the viewBox origin):
  set `transform-box: fill-box; transform-origin: center` to spin or scale an element about itself.
- Line drawing: `pathLength="1"` on the element and keyframes from
  `stroke-dasharray: 1; stroke-dashoffset: 1` to `stroke-dashoffset: 0`. Keep the dash properties
  inside the keyframes so the static state (renderers, reduced motion, end of the run) is the full
  stroke; resvg ignores `pathLength` for dashes.
- SMIL (`animate`, `animateTransform`, `animateMotion`, `set`) runs in current engines, including
  inside `<img>`, but has no reduced-motion hook: prefer CSS when motion must be optional. Never
  animate `href` (svgcheck error).
- Always ship `@media (prefers-reduced-motion: reduce) { ... animation: none }` inside the file's
  `<style>`. Animate `transform` and `opacity` only; prefix keyframe names like ids.

## 11. Embedding and safety

| Method | Scripts run | Page CSS, `currentColor` | Accessible name | Use for |
|---|---|---|---|---|
| inline `<svg>` | yes, if present | yes | `role="img"` + `<title>` | UI icons, themed or animated art |
| `<img src>` | never | no | `alt` on the `<img>` | illustrations, logos, anything untrusted |
| CSS `background-image` | never | no | none (decorative only) | textures, ornaments |
| `<use href="sprite.svg#id">` | no | inherited properties only | on the outer `<svg>` | icon systems (same origin) |

- Meaningful standalone image: root `role="img" aria-labelledby="<prefix>-title"`, first child
  `<title id="<prefix>-title">`; decorative or next to visible text: `aria-hidden="true"` and no
  title; icon-only buttons put `aria-label` on the `<button>` and hide the SVG.
- Sanitize every SVG you did not write: `python3 -I "$SVG" sanitize in.svg out.svg` removes
  `<script>`, `<foreignObject>`, `<metadata>`, editor namespaces, `on*` attributes, external and
  `javascript:` hrefs and `<animate>`/`<set>` on `href`; files with `<!ENTITY` are refused. It keeps
  `<style>` blocks: an `@import` or `url(http...)` inside one still fails `check` (verified); delete
  that rule by hand. Never inline user uploads unsanitised.
- Validate: `python3 -I "$SVG" check f.svg --budget icon|logo|illustration` (exit 1 on ERROR;
  warnings above 4 KB / 40 paths / 2 decimals for icons, 20 KB / 150 / 3 for logos, 150 KB / 2,500 / 3
  for illustrations). Then render at the largest use (512) and the smallest (16-32), Read both, or put
  them on one sheet: `"$PY" "$IMG" sheet sheet.png big.png small.png`.

## 12. Worked example

**A. 24-grid `cloud-upload` icon, hand-written with arcs.** Live area 2-22, stroke 2, round caps
and joins, `currentColor`. Cloud = three lobes: left L (6.5,14) r 3.5, big B (10,10) r 6, right R
(17,13.5) r 4, open at the bottom for the arrow. `cross 6.5 14 3.5 10 10 6` and
`cross 10 10 6 17 13.5 4` give the upper crossings L-B (4.16,11.39) and B-R (15.99,9.63) with their
angles on each circle:

| Arc | From | To | Span | Flags |
|---|---|---|---|---|
| left lobe, start at 110 degrees (5.3,17.29) | 110 | 228.1 | 118.1 | large 0, sweep 1 |
| big lobe | 166.6 | 356.5 | 189.9 | large 1, sweep 1 |
| right lobe, end at 70 degrees (18.37,17.26) | 255.4 | 430 | 174.6 | large 0, sweep 1 |

```bash
python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import svggeom as g
L, B, R = ((6.5, 14), 3.5), ((10, 10), 6), ((17, 13.5), 4)
lb = min(g.circle_intersections(L[0], L[1], B[0], B[1]), key=lambda p: p[1])   # upper crossing
br = min(g.circle_intersections(B[0], B[1], R[0], R[1]), key=lambda p: p[1])
print("M" + g.pt(*g.on_circle(*L[0], L[1], 110)) + g.arc_to(*L[0], L[1], 110, g.angle_of(L[0], lb))
      + g.arc_to(*B[0], B[1], g.angle_of(B[0], lb), g.angle_of(B[0], br))
      + g.arc_to(*R[0], R[1], g.angle_of(R[0], br), 430))' "$(dirname "$GEO")"
# M5.3 17.29A3.5 3.5 0 0 1 4.16 11.39A6 6 0 1 1 15.99 9.63A4 4 0 0 1 18.37 17.26
```

Arrow: shaft on x = 12 (even stroke on an integer: crisp at 24 px), 45-degree head of 3.5 units. The
head ends sit 1 unit inside the lobe circles but off the drawn arcs, so nothing touches.

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
     role="img" aria-labelledby="ic-cloud-upload-title">
  <title id="ic-cloud-upload-title">Upload to cloud</title>
  <path d="M5.3 17.29A3.5 3.5 0 0 1 4.16 11.39A6 6 0 1 1 15.99 9.63A4 4 0 0 1 18.37 17.26"/>
  <path d="M12 21V12M8.5 15.5 12 12l3.5 3.5"/>
</svg>
```

`check cloud-upload.svg --budget icon` → `ok, 2 paths, 0 colors, 427 bytes, max 2 decimals`. Renders
at 512 and 32 px (white background, since `currentColor` renders black): at 32 px the 2.67 px stroke
holds, the gap between arrowhead and lobes stays open, the open bottom still reads as a cloud.

**B. Layered spot illustration with symbols and one gradient** (160x100, ids prefixed `spot-`):

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 100" role="img" aria-labelledby="spot-title">
  <title id="spot-title">Sun over green hills with three pine trees</title>
  <defs>
    <linearGradient id="spot-sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#9fd3ff"/><stop offset="1" stop-color="#eaf6ff"/>
    </linearGradient>
    <clipPath id="spot-frame"><rect width="160" height="100" rx="12"/></clipPath>
    <symbol id="spot-tree" viewBox="0 0 20 32">
      <path d="M9 22h2v10H9z" fill="#7a5230"/>
      <path d="M10 0 20 24H0z" fill="#2f7d4f"/>
    </symbol>
  </defs>
  <g clip-path="url(#spot-frame)">
    <g id="spot-layer-sky"><rect width="160" height="100" fill="url(#spot-sky)"/></g>
    <g id="spot-layer-sun"><circle cx="122" cy="30" r="12" fill="#ffc542"/></g>
    <g id="spot-layer-hills">
      <path d="M0 76C30 58 60 60 90 72S140 70 160 62V100H0z" fill="#8fd18a"/>
      <path d="M0 88C40 76 80 80 160 86V100H0z" fill="#5fb565"/>
    </g>
    <g id="spot-layer-trees">
      <use href="#spot-tree" x="22" y="50" width="15" height="24"/>
      <use href="#spot-tree" x="38" y="42" width="20" height="32"/>
      <use href="#spot-tree" x="104" y="55" width="12.5" height="20"/>
    </g>
  </g>
</svg>
```

Layers are top-level groups in back-to-front order; the `S` command continues the first hill curve
smoothly; each `<use>` keeps the tree's 20:32 ratio. `check --budget illustration` → `ok, 4 paths,
7 colors, 1257 bytes, max 1 decimals`. The 32 px render keeps sky, sun, both hills and three crowns;
the trunks (1.25-2 units, 0.25-0.4 px at that size) vanish, acceptable for decoration; at the 160 px
use they are 1-2 px. For an Inkscape or Illustrator hand-off, add `inkscape:groupmode="layer"`
labels (vector-art layer conventions); `check` then warns about editor metadata, as expected.

## Pitfalls

- An arc from a point to itself draws nothing; full circles need two half arcs.
- Wrong arc direction: flip sweep (side) or large-arc (short or long way), not the coordinates.
- `nonzero` with same-direction subpaths fills holes; `evenodd` turns accidental overlaps into holes.
- A gradient in bbox units on a straight line paints nothing: use `userSpaceOnUse`.
- A `transform` on a stroked group scales its strokes; scale the geometry or the viewBox instead.
- Fill or stroke set inside a `<symbol>` cannot be overridden from `<use>`.
- Hiding a sprite with `display:none` can break gradients, clips and masks inside it; use
  `width="0" height="0"` and absolute positioning.
- `prefix-ids` leaves `aria-labelledby` pointing at the old id; `sanitize` leaves `@import` in
  `<style>`; both verified, both fixed by hand.
- `xlink:href` without `xmlns:xlink` on the root is not well-formed XML; prefer plain `href`.
- `<text>` depends on installed fonts: outline it for logos, keep live text outside icons.
- `svg_render` (resvg) ignores `vector-effect`, CSS `var()` and dash `pathLength`, and runs no
  animation: check those in a browser before delivery.
- Optimisers: never let one drop the `viewBox`; render-check after any precision below 2.

Related: `icon-system-design`, `logo-design-process`, `oklch-palette-ramps`,
`visual-accessibility-audit`, `design-tokens-dtcg`, hub `vector-art` (pack hub `graphic-design`).
