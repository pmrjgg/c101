# Quantum algorithms reference

Notation: n qubits, N = 2^n, |s⟩ = H^{⊗n}|0⟩, angles in radians.

## 1. Quantum Fourier transform

```
QFT |j⟩ = (1/√N) Σ_k exp(2πi j k / N) |k⟩
circuit: for qubit i (most significant first): H, then controlled-R_m from each less significant
qubit, R_m = diag(1, exp(2πi / 2^m)); finish with a qubit-order reversal (SWAPs or relabelling)
gates: n(n+1)/2 rotations+H, plus floor(n/2) SWAPs
approximate QFT: drop R_m with m > m_max ≈ log2(n) + 2; error O(n 2^-m_max), gates O(n log n)
```

Relabel instead of SWAP when the next stage is a measurement; SWAPs cost 3 CNOTs each after routing.

## 2. Phase estimation

Goal: U|u⟩ = exp(2πiφ)|u⟩, estimate φ.

```
t ancillas, controlled-U^(2^k) for k = 0..t-1, inverse QFT on ancillas
for n correct bits with probability ≥ 1 - δ:  t = n + ceil(log2(2 + 1/(2δ)))
if |u⟩ is a superposition Σ a_i |u_i⟩, outcome i occurs with probability |a_i|²
```

Variants:
- Iterative (Kitaev) QPE: one ancilla, mid-circuit measurement and feed-forward, bits from least
  significant up. Fits hardware with few qubits.
- Robust / Bayesian / statistical phase estimation: tolerates noise, uses classical inference over
  many short circuits; preferred for early fault-tolerant energy estimation.
- Hadamard test: ancilla in |+⟩, controlled-U, measure X (and Y) gives Re (Im) ⟨ψ|U|ψ⟩.

Costs are dominated by controlled-U^(2^k): for Hamiltonian simulation U = e^{-iHτ}, total evolution
time ~ 2^t τ, so energy precision ε needs evolution time O(1/ε) (Heisenberg limit).

## 3. Grover and amplitude amplification

```
oracle O|x⟩ = (-1)^{f(x)}|x⟩,   diffuser D = 2|s⟩⟨s| - I = H^{⊗n} (2|0⟩⟨0| - I) H^{⊗n}
sin θ = sqrt(M/N);  after k iterations P(success) = sin²((2k + 1)θ)
k_opt = floor(π / (4θ)) ≈ floor((π/4) sqrt(N/M))
```

- Unknown M: exponential search (Boyer-Brassard-Høyer-Tapp) with randomised k, expected
  O(sqrt(N/M)) queries; or quantum counting (QPE on the Grover iterate) to estimate M first.
- Fixed-point amplitude amplification (Yoder-Low-Chuang 2014) avoids the overshoot (souffle problem).
- Lower bound Ω(sqrt(N/M)) queries (BBBV 1997): the speedup is quadratic and optimal.
- Practicality: with a fault-tolerant clock of ~1 µs per logical step and oracle depth D, the
  quadratic speedup beats a classical machine evaluating 1e9-1e10 candidates/s only for very large
  N; do the crossover arithmetic before recommending Grover for any real search.

## 4. Amplitude estimation

Estimate a = |⟨good|A|0⟩|² with error ε using O(1/ε) applications of A (vs O(1/ε²) samples).

| Variant | Depth | Notes |
|---|---|---|
| Canonical (QPE on Grover iterate) | deep, ~1/ε | needs QFT and many controlled iterates |
| Maximum-likelihood AE (Suzuki 2020) | schedule of k values, no QPE | classical MLE over results |
| Iterative AE (Grinko 2021) | adaptive k, no QPE | provable confidence intervals |

Monte Carlo use (option pricing): loading the distribution and payoff into A usually costs more
than the speedup gains at realistic precision; published estimates for derivative pricing need
thousands of logical qubits and fast logical clocks.

## 5. Shor

1. Pick random a coprime to N; order finding: smallest r with a^r ≡ 1 mod N via QPE on
   U_a |y⟩ = |a y mod N⟩.
2. Continued fractions on the measured phase s/r; if r is even and a^{r/2} ≢ -1 mod N, then
   gcd(a^{r/2} ± 1, N) gives factors. Success probability per run is Ω(1); repeat.
3. Cost is modular exponentiation: O(n³) gates schoolbook, better with windowing and
   approximate residue arithmetic. Ekerå-Håstad variants target RSA moduli directly.

Published fault-tolerant estimates for RSA-2048 (0.1% physical error, 1 µs cycle, surface code):
~20M qubits / 8 hours (Gidney-Ekerå 2019); under 1M qubits / under a week (Gidney 2025). Quote
these with their assumptions; never as "N qubits break RSA".

## 6. Variational algorithms

VQE loop: prepare ansatz U(θ)|ref⟩, estimate E(θ) = Σ c_j ⟨P_j⟩, classical optimizer updates θ.

| Choice | Options | Guidance |
|---|---|---|
| Fermion-to-qubit mapping | Jordan-Wigner, Bravyi-Kitaev, parity (+2-qubit tapering) | qubits = spin orbitals (H2/STO-3G: 4, tapered to 1-2) |
| Ansatz | UCCSD, k-UpCCGSD, ADAPT-VQE, hardware-efficient | chemistry-inspired ansätze avoid barren plateaus better; hardware-efficient is shallow but untrainable at scale |
| Optimizer | SPSA (noisy), COBYLA, L-BFGS-B (exact sim), natural gradient | match to noise level; budget shots per iteration |
| Gradients | parameter shift: ∂E/∂θ = [E(θ + π/2) - E(θ - π/2)] / 2 for gates exp(-iθP/2) | 2 circuit evaluations per parameter |
| Measurement | qubit-wise commuting groups, general commuting groups, classical shadows | grouping cuts shot cost 1-2 orders of magnitude |

