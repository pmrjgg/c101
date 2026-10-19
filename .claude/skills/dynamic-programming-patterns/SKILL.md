---
name: dynamic-programming-patterns
description: "Dynamic programming design and optimisation: state, recurrence, evaluation order, base cases and reconstruction; classic families (knapsack, LIS, alignment, interval, tree, bitmask, digit, DAG, profile DP); speedups (monotone queue, convex hull trick/Li Chao, divide-and-conquer and Knuth optimisation, SOS, Aliens trick, matrix power); memory reduction. Load when a problem has overlapping subproblems or an existing DP is too slow or too large."
when_to_use: "Recursive solution that recomputes the same arguments; 'count the ways', 'minimum cost to', 'maximum value with capacity'; an O(n^2) or O(kn^2) DP that times out; a DP table that does not fit in memory; lru_cache recursion errors; reviewing a knapsack/LIS/edit-distance/bitmask/digit DP for loop-direction or base-case bugs."
---

# Dynamic programming patterns

Design, speed up and shrink DPs. Paradigm choice and greedy proofs are in
`algorithm-design-paradigms`; recurrence solving in `amortized-recurrence-analysis`; hub
`cs-foundations` section 1.

## 1. Five-step recipe

1. **State in words**: "dp[i][j] = minimum cost using the first i items with j units used". If you
   cannot say it in one sentence, the state is wrong or missing a dimension.
2. **Transition**: the last decision, e.g. dp[i][j] = min(dp[i-1][j], dp[i-1][j-w_i] + c_i).
3. **Evaluation order**: a topological order of the state DAG (every state read is already final).
4. **Base cases and impossible states**: impossible = +inf for min, -inf for max, 0 ways for counts;
   never 0 for an impossible min/max state. Extract the answer (dp[n][W], or max over a row).
5. **Cost** = number of states x transition cost; memory = states kept alive.

Reconstruction: store a parent pointer per state, or re-walk the finished table from the answer
asking which transition achieved the stored value (no extra memory).

## 2. Top-down vs bottom-up

| Use | When | Notes |
|---|---|---|
| memoised recursion (`functools.cache`, a `HashMap`) | reachable states are sparse or hard to enumerate | Python's default recursion limit is 1000; deep chains need an explicit stack or bottom-up |
| table, bottom-up | states dense, order obvious | vectorisable, no call overhead, enables rolling rows |

- The memo key must contain every input that changes the answer; globals or mutable arguments
  read inside the function silently corrupt the cache.
- `lru_cache` needs hashable arguments: pass tuples or frozensets, never lists or dicts; call
  `f.cache_clear()` between test cases.
- A cycle in the state graph (dp[a] depends on dp[b] which depends on dp[a]) is not a DP: use
  Bellman-Ford / Dijkstra on the state graph, value iteration to a fixpoint, or solve the linear
  system (expected-value problems with self-loops).

## 3. Family catalogue

| Family | State | Cost |
|---|---|---|
| 0/1 knapsack | dp[c] best value at capacity c; capacity loop **downward** | O(nW) time, O(W) space |
| unbounded knapsack | same; capacity loop **upward** | O(nW) |
| subset sum | bitset of reachable sums: `bits |= bits << a` | O(nT / w) |
| LIS | tails[l] = smallest tail of an increasing subsequence of length l+1 | O(n log n) |
| LCS, edit distance | dp[i][j] over prefixes | O(nm) |
| interval / matrix chain | dp[l][r] = min over split m | O(n^3) |
| tree DP, rerooting | down[v] from children, up[v] from parent, combine for every root | O(n) |
| bitmask TSP | dp[mask][v] = shortest path visiting mask, ending at v | O(2^n n^2), n <= 20-23 (memory 2^n n) |
| digit DP | (pos, tight, started, aux) for counting numbers <= N with a property | O(digits x states x 10) |
| longest path in a DAG | dp[v] over a topological order | O(V + E) |
| broken profile (tilings) | (cell, mask of the frontier) | O(n m 2^m) |
| expected value | E[s] = cost(s) + sum p(s,t) E[t] | DAG order; linear solve if cyclic |

