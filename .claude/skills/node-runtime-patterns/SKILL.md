---
name: node-runtime-patterns
description: "Production Node.js (and Bun) services and CLIs: LTS choice under the new annual release model, built-ins that replace dependencies, event-loop health and worker-thread offloading, AbortSignal cancellation, stream pipelines with backpressure, HTTP server timeouts and graceful shutdown, heap-snapshot leak diagnosis, safe child processes, config validation and packaging. Load when building, reviewing or debugging Node/Bun runtime code."
when_to_use: "Node services or CLIs (.ts/.js/.mjs) stalling, leaking or timing out; sporadic 502s behind a load balancer; SIGTERM handling in containers; MaxListenersExceededWarning, ERR_HTTP_HEADERS_SENT, heap out of memory, unhandled rejections; choosing a Node version; replacing dependencies with built-ins; streaming large uploads or files."
---

# Node runtime patterns

Baseline (October 2026): Node 24.x (Krypton, maintenance from 20 Oct 2026) and Node 26.x (Active LTS
from 28 Oct 2026); examples verified on Node 24.22. TypeScript setup: `typescript-build-config`; retries,
circuit breakers and concurrency limits: `resilience-patterns`; profiling method: `performance-optimization`.

Deep material: [graceful shutdown module](references/graceful-shutdown.md) |
[diagnostics commands](references/diagnostics-commands.md)

## 1. Versions

| Line | Status Oct 2026 | End of life |
|---|---|---|
| Node 20 | EOL (30 Apr 2026): upgrade now | passed |
| Node 22 (Jod) | maintenance | 30 Apr 2027 |
| Node 24 (Krypton) | maintenance from 20 Oct 2026 | 30 Apr 2028 |
| Node 26 | Active LTS from 28 Oct 2026; last line under the old odd/even model | 30 Apr 2029 |
| Node 27+ | one major per year: Alpha (Oct-Mar), Current (Apr-Oct), then LTS; 27 alpha from 28 Oct 2026, 27.0 in Apr 2027 | 36 months after Current |

- Production runs LTS only. Pin with `engines.node`, `.nvmrc`/`mise.toml`, and the container base tag
  (`node:24-slim`, never `node:latest`). CI tests the current LTS plus the next one (24 and 26 now).
- Libraries: add the Node 27 Alpha channel to CI early to catch breakage before it ships.
- Bun or Deno: only after checking every dependency you rely on for Node-API compatibility (native
  addons, `node:` modules, `worker_threads`, `http2`); run the full test suite on them in CI.

## 2. Built-ins first

| Need | Built-in | Replaces |
|---|---|---|
| HTTP client | global `fetch` (undici); tune pools with `undici`'s `Agent` + its own `fetch` | axios, node-fetch |
| test runner | `node:test`, `node:assert/strict`, `mock.fn`, `mock.timers` | jest/mocha for small libs |
| `.env` files | `node --env-file=.env` / `--env-file-if-exists`, `process.loadEnvFile()` | dotenv |
| dev reload | `node --watch src/main.ts` | nodemon |
| CLI args | `util.parseArgs({ options: { port: { type: "string", short: "p" } } })` | yargs/commander for simple CLIs |
| colours | `util.styleText(["bold", "red"], "x")` (respects `NO_COLOR`/TTY) | chalk |
| globbing | `fs.promises.glob("src/**/*.ts")` | glob, fast-glob |
| embedded SQL | `node:sqlite` `DatabaseSync` | better-sqlite3 for simple cases |
| deep copy / ids | `structuredClone`, `crypto.randomUUID()` | lodash.clonedeep, uuid |
| run TS | type stripping (22.18+/23.6+) | ts-node |
| run package scripts | `node --run build` | `npm run` (faster startup, no lifecycle hooks) |
| restrict a script's capabilities | `node --permission --allow-fs-read=./data` (fs writes, child processes, workers, addons need `--allow-*` flags; network via `--allow-net` from Node 25; denied calls throw ERR_ACCESS_DENIED; a seat belt for trusted code, not a sandbox for malicious code) | ad-hoc checks |

undici defaults `headersTimeout` and `bodyTimeout` to 300 s: always pass an `AbortSignal.timeout(ms)` on
service-to-service calls. Use `undici`'s `Agent` with `undici`'s `fetch` (same package version) rather
than mixing an npm `undici` Agent into the bundled global `fetch` (`process.versions.undici` shows the
bundled version).

## 3. Event-loop health

One thread runs every request's JavaScript. Anything that holds it delays all requests.

