# Debugging and testing concurrent Haskell

## 1. Thread dump on SIGUSR1

Compiled and run on GHC 9.10.3 (`-threaded`); `unix` ships with GHC.

```haskell
import Control.Monad (forM_, void)
import Data.Maybe (fromMaybe)
import GHC.Conc (listThreads, labelThread, threadStatus)
import GHC.Conc.Sync (threadLabel)
import System.IO (hPutStrLn, stderr)
import System.Posix.Signals (Handler (Catch), installHandler, sigUSR1)

dumpThreads :: IO ()
dumpThreads = do
  ts <- listThreads
  forM_ ts $ \t -> do
    l <- threadLabel t
    s <- threadStatus t
    hPutStrLn stderr (show t <> " " <> fromMaybe "<unlabelled>" l <> " " <> show s)

installDump :: IO ()
installDump = void (installHandler sigUSR1 (Catch dumpThreads) Nothing)   -- kill -USR1 <pid>
```

Sample output (one labelled waiter blocked on an `MVar`):

```text
ThreadId 5 waiter ThreadBlocked BlockedOnMVar
ThreadId 3 TimerManager ThreadBlocked BlockedOnForeignCall
ThreadId 2 IOManager on cap 0 ThreadBlocked BlockedOnForeignCall
ThreadId 1 <unlabelled> ThreadFinished
```

`ThreadStatus` is `ThreadRunning | ThreadFinished | ThreadBlocked BlockReason | ThreadDied`;
`BlockReason` is `BlockedOnMVar | BlockedOnBlackHole | BlockedOnException | BlockedOnSTM |
BlockedOnForeignCall | BlockedOnOther`. The RTS's own `TimerManager`/`IOManager` threads always
show `BlockedOnForeignCall`; ignore them. Windows has no `SIGUSR1`: expose the dump on an admin
HTTP endpoint instead.

## 2. Reading the dump

| Pattern | Diagnosis | Fix |
|---|---|---|
| two labelled threads `BlockedOnMVar`, each owning the other's lock | lock-order deadlock | one global acquisition order, or one STM transaction |
| all workers `BlockedOnSTM`, producer missing from the list | producer died or finished without a stop signal | `link`/`withAsync` the producer; send one stop signal per worker |
| producer `BlockedOnSTM`, workers alive but also `BlockedOnSTM` | workers blocked writing into the full queue they drain | non-blocking enqueue, or separate queues |
| a thread stuck `BlockedOnForeignCall` | C call that never returns | timeout at the C level; `interruptible` import |
| `BlockedOnBlackHole` for long | another thread is evaluating the same thunk (possibly a long or looping computation) | force shared values before sharing; check for `<<loop>>` |
| count of labelled threads grows over time | leaked children (bare `async`, `forkIO`) | `withAsync`, `ki` scopes |

## 3. Eventlog and ThreadScope

```bash
cabal build exe:app --ghc-options="-threaded -rtsopts"
$(cabal list-bin app) +RTS -N4 -l -olapp.eventlog -RTS     # -l: write eventlog; -ol<file>
threadscope app.eventlog                                   # timeline per capability, GC pauses
ghc-events show app.eventlog | grep -i -E 'label|marker' | head
```

- Label threads (`labelThread`) so timelines and dumps are readable.
- `traceMarkerIO "phase: fetch"` and `traceEventIO "batch 3 done"` (`Debug.Trace`) put markers on
  the timeline; they cost little when no eventlog is written.
- What to look for in ThreadScope: capabilities idle while work is queued (too few workers or a
  serial bottleneck), long GC bars (allocation-heavy workers: tune `-A`, see
  `haskell-performance-space-leaks`), one capability busy (missing `-N`, or `unsafe` FFI).
- The eventlog also feeds `eventlog2html` for heap profiles (`-hT` with `-l`).

## 4. dejafu: systematic schedule exploration

Write the code under test against `MonadConc` (`concurrency` package): `Control.Concurrent.Classy`
mirrors `Control.Concurrent`, `MVar`, `IORef` and STM, so production code instantiates `m ~ IO`
while tests run in dejafu's `ConcIO`.

