---
name: type-scale-systems
description: "Typography systems: modular scale choice, role table, measure/leading/tracking rules, pairing tests with measured x-heights, fluid clamp() type with a generator, variable and web-font loading (WOFF2 subsets, preload) without layout shift (metric-matched fallbacks), OpenType features, print type settings, multilingual rules, licensing and a critique checklist. Load when defining, implementing or auditing a type system for screen or print."
when_to_use: "Choosing type sizes or a scale, writing font-size/line-height tokens, clamp() fluid type, pairing two families, @font-face and font loading, CLS caused by web fonts, pyftsubset or fonttools varLib.instancer, tabular numbers, text-wrap, hyphenation, print body settings, CJK/Arabic/RTL text, or a font licence question."
---

# Type scale systems

A type system is done when every size on screen comes from a declared scale, every role has size,
weight, line-height and tracking, body text sits at 45-75 characters, fonts load without layout
shift, and every family is licensed for every medium it ships in.

Scripts: [typescale.py](scripts/typescale.py) (fluid scale to CSS custom properties) and
[fallback_css.py](scripts/fallback_css.py) (metric-matched fallback @font-face). Deep material:
[font loading and CLS](references/font-loading.md) |
[print, multilingual, licensing](references/print-multilingual-licensing.md).

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
T="$STACK/.claude/skills/type-scale-systems/scripts"
python3 -I "$T/typescale.py" --min-w 360 --max-w 1440 --min-ratio 1.2 --max-ratio 1.25 --steps=-1..5
python3 -I "$T/fallback_css.py" Inter Arial
```

## 1. Modular scale

`size_k = base x r^k`, rounded to 0.5 px (half up). From a 16 px base:

| Ratio | Name | k = -2 .. 6 | Levels that stay usable | Medium |
|---|---|---|---|---|
| 1.125 | major second | 12.5, 14, 16, 18, 20.5, 23, 25.5, 29, 32.5 | 6-8 | dense UI, dashboards |
| 1.200 | minor third | 11, 13.5, 16, 19, 23, 27.5, 33, 40, 48 | 6-7 | apps, docs, mobile |
| 1.250 | major third | 10, 13, 16, 20, 25, 31.5, 39, 49, 61 | 5-6 | websites (default) |
| 1.333 | perfect fourth | 9, 12, 16, 21.5, 28.5, 38, 50.5, 67.5, 90 | 5 | editorial, marketing |
| 1.414 | augmented fourth | 8, 11.5, 16, 22.5, 32, 45, 64, 90.5, 128 | 4-5 | landing pages |
| 1.500 | perfect fifth | 7, 10.5, 16, 24, 36, 54, 81, 121.5, 182.5 | 4 | posters, heroes |
| 1.618 | golden | 6, 10, 16, 26, 42, 68, 109.5, 177.5, 287 | 3-4 | display-heavy, few levels |

Choice: more hierarchy levels need a smaller ratio; small screens need a smaller ratio than large
ones (a 1.333 H1 at 50.5 px does not fit a 360 px phone). Two-ratio approach: 1.2 on mobile,
1.25-1.333 on desktop, interpolated with clamp() (section 4). Steps below 12 px are not used on
screen.

## 2. Role table

Line-heights snap to a multiple of 4 px so baselines land on the 4 px spacing grid. Defaults for
a 16 px body:

| Role | Step | Size px | Weight | Line-height | Tracking |
|---|---|---|---|---|---|
| Display | 5-6 | 40-61 | 700-800 | 1.0-1.1, snapped (49 px / 52) | -2% to -3% (`-0.02em`) |
| H1 | 4 | 33-39 | 700 | 1.1-1.25 (39 / 48) | -1.5% |
| H2 | 3 | 27.5-31.5 | 600 | 1.2-1.3 (31.5 / 40, rounded up) | -1% |
| H3 | 2 | 23-25 | 600 | 1.25-1.3 (25 / 32) | 0 |
| Lead / H4 | 1 | 19-20 | 500-600 | 1.4 (20 / 28) | 0 |
| Body | 0 | 16-18 | 400 | 1.5 (16 / 24) | 0 |
| Small / meta | -1 | 13-14 | 400-500 | 1.45-1.55 (13 / 20) | +0.5% |
| Caps label / overline | fixed | 12 | 600 | 16 px | +8% (`0.08em`), uppercase |
| Code | 0.875em | 14 | 400 | 20 px inline, 24 px blocks | 0 |

Fluid sizes snap with CSS `round()` (Baseline 2024): `line-height: round(up, 1.2em, 4px);`. A
length line-height inherits as a fixed length, so set it on each role, and keep body text
unitless (`line-height: 1.5`) where children change size.

## 3. Rules

| Parameter | Rule | Check |
|---|---|---|
| Measure | 45-75 characters, 66 ideal; 30-40 in narrow columns and on phones | `max-width: 66ch` on text blocks |
| Body leading | 1.4-1.6; longer lines need more | 1.5 at 16 px = 24 px |
| Heading leading | 1.05-1.25; display tighter | no ascender/descender collisions in two-line headings |
| Tracking | display -1% to -3%; caps and small labels +5% to +12%; body 0 | never track lowercase body text |
| Sizes | web body >= 16 px; UI labels >= 12 px; print body 9-11 pt | test on the device at arm's length |
| Families | <= 2 families (one superfamily is often enough), 3-4 weights | each weight has a role |
| Paragraphs | indent or space, never both; left aligned on screen | no justified text without hyphenation |

## 4. Fluid type with clamp()

From size s1 at viewport w1 to s2 at w2 (px):

```text
slope = (s2 - s1) / (w2 - w1)              -> preferred vw term = slope x 100
intercept = s1 - slope x w1                -> rem term = intercept / 16
font-size: clamp(min(s1,s2)/16 rem, intercept/16 rem + slope x 100 vw, max(s1,s2)/16 rem)
```

Worked: 32 px at 360 to 56 px at 1440: slope = 24/1080 = 0.02222 (2.222vw), intercept =
32 - 0.02222 x 360 = 24 px = 1.5rem, so `clamp(2rem, 1.5rem + 2.222vw, 3.5rem)`; at 900 px it
gives 24 + 20 = 44 px. Keep a rem term: a pure `vw` size ignores browser zoom and text-size
settings and fails WCAG 1.4.4 (resize text to 200%). Check that 200% zoom still grows the text
(the rem part doubles; the vw part does not) and that min and max are in rem.

Generator (Utopia-style: each step interpolates between a mobile scale and a desktop scale):

```bash
python3 -I "$T/typescale.py" --min-w 320 --max-w 1240 --min-base 18 --max-base 20 \
  --min-ratio 1.2 --max-ratio 1.25 --steps=0..2 --round 0.0001
