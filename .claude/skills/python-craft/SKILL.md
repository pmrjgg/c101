---
name: python-craft
description: "Python expertise pack covering repo orientation, the ruff + type checker + pytest gate in uv-managed environments, data modelling with dataclasses, enums and Protocols, exception design, typing, asyncio vs threads vs processes, packaging with pyproject and uv.lock, profiling, FastAPI/pydantic v2 services, and common pitfalls such as mutable defaults, late-binding closures, blocking calls in coroutines and naive datetimes. Load when writing, reviewing, debugging, packaging or profiling Python code."
when_to_use: "Any task touching .py/.pyi files, pyproject.toml, uv.lock, requirements*.txt, conftest.py or a '# /// script' block; mypy/pyright errors; asyncio hangs or 'coroutine was never awaited'; ImportError or dependency resolution failures; slow pandas, NumPy or pure-Python loops; FastAPI or pydantic services; Python CI gates."
---

# Python craft

Baseline: CPython 3.13 and 3.14, with older floors common in libraries. Facts that change code:
`TaskGroup`, `asyncio.timeout`, `ExceptionGroup`/`except*`, `tomllib`, `Self`, `add_note` (3.11);
PEP 695 type parameters and `type` aliases, `@override`, `itertools.batched`, f-string grammar
(PEP 701), `distutils` removed, `datetime.utcnow()` deprecated (3.12); TypeVar defaults, `TypeIs`,
`ReadOnly`, `warnings.deprecated`, `copy.replace`, the "dead batteries" removed (`cgi`, `crypt`,
`telnetlib`, `nntplib` and friends, PEP 594), an experimental free-threaded build (`3.13t`) and an
experimental JIT (3.13); lazily evaluated annotations (PEP 649), template strings (PEP 750),
`concurrent.interpreters` and `InterpreterPoolExecutor`, `forkserver` as the default start method on
Linux, and the free-threaded build officially supported (3.14). The free-threaded build is a separate,
opt-in interpreter (`python3.14t`); the default build still has the GIL.
Language semantics follow `requires-python` in pyproject.toml (its floor), not the interpreter on your
machine: check it first, and never use syntax newer than the floor.

Deep material:
[gate recipes and tool mapping](references/gate-recipes.md) |
[stdlib idioms and data modelling](references/stdlib-idioms.md)

## 1. Orient in a repo

```bash
cat .python-version 2>/dev/null; grep -n 'requires-python' pyproject.toml
ls uv.lock poetry.lock Pipfile.lock requirements*.txt setup.py setup.cfg tox.ini noxfile.py 2>/dev/null
grep -nE '^\[(tool\.(ruff|mypy|pyright|basedpyright|pyrefly|pytest|coverage|uv)|build-system|dependency-groups)' pyproject.toml
ls .pre-commit-config.yaml mypy.ini pyrightconfig.json pytest.ini conftest.py tests/conftest.py 2>/dev/null
uv run python -VV; uv tree --depth 1 | head -40         # interpreter and direct dependencies
ls src/ 2>/dev/null; find . -name py.typed -not -path './.venv/*'   # src layout? typed library?
```

Record: `requires-python` floor, package manager (uv, Poetry, pip-tools, plain pip), the gating type
checker and its strictness, test runner config, whether the project is a library (public API and
supported versions matter) or an application (lockfile and deploy matter), and CI commands
(`.github/workflows/*.yml`, `Makefile`, `noxfile.py`). The CI commands are the contract: run the same.

## 2. The gate

