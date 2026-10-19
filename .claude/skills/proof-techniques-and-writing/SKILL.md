---
name: proof-techniques-and-writing
description: "Choosing a proof technique from the statement's shape and writing or auditing the proof rigorously: restating with quantifiers, induction variants, contradiction and contrapositive, descent and extremal arguments, pigeonhole, invariants, double counting and bijections, compactness, diagonalization, heuristics when stuck, the proof template, hygiene and fallacy checks, and refereeing. Load before proving anything or reviewing a proof."
when_to_use: "Prove a theorem, lemma or algorithm property; pick a technique for a given statement; get unstuck; write a proof that others must check; or audit, referee or red-team a proof to find the first fatal step, a counterexample to a lemma, an unjustified citation, a circular argument or a broken induction."
---

# Proof techniques and writing

Restate the claim, choose a technique from its shape, write the proof with the template, run the
hygiene checklist, and audit the proof as if someone else wrote it. The status labels are defined
in `mathematics-toolkit` section 0; use them verbatim and never upgrade one in a summary.

## 1. Restate first

1. **Quantifiers.** Write every quantifier in order, ∀ε > 0 ∃δ > 0 ∀x ..., and note what each
   constant may depend on.
2. **Domains.** ℕ with or without 0, ℤ, ℝ or ℂ, finite or infinite, simple graph or multigraph,
   open or closed set.
3. **The exact claim.** Existence, uniqueness, an equality, an inequality (with or without its
   equality cases), an asymptotic (which constant is hidden?), "for all sufficiently large n".
4. **Ambiguities.** Each becomes an Open doubt that names the reading chosen ("log is natural",
   "graphs are simple").
5. **Small cases first.** Test the smallest cases and one extreme case before proving anything
   (`mathematics-toolkit` section 5). If the claim fails, the label is False and the task changes.
6. **Labels.** Proved, Proved (formal), Known, Proved assuming X, Verified for finite range,
   Numerical evidence, Conjectured, False: exactly as the hub defines them.

## 2. Statement shape → first technique

| Statement shape | First technique | Watch for |
|---|---|---|
| ∀n ∈ ℕ, P(n) | induction: weak, strong, or on a strengthened statement | base cases; the step uses only cases already proved |
| ∀ finite structures (graphs, trees, words) | structural induction, induction on size, minimal counterexample | removing an element must keep the object in the class |
| ∀x in a well-founded order (pairs, terms, programs) | well-founded or lexicographic induction | the order really is well-founded; every recursive call decreases |
| "no solution in ℕ or ℤ" | infinite descent or minimal counterexample | the smaller solution satisfies every constraint (positivity, coprimality) |
| no X exists; irrationality; infinitude | contradiction | contradict a hypothesis or a proven fact |
| P ⇒ Q with ¬Q concrete | contrapositive ¬Q ⇒ ¬P | not the converse Q ⇒ P |
| two objects share a property | pigeonhole: n items in k boxes put ≥ ⌈n/k⌉ in one box | designing the boxes is the proof |
| an object with a property exists | explicit construction; otherwise the probabilistic method or counting | expectation and union-bound arithmetic |
| a process terminates | a monovariant strictly decreasing in a well-ordered set | it decreases at every step |
| a configuration is unreachable | an invariant (parity, mod k, colouring, weighted sum) | it holds initially and every move preserves it |
| two counts are equal | bijection or double counting | the map is well defined and invertible on the stated sets |
| a count has a closed form | a bijection to a known family, or a GF (`combinatorics-generating-functions`) | offsets, empty objects |
| an optimum is attained; extremal configuration | extremal principle | the extremum exists (finite, well-ordered, compact) |
| all infinite objects, from all finite ones | compactness (König, de Bruijn-Erdős, topological) | local finiteness, closedness |
| uncountable, undecidable, not enumerable | diagonalization | the diagonal object lies in the class |
| an inequality | `inequality-proving` | equality cases choose the tool |
| a limit or convergence | explicit ε-δ, squeeze, monotone and bounded, dominated convergence | interchanging limits needs a theorem |
| a polynomial identity | compare coefficients, or deg + 1 points (`sympy-symbolic-verification`) | random tests are evidence only |

