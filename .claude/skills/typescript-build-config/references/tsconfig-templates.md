# Annotated tsconfig templates (TypeScript 6.0 / 7.0)

All templates set options explicitly even where TS 6 defaults match, so the same file behaves the same
on 5.x-era tools that read tsconfig (bundlers, IDE plugins, ts-node successors).

## Shared base: `tsconfig.base.json`

```jsonc
{
  "compilerOptions": {
    "strict": true,                         // default since 6.0; explicit for older readers
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "noPropertyAccessFromIndexSignature": true,
    "noFallthroughCasesInSwitch": true,
    "noImplicitReturns": true,
    "exactOptionalPropertyTypes": true,     // drop for legacy code (see typescript-strict-types)
    "verbatimModuleSyntax": true,           // `import type` required; makes single-file transpilers safe
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true
  }
}
```

## Bundled browser app (Vite / React)

```jsonc
{
  "extends": "./tsconfig.base.json",
  "compilerOptions": {
    "target": "es2022",
    "lib": ["es2024", "dom"],               // 6.0: "dom" now includes dom.iterable
    "module": "preserve",                    // implies moduleResolution "bundler"
    "jsx": "react-jsx",
    "noEmit": true,                          // Vite/Rolldown emits
    "allowImportingTsExtensions": true,      // only legal with noEmit / emitDeclarationOnly
    "types": ["vite/client"],                // 6.0 default is []
    "paths": { "@/*": ["./src/*"] }          // mirror in vite.config resolve.alias
  },
  "include": ["src"]
}
```

Vite projects usually split `tsconfig.app.json` (browser, `dom`) and `tsconfig.node.json`
(`vite.config.ts`, `types: ["node"]`, no `dom`) under a root `tsconfig.json` with `"files": []` and
`references` to both; type-check with `tsc -b`.

## Node service compiled with tsc

```jsonc
{
  "extends": "./tsconfig.base.json",
  "compilerOptions": {
    "target": "es2024",                     // Node 22+; es2023 if Node 20.19 is still supported
    "lib": ["es2024"],                       // no dom
    "module": "nodenext",                    // or "node20" to freeze Node 20 semantics
    "types": ["node"],
    "rootDir": "src",
    "outDir": "dist",
    "sourceMap": true,                       // run with node --enable-source-maps
    "incremental": true
  },
  "include": ["src"]
}
```

## Node service run directly with type stripping (no build)

```jsonc
{
  "extends": "./tsconfig.base.json",
  "compilerOptions": {
    "target": "esnext",
    "module": "nodenext",
    "types": ["node"],
    "noEmit": true,
    "erasableSyntaxOnly": true,              // reject enums, namespaces with values, parameter properties
    "rewriteRelativeImportExtensions": true, // write ./util.ts; emits ./util.js if you ever compile
    "verbatimModuleSyntax": true
  },
  "include": ["src"]
}
```

Run: `node src/main.ts` (Node 22.18+ / 23.6+). CI: `tsc -p . --noEmit`.

## Published library (bundled by tsdown)

```jsonc
{
  "extends": "./tsconfig.base.json",
  "compilerOptions": {
    "target": "es2023",
    "lib": ["es2023"],
    "module": "nodenext",
    "types": ["node"],                      // omit if the library is runtime-neutral
    "declaration": true,
    "isolatedDeclarations": true,           // explicit export types; enables fast oxc .d.ts generation
    "declarationMap": true,
    "noEmit": true                          // tsdown emits JS and .d.ts; tsc only checks
  },
  "include": ["src"]
}
```

## Library emitted by tsc only (no bundler)

```jsonc
{
  "extends": "./tsconfig.base.json",
  "compilerOptions": {
    "target": "es2023",
    "lib": ["es2023"],
    "module": "nodenext",
    "rootDir": "src",
    "outDir": "dist",
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "stripInternal": true                   // drop /** @internal */ members from .d.ts
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

## Monorepo leaf package with project references

```jsonc
// packages/retry/tsconfig.json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "composite": true,                       // implies declaration; required to be referenced
    "rootDir": "src",
    "outDir": "dist",
    "module": "nodenext",
    "types": ["node"]
  },
  "include": ["src"]
}
// apps/api/tsconfig.json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": { "composite": true, "rootDir": "src", "outDir": "dist", "module": "nodenext", "types": ["node"] },
  "references": [{ "path": "../../packages/retry" }],
  "include": ["src"]
}
// tsconfig.json (root, solution file)
{ "files": [], "references": [{ "path": "packages/retry" }, { "path": "apps/api" }] }
```

`tsc -b` builds in dependency order and skips up-to-date projects via `.tsbuildinfo`;
`tsc -b --verbose` explains why a project rebuilt; TS 7 adds `--builders N` for concurrency.

## Test files

Keep tests type-checked: either include them in the main config (`noEmit` builds) or add
`tsconfig.test.json` extending the main one with `"include": ["src", "test"]` and `"types": ["node"]`
(add `"vitest/globals"` only when Vitest `globals: true`).
