# Async testing recipes

Companion to `python-asyncio` section 9. Everything here ran green on Python 3.14 with pytest 9.1,
pytest-asyncio 1.4, respx, httpx 0.28, anyio 4.15 and trio. General test design (levels, fixtures,
parametrisation, coverage) is `pytest-patterns`.

## Configuration

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"                              # async tests/fixtures run without markers
asyncio_default_fixture_loop_scope = "function"   # explicit (function is the default in 1.4)
asyncio_default_test_loop_scope = "function"
filterwarnings = [
  "error::RuntimeWarning",                         # "coroutine ... was never awaited"
  "error::pytest.PytestUnraisableExceptionWarning" # how that warning reaches pytest (GC time)
]
```

Install: `uv add --dev pytest pytest-asyncio respx` (or `pytest-httpx` instead of respx).

pytest-asyncio 1.x reminders:

| Topic | 1.x behaviour |
|---|---|
| `event_loop` fixture | removed in 1.0; use `asyncio.get_running_loop()` inside the test |
| shared loop for a module or session | `@pytest.mark.asyncio(loop_scope="module")`; fixtures: `@pytest_asyncio.fixture(loop_scope="module")` |
| scoped loops | created once per scope (1.0); tasks still pending when the scope ends are cancelled (1.1) |
| invalid scope values in config | `pytest.UsageError` (1.2) |
| custom loops (uvloop) | 1.4 deprecates overriding `event_loop_policy`; use the `pytest_asyncio_loop_factories` hook (see the plugin docs for its exact signature) |

## conftest.py: shared client and a leak detector

```python
import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url="https://api.example.test") as c:
        yield c


@pytest.fixture(autouse=True)
async def no_leaked_tasks() -> AsyncIterator[None]:
    yield
    current = asyncio.current_task()
    leaked = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert not leaked, f"leaked tasks: {leaked}"
```

The autouse `no_leaked_tasks` fixture fails any test that leaves tasks running (a missing `await`, a
`create_task` nobody owns, a background loop without shutdown).

## Recipes

```python
import asyncio

import httpx
import pytest
import respx


async def get_title(client: httpx.AsyncClient) -> str:
    r = await client.get("/title")
    r.raise_for_status()
    return r.text


@respx.mock
async def test_success(client: httpx.AsyncClient) -> None:
    respx.get("https://api.example.test/title").respond(200, text="hi")
    assert await get_title(client) == "hi"


@respx.mock
async def test_5xx_raises(client: httpx.AsyncClient) -> None:
    respx.get("https://api.example.test/title").respond(503)
    with pytest.raises(httpx.HTTPStatusError):
        await get_title(client)


async def test_timeout_path() -> None:
    never = asyncio.Event()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await never.wait()


async def test_cancellation_runs_cleanup_and_propagates() -> None:
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def worker() -> None:
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    task = asyncio.create_task(worker())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()


async def test_taskgroup_failure_cancels_siblings() -> None:
    sibling_cancelled = asyncio.Event()

    async def slow() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            sibling_cancelled.set()
            raise

    async def boom() -> None:
        raise ValueError("bad row")

    with pytest.RaisesGroup(ValueError):
        async with asyncio.TaskGroup() as tg:
            tg.create_task(slow())
            tg.create_task(boom())
    assert sibling_cancelled.is_set()


async def test_concurrency_never_exceeds_limit() -> None:
    limit, in_flight, peak = 4, 0, 0
    sem = asyncio.Semaphore(limit)

    async def call() -> None:
        nonlocal in_flight, peak
        async with sem:
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1

    async with asyncio.TaskGroup() as tg:
        for _ in range(50):
            tg.create_task(call())
    assert peak == limit


async def test_queue_shutdown_drains_then_stops() -> None:
    q: asyncio.Queue[int] = asyncio.Queue()
    for i in range(3):
        q.put_nowait(i)
    q.shutdown()
    seen = []
    while True:
        try:
            seen.append(await q.get())
        except asyncio.QueueShutDown:
            break
    assert seen == [0, 1, 2]


@pytest.mark.asyncio(loop_scope="module")
async def test_module_loop_a() -> None:
    assert asyncio.get_running_loop().is_running()
```

What each test pins down:

| Test | Guards against |
|---|---|
| `test_success`, `test_5xx_raises` | HTTP behaviour without network (respx intercepts httpx) |
| `test_timeout_path` | the timeout branch actually fires; uses an `Event` that is never set, no real sleep |
| `test_cancellation_runs_cleanup_and_propagates` | cleanup in `finally` runs and `CancelledError` is not swallowed |
| `test_taskgroup_failure_cancels_siblings` | first failure cancels siblings; `pytest.RaisesGroup` (pytest 8.4+) matches the `ExceptionGroup` |
| `test_concurrency_never_exceeds_limit` | the semaphore bound holds (peak in-flight equals the limit) |
| `test_queue_shutdown_drains_then_stops` | 3.13 `Queue.shutdown` semantics used by worker pools |
| `test_module_loop_a` | module-scoped loop marker syntax |

## anyio plugin (asyncio and trio backends)

The anyio pytest plugin ships with anyio. Keep it apart from pytest-asyncio auto mode: in auto mode
pytest-asyncio also claims async fixtures, so an autouse async fixture such as `no_leaked_tasks` runs
under the wrong runner and trio tests fail. Either use one plugin per suite, or set
`asyncio_mode = "strict"` and mark pytest-asyncio tests with `@pytest.mark.asyncio` (both verified).

```python
import anyio
import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["asyncio", "trio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    return request.param


async def test_fail_after() -> None:
    with pytest.raises(TimeoutError):
        with anyio.fail_after(0.01):
            await anyio.sleep(1)
```

## Patterns that keep async tests fast and deterministic

- Synchronise with `asyncio.Event`, `asyncio.Barrier` (3.11) or queues, never with `sleep(0.1)`.
- Give every potentially blocking await in a test a timeout (`async with asyncio.timeout(1):`) so a
  regression fails in one second instead of hanging CI until the job timeout.
- Fake slow dependencies with an `Event` they wait on; release it from the test to control ordering.
- For retry/backoff code, inject the wait strategy (tenacity: `wait=wait_none()` in tests) instead of
  patching `asyncio.sleep` globally.
- Run the async suite once under `PYTHONDEVMODE=1` in CI to surface `ResourceWarning`s (unclosed
  clients and transports) and slow-callback logs.
