# gRPC with tonic 0.14 and prost 0.14

Verified October 2026: tonic 0.14.6, tonic-prost-build 0.14.6, tonic-health 0.14.6,
tonic-reflection 0.14.6, axum 0.8.9. The one-port and interceptor code in section 3 compiled;
codegen needs `protoc` on the build machine (prost-build does not bundle it; install it with the
OS package manager or set `PROTOC`).

## 1. Crates and codegen

```toml
[dependencies]
tonic = "0.14"                 # default features: router, transport, codegen
tonic-prost = "0.14"           # runtime glue for prost messages (new split in 0.14)
prost = "0.14"
tonic-health = "0.14"
tonic-reflection = "0.14"

[build-dependencies]
tonic-prost-build = "0.14"     # replaces tonic-build's prost codegen
```

```rust
// build.rs
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let out = std::path::PathBuf::from(std::env::var("OUT_DIR")?);
    tonic_prost_build::configure()
        .build_server(true)
        .build_client(true)                                   // for tests and other services
        .file_descriptor_set_path(out.join("items_descriptor.bin"))   // for reflection
        .compile_protos(&["proto/items/v1/items.proto"], &["proto"])?;
    Ok(())
}
```

```protobuf
// proto/items/v1/items.proto
syntax = "proto3";
package items.v1;
service Items {
  rpc GetItem(GetItemRequest) returns (Item);
}
message GetItemRequest { int64 id = 1; }
message Item { int64 id = 1; string name = 2; int64 price_cents = 3; }
```

## 2. Service implementation

```rust
pub mod pb {
    tonic::include_proto!("items.v1");
    pub const FILE_DESCRIPTOR_SET: &[u8] = tonic::include_file_descriptor_set!("items_descriptor");
}
use pb::items_server::{Items, ItemsServer};
use tonic::{Request, Response, Status};

#[derive(Clone)]
pub struct ItemsSvc { db: sqlx::PgPool }

#[tonic::async_trait]                         // generated server traits still use async_trait
impl Items for ItemsSvc {
    async fn get_item(&self, req: Request<pb::GetItemRequest>) -> Result<Response<pb::Item>, Status> {
        let id = req.into_inner().id;
        let row: Option<(i64, String, i64)> =
            sqlx::query_as("SELECT id, name, price_cents FROM items WHERE id = $1")
                .bind(id).fetch_optional(&self.db).await
                .map_err(|e| { tracing::error!(error = %e, "db"); Status::internal("internal error") })?;
        let (id, name, price_cents) = row.ok_or_else(|| Status::not_found(format!("item {id}")))?;
        Ok(Response::new(pb::Item { id, name, price_cents }))
    }
}
```

Status mapping: validation -> `Status::invalid_argument`, missing -> `not_found`, auth ->
`unauthenticated` / `permission_denied`, overload -> `resource_exhausted` / `unavailable`,
everything else -> `internal` with a generic message (log the cause server-side).

## 3. One port for REST and gRPC (compiled)

```rust
fn check_auth(req: tonic::Request<()>) -> Result<tonic::Request<()>, tonic::Status> {
    match req.metadata().get("authorization") {
        Some(v) if v == "Bearer secret" => Ok(req),
        _ => Err(tonic::Status::unauthenticated("missing or bad token")),
    }
}

let health = tonic_health::pb::health_server::HealthServer::with_interceptor(
    tonic_health::server::HealthService::from_health_reporter(tonic_health::server::HealthReporter::new()),
    check_auth,
);
let grpc = tonic::service::Routes::new(health).into_axum_router();   // add_service(...) for more
let app = rest_router.merge(grpc);
axum::serve(listener, app).await?;          // axum feature "http2" required for h2c
```

With your own service: `Routes::new(ItemsServer::with_interceptor(svc, check_auth))`, then
`.add_service(health_service)` and `.add_service(reflection)`. Health reporting:
`let (reporter, health_service) = tonic_health::server::health_reporter();` and
`reporter.set_serving::<ItemsServer<ItemsSvc>>().await;` (`set_not_serving` while draining).
Reflection (lets grpcurl discover the API):

```rust
let reflection = tonic_reflection::server::Builder::configure()
    .register_encoded_file_descriptor_set(pb::FILE_DESCRIPTOR_SET)
    .build_v1()?;
```

Separate ports instead: `tonic::transport::Server::builder().timeout(Duration::from_secs(10))
.add_service(ItemsServer::new(svc)).serve(addr)` next to the axum listener; simpler TLS and
load-balancer configuration, one more port to expose.

## 4. Deadlines and cancellation

- Client: `let mut req = tonic::Request::new(msg); req.set_timeout(Duration::from_millis(300));`
  sends `grpc-timeout`; also set channel-level `connect_timeout` and `timeout` on the `Endpoint`.
- Server: enforce a maximum with a timeout layer (tonic `Server::builder().timeout(d)` or tower
  middleware on the axum router); read the caller's budget from the `grpc-timeout` header and
  pass `remaining - margin` to downstream calls with `tokio::time::timeout_at`.
- A cancelled call drops the handler future at its next `.await`: keep handlers cancel-safe
  (transactions roll back on drop; do not spawn detached work that assumes completion).

## 5. Testing

- In-process: bind `tokio::net::TcpListener` to `127.0.0.1:0`, spawn
  `tonic::transport::Server::builder().add_service(...).serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))`,
  then point a generated client at the bound address; or call the trait method directly (`svc.get_item(Request::new(...)).await`) for unit
  tests.
- Contract: keep `.proto` files in one place, lint them (`buf lint`), and check breaking changes
  (`buf breaking --against '.git#branch=main'`) in CI.
