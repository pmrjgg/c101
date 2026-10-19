---
name: haskell-performance-space-leaks
description: "Making Haskell fast and memory-bounded: +RTS -s triage, space-leak patterns and the heap-profiling ladder, strictness tools, reading Core, SPECIALIZE/INLINABLE, unboxed data, RTS flags and constant-memory streaming. Load when Haskell code is slow, allocation-heavy or its memory keeps growing."
when_to_use: "A Haskell program's RSS or maximum residency grows with input size; +RTS -s shows low productivity or high GC time; heap exhaustion or OOM kills; a hot loop allocates gigabytes; profiling with -hT, -hi, -hr, -hb, eventlog2html or ghc-debug; reading -ddump-simpl Core for dictionaries and boxing; choosing INLINABLE, SPECIALIZE, -O2, -fllvm or RTS flags such as -A, -N and --nonmoving-gc; streaming a large file in constant memory."
---

# Haskell performance and space leaks

Laziness causes two families of problems: space leaks (thunks or retained data that grow with
the input) and excess allocation (boxed values, dictionary passing, intermediate lists). One
workflow handles both: measure with `+RTS -s`, locate with a profile, change one thing,
re-measure. Never add strictness or pragmas without a measurement that shows the problem.

Baseline: GHC 9.4-9.14 (late cost centres need 9.4+, info-table profiling 9.2+), cabal 3.10+.

## 1. Measure first

Link with `-rtsopts` (or bake flags in with `-with-rtsopts`); otherwise most `+RTS` options are
rejected.

```text
$ ./wc big.log +RTS -s                     (illustrative leaky run)
  6,212,345,112 bytes allocated in the heap
  3,104,224,560 bytes copied during GC
  2,401,778,032 bytes maximum residency (12 sample(s))
           5814 MiB total memory in use (0 MB lost due to fragmentation)
  GC      time   14.210s  ( 14.380s elapsed)
  Productivity  22.4% of total user, 22.1% of total elapsed
```

| Metric | Healthy | Investigate |
|---|---|---|
| productivity | above 80-90% | below 70%: GC dominates (leak, or allocation area too small) |
| maximum residency | about the live data you expect | grows with input size: a leak (section 2) |
| bytes copied / bytes allocated | below 10% | above 30%: long-lived data copied over and over |
| total memory in use | 2-3x maximum residency (copying GC) | far more: fragmentation or pinned memory |
| allocation in a hot loop | near zero per iteration | GB/s: boxing, dictionaries, lists (sections 7-8) |

Benchmarks with tasty-bench (criterion-compatible API, fewer dependencies):

```haskell
import Test.Tasty.Bench
main :: IO ()
main = defaultMain
  [ env (BS.readFile "bench/sample.log") $ \input -> bgroup "wordcount"
      [ bench "baseline" $ nf countWordsOld input
      , bcompare "$NF == \"baseline\" && $(NF-1) == \"wordcount\""
          $ bench "strict" $ nf countWordsNew input ] ]
```

```bash
cabal bench --benchmark-options='+RTS -T -RTS --csv base.csv'     # -T adds allocation columns
cabal bench --benchmark-options='+RTS -T -RTS --baseline base.csv --fail-if-slower 10'
```

Change one thing per run, keep CSV baselines in the PR, use `nf` unless WHNF is the real
contract, and pass inputs through `env` so GHC cannot constant-fold them away. criterion
(`defaultMain [bench "x" (nf f x)]`, `--output report.html`) works the same way.

## 2. Mental model and leak patterns

- WHNF: evaluated to the outermost constructor (`seq`, bang patterns, strict fields). NF: fully
  evaluated (`deepseq`, `force`).
- A thunk is a heap object holding an unevaluated expression and everything it references; a
  chain of N thunks holds N objects and can keep alive the input that built them.
- Sharing: a value referenced twice stays alive until its last reference is gone.

| Pattern | Why it leaks | Fix |
|---|---|---|
| `foldl (+) 0 xs` | builds an `(((0+1)+2)+...)` thunk chain | `foldl'` (in Prelude since base 4.20) |
| `modifyIORef r (+1)` in a loop | the IORef holds a growing thunk | `modifyIORef'`, `atomicModifyIORef'` |
| lazy record fields updated in a loop | each field keeps a thunk of the old value | bang fields or `StrictData` |
| lazy `Data.Map` with `insertWith (+) k 1` | values become thunk chains | `Data.Map.Strict` |
| lazy `State`/`Writer` accumulators | the state thunk grows each step | `Control.Monad.State.Strict` with `modify'`; avoid `Writer` |
| lazy IO (`readFile`, `getContents`) | contents and handles live as long as any reference | strict reads or streaming (section 10) |
| double traversal `sum xs / fromIntegral (length xs)` | the whole list stays alive between passes | one pass with a strict accumulator |
| slices kept as keys (`T.take`, `B.words`) | each slice pins its parent buffer | `T.copy`/`B.copy` before storing |
| `seq` on a tuple or `Maybe` | WHNF stops at the outer constructor | strict fields or `force` |

