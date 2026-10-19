---
name: quantum-noise-mitigation
description: "Noise characterisation, noise-model building and error mitigation: Kraus channels and T1/T2 conversions, RB/interleaved RB/XEB/layer fidelity, Aer and Cirq noise models from calibrations, readout mitigation (M3, TREX), dynamical decoupling, Pauli twirling, ZNE, PEC/PEA, CDR and symmetry verification, with sampling-overhead accounting. Load when results come from noisy hardware or a noisy simulation."
when_to_use: "Expectation values from a QPU or noisy simulator that disagree with theory; building an Aer or Cirq noise model from T1, T2, gate and readout errors; choosing or configuring readout mitigation, DD, twirling, ZNE, PEC/PEA, CDR or symmetry post-selection (Mitiq, Qiskit Runtime resilience options, mthree); estimating the shot overhead of mitigation; RB, XEB or layer-fidelity analysis; reviewing a paper's mitigated results."
---

# Noise characterisation and error mitigation

Mitigation trades bias for variance at a sampling cost that grows exponentially with circuit
volume. Decide in this order: will the circuit survive at all (section 4), what can be suppressed
for free (section 5), which estimator removes the remaining bias at an affordable overhead
(sections 6-9), and how the result is reported (section 12). Error correction is a different
regime: `stabilizer-codes-surface-code`.

## 1. Channels and parameters

| Channel | Kraus / map | Parameters |
|---|---|---|
| amplitude damping | K0 = [[1, 0], [0, √(1-γ)]], K1 = [[0, √γ], [0, 0]] | γ = 1 - e^{-t/T1} |
| pure dephasing | ρ → (1 - λ)ρ + λ ZρZ | 1/T_φ = 1/T2 - 1/(2T1); always T2 ≤ 2T1 |
| depolarizing (n qubits) | ρ → (1 - λ)ρ + λ I/d | average infidelity e = λ(d - 1)/d, so λ = 2e (1q), 4e/3 (2q) |
| readout | confusion matrix A_ij = P(read i, prepared j) | asymmetric: P(0 given 1) usually larger (T1 decay during readout) |
| coherent over-rotation by ε | U = e^{-iεσ/2} | 1 - F_avg = (2/3) sin²(ε/2) ≈ ε²/6; N repeats → (Nε)²/6 coherent vs Nε²/6 stochastic |
| crosstalk, leakage | spectator ZZ, population outside {0, 1} | not a single-qubit Pauli channel; leakage needs reset or LRUs |

Example: T1 = 100 µs, T2 = 80 µs gives 1/T_φ = 1/80 - 1/200 µs⁻¹, T_φ = 133 µs; a 60 ns gate has
γ = 1 - e^{-0.0006} = 6.0e-4. Always check completeness Σ K†K = I numerically
(`np.allclose(sum(K.conj().T @ K for K in Ks), np.eye(d))`).

## 2. Characterisation recipes

| Experiment | Fit | Output | qiskit-experiments 0.14 class |
|---|---|---|---|
| T1 | P1(t) = A e^{-t/T1} + B | T1 | `T1` |
| Ramsey | A e^{-t/T2*} cos(2πΔf t + φ) + B | T2*, detuning | `T2Ramsey` |
| Hahn echo | A e^{-t/T2} + B | T2 (echo) | `T2Hahn` |
| readout | prepare each basis state, histogram | assignment matrix | `LocalReadoutError`, `CorrelatedReadoutError` |
| standard RB | F(m) = A p^m + B | r = (d - 1)(1 - p)/d per Clifford | `StandardRB` |
| interleaved RB | p_C from interleaved / reference decay | r_C = (d - 1)(1 - p_C/p)/d | `InterleavedRB` |
| XEB | F_XEB = 2^n ⟨P_ideal(x_i)⟩ - 1 | per-cycle fidelity | (Cirq `cirq.experiments` XEB tools) |
| layer fidelity | product of per-layer process fidelities | LF, EPLG = 1 - LF^{1/n_2q} | `LayerFidelity` |

