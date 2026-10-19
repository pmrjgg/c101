---
name: quantum-circuit-decomposition
description: "Building and decomposing circuits at gate level: Euler/ZYZ and KAK two-qubit synthesis, controlled-U and multi-controlled gates, Toffoli/CCZ and relative-phase variants, Pauli-exponential ladders, rotation-synthesis T-counts, state preparation and native-gate equivalences. Load when building, decomposing or hand-costing a circuit."
when_to_use: "Hand-decomposing or costing a gate (controlled-U, Toffoli, multi-controlled X, Pauli rotation, arbitrary 2-qubit unitary); 'how many CNOTs does this need', 'T-count of this rotation', 'is my decomposition right'; choosing ancilla vs no-ancilla MCX constructions; preparing an arbitrary state or unitary; translating between CZ, ECR, iSWAP, sqrt(iSWAP) and MS/RZZ native gates; X/Y-basis measurement and mid-circuit feed-forward; verifying a hand-built circuit up to global phase."
---

# Quantum circuit decomposition

Gate-level cost is three numbers: the native two-qubit (2q) count after translation, the 2q depth,
and for fault-tolerant work the T (or Toffoli/CCZ) count. Each construction below states its count
and the check that proves it correct. Values marked *measured* come from runs with Qiskit 2.6.0,
Cirq 1.7.0 and pygridsynth; synthesis plugins change between releases, so re-measure on the
installed versions before quoting.

## 1. Universal sets and cost metrics

| Regime | Cost metric | Cheap or free |
|---|---|---|
| NISQ hardware | native 2q count and 2q depth after translation and routing; product of (1 - error) | virtual RZ (IBM), 1q gates (about 10x lower error than 2q) |
| fault tolerant (surface code) | T-count and T-depth, or Toffoli/CCZ count; logical qubits x time | Clifford gates (H, S, CNOT), Pauli frame updates |
| statevector simulation | qubit count (memory 16 x 2^n bytes) | depth |

Clifford+T is universal; Cliffords alone are classically simulable (Gottesman-Knill), which is why
the non-Clifford count is the fault-tolerant cost (`quantum-resource-estimation`).

| Platform | Native 2q gate | Basis, connectivity | One CNOT costs |
|---|---|---|---|
| IBM Heron (Torino, Fez, Marrakesh, Kingston) | CZ; RZZ(theta) for 0 < theta <= pi/2 with fractional gates | rz, sx, x, cz (FakeFez target, measured); heavy-hex | 1 CZ + 1q gates on the target |
| IBM Eagle | ECR | rz, sx, x, ecr; heavy-hex | 1 ECR + 1q gates |
| Google | CZ or sqrt(iSWAP) | PhasedXZ 1q; square grid | 1 CZ, or 2 sqrt(iSWAP) |
| trapped ions (Quantinuum, IonQ) | MS / ZZ(theta) at arbitrary angle | all-to-all | 1 maximally entangling ZZ + 1q gates |
| neutral atoms | CZ (Rydberg) | reconfigurable | 1 CZ |

Rule: report 2q count and 2q depth after translation to native gates and after routing
(`qiskit-transpilation`), never on the abstract circuit. With native arbitrary-angle ZZ (ions,
Heron fractional RZZ), an RZZ(theta) or controlled-phase costs one 2q gate instead of 2 CNOTs.

## 2. Single-qubit synthesis

Any U in U(2) is U = e^{i alpha} RZ(beta) RY(gamma) RZ(delta) (ZYZ). Extract the angles from
V = U / sqrt(det U), which lies in SU(2):

```
V = [[e^{-i(beta+delta)/2} cos(gamma/2), -e^{-i(beta-delta)/2} sin(gamma/2)],
     [e^{ i(beta-delta)/2} sin(gamma/2),  e^{ i(beta+delta)/2} cos(gamma/2)]]
gamma = 2 atan2(|V10|, |V00|);  beta + delta = 2 arg V11;  beta - delta = 2 arg V10
```
If sin(gamma/2) = 0 only beta + delta is defined; if cos(gamma/2) = 0 only beta - delta.

