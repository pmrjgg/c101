---
name: julia-ml-flux-lux
description: "Deep learning in Julia with Lux.jl (explicit parameters and state) and Flux.jl: model definition, Optimisers.jl, Zygote and Enzyme AD, MLUtils data loading, GPU via CUDA.jl/Metal.jl and MLDataDevices, training loops, type stability, neural ODEs with SciML. Load when building, training or debugging ML models in Julia."
when_to_use: "Defining or training neural networks with Lux.jl or Flux.jl; Zygote errors such as 'Mutating arrays is not supported' or 'try/catch is not supported'; choosing Zygote, Enzyme or Reactant; moving models and batches to CUDA or Metal with gpu_device; loss that stays flat or turns NaN; saving and resuming JLD2 checkpoints; neural ODEs with DiffEqFlux and SciMLSensitivity."
---

# Julia deep learning with Lux and Flux

Both libraries share the building blocks (NNlib kernels, Optimisers.jl, MLUtils, Zygote or
Enzyme for gradients, MLDataDevices for device movement). They differ in where parameters live:
Lux passes them explicitly as NamedTuples, Flux stores them inside the layer structs.

Baseline: Lux 1.x, Flux 0.15/0.16, Optimisers 0.4, Zygote 0.7, Enzyme 0.13, MLDataDevices 1.x.
These move fast: names marked "version-dependent" below must be checked against the installed
docs before use.

## 1. Choosing Lux vs Flux

| Criterion | Lux | Flux |
|---|---|---|
| parameters | explicit `ps`/`st` NamedTuples, model struct is immutable | stored in layers |
| call | pure `model(x, ps, st) -> (y, st)` | `model(x)`; `trainmode!`/`testmode!` mutate |
| SciML (neural ODEs, PINNs, ComponentArrays) | first-class | works, less idiomatic |
| compilation | Reactant (XLA) and Enzyme paths | Zygote-centred, Enzyme supported |
| ecosystem and tutorials | growing | larger and older (Metalhead, model zoo) |

Pick Lux for new SciML or research code and anything that will be compiled with Reactant; keep
Flux for existing Flux codebases and conventional vision or NLP models built on Flux packages.
Do not mix layers from both libraries in one model; Lux can wrap a Flux model through its Flux
adaptor (`FromFluxAdaptor`, version-dependent) when migrating.

## 2. Model definition

```julia
using Lux                                   # Lux version
lux_cnn = Chain(
    Conv((3, 3), 1 => 16, relu; pad = 1), MaxPool((2, 2)),
    Conv((3, 3), 16 => 32, relu; pad = 1), MaxPool((2, 2)),
    FlattenLayer(), Dense(7 * 7 * 32 => 128, relu), Dropout(0.1f0), Dense(128 => 10))

using Flux                                  # Flux version: same shapes
flux_cnn = Chain(
    Conv((3, 3), 1 => 16, relu; pad = 1), MaxPool((2, 2)),
    Conv((3, 3), 16 => 32, relu; pad = 1), MaxPool((2, 2)),
    x -> reshape(x, :, size(x, 4)), Dense(7 * 7 * 32 => 128, relu), Dropout(0.1), Dense(128 => 10))
```

Data layout: features first, batch last: `(features, batch)` for `Dense`, `(W, H, C, N)` for 2D
convolutions. The `7 * 7 * 32` assumes 28x28 inputs halved twice.

Custom layers:

```julia
# Lux: declare parameters and state; the call threads state through
struct Affine{F} <: Lux.AbstractLuxLayer
    in::Int; out::Int; init::F
end
Affine(in::Int, out::Int; init = glorot_uniform) = Affine(in, out, init)
Lux.initialparameters(rng::AbstractRNG, l::Affine) = (W = l.init(rng, l.out, l.in), b = zeros(Float32, l.out))
Lux.initialstates(::AbstractRNG, ::Affine) = NamedTuple()
(l::Affine)(x::AbstractMatrix, ps, st) = (ps.W * x .+ ps.b, st)

# Lux shortcut for one-off blocks
block = @compact(d1 = Dense(2 => 16, tanh), d2 = Dense(16 => 2)) do x
    @return d2(d1(x)) .+ x                       # residual connection
end

# Flux: fields are the parameters; @layer registers the struct with Functors/Optimisers
struct FAffine{M<:AbstractMatrix, V<:AbstractVector}
    W::M; b::V
end
FAffine(in::Int, out::Int) = FAffine(Flux.glorot_uniform(out, in), zeros(Float32, out))
(m::FAffine)(x) = m.W * x .+ m.b
Flux.@layer FAffine
```

