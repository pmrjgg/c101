---
name: go-testing-fuzzing
description: "Go testing toolkit. Covers table-driven subtests with t.Parallel, go-cmp diffs, golden files, httptest and bufconn, testing/synctest for time, native fuzzing, b.Loop benchmarks with benchstat, integration tests with build tags and testcontainers-go, coverage of integration binaries, rapid state-machine properties and goleak. Load when writing or fixing Go tests, adding fuzzing, or making tests deterministic."
when_to_use: "Editing *_test.go or testdata/, flaky or timing-dependent Go tests, 'race detected during execution of test', 'found unexpected goroutines' (goleak), 'testing: will not fuzz', adding FuzzXxx/BenchmarkXxx/ExampleXxx, Postgres or Redis integration tests, coverage gates for unit tests or built binaries."
---

# Go testing and fuzzing

Baseline: Go 1.26/1.27 (1.27.2 current in October 2026). Version-gated APIs below are marked; a
symbol newer than the module's `go` line is reported by the `stdversion` vet check, which `go test`
runs by default since 1.27, so raise the `go` line before using it (`go-modules-tooling`).

Deep material: [integration harnesses](references/integration-harnesses.md) (testcontainers, bufconn, fake APIs, CI) |
[fuzz and property cookbook](references/fuzz-property-cookbook.md) (properties, CI fuzz loop, rapid generators and flags).

## 1. Table-driven template

```go
func TestParseDuration(t *testing.T) {
    tests := []struct {
        name, in string
        want     time.Duration
        wantErr  error
    }{
        {"seconds", "5s", 5 * time.Second, nil},
        {"empty", "", 0, ErrEmpty},
        {"negative", "-1s", 0, ErrNegative},
    }
    for _, tc := range tests {                    // per-iteration tc since go 1.22 (no tc := tc)
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

- Message format `Func(input) = got, want want`: the reader must not need the source to know what failed.
- `t.Fatalf` when later checks are meaningless (error path), `t.Errorf` to report every mismatch.
- Structs, slices, maps: `github.com/google/go-cmp/cmp`, always `(-want +got)`:
  `if diff := cmp.Diff(want, got, opts...); diff != "" { t.Errorf("GetUser(%d) mismatch (-want +got):\n%s", id, diff) }`

| Need | Option |
|---|---|
| ignore volatile fields | `cmpopts.IgnoreFields(T{}, "ID", "CreatedAt")` |
| unexported fields (cmp panics otherwise) | `cmpopts.IgnoreUnexported(T{})` or `cmp.AllowUnexported(T{})` |
| order-insensitive slices / maps | `cmpopts.SortSlices(func(a, b string) bool { return a < b })`, `cmpopts.SortMaps(...)` |
| nil vs empty equal | `cmpopts.EquateEmpty()` |
| floats, times | `cmpopts.EquateApprox(0, 1e-9)`, `cmpopts.EquateApproxTime(time.Second)` |
| errors compared with `errors.Is` | `cmpopts.EquateErrors()` |
| protobuf messages | `protocmp.Transform()` (`google.golang.org/protobuf/testing/protocmp`) |

`cmp` uses a type's `Equal` method when present (so `time.Time` compares by instant). Use `==` and
`errors.Is` for scalars and errors; `reflect.DeepEqual` gives no diff and treats nil/empty as different.

## 2. Helpers and lifecycle

| API | Since | Rule |
|---|---|---|
| `t.Helper()` | 1.9 | first line of every helper; failures point at the caller |
| `t.Cleanup(f)` | 1.14 | LIFO, runs after subtests finish; helpers return values and register cleanup instead of returning `func()` |
| `t.TempDir()` | 1.15 | fresh directory per call, removed automatically |
| `t.Setenv(k, v)` | 1.17 | restored afterwards; panics in a test that called `t.Parallel` or has a parallel ancestor |
| `t.Context()` | 1.24 | cancelled just before Cleanup functions run; use it instead of `context.Background()` |
| `t.Chdir(dir)` | 1.24 | process-wide, same parallel restriction as `Setenv` |
| `t.Output()`, `t.Attr(k, v)` | 1.25 | `io.Writer` into the test log; key/value attributes visible in `go test -json` |
| `t.ArtifactDir()` | 1.26 | directory for test outputs; kept with `go test -artifacts -outputdir=DIR`, else deleted |
| `cryptotest.SetGlobalRandom` | 1.26 | `testing/cryptotest`: deterministic `crypto/rand` for the test |

Package-level setup with `TestMain`; defers do not run through `os.Exit`, so wrap:

```go
func TestMain(m *testing.M) { os.Exit(run(m)) }
func run(m *testing.M) int {
    stop, err := startSharedFixture()        // e.g. one Postgres container per package
    if err != nil { fmt.Fprintln(os.Stderr, err); return 1 }
    defer stop()
    return m.Run()
}
```

Never call `t.Fatal`/`FailNow` from a goroutine the test started (vet `testinggoroutine`): send the
error on a channel and fail on the test goroutine.

## 3. Golden files and fixtures

```go
var update = flag.Bool("update", false, "rewrite golden files in testdata/")

