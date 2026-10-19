---
name: quantum-computing
description: "Quantum computing working pack: state vectors and density matrices, qubit-ordering and phase conventions, gates and circuit compilation, shot budgets, algorithm selection with formulas (QFT, QPE, Grover, amplitude estimation, Shor, VQE, QAOA, HHL caveats, Hamiltonian simulation), noise models and error mitigation, stabilizer codes, surface code and decoders, fault-tolerant resource estimation, SDK snippets (Qiskit, Cirq, PennyLane, CUDA-Q, Stim) and simulator validation. Load for any quantum algorithm, circuit, QEC or quantum-advantage question."
when_to_use: "Designing or reviewing quantum circuits or algorithms, estimating qubits/T-count/runtime, choosing a simulator or SDK, debugging wrong measurement distributions, modelling noise, evaluating error-correction or advantage claims."
---

# Quantum computing

Quantum results go wrong in three predictable places: conventions (bit order, phase, units of
angle), statistics (finite shots read as exact numbers), and claims (a speedup that disappears once
input loading, readout or the best classical algorithm is counted). Every section below has a
check for one of these.

## 0. Triage

| Request | Section |
|---|---|
| Build or debug a circuit, wrong histogram | 1, 2, 3, 9 |
| Which algorithm, how many qubits/gates | 4, 7, [algorithms reference](references/algorithms.md) |
| Run on hardware, noisy results, mitigation | 5 |
| QEC code, decoder, threshold, logical error rate | 6, [error-correction reference](references/error-correction.md) |
| Code in an SDK | 8, [SDK snippets](references/sdk-snippets.md) |
| "Is this a quantum advantage?" | 10 |

## 1. States and conventions

| Object | Size | Memory (complex128) | Practical single-node limit |
|---|---|---|---|
| State vector, n qubits | 2^n amplitudes | 16 · 2^n bytes (30 qubits = 16 GiB, 34 = 256 GiB) | ~30-34 qubits CPU/GPU; ~40+ distributed |
| Density matrix | 4^n entries | 16 · 4^n bytes (15 qubits = 16 GiB) | ~14-16 qubits |
| Stabilizer tableau | O(n²) bits | tiny | millions of qubits (Clifford only, Stim) |
| MPS, bond dimension χ | O(n χ²) | depends on entanglement | 100s of qubits if χ stays small |

Bit ordering differs between SDKs and is the most common source of "wrong" results:

| SDK | Convention | Bitstring `'01'` on 2 qubits means |
|---|---|---|
| Qiskit | little-endian: qubit 0 is the rightmost character and least significant bit | qubit 0 = 1, qubit 1 = 0 |
| Cirq | order of the qubit list (default sorted); first qubit is the most significant | first qubit = 0, second = 1 |
| PennyLane | wire 0 is the most significant (leftmost) | wire 0 = 0, wire 1 = 1 |
| CUDA-Q, others | check | run the probe below |

Probe before trusting any pipeline: a circuit with only X on qubit 0 of 3 qubits; read which
character of the bitstring and which state-vector index (1 or 4) lights up. Put the probe in the
test suite.

Phase conventions: RX(θ) = exp(-iθX/2), RY, RZ likewise (Qiskit, Cirq `cirq.rx`, PennyLane).
`cirq.XPowGate(exponent=t)` = X^t differs from rx(πt) by a global phase, which becomes a relative
phase once the gate is controlled. Qiskit `RZZ(θ) = exp(-iθ Z⊗Z/2)`. Angles are radians everywhere.

Fidelity between pure states |⟨ψ|φ⟩|² ignores global phase; compare state vectors with it, never
with elementwise equality. For mixed states use Uhlmann fidelity or trace distance
½‖ρ - σ‖₁.

## 2. Gates and circuits

- Universal sets: {Clifford (H, S, CNOT)} + T. Cliffords alone are classically simulable
  (Gottesman-Knill), so T-count (or Toffoli/CCZ count) is the fault-tolerant cost metric.
