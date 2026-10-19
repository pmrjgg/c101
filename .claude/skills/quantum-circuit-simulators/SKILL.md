---
name: quantum-circuit-simulators
description: "Choosing, running and validating quantum circuit simulators: memory math; statevector, density-matrix, trajectory, stabilizer, extended-stabilizer, MPS, tensor-network and Pauli-propagation backends across Aer, qsim, Lightning, CUDA-Q, quimb and Stim; GPU and precision settings, convergence checks and a validation checklist. Load when picking a simulator, scaling a simulation, or proving a simulator result is right."
when_to_use: "Picking a simulator or method for n qubits, depth and noise; 'out of memory', 'simulation too slow', 'results differ between Qiskit and Cirq/PennyLane'; configuring Aer (method, device, precision, fusion, MPS bond dimension), qsim, Lightning, CUDA-Q targets or quimb; MPS or tensor-network convergence; fp32 vs fp64; endianness and global-phase issues; writing simulator regression tests or benchmark reports."
---

# Quantum circuit simulators

The right simulator follows from four numbers: qubits n, entanglement (depth × connectivity),
noise representation, and what is needed out (amplitudes, samples, or a few expectation values).
Compute memory first, pick the cheapest exact method, add one independent engine as a
cross-check, and never report an approximate method without its convergence evidence.
GPU kernels in CUDA-Q: `cudaq-gpu-kernels`; Clifford/QEC sampling: `stim-qec-decoding`.

## 1. Memory math

```
statevector     16 · 2^n bytes (complex128), 8 · 2^n (complex64);   plus ~1-2x workspace
density matrix  16 · 4^n bytes
MPS             ≈ 16 · n · 2 · χ² bytes (bond dimension χ)
stabilizer      O(n²) bits (tableau)
```

| n | statevector fp64 | fp32 | density matrix fp64 at n |
|---|---|---|---|
| 24 | 256 MiB | 128 MiB | 12 qubits: 256 MiB |
| 28 | 4 GiB | 2 GiB | 14: 4 GiB |
| 30 | 16 GiB | 8 GiB | 15: 16 GiB |
| 32 | 64 GiB | 32 GiB | 16: 64 GiB |
| 34 | 256 GiB | 128 GiB | 17: 256 GiB |

Every extra qubit doubles memory and time; check `free -g` / `sysctl hw.memsize` before launch so
the run never spills into swap.

## 2. Decision table

| Workload | Method | Engines |
|---|---|---|
| exact, ≤ ~30-34 qubits | statevector | Aer `statevector`, qsim, PennyLane `lightning.*`, CUDA-Q `nvidia` |
| arbitrary channels, ≤ ~15 qubits | density matrix | Aer `density_matrix`, `cirq.DensityMatrixSimulator`, `default.mixed`, CUDA-Q `density-matrix-cpu` |
| noisy, larger n | trajectories (Monte Carlo wavefunctions) | Aer statevector + noise model, CUDA-Q `observe(..., noise_model=, num_trajectories=)` |
| Clifford circuits, QEC | stabilizer tableau | Stim, Aer `stabilizer` |
| Clifford + few T | extended stabilizer / stabilizer rank | Aer `extended_stabilizer` (`extended_stabilizer_approximation_error`) |
| low entanglement, 50-1000 qubits | MPS | Aer `matrix_product_state`, quimb, CUDA-Q `tensornet-mps` |
| shallow and wide | tensor-network contraction | quimb + cotengra, cuTensorNet (CUDA-Q `tensornet`) |
| local expectations of deeper circuits | Pauli propagation / operator backpropagation | PauliPropagation.jl, `qiskit-addon-obp` |

Density matrices are needed only when the output is the full mixed state; for expectation values
of noisy circuits, trajectories at 2^n memory usually beat 4^n.

## 3. Qiskit Aer specifics (Aer 0.17)

