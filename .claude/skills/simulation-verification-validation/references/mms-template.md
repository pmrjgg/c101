# MMS template and order-test harness

Both scripts were run in October 2026 (NumPy 2.5, SciPy 1.18, SymPy 1.14); the printed orders are
quoted under each. Copy the structure, not the operator: the pattern is u* → S → solve with S and
u*-derived boundary data → error norms on 3–4 levels → observed orders.

## 1. Choosing u*

| Rule | Why |
|---|---|
| Smooth, non-polynomial (sin, cos, exp, products) | polynomials of low degree are reproduced exactly by many schemes, hiding errors |
| Every operator term active and of comparable size | a term that is 1e-6 of the others is not tested |
| No symmetry that zeroes a term (u* even about a boundary kills odd derivatives there) | silent passes |
| Physically admissible (positive density, temperature, turbulence quantities) | solvers clip or fail otherwise |
| Time dependence when the code is unsteady, e.g. factors e^{−t} or (1 + 0.1 sin t) | tests the time integrator and its coupling to space |
| Boundary data from u* for every BC type the result uses | BC closures are where order is lost |
| Variable coefficients when the code supports them (k(x), ρ(x)) | tests flux forms and face averaging |

## 2. One-dimensional harness with three boundary closures

Problem: −(k u′)′ + c u = S on [0, 1], k = 1 + x², c = 2, Dirichlet at x = 1, Neumann flux
q₀ = −k u′(0) at x = 0, second-order finite differences in flux form.

```python
import numpy as np, sympy as sp

x = sp.symbols("x")
u_star = sp.sin(sp.pi*x)*sp.exp(x) + x**2
k = 1 + x**2
c = 2
S = -sp.diff(k*sp.diff(u_star, x), x) + c*u_star
u_f, S_f, k_f = (sp.lambdify(x, e, "numpy") for e in (u_star, S, k))
q0 = float(sp.lambdify(x, -k*sp.diff(u_star, x))(0.0))

def solve(N, bc="half-cell"):
    h = 1.0/N; xs = np.linspace(0, 1, N + 1)
    kp, km = k_f(xs + h/2), k_f(xs - h/2)
    A = np.zeros((N + 1, N + 1)); b = S_f(xs).astype(float)
    for i in range(1, N):
        A[i, i - 1], A[i, i + 1] = -km[i]/h**2, -kp[i]/h**2
        A[i, i] = (km[i] + kp[i])/h**2 + c
    A[N, N] = 1.0; b[N] = u_f(1.0)                                   # Dirichlet at x = 1
    if bc == "half-cell":       # finite volume over [0, h/2]: second order
        A[0, 0], A[0, 1], b[0] = 2*kp[0]/h**2 + c, -2*kp[0]/h**2, S_f(0.0) + 2*q0/h
    elif bc == "sign-error":    # the same closure with the flux sign flipped
        A[0, 0], A[0, 1], b[0] = 2*kp[0]/h**2 + c, -2*kp[0]/h**2, S_f(0.0) - 2*q0/h
    else:                       # "one-sided": -k0 (u1 - u0)/h = q0, first order
        A[0, 0], A[0, 1], b[0] = k_f(0.0)/h, -k_f(0.0)/h, q0
    e = np.linalg.solve(A, b) - u_f(xs)
    return np.sqrt(h*np.sum(e**2)), np.abs(e).max()

def observed_orders(errors, r=2.0):
    e = np.asarray(errors); return np.log(e[:-1]/e[1:])/np.log(r)

for bc in ("half-cell", "one-sided", "sign-error"):
    E = np.array([solve(N, bc) for N in (16, 32, 64, 128)])
    print(bc, E[:, 0], observed_orders(E[:, 0]), observed_orders(E[:, 1]))
```

Output:

```
half-cell   L2 [5.434e-03 1.319e-03 3.247e-04 8.056e-05]  p_L2 [2.04 2.02 2.01]  p_inf [2.00 2.00 2.00]
one-sided   L2 [7.117e-02 3.541e-02 1.764e-02 8.804e-03]  p_L2 [1.01 1.01 1.00]  p_inf [0.96 0.98 0.99]
sign-error  L2 [1.812     1.761     1.734     1.720    ]  p_L2 [0.04 0.02 0.01]  p_inf [0.00 0.00 0.00]
```