| Blocker | Typical cost | Fix |
|---|---|---|
| `zlib.*Sync`, `crypto.pbkdf2Sync`/`scryptSync`, `fs.*Sync` in handlers | ms to seconds | async versions (run on the libuv pool) |
| `JSON.parse`/`JSON.stringify` of large payloads | ~2-5 ms per MB on a fast core (50 MB > 100 ms) | stream-parse, paginate, or move to a worker |
| catastrophic-backtracking regex on user input | unbounded | linear patterns, input length caps (`regex-engineering`) |
| CPU-heavy loops (validation, image, PDF) | unbounded | `worker_threads` via `piscina` |
| recursive `process.nextTick` / long microtask chains | starves I/O completely | `setImmediate` between chunks |

Measure before and after:

```ts
import { monitorEventLoopDelay, performance } from "node:perf_hooks";
const eld = monitorEventLoopDelay({ resolution: 20 });
eld.enable();
let elu = performance.eventLoopUtilization();
setInterval(() => {
  const now = performance.eventLoopUtilization(elu); elu = performance.eventLoopUtilization();
  log.info({ p50_ms: eld.percentile(50) / 1e6, p99_ms: eld.percentile(99) / 1e6, max_ms: eld.max / 1e6,
             utilization: now.utilization }, "event-loop");
  eld.reset();
}, 10_000).unref();
```

Thresholds: p99 delay above ~50-100 ms or utilization above ~0.9 sustained means requests queue behind
JavaScript; investigate with a CPU profile (`node --cpu-prof`, see the diagnostics reference).

Offload CPU work:

```ts
import { Piscina } from "piscina";
const pool = new Piscina({ filename: new URL("./validate.worker.ts", import.meta.url).href, maxQueue: "auto" });
const result = await pool.run(rows, { signal });   // worker module: export default function (rows) {...}
```

Arguments and results are structured-cloned: pass batches (hundreds of rows), not single items; transfer
`ArrayBuffer`s instead of copying large binary data. For a long synchronous loop you cannot move, yield
every N iterations with `await new Promise(r => setImmediate(r))`.

## 4. Cancellation and timeouts

Every outbound operation gets a deadline, and request work stops when the client goes away.

```ts
function requestSignal(res: ServerResponse, ms: number): AbortSignal {
  const ac = new AbortController();
  res.once("close", () => { if (!res.writableFinished) ac.abort(new Error("client disconnected")); });
  return AbortSignal.any([ac.signal, AbortSignal.timeout(ms)]);
}
const signal = requestSignal(res, 10_000);
const r = await fetch(url, { signal });                           // rejects with signal.reason
await setTimeout(500, undefined, { signal });                     // node:timers/promises
await pipeline(src, transform, dest, { signal });                 // node:stream/promises
execFile("convert", args, { signal, timeout: 30_000 }, cb);       // node:child_process
```

- Node 24.16+ also exposes `req.signal` on `IncomingMessage` (aborts when the client disconnects; before
  24.20 it also aborted after a normal finish). Fetch-style frameworks (Hono, route handlers) pass
  `request.signal`.
- Operations reject with `signal.reason`: a `TimeoutError` DOMException from `AbortSignal.timeout`, an
  `AbortError` from `abort()` without a reason, or the reason you passed (`abort(new Error(...))`); map
  them to 504 / 499-style logs explicitly.
- Listeners added to long-lived signals leak: use `{ once: true }` and remove them in `finally`;
  `signal.throwIfAborted()` at loop boundaries.
- DB clients: pass the signal if supported, otherwise set a statement timeout server-side
  (`statement_timeout` in Postgres) shorter than the request deadline.

## 5. Async error handling

- Keep Node's default `--unhandled-rejections=throw`. Add `process.on("unhandledRejection")` only to log
  with context and then exit non-zero; never to swallow.
- Every promise is awaited, returned or explicitly `void`ed with a `.catch` (lint: `no-floating-promises`).
- `Promise.allSettled` when partial results are acceptable; `Promise.all` when one failure must cancel the
  batch (pass a shared `AbortController` so the rest stop).
- `Promise.all(items.map(fetchOne))` over 10,000 items opens 10,000 sockets: bound concurrency with
  `p-limit` (`const limit = pLimit(16); await Promise.all(items.map(i => limit(() => fetchOne(i))))`),
  plus retries with jitter from `resilience-patterns`.
- `EventEmitter` handlers that are `async` turn throws into unhandled rejections; create emitters with
  `{ captureRejections: true }` so rejections route to `'error'`, or catch inside the handler.

## 6. Streams