```haskell
import Control.Concurrent.Classy
import Control.Monad (replicateM_)
import Test.DejaFu (autocheck)

racyCounter :: MonadConc m => m Int          -- two threads do read-then-write on one IORef
racyCounter = do
  ref  <- newIORef (0 :: Int)
  done <- newEmptyMVar
  replicateM_ 2 . fork $ do
    n <- readIORef ref
    writeIORef ref (n + 1)
    putMVar done ()
  replicateM_ 2 (takeMVar done)
  readIORef ref

main :: IO ()
main = () <$ autocheck racyCounter            -- reports the nondeterminism: results 1 and 2
-- fix: atomicModifyIORef' ref (\n -> (n + 1, ())) and autocheck passes
```

- `autocheck` tests for deadlocks, uncaught exceptions and nondeterministic results, printing
  a failing schedule trace (`S0`, `P1`, ... per thread step) for each distinct bad outcome.
- Custom predicates: `dejafu "name" deadlocksNever prog`, `dejafus [("no deadlock",
  deadlocksNever), ("same result", alwaysSame)] prog`; also `exceptionsNever`, `alwaysSameOn f`.
- Exploration ways (`Test.DejaFu.Settings`): `systematically bounds` (preemption bound 2 by
  default), `randomly gen n` and `uniformly gen n` for larger programs or nondeterministic IO.
  Memory models: `SequentialConsistency`, `TotalStoreOrder`, `PartialStoreOrder` (relaxed
  `IORef` behaviour).
- tasty: `testAuto "counter" racyCounter`, `testDejafu "no deadlock" deadlocksNever prog`
  (`tasty-dejafu`).
- Keep dejafu targets small (2-4 threads, short programs): the schedule space grows
  exponentially.

## 5. Stress harness with randomized delays

Compiled with `-threaded -fno-omit-yields` and run at `+RTS -N4` (20 iterations in 2.8 s).

```haskell
jitter :: IO ()
jitter = randomRIO (0, 200) >>= threadDelay            -- random package; microseconds

stressTransfers :: Int -> IO ()
stressTransfers iterations = replicateM_ iterations $ do
  a <- newTVarIO 1000
  b <- newTVarIO 1000
  replicateConcurrently_ 8 $ replicateM_ 50 $ do
    jitter >> transfer a b 3
    jitter >> transfer b a 3
  total <- (+) <$> readTVarIO a <*> readTVarIO b
  unless (total == 2000) $ fail ("money created or destroyed: " <> show total)
```

- Put the jitter behind a hook in the environment (`envJitter = pure ()` in production) so the
  real code paths get perturbed, not a copy.
- `-fno-omit-yields` makes tight loops preemptible, so timeouts and cancellation are exercised.
- Assert invariants and liveness (the run finishes within a deadline: wrap in `timeout`) and that
  no labelled threads survive (`listThreads` + `threadLabel` + `threadStatus`).

## 6. Driver used for the worked example (fake site, leak check)

```haskell
fakeFetch :: Url -> IO [Url]          -- /n links to /2n and /2n+1; /13 hangs; /21 throws
fakeFetch url = do
  let n = read (drop 1 url) :: Int
  case n of
    13 -> threadDelay maxBound >> pure []
    21 -> throwIO (userError "HTTP 500")
    _  -> threadDelay 20000 >> pure ['/' : show (2 * n), '/' : show (2 * n + 1)]

liveCrawlers :: IO Int                -- labelled crawler threads not yet finished
liveCrawlers = do
  ts <- listThreads
  let alive t = do
        l <- threadLabel t
        s <- threadStatus t
        pure ("crawler-" `isPrefixOf` fromMaybe "" l && s `notElem` [ThreadFinished, ThreadDied])
  length <$> filterM alive ts

main :: IO ()
main = do
  let cfg = CrawlConfig { workers = 8, queueBound = 64, maxPages = 200, reqTimeout = 500000 }
  r <- crawl cfg fakeFetch ["/1"]
  print (length (fetched r), failed r, dropped r)
  m <- timeout 100000 (crawl cfg { maxPages = 10000 } fakeFetch ["/1"])   -- global deadline
  n <- liveCrawlers
  print (null m, n)                   -- (True, 0): deadline hit, no thread leaked
```
