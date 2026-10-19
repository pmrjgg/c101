---
name: stabilizer-codes-surface-code
description: "Stabilizer and surface-code theory for practitioners: Pauli/symplectic representation, CSS construction and distance checks, a code catalogue (repetition to bivariate-bicycle qLDPC, color, bosonic), rotated surface-code layout and hook errors, thresholds by noise model, logical-error scaling and Lambda, lattice surgery and magic-state supply. Load when choosing, analysing or explaining QEC codes."
when_to_use: "Choosing or comparing QEC codes ([[n,k,d]], check weight, connectivity, rate); checking a stabilizer or CSS construction (commutation, k, distance); explaining surface-code layout, hook errors, boundaries or memory experiments; 'is this below threshold?', 'what distance do we need?', 'what does Lambda mean?'; lattice surgery, transversal gates, magic-state distillation or cultivation; reviewing QEC claims in papers or vendor roadmaps."
---

# Stabilizer codes and the surface code

Three numbers settle most QEC questions: [[n, k, d]] of the code, the threshold of the
(noise model, decoder) pair, and Λ at the operating point. Each section below pins one of them
down. Simulation and decoding (Stim, sinter, PyMatching) live in `stim-qec-decoding`; turning
distances into machine sizes and runtimes lives in `quantum-resource-estimation`.

## 1. Stabilizer basics

- Pauli group P_n = {±1, ±i} × {I, X, Y, Z}^⊗n. A stabilizer group S ⊂ P_n is abelian, does not
  contain -I, and has n - k independent generators g_1 .. g_{n-k}.
- Code space C = {|ψ⟩ : g|ψ⟩ = |ψ⟩ for all g ∈ S}, dim C = 2^k, projector P = Π_i (I + g_i)/2.
- Logical operators: N(S) \ S, where N(S) is the set of Paulis commuting with all of S. Pick k pairs
  (X̄_j, Z̄_j) that anticommute pairwise and commute across pairs.
- Distance d = min weight over N(S) \ S. The code corrects t = ⌊(d - 1)/2⌋ errors at unknown
  positions, detects d - 1, and corrects d - 1 erasures (known positions).
- Syndrome bit s_i(E) = 1 iff E anticommutes with g_i. Syndromes are linear: s(EF) = s(E) ⊕ s(F).
- Degeneracy: E and E·g (g ∈ S) act identically on C. The decoder's job is the most likely
  logical class, not the most likely error; minimum-weight decoders approximate this, maximum-
  likelihood (tensor-network) decoders compute it.
- Knill-Laflamme: {E_a} is correctable iff P E_a† E_b P = c_ab P for all a, b. For stabilizer codes
  this means no product E_a† E_b lies in N(S) \ S.

| Fault E | Syndrome | Outcome |
|---|---|---|
| E ∈ S | 0 | harmless |
| E ∈ N(S) \ S | 0 | silent logical error (weight ≥ d) |
| E ∉ N(S) | ≠ 0 | decoder applies C with s(C) = s(E); failure iff E·C ∈ N(S) \ S |

## 2. Binary symplectic form and CSS codes

```
P ∝ X^a Z^b  <->  v = (a | b) ∈ F_2^{2n}       X1 Z2 Y3  ->  (1 0 1 | 0 1 1)
product      <->  v + v' (mod 2), phases dropped
commute      <=>  a·b' + b·a' = 0 (mod 2)       check matrix H = [H_x | H_z] needs H Λ H^T = 0, Λ = [[0, I], [I, 0]]
CSS:  X checks H_X, Z checks H_Z, with H_X H_Z^T = 0 (mod 2)
k   = n - rank_2(H_X) - rank_2(H_Z)
d_X = min wt(ker H_Z \ rowspace H_X)    d_Z = min wt(ker H_X \ rowspace H_Z)    d = min(d_X, d_Z)
```

Ranks are over GF(2); `np.linalg.matrix_rank` over the reals is wrong. Minimal tooling:

```python
import numpy as np

def rank_gf2(M):
    M = (np.asarray(M) % 2).astype(np.uint8); r = 0
    for c in range(M.shape[1]):
        piv = np.nonzero(M[r:, c])[0]
        if piv.size == 0: continue
        M[[r, r + piv[0]]] = M[[r + piv[0], r]]
        rows = np.nonzero(M[:, c])[0]; M[rows[rows != r]] ^= M[r]
        r += 1
        if r == M.shape[0]: break
    return r

def hypergraph_product(H1, H2):            # Tillich-Zemor; H1 = H2 = repetition gives the unrotated surface code
    (m1, n1), (m2, n2) = H1.shape, H2.shape
    HX = np.hstack([np.kron(H1, np.eye(n2, dtype=int)), np.kron(np.eye(m1, dtype=int), H2.T)]) % 2
    HZ = np.hstack([np.kron(np.eye(n1, dtype=int), H2), np.kron(H1.T, np.eye(m2, dtype=int))]) % 2
    return HX, HZ                           # n = n1 n2 + m1 m2, d = min of the four classical distances
```

