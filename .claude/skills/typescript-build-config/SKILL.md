---
name: typescript-build-config
description: "Configuring TypeScript projects and builds (TS 6/7): tsconfig matrix for bundled apps, Node services and libraries, removed legacy options, ESM/CJS and types-first package.json exports, pnpm workspaces and project references, running TS directly (Node type stripping, tsx, Bun, Deno), tsc/tsdown/esbuild/Vite, lint/format and type-check speed. Load when creating or fixing tsconfig, module resolution, package publishing or TS builds."
when_to_use: "Editing tsconfig*.json, package.json exports/imports/engines, pnpm-workspace.yaml, tsdown/esbuild/vite configs; errors TS2307, TS2835, TS1479, TS5101/TS5102, TS5107/TS5108, ERR_MODULE_NOT_FOUND, ERR_REQUIRE_ESM, ERR_PACKAGE_PATH_NOT_EXPORTED, 'default is not a function'; publishing an npm package; upgrading to TypeScript 6 or 7."
---

# TypeScript build configuration

Baseline (October 2026): TypeScript 6.0.x and 7.0.x (Go-native `tsc` in the `typescript` package),
Node 24 (maintenance from 20 Oct 2026) and Node 26 (Active LTS from 28 Oct 2026), pnpm 11/12, Vite 8,
tsdown 0.2x. Type-level guidance lives in `typescript-strict-types`.

Deep material: [annotated tsconfig templates](references/tsconfig-templates.md) |
[package.json recipes](references/package-json-recipes.md)

## 1. Orient

```bash
npx tsc -v; node -v; cat .nvmrc .node-version mise.toml 2>/dev/null
jq '{type, exports, main, types, imports, engines, packageManager}' package.json
npx tsc --showConfig -p . | jq '.compilerOptions | {module, moduleResolution, target, lib, types, strict, noEmit}'
ls pnpm-workspace.yaml turbo.json nx.json tsconfig*.json 2>/dev/null
```

`tsc --showConfig` prints the resolved config including `extends` chains; read it before editing.

## 2. Decision matrix

| Project kind | `module` | `moduleResolution` | Emit | Imports look like | `lib` / `types` |
|---|---|---|---|---|---|
| bundled app (Vite, Next, React Router) | `"preserve"` (or `"esnext"`) | `"bundler"` (implied by `preserve`) | `noEmit: true`; bundler emits | `./util` (extensionless ok) | `["es2024", "dom"]`; `types: ["vite/client"]` |
| Node service or CLI run by Node | `"nodenext"` (or `"node20"` to pin behaviour) | implied | `tsc` to `dist/`, or none with type stripping | `./util.js`, or `./util.ts` + `rewriteRelativeImportExtensions` | `["es2024"]`, no `dom`; `types: ["node"]` |
| published library | `"nodenext"` | implied | `tsdown`/`tsc` to `dist/` + `.d.ts` | `./util.js` | runtime-neutral `lib`; `types: ["node"]` only if it uses Node APIs |
| tests / scripts in a bundled repo | inherit app config | | `noEmit` | | add `types: ["node", "vitest/globals"]` only if `globals: true` |

Rules:
- `target`/`lib` match the oldest runtime you support (Node 20.19+ supports ES2023 fully; ES2024 needs Node 22+).
  TS 6 defaults `target` to `es2025`; set it explicitly for libraries.
- TS 6 defaults `types` to `[]`: without `"types": ["node"]` you get TS2591 "Cannot find name 'process'".
  `"types": ["*"]` restores 5.x behaviour (loads every `@types/*`; slower, leaks globals).
- Never put `dom` in a Node project's `lib`: `window`, `document` and `localStorage` then compile and fail at runtime.
- `"module": "nodenext"` follows `package.json` `"type"` per file: `.mts` is always ESM, `.cts` always CJS.

## 3. TS 6 / 7 migration

