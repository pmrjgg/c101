# Reviewer assignment: full code, oracle and cross-check

Companion to section 10 of the graph-algorithms skill. Everything except the OR-Tools block was run
as shown (CPython 3, standard library only): 1 500 seeded instances, all assertions pass, 758
feasible and 742 infeasible.

## 1. Dinic max-flow with min-cut side

```python
import heapq, itertools, random
from collections import deque

class Dinic:
    """Edges are [to, residual_cap, rev_index]; add() returns a handle (u, i)."""
    def __init__(self, n):
        self.n, self.g = n, [[] for _ in range(n)]
    def add(self, u, v, cap):
        self.g[u].append([v, cap, len(self.g[v])])
        self.g[v].append([u, 0, len(self.g[u]) - 1])
        return u, len(self.g[u]) - 1
    def _bfs(self, s, t):
        self.level = [-1] * self.n; self.level[s] = 0
        q = deque([s])
        while q:
            u = q.popleft()
            for v, cap, _ in self.g[u]:
                if cap > 0 and self.level[v] < 0:
                    self.level[v] = self.level[u] + 1; q.append(v)
        return self.level[t] >= 0
    def _dfs(self, u, t, f):                 # recursion depth = BFS distance to t (3 here)
        if u == t: return f
        while self.it[u] < len(self.g[u]):
            e = self.g[u][self.it[u]]
            if e[1] > 0 and self.level[e[0]] == self.level[u] + 1:
                d = self._dfs(e[0], t, min(f, e[1]))
                if d:
                    e[1] -= d; self.g[e[0]][e[2]][1] += d
                    return d
            self.it[u] += 1
        return 0
    def max_flow(self, s, t):
        flow = 0
        while self._bfs(s, t):
            self.it = [0] * self.n
            while (f := self._dfs(s, t, float("inf"))):
                flow += f
        return flow
    def source_side(self, s):
        seen = [False] * self.n; seen[s] = True; q = deque([s])
        while q:
            u = q.popleft()
            for v, cap, _ in self.g[u]:
                if cap > 0 and not seen[v]: seen[v] = True; q.append(v)
        return seen
```

For long augmenting paths (general graphs, deep level graphs) replace the recursive `_dfs` with an
explicit stack.

## 2. Min-cost flow by successive shortest paths

```python
class MinCostFlow:
    """Successive shortest paths with Johnson potentials; initial arc costs must be >= 0."""
    def __init__(self, n):
        self.n, self.g = n, [[] for _ in range(n)]
    def add(self, u, v, cap, cost):
        self.g[u].append([v, cap, cost, len(self.g[v])])
        self.g[v].append([u, 0, -cost, len(self.g[u]) - 1])
        return u, len(self.g[u]) - 1
    def flow(self, s, t, want):
        INF, h, f, total = float("inf"), [0] * self.n, 0, 0
        while f < want:
            dist, prev, pq = [INF] * self.n, [None] * self.n, [(0, s)]
            dist[s] = 0
            while pq:
                d, u = heapq.heappop(pq)
                if d > dist[u]: continue
                for i, (v, cap, c, _) in enumerate(self.g[u]):
                    nd = d + c + h[u] - h[v]         # reduced cost, >= 0 by the potentials
                    if cap > 0 and nd < dist[v]:
                        dist[v], prev[v] = nd, (u, i); heapq.heappush(pq, (nd, v))
            if dist[t] == INF: break                 # no augmenting path: max flow reached
            for v in range(self.n):
                if dist[v] < INF: h[v] += dist[v]
            push, v = want - f, t
            while v != s:
                u, i = prev[v]; push = min(push, self.g[u][i][1]); v = u
            v = t
            while v != s:
                u, i = prev[v]; e = self.g[u][i]
                e[1] -= push; self.g[v][e[3]][1] += push; v = u
            f += push; total += push * (h[t] - h[s])
        return f, total
```

Negative initial costs: initialise `h` with one Bellman-Ford pass from s, or add a constant to
every reviewer-to-paper arc (every full assignment uses exactly k * P of them, so the optimum
is unchanged).

## 3. Model, checks and oracle

