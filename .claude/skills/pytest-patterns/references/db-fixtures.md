# Database and async fixtures

Fixture code for SQLAlchemy 2.x (checked on 2.1) with pytest 9 and pytest-asyncio 1.x. The rollback
pattern was run against SQLite with the recipe in section 5. Against Postgres it needs no recipe.

## 1. Where the database comes from

```python
# tests/conftest.py
import os
import pytest
from sqlalchemy import create_engine, make_url

@pytest.fixture(scope="session")
def pg_base_url() -> str:
    """CI provides a service container; locally start one with testcontainers."""
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    # testcontainers >= 4.15 warns that this module moved to testcontainers.community.postgres
    from testcontainers.postgres import PostgresContainer
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()          # postgresql+psycopg://test:test@127.0.0.1:<port>/test
```

`driver="asyncpg"` gives a `postgresql+asyncpg://` URL for async engines. Pin the image tag to the
production major version: testing on `latest` hides behaviour differences between Postgres versions.

## 2. One database per xdist worker, migrated once

```python
@pytest.fixture(scope="session")
def db_url(pg_base_url) -> str:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")      # gw0, gw1, ... under xdist
    base = make_url(pg_base_url)
    name = f"{base.database}_{worker}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    admin.dispose()
    url = base.set(database=name).render_as_string(hide_password=False)

    from alembic import command
    from alembic.config import Config
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)   # env.py must read this, not settings
    command.upgrade(cfg, "head")                 # the real migrations, not create_all()
    return url
```

Running the real migrations catches migration bugs that `Base.metadata.create_all()` hides. Many
`env.py` files read the URL from application settings and ignore `sqlalchemy.url`; make env.py
prefer `config.get_main_option("sqlalchemy.url")` when it is set.

## 3. Per-test transaction rollback (sync)

```python
from sqlalchemy.orm import Session

@pytest.fixture(scope="session")
def engine(db_url):
    eng = create_engine(db_url, pool_pre_ping=True)
    yield eng
    eng.dispose()

@pytest.fixture
def session(engine):
    with engine.connect() as conn:
        outer = conn.begin()
        s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        try:
            yield s
        finally:
            s.close()
            outer.rollback()                   # nothing the test wrote survives
```

`join_transaction_mode="create_savepoint"` makes the code under test's `session.commit()` release a
SAVEPOINT instead of committing the outer transaction. Limits: code that opens its own connection
(a second engine, a background thread, `LISTEN/NOTIFY`, `CREATE INDEX CONCURRENTLY`) does not see the
uncommitted data. Those tests need truncation (`TRUNCATE ... RESTART IDENTITY CASCADE`) instead.

## 4. Per-test transaction rollback (async)

```toml
[tool.pytest]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
```

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

@pytest.fixture(scope="session")
async def async_engine(db_url):
    eng = create_async_engine(db_url.replace("+psycopg", "+asyncpg"))
    yield eng
    await eng.dispose()

@pytest.fixture
async def session(async_engine):
    async with async_engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(bind=conn, expire_on_commit=False,
                         join_transaction_mode="create_savepoint")
        try:
            yield s
        finally:
            await s.close()
            await outer.rollback()
```

Both loop-scope keys set to `session` keep the engine's connections and the tests on one event loop.
A session-scoped async engine with function-scoped test loops fails with asyncpg errors such as
"attached to a different loop". For FastAPI, override the app's session dependency with this
fixture (see `fastapi-pydantic-services`).

## 5. SQLite: make SAVEPOINT nesting work

The pysqlite and aiosqlite drivers manage transactions themselves, and by default the rollback
pattern silently leaks data (the outer `BEGIN` is never emitted). Hand control to SQLAlchemy:

```python
from sqlalchemy import event

def sqlite_savepoint_fix(sync_engine):
    @event.listens_for(sync_engine, "connect")
    def _no_driver_begin(dbapi_conn, _rec):
        dbapi_conn.isolation_level = None

    @event.listens_for(sync_engine, "begin")
    def _emit_begin(conn):
        conn.exec_driver_sql("BEGIN")

# sync: sqlite_savepoint_fix(engine); async: sqlite_savepoint_fix(async_engine.sync_engine)
```

Use SQLite only for unit-level repository tests. Constraint, JSON, locking and timezone behaviour
differ from Postgres, so integration tests use the real engine.

## 6. Factories bound to the test session

```python
import factory

_current: dict = {}

class UserFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = User
        sqlalchemy_session_factory = lambda: _current["session"]
        sqlalchemy_session_persistence = "flush"     # ids assigned, nothing committed
    email = factory.Sequence(lambda n: f"user{n}@example.test")
    active = True

@pytest.fixture(autouse=True)
def _bind_factories(session):
    _current["session"] = session
```

`UserFactory.create_batch(3)` then works inside the rolled-back transaction. With polyfactory, use
`build()` for pydantic and dataclass models and persist them yourself, or use its SQLAlchemy
factory (`polyfactory.factories.sqlalchemy_factory`) when you want it to manage the session.

## 7. pytest-django specifics

```python
@pytest.mark.django_db
def test_paid_orders(django_assert_num_queries, order_factory):
    order_factory.create_batch(3, status="paid")
    with django_assert_num_queries(1):             # guards against N+1 regressions
        assert len(list(Order.objects.paid().select_related("customer"))) == 3

@pytest.mark.django_db(transaction=True)           # real commits, tables flushed afterwards
def test_worker_sees_order(order_factory):
    ...
```

- `django_db` options: `transaction`, `reset_sequences`, `databases`, `serialized_rollback`,
  `available_apps`.
- `transaction=True` is for code that must really commit: other threads or connections reading the
  data, or behaviour that depends on `transaction.on_commit` (alternatively, use the
  `django_capture_on_commit_callbacks` fixture).
- `--reuse-db` keeps the test database between local runs; `--create-db` forces a rebuild after
  migrations change. pytest-django adds a per-xdist-worker suffix to the test database name by itself.
