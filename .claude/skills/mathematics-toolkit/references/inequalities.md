# Inequalities and estimates catalogue

Each entry: statement, hypotheses, equality case, typical use. Verify hypotheses before citing.

## 1. Means and convexity

| Name | Statement | Hypotheses | Equality |
|---|---|---|---|
| Power mean | M_r ≤ M_s for r ≤ s, M_r = ((Σ w_i a_i^r))^(1/r), M_0 = Π a_i^(w_i) | a_i > 0, weights w_i ≥ 0 summing to 1 | all a_i equal |
| QM-AM-GM-HM | sqrt(Σa²/n) ≥ Σa/n ≥ (Πa)^(1/n) ≥ n/Σ(1/a) | a_i > 0 | all equal |
| Weighted AM-GM | Σ w_i a_i ≥ Π a_i^(w_i) | a_i ≥ 0, Σ w_i = 1 | all equal |
| Young | ab ≤ a^p/p + b^q/q | a, b ≥ 0, 1/p + 1/q = 1, p > 1 | a^p = b^q |
| Jensen | φ(Σ w_i x_i) ≤ Σ w_i φ(x_i) | φ convex | all x_i equal (strictly convex φ) |
| Karamata (majorisation) | x ≻ y ⇒ Σ φ(x_i) ≥ Σ φ(y_i) | φ convex, x majorises y | x is a permutation of y (strict φ) |
| Hermite-Hadamard | φ((a+b)/2) ≤ (1/(b-a)) ∫_a^b φ ≤ (φ(a)+φ(b))/2 | φ convex | φ affine |
| Schur | Σ a^t (a - b)(a - c) ≥ 0 | a, b, c ≥ 0, t > 0 | a = b = c, or two equal and third 0 |

## 2. Sums and products

| Name | Statement | Hypotheses | Equality |
|---|---|---|---|
| Cauchy-Schwarz | (Σ a_i b_i)² ≤ Σ a_i² Σ b_i² | real (or |·| for complex) | a ∥ b |
| Engel form (Titu / Sedrakyan) | Σ x_i²/y_i ≥ (Σ x_i)²/Σ y_i | y_i > 0 | x_i/y_i constant |
| Hölder | Σ |a_i b_i| ≤ ‖a‖_p ‖b‖_q | 1/p + 1/q = 1, p ∈ [1, ∞] | |a_i|^p ∝ |b_i|^q |
| Minkowski | ‖a + b‖_p ≤ ‖a‖_p + ‖b‖_p | p ≥ 1 | a ∥ b, same direction |
| Chebyshev sum | n Σ a_i b_i ≥ Σ a_i Σ b_i | a, b similarly ordered | one sequence constant |
| Rearrangement | Σ a_i b_σ(i) maximal when similarly ordered, minimal when oppositely ordered | real sequences | ties |
| Abel summation | Σ a_k b_k = A_n b_n - Σ_{k<n} A_k (b_{k+1} - b_k), A_k = Σ_{j≤k} a_j | none | identity |
| Bernoulli | (1 + x)^r ≥ 1 + r x | x ≥ -1, r ≥ 1 or r ≤ 0 (reverse for 0 ≤ r ≤ 1) | x = 0 |
| Weierstrass product | Π (1 - a_i) ≥ 1 - Σ a_i | a_i ∈ [0, 1] | at most one a_i nonzero |

## 3. Elementary function bounds

```
1 + x ≤ e^x                         all real x
e^x ≤ 1/(1 - x)                     x < 1
x/(1 + x) ≤ ln(1 + x) ≤ x           x > -1
ln x ≤ x - 1                        x > 0
sin x ≤ x                           x ≥ 0;   sin x ≥ 2x/π on [0, π/2] (Jordan)
cos x ≥ 1 - x²/2                    all x
(1 - x)^n ≥ 1 - n x                 x ≤ 1, n ∈ ℕ
(1 + 1/n)^n < e < (1 + 1/n)^(n+1)
tanh x ≤ x ≤ tan x                  x ∈ [0, π/2)
```

## 4. Combinatorial estimates

