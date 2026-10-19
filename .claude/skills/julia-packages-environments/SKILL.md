---
name: julia-packages-environments
description: "Julia package and environment engineering. Covers Project and Manifest policy, [compat] bounds, test environments, package extensions, workspaces and [sources], public API marking, Aqua, JET and ExplicitImports gates, Documenter, CI with julia-actions, registration with Registrator and TagBot, and PrecompileTools latency work. Load when creating, releasing or maintaining a Julia package or reproducible project."
when_to_use: "Creating a Julia package or application; Pkg errors such as 'Unsatisfiable requirements detected'; deciding whether to commit Manifest.toml; writing [compat], [weakdeps], [extensions], [sources] or [workspace] entries; setting up test/Project.toml or @testitem suites; Aqua, JET or ExplicitImports failures; julia-actions CI workflows; registering a release with Registrator and TagBot; slow 'using' or time-to-first-call; building an executable with juliac or PackageCompiler."
---

# Julia packages and environments

An environment is a Project.toml (direct dependencies and compat ranges) plus a Manifest.toml
(the exact resolved graph). Packages declare ranges; applications pin graphs. Agents drive Pkg
through its API (`julia --project=. -e 'using Pkg; Pkg.add("Foo")'`); the `]` forms are for
humans at the REPL.

Version-dependent: `[sources]` and `public` need Julia 1.11+; `[workspace]`, Pkg apps and
JuliaC need 1.12+; package extensions need 1.9+ (every version once the minimum is the 1.10 LTS).

## 1. Project vs package

| Kind | Project.toml has | Commit Manifest.toml? | Compat |
|---|---|---|---|
| package (library) | `name`, `uuid`, `version`, `[compat]` | no: gitignore `Manifest*.toml` | required for every dependency |
| application, service, analysis | deps, optional `name` | yes: `Pkg.instantiate()` reproduces it | optional, still useful |
| docs/, test/, benchmark/ | deps | no, unless they are workspace members (section 5) | loose |

- Apps run on several Julia minors: versioned manifests (`Manifest-v1.12.toml`) give each minor
  its own resolution (read by recent 1.10.x and later).
- juliaup manages Julia: `juliaup add release`, `juliaup add lts`, `juliaup add 1.11`,
  `juliaup default release`, `juliaup update`, `juliaup status`; one-off runs with
  `julia +lts` or `julia +1.11`.
- Keep the default environment (`@v1.12`) to dev tools (Revise, BenchmarkTools, JET). It stacks
  under every project, so a package installed there hides a missing dependency until CI fails.
  Scratch work goes in `Pkg.activate(; temp = true)`.

## 2. [compat] rules

| Entry | Allowed versions |
|---|---|
| `"1.2"`, `"1.2.3"` | [1.2.0 or 1.2.3, 2.0.0): caret, the default |
| `"0.3"` | [0.3.0, 0.4.0): in 0.x the minor is the breaking digit |
| `"0.0.3"` | [0.0.3, 0.0.4) |
| `"~1.2.3"` | [1.2.3, 1.3.0) |
| `"=1.2.3"` | exactly 1.2.3 |
| `"1.6, 2"` | union: [1.6.0, 3.0.0) |
| `"1.2 - 1.4"` | [1.2.0, 1.5.0) |
| `">= 1.2"` | unbounded: never in a registered package |

- Every non-stdlib entry in `[deps]`, `[weakdeps]` and `[extras]` gets a compat entry, plus
  `julia = "1.10"` (or your minimum); General's AutoMerge blocks releases without them.
- Lower bound: the oldest version you know works. Upper bound: the next breaking version (caret).
- CompatHelper (a scheduled workflow) opens a PR when a dependency ships a new breaking version;
  merge only when CI passes against it. `Pkg.compat("Foo", "1.2, 2")` edits entries from code.
- Updating an app: `Pkg.update("Foo"; preserve = Pkg.PRESERVE_ALL)` moves only Foo; then other
  targeted updates one at a time, never a blanket `Pkg.update()` before a deadline.
  `Pkg.status(; outdated = true)` marks packages held back by compat with ⌅.

Resolver errors ("Unsatisfiable requirements detected for package Foo"): read the log tree from
the bottom; each line names who restricts Foo and to which range, ending at "no versions left".
`Pkg.why("Foo")` (1.9+) prints the paths that pull Foo in. Fix by widening your own compat,
upgrading the restricting package or dropping the dependency; a library never pins a transitive
dependency.

