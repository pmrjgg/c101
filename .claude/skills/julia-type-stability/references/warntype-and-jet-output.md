# Reading inference output: @code_warntype, JET, @trace_dispatch

All outputs below were captured on Julia 1.13.2 (aarch64, Apple M3 Ultra) from the worked example
in the skill. SSA numbers (`%25`) depend on the exact source; the shapes do not.

## 1. Unstable: `advance!` with non-const globals `dt`, `g`

Call: `code_warntype(stdout, advance!, (Vector{Float64}, Vector{Float64}, Int))` (plain text, no
colour, so warnings are UPPERCASE).

```
MethodInstance for advance!(::Vector{Float64}, ::Vector{Float64}, ::Int64)
Arguments
  #self#::Core.Const(Main.advance!)
  pos::Vector{Float64}
  vel::Vector{Float64}
  nsteps::Int64
Locals
  @_5::UNION{NOTHING, TUPLE{INT64, INT64}}      <- iterate protocol: yellow, benign
  @_6::UNION{NOTHING, TUPLE{INT64, INT64}}      <- same
  i::Int64
Body::Vector{Float64}                            <- concrete return; NOT proof of stability
...
│   %23 = Base.getindex(vel, %22)::Float64
│   %24 = Main.:*::Core.Const(*)
│   %25 = Main.g::ANY                            <- non-const global read: red
│   %26 = Main.dt::ANY                           <- non-const global read: red
│   %27 = (%24)(%25, %26)::ANY                   <- g * dt dispatched at runtime, result boxed
│   %28 = (%21)(%23, %27)::ANY                   <- vel[i] + (...) dispatched at runtime
│         Base.setindex!(vel, %28, %29)          <- converts Any -> Float64 on every store
...
│   %37 = Main.dt::ANY
│   %38 = (%34)(%36, %37)::ANY
│   %39 = (%31)(%33, %38)::ANY
```

Reading order:

1. `Arguments`: concrete? If not, the caller is the problem (fix upstream or add a barrier).
2. `Locals`: any red entry, `Core.Box`, or a `Union` of unrelated types.
3. `Body::T`: return type. Concrete is necessary, not sufficient.
4. Body lines: scan the `::TYPE` suffix of every SSA value. The first red value is the root
   cause; everything that consumes it turns red as well.

Common line shapes:

| Line | Meaning |
|---|---|
| `Main.x::ANY` | read of a non-const global |
| `Base.getfield(p, :x)::REAL` | abstract field type |
| `Base.getindex(v, i)::ANY` | abstract element type (`Vector{Any}`, `Dict{String,Any}`) |
| `s::UNION{FLOAT64, INT64}` | variable changes type |
| `#1::var"#f##0#f##1"` with `Core.Box` fields | closure capturing a reassigned variable |
| `Core.Const(...)`, `Core.PartialStruct(...)` | constant-propagated values: good |
| `$(Expr(:static_parameter, 1))::Core.Const(Float64)` | type parameter `T` known at compile time: good |

## 2. Stable: `advance_kernel!`

```
MethodInstance for advance_kernel!(::Vector{Float64}, ::Vector{Float64}, ::Int64)
Static Parameters
  T = Float64
Arguments
  pos::Vector{Float64}
  vel::Vector{Float64}
  nsteps::Int64
Body::Vector{Float64}
1 ─ %1 = $(Expr(:static_parameter, 1))::Core.Const(Float64)
│   %2 = Main.DT::Core.Const(0.01)              <- const global: folded to a constant
│   %3 = (%1)(%2)::Core.Const(0.01)
│   %4 = (#self#)(pos, vel, nsteps, %3)::Vector{Float64}
└──      return %4
```

The 3-argument method only forwards defaults; inspect the full method with
`code_warntype(advance_kernel!, (Vector{Float64}, Vector{Float64}, Int, Float64, Float64))`.

## 3. A closure that boxes

```julia
function boxy(xs)
    s = 0.0
    foreach(x -> (s += x), xs)     # s is captured AND reassigned
    return s
end
```

`occursin("Core.Box", sprint(io -> code_warntype(io, boxy, (Vector{Float64},))))` is `true` on 1.13;
the local itself prints as `s@_4::CORE.BOX` in plain text. Fixes: `sum(xs)`; `foldl(+, xs; init=0.0)`; a typed `Ref`: `s = Ref(0.0); foreach(x -> (s[] += x), xs); s[]`.

## 4. JET report shape

```julia
using JET
@report_opt advance!(rand(4), zeros(4), 1)
```

JET prints a header such as `═════ N possible errors found ═════`, then for each site a call
tree (`┌ advance!(...) @ Main file.jl:7` ...) ending in a line of the form
`runtime dispatch detected: <callee>(<arg types>)::<inferred type>` (the JET docs show
`runtime dispatch detected: fill_twos!(a::Vector)::Any`). One entry per dynamic call site, so
the global example yields one entry per `*` / `+` on an `Any` value.

Filtering:

| Keyword | Effect |
|---|---|
| `target_modules=(MyPkg,)` | keep only reports whose site is inside these modules (and submodules) |
| `ignored_modules=(Base,)` | drop reports from these modules |
| `function_filter = f -> f !== somefunc` | skip analysis of selected callees |
| `skip_noncompileable_calls=false` | also analyse calls Julia would not compile for the inferred signature |

Version coupling: JET 0.12 has full functionality on Julia 1.12 and 1.13. On other versions it
may install but loads stubs; `JET.JET_AVAILABLE` is `false` and analysis functions throw.
Setting the `JET_DEV_MODE` preference forces loading on unsupported versions (expect breakage).

## 5. `@trace_dispatch` (Julia 1.12+)

```julia
using InteractiveUtils
dt = 0.01
function g(v)
    s = 0.0
    for x in v
        s += x * dt
    end
    s
end
@trace_dispatch g(rand(10))
```

Output on a cold 1.13 session includes compiler-internal noise and, among it, the hot-path
dispatches of interest:

```
precompile(Tuple{typeof(Main.g), Array{Float64, 1}})          <- the top-level call itself
precompile(Tuple{typeof(Base.:(*)), Float64, Float64})        <- x * dt dispatched at runtime
precompile(Tuple{typeof(Base.:(+)), Float64, Float64})        <- s += ... dispatched at runtime
```

Each signature is printed the first time it is dispatched dynamically; a second traced call of
the same code prints nothing new. The command-line form `julia --trace-dispatch=stderr script.jl`
traces a whole run. Arithmetic on `Float64` appearing here is a reliable instability marker.

## 6. Profile and IR markers

- `Profile.print(format=:flat, sortedby=:count, C=true)` on the unstable loop shows
  `ijl_apply_generic` among the top frames (runtime dispatch entry point).
- `@code_llvm debuginfo=:none` of the unstable loop contains calls to `ijl_apply_generic` and to
  binding lookups (`jl_get_binding...`, `get_binding_value`); an allocating broadcast shows
  `ijl_gc_small_alloc` and `jl_alloc_genericmemory_unchecked` on 1.13.

## 7. Cthulhu (humans at a terminal)

`using Cthulhu; @descend f(x)` opens an interactive tree of callees with type annotations.
`@descend f(::Int)` (type-annotation form) works on Julia 1.13+. Keys toggle views such as
optimized vs unoptimized code and warning colouring (`o`, `w`). Cthulhu 3 requires Julia 1.12;
the `2.16` branch serves 1.10/1.11. Agents cannot drive the TUI: use JET and `@code_warntype`.