```ts
import { pipeline } from "node:stream/promises";
import { createGunzip } from "node:zlib";
import { createReadStream, createWriteStream } from "node:fs";
await pipeline(createReadStream("in.csv.gz"), createGunzip(), transformRows, createWriteStream("out.ndjson"), { signal });
```

- `pipeline` propagates errors and destroys every stage; `.pipe()` does neither.
- Backpressure: a `Writable`'s `write(chunk, enc, cb)` must call `cb` only when the chunk is handled
  (after the DB insert), so upstream pauses instead of buffering. `objectMode` `highWaterMark` counts objects.
- Consume readables with `for await (const chunk of readable)`; it respects backpressure.
- Web streams interop: `Readable.fromWeb(res.body)` for `fetch` bodies, `Readable.toWeb(nodeStream)` for
  `Response` bodies.
- Never `Buffer.concat` an unbounded request body; cap size (`Content-Length` check plus a counting
  transform) and stream.

## 7. HTTP servers

| Setting | Default (Node 24) | Set to | Why |
|---|---|---|---|
| `server.keepAliveTimeout` | 5 s | above the LB idle timeout: LB 60 s -> 65 s | if Node closes an idle socket first, the LB reuses a dead socket -> sporadic 502 |
| `server.headersTimeout` | 60 s | slightly above `keepAliveTimeout` (66 s) | slowloris protection without cutting keep-alive |
| `server.requestTimeout` | 300 s | longest legitimate upload; >= `headersTimeout` | whole-request cap |
| per-request deadline | none | `AbortSignal.timeout` per route | work stops, not just the socket |

Graceful shutdown on SIGTERM (Kubernetes default grace period 30 s):

1. Mark not-ready (`/readyz` returns 503) and keep serving.
2. Wait for endpoints to update (5-10 s) so the LB stops sending new requests.
3. `server.close()`: stops accepting; since Node 19 it also closes idle keep-alive sockets.
4. Let in-flight requests finish until a deadline, then `server.closeAllConnections()`.
5. Close worker pools, DB pools, queue consumers; flush logs; `process.exit(0)`.

The full module with tests: [graceful-shutdown](references/graceful-shutdown.md). Run Node as PID 1
correctly: `CMD ["node", "dist/main.js"]` (exec form) or `tini`; `npm start` as PID 1 may not forward
SIGTERM. Framework choice (Fastify, Hono, Express 5) is secondary to these settings; each exposes the
same timeouts under its own option names.

## 8. Memory

- Container sizing: `--max-old-space-size` (MB) at roughly 75% of the container memory limit, leaving
  room for buffers, native memory and worker heaps. Node 24 also accepts
  `--max-old-space-size-percentage=75` (percentage of available system memory; confirm it sees the
  container limit on your platform).
- Leak workflow: start with `--heapsnapshot-signal=SIGUSR2`, take snapshot A after warm-up, run load, take
  B and C, compare in Chrome DevTools (Memory -> Comparison): sort by `# Delta` and `Retained Size`,
  follow retainers of the growing constructor. A snapshot pauses the process and needs about as much free
  memory as the heap; take it on a drained instance.
- Usual culprits: listeners added per request to long-lived emitters (signals, sockets, `process`), closures
  in unbounded `Map` caches, timers never cleared, promise chains held by retry loops.
  `MaxListenersExceededWarning` (more than 10 listeners for one event) is a leak signal, not noise.
- Caches are bounded: `lru-cache` with `max` and `ttl`, or `WeakMap` keyed by objects you do not own.
- Sampling: `node --heap-prof` writes `.heapprofile` at exit for allocation hot spots.

## 9. Child processes and security

- `execFile`/`spawn` with an argument array and `shell: false` (the default); never `exec` with
  interpolated strings. Always `timeout`, `signal`, and `maxBuffer` (or stream stdout).
- No `eval`, `new Function`, or `vm` as a security boundary.
- Prototype pollution: validate parsed JSON with a schema; use `Map` or `Object.create(null)` for
  dictionaries keyed by user input; reject `__proto__`/`constructor` keys in merge utilities;
  `--disable-proto=delete` hardens further.
- Supply chain: install with lifecycle scripts blocked by default (`pnpm` 11+ `strictDepBuilds`,
  `npm ci --ignore-scripts` plus an allowlist), lockfile committed, `npm audit signatures` in CI.
  Depth: `security-review`.

## 10. Config and packaging