```haskell
mean :: [Double] -> Double                         -- one pass, constant space
mean xs = s / fromIntegral n
  where (s, n) = foldl' (\(!acc, !len) x -> (acc + x, len + 1 :: Int)) (0, 0) xs
```

## 3. Heap-profiling ladder

| Rung | Build | Run | Shows |
|---|---|---|---|
| 1 | normal, `-rtsopts` | `+RTS -s` | whether residency grows |
| 2 | normal | `+RTS -hT -i0.1 -l`, then `eventlog2html prog.eventlog` | which closure types (constructors, thunks) dominate |
| 3 | add `-finfo-table-map -fdistinct-constructor-tables` | `+RTS -hi -i0.1 -l` | the source location of each closure: the exact thunk |
| 4 | `cabal build --enable-profiling --profiling-detail=late` | `+RTS -hr`, `-hb`, `-hr -hbdrag,void`, `-hc`, `-hy` | retainers (`-hr`), lifetimes (`-hb`), cost centres, types |
| 5 | link `ghc-debug-stub`, wrap `main` in `withGhcDebug` | attach `ghc-debug-brick` | live retainer paths in a running process |

- Rungs 2-3 need no profiling build, so you measure the optimised program. Stop at the first
  rung that names the culprit.
- eventlog2html writes `prog.eventlog.html` with one band per closure type or source location.
- Biographical states: lag (created, not yet used), drag (used for the last time, still held),
  void (never used). Drag and void are waste: `-hr -hbdrag,void` names their retainers.
- ghc-debug suits long-running servers whose leak appears only after hours.

## 4. Strictness toolbox

| Tool | Scope | Use |
|---|---|---|
| bang patterns `go !acc (x:xs)` | one binding | loop accumulators |
| strict fields `!Int`, `{-# UNPACK #-} !Int` | one field | long-lived records, small numeric fields |
| `StrictData` | every field in the module | data-definition modules; opt out with `~` |
| `seq`, `$!` | WHNF at one point | before storing into an `IORef`, `MVar`, `TVar` |
| `deepseq`, `force`, `rnf` with `NFData` via `Generic` | whole structure | results crossing a boundary (cache, another thread) |
| `evaluate (force x)` | ordering in IO | force before timing or before releasing a resource |
| `Data.Map.Strict`, `foldl'`, `modifyIORef'`, `State.Strict` + `modify'` | library choice | the default for accumulators |

```haskell
{-# LANGUAGE StrictData, DerivingStrategies, DeriveAnyClass, DeriveGeneric #-}
data Stats = Stats { count :: {-# UNPACK #-} !Int, total :: {-# UNPACK #-} !Double }
  deriving stock (Show, Generic)
  deriving anyclass (NFData)
```

Strictness belongs in accumulators, long-lived state, container values and fields of long-lived
records. It hurts on streaming list spines, on values used only on some paths, and in
knot-tied definitions.

## 5. Data representation

| Instead of | Use | Why |
|---|---|---|
| `String` | `Text` (2.x is UTF-8) or `ByteString` for bytes | `String` costs ~24-40 bytes per character |
| `[Int]` for bulk data | `Data.Vector.Unboxed`, `Data.Vector.Storable`, `PrimArray` | 8 bytes per `Int` instead of ~40 |
| repeated `<>` on strict text | `Data.ByteString.Builder`, `Data.Text.Lazy.Builder` | linear-time output |
| `Map Int v` | `Data.IntMap.Strict` | faster and smaller |
| `Map Text v` on hot paths | `Data.HashMap.Strict` (unordered-containers) | hashing beats comparing long keys |
| a list as a queue (`xs ++ [x]`) | `Data.Sequence` | O(1) at both ends |
| lazy fields in long-lived records | strict, unpacked fields | no thunks, no pointer chasing |
| silent `Integer` defaulting | explicit types, keep `-Wtype-defaults` (part of `-Wall`) | `Integer` arithmetic allocates |

## 6. CPU profiling

```bash
cabal build --enable-profiling --profiling-detail=late          # else ghc-options: -fprof-late
cabal run --enable-profiling exe:app -- input +RTS -p -RTS       # writes app.prof
profiteur app.prof                                               # interactive HTML tree
ghc-prof-flamegraph app.prof                                     # SVG flame graph
cabal run --enable-profiling exe:app -- input +RTS -p -l -RTS && hs-speedscope app.eventlog
```

