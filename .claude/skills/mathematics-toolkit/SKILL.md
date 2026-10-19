---
name: mathematics-toolkit
description: "Mathematics working pack: statement-shape to proof-technique selection (induction, contradiction, contrapositive, pigeonhole, extremal principle, invariants, double counting, probabilistic method, compactness, diagonalization), problem-solving heuristics, checking with computation (SymPy, mpmath, interval arithmetic, OEIS, Z3, Lean 4 with Mathlib, Julia), key inequalities, linear algebra and analysis facts with their hypotheses, and rules for writing rigorous proofs that separate proved, verified and conjectured claims. Load for any proof, derivation, counterexample search or mathematical claim check."
when_to_use: "Proving or disproving a statement, checking a derivation or identity, bounding a quantity, solving a competition or research-style problem, auditing another agent's math, or deciding how much a numerical experiment actually establishes."
---

# Mathematics toolkit

A mathematical answer is only as strong as its weakest unmarked step. The rule of this skill:
every claim you return carries a status label, every proof step names the fact it uses and where
its hypotheses were checked, and computation is used aggressively for discovery and checking but
never presented as proof of an infinite statement.

## 0. Status labels (use them in every output)

| Label | Meaning | Allowed evidence |
|---|---|---|
| Proved | complete argument given here, all hypotheses checked | the proof itself |
| Proved (formal) | checked by Lean/Coq/Isabelle | file path + build command + exit status |
| Known | standard theorem | precise citation (name, source, statement with hypotheses) |
| Proved assuming X | conditional | X stated exactly |
| Verified for finite range | exact computation over a finite set | code, range, exact arithmetic |
| Numerical evidence | floating-point or sampled checks | precision, sample size, worst case found |
| Conjectured | believed, not proved | heuristic reasons |
| False | counterexample | the explicit counterexample, checked exactly |

Never upgrade a label in the summary. "Verified for n ≤ 10^6" stays that in the Result section.

## 1. Workflow

1. **Restate** the problem in symbols. List hypotheses, quantifier order, domain (ℕ includes 0 or
   not; real or complex; finite or infinite), and what exactly must be shown.
2. **Experiment.** Small cases by hand and by machine (section 5). Tabulate. Look the sequence up
   in OEIS. Try to break the statement: extreme, degenerate and random inputs.
3. **Conjecture** the precise form, including where it fails (boundary cases are often where the
   proof idea lives).
4. **Choose a technique** from the statement shape (section 2), then try it on the smallest
   nontrivial case first.
5. **Prove.** Write the argument as lemmas with explicit hypotheses. If stuck, strengthen the
   claim (induction), weaken it (prove a special case), or change representation (section 4).
6. **Check.** Re-derive key steps by computation (symbolic identities, numerical spot checks at
   random points, edge cases). Run the hygiene checklist (section 8).
7. **Present** with status labels, separating what is proved from what is conjectured.

## 2. Statement shape → technique

| Statement shape | First technique to try | Watch for |
|---|---|---|
| ∀ n ∈ ℕ, P(n) | induction (weak, strong, or on a stronger statement) | base cases; step must use only proven cases |
| ∀ finite structures (graphs, trees, words) | structural induction, induction on size, minimal counterexample | removing an element must keep the class |
| "No X exists", irrationality, infinitude | contradiction | contradiction must be with a hypothesis or a proven fact |
| P ⇒ Q where ¬Q is concrete and usable | contrapositive ¬Q ⇒ ¬P | not the converse |
| Some two objects share a property | pigeonhole: n objects, k boxes → a box with ≥ ceil(n/k) | designing boxes is the whole proof |
| Existence of an object with property | construction; if none obvious, probabilistic method or counting | expectation and union bound arithmetic |
| A process terminates / reaches a state | monovariant (strictly decreasing in a well-ordered set) | must decrease every step |
| A configuration is unreachable | invariant (parity, mod, coloring, sum, determinant) | invariant must hold initially and be preserved |
| Two counts are equal / combinatorial identity | double counting or bijection | the bijection must be invertible on the stated sets |
| Optimum is achieved / extremal configuration | extremal principle: take a max/min element and derive structure | existence of the extremum (finite or compact) |
| Statement about all infinite objects from all finite ones | compactness (König, de Bruijn-Erdős, logical compactness, topological compactness) | needs local finiteness / closedness |
| Set is uncountable / not enumerable / undecidable | diagonalization | the diagonal object must be in the class |
| Inequality between expressions | known inequalities (section 6), SOS, convexity, smoothing, tangent-line trick | equality cases tell you which tool fits |
| Limit / convergence | ε-δ with explicit choice, squeeze, monotone + bounded, dominated convergence | interchange of limits needs a theorem |
| Polynomial identity | compare coefficients, or check deg + 1 points, or Schwartz-Zippel random test | random test is evidence unless points are exact and enough |

