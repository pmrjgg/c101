# Go concurrency patterns and their failure modes

## 1. Choosing the primitive

| Need | Primitive |
|---|---|
| protect shared state | `sync.Mutex` (or `RWMutex` if reads dominate and critical sections are long) |
| run N tasks, wait, first error cancels | `golang.org/x/sync/errgroup` with `WithContext` and `SetLimit` |
| run N tasks, wait, no error handling | `sync.WaitGroup` with `wg.Go(f)` (1.25) |
| one-time lazy init | `sync.OnceValue(func() T)` / `sync.OnceValues` / `sync.Once` |
| counters, flags, pointer swaps | `atomic.Int64`, `atomic.Bool`, `atomic.Pointer[T]` |
| hand work to a fixed set of workers | buffered channel + worker goroutines |
| limit concurrency without workers | semaphore channel `make(chan struct{}, n)` or `x/sync/semaphore.Weighted` |
| broadcast "stop" | `context` cancellation (or closing a `chan struct{}`) |
| deduplicate concurrent identical calls | `x/sync/singleflight.Group` |
| reuse short-lived buffers | `sync.Pool` (objects may be dropped at any GC; never for pooled connections) |
| concurrent map with disjoint or append-only keys | `sync.Map`; otherwise mutex + map |
| rate limiting | `golang.org/x/time/rate.Limiter` with `Wait(ctx)` |

## 2. Context rules

- `ctx` is the first parameter, named `ctx`, never nil (use `context.TODO()` while refactoring).
- Derive, do not replace: `ctx, cancel := context.WithTimeout(parent, 2*time.Second); defer cancel()`.
- `context.WithCancelCause` / `context.Cause(ctx)` to record why work stopped.
- `context.WithoutCancel(ctx)` (1.21) for work that must outlive the request (audit log write)
  but keep the request's values; give it its own timeout.
- `context.AfterFunc(ctx, f)` (1.21) to run cleanup on cancellation without a goroutine per wait.
- Values: request-scoped data only (trace IDs, auth principal), unexported key types,
  never optional function parameters.

## 3. Worker pool with bounded queue and shutdown

```go
type Pool struct {
    jobs chan Job
    wg   sync.WaitGroup
}

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

// Submit applies backpressure: blocks while the queue is full, fails when ctx ends.
func (p *Pool) Submit(ctx context.Context, j Job) error {
    select {
    case p.jobs <- j:
        return nil
    case <-ctx.Done():
        return ctx.Err()
    }
}

// Close stops intake and waits for workers to drain the queue.
func (p *Pool) Close() { close(p.jobs); p.wg.Wait() }
```

Only the owner calls `Close`, after all `Submit` callers are done (sending on a closed channel
panics). If producers are independent, guard with a `sync.Once` and a separate `done` channel.

## 4. Pipeline stages

```go
func stage[In, Out any](ctx context.Context, in <-chan In, f func(In) (Out, error)) (<-chan Out, <-chan error) {
    out := make(chan Out)
    errc := make(chan error, 1)
    go func() {
        defer close(out)
        defer close(errc)
        for v := range in {
            r, err := f(v)
            if err != nil { errc <- err; return }
            select {
            case out <- r:
            case <-ctx.Done():
                errc <- ctx.Err()
                return
            }
        }
    }()
    return out, errc
}
```

Every send is in a `select` with `ctx.Done()`; every stage closes its output; downstream
cancellation unblocks upstream senders. Without both properties a pipeline leaks.

## 5. Single-result goroutine without leaks

```go
func withTimeout(ctx context.Context, f func() (int, error)) (int, error) {
    type res struct { v int; err error }
    ch := make(chan res, 1)                    // buffer 1: the goroutine can always finish
    go func() { v, err := f(); ch <- res{v, err} }()
    select {
    case r := <-ch:
        return r.v, r.err
    case <-ctx.Done():
        return 0, ctx.Err()                    // f keeps running unless it observes ctx too
    }
}
```

