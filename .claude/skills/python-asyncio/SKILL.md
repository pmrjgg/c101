---
name: python-asyncio
description: "Correct and fast asyncio: async vs threads vs processes (including free-threaded builds), structured concurrency with TaskGroup and asyncio.timeout, cancellation semantics, bounded concurrency with semaphores and worker queues, offloading blocking calls, task lifetime, sync/async bridges, anyio/trio, testing with pytest-asyncio 1.x, debugging hangs and slow callbacks. Load when writing, reviewing or debugging async Python."
when_to_use: "async def/await code, asyncio, anyio, httpx.AsyncClient, asyncpg; messages like 'coroutine ... was never awaited', 'Task was destroyed but it is pending', 'Executing <Task ...> took 0.188 seconds', 'asyncio.run() cannot be called from a running event loop', an ExceptionGroup from a TaskGroup; tasks: fan out I/O, add timeouts or cancellation, fix a hang, test async code."
---

# Python asyncio

Baseline: Python 3.12+ (`Queue.shutdown` needs 3.13, `python -m asyncio ps` and
`asyncio.print_call_graph` need 3.14), pytest-asyncio 1.x, anyio 4.x, httpx 0.28. Neighbours: retry,
backoff, circuit breakers and Little's law are `resilience-patterns`; CPU profiling is
`python-performance-profiling`; root-cause method is `debugging-method`; general test design is
`pytest-patterns`.

Deep material: [worked example, full code and lab harness](references/fetch-all-example.md) |
[async testing recipes](references/async-testing.md)

## 1. Concurrency model

| Workload | Use | Why | Watch out |
|---|---|---|---|
| many I/O-bound connections (HTTP, DB, sockets) | asyncio | one thread; a pending task costs about 1 KB (20k tasks = 20 MB, measured) | every call on the path must be async or offloaded |
| blocking library without async API (SDKs, sync drivers) | threads: `await asyncio.to_thread(fn, *args)` | blocking I/O releases the GIL | default pool = `min(32, process_cpu_count() + 4)` workers |
| CPU-bound pure Python | `ProcessPoolExecutor` via `loop.run_in_executor`, or threads on a free-threaded build | GIL serialises Python bytecode | pickling cost; spawn start-up |
| CPU-bound in C (numpy, zlib, hashlib) | threads | these release the GIL | |
| free-threaded build (3.14t, officially supported since 3.14) | threads for CPU-bound Python | no GIL | 1-8% single-thread overhead (pyperformance); importing a C extension not marked free-threading-safe re-enables the GIL with a warning: check `sys._is_gil_enabled()` after imports |

Mixing is normal: an asyncio front end, `to_thread` for a blocking SDK, a process pool for a CPU
step. Never run CPU work over ~10 ms directly in a coroutine: it stalls every other task.

## 2. Structured concurrency

```python
async def load_dashboard(user_id: int) -> Dashboard:
    async with asyncio.timeout(5):                    # one deadline for the whole block
        async with asyncio.TaskGroup() as tg:         # 3.11+
            profile = tg.create_task(get_profile(user_id))
            orders = tg.create_task(get_orders(user_id))
    return Dashboard(profile.result(), orders.result())

try:
    dash = await load_dashboard(42)
except* httpx.HTTPStatusError as eg:                  # TaskGroup raises ExceptionGroup
    for exc in eg.exceptions:
        log.warning("upstream %s", exc.response.status_code)
except* TimeoutError:
    dash = Dashboard.cached(42)
```

| API | On first failure | Use for |
|---|---|---|
| `TaskGroup` | cancels siblings, waits for them, raises `ExceptionGroup` | default: all subtasks must succeed |
| `gather(*aws)` | propagates the first exception, **others keep running** unobserved | avoid in new code |
| `gather(*aws, return_exceptions=True)` | returns results and exceptions in order | partial results are intended |
| `asyncio.wait(tasks, return_when=FIRST_COMPLETED)` | nothing cancelled; you decide | races, hedged requests (cancel the losers) |
| `asyncio.as_completed(aws)` | results as they finish | progress reporting |