```python
from qiskit_aer import AerSimulator
sim = AerSimulator(method="statevector", device="GPU", precision="single",   # device="CPU" default
                   fusion_enable=True, max_parallel_threads=0,               # 0 = all cores
                   blocking_enable=True, blocking_qubits=26)                 # chunking for multi-GPU / memory
qc.save_expectation_value(obs, qubits)      # exact values, no sampling
qc.save_statevector()                       # only when amplitudes are really needed
```

Other verified options: `shot_branching_enable` (dynamic circuits and noise), `cuStateVec_enable`,
`batched_shots_gpu`, `matrix_product_state_max_bond_dimension`,
`matrix_product_state_truncation_threshold`, `mps_log_data`. `AerSimulator().available_devices()`
lists what the installed build supports.

## 4. Other engines

| Engine | Notes |
|---|---|
| qsim (`qsimcirq`) | Cirq front end; fast fused-gate statevector, GPU via cuStateVec; Cirq results are big-endian; native PhasedXZ gates |
| PennyLane Lightning | `lightning.qubit`, `lightning.gpu`, `lightning.kokkos`; `diff_method="adjoint"` for cheap exact gradients |
| CUDA-Q | `@cudaq.kernel` typed subset; `nvidia` (fp32/fp64 option), multi-GPU and multi-QPU options, `tensornet`, `tensornet-mps`, `mpirun` scaling (`cudaq-gpu-kernels`) |
| quimb + cotengra | `quimb.tensor.Circuit`, `local_expectation(...)`; plan contractions with cotengra hyper-optimisers |
| Qrack | GPU/CPU hybrid with Schmidt decomposition |
| Stim, `stimcirq` | Clifford circuits at billions of shots; `stimcirq` bridges Cirq Clifford circuits |

Use one primary engine and one cross-check engine with a different algorithm when possible.

## 5. MPS and tensor-network convergence

- Sweep χ ∈ {32, 64, 128, 256}; accept when the observable changes by less than the tolerance
  between the two largest χ. Report χ, the truncation threshold and the discarded weight.
- Entanglement entropy S across the middle cut needs χ ≳ e^S; linear growth of S in time predicts
  an exponential χ wall, so extrapolate the cost before going deeper.
- For contraction, estimate width W (log2 of the largest intermediate tensor) and cost first
  (cotengra / quimb rehearse functions); memory 16 · 2^W bytes must fit.

## 6. Precision

fp32 unit roundoff is 6e-8, so errors per gate of order 1e-7 accumulate. Check fp32 against fp64
at small n and assert the final norm: measured here at n = 20, depth 10 brickwork,
|1 - F(ψ_fp32, ψ_fp64)| = 3.3e-8 and |‖ψ_fp32‖ - 1| = 1.7e-8. Use fp64 for anything compared at
1e-8 tolerance, fp32 for sampling-scale statistics.

## 7. Validation checklist

- [ ] Endianness probe: X on qubit 0 of 3 gives index 1 / bitstring "001" in Qiskit and index 4 /
      "100" in Cirq and PennyLane. CUDA-Q prints sample strings with qubit 0 first ("100") but
      `get_state` indexes little-endian (index 1), verified on CUDA-Q 0.16.
- [ ] Known answers: Bell and GHZ probabilities; QFT of |k⟩ has uniform magnitudes 2^{-n/2} and
      phases 2πjk/2^n; Grover success sin²((2k + 1)θ) with sin θ = √(M/N).
- [ ] Unitarity of hand-built matrices: ‖U†U - I‖ < 1e-10.
- [ ] Compilation equivalence: `Operator(qc).equiv(Operator(tqc))` up to ~12 qubits (account for
      layouts), MQT QCEC (`mqt.qcec.verify`) beyond.
- [ ] Cross-simulator: exact probabilities TVD < 1e-9; compare states with `Statevector.equiv`
      or |⟨ψ|φ⟩| (global phase is unobservable).
- [ ] Sampled results: TVD to the ideal distribution inside the null distribution of TVDs from
      resampling the ideal distribution at the same shot count.
