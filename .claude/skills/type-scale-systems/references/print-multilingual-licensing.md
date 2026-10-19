# Print, multilingual and licensing reference

## 1. Print typography

| Setting | Default | Why |
|---|---|---|
| Body size | 9-11 pt; books 10-12 pt; captions >= 7-8 pt | reading distance 30-40 cm |
| Leading | body + 2-4 pt (10/13, 11/15) | longer measures need the larger value |
| Measure | 60-70 characters; columns >= 35 characters | narrow columns force bad breaks |
| Baseline grid | increment = body leading; headings use multiples or half-steps | cross-column alignment |
| Word spacing (justified) | min 80%, desired 100%, max 133% | fewer rivers and loose lines |
| Letter spacing (justified) | -2% / 0 / +2% | last resort after word spacing |
| Glyph scaling | 98% / 100% / 102% | invisible at this range, never more |
| Hyphenation | words >= 6 letters; >= 3 before and after the break; <= 2 consecutive hyphens; no hyphenated last word of a paragraph | |
| Paragraphs | first-line indent 1 em or half-line space, never both; no indent after headings | |
| Reversed text | >= 8 pt, medium weight, avoid thin serifs | ink spread fills counters |
| Fine lines | >= 0.25 pt (0.1 mm) | thinner lines break up on press |
| Figures and caps | true small caps (smcp, c2sc) and oldstyle figures (onum) from the font | synthesised small caps are too light |
| Optical margin alignment | on for justified body (hanging punctuation) | straight optical edge |
| Signage | cap height about viewing distance / 250 to / 300 (3 m -> 10-12 mm caps); check the typeface's own guidance | |

Composer: paragraph composer (InDesign "Adobe Paragraph Composer") over single-line for body.
Widows and orphans: at least 2 lines kept together; no single word on the last line of a
paragraph in prominent text. Press files, bleed, ink and PDF/X: `print-prepress-pdfx`.

## 2. Multilingual

| Script / language | Rule |
|---|---|
| Chinese, Japanese, Korean | line-height 1.7-1.8; no italics (use weight or colour); no letter-spacing changes; `line-break: strict` (Japanese kinsoku); body >= 14-16 px; fonts are large: subset by usage or use system fonts |
| Arabic, Persian, Urdu | size about +10-20% for equal legibility; never letter-space (breaks joining); RTL with `dir="rtl"`; generous line-height (diacritics) |
| Hebrew | RTL; vowel points need line-height; no letter-spacing on pointed text |
| Devanagari, Thai, other Brahmic | taller ascenders and stacked marks: start around line-height 1.6 and test; check clipping in fixed-height UI |
| Vietnamese | stacked diacritics above capitals: keep heading line-height loose enough (test, roughly 1.3 and up); the font must cover U+1EA0-1EF9 |
| German, Finnish, Dutch | long compounds: test headline breaks with real copy; allow hyphenation with `lang` set |

RTL mirroring: mirror page layout, navigation order, back/forward and progress direction, and
icons with inherent direction (arrows, send). Do not mirror clocks, media play/pause, logos,
numbers, checkmarks, or images of real objects. Use logical properties (`margin-inline-start`,
`padding-inline-end`, `inset-inline-start`) so one stylesheet serves both directions.

Expansion budget (relative to English): sentences +20-35%, short UI strings far more (a
one-word label can double); design containers for +40% and test with pseudo-localisation
(accents and padding) plus real translations.

Reading support (WCAG 1.4.12 must survive user overrides): line-height 1.5 x, paragraph spacing
2 x font size, letter spacing 0.12 em, word spacing 0.16 em. Left-aligned text, no long italic or
all-caps passages.

## 3. Licensing

| Question for each font | Where to look |
|---|---|
| Desktop installs: how many machines or users? | EULA "desktop" or "workstation" |
| Web: self-hosting allowed? pageview cap? subsetting and WOFF2 conversion allowed? | EULA "web" |
| Apps: embedding in iOS/Android/desktop binaries? per app or per install? | EULA "app" or "embedding" |
| Broadcast, video, games, ePub, PDF forms | separate licences in many foundries |
| Logo or wordmark use, trademark registration | some EULAs exclude or charge; OFL allows (OFL FAQ 1.1) |
| Modifying glyphs (custom wordmark letters) | OFL allows with Reserved Font Name rules for distributed fonts; commercial EULAs often forbid modification of the font file |

Record per family: name, version, licence type, licence file, allowed media, purchase record
(owner, date). Ship licence files next to the fonts (`brand/fonts/<family>/OFL.txt`).

## 4. Typography critique scoring

Score each checklist item (SKILL.md section 11) pass / fail with the measured value ("body
measure 92 ch at 1440 px: fail, set max-width 66ch"). Feed the result into the hub's rubric row
"Typography" (3 = all pass; 2 = one minor fail; 1 = scale or measure broken; 0 = no system).
