# ModelingToolkit and DAE recipes

ModelingToolkit (MTK) is at 11.45 as of October 2026. Its API changed in v10 and again in v11;
check `Pkg.status("ModelingToolkit")` and read the matching docs before writing model code.

## 1. Version map

| Concept | v9 | v10 | v11 |
|---|---|---|---|
| simplify + index reduction + tearing | `structural_simplify(sys)` | `mtkcompile(sys)` | `mtkcompile(sys)` |
| build macro | `@mtkbuild` | `@mtkcompile` | `@mtkcompile` |
| system types | `ODESystem`, `NonlinearSystem`, ... | unified `System(eqs, t)` / `System(eqs)` | same |
| problem constructor | `ODEProblem(sys, u0map, tspan, pmap)` | `ODEProblem(sys, op, tspan)` with one variable/parameter map | same |
| inputs/outputs | positional `(inputs, outputs)` | `mtkcompile(sys; inputs, outputs, disturbance_inputs)` | same |
| callback affects | `A ~ A + 1` | `A ~ Pre(A) + 1`, changed parameters listed in `discrete_parameters` | same |
| defaults | `defaults` | `defaults` | removed: `initial_conditions` (convenience values) and `bindings` (immutable relations) |
| `@mtkmodel` DSL | supported | supported | deprecated, moved to SciCompDSL.jl |
| index reduction | included | included | full `mtkcompile` lives in ModelingToolkit (uses AGPL-licensed StateSelection.jl and ModelingToolkitTearing); ModelingToolkitBase has a simpler `mtkcompile` without index reduction, requiring explicit `D(x) ~ ...` equations |

Licensing matters for distribution: check with the project owner before shipping code that
depends on the AGPL-licensed structural-simplification packages.

## 2. High-index DAE: pendulum (from the MTK initialization tutorial)

```julia
using ModelingToolkit, OrdinaryDiffEq, SciMLBase
using ModelingToolkit: t_nounits as t, D_nounits as D

@parameters g
@variables x(t) y(t) [state_priority = 10] λ(t)
eqs = [D(D(x)) ~ λ * x
       D(D(y)) ~ λ * y - g
       x^2 + y^2 ~ 1]                         # index-3 constraint
@mtkcompile pend = System(eqs, t)              # index reduction + tearing
prob = ODEProblem(pend, [x => 1, y => 0, g => 1], (0.0, 1.5), guesses = [λ => 1])
sol = solve(prob, Rodas5P())
SciMLBase.successful_retcode(sol) || error("pendulum failed: $(sol.retcode)")
```

- `guesses` seed the nonlinear initialization solve for algebraic unknowns (`λ`); they are not
  initial conditions.
- `initialization_eqs = [y ~ 0]` (problem or `System` keyword) adds conditions that hold only
  at `t0`.
- An unsatisfiable set of conditions returns `ReturnCode.InitialFailure`.
- Inspect: `generate_initializesystem(pend; op = [x => 1.0, y => 0.0], guesses = [λ => 1])` or
  `ModelingToolkit.InitializationProblem(pend, 0.0, op; guesses)`.
- Observed (eliminated) variables stay accessible: `sol[λ]`, `sol[x^2 + y^2]`.

Numeric code that already exists as a mass-matrix ODE can be index-reduced through tracing:

```julia
using ModelingToolkit, OrdinaryDiffEq, LinearAlgebra
function pendulum!(du, u, p, t)
    x, dx, y, dy, T = u
    g, L = p
    du[1] = dx; du[2] = T * x; du[3] = dy; du[4] = T * y - g
    du[5] = x^2 + y^2 - L^2                   # algebraic row (mass-matrix entry 0)
    return nothing
end
f = ODEFunction(pendulum!, mass_matrix = Diagonal([1, 1, 1, 1, 0]))
traced = modelingtoolkitize(ODEProblem(f, [1.0, 0, 0, 0, 0], (0, 10.0), [9.8, 1]))
sys = mtkcompile(dae_index_lowering(traced))
sol = solve(ODEProblem(sys, [], (0, 10.0)), Rodas5P(); abstol = 1e-8, reltol = 1e-8)
```

## 3. Acausal components (plain functions, v11 docs pattern)

