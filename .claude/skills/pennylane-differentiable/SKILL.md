---
name: pennylane-differentiable
description: "PennyLane differentiable quantum programming: device choice (default.qubit, lightning.*, default.mixed, default.tensor), diff methods (backprop, adjoint, parameter-shift, SPSA), JAX/Torch interfaces and Catalyst qjit, shot configuration, templates, the qchem and qaoa modules, gradient verification and specs. Load when building trainable QNodes or VQE/QAOA in PennyLane."
when_to_use: "Writing or debugging PennyLane QNodes, templates or optimisers; picking a device or diff_method; 'gradient is zero or None', 'adjoint not supported', 'setting shots on device is deprecated', 'jit recompiles every step'; JAX/optax, Torch (qml.qnn.TorchLayer) or Catalyst qjit; qml.qchem VQE or qml.qaoa MaxCut; verifying gradients against finite differences; resource counts with qml.specs; converting circuits from Qiskit or OpenQASM into PennyLane."
---

# PennyLane differentiable programming

A PennyLane number is defined by five choices: device, diff_method, interface, shots and version.
Fix all five before writing a loss function. Values marked *measured* come from PennyLane 0.45.1
with pennylane-lightning (lightning.qubit) on Python 3.13.

## 1. Versions and breaking points

```bash
python -c "import pennylane as qml; print(qml.__version__); qml.about()"
```

| Topic | Status in 0.45.1 (measured) | Do |
|---|---|---|
| shots | `qml.device(..., shots=N)` still runs but warns "Setting shots on device is deprecated. Please use the `set_shots` transform on the respective QNode instead." | `@qml.set_shots(shots=N)` on the QNode, or `qml.qnode(dev, shots=N)` |
| TensorFlow | deprecated upstream (0.45.1 still accepts `interface="tf"` when building a QNode) | write new code with JAX or Torch |
| Torch layer | lives at `qml.qnn.TorchLayer` (`qml.TorchLayer` does not exist) | |
| qchem | `molecular_hamiltonian(molecule, ...)` takes a `qml.qchem.Molecule`; `Molecule(..., unit="bohr")` is the default | pass `unit="angstrom"` or convert |
| optional devices | default.tensor needs quimb; default.clifford needs stim; lightning.gpu, lightning.kokkos and lightning.tensor are separate packages | install, then re-check |
| plugins | lightning, catalyst and pennylane-qiskit are pinned to the core minor version | upgrade together |

For any other version, check APIs with context7 (`mcp__context7__resolve-library-id`, then
`mcp__context7__query-docs`) before writing code.

## 2. Device table

| Device | Engine | Natural diff_method | Use and limits |
|---|---|---|---|
| default.qubit | NumPy/JAX/Torch statevector | backprop, adjoint | reference; up to about 20-25 qubits |
| lightning.qubit | C++ CPU statevector | adjoint | fast CPU default; up to about 30 qubits |
| lightning.gpu, lightning.kokkos | cuStateVec, Kokkos (GPU, OpenMP) | adjoint | memory 16 x 2^n bytes |
| lightning.tensor, default.tensor | MPS / tensor network (cuTensorNet, quimb) | check the docs | wide shallow circuits with bounded entanglement |
| default.mixed | density matrix | backprop | channels (`qml.DepolarizingChannel`, `qml.AmplitudeDamping`); about 12-14 qubits |
| default.clifford | stabilizer (stim) | none | Clifford circuits with thousands of qubits |
| pennylane-qiskit and Braket plugin devices | vendor simulators and hardware | parameter-shift | shots only; never submit to a QPU without the user's approval |

## 3. diff_method choice

| diff_method | Circuits or passes per gradient | Memory | Use when |
|---|---|---|---|
| backprop | a few forward passes (reverse-mode autodiff) | stores intermediate states, grows with layers | simulators with many parameters |
| adjoint | about 2-3 forward passes, exact | O(2^n) | lightning devices, analytic expectation values; no shots |
| parameter-shift | 2 per parameter of a Pauli-generator gate, 4 for controlled rotations, times measurement groups | O(2^n) | hardware, shots; unbiased |
| spsa | 2 per step whatever the parameter count | | many parameters under shots |
| finite-diff | P + 1 or 2P | | checks only; biased, step must exceed shot noise |

