---
name: go-error-handling
description: "Go error handling: sentinel vs typed vs opaque errors, the API contract created by %w, errors.Is, As, AsType and Join, handle-or-return discipline, panic and recover boundaries, logging errors once with slog, deferred Close errors, and HTTP/gRPC error mapping. Load when designing error types, fixing lost context or duplicate logs, or reviewing Go error paths."
when_to_use: "Go code returning error; fmt.Errorf with %w or %v; errors.Is/As/AsType/Join; custom error types; one failure logged at several layers; 'err != nil' true for an error that looks nil; panics in goroutines or handlers; mapping errors to HTTP status or gRPC codes; errorlint, wrapcheck, nilerr, nilnil or errcheck findings; ignored Close errors on files."
---

# Go error handling

Baseline Go 1.26/1.27. Version map: `%w`, `errors.Is/As/Unwrap` 1.13; `errors.Join`, multiple
`%w`, `Unwrap() []error` 1.20; `log/slog`, `errors.ErrUnsupported`, `panic(nil)` becoming
`*runtime.PanicNilError` 1.21; `errors.AsType` 1.26; vet `printf` reports `%w` applied to a `*E`
whose `E` already implements `error` (1.27).

Deep material: [boundary mapping](references/boundary-mapping.md) (problem+json, middleware, gRPC
interceptor, client-side status handling) | [stdlib error catalogue](references/stdlib-errors.md)
(how to test io, fs, net, url, sql, json, http, exec and context errors)

## 1. Choose the error kind

| Kind | Declare | Caller checks | Use when | Cost |
|---|---|---|---|---|
| opaque | `fmt.Errorf("...: %v", err)`, unexported types | `err != nil` only | the caller can only report; library internals stay private | caller cannot branch |
| sentinel | `var ErrNotFound = errors.New("not found")` | `errors.Is(err, ErrNotFound)` | callers branch on identity; no data needed | exported forever; carries no data |
| typed | `type ValidationError struct{ Field, Reason string }`, `Error()` on the pointer | `errors.AsType[*ValidationError](err)` | callers need fields (field name, retry-after, limit) | the type and its fields are API |
| behaviour | unexported type with `Timeout() bool`, `Temporary() bool`, `HTTPStatus() int` | `errors.As(err, &iface)` then call | stable APIs across packages without importing types | weakly typed |

Start opaque; promote to sentinel or typed only when a real caller needs to branch. Naming:
`ErrX` for sentinels, `XError` for types (lint `errname`). Messages are lowercase, no trailing
punctuation (staticcheck ST1005), no "failed to" or "error:" prefixes.

## 2. Wrapping

```go
u, err := s.q.GetUser(ctx, id)
if err != nil {
    return nil, fmt.Errorf("get user %d: %w", id, err) // operation + key IDs
}
// chain: "load profile: get user 42: query users: dial tcp 10.0.0.5:5432: connect: connection refused"
```

| Rule | Do | Do not |
|---|---|---|
| add context the caller lacks | `fmt.Errorf("parse config %s: %w", path, err)` | `"failed to parse: %w"`, `"error: %w"` |
| do not repeat the callee | `os.Open` already names the path: `fmt.Errorf("load config: %w", err)` | `"open %s: %w"` giving `open a.yml: open a.yml: no such file` |
| `%w` makes the wrapped error part of your API | wrap your own sentinels and types | wrap driver errors across package boundaries (callers start matching `pq` errors) |
| `%v` hides identity, keeps text | `fmt.Errorf("lookup %s: %v", host, err)` | `%v` when callers must see `context.Canceled` (re-expose it, section 11) |
| translate at the boundary of your package | `sql.ErrNoRows` becomes `ErrNotFound` | leaking `sql.ErrNoRows` to handlers |
| several causes | `fmt.Errorf("sync %s: %w (rollback: %w)", id, err, rbErr)` | dropping the rollback error |
| aggregate | `errors.Join(errs...)`: nil if all nil; messages joined with `\n` | concatenating strings |
| `io.EOF` from a `Reader` | return `io.EOF` itself: callers compare with `==` | `fmt.Errorf("read: %w", io.EOF)` inside `Read` |
| wrap the error value, not a pointer to it | `%w` with `err` | `%w` with `&myErr` when `MyErr` implements `error` (vet 1.27) |