```julia
using ModelingToolkit, OrdinaryDiffEq, Setfield
using ModelingToolkit: t_nounits as t, D_nounits as D

function Pin(; name)
    @variables v(t) i(t) [connect = Flow]          # potential v, flow i
    sys = System(Equation[], t, [v, i], []; name)
    return @set sys.connector_type = ModelingToolkit.connector_type(sys)
end
function TwoPin(; name)                            # shared base: voltage drop and through-current
    @named p = Pin(); @named n = Pin()
    @variables v(t) i(t)
    System([v ~ p.v - n.v, 0 ~ p.i + n.i, i ~ p.i], t, [v, i], []; systems = [p, n], name)
end
function Resistor(; name, R = 1.0)
    @named port = TwoPin(); @unpack v, i = port
    @parameters R = R
    extend(System([v ~ i * R], t, [], [R]; name), port)
end
function Capacitor(; name, C = 1.0)
    @named port = TwoPin(); @unpack v, i = port
    @parameters C = C
    extend(System([D(v) ~ i / C], t, [], [C]; name), port)
end
function Source(; name, V = 1.0)
    @named port = TwoPin(); @unpack v = port
    @parameters V = V
    extend(System([V ~ v], t, [], [V]; name), port)
end
function Ground(; name)
    @named g = Pin()
    System([g.v ~ 0], t, [], []; systems = [g], name)
end

@named R1 = Resistor(R = 2.0); @named C1 = Capacitor(C = 1.0)
@named V1 = Source(V = 1.0);   @named gnd = Ground()
eqs = [connect(V1.p, R1.p), connect(R1.n, C1.p), connect(C1.n, V1.n), connect(C1.n, gnd.g)]
@named rc = System(eqs, t; systems = [R1, C1, V1, gnd])
rc = mtkcompile(rc)                                # connection equations expanded, aliases removed
sol = solve(ODEProblem(rc, [rc.C1.v => 0.0], (0.0, 10.0)), Rodas5P())
```

Expected physics for a check: `C1.v(t) = 1 - exp(-t / (R*C))`, so `sol[rc.C1.v][end] ≈ 1 - exp(-5)`
to the solver tolerance. ModelingToolkitStandardLibrary.jl ships tested electrical,
mechanical, thermal and block components; prefer it over hand-written components.

## 4. DAEs without ModelingToolkit

| Form | Construction | Solvers |
|---|---|---|
| semi-explicit, mass matrix `M u' = f(u)` | `ODEFunction(f!; mass_matrix = M)` (singular `M`, zero rows are algebraic) | `Rodas5P()`, `Rodas4P()`, `FBDF()`, `RadauIIA5()` |
| fully implicit `F(du, u, p, t) = 0` | `DAEProblem(F!, du0, u0, tspan, p; differential_vars = [true, true, false])` | `DFBDF()` (`OrdinaryDiffEqBDF`), `IDA()` (Sundials) |

Initial conditions: since OrdinaryDiffEq v7 the default `CheckInit()` errors when `u0`/`du0` do
not satisfy the algebraic equations. Either compute consistent values (a nonlinear solve on the
algebraic rows) or pass `initializealg = BrownFullBasicInit()` (fixes algebraic variables given
the differential ones) or `ShampineCollocationInit()`. Index > 1 problems need index reduction
(MTK) before these solvers can work reliably.

## 5. Typical MTK failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `ExtraVariablesSystemException` / `ExtraEquationsSystemException` | unbalanced model (missing or duplicated equations) | count equations vs unknowns per component; check every connector is connected or grounded |
| `InitialFailure` retcode | unsatisfiable or under-specified initialization | add `guesses`, remove conflicting `initialization_eqs`, inspect the initialization system |
| `UndefVarError: structural_simplify` / `@mtkbuild` | code written for v9 on v10+ | `mtkcompile` / `@mtkcompile` |
| `ODEProblem(sys, u0map, tspan, pmap)` errors | v9 signature | merge into one map: `ODEProblem(sys, [u0map; pmap], tspan)` |
| affect `A ~ A + 1` errors as unsatisfiable | v10 callback semantics | `A ~ Pre(A) + 1`, list `A` in `discrete_parameters` if it is a parameter |
| slow first `mtkcompile` | compilation of the symbolic stack | v11 reduced this sharply (release notes show ~1.8 s to ~0.02 s for one benchmark); keep models in a package with precompilation |