Two-term rule for gates exp(-i θ G/2) with G^2 = I:
df/dθ = [f(θ + π/2) - f(θ - π/2)] / 2. Controlled rotations (generator eigenvalues 0, ±1/2) need the
four-term rule df/dθ = d1 [f(θ + π/2) - f(θ - π/2)] - d2 [f(θ + 3π/2) - f(θ - 3π/2)] with
d1 = (√2 + 1)/(4√2), d2 = (√2 - 1)/(4√2). PennyLane applies both automatically; the cost table
belongs in the shot budget (`variational-quantum-algorithms`).

## 4. Interfaces

```python
import pennylane as qml
from pennylane import numpy as pnp                 # autograd
w = pnp.array(w0, requires_grad=True)
x = pnp.array(data, requires_grad=False)           # inputs are not trainable
```

```python
import jax, jax.numpy as jnp, optax                # JAX: jit outermost, QNode inside
dev = qml.device("default.qubit", wires=4)

@jax.jit
@qml.qnode(dev, interface="jax")                   # backprop by default on default.qubit
def cost(w):
    qml.StronglyEntanglingLayers(w, wires=range(4))
    return qml.expval(qml.Z(0) @ qml.Z(1))

opt = optax.adam(0.05); state = opt.init(w)
for step in range(200):
    val, g = jax.value_and_grad(cost)(w)
    upd, state = opt.update(g, state); w = optax.apply_updates(w, upd)
batch_vals = jax.vmap(cost)(W)                     # W: (B, L, 4, 3) parameter batch
```

```python
weight_shapes = {"weights": qml.StronglyEntanglingLayers.shape(n_layers=2, n_wires=4)}

@qml.qnode(dev, interface="torch")
def circuit(inputs, weights):                      # first argument must be named inputs
    qml.AngleEmbedding(inputs, wires=range(4))
    qml.StronglyEntanglingLayers(weights, wires=range(4))
    return [qml.expval(qml.Z(i)) for i in range(4)]

layer = qml.qnn.TorchLayer(circuit, weight_shapes) # a torch.nn.Module
```

Catalyst (`pip install pennylane-catalyst`) compiles whole hybrid programs, including loops and
mid-circuit-measurement control flow:
```python
@qml.qjit
@qml.qnode(qml.device("lightning.qubit", wires=2))
def f(x):
    @qml.for_loop(0, 10, 1)
    def body(i, x):
        qml.RX(x, wires=0)
        return x
    body(x)
    m = qml.measure(0)
    qml.cond(m, qml.PauliX)(wires=1)
    return qml.expval(qml.Z(1))
```
Python `if`/`for` on traced values fails under `jax.jit` or `qml.qjit`; use `qml.cond`,
`qml.for_loop`, `qml.while_loop` (or `jax.lax`).

## 5. Templates

| Template | Weight shape | Notes |
|---|---|---|
| `StronglyEntanglingLayers` | `.shape(n_layers, n_wires)` gives (L, n, 3) | hardware-efficient; barren plateaus with depth |
| `BasicEntanglerLayers` | `.shape(n_layers, n_wires)` gives (L, n) | one rotation per qubit per layer |
| `AllSinglesDoubles(weights, wires, hf_state, singles, doubles)` | len(singles) + len(doubles) | particle-conserving chemistry |
| `UCCSD(weights, wires, s_wires, d_wires, init_state, n_repeats)` | from `qml.qchem.excitations_to_wires` | expensive; reference ansatz |
| `SingleExcitation`, `DoubleExcitation` (Givens) | scalar | custom particle-conserving circuits |
| `AngleEmbedding(features, wires, rotation="X")` | n features | cheap encoding |
| `AmplitudeEmbedding(features, wires, normalize=True, pad_with=0.0)` | 2^n features | O(2^n) gates on hardware |

## 6. Measurements and Hamiltonians

| Measurement | Returns | Shots |
|---|---|---|
| `expval(O)`, `var(O)` | float | analytic or shots |
| `probs(wires)` | 2^k vector, first wire is the most significant bit | analytic or shots |
| `sample()`, `counts()` | samples, dict | shots only |
| `state()`, `density_matrix(wires)` | arrays | analytic only |
| `classical_shadow(wires)`, `shadow_expval(H)` | shadow data, estimates | shots only |