The `galois` package gives the same over `GF = galois.GF(2)` (`np.linalg.matrix_rank(GF(H))`,
`GF(H).null_space()`) when you prefer a field type to hand-rolled elimination.

## 3. Distance computation

| Size | Method | Notes |
|---|---|---|
| n ≲ 30 | enumerate ker H_Z (2^{n - rank}) and drop rowspace H_X | exact; seconds |
| n ≈ 30-500 | integer program or SAT: min Σx s.t. H_Z x = 0, z̄_j·x = 1 (mod 2), one solve per Z̄_j | exact if the solver finishes; random information-set search gives upper bounds |
| circuit level | Stim `shortest_graphlike_error()`; `search_for_undetectable_logical_errors(...)` for hyperedge DEMs | circuit (fault) distance, includes hook and measurement faults |

```python
from scipy.optimize import milp, LinearConstraint, Bounds

def min_x_logical(HZ, zbar):                # lightest X-type logical anticommuting with Z-logical zbar
    m, n = HZ.shape
    A = np.zeros((m + 1, n + m + 1)); A[:m, :n] = HZ; A[:m, n:n + m] = -2 * np.eye(m)
    A[m, :n] = zbar; A[m, -1] = -2          # parity constraints written with integer slacks
    rhs = np.r_[np.zeros(m), 1]
    res = milp(np.r_[np.ones(n), np.zeros(m + 1)], constraints=LinearConstraint(A, rhs, rhs),
               integrality=np.ones(n + m + 1),
               bounds=Bounds(np.zeros(n + m + 1), np.r_[np.ones(n), np.full(m + 1, np.inf)]))
    return round(res.fun)                   # d_X = min over all k logicals zbar_j
```

Keep the two distances apart: code distance counts data-qubit errors only; circuit distance counts
every fault location in the syndrome-extraction circuit and is ≤ the code distance. A bad CNOT
order or a missing flag drops circuit distance while the [[n, k, d]] on paper is unchanged.

```python
err = circuit.shortest_graphlike_error()             # needs a graphlike (decomposable) DEM
assert len(err) == d
errs = circuit.search_for_undetectable_logical_errors(
    dont_explore_detection_event_sets_with_size_above=4,
    dont_explore_edges_with_degree_above=4,
    dont_explore_edges_increasing_symptom_degree=False)   # heuristic: an upper bound
```

## 4. Code catalogue

| Code | [[n, k, d]] | Check weight | Connectivity | Use |
|---|---|---|---|---|
| repetition | [[d, 1, d]] against one Pauli type only (distance 1 for the other) | 2 | 1D chain | benchmarks, outer code for biased cat qubits |
| Shor | [[9, 1, 3]] | Z checks 2, X checks 6 | concatenated | history, teaching degeneracy |
| perfect code | [[5, 1, 3]] | 4 | all-to-all | smallest d = 3; non-CSS, no transversal H |
| Steane | [[7, 1, 3]] | 4 | 2D (d = 3 color code) | transversal Clifford group, FT demos |
| rotated surface | [[d², 1, d]] | 4 bulk, 2 boundary | 2D nearest neighbour, degree 4 | the default; highest circuit-level threshold among 2D local codes |
| unrotated surface | [[d² + (d-1)², 1, d]] | 4 | 2D nearest neighbour | textbooks; hypergraph product of two repetition codes |
| 6.6.6 color | [[(3d² + 1)/4, 1, d]] | 6 | 2D, degree 3 lattice | transversal Cliffords; lower threshold than surface, harder decoding (Chromobius) |
| bivariate bicycle "gross" | [[144, 12, 12]] (family: [[72,12,6]], [[90,8,10]], [[108,8,10]], [[288,12,18]]) | 6 | degree 6 incl. 2 long-range links per qubit, two-layer layout | about 10x fewer qubits than surface patches for 12 logicals (Bravyi et al. 2024); logic via extra modules |
| hypergraph / lifted / balanced product | rate constant or growing, d up to ∝ n for the best families | bounded (row + column weights) | non-local | qLDPC memory; decoding with BP+OSD |
| cat qubit + repetition | bit flips suppressed exponentially in photon number; phase flips by a d-chain | 2 | 1D | bias-tailored hardware |
| GKP | corrects small displacements of one oscillator | - | - | inner code concatenated with surface or repetition codes |

Selection rule: on a planar nearest-neighbour chip use the rotated surface code unless a hardware
feature is specifically exploited (bias: XZZX or cat + repetition; long-range couplers or atom
movement: qLDPC memory; transversal gates on movable atoms: color or surface with transversal CNOT).

