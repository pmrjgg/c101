---
name: design-tokens-dtcg
description: "Design tokens in the W3C DTCG 2025.10 format: primitive/semantic/component tiers, aliases, types, modes and themes (resolver files), naming grammar, validation with contrast checks, and builds to CSS variables, Tailwind v4 @theme and Swift/Compose with Style Dictionary 5 or Terrazzo 2. Load when creating, migrating, validating or releasing a token set."
when_to_use: "Files named *.tokens.json, *.tokens, *.resolver.json, sd.config.*, build-tokens.mjs, terrazzo.config.ts, tailwind.config.js or a CSS @theme block; adding a dark, high-contrast or compact mode; renaming or deprecating tokens; migrating SCSS/LESS variables, Tailwind v3 themes or Figma Variables; errors such as unresolved alias, circular reference, colour given as a hex string, dimension without unit, or px sizes turning into 256.00.dp on Android."
---

# Design tokens (DTCG 2025.10)

Baseline (October 2026): Design Tokens Format Module, Color Module and Resolver Module **2025.10**
(Final Community Group Reports of the W3C Design Tokens Community Group, 28 Oct 2025; stable, not a
W3C Recommendation). Tools: style-dictionary 5.7, @terrazzo/cli 2.9, tailwindcss 4.3. Check
designtokens.org before using anything newer than this page; never invent `$` keys.

Deep material: [validator source](references/validator.md) |
[build pipelines](references/build-pipelines.md) |
[migrations and releases](references/migrations-release.md)

## 1. Three tiers and the naming grammar

| Tier | Example name | Holds | May alias | Consumed by |
|---|---|---|---|---|
| primitive | `color.pink.600`, `space.4` | literal values (a palette, a scale) | nothing (or other primitives) | semantic tokens only |
| semantic | `color.action.primary.bg`, `color.text.default` | role, swapped per mode | primitives, other semantics | components and app code |
| component | `button.primary.bg` | one component's decision | semantics only, **never primitives** | that component |

Grammar: `{category}.{property}.{variant}.{state}`, lowercase, kebab-case inside a segment.
`color.action.primary.bg` -> `color.action.primary.bg-hover` is a flat sibling; when a token needs
states, make it a group with a `$root` default: `bg: { "$root": {...}, "hover": {...} }`, aliased as
`{color.action.primary.bg.$root}` (Style Dictionary >= 5.7 names it `--color-action-primary-bg`).

Categories in use: `color`, `space`, `size`, `radius`, `border`, `font`, `typography`, `shadow`,
`motion` (duration, easing), `opacity`, `z`. A new category needs a reason in the changelog.

## 2. DTCG 2025.10 essentials

| Key | Where | Rule |
|---|---|---|
| `$value` | token | required; its presence is what makes an object a token |
| `$type` | token or group | groups pass it down to tokens without one; an alias takes its target's type; tools must not infer type from the value |
| `$description` | token or group | plain string |
| `$deprecated` | token or group | `true`, `false` or a string naming the replacement |
| `$extensions` | token or group | tool data under reverse-domain keys (`org.example.figma`) |
| `$root` | inside a group | reserved token name for the group's base value; part of the alias path |
| `$extends` | group | inherits another group's tokens; local tokens override; circular chains are errors |
| `$ref` | value position | JSON Pointer, e.g. `{"$ref": "#/color/blue/$value/components/0"}`; can target parts of a value |

Names must not start with `$` and must not contain `{`, `}` or `.`; they are case-sensitive.
Files: `.tokens` or `.tokens.json`, media type `application/design-tokens+json`. Curly aliases
`"{color.pink.600}"` resolve to the target's whole `$value` and must point at a token, not a group.
Circular references are errors for every token in the chain.

