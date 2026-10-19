---
name: graph-theory-probabilistic-method
description: "Graph theory and the probabilistic method for proofs and counterexamples: core theorems with exact hypotheses, extremal and Ramsey results, spectral graph theory, first and second moment, alteration, the Lovasz Local Lemma, random-graph thresholds, derandomization, exhaustive checks with nauty and networkx, and checkable certificates. Load for existence, extremal or structural claims about graphs and combinatorial objects."
when_to_use: "Prove or refute a claim about graphs (matchings, colourings, connectivity, planarity, Hamiltonicity, extremal edge counts, Ramsey numbers); show an object exists by a random construction (first or second moment, alteration, Local Lemma) or derandomize it; find thresholds in G(n,p); compute spectra or spanning-tree counts; or check a conjecture over all small graphs with geng and networkx."
---

# Graph theory and the probabilistic method

Graph claims usually fail on a forgotten hypothesis: simple, connected, finite, undirected.
Probabilistic existence proofs usually fail on arithmetic or on hidden dependencies. Check every
graph claim over all small graphs, and return a certificate the reader can verify in linear time
(section 10).

Notation: n vertices, e edges, δ and Δ the minimum and maximum degree, #S the size of a set S.

## 1. Theorems with their hypotheses

| Theorem | Statement | Hypotheses that matter |
|---|---|---|
| Handshake | Σ deg v = 2e, so the number of odd-degree vertices is even | finite; a loop counts 2 |
| Euler | a graph whose edges lie in one component has an Euler circuit iff every degree is even; an Euler trail iff 0 or 2 degrees are odd | multigraphs allowed; directed: in = out at every vertex, edges in one weak component |
| Hall | bipartite (X, Y) has a matching saturating X iff #N(S) ≥ #S for every S ⊆ X | X finite (infinite X needs finite degrees) |
| König-Egerváry | maximum matching = minimum vertex cover | bipartite only (a triangle has 1 vs 2) |
| Menger | for nonadjacent s, t: minimum s-t vertex cut = maximum number of internally disjoint s-t paths; likewise for edges | finite |
| Max-flow min-cut | maximum flow value = minimum cut capacity; integral capacities give an integral maximum flow | nonnegative capacities |
| Tutte | a perfect matching exists iff o(G − S) ≤ #S for all S ⊆ V, where o counts odd components | finite |
| Dirac | n ≥ 3 and δ ≥ n/2 imply Hamiltonian | simple, n ≥ 3 |
| Ore | n ≥ 3 and deg u + deg v ≥ n for all nonadjacent u, v imply Hamiltonian | simple, n ≥ 3 |
| Euler's formula | a connected plane graph has n − e + f = 2; with c components, n − e + f = 1 + c | a plane embedding |
| Planar edge bound | e ≤ 3n − 6; e ≤ 2n − 4 if triangle-free | simple, n ≥ 3 |
| Kuratowski, Wagner | planar ⇔ no subdivision of K₅ or K₃,₃ ⇔ no K₅ or K₃,₃ minor | finite |
| Brooks | χ ≤ Δ unless G is complete or an odd cycle | connected |
| Vizing | Δ ≤ χ′ ≤ Δ + 1 | simple (multigraphs: χ′ ≤ Δ + μ, μ the maximum multiplicity) |
| König (edge colouring) | χ′ = Δ | bipartite; multigraphs allowed |
| Four colour theorem | planar implies χ ≤ 4 | computer-assisted (Appel-Haken 1976; Robertson-Sanders-Seymour-Thomas 1997; Coq proof by Gonthier 2005) |

## 2. Extremal results and Ramsey numbers