func TestRender(t *testing.T) {
    got := Render(loadFixture(t, "order.json"))
    golden := filepath.Join("testdata", strings.ReplaceAll(t.Name(), "/", "_")+".golden")
    if *update {
        if err := os.WriteFile(golden, got, 0o644); err != nil { t.Fatal(err) }
    }
    want, err := os.ReadFile(golden)
    if err != nil { t.Fatalf("read golden (run with -update to create): %v", err) }
    if diff := cmp.Diff(string(want), string(got)); diff != "" {
        t.Errorf("Render mismatch (-want +got):\n%s", diff)
    }
}
```

- Regenerate per package (`go test ./render -run TestRender -update`), review `git diff testdata/` like
  code; normalise timestamps, IDs, map order and absolute paths before comparing.
- `testdata/` is ignored by the go tool for package discovery and is the conventional fixture root;
  `//go:embed testdata/*.json` into an `embed.FS` works in `_test.go` files for read-only fixtures.

## 4. HTTP and gRPC test doubles

| Dependency | Double, in order of preference |
|---|---|
| your own narrow interface (Store, Clock, Mailer) | hand-written in-memory fake in `_test.go` or `internal/fake` |
| an `http.Handler` you own | `httptest.NewRecorder()` + `httptest.NewRequest(...)`; call `ServeHTTP`; read `rec.Result()` |
| an HTTP client against a remote API | `httptest.NewServer(handler)` that asserts the request and returns canned JSON; point the client at `srv.URL` |
| HTTP inside a `synctest` bubble | `httptest.NewTestServer(t, h)` (1.27): in-memory network, Cleanup registered, use `srv.Client()`, never `Start` |
| a gRPC service | real server on `bufconn` with a fake implementation (below) |
| SQL | real database in testcontainers (section 8); `sqlmock` only checks SQL strings |
| wide interface where call order/arguments are the behaviour | generated mocks: `go tool moq -out store_moq_test.go . Store` or `go.uber.org/mock/mockgen` (golang/mock is archived) |

gRPC: serve a real `grpc.Server` on `bufconn.Listen(1 << 20)` and dial `grpc.NewClient("passthrough:///bufnet",
grpc.WithContextDialer(...lis.DialContext...), grpc.WithTransportCredentials(insecure.NewCredentials()))`;
`NewClient` resolves with `dns` by default, so `passthrough:///` is required. Full code, a
request-asserting fake API and interceptor tests: [integration harnesses](references/integration-harnesses.md).

## 5. Time and concurrency: deterministic by construction

`testing/synctest` (GA in 1.25; 1.24 had `synctest.Run` behind `GOEXPERIMENT=synctest`):

