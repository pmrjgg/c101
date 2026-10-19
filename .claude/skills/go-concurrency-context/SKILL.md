---
name: go-concurrency-context
description: "Go concurrency playbook: choosing a sync primitive, context rules, errgroup fan-out with limits, worker pools and pipelines, single-result goroutines, graceful shutdown, mutex and atomic hygiene, and finding leaks and races with -race, goleak, testing/synctest and the goroutineleak profile. Load when writing or debugging goroutines, channels, context cancellation or shared state."
when_to_use: "Code with go statements, channels, select, sync.Mutex/WaitGroup/Once, sync/atomic, errgroup or context.Context; errors like 'all goroutines are asleep - deadlock!', 'concurrent map writes', 'WARNING: DATA RACE', 'send on closed channel', goleak 'found unexpected goroutines'; goroutine counts that keep growing; cancellation that does not propagate; graceful shutdown of servers and workers."
---

# Go concurrency and context

Baseline Go 1.26/1.27; language semantics follow the `go` line in go.mod (per-iteration loop
variables need `go 1.22`+). Version map: `WithCancelCause` 1.20; `WithoutCancel`, `AfterFunc`,
`WithTimeoutCause`, `sync.OnceValue(s)` 1.21; `for range n` 1.22; unreferenced timers collectable
1.23; `sync.WaitGroup.Go`, `testing/synctest`, vet `waitgroup` 1.25; `signal.NotifyContext` cause
names the signal and goroutine-leak profile as experiment 1.26; `synctest.Sleep` and the
`goroutineleak` profile GA 1.27.

Deep material: [extended patterns](references/patterns-extended.md) (semaphore, singleflight,
rate limit, pub/sub, batching) | [detection playbook](references/detection-playbook.md) (race
reports, goroutine dumps, synctest rules, goleak options)

## 1. Choose the primitive

| Need | Use | Watch out |
|---|---|---|
| guard shared fields | `sync.Mutex` declared next to the fields | `RWMutex` only if reads dominate and sections are long; benchmark first |
| N tasks, wait, first error cancels the rest | `errgroup.WithContext` + `g.SetLimit(n)` (golang.org/x/sync) | `SetLimit` panics while goroutines are active: set it before the first `Go` |
| N tasks, wait, no error | `wg.Go(f)` (1.25) | `wg.Add(1)` inside the goroutine races with `Wait` (vet `waitgroup`) |
| lazy one-time init | `sync.OnceValue(func() T)`, `OnceValues`, `OnceFunc` | `Once.Do` treats a panicking f as done; `OnceValue(s)` re-panic on every call |
| counters, flags, pointer swaps | `atomic.Int64`, `atomic.Bool`, `atomic.Pointer[T]` | mixing atomic and plain access to the same variable |
| hand work to a fixed set of workers | buffered `chan Job` + workers | `for _, x := range input { go handle(x) }` on external input |
| cap concurrency without workers | `make(chan struct{}, n)` or `semaphore.NewWeighted(n)` (x/sync) | forgetting the release on error paths: `defer` it |
| broadcast "stop" | cancel a `context` (or `close(done)`) | sending one value per listener |
| collapse identical concurrent calls | `singleflight.Group` (x/sync) | one caller's ctx cancels everyone's shared call |
| reuse short-lived buffers | `sync.Pool` of pointers | pooled values allocate on `Put` (staticcheck SA6002); items vanish at any GC |
| concurrent map with disjoint or append-mostly keys | `sync.Map` (hash-trie since 1.24) | general maps: mutex + typed map is simpler |
| throttle calls | `rate.NewLimiter(r, burst)` + `lim.Wait(ctx)` (golang.org/x/time/rate) | `time.Sleep` loops that ignore ctx |

Default split: mutex for state, channels for ownership transfer and signalling, context for
cancellation and deadlines. A mutex-guarded map beats a goroutine-owned map in most services.

## 2. Ownership: write the exit before the `go`

