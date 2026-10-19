# Complexity classes and reduction catalogue

## 1. Classes you will be asked about

| Class | Definition (informal) | Complete problems |
|---|---|---|
| P | deterministic polynomial time | circuit value, linear programming, Horn-SAT (P-complete under log-space reductions: unlikely to parallelise well) |
| NP | polynomial-time verifiable certificates | SAT, 3-SAT, clique, vertex cover, Hamiltonian cycle, subset sum, 3-colouring |
| coNP | complements of NP | tautology (UNSAT), checking that a graph is NOT 3-colourable |
| NP ∩ coNP | short certificates both ways | factoring (decision version), parity games, (also in UP ∩ coUP) |
| #P | counting accepting paths | #SAT, permanent of 0/1 matrices, counting perfect matchings |
| PSPACE | polynomial space | QBF (TQBF), generalised geography, many two-player games of polynomial length |
| EXPTIME | exponential time | generalised chess/go (with appropriate rules) |
| BPP / RP / ZPP | randomised polynomial time with bounded error / one-sided / zero error | polynomial identity testing (in coRP, not known in P) |
| BQP | quantum polynomial time, bounded error | factoring and discrete log are in BQP |
| L / NL | logarithmic space / nondeterministic | undirected reachability ∈ L (Reingold), directed reachability NL-complete |

Known: P ⊆ NP ⊆ PSPACE ⊆ EXPTIME, P ≠ EXPTIME (time hierarchy), NL ⊆ P, NL = coNL
(Immerman-Szelepcsényi), PSPACE = NPSPACE (Savitch). Open: P vs NP, NP vs coNP, P vs PSPACE,
BPP vs P (widely believed equal).

## 2. Source problems for NP-hardness reductions

| Source | Variant notes | Good for reducing to |
|---|---|---|
| 3-SAT | each clause exactly 3 literals; planar 3-SAT; (3,B2)-SAT bounded occurrences | anything with local constraints, gadget-based puzzles, planar graph problems |
| NAE-3-SAT / 1-in-3-SAT | symmetric / exact constraints | partition-like and hypergraph colouring problems |
| Vertex cover / independent set / clique | cubic or planar versions remain NP-hard | covering, packing, conflict graphs |
| 3-colouring | planar, max degree 4 still NP-hard | frequency assignment, register allocation with constraints |
| Hamiltonian cycle / path | cubic planar still NP-hard | routing, TSP, sequencing |
| Subset sum / Partition | weakly NP-hard (pseudo-polynomial DP) | knapsack, 2-machine scheduling, load balancing with numbers |
| 3-Partition | strongly NP-hard | bin packing, scheduling with numbers encoded in unary |
| Set cover / exact cover (X3C) | X3C convenient for exact structures | facility location, test selection, tiling |
| Max-cut | NP-hard, 0.878 approx (GW) | clustering, partitioning with weights |
| Steiner tree | NP-hard in graphs and plane | network design |
| Dominating set | W[2]-hard parameterised | placement problems |
| Clique (parameterised) | W[1]-hard | to show no FPT algorithm likely exists |

Reduction gadget checklist:
- Variable gadget forces a binary choice; clause gadget is satisfiable iff one literal gadget is
  in the true state; connections preserve degrees and planarity if the target needs them.
- Prove the backward direction by extracting an assignment from ANY solution of the target,
  including weird ones the gadget designer did not intend.
- Count: size of f(y) polynomial; numbers polynomially bounded if claiming strong hardness.

## 3. Hardness of approximation and parameterised hardness

| Problem | Best known approximation | Hardness |
|---|---|---|
| Vertex cover | 2 | 2 - ε under UGC; √2 - ε unconditional (2-to-2 games theorem) |
| Set cover | H_n ≈ ln n (greedy) | (1 - ε) ln n unless P = NP |
| Max-3SAT | 7/8 (random assignment) | 7/8 + ε NP-hard (Håstad) |
| Max-cut | 0.878 (Goemans-Williamson) | optimal under UGC |
| Metric TSP | 1.5 (Christofides-Serdyukov), marginally below since 2020 | 123/122 NP-hard |
| Euclidean TSP | PTAS (Arora, Mitchell) | - |
| Bin packing | asymptotic PTAS; First Fit Decreasing 11/9 OPT + 6/9 | 3/2 - ε absolute (from Partition) |
| Knapsack | FPTAS | - |
| Max clique / independent set | n / polylog | n^(1-ε) |
| k-center | 2 | 2 - ε |

