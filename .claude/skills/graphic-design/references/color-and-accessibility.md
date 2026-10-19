# Color and accessibility reference

## 1. Contrast and OKLCH tool (stdlib Python)

Save under your out_dir and run with `python3 -I contrast.py '#E94560' '#1A1A2E'`. Values in
SKILL.md section 5 were computed with exactly this code.

```python
import math, sys

def lin(c): return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
def enc(c):
    c = min(max(c, 0.0), 1.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
def rgb(h): h = h.lstrip("#"); return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
def hexs(v): return "#" + "".join("%02X" % round(c * 255) for c in v)
def lum(v): r, g, b = map(lin, v); return 0.2126 * r + 0.7152 * g + 0.0722 * b
def contrast(a, b):
    la, lb = lum(a), lum(b); return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

def to_oklab(v):
    r, g, b = map(lin, v)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)

def from_oklab(L, a, b):
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return [enc(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
            enc(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
            enc(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)]

if __name__ == "__main__":
    fg, bg = rgb(sys.argv[1]), rgb(sys.argv[2])
    print("contrast %.2f:1" % contrast(fg, bg))
    L, a, b = to_oklab(fg)
    print("fg oklch L=%.3f C=%.3f h=%.1f" % (L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360))
    for t in [x / 100 for x in range(30, 96, 2)]:          # lightness sweep at fixed hue/chroma
        v = from_oklab(t, a, b)
        print("L=%.2f %s %.2f:1" % (t, hexs(v), contrast(v, bg)))
```

Note: `enc` clips out-of-gamut channels, which shifts hue at extreme lightness/chroma; for
production ramps reduce chroma until the color is in gamut instead (CSS Color 4 gamut mapping).

## 2. Building a palette ramp

1. Start from the brand hex; convert to OKLCH.
2. Generate 10-12 steps at fixed hue: L from ~0.97 (tint) to ~0.25 (shade). Reduce chroma toward
   both ends (tints and shades cannot hold full chroma in sRGB).
3. Name steps 50-950 (or 1-12); record which steps pass 4.5:1 on white and on your darkest surface.
4. Neutrals: same procedure with chroma 0.005-0.02 tinted toward the brand hue (warmer or cooler
   grays look intentional).
5. Semantic colors (success, warning, danger, info): pick hues far apart (≈ 145°, 75°, 25°, 250°
   in OKLCH), equalise lightness per role so no state shouts louder than another.
6. Data-viz categorical set: 6-8 hues with distinct lightness as well as hue; Okabe-Ito is a
   tested colour-blind-safe set: #E69F00 #56B4E9 #009E73 #F0E442 #0072B2 #D55E00 #CC79A7 #000000.

Harmony schemes as starting points (adjust by eye and by measurement):

| Scheme | Construction | Feel / use |
|---|---|---|
| Monochromatic | one hue, lightness/chroma steps | calm, premium, safest for UI |
| Analogous | hues within ~30-60° | harmonious, natural |
| Complementary | opposite hues (~180°) | high energy; use one dominant, one accent |
| Split-complementary | base + two hues at ±150° | contrast with less tension |
| Triadic | three hues 120° apart | playful; hard to keep balanced, mute two |

## 3. WCAG 2.2 checks beyond text contrast

| SC | Level | Check |
|---|---|---|
| 1.4.1 Use of color | A | links in body text distinguishable without color (underline) or 3:1 against surrounding text plus a non-color cue on focus/hover |
| 1.4.3 / 1.4.6 Contrast | AA / AAA | 4.5:1 / 7:1 text, 3:1 / 4.5:1 large text; text over images measured at the worst point (use a scrim) |
| 1.4.10 Reflow | AA | content works at 320 CSS px width without 2D scrolling |
| 1.4.11 Non-text contrast | AA | input borders, icons conveying meaning, focus rings, chart elements 3:1 |
| 1.4.12 Text spacing | AA | layout survives user spacing overrides |
| 2.4.7 Focus visible | AA | every focusable element shows focus |
| 2.4.11 Focus not obscured (minimum) | AA | focused element not entirely hidden by sticky headers/overlays |
| 2.5.8 Target size (minimum) | AA | ≥ 24 × 24 CSS px or spacing equivalent |
| 2.3.3 Animation from interactions | AAA | honour `prefers-reduced-motion` anyway |
| 1.1.1 Non-text content | A | meaningful images have alt text; decorative ones `alt=""` |

Text over photos: measure contrast against the lightest (for light text) region under the text;
add a gradient scrim or solid panel until the worst point passes.

APCA (the candidate contrast method for WCAG 3) is a draft and not a conformance requirement;
it can be used as an additional perceptual check (higher |Lc| for thin/small text), never as a
replacement for the WCAG 2.x ratio when conformance is required.

## 4. Color vision deficiency and dark mode

- Simulate protanopia, deuteranopia, tritanopia, achromatopsia: Chrome DevTools (Rendering →
  Emulate vision deficiencies), Color Oracle (desktop), or `colorspacious` CVD transforms in Python.
- Rule: categories must differ in lightness by ≥ ~10-15 OKLCH L units, or carry labels/patterns.
- Red/green status pairs: add icons (check, cross), position or text.
- Dark mode: surface #121212-#1E1E1E range, elevation by lighter surfaces, body text ~#E6E6E6
  (avoid pure white on pure black for long text: halation for astigmatic readers), brand colors
  lightened and desaturated, shadows replaced by borders or lighter surfaces; re-measure all pairs.

## 5. Print color

- Convert with ICC profiles supplied by the printer (FOGRA39/FOGRA51 for European coated offset,
  GRACoL 2013 / SWOP for US); rendering intent relative colorimetric with black point compensation
  for brand colors and vectors, perceptual for photographs with out-of-gamut content.
- Total area coverage (TAC): stay under the printer's limit, typically 300-330% coated, 260-300%
  uncoated, ~240% newsprint. Rich black example: C60 M40 Y40 K100 (240%) for large areas; small
  text and thin lines in 100K only (registration risk); never use "registration" color
  (C100 M100 Y100 K100) for artwork.
- Black text overprints by default in most RIPs; check that light objects are not set to overprint
  (they disappear).
- sRGB colors that do not survive CMYK: saturated RGB blues, greens, oranges and violets; soft-proof
  with gamut warning and choose a spot color (Pantone Coated/Uncoated books differ visibly) when
  the brand color is critical.
- Images: 300 ppi at final size, CMYK conversion at export (PDF/X-4 keeps RGB with output intent;
  let the printer's workflow convert when they ask for it).
- Paper changes color: uncoated stock darkens and dulls (dot gain); proof on the actual stock for
  brand-critical work.

## 6. Accessibility report template

| Pair (fg / bg) | Usage | Size/weight | Ratio | Target | Pass |
|---|---|---|---|---|---|
| #FFFFFF / #1A1A2E | body text | 18 px 400 | 17.06 | 4.5 | yes |
| #EC4862 / #1A1A2E | accent text | 18 px 600 | 4.59 | 4.5 | yes |
| #FFFFFF / #D63151 | button label | 16 px 600 | 4.75 | 4.5 | yes |
| #9CA3AF / #FFFFFF | input border | 1 px | 2.54 | 3.0 | no → use #6B7280 (4.83) |
