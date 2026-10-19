# Full listing: items CRUD service

Complete files for the worked example in the skill (ServeMux, validation, sqlc on pgx v5, goose,
graceful shutdown, integration test). Middleware (`Chain`, `RequestID`, `AccessLog`, `Recover`,
`ContextHandler`) comes from [middleware and observability](middleware-observability.md).
The migration file is shown in the skill.

## sqlc.yaml and queries

```yaml
version: "2"
sql:
  - engine: "postgresql"
    schema: "db/migrations"          # goose files; sqlc ignores the Down sections
    queries: "db/queries"
    gen:
      go:
        package: "store"
        out: "internal/store"
        sql_package: "pgx/v5"
        overrides:
          - db_type: "timestamptz"
            go_type: "time.Time"     # default with pgx/v5 would be pgtype.Timestamptz
```

```sql
-- db/queries/items.sql
-- name: GetItem :one
SELECT id, name, price_cents, created_at FROM items WHERE id = $1;

-- name: ListItems :many
SELECT id, name, price_cents, created_at FROM items
WHERE id > sqlc.arg(after_id)
ORDER BY id
LIMIT sqlc.arg(page_size);

-- name: CreateItem :one
INSERT INTO items (name, price_cents) VALUES ($1, $2)
RETURNING id, name, price_cents, created_at;

-- name: UpdateItem :one
UPDATE items SET name = $2, price_cents = $3 WHERE id = $1
RETURNING id, name, price_cents, created_at;

-- name: DeleteItem :execrows
DELETE FROM items WHERE id = $1;
```

After `sqlc generate`, check `internal/store/items.sql.go` for the parameter types (the `LIMIT`
argument is generated as a sized integer such as `int32`; convert at the call site).

```go
// db/embed.go
package db

import "embed"

//go:embed migrations/*.sql
var Migrations embed.FS
```

## internal/api/server.go

```go
package api

// Store is what the handlers consume; *store.Queries satisfies it, tests use a fake.
type Store interface {
    GetItem(ctx context.Context, id int64) (store.Item, error)
    ListItems(ctx context.Context, arg store.ListItemsParams) ([]store.Item, error)
    CreateItem(ctx context.Context, arg store.CreateItemParams) (store.Item, error)
    UpdateItem(ctx context.Context, arg store.UpdateItemParams) (store.Item, error)
    DeleteItem(ctx context.Context, id int64) (int64, error)
}

type Server struct {
    q     Store
    log   *slog.Logger
    ping  func(context.Context) error
    ready atomic.Bool
}

func New(q Store, log *slog.Logger, ping func(context.Context) error) *Server {
    return &Server{q: q, log: log, ping: ping}
}

func (s *Server) SetReady(v bool) { s.ready.Store(v) }

func (s *Server) Routes() *http.ServeMux {
    mux := http.NewServeMux()
    mux.HandleFunc("GET /v1/items", s.listItems)
    mux.HandleFunc("POST /v1/items", s.createItem)
    mux.HandleFunc("GET /v1/items/{id}", s.getItem)
    mux.HandleFunc("PUT /v1/items/{id}", s.updateItem)
    mux.HandleFunc("DELETE /v1/items/{id}", s.deleteItem)
    mux.HandleFunc("GET /livez", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNoContent) })
    mux.HandleFunc("GET /readyz", s.readyz)
    return mux
}

func (s *Server) readyz(w http.ResponseWriter, r *http.Request) {
    if !s.ready.Load() { http.Error(w, "draining", http.StatusServiceUnavailable); return }
    ctx, cancel := context.WithTimeout(r.Context(), time.Second)
    defer cancel()
    if err := s.ping(ctx); err != nil { http.Error(w, "db unavailable", http.StatusServiceUnavailable); return }
    w.WriteHeader(http.StatusNoContent)
}

type itemDTO struct {
    ID         int64     `json:"id"`
    Name       string    `json:"name"`
    PriceCents int64     `json:"price_cents"`
    CreatedAt  time.Time `json:"created_at"`
}

func toDTO(it store.Item) itemDTO {
    return itemDTO{ID: it.ID, Name: it.Name, PriceCents: it.PriceCents, CreatedAt: it.CreatedAt.UTC()}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(status)
    _ = json.NewEncoder(w).Encode(v)                       // the client may be gone; nothing to do
}

type problemDoc struct {                                   // RFC 9457
    Type   string            `json:"type"`
    Title  string            `json:"title"`
    Status int               `json:"status"`
    Detail string            `json:"detail,omitempty"`
    Errors map[string]string `json:"errors,omitempty"`     // extension member: field -> message
}

func (s *Server) problem(w http.ResponseWriter, r *http.Request, status int, detail string, fields map[string]string) {
    w.Header().Set("Content-Type", "application/problem+json")
    w.WriteHeader(status)
    _ = json.NewEncoder(w).Encode(problemDoc{Type: "about:blank", Title: http.StatusText(status),
        Status: status, Detail: detail, Errors: fields})
}

func (s *Server) internal(w http.ResponseWriter, r *http.Request, err error) {
    s.log.ErrorContext(r.Context(), "request failed", slog.String("route", r.Pattern), slog.Any("err", err))
    s.problem(w, r, http.StatusInternalServerError, "internal error", nil)  // never leak err to clients
}
```

