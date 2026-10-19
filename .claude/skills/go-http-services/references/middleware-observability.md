# Middleware and observability code

Copy-ready pieces referenced by the skill. Standard library plus `prometheus/client_golang`,
`go.opentelemetry.io/otel` and `otelhttp`; check the versions in go.mod before copying option names.

## 1. Context keys and request ID

```go
type ctxKey int

const (
    requestIDKey ctxKey = iota
    principalKey
)

func RequestIDFrom(ctx context.Context) string { s, _ := ctx.Value(requestIDKey).(string); return s }

var validID = regexp.MustCompile(`^[A-Za-z0-9._-]{8,64}$`)

// RequestID trusts an inbound X-Request-ID only when it looks sane (set by our own proxy).
func RequestID(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        id := r.Header.Get("X-Request-ID")
        if !validID.MatchString(id) {
            id = rand.Text()                                // crypto/rand, Go 1.24+
        }
        w.Header().Set("X-Request-ID", id)
        next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), requestIDKey, id)))
    })
}
```

## 2. Status-capturing writer, access log, recover

```go
type statusRecorder struct {
    http.ResponseWriter
    status int
    bytes  int64
}

func (s *statusRecorder) WriteHeader(code int) {
    if s.status == 0 { s.status = code }
    s.ResponseWriter.WriteHeader(code)
}

func (s *statusRecorder) Write(b []byte) (int, error) {
    if s.status == 0 { s.status = http.StatusOK }
    n, err := s.ResponseWriter.Write(b)
    s.bytes += int64(n)
    return n, err
}

// Unwrap lets http.NewResponseController reach Flush, Hijack and deadlines on the real writer.
func (s *statusRecorder) Unwrap() http.ResponseWriter { return s.ResponseWriter }

func AccessLog(log *slog.Logger) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            start := time.Now()
            rec := &statusRecorder{ResponseWriter: w}
            next.ServeHTTP(rec, r)
            if rec.status == 0 { rec.status = http.StatusOK }   // handler wrote nothing
            route := r.Pattern                                    // set by ServeMux during next.ServeHTTP
            if route == "" { route = "unmatched" }
            log.LogAttrs(r.Context(), slog.LevelInfo, "http request",
                slog.String("route", route), slog.String("method", r.Method),
                slog.Int("status", rec.status), slog.Int64("bytes", rec.bytes),
                slog.Duration("duration", time.Since(start)))
        })
    }
}

func Recover(log *slog.Logger) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            defer func() {
                v := recover()
                if v == nil { return }
                if v == http.ErrAbortHandler { panic(v) }         // deliberate abort: let net/http handle it
                log.ErrorContext(r.Context(), "panic", slog.Any("panic", v), slog.String("stack", string(debug.Stack())))
                http.Error(w, http.StatusText(http.StatusInternalServerError), http.StatusInternalServerError)
            }()
            next.ServeHTTP(w, r)
        })
    }
}
```

If the panic happens after the handler started writing, the 500 cannot replace the status already
sent; the access log then shows the original status. Only the outermost recover should write.

## 3. Authentication

```go
type Principal struct{ Subject string; Scopes []string }

type Verifier interface {                                   // consumer-side, one method
    Verify(ctx context.Context, token string) (Principal, error)
}

func RequireAuth(v Verifier) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            tok, ok := strings.CutPrefix(r.Header.Get("Authorization"), "Bearer ")
            if !ok || tok == "" {
                w.Header().Set("WWW-Authenticate", `Bearer`)
                http.Error(w, "unauthenticated", http.StatusUnauthorized)
                return
            }
            p, err := v.Verify(r.Context(), tok)
            if err != nil {
                http.Error(w, "unauthenticated", http.StatusUnauthorized)   // do not echo the reason
                return
            }
            next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), principalKey, p)))
        })
    }
}
```

Static shared secrets: compare with `subtle.ConstantTimeCompare([]byte(tok), []byte(want)) == 1`.
401 = who are you; 403 = known principal without permission (check scopes in the handler or a
second middleware).

## 4. slog handler that adds context attributes

```go
type ContextHandler struct{ slog.Handler }

func (h ContextHandler) Handle(ctx context.Context, r slog.Record) error {
    if id := RequestIDFrom(ctx); id != "" {
        r.AddAttrs(slog.String("request_id", id))
    }
    if sc := trace.SpanContextFromContext(ctx); sc.HasTraceID() {   // go.opentelemetry.io/otel/trace
        r.AddAttrs(slog.String("trace_id", sc.TraceID().String()), slog.String("span_id", sc.SpanID().String()))
    }
    return h.Handler.Handle(ctx, r)
}

// Without these two methods logger.With(...) returns the inner handler and drops the context attrs.
func (h ContextHandler) WithAttrs(as []slog.Attr) slog.Handler { return ContextHandler{h.Handler.WithAttrs(as)} }
func (h ContextHandler) WithGroup(name string) slog.Handler    { return ContextHandler{h.Handler.WithGroup(name)} }
```