```go
func (r CreateUser) Validate() error {
    var errs []error
    if r.Email == "" { errs = append(errs, &ValidationError{Field: "email", Reason: "required"}) }
    if utf8.RuneCountInString(r.Name) > 100 { errs = append(errs, &ValidationError{Field: "name", Reason: "max 100 characters"}) }
    return errors.Join(errs...)                         // nil when valid
}
```

## 3. Inspection

| API | Matches | Note |
|---|---|---|
| `errors.Is(err, target)` | `==` anywhere in the tree, or an `Is(error) bool` method | `errors.Is(nil, nil)` is true: handy in table tests |
| `errors.As(err, &target)` | first error assignable to the target type, or an `As(any) bool` method | target must be a non-nil pointer to an error type or interface, else panic (vet `errorsas`) |
| `errors.AsType[E](err) (E, bool)` | same search, generic | 1.26+; type-safe and faster than `As` |
| `errors.Unwrap(err)` | one `Unwrap() error` level | returns nil for `Join` and multi-`%w` errors |
| tree walk | `Unwrap() error` and `Unwrap() []error` | depth-first; `Is`/`As` see every branch |

```go
if ve, ok := errors.AsType[*ValidationError](err); ok { return badRequest(ve.Field, ve.Reason) } // 1.26+
var ve *ValidationError                                  // before 1.26
if errors.As(err, &ve) { return badRequest(ve.Field, ve.Reason) }

type QueryError struct{ Query string; Err error }        // typed error that keeps its cause
func (e *QueryError) Error() string { return "query " + e.Query + ": " + e.Err.Error() }
func (e *QueryError) Unwrap() error { return e.Err }

type CodeError struct{ Code, Msg string }                // custom Is: match by code
func (e *CodeError) Error() string { return e.Code + ": " + e.Msg }
func (e *CodeError) Is(target error) bool {              // shallow: never call Unwrap here
    t, ok := target.(*CodeError)
    return ok && t.Code == e.Code
}
var ErrRateLimited = &CodeError{Code: "rate_limited"}    // errors.Is(err, ErrRateLimited) for any message

var te interface{ Timeout() bool }                       // behaviour check, no type import
if errors.As(err, &te) && te.Timeout() { return retryLater(err) }
```

## 4. Handle or return, never both

| Layer | Responsibility |
|---|---|
| store / client | translate driver and transport errors into domain errors; wrap with context; return |
| service | add operation context; branch only where policy needs it (retry, fallback); return |
| boundary: HTTP handler, gRPC method, worker loop, `main` | log once with full context, map to a response or exit code, stop propagation |

Logging and returning at each layer turns one failure into N log lines, each with partial context.
Log at the boundary with slog; 4xx outcomes are client errors (debug level or a metric), 5xx are
errors:

```go
slog.ErrorContext(ctx, "request failed",
    slog.Any("err", err),                 // handlers render err.Error() for top-level error values
    slog.String("route", r.Pattern),      // ServeMux pattern (1.23+)
    slog.Int("status", code))
```

`LogValuer` controls how a value renders and is resolved lazily; use it for redaction and
structure. It applies to the value passed in, not to errors wrapped inside another error:

```go
func (u User) LogValue() slog.Value { return slog.GroupValue(slog.Int64("id", u.ID)) } // never logs email
func (e *ValidationError) LogValue() slog.Value {
    return slog.GroupValue(slog.String("msg", e.Error()), slog.String("field", e.Field))
}
```

`JSONHandler` calls `Error()` only for top-level error attributes; an error stored in a struct field
and logged with `slog.Any` is JSON-marshalled, usually as `{}`.

## 5. Panics

