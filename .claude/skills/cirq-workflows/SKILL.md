---
name: cirq-workflows
description: "Google Cirq: qubits, moments and circuits, gates and decompositions, simulators (cirq.Simulator, DensityMatrixSimulator, qsim), noise models, parameter sweeps with sympy, transformers, device constraints and OpenQASM interop. Load when writing, simulating or porting Cirq code."
when_to_use: "Writing, simulating or debugging Cirq code; 'moment structure looks wrong', 'histogram bit order', 'unresolved symbol', 'operation not valid on device'; choosing Simulator, DensityMatrixSimulator or qsim; sympy parameter sweeps with run_sweep; noise models; compiling to CZ or sqrt-iSWAP gatesets; routing onto a device graph; JSON serialisation; moving circuits between Cirq, Qiskit (OpenQASM 2) and OpenFermion."
---

# Cirq workflows

Cirq's model is explicit: a Circuit is a list of Moments, each a set of operations on disjoint
qubits, and every compiled, routed or noisy circuit is a transformation of that list. Values marked
*measured* come from Cirq 1.7.0 (cirq-core) with NumPy 2 on Python 3.13.

```bash
python -c "import cirq; print(cirq.__version__)"   # cirq-google and qsimcirq are separate packages
```

## 1. Core objects

| Object | Construct | Notes |
|---|---|---|
| LineQubit | `cirq.LineQubit(3)`, `cirq.LineQubit.range(n)` | 1D, ordered by index |
| GridQubit | `cirq.GridQubit(r, c)`, `cirq.GridQubit.rect(rows, cols)` | Google device layouts |
| NamedQubit | `cirq.NamedQubit("anc")` | ordered by name |
| Moment | `cirq.Moment([ops])` | operations on disjoint qubits, one time slice |
| Circuit | `cirq.Circuit(ops_or_moments)`, `.append(ops, strategy=...)` | ordered list of moments |

`cirq.InsertStrategy` members: EARLIEST (default for append), NEW, INLINE, NEW_THEN_INLINE, LATEST
(measured). EARLIEST slides each operation to just after the last moment touching its qubits, so the
order of appends decides the packing: ZZ gates on the 4-cycle edges appended as (0,1), (1,2), (2,3),
(3,0) take 4 moments; as (0,1), (2,3), (1,2), (3,0) they take 2.

Qubit order and endianness: Cirq sorts qubits, and the first qubit is the most significant bit of
state-vector indices and histogram integers (measured: X on q0, then `cirq.measure(q0, q1, key="m")`
gives histogram key 2 = binary 10). Qiskit is the opposite.

```python
import cirq, numpy as np, sympy
q = cirq.LineQubit.range(3)
c = cirq.Circuit(cirq.H(q[0]), cirq.CNOT(q[0], q[1]), cirq.CNOT(q[1], q[2]), cirq.measure(*q, key="m"))
print(c)                 # text diagram
print(len(c))            # number of moments: 4
```

## 2. Gates and operations

| Family | Examples | Convention |
|---|---|---|
| Paulis, Clifford, T | `cirq.X, Y, Z, H, S, T` | |
| rotations | `cirq.rx(rads)`, `ry`, `rz` | exp(-i θ P/2) |
| power gates | `cirq.X**t` (XPowGate), `cirq.ZZPowGate(exponent=t)`, `cirq.CZ**t` | eigenphase convention: equal to rotations only up to global phase |
| 2q | `cirq.CNOT`, `cirq.CZ`, `cirq.SWAP`, `cirq.ISWAP`, `cirq.ISWAP**0.5`, `cirq.FSimGate(theta, phi)` | |
| 3q | `cirq.CCX` (TOFFOLI), `cirq.CCZ` | |
| arbitrary | `cirq.MatrixGate(U)` | check unitarity first |
| 1q native | `cirq.PhasedXZGate(x_exponent=, z_exponent=, axis_phase_exponent=)` | Google 1q gate |
| controlled | `gate.controlled(num_controls=k)`, `op.controlled_by(q)`, `cirq.ControlledGate(gate, k)` | |

ZZPowGate: ZZ**t = diag(1, e^(iπt), e^(iπt), 1), which equals exp(-i (πt/2) Z x Z) up to global phase.
The QAOA factor exp(-iγ(1 - ZZ)/2) is therefore `cirq.ZZPowGate(exponent=-gamma/np.pi)` up to phase.

