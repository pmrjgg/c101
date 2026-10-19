---
name: logo-design-process
description: "Logo design from brief to vector master kit: discovery worksheet and competitor map, mark-type choice, exploration funnel (thumbnails, vector_generate sketches), construction geometry on a 96- or 1000-unit grid, optical corrections, wordmarks from licensed fonts, a measured small-size and monochrome test ladder, distinctiveness checks, lockups and clear space, and the export kit (SVG, PDF, PNG, favicons, app icons). Load when creating, refining or auditing a logo, monogram or wordmark."
when_to_use: "A new logo, symbol, monogram or wordmark; refining or vectorising an existing mark; a logo that fills in or blurs at favicon size; building favicon.ico, apple-touch-icon or maskable PWA icons; defining lockups, clear space and minimum sizes; checking a mark for lookalikes."
---

# Logo design process

A logo is done when one vector master, built on a declared grid, survives every size and medium
it will meet (16 px favicon to signage, one colour, reversed, embroidered, engraved), has been
checked for lookalikes (reported as an Open doubt, never as legal clearance), and ships as a
named kit with lockups, clear space, minimum sizes and usage rules.

Scripts (Pillow + resvg, stack venv): [logo_ladder.py](scripts/logo_ladder.py) (size ladder and
counter measurement), [logo_kit.py](scripts/logo_kit.py) (raster kit: PNG, favicon.ico, touch and
PWA icons). Deep material: [discovery and clearance](references/discovery-and-clearance.md) |
[export kit](references/export-kit.md).

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
PY="$STACK/.venv/bin/python"; [ -x "$PY" ] || PY=.venv/bin/python
L="$STACK/.claude/skills/logo-design-process/scripts"
SVG="$STACK/.claude/skills/vector-art/scripts/svgcheck.py"
"$PY" -I "$L/logo_ladder.py" mark.svg --counter 34,18,48,30 --sizes 16,24,32,64,256 --sheet ladder.png
"$PY" -I "$L/logo_kit.py" mark.svg --name acme-mark --out kit --bg '#1A1A2E' --fg-on-bg mark-reversed.svg
python3 -I "$SVG" check mark.svg --budget logo      # logo budget: 20 KB, 150 paths, 3 decimals
```

## 1. Discovery

Worksheet (fill before drawing; missing answers become Open doubts):

| Field | Example |
|---|---|
| Three brand attributes (adjectives that must be visible) | precise, warm, durable |
| Name meaning and length | "Brackenby": invented, 9 letters, no initials collision |
| Audience and category | outdoor-gear repair shops, B2B |
| Usage contexts, smallest first | 16 px favicon, 1024 px app icon, shop signage at 10 m, embroidered cap (20 mm), laser-engraved tool (8 mm) |
| Colour constraints | must work in one colour; brand palette not yet fixed |
| Must avoid | mountains and pine trees (every competitor uses them) |
| Decision-maker and taste references | founder; likes Swiss geometric marks |

Competitor audit: collect 8-12 marks from the category (screenshots, not generated look-alikes),
plot each on two axes, geometric <-> organic and literal <-> abstract, and look for the empty
quadrant. Seven of ten outdoor-repair brands sat in "organic + literal" (mountains, trees) and
none in "geometric + abstract": that quadrant is the unclaimed territory. Template and plotting code: [discovery and
clearance](references/discovery-and-clearance.md).

## 2. Mark type

| Type | Choose when | Watch out |
|---|---|---|
| Wordmark | short or distinctive name (<= ~10 letters), recognition built through the name | small sizes need a separate mark or monogram |
| Lettermark / monogram | long name with strong initials; favicon and app icon matter | initials are hard to protect; needs a distinctive construction |
| Pictorial | a concrete, ownable object exists that is not the category cliche | literal objects age and limit expansion |
| Abstract | global brand, new category, budget to build recognition | meaningless until repeated; must be legally distinctive |
| Emblem | heritage, institutions, badges and patches | fails small: plan a simplified mark |
| Combination | most new brands: symbol + wordmark lockups, each usable alone later | define which part survives alone |
| Mascot | consumer, playful, character-driven communication | costly to keep consistent; needs a simplified icon |

Decision: recognition budget (how often will people see it?), smallest size, name length,
scalability across media, and distinctiveness (initials and common objects are crowded).

## 3. Exploration funnel

1. 20-40 thumbnails: one-line descriptions or black-only sketches ("B from two stacked bowls
   sharing a stem, 0/90 geometry"). Diverge on concept, not on colour.
2. Optional generated sketches (black only, explorations, never deliverables) with
   `mcp__image__vector_generate`, `n` 2-4, one concept per call:
   `Flat one-colour logo mark of <concept>, geometric construction from circles and rectangles,
   solid black #000000 on white, no gradients, no shadows, no text, no outlines, bold simple
   silhouette that stays readable at 16 px, centred with even padding.`
3. Narrow to 3-5 directions: score each against the three attributes, the smallest context and
   distinctiveness (competitor map). Write one rationale sentence per direction.
4. Refine 1-2 directions by hand as vector masters (section 4). Raster-generated logos are never
   deliverables; a generated SVG is a sketch to redraw, because its geometry is not on a grid,
   carries hundreds of nodes and cannot be defended.

## 4. Construction rules

| Rule | Detail |
|---|---|
| Grid | integer coordinates on a 96-unit grid (96/16 = 6 units per pixel at 16 px, 4 at 24, 3 at 32, 2 at 48) or 1000 units (matches a 1000-UPM font for wordmarks; no pixel alignment) |
| Angles | 0/45/90 (add 30/60 only as a deliberate system) |
| Vocabulary | one stroke weight family (stem, thinner horizontals), one corner-radius value, one terminal style |
| Node economy | nodes at curve extrema only; no stacked or redundant nodes; arcs as arcs |
| Paths | closed; overlapping shapes united (flattened booleans) so even-odd fills cannot punch seams |
| Small details | nothing thinner or smaller than 1/32 of the mark height (2.5 units at 80 tall) |
| Presentation grids | golden-ratio circles may illustrate the construction in a deck; they are not a requirement and do not make a mark better |

## 5. Optical corrections

| Correction | Amount | Why |
|---|---|---|
| Overshoot | round and pointed forms extend 1-3% beyond the flat baseline/cap line | equal geometric height looks short |
| Horizontal vs vertical | horizontals about 5-10% thinner than verticals | equal weights make horizontals look heavier |
| Ink traps, open counters | notches where strokes meet; counters >= 1 px at the smallest size | junctions fill in small and in print |
| Optical centre | place the mass slightly above geometric centre; centre triangles by area, not bounding box | the eye reads the geometric centre as low |
| Optical kerning | equalise the areas between letters, not the distances | round-round pairs need less space than straight-straight |

## 6. Wordmark from a real typeface

1. Licence first: OFL fonts allow logo use (OFL FAQ 1.1; the artwork is not bound by the OFL);
   commercial EULAs may exclude logos or charge for them: search the EULA for "logo",
   "trademark", "wordmark". Record the licence in the kit.
2. Set the name, choose weight and case, then outline (Illustrator Create Outlines, Inkscape
   Object to Path, or fontTools):

```python
# uv run --no-project --with fonttools python -I wordmark.py Font.ttf Brackenby
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
f = TTFont(sys.argv[1]); gs = f.getGlyphSet(); cmap = f.getBestCmap(); x = 0; d = []
for ch in sys.argv[2]:
    g = gs[cmap[ord(ch)]]; pen = SVGPathPen(gs)
    g.draw(TransformPen(pen, (1, 0, 0, -1, x, 0)))      # flip y; advance by width
    d.append(pen.getCommands()); x += g.width
