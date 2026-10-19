---
name: fastapi-pydantic-services
description: "Python HTTP services with FastAPI and pydantic v2: layout separating schemas, ORM models and services; validators, strictness and settings; Annotated dependency injection; lifespan-managed clients; async vs sync endpoints; SQLAlchemy 2.0 async sessions; problem+json error handlers; background work; testing with httpx ASGITransport and dependency overrides; deployment flags. Load when building, reviewing or debugging a FastAPI service."
when_to_use: "Files importing fastapi, pydantic, pydantic_settings or sqlalchemy.ext.asyncio; errors like MissingGreenlet, 'greenlet_spawn has not been called', 422 bodies nobody expected, 'on_event is deprecated', 'attached to a different loop'; slow p99 on async endpoints; password_hash or other internal fields in responses; adding endpoints, settings, auth dependencies, tests or deployment config."
---

# FastAPI and pydantic services

Baseline: FastAPI 0.14x (checked on 0.148) on Starlette 1.x, pydantic 2.x (2.14), pydantic-settings
2.x, SQLAlchemy 2.x (2.1), httpx 0.28, uvicorn 0.5x. FastAPI is still 0.x, so a minor bump can change
behaviour: read the release notes before upgrading. Event-loop rules (no blocking calls in
`async def`, task lifetimes, cancellation) live in `python-asyncio`. URL, status-code and pagination
design live in `api-contract-design`.

Complete, tested example service: [orders-example](references/orders-example.md)

## 1. Layout

```
app/
├── main.py              # create_app(): lifespan, routers, exception handlers. No business logic.
├── settings.py          # Settings(BaseSettings) + cached get_settings()
├── deps.py              # SessionDep, CurrentUser, PricesDep: Annotated aliases
├── api/routers/orders.py    # thin: parse, call the service, map the result to a schema
├── schemas/order.py     # pydantic I/O models: OrderCreate, OrderUpdate, OrderRead
├── models/order.py      # SQLAlchemy ORM
└── services/orders.py   # business logic: session + ports in, domain objects or errors out
```

- `services/` and `models/` never import fastapi or starlette. Check with
  `rg -n 'fastapi|starlette' app/services app/models`, which must print nothing. Services are then
  testable without HTTP and reusable from workers and CLIs.
- Routers hold no queries and no business rules. Schemas never import ORM models.
- Build the app in `create_app()`, so each test gets a fresh app and its own `dependency_overrides`.

## 2. pydantic v2 essentials

```python
Sku = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9-]+$")]

class OrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sku: Sku                                         # " SKU-2 " is stripped before the pattern check
    qty: Annotated[int, Field(gt=0, le=1000)]

class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")        # unknown keys are 422, not silently dropped
    customer_id: Annotated[int, Field(gt=0)]
    lines: Annotated[list[OrderLineIn], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")                   # cross-field rule, runs on the built model
    def unique_skus(self) -> Self:
        if len({l.sku for l in self.lines}) != len(self.lines):
            raise ValueError("each sku may appear once per order")
        return self

class OrderUpdate(BaseModel):                        # PATCH: every field optional
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "paid", "cancelled"] | None = None
    note: Annotated[str, Field(max_length=500)] | None = None

    @field_validator("note")
    @classmethod
    def no_blank_note(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("note must not be blank")
        return v

class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # OrderRead.model_validate(orm_order)
    id: int
    status: str
    total: Decimal
    lines: list[OrderLineRead]

SkuList = TypeAdapter(list[Sku])                     # validate non-model types; build once, module level
```

- PATCH: `body.model_dump(exclude_unset=True)` holds only the fields the client sent (an explicit
  `null` included), so "not sent" and "set to null" stay distinct. Use `mode="json"` when that dict
  is forwarded as JSON (outbox payload, downstream API). Keep the default Python mode when you
  `setattr` it onto an ORM object, so Decimal stays Decimal.
- Separate Create, Update and Read schemas. One model for all three either leaks server-owned
  fields (`id`, `status`) into input or makes required output fields optional.
- Strictness: prefer per-field strictness (`Annotated[int, Field(strict=True)]`, `StrictBool`).
  `ConfigDict(strict=True)` on a FastAPI body model rejects `"2026-10-19"` for `date` and `"1.10"` for
  `Decimal` with 422, because FastAPI validates the already-parsed dict in Python mode.
  `model_validate_json` accepts them; the request path does not.
