---
name: quantum-algorithm-primitives
description: "Textbook quantum algorithm building blocks with formulas, circuits and known-answer tests: QFT and approximate QFT, phase estimation (standard, iterative, Bayesian, Hadamard test), Grover and amplitude amplification, quantum counting, amplitude-estimation variants, and Shor order finding. Load when designing, implementing or debugging these algorithms."
when_to_use: "Implementing or debugging QFT, phase estimation (QPE, iterative, Bayesian, Hadamard test), Grover search, amplitude amplification, quantum counting, amplitude estimation (canonical, MLAE, IAE) or Shor order finding; 'QPE returns the wrong phase', 'Grover success lower than expected', 'how many iterations', 'bit order reversed after the QFT'; sizing ancilla registers and oracle calls; deciding whether a quadratic speedup survives the oracle cost; writing known-answer tests for these circuits."
---

# Quantum algorithm primitives

Each primitive is specified by a formula, a circuit with its gate count, and a known-answer test that
must pass before the primitive is used inside anything larger. Values marked *measured* come from
Qiskit 2.6.0 statevector runs.

## 1. Quantum Fourier transform

QFT|j⟩ = N^(-1/2) Σ_k e^(2πi jk/N) |k⟩ with N = 2^n.

Circuit: for each qubit from the most significant down, an H and then controlled-R_m from each less
significant qubit, R_m = diag(1, e^(2πi/2^m)), m = 2..n; finally bit reversal. Count: n(n+1)/2 gates
(n H + n(n-1)/2 controlled phases at 2 CNOTs each) and floor(n/2) SWAPs.

Approximate QFT: drop R_m for m > m_max with m_max about log2 n + 2; error O(n 2^(-m_max)) and
O(n log n) gates (Coppersmith 1994; Barenco et al. 1996). Before a measurement, replace the final
SWAPs by relabelling the classical bits.

```python
import numpy as np
from qiskit.circuit.library import QFTGate
from qiskit.quantum_info import Statevector
n, N = 3, 8
ok = all(np.allclose(Statevector.from_int(j, N).evolve(QFTGate(n)).data,
                     np.exp(2j * np.pi * j * np.arange(N) / N) / np.sqrt(N)) for j in range(N))
print(ok)     # measured True: QFTGate is e^(+2 pi i jk/N) on little-endian integers, swaps included
```
Run this check whenever you mix SDKs or hand-written QFTs; a failure means a sign flip (you have
the inverse) or a missing bit reversal.

## 2. Phase estimation

U|u⟩ = e^(2πiφ)|u⟩. Circuit: t ancillas in |+⟩, controlled-U^(2^k) from ancilla k, inverse QFT,
measure m, estimate φ = m/2^t.

| Fact | Formula |
|---|---|
| ancillas for n bits with probability >= 1 - δ | t = n + ceil(log2(2 + 1/(2δ))) |
| φ not representable in t bits | the best t-bit estimate has probability >= 4/π^2 = 0.405 |
| total controlled evolution | Σ_k 2^k τ = (2^t - 1) τ, so precision ε costs about 1/ε (Heisenberg scaling) |
| input Σ_i a_i\|u_i⟩ | outcome φ_i with probability \|a_i\|^2, so a ground state with overlap \|a_0\|^2 needs about 1/\|a_0\|^2 repetitions |

```python
from qiskit import QuantumCircuit
from qiskit.primitives import StatevectorSampler
q = QuantumCircuit(4, 3)
q.x(3); q.h(range(3))                         # target in eigenstate |1> of T, phase 1/8
for k in range(3):
    q.cp(2 * np.pi * (1/8) * 2**k, k, 3)      # controlled-T^(2^k), built directly as a phase
q.append(QFTGate(3).inverse(), range(3)); q.measure(range(3), range(3))
print(StatevectorSampler(seed=1).run([q], shots=1000).result()[0].data.c.get_counts())
# measured {'001': 1000}: m = 1, phi = 1/8
```
Ancilla k controls U^(2^k), so ancilla 0 is the least significant bit, which matches Qiskit's
little-endian readout. The library function `qiskit.circuit.library.phase_estimation(num_evaluation_qubits, unitary)`
exists in 2.6; run the same T-gate test on it before use.

