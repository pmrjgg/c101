# Typography reference

## 1. Vocabulary that matters for decisions

| Term | Why it matters |
|---|---|
| x-height | larger x-height reads bigger at the same point size; match x-heights when pairing |
| Cap height | aligns with icons and numerals in UI; use for vertical centring of labels |
| Counter / aperture | open apertures (e.g. Inter, Source Sans) survive small sizes and low resolution |
| Contrast (stroke) | high-contrast serifs (Didone) break at small sizes and on screens; use for display only |
| Optical size | fonts with `opsz` axes adjust contrast and spacing per size: let them (`font-optical-sizing: auto`) |
| Width | condensed families save space in headlines and tables, hurt long reading |
| Ambiguous glyphs | Il1 and O0 must be distinct in UI, codes, passwords, IDs |

## 2. Pairing catalogue (open-licence families)

| Body / UI | Pair with | Character | Notes |
|---|---|---|---|
| Inter | Source Serif 4 or Newsreader | neutral product + editorial | Inter has `opsz` (Inter 4) and tabular figures |
| IBM Plex Sans | IBM Plex Serif, IBM Plex Mono | technical, corporate | superfamily: safest coherent choice |
| Source Sans 3 | Source Serif 4, Source Code Pro | documentation | superfamily with matched metrics |
| Roboto Flex | Roboto Serif, Roboto Mono | Android-native feel | variable widths and optical sizes |
| Manrope | Literata | friendly app + long-form | Literata designed for e-reading |
| DM Sans | DM Serif Display | startup marketing | serif display only, not body |
| Work Sans | Fraunces | warm, expressive | Fraunces has a "wonk" axis; restrain it |
| Space Grotesk | IBM Plex Mono | developer/tech branding | do not pair with another grotesque |
| Noto Sans / Noto Serif | (same family per script) | multilingual | coverage for almost all scripts |

Pairing tests: set a headline + paragraph + caption in both candidates; check x-height match,
shared proportions (wide with wide), contrast in classification (serif vs sans, geometric vs
humanist), and that weights available cover the hierarchy (regular, medium/semibold, bold).

## 3. Roles and defaults (screen)

| Role | Size | Weight | Line-height | Tracking |
|---|---|---|---|---|
| Display / hero | 48-96 px | 600-800 | 1.0-1.1 | -2% to -3% |
| H1 | 32-48 px | 600-700 | 1.1-1.2 | -1% to -2% |
| H2 | 24-32 px | 600 | 1.2-1.25 | -1% |
| H3 | 20-24 px | 600 | 1.25-1.3 | 0 |
| Body | 16-18 px | 400 | 1.5-1.6 | 0 |
| Small / meta | 13-14 px | 400-500 | 1.4-1.5 | +0.5% |
| Label / overline (caps) | 11-12 px | 500-600 | 1.3 | +6% to +10% |
| Code | 0.9 × body | 400 | 1.5 | 0 |

## 4. CSS patterns

Fluid size between two viewport widths (size s1 at w1, s2 at w2; px values):

```
slope = (s2 - s1) / (w2 - w1)
intercept = s1 - slope × w1
font-size: clamp(s1, intercept + slope × 100vw, s2)

Example 32 px @ 360 → 56 px @ 1440:
slope = 24/1080 = 0.02222 → 2.222vw; intercept = 32 - 8 = 24 px = 1.5rem
font-size: clamp(2rem, 1.5rem + 2.222vw, 3.5rem);
```

Keep a rem term in the preferred value; pure `vw` sizes do not respond to browser zoom and fail
WCAG 1.4.4 (resize text to 200%).

```css
:root { --step-0: clamp(1rem, 0.96rem + 0.18vw, 1.125rem); }
body  { font: 400 var(--step-0)/1.55 Inter, system-ui, sans-serif; }
p     { max-width: 66ch; hyphens: auto; text-wrap: pretty; }
h1, h2 { text-wrap: balance; line-height: 1.1; letter-spacing: -0.02em; }
table { font-variant-numeric: tabular-nums lining-nums; }
.caps { text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.75rem; }
html  { font-optical-sizing: auto; }  /* for fonts with an opsz axis */
```

`hyphens: auto` requires the correct `lang` attribute. Line-height unitless so it scales with
the element's own size. Load only the weights used; subset with `unicode-range`; `font-display:
swap` plus metric-compatible fallbacks (`size-adjust`, `ascent-override`) to avoid layout shift.

## 5. Print typography

| Setting | Default |
|---|---|
| Body size | 9-11 pt (books 10-12 pt) |
| Leading | body size + 2-4 pt (e.g. 10/13, 11/15) |
| Measure | 60-70 characters; columns ≥ 35 characters |
| Baseline grid | = body leading; headings use multiples or half-steps |
| Justification (InDesign word spacing) | min 80%, desired 100%, max 133%; letter spacing -2/0/+2%; glyph scaling 98/100/102% |
| Hyphenation | words ≥ 6 letters, ≥ 3 letters before/after break, ≤ 2 consecutive hyphens |
| Paragraph separation | indent (1 em) or space (half line), never both |
| Small text reversed out of color | ≥ 8 pt, medium weight, avoid thin serifs (ink spread fills counters) |
| Fine lines | ≥ 0.25 pt (0.1 mm) |

Use true small caps and old-style figures from the font, not synthesised ones; enable optical
margin alignment (hanging punctuation) for justified body text.

## 6. Multilingual and accessibility

- CJK: larger line-height (1.7-1.8), no italics (use weight or color for emphasis), avoid letter
  spacing changes, line breaking rules (kinsoku) handled by the layout engine.
- Arabic/Hebrew (RTL): mirror layouts, not icons with inherent direction (clocks, media controls);
  Arabic needs larger sizes for the same legibility (about +10-20%).
- German/Finnish/Dutch long compounds: test headline breaks with real copy; allow hyphenation.
- Expansion: translations run 20-35% longer than English (more for short UI strings); design
  containers for +40%.
- Dyslexia-friendly practice: generous spacing (WCAG 1.4.12 requires layouts to survive line
  height 1.5, paragraph spacing 2×, letter spacing 0.12 em, word spacing 0.16 em), left-aligned
  text, no long italics or all-caps passages.

## 7. Typography critique checklist

- [ ] Scale declared and followed (no ad-hoc sizes).
- [ ] Measure within 45-75 characters for body.
- [ ] Leading appropriate to size and measure; headings tighter than body.
- [ ] ≤ 2 families, ≤ 4 weights; each weight has a role.
- [ ] Caps and small labels tracked out; display sizes tracked in.
- [ ] Tabular figures in tables and changing numbers (timers, prices).
- [ ] No widows/orphans in prominent text; headlines balanced; no rivers in justified text.
- [ ] Quotes, apostrophes and dashes typographic (" " ' – —), not straight quotes or double hyphens.
- [ ] Legible at actual size on the target device or print distance.
- [ ] Fonts licensed for the medium (web, app, print, broadcast).