- Arbitrary single-qubit rotation to precision ε costs ≈ 3 log2(1/ε) T gates with
  Ross-Selinger gridsynth (e.g. ε = 1e-10 → ~100 T); repeat-until-success and catalysed rotations
  can reduce this.
- Near-term cost metrics: two-qubit gate count and two-qubit depth after transpilation to the
  device's native gates and coupling map. Report them post-transpile, with optimisation level and
  seed, never pre-transpile.
- Useful identities: HZH = X; CZ is symmetric; CNOT = (I⊗H) CZ (I⊗H); SWAP = 3 CNOTs; Toffoli =
  6 CNOT + 7 T/T† (+ H); a controlled-U costs at most 2 CNOT + single-qubit gates for U in SU(2).
- Measurement in another basis: X basis = H then Z-measure; Y basis = S† H then Z-measure.
- Mid-circuit measurement and feed-forward are hardware-dependent; check backend support before
  designing around them.

## 3. Measurement statistics and shot budgets

| Quantity | Standard error with N shots |
|---|---|
| Probability p of an outcome | sqrt(p(1 - p)/N), worst case 0.5/√N |
| Pauli expectation ⟨P⟩ ∈ [-1, 1] | sqrt((1 - ⟨P⟩²)/N), worst case 1/√N |
| H = Σ c_j P_j, groups measured separately | sqrt(Σ c_j² (1 - ⟨P_j⟩²)/N_j) |

Optimal shot allocation N_j ∝ |c_j| sqrt(1 - ⟨P_j⟩²); total shots for precision ε is about
(Σ_j |c_j| sqrt(1 - ⟨P_j⟩²))² / ε² ≤ λ²/ε² with λ = Σ|c_j|. Worked number: molecular Hamiltonian
with λ = 10 Ha at chemical accuracy ε = 1.6 mHa needs up to (10/0.0016)² ≈ 3.9e7 shots per energy
evaluation before grouping commuting terms; qubit-wise commuting grouping or classical shadows
typically cut this by 1-2 orders of magnitude. Do this arithmetic before proposing a VQE.

Comparing a measured histogram with an ideal distribution: total variation distance
TVD = ½ Σ|p - q|. A perfect device still shows TVD > 0 at finite N (for a uniform ideal
distribution over K ≫ 1 outcomes, E[TVD] ≈ sqrt(K/(2πN))). For a general distribution, simulate
N-shot sampling from the ideal distribution 1000 times to get the null distribution and compare
the hardware TVD with its 95th percentile.

## 4. Algorithm selection

Formulas and circuit constructions: [algorithms reference](references/algorithms.md).

| Algorithm | Speedup and cost | Use / caveat |
|---|---|---|
| QFT | O(n²) gates exact, O(n log n) approximate (drop R_m for m > log2 n + 2) | subroutine; not useful alone (output is in phases) |
| Phase estimation | t = n + ceil(log2(2 + 1/(2δ))) ancillas for n bits w.p. ≥ 1 - δ; needs controlled-U^(2^k) | energy estimation, Shor; iterative/Bayesian QPE uses 1 ancilla |
| Grover / amplitude amplification | k = floor(π/(4θ)), sin θ = sqrt(M/N); quadratic speedup | unstructured search; overshooting k lowers success; oracle cost usually dominates |
| Amplitude estimation | error O(1/k) with k oracle calls vs O(1/√k) classical sampling | Monte Carlo pricing; deep coherent circuits; iterative/MLE variants reduce depth |
| Shor | polynomial factoring / discrete log | RSA-2048 estimates: ~20M noisy qubits, 8 h (Gidney-Ekerå 2019); under 1M noisy qubits, under a week (Gidney 2025), both at 0.1% gate error and 1 µs cycles |
| VQE | heuristic, no proven speedup | barren plateaus, shot cost (section 3), noise; benchmark vs CCSD(T)/DMRG/FCI |
| QAOA | heuristic, no proven general advantage | compare against Goemans-Williamson (0.878 for MaxCut), simulated annealing, Gurobi on the same instances |
| HHL / QLSA | poly(log N, κ, log 1/ε) under strong assumptions | read the fine print: state preparation of b, sparsity/block-encoding of A, condition number κ, output is a state not a vector; low-rank cases dequantized (Tang 2018) |
| Hamiltonian simulation | Trotter, qDRIFT, LCU, qubitization/QSVT | the strongest candidate for useful advantage (chemistry, materials); choose method by λ, L, t, ε below |

