---
name: go-http-services
description: "Production Go services. Covers net/http ServeMux patterns (1.22+), middleware chains, server and client timeouts, graceful shutdown, slog and OpenTelemetry, Prometheus and pprof, CrossOriginProtection, database/sql and pgx pool tuning with sqlc and goose, and gRPC/Connect error and deadline handling. Load when building, hardening or debugging a Go HTTP or gRPC service."
when_to_use: "Writing or reviewing net/http handlers, routers, middleware, http.Server or http.Client setup; 'context deadline exceeded', 'http: superfluous response.WriteHeader call', 'http: request body too large', connection leaks or pool exhaustion; graceful shutdown on SIGTERM; pgxpool/sqlc/goose; buf, grpc-go or connect-go services."
---

# Go HTTP and gRPC services

Baseline: Go 1.26/1.27, `go 1.22`+ in go.mod (the routing syntax depends on it). Security review of
a finished service is `security-review`; tests are `go-testing-fuzzing`.

Deep material: [middleware and observability code](references/middleware-observability.md) |
[gRPC and Connect](references/grpc-connect.md) | [full CRUD listing](references/crud-service-listing.md).

## 1. Routing with ServeMux

```go
mux := http.NewServeMux()
mux.HandleFunc("GET /v1/items", s.listItems)            // GET also matches HEAD
mux.HandleFunc("POST /v1/items", s.createItem)
mux.HandleFunc("GET /v1/items/{id}", s.getItem)         // id := r.PathValue("id")
mux.HandleFunc("GET /v1/items/export", s.export)        // literal segment beats {id}: more specific
mux.HandleFunc("GET /files/{path...}", s.files)         // remainder, may contain '/'
mux.HandleFunc("GET /{$}", s.home)                      // exactly "/", not a catch-all
```

| Rule | Detail |
|---|---|
| syntax | `[METHOD ][HOST]/[PATH]`; `{name}` = one segment, `{name...}` = rest (last only), `{$}` = end of path |
| methods | `GET` matches GET and HEAD; path matches but method does not: 405 with an `Allow` header |
| precedence | the most specific pattern wins; a host pattern beats a host-less one; overlapping patterns with neither more specific (`/a/{x}` and `/{y}/b`) panic at registration, so conflicts surface at startup |
| trailing slash | `/files/` matches the subtree and `/files` redirects to it (307 since 1.26, 301 before) |
| values | `r.PathValue("id")` is the unescaped segment, `""` if absent; `r.Pattern` (1.23) is the matched pattern: the only safe route label for logs, metrics and spans |
| version gate | with `go` < 1.22 in go.mod (`GODEBUG=httpmuxgo121=1`) method and wildcard patterns are not recognised and requests fall through to 404 or the `/` catch-all |

Calling a handler directly in a test skips the mux: set `req.SetPathValue("id", "42")`. Stay on
ServeMux unless you need what it lacks: middleware per route subtree (chi `r.Group`/`r.Route`),
regex-constrained parameters (`{id:[0-9]+}`), or an existing chi codebase. Emulate small groups with
a sub-mux behind `http.StripPrefix` or by wrapping individual handlers.

## 2. Server hardening

```go
srv := &http.Server{
    Addr:              cfg.Addr,
    Handler:           handler,
    ReadHeaderTimeout: 5 * time.Second,    // slowloris guard; gosec G112 flags its absence
    ReadTimeout:       15 * time.Second,   // whole request including body
    WriteTimeout:      30 * time.Second,   // end of header read to end of response write
    IdleTimeout:       120 * time.Second,  // keep-alive wait between requests
    MaxHeaderBytes:    64 << 10,           // default http.DefaultMaxHeaderBytes = 1 MiB
    ErrorLog:          slog.NewLogLogger(logger.Handler(), slog.LevelWarn),
}
```

| Field | Zero value means | Guidance |
|---|---|---|
| `ReadHeaderTimeout` | falls back to `ReadTimeout` | always set, 2-10 s |
| `ReadTimeout`, `WriteTimeout` | no timeout | set both; extend per request for uploads, exports, SSE (section 3) |
| `IdleTimeout` | falls back to `ReadTimeout` (none if both zero) | 60-120 s; longer than the idle timeout of a load balancer that reuses connections to you (avoids 502s) |
| `MaxHeaderValueCount` (1.27) | `DefaultMaxHeaderValueCount` | lower for public edge services |

