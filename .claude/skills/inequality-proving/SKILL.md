---
name: inequality-proving
description: "Proves, sharpens and machine-checks inequalities: classical catalogue with hypotheses and equality cases, choosing a technique from where equality sits, SOS and Schur/Muirhead, uvw/pqr, tangent-line trick, smoothing, Lagrange multipliers with boundary checks, and rigorous interval and SOS certificates. Load when proving, refuting, sharpening or auditing any bound, estimate or inequality."
when_to_use: "Prove or refute an inequality (competition, research, algorithm or error analysis), tighten a constant, locate equality cases, audit a 'by AM-GM' or 'by Cauchy-Schwarz' step, certify a polynomial is nonnegative (SOS Gram matrix, interval branch-and-bound), hunt counterexamples to cyclic or symmetric inequalities, or close a Lean goal with nlinarith, positivity or gcongr."
---

# Inequality proving

An inequality proof is a chain of named facts, each used where its hypotheses hold, that is tight
exactly at the equality case. Find the equality case first: it chooses the technique, and it is the
first thing a checker tests. Label results with the hub's status labels (Proved, Proved (formal),
Verified for finite range, Numerical evidence, False).

Deep material: [certificate and interval scripts](references/certificates-scripts.md) |
[extended catalogue](references/catalogue-extended.md)

## 1. Workflow

1. **Domain and signs.** Write each variable's domain. Mark every factor you will multiply, divide
   or square by with its sign; an unknown sign forces a case split.
2. **Homogeneity.** If both sides are homogeneous of the same degree and every constraint is
   homogeneous, normalise (a + b + c = 1, abc = 1, or max = 1). If a constraint is not homogeneous
   (a + b + c = 3 together with abc ≤ 1, say), homogenise with it first (replace 1 by (a + b + c)/3)
   instead of scaling.
3. **Locate equality numerically.** Multistart minimisation of LHS − RHS (code below). Record every
   minimiser: symmetric interior, boundary (a variable 0, two equal), non-symmetric, or none (strict).
4. **Confirm equality exactly** at each candidate with SymPy rationals.
5. **Pick the technique** from the table, write the chain, then evaluate every intermediate step at
   random points: a chain with one false link proves nothing.
6. **Certify**: exact SOS identity or Gram matrix, interval branch-and-bound, or Lean.

```python
import numpy as np
from scipy.optimize import minimize

def equality_hunt(F, n, starts=300, seed=0, tol=1e-9):
    """Minimise a homogeneous F over the open simplex; return the best value and every
    distinct minimiser (coordinates sorted, so symmetric copies merge)."""
    rng, out = np.random.default_rng(seed), []
    to_simplex = lambda u: np.exp(u - u.max()) / np.exp(u - u.max()).sum()
    for _ in range(starts):
        r = minimize(lambda u: F(*to_simplex(u)), rng.normal(scale=3, size=n), method="Nelder-Mead",
                     options=dict(xatol=1e-10, fatol=1e-14, maxiter=5000))
        out.append((r.fun, tuple(np.round(np.sort(to_simplex(r.x))[::-1], 4))))
    best = min(v for v, _ in out)
    return best, sorted({p for v, p in out if v <= best + tol})

equality_hunt(lambda a, b, c: a/(b + c) + b/(c + a) + c/(a + b) - 1.5, 3)  # -2.2e-16, [(1/3,1/3,1/3)]
```

Start scale 3 sends coordinates to e^-10 or so, so boundary minima show up: Schur's
a(a-b)(a-c) + ... returns both (1/3, 1/3, 1/3) and (1/2, 1/2, 0). A minimum of -1e-16 is rounding,
not a counterexample; a minimum of -3e-4 is a candidate to recheck exactly (section 10, Shapiro).

