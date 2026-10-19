# SDK snippets

These target the current major lines (Qiskit 2.x with Aer and IBM Runtime, Cirq 1.x, PennyLane,
CUDA-Q, Stim). APIs drift: print the installed versions, run the snippet, and check the docs via
context7 when anything fails. Never paste credentials into code; IBM Runtime and cloud backends
read saved accounts configured outside the repository.

```bash
python -c "import qiskit, qiskit_aer; print(qiskit.__version__, qiskit_aer.__version__)"
python -c "import cirq; print(cirq.__version__)"
python -c "import pennylane as qml; print(qml.__version__)"
python -c "import cudaq; print(cudaq.__version__)"
python -c "import stim, pymatching; print(stim.__version__, pymatching.__version__)"
```

## 1. Qiskit

Exact state, sampling and expectation values locally:

```python
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector, SparsePauliOp, Operator
from qiskit.primitives import StatevectorSampler, StatevectorEstimator

bell = QuantumCircuit(2)
bell.h(0)
bell.cx(0, 1)
print(Statevector(bell).probabilities_dict())          # {'00': 0.5, '11': 0.5}

meas = bell.copy()
meas.measure_all()                                     # classical register named 'meas'
res = StatevectorSampler(seed=7).run([meas], shots=4000).result()
print(res[0].data.meas.get_counts())

ev = StatevectorEstimator().run([(bell, SparsePauliOp("ZZ"))]).result()[0].data.evs
print(ev)                                              # 1.0
```

Noisy simulation with Aer:

```python
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error, ReadoutError
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

nm = NoiseModel()
nm.add_all_qubit_quantum_error(depolarizing_error(1e-3, 1), ["sx", "x"])
nm.add_all_qubit_quantum_error(depolarizing_error(1e-2, 2), ["cx"])
nm.add_all_qubit_readout_error(ReadoutError([[0.98, 0.02], [0.05, 0.95]]))

pm = generate_preset_pass_manager(optimization_level=1, basis_gates=["rz", "sx", "x", "cx"],
                                  seed_transpiler=7)
tqc = pm.run(meas)
sim = AerSimulator(noise_model=nm, seed_simulator=7)
print(sim.run(tqc, shots=4000).result().get_counts())
print(tqc.count_ops(), tqc.depth(lambda inst: inst.operation.num_qubits == 2))
```

Hardware through IBM Runtime (primitives V2, ISA circuits):

```python
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler, EstimatorV2 as Estimator

service = QiskitRuntimeService()                       # uses a saved account
backend = service.least_busy(operational=True, simulator=False)
pm = generate_preset_pass_manager(optimization_level=3, backend=backend, seed_transpiler=7)
isa = pm.run(meas)
counts = Sampler(mode=backend).run([isa], shots=4000).result()[0].data.meas.get_counts()

isa_bell = pm.run(bell)
obs = SparsePauliOp("ZZ").apply_layout(isa_bell.layout)   # map observable to physical qubits
est = Estimator(mode=backend)
est.options.resilience_level = 1                       # readout mitigation; 2 adds ZNE
print(est.run([(isa_bell, obs)]).result()[0].data.evs)
```

Equivalence after transpilation (small circuits): `Operator.from_circuit(tqc)` accounts for the
layout permutation; compare with `Operator(bell).equiv(...)`. For larger circuits use MQT QCEC.

## 2. Cirq

```python
import cirq

q = cirq.LineQubit.range(2)
c = cirq.Circuit(cirq.H(q[0]), cirq.CNOT(q[0], q[1]), cirq.measure(*q, key="m"))
r = cirq.Simulator(seed=7).run(c, repetitions=4000)
print(r.histogram(key="m"))            # integer keys; q[0] is the most significant bit

psi = cirq.Simulator().simulate(c[:-1]).final_state_vector    # drop the measurement moment
noisy = c.with_noise(cirq.depolarize(p=0.01))
print(cirq.DensityMatrixSimulator(seed=7).run(noisy, repetitions=4000).histogram(key="m"))
print(cirq.unitary(c[:-1]))            # unitary of a measurement-free circuit
```