| `$type` | `$value` shape | Example |
|---|---|---|
| `color` | `{colorSpace, components[3], alpha?, hex?}` | `{"colorSpace":"oklch","components":[0.58,0.199,15.7],"hex":"#d63151"}` |
| `dimension` | `{value, unit}`, unit `px` or `rem` only, required even for 0 | `{"value":16,"unit":"px"}` |
| `duration` | `{value, unit}`, unit `ms` or `s` | `{"value":120,"unit":"ms"}` |
| `cubicBezier` | `[x1, y1, x2, y2]`, x in [0, 1], y any number | `[0.2, 0, 0, 1]` |
| `fontFamily` | string or array of names | `["Inter","system-ui","sans-serif"]` |
| `fontWeight` | 1-1000 or a case-sensitive alias | `600`, `"semi-bold"` |
| `number` | JSON number | `1.5` |
| `strokeStyle` | keyword (`solid` `dashed` `dotted` `double` `groove` `ridge` `outset` `inset`) or `{dashArray, lineCap}` | `"dashed"` |
| `border` | `{color, width, style}` | sub-values may be aliases |
| `transition` | `{duration, delay, timingFunction}` | |
| `shadow` | `{color, offsetX, offsetY, blur, spread, inset?}` or an array of them | layered shadows |
| `gradient` | array of `{color, position}`, position clamped to [0, 1] | |
| `typography` | `{fontFamily, fontSize, fontWeight, letterSpacing, lineHeight}` | lineHeight is a number (multiplier) |

fontWeight aliases: thin/hairline 100, extra-light/ultra-light 200, light 300,
normal/regular/book 400, medium 500, semi-bold/demi-bold 600, bold 700, extra-bold/ultra-bold 800,
black/heavy 900, extra-black/ultra-black 950.

Colour spaces: `srgb`, `srgb-linear`, `hsl`, `hwb`, `lab`, `lch`, `oklab`, `oklch`, `display-p3`,
`a98-rgb`, `prophoto-rgb`, `rec2020`, `xyz-d65`, `xyz-d50`. `oklch` components are L 0-1 (not
0-100), C >= 0 (about 0.5 at most in practice), hue in degrees [0, 360). A component may be
`"none"`. `alpha` defaults to 1; `hex` is a 6-digit sRGB fallback for tools that cannot convert.

## 3. Annotated token file

```json
{
  "color": {
    "$type": "color",
    "pink": {
      "600": { "$value": { "colorSpace": "oklch", "components": [0.58, 0.199, 15.7], "hex": "#d63151" },
               "$description": "Accent fill; 4.75:1 under white text" }
    },
    "white": { "$value": { "colorSpace": "srgb", "components": [1, 1, 1], "hex": "#ffffff" } }
  },
  "space": { "$type": "dimension", "2": { "$value": { "value": 8, "unit": "px" } } },
  "font": {
    "family": { "sans": { "$type": "fontFamily", "$value": ["Inter", "system-ui", "sans-serif"] } },
    "weight": { "$type": "fontWeight", "regular": { "$value": 400 }, "semibold": { "$value": "semi-bold" } },
    "size": { "body": { "$type": "dimension", "$value": { "value": 1, "unit": "rem" } } }
  },
  "typography": {
    "body": { "$type": "typography",
              "$value": { "fontFamily": "{font.family.sans}", "fontSize": "{font.size.body}",
                          "fontWeight": "{font.weight.regular}", "letterSpacing": { "value": 0, "unit": "px" },
                          "lineHeight": 1.5 } }
  },
  "motion": {
    "duration": { "fast": { "$type": "duration", "$value": { "value": 120, "unit": "ms" } } },
    "easing": { "standard": { "$type": "cubicBezier", "$value": [0.2, 0, 0, 1] } }
  },
  "shadow": {
    "card": { "$type": "shadow",
              "$value": { "color": { "colorSpace": "srgb", "components": [0, 0, 0], "alpha": 0.2 },
                          "offsetX": { "value": 0, "unit": "px" }, "offsetY": { "value": 1, "unit": "px" },
                          "blur": { "value": 3, "unit": "px" }, "spread": { "value": 0, "unit": "px" } } },
    "raised": { "$type": "shadow", "$value": "{shadow.card}", "$deprecated": "Use shadow.card; removed in 3.0" }
  }
}
```