| Situation | Action |
|---|---|
| programmer error, broken invariant | panic (or `log.Fatal` in `main` at startup) |
| bad input, I/O failure, timeout | return an error; never panic |
| panic inside a net/http handler | the server recovers per request; add middleware to log with context and return 500 |
| panic in a goroutine you started | kills the whole process; only a `recover` inside that goroutine helps |
| `panic(http.ErrAbortHandler)` | aborts the response; the server does not log it |
| `panic(nil)` | with go.mod `go` 1.21+, `recover()` returns a `*runtime.PanicNilError`, not nil |
| `recover()` | works only when called directly by a deferred function |

```go
g.Go(func() (err error) {                       // errgroup does not recover panics: convert here
    defer func() {
        if r := recover(); r != nil { err = fmt.Errorf("task %s: panic: %v\n%s", id, r, debug.Stack()) }
    }()
    return task(gctx, id)
})

func recoverMW(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        defer func() {
            if v := recover(); v != nil {
                if v == http.ErrAbortHandler { panic(v) }   // keep net/http's abort semantics
                slog.ErrorContext(r.Context(), "panic", "value", v, "stack", string(debug.Stack()))
                http.Error(w, "internal error", http.StatusInternalServerError)
            }
        }()
        next.ServeHTTP(w, r)
    })
}
```

## 6. Boundary mapping

One function maps domain errors to transport status; messages for 5xx never contain internals.

| Condition | HTTP | gRPC `codes.` |
|---|---|---|
| not found | 404 | `NotFound` |
| validation failed | 422 (400 for malformed syntax) | `InvalidArgument` + `errdetails.BadRequest` |
| already exists / edit conflict | 409 | `AlreadyExists` / `Aborted` |
| precondition (version mismatch) | 412 or 409 | `FailedPrecondition` |
| not authenticated / not allowed | 401 / 403 | `Unauthenticated` / `PermissionDenied` |
| rate limited | 429 + `Retry-After` | `ResourceExhausted` |
| `context.DeadlineExceeded` | 504 (upstream timeout) or 503 | `DeadlineExceeded` |
| `context.Canceled` (client left) | nothing to send; log at debug (499 is an nginx convention) | `Canceled` |
| dependency down | 503 | `Unavailable` |
| anything else | 500, generic body | `Internal`, generic message |

```go
func statusOf(err error) (int, string) {
    switch {
    case errors.Is(err, store.ErrNotFound): return http.StatusNotFound, "not found"
    case errors.Is(err, store.ErrConflict): return http.StatusConflict, "conflict"
    case errors.Is(err, context.DeadlineExceeded): return http.StatusGatewayTimeout, "timeout"
    }
    if ve, ok := errors.AsType[*user.ValidationError](err); ok {
        return http.StatusUnprocessableEntity, ve.Error()
    }
    return http.StatusInternalServerError, "internal error"   // details only in the log
}

func toStatus(err error) error {                              // gRPC
    switch {
    case errors.Is(err, store.ErrNotFound): return status.Error(codes.NotFound, "user not found")
    case errors.Is(err, context.DeadlineExceeded): return status.Error(codes.DeadlineExceeded, "deadline exceeded")
    }
    if ve, ok := errors.AsType[*user.ValidationError](err); ok {
        st, derr := status.New(codes.InvalidArgument, "invalid request").WithDetails(&errdetails.BadRequest{
            FieldViolations: []*errdetails.BadRequest_FieldViolation{{Field: ve.Field, Description: ve.Reason}}})
        if derr != nil { return status.Error(codes.InvalidArgument, ve.Error()) }
        return st.Err()
    }
    return status.Error(codes.Internal, "internal error")
}
```

A plain Go error returned by a gRPC handler reaches the client as `codes.Unknown` with the raw
`err.Error()` text: always convert. `status.Code(err)` and `status.FromError(err)` unwrap wrapped
status errors. Interceptor and client-side detail decoding: see the boundary mapping reference.

## 7. Nil-interface trap

```go
func (s *Service) check(u User) *ValidationError { ... return nil }  // concrete pointer result
func (s *Service) Validate(u User) error { return s.check(u) }       // BUG: never nil
```

The returned `error` holds `(*ValidationError)(nil)`: type set, value nil, so `err != nil` is true
and the caller reports a "<nil>" failure. Declare results as `error` everywhere and return a
literal `nil`; staticcheck SA4023 flags some impossible nil comparisons.

