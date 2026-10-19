# Integration harnesses for Go tests

Copy-ready harnesses for the doubles table in the parent skill. All code assumes `go 1.25`+ in go.mod
(for `t.Context()` 1.24 and `synctest` 1.25) and testcontainers-go v0.32+ (`Run` API).

## 1. Postgres: one container per package, one database per test

Cloning a migrated template database gives each test a clean database in milliseconds without
restarting the container, and works even when the code under test commits its own transactions.

```go
//go:build integration

package store_test

import (
    "context"
    "crypto/rand"
    "database/sql"
    "fmt"
    "io/fs"
    "net/url"
    "os"
    "strings"
    "testing"

    "github.com/jackc/pgx/v5"
    "github.com/jackc/pgx/v5/pgxpool"
    _ "github.com/jackc/pgx/v5/stdlib"                      // registers the "pgx" database/sql driver
    "github.com/pressly/goose/v3"
    "github.com/testcontainers/testcontainers-go"
    "github.com/testcontainers/testcontainers-go/modules/postgres"

    "example.com/svc/db"                                    // db.Migrations: //go:embed migrations/*.sql
)

var adminDSN string // DSN of the maintenance database "postgres"

func TestMain(m *testing.M) { os.Exit(run(m)) }

func run(m *testing.M) int {
    ctx := context.Background()
    ctr, err := postgres.Run(ctx, "postgres:17-alpine",
        postgres.WithDatabase("app"), postgres.WithUsername("app"), postgres.WithPassword("app"),
        postgres.BasicWaitStrategies())
    defer func() { _ = testcontainers.TerminateContainer(ctr) }()
    if err != nil { fmt.Fprintln(os.Stderr, "start postgres:", err); return 1 }
    appDSN, err := ctr.ConnectionString(ctx, "sslmode=disable")
    if err != nil { fmt.Fprintln(os.Stderr, err); return 1 }
    if err := migrate(ctx, appDSN); err != nil { fmt.Fprintln(os.Stderr, "migrate:", err); return 1 }
    u, err := url.Parse(appDSN)                             // postgres://app:app@host:port/app?sslmode=disable
    if err != nil { fmt.Fprintln(os.Stderr, err); return 1 }
    u.Path = "/postgres"
    adminDSN = u.String()
    return m.Run()
}

func migrate(ctx context.Context, dsn string) error {
    sqlDB, err := sql.Open("pgx", dsn)
    if err != nil { return err }
    defer sqlDB.Close()                                     // template must have no open sessions
    fsys, err := fs.Sub(db.Migrations, "migrations")
    if err != nil { return err }
    p, err := goose.NewProvider(goose.DialectPostgres, sqlDB, fsys)
    if err != nil { return err }
    _, err = p.Up(ctx)
    return err
}

// newDB returns a pool on a fresh copy of the migrated "app" database.
func newDB(t *testing.T) *pgxpool.Pool {
    t.Helper()
    ctx := t.Context()
    admin, err := pgx.Connect(ctx, adminDSN)
    if err != nil { t.Fatal(err) }
    name := "t_" + strings.ToLower(rand.Text())            // crypto/rand.Text (1.24): 26 base32 chars
    if _, err := admin.Exec(ctx, "CREATE DATABASE "+name+" TEMPLATE app"); err != nil { t.Fatal(err) }
    cfg, err := pgxpool.ParseConfig(adminDSN)
    if err != nil { t.Fatal(err) }
    cfg.ConnConfig.Database = name
    pool, err := pgxpool.NewWithConfig(ctx, cfg)
    if err != nil { t.Fatal(err) }
    t.Cleanup(func() {                                      // t.Context() is already cancelled here
        pool.Close()
        _, _ = admin.Exec(context.Background(), "DROP DATABASE "+name+" WITH (FORCE)") // PostgreSQL 13+
        _ = admin.Close(context.Background())
    })
    return pool
}
```

Cheaper alternatives, in order: wrap each repository test in a transaction and roll back in
`t.Cleanup` (only when the code under test accepts a `pgx.Tx`/`DBTX`); `ctr.Snapshot(ctx)` once and
`ctr.Restore(ctx)` per test (the database must not be named `postgres`). Per-test containers cost
seconds each: reserve them for tests that need different server configuration.

## 2. Redis

```go
import (
    "github.com/redis/go-redis/v9"
    tcredis "github.com/testcontainers/testcontainers-go/modules/redis"
)

func newRedis(t *testing.T) *redis.Client {
    t.Helper()
    ctr, err := tcredis.Run(t.Context(), "redis:7-alpine")
    testcontainers.CleanupContainer(t, ctr)
    if err != nil { t.Fatalf("start redis: %v", err) }
    uri, err := ctr.ConnectionString(t.Context())          // redis://host:port
    if err != nil { t.Fatal(err) }
    opt, err := redis.ParseURL(uri)
    if err != nil { t.Fatal(err) }
    c := redis.NewClient(opt)
    t.Cleanup(func() { _ = c.Close() })
    return c
}
```

