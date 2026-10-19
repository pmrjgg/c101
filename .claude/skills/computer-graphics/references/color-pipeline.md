# Color pipeline reference

## 1. Spaces and what they mean

A color space = primaries + white point + transfer function. Lighting math needs linear values in
one set of primaries; the transfer function only matters at decode (textures) and encode (display).

| Space | Primaries | White | Transfer | Typical role |
|---|---|---|---|---|
| sRGB | Rec.709 | D65 | piecewise sRGB (≈2.2) | 8-bit textures, SDR web/display |
| Linear Rec.709 | Rec.709 | D65 | linear | default working space for real-time |
| Display P3 | DCI-P3 | D65 | sRGB curve | Apple displays, wide-gamut web (`color(display-p3 ...)`) |
| Rec.2020 / BT.2100 | Rec.2020 | D65 | PQ or HLG | HDR video and HDR10 output |
| ACEScg | AP1 | ~D60 | linear | film/VFX working space (wider than Rec.709) |
| ACES2065-1 | AP0 | ~D60 | linear | archival interchange |
| scRGB | Rec.709 | D65 | linear, 1.0 = 80 nits, negative allowed | Windows HDR swapchains (FP16) |
| OKLab / OKLCh | perceptual | D65 | n/a | gradients, palette generation, gamut mapping |

Matrices (linear, D65):

```
sRGB -> XYZ     [0.4124564 0.3575761 0.1804375]
                [0.2126729 0.7151522 0.0721750]
                [0.0193339 0.1191920 0.9503041]
Rec.709 -> Rec.2020 (BT.2087)
                [0.6274 0.3293 0.0433]
                [0.0691 0.9195 0.0114]
                [0.0164 0.0880 0.8956]
```

Use OpenColorIO configs (ACES studio config, or the Blender/AgX config) rather than hand-typed
matrices for anything involving ACES, chromatic adaptation (Bradford) or camera spaces.

## 2. Transfer functions

```
sRGB decode   c <= 0.04045 ? c/12.92 : ((c + 0.055)/1.055)^2.4
sRGB encode   c <= 0.0031308 ? 12.92 c : 1.055 c^(1/2.4) - 0.055
BT.1886       display EOTF gamma 2.4 (Rec.709 video is graded for this, not for the sRGB curve)
PQ (ST 2084)  Y = L / 10000 nits
              E = ((c1 + c2 Y^m1) / (1 + c3 Y^m1))^m2
              m1 = 0.1593017578125, m2 = 78.84375, c1 = 0.8359375, c2 = 18.8515625, c3 = 18.6875
HLG           relative, scene-referred; broadcast HDR; system gamma depends on display peak
```

GPU formats with `_SRGB` suffix decode on sample and encode on write for free; use them for color
textures and the final SDR swapchain, never for normal, roughness, metalness, AO, masks or LUTs.

## 3. Exposure

```
Physical camera:   EV100 = log2(N² / t) - log2(S / 100)        N f-number, t seconds, S ISO
From scene:        EV100 = log2(L_avg · S / K), S = 100, K = 12.5
Max luminance:     L_max = (78 / (q · S)) · 2^EV100 with q = 0.65  ->  1.2 · 2^EV100
Exposure scale:    pixel = L · (1 / L_max)
```

Auto-exposure: build a log2-luminance histogram (compute shader, 64-256 bins), average between the
50th and 95th percentile to ignore sky and specular outliers, adapt with
`EV += (EV_target - EV) · (1 - exp(-dt · speed))`, separate speeds for brightening and darkening.

## 4. Tonemapping operators

```
Reinhard            x / (1 + x)
Reinhard extended   x (1 + x / Lw²) / (1 + x)              Lw = white point
ACES fit (Narkowicz) (x (2.51 x + 0.03)) / (x (2.43 x + 0.59) + 0.14), clamp 0..1
```

Khronos PBR Neutral (2024), per pixel on linear Rec.709 after exposure:

```
startCompression = 0.8 - 0.04; desaturation = 0.15
x = min(r, g, b); offset = x < 0.08 ? x - 6.25 x² : 0.04; c -= offset
peak = max(r, g, b); if peak < startCompression: return c
d = 1 - startCompression
newPeak = 1 - d² / (peak + d - startCompression)
c *= newPeak / peak
g = 1 - 1 / (desaturation (peak - newPeak) + 1)
return mix(c, vec3(newPeak), g)
```

AgX: log2 encoding inside an inset gamut, a sigmoid, then an outset; take the reference
implementation (Blender, or the three.js / Filament ports) rather than reconstructing constants.

Per-channel curves (Reinhard, ACES fit) shift hue in saturated highlights (orange fire turns
yellow, blue lights go cyan/purple). Operators that compress luminance and desaturate toward
white (AgX, PBR Neutral) avoid the "notorious six" hue skews.

## 5. HDR output

- Decide paper white (BT.2408 suggests 203 nits for HDR reference white) and expose a slider.
- Query display peak (DXGI output desc, `EDR headroom` on Apple via `maximumExtendedDynamicRangeColorComponentValue`, WebGPU canvas `toneMapping: { mode: 'extended' }` where supported).
- Tonemap to the display peak, not to 1.0; encode PQ in Rec.2020 for HDR10 or write scRGB FP16.
- UI composites at paper white; never run the scene tonemapper over UI.

## 6. Quantisation and banding

- Use RGBA16F or R11G11B10F for HDR targets (R11G11B10F has no sign bit and ~5-6 bit mantissas:
  fine for lighting, bad for alpha or negative values).
- Dither before quantising to 8 or 10 bits: triangular-pdf noise of ±1 LSB (sum of two uniform
  ±0.5 LSB) removes visible bands in gradients and fog.
- Quantise in the encoded (perceptual) domain, never store 8-bit linear for color.

## 7. Blending and alpha

- Premultiplied alpha everywhere in the pipeline (`src + dst (1 - src.a)`); straight alpha through
  bilinear filtering or mipmapping produces dark fringes.
- Blending happens in linear space when the render target is `_SRGB` or float; blending in an
  8-bit UNORM target holding sRGB-encoded values darkens mid-tones.
- Mipmap generation for sRGB textures: decode, average in linear, encode.

## 8. Gamut mapping

Out-of-gamut values after converting wide-gamut content (ACEScg, Rec.2020) to Rec.709 have
negative components. Clipping per channel shifts hue. Prefer: reduce chroma in OKLCh at constant
lightness and hue until in gamut, or use the ACES 2.0 / OCIO gamut compression transforms.

## 9. Checks

- Render a gray ramp and a Macbeth/ColorChecker chart in linear, tonemap, and compare against
  values from a reference tool (OCIO `ociocheck`/`ocioconvert`, or a known-good engine).
- Middle gray: 0.18 linear should land near 0.46 sRGB-encoded (≈118/255) with an identity
  display transform at exposure 1.
- Swap the tonemapper to identity and confirm the pre-tonemap buffer contains plausible absolute
  values (white diffuse under ~1e5 lux of sun: L = ρE/π ≈ 0.9 · 1e5 / π ≈ 2.9e4 cd/m²; if the
  engine uses arbitrary units, document the scale factor).
