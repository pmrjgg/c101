# Build pipelines

Versions current in October 2026: style-dictionary 5.7.0 (Node >= 22), @terrazzo/cli 2.9.0 with
plugin-css/plugin-tailwind 2.9.0 and plugin-swift 0.3.x, tailwindcss 4.3.x. The Style Dictionary
names below were checked against its 5.7 source (transform, transform-group and format enums); the
Terrazzo options against its 2.x docs and plugin-css types. Run `npx style-dictionary --version` or
`npx tz --help` before relying on an option that is not listed here.

## 1. Style Dictionary 5.x, one build per mode

```js
// build-tokens.mjs   node build-tokens.mjs   (npm i -D style-dictionary@^5.7)
import StyleDictionary from 'style-dictionary';

// The 'css' transform group with color/css swapped for color/oklch (5.3+) so CSS keeps oklch().
const cssTransforms = ['attribute/cti', 'name/kebab', 'time/seconds', 'html/icon', 'size/rem',
  'color/oklch', 'asset/url', 'fontFamily/css', 'cubicBezier/css', 'strokeStyle/css/shorthand',
  'border/css/shorthand', 'typography/css/shorthand', 'transition/css/shorthand', 'shadow/css/shorthand'];
const semanticOnly = (token) => token.filePath.includes('semantic.');

for (const mode of ['light', 'dark']) {
  const base = mode === 'light';
  const files = base
    ? [{ destination: 'tokens.light.css', format: 'css/variables',
         options: { outputReferences: true, selector: ':root, [data-theme]' } }]
    : [{ destination: `tokens.${mode}.css`, format: 'css/variables', filter: semanticOnly,
         options: { outputReferences: true, selector: `[data-theme="${mode}"]` } },
       { destination: `tokens.${mode}-auto.css`, format: 'css/variables', filter: semanticOnly,
         options: { outputReferences: true,
                    selector: ['@media (prefers-color-scheme: dark)', ':root:not([data-theme])'] } }];
  const sd = new StyleDictionary({
    source: ['tokens/primitive.tokens.json', `tokens/semantic.${mode}.tokens.json`, 'tokens/component.tokens.json'],
    platforms: {
      css: { transforms: cssTransforms, prefix: 'ds', buildPath: 'dist/', files },
      ...(base && {
        ios: { transformGroup: 'ios-swift', buildPath: 'dist/ios/',
               files: [{ destination: 'Tokens.swift', format: 'ios-swift/class.swift',
                         options: { className: 'Tokens' } }] },
        android: { transformGroup: 'compose', buildPath: 'dist/android/',
                   files: [{ destination: 'Tokens.kt', format: 'compose/object',
                             options: { className: 'Tokens', packageName: 'com.example.tokens' } }] },
      }),
    },
  });
  await sd.buildAllPlatforms();
}
```

Notes:

- DTCG is auto-detected (`usesDtcg`); keep every source file in DTCG form.
- `options.selector` takes a string or an array; an array nests the blocks (outer first), which is
  how the `@media` + `:root:not([data-theme])` file above is produced.
- `outputReferences: true` keeps `var(--ds-color-pink-600)` chains; with the semantic-only filter
  Style Dictionary warns about references to filtered tokens. Expected: the primitives come from
  `tokens.light.css`, which must be loaded first.
- Load order in the app: `tokens.light.css`, then `tokens.dark.css`, then `tokens.dark-auto.css`.
  The base file declares semantics and components on `:root, [data-theme]`, so component aliases
  re-resolve inside every themed subtree.
- Native groups: `ios-swift` = attribute/cti, name/camel, color/UIColorSwift, content/swift/literal,
  asset/swift/literal, size/swift/remToCGFloat. `compose` = attribute/cti, name/camel,
  color/composeColor, size/compose/em, size/compose/remToSp, size/compose/remToDp. The size
  transforms multiply by `basePxFontSize` (platform option, default 16) regardless of unit: author
  dimension tokens in `rem`, or set `basePxFontSize: 1` on a platform whose tokens are all px.
- `ios-swift/class.swift` options: `className`, `accessControl` (default `public`), `import`
  (default `UIKit`). `compose/object` options: `className`, `packageName`, `import`.

