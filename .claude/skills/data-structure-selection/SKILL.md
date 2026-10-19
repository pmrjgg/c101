---
name: data-structure-selection
description: "Choosing data structures from the operation mix: dictionaries and ordered maps, priority queues, sequences, range-query structures, spatial and vector indexes, persistent structures and graph representations, with asymptotic costs, cache and allocation constants, concrete per-language library picks (2026), adversarial-key defences and a benchmark-to-confirm step. Load when picking, reviewing or replacing a container, index or in-memory structure."
when_to_use: "Choosing a map/set/heap/deque/tree for a hot path; a container showing up in a profile; 'which index for range, k-th, nearest-neighbour or top-k queries'; rank/leaderboard/sliding-window features; std::unordered_map, LinkedList or list.pop(0) in review; hash maps keyed by user input; embedding search sizing (HNSW, IVF-PQ)."
---

# Data structure selection

Pick by operation mix, then by constants, then by availability, then measure. The hub
`cs-foundations` section 5 has the short table; storage engines (LSM vs B+tree) stay there.
Graph algorithms are in `graph-algorithms`, sketches in `randomized-algorithms-sketches`.

## 1. Selection procedure

1. **List operations** with frequencies, data size, key type and distribution (uniform, Zipf,
   sequential, adversarial) and latency targets (mean vs p99).
2. **Derive required complexities**: e.g. 10^5 updates/s and 10^3 range queries/s over 10^7 keys
   rules out O(n) per query.
3. **Shortlist** 2-3 candidates from the tables below.
4. **Compare constants**: a cache miss costs ~100 ns (vs ~1 ns for an L1 hit); one allocation
   ~20-100 ns plus fragmentation; pointer-chasing structures pay a miss per node, so a B-tree
   with 16-64 keys per node beats a red-black tree at equal O(log n).
5. **Check availability**: a maintained library beats a hand-rolled structure unless profiling
   proves otherwise.
6. **Microbenchmark** on realistic sizes and distributions (section 11), then decide.

RUM conjecture: of **R**ead cost, **U**pdate cost and **M**emory overhead you can optimise two at
the expense of the third (B-tree: reads; LSM: updates; sorted array: memory and reads). Say which
two you chose.

## 2. Dictionaries and sets

| Structure | Insert | Lookup | Delete | Ordered ops | Notes |
|---|---|---|---|---|---|
| hash table, chaining | O(1) exp | O(1) exp | O(1) exp | no | pointer chasing, stable references |
| open addressing (linear, Robin Hood, Swiss) | O(1) exp | O(1) exp | O(1) exp (tombstones/backshift) | no | cache friendly; load <= ~0.875 (Swiss), ~0.7 (linear) |
| cuckoo hashing | O(1) amortised exp | O(1) worst | O(1) | no | worst-case lookups; rebuild on cycles |
| red-black / AVL tree | O(log n) | O(log n) | O(log n) | yes | AVL is stricter, faster lookups |
| B-tree (in memory) | O(log n) | O(log n) | O(log n) | yes, fast scans | best cache behaviour among ordered maps |
| skip list | O(log n) exp | O(log n) exp | O(log n) exp | yes | simple concurrent variants |
| treap / splay | O(log n) exp / amortised | same | same | yes | splay adapts to access skew |
| radix tree / ART | O(k) | O(k) | O(k) | lexicographic | k = key length; strings, integer keys |
| sorted array | O(n) | O(log n) | O(n) | yes | static data; Eytzinger (BFS) layout for cache-friendly search |
| van Emde Boas / y-fast trie | O(log log U) | O(log log U) | O(log log U) | predecessor | integer universe U, large constants |

## 3. Per-language picks (2026)

| Language | Unordered map | Ordered map | Notes |
|---|---|---|---|
| Rust | `HashMap` (hashbrown SwissTable, SipHash-1-3 by default) | `BTreeMap` | trusted keys: `foldhash` or `ahash` hasher; insertion order: `indexmap` |
| C++ | `absl::flat_hash_map`, `boost::unordered_flat_map` | `absl::btree_map`; C++23 `std::flat_map` for read-mostly | `std::unordered_map` is node-based (a miss per lookup): avoid on hot paths unless you need pointer stability |
| Java | `HashMap` (bucket treeified at 8 entries) | `TreeMap` | primitive keys: fastutil or Eclipse Collections maps (no boxing) |
| Go | built-in `map` (Swiss table since Go 1.24) | `google/btree`, `tidwall/btree` | no ordered map in the standard library |
| Python | `dict`, `set` | `sortedcontainers.SortedDict` / `SortedList` | `collections.deque`, `heapq`, `bisect` for the rest |
| Haskell | `Data.HashMap` (HAMT, unordered-containers) | `Data.Map` (size-balanced tree); `Data.IntMap` (Patricia trie) | `Data.Sequence` (finger tree) for sequences |
| Julia | `Dict` | `DataStructures.SortedDict` | DataStructures.jl also has heaps, `Deque`, `DisjointSets` |

