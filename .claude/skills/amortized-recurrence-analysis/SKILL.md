---
name: amortized-recurrence-analysis
description: "Proving running-time bounds: cost models and measures (worst, expected, amortised, average, w.h.p.), recurrences (master theorem and its gaps, Akra-Bazzi, recursion trees, substitution, characteristic roots), aggregate, accounting and potential methods with standard potentials, de-amortisation for latency, competitive analysis, work-span bounds and empirical scaling checks. Load when deriving, proving or disputing a complexity bound."
when_to_use: "Solving T(n) = aT(n/b) + f(n) or an unequal-split recurrence; 'is this really O(1) amortised / O(n log n)?'; a p99 latency spike traced to a resize, rehash or compaction; proving a bound for a data structure or a divide-and-conquer algorithm; competitive ratios of caching or online policies; checking a claimed complexity with measurements."
---

# Amortised and recurrence analysis

Bounds with their model, measure and proof. Algorithm design is in `algorithm-design-paradigms`,
Chernoff-style high-probability bounds in `randomized-algorithms-sketches`, benchmarking
statistics in `performance-optimization`; hub `cs-foundations` section 2.

## 1. Declare the model and the measure first

| Model | Unit cost | Use |
|---|---|---|
| word RAM, w = Theta(log n) bits | arithmetic, memory access on w-bit words | default for algorithms on integers and pointers |
| comparison | comparisons only | sorting and searching lower bounds |
| external memory (B, M) | block transfers of B items, memory M | databases, large sorts: sort(N) = Theta((N/B) log_{M/B}(N/B)) |
| work-span | work W (total ops), span D (critical path) | parallel algorithms, T_p <= W/p + D |

| Measure | Statement | Typical source |
|---|---|---|
| worst case | every input of size n | deterministic code paths |
| expected | over the algorithm's own randomness, every input | quicksort with random pivots, hashing with random seeds |
| average | over a stated input distribution | uniform keys: say so explicitly |
| amortised | total over any sequence divided by its length | dynamic arrays, union-find, splay trees |
| with high probability | probability >= 1 - n^(-c) | skip lists, randomised load balancing |

Hidden costs: hashing is O(1) only in expectation and with a suitable hash; big integers cost
O(digits) per operation; string comparison and hashing cost O(length); recursion depth costs
stack and can overflow; memory allocation is not free.

## 2. Master theorem and where it fails

T(n) = a T(n/b) + f(n), a >= 1, b > 1, c* = log_b a:

| Case | Condition | Result |
|---|---|---|
| 1 | f(n) = O(n^(c* - eps)) | Theta(n^c*) |
| 2 | f(n) = Theta(n^c* log^k n), k >= 0 | Theta(n^c* log^(k+1) n) |
| 3 | f(n) = Omega(n^(c* + eps)) and a f(n/b) <= c f(n) for some c < 1 | Theta(f(n)) |

Examples: merge sort 2T(n/2) + n gives n log n; Karatsuba 3T(n/2) + n gives n^1.585; Strassen
7T(n/2) + n^2 gives n^2.807; binary search T(n/2) + 1 gives log n.

Outside the three cases:
- **Log factors below n^c***: a = b = 2, f(n) = n / log n is not O(n^(1 - eps)) and not
  Theta(n log^k n) for k >= 0. The recursion tree gives level i cost n / (log n - i), summing to
  n H_(log n) = **Theta(n log log n)**. Extended case 2: k = -1 gives Theta(n^c* log log n), k < -1
  gives Theta(n^c*).
- **Non-polynomial gaps**: in the textbook statement f(n) = n log n with a = b = 2 falls between
  cases 2 (k = 0) and 3; the extended case 2 (k = 1) gives Theta(n log^2 n).
- **Regularity failure** in case 3, e.g. a = 1, b = 2, f(n) = n (2 - cos n).
- **Floors and ceilings** do not change the asymptotics (Akra-Bazzi tolerates perturbations
  h(n) = O(n / log^2 n)); unequal splits need Akra-Bazzi.