| Equality sits at | Try first | Usually fails |
|---|---|---|
| symmetric interior point only | AM-GM, Cauchy-Schwarz (Engel), Jensen, tangent line, SOS | — |
| symmetric point and a boundary point (a = b, c = 0) | Schur, SOS with S-criteria, uvw/pqr | AM-GM, Jensen (their equality is all-equal only) |
| boundary only | convexity in one variable, smoothing toward the boundary, Lagrange on faces | symmetric-point tools |
| non-symmetric interior point (Vasc: a:b:c = sin²(4π/7) : sin²(2π/7) : sin²(π/7)) | SOS by SDP, explicit quadratic forms | AM-GM, symmetric smoothing |
| weighted point (a = 2b) | weighted AM-GM, Hölder with weights matched to the point | unweighted forms |
| none (infimum not attained) | limits at the boundary and infinity, monotonicity, slack | Lagrange (no interior critical point) |

## 2. Catalogue: means, convexity, sums and products

| Name | Statement | Hypotheses | Equality |
|---|---|---|---|
| Power mean | M_r ≤ M_s for r ≤ s; M_r = (Σ w_i a_i^r)^(1/r), M_0 = Π a_i^(w_i) | a_i > 0, w_i ≥ 0, Σ w_i = 1 | all a_i equal |
| QM-AM-GM-HM | sqrt(Σa²/n) ≥ Σa/n ≥ (Πa)^(1/n) ≥ n/Σ(1/a) | a_i > 0 | all equal |
| Weighted AM-GM | Σ w_i a_i ≥ Π a_i^(w_i) | a_i ≥ 0, w_i ≥ 0, Σ w_i = 1 | all a_i with w_i > 0 equal |
| Young | ab ≤ a^p/p + b^q/q | a, b ≥ 0, p > 1, 1/p + 1/q = 1 | a^p = b^q |
| Jensen | φ(Σ w_i x_i) ≤ Σ w_i φ(x_i) | φ convex on an interval holding the x_i, weights as above | all x_i equal (φ strictly convex) or φ affine on their hull |
| Karamata | x ≻ y ⇒ Σ φ(x_i) ≥ Σ φ(y_i) | φ convex; x majorises y (sorted decreasingly, partial sums ≥, totals equal) | x a permutation of y (φ strictly convex) |
| Hermite-Hadamard | φ((a+b)/2) ≤ (1/(b-a)) ∫_a^b φ ≤ (φ(a)+φ(b))/2 | φ convex on [a, b] | φ affine |
| Schur (degree t) | Σ a^t (a - b)(a - c) ≥ 0 | a, b, c ≥ 0, t > 0 | a = b = c, or two equal and the third 0 |
| Cauchy-Schwarz | (Σ a_i b_i)² ≤ Σ a_i² Σ b_i² | real (use \|·\| for complex) | a ∥ b |
| Engel (Titu, Sedrakyan) | Σ x_i²/y_i ≥ (Σ x_i)²/Σ y_i | y_i > 0 | x_i/y_i constant |
| Hölder | Σ \|a_i b_i\| ≤ ‖a‖_p ‖b‖_q | 1/p + 1/q = 1, p ∈ [1, ∞] | \|a_i\|^p ∝ \|b_i\|^q |
| Minkowski | ‖a + b‖_p ≤ ‖a‖_p + ‖b‖_p | p ≥ 1 (reverses for 0 < p < 1 on nonnegative vectors) | a, b parallel, same direction |
| Chebyshev sum | n Σ a_i b_i ≥ Σ a_i Σ b_i | a, b similarly ordered (reverse if oppositely) | one sequence constant |
| Rearrangement | Σ a_i b_σ(i) is largest similarly ordered, smallest oppositely ordered | real sequences | ties among the a_i or b_i |
| Abel summation | Σ_{k≤n} a_k b_k = A_n b_n - Σ_{k<n} A_k (b_{k+1} - b_k), A_k = Σ_{j≤k} a_j | none (identity) | identity |
| Bernoulli | (1 + x)^r ≥ 1 + r x | x ≥ -1 and r ≥ 1 or r ≤ 0; reversed for 0 ≤ r ≤ 1 | x = 0 (or r ∈ {0, 1}) |
| Weierstrass product | Π (1 - a_i) ≥ 1 - Σ a_i | a_i ∈ [0, 1] | at most one a_i nonzero |