```python
H = qml.dot([0.5, -0.2], [qml.Z(0) @ qml.Z(1), qml.X(0)])        # also qml.s_prod, qml.Hamiltonian(coeffs, ops)
coeffs, ops = H.terms()
groups = qml.pauli.group_observables(ops, coeffs, grouping_type="qwc", method="lf")
```
`grouping_type` is "qwc", "commuting" or "anticommuting"; `method` is "lf", "rlf", "dsatur" or
"gis" (measured signature). H2/STO-3G (Jordan-Wigner) has 15 terms in 5 QWC groups (measured).
Every finite-shot expectation value carries sigma (`quantum-measurement-estimation`).

## 7. VQE recipe

```python
import numpy as np
R = 0.7414 / 0.529177210903                                   # Angstrom to bohr (Molecule default unit)
mol = qml.qchem.Molecule(["H", "H"], np.array([0.0, 0.0, -R/2, 0.0, 0.0, R/2]))
H, nq = qml.qchem.molecular_hamiltonian(mol)                   # active_electrons=, active_orbitals=, mapping="jordan_wigner"
hf = qml.qchem.hf_state(electrons=2, orbitals=nq)              # [1 1 0 0]
singles, doubles = qml.qchem.excitations(2, nq)                # [[0, 2], [1, 3]] and [[0, 1, 2, 3]]
E_exact = np.linalg.eigvalsh(qml.matrix(H, wire_order=range(nq)))[0]
```
Optimisers: `qml.GradientDescentOptimizer(stepsize)`, `qml.AdamOptimizer(0.05)`,
`qml.QNGOptimizer(stepsize, approx="block-diag")` (uses `qml.metric_tensor`), `qml.SPSAOptimizer`, or
optax under JAX. Stop at abs(dE) < 1e-6 Ha on exact devices; compare with the exact ground energy of
the same Hamiltonian and with PySCF FCI for absolute energies (`quantum-chemistry-mapping`). Under
shots, stop when abs(dE) < 2 sigma for three consecutive steps.

## 8. QAOA recipe

```python
import networkx as nx
G = nx.cycle_graph(4); p = 1
cost_h, mixer_h = qml.qaoa.maxcut(G)
dev = qml.device("lightning.qubit", wires=4)

def qaoa_layer(gamma, alpha):
    qml.qaoa.cost_layer(gamma, cost_h)
    qml.qaoa.mixer_layer(alpha, mixer_h)

@qml.qnode(dev)
def cost(params):                                  # params shape (2, p)
    for w in range(4):
        qml.Hadamard(w)
    qml.layer(qaoa_layer, p, params[0], params[1])
    return qml.expval(cost_h)
```
Minimise ⟨cost_h⟩. Check the sign convention on a 2-node graph before trusting it (the cut state
01 should have the lowest cost). At the optimum, sample bitstrings (`qml.set_shots` + `qml.counts()`),
compute cut values classically, and report the approximation ratio E[cut]/maxcut against brute force
(n <= 20) and against the Goemans-Williamson 0.878 guarantee (`variational-quantum-algorithms`). For
the 4-cycle at p = 1 the best ratio is 0.75 (analytic; reproduced in the `cirq-workflows` example).

## 9. Gradient verification

```python
rng = np.random.default_rng(0); h = 1e-4
for x0 in rng.uniform(-np.pi, np.pi, 5):
    x = pnp.array(x0, requires_grad=True)
    g = qml.grad(energy)(x)
    fd = (energy(x + h) - energy(x - h)) / (2 * h)
    assert abs(g - fd) < 1e-6
```
Measured on the H2 QNode below (adjoint, lightning.qubit): max abs difference 1.3e-9. With shots,
require agreement within 4 sigma, with sigma taken from at least 10 repeated gradient evaluations.
For custom gates, compare `qml.gradients.param_shift(qnode)(x)` with backprop on default.qubit.

## 10. Resource inspection

