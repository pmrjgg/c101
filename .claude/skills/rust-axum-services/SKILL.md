---
name: rust-axum-services
description: "Rust web services with axum 0.8. Covers the skeleton (config, AppState, Router composition, graceful shutdown), extractor rules, problem+json errors, tower and tower-http middleware order, sqlx 0.8/0.9 pools, migrations and transactions, tracing with OpenTelemetry and Prometheus, auth, validation, rate limits, tonic gRPC on one port, and in-process tests. Load when creating, extending, testing or debugging a Rust HTTP or gRPC service."
when_to_use: "Rust code using axum, tower, tower-http, sqlx, tonic or tracing-opentelemetry; route panics about ':' path syntax, 'Nesting at the root is no longer supported', extractor order errors ('the trait Handler is not implemented'), 'dynamic SQL strings should be audited', pool timeouts, 413/408 responses, missing request ids, services that hang on shutdown; adding endpoints, middleware, auth, metrics or integration tests."
---

# Rust HTTP and gRPC services with axum

Verified October 2026 by compiling the worked example and the reference files against axum
0.8.9, tower 0.5.3, tower-http 0.7.1, sqlx 0.8.6 and 0.9.0, tonic 0.14.6, opentelemetry 0.33 /
tracing-opentelemetry 0.34, metrics-exporter-prometheus 0.18, jsonwebtoken 11, validator 0.21,
garde 0.23, tower_governor 0.8 on Rust 1.99 (the section 1 sketch uses placeholder functions). axum 0.9 is in development: re-check its changelog before
upgrading. `tracing` is 0.1 (`tracing = "1"` does not resolve).

Deep material: [service skeleton, config and observability](references/service-skeleton.md) |
[complete CRUD example files](references/crud-example.md) | [tonic gRPC](references/grpc-tonic.md)

## 1. Skeleton

```rust
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_tracing()?;                                   // fmt JSON + OTLP layer, section 6
    let cfg = Config::from_env()?;                     // figment or config crate, see reference
    let db = PgPoolOptions::new()
        .max_connections(cfg.db_max_conns)
        .acquire_timeout(Duration::from_secs(3))       // default 30 s: fail fast instead
        .connect(&cfg.database_url).await?;
    sqlx::migrate!().run(&db).await?;                  // ./migrations embedded at compile time
    let state = AppState { db, keys: Arc::new(keys_from(&cfg)) };
    let app = Router::new()
        .nest("/api/v1", api::router())                // nest under a prefix
        .merge(health::router())                       // merge at the root (nest("/") panics)
        .with_state(state)
        .layer(middleware_stack());                    // section 4
    let listener = tokio::net::TcpListener::bind(cfg.addr).await?;
    axum::serve(listener, app).with_graceful_shutdown(shutdown_signal()).await?;
    Ok(())
}
```

- `AppState` is cloned per request: hold pools and clients (already `Arc` inside) or `Arc<T>`;
  never large owned data. Sub-states via `impl FromRef<AppState> for Arc<Keys>`.
- `shutdown_signal()` awaits `ctrl_c` or SIGTERM (`tokio::signal::unix::signal(SignalKind::terminate())`).
  On SIGTERM: flip readiness to 503, let the load balancer drain (a few seconds), then stop
  accepting; bound the drain with a deadline because long-lived connections (SSE, websockets,
  slow uploads) can hold graceful shutdown open. Flush telemetry (`provider.shutdown()`) last.

## 2. axum 0.8 rules

| Rule | Detail |
|---|---|
| path syntax | `/items/{id}`, catch-all `/files/{*path}`; old `/:id` and `/*rest` panic at startup |
| extractor order | `FromRequestParts` extractors (`State`, `Path`, `Query`, headers, your auth) first; at most one body extractor (`Json`, `Form`, `Bytes`, `String`, `Request`), and it must be last |
| `State` vs `Extension` | `State<T>` is checked at compile time (`with_state`); `Extension<T>` fails at runtime with 500 if the layer is missing: use it only for values set by middleware |
| custom extractors | `impl<S: Send + Sync> FromRequestParts<S> for AuthUser { type Rejection = AppError; async fn from_request_parts(...) }`: native async fn, no `#[async_trait]` |
| optional extractors | `Option<T>` needs `OptionalFromRequestParts`; `Option<Query<T>>` was removed: use `Query<Params>` with `Option` fields |
| rejections | `Json` gives 400 for syntax errors and 422 for type errors, `Path` gives plain-text 400; wrap them (`#[derive(FromRequest)] #[from_request(via(Json), rejection(AppError))] struct AppJson<T>(T);`, same with `FromRequestParts` for `Path`/`Query`, needs the `macros` feature) |
| body size | `Json`/`Bytes`/`String`/`Form` reject bodies over 2 MB by default (`DefaultBodyLimit::max(n)` to change); streaming `Body` is not limited: add `RequestBodyLimitLayer` |
| handlers | handler fns must be `Clone + Send + Sync + 'static` and their futures `Send`; a non-`Send` value held across `.await` produces "the trait `Handler<_, _>` is not implemented" (see `rust-async-tokio`) |
| HTTP/2 | not in default features: enable `http2` for h2c/gRPC on `axum::serve` |