Hamiltonian simulation method choice (H = Σ_{j=1..L} c_j P_j, λ = Σ|c_j|):

| Method | Cost scaling (gates or queries) | Prefer when |
|---|---|---|
| 1st-order Trotter | error ≤ (t²/2r) Σ‖[H_j, H_k]‖ for r steps | early fault-tolerant, commuting-heavy H, small circuits |
| 2nd/4th-order Trotter-Suzuki | error O(t^(p+1)/r^p) with nested commutators | default product formula; real error is often 10-1000x below bounds, measure it on small n |
| qDRIFT | O(λ² t² / ε) samples, independent of L | many small terms (L huge, λ moderate) |
| Qubitization + QSP/QSVT | O(λ t + log(1/ε)) queries to block encoding | fault-tolerant phase estimation of chemistry (THC/double-factorised encodings) |

## 5. Noise and mitigation

Channels (Kraus form ρ → Σ K_i ρ K_i†, Σ K_i†K_i = I):

| Channel | Physical origin | Parameters |
|---|---|---|
| Amplitude damping | energy relaxation | γ = 1 - exp(-t/T1) |
| Pure dephasing | low-frequency noise | 1/T_φ = 1/T2 - 1/(2 T1); always T2 ≤ 2 T1 |
| Depolarizing | twirled gate error | ρ → (1 - p)ρ + p I/d |
| Readout error | discrimination | confusion matrix P(read j given prepared i), often asymmetric (1 → 0 worse) |
| Coherent over-rotation | calibration | accumulates quadratically in infidelity; twirl it into Pauli noise |
| Crosstalk, leakage | spectator coupling, non-qubit levels | not captured by single-qubit models; leakage needs reset/LRUs |

Fidelity bookkeeping: average gate fidelity F_avg = (d F_pro + 1)/(d + 1); randomized
benchmarking decay A p^m + B gives error per Clifford r = (d - 1)(1 - p)/d. Rough circuit success
≈ Π (1 - e_gate) over all gates (and idle errors): 200 two-qubit gates at 0.5% error leave
≈ 0.37 signal. If the estimate is below ~0.1 the circuit is in the noise floor; redesign before
running.

| Mitigation | Cost | Notes |
|---|---|---|
| Readout mitigation (matrix inversion, M3, TREX) | calibration circuits | always on for expectation values |
| Dynamical decoupling | none (idle slots) | suppresses dephasing on idle qubits; use device-aware sequences (XY4) |
| Pauli twirling | more circuit instances | turns coherent errors into stochastic; prerequisite for ZNE/PEC models |
| Zero-noise extrapolation | 3-5 noise scales × shots | biased; gate folding or pulse stretching; extrapolate linear/exponential and report both |
| Probabilistic error cancellation | shots × γ_tot², γ_tot = Π γ_i | unbiased given an accurate noise model; exponential in circuit volume, viable while γ_tot² ≲ 1e2-1e3 |
| Symmetry verification / post-selection | discards shots | particle number, parity; cheap and honest |

Mitigation reduces bias at exponential sampling cost; it does not scale. Report raw and mitigated
values side by side with shot counts.

## 6. Error correction (summary)

Details, code tables and Stim/PyMatching pipeline: [error-correction reference](references/error-correction.md).

- [[n, k, d]] stabilizer code: n physical, k logical, distance d corrects floor((d-1)/2) errors.
- Surface code (rotated): 2d² - 1 physical qubits per logical patch (d² data + d² - 1 measure),
  threshold ~1% under circuit-level depolarizing noise, logical error per round
  p_L ≈ A (p/p_th)^((d+1)/2) with A ≈ 0.1, p_th ≈ 0.01.
