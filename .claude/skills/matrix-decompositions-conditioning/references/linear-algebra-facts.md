# Linear algebra facts with their hypotheses

Cite with the hypothesis check next to the citation, e.g. "By Courant-Fischer (A is real symmetric,
step 2) ...". Most errors are a correct theorem used without its hypothesis.

## 1. Structure

| Fact | Statement | Hypotheses |
|---|---|---|
| Rank-nullity | dim ker T + rank T = dim V | T: V → W linear, V finite-dimensional |
| Rank facts | rank(AB) ≤ min(rank A, rank B); rank(A + B) ≤ rank A + rank B; rank AᵀA = rank A | real matrices for AᵀA (use AᴴA over ℂ) |
| Sylvester rank inequality | rank A + rank B - n ≤ rank(AB) | A is m×n, B is n×p |
| Frobenius rank inequality | rank(AB) + rank(BC) ≤ rank B + rank(ABC) | conformable sizes |
| Spectral theorem | A = QΛQᵀ, Q orthogonal, Λ real diagonal | A real symmetric (complex: A normal ⇔ unitarily diagonalisable) |
| Schur decomposition | A = UTUᴴ, U unitary, T upper triangular | any complex square A (real Schur: quasi-triangular, 2×2 blocks for complex pairs) |
| Jordan form | A = PJP⁻¹ | algebraically closed field; not computable stably in floating point |
| SVD | A = UΣVᴴ, σ_1 ≥ ... ≥ 0 | any real or complex matrix |
| Polar | A = UP, U unitary, P = (AᴴA)^½ PSD | square (P unique; U unique if A invertible) |
| QR | A = QR, Q orthonormal columns, R upper triangular | any m×n with m ≥ n; unique with diag(R) > 0 if full rank |
| Cholesky | A = LLᵀ, L lower triangular with positive diagonal | A symmetric positive definite (LDLᵀ or pivoted Cholesky for PSD) |
| LU with partial pivoting | PA = LU | any square A (U singular iff A singular) |
| Cayley-Hamilton | p_A(A) = 0 | square, entries in any commutative ring |
| Eckart-Young-Mirsky | best rank-k approximation in ‖·‖₂ and ‖·‖_F is the truncated SVD | any matrix (unitarily invariant norms) |

## 2. Eigenvalues

| Fact | Statement | Hypotheses |
|---|---|---|
| Trace and determinant | tr A = Σ λ_i, det A = Π λ_i (algebraic multiplicity) | over ℂ |
| AB vs BA | same nonzero eigenvalues with multiplicities | A m×n, B n×m |
| Courant-Fischer | λ_k = min_{dim U = k} max_{x ∈ U, ‖x‖ = 1} xᴴAx (ascending order) | Hermitian |
| Cauchy interlacing | eigenvalues of an (n-1)×(n-1) principal submatrix interlace those of A | Hermitian |
| Weyl | λ_i(A) + λ_1(E) ≤ λ_i(A + E) ≤ λ_i(A) + λ_n(E) (ascending) | Hermitian A, E |
| Gershgorin | every eigenvalue lies in ∪_i D(a_ii, Σ_{j≠i} \|a_ij\|); a union of k discs disjoint from the rest holds exactly k eigenvalues | any complex square |
| Perron-Frobenius | spectral radius is a simple eigenvalue with a positive eigenvector | A positive; for A ≥ 0 irreducible: positive eigenvector, simple; strict dominance needs A primitive |
| Similar matrices | same characteristic polynomial, eigenvalues, rank, trace, det | similar (converse false: [[0,1],[0,0]] vs 0) |
| Diagonalisable | iff the minimal polynomial has distinct roots | square, algebraically closed field |
| Nilpotent | all eigenvalues 0 ⇔ Aⁿ = 0 | square n×n |
| Commuting matrices | simultaneously triangularisable; simultaneously diagonalisable if each is diagonalisable | over ℂ |
| Rayleigh quotient | λ_min ≤ xᴴAx/xᴴx ≤ λ_max | Hermitian, x ≠ 0 |

## 3. Definiteness

- Symmetric A is positive definite ⇔ all eigenvalues > 0 ⇔ all leading principal minors > 0
  (Sylvester) ⇔ A = LLᵀ with L invertible (Cholesky succeeds). For positive semidefinite, ALL
  principal minors must be ≥ 0, not only the leading ones: diag(0, -1) has leading minors 0 and 0.
- Numerically: test definiteness by attempting `cho_factor` (fails with `LinAlgError` if not PD) or
  by `eigvalsh(A).min()` with a tolerance; never by computing minors.