## 5. Rotated surface-code layout

- d² data qubits on a d × d grid and d² - 1 measure qubits: (d - 1)² weight-4 bulk plaquettes and
  2(d - 1) weight-2 boundary plaquettes, half X-type and half Z-type. Total 2d² - 1.
- Boundaries: Z̄ is a weight-d string of Z joining the two boundaries that carry weight-2 Z checks;
  X̄ is a weight-d string of X joining the two boundaries with weight-2 X checks. They cross on one
  qubit, so they anticommute.
- One round: reset ancillas, basis change on X-ancillas, 4 CNOT layers, basis change, measure.
- Hook errors: an ancilla fault after 2 of the 4 CNOTs spreads to 2 data qubits. Order the CNOTs in
  an "N" pattern for one check type and a "Z" pattern for the other (Tomita-Svore 2014) so hooks lie
  perpendicular to the logical of the same type; aligned hooks cut circuit distance to about d/2.
- Memory experiment (memory_z): prepare |0⟩^⊗d², run r rounds, measure data in Z. Detectors compare
  consecutive rounds; first-round Z checks and the final data-derived Z checks are deterministic.
  Use r ≥ d, otherwise time-like chains (repeated measurement errors) are not fully tested.

| d | data | measure | total | corrects t |
|---|---|---|---|---|
| 3 | 9 | 8 | 17 | 1 |
| 5 | 25 | 24 | 49 | 2 |
| 7 | 49 | 48 | 97 | 3 |
| 11 | 121 | 120 | 241 | 5 |
| 25 | 625 | 624 | 1249 | 12 |

## 6. Thresholds by noise model

| Noise model (surface code) | Threshold | Decoder |
|---|---|---|
| code capacity, independent X/Z flips, perfect syndromes | ~10.3% | MWPM |
| same | ~10.9% | optimal (random-bond Ising, Nishimori line) |
| code capacity, depolarizing | ~15.5% MWPM, ~18.9% optimal | |
| phenomenological (data + measurement flips, equal p) | ~2.9-3% | MWPM |
| circuit-level depolarizing (every gate, reset, measure, idle) | ~0.5-1% | MWPM; exact value depends on the schedule and on noise details |
| SI1000-style (2q p, 1q and idle p/10, measure 5p, reset 2p) | same order, not interchangeable with uniform depolarizing | MWPM / correlated matching |
| ~98% of errors converted to erasures | ~1% rises to ~4% (Wu et al. 2022) | erasure-aware MWPM |
| infinitely Z-biased noise, XZZX variant | 50% (code capacity) | |

Rules: quote a threshold together with its noise model and decoder; never compare a hardware error
rate with a code-capacity threshold; a threshold is the crossing of the d curves, not a single-d
"pseudo-threshold" where p_L = p.

## 7. Logical-error scaling and Λ

```
p_L(d) ≈ A (p / p_th)^((d+1)/2)      per round,  A ≈ 0.1,  p_th ≈ 0.01 (circuit-level rule of thumb)
Λ = p_L(d) / p_L(d+2) ≈ p_th / p      Λ > 1 (decreasing with d) is the operational meaning of "below threshold"
distance steps of +2 needed = ceil( log10(p_L,now / p_L,target) / log10 Λ )
per logical operation (≈ d rounds):  p_op ≈ d · p_L(round)
```

Google's Willow memory (2024) reported Λ ≈ 2.14 over d = 3, 5, 7 and ≈ 0.143% error per round at
d = 7. Reaching 1e-6 per round from there: log10(1.43e-3/1e-6)/log10(2.14) = 9.55, so 10 steps,
d = 27 (1457 qubits per patch). At Λ = 4 the same target needs 6 steps, d = 19 (721 qubits).
Λ must be measured over at least three distances; two points cannot show a trend.

## 8. Logical operations

| Operation | How | Cost |
|---|---|---|
| Paulis | Pauli-frame tracking in software | free |
| Z̄Z̄ or X̄X̄ measurement | lattice surgery: merge two patches along matching boundaries for d rounds, read the product from the new boundary checks, split | ~d rounds, one routing strip |
| CNOT | Z̄Z̄ then X̄X̄ surgery with an ancilla patch, plus Pauli corrections | ~2d rounds |
| H, S | patch deformation / rotation (surface), transversal on color and Steane codes | ~d rounds (surface) |
| transversal CNOT | aligned patches with pairwise links (atom movement, stacked layouts) | ~1 round + decoding across patches |
| T, CCZ | consume a magic state via teleportation (section 9) | factory supply |

Eastin-Knill forbids a transversal universal gate set, so some non-Clifford resource is always
needed. Budget every logical operation as ≈ d rounds; that is the clock of `quantum-resource-estimation`.

## 9. Magic states

