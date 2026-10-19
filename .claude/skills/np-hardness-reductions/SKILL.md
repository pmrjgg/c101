---
name: np-hardness-reductions
description: "Hardness and lower bounds done right: class map, reduction procedure (direction, both implications, size and number magnitude), source catalogue and gadget checklist, strong vs weak NP-hardness, escapes (pseudo-polynomial, FPT, structure, approximation, solvers), inapproximability, W-hardness, fine-grained conjectures, model-specific lower bounds, undecidability via Rice. Load for 'is this NP-hard', 'can we do better' or any impossibility claim."
when_to_use: "Someone says a problem is NP-hard, intractable, impossible or optimal; proving or reviewing a reduction; promising an approximation ratio; deciding whether to stop optimising an O(n^2) algorithm; a static-analysis tool claiming to catch all bugs; choosing between exact, approximate and heuristic approaches for scheduling, packing, routing or covering problems."
---

# NP-hardness, reductions and lower bounds

Every impossibility claim names its model, its assumption and its reduction direction. Algorithm
design is in `algorithm-design-paradigms`; pseudo-polynomial DPs in `dynamic-programming-patterns`;
hub `cs-foundations` sections 3, 4 and 12.

## 1. Class map

| Class | Informal definition | Complete / representative problems |
|---|---|---|
| P | deterministic polynomial time | circuit value, LP, Horn-SAT (P-complete under log-space reductions: hard to parallelise) |
| NP | polynomial-time verifiable certificates | SAT, 3-SAT, clique, vertex cover, Hamiltonian cycle, subset sum, 3-colouring |
| coNP | complements of NP | tautology (UNSAT), "graph is not 3-colourable" |
| NP intersect coNP | short certificates both ways | factoring (decision), parity games; not NP-complete unless NP = coNP |
| #P | counting accepting paths | #SAT, permanent of 0/1 matrices, counting perfect matchings |
| PSPACE | polynomial space | TQBF, generalised geography, many polynomial-length two-player games |
| EXPTIME | exponential time | generalised chess and go (suitable rules) |
| BPP / RP / ZPP | randomised, bounded two-sided / one-sided / zero error | polynomial identity testing (coRP, not known in P) |
| BQP | quantum polynomial time | factoring, discrete log (Shor); relation to NP unknown |
| L / NL | (non)deterministic log space | undirected reachability in L (Reingold); directed reachability NL-complete |

Known: P in NP in PSPACE in EXPTIME; P != EXPTIME (time hierarchy); NL in P; NL = coNL
(Immerman-Szelepcsenyi); PSPACE = NPSPACE (Savitch); BPP in BQP; PH in P^#P (Toda). Open: P vs
NP, NP vs coNP, P vs PSPACE, BPP vs P (believed equal). If P != NP, NP-intermediate problems
exist (Ladner); factoring and graph isomorphism (quasi-polynomial, Babai) are the usual candidates.

## 2. Reduction procedure

To show X is NP-hard:
1. **Choose a source** Y known NP-hard and structurally close to X (section 3).
2. **Map Y <=_p X**: a polynomial-time f from Y-instances to X-instances. Known-hard to new.
   Reducing X to Y only shows X is no harder than Y.
3. **Prove both implications**: y in Y implies f(y) in X, and f(y) in X implies y in Y. The second
   is where gadget proofs break: argue from an arbitrary solution of f(y).
4. **Check size and magnitude**: |f(y)| polynomial; numbers polynomially bounded for strong
   hardness, or the result is only weak NP-hardness.
5. **Membership** (for NP-completeness): a polynomial certificate and verifier for X.

| Reduction | Allows | Use |
|---|---|---|
| Karp (many-one) | one call, answer preserved | NP-completeness; keeps NP and coNP apart |
| Cook (Turing) | polynomially many oracle calls | NP-hardness of optimisation and search versions |
| L-reduction | linear relation of optima and of errors | transfers APX-hardness and PTAS non-existence |
| gap-preserving | maps yes to OPT >= c, no to OPT < s | inapproximability from PCP-based gaps |

