---
name: algorithm-design-paradigms
description: "Algorithm design from a problem statement: formalise, recognise the classic problem in disguise, pick a paradigm (greedy, divide and conquer, search, solver, streaming, online) and meet its proof obligation, then verify with a brute-force oracle and differential tests. Load when designing an algorithm or judging whether a proposed approach is correct."
when_to_use: "A problem statement with sizes and a min/max/count/feasibility objective; a greedy rule proposed without proof; timeouts at n = 10^5..10^7; choosing between DP, greedy, flow, search or a CP-SAT/MILP model; reviewing an algorithmic PR or contest-style solution; 'can this be faster than O(n^2)?'"
---

# Algorithm design paradigms

From statement to verified algorithm. DP technique lives in `dynamic-programming-patterns`, graphs in
`graph-algorithms`, proofs of bounds in `amortized-recurrence-analysis`, hardness in
`np-hardness-reductions`, randomness and sketches in `randomized-algorithms-sketches`; the hub is
`cs-foundations` section 1.

## 1. Formalisation template

Write this down before choosing anything:

| Field | Fill in |
|---|---|
| Input | types, n, m, value ranges (weights up to 10^9? negative? reals?) |
| Output | value only, or the witness (set, order, path) too |
| Objective | min / max / count (mod p?) / decide / enumerate all |
| Constraints | hard vs soft; ties; online or all input known; queries after preprocessing |
| Machine model | word RAM (w = 64), comparison only, external memory (B, M), work-span (W, D), streaming (one pass, sublinear space) |
| Budget | time limit, memory limit, latency percentile if it serves requests |

Size-to-budget table at ~10^8 simple operations per second per core (C++/Rust/Java; divide n by
roughly 10-50 for pure Python loops, or vectorise):

| n up to | Affordable | Typical algorithm |
|---|---|---|
| 10 | n! (3.6e6) | permutations, brute force |
| 20 | 2^n · n (2e7) | bitmask DP, subset enumeration |
| 40 | 2^(n/2) · n | meet in the middle |
| 500 | n^3 (1.25e8) | Floyd-Warshall, interval DP |
| 5 000 | n^2 (2.5e7) | pairwise DP, O(n^2) DP |
| 10^6 | n log n (2e7) | sorting, heaps, segment trees, Dijkstra |
| 10^8 | n | linear scans, two pointers, counting sort |
| larger / unbounded | o(n) space | streaming and sketches |

## 2. Recognition catalogue (the classic in disguise)

| Signal in the statement | Classic | Cost |
|---|---|---|
| most non-overlapping meetings | interval scheduling: greedy by earliest finish | O(n log n) |
| fewest rooms/machines so nothing overlaps | interval partitioning: sort starts, min-heap of ends; answer = max depth | O(n log n) |
| weighted non-overlapping selection | weighted interval scheduling DP (section 10) | O(n log n) |
| longest chain, nesting envelopes, increasing subsequence | LIS by patience sorting | O(n log n) |
| fewest edits, diff, alignment, typo tolerance | edit distance / LCS | O(nm) |
| choose items under a capacity | knapsack (pseudo-polynomial) | O(nW) |
| one-to-one assignment of workers to tasks | bipartite matching / assignment | O(E sqrt V) / O(n^3) |
| pick projects with prerequisites; split into two camps with penalties | max-weight closure / min s-t cut | max-flow |
| booleans with pairwise "x or y" constraints | 2-SAT via implication-graph SCCs | O(n + m) |
| cheapest/fastest way from A to B | shortest paths (pick by weights, `graph-algorithms`) | BFS..Dijkstra |
| order tasks with dependencies, detect cycles | topological sort (Kahn) | O(V + E) |
| merge groups, "are x and y connected" with only unions | union-find | O(alpha(n)) amortised |
| events on a line or plane, max overlap, union area | sweep line over sorted events | O(n log n) |
| best contiguous subarray/substring with a monotone property | two pointers / sliding window | O(n) |
| next greater element, largest rectangle in a histogram | monotone stack | O(n) |
| minimise the maximum / maximise the minimum | binary search on the answer with a feasibility check; parametric search | O(check · log range) |

## 3. Paradigm decision table and proof obligations