Barren plateaus: for deep random (2-design) circuits or global cost functions, Var[∂E] decays as
O(2^-n): gradients cannot be resolved with polynomial shots. Mitigations (local costs, shallow
problem-inspired ansätze, warm starts) also tend to make the problem classically simulable;
state this tension when proposing VQE.

QAOA:

```
|γ, β⟩ = Π_{l=1..p} exp(-iβ_l B) exp(-iγ_l C) |s⟩,  B = Σ X_i
MaxCut: C = Σ_{(i,j)∈E} (1 - Z_i Z_j)/2
p = 1 on 3-regular graphs: approximation ratio ≥ 0.6924 (Farhi-Goldstone-Gutmann 2014)
```

Classical baselines to beat on the same instances: Goemans-Williamson SDP (0.878 guarantee),
Burer-Monteiro heuristics, simulated annealing, tabu search, commercial MIP solvers. Parameter
concentration lets p-layer angles transfer across instances of a family; use it to cut optimisation
cost.

## 7. Linear systems (HHL and successors)

Original HHL: Õ(log(N) s² κ² / ε) for s-sparse A with condition number κ. Later algorithms reach
Õ(κ log(1/ε)) queries (e.g. discrete adiabatic methods, 2022) given a block encoding of A.

Read-the-fine-print checklist (Aaronson 2015):
1. |b⟩ must be preparable in polylog(N) time. Arbitrary classical data is not.
2. A must be sparse or block-encodable efficiently and well-conditioned (κ = polylog N).
3. The output is |x⟩, not x. Reading all entries needs ~N repetitions; only quantities such as
   ⟨x|M|x⟩ are cheap.
4. Compare against classical iterative solvers on the same promise (conjugate gradient
   O(N s sqrt(κ) log(1/ε))) and against dequantized randomized algorithms for low-rank inputs
   (Tang 2018 and successors).

## 8. Hamiltonian simulation

Pauli-string exponential exp(-iθP/2) for P of weight w: basis change V on each support qubit so
that V P_i V† = Z (H for X; S† then H, or RX(π/2), for Y), CNOT ladder onto one qubit (w - 1
CNOTs), RZ(θ), then uncompute the ladder and V†: 2(w - 1) CNOTs total. Jordan-Wigner strings have weight O(n);
Bravyi-Kitaev O(log n).

Product formulas:

```
S1(t)  = Π_j exp(-i H_j t)
S2(t)  = Π_{j=1..L} exp(-i H_j t/2) Π_{j=L..1} exp(-i H_j t/2)              (Strang)
S_{2k}(t) = S_{2k-2}(p_k t)² S_{2k-2}((1 - 4 p_k) t) S_{2k-2}(p_k t)²,  p_k = 1/(4 - 4^{1/(2k-1)})
error of r steps of S_p: O(α_comm t^{p+1} / r^p), α_comm = nested-commutator norm (Childs et al. 2021)
```

qDRIFT: sample term j with probability |c_j|/λ, apply exp(-i sign(c_j) P_j λ τ); N = O(2 λ² t² / ε)
samples; cost independent of the number of terms L.

LCU and qubitization: write H = Σ α_j U_j (unitaries), λ = Σ|α_j|; PREPARE|0⟩ = Σ sqrt(α_j/λ)|j⟩,
SELECT = Σ |j⟩⟨j| ⊗ U_j; ⟨0|PREP† SELECT PREP|0⟩ = H/λ (block encoding). The qubitized walk
operator has eigenphases arccos(E_k/λ); phase estimation to energy precision ε needs about
πλ/(2ε) walk steps. Chemistry costs therefore hinge on reducing λ (double factorisation, tensor
hypercontraction) and on the Toffoli cost of PREPARE (QROM).

Practical rule: measure Trotter error numerically on small instances (exact diagonalisation up to
~20 qubits) and extrapolate; commutator bounds are often loose by orders of magnitude.

## 9. Complexity landmarks

| Statement | Status |
|---|---|
| BPP ⊆ BQP ⊆ PP (hence ⊆ PSPACE) | proven |
| Oracle separations (Simon, Bernstein-Vazirani, Forrelation, BQP vs PH relative to an oracle, Raz-Tal 2018) | proven, oracle model only |
| Factoring in BQP | proven (Shor); factoring not known to be NP-hard |
| NP ⊆ BQP | not believed; Grover's quadratic bound is optimal for black-box search |
| Random circuit sampling hard classically | conjectured, with evolving classical attacks |

## 10. Classical baselines to check first

| Quantum proposal | Classical competitor |
|---|---|
| Ground-state energy, weakly correlated | DFT, CCSD(T) |
| Ground-state energy, strongly correlated 1D/quasi-1D | DMRG |
| Shallow circuits, low entanglement | MPS/PEPS tensor networks, Pauli propagation |
| Near-Clifford circuits | stabilizer rank / Clifford perturbation |
| Combinatorial optimisation | SA, tabu, MIP solvers, GW SDP |
| Low-rank linear algebra | dequantized sampling algorithms |
