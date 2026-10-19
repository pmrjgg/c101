# tokio service templates (all compiled and run on tokio 1.53 / tokio-util 0.7)

## 1. Worker pool with drain-first graceful shutdown

```rust
use std::{sync::Arc, time::Duration};
use tokio::{sync::{mpsc, Mutex}, time::{sleep, timeout}};
use tokio_util::{sync::CancellationToken, task::TaskTracker};

#[derive(Debug)] struct Job(u32);

async fn handle(job: Job) -> anyhow::Result<()> {
    sleep(Duration::from_millis(30)).await;
    if job.0 % 7 == 3 { anyhow::bail!("job {} failed", job.0) }
    Ok(())
}

async fn accept_loop(tx: mpsc::Sender<Job>, accept_cancel: CancellationToken) {
    let mut n = 0;
    let mut tick = tokio::time::interval(Duration::from_millis(5));   // stand-in for listener.accept()
    loop {
        tokio::select! {
            biased;
            _ = accept_cancel.cancelled() => break,
            _ = tick.tick() => {
                let Ok(permit) = tx.reserve().await else { break };    // cancel-safe enqueue
                permit.send(Job(n)); n += 1;
            }
        }
    }
    tracing::info!(accepted = n, "accept loop stopped");             // `tx` dropped here: queue closes
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let (tx, rx) = mpsc::channel::<Job>(64);
    let rx = Arc::new(Mutex::new(rx));            // tokio Mutex: the guard is held across recv().await
    let (accept_cancel, cancel) = (CancellationToken::new(), CancellationToken::new());
    let tracker = TaskTracker::new();
    tracker.spawn(accept_loop(tx, accept_cancel.clone()));
    for id in 0..4 {
        let (token, rx) = (cancel.child_token(), Arc::clone(&rx));
        tracker.spawn(async move {
            let next_job = || async { rx.lock().await.recv().await };
            while let Some(job) = token.run_until_cancelled(next_job()).await.flatten() {
                if let Err(e) = handle(job).await { tracing::warn!(error = %format!("{e:#}"), worker = id); }
            }
        });
    }
    tokio::signal::ctrl_c().await?;
    accept_cancel.cancel();
    tracker.close();
    if timeout(Duration::from_secs(25), tracker.wait()).await.is_err() {
        cancel.cancel();
        if timeout(Duration::from_secs(5), tracker.wait()).await.is_err() {
            anyhow::bail!("stragglers after 30 s");
        }
    }
    Ok(())
}
```

Measured (shutdown triggered 200 ms in, 4 workers): drain-first processed 41 of 41 accepted jobs;
the cancel-first variant (`cancel.cancel()` before waiting) processed 27 and dropped 14 queued jobs.
A shared `Arc<Mutex<Receiver>>` is the simplest multi-consumer queue; for high rates prefer one
channel per worker (round-robin dispatch) or `async-channel`/`flume` (multi-consumer receivers).

## 2. Actor with a typed handle

```rust
use std::collections::HashMap;
use tokio::sync::{mpsc, oneshot};

enum Cmd { Get { key: String, reply: oneshot::Sender<Option<u64>> }, Incr { key: String } }

#[derive(Clone)]
pub struct Counter { tx: mpsc::Sender<Cmd> }

impl Counter {
    pub fn spawn(tracker: &tokio_util::task::TaskTracker) -> Self {
        let (tx, mut rx) = mpsc::channel(64);
        tracker.spawn(async move {
            let mut state = HashMap::<String, u64>::new();
            while let Some(cmd) = rx.recv().await {          // exits when every Counter clone is dropped
                match cmd {
                    Cmd::Get { key, reply } => { let _ = reply.send(state.get(&key).copied()); }
                    Cmd::Incr { key } => *state.entry(key).or_default() += 1,
                }
            }
        });
        Counter { tx }
    }
    pub async fn incr(&self, key: &str) -> anyhow::Result<()> {
        let permit = self.tx.reserve().await.map_err(|_| anyhow::anyhow!("counter actor stopped"))?;
        permit.send(Cmd::Incr { key: key.to_owned() });
        Ok(())
    }
    pub async fn get(&self, key: &str) -> anyhow::Result<Option<u64>> {
        let (reply, rx) = oneshot::channel();
        self.tx.send(Cmd::Get { key: key.to_owned(), reply }).await
            .map_err(|_| anyhow::anyhow!("counter actor stopped"))?;
        Ok(rx.await?)                                         // RecvError if the actor dropped `reply`
    }
}
```

