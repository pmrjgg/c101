---
name: qiskit-primitives-runtime
description: "Qiskit SamplerV2/EstimatorV2 and IBM Qiskit Runtime: PUB formats and broadcasting, local exact, Aer and fake-backend testing, execution modes, resilience/twirling/DD options, job management, addons and cost guards. Load when running circuits through primitives locally or on IBM hardware."
when_to_use: "Running circuits or expectation values through Qiskit primitives (StatevectorSampler/StatevectorEstimator, Aer, qiskit-ibm-runtime); building PUBs and parameter sweeps; 'evs has the wrong shape', 'BitArray has no attribute', 'results look like the wrong qubits', 'circuit is not ISA'; choosing job, Batch or Session mode; setting resilience_level, twirling, dynamical decoupling, ZNE/PEA or PEC; local testing mode with fake backends; preparing a QPU submission with a cost cap; migrating V1 primitive code or the deprecated runtime SamplerV2/EstimatorV2 classes."
---

# Qiskit primitives and IBM Runtime

Primitives are the only supported way to execute circuits in Qiskit 2.x. The workflow is fixed:
transpile to ISA, map observables with `apply_layout`, compute an exact local reference, dry-run on
a fake backend, then hand a ready job (options, cost cap, saved IDs) to the user for approval.
Values marked *measured* come from qiskit 2.6.0, qiskit-aer 0.17.2 and qiskit-ibm-runtime 0.50.0.

Version note (measured): qiskit-ibm-runtime 0.50.0 marks the `SamplerV2` and `EstimatorV2` classes
deprecated. Client-side replacements are `qiskit_ibm_runtime.executor_sampler.Sampler` and
`qiskit_ibm_runtime.executor_estimator.Estimator` (constructor `(mode=None, options=None)`), next
to a new `Executor` primitive, and the top-level `qiskit_ibm_runtime.Sampler` / `Estimator` names
are announced to switch to them. The PUB and options model below is the V2 primitives interface;
before migrating, confirm in the docs for your version which options and result fields the
replacements keep.

## 1. PUB shapes and broadcasting

| Primitive | PUB tuple | Circuit rule |
|---|---|---|
| Sampler | (circuit, parameter_values=None, shots=None) | must contain measurements |
| Estimator | (circuit, observables, parameter_values=None, precision=None) | must not contain measurements |

parameter_values has shape (..., n_params); observables have shape (...). The result shape is the
NumPy broadcast of the observables shape with the parameter shape minus its last axis.

| observables shape | parameter_values shape | evs shape |
|---|---|---|
| () one SparsePauliOp | (n_params,) | () |
| (3,) | (n_params,) | (3,) |
| (3, 1) | (50, n_params) | (3, 50) |
| (k, 1, 1) | (20, 30, n_params) | (k, 20, 30) |

One PUB with a 2D sweep replaces 600 x k separate jobs. A Sampler PUB with parameters of shape
(B, n_params) returns a BitArray of shape (B,), each element holding `shots` samples.

## 2. Result access

```python
res = sampler.run([(isa, vals, 4000)]).result()
ba = res[0].data.meas                  # BitArray named after the classical register ('meas' after measure_all)
ba.get_counts()                        # {'011': 512, ...}; loc= selects one element of a broadcast shape
ba.get_int_counts(); ba.get_bitstrings()
ba.slice_bits([0, 2])                  # marginal on clbits 0 and 2
ba.expectation_values(["ZZ", "ZI"])    # Z-type observables computed from the samples
ba.to_bool_array(order="big")          # (shots, bits) array for large-n post-processing
ba.num_shots, ba.shape

res = estimator.run([(isa, obs_isa, vals)]).result()
evs, stds = res[0].data.evs, res[0].data.stds     # broadcast shape
res[0].metadata                                    # e.g. {'target_precision': 0.01, 'shots': 10000, ...}
```
Bitstrings are little-endian (clbit 0 is the rightmost character). Precision is the target standard
error: shots is about 1/precision^2 (measured in local mode: precision 0.01 gave 10000 shots), and
the actual sigma of a Pauli is sqrt((1 - ⟨P⟩^2)/shots), below the target when ⟨P⟩ is near +-1
(`quantum-measurement-estimation`).

