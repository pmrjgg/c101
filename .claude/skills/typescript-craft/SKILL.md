---
name: typescript-craft
description: "TypeScript and Node expertise pack covering strict types (unknown over any, narrowing, discriminated unions, satisfies, branded types), tsconfig and moduleResolution, ESM/CJS interop and package exports, async correctness (floating promises, AbortSignal, unhandled rejections), React component typing, Vitest/Jest/node:test, package-manager and lockfile discipline, and the tsc/lint/format/test gate. Load when writing, reviewing, debugging or migrating TypeScript or Node code."
when_to_use: "Any task touching .ts/.tsx/.mts/.cts or Node .js/.mjs files, tsconfig*.json, package.json exports or engines, a tsc error code (TS2322, TS2345, TS2307, TS2835, TS1479), ERR_REQUIRE_ESM or ERR_MODULE_NOT_FOUND, unhandled promise rejections in a Node service, React hook bugs, or migrating JavaScript to strict TypeScript."
---

# TypeScript craft

Baseline (October 2026): TypeScript 6.0.x (last JS-based compiler, full programmatic API) and 7.0.x
(Go-native `tsc`, no stable programmatic API until 7.1); Node 24 (maintenance) and Node 26 (Active
LTS from 28 Oct 2026); Node 20 is EOL. TS 6 changed defaults that bite on upgrade: `strict: true`,
`types: []` (so `process` is TS2591 until `"types": ["node"]`), `module: "esnext"`, and
`moduleResolution: "node"`/`"node10"` and `baseUrl` are deprecated (removed in 7.0).
Semantics follow the repo's installed `typescript` and its resolved tsconfig, not your memory: check
both first. Versions and migration detail live in the granular skills (table at the end).

Deep material:
[async and error patterns](references/async-patterns.md) |
[JavaScript to strict TypeScript migration](references/js-migration.md)

## 1. Orient in a repo

```bash
ls pnpm-lock.yaml package-lock.json yarn.lock bun.lock bun.lockb 2>/dev/null   # package manager
jq '{type, packageManager, engines, scripts, exports, main, types}' package.json
npx tsc -v; node -v; cat .nvmrc .node-version mise.toml 2>/dev/null
npx tsc --showConfig -p . | jq '.compilerOptions | {strict, module, moduleResolution, target, lib, types, noEmit, verbatimModuleSyntax}'
ls tsconfig*.json pnpm-workspace.yaml turbo.json nx.json 2>/dev/null
ls eslint.config.* .eslintrc* biome.json biome.jsonc .prettierrc* prettier.config.* 2>/dev/null
ls vitest.config.* vite.config.* jest.config.* 2>/dev/null; jq '.scripts.test' package.json
```

Record: package manager (from the lockfile), module system (`"type"`), resolved `module` /
`moduleResolution`, strictness flags, linter + formatter, test runner, Node version pin, and whether
the package is an app (bundled or run by Node), a service, or a published library (API and
`exports` stability matter).

### Package manager: the lockfile decides

| Lockfile present | Use | Install (CI) | Run a binary |
|---|---|---|---|
| `pnpm-lock.yaml` | pnpm | `pnpm install --frozen-lockfile` | `pnpm exec <bin>` / `pnpm <script>` |
| `package-lock.json` | npm | `npm ci` | `npx <bin>` / `npm run <script>` |
| `yarn.lock` | yarn (check `packageManager` for classic 1.x vs berry) | `yarn install --immutable` (berry) / `--frozen-lockfile` (1.x) | `yarn <bin>` |
| `bun.lock` / `bun.lockb` | bun | `bun install --frozen-lockfile` | `bunx <bin>` / `bun run <script>` |

- Never mix: no `npm install` in a pnpm repo, never commit a second lockfile, never delete a
  lockfile to "fix" resolution. Two lockfiles present: ask which one CI uses (Open doubt).
