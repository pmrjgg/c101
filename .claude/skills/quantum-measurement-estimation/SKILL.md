---
name: quantum-measurement-estimation
description: "Measurement statistics and estimator design for quantum experiments: shot budgets and standard errors, optimal shot allocation, commuting-group measurement, classical shadows, confidence intervals and bootstrap, and distribution comparison (TVD, Hellinger, heavy output, XEB). Load when choosing shots, estimating observables or judging whether a histogram matches theory."
when_to_use: "Choosing shot counts or a precision target; error bars on probabilities, Pauli expectations or energies; 'is this difference real or shot noise', 'how many shots for chemical accuracy'; grouping Hamiltonian terms for measurement; classical shadows; bootstrap or delta-method errors for fidelities, ratios and mitigated values; comparing a measured histogram with theory (TVD, Hellinger, chi-square); heavy-output and XEB benchmark statistics; GHZ or state-fidelity estimates."
---

# Measurement statistics and estimation

Every number read off a quantum device is an estimator. State its shots, its sigma and the null
distribution it is compared against; the formulas below give all three. Values marked *measured*
come from Qiskit 2.6 / Aer 0.17 / NumPy simulations with fixed seeds.

Deep material: [classical shadows: estimator code, test run and sample-complexity table](references/classical-shadows.md)

## 1. Standard errors

| Quantity | sigma with N shots | Worst case |
|---|---|---|
| outcome probability p | sqrt(p(1 - p)/N) | 0.5/sqrt(N) |
| Pauli expectation ⟨P⟩ | sqrt((1 - ⟨P⟩^2)/N) | 1/sqrt(N) |
| H = Σ_j c_j P_j, one term per setting | sqrt(Σ_j c_j^2 (1 - ⟨P_j⟩^2)/N_j) | λ/sqrt(N) with λ = Σ abs(c_j) |
| H measured in groups g with N_g shots | sqrt(Σ_g Var_g / N_g), Var_g = per-shot variance of the group's summed estimator | |

Near p = 0 or 1 the normal interval fails; use the Wilson interval:

```python
def wilson(k, N, z=1.96):
    p = k / N; den = 1 + z*z/N
    centre = (p + z*z/(2*N)) / den
    half = z * np.sqrt(p*(1 - p)/N + z*z/(4*N*N)) / den
    return centre - half, centre + half
# measured: 3 counts in 8192 shots -> Wilson [1.25e-4, 1.08e-3]; the normal interval [-4.8e-5, 7.8e-4] goes negative
```

## 2. Shot allocation

Minimising Var = Σ_j c_j^2 sigma_j^2 / N_j at fixed Σ_j N_j gives N_j proportional to abs(c_j) sigma_j and
a total of N = (Σ_j abs(c_j) sigma_j)^2 / ε^2 <= λ^2/ε^2 for target precision ε.

```python
def allocate(c, sigma, eps):
    w = np.abs(c) * sigma
    N_total = (w.sum() / eps) ** 2
    return np.ceil(N_total * w / w.sum()).astype(int), N_total
```
Worked number: λ = 10 Ha at chemical accuracy ε = 1.6 mHa needs up to (10/0.0016)^2 = 3.9e7 shots per
energy evaluation before grouping. A parameter-shift gradient with P parameters costs (2P + 1) times
that per optimiser step (`variational-quantum-algorithms`). The sigma_j are unknown at the start:
spend a pilot (about 1000 shots per group), estimate sigma_j, then allocate; or assume sigma_j = 1.

## 3. Grouping commuting terms

| Grouping | Measurement circuit | Groups | Variance |
|---|---|---|---|
| none | per-term basis change | L terms | adds over terms |
| qubit-wise commuting (QWC) | local rotations only (H, or S-dagger then H) | fewer | includes covariances inside each group |
| general commuting | Clifford diagonalisation circuit with extra 2q gates | fewest | same, plus the extra gate noise |

Tools: Qiskit `SparsePauliOp.group_commuting(qubit_wise=True)`; PennyLane
`qml.pauli.group_observables(ops, coeffs, grouping_type="qwc", method="lf")` (types "qwc",
"commuting", "anticommuting"). H2/STO-3G (Jordan-Wigner) has 15 terms in 5 QWC groups (measured).
Sorted insertion (Crawford et al. 2021): sort terms by abs(c_j) descending, put each into the first group
it commutes with, otherwise open a new group; it usually beats graph colouring on variance.

Covariances inside a group can raise or lower the variance; never drop them. Computing the group
estimator per shot includes them automatically:

```python
def group_energy(bits, terms):
    """bits: (shots, n) 0/1 array measured after the group's basis rotation.
    terms: list of (coeff, support qubit indices). Returns mean and standard error."""
    vals = np.zeros(len(bits))
    for c, sup in terms:
        vals += c * (1 - 2 * (bits[:, sup].sum(axis=1) % 2))
    return vals.mean(), vals.std(ddof=1) / np.sqrt(len(vals))
```

## 4. Classical shadows