Every goroutine has an owner who knows what ends it. Write it down first:

```go
// owner: Server.Run; exits when ctx is cancelled (Shutdown) or jobs is closed (Close).
s.wg.Go(func() { s.worker(ctx, jobs) })
```

| Exit trigger | Mechanism | The owner must also |
|---|---|---|
| caller gave up | every blocking op selects on `<-ctx.Done()` | `defer cancel()` where the ctx was derived |
| input exhausted | `for v := range in` ends when the producer closes `in` | guarantee exactly one closer |
| single result delivered | send into `make(chan T, 1)` | nothing: the send cannot block |
| process shutdown | root ctx from `signal.NotifyContext`, then `wg.Wait()` | bound the wait with a timeout |

A `go` statement that maps to no row is a leak. Review rule: point at the line that ends it.

## 3. Context rules

| Rule | Reason |
|---|---|
| `ctx context.Context` is the first parameter of anything that blocks or does I/O | cancellation and deadlines reach every leaf; `context.TODO()` while refactoring, never `nil` |
| never store a ctx in a struct (golangci-lint `containedctx`) | a stored ctx outlives its request; pass it per call |
| `ctx, cancel := context.WithTimeout(parent, d)` then `defer cancel()` | a missing cancel keeps the timer and child alive until the parent ends (vet `lostcancel`) |
| derive, never replace: no `context.Background()` in request paths (`contextcheck`) | it cuts cancellation and trace propagation |
| children only shorten deadlines | `WithTimeout(parent, 10*time.Second)` under a 2 s parent still ends at 2 s |
| record why: `WithCancelCause`, `WithTimeoutCause`, `context.Cause(ctx)` | `ctx.Err()` only says `Canceled` or `DeadlineExceeded` |
| work that must outlive the request: `context.WithoutCancel(ctx)` plus its own timeout | keeps values (trace IDs), drops cancel and deadline |
| run cleanup on cancel with `context.AfterFunc(ctx, f)` | no goroutine parked on `<-ctx.Done()`; returns `stop func() bool` |
| values: request-scoped data only, unexported key type | never optional parameters, loggers or DB handles |
| CPU loops check `ctx.Err()` every iteration (or every N) | cancellation is cooperative |
| never `ctx = context.WithValue(ctx, ...)` on a loop-carried ctx (`fatcontext`) | every iteration nests a layer; lookups and memory grow |

```go
ctx, cancel := context.WithCancelCause(parent)
defer cancel(nil)
if over { cancel(fmt.Errorf("tenant %s: %w", id, ErrQuota)) }
if ctx.Err() != nil { return context.Cause(ctx) }        // ErrQuota chain, not "context canceled"

stop := context.AfterFunc(ctx, func() { conn.SetReadDeadline(time.Now()) }) // unblock a ctx-less read
defer stop()

if dl, ok := ctx.Deadline(); ok {                        // propagate a budget to a timeout-only API
    req.TimeoutMs = time.Until(dl).Milliseconds() - 50   // keep a margin for the response path
}

bg := context.WithoutCancel(ctx)                          // audit write after the response is sent
bg, cancelBG := context.WithTimeout(bg, 5*time.Second)
s.bg.Go(func() { defer cancelBG(); s.audit.Write(bg, ev) }) // owned by s.bg, drained at shutdown

type principalKey struct{}
func WithPrincipal(ctx context.Context, p Principal) context.Context { return context.WithValue(ctx, principalKey{}, p) }
func PrincipalFrom(ctx context.Context) (Principal, bool) { p, ok := ctx.Value(principalKey{}).(Principal); return p, ok }
```

## 4. Patterns with code

**Bounded worker pool with shutdown.** Submit applies backpressure; only the owner calls `Close`,
after every `Submit` caller is done (a send on a closed channel panics). With independent
producers, signal shutdown through a separate `done` channel closed once via `sync.Once`.

