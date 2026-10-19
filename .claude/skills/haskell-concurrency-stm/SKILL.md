---
name: haskell-concurrency-stm
description: "Concurrent Haskell done safely: async combinators, structured concurrency with ki, STM design (TVar, TMVar, TBQueue, retry/orElse), async-exception-safe catching and timeouts, the -threaded RTS and FFI blocking, eventlog debugging, and dejafu testing. Load when writing threaded Haskell, sharing state through STM, or debugging blocked or killed threads."
when_to_use: "Haskell code using forkIO, async, ki, MVar, TVar, TBQueue, TChan, atomically or timeout; errors 'thread blocked indefinitely in an MVar operation' / 'in an STM transaction', 'registerDelay: requires -threaded', ExceptionInLinkedThread; hangs, lost threads, timeouts that never fire, programs using one core, workers or crawlers needing bounded parallelism."
---

# Haskell concurrency and STM

Baseline: GHC 9.10-9.14, `async` 2.2.6, `stm` 2.5.3 (ships with GHC), `unliftio` 0.2.25, `ki`
1.0.1.2, `dejafu` 2.4.0.8. Green threads are cheap (thousands are fine); the scarce resources
are capabilities, file descriptors and remote rate limits.

Deep material: [pattern implementations](references/patterns.md) (worker pool, rate limiter,
single-flight cache, broadcast) | [debugging and testing](references/debugging-testing.md)
(eventlog, thread dumps, dejafu, stress harness)

## 1. Rules

1. Use `async` (or `ki`), not raw `forkIO`, for work whose result or failure matters. A `forkIO`
   thread that throws prints to stderr and dies; the parent never learns.
2. Every child is joined: `wait`, `withAsync`, the combinators below, or `link` when you cannot
   wait. A failure must surface in a thread that handles it.
3. Bound everything: queues (`TBQueue`, never an unbounded `TQueue`/`Chan` fed by external input),
   parallelism (`pooledMapConcurrentlyN`, worker counts), per-request time (`timeout`).
4. Build with `-threaded` and run with `+RTS -N` (`ghc-options: -threaded -rtsopts
   -with-rtsopts=-N`). Without it, one capability runs everything, blocking (safe) FFI calls stall
   all threads, and `registerDelay` throws "registerDelay: requires -threaded". The non-threaded
   RTS is still the default (checked on 9.10.3: `rtsSupportsBoundThreads == False`).
5. Shared mutable state goes in STM (`TVar`) or behind one owner thread; `IORef` only for
   single-writer counters with `atomicModifyIORef'`.
6. Catch only synchronous exceptions (`catchAny`/`tryAny`); never swallow `SomeException`.

## 2. async API

| Function | Semantics | Use |
|---|---|---|
| `concurrently a b` / `concurrently_` | both run; first exception cancels the other and is rethrown | two independent fetches |
| `race a b` / `race_` | first result wins (`Either a b`); loser cancelled | timeouts, fallbacks, "until signal" |
| `withAsync act k` | child cancelled (uninterruptibly) when `k` exits | background helper scoped to a block |
| `async` + `wait` / `waitCatch` / `poll` | manual handle | only inside `withAsync`-like scopes; bare `async` can leak if an earlier `wait` throws |
| `cancel a` | throws `AsyncCancelled`, **waits** for termination; blocks if the target is in an unsafe FFI call or masked | stop a child |
| `link a` / `link2 a b` | rethrows the child's failure in the parent as `ExceptionInLinkedThread`; `AsyncCancelled` ignored | children you cannot `wait` on |
| `mapConcurrently f xs` / `mapConcurrently_` / `forConcurrently(_)` | one thread per element, **no bound** | small, known-size inputs |
| `replicateConcurrently n act` / `replicateConcurrently_` | `n` copies | fixed worker sets |
| `Concurrently` (Applicative, Alternative = race, Monoid) | compose: `runConcurrently ((,) <$> Concurrently a <*> Concurrently b)` | heterogeneous fan-out, `foldMap Concurrently` |
| `concurrentlyE` / `ConcurrentlyE` | first `Left` interrupts the other | typed early failure |
| `pooledMapConcurrentlyN n f xs` / `_` (unliftio) | at most `n` at once, any `MonadUnliftIO` | bounded parallelism over large inputs |
| `waitAny` / `waitAnyCancel` / `waitEither` / `waitBoth` | select over handles | hedged requests |