| Form | Gates | Where |
|---|---|---|
| ZYZ | RZ RY RZ | textbook (Nielsen-Chuang Thm 4.1) |
| ZXZ | RZ RX RZ | X-rotation hardware |
| U3(theta, phi, lambda) = RZ(phi) RY(theta) RZ(lambda) up to phase | 1 gate | OpenQASM 2 |
| ZSX | RZ SX RZ SX RZ | IBM: RZ is virtual (zero time, zero error), so the cost is 2 SX at most |
| PhasedXZ | PhXZ(a, x, z) | Cirq, Google |

```python
from qiskit.synthesis import OneQubitEulerDecomposer
from qiskit.quantum_info import Operator, random_unitary
U = random_unitary(2, seed=7)
for basis in ("ZYZ", "ZSX", "U3"):
    c = OneQubitEulerDecomposer(basis=basis)(U)
    print(basis, dict(c.count_ops()), Operator(c).equiv(U))
# measured: ZYZ {'rz': 2, 'ry': 1} True | ZSX {'rz': 3, 'sx': 2} True | U3 {'u3': 1} True

import cirq
cirq.single_qubit_matrix_to_phxz(cirq.unitary(cirq.H))     # PhXZ(a=-0.5,x=0.5,z=-1), measured
```

Merge adjacent 1q gates before counting anything: Qiskit `Optimize1qGatesDecomposition(basis=[...])`,
Cirq `cirq.merge_single_qubit_gates_to_phxz`. Any run of 1q gates on one wire is one Euler triple.

## 3. Two-qubit synthesis: KAK and the Weyl chamber

U = (A1 x A2) exp(i(a XX + b YY + c ZZ)) (B1 x B2), with pi/4 >= a >= b >= abs(c). The Weyl
coordinates fix the CNOT count (coordinates measured with `TwoQubitWeylDecomposition`):

| CNOTs | Condition | Examples (a, b, c) |
|---|---|---|
| 0 | a = b = c = 0 (local) | A x B: (0, 0, 0) |
| 1 | (pi/4, 0, 0) | CNOT, CZ: (0.7854, 0, 0) |
| 2 | c = 0 | iSWAP (0.7854, 0.7854, 0); sqrt(iSWAP) (0.3927, 0.3927, 0); RZZ(0.02) (0.01, 0, 0) |
| 3 | otherwise | SWAP (0.7854, 0.7854, 0.7854); Haar-random U(4), seed 11: (0.5265, 0.3268, 0.1870) |

```python
from qiskit.synthesis import TwoQubitBasisDecomposer, TwoQubitWeylDecomposition
from qiskit.circuit.library import CXGate
dec = TwoQubitBasisDecomposer(CXGate())
w = TwoQubitWeylDecomposition(U4)                  # U4: 4x4 ndarray
print(w.a, w.b, w.c, dec.num_basis_gates(U4))      # exact CNOT count
approx = dec(U4, basis_fidelity=0.99)              # approximate synthesis
```

Approximate synthesis maximises (fidelity of the approximant) x basis_fidelity^k over k = 0..3, so it
drops a CNOT whenever the approximation error is below that CNOT's own error. Measured: RZZ(0.02)
needs 2 CNOTs exactly and 0 at basis_fidelity = 0.99. In the transpiler the knob is
`approximation_degree`. Cirq: `cirq.two_qubit_matrix_to_cz_operations(q0, q1, U4,
allow_partial_czs=False)` (3 CZ for a random U, measured), `cirq.two_qubit_matrix_to_sqrt_iswap_operations`,
`cirq.kak_decomposition(U4).interaction_coefficients`.

Other bases: CNOT = 2 sqrt(iSWAP); a generic U(4) is 3 CZ, 3 ECR or 3 sqrt(iSWAP). With native
arbitrary-angle ZZ a generic U(4) needs at most 3 entangling interactions (XX, YY and ZZ commute,
one per Weyl coordinate), and a gate with b = c = 0 needs one.

## 4. Controlled-U by ABC decomposition