## 3. Induction catalogue

| Variant | Scheme | Typical use |
|---|---|---|
| weak | P(n₀), and P(n) ⇒ P(n+1) | sums, one-term recurrences |
| strong | (P(m) for all n₀ ≤ m ≤ n) ⇒ P(n+1) | factorisation, multi-term recurrences; a step reaching back k needs k base cases (F_n < 2ⁿ needs n = 0 and 1) |
| structural | prove each constructor case assuming the claim for sub-objects | trees, formulas, lists, programs |
| well-founded or lexicographic | (∀y ≺ x, P(y)) ⇒ P(x) for a well-founded ≺ | Ackermann termination on (m, n) ordered lexicographically; Euclid on the second argument |
| two-variable | induct on m with ∀n inside, or on m + n | R(s,t) ≤ C(s+t−2, s−1) by induction on s + t |
| forward-backward (Cauchy) | P(2^k) for every k, and P(n) ⇒ P(n−1) | AM-GM for every n |
| strengthened ("loading") | prove a stronger, inductive statement | Σ_{k≤n} 1/k² ≤ 2 − 1/n, which implies < 2 |

Rules:

1. State P(n) as one sentence about one n.
2. The step must hold for every n from the last base case on. Instantiate it at the smallest n
   by hand: that is where "all horses are one colour" fails (section 11).
3. When the step fails, strengthen the statement: add a bound, carry an extra quantity, or induct
   on another parameter. For the loaded example the step is
   2 − 1/n + 1/(n+1)² ≤ 2 − 1/(n+1) ⇔ 1/(n+1)² ≤ 1/(n(n+1)), which is true.

## 4. Contradiction, contrapositive, descent and the extremal principle

- **Contrapositive.** The contrapositive of P ⇒ Q is ¬Q ⇒ ¬P, which is equivalent. The converse
  Q ⇒ P and the inverse ¬P ⇒ ¬Q are not. A "contradiction" proof that assumes ¬Q, derives ¬P and
  stops is a contrapositive in disguise, so write it as one.
- **Mechanical negation.** Negate from the outside in, one symbol at a time (Lean's `push_neg` does
  exactly this):
  - ¬∀x P ≡ ∃x ¬P, and ¬∃x P ≡ ∀x ¬P;
  - ¬(P ∧ Q) ≡ ¬P ∨ ¬Q, and ¬(P ⇒ Q) ≡ P ∧ ¬Q;
  - not continuous at a: ∃ε > 0 ∀δ > 0 ∃x with |x − a| < δ and |f(x) − f(a)| ≥ ε.
- **Minimal counterexample.** If counterexamples exist, their sizes form a nonempty subset of ℕ,
  which has a least element. Derive a smaller counterexample.
- **Infinite descent.**
  - **√2 ∉ ℚ.** Suppose √2 = p/q with q ≥ 1 minimal. Then p² = 2q², so p = 2p′ and q² = 2p′². So q
    is even, and √2 = p′/(q/2) has a smaller denominator.
  - **x⁴ + y⁴ = z² has no positive solutions** (Fermat). Take a solution with z minimal.
    1. gcd(x, y) = 1: a common prime p would give p⁴ ∣ z², so p² ∣ z and a smaller solution.
    2. (x², y², z) is a primitive Pythagorean triple; let y be the even leg. Then x² = m² − n²,
       y² = 2mn, z = m² + n² with m > n > 0 coprime and of opposite parity.
    3. x² + n² = m² is primitive with x odd, so n is even: n = 2rs and m = r² + s² with r, s
       coprime.
    4. (y/2)² = mrs with m, r, s pairwise coprime, so each is a square: m = c², r = a², s = b².
    5. Then a⁴ + b⁴ = c² with 0 < c ≤ c² = m < z, contradicting minimality. Corollary:
       x⁴ + y⁴ = w⁴ has no solutions.