## 3. Error type

One `AppError` per service, mapped to status codes in exactly one `IntoResponse` impl, logged
once there, never leaking internal messages:

```rust
#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("invalid JSON body")] Json(#[from] JsonRejection),
    #[error("validation failed")] Validation(#[from] validator::ValidationErrors),
    #[error("item {0} not found")] NotFound(i64),
    #[error("missing or invalid credentials")] Unauthorized,
    #[error("database error")] Db(#[from] sqlx::Error),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, detail) = match &self {
            AppError::Json(r) => (r.status(), r.body_text()),
            AppError::Validation(e) => (StatusCode::UNPROCESSABLE_ENTITY, e.to_string()),
            AppError::NotFound(_) => (StatusCode::NOT_FOUND, self.to_string()),
            AppError::Unauthorized => (StatusCode::UNAUTHORIZED, self.to_string()),
            AppError::Db(e) => {
                tracing::error!(error = %e, "database error");          // log once, here
                (StatusCode::INTERNAL_SERVER_ERROR, "internal error".to_owned())
            }
        };
        let body = serde_json::json!({ "type": "about:blank", "status": status.as_u16(),
            "title": status.canonical_reason().unwrap_or("error"), "detail": detail });
        (status, [(header::CONTENT_TYPE, "application/problem+json")], body.to_string()).into_response()
    }
}
```

Map unique violations to 409 before the generic 500 arm:
`AppError::Db(e) if e.as_database_error().is_some_and(|d| d.is_unique_violation())` (Postgres
code `23505`). Error-type design in general: `rust-error-handling`.

## 4. Middleware with ServiceBuilder

`ServiceBuilder` runs layers top to bottom on the request (first listed = outermost);
repeated `Router::layer` calls run bottom to top. `Router::layer` wraps only routes added before
it; `route_layer` runs only for matched routes (auth there keeps unknown paths 404, not 401).

```rust
let middleware = ServiceBuilder::new()
    .layer(SetSensitiveRequestHeadersLayer::new([header::AUTHORIZATION]))   // redact in logs
    .layer(SetRequestIdLayer::x_request_id(MakeRequestUuid))                 // before tracing
    .layer(TraceLayer::new_for_http().make_span_with(|req: &Request<_>| {
        let rid = req.headers().get("x-request-id").and_then(|v| v.to_str().ok()).unwrap_or("-");
        tracing::info_span!("http", method = %req.method(), uri = %req.uri(), request_id = %rid)
    }))
    .layer(PropagateRequestIdLayer::x_request_id())                          // echo to client
    .layer(CatchPanicLayer::new())                                          // panic -> 500
    .layer(HandleErrorLayer::new(|err: BoxError| async move {               // tower errors -> HTTP
        if err.is::<tower::load_shed::error::Overloaded>() {
            (StatusCode::SERVICE_UNAVAILABLE, "overloaded")
        } else {
            (StatusCode::INTERNAL_SERVER_ERROR, "internal error")
        }
    }))
    .load_shed()                                                            // reject when full
    .concurrency_limit(512)
    .layer(TimeoutLayer::with_status_code(StatusCode::REQUEST_TIMEOUT, Duration::from_secs(10)))
    .layer(RequestBodyLimitLayer::new(1024 * 1024))
    .layer(CompressionLayer::new());
```

- tower-http 0.7: `TimeoutLayer::new` is deprecated (since 0.6.7) for
  `with_status_code(status, duration)`; `RequestBodyDeadlineLayer` caps total upload time (slow
  clients); `CsrfLayer` exists for cookie-authenticated browser apps; `CorsLayer::new()` with
  explicit origins, methods and headers (never `permissive()` with credentials).
