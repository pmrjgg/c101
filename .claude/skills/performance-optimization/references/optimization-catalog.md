# Optimization catalog

Patterns by rung of the optimization ladder. Each entry: symptom in a profile, change, and the trap.

## Rung 1: do less work

| Symptom | Change | Trap |
|---|---|---|
| Membership test in a loop over a list (`x in list`, `contains` on Vec) | Hash set / sorted array + binary search / bitset for dense ints | Hashing cost on tiny collections (< ~16 items a linear scan can win) |
| Pairwise comparison O(n^2) | Sort + sweep, hashing by key, spatial index (grid, k-d tree, BVH) | Correctness of tie handling after sorting |
| Repeated computation with same inputs | Memoize with bounded LRU; precompute tables | Unbounded caches = memory leak; cache key missing an input |
| Recomputing aggregates on every update | Incremental maintenance (running sums, Fenwick tree, dirty flags) | Drift in floating-point running sums; recompute periodically |
| N+1 queries | Batch fetch (`WHERE id IN (...)`, joins, DataLoader pattern) | Huge IN lists; chunk them (e.g. 1,000 per query) |
| Filtering in application after fetching everything | Push predicates and projections into the query; add index | Index write amplification on hot tables |
| Full re-serialization of large objects on each change | Partial updates, patches, append-only logs | Complexity of merge logic |
| Expensive work for results nobody reads | Lazy evaluation, pagination, early exit (`any`, `take`) | Lazy chains that recompute on each access |
| Regex or parser compiled per call | Compile once (module-level, `OnceLock`/`LazyLock`, `sync.Once`, static `Pattern`) | Thread safety of shared compiled objects (usually fine) |

## Rung 2: data layout and memory

- **Contiguity**: `Vec<T>`/arrays of values beat linked lists and `Vec<Box<T>>`; pointer chasing costs a
  cache miss per hop (~100 ns).
- **Struct of arrays** for hot loops touching one or two fields of many records (positions only, not
  names). Array of structs when most fields of each record are used together.
- **Smaller types**: `u32` indices instead of pointers/`usize` (halves memory for graph structures),
  `f32` where precision allows, enums instead of strings, bit-packing flags.
- **Preallocate**: `Vec::with_capacity`, `make([]T, 0, n)`, `ArrayList(n)`, `list` comprehension instead
  of repeated append in tight Python loops, `StringBuilder` with capacity.
- **Reuse buffers**: clear and refill instead of allocating per iteration; `sync.Pool` for short-lived
  objects in Go (measure: pools can hurt); object pools in JVM only for genuinely expensive objects.
- **Arenas / bump allocation** for many objects with a shared lifetime (per request, per parse);
  `bumpalo` (Rust), `std::pmr::monotonic_buffer_resource` (C++), region-style allocation in Go via
  slabs of structs.
- **Avoid copies**: borrow/slice instead of clone (`&str`, `&[T]`, `string_view`, `span`), move semantics,
  `bytes.Buffer` reuse, zero-copy parsing that keeps references into the input.
- **Interning** repeated strings (symbols, keys) to compare by id.
- **Boxing**: JVM `List<Integer>` vs primitive arrays or specialized collections; Python lists of floats vs
  NumPy arrays (vectorize the loop instead of iterating in Python).
- **Access order**: iterate row-major for row-major arrays; tile/block loops for matrix ops so the working
  set fits in L1/L2 (32-64 KiB L1d, 1-2 MiB L2 per core on typical 2026 hardware; check the target).
- **False sharing**: per-thread counters in adjacent memory bounce cache lines; pad to 64 bytes (128 on
  Apple silicon and some server parts) or use per-thread shards merged at the end.

## Rung 3: I/O and system

- Buffered I/O (`BufReader`/`BufWriter`, `bufio`, `BufferedOutputStream`); avoid flushing per line.
- Batch writes to databases (multi-row inserts, `COPY` in PostgreSQL), batch network calls, pipelining
  (Redis pipelines, HTTP/2 multiplexing).
