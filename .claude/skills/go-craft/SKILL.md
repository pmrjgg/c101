---
name: go-craft
description: "Go expertise pack covering interfaces and composition, error wrapping, generics and iterators, goroutines, channels and context, sync primitives, the race detector, pprof and execution traces, modules and workspaces, table-driven tests, fuzzing, benchmarks, and common pitfalls such as loop variables, nil interfaces and goroutine leaks. Load when writing, reviewing, debugging or profiling Go code."
when_to_use: "Any task touching .go files, go.mod/go.work, Go services (net/http, gRPC), goroutine leaks or races, Go performance and GC tuning, or Go CI gates."
---

# Go craft

Baseline: Go 1.26/1.27. Key recent changes: per-iteration loop variables (1.22, when go.mod says
`go 1.22`+), range-over-func iterators (1.23), `testing.B.Loop`, `t.Context()`, `os.Root`, `tool`
directives and generic type aliases (1.24), `testing/synctest`, `sync.WaitGroup.Go`, cgroup-aware
`GOMAXPROCS` and the trace flight recorder (1.25), `new(expr)`, `errors.AsType`, Green Tea GC on by
default, rewritten `go fix` modernizers and an experimental goroutine-leak profile (1.26); generic
methods (not on interfaces), `encoding/json` backed by the v2 implementation, `encoding/json/v2`
without GOEXPERIMENT, `synctest.Sleep`, `httptest.NewTestServer`, goroutine-leak profile GA and the
`stdversion` vet check in `go test` (1.27).
Language semantics follow the `go` line in go.mod, not the installed toolchain: check it first.

Deep material:
[concurrency patterns](references/concurrency-patterns.md) |
[profiling, GC tuning and tooling](references/profiling-tooling.md)

## 1. Orient in a repo

```bash
go version; go env GOVERSION GOFLAGS GOEXPERIMENT GOTOOLCHAIN
head -5 go.mod; ls go.work 2>/dev/null; grep -n '^tool' go.mod
go list -m all | wc -l                         # dependency count
ls .golangci.yml .golangci.yaml 2>/dev/null; grep -rn 'go:generate' --include=*.go . | head
go list ./... | head -30                        # package layout
```

Record: `go` directive (semantics), `toolchain` directive, linter config, generators, whether
the module is a library (API stability matters) or a service.

## 2. The gate

| Step | Command | Blocks when |
|---|---|---|
| Format | `test -z "$(gofmt -l .)"` (or `gofumpt -l .`) | any file listed |
| Vet + lint | `go vet ./... && golangci-lint run` (v2 config) or `staticcheck ./...` | any finding |
| Build | `go build ./...` | failure |
| Test with race detector | `go test -race -shuffle=on -count=1 ./...` | failure or race report |
| Tidy | `go mod tidy -diff` (1.23+) | non-empty diff |
| Vulnerabilities | `govulncheck ./...` | a reachable vulnerable symbol |
| Fuzz (changed parsers) | `go test -run=^$ -fuzz=FuzzX -fuzztime=60s ./pkg` | new crasher |

`-race` slows tests 2-20x and raises memory 5-10x; it only finds races on executed paths, so
tests must exercise the concurrent code.

## 3. Interfaces and composition

Rules:
1. Accept interfaces, return concrete types. Constructors return `*T`, not an interface.
2. Define interfaces where they are **consumed**, with only the methods that consumer calls.
   One- or two-method interfaces (`io.Reader`, `fmt.Stringer`) compose; twelve-method
   "repository" interfaces exist only for mocking and leak implementation shape.
3. Do not export an interface just to mock; tests can define their own small interface or use
   a fake implementation of the concrete dependency.
4. Compile-time conformance check: `var _ http.Handler = (*Server)(nil)`.
5. Embedding promotes methods; embed for behavior reuse, never to fake inheritance. Embedding
   an interface in a struct makes unimplemented methods nil-panic at call time.
6. Zero values should be useful (`var mu sync.Mutex`, `var buf bytes.Buffer`); design new types
   so `T{}` is valid or unexported fields force use of a constructor.

