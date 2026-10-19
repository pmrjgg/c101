# Service skeleton, configuration and observability

Everything here compiled with `cargo check --all-targets` on Rust 1.99 (October 2026) against
the resolved versions listed in SKILL.md. Treat the dependency list as a starting point and drop
what you do not use.

## 1. Cargo.toml

```toml
[dependencies]
anyhow = "1"
axum = { version = "0.8", features = ["macros", "http2"] }          # macros: FromRequest derive; http2: h2c/gRPC
jsonwebtoken = { version = "11", default-features = false, features = ["rust_crypto"] }  # or "aws_lc_rs"
metrics = "0.24"
metrics-exporter-prometheus = { version = "0.18", default-features = false }
opentelemetry = "0.33"
opentelemetry-otlp = { version = "0.33", features = ["grpc-tonic", "trace"] }
opentelemetry_sdk = "0.33"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
sqlx = { version = "0.8", default-features = false, features = ["runtime-tokio", "tls-rustls", "postgres", "macros", "migrate"] }
thiserror = "2"
tokio = { version = "1", features = ["macros", "rt-multi-thread", "signal", "net", "time"] }
tower = { version = "0.5", features = ["limit", "load-shed", "util"] }
tower-http = { version = "0.7", features = ["trace", "timeout", "limit", "request-id", "cors", "compression-gzip", "catch-panic", "sensitive-headers"] }
tracing = "0.1"
tracing-opentelemetry = "0.34"
tracing-subscriber = { version = "0.3", features = ["env-filter", "json"] }
validator = { version = "0.21", features = ["derive"] }

[dev-dependencies]
http-body-util = "0.1"
insta = { version = "1", features = ["json", "redactions"] }
```

The same manifest builds with `sqlx = "0.9"` (MSRV 1.94).

## 2. main.rs

```rust
use std::{net::SocketAddr, sync::Arc, time::Duration};
use axum::{error_handling::HandleErrorLayer, http::{header, Request, StatusCode}, routing::get, BoxError};
use opentelemetry::trace::TracerProvider as _;
use sqlx::postgres::PgPoolOptions;
use tower::ServiceBuilder;
use tower_http::{catch_panic::CatchPanicLayer, compression::CompressionLayer, limit::RequestBodyLimitLayer,
    request_id::{MakeRequestUuid, PropagateRequestIdLayer, SetRequestIdLayer},
    sensitive_headers::SetSensitiveRequestHeadersLayer, timeout::TimeoutLayer, trace::TraceLayer};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};
use items_api::{router, AppState, Keys};

struct Config { addr: SocketAddr, database_url: String, db_max_conns: u32, jwt_secret: String }

impl Config {
    fn from_env() -> anyhow::Result<Self> {
        Ok(Self {
            addr: std::env::var("APP_ADDR").unwrap_or_else(|_| "0.0.0.0:8080".into()).parse()?,
            database_url: std::env::var("DATABASE_URL")?,
            db_max_conns: std::env::var("APP_DB_MAX_CONNS").ok().and_then(|v| v.parse().ok()).unwrap_or(10),
            jwt_secret: std::env::var("APP_JWT_SECRET")?,
        })
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let exporter = opentelemetry_otlp::SpanExporter::builder().with_tonic().build()?;
    let provider = opentelemetry_sdk::trace::SdkTracerProvider::builder()
        .with_batch_exporter(exporter)
        .with_resource(opentelemetry_sdk::Resource::builder().with_service_name("items-api").build())
        .build();
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info,tower_http=info")))
        .with(tracing_subscriber::fmt::layer().json())
        .with(tracing_opentelemetry::layer().with_tracer(provider.tracer("items-api")))
        .init();

    let cfg = Config::from_env()?;
    let db = PgPoolOptions::new()
        .max_connections(cfg.db_max_conns)
        .acquire_timeout(Duration::from_secs(3))
        .connect(&cfg.database_url)
        .await?;
    sqlx::migrate!().run(&db).await?;

    let keys = Arc::new(Keys {
        decoding: jsonwebtoken::DecodingKey::from_secret(cfg.jwt_secret.as_bytes()),
        validation: jsonwebtoken::Validation::new(jsonwebtoken::Algorithm::HS256),
    });
    let metrics = metrics_exporter_prometheus::PrometheusBuilder::new().install_recorder()?;

    let middleware = ServiceBuilder::new()
        .layer(SetSensitiveRequestHeadersLayer::new([header::AUTHORIZATION]))
        .layer(SetRequestIdLayer::x_request_id(MakeRequestUuid))
        .layer(TraceLayer::new_for_http().make_span_with(|req: &Request<_>| {
            let rid = req.headers().get("x-request-id").and_then(|v| v.to_str().ok()).unwrap_or("-");
            tracing::info_span!("http", method = %req.method(), uri = %req.uri(), request_id = %rid)
        }))
        .layer(PropagateRequestIdLayer::x_request_id())
        .layer(CatchPanicLayer::new())
        .layer(HandleErrorLayer::new(|err: BoxError| async move {
            if err.is::<tower::load_shed::error::Overloaded>() {
                (StatusCode::SERVICE_UNAVAILABLE, "overloaded")
            } else {
                (StatusCode::INTERNAL_SERVER_ERROR, "internal error")
            }
        }))
        .load_shed()
        .concurrency_limit(512)
        .layer(TimeoutLayer::with_status_code(StatusCode::REQUEST_TIMEOUT, Duration::from_secs(10)))
        .layer(RequestBodyLimitLayer::new(1024 * 1024))
        .layer(CompressionLayer::new());

    let app = router(AppState { db, keys })
        .route("/metrics", get(move || std::future::ready(metrics.render())))
        .layer(middleware);

    let listener = tokio::net::TcpListener::bind(cfg.addr).await?;
    tracing::info!(addr = %cfg.addr, "listening");
    axum::serve(listener, app).with_graceful_shutdown(shutdown_signal()).await?;
    provider.shutdown()?;                     // flush spans last
    Ok(())
}

async fn shutdown_signal() {
    let ctrl_c = async { tokio::signal::ctrl_c().await.expect("install ctrl-c handler") };
    #[cfg(unix)]
    let terminate = async {
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("install SIGTERM handler")
            .recv()
            .await;
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();
    tokio::select! { _ = ctrl_c => {}, _ = terminate => {} }
}
```

