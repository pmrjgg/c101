---
name: python-performance-profiling
description: "Speeding up Python with evidence: pyperf benchmarks, py-spy/Scalene/cProfile CPU profiles, memray and tracemalloc memory profiles, a symptom-to-fix table, NumPy/Polars vectorisation, Numba/Cython/mypyc/PyO3 kernels, free-threaded and multi-process parallelism. Load when Python code is slow or memory-hungry."
when_to_use: "A Python job, endpoint or test suite misses a latency, throughput, memory or startup target; pandas iterrows/apply in hot code; MemoryError or OOM kills; 'is this faster?' claims; choosing between Numba, Cython, mypyc, Rust or Polars; threads not scaling; slow imports or CLI startup."
---

# Python performance profiling

Baseline: CPython 3.13 and 3.14 (3.15.0 adds the stdlib sampling profiler). Tools checked: pyperf
2.10, py-spy 0.4.2, Scalene 2.3, memray 1.20, line_profiler 5.1, Numba 0.68, Cython 3.3, Polars 2.0,
pandas 3.0, DuckDB 1.5. Framing the target, statistics for speedup claims, the optimisation ladder
and the report template come from `performance-optimization`. This skill is the Python toolbox.

Deep material: [profiler commands](references/profiler-commands.md) |
[worked example scripts and raw numbers](references/worked-example.md)

## 1. Measure first

```bash
# micro: a function on a fixed input; pyperf spawns 20 worker processes x 3 values by default
python -m pyperf timeit -s "from app.score import score; from tests.data import EVENTS" \
    "score(EVENTS)" -o before.json
python -m pyperf timeit ... -o after.json                       # same command after the change
python -m pyperf compare_to before.json after.json --table --table-format md
# macro: a whole program, 5 fresh processes, 1 discarded warm-up run
python -m pyperf command -p 5 -n 1 -w 1 -l 1 -o after.json -- python job.py data.csv
python -m pyperf system tune     # Linux, root: fix CPU frequency, then `system reset` afterwards
```

```python
def test_score_speed(benchmark, events):           # pytest-benchmark, for regression gates in CI
    assert benchmark(score, events).total > 0
```

```bash
pytest --benchmark-only --benchmark-autosave                      # on main: store a baseline
pytest --benchmark-only --benchmark-compare --benchmark-compare-fail=median:10%
```

Rules: fixed inputs (seeded generator or a checked-in fixture file, never "today's data"); warm-up
excluded; at least 5 runs and report median and spread; same interpreter build, same machine,
nothing else running; check the output is identical before timing anything. Confidence intervals and
sample sizes: `performance-optimization`.

## 2. CPU profiling

| Tool | Overhead | Attach to PID | Best for | Command |
|---|---|---|---|---|
| py-spy | low (sampling, out of process) | yes | production processes, first look | `py-spy record -o flame.svg -- python job.py` / `--pid N` |
| `profiling.sampling` (3.15+, stdlib) | low | yes | same as py-spy, plus `--mode cpu/wall/gil` and asyncio task stacks | `python -m profiling.sampling run --flamegraph -o f.html job.py` |
| Scalene 2.x | low to moderate | no | per line: Python vs native vs system time, memory | `scalene run job.py; scalene view --cli -r` |
| cProfile + pstats/snakeviz | high on call-heavy code | no | exact call counts, call graph | `python -m cProfile -o out.prof -s cumtime job.py` |
| line_profiler | high, decorated functions only | no | which line inside a known-hot function | `kernprof -l -v job.py` |

- macOS: py-spy and `profiling.sampling` need `sudo`. `py-spy --native` (C, C++ and Rust
  frames) works only on Linux and Windows. Containers need `SYS_PTRACE` to attach.
- Read a flame graph by width (share of samples), not by order. Find the widest frames that are your
  code and ask why they are wide. Many calls? Python-level loops over data? Waiting?
- Wall far above CPU means the program waits: `py-spy record --idle` or `--mode wall` shows the
  waiting stacks (section 9).
