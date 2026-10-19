---
name: qiskit-transpilation
description: "Qiskit 2.x transpiler workflow: preset pass managers and stages, Target and fake backends, layout and SABRE routing with seed sweeps, Heron fractional gates, AI routing passes, custom passes, layout-aware observables and equivalence checks. Load when compiling circuits to ISA form or minimising 2q count and depth after routing."
when_to_use: "Compiling a circuit for an IBM backend or a custom Target; 'too many SWAPs', 'depth exploded after transpile', 'results wrong after transpile', 'observable acts on the wrong qubits'; choosing optimization_level, layout or routing method; seed sweeps; offline tests with GenericBackendV2 or FakeFez; writing a TransformationPass or StagedPassManager hook; fractional RZZ gates on Heron; checking a transpiled circuit is equivalent to the source; porting transpile() or execute() code from Qiskit 0.x/1.x."
---

# Qiskit transpilation

A transpiled circuit can only be compared with another when backend (and calibration snapshot),
optimisation level, seed and package versions are stated. This skill turns "transpile and hope"
into a measured search over those knobs. Values marked *measured* come from qiskit 2.6.0 and
qiskit-ibm-runtime 0.50.0.

## 1. Version gate

```bash
python -c "import qiskit, qiskit_aer, qiskit_ibm_runtime as r; print(qiskit.__version__, qiskit_aer.__version__, r.__version__)"
```

| Gone in Qiskit 2.x | Use instead |
|---|---|
| BackendV1, `qiskit.providers.models`, V1 fake backends (FakeVigo, ...) | BackendV2 + `Target`; `qiskit_ibm_runtime.fake_provider` (FakeFez, FakeTorino, FakeMarrakesh, FakeKingston) or `GenericBackendV2` |
| `qiskit.pulse`, circuit calibrations | fractional gates (section 8); no pulse-level control |
| `execute()` (removed in 1.0) | `generate_preset_pass_manager(...).run(qc)` + primitives |
| V1 primitives `Sampler`, `Estimator` in qiskit.primitives | `StatevectorSampler/StatevectorEstimator`, runtime V2 primitives (`qiskit-primitives-runtime`) |
| StochasticSwap routing | routing plugins `basic`, `default`, `lookahead`, `none`, `sabre` (measured) |

Confirm any API you are unsure of with context7 (`mcp__context7__resolve-library-id`, then
`mcp__context7__query-docs`) or `inspect.signature`, never from 0.x tutorials.

```python
from qiskit_ibm_runtime.fake_provider import FakeFez      # 156-qubit Heron r2 snapshot
from qiskit.providers.fake_provider import GenericBackendV2
be = FakeFez()
print(sorted(be.target.operation_names))
# measured: cz, delay, for_loop, id, if_else, measure, reset, rz, switch_case, sx, x
gb = GenericBackendV2(num_qubits=4, basis_gates=["cz", "rz", "sx", "x"],
                      coupling_map=[[0, 1], [1, 0], [1, 2], [2, 1], [2, 3], [3, 2]], seed=3)
```

## 2. Preset pass managers and stages

```python
from qiskit.transpiler import generate_preset_pass_manager
pm = generate_preset_pass_manager(optimization_level=3, backend=be, seed_transpiler=7)  # or target=...
isa = pm.run(qc)
pm.stages      # ('init', 'layout', 'routing', 'translation', 'optimization', 'scheduling'), measured
```
Other keywords: `layout_method` (plugins `default`, `dense`, `sabre`, `trivial`, measured),
`routing_method`, `translation_method`, `scheduling_method`, `initial_layout`, `approximation_degree`
(1.0 exact; below 1 allows approximate 2q synthesis), `hls_config`. The default optimisation level
is 2 (measured signature); code written for 1.x may silently assume 1. List stage plugins with
`qiskit.transpiler.preset_passmanagers.plugin.list_stage_plugins("routing")`.

| Level | Optimisation stage | Use |
|---|---|---|
| 0 | none: layout, routing and translation only | debugging, reproducing a reference |
| 1 | 1q merging, inverse cancellation, VF2PostLayout | fast iteration |
| 2 (default) | + commutation analysis and cancellation, more layout/routing trials | general use |
| 3 | + 2q block consolidation and resynthesis (ConsolidateBlocks + UnitarySynthesis), most trials | final circuits; compile time grows |