`asyncio.timeout(delay)` (3.11) raises the builtin `TimeoutError` at block exit and composes with
nesting; use it instead of `wait_for` for multi-step operations. `asyncio.timeout_at(loop.time() + n)`
for absolute deadlines; `cm.reschedule(...)` to extend one.

## 3. Bounded concurrency

```python
sem = asyncio.Semaphore(64)
async def fetch(url: str) -> bytes:
    async with sem:                                   # released on success, error and cancellation
        r = await client.get(url)
    return r.content
```

Worker pool with backpressure (bounded memory however many items arrive):

```python
async def run_pool(items: Iterable[str], n: int = 32) -> None:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=2 * n)   # producer blocks when workers lag
    async def worker() -> None:
        while True:
            try:
                item = await q.get()
            except asyncio.QueueShutDown:             # 3.13: raised once the queue is shut and empty
                return
            try:
                await process(item)
            finally:
                q.task_done()
    async with asyncio.TaskGroup() as tg:
        for _ in range(n):
            tg.create_task(worker())
        for item in items:
            await q.put(item)
        q.shutdown()                                  # workers drain the rest, then exit
```

Before 3.13 put one sentinel per worker. `shutdown(immediate=True)` drops queued items and wakes
`join()`.

Sizing (`resilience-patterns` has the derivation): Little's law `L = lambda * W`. Target 500 req/s at
120 ms mean latency needs `L = 500 * 0.12 = 60` in flight, so `Semaphore(64)`. Then measure: sweep 16,
32, 64 and stop where throughput stops rising or p99 latency jumps; the origin's rate limit caps
`lambda` whatever `L` is. Do not create one task per item beyond roughly 100k items: 100k pending tasks
cost about 93 MB and 0.15 s of loop time just to create (measured, 3.14); use the worker pool.

## 4. Cancellation rules

- `CancelledError` subclasses `BaseException`, so `except Exception` does not catch it. Bare `except:`
  and `except BaseException` do: re-raise it. Swallowing it breaks `asyncio.timeout`, TaskGroup and
  shutdown (the cancelled task keeps running).
- Cancellation arrives at the next `await`. A coroutine that loops on CPU without awaiting cannot be
  cancelled or timed out.
- Clean up in `finally` / `async with`. Cleanup that awaits must be short and bounded.
- Must-complete writes (ledger entry, ack) survive caller cancellation with `shield`, bounded by their
  own timeout, and the cancellation is still propagated:

```python
async def record(entry: Entry) -> None:
    write = asyncio.create_task(db.insert(entry))     # owns the must-complete work
    try:
        await asyncio.shield(write)
    except asyncio.CancelledError:
        try:
            async with asyncio.timeout(5):            # never hang shutdown
                await write
        except TimeoutError:
            write.cancel()
            log.error("ledger write abandoned: %s", entry.id)
        raise                                         # still cancelled
```

- `asyncio.run` (3.11+) turns the first Ctrl-C into cancellation of `main()`, runs its cleanup, then
  raises `KeyboardInterrupt`: correct cancellation handling gives clean SIGINT shutdown for free.

## 5. Blocking-call hygiene

| Blocking in a coroutine | Replace with |
|---|---|
| `requests`, `urllib` | one shared `httpx.AsyncClient` (or aiohttp session) per app, closed on shutdown |
| `time.sleep(n)` | `await asyncio.sleep(n)` |
| psycopg2, sqlite3, PyMySQL | asyncpg, psycopg 3 `AsyncConnection`, aiosqlite, SQLAlchemy 2 asyncio |
| file reads/writes, `os.walk` | `await asyncio.to_thread(path.read_bytes)`, `anyio.Path` |
| `subprocess.run` | `await asyncio.create_subprocess_exec(...)` |
| `threading.Lock` / `queue.Queue` | `asyncio.Lock` / `asyncio.Queue` |
| CPU loop > 10 ms | `loop.run_in_executor(process_pool, fn, arg)` |

Detection:

- Debug mode: `PYTHONASYNCIODEBUG=1` or `asyncio.run(main(), debug=True)` logs
  `Executing <Task ...> took 0.188 seconds` for any step longer than `loop.slow_callback_duration`
  (default 0.1 s), shows where never-awaited coroutines were created, and raises on non-thread-safe
  calls from other threads.
