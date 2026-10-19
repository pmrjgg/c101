# TypeScript async and error patterns

Patterns and failure modes for promises, cancellation and errors in TypeScript on Node and in the
browser. Runtime-level depth (streams, HTTP servers, shutdown) lives in `node-runtime-patterns`.

## 1. Choosing the primitive

| Need | Shape |
|---|---|
| run steps in order | `for (const x of xs) { await step(x); }` |
| run N independent tasks, all must succeed | `await Promise.all(xs.map(f))` + shared `AbortController` |
| run N tasks, keep partial results | `Promise.allSettled` then split `fulfilled` / `rejected` |
| first to succeed wins | `Promise.any` (rejects with `AggregateError` when all fail) |
| first to settle wins (timeouts) | prefer `AbortSignal.timeout(ms)` over `Promise.race` with a timer |
| bounded concurrency | `p-limit` / `p-map` with `concurrency`, or a small worker loop over a shared iterator |
| cancel on caller abort or timeout | `AbortSignal.any([callerSignal, AbortSignal.timeout(ms)])` |
| process a large or unbounded sequence | async iterator `for await (const x of source)` with backpressure |
| CPU-heavy work | `worker_threads` (Node) / Web Worker; never a tight loop on the event loop |

## 2. Floating promises

The single most common async bug: a promise nobody awaits. Its rejection becomes an unhandled
rejection (Node default: crash with exit code 1) or vanishes in a browser.

| Code | Problem | Fix |
|---|---|---|
| `save(user);` | not awaited | `await save(user);` |
| `items.forEach(async (i) => await save(i));` | `forEach` ignores returned promises | `for...of` + `await`, or `await Promise.all(items.map(save))` |
| `button.onclick = async () => {...}` with a throw | rejection nobody handles | catch inside and report |
| `setTimeout(async () => {...})` | same | catch inside |
| `if (isReady()) ...` where `isReady` is async | a promise is always truthy | `if (await isReady())` (`no-misused-promises` catches it) |
| `return fetchUser(id)` inside `try` | rejection skips the local `catch` | `return await fetchUser(id)` inside `try` |
| fire-and-forget telemetry | deliberate | `void send(evt).catch(logError);` |

Lint configuration (typescript-eslint, type-aware):

```js
// eslint.config.js (flat config)
import tseslint from "typescript-eslint";
export default tseslint.config(
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    rules: {
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "@typescript-eslint/return-await": ["error", "in-try-catch"],
      "@typescript-eslint/only-throw-error": "error",
    },
  },
);
```

Biome-only repos: check the installed version's rule list for a floating-promise rule before relying
on it; if there is none, say so in the review instead of assuming coverage.

## 3. Cancellation

```ts
export async function fetchJson(url: string, opts: { signal?: AbortSignal; timeoutMs?: number } = {}): Promise<unknown> {
  const signals = [AbortSignal.timeout(opts.timeoutMs ?? 5_000)];
  if (opts.signal) signals.push(opts.signal);
  const res = await fetch(url, { signal: AbortSignal.any(signals) });
  if (!res.ok) throw new HttpError(res.status, url);
  return res.json() as Promise<unknown>;                  // validate at the caller's boundary
}
```

Rules:
- Accept `signal?: AbortSignal` in every function that does I/O or waits; pass it down to `fetch`,
  `fs/promises` calls that support it, `timers/promises` `setTimeout(ms, v, { signal })`, and child
  libraries.
- Aborted operations reject with a `DOMException` named `AbortError` (or `TimeoutError` for
  `AbortSignal.timeout`): check `e.name`, and do not log aborts as failures.
- In a loop, call `signal.throwIfAborted()` per iteration.
- `Promise.all` + shared controller: on the first rejection call `controller.abort()` so siblings stop.

## 4. Errors

```ts
export class HttpError extends Error {
  override readonly name = "HttpError";
  constructor(readonly status: number, readonly url: string, options?: ErrorOptions) {
    super(`GET ${url}: status ${status}`, options);
  }
}

try {
  await load();
} catch (e: unknown) {
  if (e instanceof HttpError && e.status === 404) return null;
  throw new Error("load profile", { cause: e });         // keep the chain
}
```

- `catch` variables are `unknown` under `strict` (`useUnknownInCatchVariables`); narrow first.
  Third-party code can throw strings or plain objects.
- Throw `Error` subclasses only (`only-throw-error`); never strings.
- Add context once per layer with `{ cause }`; log once at the top (request handler, CLI main), not
  at every layer.
- Expected failures that callers must branch on can be returned as a discriminated union
  `Result<T, E>` instead of thrown; do not mix both styles in one module.
- `instanceof` fails across realms and duplicated package copies; for library errors exposed to
  consumers, also set a stable `code` or `name` field and check that.

## 5. Bounded fan-out

```ts
import pLimit from "p-limit";

export async function fetchAll(urls: readonly string[], signal: AbortSignal): Promise<unknown[]> {
  const limit = pLimit(8);
  const controller = new AbortController();
  const both = AbortSignal.any([signal, controller.signal]);
  try {
    return await Promise.all(urls.map((u) => limit(() => fetchJson(u, { signal: both }))));
  } catch (e) {
    controller.abort();                                   // stop the rest on first failure
    throw e;
  }
}
```

## 6. Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| process exits `1` with "unhandled rejection" | floating promise | lint rule; await or `.catch` |
| requests pile up, memory grows | unbounded `Promise.all` over thousands of items | concurrency limit |
| work continues after the client disconnected | signal not propagated | pass `req.signal` / an `AbortController` tied to `close` |
| test passes although the code throws | `expect(p).rejects` not awaited | `await expect(p).rejects...` |
| stack trace ends at the event loop | lost context | `{ cause }` and named errors; `--enable-source-maps` for compiled code |
| `Promise.race` timeout leaves the loser running | race does not cancel | `AbortSignal.timeout` passed into the operation |
| event-loop lag spikes | synchronous CPU work, sync fs calls, large `JSON.parse` | workers, streaming parsers, async fs |