`http.ListenAndServe(addr, h)` has no timeouts at all (gosec G114): always build an `http.Server`.

- Bodies: `r.Body = http.MaxBytesReader(w, r.Body, 1<<20)` per handler (or `http.MaxBytesHandler`);
  a `*http.MaxBytesError` from the read maps to 413. `ParseForm` caps url-encoded bodies at 10 MB;
  multipart needs an explicit `r.ParseMultipartForm(32 << 20)` memory limit.
- CSRF (1.25): `cop := http.NewCrossOriginProtection()` then `handler = cop.Handler(mux)`. GET, HEAD and
  OPTIONS always pass; `Sec-Fetch-Site: same-origin|none` passes; other cross-origin browser requests
  get 403 unless `cop.AddTrustedOrigin("https://admin.example.com")` (exact `scheme://host[:port]`, returns
  an error otherwise) or `cop.AddInsecureBypassPattern("POST /webhooks/{provider}")` (signature-verified
  server-to-server calls). Requests without `Sec-Fetch-Site` and `Origin` (curl, other services) pass,
  and the Origin-vs-Host fallback ignores the scheme. It is not CORS: CORS lets browsers read responses.
- TLS: `TLSConfig: &tls.Config{MinVersion: tls.VersionTLS12}` (`VersionTLS13` for internal traffic);
  leave `CipherSuites` and `CurvePreferences` nil for Go's defaults (hybrid post-quantum key exchange
  on since 1.24); rotate certificates with `GetCertificate` instead of restarts.
- HTTP/2 is automatic with TLS. Tune via `srv.HTTP2 = &http.HTTP2Config{MaxConcurrentStreams: 250}`
  (1.24). Cleartext HTTP/2 behind a TLS-terminating proxy (gRPC, Connect): `var p http.Protocols;
  p.SetHTTP1(true); p.SetUnencryptedHTTP2(true); srv.Protocols = &p` (replaces `x/net/http2/h2c`).

## 3. Middleware

```go
type Middleware func(http.Handler) http.Handler

func Chain(h http.Handler, mws ...Middleware) http.Handler { // mws[0] is the outermost
    for i := len(mws) - 1; i >= 0; i-- { h = mws[i](h) }
    return h
}

handler := Chain(mux, RequestID, AccessLog(logger), Recover(logger), cop.Handler)
mux.Handle("POST /v1/items", RequireAuth(verifier)(http.HandlerFunc(s.createItem))) // per route
```

| Order | Middleware | Rule |
|---|---|---|
| 1 | request ID | reuse an inbound `X-Request-ID` only from trusted proxies (validate length and charset), else `rand.Text()` (crypto/rand, 1.24); echo it in the response; store in ctx |
| 2 | access log | wraps the writer to capture status and bytes; reads `r.Pattern` after `next` returns; one line per request with `slog.LogAttrs` |
| 3 | recover | logs `debug.Stack()`, writes 500 (effective only before headers are sent), re-panics `http.ErrAbortHandler` |
| 4 | CSRF / CORS | reject before doing work |
| 5 | auth | verify token (`subtle.ConstantTimeCompare` for static secrets, a vetted JWT/OIDC library otherwise); principal into ctx under an unexported key type; 401 vs 403 |

Every `ResponseWriter` wrapper must implement `Unwrap() http.ResponseWriter`, or
`http.NewResponseController(w)` cannot reach the real connection. The controller replaces type
assertions to `http.Flusher`/`http.Hijacker` and adds per-request deadlines:

```go
rc := http.NewResponseController(w)
_ = rc.SetWriteDeadline(time.Now().Add(10 * time.Minute))  // this export only; time.Time{} clears it
for ev := range events {
    fmt.Fprintf(w, "data: %s\n\n", ev)
    if err := rc.Flush(); err != nil { return }             // errors.Is(err, http.ErrNotSupported) if unwrappable
}
```

`http.TimeoutHandler` buffers the response and cannot flush: use it only for plain request/response routes.

## 4. Client hygiene

