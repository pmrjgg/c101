---
name: typescript-testing-vitest
description: "Testing TypeScript/JavaScript with Vitest 4/5 (plus node:test and bun test): config and projects, vi.mock and vi.hoisted, spies, fake timers and dates, HTTP mocking with MSW 2/3, DOM and component tests with Testing Library and browser mode, expectTypeOf type tests, snapshots, coverage thresholds, sharding and Jest migration. Load when writing, fixing or speeding up TS/JS unit and component tests."
when_to_use: "Editing *.test.ts(x), *.spec.ts(x), *.test-d.ts, vitest.config.ts or MSW handlers; errors like 'vi.mock ... defined outside of the module top level scope', 'Cannot spy on export', 'Promise returned by expect(...).rejects was not awaited', unhandled-request warnings, act() warnings, flaky or slow JS suites; migrating from Jest."
---

# TypeScript testing with Vitest

Baseline (October 2026): Vitest **5.0.x** (Sept 2026; Node >= 22.12, Vite >= 6.4) and 4.x, MSW **3.x**
(Sept 2026; ESM-only, Node 22+) and 2.x, Testing Library React 16, user-event 14, jest-dom 7.
Check versions first: `npx vitest --version`, `npm ls msw @testing-library/react`.
What to test and at which level: `testing-strategy`. Type design: `typescript-strict-types`.

Deep material: [Jest -> Vitest migration map](references/jest-migration.md) |
[CI sharding and speed recipes](references/ci-sharding.md)

## 0. Vitest 4 -> 5 behaviour changes that bite

| Area | 4.x | 5.x |
|---|---|---|
| mock call history between tests | kept unless `clearMocks: true` | `clearMocks` defaults to `true` |
| `vi.mock`/`vi.unmock`/`vi.hoisted` placement | hoisted from anywhere | top level only; inside `it`/`describe` the file fails to collect (`vi.doMock` still allowed) |
| unawaited `rejects`/`resolves`/`toMatchFileSnapshot` | can pass vacuously | test fails ("was not awaited") |
| inline `projects` | need `extends: true` to inherit root options | inherit by default (`extends: false` opts out) |
| `-t` name filter | names joined by a space | joined by `" > "` (`-t 'math > adds'`) |
| reports | blobs in `.vitest-reports/` | `.vitest/blob/`, JSON/JUnit/HTML under `.vitest/` |
| config lookup | searched parent directories | not searched: pass `--config` from subdirectories |
| `test.sequential` | exists | removed: `{ concurrent: false }` |
| `toThrow("")` | empty message only | any message (use `/^$/` for empty) |
| fake timers | `Date` faked | `Temporal` faked with `Date` |
| browser locators | partial text match | exact by default (`browser.locators.exact: false`) |

## 1. Config

```ts
// vitest.config.ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    restoreMocks: true,          // restore vi.spyOn originals after each test (v4+: spies only)
    clearMocks: true,            // explicit for 4.x; default in 5.x
    unstubEnvs: true,            // undo vi.stubEnv
    unstubGlobals: true,         // undo vi.stubGlobal
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],       // required since 4.0 to report never-loaded files
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**"],
      thresholds: { lines: 90, branches: 85 },
    },
    projects: [
      { extends: true, test: { name: "unit", environment: "node", include: ["src/**/*.test.ts"],
          typecheck: { enabled: true, include: ["src/**/*.test-d.ts"] } } },
      { extends: true, test: { name: "dom", environment: "jsdom", include: ["src/**/*.test.tsx"],
          setupFiles: ["./src/test/setup-dom.ts"] } },
    ],
  },
});
```

- `environment: "node"` is the default; use `jsdom` (most complete) or `happy-dom` (faster, less complete)
  per project, never globally. `projects` replaced `workspace` (removed in 4.0).
- Keep `globals: false` and import `describe/it/expect/vi` explicitly; types and lint stay honest.
- Coverage: `@vitest/coverage-v8` (default, fast, accurate with AST remapping) or `coverage-istanbul`
  (instrumented; needed for some non-V8 runtimes). Thresholds fail `vitest run --coverage`.
- Run one project: `vitest run --project dom`; one file/test: `vitest run src/a.test.ts -t 'name'`.

## 2. Module mocking

| Need | Tool |
|---|---|
| replace a module for the whole file | `vi.mock("./db", () => ({ query: vi.fn() }))` (hoisted above imports) |
| share values with the hoisted factory | `const { rows } = vi.hoisted(() => ({ rows: [...] }))` |
| keep most of the real module | `vi.mock(import("./db"), async (importOriginal) => ({ ...(await importOriginal()), query: vi.fn() }))` (typed) |
| per-test variation | set behaviour on the mock: `vi.mocked(query).mockResolvedValueOnce([])` |
| mock only in one test | `vi.doMock` + dynamic `await import()` after it |
| spy on a method of an object you own | `vi.spyOn(service, "send")` |
| typed standalone mock | `const fetchUser = vi.fn<typeof realFetchUser>()` |