```go
type Pool struct { jobs chan Job; wg sync.WaitGroup }

func NewPool(ctx context.Context, workers, queue int, handle func(context.Context, Job)) *Pool {
    p := &Pool{jobs: make(chan Job, queue)}
    for range workers {
        p.wg.Go(func() {
            for {
                select {
                case <-ctx.Done():
                    return
                case j, ok := <-p.jobs:
                    if !ok { return }
                    handle(ctx, j)
                }
            }
        })
    }
    return p
}
func (p *Pool) Submit(ctx context.Context, j Job) error {
    select { case p.jobs <- j: return nil; case <-ctx.Done(): return ctx.Err() }
}
func (p *Pool) Close() { close(p.jobs); p.wg.Wait() } // drains the queue (unless ctx ended), then returns
```

**Pipeline stage.** Every send selects on `ctx.Done()`; every stage closes its output; an error
channel with buffer 1 never blocks the stage.

```go
func stage[In, Out any](ctx context.Context, in <-chan In, f func(In) (Out, error)) (<-chan Out, <-chan error) {
    out, errc := make(chan Out), make(chan error, 1)
    go func() {
        defer close(out)
        defer close(errc)
        for v := range in {
            r, err := f(v)
            if err != nil { errc <- err; return }
            select { case out <- r: case <-ctx.Done(): errc <- ctx.Err(); return }
        }
    }()
    return out, errc
}
```

**Fan-in.** One goroutine per input; the single closer waits for all senders.

```go
func merge[T any](ctx context.Context, ins ...<-chan T) <-chan T {
    out := make(chan T)
    var wg sync.WaitGroup
    for _, in := range ins {
        wg.Go(func() {
            for v := range in {
                select { case out <- v: case <-ctx.Done(): return }
            }
        })
    }
    go func() { wg.Wait(); close(out) }()
    return out
}
```

**Single-result goroutine.** The buffer of 1 lets the goroutine finish even when nobody reads; it
does not stop `f`, so pass ctx into `f` whenever possible.

```go
func withTimeout(ctx context.Context, f func(context.Context) (int, error)) (int, error) {
    type res struct { v int; err error }
    ch := make(chan res, 1)
    go func() { v, err := f(ctx); ch <- res{v, err} }()
    select { case r := <-ch: return r.v, r.err; case <-ctx.Done(): return 0, context.Cause(ctx) }
}
```

**Tee / broadcast.** Lock-step copy to n consumers; the slowest consumer sets the pace. For
independent subscribers with drop policies use the pub/sub in the extended patterns reference.

```go
func tee[T any](ctx context.Context, in <-chan T, n int) []<-chan T {
    outs, ro := make([]chan T, n), make([]<-chan T, n)
    for i := range outs { outs[i] = make(chan T); ro[i] = outs[i] }
    go func() {
        defer func() { for _, o := range outs { close(o) } }()
        for v := range in {
            for _, o := range outs {
                select { case o <- v: case <-ctx.Done(): return }
            }
        }
    }()
    return ro
}
```

## 5. Channel axioms

| Axiom | Consequence |
|---|---|
| send or receive on a nil channel blocks forever | set a case's channel to `nil` to disable it in a `select` (merge example in the extended patterns) |
| close of nil or closed channel panics; send on closed panics | the single sender closes, exactly once; never the receiver |
| receive from a closed channel returns the zero value, `ok == false` | use `v, ok := <-ch` or `for range ch` |
| every blocking send or receive in a goroutine selects on `ctx.Done()` | otherwise a departed consumer strands the producer |
| `select` picks uniformly among ready cases | `ctx.Done()` can lose to a busy channel: check `ctx.Err()` at loop top |
| `select` with `default` never blocks | in a loop it is a busy spin: block on a channel or timer instead |
| `t := time.NewTicker(d); defer t.Stop()` | stop is explicit; the goroutine ranging over `t.C` still needs a ctx exit |
| reuse one `time.Timer` in hot loops rather than `time.After` | unreferenced timers are collectable since 1.23, but each `time.After` allocates |
| unbuffered = synchronisation; buffered = bounded decoupling | size buffers from a measured burst, never "until the deadlock goes away" |