## 2. Terrazzo 2.x with a resolver

```ts
// terrazzo.config.ts   npx tz build   (npm i -D @terrazzo/cli @terrazzo/plugin-css @terrazzo/plugin-tailwind)
import { defineConfig } from "@terrazzo/cli";
import css from "@terrazzo/plugin-css";

export default defineConfig({
  tokens: ["./tokens/tokens.resolver.json"],      // a resolver must be the only input
  outDir: "./dist/",
  plugins: [
    css({
      filename: "tokens.css",
      permutations: [
        { input: {}, prepare: (css) => `:root, [data-theme] {\n  color-scheme: light;\n  ${css}\n}` },
        { input: { theme: "dark" },
          prepare: (css) => `[data-theme="dark"] {\n  color-scheme: dark;\n  ${css}\n}\n` +
            `@media (prefers-color-scheme: dark) {\n  :root:not([data-theme]) {\n    ${css}\n  }\n}` },
      ],
    }),
  ],
});
```

- `input: {}` is the default permutation (the resolver's `default` contexts); the docs warn that
  without it base tokens are never declared.
- Permutation inputs are `{ <modifier name>: <context name> }`, matching `#/modifiers/theme` in the
  resolver. Legacy `$extensions.mode` token files map to the synthetic modifier `tzMode`
  (`input: { tzMode: "dark" }`); `modeSelectors` is deprecated in 2.x.
- `prepare` owns the wrapper: inside `@media` you must still write a selector (`:root`).
- `npx tz check tokens.json` validates a file against DTCG and runs lint rules; `npx tz build
  --watch` rebuilds on change; `npx tz lab` opens the web editor.
- Tailwind via plugin: `tailwind({ template: "tailwind.template.css", filename: "tailwind-theme.css",
  theme: { color: ["color.*"], spacing: ["space.*"], radius: ["radius.*"] } })` with a template
  that contains `@theme { @tz (theme: "light"); }` and `@variant dark { @tz (theme: "dark"); }`;
  every permutation used in the template must also exist in plugin-css `permutations`.

## 3. Tailwind v4 consuming token variables

```css
/* app.css */
@import "tailwindcss";
@import "./dist/tokens.light.css";
@import "./dist/tokens.dark.css";
@import "./dist/tokens.dark-auto.css";
@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *));
@theme { --color-*: initial; }
@theme inline {
  --color-surface: var(--ds-color-bg-surface);
  --color-ink: var(--ds-color-text-default);
  --color-accent: var(--ds-color-accent-fg);
  --color-accent-fill: var(--ds-color-accent-fill);
  --color-on-accent: var(--ds-color-accent-on-fill);
  --radius-card: var(--ds-radius-3);
  --font-sans: var(--ds-font-family-sans);
}
```

```html
<button class="bg-accent-fill text-on-accent rounded-card px-6 h-11">Save changes</button>
<a class="text-accent underline">Why can't I change this?</a>
```

- Namespaces: `--color-*`, `--font-*`, `--text-*`, `--font-weight-*`, `--tracking-*`, `--leading-*`,
  `--tab-size-*`, `--breakpoint-*`, `--container-*`, `--spacing-*`, `--radius-*`, `--shadow-*`,
  `--inset-shadow-*`, `--drop-shadow-*`, `--blur-*`, `--perspective-*`, `--zoom-*`, `--aspect-*`,
  `--ease-*`, `--animate-*`.
- `--color-*: initial` removes every default colour utility so only token colours exist.
- `@theme static` emits all theme variables even when unused (default emits used ones only).

## 4. Package and CI gate

```json
{
  "name": "@example/tokens",
  "version": "2.3.0",
  "files": ["dist", "tokens"],
  "scripts": {
    "validate": "python3 -I tools/validate_tokens.py tokens/",
    "build": "node build-tokens.mjs",
    "diff": "python3 -I tools/token_diff.py .tokens-prev/ tokens/ --public-prefix color. --public-prefix space.",
    "test:visual": "playwright test visual/"
  }
}
```

Order in CI: `validate` (fails on any contrast or alias error) -> `build` -> `diff` (paste into the
changelog; a major bump needs a human) -> `test:visual` in every mode.