More (Maclaurin, Newton, multi-sequence Hölder, Aczél, Popoviciu, Carleman, Hardy, Vasc, Shapiro's
limits): [extended catalogue](references/catalogue-extended.md).

## 3. Elementary-function and combinatorial estimates

```
1 + x ≤ e^x                          all real x
e^x ≤ 1/(1 - x)                      x < 1
x/(1 + x) ≤ ln(1 + x) ≤ x            x > -1
ln x ≤ x - 1                         x > 0
sin x ≤ x (x ≥ 0);  sin x ≥ 2x/π     x ∈ [0, π/2] (Jordan)
cos x ≥ 1 - x²/2                     all real x
(1 - x)^n ≥ 1 - n x                  x ≤ 1, n ∈ ℕ
(1 + 1/n)^n < e < (1 + 1/n)^(n+1)    n ≥ 1
tanh x ≤ x ≤ tan x                   x ∈ [0, π/2)
Stirling:   n! = sqrt(2πn)(n/e)^n e^(r_n), 1/(12n+1) < r_n < 1/(12n);  sqrt(2πn)(n/e)^n ≤ n! ≤ e sqrt(n)(n/e)^n
Binomial:   (n/k)^k ≤ C(n,k) ≤ (e n/k)^k  (1 ≤ k ≤ n);  4^n/(2 sqrt n) ≤ C(2n,n) ≤ 4^n/sqrt(3n+1);
            C(2n,n) ≥ 4^n/(2n+1);  C(2n,n) ~ 4^n/sqrt(πn)
Entropy:    2^(n H(k/n))/(n+1) ≤ C(n,k) ≤ 2^(n H(k/n)),  H(α) = -α log2 α - (1-α) log2(1-α)
            Σ_{k ≤ αn} C(n,k) ≤ 2^(n H(α))   for α ≤ 1/2
Harmonic:   H_n = ln n + γ + 1/(2n) - 1/(12n²) + O(n^-4), γ ≈ 0.5772156649;  ln(n+1) ≤ H_n ≤ 1 + ln n
Primes:     π(x) ~ x/ln x;  Σ_{p≤x} 1/p = ln ln x + M + o(1), M ≈ 0.2615;  p_n ~ n ln n
Integral comparison:  f decreasing ⇒ ∫_1^{n+1} f ≤ Σ_{k=1}^n f(k) ≤ f(1) + ∫_1^n f
```

The Stirling, binomial, entropy and harmonic lines were rechecked exactly for n < 400 (mpmath, 40 digits).
Probability tail bounds (Markov to McDiarmid) live in `probability-distributions-limits`.

## 4. SOS method

**Form.** For symmetric or cyclic f(a, b, c) vanishing at a = b = c, write
f = S_a (b - c)² + S_b (c - a)² + S_c (a - b)². Identities that produce the S's:

```
a² + b² + c² - ab - bc - ca      = ½ Σ (a - b)²
a³ + b³ + c³ - 3abc              = ½ (a + b + c) Σ (a - b)²
2Σa³ - Σ_sym a²b                 = Σ (a + b)(a - b)²          (Σ_sym over all 6 permutations)
Σ a/(b + c) - 3/2                = Σ (a - b)² / (2(a + c)(b + c))
```

**S-criteria** (each proves f ≥ 0; assume a ≥ b ≥ c only if f is symmetric):

| # | Conditions | Why |
|---|---|---|
| 1 | S_a, S_b, S_c ≥ 0 | sum of nonnegative terms |
| 2 | a ≥ b ≥ c; S_b ≥ 0, S_a + S_b ≥ 0, S_c + S_b ≥ 0 | (a-c)² ≥ (a-b)² + (b-c)² |
| 3 | a ≥ b ≥ c; S_a ≥ 0, S_c ≥ 0, S_a + 2S_b ≥ 0, S_c + 2S_b ≥ 0 | (a-c)² ≤ 2(a-b)² + 2(b-c)² when S_b < 0 |
| 4 | a ≥ b ≥ c ≥ 0, b > 0; S_b ≥ 0, S_c ≥ 0, a²S_b + b²S_a ≥ 0 | (a-c)/(b-c) ≥ a/b |
| 5 | S_a + S_b + S_c ≥ 0 and S_aS_b + S_bS_c + S_cS_a ≥ 0 | 2×2 quadratic form on x + y + z = 0 is PSD |