| Paradigm | Use when | You owe |
|---|---|---|
| Dynamic programming | optimal substructure, overlapping subproblems | state in words, recurrence, topological evaluation order, base cases; cost = #states x transition |
| Greedy | a local choice never needs revisiting | exchange or stays-ahead argument, or a matroid; a failed counterexample search first |
| Divide and conquer | independent parts of a constant fraction of the size | recurrence solved (master theorem / Akra-Bazzi) including combine cost |
| Graph modelling | relations, reachability, dependencies, assignment | explicit vertex/edge meaning, direction, weight sign; certificate checks |
| Backtracking / branch and bound | feasibility or optimisation over a small space | pruning is sound (never cuts a feasible optimum); bound is optimistic |
| Solver (CP-SAT, MILP, SAT, SMT) | hard combinatorics, side constraints change often | encoding size, symmetry breaking, reported gap and time limit |
| Randomisation | simplicity or expected speed (quickselect, hashing, treaps) | expectation and tail bounds; behaviour under adaptive adversaries |
| Streaming / sketches | data exceeds memory, one pass | error eps, failure probability delta, space in bits |
| Online | decisions before the future is known | competitive ratio against the adversary model |
| Parameterised (FPT) | NP-hard but a small parameter k | f(k) poly(n) bound, kernel size |
| Approximation | NP-hard, a guarantee is needed | ratio proof; known inapproximability not violated |
| Preprocessing + queries | many queries over static data | preprocessing vs per-query cost and memory |

## 4. Greedy proofs

Before any proof, search for a counterexample with a brute-force oracle on all small instances:

```python
import itertools, random
def find_counterexample(greedy, brute, gen, trials=20000, seed=1):
    rng = random.Random(seed)
    for _ in range(trials):
        inst = gen(rng)                     # instances with n <= 8 so brute force is exact
        g, b = greedy(inst), brute(inst)
        if g != b:
            return inst, g, b               # most "obvious" greedy rules die here
    return None
```

- **Exchange argument.** Let G = g1, g2, ... be the greedy choices. Take an optimal solution O that
  agrees with G on the longest prefix g1..g(k-1) and differs at step k. Show that replacing O's
  k-th element by gk (and repairing locally) keeps O feasible and no worse. This contradicts the
  maximality of the common prefix, so some optimum extends every greedy prefix.
- **Stays ahead.** Define a measure after each step (e.g. finish time of the r-th selected interval)
  and prove by induction that greedy's measure is at least as good as any solution's after r steps;
  conclude greedy cannot select fewer items. Interval scheduling by earliest finish is the template.
- **Matroid test.** If the feasible sets are hereditary (subsets of feasible sets are feasible) and
  satisfy exchange (|A| < |B| implies some x in B \ A with A + x feasible), then "sort by weight
  descending, add if still feasible" is optimal for max-weight independent set for all weights.
  Graphic matroid gives Kruskal; partition and transversal matroids give scheduling variants. Unit
  jobs with deadlines and profits form a matroid; weighted intervals do not (section 10).

## 5. Divide and conquer and search

Divide and conquer: write T(n) = a T(n/b) + f(n) and solve it before coding; the combine step
usually dominates. Cut to a simple quadratic routine below a measured threshold (insertion sort
below ~16-32 elements, schoolbook below ~30-60 limbs for Karatsuba).

| Classic | Recurrence | Bound |
|---|---|---|
| merge sort with inversion counting (count across halves while merging) | 2T(n/2) + n | O(n log n) |
| closest pair (strip of width 2d sorted by y, at most 7 neighbours checked) | 2T(n/2) + n | O(n log n) |
| median of medians (groups of 5) | T(n/5) + T(7n/10) + n | O(n) worst case |
| Karatsuba | 3T(n/2) + n | O(n^1.585) |
| FFT polynomial/big-integer multiplication | 2T(n/2) + n | O(n log n) |

Search:
- **Backtracking**: order variables by fewest remaining options, prune on infeasibility, memoise
  failed states when they repeat. Pruning is sound only if it never removes every optimum.
- **Branch and bound**: the bound must be optimistic for every completion (an upper bound when
  maximising: e.g. the LP or fractional-knapsack relaxation). A heuristic "bound" turns B&B into
  an unproven heuristic. Seed the incumbent with a greedy solution.
- **Meet in the middle**: split n items in halves, enumerate 2^(n/2) partial results per half, sort
  one side, then binary search or two-pointer merge: O(2^(n/2) n), fine for n <= 40-45.
- **A\***: f = g + h. h admissible (never overestimates) gives optimal answers; h consistent
  (h(u) <= w(u,v) + h(v)) additionally expands each node at most once, like Dijkstra on reduced
  costs. **IDA\***: iterative deepening on f, memory O(depth), for huge implicit state spaces
  (15-puzzle with Manhattan or pattern-database heuristics).