- Mutable defaults: pydantic v2 copies `tags: list[str] = []` per instance, but write
  `Field(default_factory=list)` anyway so it reads correctly next to dataclasses and SQLAlchemy.

| pydantic v1 | v2 |
|---|---|
| `.dict()`, `.json()` | `.model_dump()`, `.model_dump_json()` |
| `parse_obj`, `parse_raw`, `parse_obj_as` | `model_validate`, `model_validate_json`, `TypeAdapter(T).validate_python` |
| `@validator`, `@root_validator` | `@field_validator` (+ `@classmethod`), `@model_validator(mode=...)` |
| `class Config: orm_mode = True` | `model_config = ConfigDict(from_attributes=True)` |
| `.copy(update=...)`, `.schema()`, `update_forward_refs()` | `.model_copy(update=...)`, `.model_json_schema()`, `model_rebuild()` |
| `Field(regex=...)`, `min_items`, `const` | `pattern=`, `min_length`, `Literal[...]` |
| `BaseSettings` from pydantic | `pydantic_settings.BaseSettings` (separate package) |

## 3. Settings

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORDERS_", env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://orders@localhost:5432/orders"
    db_pool_size: int = 10
    db_max_overflow: int = 5
    pricing_url: str = "http://pricing.internal"
    pricing_token: SecretStr = SecretStr("")        # repr shows '**********'

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- Real environment variables override `.env`. Keep `.env` for local development only, out of git
  and out of images. Production config comes from the platform's env or secret store.
- Call `.get_secret_value()` only at the edge where the secret is used (a header, a DSN), never in
  logs or responses.
- Tests: `app.dependency_overrides[get_settings] = lambda: Settings(pricing_url="http://fake")` for
  injected uses. Code that calls `get_settings()` directly (the lifespan) needs `monkeypatch.setenv`
  plus `get_settings.cache_clear()`.

## 4. Dependency injection

```python
async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:   # one session per request
        yield session

SessionDep = Annotated[AsyncSession, Depends(get_session)]

async def current_user(token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep) -> User:
    user = await auth.user_from_token(session, token)
    if user is None:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    return user

CurrentUser = Annotated[User, Depends(current_user)]

def require(scope: str):
    async def check(user: CurrentUser) -> User:
        if scope not in user.scopes:
            raise HTTPException(403)
        return user
    return Depends(check)

@router.delete("/{order_id}", status_code=204, dependencies=[require("orders:write")])
async def cancel(order_id: int, session: SessionDep, user: CurrentUser) -> None: ...
```

- A dependency runs once per request even when several dependants ask for it (`use_cache=True`).
- Code after `yield` runs after the response is sent (`scope="request"`, the default for yield
  dependencies). `Depends(dep, scope="function")` closes it before the response goes out, which is
  what you want for a lock or a transaction that must finish first. In an `except` block inside a
  yield dependency, re-raise, or the client gets a 500 with nothing in the logs.
- Tests swap any dependency with `app.dependency_overrides[get_session] = lambda: test_session`.
- No module-level clients (`client = httpx.AsyncClient()` at import time). They are created before
  any event loop, shared across tests and never closed. Lifespan owns them.

## 5. Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    engine = create_async_engine(s.database_url, pool_size=s.db_pool_size,
                                 max_overflow=s.db_max_overflow, pool_pre_ping=True, pool_recycle=1800)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    app.state.http = httpx.AsyncClient(base_url=s.pricing_url, timeout=httpx.Timeout(2.0, connect=0.5),
                                       limits=httpx.Limits(max_connections=100, max_keepalive_connections=20))
    try:
        yield
    finally:
        await app.state.http.aclose()
        await engine.dispose()