Without Docker (laptops, restricted CI), call `testcontainers.SkipIfProviderIsNotHealthy(t)` first.

## 3. Fake remote HTTP API that asserts the request

```go
func TestClientFetchUser(t *testing.T) {
    auth := make(chan string, 1)                            // hand data to the test goroutine: no race
    srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if r.Method != http.MethodGet || r.URL.Path != "/v1/users/42" {
            t.Errorf("request = %s %s, want GET /v1/users/42", r.Method, r.URL.Path) // Errorf is goroutine-safe
            http.NotFound(w, r)
            return
        }
        auth <- r.Header.Get("Authorization")
        w.Header().Set("Content-Type", "application/json")
        _, _ = io.WriteString(w, `{"id":42,"name":"Ada"}`)
    }))
    t.Cleanup(srv.Close)

    c := NewClient(srv.URL, srv.Client(), "test-token")
    got, err := c.FetchUser(t.Context(), 42)
    if err != nil { t.Fatalf("FetchUser(42) err = %v", err) }
    if diff := cmp.Diff(User{ID: 42, Name: "Ada"}, got); diff != "" {
        t.Errorf("FetchUser(42) mismatch (-want +got):\n%s", diff)
    }
    if a := <-auth; a != "Bearer test-token" { t.Errorf("Authorization = %q, want %q", a, "Bearer test-token") }
}
```

Error injection: a handler that returns 503 twice then 200 tests retries; a handler that sleeps tests
client timeouts, deterministically inside `synctest.Test` with `httptest.NewTestServer(t, h)` (1.27)
and `srv.Client()` (do not call `Start`; Cleanup is registered for you).

## 4. gRPC over bufconn

```go
func newItemsClient(t *testing.T, impl itemsv1.ItemsServer, opts ...grpc.ServerOption) itemsv1.ItemsClient {
    t.Helper()
    lis := bufconn.Listen(1 << 20)
    s := grpc.NewServer(opts...)                           // pass the production interceptors here
    itemsv1.RegisterItemsServer(s, impl)
    go func() { _ = s.Serve(lis) }()
    t.Cleanup(s.Stop)
    conn, err := grpc.NewClient("passthrough:///bufnet",
        grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) { return lis.DialContext(ctx) }),
        grpc.WithTransportCredentials(insecure.NewCredentials()))
    if err != nil { t.Fatal(err) }
    t.Cleanup(func() { _ = conn.Close() })
    return itemsv1.NewItemsClient(conn)
}
```

`bufconn.Listener.DialContext` exists since grpc-go v1.41. Interceptors are plain functions; test them
without a server:

```go
func TestAuthUnaryRejectsMissingToken(t *testing.T) {
    _, err := authUnary(t.Context(), &itemsv1.GetItemRequest{Id: 1},
        &grpc.UnaryServerInfo{FullMethod: "/items.v1.Items/GetItem"},
        func(ctx context.Context, req any) (any, error) { t.Fatal("handler must not run"); return nil, nil })
    if got := status.Code(err); got != codes.Unauthenticated {
        t.Fatalf("authUnary() code = %v, want %v", got, codes.Unauthenticated)
    }
}
```

## 5. Merged coverage script

```bash
#!/usr/bin/env bash
set -euo pipefail
out=.stack/out/coverage; rm -rf "$out"; mkdir -p "$out"/{unit,int}
go test -cover -coverpkg=./... ./... -args -test.gocoverdir="$PWD/$out/unit"
go build -cover -coverpkg=./... -o "$out/app" ./cmd/app
GOCOVERDIR="$out/int" "$out/app" -selftest            # or start it, drive the e2e suite, send SIGTERM
go tool covdata merge -i="$out/unit,$out/int" -o "$out/all"
go tool covdata textfmt -i="$out/all" -o "$out/cover.out"
go tool cover -func="$out/cover.out" | tail -1
```

`-selftest` stands for whatever drives the binary through its scenarios; the binary must exit via
`return` from `main` or `os.Exit`. `go tool covdata percent -pkg=example.com/svc/internal/...` narrows
the report.

## 6. CI layout

| Job | Trigger | Command | Notes |
|---|---|---|---|
| unit | every push | `go test -race -shuffle=on -count=1 -short ./...` | runs fuzz seeds and committed crashers too |
| integration | every PR | `go test -tags=integration -race -count=1 ./...` | needs Docker; one container per package |
| coverage | every PR | script in section 5 | fail on a drop against main, not on an absolute floor |
| fuzz | nightly | loop in the cookbook, 5-10 min per target | cache `$(go env GOCACHE)/fuzz`; open an issue with the crasher file |
| bench | label or manual | `-count=10` on base and head, `benchstat` | quiet runners only; never gate on noisy shared runners |
| flake hunt | manual | `-count=500 -race` or `stress` on the named test | attach `-test.shuffle` seed to the issue |
