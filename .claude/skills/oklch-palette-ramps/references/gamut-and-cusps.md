# Gamut mapping and cusp tables

All numbers computed with `scripts/oklch.py` (OKLab matrices from CSS Color 4; sRGB and Display P3
matrices derived from their primaries and the D65 white x 0.3127, y 0.3290).

## 1. Maximum in-gamut chroma per hue

The cusp is the lightness at which a hue reaches its maximum chroma. Put the ramp's chroma peak
near the cusp; steps far from it cannot hold much chroma in sRGB.

| OKLCH h | Hue family | Cusp L (sRGB) | Max C sRGB | Max C P3 (at L) |
|---|---|---|---|---|
| 25 | red | 0.630 | 0.255 | 0.297 (0.65) |
| 50 | orange | 0.720 | 0.190 | 0.221 (0.73) |
| 75 | amber | 0.805 | 0.170 | 0.198 (0.82) |
| 105 | yellow | 0.935 | 0.198 | 0.230 (0.94) |
| 145 | green | 0.865 | 0.272 | 0.363 (0.85) |
| 165 | teal-green | 0.885 | 0.186 | 0.249 (0.86) |
| 200 | cyan | 0.880 | 0.150 | 0.195 (0.85) |
| 250 | azure | 0.660 | 0.187 | 0.227 (0.62) |
| 265 | blue | 0.455 | 0.311 | 0.320 (0.47) |
| 300 | violet | 0.550 | 0.294 | 0.311 (0.56) |
| 345 | pink-magenta | 0.665 | 0.283 | 0.327 (0.69) |

Maximum sRGB chroma at fixed L (what a ramp step can hold before gamut mapping cuts it):

| h | L 0.97 | 0.90 | 0.80 | 0.70 | 0.60 | 0.50 | 0.40 | 0.30 | 0.25 |
|---|---|---|---|---|---|---|---|---|---|
| 25 | 0.015 | 0.052 | 0.114 | 0.191 | 0.243 | 0.203 | 0.162 | 0.122 | 0.101 |
| 50 | 0.017 | 0.058 | 0.127 | 0.185 | 0.159 | 0.132 | 0.106 | 0.079 | 0.066 |
| 75 | 0.024 | 0.083 | 0.169 | 0.148 | 0.127 | 0.105 | 0.084 | 0.063 | 0.053 |
| 105 | 0.102 | 0.191 | 0.170 | 0.149 | 0.127 | 0.106 | 0.085 | 0.064 | 0.053 |
| 145 | 0.051 | 0.195 | 0.252 | 0.220 | 0.189 | 0.157 | 0.126 | 0.094 | 0.079 |
| 165 | 0.043 | 0.160 | 0.168 | 0.147 | 0.126 | 0.105 | 0.084 | 0.063 | 0.053 |
| 200 | 0.037 | 0.127 | 0.136 | 0.119 | 0.102 | 0.085 | 0.068 | 0.051 | 0.043 |
| 250 | 0.015 | 0.050 | 0.105 | 0.163 | 0.170 | 0.142 | 0.113 | 0.085 | 0.071 |
| 265 | 0.014 | 0.048 | 0.100 | 0.156 | 0.217 | 0.281 | 0.275 | 0.206 | 0.172 |
| 300 | 0.017 | 0.057 | 0.119 | 0.186 | 0.258 | 0.267 | 0.214 | 0.160 | 0.133 |
| 345 | 0.018 | 0.065 | 0.145 | 0.245 | 0.255 | 0.213 | 0.170 | 0.128 | 0.106 |

Reading it: an amber ramp (h 75) cannot exceed C 0.105 at L 0.50, which is why dark ambers look
brown; a yellow with chroma at L 0.97 (0.102) gives a visible cream 50-step while reds and blues
are almost grey there; blue holds chroma deep into the shades.

Recompute for any hue:

```python
import importlib.util
spec = importlib.util.spec_from_file_location("ok", "scripts/oklch.py")
ok = importlib.util.module_from_spec(spec); spec.loader.exec_module(ok)

def max_c(L, h, space="srgb"):
    lo, hi = 0.0, 0.5
    for _ in range(40):                         # bisection on chroma
        c = (lo + hi) / 2
        v = ok.to_space(ok.oklch_to_oklab(L, c, h), space)
        lo, hi = (c, hi) if all(-1e-9 <= x <= 1 + 1e-9 for x in v) else (lo, c)
    return lo
```

## 2. CSS Color 4 gamut mapping (binary search with local MINDE)

```text
input: origin in OKLCH (L, C, h), destination RGB space
if L >= 1: return white;  if L <= 0: return black
if inGamut(origin): return origin converted
JND = 0.02; epsilon = 0.0001
clipped = clip(origin); if deltaE_OK(clipped, origin) < JND: return clipped
min = 0; max = C; min_inGamut = true
while max - min > epsilon:
    chroma = (min + max) / 2; current = (L, chroma, h)
    if min_inGamut and inGamut(current): min = chroma; continue
    clipped = clip(current); E = deltaE_OK(clipped, current)
    if E < JND:
        if JND - E < epsilon: return clipped
        min_inGamut = false; min = chroma
    else: max = chroma
return clipped
```

Properties: lightness and hue are held (up to one JND absorbed by the final clip, so a mapped
colour can move a little in L and h: `map 0.70 0.30 145` gives #00C300 = oklch(0.709 0.241
142.5)); only chroma is sacrificed. The specification also allows EdgeSeeker and ray-trace
mappers with comparable results; implementations choose.

| ColorAide `fit(method=...)` | What it is |
|---|---|
| `raytrace` | ColorAide's default (`fit()` with no method) |
| `oklch-chroma` | CSS Color 4 MINDE chroma reduction in OKLCh, JND 0.02 |
| `lch-chroma` | the same idea in CIELCh (JND 2) |
| `minde-chroma` | configurable MINDE (`pspace`, `jnd`, `de_options`) |
| `clip`, `scale` | channel clipping / scaling: keep only for checks, they shift hue |

`Color(...).in_gamut('srgb')` uses a small default tolerance; `to_string()` fits by default,
`fit=False` disables it.

## 3. Display P3 tier

- P3 primaries: R (0.680, 0.320), G (0.265, 0.690), B (0.150, 0.060), white D65; it extends sRGB
  most in greens, oranges and reds (compare the two max-C columns above).
- Ship sRGB values unconditionally and override inside `@media (color-gamut: p3)`; write P3
  colours as `oklch()` (or `color(display-p3 r g b)` from `map ... --gamut p3`).
- Contrast is measured on the sRGB tier (WCAG 2.x is defined on sRGB); keep the P3 tier at the
  same L so ratios barely move, and spot-check with the P3 values converted back.
- Screenshots and PNG exports in sRGB lose the P3 tier: brand files for print or social use the
  sRGB hex.
