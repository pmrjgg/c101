---
name: graph-algorithms
description: "Graph modelling and algorithm choice: representations, traversal and ordering (BFS, DFS, topological sort, SCC, bridges, 2-SAT), shortest paths (0-1 BFS, Dijkstra, Bellman-Ford, Johnson, Floyd-Warshall, A*), MST, max-flow/min-cut, matching, assignment, libraries (NetworkX, rustworkx, igraph, graph-tool, scipy.csgraph, OR-Tools, petgraph, BGL) and certificate checks. Load for dependency, routing, reachability, assignment or capacity problems."
when_to_use: "Build/task dependency ordering or cycle reports; routing and shortest-path queries; 'can every X get a Y' assignment or allocation with capacities; matching, scheduling with conflicts, project selection with prerequisites; picking a graph library for 10^5..10^9 edges; Dijkstra/BFS code review; a flow or matching result nobody can verify."
---

# Graph algorithms

Model first, then pick the algorithm from the weights and the question, then check a certificate.
Paradigm choice is in `algorithm-design-paradigms`, representation costs in
`data-structure-selection`; hub `cs-foundations` section 1. Full worked-example code with the oracle
and the OR-Tools cross-check: [reviewer assignment](references/reviewer-assignment.md).

## 1. Modelling step

1. What is a vertex (entity, state, time-expanded copy) and what is an edge (relation, move,
   capacity)? Write it in one sentence each.
2. Directed? Weight sign and range (negative? integer up to 10^9? floating?). Multi-edges and
   self-loops allowed?
3. Implicit (grid, puzzle states, product graphs: generate neighbours on the fly) or materialised?
4. Pick the representation from V and E:

| Graph | Representation | Why |
|---|---|---|
| large, static, sparse | CSR (offsets + targets arrays) | 2 arrays, cache-friendly scans, 4-8 bytes per edge |
| dynamic, sparse | adjacency lists (vector per vertex) | O(1) amortised edge insert |
| dense, V up to ~10^4 | bitset adjacency matrix (V^2 / 8 bytes: 12.5 MB at 10^4) | O(1) edge test, word-parallel set ops |
| Kruskal, streaming, I/O | edge list | sortable, no per-vertex structure |
| unions + "connected?" only | union-find | O(alpha(n)) amortised, no edges kept |

## 2. Shortest paths: decision table

| Situation | Algorithm | Cost |
|---|---|---|
| unweighted | BFS | O(V + E) |
| weights in {0, 1} | 0-1 BFS with a deque | O(V + E) |
| non-negative weights | Dijkstra, binary heap, lazy deletion | O((V + E) log V) |
| negative edges, no negative cycle expected | Bellman-Ford; V-th round still relaxing = negative cycle | O(VE) |
| same, "faster in practice" | SPFA (queue Bellman-Ford): same O(VE) worst case, adversarial inputs hit it | O(VE) |
| DAG (any signs) | relax in topological order | O(V + E) |
| all pairs, dense or V <= ~500 | Floyd-Warshall; d[i][i] < 0 flags a negative cycle | O(V^3) |
| all pairs, sparse, negative edges | Johnson: Bellman-Ford potentials, then V Dijkstras on w + h(u) - h(v) | O(VE log V) |
| single pair with a good heuristic | A* (admissible h), bidirectional Dijkstra | output-sensitive |
| road networks, many queries | contraction hierarchies (OSRM, RoutingKit) | preprocessing, then sub-millisecond-scale queries |

```python
import heapq
from collections import deque
INF = float("inf")

def dijkstra(adj, s):                       # adj[u] = [(v, w)], all w >= 0
    dist, parent, pq = [INF] * len(adj), [-1] * len(adj), [(0, s)]
    dist[s] = 0
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]: continue            # stale heap entry: lazy deletion
        for v, w in adj[u]:
            if d + w < dist[v]:
                dist[v], parent[v] = d + w, u
                heapq.heappush(pq, (d + w, v))
    return dist, parent

def zero_one_bfs(adj, s):                   # weights 0 or 1
    dist, dq = [INF] * len(adj), deque([s])
    dist[s] = 0
    while dq:
        u = dq.popleft()
        for v, w in adj[u]:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                (dq.appendleft if w == 0 else dq.append)(v)
    return dist
```