- Fallible tower layers (`load_shed`, `tower::timeout`, buffer) need `HandleErrorLayer` above them;
  tower-http's `TimeoutLayer` answers 408 itself.
- Features used here: tower `limit`, `load-shed`, `util`; tower-http `trace`, `timeout`,
  `limit`, `request-id`, `cors`, `compression-gzip`, `catch-panic`, `sensitive-headers`.

## 5. sqlx

- Pool sizing: per-instance `max_connections` = (DB `max_connections` - reserved - other
  clients) / instances. Postgres default 100 with 3 superuser-reserved: 6 pods with 7 slots kept
  for migrations/admin gives 90 / 6 = 15 each. Defaults: max 10, `acquire_timeout` 30 s,
  `idle_timeout` 10 min, `max_lifetime` 30 min, `test_before_acquire` true.
- Compile-time checked queries: `sqlx::query_as!(Item, "SELECT id, name, price_cents FROM items WHERE id = $1", id)`
  needs `DATABASE_URL` at build time or offline data: `cargo sqlx prepare --workspace` writes
  `.sqlx/` (commit it); CI builds with `SQLX_OFFLINE=true` and checks with `cargo sqlx prepare --check`.
- Migrations: `sqlx migrate add -r create_items` (up/down files), `sqlx migrate run`,
  `sqlx::migrate!()` in the binary or a separate job. Never edit an applied migration.
- Transactions: `let mut tx = pool.begin().await?;` run queries with `.execute(&mut *tx)`,
  finish with `tx.commit().await?`; dropping `tx` (error, `?`, client disconnect cancelling the
  handler) rolls back.