## 6. Hand-off to solvers (2026)

| Problem shape | Tool |
|---|---|
| combinatorial with logical side constraints, scheduling, integer variables | OR-Tools CP-SAT |
| linear objective/constraints with integers | HiGHS (open source), Gurobi (commercial) MILP |
| pure Boolean satisfiability | CaDiCaL, Kissat (via PySAT) |
| arithmetic, bit-vectors, arrays, program verification | Z3, cvc5 (SMT) |
| model once, try several back-ends | MiniZinc |

```python
from ortools.sat.python import cp_model         # weighted independent set in a conflict graph
m = cp_model.CpModel()
x = [m.new_bool_var(f"x{i}") for i in range(n)]
for i, j in conflicts:
    m.add(x[i] + x[j] <= 1)
m.add(x[0] >= x[1])                              # symmetry breaking only if items 0 and 1 are interchangeable
m.maximize(sum(w[i] * x[i] for i in range(n)))
s = cp_model.CpSolver()
s.parameters.max_time_in_seconds = 30.0
s.parameters.num_workers = 8
st = s.solve(m)
gap = abs(s.best_objective_bound - s.objective_value) / max(1.0, abs(s.objective_value))
print(s.status_name(st), s.objective_value, s.best_objective_bound, f"gap={gap:.2%}")
```

Encoding tips: break symmetry (order identical machines or bins), keep big-M as tight as the data
allows (M = the actual maximum, not 10^9; loose M ruins the LP relaxation and causes numerical
trouble), add redundant constraints that strengthen propagation (cumulative plus no-overlap),
prefer interval variables over time-indexed Booleans for scheduling. Always report: solver and
version, time limit, status (OPTIMAL vs FEASIBLE), objective, best bound, gap, seed and workers.

## 7. Workhorse techniques with invariants

- **Prefix sums**: P[0] = 0, P[i+1] = P[i] + a[i]; sum(a[l:r]) = P[r] - P[l] (half-open).
  **Difference array**: add v on [l, r) via D[l] += v, D[r] -= v; prefix-sum D once at the end.
- **Coordinate compression**: `xs = sorted(set(vals)); idx = {v: i for i, v in enumerate(xs)}`;
  keep half-open boundaries so segment lengths are xs[i+1] - xs[i].
- **Sweep line**: events (x, type, payload) sorted by x; at equal x process ends before starts for
  half-open intervals (starts first for closed ones). Invariant: the active structure holds exactly
  the objects intersecting the sweep position.
- **Sliding window minimum** with a monotone deque of indices, values increasing front to back:

```python
from collections import deque
def window_min(a, k):
    dq, out = deque(), []
    for i, x in enumerate(a):
        while dq and a[dq[-1]] >= x: dq.pop()    # invariant: a[dq] strictly increasing
        dq.append(i)
        if dq[0] <= i - k: dq.popleft()          # invariant: dq holds indices in (i-k, i]
        if i >= k - 1: out.append(a[dq[0]])
    return out                                   # O(n): each index pushed and popped once
```

- **Binary search on a monotone predicate** (F...F T...T). Template with an explicit invariant;
  never mix it with other variants:

```python
def first_true(lo, hi, pred):
    """Smallest x in [lo, hi) with pred(x), or hi if none.
    Invariant: pred is False on [orig_lo, lo) and True on [hi, orig_hi)."""
    while lo < hi:
        mid = lo + (hi - lo) // 2       # no overflow in fixed-width languages
        if pred(mid): hi = mid
        else: lo = mid + 1
    return lo
```

  For real-valued answers iterate a fixed count (100 halvings of a double interval) instead of
  comparing with an epsilon.

## 8. Verification loop

1. **Oracle**: an exhaustive brute force that is obviously correct (all subsets, permutations or
   assignments) for n <= 8. Never derive it from the fast algorithm.
2. **Differential testing**: seeded random instances, 10^4 to 10^6 cases, small value ranges so
   ties and collisions occur; compare value and validate the witness independently.
3. **Shrink** the first failure with Hypothesis (Python) or proptest (Rust) to a minimal instance.
4. **Scaling check**: time or count operations at >= 5 sizes over >= 2 decades and fit the log-log
   slope (`numpy.polyfit(np.log(ns), np.log(ts), 1)[0]`): ~1.0-1.15 for n log n, ~2 for n^2.
   Harness mechanics (fixtures, CI budgets) are in `testing-strategy`.

