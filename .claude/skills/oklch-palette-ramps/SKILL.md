---
name: oklch-palette-ramps
description: "Colour palette construction in OKLCH: brand hex to gamut-safe 11-step ramps (CSS Color 4 gamut mapping, optional Display P3 tier), tinted neutrals, semantic and state colours, dark-theme palettes, harmony schemes and categorical sets, every step annotated with measured WCAG contrast, shipped as a palette table, CSS custom properties and DTCG tokens. Load when building, extending or fixing a palette."
when_to_use: "Turning a brand hex into tints and shades, a ramp that looks uneven or muddy, a brand colour that fails contrast as text or as a fill, adding success/warning/danger/info colours, a dark theme, a chart colour set, oklch(), color-mix() or relative colour syntax in CSS, or writing colour tokens."
---

# OKLCH palette ramps

A palette is done when every colour has a role, every intended foreground/background pair has a
measured WCAG ratio, every value is inside the sRGB gamut (with an optional P3 tier), and the
result ships as a table, CSS custom properties and DTCG tokens. Ramps are built in OKLCH because
its L axis is perceptual; contrast is still measured in WCAG luminance, never inferred from L.

Tool (stdlib, deterministic): [oklch.py](scripts/oklch.py). Deep material:
[gamut mapping and cusp tables](references/gamut-and-cusps.md) |
[complete example palette](references/palette-example.md).

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
OK="$STACK/.claude/skills/oklch-palette-ramps/scripts/oklch.py"
python3 -I "$OK" info '#E94560'                    # OKLab, OKLCH, relative luminance
python3 -I "$OK" pairs '#FFFFFF/#D63151' '#EC4862/#1A1A2E'   # every intended pair
python3 -I "$OK" sweep '#E94560' --bg '#1A1A2E' --lo 0.56 --hi 0.70 --step 0.01
python3 -I "$OK" ramp '#E94560' --name pink --surfaces '#121212,#F7F7F8' --p3-peak-c 0.23
python3 -I "$OK" ramp '#E94560' --name pink --format css   # or json, dtcg (DTCG tokens)
python3 -I "$OK" map 0.70 0.30 145 --gamut srgb|p3  # CSS Color 4 gamut mapping
```

## 1. Why OKLCH, and what CSS supports

| Space | Lightness axis | Consequence for ramps |
|---|---|---|
| HSL | `l` is not perceptual: HSL yellow and blue at l=50% differ hugely in luminance | equal HSL steps look uneven; hue drifts when darkening |
| CIELCh | perceptual-ish, but blue hues shift toward purple as chroma drops | blue ramps turn violet |
| OKLCH (Ottosson 2020) | L 0..1 tracks perceived lightness; hue holds when chroma changes | equal L steps look evenly spaced; chroma can be tapered without hue drift |

CSS (all evergreen engines):

| Feature | Status (Oct 2026) | Example |
|---|---|---|
| `oklch(L C H / a)` | Baseline 2023, widely available | `oklch(0.633 0.199 15.7)`; L as 0..1 or %, C about 0..0.4, H degrees |
| `color-mix(in oklch, ...)` | Baseline 2023, widely available | `color-mix(in oklch, var(--pink-500) 80%, white)` |
| Relative colour syntax | Baseline 2024 (Chrome/Edge 119, Firefox 128, Safari 18) | `oklch(from var(--brand) calc(l - 0.1) c h)` |
| `@media (color-gamut: p3)` | widely supported | gate the P3 tier |
| `color(display-p3 r g b)` | widely supported | explicit P3 values |

Relative syntax rules: channel keywords resolve to numbers (`l` 0..1 for oklch, so write
`calc(l - 0.1)`, not `- 10%`); hue `h` is degrees. Guard with a literal colour, never `var()`,
inside `@supports`: `@supports (color: oklch(from red l c h)) { ... }`. A relative colour can
leave the gamut (raising L at fixed C): pre-compute shipped tokens instead of deriving them live.

## 2. The converter and gamut mapping

The tool carries the reference maths (identical to the graphic-design hub's former colour
reference, extended):

```text
linear(c) = c <= 0.04045 ? c/12.92 : ((c + 0.055)/1.055)^2.4          sRGB decode, c in 0..1
Y = 0.2126 R + 0.7152 G + 0.0722 B                                     WCAG relative luminance
ratio = (Y_lighter + 0.05) / (Y_darker + 0.05)                         1..21
OKLab: LMS = M1 * linear_rgb; L,a,b = M2 * cbrt(LMS); C = hypot(a,b); h = atan2(b,a)
deltaE_OK = Euclidean distance in OKLab (one JND is about 0.02)
```

Gamut mapping: an OKLCH colour with too much chroma for sRGB must lose chroma, not be clipped
per channel. Clipping changes the proportions of R, G and B and shifts hue (orange goes yellow,
blue goes purple). CSS Color 4 (section 14.2) allows three algorithms (binary search with local
MINDE, EdgeSeeker, ray trace); the tool implements the binary search:

| Step | Rule |
|---|---|
| L >= 1 / L <= 0 | return white / black |
| already in gamut | return it |
| clip once | if deltaE_OK(clipped, origin) < JND (0.02), return clipped |
| bisect chroma | min 0, max C, epsilon 0.0001; in-gamut midpoint raises min; otherwise clip and compare: < JND moves min (returns when JND - E < epsilon), >= JND lowers max |
| end | return the last clipped colour |

Python alternative with a library: `coloraide` (`uv add coloraide` in a project that needs it):
`Color('oklch(0.97 0.12 15)').fit('srgb', method='oklch-chroma')` is the CSS Color 4 MINDE
method (JND 0.02); plain `fit('srgb')` uses ColorAide's default (ray trace), and
`to_string(hex=True)` fits by default. Do not rely on the browser: engines have historically
clipped out-of-gamut colours at display time, so ship values that are already in gamut.

## 3. Ramp procedure (steps 50-950)

1. Convert the brand hex: `info`. Note L, C, h. Find the hue's cusp (lightness of maximum chroma)
   in the cusp table: yellow h~105 peaks at L 0.935, blue h~265 at L 0.455.
2. Target L per step (sRGB ramp; the anchor step takes the brand's own L):

| Step | 50 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900 | 950 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Target L | 0.97 | 0.93 | 0.87 | 0.79 | 0.71 | 0.63 | 0.55 | 0.47 | 0.39 | 0.31 | 0.25 |
| Chroma taper x peak C | 0.10 | 0.22 | 0.42 | 0.66 | 0.88 | 1.00 | 1.00 | 0.92 | 0.80 | 0.66 | 0.52 |

3. Anchor: the brand colour replaces the step with the nearest target L (`*` in the table
   output); `--no-anchor` keeps a pure ramp and leaves the brand as its own token.
4. Hue: fixed by default. Yellows and oranges turn olive or brown in the shades; rotate toward red
   as L falls (`--hue-shift -20` to `-30`). Tailwind v4's own yellow ramp does this (h 102 at 50,
   54 at 950). Blues may rotate slightly toward 265-270 in shades.
5. Gamut-map every step to sRGB (automatic). Extreme steps lose chroma (pink-50 asked 0.020, got
   0.016): expected, and the reason the taper exists.
6. Optional P3 tier: `--p3` maps the same targets into Display P3; `--p3-peak-c 0.23` gives the
   P3 tier more chroma while the sRGB tier (and the pinned brand hex) stays unchanged. `--peak-c`
   changes the sRGB tier and unpins the brand step.

```css
:root { --pink-600: #CB2449; }                                  /* sRGB, always present */
@media (color-gamut: p3) { :root { --pink-600: oklch(0.550 0.230 15.7); } }   /* --p3-peak-c 0.23 */
```

Measured result for `ramp '#E94560' --surfaces '#1A1A2E,#F7F7F8'` (ratios: white, black, navy):

| Step | Hex | oklch() | vs white | vs black | vs #1A1A2E |
|---|---|---|---|---|---|
| 50 | #FFF0F1 | 0.967 0.016 15.2 | 1.11 deco | 18.99 text | 15.42 text |
| 200 | #FFBEC2 | 0.862 0.075 15.1 | 1.57 deco | 13.42 text | 10.90 text |
| 400 | #FB6B7C | 0.710 0.176 15.7 | 2.79 deco | 7.52 text | 6.11 text |
| 500* | #E94560 | 0.633 0.199 15.7 | 3.83 ui | 5.48 text | 4.46 ui |
| 600 | #CB2449 | 0.550 0.199 15.7 | 5.40 text | 3.89 ui | 3.16 ui |
| 700 | #A90936 | 0.470 0.184 15.7 | 7.55 text | 2.78 deco | 2.26 deco |
| 900 | #620018 | 0.315 0.126 17.3 | 13.69 text | 1.53 deco | 1.25 deco |

All 11 steps: [palette example](references/palette-example.md).

## 4. Contrast annotation

| Class | Rule (WCAG 2.2) | Use |
|---|---|---|
| text | >= 4.5:1 (1.4.3 AA) | body text, labels, links |
| large / ui | >= 3:1 | text >= 24 px regular or >= 18.66 px bold; UI boundaries, icons, focus rings (1.4.11) |
| deco | < 3:1 | backgrounds, tints, illustration only |
| AAA | >= 7:1 (4.5:1 large) | when the brief asks for 1.4.6 |

Annotate each step against white, black, the darkest and the lightest surface (`--surfaces`).
Then list the pairs the design actually uses and run `pairs` on all of them. Step distance is not
contrast: neutral-500 (#908687) on white is 3.52 but pink-500 is 3.83 and an unshifted
yellow-500 3.43; the same step number differs per hue because WCAG luminance is not OKLCH L.

## 5. Tinted neutrals and semantic colours

Neutrals: constant chroma 0.005-0.02 at the brand hue (`ramp '#E94560' --neutral 0.012`): warm
or cool greys read as intentional. Measured: neutral-600 #786F6F 4.88 on white, neutral-900
#362E2E 13.23.

Semantic roles: hues far apart, lightness equal per role so no state shouts louder. Measured at
L 0.52, C <= 0.15 (fills with white text, or text on white) and L 0.95, C 0.04 (tints):

| Role | OKLCH h | Fill / text | White on fill | Tint | Fill on tint | Dark-mode text (L 0.80) on #121212 |
|---|---|---|---|---|---|---|
| success | 145 | #1B7E2A | 5.17 | #DFF6DE | 4.52 | #86D489 10.50 |
| warning | 75 | #935B00 (text only) | 5.61 | #FFEBD2 | 4.84 | #EEB154 9.86 |
| danger | 25 | #AF3C3A | 5.95 | #FFE5E1 | 4.96 | #FF9B93 9.25 |
| info | 250 | #006BBB | 5.51 | #DBF1FF | 4.74 | #7BC3FF 9.92 |

Warning is the exception: an amber fill #F9AD26 (L 0.80) carries dark text (#271F20 on it 8.43);
white on amber is 1.91. Amber at L 0.52 is brown, so use it for warning text only. Equal L still
gives 5.17-5.95: measure. Pair every state colour with an icon or label (WCAG 1.4.1).

## 6. Harmony schemes and proportion

| Scheme | Construction (OKLCH h) | Feel / use |
|---|---|---|
| Monochromatic | one h, L and C steps | calm, premium, safest for UI |
| Analogous | hues within 30-60 degrees | harmonious, natural |
| Complementary | h + 180 | high energy; one dominant, one accent |
| Split-complementary | h, h + 150, h + 210 | contrast with less tension |
| Triadic | h, h + 120, h + 240 | playful; mute two of the three |

Relative syntax builds them live (`oklch(from var(--base) l c calc(h + 120))`) for exploration;
ship measured values. Proportion: ~60% neutral ground, ~30% secondary, ~10% accent (60-30-10) as a
starting point; the accent's rarity is what makes it signal.

## 7. Worked example: one brand colour, two roles

Brief: brand pink #E94560 on a navy page #1A1A2E; it must work as accent text on navy and as a
button fill behind white text. Measure first:

```bash
python3 -I "$OK" pairs '#E94560/#1A1A2E' '#FFFFFF/#E94560'
# #E94560 on #1A1A2E  4.46:1  ui      -> fails 1.4.3 text by 0.04
# #FFFFFF on #E94560  3.83:1  ui      -> fails for normal text; passes only >= 18.66 px bold
```

One value cannot do both: as text on dark it must get lighter, as a fill under white it must get
darker. Sweep L at the brand's own C and h:

```bash
python3 -I "$OK" sweep '#E94560' --bg '#1A1A2E' --lo 0.62 --hi 0.66 --step 0.01
# L=0.63 #E8445F 4.41:1   L=0.64 #EC4862 4.59:1 text
python3 -I "$OK" sweep '#E94560' --bg '#FFFFFF' --lo 0.57 --hi 0.60 --step 0.01
# L=0.58 #D63151 4.76:1 text   L=0.59 #DA3554 4.56:1 text   L=0.60 #DD3957 4.38:1
```

Choose the smallest move that passes (keeps the brand look), then re-measure the rounded hex,
because the sweep reports the unrounded colour:

```bash
python3 -I "$OK" pairs '#EC4862/#1A1A2E' '#FFFFFF/#D63151'
# #EC4862 on #1A1A2E  4.61:1  text     (sweep said 4.59)
# #FFFFFF on #D63151  4.75:1  text     (sweep said 4.76)
```

| Token | Value | oklch() | Pair | Ratio | Allowed |
|---|---|---|---|---|---|
| `color.pink.500` (primitive) | #E94560 | 0.633 0.199 15.7 | white on it 3.83 | | decoration, large bold |
| `color.accent.on-dark` | #EC4862 | 0.641 0.199 15.9 | on #1A1A2E | 4.61 | text and icons on navy |
| `color.accent.fill` | #D63151 | 0.580 0.199 15.7 | white on it | 4.75 | buttons, badges with white labels |

Alternative when a ramp exists: snap to steps (pink-400 #FB6B7C on navy 6.11; white on pink-600
#CB2449 5.40); larger visual change, simpler system. Dark theme (section 8): accent text on
#121212 becomes oklch(0.70 0.16 15.7) #F16F7D, 6.51:1, chroma cut by 20%.

## 8. Dark theme as its own mapping

| Role | Light theme | Dark theme | Measured (dark) |
|---|---|---|---|
| surface-0 (page) | #FFFFFF | #121212 to #151010 (L 0.18, C 0.008 brand-tinted) | |
| surface-1..3 (elevation) | shadows | lighter surfaces: L 0.215 #1D1818, 0.245 #241F1F, 0.275 #2B2626 | |
| body text | neutral-900 | #E6E6E6 (not #FFFFFF) | 15.01 on #121212, 13.36 on #1E1E1E, 11.92 on #2B2626 |
| accent text | #EC4862 | #F16F7D (L 0.70, C 0.16) | 6.51 on #121212, 5.17 on #2B2626 |
| borders | neutral-200 | neutral at L 0.35-0.40 | >= 3:1 where they identify a control |

Rules: never invert (inversion turns shadows into glows and pastel tints into mud); elevation is
shown by lighter surfaces, not shadows; reduce brand chroma 10-25% (saturated colours vibrate on
dark); pure white on pure black causes halation for long reading; re-measure every pair on every
elevation (accent L 0.66 passes on #121212 at 5.54 but fails on #2B2626 at 4.40).

## 9. Categorical sets

Okabe-Ito (colour-blind safe), measured:

| Colour | Hex | OKLCH L | vs white | vs #121212 |
|---|---|---|---|---|
| orange | #E69F00 | 0.753 | 2.25 | 8.32 |
| sky blue | #56B4E9 | 0.735 | 2.31 | 8.12 |
| bluish green | #009E73 | 0.620 | 3.42 | 5.48 |
| yellow | #F0E442 | 0.902 | 1.32 | 14.17 |
| blue | #0072B2 | 0.532 | 5.19 | 3.61 |
| vermillion | #D55E00 | 0.621 | 3.87 | 4.84 |
| reddish purple | #CC79A7 | 0.679 | 3.06 | 6.12 |
| black | #000000 | 0.000 | 21.00 | 1.12 |

Canonical order puts near-equal L next to each other (orange/sky blue differ by 0.018). Order
series so neighbours differ by >= 0.10-0.15 L: sky blue, blue, reddish purple, yellow, bluish
green, orange, vermillion has a minimum neighbour spread of 0.13 (found by brute force over the
7! orders). On white, orange, sky blue and yellow fail 3:1 for marks (1.4.11): outline them, use
a dark background, or label directly. More than 7 categories: group or facet instead.
Sequential and diverging scales (single-hue OKLCH ramps, viridis, midpoints): `chart-design-encoding`.

## 10. Deliverable

1. Palette table: token, hex, oklch(), ratio vs white / black / each surface, allowed roles.
2. CSS custom properties: `ramp --format css` (sRGB plus the `@media (color-gamut: p3)` block
   with `--p3`), semantic tokens as `var()` aliases of primitives.
3. DTCG 2025.10 tokens (`ramp --format dtcg`): `$type: color` on the group, each `$value` an
   object `{colorSpace: "oklch", components: [L, C, h], hex}` (hex is the optional fallback);
   semantic tokens alias primitives (`"$value": "{color.pink.600}"`). Tiers, modes and builds:
   `design-tokens-dtcg`.
4. A pairs report (the `pairs` output) for the accessibility statement; full audits:
   `visual-accessibility-audit`.

## Pitfalls

- HSL or RGB-lerp ramps: uneven perceived steps, hue drift in shades; rebuild in OKLCH.
- Pure yellow text on white (#FFFF00 1.07:1); yellow and amber are fills with dark text.
- Red/green pairs at equal L: oklch(0.6 0.15 25) #CA5551 vs oklch(0.6 0.15 145) #3A9742 measure
  1.14:1 against each other, indistinguishable for red-green CVD; vary L and add icons.
- Inferring contrast from step numbers or from L; measure the shipped (rounded) hex.
- Out-of-gamut chroma at extreme steps clipped per channel: hue shift; gamut-map instead.
- Saturated RGB brand colours with no CMYK or spot note: vivid pinks, blues and greens fall
  outside coated CMYK; flag them and hand off to `print-prepress-pdfx` and the colour spec in
  `brand-guidelines-system`.
- A dark theme made by inverting, or light-theme chroma carried into dark mode.
- Relative-colour tokens computed at runtime that leave the gamut; ship computed values.

Related: `design-tokens-dtcg`, `visual-accessibility-audit`, `chart-design-encoding`,
`brand-guidelines-system`, `print-prepress-pdfx`, `type-scale-systems`, hub `graphic-design`.
