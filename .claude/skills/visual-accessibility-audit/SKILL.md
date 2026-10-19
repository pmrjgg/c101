---
name: visual-accessibility-audit
description: "Accessibility in visual design: WCAG 2.2 contrast matrix for every text and UI pair, non-text and focus-indicator contrast, text over images with solved scrims, colour-vision-deficiency simulation, use of colour, target size, motion, forced colours and alt text, with APCA only as a second opinion. Load when designing or auditing visuals that must meet AA or AAA."
when_to_use: "Checking whether colours, text or UI pass WCAG 2.2 AA or AAA, fixing a contrast failure without changing hue, text on photos or video stills, focus rings, input borders, icons and chart marks, colour-blind safety of status colours or chart palettes, target sizes, reduced motion, Windows contrast themes and forced colours, alt text for images and charts, or interpreting an axe or Lighthouse accessibility report."
---

# Visual accessibility audit

An audit is done when every text and UI pair actually used sits in a contrast matrix with size,
weight, target and a measured verdict; every failure has a fix that moves OKLCH L at fixed hue and
chroma; text over images passes at the worst pixel; non-text parts and focus indicators reach 3:1;
CVD and grayscale passes are clean or backed by non-colour cues; motion, forced colours and alt
text are reviewed; and automated runs are paired with the manual checks they cannot do.