Stage roles: init (unroll 3q+ gates, high-level synthesis), layout (perfect embedding by VF2Layout,
else SabreLayout), routing (SabreSwap inserts SWAPs), translation (BasisTranslator to the Target),
optimization (loops until depth and size stop shrinking), scheduling (only when requested).

## 3. Targets from data

```python
from qiskit.transpiler import Target, CouplingMap, InstructionProperties
from qiskit.circuit import Parameter
from qiskit.circuit.library import CZGate, RZGate, SXGate, XGate, Measure

cm = CouplingMap.from_heavy_hex(3)            # also from_grid(r, c), from_line(n)
t1 = Target.from_configuration(basis_gates=["cz", "rz", "sx", "x", "measure"],
                               num_qubits=cm.size(), coupling_map=cm)

t2 = Target(num_qubits=3)                     # per-qubit and per-pair errors from published calibrations
t2.add_instruction(CZGate(), {(0, 1): InstructionProperties(error=3e-3, duration=68e-9),
                              (1, 0): InstructionProperties(error=3e-3, duration=68e-9),
                              (1, 2): InstructionProperties(error=8e-3, duration=68e-9),
                              (2, 1): InstructionProperties(error=8e-3, duration=68e-9)})
t2.add_instruction(RZGate(Parameter("t")), {(q,): InstructionProperties(error=0.0, duration=0.0) for q in range(3)})
t2.add_instruction(SXGate(), {(q,): InstructionProperties(error=2e-4, duration=32e-9) for q in range(3)})
t2.add_instruction(XGate(), {(q,): InstructionProperties(error=2e-4, duration=32e-9) for q in range(3)})
t2.add_instruction(Measure(), {(q,): InstructionProperties(error=1.5e-2, duration=1.5e-6) for q in range(3)})
```
Add both orientations of symmetric gates. Topology dominates routing cost: heavy-hex (degree 3)
needs far more SWAPs than a square lattice (degree 4) or all-to-all ions for dense interaction
graphs (QFT, QAOA on dense graphs). When choosing hardware, transpile against each Target and
compare section 5 metrics instead of reasoning about qubit counts.

## 4. Layout and routing with seed sweeps

SabreLayout and SabreSwap are randomised; VF2Layout finds a perfect subgraph embedding when one
exists (then routing adds no SWAPs); VF2PostLayout re-maps a routed circuit onto lower-error qubits.

```python
def sweep(qc, be, level, seeds=range(20)):
    rows = []
    for s in seeds:
        t = generate_preset_pass_manager(optimization_level=level, backend=be, seed_transpiler=s).run(qc)
        rows.append((t.num_nonlocal_gates(), -est_success(t, be.target), s, t))
    return min(rows, key=lambda r: r[:2])     # fewest 2q gates, then highest estimated success
```
- 10-50 seeds; stop early when the best has not improved for 10 seeds. Report min/median/max, not
  only the best.
- Alternative: a custom pass manager with `SabreLayout(coupling_map, seed=, max_iterations=3,
  swap_trials=, layout_trials=)` (measured signature) to raise trials inside one run.
- If VF2 finds a perfect layout, seeds stop mattering (worked example: spread 0); when SWAPs are
  needed the seeds give different SWAP counts, so measure the spread rather than assuming it.

## 5. Metrics script

```python
def est_success(t, target):
    """Product of (1 - error) over every instruction with a known error: a ranking proxy, not a fidelity."""
    p = 1.0
    for inst in t.data:
        name = inst.operation.name
        if name in target.operation_names:
            qargs = tuple(t.find_bit(q).index for q in inst.qubits)
            props = target[name].get(qargs)
            if props is not None and props.error is not None:
                p *= 1 - props.error
    return p

def report(t, target):
    return dict(ops=dict(t.count_ops()), n2q=t.num_nonlocal_gates(),
                depth2q=t.depth(lambda i: i.operation.num_qubits == 2),
                depth=t.depth(), est_success=round(est_success(t, target), 4))
```
Always state backend (for fakes the qiskit-ibm-runtime version, since snapshots change),
optimisation level and seed. est_success ignores idle decoherence, crosstalk and leakage; it is an
upper bound for ranking candidates.