## 3. Structure algorithms

| Question | Algorithm | Notes |
|---|---|---|
| order with dependencies; report a cycle | Kahn (in-degree queue) | leftover vertices with in-degree > 0 lie on or behind a cycle |
| mutual reachability, condensation | Tarjan (one pass) or Kosaraju (two passes) | condensation is a DAG; DP over it |
| boolean pairs (a or b) | 2-SAT: implication graph, SCC | unsatisfiable iff x and not-x share an SCC |
| single points of failure | bridges and articulation points via low-link | tree edge (u,v) is a bridge iff low[v] > tin[u]; non-root u is a cut vertex iff some child has low[v] >= tin[u]; root iff >= 2 children |
| traverse every edge once | Hierholzer, O(E) | edges connected; undirected: 0 or 2 odd-degree vertices; directed: in = out except start/end |
| two-colourable? | BFS 2-colouring | an edge inside one colour class closes an odd cycle (certificate) |
| ancestor queries | LCA: binary lifting O(log n) per query, or Euler tour + sparse table O(1) | O(n log n) preprocessing |

```python
def kahn(n, edges):
    adj, indeg = [[] for _ in range(n)], [0] * n
    for u, v in edges:
        adj[u].append(v); indeg[v] += 1
    q, order = deque(v for v in range(n) if indeg[v] == 0), []
    while q:
        u = q.popleft(); order.append(u)
        for v in adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0: q.append(v)
    blocked = [v for v in range(n) if indeg[v] > 0]   # non-empty iff there is a cycle
    return order, blocked
```

2-SAT encoding: literal x_i is node 2i, not-x_i is 2i+1; clause (a or b) adds edges
not-a -> b and not-b -> a. Tarjan numbers SCCs in reverse topological order, so set
x_i = true iff comp[2i] < comp[2i+1]. Use iterative DFS for Tarjan and low-link above ~10^4 depth.

## 4. Minimum spanning trees

| Algorithm | Cost | Use |
|---|---|---|
| Kruskal + union-find | O(E log E) | edge lists, sparse graphs, also gives a minimum spanning forest |
| Prim + binary heap | O(E log V) | adjacency lists, dense-ish graphs (O(V^2) array version for complete graphs) |
| Boruvka | O(E log V), log V rounds | parallel, distributed and external-memory settings |

Proof tools: **cut property** (the lightest edge crossing any cut is in some MST; in every MST if it
is strictly lightest) and **cycle property** (a strictly heaviest edge on a cycle is in no MST).
The MST path between u and v is a minimum bottleneck path (minimises the maximum edge), so
"widest/narrowest path" queries reduce to MST plus LCA with path maxima.

## 5. Flow modelling cookbook

| Algorithm | Bound | Use |
|---|---|---|
| Dinic | O(V^2 E); O(E sqrt V) on unit networks (bipartite matching) | default for sparse graphs |
| push-relabel, highest label + gap heuristic | O(V^2 sqrt E) | dense graphs, large capacities |
| min-cost flow: successive shortest paths with potentials | O(F E log V) for flow value F | small F, assignment-like models |
| network simplex / cost scaling | fast in practice on large instances | large min-cost flow (OR-Tools SimpleMinCostFlow, LEMON) |

Min cut: after max flow, the vertices reachable from s in the residual graph form the source
side S; saturated edges from S to V \ S form a minimum cut of capacity = max-flow value.

