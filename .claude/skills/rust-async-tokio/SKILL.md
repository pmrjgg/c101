---
name: rust-async-tokio
description: "Production async Rust on tokio 1.x. Covers runtime setup, where blocking and CPU work run, task ownership with JoinSet, TaskTracker and CancellationToken, graceful shutdown, channel and lock choice, cancel safety, timeouts and retries, bounded fan-out, Send errors, paused-time tests, tokio-console and runtime metrics. Load when debugging a tokio service bug, stall or leak, or when designing tasks, channels and shutdown."
when_to_use: "Rust code using tokio, tokio-util, futures or reqwest: 'future cannot be sent between threads safely', 'Cannot start a runtime from within a runtime', 'there is no reactor running', p99 latency spikes, memory growing under load, tasks dying silently, lost messages on shutdown, deadlocks across .await, tokio::select! loops, designing workers, actors, fan-out or graceful shutdown, writing async tests."
---

# Async Rust on tokio

Baseline: tokio 1.53, tokio-util 0.7.20, futures 0.3 (October 2026); APIs below compiled and ran on
the Rust Playground (rustc 1.99.1). Check signatures with context7 (`/tokio-rs/tokio`) before
relying on anything newer. Templates for actors, shutdown and the watchdog:
[service templates](references/service-templates.md).

## 1. Runtime setup

| Situation | Setup |
|---|---|
| network service | `#[tokio::main]`: multi-thread, `worker_threads` = number of cores |
| CLI doing a few requests | `#[tokio::main(flavor = "current_thread")]` |
| library | never create a runtime; expose `async fn` and let the application choose |
| tests | `#[tokio::test]`; timers: `#[tokio::test(start_paused = true)]` (feature `test-util`); races: `#[tokio::test(flavor = "multi_thread", worker_threads = 4)]` |
| async inside sync code | build once: `let rt = tokio::runtime::Builder::new_multi_thread().enable_all().build()?;` then `rt.block_on(fut)` |
| sync code called from async, must block | `tokio::task::block_in_place(\|\| ..)` (multi-thread only) or `spawn_blocking` |

Panics to recognise (verified on tokio 1.53):

| Message | Cause |
|---|---|
| "Cannot start a runtime from within a runtime. This happens because a function (like `block_on`) attempted to block the current thread while the thread is being used to drive asynchronous tasks." | `Runtime::block_on` or `Handle::block_on` on a runtime thread |
| "can call blocking only when running on the multi-threaded runtime" | `block_in_place` under `current_thread` |
| "there is no reactor running, must be called from the context of a Tokio 1.x runtime" | `tokio::spawn`/timers/sockets used outside a runtime, e.g. `rt.block_on(tokio::spawn(f))` evaluates `spawn` before `block_on` enters |

## 2. Where work runs

| Work | Place | Note |
|---|---|---|
| async I/O (sockets, `tokio::fs`, `reqwest`, `sqlx`) | the task itself | |
| blocking syscall or blocking crate (`std::fs`, `rusqlite`, compressing a file) | `tokio::task::spawn_blocking(move \|\| ..)` | pool capped by `max_blocking_threads` (default 512), idle threads exit after 10 s |
| CPU-heavy batch (parse 50 MB, hashing, image ops) | rayon, result through `tokio::sync::oneshot` | keeps the 512 blocking threads for I/O |
| long-lived blocking loop (sync consumer library) | dedicated `std::thread::spawn` plus a channel | |

```rust
async fn parse_big(bytes: Vec<u8>) -> anyhow::Result<Doc> {
    let (tx, rx) = tokio::sync::oneshot::channel();
    rayon::spawn(move || {
        // an uncaught panic in rayon::spawn aborts the process ("Rayon: detected unexpected panic; aborting")
        let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| parse(&bytes)));
        let _ = tx.send(r.unwrap_or_else(|_| Err(anyhow::anyhow!("parser panicked"))));
    });
    rx.await.context("rayon job dropped")?          // RecvError only if the job never ran to the send
}
```