- Dev mode: `PYTHONDEVMODE=1 uv run app.py` (or `uv run python -X dev app.py`; `uv run` itself has no
  `-X`) adds asyncio debug plus `ResourceWarning` for unclosed sockets and transports.
- Static: ruff `ASYNC` rules (ASYNC210 blocking HTTP, ASYNC230 `open`, ASYNC251 `time.sleep`,
  ASYNC22x subprocess, ASYNC110 busy-wait), RUF006 (unreferenced `create_task`), RUF029 (async without
  await); mypy reports a forgotten `await` as `unused-coroutine` by default.

## 6. Task lifetime

The loop keeps only weak references to tasks: an unreferenced task can be garbage-collected mid-flight.

```python
_background: set[asyncio.Task[None]] = set()

def spawn(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
    task.add_done_callback(_report)                   # observe failures now, not at GC time
    return task

def _report(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        log.error("background task %s failed", task.get_name(), exc_info=exc)
```

Better still: own background work in an app-lifespan `TaskGroup` (in `main()` or the framework's
lifespan hook) so shutdown cancels and awaits it. Unobserved failures otherwise surface only as
"Task exception was never retrieved" at garbage collection.

`eager_task_factory` (3.12): `asyncio.get_running_loop().set_task_factory(asyncio.eager_task_factory)`
runs each new task synchronously until its first real suspension; tasks that finish without
suspending (cache hits) never touch the scheduler. 3.14 also accepts
`create_task(coro, eager_start=True)` per task. Behaviour change: code runs before `create_task`
returns, so test ordering assumptions.

## 7. Sync/async bridges

| Situation | Do | Never |
|---|---|---|
| program entry | one `asyncio.run(main())` | `asyncio.run` per request or loop iteration (new loop each time; clients bound to the old loop) |
| sync harness running several coroutines | `with asyncio.Runner() as runner: runner.run(a()); runner.run(b())` | |
| another thread needs a coroutine result | `asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=5)` | calling loop methods from that thread |
| another thread needs to poke the loop | `loop.call_soon_threadsafe(callback, arg)` | `loop.call_soon` (not thread-safe) |
| coroutine needs a blocking call | `await asyncio.to_thread(fn, *args)` | calling `fn` directly |
| sync function inside a running loop wants an async result | make the caller async; or run that part in a worker thread with its own `asyncio.run` | `nest_asyncio`; `asyncio.run` inside a loop raises `RuntimeError: asyncio.run() cannot be called from a running event loop` |
| custom loop (uvloop) | `asyncio.run(main(), loop_factory=uvloop.new_event_loop)` or `uvloop.run(main())` | `set_event_loop_policy` (deprecated in 3.14, removal planned for 3.16) |

3.14 also deprecates `asyncio.iscoroutinefunction` (use `inspect.iscoroutinefunction`), and
`asyncio.get_event_loop()` raises `RuntimeError` when no loop is running: use
`asyncio.get_running_loop()` inside coroutines.

## 8. Libraries and runtimes

- **anyio** for library code that must run on asyncio and trio: `anyio.create_task_group()`,
  `anyio.fail_after(5)`, `anyio.to_thread.run_sync(fn)`, `CapacityLimiter`, memory object streams. Its
  cancel scopes are level-triggered (every await inside a cancelled scope raises), stricter than
  asyncio's one-shot cancellation.
- **trio** for applications that want structured concurrency enforced everywhere.
- **uvloop** (libuv loop, not on Windows) for socket-heavy services; measure before and after, gains
  depend on how much time is spent in the loop itself.
- **Streaming resources**: an async generator holding a connection must be closed when the consumer
  stops early, or cleanup waits for garbage collection:

```python
async with contextlib.aclosing(stream_rows(conn, query)) as rows:
    async for row in rows:
        if row.id == wanted:
            break                                     # aclose() runs here, connection returned
```

