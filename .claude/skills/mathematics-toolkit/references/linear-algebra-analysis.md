# Linear algebra and analysis facts (with hypotheses)

Cite with the hypothesis check written next to the citation, e.g. "By Courant-Fischer (A is real
symmetric, step 2) ...".

## 1. Linear algebra

### Structure

| Fact | Statement | Hypotheses |
|---|---|---|
| Rank-nullity | dim ker T + rank T = dim V | T: V → W linear, V finite-dimensional |
| Rank facts | rank(AB) ≤ min(rank A, rank B); rank(A + B) ≤ rank A + rank B; rank AᵀA = rank A | real matrices for AᵀA (use A*A over ℂ) |
| Sylvester rank | rank A + rank B - n ≤ rank(AB) | A is m×n, B is n×p |
| Spectral theorem | A = QΛQᵀ, Q orthogonal, Λ real | A real symmetric (complex: A normal ⇒ unitarily diagonalisable) |
| Schur decomposition | A = U T U*, T upper triangular | any complex square A |
| Jordan form | A = P J P⁻¹ | algebraically closed field |
| SVD | A = U Σ Vᵀ, singular values ≥ 0 | any real/complex matrix |
| Polar | A = U P, U unitary, P PSD | square |
| Cayley-Hamilton | p_A(A) = 0 | square, any commutative ring |
| Eckart-Young | best rank-k approximation in ‖·‖₂ and ‖·‖_F is truncated SVD | any matrix |

### Eigenvalues

| Fact | Statement | Hypotheses |
|---|---|---|
| Trace / det | tr A = Σ λ_i, det A = Π λ_i (with algebraic multiplicity) | over ℂ |
| AB vs BA | same nonzero eigenvalues with multiplicities | A m×n, B n×m |
| Courant-Fischer | λ_k = min_{dim U = k} max_{x ∈ U, ‖x‖=1} xᵀAx (ascending order) | symmetric/Hermitian |
| Cauchy interlacing | eigenvalues of a principal (n-1)×(n-1) submatrix interlace those of A | symmetric/Hermitian |
| Gershgorin | every eigenvalue lies in ∪ D(a_ii, Σ_{j≠i} |a_ij|) | any complex square |
| Perron-Frobenius | spectral radius is a simple eigenvalue with positive eigenvector | A positive (or non-negative irreducible: positive eigenvector, simple; primitive for strict dominance) |
| Similar matrices | same characteristic polynomial | similar (converse false) |
| Diagonalisable | iff minimal polynomial has distinct roots (over algebraically closed field) | square |
| Nilpotent | all eigenvalues 0 ⇔ A^n = 0 | square n×n |

### Definiteness

- Symmetric A is positive definite ⇔ all eigenvalues > 0 ⇔ all leading principal minors > 0
  (Sylvester) ⇔ A = LLᵀ with L invertible (Cholesky). For semidefinite, ALL principal minors ≥ 0,
  not only leading ones.
- Schur complement: [[A, B],[Bᵀ, C]] ≻ 0 ⇔ A ≻ 0 and C - BᵀA⁻¹B ≻ 0.
- Sum and Kronecker product of PSD matrices are PSD; Hadamard (entrywise) product of PSD is PSD
  (Schur product theorem). The ordinary product of PSD matrices is PSD only if they commute.

### Identities

```
Woodbury:            (A + U C V)⁻¹ = A⁻¹ - A⁻¹U (C⁻¹ + V A⁻¹ U)⁻¹ V A⁻¹      A, C, C⁻¹ + VA⁻¹U invertible
Sherman-Morrison:    (A + u vᵀ)⁻¹ = A⁻¹ - A⁻¹u vᵀA⁻¹ / (1 + vᵀA⁻¹u)            1 + vᵀA⁻¹u ≠ 0
Matrix determinant:  det(A + u vᵀ) = (1 + vᵀA⁻¹u) det A
Block determinant:   det [[A, B],[C, D]] = det A · det(D - C A⁻¹ B)              A invertible
Derivatives:         ∂ log det X / ∂X = X⁻ᵀ;  ∂ tr(AX)/∂X = Aᵀ;  d(X⁻¹) = -X⁻¹ (dX) X⁻¹
Vandermonde:         det [x_i^(j-1)] = Π_{i<j} (x_j - x_i)
```

### Numerical facts

- Condition number κ(A) = σ_max/σ_min; solving Ax = b loses about log10 κ digits.
- Never form AᵀA for least squares when κ is large (κ(AᵀA) = κ(A)²); use QR or SVD.
- Floating eigenvalues of non-normal matrices are ill-conditioned; check pseudospectra before
  trusting them.

## 2. Real analysis