```ts
const { rows } = vi.hoisted(() => ({ rows: [{ id: 1 }, { id: 2 }] }));
vi.mock("./db.js", () => ({ query: vi.fn(async () => rows) }));
import { query } from "./db.js";
import { countUsers } from "./repo.js";

it("counts", async () => {
  await expect(countUsers()).resolves.toBe(2);
  expect(vi.mocked(query)).toHaveBeenCalledWith("select");
});
```

- The `vi.mock` path must resolve to the same file the code under test imports (aliases included:
  configure `resolve.alias` in Vitest too). A default export is mocked as `{ default: ... }`.
- `vi.spyOn(ns, "fn")` on an `import * as ns` of an externalized package (node_modules) throws
  "Cannot spy on export ... Module namespace is not configurable in ESM"; it works on your own
  transformed source, but never intercepts calls made inside the same module. Use `vi.mock` instead.
- Prefer dependency injection (`createService({ clock, http, repo })`) over module mocks: no hoisting,
  no path coupling, and the test documents the collaborators.

## 3. Timers and time

```ts
afterEach(() => { vi.useRealTimers(); });

it("polls every 30 s", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
  const fn = vi.fn<() => Promise<void>>(async () => {});
  const stop = poll(fn, 30_000);
  await vi.advanceTimersByTimeAsync(90_000);     // async variant flushes promise callbacks between timers
  expect(fn).toHaveBeenCalledTimes(3);
  expect(new Date().toISOString()).toBe("2026-01-01T00:01:30.000Z");
  stop();
});
```

- `advanceTimersByTimeAsync`/`runAllTimersAsync`/`runOnlyPendingTimersAsync` for timer -> promise -> timer
  chains; the sync versions skip the awaited parts.
- `vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "Date"] })` fakes a subset; `nextTick` and
  `queueMicrotask` are not faked by default.
- `shouldAdvanceTime: true` lets the fake clock follow real time: needed with Testing Library `waitFor`/
  `findBy*`, which only auto-advance Jest's fake timers, not Vitest's.
- Time zones: set `TZ=UTC` in the test script (`"test": "TZ=UTC vitest"`) or `process.env.TZ` in a
  global setup file before any `Date` is created.

## 4. HTTP with MSW

```ts
// src/test/server.ts
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
export const API = "https://api.example.test";
export const handlers = {
  success: http.get(`${API}/orders`, () => HttpResponse.json([{ id: "ord_1", customer: "Ada", total: 4200, status: "open" }])),
  empty: http.get(`${API}/orders`, () => HttpResponse.json([])),
  failure: http.get(`${API}/orders`, () => new HttpResponse(null, { status: 500 })),
};
export const server = setupServer(handlers.success);

// setup file
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));   // MSW 2.x: onUnhandledRequest: "error"
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// in a test: override for this test only (resetHandlers removes it)
server.use(handlers.failure);
server.use(http.get(`${API}/orders`, () => HttpResponse.json([]), { once: true }));
```

- Unhandled requests must fail the test (`"error"`), or a typo in a URL silently hits the network.
- Use absolute URLs in code under test (configurable base URL); Node's `fetch` rejects relative URLs
  even under jsdom.
- MSW 3 vs 2: ESM-only, Node 22+ and TS 5.9+; option renamed to `onUnhandledFrame`; no longer patches
  `setTimeout` for fake timers (advance them normally); cookies are not managed in Node and
  `request.headers.get("cookie")` is `null` (use the `cookies` resolver argument); GraphQL moved to
  `msw/graphql`; `worker.stop()` returns a Promise.
- Reuse the same handler modules in browser tests (`setupWorker` from `msw/browser`) and Storybook.

## 5. Components and the DOM

Query priority (Testing Library), best first: `getByRole(role, { name })`, `getByLabelText`,
`getByPlaceholderText`, `getByText`, `getByDisplayValue`, `getByAltText`/`getByTitle`, and `getByTestId`
only as a last resort.

| Query | Use when |
|---|---|
| `getBy*` | element must exist now (throws otherwise) |
| `queryBy*` | asserting absence: `expect(screen.queryByRole("alert")).not.toBeInTheDocument()` |
| `findBy*` | element appears asynchronously (polls, default 1000 ms) |
| `within(el).getBy*` | scope to a row, dialog or region |

