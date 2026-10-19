# Mapping Go errors at HTTP and gRPC boundaries

One mapping function per transport, one log line per failed request, no internals in responses.

## HTTP: problem+json (RFC 9457)

```go
type FieldError struct {
    Field  string `json:"field"`
    Reason string `json:"reason"`
}
type Problem struct {
    Type   string       `json:"type,omitempty"`   // URI identifying the problem kind
    Title  string       `json:"title"`
    Status int          `json:"status"`
    Detail string       `json:"detail,omitempty"`
    Errors []FieldError `json:"errors,omitempty"` // extension member for validation
}

func problemOf(err error) Problem {
    switch {
    case errors.Is(err, store.ErrNotFound):
        return Problem{Title: "not found", Status: http.StatusNotFound}
    case errors.Is(err, store.ErrConflict):
        return Problem{Title: "conflict", Status: http.StatusConflict}
    case errors.Is(err, context.DeadlineExceeded):
        return Problem{Title: "timeout", Status: http.StatusGatewayTimeout}
    }
    var mbe *http.MaxBytesError
    if errors.As(err, &mbe) {
        return Problem{Title: "request body too large", Status: http.StatusRequestEntityTooLarge,
            Detail: fmt.Sprintf("limit is %d bytes", mbe.Limit)}
    }
    var syn *json.SyntaxError
    var typ *json.UnmarshalTypeError
    if errors.As(err, &syn) || errors.As(err, &typ) || errors.Is(err, io.ErrUnexpectedEOF) {
        return Problem{Title: "malformed JSON", Status: http.StatusBadRequest}
    }
    var fields []FieldError
    for _, e := range flatten(err) {                       // collects every *ValidationError in a Join
        if ve, ok := e.(*user.ValidationError); ok { fields = append(fields, FieldError{ve.Field, ve.Reason}) }
    }
    if len(fields) > 0 {
        return Problem{Title: "validation failed", Status: http.StatusUnprocessableEntity, Errors: fields}
    }
    return Problem{Title: "internal error", Status: http.StatusInternalServerError}
}

// flatten walks Unwrap() error and Unwrap() []error depth-first.
func flatten(err error) []error {
    if err == nil { return nil }
    out := []error{err}
    switch u := err.(type) {
    case interface{ Unwrap() []error }:
        for _, e := range u.Unwrap() { out = append(out, flatten(e)...) }
    case interface{ Unwrap() error }:
        out = append(out, flatten(u.Unwrap())...)
    }
    return out
}

func writeProblem(w http.ResponseWriter, r *http.Request, err error) {
    p := problemOf(err)
    switch {
    case p.Status >= 500:
        slog.ErrorContext(r.Context(), "request failed", "err", err, "route", r.Pattern, "status", p.Status)
    case errors.Is(err, context.Canceled):
        slog.DebugContext(r.Context(), "client went away", "route", r.Pattern)
        return                                              // nobody is listening
    }
    w.Header().Set("Content-Type", "application/problem+json")
    w.WriteHeader(p.Status)
    _ = json.NewEncoder(w).Encode(p)                        // write errors here mean the client left
}
```

Notes:
- Error types and messages from `encoding/json` decoding can differ between Go versions (1.27 backs
  `encoding/json` with the v2 implementation); match types, never message text.
- `http.MaxBytesReader(w, r.Body, n)` produces `*http.MaxBytesError` once the limit is exceeded.
- `json.Decoder.DisallowUnknownFields` reports unknown fields as a plain error: treat any decode
  error that is not one of the typed cases above as 400 as well, if the body came from a client.
- Once headers are written (streaming responses), the status cannot change: log and abort.

## HTTP middleware order

```go
handler := recoverMW(requestIDMW(logMW(mux)))   // outermost recovers panics from everything inside
```

The logging middleware records method, route, status and latency for every request; the error log
line comes only from `writeProblem` for 5xx, so a failure is logged once.

## gRPC: server interceptor

```go
func errorInterceptor(log *slog.Logger) grpc.UnaryServerInterceptor {
    return func(ctx context.Context, req any, info *grpc.UnaryServerInfo, h grpc.UnaryHandler) (resp any, err error) {
        defer func() {
            if r := recover(); r != nil {
                log.ErrorContext(ctx, "panic", "method", info.FullMethod, "value", r, "stack", string(debug.Stack()))
                resp, err = nil, status.Error(codes.Internal, "internal error")
            }
        }()
        resp, err = h(ctx, req)
        if err == nil { return resp, nil }
        if _, ok := status.FromError(err); ok { return nil, err } // already a status (or wraps one)
        st := toStatus(err)                                        // domain mapping from SKILL.md
        if status.Code(st) == codes.Internal {
            log.ErrorContext(ctx, "rpc failed", "method", info.FullMethod, "err", err)
        }
        return nil, st
    }
}

srv := grpc.NewServer(grpc.ChainUnaryInterceptor(errorInterceptor(logger)))
```

Streaming RPCs need the matching `grpc.StreamServerInterceptor`. The grpc-ecosystem middleware
module (`github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/recovery`) provides a
ready-made recovery interceptor.

## gRPC: client side

```go
resp, err := client.GetUser(ctx, req)
if err != nil {
    st := status.Convert(err)                      // never nil; Unknown for non-status errors
    switch st.Code() {
    case codes.NotFound:
        return nil, fmt.Errorf("get user %d: %w", id, ErrNotFound) // back into the domain
    case codes.InvalidArgument:
        for _, d := range st.Details() {
            if br, ok := d.(*errdetails.BadRequest); ok {
                for _, v := range br.GetFieldViolations() { log.Info("bad field", "field", v.GetField(), "why", v.GetDescription()) }
            }
        }
        return nil, fmt.Errorf("get user %d: %w", id, ErrInvalid)
    case codes.Unavailable, codes.DeadlineExceeded, codes.ResourceExhausted:
        return nil, fmt.Errorf("get user %d: %w", id, ErrRetryable) // retry only idempotent calls, with backoff
    default:
        return nil, fmt.Errorf("get user %d: %v", id, err)       // %v: do not leak transport types upward
    }
}
```

## Retry decision table

| Signal | Retry? |
|---|---|
| HTTP 408, 429, 502, 503, 504; gRPC `Unavailable`, `ResourceExhausted` | yes, with exponential backoff and jitter, honour `Retry-After` |
| gRPC `DeadlineExceeded`, HTTP 504 | only if the overall deadline still has budget and the call is idempotent |
| `context.Canceled` | never: the caller gave up |
| 4xx other than 408/429; `InvalidArgument`, `NotFound`, `PermissionDenied` | never |
| network errors with `Timeout() == true` before the request was sent | yes for idempotent calls |