## 3. Low-ancilla variants

Iterative (Kitaev) phase estimation, one ancilla, bits read least significant first. Write
φ = 0.φ_1 φ_2 ... φ_t in binary. For k = t down to 1: ancilla to |+⟩, controlled-U^(2^(k-1)), phase
correction ω_k = -2π Σ_{j=k+1..t} φ_j 2^(-(j-k+1)) on the ancilla, H, measure; the outcome is φ_k
(deterministic when φ has exactly t bits).

```python
phi, t, bits = 5/8, 3, {}
for k in range(t, 0, -1):
    w = -2 * np.pi * sum(bits[j] * 2.0 ** (-(j - k + 1)) for j in range(k + 1, t + 1))
    qc = QuantumCircuit(2); qc.x(1); qc.h(0)
    qc.cp(2 * np.pi * phi * 2 ** (k - 1), 0, 1)        # controlled-U^(2^(k-1)), U = P(2 pi phi)
    qc.p(w, 0); qc.h(0)
    bits[k] = int(round(Statevector(qc).probabilities([0])[1]))
print([bits[k] for k in range(1, t + 1)])              # measured [1, 0, 1]: phi = 0.101 binary = 5/8
```
On hardware each bit is a mid-circuit measurement with feed-forward (`qc.if_test`), or a separate
circuit per bit with the correction computed classically.

Noisy, early fault-tolerant hardware: Bayesian phase estimation (Wiebe-Granade 2016), robust phase
estimation (Kimmel-Low-Yoder 2015) and statistical, Heisenberg-limited single-ancilla methods
(Lin-Tong 2022) replace the QFT with classical inference over many short circuits.

Hadamard test: ancilla in |+⟩, controlled-U, H, measure. P(0) = (1 + Re⟨ψ|U|ψ⟩)/2. With S-dagger on
the ancilla before the final H, P(0) = (1 - Im⟨ψ|U|ψ⟩)/2. Each estimate has sigma about 1/sqrt(shots)
(`quantum-measurement-estimation`).

## 4. Grover search

| Oracle | Action | Build |
|---|---|---|
| phase | x maps to (-1)^f(x) x | one marked pattern: X on its 0-bits, multi-controlled Z, X again |
| bit-flip | (x, y) maps to (x, y XOR f(x)) | put y in \|−⟩: phase kickback turns it into a phase oracle |

Diffuser D = H^n (2|0⟩⟨0| - I) H^n. With sin θ = sqrt(M/N), after k iterations
P = sin^2((2k+1)θ), and k_opt = floor(π/(4θ)), about (π/4) sqrt(N/M). Overshooting lowers success.

```python
from qiskit.circuit.library import grover_operator
orc = QuantumCircuit(3)
orc.x(1); orc.h(2); orc.ccx(0, 1, 2); orc.h(2); orc.x(1)   # phase flip on '101' (q0 = 1, q1 = 0, q2 = 1)
G = grover_operator(orc)
qc = QuantumCircuit(3); qc.h(range(3))
for _ in range(2):
    qc.compose(G, inplace=True)
print(Statevector(qc).probabilities_dict()["101"])         # 0.9453
```

Measured (N = 8, M = 1, transpiled to cx+u at level 3):

| k | P(marked) | CX |
|---|---|---|
| 1 | 0.7812 | 12 |
| 2 | 0.9453 | 24 |
| 3 | 0.3301 | 36 |

## 5. Unknown number of solutions

| Method | Idea | Cost |
|---|---|---|
| BBHT exponential search (Boyer-Brassard-Høyer-Tapp 1998) | random k in [0, m); grow m by 6/5 after each failure | expected O(sqrt(N/M)) queries |
| quantum counting | phase estimation on the Grover iterate (eigenphases ±2θ), then M = N sin^2 θ | t ancillas fix the precision of θ |
| fixed-point amplitude amplification (Yoder-Low-Chuang 2014) | phases chosen so success >= 1 - δ^2 for any M above a known lower bound | no overshoot ("souffle problem") |
| lower bound (BBBV 1997) | | Ω(sqrt(N/M)) queries for any algorithm |

## 6. Amplitude estimation

