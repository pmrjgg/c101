---
name: cs-foundations
description: "Computer science foundations pack: algorithm design paradigm selection, complexity analysis (master theorem, amortised, recurrences), lower bounds and fine-grained conjectures, reductions and NP-hardness proofs with pitfalls, approximation and parameterised escapes, data-structure selection table, automata and formal languages, type systems, compiler internals (SSA, dataflow, register allocation), distributed systems (consensus, quorums, CAP/PACELC, consistency models, clocks), concurrency correctness and memory models, and formal methods (TLA+, model checking, proof assistants). Load for any algorithmic, theoretical, distributed-systems or correctness-proof question."
when_to_use: "Designing or analysing an algorithm, proving a bound or hardness result, choosing a data structure, reasoning about parsers, type checkers or compilers, designing or reviewing replication/consensus, diagnosing races, or writing a TLA+/model-checking spec."
---

# CS foundations

Foundational claims are cheap to state and expensive to get wrong: a "linear" algorithm that is
quadratic on adversarial input, an NP-hardness proof reduced in the wrong direction, a consensus
design that loses acknowledged writes under a partition. This skill gives the selection tables
and the proof obligations; every answer states its model (input model, machine model, failure
model, consistency model) before its conclusion.

## 0. Triage

| Request | Section |
|---|---|
| Design an algorithm / pick a paradigm | 1 |
| Analyse running time, prove a bound | 2, 3 |
| "Is this NP-hard?", "Can we do better?" | 3, 4, [complexity and reductions](references/complexity-reductions.md) |
| Pick a data structure | 5, [data structures](references/data-structures.md) |
| Regex, parsing, grammar, decidability | 6 |
| Type system or compiler question | 7, 8 |
| Replication, consensus, consistency, clocks | 9, [distributed systems](references/distributed-systems.md) |
| Races, deadlocks, memory ordering | 10 |
| Specify and check a design | 11, [formal methods](references/formal-methods.md) |

## 1. Algorithm design paradigms

| Problem signal | Paradigm | Proof obligation |
|---|---|---|
| Optimal solution composed of optimal sub-solutions, subproblems repeat | dynamic programming | state definition, recurrence, order of evaluation, base cases; count states × transition cost |
| Local choice never needs revisiting | greedy | exchange argument or matroid structure; find a counterexample first (they usually exist) |
| Split into independent parts of a fraction of the size | divide and conquer | recurrence + master theorem; combine step cost |
| Relations between items, reachability, dependencies | graph algorithms (BFS, DFS, Dijkstra, Bellman-Ford, flows, matching) | model vertices/edges explicitly; check weights (negative?), directedness |
| Feasibility with constraints, small search space | backtracking / branch-and-bound | pruning soundness, bound validity |
| Hard combinatorial optimisation in practice | ILP / SAT / CP solvers (OR-Tools, Gurobi, HiGHS, CaDiCaL) | encoding size, symmetry breaking |
| Need fast typical time or simplicity | randomisation (quickselect, hashing, skip lists, random sampling) | expectation and tail bounds; adversarial inputs |
| Data too big for memory / single pass | streaming and sketches (count-min, HyperLogLog, reservoir sampling) | error ε, failure probability δ, space |
| Online decisions without the future | online algorithms | competitive ratio vs adversary |
| NP-hard but small parameter k | parameterised (FPT, kernelisation, treewidth DP) | f(k)·poly(n) bound |
| NP-hard, need a guarantee | approximation (LP rounding, primal-dual, local search) | ratio proof; check known inapproximability |
| Many queries on static data | preprocessing + query structures (sparse tables, suffix arrays) | preprocessing vs query trade-off |

Before inventing: is it a known problem in disguise (shortest path, bipartite matching, min-cut,
2-SAT, interval scheduling, LIS, edit distance, knapsack)? Recognising the reduction to a
classic is the highest-leverage step.

## 2. Complexity analysis

Master theorem for T(n) = a T(n/b) + f(n), a ≥ 1, b > 1, c* = log_b a:

| Case | Condition | Result |
|---|---|---|
| 1 | f(n) = O(n^(c* - ε)) | Θ(n^c*) |
| 2 | f(n) = Θ(n^c* log^k n), k ≥ 0 | Θ(n^c* log^(k+1) n) |
| 3 | f(n) = Ω(n^(c* + ε)) and a f(n/b) ≤ c f(n), c < 1 | Θ(f(n)) |

Examples: merge sort 2T(n/2) + n → n log n; Karatsuba 3T(n/2) + n → n^1.585; Strassen
7T(n/2) + n² → n^2.807; binary search T(n/2) + 1 → log n. Unequal splits (T(n/3) + T(2n/3) + n)
use Akra-Bazzi or a recursion tree. Linear recurrences T(n) = T(n-1) + T(n-2) → characteristic
roots (φ^n).

Amortised analysis: aggregate, accounting, or potential Φ ≥ 0 with Φ(initial) = 0; amortised cost
= actual + ΔΦ. Dynamic array doubling: O(1) amortised push; union-find with union by rank and
path compression: O(α(n)) amortised.

Analysis hygiene:
- Name the model: word RAM with w = Θ(log n) bits, comparison model, external memory (B, M),
  PRAM/work-span (work W, span D, time ≈ W/p + D).
- Name the measure: worst case, expected (over algorithm randomness), average (over an input
  distribution, state it), amortised, or high probability.
- Hidden costs: hashing assumes O(1) only in expectation and with a good hash; recursion depth
  O(n) can overflow; big integers are not O(1); strings compare in O(length).
- Constants and memory hierarchy decide among equal-Θ choices; measure with a benchmark (fixed
  seed, warm-up, ≥ 5 runs, report median and spread).

## 3. Lower bounds

| Technique | Example result |
|---|---|
| Decision tree / information theory | comparison sorting needs log2(n!) = n log2 n - 1.44n + O(log n) comparisons |
| Adversary argument | finding max and min needs ceil(3n/2) - 2 comparisons |
| Reduction from a known bound | element distinctness Ω(n log n) (algebraic decision trees) ⇒ closest pair, convex hull Ω(n log n) |
| Communication complexity | streaming / distributed lower bounds via disjointness Ω(n) |
| Cell-probe | dynamic connectivity, predecessor bounds |
| Fine-grained conditional | SETH ⇒ no O(n^(2-ε)) edit distance / LCS / orthogonal vectors; 3SUM ⇒ many geometry problems n^(2-o(1)); APSP conjecture ⇒ n^(3-o(1)) for related graph problems |

A lower bound holds only in its model: radix sort beats Ω(n log n) by leaving the comparison model;
hashing beats the element-distinctness bound in expectation. State the model with the bound.

## 4. Reductions and NP-hardness

Procedure to prove problem X is NP-hard:
1. Pick a known NP-hard source Y close in structure to X (catalogue in
   [complexity and reductions](references/complexity-reductions.md)).
2. Give a polynomial-time map f from instances of Y to instances of X. Direction: Y ≤_p X
   (known-hard to new). Reducing X to Y proves nothing about X's hardness.
3. Prove both directions: y ∈ Y ⇒ f(y) ∈ X, and f(y) ∈ X ⇒ y ∈ Y (the second is where gadget
   proofs usually break).
4. Check the size of f(y) and the magnitude of numbers in it (pseudo-polynomial trap: a reduction
   from Partition only shows weak NP-hardness; use 3-Partition for strong NP-hardness).
5. For NP-completeness also show X ∈ NP: a polynomial certificate and verifier.

Escapes when a problem is NP-hard (always check before saying "intractable"):

| Escape | When it works | Example |
|---|---|---|
| Pseudo-polynomial DP | numbers are small (weakly NP-hard) | knapsack O(nW), subset sum O(nT) |
| Parameterised algorithm | a small parameter k | vertex cover O(1.2738^k + kn), treewidth DP |
| Special structure | planar, bipartite, interval, bounded degree, trees | max independent set polynomial on bipartite graphs (König) and trees |
| Approximation | a ratio is acceptable | vertex cover 2, metric TSP 1.5 (Christofides; slightly better since 2020), set cover ln n |
| Good heuristics + solvers | real instances are structured | SAT/ILP solve industrial instances with millions of variables |
| Exponential but fast exact | n ≤ ~40-60 | meet-in-the-middle 2^(n/2), inclusion-exclusion, branch and bound |

