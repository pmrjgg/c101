# Tracing reference (raster to vector)

`image_vectorize` (op `IMAGE_TRACE`) traces with exactly the backend the user configured; there is
no provider list and no fallback. What you get depends on the adapter `image_ops_status` reports:

| Adapter (configuration) | What it is | Fidelity | Palette control | Layers |
|---|---|---|---|---|
| fal, `IMAGE_TRACE_MODEL=fal-ai/recraft/vectorize` (URL `https://queue.fal.run`) | Recraft vectorize: a real tracer | good, fast, cheap (~$0.01) | none exposed: pre-quantise the input | `layered: true` → one layer per colour (server post-processing) |
| local, `IMAGE_TRACE_API=local` | vtracer (MIT), runs in the server, deterministic, free | good on flat art; depends entirely on input prep | input palette, plus vtracer settings | same |
| OpenRouter, a Recraft `*-vector` model with the raster as the single reference | not a trace: the model redraws "a vector version of" the input | shapes, proportions and lettering drift | prompt only | same |
| Opper | no tracing model; the adapter refuses TRACE | - | - | - |

Rules:
- A logo, mark or anything that must stay identical needs a real tracer (fal or local). If TRACE is
  OpenRouter, return an Open doubt naming `IMAGE_TRACE_API=local` or `IMAGE_TRACE_URL`,
  `IMAGE_TRACE_KEY`, `IMAGE_TRACE_MODEL` (fal) instead of shipping a redraw as a trace.
- TRACE not configured: Open doubt with those names. Do not run vtracer or any other tracer
  yourself as a substitute; local tracing is an explicit configuration choice of the user.
- Inputs: PNG, JPEG or WebP. fal Recraft vectorize accepts under 5 MB and 16 MP, 256-4096 px per
  side; downscale or crop larger sources first.

## Choosing settings

| Decision | Choose | When |
|---|---|---|
| Colour count | exact brand count (2-8) | logos; pre-quantise to the same count |
| | 8-24 | flat illustrations |
| | 2 (binary) | line art, stamps, signatures, scans |
| Layers | `layered: true` | screen printing, vinyl, laser, embroidery prep, or any editable hand-off by colour |
| Stacking | stacked (shapes overlap) | screen use: fewer shapes, no hairline gaps between colours |
| | cut-out (shapes tile without overlap) | cutters, plotters, embroidery: overlap means double work |
| Output after tracing | SVG master | web, apps, further editing |
| | `export_pdf` (layered) | print hand-off; RGB only |

Stacking is a tracer setting: on the local adapter it is vtracer's `hierarchical` (`stacked` or
`cutout`); fal's Recraft endpoint does not expose it.

## Local adapter: vtracer settings

When `IMAGE_TRACE_API=local`, vtracer options can be fixed by the user in `IMAGE_TRACE_PARAMS`
(JSON) or passed per call in `params` if the tool schema offers it; anything the server does not
forward is reported in the result's `notes` / `warnings`.

| vtracer parameter | Effect | Typical change |
|---|---|---|
| `colormode` | `color` or `binary` | `binary` for line art (much faster) |
| `hierarchical` | `stacked` or `cutout` | per the stacking row above |
| `mode` | `spline`, `polygon`, `none` | `polygon` for pixel art and strictly geometric marks |
| `filter_speckle` | discard patches smaller than N px | 8-16 on noisy scans |
| `color_precision` | significant bits per RGB channel | lower (4-5) merges shades |
| `layer_difference` | colour difference between layers | higher (24-32) for fewer colours |
| `corner_threshold` | degrees below which a corner stays sharp | lower (30-45) keeps more sharp corners on logos |
| `length_threshold` | minimum segment length (3.5-10) | higher smooths wobble |
| `splice_threshold` | angle for splitting splines | rarely changed (45) |
| `path_precision` | decimals in output | 2-3 |

## Preprocessing recipes (Pillow via the stack venv `PY`)

```bash
# Small logos (short side under 1000 px): get an upscale first (image-editing; native or local
# UPSCALE, never a regenerating one for a logo), then:
# 1. Flatten alpha onto white (tracers handle opaque input most predictably)
"$PY" -c "from PIL import Image; im=Image.open('in.png').convert('RGBA'); bg=Image.new('RGBA', im.size, (255,255,255,255)); Image.alpha_composite(bg, im).convert('RGB').save('flat.png')"
# 2. Light denoise for JPEG sources (median 3 keeps edges)
"$PY" -c "from PIL import Image, ImageFilter; Image.open('flat.png').filter(ImageFilter.MedianFilter(3)).save('dn.png')"
# 3. Quantise to K colours without dithering
"$PY" -c "from PIL import Image; Image.open('dn.png').quantize(colors=4, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert('RGB').save('q.png')"
# 4. Binary for line art
"$PY" -c "from PIL import Image; Image.open('dn.png').convert('L').point(lambda v: 255 if v > 160 else 0).save('bw.png')"
```

Read each intermediate before tracing: merged colours that should stay distinct mean K is too low.
The trace cannot be better than its input.

## Post-trace checks

1. `svg_inspect` (path count, palette, layers) and `python3 -I "$SVG" check traced.svg --budget logo`
   (or `illustration`).
2. Palette larger than requested: anti-aliased edge colours survived. `remap --merge 20` then
   `--max-colors K`, or re-trace from a better-quantised source. With `layered: true`, remap before
   layering (or re-layerize after) so each layer is one clean colour.
3. Render and compare with the source on one sheet: `svg_render {svg_path, width: 512}`, plus the
   smallest real size; `"$PY" "$IMG" sheet cmp.png source.png traced-512.png traced-32.png`. Look
   for rounded corners that should be sharp, wobbly straight lines, lost small counters, speckles,
   hairline gaps between colours.
4. Corner and line quality problems on a logo: adjust preprocessing or vtracer settings and re-trace
   once; then rebuild the simplest shapes by hand ([svg-editing](svg-editing.md)) and keep traced
   paths only for organic parts.
5. Hairline gaps with stacked art in a renderer: add a 0.25-0.5 px stroke in the fill colour to the
   affected shapes (`stroke="<fill>" stroke-width="0.4"`), or re-trace with `hierarchical: stacked`
   on the local adapter.

For pure black-and-white art, `colormode: binary` on the local adapter gives the cleanest result;
potrace-style output is not available through the server.