## 9. Testing

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"                         # async tests and fixtures need no marker
asyncio_default_fixture_loop_scope = "function"
asyncio_default_test_loop_scope = "function"
filterwarnings = ["error::RuntimeWarning", "error::pytest.PytestUnraisableExceptionWarning"]
```

- pytest-asyncio 1.0 removed the `event_loop` fixture: call `asyncio.get_running_loop()` inside the
  test; share a loop with `@pytest.mark.asyncio(loop_scope="module")`. 1.4 deprecates overriding the
  `event_loop_policy` fixture in favour of the `pytest_asyncio_loop_factories` hook (uvloop runs).
- The anyio plugin is the alternative: `@pytest.mark.anyio` plus an `anyio_backend` fixture.
- HTTP: `respx` or `pytest-httpx` mock `httpx`; no network in unit tests.
- No real sleeps: block slow fakes on an `asyncio.Event` that is never set and use tiny timeouts
  (`asyncio.timeout(0.01)`).
- Test the timeout path, the cancellation path (cleanup ran, `CancelledError` propagated) and the
  partial-failure path explicitly.
- The `filterwarnings` above turns "coroutine ... was never awaited" into a test failure (verified: it
  surfaces as `PytestUnraisableExceptionWarning`).

Recipes (fixtures, cancellation and timeout tests, TaskGroup error tests):
[async-testing.md](references/async-testing.md).

## 10. Debugging hangs

| Tool | Command | Shows |
|---|---|---|
| asyncio CLI (3.14+) | `python -m asyncio ps <pid>`, `python -m asyncio pstree <pid>` | every pending task and what it awaits |
| in-process | `for t in asyncio.all_tasks(): t.print_stack()`; 3.14 `asyncio.print_call_graph(task)` | stacks of suspended tasks |
| py-spy | `py-spy dump --pid <pid> --locals` | thread stacks: a loop thread stuck in `socket.recv` means a blocking call |
| faulthandler | `faulthandler.dump_traceback_later(120, repeat=True)` or `faulthandler.register(signal.SIGUSR1)` | all-thread tracebacks, no dependencies |
| debug mode | `PYTHONASYNCIODEBUG=1` | slow steps, unawaited coroutines |

Attaching needs privileges: on macOS run the asyncio CLI or py-spy with `sudo` (without it: "cannot
be attached to due to insufficient permissions"); on Linux the same user plus a permissive
`kernel.yama.ptrace_scope`, or `sudo -E`. `PYTHON_DISABLE_REMOTE_DEBUG=1` disables the 3.14 attach
protocol in hardened deployments. Check that your py-spy release supports your Python minor version.

| What the dump shows | Usual cause | Fix |
|---|---|---|
| task awaiting a `Future` forever | nobody calls `set_result` (exception path skipped it) | resolve in `finally`; give the wait a timeout |
| producer stuck in `Queue.put` | consumers crashed or never started | consumers and producer in one TaskGroup; `shutdown()` |
| many tasks in `Lock.acquire` | lock held across a slow `await` | shrink the critical section; no network I/O under a lock |
| tasks queued on a `Semaphore` that never frees | manual `acquire()` without `finally: release()` | `async with sem` |
| loop thread inside `requests` / `socket` / `time.sleep` | blocking call in a coroutine | section 5 replacements |
| no tasks pending, process alive | non-daemon thread or executor still running | shut executors down; join threads |

## 11. Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| forgotten `await` | `RuntimeWarning: coroutine ... was never awaited`; work silently skipped | mypy `unused-coroutine`, ruff, `-W error::RuntimeWarning` in tests |
| `create_task` without a stored reference | task vanishes or its exception is never seen | TaskGroup, or the `spawn` helper above |
| client created per request | TLS handshake and pool per call; socket exhaustion | one `AsyncClient` per app with `limits` and `timeout` |
| `async def` endpoint calling sync I/O | whole server stalls under load | async driver or `to_thread`; ruff `ASYNC` |
| timeout around a multi-step write | half-written state after `TimeoutError` | idempotent steps, transactions, or `shield` with its own bound |
| `threading.Lock` in coroutines | deadlock when two tasks on the same thread contend | `asyncio.Lock` |
| `except Exception: pass` around awaits | hides failures; with bare `except`, also cancellation | catch specific errors; re-raise `CancelledError` |
| `gather` without `return_exceptions` | first error returns while siblings keep running | TaskGroup |
| one task per item for millions of items | memory and loop stalls | worker pool on a bounded queue |

## 12. Worked example: fetch 20k URLs

Baseline: a sequential `requests` loop over 20,000 URLs, mean latency 123 ms: 20,000 x 0.123 s =
**41 min**. Goal: under 5 min, clean Ctrl-C, no leaked tasks.

```python
CONCURRENCY = 64

def retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)

async def fetch(client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str) -> dict[str, object]:
    async for attempt in AsyncRetrying(retry=retry_if_exception(retryable), stop=stop_after_attempt(4),
                                       wait=wait_random_exponential(multiplier=0.5, max=8), reraise=True):
        with attempt:
            async with sem:                    # bounds in-flight requests, not sleeping retries
                r = await client.get(url)
            r.raise_for_status()
            return {"url": url, "status": r.status_code, "bytes": len(r.content)}
    raise AssertionError("unreachable")

async def fetch_one(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                    out: asyncio.Queue[dict[str, object]], url: str) -> None:
    try:
        row = await fetch(client, sem, url)
    except httpx.HTTPError as e:               # a dead URL is a row, not a crash of the run
        row = {"url": url, "error": type(e).__name__}
    await out.put(row)                         # bounded queue: backpressure from the writer

async def main(urls: list[str], path: Path) -> int:
    sem = asyncio.Semaphore(CONCURRENCY)
    out: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=1000)
    limits = httpx.Limits(max_connections=CONCURRENCY, max_keepalive_connections=CONCURRENCY)
    timeout = httpx.Timeout(10.0, connect=3.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client, asyncio.TaskGroup() as tg:
        w = tg.create_task(writer(out, path))  # 500-row batches via to_thread; flushes in finally
        async with asyncio.TaskGroup() as fetchers:
            for i, url in enumerate(urls):
                fetchers.create_task(fetch_one(client, sem, out, url))
                if i % 500 == 499:
                    await asyncio.sleep(0)     # yield so one loop step never creates 20k tasks
        out.shutdown()                         # writer drains, sees QueueShutDown, returns
    return w.result()
```

Imports, the writer and the `__main__` block (exit 130 on Ctrl-C) are in
[fetch-all-example.md](references/fetch-all-example.md). Choices: tenacity full-jitter backoff on
5xx and transport errors only (never on 4xx); the semaphore is taken per attempt so backoff sleeps do
not hold a slot; 20k tasks cost about 20 MB and 20 ms to create, acceptable here (section 3 says when
to switch to workers). Without the `sleep(0)` every 500 tasks, debug mode flagged the creation loop
(`Executing <Task ... main() ...> took 0.188 seconds` for 3,000 tasks); with it, dev mode is silent.

Result: **3.5 min** (210 s). Little's law check: throughput 20,000 / 210 = 95 req/s, so mean time in
flight `W = L / lambda = 64 / 95 = 0.67 s`, 5.5x the unloaded 123 ms. The origin is now the
bottleneck (it queues requests), so raising the semaphore would only add queueing: sweep 16/32/64 and
keep the smallest value at the throughput plateau. Measure the client too: in the lab, httpx 0.28.1 on
macOS plateaued near 150 req/s above about 48 connections against a local server that aiohttp drove at
about 1,170 req/s with 64.

Verification, all run in the lab against a local test server (50 ms latency, 2% 503s):

```bash
PYTHONDEVMODE=1 uv run --script fetch_all.py urls.txt out.jsonl   # "3000 rows in 24.5s", nothing else
wc -l out.jsonl; grep -c '"error"' out.jsonl                      # 3000 rows, 0 errors despite 2% 503s
uv run --no-project --with mypy --with httpx --with tenacity mypy --strict fetch_all.py  # clean
# SIGINT after 4 s: exit code 130, every flushed line valid JSON (313 and 343 rows in two runs),
# no pending-task warnings
```

Done when: rows equal URLs, injected 5xx are absorbed by retries, dev mode is silent, Ctrl-C leaves a
valid partial file, and the concurrency value is justified by the sweep rather than guessed.

Related: `python-uv-packaging`, `python-typing`, `pytest-patterns`, `fastapi-pydantic-services`,
`python-performance-profiling`, `resilience-patterns`, `observability-instrumentation`,
`debugging-method`, `performance-optimization`, `code-review-checklist`; hub `coding-general`.
