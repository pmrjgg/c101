# Compile latency (TTFX), sysimages and trimmed binaries

## 1. Measure first

```julia
@time_imports using MyPkg          # per-dependency load time, including __init__ (1.10+ shows __init__)
@time using MyPkg                  # total load
@time MyPkg.run(small_input)       # first call: note "% compilation time" and "recompilation"
@time MyPkg.run(small_input)       # second call: steady state
```

```bash
julia --project --trace-compile=stderr --trace-compile-timing -e 'using MyPkg; MyPkg.run(input)'
```

Each `precompile(...)` line is a method compiled at runtime (with its time in ms). Recompiled
methods are printed in yellow, or with a trailing comment when colour is unavailable; those
indicate invalidations. 1.12+ has the in-session forms `@trace_compile expr` and
`@trace_dispatch expr` (InteractiveUtils).

| Observation | Next step |
|---|---|
| one dependency dominates `@time_imports` | check its version, its own workload, or load it lazily via a package extension |
| many `precompile(...)` lines from your package on first call | add a PrecompileTools workload |
| recompiled (yellow / commented) lines | find invalidations with SnoopCompile |
| long `% compilation time` despite a workload | inference triggers: `@snoop_inference` |
| startup of a deployed application | sysimage or `juliac` |

## 2. PrecompileTools workload

```julia
module MyPkg
using PrecompileTools: @setup_workload, @compile_workload

# ... package code ...

@setup_workload begin
    xs = rand(100)                         # setup code: runs, not forced to compile
    cfg = default_config()
    @compile_workload begin
        res = run_model(xs, cfg)           # these calls and all their callees get cached
        show(devnull, MIME"text/plain"(), res)
    end
end
end
```

- Place the block at top level of the module, after the definitions it calls.
- Use a small but representative workload covering the concrete types users will pass.
- Native code is cached in package images from Julia 1.9 on, so the first call afterwards is
  fast (provided nothing invalidates it).
- Developers can skip workloads while iterating:
  `using Preferences; set_preferences!(MyPkg, "precompile_workload" => false; force=true)`
  (restart; one-time recompilation of dependents). The PrecompileTools docs give the global
  switch as `set_preferences!(PrecompileTools, "precompile_workloads" => false; force=true)`;
  note the singular/plural key difference.

## 3. Invalidations (SnoopCompile 3)

```julia
using SnoopCompileCore                       # load first, alone: it must not invalidate anything
invs = @snoop_invalidations using MyPkg, OtherDep;
using SnoopCompile, AbstractTrees
trees = invalidation_trees(invs)             # one tree per cause (a newly added method)
tree = trees[end]
sig, victim = tree.mt_backedges[end]          # a call site inferred on Any that the new method hijacked
print_tree(victim)                            # everything that had to be recompiled
```

Fixes, in order: make the victim's call site inferable (it called a function on an `Any`
argument), avoid defining methods on Base functions for broad types (`Base.convert(::Type{Any}, ...)`,
piracy), and load packages that add such methods early. SnoopCompile 3 renamed `@snoopr` to
`@snoop_invalidations`, `@snoopi_deep` to `@snoop_inference` and `@snoopl` to `@snoop_llvm`.
The current 3.2.x line declares `julia = "1.12"`; on older Julia let Pkg pick a compatible
release and check which macro names it exports. Interactive tracing of victims with Cthulhu's
`ascend` is for humans.

Inference profiling:

```julia
using SnoopCompileCore
tinf = @snoop_inference MyPkg.run(input);    # keep the semicolon: the result is huge
using SnoopCompile
staleinstances(tinf)                          # check first: stale cache entries
itrigs = inference_triggers(tinf)             # runtime-dispatch points that triggered fresh inference
mtrigs = accumulate_by_source(Method, itrigs)
```

## 4. PackageCompiler

```julia
using PackageCompiler
create_sysimage(["MyPkg"]; sysimage_path = "sys_mypkg.so",
                precompile_execution_file = "warmup.jl")        # warmup.jl exercises typical calls
```

Start with `julia -Jsys_mypkg.so` (or `--sysimage=sys_mypkg.so`). The sysimage freezes package
versions: rebuild after every dependency update, never commit it.

Relocatable application: `create_app("MyApp", "MyAppCompiled")`, where the package defines
`function julia_main()::Cint` (returns an exit code; read arguments from `ARGS`).

## 5. `juliac` and `--trim` (Julia 1.12+, experimental)

```bash
# install the app shim once (Pkg apps), then make sure ~/.julia/bin is on PATH
julia -e 'using Pkg; Pkg.Apps.add(Pkg.PackageSpec(name = "JuliaC"))'   # REPL form: pkg> app add JuliaC
juliac --output-exe myapp --bundle build --trim=safe --experimental path/to/AppProject
```

- Entry point: `function @main(args::Vector{String})` in the package or script (the
  `function @main(args)` form without parentheses needs 1.12+).
- `--bundle <dir>` copies the needed Julia libraries and artifacts next to the executable.
- `--trim` modes (`julia --help-hidden`): `safe` reports unresolvable dynamic call sites as
  compile-time errors; `unsafe` may produce a binary missing code; `unsafe-warn` warns per
  dynamic call site. In practice the whole reachable program must be type-stable: run JET
  `@report_opt` on the entry point before building.
- `--trim` requires `--experimental` on some builds; check the JuliaC README for the installed
  version before scripting it.
- Without installing the app: `julia --project -e "using JuliaC; JuliaC.main(ARGS)" -- <args>`.

## 6. Day-to-day latency hygiene

- Keep the default `@v1.x` environment small (Revise, BenchmarkTools, JET-in-temp-env); every
  extra package there competes for invalidations.
- Use Revise so method edits do not require restarting and recompiling everything.
- Optional heavy integrations go in package extensions (`[weakdeps]` + `[extensions]`), loaded
  only when the user loads the trigger package.