## 3. Local tiers

| Tier | Classes | Use |
|---|---|---|
| exact | `qiskit.primitives.StatevectorSampler(default_shots=1024, seed=)`, `StatevectorEstimator(default_precision=0.0, seed=)` | known answers, unit tests |
| noisy simulation | `qiskit_aer.primitives.SamplerV2`, `EstimatorV2` with a noise model | noise studies |
| local testing mode | runtime primitives with `mode=FakeFez()` (Aer with the fake backend's noise model) | mandatory dry run of the exact hardware script |

Measured gotchas: `StatevectorEstimator(default_precision=0.01)` adds Gaussian noise (rms error
0.0083 over 50 points) but returns `stds = 0`; take sigma from `metadata["target_precision"]`.
Local testing mode warns "The resilience_level option has no effect in local testing mode": error
mitigation cannot be dry-run locally, only the circuit, layout, shapes and shot count.

## 4. Accounts and safety

```python
from qiskit_ibm_runtime import QiskitRuntimeService
# One-time setup, run by the user in their own shell; the token never goes in code, repo or logs:
#   QiskitRuntimeService.save_account(channel="ibm_quantum_platform", token=..., instance="<CRN>", set_as_default=True)
service = QiskitRuntimeService()                          # reads the saved account
be = service.least_busy(operational=True, simulator=False)    # or service.backend("ibm_fez")
```
Channels: `ibm_quantum_platform` or `ibm_cloud`, with the instance CRN. Never submit a QPU job
yourself: write the script to out_dir and return backend, number of PUBs, shots or precision,
options and estimated QPU seconds as an Open doubt for the user's approval (hub rule). Estimate QPU
time from a small pilot job's usage (`job.usage()`, `job.metrics()`; both exist in 0.50) scaled
linearly in circuits x shots, times the mitigation multiplier (section 7).

## 5. Execution modes

| Mode | Behaviour | Fits | Plan |
|---|---|---|---|
| job (`mode=backend`) | one job, queued on its own | single runs | all |
| `Batch(backend, max_time=)` | independent jobs scheduled together; classical work overlaps | sweeps, many PUBs | all |
| `Session(backend, max_time=)` | dedicated QPU access between your jobs | iterative loops (VQE, adaptive) | not on the Open plan |

```python
from qiskit_ibm_runtime import Batch, EstimatorV2
with Batch(backend=be, max_time="1h") as batch:
    est = EstimatorV2(mode=batch)
    est.options.max_execution_time = 600       # QPU seconds per job: the hard cost cap
    jobs = [est.run([pub]) for pub in pubs]
```

## 6. ISA requirements

```python
from qiskit.transpiler import generate_preset_pass_manager
pm = generate_preset_pass_manager(optimization_level=2, backend=be, seed_transpiler=7)
isa = pm.run(qc)
obs_isa = obs.apply_layout(isa.layout)         # 2-qubit 'ZZ' becomes a 156-qubit operator on the chosen qubits
```
- Sampler circuits need measurements; Estimator circuits must have none
  (`qc.remove_final_measurements(inplace=False)`).
- The classical register name is the data attribute: `measure_all()` gives `.data.meas`,
  `ClassicalRegister(3, "c")` gives `.data.c`.
- Hardware rejects non-ISA circuits: transpile with the backend's own pass manager
  (`qiskit-transpilation`), and transpile once, then bind parameters in the PUB.

## 7. Options map

All paths below were measured on `EstimatorOptions` / `SamplerOptions` in 0.50.0.

| Option | Values | Effect and cost |
|---|---|---|
| `default_shots` | int | Sampler shots; Estimator alternative to precision |
| `default_precision` | float | Estimator target sigma; shots about 1/p^2 |
| `resilience_level` | 0, 1, 2 (Estimator only) | 0 none; 1 measurement mitigation (TREX); 2 adds ZNE with gate twirling |
| `resilience.measure_mitigation` | bool | TREX readout mitigation |
| `resilience.zne_mitigation`, `resilience.zne.noise_factors`, `.extrapolator`, `.amplifier` | e.g. (1, 3, 5); 'linear', 'exponential' (more in `ExtrapolatorType`); 'gate_folding', 'gate_folding_front', 'gate_folding_back', 'pea' | runtime grows with the sum of noise factors, about 3-5x |
| `resilience.pec_mitigation`, `resilience.pec.max_overhead`, `.noise_gain` | bool, float, float or 'auto' | sampling overhead grows exponentially with circuit noise |
| `resilience.layer_noise_learning` | sub-options | noise learning for PEA and PEC |
| `twirling.enable_gates`, `enable_measure`, `num_randomizations`, `shots_per_randomization`, `strategy` | bool, int or 'auto', 'active', 'active-accum', 'active-circuit', 'all' | randomised compiling; Sampler supports it too |
| `dynamical_decoupling.enable`, `sequence_type`, `extra_slack_distribution`, `scheduling_method` | bool; 'XX', 'XpXm', 'XY4'; 'middle', 'edges'; 'alap', 'asap' | protects idle qubits |
| `max_execution_time` | seconds | cost cap |
| `seed_estimator`; `simulator.seed_simulator` | int | reproducibility (the latter in local mode) |

```python
est = EstimatorV2(mode=be)
o = est.options
o.default_precision = 0.01
o.resilience_level = 1
o.twirling.enable_gates = True
o.twirling.num_randomizations = 32
o.dynamical_decoupling.enable = True
o.dynamical_decoupling.sequence_type = "XpXm"
o.resilience.zne_mitigation = True                 # explicit ZNE instead of resilience_level 2
o.resilience.zne.noise_factors = (1, 3, 5)
o.resilience.zne.extrapolator = "exponential"
o.resilience.zne.amplifier = "pea"
(out_dir / "options.txt").write_text(str(est.options))     # save the exact options with every result
```
What each technique corrects and how to judge it: `quantum-noise-mitigation`.

## 8. Job lifecycle

```python
job = est.run([pub])
job_id = job.job_id()               # save immediately
job.status()                        # QUEUED, RUNNING, DONE, ERROR, CANCELLED
result = job.result()               # blocks until done
job = service.job(job_id)           # re-fetch later or from another process
job.cancel()

import json
from qiskit import qpy
with open(out_dir / "isa.qpy", "wb") as f:
    qpy.dump(isa, f)
(out_dir / "manifest.json").write_text(json.dumps({
    "job_ids": [job_id], "backend": be.name, "seed_transpiler": 7,
    "observables": [str(o) for o in obs], "precision": 0.01}, indent=2))
```
Saving job IDs, options, transpile seeds and ISA circuits lets results be re-fetched and audited
without re-running anything.

## 9. Parameter binding order

`qc.parameters` is sorted by name (a ParameterVector sorts by index, so θ[10] follows θ[9]);
columns of parameter_values follow `list(isa.parameters)`. Parameters named `beta` and `gamma` take
columns 0 and 1 whatever order the circuit uses them in. Before any sweep, run one known-answer point
(for the ansatz below, θ = 0 gives ⟨ZZ⟩ = 1, ⟨XX⟩ = ⟨YY⟩ = 0).

## 10. Higher-level tools

| Package | Purpose | Check first |
|---|---|---|
| qiskit-addon-sqd | sample-based quantum diagonalisation (configuration recovery + subspace diagonalisation) | classical diagonalisation cost dominates at scale |
| qiskit-addon-obp | operator backpropagation: evolve the observable classically to shorten the circuit | truncation error budget |
| qiskit-addon-mpf | multi-product formulas to cut Trotter error | number of extra circuits |
| qiskit-addon-cutting | gate and wire cutting | sampling overhead exponential in the number of cuts |
| Qiskit Functions catalog (`qiskit-ibm-catalog`) | IBM and partner circuit and application functions | plan availability and pricing |

Check plan availability and cost before proposing any of them.

## 11. Worked example: three observables x 50 angles in one PUB

Ansatz: CX (RY(θ) x I) acting on 00 gives cos(θ/2)|00⟩ + sin(θ/2)|11⟩, so ⟨ZZ⟩ = 1, ⟨XX⟩ = sin θ,
⟨YY⟩ = -sin θ.

```python
import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter
from qiskit.quantum_info import SparsePauliOp
from qiskit.primitives import StatevectorEstimator
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import EstimatorV2
from qiskit_ibm_runtime.fake_provider import FakeFez

th = Parameter("θ")
qc = QuantumCircuit(2); qc.ry(th, 0); qc.cx(0, 1)
obs = [[SparsePauliOp("ZZ")], [SparsePauliOp("XX")], [SparsePauliOp("YY")]]    # shape (3, 1)
T = np.linspace(0, 2 * np.pi, 50).reshape(50, 1)                                  # shape (50, 1)
s = np.sin(T[:, 0])

r = StatevectorEstimator().run([(qc, obs, T)]).result()[0]
print(r.data.evs.shape, np.abs(r.data.evs[1] - s).max())                         # (3, 50) 0.0

be = FakeFez()
isa = generate_preset_pass_manager(optimization_level=2, backend=be, seed_transpiler=7).run(qc)
obs_isa = [[o.apply_layout(isa.layout) for o in row] for row in obs]
est = EstimatorV2(mode=be)                                                         # local testing mode
est.options.default_precision = 0.01
est.options.simulator.seed_simulator = 42
r = est.run([(isa, obs_isa, T)]).result()[0]
amp = lambda y, f: float(np.sum(y * f) / np.sum(f * f))                           # least-squares amplitude
print(r.data.evs[0].mean(), amp(r.data.evs[1], s), amp(r.data.evs[2], -s), r.data.stds.mean(), r.metadata)
```

Measured:

| Tier | ⟨ZZ⟩ mean (ideal 1) | XX amplitude (ideal 1) | YY amplitude (ideal 1) | sigma per point |
|---|---|---|---|---|
| StatevectorEstimator, exact | 1.0000 | 1.0000 | 1.0000 | 0 |
| FakeFez local mode, precision 0.01 (10000 shots; qubits 23, 22; 1 CZ) | 0.9714 | 0.9699 | 0.9680 | 0.0053 (mean of stds) |
| local readout rescaling (divide by ⟨ZZ⟩ = 0.9952 measured on 00 with the same layout) | n/a | 0.9746 | n/a | about 0.005 |
| hardware with resilience_level 1 | user runs it | | | |

Reading: the 3% contraction is mostly gate noise; readout explains only 0.5% on these qubits, so
resilience_level 1 (TREX corrects readout only) will recover little, and ZNE (level 2) targets the
gate part at 3-5x runtime. The deficit (0.03) is about 6 sigma per point and far more over 50
points, so it is real. The hardware script is the same file with `be = service.backend(...)`,
`resilience_level = 1`, a Batch and `max_execution_time`; hand it to the user with backend, 1 PUB of
3 x 50 values, precision 0.01 and the pilot-based QPU time estimate.

## 12. Pitfalls

- V1 result access (`result.quasi_dists`, `result.values`) mixed with V2 (`res[0].data...`).
- `apply_layout` forgotten: the observable silently lands on the wrong physical qubits.
- Precision confused with shots, or sigma assumed to equal precision when ⟨P⟩ is near +-1.
- PUBs or jobs above the service size limits: split large sweeps (limits are in the runtime docs).
- Resilience options assumed free: ZNE multiplies runtime by about 3-5x, PEC exponentially.
- StatevectorEstimator `stds` read as the error bar (it is 0 even with precision set).
- Measurements left in Estimator circuits, or missing from Sampler circuits.
- `.data.meas` assumed when the register has another name.
- Parameter columns passed in circuit order instead of sorted order.
- Session mode requested on the Open plan.

Related: `qiskit-transpilation`, `quantum-noise-mitigation`, `quantum-measurement-estimation`, `variational-quantum-algorithms`, hub `quantum-computing`
