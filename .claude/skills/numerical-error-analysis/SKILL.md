---
name: numerical-error-analysis
description: "Error analysis for floating-point arithmetic and numerical methods: unit roundoff and error models, conditioning vs stability, cancellation and stable rewrites, accurate summation, root finding, quadrature, interpolation, differentiation step choice, convergence studies with Richardson extrapolation, high-precision and interval references, and tolerance-aware tests. Load when a computed number must be trusted or a numerical bug is suspected."
when_to_use: "A result differs across machines, precisions, thread counts or libraries; a formula loses digits (variance, softmax, quadratic roots, log(1+x)); you must pick step sizes, tolerances or rtol/atol for tests; a root finder, quadrature or interpolant misbehaves; discretisation error needs an h-refinement estimate; or digits must be certified with mpmath or interval arithmetic."
---

# Numerical error analysis

Every computed number carries three kinds of error: representation of the data, roundoff, and
truncation (discretisation or sampling). Name the dominant one, bound it, and confirm it with a
second computation that changes one thing: the precision, the step or the algorithm. Report digits
only as far as the condition number allows.

## 1. Floating-point model

fl(a ∘ b) = (a ∘ b)(1 + δ) with |δ| ≤ u, for ∘ ∈ {+, −, ×, ÷, √}, under round-to-nearest and away
from overflow and underflow.

| Format | precision p (bits) | u = 2^−p | eps = 2u (np.finfo eps) | largest | smallest normal |
|---|---|---|---|---|---|
| binary64 | 53 | 1.11e−16 | 2.22e−16 | 1.8e308 | 2.2e−308 |
| binary32 | 24 | 5.96e−8 | 1.19e−7 | 3.4e38 | 1.2e−38 |
| binary16 (fp16) | 11 | 4.88e−4 | 9.77e−4 | 65504 | 6.1e−5 |
| bfloat16 | 8 | 3.91e−3 | 7.81e−3 | 3.4e38 | 1.2e−38 |

- **Spacing.** `np.spacing(x)` gives the gap to the next float. Doubles hold integers exactly up to
  2⁵³ ≈ 9.0e15. The spacing is 128 near 1e18 in binary64 and 64 near 1e9 in binary32.
- **Subnormals** extend binary64 down to 4.9e−324 with lost relative precision. Flush-to-zero (GPUs,
  -ffast-math, DAZ/FTZ flags) turns them into 0.
- **Signed zero.** −0.0 == 0.0, yet 1/−0.0 = −inf and atan2(−0.0, −1) = −π. It matters at branch
  cuts.
- **NaN.** NaN != NaN, and every comparison with NaN is False, so max, min and sort results depend
  on input order. Use `np.isnan` and `np.nanmax`, and validate inputs.
- **Non-associativity.** (1e16 + 1) − 1e16 = 0.0, but 1e16 − 1e16 + 1 = 1.0.
- **FMA** computes a·b + c with one rounding. Compilers may contract expressions into FMA
  (-ffp-contract), so results differ by ulps across compilers and CPUs. Old 32-bit x87 builds use
  80-bit intermediates.
- **-ffast-math / -Ofast** assume no NaN or Inf (isnan checks can vanish), reassociate (which
  destroys Kahan compensation), enable FTZ and approximate reciprocals. Keep them off any code whose
  accuracy you need to argue about.
- **Standard bounds** (Higham). Recursive summation: |ŝ − s| ≤ γ_{n−1} Σ|x_i| with
  γ_n = nu/(1 − nu). Dot product: |fl(xᵀy) − xᵀy| ≤ γ_n |x|ᵀ|y|. Pairwise summation replaces n − 1
  by ⌈log₂ n⌉.

## 2. Conditioning vs stability

- **Relative condition number** κ_f(x) = |x f′(x)/f(x)|; for vectors, κ = ‖J(x)‖‖x‖/‖f(x)‖.
  Examples: x − 1 near x = 1 has κ = |x/(x − 1)| → ∞; log x near 1 has 1/|log x|; √x has 1/2; eˣ
  has |x|. For linear systems κ(A) = ‖A‖‖A⁻¹‖ (see `matrix-decompositions-conditioning`).