**Akra-Bazzi**: T(n) = sum a_i T(b_i n + h_i(n)) + g(n). Find p with sum a_i b_i^p = 1; then
T(n) = Theta(n^p (1 + integral_1^n g(u) / u^(p+1) du)).
Worked: T(n) = T(n/3) + T(2n/3) + n. (1/3)^p + (2/3)^p = 1 gives p = 1; the integral is
integral_1^n u / u^2 du = ln n, so T(n) = Theta(n log n). Median of medians T(n/5) + T(7n/10) + n:
(1/5)^1 + (7/10)^1 = 0.9 < 1 so p < 1, the integral is Theta(n^(1-p)) and T(n) = Theta(n).

## 3. Other recurrence methods

- **Recursion tree**: write the cost per level. Geometrically decreasing per-level costs: the root
  dominates (case 3). Increasing: the leaves dominate (case 1). Equal: levels x per-level cost.
- **Substitution with a strengthened hypothesis**: T(n) = 2T(n/2) + 1, guess T(n) <= cn fails
  (cn + 1). Strengthen to T(n) <= cn - d: 2(cn/2 - d) + 1 = cn - 2d + 1 <= cn - d for d >= 1.
- **Characteristic roots** for T(n) = c_1 T(n-1) + ... + c_k T(n-k): roots r of
  x^k = c_1 x^(k-1) + ... + c_k; a root of multiplicity m contributes n^j r^n for j < m. Fibonacci:
  x^2 = x + 1 gives phi^n, phi = 1.618.
- **Generating functions**: multiply by x^n, sum, solve for G(x); the smallest singularity rho of
  G gives growth (1/rho)^n, partial fractions give exact forms.
- **Change of variables**: T(n) = 2T(sqrt n) + log n; with m = log n, S(m) = 2S(m/2) + m gives
  Theta(m log m), so T(n) = Theta(log n log log n).

| Recurrence | Solution |
|---|---|
| T(n-1) + O(1) / T(n-1) + O(n) / 2T(n-1) + O(1) | O(n) / O(n^2) / O(2^n) |
| T(n/2) + O(1) / T(n/2) + O(n) | O(log n) / O(n) |
| 2T(n/2) + O(1) / 2T(n/2) + O(n) / 2T(n/2) + O(n log n) | O(n) / O(n log n) / O(n log^2 n) |
| 2T(n/2) + n / log n | Theta(n log log n) |
| T(sqrt n) + O(1) / 2T(sqrt n) + log n / sqrt(n) T(sqrt n) + n | O(log log n) / O(log n log log n) / O(n log log n) |
| T(n/3) + T(2n/3) + O(n) | O(n log n) |
| T(n/5) + T(7n/10) + O(n) | O(n) (median of medians) |

## 4. Aggregate method

Bound the total cost of any sequence of n operations, divide by n.
- **Binary counter**: bit i flips floor(n / 2^i) times in n increments; sum < 2n flips.
- **Monotone stack / deque**: each element is pushed once and popped at most once: O(n) total
  however long a single pop loop runs.
- **BFS / DFS**: each vertex is dequeued once and each adjacency list scanned once: O(V + E).
- **KMP prefix function**: the border pointer rises by at most 1 per character and every fallback
  lowers it, so total fallbacks <= n.

## 5. Accounting method

Charge each operation an amortised fee; store the surplus as credit on specific elements; prove
the credit never goes negative by an invariant checked at every operation.

- **Dynamic array with doubling**: charge 3 per push: 1 to write, 1 stored on the new element,
  1 stored on an element from the older half. Invariant: credit >= 2 (size - capacity/2). When a
  full array of capacity c doubles, the c/2 elements pushed since the last resize hold c credits,
  exactly paying for copying c elements.
- **Shrinking**: halve when size drops to capacity/4, not 1/2. With a 1/2 threshold, alternating
  push and pop at the boundary resizes every operation: Theta(n) each.

## 6. Potential method

Amortised cost = actual + Phi(after) - Phi(before). Requirements: Phi >= 0 always and Phi_0 = 0,
so the sum of amortised costs bounds the sum of actual costs.