## internal/api/items.go

```go
type itemInput struct {
    Name       string `json:"name"`
    PriceCents int64  `json:"price_cents"`
}

func (in *itemInput) normalize() map[string]string {
    in.Name = strings.TrimSpace(in.Name)
    fields := map[string]string{}
    if n := utf8.RuneCountInString(in.Name); n < 1 || n > 200 { fields["name"] = "must be 1-200 characters" }
    if in.PriceCents < 0 { fields["price_cents"] = "must be >= 0" }
    return fields
}

// decodeJSON returns a non-zero status and a message when the body is unusable.
func decodeJSON(w http.ResponseWriter, r *http.Request, dst any) (int, string) {
    r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
    dec := json.NewDecoder(r.Body)
    dec.DisallowUnknownFields()
    if err := dec.Decode(dst); err != nil {
        if mbe := new(http.MaxBytesError); errors.As(err, &mbe) {
            return http.StatusRequestEntityTooLarge, "body exceeds 1 MiB"
        }
        return http.StatusBadRequest, "malformed JSON: " + err.Error()
    }
    if err := dec.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
        return http.StatusBadRequest, "body must contain a single JSON object"
    }
    return 0, ""
}

func parseID(r *http.Request) (int64, bool) {
    id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
    return id, err == nil && id > 0
}

func (s *Server) createItem(w http.ResponseWriter, r *http.Request) {
    var in itemInput
    if status, msg := decodeJSON(w, r, &in); status != 0 { s.problem(w, r, status, msg, nil); return }
    if fields := in.normalize(); len(fields) > 0 {
        s.problem(w, r, http.StatusUnprocessableEntity, "validation failed", fields)
        return
    }
    it, err := s.q.CreateItem(r.Context(), store.CreateItemParams{Name: in.Name, PriceCents: in.PriceCents})
    if err != nil { s.internal(w, r, err); return }
    w.Header().Set("Location", fmt.Sprintf("/v1/items/%d", it.ID))
    writeJSON(w, http.StatusCreated, toDTO(it))
}

func (s *Server) getItem(w http.ResponseWriter, r *http.Request) {
    id, ok := parseID(r)
    if !ok { s.problem(w, r, http.StatusBadRequest, "invalid id", nil); return }
    it, err := s.q.GetItem(r.Context(), id)
    switch {
    case errors.Is(err, pgx.ErrNoRows):
        s.problem(w, r, http.StatusNotFound, "item not found", nil)
    case err != nil:
        s.internal(w, r, err)
    default:
        writeJSON(w, http.StatusOK, toDTO(it))
    }
}

func (s *Server) listItems(w http.ResponseWriter, r *http.Request) {
    q := r.URL.Query()
    after, limit := int64(0), 50
    if v := q.Get("after"); v != "" {
        n, err := strconv.ParseInt(v, 10, 64)
        if err != nil || n < 0 { s.problem(w, r, http.StatusBadRequest, "after must be a non-negative integer", nil); return }
        after = n
    }
    if v := q.Get("limit"); v != "" {
        n, err := strconv.Atoi(v)
        if err != nil || n < 1 || n > 100 { s.problem(w, r, http.StatusBadRequest, "limit must be 1-100", nil); return }
        limit = n
    }
    items, err := s.q.ListItems(r.Context(), store.ListItemsParams{AfterID: after, PageSize: int32(limit)})
    if err != nil { s.internal(w, r, err); return }
    out := struct {
        Items     []itemDTO `json:"items"`
        NextAfter *int64    `json:"next_after,omitempty"`  // keyset pagination cursor
    }{Items: make([]itemDTO, 0, len(items))}
    for _, it := range items { out.Items = append(out.Items, toDTO(it)) }
    if len(items) == limit { last := items[len(items)-1].ID; out.NextAfter = &last }
    writeJSON(w, http.StatusOK, out)
}

func (s *Server) updateItem(w http.ResponseWriter, r *http.Request) {
    id, ok := parseID(r)
    if !ok { s.problem(w, r, http.StatusBadRequest, "invalid id", nil); return }
    var in itemInput
    if status, msg := decodeJSON(w, r, &in); status != 0 { s.problem(w, r, status, msg, nil); return }
    if fields := in.normalize(); len(fields) > 0 {
        s.problem(w, r, http.StatusUnprocessableEntity, "validation failed", fields)
        return
    }
    it, err := s.q.UpdateItem(r.Context(), store.UpdateItemParams{ID: id, Name: in.Name, PriceCents: in.PriceCents})
    switch {
    case errors.Is(err, pgx.ErrNoRows):
        s.problem(w, r, http.StatusNotFound, "item not found", nil)
    case err != nil:
        s.internal(w, r, err)
    default:
        writeJSON(w, http.StatusOK, toDTO(it))
    }
}

func (s *Server) deleteItem(w http.ResponseWriter, r *http.Request) {
    id, ok := parseID(r)
    if !ok { s.problem(w, r, http.StatusBadRequest, "invalid id", nil); return }
    n, err := s.q.DeleteItem(r.Context(), id)
    switch {
    case err != nil:
        s.internal(w, r, err)
    case n == 0:
        s.problem(w, r, http.StatusNotFound, "item not found", nil)
    default:
        w.WriteHeader(http.StatusNoContent)
    }
}
```