## 3. Parameters and state in Lux

```julia
using Lux, Random
rng = Xoshiro(0)
ps, st = Lux.setup(rng, model)       # NamedTuples mirroring the layer tree: ps.layer_1.weight
y, st = model(x, ps, st)             # same as Lux.apply(model, x, ps, st); always rebind st
st_eval = Lux.testmode(st)           # Dropout off, BatchNorm uses running statistics
Lux.parameterlength(model), Lux.statelength(model)
smodel = StatefulLuxLayer{true}(model, ps, st)   # closes over ps/st: smodel(x) returns y only
```

- `ps` holds trainable arrays, `st` everything else (BatchNorm running stats, dropout RNG,
  `training` flags). Forgetting to thread the returned `st` freezes BatchNorm statistics and
  reuses one dropout mask.
- Parameters are immutable values: optimizers return new `ps` (section 4).
- Flatten for SciML or Optimization.jl with `ComponentArray(ps)` (ComponentArrays.jl).

## 4. Optimisers.jl

```julia
using Optimisers
opt = OptimiserChain(ClipNorm(1f0), AdamW(1f-3, (0.9f0, 0.999f0), 1f-4))   # eta, betas, weight decay
opt_state = Optimisers.setup(opt, ps)            # Flux: Flux.setup(opt, model)
opt_state, ps = Optimisers.update!(opt_state, ps, grads)   # always rebind both results
Optimisers.adjust!(opt_state, 1f-4)              # change the learning rate everywhere
Optimisers.freeze!(opt_state.layer_1)            # stop updating a subtree; thaw! to resume
```

- `ClipNorm(ω)` clips each array's norm separately, not the global norm; `ClipGrad(δ)` clamps
  elementwise. For a global-norm clip, scale the whole gradient tree yourself.
- AdamW weight-decay semantics changed in Optimisers 0.4 (decay coupled to the learning rate by
  default); check the docstring when porting hyperparameters from PyTorch.
- Schedules: compute the rate per epoch and call `adjust!`, e.g. cosine decay
  `lr(e) = lr_min + (lr0 - lr_min) * (1 + cos(Float32(π) * (e - 1) / E)) / 2`; ParameterSchedulers.jl
  provides ready-made schedules.

## 5. AD backends

| Backend | How | Strengths | Limits |
|---|---|---|---|
| Zygote | `AutoZygote()` (Lux), `Flux.withgradient` | default, broad coverage via ChainRules | no array mutation, no try/catch, slow scalar loops |
| Enzyme | `AutoEnzyme()` (Lux); Flux accepts Enzyme `Duplicated` models (Flux 0.15+, version-dependent) | mutation-friendly, fast loops, needed for Reactant | needs type-stable code, long first compile, tight Julia-version coupling |
| ForwardDiff | `AutoForwardDiff()` | under ~100 parameters, nested derivatives | cost grows with parameter count |
| Mooncake | `AutoMooncake()` where supported | reverse mode on mutating code | newer: check backend support |