For U = e^{i alpha} RZ(beta) RY(gamma) RZ(delta) take (Nielsen-Chuang Cor. 4.2)
A = RZ(beta) RY(gamma/2), B = RY(-gamma/2) RZ(-(delta + beta)/2), C = RZ((delta - beta)/2),
so ABC = I and U = e^{i alpha} A X B X C. Controlled-U = phase gate P(alpha) on the control, and on
the target in time order C, CNOT, B, CNOT, A: 2 CNOTs + at most 3 1q gates. Dropping P(alpha) gives
a different gate (section 12).

```python
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator
th = 0.7
qc = QuantumCircuit(2); qc.ry(th/2, 1); qc.cx(0, 1); qc.ry(-th/2, 1); qc.cx(0, 1)
ref = QuantumCircuit(2); ref.cry(th, 0, 1)
assert Operator(qc).equiv(Operator(ref))           # measured True
```

- CRZ(theta) = RZ(theta/2), CX, RZ(-theta/2), CX on the target (same pattern as CRY).
- CP(lambda) = P(lambda/2) on control and target, then CX, P(-lambda/2) on the target, CX.
- CZ = (I x H) CX (I x H); CY = (I x S) CX (I x S-dagger).
- Controlled Pauli exponential: only the central RZ needs the control (section 6, worked example).
- Controlled-U^(2^k) for phase estimation: synthesise exp(-iH 2^k t) directly, never 2^k copies
  of U (`quantum-algorithm-primitives`).

## 5. Multi-controlled X and the Toffoli family

| Construction | 2q cost | T cost | Valid when |
|---|---|---|---|
| Toffoli (CCX) | 6 CX (measured) | 7 (4 T + 3 T-dagger, measured), T-depth 3 | always |
| CCZ | 6 CX | 7 | Toffoli without its two H |
| Toffoli at T-depth 1 | more CX | 7 | 4 ancillas available (Selinger 2013) |
| Margolus relative-phase Toffoli (RCCX) | 3 CX (measured) | 4 | its diagonal phase is later cancelled (uncomputed by its inverse) |
| Gidney temporary logical-AND | a few CX | 4 to compute, 0 to uncompute (X-basis measurement + classically controlled CZ) | target starts in \|0⟩ and is discarded afterwards |

Multi-controlled X with k = 6 controls, `qiskit.synthesis` functions, transpiled to cx+u at
level 1 (measured, Qiskit 2.6):

| Function | Total qubits (7 = controls + target) | CX | Depth |
|---|---|---|---|
| synth_mcx_noaux_v24 | 7 | 140 | 193 |
| synth_mcx_noaux_hp24 | 7 | 124 | 191 |
| synth_mcx_gray_code | 7 | 188 | 315 |
| synth_mcx_1_clean_b95 | 8 | 64 | 116 |
| synth_mcx_1_clean_kg24 | 8 | 30 | 56 |
| synth_mcx_1_dirty_kg24 | 8 | 54 | 99 |
| synth_mcx_2_clean_kg24 | 9 | 30 | 54 |
| synth_mcx_n_dirty_i15 | 11 | 42 | 83 |

Decision: one clean ancilla turns 120-190 CX into about 30; a dirty (borrowed, arbitrary-state)
ancilla costs about twice a clean one; no-ancilla constructions only when every qubit is busy.
Names and ancilla counts change between releases: list them with
`[n for n in dir(qiskit.synthesis) if n.startswith("synth_mcx")]`. The same names without the
`synth_mcx_` prefix are HighLevelSynthesis plugins (`high_level_synthesis_plugin_names("mcx")` from
`qiskit.transpiler.passes.synthesis.plugin`), selected with `hls_config=HLSConfig(mcx=["1_clean_kg24"])`.
Cirq's generic `cirq.decompose(cirq.X.controlled(k))` gives 8, 28 and 76 two-qubit ops for
k = 2, 3, 4 (measured): fine for simulation, useless for costing.

Fault-tolerant MCX with clean ancillas: compute a chain of k - 2 temporary ANDs (4 T each), one
Toffoli into the target (7 T), uncompute the ANDs by measurement (0 T): about 4(k - 2) + 7 T, so
23 T for k = 6 instead of 9 Toffolis x 7 = 63 T.