```python
from bisect import bisect_left
def lis_length(a):                       # strict; use bisect_right for non-decreasing
    tails = []
    for x in a:
        i = bisect_left(tails, x)
        if i == len(tails): tails.append(x)
        else: tails[i] = x
    return len(tails)

def knapsack01(items, W):                # items: (weight, value)
    dp = [0] + [float("-inf")] * W       # exact capacity; use [0] * (W + 1) for "at most W"
    for w, v in items:
        for c in range(W, w - 1, -1):    # downward: each item used at most once
            dp[c] = max(dp[c], dp[c - w] + v)
    return max(dp)

def subset_sums(a, T):                   # bit s set iff some subset sums to s (s <= T)
    bits, mask = 1, (1 << (T + 1)) - 1
    for x in a:
        bits = (bits | bits << x) & mask
    return bits

from functools import cache
def count_upto(N, pred_digit_sum):       # digit DP: #x in [0, N] whose digit sum satisfies pred
    digits = list(map(int, str(N)))
    @cache
    def go(pos, tight, s):
        if pos == len(digits): return int(pred_digit_sum(s))
        hi = digits[pos] if tight else 9
        return sum(go(pos + 1, tight and d == hi, s + d) for d in range(hi + 1))
    return go(0, True, 0)                # add a `started` flag when leading zeros matter
```

## 4. Transition speedups

| Technique | Recurrence shape | Applies when | Cost |
|---|---|---|---|
| monotone deque | dp[i] = min over j in [i-k, i) of dp[j] + c(i) | sliding window of j | O(n) |
| convex hull trick | dp[i] = c(i) + min_j (m_j x_i + b_j) | slopes and queries monotone | O(n) |
| Li Chao tree | same | arbitrary order of lines/queries | O(n log C) |
| divide-and-conquer opt | dp_t[i] = min_{j<i} dp_{t-1}[j] + C(j, i) | opt(i) <= opt(i+1), implied by the quadrangle inequality on C | O(k n log n) |
| Knuth | dp[l][r] = min_{l<=m<r} dp[l][m] + dp[m+1][r] + C(l, r) | C has the QI and is monotone on inclusion | O(n^3) -> O(n^2) |
| SOS (sum over subsets) | F[mask] = sum of f[sub] over sub of mask | subset convolution style sums | O(n 2^n) instead of O(3^n) |
| matrix power | linear recurrence of order k | constant coefficients | O(k^3 log n) (Kitamasa O(k^2 log n)) |

Quadrangle inequality (QI): C(a,c) + C(b,d) <= C(a,d) + C(b,c) for a <= b <= c <= d. With QI the
smallest argmin is non-decreasing in i. Knuth then restricts m to [opt(l, r-1), opt(l+1, r)],
which telescopes to O(n^2) total.

```python
class LiChao:                            # min of lines m*x + b over integer x in [lo, hi]
    def __init__(self, lo, hi):
        self.lo, self.hi, self.node = lo, hi, {}
    def add(self, m, b, k=1, lo=None, hi=None):
        lo = self.lo if lo is None else lo; hi = self.hi if hi is None else hi
        cur = self.node.get(k)
        if cur is None: self.node[k] = (m, b); return
        mid = (lo + hi) // 2
        f = lambda ln, x: ln[0] * x + ln[1]
        if f((m, b), mid) < f(cur, mid): self.node[k], (m, b) = (m, b), cur
        if lo == hi: return
        if f((m, b), lo) < f(self.node[k], lo): self.add(m, b, 2 * k, lo, mid)
        elif f((m, b), hi) < f(self.node[k], hi): self.add(m, b, 2 * k + 1, mid + 1, hi)
    def query(self, x):
        k, lo, hi, best = 1, self.lo, self.hi, float("inf")
        while k in self.node:
            m, b = self.node[k]; best = min(best, m * x + b)
            mid = (lo + hi) // 2
            k, lo, hi = (2 * k, lo, mid) if x <= mid else (2 * k + 1, mid + 1, hi)
        return best

def sos(f, n):                           # F[mask] = sum of f[sub] for sub subset of mask
    F = list(f)
    for b in range(n):
        for mask in range(1 << n):
            if mask >> b & 1: F[mask] += F[mask ^ (1 << b)]
    return F
```

## 5. Dimension removal: the Aliens trick (WQS / Lagrangian)

When the answer f(k) for "exactly k pieces" is convex in k, drop k: solve
g(lam) = min over any count of (cost + lam * count), which is often one fast 1-D DP. For integer
costs the breakpoints are integers, so binary search lam over integers.