| Failure | Cause | Fix |
|---|---|---|
| `Mutating arrays is not supported -- called setindex!` | in-place writes in the loss or model | rewrite with `map`/broadcast/`vcat`, use `Zygote.Buffer`, or switch to Enzyme |
| `try/catch is not supported` | exception handling on the differentiated path | move it out, or wrap in `ChainRulesCore.@ignore_derivatives` |
| gradient is `nothing` | parameter unused, or differentiating the wrong argument | check the closure uses `ps`/the model argument |
| `Can't differentiate foreigncall expression` | `ccall` or low-level code in the path | `@ignore_derivatives` or a custom `rrule` |
| NaN loss or gradients | `log(0)`, softmax then crossentropy, exploding activations | logit losses, clipping, lower learning rate |
| Enzyme runtime-activity or type errors | instability in the model or loss | fix stability; runtime-activity mode (`Enzyme.set_runtime_activity(Reverse)`) as a last resort |

Custom gradient for a function AD cannot handle:

```julia
using ChainRulesCore
mysquare(x) = x .^ 2
function ChainRulesCore.rrule(::typeof(mysquare), x)
    pullback(ȳ) = (NoTangent(), 2 .* x .* unthunk(ȳ))
    return mysquare(x), pullback
end
```

## 6. Data

```julia
using MLUtils, OneHotArrays
X = rand(Float32, 28, 28, 1, 60_000); labels = rand(0:9, 60_000)
Y = onehotbatch(labels, 0:9)
(Xtr, Ytr), (Xva, Yva) = splitobs((X, Y); at = 0.9, shuffle = true)
train_loader = DataLoader((Xtr, Ytr); batchsize = 128, shuffle = true, partial = false)
val_loader = DataLoader((Xva, Yva); batchsize = 512)
gdev, cdev = gpu_device(), cpu_device()
for (x, y) in gdev(train_loader)     # moves each batch to the device as it is consumed
    # ...
end
```

- Observations along the last dimension; `Float32` arrays (`Float32.(X)` once, not per batch).
- `partial = false` drops the ragged last batch (stable shapes, fewer recompilations).
- `DataLoader(...; parallel = true)` loads batches on threads when loading is the bottleneck.
- Keep the full dataset on the host and move batches; move it whole only when it fits on the
  device with room for activations.

## 7. GPU

```julia
using CUDA, cuDNN            # NVIDIA (LuxCUDA bundles both); `using Metal` on Apple silicon
gdev = gpu_device()          # CUDADevice, MetalDevice, ...; warns and falls back to CPU if none
ps, st = (ps, st) |> gdev    # model structs stay on the host in Lux; Flux: model = gdev(model)
CUDA.allowscalar(false)      # turn silent scalar fallbacks into errors
```

- Pass `force = true` to `gpu_device` to error instead of falling back (keyword name is
  version-dependent).
- Metal: Float32 only, and some NNlib kernels are missing or slow; test each layer type first.
- `Scalar indexing is disallowed` usually comes from metrics: compute `onecold` and accuracy on
  `cdev(ŷ)`, or with broadcasts.
- Memory: lower `batchsize` first; `CUDA.memory_status()`; `GC.gc(); CUDA.reclaim()` between
  epochs when fragmentation causes out-of-memory. See `julia-gpu` for kernels and profiling.

## 8. Training loop patterns and the Lux Training API

```julia
using Lux, Optimisers, Zygote
lossfn = CrossEntropyLoss(; logits = Val(true))
ts = Training.TrainState(model, ps, st, Adam(1f-3))
for epoch in 1:nepochs
    for (x, y) in gdev(train_loader)
        _, loss, _, ts = Training.single_train_step!(AutoZygote(), lossfn, (x, y), ts)
    end
    acc = accuracy(model, ts.parameters, Lux.testmode(ts.states), gdev(val_loader))
    @info "epoch" epoch loss acc
end
```

- A custom objective has the signature `(model, ps, st, data) -> (loss, st, stats)`.
- `ts.parameters`, `ts.states` and `ts.optimizer_state` hold the current values.
- Manual Lux loop (full control, e.g. gradient accumulation):
  `(l, st), back = Zygote.pullback(p -> lossfn_state(p, st, x, y), ps)`, then
  `gs = back((one(l), nothing))[1]` and `opt_state, ps = Optimisers.update!(opt_state, ps, gs)`.