Redaction: `type Secret string; func (Secret) LogValue() slog.Value { return slog.StringValue("[redacted]") }`.
Runtime level: `var lvl slog.LevelVar` in `HandlerOptions{Level: &lvl}`, change with `lvl.Set(slog.LevelDebug)`
from an admin endpoint.

## 5. OpenTelemetry setup

```go
func setupTracing(ctx context.Context) (shutdown func(context.Context) error, err error) {
    exp, err := otlptracegrpc.New(ctx)                     // endpoint from OTEL_EXPORTER_OTLP_ENDPOINT
    if err != nil { return nil, err }
    tp := sdktrace.NewTracerProvider(
        sdktrace.WithBatcher(exp),
        sdktrace.WithResource(resource.Default()),         // OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES
    )
    otel.SetTracerProvider(tp)
    otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(propagation.TraceContext{}, propagation.Baggage{}))
    return tp.Shutdown, nil
}
```

Wrap the outermost handler with `otelhttp.NewHandler(h, "api", otelhttp.WithSpanNameFormatter(...))`
and outgoing transports with `otelhttp.NewTransport(base)`. The span name formatter runs again after
routing, so `r.Pattern` is available for span names. Call `shutdown` during graceful shutdown with
its own short timeout so buffered spans are flushed.

## 6. Prometheus RED metrics and the admin mux

```go
type HTTPMetrics struct {
    requests *prometheus.CounterVec
    duration *prometheus.HistogramVec
}

func NewHTTPMetrics(reg prometheus.Registerer) *HTTPMetrics {
    m := &HTTPMetrics{
        requests: prometheus.NewCounterVec(prometheus.CounterOpts{
            Name: "http_requests_total", Help: "HTTP requests by route, method and status code.",
        }, []string{"route", "method", "code"}),
        duration: prometheus.NewHistogramVec(prometheus.HistogramOpts{
            Name: "http_request_duration_seconds", Help: "HTTP request latency by route and method.",
            Buckets: prometheus.DefBuckets,
        }, []string{"route", "method"}),
    }
    reg.MustRegister(m.requests, m.duration)
    return m
}

func (m *HTTPMetrics) Middleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        start := time.Now()
        rec := &statusRecorder{ResponseWriter: w}
        next.ServeHTTP(rec, r)
        route := r.Pattern
        if route == "" { route = "unmatched" }                // bounded label set
        if rec.status == 0 { rec.status = http.StatusOK }
        m.requests.WithLabelValues(route, r.Method, strconv.Itoa(rec.status)).Inc()
        m.duration.WithLabelValues(route, r.Method).Observe(time.Since(start).Seconds())
    })
}

func AdminMux(reg *prometheus.Registry) *http.ServeMux {
    mux := http.NewServeMux()
    mux.Handle("GET /metrics", promhttp.HandlerFor(reg, promhttp.HandlerOpts{}))
    mux.HandleFunc("/debug/pprof/", pprof.Index)             // also serves heap, goroutine, goroutineleak (1.27)...
    mux.HandleFunc("/debug/pprof/cmdline", pprof.Cmdline)
    mux.HandleFunc("/debug/pprof/profile", pprof.Profile)
    mux.HandleFunc("/debug/pprof/symbol", pprof.Symbol)
    mux.HandleFunc("/debug/pprof/trace", pprof.Trace)
    return mux
}
```

Registry: `reg := prometheus.NewRegistry(); reg.MustRegister(collectors.NewGoCollector(),
collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}))`. Serve `AdminMux` on its own
`http.Server` bound to `127.0.0.1:9090` (or a port the Service does not expose) with the same
timeouts, and shut it down after the public server. Reading profiles: `go-profiling-pprof`.

## 7. Health endpoints

```go
func Health(ready *atomic.Bool, ping func(context.Context) error) (live, readyz http.HandlerFunc) {
    live = func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusNoContent) }
    readyz = func(w http.ResponseWriter, r *http.Request) {
        if !ready.Load() { http.Error(w, "draining", http.StatusServiceUnavailable); return }
        ctx, cancel := context.WithTimeout(r.Context(), time.Second)
        defer cancel()
        if err := ping(ctx); err != nil { http.Error(w, "db unavailable", http.StatusServiceUnavailable); return }
        w.WriteHeader(http.StatusNoContent)
    }
    return live, readyz
}
```

Register as `GET /livez` and `GET /readyz`; with pgxpool, `ping` is `pool.Ping`.
