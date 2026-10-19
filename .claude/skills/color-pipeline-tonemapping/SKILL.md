---
name: color-pipeline-tonemapping
description: "Scene-referred color management for renderers and image tools covering sRGB decode and encode, primaries and white points (Rec.709, P3, Rec.2020, ACEScg), OCIO configs, exposure and auto-exposure, tonemappers (AgX, ACES 2.0, Khronos PBR Neutral, Reinhard), HDR output (PQ, scRGB, EDR), banding, alpha and gamut mapping. Load when images look washed out, too dark, hue-shifted or banded, or wrong on HDR displays."
when_to_use: "Textures or swapchains with the wrong _SRGB/UNORM format; images too dark, washed out, oversaturated or hue-shifted; choosing or implementing AgX, ACES 2.0, PBR Neutral or Reinhard; OCIO configs, ocioconvert or colour-science matrices; physical exposure, EV100 or auto-exposure; HDR10/PQ, scRGB, EDR or paper-white settings; banding and dithering; RGBA16F vs R11G11B10F; dark alpha fringes; wide-gamut conversion and gamut mapping."
---

# Color pipeline and tonemapping

Rule zero: every texture, buffer and swapchain has a declared encoding and primaries, and an image is
decoded exactly once and encoded exactly once. Numbers below come from
[references/color-checks.md](references/color-checks.md) (NumPy; matrices re-derived, test pairs checked).

## 1. Pipeline order and per-buffer conventions

decode → linear working space (lighting) → exposure → display transform (tonemap, gamut map) → encode.

| Data | Format | Why |
|---|---|---|
| baseColor/albedo, emissive colour, sheen and specular colour, UI and sprite textures | `*_SRGB` (decoded on sample, before filtering) | authored as sRGB-encoded colour |
| normal, roughness, metallic, occlusion, ORM packs, height, masks, flow maps, noise, LUTs | `UNORM` (linear) | data, not colour |
| HDR environment maps | float (EXR, RGBE, KTX2 float) | already linear |
| HDR render targets | RGBA16F, or R11G11B10F for opaque lighting | section 7 |
| SDR swapchain | `*_SRGB` view with linear shader output, or `UNORM` plus one manual encode | exactly one encode |
| HDR swapchain | RGB10A2 with PQ (HDR10) or RGBA16F scRGB | section 6 |

## 2. Spaces and matrices

| Space | R xy | G xy | B xy | White | Transfer |
|---|---|---|---|---|---|
| sRGB / Rec.709 | 0.64, 0.33 | 0.30, 0.60 | 0.15, 0.06 | D65 (0.3127, 0.3290) | sRGB piecewise; BT.1886 for video |
| Display P3 | 0.680, 0.320 | 0.265, 0.690 | 0.150, 0.060 | D65 | sRGB curve |
| Rec.2020 / BT.2100 | 0.708, 0.292 | 0.170, 0.797 | 0.131, 0.046 | D65 | PQ or HLG |
| ACEScg (AP1) | 0.713, 0.293 | 0.165, 0.830 | 0.128, 0.044 | ACES (0.32168, 0.33767) | linear |
| ACES2065-1 (AP0) | 0.7347, 0.2653 | 0.0, 1.0 | 0.0001, −0.0770 | ACES | linear |

```text
linear sRGB → XYZ (D65)          [0.4124 0.3576 0.1805; 0.2126 0.7152 0.0722; 0.0193 0.1192 0.9505]
XYZ → linear sRGB (IEC 61966-2-1) [3.2406 −1.5372 −0.4986; −0.9689 1.8758 0.0415; 0.0557 −0.2040 1.0570]
Rec.709 → Rec.2020 (BT.2087)     [0.6274 0.3293 0.0433; 0.0691 0.9195 0.0114; 0.0164 0.0880 0.8956]
linear sRGB → ACEScg (Bradford)  [0.6131 0.3395 0.0474; 0.0702 0.9164 0.0135; 0.0206 0.1096 0.8698]
Bradford M                       [0.8951 0.2664 −0.1614; −0.7502 1.7135 0.0367; 0.0389 −0.0685 1.0296]
CAT(src → dst) = M⁻¹ diag(M w_dst / M w_src) M     (w: white point XYZ)
luminance (linear Rec.709)       Y = 0.2126 R + 0.7152 G + 0.0722 B
```

The forward matrices were re-derived from the primaries above in the reference script. Derive others
the same way or take them from a library rather than typing them:

```python
import colour   # colour-science
M = colour.matrix_RGB_to_RGB(colour.RGB_COLOURSPACES["sRGB"], colour.RGB_COLOURSPACES["ACEScg"],
                             chromatic_adaptation_transform="Bradford")
```