## 3. Test environments

| Approach | Where | Notes |
|---|---|---|
| `test/Project.toml` | separate env; the package itself is added automatically | preferred |
| `[extras]` + `[targets] test = ["Test", ...]` | main Project.toml | legacy, still common |
| workspace member `test` | `[workspace] projects = ["test"]` (1.12+) | one manifest; `julia --project=test` works directly |

```bash
julia --project=. -e 'using Pkg; Pkg.test()'
julia --project=. -e 'using Pkg; Pkg.test(; test_args = ["fast"])'     # runtests.jl reads ARGS
julia --project=. -e 'using Pkg; Pkg.test(; coverage = true)'
```

TestItemRunner: each `@testitem` runs in its own module (and individually from VS Code).

```julia
@testitem "parse round-trip" tags = [:fast] begin
    using MyPkg: parse_config, render, default_config
    cfg = default_config()
    @test parse_config(render(cfg)) == cfg
end

# test/runtests.jl
using TestItemRunner
@run_package_tests filter = ti -> !(:slow in ti.tags)
```

Shared setup: `@testsnippet` (code spliced into each item) or `@testmodule` (loaded once).
ReTestItems.jl runs the same items in parallel worker processes from files named `*_tests.jl`:
`using ReTestItems; runtests(MyPkg; nworkers = 4)`.

## 4. Package extensions

```toml
[weakdeps]
Plots = "91a5bcdd-55d7-5caf-9e0b-520d859cae80"

[extensions]
MyPkgPlotsExt = "Plots"            # ["Plots", "Unitful"] when both must be loaded

[compat]
Plots = "1"
```

```julia
# src/MyPkg.jl: own the function; the extension only adds methods
"""
    plotfit(result; kwargs...)

Plot a fit. Available after `using Plots`.
"""
function plotfit end

# ext/MyPkgPlotsExt.jl: file and module name must match the [extensions] key
module MyPkgPlotsExt
using MyPkg, Plots
MyPkg.plotfit(r::MyPkg.FitResult; kw...) = plot(r.x, r.y; label = "fit", kw...)
end
```

- The extension loads by itself once MyPkg and every trigger are loaded, and precompiles
  separately. `Base.get_extension(MyPkg, :MyPkgPlotsExt)` returns the module or `nothing` (tests).
- Users cannot reach names defined only inside an extension: put functions and types in the parent.
- Adding a weak dependency: newer Pkg versions accept `]add --weak Plots`; otherwise add it
  normally, move the line from `[deps]` to `[weakdeps]`, and add the compat entry.
- Migrating off Requires.jl: turn each `@require Plots="..." include("plots.jl")` from
  `__init__` into an extension and delete Requires; with `julia = "1.10"` no fallback is needed.

## 5. Monorepos: workspace and sources

```toml
# root Project.toml, Julia 1.12+: one Manifest.toml for every listed project
[workspace]
projects = ["test", "docs", "benchmark", "lib/MyPkgCore"]

# Julia 1.11+: where unregistered or local dependencies come from
[sources]
MyPkgCore = {path = "lib/MyPkgCore"}
Forked = {url = "https://github.com/me/Forked.jl", rev = "fix-branch"}
```

- `[sources]` applies only to the active project; dependents of a registered package ignore it,
  so a registered release must resolve without it.
- Before 1.11: `Pkg.develop(path = "lib/MyPkgCore")` records the path in the manifest; keep it
  relative, never commit an absolute path.
- Workspace resolution is joint: a compat conflict in `docs` also blocks `test`. That is the
  point (one consistent graph), so keep docs-only dependencies loosely bounded.

## 6. API surface

- `export f` brings `f` into scope on `using MyPkg`; `public g` (1.11+) marks `g` as API without
  exporting it (`MyPkg.g`). On 1.10 write `Compat.@compat public g`. `Base.ispublic(MyPkg, :g)`.
- Everything neither exported nor public is internal and may change in any release; say so in
  the docs.

Docstrings carry `jldoctest` examples, and `docs/make.jl` calls `makedocs` and `deploydocs`;
templates for both: [ci-and-docs](references/ci-and-docs.md).

`makedocs` runs the doctests; also call `doctest(MyPkg)` from the test suite so a docs build is
not the only gate. Deployment needs a `DOCUMENTER_KEY` deploy-key secret (DocumenterTools
generates the pair).

## 7. Quality gates