## 3. Technique templates

**Induction.** State P(n) exactly. Base: P(n₀) (and more bases if the step jumps by more than 1).
Step: assume P(m) for all n₀ ≤ m ≤ n (strong) and prove P(n+1). If the step fails, strengthen P:
bounds like Σ 1/k² < 2 are not inductive, Σ 1/k² ≤ 2 - 1/n is (worked example A).

**Contradiction.** "Suppose not: there is x with ¬P(x)." Derive a statement contradicting a
hypothesis or a proven fact. Prefer a direct or contrapositive proof when the contradiction is
just ¬Q reached from ¬Q (a disguised contrapositive), because it is easier to check.

**Pigeonhole.** Define boxes so that two items in one box give the conclusion. Generalised:
if Σ of n quantities exceeds k·m, one exceeds m. Infinite version: infinitely many items in
finitely many boxes ⇒ some box infinite.

**Extremal principle.** Consider the minimal counterexample, longest path, maximal independent set,
lexicographically smallest solution. Show that a smaller counterexample or longer path would exist.
Requires the extremum to exist (finite set, well-ordering, compactness).

**Invariants and monovariants.** Compute a quantity mod 2, mod 3, a weighted sum, a coloring
count, an area or a determinant before and after each allowed move. Invariant ⇒ unreachable
states; monovariant bounded below in ℕ ⇒ termination.

**Double counting.** Count one set two ways: incidences (vertex, edge) give Σ deg = 2|E|; pairs
(element, subset) give Σ_k k C(n,k) = n 2^(n-1).

**Probabilistic method.** Random object X; show P(bad) < 1 (union bound) or E[count of bad] < 1, or
E[f] ≥ t ⇒ some instance has f ≥ t. Alteration: delete one element per bad event. Lovász Local
Lemma: each bad event has probability ≤ p and depends on ≤ d others, e p (d + 1) ≤ 1 ⇒ positive
probability no bad event happens.

**Compactness.** Topological: a continuous function on a compact set attains its extrema;
sequences in compact metric spaces have convergent subsequences. Combinatorial: König's lemma
(infinite, locally finite tree has an infinite path); de Bruijn-Erdős (an infinite graph is
k-colourable iff every finite subgraph is; uses the axiom of choice).

**Diagonalization.** Enumerate the candidates f₁, f₂, ...; build g differing from f_i at input i.

## 4. Heuristics when stuck

- Specialise: n = 1, 2, 3; a degenerate triangle; the zero matrix; p = 2. Generalise: the
  inventor's paradox, a stronger statement can be easier to prove.
- Draw it. Add an auxiliary point, line, variable or object.
- Exploit symmetry: WLOG orderings (justify them), symmetric sums, group actions (Burnside).
- Change representation: generating functions, matrices, graphs, complex numbers for plane
  geometry, binary for subsets, probability for counting, linear algebra over F₂ for parity.
- Work backwards from the goal; or forwards from all hypotheses (unused hypotheses are a hint).
- Look at the equality case of an inequality; look for where the claim becomes false.
- Solve a related solved problem; check the dimensions/degrees/units of every expression.
- Find a monovariant or invariant for any process.
- Bound both sides: prove ≤ and ≥ separately.

