# Node diagnostics command sheet

Flags verified with `node --help` on Node 24.22; check yours with `node --help | grep <flag>`.

## CPU

| Goal | Command | Output / next step |
|---|---|---|
| profile a run | `node --cpu-prof --cpu-prof-dir=./prof dist/main.js` | `.cpuprofile` at exit; open in Chrome DevTools (Performance -> Load profile) or speedscope |
| profile a live process | `node --inspect=127.0.0.1:9229 dist/main.js`, then chrome://inspect -> Profiler | never expose the inspector port publicly |
| flame graph from perf (Linux) | `node --perf-basic-prof dist/main.js` + `perf record -g -p <pid>` | see `performance-optimization` for perf usage |
| event-loop blocking | `monitorEventLoopDelay` percentiles (SKILL.md section 3) | p99 > 50-100 ms: profile under load |
| slow startup | `node --cpu-prof` on startup only; `NODE_DEBUG=module` sparingly | heavy top-level imports: lazy-load |

## Memory

| Goal | Command | Notes |
|---|---|---|
| snapshot on demand | `node --heapsnapshot-signal=SIGUSR2 dist/main.js`, then `kill -USR2 <pid>` | writes `Heap.*.heapsnapshot` in the cwd; process pauses while writing |
| snapshot from code | `import { writeHeapSnapshot } from "node:v8"; writeHeapSnapshot()` | guard behind an admin-only endpoint |
| snapshot before OOM | `node --heapsnapshot-near-heap-limit=2 dist/main.js` | captures up to 2 snapshots as the heap approaches its limit |
| allocation sampling | `node --heap-prof dist/main.js` | `.heapprofile` at exit; lower overhead than snapshots |
| heap limit | `--max-old-space-size=<MB>` or `--max-old-space-size-percentage=<n>` | size below the container limit |
| live numbers | `process.memoryUsage()` (`rss`, `heapUsed`, `external`, `arrayBuffers`) | `rss` >> `heapUsed`: native or Buffer memory, not JS objects |
| GC activity | `node --trace-gc dist/main.js` | frequent mark-compact with little freed: near the limit or leaking |

Comparison workflow in DevTools (Memory tab): load snapshots A (after warm-up), B and C (after equal load
rounds); select C, view "Comparison" against A; sort by `# Delta`; a constructor growing linearly with
load rounds is the leak; expand it and follow "Retainers" up to a GC root (a module-level Map, an
emitter listener array, a timer).

## Handles that keep the process alive

| Symptom | Command |
|---|---|
| process does not exit | `process.getActiveResourcesInfo()` logs resource types still alive (`Timeout`, `TCPSocketWrap`, `FSReqCallback`) |
| test runner hangs | Vitest `--reporter=hanging-process`; `node --test` `--test-force-exit` only as a stopgap |
| leaking listeners | run with `--trace-warnings` to get the stack for `MaxListenersExceededWarning` |

## Runtime warnings and errors

| Flag | Use |
|---|---|
| `--trace-warnings` | stack traces for process warnings |
| `--trace-uncaught` | stack of where an uncaught exception was thrown (for non-Error throws) |
| `--unhandled-rejections=strict` | treat every unhandled rejection as an uncaught exception (default `throw` already crashes unless a handler exists) |
| `--enable-source-maps` | map compiled JS frames to TS sources |
| `--disable-warning=ExperimentalWarning` | silence a known warning class instead of all warnings |
| `--stack-trace-limit=50` | deeper async stacks while debugging |

## Network

| Goal | Command |
|---|---|
| see HTTP client internals | `NODE_DEBUG=http,net node dist/main.js` (very verbose; never in production) |
| undici (fetch) diagnostics | subscribe to `node:diagnostics_channel` channels such as `undici:request:create` |
| DNS latency | time `dns.promises.lookup(host)`; `lookup` runs on the libuv thread pool (`UV_THREADPOOL_SIZE`, default 4) and can queue behind `fs`/`crypto`/`zlib` work |

## Reports

`node --report-on-signal --report-signal=SIGUSR1 dist/main.js` then `kill -USR1 <pid>` writes a JSON
diagnostic report (JS and native stacks, heap summary, libuv handles, environment). Redact environment
variables before sharing reports: they contain secrets.