# --step-0: clamp(1.125rem, 1.0815rem + 0.2174vw, 1.25rem); /* 18 -> 20 px */
```

Negative steps can shrink as the ratio grows (16/1.2 = 13.3 on mobile, 16/1.25 = 12.8 on
desktop); the generator orders min and max and emits a negative slope.

## 5. Pairing

OFL catalogue with metrics (from @capsizecss/metrics 4.4.0; x = sxHeight / unitsPerEm):

| Family | Classification | x-height | cap height | Pairs well with |
|---|---|---|---|---|
| Inter | neo-grotesque sans (opsz 14-32, wght 100-900) | 0.546 | 0.728 | Source Serif 4, Literata, Fraunces (display) |
| IBM Plex Sans / Serif | grotesque / transitional serif superfamily | 0.516 / 0.516 | 0.698 | each other, IBM Plex Mono |
| Source Sans 3 | humanist sans | 0.486 | 0.660 | Source Serif 4 (matched design) |
| Source Serif 4 | transitional serif with opsz | 0.475 | 0.670 | Source Sans 3, Inter (size up) |
| Fraunces | soft old-style display serif (wonk axis) | 0.482 | 0.700 | Inter or Source Sans 3 for body |
| Literata | book serif with opsz | 0.507 | 0.701 | Inter, Source Sans 3 |
| Noto Sans / Serif | humanist sans / serif, near-universal script coverage | 0.536 / 0.536 | 0.714 | each other, per script |

Measure any font yourself (fontTools; does not touch the project environment):

```bash
uv run --no-project --with fonttools python -I -c "
from fontTools.ttLib import TTFont; import sys
f = TTFont(sys.argv[1]); upm = f['head'].unitsPerEm; os2 = f['OS/2']
print('x %.3f cap %.3f' % (os2.sxHeight / upm, os2.sCapHeight / upm))" MyFont.ttf
```

Tests: (1) x-heights within about 5% at the same font-size, else size the second family up or
down, or use `font-size-adjust: ex-height 0.546` on it (Baseline 2024): Inter 0.546 next to
Source Serif 4 0.475 is a 1.149 ratio, so the serif reads equal at 18.4 px beside 16 px Inter.
(2) Contrast in classification (serif with sans, humanist with geometric), similar proportions
(wide with wide). (3) The weights cover the role table. (4) Set headline + paragraph + caption in
both and look at real copy. Never pair two similar grotesques (Inter with Roboto, Helvetica with
Arial): they look like a mistake, not a pairing.

## 6. Web-font loading

| Rule | Detail |
|---|---|
| WOFF2 only | every evergreen browser supports it; drop TTF/WOFF fallbacks |
| Subset per script | `pyftsubset` with `--unicodes` per script plus `unicode-range` in @font-face, so a page downloads only the scripts it uses |
| Keep layout features | pyftsubset keeps only calt, ccmp, clig, curs, dnom, frac, kern, liga, locl, mark, mkmk, numr, rclt, rlig, rvrn (plus shaping features) by default: add what the CSS uses (`--layout-features+=tnum,lnum,case,ss01,zero`) or tabular figures silently disappear |
| Variable fonts | one file for wght 400-700 (and opsz) instead of 3-4 statics; limit axes with `fonttools varLib.instancer in.ttf wght=400:700 -o out.ttf`; declare `font-weight: 400 700`; `font-optical-sizing: auto` (the initial value; only needed to undo `none`) |
| Preload | only the 1-2 files used above the fold: `<link rel="preload" href="/fonts/inter-latin.woff2" as="font" type="font/woff2" crossorigin>` (crossorigin even on same origin) |
| font-display | `swap` for text faces (paired with a metric-matched fallback); `optional` for non-critical decorative faces |

```bash
uvx --from fonttools fonttools varLib.instancer inter-var.ttf wght=400:700 -o inter-400-700.ttf
uvx --from fonttools --with brotli pyftsubset inter-400-700.ttf \
  --unicodes="U+0000-00FF,U+0131,U+0152-0153,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2212" \
  --layout-features+=tnum,lnum,case,ss01,zero --flavor=woff2 --output-file=inter-latin.woff2