The buffer prevents the leak of the goroutine itself; it does not stop `f`. Pass `ctx` into `f`
whenever possible.

## 6. Graceful HTTP server shutdown

```go
srv := &http.Server{
    Addr: ":8080", Handler: mux,
    ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second,
    WriteTimeout: 30 * time.Second, IdleTimeout: 120 * time.Second,
}
ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
defer stop()
go func() {
    if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
        log.Fatalf("listen: %v", err)
    }
}()
<-ctx.Done()
shutdownCtx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
defer cancel()
if err := srv.Shutdown(shutdownCtx); err != nil { log.Printf("shutdown: %v", err) }
```

Kubernetes: make the readiness probe fail first, keep the shutdown timeout below
`terminationGracePeriodSeconds`, and stop background workers after the server drains.

## 7. Detecting leaks and races

| Tool | Use |
|---|---|
| `go test -race` | data races on executed paths |
| `go.uber.org/goleak` | `defer goleak.VerifyNone(t)` or `goleak.VerifyTestMain(m)`; fails tests that leave goroutines |
| `testing/synctest` (1.25) | deterministic tests of timers, timeouts, and goroutine coordination with virtual time |
| goroutine profile | `curl localhost:6060/debug/pprof/goroutine?debug=2` groups stacks; look for thousands of identical blocked stacks |
| goroutine leak profile (GA in 1.27; on 1.26 build with `GOEXPERIMENT=goroutineleakprofile`) | `/debug/pprof/goroutineleak` reports goroutines blocked on unreachable primitives |
| `GOTRACEBACK=all` + SIGQUIT | dump all stacks of a hung process |

synctest example:

```go
func TestRetryBackoff(t *testing.T) {
    synctest.Test(t, func(t *testing.T) {
        start := time.Now()
        err := retry(t.Context(), 4, 100*time.Millisecond, alwaysFail) // 4 attempts, 3 backoff sleeps
        if err == nil { t.Fatal("want error") }
        if got := time.Since(start); got != 700*time.Millisecond {   // 100+200+400, virtual clock
            t.Fatalf("elapsed %v", got)
        }
    })
}
```

## 8. Mutex hygiene

- Keep the mutex next to the fields it guards, with a comment: `mu sync.Mutex // guards a, b`.
- `mu.Lock(); defer mu.Unlock()` unless the function then does slow I/O; then copy state out
  and unlock before the I/O.
- Never call user callbacks or send on unbuffered channels while holding a lock.
- `RWMutex` has writer starvation protection but more overhead; benchmark before switching.
- Copying a struct containing a mutex copies the lock state; `go vet` copylocks catches it.

## 9. Atomics

- Typed atomics (`atomic.Int64`, `atomic.Pointer[T]`) prevent mixed atomic/non-atomic access.
- Go's atomics are sequentially consistent; there are no weaker orderings to choose.
- Copy-on-write config: `cfg atomic.Pointer[Config]`; writers build a new `*Config` and
  `Store`; readers `Load` and never mutate.

## 10. Common concurrency bugs in review

| Bug | Sign in code |
|---|---|
| leak on early return | `go func(){ ch <- x }()` with unbuffered `ch` and a reader that can return early |
| close of closed channel | multiple goroutines closing; close not owned by the single sender |
| send on closed channel | producer outlives the consumer that closed the channel |
| WaitGroup misuse | `wg.Add` inside the goroutine (race with `Wait`); use `wg.Go` |
| ticker leak | goroutine still ranging over `ticker.C` with no ctx exit (Timers and Tickers are collectable without `Stop` since 1.23 with go.mod >= 1.23; the leak is the goroutine: tie it to ctx, still `defer t.Stop()` for clarity) |
| context not propagated | `context.Background()` deep inside request handling |
| unbounded goroutines | `for _, x := range input { go handle(x) }` on external input |
| lock held during I/O | `mu.Lock()` followed by network call before `Unlock` |
| map read during write | `RLock` missing on a read path |
