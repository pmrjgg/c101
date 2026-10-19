# Discovery and clearance

## 1. Discovery worksheet (YAML, saved next to the brief)

```yaml
brand: Brackenby                     # fictional example
attributes: [precise, warm, durable] # three adjectives the mark must show
name:
  meaning: invented; evokes bracken (fern) and -by (settlement)
  length: 9 letters
  initials: B
audience: outdoor-gear repair shops (B2B), owners aged 30-60
category_cliches: [mountains, pine trees, compass roses]
contexts:                            # smallest and hardest first
  - {use: favicon, size: 16 px}
  - {use: app icon, size: 1024 px master, mask: rounded square}
  - {use: embroidered cap, size: 20 mm wide, colours: 1}
  - {use: laser-engraved tool, size: 8 mm, colours: 0 (engraving)}
  - {use: shop sign, size: 600 mm, viewing distance: 10 m}
colour: one-colour first; palette later (oklch-palette-ramps)
must_avoid: [mountains, trees, gradients]
decision_maker: founder
taste_references: [two Swiss-style geometric marks the founder likes, as files]
deadline: 2026-11-15
open_doubts: []
```

## 2. Competitor map

1. Collect 8-12 marks (official sites, screenshots or SVGs; never generate imitations).
2. Score each on two axes from -2 to +2: x = geometric (-2) to organic (+2), y = literal (-2) to
   abstract (+2). Two people scoring independently and averaging reduces bias.
3. Plot and look for the empty or thin quadrant; also note shared colours and shapes.

```python
# PY -I map.py   (marks.csv: name,x,y)
import csv
from PIL import Image, ImageDraw
W = 640; m = 60; im = Image.new("RGB", (W, W), "white"); d = ImageDraw.Draw(im)
c = W // 2; s = (W / 2 - m) / 2
d.line([(m, c), (W - m, c)], fill=(150, 150, 150)); d.line([(c, m), (c, W - m)], fill=(150, 150, 150))
for t, xy in (("geometric", (m, c + 6)), ("organic", (W - m - 50, c + 6)),
              ("abstract", (c + 6, m)), ("literal", (c + 6, W - m - 12))):
    d.text(xy, t, fill=(90, 90, 90))
for row in csv.DictReader(open("marks.csv")):
    x, y = c + float(row["x"]) * s, c - float(row["y"]) * s
    d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(30, 30, 30))
    d.text((x + 8, y - 6), row["name"], fill=(0, 0, 0))
im.save("competitor-map.png")
```

Read the PNG and write one sentence: "7 of 10 sit in organic + literal; none in geometric +
abstract; two use green". The chosen direction should land away from the cluster.

## 3. Direction scoring

| Direction | Attribute fit (0-3 each x3) | 16 px test (0-3) | Distinct from map (0-3) | Extensible (0-3) | Total /18 |
|---|---|---|---|---|---|
| A stacked B | 2, 3, 2 | 3 (after fix) | 3 | 2 | 15 |
| B ring B | 2, 2, 2 | 1 (rings merge at 16 px) | 2 | 2 | 11 |

Keep the scoring rationale in one line per cell when presenting; the decision-maker sees the
table and the ladder sheets, not 40 thumbnails.

## 4. Lookalike search procedure

| Source | How | Record |
|---|---|---|
| Google Lens | upload the 256 px black mark and each final lockup | screenshots of the 10 closest results |
| TinEye | same files | match count, closest hits |
| USPTO Trademark Search | figurative marks via design search codes from the Design Search Code Manual (e.g. the codes for letters presented in a geometric design); filter by status live | serial numbers of close marks |
| EUIPO eSearch plus / TMview | image search where offered; filter Nice classes and territories | application numbers |
| WIPO Global Brand Database | image search plus Nice class filter | record ids |

Nice classes: list the client's goods and services (here 35 retail, 37 repair services) and
search those plus neighbouring classes. Lookalike means overall impression: same structure, same
letter, same concept, not only identical artwork.

Report template (Open doubt, never "cleared"):

```text
- [legal|high] Lookalike check 2026-10-19: Google Lens, TinEye, USPTO Trademark Search (design
  codes for stylised letter B), TMview and WIPO GBD image search, Nice 35/37: two letter-B marks
  with stacked bowls found in class 25 (apparel), none in 35/37 - not legal clearance - resolve:
  trademark counsel runs a full search and files before launch - route: user
```

## 5. Presenting directions

- Each direction on one sheet: the mark at 256 px, the ladder (16-64 px), black and reversed,
  one realistic mock-up (sign, cap or app icon), and one rationale sentence tied to the
  attributes.
- Show the construction grid only as supporting material; do not sell a mark by its geometry.
- Never present raster-generated logos as finals; label exploration sketches as such.
