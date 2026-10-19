# Robertson (ROBER) reference data, computed without SciML

Independent reference for the skill's worked example: a plain-Julia 3-stage Radau IIA (order 5,
L-stable) integrator with full Newton iterations on a geometric time grid. Runs in about 2 s on
Julia 1.13.2 with only the LinearAlgebra stdlib, so it can validate any solver configuration.

Problem: `y1' = -k1 y1 + k3 y2 y3`, `y2' = k1 y1 - k2 y2^2 - k3 y2 y3`, `y3' = k2 y2^2`,
`k = (0.04, 3e7, 1e4)`, `y(0) = (1, 0, 0)`, conserved `y1 + y2 + y3 = 1`.

## 1. Results

| t | y1 | y2 | y3 |
|---|---|---|---|
| 40 | 7.15827068719403e-1 | 9.18553476455777e-6 | 2.84163745745829e-1 |
| 1e5 | 1.78659211420993e-2 | 7.27475146843626e-8 | 9.82134006110384e-1 |

Grid ratios `r = 1.002` and `r = 1.001` agree to 3e-15 relative; `y1 + y2 + y3 - 1` is below
4e-15. The t = 40 values match the classical published ROBER values (y1 ≈ 0.715827,
y2 ≈ 9.1855e-6, y3 ≈ 0.284164). `y2` peaks at about 3.65e-5 near t ≈ 5e-3.

Jacobian eigenvalues along the reference solution (one is always ~0 from conservation):

| t | fast eigenvalue | slow eigenvalue |
|---|---|---|
| 1e-3 | -1750 | -0.33 |
| 1 | -2180 | -0.29 |
| 40 | -3393 | -0.021 |
| 1e5 | -9826 | -1.8e-5 |

Stiffness ratio at t = 1e5: 9826 / 1.8e-5 ≈ 5e8.

## 2. Explicit-solver behaviour (Dormand-Prince 5(4) stand-in for Tsit5)

A textbook adaptive Dormand-Prince 5(4) loop (same explicit RK class as `Tsit5`, `rtol = atol =
1e-6`, step factor limits 0.2-5, `maxiters = 1e5` like SciML's default) gave:

| Target | Outcome |
|---|---|
| t = 40 | reached after 49,373 iterations (13,243 rejected); `y1(40)` relative error 1.6e-4 despite `rtol = 1e-6` |
| t = 1e5 | stopped at t = 72.5 after 100,000 iterations, 26% rejected; final `h = 8.3e-4` |

At the stall `h·|λ| = 8.3e-4 × 3895 = 3.2`, the edge of the explicit stability region on the
negative real axis (about 3.3 for Dormand-Prince 5). The step size is set by stability, not
accuracy: reaching t = 1e5 with `h ≤ 3.3/9826 ≈ 3.4e-4` needs on the order of 3e8 steps.

## 3. Script

```julia
using LinearAlgebra, Printf

const k1, k2, k3 = 0.04, 3e7, 1e4
rober(y) = [-k1 * y[1] + k3 * y[2] * y[3],
             k1 * y[1] - k2 * y[2]^2 - k3 * y[2] * y[3],
             k2 * y[2]^2]
jac(y) = [-k1  k3 * y[3]                  k3 * y[2];
           k1  -2k2 * y[2] - k3 * y[3]   -k3 * y[2];
           0.0  2k2 * y[2]                0.0]

const s6 = sqrt(6.0)                     # Radau IIA order 5; last row of A is b
const A = [(88 - 7s6) / 360      (296 - 169s6) / 1800  (-2 + 3s6) / 225;
           (296 + 169s6) / 1800  (88 + 7s6) / 360      (-2 - 3s6) / 225;
           (16 - s6) / 36        (16 + s6) / 36        1 / 9]
const c = [(4 - s6) / 10, (4 + s6) / 10, 1.0]
@assert all(abs(dot(A[3, :], c .^ (k - 1)) - 1 / k) < 1e-15 for k in 1:5)   # B(5) conditions

function radau_step(y0, h; n = length(y0))
    Z = zeros(3n)
    for _ in 1:50                                       # full Newton on the stage equations
        Y = [y0 + Z[(j-1)*n+1:j*n] for j in 1:3]
        F = [rober(Y[j]) for j in 1:3]
        G = similar(Z); J = zeros(3n, 3n)
        for i in 1:3
            G[(i-1)*n+1:i*n] = Z[(i-1)*n+1:i*n] - h * sum(A[i, j] * F[j] for j in 1:3)
            for j in 1:3
                J[(i-1)*n+1:i*n, (j-1)*n+1:j*n] = (i == j) * I(n) - h * A[i, j] * jac(Y[j])
            end
        end
        dZ = J \ G
        Z -= dZ
        norm(dZ) < 1e-15 * (1 + norm(Z)) && break
    end
    return y0 + Z[2n+1:3n]
end

function reference(tout; r = 1.001)                    # h = t*(r-1) after a uniform start
    y = [1.0, 0.0, 0.0]; t = 0.0
    for _ in 1:200
        y = radau_step(y, 1e-6 / 200); t += 1e-6 / 200
    end
    out = Dict{Float64,Vector{Float64}}()
    for T in sort(tout)
        while t < T
            h = min(t * (r - 1), T - t)
            y = radau_step(y, h); t += h
        end
        out[T] = copy(y)
    end
    return out
end

ts = [40.0, 1e5]
coarse, fine = reference(ts; r = 1.002), reference(ts; r = 1.001)
for T in ts
    y = fine[T]
    @printf("t = %-6g y = [%.15e, %.15e, %.15e]  sum-1 = %.1e  grid diff = %.1e\n",
            T, y..., sum(y) - 1, maximum(abs.(coarse[T] .- y) ./ abs.(y)))
end
```

Use it to validate solver choices and tolerances: the relative error of `sol.u[end]` against
the t = 1e5 row should shrink roughly in proportion to `reltol` until it reaches ~1e-12.
