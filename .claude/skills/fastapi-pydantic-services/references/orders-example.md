# Orders service: complete worked example

Every file below was run: 9 tests passing serially, under `-p randomly` and under `-n 2` (pytest 9.1,
FastAPI 0.148, pydantic 2.14, SQLAlchemy 2.1, httpx 0.28, pytest-asyncio 1.4). The tests ran against
SQLite via aiosqlite, using the SAVEPOINT recipe in `tests/conftest.py`. Point `TEST_DATABASE_URL` at
Postgres (`postgresql+asyncpg://...`) for the real engine. A smoke run through the real lifespan
(asgi-lifespan `LifespanManager` plus respx for the pricing API) returned 201 and `/readyz` 200.

Layout:

```
app/
  main.py  settings.py  deps.py
  api/routers/orders.py
  schemas/order.py  models/order.py
  services/orders.py  services/errors.py
tests/
  conftest.py  test_orders.py
```

Dependencies: `uv add 'fastapi[standard]' pydantic-settings 'sqlalchemy[asyncio]' asyncpg httpx` and
`uv add --dev pytest pytest-asyncio aiosqlite asgi-lifespan respx`. Run with `uv run pytest`.

## `pyproject.toml`

Test configuration (pytest 9 native TOML).

```toml
[project]
name = "orders"
version = "0"

[tool.pytest]
addopts = ["-ra", "--strict-markers", "--strict-config"]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
filterwarnings = ["error"]
```

## `app/settings.py`

Settings: one cached instance, secrets as SecretStr.

```python
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORDERS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://orders@localhost:5432/orders"
    db_pool_size: int = 10
    db_max_overflow: int = 5
    pricing_url: str = "http://pricing.internal"
    pricing_token: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

## `app/models/order.py`

ORM models (SQLAlchemy 2.x typed declarative).

```python
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    qty: Mapped[int]
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    order: Mapped[Order] = relationship(back_populates="lines")
```

## `app/schemas/order.py`

I/O schemas: separate Create and Read models, strict input, ORM-readable output.

```python
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sku = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9-]+$")]


class OrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sku: Sku
    qty: Annotated[int, Field(gt=0, le=1000)]


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: Annotated[int, Field(gt=0)]
    lines: Annotated[list[OrderLineIn], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def unique_skus(self) -> Self:
        skus = [line.sku for line in self.lines]
        if len(skus) != len(set(skus)):
            raise ValueError("each sku may appear once per order")
        return self


class OrderLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sku: str
    qty: int
    unit_price: Decimal


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    status: str
    total: Decimal
    lines: list[OrderLineRead]


class OrderPage(BaseModel):
    items: list[OrderRead]
    next_cursor: int | None
```

## `app/services/errors.py`

Domain errors carry their problem+json metadata; no FastAPI import.

```python
class DomainError(Exception):
    status = 400
    type_uri = "about:blank"
    title = "Bad request"


class NotFound(DomainError):
    status, type_uri, title = 404, "https://errors.example.com/not-found", "Resource not found"


class UnknownSku(DomainError):
    status, type_uri, title = 422, "https://errors.example.com/unknown-sku", "Unknown SKU"
```

## `app/services/orders.py`

Business logic: takes a session and a price port, raises domain errors, eager-loads lines.

```python
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.order import Order, OrderLine
from app.schemas.order import OrderCreate
from app.services.errors import NotFound, UnknownSku


class PriceSource(Protocol):
    async def quote(self, skus: list[str]) -> dict[str, Decimal]: ...


async def create_order(session: AsyncSession, prices: PriceSource, data: OrderCreate) -> Order:
    quoted = await prices.quote([line.sku for line in data.lines])
    missing = [line.sku for line in data.lines if line.sku not in quoted]
    if missing:
        raise UnknownSku(f"unknown sku(s): {', '.join(missing)}")
    lines = [OrderLine(sku=l.sku, qty=l.qty, unit_price=quoted[l.sku]) for l in data.lines]
    order = Order(
        customer_id=data.customer_id,
        total=sum((l.unit_price * l.qty for l in lines), Decimal(0)),
        lines=lines,
    )
    session.add(order)
    await session.commit()
    return await get_order(session, order.id)


async def get_order(session: AsyncSession, order_id: int) -> Order:
    order = await session.scalar(
        select(Order).options(selectinload(Order.lines)).where(Order.id == order_id)
    )
    if order is None:
        raise NotFound(f"order {order_id} does not exist")
    return order


async def list_orders(
    session: AsyncSession, customer_id: int, limit: int, after: int | None
) -> tuple[list[Order], int | None]:
    stmt = (
        select(Order)
        .options(selectinload(Order.lines))
        .where(Order.customer_id == customer_id)
        .order_by(Order.id)
        .limit(limit + 1)
    )
    if after is not None:
        stmt = stmt.where(Order.id > after)
    rows = list(await session.scalars(stmt))
    items = rows[:limit]
    return items, (items[-1].id if len(rows) > limit else None)
```

## `app/deps.py`

Dependencies and Annotated aliases; the price source wraps the lifespan-owned client.

```python
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Annotated

import httpx
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import Settings, get_settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


class HttpPriceSource:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def quote(self, skus: list[str]) -> dict[str, Decimal]:
        r = await self.client.get("/v1/prices", params={"sku": skus})
        r.raise_for_status()
        return {k: Decimal(v) for k, v in r.json().items()}


def get_prices(request: Request) -> HttpPriceSource:
    return HttpPriceSource(request.app.state.http)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
PricesDep = Annotated[HttpPriceSource, Depends(get_prices)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
```

## `app/api/routers/orders.py`

Thin router: validate, call the service, map to the Read schema.

```python
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.deps import PricesDep, SessionDep
from app.schemas.order import OrderCreate, OrderPage, OrderRead
from app.services import orders as svc

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_order(body: OrderCreate, session: SessionDep, prices: PricesDep) -> OrderRead:
    return OrderRead.model_validate(await svc.create_order(session, prices, body))


@router.get("/{order_id}")
async def read_order(order_id: int, session: SessionDep) -> OrderRead:
    return OrderRead.model_validate(await svc.get_order(session, order_id))


@router.get("")
async def list_orders(
    session: SessionDep,
    customer_id: Annotated[int, Query(gt=0)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: Annotated[int | None, Query(gt=0)] = None,
) -> OrderPage:
    items, cursor = await svc.list_orders(session, customer_id, limit, after)
    return OrderPage(items=[OrderRead.model_validate(o) for o in items], next_cursor=cursor)
```

## `app/main.py`

App factory, lifespan, problem+json handlers, health endpoints.

```python
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routers import orders
from app.deps import SessionDep
from app.services.errors import DomainError
from app.settings import get_settings

PROBLEM = "application/problem+json"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    engine = create_async_engine(
        s.database_url, pool_size=s.db_pool_size, max_overflow=s.db_max_overflow,
        pool_pre_ping=True, pool_recycle=1800,
    )
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    app.state.http = httpx.AsyncClient(
        base_url=s.pricing_url,
        headers={"Authorization": f"Bearer {s.pricing_token.get_secret_value()}"},
        timeout=httpx.Timeout(2.0, connect=0.5),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    try:
        yield
    finally:
        await app.state.http.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="orders", lifespan=lifespan)
    app.include_router(orders.router)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, media_type=PROBLEM,
            content={"type": exc.type_uri, "title": exc.title, "status": exc.status,
                     "detail": str(exc), "instance": request.url.path},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422, media_type=PROBLEM,
            content={"type": "https://errors.example.com/validation", "title": "Invalid request",
                     "status": 422, "instance": request.url.path,
                     "errors": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]},
        )

    @app.get("/healthz", include_in_schema=False)          # liveness: never touches dependencies
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)           # readiness: can we serve traffic?
    async def readyz(session: SessionDep) -> JSONResponse:
        try:
            async with asyncio.timeout(1.0):
                await session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "db unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return app


app = create_app()
```

## `tests/conftest.py`

Per-test SAVEPOINT rollback, fake price source, ASGITransport client with dependency overrides.

```python
import os
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.deps import get_prices, get_session
from app.main import create_app
from app.models.order import Base