## 6. Mutex and atomic hygiene

- Never copy a struct that contains a lock: pointer receivers, no by-value passing (vet `copylocks`).
- `mu.Lock(); defer mu.Unlock()` by default; keep sections to memory operations.
- No I/O, callbacks or channel sends while holding a lock: copy state out, unlock, then act.
- One documented lock order (`// lock order: Registry.mu before shard.mu`); never acquire in reverse.
- Locks are not reentrant; a recursive `RLock` deadlocks as soon as a writer queues between them.
- Comment what a lock guards: `mu sync.Mutex // guards pending, closed`.
- Atomics for counters, flags and pointer swaps only; Go atomics are sequentially consistent.
  Two related fields that must change together need a mutex, not two atomics.

```go
func (s *Sink) Flush(ctx context.Context) error {
    s.mu.Lock()
    batch := s.pending
    s.pending = nil
    s.mu.Unlock()
    return s.out.Write(ctx, batch)              // network I/O outside the lock
}

type Server struct { cfg atomic.Pointer[Config]; hits atomic.Int64 }
func (s *Server) Reload(c *Config) { s.cfg.Store(c) }   // copy-on-write: build a new *Config, never mutate
func (s *Server) handle() { cfg := s.cfg.Load(); s.hits.Add(1); _ = cfg.Limit }
```

## 7. Graceful shutdown

Order: fail readiness, stop accepting and drain HTTP, cancel background work, wait for workers with
a bound, flush telemetry, exit; total under Kubernetes `terminationGracePeriodSeconds` (default 30 s).

```go
func run() error {
    ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
    defer stop()
    bgCtx, bgCancel := context.WithCancel(context.Background())
    defer bgCancel()
    var bg sync.WaitGroup
    bg.Go(func() { consumer.Run(bgCtx) })                 // exits on bgCtx

    srv := &http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 5 * time.Second,
        ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 120 * time.Second}
    errc := make(chan error, 1)                            // buffered: ListenAndServe's return never blocks
    go func() { errc <- srv.ListenAndServe() }()
    select {
    case err := <-errc: return fmt.Errorf("listen: %w", err)
    case <-ctx.Done(): slog.Info("shutting down", "cause", context.Cause(ctx)) // 1.26+: names the signal
    }
    shCtx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
    defer cancel()
    if err := srv.Shutdown(shCtx); err != nil { return fmt.Errorf("http shutdown: %w", err) } // drains in-flight
    bgCancel()
    done := make(chan struct{})
    go func() { bg.Wait(); close(done) }()
    select {                                                 // bounded join of background work
    case <-done: return nil
    case <-shCtx.Done(): return errors.New("background workers did not stop in time")
    }
}
```

`Shutdown` does not wait for hijacked connections (WebSockets): register cleanup with
`srv.RegisterOnShutdown`. Do not set `BaseContext` to the signal ctx: in-flight requests would be
cancelled at SIGTERM instead of drained.

## 8. Detection

| Tool | Command | Finds | Misses |
|---|---|---|---|
| race detector | `go test -race -shuffle=on -count=1 ./...` in CI | data races on executed paths (2-20x slower, 5-10x memory) | code the tests never run |
| goleak | `goleak.VerifyTestMain(m)` or `defer goleak.VerifyNone(t)` | goroutines alive after a test or package | leaks in code paths not tested; `VerifyNone` is unusable with `t.Parallel` |
| testing/synctest (1.25) | `synctest.Test(t, func(t *testing.T){...})`, `synctest.Wait()`, `synctest.Sleep(d)` (1.27) | timer, timeout and retry logic with a virtual clock, deterministically | code blocked on mutexes, network I/O or syscalls (not durably blocking) |
| goroutine dump | `curl -s localhost:6060/debug/pprof/goroutine?debug=2` or `kill -QUIT <pid>` | thousands of identical blocked stacks, `[chan send, 12 minutes]` | why the stack is blocked |
| goroutineleak profile | 1.26: build with `GOEXPERIMENT=goroutineleakprofile`; 1.27: `/debug/pprof/goroutineleak`, `pprof.Lookup("goroutineleak")` | goroutines blocked on primitives no runnable goroutine can reach (GC-based) | primitives reachable from globals or runnable goroutines' locals |
| vet | `go vet ./...` (`copylocks`, `lostcancel`, `waitgroup`) | lock copies, leaked cancels, misplaced `Add` | logic races |