Inapproximability to check before promising a ratio: set cover (1 - ε) ln n (P ≠ NP), max-3SAT
7/8 + ε (Håstad), vertex cover 2 - ε under the Unique Games Conjecture, max clique n^(1-ε),
general TSP (no constant ratio without the triangle inequality).

Undecidability: Rice's theorem (any non-trivial semantic property of programs is undecidable)
means static analysers must be sound-but-incomplete or complete-but-unsound; say which one a
proposed tool is.

## 5. Data structure selection (full table in [data structures](references/data-structures.md))

| Need | Structure | Cost |
|---|---|---|
| Key → value, no order | hash table (open addressing, Swiss table) | O(1) expected; worst case O(n) under adversarial keys unless seeded hash |
| Ordered keys, range queries | balanced BST / B-tree (in-memory B-tree beats BST by cache) | O(log n) |
| Write-heavy persistent storage | LSM tree | fast writes, read/space amplification, compaction tuning |
| Read-heavy persistent storage | B+tree | O(log_B n) I/Os |
| Min/max repeatedly | binary heap; pairing heap if decrease-key heavy | O(log n); O(1) find |
| Dynamic connectivity (unions only) | union-find | O(α(n)) amortised |
| Range sum/min with updates | Fenwick tree (invertible ops) / segment tree (any monoid, lazy propagation) | O(log n) |
| Prefix / string search | trie, suffix array + LCP, suffix automaton | O(m) or O(m log n) per query |
| Membership with false positives OK | Bloom filter: m/n = 1.44 log2(1/p) bits, k = (m/n) ln 2 | 1% → 9.6 bits/key, k = 7 |
| Membership with deletes | cuckoo / quotient filter | ~similar space, supports delete |
| Count distinct | HyperLogLog, std error 1.04/sqrt(m) registers | m = 2^14 → 0.81% |
| Frequencies of heavy hitters | count-min: w = ceil(e/ε), d = ceil(ln(1/δ)) | error ≤ εN with prob 1 - δ |
| Spatial queries | k-d tree (low dimension), R-tree (rectangles), BVH, geohash/S2 cells | dimension curse above ~10-20 |
| LRU cache | hash map + doubly linked list | O(1) |
| Versioned / undo | persistent (path copying) structures | O(log n) per version |
| Concurrent map | sharded locks or lock-free (e.g. Java ConcurrentHashMap) | contention-bound |

## 6. Automata and formal languages

| Class | Recogniser | Closure / decidability | Practical tool |
|---|---|---|---|
| Regular | DFA/NFA | closed under ∪, ∩, complement, *; emptiness, equivalence decidable | RE2, Rust `regex`, Hyperscan (linear time) |
| Deterministic context-free | DPDA | LR(k)/LL(k) parseable in linear time | yacc/bison (LALR), ANTLR (ALL(*)), hand-written recursive descent |
| Context-free | PDA | closed under ∪, concatenation, * (not ∩, complement); emptiness decidable, equivalence and ambiguity undecidable | CYK O(n³), Earley (O(n³) worst, linear for most), GLR |
| Context-sensitive | LBA | membership PSPACE-complete | rarely used directly |
| Recursively enumerable | Turing machine | membership semi-decidable; halting undecidable | n/a |

Proof tools: pumping lemma (to show non-regular / non-CF: pick the string, then the adversary picks
the split); Myhill-Nerode (number of distinguishable suffix classes = minimal DFA size; infinitely
many classes ⇒ not regular; cleaner than pumping). Subset construction can blow up 2^n states
(language "n-th symbol from the end is a").

Practical traps: backtracking regex engines (PCRE, Java, Python `re`, JavaScript) have exponential
worst cases on patterns like `(a+)+$` (ReDoS); use linear-time engines for untrusted input or
bound input length. Backreferences make matching NP-hard. PEG ordered choice silently hides
ambiguity; left recursion breaks LL and PEG unless handled.