```julia
# test/qa.jl, included from runtests.jl
using Aqua, JET, ExplicitImports, MyPkg, Test
@testset "quality" begin
    Aqua.test_all(MyPkg)     # ambiguities, unbound type params, stale deps, compat, piracy
    @test check_no_implicit_imports(MyPkg) === nothing        # throws on failure
    @test check_no_stale_explicit_imports(MyPkg) === nothing
    if v"1.12" <= VERSION < v"1.13"      # example gate: run JET only on the minor its release supports
        JET.test_package(MyPkg; target_modules = (MyPkg,))
    end
end
```

- Tune Aqua instead of disabling a check:
  `Aqua.test_all(MyPkg; ambiguities = (exclude = [Base.show],), piracies = (treat_as_own = [Wrapped],))`.
- JET is coupled to Julia internals; see `julia-type-stability` for the version map.
- Formatting, pick one: JuliaFormatter with `.JuliaFormatter.toml` (`style = "blue"`), checked by
  `julia -e 'using JuliaFormatter; exit(format(".") ? 0 : 1)'` (`format` returns true when nothing
  changed); or Runic (no options): `runic --check --diff .`, `fredrikekre/runic-action@v1` in CI.

## 8. CI

| Piece | Setting |
|---|---|
| matrix | `version: ['lts', '1', 'pre']` on `ubuntu-latest`, plus `'1'` on `macos-latest` and `windows-latest`; `fail-fast: false`; `continue-on-error` for `pre` |
| test steps | `actions/checkout@v4`, `julia-actions/setup-julia@v2`, `julia-actions/cache@v2`, `julia-actions/julia-buildpkg@v1`, `julia-actions/julia-runtest@v1`, `julia-actions/julia-processcoverage@v1`, `codecov/codecov-action@v5` |
| docs job | `julia-actions/julia-docdeploy@v1` with `GITHUB_TOKEN` and `DOCUMENTER_KEY` from repository secrets |

`lts` is the long-term-support release, `1` the latest release, `pre` the latest prerelease.
Complete `CI.yml`: [ci-and-docs](references/ci-and-docs.md).

## 9. Releasing

Semver: patch for fixes, minor for additions (in 0.x the minor digit is breaking), major for
breaking changes to exported or `public` names and documented behaviour.

1. Bump `version` in Project.toml through a PR; merge when CI is green.
2. Comment `@JuliaRegistrator register` on the merge commit (Registrator GitHub app); add a
   `Release notes:` paragraph and list breaking changes explicitly.
3. General's AutoMerge checks compat entries, version sequencing and, for new packages, naming;
   new packages wait three days, new versions usually merge within minutes.
4. TagBot (`.github/workflows/TagBot.yml`) creates the git tag and GitHub release after the
   registry merge; never tag by hand first.

Private registries with LocalRegistry.jl:

```julia
using LocalRegistry
create_registry("MyRegistry", "git@github.com:me/MyRegistry.git")   # once
register(MyPkg; registry = "MyRegistry")                             # each release, clean checkout
# consumers, once: ]registry add git@github.com:me/MyRegistry.git
```

## 10. Latency and apps

```julia
module MyPkg
using PrecompileTools: @setup_workload, @compile_workload
# ... package code ...
@setup_workload begin
    data = rand(100)                  # runs during precompilation, not cached itself
    @compile_workload begin
        r = fit(data)                 # everything called here is cached in the package image
        summarize(r)
    end
end
end
```

Measure in fresh processes: `julia --project -e '@time using MyPkg; @time MyPkg.fit(rand(100))'`.
A first call of 1 s or more that takes milliseconds the second time is compilation, which a
workload fixes. Keep workloads free of I/O, network and global state.

```julia
using SnoopCompileCore
invs = @snoop_invalidations using MyPkg      # methods compiled earlier and discarded by new loads
using SnoopCompile
trees = invalidation_trees(invs)              # worst last; fix by tightening signatures, removing piracy
```

```julia
module MyApp
function (@main)(args)                        # 1.11+: entry point, returns the exit code
    println("hello ", join(args, " "))
    return 0
end
end
```

