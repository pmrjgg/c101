---
name: cudaq-gpu-kernels
description: "NVIDIA CUDA-Q: kernels in Python (@cudaq.kernel) and C++ (__qpu__), sample/observe/get_state, spin operators, targets (nvidia, nvidia-mgpu, nvidia-mqpu, tensornet, density-matrix-cpu, hardware backends), async and multi-QPU batching, noise models, performance and memory limits. Load when writing CUDA-Q kernels or scaling circuit simulation on GPUs."
when_to_use: "Writing or debugging CUDA-Q kernels in Python or C++ (nvq++); choosing a CUDA-Q target or option (fp32/fp64, multi-GPU, multi-QPU, tensor network, density matrix); 'kernel fails to compile', 'out of GPU memory', 'results ordered differently from Qiskit'; batching observe/sample over parameters or GPUs with observe_async and qpu_id; noisy simulation with cudaq.NoiseModel; VQE loops with cudaq.optimizers or SciPy; preparing (not submitting) runs on hardware backends."
---

# CUDA-Q GPU kernels

CUDA-Q compiles typed quantum kernels and runs them on interchangeable targets: CPU and GPU
statevector, multi-GPU pooled memory, one virtual QPU per GPU, tensor networks, density matrices
and hardware. Pick the target from memory math, batch work across QPUs asynchronously, and check
conventions (bit order, exp_pauli sign) once per project. Facts marked verified were checked on
CUDA-Q 0.16 (CPU build); GPU targets exist only in CUDA-enabled Linux builds, so confirm them with
`cudaq.get_targets()` on the machine. Simulator choice beyond CUDA-Q: `quantum-circuit-simulators`.

## 1. Kernel model

```python
import cudaq

@cudaq.kernel
def ghz(n: int):
    q = cudaq.qvector(n)
    h(q[0])
    for i in range(n - 1):
        x.ctrl(q[i], q[i + 1])
    mz(q)

@cudaq.kernel
def ansatz(theta: float):              # every argument annotated: int, float, bool, list[float], cudaq.pauli_word, ...
    q = cudaq.qvector(4)
    x(q[0])
    x(q[1])
    exp_pauli(theta, q, "XXXY")
```

- Gates: `h x y z s t rx ry rz r1 u3 swap`, controlled `x.ctrl(c, t)`, adjoint `t.adj(q)`,
  measurement `mz mx my`, Pauli exponentials `exp_pauli(theta, qubits, word)`; kernels can call
  other kernels and use `cudaq.control` / `cudaq.adjoint`.
- Control flow: `for` over `range`, `if` on mid-circuit measurement results, kernel arguments.
- Restrictions: kernels are a statically compiled Python subset. No general Python objects,
  external libraries, exceptions or untyped containers inside; compute angles, Pauli words and
  coefficient lists outside and pass them in. Return values from per-shot execution go through
  `cudaq.run` in recent versions.
- C++: `__qpu__ void ghz(int n) { cudaq::qvector q(n); h(q[0]); for (int i = 0; i < n - 1; i++)
  x<cudaq::ctrl>(q[i], q[i + 1]); mz(q); }`, compiled with `nvq++ --target nvidia ghz.cpp -o ghz.x`.
- `cudaq.draw(kernel, *args)` prints the circuit; use it before debugging numbers.

## 2. Execution primitives

| Call | Returns | Key options (verified 0.16) |
|---|---|---|
| `cudaq.sample(kernel, *args)` | counts (`SampleResult`) | `shots_count=1000`, `noise_model=`, `explicit_measurements=` |
| `cudaq.observe(kernel, H, *args)` | `ObserveResult`, `.expectation()` | `shots_count=-1` (exact), `noise_model=`, `num_trajectories=`, `qpu_id=` |
| `cudaq.get_state(kernel, *args)` | `cudaq.State` (`np.array(state)`) | statevector or density matrix by target |
| `sample_async`, `observe_async`, `get_state_async` | futures, `.get()` | `qpu_id=` selects the virtual QPU |

Spin operators: `from cudaq import spin`; terms `spin.x(i)`, `spin.y(i)`, `spin.z(i)`, `spin.i(i)`,
combined with `*`, `+` and float coefficients. Passing lists or arrays of argument values
broadcasts `sample`/`observe` over parameter sets. CUDA-Q 0.16 warns that the `sample` and
`observe` primitives will change in a future release: pin the version and re-check on upgrade.

Bit order (verified): `sample` strings list qubit 0 first (X on qubit 0 of 3 → "100"), but
`get_state` amplitudes are indexed little-endian (the same state is index 1). Qiskit prints "001".