| Line | Why |
|---|---|
| `"$type": "color"` on the group | every token below inherits it; no per-token repetition |
| oklch `components` + `hex` | perceptual source of truth; the hex is the sRGB fallback, keep them in sync |
| `"unit": "px"` / `"rem"` | required; a bare `16` is not a dimension |
| `"semi-bold"` | valid alias for 600; `"Semi-Bold"` must be rejected (case-sensitive) |
| typography sub-values as aliases | the composite stays in sync with the scale; letterSpacing is a dimension |
| `$deprecated` string | names the replacement; the token stays until the next major release |

This file validates with 0 errors (section 6); as CSS it becomes, for example,
`--typography-body: var(--font-weight-regular) var(--font-size-body)/1.5 var(--font-family-sans)` and
`--shadow-card: 0px 1px 3px 0px color(srgb 0 0 0 / 0.2)` (both resolve in Chrome).

## 4. Modes and themes

- Swap **only the semantic tier**. Primitives are shared; components alias semantics, so they follow.
- One axis per concern: `theme` (light, dark), `contrast` (default, high), `density` (comfortable,
  compact), `motion` (default, reduced). Never multiply files per combination (`dark-hc-compact`).
- Layout A, one file per mode: `semantic.light.tokens.json`, `semantic.dark.tokens.json`. Every mode
  file defines the same token names (the validator fails a name missing from one mode).
- Layout B, a resolver document (2025.10 Resolver Module, `*.resolver.json`):

```json
{
  "version": "2025.10",
  "sets": { "base": { "sources": [ { "$ref": "primitive.tokens.json" }, { "$ref": "component.tokens.json" } ] } },
  "modifiers": {
    "theme": { "contexts": { "light": [ { "$ref": "semantic.light.tokens.json" } ],
                             "dark":  [ { "$ref": "semantic.dark.tokens.json" } ] },
               "default": "light" }
  },
  "resolutionOrder": [ { "$ref": "#/sets/base" }, { "$ref": "#/modifiers/theme" } ]
}
```

Later entries in `resolutionOrder` win; aliases resolve after merging, so components may point at
semantics loaded later. Inputs are `{ "theme": "dark" }`; a modifier without `default` must be given.

CSS emission (what any build must produce):

```css
:root { /* primitives */ }
:root, [data-theme] { /* base-mode semantics + component aliases, re-declared on every themed element */ }
@media (prefers-color-scheme: dark) { :root:not([data-theme]) { /* dark semantics */ } }
[data-theme="dark"] { /* dark semantics */ }
@media (prefers-contrast: more) { :root:not([data-contrast]) { /* high-contrast semantics */ } }
[data-density="compact"] { /* compact space/size semantics */ }
@media (prefers-reduced-motion: reduce) { :root { /* motion.duration.* = 0ms */ } }
```

Why re-declare aliases on `[data-theme]`: custom properties inherit **computed** values. If
`--button-primary-bg: var(--color-accent-fill)` is declared only on `:root`, a
`<div data-theme="dark">` subtree keeps the light colour (checked in Chrome: the alias declared only
on `:root` stayed red inside the dark subtree; re-declared on `[data-theme]` it turned blue).

## 5. Build pipelines

