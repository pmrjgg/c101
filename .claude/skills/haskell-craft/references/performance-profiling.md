# Haskell performance, strictness and profiling

## 1. First measurement: `+RTS -s`

Build with `-rtsopts` (or bake defaults with `-with-rtsopts="-N -A64m"`), then:

```bash
cabal run exe:app -- input.txt +RTS -s -RTS
```

| Line | Meaning | Red flag |
|---|---|---|
| bytes allocated in the heap | total allocation | 10s of GB for modest input → boxing, lists, `String` |
| bytes copied during GC | live data copied by the copying collector | large relative to allocation → long-lived data in nursery churn |
| maximum residency | peak live heap | grows with input size when it should not → space leak |
| total memory in use | OS-level footprint (~2-3x residency with copying GC) | |
| GC time / MUT time, productivity | share of time in GC | productivity < 80% → allocation or residency problem |

## 2. Heap profiling ladder (cheapest first)

1. **By closure type, no profiling build**: `+RTS -hT -l -i0.1` → `app.eventlog`; render with
   `eventlog2html app.eventlog`. Shows *what kind* of closures dominate (e.g. `THUNK`, `:`, `Text`).
2. **Info-table profiling** (precise source locations, no profiling build): compile with
   `-finfo-table-map -fdistinct-constructor-tables`, run `+RTS -hi -l`, open with eventlog2html;
   each band links to the source line that allocated the closure.
3. **Cost-centre profiling** (profiling build, changes optimization):
   `cabal build --enable-profiling --ghc-options="-fprof-late"` then
   - `+RTS -p` time/alloc report (`app.prof`); `-pj` JSON for speedscope;
   - `+RTS -hc` heap by cost centre, `-hy` by type, `-hd` by closure description,
     `-hr` retainer (who keeps it alive), filters like `-hc -hyTHUNK`;
   - `+RTS -xc` prints the cost-centre stack on exceptions (finds the `head []` caller).
   `-fprof-late` inserts cost centres after optimization, so profiles reflect optimized code.
4. **ghc-debug** for interactive heap inspection of a live process (attach, query retainers).
5. **nothunks** in tests: derive `NoThunks` for long-lived state and assert
   `unsafeNoThunks state == Nothing` after each operation.

## 3. Reading Core

```bash
cabal build --ghc-options="-ddump-simpl -dsuppress-all -dsuppress-uniques -ddump-to-file"
# output under dist-newstyle/build/.../*.dump-simpl
```

Look for:

| In Core | Means | Action |
|---|---|---|
| `I# x` / `D# x` constructed inside a loop | boxing per iteration | strict accumulators, `UNPACK`, specialization |
| `$dNum`, `$dMonad...` arguments to a hot function | dictionary passing | `INLINABLE`/`SPECIALIZE`, monomorphic signature |
| `let x = ...` inside a loop body | a thunk allocated per iteration | bang pattern / `seq` |
| `$wfoo` (worker) with unboxed args `Int#` | worker/wrapper succeeded | good |
| calls to `GHC.Base.++` / list functions in a numeric loop | list fusion failed | use `vector`/`foldl'` over a range, or check `RULES` firing (`-ddump-rule-firings`) |

## 4. Strictness toolbox

| Tool | Semantics | Use |
|---|---|---|
| `!x` bang pattern | force to WHNF when the pattern is matched | accumulators, loop variables |
| `!Int` strict field | field forced when the constructor is built | long-lived records |
| `{-# UNPACK #-} !Double` | stored unboxed in the constructor | small numeric fields |
| `StrictData` (module) | all fields strict unless `~` | domain modules |
| `Strict` (module) | all bindings strict | numeric kernels only; changes semantics broadly |
| `seq a b`, `f $! x` | WHNF | one-off forcing |
| `deepseq`, `force`, `evaluate (force x)` | full normal form (`NFData`) | before timing, before passing to another thread, at cache insertion |
| `Data.Map.Strict`, `Data.IntMap.Strict`, `Data.HashMap.Strict` | values forced to WHNF on insert | default choice |

WHNF trap: `Map.Strict` forces the value to WHNF only; a `(Int, Int)` value stays a pair of
thunks. Use strict pair types (`data P = P !Int !Int`) for compound values.

## 5. Data structure selection

