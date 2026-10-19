---
name: hamiltonian-simulation-methods
description: "Hamiltonian simulation methods and their costs: Pauli-exponential circuits, Trotter-Suzuki orders with commutator bounds and empirical error measurement, qDRIFT, randomized and multi-product formulas, LCU block encodings, qubitization and QSP/QSVT, plus SDK implementations (PauliEvolutionGate, TrotterProduct, CUDA-Q exp_pauli). Load when implementing or costing time evolution, or when choosing a simulation method."
when_to_use: "Implementing e^{-iHt} for spin, fermionic or chemistry Hamiltonians; choosing Trotter order and step count, qDRIFT, multi-product formulas, LCU, qubitization or QSVT; 'how many Trotter steps?', 'is the Trotter error bound tight?', 'why does my circuit have twice the CNOTs?'; costing controlled evolution for QPE; validating dynamics against exact or MPS/TEBD results; reviewing utility-scale dynamics claims."
---

# Hamiltonian simulation methods

Choose the method from (λ, L, t, ε, hardware era), then measure the actual error on a small
instance instead of trusting worst-case bounds: product-formula bounds are routinely 10-1000x
loose, and a factor of 30 in steps is a factor of 30 in circuit depth. Fermionic mappings:
`quantum-chemistry-mapping`; fault-tolerant costing of the result: `quantum-resource-estimation`.

## 1. Setup

```
H = Σ_{j=1..L} c_j P_j      λ = Σ_j |c_j|      target ‖U - e^{-iHt}‖ ≤ ε  (or state / observable error, say which)
```

Write down the geometry and the grouping before any formula: grouping terms into commuting layers
(even/odd bonds; X, Y, Z colours; DF/THC factors) sets both the Trotter constants and the depth.
Units: ħ = 1, t in inverse energy units of H; a Hamiltonian in Hartree or GHz needs t in matching
units (2π factors included).

## 2. Product formulas

```
S1(Δ) = Π_j e^{-i H_j Δ}
S2(Δ) = Π_{j=1..m} e^{-i H_j Δ/2} · Π_{j=m..1} e^{-i H_j Δ/2}            (adjacent halves merge)
S_{2k}(Δ) = S_{2k-2}(p_k Δ)² S_{2k-2}((1 - 4p_k)Δ) S_{2k-2}(p_k Δ)²,     p_k = 1/(4 - 4^{1/(2k-1)})   (p_2 = 0.4145)
error  ‖S_p(t/r)^r - e^{-iHt}‖ = O(α_comm t^{p+1} / r^p)     ⇒   r = O(α_comm^{1/p} t^{1+1/p} ε^{-1/p})
S1 with two groups A, B:  error ≤ (t²/2r) ‖[A, B]‖
```

α_comm sums nested commutator norms of depth p + 1 (Childs-Su-Tran-Wiebe-Zhu 2021). For 1D
nearest-neighbour models it grows like n (only neighbouring terms fail to commute), not n².
S_{2k} uses 5^{k-1} S2 stages per step, so higher order pays off only when it cuts r by more.

## 3. Empirical error

Up to ~20-24 qubits: compute exact e^{-iHt}|ψ⟩ with `scipy.sparse.linalg.expm_multiply`, run the
Trotter circuit as a statevector, fit the error against r on a log-log scale (slope -p), and pick
the smallest r meeting ε. Then scale r to the target size with the bound's n-dependence.

```python
import numpy as np, scipy.sparse as sp
from scipy.sparse.linalg import expm_multiply
n, J, h, T = 12, 1.0, 1.0, 5.0                       # H = -J Σ Z_i Z_{i+1} - h Σ X_i, open chain
N, idx = 2**n, np.arange(2**n)
z = 1 - 2 * ((idx[:, None] >> (n - 1 - np.arange(n))) & 1)      # z[:, q] = ±1, qubit 0 = most significant bit
dZZ = -J * sum(z[:, i] * z[:, i + 1] for i in range(n - 1)).astype(float)
HX = sum(sp.csr_matrix((np.ones(N), (idx ^ (1 << (n - 1 - q)), idx)), shape=(N, N)) for q in range(n))
psi0 = np.zeros(N, complex); psi0[0] = 1
exact = expm_multiply(-1j * T * (sp.diags(dZZ) - h * HX).tocsc(), psi0)

def xlayer(a):                                       # e^{-i a H_X} = ⊗ e^{i a h X}, applied as two 64x64 blocks
    R = np.array([[np.cos(a * h), 1j * np.sin(a * h)], [1j * np.sin(a * h), np.cos(a * h)]])
    A = R
    for _ in range(n // 2 - 1): A = np.kron(A, R)
    return lambda v: (A @ v.reshape(2**(n // 2), -1) @ A.T).reshape(-1)

def s2(r):                                           # S2 with X outside: X(dt/2) ZZ(dt) X(dt/2)
    dt = T / r; X, ph, v = xlayer(dt / 2), np.exp(-1j * dt * dZZ), psi0.copy()
    for _ in range(r): v = X(ph * X(v))
    return v

err = {r: np.linalg.norm(s2(r) - exact) for r in (64, 128, 256, 512)}   # slope -2 on a log-log fit
p2 = 1 / (4 - 4 ** (1 / 3))
def s4(r):                                           # Suzuki S4: five S2 stages per step
    dt, v = T / r, psi0.copy()
    stages = [(xlayer(s * dt / 2), np.exp(-1j * s * dt * dZZ)) for s in (p2, p2, 1 - 4 * p2, p2, p2)]
    for _ in range(r):
        for X, ph in stages: v = X(ph * X(v))
    return v
```