- Flux loop: `loss, grads = Flux.withgradient(m -> Flux.logitcrossentropy(m(x), y), model)`,
  then `Flux.update!(opt_state, model, grads[1])`; `Flux.trainmode!`/`Flux.testmode!` around
  training and evaluation.
- Logging: per-step loss as a running mean, validation metrics per epoch; first epoch includes
  compilation, so compare timings from epoch two.

Checkpointing (always move to the CPU first):

```julia
using JLD2
jldsave("ckpt_$epoch.jld2"; ps = cdev(ts.parameters), st = cdev(ts.states),
        opt_state = cdev(ts.optimizer_state), epoch)
ck = JLD2.load("ckpt_10.jld2")              # Dict with "ps", "st", "opt_state", "epoch"
# Flux: jldsave("m.jld2"; model_state = Flux.state(cpu_device()(model)))
#       Flux.loadmodel!(model, JLD2.load("m.jld2", "model_state"))
```

Resuming with the optimizer state is simplest in a manual loop (pass the loaded `opt_state` to
`Optimisers.update!`); a fresh `TrainState` restarts the optimizer moments.

## 9. Performance

- `@code_warntype model(x, ps, st)` and on the loss: Lux layers are type stable for concrete
  inputs; instability usually comes from user closures, non-const globals or `Any` containers.
- `Float32` end to end: one Float64 input or literal promotes whole matmuls (LuxLib may warn
  about mixed precision).
- Benchmark a single step: `@btime CUDA.@sync train_step!(...)` after warm-up; check data
  loading separately (GPU utilisation below ~70% in `nvidia-smi` means the loader starves it).
- Reactant (optional, version-dependent): `rdev = reactant_device()`, move `ps`, `st` and data
  with `rdev`, and the Lux training API compiles the whole step through XLA when used with
  `AutoEnzyme()`; worthwhile for large models, but it supports a subset of Julia: follow the
  current Lux docs.

## 10. Neural ODEs with DiffEqFlux and SciMLSensitivity

```julia
using Lux, DiffEqFlux, OrdinaryDiffEq, SciMLSensitivity, ComponentArrays
using Optimization, OptimizationOptimisers, Zygote, Random
rng = Xoshiro(0)
u0 = Float32[2.0, 0.0]; tspan = (0.0f0, 1.5f0)
tsteps = range(tspan[1], tspan[2]; length = 30)
dudt = Chain(x -> x .^ 3, Dense(2 => 50, tanh), Dense(50 => 2))   # functions are wrapped as layers
node = NeuralODE(dudt, tspan, Tsit5(); saveat = tsteps)
ps, st = Lux.setup(rng, node)
ps = ComponentArray(ps)
predict(p) = Array(first(node(u0, p, st)))     # node returns (solution, state)
loss(p, _) = sum(abs2, predict(p) .- target)   # target: 2×30 Float32 observations at tsteps
optf = OptimizationFunction(loss, Optimization.AutoZygote())
res = solve(OptimizationProblem(optf, ps), OptimizationOptimisers.Adam(0.05f0); maxiters = 300)
```

- Sensitivity algorithm: the default choice is usually right; for many parameters on stiff or
  long problems pass `sensealg = InterpolatingAdjoint(; autojacvec = ZygoteVJP())` (or
  `GaussAdjoint`) to `NeuralODE`; under ~100 parameters `ForwardDiffSensitivity()` is often fastest.
- Long series: train on growing time windows or multiple shooting; finish with
  `OptimizationOptimJL.BFGS()` after Adam has found the basin.
- Solver choice and stiffness: see `julia-sciml-diffeq`.

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| slow training, LuxLib mixed-precision warning | Float64 data or literals | `Float32` everywhere |
| validation metrics noisy or poor | evaluating with training-mode state | `Lux.testmode(st)`; Flux `testmode!` |
| BatchNorm statistics never change | returned `st` dropped | rebind `st` every call |
| no learning, loss flat | `update!` results not rebound, learning rate off by 10x, labels misaligned | rebind; LR sweep 1e-4..1e-2; check `size(y)` |
| NaN after a few steps | softmax + crossentropy, `log(0)`, exploding gradients | logit losses, `ClipNorm`, lower LR |
| "Scalar indexing is disallowed" | metrics or indexing on device arrays | compute on `cdev(ŷ)` or broadcast |
| model and data on different devices | one side not moved | move `ps`, `st` and batches with the same device |
| Zygote mutation or try/catch errors | in-place code in the loss | section 5 table |
| checkpoint unreadable on another machine | GPU arrays saved | `cdev` before `jldsave` |
| first epoch 10x slower | compilation | time from epoch two |