- Late cost centres are inserted after optimisation, so the profile matches the optimised
  program; `-fprof-auto` inserts them before and blocks inlining, distorting hot loops.
- Read the top table (`%time`, `%alloc`), then inherited costs in the tree; many `entries` with
  high `%alloc` point at boxing or dictionary passing (section 7).
- Dependencies are rebuilt with profiling (slow first build); keep `profiling: True` in
  `cabal.project.local` while iterating.

## 7. Reading Core

```haskell
{-# OPTIONS_GHC -ddump-simpl -dsuppress-all -dsuppress-uniques -ddump-to-file #-}
```

Build, `find dist-newstyle -name '*.dump-simpl'`, search for the function; workers appear as
`$wname`, specialisations as `$sname`.

| In Core | Meaning | Fix |
|---|---|---|
| `$dNum`, `$dFractional` or other dictionary arguments in a hot worker | unspecialised polymorphism | `INLINABLE`/`SPECIALIZE`, monomorphic signature |
| `I# x`/`D# x` built and unpacked every iteration | boxed accumulator | bang patterns, strict fields |
| `$wgo :: Int# -> Double# -> ...` | unboxed worker loop: the goal | none |
| `integerAdd`, `IS`/`IP` constructors | `Integer` defaulting | explicit `Int`/`Double` |
| `(:)` allocation, `build`/`foldr` left in a loop | missed fusion | fusing combinators, vector streams |
| `join j ... jump j` | join point: a jump, no allocation | none |
| `let x = ...` inside the loop body | a thunk allocated per iteration | force it or restructure |

`-ddump-stg-final` shows what is really allocated (`let` in STG is a heap allocation). Annotated
dumps for the second worked example: [core-before-after](references/core-before-after.md).

## 8. Specialisation and inlining

| Pragma or flag | Effect | Use |
|---|---|---|
| `{-# INLINABLE f #-}` | exposes the unfolding so other modules can specialise | exported polymorphic functions on hot paths |
| `{-# SPECIALIZE f :: [Double] -> Double #-}` | forces a monomorphic copy | known hot instantiations |
| `{-# INLINE f #-}` | inline at every call site | small wrappers, combinators that must fuse |
| `{-# NOINLINE f #-}` | never inline | `unsafePerformIO` globals; keeping RULES matchable |
| `-fspecialise-aggressively -fexpose-all-unfoldings` | whole-program specialisation | applications; compile time and binary size grow |
| `{-# RULES ... #-}` | rewrite rules, fusion | libraries; verify with `-ddump-rule-firings` |

mtl-style code (`(MonadState S m, MonadIO m) => m ()`) passes dictionaries on every bind unless
specialised: mark hot functions `INLINABLE` and specialise to the concrete stack, or run hot
loops in a concrete monad such as `ReaderT Env IO` (effect-system costs: `haskell-effects`).

## 9. GHC and RTS flags

| Flag | Use | Note |
|---|---|---|
| `-O2` | hot packages only (`optimization: 2` per package in cabal.project) | 1.5-3x compile time |
| `-fllvm` | tight numeric loops | needs a supported LLVM (`opt`, `llc`) on PATH |
| `-funbox-strict-fields` | unbox every strict field | can re-box when passed to polymorphic code |
| `+RTS -A64m` | larger allocation area per core: fewer minor GCs | memory grows by cores × 64 MB |
| `+RTS -N`, `-qn4` | use all cores; cap parallel GC threads | `-qn` helps on many-core machines |
| `+RTS --nonmoving-gc` | concurrent old-generation GC, shorter pauses on large heaps | lower throughput, more fragmentation |
| `+RTS -I0` | no idle GC | servers with idle-time CPU spikes |
| `+RTS -M2g` | heap limit: fail fast instead of swapping | tests, containers |
| `-with-rtsopts="-N -A64m"` | bake defaults into the executable | link-time `ghc-options` |

Parallel `Strategies`: `+RTS -s` prints a `SPARKS:` line (converted, overflowed, dud, GC'd,
fizzled). Mostly GC'd or fizzled sparks mean wasted parallelism: use coarser chunks
(`parListChunk`). ThreadScope reads `+RTS -l` eventlogs for per-core activity.

## 10. Constant-memory streaming

```haskell
import Conduit

countLines :: FilePath -> IO Int
countLines path = runConduitRes $ sourceFile path .| linesUnboundedAsciiC .| lengthC

copyTransformed :: FilePath -> FilePath -> IO ()
copyTransformed src dst = runConduitRes $ sourceFile src .| mapC transformChunk .| sinkFile dst
```