```

WOFF2 output needs the Brotli module (hence `--with brotli`). Self-host; third-party font CSS
adds a connection and hides the subset.

## 7. Layout-shift prevention

Text first paints in the fallback; when the web font swaps in, different widths re-wrap lines
and different vertical metrics move baselines: cumulative layout shift. Make the fallback measure
like the web font:

```text
size-adjust     = (font xWidthAvg / font upm) / (fallback xWidthAvg / fallback upm)
ascent-override = font ascent / (font upm x size-adjust)      (same for |descent|, lineGap)
```

```bash
python3 -I "$T/fallback_css.py" Inter Arial
# size-adjust: 107.12%; ascent-override: 90.44%; descent-override: 22.52%; line-gap-override: 0.00%
```

| Tool | Use |
|---|---|
| `fallback_css.py` | stdlib; built-in Capsize metrics for common families, `--metrics` JSON for others |
| Capsize `createFontStack` (`@capsizecss/core` + `@capsizecss/metrics/<font>`) | JS build step; returns `{ fontFamily, fontFaces }`; `@capsizecss/unpack` `fromFile` reads any font |
| fontaine (`FontaineTransform.vite({ fallbacks, resolvePath })`) | Vite/webpack plugin that writes the fallback @font-face and appends it to font-family |

Support: `size-adjust` is Baseline (Safari 17+); `ascent-override`, `descent-override` and
`line-gap-override` work in Chromium and Firefox but were missing from stable Safari through the
26.x releases (check caniuse). Set explicit line-heights on every role so the line box does not
depend on font ascent and descent; then size-adjust carries most of the benefit everywhere.
Verify with Lighthouse (Node 22+) and a box comparison: [font loading and CLS](references/font-loading.md).

## 8. OpenType features and CSS details

| Need | CSS | Feature |
|---|---|---|
| Tables, prices, timers | `font-variant-numeric: tabular-nums lining-nums` | tnum, lnum |
| Running text figures | `font-variant-numeric: oldstyle-nums proportional-nums` | onum, pnum |
| Caps and figures with punctuation | `font-feature-settings: "case" 1` | case |
| Stylistic set | `font-feature-settings: "ss01" 1` | ss01 |
| Slashed zero for codes | `font-variant-numeric: slashed-zero` | zero |
| Headlines | `text-wrap: balance` (Baseline 2024; Chromium balances <= 6 lines, Firefox <= 10) | |
| Paragraphs | `text-wrap: pretty` (progressive enhancement; avoids one-word last lines where supported) | |
| Hyphenation | `hyphens: auto` plus a correct `lang` attribute (no lang, no hyphenation) | |

`font-feature-settings` does not merge: a later rule replaces the whole list, so declare all
features in one place (or with custom properties). Prefer `font-variant-*` where one exists.
Typography marks: curly quotes and apostrophes, en dash for ranges (9-17 as 9–17), em dash or
spaced en dash for breaks, true ellipsis, non-breaking space before units (12 px).

## 9. Print settings

| Setting | Default |
|---|---|
| Body | 9-11 pt (books 10-12 pt), leading +2-4 pt: 10/13, 11/15 |
| Measure | 60-70 characters; columns >= 35 characters |
| Baseline grid | = body leading; headings on multiples or half-steps |
| Justification (word spacing) | min 80%, desired 100%, max 133%; letter spacing -2/0/+2%; glyph scaling 98/100/102% |
| Hyphenation | words >= 6 letters, >= 3 letters before and after, <= 2 consecutive hyphens |
| Reversed text | >= 8 pt, medium weight, no hairline serifs (ink spread fills counters) |
| Lines | >= 0.25 pt (0.1 mm) |
| Small caps and figures | true small caps (smcp) and oldstyle figures from the font, never synthesised |

Optical margin alignment (hanging punctuation) for justified body. Full table and press checks:
[print, multilingual, licensing](references/print-multilingual-licensing.md); press files:
`print-prepress-pdfx`.

## 10. Multilingual

- CJK: line-height 1.7-1.8; no italics (emphasis by weight or colour); no letter-spacing changes;
  line-breaking rules (kinsoku) left to the engine (`line-break: strict` for Japanese).
- Arabic: about 10-20% larger for equal legibility; no letter-spacing (breaks joining); RTL with
  `dir="rtl"` and logical properties (`margin-inline-start`), so layouts mirror without forking.
- RTL mirroring: mirror layout, back/forward arrows and progress direction; do not mirror clocks,
  media play buttons, logos, numbers or checkmarks.
- Expansion: translations run 20-35% longer than English (short UI strings more); size
  containers for +40% and test with real strings (German compounds, Finnish).
- Coverage: check every script in the copy deck against the font's cmap; Noto per script fills
  gaps.

## 11. Licensing and critique

| Medium | What the licence must allow | OFL |
|---|---|---|
| Desktop (design, print) | installation on N machines, PDF embedding | yes |
| Web | self-hosted @font-face, pageview limits, subsetting | yes |
| App embedding | bundling inside iOS/Android/desktop apps | yes |
| Broadcast / video | on-screen use in film, TV, ads | yes |
| Logo / wordmark | outlined letterforms in a registered mark; some commercial EULAs restrict or charge for it | yes (OFL FAQ: logos allowed) |

OFL fonts may not be sold on their own, and modified versions must drop any Reserved Font Name.
Commercial fonts: read the EULA per medium; record licence files in the brand `fonts/` folder.

Critique checklist (one line each, pass/fail):

1. Scale declared and followed: no ad-hoc sizes.
2. Body measure 45-75 characters.
3. Leading fits size and measure; headings tighter than body.
4. At most 2 families and 4 weights; each weight has a role.
5. Caps and small labels tracked out; display sizes tracked in.
6. Tabular figures in tables and changing numbers.
7. No widows or orphans in prominent text; headlines balanced; no rivers in justified text.
8. Typographic quotes, apostrophes and dashes.
9. Legible at actual size on the target device or print distance.
10. Fonts licensed for every medium.

## 12. Worked example: docs-site type system

Brief: documentation site, Inter for everything, body 16 px on every viewport, ratio 1.2 at
360 px rising to 1.25 at 1440 px, no layout shift from font loading.

```bash
python3 -I "$T/typescale.py" --min-w 360 --max-w 1440 --min-base 16 --max-base 16 \
  --min-ratio 1.2 --max-ratio 1.25 --steps=-1..5