## 3. Targets and memory

| Target | Purpose |
|---|---|
| `qpp-cpu` | CPU statevector; default without a GPU (verified) |
| `density-matrix-cpu` | exact noisy simulation, small n (verified) |
| `stim` | Clifford circuits, QEC-scale sampling (verified) |
| `nvidia` | cuStateVec statevector on one GPU; `option="fp64"` for double precision |
| `nvidia` with `option="mgpu"` (also `nvidia-mgpu`) | one statevector pooled across GPUs/nodes via MPI |
| `nvidia` with `option="mqpu"` (also `nvidia-mqpu`, verified present) | one virtual QPU per GPU, fp32 by default; async batching |
| `tensornet`, `tensornet-mps` | cuTensorNet contraction / MPS for wide, shallow or low-entanglement circuits |
| hardware names | section 8 |

```python
cudaq.set_target("nvidia", option="fp64")      # check names with: [t.name for t in cudaq.get_targets()]
# command line alternative: python3 prog.py --target nvidia --target-option mgpu,fp64
```

Memory: statevector 8 · 2^n bytes (fp32) or 16 · 2^n (fp64), plus workspace. One 80 GB GPU holds
33 qubits in fp32 (64 GiB) and 32 in fp64; 2^k pooled GPUs add k qubits (8 × 80 GB: 36 in fp32,
35 in fp64). Size runs with ~20% headroom.

## 4. Multi-GPU and multi-QPU

- Pooling (`mgpu`): launch with MPI, `mpiexec -np 8 python3 prog.py --target nvidia --target-option mgpu`;
  in code `cudaq.mpi.initialize()`, `cudaq.mpi.rank()`, `cudaq.mpi.num_ranks()`, `cudaq.mpi.finalize()`.
  Use it when one statevector does not fit a single GPU; communication makes it slower per gate.
- Virtual QPUs (`mqpu`): many independent small circuits (parameter scans, gradients, Hamiltonian
  terms, shots of different circuits). `n = cudaq.get_target().num_qpus()`; submit with
  `observe_async(..., qpu_id=i % n)`, collect with `.get()`. Across nodes combine with MPI ranks.
- Rule: one big state → mgpu; many small states → mqpu; both are wasted on circuits that fit and
  finish in milliseconds on one device.

## 5. Tensor-network targets

`tensornet` contracts the network exactly (cost set by treewidth, not qubit count): good for wide,
shallow circuits and single expectation values on 50-100+ qubits. `tensornet-mps` truncates to a
maximum bond dimension (configured through environment variables whose names are
version-dependent; check the target docs) and needs a χ-convergence sweep exactly as in
`quantum-circuit-simulators`. Neither helps deep, highly entangled circuits.

## 6. Noise

```python
noise = cudaq.NoiseModel()                                        # methods (verified): add_channel,
noise.add_all_qubit_channel("h", cudaq.DepolarizationChannel(0.01))   # add_all_qubit_channel, get_channels, register_channel
noise.add_channel("x", [0], cudaq.AmplitudeDampingChannel(0.005))
noise.add_channel("rx", [1], cudaq.KrausChannel([K0, K1]))        # K_i: complex numpy arrays with Σ K†K = I
cudaq.set_target("density-matrix-cpu")
counts = cudaq.sample(kernel, shots_count=4000, noise_model=noise)
```

Channels (verified): `DepolarizationChannel`, `AmplitudeDampingChannel`, `BitFlipChannel`,
`PhaseFlipChannel`, `KrausChannel`. Noise attaches to gate names, so noise placed on a gate that
does not change the measured observable shows nothing (depolarizing on the H of a Bell circuit
leaves only 00/11 outcomes). Statevector targets sample noise as trajectories (`num_trajectories`
in `observe`). Building noise models from calibrations: `quantum-noise-mitigation`.

## 7. Variational loops

```python
opt = cudaq.optimizers.COBYLA()             # also Adam, GradientDescent, LBFGS, NelderMead, SGD, SPSA (verified)
opt.initial_parameters = [0.0]; opt.max_iterations = 100
energy, params = opt.optimize(1, lambda v: cudaq.observe(ansatz, H, v[0]).expectation())
```

`cudaq.gradients` supplies finite-difference gradients for the gradient-based optimisers; SciPy
works the same way (`scipy.optimize.minimize(f, x0, method="COBYLA")`). `cudaq.vqe` was removed
in 0.16 (verified: the error points to the CUDA-QX VQE); write the loop or use CUDA-QX.
Design questions (ansatz, shots, barren plateaus): `variational-quantum-algorithms`.