- Let kmin(lam) be the smallest optimal count at lam (non-increasing in lam). Take the smallest lam
  with kmin(lam) <= k; then k is optimal at lam and **f(k) = g(lam) - lam * k**. This is the tie
  rule: several k can share one lam (collinear hull points), so never read the count back.
- Exact tie-breaking without tracking pairs: with S = n + 1 > any count, minimise
  S * (cost + lam * cnt) + cnt; then value = result // S and kmin = result % S.
- Search range: lam in [0, f(1) - f(2)] when f is non-increasing; the convexity proof usually comes
  from QI (Monge) costs. If convexity is not proven, differential-test first: Aliens silently
  returns wrong answers on non-convex f.

## 6. Memory reduction

- **Rolling rows**: if row i reads only row i-1, keep two rows (or one, see below): O(m) memory.
- **1-D in-place direction rule**: reading the previous row at smaller indices (0/1 knapsack) means
  iterate downward so reads see old values; reading the current row (unbounded) means upward.
  LCS in one row needs one saved diagonal variable.
- **Hirschberg**: alignment with reconstruction in O(nm) time and O(min(n, m)) space. Run the
  forward score row for A[:n/2] vs B and the backward row for A[n/2:] vs B, split B at the column
  minimising the sum, recurse on both halves. Time roughly doubles.
- **Checkpoint and recompute**: keep every sqrt(n)-th row; during reconstruction recompute the
  rows between checkpoints: O(sqrt(n) m) memory, about 2x time.

## 7. Correctness argument

- **Optimal substructure by cut-and-paste**: if an optimal solution used a non-optimal
  sub-solution, replacing it by the optimal one would improve the whole: contradiction.
- **Induction over the evaluation order**: every state is computed from final states, and the
  transition enumerates all last decisions (completeness) and only feasible ones (soundness).
- **Differential testing** against exhaustive enumeration for n <= 8-10 (section 10).
- O(nW) is **pseudo-polynomial**: W takes log W bits, so the running time is exponential in the
  input size. Knapsack stays NP-hard; see `np-hardness-reductions` before claiming "polynomial".

## 8. Numerics and engineering

- Counting: reduce modulo a prime (10^9 + 7, 998244353) at every addition; exact counts need
  Python ints, `u128` in Rust, `__int128` in C++ or a BigInt.
- Probabilities: multiply in log space and add with logsumexp
  (`m = max(xs); m + log(sum(exp(x - m) for x in xs))`, or `scipy.special.logsumexp`).
- Vectorise row updates: 0/1 knapsack row `dp[w:] = np.maximum(dp[w:], dp[:-w] + v)` is correct
  because the right side is evaluated from old values before assignment.
- Bitsets: Python int shifts, `std::bitset<N>` / `boost::dynamic_bitset`, Rust `bitvec`; 64x
  fewer word operations for Boolean DPs.
- Loop order: make the inner loop run over the contiguous dimension (row-major `dp[i][j]`: inner
  over j); flat 1-D arrays beat lists of lists.

## 9. Pitfalls

- A state missing a dimension (the last item used, the current tightness, whether a segment is
  open): the DP gives plausible wrong answers on some inputs only.
- Wrong loop direction: upward capacity loop turns 0/1 knapsack into unbounded knapsack.
- Impossible states initialised to 0: "minimum cost" becomes 0 for unreachable states.
- A helper recursion left un-memoised inside a memoised one: exponential time again.
- Off-by-one between 1-indexed tables (dp[i] = first i items) and 0-indexed arrays (item i-1).
- D&C/Knuth optimisation applied without checking QI; it fails silently (here: negative values).

## 10. Worked example: k contiguous segments, minimise the sum of squared segment sums

a[0..n-1] >= 0, split into exactly k non-empty contiguous segments. P = prefix sums,
C(j, i) = (P[i] - P[j])^2, dp_t[i] = min_{j<i} dp_{t-1}[j] + C(j, i), dp_0 = [0, inf, ...].

**QI holds for a >= 0**: C(a,c) + C(b,d) - C(a,d) - C(b,c) = -2 (P_b - P_a)(P_d - P_c) <= 0 since P
is non-decreasing. So opt is monotone and f(k) is convex (Monge partition costs), enabling both
speedups. With negative entries P is not monotone and both can fail.