## 12. Worked example: an MLP classifier trained on GPU with Lux and Optimisers

Three noisy concentric rings in 2D, three classes:

```julia
using Lux, Optimisers, Zygote, MLUtils, OneHotArrays, JLD2, Random, Printf
using CUDA, cuDNN                  # or `using Metal`; omit both to train on the CPU

function rings(rng, n_per_class)
    X = Matrix{Float32}(undef, 2, 3n_per_class); labels = Vector{Int}(undef, 3n_per_class)
    for c in 0:2, k in 1:n_per_class
        i = c * n_per_class + k
        r, θ = 1f0 + c + 0.15f0 * randn(rng, Float32), 2f0 * π * rand(rng, Float32)
        X[1, i], X[2, i] = r * cos(θ), r * sin(θ)
        labels[i] = c
    end
    return X, onehotbatch(labels, 0:2)
end

function accuracy(model, ps, st, loader)
    cdev = cpu_device(); hits = 0; total = 0
    for (x, y) in loader
        ŷ, _ = model(x, ps, st)
        hits += sum(onecold(cdev(ŷ)) .== onecold(cdev(y)))     # metrics on the host
        total += size(y, 2)
    end
    return hits / total
end

rng = Xoshiro(42)
X, Y = rings(rng, 2_000)
(Xtr, Ytr), (Xva, Yva) = splitobs((X, Y); at = 0.8, shuffle = true)
gdev, cdev = gpu_device(), cpu_device()
train_loader = gdev(DataLoader((Xtr, Ytr); batchsize = 256, shuffle = true, partial = false))
val_loader = gdev(DataLoader((Xva, Yva); batchsize = 1024))

model = Chain(Dense(2 => 64, relu), Dense(64 => 64, relu), Dense(64 => 3))
ps, st = Lux.setup(rng, model) |> gdev
opt = OptimiserChain(ClipNorm(1f0), AdamW(3f-3, (0.9f0, 0.999f0), 1f-4))
ts = Training.TrainState(model, ps, st, opt)
lossfn = CrossEntropyLoss(; logits = Val(true))

for epoch in 1:50
    total = 0f0; nb = 0
    for (x, y) in train_loader
        _, loss, _, ts = Training.single_train_step!(AutoZygote(), lossfn, (x, y), ts)
        total += loss; nb += 1
    end
    if epoch % 10 == 0
        acc = accuracy(model, ts.parameters, Lux.testmode(ts.states), val_loader)
        @printf "epoch %2d  train_loss %.4f  val_acc %.3f\n" epoch total / nb acc
        jldsave("ckpt_$epoch.jld2"; ps = cdev(ts.parameters), st = cdev(ts.states), epoch)
    end
end
```

Checks, in order:
1. Device: `ts.parameters.layer_1.weight isa CuArray` (or `MtlArray`); if `gpu_device()` warned
   and fell back, fix the GPU setup before tuning anything.
2. Learning: training loss falls steadily over the first ten epochs; flat loss means the section
   11 "no learning" row.
3. Target: validation accuracy of at least 0.95 by epoch 50 (the rings are nearly separable for
   a two-hidden-layer MLP; below that, check labels with `onecold(Y[:, 1:5])` and the LR).
4. Portability: reload `ps`/`st` from `ckpt_50.jld2` on the CPU and recompute accuracy with
   CPU loaders; it must match the GPU figure to about 1e-3.

Related: `julia-gpu`, `julia-sciml-diffeq`, `julia-type-stability`, `julia-performance-allocations`, hub `julia-craft`