## 6. Pauli-string exponentials

exp(-i theta P / 2) for a Pauli string P of weight w:
1. Basis change V on each support qubit so that V P V-dagger is all-Z: X needs H; Y needs S-dagger
   then H (or RX(pi/2)); Z needs nothing.
2. CNOT ladder collecting the parity on one support qubit (w - 1 CNOTs), RZ(theta) on it, reverse
   ladder (w - 1 CNOTs): 2(w - 1) CNOTs and 2q depth 2(w - 1); a balanced tree gives 2q depth
   2 ceil(log2 w) for the same count.
3. Undo the basis change.

```python
from qiskit.circuit.library import PauliEvolutionGate
from qiskit.quantum_info import SparsePauliOp
th = 0.37                                            # exp(-i th/2 X0 Y1 Z2)
qc = QuantumCircuit(3)
qc.h(0); qc.sdg(1); qc.h(1)                          # X on q0 and Y on q1 rotated to Z
qc.cx(0, 1); qc.cx(1, 2); qc.rz(th, 2); qc.cx(1, 2); qc.cx(0, 1)
qc.h(1); qc.s(1); qc.h(0)
ref = QuantumCircuit(3)
ref.append(PauliEvolutionGate(SparsePauliOp("ZYX"), time=th/2), [0, 1, 2])   # label is little-endian: X acts on q0
assert Operator(qc).equiv(Operator(ref))             # measured True, 4 CX
```

Sequences of exponentials: neighbouring strings that share support share ladder segments, so order
the terms to make adjacent strings differ on few qubits and cancel inner CNOT pairs. Qiskit's
`LieTrotter` / `SuzukiTrotter` take `cx_structure="chain"` or `"fountain"` and `preserve_order=False`
(reorders commuting terms); PauliEvolutionGate synthesis plugins in 2.6 are `basic`, `default`,
`mcts` and `rustiq` (measured), selected with `HLSConfig(PauliEvolution=[...])`. Two-qubit
rotations: RZZ(theta) = CX, RZ(theta) on the target, CX (2 CX) unless RZZ is native;
RXX = (H x H) RZZ (H x H); RYY uses RX(pi/2) basis changes.

## 7. Rotation synthesis for fault tolerance

Gridsynth (Ross-Selinger) approximates RZ(theta) to operator-norm error eps with about
3 log2(1/eps) + O(log log(1/eps)) T gates. Measured with pygridsynth at theta = 0.2906:

| eps | 1e-3 | 1e-6 | 1e-10 | 1e-15 |
|---|---|---|---|---|
| T-count | 32 | 62 | 106 | 152 |
| 3 log2(1/eps) | 30 | 60 | 100 | 149 |

```python
import mpmath
from pygridsynth.gridsynth import gridsynth_gates
mpmath.mp.dps = 128
word = gridsynth_gates(theta=mpmath.mpf("0.2906"), epsilon=mpmath.mpf("1e-10"))   # Clifford+T word (str)
print(word.count("T"))                                                            # 106
```
Alternatives: `newsynth` (the original Haskell gridsynth). Probabilistic mixing of two
approximations (Campbell 2017; Hastings 2017) reaches the same diamond-norm error with roughly half
the T gates; repeat-until-success circuits trade ancillas and measurements for fewer T.

Error budget: N_rot rotations sharing a synthesis budget eps_synth get eps = eps_synth / N_rot each
(errors add at most linearly). Example: 1e4 rotations at eps_synth = 1e-3 give eps = 1e-7 each,
about 3 log2(1e7) = 70 T per rotation and 7e5 T in total. One arbitrary rotation therefore costs
as much as 10-15 Toffolis; prefer constructions with few distinct angles (Hamming-weight phasing,
catalysed rotations; `quantum-resource-estimation`).

## 8. Identities for hand optimisation

