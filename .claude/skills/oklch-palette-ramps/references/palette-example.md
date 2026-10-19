# Complete example palette (brand pink #E94560, navy page #1A1A2E)

Generated with `scripts/oklch.py`; every ratio measured on the rounded hex.

## 1. Brand ramp (`ramp '#E94560' --name pink --surfaces '#1A1A2E,#121212' --p3-peak-c 0.23`)

| Step | Hex (sRGB tier) | oklch() | White | Black | #1A1A2E | #121212 | P3 tier |
|---|---|---|---|---|---|---|---|
| 50 | #FFF0F1 | 0.967 0.016 15.2 | 1.11 | 18.99 | 15.42 | 16.94 | oklch(0.968 0.020 15.6) |
| 100 | #FFDDDE | 0.925 0.038 15.3 | 1.26 | 16.62 | 13.50 | 14.83 | oklch(0.928 0.048 15.6) |
| 200 | #FFBEC2 | 0.862 0.075 15.1 | 1.57 | 13.42 | 10.90 | 11.97 | oklch(0.867 0.093 15.6) |
| 300 | #FF969E | 0.785 0.126 15.4 | 2.08 | 10.10 | 8.20 | 9.01 | oklch(0.790 0.152 15.7) |
| 400 | #FB6B7C | 0.710 0.176 15.7 | 2.79 | 7.52 | 6.11 | 6.71 | oklch(0.710 0.202 15.7) |
| 500 (brand) | #E94560 | 0.633 0.199 15.7 | 3.83 | 5.48 | 4.46 | 4.89 | oklch(0.633 0.230 15.7) |
| 600 | #CB2449 | 0.550 0.199 15.7 | 5.40 | 3.89 | 3.16 | 3.47 | oklch(0.550 0.230 15.7) |
| 700 | #A90936 | 0.470 0.184 15.7 | 7.55 | 2.78 | 2.26 | 2.48 | oklch(0.470 0.212 15.7) |
| 800 | #850026 | 0.392 0.157 16.3 | 10.33 | 2.03 | 1.65 | 1.81 | oklch(0.394 0.178 16.9) |
| 900 | #620018 | 0.315 0.126 17.3 | 13.69 | 1.53 | 1.25 | 1.37 | oklch(0.317 0.143 17.9) |
| 950 | #470010 | 0.252 0.101 16.7 | 16.47 | 1.27 | 1.04 | 1.14 | oklch(0.254 0.115 17.3) |

Allowed roles: 50-200 tints and selected-row backgrounds; 400 text and icons on navy or #121212;
500 brand decoration, large bold text on navy only (4.46); 600-700 fills under white text and
text on white; 800-950 text on tints.

## 2. Tinted neutrals (`ramp '#E94560' --name neutral --neutral 0.012 --surfaces '#121212'`)

| Step | Hex | oklch() | White | Black | #121212 | Role |
|---|---|---|---|---|---|---|
| 50 | #FDF2F2 | 0.970 0.012 15.7 | 1.10 | 19.17 | 17.10 | page tint |
| 100 | #F0E5E5 | 0.930 0.012 15.7 | 1.23 | 17.01 | 15.18 | surface-raised |
| 200 | #DCD1D1 | 0.870 0.012 15.7 | 1.49 | 14.11 | 12.58 | dividers (decorative) |
| 300 | #C2B8B8 | 0.790 0.012 15.7 | 1.94 | 10.81 | 9.64 | disabled fills |
| 400 | #A99F9F | 0.710 0.012 15.7 | 2.59 | 8.12 | 7.24 | dark-mode secondary text |
| 500 | #908687 | 0.630 0.012 15.7 | 3.52 | 5.97 | 5.32 | input borders on white (>= 3:1) |
| 600 | #786F6F | 0.550 0.012 15.7 | 4.88 | 4.30 | 3.84 | secondary text on white |
| 700 | #615858 | 0.470 0.012 15.7 | 6.87 | 3.06 | 2.73 | body text alternative |
| 800 | #4B4343 | 0.390 0.012 15.7 | 9.66 | 2.17 | 1.94 | headings |
| 900 | #362E2E | 0.310 0.012 15.7 | 13.23 | 1.59 | 1.42 | body text |
| 950 | #271F20 | 0.250 0.012 15.7 | 16.07 | 1.31 | 1.17 | text on amber |

## 3. Semantic and theme tokens

| Token | Light | Dark | Pair checked (light / dark) |
|---|---|---|---|
| `color.bg.page` | #FFFFFF | #151010 | |
| `color.bg.raised` | neutral-100 | #1D1818 | |
| `color.text.body` | neutral-900 #362E2E | #E6E6E6 | 13.23 on white / 15.09 on #151010 |
| `color.text.muted` | neutral-600 #786F6F | neutral-400 #A99F9F | 4.88 / 7.24 on #121212 |
| `color.accent.on-dark` | #EC4862 (on navy hero) | #F16F7D | 4.61 on #1A1A2E / 6.51 on #121212 |
| `color.accent.fill` | #D63151 | #D63151 | white label 4.75 |
| `color.success` | #1B7E2A | #86D489 | 5.17 white / 10.50 on #121212 |
| `color.warning.fill` | #F9AD26 + text #271F20 | same | 8.43 |
| `color.warning.text` | #935B00 | #EEB154 | 5.61 on white / 9.86 |
| `color.danger` | #AF3C3A | #FF9B93 | 5.95 white / 9.25 |
| `color.info` | #006BBB | #7BC3FF | 5.51 white / 9.92 |
| `color.focus` | #006BBB 2 px ring | #7BC3FF | >= 3:1 against both adjacent colours |

## 4. CSS

```css
:root {
  --pink-400: #FB6B7C; --pink-500: #E94560; --pink-600: #CB2449;
  --neutral-100: #F0E5E5; --neutral-600: #786F6F; --neutral-900: #362E2E;
  --color-bg-page: #FFFFFF;
  --color-text-body: var(--neutral-900);
  --color-accent-on-dark: #EC4862;
  --color-accent-fill: #D63151;
}
@media (color-gamut: p3) {
  :root { --pink-500: oklch(0.633 0.230 15.7); --pink-600: oklch(0.550 0.230 15.7); }
}
[data-theme="dark"] {
  --color-bg-page: #151010;
  --color-text-body: #E6E6E6;
  --color-accent-on-dark: #F16F7D;
}
```

## 5. DTCG 2025.10 excerpt

```json
{
  "color": {
    "$type": "color",
    "pink": {
      "500": { "$value": { "colorSpace": "oklch", "components": [0.633, 0.199, 15.7], "hex": "#e94560" } },
      "600": { "$value": { "colorSpace": "oklch", "components": [0.55, 0.199, 15.7], "hex": "#cb2449" } }
    },
    "accent": {
      "on-dark": { "$value": { "colorSpace": "oklch", "components": [0.641, 0.199, 15.9], "hex": "#ec4862" },
                   "$description": "Accent text and icons on navy #1A1A2E: 4.61:1" },
      "fill": { "$value": { "colorSpace": "oklch", "components": [0.58, 0.199, 15.7], "hex": "#d63151" },
                "$description": "Button fill under white labels: 4.75:1" }
    },
    "text": { "link-on-light": { "$value": "{color.pink.600}" } }
  }
}
```

`ramp --format dtcg` emits the primitive groups; semantic groups and aliases (`{color.pink.600}`)
are written by hand and validated with the tooling in `design-tokens-dtcg`.