- [ ] Noise sanity: p → 0 reproduces the ideal result; maximal depolarizing gives uniform outputs.

## 8. Regression testing

```python
import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

def ghz(n):
    qc = QuantumCircuit(n); qc.h(0)
    for i in range(n - 1): qc.cx(i, i + 1)
    return qc

def test_ghz_exact():                                   # golden file from a trusted run
    np.testing.assert_allclose(Statevector(ghz(5)).probabilities(), np.load("golden/ghz5.npy"), atol=1e-8)

def test_ghz_sampled(run_sampled):                      # fixture with fixed simulator + transpiler seeds
    shots, counts = 20_000, run_sampled(ghz(5), shots=20_000, seed=1234)
    assert abs(counts.get("00000", 0) / shots - 0.5) < 4 * np.sqrt(0.25 / shots)
```

Fix simulator and transpiler seeds, keep golden data for small circuits, use atol 1e-8 for exact
and 4σ for sampled tests, and run small n in CI.

## 9. Performance hygiene

- Compile once, bind parameters many times; batch circuits into one `run` call.
- No per-shot Python loops; request expectation values instead of sampling when exact values
  suffice.
- Profile time against n (n, n + 2, n + 4) to locate the wall before launching the big run.
- Thread count = physical cores; pin GPU runs to one process per device.

## 10. Benchmark reporting

Report wall time against n; hardware (CPU model and threads, GPU model, memory); library versions;
precision; method and options (fusion, blocking, χ); and at least one alternative engine. One
timing without versions or hardware is an anecdote.

## 11. Worked example

Random brickwork (U3 on every qubit, CX on alternating pairs) at depth 10, Aer 0.17.2 statevector,
`save_expectation_value(Z_0)`, Apple-silicon CPU, 32 threads (no NVIDIA GPU available, so the GPU
column must be filled on the target machine):

| n | precision | wall time | ⟨Z_0⟩ |
|---|---|---|---|
| 24 | fp64 | 0.48 s | 0.222157 |
| 24 | fp32 | 0.47 s | 0.222157 |
| 28 | fp64 | 5.80 s | 0.176350 |
| 28 | fp32 | 5.51 s | 0.176350 |

Four extra qubits cost 12x time (16x memory); fp32 saved only ~5% of time on this CPU while
halving memory, so measure precision gains on the target hardware. Inter-precision fidelity at n = 20 is
1 - 3.3e-8 (section 6).

MPS: 60-qubit 1D transverse-field Ising Trotter circuit, J = h = 1, 20 steps of dt = 0.25 (even/odd
RZZ layers then RX), ⟨Z_30⟩, Aer `matrix_product_state` with truncation threshold 1e-16:

| χ | ⟨Z_30⟩ | change | wall time |
|---|---|---|---|
| 16 | +0.009520 | - | 0.2 s |
| 32 | +0.002924 | 6.6e-3 | 0.6 s |
| 64 | +0.001444 | 1.5e-3 | 3.5 s |
| 128 | +0.001444 | 9.7e-8 | 18.6 s |
| 256 | +0.001445 | 5.8e-8 | 68.0 s |

χ = 16 and 32 are wrong by 6x and 2x with no warning; the value is converged at χ = 128 to 1e-7,
and time grows 4-5x per doubling of χ. Report ⟨Z_30⟩ = 0.001444 (χ = 128 vs 256 agree to 6e-8).

## Pitfalls

- Density matrix chosen where trajectories or exact expectation values suffice (4^n vs 2^n).
- MPS or tensor-network numbers reported without a χ (or truncation) sweep.
- States compared without handling global phase, or bitstrings without handling endianness.
- Default seeds differing between engines, so "disagreements" are sampling noise.
- Memory silently spilling into swap: the run looks hung, then times out.
- Transpiled circuits compared without the final layout permutation.

Related: `cudaq-gpu-kernels`, `stim-qec-decoding`, `quantum-noise-mitigation`, `hamiltonian-simulation-methods`, hub `quantum-computing`