| Need | Style Dictionary 5.x | Terrazzo 2.x |
|---|---|---|
| install | `npm i -D style-dictionary` (Node >= 22) | `npm i -D @terrazzo/cli @terrazzo/plugin-css @terrazzo/plugin-tailwind` |
| DTCG 2025.10 values | colour objects from 5.3, dimension objects 5.4, duration objects and `$root` names 5.7 | supported; a resolver file must be the **only** `tokens` input |
| modes | one build per mode file, `options.selector` per file (string, or array for nesting) | `css({ permutations: [{ input, prepare }] })` |
| CSS | format `css/variables`, transform group `css` (swap `color/css` for `color/oklch` to keep `oklch()`) | `@terrazzo/plugin-css`, default `tokens.css` |
| Tailwind v4 | map the CSS variables with `@theme inline` (below) | `@terrazzo/plugin-tailwind` fills a template via `@tz (theme: "dark")` |
| Swift / Kotlin | groups `ios-swift` + format `ios-swift/class.swift`; `compose` + `compose/object` | `@terrazzo/plugin-swift` (0.3.x) |
| commands | `node build-tokens.mjs` or `npx style-dictionary build --config sd.config.mjs` | `npx tz build`, `npx tz check tokens.json`, `npx tz format`, `npx tz import <figma-url>` |

Full configs, the multi-mode build script and the Terrazzo resolver setup:
[build pipelines](references/build-pipelines.md). Two traps found in the 5.7 source: for
`dimension` tokens, `size/compose/remToDp` (group `compose`) and `size/swift/remToCGFloat` (group
`ios-swift`) multiply the number by `basePxFontSize` (default 16) whatever the unit, so `{16, px}`
becomes `256.00.dp`; author dimensions in rem for native targets or swap in a custom transform. And
`outputReferences: true` plus a filter warns about filtered references; that is expected when the
primitives live in the base file.

Tailwind v4 consumes the built variables; prefix token variables (`prefix: "ds"` gives `--ds-*`) so
no Tailwind theme variable ever reads `--color-x: var(--color-x)`, a self-reference CSS treats as
invalid:

```css
@import "tailwindcss";
@import "./dist/tokens.light.css";
@import "./dist/tokens.dark.css";
@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *));
@theme { --color-*: initial; }                   /* drop the default palette: tokens only */
@theme inline {
  --color-surface: var(--ds-color-bg-surface);
  --color-ink: var(--ds-color-text-default);
  --color-accent: var(--ds-color-accent-fg);
  --color-accent-fill: var(--ds-color-accent-fill);
  --color-on-accent: var(--ds-color-accent-on-fill);
}
```

`@theme inline` makes `bg-accent-fill` emit `var(--ds-color-accent-fill)` itself, so utilities follow
`[data-theme]` switches. `@theme` variables must be top level, never inside selectors or media queries.

## 6. Validator (stdlib Python)

Layout: one directory with `primitive*.tokens.json`, `semantic.<mode>.tokens.json`,
`component*.tokens.json` and `contrast-pairs.json`. Run
`python3 -I validate_tokens.py tokens/ [--emit-css dist/preview.css] [--prefix ds]`; exit 1 on errors.

| Check | Failure example |
|---|---|
| every alias resolves, including aliases inside composites | `color.text.gone: missing target {color.nope}` |
| no cycles | `cycle color.loopA -> color.loopB -> color.loopA` |
| `$type` known (own, group, or alias target) and consistent along the chain | `$type dimension but alias chain ends in color` |
| tier rules | `component skips the semantic tier`, `semantic aliases higher tier (component)` |
| 2025.10 value shapes | colour as `"#2563eb"`, dimension `"16px"` or `{value: 16}` without unit, cubicBezier x outside [0, 1] |
| no duplicate CSS names after kebab-casing | `color.action.primaryBg` and `color.action.primary-bg` |
| mode parity | `semantic color.accent.fg is defined in mode dark but missing here` |
| contrast pairs per mode (WCAG 2.x, same formula as `visual-accessibility-audit`) | `contrast color.accent.fg on color.bg.surface = 3.83 < 4.5` |
| warnings: literal values in semantic/component tiers, primitives nobody references, aliases to deprecated tokens | |

