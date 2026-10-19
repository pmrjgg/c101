# Extended inequality catalogue

Each entry: statement, hypotheses, equality case. Entries marked (r) were also spot-checked on 2000
random instances (NumPy, seed 3) while this file was written; that is evidence of transcription
accuracy, not a proof. Cite the classical source when you use one.

## 1. Symmetric means

| Name | Statement | Hypotheses | Equality |
|---|---|---|---|
| Maclaurin (r) | S_1 ≥ S_2^(1/2) ≥ ... ≥ S_n^(1/n), S_k = e_k / C(n, k) (e_k elementary symmetric) | a_i ≥ 0 | all equal |
| Newton (r) | S_k² ≥ S_{k-1} S_{k+1}, 1 ≤ k ≤ n - 1 | a_i real | all equal |
| Huygens (r) | Π (1 + a_i) ≥ (1 + (Π a_i)^(1/n))^n | a_i ≥ 0 | all equal |
| Generalised Bernoulli | (1 + x)^r ≤ 1 + r x | x ≥ -1, 0 ≤ r ≤ 1 | x = 0 or r ∈ {0, 1} |
| Power-mean special case | ((a^p + b^p)/2)^(1/p) ≥ sqrt(ab) | a, b > 0, p > 0 | a = b |

## 2. Sums, products and quadratic forms

| Name | Statement | Hypotheses | Equality |
|---|---|---|---|
| Hölder, several sequences | Σ_i Π_j \|a_ij\| ≤ Π_j (Σ_i \|a_ij\|^(p_j))^(1/p_j) | p_j ≥ 1, Σ_j 1/p_j = 1 | the vectors (\|a_ij\|^(p_j))_i proportional |
| Hölder, cube form (r) | (Σ a³)(Σ b³)(Σ c³) ≥ (Σ abc)³ | a, b, c ≥ 0 | (a_i³), (b_i³), (c_i³) proportional |
| Aczél (r) | (a_1 b_1 - Σ_{i≥2} a_i b_i)² ≥ (a_1² - Σ_{i≥2} a_i²)(b_1² - Σ_{i≥2} b_i²) | a_1² > Σ_{i≥2} a_i² (or the same for b) | a, b proportional |
| Pólya-Szegő reverse Cauchy-Schwarz (r) | Σa² Σb² ≤ ¼(sqrt(M₁M₂/(m₁m₂)) + sqrt(m₁m₂/(M₁M₂)))² (Σab)² | 0 < m₁ ≤ a_i ≤ M₁, 0 < m₂ ≤ b_i ≤ M₂ | extremal two-point configurations |
| Kantorovich (r) | (xᵀAx)(xᵀA⁻¹x) ≤ ((M + m)²/(4Mm)) (xᵀx)² | A symmetric positive definite, spectrum in [m, M] | x spread equally over the extreme eigenvectors |
| Chebyshev, integral form (r) | (1/(b-a))∫fg ≥ ((1/(b-a))∫f)((1/(b-a))∫g) | f, g monotone in the same direction on [a, b] | f or g constant |
| Cauchy-Schwarz, integral | (∫fg)² ≤ ∫f² ∫g² | f, g ∈ L² | f, g linearly dependent |
| Jensen, integral | φ(∫ f dμ) ≤ ∫ φ(f) dμ | μ a probability measure, φ convex, f and φ∘f integrable | f constant μ-a.e. (strictly convex φ) |

## 3. Convexity

| Name | Statement | Hypotheses | Equality |
|---|---|---|---|
| Popoviciu (r) | f(x) + f(y) + f(z) + 3f((x+y+z)/3) ≥ 2[f((x+y)/2) + f((y+z)/2) + f((z+x)/2)] | f convex on an interval containing x, y, z | x = y = z, or f affine |
| Karamata, weighted (Fuchs) | Σ w_i φ(x_i) ≥ Σ w_i φ(y_i) | φ convex, x and y decreasingly ordered, weighted partial sums of x ≥ those of y, equal totals | as Karamata |
| Majorisation facts | (x_1, ..., x_n) ≻ (x̄, ..., x̄); any vector with total s and entries in [0, 1] is majorised by (1, ..., 1, s - ⌊s⌋, 0, ...) | — | — |

## 4. Series

| Name | Statement | Hypotheses | Equality |
|---|---|---|---|
| Carleman (r) | Σ_n (a_1 ⋯ a_n)^(1/n) < e Σ_n a_n | a_n ≥ 0, not all 0, Σ a_n < ∞ | never (e is sharp) |
| Hardy (r) | Σ_n ((a_1 + ... + a_n)/n)^p < (p/(p-1))^p Σ_n a_n^p | p > 1, a_n ≥ 0 not all 0, Σ a_n^p < ∞ | never (constant sharp) |
| Basel partial sums | Σ_{k≤n} 1/k² ≤ 2 - 1/n | n ≥ 1 (the inductive strengthening of Σ < 2) | n = 1 |

## 5. Named three-variable inequalities with unusual equality cases

| Name | Statement | Equality | Lesson |
|---|---|---|---|
| Schur, t = 1 | Σ a(a - b)(a - c) ≥ 0, a, b, c ≥ 0 | a = b = c and (1, 1, 0) | AM-GM cannot prove it |
| Vasc | (a² + b² + c²)² ≥ 3(a³b + b³c + c³a), a, b, c real | a = b = c and a:b:c = sin²(4π/7) : sin²(2π/7) : sin²(π/7) (value 0 to 30 digits, mpmath) | cyclic, non-symmetric equality: SOS by SDP |
| Nesbitt | Σ a/(b + c) ≥ 3/2, a, b, c > 0 | a = b = c | worked example in SKILL.md |
| Shapiro (cyclic) | Σ_{i=1}^n x_i/(x_{i+1} + x_{i+2}) ≥ n/2, indices mod n, x_i > 0 | holds for even n ≤ 12 and odd n ≤ 23, fails otherwise; n = 14 counterexample found by multistart and confirmed with exact rationals | small cases are not a proof |

## 6. Proof patterns (summary)

1. Check homogeneity; normalise one constraint (only when all constraints are homogeneous).
2. Find equality cases numerically (minimise LHS - RHS from many random starts).
3. Equality at a symmetric point → AM-GM, Cauchy-Schwarz, Jensen, SOS. Equality on the boundary →
   convexity in one variable, smoothing, Schur, uvw. Non-symmetric equality → SDP.
4. Tangent-line trick for Σ f(x_i) with Σ x_i fixed: f(x) ≥ ℓ(x) on the domain, touching at the
   equality point.
5. Verify the final inequality at random points and at the equality case with exact arithmetic
   (SymPy rationals) before writing it up.

## 7. Quick random-instance checker

```python
import numpy as np
def spot_check(lhs, rhs, sampler, n=10_000, seed=0, tol=1e-12):
    rng = np.random.default_rng(seed); worst = np.inf; arg = None
    for _ in range(n):
        x = sampler(rng); s = lhs(*x) - rhs(*x)
        if s < worst: worst, arg = s, x
    return worst, arg      # worst < -tol: recheck arg exactly before claiming False

spot_check(lambda a, b, c: (a*a + b*b + c*c)**2, lambda a, b, c: 3*(a**3*b + b**3*c + c**3*a),
           lambda r: r.normal(size=3))
```
