# Data structure selection reference

Pick by the operation mix and its frequencies, then by constants (cache behaviour, allocation),
then by implementation availability. Measure with realistic data before committing.

## 1. Dictionaries and sets

| Structure | Insert | Lookup | Delete | Ordered ops | Notes |
|---|---|---|---|---|---|
| Hash table, chaining | O(1) exp | O(1) exp | O(1) exp | no | simple; pointer chasing |
| Hash table, open addressing (linear/Robin Hood/Swiss) | O(1) exp | O(1) exp | O(1) exp (tombstones/backshift) | no | cache friendly; keep load ≤ ~0.875 (Swiss) or ~0.7 (linear) |
| Cuckoo hashing | O(1) amortised exp | O(1) worst | O(1) | no | worst-case lookups; rebuilds |
| Red-black / AVL tree | O(log n) | O(log n) | O(log n) | yes | AVL stricter balance, faster lookups |
| B-tree / B+tree (in memory) | O(log n) | O(log n) | O(log n) | yes, fast scans | best cache behaviour among ordered maps |
| Skip list | O(log n) exp | O(log n) exp | O(log n) exp | yes | simple lock-free variants exist |
| Treap / splay tree | O(log n) exp / amortised | same | same | yes | splay adapts to access skew |
| Radix tree / ART | O(k) | O(k) | O(k) | yes (lexicographic) | k = key length; great for strings and integer keys |
| Sorted array | O(n) | O(log n) | O(n) | yes | best for static data; Eytzinger layout for cache |
| van Emde Boas / y-fast trie | O(log log U) | O(log log U) | O(log log U) | predecessor | integer universe U; large constants |