app = FastAPI(lifespan=lifespan)
```

`@app.on_event("startup")` emits "on_event is deprecated, use lifespan event handlers instead", and
Starlette 1.x no longer accepts `on_startup`/`on_shutdown`. The lifespan runs once per worker
process: four workers make four pools and four clients (see the sizing formula in section 7).

## 6. Async vs sync endpoints

| Endpoint body | Declare as | What happens |
|---|---|---|
| awaits async libraries only (asyncpg, httpx.AsyncClient) | `async def` | runs on the event loop |
| calls blocking libraries (requests, psycopg2, boto3, big file I/O) | plain `def` | runs in the threadpool: anyio's default limiter, 40 threads |
| mostly async with one blocking call | `async def` + `await run_in_threadpool(fn, ...)` | offloads only the blocking part |
| CPU work over ~10 ms per request | process pool (`loop.run_in_executor(pool, fn)`) or a job queue | the GIL stalls both the loop and the threads |

- One blocking call inside `async def` stalls every request on that worker. The worked example
  shows what it does to p99.
- Threadpool capacity by Little's law: throughput <= threads / time held. 40 threads each holding
  200 ms cap a worker at 200 req/s. Raise it in the lifespan with
  `anyio.to_thread.current_default_thread_limiter().total_tokens = 100`, and only after checking that
  the downstream (the DB pool) can take it. Sync dependencies use the same pool.

## 7. SQLAlchemy 2.0 async

- Engine: `create_async_engine(url, pool_size=10, max_overflow=5, pool_pre_ping=True, pool_recycle=1800)`.
  Sizing rule: `replicas x workers x (pool_size + max_overflow) <= max_connections - reserved`.
  Example: 3 pods x 4 workers x (10 + 5) = 180 <= 200 - 20 kept for admin, migrations and cron. Size
  `pool_size` by Little's law: 300 req/s x 20 ms of connection hold time = 6 busy connections on
  average, so 10 leaves headroom. Past that, put PgBouncer in front and check the asyncpg
  prepared-statement settings it needs (SQLAlchemy asyncpg dialect docs).
- `async_sessionmaker(engine, expire_on_commit=False)`, one session per request (the dependency
  above). With the default `expire_on_commit=True` every attribute access after `commit()` triggers a
  lazy refresh, which in async code fails with `MissingGreenlet: greenlet_spawn has not been called`.
- Eager-load what the response needs: `selectinload(Order.lines)` for collections, `joinedload` for
  many-to-one. Set `lazy="raise"` on relationships so a hidden lazy load fails in tests instead of in
  production. For a one-off, use the `AsyncAttrs` mixin and `await order.awaitable_attrs.lines`.
- 2.0 style only: `select(Order).where(...)`, `await session.scalars(stmt)`,
  `await session.scalar(stmt)`, `await session.get(Order, 42)`,
  `await session.execute(update(Order).where(...).values(...))`. No `session.query`.
- Migrations: Alembic (`alembic init -t async migrations`, `alembic revision --autogenerate`, review
  the script, then `alembic upgrade head` as a release step, never inside the lifespan of N workers
  racing each other). Expand and contract for live tables: `zero-downtime-migrations`. Query plans:
  `sql-query-tuning`.

## 8. Errors and responses

```python
class DomainError(Exception):                 # services raise these; no HTTP knowledge inside
    status, type_uri, title = 400, "about:blank", "Bad request"

class NotFound(DomainError):
    status, type_uri, title = 404, "https://errors.example.com/not-found", "Resource not found"

@app.exception_handler(DomainError)
async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, media_type="application/problem+json",
                        content={"type": exc.type_uri, "title": exc.title, "status": exc.status,
                                 "detail": str(exc), "instance": request.url.path})
```

- RFC 9457 problem details (`type`, `title`, `status`, `detail`, `instance`, plus extension members
  such as `errors`). Install a second handler for `RequestValidationError` so 422s share the shape.
  Error catalogue and status-code policy: `api-contract-design`.
- Every endpoint declares its output with a return annotation (`-> OrderRead`) or `response_model=`.
  Returning an ORM object without one serialises every loaded column: a `User` row came back with
  `"password_hash":"argon2$..."` in a local check, and with `-> UserRead` it did not.
- Explicit codes: `status_code=201` (plus `Location`) for creates, 204 for deletes, 409 for conflicts.
- `HTTPException` only in the API layer (routers, auth dependencies). Services raise domain errors.

## 9. Background work

| Need | Use | Guarantees |
|---|---|---|
| small, loss-tolerant work after the response (audit log line, cache warm) | `BackgroundTasks.add_task(fn, *args)` | same process; lost on crash, deploy or OOM; delays worker shutdown |
| anything that must happen (emails, payments, webhooks, reports) | a queue: arq (asyncio + Redis), Dramatiq, Celery, RQ | retries, visibility, separate scaling |
| must commit atomically with the DB write | transactional outbox table + relay worker (`SELECT ... FOR UPDATE SKIP LOCKED`) | at-least-once delivery |

Jobs carry an idempotency key (order id plus action) and consumers deduplicate on it, because every
real queue redelivers. API-level `Idempotency-Key` handling and retry policies: `resilience-patterns`.

## 10. Testing

```python
@pytest.fixture
async def client(session, prices) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session    # SAVEPOINT-joined, rolled back
    app.dependency_overrides[get_prices] = lambda: prices      # in-memory fake of the price port
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