## 8. Deferred Close errors on writers

`Close` on a written file can report the write failure (delayed allocation, NFS, full disk);
`defer f.Close()` throws it away. Use a named result:

```go
func writeReport(path string, rep Report) (err error) {
    f, err := os.Create(path)
    if err != nil { return fmt.Errorf("create report: %w", err) }
    defer func() {
        if cerr := f.Close(); cerr != nil { err = errors.Join(err, fmt.Errorf("close %s: %w", path, cerr)) }
    }()
    w := bufio.NewWriter(f)
    if err := rep.Encode(w); err != nil { return fmt.Errorf("encode report: %w", err) }
    if err := w.Flush(); err != nil { return fmt.Errorf("flush report: %w", err) }
    if err := f.Sync(); err != nil { return fmt.Errorf("sync %s: %w", path, err) } // durable before success
    return nil
}
```

`return x` assigns the named result before deferred functions run, so the join sees it. Read-only
files and `resp.Body` keep a plain `defer x.Close()`.

## 9. Testing

```go
tests := []struct {
    name    string
    id      int64
    wantErr error                                  // nil means success; errors.Is(nil, nil) is true
}{
    {"found", 1, nil},
    {"missing", 2, store.ErrNotFound},
}
for _, tc := range tests {
    t.Run(tc.name, func(t *testing.T) {
        _, err := svc.Get(t.Context(), tc.id)
        if !errors.Is(err, tc.wantErr) { t.Fatalf("Get(%d) err = %v, want %v", tc.id, err, tc.wantErr) }
    })
}
```

- Typed errors: `ve, ok := errors.AsType[*ValidationError](err)` then assert fields, not text.
- Structs holding errors: `cmp.Diff(want, got, cmpopts.EquateErrors())` compares errors with
  `errors.Is`; `cmpopts.AnyError` matches any non-nil error.
- Golden error messages only where the text is the product (CLI output, user-facing validation);
  elsewhere assert identity so rewording a message breaks nothing.

## 10. Linters (golangci-lint v2)

| Linter | Flags |
|---|---|
| `errcheck` | unchecked errors (`check-type-assertions: true` adds unchecked `x.(T)`) |
| `errorlint` | `%v` on errors in `fmt.Errorf`, `==` comparisons, type assertions or switches on errors |
| `wrapcheck` | errors from other packages returned without wrapping |
| `nilerr` | returning nil after checking `err != nil` |
| `nilnil` | `return nil, nil` for pointer/interface results |
| `errname` | sentinel and type naming |

```yaml
version: "2"
linters:
  enable: [errcheck, errorlint, wrapcheck, nilerr, nilnil, errname]
  settings:
    errorlint: { errorf: true, asserts: true, comparison: true }
    wrapcheck:
      ignore-sigs: [".Errorf(", "errors.New(", "errors.Unwrap(", "errors.Join(", ".Wrap(", ".Wrapf(",
                    ".WithMessage(", ".WithMessagef(", ".WithStack(", "status.Error("]
```

Setting `ignore-sigs` replaces wrapcheck's default list, so repeat the defaults (as above, from the
wrapcheck README) and append your own constructors. Keep `go vet` (`printf`, `errorsas`) in the gate.

## 11. Worked example: store, service and handler mapped to 404 and 422