```

```css
:root {
  --step-n1: clamp(0.8125rem, 0.8542rem - 0.0463vw, 0.8438rem); /* 13.5 -> 13 px */
  --step-0: 1rem;                                                /* 16 px */
  --step-1: clamp(1.1875rem, 1.1667rem + 0.0926vw, 1.25rem);    /* 19 -> 20 px */
  --step-2: clamp(1.4375rem, 1.3958rem + 0.1852vw, 1.5625rem);  /* 23 -> 25 px */
  --step-3: clamp(1.7188rem, 1.6354rem + 0.3704vw, 1.9688rem);  /* 27.5 -> 31.5 px */
  --step-4: clamp(2.0625rem, 1.9375rem + 0.5556vw, 2.4375rem);  /* 33 -> 39 px */
  --step-5: clamp(2.5rem, 2.3125rem + 0.8333vw, 3.0625rem);     /* 40 -> 49 px */
}
h1 { font: 700 var(--step-4)/1 "Inter", "Inter Fallback", sans-serif;
     line-height: round(up, 1.2em, 4px); letter-spacing: -0.015em; text-wrap: balance; }
h2 { font-size: var(--step-3); font-weight: 600; line-height: round(up, 1.25em, 4px); }
body { font: 400 var(--step-0)/1.5 "Inter", "Inter Fallback", sans-serif; }
main p, main li { max-width: 66ch; text-wrap: pretty; }
.overline { font-size: 0.75rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }
table { font-variant-numeric: tabular-nums lining-nums; }
```

Fonts: instancer to wght 400-700 (opsz kept), latin subset with tnum, lnum, case, ss01 and zero
(commands in section 6); one preload; fallback from `fallback_css.py Inter Arial` (section 7):

```css
@font-face { font-family: "Inter"; src: url("/fonts/inter-latin.woff2") format("woff2");
  font-weight: 400 700; font-display: swap;
  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02C6, U+02DA, U+02DC, U+2000-206F,
                 U+20AC, U+2122, U+2212; }