async def test_unknown_sku_is_problem_json(client):
    r = await client.post("/orders", json={"customer_id": 7, "lines": [{"sku": "NOPE", "qty": 1}]})
    assert r.status_code == 422
    assert r.headers["content-type"] == "application/problem+json"
```

- `ASGITransport` does not run the lifespan. Either override every lifespan-owned dependency (above)
  or wrap the app: `async with LifespanManager(app) as m:` (asgi-lifespan), then
  `ASGITransport(app=m.app)`. Starlette's sync `TestClient` runs it when used as `with TestClient(app):`.
- Per-test rollback session and async loop scopes: `pytest-patterns`. Assert on behaviour (status,
  body, DB state), not on which service functions were called.
- Contract fuzzing from the OpenAPI schema with Schemathesis (4.x API):

```python
schema = schemathesis.openapi.from_asgi("/openapi.json", create_app())

@schema.parametrize()
def test_api_contract(case):
    case.call_and_validate()           # 5xx, schema-violating responses, wrong content types
```

  Against a running server: `schemathesis run http://127.0.0.1:8000/openapi.json --checks all`.

## 11. Deploy

```bash
fastapi run app/main.py --workers 4                            # 0.0.0.0:8000, proxy headers on by default
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 \
  --proxy-headers --forwarded-allow-ips 10.0.0.0/8 \
  --timeout-graceful-shutdown 20 --limit-max-requests 50000 --limit-max-requests-jitter 5000 --no-access-log
gunicorn app.main:app -k uvicorn_worker.UvicornWorker -w 4 -b 0.0.0.0:8000 --graceful-timeout 20
```

| Setting | Rule |
|---|---|
| workers | one per core on a VM; in Kubernetes often 1 to 2 per pod, scaling pods instead. Each worker is one event loop with its own pool |
| `--forwarded-allow-ips` | the proxy's addresses or CIDR. uvicorn trusts only `127.0.0.1,::1` by default, so behind an ingress without it you get wrong client IPs and `http://` redirect URLs |
| gunicorn worker class | `uvicorn_worker.UvicornWorker` from the `uvicorn-worker` package; `uvicorn.workers` is deprecated |
| `/healthz` (liveness) | process alive, touches nothing. A DB outage must not restart every pod |
| `/readyz` (readiness) | `SELECT 1` with a 1 s timeout; 503 takes the pod out of rotation |
| shutdown | SIGTERM, stop accepting, drain in-flight requests (`--timeout-graceful-shutdown`), then lifespan exit. Kubernetes `terminationGracePeriodSeconds` > preStop sleep + drain time |
| `--limit-max-requests` (+ jitter) | recycles workers to contain slow leaks while you find them (`python-performance-profiling`) |

Tracing: `FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")` from
`opentelemetry-instrumentation-fastapi`, plus the SQLAlchemy and httpx instrumentors. Span naming,
metrics and log correlation: `observability-instrumentation`. Images: `container-images`.

