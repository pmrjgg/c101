---
name: pytest-patterns
description: "Productive pytest: strict configuration (pytest 9 native [tool.pytest] TOML), conftest layout, fixture scopes, factories and teardown, parametrize with ids and marks, built-in helpers, autospec mocking and where to patch, HTTP and time fakes, async and database tests, snapshot testing, xdist/randomly for speed and isolation, and debugging flags. Load when writing, organising, speeding up or debugging a Python test suite."
when_to_use: "Editing tests/, conftest.py or the [tool.pytest] table; errors like 'fixture not found', 'not found in markers configuration option', 'Cannot use both [tool.pytest] and [tool.pytest.ini_options]', ScopeMismatch, 'attached to a different loop'; mocks that pass while production fails; slow, order-dependent or xdist-only failures; snapshot updates."
---

# pytest patterns

Baseline: pytest 9.x (checked against 9.1.1), pytest-asyncio 1.x, pytest-xdist 3.x, pytest-randomly
5.x; code samples assume Python >= 3.11. This skill is the *how* of pytest. Choosing the test level, property-based
testing, mutation testing and flaky-test run-count math stay in `testing-strategy`; the rule never to
weaken an assertion to get green comes from there too.

Deep material: [command cheat-sheet](references/cli-cheatsheet.md) |
[database and async fixtures](references/db-fixtures.md)

## 1. Configuration: strict by default

pytest 9.0 added native TOML config. Pick one form per project. If both tables exist, pytest refuses
to start: `Cannot use both [tool.pytest] (native TOML types) and [tool.pytest.ini_options]`.

```toml
# pyproject.toml, pytest >= 9.0: real TOML lists and booleans
[tool.pytest]
minversion = "9.0"
addopts = ["-ra", "--strict-markers", "--strict-config"]
testpaths = ["tests"]
strict_xfail = true                      # alias of xfail_strict: an unexpected XPASS fails
filterwarnings = [
    "error",                             # a warning fails the test that raised it
    "ignore:datetime.datetime.utcnow:DeprecationWarning:botocore.*",   # third party, ticket #881
]
markers = [
    "slow: takes more than 1 s; deselect with -m 'not slow'",
    "integration: needs Docker (Postgres, MinIO)",
]
```

| Form | Where | Notes |
|---|---|---|
| `[tool.pytest]` | pyproject.toml | pytest >= 9.0, native types (above) |
| `[pytest]` table | `pytest.toml` | same keys; wins over pyproject.toml in the same directory |
| `[tool.pytest.ini_options]` | pyproject.toml | legacy INI semantics; use when pytest < 9 must still run |
| `strict = true` | any of the above | 9.0+: turns on strict_config, strict_markers, strict_xfail, strict_parametrization_ids; later releases may add more checks |
| `max_warnings = "0"` | any | 9.1+: fail a green run that emits more warnings than the threshold |

- `-ra` prints a reason for every skip, xfail and error in the summary. Hidden skips are where
  coverage goes to die.
- `--strict-markers`: a typo such as `@pytest.mark.intergration` becomes a collection error instead
  of a marker that `-m` silently never selects.
- `--strict-config`: unknown keys in the pytest section are errors, so a misspelt key fails instead
  of being ignored.
- `filterwarnings = ["error", ...]`: every ignore names the message, category and module, and has a
  ticket. A bare `"ignore::DeprecationWarning"` is a bug.
- Check which file won: the session header prints `configfile:`. A `pytest.toml` or `pytest.ini` takes
  precedence even when empty.
- Run through the project environment: `uv run pytest`. With a `src/` layout `uv sync` installs the
  package, so tests import the installed code and not whatever is in the current directory. Use
  `pythonpath = ["src"]` only for unpackaged apps. `--import-mode=importlib` (recommended for new
  projects) stops test modules importing each other; shared helpers go in a package.

## 2. conftest layout