- **Backward error.** The computed ŷ equals f(x + Δx) exactly for some Δx. The algorithm is
  backward stable if |Δx|/|x| = O(u).
- **Rule.** Forward relative error ≲ κ × backward relative error. A backward-stable algorithm loses
  about log₁₀ κ digits; losing more means the algorithm is unstable.

Diagnosis:

1. Get a reference (mpmath at 50 digits, section 10) and measure the actual relative error e.
2. Compute κ at the input. If e ≈ κu, the problem is ill-conditioned. A better algorithm will not
   help: reformulate in better variables, raise precision, or report the error bar.
3. If e ≫ κu, the algorithm is unstable. Find the step with cancellation (section 3) or error
   growth, and rewrite it.
4. Perturbation test: perturb the inputs by relative 1e−14, several times. The output spread
   ≈ κ·1e−14 measures κ empirically.

## 3. Cancellation catalogue and stable rewrites

Subtracting nearly equal floats is exact (Sterbenz), but it exposes the rounding already present:
the relative error of a − b is about u(|a| + |b|)/|a − b|.

| Expression | Fails when | Stable form |
|---|---|---|
| log(1 + x) | x near 0 | `np.log1p(x)` |
| eˣ − 1 | x near 0 | `np.expm1(x)` |
| √(x² + y²) | the squares overflow or underflow | `np.hypot(x, y)` |
| (−b ± √(b² − 4ac))/(2a) | b² ≫ 4ac | q = −(b + sign(b)√(b² − 4ac))/2; roots q/a and c/q |
| 1 − cos x | x near 0 | 2 sin²(x/2) |
| log Σ e^(x_i) | overflow or underflow | m + log Σ e^(x_i − m), m = max x_i (`scipy.special.logsumexp`) |
| softmax | large inputs | subtract the max first (`scipy.special.softmax`) |
| E[x²] − E[x]² | mean ≫ spread | two-pass Σ(x − x̄)²/(n − 1), or Welford |
| √(x + 1) − √x | large x | 1/(√(x + 1) + √x) |
| a² − b² | a ≈ b | (a − b)(a + b) |
| x − sin x | x near 0 | series x³/6 − x⁵/120 + ... below a cutoff |
| log(1 − e^(−x)) | x near 0, or large x | log(−expm1(−x)) for x ≤ ln 2, log1p(−exp(−x)) above |
| sigmoid and log-sigmoid | very negative x | `scipy.special.expit`; log-sigmoid = −`np.logaddexp(0, -x)` |
| 1 − Φ(x), a tail probability | large x | `scipy.stats.norm.sf(x)` and `logsf` |
| (1 + 1/n)ⁿ | large n | exp(n·log1p(1/n)) |
| atan(y/x) | x = 0, or the wrong quadrant | `atan2(y, x)` |

For x² + 10⁸x + 1 = 0, the naive small root comes out as −7.45e−9, wrong in the first digit, while
c/q gives −1.0e−8. Herbie (herbie.uwplse.org) searches rewrites of an FPCore expression and reports
accuracy over the input range; verify what it proposes.

## 4. Summation and reductions

| Method | Error bound, in units of Σ abs(x_i) | Where you meet it |
|---|---|---|
| recursive loop | (n − 1)u | plain loops in C, Fortran, Julia, Rust |
| pairwise | about u·log₂ n | `np.sum` on contiguous float arrays (blocked pairwise) |
| Kahan | 2u + O(nu²) | breaks when a term is larger than the running sum |
| Neumaier | 2u + O(nu²) | handles large terms; Python ≥ 3.12 built-in `sum` of floats |
| `math.fsum` | correctly rounded | Shewchuk's exact algorithm; slower |

On [1.0, 1e100, 1.0, −1e100] (true sum 2.0): `np.sum` and Kahan return 0.0; Neumaier, `math.fsum`
and Python 3.13 `sum` return 2.0.