@font-face { font-family: "Inter Fallback"; src: local("Arial"), local("ArialMT");
  size-adjust: 107.12%; ascent-override: 90.44%; descent-override: 22.52%;
  line-gap-override: 0%; }
```

Tokens: steps go to `design-tokens-dtcg` as dimension tokens (rem) plus typography composites per
role. Acceptance: Lighthouse CLS reports 0.00 both with the WOFF2 blocked (fallback only,
`--blocked-url-patterns`) and with it loaded, and the before/after box heights of the first 20
text blocks match within 2 px (script in [font loading and CLS](references/font-loading.md)).
Then run the critique checklist at 360, 768 and 1440 px and at 200% zoom.

## Pitfalls

- Pure `vw` font sizes (fail 1.4.4) or clamp() min/max in px (ignore user font size).
- Ad-hoc sizes outside the scale (a 15 px label, a 22 px heading): critique defects.
- Too many scale levels at a big ratio: the top steps overflow phones.
- Subsetting that drops `tnum`/`case`, or a latin subset served to a page with Vietnamese text.
- Preloading every weight; loading 4 static weights when one variable file covers them.
- `font-display: swap` without a metric-matched fallback: visible reflow and CLS.
- Unitless line-height on headings that need grid snapping, or length line-heights on body text
  whose children change size.
- Justified text without hyphenation; `hyphens: auto` without `lang`.
- Faux bold or italic synthesised by the browser because the weight or style was not loaded
  (`font-synthesis: none` exposes it).
- Pairing two near-identical sans-serifs; ignoring x-height mismatch between paired families.

Related: `oklch-palette-ramps`, `design-tokens-dtcg`, `layout-grids-posters-editorial`,
`brand-guidelines-system`, `print-prepress-pdfx`, `visual-accessibility-audit`, hub `graphic-design`.