@pytest.fixture(scope="session")
async def engine():
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")        # gw0, gw1, ... under xdist
    # CI: TEST_DATABASE_URL=postgresql+asyncpg://app:pw@db:5432/orders_test
    base = make_url(os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///./test.db"))
    if base.get_backend_name() == "sqlite":
        url = base.set(database=f"./test_{worker}.db")
    else:  # one database per worker, created and migrated before the run
        url = base.set(database=f"{base.database}_{worker}")
    eng = create_async_engine(url)
    if eng.dialect.name == "sqlite":   # aiosqlite needs an explicit BEGIN for SAVEPOINT nesting
        @event.listens_for(eng.sync_engine, "connect")
        def _no_driver_begin(dbapi_conn, _rec):
            dbapi_conn.isolation_level = None

        @event.listens_for(eng.sync_engine, "begin")
        def _emit_begin(conn):
            conn.exec_driver_sql("BEGIN")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(bind=conn, expire_on_commit=False,
                         join_transaction_mode="create_savepoint")
        try:
            yield s
        finally:
            await s.close()
            await outer.rollback()


class FakePrices:
    def __init__(self, table: dict[str, Decimal]) -> None:
        self.table, self.calls = table, []

    async def quote(self, skus: list[str]) -> dict[str, Decimal]:
        self.calls.append(skus)
        return {k: v for k, v in self.table.items() if k in skus}


@pytest.fixture
def prices() -> FakePrices:
    return FakePrices({"SKU-1": Decimal("9.99"), "SKU-2": Decimal("100.00")})


@pytest.fixture
async def client(session, prices) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_prices] = lambda: prices
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
```

## `tests/test_orders.py`

Behaviour tests through HTTP.

```python
import pytest


async def test_create_then_read(client):
    r = await client.post("/orders", json={"customer_id": 7, "lines": [
        {"sku": "SKU-1", "qty": 2}, {"sku": " SKU-2 ", "qty": 1}]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total"] == "119.98"
    assert {l["sku"] for l in body["lines"]} == {"SKU-1", "SKU-2"}
    r2 = await client.get(f"/orders/{body['id']}")
    assert r2.json() == body


async def test_unknown_sku_is_problem_json(client):
    r = await client.post("/orders", json={"customer_id": 7, "lines": [{"sku": "NOPE", "qty": 1}]})
    assert r.status_code == 422
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["title"] == "Unknown SKU"


@pytest.mark.parametrize("payload, loc", [
    ({"customer_id": 0, "lines": [{"sku": "SKU-1", "qty": 1}]}, ["body", "customer_id"]),
    ({"customer_id": 1, "lines": []}, ["body", "lines"]),
    ({"customer_id": 1, "lines": [{"sku": "SKU-1", "qty": 1, "price": 0}]}, ["body", "lines", 0, "price"]),
], ids=["customer-not-positive", "no-lines", "extra-field-forbidden"])
async def test_validation(client, payload, loc):
    r = await client.post("/orders", json=payload)
    assert r.status_code == 422
    assert r.json()["errors"][0]["loc"] == loc


async def test_keyset_pagination(client):
    ids = []
    for _ in range(5):
        r = await client.post("/orders", json={"customer_id": 9, "lines": [{"sku": "SKU-1", "qty": 1}]})
        ids.append(r.json()["id"])
    page1 = (await client.get("/orders", params={"customer_id": 9, "limit": 2})).json()
    page2 = (await client.get("/orders", params={"customer_id": 9, "limit": 2, "after": page1["next_cursor"]})).json()
    page3 = (await client.get("/orders", params={"customer_id": 9, "limit": 2, "after": page2["next_cursor"]})).json()
    got = [o["id"] for p in (page1, page2, page3) for o in p["items"]]
    assert got == ids and page3["next_cursor"] is None


async def test_rollback_isolates_tests(client):
    r = await client.get("/orders", params={"customer_id": 9})
    assert r.json()["items"] == []


async def test_missing_order_404(client):
    r = await client.get("/orders/999999")
    assert r.status_code == 404 and r.json()["status"] == 404


async def test_readyz(client):
    r = await client.get("/readyz")
    assert r.status_code == 200 and r.json() == {"status": "ready"}
```

## What to look at

- `services/` has no FastAPI import: `rg -n 'fastapi|starlette' app/services app/models` returns nothing.
- `OrderRead.model_validate(order)` (or a return annotation) is the only path from ORM to JSON, so
  columns added to `Order` later never leak.
- `list_orders` fetches `limit + 1` rows ordered by the primary key, so `next_cursor` is the last id
  only when another page exists. The keyset predicate `Order.id > after` is an index range seek
  however deep the client pages, while `OFFSET n` reads and discards n rows. In production give the
  query a composite index `(customer_id, id)` (the example only indexes `customer_id`); see
  `sql-query-tuning`.
- The tests never start the lifespan: `ASGITransport` does not send lifespan events, so every resource
  the lifespan would create reaches the code through a dependency the tests override.
- `create_order` commits. Inside the test fixture that commit only releases a SAVEPOINT, and the
  outer transaction is rolled back at teardown (`test_rollback_isolates_tests` proves it).