```python
print(qml.specs(energy)(theta))      # gates, depth, wires, shots, measurements; output format varies by version
print(qml.draw(energy)(theta)); qml.draw_mpl(energy)(theta)
from pennylane.transforms import cancel_inverses, merge_rotations
lean = cancel_inverses(merge_rotations(energy))
native = qml.transforms.decompose(energy, gate_set={"RX", "RY", "RZ", "CNOT"})
```
`qml.specs` counts template-level gates (measured for the H2 QNode: 2 gates, BasisState and
DoubleExcitation, depth 2), which are not hardware costs: decompose to a native set with
`qml.transforms.decompose(..., gate_set=...)` before any cost claim. Interop: `qml.from_qiskit(qc)`
(needs pennylane-qiskit) and `qml.from_qasm(qasm_string)`.

## 11. Worked example: H2 VQE, STO-3G, 0.7414 Angstrom

```python
dev = qml.device("lightning.qubit", wires=nq)

@qml.qnode(dev, diff_method="adjoint")
def energy(t):
    qml.BasisState(hf, wires=range(nq))
    qml.DoubleExcitation(t, wires=[0, 1, 2, 3])
    return qml.expval(H)

opt = qml.GradientDescentOptimizer(stepsize=0.4)
t = pnp.array(0.0, requires_grad=True); E_prev = float(energy(t))
for it in range(1, 200):
    t = opt.step(energy, t); E = float(energy(t))
    if abs(E - E_prev) < 1e-6:
        break
    E_prev = E

dev_s = qml.device("default.qubit", wires=nq, seed=1234)

@qml.set_shots(shots=10000)
@qml.qnode(dev_s, diff_method="parameter-shift")
def energy_s(t):
    qml.BasisState(hf, wires=range(nq))
    qml.DoubleExcitation(t, wires=[0, 1, 2, 3])
    return qml.expval(H)

Es = [float(energy_s(t)) for _ in range(30)]                  # 30 independent estimates
Gs = [float(qml.grad(energy_s)(t)) for _ in range(10)]
print(np.mean(Es), np.std(Es, ddof=1), np.mean(Gs), np.std(Gs, ddof=1))
```

Measured (PennyLane 0.45.1):

| Quantity | Value |
|---|---|
| qubits, Pauli terms, QWC groups | 4, 15, 5 |
| E_HF (θ = 0) | -1.11668439 Ha |
| exact ground energy of this H (eigvalsh) | -1.13727017 Ha |
| VQE: lightning.qubit, adjoint, GD stepsize 0.4 | 13 steps, θ* = 0.22472, E = -1.13726936 Ha (8.1e-7 above exact; 99.996% of the correlation energy) |
| gradient check, 5 points, h = 1e-4 | max abs(g - fd) = 1.3e-9 |
| 10k shots per group, parameter-shift, at θ* | E = -1.1373 ± 0.0022 Ha (sigma of one evaluation, 30 repeats); dE/dθ = -0.0012 ± 0.0030 (consistent with 0) |

Reading:
- sigma = 2.2 mHa at 10k shots exceeds chemical accuracy (1.6 mHa). Reaching 1.6 mHa needs about
  (2.2/1.6)^2 x 10k = 19k shots per group; 0.1 mHa needs about 5e6.
- The commonly quoted PySCF/OpenFermion FCI value at this geometry is -1.13728 Ha; PennyLane's
  built-in integrals land 1.4e-5 Ha higher. That is far below chemical accuracy but far above the
  1e-6 convergence threshold, so judge convergence against the exact energy of the same Hamiltonian
  and check absolute energies against PySCF before quoting them.

## 12. Pitfalls

- Wire 0 is the most significant bit in `probs`, `sample` and `state` (big-endian), the opposite of
  Qiskit.
- Inputs created with `requires_grad=True` under autograd: wasted gradients and wrong argnums.
- backprop requested on a shot-based device; use parameter-shift or spsa.
- QNodes rebuilt or re-jitted inside the training loop; define and jit once, keep shapes static.
- Python control flow on traced values under jit or qjit.
- Device-level shots (deprecated); use `qml.set_shots` or the QNode `shots=` keyword.
- Template-level `qml.specs` counts quoted as hardware cost.
- Geometry in Angstrom passed to `Molecule` without `unit="angstrom"`: a different molecule, silently.
- adjoint with shots or with non-expectation measurements.

Related: `variational-quantum-algorithms`, `quantum-chemistry-mapping`, `quantum-measurement-estimation`, `qiskit-primitives-runtime`, `cirq-workflows`, hub `quantum-computing`