| Route | Command | Notes |
|---|---|---|
| run from source | `julia --project -m MyApp args...` | recent Julia (check `julia --help` for `-m`) |
| JuliaC.jl (1.12+, experimental) | `juliac --output-exe myapp --bundle build --trim=safe --experimental .` | small binary in `build/bin`; `--trim=safe` errors on dynamic dispatch reachable from `@main`; install with `Pkg.Apps.add("JuliaC")`, `~/.julia/bin` on PATH |
| PackageCompiler.jl | `create_app("MyApp", "build/MyApp")` | relocatable bundle with full Julia; expects `julia_main()::Cint` |
| custom sysimage | `create_sysimage(["Plots"]; sysimage_path = "sys.so", precompile_execution_file = "warmup.jl")` | start with `julia -J sys.so` |

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| works locally, "Package Foo not found" in CI | Foo installed in the default env, missing from Project.toml | add it; test in CI or `Pkg.test()` only |
| AutoMerge blocks the release | missing compat entries or no upper bounds | complete `[compat]` |
| users hit "Unsatisfiable requirements" | bounds too tight, CompatHelper PRs left open | test and widen |
| users install test frameworks | test packages in `[deps]` | `test/Project.toml` |
| extension never loads | trigger missing from `[weakdeps]`, or key, file and module names differ | make all three identical |
| absolute path in a committed manifest | `Pkg.develop` of a local path | relative path or `[sources]` |
| Aqua piracy failure | Base methods on types you do not own | wrap the type; `treat_as_own` only when justified |
| JET errors after a Julia upgrade | JET tracks compiler internals | version gate |
| precompilation slow or failing | I/O or randomness in the workload | small pure workload |
| `using MyPkg` slow without heavy deps | work in `__init__`, invalidations | lazy init, fix invalidation trees |
| Registrator rejects the version | version not bumped | bump in Project.toml |

## 12. Worked example: scaffold, extension, gates, CI, registration

1. Scaffold (PkgTemplates; the `aqua`/`jet` flags exist in recent releases, otherwise add the
   section 7 file by hand):

```julia
using PkgTemplates
t = Template(; user = "me", julia = v"1.10",
    plugins = [Git(; manifest = false), GitHubActions(), Codecov(),
               Documenter{GitHubActions}(), Tests(; project = true, aqua = true, jet = true)])
t("CurveFits")                      # created under Pkg.devdir() unless dir = ... is given
```

2. Code with an extension point (`export` rather than `public`, because the minimum is 1.10):

```julia
module CurveFits
export FitResult, fit_line, plotfit
struct FitResult{T<:AbstractFloat}
    x::Vector{T}; yhat::Vector{T}; slope::T; intercept::T
end
function fit_line(x::AbstractVector{T}, y::AbstractVector{T}) where {T<:AbstractFloat}
    X = [ones(T, length(x)) x]
    b, m = X \ y
    return FitResult(collect(x), X * [b, m], m, b)
end
"Plot the fitted line. Available after `using Plots`."
function plotfit end
end
```

   Add Plots as a weak dependency with the `[weakdeps]`/`[extensions]`/`[compat]` block of
   section 4 (`CurveFitsPlotsExt = "Plots"`) and `ext/CurveFitsPlotsExt.jl` defining
   `CurveFits.plotfit(r::CurveFits.FitResult; kw...) = plot(r.x, r.yhat; label = "fit", kw...)`.

3. Tests: `test/Project.toml` lists Aqua, ExplicitImports, JET, Plots, Test.

```julia
# test/runtests.jl
using CurveFits, Test
@test Base.get_extension(CurveFits, :CurveFitsPlotsExt) === nothing   # Plots not loaded yet
using Plots
@testset "CurveFits" begin
    r = fit_line([0.0, 1.0, 2.0], [1.0, 3.0, 5.0])
    @test r.slope ≈ 2 && r.intercept ≈ 1
    @test Base.get_extension(CurveFits, :CurveFitsPlotsExt) !== nothing
    @test plotfit(r) isa Plots.Plot
end
include("qa.jl")                      # section 7
```

4. CI: replace the generated matrix with section 8 (`lts`, `1`, `pre`), push, and wait for green
   on all three plus the docs job.
5. Release: set `version = "0.1.0"`, merge, comment `@JuliaRegistrator register`, wait out the
   three-day new-package period, and confirm that TagBot created `v0.1.0` and that the docs
   deployed from the tag.

Acceptance: `Pkg.test()` green on every matrix entry; Aqua and ExplicitImports clean; JET clean
on its gated version; `@time using CurveFits` does not load Plots (first test line).

Related: `julia-type-stability`, `julia-performance-allocations`, `julia-gpu`, `julia-ml-flux-lux`, hub `julia-craft`