Conversions: F_avg = (d F_pro + 1)/(d + 1); RB reports average error per Clifford, not per native
gate (divide by the mean native-gate count per Clifford only as an estimate).

## 3. Noise-model construction (Aer)

```python
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error, thermal_relaxation_error, ReadoutError

sim = AerSimulator.from_backend(backend)        # fake or snapshot backend: gate, T1/T2 and readout errors
nm = NoiseModel()                               # or by hand from a calibration table:
t1, t2, t_1q, t_2q = 100e-6, 80e-6, 50e-9, 70e-9
relax = thermal_relaxation_error(t1, t2, t_2q)
nm.add_all_qubit_quantum_error(depolarizing_error(4e-3 * 4 / 3, 2).compose(relax.tensor(relax)), ["cz"])
nm.add_all_qubit_quantum_error(depolarizing_error(2e-4 * 2, 1).compose(thermal_relaxation_error(t1, t2, t_1q)), ["sx", "x"])
nm.add_all_qubit_readout_error(ReadoutError([[0.99, 0.01], [0.03, 0.97]]))   # rows: prepared 0, prepared 1
```

`from_backend` already subtracts the relaxation part from the reported gate error; a hand-built
model that adds both double-counts. Cirq: `cirq.ConstantQubitNoiseModel` or per-moment custom
models. Validate before trusting predictions: reproduce a measured RB decay or GHZ fidelity on the
same qubits within its error bar, then predict.

## 4. Success budget

```
S ≈ Π_gates (1 - e_g) · Π_readout (1 - e_ro) · Π_idle e^{-t_idle/T}        200 CZ at 0.5% → 0.995^200 = 0.37
```

S estimates the surviving signal fraction of a global observable. Below ~0.1, redesign (fewer 2q
gates, better layout, shorter idle) before spending shots; mitigation cannot recover a vanished
signal at sane cost.

## 5. Suppression first

- Dynamical decoupling: XY4 or XpXm in idle windows, aligned to the device timing.
  Qiskit: `PassManager([ALAPScheduleAnalysis(target=t), PadDynamicalDecoupling(target=t,
  dd_sequence=[XGate(), XGate()])])`; Runtime: `dynamical_decoupling.enable`,
  `dynamical_decoupling.sequence_type = "XpXm"`.
- Pauli twirling: wrap each 2q layer in random Paulis P before and C P C† after; averaging over
  instances turns coherent errors into stochastic Pauli noise (a prerequisite for ZNE and PEC
  models). Runtime: `twirling.enable_gates`, `twirling.num_randomizations`.
- Twirl measurements too (random X before measure, flip the bit classically): readout error
  becomes a single scale factor per observable (TREX). Runtime: `twirling.enable_measure`.

## 6. Readout mitigation

| Method | Qubits | Calibration | Use |
|---|---|---|---|
| full matrix inversion | ≲ 10 | 2^n circuits | small registers, correlated readout |
| tensored (independent per qubit) | any | 2 circuits | quick, assumes no correlations |
| M3 (`mthree`) | 10s-100s | per-qubit or tensored cals, subspace-reduced solve | counts-based observables |
| TREX | any | twirled cals | expectation values (Runtime `resilience_level = 1`) |

Single-qubit Z with e01 = P(1|0), e10 = P(0|1): ⟨Z⟩ = (⟨Z⟩_meas - (e10 - e01)) / (1 - e01 - e10);
the denominator also inflates σ. M3: `mit = mthree.M3Mitigation(backend);
mit.cals_from_system(qubits); quasi = mit.apply_correction(counts, qubits); quasi.expval()`.
Calibrate on the same physical qubits within the same calibration window as the data.

## 7. Zero-noise extrapolation

- Scale noise by unitary folding G → G (G†G)^k (scale 1 + 2k): `mitiq.zne.scaling.fold_gates_at_random`,
  `fold_global`, `fold_all`; or by pulse stretching / PEA (probabilistic error amplification from a
  learned model). Use scale factors such as {1, 3, 5}.