- cProfile tripled the runtime of the pandas baseline in the worked example. Trust the shape of its
  profile, not its absolute times.

## 3. Memory

```python
import tracemalloc
tracemalloc.start(25)
base = tracemalloc.take_snapshot()
process_batch(batch)
for stat in tracemalloc.take_snapshot().compare_to(base, "lineno")[:10]:
    print(stat)          # app/cache.py:41: size=10171 KiB (+10171 KiB), count=10001 (+10001), ...
print(tracemalloc.get_traced_memory())            # (current, peak) bytes, Python allocator only
```

```bash
memray run -o run.bin job.py data.csv           # --native for C/Rust frames, --follow-fork for workers
memray stats run.bin                            # peak, totals, allocator mix
memray flamegraph run.bin                       # what is held at the peak
memray flamegraph --leaks run.bin               # not freed at exit (run with PYTHONMALLOC=malloc)
memray run --live job.py data.csv               # live TUI while it runs; `memray attach PID` for running ones
pytest --memray tests/perf                      # with @pytest.mark.limit_memory("200 MB") per test
```

- Peak or leak? Peak: use the flame graph at the peak, then stream or chunk the input. Leak: memory
  grows per request or batch. Take snapshots N batches apart, then `objgraph.show_growth()` and
  `objgraph.show_backrefs(...)` to find the owner (an unbounded cache, `lru_cache` on a method holding
  `self`, a registry of callbacks, stored tracebacks).
- Many small objects: `@dataclass(slots=True)` or `__slots__`. 1 M three-float instances measured
  with tracemalloc: 104 MB plain, 64 MB with slots (CPython 3.13). Interpreters before the 3.11/3.12
  inline-attribute work show a bigger gap. For millions of rows, use columns (NumPy, Arrow) instead of objects.
- memray counts bytes requested through malloc and mmap, while RSS counts resident pages. Native
  thread pools can make memray report far more than RSS: 4.9 GB versus 0.82 GB for the Polars
  version in the worked example. Compare like with like.

## 4. Symptom to fix

Timed with `timeit` (best of 5, CPython 3.13, Apple Silicon). The ratios matter, not the absolute
numbers.