| Need | Use | Avoid |
|---|---|---|
| text | `Data.Text` (UTF-8 since text-2.0), `Data.Text.Lazy` for streams | `String` |
| bytes, binary I/O | `Data.ByteString`, `Data.ByteString.Builder` for output | `[Word8]` |
| ordered map / set | `Data.Map.Strict`, `Data.Set` | association lists |
| `Int` keys | `Data.IntMap.Strict` | `Map Int` |
| hashable keys, large maps | `Data.HashMap.Strict` (unordered-containers) | |
| arrays of numbers | `Data.Vector.Unboxed` / `Storable` | boxed `Vector Double`, lists |
| mutable arrays in loops | `Data.Vector.Unboxed.Mutable` in `ST`/`IO` | `IORef [a]` |
| sequence with both-end ops | `Data.Sequence` | `xs ++ [x]` |
| priority queue | `Data.Set` as PQ, or `psqueues` | sorting repeatedly |
| text building | `Data.Text.Lazy.Builder`, `text-builder-linear` | `<>` on strict `Text` in a loop |

## 6. Compiler flags

| Flag | Effect | Cost |
|---|---|---|
| `-O2` | more aggressive optimization (SpecConstr, liberate-case) | compile time |
| `-fspecialise-aggressively` | specialize across modules wherever unfoldings exist | compile time, code size |
| `-fexpose-all-unfoldings` | make every function inlinable/specializable downstream | interface size |
| `-fpolymorphic-specialisation` | off by default (regression concerns); opt in and test | correctness risk historically |
| `-flate-dmd-anal` | late demand analysis, more unboxing | small compile cost |
| `-funbox-strict-fields` | unpack all strict fields | may rebox when passed to polymorphic functions |
| `-fllvm` | LLVM backend | needs matching LLVM; helps tight numeric loops |
| `-threaded` | multi-core runtime | required for `-N`, safe FFI calls in parallel |

GHC 9.14 extended `SPECIALISE` pragmas to accept type applications and expression arguments; use
the older form when supporting earlier compilers.

## 7. RTS tuning

| RTS flag | Effect | Typical setting |
|---|---|---|
| `-N` / `-N8` | capabilities (cores) | `-N` (all) or match container CPU limit |
| `-A64m` | nursery size per capability | 16m-128m for allocation-heavy services; fewer minor GCs |
| `-n4m` | split nursery into chunks | with large `-A` and many cores |
| `-qn4` / `-qg` | number of parallel GC threads / disable parallel GC | parallel GC on many cores can hurt; try `-qn` = cores/2 |
| `-I0` | disable idle GC | servers with idle periods and big heaps |
| `--nonmoving-gc` (`-xn`) | concurrent mark for the old generation | large heaps with pause-time goals |
| `-M2g` | max heap size | fail fast instead of swapping |
| `-F1.5` | old-gen growth factor (default 2) | reduce footprint at more GC CPU |

Verify every change with `+RTS -s` and an end-to-end benchmark; RTS flags interact.

## 8. Benchmarking

tasty-bench (criterion-compatible API, fewer dependencies):

```haskell
import Test.Tasty.Bench
main :: IO ()
main = defaultMain
  [ bgroup "parse"
      [ bench "small"  $ nf parse smallInput     -- nf: force to normal form
      , bench "large"  $ nf parse largeInput
      , bench "lookup" $ whnf (Map.lookup k) m   -- whnf when the result's head is enough
      ]
  ]
```

```bash
cabal bench --benchmark-options='--csv baseline.csv'                 # base commit
cabal bench --benchmark-options='--baseline baseline.csv --fail-if-slower 10'
```

Force inputs before the benchmark (`env` or `evaluate (force input)`) so you do not time input
construction. Use `nf` for results that are lazy structures, otherwise you time almost nothing.

## 9. Worked example: diagnosing a leak from `+RTS -s`

Observation: `maximum residency 3.1 GB`, `productivity 41%` on a 500 MB input; expected
residency is the size of the final summary (a few MB).

1. `+RTS -hT -l` → eventlog2html shows `THUNK` bands growing linearly and `Map` nodes flat.
   Conclusion: thunks are retained, not map structure.
2. Info-table profile (`-hi`) points at `Stats.hs:41`, `modify (\s -> s { total = total s + x })`
   inside `State`.
3. Fix: strict field `total :: !Int` and `modify'`; the State monad is
   `Control.Monad.State.Strict`.
4. Re-run: residency 6 MB, productivity 96%, wall time 3.4x faster. Add a `nothunks` test for the
   state record so the regression cannot return silently.