## 12. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| p99 explodes under load, CPU idle | sync driver or `requests` inside `async def` | async client, or `def` endpoint, or `run_in_threadpool` |
| TIME_WAIT pile-up, TLS handshakes on every call | `async with httpx.AsyncClient()` per request | one pooled client from the lifespan |
| `password_hash` in a response | ORM object returned with no response model | return annotation or `response_model` |
| one row's JSON column changes another's | SQLAlchemy `default={}` shares one dict across rows (checked: `r1.meta is r2.meta`) | `default=dict`; `Field(default_factory=list)` in schemas |
| `GET /orders` times out as data grows | unbounded list endpoint | `limit: Annotated[int, Query(ge=1, le=100)]` + keyset cursor |
| `MissingGreenlet` | lazy load or expired attribute in async code | `expire_on_commit=False`, `selectinload`, `lazy="raise"` |
| valid dates and decimals rejected with 422 | model-wide `strict=True` on a body model | per-field strictness |
| tests leak rows into each other | real commits in tests | SAVEPOINT rollback fixture (`pytest-patterns`) |
| "attached to a different loop" in tests | module-level client or engine reused across loops | lifespan-owned resources; one loop scope |
| unknown JSON keys silently ignored | default `extra="ignore"` | `extra="forbid"` on input schemas |

## 13. Worked example: orders service and a 230 ms p99

The [orders-example](references/orders-example.md) reference has the complete code and 9 passing
tests. In outline:

- **Schemas**: `OrderCreate` (forbid extras, positive ids, 1 to 100 unique lines) and `OrderRead`
  (`from_attributes=True`) as in section 2, plus `OrderPage(items: list[OrderRead], next_cursor: int | None)`.
- **Router**: `SessionDep` and `PricesDep` only, and it returns schemas:

```python
@router.get("")
async def list_orders(session: SessionDep, customer_id: Annotated[int, Query(gt=0)],
                      limit: Annotated[int, Query(ge=1, le=100)] = 50,
                      after: Annotated[int | None, Query(gt=0)] = None) -> OrderPage:
    items, cursor = await svc.list_orders(session, customer_id, limit, after)
    return OrderPage(items=[OrderRead.model_validate(o) for o in items], next_cursor=cursor)
```

- **Service** (keyset pagination, eager lines):

```python
stmt = (select(Order).options(selectinload(Order.lines))
        .where(Order.customer_id == customer_id).order_by(Order.id).limit(limit + 1))
if after is not None:
    stmt = stmt.where(Order.id > after)
rows = list(await session.scalars(stmt))
items = rows[:limit]
return items, (items[-1].id if len(rows) > limit else None)
```

- **Errors**: `UnknownSku` (422) and `NotFound` (404) leave as `application/problem+json`, and so do
  validation errors through the `RequestValidationError` handler.
- **Tests**: the `client` fixture from section 10. One test creates 5 orders and pages through them
  2 at a time: the three pages must return exactly the created ids in order, with a final
  `next_cursor` of `None`. Another test asserts that the same customer has no orders, which proves
  the rollback. The suite also passes under `-p randomly` and `-n 2`.

**The incident.** The first version priced lines with `requests.get(f"{PRICING}/v1/prices", ...)`
inside `async def create_order`. The pricing call took about 25 ms. While a worker waited on it the
event loop was blocked, so concurrent requests queued behind each other. Production p99 at peak was
230 ms against a 50 ms SLO, with CPU at 15%. `py-spy dump --pid <worker>` showed `MainThread` inside
`requests/adapters.py:send`. The fix was the lifespan-owned `httpx.AsyncClient` behind the
`PricesDep` port (section 5), which awaits the call and frees the loop. p99 dropped to 35 ms with
the same pods.

Local reproduction (one uvicorn worker, a 25 ms stub upstream, 600 requests after 50 warm-up):

| Concurrent clients | blocking `requests` p50 / p99 | `httpx.AsyncClient` p50 / p99 |
|---|---|---|
| 4 | 89 / 188 ms | 28 / 29 ms |
| 8 | 193 / 392 ms | 29 / 32 ms |
| 10 | 256 / 546 ms | 29 / 34 ms |

The blocking version's latency grows linearly with concurrency (each request waits for everyone
ahead of it), while the async version stays at the upstream's 25 ms plus overhead. That linear
growth is the signature to look for in latency-versus-load graphs.

Related: `python-asyncio`, `pytest-patterns`, `python-typing`, `python-uv-packaging`, `python-performance-profiling`, `api-contract-design`, `sql-query-tuning`, `zero-downtime-migrations`, `resilience-patterns`, `observability-instrumentation`, `container-images`, hub `coding-general`