| Fact | Consequence |
|---|---|
| `synctest.Test(t, func(t *testing.T){...})` runs f in a bubble with a fake clock starting at 2000-01-01 00:00 UTC | `time.Now`, `Sleep`, timers, tickers, `context.WithTimeout` are virtual and exact |
| time advances only when every bubble goroutine is durably blocked | a 10-minute backoff runs in microseconds |
| durably blocked = bubble channel ops, `select` on bubble channels, `sync.Cond.Wait`, `WaitGroup.Wait` (Add in bubble), `time.Sleep` | mutex waits, network I/O and syscalls are not: use `net.Pipe` or `NewTestServer`, never loopback |
| `synctest.Wait()` returns when all other bubble goroutines are durably blocked | assert intermediate state after `time.Sleep(d); synctest.Wait()` (1.27: `synctest.Sleep(d)`) |
| all blocked, no pending timer | `Test` panics with a deadlock: leaks become failures |
| inside the bubble | no `t.Run`, `t.Parallel`, `t.Deadline`; `t.Context()` and `t.Cleanup` are bubble-aware |
| bubbled channel/timer used from outside | panic |

Flake hunting, in this order:

```bash
go test -race -shuffle=on -count=1 ./...                      # gate; prints "-test.shuffle N" to replay with -shuffle=N
go test -run '^TestX$' -race -count=500 ./pkg                 # reproduce
go test -run '^TestX$' -count=200 -cpu=1,2,8 ./pkg            # vary GOMAXPROCS
go test -c -race -o .stack/out/pkg.test ./pkg && go run golang.org/x/tools/cmd/stress@latest -p 8 .stack/out/pkg.test -test.run '^TestX$'
```

`-race` costs 2-20x CPU and 5-10x memory and only sees executed interleavings; `-count=1` bypasses the
test cache. Goroutine leaks: `go.uber.org/goleak`:
`func TestMain(m *testing.M) { goleak.VerifyTestMain(m) }` package-wide (safe with `t.Parallel`);
`defer goleak.VerifyNone(t)` only in serial tests; allow known pollers with
`goleak.IgnoreTopFunction("pkg.(*T).loop")` or `goleak.IgnoreCurrent()`.

## 6. Native fuzzing

```go
func FuzzRoundTrip(f *testing.F) {
    for _, seed := range []string{`{"a":1}`, `[]`, `{"a":[1,2,{"b":null}]}`} {
        f.Add([]byte(seed))                                  // seed corpus: types must match f.Fuzz args
    }
    f.Fuzz(func(t *testing.T, data []byte) {
        v, err := Decode(data)
        if err != nil { return }                             // invalid input is fine; panics are not
        out, err := Encode(v)
        if err != nil { t.Fatalf("Encode(Decode(%q)): %v", data, err) }
        v2, err := Decode(out)
        if err != nil { t.Fatalf("Decode(Encode(v)) = %v", err) }
        if diff := cmp.Diff(v, v2); diff != "" { t.Fatalf("round trip (-first +second):\n%s", diff) }
    })
}
```

Properties to assert: no panic or hang (bound work: `if len(data) > 1<<16 { t.Skip() }`); round trip
(`Decode(Encode(x)) == x`); differential against a reference (stdlib `strconv`/`net/url`, the previous
release, a slow obvious implementation); invariants (sorted output, length bounds, `f(f(x)) == f(x)`).

Arguments: `[]byte`, `string`, `bool`, `byte`, `rune`, `float32/64`, signed and unsigned ints. One
`f.Fuzz` per `FuzzXxx`; targets must be fast, deterministic and free of global state.

```bash
go test ./codec                                                 # seeds + committed crashers run as plain tests
go test -run='^$' -fuzz='^FuzzRoundTrip$' -fuzztime=60s ./codec # one target, one package per run
go test -run='^$' -fuzz='^FuzzRoundTrip$' -fuzztime=200000x ./codec  # iteration budget instead of time
go test -run='FuzzRoundTrip/8a1f0c2d9e' ./codec                 # replay one crasher
```