| Removed in 7.0 (deprecated in 6.0) | Replacement |
|---|---|
| `moduleResolution: "node"`/`"node10"` (TS5107 -> TS5108), `"classic"` | `"nodenext"` or `"bundler"` |
| `baseUrl` (TS5101 -> TS5102) | `paths` with explicit prefixes: `"paths": { "@/*": ["./src/*"] }` |
| `target: "es5"`, `downlevelIteration` | `target` >= `es2015`; transpile further with a bundler if needed |
| `module: "amd" \| "umd" \| "systemjs" \| "none"`, `outFile` | ESM plus a bundler |
| `esModuleInterop: false`, `allowSyntheticDefaultImports: false`, `alwaysStrict: false` | delete (always on) |
| `import x from "y" assert {...}` | `with { type: "json" }` |

Other TS 6 defaults: `strict: true`, `module: "esnext"`, `noUncheckedSideEffectImports: true`,
`rootDir` = tsconfig directory, `dom` lib now includes `dom.iterable`. Passing files on the command line
while a tsconfig exists is TS5112; use `tsc -p .` or `--ignoreConfig`.

Upgrade path: 5.x -> 6.0 with `"ignoreDeprecations": "6.0"` as a stopgap -> fix every TS5101/TS5107 ->
remove `ignoreDeprecations` -> 7.0. Optionally run `--stableTypeOrdering` on 6.0 to preview 7.0's
type ordering in declaration output (slower, diagnostic only).

TS 7 has no stable programmatic API until 7.1. Tools importing `typescript` as a library
(typescript-eslint peers `typescript <6.1` as of 8.71, Vue/Svelte/Astro/Angular tooling, ts-morph)
need 6.x. Run both:

```json
{ "devDependencies": {
    "@typescript/native": "npm:typescript@^7.0.2",
    "typescript": "npm:@typescript/typescript6@^6.0.2" } }
```

`tsc` then runs 7.0, `tsc6` runs 6.0, and `import "typescript"` resolves to 6.0. Verify with
`npx tsc -v` and `npx tsc6 -v`. Nightly 7.x previews: `@typescript/native-preview` (`tsgo` binary).

## 4. ESM vs CJS

| Situation | Choose |
|---|---|
| new app or service | ESM only: `"type": "module"` |
| new library, consumers on Node >= 20.19 / 22.12 | ESM only; CJS consumers `require()` it (require(esm) is unflagged there) |
| library with consumers on older Node or tools that cannot load ESM | dual build (tsdown `format: ["esm", "cjs"]`) and accept the dual-package hazard |
| one CJS file in an ESM package (config loaded by an old tool) | `.cts` / `.cjs` |

require(esm) limits: the ESM graph must not use top-level `await` (ERR_REQUIRE_ASYNC_MODULE), and the
`exports` condition must match `require`: use `"default"`, not `"import"` alone, or `require()` fails with
ERR_PACKAGE_PATH_NOT_EXPORTED. TypeScript models this under `module: "nodenext"`/`"node20"`; under
`"node16"` the same import is TS1479.

Dual-package hazard: ESM and CJS copies of one package load twice, so `instanceof`, singletons and
module-level caches split. Avoid by shipping ESM only, or by making the CJS entry a thin wrapper
re-exporting one implementation.

## 5. Library `package.json`

```json
{
  "name": "@acme/retry",
  "type": "module",
  "exports": {
    ".": { "types": "./dist/index.d.ts", "default": "./dist/index.js" },
    "./package.json": "./package.json"
  },
  "files": ["dist"],
  "sideEffects": false,
  "engines": { "node": "^20.19.0 || >=22.12.0" }
}
```

- `types` is listed first in every condition object; conditions match in order, so a later `types`
  is never seen.
- `"import"`-only maps break `require(esm)` consumers; `"default"` serves both.
- `main`/`types` top-level fields are only for `node10` resolvers (legacy tools); TS 7 no longer
  supports that resolution mode.
- `isolatedDeclarations: true` forces explicit types on exports so declaration files can be produced
  per file without the checker (tsdown/rolldown-plugin-dts then uses the fast oxc generator).

Validate every release candidate:

```bash
npx publint --strict                         # packaging errors (missing files, wrong conditions)
pnpm pack && npx @arethetypeswrong/cli acme-retry-1.0.0.tgz --profile esm-only
# npm users: npx @arethetypeswrong/cli --pack . --profile esm-only   (--pack only supports npm)
```