```
tests/
├── conftest.py          # root: pytest_plugins, session resources, shared fixtures, hooks
├── factories.py         # data builders (plain module, imported by fixtures)
├── helpers/assertions.py # custom assert helpers (registered for rewriting, see section 10)
├── unit/conftest.py     # fakes only; no I/O fixtures visible here
└── integration/conftest.py  # containers, S3 fake, auto-marks tests as integration
```

- `pytest_plugins = ["tests.fixtures.db"]` is allowed only in the rootdir conftest. In a nested one
  pytest fails with `Defining 'pytest_plugins' in a non-top-level conftest is no longer supported`.
- A fixture in a deeper conftest overrides the same name for that subtree. It can request the
  outer one by the same name to extend it.
- conftest.py holds fixtures and hooks, not helper functions to import. Helpers go in modules.
- Auto-mark by directory instead of decorating 300 tests:

```python
# tests/integration/conftest.py
def pytest_collection_modifyitems(config, items):   # receives every collected item, not just this dir's
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker("integration")
```

| Question | Command |
|---|---|
| Which fixtures are visible here, and from which file? | `pytest --fixtures -v tests/unit` |
| What does one test use? | `pytest --fixtures-per-test tests/unit/test_x.py::test_y` |
| In what order do setup and teardown run, and at which scope? | `pytest --setup-show -k test_y` (`--setup-plan` to only plan) |
| Which conftests and plugins loaded? | `pytest --trace-config -q --co` |
| Which markers are registered? | `pytest --markers` |

## 3. Fixtures

| Scope | Use for | Never for |
|---|---|---|
| `function` (default) | anything mutable: sessions, mocks, files, clients | (none) |
| `class` / `module` | read-only data parsed once (schemas, big lookup tables) | objects any test mutates |
| `package` | resources shared by one test package | |
| `session` | containers, engines and pools, migrated schemas, compiled assets: expensive and immutable, or reset per test | mutable state with no per-test reset |

A fixture may request only fixtures of the same or a wider scope, otherwise you get `ScopeMismatch`.
Session fixtures under xdist run once per worker, not once per run.

```python
@pytest.fixture
def make_user(session):                     # factory: each test states the data it relies on
    def _make(**overrides) -> User:
        user = User(**{"email": f"u{uuid4().hex[:8]}@example.test", "active": True, **overrides})
        session.add(user)
        session.flush()
        return user
    return _make

@pytest.fixture
def smtp(tmp_path):
    server = FakeSmtp(spool=tmp_path)
    server.start()
    yield server                            # code after yield runs even when the test fails...
    server.stop()                           # ...but not if setup above raised

@pytest.fixture(params=["sqlite", "postgres"], ids=lambda p: f"db={p}")
def dialect(request):
    if request.param == "postgres" and "PG_URL" not in os.environ:
        pytest.skip("PG_URL not set")
    return request.param

@pytest.fixture(autouse=True)               # autouse only for global hygiene
def _isolate_env(monkeypatch):
    for var in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()              # cached settings must not leak between tests
```

- Keep fixture chains shallow (depth 3 or less). A test that needs six fixtures to arrange its data
  wants a builder.
- Return immutable views from wide-scope fixtures (`MappingProxyType`, tuples, frozen dataclasses)
  so a mutation fails loudly instead of leaking into the next test.

## 4. Parametrize

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("90s", 90),
        ("1h", 3600),
        pytest.param("1h30m", 5400, id="compound"),
        pytest.param("-5s", None, id="negative",
                     marks=pytest.mark.xfail(strict=True, raises=ValueError, reason="#412")),
    ],
)
def test_parse_duration(raw, expected):
    assert parse_duration(raw) == expected

@pytest.mark.parametrize("currency", ["EUR", "JPY"])
@pytest.mark.parametrize("amount", [0, 1, 10**9])        # stacked: 3 x 2 = 6 cases
def test_format_money(amount, currency): ...

@pytest.fixture
def account(request, make_account):
    return make_account(tier=request.param)