| Result | Statement | Sharpness |
|---|---|---|
| Mantel | triangle-free implies e ≤ ⌊n²/4⌋ | K_{⌊n/2⌋,⌈n/2⌉} |
| Turán | K_{r+1}-free implies e ≤ (1 − 1/r) n²/2; exactly, ex(n, K_{r+1}) = e(T(n, r)) | the Turán graph T(n, r): complete r-partite with balanced parts |
| Erdős-Stone-Simonovits | ex(n, H) = (1 − 1/(χ(H) − 1) + o(1)) n²/2 | T(n, χ(H) − 1); gives only o(n²) for bipartite H |
| Kővári-Sós-Turán | K_{s,t}-free with s ≤ t implies e ≤ ½(t − 1)^(1/s) n^(2−1/s) + ½(s − 1)n | the order is matched for s = 2 (polarity graphs: ex(n, C₄) ~ n^(3/2)/2) and s = 3 (Brown) |
| Zarankiewicz | z(n, n; s, t), the most 1s in an n × n 0-1 matrix with no s × t all-ones submatrix, is O(n^(2−1/s)) for s ≤ t | the same constructions |

**Ramsey numbers.**

- **R(3,3) = 6.** In a 2-coloured K₆, some vertex has ≥ 3 edges of one colour. Any edge of that
  colour among those three neighbours closes a triangle; otherwise the three neighbours form a
  triangle of the other colour. K₅ coloured as pentagon and pentagram has no monochromatic triangle.
- **Recursion.** R(s, t) ≤ R(s−1, t) + R(s, t−1), strictly when both terms are even, so
  R(s, t) ≤ C(s + t − 2, s − 1).
- **Known values.** R(3,4) = 9, R(3,5) = 14, R(4,4) = 18, R(4,5) = 25; 43 ≤ R(5,5) ≤ 46 (the upper
  bound dates from 2024).
- **Diagonal bounds.** R(k, k) > 2^(k/2) (section 4). R(k, k) ≤ C(2k−2, k−1) < 4^k, improved to
  (4 − ε)^k by Campos-Griffiths-Morris-Sahasrabudhe (2023).

## 3. Spectral graph theory

State the matrix and the eigenvalue ordering every time, because conventions differ.

| Matrix | Definition | Eigenvalues |
|---|---|---|
| adjacency A | A_uv = 1 on edges | λ₁ ≥ ... ≥ λ_n; λ₁ ≤ Δ, with λ₁ = d for d-regular graphs |
| Laplacian L | D − A | 0 = μ₁ ≤ μ₂ ≤ ... ≤ μ_n ≤ 2Δ; the multiplicity of 0 is the number of components |
| normalised Laplacian ℒ | I − D^(−1/2) A D^(−1/2) | 0 = ν₁ ≤ ... ≤ ν_n ≤ 2; ν_n = 2 iff some component with an edge is bipartite |

- **Matrix-tree theorem.** The number of spanning trees τ(G) equals any cofactor of L, and
  τ(G) = (1/n) μ₂ ⋯ μ_n. K_n has n^(n−2). The Petersen graph has L-spectrum 0, 2⁵, 5⁴, so
  τ = 2⁵·5⁴/10 = 2000.
- **Fiedler.** μ₂ > 0 iff G is connected (algebraic connectivity). The sign pattern of the Fiedler
  vector gives a spectral partition.
- **Cheeger (normalised Laplacian).** Define the conductance h(G) as the minimum of e(S, S̄)/vol(S)
  over S with vol(S) ≤ vol(V)/2. Then ν₂/2 ≤ h(G) ≤ √(2ν₂). For a d-regular graph with edge expansion
  h = min over #S ≤ n/2 of e(S, S̄)/#S: (d − λ₂)/2 ≤ h ≤ √(2d(d − λ₂)).
- **Expander mixing lemma.** For d-regular G with λ = max(|λ₂|, |λ_n|) and all S, T ⊆ V,
  |e(S, T) − d·#S·#T/n| ≤ λ√(#S·#T), where e(S, T) counts the pairs (s, t) ∈ S × T that are edges.