attw without a profile still flags ESM-only packages as "CJSResolvesToESM / dynamic import only" for
`node16 (from CJS)` even though Node 20.19+/22.12+ can `require()` them; `--profile esm-only` ignores CJS
resolution, `--profile node16` ignores only `node10`. More layouts (dual, subpaths, conditions per
runtime): [package-json-recipes](references/package-json-recipes.md).

## 6. Monorepos

```yaml
# pnpm-workspace.yaml
packages: ["apps/*", "packages/*"]
catalog:
  typescript: ^6.0.3
  vitest: ^5.0.5
```

- Internal dependency: `"@acme/retry": "workspace:*"`; shared versions: `"vitest": "catalog:"`.
- Two internal-package styles:

| Style | `exports` points at | Pros | Cons |
|---|---|---|---|
| source package (internal only) | `./src/index.ts` | no build step, instant HMR | every consumer's bundler/tsconfig must handle TS; cannot publish |
| built package (publishable) | `./dist/index.js` + `.d.ts` | real artefact, cacheable | build before dependents; use project references or task graph |

- Project references for type-checking speed and correct ordering:
  `packages/retry/tsconfig.json` has `"composite": true` (implies `declaration`), the app has
  `"references": [{ "path": "../../packages/retry" }]`, and CI runs `tsc -b` (incremental via
  `.tsbuildinfo`; `tsc -b --clean` to reset). TS 7: `tsc -b --builders 4` builds projects concurrently.
- `paths` is type-only: Node and most runtimes do not read it. Runtime aliases need the bundler's
  `resolve.alias` or the `package.json` `imports` field: `"imports": { "#internal/*": "./dist/internal/*.js" }`
  for built output, or `"./src/internal/*.ts"` when Node runs the sources with type stripping (`tsc`
  resolves both under `nodenext`; TS 6 also accepts the bare `#/` prefix).
- Task caching: Turborepo (`turbo run build test --filter=...[origin/main]`) or Nx (`nx affected -t build`);
  declare `outputs` (`dist/**`, `.tsbuildinfo`) or the cache restores nothing.

## 7. Running TypeScript without a build step

| Runner | Supports | Type checks? | Use for |
|---|---|---|---|
| Node type stripping (default since 23.6 / 22.18; stable since 25.2 / 24.12) | erasable syntax only; no enums, namespaces with values, parameter properties, `paths`; not under `node_modules` | no | services and scripts on Node 22.18+ |
| `tsx` (esbuild) | full TS incl. enums, `tsx watch` | no | dev loops, legacy code with enums |
| Bun | native TS, `bun test`, `bun build --compile` | no | Bun-native projects |
| Deno 2 | native TS, `deno check` | yes with `deno check` | Deno projects |

For Node stripping set `erasableSyntaxOnly`, `verbatimModuleSyntax`, `rewriteRelativeImportExtensions`
and import with `.ts` extensions; `--experimental-transform-types` (enums via transformation) was removed
in Node 26. Every row still needs `tsc --noEmit` (or `tsc -b`) in CI; runners only erase types.

## 8. Build tools

| Tool | Use for | Notes |
|---|---|---|
| `tsc` | declarations; small libraries without bundling | slowest emit; the only full-fidelity `.d.ts` without `isolatedDeclarations` |
| tsdown (Rolldown) | bundled libraries, ESM/CJS, `.d.ts` | `platform: "node"` defaults `fixedExtension: true` (`.mjs`/`.d.mts`); set `false` for `.js` |
| esbuild | scripts, CLIs, Lambda bundles | no type checking, no `.d.ts`; bundling CJS deps into ESM may need a `createRequire` banner |
| Vite | apps; library mode for UI kits | `vite build`; typecheck separately (`tsc -b` or `vue-tsc`) |

Always emit source maps (`sourceMap`, `declarationMap` for go-to-source in consumers) and run Node with
`--enable-source-maps` so stack traces point at `.ts` lines.

## 9. Lint and format