@pytest.mark.parametrize("account", ["free", "pro"], indirect=True)   # value goes through the fixture
def test_quota(account): ...
```

- Give every case an id (`ids=[...]`, `ids=callable` or `pytest.param(..., id=...)`). `-k compound`
  then selects one case, and failures read as sentences. With `strict_parametrization_ids` a
  duplicate id is an error.
- `xfail(strict=True, raises=...)`: the case must fail with that exception. When the bug is fixed
  the XPASS turns the run red, so the mark gets removed.
- More than about 15 cases, or cases that need comments, belong in a table (a CSV or a list of
  dataclasses) loaded at module level and fed to `parametrize`.

## 5. Built-in helpers

| Helper | Use | Notes |
|---|---|---|
| `tmp_path` / `tmp_path_factory` | per-test / per-session `pathlib.Path` | never write into the repo; retention set by `tmp_path_retention_policy` |
| `monkeypatch.setenv` / `delenv(name, raising=False)` | environment | undone at teardown |
| `monkeypatch.setattr("app.billing.gateway", fake)` | replace the attribute where it is looked up | the string form fails fast on typos |
| `monkeypatch.chdir(tmp_path)` | working directory | |
| `capsys.readouterr().out` | Python-level stdout and stderr | use `capfd` for subprocess or C-level writes |
| `with caplog.at_level(logging.WARNING, logger="app.billing"):` | assert on logs | `caplog.records`, `caplog.messages` |
| `pytest.raises(ValueError, match=r"unknown sku 'X'")` | exceptions | `match` is `re.search`; `pytest.RaisesGroup` for ExceptionGroup |
| `pytest.approx(0.3, rel=1e-9)` | floats, also inside lists, dicts and numpy arrays | defaults: `rel=1e-6`, `abs=1e-12` |
| `pytest.warns(DeprecationWarning, match="use parse_v2")` | warnings | |
| `subtests` fixture | independent failures inside one loop | built in since pytest 9.0 |

## 6. Mocking and fakes

Patch the name where it is looked up, not where it is defined:

| Code under test (app/service.py) | Patch target |
|---|---|
| `from app.clients import pricing` then `pricing.quote()` | `app.service.pricing` |
| `import app.clients` then `app.clients.pricing.quote()` | `app.clients.pricing` |
| `datetime.now()`, `time.time()` | do not patch: freeze time (below) |
| a method on a class used everywhere | `mocker.patch.object(PricingClient, "quote", autospec=True)` |

```python
def test_charge_retries_once_on_timeout(mocker, make_order):
    gw = mocker.patch("app.billing.gateway", autospec=True)    # keeps the real signature
    gw.charge.side_effect = [TimeoutError(), {"id": "ch_1"}]
    order = make_order(total=Decimal("12.50"))
    assert billing.charge_with_retry(order) == "ch_1"
    assert gw.charge.call_count == 2
    gw.charge.assert_called_with(order.id, amount=Decimal("12.50"))
```

Without pytest-mock the same thing is `with unittest.mock.patch("app.billing.gateway", autospec=True) as gw:`.
Without autospec a `Mock` accepts calls with the wrong arguments and misspelt methods (`gw.chrage(...)`),
so the test stays green after the real signature changes. `mocker.create_autospec(Client, instance=True)`
builds a standalone strict double. Before reaching for a mock, prefer an in-memory fake that
implements the same Protocol, injected through the constructor, a fixture or a dependency override.
Fakes test behaviour; mocks test calls.

| Client | Library | Entry point | Unmatched request |
|---|---|---|---|
| httpx (sync and async) | respx | `respx_mock` fixture, `@respx.mock` | raises `AllMockedAssertionError` |
| httpx | pytest-httpx | `httpx_mock` fixture | raises; a registered response never requested fails teardown (`@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)` to allow) |
| requests | responses | `@responses.activate` | `requests.exceptions.ConnectionError` |

```python
def test_rates(respx_mock):
    route = respx_mock.get("https://fx.example.test/rates").mock(
        return_value=httpx.Response(200, json={"EUR": "1.08"}))
    assert fx.rate("EUR") == Decimal("1.08")
    assert route.call_count == 1