- `-fuzz` must match exactly one fuzz test in one package ("testing: will not fuzz, -fuzz matches more
  than one fuzz test"); workers default to `$GOMAXPROCS` (`-parallel`); `-fuzzminimizetime` is 60s.
- A failure writes `testdata/fuzz/FuzzRoundTrip/<hash>` (`go test fuzz v1` format): fix the bug, keep
  the file, commit it; it now runs in every plain `go test`.
- The generated corpus lives in `$GOCACHE/fuzz` (not committed; `go clean -fuzzcache` wipes it);
  cache it in CI so nightly runs resume.
- CI: PRs run seeds only; nightly loops every target for 5-10 minutes
  ([CI fuzz loop](references/fuzz-property-cookbook.md)).

## 7. Benchmarks

```go
func BenchmarkEncode(b *testing.B) {
    for _, n := range []int{10, 1_000, 100_000} {
        b.Run(fmt.Sprintf("items=%d", n), func(b *testing.B) {
            v := sample(n)                                   // setup outside the loop: not timed
            b.ReportAllocs()
            for b.Loop() {                                   // 1.24+; 1.26+ no longer blocks inlining
                if _, err := Encode(v); err != nil { b.Fatal(err) }
            }
        })
    }
}
```

`b.Loop` excludes setup, keeps results alive (no sink, no `b.ResetTimer`) and runs the function once per
`-count`; never mix it with `b.N`. `b.SetBytes(int64(size))` adds MB/s.

```bash
go test -run='^$' -bench='^BenchmarkEncode$' -benchmem -count=10 ./codec | tee .stack/out/bench-old.txt  # base commit
go test -run='^$' -bench='^BenchmarkEncode$' -benchmem -count=10 ./codec | tee .stack/out/bench-new.txt  # change
go tool benchstat .stack/out/bench-old.txt .stack/out/bench-new.txt   # after go get -tool golang.org/x/perf/cmd/benchstat
```

Report only deltas benchstat marks significant (p < 0.05; `~` means no difference) with n >= 10
per side. If the `±` spread exceeds about 5%, quiet the machine before concluding. Profiling
the hot path is `go-profiling-pprof`.

## 8. Integration tests

- Gate with a build tag on line 1 of the file: `//go:build integration`; run `go test -tags=integration ./...`;
  configure gopls `buildFlags: ["-tags=integration"]` or the file is not analysed.
- Or skip at runtime: `if testing.Short() { t.Skip("integration: needs Docker") }` and run unit CI with `-short`.
- testcontainers-go modules (`Run` API since v0.32):

```go
ctr, err := postgres.Run(t.Context(), "postgres:17-alpine",
    postgres.WithDatabase("app"), postgres.WithUsername("app"), postgres.WithPassword("app"),
    postgres.WithInitScripts(filepath.Join("testdata", "schema.sql")),
    postgres.BasicWaitStrategies())                          // no default wait strategy: set one
testcontainers.CleanupContainer(t, ctr)                       // before the error check; nil-safe
if err != nil { t.Fatalf("start postgres: %v", err) }
dsn, err := ctr.ConnectionString(t.Context(), "sslmode=disable")
```

  Redis: `redis.Run(ctx, "redis:7-alpine")` then `ctr.ConnectionString(ctx)`. One container per package
  (TestMain) plus per-test isolation (transaction rollback, schema per test, or `ctr.Snapshot`/`Restore`
  with a database not named `postgres`) keeps suites fast; `testcontainers.SkipIfProviderIsNotHealthy(t)`
  skips cleanly without Docker.
- Example functions are executable docs: `func ExampleParseDuration()` printing with `fmt.Println`
  and ending in a `// Output: 1m30s` comment runs as a test and renders on pkg.go.dev. Use
  `// Unordered output:` for map order; without an output comment it compiles but does not run.
  Names: `ExampleF`, `ExampleT`, `ExampleT_Method`, `ExampleF_suffix`; `go doc -ex` lists them (1.27).

## 9. Coverage

```bash
go test -coverprofile=.stack/out/cover.out -coverpkg=./... ./...      # mode "set"; "atomic" when -race
go tool cover -func=.stack/out/cover.out | tail -1                     # total; -html=... -o file.html for a report
# integration coverage of a real binary (1.20+), merged with unit-test coverage
go build -cover -coverpkg=./... -o .stack/out/app.cover ./cmd/app
mkdir -p .stack/out/covint && GOCOVERDIR=.stack/out/covint .stack/out/app.cover --config testdata/e2e.yaml
go tool covdata percent -i=.stack/out/covint
go test -cover -coverpkg=./... ./... -args -test.gocoverdir="$PWD/.stack/out/covunit"
go tool covdata merge -i=.stack/out/covunit,.stack/out/covint -o .stack/out/covall
go tool covdata textfmt -i=.stack/out/covall -o .stack/out/cover-all.out && go tool cover -func=.stack/out/cover-all.out | tail -1
```

Counters are written only when `main` returns or calls `os.Exit` (a crash loses the run), so servers
under test must handle SIGTERM and return; without `GOCOVERDIR` the binary only warns. Gate on deltas
(for example, fail if the total drops more than 1 point against main), not a vanity absolute number.

## 10. Stateful property testing with rapid

`pgregory.net/rapid` generates and shrinks operation sequences against a model:

```go
type queueMachine struct {
    q     *Queue // system under test
    model []int  // obviously-correct model
}
func (m *queueMachine) Push(t *rapid.T) {
    if m.q.Len() == m.q.Cap() { t.Skip("full") }   // skip before drawing: rapid picks another action
    v := rapid.IntRange(-100, 100).Draw(t, "v")
    m.q.Push(v)
    m.model = append(m.model, v)
}
func (m *queueMachine) Pop(t *rapid.T) {
    if len(m.model) == 0 { t.Skip("empty") }
    if got, want := m.q.Pop(), m.model[0]; got != want { t.Fatalf("Pop() = %d, want %d", got, want) }
    m.model = m.model[1:]
}
func (m *queueMachine) Check(t *rapid.T) {        // invariant: before the first and after every action
    if m.q.Len() != len(m.model) { t.Fatalf("Len() = %d, want %d", m.q.Len(), len(m.model)) }
}
func TestQueueModel(t *testing.T) {
    rapid.Check(t, func(t *rapid.T) {
        m := &queueMachine{q: NewQueue(rapid.IntRange(1, 8).Draw(t, "cap"))}
        t.Repeat(rapid.StateMachineActions(m))
    })
}
```

Defaults: 100 checks (`-rapid.checks=10000` for a deep run), about 30 actions per sequence
(`-rapid.steps`), 30s shrink budget. Minimized failures persist to `testdata/rapid/<Test>/*.fail`
and are replayed automatically; commit them like fuzz crashers. `f.Fuzz(rapid.MakeFuzz(prop))` drives
the same property from the native fuzzer. Generators and flags: [cookbook](references/fuzz-property-cookbook.md).

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| table test passes but only the last case ran | pre-1.22 loop variable with `t.Parallel` | `go` line >= 1.22, or `tc := tc` |
| `panic: testing: t.Setenv called after t.Parallel` | Setenv/Chdir in a parallel test | make that test serial; pass config explicitly |
| timing assertion fails on CI only | wall-clock sleeps and bounds | `synctest` (section 12) |
| synctest test hangs until `-timeout` | bubble goroutine waits on a mutex, real network I/O or a channel made outside the bubble (not durable, clock never advances) | `net.Pipe`/`NewTestServer`; create channels inside the bubble |
| synctest panics: deadlock | a bubble goroutine waits forever on a bubble channel (a leak) | close or cancel it; tie it to `t.Context()` |
| goleak reports goroutines from another test | `VerifyNone` with `t.Parallel` | `VerifyTestMain` |
| fuzzing finds nothing | target returns early on most inputs, or no seeds | add seeds from table tests; fuzz the decoder, not the validator |
| benchmark reports near-0 ns/op | result unused, compiler removed the work in a `b.N` loop | `b.Loop()` |
| `flag provided but not defined: -update` | ran `./...` with a package-local flag | target the package |
| integration tests never ran, CI green | no `-tags=integration`: files excluded, no skip reported | dedicated CI job with the tag; assert expected test names in `go test -json` |
| coverage of the binary is empty | killed by SIGKILL or no `GOCOVERDIR` | graceful SIGTERM, set `GOCOVERDIR` |
| 1.27 vet error `stdversion` | API newer than the `go` line | raise the `go` line or avoid the symbol |

## 12. Worked example: flaky retry-with-backoff made deterministic

Code under test (production uses `Jitter: FullJitter`):

```go
type Policy struct {
    Attempts  int                                   // total tries, >= 1
    Base, Max time.Duration                         // first backoff, cap per sleep
    Jitter    func(time.Duration) time.Duration     // nil = none
}
func FullJitter(d time.Duration) time.Duration { return rand.N(d + 1) } // math/rand/v2, [0, d]
func Do(ctx context.Context, p Policy, op func(context.Context) error) error {
    backoff := p.Base
    for attempt := 1; ; attempt++ {
        err := op(ctx)
        if err == nil { return nil }
        if attempt == p.Attempts { return fmt.Errorf("retry: %d attempts: %w", attempt, err) }
        d := backoff
        if p.Jitter != nil { d = p.Jitter(d) }
        backoff = min(p.Max, 2*backoff)
        timer := time.NewTimer(d)
        select {
        case <-ctx.Done():
            timer.Stop()
            return fmt.Errorf("retry: attempt %d: %w (last error: %v)", attempt, ctx.Err(), err)
        case <-timer.C:
        }
    }
}
```

Before: 700 ms of real sleeping per run and a wall-clock window that a loaded CI runner misses
(typical failure `elapsed = 763ms, want ~700ms`):

```go
start := time.Now()
_ = Do(context.Background(), Policy{Attempts: 4, Base: 100 * time.Millisecond, Max: time.Second},
    func(context.Context) error { return errBoom })
if el := time.Since(start); el < 700*time.Millisecond || el > 750*time.Millisecond {
    t.Fatalf("elapsed = %v, want ~700ms", el)
}
```

Reproduce: `go test -run '^TestDoBackoff$' -race -count=100 -cpu=1 ./retry`. After: exact virtual
time, 100 + 200 + 400 = 700 ms, and cancellation checked mid-backoff:

```go
var errBoom = errors.New("boom")
func TestDoBackoff(t *testing.T) {
    synctest.Test(t, func(t *testing.T) {
        calls := 0
        start := time.Now()
        err := Do(t.Context(), Policy{Attempts: 4, Base: 100 * time.Millisecond, Max: time.Second},
            func(context.Context) error { calls++; return errBoom })
        if !errors.Is(err, errBoom) { t.Fatalf("Do() err = %v, want %v", err, errBoom) }
        if calls != 4 { t.Errorf("calls = %d, want 4", calls) }
        if got, want := time.Since(start), 700*time.Millisecond; got != want {
            t.Errorf("elapsed = %v, want %v", got, want)
        }
    })
}

func TestDoCancelDuringBackoff(t *testing.T) {
    synctest.Test(t, func(t *testing.T) {
        ctx, cancel := context.WithCancel(t.Context())
        var calls atomic.Int32
        done := make(chan error, 1)
        go func() {
            done <- Do(ctx, Policy{Attempts: 4, Base: 100 * time.Millisecond, Max: time.Second},
                func(context.Context) error { calls.Add(1); return errBoom })
        }()
        time.Sleep(250 * time.Millisecond)              // attempts ran at t=0 and t=100ms; next due t=300ms
        synctest.Wait()                                 // 1.27+: synctest.Sleep(250 * time.Millisecond)
        if got := calls.Load(); got != 2 { t.Fatalf("calls before cancel = %d, want 2", got) }
        cancel()
        if err := <-done; !errors.Is(err, context.Canceled) {
            t.Fatalf("Do() err = %v, want context.Canceled", err)
        }
    })
}
```

Why it works: `t.Context()` (and contexts derived in the bubble) and `time.NewTimer` give bubble
channels, so the `select` is durably blocked and the clock jumps to the next timer. `Jitter: nil` keeps
randomness out of the assertion (test `FullJitter` separately for `[0, d]`). Needs `go 1.25`+ in go.mod
(1.27 for `synctest.Sleep`); a goroutine left blocked at the end fails as a deadlock, so leaks are caught too.

```bash
go test -run '^TestDo' -race -count=1000 ./retry    # no real time passes: 2000 runs finish quickly
go test -race -shuffle=on -count=1 ./...            # full gate
```

Related: `go-concurrency-context` (leak-free patterns these tests verify), `go-http-services`
(handler and service tests), `go-modules-tooling` (tool directives, CI gates), `go-profiling-pprof`
(benchmark-driven optimization), `go-error-handling`, `testing-strategy`; hub `go-craft`.