Budget: a task should reach an `.await` within roughly 10 to 100 µs. A longer poll stalls every
other task queued on that worker: measured, two tasks calling `std::thread::sleep(200 ms)` on a
2-worker runtime delayed a 20 ms timer by 180 ms.

## 3. Task ownership and graceful shutdown

Every spawned task has an owner that sees its result. `JoinSet` when results matter, `TaskTracker`
when only "all finished" matters. Dropping a `JoinSet` aborts its tasks; dropping a `JoinHandle`
detaches the task (it keeps running, its result and panic are lost).

```rust
use tokio_util::{sync::CancellationToken, task::TaskTracker};

let cancel = CancellationToken::new();
let tracker = TaskTracker::new();
for id in 0..workers {
    let token = cancel.child_token();                 // cancelling the parent cancels every child
    tracker.spawn(async move {
        while let Some(job) = token.run_until_cancelled(next_job()).await.flatten() {
            if let Err(e) = handle(job).await { tracing::warn!(error = %format!("{e:#}"), worker = id); }
        }
    });
}

tokio::signal::ctrl_c().await?;          // or SIGTERM via tokio::signal::unix
accept_cancel.cancel();                  // 1. stop accepting; the accept loop drops its Sender, closing the queue
tracker.close();                         //    no new tasks; wait() resolves once all tasks finished
// 2. soft drain: workers empty the queue (recv() returns None when it is empty and closed)
if timeout(Duration::from_secs(25), tracker.wait()).await.is_err() {
    cancel.cancel();                     // 3. hard stop: workers quit at their next await
    if timeout(Duration::from_secs(5), tracker.wait()).await.is_err() {
        anyhow::bail!("stragglers after 30 s");   // 4. exit anyway (JoinSet::shutdown aborts and waits)
    }
}
```

Order matters. Measured with 4 workers, 30 ms jobs and a 5 ms producer stopped after 200 ms:
cancelling workers first handled 27 of 41 accepted jobs (14 dropped from the queue); closing the
input and draining first handled all 41. Cancel first only when queued work is disposable.

`run_until_cancelled(fut)` returns `None` when the token fires first (cancel-safe only if `fut` is).
`token.drop_guard()` cancels on drop, tying a child tree to a scope. `JoinSet::shutdown().await`
aborts and waits; `join_all().await` collects every result. Decide per service whether a worker
panic is fatal (usually: log, count, restart the worker, alert on rate).

## 4. Channels

| Need | Channel | Note |
|---|---|---|
| many producers, one consumer, backpressure | `mpsc::channel(n)` | `send().await` waits when full; n = the burst you accept to buffer |
| request/response | `oneshot` inside the request (actor pattern below) | |
| every subscriber sees every message | `broadcast::channel(n)` | a slow receiver gets `Err(RecvError::Lagged(k))`, then resumes at the oldest retained message |
| latest value only (config, health) | `watch::channel(v)` | `changed().await`, then `borrow_and_update()` |
| sync thread to async | `mpsc` with `blocking_send` / `blocking_recv` (panic inside a runtime), or `flume` | |

Measured: `broadcast::channel(2)` with 5 sends gives the receiver `Lagged(3)`, then `Ok(3)`.
`unbounded_channel` turns overload into OOM: never feed it from external input; if unavoidable,
export its depth as a metric.

```rust
enum Cmd { Get { key: String, reply: oneshot::Sender<Option<u64>> }, Incr { key: String } }

async fn actor(mut rx: mpsc::Receiver<Cmd>) {                 // owns the state: no locks
    let mut state = HashMap::<String, u64>::new();
    while let Some(cmd) = rx.recv().await {                   // ends when all senders are dropped
        match cmd {
            Cmd::Get { key, reply } => { let _ = reply.send(state.get(&key).copied()); }
            Cmd::Incr { key } => *state.entry(key).or_default() += 1,
        }
    }
}
// caller: let (tx, rx) = oneshot::channel(); handle.send(Cmd::Get { key, reply: tx }).await?; rx.await?
```

## 5. Locks in async code