```go
func NewClient() *http.Client {                         // one per downstream, shared, never per request
    tr := http.DefaultTransport.(*http.Transport).Clone()
    tr.MaxIdleConns = 200
    tr.MaxIdleConnsPerHost = 50                          // default 2: reconnect churn under load to one host
    tr.MaxConnsPerHost = 100                             // 0 = unlimited
    tr.TLSHandshakeTimeout = 5 * time.Second
    tr.ResponseHeaderTimeout = 10 * time.Second
    return &http.Client{Timeout: 30 * time.Second, Transport: tr} // http.DefaultClient has no timeout
}
```

- Per-call budget: `ctx, cancel := context.WithTimeout(ctx, 2*time.Second); defer cancel()` and
  `http.NewRequestWithContext(ctx, ...)`; `Client.Timeout` is the backstop.
- `defer resp.Body.Close()` immediately after the error check; on early returns drain a bounded amount
  (`io.Copy(io.Discard, io.LimitReader(resp.Body, 64<<10))`) so the connection is reused (1.27 drains
  small remainders on Close itself); read with `io.LimitReader`; a non-2xx status is not an error from `Do`.
- Retries: idempotent methods only (GET, HEAD, OPTIONS, PUT, DELETE, or POST with an idempotency key);
  on connection errors and 429/502/503/504; honour `Retry-After`; full-jitter backoff
  `sleep = rand.N(min(cap, base<<attempt))`; at most 3-4 attempts inside the caller's deadline; rewind
  bodies with `req.GetBody` (set by `NewRequest` for `bytes.Reader`, `bytes.Buffer`, `strings.Reader`);
  cap retries at about 10% extra load so an outage does not become a retry storm.

## 5. Graceful shutdown

1. `ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)`; after
   `<-ctx.Done()` call `stop()` so a second signal kills immediately.
2. Fail readiness (`/readyz` returns 503) and wait `DrainDelay` so load balancers stop routing to you.
3. `srv.Shutdown(ctx)` with a timeout: closes listeners, then idle connections, then waits for
   in-flight requests. `ListenAndServe` returns `http.ErrServerClosed` at once: not an error, and `main`
   must wait for `Shutdown` to return. Hijacked connections (WebSockets) are not tracked: notify them via
   `srv.RegisterOnShutdown`.
4. Cancel background workers and wait for them, flush telemetry (`tp.Shutdown`), close the DB pool last.

Budget: `DrainDelay + ShutdownTimeout + worker drain + telemetry flush < terminationGracePeriodSeconds`
(Kubernetes default 30 s), for example 5 + 15 + 5 + 2 = 27 s.

## 6. Observability

```go
logger := slog.New(ContextHandler{slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: cfg.LogLevel})})
slog.SetDefault(logger)                                  // also routes the log package
logger.InfoContext(r.Context(), "item created", slog.Int64("item_id", it.ID))

handler = otelhttp.NewHandler(handler, "api", otelhttp.WithSpanNameFormatter(
    func(op string, r *http.Request) string { if r.Pattern != "" { return r.Pattern }; return op }))
client.Transport = otelhttp.NewTransport(client.Transport) // propagates traceparent downstream
```

- `ContextHandler` adds `request_id` and `trace_id` from ctx to every record; it must wrap
  `WithAttrs`/`WithGroup` too or derived loggers lose it (code in the reference). Use `*Context` log
  methods everywhere; `slog.LevelVar` for runtime level changes; `LogValuer` to redact secrets;
  `slog.DiscardHandler` (1.24) in tests; `slog.NewMultiHandler` (1.26) to fan out.
- Metrics: RED per route with `prometheus/client_golang`: `http_requests_total{route,method,code}` and
  `http_request_duration_seconds` histogram, `route` = `r.Pattern`, never the raw path (cardinality).
- Admin listener on `127.0.0.1:9090` or an internal-only port: `/metrics`, `net/http/pprof` handlers
  registered explicitly on the admin mux (the package's init also registers on `http.DefaultServeMux`,
  so never serve the default mux publicly); `/debug/pprof/goroutineleak` is available in 1.27.
- Health: `/livez` checks only the process (no dependencies: a DB outage must not restart every pod);
  `/readyz` checks dependencies with a 1 s timeout and the draining flag; no auth on probes.

## 7. Data access

| `database/sql` setting | Default | Guidance |
|---|---|---|
| `SetMaxOpenConns` | 0 (unlimited) | per instance = floor(0.8 x server `max_connections` / instances); Postgres default `max_connections` = 100 |
| `SetMaxIdleConns` | 2 | equal to MaxOpenConns for steady traffic, avoids reconnect churn |
| `SetConnMaxLifetime` | 0 (forever) | 30-60 min, below proxy and load-balancer cut-offs |
| `SetConnMaxIdleTime` | 0 | about 5 min |