## cmd/itemsd/main.go

```go
func main() {
    if err := run(context.Background(), os.Getenv, os.Stdout); err != nil {
        fmt.Fprintln(os.Stderr, "itemsd:", err)
        os.Exit(1)
    }
}

type config struct {
    Addr, DatabaseURL           string
    LogLevel                    slog.Level
    DrainDelay, ShutdownTimeout time.Duration
}

func loadConfig(getenv func(string) string) (config, error) {
    c := config{Addr: ":8080", DrainDelay: 5 * time.Second, ShutdownTimeout: 15 * time.Second}
    var errs []error
    if v := getenv("ADDR"); v != "" { c.Addr = v }
    if c.DatabaseURL = getenv("DATABASE_URL"); c.DatabaseURL == "" {
        errs = append(errs, errors.New("DATABASE_URL is required"))
    }
    if v := getenv("LOG_LEVEL"); v != "" {
        if err := c.LogLevel.UnmarshalText([]byte(v)); err != nil { errs = append(errs, fmt.Errorf("LOG_LEVEL: %w", err)) }
    }
    for name, dst := range map[string]*time.Duration{"DRAIN_DELAY": &c.DrainDelay, "SHUTDOWN_TIMEOUT": &c.ShutdownTimeout} {
        if v := getenv(name); v != "" {
            d, err := time.ParseDuration(v)
            if err != nil { errs = append(errs, fmt.Errorf("%s: %w", name, err)); continue }
            *dst = d
        }
    }
    return c, errors.Join(errs...)
}

func run(ctx context.Context, getenv func(string) string, stdout io.Writer) error {
    ctx, stop := signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)
    defer stop()
    cfg, err := loadConfig(getenv)
    if err != nil { return fmt.Errorf("config: %w", err) }
    logger := slog.New(api.ContextHandler{Handler: slog.NewJSONHandler(stdout, &slog.HandlerOptions{Level: cfg.LogLevel})})

    pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
    if err != nil { return fmt.Errorf("db pool: %w", err) }
    defer pool.Close()                                      // runs last
    pingCtx, cancelPing := context.WithTimeout(ctx, 5*time.Second)
    defer cancelPing()
    if err := pool.Ping(pingCtx); err != nil { return fmt.Errorf("db ping: %w", err) }

    app := api.New(store.New(pool), logger, pool.Ping)
    cop := http.NewCrossOriginProtection()
    srv := &http.Server{
        Handler:           api.Chain(app.Routes(), api.RequestID, api.AccessLog(logger), api.Recover(logger), cop.Handler),
        ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second,
        WriteTimeout: 30 * time.Second, IdleTimeout: 120 * time.Second, MaxHeaderBytes: 64 << 10,
        ErrorLog: slog.NewLogLogger(logger.Handler(), slog.LevelWarn),
    }
    ln, err := net.Listen("tcp", cfg.Addr)                 // bind errors surface here, synchronously
    if err != nil { return fmt.Errorf("listen: %w", err) }
    errc := make(chan error, 1)
    go func() { errc <- srv.Serve(ln) }()
    app.SetReady(true)
    logger.Info("serving", slog.String("addr", ln.Addr().String()))

    select {
    case err := <-errc:
        return fmt.Errorf("serve: %w", err)
    case <-ctx.Done():
    }
    stop()                                                  // a second signal now kills the process
    app.SetReady(false)
    logger.Info("draining", slog.Duration("delay", cfg.DrainDelay))
    time.Sleep(cfg.DrainDelay)
    sctx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
    defer cancel()
    if err := srv.Shutdown(sctx); err != nil { return fmt.Errorf("shutdown: %w", err) }
    if err := <-errc; !errors.Is(err, http.ErrServerClosed) { return fmt.Errorf("serve: %w", err) }
    logger.Info("stopped")
    return nil
}
```