| Need | Construction |
|---|---|
| vertex capacity c(v) | split v into v_in -> v_out with capacity c(v) |
| many sources/sinks | super source to each source, each sink to super sink |
| lower bounds l(e) on edges | capacity c - l; move l into node demands; add t -> s with infinite capacity; feasible iff the auxiliary max flow saturates every demand edge |
| project selection / max-weight closure | s -> v capacity p(v) for profit, v -> t capacity -p(v) for cost, u -> v infinite when u requires v; profit = sum of positive p - min cut; chosen set = S \ {s} |
| k edge-disjoint paths (Menger) | unit capacities; max flow = number of disjoint paths |
| b-matching (each left vertex up to a_i, each right up to b_j) | s -> left capacity a_i, left -> right capacity 1, right -> t capacity b_j |

## 6. Matching and assignment

| Problem | Algorithm / call | Cost |
|---|---|---|
| maximum bipartite matching | Hopcroft-Karp (or Dinic on the unit network) | O(E sqrt V) |
| min vertex cover, bipartite | Konig: size = max matching; extract from the residual graph | O(E sqrt V) |
| weighted assignment (dense cost matrix) | `scipy.optimize.linear_sum_assignment` (Jonker-Volgenant style) | O(n^3) |
| sparse weighted bipartite | `scipy.sparse.csgraph.min_weight_full_bipartite_matching`, or min-cost flow | |
| general graph matching (odd cycles) | Edmonds blossom: `networkx.max_weight_matching` | O(V^3) |
| stable matching with preferences | Gale-Shapley; proposer-optimal | O(n^2) |

Konig cover extraction: from every unmatched left vertex, search alternating paths (left to right
on non-matching edges, right to left on matching edges); with Z the visited set, the cover is
(L \ Z) union (R intersect Z), and its size equals the matching size, which certifies both.

## 7. Library cheat sheet (2026)

| Library | Core | Practical scale | Notes |
|---|---|---|---|
| NetworkX | pure Python | ~10^5 edges | richest API; the reference oracle for tests |
| rustworkx | Rust | 10^7+ edges | NetworkX-like API, integer node indices |
| igraph (python-igraph, R) | C | 10^7-10^8 edges | community detection, layouts |
| graph-tool | C++ (Boost) | 10^8-10^9 edges | conda install; property maps; parallel algorithms |
| NetworKit | C++ with OpenMP | 10^8-10^9 edges | parallel analytics (centrality, communities) |
| scipy.sparse.csgraph | C/Cython on CSR | 10^7+ edges | `shortest_path`, `maximum_flow`, `min_weight_full_bipartite_matching`, `connected_components` |
| OR-Tools | C++ | 10^7 arcs | `SimpleMaxFlow`, `SimpleMinCostFlow`, linear assignment, routing |
| petgraph | Rust | memory bound | `Graph`, `StableGraph`, `Csr`; Dijkstra, SCC, MST, matching |
| Boost.Graph (BGL) | C++ templates | memory bound | generic algorithms; compressed_sparse_row_graph |
| cuGraph (RAPIDS) | CUDA | 10^9 edges on GPUs | BFS, PageRank, Louvain on GPU dataframes |

## 8. Certificate checks instead of trusting output

| Output | Check (all linear time) |
|---|---|
| shortest-path distances d | d[s] = 0; d[v] <= d[u] + w(u,v) for every edge; equality on every parent edge |
| max flow f | capacity 0 <= f(e) <= c(e); conservation at every vertex except s, t; value = capacity of the residual-reachability cut |
| bipartite matching M | edges disjoint; size = size of the Konig cover from section 6 |
| topological order | position[u] < position[v] for every edge (u, v) |
| MST | spanning, V - 1 edges; cycle property for every non-tree edge (needs path maxima) |
| no path / infeasible | the reachable set or the min cut itself |

## 9. Pitfalls

- Dijkstra with a negative edge returns wrong distances without any error; assert w >= 0.
- `INF + w` overflow in fixed-width integers: use INF = 2^62 and skip relaxations from INF.
- Recursive DFS overflows: CPython stops at 1000 frames by default, C++ with an 8 MB stack dies
  somewhere around 10^5-10^6 depth (frame size dependent); path graphs with 10^6 vertices hit
  both. Use an explicit stack.