## 5. Checking with computation

What computation establishes:

| Computation | Establishes | Does not establish |
|---|---|---|
| Exact arithmetic over a finite set (integers, rationals, finite fields) | the statement on that set (label: verified) | anything beyond it |
| Explicit counterexample checked exactly | falsity (label: False) | nothing more needed |
| Symbolic simplification to 0 | identity, if the CAS assumptions (branches, domains) match yours | identities involving sqrt/log branch choices without assumptions |
| Interval / ball arithmetic | rigorous enclosures of a computed value | properties at untested inputs |
| Floating point, random sampling | evidence, plus candidate counterexamples to recheck exactly | proof |
| Lean / Coq / Isabelle compiled proof | the formal statement | that the formal statement says what you meant (read it) |

Fast tools (commands and patterns in [computational checking](references/computational-checking.md)):

```python
from sympy import symbols, summation, simplify, factor, limit, series, oo, sin, log
n, k = symbols("n k", integer=True, positive=True)
x = symbols("x", real=True)
summation(2*k - 1, (k, 1, n))                       # n**2
simplify(summation(1/(k*(k+1)), (k, 1, n)))        # n/(n + 1)
limit(sin(x)/x, x, 0), series(log(1 + x), x, 0, 5)
```

- Integer sequences: compute the first 10-20 terms exactly and query OEIS
  (`https://oeis.org/search?q=1,2,5,14,42&fmt=json`); cite the A-number, then still prove it.
- High precision: `mpmath` with `mp.dps = 50`; compare runs at two precisions; a value stable to
  45 digits that matches a closed form is strong evidence, identified with `mpmath.identify` or
  PSLQ, not a proof.
- Rigorous numerics: `mpmath.iv`, python-flint (arb balls), Julia IntervalArithmetic.jl.
- Finite logic and small existence questions: Z3 or a SAT solver; nonlinear integer arithmetic is
  undecidable in general, so treat `unknown` as unknown.
- Formal proof: Lean 4 + Mathlib when the toolchain is available; tactics `norm_num`, `decide`,
  `omega`, `linarith`, `nlinarith`, `positivity`, `ring`, `field_simp`, `simp`, `gcongr`,
  `exact?` to search the library.

Counterexample search protocol: exhaustive over small parameters → random sampling with a fixed
seed → adversarial search (minimise the slack of the inequality with an optimiser from many
starts) → recheck any hit with exact arithmetic before reporting.

## 6. Inequalities (top ten; full catalogue in [inequalities](references/inequalities.md))

| Inequality | Statement | Equality |
|---|---|---|
| AM-GM | (a₁ + ... + a_n)/n ≥ (a₁ ⋯ a_n)^(1/n), a_i ≥ 0 | all equal |
| Cauchy-Schwarz | (Σ a_i b_i)² ≤ (Σ a_i²)(Σ b_i²); |⟨u, v⟩| ≤ ‖u‖‖v‖ | proportional |
| Jensen | φ convex ⇒ φ(E X) ≤ E φ(X) | X constant or φ affine on support |
| Hölder | Σ|a_i b_i| ≤ ‖a‖_p ‖b‖_q, 1/p + 1/q = 1 | |a|^p ∝ |b|^q |
| Triangle / Minkowski | ‖u + v‖ ≤ ‖u‖ + ‖v‖ | same direction |
| Bernoulli | (1 + x)^r ≥ 1 + r x for x ≥ -1, r ≥ 1 | x = 0 or r = 1 |
| Exponential | 1 + x ≤ e^x for all real x; ln(1 + x) ≤ x for x > -1 | x = 0 |
| Markov / Chebyshev | P(X ≥ a) ≤ E X/a (X ≥ 0); P(|X - μ| ≥ kσ) ≤ 1/k² | two-point distributions |
| Chernoff / Hoeffding | P(S - E S ≥ t) ≤ exp(-2t²/Σ(b_i - a_i)²), independent bounded | asymptotically tight |
| Binomial bounds | (n/k)^k ≤ C(n, k) ≤ (e n/k)^k | k = 1 (lower) |