**Machine search (Gram matrix SDP).** A polynomial p of degree 2d is SOS iff p = mᵀ G m with m the
monomials of degree ≤ d and G ⪰ 0. Match coefficients (linear constraints on G), solve the SDP, then
round G to rationals and recheck exactly; a floating Gram matrix is not a certificate.

```python
import itertools, cvxpy as cp, sympy as sp
def sos_gram(expr, gens, half_deg, den=2):
    P = sp.Poly(sp.expand(expr), *gens)
    hom = all(sum(e) == P.total_degree() for e in P.monoms())   # homogeneous: use degree-d monomials only
    half = [e for e in itertools.product(range(half_deg + 1), repeat=len(gens))
            if (sum(e) == half_deg if hom else sum(e) <= half_deg)]
    G, pairs = cp.Variable((len(half), len(half)), symmetric=True), {}
    for i, j in itertools.product(range(len(half)), repeat=2):
        pairs.setdefault(tuple(u + v for u, v in zip(half[i], half[j])), []).append((i, j))
    coeffs = dict(P.terms())
    cons = [G >> 0] + [sum(G[i, j] for i, j in ij) == float(coeffs.get(e, 0)) for e, ij in pairs.items()]
    cp.Problem(cp.Minimize(cp.trace(G)), cons).solve(solver=cp.CLARABEL)   # trace pushes to low rank
    Gq = sp.Matrix(G.shape[0], G.shape[1], lambda i, j: sp.Rational(round(G.value[i, j] * den), den))
    m = sp.Matrix([sp.Mul(*[g**k for g, k in zip(gens, e)]) for e in half])
    ok = sp.expand((m.T * Gq * m)[0] - P.as_expr()) == 0 and Gq.is_positive_semidefinite
    return ok, Gq
```

- Nonnegativity on the orthant: substitute a = x², b = y², c = z² (degree doubles) and test global SOS.
- If rounding fails: raise `den`, re-solve with tighter tolerances, drop monomials that must vanish at
  the known zeros (facial reduction), or project the rounded G onto the affine constraints exactly
  (Peyrl-Parrilo) before the PSD check.
- Infeasible SDP does not refute: Motzkin x⁴y² + x²y⁴ - 3x²y² + 1 ≥ 0 (AM-GM) is not SOS (CLARABEL:
  infeasible), while the SDP for (x² + y² + 1)·Motzkin is feasible; multiply by such a positive
  factor. Its Gram matrix does not round at `den=8`, so the exact certificate needs the repairs above.