## 8. Hardware backends

Target names present in 0.16 (verified): `anyon`, `braket`, `fermioniq`, `infleqtion`, `ionq`,
`iqm`, `oqc`, `orca`, `orca-photonics`, `pasqal`, `qbraid`, `quantinuum`, `quantum_machines`,
`quera`, `scaleway`, `tii`. Credentials come from environment variables or the provider's own
config file as described in each target's documentation; never put keys in code, notebooks or
skills. Several targets offer local emulation; check before spending quota. Do not submit to a
paid QPU yourself: prepare the script and hand the submission (target, shots, cost) to the user.

## 9. Worked example: H2 VQE batched over QPUs with observe_async

Hamiltonian: H2/STO-3G at 0.7414 Å, Jordan-Wigner, interleaved spin orbitals (15 terms, from
`quantum-chemistry-mapping`); ansatz: HF |1100⟩ plus one double-excitation rotation.

```python
import numpy as np, cudaq
from cudaq import spin
H = (-0.0988639693 * spin.i(0) + 0.1711977490 * (spin.z(0) + spin.z(1)) - 0.2227859304 * (spin.z(2) + spin.z(3))
     + 0.1686221916 * spin.z(0) * spin.z(1) + 0.1205448221 * (spin.z(0) * spin.z(2) + spin.z(1) * spin.z(3))
     + 0.1658670241 * (spin.z(0) * spin.z(3) + spin.z(1) * spin.z(2)) + 0.1743484419 * spin.z(2) * spin.z(3)
     + 0.0453222021 * (spin.x(0) * spin.y(1) * spin.y(2) * spin.x(3) + spin.y(0) * spin.x(1) * spin.x(2) * spin.y(3)
                       - spin.x(0) * spin.x(1) * spin.y(2) * spin.y(3) - spin.y(0) * spin.y(1) * spin.x(2) * spin.x(3)))

if cudaq.num_available_gpus() > 0:
    cudaq.set_target("nvidia", option="mqpu,fp64")     # one virtual QPU per GPU
n_qpu = cudaq.get_target().num_qpus()
thetas = np.linspace(-0.5, 0.5, 41)
futures = [cudaq.observe_async(ansatz, H, float(t), qpu_id=i % n_qpu) for i, t in enumerate(thetas)]
E = np.array([f.get().expectation() for f in futures])
opt = cudaq.optimizers.COBYLA(); opt.initial_parameters = [float(thetas[E.argmin()])]
e_min, p = opt.optimize(1, lambda v: cudaq.observe(ansatz, H, v[0]).expectation())
```

Verified output (CUDA-Q 0.16, `qpp-cpu`, 1 QPU; on k GPUs the 41 scan points spread over k QPUs):

| Quantity | Value |
|---|---|
| E(θ = 0) | -1.116684 Ha (= E_HF) |
| grid minimum | θ = 0.125, E = -1.137040 Ha |
| COBYLA | θ* = 0.11311, E = -1.13727017 Ha (FCI -1.13727017) |
| state at θ* | 0.99361 \|1100⟩ - 0.11287 \|0011⟩ (`get_state` indices 3 and 12) |
| `sample(..., shots_count=2000)` | { 1100: 1978, 0011: 22 } (sin²θ* = 1.3%) |

The amplitudes show `exp_pauli(θ, q, "XXXY")` maps |1100⟩ to cos θ|1100⟩ - sin θ|0011⟩. Before
reusing exp_pauli for time evolution, fix its sign convention with a one-qubit test against `rx`.
For 4 qubits the GPU batching is pure overhead; it pays when each observe is large (20+ qubits)
or the scan/gradient has hundreds of points.

## Pitfalls

- Untyped or Python-object arguments in kernels: compilation errors that point at the kernel line.
- Bit order: sample strings and `get_state` indices use opposite conventions; Qiskit uses a third
  printing order.
- fp32 default on `nvidia`/`mqpu` compared against fp64 references at 1e-8 tolerance.
- `mgpu` used for circuits that fit one GPU (slower), or `mqpu` expected to enlarge memory (it does not).
- Noise placed on gates that do not affect the observable, then "no effect" reported.
- Removed or changed APIs (`cudaq.vqe` in 0.16; sample/observe changes announced): pin versions.
- Credentials pasted into code; jobs submitted to paid hardware without the user's approval.

Related: `quantum-circuit-simulators`, `variational-quantum-algorithms`, `quantum-chemistry-mapping`, `hamiltonian-simulation-methods`, hub `quantum-computing`