## 4. Randomised and extrapolated methods

- qDRIFT: sample N = ⌈2 λ² t² / ε⌉ single-term exponentials e^{-i λ (t/N) sign(c_j) P_j} with
  probability |c_j|/λ (diamond-norm channel error). Independent of L, so it wins for many small
  terms; for the section 11 model λ = 23 gives N = 2.6e7 rotations against 1,705 RZZ for S4.
- Random term ordering per step and partially randomised hybrids (large terms by Trotter, the tail
  by qDRIFT) cut the constants.
- Multi-product formulas: combine ⟨O⟩ from Trotter circuits with different r_j classically,
  Σ c_j = 1, coefficients cancelling leading error orders; ‖c‖_1 multiplies shot noise. Tooling:
  `qiskit-addon-mpf` 0.3 (`qiskit_addon_mpf.static.setup_static_lse`, `costs.setup_exact_problem`,
  `costs.setup_frobenius_problem`, `dynamic.setup_dynamic_lse`; check argument lists in its docs).

## 5. Circuit costs

- e^{-iθP/2} for a weight-w Pauli: basis change (H for X, H·S† for Y), a CNOT ladder computing
  parity onto one qubit, RZ(θ), uncompute: 2(w - 1) CNOTs, depth reducible to O(log w) with trees.
- Jordan-Wigner hopping terms have weight O(n); Bravyi-Kitaev O(log n); fermionic swap networks
  make all pair terms nearest-neighbour in linear depth.
- 1D nearest-neighbour Trotter step: two layers of RZZ (even bonds, odd bonds) = 2q depth 2;
  (n - 1) RZZ = 2(n - 1) CNOTs plus n RX. IBM Heron fractional RZZ(θ) gates implement Ising
  layers natively (restricted angle range; check the target).
- Controlled evolution for QPE roughly doubles the cost (every rotation becomes controlled), and
  routing on hardware adds SWAPs: use post-routing counts for hardware estimates.

## 6. LCU and block encoding

```
H = Σ_j α_j U_j   (α_j > 0, signs absorbed into U_j),   λ = Σ α_j
PREP |0⟩ = Σ_j √(α_j/λ) |j⟩        SELECT = Σ_j |j⟩⟨j| ⊗ U_j
(⟨0| PREP† ⊗ I) SELECT (PREP |0⟩ ⊗ I) = H / λ
```

SELECT by unary iteration costs ≈ L Toffolis; PREPARE uses QROM plus coherent alias sampling
(≈ L + O(log 1/ε) Toffolis). Check small cases numerically: in PennyLane,
`qml.matrix(qml.PrepSelPrep(H, control=[2, 3]), wire_order=[2, 3, 0, 1])[:4, :4] * λ` equals
`qml.matrix(H)` (verified on PennyLane 0.45 with a negative coefficient).

## 7. Qubitization and QSP/QSVT

- Walk operator W = (2 PREP|0⟩⟨0|PREP† - I) · SELECT has eigenphases ±arccos(E_k/λ).
- Hamiltonian simulation by QSP/QSVT on W: O(λt + log(1/ε)) queries, optimal in both.
- Phase factors: `pyqsp`, QSPPACK, PennyLane `qml.poly_to_angles`; circuits `qml.QSVT`,
  `qml.qsvt`, `qml.Qubitization` (verify small cases against `scipy.linalg.expm`).
- Energy estimation: QPE on W needs ≈ π λ / (2ε) walk steps for precision ε.

## 8. Method choice

