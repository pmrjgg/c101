# Jest -> Vitest migration map

Migrate in one PR per package: config first, then a codemod-style rename, then fix the residue by
running the suite. Keep Jest runnable until the Vitest run is green in CI.

## API map

| Jest | Vitest | Notes |
|---|---|---|
| `jest.fn()` | `vi.fn()` | typed: `vi.fn<typeof realFn>()` |
| `jest.spyOn(obj, "m")` | `vi.spyOn(obj, "m")` | 4.x+: `restoreAllMocks` restores only `spyOn` spies |
| `jest.mock("./m")` (automock) | `vi.mock("./m")` | automock replaces exports with spies returning `undefined` |
| `jest.mock("./m", () => ({...}))` | `vi.mock("./m", () => ({...}))` | factory cannot use outer variables: move them into `vi.hoisted` |
| default export in factory | `vi.mock("./m", () => ({ default: fn }))` | Jest's `__esModule: true` trick is not needed |
| `jest.requireActual("./m")` | `await vi.importActual<typeof import("./m")>("./m")` | async; or `vi.mock(import("./m"), async (orig) => ({ ...(await orig()), x: vi.fn() }))` |
| `jest.requireMock` | `await vi.importMock("./m")` | |
| `jest.doMock` | `vi.doMock` | not hoisted; import the module dynamically after it |
| `jest.resetModules()` | `vi.resetModules()` | does not reset mocks registry |
| `jest.useFakeTimers()` | `vi.useFakeTimers()` | `nextTick`/`queueMicrotask` not faked by default |
| `jest.advanceTimersByTime` | `vi.advanceTimersByTime` / `...Async` | prefer the async form with promises |
| `jest.setSystemTime` | `vi.setSystemTime` | |
| `jest.clearAllMocks` / `resetAllMocks` / `restoreAllMocks` | `vi.clearAllMocks` / `vi.resetAllMocks` / `vi.restoreAllMocks` | |
| `jest.isolateModules(fn)` | `vi.resetModules()` + dynamic import | |
| `expect.extend` | `expect.extend` | type via `declare module "vitest" { interface Matchers<T> { ... } }` (5.x: `Matchers<R, T>`; `jest.Matchers` augmentation is ignored) |
| `test.each` / `describe.each` | same | tagged-template form supported |
| `test(name, done => ...)` | return or await a promise | `done` callbacks are not supported |
| `test.concurrent` | `test.concurrent` | use the `expect` from the test context: `test.concurrent("x", async ({ expect }) => ...)` |
| `@jest-environment jsdom` docblock | `// @vitest-environment jsdom` | or a project with `environment: "jsdom"` |

## Config map

| `jest.config` | `vitest.config.ts` (`test.*` unless noted) |
|---|---|
| `testEnvironment` | `environment` |
| `testMatch` / `testRegex` | `include` (globs) |
| `testPathIgnorePatterns` | `exclude` |
| `setupFiles` / `setupFilesAfterEnv` | `setupFiles` (runs before each test file, after the environment) |
| `globalSetup` / `globalTeardown` | `globalSetup` (one module exporting `setup`/`teardown`, or a returned teardown function) |
| `moduleNameMapper` | top-level `resolve.alias` |
| `transform` (ts-jest, babel-jest) | nothing: Vite transforms TS/JSX; Babel-only syntax needs a Vite plugin |
| `collectCoverageFrom` | `coverage.include` |
| `coverageThreshold.global` | `coverage.thresholds` |
| `clearMocks` / `resetMocks` / `restoreMocks` | same names (`clearMocks` defaults to `true` in 5.x) |
| `testTimeout` | `testTimeout` (default 5000 ms) |
| `projects` | `projects` |
| `maxWorkers` | `maxWorkers` |
| `snapshotSerializers` | `snapshotSerializers` |
| `injectGlobals: true` (default in Jest) | `globals: true` only if you cannot add imports; prefer explicit imports |

## Behaviour differences that cause failures after the rename

1. Hoisting: Jest hoists `jest.mock` above imports via Babel; Vitest hoists `vi.mock` too, but in 5.x only
   top-level calls are allowed and factories cannot close over module variables (use `vi.hoisted`).
2. ESM: Vitest runs real ESM semantics. Module namespace objects of externalized packages are frozen,
   so `vi.spyOn(fs, "readFileSync")` on `import * as fs from "node:fs"` fails; mock the module instead.
3. Snapshot format: Vitest's default serializer differs slightly (quotes, `[Function]` names, 4.x
   `vi.fn()` mock names). Regenerate with `-u` once and review the whole diff in a dedicated commit.
4. Timers: Vitest fakes `Date` (and `Temporal` in 5.x) by default; tests that relied on a real `Date`
   while timers were faked must set `toFake`.
5. Environment per file: Jest's per-file docblock works (`// @vitest-environment jsdom`), but projects
   are cheaper to maintain.
6. `expect.assertions` inside `test.concurrent` must use the context `expect`.
7. Module mocks are per test file (each file has its own module graph unless `isolate: false`).

## Mechanical rename

```bash
# preview first; review the diff before committing
grep -rlE '\bjest\.' src test | xargs sed -i.bak -E \
  -e 's/\bjest\.(fn|spyOn|mock|unmock|doMock|resetModules|useFakeTimers|useRealTimers|advanceTimersByTime|runAllTimers|runOnlyPendingTimers|setSystemTime|clearAllMocks|resetAllMocks|restoreAllMocks|mocked)\b/vi.\1/g' \
  -e 's/\bjest\.requireActual\(/await vi.importActual(/g'
find src test -name '*.bak' -delete
# then add `import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";` where needed
# (or a codemod tool; check it targets your Vitest major)
```

`requireActual` -> `await vi.importActual` makes the enclosing factory async; fix those by hand.

## Done criteria

- `vitest run` green in CI on the same Node matrix; coverage thresholds at least as strict as before.
- No `jest` or `@types/jest` in `package.json`; `types` in tsconfig no longer lists `jest`.
- Run the suite three times with `--sequence.shuffle` to surface order dependence the old runner hid.