```haskell
(user, orders) <- runConcurrently $ (,) <$> Concurrently (getUser uid) <*> Concurrently (getOrders uid)
answer <- runConcurrently (Concurrently primary <|> Concurrently (threadDelay 50000 >> fallback))
pooledMapConcurrentlyN_ 8 runJob jobs           -- unliftio: max 8 at once; `n` must be >= 1
```

## 3. ki: structured concurrency where lifetimes must nest

`ki` guarantees no child outlives the scope that created it, for long-lived supervisors and
dynamic spawning, where `withAsync` nesting gets awkward.

```haskell
import qualified Ki
Ki.scoped $ \scope -> do                         -- Ki.scoped :: (Scope -> IO a) -> IO a
  t1 <- Ki.fork scope (fetch a)                  -- Ki.fork :: Scope -> IO a -> IO (Thread a)
  Ki.fork_ scope heartbeatForever                -- IO Void: must never return
  r  <- atomically (Ki.await t1)                 -- await :: Thread a -> STM a (composes with STM)
  atomically (Ki.awaitAll scope)                 -- optional: wait for the rest
  pure r
```

| Event | ki behaviour |
|---|---|
| scope callback returns | living children get an exception, parent waits for them |
| child throws (`fork`) | exception re-raised in the parent, which tears the scope down |
| child throws a handled type (`forkTry @E`) | returned as `Left`, nothing propagates |
| scope used after `scoped` returned | invalid; the scope is only valid inside its callback |
| thread options | `forkWith scope defaultThreadOptions { label = "...", allocationLimit = Just (megabytes 64) }` |

Pick `async` for fan-out/fan-in, `ki` for supervisors that spawn dynamically. Do not mix both for
the same children.

## 4. STM design

| Type | Semantics | Use |
|---|---|---|
| `TVar a` | transactional variable | shared state, flags, counters (`modifyTVar'`, `stateTVar`) |
| `TMVar a` | empty or full (`takeTMVar`, `putTMVar`, `readTMVar`, `writeTMVar`) | one-shot results, locks, handoff |
| `TBQueue a` | bounded FIFO, `newTBQueueIO :: Natural -> IO (TBQueue a)`; `writeTBQueue` retries when full | work queues with backpressure |
| `TQueue a` | unbounded FIFO | internal events with bounded producers only |
| `TChan a` | FIFO with `dupTChan`/`newBroadcastTChanIO` | broadcast |
| `TSem` | counting semaphore (`waitTSem`, `signalTSem`) | limit concurrent access inside STM logic |
| `stm-containers` `StmContainers.Map` | fine-grained concurrent map | many writers on different keys |

Rules:
- **Short and IO-free**: a transaction is re-run on every conflict; long transactions touching hot
  `TVar`s starve. No `unsafeIOToSTM`; perform effects after `atomically` returns, driven by the
  value it returned.
- **Block with `retry`** (or `check cond`): the thread sleeps until a `TVar` it read changes. Choose
  with `orElse`: ``(Just <$> readTBQueue q) `orElse` pure Nothing`` tries the queue without blocking.
- **Invariants by construction**: stm no longer has `always`/`alwaysSucceeds` invariant checks.
  Put related fields in one `TVar` (or update them in one transaction) and expose only functions
  that preserve the invariant. Test the invariant after every step in a stress test.
- **Contention hot spots**: one `TVar (Map k v)` serialises every writer and re-runs readers on
  each commit. Shard it (`Vector (TVar (Map k v))` by key hash) or use `stm-containers`; keep
  global counters per-capability and sum them on read.
