# Placements, safe zones and the kit file

Checked 2026-10-19 against: Meta's Instagram Stories ad guide (9:16, 1440 x 2560 recommended,
14% top / 35% bottom / 6% sides free of text), the IAB Tech Lab LEAN fixed-size ad
specification (2017 release; no newer fixed-size table was found when checked), YouTube thumbnail guidance
(1280 x 720, >= 640 px wide, under 2 MB) and the Instagram 3:4 profile grid (rolled out January
2025). Platforms change these without notice: re-check before every launch and record the date.

## 1. Social and web placements

| Placement | Aspect | Pixels | Safe-zone insets for `kitcheck` (fractions) | Notes |
|---|---|---|---|---|
| Feed portrait | 4:5 | 1080 x 1350 | left/right 0.031 (3:4 grid crop) | Instagram, Facebook, LinkedIn feeds |
| Feed square | 1:1 | 1080 x 1080 | left/right 0.125 (3:4 grid crop) | |
| Feed 3:4 | 3:4 | 1080 x 1440 | none | fills the Instagram grid tile without a crop |
| Story / Reel, organic | 9:16 | 1080 x 1920 | top 0.14, bottom 0.20 | username, caption and reply bar overlays |
| Instagram Stories ad | 9:16 | 1080 x 1920 (1440 x 2560 recommended) | top 0.14, bottom 0.35, left/right 0.06 | Meta places a CTA in the bottom zone |
| Reel cover in the grid | 9:16 shown 3:4 | 1080 x 1920 | top/bottom 0.125 (centre 1080 x 1440) | |
| OG / link preview | 1.91:1 | 1200 x 630 | left/right 0.05 (0.2375 to survive a square crop) | text >= 48 px |
| YouTube thumbnail | 16:9 | 1280 x 720 | keep the bottom-right ~15% x 12% free (duration badge) | JPG, PNG or GIF under 2 MB |
| Web hero | 16:9 to 21:9 | 1920-2560 wide | design a 4:5 art-direction crop for mobile | |
| Slide or video frame | 16:9 | 1920 x 1080 | 0.05 all sides (title-safe) | |

The "safe" numbers for the YouTube badge and OG crop are working values, not platform
specifications; keep critical content clear of them and inspect the platform preview.

## 2. IAB display (LEAN fixed-size table)

| Unit | Size | Initial load (kB) | Subload (kB) |
|---|---|---|---|
| Medium rectangle | 300 x 250 | 150 | 300 |
| Leaderboard | 728 x 90 | 150 | 300 |
| Skyscraper | 160 x 600 | 150 | 300 |
| Smartphone banner | 300 x 50 or 320 x 50 | 50 | 100 |
| Super leaderboard / pushdown | 970 x 90 | 200 | 400 |
| Billboard | 970 x 250 | 250 | 500 |
| Portrait | 300 x 1050 | 250 | 500 |
| Mobile phone interstitial | 640 x 1136, 750 x 1334 or 1080 x 1920 | 300 | 600 |
| 120 x 60 | 120 x 60 | 50 | 100 |

Rules from the same specification: weights are measured after gzip; static image ads use the
initial-load figure; on 3G-class connections weights should be 30% lower; at most ten file
requests during initial load; audio muted by default; ad content clearly distinguishable from
publisher content (for example a defined border). Fixed-size weights are calculated at double
density, so a 2x asset (600 x 500 for the medium rectangle) is expected to fit the same budget.
The 300 x 600 half page is not in the fixed table; its flexible-grid size group allows 250 kB.
Ad servers and networks publish their own (often stricter) caps: theirs win.

## 3. How `kitcheck plan` maps a placement into the master

Given master W x H, focal box F and a placement w x h (aspect a = w / h) with insets
(top, bottom, left, right):

1. Window width: `fill` → `fw / (fill x (1 - left - right))`; `fill_h` → height from the same
   rule; neither → the largest window of aspect a inside the master. Window height = width / a.
2. Position: the focal centre goes to `anchor` inside the safe box; a window that fits inside the
   master is then clamped into it (crop); a window larger than the master keeps its position and
   the overflow becomes outpaint pads.
3. Safe box in master px = window origin + insets x window size. `focus_ok` = F inside it.
4. `safe_in_all_master_px` = intersection of every placement's safe box (equivalently, the master
   minus the union of all keep-out zones): the only area guaranteed visible and uncovered in every
   placement. The focal subject, and any element that must survive everywhere, belongs there.
5. `copy_bands_px` = the parts of each placement's safe box above, below, left and right of the
   focal box: where that placement's text template may go.
6. `new_area_share` = 1 - (window ∩ master) / window: the share an outpaint must invent.

## 4. Kit file template

```json
{"campaign": "orbit", "message": "launch", "version": 1,
 "master": {"file": "master.png", "w": 3840, "h": 2160, "focus": [2000, 430, 3300, 1730]},
 "copy": {"headline": "Orbit 2 is here", "sub": "Sync every device in one tap", "cta": "Get Orbit"},
 "alt": "Coral and blue Orbit disc on a navy-to-grey studio gradient",
 "variants": {"b": {"variable": "headline", "headline": "Meet Orbit 2"}},
 "placements": [
  {"name": "yt",     "w": 1280, "h": 720},
  {"name": "og",     "w": 1200, "h": 630,  "safe": {"left": 0.05, "right": 0.05, "top": 0.05, "bottom": 0.05}},
  {"name": "square", "w": 1080, "h": 1080, "safe": {"left": 0.125, "right": 0.125}, "anchor": [0.5, 0.42]},
  {"name": "feed",   "w": 1080, "h": 1350, "safe": {"left": 0.031, "right": 0.031}, "fill": 0.56},
  {"name": "story",  "w": 1080, "h": 1920, "safe": {"top": 0.14, "bottom": 0.35, "left": 0.06, "right": 0.06},
   "fill": 0.74, "anchor": [0.5, 0.64]},
  {"name": "mrec",   "w": 300,  "h": 250,  "safe": {"left": 0.04, "right": 0.04, "top": 0.04, "bottom": 0.04},
   "alt": "Orbit 2 disc with Get Orbit button"}
 ]}
```

Placement names must not contain underscores (they are a field of the file name). A
placement-level `alt` overrides the kit-level one in the manifest.

## 5. Choosing the master aspect

| Kit contents | Master |
|---|---|
| social only (4:5, 1:1, 9:16) | 4:5 or 3:4 at the largest tier: vertical placements crop, the rare landscape one outpaints |
| social + OG + YouTube | 16:9: landscape crops, verticals outpaint top and bottom |
| banner-heavy (728 x 90, 970 x 250) | 21:9 or wider (Nano Banana 2.1 reaches 8:1), or a dedicated banner master from the same seed and hero reference |
| product cut-outs on brand colour | a transparent product asset (`image_generate_transparent` or `image_remove_background`) composited on flat grounds per placement: no outpaint needed |

Rule of thumb: pick the master aspect that minimises the largest `new_area_share` across the
kit; run `kitcheck plan` with two candidate masters (edit `w`, `h` and `focus`) before generating.