`/metrics` is added before `.layer(middleware)` so it is traced too; expose it on an internal
port or protect it if the service is public.

Bounded drain: graceful shutdown waits for all connections. To cap it, share a
`tokio_util::sync::CancellationToken`: the shutdown future cancels it and the main task races
`serve` against `token.cancelled()` followed by a `tokio::time::sleep(Duration::from_secs(25))`,
exiting when either finishes (keep the cap below the orchestrator's kill timeout, e.g. 30 s in
Kubernetes by default).

## 3. Configuration

Both variants were run with environment overrides:

```rust
// figment (toml + env features): defaults < App.toml < APP_* env
let cfg: Settings = figment::Figment::new()
    .merge(figment::providers::Serialized::defaults(Settings::default()))
    .merge(figment::providers::Toml::file("App.toml"))
    .merge(figment::providers::Env::prefixed("APP_"))       // APP_DB_MAX_CONNS=20 -> db_max_conns
    .extract()?;

// config crate 0.15
let cfg: Settings = config::Config::builder()
    .add_source(config::Config::try_from(&Settings::default())?)
    .add_source(config::File::with_name("config/default").required(false))
    .add_source(config::Environment::with_prefix("APP").prefix_separator("_").separator("__"))
    .build()?
    .try_deserialize()?;
```

Gotcha (measured): with `.separator("__")` alone the prefix separator also becomes `__`, so only
`APP__DB_MAX_CONNS` is read; add `.prefix_separator("_")` to accept `APP_DB_MAX_CONNS`.
figment's last release is 0.10.19 (2024); the config crate is actively released. Validate the
loaded config at startup (ranges, URLs) and fail fast with a clear error; never log secrets.

## 4. Observability notes

- JSON logs with `tracing_subscriber::fmt::layer().json()` (feature `json`); filter with
  `RUST_LOG` through `EnvFilter`.
- OTLP endpoint and protocol come from `OTEL_EXPORTER_OTLP_ENDPOINT` /
  `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` / `OTEL_EXPORTER_OTLP_PROTOCOL`; builder settings win over
  env. `with_tonic()` needs a tokio runtime when built; HTTP export uses `.with_http()` (the crate's
  default `http-proto` + blocking reqwest client).
- Propagate trace context from incoming headers when you sit behind other traced services (an
  OpenTelemetry text-map propagator in a small middleware that sets the span parent).
- Metrics naming: `_total` for counters, base units (`_seconds`, `_bytes`), labels from route
  templates (`axum::extract::MatchedPath`), never user ids.
- Readiness: share an `Arc<AtomicBool>` "draining" flag set by the shutdown future; `/readyz`
  returns 503 when set or when `SELECT 1` fails within 1 s.