## 6. Layout bookkeeping

```python
L = isa.layout                                  # TranspileLayout
L.initial_index_layout(filter_ancillas=True)    # virtual qubit i -> physical qubit at the start
L.final_index_layout()                          # virtual qubit i -> physical qubit at the end
L.routing_permutation()                         # permutation applied by routing SWAPs
obs_isa = obs.apply_layout(L)                   # SparsePauliOp on all device qubits (156 on FakeFez, measured)
```
- Measured clbits keep logical order, so counts need no remapping.
- Statevector and Operator comparisons do: `Operator.from_circuit(isa)` undoes the initial layout and
  the final permutation (measured equivalent for a routed 4-qubit circuit).
- Estimator observables must go through `apply_layout`; skipping it measures the wrong physical
  qubits without any error (`qiskit-primitives-runtime`).

## 7. Parameterised circuits

```python
from qiskit.circuit import ParameterVector
theta = ParameterVector("θ", 8)
isa = pm.run(ansatz)                                    # once, with free parameters
assert set(ansatz.parameters) == set(isa.parameters)   # measured True for rx(p) + cx at level 3
# every optimiser step: estimator.run([(isa, obs_isa, values)]), no re-transpilation
```
Re-transpiling inside an optimiser loop costs seconds per call and can change the layout between
iterations, which adds noise to the objective. If optimisation removes a parameter (it commuted into
a no-op), the binding array no longer matches: keep the assertion. Column order of bound values is
`list(isa.parameters)` (sorted by name; ParameterVector elements by index).

## 8. Heron fractional gates

```python
from qiskit_ibm_runtime import QiskitRuntimeService
service = QiskitRuntimeService()
be = service.backend("ibm_fez", use_fractional_gates=True)   # keyword verified in qiskit-ibm-runtime 0.50
print("rzz" in be.target.operation_names, "rx" in be.target.operation_names)
```
The backend then exposes RZZ(theta) (documented angle range 0 < theta <= pi/2; check the current
docs) and RX(theta). Each ZZ rotation in a Trotter or QAOA layer becomes one native 2q gate instead
of 2 CZ, roughly halving 2q count and depth. Angle identities if your version does not fold angles
automatically: RZZ(-theta) = (X x I) RZZ(theta) (X x I), and RZZ(theta) = RZZ(theta - pi)(Z x Z) up
to global phase for theta in (pi/2, pi]. Check the current docs for incompatibilities with dynamic
circuits, with some twirling and error-mitigation options, and for whether angles must be bound
before submission.

## 9. Optional plugin passes

- qiskit-ibm-transpiler: AI routing and AI synthesis passes (Clifford, linear-function,
  permutation, Pauli-network), in local or cloud service mode. Not installed in the measurement
  environment; take class names and install extras from the package docs for your version.
- Unitary-synthesis plugins (`unitary_synthesis_method=`), HighLevelSynthesis plugins
  (`hls_config=HLSConfig(...)`, MCX plugin list in `quantum-circuit-decomposition`), layout and
  routing stage plugins (`list_stage_plugins`).
- Adoption rule: run plugin and preset baseline on the same circuits and the same 20 seeds; adopt
  only if the median 2q count (or est_success) improves and the section 11 check passes. Report both.

## 10. Custom passes

```python
from qiskit.transpiler import PassManager
from qiskit.transpiler.basepasses import AnalysisPass, TransformationPass

class CountRZZ(AnalysisPass):
    def run(self, dag):
        self.property_set["n_rzz"] = sum(1 for n in dag.op_nodes() if n.op.name == "rzz")

class DropTinyRZ(TransformationPass):
    """Remove bound RZ(theta) with abs(theta) < tol (changes the unitary by O(tol))."""
    def __init__(self, tol=1e-9):
        super().__init__()
        self.tol = tol
    def run(self, dag):
        for node in dag.op_nodes():
            if node.op.name == "rz" and not node.op.is_parameterized() and abs(float(node.op.params[0])) < self.tol:
                dag.remove_op_node(node)
        return dag

pm = generate_preset_pass_manager(optimization_level=2, backend=be, seed_transpiler=1)
pm.post_optimization = PassManager([DropTinyRZ(1e-9), CountRZZ()])
```
Hooks exist as `pre_<stage>` and `post_<stage>` for every stage (pre_init, pre_layout,
post_routing, post_optimization measured). Analysis passes write to `property_set`; later passes
read it. Unit-test every transformation pass on its own:

```python
out = PassManager([DropTinyRZ(1e-9)]).run(qc)
assert Operator(out).equiv(Operator(qc), atol=1e-8)
```

## 11. Equivalence checks

| Width | Method |
|---|---|
| up to about 12 qubits | `Operator(qc.remove_final_measurements(inplace=False)).equiv(Operator.from_circuit(isa_without_measurements))` |
| up to about 28 qubits | random-input statevector fidelity, mapping qubits with the layout |
| larger or structured | `mqt.qcec` equivalence checking (check its current API and how it treats ancillas and layouts) |

`Operator.from_circuit` on an ISA circuit for a 156-qubit backend builds a 156-qubit operator, which
is impossible: test passes and pass managers against a small `GenericBackendV2` or hand-built
`Target` with the same basis and a similar topology, and keep those tests in CI.

## 12. Worked example: GHZ-12 on FakeFez, levels 1 and 3, 20 seeds

```python
import numpy as np
from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime.fake_provider import FakeFez

be = FakeFez()
n = 12
qc = QuantumCircuit(n); qc.h(0)
for i in range(n - 1):
    qc.cx(i, i + 1)
qc.measure_all()                                    # measurements before transpiling
for level in (1, 3):
    rows = []
    for seed in range(20):
        t = generate_preset_pass_manager(optimization_level=level, backend=be, seed_transpiler=seed).run(qc)
        rows.append((t.num_nonlocal_gates(), -est_success(t, be.target), seed, t))
    n2q = [r[0] for r in rows]
    best = min(rows, key=lambda r: r[:2]); t = best[3]
    print(level, min(n2q), np.median(n2q), max(n2q), t.depth(lambda i: i.operation.num_qubits == 2),
          round(-best[1], 3), best[2], dict(t.count_ops()), t.layout.initial_index_layout(filter_ancillas=True))
```

Measured (qiskit 2.6.0, FakeFez from qiskit-ibm-runtime 0.50.0):

| | Level 1 | Level 3 |
|---|---|---|
| CZ count, min / median / max over 20 seeds | 11 / 11 / 11 | 11 / 11 / 11 |
| 2q depth | 11 | 11 |
| other ops | rz 46, sx 23, measure 12 | rz 35, sx 23, measure 12 |
| est_success (product of 1 - error), every seed | 0.843 | 0.884 |
| physical qubits | 0-11 (one row of the lattice) | 146, 147, 137, 127, 126, 125, 124, 123, 136, 143, 142, 141 |

Reading:
- 11 CZ = n - 1: a perfect line embedding exists, so no SWAPs and zero spread across seeds.
- Level 3 gains through qubit choice (est_success +0.041) and 1q cleanup, not through 2q count.
- 2q depth 11 is the chain's own depth. Growing the GHZ outwards from the middle qubit along the
  same line (two branches of 5 and 6 CNOTs in parallel) gives 2q depth 6 at the same CZ count: an
  algorithmic change beats every transpiler knob here.
- est_success includes the 12 readout errors; it is a ranking proxy, not a predicted fidelity.

## 13. Pitfalls

- Barriers block optimisation across them; remove them (`RemoveBarriers`) unless they are needed.
- `measure_all()` added after transpiling: it measures all 156 device qubits into a new register and
  the result no longer matches the logical circuit. Add measurements first.
- Levels or plugins compared on a single seed.
- Gates counted on a non-ISA circuit.
- Observables not passed through `apply_layout`.
- `Operator` built on full-width ISA circuits; test on small Targets instead.
- Fake backends are calibration snapshots that drift between qiskit-ibm-runtime versions; record
  the version with every number.
- Old code relying on the former default optimisation level (now 2).

Related: `qiskit-primitives-runtime`, `quantum-circuit-decomposition`, `quantum-noise-mitigation`, `quantum-circuit-simulators`, hub `quantum-computing`