A|0⟩ = sqrt(1 - a)|ψ_0⟩|0⟩ + sqrt(a)|ψ_1⟩|1⟩; Q = A S_0 A-dagger S_χ has eigenphases ±2θ_a with
a = sin^2 θ_a.

| Variant | Circuits | Error | Note |
|---|---|---|---|
| canonical (Brassard-Høyer-Mosca-Tapp 2002) | QPE on Q with t ancillas | abs(Δa) <= 2π sqrt(a(1 - a))/2^t + π^2/4^t | depth about 2^t applications of Q |
| maximum-likelihood AE (Suzuki et al. 2020) | Q^k for a schedule k = 0, 1, 2, 4, ...; fit the likelihood | close to 1/(total queries) | no QPE, shallower |
| iterative AE (Grinko et al. 2021) | adaptive k with confidence intervals | O(1/ε) up to a log factor | gives a confidence interval |
| classical Monte Carlo | | O(1/sqrt(samples)) | the baseline |

Always state the cost of A (state loading plus payoff circuit); in pricing it dominates
(`quantum-resource-estimation`).

```python
def mlae(hits, shots, ks, grid=20001):
    """hits[i] = count of the good outcome after Q^ks[i] A; returns the a = sin^2(theta) estimate."""
    th = np.linspace(1e-6, np.pi / 2 - 1e-6, grid)
    ll = sum(h * np.log(np.sin((2*k + 1) * th) ** 2 + 1e-300) +
             (shots - h) * np.log(np.cos((2*k + 1) * th) ** 2 + 1e-300) for h, k in zip(hits, ks))
    return np.sin(th[np.argmax(ll)]) ** 2
```
Known answer: A = RY(2θ) on one qubit gives a = sin^2 θ for any schedule.

## 7. Shor order finding

U_a|y⟩ = |a y mod N⟩ has eigenphases s/r, where r is the order of a mod N. Phase estimation with
t = 2n + 1 ancillas (n = ceil(log2 N), plus a few more for higher success) gives m with m/2^t close to
s/r; continued fractions recover r. Success needs r even and a^(r/2) not congruent to -1 mod N; then
gcd(a^(r/2) ± 1, N) are factors.

```python
from fractions import Fraction
from math import gcd
N, a, t = 15, 7, 8                       # the order of 7 mod 15 is 4
for m in (0, 64, 128, 192):              # ideal QPE outcomes m = s 2^t / r
    r = Fraction(m, 2**t).limit_denominator(N).denominator
    if pow(a, r, N) == 1 and r % 2 == 0 and pow(a, r // 2, N) != N - 1:
        print(m, r, gcd(pow(a, r // 2) - 1, N), gcd(pow(a, r // 2) + 1, N))
# prints "64 4 3 5" and "192 4 3 5"; m = 0 and m = 128 fail (s and r not coprime) and are retried
```
Modular exponentiation dominates the cost (windowed arithmetic). RSA-2048 estimates: about 20 million
noisy qubits and 8 hours (Gidney-Ekerå 2019); under 1 million noisy qubits and under a week (Gidney
2025); both assume 0.1% physical error rates and 1 µs surface-code cycles. Quote them only with these
assumptions (`quantum-resource-estimation`).

## 8. Oracle and arithmetic hygiene

- Compute, copy, uncompute (Bennett): compute f into ancillas, copy the result (or kick back the
  phase), uncompute. Leftover garbage entangles with the register and kills interference.
- Ancillas against Toffolis: fewer ancillas cost more Toffolis (MCX table in
  `quantum-circuit-decomposition`).
- Adders: Cuccaro ripple-carry (one ancilla, about 2n Toffolis); Gidney's temporary-AND adder
  (about n Toffolis, i.e. 4n T, with n ancillas whose uncomputation is measurement-based).
- QROM table lookup of L entries costs about L Toffolis (Babbush et al. 2018); select-swap variants
  trade qubits for about sqrt(L) scaling. Lookups and arithmetic usually dominate oracle cost.

## 9. Crossover arithmetic

Before recommending Grover or amplitude estimation, solve for the problem size where the quantum
runtime (π/4) sqrt(N) t_iter beats the classical N / r_c:

