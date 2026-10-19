# Async Rust with tokio: production rules

Scope: tokio 1.x multi-thread runtime services (axum, tonic, hyper, sqlx, reqwest). Check exact
signatures with context7 (`/tokio-rs/tokio`) when in doubt; the module paths below are stable.

## 1. Runtime setup

| Situation | Setup |
|---|---|
| network service | `#[tokio::main]` (multi-thread, one worker per core) |
| CLI doing a few requests | `#[tokio::main(flavor = "current_thread")]` |
| library | never create a runtime; expose `async fn`, let the app choose |
| tests | `#[tokio::test]`; time-dependent tests `#[tokio::test(start_paused = true)]` |
| embedding async in sync code | build once: `tokio::runtime::Builder::new_multi_thread().enable_all().build()?`, then `rt.block_on(..)` |

Never call `block_on` from inside a runtime worker (panics: "Cannot start a runtime from within a
runtime"). From sync code already inside a runtime use `tokio::task::block_in_place` (multi-thread
flavor only) or restructure.

## 2. Blocking and CPU work

| Work | Where |
|---|---|
| async I/O (sockets, `tokio::fs`) | the task itself |
| blocking syscall / blocking crate (std::fs, rusqlite, compression of a large file) | `tokio::task::spawn_blocking(move || ...)` (pool default max 512 threads) |
| CPU-heavy batch (parsing a 50 MB file, hashing, image ops) | `rayon` pool; return result via `tokio::sync::oneshot` |
| long-lived blocking loop (consumer of a sync library) | dedicated `std::thread::spawn` with a channel bridge |

Rule of thumb: a task should reach an `.await` within roughly 10-100 µs. Detect violations with
`tokio-console` (build with `RUSTFLAGS="--cfg tokio_unstable"` and `console-subscriber`), which
flags tasks with long poll times, or with a watchdog that measures scheduling delay.

## 3. Task ownership and shutdown

```rust
use tokio::task::JoinSet;
use tokio_util::{sync::CancellationToken, task::TaskTracker};

let cancel = CancellationToken::new();
let tracker = TaskTracker::new();

for i in 0..workers {
    let cancel = cancel.child_token();
    tracker.spawn(async move {
        loop {
            tokio::select! {
                _ = cancel.cancelled() => break,
                job = next_job() => { if let Err(e) = handle(job).await { tracing::warn!(error = %e, worker = i); } }
            }
        }
    });
}

tokio::signal::ctrl_c().await?;
cancel.cancel();              // ask everything to stop
tracker.close();              // no new tasks
tokio::time::timeout(Duration::from_secs(30), tracker.wait()).await.ok(); // bounded drain
```

`JoinSet` when you need each task's result (`while let Some(res) = set.join_next().await`);
`TaskTracker` when you only need "all finished". Dropping a `JoinSet` aborts its tasks; dropping a
`JoinHandle` detaches the task (it keeps running, result lost).

`JoinError` means the task panicked or was aborted: `res.map_err(|e| if e.is_panic() { ... })`.
Decide per service whether a worker panic is fatal (usually: log, increment a metric, restart the
worker, alert on rate).

## 4. Channels

| Need | Channel | Notes |
|---|---|---|
| many producers, one consumer, backpressure | `tokio::sync::mpsc::channel(n)` | size n = burst you accept to buffer; `send().await` waits when full |
| request/response | `tokio::sync::oneshot` | embed the `oneshot::Sender` in the request message (actor pattern) |
| fan-out every message to all subscribers | `tokio::sync::broadcast::channel(n)` | slow receivers get `RecvError::Lagged(k)`; handle it |
| latest value only (config, health) | `tokio::sync::watch` | receivers see only the newest value; `changed().await` |
| sync↔async bridge | `mpsc` with `blocking_send` / `blocking_recv`, or `flume` | |

Never use `unbounded_channel` for data derived from external input. If you must, meter its depth.

## 5. Locks in async code

| Lock | Use when |
|---|---|
| `std::sync::Mutex` / `parking_lot::Mutex` | guard never crosses `.await` (most cases; faster) |
| `tokio::sync::Mutex` | guard must be held across `.await` (e.g. serializing access to a connection) |
| `tokio::sync::RwLock` | read-heavy and guard crosses `.await` |
| `tokio::sync::Semaphore` | bounding concurrency (`acquire_owned` to move a permit into a task) |
| actor task + mpsc | contended mutable state, complex invariants, I/O while "holding" state |

Pattern to keep a std guard out of the future's state:

```rust
let snapshot = { let g = state.lock().unwrap(); g.items.clone() };  // guard dropped here
send(snapshot).await?;
```

## 6. Cancellation safety

A future is dropped at any `.await` when its caller is cancelled (`select!` loses, `timeout`
fires, the task is aborted, the request is dropped by axum on client disconnect).