| Situation | Method |
|---|---|
| NISQ or early fault tolerance, small circuits, local H | S2 (or S4 when ε is tight, section 11), measured r |
| many terms, moderate λ, L ≫ λ² t²/ε per step budget | qDRIFT or a Trotter/qDRIFT hybrid |
| long times, high precision, fault tolerant | qubitization + QSVT |
| chemistry, fault tolerant | DF or THC block encodings + qubitised QPE |
| observables at several t with shallow circuits | multi-product formulas |
| open systems | Lindblad dilations or stochastic unravellings (hand to physics-expert) |

## 9. SDK implementations (verified on Qiskit 2.6, PennyLane 0.45, CUDA-Q 0.16)

```python
from qiskit.circuit.library import PauliEvolutionGate
from qiskit.synthesis import LieTrotter, SuzukiTrotter, QDrift
gate = PauliEvolutionGate([H_X, H_ZZ], time=5.0, synthesis=SuzukiTrotter(order=2, reps=500))
```

Term ordering decides the CNOT count. For n = 12 TFIM, one step costs:

| Operator passed to PauliEvolutionGate | S1 | S2 | S4 |
|---|---|---|---|
| flat `H_ZZ + H_X` | 22 CX | 44 CX | 220 CX |
| list `[H_ZZ, H_X]` | 22 | 44 | 220 |
| list `[H_X, H_ZZ]` (commuting groups, ZZ last) | 22 | 22 | 110 |

Qiskit's second order applies every operator but the last at half time on both sides, so the
expensive group must be last. PennyLane `qml.TrotterProduct(H, time, n=r, order=2)` decomposes
every term twice per step (6 `Evolution` ops for 3 terms); merge or count accordingly; `qml.evolve`
gives single exponentials. CUDA-Q: `exp_pauli(theta, qubits, "XXYZ")` inside a kernel. On CUDA-Q
0.16, `exp_pauli(θ, q, "XXXY")` maps |1100⟩ to cos θ|1100⟩ - sin θ|0011⟩, consistent with e^{iθP}
(character k on qubit k), so θ = -c·Δt gives e^{-i c P Δt}; confirm with a one-qubit test against
`rx` before relying on it.

## 10. Observables and baselines

Track correlators, magnetisation against time and Loschmidt echoes |⟨ψ0|ψ(t)⟩|². Compare with exact
results at small n and with MPS/TEBD for large 1D systems (`quantum-circuit-simulators`). Claims of
utility-scale dynamics must beat tensor-network and Pauli-propagation simulations of the same
circuit at equal accuracy.

## 11. Worked example: transverse-field Ising, n = 12, t = 5

H = -Σ Z_i Z_{i+1} - Σ X_i (J = h = 1, open chain), |ψ0⟩ = |0⟩^⊗12, ε = 1e-3 in state 2-norm,
smallest r found by doubling then bisection to 1% (section 3 code; S4 built from five S2 stages):

| Order | r | fitted slope | RZZ total | CNOT total | ⟨Z_6(5)⟩ |
|---|---|---|---|---|---|
| exact | - | - | - | - | -0.003324 |
| S1 | 16,128 | -1.00 | 177,408 | 354,816 | -0.003324 |
| S2 | 500 | -2.00 | 5,500 | 11,000 | -0.003324 |
| S4 | 31 | -3.82 | 1,705 | 3,410 | -0.003323 |

Per step S1 and S2 cost (n - 1) = 11 RZZ (S2 with merged X halves), S4 five times that. The S1
commutator bound (t²/2ε)·‖[H_ZZ, H_X]‖ ≤ 25 · 44 / 0.002 asks for r = 550,000, 34x the measured
16,128. At this tolerance S4 has the lowest 2q count, 3.2x below S2; S2 wins only when a very
loose ε (state error ≳ 0.1-0.2) or a short t needs a handful of steps. Either way, 3,410 CNOTs at
0.3% error leave e^{-10} of the signal: this is a fault-tolerant workload, or the time must shrink.

## Pitfalls

- Worst-case bounds used to size circuits (here 34x too many steps).
- Term ordering or grouping ignored: the same formula costs 2x more CNOTs (section 9).
- Controlled evolution for QPE costed as uncontrolled.
- τ units mixed (ħ = 1, energy units, 2π) between the Hamiltonian and the circuit.
- Pre-routing gate counts used for hardware estimates.
- Dynamics "validated" only against another Trotter run with the same step size.

Related: `quantum-chemistry-mapping`, `quantum-resource-estimation`, `quantum-circuit-simulators`, `cudaq-gpu-kernels`, hub `quantum-computing`
