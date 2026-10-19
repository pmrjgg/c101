# Font loading without layout shift

Pipeline: licensed source font -> limit variable axes -> subset per script -> WOFF2 -> @font-face
with `unicode-range` -> preload the critical file -> metric-matched fallback -> verify CLS.

## 1. Build the files

```bash
# axes: keep only what the design uses (wght 400-700; opsz kept because it is not mentioned)
uvx --from fonttools fonttools varLib.instancer inter-var.ttf wght=400:700 -o inter-400-700.ttf
#   pin an axis: wdth=100    drop an axis at its default: opsz=drop    static instance: --static

# one subset per script; add every OpenType feature the CSS uses
uvx --from fonttools --with brotli pyftsubset inter-400-700.ttf \
  --unicodes="U+0000-00FF,U+0131,U+0152-0153,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2212" \
  --layout-features+=tnum,lnum,case,ss01,zero \
  --flavor=woff2 --output-file=inter-latin.woff2
uvx --from fonttools --with brotli pyftsubset inter-400-700.ttf \
  --unicodes="U+0100-024F,U+1E00-1EFF,U+20A0-20CF,U+2C60-2C7F,U+A720-A7FF" \
  --layout-features+=tnum,lnum,case,ss01,zero \
  --flavor=woff2 --output-file=inter-latin-ext.woff2
ls -l *.woff2                        # budget: a latin variable subset is usually tens of KB
```

| Option | Effect |
|---|---|
| `--unicodes=` / `--unicodes-file=` / `--text=` | code points to keep (ranges as hex) |
| `--layout-features+=a,b` | add to the default list; `--layout-features='*'` keeps all (bigger) |
| `--layout-scripts=latn,cyrl` | keep only these OpenType scripts (default all) |
| `--flavor=woff2` | WOFF2 output; needs the Brotli module |
| `--no-hinting` | drop hinting (smaller; check Windows rendering of small sizes first) |
| `--desubroutinize` | CFF fonts: larger raw, often smaller after WOFF2 compression |
| `--name-IDs=` | name records kept (default 0-6) |

Script ranges (Unicode blocks; extend for the copy deck):

| Subset | Ranges |
|---|---|
| latin (core) | U+0000-00FF, U+0131, U+0152-0153, U+02C6, U+02DA, U+02DC, U+2000-206F, U+20AC, U+2122, U+2212 |
| latin-ext | U+0100-024F (Extended-A/B), U+1E00-1EFF (Extended Additional), U+20A0-20CF (currency), U+2C60-2C7F, U+A720-A7FF |
| vietnamese | U+0102-0103, U+0110-0111, U+0128-0129, U+0168-0169, U+01A0-01A1, U+01AF-01B0, U+0300-0323, U+1EA0-1EF9, U+20AB |
| greek | U+0370-03FF, U+1F00-1FFF |
| cyrillic | U+0400-04FF, U+0500-052F |

Check the subset kept what matters: `fonttools ttx -t cmap -t GSUB -o - inter-latin.woff2` (Brotli
needed to read WOFF2), or drop the file on wakamaifondue.com and look at features and glyphs.

## 2. CSS

```css
@font-face {
  font-family: "Inter";
  src: url("/fonts/inter-latin.woff2") format("woff2");
  font-weight: 400 700;            /* variable range */
  font-style: normal;
  font-display: swap;
  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02C6, U+02DA, U+02DC, U+2000-206F,
                 U+20AC, U+2122, U+2212;
}
@font-face {
  font-family: "Inter";
  src: url("/fonts/inter-latin-ext.woff2") format("woff2");
  font-weight: 400 700; font-style: normal; font-display: swap;
  unicode-range: U+0100-024F, U+1E00-1EFF, U+20A0-20CF, U+2C60-2C7F, U+A720-A7FF;
}
@font-face {                        /* from fallback_css.py Inter Arial */
  font-family: "Inter Fallback";
  src: local("Arial"), local("ArialMT");
  size-adjust: 107.12%; ascent-override: 90.44%; descent-override: 22.52%; line-gap-override: 0%;
}
html { font-family: "Inter", "Inter Fallback", sans-serif; }
```