- Add dependencies with the same manager (`pnpm add -D x`), then commit the lockfile diff.
- `packageManager` in package.json pins the version; Node 25+ no longer ships Corepack, so the
  binary may simply be missing in CI images.

## 2. The gate (definition of done)

Use the project's own scripts first (`jq .scripts package.json`); the commands below are the
fallbacks. `<pm>` is the manager from section 1.

| Step | Command | Blocks when |
|---|---|---|
| Type check | `<pm> exec tsc --noEmit -p .` (per project in references: `tsc -b`) | any `error TS` |
| Lint | `<pm> exec eslint .` (typescript-eslint, type-aware) or `<pm> exec biome check .` | any error |
| Format | `<pm> exec prettier --check .` or `biome format .` (whichever the repo has; never both) | any file listed |
| Tests | `<pm> exec vitest run` / `jest --ci` / `node --test` (the repo's runner) | failure or unhandled error |
| Build (libraries, services) | the `build` script (tsdown, tsc, Vite) | failure |
| Package shape (libraries) | `npx @arethetypeswrong/cli --pack .` and `npx publint` | any problem |
| Audit (deps changed) | `pnpm audit --prod` / `npm audit --omit=dev` | high or critical reachable advisory |

- Strictness of the gate is the project's. Do not loosen `strict`, add `skipLibCheck`, or disable a
  lint rule to get green; raise the issue instead.
- `tsc --noEmit` checks types only; a bundler or `tsx` running the code proves nothing about types.
  Vitest also does not type-check unless run with `--typecheck`.
- Count, do not eyeball: `<pm> exec tsc --noEmit -p . 2>&1 | grep -c 'error TS'` before and after.

## 3. Types: idioms

| Need | TypeScript shape | Not |
|---|---|---|
| value of unknown shape (JSON, `catch`, `postMessage`, env) | `unknown`, then validate (zod 4, valibot) or narrow | `any` |
| closed set of variants | discriminated union `{ kind: "ok"; value: T } \| { kind: "err"; error: E }` | optional fields soup |
| exhaustive handling | `switch (x.kind)` + `default: { const _: never = x; throw ... }` | `default: return null` |
| check a literal against a type, keep its literal type | `const routes = {...} satisfies Record<string, Route>` | `: Record<...>` (widens) or `as` |
| frozen literal tuples / config | `as const` | `enum` (runtime object, reverse maps, not erasable) |
| IDs that must not mix | branded type `string & { readonly __brand: "UserId" }` + constructor that validates | plain `string` |
| narrow a value | `typeof`, `in`, `instanceof`, discriminant check, `Array.isArray` | `as T` |
| reusable narrowing | type predicate `(x: unknown): x is User` backed by a real check | a predicate that returns `true` |
| assertion function | `function assertDefined<T>(x: T): asserts x is NonNullable<T>` | `x!` |
| infer literal from a call argument | `function f<const T extends readonly string[]>(xs: T)` | `as const` at every call site |
| stop inference from one argument | `NoInfer<T>` on that parameter | an extra overload |
| immutable inputs | `readonly T[]`, `Readonly<T>` on parameters | mutating callers' arrays |
| optional means absent | `exactOptionalPropertyTypes` + `p?: string` | `p: string \| undefined` everywhere |

Rules:
1. Annotate boundaries (exported functions, public class members, module exports); let inference do
   the inside. Return types on exported functions keep `.d.ts` stable and errors local.
2. `any` is contagious: it silently disables checking for everything it touches. Contain it at the
   source with a typed wrapper; typescript-eslint `no-unsafe-*` and `no-explicit-any` find leaks.
3. `as` is a promise you make to the compiler; each one needs a comment saying why it is true. Double
   casts (`as unknown as T`) are a review blocker without a validated reason.
4. Type guards and validators run at I/O boundaries only: parse once, then pass the typed value.
5. Prefer unions of object types over class hierarchies; prefer functions and plain objects over
   classes unless state and identity matter.
6. Generic type parameters must appear at least twice (input and output) to earn their place;
   otherwise use the concrete type or `unknown`.

## 4. Modules, resolution and ESM/CJS

| Project kind | `module` | `moduleResolution` | Relative imports |
|---|---|---|---|
| bundled app (Vite, Next) | `preserve` / `esnext` | `bundler` | extensionless ok |
| Node service or CLI run by Node | `nodenext` | implied (`nodenext`) | `./util.js` (or `.ts` with `rewriteRelativeImportExtensions`) |
| published library | `nodenext` | implied | `./util.js`; `exports` with `types` first |

- `bundler` resolution for code Node executes directly compiles fine and fails at runtime with
  ERR_MODULE_NOT_FOUND (extensionless relative import). Code Node runs uses `nodenext`.
- `nodenext` decides ESM vs CJS per file from the nearest package.json `"type"`; `.mts` is always
  ESM, `.cts` always CJS.
- `verbatimModuleSyntax: true`: `import type` for type-only imports (TS1484), emitted imports equal
  written imports. Required for Node type stripping and single-file transpilers.
- New apps, services and libraries: ESM only (`"type": "module"`). Node 20.19+/22.12+ can
  `require()` an ESM graph without top-level await; dual builds only for older consumers, and they
  bring the dual-package hazard (two copies, split `instanceof` and singletons).
- `paths` aliases are compile-time only: without a runtime or bundler alias they become
  ERR_MODULE_NOT_FOUND in production.
- Deep dive and error table: `typescript-build-config`.

## 5. Async correctness (summary; patterns in [async-patterns](references/async-patterns.md))

1. Every promise is awaited, returned, or explicitly handled: `void p.catch(log)`. Enable
   typescript-eslint `no-floating-promises` and `no-misused-promises` (type-aware lint).
2. `forEach(async ...)` does not wait; use `for...of` with `await` (sequential) or
   `Promise.all(items.map(...))` with a concurrency limit (parallel).
3. `Promise.all` rejects on the first failure but the other promises keep running: pass a shared
   `AbortController.signal` so they stop. `Promise.allSettled` when partial success is fine.
4. Every I/O call that can hang takes a signal or a timeout: `fetch(url, { signal:
   AbortSignal.timeout(5_000) })`; combine with `AbortSignal.any([req.signal, timeout])`.
5. `catch (e)` binds `unknown` under `strict`: narrow (`e instanceof Error`) before reading `.message`;
   rethrow with `new Error("load config", { cause: e })`.
6. Keep Node's default `--unhandled-rejections=throw`; `process.on("unhandledRejection")` only to log
   with context and exit non-zero, never to swallow.
7. `async` event-emitter listeners turn throws into unhandled rejections: catch inside or use
   `captureRejections: true`.
8. CPU work over ~10 ms on the event loop stalls every request: move it to `worker_threads` or chunk it.

## 6. Testing (summary; mechanics in `typescript-testing-vitest`)

```ts
import { describe, expect, it, vi } from "vitest";
import { parseAmount } from "./amount.js";

describe("parseAmount", () => {
  it.each([
    ["12.50", { ok: true, cents: 1250 }],
    ["-1", { ok: false, error: "negative" }],
    ["", { ok: false, error: "empty" }],
  ] as const)("parseAmount(%j)", (input, want) => {
    expect(parseAmount(input)).toEqual(want);
  });

  it("rejects when the rate service times out", async () => {
    vi.useFakeTimers();
    const p = convert("10", { timeoutMs: 1_000 });
    vi.advanceTimersByTime(1_000);
    await expect(p).rejects.toThrow(/timeout/);       // always await rejects/resolves
    vi.useRealTimers();
  });
});
```

- Use the runner the repo has; do not add Vitest to a Jest repo (or the reverse) inside a feature
  change. `node:test` + `node --test` is fine for small Node packages with no bundler.
- Mock at the network boundary (MSW) rather than mocking your own modules; `vi.mock` only for
  modules with side effects you cannot inject.
- Type-level behaviour of shared utilities: `expectTypeOf` in `*.test-d.ts` run by `vitest --typecheck`,
  or a `// @ts-expect-error` line that must keep failing.
- Fake timers for anything time-based; never `setTimeout` sleeps in tests.
- A bug fix starts with a failing test reproducing it.

## 7. React (summary; details in `react-typescript-components`)

- Props: a `type Props = {...}` (or interface) per component, `children: React.ReactNode` when
  needed, discriminated unions for mutually exclusive props; avoid `React.FC` for generics.
- Effects synchronise with external systems only. Derived state is computed during render; event
  logic lives in handlers. Effects that fetch handle cancellation (`AbortController` in cleanup) or
  use a server-state library.
- Keep `react-hooks/exhaustive-deps` on; a missing dependency is a stale-closure bug, not noise.
- Keys are stable IDs, never array indexes for lists that reorder.
- Test behaviour through roles and text (Testing Library `getByRole`), not implementation details.

## 8. Pitfalls (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| `Type 'string' is not assignable to type 'never'` | writing through a union of keys/objects (`obj[k] = v` with `k: "a" \| "b"`), or an empty-array literal inferred as `never[]` | generic key `<K extends keyof T>(k: K, v: T[K])`; annotate `const xs: Item[] = []` |
| TS2322 with a literal that "obviously" fits | value widened (`let`, object literal property becomes `string`) | `as const`, `satisfies`, or a literal-union annotation |
| TS2532 / TS18048 possibly undefined | `strictNullChecks` / `noUncheckedIndexedAccess` doing their job | narrow or default (`?? 0`); never `!` |
| TS2339 on a union | property exists on only some members | narrow by the discriminant first |
| TS2591 `Cannot find name 'process'` | TS 6 `types: []` default | `"types": ["node"]` |
| TS2307 / TS2835 for a relative import | `nodenext` needs an extension | `./x.js`, or switch to `bundler` for bundled code |
| TS1479 CJS importing ESM | `module: "node16"` or a CJS file | `nodenext`, or make the file ESM |
| `ERR_REQUIRE_ESM` / `ERR_REQUIRE_ASYNC_MODULE` | old Node, or the ESM graph uses top-level await | Node 20.19+/22.12+; drop TLA from library entries; or `await import()` |
| `x.default is not a function` | CJS `exports.default` imported from ESM | `const fn = pkg.default ?? pkg`, or use the package's ESM build |
| `Types have separate declarations of a private property` | two copies of one package | `pnpm why x`, dedupe or align versions |
| test passes but code is broken | unawaited `expect(...).rejects`, `forEach(async)` in the test | `await expect(...)`; `for...of` |
| process exits with code 1 and an unhandled rejection | floating promise | `no-floating-promises`; await or `.catch` |
| service hangs on shutdown | open handles (servers, intervals, sockets) | `server.close()` + `closeAllConnections()`, clear intervals, `unref()` timers |
| `JSON.parse` result used as a typed object | `any` from parse | `unknown` + schema `.parse()` |
| `window` compiles in a Node service | `dom` in `lib` | remove `dom`; split tsconfigs |
| `enum` / parameter property fails under `node file.ts` | not erasable syntax (type stripping) | `erasableSyntaxOnly`; union of literals; explicit fields |
| `{}` accepts strings and numbers | `{}` means any non-nullish value | `Record<string, never>` or `object` |
| infinite re-render / effect loop | object or array dependency recreated every render, or setState in an effect | derive in render; memoise or move the value out |

## 9. Review checklist

- [ ] `tsc --noEmit` clean under the project's strict settings; no new `any`, `as`, `!`, `@ts-ignore`
      (a justified `@ts-expect-error <reason>` only).
- [ ] External input typed `unknown` and validated once at the boundary.
- [ ] Unions are discriminated and switches exhaustive (`never` check).
- [ ] Every promise awaited or handled; long I/O takes an `AbortSignal` or timeout.
- [ ] Imports follow the resolution mode (`.js` extensions under `nodenext`, `import type` with
      `verbatimModuleSyntax`); no `dom` in Node code.
- [ ] Library `exports` list `types` first; attw and publint clean; no breaking export change
      without a major bump noted.
- [ ] Tests use the repo's runner, await every async assertion, and cover the new branch.
- [ ] One package manager, lockfile updated with the change, no second lockfile.
- [ ] Lint and formatter clean at project config; no rule disabled to get green.

## 10. Worked example: removing `any` from a config loader

Before: compiles, crashes at runtime on a missing key, and swallows errors.

```ts
export async function loadConfig(path: string): Promise<any> {
  const raw = await readFile(path, "utf8").catch(() => "{}");
  const cfg = JSON.parse(raw);
  cfg.port = parseInt(cfg.port);                       // NaN if absent, no error
  return cfg;                                          // any leaks into every caller
}
```

After: validated once, typed everywhere, errors keep their cause.

```ts
import { readFile } from "node:fs/promises";
import { z } from "zod";

const Config = z.object({
  port: z.coerce.number().int().min(1).max(65_535),
  databaseUrl: z.url(),
  logLevel: z.enum(["debug", "info", "warn", "error"]).default("info"),
});
export type Config = z.infer<typeof Config>;

export async function loadConfig(path: string): Promise<Config> {
  let raw: string;
  try {
    raw = await readFile(path, "utf8");
  } catch (e) {
    throw new Error(`read config ${path}`, { cause: e });
  }
  const parsed = Config.safeParse(JSON.parse(raw) as unknown);
  if (!parsed.success) {
    throw new Error(`invalid config ${path}: ${z.prettifyError(parsed.error)}`);
  }
  return parsed.data;
}
```

Evidence: `tsc --noEmit` error count unchanged at 0, callers that relied on `any` now fail to
compile and are fixed (they were reading `cfg.dbUrl`, a typo the old code hid), and a Vitest case
for a missing `port` asserts the thrown message. `JSON.parse` can still throw `SyntaxError`; wrap it
too if the caller must distinguish read, syntax and schema failures.

## Delegation hints

- Playwright E2E suites and cross-browser runs: `tester`; a live check of a running UI:
  `browser-operator`.
- Heap snapshots, event-loop stalls or a leak that only appears under load: `debugger`.
- Bundle size, render or throughput work against a budget: `code-optimizer`.
- Untrusted input, auth, SSRF, prototype pollution, `child_process` with user data: `security-auditor`.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `typescript-strict-types` | writing, reviewing or fixing TypeScript types: a TS error code, strict-flag adoption, replacing `any`/`as`/`!`, branded or discriminated domain types, boundary validation |
| `typescript-build-config` | creating or fixing tsconfig, `module`/`moduleResolution`, ESM/CJS, package `exports`, monorepos and project references, TS 6/7 upgrades, publishing |
| `typescript-testing-vitest` | writing, fixing or speeding up Vitest, Jest or node:test suites, mocks, fake timers, MSW, component tests, Jest migration |
| `react-typescript-components` | writing, reviewing or debugging React components or hooks: effects, state placement, forms, re-renders, hydration |
| `node-runtime-patterns` | building or debugging Node/Bun services and CLIs: event-loop stalls, cancellation, streams, HTTP timeouts, graceful shutdown, leaks |

From the required `coding-core` pack (hub `coding-general`):

| skill | load when |
|---|---|
| `codemod-automation` | the same TS change at dozens of sites (jscodeshift, ts-morph, ast-grep) |
| `dependency-upgrades` | bumping TypeScript, Node, React, Vitest or other dependencies |
| `api-contract-design` | an endpoint, OpenAPI spec or generated TS client changes |
| `resilience-patterns` | retries, timeouts, circuit breakers or bounded fan-out around network calls |
| `refactoring-playbook` | restructuring TS modules without changing behaviour |
| `regex-engineering` | writing or debugging a JS regex (`u`/`v` flags, catastrophic backtracking) |