def test_token_expiry(time_machine):                 # time-machine: also moves C-level clocks
    time_machine.move_to(datetime(2026, 1, 1, tzinfo=UTC), tick=False)
    token = issue_token(ttl=timedelta(minutes=5))
    time_machine.shift(timedelta(minutes=6))
    assert token.expired()
```

freezegun's `@freeze_time("2026-01-01")` also works, but each freeze walks the loaded modules to swap
`datetime` and `time` references, which gets slow on large suites. time-machine patches the clock at
the C level and is the default for new code.

## 7. Async and database tests

```toml
[tool.pytest]
asyncio_mode = "auto"                         # every async def test/fixture runs without a marker
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"   # one loop for tests and session-scoped async engines
```

- In pytest-asyncio 1.x the `event_loop` fixture is gone. Set loop scope with
  `@pytest.mark.asyncio(loop_scope="session")` or `@pytest_asyncio.fixture(loop_scope=..., scope=...)`.
  A session engine used from function-scoped loops raises "attached to a different loop" (asyncpg).
- What async code must not do (blocking calls, un-awaited tasks) is covered in `python-asyncio`.
- Database isolation, fastest first: a per-test transaction rolled back at teardown (SQLAlchemy
  `join_transaction_mode="create_savepoint"` lets code under test call `commit()`); then truncating
  tables per test; then a fresh database per test (last resort).
- Real engine: a session-scoped testcontainers Postgres (`from testcontainers.postgres import
  PostgresContainer`; recent releases warn and point to `testcontainers.community.postgres`),
  migrated once with `alembic upgrade head`. Under xdist give each worker its own database named
  from `os.environ.get("PYTEST_XDIST_WORKER", "main")`.
- Data: factory_boy (`SQLAlchemyModelFactory` with `sqlalchemy_session_persistence = "flush"`) or
  polyfactory (`class UserFactory(ModelFactory[User]): ...; UserFactory.build(active=False)`) for
  pydantic, dataclass and attrs models.
- pytest-django: `@pytest.mark.django_db` wraps the test in a transaction, while
  `@pytest.mark.django_db(transaction=True)` really commits and flushes the tables afterwards. Use it
  only when other threads or connections must see the data, or when the code relies on
  `transaction.on_commit` (or use the `django_capture_on_commit_callbacks` fixture instead). Other
  knobs: `databases=`, `reset_sequences=`, `serialized_rollback=`, `--reuse-db` locally, and
  `django_assert_num_queries` to catch N+1 queries.

Full fixture code (sync and async rollback, containers, xdist databases, the SQLite SAVEPOINT recipe):
[db-fixtures](references/db-fixtures.md).

## 8. Snapshots and golden files

| Tool | Assert | Update | Stored |
|---|---|---|---|
| syrupy | `assert result == snapshot` | `pytest --snapshot-update` | `__snapshots__/test_x.ambr` (`JSONSnapshotExtension` for .json) |
| inline-snapshot | `assert result == snapshot()` | `pytest --inline-snapshot=create` / `fix` / `review` | the test source itself |

```python
from syrupy.matchers import path_type

def test_order_payload(snapshot, make_order):
    payload = serialize(make_order(lines=2))
    assert payload == snapshot(matcher=path_type({"id": (int,), "created_at": (str,)}))