Decomposition and inspection: `cirq.decompose(op)` (to default gates), `cirq.decompose_once`,
`cirq.unitary(circuit)` (big-endian), `cirq.kak_decomposition(U)`,
`cirq.two_qubit_matrix_to_cz_operations(q0, q1, U, allow_partial_czs=False)` (3 CZ for a random U,
measured), `cirq.single_qubit_matrix_to_phxz(U)`. Generic multi-controlled decompositions are
expensive: `cirq.decompose(cirq.X.controlled(k))` gives 8, 28 and 76 two-qubit ops for k = 2, 3, 4
(measured); cost them with `quantum-circuit-decomposition` instead.

Global phase trap (measured): `cirq.X**0.5` and `cirq.rx(np.pi/2)` are equal up to phase, but
`cirq.ControlledGate(cirq.X**0.5)` and `cirq.ControlledGate(cirq.rx(np.pi/2))` differ.

## 3. Simulation

| Simulator | Key calls | Use |
|---|---|---|
| `cirq.Simulator(seed=)` | `.run(c, repetitions=)` samples; `.simulate(c)` gives `final_state_vector`; `.simulate_expectation_values(c, observables=[...])` | pure states up to about 25 qubits |
| `cirq.DensityMatrixSimulator(noise=, seed=)` | `.run`, `.simulate` gives `final_density_matrix` | exact noise up to about 12-14 qubits (complex64: 4^14 x 8 B = 2 GB) |
| `qsimcirq.QSimSimulator()` (`pip install qsimcirq`) | same interface | fast multithreaded C++ statevector, about 30+ qubits |
| `cirq.Simulator` with noisy circuits | trajectories for channels with mixtures | larger noisy circuits |
| `cirq.CliffordSimulator`, stim via stimcirq | stabilizer | Clifford-only circuits |

- `run` samples measurements: `result.measurements["m"]` is a (repetitions, bits) array;
  `result.histogram(key="m")` is a Counter of big-endian integers; `result.data` is a DataFrame.
- `simulate` returns the exact state, but measurements inside the circuit still collapse randomly:
  strip them (`c[:-1]` when the last moment is the measurement) for exact amplitudes.
- Expectation values without sampling: build a PauliSum, e.g.
  `obs = sum(0.5 - 0.5 * cirq.Z(a) * cirq.Z(b) for a, b in edges)`, and call
  `cirq.Simulator().simulate_expectation_values(circuit_without_measurements, observables=[obs])`.

## 4. Parameters and sweeps

```python
g, b = sympy.symbols("gamma beta")
op1 = cirq.rx(2 * b).on(q[0])                          # sympy expressions are allowed in angles
op2 = cirq.ZZPowGate(exponent=-g / np.pi).on(q[0], q[1])
sweep = cirq.Linspace("gamma", 0, np.pi/2, 9) * cirq.Linspace("beta", 0, np.pi/4, 9)   # Product: 81 points
zipped = cirq.Points("gamma", [0.1, 0.2]) + cirq.Points("beta", [0.3, 0.4])            # Zip: 2 points
resolved = cirq.resolve_parameters(circuit, {"gamma": 0.785, "beta": 0.393})
results = cirq.Simulator(seed=7).run_sweep(circuit, params=sweep, repetitions=2000)
for r in results:
    r.params.param_dict, r.measurements["m"]
```
`*` builds `cirq.Product`, `+` builds `cirq.Zip` (measured). Check for leftovers with
`cirq.is_parameterized(c)` and `cirq.parameter_names(c)` before simulating or exporting.

## 5. Noise

| Channel | Call | Meaning |
|---|---|---|
| depolarizing | `cirq.depolarize(p)` | X, Y, Z each with probability p/3 |
| asymmetric Pauli | `cirq.asymmetric_depolarize(p_x, p_y, p_z)` | biased noise |
| amplitude damping | `cirq.amplitude_damp(gamma)` | T1-type decay |
| phase damping | `cirq.phase_damp(gamma)` | T2-type dephasing |
| bit and phase flip | `cirq.bit_flip(p)`, `cirq.phase_flip(p)` | readout error model: bit_flip just before measurement |

Noise models: `cirq.ConstantQubitNoiseModel(cirq.depolarize(p))` adds the channel to every qubit after
every moment, idle qubits included; `circuit.with_noise(channel)` does the same to one circuit;
`cirq.NoiseModel.from_noise_model_like(x)` converts a channel or model; subclass `cirq.NoiseModel`
and implement `noisy_operation` for gate-dependent noise. Sanity checks: p = 0 reproduces the ideal
result, and large p drives expectation values to their maximally mixed value.

## 6. Transformers