| Profile shows | Fix | Measured |
|---|---|---|
| pandas `iterrows` / `apply(axis=1)` | column expressions; `itertuples` if a loop is unavoidable | 100k rows: iterrows 621 ms, apply 186 ms, itertuples 16 ms, vectorised 0.12 ms |
| Python loop over array elements | NumPy ufuncs and broadcasting (section 5) | sum of squares, 1 M floats: loop over the ndarray 53 ms (each element boxed), `(a*a).sum()` 0.25 ms, `np.dot(a, a)` 0.08 ms |
| `s += t` on an attribute or element; `bytes +=` | collect parts, then `"".join` / `b"".join` / `io.StringIO` | 100k parts: attribute `+=` 620 ms vs join 0.24 ms; local `str +=` 2.3 ms (CPython fast path for locals only); 20k `bytes +=` 36 ms vs 0.08 ms |
| `list.pop(0)` as a queue | `collections.deque.popleft()` | draining 100k: 634 ms vs 1.8 ms |
| `x in some_list` inside a loop | build a `set` or `dict` once | 10k probes into 10k items: 206 ms vs 0.13 ms |
| regex built per item | compile once at module level | 20k lines: `re.search(str)` 3.4 ms, compiled 1.5 ms, per-item pattern 173 ms (re's cache thrashes) |
| `copy.deepcopy` | copy what changes; immutable data | 2k nested rows: 3.7 ms vs orjson round-trip 0.4 ms |
| `json` at volume | orjson (`dumps` returns bytes) or msgspec (typed decode) | 10k docs: dumps 3.4 ms vs 0.49 ms; loads 3.2 ms vs 1.8 ms |
| exceptions on the common path | `dict.get`, membership tests | 1k misses: try/except 61 us vs get 19 us |
| global or attribute lookups in a hot loop | bind to a local (`append = out.append`) | small on 3.11+ (specialising interpreter); measure |
| same pure function recomputed | `functools.cache` / `lru_cache(maxsize=N)`, `cached_property` | unbounded caches are leaks |
| sorting to get the top k | `heapq.nsmallest(k, xs)`, `bisect` on sorted data | O(n log k) instead of O(n log n) |

## 5. Vectorise

- NumPy: broadcasting instead of loops; preallocate and write with `out=`; in-place ops (`a *= 2`)
  to avoid temporaries; the narrowest correct dtype (float32 halves memory traffic when precision
  allows, never object dtype); `np.einsum("ij,ij->i", a, b)` for contractions (`optimize=True` with
  3+ operands); C-contiguous data iterated along the last axis (`np.ascontiguousarray`);
  `np.bincount`, `np.add.at` and `np.searchsorted` for group-by-like work.
- pandas to Polars lazy for pipelines: the query optimiser pushes filters and column selection into
  the scan and runs the plan multi-threaded. `.explain()` shows the plan.

```python
daily = (pl.scan_parquet("events/*.parquet")                  # or scan_csv
           .filter(pl.col("amount") > 0)
           .group_by("customer_id", pl.col("ts").dt.date().alias("day"))
           .agg(total=pl.col("amount").sum(), n=pl.len())
           .collect(engine="streaming"))                       # bounded memory for big inputs
```

- DuckDB for SQL-shaped and out-of-core work:
  `duckdb.sql("SELECT customer_id, CAST(ts AS DATE) AS day, sum(amount) FROM read_csv('events.csv') GROUP BY ALL").pl()`
  ran in 0.19 s on 1 M rows. `SET memory_limit = '4GB'` makes it spill to disk instead of dying.
- Arrow is the interchange format: Polars, DuckDB, pyarrow and pandas (ArrowDtype) exchange columns
  without copying. Stream big Parquet files with `pq.ParquetFile(p).iter_batches(batch_size=100_000, columns=[...])`.

## 6. Compile the kernel

When the hot part is an inherently sequential loop (recurrences, state machines, custom scoring),
compile it instead of contorting it into array operations.

| Situation | Choose | Notes |
|---|---|---|
| numeric loops over NumPy arrays | Numba `@njit(cache=True)` | first call compiles (0.40 s here, 0.055 s when loaded from cache); NumPy subset only, no pandas or Polars objects inside |
| independent iterations | Numba `@njit(parallel=True)` + `prange` | the reduction variable must be loop-local or a supported reduction |
| typed Python module, ship wheels without a JIT | Cython 3 pure-Python mode | `cython -a mod.py` writes `mod.html`, where yellow lines still talk to Python; build with `cythonize -i mod.py` |
| fully annotated pure-Python code (parsers, business rules) | mypyc | `mypyc pkg/mod.py`; compiled classes cannot be monkeypatched |
| new kernel, threads, Rust crates | PyO3 + maturin | `maturin new -b pyo3 fastscore`, `maturin develop --release` (never time a debug build) |
| existing C++ library | nanobind (or pybind11) | release the GIL inside long calls |

```python
@njit(cache=True)
def velocity(cust, t, amt, tau, cap):          # time-decayed, capped score per customer
    out = np.empty(amt.size)
    s = 0.0
    for i in range(amt.size):
        if i == 0 or cust[i] != cust[i - 1]:
            s = 0.0
        else:
            s *= np.exp(-(t[i] - t[i - 1]) / tau)
        s = min(cap, s + amt[i])
        out[i] = s
    return out
```

Independent iterations parallelise with `prange`. Here each row's nearest neighbour, run with 5,000
points on 32 threads, took 0.8 ms, with a 0.40 s first compile and 0.055 s when loaded from cache:

```python
@njit(cache=True, parallel=True)
def nearest_gap(x):
    out = np.empty(x.shape[0])
    for i in prange(x.shape[0]):               # iterations are independent: safe to split
        best = np.inf
        for j in range(x.shape[0]):
            if i != j and abs(x[i] - x[j]) < best:
                best = abs(x[i] - x[j])
        out[i] = best
    return out

nearest_gap(x[:10])                            # compile (or load from cache) before timing
```

The Cython pure-Python version of the same kernel declares `cust: cython.long[:]`,
`t: cython.double[:]`, `i: cython.Py_ssize_t` and `s: cython.double`, with
`@cython.boundscheck(False)` and `@cython.wraparound(False)`, and stays importable as plain Python.

## 7. Parallelism

| Work | Use |
|---|---|
| I/O with blocking libraries | `ThreadPoolExecutor` |
| I/O with async libraries | asyncio with bounded concurrency (`python-asyncio`) |
| CPU-bound pure Python, GIL build | `ProcessPoolExecutor`, or `InterpreterPoolExecutor` (3.14+) |
| CPU-bound pure Python, free-threaded 3.14t | threads, if every extension module supports free threading |
| NumPy, Polars, DuckDB, Numba `nogil` kernels | threads or the library's own parallelism: they release the GIL |

Measured, 8 tasks of a 3 M-iteration pure-Python loop on 8 workers (Apple Silicon):

| Build | serial | threads | interpreters | processes |
|---|---|---|---|---|
| CPython 3.14 (GIL) | 0.60 s | 0.63 s | 0.15 s | 0.17 s |
| CPython 3.14t (free-threaded) | 0.54 s | 0.13 s | 0.47 s | 0.32 s |

- Processes: `pool.map(fn, items, chunksize=max(1, len(items) // (4 * workers)))` amortises IPC.
  Send paths, ids or shared-memory names rather than big objects, because arguments are pickled per
  task. Load read-only data once per worker with `initializer=`. Guard with
  `if __name__ == "__main__":`. Since 3.14 the default start method on Linux is `forkserver` (macOS
  and Windows use `spawn`), so workers do not inherit module state set up at runtime.
- `InterpreterPoolExecutor`: module-level functions with shareable arguments. Each interpreter
  imports its own modules, and extension modules without subinterpreter support fail to import there.
- Free-threaded: `uv python install 3.14t`, then check `sys._is_gil_enabled()`. Importing an
  extension not marked free-threading-safe turns the GIL back on and prints a warning. Single-thread
  code runs roughly 5 to 10% slower (Python 3.14 docs). Shared mutable state now needs real locks.

## 8. Interpreter and stdlib levers

- Upgrade first. 3.11's specialising adaptive interpreter averaged about 25% faster than 3.10, and
  later releases kept improving. Benchmark your workload on the newest supported version before
  rewriting code.
- Experimental JIT: `PYTHON_JIT=1` on builds that include it (3.14 macOS and Windows installers;
  check `sys._jit.is_available()`). It is off by default and gains depend on the workload, so
  measure with pyperf and keep it off unless it wins.
- Startup: `python -X importtime -c "import app.cli" 2> import.log`, then sort by the cumulative
  column. Move heavy imports (pandas, torch, boto3) into the functions that need them. Python 3.15
  adds explicit `lazy import pandas` (PEP 810) and `-X lazy_imports=all` / `PYTHON_LAZY_IMPORTS`.
- Algorithms beat micro-tuning: `set`/`dict` for membership, `bisect` for sorted lookups, `heapq`
  for top-k, `collections.Counter`, generators and `itertools` to stream instead of materialise.
- Linux `perf` sees Python frames with `python -X perf` (3.12+).

## 9. I/O

- Separate waiting from computing: `time.perf_counter()` (wall) vs `time.process_time()` (CPU), or
  `/usr/bin/time -v` (Linux) / `-l` (macOS). If CPU is much less than wall, profile the waits
  (`py-spy --idle`, `profiling.sampling --mode wall`), not the code.
- Files: iterate line by line or read fixed-size chunks; `open(p, "rb", buffering=1 << 20)` for big
  sequential reads; `mmap` for random access into large files. Convert CSV to Parquet once and read
  only the needed columns (`pq.read_table(p, columns=[...], filters=[...])`).
- Databases: batch writes (`executemany`, psycopg 3 `cursor.copy("COPY t (a, b) FROM STDIN")` with
  `copy.write_row(row)`, asyncpg `copy_records_to_table`), fetch with `fetchmany` or server-side
  cursors, never one round trip per row. Query plans: `sql-query-tuning`.
- HTTP: one pooled `httpx.Client`/`AsyncClient` with explicit `Limits` and timeouts, reused for the
  life of the process. Concurrency through asyncio plus a semaphore, not a thread per request.

## 10. Pitfalls

| Pitfall | Effect | Fix |
|---|---|---|
| profiling with coverage, a debugger or tracing enabled | trace hooks inflate call-heavy code unevenly | profile a plain run |
| cold caches and first-run effects (imports, disk cache, JIT) | the first run is slower and the comparison is wrong | warm-up runs, pyperf's process model |
| Numba compile time inside the timing | 0.40 s compile against a sub-millisecond kernel | call once before timing; `cache=True` |
| pandas copy-on-write differences | pandas 3 always uses CoW: `df[mask]["col"] = v` never writes back, and copies happen at different points than in 2.x | `df.loc[mask, "col"] = v`; benchmark on the pandas version you deploy |
| multiprocessing pickles large arguments per task | the IPC time exceeds the work | `initializer`, shared memory, pass paths |
| unstable sort ties after a rewrite | different but valid row order, false "results changed" | `sort(..., maintain_order=True)` or a tie-breaker column |
| memray peak taken as RSS (or the reverse) | wrong conclusion about memory | compare the same metric before and after |
| a micro-benchmark of the wrong thing (constants folded, setup inside the timed statement) | impossible speedups | time the real function on real-shaped data |

## 11. Worked example: 95 s CSV aggregation

The job: a nightly aggregation that reads an events CSV and computes per customer and day the
total, the count and the peak of a time-decayed, capped "velocity" score (a recurrence over each
customer's events in time order). Production run: 95 s, peak memory 6 GB.

1. **Profile.** `sudo py-spy record -o before.svg -- python before.py events.csv`. The flame graph is
   almost entirely `DataFrame.iterrows`, building one `Series` per row, plus `Series.__getitem__`.
   cProfile on a 200k-row sample agrees: iterrows 61% of cumulative time, `Series.__getitem__` 25%.
2. **Lock the output.** Before changing anything, save the baseline result and write an
   equivalence check: same groups, `np.allclose` on `total` and `max_score`.
3. **Polars lazy for the relational part.** `scan_csv` with `select("customer_id", "ts", "amount")`
   (projection pushdown skips the two text columns), a stable sort by customer and timestamp, then
   `group_by("customer_id", "day").agg(total=..., n=pl.len(), max_score=...)`. The job dropped from
   95 s to about 3 s.
4. **Numba for the recurrence.** The velocity score depends on the previous row, so it does not
   vectorise. It became the `velocity` kernel in section 6 over three NumPy columns (about 30 ms per
   4 M rows once compiled). `cache=True` keeps the compile out of nightly runs.
5. **Stream.** `collect(engine="streaming")` plus projection took peak memory from 6 GB to 900 MB
   (memray for the pandas baseline, max RSS cross-checked for Polars, because of the memray caveat
   in section 3).
6. **Report with pyperf.** A local reproduction on 1 M synthetic rows (5 columns, 53.6 MB), 5
   processes each:

| Benchmark | before | after |
|---|:---:|:---:|
| command (1 M rows) | 12.5 sec | 389 ms: 32.19x faster |

At 4 M rows the reproduction measured 51.6 s and 3.33 GB max RSS before, 0.54 s and 1.48 GB after.
Of the 0.54 s, 0.24 s is the pipeline (CSV parse 0.12 s, sort 0.06 s, kernel 0.03 s, group_by
0.03 s) and the rest is interpreter start-up and imports. The next levers are Parquet input and
`-X importtime`, not more kernel work. Scripts, commands and raw outputs:
[worked-example](references/worked-example.md).

Related: `pytest-patterns`, `fastapi-pydantic-services`, `python-asyncio`, `python-typing`, `python-uv-packaging`, `sql-query-tuning`, `performance-optimization`, `code-quality-metrics`, hub `coding-general`