```ts
const user = userEvent.setup();                // per test, before render
render(<LoginForm />);
await user.type(screen.getByLabelText("Email"), "ada@example.com");
await user.click(screen.getByRole("button", { name: "Sign in" }));
expect(await screen.findByRole("alert")).toHaveTextContent("Wrong password");
```

- Always `await` user-event calls; `fireEvent` skips focus, pointer and keyboard semantics.
- jest-dom matchers: `import "@testing-library/jest-dom/vitest"` in the setup file (jest-dom 7 needs
  `@testing-library/dom` installed and Node 22+).
- Browser mode (stable since Vitest 4.0) when jsdom lacks layout, `IntersectionObserver`/`ResizeObserver`,
  real focus, CSS or canvas:

```ts
import { playwright } from "@vitest/browser-playwright";
// project entry:
{ extends: true, test: { name: "browser", include: ["src/**/*.browser.test.tsx"],
    browser: { enabled: true, provider: playwright(), headless: true, instances: [{ browser: "chromium" }] } } }
// test: import { render } from "vitest-browser-react";
//   const screen = await render(<Menu />);
//   await screen.getByRole("button", { name: "Open" }).click();
//   await expect.element(screen.getByRole("menu")).toBeVisible();
```

- Accessibility smoke check in jsdom with axe-core (disable `color-contrast`; jsdom has no layout or canvas):
  `const { violations } = await axe.run(container, { rules: { "color-contrast": { enabled: false } } }); expect(violations).toEqual([]);`

## 6. Async assertions

| Pattern | Why |
|---|---|
| `await expect(p).rejects.toThrow(/timeout/)` | without `await` the assertion runs after the test ended (5.x fails the test; 4.x could pass vacuously) |
| `expect.assertions(2)` | proves callbacks or catch branches actually ran |
| `await vi.waitFor(() => expect(calls).toBe(2), { timeout: 2000 })` | retry an assertion until it passes |
| `await expect.poll(() => store.size).toBe(3)` | poll a value; 5.x rejects on timeout and passes an `AbortSignal` to the callback |
| unhandled rejections | fail the run; fix the source, do not add `dangerouslyIgnoreUnhandledErrors` |

## 7. Type tests

```ts
// src/orders/useOrders.test-d.ts
import { expectTypeOf, test } from "vitest";
test("hook types", () => {
  expectTypeOf(useOrders).parameters.toEqualTypeOf<[]>();
  expectTypeOf(useOrders).returns.toHaveProperty("data").toEqualTypeOf<Order[] | undefined>();
  expectTypeOf(toUserId).parameter(0).toEqualTypeOf<string>();
  expectTypeOf(toUserId).returns.toEqualTypeOf<UserId>();
});
```

Run with `vitest --typecheck` or, inside `projects`, `typecheck: { enabled: true, include: [...] }` on a
project (as in section 1). `toMatchTypeOf` is deprecated: use `toExtend` (assignability) or
`toMatchObjectType` (object subset). `expectTypeOf` in normal `.test.ts` files is also checked by `tsc`.

## 8. Snapshots

- `toMatchInlineSnapshot()` for small outputs (diffs reviewed in the test file).
- File snapshots only for stable serialized data (generated SQL, CLI output, AST dumps).
- `vitest -u` rewrites snapshots: review every changed line in the diff, as if it were a new assertion.
- Strip volatile fields with a serializer: `expect.addSnapshotSerializer({ test: v => v instanceof Date, serialize: () => '"<date>"' })`.
- Visual regression (`toMatchScreenshot`) only in browser mode with pinned fonts, viewport and browser
  version; never in jsdom.

## 9. Speed and CI

| Lever | Setting | Notes |
|---|---|---|
| no watch | `vitest run` | CI default (`CI=true` also disables watch) |
| pool | `pool: "forks"` (default) / `"threads"` | threads faster for large suites; forks for native addons, `process.chdir`, segfault isolation |
| isolation | `isolate: false` | only for pure tests with no module-level state; big win on many small files |
| workers | `maxWorkers: "50%"` | v4+ replaced `maxThreads`/`maxForks`/`poolOptions` |
| sharding | `vitest run --shard=1/4 --reporter=blob` per job, then `vitest run --merge-reports` | merge job restores the blob directory |
| changed only | `vitest --changed origin/main` | local loops, pre-push |
| order dependence | `vitest run --sequence.shuffle` | run nightly; fix any failure as a real bug |