## 7. Type systems

| Concept | Fact to use |
|---|---|
| Soundness | progress + preservation (well-typed programs do not get stuck); stated relative to an operational semantics |
| Hindley-Milner | principal types, decidable inference (Algorithm W / constraint solving), let-polymorphism; worst case exponential but near-linear in practice |
| System F | impredicative polymorphism; full type inference undecidable (Wells 1999), so annotate or use bidirectional checking |
| Subtyping variance | functions contravariant in arguments, covariant in results; mutable containers must be invariant (Java covariant arrays are unsound, checked at runtime with ArrayStoreException) |
| Bidirectional typing | check mode for introductions, infer mode for eliminations; scales to dependent and higher-rank types |
| Linear / affine types | use exactly / at most once; foundation of Rust ownership, session types |
| Dependent types | types indexed by values (Lean, Agda, Idris, Coq/Rocq); type checking requires evaluation, so termination checking matters |
| Effects | monads, algebraic effects (OCaml 5), effect rows |
| Gradual typing | blame tracking; casts cost performance at boundaries |
| Refinement types | predicates on types checked by SMT (Liquid Haskell, F*) |

## 8. Compilers

- Pipeline: lex → parse → AST → name resolution and type checking → IR lowering (SSA) →
  optimisation → instruction selection → register allocation → scheduling → emission.
- SSA: each variable assigned once; φ-functions at dominance frontiers (Cytron et al.); makes
  constant propagation, GVN and dead-code elimination sparse and simple.
- Dataflow analysis: lattice of facts, monotone transfer functions, worklist iteration to the
  least (or greatest) fixpoint; terminates when the lattice has finite height (or with widening).
  Forward (reaching definitions, available expressions) vs backward (liveness).
- Register allocation: graph colouring with coalescing and spilling (Chaitin-Briggs, iterated
  register coalescing) for quality; linear scan for JIT speed; SSA-form graphs are chordal
  (optimal colouring in polynomial time).
- Undefined behaviour in C/C++ licenses the optimiser to assume it never happens (signed overflow,
  null deref, out-of-bounds); explain surprising codegen through that lens.
- Tools: Compiler Explorer (godbolt.org), `clang -O2 -S -emit-llvm x.c -o x.ll`,
  `opt -passes='default<O2>' -S x.ll`, `clang -O2 -Rpass=loop-vectorize -Rpass-missed=loop-vectorize`,
  `llvm-mca` for throughput estimates, MLIR for domain-specific IRs.

## 9. Distributed systems (detail in [distributed systems](references/distributed-systems.md))

State the failure model first: crash-stop, crash-recovery (with stable storage), omission, or
Byzantine; synchronous, partially synchronous, or asynchronous network.

| Fact | Consequence |
|---|---|
| FLP: no deterministic consensus in an asynchronous system with one crash | real protocols assume partial synchrony (timeouts) for liveness, keep safety always |
| Crash-fault consensus needs n ≥ 2f + 1 | 3 nodes tolerate 1 failure, 5 tolerate 2 |
| Byzantine consensus needs n ≥ 3f + 1 | 4 nodes tolerate 1 Byzantine node |
| Quorums intersect when R + W > N (and W > N/2 for write-write ordering) | Dynamo-style N=3, R=W=2; still not linearizable without read repair/sync and conflict handling |
| CAP: during a partition choose consistency or availability | PACELC: else (no partition) choose latency or consistency |
| Exactly-once delivery is impossible end to end | exactly-once effects = at-least-once delivery + idempotent processing / deduplication keys |
| Clocks drift and jump | use logical clocks (Lamport, vector, hybrid logical) for ordering; TrueTime-style bounded uncertainty only with dedicated hardware |

Consistency models, strongest first (single-object then transactional): linearizable >
sequential > causal > PRAM/FIFO > eventual; strict serializable > serializable > {snapshot
isolation, repeatable read} (incomparable: SI allows write skew, RR allows phantoms) > read
committed > read uncommitted. Name the
exact model a system provides and test it (Jepsen/Elle-style histories), not marketing terms.