Parameterised: FPT (f(k) n^O(1)), W[1]-hard (clique, independent set by solution size),
W[2]-hard (dominating set, set cover). ETH: 3-SAT has no 2^(o(n)) algorithm. SETH: k-SAT needs
2^((1-ε_k)n) with ε_k → 0.

## 4. Fine-grained conjectures and their consequences

| Conjecture | Statement | Consequences (conditional lower bounds) |
|---|---|---|
| SETH | for every ε > 0 there is k with k-SAT not in O(2^((1-ε)n)) | orthogonal vectors n^(2-o(1)); edit distance, LCS, DTW n^(2-o(1)); (3/2 - ε)-approximate diameter in sparse graphs needs n^(2-o(1)) (a 3/2-approx exists in Õ(m√n)) |
| 3SUM | no O(n^(2-ε)) for 3SUM | collinear points, polygon containment, some dynamic graph problems |
| APSP | no O(n^(3-ε)) for all-pairs shortest paths (real weights) | negative triangle, radius, median, replacement paths |
| OMv | online matrix-vector multiplication needs n^(3-o(1)) | dynamic graph data structures |
| Boolean matrix multiplication (combinatorial) | no combinatorial n^(3-ε) | triangle detection, CFG parsing (Valiant / Lee) |

Use them to justify "a quadratic algorithm is likely optimal" and to stop teams from chasing
impossible improvements; state that the bound is conditional.

## 5. Recurrences cheat sheet

| Recurrence | Solution |
|---|---|
| T(n) = T(n-1) + O(1) | O(n) |
| T(n) = T(n-1) + O(n) | O(n²) |
| T(n) = 2T(n-1) + O(1) | O(2^n) |
| T(n) = T(n/2) + O(1) | O(log n) |
| T(n) = T(n/2) + O(n) | O(n) |
| T(n) = 2T(n/2) + O(1) | O(n) |
| T(n) = 2T(n/2) + O(n) | O(n log n) |
| T(n) = 2T(n/2) + O(n log n) | O(n log² n) |
| T(n) = T(√n) + O(1) | O(log log n) |
| T(n) = T(n/3) + T(2n/3) + O(n) | O(n log n) |
| T(n) = T(n/5) + T(7n/10) + O(n) | O(n) (median of medians) |

Akra-Bazzi: T(n) = Σ a_i T(b_i n) + g(n); find p with Σ a_i b_i^p = 1; then
T(n) = Θ(n^p (1 + ∫_1^n g(u)/u^(p+1) du)).

## 6. Useful polynomial-time results to recognise

| Problem | Algorithm | Complexity |
|---|---|---|
| Shortest paths, non-negative weights | Dijkstra with binary heap | O((V + E) log V) |
| Shortest paths, negative weights | Bellman-Ford; Johnson for all pairs | O(VE); O(VE + V² log V) |
| Max flow / min cut | Dinic, push-relabel; almost-linear time theoretically (Chen et al. 2022) | O(V² E) Dinic worst case, much faster in practice |
| Bipartite matching | Hopcroft-Karp | O(E sqrt(V)) |
| General matching | Edmonds' blossom (Micali-Vazirani) | O(E sqrt(V)) |
| Assignment (weighted bipartite) | Hungarian | O(V³) |
| Min-cost flow | successive shortest paths, cost scaling | polynomial |
| 2-SAT | implication graph SCC | O(n + m) |
| Linear programming | simplex (fast in practice), interior point (polynomial) | - |
| Minimum spanning tree | Kruskal / Prim / Borůvka | O(E log V) |
| Strongly connected components | Tarjan / Kosaraju | O(V + E) |
| Planarity testing | Hopcroft-Tarjan, Boyer-Myrvold | O(V) |
| Graph isomorphism | quasi-polynomial (Babai 2015); practical: nauty/Traces | - |
| Primality | AKS (deterministic polynomial); Miller-Rabin in practice | - |
| Treewidth-bounded graphs | many NP-hard problems in O(f(tw) n) via DP (Courcelle for MSO) | - |