OKLCH values are converted to the 8-bit sRGB colour that is drawn before measuring, and out-of-gamut
values are flagged. Source and sample output: [validator](references/validator.md).

## 7. Naming rules

| Do | Do not |
|---|---|
| name by role: `color.text.danger`, `color.bg.surface-raised` | name by value: `color.blue-text`, `color.red`, `space.16px` |
| one semantic per decision that can change independently | one component token per CSS property of every component (token explosion) |
| component tokens only where a component deviates from semantics | `card.padding` = `{space.6}` repeated in 40 components |
| deprecate with `$deprecated: "Use x"` and keep one major | delete or rename in a minor release |
| a public set (`color.*`, `space.*`, `typography.*`) under semver, an internal set (`_internal.*`, excluded from builds) | consumers reaching into primitives |
| numeric scale steps that leave gaps (`space.1,2,3,4,6,8,12`) | `space.small/smaller/smallest` |

## 8. Migration recipes

- **Tailwind v3 to v4**: on a clean branch `npx @tailwindcss/upgrade` (Node >= 20); move
  `theme.extend` values into `@theme` or the token mapping above; keep a JS config temporarily with
  `@config "../../tailwind.config.js";` (no `corePlugins`, `safelist`, `separator`; safelist becomes
  `@source inline()`); replace `theme(colors.red.500)` with `var(--color-red-500)`; replace the
  `darkMode` setting with the `@custom-variant dark` line.
- **SCSS/LESS variables**: convert with the stdlib converter (hex to srgb objects, px/rem to
  dimensions, ms/s to durations, `$a: $b` to aliases, anything else reported), sort the result into
  tiers, then point the old variables at the CSS variables for one release (`$color-link:
  var(--ds-color-accent-fg);`) before deleting them.
- **Figma Variables**: collections become tiers, modes become semantic mode files, `VARIABLE_ALIAS`
  becomes `{alias}`, `COLOR` becomes `color`, `FLOAT` becomes `dimension` or `number` (decide per
  collection), `STRING` becomes `fontFamily` or stays out, `BOOLEAN` has no DTCG type. Routes:
  Figma's native DTCG export (announced late 2025, rolling out per account: check the Variables
  panel), the Tokens Studio plugin in DTCG mode, `npx tz import <figma-file-url> --o tokens.json`
  (reads `FIGMA_ACCESS_TOKEN` or `FIGMA_OAUTH_TOKEN` from the environment: ask the user to export
  it, never write it to a file), or REST `GET /v1/files/:file_key/variables/local` (Enterprise plan,
  full seat, scope `file_variables:read`).

Scripts and the mapping table: [migrations and releases](references/migrations-release.md).

## 9. Release discipline

| Change | Semver |
|---|---|
| public token removed, renamed or `$type` changed; meaning changed (`color.text.muted` now used for disabled) | major |
| token, mode or category added; token deprecated | minor |
| value tuned within the same intent (contrast fix, ramp step nudged) | patch, plus visual regression |

1. Package the built outputs (`dist/`) and the source tokens as one versioned npm or Swift package.
2. Changelog from a token diff: `python3 -I token_diff.py tokens@v1/ tokens/ --public-prefix color.`
   classifies removed/retyped (major), added/deprecated (minor), value changes (patch).
3. After any semantic change run screenshot diffs of key screens in every mode:
   `await expect(page).toHaveScreenshot('settings-dark.png', { maxDiffPixelRatio: 0.01, animations: 'disabled' })`;
   accept new baselines with `npx playwright test --update-snapshots` only after a human looked.

## 10. Worked example: brand pink split into two semantics

Input: brand pink `#E94560` (`oklch(0.633 0.199 15.7)`), light surface white, dark surface navy
`#1A1A2E`. Version 1 used the brand colour directly for accent text and button fills. Validator:

```
dark   color.accent.fg          on color.bg.surface         4.46:1  min 4.5  FAIL
dark   color.accent.on-fill     on color.accent.fill        3.83:1  min 4.5  FAIL
light  color.accent.fg          on color.bg.surface         3.83:1  min 4.5  FAIL
light  color.accent.on-fill     on color.accent.fill        3.83:1  min 4.5  FAIL
4 error(s), 1 warning(s)
```

Fix at the primitive tier by stepping OKLCH L at fixed hue (15.7): `pink.400` = L 0.70, C 0.17
(`#f56b7a`, chroma reduced to stay in gamut), `pink.600` = L 0.58, C 0.199 (`#d63151`). Then split
the semantic tier: `color.accent.fg` (accent text on the page) and `color.accent.fill` (button
backgrounds, with `color.accent.on-fill` = white):

| Semantic | light | dark |
|---|---|---|
| `color.accent.fg` | `{color.pink.600}` 4.75:1 on white | `{color.pink.400}` 5.90:1 on navy |
| `color.accent.fill` | `{color.pink.600}`, white label 4.75:1 | `{color.pink.600}`, white label 4.75:1 |

```
$ python3 -I validate_tokens.py tokens/ --emit-css dist/preview.css --prefix ds
dark   color.accent.fg          on color.bg.surface         5.90:1  min 4.5  pass
dark   color.accent.on-fill     on color.accent.fill        4.75:1  min 4.5  pass
light  color.accent.fg          on color.bg.surface         4.75:1  min 4.5  pass
light  color.accent.on-fill     on color.accent.fill        4.75:1  min 4.5  pass
WARN  [light] primitive color.pink.500 is not referenced by any semantic or component token
...   (pink.500 in dark, pink.400 and gray.100 in light: each is used by only one mode)
0 error(s), 4 warning(s)
```

The `pink.500` warning is deliberate: the brand primitive stays for marketing art, documented as
"never on text". Emitted CSS (excerpt), then the Tailwind mapping from section 5:

```css
:root, [data-theme] {
  --ds-color-accent-fg: var(--ds-color-pink-600);
  --ds-color-accent-fill: var(--ds-color-pink-600);
  --ds-button-primary-bg: var(--ds-color-accent-fill);
}
[data-theme="dark"] { --ds-color-accent-fg: var(--ds-color-pink-400); }
```

`token_diff.py` on v1 -> v2 prints `## Tokens (minor)`: added `color.pink.400`, `color.pink.600`;
value changed `color.accent.fg` and `color.accent.fill` in both modes; run the screenshot diff. APCA
(advisory only) rates `#F56B7A` on navy at Lc -45.7: fine for 24 px bold links, weak for 16 px body
links, so record it as a known limitation rather than a failure.

## Pitfalls

- Hex strings where 2025.10 expects colour objects; Style Dictionary < 5.3 and older tools choke on
  the objects instead, so pin versions before migrating.
- `hex` fallback out of sync with `components` after someone edits one of them.
- Aliases that cross tiers backwards (primitive -> semantic, semantic -> component) or skip a tier
  (component -> primitive); one theme change then misses half the UI.
- `"16"` or `{"value": 16}` without `unit`; px dimensions sent to the Compose/Swift groups (x16).
- Dark theme forked at the primitive tier (`blue.600` redefined in dark): every consumer of the
  primitive changes, including charts and print.
- Component aliases declared only on `:root`: themed subtrees keep the root colours.
- Token CSS variables named like Tailwind theme variables (self-reference), or `@theme` nested in a selector.
- Tokens nobody consumes: grep the codebase for each public token before a major release.
- Mode files with different key sets: the missing token silently falls back to the base mode.
- Contrast checked on the hex fallback while CSS ships `oklch()`; measure what is drawn.

Related: `visual-accessibility-audit`, `oklch-palette-ramps`, `type-scale-systems`,
`brand-guidelines-system`, `ui-mockup-hifi`, `kotlin-compose`, hub `graphic-design`.