| Need | Go shape |
|---|---|
| polymorphism over behavior | small interface |
| polymorphism over data shape (containers, algorithms) | generics |
| closed set of variants | interface with an unexported marker method + type switch |
| optional configuration | functional options `func WithTimeout(d time.Duration) Option` or a config struct |
| plugin-like extension | interface + registry map populated at init by the main package |

## 4. Errors

```go
var ErrNotFound = errors.New("user not found")             // sentinel: compare with errors.Is

type ValidationError struct{ Field, Reason string }        // typed: extract with errors.As / AsType
func (e *ValidationError) Error() string { return e.Field + ": " + e.Reason }

func (s *Store) Get(ctx context.Context, id int64) (*User, error) {
    u, err := s.q.GetUser(ctx, id)
    if errors.Is(err, sql.ErrNoRows) {
        return nil, fmt.Errorf("get user %d: %w", id, ErrNotFound)
    }
    if err != nil {
        return nil, fmt.Errorf("get user %d: %w", id, err)
    }
    return u, nil
}

// caller
if ve, ok := errors.AsType[*ValidationError](err); ok { ... }   // Go 1.26; older: var ve *ValidationError; errors.As(err, &ve)
```

Rules:
- Wrap with `%w` and context that the caller does not already have (operation + key IDs).
  Not "failed to ...": the chain reads `get user 42: query: connection refused`.
- Use `%v` instead of `%w` when you deliberately hide the underlying error from your API
  (wrapping makes the wrapped error part of your contract).
- Handle **or** return, never both: logging and returning duplicates every log line up the stack.
- `errors.Join(errs...)` and multiple `%w` for aggregate errors; `errors.Is` walks all branches.
- Panics are for programmer errors and impossible states. Recover only at goroutine and request
  boundaries (net/http already recovers per handler; your own goroutines do not).
- Return `error`, never a concrete error pointer type (see nil-interface pitfall, section 10).

## 5. Generics and iterators

Use generics for: containers, algorithms over slices/maps/channels, type-safe wrappers (pools,
caches, result types). Do not use them where an interface method set expresses the behavior.

```go
func Map[S ~[]E, E, R any](s S, f func(E) R) []R {
    out := make([]R, 0, len(s))
    for _, v := range s { out = append(out, f(v)) }
    return out
}

type Set[T comparable] struct{ m map[T]struct{} }
func (s *Set[T]) All() iter.Seq[T] {                      // range-over-func (1.23)
    return func(yield func(T) bool) {
        for v := range s.m {
            if !yield(v) { return }                       // must stop when yield returns false
        }
    }
}
// for v := range set.All() { ... }; slices.Sorted(maps.Keys(m)); slices.Collect(seq)
```

- Prefer the standard `slices`, `maps`, `cmp`, `iter` packages before writing helpers.
- Constraints: `comparable`, `cmp.Ordered`, `~int | ~int64` unions; `any` when nothing else is needed.
- Before 1.27 (or with go.mod `go` < 1.27) methods cannot declare type parameters: write a function.
  Interface methods never can, and a generic method never implements an interface method.
- An iterator that ignores `yield`'s `false` panics at runtime when the loop body breaks.

## 6. Concurrency rules (summary; patterns in [concurrency-patterns](references/concurrency-patterns.md))

1. Every goroutine has an owner who knows how it ends. Before writing `go`, write down what
   makes it exit (context cancellation, channel close, input exhausted).
2. `context.Context` is the first parameter of anything that blocks or does I/O; never stored in
   structs; always `defer cancel()` after `WithTimeout`/`WithCancel` (vet `lostcancel`).
3. Fan-out with `errgroup.WithContext` and `g.SetLimit(n)`; first error cancels the rest.
4. The sender closes a channel, never the receiver; close only once; a nil channel blocks
   forever (use it to disable a `select` case).
5. Mutex for state, channels for ownership transfer and signaling. A mutex-protected map is
   simpler and faster than a goroutine-owned map in most services.