Adversarial input: use a keyed hash (SipHash, or the language's randomised default) for
untrusted keys; otherwise collision attacks degrade to O(n) per operation.

## 2. Priority queues

| Structure | Insert | Find-min | Delete-min | Decrease-key | Merge |
|---|---|---|---|---|---|
| Binary heap | O(log n) | O(1) | O(log n) | O(log n) (needs handle) | O(n) |
| d-ary heap | O(log_d n) | O(1) | O(d log_d n) | O(log_d n) | O(n) |
| Pairing heap | O(1) | O(1) | O(log n) amortised | o(log n) amortised | O(1) |
| Fibonacci heap | O(1) | O(1) | O(log n) amortised | O(1) amortised | O(1) |
| Radix heap | O(1) amortised | - | O(log C) amortised | O(1) | - (monotone, integer keys ≤ C) |

In practice a binary or 4-ary heap with lazy deletion (push duplicates, skip stale entries) beats
Fibonacci heaps for Dijkstra on real graphs.

## 3. Sequences

| Need | Structure | Notes |
|---|---|---|
| Append, index | dynamic array | O(1) amortised append, growth factor 1.5-2 |
| Both ends | ring buffer deque | O(1) both ends |
| Insert/delete in middle, large text | rope / piece table / gap buffer | editors (piece table: VS Code; gap buffer: Emacs) |
| Persistent / immutable | RRB-vector, finger tree, HAMT | O(log n) with high branching factor |
| Order statistics | order-statistic tree, Fenwick on ranks | k-th element in O(log n) |

## 4. Range queries

| Query | Updates | Structure | Cost |
|---|---|---|---|
| Sum | point | Fenwick (BIT) | O(log n), tiny constant |
| Any associative op (min, max, gcd, matrix product) | point / range (lazy) | segment tree | O(log n) |
| Min, static | none | sparse table | O(1) query, O(n log n) build |
| LCA | none | Euler tour + sparse table, or binary lifting | O(1) / O(log n) |
| 2D sum, static | none | prefix sums | O(1) |
| Intervals overlapping a point/interval | insert/delete | interval tree, segment tree on coordinates | O(log n + k) |
| Offline many queries | none | Mo's algorithm, sqrt decomposition | O((n + q) sqrt n) |

## 5. Strings

| Need | Structure / algorithm | Cost |
|---|---|---|
| Single pattern search | KMP, Z-algorithm, Boyer-Moore (practical), two-way (glibc memmem) | O(n + m) |
| Many patterns | Aho-Corasick | O(n + Σm + matches) |
| Many queries on one text | suffix array + LCP (SA-IS build O(n)), FM-index (compressed) | O(m log n) or O(m) |
| All distinct substrings, LCS of two strings | suffix automaton | O(n) |
| Prefix lookups, autocomplete | trie / radix tree / DAWG / FST (Lucene) | O(m) |
| Approximate matching | edit-distance DP (O(nm), SETH-hard to beat), bit-parallel Myers, BK-trees, n-gram indexes | - |
| Hash-based substring compare | rolling hash (Rabin-Karp) with random base mod a large prime | O(1) compare, probabilistic |

## 6. Graphs

| Representation | Space | Best for |
|---|---|---|
| Adjacency list (CSR for static) | O(V + E) | sparse graphs, traversals; CSR is cache friendly |
| Adjacency matrix / bitset | O(V²) | dense graphs, O(1) edge test, bit-parallel algorithms |
| Edge list | O(E) | Kruskal, streaming, input/output |
| Union-find | O(V) | incremental connectivity |
| Link-cut / Euler-tour trees | O(V) | dynamic forests (O(log n)) |

## 7. Probabilistic and streaming structures

| Structure | Answers | Space / error |
|---|---|---|
| Bloom filter | membership, false positives only | m = -n ln p / (ln 2)² bits, k = (m/n) ln 2 hashes; p = 1% → 9.6 bits/key, 0.1% → 14.4 |
| Blocked / register-blocked Bloom | same, one cache line per query | slightly more bits for same p |
| Cuckoo filter / quotient filter / XOR (binary fuse) filter | membership; deletes (cuckoo, quotient); static (XOR) | binary fuse ≈ 1.13 × log2(1/p) bits/key |
| Count-min sketch | frequency over-estimates | w = ceil(e/ε), d = ceil(ln 1/δ); error ≤ εN w.p. 1 - δ |
| Count sketch | frequency, unbiased | error ∝ ‖f‖₂ / sqrt(w) |
| Misra-Gries / Space-Saving | heavy hitters (top-k) | k counters, error ≤ N/k |
| HyperLogLog (HLL++) | distinct count | 1.04/sqrt(m) relative std error; 2^14 registers ≈ 12 KB → 0.8% |
| KLL / t-digest | quantiles | KLL: ε-approx rank with O((1/ε) log log(1/δ)) space; t-digest: accurate tails, heuristic |
| Reservoir sampling | uniform k-sample of a stream | O(k) |
| MinHash / SimHash | Jaccard / cosine similarity | error 1/sqrt(k) |
| LSH | approximate nearest neighbour | tuned (bands × rows) |

## 8. Storage engines

| Engine | Writes | Reads | Space | Use |
|---|---|---|---|---|
| B+tree (in place) | random I/O, write amplification from page rewrites | O(log_B n) I/O, great range scans | moderate fragmentation | OLTP, read-heavy (PostgreSQL, InnoDB) |
| LSM tree (leveled) | sequential, batched | point reads check several levels (Bloom filters per SSTable) | low space amp, high write amp (~10-30x) | write-heavy, KV stores (RocksDB) |
| LSM (tiered / universal) | lowest write amp | more read amp | higher space amp | ingest-heavy |
| Log-structured hash (Bitcask) | sequential | O(1) with in-memory index | keys must fit in RAM | simple KV |
| Columnar (Parquet, ORC, Arrow) | batch append | fast scans of few columns, compression | very compact | analytics |

RUM conjecture: you cannot minimise read, update and memory overhead simultaneously; state which
two you optimise.

## 9. Concurrent structures

| Need | Choice |
|---|---|
| Shared map, mostly reads | read-copy-update / epoch-based, or sharded RW locks |
| Shared map, mixed | lock striping (ConcurrentHashMap), or lock-free hash (split-ordered lists) |
| Queue, single producer single consumer | lock-free ring buffer (no CAS needed) |
| Queue, MPMC | Michael-Scott queue, LCRQ, or bounded ring with sequence numbers (Vyukov) |
| Counters | per-thread/sharded counters aggregated on read (LongAdder) |
| Memory reclamation | hazard pointers, epoch-based reclamation (crossbeam-epoch), RCU |

Always state the progress guarantee and the reclamation scheme; lock-free without safe
reclamation is a use-after-free.