- **Timeouts inside STM**: `registerDelay :: Int -> IO (TVar Bool)` (threaded RTS only):

```haskell
awaitFlag :: Int -> TVar Bool -> IO Bool                -- True if set, False on timeout
awaitFlag micros flag = do
  timedOut <- registerDelay micros
  atomically $ (readTVar flag >>= check >> pure True)
       `orElse` (readTVar timedOut >>= check >> pure False)

withdraw :: TVar Int -> Int -> STM ()                   -- blocks until funds suffice
withdraw acc n = do
  bal <- readTVar acc
  when (bal < n) retry
  writeTVar acc (bal - n)
transfer :: TVar Int -> TVar Int -> Int -> IO ()        -- atomic across both accounts
transfer from to n = atomically $ withdraw from n >> modifyTVar' to (+ n)
```

## 5. Async exceptions

| Exception | Thrown by | Note |
|---|---|---|
| `ThreadKilled` | `killThread` | async |
| `AsyncCancelled` | `cancel`, scope exit of `withAsync`/combinators | async |
| `Timeout` (shown as `<<timeout>>`) | `System.Timeout.timeout` | async: a `SomeException` catch inside swallows it |
| `ExceptionInLinkedThread` | `link` | the parent receives it asynchronously |
| `BlockedIndefinitelyOnMVar` / `...OnSTM` | RTS, when GC proves no other thread can wake you | detection is best effort |

Observed on 9.10.3: ``timeout 10000 (threadDelay 1000000 `catch` \(e :: SomeException) -> pure
"swallowed")`` returns `Just "swallowed"`: the timeout is caught as `<<timeout>>` and lost.

- Catch with `catchAny`/`tryAny`/`handleAny` (unliftio, safe-exceptions): they let async
  exceptions through. A catch-all is acceptable only to record and rethrow.
- `timeout n act`: `n < 0` means no limit, `n == 0` returns `Nothing` immediately (both
  checked). The exception is delivered only at a safe point: an unsafe FFI call, an
  `uninterruptibleMask`, or a **non-allocating loop** delays it indefinitely. A tight `Int`
  loop at `-O2` ignored a 200 ms timeout; built with `-fno-omit-yields` it returned `Nothing`.
