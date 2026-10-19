# Logo export kit

## 1. Naming and folders

`<brand>-<lockup>-<colourway>[@<scale>x].<ext>`; lockup in {mark, horizontal, stacked, wordmark};
colourway in {fullcolour, black, white, grayscale, pms, cmyk}.

```text
brand/logo/
  svg/  brackenby-mark-black.svg  brackenby-mark-white.svg  brackenby-horizontal-fullcolour.svg ...
  pdf/  brackenby-horizontal-fullcolour.pdf  (vector; print hand-off adds CMYK and spot versions)
  png/  brackenby-mark-black@1x.png @2x @3x  (transparent, sRGB)
  web/  favicon.ico  favicon.svg  apple-touch-icon.png  icon-192.png  icon-512.png  icon-mask.png
        manifest.webmanifest
  source/ master files with construction grid and keylines (not for distribution)
  USAGE.md  clear space, minimum sizes, colourways, backgrounds, misuse (brand-guidelines-system)
```

## 2. SVG master checklist

- `viewBox` set, no fixed width/height or the intended default; one or few closed paths; booleans
  united; no strokes (outline strokes so scaling cannot change weight); no `<text>`; no raster;
  no editor metadata (`svgcheck.py sanitize` when not layered); ids prefixed when inlined
  (`svgcheck.py prefix-ids`); `svgcheck.py check --budget logo` exits 0 (20 KB, 150 paths,
  3 decimals).
- Colour versions differ only in fill values; the one-colour version uses `currentColor` when
  it will be inlined in web pages.

## 3. favicon.svg with dark mode

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
  <style>path { fill: #111111 } @media (prefers-color-scheme: dark) { path { fill: #FFFFFF } }</style>
  <path fill-rule="evenodd" d="..."/>
</svg>
```

## 4. HTML and manifest

```html
<link rel="icon" href="/favicon.ico" sizes="32x32">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/manifest.webmanifest">
```

```json
{ "icons": [
  { "src": "/icon-192.png", "type": "image/png", "sizes": "192x192" },
  { "src": "/icon-512.png", "type": "image/png", "sizes": "512x512" },
  { "src": "/icon-mask.png", "type": "image/png", "sizes": "512x512", "purpose": "maskable" } ] }
```

- `sizes="32x32"` on the ICO link (not `any`) so browsers that support SVG do not fetch both.
- Keep `maskable` and `any` icons separate: a maskable icon used as `any` shows its padding.
- Maskable safe zone: everything important inside a centred circle of radius 40% of the icon
  (204.8 px at 512); launchers may crop the rest. Preview at maskable.app or in Chrome DevTools
  (Application, Manifest, Icons, show only the minimum safe area).
- Apple touch icon: 180 x 180, opaque background (transparency renders black), about 20 px
  padding (mark within 140 px); iOS applies its own corner mask.

## 5. logo_kit.py

```bash
"$PY" -I scripts/logo_kit.py mark.svg --name brackenby-mark --out kit --width 240 \
  --small mark-16.svg --bg '#1A1A2E' --fg-on-bg mark-reversed.svg
```

| Output | How it is built |
|---|---|
| `<name>@1x/2x/3x.png` | resvg render at width, 2x, 3x; transparent |
| `favicon.ico` | Pillow ICO with a 32 px frame from the master and a 16 px frame from `--small` (a hand-fitted variant) when given |
| `apple-touch-icon.png` | `--fg-on-bg` mark fitted into 140 px on an opaque 180 px `--bg` square |
| `icon-192.png`, `icon-512.png` | transparent, mark at 84% of the canvas |
| `icon-mask.png` | opaque `--bg`, mark fitted into a square of side 0.8 x 512 / sqrt(2) so all ink lies inside the safe circle; the measured ink radius is printed |

## 6. Print hand-off (to print-prepress-pdfx)

| Item | Content |
|---|---|
| Vector master | PDF from `mcp__image__export_pdf` (RGB) plus the SVG |
| Spot colour | the Pantone Coated and Uncoated references chosen against physical guides, named swatch in the separation |
| CMYK | values converted with the printer's ICC profile (e.g. PSO Coated v3 / FOGRA51, GRACoL 2013 / CRPC6), relative colorimetric with black point compensation; confirmed on a proof |
| One-colour | 100K black version for small and newspaper use |
| Minimums | smallest print size in mm and the thinnest feature at that size |
| Special processes | embroidery (min line about 1 mm, satin stitch direction, max colours), engraving (min line about 0.3 mm), foil or emboss (no fine counters) |

## 7. Usage table template

| Lockup | Min px | Min mm | Clear space | Colourways | Approved backgrounds (measured contrast) |
|---|---|---|---|---|---|
| Mark | 16 | 6 | 0.25 x mark height | black, white, brand | #111 mark on white 18.88:1; white mark on #1A1A2E 17.06:1 (never #111 on #1A1A2E: 1.11:1) |
| Horizontal | 96 | 25 | 0.25 x mark height | full colour, black, white | white, #1A1A2E, photos with a plate |
| Stacked | 64 | 18 | 0.25 x mark height | full colour, black, white | as horizontal |