```html
<link rel="preload" href="/fonts/inter-latin.woff2" as="font" type="font/woff2" crossorigin>
```

Rules: preload only files the first viewport needs (each preload competes with CSS and the hero
image); the preload URL must match the @font-face URL exactly or the font downloads twice; the
`crossorigin` attribute is required for fonts even on the same origin. Italic is a second file
(or a `slnt`/`ital` axis); do not let the browser synthesise it.

## 3. Fallback metrics

| Route | Code |
|---|---|
| stdlib | `python3 -I scripts/fallback_css.py Inter Arial` (built-in metrics: Inter, Arial, Georgia, Source Serif 4, Source Sans 3, IBM Plex Sans/Serif, Noto Sans/Serif, Fraunces, Literata) |
| any font file | `uv run --no-project --with fonttools python -I -c "from fontTools.ttLib import TTFont; f=TTFont('X.ttf'); h=f['hhea']; print(f['head'].unitsPerEm, h.ascent, h.descent, h.lineGap, f['OS/2'].sxHeight, f['OS/2'].xAvgCharWidth)"`, then pass them with `--metrics` (xWidthAvg: Capsize weights glyph widths by letter frequency; `xAvgCharWidth` is a rougher stand-in) |
| Capsize | `createFontStack([inter, arial])` with `import inter from '@capsizecss/metrics/inter'`; returns `{ fontFamily, fontFaces }`; `@capsizecss/unpack` `fromFile(path)` for unlisted fonts |
| fontaine | `FontaineTransform.vite({ fallbacks: ['Segoe UI', 'Helvetica Neue', 'Arial', 'Noto Sans'], resolvePath: (id) => new URL('./public' + id, import.meta.url) })` |

Formulas (Capsize): size-adjust = (font xWidthAvg / font upm) / (fallback xWidthAvg / fallback
upm); ascent-override = font ascent / (font upm x size-adjust); same for |descent| and lineGap.
Several fallbacks (Arial on Windows/macOS, Roboto or Noto Sans on Android) each need their own
@font-face with their own size-adjust.

## 4. Verify

Lighthouse (Node 22+), once with the font blocked (fallback only) and once normally:

```bash
npx lighthouse "$URL" --only-categories=performance --output=json --output-path=lh-fallback.json \
  --quiet --chrome-flags="--headless" --blocked-url-patterns="*.woff2"
npx lighthouse "$URL" --only-categories=performance --output=json --output-path=lh-font.json \
  --quiet --chrome-flags="--headless"
jq '.audits["cumulative-layout-shift"].numericValue' lh-fallback.json lh-font.json   # target 0 (good < 0.1)
```

Lab CLS only sees shifts during the run; a font that arrives before first paint shows no shift
even with a bad fallback. The box comparison catches that case:

```js
// node boxes.mjs http://localhost:3000/docs   (npm i -D playwright; npx playwright install chromium)
import { chromium } from 'playwright';
const url = process.argv[2];
const browser = await chromium.launch();
async function heights(blockFonts) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  if (blockFonts) await page.route('**/*.woff2', (route) => route.abort());
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.evaluate(async () => { await document.fonts.ready; return true; });
  const h = await page.$$eval('h1, h2, h3, p, li', (els) =>
    els.slice(0, 20).map((e) => Math.round(e.getBoundingClientRect().height)));
  await page.close();
  return h;
}
const a = await heights(true), b = await heights(false);
a.forEach((h, i) => console.log(`${i}\tfallback ${h}\tfont ${b[i]}\t${Math.abs(h - b[i]) <= 2 ? 'ok' : 'SHIFT'}`));
await browser.close();
```

Repeat at 360 px width (more wrapping, larger effect). DevTools: Rendering, Layout Shift Regions
shows shifts live; `document.fonts.check('16px Inter')` tells whether the face is ready.