- **Extremal principle.** Take a maximal or minimal object and show that anything else would beat
  it. Example: in a tournament, a vertex v of maximum out-degree reaches every vertex in ≤ 2 steps.
  If u were not reached, u would beat v and every vertex v beats, so outdeg(u) ≥ outdeg(v) + 1.
  First check that the extremum exists. A finite set or an ℕ-valued quantity is safe. "The closest
  point of an infinite set" may not exist, and "the largest prime" exists only inside a
  contradiction that assumed finitely many primes.

## 5. Pigeonhole patterns, invariants and monovariants

| Pattern | Boxes | Conclusion |
|---|---|---|
| residues | the n residues mod n | among n + 1 integers, two are congruent mod n |
| prefix sums | the residues of S_1, ..., S_n mod n | any n integers contain a nonempty consecutive block with sum ≡ 0 (mod n) |
| odd parts | the odd part m of x = 2^a·m, m ∈ {1, 3, ..., 2n − 1} | n + 1 numbers from {1..2n} contain a divisibility pair (section 11) |
| Erdős-Szekeres | the label (longest increasing, longest decreasing subsequence ending here) | rs + 1 distinct reals contain an increasing subsequence of length r + 1 or a decreasing one of length s + 1 |
| averaging | — | if n quantities sum to more than nm, one exceeds m; some outcome is at least the mean |
| geometry | 4 squares of side 1/2 | among 5 points in a unit square, two are within √2/2 |
| Dirichlet approximation | N intervals [j/N, (j+1)/N) for the fractional parts of 0, α, ..., Nα | some 1 ≤ q ≤ N has ‖qα‖ < 1/N, so α is within 1/(qN) of some p/q |
| infinite | finitely many boxes | infinitely many items put infinitely many in some box |

**Invariants.** Compute a candidate invariant at the start and at the target, and check that every
allowed move preserves it, including edge cases. Different values mean the target is unreachable.

- **Parity.** Removing two opposite corners from a chessboard leaves 32 squares of one colour and
  30 of the other. Every domino covers one of each, so no tiling exists.
- **Colouring mod k.** A 10 × 10 board cannot be tiled by 1 × 4 tiles. Colour (i, j) by
  (i + j) mod 4: every tile covers one cell of each colour, so 25 tiles cover 25 of each, but the
  colour counts are 25, 26, 25, 24.
- **Weighted sums.** For "replace a, b by ..." processes, compute the sum, the sum of squares, the
  product, or Σx_i mod k before and after a move.

**Monovariants.** A quantity in ℕ, or in any well-ordered set, that strictly decreases at every
step proves termination. Examples: the number of inversions under adjacent swaps of out-of-order
pairs; the second argument in Euclid's algorithm. Local search for a cut: moving a vertex that has
more neighbours on its own side raises the cut by ≥ 1, and the cut is at most |E|. So the search
stops, and the final cut has ≥ |E|/2 edges.

## 6. Double counting, bijections, compactness, diagonalization

- **Handshake.** Counting (vertex, incident edge) pairs gives Σ deg v = 2|E|, so the number of
  odd-degree vertices is even.
- **Σ_k k C(n,k) = n 2^(n−1).** Count (committee, chair) pairs: choose the committee and then its
  chair, or choose the chair (n ways) and then any subset of the other n − 1 people.
- **Bijection hygiene.** Show the map lands in the target, give the inverse explicitly, and check
  both compositions are the identity. Brute-force both directions for n ≤ 8; the reflection check
  in `combinatorics-generating-functions` section 2 is the model.
- **König's lemma.** An infinite rooted tree in which every vertex has finitely many children has an
  infinite path. Local finiteness is essential: a root with infinitely many children, the k-th
  starting a path of length k, gives an infinite tree with no infinite path.
- **de Bruijn-Erdős.** A graph is k-colourable iff every finite subgraph is. The countable case
  follows from König; the uncountable case needs the axiom of choice.
- **Topological compactness.** A continuous function on a compact set attains its extrema. f(x) = x
  on (0, 1) attains neither, so compactness is the hypothesis that matters.