| Lock | Use when |
|---|---|
| `std::sync::Mutex` / `parking_lot::Mutex` | the guard never crosses `.await` (most cases, faster) |
| `tokio::sync::Mutex` | the guard must live across `.await` (serialising use of one connection) |
| `tokio::sync::RwLock` | read-heavy and the guard crosses `.await` |
| `tokio::sync::Semaphore` | limit concurrency; `Arc<Semaphore>::acquire_owned()` moves the permit into a task |
| actor task + mpsc | contended state, invariants spanning several fields, I/O while "holding" state |

Keep std guards out of the future's state with a block: `let snapshot = { let g =
state.lock().unwrap(); g.items.clone() }; send(snapshot).await?;`. clippy `await_holding_lock` and
`await_holding_refcell_ref` (suspicious group, warn by default) flag the mistake.

## 6. Cancel safety

A future is dropped at an `.await` whenever its caller stops polling: a `select!` branch loses,
`timeout` fires, the task is aborted, axum drops a handler because the client disconnected.

| Operation | Cancel-safe | If not, on cancel |
|---|---|---|
| `mpsc`/`broadcast` `recv`, `watch::changed`, `TcpListener::accept`, `AsyncReadExt::read`/`read_buf`, `AsyncWriteExt::write`/`write_buf`, `StreamExt::next` | yes | |
| `read_exact`, `read_to_end`, `read_to_string` | no | bytes already read are lost |
| `write_all` | no | unknown amount written |
| `mpsc::Sender::send` | no | the message is dropped |
| `Mutex::lock`, `RwLock::read`/`write`, `Semaphore::acquire`, `Notify::notified` | no data loss | loses its place in the fair queue |
| your `async fn` with state between two awaits | assume no | audit it |

```rust
let permit = tx.reserve().await?;      // cancel-safe: nothing is lost if cancelled here
permit.send(msg);                      // synchronous, cannot be cancelled

let deadline = tokio::time::sleep(Duration::from_secs(30));
tokio::pin!(deadline);                 // created once; polled by reference every iteration
loop {
    tokio::select! {
        biased;                        // poll in order: shutdown first (default order is random)
        _ = shutdown.cancelled() => break,
        _ = &mut deadline => break,
        Some(msg) = rx.recv() => process(msg).await,
        else => break,                 // every branch disabled; without `else` select! panics
    }
}
```

Read frames with `tokio_util::codec::FramedRead` (its `next()` is cancel-safe) instead of
`read_exact` inside `select!`. Dropped transactions must roll back: sqlx `Transaction` rolls back on
drop; verify the same for any other client.

## 7. Timeouts, deadlines, retries

- Every network call gets a bound: `tokio::time::timeout(d, fut).await` returns
  `Result<T, Elapsed>`. Set the client's own timeouts too (`reqwest::ClientBuilder::timeout`,
  `connect_timeout`).
- Propagate an absolute deadline, not a fresh timeout per hop: compute it once
  (`let deadline = Instant::now() + budget;`), then `timeout_at(deadline, call()).await` and pass
  `deadline.saturating_duration_since(Instant::now())` downstream (gRPC/HTTP timeout headers).
- Retry only idempotent operations, with exponential backoff plus jitter, capped attempts and the
  remaining deadline respected.

```rust
use backon::{ExponentialBuilder, Retryable};
let body = (|| async { fetch(&client, &url).await })
    .retry(ExponentialBuilder::default().with_jitter().with_max_times(4)
        .with_min_delay(Duration::from_millis(100)).with_max_delay(Duration::from_secs(5)))
    .sleep(tokio::time::sleep)
    .when(|e: &anyhow::Error| is_transient(e))
    .notify(|e, dur| tracing::warn!(error = %e, ?dur, "retrying"))
    .await?;
```

backon 1.6 defaults: factor 2, min delay 1 s, max delay 60 s, 3 retries, no jitter, so set them.
For tower `Service` stacks use `tower::retry` with a `Policy` instead.

## 8. Bounded fan-out

| Shape | Use |
|---|---|
| N futures, results as they finish, max k in flight | `stream::iter(items).map(f).buffer_unordered(k)` |
| same, results in input order | `.buffered(k)` |
| each unit is its own task (parallel CPU, independent failure) | `JoinSet` + `Arc<Semaphore>` permits moved into each task |
| borrow locals, no `'static` | the stream forms above run inside one task, so they may borrow |

