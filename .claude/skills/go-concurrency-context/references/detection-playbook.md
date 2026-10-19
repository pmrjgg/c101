# Detecting races, leaks and deadlocks in Go

## Race detector

```bash
go test -race -shuffle=on -count=1 ./...                 # CI gate
go test -race -count=200 -run 'TestCache$' ./cache       # repeat to hit rare interleavings
GORACE="halt_on_error=1" go test -race ./cache           # stop at the first report
GORACE="history_size=4" go test -race ./cache            # more history when a stack shows "failed to restore"
go build -race -o app-race ./cmd/app                     # race-enabled binary for a staging soak
```

Cost: 2-20x slower, 5-10x memory. Only executed paths are checked, so the test must actually run
the two accesses concurrently. Non-zero exit (default 66) when a race was reported.

Anatomy of a report:

```text
WARNING: DATA RACE
Write at 0x00c0000a4010 by goroutine 8:       <- access 1: stack of the writer
  example.com/cache.(*Cache).Set() cache.go:31
Previous read at 0x00c0000a4010 by goroutine 7:  <- access 2: the conflicting earlier access
  example.com/cache.(*Cache).Get() cache.go:22
Goroutine 8 (running) created at:              <- where each goroutine was started
  example.com/cache.TestConcurrent() cache_test.go:40
Goroutine 7 (finished) created at: ...
```

Procedure: map the address to the field from the two lines (cache.go:31 and :22), find which lock
or owner should guard that field, and fix the design (guard it, give it a single owner, or make it
immutable after publication). Never silence a race by adding `time.Sleep`.

## goleak

```go
func TestMain(m *testing.M) { goleak.VerifyTestMain(m) }   // whole package; works with t.Parallel

func TestWorker(t *testing.T) {
    defer goleak.VerifyNone(t,                             // per test; not with t.Parallel
        goleak.IgnoreTopFunction("example.com/lib.(*poller).loop"), // known long-lived goroutine
        goleak.IgnoreCurrent(),                            // anything already running before this test
    )
    ...
}
```

Options (go.uber.org/goleak): `IgnoreTopFunction(f)` (top frame), `IgnoreAnyFunction(f)` (any
frame, v1.3.0+), `IgnoreCurrent()`, `Cleanup(func(exitCode int))` for `VerifyTestMain`. `Find`
returns the error instead of failing a test. goleak retries for a short time before failing, so
goroutines that are about to exit do not cause flakes. Failure text starts with
`found unexpected goroutines:` followed by one block per goroutine:
`Goroutine N in state <state>, with <function> on top of the stack:`.

Defer order matters: `defer goleak.VerifyNone(t)` must be the first defer so it runs last, after
`srv.Close()`, `cancel()` and `wg.Wait()` defers.

## testing/synctest (Go 1.25+)

```go
func retry(ctx context.Context, attempts int, base time.Duration, f func(context.Context) error) error {
    var err error
    for i, d := 0, base; i < attempts; i, d = i+1, d*2 {
        if err = f(ctx); err == nil { return nil }
        if i == attempts-1 { break }
        t := time.NewTimer(d)
        select {
        case <-ctx.Done(): t.Stop(); return errors.Join(err, context.Cause(ctx))
        case <-t.C:
        }
    }
    return err
}
```

With 4 attempts the sleeps are 100, 200 and 400 ms, so the bubble's clock advances exactly 700 ms
(the SKILL.md test). Rules of the bubble:

| Topic | Rule |
|---|---|
| fake clock | starts at 2000-01-01 00:00 UTC; advances only when every goroutine in the bubble is durably blocked |
| durably blocking | send/receive on a channel created in the bubble, `select` over such channels only, `sync.Cond.Wait`, `sync.WaitGroup.Wait` when `Add`/`Go` ran in the bubble, `time.Sleep` |
| not durably blocking | `sync.Mutex`/`RWMutex` lock, network or file I/O, syscalls: time does not advance while a goroutine waits on these |
| isolation | using a bubble's channel, Timer or Ticker from outside panics; a package-level `sync.WaitGroup` value cannot join a bubble |
| deadlock | all goroutines durably blocked and no timer pending: `Test` fails the test |
| `t.Context()` | Done channel tied to the bubble; `t.Cleanup` runs inside the bubble before `Test` returns |
| forbidden inside | `t.Run`, `t.Parallel`, `t.Deadline`, nested `synctest.Test` |
| `Wait` | blocks until all other bubble goroutines are durably blocked; not concurrently from two goroutines |
| `Sleep(d)` (1.27) | `time.Sleep(d)` followed by `synctest.Wait()` |
| networking | loopback connections are not durably blocking: use `net.Pipe` or (1.27) `httptest.NewTestServer`, which uses an in-memory network |