```
Stirling:   n! = sqrt(2πn) (n/e)^n (1 + 1/(12n) + O(1/n²));  sqrt(2πn)(n/e)^n ≤ n! ≤ e sqrt(n)(n/e)^n
Binomial:   (n/k)^k ≤ C(n,k) ≤ (e n/k)^k;   C(2n, n) ~ 4^n / sqrt(πn);   C(2n,n) ≥ 4^n/(2n + 1)
Entropy:    C(n, αn) = 2^(n H(α) - O(log n)),  H(α) = -α log2 α - (1-α) log2 (1-α)
Sum:        Σ_{k ≤ αn} C(n,k) ≤ 2^(n H(α)) for α ≤ 1/2
Harmonic:   H_n = ln n + γ + 1/(2n) - 1/(12n²) + ...,  γ ≈ 0.5772156649
Primes:     π(x) ~ x/ln x;  Σ_{p≤x} 1/p = ln ln x + M + o(1), M ≈ 0.2615;  p_n ~ n ln n
Integral comparison: f decreasing ⇒ ∫_1^{n+1} f ≤ Σ_{k=1}^n f(k) ≤ f(1) + ∫_1^n f
```

## 5. Probability tail bounds

| Bound | Statement | Hypotheses |
|---|---|---|
| Markov | P(X ≥ a) ≤ E X / a | X ≥ 0, a > 0 |
| Chebyshev | P(|X - μ| ≥ t) ≤ Var X / t² | finite variance |
| Cantelli (one-sided) | P(X - μ ≥ t) ≤ σ²/(σ² + t²) | finite variance |
| Chernoff (multiplicative) | P(S ≥ (1+δ)μ) ≤ exp(-δ²μ/(2+δ)); P(S ≤ (1-δ)μ) ≤ exp(-δ²μ/2) | S sum of independent Bernoulli, μ = E S, δ ∈ (0, 1) for the lower tail |
| Hoeffding | P(S - E S ≥ t) ≤ exp(-2t² / Σ (b_i - a_i)²) | independent, X_i ∈ [a_i, b_i] |
| Bernstein | P(S - E S ≥ t) ≤ exp(-t²/2 / (Σ Var X_i + M t/3)) | independent, |X_i - E X_i| ≤ M |
| Azuma-Hoeffding | P(Z_n - Z_0 ≥ t) ≤ exp(-t²/(2 Σ c_i²)) | martingale, |Z_i - Z_{i-1}| ≤ c_i |
| McDiarmid | P(f - E f ≥ t) ≤ exp(-2t²/Σ c_i²) | independent inputs, bounded differences c_i |
| Union bound | P(∪ A_i) ≤ Σ P(A_i) | none |
| Paley-Zygmund | P(X > θ E X) ≥ (1 - θ)² (E X)² / E X² | X ≥ 0, θ ∈ [0, 1] |
| Second moment | P(X > 0) ≥ (E X)² / E X² | X ≥ 0 |

## 6. Linear algebra and functional inequalities

| Name | Statement |
|---|---|
| Rayleigh quotient | λ_min ≤ xᵀAx / xᵀx ≤ λ_max for symmetric A |
| Weyl | |λ_i(A + E) - λ_i(A)| ≤ ‖E‖₂ for symmetric A, E |
| Hadamard | |det A| ≤ Π ‖a_i‖₂ (columns) |
| Submultiplicativity | ‖AB‖ ≤ ‖A‖ ‖B‖ for operator and Frobenius norms |
| Norm equivalence (ℝ^n) | ‖x‖_∞ ≤ ‖x‖₂ ≤ ‖x‖₁ ≤ sqrt(n) ‖x‖₂ ≤ n ‖x‖_∞ |
| Matrix norms | ‖A‖₂ ≤ ‖A‖_F ≤ sqrt(rank A) ‖A‖₂ |
| Poincaré (1D) | ∫_0^L u² ≤ (L/π)² ∫_0^L u'² for u(0) = u(L) = 0 |
| Wirtinger | ∫_0^{2π} (f - mean)² ≤ ∫_0^{2π} f'² for 2π-periodic f |
| Grönwall | u' ≤ β u ⇒ u(t) ≤ u(0) e^{∫β}; integral form u ≤ α + ∫ β u ⇒ u ≤ α e^{∫β} (α constant, β ≥ 0) |
| Isoperimetric (plane) | 4π A ≤ L² |

## 7. Proof patterns for inequalities

1. Check homogeneity; normalise one constraint.
2. Find equality cases numerically (minimise the difference with many random starts).
3. Equality at a symmetric point → AM-GM, Cauchy-Schwarz, Jensen, SOS (write difference as Σ of squares).
   Equality at the boundary → convexity/concavity in one variable, smoothing (move two variables
   together while preserving constraints), Schur.
4. Tangent-line trick: for Σ f(x_i) with Σ x_i fixed, find a line ℓ with f(x) ≥ ℓ(x) on the domain
   touching at the equality point.
5. Verify the final inequality at random points and at the equality case with exact arithmetic
   (SymPy rationals) before writing it up.