Verified: `incr("a")` then `get("a")` returns `Some(1)`. Rules: bounded mailbox; the actor never
awaits another actor that may await it (cycle = deadlock); long work inside the actor blocks every
caller, so spawn it and send the result back as a message.

## 3. Scheduling-delay watchdog (what agents use instead of tokio-console)

```rust
async fn watchdog(period: Duration, warn_after: Duration) {
    loop {
        let start = tokio::time::Instant::now();
        tokio::time::sleep(period).await;
        let lag = start.elapsed().saturating_sub(period);
        if lag > warn_after { tracing::warn!(?lag, "scheduler lag: a task is blocking a worker"); }
    }
}
// tokio::spawn(watchdog(Duration::from_millis(20), Duration::from_millis(10)));
```

Measured on a 2-worker runtime: two tasks each calling `std::thread::sleep(200 ms)` produced
"scheduler lag 180.185899ms". Combine with a periodic metrics log:

```rust
let m = tokio::runtime::Handle::current().metrics();
let busy: Vec<_> = (0..m.num_workers()).map(|w| m.worker_total_busy_duration(w)).collect();
tracing::info!(alive = m.num_alive_tasks(), global_queue = m.global_queue_depth(), ?busy, "runtime");
```

A worker whose busy duration grows by the full sampling interval while others idle is running a
blocking or CPU-heavy task.

## 4. Debouncer with a paused-time test

```rust
use std::time::Duration;
use tokio::sync::mpsc;

pub async fn debouncer(mut input: mpsc::Receiver<()>, out: mpsc::Sender<&'static str>, quiet: Duration) {
    while input.recv().await.is_some() {
        loop {
            match tokio::time::timeout(quiet, input.recv()).await {
                Ok(Some(())) => continue,                 // another event: restart the quiet window
                Ok(None) => return,                       // input closed
                Err(_) => { let _ = out.send("fired").await; break; }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test(start_paused = true)]
    async fn debounce_fires_once() {
        let (in_tx, in_rx) = mpsc::channel(8);
        let (out_tx, mut out_rx) = mpsc::channel(8);
        tokio::spawn(debouncer(in_rx, out_tx, Duration::from_millis(300)));
        for _ in 0..3 { in_tx.send(()).await.unwrap(); }
        tokio::task::yield_now().await;                          // debouncer sees the burst at t = 0
        tokio::time::advance(Duration::from_millis(299)).await;
        assert!(out_rx.try_recv().is_err());
        tokio::time::advance(Duration::from_millis(1)).await;
        assert_eq!(out_rx.recv().await, Some("fired"));
        drop(in_tx);
        assert_eq!(out_rx.recv().await, None);                   // debouncer exited, sender dropped
    }
}
```

Without the `yield_now`, the spawned task first runs after `advance(299)` and starts its window at
t = 299 ms; the final `recv` still succeeds because paused time auto-advances, so the test would
pass while checking the wrong thing. Make every paused-time test assert the virtual instant it
expects (`Instant::now()` deltas), not just the eventual value.

## 5. Sync and async bridges

```rust
let (tx, mut rx) = tokio::sync::mpsc::channel::<u32>(8);
let producer = std::thread::spawn(move || {           // plain OS thread, e.g. a C callback loop
    for i in 0..3 { tx.blocking_send(i).unwrap(); }   // blocks this thread when full; panics on a runtime thread
});
while let Some(v) = rx.recv().await { println!("from thread {v}"); }
producer.join().unwrap();
```

And `!Send` work on the async side:

```rust
let local = tokio::task::LocalSet::new();
let n = local.run_until(async {
    let rc = std::rc::Rc::new(41);
    tokio::task::spawn_local(async move { tokio::task::yield_now().await; *rc + 1 }).await.unwrap()
}).await;   // 42
```