| Fact | Statement | Hypotheses |
|---|---|---|
| Completeness | every non-empty set bounded above has a supremum | ℝ |
| Monotone convergence (sequences) | bounded monotone sequences converge | real |
| Bolzano-Weierstrass | bounded sequence in ℝ^n has a convergent subsequence | finite dimension |
| Heine-Borel | compact ⇔ closed and bounded | ℝ^n (false in infinite dimensions) |
| Extreme value | continuous f on compact K attains max and min | compact domain |
| Heine-Cantor | continuous on compact ⇒ uniformly continuous | compact |
| IVT | f continuous on [a, b], y between f(a) and f(b) ⇒ ∃ c, f(c) = y | real-valued, connected domain |
| MVT | f(b) - f(a) = f'(c)(b - a) | continuous on [a,b], differentiable on (a,b), real-valued |
| Taylor (Lagrange remainder) | R_n = f^(n+1)(ξ)(x - a)^(n+1)/(n+1)! | f ∈ C^(n+1) near [a, x] |
| L'Hôpital | lim f/g = lim f'/g' | 0/0 or ∞/∞, g' ≠ 0 near the point, the right-hand limit exists |
| Uniform limit | uniform limit of continuous functions is continuous | uniform convergence |
| Term-by-term differentiation | (Σ f_n)' = Σ f_n' | Σ f_n' converges uniformly and Σ f_n converges at one point |
| Weierstrass M-test | |f_n| ≤ M_n, Σ M_n < ∞ ⇒ Σ f_n converges uniformly | |
| Dini | monotone sequence of continuous functions converging pointwise to a continuous limit on a compact set converges uniformly | compact, monotone, continuous limit |
| Arzelà-Ascoli | uniformly bounded + equicontinuous on compact ⇒ uniformly convergent subsequence | compact domain |
| Banach fixed point | contraction on a complete metric space has a unique fixed point; iteration converges geometrically | contraction constant < 1, complete space |
| Stone-Weierstrass | polynomials are dense in C([a, b]) (sup norm) | compact interval / compact Hausdorff with separating subalgebra |

## 3. Measure and integration

| Fact | Statement | Hypotheses |
|---|---|---|
| Monotone convergence | 0 ≤ f_n ↑ f ⇒ ∫ f_n → ∫ f | measurable, non-negative |
| Fatou | ∫ liminf f_n ≤ liminf ∫ f_n | non-negative measurable |
| Dominated convergence | f_n → f a.e., |f_n| ≤ g ∈ L¹ ⇒ ∫ f_n → ∫ f | integrable dominating g |
| Fubini | iterated integrals equal the double integral | ∫∫ |f| < ∞ |
| Tonelli | same conclusion | f ≥ 0 measurable (σ-finite spaces) |
| Leibniz rule | d/dt ∫ f(x, t) dx = ∫ ∂_t f dx | ∂_t f dominated by an integrable g independent of t |
| Change of variables | ∫ f(φ(u)) |det Dφ(u)| du = ∫ f(x) dx | φ a C¹ diffeomorphism (injective) |
| Cauchy-Schwarz in L² | |∫ fg| ≤ ‖f‖₂ ‖g‖₂ | f, g ∈ L² |

Counterexamples to keep handy:
- f_n = n·1_{(0, 1/n)}: f_n → 0 pointwise, ∫ f_n = 1 (no dominating function).
- Σ (-1)^n/n converges; rearrangements can converge to any real number.
- f(x, y) = (x² - y²)/(x² + y²)² on (0,1)²: the two iterated integrals differ (±π/4), Fubini fails.
- f(x) = x² sin(1/x) (f(0) = 0) is differentiable everywhere with discontinuous derivative.
- The Cantor function: continuous, increasing, derivative 0 a.e., not absolutely continuous.

## 4. Complex analysis

| Fact | Hypotheses |
|---|---|
| Cauchy integral theorem ∮ f = 0 | f holomorphic on a simply connected domain containing the contour |
| Residue theorem ∮ f = 2πi Σ Res | f meromorphic inside, no poles on the contour |
| Liouville: bounded entire ⇒ constant | entire |
| Maximum modulus | holomorphic, non-constant, on a connected open set |
| Identity theorem | holomorphic on connected domain; zero set with a limit point inside |
| Jordan's lemma | for ∫ e^{iax} g over upper semicircle → 0 when a > 0 and g → 0 uniformly |
| Argument principle (1/2πi) ∮ f'/f = Z - P (counted with multiplicity) | meromorphic inside, no zeros/poles on the contour |

## 5. Probability facts

- Linearity of expectation needs no independence; Var(X + Y) = Var X + Var Y needs uncorrelated.
- Independence ⇒ uncorrelated; converse false (X uniform on [-1, 1], Y = X²).
- LLN: i.i.d. with E|X| < ∞ ⇒ sample mean → E X almost surely (strong law).
- CLT: i.i.d. with finite variance ⇒ sqrt(n)(mean - μ)/σ → N(0, 1) in distribution; Berry-Esseen
  rate C ρ/(σ³ sqrt n) with ρ = E|X - μ|³.
- Conditional expectation tower: E[E[X | G]] = E X; Jensen holds conditionally.
- Borel-Cantelli: Σ P(A_n) < ∞ ⇒ P(A_n i.o.) = 0; converse needs independence.