## internal/api/items_integration_test.go

```go
//go:build integration

package api_test

func TestItemsCRUD(t *testing.T) {
    pool := newDB(t)          // Postgres container + goose migrations: harness in go-testing-fuzzing
    app := api.New(store.New(pool), slog.New(slog.DiscardHandler), pool.Ping)
    ts := httptest.NewServer(app.Routes())
    t.Cleanup(ts.Close)

    resp, body := call(t, ts, "POST", "/v1/items", `{"name":" widget ","price_cents":1299}`)
    if resp.StatusCode != http.StatusCreated { t.Fatalf("POST /v1/items = %d %s, want 201", resp.StatusCode, body) }
    if loc := resp.Header.Get("Location"); loc != "/v1/items/1" { t.Errorf("Location = %q, want /v1/items/1", loc) }

    resp, body = call(t, ts, "GET", "/v1/items/1", "")
    if resp.StatusCode != http.StatusOK { t.Fatalf("GET /v1/items/1 = %d, want 200", resp.StatusCode) }
    golden(t, "get_item.json", normalize(t, body))          // golden helper: see go-testing-fuzzing

    resp, body = call(t, ts, "POST", "/v1/items", `{"name":"","price_cents":-1}`)
    if resp.StatusCode != http.StatusUnprocessableEntity || !strings.Contains(body, `"price_cents"`) || !strings.Contains(body, `"name"`) {
        t.Errorf("invalid POST = %d %s, want 422 naming both fields", resp.StatusCode, body)
    }
    if resp, _ = call(t, ts, "DELETE", "/v1/items/1", ""); resp.StatusCode != http.StatusNoContent {
        t.Errorf("DELETE = %d, want 204", resp.StatusCode)
    }
    if resp, _ = call(t, ts, "GET", "/v1/items/1", ""); resp.StatusCode != http.StatusNotFound {
        t.Errorf("GET after DELETE = %d, want 404", resp.StatusCode)
    }
}

func call(t *testing.T, ts *httptest.Server, method, path, body string) (*http.Response, string) {
    t.Helper()
    req, err := http.NewRequestWithContext(t.Context(), method, ts.URL+path, strings.NewReader(body))
    if err != nil { t.Fatal(err) }
    req.Header.Set("Content-Type", "application/json")
    resp, err := ts.Client().Do(req)
    if err != nil { t.Fatal(err) }
    defer resp.Body.Close()
    b, err := io.ReadAll(resp.Body)
    if err != nil { t.Fatal(err) }
    return resp, string(b)
}

func normalize(t *testing.T, body string) []byte {
    t.Helper()
    var m map[string]any
    if err := json.Unmarshal([]byte(body), &m); err != nil { t.Fatal(err) }
    if _, ok := m["created_at"]; ok { m["created_at"] = "<time>" }
    out, err := json.MarshalIndent(m, "", "  ")            // map keys marshal sorted: stable bytes
    if err != nil { t.Fatal(err) }
    return append(out, '\n')
}
```

`testdata/get_item.json`:

```json
{
  "created_at": "<time>",
  "id": 1,
  "name": "widget",
  "price_cents": 1299
}
```

Unit tests without Docker use a map-backed fake `Store` and drive `app.Routes().ServeHTTP(rec, req)`
so patterns, status codes and problem bodies are covered on every push.
