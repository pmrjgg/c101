# Text templates, rendering, logos and compositing

Text and logos are layers over the art, rendered from templates with the brand's font files.
Everything below ran with the stack venv (Pillow 13, resvg_py 0.5).

## 1. SVG template with slots

One template per placement, positions taken from `kitcheck plan` copy bands (square: bottom
band x 135-945, y 865-1080; logo in the top band).

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1080" viewBox="0 0 1080 1080">
  <style>
    .h   { font: 700 64px Inter, Helvetica, Arial, sans-serif; fill: #FFFFFF; letter-spacing: -1.3px; }
    .sub { font: 400 30px Inter, Helvetica, Arial, sans-serif; fill: #FFFFFF; }
    .cta { font: 700 28px Inter, Helvetica, Arial, sans-serif; fill: #FFFFFF; }
  </style>
  <image href="logo-reversed.svg" x="135" y="56" width="160" height="40"/>
  <text class="h" x="135" y="964">{headline}</text>
  <text class="sub" x="135" y="1012">{sub}</text>
  <rect x="765" y="972" width="180" height="56" rx="8" fill="#D63151"/>
  <text class="cta" x="855" y="1010" text-anchor="middle">{cta}</text>
</svg>
```

- `y` on `<text>` is the baseline. Keep baselines on the layout's spacing scale.
- SVG text does not wrap: fit or break lines yourself (section 3).
- The CTA label on #D63151 is white at 4.75:1; check any new button colour with the WCAG formula
  and the button against the art (3:1 non-text contrast).

## 2. Render and composite

```python
# render.py: "$PY" -I render.py square.svg art.png out.png '{"headline": "...", "sub": "...", "cta": "..."}'
import json, sys
from xml.sax.saxutils import escape
import resvg_py
from PIL import Image

tpl, art, out = sys.argv[1], sys.argv[2], sys.argv[3]
svg = open(tpl, encoding="utf-8").read()
for k, v in json.loads(sys.argv[4]).items():
    svg = svg.replace("{%s}" % k, escape(v))               # &, <, > in copy must not break the XML
png = resvg_py.svg_to_bytes(svg_string=svg, width=1080, height=1080,
                            font_files=["fonts/Inter-Bold.otf", "fonts/Inter-Regular.otf"],
                            resources_dir=".")             # resolves the logo <image href>
open(out + ".text.png", "wb").write(png)                   # keep the text layer for re-use and QA
layer = Image.open(out + ".text.png").convert("RGBA")
Image.alpha_composite(Image.open(art).convert("RGBA"), layer).convert("RGB").save(out)
```

`svg_to_bytes` also accepts `font_dirs`, `background`, `dpi` and `skip_system_fonts=True` (use
it to prove that only the brand fonts are used: a missing font then renders nothing instead of
silently falling back). CLI alternative: `rsvg-convert -w 1080 -h 1080 -o text.png text.svg`
(fonts via fontconfig).

HTML templates suit long copy that must wrap: render the text layer with Playwright on a
transparent page.

```python
page = browser.new_page(viewport={"width": 1080, "height": 1350})
page.set_content(html)                                   # body { background: transparent }
page.screenshot(path="text.png", omit_background=True)
```

## 3. Fitting copy

```python
from PIL import ImageFont
def fit(text, font_path, max_w, start, min_size, index=0):
    """Largest size (1 px steps) at which text fits max_w on one line, with its width; None below min_size."""
    for size in range(start, min_size - 1, -1):
        f = ImageFont.truetype(font_path, size, index=index)
        if f.getlength(text) <= max_w:
            return size, round(f.getlength(text))
    return None
```

`fit("Orbit 2 is here", "/System/Library/Fonts/Helvetica.ttc", 810, 96, 40, index=1)` returned
`(96, 646)`. Rules: never shrink below the placement minimum (headline about 48 px on 1080-wide
social, 18-20 px on a 300 x 250 ad); if the copy does not fit, break it into two balanced lines
or shorten it with the copywriter; use the same size for the same role across all placements of
a size class so the kit looks like one family.

## 4. Logos

- Use the supplied master files (SVG or PDF); pick the version by ground: full colour on light,
  reversed or mono on dark or busy art.
- Minimum size and clear space come from the brand guidelines (often clear space = the cap
  height of the wordmark or the height of the mark); if none exist, keep at least the logo's
  x-height or 1/4 of its height free on every side and state the assumption.
- Same logo position and relative size in every placement of a size class; on display ads it
  sits inside the 4% frame padding.
- Check non-text contrast of the logo against the art (3:1 for meaningful graphics) with
  `kitcheck contrast --box <logo box> --text <logo colour> --large`.

## 5. Compositing products or cut-outs on brand grounds

For banner shapes where outpainting would invent most of the frame, composite a transparent
product asset on a flat or gradient ground:

```bash
"$PY" "$MT" over product.png ground-728x90.png banner.png --scale 0.18 --x 560 --y 4
```

The product asset comes from `image_generate_transparent` or `image_remove_background` (sibling
skills `image-generation` and `image-editing`); inspect the alpha edge on light and dark grounds
before compositing.

## 6. Scrims and panels

- Gradient scrim (solved by `kitcheck scrim`): behind text on photos with a light region; keep the
  fade long enough (>= half the text box height) that the edge is not visible.
- Solid panel: when the solved scrim alpha exceeds about 0.6 (the photo turns murky) or the art
  is busy; panel colour from the palette, contrast measured like any text pair.
- Do not rely on thin shadows or outlines: they break under platform compression and resizing.
  Measure the text colour against the art itself and fix the art (scrim, panel, other band).