- `mask $ \restore -> ...` in library code: acquire masked, run the body under `restore`, release
  in `onException`/`finally`. Blocking operations (`takeMVar`, `atomically` that retries,
  `throwTo`) stay interruptible under `mask`. `uninterruptibleMask` only for short cleanup
  (unliftio's `bracket` runs cleanup under it).
- `bracket` + threads: a resource from an enclosing `bracket` must not be used by a child that
  outlives it. Join the child (`withAsync ... wait`) inside the bracket.
- Combining with `tryAny`: `timeout n (tryAny act)` turns per-call failures into values and the
  timeout still fires, because `tryAny` lets the async `Timeout` through (with a base
  `try @SomeException` in that position, the timeout would be swallowed).

## 6. Runtime details

| Topic | Fact | Action |
|---|---|---|
| capabilities | `+RTS -N` = one per core; `-N4` fixed; `-maxN8` caps it; `setNumCapabilities` at runtime | match container CPU limits |
| IO-bound work | green threads overlap waits on any `-N`: the worked example takes the same 0.65 s at `-N1` and `-N4` | `-N` helps CPU-bound work |
| `safe` FFI call (default) | releases the capability; other Haskell threads keep running (threaded RTS) | blocking C calls |
| `unsafe` FFI call | holds the capability and blocks GC sync: one slow call stalls every thread at the next GC | only short, non-blocking, non-callback calls |
| `interruptible` FFI (`InterruptibleFFI`) | async exceptions interrupt the call (signals the OS thread) | long blocking syscalls you need to cancel |
| bound threads | `forkOS`, `runInBoundThread`; `main` is bound under `-threaded` | C libraries with thread-local state (GUI, OpenGL) |
| `MVar` take without put | an exception between `takeMVar` and `putMVar` leaves it empty forever | `modifyMVar_`, `withMVar` (exception-safe) |
| `MVar` lock ordering | two threads taking two MVars in opposite order deadlock | single global order, or one STM transaction |
| lazy value in `MVar`/`TVar` | the thunk is evaluated by the reader, possibly much later | `putMVar v $! x`, `modifyTVar'`, strict fields |
| `BlockedIndefinitelyOnMVar/STM` | raised only when the variable becomes unreachable from live threads | not a deadlock detector: a reference held elsewhere (global, `Env`) hides it |

## 7. Patterns (full code in [patterns](references/patterns.md))

| Pattern | Core | Watch out |
|---|---|---|
| worker pool on `TBQueue` | producer `writeTBQueue q (Just x)`, then one `Nothing` per worker; `concurrently_ producer (replicateConcurrently_ n worker)` | a worker blocking on writing into the queue it drains deadlocks: never block on your own queue |
| broadcast | `bc <- newBroadcastTChanIO`; each subscriber `dupTChan bc` before the first write | subscribers miss earlier messages; slow ones grow memory (unbounded) |
| rate limiter | token bucket in a `TVar Int`, refill thread under `withAsync`, `acquire = atomically (readTVar t >>= \n -> check (n > 0) >> writeTVar t (n - 1))` | refill thread must be scoped; burst = capacity |
| TVar-backed cache (single-flight) | `TVar (Map k (TMVar (Either SomeException v)))`: first caller computes, others `readTMVar` | the owner must fill the slot even on async exceptions (`mask` + `try` + rethrow) |

Measured with the reference code (`-N4`): pool summed 1..1000 = 500500 with 4 workers and a
16-slot queue; 10 concurrent cache lookups ran the computation once; 12 permits from a 5-token
bucket refilled every 10 ms took 0.082 s (5 immediate plus 7 refills).

## 8. Debugging

- **Name threads**: `labelThread tid "crawler-3"` (`GHC.Conc`). Labels show in eventlogs and in
  `listThreads` (`GHC.Conc`, 9.6+) with `threadLabel` (`GHC.Conc.Sync`) and `threadStatus`.
- **Thread dump on demand**: install a `SIGUSR1` handler that prints every thread's label and
  status (`ThreadBlocked BlockedOnMVar`, `BlockedOnSTM`, `BlockedOnForeignCall`, ...); see
  the reference.
- **Eventlog + ThreadScope**: since GHC 9.4 every RTS flavour supports the eventlog (the
  `-eventlog` link flag is deprecated; checked without it on 9.10.3):

```bash
cabal build exe:crawler --ghc-options="-threaded -rtsopts"
$(cabal list-bin crawler) +RTS -N4 -l -olcrawl.eventlog -RTS    # -ol<file>: no space
threadscope crawl.eventlog          # per-capability activity, GC, thread labels
ghc-events show crawl.eventlog | head -50                         # text view
```

  Add `traceMarkerIO "batch 3 start"` / `traceEventIO` (`Debug.Trace`) to correlate phases.
- **Deadlock diagnosis**: (1) reproduce with labels on; (2) dump threads; (3) classify: two
  threads `BlockedOnMVar` holding each other's lock means lock ordering; workers `BlockedOnSTM` on
  an empty queue with no producer alive means a missing termination signal; `BlockedOnForeignCall`
  means a C call that never returns; (4) fix ownership, not timing. Adding `threadDelay` hides
  the problem.
- Uncaught-exception origin: profiling build + `+RTS -xc` prints the cost-centre stack; on 9.10+
  the `HasCallStack` backtrace in the exception context shows the `throwIO` site.

## 9. Testing

- **dejafu** explores schedules systematically (preemption bound 2 by default) over code written
  against `MonadConc` from the `concurrency` package (`Control.Concurrent.Classy` mirrors
  `Control.Concurrent`, `MVar`, `IORef`, STM). `autocheck` checks determinism, deadlocks and
  uncaught exceptions; `tasty-dejafu` provides `testAuto` / `testDejafu`. Any `liftIO` inside must
  be deterministic; otherwise use `randomly`/`uniformly` ways. Example in the reference.
- **Stress tests**: inject jitter at interleaving points through a test hook (`randomRIO (0, 200)
  >>= threadDelay`), run hundreds of iterations at `+RTS -N4`, compile with `-threaded
  -fno-omit-yields`, assert invariants and that `listThreads` shows no leaked labelled threads.
- Test-suite stanza: `ghc-options: -threaded -rtsopts -with-rtsopts=-N`.

## 10. Worked example: bounded crawler

Requirements: bounded memory (a `TBQueue`), N workers via `mapConcurrently_`, a per-request
timeout, failures recorded rather than fatal, termination when the frontier is empty and no
worker is busy, and clean cancellation (no thread outlives `crawl`). Compiled with `-threaded
-O1` on GHC 9.10.3.

```haskell
module Crawler (Url, CrawlConfig (..), CrawlResult (..), crawl) where
import Control.Concurrent (myThreadId)
import Control.Concurrent.Async (mapConcurrently_)
import Control.Concurrent.STM
import Control.Exception (SomeException (..), displayException)
import qualified Data.Set as Set
import GHC.Conc (labelThread)
import Numeric.Natural (Natural)
import System.Timeout (timeout)
import UnliftIO.Exception (tryAny)                 -- sync exceptions only

type Url = String
data CrawlConfig = CrawlConfig
  { workers :: !Int, queueBound :: !Natural, maxPages :: !Int, reqTimeout :: !Int }  -- µs
data CrawlResult = CrawlResult
  { fetched :: ![(Url, Int)], failed :: ![(Url, String)], dropped :: !Int } deriving stock Show
data St = St
  { queue :: TBQueue Url, seen :: TVar (Set.Set Url), budget :: TVar Int
  , inFlight :: TVar Int                              -- dequeued but not finished
  , okV :: TVar [(Url, Int)], errV :: TVar [(Url, String)], dropV :: TVar Int }

crawl :: CrawlConfig -> (Url -> IO [Url]) -> [Url] -> IO CrawlResult
crawl cfg fetchLinks seeds = do
  st <- St <$> newTBQueueIO (queueBound cfg) <*> newTVarIO Set.empty <*> newTVarIO (maxPages cfg)
           <*> newTVarIO 0 <*> newTVarIO [] <*> newTVarIO [] <*> newTVarIO 0
  atomically (mapM_ (enqueue st) seeds)
  mapConcurrently_ (worker st) [1 .. workers cfg]     -- one failure cancels all workers
  CrawlResult <$> readTVarIO (okV st) <*> readTVarIO (errV st) <*> readTVarIO (dropV st)
  where
    worker st i = do
      myThreadId >>= \t -> labelThread t ("crawler-" <> show i)
      let loop = do
            next <- atomically $
                  (Just <$> readTBQueue (queue st) <* modifyTVar' (inFlight st) (+ 1))
              `orElse` (readTVar (inFlight st) >>= check . (== 0) >> pure Nothing)
            case next of
              Nothing  -> pure ()                     -- empty frontier, nobody busy: done
              Just url -> do
                r <- timeout (reqTimeout cfg) (tryAny (fetchLinks url))
                atomically $ do                       -- record + enqueue + decrement: one step
                  case r of
                    Nothing                       -> modifyTVar' (errV st) ((url, "timeout") :)
                    Just (Left (SomeException e)) -> modifyTVar' (errV st) ((url, displayException e) :)
                    Just (Right ls) -> do
                      modifyTVar' (okV st) ((url, length ls) :)
                      mapM_ (enqueue st) ls
                  modifyTVar' (inFlight st) (subtract 1)
                loop
      loop

enqueue :: St -> Url -> STM ()                        -- never blocks a worker on its own queue
enqueue st url = do
  s <- readTVar (seen st); b <- readTVar (budget st); full <- isFullTBQueue (queue st)
  if Set.member url s || b <= 0 then pure ()
  else if full then modifyTVar' (dropV st) (+ 1)
  else do writeTVar (seen st) (Set.insert url s); writeTVar (budget st) (b - 1); writeTBQueue (queue st) url
```

Why it is correct: the decrement of `inFlight` and the enqueue of children happen in one
transaction, so no worker can see "queue empty and `inFlight == 0`" while links are pending. The
exit branch `check (n == 0)` retries, so idle workers sleep until the queue or the counter
changes. `enqueue` drops links when the queue is full instead of blocking (all workers blocked
on a full queue they drain would deadlock). `SomeException e` unwraps the error so the 9.10
context and backtrace lines stay out of the one-line message.

Run against a fake site (`/n` links to `/2n` and `/2n+1`, 20 ms per fetch, `/13` hangs, `/21`
throws) with `workers = 8, queueBound = 64, maxPages = 200, reqTimeout = 500000`:

```text
$ ./crawler +RTS -N4
fetched=198 failed=[("/13","timeout"),("/21","user error (HTTP 500)")] dropped=56 wall=0.655s
deadline hit=True live crawler threads after cancel=0
```

`fetched + failed = 200 = maxPages` on every run; `dropped` depends on scheduling (56 and 58 seen
in two runs), so assert on bounds and invariants, not exact counts.

The second line is `timeout 100000 (crawl cfg { maxPages = 10000 } fakeFetch ["/1"])`: the global
deadline cancels `mapConcurrently_`, which waits for every worker to die, and a `listThreads` scan
for `crawler-*` labels finds none alive. Production fetch with http-client:

```haskell
httpFetch :: Manager -> Url -> IO [Url]                 -- Manager from newTlsManager, shared
httpFetch mgr url = do
  req  <- parseRequest url
  body <- responseBody <$> httpLbs req mgr
  pure (extractLinks body)                              -- your HTML parser (tagsoup, html-conduit)
```

Keep `timeout` as the end-to-end bound (DNS, connect, body), add a per-host limiter (section 7)
before going wide, and size `workers` by the remote limits, not by core count.

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| thread silently dies | exception in a `forkIO` thread | `async` + `wait`/`link`, or `withAsync` |
| timeouts never fire / `cancel` hangs | `SomeException` catch, unsafe FFI call, non-allocating loop | `catchAny`; safe FFI; `-fno-omit-yields` |
| "thread blocked indefinitely in an MVar operation" | nobody can fill the var (lost `putMVar`, lock order) | `modifyMVar_`/`withMVar`, single lock order, STM |
| "thread blocked indefinitely in an STM transaction" | `retry` on state no live thread will change (e.g. writing a full `TBQueue` nobody reads) | redesign ownership; termination signals; `registerDelay` timeouts |
| "registerDelay: requires -threaded" | non-threaded RTS | link with `-threaded` |
| program uses one core | missing `-threaded` or `+RTS -N` | add both (`-with-rtsopts=-N`) |
| memory grows under load | unbounded `TQueue`/`Chan`, `mapConcurrently` over huge input | `TBQueue`, `pooledMapConcurrentlyN` |
| throughput collapses with more cores | hot `TVar` contention, transaction retries | shard state, shorten transactions |
| all threads freeze during GC | long `unsafe` FFI call | make the import `safe` |
| sporadic wrong totals | read-modify-write across two `atomically` blocks or `IORef` without atomics | one transaction / `atomicModifyIORef'` |
| `ExceptionInLinkedThread` at odd places | `link`ed child failed | handle in the parent or switch to `withAsync` + `wait` |

Review checklist: concurrency via `async`/`ki`/STM; every child joined; queues and parallelism
bounded; transactions short and IO-free; async-safe catching; `-threaded` set.

Related: `haskell-effects`, `haskell-performance-space-leaks`, `haskell-testing-properties`,
`haskell-type-level`, `haskell-cabal-builds`, hub `haskell-craft`.