```go
func TestRetryBackoff(t *testing.T) {
    synctest.Test(t, func(t *testing.T) {
        start := time.Now()                                    // fake clock starts 2000-01-01 UTC
        err := retry(t.Context(), 4, 100*time.Millisecond, func(context.Context) error { return errBoom })
        if !errors.Is(err, errBoom) { t.Fatalf("err = %v", err) }
        if got := time.Since(start); got != 700*time.Millisecond { t.Fatalf("elapsed %v", got) } // 100+200+400
    })
}
```

`retry` and the durable-blocking rules are in the detection playbook, with race-report and dump
reading. `go test -race -count=200 -run TestX ./pkg` shakes out rare interleavings.

## 9. Common bugs

| Bug | Sign in code | Fix |
|---|---|---|
| leak on early return | `go func(){ ch <- r }()` with unbuffered `ch`, reader returns on first error | errgroup, or buffer `len(work)`, or select on ctx |
| unbuffered single-result channel | `ch := make(chan T)` + `select { case <-ch: case <-ctx.Done(): }` | `make(chan T, 1)` |
| loop-variable capture | goroutines all see the last `v`; go.mod `go` < 1.22 | raise the `go` line (then `copyloopvar` flags old `v := v` copies) |
| `WaitGroup.Add` inside the goroutine | `go func(){ wg.Add(1); defer wg.Done() ...}()` | `wg.Go(f)`; vet `waitgroup` (1.25) flags the misplaced `Add` |
| receiver closes the channel | consumer calls `close(ch)` while producers run | producer side closes; consumers signal via ctx |
| select-default busy loop | `for { select { case v := <-ch: ...; default: } }` | remove `default` or block on a timer |
| double close / send on closed | several goroutines may close; producer outlives consumer | single owner closes; `sync.Once` guard if unavoidable |
| lock held across I/O | `mu.Lock()` then an HTTP or DB call | copy out, unlock, call |
| ctx not propagated | `context.Background()` deep in a handler | thread `ctx` through every call |
| `t.Fatal` from a spawned goroutine | `go func(){ t.Fatal(...) }()` | return errors over a channel; `t.Error` + return (vet `testinggoroutine`) |

## 10. Worked example: leaking fan-out to errgroup, verified with goleak

Before: unbounded goroutines, no ctx, unbuffered results, early return, results in arrival order.

```go
func FetchAll(urls []string, get func(string) ([]byte, error)) ([][]byte, error) {
    ch := make(chan result)
    for _, u := range urls {
        go func() { b, err := get(u); ch <- result{b, err} }()
    }
    var out [][]byte
    for range urls {
        r := <-ch
        if r.err != nil { return nil, r.err } // the other senders block on ch forever
        out = append(out, r.body)
    }
    return out, nil
}
```

The test that proves it (fake getter: `"bad"` fails at once, the rest sleep 20 ms):

```go
func TestFetchAllLeaks(t *testing.T) {
    defer goleak.VerifyNone(t)
    get := func(u string) ([]byte, error) {
        if u == "bad" { return nil, errors.New("boom") }
        time.Sleep(20 * time.Millisecond); return []byte(u), nil
    }
    if _, err := FetchAll([]string{"bad", "a", "b", "c"}, get); err == nil { t.Fatal("want error") }
}
```