- Connection pools sized with Little's law; timeouts and limits so a slow dependency does not exhaust them.
- Overlap independent waits: `asyncio.gather`, `errgroup`, `CompletableFuture.allOf`, `tokio::join!`, with
  a concurrency bound (semaphore) to protect downstreams.
- Avoid sync I/O on async runtimes; offload CPU-heavy work from event loops (worker threads,
  `spawn_blocking`, process pools).
- Compression: trade CPU for bandwidth deliberately (zstd low levels are fast; gzip -9 rarely pays).
- Serialization: binary formats (protobuf, flatbuffers, bincode, MessagePack) or faster JSON libraries
  (simdjson, orjson, sonic) when profiles show parse/format dominance.
- Startup: lazy imports/initialization, avoid reflection-heavy scanning, AppCDS/CRaC/native-image (JVM)
  where startup matters.

## Rung 4: parallelism

- First compute the ceiling: Amdahl with the measured serial fraction; memory-bandwidth-bound loops
  stop scaling at a few cores.
- Data parallelism with work stealing: rayon `par_iter`, Java parallel streams (on a dedicated
  ForkJoinPool for blocking work), Go worker pools reading from a channel, Python `ProcessPoolExecutor`
  for CPU-bound work (GIL; free-threaded CPython 3.13+ builds change this but extension support varies).
- Chunk size: large enough to amortize scheduling (>= ~10-100 us of work per task), small enough to
  balance load.
- Avoid shared mutable state: shard, reduce at the end (map-reduce), thread-local accumulators.
- Lock granularity: shard locks (striping), read-write locks only when reads dominate heavily and
  critical sections are long; lock-free structures only with a proven need and expert review.
- SIMD: let the compiler auto-vectorize first (simple loops, no aliasing, `-O3`, check with compiler
  reports `-Rpass=loop-vectorize` or `cargo asm`), then portable SIMD libraries (`std::simd` nightly,
  `wide`, Highway, xsimd) before intrinsics.
- GPU offload only when data transfer cost is amortized (large, arithmetic-heavy batches).

## Rung 5: micro-optimizations

- Branch prediction: sort data before branchy processing, replace unpredictable branches with
  arithmetic/conditional moves, move rare cases out of the hot loop.
- Bounds-check elimination: iterate with iterators/slices, assert lengths once before the loop
  (`assert!(i < v.len())` hoisting in Rust), use `get_unchecked` only with a SAFETY argument.
- Inlining: mark small hot cross-crate/module functions inlinable (`#[inline]`), avoid megamorphic
  virtual calls in hot loops (JVM inline caches, devirtualization).
- Faster hashers for non-adversarial keys (FxHash, ahash, xxHash); keep SipHash/randomized hashing where
  keys are attacker-controlled (HashDoS).
- Compiler: LTO (`lto = "thin"`), `codegen-units = 1`, PGO (Go `default.pgo`, clang/rustc PGO, JVM
  tiered compilation is already profile-guided), `-march=native` only when the deployment CPU equals
  the build CPU.
- Integer division by constants, `pow` with small integer exponents, `sqrt` in comparisons (compare
  squared distances): compilers handle many of these; verify in assembly before hand-tuning.

## Memory reduction checklist

- [ ] Measure peak RSS and allocation volume separately (`/usr/bin/time`, allocation profiler).
- [ ] Stream instead of loading whole inputs (iterators, generators, chunked reads, cursors).
- [ ] Release references early (large locals in long-lived scopes, caches holding request objects).
- [ ] Choose compact representations (columnar arrays, compact maps, `__slots__` in Python classes).
- [ ] Check for leaks: growth across identical iterations, heap diffs between two snapshots.
- [ ] GC tuning only after allocation reduction: heap sizing (`GOMEMLIMIT`, `-Xmx`, G1/ZGC choice).