Profile slow suites with the duration breakdown Vitest prints (`environment`, `import`, `setup`,
`transform`, `tests`): a large `environment` share means jsdom where `node` would do; a large `import`
share means barrel files or heavy modules loaded by every test. Full CI workflow:
[ci-sharding](references/ci-sharding.md).

## 10. Alternatives and migration

- `node --test` (zero dependencies, good for small libraries):

```ts
import { test, mock } from "node:test";
import assert from "node:assert/strict";
test("debounce fires once", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  const fn = mock.fn();
  const d = debounce(fn, 100); d(); d();
  mock.timers.tick(100);
  assert.equal(fn.mock.callCount(), 1);
  mock.timers.reset();
});
```

  Runs `.ts` directly on Node 22.18+ (type stripping); `--test-shard=1/4`, `--experimental-test-coverage`.
- `bun test` in Bun projects: Jest-compatible `expect`, `mock`, `spyOn`; check APIs you rely on.
- Jest -> Vitest: `jest.fn`/`jest.spyOn`/`jest.mock` -> `vi.*`; `jest.requireActual` -> `await vi.importActual`;
  factories may not reference outer variables except via `vi.hoisted`; `done` callbacks -> promises;
  `moduleNameMapper` -> `resolve.alias`. Full map: [jest-migration](references/jest-migration.md).

## 11. Pitfalls

- Mocks leaking between tests: missing `restoreMocks`/`clearMocks`, module-level state in mocked modules,
  `mockImplementation` set in `beforeAll`. 5.x clears call history by default; implementations persist.
- `vi.mock` path not matching how the code imports (alias vs relative path, `.js` vs no extension).
- Fake timers blocking real I/O: awaiting a real socket or DB call while `setTimeout` is faked hangs
  until the test timeout; fake only `toFake` subsets or use `shouldAdvanceTime`.
- Testing implementation details: component state, hook internals, CSS class names, call counts of
  private helpers. Assert what a user or caller observes.
- Snapshot-everything tests that get `-u`'d without review.
- jsdom gaps masquerading as passes: no layout (`getBoundingClientRect` is all zeros), no
  `IntersectionObserver`, `<dialog>` and focus partially emulated; use browser mode for those.
- A new `QueryClient` per test with `retry: false`, or a 500 test waits through 3 retries with backoff.
- Environment variables set in one test and read at module load in another: stub before import with
  `vi.stubEnv` + `vi.resetModules()`.

## 12. Worked example: `useOrders` + `OrdersTable`

Code: `fetchOrders(signal)` validates `/orders` JSON with zod; `useOrders()` wraps it in TanStack Query
with `refetchInterval: 30_000`; `OrdersTable` renders loading (`role="status"`), error (`role="alert"`),
empty and table states. Handlers and setup are those in section 4.

```tsx
function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

it("renders one row per order", async () => {
  const { container } = renderWithClient(<OrdersTable />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading orders");
  const table = await screen.findByRole("table", { name: "Orders" });
  expect(within(table).getAllByRole("row")).toHaveLength(2);          // header + 1 order
  const { violations } = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  expect(violations).toEqual([]);
});

it("shows an alert on HTTP 500", async () => {
  server.use(handlers.failure);
  renderWithClient(<OrdersTable />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load orders");
});

it("polls every 30 s", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });                       // findBy* keeps working
  let calls = 0;
  server.use(http.get(`${API}/orders`, () => { calls++; return HttpResponse.json([]); }));
  renderWithClient(<OrdersTable />);
  await screen.findByText("No orders yet");
  expect(calls).toBe(1);
  await vi.advanceTimersByTimeAsync(30_000);
  await vi.waitFor(() => expect(calls).toBe(2));
  await vi.advanceTimersByTimeAsync(60_000);
  await vi.waitFor(() => expect(calls).toBe(4));
});
```

Plus an empty-state test (`server.use(handlers.empty)`) and the `.test-d.ts` from section 7.
This exact set passes on Vitest 5.0.5 + MSW 3 + React 19 + jsdom (5 tests + 1 type test, 0.7 s).

Scenario figures (illustrative) after rolling the pattern out to a 312-test suite:
- branch coverage 71% -> 92% (the error and empty branches had no tests); threshold set to 90.
- duration 41 s -> 9 s: `environment: "node"` for the 60% of files that never touched the DOM,
  `pool: "threads"`, `isolate: false` for the pure `unit` project, and `--shard=i/4` with blob merge in CI.
- `--sequence.shuffle` nightly found one order-dependent test (a module-level cache) which was fixed,
  not skipped.

Related: `typescript-strict-types`, `typescript-build-config`, `node-runtime-patterns`,
`react-typescript-components`, `testing-strategy`, `ci-pipelines`, hub `coding-general`.