- Pólya: a form strictly positive on the simplex has (Σ x_i)^N f with all coefficients positive for
  large N; it never works when f has a zero on the simplex (Nesbitt's P below does).
- Julia: SumOfSquares.jl, `model = SOSModel(CSDP.Optimizer)`, `con = @constraint(model, p >= 0)` or
  `@constraint(model, p >= 0, domain = @set(a >= 0 && b >= 0))`, `optimize!(model)`,
  `gram_matrix(con)`, `sos_decomposition(con)`.

## 5. Symmetric-polynomial tools

**Muirhead.** For a_i ≥ 0 and exponent vectors α, β with equal sums: Σ_sym x^α ≥ Σ_sym x^β for all
inputs iff α ≻ β (sort decreasingly; every partial sum of α ≥ that of β). Sums run over all n!
permutations. Chain for three variables: [3,0,0] ≻ [2,1,0] ≻ [1,1,1], [2,0,0] ≻ [1,1,0],
[4,0,0] ≻ [3,1,0] ≻ [2,2,0] ≻ [2,1,1]. It needs full symmetric sums (not cyclic), nonnegative
variables and homogeneous terms of equal degree; [3,0,0] and [2,2,-1] are not comparable this way.

```python
def majorizes(a, b):
    a, b = sorted(a, reverse=True), sorted(b, reverse=True)
    pa = [sum(a[:k + 1]) for k in range(len(a))]; pb = [sum(b[:k + 1]) for k in range(len(b))]
    return pa[-1] == pb[-1] and all(x >= y for x, y in zip(pa, pb))
```

**Schur** in p = a + b + c, q = ab + bc + ca, r = abc: degree t = 1 gives p³ - 4pq + 9r ≥ 0;
t = 2 gives p⁴ - 5p²q + 4q² + 6pr ≥ 0 (both SymPy-verified identities).

**uvw / pqr.** Useful identities (verified):

| Expression | In p, q, r |
|---|---|
| a² + b² + c² | p² - 2q |
| a³ + b³ + c³ | p³ - 3pq + 3r |
| a⁴ + b⁴ + c⁴ | p⁴ - 4p²q + 2q² + 4pr |
| (a + b)(b + c)(c + a) | pq - r |
| (a - b)²(b - c)²(c - a)² | p²q² - 4q³ - 4p³r + 18pqr - 27r² (≥ 0 iff a, b, c real) |

Theorem (uvw): with p and q fixed, the set of attainable r is an interval; its endpoints occur when two
variables are equal, or (for nonnegative variables) when one variable is 0. So if the inequality,
written in p, q, r, is linear in r (or monotone, convex or concave in r in the right direction), it
suffices to check two one-variable families: (a, b, c) = (1, 1, t) and (a, b, 0). Example, Schur
t = 1: the two-equal case gives t(t - 1)² ≥ 0, the zero case gives (a + b)(a - b)² ≥ 0. Proved.

## 6. Tangent-line trick, SOS-tangent and smoothing

**Tangent line.** For Σ f(x_i) ≥ n f(m) under Σ x_i = n m: let ℓ(x) = f(m) + f'(m)(x - m), prove
f(x) ≥ ℓ(x) on the whole domain, sum. The proof of f ≥ ℓ is the SOS-tangent step: factor
f(x) - ℓ(x) = (x - m)² g(x) and show g ≥ 0 on the domain. Example (Japan 1997, a + b + c = 3,
a, b, c > 0): f(a) = (3 - 2a)²/((3 - a)² + a²), f(1) = 1/5, f'(1) = -18/25 and
f(a) - ℓ(a) = 18(a - 1)²(2a + 1)/(25(2a² - 6a + 9)) ≥ 0 for a > 0, so Σ f ≥ 3/5. When g changes
sign on part of the domain, split it: on that part the inequality usually holds trivially (one huge
term), otherwise switch to SOS.

**Smoothing (mixing variables).** Show f does not increase when two variables are replaced by a
"more equal" pair that keeps the constraint, then finish with a one-variable inequality.

| Constraint | Smoothing move that keeps it |
|---|---|
| a + b fixed (sum constraint) | (a, b) → ((a + b)/2, (a + b)/2) |
| ab fixed (product constraint) | (a, b) → (sqrt(ab), sqrt(ab)) |
| a² + b² fixed | (a, b) → (sqrt((a² + b²)/2), same) |
| mixed (a + b + c = abc, a + b + c = 3 with abc = 1) | no single move; substitute (a = x/y, ...) or use uvw |

SMV pattern: if smoothing the largest and smallest variable never increases a continuous f, the
minimum is at all-equal (repeat the move; the spread shrinks to 0). If smoothing increases f, try
the opposite move (toward the boundary): the minimum is then at a boundary point.

## 7. Calculus route

- Lagrange: interior critical points satisfy ∇f = λ∇g; with x_i ≥ 0 use KKT
  (∂_i f - λ ∂_i g ≥ 0, equality when x_i > 0). Candidate list = interior critical points
  + critical points on every face (x_i = 0), edge and corner + non-smooth points (|x|, max, min)
  + points where ∇g = 0 (constraint qualification fails).
- Existence: a minimum exists only on a compact set; on (0, ∞)^n add the limits at the boundary and
  at infinity, or prove coercivity, before trusting "the only critical point is the minimum".
- Second order: the Hessian of the Lagrangian restricted to the tangent space of the constraint is
  positive definite at a strict local minimum (bordered Hessian test).
- One variable at a time: f convex in a (others fixed) ⇒ the max over a ∈ [lo, hi] is at an
  endpoint; concave ⇒ the min is at an endpoint; linear ⇒ both. This proves boundary equality cases.

```python
a, b, c, lam = sp.symbols("a b c lam", real=True)
f, g = a/(b + c) + b/(c + a) + c/(a + b), a + b + c - 1
eqs = [sp.numer(sp.together(sp.diff(f - lam*g, v))) for v in (a, b, c)] + [g]   # clear denominators
crit = [s for s in sp.solve(eqs, [a, b, c, lam], dict=True) if all(s[v] > 0 for v in (a, b, c))]
# [{a: 1/3, b: 1/3, c: 1/3, lam: 0}]; lam = 0 because f is homogeneous of degree 0 (Euler)
```

On the raw rational system `sp.solve` returned `[]` (SymPy 1.14); on the cleared numerators it
returns the candidates plus spurious ones (negative coordinates), so filter by the domain and drop
zero denominators. When `solve` stalls, `sp.groebner(eqs, lam, a, b, c, order="lex")` eliminates to
a univariate polynomial (here (c - 3)(c - 1)(c + 1)(3c - 1)). A symbolic solve is a candidate
generator; completeness still needs the boundary and infinity checks above.

## 8. Matrix and functional inequalities (with hypotheses)

| Name | Statement | Hypotheses |
|---|---|---|
| Rayleigh quotient | λ_min ≤ xᵀAx/xᵀx ≤ λ_max | A real symmetric (Hermitian), x ≠ 0 |
| Weyl | \|λ_i(A + E) - λ_i(A)\| ≤ ‖E‖₂ | A, E symmetric; eigenvalues sorted the same way |
| Hadamard | \|det A\| ≤ Π_i ‖a_i‖₂ (columns a_i) | any square A; equality iff orthogonal columns or a zero column |
| Submultiplicativity | ‖AB‖ ≤ ‖A‖ ‖B‖ | operator norms and Frobenius norm |
| Norm equivalence (ℝ^n) | ‖x‖_∞ ≤ ‖x‖₂ ≤ ‖x‖₁ ≤ sqrt(n)‖x‖₂ ≤ n‖x‖_∞ | finite dimension |
| Matrix norms | ‖A‖₂ ≤ ‖A‖_F ≤ sqrt(rank A) ‖A‖₂ | any matrix |
| Poincaré (1D) | ∫_0^L u² ≤ (L/π)² ∫_0^L u'² | u(0) = u(L) = 0, u' ∈ L² |
| Wirtinger | ∫_0^{2π} (f - f̄)² ≤ ∫_0^{2π} f'² | f 2π-periodic, f' ∈ L²; equality for a cos x + b sin x + c |
| Grönwall | u' ≤ βu ⇒ u(t) ≤ u(0) e^{∫_0^t β}; u ≤ α + ∫_0^t βu ⇒ u ≤ α e^{∫_0^t β} | integral form: α constant, β ≥ 0 continuous |
| Isoperimetric (plane) | 4πA ≤ L² | rectifiable simple closed curve; equality for the circle |

Conditioning-related bounds (Bauer-Fike, Davis-Kahan) are in `matrix-decompositions-conditioning`.

## 9. Rigorous verification

| Check | Establishes | Tool |
|---|---|---|
| exact identity (f - certificate simplifies to 0) | Proved, if the certificate's terms are visibly ≥ 0 | SymPy with declared assumptions |
| rational Gram matrix, PSD in exact arithmetic | Proved (polynomial is SOS) | `sos_gram` above |
| interval branch-and-bound covering the domain | Proved on the covered boxes | `mpmath.iv`, python-flint `arb` |
| float sampling or optimisation | Numerical evidence, candidate counterexamples | NumPy, SciPy |
| compiled Lean proof, no `sorry` | Proved (formal) of the statement as written | Lean 4 + Mathlib |

Interval branch-and-bound (2-D slice of a homogeneous 3-variable problem on a + b + c = 1):

```python
from mpmath import iv, mpf
iv.dps = 20
def bb(F, keep_out=None, min_width=mpf(2)**-12):
    stack, cert, fail, excl = [(mpf(0), mpf(1), mpf(0), mpf(1))], 0, 0, 0
    while stack:
        a0, a1, b0, b1 = stack.pop()
        if a0 + b0 > 1: continue                                  # box outside the triangle
        if keep_out and keep_out(a0, a1, b0, b1): excl += 1; continue
        if F(iv.mpf([a0, a1]), iv.mpf([b0, b1])).a > 0: cert += 1; continue   # lower bound > 0
        if a1 - a0 < min_width: fail += 1; continue
        am, bm = (a0 + a1)/2, (b0 + b1)/2
        stack += [(a0, am, b0, bm), (am, a1, b0, bm), (a0, am, bm, b1), (am, a1, bm, b1)]
    return cert, fail, excl
```

- Boxes straddling a + b = 1 include points with c < 0; that is sound (a superset) but loose.
- Interval arithmetic cannot certify f ≥ 0 at a point where f = 0: boxes around an equality point
  never close. Exclude a small disc there and cover it by an exact local argument (SOS identity, or
  a positive-definite Hessian plus a rigorous remainder bound). Report all three counts.
- python-flint: `from flint import arb, ctx; ctx.dps = 30; arb(mid, rad)`; comparisons are True only
  when certain, so `x > 0` and `x < 0` are both False for a ball containing 0. Test `x > 0` or
  `x.lower()`, never the printed string (it can show `[+/- 0.315]` for the ball [0.198, 0.314]).
- Exact spot checks: `f.subs({a: Rational(1, 3), b: Rational(1, 3), c: Rational(1, 3)})` must give
  exactly 0 at the claimed equality case, and positive rationals elsewhere.
- Lean 4 + Mathlib (toolchain setup is in `lean4-mathlib-formalization`):

```lean
import Mathlib

theorem nesbitt_poly (a b c : ℝ) (ha : 0 ≤ a) (hb : 0 ≤ b) (hc : 0 ≤ c) :
    a^2*b + a^2*c + b^2*a + b^2*c + c^2*a + c^2*b ≤ 2*(a^3 + b^3 + c^3) := by
  nlinarith [mul_nonneg (add_nonneg ha hb) (sq_nonneg (a - b)),
             mul_nonneg (add_nonneg hb hc) (sq_nonneg (b - c)),
             mul_nonneg (add_nonneg hc ha) (sq_nonneg (c - a))]

example (x y : ℝ) (hx : 0 < x) : 0 < x^2 + y^2 + x := by positivity
example (a b c : ℝ) (h : a ≤ b) (hc : 0 ≤ c) : a * c ≤ b * c := by gcongr
```

Give `nlinarith` the products the SOS certificate uses; it searches linear combinations of hint
terms and pairwise products, so the right hints usually turn a failure into a one-liner. Clearing
denominators in the rational form (`field_simp`, `div_le_div_iff`-style lemmas) changes names
between Mathlib versions: find the current lemma with `exact?` instead of guessing. Run
`#print axioms nesbitt_poly` to confirm no `sorryAx`.

## 10. Pitfalls

- Multiplying or dividing by a quantity of unknown sign, or squaring both sides when a side can be
  negative: split cases or move everything to one side first.
- WLOG a ≥ b ≥ c for a cyclic inequality: only "a is the largest" is free; then two cases
  (a ≥ b ≥ c and a ≥ c ≥ b) remain.
- AM-GM or Jensen when equality also holds on the boundary (Schur-type): the tool's equality case is
  all-equal, so the chain cannot be tight at (1, 1, 0) and the step is false somewhere.
- Normalising with a non-homogeneous constraint (a + b + c = 3 and abc = 1 cannot both be imposed by
  scaling); homogenise first.
- A chain with an intermediate inequality that is false: check every link at random points.
- Muirhead on cyclic sums, on negative variables, or with exponents of unequal total degree.
- Treating a floating minimum of -1e-16 as a counterexample, or a minimum of +1e-12 as a proof.
- "True for n ≤ 12" is not a proof: Shapiro's cyclic Σ x_i/(x_{i+1} + x_{i+2}) ≥ n/2 holds for even
  n ≤ 12 and odd n ≤ 23 and fails beyond (multistart finds -3.5e-4 at n = 14).
- SOS over ℝ is not nonnegativity on the orthant: substitute squares, or use a Positivstellensatz
  (SumOfSquares.jl `domain = @set(...)`).
- An infeasible SDP does not refute the inequality (Motzkin).

## 11. Worked example: Nesbitt

Claim: a/(b + c) + b/(c + a) + c/(a + b) ≥ 3/2 for a, b, c > 0, equality iff a = b = c.

1. Homogeneous of degree 0; normalise a + b + c = 1. `equality_hunt` returns minimum -2e-16 at
   (1/3, 1/3, 1/3) only. On the boundary c → 0 the sum tends to a/b + b/a ≥ 2 > 3/2 (and blows up
   when two variables vanish), so equality is interior and symmetric: Cauchy-Schwarz or SOS.
2. Proof (Engel form, needs a(b + c) > 0, true):
   Σ a/(b + c) = Σ a²/(a(b + c)) ≥ (a + b + c)²/(2(ab + bc + ca)) ≥ 3/2,
   the last step ⇔ (a + b + c)² ≥ 3(ab + bc + ca) ⇔ ½Σ(a - b)² ≥ 0. Engel's equality needs
   a/(a(b + c)) constant, i.e. a = b = c, consistent with step 1. Status: Proved.
3. SOS identity (SymPy `simplify(lhs - sos) == 0` returned True):
   Σ a/(b + c) - 3/2 = Σ (a - b)²/(2(a + c)(b + c)), each S ≥ 0 (criterion 1).
4. Polynomial form: the common denominator is 2(a + b)(b + c)(c + a) > 0, and the numerator is
   P = 2Σa³ - Σ_sym a²b = Σ (a + b)(a - b)²; Muirhead [3,0,0] ≻ [2,1,0] also gives P ≥ 0 at once.
5. SDP certificate: `sos_gram(P(x², y², z²), (x, y, z), 3)` solved by CLARABEL (cvxpy 1.9.3):
   optimal trace 12.0, smallest eigenvalue -3.4e-9 (floating); rounded to halves the Gram matrix has
   integer entries in {-1, 0, 1, 2}, rank 6, exact residual 0 and is PSD in exact arithmetic. It
   encodes P(x², y², z²) = Σ_cyc [x(x² - y²)]² + [y(x² - y²)]². Status: Proved (exact certificate).
6. Interval check on P(a, b, 1 - a - b) over the triangle, `iv.dps = 20`, minimum box width 2^-12:
   keep-out disc of radius 0.05 around (1/3, 1/3): 2016 boxes certified, 0 failures, 157 boxes
   excluded, 0.1 s; radius 0.02: 12136 certified, 0 failures, 450 excluded, 0.8 s. Without a keep-out
   disc and width 1e-3, 2484 boxes within 0.036 of the equality point never certify, as expected.
   The disc is covered by step 3. Status of the interval part: Proved outside the disc.
7. Lean: `nesbitt_poly` above states step 4; it is a linear combination of the three hint terms.

| Claim | Status | Evidence |
|---|---|---|
| Nesbitt for a, b, c > 0 | Proved | steps 2-4 |
| P(x², y², z²) is SOS | Proved | exact rational Gram matrix, step 5 |
| P > 0 on the triangle minus the r = 0.02 disc | Proved | 12136 interval boxes, step 6 |
| Equality only at a = b = c | Proved | SOS terms vanish iff a = b = c |

Related: `proof-techniques-and-writing`, `sympy-symbolic-verification`, `lean4-mathlib-formalization`,
`optimization-convex-nonconvex`, `probability-distributions-limits`, `matrix-decompositions-conditioning`,
hub `mathematics-toolkit`.