Watch `db.Stats()`: rising `WaitCount`/`WaitDuration` means the pool is too small or queries too slow.
Postgres-only services use `pgxpool` (pgx v5): `pgxpool.New(ctx, dsn)` with DSN parameters
`pool_max_conns` (default max(4, NumCPU)), `pool_max_conn_lifetime` (1h), `pool_max_conn_idle_time`
(30m), `pool_health_check_period` (1m); `pool.Stat()` exposes `EmptyAcquireCount` and `AcquireDuration`.
Behind PgBouncer in transaction mode set `default_query_exec_mode=simple_protocol` (or `exec`), since
cached prepared statements break across pooled server connections.

- sqlc: SQL in `queries/*.sql` with `-- name: GetItem :one` (`:many`, `:exec`, `:execrows`; on Postgres
  `:copyfrom` and `:batch*` need pgx); `sql_package: "pgx/v5"`; regenerate with `sqlc generate`, gate CI on
  `sqlc diff`. sqlc reads goose migrations as the schema and ignores the Down sections.
- Transactions: `pgx.BeginFunc(ctx, pool, func(tx pgx.Tx) error { q := store.New(tx); ... })` commits on
  nil and rolls back on error; with database/sql `tx, _ := db.BeginTx(ctx, nil); defer tx.Rollback()`,
  `q.WithTx(tx)`, `tx.Commit()`. Retry the whole transaction on SQLSTATE 40001 (serialization failure).
- Migrations: goose SQL files (`-- +goose Up` / `-- +goose Down`, `StatementBegin/End` around
  functions), embedded and applied with `goose.NewProvider(goose.DialectPostgres, db, fsys)`; run them as
  a release step, or at startup with `locker, err := lock.NewPostgresSessionLocker()` passed as
  `goose.WithSessionLocker(locker)` so replicas do not race. Atlas can generate them: `atlas migrate diff add_items --dir
  "file://db/migrations?format=goose" --to "file://schema.sql" --dev-url "docker://postgres/17/dev?search_path=public"`.

## 8. gRPC and Connect

- Protobuf with buf: `buf lint`, `buf breaking --against '.git#branch=main'`, `buf generate` with
  `protoc-gen-go` and `protoc-gen-go-grpc` (or `protoc-gen-connect-go`) pinned as `go tool` tools.
- grpc-go server: `grpc.NewServer(grpc.StatsHandler(otelgrpc.NewServerHandler()),
  grpc.ChainUnaryInterceptor(recover, log, auth))`, health service registered, `keepalive.ServerParameters{MaxConnectionAge: 5 * time.Minute}`
  so clients rebalance, `GracefulStop` with a `Stop` fallback after the shutdown timeout.
- Clients: `grpc.NewClient(target, ...)` (no I/O at construction; `Dial` is discouraged), one per
  target, reused.
- Deadlines: the client's ctx deadline travels as `grpc-timeout` (Connect protocol: `Connect-Timeout-Ms`)
  and becomes the handler's ctx deadline; pass that ctx to every DB and downstream call so each hop
  spends from the same budget; never `context.Background()` inside a handler.
- Connect: one handler serves Connect, gRPC and gRPC-Web over HTTP/1.1 and HTTP/2. connect-go v1
  (`connectrpc.com/connect`, the common one): `path, h := itemsv1connect.NewItemsServiceHandler(svc)`,
  `mux.Handle(path, h)`, errors `connect.NewError(connect.CodeNotFound, err)`. v2 (`connectrpc.com/connect/v2`,
  stable since October 2026) changes construction and errors: see [gRPC and Connect](references/grpc-connect.md).

| Domain error | gRPC / Connect code | HTTP (Connect protocol) |
|---|---|---|
| not found | `NotFound` | 404 |
| validation failed | `InvalidArgument` | 400 |
| duplicate | `AlreadyExists` | 409 |
| unauthenticated / forbidden | `Unauthenticated` / `PermissionDenied` | 401 / 403 |
| rate limited | `ResourceExhausted` | 429 |
| ctx deadline / cancelled | `DeadlineExceeded` / `Canceled` | 504 / 499 |
| dependency down (retryable) | `Unavailable` | 503 |
| anything else | `Internal` (log the cause, generic message) | 500 |