6. Unbuffered channel send in a goroutine whose receiver may return early is a leak; use a
   buffer of 1 for single-result goroutines or `select` on `ctx.Done()`.
7. `sync.WaitGroup.Go(f)` (1.25) replaces `Add(1)` + `go` + `defer Done()`.
8. Test concurrency with `-race`, and time-dependent code with `testing/synctest` (1.25):
   time is virtual inside the bubble and `synctest.Wait()` blocks until all goroutines idle
   (1.27: `synctest.Sleep(d)` sleeps then waits).

## 7. Testing

```go
func TestParseDuration(t *testing.T) {
    tests := []struct {
        name    string
        in      string
        want    time.Duration
        wantErr error
    }{
        {"seconds", "5s", 5 * time.Second, nil},
        {"empty", "", 0, ErrEmpty},
        {"negative", "-1s", 0, ErrNegative},
    }
    for _, tc := range tests {
        t.Run(tc.name, func(t *testing.T) {
            t.Parallel()
            got, err := ParseDuration(tc.in)
            if !errors.Is(err, tc.wantErr) {
                t.Fatalf("ParseDuration(%q) err = %v, want %v", tc.in, err, tc.wantErr)
            }
            if got != tc.want {
                t.Errorf("ParseDuration(%q) = %v, want %v", tc.in, got, tc.want)
            }
        })
    }
}
```

- Failure messages: `Func(input) = got, want want`. Use `github.com/google/go-cmp/cmp.Diff`
  for structs (`if diff := cmp.Diff(want, got); diff != "" { t.Errorf("mismatch (-want +got):\n%s", diff) }`).
- Helpers call `t.Helper()`; cleanup with `t.Cleanup`; temp dirs `t.TempDir()`; context
  `t.Context()` (1.24, cancelled when the test ends); `t.Setenv` cannot be combined with `t.Parallel`.
- Golden files under `testdata/`, regenerated with a `-update` flag defined in the test package.
- HTTP: `httptest.NewRecorder()` for handlers, `httptest.NewServer()` for clients;
  `httptest.NewTestServer()` (1.27) uses an in-memory network that works inside synctest.
- Integration tests behind a build tag (`//go:build integration`) or `testing.Short()`.

Fuzzing:

```go
func FuzzRoundTrip(f *testing.F) {
    f.Add([]byte(`{"a":1}`))                               // seed corpus
    f.Fuzz(func(t *testing.T, data []byte) {
        v, err := Decode(data)
        if err != nil { return }                           // invalid input is fine; panics are not
        out, err := Encode(v)
        if err != nil { t.Fatalf("encode after decode: %v", err) }
        if _, err := Decode(out); err != nil { t.Fatalf("round trip: %v", err) }
    })
}
```

`go test -run=^$ -fuzz=FuzzRoundTrip -fuzztime=5m ./codec` (one package per invocation). Crashers
are written to `testdata/fuzz/FuzzRoundTrip/` and replay as regular tests: commit them.

Benchmarks:

```go
func BenchmarkEncode(b *testing.B) {
    v := sampleValue()
    b.ReportAllocs()
    for b.Loop() {                                         // 1.24+: setup excluded, no dead-code elimination
        if _, err := Encode(v); err != nil { b.Fatal(err) }
    }
}
```

```bash
go test -run=^$ -bench=Encode -benchmem -count=10 ./codec > old.txt   # on base commit
go test -run=^$ -bench=Encode -benchmem -count=10 ./codec > new.txt   # on change
benchstat old.txt new.txt                                              # golang.org/x/perf/cmd/benchstat
```

Only report a change benchstat marks significant (p < 0.05 with the shown delta).

## 8. Performance procedure (details in [profiling-tooling](references/profiling-tooling.md))

1. Benchmark or load test reproduces the problem; capture a CPU profile and a heap profile.
2. `go tool pprof -top -cum cpu.out | head -30`, then `go tool pprof -list 'pkg.Func' cpu.out` for
   line detail (the `-http=:0` web UI blocks and needs a browser: humans only); for
   allocation pressure use `-sample_index=alloc_space` on the heap profile.