- Fold after transpiling to the device ISA; a later optimising transpile cancels G†G.
- Extrapolators (Mitiq 0.4x factories): `LinearFactory`, `RichardsonFactory`, `ExpFactory`,
  `PolyFactory`, `AdaExpFactory`. Report at least two; ZNE is biased and the model choice matters.
- Variance: extrapolation is a weighted sum Σ w_i y_i. For scales (1, 3, 5) the weights are
  (1.083, 0.333, -0.417) for a least-squares line (σ × 1.21) and (1.875, -1.25, 0.375) for
  Richardson (σ × 2.28), before accounting for the smaller signal at high scale.

```python
from mitiq import zne
from mitiq.zne.inference import LinearFactory, RichardsonFactory, ExpFactory
for fac in (LinearFactory([1, 3, 5]), ExpFactory([1, 3, 5], asymptote=0.0), RichardsonFactory([1, 3, 5])):
    print(type(fac).__name__, zne.execute_with_zne(isa_circuit, executor, factory=fac))   # executor: circuit -> float
```

## 8. Probabilistic error cancellation and PEA

Learn a sparse Pauli-Lindblad model per twirled layer: Λ(ρ) = Π_k [w_k ρ + (1 - w_k) P_k ρ P_k],
w_k = (1 + e^{-2λ_k})/2. Inverting factor k costs γ_k = e^{2λ_k}; per layer γ_l = e^{2Σλ_k}; the
circuit needs γ_tot = Π_l γ_l and γ_tot² times the shots of an unmitigated estimate for equal σ.

| Layers × Σλ per layer | γ_tot | γ_tot² | Verdict |
|---|---|---|---|
| 10 × 0.05 | e^1 = 2.7 | 7.4 | fine |
| 20 × 0.05 | e^2 = 7.4 | 55 | feasible |
| 50 × 0.05 | e^5 = 148 | 2.2e4 | infeasible; use ZNE/PEA or a smaller circuit |

PEC is unbiased only if the learned model is right (drift breaks it); keep γ_tot² ≲ 1e2-1e3. PEA uses
the same model to amplify noise for ZNE (Runtime `resilience.zne.amplifier = "pea"`). Mitiq:
`pec.execute_with_pec(circuit, executor, representations=reps, num_samples=...)` with
`represent_operations_in_circuit_with_local_depolarizing_noise(circuit, noise_level)`.

## 9. Other methods

| Method | Idea | Cost / caveat |
|---|---|---|
| Clifford data regression (`mitiq.cdr.execute_with_cdr`) | fit noisy→exact map on near-Clifford training circuits | needs a classical simulator; bias if training set is unrepresentative |
| symmetry verification / post-selection | discard shots violating particle number, parity, S_z | honest and cheap; report the kept fraction |
| virtual distillation | estimate Tr(ρ^M O)/Tr(ρ^M) with M copies | M× qubits or deep circuits |
| Mitiq REM / DDD | `rem.execute_with_rem`, `ddd.execute_with_ddd` with rules `xx`, `yy`, `xyxy` | same physics as sections 5-6 |
| vendor tensor-network mitigation functions | classical post-processing with a learned noise model | check availability and assumptions |

## 10. Tooling

```python
from qiskit_ibm_runtime import EstimatorV2, EstimatorOptions        # option paths verified on 0.50
o = EstimatorOptions()
o.resilience_level = 1                                # TREX readout mitigation
o.resilience.zne_mitigation = True
o.resilience.zne.noise_factors = (1, 3, 5)
o.resilience.zne.extrapolator = ("exponential", "linear")
o.twirling.enable_gates = True; o.twirling.enable_measure = True; o.twirling.num_randomizations = 32
o.dynamical_decoupling.enable = True; o.dynamical_decoupling.sequence_type = "XpXm"
```