## 4. Priority queues

| Structure | Insert | Delete-min | Decrease-key | Meld |
|---|---|---|---|---|
| binary heap | O(log n) | O(log n) | O(log n) with a position index | O(n) |
| d-ary heap (d = 4) | O(log_d n) | O(d log_d n) | O(log_d n) | O(n) |
| pairing heap | O(1) | O(log n) amortised | o(log n) amortised | O(1) |
| Fibonacci heap | O(1) | O(log n) amortised | O(1) amortised | O(1) |
| radix heap (monotone integer keys <= C) | O(1) amortised | O(log C) amortised | O(1) | - |

Advice: a binary or 4-ary heap with **lazy deletion** (push a new entry, skip stale ones on pop)
beats Fibonacci heaps for Dijkstra on real graphs. Use an indexed heap (heap plus position map)
only when the heap must stay small or entries must be updated in place; radix heaps for Dijkstra
with small integer weights; pairing heaps when melds dominate.

## 5. Sequences

| Need | Structure | Cost / notes |
|---|---|---|
| append, index | dynamic array, growth factor 1.5-2 | O(1) amortised push; libstdc++/libc++/Rust double, MSVC and folly use 1.5, CPython ~1.125 |
| both ends | ring-buffer deque | O(1) at both ends; `collections.deque`, `VecDeque`, `ArrayDeque` |
| edits in the middle of large text | rope, piece table (VS Code), gap buffer (Emacs) | O(log n) or O(1) near the cursor |
| persistent / immutable | RRB vector, finger tree, HAMT | O(log_32 n) with wide nodes |
| k-th element, rank of a value | order-statistic tree, Fenwick on ranks | O(log n); C++ `__gnu_pbds::tree` with `tree_order_statistics_node_update` |

## 6. Range queries

| Query | Updates | Structure | Cost |
|---|---|---|---|
| sum, xor (invertible) | point | Fenwick tree | O(log n), tiny constant |
| any monoid (min, max, gcd, matrix product) | point, or range with lazy propagation | segment tree | O(log n) |
| min/max/gcd (idempotent), static | none | sparse table | O(1) query, O(n log n) build |
| LCA | none | Euler tour + sparse table / binary lifting | O(1) / O(log n) |
| intervals containing a point or overlapping an interval | insert/delete | interval tree, or segment tree over coordinates | O(log n + k) |
| k-th smallest in a range | none | wavelet tree O(log sigma); persistent segment tree O(log n); merge-sort tree O(log^2 n) per count | |
| many offline queries | none | Mo's algorithm, sqrt decomposition | O((n + q) sqrt n) |
| 2-D rectangle sums, static | none | 2-D prefix sums | O(1) query |

## 7. Spatial and vector indexes

| Data | Structure | Notes |
|---|---|---|
| points, low dimension | k-d tree | effective up to ~10-20 dimensions; beyond that close to a linear scan |
| rectangles, geometries | R*-tree; PostGIS GiST index | bulk-load (STR) static data |
| 2-D points, adaptive density | quadtree | simple, good for games and tiling |
| ray tracing, collision | bounding volume hierarchy (BVH) | SAH-built trees |
| global cells and sharding | geohash, S2 (quad cells), H3 (hexagons) | cover regions with cell sets, join on cell ids |
| embeddings (ANN) | HNSW (hnswlib, FAISS, pgvector, usearch); IVF-PQ (FAISS) | trade recall, latency and memory |

ANN trade-off: HNSW keeps full vectors plus ~2M links per node at the base layer (d = 768
float32 with M = 16 is ~3.2 KB per vector, ~3.2 GB per 10^6), and gives high recall at
sub-millisecond-scale latency; raise `ef_search` for recall. IVF-PQ stores ~m bytes per vector
(64-byte codes: ~70 MB per 10^6 with ids) at lower recall unless candidates are re-ranked with
exact distances; tune `nlist` and `nprobe`. Always measure recall@k against exact search on a
held-out query set.

## 8. Graph representations and persistence

| Representation | Space | Best for |
|---|---|---|
| CSR adjacency (static) | O(V + E) | traversals; two flat arrays |
| bitset adjacency matrix | V^2 / 8 bytes | dense graphs, O(1) edge test |
| edge list | O(E) | Kruskal, streaming, I/O |
| union-find | O(V) | incremental connectivity, O(alpha(n)) |
| link-cut / Euler-tour trees | O(V) | dynamic forests, O(log n) |

Persistent structures copy the root-to-leaf path on each update: O(log n) time and space per
version, old versions shared. Immutability pays for snapshots (consistent reads while writers
continue), undo histories, and lock-free readers (publish a new root with one atomic store); it
costs allocation and GC pressure on write-heavy paths.

## 9. Adversarial keys