| Setup | When | Command |
|---|---|---|
| ESLint 9/10 flat config + typescript-eslint `recommendedTypeChecked`/`strictTypeChecked` with `parserOptions.projectService: true` | TS 6 (or TS 7 with the 6.0 alias above) | `eslint . --max-warnings 0` |
| oxlint + `oxlint-tsgolint` | TS 7.0+ (requires it); legacy options like `baseUrl` unsupported | `oxlint --type-aware` (`--type-check` also reports compiler errors) |
| Biome | fast lint + format in one tool | `biome check --write` |
| Prettier | formatting alongside ESLint only | `prettier --check .` |

Type-aware lint is the slow step; run it in CI and pre-push, keep editor lint syntactic if it lags.
Rule choices: `typescript-strict-types`.

## 10. Type-check performance

| Step | Command / setting | Look for |
|---|---|---|
| baseline | `tsc --noEmit --extendedDiagnostics` | `Check time`, `Instantiations`, `Types`, `Memory used`, `Files` |
| trace | `tsc --noEmit --generateTrace .trace && npx @typescript/analyze-trace .trace` | hot files, expensive types |
| skip `.d.ts` re-checks | `skipLibCheck: true` | large share of check time in dependency-heavy apps |
| incremental | `incremental: true` or `composite` + `tsc -b` | warm runs |
| split | project references per package/layer | parallel and cached builds |
| simplify types | unions with hundreds of members, deep conditional/recursive types, wide zod inference chains | instantiation counts in the millions |
| TS 7 | `--checkers N` (per-project checker parallelism), `--builders N` (projects in parallel), `--singleThreaded` | memory vs speed on CI runners |

Budget: if `Instantiations` grows >2x in a PR, find the type that caused it before merging.

## 11. Package managers and runtimes

- pnpm 11: `minimumReleaseAge` defaults to 1440 min (1-day cooldown), `strictDepBuilds: true` (dependency
  lifecycle scripts blocked unless allowed via `allowBuilds: { esbuild: true }`), Node 22+ required, pnpm
  settings live in `pnpm-workspace.yaml` (`.npmrc` is auth/registry only). pnpm 12 (Rust rewrite, Aug 2026)
  keeps these and adds stricter workspace-setting validation; `--frozen-lockfile false` is gone (use
  `--no-frozen-lockfile`).
- npm 11, Bun: fine for single packages; for monorepos prefer pnpm workspaces.
- Pin the manager: `"packageManager": "pnpm@12.14.0"`. Node 25+ no longer ships Corepack: install pnpm
  explicitly (`npm i -g pnpm`, `npm i -g corepack`, mise, or the CI setup action).
- Pin Node: `.nvmrc` / `mise.toml` (`node = "24"`), `engines.node` for consumers, CI matrix Node 24 + 26,
  Node 22 until it reaches EOL on 30 Apr 2027.

## 12. Error -> fix

| Symptom | Cause | Fix |
|---|---|---|
| TS2307 Cannot find module './x' | resolution mode mismatch (bundler-style import under `nodenext`) | add `.js` or use `.ts` + `rewriteRelativeImportExtensions`; or switch to `bundler` for bundled code |
| TS2307 for a package | package `exports` lacks `types` (or lists it last); missing `@types/x` | fix upstream or add `@types`; check with attw |
| TS2835 relative import needs extension | `nodenext` | `./x.js` |
| TS1479 CJS file importing ESM | `module: "node16"` | `nodenext`/`node20`, or make the file ESM (`.mts`, `"type": "module"`) |
| TS2591 `process` / `Buffer` not found | TS 6 `types: []` default | `"types": ["node"]` |
| ERR_MODULE_NOT_FOUND at runtime | emitted import without extension (compiled with `bundler` resolution, run by Node) | use `nodenext` for code Node runs |
| ERR_REQUIRE_ESM | Node < 20.19 / 22.12, or `--no-experimental-require-module` | upgrade Node; or `await import()` |
| ERR_REQUIRE_ASYNC_MODULE | required ESM graph uses top-level await | remove TLA from the library entry |
| ERR_PACKAGE_PATH_NOT_EXPORTED | subpath not in `exports`, or only an `"import"` condition when `require()`d | add the subpath / a `"default"` condition |
| ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX | enum/namespace/parameter property under Node type stripping | `erasableSyntaxOnly`, replace the construct |
| `x.default is not a function` / `default.default` | CJS module with `exports.default` imported from ESM | `import pkg from "x"; const fn = pkg.default ?? pkg;` or use the package's ESM build |
| "Types have separate declarations of a private property" (TS2322) | two copies of a package (`pnpm why x` shows two versions) | dedupe (`pnpm dedupe`, `overrides`), align versions, or `peerDependencies` |
| `window`/`document` compile in Node code | `dom` in `lib` | remove `dom`; split browser and server tsconfigs |

