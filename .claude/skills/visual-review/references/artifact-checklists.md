# Artefact checklists per output type

Run every row for the output type (and the rows of each type a deliverable combines: a layered logo
is typography / logo + SVG + layered SVG + layered PDF). Record each finding as
`ID - where - what - measurement`, map it to its criterion and apply the caps from
[rubric-anchors.md](rubric-anchors.md#8-caps-hard-gates). Snippets referenced as `S0`..`S10` are in
the last section.

Contents: 1 photoreal, 2 illustration, 3 typography and logos, 4 cutouts and RGBA edges, 5 masks,
6 edits and inpaints, 7 upscales, 8 SVG and vector, 9 layered SVG, 10 layered PDF, 11 inspection
snippets.

## 1. Photoreal

| ID | Check | How | Criterion (cap) |
|---|---|---|---|
| P1 | Hands: five fingers each, joints plausible, no fusion, nails and knuckles consistent | zoom crop 3x of every hand | artefacts (4) |
| P2 | Faces: eye symmetry and gaze direction, irises round, teeth count and shape, ears, hairline | zoom crop 3x | artefacts (4) |
| P3 | Limbs and body: count, length, joints, clothing continuity across occlusions | full view + crops | artefacts (4) |
| P4 | Text on objects (signs, labels, screens): exact or intentionally absent | crop, read letter by letter | typography (4) or artefacts (4) if unrequested |
| P5 | Light: one consistent direction; shadows and reflections agree; specular highlights on the right side | full view | artefacts |
| P6 | Geometry: straight lines straight, verticals vertical unless intended, perspective vanishing points agree | crop the architecture | artefacts / composition |
| P7 | Duplicates and melts: repeated objects, merged objects, smeared backgrounds, impossible joins | full view, then crops of busy areas | artefacts (4) |
| P8 | Skin and material texture: no plastic skin, no over-smoothing, no repeated texture tiles | crop 2x | artefacts |
| P9 | Noise, banding (skies, gradients), compression blocks, over-sharpening halos | crop 4x of a smooth gradient | artefacts / colour (5 for banding in a key area) |
| P10 | Watermark-like marks, signatures, stock-photo text | corners and edges | artefacts (4) |
| P11 | Likeness and brands: no unrequested real person, logo or trademark | full view | fidelity (3) |
| P12 | Copy-safe area and crops the brief names (e.g. 16:9 hero also cropped 1:1) | crop each named area with the SKILL.md zoom one-liner (factor 1) and Read it | composition |

## 2. Illustration

| ID | Check | How | Criterion (cap) |
|---|---|---|---|
| I1 | One consistent style across the frame (line weight, shading model, texture, palette) | full view + 3 crops in different areas | artefacts / references |
| I2 | Line quality: no wobbly, doubled or broken lines where clean ink is intended | crop 3x | artefacts |
| I3 | Anatomy and perspective (same as P1-P3 for characters) | crops | artefacts (4) |
| I4 | Stray marks, smudges, half-erased objects, unintended text or signature | full view, corners | artefacts (4) |
| I5 | Flat-colour areas really flat when the brief says flat (no gradients or noise) | crop 4x | fidelity / artefacts |
| I6 | Character consistency with model sheets or earlier images in the set | sheet S9 | references |
| I7 | Palette roles and limits (e.g. "4 colours") | count dominant colours in a crop (S6) | colour / fidelity |

## 3. Typography and logos

| ID | Check | How | Criterion (cap) |
|---|---|---|---|
| T1 | Every required string exact: letters, case, punctuation, diacritics, line breaks | zoom crop; write what you read in Evidence | typography (4) |
| T2 | Glyph integrity: no melted or invented letterforms, consistent stroke contrast | crop 4x per word | typography (5) |
| T3 | Spacing: kerning pairs (AV, To, LT), even word spacing, aligned baselines | crop 4x | typography |
| T4 | Hierarchy: headline, subhead, body clearly ranked; at most 2 families unless the brief asks | full view | typography / composition |
| T5 | Legibility at the smallest target size: logos at 16 and 32 px, posters at viewing distance | S0 at the target pixel size; SVGs via `svg_render` at that width | typography |
| T6 | Contrast of every text pair (WCAG; SKILL.md section 6 snippet) | measure | colour (5) |
| T7 | Logo: clear space, works in one colour and reversed (render on dark), no fine detail that disappears at 16 px | svg_render on light and dark, 16/32/64/512 | technical / artefacts |
| T8 | SVG text: outlines for logos; live `<text>` only where the brief wants editable text, with a generic font fallback | svg_inspect text elements | technical |
| T9 | No unrequested trademark resemblance | full view | fidelity (3) |

## 4. Cutouts and RGBA edges

| ID | Check | How | Criterion (cap) |
|---|---|---|---|
| C1 | Alpha exists and is not fully opaque; mode RGBA; size equals the source | `image_info`; S2 | technical (2) |
| C2 | Subject complete: nothing chopped (fingers, ears, product edges, thin parts like straps and antennas) | strip S1 over black and white; compare with the source | fidelity / artefacts (4) |
| C3 | Halo or fringe: light ring on dark backgrounds or dark ring on light | strip S1; S2 ring luma vs interior luma (difference > ~40 with a visible ring = halo) | artefacts (5) |
| C4 | Hair, fur, glass, smoke: soft partial alpha, not a hard cut-out or a grey veil | S2 `partial` fraction (near 0 on hair = hard edge); zoom 4x | artefacts |
| C5 | Residual background: haze, islands, unremoved shadows or floor | strip over magenta and green; S2 `bbox` hugging the subject | artefacts / fidelity |
| C6 | Holes: transparent pixels inside the subject (eyes, logos, white shirts on white backgrounds) | strip over magenta | artefacts (4) |
| C7 | Pixels preserved: RGB inside the alpha equals the source (alpha transfer); drift noted in the sidecar | S4 diff with the alpha as mask (inside mean < 2) | references |
| C8 | Contact shadow: present or absent as the brief says, soft and in the light direction | strip over the intended background | fidelity |
| C9 | Alpha bbox touching the frame edge where the subject should be whole | S2 `bbox` | artefacts (4) |

## 5. Masks

| ID | Check | How | Criterion (cap) |
|---|---|---|---|
| M1 | Size equals the source; single channel; convention white = edit (canonical) | S3 `size`, `source_size`; `image_info` | technical (4) |
| M2 | Binary when the consumer needs binary (grey fraction <= 1%) or intentionally feathered at 1-2 px | S3 `non_binary` | technical (4) |
| M3 | Selects the intended object, all of it, nothing else | overlay S5 on the source, Read; zoom the boundary | fidelity |
| M4 | Margin: grown enough for the edit (hands 12-24 px, text 8 px) without eating neighbours | overlay, measure in px | fidelity |
| M5 | Speckles and holes | S3 `speckle_px` (counts of a few px per corner are normal rounding; clusters are islands) + overlay | artefacts |
| M6 | Edge alignment with the object boundary (no 5+ px offset) | overlay crop 4x | references |
| M7 | Coverage plausible (`coverage` fraction vs the object's share of the frame) | S3 | fidelity |

## 6. Edits and inpaints

| ID | Check | How | Criterion (cap) |
|---|---|---|---|
| E1 | The instruction executed exactly inside the region (object, colour, count, text) | side by side S9 at the same scale | fidelity |
| E2 | Outside the mask unchanged | S4 with the mask grown by 3 px: outside mean < 1.0, changed < 0.1% | references (4 when mean > 3 or changed > 0.5%) |
| E3 | Seam at the mask boundary: no visible edge, matching grain, noise, blur and light | crop 4x along the boundary | artefacts |
| E4 | Lighting and perspective of the new content match the scene | full view + crop | artefacts |
| E5 | Size, mode and format equal to the source unless the brief changed them | `image_info` on both | technical |
| E6 | The sidecar `notes`: e.g. mask sent as an extra reference (OpenRouter), whole-frame regeneration | Read sidecar | technical / references |

## 7. Upscales

| ID | Check | How | Criterion (cap) |
|---|---|---|---|
| U1 | Target size reached exactly; aspect unchanged | `image_info` | technical (4) |
| U2 | No invented content: faces, text and logos keep their identity and spelling | side by side S9 with the source resized to the same size | references / typography (4) |
| U3 | No over-sharpening halos, ringing, waxy skin, painterly texture on photos | crop 4x of edges and skin | artefacts |
| U4 | Alpha preserved for RGBA sources (split-alpha upscale) | `image_info`, S2 | technical (2) |
| U5 | Noise and JPEG blocks not amplified | crop 4x of flat areas | artefacts |

## 8. SVG and vector

Start with `mcp__image__svg_inspect`; render with `mcp__image__svg_render` (sizes per SKILL.md
section 6). The vector-art skill's validator, when installed, adds a second opinion:
`python3 -I "$STACK/.claude/skills/vector-art/scripts/svgcheck.py" check f.svg --budget icon|logo|illustration`
with `STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"` in the same command.

| ID | Check | How | Criterion (cap) |
|---|---|---|---|
| V1 | Well-formed XML, root `<svg>` in the SVG namespace | svg_inspect | technical (0) |
| V2 | Safety: no `<script>`, `<foreignObject>`, `on*=` handlers, external or `javascript:` hrefs, `@import` | svg_inspect flags; `grep -Eic "<script|<foreignObject|[[:space:]]on[a-z]+=|javascript:" f.svg` must print 0 | technical (0) |
| V3 | viewBox present, origin as intended, aspect equals the brief; icons on their grid (`0 0 24 24`) without fixed width/height | svg_inspect | technical (6 when fixable) |
| V4 | Content inside the viewBox: nothing clipped at the edges, safe margin respected | render with a contrasting background; look at all four edges | composition / artefacts |
| V5 | Path count and file size within budget (icon 40 paths / 4 KB, logo 150 / 20 KB, illustration 2,500 / 150 KB unless the brief sets its own) | svg_inspect counts; `wc -c` | technical (5 at 2-4x) |
| V6 | Palette: count equals the brief; every colour within dE 0.5 of a brand hex; no near-duplicates (dE < 3, tracing noise) | svg_inspect palette -> S6 | colour / technical |
| V7 | Embedded rasters: none unless requested | svg_inspect | technical (3) |
| V8 | Live `<text>` vs outlines as the brief wants | svg_inspect text elements | technical |
| V9 | Hairline gaps between adjacent fills, slivers, overlapping duplicates | render at 2048 on a contrasting background; zoom joins | artefacts |
| V10 | Strokes: consistent width across the file or set, `stroke-linecap`/`linejoin` as specified, no scaled strokes in icons | Read the SVG text (Grep `stroke-width`) | references / artefacts |
| V11 | Ids unique (and prefixed when the SVG will be inlined); no dangling `url(#id)` | svg_inspect or svgcheck | technical |
| V12 | Precision: at most 2 decimals for icons, 3 for logos and illustrations | Grep a sample of path data | technical (8) |
| V13 | Gradients and filters justified (none in a flat icon set) | svg_inspect | fidelity / technical |
| V14 | Small-size legibility: counters open, details survive at 16-24 px | renders at 16/24/32/48 | artefacts / typography |
| V15 | Tracing quality: smooth curves, no stair-steps, no thousands of speckle paths | render 2048 crop + counts | artefacts |
| V16 | Accessibility: standalone meaningful graphic has `<title>` | Grep | technical (8) |

## 9. Layered SVG

| ID | Check | How | Criterion (cap) |
|---|---|---|---|
| L1 | Top-level `<g id="layer-..." inkscape:groupmode="layer" inkscape:label="...">` groups exist (Inkscape-native; Illustrator imports top-level groups as layers) | `mcp__image__svg_layers` | technical (4) |
| L2 | Layer names and count match the brief's layer plan (e.g. Background, Mark, Text) | svg_layers labels | technical / fidelity |
| L3 | Nothing drawable outside layers (only `<defs>`, `<title>`, `<desc>`, `<metadata>` at top level) | svg_inspect or Grep the top level | technical |
| L4 | Z-order: background first, text last; appearance identical to the unlayered source | render full file vs the source render, side by side S9 | artefacts / references |
| L5 | Each layer holds what its name says, and nothing else | S7 split + `svg_render` of each copy | technical |
| L6 | No empty layers; hidden layers (`display:none`) only when intended | svg_layers element counts and visibility | technical |
| L7 | Shared `<defs>` (gradients, clip paths) still referenced correctly after layering | render each layer copy; no missing fills | artefacts |
| L8 | Raster layers (from `layers_compose`) embedded as `<image>` data URIs only in their own layer, at the stated position and size | svg_layers, render | technical |

## 10. Layered PDF (OCGs)

| ID | Check | How | Criterion (cap) |
|---|---|---|---|
| D1 | `/OCProperties` exists and lists one OCG per SVG layer | S8 `ocgs` vs svg_layers labels | technical (3) |
| D2 | OCG names equal the SVG layer labels, same order (`/D /Order`) | S8 `order` | technical |
| D3 | Content bound to the OCGs: `/OC` marked-content blocks (`oc_blocks`) or Form XObjects with `/OC` (`oc_forms`) at least equal to the layer count | S8 | technical (3 when 0) |
| D4 | Default visibility: `/OFF` lists exactly the layers hidden in the SVG | S8 `off` | technical |
| D5 | Vector pages: `images` = 0 unless a raster layer was intended; text outlined or fonts embedded | S8 `images`, `fonts` | technical (3) |
| D6 | Page size: auto = SVG size; A4 = 595.28 x 841.89 pt; letter = 612 x 792 pt; W x H mm = mm x 72 / 25.4 pt | S8 `mediabox_pt` | technical (4) |
| D7 | Appearance equals the SVG render (colours, z-order, nothing missing) | Read the PDF (`pages: "1"`) or `sips -s format png f.pdf --out <review-dir>/page1.png`; side by side with `svg_render` | references / artefacts |
| D8 | Non-layered request: single-layer PDF is correct; OCGs are not required | S8 | - |

Toggling layers in Acrobat or Illustrator cannot be done here; D1-D4 are the proof that it will
work. Say so in Evidence.

## 11. Inspection snippets

Each block is one Bash command: it sets `PY` to the stack venv interpreter (Pillow, pikepdf,
resvg_py; variables do not persist between Bash calls), passes the inputs as arguments and reads
the Python from a quoted heredoc. Replace the example paths; write every output into the review
directory, never next to a deliverable.

**S0 - view at target size** (IN OUT MAX_SIDE; then Read OUT; for SVGs render at that width instead):

```bash
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I -c "import sys;from PIL import Image as I;im=I.open(sys.argv[1]);n=int(sys.argv[3]);im.thumbnail((n,n),I.LANCZOS);im.save(sys.argv[2])" hero.png <review-dir>/hero-at-320.png 320
```

**S1 - background strip** (RGBA over black, white, magenta, green and optional extra hex
backgrounds; optional crop box first, which keeps large images readable):

```bash
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I - cut.png <review-dir>/strip.png 80,30,320,270 '#f4efe6' <<'EOF'
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGBA")
if len(sys.argv) > 3: im = im.crop(tuple(map(int, sys.argv[3].split(","))))
bgs = [(0, 0, 0), (255, 255, 255), (255, 0, 255), (0, 160, 0)] + [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in sys.argv[4:]]
out = Image.new("RGB", (im.width * len(bgs), im.height))
for i, c in enumerate(bgs):
    b = Image.new("RGBA", im.size, c + (255,)); b.alpha_composite(im); out.paste(b.convert("RGB"), (i * im.width, 0))
out.save(sys.argv[2])
EOF
```

**S2 - alpha statistics and halo ring** (`partial` near 0 on hair = hard edge; `ring_luma` far
from `inner_luma`, with a visible ring in S1, = halo or fringe):

```bash
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I - cut.png <<'EOF'
import sys, json
from PIL import Image, ImageChops, ImageFilter, ImageStat
im = Image.open(sys.argv[1]).convert("RGBA"); a = im.getchannel("A"); h = a.histogram(); n = sum(h)
solid = a.point(lambda v: 255 if v > 127 else 0); inner = solid.filter(ImageFilter.MinFilter(7))
ring = ImageChops.subtract(solid, inner); rgb = im.convert("RGB")
lum = lambda c: round(0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2], 1)
print(json.dumps({"transparent": round(h[0] / n, 4), "opaque": round(h[255] / n, 4),
    "partial": round(1 - (h[0] + h[255]) / n, 4), "bbox": a.getbbox(),
    "ring_luma": lum(ImageStat.Stat(rgb, mask=ring).mean) if ring.getbbox() else None,
    "inner_luma": lum(ImageStat.Stat(rgb, mask=inner).mean) if inner.getbbox() else None}))
EOF
```

**S3 - mask statistics** (MASK SOURCE; `speckle_px` of a few pixels per corner is normal rounding,
clusters are islands or holes):

```bash
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I - mask.png src.png <<'EOF'
import sys, json
from PIL import Image, ImageChops, ImageFilter
m = Image.open(sys.argv[1]).convert("L"); src = Image.open(sys.argv[2]); h = m.histogram(); n = sum(h)
speck = ImageChops.difference(m, m.filter(ImageFilter.MedianFilter(5))).point(lambda v: 255 if v > 127 else 0)
print(json.dumps({"size": m.size, "source_size": src.size, "coverage": round(sum(h[128:]) / n, 4),
    "non_binary": round(1 - (h[0] + h[255]) / n, 4), "speckle_px": speck.histogram()[255], "bbox": m.getbbox()}))
EOF
```

**S4 - diff inside vs outside a mask** (ORIGINAL EDITED MASK [GROW_PX]; "changed" = abs diff > 8
of 255; grow 3 px for server-feathered edits; for cutouts pass the cutout's alpha as the mask):

```bash
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I - src.png edit.png mask.png 3 <<'EOF'
import sys, json
from PIL import Image, ImageChops, ImageFilter, ImageStat
o = Image.open(sys.argv[1]).convert("RGB"); e = Image.open(sys.argv[2]).convert("RGB").resize(o.size)
mi = Image.open(sys.argv[3]); mi = mi.getchannel("A") if mi.mode in ("RGBA", "LA") else mi.convert("L")
m = mi.resize(o.size).point(lambda v: 255 if v > 127 else 0)
g = int(sys.argv[4]) if len(sys.argv) > 4 else 0
if g: m = m.filter(ImageFilter.MaxFilter(2 * g + 1))
d = ImageChops.difference(o, e).convert("L"); out = ImageChops.invert(m); ch = d.point(lambda v: 255 if v > 8 else 0)
f = lambda k: (round(ImageStat.Stat(d, mask=k).mean[0], 3), round(ImageStat.Stat(ch, mask=k).mean[0] / 255, 5)) if k.getbbox() else (None, None)
(a, b), (c, z) = f(m), f(out)
print(json.dumps({"inside_mean": a, "inside_changed": b, "outside_mean": c, "outside_changed": z}))
EOF
```

**S5 - mask overlay** (red tint over the edit area; SOURCE MASK OUT):

```bash
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I -c "import sys;from PIL import Image as I;s=I.open(sys.argv[1]).convert('RGB');m=I.open(sys.argv[2]).convert('L').resize(s.size);I.composite(I.blend(s,I.new('RGB',s.size,(255,0,0)),0.5),s,m).save(sys.argv[3])" src.png mask.png <review-dir>/overlay.png
```

**S6 - palette delta-E 76 against brand hex** (BRAND_CSV, then colours from `svg_inspect` or
sampled medians; stdlib only). To sample a raster colour take the median of a box,
`ImageStat.Stat(im.crop(box)).median[:3]`, formatted as `'#%02x%02x%02x'`.

```bash
python3 -I - '#0f172a,#3b82f6,#fff' '#3a80f0' '#fefefe' '#e11d48' <<'EOF'
import sys
def lab(h):
    h = h.lstrip("#"); h = "".join(c * 2 for c in h) if len(h) == 3 else h
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    x = (0.4124 * c[0] + 0.3576 * c[1] + 0.1805 * c[2]) / 0.95047
    y = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    z = (0.0193 * c[0] + 0.1192 * c[1] + 0.9505 * c[2]) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))
de = lambda a, b: sum((p - q) ** 2 for p, q in zip(lab(a), lab(b))) ** 0.5
brand = sys.argv[1].split(","); cols = sys.argv[2:]
for c in cols:
    near = min(brand, key=lambda b: de(c, b)); d = de(c, near)
    print("%s -> %s  dE76 %.1f  %s" % (c, near, d, "exact" if d < 0.5 else "ok" if d <= 2 else "drift" if d <= 5 else "OFF-BRAND"))
print("near-duplicates (dE<3):", [(a, b, round(de(a, b), 1)) for i, a in enumerate(cols) for b in cols[i + 1:] if de(a, b) < 3] or "none")
EOF
```

**S7 - one SVG copy per layer** (other layers hidden; then `svg_render` each copy; SVG OUTDIR):

```bash
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I - logo.svg <review-dir>/layers <<'EOF'
import sys, os, xml.etree.ElementTree as ET
S, K = "http://www.w3.org/2000/svg", "http://www.inkscape.org/namespaces/inkscape"
for p, u in (("", S), ("inkscape", K), ("xlink", "http://www.w3.org/1999/xlink"),
             ("sodipodi", "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd")):
    ET.register_namespace(p, u)
tree = ET.parse(sys.argv[1]); root = tree.getroot(); os.makedirs(sys.argv[2], exist_ok=True)
layers = [g for g in root if g.tag == "{%s}g" % S and g.get("{%s}groupmode" % K) == "layer"]
for i, keep in enumerate(layers):
    for g in layers: g.set("style", "display:inline" if g is keep else "display:none")
    out = os.path.join(sys.argv[2], "layer-%02d-%s.svg" % (i, keep.get("id", "x")))
    tree.write(out, xml_declaration=True, encoding="utf-8"); print(out, keep.get("{%s}label" % K))
EOF
```

**S8 - PDF OCG check** (pikepdf; `ocgs: null` means no layers):

```bash
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I - logo.pdf <<'EOF'
import sys, json, pikepdf
pdf = pikepdf.open(sys.argv[1]); oc = pdf.Root.get("/OCProperties")
nm = lambda g: str(g.get("/Name"))
rep = {"pages": len(pdf.pages), "ocgs": [nm(g) for g in oc.OCGs] if oc else None,
       "off": [nm(g) for g in oc.D.get("/OFF", [])] if oc else [],
       "order": [nm(g) for g in oc.D.get("/Order", []) if isinstance(g, pikepdf.Dictionary)] if oc else []}
for i, p in enumerate(pdf.pages):
    res = p.obj.get("/Resources", pikepdf.Dictionary()); xo = res.get("/XObject", {})
    bdc = sum(1 for ins in pikepdf.parse_content_stream(p)
              if str(ins.operator) == "BDC" and ins.operands and str(ins.operands[0]) == "/OC")
    rep["page%d" % i] = {"mediabox_pt": [round(float(v), 2) for v in p.mediabox], "oc_blocks": bdc,
        "oc_forms": sum(1 for k in xo.keys() if "/OC" in xo[k]),
        "images": sum(1 for k in xo.keys() if xo[k].get("/Subtype") == "/Image"),
        "fonts": [str(k) for k in res.get("/Font", {}).keys()]}
print(json.dumps(rep))
EOF
```

Nested Form XObjects are not descended. When `ocgs` is populated but `oc_blocks` and `oc_forms`
are both 0, look one level deeper (`/XObject` entries of each Form XObject's own `/Resources`)
before failing D3.

**S9 - contact sheet / side by side** (OUT CELL FILE...; transparency on a checkerboard; one Read
reviews many files; the image-generation skill's `imgcheck.py sheet` does the same when installed):

```bash
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I - <review-dir>/sheet.png 512 a.png b.png ref.png <<'EOF'
import sys, os
from PIL import Image, ImageDraw
out, cell, files = sys.argv[1], int(sys.argv[2]), sys.argv[3:]; cols = min(4, len(files)); rows = -(-len(files) // cols)
sheet = Image.new("RGB", (cols * cell, rows * (cell + 18)), (255, 255, 255)); d = ImageDraw.Draw(sheet)
for i, f in enumerate(files):
    im = Image.open(f).convert("RGBA"); im.thumbnail((cell, cell))
    bg = Image.new("RGBA", (cell, cell), (204, 204, 204, 255)); bd = ImageDraw.Draw(bg)
    for y in range(0, cell, 16):
        for x in range(0, cell, 16):
            if (x // 16 + y // 16) % 2: bd.rectangle((x, y, x + 15, y + 15), fill=(255, 255, 255, 255))
    bg.alpha_composite(im, ((cell - im.width) // 2, (cell - im.height) // 2))
    x, y = (i % cols) * cell, (i // cols) * (cell + 18)
    sheet.paste(bg.convert("RGB"), (x, y + 18)); d.text((x + 4, y + 3), "%d %s" % (i + 1, os.path.basename(f))[:60], fill=(0, 0, 0))
sheet.save(out)
EOF
```

**S10 - fallback SVG render** when the `image` server is not connected (say so in Evidence;
SVG OUT WIDTH BACKGROUND):

```bash
PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python"
"$PY" -I -c "import sys,resvg_py;open(sys.argv[2],'wb').write(bytes(resvg_py.svg_to_bytes(svg_path=sys.argv[1],width=int(sys.argv[3]),background=sys.argv[4])))" logo.svg <review-dir>/logo-1024.png 1024 '#ffffff'
```