```
sqrt(N*) = (π/4) t_iter r_c            T_quantum at crossover = (π/4)^2 t_iter^2 r_c
```
Example: oracle plus diffuser of 1e4 logical operations at 1 µs each gives t_iter = 10 ms. Against one
classical core at r_c = 1e9 checks/s: N* = 6.2e13 and the quantum run takes 6.2e4 s (17 hours) just to
break even. Against 1000 cores (r_c = 1e12): 6.2e7 s, about 2 years. Babbush et al. 2021 ("Focus
beyond quadratic speedups for error-corrected quantum advantage") reach the same conclusion with full
error-correction overheads: quadratic speedups need much better than quadratic margins in practice.

## 10. Known-answer tests

| Test | Expected |
|---|---|
| QPE on T, t = 3, eigenstate \|1⟩ | '001' with probability 1 (measured 1000 of 1000) |
| QFT of the all-zero state | uniform amplitudes 2^(-n/2) |
| QFT of basis state j | amplitudes 2^(-n/2) e^(2πijk/2^n), linear phases (measured for QFTGate) |
| iterative QPE, φ = 5/8, t = 3 | bits 1, 0, 1 (measured) |
| Bernstein-Vazirani with secret s | s with probability 1 |
| Grover, N = 8, M = 1, k = 2 | 0.9453 (measured) |
| amplitude estimation with A = RY(2θ) | a = sin^2 θ |
| Hadamard test with U = Z on \|0⟩ | P(0) = 1 |
| Shor classical post-processing, N = 15, a = 7 | r = 4, factors 3 and 5 |

## 11. Worked example: Grover on 3 qubits

N = 8, M = 1: θ = arcsin(1/sqrt(8)) = 0.3614 rad; k = floor(π/(4θ)) = floor(2.173) = 2;
P(2) = sin^2(5θ) = 0.9453; one more iteration gives sin^2(7θ) = 0.3301.

```python
from qiskit.primitives import StatevectorSampler
from qiskit import transpile
qc = QuantumCircuit(3); qc.h(range(3))
qc.compose(G, inplace=True); qc.compose(G, inplace=True); qc.measure_all()
counts = StatevectorSampler(seed=5).run([qc], shots=10000).result()[0].data.meas.get_counts()
p = counts["101"] / 1e4
print(p, np.sqrt(p * (1 - p) / 1e4))                                   # 0.9436 0.0023
tq = transpile(qc.remove_final_measurements(inplace=False), basis_gates=["cx", "u"],
               optimization_level=3, seed_transpiler=1)
print(tq.count_ops()["cx"])                                           # 24
```

| Quantity | Value |
|---|---|
| ideal success, k = 2 | 0.9453 |
| sampled, 10,000 shots (measured) | 0.9436 ± 0.0023: within 1 sigma of ideal |
| CX before routing (measured) | 24 (12 per iteration: one CCZ in the oracle, one in the diffuser) |
| fidelity bound at 0.5% two-qubit error | 0.995^24 = 0.887, before routing SWAPs, readout and 1q errors |

Reading: hardware should still show '101' clearly, but well below 0.945. Report ideal, noisy-simulation
(fake backend, `qiskit-primitives-runtime`) and hardware numbers together, each with its sigma.

## 12. Pitfalls

- Bit reversal forgotten, or QFT and readout using different endianness.
- Controlled-U^(2^k) built by repeating U 2^k times instead of evolving for 2^k τ: exponential gate
  count and wrong cost claims (`hamiltonian-simulation-methods`).
- Phase oracle and bit-flip oracle mixed up: a bit-flip oracle without the |−⟩ ancilla changes nothing
  that the diffuser can amplify.
- Grover iterations overshot because M was guessed; use BBHT, counting or fixed-point amplification.
- Garbage left in oracles (section 8).
- Continued-fraction candidates used without checking a^r = 1 mod N.
- Dependence on qiskit-algorithms (Grover, AmplitudeEstimation and PhaseEstimation classes), which is
  community-maintained outside Qiskit core: check its maintenance status and Qiskit 2.x compatibility
  first. The circuit library has the building blocks (`QFTGate`, `grover_operator`,
  `phase_estimation`, all present in 2.6).

Related: `quantum-circuit-decomposition`, `hamiltonian-simulation-methods`, `quantum-resource-estimation`, `quantum-measurement-estimation`, hub `quantum-computing`
