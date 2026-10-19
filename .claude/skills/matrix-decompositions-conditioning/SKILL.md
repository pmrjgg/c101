---
name: matrix-decompositions-conditioning
description: "Numerical linear algebra in practice: choosing LU, Cholesky, QR, SVD, eigh or Schur for a task with the SciPy/NumPy/Julia call; conditioning and digit loss, residual checks for backward stability, least squares and rank decisions, eigenvalue and eigenvector perturbation bounds, iterative sparse solvers and preconditioning, randomized low-rank methods. Load when solving, factorising, or deciding whether to trust a matrix computation."
when_to_use: "LinAlgError 'Singular matrix', LinAlgWarning 'An ill-conditioned matrix detected ... rcond', inv(A) @ b in code, normal equations or high-degree polyfit, garbage least-squares coefficients, eigenvalues that jump under tiny perturbations, cg/gmres not converging, choosing lstsq vs qr vs svd vs eigh vs cho_factor, sparse or huge matrices, randomized SVD, Julia factorize, BLAS threading or GPU linear algebra."
---

# Matrix decompositions and conditioning

Checked October 2026 against NumPy 2.5, SciPy 1.18, scikit-learn 1.9, pyamg 5.3, python-flint 0.9,
mpmath 1.3. A computed answer deserves trust when two numbers are small: the backward error (did
the algorithm solve a nearby problem?) and condition number × backward error (how far can that
nearby problem's answer be from yours?).

Deep material: [structural facts and identities](references/linear-algebra-facts.md) |
[iterative and large-scale recipes](references/iterative-large-scale.md)

## 1. Task → factorisation → call

`from scipy.linalg import ...` unless noted. Flop counts are leading terms (Golub-Van Loan).

| Task | Factorisation | SciPy / NumPy | Julia (LinearAlgebra) | Flops |
|---|---|---|---|---|
| solve, A symmetric positive definite | Cholesky | `c = cho_factor(A); cho_solve(c, b)`; `solve(A, b, assume_a="pos")` | `cholesky(Symmetric(A)) \ b` | n³/3 |
| solve, A symmetric indefinite | LDLᵀ (Bunch-Kaufman) | `solve(A, b, assume_a="sym")`; `ldl(A)` | `bunchkaufman(Symmetric(A)) \ b` | n³/3 |
| solve, general square | LU, partial pivoting | `lu = lu_factor(A); lu_solve(lu, b)` | `lu(A) \ b` | 2n³/3 |
| solve, banded / triangular | structured | `solve_banded`, `solveh_banded`, `solve_triangular` | `Tridiagonal`, `UpperTriangular` wrappers | O(n·bw²) |
| least squares, full rank, moderate κ | Householder QR | `lstsq(A, b)` (driver `gelsd`); `qr(A, mode="economic")` + `solve_triangular` | `qr(A) \ b`, `A \ b` | 2mn² - 2n³/3 |
| least squares, rank-deficient or ill-conditioned | SVD or pivoted QR | `lstsq(A, b, cond=rc, lapack_driver="gelsd")`; `qr(A, pivoting=True)` | `pinv(A; rtol=rc) * b`, `qr(A, ColumnNorm()) \ b` | ~ SVD |
| symmetric / Hermitian eigenproblem | tridiagonal reduction | `eigh(A)`, `eigh(A, subset_by_index=[0, k-1])`, `eigh(A, B)` | `eigen(Symmetric(A))` | 4n³/3 values, ~9n³ with vectors |
| general eigenproblem | real Schur (QR algorithm) | `eig(A)`, `schur(A, output="real")` | `eigen(A)`, `schur(A)` | ~10n³ values, ~25n³ vectors |
| rank, null space, range | SVD with a tolerance | `np.linalg.matrix_rank(A)`, `null_space(A, rcond=...)`, `orth(A)` | `rank(A; rtol)`, `nullspace(A)` | O(mn²) |
| determinant | LU | `sign, logabsdet = np.linalg.slogdet(A)` | `logabsdet(A)` | 2n³/3 |
| matrix functions | scaling-and-squaring Padé, Schur | `expm`, `logm`, `sqrtm`, `funm` (generic f, least reliable) | `exp(A)`, `log(A)`, `sqrt(A)` | ~ n³ |
| polar decomposition A = UP | SVD | `polar(A)` | via `svd(A)` | ~ SVD |

SciPy ≥ 1.15: `solve` with `assume_a=None` detects diagonal, tridiagonal and triangular structure;
explicit values are `"diagonal"`, `"tridiagonal"`, `"banded"`, `"upper triangular"`,
`"lower triangular"`, `"sym"`, `"her"`, `"pos"`, `"gen"`. Julia `factorize(A)` does the same
dispatch (Cholesky if positive definite, Bunch-Kaufman for dense symmetric, LU for general square,
QR for non-square) and returns a reusable object: `F = factorize(A); F \ b`.

## 2. Rules

| Rule | Why | Instead |
|---|---|---|
| Never form A⁻¹ to solve | ~3× the flops of one LU solve, larger residuals, destroys sparsity | `lu_solve`, `cho_solve`; for A⁻¹B solve with B as many right-hand sides |
| Never form AᵀA when κ(A) is large | κ(AᵀA) = κ(A)²: κ = 1e8 leaves no digits in double | QR or SVD on A (section 13) |
| Never use det to test singularity | det(H₁₂) = 2.8e-78 for a well-defined matrix; det of a 1000×1000 N(0,1) matrix overflows to inf | `slogdet` for the value (logabsdet 2952.6 here), singular values for singularity |
| Reuse one factorisation | factor O(n³), each solve O(n²) | `lu_factor` once, `lu_solve` per right-hand side; sparse `splu(A).solve` |
| `eigh`, not `eig`, for symmetric input | `eig` returns unsorted, possibly complex output and non-orthogonal vectors | `eigh` (sorted ascending, orthonormal vectors) |
| Scale columns before judging κ | κ depends on units; badly scaled columns inflate it | divide columns by their norms, report κ of the scaled matrix |

## 3. Conditioning and digit loss

- κ₂(A) = σ_max/σ_min. Relative forward error ≲ κ·u with u = 2⁻⁵³ ≈ 1.1e-16 (double), 2⁻²⁴ ≈ 6e-8
  (single): you lose about log10 κ digits; at κ ≥ 1/u nothing is guaranteed.
- `np.linalg.cond(A)` costs an SVD and is itself inaccurate once κ ≳ 1e15. Cheap 1-norm estimates
  reuse an existing LU:

```python
import numpy as np
from scipy.linalg import lu_factor, lu_solve, lapack, hilbert
import scipy.sparse.linalg as sla
A = hilbert(12)
lu, piv = lu_factor(A)
rcond, info = lapack.dgecon(lu, np.linalg.norm(A, 1), norm="1")       # 1/κ₁ estimate, O(n²)
inv_norm = sla.onenormest(sla.LinearOperator(A.shape, matvec=lambda v: lu_solve((lu, piv), v),
                                             rmatvec=lambda v: lu_solve((lu, piv), v, trans=1)))
print(1/rcond, np.linalg.norm(A, 1) * inv_norm)                       # 3.92e16  3.92e16
```

Hilbert H₁₂ (x* = ones, b = A x*), measured:

| Quantity | Value |
|---|---|
| exact κ₂ (mpmath, 60 digits) | 1.713e16 (`np.linalg.cond`: 1.66e16) |
| κ₁: `dgecon` estimate vs exact | 3.92e16 vs 3.86e16 |
| relative residual ‖b - Ax̂‖/(‖A‖‖x̂‖) | 1.6e-16 (backward stable) |
| relative forward error ‖x̂ - x*‖/‖x*‖ | 0.26 (BLAS-dependent) |
| `solve(A, b)` | `LinAlgWarning: An ill-conditioned matrix detected: slice 0 has rcond = 2.54e-17` |

Tiny residual, wrong answer: the residual certifies the algorithm, κ decides the answer.

## 4. Backward error and stability

- Normwise backward error (Rigal-Gaches): η = ‖b - Ax̂‖/(‖A‖‖x̂‖ + ‖b‖). η within a small multiple of
  u means the solver is backward stable on this input.
- Exact bound: ‖x̂ - x‖/‖x‖ ≤ κ(A)·‖b - Ax̂‖/(‖A‖‖x‖). Forward error ≤ κ × backward error.
- Stable: LU with partial pivoting (growth factor tiny in practice, 2ⁿ⁻¹ worst case), Cholesky on
  SPD, Householder QR, SVD. Not stable for least squares: normal equations, Gram-Schmidt (classical).
- Mixed-precision iterative refinement: factor in float32, residual in float64, correct, repeat.
  Converges to float64 accuracy when κ·u₃₂ ≪ 1.

```python
import numpy as np, scipy.linalg as sl
lu32 = sl.lu_factor(A.astype(np.float32))
x = sl.lu_solve(lu32, b.astype(np.float32)).astype(np.float64)
for _ in range(5):
    r = b - A @ x                                            # residual in float64
    x += sl.lu_solve(lu32, r.astype(np.float32)).astype(np.float64)
```

Measured (n = 500, κ = 1e4, random orthogonal factors): float32 LU error 4.2e-4; after 1, 2, 3
refinement steps 1.0e-7, 2.0e-11, 1.4e-13; plain float64 LU 6.7e-13.

## 5. Rank-deficient and ill-posed problems

- Numerical rank: `np.linalg.matrix_rank` counts σ_i > σ_max·max(m, n)·eps (NumPy default, checked in
  the 2.5 source); `null_space(A)` uses the same default `rcond`. Machine-eps tolerances suit exact
  data only: for measured data set tol = (relative noise level)·σ_max and look for a gap in
  `scipy.linalg.svdvals(A)` on a log plot; rank = values above the gap.
- Truncated SVD: x_k = Σ_{i≤k} (u_iᵀb/σ_i) v_i. Picard check: |u_iᵀb| must decay faster than σ_i up
  to k; where it flattens, noise dominates.
- Pivoted QR: `Q, R, P = qr(A, pivoting=True, mode="economic")`; rank = #{i : |R_ii| > tol·|R_11|}.
  Cheaper than SVD and reliable in practice (Kahan's matrix defeats plain column pivoting).
- Tikhonov / ridge: x_λ = argmin ‖Ax - b‖² + λ²‖x‖² = Σ σ_i/(σ_i² + λ²)(u_iᵀb) v_i. Solve as the
  augmented least-squares problem [A; λI] x ≈ [b; 0] (`lstsq`), or `scipy.sparse.linalg.lsqr(A, b,
  damp=λ)` for sparse A. Choose λ by the L-curve corner (log ‖Ax_λ - b‖ against log ‖x_λ‖), by
  cross-validation or GCV (`sklearn.linear_model.RidgeCV`; sklearn's `alpha` is λ²), or by the
  discrepancy principle ‖Ax_λ - b‖ ≈ ‖noise‖.

```python
U, s, Vt = np.linalg.svd(A, full_matrices=False); beta = U.T @ b
for lam in np.logspace(-8, 0, 33):
    f = s / (s**2 + lam**2); x = Vt.T @ (f * beta)
    print(lam, np.linalg.norm(A @ x - b), np.linalg.norm(x))       # L-curve points
```

## 6. Trusting eigenvalues and eigenvectors

| Result | Statement | Hypotheses |
|---|---|---|
| Weyl | \|λ_i(A + E) - λ_i(A)\| ≤ ‖E‖₂ | A, E Hermitian, both spectra sorted |
| Weyl for singular values | \|σ_i(A + E) - σ_i(A)\| ≤ ‖E‖₂ | any A, E |
| Bauer-Fike | every eigenvalue μ of A + E has min_i \|μ - λ_i\| ≤ κ_p(V)‖E‖_p | A = VΛV⁻¹ diagonalisable |
| Simple-eigenvalue sensitivity | δλ ≈ yᴴEx/(yᴴx); condition ‖x‖‖y‖/\|yᴴx\| | λ simple, x right and y left eigenvector |
| Davis-Kahan sin Θ | ‖sin Θ(V, V̂)‖ ≤ ‖E‖/δ in any unitarily invariant norm | A, Â = A + E Hermitian; δ separates the chosen eigenvalues of A from the remaining eigenvalues of Â |
| Yu-Wang-Samworth form | ‖sin Θ(V, V̂)‖_F ≤ 2 min(√d ‖E‖₂, ‖E‖_F)/δ₀ | Hermitian; d vectors; δ₀ = gap of A alone around the chosen block |
| Wedin | max(‖sin Θ_U‖, ‖sin Θ_V‖) ≤ max(‖EV̂‖, ‖EᴴÛ‖)/δ ≤ ‖E‖₂/δ | singular subspaces; δ separates kept singular values of Â from discarded ones of A |

- Symmetric eigenvalues are always well conditioned (Weyl); eigenvectors are only as good as the
  spectral gap (Davis-Kahan): equal or close eigenvalues make individual vectors meaningless, the
  invariant subspace is what is determined.
- Non-normal matrices: A = [[1, 1e4], [0, 1]] with a 1e-8 perturbation in entry (2, 1) has
  eigenvalues 1 ± 0.01 (κ(V) of the computed eigenvectors 9e19). Before trusting eigenvalues of a
  non-normal matrix compute departure from normality ‖AᴴA - AAᴴ‖_F/‖A‖_F² and the ε-pseudospectrum
  Λ_ε(A) = {z : σ_min(zI - A) ≤ ε} on a grid (script in the iterative reference).

## 7. Structural facts (full tables in [linear-algebra facts](references/linear-algebra-facts.md))

| Fact | Hypothesis people forget |
|---|---|
| rank(AB) ≤ min(rank A, rank B); rank AᵀA = rank A; Sylvester rank A + rank B - n ≤ rank AB | real for AᵀA (use AᴴA over ℂ); A is m×n, B is n×p |
| spectral theorem A = QΛQᵀ | real symmetric; over ℂ unitary diagonalisation needs A normal |
| Schur A = UTUᴴ | any complex square A; real Schur has 2×2 blocks |
| Jordan form | algebraically closed field; discontinuous in A, never compute it in floating point |
| SVD, polar A = UP | SVD any matrix; polar square (U unitary, P PSD) |
| Courant-Fischer, Cauchy interlacing | Hermitian |
| Gershgorin: eigenvalues in ∪ D(a_ii, Σ_{j≠i} \|a_ij\|) | any complex square (a union of k disjoint discs holds exactly k eigenvalues) |
| Perron-Frobenius | positive (or nonnegative irreducible; primitive for strict dominance) |
| PD ⇔ all leading principal minors > 0 (Sylvester) | PD only: diag(0, -1) has leading minors 0, 0 but is not PSD; PSD needs all principal minors ≥ 0 |
| [[A, B], [Bᵀ, C]] ≻ 0 ⇔ A ≻ 0 and C - BᵀA⁻¹B ≻ 0 | symmetric block matrix |
| Woodbury, Sherman-Morrison, determinant lemma | the small inverse exists: C⁻¹ + VA⁻¹U invertible; 1 + vᵀA⁻¹u ≠ 0 |
| ∂ log det X/∂X = X⁻ᵀ; d(X⁻¹) = -X⁻¹(dX)X⁻¹; ∂ tr(AX)/∂X = Aᵀ | X invertible (log det: det X > 0) |

## 8. Sparse and iterative solvers

| Matrix | Method | SciPy (`scipy.sparse.linalg`) | Notes |
|---|---|---|---|
| SPD | CG | `cg(A, b, rtol=1e-8, M=M)` | ‖e_k‖_A ≤ 2((√κ-1)/(√κ+1))^k ‖e_0‖_A: iterations grow like √κ |
| symmetric indefinite | MINRES | `minres(A, b, rtol=..., M=M)` | preconditioner must be SPD |
| general | restarted GMRES | `gmres(A, b, rtol=..., restart=50, M=M)` | memory n·restart; small restarts can stagnate |
| general, memory-tight | BiCGSTAB | `bicgstab(A, b, rtol=..., M=M)` | short recurrences, erratic residuals |
| least squares | LSQR, LSMR | `lsqr(A, b, damp=λ)`, `lsmr(A, b)` | never forms AᵀA |
| moderate size, many solves | sparse direct | `splu(A.tocsc())`, `factorized(A)`, `spsolve` | fill-in decides feasibility |

- Preconditioners: Jacobi `M = diags(1/A.diagonal())`; ILU
  `ilu = spilu(A.tocsc(), drop_tol=1e-4, fill_factor=10)` wrapped as
  `LinearOperator(A.shape, ilu.solve)`; algebraic multigrid
  `pyamg.smoothed_aggregation_solver(A).aspreconditioner(cycle="V")` (elliptic PDEs).
  Measured, 2-D Poisson 100×100 (n = 10⁴), rtol 1e-8: CG 187 iterations, CG + smoothed-aggregation
  AMG 9 iterations.
- Eigenvalues: `eigsh(A, k=6, sigma=0.0, which="LM")` (shift-invert: eigenvalues nearest 0, one
  sparse LU of A - σI); `which="SA"` without a shift converges slowly for interior or small
  eigenvalues; `lobpcg(A, X, M=precond, largest=False, tol=1e-8, maxiter=500)` for a few extreme
  pairs with a preconditioner; `svds(A, k)` for a few singular triplets.
- Stopping: SciPy stops when ‖b - Ax_k‖ ≤ max(rtol·‖b‖, atol). `tol=` was deprecated for `rtol=` in
  SciPy 1.12 and raises `TypeError` from 1.14 (checked against 1.11.4, 1.12.0, 1.13.1, 1.14.1).
  Check the returned `info` (0 converged, > 0 iteration limit, < 0 bad input) and recompute the true
  residual: preconditioned methods may monitor the preconditioned residual.
- Formats: CSR for products, CSC for `splu`/`spilu` (else `SparseEfficiencyWarning`); build with COO
  or LIL, convert once; pass float arrays to `sp.diags` (integer input warns about a future dtype
  change).

## 9. Large and low-rank matrices

- Randomized SVD (Halko-Martinsson-Tropp): `sklearn.utils.extmath.randomized_svd(M, n_components=k,
  n_oversamples=10, n_iter="auto", random_state=0)`; `"auto"` means 7 power iterations when
  k < 0.1·min(M.shape), else 4. Expected error (HMT Thm 10.6, oversampling p ≥ 2, no power steps):
  E‖A - QQᵀA‖ ≤ (1 + √(k/(p-1)))σ_{k+1} + (e√(k+p)/p)(Σ_{j>k} σ_j²)^½; power iterations help
  when the spectrum decays slowly. Verify a posteriori: ‖A - QQᵀA‖ via a few random probe vectors.
- Eckart-Young-Mirsky: min over rank ≤ k of ‖A - B‖₂ = σ_{k+1}, of ‖A - B‖_F = (Σ_{j>k} σ_j²)^½,
  attained by the truncated SVD. Pick k from the energy Σ_{i≤k} σ_i²/Σ σ_i² or from the noise level.
- Nyström for PSD kernel matrices: K ≈ C W⁺ Cᵀ with C = K[:, S], W = K[S, S];
  `sklearn.kernel_approximation.Nystroem(kernel="rbf", n_components=m)`.

## 10. Exact and high-precision routes

| Need | Tool | Call |
|---|---|---|
| exact rank, determinant, solve over ℚ (small) | SymPy | `Matrix(M).rank()`, `.det(method="bareiss")`, `.nullspace()`, `.rref()` |
| same, fast and larger | python-flint | `fmpq_mat(m, n, entries)`, `.rank()`, `.det()`, `.solve(B)`, `.rref()`; `fmpz_mat` for integers |
| reference solution to many digits | mpmath | `mp.dps = 50`; `mp.matrix`, `mp.lu_solve`, `mp.qr_solve` (least squares, returns (x, residual norm)), `mp.svd_r`, `mp.eigsy`, `mp.expm` |

Floating rank of an integer matrix is a guess; certify with `fmpq_mat(...).rank()`, or rank modulo
a large prime (≤ rank over ℚ, equal for all but finitely many primes). Measure a float solver's real
error against an mpmath solution at 50+ digits computed from the same float data.

## 11. Performance

- BLAS threads: `with threadpoolctl.threadpool_limits(limits=1, user_api="blas"): ...` inside worker
  processes to avoid oversubscription (or set `OMP_NUM_THREADS`/`OPENBLAS_NUM_THREADS` before
  importing NumPy).
- float32 halves memory traffic and is roughly 2× faster on CPU (more on GPU) but keeps only about
  7 - log10 κ digits; pair it with refinement (section 4) rather than using it bare.
- GPU: `torch.linalg.solve`, `cholesky`, `eigh`, `svd`, `lstsq` (batched over leading dimensions);
  `cupy.linalg.solve`. Host-device transfer dominates for small n; consumer GPUs run float64 slowly.
- Batched small systems: `np.linalg.solve(A[k, n, n], b[k, n, 1])` broadcasts; SciPy ≥ 1.16 linalg
  functions accept batches, and 1.18 moved the `qr`, `eig`, `lstsq`, `svd` batch loops to C.
- Julia: `F = factorize(A)` then `F \ b` repeatedly; `ldiv!(y, F, b)` avoids allocation;
  `BLAS.set_num_threads(n)`.

## 12. Pitfalls

- `inv(A) @ b`, normal equations, `det(A) == 0` tests, `eig` on symmetric data.
- Judging a solve by its residual alone (section 3) or by `cond` once κ ≳ 1e15 (the estimate is
  itself noise).
- A machine-eps rank tolerance on measured data; a fixed absolute tolerance on unscaled data.
- Treating eigenvectors as unique: signs flip, and in repeated or clustered eigenvalues any rotation
  of the basis is equally valid; compare subspaces (principal angles, `scipy.linalg.subspace_angles`).
- `np.polyfit(x, y, 15)` (monomial Vandermonde, `RankWarning`): use
  `numpy.polynomial.Chebyshev.fit(x, y, 15)`, which maps the data domain to [-1, 1].
- float32 data entering a float64 pipeline unnoticed: check `A.dtype` before blaming the algorithm.
- Iterative solver "converged" on the preconditioned residual while the true residual is large.

## 13. Worked example: degree-15 least-squares fit

Fit y = eˣ sin 3x at m = 200 points of [0, 1] with a degree-15 polynomial, in the monomial basis
and in the Chebyshev basis on t = 2x - 1.

```python
import numpy as np, scipy.linalg as sl, mpmath as mp
from numpy.polynomial import chebyshev as C
x = np.linspace(0.0, 1.0, 200); y = np.exp(x) * np.sin(3 * x)
V = np.vander(x, 16, increasing=True)                  # 1, x, ..., x^15
T = C.chebvander(2 * x - 1, 15)                        # T_0 .. T_15 on [-1, 1]
mp.mp.dps = 80
def reference(A):                                      # 80-digit LS solution of the same float data
    sol, _ = mp.qr_solve(mp.matrix(A.tolist()), mp.matrix(y.tolist()))
    return np.array([float(v) for v in sol])
for name, A in (("monomial", V), ("chebyshev", T)):
    c_ref = reference(A)
    c_qr = sl.lstsq(A, y, lapack_driver="gelsd")[0]
    c_ne = sl.solve(A.T @ A, A.T @ y, assume_a="gen")   # normal equations, for contrast
    for meth, c in (("lstsq", c_qr), ("normal eq", c_ne)):
        print(name, meth, np.linalg.cond(A),
              np.linalg.norm(c - c_ref) / np.linalg.norm(c_ref),             # coefficient error
              np.linalg.norm(A @ (c - c_ref)) / np.linalg.norm(A @ c_ref))   # fitted-value error
```

Prediction: κ(V) = 1.34e11 → QR-based solvers lose about 11 of 16 digits in the coefficients;
normal equations square it (κ² ≈ 1.8e22 > 1/u) → no correct digits; κ(T) = 3.47 → full accuracy.

| Basis | Method | Coefficient rel. error | Fitted-value rel. error | ‖y - Ac‖ |
|---|---|---|---|---|
| monomial | `lstsq` (gelsd) | 2.6e-6 | 1.4e-15 | 3.0e-14 |
| monomial | economic QR + `solve_triangular` | 3.0e-6 | 1.1e-15 | 2.5e-14 |
| monomial | normal equations, `assume_a="pos"` | `LinAlgError` (Cholesky fails) | — | — |
| monomial | normal equations, LU | 7.5 | 3.7e-8 | 6.6e-7 |
| Chebyshev | `lstsq` | 1.6e-15 | 1.6e-15 | 3.2e-14 |
| Chebyshev | QR | 3.8e-16 | 2.7e-16 | 1.6e-14 |
| Chebyshev | normal equations, LU | 1.1e-15 | 4.1e-16 | 1.7e-14 |

Reading: measured coefficient loss with QR is 10.5 digits against 11.1 predicted. A backward-stable
solver keeps the fitted values accurate even when the coefficients are poorly determined (the error
lies along near-null directions of V), so "the fit looks fine" says nothing about the coefficients.
Normal equations destroy both. The fix is the basis, not the solver: `Chebyshev.fit(x, y, 15)` gives
max error 9.5e-15 on the data. Report: κ, method, coefficient error against the high-precision
reference, label Numerical evidence (the reference uses the same float data, so it measures solver
error, not modelling error).

Related: `numerical-error-analysis`, `optimization-convex-nonconvex`, `inequality-proving`,
`sympy-symbolic-verification`, `julia-craft`, `python-performance-profiling`, hub `mathematics-toolkit`.