The sign-error row is a real bug this harness caught while the template was being written: the
first draft of the half-cell closure had the flux term with the wrong sign, and the error stayed
at O(1) on every level.

## 3. Two-dimensional advection-diffusion template

−∇·(k∇u) + a·∇u = S on the unit square, k = 1 + xy, a = (1, 0.5), Dirichlet data from u*,
five-point flux-form diffusion with face-centred k and central advection (second order).

```python
import numpy as np, sympy as sp
import scipy.sparse as sps, scipy.sparse.linalg as spla
x, y, t = sp.symbols("x y t")
u_s = sp.sin(sp.pi*x)*sp.cos(sp.pi*y/2)*sp.exp(x*y) + x**2*y
k_s = 1 + x*y
a = (1.0, 0.5)
S_s = (sp.diff(u_s, t) + a[0]*sp.diff(u_s, x) + a[1]*sp.diff(u_s, y)      # u_t = 0 here;
       - sp.diff(k_s*sp.diff(u_s, x), x) - sp.diff(k_s*sp.diff(u_s, y), y))   # keep it for unsteady u*
u_f, k_f, S_f = (sp.lambdify((x, y), e, "numpy") for e in (u_s, k_s, S_s))

def solve(N):
    h = 1.0/N; xs = np.linspace(0, 1, N + 1); X, Y = np.meshgrid(xs, xs, indexing="ij")
    idx = -np.ones((N + 1, N + 1), int); inner = (slice(1, N), slice(1, N))
    idx[inner] = np.arange((N - 1)**2).reshape(N - 1, N - 1)
    rows, cols, vals = [], [], []; b = S_f(X, Y)[inner].ravel().astype(float)
    for i in range(1, N):
        for j in range(1, N):
            r = idx[i, j]
            ke, kw = k_f(X[i, j] + h/2, Y[i, j]), k_f(X[i, j] - h/2, Y[i, j])
            kn, ks = k_f(X[i, j], Y[i, j] + h/2), k_f(X[i, j], Y[i, j] - h/2)
            coef = {(i, j): (ke + kw + kn + ks)/h**2,
                    (i + 1, j): -ke/h**2 + a[0]/(2*h), (i - 1, j): -kw/h**2 - a[0]/(2*h),
                    (i, j + 1): -kn/h**2 + a[1]/(2*h), (i, j - 1): -ks/h**2 - a[1]/(2*h)}
            for (ii, jj), cf in coef.items():
                if idx[ii, jj] >= 0:
                    rows.append(r); cols.append(idx[ii, jj]); vals.append(cf)
                else:
                    b[r] -= cf*u_f(X[ii, jj], Y[ii, jj])          # Dirichlet data from u*
    A = sps.csr_matrix((vals, (rows, cols)), shape=((N - 1)**2,)*2)
    E = spla.spsolve(A, b) - u_f(X, Y)[inner].ravel()
    return np.sqrt(np.mean(E**2)), np.abs(E).max()
```

Output for N = 16, 32, 64, 128: L2 1.00e-3, 2.42e-4, 5.96e-5, 1.48e-5 (p = 2.05, 2.02, 2.01);
L∞ p = 2.00 on every pair.

## 4. Harness checklist

- Error norms: discrete L2 (sqrt of the mean square, or sqrt(h Σ e²) in 1D) and L∞; for finite
  volumes compare cell averages of u*, not point values, or accept an O(h²) offset.
- Levels: 3 minimum, 4 preferred; the coarsest must already resolve u* (several points per
  wavelength).
- Iterative solvers: converge to 1e-3 of the finest discretisation error or the order stalls.
- Time: either refine Δt ∝ Δx (fixed Courant number) and expect min(p_space, p_time) in the
  combined error, or freeze one parameter at a value whose error is 100× below the other.
- Record the expected and observed orders per norm in the test; fail when |p_obs − p_th| > 0.1
  on the two finest pairs.
- Systems: one u* per field, chosen so that coupling terms are active (no field identically zero).
- Nonlinear operators: S comes from the full nonlinear operator applied to u*; MMS does not need
  the problem to be linear.
- Code paths: every boundary type, every coefficient model and every branch (limiters off and on)
  needs its own run; a limiter clipping a smooth u* drops the order to about 1 near extrema.