print('<path d="%s"/>' % " ".join(d))                    # no kerning applied: kern by hand next
```

3. Kern by eye at display size and again at the smallest size; write pairs down (for example
   "r-a -12 units, k-e -8").
4. Adjust letterforms that clash with the mark (terminals, dots, a tail), keeping the type's
   stroke logic. Never ship generated lettering: models mis-space and malform letters.

## 7. Test ladder

| Test | Pass |
|---|---|
| Render 16, 24, 32, 64, 256 px (`logo_ladder.py`, magnified sheet) | every counter open (min alpha <= 0.25), no stroke below 1 px at 16 px |
| 10 mm print | at 300 ppi 10 mm = 118 px; thinnest positive feature >= 0.1 mm, reversed features thicker (press ink spread) |
| Black first | the mark works as one solid colour before any colour is added |
| Reversed and one colour | white on the darkest brand colour and on black; one spot colour |
| Over a photo | legible on a busy image with a plate or scrim, not by luck |
| Blur / squint | Gaussian blur radius about 4 px at 256 px: silhouette still identifiable |
| Favicon and app icon crops | 16/32 px square crop, 180 px touch icon, 512 px maskable inside the 80% circle |
| Embroidery | lines and gaps >= about 1 mm at the stitched size; no hairlines; confirm with the vendor |
| Laser engraving | lines >= about 0.3 mm; check the vendor's minimum kerf and spacing |

## 8. Distinctiveness sanity check

1. Reverse image search the final mark and the closest directions: Google Lens and TinEye.
2. Trademark databases: USPTO Trademark Search (replaced TESS in November 2023; search figurative
   marks with design search codes), EUIPO eSearch plus and TMview (image search for participating
   offices), WIPO Global Brand Database (image search across national and Madrid records).
3. Record what was searched, classes (Nice classes of the client's goods and services), hits that
   look close, and screenshots.
4. Report as an Open doubt, never as clearance:
   `- [legal|high] Lookalike search found no close match in USPTO, TMview and WIPO GBD image
   search for Nice classes 35 and 37 (2026-10-19) - this is not legal clearance - resolve: trademark
   counsel searches and files before launch - route: user`

## 9. Lockups and rules

| Element | Rule |
|---|---|
| Lockups | horizontal (mark left of wordmark), stacked (mark above), mark-only, wordmark-only; fixed spacing and size ratio inside each |
| Clear space | unit from the mark: e.g. x = stem width or 1/4 of mark height; keep 1x on all sides, measured from the outermost ink |
| Minimum size | per lockup in px and mm, set where the ladder last passes (e.g. mark-only 16 px / 6 mm; horizontal 96 px / 25 mm wide) |
| Colourways | full colour, one colour, reversed (white), grayscale; each as its own file |
| Backgrounds | approved list with measured contrast of the mark against each (>= 3:1 non-text) |

## 10. Export kit

| File | Spec |
|---|---|
| `<brand>-<lockup>-<colourway>.svg` | master; `svgcheck check --budget logo` exits 0; ids prefixed; no raster, no text elements |
| `<brand>-<lockup>-<colourway>.pdf` | vector PDF via `mcp__image__export_pdf {svg_path, page_size: "auto"}` |
| `<brand>-<lockup>-<colourway>@1x/@2x/@3x.png` | transparent, sRGB |
| `favicon.svg` | mark with a `prefers-color-scheme: dark` style rule |
| `favicon.ico` | 32 px frame plus a 16 px frame (hand-fitted small variant when available) |
| `apple-touch-icon.png` | 180 x 180, opaque background, mark within 140 px |
| `icon-192.png`, `icon-512.png`, `icon-mask.png` | manifest icons; maskable 512 with all ink inside the central circle of radius 40% (204.8 px) |
| CMYK / spot | handed to `print-prepress-pdfx` with the printer's profile and the Pantone choice |

`logo_kit.py` writes the raster files and prints the manifest and `<link>` snippets; it reports
the maskable icon's measured ink radius against the 204.8 px limit. Full naming, favicon.svg and
print hand-off: [export kit](references/export-kit.md).

## 11. Worked example: geometric monogram "B" (fictional brand Brackenby)

Directions on a 96-unit grid: (A) stacked B, a 16-unit stem plus two semicircular bowls, 0/90
geometry; (B) ring B, two circles threaded on a stem. Direction A won on the 16 px test and on
distinctiveness (no bowls-only B among the 10 competitors).

Master v1 (horizontals 15 units, upper counter 6 units tall):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
  <path fill="#111" fill-rule="evenodd" d="M16 6H44A18 18 0 0 1 44 42A22 22 0 0 1 44 86H16Z
    M32 21H44A3 3 0 0 1 44 27H32Z M32 57H44A7 7 0 0 1 44 71H32Z"/>
</svg>
```