| Structure | Potential | Amortised result |
|---|---|---|
| dynamic array (grow only) | Phi = 2 size - capacity | push 3 (resize from k to 2k: (k + 1) + (2 - k) = 3) |
| dynamic array with 1/4 shrink | 2 size - cap if size >= cap/2, else cap/2 - size | O(1) push and pop |
| binary counter | number of 1 bits | increment 2 (t trailing ones: (t + 1) + (1 - t)) |
| multipop stack | stack size | O(1) per operation |
| two-stack queue | Phi = 2 |inbox| | push 3, pop 1 (section 12) |
| splay tree | sum over nodes of log2(subtree size) | access lemma: splay(x) <= 3 (r(root) - r(x)) + 1 = O(log n) |
| union-find, union by rank + path compression | Tarjan's level/index potential | O(alpha(n)) per operation |
| Fibonacci heap | trees + 2 x marked nodes | insert O(1), decrease-key O(1), extract-min O(log n) |

## 7. Amortised bounds versus latency

An amortised bound says nothing about one request: a rehash of 10^7 entries, a vector doubling,
a GC pause or an LSM compaction lands on some p99 request. De-amortise when per-operation
latency matters:
- **Incremental rehash** (Redis dicts): keep old and new tables, move a few buckets on every
  operation (and from a timer), look up in both until done.
- **Pre-sizing**: `reserve` / `with_capacity` when the final size is known.
- **Real-time queues** (Hood-Melville): spread the reversal over the operations so every
  operation is O(1) worst case.
- **Persistence breaks naive amortisation**: an expensive operation can be replayed on the same
  old version many times. Okasaki's banker's method combines laziness with memoisation: the
  suspension is paid for before it is forced and evaluated at most once (section 12).

## 8. Expected bounds

Linearity of expectation with indicator variables, no independence needed. Randomised quicksort
on distinct keys: the i-th and j-th smallest are compared iff one of them is the first pivot
chosen among the j - i + 1 keys between them: probability 2 / (j - i + 1). Summing gives
2(n + 1) H_n - 4n ~ 2n ln n ~ 1.39 n log2 n comparisons. Expectation alone does not bound the
tail; for "with high probability" use Chernoff bounds (`randomized-algorithms-sketches`).

## 9. Online and parallel bounds

| Problem | Policy | Ratio |
|---|---|---|
| ski rental (rent 1/day, buy B) | rent B - 1 days, then buy | 2 - 1/B deterministic (optimal) |
| ski rental | randomised buy day | e / (e - 1) ~ 1.58 |
| paging, cache size k | LRU, FIFO | k-competitive, optimal for deterministic policies |
| paging | randomised marking | 2 H_k |
| list update | move-to-front | 2-competitive |

Work-span: with work W and span D a greedy scheduler gives T_p <= W/p + D (Brent); parallelism
is W/D. Parallel prefix sums (Blelloch scan: up-sweep then down-sweep): W = O(n), D = O(log n),
so T_p = O(n/p + log n), linear speedup while p <= n / log n.

## 10. Empirical check

- Count operations (comparisons, probes, element moves) instead of wall time: no cache, turbo or
  noise effects; time separately once the counts confirm the shape.
- Use n = 2^k for >= 5 sizes over >= 2 decades; repeat with several seeds.
- Fit the log-log slope: `slope = numpy.polyfit(numpy.log(ns), numpy.log(counts), 1)[0]`.
- n log n has local slope 1 + 1/ln n (~1.1 for n = 2^10..2^17), indistinguishable from n^1.1 by
  slope alone: plot counts / (n log2 n) and check it flattens.

Measured for this skill (randomised quicksort comparisons, n = 2^10..2^17, 3 runs each): slope
1.118; counts / (n log2 n) between 1.13 and 1.20, matching 2(n + 1) H_n - 4n within noise and
approaching the 1.386 asymptote slowly because of the -2.85n term. Statistics for wall-clock
benchmarks are in `performance-optimization`.

## 11. Pitfalls

- An amortised bound quoted for an SLO or a per-request latency budget.
- An average-case result over uniform inputs presented as worst case (quicksort with a fixed
  first-element pivot on sorted input is Theta(n^2)).