## 3. Source catalogue

| Source | Hard variants worth knowing | Good for |
|---|---|---|
| 3-SAT | planar 3-SAT; planar monotone rectilinear 3-SAT; (3,B2)-SAT (each literal exactly twice); clauses of size 2-3 with each variable <= 3 times | local constraints, puzzles, planar geometry; note exactly-3 clauses with <= 3 occurrences per variable are always satisfiable (Tovey) |
| NAE-3SAT, 1-in-3-SAT | monotone 1-in-3-SAT; planar 1-in-3-SAT | partition-like, hypergraph colouring; planar NAE-3SAT is polynomial (trap) |
| vertex cover / independent set / clique | VC and IS stay hard on planar cubic graphs | covering, packing, conflict graphs; clique on planar graphs is polynomial (no K5) |
| 3-colouring | planar, max degree 4 | frequency and register allocation |
| Hamiltonian cycle / path | cubic planar; grid graphs (puzzles, robot paths) | routing, TSP, sequencing |
| 3-dimensional matching | | assignment with triples |
| Partition / subset sum | weakly NP-hard (O(nS) DP) | two-machine scheduling, load balancing |
| 3-Partition | strongly NP-hard | bin packing, scheduling with m in the input |
| X3C (exact cover by 3-sets), set cover | | facility location, tiling, test selection |
| max-cut | hard in general; polynomial on planar graphs | clustering, partitioning |
| Steiner tree | graphs, Euclidean and rectilinear plane | network design |
| dominating set | W[2]-complete | placement problems |

## 4. Gadget checklist

- **Variable gadget** forces exactly one of two states (true/false) in every solution.
- **Clause gadget** can be completed iff at least one attached literal gadget is in the true
  state (exactly one, for 1-in-3 constructions).
- **Connections** preserve what the target requires: maximum degree, planarity (crossover
  gadget, or start from planar 3-SAT), bipartiteness, unit weights.
- **Backward direction**: extract an assignment from ANY target solution, including unintended
  ones (a solution that splits a gadget, uses slack, or exploits ties).
- **Accounting**: count vertices, edges and constraints as a polynomial in n and m; state whether
  numbers are written in unary or binary and their maximum magnitude.

## 5. Escape table (check before saying "intractable")

| Escape | Works when | Example |
|---|---|---|
| pseudo-polynomial DP | numbers are small (weak NP-hardness) | knapsack O(nW), subset sum O(nT), two-machine makespan O(nS) |
| parameterised algorithm | a small parameter k | vertex cover O(1.2738^k + kn); treewidth DP |
| special structure | planar, bipartite, interval, chordal, bounded degree, trees | max independent set on bipartite graphs (Konig) and trees |
| approximation | a ratio is acceptable | vertex cover 2, metric TSP 1.5, set cover ln n |
| solver plus heuristics | instances are structured | SAT/MILP/CP-SAT on industrial instances with 10^6 variables |
| fast exponential exact | n up to ~40-60 | meet in the middle 2^(n/2), inclusion-exclusion (Hamiltonicity O(2^n poly)), branch and bound |

Rule: before declaring intractability, look at real instance sizes, number magnitudes and
structure (degree, planarity, treewidth, number of distinct values). A worst-case hardness
theorem about the general problem says little about 200-node planar instances.

## 6. Approximation, parameterised hardness, ETH and SETH

| Problem | Best known approximation | Hardness |
|---|---|---|
| vertex cover | 2 | 2 - eps under UGC; sqrt(2) - eps NP-hard (2-to-2 games theorem) |
| set cover | H_n ~ ln n (greedy) | (1 - eps) ln n unless P = NP |
| max-3SAT | 7/8 (random assignment) | 7/8 + eps NP-hard (Hastad) |
| max-cut | 0.878 (Goemans-Williamson) | optimal under UGC; 16/17 + eps NP-hard |
| metric TSP | 1.5 (Christofides-Serdyukov), marginally below 1.5 since 2020 | 123/122 NP-hard |
| Euclidean TSP | PTAS (Arora, Mitchell) | - |
| bin packing | asymptotic PTAS; FFD <= 11/9 OPT + 6/9 | absolute 3/2 - eps (from Partition) |
| knapsack | FPTAS | - (weakly NP-hard) |
| max clique / independent set | n / polylog n | n^(1 - eps) |
| k-center | 2 | 2 - eps |
| general TSP (no triangle inequality) | none | no constant ratio unless P = NP |