```text
$ "$PY" -I "$L/logo_ladder.py" mark-v1.svg --counter 34,21,44,27 --counter 34,57,48,71 --sizes 16,24,32,64
  16px counter 34,21,44,27: min 0.50 mean 0.50 -> closing     (upper counter is a grey bar)
  16px counter 34,57,48,71: min 0.00 mean 0.26 -> open
  24px counter 34,21,44,27: min 0.25 mean 0.25 -> open        (borderline)
  32px counter 34,21,44,27: min 0.00 mean 0.00 -> open
```

Cause: the 6-unit counter is exactly one pixel at 16 px and straddles two pixel rows (21/6 = 3.5).
Fix v2: horizontals 15 -> 12 units (beyond the usual 5-10% because the favicon governs), upper
counter edges on multiples of 6 (18..30 = pixel rows 3-4 at 16 px; the lower counter, 54..74, is
3.3 px tall and open anyway), and 45-degree ink traps cut into the stem at the four counter corners:

```svg
<path fill="#111" fill-rule="evenodd" d="M16 6H44A18 18 0 0 1 44 42A22 22 0 0 1 44 86H16Z
  M32 20L29 17L31 15L34 18H44A6 6 0 0 1 44 30H34L31 33L29 31L32 28Z
  M32 56L29 53L31 51L34 54H44A10 10 0 0 1 44 74H34L31 77L29 75L32 72Z"/>
```