- Marking visited on pop in BFS enqueues a vertex many times; mark on push. In Dijkstra the
  opposite holds: a vertex is final on pop, never on push.
- Undirected edges stored once (missing the reverse arc), or twice in flow networks where one arc
  plus its residual twin is needed per direction.
- Parallel and anti-parallel edges in flow networks: keep each as its own arc with its own
  residual; never merge u->v with v->u.
- Floating-point capacities or weights: scale to integers, or compare with an explicit epsilon;
  Dinic can loop on tiny residuals.

## 10. Worked example: reviewer assignment

Papers need k reviews each, reviewer r takes at most load[r] papers, conflicts of interest forbid
pairs, preferences give costs. Model as a b-matching:

```
s --load[r]--> reviewer r --1 (no conflict)--> paper p --k--> t
```

Feasible iff max flow = k * P. For preferences put cost[r][p] on the middle arcs and solve
min-cost flow with supply k * P at s (OR-Tools `SimpleMinCostFlow` or the SSP code in the
reference). Dinic is in [the reference](references/reviewer-assignment.md); the model:

```python
def assign(R, P, load, k, conflicts):        # reviewers 0..R-1, papers R..R+P-1
    s, t = R + P, R + P + 1
    G = Dinic(R + P + 2)
    for r in range(R): G.add(s, r, load[r])
    arcs = {(r, p): G.add(r, R + p, 1)
            for r in range(R) for p in range(P) if (r, p) not in conflicts}
    for p in range(P): G.add(R + p, t, k)
    f = G.max_flow(s, t)
    pairs = sorted(rp for rp, (u, i) in arcs.items() if G.g[u][i][1] == 0)  # saturated
    return f, pairs, G

def shortage_certificate(R, P, load, k, conflicts, G):
    S = G.source_side(R + P)                 # residual reachability from s
    cut = (sum(load[r] for r in range(R) if not S[r])
           + sum(1 for r in range(R) for p in range(P)
                 if S[r] and not S[R + p] and (r, p) not in conflicts)
           + sum(k for p in range(P) if S[R + p]))
    short = [p for p in range(P) if not S[R + p]]   # deficient paper set X
    supply = cut - k * (P - len(short))             # most reviews X can ever receive
    return cut, short, supply                       # infeasible iff supply < k * len(short)
```

When f < k * P, report the cut instead of "infeasible": its capacity equals f (strong duality).
X = papers unreachable from s in the residual graph contains every under-reviewed paper. X needs
k |X| reviews, but the reviewers unreachable from s are already at full load and every eligible
pair from a reachable reviewer into X is already used, so X can receive at most
supply = f - k (P - |X|) < k |X|. The report names the papers and the exhausted reviewer pool,
and the shortfall k P - f says how many extra review slots to recruit.

Verification run for this skill (seeded, 1 500 random instances, R <= 4, P <= 3, k <= 2, loads
0-3, 25% conflicts, costs 0-4): per-reviewer load, per-paper count, conflict exclusion and
|pairs| = flow hold on every instance; cut capacity = flow on every instance; every
under-reviewed paper lies in X and supply < k |X| exactly when f < k * P; max-flow
feasibility matched an exhaustive subset-enumeration oracle (758 feasible, 742 infeasible) and the
min-cost flow cost equalled the oracle's optimum on all 758 feasible ones. The OR-Tools cross-check
for larger seeded instances is in the reference (not executed in the authoring environment, where
OR-Tools was not installed).

At conference scale (R = 2 000, P = 10 000, k = 3, ~2 x 10^7 eligible pairs) the middle layer
dominates memory: prune to each paper's top-m bids or affinities before building the graph, and
use OR-Tools or a C++ solver rather than Python Dinic.

Related: `algorithm-design-paradigms`, `data-structure-selection`, `dynamic-programming-patterns`, `np-hardness-reductions`, `amortized-recurrence-analysis`, hub `cs-foundations`