Random single-qubit Pauli bases per shot; each snapshot is an unbiased estimator of the state. A
k-local Pauli is estimated from the snapshots whose bases match it on its support (each match
contributes 3^k times the product of outcomes), combined with a median of means. For M observables
of locality k, N is about O(3^k log(M/δ)/ε^2) (Huang-Kueng-Preskill 2020).

| Situation | Use |
|---|---|
| few observables (under about 10) or high-weight ones | direct grouped measurement |
| hundreds of low-weight Paulis (k <= 3), e.g. all 2-local correlators | random Pauli shadows |
| fidelity with a known pure state | Clifford shadows or direct fidelity estimation (deep random Cliffords) |
| many known observables | derandomised (Huang et al. 2021) or locally biased (Hadfield et al. 2022) shadows |

PennyLane has `qml.classical_shadow(wires)` and `qml.shadow_expval(H)`. Code and a measured test
(GHZ-4, 20,000 snapshots: Z0Z1 = 0.988 ± 0.020, weight-4 XXXX = 1.013 ± 0.063) are in the reference
file.

## 5. Runtime-side helpers

- Qiskit runtime EstimatorV2 groups commuting terms itself and maps precision p to about 1/p^2 shots
  (measured in local mode: precision 0.01 gave `metadata["shots"] = 10000`). Read the metadata for
  the shots actually used (`qiskit-primitives-runtime`).
- `StatevectorEstimator(default_precision=p)` adds Gaussian noise but returns `stds = 0` (measured,
  Qiskit 2.6): take sigma from `metadata["target_precision"]`.
- Sampler `BitArray`: `expectation_values(["ZZ", "ZI"])` for Z-type observables, `slice_bits`,
  `get_counts`, `to_bool_array(order="big")`; compute sigma yourself as sqrt((1 - ⟨P⟩^2)/N).

## 6. Derived quantities

Delta method: for f(x) with estimated covariance Σ, Var f is about ∇f^T Σ ∇f. Ratio R = A/B:
(sigma_R/R)^2 = (sigma_A/A)^2 + (sigma_B/B)^2 - 2 Cov(A, B)/(AB).

Bootstrap (use it for anything nonlinear: fidelities, fits, mitigated values): resample the shots of
every setting multinomially from its observed frequencies, re-run the whole pipeline (mitigation and
fits included), at least 1000 resamples; sigma = std, 95% CI = 2.5th and 97.5th percentiles.

```python
def bootstrap(counts_list, stat, N, B=1000, seed=7):
    rng = np.random.default_rng(seed); out = []
    for _ in range(B):
        res = []
        for c in counts_list:
            keys = list(c); p = np.array([c[k] for k in keys]) / N
            res.append(dict(zip(keys, rng.multinomial(N, p))))
        out.append(stat(res))
    return np.std(out, ddof=1), np.percentile(out, [2.5, 97.5])
```
A mitigated value never appears without its inflated sigma (ZNE and PEC amplify variance;
`quantum-noise-mitigation`).

## 7. Comparing distributions

- TVD = 1/2 Σ abs(p - q); Hellinger fidelity (Σ sqrt(p q))^2 via
  `qiskit.quantum_info.hellinger_fidelity(counts_a, counts_b)`; KL divergence only with smoothing
  (pseudo-count 0.5) when q has zeros.
- A perfect device still shows TVD > 0 at finite N. Uniform ideal over K outcomes: E[TVD] is about
  sqrt(K/(2πN)) (measured, K = 64, N = 8192: formula 0.0353, simulation 0.0351).
- General ideal distribution: build the null by sampling N shots from the ideal 1000 times and
  compare the measured TVD with the null's 95th percentile.

```python
def tvd(p, q):
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0) - q.get(k, 0)) for k in keys)

def tvd_null(ideal, N, reps=1000, seed=0):
    rng = np.random.default_rng(seed); keys = list(ideal); pr = np.array([ideal[k] for k in keys])
    return np.percentile([tvd(dict(zip(keys, rng.multinomial(N, pr) / N)), ideal) for _ in range(reps)], 95)
```

## 8. Benchmark statistics

- Heavy-output probability (quantum volume): heavy outputs are bitstrings whose ideal probability is
  above the median; the ideal value approaches (1 + ln 2)/2 = 0.85 for Porter-Thomas outputs. A width
  passes when the one-sided 97.5% confidence bound on the heavy-output probability exceeds 2/3.
- Linear cross-entropy benchmarking: F = 2^n ⟨p_ideal(x)⟩ over the samples, minus 1; F = 1 ideal and
  0 for uniform noise; sigma is about 1/sqrt(N) for Porter-Thomas outputs (1e6 samples give
  sigma 1e-3). It needs p_ideal(x) for every sample: say when that requires a large classical
  simulation (`quantum-circuit-simulators`).

## 9. Hypothesis tests

- Chi-square or G-test on counts: `scipy.stats.chisquare(obs, f_exp)`,
  `scipy.stats.power_divergence(obs, f_exp, lambda_="log-likelihood")`; at least 5 expected counts
  per bin (merge rare bins); degrees of freedom = bins - 1 - fitted parameters.
