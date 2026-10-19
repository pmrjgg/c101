---
name: icon-system-design
description: "Icon system design: canvas, live area and keyline shapes, stroke/cap/corner rules, pixel snapping at 16/20/24, size variants, metaphor choice and recognition tests, outline vs filled sets and states, production with vector-artist and svgcheck, naming and metadata, sprite/React/Iconify delivery, accessibility, and a measured consistency audit (ink coverage, bounds, style). Load when designing, extending or auditing an icon set."
when_to_use: "Drawing or generating UI icons, a 24 px or 16 px icon that looks blurry or heavier than its neighbours, extending an existing set (Lucide-style, Material-style), choosing a metaphor, exporting an SVG sprite or React icon components, icon-only buttons, or reviewing an icon set for consistency."
---

# Icon system design

An icon set is done when every icon follows one written spec (grid, stroke, caps, radii,
keylines), renders crisp at its primary size, passes a measured audit against its peers, is
recognisable without a label (or ships with one), and is delivered as clean `currentColor` SVGs
with names, tags and a version.

Audit script: [icon_audit.py](scripts/icon_audit.py) (Pillow + resvg, stack venv). Deep
material: [metaphor conventions](references/metaphors.md) | [delivery formats](references/delivery.md).

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
PY="$STACK/.venv/bin/python"; [ -x "$PY" ] || PY=.venv/bin/python
AUD="$STACK/.claude/skills/icon-system-design/scripts/icon_audit.py"
SVG="$STACK/.claude/skills/vector-art/scripts/svgcheck.py"
"$PY" -I "$AUD" new/*.svg --ref set/home.svg set/square.svg --sheet sheet.png   # MASS/BOUNDS/STYLE
python3 -I "$SVG" check new/*.svg --budget icon     # icon budget: 4000 bytes, 40 paths, 2 decimals
```

## 1. Spec sheet (write it before the first icon)

| Parameter | Default | Notes |
|---|---|---|
| Canvas | 24 x 24 px, `viewBox="0 0 24 24"` | the unit is the CSS pixel at 1x |
| Padding / live area | 2 px / 20 x 20 | extending a set: its rule wins (Lucide: >= 1 px) |
| Stroke | 1.5 or 2 px, centred, one value for the set | 2 px reads at 1x; 1.5 px only for 2x-first products (section 3) |
| Caps and joins | round or square, chosen once | round feels friendly, square technical; never mix |
| Corner radius | one outer radius, e.g. 2 px (1 px on shapes < 8 px) | inner radius follows from stroke |
| Gaps | >= 2 px between distinct elements | smaller gaps fill in at 16 px |
| Fills | none (outline set) or solid (filled set); 1-2 px dots allowed | |
| Colour | `stroke="currentColor"` / `fill="currentColor"` | icons inherit text colour |

Keylines (equal optical size, not equal bounding boxes):

| Shape | Keyline | Why |
|---|---|---|
| Circle | 20 px diameter (r = 9 at a 2 px stroke) | round shapes look smaller than squares of the same width |
| Square | 18 x 18 (rect 16 + stroke) | |
| Portrait rectangle | 16 x 20 | phones, documents |
| Landscape rectangle | 20 x 16 | screens, mail, cards |

Template (hide in exports; keep in the source file):

```svg
<g id="keylines" fill="none" stroke="#FF00FF" stroke-width="0.1" opacity="0.5">
  <rect x="2" y="2" width="20" height="20"/><circle cx="12" cy="12" r="10"/>
  <rect x="3" y="3" width="18" height="18"/><rect x="4" y="2" width="16" height="20"/>
  <rect x="2" y="4" width="20" height="16"/></g>
```

## 2. Size variants: redraw, do not only scale

| Size | Padding / live area | Stroke | What changes |
|---|---|---|---|
| 16 px | 1 px / 14 x 14 | 1.5 px (2x-first) or 1 px on .5 coordinates (crisp at 1x) | drop interior detail, merge small parts, open gaps to >= 2 px |
| 20 px | 2 px / 16 x 16 | 1.5 or 2 px | redraw from 24 when strokes land off-grid |
| 24 px | 2 px / 20 x 20 | 2 px | master |
| 32 px | 2-3 px | 2.5 or 3 px (3 px crisp on .5) | can add one level of detail |

Matching rule: keep stroke / canvas near 1/12 (2 px at 24) and pick the nearest pixel-fit width;
a 24 px icon scaled to 16 px has a 1.33 px stroke, which is never crisp (see the 16 px column of
any audit sheet). Ship 16 px variants for dense UI rather than letting the browser scale.

## 3. Pixel snapping

A stroke is centred on its path: width w at coordinate c covers c - w/2 .. c + w/2.

| Stroke | Put horizontal/vertical centres on | 1x render (resvg, measured coverage per pixel row) |
|---|---|---|
| 1 px | .5 (12.5) | one full row; on 12 two rows at 50% (blurred) |
| 2 px | integers (12) | two full rows; on 12.5 a 50/100/50 smear |
| 3 px | .5 | three full rows |
| 1.5 px | none at 1x: at 12 two rows at 75%, at 12.25 one row 50% + one full | at 2x (3 device px) centres on .25/.75 render three full rows |

Rules: odd widths on half pixels, even widths on integers; boxes drawn with strokes have their
edges on the same rule (`<rect x="4" y="4" width="16" height="16">` with a 2 px stroke). Curves
and diagonals always anti-alias; keep their endpoints on the grid. Verify at 1x, not zoomed in a
vector editor: `mcp__image__svg_render {svg_path, width: 24}` (or `svg_render` at 16), then Read
the PNG; the audit sheet (section 11) magnifies 1x renders with nearest-neighbour so grey half
rows are visible. Locally: `rsvg-convert -w 24 in.svg -o out.png` or `resvg -w 24 in.svg out.png`
when installed.

## 4. Construction rules

| Rule | Detail |
|---|---|
| Angles | 0/45/90 only (30/60 for isometric sets); a 45-degree line looks right at small sizes, a 37-degree one jags |
| Terminals | all round or all flat, matching the cap choice |
| Perspective | front-on, flat; no 3/4 views in a front-on set |
| Open vs closed | decide whether shapes close (a closed bag vs an open cup) and keep it |
| Corners | one outer radius; inner radius = outer - stroke (or 0) |
| Visual mass | measured: ink coverage of a 4x render vs peers (below) |

Visual mass: `coverage` = mean alpha of a 4x render (0..1, ink share of the canvas). Compare an
icon with the median of its peer group, flag beyond about +/-10%: the base icon for variants, or
2-4 existing icons of the same structure (containers vs containers, round vs round). Whole-set
coverage is not a gate: in a 2 px outline set it spans about 0.10 (plus) to 0.29 (archive,
mail). Open glyphs (plus, minus, chevrons, arrows) are judged by eye. A heavy icon is simplified
(drop an interior stroke, shrink an inner part), never thinned below the set stroke.

## 5. Metaphors and recognition

Conventional beats clever: magnifier = search, gear = settings, trash can = delete, X = close,
pencil = edit, plus = add, bell = notifications, house = home, three lines = menu, funnel =
filter, padlock = security, chain = link, paperclip = attach. Platform conventions differ for
share (iOS box with up arrow; Material connected nodes) and more (horizontal vs vertical dots).
Full table and things to avoid: [metaphors](references/metaphors.md).

- Avoid culture-specific gestures (thumbs-up, OK hand), national objects (a US mailbox for mail),
  religious symbols, and text glyphs (a letter "A" for fonts, "$" for prices) that break in
  translation.
- 5-second test: show each icon at 24 px with labels hidden for 5 seconds, ask what it does;
  aim for 4 of 5 testers naming the intended action. Failures get a different metaphor or a
  visible label.
- Ambiguous actions (archive vs save vs bookmark, sync vs refresh) always ship icon + label.

## 6. Outline, filled, duotone

Separate sets with the same metaphors and keylines, never mixed within one view. State mapping:
outline = default, filled = active or selected (tab bars, toggles), duotone = illustrative or
marketing only. Filled variants keep outer dimensions identical so state changes do not shift
layout; counters and gaps of the outline become knock-outs of at least 2 px.

## 7. Production pipeline

1. Spec sheet (section 1) and keyline template.
2. Anchor icon: draw or generate one representative icon (e.g. settings), review it, then freeze
   its style sentence and reuse it verbatim in every brief: "24 px canvas, 2 px centred stroke,
   round caps and joins, 2 px outer radius, content inside 2-22, no fills, front-on".
3. Production: hand-write simple glyphs (<= ~20 primitives: chevrons, plus, check, arrows) with
   Write; brief `vector-artist` for complex ones, one agent per icon fanned out when the set has
   more than 8 icons (the `fanout` skill, or the visual-iterate workflow for a quality bar).
4. Normalise generated SVGs: `python3 -I "$SVG" fit in.svg out.svg --size 24 --pad 2` scales the
   old viewBox into 0 0 24 24 inside a wrapper `transform`, which also scales stroke-width (a
   100-unit drawing with stroke 8 becomes 1.6 px). Re-express coordinates in 24 units
   (x' = tx + s * x), set the spec stroke, snap to the grid, drop the transform.
5. `python3 -I "$SVG" currentcolor out.svg out-cc.svg` (every solid paint to currentColor).
6. `python3 -I "$SVG" check out-cc.svg --budget icon`, then the audit (section 11).

Prompt skeleton for `mcp__image__vector_generate` (one icon per call):
`Flat UI icon of <subject>, single-weight 2 px outline, round caps and joins, 2 px corner radius,
front-on, built from simple geometric primitives on a 24 px grid, no fills, no text, no
gradients, one colour #000000, centred with even padding.`

## 8. Naming and metadata

- File names: kebab-case `<name>[-<variant>][-<size>].svg`: `trash.svg`, `trash-filled.svg`,
  `trash-16.svg`. Name what it depicts; put meanings in tags.
- Metadata (one JSON for the set):

```json
{ "name": "trash", "variants": ["outline", "filled"], "sizes": [16, 24],
  "tags": ["delete", "remove", "bin", "discard"], "category": "actions", "since": "1.4.0" }
```

- Semver for the set: MAJOR = rename, removal, or a grid/stroke change; MINOR = new icons or
  variants; PATCH = path fixes that keep the look. Deprecate (keep plus alias) before removing.

## 9. Delivery

| Format | Use | Notes |
|---|---|---|
| Individual SVGs | design tools, CMS | `viewBox`, no width/height or 24, `currentColor`, no ids, no transforms, no raster |
| Symbol sprite | web without a framework | `<symbol id="i-trash" viewBox="0 0 24 24">`, used as `<svg class="icon"><use href="#i-trash"/></svg>`; external sprite files work same-origin only |
| React components | apps | `npx @svgr/cli --icon --typescript --out-dir src/icons -- icons/` (`--icon` sets 1em sizing; add `--replace-attr-values '#000=currentColor'` if needed) |
| Iconify JSON | icon pickers, multi-framework | `{prefix, width: 24, height: 24, icons: {name: {body}}, aliases}` |
| Icon font | avoid | screen readers read private-use glyphs or nothing, hinting distorts shapes, font loading causes invisible icons and layout shift, one colour only, user font overrides break it |

Sprite and component details: [delivery formats](references/delivery.md).

## 10. Accessibility

| Case | Markup |
|---|---|
| Decorative (next to a visible label) | `<svg aria-hidden="true">` |
| Icon-only button | label on the control: `<button aria-label="Delete"><svg aria-hidden="true">...</svg></button>` |
| Meaningful standalone image | `<svg role="img" aria-label="Warning">` or `<title>` referenced by `aria-labelledby` |
| Status icons | never colour-only: shape differs per state (check, exclamation, cross) plus text |

Contrast: icons that convey meaning need 3:1 against adjacent colours (WCAG 1.4.11). Target size:
the hit area is at least 24 x 24 CSS px (WCAG 2.5.8 AA) even when the glyph is 16 px (pad the
button; Apple HIG asks 44 x 44 pt, Material 48 x 48 dp). Tooltips do not replace labels.

## 11. Consistency audit and worked example

Checklist on the contact sheet (24 px and 16 px, 1x pixels magnified): stroke weight identical,
caps and joins identical, radii from the spec, visual mass within the peer band, front-on
perspective, optical size matches the keylines, content inside the live area, 16 px variants
legible, gaps >= 2 px, nothing blurry at 1x.

Worked example: extend an open 24 px / 2 px round-stroke outline set (Lucide-style rules: 24
canvas, >= 1 px padding, 2 px centred stroke, round caps and joins, radius 2 on shapes >= 8 px
and 1 below, 2 px between elements) with tag, archive and bookmark.

1. Measure the existing 8 icons: `"$PY" -I "$AUD" set/*.svg` gives median coverage 0.1929 and
   flags plus (-47.6%), mail (+43.5%), home, search and user: the whole-set band is useless, so
   peers are chosen per new icon.
2. Draw the three icons by hand on the grid (all coordinates integer or .5 on curves):

```svg
<!-- tag --><path d="M3 4v7.6a1 1 0 0 0 .3.7l8.4 8.4a1 1 0 0 0 1.4 0l7.6-7.6a1 1 0 0 0 0-1.4L12.3 3.3a1 1 0 0 0-.7-.3H4a1 1 0 0 0-1 1z"/><circle cx="7.5" cy="7.5" r="1"/>
<!-- bookmark --><path d="M6 5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v15l-6-4-6 4z"/>
<!-- archive v1 --><rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4"/>
```

   Each inside `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"
   fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">`.
3. Audit against peers:

```text
$ "$PY" -I "$AUD" new/tag.svg new/bookmark.svg --ref set/home.svg set/square.svg
median 0.2205 (ref); band +/-10%
tag.svg       cov 0.2145   -2.7%  bbox (2, 2, 22, 22)  ok
bookmark.svg  cov 0.2010   -8.8%  bbox (5, 2, 19, 21)  ok
$ "$PY" -I "$AUD" new/archive.svg --ref set/mail.svg set/square.svg
median 0.2434 (ref); band +/-10%
archive.svg   cov 0.2875  +18.1%  bbox (2, 3, 22, 21)  MASS
```

4. Fix archive: lid narrowed to 16 px, body to 14 px with the set's 2 px radius at the bottom
   (`<rect x="4" y="5" width="16" height="4" rx="1"/><path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0
   2-2V9M10 13h4"/>`): coverage 0.2640, +8.5%, ok. All three pass `svgcheck check --budget icon`
   (247-346 bytes, 0 colours, <= 1 decimal).
5. Read `sheet.png`: 24 px renders crisp on straight edges; at 16 px the scaled strokes blur, so
   16 px variants are redrawn for the dense table view only.
6. Ship: SVGs, sprite symbols, SVGR components, metadata with tags (`tag`: label, price, category;
   `archive`: store, box; `bookmark`: save, later), set version 1.3.0 -> 1.4.0 (MINOR).

## Pitfalls

- Scaling a 24 px master to 16 px and calling it a variant (1.33 px blurred strokes).
- 1.5 px strokes in a product that renders mostly at 1x.
- Mixing outline and filled icons, or round and square caps, in one view.
- Equal bounding boxes instead of keylines (circles look small, squares heavy).
- Detail below the 2 px gap rule; text or letters inside icons.
- Clever metaphors without a recognition test; colour as the only state signal.
- Generated SVGs left with wrapper transforms, scaled strokes, hard-coded colours or ids.
- Icon fonts; sprites loaded cross-origin; meaningful icons without an accessible name.
- Raw whole-set ink coverage used as a pass/fail gate.

Related: `vector-art`, `svg-hand-authoring`, `visual-review`, `logo-design-process`,
`brand-guidelines-system`, `visual-accessibility-audit`, `design-tokens-dtcg`, hub `graphic-design`.