One mapping function per transport; `status.FromContextError(err)` converts ctx errors in grpc-go.

## 9. Configuration and wiring

- `main` only calls `run` and maps its error to an exit code: `if err := run(ctx, os.Getenv, os.Stdout); err != nil { ...; os.Exit(1) }`.
  `run` owns signals, loads config, builds every dependency and passes it explicitly; tests call `run` too.
- Config is one struct parsed from the environment at startup with defaults, validated with all errors
  joined (`errors.Join`), durations via `time.ParseDuration`, levels via `slog.Level.UnmarshalText`; fail
  fast before opening listeners.
- No package-level DB handles, loggers or config, no `init()` side effects; constructors take the
  narrow interfaces they consume (`go-interfaces-generics`). Secrets come from the environment or
  mounted files and are never logged (wrap them in a `LogValuer`).

## 10. Testing

- Route tests go through the mux so patterns are exercised: `mux.ServeHTTP(rec, httptest.NewRequest("GET", "/v1/items/42", nil))`.
- Service tests: `httptest.NewServer(handler)` over the real router and middleware with Postgres in
  testcontainers and goose migrations; golden JSON responses with ids and timestamps normalised.
- Shutdown test: start on `127.0.0.1:0`, hold a slow request open, trigger shutdown, assert it completes
  and new connections are refused. Harnesses: `go-testing-fuzzing`.

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| new routes 404 | `go` < 1.22 in go.mod | raise the `go` line |
| registration panic at startup | two overlapping patterns, neither more specific | make one literal or more specific |
| `http: superfluous response.WriteHeader call` | writing status after the body or twice | write headers once; return after errors |
| slowloris / goroutine pile-up | no `ReadHeaderTimeout` or `http.ListenAndServe` | full `http.Server` with timeouts |
| SSE stream cut after 30 s | server `WriteTimeout` | per-request `SetWriteDeadline` |
| sockets in TIME_WAIT, high latency to one host | `MaxIdleConnsPerHost` default 2, or undrained bodies | raise it; drain and close |
| outgoing call hangs forever | `http.DefaultClient` without ctx | client `Timeout` plus ctx per call |
| metrics cardinality explosion | raw `r.URL.Path` as label | `r.Pattern` |
| requests fail during deploy | no readiness flip or drain delay before `Shutdown` | section 5 order |
| requests stall on DB acquire (`WaitDuration`, `AcquireDuration` climbing) | pool smaller than concurrency, slow queries or unclosed rows | size per formula; always `rows.Close()` (sqlc does) |
| `prepared statement ... already exists` | pgx statement cache behind PgBouncer | `default_query_exec_mode=simple_protocol` |
| CSRF on JSON API | cookie auth without origin checks | `CrossOriginProtection` |

## 12. Worked example: JSON CRUD service

Layout: `cmd/itemsd/main.go`, `internal/api` (server, handlers, middleware), `internal/store`
(sqlc output), `db/migrations` and `db/queries`, `sqlc.yaml`. Full files: [listing](references/crud-service-listing.md).

```sql
-- db/migrations/00001_items.sql
-- +goose Up
CREATE TABLE items (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
    price_cents bigint      NOT NULL CHECK (price_cents >= 0),
    created_at  timestamptz NOT NULL DEFAULT now()
);
-- +goose Down
DROP TABLE items;

-- db/queries/items.sql
-- name: GetItem :one
SELECT id, name, price_cents, created_at FROM items WHERE id = $1;
-- name: CreateItem :one
INSERT INTO items (name, price_cents) VALUES ($1, $2) RETURNING id, name, price_cents, created_at;
-- name: DeleteItem :execrows
DELETE FROM items WHERE id = $1;
```

`sqlc.yaml`: `version: "2"`, one `sql` entry with `engine: postgresql`, `schema: db/migrations`,
`queries: db/queries`, `gen.go: {package: store, out: internal/store, sql_package: pgx/v5}` and an
override `db_type: timestamptz` to `go_type: time.Time` (otherwise `pgtype.Timestamptz`). `sqlc generate`
yields `store.New(pool)`, `GetItem(ctx, id int64) (store.Item, error)`,
`CreateItem(ctx, store.CreateItemParams{Name, PriceCents})` and `DeleteItem(ctx, id) (int64, error)`.