```

- Review every snapshot diff line by line before committing (`testing-strategy` rule). A blanket
  `--snapshot-update` turns a regression into the new truth.
- Keep snapshots small and deterministic: sorted keys, frozen time, matchers for ids and
  timestamps, no absolute paths. A 2,000-line snapshot nobody reads protects nothing.
- syrupy deletes unused snapshots on `--snapshot-update`. Run the full suite, not `-k`, when updating.

## 9. Speed and isolation

```bash
uv run pytest --durations=20 --durations-min=0.5   # where the time goes (setup is listed separately)
uv run pytest -n auto                              # xdist: one worker per physical core
uv run pytest -n 8 --dist loadgroup                # keep xdist_group-marked tests on one worker
uv run pytest -p randomly                          # header prints: Using --randomly-seed=2450178648
uv run pytest -p randomly --randomly-seed=last     # replay the previous order
uv run pytest -p no:randomly                       # deterministic order while bisecting
uv run pytest --store-durations                    # pytest-split: refresh .test_durations on main
uv run pytest --splits 4 --group 2                 # CI shard 2 of 4 (groups are 1-based)
```

| `--dist` | Sends | Use when |
|---|---|---|
| `load` (default with `-n`) | any test to any free worker | independent tests |
| `loadscope` | whole modules or classes per worker | expensive module or class fixtures |
| `loadfile` | whole files per worker | file-level shared state |
| `loadgroup` | `@pytest.mark.xdist_group(name="s3")` groups to one worker, the rest like `load` | a few tests share a non-shareable resource |
| `worksteal` | rebalances when a worker runs dry | very uneven test durations |

- Order dependence is a bug, not bad luck. With pytest-randomly installed every run shuffles and
  reseeds `random`, Faker and numpy. Reproduce with the printed seed, then find the polluting test
  with `detect-test-pollution --failing-test tests/x.py::test_y --tests tests/`.
- `--pdb` turns xdist off (`-n` is forced to 0). Debug with `-p no:xdist`.

## 10. Debugging flags

| Need | Flags |
|---|---|
| stop at the first failure and debug | `-x --pdb` (`--pdbcls=IPython.terminal.debugger:TerminalPdb`) |
| rerun failures only / failures first | `--lf` / `--ff`; step through with `--sw` (stepwise) |
| full diff and locals | `-vv --showlocals --tb=long` (`--tb=short` or `line` for CI noise) |
| select | `-k "parse and not slow"`, `-m "not integration"`, `path::Class::test[id]` |
| see prints | `-s` (same as `--capture=no`) |
| discovery problems | `--collect-only -q`, then `--trace-config` |
| breakpoint() behaviour | `PYTHONBREAKPOINT=ipdb.set_trace`, `PYTHONBREAKPOINT=0` disables |
| live logs | `-o log_cli=true --log-cli-level=DEBUG` |

Assertion rewriting applies only to test modules and conftests. Helpers that `assert` in other
modules need registering before they are imported, or their failures show a bare `AssertionError`:

```python
# tests/conftest.py (top, before importing the helpers)
import pytest
pytest.register_assert_rewrite("tests.helpers.assertions")
```

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Mock never called, real API hit | patched the defining module (`app.clients.pricing`) instead of the importer | patch `app.service.pricing` (section 6) |
| Test green, production `TypeError` | `Mock` without autospec accepted the old signature | `autospec=True` / `create_autospec`; prefer fakes |
| Passes alone, fails in the suite | session fixture mutated, cached settings, rows left by an earlier test | function scope or immutable views; `cache_clear()` autouse; rollback fixture |
| Fails only under `-n` | shared database, port, bucket or file between workers | per-worker names from `PYTEST_XDIST_WORKER`; `xdist_group` + `loadgroup` |
| Test can never fail | broad `except Exception:` around the assertion swallows `AssertionError`, or `pytest.raises(Exception)` | narrow the exception; `match=` |
| `-m integration` selects nothing | marker typo, `--strict-markers` off | strict config, register markers |
| Warnings scroll by forever | `filterwarnings` ignores by category | `"error"` plus named, ticketed ignores |
| XPASS ignored for months | non-strict xfail | `strict_xfail = true` |
| Snapshot churn on every run | timestamps, dict order, absolute paths | matchers, frozen time, sorted output |
| Async test hangs or "different loop" | session-scoped async resource with function loop scope | align `loop_scope` (section 7) |

## 12. Worked example: 1,200 tests from 14 min to 3 min

Starting point: a FastAPI and SQLAlchemy service with 1,200 tests, run serially, 14:00 wall in CI.
`uv run pytest -p no:randomly --durations=20` showed the setup phase dominating:

| Cost centre | Per test | Tests | Total |
|---|---|---|---|
| `db` fixture: create database plus `alembic upgrade head` (function scope) | 0.40 s | 1,000 | 400 s |
| JSON fixtures (`orders_big.json`, 300 rows inserted per test) | 0.18 s | 600 | 108 s |
| S3-fake tests (moto server per module, fixed port 5000) | | 180 | 120 s |
| collection plus test bodies | | | 212 s |

1. **Strict config first.** Adding `--strict-markers --strict-config` failed collection on 41
   uses of unregistered markers. 29 were `intergration` typos, so the fast CI job's
   `-m "not integration"` had been running those tests all along. The other 12 used `s3`, `slow`
   and `smoke`, none of them registered. Registered the 4 real markers and fixed the typos with `rg -l 'mark\.intergration' tests | xargs perl -pi -e 's/mark\.intergration/mark.integration/g'`.
2. **Consolidate conftests.** Seven directories each defined their own `db` and `client` fixtures
   with drift (two still used `expire_on_commit=True`). Replaced them with one root conftest plus
   `tests/factories.py`. `--setup-show` now shows `SETUP S engine` once and `SETUP F session` per test.
3. **Session Postgres plus per-test rollback.** One Postgres per run (the CI service container;
   testcontainers locally), with each worker's database migrated once (about 6 s) and each test
   inside a SAVEPOINT-joined transaction rolled back at teardown
   ([db-fixtures](references/db-fixtures.md)). Per-test DB cost went from 0.40 s to about 3 ms.
   Wall: 840 s to 450 s.
4. **Factories instead of JSON.** `make_order(lines=2, status="paid")` creates only the 2 or 3 rows
   each test asserts on, and a failing test now shows its data inline. Wall: 450 s to 370 s.
5. **xdist with groups.** `-n 8 --dist loadgroup`. Each worker gets its own database
   (`orders_test_gw3`). The 180 S3 tests share one moto server and bucket namespace, so they carry
   `@pytest.mark.xdist_group(name="s3")` (applied in `tests/s3/conftest.py` via
   `pytest_collection_modifyitems`) and stay on one worker. Wall: 370 s to 180 s. The S3 group
   (about 120 s on its worker) is now the critical path, and collection, worker start-up and
   migrations make up the rest. The next lever is two groups, `s3-a` and `s3-b`, each with its own
   bucket prefix.
6. **Randomise.** `pytest -p randomly` turned up three order-dependent tests:
   `test_discount_flag` read an `lru_cache`d `get_settings()` primed by an earlier test (fixed with
   the autouse `cache_clear()` from section 3); `test_currency_default` mutated a session `config`
   dict (now a `MappingProxyType`); `test_export_lists_orders` counted rows an earlier test had
   committed before rollback existed (now builds its own with `make_order`). Each was reproduced
   with `--randomly-seed=<seed>` and isolated with `detect-test-pollution`.

| Metric | Before | After |
|---|---|---|
| CI wall time | 14:00 | 3:00 |
| per-test DB setup | 0.40 s | ~3 ms |
| unregistered markers | 41 | 0 |
| order-dependent tests | unknown | 3 found, 3 fixed |
| CI command | `pytest` | `uv run pytest -n 8 --dist loadgroup -p randomly --durations=20` |

Related: `testing-strategy`, `python-asyncio`, `fastapi-pydantic-services`, `python-uv-packaging`, `python-typing`, `python-performance-profiling`, `ci-pipelines`, `debugging-method`, hub `coding-general`