```text
$ go test -run TestFetchAllLeaks ./fetch          (abridged)
--- FAIL: TestFetchAllLeaks
    found unexpected goroutines:
    [Goroutine 8 in state chan send, with example.com/fetch.FetchAll.func1 on top of the stack: ...
```

After: bounded, cancellable, input-ordered; `Wait` returns only after every goroutine exits.

```go
func FetchAll(ctx context.Context, urls []string, limit int,
    get func(context.Context, string) ([]byte, error)) ([][]byte, error) {
    out := make([][]byte, len(urls))
    g, gctx := errgroup.WithContext(ctx)        // gctx is cancelled on first error AND when Wait returns
    g.SetLimit(limit)                           // Go blocks while limit goroutines are active
    for i, u := range urls {
        if gctx.Err() != nil { break }          // stop scheduling after a failure
        g.Go(func() error {
            b, err := get(gctx, u)
            if err != nil { return fmt.Errorf("fetch %q: %w", u, err) }
            out[i] = b                          // distinct index per goroutine: no lock
            return nil
        })
    }
    if err := g.Wait(); err != nil { return nil, err }
    return out, nil
}
```

The verifying test asserts the error, the concurrency bound and the absence of leaks:

```go
func TestFetchAll(t *testing.T) {
    defer goleak.VerifyNone(t)
    var inflight, peak atomic.Int64
    get := func(ctx context.Context, u string) ([]byte, error) {
        n := inflight.Add(1)
        defer inflight.Add(-1)
        for p := peak.Load(); n > p && !peak.CompareAndSwap(p, n); p = peak.Load() {}
        if u == "bad" { return nil, errors.New("boom") }
        select {
        case <-time.After(20 * time.Millisecond): return []byte(u), nil
        case <-ctx.Done(): return nil, ctx.Err()
        }
    }
    urls := []string{"a", "bad", "b", "c", "d", "e", "f", "g"}
    _, err := FetchAll(t.Context(), urls, 3, get)
    if err == nil || err.Error() != `fetch "bad": boom` { t.Fatalf("err = %v", err) }
    if p := peak.Load(); p > 3 { t.Fatalf("peak in-flight %d, want <= 3", p) }
}
```

```bash
go test -race -count=50 -run 'TestFetchAll$' ./fetch   # ok: no race, no leak, bound held 50 times
```

Production getter: `http.NewRequestWithContext(ctx, ...)`, `defer resp.Body.Close()`, a size cap
(`io.LimitReader`) and an `http.Client` with a `Timeout`.

## 11. Pitfalls

- Using errgroup's derived ctx after `Wait`: it is already cancelled. Name it `gctx`; reuse the parent.
- errgroup does not recover panics: one panicking task kills the process. Recover inside the task.
- A goroutine using the request ctx after the handler returned sees it cancelled: use
  `context.WithoutCancel` plus an owned WaitGroup drained at shutdown.
- `sync.WaitGroup` reuse: new `Go`/`Add` calls must come after the previous `Wait` returned.
- `-race` finds nothing in code your tests do not run concurrently: write a test that does.
- `time.Sleep` in tests to "wait for the goroutine": use `synctest.Wait` or channels; sleeps flake.
- `sync.Pool` holding huge buffers pins memory: drop buffers above a cap before `Put`.
- `GOMAXPROCS` before 1.25 ignores cgroup CPU limits (throttling under a 2-CPU quota on a 64-core
  host); 1.25+ respects the limit unless `GOMAXPROCS` is set explicitly.
- `singleflight` shares one result: if the leader's ctx is cancelled, all waiters get the error.
- A `select` without `ctx.Done()` around `wg.Wait()`-style joins makes shutdown unbounded.

Related: `go-error-handling`, `go-profiling-pprof`, `go-testing-fuzzing`, `go-http-services`,
`go-interfaces-generics`, hub `go-craft`.