```python
def kahan(xs):
    s = c = 0.0
    for x in xs:
        y = x - c; t = s + y; c = (t - s) - y; s = t
    return s

def neumaier(xs):
    s = c = 0.0
    for x in xs:
        t = s + x
        c += (s - t) + x if abs(s) >= abs(x) else (x - t) + s
        s = t
    return s + c
```

Parallel reductions change the summation order with the thread count, chunking and scheduling, so
results differ at the u·Σ|x_i| level, and GPU float atomicAdd is non-deterministic. The fixes:
fixed-shape tree reductions, compensated or exact accumulation (superaccumulators, integer fixed
point), `torch.use_deterministic_algorithms(True)` and pinned BLAS thread counts. Compare such runs
with a tolerance, never with equality.

## 5. Root finding

| Method | Convergence | Needs | Use |
|---|---|---|---|
| bisection | linear; halves the bracket each step | a sign change, continuity | guaranteed; log₂((b − a)/tol) steps |
| Newton | quadratic at a simple root; linear with ratio (m − 1)/m at a root of multiplicity m | f′ and a good start | polishing; x − m f/f′ restores quadratic convergence when m is known |
| secant | order ≈ 1.618 | two starting points | no derivative available |
| Brent (`brentq`) | superlinear, with a bisection safeguard | a bracket | the default for scalar roots |

```python
from scipy.optimize import root_scalar
r = root_scalar(lambda x: x**3 - 2*x - 5, bracket=[2, 3], method="brentq", xtol=1e-14)
r.root, r.iterations, r.converged      # 2.0945514815423..., 7, True
```

- **Stopping.** Require a small step, |x_{k+1} − x_k| ≤ xtol + rtol|x_k|, and a small residual,
  |f(x_k)| ≤ ftol. Either test alone can fail: a flat f (multiple root) has tiny |f| far from the
  root, and slow convergence takes tiny steps far from it.
- **Root conditioning.** Changing f to f + εg moves a simple root by about −εg(x*)/f′(x*), so the
  attainable accuracy is (the error in evaluating f)/|f′(x*)|. A root of multiplicity m is only
  determined to about (u·scale)^(1/m): (x − 1)³ evaluated in expanded form pins the root to ~1e−5.
- **Newton's ratio as a diagnostic.** Newton on (x − 1)³ from x = 2 gives errors 0.667, 0.444,
  0.296. The constant ratio 2/3 flags multiplicity 3.
- **Polynomials.** `np.roots` (companion-matrix eigenvalues) is backward stable in the coefficients,
  but clustered roots are ill-conditioned (Wilkinson). Use `mpmath.polyroots` at high precision for
  references.

## 6. Quadrature

- **`scipy.integrate.quad`** (QUADPACK: adaptive 21-point Gauss-Kronrod with extrapolation). The
  defaults are epsabs = epsrel = 1.49e−8 and limit = 50 subintervals. Options:
  - `points=[...]` for interior kinks or singularities (finite ranges only);
  - `weight="cos"` or `"sin"` with `wvar=ω` for oscillatory integrands (QAWO, or QAWF on infinite
    ranges);
  - `weight="alg"` with `wvar=(α, β)` for (x − a)^α(b − x)^β endpoint behaviour;
  - `weight="cauchy"` for principal values;
  - `np.inf` limits.
- **Gauss-Legendre vs Clenshaw-Curtis.** n-point Gauss-Legendre is exact to degree 2n − 1;
  (n+1)-point Clenshaw-Curtis is exact to degree n. In practice they are about equally accurate at
  the same n, and Clenshaw-Curtis is nested, reusing points when n doubles. Both converge
  geometrically for analytic integrands.
- **Trapezoid rule.** It converges geometrically for smooth periodic integrands over a full period,
  and for smooth, rapidly decaying integrands on ℝ. Do not "upgrade" it to Simpson there.
- **Endpoint singularities.** Use tanh-sinh (the `mpmath.quad` default), and split at interior
  singularities with [a, c, b]. Even tanh-sinh got only 25 of 50 digits for ∫₀¹ log(t)/√t dt = −4 at
  mp.dps = 50, so compare two precisions or pass `error=True`.