```python
INF = float("inf")
def prefix(a):
    P = [0]
    for x in a: P.append(P[-1] + x)
    return P

def naive(a, k):                                   # O(k n^2)
    n, P = len(a), prefix(a)
    prev = [0] + [INF] * n
    for _ in range(k):
        prev = [INF] + [min(prev[j] + (P[i] - P[j]) ** 2 for j in range(i)) for i in range(1, n + 1)]
    return prev[n]

def dc_opt(a, k):                                  # O(k n log n), iterative (no recursion limit)
    n, P = len(a), prefix(a)
    prev = [0] + [INF] * n
    for _ in range(k):
        cur, stack = [INF] * (n + 1), [(1, n, 0, n - 1)]
        while stack:
            lo, hi, optlo, opthi = stack.pop()
            if lo > hi: continue
            mid = (lo + hi) // 2
            best, bj = INF, optlo
            for j in range(optlo, min(mid - 1, opthi) + 1):
                c = prev[j] + (P[mid] - P[j]) ** 2
                if c < best: best, bj = c, j       # strict <: smallest argmin is monotone
            cur[mid] = best
            stack += [(lo, mid - 1, optlo, bj), (mid + 1, hi, bj, opthi)]
        prev = cur
    return prev[n]

def penalised(P, lam):        # min_j dp[j] + S*(P_i - P_j)^2 + L via a monotone convex hull
    n = len(P) - 1; S = n + 1; L = S * lam + 1     # exact tie-break (section 5)
    dp, hull, head = [0] * (n + 1), [], 0          # lines (m, b), slopes non-increasing
    def add(m, b):
        if len(hull) > head and hull[-1][0] == m:
            if hull[-1][1] <= b: return
            hull.pop()
        while len(hull) - head >= 2:
            (m1, b1), (m2, b2) = hull[-2], hull[-1]
            if (b - b1) * (m1 - m2) <= (b2 - b1) * (m1 - m): hull.pop()
            else: break
        hull.append((m, b))
    add(0, 0)
    for i in range(1, n + 1):
        x = P[i]                                   # queries non-decreasing since a >= 0
        while len(hull) - head >= 2 and \
                hull[head + 1][0] * x + hull[head + 1][1] <= hull[head][0] * x + hull[head][1]:
            head += 1
        m, b = hull[head]
        dp[i] = S * x * x + L + m * x + b
        add(-2 * S * x, dp[i] + S * x * x)
    return dp[n] // S, dp[n] % S                   # (cost + lam*cnt, smallest optimal cnt)

def aliens(a, k):                                  # O(n log C), independent of k
    P = prefix(a)
    lo, hi = 0, P[-1] ** 2 + 1
    while lo < hi:                                 # smallest lam with kmin(lam) <= k
        mid = (lo + hi) // 2
        if penalised(P, mid)[1] <= k: hi = mid
        else: lo = mid + 1
    return penalised(P, lo)[0] - lo * k
```

Python ints make the hull cross-multiplication exact; in C++ the products reach ~10^24 here, so use
`__int128` or long double with care. With a Li Chao tree instead of the monotone hull (needed when
queries are not sorted) the bound becomes O(n log n log C).

Verification (run for this skill): brute force over all `itertools.combinations(range(1, n), k-1)`
cut sets; 4 000 seeded instances with n <= 10, values from {0,0,1,2,3,5,8,13} (zeros force ties),
k in [1, n]: naive, dc_opt and aliens all equal the oracle. Timing in CPython, k = 8, values in
[0, 1000]:

| n | dc_opt | aliens |
|---|---|---|
| 2^12 | 0.09 s | 0.18 s |
| 2^13 | 0.19 s | 0.38 s |
| 2^14 | 0.41 s | 0.81 s |

Both scale ~2.1x per doubling (log-log slope ~1.1). Naive needs k n^2 / 2 ~ 1.7 x 10^10 inner steps
at n = 2^16, so it stays an oracle. Aliens does ~log2(C) ~ 47 penalised passes regardless of k, so
dc_opt wins for k below ~16 and Aliens above; extend the table to 2^16 with the same harness
before choosing for production sizes.

Related: `algorithm-design-paradigms`, `amortized-recurrence-analysis`, `np-hardness-reductions`, `graph-algorithms`, `string-algorithms`, `data-structure-selection`, hub `cs-foundations`