```python
opt = cirq.optimize_for_target_gateset(resolved, gateset=cirq.CZTargetGateset())   # or cirq.SqrtIswapTargetGateset()
opt = cirq.merge_single_qubit_gates_to_phxz(opt)
opt = cirq.drop_negligible_operations(opt)
opt = cirq.drop_empty_moments(opt)
assert cirq.allclose_up_to_global_phase(cirq.unitary(opt), cirq.unitary(resolved))
```
Other transformers: `cirq.eject_z`, `cirq.eject_phased_paulis`, `cirq.stratified_circuit` (separate
1q and 2q layers), `cirq.synchronize_terminal_measurements`, `cirq.expand_composite`,
`cirq.merge_k_qubit_unitaries`.

Routing onto a device graph (networkx graph whose nodes are qubits):
```python
import networkx as nx
G = nx.Graph([(q4[i], q4[i + 1]) for i in range(3)])              # 4-qubit line
routed, initial_map, swap_map = cirq.RouteCQC(G).route_circuit(unitary_part)   # lookahead_radius=8 default
cirq.testing.assert_circuits_have_same_unitary_given_final_permutation(routed, unitary_part, qubit_map=swap_map)
```
Route the unitary part (the measured example routed the circuit without its 4-qubit measurement),
then add measurements on the mapped qubits.

Custom transformer:
```python
@cirq.transformer
def drop_tiny_rz(circuit: cirq.AbstractCircuit, *, context: cirq.TransformerContext | None = None, atol: float = 1e-9):
    def keep(op, _):
        g = op.gate
        if isinstance(g, cirq.ZPowGate) and not cirq.is_parameterized(op) and abs(g.exponent) < atol:
            return []
        return op
    return cirq.map_operations(circuit, keep).unfreeze(copy=False)
```

## 7. Devices, serialisation, OpenQASM

- Hardware constraints: cirq-google device objects carry the gateset and qubit graph; validate with
  `device.validate_circuit(circuit)` and take the routing graph from `device.metadata.nx_graph`.
  Access to current processors goes through cirq-google's engine API and needs Google Cloud access;
  check that package's version and docs.
- JSON: `s = cirq.to_json(circuit)` (or pass a file path), `cirq.read_json(json_text=s)`; the
  round trip compares equal (measured). Store circuits as JSON in out_dir for reproducibility.