```python
def assign(R, P, load, k, conflicts, cost=None):
    """Reviewers 0..R-1, papers R..R+P-1, s = R+P, t = R+P+1. With cost: min-cost flow."""
    s, t, need = R + P, R + P + 1, k * P
    G = MinCostFlow(R + P + 2) if cost else Dinic(R + P + 2)
    arc = (lambda u, v, c, w: G.add(u, v, c, w)) if cost else (lambda u, v, c, w: G.add(u, v, c))
    for r in range(R): arc(s, r, load[r], 0)
    h = {(r, p): arc(r, R + p, 1, cost[r][p] if cost else 0)
         for r in range(R) for p in range(P) if (r, p) not in conflicts}
    for p in range(P): arc(R + p, t, k, 0)
    value = G.flow(s, t, need) if cost else (G.max_flow(s, t), None)
    pairs = sorted(rp for rp, (u, i) in h.items() if G.g[u][i][1] == 0)
    return value, pairs, G

def check(R, P, load, k, conflicts, pairs, flow):
    per_r = [sum(1 for r, _ in pairs if r == x) for x in range(R)]
    per_p = [sum(1 for _, p in pairs if p == y) for y in range(P)]
    assert all(per_r[r] <= load[r] for r in range(R))              # reviewer capacity
    assert all(per_p[p] <= k for p in range(P))                    # paper capacity
    assert not set(pairs) & set(conflicts) and len(pairs) == flow  # conservation at s and t

def brute(R, P, load, k, conflicts, cost):
    """Exhaustive oracle: min cost over all edge subsets meeting every constraint, or None."""
    elig = [(r, p) for r in range(R) for p in range(P) if (r, p) not in conflicts]
    best = None
    for m in range(1 << len(elig)):
        sel = [elig[i] for i in range(len(elig)) if m >> i & 1]
        if all(sum(1 for _, p in sel if p == y) == k for y in range(P)) and \
           all(sum(1 for r, _ in sel if r == x) <= load[x] for x in range(R)):
            c = sum(cost[r][p] for r, p in sel)
            best = c if best is None else min(best, c)
    return best
```

## 4. Differential test (run)

```python
rng = random.Random(11)
feas = infeas = 0
for _ in range(1500):
    R, P, k = rng.randint(1, 4), rng.randint(1, 3), rng.randint(1, 2)
    load = [rng.randint(0, 3) for _ in range(R)]
    conflicts = {(r, p) for r in range(R) for p in range(P) if rng.random() < 0.25}
    cost = [[rng.randint(0, 4) for _ in range(P)] for _ in range(R)]
    (f, _), pairs, D = assign(R, P, load, k, conflicts)
    check(R, P, load, k, conflicts, pairs, f)
    S = D.source_side(R + P)                                  # certificate: cut == flow
    cut = sum(load[r] for r in range(R) if not S[r]) \
        + sum(1 for r in range(R) for p in range(P)
              if S[r] and not S[R + p] and (r, p) not in conflicts) \
        + sum(k for p in range(P) if S[R + p])
    assert cut == f
    want = brute(R, P, load, k, conflicts, cost)
    (f2, c2), pairs2, _ = assign(R, P, load, k, conflicts, cost)
    check(R, P, load, k, conflicts, pairs2, f2)
    assert f2 == f
    if want is None:
        assert f < k * P; infeas += 1
    else:
        assert f == k * P and c2 == want == sum(cost[r][p] for r, p in pairs2); feas += 1
print("flow ok", feas, "feasible", infeas, "infeasible")   # -> flow ok 758 feasible 742 infeasible
```

## 5. OR-Tools cross-check for larger instances (not run here)

Uses the bulk API from the OR-Tools min-cost-flow guide. Run it in CI where `ortools` and `numpy`
are installed; compare the optimal cost with the SSP result for seeded instances of R = 50,
P = 120, k = 3.

```python
import numpy as np
from ortools.graph.python import min_cost_flow

def ortools_cost(R, P, load, k, conflicts, cost):
    s, t = R + P, R + P + 1
    tails, heads, caps, costs = [], [], [], []
    def arc(u, v, c, w): tails.append(u); heads.append(v); caps.append(c); costs.append(w)
    for r in range(R): arc(s, r, load[r], 0)
    for r in range(R):
        for p in range(P):
            if (r, p) not in conflicts: arc(r, R + p, 1, cost[r][p])
    for p in range(P): arc(R + p, t, k, 0)
    smcf = min_cost_flow.SimpleMinCostFlow()
    smcf.add_arcs_with_capacity_and_unit_cost(np.array(tails), np.array(heads),
                                              np.array(caps), np.array(costs))
    supplies = np.zeros(R + P + 2, dtype=np.int64); supplies[s], supplies[t] = k * P, -k * P
    smcf.set_nodes_supplies(np.arange(R + P + 2), supplies)
    status = smcf.solve()
    return smcf.optimal_cost() if status == smcf.OPTIMAL else None   # None: infeasible
```

Expected agreement: `ortools_cost(...) == assign(..., cost)[0][1]` whenever the instance is
feasible, and `None` exactly when Dinic's flow is below k * P.