- **Cantor.** No f: ℕ → P(ℕ) is onto: D = {n : n ∉ f(n)} differs from each f(n) at n.
- **Halting problem.** If H decided halting, define D(x) = "loop if H says x halts on x, else halt";
  running D on D is contradictory. The diagonal object must lie in the class, and D is a program
  because H is.
- **Diagonalising the reals.** Avoid the digits 0 and 9 when diagonalising decimal expansions,
  because 0.0999... = 0.1000....

## 7. When stuck

| Move | Concretely |
|---|---|
| specialise | n = 1, 2, 3; p = 2; the zero matrix; a degenerate triangle; tabulate and guess |
| generalise | a stronger or more general statement can be easier (the inventor's paradox); add a parameter |
| auxiliary object | a point, line, variable, potential function, graph or generating function |
| symmetry, with a justified WLOG | order the variables only if the statement is symmetric under that permutation; name the symmetry |
| change representation | GFs, matrices, graphs, complex numbers for plane geometry, binary for subsets, probability for counting, linear algebra over F₂ for parity |
| work backwards | what would immediately imply the goal? chain back to the hypotheses |
| find the unused hypothesis | find the counterexample that appears when it is dropped; the proof must use it there |
| find the boundary | where does the statement become false? the proof idea lives near there |
| a related solved problem | a special case, the converse, the continuous analogue; reuse its technique |

## 8. Proof template

```
Theorem.     <exact statement: quantifiers, domains, hypotheses>
Assumptions. <list; mark where each one is used>
Notation.    <symbols and conventions, e.g. whether ℕ includes 0>
Lemma 1.     <statement>   Proof. ... ∎
Proof.
  Step 1. <one claim>. By <fact or lemma>, applicable because <hypothesis check>.
  Step 2. ...
  Therefore <the theorem exactly as stated>. ∎
Checks.      <computations run, each with its status label>
Remarks.     <sharpness: equality cases; examples showing hypotheses cannot be dropped>
Open.        <conjectured extensions, labelled>
Rigor.       sketch / full / computer-assisted / formal
```

- **One claim per sentence.** Every step names the fact it uses and why that fact applies.
- **Explicit constants and dependencies.** "δ = min(1, ε/(2M + 1)), depending on ε and M only."
- **State the rigor level.**
  - sketch: the key ideas;
  - full: every step justified;
  - computer-assisted: name the computation and whether it is exact;
  - formal: give the Lean file and the axioms (`lean4-mathlib-formalization`).
- **Definitions.** Define each symbol before using it, and keep names consistent.
- **No bare "clearly".** "Clearly" and "it is easy to see" need the one-line reason or nothing.

## 9. Hygiene and fallacy checklist

| Fallacy | One-line detector |
|---|---|
| circularity | trace each step's justification: does any step lean on the conclusion or an equivalent? |
| affirming the consequent | did we show Q and P ⇒ Q, then claim P? |
| converse proved instead | is the proved direction the one asked for? |
| induction step that uses P(n+1) | does the step cite the statement at n + 1? |
| step invalid at the smallest n | instantiate the step at the last base case by hand |
| sign error with inequalities | for every multiplication or division of an inequality, is the factor's sign recorded? |
| division by zero, log or √ of a negative | is every denominator and argument checked on the whole domain? |
| reused existential witness | are two separate "there exists x" claims later used with the same x? |
| quantifier swap | ∀ε ∃δ vs ∃δ ∀ε; pointwise vs uniform |
| unjustified interchange | is a limit, sum, integral or derivative swapped without a named theorem? |
| examples as proof | a universal claim "checked" on cases: n² + n + 41 is prime for n ≤ 39, but not at n = 40 (41²) |
| WLOG breaks an asymmetric hypothesis | is every hypothesis invariant under the symmetry used? |
| existence assumed | "let x be the largest ..." for a set that may be empty or infinite |
| finite reasoning on infinite sets | a pigeonhole or extremal step used where finiteness fails |
| wrong final statement | is the conclusion the theorem asked for, not a special case or a weaker bound? |

## 10. Auditing a proof

1. **Check the theorem first.** Restate it (section 1) and test small cases. A false theorem ends
   the audit with a counterexample.
2. **Grade every step.** Number the steps and give each a verdict from the table below.
3. **Attack the lemmas.** Try to break each one on small or extreme cases by computer (brute force,
   exact arithmetic) before reading its proof closely.
4. **Report the first fatal error.** That is the first step whose failure breaks the conclusion.
   Give a counterexample to the step, and say whether the theorem survives (by another proof or a
   known result) or falls (a counterexample to the theorem).
5. **Sharpness.** Add equality cases, hypotheses that cannot be dropped (with examples), and whether
   the constants are optimal.
6. **Label the verdict.** Use the hub labels. "The proof is wrong" is a different finding from "the
   theorem is false".

| Verdict | Meaning |
|---|---|
| correct | follows from earlier steps and cited facts whose hypotheses are checked |
| gap | probably true but unjustified; say what is missing and whether it is routine |
| error | false as stated; give a counterexample to the step |
| unjustified citation | the theorem is misquoted, or its hypotheses are not verified here |

## 11. Worked examples

**A. Pigeonhole on odd parts** (hub example C). Claim: every (n+1)-subset of {1, ..., 2n} contains
distinct a, b with a ∣ b.

- **Proof.** Write x = 2^a·m with m odd. The odd parts m ∈ {1, 3, ..., 2n − 1} take n values (the
  boxes), so two of the n + 1 numbers share m: 2^a·m and 2^b·m with a < b. The first divides the
  second.
- **Sharpness.** {n + 1, ..., 2n} has n elements and no divisibility pair, because 2x > 2n for each
  element x. So n + 1 cannot be lowered.

```python
from itertools import combinations
def has_pair(S):
    return any(b % a == 0 for a, b in combinations(sorted(S), 2))
for n in range(1, 11):
    assert all(has_pair(S) for S in combinations(range(1, 2*n + 1), n + 1))   # the theorem
    assert not has_pair(range(n + 1, 2*n + 1))                                 # sharpness
```

Status: Proved, sharp; Verified for n ≤ 10.

**B. Auditing "all horses are the same colour".** Claim: in every set of n ≥ 1 horses, all horses
have the same colour. "Proof": P(1) is trivial. Given h_1, ..., h_{n+1}, the sets
A = {h_1, ..., h_n} and B = {h_2, ..., h_{n+1}} have n horses each, so each is monochromatic; they
overlap, so all n + 1 horses share one colour.

| Step | Claim | Verdict |
|---|---|---|
| 1 | P(1) | correct |
| 2 | A and B are each monochromatic | correct: each has n horses |
| 3 | A ∩ B ≠ ∅, so the two colours agree | error at n = 1: A = {h_1}, B = {h_2}, A ∩ B = ∅ |
| 4 | therefore P(n+1) | rests on step 3 |

- **First fatal error.** Step 3 at n = 1. Counterexample to the step: one black and one white horse,
  where P(1) holds and P(2) fails.
- **What survives.** For n ≥ 2 the step is valid, since A ∩ B = {h_2, ..., h_n} ≠ ∅. The argument
  would therefore need P(2) as its base case, and P(2) is false.
- **Verdict.** The theorem is False: two horses of different colours. Lesson: instantiate the step
  at the smallest n where it is used.

## 12. Pitfalls

- **Proving something else.** A special case, a weaker bound or the converse reported as the
  original theorem.
- **Citing a theorem by name without checking its hypotheses in place** (compactness, connectedness,
  simple graphs, continuity).
- **Label inflation.** "Verified for n ≤ 10⁶" becoming "proved" in the summary.
- **Hiding the hard step** inside "similarly" or "by symmetry".
- **No lemma structure.** Split long proofs into lemmas with explicit hypotheses, each at most a
  page.
- **Trusting a picture.** A diagram suggests; check the degenerate configurations.
- **A failed attempt treated as evidence of falsity.** Only a counterexample shows that.

Related: `inequality-proving`, `combinatorics-generating-functions`, `graph-theory-probabilistic-method`, `lean4-mathlib-formalization`, `adversarial-verification`, `first-principles`, hub `mathematics-toolkit`