- `runConduitRes` (ResourceT) closes files even on exceptions; in hand-written IO use
  `withFile`/`bracket` and never return lazily read data from inside them ("delayed read on
  closed handle").
- streamly offers the same through folds (`Streamly.Data.Stream`, `Streamly.Data.Fold`); its
  file modules moved between releases, so follow the installed version's docs.
- Chunks of 32 KiB to 1 MiB (`B.hGetSome h 65536`) balance syscall overhead and cache use.
- Never lazy IO for large inputs: memory and handle lifetimes depend on consumption order.
- Constant memory means bounded by the accumulator: rerun on a 10x larger input and check that
  `+RTS -s` maximum residency does not grow.

## 11. Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| strictness added without a profile | no gain, or divergence on infinite structures | sections 1 and 3 first |
| WHNF not deep enough | leak survives `seq` on a tuple or record | strict fields, `force` |
| INLINE everywhere | code size and compile time explode, no speedup | only where Core shows a need |
| `-O2` on every package | build time multiplies | `optimization: 2` for hot packages only |
| benchmark constant-folded away | nanosecond timings | inputs through `env`, `nf` |
| `+RTS` flags rejected | "Most RTS options are disabled" | link with `-rtsopts` |
| profiled build taken as truth | distorted hot paths | `-fprof-late`; confirm with a non-profiled `+RTS -s` |
| timing in GHCi | interpreted code | compiled, optimised builds only |
| `Text`/`ByteString` slices kept in maps | residency far above the data size | `copy` before storing |

## 12. Worked examples

### 12.1 Word count over a 2 GB log: ~6 GB RSS down to residency bounded by distinct words

```haskell
main :: IO ()                                       -- before
main = do
  [path] <- getArgs
  s <- readFile path                                -- lazy String IO
  print (M.size (foldl (\m w -> M.insertWith (+) w (1 :: Int) m) M.empty (words s)))
```

1. `+RTS -s` looks like the section 1 sample: residency in gigabytes, productivity near 20%,
   and residency grows with file size, so this is a leak, not a large working set.
2. `+RTS -hT -i0.1 -l` with eventlog2html: bands of `:` cells and `C#` characters (the
   `String`) plus thunks (the `foldl` chain and the lazy `(+)` values in the Map).
3. Remove all three causes:

```haskell
import qualified Data.ByteString.Char8 as B
import qualified Data.HashMap.Strict as HM
import Conduit

main :: IO ()                                       -- after
main = do
  [path] <- getArgs
  counts <- runConduitRes $
    sourceFile path .| linesUnboundedAsciiC .| foldlC (\m l -> foldl' bump m (B.words l)) HM.empty
  print (HM.size counts)
  where
    bump m w
      | HM.member w m = HM.adjust (+ 1) w m                   -- keeps the existing copied key
      | otherwise     = HM.insert (B.copy w) (1 :: Int) m     -- a slice would pin its whole chunk
```

4. Expected after-state (record your measured numbers in the PR): maximum residency
   proportional to the number of distinct words (tens of MB for typical logs), productivity
   above 90%, a flat `-hT` profile of `HashMap` nodes and `ARR_WORDS` (the copied keys), and
   unchanged residency on a 4x larger file.

### 12.2 Numeric loop: dictionary passing and boxed accumulators

```haskell
module Stats (meanVar) where

meanVar :: Fractional a => Int -> (Int -> a) -> (a, a)
meanVar n f = go 0 0 0
  where
    go i s ss
      | i == n    = let m = s / fromIntegral n in (m, ss / fromIntegral n - m * m)
      | otherwise = let x = f i in go (i + 1) (s + x) (ss + x * x)
```

Used at `Double` from another module, the loop receives the `Fractional` dictionary on every
iteration and builds `s`/`ss` thunk chains (strictness analysis cannot see through an unknown
`+`). Core shows the dictionary argument and boxed values in the worker. Fix:

```haskell
{-# INLINABLE meanVar #-}
{-# SPECIALIZE meanVar :: Int -> (Int -> Double) -> (Double, Double) #-}
    go !i !s !ss                                    -- was: go i s ss (needs BangPatterns, in GHC2021)
```

Confirm in Core that the specialised worker takes `Int#` and `Double#` arguments and no
dictionary ([core-before-after](references/core-before-after.md)). Then confirm with tasty-bench
under `+RTS -T`, benchmarking `nf (meanVar 10000000) (fromIntegral :: Int -> Double)` before and
after: the allocation column should drop from gigabytes to near zero and the time by roughly an
order of magnitude (expected shape; keep the measured CSV rows).

Related: `haskell-concurrency-stm`, `haskell-effects`, `haskell-testing-properties`, `haskell-cabal-builds`, hub `haskell-craft`
