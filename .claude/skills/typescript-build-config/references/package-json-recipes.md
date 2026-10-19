# package.json recipes for TypeScript packages

Condition order matters: Node and TypeScript take the first matching key in object order. Put `types`
first inside every condition object, and `default` last.

## 1. ESM-only, single entry (preferred)

```json
{
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

`default` (not `import`) lets Node 20.19+/22.12+ CJS consumers `require()` it. Check with
`npx publint --strict` and attw `--profile esm-only`.

## 2. ESM-only with subpath exports

```json
{
  "exports": {
    ".": { "types": "./dist/index.d.ts", "default": "./dist/index.js" },
    "./testing": { "types": "./dist/testing.d.ts", "default": "./dist/testing.js" },
    "./package.json": "./package.json"
  }
}
```

Anything not listed is private: deep imports (`pkg/dist/x.js`) fail with ERR_PACKAGE_PATH_NOT_EXPORTED,
which is the point. Pattern exports (`"./plugins/*": {...}`) work but make attw and API review harder.

## 3. Dual ESM + CJS (only when old consumers require it)

tsdown: `format: ["esm", "cjs"]`, `dts: true`. Output with `fixedExtension: true` is `.mjs`/`.cjs` with
`.d.mts`/`.d.cts`, which keeps each format's types next to its JS:

```json
{
  "type": "module",
  "exports": {
    ".": {
      "import": { "types": "./dist/index.d.mts", "default": "./dist/index.mjs" },
      "require": { "types": "./dist/index.d.cts", "default": "./dist/index.cjs" }
    },
    "./package.json": "./package.json"
  },
  "main": "./dist/index.cjs",
  "types": "./dist/index.d.cts"
}
```

`main`/`types` are fallbacks for `node10` resolvers only. A single `.d.ts` shared by both formats is the
"masquerading as ESM/CJS" bug that attw reports; ship one declaration file per format.

Hazard mitigation: keep state (caches, registries, singletons) out of module scope, or make the CJS
entry a thin wrapper over the ESM implementation (`module.exports = require("./index.mjs");`, valid where
require(esm) is available) so only one copy of the code ever loads.

## 4. Runtime-specific conditions

```json
{
  "exports": {
    ".": {
      "types": "./dist/index.d.ts",
      "workerd": "./dist/index.workerd.js",
      "browser": "./dist/index.browser.js",
      "node": "./dist/index.node.js",
      "default": "./dist/index.js"
    }
  }
}
```

Bundlers pick `browser`; Node picks `node`; Cloudflare Workers tooling picks `workerd`; every
condition still shares one `types` entry, so the public API must be identical across them.

## 5. Internal imports (`#` specifiers)

```json
{
  "imports": {
    "#config": "./dist/config.js",
    "#internal/*": "./dist/internal/*.js"
  }
}
```

Works in Node, bundlers and TypeScript (`nodenext`/`bundler`) without `paths`. Unlike `paths`, it is a
runtime feature, so production and tests resolve the same way.

## 6. Source-first internal workspace package (not published)

```json
{
  "name": "@acme/ui",
  "private": true,
  "type": "module",
  "exports": { ".": "./src/index.ts" }
}
```

Consumers must compile TypeScript from `node_modules` (Vite does; Next.js needs `transpilePackages`;
Node type stripping refuses files under `node_modules`). Switch to recipe 1 the day it is published.

## 7. CLI package

```json
{
  "type": "module",
  "bin": { "acme": "./dist/cli.js" },
  "files": ["dist"],
  "engines": { "node": ">=22.12.0" }
}
```

`dist/cli.js` must start with `#!/usr/bin/env node`: put it in the entry source and confirm with
`head -1 dist/cli.js` after the build.
Parse arguments with `util.parseArgs`; keep startup fast by lazy-importing heavy modules.

## 8. Fields checklist

| Field | Purpose | Check |
|---|---|---|
| `exports` | the only public entry points | publint, attw |
| `files` | what ships; omit and you publish tests and sources | `npm pack --dry-run` |
| `sideEffects: false` | lets bundlers drop unused modules | false only if importing a module never mutates globals (CSS imports are side effects) |
| `engines.node` | supported runtime range | match the CI matrix |
| `peerDependencies` | frameworks the consumer provides (react, typescript for tools) | avoid duplicate copies |
| `packageManager` / `devEngines` | toolchain pinning for contributors | CI uses the same version |
| `publishConfig.provenance` | npm provenance attestation | publish from CI only |
