# Concurrency pattern implementations

Compiled with `-Wall -threaded -O1` on GHC 9.10.3 and run at `+RTS -N4`. Imports used across
the snippets:

```haskell
import Control.Concurrent (threadDelay)
import Control.Concurrent.Async (concurrently_, replicateConcurrently_, withAsync)
import Control.Concurrent.STM
import Control.Exception (SomeException, mask, throwIO, try)
import Control.Monad (forever, replicateM_, forM_, when)
import qualified Data.Map.Strict as Map
import Numeric.Natural (Natural)
```

## 1. Worker pool with backpressure

```haskell
runPool :: Int -> Natural -> (a -> IO ()) -> [a] -> IO ()
runPool n cap handle items = do
  q <- newTBQueueIO cap
  let producer = do
        mapM_ (atomically . writeTBQueue q . Just) items          -- blocks while the queue is full
        replicateM_ n (atomically (writeTBQueue q Nothing))      -- one stop signal per worker
      worker = atomically (readTBQueue q) >>= maybe (pure ()) (\x -> handle x >> worker)
  concurrently_ producer (replicateConcurrently_ n worker)
```

- `runPool 4 16 add [1..1000]` summed to 500500.
- A failing `handle` cancels the producer and the other workers (`concurrently_`); wrap `handle`
  in `tryAny` when per-item failures should be recorded instead.
- Size `cap` at about 2-4x `n`: enough to hide producer latency, small enough to bound memory.
- If workers also produce work (a crawler), they must never block on the full queue they drain:
  drop, spill to a side list, or use the frontier pattern of the worked example.

## 2. Token-bucket rate limiter

```haskell
withRateLimit :: Int -> Int -> (IO () -> IO a) -> IO a
withRateLimit cap periodMicros body = do
  tokens <- newTVarIO cap
  let refill = forever $ do
        threadDelay periodMicros
        atomically (modifyTVar' tokens (min cap . (+ 1)))
      acquire = atomically $ do
        t <- readTVar tokens
        check (t > 0)                                            -- sleep until a token exists
        writeTVar tokens (t - 1)
  withAsync refill (\_ -> body acquire)                          -- refill thread dies with the scope
```

12 acquisitions with `cap = 5`, `periodMicros = 10000` took 0.082 s: 5 immediate, then one per
refill. Per-host limiting: a `TVar (Map Host (TVar Int))`, or one bucket per host created on first
use. For distributed limits, use a central store (Redis) instead.

## 3. Single-flight TVar cache

Concurrent callers for the same key share one computation; failures are not cached.

```haskell
type Cache k v = TVar (Map.Map k (TMVar (Either SomeException v)))

getOrCompute :: Ord k => Cache k v -> k -> IO v -> IO v
getOrCompute cache k compute = mask $ \restore -> do
  (slot, owner) <- atomically $ do
    m <- readTVar cache
    case Map.lookup k m of
      Just s  -> pure (s, False)
      Nothing -> do
        s <- newEmptyTMVar
        writeTVar cache (Map.insert k s m)
        pure (s, True)
  if owner
    then do
      r <- try (restore compute)          -- catch-all is fine: recorded and rethrown below
      atomically $ do
        putTMVar slot r
        either (const (modifyTVar' cache (Map.delete k))) (const (pure ())) r
      either throwIO pure r
    else restore (atomically (readTMVar slot)) >>= either throwIO pure
```

- 10 concurrent `getOrCompute cache "k" slow` calls ran `slow` once.
- `mask` + `try` guarantees the slot is filled even if the owner is cancelled; otherwise waiters
  would block forever (or get `BlockedIndefinitelyOnSTM`).
- Add expiry by storing `(UTCTime, v)` and treating stale entries as missing; bound the size with
  an LRU (`psqueues`) if keys are unbounded.

## 4. Broadcast with dupTChan

```haskell
broadcastDemo :: IO ()
broadcastDemo = do
  bc <- newBroadcastTChanIO                         -- write-only: readTChan on it retries forever
  subs <- atomically (mapM (const (dupTChan bc)) [1 .. 3 :: Int])
  atomically (writeTChan bc "tick")
  forM_ subs $ \s -> atomically (readTChan s) >>= putStrLn      -- prints tick three times
```

- A subscriber sees only messages written after its `dupTChan`; subscribe before publishing.
- Each subscriber has an unbounded view: a slow one accumulates every message. For bounded
  fan-out, give each subscriber its own `TBQueue` and decide per publish whether to block, drop,
  or disconnect.

## 5. Bank transfer with retry (from the hub)

```haskell
withdraw :: TVar Int -> Int -> STM ()
withdraw acc n = do
  bal <- readTVar acc
  when (bal < n) retry                  -- block until another transaction changes acc
  writeTVar acc (bal - n)

transfer :: TVar Int -> TVar Int -> Int -> IO ()
transfer from to n = atomically $ withdraw from n >> modifyTVar' to (+ n)
```

Both accounts change in one transaction, so no observer sees money in flight. The stress harness
in [debugging-testing](debugging-testing.md) checks that the total is conserved.