Choosing: the equality case tells you which inequality can work (AM-GM and Cauchy-Schwarz need
"all equal" or "proportional" at the optimum). Homogenise first; normalise (e.g. a + b + c = 1)
second.

## 7. Facts with hypotheses (catalogue in [linear algebra and analysis facts](references/linear-algebra-analysis.md))

The usual error is not a wrong theorem but a missing hypothesis. Before citing, check it:

| Fact | Hypothesis people forget |
|---|---|
| Real symmetric ⇒ orthogonally diagonalisable, real eigenvalues | symmetric (normal for unitary diagonalisation over ℂ) |
| A, B commute ⇒ simultaneously triangularisable; diagonalisable if both diagonalisable | over ℂ (algebraically closed field) for triangularisation; both diagonalisable for simultaneous diagonalisation |
| det(AB) = det A det B; tr(AB) = tr(BA) | square for det; tr(ABC) = tr(CAB) but ≠ tr(ACB) in general |
| Continuous on [a, b] ⇒ bounded, attains max | closed and bounded interval (compact) |
| Limit of derivatives = derivative of limit | uniform convergence of derivatives + convergence at a point |
| ∫ lim = lim ∫ | dominated or monotone convergence, or uniform convergence on a finite measure space |
| Swap sums / integrals (Fubini) | absolute integrability (Tonelli for non-negative) |
| Rearranging a series | absolute convergence (Riemann rearrangement otherwise) |
| L'Hôpital | 0/0 or ∞/∞ form and the limit of f'/g' exists |
| Taylor with remainder | f ∈ C^(n+1) on the interval |
| Mean value theorem | continuous on [a, b], differentiable on (a, b), real-valued |

## 8. Writing the proof

Template:

```
Theorem. <exact statement with all quantifiers and domains>
Assumptions. <list; mark which are used where>
Notation. <symbols>
Proof.
  Lemma 1. <statement>  Proof. ... ∎
  Step 1. <claim>. By <fact/lemma>, applicable because <hypothesis check>.
  ...
  Therefore <conclusion>. ∎
Checks. <computational checks run, with status labels>
Remarks. <sharpness: example showing a hypothesis cannot be dropped; equality cases>
Open. <conjectured extensions, labelled>
```

Hygiene checklist (run on your own proof and on any proof you audit):
- [ ] Quantifier order correct (∀ε ∃δ vs ∃δ ∀ε); dependencies of constants stated (δ may depend on ε, x).
- [ ] No division by a quantity that can be 0; no log/sqrt of a possibly negative quantity.
- [ ] Every "WLOG" justified by a symmetry that actually holds.
- [ ] Base cases cover every case the step does not reach; the step does not use P(n+1).
- [ ] Every limit interchange, rearrangement or differentiation under the integral cites its theorem.
- [ ] Edge cases: n = 0 or 1, empty set, degenerate geometry, equal elements, boundary of domain.
- [ ] Converse not used in place of the statement; necessary vs sufficient conditions distinguished.
- [ ] "Clearly" and "it is easy to see" replaced by the argument, or justified in a line.
- [ ] Examples are not used as proof of a universal claim.
- [ ] Dimensions/degrees/homogeneity of both sides agree.
- [ ] The final statement proved is the statement asked (not a special case or a weaker bound).

## 9. Worked examples

**A. Strengthen to induct.** Claim: Σ_{k=1}^n 1/k² < 2 for all n ≥ 1. Induction on the claim
fails (adding 1/(n+1)² to something < 2 gives no bound). Prove P(n): Σ_{k=1}^n 1/k² ≤ 2 - 1/n.
Base n = 1: 1 ≤ 1. Step: 2 - 1/n + 1/(n+1)² ≤ 2 - 1/(n+1) ⇔ 1/(n+1)² ≤ 1/n - 1/(n+1) = 1/(n(n+1)),
true since n < n + 1. Hence Σ ≤ 2 - 1/n < 2. Status: Proved. Check: SymPy partial sums for
n ≤ 1000 exact rationals satisfy the stronger bound (Verified, consistent).