- **Interlacing (Cauchy).** An induced subgraph H on m vertices has λ_i(A) ≥ λ_i(H) ≥ λ_{i+n−m}(A).
  Consequences:
  - the Hoffman ratio bound for d-regular G: α ≤ n(−λ_n)/(d − λ_n), tight for Petersen
    (10·2/5 = 4);
  - Hoffman's χ ≥ 1 + λ₁/(−λ_n), and Wilf's χ ≤ 1 + λ₁.

```python
import networkx as nx, numpy as np
G = nx.petersen_graph()
A = nx.to_numpy_array(G); L = nx.laplacian_matrix(G).toarray()
np.linalg.eigvalsh(A).round(6)          # [-2 (x4), 1 (x5), 3]
np.linalg.eigvalsh(L).round(6)          # [0, 2 (x5), 5 (x4)]
round(np.linalg.det(L[1:, 1:]))         # 2000 spanning trees
```

Use `scipy.sparse.linalg.eigsh` on large sparse graphs. `nx.number_of_spanning_trees(G)` returns a
float (1999.9999999999998 for Petersen): round it, or take an exact SymPy determinant.

## 4. First moment, union bound and alteration

- **First moment.** If X ≥ 0 is integer-valued, P(X ≥ 1) ≤ E[X]. So E[X] < 1 gives P(X = 0) > 0,
  and an object with X = 0 exists. If E[f] ≥ t, some outcome has f ≥ t. The union bound is
  P(∪A_i) ≤ Σ P(A_i). Linearity of expectation needs no independence.
- **Estimates.** (n/k)^k ≤ C(n, k) ≤ (en/k)^k, C(n, k) ≤ n^k/k!, 1 − x ≤ e^(−x), k! ≥ (k/e)^k.
- **R(k, k) > 2^(k/2) for k ≥ 3** (hub example D). Colour K_n at random with n = ⌊2^(k/2)⌋; the
  expected number of monochromatic K_k is C(n, k)·2^(1−C(k,2)) < 1.
- **Alteration (sample, then repair).** Let G have n vertices and average degree d ≥ 1.
  1. Keep each vertex with probability p. With X the kept vertices and Y the kept edges,
     E[X − Y] = np − (nd/2)p², which is n/(2d) at p = 1/d.
  2. Delete one endpoint of each kept edge. What remains is independent, so an independent set of
     size ≥ n/(2d) exists. (Caro-Wei gives the stronger Σ 1/(deg v + 1) ≥ n/(d + 1).)
- **Ramsey by alteration.** R(k, k) > n − C(n, k)·2^(1−C(k,2)) for every n, which gives
  (1 − o(1))·k·2^(k/2)/e.

## 5. Second moment and thresholds

- **Second moment.** P(X > 0) ≥ (E X)²/E[X²] (Cauchy-Schwarz), and Chebyshev gives
  P(X = 0) ≤ Var X/(E X)².
- **Indicator sums.** For X = Σ X_i with X_i the indicator of A_i, Var X ≤ E X + Δ, where
  Δ = Σ P(A_i ∧ A_j) over ordered dependent pairs i ≠ j. If E X → ∞ and Δ = o((E X)²), then X > 0
  asymptotically almost surely.