OpenColorIO: use a studio config rather than hand-built ACES maths. OCIO 2.4.0 shipped the ACES 2.0
output transforms as a preview, 2.4.2 made them production-ready alongside downloadable ACES 2.0
configs, and OCIO 2.5 adds built-in ACES 2.0 configs; Blender's config carries AgX. Convert with
`ocioconvert in.exr <input space> out.exr <output space>` (or `ocioconvert --view in.exr <input space>
out.tif <display> <view>`), or in Python with
`config.getProcessor(src, display, view, OCIO.TRANSFORM_DIR_FORWARD).getDefaultCPUProcessor()`. Display
and view names are config-specific; list them with `getDisplays()` and `getViews(display)`.

## 3. Transfer functions

```glsl
vec3 srgbDecode(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }
vec3 srgbEncode(vec3 x) { return mix(12.92 * x, 1.055 * pow(x, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, x)); }
// PQ (SMPTE ST 2084), absolute nits: m1 = 2610/16384, m2 = 2523/4096*128, c1 = 3424/4096, c2 = 2413/4096*32, c3 = 2392/4096*32
const float m1 = 0.1593017578125, m2 = 78.84375, c1 = 0.8359375, c2 = 18.8515625, c3 = 18.6875;
vec3 pqEncode(vec3 nits) { vec3 y = pow(clamp(nits / 10000.0, 0.0, 1.0), vec3(m1)); return pow((c1 + c2 * y) / (1.0 + c3 * y), vec3(m2)); }
vec3 pqDecode(vec3 e) { vec3 p = pow(clamp(e, 0.0, 1.0), vec3(1.0 / m2)); return 10000.0 * pow(max(p - c1, 0.0) / (c2 - c3 * p), vec3(1.0 / m1)); }
```

- PQ codes: 100 nits → 0.5081, 203 nits → 0.5807, 1000 nits → 0.7518, 10,000 nits → 1.0; the round trip
  is exact to 1e-12.
- HLG (BT.2100) OETF: E' = sqrt(3E) for E ≤ 1/12, else a ln(12E − b) + c with a = 0.17883277,
  b = 1 − 4a = 0.28466892, c = 0.5 − a ln(4a) = 0.55991073; scene-relative, system gamma 1.2 at 1000 nits.
- BT.1886: L = a max(V + b, 0)^2.4 with a = (L_W^(1/2.4) − L_B^(1/2.4))^2.4 and
  b = L_B^(1/2.4)/(L_W^(1/2.4) − L_B^(1/2.4)), a pure 2.4 power for a zero black level. Rec.709 video
  is graded for it, not for the sRGB curve.
- `_SRGB` formats decode on sample (before filtering) and encode on write, so blending happens in linear.

## 4. Exposure

```text
camera:  EV100 = log2(N²/t) − log2(S/100)            N f-number, t seconds, S ISO
scene:   EV100 = log2(L_avg S / K), S = 100, K = 12.5
L_max = (78/(q S)) 2^EV100 with q = 0.65, i.e. 1.2 · 2^EV100;   exposure = 1/L_max
```

Check: sunny 16 (f/16, 1/100 s, ISO 100) gives EV100 = 14.64 and L_max = 30,720 cd/m². A white diffuse
(ρ = 0.9) under 1e5 lux has L = ρE/π = 2.9e4 cd/m² and exposes to 0.933; an 18% card exposes to 0.187.

```python
def auto_ev100(lum, prev_ev, dt, bins=128, lo=-8.0, hi=16.0, p_lo=0.5, p_hi=0.95, up=3.0, down=1.0):
    l = np.log2(np.maximum(lum[lum > 0], 1e-8))      # GPU: compute-shader histogram with 64-256 bins
    h, edges = np.histogram(np.clip(l, lo, hi), bins=bins, range=(lo, hi))
    c = np.cumsum(h) / h.sum()
    mid = 0.5 * (edges[:-1] + edges[1:])
    sel = (c >= p_lo) & (c <= p_hi)                  # 50th-95th percentile: ignore sky and highlights
    avg = np.average(mid[sel], weights=h[sel]) if sel.any() else mid[np.searchsorted(c, 0.5)]
    target = avg + math.log2(100.0 / 12.5)           # EV100 = log2(L_avg S / K)
    speed = up if target > prev_ev else down         # adapt to brighter scenes faster than to darker
    return prev_ev + (target - prev_ev) * (1.0 - math.exp(-dt * speed))
```

Keep EV in a 1 × 1 GPU buffer read next frame (no CPU readback) and apply exposure compensation in EV.

## 5. Display transforms