```python
from hypothesis import given, strategies as st
interval = st.tuples(st.integers(0, 20), st.integers(1, 8), st.integers(1, 10)).map(
    lambda t: (t[0], t[0] + t[1], t[2]))
@given(st.lists(interval, max_size=10))
def test_wis_matches_oracle(ivs):
    assert wis(ivs)[0] == brute(ivs)
```

## 9. Pitfalls

- Greedy shipped without a proof or a counterexample search; "it passed the examples" is not one.
- Integer overflow: sums of 10^5 values up to 10^9 exceed 32 bits; use int64 (or checked/i128
  arithmetic), and in C++ write `1LL * a * b`.
- Recursion depth: CPython's default limit is 1000 frames; go iterative or use an explicit stack
  (raising the limit risks a C-stack crash).
- Comparators that are not strict weak orderings (`<=`, inconsistent tie-breaks, NaN keys) give
  undefined behaviour in `std::sort` and exceptions in Java's TimSort.
- Floating-point geometry predicates: use exact integer orientation tests
  (cross product in int64/int128) or state an explicit epsilon policy.
- Binary search on a predicate that is not monotone; off-by-one from mixing closed and half-open
  bounds.

## 10. Worked example: weighted interval scheduling

Input: half-open intervals (s, e, w) with s < e. Maximise the total weight of pairwise disjoint
intervals.

**Greedy fails.** Earliest finish picks A = [0,2) w=1, then C = [3,5) w=1: total 2. The optimum is
B = [1,4) w=5 alone, which overlaps both. Weighted intervals are not a matroid (adding a heavy
interval can require removing two light ones), so no greedy order is safe.

**DP.** Sort by end. p(j) = number of intervals that end no later than interval j starts (binary
search in the sorted ends). OPT(j) = max(OPT(j-1), w_j + OPT(p(j))), OPT(0) = 0. Optimal
substructure by cut-and-paste: if interval j is in an optimum, the rest of that optimum is an
optimum over the first p(j) intervals. Cost: O(n log n) for sorting and p, O(n) for the table.

```python
import bisect
def wis(intervals):
    order = sorted(range(len(intervals)), key=lambda i: intervals[i][1])
    iv = [intervals[i] for i in order]
    ends = [e for _, e, _ in iv]
    n = len(iv)
    p = [bisect.bisect_right(ends, iv[j][0], 0, j) for j in range(n)]
    opt = [0] * (n + 1)                          # opt[j]: best over the first j intervals
    for j in range(1, n + 1):
        opt[j] = max(opt[j - 1], iv[j - 1][2] + opt[p[j - 1]])
    chosen, j = [], n                            # reconstruct by re-walking the table
    while j > 0:
        if iv[j - 1][2] + opt[p[j - 1]] >= opt[j - 1]:
            chosen.append(order[j - 1]); j = p[j - 1]
        else:
            j -= 1
    return opt[n], sorted(chosen)

def brute(intervals):                            # 2^n oracle
    n, best = len(intervals), 0
    for mask in range(1 << n):
        sel = sorted((intervals[i] for i in range(n) if mask >> i & 1), key=lambda t: t[0])
        if all(a[1] <= b[0] for a, b in zip(sel, sel[1:])):
            best = max(best, sum(w for _, _, w in sel))
    return best
```

Differential test (run for this skill: 3 000 seeded instances, n <= 12, all agree; the
counterexample gives greedy 2 vs `wis` 5 with chosen = [1]):

```python
import random
rng = random.Random(20261019)
for _ in range(3000):
    ivs = []
    for _ in range(rng.randint(0, 12)):
        s = rng.randint(0, 20); ivs.append((s, s + rng.randint(1, 8), rng.randint(1, 10)))
    val, idx = wis(ivs)
    sel = sorted((ivs[i] for i in idx), key=lambda t: t[0])
    assert all(a[1] <= b[0] for a, b in zip(sel, sel[1:]))      # witness is feasible
    assert sum(ivs[i][2] for i in idx) == val == brute(ivs)      # and optimal
```

Notes: `bisect_right(..., hi=j)` treats touching intervals ([0,2) and [2,3)) as compatible, which
is the half-open semantics; for closed intervals use `bisect_left` on ends with start. Zero-length
intervals break the "earlier in end order" assumption: reject them or order ties by start.

Related: `dynamic-programming-patterns`, `graph-algorithms`, `amortized-recurrence-analysis`, `np-hardness-reductions`, `randomized-algorithms-sketches`, `data-structure-selection`, `string-algorithms`, `testing-strategy`, hub `cs-foundations`