3. Fix the top item; compare with `benchstat` and `go tool pprof -top -diff_base=old.out new.out | head -30`.

| Profile symptom | Fix |
|---|---|
| `runtime.mallocgc` high, GC CPU > 10% | preallocate (`make([]T, 0, n)`), reuse buffers (`sync.Pool` for short-lived large buffers), avoid `[]byte`↔`string` conversions, pointer-free structs |
| `runtime.mapassign` / growth | size hint `make(map[K]V, n)` |
| escape to heap (`-gcflags=-m`) in hot path | return values not pointers, avoid interface boxing, avoid closures capturing locals |
| `fmt.Sprintf` hot | `strconv.AppendInt`, `strings.Builder` with `Grow` |
| `encoding/json` hot | code-generated or faster codecs; 1.27 backs `encoding/json` with the v2 implementation (opt out: GOEXPERIMENT=nojsonv2) and ships `encoding/json/v2`; on 1.25/1.26 v2 needs GOEXPERIMENT=jsonv2; test before switching |
| lock contention (mutex profile) | shard, `atomic` counters, RWMutex only if reads dominate and sections are long |
| syscalls / small writes | `bufio.Writer`, batch |
| CPU fine, latency poor | execution trace: scheduler delays, GC assists, blocking |

Profile-guided optimization: commit a representative production CPU profile as `default.pgo` in
the main package directory; `go build` uses it automatically (typically 2-14% CPU).

## 9. Modules and workspaces

| Task | Command |
|---|---|
| add/upgrade a dependency | `go get example.com/pkg@v1.4.2` then `go mod tidy` |
| upgrade all minor/patch (review the diff) | `go get -u ./... && go mod tidy` (or `-u=patch`) |
| why is a module present | `go mod why -m example.com/pkg`; `go mod graph | grep pkg` |
| develop two modules together | `go work init ./app ./lib` (do not commit `replace` for this) |
| pin a tool (1.24+) | `go get -tool golang.org/x/tools/cmd/stringer`, run `go tool stringer` |
| private modules | `GOPRIVATE=github.com/acme/*` (skips proxy and checksum DB) |
| major version 2+ | module path ends in `/v2`; import paths change |
| withdraw a bad release | `retract v1.3.0 // reason` in go.mod; tagging and pushing the new version is irreversible (the proxy caches it forever): return it as an Open doubt for the user |

The `go` directive is a minimum requirement (1.21+): raising it forces every consumer to that
toolchain. Libraries raise it only when they use the feature. Go 1.26's `go mod init` writes the
previous minor version by default for wider compatibility.

## 10. Pitfalls (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| `err != nil` is true but the error is "nil" | typed nil pointer stored in an `error` interface (`var e *MyErr; return e`) | return literal `nil`; never declare return type as concrete error pointer |
| all goroutines see the last loop value | pre-1.22 loop variable semantics (go.mod `go` < 1.22) | raise `go` directive or copy `v := v` |
| goroutine count grows forever | blocked send/receive with no reader, missing ctx cancel, goroutine looping on `ticker.C` with no ctx exit | owner + ctx; buffered result channel; `defer ticker.Stop()`; goleak in tests |
| `fatal error: concurrent map writes` | unsynchronized map | mutex, or ownership by one goroutine |
| slices share memory unexpectedly | `append` into a sub-slice with spare capacity | full slice expression `s[a:b:b]`, `slices.Clone` |
| `defer` in a loop exhausts file handles | defers run at function end | wrap the loop body in a function |
| HTTP client hangs forever | `http.DefaultClient` has no timeout | `&http.Client{Timeout: 10 * time.Second}` plus per-request ctx |
| connection leak | response body not closed/drained | `defer resp.Body.Close()`; drain `io.Copy(io.Discard, resp.Body)` before close for reuse |
| copied mutex | struct with `sync.Mutex` passed by value | pointer receivers; vet `copylocks` |
| JSON numbers become float64 | decoding into `any` | concrete types or `json.Decoder.UseNumber()` |
| `time.Time` equality fails | monotonic clock reading / location differ | `t.Equal(u)` |
| shadowed `err` | `:=` in inner scope | `shadow` analyzer (golangci-lint `govet` with `enable: [shadow]`) or careful naming |
| `select` loop burns CPU | `default:` case with no blocking | remove `default` or block on a timer |
| ctx cancelled work keeps running | function ignores `ctx.Done()` in loops | check `ctx.Err()` per iteration |
| integer overflow silently wraps | Go integers wrap | `math/bits`, explicit checks at boundaries |