**B. Evidence is not proof.** Claim: n² + n + 41 is prime for every n ≥ 0. Exact check for
n = 0..39 finds only primes. n = 40 gives 1681 = 41² (and n = 41 gives 41·43). Status: False,
counterexample n = 40. The lesson to report: 40 consecutive confirmations had zero proof value.

**C. Pigeonhole with designed boxes.** Claim: any n + 1 numbers from {1, ..., 2n} contain two
with one dividing the other. Write each number as 2^a · m with m odd; m ∈ {1, 3, ..., 2n - 1},
n possible values (boxes). Two of the n + 1 numbers share m: 2^a m and 2^b m with a < b, so the
first divides the second. Sharpness: {n + 1, ..., 2n} has n numbers and no divisibility pair, so
n + 1 cannot be lowered. Status: Proved, sharp.

**D. Probabilistic method.** Claim: R(k, k) > 2^(k/2) for k ≥ 3. Colour the edges of K_n
uniformly at random, n = floor(2^(k/2)). Expected number of monochromatic K_k:
C(n, k) 2^(1 - C(k,2)) < (n^k/k!) 2^(1 - k(k-1)/2) ≤ 2^(k²/2) 2^(1 - k²/2 + k/2)/k! = 2^(1 + k/2)/k!,
which is < 1 for k ≥ 3 (k = 3: 5.66/6). So some colouring has none. Status: Known (Erdős 1947),
proof reproduced.

## Quality gate before returning

- [ ] Every claim labelled (section 0); summary does not upgrade any label.
- [ ] Each cited theorem appears with its hypotheses checked in place.
- [ ] At least one computational check on every identity, closed form or numerical constant.
- [ ] Sharpness or equality cases discussed when a bound is proved.
- [ ] Counterexamples verified with exact arithmetic.
- [ ] Any output past ~60 lines or ~3k characters (long derivations, tables, check logs) written
      to `<out_dir>/<YYYYMMDD-HHMM>-<slug>.md` (out_dir from the <stack-context> header) with line
      anchors; reply has the statement, the proof skeleton, the status table and the path.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `combinatorics-generating-functions` | counting objects, solving or guessing a recurrence, or proving an enumeration identity |
| `graph-theory-probabilistic-method` | Graph theory and the probabilistic method for proofs and counterexamples: core theorems with exact hypotheses, extremal and Ramsey results, spectral graph th... |
| `inequality-proving` | proving, refuting, sharpening or auditing any bound, estimate or inequality |
| `lean4-mathlib-formalization` | a proof should be machine-checked or a Lean file must compile |
| `matrix-decompositions-conditioning` | solving, factorising, or deciding whether to trust a matrix computation |
| `number-theory-modular` | solving congruences or integer equations, or when writing or reviewing modular-arithmetic code |
| `numerical-error-analysis` | a computed number must be trusted or a numerical bug is suspected |
| `ode-pde-analytic-methods` | an ODE or PDE needs an analytic solution or a qualitative guarantee |
| `optimization-convex-nonconvex` | anything is minimised, fitted, allocated or scheduled |
| `probability-distributions-limits` | deriving, bounding or checking any probability, expectation, distribution or limit |
| `proof-techniques-and-writing` | Choosing a proof technique from the statement's shape and writing or auditing the proof rigorously: restating with quantifiers, induction variants, contradic... |
| `real-complex-analysis` | a proof or derivation involves limits, series, integrals, analytic estimates or contour integrals |
| `statistical-inference-bayesian` | data must support a claim or an experiment must be designed |
| `sympy-symbolic-verification` | deriving, simplifying or machine-checking a formula |