```go
func (s *Server) createItem(w http.ResponseWriter, r *http.Request) {
    var in struct {
        Name       string `json:"name"`
        PriceCents int64  `json:"price_cents"`
    }
    r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
    dec := json.NewDecoder(r.Body)
    dec.DisallowUnknownFields()
    if err := dec.Decode(&in); err != nil {
        if mbe := new(http.MaxBytesError); errors.As(err, &mbe) { s.problem(w, r, http.StatusRequestEntityTooLarge, "body too large", nil); return }
        s.problem(w, r, http.StatusBadRequest, "malformed JSON", nil)
        return
    }
    fields := map[string]string{}
    if n := utf8.RuneCountInString(strings.TrimSpace(in.Name)); n < 1 || n > 200 { fields["name"] = "1-200 characters" }
    if in.PriceCents < 0 { fields["price_cents"] = "must be >= 0" }
    if len(fields) > 0 { s.problem(w, r, http.StatusUnprocessableEntity, "validation failed", fields); return }
    it, err := s.q.CreateItem(r.Context(), store.CreateItemParams{Name: strings.TrimSpace(in.Name), PriceCents: in.PriceCents})
    if err != nil { s.internal(w, r, err); return }
    w.Header().Set("Location", fmt.Sprintf("/v1/items/%d", it.ID))
    writeJSON(w, http.StatusCreated, toDTO(it))
}

func (s *Server) getItem(w http.ResponseWriter, r *http.Request) {
    id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
    if err != nil || id < 1 { s.problem(w, r, http.StatusBadRequest, "invalid id", nil); return }
    it, err := s.q.GetItem(r.Context(), id)
    switch {
    case errors.Is(err, pgx.ErrNoRows): s.problem(w, r, http.StatusNotFound, "item not found", nil)
    case err != nil:                    s.internal(w, r, err)          // logs cause, returns generic 500
    default:                            writeJSON(w, http.StatusOK, toDTO(it))
    }
}
```

`problem` writes RFC 9457 `application/problem+json`; `internal` logs with the request ID and returns
a generic 500. Serving and shutdown in `run`, which owns `ctx, stop := signal.NotifyContext(...)`:

```go
ln, err := net.Listen("tcp", cfg.Addr)                       // bind errors surface synchronously
if err != nil { return fmt.Errorf("listen: %w", err) }
errc := make(chan error, 1)
go func() { errc <- srv.Serve(ln) }()
app.SetReady(true)
select {
case err := <-errc:
    return fmt.Errorf("serve: %w", err)
case <-ctx.Done():
}
stop()                                                       // second SIGTERM kills immediately
app.SetReady(false)                                          // /readyz -> 503
logger.Info("draining", slog.Duration("delay", cfg.DrainDelay))
time.Sleep(cfg.DrainDelay)
sctx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
defer cancel()
if err := srv.Shutdown(sctx); err != nil { return fmt.Errorf("shutdown: %w", err) }
return nil                                                   // deferred pool.Close() runs last
```

Integration test (`//go:build integration`): migrate a testcontainers Postgres with goose, mount the
real router on `httptest.NewServer`, then POST `{"name":"widget","price_cents":1299}` and expect 201
with `Location: /v1/items/1`; GET it (200, golden JSON after replacing `created_at`); POST
`{"name":"","price_cents":-1}` and expect 422 with both fields; DELETE (204), then GET (404).

```bash
sqlc generate && sqlc diff                                  # generated code is current
go vet ./... && go test -race ./...                          # unit: handlers via mux.ServeHTTP
go test -tags=integration -race -count=1 ./internal/api     # Postgres in Docker
go build -o .stack/out/itemsd ./cmd/itemsd && .stack/out/itemsd &   # a built binary gets the signal directly
curl -si localhost:8080/v1/items -d '{"name":"widget","price_cents":1299}'   # 201, Location: /v1/items/1
kill -TERM %1                                               # logs "draining", /readyz 503, exits 0 after drain
```

Related: `go-testing-fuzzing` (httptest, testcontainers, synctest), `go-error-handling` (domain errors
to status codes), `go-concurrency-context` (ctx, worker shutdown), `go-profiling-pprof` (pprof
endpoints, GC tuning), `go-modules-tooling` (builds, images, govulncheck), `security-review`; hub `go-craft`.