| Operation | Cancel-safe? | Consequence if not |
|---|---|---|
| `mpsc::Receiver::recv`, `broadcast::Receiver::recv`, `watch::Receiver::changed` | yes | |
| `TcpListener::accept`, `AsyncReadExt::read` | yes | |
| `AsyncReadExt::read_exact`, `read_to_end`, `read_to_string` | no | bytes consumed and lost |
| `AsyncWriteExt::write_all` | no | partial write, unknown how much |
| `mpsc::Sender::send` | no (message dropped, not sent) | use `reserve().await` then `permit.send(msg)` |
| `tokio::sync::Mutex::lock` | yes, but loses queue position | |
| user `async fn` doing two awaits with state in between | usually no | audit it |

`select!` in a loop: create long-lived futures once and poll by reference, otherwise each
iteration restarts them.

```rust
let deadline = tokio::time::sleep(Duration::from_secs(30));
tokio::pin!(deadline);
loop {
    tokio::select! {
        _ = &mut deadline => break,
        Some(msg) = rx.recv() => process(msg).await,
        else => break,                       // all branches disabled (channel closed)
    }
}
```

Use `biased;` as the first token inside `select!` when branch priority matters (e.g. always
check shutdown first); default is random to avoid starvation.

Database transactions: a dropped future mid-transaction must roll back. sqlx `Transaction` rolls
back on drop; verify the same for any other client before relying on it.

## 7. Timeouts and deadlines

- `tokio::time::timeout(d, fut).await` returns `Result<T, Elapsed>`; wrap every external call.
- Propagate an absolute deadline (`Instant`) through request handling and compute remaining
  budget per hop: `timeout_at(deadline, fut)`.
- Client libraries have their own timeouts (reqwest `ClientBuilder::timeout`,
  `connect_timeout`); set both the library timeout and an outer budget.
- Retries: exponential backoff with jitter, cap attempts, only for idempotent operations, and
  respect the remaining deadline. `backon` or `tokio-retry` crates, or a 10-line loop.

## 8. Streams and fan-out

```rust
use futures::{stream, StreamExt};
// unordered, max 32 concurrent, results as they complete
let results: Vec<_> = stream::iter(items).map(process).buffer_unordered(32).collect().await;
// ordered results
let results: Vec<_> = stream::iter(items).map(process).buffered(32).collect().await;
```

`futures::future::join_all` on thousands of futures has no concurrency bound on in-flight I/O
(they all start); prefer `buffer_unordered`. `JoinSet` + `Semaphore` when each unit must run as
its own task (parallel CPU across workers, independent failure).

## 9. Send bounds and spawning

- `tokio::spawn` requires `Future + Send + 'static`. The error points at the await where a
  non-`Send` value is live; the value is listed in the note ("has type `Rc<..>` which is not Send").
- Usual offenders: `Rc`, `RefCell` borrows, std `MutexGuard`, `&mut` to a non-Sync type,
  `Box<dyn Error>` without `+ Send + Sync`, `tracing::span::Entered` guards (use `.instrument(span)`).
- `tokio::task::spawn_local` inside a `LocalSet` for genuinely `!Send` futures.

## 10. Testing async code

```rust
#[tokio::test(start_paused = true)]
async fn retries_with_backoff() {
    let start = tokio::time::Instant::now();
    let r = fetch_with_retry(&flaky_server(3)).await;   // 3 failures then success
    assert!(r.is_ok());
    assert!(start.elapsed() >= Duration::from_millis(700)); // virtual time; test runs instantly
}
```

- Paused time auto-advances when all tasks are idle; `tokio::time::advance(d)` for manual steps.
- `tokio::test(flavor = "multi_thread", worker_threads = 4)` to surface Send and race issues.
- Deterministic concurrency exploration: `loom` for lock-free primitives (models every
  interleaving of a small test); `turmoil` for distributed-system simulation tests.

## 11. Observability

- `tracing` with `#[tracing::instrument(skip(big_arg), fields(user_id = %id))]`; attach spans
  to spawned futures with `.instrument(tracing::info_span!("worker", i))`.
- Never hold `span.enter()` guards across `.await`.
- Runtime metrics: `tokio::runtime::Handle::current().metrics()` (some fields require
  `tokio_unstable`), plus tokio-console in staging.

## 12. Async pitfalls quick table

| Symptom | Cause | Fix |
|---|---|---|
| p99 latency spikes, CPU idle | blocking call on worker | `spawn_blocking`; find with runtime metrics or a scheduling-delay watchdog (tokio-console is interactive: humans) |
| memory climbs under load | unbounded channel or unbounded `join_all` | bounded channel, `buffer_unordered` |
| messages lost on shutdown | `select!` cancelled a non-cancel-safe send/read | `reserve()` pattern, cancel-safe reads with buffered framing (`tokio_util::codec::FramedRead`) |
| task silently stopped | panic in detached task | `JoinSet` + log `JoinError`, panic hook |
| deadlock | lock held across `.await` while the other task needs it | scope guards, actor |
| "future cannot be sent between threads" | non-Send value live across await | drop before await, Arc, or `spawn_local` |
| timer test takes real seconds | not using paused time | `start_paused = true` |