- Λ = p_L(d)/p_L(d+2) is the experimental figure of merit; Google's Willow memory experiment
  (2024) reported Λ ≈ 2.1 through d = 7 (≈0.14% logical error per round). Λ > 1 means below
  threshold, and Λ sets the bill: going from 1.4e-3 to 1e-12 per round takes log10(1.4e9)/log10(Λ)
  distance steps of 2, i.e. d ≈ 69 (~9,500 physical qubits per patch) at Λ = 2 but d ≈ 27 (~1,460)
  at Λ = 10.
- Decoders: MWPM (PyMatching 2, sparse blossom) default for surface codes; union-find for speed;
  BP+OSD for qLDPC codes (e.g. IBM bivariate bicycle [[144, 12, 12]] gross code); neural decoders
  (AlphaQubit) for correlated hardware noise. Real-time decoding must keep up with ~1 µs rounds.
- Non-Clifford gates via magic states: 15-to-1 distillation, or magic state cultivation
  (Gidney-Shutty-Jones 2024), consumed by lattice surgery.

## 7. Resource estimation procedure

1. Write the algorithm as logical operations: logical qubits Q, Toffoli/T count N_T, logical depth.
   Include arithmetic ancillas and QROM/block-encoding cost; these usually dominate.
2. Pick hardware assumptions explicitly: physical error p, code cycle time t_c (≈1 µs
   superconducting, ms-scale for ions/atoms), connectivity.
3. Choose code distance d so the total logical failure budget holds:
   `(Q_patches · D_steps · d) · p_L(d) ≤ ε_total` where D_steps = logical time steps (each d rounds).
4. Physical qubits ≈ Q_patches · 2d² (data + routing) + magic-state factories.
5. Runtime ≈ D_steps · d · t_c, unless T-state production is the bottleneck: then
   N_T / (factory output rate).