`futures::future::join_all` over thousands of futures starts them all at once: no bound on sockets
or memory. Fan-out size k: start near the downstream's concurrency limit (connection pool size,
rate limit times latency), then tune with metrics.

## 9. Send and 'static errors

`tokio::spawn` needs `Future + Send + 'static`. The error "future cannot be sent between threads
safely" names the value ("has type `std::sync::MutexGuard<'_, i32>` which is not `Send`") and the
`.await` that keeps it alive.

| Offender alive across `.await` | Fix |
|---|---|
| `Rc<T>`, `RefCell` borrow | `Arc`, or end the scope before the await |
| std `MutexGuard` | block-scope the guard; or `tokio::sync::Mutex` |
| `tracing` `span.enter()` guard | `fut.instrument(span)` |
| `Box<dyn Error>` without `+ Send + Sync` | `anyhow::Error` or add the bounds |
| genuinely `!Send` state (FFI handle, `Rc` graph) | `LocalSet::run_until` plus `tokio::task::spawn_local` |

`'static`: move owned data or `Arc` clones in (`let db = Arc::clone(&db); tokio::spawn(async move
{ db.query().await })`). To borrow instead, do not spawn: run the futures concurrently in the current
task (`tokio::join!`, `try_join!`, the stream forms of section 8).

## 10. Testing and observability

```rust
// debouncer(input, out, quiet): after a burst on `input`, sends "fired" once `quiet` passes with no event
#[tokio::test(start_paused = true)]
async fn debounce_fires_once() {
    let (in_tx, in_rx) = mpsc::channel(8);
    let (out_tx, mut out_rx) = mpsc::channel(8);
    tokio::spawn(debouncer(in_rx, out_tx, Duration::from_millis(300)));
    for _ in 0..3 { in_tx.send(()).await.unwrap(); }
    tokio::task::yield_now().await;                          // let the debouncer see the burst at t = 0
    tokio::time::advance(Duration::from_millis(299)).await;  // manual step of the paused clock
    assert!(out_rx.try_recv().is_err());
    tokio::time::advance(Duration::from_millis(1)).await;
    assert_eq!(out_rx.recv().await, Some("fired"));
}
```

Full debouncer and this passing test: [service templates](references/service-templates.md).

- Paused time auto-advances when every task is idle, so sleeps cost nothing; `advance(d)` for steps.
- Mock I/O: `let mock = tokio_test::io::Builder::new().write(b"PING\r\n").read(b"+PONG\r\n").build();`
  passes as any `AsyncRead + AsyncWrite`; unmatched writes panic, and leftover script actions panic
  on drop ("There is still data left to read").
- Spans: `#[tracing::instrument(skip(self, body), fields(user = %id), err)]`; spawned work:
  `tokio::spawn(fut.instrument(tracing::info_span!("worker", id)))`.
- Runtime metrics without `tokio_unstable`: `Handle::current().metrics()` gives `num_workers()`,
  `num_alive_tasks()`, `global_queue_depth()`, `worker_total_busy_duration(w)`,
  `worker_park_count(w)`; poll counts, poll-time histograms and blocking-pool gauges need
  `--cfg tokio_unstable`.
- tokio-console (interactive TUI, for humans): add `console-subscriber`, call
  `console_subscriber::init()`, build with `RUSTFLAGS="--cfg tokio_unstable"` (or `[build] rustflags
  = ["--cfg", "tokio_unstable"]` in `.cargo/config.toml`), run `tokio-console` (connects to
  127.0.0.1:6669). Agents use metrics or the scheduling-delay watchdog in the templates file.
- Deterministic interleavings: `loom` for lock-free primitives, `turmoil` for distributed systems.

## 11. Worked example: bounded fetch_all with cancellation