```glsl
vec3 reinhard(vec3 x) { return x / (1.0 + x); }      // per channel: debugging only
float reinhardExtended(float L, float Lw) { return L * (1.0 + L / (Lw * Lw)) / (1.0 + L); }  // Lw maps to 1; scale RGB by Lout/L
vec3 acesNarkowicz(vec3 x) { return clamp(x * (2.51 * x + 0.03) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0); }  // a fit, not ACES
vec3 pbrNeutral(vec3 c) {                            // Khronos PBR Neutral, linear Rec.709 after exposure
    const float startCompression = 0.8 - 0.04, desaturation = 0.15;
    float x = min(c.r, min(c.g, c.b));
    float offset = x < 0.08 ? x - 6.25 * x * x : 0.04;
    c -= offset;
    float peak = max(c.r, max(c.g, c.b));
    if (peak < startCompression) return c;
    const float d = 1.0 - startCompression;
    float newPeak = 1.0 - d * d / (peak + d - startCompression);
    c *= newPeak / peak;
    float g = 1.0 - 1.0 / (desaturation * (peak - newPeak) + 1.0);
    return mix(c, vec3(newPeak), g);
}
```

| Transform | Character | Use |
|---|---|---|
| Reinhard per channel | flat, desaturated | debugging |
| Narkowicz ACES fit | contrasty, hue skews in bright saturated colours | matching a legacy look |
| ACES 2.0 output transforms (OCIO) | standard film pipeline with built-in gamut compression | ACES productions |
| AgX (Blender 4.x default, three.js `AgXToneMapping`) | graceful path to white | general default for path tracers |
| Khronos PBR Neutral (2024) | reproduces base colours under unit lighting | product shots, material preview, glTF viewers |

- AgX: inset matrix toward the achromatic axis → log2 encoding over a fixed EV range → sigmoid contrast
  curve → outset matrix → display encoding. Copy the constants from the Blender config or the three.js
  and Filament ports instead of re-deriving them.