- |T⟩ = T|+⟩ consumed by gate teleportation; a Clifford (S) fix-up is needed with probability 1/2.
- 15-to-1 distillation: p_out ≈ 35 p_in³, success ≈ 1 - 15 p_in. p_in = 1e-3 gives 3.5e-8; two
  levels give ≈ 1.5e-21. Footprints range from a few thousand to tens of thousands of physical
  qubits per factory depending on the target (Litinski 2019 tables).
- CCZ factories (8 T → 1 CCZ style) serve Toffoli-heavy arithmetic directly.
- Magic-state cultivation (Gidney-Shutty-Jones 2024): grow a checked T state inside a small color-code
  patch, then expand into a surface-code patch. Reported T-state errors around 1e-9 at uniform
  depolarizing p = 1e-3 for a space-time cost near a lattice-surgery CNOT; check its tables before
  reusing numbers for another noise model.
- When the T count is large, runtime = N_T / (factories × rate per factory), and factories plus
  their routing can rival the data footprint.

## 10. Hardware realism

- Leakage out of the qubit subspace is not a Pauli error: use leakage-reduction units, reset ancillas
  every round, and data-qubit leakage removal; simulate it or state that it is excluded.
- Correlated bursts (high-energy impacts) can raise error rates chip-wide for milliseconds; they
  break the independence assumption behind p_L scaling.
- Crosstalk and drifting two-level-system defects change the error model; reweight the decoder's
  DEM from recent calibration (`stim-qec-decoding`).
- Real-time decoding: throughput must exceed the syndrome rate (otherwise the backlog grows without
  bound) and latency sets the reaction time of feed-forward. Google reported ~63 µs average decoder
  latency at d = 5 on Willow.
- Memory-experiment qubit counts exclude routing lanes, factories and I/O; algorithms need 2-10x more.

## 11. Worked example: Steane, then rotated d = 5

Steane [[7, 1, 3]] from Hamming(7, 4): H_X = H_Z = H, column j is j in binary (MSB first).

```python
import itertools, numpy as np
H = np.array([[int(b) for b in format(j, "03b")] for j in range(1, 8)]).T
assert not (H @ H.T % 2).any()                         # H_X H_Z^T = 0
k = 7 - 2 * rank_gf2(H)                                # = 1
allv = np.array(list(itertools.product([0, 1], repeat=7)))
ker = allv[(allv @ H.T % 2 == 0).all(1)]               # X-type ops commuting with Z checks: 16
rows = {tuple(np.array(c) @ H % 2) for c in itertools.product([0, 1], repeat=3)}
logicals = [v for v in ker if tuple(v) not in rows]    # 8 nontrivial X logicals
```

Output (verified): H_X H_Z^T = 0, k = 1, 8 nontrivial X logicals with weights {3: 7, 7: 1}, so d = 3.
Weight-3 supports: (1,2,3), (1,4,5), (1,6,7), (2,4,6), (2,5,7), (3,4,7), (3,5,6) - the 7 lines of
the Fano plane. By symmetry the same holds for Z logicals. Single-X-error syndromes (Z checks):

| error | X1 | X2 | X3 | X4 | X5 | X6 | X7 |
|---|---|---|---|---|---|---|---|
| syndrome | 001 | 010 | 011 | 100 | 101 | 110 | 111 |

Every single error has a distinct non-zero syndrome equal to its position in binary, so t = 1. Two
X errors give the syndrome of a third qubit and the correction completes a weight-3 logical: d = 3
is tight.

Rotated d = 5 (Stim 1.16, `surface_code:rotated_memory_z`, rounds = 5): 49 qubits with coordinates
(25 data + 24 measure; qubit indices span 64, so count coordinates, not `num_qubits`),
120 detectors (12 + 4 × 24 + 12), 1 observable, `shortest_graphlike_error()` of length 5 (circuit
distance = code distance), all detectors silent over 1000 noiseless shots. It corrects any 2 faults.
At uniform p = 1e-3 a 200k-shot spot check gave 29 logical errors (1.45e-4 per 5-round shot).

## Pitfalls

- [[n, k, d]] (quantum) read as [n, k, d] (classical): the classical code inside a CSS code has a
  different n, k and often a larger distance than the quantum code.
- Thresholds compared across decoders or noise models (10.3% code capacity against 0.7% circuit level).
- "Below threshold" claimed from one distance or from p_L < p at a single d; show Λ over ≥ 3 distances.
- Measurement errors ignored: rounds < d, or code-capacity simulations used to size hardware.
- Circuit distance never checked; a hook-aligned schedule silently halves d.
- Physical counts taken from memory experiments (2d² - 1 per patch) for algorithms that need routing
  and factories.

Related: `stim-qec-decoding`, `quantum-resource-estimation`, `quantum-noise-mitigation`, `quantum-circuit-simulators`, hub `quantum-computing`