- **Infinite ranges.** Substitute x = t/(1 − t) or x = tan θ, or use the library's infinite-range
  rules. For oscillatory tails use the weight options or `mpmath.quadosc`.
- **Error estimates are not bounds.** `quad(lambda x: np.exp(-(x - 700)**2), 0, 1000)` returns
  4.2e−70 with an error estimate of 7.7e−70, while the truth is √π ≈ 1.7725: the peak fell between
  nodes. With `points=[700]` it returns 1.7724538509055283 (error 1.2e−14). Know where the
  integrand's features are.

## 7. Interpolation and approximation

- **Runge.** For 1/(1 + 25x²) on [−1, 1], equispaced interpolants of degree 10, 20 and 40 have max
  errors 1.9, 60 and 1.0e5. Chebyshev points give 0.13, 0.018 and 3.4e−4. The Lebesgue constants
  grow like 2^(n+1)/(e n log n) for equispaced points and like (2/π) log n for Chebyshev points.
- **Barycentric formula** (second kind): p(x) = Σ w_j f_j/(x − x_j) / Σ w_j/(x − x_j). For
  Chebyshev points x_j = cos(jπ/n), w_j = (−1)^j, halved at both ends. It is stable (Higham 2004);
  use `scipy.interpolate.BarycentricInterpolator`. Never solve a high-degree Vandermonde system: its
  condition number grows exponentially.
- **Chebyshev coefficients as a diagnostic**
  (`numpy.polynomial.chebyshev.chebinterpolate(f, deg)`):
  - Analytic f: geometric decay, with the rate set by the nearest complex singularity. For
    1/(1 + 25x²), with poles at ±i/5, the factor is about 0.82 per coefficient.
  - A plateau near u·max|f| means f is resolved to machine precision.
  - Algebraic decay means a singularity. If f^(k) has bounded variation, coefficients are
    O(n^(−k−1)); |x| gives about n⁻².
- **Splines.** Cubic splines have O(h⁴) error for f in C⁴ with not-a-knot or clamped ends; natural
  ends degrade to O(h²) near the boundary. Use `CubicSpline(x, y, bc_type="not-a-knot")`, and PCHIP
  when the data's monotonicity must be kept.
- **Minimax vs least squares.** Minimax (Remez; the error equioscillates at n + 2 points) minimises
  the worst-case error and suits function libraries. Least squares minimises the average error and
  suits noisy data. Chebyshev interpolation is near-minimax: its error is at most
  (2 + (2/π) log(n + 1)) times the best possible.

## 8. Numerical differentiation

| Formula | Truncation | Good h | Typical relative error |
|---|---|---|---|
| forward (f(x+h) − f(x))/h | h f″/2 | √eps·max(abs(x), 1) | 1e−8 |
| central (f(x+h) − f(x−h))/(2h) | h² f‴/6 | eps^(1/3)·max(abs(x), 1) | 1e−11 |
| complex step Im f(x + ih)/h | h² f‴/6, with no cancellation | 1e−20 or smaller | u |
| automatic differentiation | none for the code as written | — | u |

Measured for exp at x = 1: forward differences give 5.0e−5 at h = 1e−4, 2.4e−9 at h = 1e−8 and
1.6e−4 at h = 1e−12 (roundoff). Central differences give 5.7e−12 at h = 6e−6, and the complex step
gives 0.

- Make h exactly representable: h = (x + h) − x.
- The complex step needs f analytic and coded without abs, comparisons on the value, or conjugation.
- AD is the default when the code already lives in JAX or PyTorch (`jax.grad`, `jacfwd`, `jacrev`).
  JAX defaults to float32: call `jax.config.update("jax_enable_x64", True)`.
- Richardson for derivatives: (4D(h/2) − D(h))/3 with the central D is O(h⁴).

## 9. Convergence studies

For a quantity Q(h) with error ≈ C h^p:

- Compute Q(h), Q(h/2) and Q(h/4). The observed order is
  p_obs = log₂((Q(h) − Q(h/2))/(Q(h/2) − Q(h/4))).
- Richardson: Q* ≈ Q(h/2) + (Q(h/2) − Q(h))/(2^p − 1). The error of the finer value is about
  |Q(h/2) − Q(h)|/(2^p − 1).
- Trust this only in the asymptotic range, where p_obs is within about 0.1 of the theoretical
  order. Otherwise refine further, or suspect a bug, a non-smooth solution or the roundoff floor.
- Keep three errors apart: discretisation (∝ h^p), statistical (Monte Carlo ∝ N^(−1/2), reported
  with a confidence interval) and roundoff (grows like u/h^k as h → 0). A log-log plot of error
  against h is V-shaped, and the left arm is roundoff.

```python
import math, numpy as np
def trap(f, a, b, m):
    x = np.linspace(a, b, m + 1); return (b - a) / m * (f(x).sum() - (f(x[0]) + f(x[-1])) / 2)
Q = [trap(np.exp, 0, 1, m) for m in (8, 16, 32)]
p = math.log2((Q[0] - Q[1]) / (Q[1] - Q[2]))            # 1.9996
est = abs(Q[2] - Q[1]) / (2**2 - 1)                     # 1.398e-4; the true error is 1.398e-4
rich = Q[2] + (Q[2] - Q[1]) / 3                         # error 9.1e-9
```

Integrator specifics for ODEs and PDEs (step control, stiffness) stay in `physics-toolkit`.

## 10. Reference values

- **mpmath.** Set `mp.dps = 50` (decimal digits) and recompute at 70; the digits that agree are
  strong evidence. Build inputs from strings: `mpf("0.1")` is 1/10 to working precision, while
  `mpf(0.1)` is 0.1000000000000000055511151231257827.... Tools: `mp.quad`, `mp.nsum`,
  `mp.findroot`, `mp.polyroots`.
- **Rigorous enclosures.** python-flint `arb` balls: `from flint import arb, ctx; ctx.prec = 200`
  (bits), then `arb(1).exp()` gives [2.71828... +/- 3.7e−59], and `arb("0.1")` encloses 1/10.
  Comparisons return True only when they are certain: `(arb(1) + arb("1e-70")) > arb(1)` is False at
  200 bits, which means "not proved", not "false". `mpmath.iv` provides interval arithmetic too;
  `sympy-symbolic-verification` has bisection proofs on boxes.
- **Two precisions.** Compare float32, float64 and mpmath. If the float64 and 50-digit results
  differ by more than κu, the algorithm is unstable.
- Store golden values with their source, precision and date.

## 11. Testing numerical code

```python
import math, numpy as np
np.testing.assert_allclose(actual, desired, rtol=1e-12, atol=1e-15)  # abs(a - d) <= atol + rtol*abs(d)
math.isclose(a, b, rel_tol=1e-9, abs_tol=0.0)                         # symmetric in a and b
np.testing.assert_array_max_ulp(a, b, maxulp=4)                       # distance in units in the last place
abs(a - b) / np.spacing(abs(b))                                       # the ULP distance itself, for reports
```

- **Justify tolerances.** Set rtol ≈ c·κ·u, with c a modest growth factor (n for a length-n loop
  sum, log n for pairwise). atol is mandatory when the expected value can be 0, because relative
  error means nothing there; derive it from the input scale.
- **Defaults to know.** `assert_allclose` uses rtol = 1e−7 and atol = 0, relative to `desired` (so
  it is asymmetric); `math.isclose` uses rel_tol = 1e−9; `pytest.approx` uses rel = 1e−6 and
  abs = 1e−12.
- **Never use == on floats**, except for results exact by construction (integers below 2⁵³,
  copies).
- **Property tests.** Use Hypothesis `floats(allow_nan=False, allow_infinity=False)` plus explicit
  edge inputs: 0.0, −0.0, 5e−324, 2.2e−308, 1e−300, 1e300, negatives and points near branch cuts.
  Check identities (round trips, symmetry, monotonicity) to within a few ulps.