Go 1.24 had the experimental `synctest.Run` under `GOEXPERIMENT=synctest`; use `synctest.Test`.

## Goroutine dumps

```bash
curl -s 'http://127.0.0.1:6060/debug/pprof/goroutine?debug=1' | head -40   # grouped: "N @ 0x..." per identical stack
curl -s 'http://127.0.0.1:6060/debug/pprof/goroutine?debug=2' > g.txt      # every goroutine, panic-style stacks
grep -E '^goroutine [0-9]+ \[' g.txt | sed -E 's/^goroutine [0-9]+ \[([^],]*).*/\1/' \
  | sort | uniq -c | sort -rn | head                                       # histogram of wait states
kill -QUIT <pid>                                                           # dump all stacks to stderr and exit
```

On fatal panics, `GOTRACEBACK=all` prints every user goroutine instead of only the failing one;
`GOTRACEBACK=crash` adds runtime frames and aborts with SIGABRT so Unix systems can write a core
dump. Set it before starting a process you expect to hang.

| State in `goroutine N [state, M minutes]:` | Usual meaning |
|---|---|
| `chan send` / `chan receive` | missing peer: receiver returned early, or producer never closed |
| `chan send (nil chan)` / `chan receive (nil chan)` | a nil channel outside a `select`: always a bug |
| `select` | every case blocked; check that one case is `ctx.Done()` |
| `select (no cases)` | `select {}`: intentional park |
| `sync.Mutex.Lock`, `sync.RWMutex.RLock`, `semacquire` | contention or deadlock (wording varies by Go version) |
| `sync.WaitGroup.Wait` | waiting for workers that may themselves be blocked |
| `IO wait` | network read; normal for idle keep-alive connections |
| `sleep`, `syscall`, `running`, `runnable` | usually healthy |

The `M minutes` suffix appears once a goroutine has been blocked for about a minute or more.
Leak test: take two dumps minutes apart; a stack whose count only grows is the leak.

## goroutineleak profile

- Go 1.26: experiment, build with `GOEXPERIMENT=goroutineleakprofile`. Go 1.27: generally
  available, the experiment setting is deleted.
- Endpoint `/debug/pprof/goroutineleak` (net/http/pprof); in code
  `pprof.Lookup("goroutineleak").WriteTo(w, 1)`; or `go tool pprof -top http://127.0.0.1:6060/debug/pprof/goroutineleak`.
- Detection uses the garbage collector: a goroutine blocked on a primitive that no runnable
  goroutine (or any goroutine those could unblock) can reach can never wake up.
- Misses leaks whose primitive is reachable from a global variable or from a runnable goroutine's
  locals. A clean profile is not proof of no leaks; keep goleak in tests.

## Deadlock messages

| Message | Cause |
|---|---|
| `fatal error: all goroutines are asleep - deadlock!` | every goroutine blocked (only detected when no goroutine can run, e.g. in small programs and tests) |
| `fatal error: concurrent map writes` / `concurrent map read and map write` | unsynchronised map; the runtime check is best-effort, run `-race` to find the pair |
| `panic: send on closed channel` | a producer outlived the closer: make the producer side own `close` |
| `panic: close of closed channel` | two closers: single owner or `sync.Once` |
| `panic: sync: negative WaitGroup counter` | `Done` called more times than `Add`; use `wg.Go` |
| `fatal error: sync: unlock of unlocked mutex` | unlock on a path that did not lock, or a copied mutex |