Parameterised: FPT means f(k) n^O(1). Clique and independent set by solution size are W[1]-hard,
dominating set and set cover W[2]-hard: no FPT algorithm unless FPT = W[1] (resp. W[2]).
Kernelisation shrinks to an equivalent instance of size g(k): vertex cover has a 2k-vertex kernel
(LP / crown) and the O(k^2) Buss kernel. ETH: 3-SAT has no 2^(o(n)) algorithm (via sparsification
also no 2^(o(n + m))). SETH: for every eps > 0 some k-SAT needs 2^((1 - eps) n).

## 7. Fine-grained conjectures

| Conjecture | Statement | Conditional lower bounds |
|---|---|---|
| SETH | k-SAT needs 2^((1-eps)n) for large k | orthogonal vectors, edit distance, LCS, DTW: n^(2-o(1)); (3/2 - eps)-approximate diameter in sparse graphs: n^(2-o(1)) |
| 3SUM | no O(n^(2-eps)) for 3SUM | collinear points, polygon containment, some dynamic graph problems |
| APSP | no O(n^(3-eps)) for real-weighted APSP | negative triangle, radius, median, replacement paths |
| OMv | online matrix-vector multiplication needs n^(3-o(1)) | dynamic graph data structures |
| combinatorial BMM | no combinatorial n^(3-eps) | triangle detection, CFG parsing (Valiant, Lee) |

Use these to justify "quadratic is likely optimal" and stop chasing impossible speedups, and
always label the statement conditional: "no O(n^(2-eps)) edit distance algorithm unless SETH
fails".

## 8. Lower-bound techniques and their models

| Technique | Model | Example |
|---|---|---|
| decision tree / information theory | comparisons | sorting needs ceil(log2 n!) = n log2 n - 1.44 n + O(log n) comparisons |
| adversary argument | comparisons | max and min together need ceil(3n/2) - 2 comparisons |
| reduction from a known bound | algebraic decision trees | element distinctness Omega(n log n) gives closest pair; sorting gives convex hull |
| communication complexity | streaming, distributed | set disjointness Omega(n) bits: exact distinct counting or exact max frequency need linear space in one pass |
| cell probe | data structures on a word RAM | predecessor search, dynamic connectivity Omega(log n) |

A bound holds only in its model: radix sort and hashing escape comparison bounds, randomisation
escapes deterministic adversaries, and approximation escapes streaming exactness bounds (see
`randomized-algorithms-sketches`). State the model next to the bound.

## 9. Undecidability

Halting is undecidable; Rice's theorem: every non-trivial semantic property of programs
(behaviour, not syntax) is undecidable. Consequences for tools:
- A static analyser is either **sound but incomplete** (never misses a bug of its class, reports
  false alarms: abstract interpretation, type systems) or **complete but unsound** (every report
  is real, misses some: testing, bug finders), or neither. Ask which one a proposed tool is.
- Halting is semi-decidable (run it and wait), its complement is not.
- Still achievable: bounded checking (CBMC, Kani: exhaustive up to a bound), abstraction plus
  refinement, decidable fragments (Presburger arithmetic, finite-state models), and runtime
  monitoring.

## 10. Mechanical check of a reduction

Before trusting a hand proof, solve every small source instance and its image independently by
brute force and compare. For larger instances use a SAT or pseudo-Boolean encoding (PySAT) or a
MILP as the oracle.