## 11. Review checklist

- [ ] Every goroutine has an exit path tied to ctx or channel close; tests use goleak or synctest.
- [ ] Errors wrapped with context, checked with `errors.Is`/`As`; handled or returned, not both.
- [ ] No interface declared at the producer just for mocking; constructors return concrete types.
- [ ] `ctx` first param, propagated to every blocking call; timeouts on all network I/O.
- [ ] Shared state guarded; `go test -race` passes with tests that exercise concurrency.
- [ ] HTTP bodies closed; clients have timeouts; servers set `ReadHeaderTimeout`.
- [ ] Hot paths benchmarked with `-benchmem` and compared via benchstat.
- [ ] `go mod tidy -diff` clean; new dependencies justified; `govulncheck` clean.
- [ ] Exported identifiers documented; package names short, no `util`/`common` dumping grounds.

## 12. Worked example: fixing a leaking fan-out

Before: leaks a goroutine per URL whenever the caller returns early on the first error, and has
unbounded concurrency.

```go
func FetchAll(urls []string) ([][]byte, error) {
    ch := make(chan result)
    for _, u := range urls {
        go func() { b, err := fetch(u); ch <- result{b, err} }()   // blocks forever if nobody reads
    }
    var out [][]byte
    for range urls {
        r := <-ch
        if r.err != nil { return nil, r.err }                     // remaining senders leak
        out = append(out, r.body)
    }
    return out, nil
}
```

After: bounded, cancellable, ordered, no leaks.

```go
func FetchAll(ctx context.Context, c *http.Client, urls []string) ([][]byte, error) {
    out := make([][]byte, len(urls))
    g, ctx := errgroup.WithContext(ctx)
    g.SetLimit(8)
    for i, u := range urls {
        g.Go(func() error {                                       // i, u per-iteration (Go 1.22+)
            req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
            if err != nil { return fmt.Errorf("build request %s: %w", u, err) }
            resp, err := c.Do(req)
            if err != nil { return fmt.Errorf("get %s: %w", u, err) }
            defer resp.Body.Close()
            if resp.StatusCode != http.StatusOK { return fmt.Errorf("get %s: status %d", u, resp.StatusCode) }
            body, err := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
            if err != nil { return fmt.Errorf("read %s: %w", u, err) }
            out[i] = body                                         // distinct index per goroutine: no race
            return nil
        })
    }
    if err := g.Wait(); err != nil { return nil, err }
    return out, nil
}
```

The first error cancels `ctx`, in-flight requests abort, `Wait` returns after every goroutine
exits, and the response size is capped.

## Delegation hints

- pprof/trace analysis of a production incident: `debugger` with the profile paths.
- Systematic optimization against a latency or allocation budget: `code-optimizer`.
- Fuzz harness design and coverage gaps: `tester`.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `go-concurrency-context` | writing or debugging goroutines, channels, context cancellation or shared state |
| `go-error-handling` | designing error types, fixing lost context or duplicate logs, or reviewing Go error paths |
| `go-http-services` | building, hardening or debugging a Go HTTP or gRPC service |
| `go-interfaces-generics` | designing Go packages, adding generics or iterators, or reviewing the shape of a Go API |
| `go-modules-tooling` | managing Go dependencies, linters, builds or releases |
| `go-profiling-pprof` | a Go service is slow, allocation-heavy, leaking memory or showing latency spikes |
| `go-testing-fuzzing` | writing or fixing Go tests, adding fuzzing, or making tests deterministic |
