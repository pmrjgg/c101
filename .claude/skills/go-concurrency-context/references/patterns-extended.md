# Extended Go concurrency patterns

Each pattern states its exit path. Packages: `golang.org/x/sync/{errgroup,semaphore,singleflight}`,
`golang.org/x/time/rate`.

## Merge two streams with nil-channel disabling

```go
for in1 != nil || in2 != nil {
    select {
    case v, ok := <-in1:
        if !ok { in1 = nil; continue }   // a nil channel never becomes ready: case disabled
        handle(v)
    case v, ok := <-in2:
        if !ok { in2 = nil; continue }
        handle(v)
    case <-ctx.Done():
        return ctx.Err()
    }
}
```

Exit: both inputs closed, or ctx cancelled.

## Ordered parallel map (bounded)

```go
func ParallelMap[T, R any](ctx context.Context, in []T, limit int,
    f func(context.Context, T) (R, error)) ([]R, error) {
    out := make([]R, len(in))
    g, gctx := errgroup.WithContext(ctx)
    g.SetLimit(limit)
    for i, v := range in {
        if gctx.Err() != nil { break }
        g.Go(func() error {
            r, err := f(gctx, v)
            if err != nil { return err }
            out[i] = r                       // each goroutine owns one index
            return nil
        })
    }
    if err := g.Wait(); err != nil { return nil, err }
    return out, nil
}
```

Use `g.TryGo` when the caller must not block once the limit is reached (it reports whether the
task started).

## Weighted semaphore (no worker goroutines)

```go
sem := semaphore.NewWeighted(int64(maxInFlightBytes))
func upload(ctx context.Context, blob []byte) error {
    if err := sem.Acquire(ctx, int64(len(blob))); err != nil { return err } // ctx-aware wait
    defer sem.Release(int64(len(blob)))
    return put(ctx, blob)
}
```

A weight larger than the semaphore size never succeeds and blocks until ctx ends: cap or reject it.
For a plain count, `sem := make(chan struct{}, n)`; acquire `sem <- struct{}{}` inside a `select`
with `ctx.Done()`, release `<-sem` in a `defer`.

## singleflight without coupling callers' cancellation

```go
var g singleflight.Group
func (c *Cache) User(ctx context.Context, id string) (*User, error) {
    ch := g.DoChan(id, func() (any, error) {
        lctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 3*time.Second)
        defer cancel()                       // shared call: one caller leaving must not fail the others
        return c.load(lctx, id)
    })
    select {
    case r := <-ch:
        if r.Err != nil { return nil, r.Err }
        return r.Val.(*User), nil            // r.Shared reports whether the result was shared
    case <-ctx.Done():
        return nil, ctx.Err()
    }
}
```

Errors are shared too; call `g.Forget(id)` if a failed load should not be joined by later callers
while it is still in flight.

## Rate limiting

```go
lim := rate.NewLimiter(rate.Every(100*time.Millisecond), 5)   // 10 events/s, bursts of 5
for _, job := range jobs {
    if err := lim.Wait(ctx); err != nil { return err }          // fails fast if ctx ends or the wait exceeds its deadline
    go process(ctx, job)                                       // still needs an owner and a bound
}
```

`lim.Allow()` for drop-on-overload, `lim.Reserve()` to learn the delay without blocking.

## Pub/sub with per-subscriber buffers and drop policy

```go
type Broker[T any] struct { mu sync.Mutex; subs map[chan T]struct{} }

func NewBroker[T any]() *Broker[T] { return &Broker[T]{subs: map[chan T]struct{}{}} }

func (b *Broker[T]) Subscribe(buf int) (<-chan T, func()) {
    ch := make(chan T, buf)
    b.mu.Lock(); b.subs[ch] = struct{}{}; b.mu.Unlock()
    return ch, func() {                       // unsubscribe closes under the lock: no send on closed
        b.mu.Lock(); defer b.mu.Unlock()
        if _, ok := b.subs[ch]; ok { delete(b.subs, ch); close(ch) }
    }
}

func (b *Broker[T]) Publish(v T) (dropped int) {
    b.mu.Lock(); defer b.mu.Unlock()
    for ch := range b.subs {
        select { case ch <- v: default: dropped++ } // never block the publisher on a slow subscriber
    }
    return dropped
}
```

Export `dropped` as a metric. If loss is unacceptable, the tee in SKILL.md (lock-step) or a
persistent queue is the right tool instead.

## Batching by size or time

```go
func batch[T any](ctx context.Context, in <-chan T, max int, every time.Duration, flush func([]T)) {
    t := time.NewTicker(every)
    defer t.Stop()
    buf := make([]T, 0, max)
    emit := func() { if len(buf) > 0 { flush(buf); buf = make([]T, 0, max) } } // flush may retain buf
    for {
        select {
        case v, ok := <-in:
            if !ok { emit(); return }
            if buf = append(buf, v); len(buf) == max { emit() }
        case <-t.C:
            emit()
        case <-ctx.Done():
            emit()                            // or drop, by policy; document which
            return
        }
    }
}
```

## Copy-on-write configuration reload

```go
type Holder struct{ p atomic.Pointer[Config] }
func (h *Holder) Get() *Config { return h.p.Load() }           // readers never lock, never mutate
func (h *Holder) Update(f func(old Config) Config) {
    for {
        old := h.p.Load()
        next := f(*old)                                        // copy, modify the copy
        if h.p.CompareAndSwap(old, &next) { return }           // retry if a concurrent update won
    }
}
```

Deep fields (maps, slices) inside `Config` must be cloned in `f` (`maps.Clone`, `slices.Clone`),
otherwise readers and the writer share them.

## sync.Cond

Rarely the right tool: it cannot be combined with `ctx.Done()` in a `select`. Prefer a channel
that is closed or replaced on state change. If used, always `Wait` in a loop re-checking the
condition, with the lock held.