- **Determinism.** Run with `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` set to
  1 and to 8 (or `threadpoolctl.threadpool_limits(1)`) and compare with a tolerance. Seed the RNGs
  (`np.random.default_rng(seed)`). On NVIDIA GPUs, check the TF32 switches
  (`torch.backends.cudnn.allow_tf32`, `torch.set_float32_matmul_precision("highest")`) before
  assuming float32 accuracy.

## 12. Worked example: a variance that cancels

Data [1e9+4, 1e9+7, 1e9+13, 1e9+16]. Exactly, the mean is 1e9 + 10, the deviations are −6, −3, 3, 6,
Σ dev² = 90, and the sample variance is 90/3 = 30.

```python
import math, numpy as np
x = np.array([1e9 + 4, 1e9 + 7, 1e9 + 13, 1e9 + 16]); n = len(x)
naive_np = (np.mean(x**2) - np.mean(x)**2) * n / (n - 1)                         # -170.67
naive_fsum = (math.fsum(v*v for v in x)/n - (math.fsum(x)/n)**2) * n / (n - 1)   # 0.0
def welford(xs):
    mean = m2 = 0.0
    for k, v in enumerate(xs, 1):
        d = v - mean; mean += d / k; m2 += d * (v - mean)
    return m2 / (len(xs) - 1)
welford(x), np.var(x, ddof=1)                                    # 30.0, 30.0 (np.var is two-pass)
np.spacing(1e18), np.var(x.astype(np.float32), ddof=1)           # 128.0, 0.0
```

1. **Error model for the naive formula.** Each x² ≈ 1e18 sits where the spacing is 128, so each
   square carries an error up to 64. The subtraction then removes about 1e18 and leaves 22.5 (the
   population variance). Its condition number is κ ≈ 2·10¹⁸/22.5 ≈ 9·10¹⁶, so κu ≈ 10: no digit
   can survive. Observed: −170.67 from NumPy (a negative variance) and 0.0 from Python's sum. Even
   `math.fsum` returns 0.0, because the squares are rounded before any summation happens.
2. **Welford.** Every intermediate is exactly representable. The first step copies x₁; after that
   the deviations are 3, 7.5 and 8, the running means are 1e9 + 5.5, 1e9 + 8 and 1e9 + 10, and the
   increments to m2 are 4.5, 37.5 and 48. The error model predicts no rounding at all, and the
   result is exactly 30.0. The two-pass method (`np.var`) agrees.
3. **float32.** The spacing near 1e9 is 64, so all four values round to 1e9 before any arithmetic,
   and every algorithm returns 0. That is representation error. Only centring before storage
   (store x − 1e9) or float64 fixes it.

Status: the observed failures match the error model (κu ≈ 10 for the naive formula, exact
arithmetic for Welford), and the correct value 30 is recovered.

## 13. Pitfalls

- **eps vs u.** eps = 2⁻⁵² and u = 2⁻⁵³ differ by a factor of 2.
- **Bad tolerances.** atol = 0 for values near zero, rtol tighter than κu, or == on floats.
- **quad's error estimate treated as a bound.**
- **Root-finder stopping.** Stopping Newton on |f| alone, or root finding without a bracket and
  without a convergence check.
- **Compensation destroyed or blamed.** -ffast-math on compensated sums; a reordered sum's
  difference reported as a bug.
- **Float literals passed to mpmath.** `mpf(0.1)` is not 1/10.
- **More digits than κu supports.**
- **Accelerator precision.** float32, TF32 or bfloat16 defaults on accelerators, and float32 by
  default in JAX.
- **Unshifted tails and exponentials.** 1 − cdf instead of `sf` for tails, or log(sum(exp(x)))
  without the max shift.
- **One test input.** Also test tiny, huge, negative and subnormal inputs.

Related: `matrix-decompositions-conditioning`, `uncertainty-propagation-fitting`, `simulation-verification-validation`, `physics-toolkit`, `sympy-symbolic-verification`, `python-performance-profiling`, hub `mathematics-toolkit`
