---
name: print-prepress-pdfx
description: "Print preparation: printer-spec intake, bleed and safe zones, effective-ppi checks, ICC CMYK conversion (PSO Coated v3/FOGRA51, GRACoL 2013), rich black and total-ink limits, overprint and spot colours, font embedding, PDF/X-4 export, and command-line preflight with poppler, qpdf and Ghostscript. Load before sending any file to a printer."
when_to_use: "Preparing a flyer, poster, brochure, business card, packaging or book for a commercial printer: asking for the printer's specs, setting bleed and safe zones, checking image ppi, converting RGB to CMYK with an ICC profile, rich black and ink limits, overprint and spot colours, dielines and varnish, embedding fonts, exporting or checking PDF/X-4 or PDF/X-1a, HTML-to-print with WeasyPrint or Paged.js, or writing a preflight report."
---

# Print prepress and PDF/X

A print file is done when it matches the printer's written spec, every row of the preflight table
passes with evidence from a command, and the final certification (callas pdfToolbox, Acrobat
Preflight or the printer's own preflight) is handed over explicitly as the user's or printer's step.

Tools: Ghostscript (commands below verified with 10.07), poppler (`pdfinfo`, `pdffonts`,
`pdfimages`), `qpdf`, ImageMagick 7 (`magick`), Pillow `ImageCms`, and
[tac_check.py](scripts/tac_check.py) for peak ink coverage. Install with
`brew install ghostscript poppler qpdf imagemagick` or `apt install ghostscript poppler-utils qpdf imagemagick`.

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
TAC="$STACK/.claude/skills/print-prepress-pdfx/scripts/tac_check.py"
PY="$STACK/.venv/bin/python"; [ -x "$PY" ] || PY=python3            # needs Pillow and gs on PATH
"$PY" -I "$TAC" flyer.pdf --limit 300 --dpi 150
```

## 1. Printer spec intake

| Item | Typical | Notes |
|---|---|---|
| Trim size | A5 148 × 210 mm | finished size after cutting |
| Bleed | 3 mm (EU), 0.125 in = 3.175 mm (US) | large format and packaging often differ |
| Safe zone | 3-5 mm inside the trim | more near folds and bindings |
| Printing condition / ICC profile | PSO Coated v3 (FOGRA51) | the printer's file, not a guess |
| TAC limit | 300 % coated sheet-fed | from the printer |
| PDF standard | PDF/X-4, or X-1a only when demanded | |
| Spot colours | exact names, e.g. "PANTONE 1795 C"; keep or convert | |
| Stock | 170 gsm gloss coated | sets profile, dot gain, ink limit |
| Proof | soft proof, contract proof (ISO 12647-7) or press proof | |
| Also | pages and imposition, crop marks yes/no, finishing (die, varnish, foil), deadline | |

Unknown values become an Open doubt in the output; they are never assumed. Record the answers:

```yaml
printer_spec: {trim_mm: [148, 210], bleed_mm: 3, safe_mm: 5, profile: "PSO Coated v3 (FOGRA51)",
               tac_max_pct: 300, pdf: "PDF/X-4", spots: [], stock: "170 gsm gloss coated",
               proof: "PDF soft proof + ISO 12647-7 contract proof", marks: "none, printer imposes"}
open_doubts: []
```

## 2. Document maths

```text
final px   = (trim_mm + 2 × bleed_mm) / 25.4 × ppi
points     = mm / 25.4 × 72
TrimBox    = [bleed_pt, bleed_pt, width_pt − bleed_pt, height_pt − bleed_pt] inside MediaBox = BleedBox
```

| Format | Trim (mm) | With 3 mm bleed (mm) | Pixels at 300 ppi | MediaBox (pt) |
|---|---|---|---|---|
| A4 | 210 × 297 | 216 × 303 | 2551 × 3579 | 612.28 × 858.90 |
| A5 | 148 × 210 | 154 × 216 | 1819 × 2551 | 436.54 × 612.28 |
| A6 | 105 × 148 | 111 × 154 | 1311 × 1819 | 314.65 × 436.54 |
| DL | 99 × 210 | 105 × 216 | 1240 × 2551 | 297.64 × 612.28 |
| Business card (EU) | 85 × 55 | 91 × 61 | 1075 × 720 | 257.95 × 172.91 |
| US Letter, 0.125 in bleed | 8.5 × 11 in | 8.75 × 11.25 in | 2625 × 3375 | 630 × 810 |

Backgrounds and images run fully into the bleed (to the BleedBox edge); text and logos stay inside
the safe zone; borders closer than about 5 mm to the trim show the cutting tolerance.

## 3. Effective resolution

Effective ppi = image pixels ÷ placed size in inches, after scaling in the layout.
`pdfimages -list` prints it per placement (`x-ppi`, `y-ppi` are columns 13 and 14):

```bash
pdfimages -list flyer.pdf                                   # page num type width height color ... x-ppi y-ppi
pdfimages -list flyer.pdf | awk 'NR > 2 && ($13 < 300 || $14 < 300)'    # offenders
```

| Use | Minimum effective ppi |
|---|---|
| Sheet-fed offset, viewing distance under 1 m | 300 (above ~450 downsample at export) |
| Posters and large format seen from 2 m or more | 150 |
| 1-bit line art | 600-1200 |

Upscaling is a last resort: re-source first; if upscaled (including AI upscalers), label it in the
report ("hero upscaled 2× from 1000 px, approved by …").

## 4. Colour conversion

| Printing condition | Characterisation | Typical profile file | Use |
|---|---|---|---|
| PSO Coated v3 | FOGRA51 | PSOcoated_v3.icc (ECI) | EU offset, premium coated paper |
| PSO Uncoated v3 | FOGRA52 | PSOuncoated_v3_FOGRA52.icc (ECI) | EU offset, uncoated paper |
| ISO Coated v2 (older, still requested) | FOGRA39 | ISOcoated_v2_eci.icc | EU coated, previous standard |
| GRACoL 2013 | CGATS21 CRPC6 | GRACoL2013_CRPC6.icc (Idealliance) | US sheet-fed coated |
| SWOP 2013 | CGATS21 CRPC5 | SWOP2013C3_CRPC5.icc (Idealliance) | US web offset, publication |
| Japan Color 2011 Coated | Japan Color 2011 | JapanColor2011Coated.icc | Japan sheet-fed coated |

Use the profile the printer sends. Downloading ECI or Idealliance profiles requires the user's
permission; ask, or ask the printer.

Rendering intent: relative colorimetric with black point compensation (BPC) for vectors, text and
brand colours; perceptual for photographs with large out-of-gamut areas; absolute colorimetric
only to simulate paper white on a proofer.

```bash
magick photo.jpg -profile sRGB.icc -intent Perceptual -black-point-compensation \
       -profile PSOcoated_v3.icc photo_cmyk.tif      # first -profile assigns (or converts from embedded)
```

```python
import io
from PIL import Image, ImageCms                      # verified with Pillow 13
img = Image.open("photo.jpg"); icc = img.info.get("icc_profile")
src = ImageCms.ImageCmsProfile(io.BytesIO(icc)) if icc else ImageCms.createProfile("sRGB")
dst = ImageCms.getOpenProfile("PSOcoated_v3.icc")
cmyk = ImageCms.profileToProfile(img.convert("RGB"), src, dst, outputMode="CMYK",
                                 renderingIntent=ImageCms.Intent.PERCEPTUAL,
                                 flags=ImageCms.Flags.BLACKPOINTCOMPENSATION)
cmyk.save("photo_cmyk.tif", compression="tiff_lzw", icc_profile=dst.tobytes())
```

Whole PDFs convert in Ghostscript (section 9): `-sColorConversionStrategy=CMYK` with
`-sOutputICCProfile=<printer profile>`. Verified: changing the output profile changes the
converted RGB values while DeviceCMYK content (e.g. 100K text) passes through unchanged.
`-dRenderIntent=1 -dBlackPtComp=1` request relative colorimetric with BPC; with Ghostscript's
bundled test profiles they changed nothing measurable, so confirm their effect on a soft proof
with the real profile, and pre-convert photos perceptually (above) when the intent matters.

## 5. Black and ink

| Element | Build | Why |
|---|---|---|
| Large black areas | rich black C60 M40 Y40 K100 (240 %) or the printer's recipe | 100K alone prints dark gray |
| Body and small text, hairlines | 100K only | 4-colour text blurs on misregistration |
| Never in artwork | Registration (C100 M100 Y100 K100, 400 %) | over every limit; only for printer's marks |

RGB #000000 text converted through an ICC profile becomes a 4-colour black: set text as
DeviceCMYK 0/0/0/100 at the source (CSS `device-cmyk(0 0 0 1)` in WeasyPrint, a 100K swatch in
layout apps).

Total ink (TAC) limits, unless the printer says otherwise: 300-330 % coated, 260-300 % uncoated,
about 240 % newsprint. Measure averages and peaks:

```bash
gs -q -o - -sDEVICE=ink_cov flyer.pdf   # per page, % ink amount: "11.93285  7.71745  7.71745 17.41259 CMYK OK"
gs -q -o - -sDEVICE=inkcov  flyer.pdf   # per page, FRACTION of area touched by each ink (0-1), not amount
"$PY" -I "$TAC" flyer.pdf --limit 300   # peaks: renders tiffsep separations and sums the inks per pixel
```

Averages never reveal a 400 % patch; peaks do. Verified `tac_check.py` output on a test page with a
small registration-black square and a 240 % rich-black band:

```text
page 1: max TAC 400 % at (105.8, 103.1) mm; 0.15 % of the area above 300 % -> OVER
        spot BrandRed: max 100 %
```

Acrobat Pro's Output Preview (Total Area Coverage highlight) gives the same answer interactively.

## 6. Overprint and knockout

- Black text and fine black lines overprint (no white halo when plates shift); most RIPs force
  100K text to overprint anyway.
- White and light objects never overprint: white overprinting vanishes, light colours mix with
  what is underneath.
- Simulate before sending: `gs -o sim_%02d.png -sDEVICE=png16m -r150 -dOverprint=/simulate flyer.pdf`,
  or Acrobat Output Preview with Simulate Overprinting.
- Spot colours stay Separation (or DeviceN) spaces named exactly as in the printer's guide; convert
  them to CMYK only when told.
- Dielines, spot varnish, foil and white ink live on named spot layers ("Dieline", "Varnish"),
  100 % tint, set to overprint, never mixed into the CMYK artwork. `tac_check.py` lists every
  spot separation, so a stray or misnamed spot shows up.

## 7. Fonts and fine detail

- `pdffonts flyer.pdf`: every row `emb yes` (subsets fine); investigate Type 3 fonts. Outline text
  only as a last resort (it loses searchability and accessibility).
- Reversed (knocked-out) text at least 8 pt, sans or sturdy serif, not knocked out of 4-colour
  builds when small.
- Lines at least 0.25 pt; heavier for reversed or 4-colour lines.
- Small text in one ink (100K or a spot), never a 4-colour build; no RGB rich-black body text.

## 8. Boxes and marks

```bash
pdfinfo -box -f 1 -l 1 flyer.pdf     # MediaBox, CropBox, BleedBox, TrimBox, ArtBox
```

A5 with 3 mm bleed and no marks: MediaBox = BleedBox = 0 0 436.54 612.28, TrimBox = 8.50 8.50
428.03 603.78. PDF/X needs a TrimBox (or ArtBox) on every page, with TrimBox ⊆ BleedBox ⊆ MediaBox.

Verified Ghostscript behaviour: in PDF/X mode, a page without a TrimBox gets TrimBox = BleedBox =
MediaBox (the bleed silently becomes part of the trim); an existing TrimBox and BleedBox are kept.
So set the boxes at the source and confirm with `pdfinfo -box` after every conversion. To add
them to a finished PDF (`uv add pikepdf`):

```python
import pikepdf
b = 3 * 72 / 25.4                                     # 3 mm bleed in points
with pikepdf.open("flyer_rgb.pdf") as pdf:
    for page in pdf.pages:
        x0, y0, x1, y1 = (float(v) for v in page.mediabox)
        page.obj["/TrimBox"] = pikepdf.Array([x0 + b, y0 + b, x1 - b, y1 - b])
        page.obj["/BleedBox"] = pikepdf.Array([x0, y0, x1, y1])
    pdf.save("flyer_boxed.pdf")
```

Crop marks sit outside the trim with an offset of at least the bleed (so they never print into the
bleed), 0.25 pt in Registration, and the MediaBox grows to hold them. Many printers impose and add
their own marks: ask before adding any.

## 9. PDF/X export

| Standard | ISO | Based on | Colour | Transparency | Use |
|---|---|---|---|---|---|
| PDF/X-1a:2001 / :2003 | 15930-1 / 15930-4 | PDF 1.3 / 1.4 | CMYK and spot only | flattened | only when the printer demands it |
| PDF/X-3:2002 / :2003 | 15930-3 / 15930-6 | PDF 1.3 / 1.4 | also ICC-based RGB/Lab | flattened | legacy colour-managed workflows |
| PDF/X-4 | 15930-7 | PDF 1.6 | CMYK, spot, ICC-based RGB/Lab | live; layers allowed | default choice |
| PDF/X-6 | 15930-9 | PDF 2.0 | as X-4 | live | only on request |

All of them: fonts embedded, an OutputIntent naming the printing condition (X-4 embeds the ICC
profile), a TrimBox or ArtBox per page, a Trapped key, no encryption.

Routes:

1. Layout apps (InDesign, Affinity, Scribus): the PDF/X-4 preset with the printer's profile as
   output intent and the bleed from the spec.
2. HTML: WeasyPrint supports `@page { bleed: 3mm; marks: crop }`, CSS `device-cmyk()` and
   `@color-profile`; its docs (v70) list `--pdf-variant pdf/x-1a | pdf/x-3 | pdf/x-4 | pdf/x-5g`
   and `--output-intent` (check `weasyprint --help` for the installed version). Paged.js prints
   through Chrome: an RGB PDF without PDF/X, so convert it with Ghostscript.
3. Ghostscript with an edited copy of `PDFX_def.ps` (verified on 10.07: `-dPDFX=1` writes
   PDF/X-1a:2001, `3` PDF/X-3:2002, `4` PDF/X-4; ColorConversionStrategy must be CMYK or Gray):

```bash
GSLIB=$(dirname "$(find /usr/local/share/ghostscript /opt/homebrew/share/ghostscript /usr/share/ghostscript \
         -name PDFX_def.ps 2>/dev/null | head -1)")
PROF="$PWD/profiles"                                  # holds the printer's PSOcoated_v3.icc
sed -e "s#^/ICCProfile (.*) def#/ICCProfile ($PROF/PSOcoated_v3.icc) def#" \
    -e "s#(CGATS TR001)#(FOGRA51)#" -e "s#(Commercial and specialty printing)#(PSO Coated v3)#" \
    "$GSLIB/PDFX_def.ps" > PDFX_def.ps
gs -dPDFX=4 -dBATCH -dNOPAUSE -sDEVICE=pdfwrite -sColorConversionStrategy=CMYK \
   -sOutputICCProfile="$PROF/PSOcoated_v3.icc" -dRenderIntent=1 -dBlackPtComp=1 \
   --permit-file-read="$PROF/" -sOutputFile=flyer_x4.pdf "$PWD/PDFX_def.ps" flyer_boxed.pdf
qpdf --check flyer_x4.pdf                             # structure; exit 0 = no errors found
```

Verified traps: pass `PDFX_def.ps` by absolute path (a bare name runs Ghostscript's own unedited
copy from its library path); without `--permit-file-read` SAFER refuses to read a profile outside
Ghostscript's directories (`/invalidfileaccess`); GRACoL 2013 uses the identifier `CGATS21_CRPC6`;
add `-dWriteObjStms=false -dWriteXRefStm=false` to inspect the result with `grep -a GTS_PDFXVersion`.
Recent poppler `pdfinfo` prints a "PDF subtype" line for declared PDF/X files: declared is not
compliant. veraPDF validates PDF/A, PDF/UA and WTPDF, not PDF/X.

## 10. Preflight report

| Check | Command | Expected | Result | Pass |
|---|---|---|---|---|
| Size and boxes | `pdfinfo -box` | trim and bleed per spec | | |
| Effective ppi | `pdfimages -list` | ≥ 300 (≥ 150 large format) | | |
| Colour spaces | `pdfimages -list` color column, Output Preview | CMYK and agreed spots (X-4: ICC RGB allowed) | | |
| Fonts | `pdffonts` | all emb yes, no Type 3 | | |
| Ink average | `gs -sDEVICE=ink_cov` | information | | |
| Peak TAC | `tac_check.py --limit <TAC>` | ≤ limit | | |
| Black text | separations or Output Preview | 100K only | | |
| Overprint | `gs -dOverprint=/simulate` render | black overprints, no white overprint | | |
| Spot list | `tac_check.py` separations | exactly the agreed spots | | |
| PDF/X | `pdfinfo`, output intent | X-4, named condition | | |
| Structure | `qpdf --check` | no errors | | |
| Certification | pdfToolbox or Acrobat Preflight with the printer's profile | pass | user or printer step | open |

## 11. Proofing

- Soft proof: calibrated monitor, simulate paper colour and black ink with the output profile,
  gamut warning on; large out-of-gamut areas trigger perceptual conversion or a spot colour.
- Hard proof on the actual stock for brand-critical work: a contract proof to ISO 12647-7 with a
  measured media wedge, or a press proof; press check for high-value jobs.
- Uncoated stock gains more dot: midtones and shadows darken, colours dull. The uncoated profile
  compensates part of it; never send a coated-profile file for uncoated paper, and pick Pantone U
  (not C) references for comparison.

## 12. Worked example: A5 flyer from HTML

Spec: A5, 3 mm bleed, 5 mm safe zone, PSO Coated v3 (FOGRA51), TAC 300 %, PDF/X-4, no spots,
170 gsm gloss coated, no marks. Hero photo 2000 × 2800 px.

1. Layout (WeasyPrint): the page background paints into the bleed; the margin keeps type inside the
   safe zone; text is DeviceCMYK 100K.

```css
@page { size: 148mm 210mm; bleed: 3mm; margin: 5mm; background: #1A1A2E url(hero.jpg) center / cover; }
body  { font: 10pt/1.4 "Inter", sans-serif; color: device-cmyk(0 0 0 1); }
h1    { font: 700 30pt/1.1 "Inter", sans-serif; color: #FFFFFF; }   /* reversed, well above 8 pt */
```

2. Render and check boxes: `weasyprint flyer.html flyer_rgb.pdf`, then `pdfinfo -box`; expect
   MediaBox 436.54 × 612.28 pt and TrimBox 8.50 8.50 428.03 603.78. If the TrimBox is missing or
   equals the MediaBox, add it with the pikepdf snippet (section 8) → `flyer_boxed.pdf`.
3. Resolution: `cover` scales the 2000 × 2800 px hero by the axis that needs more enlargement,
   2800 px over 216 mm (8.50 in) = 329 ppi, and crops the width; `pdfimages -list` should report
   about 329 × 329 (≥ 300: pass). Check a render too: the background must reach the BleedBox edge.
4. Convert and export: the Ghostscript X-4 command in section 9 with PSO Coated v3 → `flyer_x4.pdf`.
   If the soft proof clips the photo badly, pre-convert it perceptually (section 4) and re-render.
5. Verify: `pdfinfo -box` (boxes survived), `pdffonts` (emb yes), `pdfimages -list` (cmyk),
   `gs -sDEVICE=ink_cov` and `tac_check.py --limit 300` (peak ≤ 300 %; the dark background is
   where rich builds pile up), overprint simulation render, `qpdf --check`.
6. Deliver `flyer_A5_PSOcoatedv3_X4.pdf` plus the filled section 10 table, with open doubts:
   certification by pdfToolbox or Acrobat Preflight with the printer's profile (their step), and a
   contract proof if the brand pink is critical.

## Pitfalls

- Missing bleed, or a TrimBox equal to the MediaBox after conversion (the bleed gets printed).
- Web-resolution images (72-150 ppi) placed at print size; silent upscaling.
- 4-colour small text and RGB black text turned into rich black; hairlines under 0.25 pt.
- White or light objects set to overprint; Registration colour used in artwork.
- Pantone or CMYK brand values taken from an automatic conversion instead of a printed guide and a
  proof (`brand-guidelines-system`).
- Converting to a generic profile instead of the printer's printing condition; coated profile on
  uncoated stock.
- Trusting ink averages (`ink_cov`, `inkcov`) as a TAC check; peaks fail preflight.
- Editing the wrong `PDFX_def.ps`, or a SAFER refusal hidden in a long Ghostscript log.

Related: `brand-guidelines-system`, `layout-grids-posters-editorial`, `oklch-palette-ramps`, `photo-retouch-composite`, `type-scale-systems`, `logo-design-process`, hub `graphic-design`