Executors return an expectation value and record shots; keep raw counts. Never submit QPU jobs
yourself: write the script and hand the submission (backend, shots, estimated QPU time) to the user.

## 11. Worked example: 8-qubit Ising Trotter circuit under FakeFez

Circuit: 4 Trotter steps of H = -Σ Z_iZ_{i+1} - Σ X_i (dt = 0.25) on 8 qubits, observable Z_4.
Exact ⟨Z_4⟩ = 0.31826. Transpiled to FakeFez (seed 11): 56 CZ, 208 RZ, 120 SX. Qiskit 2.6,
Aer 0.17.2, qiskit-ibm-runtime 0.50, `AerSimulator.from_backend(FakeFez())`, 20,000 shots per
circuit, 5 simulator seeds; readout corrected with the single-qubit formula from two calibration
circuits on the same physical qubit; ZNE by folding every CZ on the ISA circuit:

```python
def fold(circ, scale):                        # CZ -> CZ (CZ† CZ)^k on an ISA circuit
    out = circ.copy_empty_like()
    for ins in circ.data:
        out.append(ins.operation, ins.qubits, ins.clbits)
        if ins.operation.num_qubits == 2 and ins.operation.name != "barrier":
            for _ in range((scale - 1) // 2):
                out.append(ins.operation.inverse(), ins.qubits, ins.clbits)
                out.append(ins.operation, ins.qubits, ins.clbits)
    return out
x = np.array([1.0, 3.0, 5.0])                  # y = readout-corrected <Z_4> at each scale
lin  = np.polyval(np.polyfit(x, y, 1), 0.0)
rich = np.polyval(np.polyfit(x, y, 2), 0.0)
expo = np.exp(np.polyval(np.polyfit(x, np.log(y), 1), 0.0))
```

| Estimator | mean over 5 seeds | std | bias vs 0.31826 |
|---|---|---|---|
| raw | 0.2770 | 0.0066 | -0.041 |
| readout-corrected | 0.2777 | 0.0065 | -0.041 |
| scale 3 / scale 5 | 0.2176 / 0.1815 | 0.0070 / 0.0064 | - |
| ZNE linear | 0.2977 | 0.0072 | -0.021 |
| ZNE exponential | 0.3056 | 0.0078 | -0.013 |
| ZNE Richardson | 0.3166 | 0.0097 | -0.002 |

Reading: readout correction barely matters here (FakeFez readout error on this qubit ≈ 0.2%; on
hardware it is often 1-3%). The surviving signal 0.277/0.318 = 0.87 corresponds to an effective
0.25% error per CZ (0.9975^56 ≈ 0.87), the section 4 budget in reverse. Bias
falls from 0.041 to 0.002 while σ grows; theory predicts σ × 1.21 (linear) and × 2.28 (Richardson)
and a 5-seed std is itself ±35% uncertain, so quote the predicted σ. The extrapolators disagree by
0.019, which is the honest systematic error of this ZNE result.

## 12. Reporting rules

- Raw and mitigated values side by side, with shots, σ (statistical) and the spread across
  extrapolators or models (systematic), plus the overhead factor (γ², number of scales).
- State the noise-model assumptions (twirled Pauli noise, stationarity window, calibration time).
- Mitigation does not scale: its sampling cost is exponential in circuit volume. Never call it
  error correction or extrapolate its success to larger circuits.

## Pitfalls

- Folded circuits re-optimised by the transpiler, so every "scale" is scale 1.
- One extrapolator reported as if exact; ZNE error bars that omit the model spread.
- Readout calibration from another day or other qubits.
- PEC run with a stale noise model (bias returns silently) or with γ² beyond the shot budget.
- Noise model double-counting relaxation, or never validated against a measured benchmark.
- Mitigated values outside physical bounds (|⟨P⟩| > 1) reported without comment.

Related: `stabilizer-codes-surface-code`, `quantum-circuit-simulators`, `hamiltonian-simulation-methods`, `variational-quantum-algorithms`, hub `quantum-computing`
