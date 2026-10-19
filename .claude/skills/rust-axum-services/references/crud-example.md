# Complete CRUD example (compiled and partially run)

These files compiled with `cargo check --all-targets` against axum 0.8.9, sqlx 0.8.6 (and
unchanged against sqlx 0.9.0), tower-http 0.7.1, validator 0.21 and jsonwebtoken 11.1 on Rust
1.99. `tests/no_db.rs` was run (output in SKILL.md section 10); `tests/items.rs` needs a
PostgreSQL server in `DATABASE_URL` (or testcontainers) and was compiled, not run, here.
`main.rs` is in [service-skeleton](service-skeleton.md).

## migrations/0001_items.sql

```sql
CREATE TABLE items (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT   NOT NULL,
    price_cents BIGINT NOT NULL CHECK (price_cents >= 0)
);
CREATE TABLE audit_log (
    id      BIGSERIAL PRIMARY KEY,
    item_id BIGINT NOT NULL REFERENCES items(id),
    action  TEXT   NOT NULL,
    at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## src/lib.rs

```rust
use axum::extract::rejection::JsonRejection;
use axum::extract::{FromRef, FromRequest, FromRequestParts, Path, State};
use axum::http::{header, request::Parts, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use sqlx::PgPool;
use std::sync::Arc;
use std::time::Duration;
use validator::Validate;

#[derive(Clone)]
pub struct AppState {
    pub db: PgPool,
    pub keys: Arc<Keys>,
}

pub struct Keys {
    pub decoding: jsonwebtoken::DecodingKey,
    pub validation: jsonwebtoken::Validation,
}

impl FromRef<AppState> for Arc<Keys> {
    fn from_ref(s: &AppState) -> Self {
        Arc::clone(&s.keys)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("invalid JSON body")]
    Json(#[from] JsonRejection),
    #[error("validation failed")]
    Validation(#[from] validator::ValidationErrors),
    #[error("item {0} not found")]
    NotFound(i64),
    #[error("missing or invalid credentials")]
    Unauthorized,
    #[error("database error")]
    Db(#[from] sqlx::Error),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, detail) = match &self {
            AppError::Json(r) => (r.status(), r.body_text()),
            AppError::Validation(e) => (StatusCode::UNPROCESSABLE_ENTITY, e.to_string()),
            AppError::NotFound(_) => (StatusCode::NOT_FOUND, self.to_string()),
            AppError::Unauthorized => (StatusCode::UNAUTHORIZED, self.to_string()),
            AppError::Db(e) => {
                tracing::error!(error = %e, "database error"); // log once, here
                (StatusCode::INTERNAL_SERVER_ERROR, "internal error".to_owned())
            }
        };
        let body = serde_json::json!({
            "type": "about:blank",
            "title": status.canonical_reason().unwrap_or("error"),
            "status": status.as_u16(),
            "detail": detail,
        });
        (status, [(header::CONTENT_TYPE, "application/problem+json")], body.to_string()).into_response()
    }
}

/// `Json` whose rejection is our `AppError` (problem+json instead of plain text).
#[derive(FromRequest)]
#[from_request(via(Json), rejection(AppError))]
pub struct AppJson<T>(pub T);

#[derive(Debug, Deserialize, Validate)]
pub struct NewItem {
    #[validate(length(min = 1, max = 100))]
    pub name: String,
    #[validate(range(min = 0, max = 1_000_000))]
    pub price_cents: i64,
}

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct Item {
    pub id: i64,
    pub name: String,
    pub price_cents: i64,
}

#[derive(Debug, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub exp: u64,
}

pub struct AuthUser {
    pub sub: String,
}

impl<S> FromRequestParts<S> for AuthUser
where
    S: Send + Sync,
    Arc<Keys>: FromRef<S>,
{
    type Rejection = AppError;

    async fn from_request_parts(parts: &mut Parts, state: &S) -> Result<Self, Self::Rejection> {
        let keys = Arc::<Keys>::from_ref(state);
        let token = parts
            .headers
            .get(header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.strip_prefix("Bearer "))
            .ok_or(AppError::Unauthorized)?;
        let data = jsonwebtoken::decode::<Claims>(token, &keys.decoding, &keys.validation)
            .map_err(|_| AppError::Unauthorized)?;
        Ok(AuthUser { sub: data.claims.sub })
    }
}

#[tracing::instrument(skip_all, fields(user = %user.sub, name = %input.name))]
async fn create_item(
    State(st): State<AppState>,
    user: AuthUser,
    AppJson(input): AppJson<NewItem>,
) -> Result<(StatusCode, Json<Item>), AppError> {
    input.validate()?;
    let mut tx = st.db.begin().await?;
    let item: Item = sqlx::query_as(
        "INSERT INTO items (name, price_cents) VALUES ($1, $2) RETURNING id, name, price_cents",
    )
    .bind(&input.name)
    .bind(input.price_cents)
    .fetch_one(&mut *tx)
    .await?;
    sqlx::query("INSERT INTO audit_log (item_id, action) VALUES ($1, 'create')")
        .bind(item.id)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?; // dropped without commit = rollback
    metrics::counter!("items_created_total").increment(1);
    Ok((StatusCode::CREATED, Json(item)))
}

async fn get_item(State(st): State<AppState>, Path(id): Path<i64>) -> Result<Json<Item>, AppError> {
    sqlx::query_as::<_, Item>("SELECT id, name, price_cents FROM items WHERE id = $1")
        .bind(id)
        .fetch_optional(&st.db)
        .await?
        .map(Json)
        .ok_or(AppError::NotFound(id))
}

async fn readyz(State(st): State<AppState>) -> StatusCode {
    let ping = sqlx::query("SELECT 1").execute(&st.db);
    match tokio::time::timeout(Duration::from_secs(1), ping).await {
        Ok(Ok(_)) => StatusCode::OK,
        _ => StatusCode::SERVICE_UNAVAILABLE,
    }
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/items", post(create_item))
        .route("/items/{id}", get(get_item))
        .route("/healthz", get(|| async { StatusCode::OK }))
        .route("/readyz", get(readyz))
        .with_state(state)
}
```

## tests/items.rs (needs PostgreSQL)

```rust
use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use http_body_util::BodyExt;
use items_api::{router, AppState, Keys};
use sqlx::PgPool;
use std::sync::Arc;
use tower::ServiceExt;

fn app(db: PgPool) -> axum::Router {
    let mut validation = jsonwebtoken::Validation::new(jsonwebtoken::Algorithm::HS256);
    validation.validate_exp = false;
    validation.required_spec_claims.clear();
    let keys = Keys { decoding: jsonwebtoken::DecodingKey::from_secret(b"test-secret"), validation };
    router(AppState { db, keys: Arc::new(keys) })
}

fn token() -> String {
    // {"alg":"HS256","typ":"JWT"} . {"sub":"u1","exp":4102444800} signed with "test-secret"
    jsonwebtoken::encode(
        &jsonwebtoken::Header::default(),
        &serde_json::json!({"sub": "u1", "exp": 4_102_444_800u64}),
        &jsonwebtoken::EncodingKey::from_secret(b"test-secret"),
    )
    .unwrap()
}

async fn send(app: &axum::Router, req: Request<Body>) -> (StatusCode, serde_json::Value) {
    let resp = app.clone().oneshot(req).await.unwrap();
    let status = resp.status();
    let bytes = resp.into_body().collect().await.unwrap().to_bytes();
    (status, serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null))
}