```rust
use std::{future::Future, time::Duration};
use anyhow::Context;
use bytes::Bytes;
use futures::{stream, StreamExt, TryStreamExt};
use tokio_util::sync::CancellationToken;

/// At most `limit` in flight, per-item timeout, input order kept, first error wins, prompt cancel.
pub async fn bounded_all<T, R, F, Fut>(
    items: Vec<T>, limit: usize, per_item: Duration, cancel: &CancellationToken, f: F,
) -> anyhow::Result<Vec<R>>
where T: std::fmt::Display, F: Fn(T) -> Fut, Fut: Future<Output = anyhow::Result<R>>,
{
    let work = stream::iter(items)
        .map(|item| {
            let label = item.to_string();
            let fut = f(item);
            async move {
                tokio::time::timeout(per_item, fut).await
                    .with_context(|| format!("timed out after {per_item:?}: {label}"))?
                    .with_context(|| format!("fetching {label}"))
            }
        })
        .buffered(limit)                 // ordered; buffer_unordered(limit) if order is irrelevant
        .try_collect::<Vec<R>>();        // first Err drops every in-flight future
    match cancel.run_until_cancelled(work).await {
        Some(res) => res,
        None => anyhow::bail!("cancelled"),
    }
}

pub async fn fetch_all(client: &reqwest::Client, urls: Vec<String>, cancel: &CancellationToken)
    -> anyhow::Result<Vec<Bytes>> {
    bounded_all(urls, 16, Duration::from_secs(10), cancel, |u| async move {
        Ok(client.get(&u).send().await?.error_for_status()?.bytes().await?)
    }).await
}
```

Test (passes on tokio 1.53 with `start_paused = true`): 100 items, each sleeping 100 ms, limit 16.
A gauge (`AtomicUsize` incremented on entry, `fetch_max` into `peak`) proves the bound, and the
paused clock proves the wave count without real waiting:

```rust
assert_eq!(out, (0..100u32).map(|i| i * 2).collect::<Vec<_>>());   // order preserved
assert_eq!(peak.load(Ordering::SeqCst), 16);                       // never more than 16 in flight
assert_eq!(start.elapsed(), Duration::from_millis(700));           // ceil(100 / 16) = 7 waves x 100 ms
```

Error paths, printed with `{err:#}` under paused time: an item sleeping 60 s with a 10 s
per-item timeout gives "timed out after 10s: 1: deadline has elapsed"; an item returning
`bail!("boom")` gives "fetching 2: boom"; cancelling the token 50 ms into a run of 5 s items gives
"cancelled" after exactly 50 ms of virtual time. Why it is correct: concurrency is bounded, every request has a timeout, an error or
cancel drops all in-flight futures (nothing half-written, since the stream only reads), and no
task is spawned, so no task can leak.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| p99 latency spikes, CPU mostly idle | blocking call or long CPU loop on a worker | `spawn_blocking`/rayon; find it with the watchdog or `worker_total_busy_duration` |
| memory climbs under load | unbounded channel, unbounded `join_all`, one task per request item | bounded `mpsc`, `buffer_unordered(k)`, semaphore |
| messages lost on shutdown | `send`/`read_exact`/`write_all` cancelled inside `select!` | `reserve()` + `permit.send`, `FramedRead`, drain before exit |
| a worker silently stopped | panic in a detached task, `JoinHandle` dropped | `JoinSet`/`TaskTracker`, log every `JoinError`, panic hook |
| deadlock | guard held across `.await` while another task needs it, or lock-order inversion | scope guards, one lock order, actor task |
| "future cannot be sent between threads safely" | `!Send` value alive across `.await` | section 9 |
| `select!` loop restarts work every iteration | future created inside the loop | create once, `tokio::pin!`, poll `&mut fut` |
| `select!` panics "all branches are disabled and there is no else branch" | every pattern failed | add `else => break` |
| timer test takes real seconds | not using paused time | `start_paused = true`, `time::advance` |
| shutdown hangs forever | a task ignores cancellation | `run_until_cancelled` in loops, `timeout` on `tracker.wait()`, then abort |

Related: `rust-error-handling`, `rust-ownership-lifetimes`, `rust-axum-services`, `rust-performance`,
`rust-testing-fuzzing`, hub `rust-craft`.