- Untrusted keys (HTTP parameters, JSON object keys, user IDs) need a keyed hash with a random
  per-process seed: SipHash (Rust default, Python `str` hashing) or the runtime's randomised
  default. Otherwise collision floods turn O(1) into O(n) per operation (HashDoS).
- Java mitigates with bucket treeification (O(log n) per colliding bucket for `Comparable` keys).
- Fast non-keyed hashes (FxHash, wyhash with a fixed seed) are for trusted keys only.
- Never expose hash iteration order in APIs or outputs: it changes between runs and versions
  (Go randomises it deliberately) and leaks seed information.

## 10. Pitfalls

- Python `list.pop(0)` and `x in list` are O(n): use `deque.popleft()` and a `set`.
- Java `LinkedList` almost never wins: `ArrayList` / `ArrayDeque` are faster for nearly every mix.
- Iterator and reference invalidation on rehash or vector growth (C++ `unordered_map` rehash,
  `vector::push_back`, Rust borrowck prevents it, C++ does not).
- Mutable objects as hash keys: mutate after insertion and the entry becomes unreachable.
- Small n: a linear scan over a flat array beats trees and hash maps below ~32-64 elements;
  measure. Use small-size-optimised containers (`SmallVec`, `absl::InlinedVector`) for tiny
  collections to avoid allocations.

## 11. Worked example: leaderboard

10^6 players, 50k score updates/s, top-100 and rank-of-player queries. Integer scores in
[0, 10^6]; rank = 1 + number of players with a strictly higher score (ties share a rank).

| Option | Update | Rank | Top-100 | Memory (10^6 players) |
|---|---|---|---|---|
| Redis sorted set (skip list + hash) | `ZADD` O(log n) | `ZREVRANK` O(log n) | `ZREVRANGE 0 99` O(log n + 100) | on the order of 100 B per member (measure with `MEMORY USAGE`) |
| order-statistic tree keyed (-score, id) | O(log n), 1 allocation | O(log n) | O(log n + 100) | ~50-70 B per node |
| Fenwick over score buckets | O(log S), no allocation | O(log S) | O(d log S), d = distinct scores in the top 100 | 4(S + 1) B counts + score array + buckets |

```python
class Fenwick:
    def __init__(self, n): self.n, self.t = n, [0] * (n + 1)
    def add(self, i, d):                          # 0-based position
        i += 1
        while i <= self.n: self.t[i] += d; i += i & -i
    def prefix(self, i):                          # sum over [0, i]
        i += 1; s = 0
        while i > 0: s += self.t[i]; i -= i & -i
        return s
    def lower_bound(self, k):                     # smallest i with prefix(i) >= k, k >= 1
        pos, step = 0, 1 << self.n.bit_length()
        while step:
            if pos + step <= self.n and self.t[pos + step] < k:
                pos += step; k -= self.t[pos]
            step >>= 1
        return pos

class Leaderboard:
    def __init__(self, max_score):
        self.fw, self.score, self.bucket = Fenwick(max_score + 1), {}, {}
    def set_score(self, player, s):
        old = self.score.get(player)
        if old is not None:
            self.fw.add(old, -1); b = self.bucket[old]; b.discard(player)
            if not b: del self.bucket[old]
        self.score[player] = s; self.fw.add(s, 1)
        self.bucket.setdefault(s, set()).add(player)
    def rank(self, player):
        return 1 + len(self.score) - self.fw.prefix(self.score[player])
    def top(self, k):
        out, n = [], len(self.score)
        while len(out) < min(k, n):
            s = self.fw.lower_bound(n - len(out))  # score of the next-best player
            out.extend(sorted(self.bucket[s])[: k - len(out)])
        return out
```

Checked for this skill against a brute-force dict (300 seeded runs x 200 operations, rank and
top-k with ties broken by player id). In C++/Rust replace the per-score sets with vectors plus a
position index (swap-remove), and use int32 counts.

Benchmark plan (fixed seeds, warm-up, >= 5 repetitions, report median and p99/p999 with an
HdrHistogram):
- 10^6 players, initial scores from the production histogram (or Pareto if unknown).
- 10^7 operations: 95% updates on players drawn from Zipf(s = 1.1) (hot players dominate, which
  favours caches and hurts lock contention), 4.9% rank queries, 0.1% top-100.
- Drive at 1x, 5x and 10x the 50k/s peak; record throughput, latency per operation type and RSS.

Decision rule: choose the Fenwick design when scores are bounded integers (S up to ~10^7),
shared ranks for ties are acceptable and one process owns the data; choose an order-statistic
tree or skip list when keys are unbounded or compound (score, timestamp) for unique ranks; choose
Redis sorted sets when several services share the leaderboard or persistence is needed. Among
candidates that hold p99 update < 1 ms and p99 top-100 < 5 ms at 5x peak, take the smallest RSS.

Related: `graph-algorithms`, `randomized-algorithms-sketches`, `string-algorithms`, `amortized-recurrence-analysis`, `algorithm-design-paradigms`, `performance-optimization`, hub `cs-foundations`
