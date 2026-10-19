# CI gates for inference and allocations

## 1. Test environment

`test/Project.toml` (preferred over `[extras]`):

```toml
[deps]
AllocCheck = "9b6a8646-10ed-4001-bbdc-1d2f46dfbb1a"
JET = "c3a54625-cd67-489e-a8e7-0a5a0ff4e31b"
Test = "8dfed614-e22c-5e08-85e1-65c5234f0b40"
```

Add entries with the Pkg API so UUIDs are correct:
`julia --project=test -e 'using Pkg; Pkg.add(["JET", "AllocCheck"])'`. JET resolves to a series
matching the running Julia; a package that also loads Revise in the same environment can pin an
incompatible JuliaInterpreter, so keep JET out of the main project and the default `@v1.x`
environment.

## 2. `test/runtests.jl` layout

```julia
using Test, MyPkg

@testset "MyPkg" begin
    include("unit_tests.jl")
    include("stability_tests.jl")
end
```

`test/stability_tests.jl`:

```julia
using Test, AllocCheck, MyPkg
import JET

# Run every check inside a function: no globals in the measured expression.
function alloc_bytes(f!, args...)
    f!(args...)                          # warm-up compiles
    return @allocated f!(args...)
end

@testset "inference" begin
    x = rand(128); out = similar(x)
    @inferred MyPkg.kernel!(out, x)
    @inferred Union{Nothing,Int} MyPkg.find_first_peak(x)    # deliberate small union
    @test Base.return_types(MyPkg.kernel!, (Vector{Float64}, Vector{Float64})) == [Vector{Float64}]
end

@testset "allocation budgets" begin
    x = rand(128); out = similar(x)
    @test alloc_bytes(MyPkg.kernel!, out, x) == 0
    @test alloc_bytes(MyPkg.solve_small!, zeros(8), x) <= 1024     # budget, not zero
    @test isempty(check_allocs(MyPkg.kernel!, (Vector{Float64}, Vector{Float64})))
end

if JET.JET_AVAILABLE
    @testset "JET" begin
        x = rand(128); out = similar(x)
        JET.@test_opt target_modules=(MyPkg,) MyPkg.kernel!(out, x)
        JET.test_package(MyPkg; target_modules=(MyPkg,))
    end
else
    @info "JET analysis unavailable on Julia $(VERSION); skipping"
end
```

Notes:

- `@test_opt` fails the test on any runtime-dispatch report in the filtered scope; mark known
  issues with `broken=true` rather than deleting the check.
- `JET.test_package` runs JET's error analysis over the whole package (default `mode=:basic`;
  `:sound` reports every possible error with more false positives; `:typo` only likely typos).
- Allocation numbers can change between Julia minors (e.g. `Array` became a wrapper over
  `Memory` in 1.11, so one array allocation can count as more than one allocation event):
  assert bytes or zero, not exact allocation counts, for non-zero budgets.

## 3. DispatchDoctor in tests

Library code wraps hot modules with `@stable default_mode="disable" begin ... end`. The test job
enables the checks through a preference, set at the top of `test/runtests.jl` before the
package is imported (the DispatchDoctor README pattern; the name string is resolved through the
active environment):

```julia
using Preferences: set_preferences!
set_preferences!("MyPkg", "dispatch_doctor_mode" => "error"; force = true)   # writes LocalPreferences.toml
using Test, MyPkg
```

In an interactive session, restart Julia after changing a preference. Other keys: `dispatch_doctor_codegen_level` (`"min"` for
coverage runs and shorter precompilation), `dispatch_doctor_union_limit`.
Checks are active only on Julia [1.10, 1.13) as of DispatchDoctor 0.4.29, and are ignored during
precompilation, so run this job on 1.12 or the 1.10 LTS.

## 4. Matrix

| Job | Julia | Runs |
|---|---|---|
| unit + inference + allocations | 1.10 (LTS) and 1.13 (release) | `Pkg.test()` |
| JET | 1.12 and 1.13 | the JET testset (skips itself elsewhere) |
| DispatchDoctor | 1.12 | `Pkg.test()` with `dispatch_doctor_mode = "error"` |
| bounds | release | `julia --check-bounds=yes --project -e 'using Pkg; Pkg.test()'` |

Bounds checks: up to Julia/Pkg 1.12, `Pkg.test()` forced `--check-bounds=yes`. Since Pkg 1.13
it inherits the parent session's setting (Pkg 1.13 changelog), so start the parent with
`--check-bounds=yes` (as in the table) or pass `julia_args=["--check-bounds=yes"]` to
`Pkg.test` to keep `@inbounds` mistakes visible.

## 5. Quick local gate (no test package needed)

Plain-text `code_warntype` prints warnings in UPPERCASE (`Main.g::ANY`, `s@_4::CORE.BOX`), so a
regex can flag them. The `UNION{NOTHING, TUPLE{...}}` of the iterate protocol is excluded.
Tested on 1.13: flags the unstable `advance!` (7 lines) and the boxing closure (9 lines),
reports the stable 5-argument `advance_kernel!` method as clean.

```julia
using InteractiveUtils
function warntype_issues(f, types)
    s = sprint(io -> code_warntype(io, f, types))
    filter(split(s, "\n")) do l
        (occursin(r"::[A-Z][A-Z0-9_]{2,}(?![a-z])", l) && !occursin("UNION{NOTHING, TUPLE{", l)) ||
            occursin("Core.Box", l)
    end
end
issues = warntype_issues(MyPkg.kernel!, (Vector{Float64}, Vector{Float64}))
isempty(issues) || (foreach(println, issues); error("type instability in kernel!"))
```

Check the method that holds the loop: for functions with default arguments, pass the full
signature (all positional arguments), because the short method only forwards.