| Step | Command (uv project) | Blocks when |
|---|---|---|
| Lint | `uv run ruff check .` | any finding at the project's rule set |
| Format | `uv run ruff format --check .` | any file would change |
| Types | `uv run mypy --strict <touched modules>` or `uv run pyright <paths>` (the project's checker and config) | any new error |
| Tests | `uv run pytest -q` (project config; add `-x --lf` while iterating) | failure, error, or a warning promoted to error |
| Lock | `uv lock --check` | lockfile out of date with pyproject |
| Vulnerabilities (deps changed) | `uvx pip-audit -r <exported lock>` ([recipe](references/gate-recipes.md)) | a known vulnerable pinned version |

Adapt, do not impose: a project on black + isort + flake8, Poetry, tox or nox keeps its tools; run its
commands (mapping in [gate-recipes](references/gate-recipes.md)). Do not migrate tooling inside an
unrelated change. A type checker always runs **inside the project env** (`uv run ...`) so it sees
installed packages and stubs; a global `mypy` reports phantom `import-not-found` errors.
`--strict` on touched modules is the bar for new code even when the project config is looser; do not
flip the project-wide setting without a baseline (`python-typing` section 2).

## 3. Data modelling and API shape

Rules:
1. Pick the lightest shape that carries the invariants (table below). Plain dicts across module
   boundaries are untyped contracts: give them a `TypedDict` or a dataclass.
2. `@dataclass(frozen=True, slots=True)` for value objects; `kw_only=True` once there are more than
   three fields. Validate invariants in `__post_init__`, and change copies with `dataclasses.replace`
   (or `copy.replace`, 3.13+).
3. Parse at the boundary, trust inside: untrusted input (HTTP, files, env) becomes a validated model
   (pydantic v2 or explicit parsing) once; core code takes typed objects, never raw dicts.
4. Accept abstract, return concrete: parameters `Iterable[T]`, `Mapping[K, V]`, `Sequence[T]`;
   return `list[T]`, `dict[K, V]`. Structural seams via `typing.Protocol` defined by the consumer.
5. Functions over classes when there is no state; modules are the namespace (no static-method bags,
   no `utils.py` dumping grounds).
6. Keyword-only parameters (`*`) for flags and anything a caller could confuse; never a positional bool.
7. Public names in `__all__`; underscore-prefix everything else in a library.

| Need | Python shape |
|---|---|
| immutable value with invariants | frozen, slotted dataclass |
| external input with validation and coercion | pydantic `BaseModel` (`fastapi-pydantic-services`) |
| dict-shaped JSON you do not own | `TypedDict` (`NotRequired`, `ReadOnly`) |
| closed set of constants | `enum.Enum` / `StrEnum`; `match` with `assert_never` for exhaustiveness |
| closed set of variants with data | union of dataclasses + `match` on class patterns |
| polymorphism over behaviour | `Protocol` at the consumer; ABC only when sharing implementation |
| generic container or algorithm | PEP 695 generics (`class Box[T]:`) on 3.12+ floors, `TypeVar` below |
| resource with setup and teardown | context manager (`@contextmanager` or `__enter__`/`__exit__`) |

## 4. Exceptions

```python
class BillingError(Exception):
    """Base for this package: callers catch one type."""

class InvoiceNotFound(BillingError):
    def __init__(self, invoice_id: int) -> None:
        super().__init__(f"invoice {invoice_id} not found")
        self.invoice_id = invoice_id                     # data for callers, not just a message

def load_invoice(repo: Repo, invoice_id: int) -> Invoice:
    try:
        row = repo.fetch(invoice_id)
    except KeyError:
        raise InvoiceNotFound(invoice_id) from None      # hide the internal cause deliberately
    except DatabaseError as e:
        raise BillingError(f"load invoice {invoice_id}") from e   # keep the chain
    return Invoice.from_row(row)
```

Rules:
- Catch the narrowest type at the place that can **handle** it; let everything else propagate.
  Handle or re-raise, never both (log-and-raise duplicates every traceback up the stack).
- `raise X from e` keeps the cause; `from None` hides it on purpose. A bare `raise` re-raises unchanged.
- `except Exception:` only at process or request boundaries, with `logger.exception(...)`. Never bare
  `except:` (it swallows `KeyboardInterrupt` and `SystemExit`), never `except BaseException` unless
  re-raising, and in async code never swallow `CancelledError`.
- `try` blocks cover only the line that can raise; the success path goes in `else`.
- `ExceptionGroup` and `except*` for concurrent failures (`TaskGroup` raises groups); `e.add_note()`
  adds context without changing the type.
- `assert` is for internal invariants only: `python -O` strips it, so never use it to validate input.
- Return `None` for "not found" only when absence is normal and typed (`-> User | None`); otherwise raise.

## 5. Typing (summary; full playbook in `python-typing`)

1. One gating checker, pinned in the dev group, run with `uv run`. New and touched code passes
   `--strict` (mypy) or `typeCheckingMode = "strict"` (pyright).
2. Annotate public signatures first; locals are inferred. `Any` is a hole, not a type: prefer
   `object` for "anything" you will only pass through.
3. `X | None` and builtin generics (`list[int]`) in annotations; `collections.abc` for `Callable`,
   `Iterable`, `Mapping`.
4. Narrow before use (`if x is None: return`, `isinstance`, `TypeIs` functions); never silence
   `union-attr` with a cast.
5. `# type: ignore[code]` always with the code and a reason; `warn_unused_ignores` removes stale ones.
6. Untyped third-party package: install its stubs (`types-*`, `pandas-stubs`) into the dev group
   before reaching for `ignore_missing_imports`.

## 6. Concurrency rules (summary; asyncio in `python-asyncio`)

| Workload | Use |
|---|---|
| many concurrent network calls with async libraries | asyncio with `TaskGroup` and a semaphore bound |
| blocking library (sync SDK, file I/O) inside async code | `await asyncio.to_thread(fn, ...)` |
| blocking I/O in a sync program | `ThreadPoolExecutor` |
| CPU-bound pure Python, GIL build | `ProcessPoolExecutor` (3.14+: `InterpreterPoolExecutor` is an option) |
| CPU-bound in NumPy, Polars, hashlib, zlib | threads: these release the GIL |

1. Every task has an owner that awaits it: `async with asyncio.TaskGroup()` instead of loose
   `create_task` (the loop only weakly references tasks; an unreferenced one can vanish mid-flight).
2. Every network await has a deadline (`async with asyncio.timeout(5):` or the client's timeout).
3. Nothing blocks the event loop: no `time.sleep`, `requests`, sync DB drivers or CPU work over
   ~10 ms in a coroutine. Detect with `PYTHONASYNCIODEBUG=1` and ruff `ASYNC` rules.
4. Cancellation is an exception: `CancelledError` must propagate; clean up in `finally`.
5. Threads share state: guard it with `threading.Lock`. On a free-threaded build, code that leaned on
   the GIL for atomicity of compound operations is racy; check `sys._is_gil_enabled()` after imports.
6. Process pools pickle arguments: pass paths or ids, guard entry with `if __name__ == "__main__":`.

## 7. Testing (full playbook in `pytest-patterns`)

```python
import pytest
from billing.money import parse_amount, InvalidAmount

@pytest.mark.parametrize(
    ("raw", "expected"),
    [("12.50", 1250), ("0", 0), ("1e3", 100_000)],
    ids=["decimal", "zero", "exponent"],
)
def test_parse_amount_cents(raw: str, expected: int) -> None:
    assert parse_amount(raw) == expected

@pytest.mark.parametrize("raw", ["", "abc", "-1", "1.005"])
def test_parse_amount_rejects(raw: str) -> None:
    with pytest.raises(InvalidAmount):
        parse_amount(raw)
```

- Strict config: `--strict-markers`, `--strict-config`, `filterwarnings = ["error"]`, `strict_xfail`.
- Fixtures over setup methods; factories for variations; `tmp_path`, `monkeypatch`, `caplog`,
  `capsys` before writing helpers.
- Mock at the boundary you own, with `autospec=True`, patched where it is **looked up**
  (`mocker.patch("billing.service.http_get")`, not `"httpx.get"`).
- Property-based tests (`hypothesis`) for parsers, serialisers and anything with round-trip laws.
- A bug fix lands with a test that fails before the fix and passes after.
- Order dependence: pytest-randomly shuffles once installed; replay with `--randomly-seed=N`,
  isolate with `-p no:randomly`. Parallel with `pytest -n auto` (xdist) only when tests are isolated.

## 8. Performance procedure (full playbook in `python-performance-profiling`)

1. Reproduce with a fixed input and a timing harness: `python -m pyperf timeit` or `pyperf command`
   for programs, `pytest-benchmark` for regression gates. Confirm output identity before timing.
2. Profile without guessing: `py-spy record -o profile.speedscope.json --format speedscope -- python job.py` or
   `py-spy top --pid N` for live processes; `python -m cProfile -o prof.out job.py` then
   `python -c "import pstats; pstats.Stats('prof.out').sort_stats('cumulative').print_stats(25)"`;
   memory with `memray run` / `tracemalloc`.
3. Fix the top item, re-measure with the same harness, report median and spread.

| Profile symptom | Fix |
|---|---|
| time in a Python `for` over rows (`iterrows`, `apply(axis=1)`) | vectorise in NumPy/pandas/Polars; never loop rows in Python |
| repeated membership tests on a list | `set` / `dict` |
| string building with `+=` in a loop | `"".join(parts)`, `io.StringIO` |
| same pure function called with same args | `functools.cache` / `lru_cache(maxsize=N)` |
| attribute lookups in a hot loop | hoist to a local; `__slots__` for many small objects |
| many small objects, high RSS | `slots=True` dataclasses, arrays (`array`, NumPy) instead of lists of floats |
| slow import / CLI startup | `python -X importtime`, move heavy imports into functions |
| CPU-bound kernel still dominant | Numba, Cython, mypyc or a Rust extension (PyO3), chosen by measurement |
| threads do not scale on CPU work | processes, or a free-threaded build if every extension supports it |

## 9. Packaging and environments (full playbook in `python-uv-packaging`)

| Task | Command |
|---|---|
| runtime dependency | `uv add 'httpx>=0.28'` |
| dev tool (test, lint, type) | `uv add --dev pytest mypy ruff` |
| reproduce the env exactly (CI) | `uv sync --locked` |
| bump one package | `uv lock --upgrade-package httpx` |
| why is a package here | `uv tree --invert --package urllib3` |
| pin the interpreter | `uv python pin 3.13` (writes `.python-version`) |
| one-off tool without polluting the env | `uvx pip-audit`, `uvx ruff` |
| single-file script with deps | PEP 723 `# /// script` block, `uv run script.py` |
| build a wheel / sdist | `uv build`; publishing is irreversible: return it as an Open doubt |

- Never `pip install` into a uv project (the next `uv sync` removes it) and never into the system Python.
- `requires-python` is a floor for every consumer: raising it in a library is a breaking change.
- Libraries declare ranges (`httpx>=0.27`), applications commit `uv.lock`; never pin `==` in a library.
- Commit `uv.lock` with the pyproject change that caused it.

## 10. Idioms (write this, not that)

| Instead of | Write | Why |
|---|---|---|
| `for i in range(len(xs)): x = xs[i]` | `for i, x in enumerate(xs)` | no index errors |
| two lists walked in step | `for a, b in zip(xs, ys, strict=True)` | length mismatch raises |
| `if key in d: v = d[key] else: v = default` | `d.get(key, default)`; counts with `Counter`, groups with `defaultdict(list)` | one lookup |
| `open(p).read()` | `Path(p).read_text(encoding="utf-8")` or `with open(p, encoding="utf-8") as f:` | closed handle, explicit encoding |
| `os.path.join(a, b)` | `Path(a) / b` | typed paths |
| `"%s: %s" % (k, v)` or `.format` | f-strings; `logger.info("user %s", uid)` in logging (lazy) | readable; no eager log formatting |
| `datetime.utcnow()`, naive `datetime.now()` | `datetime.now(UTC)`; `zoneinfo.ZoneInfo("Europe/Paris")` | aware times compare and serialise correctly |
| `type(x) == Foo` | `isinstance(x, Foo)` or `match` | subclasses, narrowing |
| `x == None` | `x is None` | identity, no `__eq__` surprises |
| manual `try/finally` close | `with` / `contextlib.ExitStack` | exception-safe |
| `list(map(lambda x: ..., xs))` | comprehension; generator expression when consumed once | clearer, lazier |
| chunking by hand | `itertools.batched(xs, 100)` (3.12+) | fewer off-by-one bugs |
| `subprocess.run(cmd, shell=True)` with input | `subprocess.run([...], check=True, timeout=60)` | no shell injection, failures raise |
| `print` for diagnostics | `logging.getLogger(__name__)` | levels, handlers, structure |
| global mutable singletons | pass dependencies explicitly; module-level constants only | testable |

## 11. Pitfalls (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| list default grows across calls | mutable default `def f(x=[])` evaluated once | `x: list[int] \| None = None`, create inside; dataclasses `field(default_factory=list)` |
| all lambdas use the last loop value | closures bind names late | default arg `lambda i=i: ...` or `functools.partial` |
| instances share state unexpectedly | mutable class attribute `items = []` | assign in `__init__` / dataclass field factory |
| `RuntimeWarning: coroutine ... was never awaited` | missing `await` | add it; mypy `unused-coroutine`, ruff RUF006 for dropped tasks |
| whole service stalls under load | blocking call inside a coroutine | async client or `asyncio.to_thread` (section 6) |
| `ImportError: cannot import name ... (most likely due to a circular import)` | modules import each other at top level | move the shared type to a third module; import inside the function; `TYPE_CHECKING` guard for annotation-only imports |
| tests pass locally, fail in CI | env differs: unlocked deps, system Python, TZ/locale | `uv sync --locked`, pin Python, set `TZ`/encoding in tests |
| `UnicodeDecodeError` on another OS | `open()` without `encoding` uses the locale | always pass `encoding="utf-8"` |
| `float` sums off by a cent | binary floating point | `decimal.Decimal` or integer cents for money; `math.isclose` for comparisons |
| dict changed size during iteration | mutating while iterating | iterate over `list(d)` or build a new dict |
| HTTP call hangs forever | `requests` call without `timeout=` (it has no default; httpx defaults to 5 s) | explicit `timeout=` on every call or client |
| pandas assignment silently does nothing | chained assignment `df[df.a > 0]["b"] = 1` (never updates under Copy-on-Write) | `df.loc[df.a > 0, "b"] = 1` |
| `pickle.load` on received data | arbitrary code execution | JSON or a schema'd format; never unpickle untrusted bytes |
| `except Exception: pass` hides a bug | swallowed error | narrow the type, log with traceback, or remove |
| works in REPL, `ModuleNotFoundError` in tests | flat layout and import-path accidents | src layout and an installed project (`uv sync`), not `sys.path` hacks |
| `is` comparison of ints or strings "randomly" fails | identity vs equality (small-int and interning caches) | `==` for values; `is` only for `None` and sentinels |
| async test hangs or "attached to a different loop" | event-loop-scoped fixtures mismatched | pytest-asyncio loop scope config (`pytest-patterns`) |

## 12. Review checklist

- [ ] Gate green: ruff check, ruff format --check, the project's type checker on touched modules, pytest.
- [ ] No syntax or stdlib API newer than `requires-python`.
- [ ] Untrusted input parsed into a typed model at the boundary; no raw dicts in the core.
- [ ] Exceptions narrow, chained with `from`, handled or re-raised but not both; no bare `except`.
- [ ] Every coroutine awaited, every task owned by a `TaskGroup`, every network call has a timeout.
- [ ] No blocking call in async code; no shared mutable state across threads without a lock.
- [ ] Files opened with `with` and an explicit encoding; datetimes timezone-aware.
- [ ] New dependencies justified, added with `uv add`, lockfile committed; library ranges not pinned.
- [ ] New behaviour tested; bug fixes have a fail-before, pass-after test; performance claims have
      before/after numbers from the same harness.
- [ ] Public functions annotated and documented; no `utils.py` growth, no `print` debugging left.

## 13. Worked example: a blocking call stalls a FastAPI service

Symptom: p99 of `GET /quote` jumps from 40 ms to 2.1 s at 50 concurrent users; CPU is idle.

```python
@app.get("/quote/{sku}")
async def quote(sku: str) -> Quote:
    price = requests.get(f"{PRICING}/{sku}").json()["price"]      # blocks the loop, no timeout
    time.sleep(0.05)                                              # "rate limit" blocks it again
    return Quote(sku=sku, price=price)
```

Evidence: `PYTHONASYNCIODEBUG=1 uv run uvicorn app.main:app` logs
`Executing <Task ...> took 0.412 seconds`; `uv run ruff check --select ASYNC app/` reports ASYNC210
and ASYNC251 on those two lines.

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(base_url=PRICING, timeout=httpx.Timeout(2.0)) as client:
        app.state.pricing = client                                # one pooled client per process
        yield

app = FastAPI(lifespan=lifespan)
limit = asyncio.Semaphore(20)                                     # protect the pricing service

@app.get("/quote/{sku}")
async def quote(sku: str, request: Request) -> Quote:
    async with limit:
        resp = await request.app.state.pricing.get(f"/{sku}")
    resp.raise_for_status()
    return Quote(sku=sku, price=Decimal(str(resp.json()["price"])))
```

A regression test drives 50 concurrent requests through `httpx.ASGITransport` against a fake pricing
handler that sleeps 50 ms asynchronously and asserts total wall time under 0.5 s (it took 2.6 s before).
After: p99 45 ms at 50 users, with the same load script before and after.

## Delegation hints

- Profiling a production incident or a hang with py-spy dumps: `debugger` with the dump paths.
- Systematic optimisation against a latency or memory budget once a harness exists: `code-optimizer`.
- Test strategy, coverage gaps, long hypothesis or load campaigns: `tester`.
- Untrusted input, auth, deserialisation, `subprocess`: `security-auditor`.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `python-typing` | adding or fixing type hints, configuring mypy/pyright/pyrefly, strict-mode burn-down, typing decorators, overloads or generics |
| `python-asyncio` | writing, reviewing or debugging async Python: TaskGroup, timeouts, cancellation, bounded fan-out, blocking calls, hangs |
| `python-uv-packaging` | creating or fixing pyproject.toml, uv.lock, dependency resolution, workspaces, custom indexes, migration from pip/Poetry, build and publish |
| `pytest-patterns` | writing, organising, speeding up or debugging a pytest suite: fixtures, parametrize, mocking, async and DB tests, xdist |
| `python-performance-profiling` | Python code is slow or memory-hungry: pyperf, py-spy, memray, vectorisation, compiled kernels, parallelism |
| `fastapi-pydantic-services` | building, reviewing or debugging a FastAPI service with pydantic v2, settings, DI, lifespan, SQLAlchemy async |

From the `coding-core` pack (hub `coding-general`):

| skill | load when |
|---|---|
| `refactoring-playbook` | restructuring Python modules without changing behaviour |
| `codemod-automation` | the same rewrite at dozens of sites (LibCST, ruff `--fix`, ast-grep) |
| `dependency-upgrades` | bumping Python, Django, pydantic, SQLAlchemy or other major versions |
| `api-contract-design` | changing a FastAPI/OpenAPI endpoint, error format or pagination |
| `sql-query-tuning` | an ORM-generated query is slow (N+1, missing index) |
| `zero-downtime-migrations` | writing Alembic or Django migrations for a live database |
| `resilience-patterns` | retries, timeouts, circuit breakers around network calls |
| `regex-engineering` | writing or debugging `re` patterns |
| `docs-and-adr-writing` | docstrings, README, changelog or an ADR for a design choice |
| `git-advanced-workflows` | rebasing, bisecting or untangling history |