- Single probability against theory: flag abs(p_hat - p) > 4 sigma (4, not 2, because many quantities
  get inspected).
- Scans over many settings: Bonferroni (α/m) or Holm step-down correction.

## 10. Sparse outputs at many qubits

Beyond about 20 qubits most bitstrings appear once, so histograms carry no information per entry.
Estimate marginals and correlators straight from the bit array:

```python
b = np.asarray(ba.to_bool_array(order="big"), dtype=np.int8)   # check the column-to-qubit order on a known state
z = 1 - 2 * b                                                    # +-1 per shot and column
mean_z = z.mean(axis=0)
zz = (z.T @ z) / len(z)                                          # all two-point correlators
connected = zz - np.outer(mean_z, mean_z)
```
Memory: 1e6 shots x 100 qubits is 12.5 MB as packed bits, 100 MB as bytes, and far more as a dict
of strings, so avoid `get_counts()` at large n.

## 11. Worked example: 6-qubit GHZ fidelity with a bootstrap error

F = ⟨GHZ|ρ|GHZ⟩ = (P + C)/2, where P = p(000000) + p(111111) and C is the amplitude of the parity
oscillation ⟨⊗_k (cos φ X + sin φ Y)⟩ = C cos(nφ + φ_0). Measuring cos φ X + sin φ Y on each qubit is
RZ(-φ) then H then a Z measurement. Setup: GHZ-6 (H plus a CX chain); Aer noise with 1% two-qubit
depolarizing, 0.1% one-qubit, 1.5% symmetric readout; 8192 shots per setting; one population setting
plus K = 8 phases φ_j = 2πj/(nK).

```python
import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error, ReadoutError

nm = NoiseModel()
nm.add_all_qubit_quantum_error(depolarizing_error(0.01, 2), ["cx"])
nm.add_all_qubit_quantum_error(depolarizing_error(0.001, 1), ["h", "rz", "sx", "x"])
nm.add_all_qubit_readout_error(ReadoutError([[0.985, 0.015], [0.015, 0.985]]))
sim = AerSimulator(noise_model=nm, seed_simulator=11)
n, N, K = 6, 8192, 8

def ghz():
    qc = QuantumCircuit(n); qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    return qc

phis = [2 * np.pi * j / (n * K) for j in range(K)]
circs = [ghz()]; circs[0].measure_all()
for f in phis:
    qc = ghz(); qc.rz(-f, range(n)); qc.h(range(n)); qc.measure_all(); circs.append(qc)
counts = sim.run(transpile(circs, basis_gates=["cx", "rz", "sx", "x", "h"], optimization_level=0),
                 shots=N).result().get_counts()

def fidelity(cs):
    P = (cs[0].get("0" * n, 0) + cs[0].get("1" * n, 0)) / N
    par = np.array([sum(v * (-1) ** k.count("1") for k, v in c.items()) / N for c in cs[1:]])
    A = np.column_stack([np.cos(n * np.array(phis)), np.sin(n * np.array(phis))])
    a, b = np.linalg.lstsq(A, par, rcond=None)[0]
    return (P + np.hypot(a, b)) / 2

F = fidelity(counts)
sigma, ci = bootstrap(counts, fidelity, N)                  # section 6
print(F, sigma, (F - 0.5) / sigma)
```

Measured:

| Quantity | Value |
|---|---|
| populations P | 0.8851 |
| coherence C (parity amplitude) | 0.7775 |
| fidelity F = (P + C)/2 | 0.8313 |
| bootstrap sigma (1000 resamples) | 0.0026 |
| z = (F - 0.5)/sigma | 125, so F > 0.5 (genuine 6-partite entanglement) far beyond 3 sigma |
| population TVD against the ideal 50/50 | 0.1149, against a finite-N null 95th percentile of 0.011 |
| Hellinger fidelity of the populations | 0.8851 |

Reading: the TVD is ten times its null, so the deviation is device noise, not shot noise.
Population-only metrics (TVD, Hellinger) miss coherence: C < P shows dephasing that the histogram
cannot see, which is why F needs the parity settings. Budget: sigma = 0.0026 from 9 x 8192 shots;
resolving F = 0.83 against 0.84 at 3 sigma needs sigma <= 0.0033, so this budget suffices.

## 12. Pitfalls

- Shot-noise fluctuations read as signal: always show sigma or the null distribution.
- The same shots reused for optimisation and reporting (winner's curse, optimistic bias): re-measure
  the chosen parameters with fresh shots.
- Covariance inside measurement groups ignored, so sigma is wrong in either direction.
- TVD or Hellinger quoted without the finite-N null.
- Normal-approximation intervals at p near 0 or 1.
- Mitigated values reported without their inflated sigma.
- Bootstrap that resamples final numbers instead of shots, which underestimates sigma.
- Many settings scanned without a multiple-comparison correction.

Related: `quantum-noise-mitigation`, `variational-quantum-algorithms`, `qiskit-primitives-runtime`, `pennylane-differentiable`, `quantum-circuit-simulators`, hub `quantum-computing`