## 13. Pitfalls

- `paths` without a runtime alias: compiles, then ERR_MODULE_NOT_FOUND in production.
- `moduleResolution: "bundler"` for code executed by Node without a bundler.
- `"types"` condition after `"import"`/`"default"`: TypeScript never reaches it.
- `skipLibCheck` hiding broken `.d.ts` you publish yourself: run attw on your own package.
- `declaration` emitted by `tsc` and bundled JS from another tool drifting apart: one tool per artefact, or tsdown for both.
- `noEmit` in the base config inherited by the package that is supposed to emit.
- `outDir` inside `include` (re-checks `dist/`): `"include": ["src"]` explicitly.
- `allowJs` + `checkJs` in a large legacy repo multiplies check time; scope with `include`.
- `.d.ts` files with `declare module "x";` turn a whole package into `any`.
- Corepack assumptions in CI images on Node 25+: the `pnpm` binary is simply missing.

## 14. Worked example: publish `@acme/retry` ESM-only

1. `src/index.ts` exports `retry<T>(fn: (attempt: number) => Promise<T>, opts: RetryOptions = {}): Promise<T>`
   (exponential backoff with full jitter, `AbortSignal` support); every export has an explicit type.
2. `tsconfig.json` (type-check only; tsdown emits):

```json
{ "compilerOptions": {
    "target": "es2023", "lib": ["es2023"], "module": "nodenext", "types": ["node"],
    "strict": true, "verbatimModuleSyntax": true, "erasableSyntaxOnly": true,
    "isolatedDeclarations": true, "declaration": true, "noEmit": true,
    "noUncheckedIndexedAccess": true, "skipLibCheck": true },
  "include": ["src"] }
```

3. `tsdown.config.ts`:

```ts
import { defineConfig } from "tsdown";
export default defineConfig({
  entry: ["src/index.ts"], format: "esm", platform: "node", target: "node20.19",
  fixedExtension: false, dts: true, sourcemap: true, clean: true,
});
```

   `npx tsdown` -> `dist/index.js` 0.70 kB, `dist/index.js.map`, `dist/index.d.ts` 0.40 kB in 275 ms.
4. `package.json` as in section 5. `npx publint --strict` -> "All good!".
   `npx @arethetypeswrong/cli acme-retry-1.0.0.tgz` without a profile warns
   `node16 (from CJS): ESM (dynamic import only)` and `node10: Resolution failed`; with
   `--profile esm-only` both rows are ignored and the check passes.
5. Consumers:
   - Vite app (`moduleResolution: "bundler"`): `import { retry } from "@acme/retry"` resolves via `default`.
   - Node 24 CJS service (`"type": "commonjs"`, TS `module: "nodenext"`): `import { retry } from "@acme/retry"`
     type-checks and compiles to `require("@acme/retry")`, which loads the ESM build;
     `node -e 'require("@acme/retry").retry(...)'` returned `ok@2` after two retries. With
     `module: "node16"` the same import is TS1479.
6. CI matrix: Node 24, Node 26 and Bun 1.x run `pnpm test`; one job runs `tsc6 --noEmit` and
   `tsc --noEmit` (6.0 and 7.0 via the alias in section 3), `publint --strict` and attw; publish only from the tagged commit with provenance
   (`npm publish --provenance`).

Related: `typescript-strict-types`, `typescript-testing-vitest`, `node-runtime-patterns`,
`react-typescript-components`, `dependency-upgrades`, `ci-pipelines`, hub `coding-general`.