| Identity | Use |
|---|---|
| HZH = X, HXH = Z, S X S-dagger = Y | basis changes |
| CZ is symmetric in its two qubits | either end is the control; free relabelling |
| CNOT = (I x H) CZ (I x H) | CZ-native hardware |
| SWAP = CX(a,b) CX(b,a) CX(a,b); only CX(a,b) CX(b,a) when b is known to be \|0⟩ | moving a state |
| iSWAP = 2 CNOT + 1q; CNOT = 2 sqrt(iSWAP) + 1q; CNOT = 1 ECR + 1q | native translation |
| RZ on a CNOT control and RX on its target commute with the CNOT | push rotations through, then merge |
| CNOT(a to b) maps Z_b to Z_a Z_b and X_a to X_a X_b | Pauli propagation, error tracking |
| phase polynomial: a CNOT+RZ network maps x to e^{i sum_j theta_j f_j(x)} times the basis state Ax; rotations on the same parity f_j merge (theta_1 + theta_2), A is resynthesised separately | RZ and T-count reduction |
| a trailing qubit permutation before measurement equals relabelling the clbits | delete the SWAPs (Qiskit `ElidePermutations`) |

## 9. State preparation and generic unitaries

Parameter-counting lower bounds: an arbitrary n-qubit state needs ceil((2^n - n - 1)/2) CNOTs; a
generic n-qubit unitary needs ceil((4^n - 3n - 1)/4) (Shende-Markov-Bullock 2004). Constructions
with multiplexed rotations (Mottonen 2004; Shende-Bullock-Markov 2006) use about 2^n to 2^(n+1)
CNOTs for states, and the quantum Shannon decomposition about (23/48) 4^n for unitaries.

Measured (Qiskit 2.6, level 3, cx+u basis): random state n = 3, 4, 5 needs 4, 11, 26 CX (bounds 2,
6, 13); random unitary n = 2, 3 needs 3, 19 CX (bounds 3, 14).

- `StatePreparation(sv)` is unitary (invertible, controllable); `Initialize(sv)` adds a reset and is
  not. Use StatePreparation inside algorithms.
- Loading N = 2^n arbitrary amplitudes costs O(N) gates. Flag every algorithm (HHL, amplitude-encoded
  QML, Monte Carlo over a generic distribution) whose speedup assumes cheap data loading; it needs
  structure (efficiently integrable distributions, QROM with a stated cost) or the advantage is gone.
- Cheap structured states: GHZ (n - 1 CNOT; log depth as a fan-out tree; constant depth with
  measurement and feed-forward), W (n - 1 controlled rotations + CNOTs), uniform superposition over
  2^m states (m H gates).

## 10. Measurement and dynamic circuits

| Measure | Before the Z measurement |
|---|---|
| X basis | H |
| Y basis | S-dagger, then H |
| Pauli string P | per-qubit basis change; eigenvalue = (-1)^(parity of the measured support bits) |

```python
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
q = QuantumRegister(2); c = ClassicalRegister(1)
qc = QuantumCircuit(q, c)
qc.h(q[0]); qc.measure(q[0], c[0]); qc.reset(q[0])     # mid-circuit measurement + reset
with qc.if_test((c, 1)):                               # feed-forward
    qc.x(q[1])
```

Uses: constant-depth GHZ and fan-out (Bell pairs, parity measurements, Pauli corrections),
long-range CNOT by teleportation along an ancilla chain (constant 2q depth instead of O(distance)
SWAPs), Gidney AND uncomputation, iterative phase estimation. Before designing around them, check
`"if_else" in backend.target.operation_names` (present on FakeFez, measured), the documented
feed-forward latency, and that idle qubits get dynamical decoupling while they wait
(`quantum-noise-mitigation`).

## 11. Verification

| Size | Check |
|---|---|
| up to about 12 qubits | `Operator(qc).equiv(Operator(ref))` (ignores global phase); Cirq `cirq.testing.assert_allclose_up_to_global_phase(cirq.unitary(a), cirq.unitary(b), atol=1e-8)` |
| hand-built matrices | unitarity: norm(U^dagger U - I) < 1e-10 |
| 12 to about 28 qubits | random-input fidelity on 5-10 random product states |
| larger | MQT QCEC equivalence checking (check its current API), or checks on sub-blocks |

