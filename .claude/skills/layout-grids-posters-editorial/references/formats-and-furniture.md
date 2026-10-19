# Formats, viewing distance, editorial furniture, academic posters and slides

## 1. Print formats

Pixels = mm / 25.4 x ppi. Bleed adds 3 mm per side (0.125 in in the US); keep text 3-5 mm
inside the trim (more on large formats).

| Size | mm | px at 300 ppi | px at 150 ppi | px at 300 ppi with 3 mm bleed |
|---|---|---|---|---|
| A0 | 841 x 1189 | 9933 x 14043 | 4967 x 7022 | 10004 x 14114 |
| A1 | 594 x 841 | 7016 x 9933 | 3508 x 4967 | 7087 x 10004 |
| A2 | 420 x 594 | 4961 x 7016 | 2480 x 3508 | 5031 x 7087 |
| A3 | 297 x 420 | 3508 x 4961 | 1754 x 2480 | 3579 x 5031 |
| A4 | 210 x 297 | 2480 x 3508 | 1240 x 1754 | 2551 x 3579 |

| US size | inches | mm | px at 300 ppi | px at 150 ppi |
|---|---|---|---|---|
| Letter | 8.5 x 11 | 216 x 279 | 2550 x 3300 | 1275 x 1650 |
| Tabloid | 11 x 17 | 279 x 432 | 3300 x 5100 | 1650 x 2550 |
| Poster | 18 x 24 | 457 x 610 | 5400 x 7200 | 2700 x 3600 |
| Poster | 24 x 36 | 610 x 914 | 7200 x 10800 | 3600 x 5400 |
| One-sheet | 27 x 40 | 686 x 1016 | 8100 x 12000 | 4050 x 6000 |

A-series pages all have the ratio 1 : sqrt(2) (1.414), so a layout scales between A sizes
without reflow; type sizes do not scale with the page when the viewing distance stays the same.

## 2. Viewing distance → type size

Cap height ≈ distance / 250 (comfortable) to distance / 300. Size in pt = cap mm / cap ratio /
25.4 x 72. The table assumes a cap ratio of 0.72 em; read the font's own `capHeight / unitsPerEm`
(for example with fontTools: `TTFont(path)['OS/2'].sCapHeight / TTFont(path)['head'].unitsPerEm`).

| Distance | Cap height | Size | Use |
|---|---|---|---|
| 0.5 m | 1.7-2.0 mm | 7-8 pt | legal lines on hand-held print |
| 1 m | 3.3-4.0 mm | 13-16 pt | poster details, QR caption |
| 2 m | 6.7-8.0 mm | 26-31 pt | poster body, academic-poster headings |
| 3 m | 10-12 mm | 39-47 pt | sub-headlines on A1/A0 |
| 5 m | 16.7-20 mm | 66-79 pt | headline on A2/A1 |
| 10 m | 33-40 mm | 131-157 pt | headline on A0, banners, signage |

Signage and wayfinding have their own standards (local accessibility codes); use the font's
guidance and test at distance with a printed strip.

## 3. Editorial furniture

| Element | Placement and style |
|---|---|
| Kicker / overline | above the headline; caps or small caps, +6-10% tracking, accent colour or rule |
| Headline | 2-4 steps above body on the type scale; leading 1.0-1.15; balanced lines; no widow |
| Deck (dek) / standfirst | under the headline, 1.25-1.5x body, 1-3 lines, lighter weight |
| Byline / dateline | after the deck or at the start of the body; meta size; same position every article |
| Lede | first paragraph; may run wider or larger; starts with the drop cap |
| Drop cap | 2-4 lines deep, top aligned to the cap height of line 1, baseline on line n |
| Subheads | every 300-500 words in long reads; more space above than below |
| Pull quote | 1.5-2x body; at most 3 lines; quote marks hung; not on the same spread as the quoted line |
| Sidebar / boxout | separate column or tinted module; own heading style; never splits a paragraph |
| Captions | one style; adjacent to the image (touching or within one gutter); credit at the end or rotated |
| Folio | page number in the outer margin, same baseline on every page |
| Running head / foot | section or publication name; outer margin; small caps or meta size |
| Jump line | "Continued on page 12" at the break, "Continued from page 1" at the resumption |

Drop cap with fallback (Chromium supports `initial-letter`, Safari via `-webkit-initial-letter`;
Firefox did not at last check):

```css
.article > p:first-of-type::first-letter { -webkit-initial-letter: 3; initial-letter: 3; margin-inline-end: .4em; font-weight: 700; }
@supports not ((initial-letter: 3) or (-webkit-initial-letter: 3)) {
  .article > p:first-of-type::first-letter { float: left; font-size: 3.6em; line-height: .8; margin: .06em .08em 0 0; }
}   /* tune the fallback per font against the overlay: the cap must sit on line 3's baseline */
```

Measure check: characters per line ≈ column width / (0.5 x font size) as a first estimate (most
text faces average 0.45-0.55 em per character), then count real lines. Targets: single-column
body 45-75 (about 66), multi-column 35-50, captions 30-60.

Images:
- Crop around a declared focal box; check that box in every format before approving the crop.
- Portraits: eyes near the upper third line; leave lead room in the gaze direction; do not cut
  at joints (wrists, knees, ankles).
- Bleed images extend 3 mm past the trim; boxed images align to module edges, not to text.
- Effective ppi = pixel width / placed width in inches. 300 ppi for print viewed at reading
  distance; about 150 ppi for large formats viewed from a distance.

## 4. Academic posters

| Item | A0 portrait (841 x 1189 mm) | A0 landscape (1189 x 841 mm) |
|---|---|---|
| margins / gutters | 30 mm / 20 mm | 30 mm / 20 mm |
| columns | 3 x 247 mm | 4 x 267.25 mm |
| measure at 24 pt | about 58 characters | about 63 characters |
| title band | top 10-15%: title, authors, affiliations, logos | same |
| title | 72-100+ pt (readable from 4-5 m) | same |
| section heads | 36-48 pt | same |
| body | >= 24 pt (28-32 pt preferred) | same |
| captions, references | >= 18 pt | same |

Column width check: (841 - 60 - 2 x 20) / 3 = 247 mm; (1189 - 60 - 3 x 20) / 4 = 267.25 mm.
Flow: numbered sections down column 1, then column 2; one dominant result figure, labelled at
>= 18 pt; a QR to the paper or code in the footer. Word budget is a judgment call: cut until
the 3-second test names the finding.

## 5. Slides (1920 x 1080)

| Item | Value |
|---|---|
| grid | 12 columns, gutter 24, margins 96 → 122 px columns |
| safe area | 5% each side: x 96..1824, y 54..1026 |
| title | 64-80 px, one line, same position on every slide |
| body | >= 48 px; at most about 6 lines; one idea per slide |
| chart labels | >= 32 px; direct labels instead of legends |
| contrast | >= 4.5:1 required; aim for 7:1 because projectors wash out |

Point sizes are page-relative: PowerPoint widescreen pages are 13.333 x 7.5 in (960 x 540 pt),
so 24 pt exports as 48 px at 1920 x 1080; Google Slides' default 10 x 5.625 in page (720 x 405 pt)
exports 24 pt as 64 px. Specify slide type in px at 1920 x 1080 or as a share of slide height.