```python
import itertools
def reduce_partition_to_makespan(a):
    return list(a), 2, sum(a) // 2      # (jobs, machines, deadline); odd total -> forced "no"

def partition_brute(a):                 # source oracle
    T = sum(a)
    return T % 2 == 0 and any(sum(c) == T // 2 for r in range(len(a) + 1)
                              for c in itertools.combinations(a, r))

def makespan_brute(jobs, m, deadline):  # image oracle: every assignment of jobs to machines
    for assign in itertools.product(range(m), repeat=len(jobs)):
        loads = [0] * m
        for j, mach in zip(jobs, assign): loads[mach] += j
        if max(loads, default=0) <= deadline: return True
    return False

for n in range(1, 9):                   # all multisets, n <= 8, values 1..10
    for a in itertools.combinations_with_replacement(range(1, 11), n):
        assert partition_brute(a) == makespan_brute(*reduce_partition_to_makespan(a)), a
```

Run for this skill: all 43 757 instances agree (3.4 s in CPython). Also assert that the map is
linear time and that its output numbers are bounded by the input numbers (here identical).

## 11. Pitfalls

- Reducing in the wrong direction (new problem to SAT shows membership, not hardness).
- Calling an O(nW) or O(nS) algorithm polynomial: it is exponential in the bit length of W.
- Using hardness of the general problem to dismiss small or structured real instances.
- Confusing hardness of a special case with hardness of yours (and the reverse: your special case
  may be easy, e.g. planar max-cut, bipartite independent set).
- Promising a ratio below a known inapproximability bound (vertex cover below 2 needs to beat
  UGC; set cover below ln n contradicts P != NP).
- A reduction whose numbers blow up exponentially (weak hardness claimed as strong).

## 12. Worked example: two-machine makespan from Partition

Claim: deciding whether n jobs with integer durations fit on 2 identical machines within makespan
D is NP-complete. Membership: the assignment is the certificate. Reduction from Partition
(a_1..a_n, total T): jobs a_i, deadline D = floor(T/2).
- (=>) A partition into two halves of sum T/2 puts each half on one machine: makespan T/2 = D.
- (<=) Makespan <= D = floor(T/2) with total work T forces T even and both loads exactly T/2:
  the machine contents are a partition. For odd T no schedule meets D, matching "no".
- f copies the numbers: linear time, magnitudes unchanged.

Strength: only **weakly** NP-hard, because a subset-sum bitset decides it in O(nS) (S = T/2):

```python
def makespan2_dp(jobs):                 # exact optimum for 2 machines, O(n * S / w) with ints
    T, bits = sum(jobs), 1
    for x in jobs: bits |= bits << x
    return T - max(s for s in range(T // 2 + 1) if bits >> s & 1)

def lpt(jobs, m):                       # longest processing time first
    loads = [0] * m
    for j in sorted(jobs, reverse=True):
        loads[loads.index(min(loads))] += j
    return max(loads)
```

With m machines as part of the input (P||Cmax), reduce from 3-Partition instead: 3m jobs,
m machines, deadline B; numbers stay polynomial, so the problem is **strongly** NP-hard and has
no FPTAS unless P = NP (a PTAS exists: Hochbaum-Shmoys). For fixed m an FPTAS exists.

LPT guarantees makespan <= (4/3 - 1/(3m)) OPT (Graham): 7/6 for m = 2, 11/9 for m = 3. The
bound is tight: jobs [3, 3, 2, 2, 2] on 2 machines give LPT 7 vs OPT 6 (3+3 | 2+2+2). Checked on
3 000 seeded instances (n <= 8, durations 1-20) against brute-force optima: the DP always matched
and the worst LPT ratios seen were 1.139 (m = 2) and 1.167 (m = 3), inside the bounds.

Recommendation: exact DP when S = T/2 is small (S x n up to ~10^9 bit operations is seconds);
CP-SAT or MILP for many machines with side constraints; LPT, or LPT plus local search, when a
quick answer within 4/3 is enough.

Related: `algorithm-design-paradigms`, `dynamic-programming-patterns`, `amortized-recurrence-analysis`, `randomized-algorithms-sketches`, `graph-algorithms`, `quantum-computing`, hub `cs-foundations`