Random-input check: for 5-10 random product inputs (a random `u(theta, phi, lambda)` on every qubit,
fixed seed), compare `Statevector(prep.compose(qc))` with `Statevector(prep.compose(ref))` and require
abs(vdot) > 1 - 1e-9; the absolute value removes the global phase. Record `count_ops()` before and
after every rewrite and keep the check in the test suite.

## 12. Pitfalls

- A global phase becomes a relative phase once controlled: `cirq.X**0.5` and `cirq.rx(pi/2)` agree
  up to phase, but their controlled versions differ (measured). The same holds for Qiskit
  `SXGate().control()` against `RXGate(pi/2).control()`. Put the phase on the control as P(alpha).
- Ancillas left un-uncomputed stay entangled with the register and destroy interference; Grover
  and QPE then fail silently. Compute, copy, uncompute.
- CNOT counts read off the abstract circuit, before translation and routing.
- SWAPs left in front of measurements where relabelling the clbits would do.
- Qiskit Pauli labels are little-endian (`"ZYX"` puts X on qubit 0); Cirq and most papers are
  big-endian.
- Relative-phase Toffolis used where their phase is never cancelled.
- MCX synthesis names, ancilla counts and plugin defaults that change between Qiskit releases.
- Approximate synthesis (basis_fidelity or approximation_degree below 1) silently changes the
  unitary; record it next to the result.

## Worked example: controlled Pauli rotation for a Hadamard test

Task: cost C-exp(-i theta/2 X1 Y2 Z3) controlled by q0, theta = 0.37, on IBM Heron and in Clifford+T.
Key step: the basis change V and ladder L cancel when the control is off, so
C-(V-dagger L-dagger RZ L V) = V-dagger L-dagger (C-RZ) L V. Only the central rotation is
controlled, and CRZ costs 2 CX (section 4).

```python
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator, SparsePauliOp
from qiskit.circuit.library import PauliEvolutionGate
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime.fake_provider import FakeFez

th = 0.37
qc = QuantumCircuit(4)
qc.h(1); qc.sdg(2); qc.h(2); qc.cx(1, 2); qc.cx(2, 3)            # V, then ladder L
qc.rz(th/2, 3); qc.cx(0, 3); qc.rz(-th/2, 3); qc.cx(0, 3)         # CRZ(th) controlled by q0
qc.cx(2, 3); qc.cx(1, 2); qc.h(2); qc.s(2); qc.h(1)               # L-dagger, V-dagger
ref = QuantumCircuit(4)
ref.append(PauliEvolutionGate(SparsePauliOp("ZYX"), time=th/2).control(1), [0, 1, 2, 3])
print(Operator(qc).equiv(Operator(ref)), qc.count_ops()["cx"])     # True 6

be = FakeFez()
best = min((generate_preset_pass_manager(optimization_level=3, backend=be, seed_transpiler=s).run(qc)
            for s in range(10)), key=lambda t: t.num_nonlocal_gates())
print(best.num_nonlocal_gates(), best.depth(lambda i: i.operation.num_qubits == 2))   # 6 6
```

| Quantity (measured unless noted) | Value |
|---|---|
| hand circuit equals the library's controlled PauliEvolutionGate | True |
| abstract CX count | 6 = 2(w - 1) + 2 with w = 3 |
| FakeFez, level 3, best of 10 seeds | 6 CZ, 2q depth 6 (library version: also 6 and 6) |
| uncontrolled rotation (section 6) | 4 CX |
| Clifford+T at eps = 1e-10 per rotation (from the section 7 table) | 2 rotations RZ(+-theta/2), about 2 x 106 = 212 T; CNOTs free |

Reading: on NISQ hardware the control adds 2 CZ (+50%); in fault tolerance it doubles the T bill,
because the cost lives in the rotations. A Hadamard test over many Pauli terms should therefore
share one controlled block where the algorithm allows it (`quantum-algorithm-primitives`).

Related: `qiskit-transpilation`, `quantum-algorithm-primitives`, `quantum-resource-estimation`, `hamiltonian-simulation-methods`, `cirq-workflows`, hub `quantum-computing`