```go
// package store
var ErrNotFound = errors.New("not found")
func (s *Users) Get(ctx context.Context, id int64) (*User, error) {
    var u User
    err := s.db.QueryRowContext(ctx, `SELECT id, name FROM users WHERE id = $1`, id).Scan(&u.ID, &u.Name)
    switch {
    case errors.Is(err, sql.ErrNoRows):
        return nil, fmt.Errorf("user %d: %w", id, ErrNotFound)      // translate; sql stays private
    case err != nil && ctx.Err() != nil:
        return nil, fmt.Errorf("query user %d: %w", id, ctx.Err())  // keep cancel/deadline identity
    case err != nil:
        return nil, fmt.Errorf("query user %d: %v", id, err)        // driver error: text, not API
    }
    return &u, nil
}

// package user
type ValidationError struct{ Field, Reason string }
func (e *ValidationError) Error() string { return e.Field + ": " + e.Reason }

func (s *Service) Rename(ctx context.Context, id int64, name string) (*store.User, error) {
    if n := utf8.RuneCountInString(strings.TrimSpace(name)); n == 0 || n > 100 {
        return nil, &ValidationError{Field: "name", Reason: "must be 1-100 characters"}
    }
    u, err := s.users.Get(ctx, id)
    if err != nil { return nil, fmt.Errorf("rename user: %w", err) }
    u.Name = strings.TrimSpace(name)
    if err := s.users.Update(ctx, u); err != nil { return nil, fmt.Errorf("rename user %d: %w", id, err) }
    return u, nil
}

// package api, routed as mux.HandleFunc("PUT /users/{id}/name", h.rename)
func (h *Handler) rename(w http.ResponseWriter, r *http.Request) {
    var body struct{ Name string `json:"name"` }
    id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
    if err == nil { err = json.NewDecoder(r.Body).Decode(&body) }
    if err != nil { h.fail(w, r, &user.ValidationError{Field: "request", Reason: "bad id or JSON"}); return }
    u, err := h.svc.Rename(r.Context(), id, body.Name)
    if err != nil { h.fail(w, r, err); return }
    writeJSON(w, http.StatusOK, u)
}
func (h *Handler) fail(w http.ResponseWriter, r *http.Request, err error) {
    code, msg := statusOf(err)
    if code >= 500 { slog.ErrorContext(r.Context(), "request failed", "err", err, "route", r.Pattern) } // the one log
    writeJSON(w, code, map[string]string{"error": msg})
}
```

```go
func TestRename(t *testing.T) {
    h := api.NewHandler(user.NewService(&fakeUsers{m: map[int64]*store.User{1: {ID: 1, Name: "Ada"}}}))
    for _, tc := range []struct{ name, path, body string; code int; want string }{
        {"ok", "/users/1/name", `{"name":"Grace"}`, 200, `"Grace"`},
        {"missing", "/users/2/name", `{"name":"Grace"}`, 404, `{"error":"not found"}`},
        {"invalid", "/users/1/name", `{"name":""}`, 422, `{"error":"name: must be 1-100 characters"}`},
    } {
        t.Run(tc.name, func(t *testing.T) {
            rec := httptest.NewRecorder()
            h.ServeHTTP(rec, httptest.NewRequest(http.MethodPut, tc.path, strings.NewReader(tc.body)))
            if rec.Code != tc.code || !strings.Contains(rec.Body.String(), tc.want) {
                t.Fatalf("PUT %s = %d %q, want %d containing %q", tc.path, rec.Code, rec.Body, tc.code, tc.want)
            }
        })
    }
}
```

`fakeUsers.Get` returns `fmt.Errorf("user %d: %w", id, store.ErrNotFound)` for unknown IDs, so the
404 path is exercised through two wraps. On a database outage the client sees
`{"error":"internal error"}` and exactly one log line carries
`err="rename user: query user 1: dial tcp ...: connection refused"`.

## 12. Pitfalls

- Bare `return err` everywhere: the final message lacks every location it passed through.
- `err == ErrX` or `err.(*T)` after anyone wrapped it: silently false (errorlint).
- `os.IsNotExist(err)` does not unwrap: use `errors.Is(err, fs.ErrNotExist)`.
- `%v` on a driver error also hides `context.Canceled`: re-expose ctx errors as in section 11.
- Logging and returning: duplicate lines; logging 4xx at error level: noisy pages.
- Shadowed `err` in an inner `if err := ...` while the outer `err` is returned stale.
- `return nil, nil` from lookups: callers dereference nil; return `ErrNotFound` instead (nilnil).
- SQL text, stack traces or hostnames in a 500 body: information leak; keep them in logs.
- Panics as control flow or across package APIs: return errors; recover only at boundaries.
- `errors.As(err, ve)` with a non-pointer target panics at runtime (vet `errorsas`).

Related: `go-interfaces-generics`, `go-concurrency-context`, `go-http-services`,
`go-testing-fuzzing`, `go-modules-tooling`, hub `go-craft`.