- O() hiding 10^3 constants or a log factor that matters at the real n.
- Expected bounds defeated by adversarial inputs when the seed is fixed, logged or leaked (hash
  flooding, quicksort killers).
- A potential that can go negative, or that starts above 0 without accounting for it.

## 12. Worked example: two-stack queue

```python
class TwoStackQueue:
    def __init__(self): self.inbox, self.outbox, self.cost = [], [], 0
    def push(self, x):
        self.inbox.append(x); self.cost += 1
    def pop(self):
        if not self.outbox:
            while self.inbox:                  # transfer: one pop + one push per element
                self.outbox.append(self.inbox.pop()); self.cost += 2
        self.cost += 1
        return self.outbox.pop()
```

Proof with Phi = 2 |inbox| (Phi >= 0, Phi_0 = 0): push costs 1 and raises Phi by 2, amortised 3;
pop from a non-empty outbox costs 1, amortised 1; pop that transfers k elements costs 2k + 1 and
lowers Phi by 2k, amortised 1. Hence for any sequence, actual cost + Phi_end = 3 pushes + pops
exactly, and actual cost <= 3 pushes + pops. The worst single pop is Theta(n).

Real-time version (Okasaki): a persistent queue with O(1) worst-case operations. The front is a
lazy stream; when |rear| would exceed |front|, a rotation front ++ reverse(rear) starts as a
suspension, and a schedule forces one cell per operation so no single operation does more than
O(1) work.

```python
class Lazy:                                    # memoised thunk = one stream cell
    __slots__ = ("thunk", "val")
    def __init__(self, thunk=None, val=None): self.thunk, self.val = thunk, val
    def force(self):
        if self.thunk is not None: self.val, self.thunk = self.thunk(), None
        return self.val                        # None (empty) or (head, tail)

EMPTY = Lazy()
def cons(x, s): return Lazy(val=(x, s))
def rotate(f, r, a):                           # lazily f ++ reverse(r) ++ a, |r| = |f| + 1
    def step():
        cell = f.force()                       # already forced by the schedule: O(1)
        x, r_rest = r
        if cell is None: return (x, a)
        return (cell[0], rotate(cell[1], r_rest, cons(x, a)))
    return Lazy(step)

class RTQueue:                                 # invariant: |schedule| = |front| - |rear|
    __slots__ = ("f", "r", "s")
    def __init__(self, f=EMPTY, r=None, s=EMPTY): self.f, self.r, self.s = f, r, s
    @staticmethod
    def _exec(f, r, s):
        cell = s.force()
        if cell is not None: return RTQueue(f, r, cell[1])
        f2 = rotate(f, r, EMPTY)
        return RTQueue(f2, None, f2)
    def push(self, x): return RTQueue._exec(self.f, (x, self.r), self.s)
    def pop(self):
        cell = self.f.force()
        if cell is None: raise IndexError("pop from empty queue")
        return cell[0], RTQueue._exec(cell[1], self.r, self.s)
```

Verification run for this skill (seeded, 10^6 random operations, 55% push / 45% pop, checked
against `collections.deque`): two-stack queue with 550 133 pushes and 449 867 pops cost 2 016 970
<= 3 x 550 133 + 449 867 = 2 100 266; actual + Phi_end equalled the amortised sum after every
operation; the worst single pop cost 184 565 (one transfer of ~92 000 elements). The real-time
queue never evaluated more than 1 suspension per operation, ran with the recursion limit lowered
to 200 (forcing stays shallow), and repeated pops on one shared old version cost 0 evaluations
(memoised). Use the two-stack queue when throughput matters and the real-time or a ring-buffer
deque when p99 latency or persistence matters; in imperative code a block-linked deque
(`collections.deque`) already gives O(1) worst-case ends (`std::deque` occasionally reallocates
its block map, a pointer copy).

Related: `algorithm-design-paradigms`, `dynamic-programming-patterns`, `data-structure-selection`, `randomized-algorithms-sketches`, `np-hardness-reductions`, `performance-optimization`, hub `cs-foundations`