Raft essentials: one leader per term; leader election needs a majority and the candidate's log
must be at least as up to date; log matching property; an entry is committed when stored on a
majority in the leader's current term (entries from older terms commit only indirectly, Raft
paper Figure 8); reconfiguration via joint consensus or single-server changes.

## 10. Concurrency correctness

- Data race (unsynchronised conflicting accesses, at least one write) is undefined behaviour in
  C/C++ and Rust unsafe, and breaks happens-before reasoning in Java/Go. A race condition (bad
  interleaving) can exist without a data race.
- Memory models: C++/Rust `seq_cst`, `acquire`/`release` (message passing), `relaxed` (counters
  only); Java `volatile` and `synchronized` create happens-before edges; Go: channels and `sync`
  create edges, `sync/atomic` is sequentially consistent.
- Correctness criterion for concurrent objects: linearizability (each operation appears atomic at
  a point between call and return). Progress: wait-free > lock-free > obstruction-free > blocking.
- Deadlock needs all four Coffman conditions (mutual exclusion, hold and wait, no preemption,
  circular wait); break one, usually by a global lock order.
- Classic bugs: check-then-act (TOCTOU), double-checked locking without proper ordering, ABA in
  CAS loops (use tagged pointers, hazard pointers or epoch reclamation), lost wakeups (condition
  variables need a predicate loop), priority inversion.
- Tools: ThreadSanitizer (`-fsanitize=thread`), `go test -race`, `cargo +nightly miri test`,
  `loom` (exhaustive interleavings for Rust), jcstress (Java), Coyote / Shuttle (systematic
  testing), Helgrind. Stress tests find bugs; only model checking or proof shows absence.

## 11. Formal methods (templates in [formal methods](references/formal-methods.md))

| Goal | Tool |
|---|---|
| Design-level protocol bugs (consensus, caches, workflows) | TLA+ with TLC (explicit state) or Apalache (symbolic); PlusCal for algorithm-style specs; P language for event-driven systems |
| Structural / relational models | Alloy 6 |
| Bounded checking of C/Rust code | CBMC, Kani (Rust) |
| Verified functions and invariants in code | Dafny, Verus (Rust), Why3, Frama-C |
| Mathematical proofs, verified compilers | Lean 4, Rocq (formerly Coq), Isabelle/HOL |
| Concurrency in Rust tests | loom, Shuttle |

Workflow: specify state and actions → write safety invariants (TypeOK plus the property) →
model check small configurations (3 nodes, 2-3 values) with symmetry → add liveness with fairness
→ trace any counterexample into a test in the real code. Model checking proves properties of the
model at the bounds checked; report bounds.

## 12. Worked example: a hardness claim done right

Claim: scheduling n jobs with integer durations on 2 identical machines to minimise makespan is
NP-hard. Reduce from Partition (known NP-complete): given integers a₁..a_n with sum 2S, create
jobs with durations a_i and ask whether makespan ≤ S. (⇒) a partition into two sets of sum S gives
a schedule with both machines finishing at S. (⇐) makespan ≤ S with total work 2S forces both
machines to have load exactly S, giving the partition. f is linear time. Conclusion: NP-hard, but
only weakly (Partition has an O(nS) DP), so a pseudo-polynomial O(nS) algorithm exists; for 3+
machines as part of the input, reduce from 3-Partition for strong NP-hardness. Practical answer:
LPT greedy gives a 4/3 - 1/(3m) approximation; exact DP when S is small.

## Quality gate before returning

- [ ] Model stated (machine, input, failure, consistency) for every complexity or correctness claim.
- [ ] Bounds labelled worst/expected/amortised/average with the distribution.
- [ ] Reductions in the right direction, both implications proved, size and number magnitude checked.
- [ ] Data structure choice justified by the operation mix with complexities and constants.
- [ ] Distributed designs state quorum sizes, fault tolerance f, and the consistency model provided.
- [ ] Concurrency claims backed by a memory-model argument, a tool run, or a model-checked spec
      (with bounds).