- sqlx 0.9 (May 2026) deltas: MSRV 1.94; query functions take `impl SqlSafeStr` (string literals
  pass; `format!` strings fail with "dynamic SQL strings should be audited for possible
  injections": use binds, `QueryBuilder`, or `sqlx::AssertSqlSafe(q)` after review); combined
  runtime+TLS features removed (use `runtime-tokio` + `tls-rustls`); optional `sqlx.toml`;
  repository moving to the transact-rs org. The example below compiles unchanged on both.

## 6. Observability

- `#[tracing::instrument(skip_all, fields(user = %user.sub, item_id = tracing::field::Empty))]` on
  handlers; fill late fields with `tracing::Span::current().record("item_id", id)`; `skip_all`
  keeps bodies and secrets out of spans.
- OTLP: `opentelemetry_otlp::SpanExporter::builder().with_tonic().build()?` ->
  `SdkTracerProvider::builder().with_batch_exporter(exporter).with_resource(Resource::builder().with_service_name("items-api").build()).build()`
  -> `tracing_opentelemetry::layer().with_tracer(provider.tracer("items-api"))`
  (`use opentelemetry::trace::TracerProvider as _`). Endpoint from `OTEL_EXPORTER_OTLP_ENDPOINT`
  (gRPC default `http://localhost:4317`). Versions move in lockstep: opentelemetry 0.33 with
  tracing-opentelemetry 0.34.
- Metrics: `PrometheusBuilder::new().install_recorder()?` returns a handle; serve
  `handle.render()` on `/metrics`; record with `metrics::counter!("items_created_total").increment(1)`.
  Keep label cardinality bounded (route templates via `MatchedPath`, never raw URIs or user ids).
- Health: `/healthz` (liveness: process is up, no dependencies) and `/readyz` (readiness:
  `SELECT 1` under a 1 s timeout, 503 while draining).
- Background work keeps its trace: `tokio::spawn(fut.instrument(tracing::info_span!("job")))`
  (`use tracing::Instrument`); never hold a `span.enter()` guard across `.await`.
- Outbound HTTP: one shared `reqwest::Client` in `AppState` with `timeout` and `connect_timeout`
  set, plus an outer `tokio::time::timeout` bounded by the request's remaining budget.

## 7. Security basics

| Concern | Tool |
|---|---|
| JWT bearer auth | `jsonwebtoken` 11 (pick a crypto backend feature: `aws_lc_rs` or `rust_crypto`); `decode::<Claims>(token, &DecodingKey, &Validation::new(Algorithm::HS256))` in a `FromRequestParts` extractor; keys built once at startup |
| sessions | `tower-sessions` (`SessionManagerLayer` with a store; secure, HttpOnly, SameSite cookies) |
| input validation | `validator` (`#[derive(Validate)]`, `#[validate(length(min = 1, max = 100))]`, `.validate()?`) or `garde` (`#[garde(length(min = 3, max = 20))]`, `email`) |
| rate limiting | `tower_governor`: `GovernorConfigBuilder::default().per_second(2).burst_size(5)` means one token every 2 s with bursts of 5 (not 2 per second); serve with `into_make_service_with_connect_info::<SocketAddr>()` for per-IP keys, behind proxies use a header-based key extractor; prune with `limiter().retain_recent()` |
| body limits and timeouts | `RequestBodyLimitLayer`, `DefaultBodyLimit`, `TimeoutLayer`, `RequestBodyDeadlineLayer` |
| secrets in logs | `SetSensitiveRequestHeadersLayer`, `skip_all` in `#[instrument]` |
| SQL injection | bind parameters only; sqlx 0.9 enforces it at compile time |

## 8. gRPC with tonic 0.14

- Codegen moved to `tonic-prost-build` (build.rs: `tonic_prost_build::compile_protos("proto/items.proto")?`;
  needs `protoc` installed); runtime crates `tonic`, `tonic-prost`, `prost`; include with
  `tonic::include_proto!("items.v1")`.
- One port for REST and gRPC: `let grpc = tonic::service::Routes::new(ItemsServer::new(svc)).into_axum_router();`
  then `rest_router.merge(grpc)` and enable axum's `http2` feature (h2c).
- Interceptors: `ItemsServer::with_interceptor(svc, check_auth)` with
  `fn check_auth(req: Request<()>) -> Result<Request<()>, Status>`.
- Deadlines: clients set `request.set_timeout(d)` (sent as `grpc-timeout`); enforce server-side
  with a timeout layer and pass the remaining budget to downstream calls.
Details: [grpc-tonic](references/grpc-tonic.md).

## 9. Testing

- In-process: build the `Router` with test state and call `app.clone().oneshot(request)`
  (`tower::ServiceExt`, feature `util`); read bodies with `http_body_util::BodyExt::collect`.
  No sockets, no ports, runs in milliseconds.
- Databases: `#[sqlx::test(migrations = "./migrations")] async fn t(pool: PgPool)` gets a fresh
  database per test from `DATABASE_URL`; without a local server, testcontainers
  (`testcontainers-modules` `postgres`).
- Error paths that never reach the database can use `PgPoolOptions::new().connect_lazy(url)` with
  an unreachable URL: the pool only connects on first use.
- Snapshots: `insta::assert_json_snapshot!(body, { ".id" => "[id]" })` (insta features `json`,
  `redactions`). Patterns for doubles and fuzzing: `rust-testing-fuzzing`.

## 10. Worked example: create/get items with validation, a transaction and tests

Migration `migrations/0001_items.sql` creates
`items(id BIGSERIAL, name TEXT, price_cents BIGINT CHECK (price_cents >= 0))` and
`audit_log(id, item_id REFERENCES items, action, at)`. Handlers (error type from section 3):

```rust
#[derive(FromRequest)]
#[from_request(via(Json), rejection(AppError))]
pub struct AppJson<T>(pub T);

#[derive(Debug, Deserialize, Validate)]
pub struct NewItem {
    #[validate(length(min = 1, max = 100))] pub name: String,
    #[validate(range(min = 0, max = 1_000_000))] pub price_cents: i64,
}
#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct Item { pub id: i64, pub name: String, pub price_cents: i64 }

#[tracing::instrument(skip_all, fields(user = %user.sub, name = %input.name))]
async fn create_item(State(st): State<AppState>, user: AuthUser, AppJson(input): AppJson<NewItem>)
    -> Result<(StatusCode, Json<Item>), AppError> {
    input.validate()?;
    let mut tx = st.db.begin().await?;
    let item: Item = sqlx::query_as(
        "INSERT INTO items (name, price_cents) VALUES ($1, $2) RETURNING id, name, price_cents")
        .bind(&input.name).bind(input.price_cents)
        .fetch_one(&mut *tx).await?;
    sqlx::query("INSERT INTO audit_log (item_id, action) VALUES ($1, 'create')")
        .bind(item.id).execute(&mut *tx).await?;
    tx.commit().await?;                                   // dropped without commit = rollback
    metrics::counter!("items_created_total").increment(1);
    Ok((StatusCode::CREATED, Json(item)))
}

async fn get_item(State(st): State<AppState>, Path(id): Path<i64>) -> Result<Json<Item>, AppError> {
    sqlx::query_as::<_, Item>("SELECT id, name, price_cents FROM items WHERE id = $1")
        .bind(id).fetch_optional(&st.db).await?
        .map(Json).ok_or(AppError::NotFound(id))
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/items", post(create_item))
        .route("/items/{id}", get(get_item))
        .with_state(state)
}
```

`AuthUser` is the JWT extractor from section 7. Integration test (`tests/items.rs`):

```rust
#[sqlx::test(migrations = "./migrations")]
async fn create_then_get(db: PgPool) {
    let app = app(db.clone());                            // router with test keys
    let (status, body) = send(&app, post_item(r#"{"name":"widget","price_cents":1299}"#)).await;
    assert_eq!(status, StatusCode::CREATED);
    insta::assert_json_snapshot!(body, { ".id" => "[id]" });
    let id = body["id"].as_i64().unwrap();
    let (status, _) = send(&app, Request::get(format!("/items/{id}")).body(Body::empty()).unwrap()).await;
    assert_eq!(status, StatusCode::OK);
    let audit: i64 = sqlx::query_scalar("SELECT count(*) FROM audit_log WHERE item_id = $1")
        .bind(id).fetch_one(&db).await.unwrap();
    assert_eq!(audit, 1, "item and audit row commit together");
}
```

`send` wraps `app.clone().oneshot(req)` plus `collect()`; `post_item` adds JSON content type and a
bearer token minted with `jsonwebtoken::encode` and the test secret (full file in the
reference). Run: `DATABASE_URL=postgres://localhost/postgres cargo test` (sqlx creates a test
database per test and cleans it up; the role needs CREATEDB). Real responses from the in-process
error-path test (lazy pool, no database; bodies abridged):

```text
422 application/problem+json {"detail":"name: Validation error: length [...]","status":422,...}
400 application/problem+json {"detail":"Failed to parse the request body as JSON: EOF while parsing an object at line 1 column 11",...}
422 application/problem+json {"detail":"Failed to deserialize the JSON body into the target type: price_cents: invalid type: string \"free\", expected i64 at line 1 column 32",...}
401 application/problem+json {"detail":"missing or invalid credentials","status":401,...}
400 text/plain  Invalid URL: Cannot parse `abc` to a `i64`
```

The last line shows why `Path` needs the same wrapper as `Json`. The auth extractor runs before
the body is read, so an unauthenticated request with a bad body still gets 401.

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| p99 spikes, workers stalled | blocking call in a handler (`std::fs`, sync HTTP, bcrypt/argon2, big JSON) | `spawn_blocking` or rayon via oneshot; see `rust-async-tokio` |
| "pool timed out while waiting for an open connection" | connection held across slow awaits (external HTTP inside a transaction), pool too small | acquire late, release early; no network calls inside transactions; size per section 5 |
| memory grows under load | unbounded `tokio::spawn` per request, unbounded channels | `concurrency_limit` + `load_shed`, bounded channels, `JoinSet` with limits |
| OOM or slow requests on uploads | no body limit on streaming bodies | `RequestBodyLimitLayer`, `RequestBodyDeadlineLayer` |
| latency proportional to state size | `AppState` holds big owned data cloned per request | `Arc` everything shared |
| startup panic on routes | 0.7-style `/:id`, or `nest("/", ...)` | `/{id}`, `merge` |
| handler "does not implement Handler" | non-`Send` value across `.await`, body extractor not last, too many extractors (max 16) | fix order, scope guards, group extractors |
| plain-text 400/422 bodies in a JSON API | default rejections | `AppJson`/`AppPath` wrappers |
| request id missing from logs | `SetRequestIdLayer` after `TraceLayer` | set the id first, propagate last |
| shutdown hangs | graceful shutdown waits for long-lived connections | readiness 503, drain deadline, then exit |
| gRPC clients fail with protocol errors on the shared port | axum built without `http2` | enable `features = ["http2"]` |

Related: `rust-async-tokio`, `rust-error-handling`, `rust-testing-fuzzing`, `rust-performance`,
`cargo-workspaces-features`, hub `rust-craft`.