6. Cross-check with a tool: Microsoft QDK resource estimator (`pip install "qdk[qre]"`;
   `qdk.qre.estimate`; check the installed version's docs), Google Qualtran,
   or published estimates for the same problem class. Report assumptions in a table.

Worked example. Q = 100 logical qubits, doubled to 200 patches for routing; D_steps = 1e8;
p = 1e-3, p_th = 1e-2, ε_total = 0.01. Need 200 · 1e8 · d · 0.1 · 10^(-(d+1)/2) ≤ 0.01, i.e.
d · 10^(-(d+1)/2) ≤ 5e-12. d = 21 gives 21 · 1e-11 = 2.1e-10 (fails); d = 23: 2.3e-11 (fails);
d = 25: 2.5e-12 (passes). Patch size 2·25² - 1 = 1249, so ≈ 2.5e5 physical qubits before factories;
runtime 1e8 · 25 · 1 µs = 2500 s ≈ 42 min if factories supply 1e8 T states in that time
(4e4 T/s). State the result as "~3e5 physical qubits, ~1 h, at p = 1e-3", not as a precise count.

## 8. SDK rules

- Read the installed version first (`python -c "import qiskit; print(qiskit.__version__)"` and
  likewise for cirq, pennylane, cudaq, stim) and verify APIs with context7
  (`mcp__context7__resolve-library-id` -> `mcp__context7__query-docs`); these SDKs break APIs between
  minor versions (Qiskit 1.0 removed `execute`, 2.0 removed BackendV1 and pulse; PennyLane has moved
  shot configuration between releases).
- Use the primitives model in Qiskit (Sampler/Estimator V2, `StatevectorSampler`,
  `StatevectorEstimator` locally) and transpile to ISA circuits with `generate_preset_pass_manager`.
- Never submit to a cloud QPU yourself (`qiskit_ibm_runtime`, Braket, Azure Quantum): it spends paid
  quota on the user's account and cannot be undone. Write the ready-to-run job script to your out_dir
  and return the submission (backend, shots, estimated QPU time) as an Open doubt for the user.
- Fix seeds (simulator, transpiler) in every test and report them.
- Snippets for each SDK: [SDK snippets](references/sdk-snippets.md).

## 9. Simulators and validation

| Need | Simulator |
|---|---|
| Exact amplitudes ≤ ~30 qubits | statevector: Qiskit Aer, qsim, PennyLane lightning, CUDA-Q `nvidia` target (cuStateVec) |
| Noise with arbitrary channels ≤ ~15 qubits | density matrix (Aer `method="density_matrix"`, `cirq.DensityMatrixSimulator`, `default.mixed`) |
| Noise at larger n | trajectories (Monte Carlo wavefunction) on statevector |
| Clifford circuits, QEC | Stim (stabilizer), sampling billions of shots |
| Low entanglement, 50-1000 qubits | MPS / tensor networks (Aer `matrix_product_state`, quimb, CUDA-Q `tensornet`) |
| Few T gates | extended stabilizer / stabilizer-rank methods |

Validation checklist:
- [ ] Endianness probe passes (section 1).
- [ ] Known-answer tests: Bell state (|00⟩ + |11⟩)/√2, GHZ, QFT of a basis state gives uniform
      magnitudes with linear phases, Grover success probability matches sin²((2k+1)θ).
- [ ] Unitarity: ‖U†U - I‖ < 1e-10 for any matrix you build by hand.
- [ ] Equivalence after compilation: `Operator(qc).equiv(Operator(tqc))` for ≤ ~12 qubits
      (accounting for the final layout), MQT QCEC for larger circuits.
- [ ] Cross-simulator check: same circuit in two SDKs, compare probabilities (TVD < 1e-9 exact).
- [ ] Sampling statistics: measured vs ideal TVD within the simulated null distribution.
- [ ] Noise model sanity: depolarizing p → 0 reproduces the ideal result; p → max gives uniform.

## 10. Claims hygiene

Before accepting "quantum advantage" or "exponential speedup", answer in writing:
1. What is the best classical algorithm, including heuristics, tensor networks, Pauli-path and
   Clifford-perturbation simulation, and dequantized algorithms? Advantage claims for sampling
   tasks have repeatedly been narrowed by improved classical simulation.
2. Are input loading (state preparation, QRAM) and output readout counted? Exponential speedups
   that need QRAM or full-state tomography usually vanish.
3. Is the comparison at equal accuracy and with error bars, on the same instances?
4. Is the complexity statement about BQP vs BPP in the oracle model (provable separations exist)
   or about a concrete problem (no unconditional separation is known)?
5. Does the estimate assume fault tolerance? Then quote physical qubits and runtime (section 7).

Label each claim Proven (cite theorem), Evidence (experiment/numerics with error bars), or
Conjecture. Never let NISQ-era heuristic results stand in for fault-tolerant speedups.

## 11. Worked example: Grover on 3 qubits

N = 8, M = 1: θ = arcsin(1/√8) = 0.3614 rad; k = floor(π/(4θ)) = 2; success sin²(5θ) = 0.945.
One more iteration (k = 3) drops it to sin²(7θ) = 0.330. On a simulator with 10,000 shots expect
the marked state at 0.945 ± 0.0023 (1σ). Two-qubit gate count after decomposing each 3-qubit
oracle and diffuser (each needs a CCZ, 6 CNOTs) is ≥ 24 CNOTs for k = 2 before routing; at 0.5%
two-qubit error the fidelity bound ≈ 0.995^24 ≈ 0.89 before routing and readout, so a hardware
run should still show the marked state clearly but well below 0.945. Report ideal, noisy-sim and
hardware numbers together.

## Quality gate before returning

- [ ] Conventions stated: bit order, angle convention, basis of measurement.
- [ ] Every probability or expectation value carries shots and a standard error.
- [ ] Gate counts are post-transpilation with device, optimisation level and seed.
- [ ] Resource estimates list p, t_c, d, factory assumptions and the tool used.
- [ ] Advantage-related statements pass the five questions of section 10.
- [ ] SDK code was run (or checked against current docs via context7) with versions recorded.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `variational-quantum-algorithms` | proposing, debugging or reviewing VQE, QAOA or QML training |