- Schur complement: [[A, B], [Bᵀ, C]] ≻ 0 ⇔ A ≻ 0 and C - BᵀA⁻¹B ≻ 0. PSD version (A possibly
  singular): A ⪰ 0, (I - AA⁺)B = 0 and C - BᵀA⁺B ⪰ 0.
- Sums and Kronecker products of PSD matrices are PSD; the Hadamard (entrywise) product of PSD
  matrices is PSD (Schur product theorem). The ordinary product of two PSD matrices has nonnegative
  eigenvalues but is symmetric (hence PSD) only if they commute.
- Loewner order: A ⪰ B ⇒ CᵀAC ⪰ CᵀBC; A ⪰ B ≻ 0 ⇒ B⁻¹ ⪰ A⁻¹; the map A ↦ A² is not monotone,
  A ↦ A^(1/2) is.

## 4. Identities

```
Woodbury:            (A + UCV)⁻¹ = A⁻¹ - A⁻¹U (C⁻¹ + VA⁻¹U)⁻¹ VA⁻¹       A, C, C⁻¹ + VA⁻¹U invertible
Sherman-Morrison:    (A + uvᵀ)⁻¹ = A⁻¹ - A⁻¹uvᵀA⁻¹ / (1 + vᵀA⁻¹u)            1 + vᵀA⁻¹u ≠ 0
Determinant lemma:   det(A + uvᵀ) = (1 + vᵀA⁻¹u) det A                        A invertible
Generalised:         det(A + UCV) = det(C⁻¹ + VA⁻¹U) det C det A
Block determinant:   det [[A, B], [C, D]] = det A · det(D - CA⁻¹B)            A invertible
Block inverse:       uses the Schur complement S = D - CA⁻¹B (A and S invertible)
Vandermonde:         det [x_i^(j-1)] = Π_{i<j} (x_j - x_i)
Kronecker:           (A ⊗ B)(C ⊗ D) = AC ⊗ BD;  vec(AXB) = (Bᵀ ⊗ A) vec X;  eig(A ⊗ B) = {λ_i μ_j}
Trace:               tr(AB) = tr(BA);  tr(ABC) = tr(CAB) = tr(BCA) ≠ tr(ACB) in general
```

## 5. Matrix calculus (denominator layout: gradient has the shape of X)

```
∂ tr(AX)/∂X = Aᵀ                    ∂ tr(XᵀAX)/∂X = (A + Aᵀ)X
∂ log det X/∂X = X⁻ᵀ   (det X > 0)  ∂ det X/∂X = det(X) X⁻ᵀ
d(X⁻¹) = -X⁻¹ (dX) X⁻¹              ∂ (xᵀAx)/∂x = (A + Aᵀ)x
∂ ‖Ax - b‖²/∂x = 2Aᵀ(Ax - b)          ∂ ‖X‖_F²/∂X = 2X
```

Check any derived gradient by finite differences at a random point (relative step ~1e-6, compare to
~1e-6 relative) or with automatic differentiation (`jax.grad`, `torch.autograd`).

## 6. Norms

| Fact | Statement |
|---|---|
| Operator norms | ‖A‖₁ = max column sum, ‖A‖_∞ = max row sum, ‖A‖₂ = σ_max |
| Equivalence | ‖A‖₂ ≤ ‖A‖_F ≤ sqrt(rank A)‖A‖₂; ‖A‖₂ ≤ sqrt(‖A‖₁‖A‖_∞) |
| Spectral radius | ρ(A) ≤ ‖A‖ for every induced norm; ρ(A) = lim ‖A^k‖^(1/k) (Gelfand) |
| Unitary invariance | ‖UAV‖ = ‖A‖ for ‖·‖₂, ‖·‖_F and all Schatten norms |
| Condition number | κ(A) = ‖A‖‖A⁻¹‖ ≥ 1; κ₂(AᵀA) = κ₂(A)² for full column rank A |

## 7. Numerical facts

- Solving Ax = b loses about log10 κ(A) digits; least squares by QR loses log10 κ (plus a κ² tan θ
  term when the residual is large), by normal equations 2·log10 κ.
- Floating eigenvalues of non-normal matrices are ill-conditioned; check pseudospectra first.
- Eigenvectors of close eigenvalues are ill-determined; invariant subspaces of well-separated
  clusters are well-determined (Davis-Kahan).
- Gram-Schmidt: classical loses orthogonality like κ², modified like κ; Householder QR keeps it at
  the level of u. Re-orthogonalise once ("twice is enough") when using Gram-Schmidt.