| Property of G(n, p) | Threshold | Detail |
|---|---|---|
| contains K₄ | n^(−2/3) | E[#K₄] = C(n,4)p⁶ ~ n⁴p⁶/24; K₄ is balanced, so the second moment works above the threshold |
| contains H | n^(−1/m(H)), m(H) = max over subgraphs H′ of e(H′)/v(H′) | Bollobás 1981 |
| connected | ln n/n | at p = (ln n + c)/n, P(connected) → e^(−e^(−c)), the same limit as "no isolated vertex" |
| giant component | 1/n | p = c/n: for c < 1 all components are O(log n); c = 1 gives Θ(n^(2/3)); for c > 1 one component has size ~βn with β = 1 − e^(−cβ) |
| perfect matching (n even) | ln n/n | |
| Hamiltonian cycle | (ln n + ln ln n)/n | |

- **Janson** (increasing events determined by independent random subsets). With μ = Σ P(A_i) and Δ
  as above, P(no A_i) ≤ e^(−μ + Δ/2), and P(no A_i) ≤ e^(−μ²/(2Δ)) when Δ ≥ μ. Harris gives the lower
  bound P(no A_i) ≥ Π(1 − P(A_i)).
- **Poisson approximation.** The triangle count in G(n, c/n) converges to Poisson(c³/6) (method of
  moments, Brun's sieve or Stein-Chen), so P(triangle-free) → e^(−c³/6).

## 6. Lovász Local Lemma

- **Symmetric.** Let each P(A_i) ≤ p, and let each A_i be mutually independent of all but at most d
  of the other events. If e·p·(d + 1) ≤ 1, then P(no A_i) > 0.
- **Asymmetric.** If some x_i ∈ [0, 1) satisfy P(A_i) ≤ x_i Π_{j∈Γ(i)} (1 − x_j), then
  P(no A_i) ≥ Π(1 − x_i) > 0.
- **Lopsided (Erdős-Spencer).** It is enough that P(A_i | ∩_{j∈S} Ā_j) ≤ P(A_i) for every S disjoint
  from Γ(i) ∪ {i}, a negative-dependency graph. This is what handles Latin transversals.
- **Building the dependency graph.** A_i must be mutually independent of the whole family
  {A_j : j ∉ Γ(i) ∪ {i}}; pairwise independence is not enough. The safe construction: events
  determined by independent variables, with i and j joined when their variable sets intersect.
- **k-SAT.** If every clause has k distinct literals and shares variables with at most d other
  clauses, then e·2^(−k)·(d + 1) ≤ 1 implies satisfiable. For example, it suffices that each variable
  occurs in at most 2^k/(ek) clauses.
- **Moser-Tardos** (variable setting). Sample all variables. While some bad event holds, pick one and
  resample its variables. Under the asymmetric condition the expected number of resamplings is at
  most Σ x_i/(1 − x_i), which is m/d in the symmetric case with x_i = 1/(d+1). The existence proof
  becomes a randomized algorithm, polynomial in m.

## 7. Derandomization

- **Conditional expectations.** Fix the random choices one at a time, each time taking the value
  that does not decrease E[f | choices so far]. The final object has f ≥ E[f].
- **MAX-CUT ≥ m/2.** A random side per vertex gives E[cut] = m/2. Derandomized: place the vertices
  in order, each on the side opposite the majority of its already-placed neighbours.
- **MAX-E3SAT ≥ 7m/8.** A random assignment satisfies each 3-literal clause with probability 7/8.
  Set the variables one by one to the value with the larger conditional expectation, computed
  exactly clause by clause. Beating 7/8 + ε is NP-hard (Håstad).
- **Pessimistic estimators.** When the conditional failure probability cannot be computed, use a
  computable upper bound that starts below 1 and can be kept from increasing at every greedy choice
  (Raghavan). This is typical with Chernoff bounds, for discrepancy and set-cover rounding.
- **Concentration** (Chernoff, Azuma, McDiarmid, Talagrand), with exact hypotheses, lives in
  `probability-distributions-limits`.

## 8. Pitfalls in proofs and computation

- **The induction trap.** "Build G_{n+1} from G_n by adding a vertex" covers only the graphs
  reachable that way. Start from an arbitrary G on n + 1 vertices, remove a well-chosen vertex,
  apply the hypothesis, then put the vertex back.
- **Simple vs multigraph.** Dirac, Vizing, e ≤ 3n − 6 and Turán are statements about simple graphs.
- **Forgotten connectedness** (Euler's formula, Euler circuits, Brooks) **or finiteness** (Hall,
  König's lemma).
- **Directed vs undirected.** The handshake becomes Σ outdeg = Σ indeg = e; tournaments have their
  own theorems.
- **Dependent events treated as independent.** Two triangles sharing an edge in G(n, p) are
  dependent. A dependency graph built from pairwise independence is invalid.
- **Variance without covariances.** Linearity of expectation is free; variance is not.
- **"Asymptotically almost surely" quoted for a fixed n** without a rate.
- **Computational traps.**
  - `nx.greedy_color` gives only an upper bound on χ.
  - `nx.number_of_spanning_trees` returns a float.
  - `nx.read_graph6` returns a single graph, not a list, for a one-line file.
  - geng counts isomorphism classes, not labelled graphs: there are 12346 graphs on 8 vertices,
    against 2^28 labelled ones.

## 9. Computation

```python
import networkx as nx
G = nx.petersen_graph()
nx.is_connected(G), nx.diameter(G), nx.is_bipartite(G)
M = nx.max_weight_matching(G, maxcardinality=True)              # a maximum matching: a certificate
ok, K = nx.check_planarity(nx.complete_graph(5), counterexample=True)   # False, Kuratowski subgraph (10 edges)
s = nx.to_graph6_bytes(G, header=False).strip(); H = nx.from_graph6_bytes(s)
```

- **All non-isomorphic graphs with nauty's geng.** `geng -c 9 > g9c.g6` gives the connected ones;
  `-dK` and `-DK` bound the minimum and maximum degree, `-b` restricts to bipartite, `-t` to
  triangle-free, and `-q` silences the header.
- **Sanity counts.** Graphs on n = 1..9 vertices: 1, 2, 4, 11, 34, 156, 1044, 12346, 274668
  (A000088). Connected: 1, 1, 2, 6, 21, 112, 853, 11117, 261080 (A001349).
- **Without nauty.** `nx.graph_atlas_g()` lists all 1253 graphs on 0-7 vertices.
- **Other tools.** python-igraph for large graphs; House of Graphs (houseofgraphs.org) to look up
  graphs by invariants; SageMath for chromatic number, Hamiltonicity and Lovász theta.
- **SAT encodings.**
  - k-colouring: variables x_{v,c}, a clause ∨_c x_{v,c} for each vertex, and (¬x_{u,c} ∨ ¬x_{v,c})
    for each edge uv and colour c. Fix the colours of a clique to break symmetry.
  - "R(s,t) > n": one variable per edge of K_n, with a clause per s-set forbidding all-red and a
    clause per t-set forbidding all-blue.
  - Solvers: pysat, Kissat or CaDiCaL. SAT returns a model, which is a certificate. UNSAT should come
    with a DRAT proof checked by drat-trim.
- **Random constructions.** Seed every run (`np.random.default_rng(seed)`,
  `nx.gnp_random_graph(n, p, seed=s)`). Use ≥ 1000 trials with a Wilson or Clopper-Pearson interval,
  and store the seeds with the results.

## 10. Certificates over trust

| Claim | Certificate | Check cost |
|---|---|---|
| k-colourable | the colouring | O(n + e) |
| not k-colourable | a (k+1)-clique or other obstruction, or a DRAT UNSAT proof | proof size |
| has a perfect matching | the matching | O(n) |
| has no perfect matching | a Tutte set S with o(G − S) > #S (bipartite: a Hall violator) | O(n + e) |
| Hamiltonian | the cycle | O(n) |
| non-planar | a Kuratowski subdivision (`check_planarity(..., counterexample=True)`) | O(n + e) |
| planar | a combinatorial embedding (rotation system) | O(n + e) |
| max flow = min cut | a flow and a cut of equal value | O(e) |
| bipartite / not bipartite | a 2-colouring / an odd cycle | O(n + e) |
| isomorphic | the vertex bijection | O(e) |

Check the certificate in code that is separate from the solver that produced it.

## 11. Worked example: Dirac's theorem

**Theorem.** A simple graph G on n ≥ 3 vertices with δ(G) ≥ n/2 is Hamiltonian.

1. **G is connected.** Two nonadjacent u, v have deg u + deg v ≥ n > n − 2 = #(V ∖ {u, v}), so they
   share a neighbour.
2. **Longest path.** Take a longest path P = v₁ ... v_k. By maximality, every neighbour of v₁ and of
   v_k lies on P. Since δ ≥ n/2 ≥ 3/2, δ ≥ 2, so k ≥ 3.
3. **A crossing pair.** Let S = {i : v₁ ~ v_{i+1}} and T = {i : v_i ~ v_k}, both subsets of
   {1, ..., k − 1}. #S = deg v₁ ≥ n/2 and #T = deg v_k ≥ n/2, so #S + #T ≥ n > k − 1, and some i lies
   in S ∩ T.
4. **A cycle on P.** C = v₁ v₂ ... v_i v_k v_{k−1} ... v_{i+1} v₁ is a cycle through all k vertices
   of P; the cases i = 1 and i = k − 1 work too.
5. **The cycle is spanning.** If k < n, connectivity gives a vertex w ∉ C adjacent to some v_j ∈ C.
   Then w followed by C, starting at v_j and going around, is a path with k + 1 vertices,
   contradicting maximality. So k = n, and C is a Hamiltonian cycle. ∎

**Sharpness and hypotheses.**

- For odd n, K_{(n−1)/2,(n+1)/2} has δ = (n − 1)/2 and no Hamiltonian cycle: a cycle alternates
  sides, so the sides would have to be equal.
- n ≥ 3 is needed, since K₂ has δ = 1 = n/2 and no cycle.
- Simplicity is needed so that degrees count distinct neighbours.

```python
import networkx as nx
def ham_cycle(G):                       # backtracking; returns a certificate or None
    nodes = list(G); n = len(nodes)
    if n < 3: return None
    path, on = [nodes[0]], {nodes[0]}
    def extend():
        if len(path) == n: return G.has_edge(path[-1], path[0])
        for w in G[path[-1]]:
            if w not in on:
                path.append(w); on.add(w)
                if extend(): return True
                path.pop(); on.discard(w)
        return False
    return path[:] if extend() else None
def is_ham_cycle(G, c):                 # checks the certificate independently
    return c is not None and sorted(c) == sorted(G) and all(G.has_edge(c[i], c[(i + 1) % len(c)]) for i in range(len(c)))
def dirac_graphs(n, g6_path=None):      # every graph on n vertices with 2*min degree >= n
    if g6_path:                         # produced by: geng -q -d<ceil(n/2)> n > g6_path
        return [nx.from_graph6_bytes(l.strip()) for l in open(g6_path, "rb") if l.strip()]
    return [H for H in nx.graph_atlas_g() if H.number_of_nodes() == n and 2 * min(d for _, d in H.degree()) >= n]
for n in range(3, 8):                   # the atlas covers n <= 7; pass geng files for n = 8, 9
    assert all(is_ham_cycle(H, ham_cycle(H)) for H in dirac_graphs(n))
for n in (5, 7, 9):                     # sharpness
    assert ham_cycle(nx.complete_bipartite_graph((n - 1)//2, (n + 1)//2)) is None
```

Run here, the atlas yields 55 graphs with 3 ≤ n ≤ 7 and δ ≥ n/2. All are Hamiltonian, and every
certificate checks. K_{2,3}, K_{3,4} and K_{4,5} have no Hamiltonian cycle. For n = 8 and 9, run
`geng -q -d4 8 > d8.g6` and `geng -q -d5 9 > d9.g6` and pass the files. Status: Known (Dirac 1952),
proof reproduced; Verified for n ≤ 7 here (n ≤ 9 once the geng files are run); sharp for odd n.

Related: `combinatorics-generating-functions`, `probability-distributions-limits`, `proof-techniques-and-writing`, `optimization-convex-nonconvex`, `cs-foundations`, `matrix-decompositions-conditioning`, hub `mathematics-toolkit`