```text
$ "$PY" -I "$L/logo_ladder.py" mark-v2.svg --counter 34,18,48,30 --counter 34,54,52,74 --sizes 16,24,32,64
  16px counter 34,18,48,30: min 0.00 mean 0.03 -> open
  16px counter 34,54,52,74: min 0.00 mean 0.10 -> open        (all sizes open; exit 0)
$ python3 -I "$SVG" check mark-v2.svg --budget logo
mark-v2.svg: ok, 1 paths, 1 colors, 305 bytes, max 0 decimals
$ "$PY" -I "$L/logo_kit.py" mark-v2.svg --name brackenby-mark --out kit --bg '#1A1A2E' --fg-on-bg mark-v2-reversed.svg
maskable ink radius 172.1 px (limit 204.8)
```

The ink traps alone did not reopen the counter (still 0.50); the counter size and pixel alignment
did. The traps keep the junctions clean in print and engraving; at 64 px they read as small
notches, so they stay at 3 units (under 4% of the mark height).

Usage table delivered with the kit:

| Lockup | Min size | Clear space | Colourways | Backgrounds |
|---|---|---|---|---|
| Mark only | 16 px / 6 mm tall | 0.25 x mark height | #111 on white, white on #1A1A2E | white, #1A1A2E, photos with a plate |
| Horizontal | 96 px / 25 mm wide | 0.25 x mark height | full colour, 1-colour, reversed | as above |
| Favicon | 16 and 32 px (ico), svg | n/a | dark-mode aware svg | browser chrome |

## Pitfalls

- Hairlines and ink traps that vanish small or fill in print; details below 1/32 of the mark
  height.
- A gradient, shadow or texture that the mark depends on (it must work in one flat colour).
- Trend-chasing (category cliches, this year's style) instead of the empty quadrant.
- Colour as the only differentiator between versions or from competitors.
- Unlicensed or EULA-restricted fonts in a wordmark; generated lettering.
- Even-odd fills over overlapping shapes (seams), un-united booleans, hundreds of nodes from a
  trace or a generator.
- Testing only at 256 px on screen; skipping reversed, one-colour, embroidery or engraving.
- Calling a lookalike search "trademark clearance".

Related: `vector-art`, `svg-hand-authoring`, `brand-guidelines-system`, `type-scale-systems`,
`oklch-palette-ramps`, `icon-system-design`, `print-prepress-pdfx`, `visual-review`, hub `graphic-design`.