- OpenQASM export: `cirq.qasm(circuit)` emits OpenQASM 2.0 (measured header "// Generated from Cirq
  v1.7.0", "OPENQASM 2.0;"); `cirq.qasm(circuit, args=cirq.QasmArgs(version="3.0"))` targets 3.0
  (check feature coverage).
- OpenQASM import: `from cirq.contrib.qasm_import import circuit_from_qasm` needs the `ply` package
  (measured ModuleNotFoundError without it).

## 8. Interop with Qiskit and OpenFermion

```python
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator
qc = QuantumCircuit.from_qasm_str(cirq.qasm(resolved))           # handles Cirq's 'sx' gate
print(Operator(cirq.unitary(resolved)).equiv(Operator(qc)))                  # False: endianness
print(Operator(cirq.unitary(resolved)).equiv(Operator(qc).reverse_qargs()))  # True (measured)
```
`qiskit.qasm2.loads(cirq.qasm(c))` fails with "'sx' is not defined in this scope" (measured); pass
`custom_instructions=qiskit.qasm2.LEGACY_CUSTOM_INSTRUCTIONS` or use `QuantumCircuit.from_qasm_str`.
Qiskit to Cirq: `qiskit.qasm2.dumps(qc)`, then `circuit_from_qasm`. OpenQASM 2 does not carry
mid-circuit control flow well; keep dynamic circuits native.

OpenFermion builds on Cirq qubits: map fermionic operators with `openfermion.jordan_wigner` (or
`bravyi_kitaev`), convert the resulting QubitOperator to a `cirq.PauliSum`
(`openfermion.qubit_operator_to_pauli_sum`; check the name in your openfermion version), and use
OpenFermion's circuit primitives (Givens rotations, Trotter steps) on LineQubits. Chemistry mapping
choices: `quantum-chemistry-mapping`.

## 9. Worked example: QAOA MaxCut on a 4-cycle, parameter sweep with noisy simulation

Reference (p = 1, 2-regular triangle-free graphs; Wang et al. 2018 formula): with U_C = exp(-iγC),
C = Σ_edges (1 - Z_u Z_v)/2 and U_B = exp(-iβ Σ X), each edge gives
⟨C_uv⟩ = 1/2 + (1/4) sin 4β sin 2γ, at most 3/4 at γ = π/4, β = π/8. The 4-cycle therefore reaches
⟨C⟩ = 3 out of a maximum cut of 4 (ratio 0.75).

```python
import cirq, sympy, numpy as np, networkx as nx
q = cirq.LineQubit.range(4)
edges = [(0, 1), (2, 3), (1, 2), (3, 0)]                 # ordered to pack into 2 moments
g, b = sympy.symbols("gamma beta")
circuit = cirq.Circuit(
    cirq.H.on_each(*q),
    [cirq.ZZPowGate(exponent=-g / np.pi).on(q[i], q[j]) for i, j in edges],   # exp(-i g (1 - ZZ)/2)
    cirq.rx(2 * b).on_each(*q),                                               # exp(-i b X)
    cirq.measure(*q, key="m"))
sweep = cirq.Linspace("gamma", 0, np.pi/2, 9) * cirq.Linspace("beta", 0, np.pi/4, 9)
cut = lambda x: sum(int(x[i] != x[j]) for i, j in edges)

def best(sim, reps=2000):
    out = []
    for r in sim.run_sweep(circuit, params=sweep, repetitions=reps):
        out.append((np.mean([cut(x) for x in r.measurements["m"]]),
                    r.params.param_dict["gamma"], r.params.param_dict["beta"]))
    return max(out)

print(len(circuit), best(cirq.Simulator(seed=7)))
noisy = cirq.DensityMatrixSimulator(noise=cirq.ConstantQubitNoiseModel(cirq.depolarize(0.01)), seed=7)
print(best(noisy))

unitary_part = cirq.resolve_parameters(circuit[:-1], {"gamma": np.pi/4, "beta": np.pi/8})
def exact_cut(sim):                                          # exact <C> from the density-matrix diagonal
    p = np.real(np.diag(sim.simulate(unitary_part).final_density_matrix))
    return sum(p[x] * cut([(x >> (3 - k)) & 1 for k in range(4)]) for x in range(16))
print(exact_cut(cirq.DensityMatrixSimulator()), exact_cut(noisy))
obs = sum(0.5 - 0.5 * cirq.Z(q[i]) * cirq.Z(q[j]) for i, j in edges)
print(cirq.Simulator().simulate_expectation_values(unitary_part, observables=[obs]))
```

Measured (Cirq 1.7.0):

| Quantity | Value |
|---|---|
| moments (H, 2 ZZ layers, RX, measure) | 5 |
| ideal sweep, 81 points x 2000 shots, best point | ⟨C⟩ = 3.028 at γ = 0.7854 (π/4), β = 0.3927 (π/8) |
| depolarize(0.01) after every moment, best point | ⟨C⟩ = 2.931 at the same γ, β |
| exact ⟨C⟩ at the optimum: ideal, p = 0.01, p = 0.03 | 3.0000, 2.9165, 2.7671 (ratios 0.750, 0.729, 0.692) |
| `simulate_expectation_values` with the PauliSum, ideal | 3.0 |
| CZ gateset after transformers | 8 CZ (2 per ZZ), 9 moments, unitary preserved |
| `RouteCQC` onto a 4-qubit line | 2 SWAPs inserted; permutation-aware equivalence check passed |

Reading: the sampled grid maximum (3.028) sits above the exact 3.0 because the best of 81 noisy
estimates is biased upwards (winner's curse); re-measure the chosen point with fresh shots before
reporting (`quantum-measurement-estimation`). Noise at p = 0.01 per qubit per moment costs 2.8% of
⟨C⟩ and p = 0.03 costs 7.8%; on a line-connected device the 2 routing SWAPs (6 more CZ) add to that.
Compare against the classical answer (brute force: maxcut 4) before any claim
(`variational-quantum-algorithms`).

## 10. Pitfalls

- Histogram integers and `cirq.unitary` are big-endian; Qiskit is little-endian, so cross-SDK
  comparisons need `reverse_qargs()` or reversed bitstrings.
- Power gates and rotations differ by a global phase that becomes relative once controlled.
- Unresolved sympy symbols at simulation or export time; check `cirq.is_parameterized`.
- `simulate()` on circuits with measurements gives a random collapsed state.
- `ConstantQubitNoiseModel` also hits idle qubits and the measurement moment; make sure that is
  the intended model.
- Moment packing depends on append order; depth comparisons need the same construction.
- DensityMatrixSimulator memory grows as 4^n; switch to trajectories or qsim beyond about 12-14 qubits.
- cirq-google, qsimcirq and the QASM importer's `ply` dependency are not part of cirq-core.

Related: `quantum-circuit-simulators`, `quantum-circuit-decomposition`, `variational-quantum-algorithms`, `quantum-noise-mitigation`, `quantum-chemistry-mapping`, hub `quantum-computing`