Tool: [a11y_check.py](scripts/a11y_check.py), stdlib only (Pillow just for `scrim --image`).

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
A11Y="$STACK/.claude/skills/visual-accessibility-audit/scripts/a11y_check.py"
PY="$STACK/.venv/bin/python"; [ -x "$PY" ] || PY=python3
python3 -I "$A11Y" ratio '#767676' '#FFFFFF' '#777777' '#FFFFFF'     # pairs and what they may be used for
python3 -I "$A11Y" matrix pairs.csv --level AA                       # report table with fixes
python3 -I "$A11Y" fix '#FFFFFF' '#E94560' --move bg --margin 0.25   # OKLCH-L fix, hue and chroma kept
"$PY" -I "$A11Y" scrim '#FFFFFF' --image hero.jpg --box 40,300,760,420 --scrim '#000000'
python3 -I "$A11Y" cvd '#15803D' '#B45309' '#B91C1C' '#1D4ED8'      # Machado 2009 + grayscale
python3 -I "$A11Y" apca '#FFFFFF' '#D63151'                           # advisory Lc
```

## 1. Contrast formula and reference pairs

```text
c = channel / 255
lin(c) = c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ^ 2.4
L = 0.2126 R + 0.7152 G + 0.0722 B                     relative luminance of the linear channels
ratio = (L_lighter + 0.05) / (L_darker + 0.05)        1:1 to 21:1
```

Older WCAG texts print 0.03928 for the knee; no 8-bit colour changes. Decide pass/fail on the
unrounded ratio: 4.497 fails 4.5 even though it rounds to 4.50 (the script prints more decimals
whenever rounding would hide a fail).

| Pair | Ratio | Verdict |
|---|---|---|
| #767676 on #FFFFFF | 4.54 | passes AA for all text: the lightest gray that does on white |
| #777777 on #FFFFFF | 4.48 | fails body text; large text and UI only |
| #9CA3AF on #FFFFFF | 2.54 | fails text and 1.4.11 (a classic input-border failure) |
| #FFFFFF on #E94560 | 3.83 | large text and UI only |
| #FFFFFF on #D63151 | 4.75 | all text AA |

| Content | AA | AAA |
|---|---|---|
| Normal text (under 24 px, or under 18.66 px bold) | 4.5:1 (1.4.3) | 7:1 (1.4.6) |
| Large text: at least 24 px regular or 18.66 px bold (18 pt / 14 pt) | 3:1 | 4.5:1 |
| UI component boundaries and states, meaningful graphics | 3:1 (1.4.11) | no AAA criterion |
| Logotypes, decoration, inactive (disabled) components | exempt | exempt |

Bold means weight 700 or more; 600 does not qualify. Thin weights (300 and below) pass the formula
but read worse: flag them.

## 2. Criteria table (WCAG 2.2)

| SC | Name | Level | Visual check |
|---|---|---|---|
| 1.1.1 | Non-text Content | A | meaningful images have text alternatives; decorative ones `alt=""` |
| 1.4.1 | Use of Color | A | colour is never the only cue (section 7) |
| 1.4.3 | Contrast (Minimum) | AA | 4.5:1 text, 3:1 large text |
| 1.4.6 | Contrast (Enhanced) | AAA | 7:1 text, 4.5:1 large text |
| 1.4.10 | Reflow | AA | works at 320 CSS px wide (400 % zoom of 1280 px) without 2D scrolling |
| 1.4.11 | Non-text Contrast | AA | UI boundaries, states, icons, chart marks, focus indicators 3:1 |
| 1.4.12 | Text Spacing | AA | survives line height 1.5, paragraph spacing 2×, letter 0.12 em, word 0.16 em |
| 2.3.1 | Three Flashes or Below Threshold | A | nothing flashes more than three times in any one second |
| 2.4.7 | Focus Visible | AA | every focusable element shows focus |
| 2.4.11 | Focus Not Obscured (Minimum) | AA | the focused element is not entirely hidden by sticky bars, banners, overlays |
| 2.4.13 | Focus Appearance | AAA | indicator area ≥ a 2 CSS px perimeter of the component, 3:1 between focused and unfocused pixels |
| 2.5.8 | Target Size (Minimum) | AA | targets ≥ 24 × 24 CSS px, or spaced so 24 px circles centred on them do not overlap (exceptions: inline, equivalent, user agent, essential) |

Related: 1.4.5 Images of Text (AA), 2.2.2 Pause, Stop, Hide (A, moving content over 5 s),
2.3.3 Animation from Interactions (AAA), 2.4.12 Focus Not Obscured (Enhanced, AAA), 2.5.5 Target
Size (Enhanced, AAA, 44 × 44).

## 3. Contrast matrix procedure

1. Enumerate the pairs actually used: from tokens (every semantic foreground × background that
   components combine) or by sampling screenshots (pick the glyph core and the background next to
   it; anti-aliased edge pixels are not the text colour). Include hover, focus, active, visited,
   selected, error and placeholder states (placeholder text is text), dark mode and any
   high-contrast theme; list disabled states as exempt.
2. Write `pairs.csv` with `fg,bg,usage,size_px,weight,kind,move`; `kind` is text, ui, decorative
   or logo; `move` says which colour a fix may change (brand fills move the fill, text tokens move
   the text).
3. Run `matrix`. Every failure gets a fix that moves OKLCH L at fixed hue and chroma (chroma is
   reduced only where the colour would leave sRGB, and the output says so).
4. Apply the fixes to the tokens, re-run until there are no failures, then publish the table as
   the accessibility statement (`brand-guidelines-system`) and gate CI on the exit status.

```text
| Pair (fg / bg) | Usage | Size / weight | Ratio | Target | Pass | Fix |
| #1A1A2E / #FFFFFF | body text | 16 px / 400 | 17.06 | 4.5 | yes |  |
| #6B7280 / #FFFFFF | secondary text | 14 px / 400 | 4.83 | 4.5 | yes |  |
| #FFFFFF / #E94560 | CTA label | 16 px / 600 | 3.83 | 4.5 | **no** | bg #E94560 (L 0.633) -> #DA3654 oklch(0.592 0.199 15.7) = 4.53:1 |
| #9CA3AF / #FFFFFF | input border | ui | 2.54 | 3 | **no** | fg #9CA3AF (L 0.714) -> #8F95A1 oklch(0.670 0.019 261.3) = 3.01:1 |
| #E94560 / #FFFFFF | focus ring | ui | 3.83 | 3 | yes |  |
| #AEB4BE / #FFFFFF | divider | decorative | 2.08 | exempt | yes |  |
```

Dark mode is a separate matrix: lighten brand colours at fixed hue, avoid pure white on pure black
for long text (#E6E6E6 on #121212 is 15.01:1 and calmer), re-measure everything.

## 4. Text over images

- Measure the worst point under the text box, never the average: one sunlit patch under a letter
  fails the line. For light text the worst pixel is the lightest, for dark text the darkest.
- Solve a scrim: per sRGB channel (how browsers composite), blended = a × scrim + (1 − a) × bg.
  Find the smallest a for which the worst blended pixel reaches the target. The sRGB curve has an
  offset, so solve numerically (`scrim` scans a in 0.01 steps and re-checks every pixel).
- Verified run, white headline over a sky photo with a bright patch:

```text
worst pixel under the text: #FAF4E1, 1.09:1 against #FFFFFF without a scrim
scrim alpha >= 0.52 -> worst blended #78756C = 4.59:1 (target 4.5)
CSS: background: rgb(0 0 0 / 0.52) behind the text box (a gradient must reach 0.52 there)
```

- A gradient scrim must reach the solved alpha everywhere under the text box at every breakpoint
  (the box moves when the layout reflows); for video, sample the brightest frames.
- Alternatives: a solid panel, a calmer crop, a darker grade of the photo. Text shadows help
  legibility but are hard to measure; do not count them toward the ratio.

## 5. Non-text contrast and focus indicators

- 3:1 against adjacent colours (1.4.11): input and checkbox borders when the border identifies the
  control, toggle and selected states, meaningful icons without text, chart marks, focus rings.
- Not required: disabled components, decoration, logotypes, controls identified by their text alone
  (their states still need to be visible).
- Focus indicator: a 2 px outline with a 2 px offset, contrasting with both the page background
  and the component's own fill. A ring the same pink as a pink button fails (#E94560 against
  #D63151 is 1.24:1); with the offset it sits on white (3.83:1) and passes. Where backgrounds vary,
  use a two-tone ring.

```css
:focus-visible { outline: 2px solid var(--focus-ring, #1A1A2E); outline-offset: 2px; }
.on-dark :focus-visible { outline-color: #FFFFFF; }
.two-tone:focus-visible { outline: 2px solid #1A1A2E; box-shadow: 0 0 0 4px #FFFFFF; }
html { scroll-padding-top: 72px; }      /* sticky header height: focused items stay visible (2.4.11) */
```

Never remove `outline` without a replacement; keep the outline even when a box-shadow ring is
added, because forced-colours modes drop box-shadow (section 8).

## 6. Colour-vision-deficiency simulation

Machado, Oliveira and Fernandes 2009 matrices at severity 1.0 (checked against the authors'
table), applied to linear RGB, plus a grayscale (luminance) pass:

```text
protan [[ 0.152286,  1.052583, -0.204868], [ 0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]]
deutan [[ 0.367322,  0.860646, -0.227968], [ 0.280085, 0.672501, 0.047413], [-0.011820,  0.042940, 0.968881]]
tritan [[ 1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [ 0.004733,  0.691367, 0.303900]]
```

For screenshots and charts, with NumPy (`uv add numpy pillow`):

```python
import numpy as np
from PIL import Image
M = {"protan": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
     "deutan": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
     "tritan": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]]}
lin = lambda c: np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
enc = lambda c: np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.clip(c, 0.0031308, 1) ** (1 / 2.4) - 0.055)
save = lambda a, name: Image.fromarray(np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)).save(name)
rgb = lin(np.asarray(Image.open("screen.png").convert("RGB"), dtype=np.float64) / 255)
for name, m in M.items():
    save(enc(np.clip(rgb @ np.array(m).T, 0, 1)), f"screen_{name}.png")
save(enc(rgb @ np.array([0.2126, 0.7152, 0.0722])), "screen_gray.png")
```

Rule: categories that must be told apart differ by at least 0.10-0.15 OKLCH L under every
simulation, or carry labels, icons or patterns. `cvd` flags FAIL (ΔL < 0.10 and ΔE_OK < 0.10:
the same colour for that viewer) and LABEL (ΔL < 0.10 with a hue-only difference: fine for large
fills, label thin lines and small marks). Interactive checks: Chrome DevTools, Rendering panel,
"Emulate vision deficiencies"; Color Oracle on the desktop.

## 7. Use of colour (1.4.1)

- Status: colour plus icon plus text ("Overdue" with a cross icon), never a coloured dot alone.
- Links in body text: underlined; or 3:1 against the surrounding text plus a non-colour cue on
  hover and focus.
- Form errors: icon, text message next to the field, and the field border, not a red border alone.
- Charts: direct labels, shapes per series, dash patterns, hatching (`chart-design-encoding`).
- Required fields, selected tabs, active filters: a mark, weight or underline as well as colour.

## 8. Motion and forced colours

```css
@media (prefers-reduced-motion: no-preference) {        /* motion is opt-in */
  .hero { animation: drift 12s ease-in-out infinite alternate; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .parallax { transform: none !important; }             /* no parallax without an opt-out */
}
@media (forced-colors: active) {
  .btn { border: 1px solid ButtonText; }                 /* backgrounds are overridden: keep a border */
  .icon { fill: CanvasText; }                            /* or fill="currentColor" in the SVG */
  :focus-visible { outline: 2px solid Highlight; }       /* box-shadow rings disappear here */
  .legend-swatch { forced-color-adjust: none; }          /* only where the colour itself is the data */
}
```

- No flashing above three per second (2.3.1); auto-moving content over 5 s gets pause or stop
  (2.2.2); no parallax or scroll-jacking without an opt-out.
- Forced colours (Windows contrast themes): the system palette replaces author colours; use system
  colours (Canvas, CanvasText, LinkText, ButtonFace, ButtonText, Highlight, HighlightText,
  GrayText) and check that focus stays visible. An `outline: 2px solid transparent` fallback turns
  into a visible ring there. Test with a Windows contrast theme or DevTools' forced-colors emulation.

## 9. Alt text

- Describe the purpose, not the appearance: a linked icon is "Download the 2026 report (PDF,
  2 MB)", not "blue arrow".
- Decorative images: `alt=""` (or CSS backgrounds); no "image of".
- Charts: chart type, the takeaway, key numbers, and a link to the data: "Line chart: support
  tickets fell 18 % after the June 2026 help-centre redesign. Data table below."
- Complex images (diagrams, maps, infographics): a short alt plus a long description next to the
  image (figure caption, a details element or a linked page).
- Avoid images of text (1.4.5); when unavoidable, the alt repeats the text. Inline SVG gets
  `role="img"` and a `<title>` or `aria-label`.

## 10. Automated checks

```ts
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
test("home has no detectable WCAG A/AA violations", async ({ page }) => {
  await page.goto("http://localhost:3000/");
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  expect(results.violations).toEqual([]);
});
```

```bash
npx lighthouse http://localhost:3000 --only-categories=accessibility --output=json \
    --output-path=./lh-a11y.json --chrome-flags="--headless=new"
verapdf --flavour ua1 report.pdf        # PDFs: machine-checkable PDF/UA-1 rules only
```

Automation misses or only flags for review: text over images and gradients, focus order and
visibility, focus obscured by sticky elements, alt text quality, colour-only meaning, motion, CVD,
contrast of hover and focus states, reflow behaviour. Review these by hand with screenshots from
the `browser-operator` agent (`browser-automation`) and record them in the report.

## 11. APCA as a second opinion

- APCA (the candidate method for a future WCAG 3) gives a signed lightness contrast Lc: positive
  for dark text on light, negative for light on dark. Rough guide: |Lc| 75 for body text, 60 for
  large or content text, 45 for headlines and non-text elements.
- Report it next to the WCAG ratio, never instead of it: white on #D63151 is 4.75:1 and Lc −77.0;
  white on #E94560 is 3.83:1 (fails AA) yet Lc −70.1. The WCAG 2 result decides conformance.
- Never claim WCAG 3 conformance: WCAG 3 is a draft and its contrast method is undecided.

## 12. Report template and worked example

| Pair (fg / bg) | Usage | Size / weight | Ratio | Target | Pass | Fix |
|---|---|---|---|---|---|---|
| #FFFFFF / #E94560 | CTA label | 16 px / 600 | 3.83 | 4.5 | no | fill → #D63151, oklch(0.581 0.199 15.7) = 4.75:1 |
| #E94560 / #D63151 | focus ring on the fixed CTA | ui | 1.24 | 3 | no | `outline-offset: 2px`, ring on #FFFFFF = 3.83:1 |
| #9CA3AF / #FFFFFF | input border | ui | 2.54 | 3 | no | → gray.500 #6B7280 (4.83:1) |
| #FFFFFF / #15803D | chip "Paid" | 12 px / 600 | 5.02 | 4.5 | yes | add icon (CVD, below) |
| #FFFFFF / #B45309 | chip "Due soon" | 12 px / 600 | 5.02 | 4.5 | yes | add icon |
| #FFFFFF / #B91C1C | chip "Overdue" | 12 px / 600 | 6.47 | 4.5 | yes | add icon |
| #FFFFFF / #1D4ED8 | chip "Info" | 12 px / 600 | 6.70 | 4.5 | yes | add icon |

CTA: 16 px at weight 600 is normal text, so the target is 4.5:1. `fix --move bg` gives the
minimum, #DA3654 (L 0.633 → 0.592, 4.53:1); `--margin 0.25` leaves room for a darker hover state
and lands exactly on #D63151 (L 0.581, same hue 15.7 and chroma 0.199, 4.75:1), which ships.
Alternative without recolouring: set the label at 18.66 px bold or larger, where 3.83:1 passes 3:1.

Status chips, `cvd` run: every label passes contrast, but under deutan "Paid" and "Overdue" become
the same olive (ΔL 0.008, ΔE_OK 0.042: FAIL), protan merges "Paid" with "Due soon" (FAIL),
tritan merges "Paid" with "Info" (FAIL), and in grayscale "Paid" and "Due soon" are both #6F6F6F.
Fix (1.4.1): keep the colours, add an icon and keep the word on every chip (check "Paid",
triangle "Due soon", cross "Overdue", "i" "Info"); if chips appear without text anywhere (a table
column of dots), give them distinct shapes. Re-run `matrix` and `cvd`: contrast failures 0, CVD
FAILs remain but are now covered by non-colour cues, which the report states.

## Pitfalls

- Averaging the background under text instead of taking the worst pixel.
- Rounding 4.497 up to 4.5; sampling anti-aliased edge pixels as the text colour.
- Treating weight 600 as bold for the large-text threshold.
- Forgetting states (hover, focus, placeholder, error), dark mode and the focus ring against the
  component itself.
- Focus rings built only from box-shadow (they vanish in forced colours) or `outline: none`.
- Fixing contrast by changing hue (brand drift) instead of moving OKLCH L.
- Colour-only status, links or chart series; red/green pairs with no icon or label.
- Treating a clean axe or Lighthouse run as a pass; claiming APCA or WCAG 3 conformance.
- Alt text that describes appearance ("pink chart") instead of the message.

Related: `oklch-palette-ramps`, `design-tokens-dtcg`, `brand-guidelines-system`, `chart-design-encoding`, `ui-mockup-hifi`, `browser-automation`, `visual-review`, hub `graphic-design`