## 3. PennyLane

```python
import pennylane as qml
from pennylane import numpy as pnp

dev = qml.device("default.qubit", wires=2)

@qml.qnode(dev)
def circuit(theta):
    qml.RY(theta, wires=0)
    qml.CNOT(wires=[0, 1])
    return qml.expval(qml.PauliZ(1))

theta = pnp.array(0.3, requires_grad=True)
print(circuit(theta), qml.grad(circuit)(theta))   # cos(0.3) = 0.9553, -sin(0.3) = -0.2955
print(qml.draw(circuit)(theta))
```

Finite shots: the configuration point has moved between releases (device-level `shots=` in older
versions, QNode-level in newer ones); check the installed version's docs. Use `lightning.qubit`
(C++) or `lightning.gpu` for speed, `default.mixed` for density-matrix noise.

## 4. CUDA-Q

```python
import cudaq
from cudaq import spin

cudaq.set_target("qpp-cpu")            # "nvidia" for GPU statevector, "tensornet" for tensor networks

@cudaq.kernel
def bell():
    q = cudaq.qvector(2)
    h(q[0])
    x.ctrl(q[0], q[1])
    mz(q)

print(cudaq.sample(bell, shots_count=4000))

@cudaq.kernel
def ansatz(theta: float):
    q = cudaq.qvector(2)
    x(q[0])
    ry(theta, q[1])
    x.ctrl(q[1], q[0])

H = (5.907 - 2.1433 * spin.x(0) * spin.x(1) - 2.1433 * spin.y(0) * spin.y(1)
     + 0.21829 * spin.z(0) - 6.125 * spin.z(1))         # deuteron toy Hamiltonian
print(cudaq.observe(ansatz, H, 0.59).expectation())     # about -1.75
```

## 5. Stim and PyMatching

See [error-correction reference](error-correction.md) section 5 for the full pipeline.

```python
import stim
c = stim.Circuit("""
    H 0
    CNOT 0 1
    M 0 1
    DETECTOR rec[-1] rec[-2]
""")
print(c.compile_detector_sampler(seed=7).sample(5))     # all False: parity of a Bell pair is even
```

## 6. Endianness probe (put in every test suite)

```python
# Qiskit: X on qubit 0 of 3 -> bitstring '001', statevector index 1
qc = QuantumCircuit(3); qc.x(0)
assert Statevector(qc).probabilities_dict() == {"001": 1.0}

# Cirq: X on the first qubit of 3 -> integer 4 (first qubit is most significant)
q = cirq.LineQubit.range(3)
r = cirq.Simulator().run(cirq.Circuit(cirq.X(q[0]), cirq.measure(*q, key="m")), repetitions=1)
assert r.histogram(key="m") == {4: 1}

# PennyLane: X on wire 0 of 3 -> probs index 4
dev = qml.device("default.qubit", wires=3)
@qml.qnode(dev)
def probe():
    qml.PauliX(0)
    return qml.probs(wires=[0, 1, 2])
assert int(probe().argmax()) == 4
```

## 7. Resource estimation tools

- Microsoft QDK resource estimator, `qdk.qre` module (`pip install "qdk[qre]"`; `qdk.qre.estimate` with
  QSharpApplication / GateBased / SurfaceCode / RoundBasedFactory; the older `qsharp` estimator path
  is being deprecated, check the installed version's docs) (Q# or Qiskit circuits in,
  physical qubits, runtime, T-factory layout out; configurable qubit and QEC models).
- Google Qualtran: bloqs with symbolic T/Toffoli counts and qubit counts for chemistry and
  arithmetic building blocks.
- Check both against a hand estimate (SKILL.md section 7); disagreements beyond ~2x usually mean
  different assumptions about factories, routing or rotation synthesis.