fn post_item(body: &str) -> Request<Body> {
    Request::post("/items")
        .header(header::CONTENT_TYPE, "application/json")
        .header(header::AUTHORIZATION, format!("Bearer {}", token()))
        .body(Body::from(body.to_owned()))
        .unwrap()
}

#[sqlx::test(migrations = "./migrations")]
async fn create_then_get(db: PgPool) {
    let app = app(db.clone());
    let (status, body) = send(&app, post_item(r#"{"name":"widget","price_cents":1299}"#)).await;
    assert_eq!(status, StatusCode::CREATED);
    insta::assert_json_snapshot!(body, { ".id" => "[id]" });

    let id = body["id"].as_i64().unwrap();
    let (status, _) = send(&app, Request::get(format!("/items/{id}")).body(Body::empty()).unwrap()).await;
    assert_eq!(status, StatusCode::OK);

    let audit: i64 = sqlx::query_scalar("SELECT count(*) FROM audit_log WHERE item_id = $1")
        .bind(id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(audit, 1, "item and audit row commit together");
}

#[sqlx::test(migrations = "./migrations")]
async fn rejects_bad_input_with_problem_json(db: PgPool) {
    let app = app(db);
    let (status, body) = send(&app, post_item(r#"{"name":"","price_cents":5}"#)).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["status"], 422);

    let (status, _) = send(&app, post_item(r#"{"name":"x""#)).await; // truncated JSON
    assert_eq!(status, StatusCode::BAD_REQUEST);

    let req = Request::post("/items")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(r#"{"name":"x","price_cents":1}"#))
        .unwrap();
    let (status, _) = send(&app, req).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}
```

Run with `DATABASE_URL=postgres://postgres:postgres@localhost:5432/postgres cargo test`. The
first run writes `tests/snapshots/items__create_then_get.snap.new`; review it with
`cargo insta review` and commit the accepted `.snap`.

## tests/no_db.rs (runs without a database)

```rust
use axum::body::Body;
use axum::http::{header, Request};
use http_body_util::BodyExt;
use items_api::{router, AppState, Keys};
use std::sync::Arc;
use tower::ServiceExt;

#[tokio::test]
async fn error_paths_without_a_database() {
    let db = sqlx::postgres::PgPoolOptions::new().connect_lazy("postgres://nobody@127.0.0.1:1/none").unwrap();
    let mut validation = jsonwebtoken::Validation::new(jsonwebtoken::Algorithm::HS256);
    validation.required_spec_claims.clear();
    let keys = Keys { decoding: jsonwebtoken::DecodingKey::from_secret(b"test-secret"), validation };
    let app = router(AppState { db, keys: Arc::new(keys) });
    let token = jsonwebtoken::encode(
        &jsonwebtoken::Header::default(),
        &serde_json::json!({"sub": "u1", "exp": 4_102_444_800u64}),
        &jsonwebtoken::EncodingKey::from_secret(b"test-secret"),
    ).unwrap();
    for (auth, body) in [
        (true, r#"{"name":"","price_cents":5}"#),
        (true, r#"{"name":"x""#),
        (true, r#"{"name":"x","price_cents":"free"}"#),
        (false, r#"{"name":"x","price_cents":1}"#),
    ] {
        let mut req = Request::post("/items").header(header::CONTENT_TYPE, "application/json");
        if auth { req = req.header(header::AUTHORIZATION, format!("Bearer {token}")); }
        let resp = app.clone().oneshot(req.body(Body::from(body)).unwrap()).await.unwrap();
        let status = resp.status();
        let ct = resp.headers().get(header::CONTENT_TYPE).cloned();
        let bytes = resp.into_body().collect().await.unwrap().to_bytes();
        println!("{status} {ct:?} {}", String::from_utf8_lossy(&bytes));
    }
    let resp = app.clone().oneshot(Request::get("/items/abc").body(Body::empty()).unwrap()).await.unwrap();
    let status = resp.status();
    let bytes = resp.into_body().collect().await.unwrap().to_bytes();
    println!("{status} {}", String::from_utf8_lossy(&bytes));
}
```

`connect_lazy` builds a pool that connects only on first use, so every path that fails before
touching the database (auth, JSON syntax, JSON types, validation, path parsing) is testable in
milliseconds without infrastructure.

## Extending the example

| Add | How |
|---|---|
| list with pagination | `Query<ListParams>` with `limit: Option<u32>` (cap at 100) and keyset pagination (`WHERE id > $1 ORDER BY id LIMIT $2`) instead of `OFFSET` |
| update | `PATCH /items/{id}` with `Option` fields and `UPDATE ... SET name = COALESCE($2, name)`; return 404 when `rows_affected() == 0` |
| delete | `DELETE /items/{id}` returning 204 (`StatusCode::NO_CONTENT`) |
| duplicates | unique index plus `is_unique_violation()` mapped to 409 |
| compile-time checked SQL | swap `query_as::<_, Item>(...)` for `query_as!(Item, ...)`, run `cargo sqlx prepare`, commit `.sqlx/` |
| custom Path rejection | `#[derive(FromRequestParts)] #[from_request(via(Path), rejection(AppError))] struct AppPath<T>(T);` plus `From<PathRejection> for AppError` |