- Per-channel curves push bright saturated colours toward the primaries and secondaries (the "notorious
  six": orange fire turns yellow, blue lights turn cyan or purple). Luminance-based or path-to-white
  operators (AgX, ACES 2.0, PBR Neutral) avoid it.
- Fidelity under a uniform white environment of radiance 1 (24-patch chart, glTF dielectric; reference
  script): mean ΔE2000 1.14 for PBR Neutral, 7.16 for per-channel Reinhard, 9.35 for the Narkowicz fit.

## 6. HDR output

- Paper white: 203 nits (BT.2408 reference white) with a user slider; scRGB 1.0 is 80 nits, so 203 nits
  is 2.54.
- Query the display: DXGI `IDXGIOutput6::GetDesc1` (`MaxLuminance`, `MinLuminance`,
  `MaxFullFrameLuminance`, colour space), then `IDXGISwapChain3::SetColorSpace1` with
  `DXGI_COLOR_SPACE_RGB_FULL_G2084_NONE_P2020` (HDR10) or `DXGI_COLOR_SPACE_RGB_FULL_G10_NONE_P709`
  (scRGB). Apple EDR: `CAMetalLayer.wantsExtendedDynamicRangeContent`, RGBA16F with an extended linear
  Display P3 colour space, headroom from `maximumExtendedDynamicRangeColorComponentValue` (re-query it;
  it changes with screen brightness). WebGPU: configure the canvas with `format: "rgba16float"` and
  `toneMapping: {mode: "extended"}` where supported.
- Tonemap to the display peak and paper white, not to 1.0. HDR10 is PQ-encoded Rec.2020 nits in RGB10A2;
  scRGB is linear Rec.709 FP16 with values above 1 and below 0.
- Render UI in its own pass at paper white and composite it after the scene transform; never tonemap UI.

## 7. Quantization and banding

- RGBA16F: 10-bit mantissa, sign and alpha; safe for HDR lighting, scRGB and alpha.
- R11G11B10F: 6/6/5-bit mantissas, no sign, no alpha, half the bandwidth; fine for opaque lighting and
  bloom, visible hue shifts in dark saturated gradients (blue keeps 5 bits).
- Dither before quantising to 8 or 10 bits with triangular-pdf noise of ±1 LSB in the encoded domain:

```glsl
vec3 quantize8(vec3 encoded, vec2 r) { return floor(encoded * 255.0 + (r.x - r.y) + 0.5) / 255.0; }  // r: blue noise in [0,1)^2
```

- Never store colour as 8-bit linear: shadows get a handful of codes and band.

## 8. Alpha and blending

- Premultiplied alpha end to end: store (rgb · a, a), composite src + dst (1 − src.a), and filter and mip
  premultiplied data. Straight alpha through bilinear filtering is the classic source of dark fringes;
  also dilate colour into fully transparent texels.
- Blend in linear: `_SRGB` and float targets blend linear values; a UNORM target holding encoded values
  blends in gamma space and darkens mid-tones.
- sRGB mips: decode, filter in linear (premultiplied), encode.

## 9. Gamut mapping

Wide-gamut content converted to Rec.709 produces negative components, and per-channel clipping shifts
hue: Rec.2020 green is (−0.5876, 1.1329, −0.1006) in linear Rec.709, and clipping it to (0, 1, 0) moves
its OKLCh hue by −10.1°. Reduce chroma at constant OKLCh lightness and hue instead (result
(0, 0.849, 0.210): hue shift 0.00°, L 0.8298 kept), or use the ACES 2.0 / OCIO gamut compression. Apply it
after tonemapping, on display-referred values.

```python
M_LMS = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                  [0.0883024619, 0.2817188376, 0.6299787005]])   # Ottosson 2020, from linear sRGB
M_LAB = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                  [0.0259040371, 0.7827717662, -0.8086757660]])
oklab = lambda rgb: M_LAB @ np.cbrt(M_LMS @ np.asarray(rgb, float))
oklab_inv = lambda lab: np.linalg.solve(M_LMS, np.linalg.solve(M_LAB, np.asarray(lab, float)) ** 3)

def gamut_map_oklch(rgb, iters=16):          # bisection on chroma; L clamped to [0, 1]
    rgb = np.asarray(rgb, float)
    if (rgb >= 0).all() and (rgb <= 1).all():
        return rgb
    L, a, b = oklab(rgb)
    L = min(max(L, 0.0), 1.0)
    C, h = math.hypot(a, b), math.atan2(b, a)
    lo, hi = 0.0, C
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        c = oklab_inv([L, mid * math.cos(h), mid * math.sin(h)])
        lo, hi = (mid, hi) if (c >= -1e-6).all() and (c <= 1 + 1e-6).all() else (lo, mid)
    return np.clip(oklab_inv([L, lo * math.cos(h), lo * math.sin(h)]), 0.0, 1.0)
```

The numeric inverses of these matrices match Ottosson's published inverse matrices to 1e-8. For
palettes and UI ramps see `oklch-palette-ramps`.

## 10. Checks

- Middle grey: 0.18 linear encodes to 0.4614, code 117.6 of 255, with an identity transform at exposure 1.
- Push a −10 to +10 EV grey ramp and a ColorChecker through the pipeline: monotonic, no clipping before
  the display transform, values matching `ocioconvert` or a known-good engine within about 1-2 ΔE2000.
- With an identity tonemap the pre-tonemap buffer holds plausible absolute values: sunlit white diffuse
  is about 2.9e4 cd/m² (or document the engine's scale factor).
- Validate ΔE code on Sharma's CIEDE2000 test data (pair 1 gives 2.0425).

## 11. Pitfalls

- Double decode (an sRGB texture view plus a shader pow) or double encode (an sRGB swapchain plus a
  manual encode).
- Albedo loaded as linear (washed out); normal or roughness maps loaded as sRGB (roughness 0.5 reads as
  0.214, α 0.046 instead of 0.25; normals bend).
- Tonemapping applied twice (post chain plus UI pass), or UI tonemapped at all.
- 8-bit targets for HDR passes; blending in gamma space; straight alpha through filtering.
- Exposure applied after tonemapping, or auto-exposure metering the UI.

## 12. Worked example: a glTF viewer renders too dark and oversaturated

1. Measure: an 18% grey card under a uniform white environment shows code 53 instead of about 118,
   saturated patches look deeper, and surfaces look glossier than in the Khronos glTF Sample Viewer.
2. Cause one: the loader marks every map sRGB. Per the glTF specification `baseColorTexture`,
   `emissiveTexture` and the KHR colour textures (`specularColorTexture`, `sheenColorTexture`) are sRGB;
   metallic-roughness, normal, occlusion and the remaining KHR textures are linear. Roughness 0.5
   decoded as sRGB became 0.214 (α 0.046 instead of 0.25).
3. Cause two: the swapchain is UNORM and no pass encodes, so linear values are displayed as if encoded;
   the grey card's 0.2095 becomes code 53.4.
4. Fix: per-texture colour spaces, an `_SRGB` swapchain view (or one manual encode in the last pass),
   exposure, and PBR Neutral as the display transform.
5. Verify (reference script; unit white environment, F0 0.04, roughness 0.5): grey card 53.4 → 114.4
   (ideal 117.6); ColorChecker mean ΔE2000 18.50 → 1.14 and max 24.70 → 1.72. Then compare the real
   render with the Sample Viewer under the same environment and exposure, patch by patch.

Related: `pbr-microfacet-brdf`, `denoising-taa-upscaling`, `raster-pipeline-architecture`, `path-tracer-implementation`, `realtime-global-illumination`, `oklch-palette-ramps`, hub `computer-graphics`