```ts
import * as z from "zod";
const Env = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  PORT: z.coerce.number().int().min(1).max(65535).default(8080),
  DATABASE_URL: z.url(),
  SHUTDOWN_DRAIN_MS: z.coerce.number().int().default(5_000),
});
export const config = Env.parse(process.env);   // crash at boot with every missing variable listed
```

- Twelve-factor: config from environment, validated once at startup, exported as a typed object.
- `NODE_ENV=production` changes framework behaviour (Express caching, React builds); Node itself ignores it.
- ESM by default (`"type": "module"`); `node --enable-source-maps dist/main.js` when running compiled TS.
- Distributable CLIs: single executable applications (Node 24: `--experimental-sea-config` + `postject`;
  Node 25.5+: `node --build-sea sea-config.json`) or `bun build --compile ./src/cli.ts --outfile mycli`.

## 11. Pitfalls

- `array.forEach(async x => ...)` does not wait and loses rejections: `for...of` with `await`, or
  `Promise.all` with a limit.
- `res.end()` or `res.writeHead()` after headers were sent: ERR_HTTP_HEADERS_SENT; return after
  responding, check `res.headersSent` in error handlers.
- `console.log` in hot paths: string formatting costs CPU, writes to files and TTYs are synchronous on
  POSIX, and writes to pipes buffer without limit; use an async structured logger (pino).
- Intervals and sockets keeping the process alive after `main` ends: `.unref()` housekeeping timers.
- Duplicate module singletons (two copies of a package, or ESM and CJS builds both loaded): module-level
  caches and `instanceof` checks split silently.
- `new Date("2026-03-01")` is UTC, `new Date("2026-03-01T00:00")` is local time: set `TZ=UTC` in
  containers and store instants as ISO strings with offsets.
- `setTimeout` delays above 2^31-1 ms (~24.8 days) fire immediately.

## 12. Worked example: CSV import service stalling under load

Symptom: `/import` accepts gzipped CSV uploads (up to 300 MB). Under load every endpoint's p99 rose to
2.4 s and the ALB logged sporadic 502s. Event-loop p99 delay was 1.8 s.

Diagnosis:
1. `node --cpu-prof` during a load test: 61% of samples in `zlib.gunzipSync`, `JSON.parse` of a per-row
   metadata column and zod validation, all on the main thread.
2. Heap peaked at 2.1 GB: the handler buffered the whole body (`Buffer.concat`) and the full parsed array.
3. 502s matched the default `keepAliveTimeout` (5 s) being below the ALB idle timeout (60 s).

Fix (complete code checked with `tsc` and run on Node 24.22 under type stripping):

```ts
const BATCH = 500;
const pool = new Piscina({ filename: new URL("./validate-rows.worker.ts", import.meta.url).href });

async function importCsv(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const signal = requestSignal(res, 120_000);
  let batch: Record<string, string>[] = [];
  let inserted = 0, rejected = 0;
  const flush = async () => {
    if (batch.length === 0) return;
    const rows = batch; batch = [];
    const out: { valid: ValidRow[]; rejected: number } = await pool.run(rows, { signal });
    rejected += out.rejected;
    inserted += await db.insertMany(out.valid, signal);
  };
  const sink = new Writable({
    objectMode: true, highWaterMark: BATCH,
    write(row: Record<string, string>, _enc, cb) {
      batch.push(row);
      if (batch.length < BATCH) return cb();
      flush().then(() => cb(), cb);                 // callback after the insert: backpressure
    },
    final(cb) { flush().then(() => cb(), cb); },
  });
  await pipeline(req, createGunzip(), parse({ columns: true, skip_empty_lines: true }), sink, { signal });
  res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ inserted, rejected }));
}

server.keepAliveTimeout = 65_000;   // ALB idle 60 s
server.headersTimeout = 66_000;
server.requestTimeout = 300_000;
```

`parse` is from `csv-parse`; the worker's default export validates a batch with zod and returns
`{ valid, rejected }`. SIGTERM handling follows section 7.

Results:
- Local reproduction, 400k rows (gzip): synchronous version blocked the loop for 413 ms per upload; the
  pipeline version kept event-loop max at 21 ms (100k-row file: 99,900 inserted, 100 rejected, 0.66 s).
- Scenario production figures (illustrative): event-loop p99 1.8 s -> 35 ms, endpoint p99 2.4 s -> 120 ms, heap peak
  2.1 GB -> 180 MB, zero 502s over 14 days; uploads cancelled by clients now stop inserting within one batch.

Related: `typescript-build-config`, `typescript-strict-types`, `typescript-testing-vitest`,
`resilience-patterns`, `observability-instrumentation`, `performance-optimization`, `security-review`,
hub `coding-general`.
