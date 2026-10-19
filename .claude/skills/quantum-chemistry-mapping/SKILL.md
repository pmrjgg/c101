---
name: quantum-chemistry-mapping
description: "Electronic-structure Hamiltonians for quantum algorithms: PySCF integrals, active-space selection, second quantisation, Jordan-Wigner, Bravyi-Kitaev, parity and ternary-tree mappings, symmetry tapering, Hamiltonian norms and factorisations (DF/THC), classical reference energies, and NISQ (VQE, SQD) vs fault-tolerant (qubitised QPE) routes. Load when turning a molecule or lattice model into qubit operators."
when_to_use: "Building a qubit Hamiltonian from a molecule (PySCF, OpenFermion, PennyLane qchem, Qiskit Nature); choosing an active space or fermion-to-qubit mapping; tapering qubits with symmetries; 'energy is off by a constant', 'VQE energy below FCI', 'HF state gives the wrong energy'; computing lambda or DF/THC factorisations for QPE costing; Hubbard or Heisenberg models; comparing quantum results with HF, CCSD(T), FCI or DMRG references."
---

# Quantum chemistry mapping

Most wrong quantum-chemistry energies come from bookkeeping, not physics: a dropped constant, a
unit mix-up, a spin-orbital ordering mismatch, or a reference computed in a different basis. The
pipeline below makes each convention explicit and ends in one hard check: exact diagonalisation
of the qubit Hamiltonian equals PySCF FCI to 1e-8 Ha, constant included.

## 1. Pipeline

```
geometry (Angstrom or Bohr, say which) + basis + charge + spin (2S, multiplicity = 2S + 1)
 -> PySCF RHF / ROHF (converged, stable)  -> optional CASSCF or natural orbitals
 -> active space (n_e, n_orb)  -> h_pq, (pq|rs) + E_core (nuclear repulsion + frozen-core energy)
 -> fermionic H = E_core + Σ h_pq a†_p a_q + ½ Σ (pq|rs) a†_p a†_r a_s a_q      (spin orbitals, chemist order)
 -> qubit H via a mapping (section 3), tapered (section 4)
```

```python
from pyscf import gto, scf, fci, ao2mo, mcscf
mol = gto.M(atom="H 0 0 0; H 0 0 0.7414", basis="sto-3g", unit="Angstrom", charge=0, spin=0)
mf = scf.RHF(mol).run()
C = mf.mo_coeff
h1 = C.T @ mf.get_hcore() @ C                                  # MO one-body integrals
eri = ao2mo.restore(1, ao2mo.kernel(mol, C), C.shape[1])        # chemist (pq|rs), 4-index array
e_core = mol.energy_nuc()
# active space instead: mc = mcscf.CASCI(mf, ncas, nelecas)
# h1_act, e_core = mc.get_h1eff(); h2_act = ao2mo.restore(1, mc.get_h2eff(), ncas)
```

Index order: chemist (pq|rs) = physicist ⟨pr|qs⟩. OpenFermion's `InteractionOperator.two_body_tensor[p, q, r, s]`
multiplies a†_p a†_q a_r a_s; pasting chemist integrals into it is the classic silent bug.

## 2. Active-space selection

| Method | How | When |
|---|---|---|
| frozen core | drop 1s (and deeper) cores; energy moves into E_core | always for second-row and heavier atoms |
| natural-orbital occupations | MP2 or CCSD 1-RDM, eigen-decompose; keep 0.02 < n < 1.98 | default automatic choice |
| AVAS | project onto chosen AO labels (`pyscf.mcscf.avas.avas(mf, ["Fe 3d", "S 3p"])`) | transition metals, chemically motivated spaces |
| CASSCF | optimise orbitals for the active space | strong correlation; needed before quoting dissociation curves |

Record (n_electrons, n_orbitals) as CAS(n_e, n_orb); qubits = 2 × n_orb before tapering. An active
space so small that CASCI ≈ HF says nothing about quantum advantage.

## 3. Fermion-to-qubit mappings

| Mapping | Weight of a†_j | Qubits | Notes |
|---|---|---|---|
| Jordan-Wigner | O(n) (Z string) | 2 n_orb | occupation stored directly; local for 1D nearest-neighbour hopping |
| parity | O(n) | 2 n_orb | N_α, N_β parities sit on two qubits: removes 2 qubits for fixed particle numbers |
| Bravyi-Kitaev | O(log n) | 2 n_orb | balanced storage of occupation and parity |
| ternary tree | ⌈log_3(2n + 1)⌉, optimal | 2 n_orb | lowest max weight |
| JW + fermionic swap network | all pair interactions in linear depth | 2 n_orb | Trotter steps for chemistry and Hubbard (`hamiltonian-simulation-methods`) |

Spin-orbital order: OpenFermion interleaves (0α, 0β, 1α, 1β, ...), so the H2 HF state is |1100⟩;
Qiskit Nature blocks (all α, then all β), so HF is |1010⟩ in the same left-to-right qubit listing.
An ansatz or HF circuit built for one order and a Hamiltonian in the other gives wrong energies
with no error message.

## 4. Symmetries and tapering

- Conserved Paulis (particle-number parity per spin, S_z parity, Z2 point-group symmetries) commute
  with H; each independent one removes a qubit (Bravyi et al. 2017): find generators τ_i, rotate
  with a Clifford U_i so τ_i → X_q, fix the eigenvalue, drop qubit q.
- Choose the sector containing the HF state (evaluate each τ_i on the HF bitstring). The wrong
  sector gives a valid but wrong state, often an ion or excited state.
- H2/STO-3G: 4 qubits → 2 (parity mapping, fixed N_α and N_β) → 1 (one more Z2 symmetry).
- Tools: OpenFermion `symmetry_conserving_bravyi_kitaev`, `taper_off_qubits`; Qiskit Nature
  `problem.get_tapered_mapper(ParityMapper(num_particles=problem.num_particles))`.

## 5. Tooling

| Library | Role | Entry point |
|---|---|---|
| PySCF | integrals, HF, CASSCF, CCSD(T), FCI | `gto.M`, `scf.RHF`, `mcscf.CASSCF`, `fci.FCI` |
| OpenFermion + openfermionpyscf | fermionic operators, mappings, factorisations | `MolecularData`, `run_pyscf`, `get_fermion_operator`, `jordan_wigner`, `bravyi_kitaev` |
| PennyLane qchem (0.45) | end-to-end qubit Hamiltonians | `qml.qchem.Molecule(symbols, coords, unit="angstrom")` (default unit is Bohr), `qml.qchem.molecular_hamiltonian(mol, active_electrons=, active_orbitals=, mapping="jordan_wigner"\|"parity"\|"bravyi_kitaev")` |
| Qiskit Nature | drivers, mappers, tapering | `PySCFDriver(...).run()`; community-maintained, confirm it supports your Qiskit major version |
| block2, SHCI codes | DMRG / selected-CI references | large active spaces |
| ffsim | fast fermionic circuit simulation (LUCJ ansatz) | small and medium active spaces |

```python
from openfermion import MolecularData, get_fermion_operator, jordan_wigner, get_sparse_operator
from openfermionpyscf import run_pyscf
mol = run_pyscf(MolecularData([("H", (0, 0, 0)), ("H", (0, 0, 0.7414))], "sto-3g", 1, 0), run_scf=True, run_fci=True)
H_q = jordan_wigner(get_fermion_operator(mol.get_molecular_hamiltonian()))   # constant = nuclear repulsion
```

## 6. Norms and factorisations

- Pauli LCU norm λ = Σ_j |c_j| (identity excluded; it only shifts the energy). Fault-tolerant cost
  scales as λ/ε, sampling cost of naive VQE energy estimation as (λ/ε)².
- Single factorisation: V_(pq)(rs) = Σ_l L^l_pq L^l_rs (Cholesky, rank ~ O(N)). Double
  factorisation diagonalises each L^l (eigenvalue truncation). THC: V_pqrs ≈ Σ_{μν} χ^μ_p χ^μ_q
  Z_μν χ^ν_r χ^ν_s with M ~ O(N) points. Each lowers λ and the PREPARE/SELECT Toffoli cost.
- Compute λ for every candidate representation and hand the smallest, with the truncation error it
  introduces, to `quantum-resource-estimation`.

## 7. Reference energies

| Method | Use | Limit |
|---|---|---|
| HF | reference determinant, sanity check of θ = 0 | no correlation |
| MP2 | cheap correlation, natural orbitals | fails for small gaps |
| CCSD(T) | near-equilibrium benchmark | breaks for strong correlation and bond breaking |
| FCI | exact in the basis and active space | up to ~18 orbitals with ~18 electrons |
| DMRG / SHCI | strong correlation, large active spaces | bond-dimension or selection convergence must be shown |

Chemical accuracy = 1.6 mHa (1 kcal/mol), measured against FCI (or converged DMRG) in the same
basis and active space, never against experiment.

## 8. NISQ routes

- VQE with UCCSD, k-UpCCGSD or ADAPT (`variational-quantum-algorithms`); shot cost from
  `quantum-measurement-estimation`. H2 below: (λ/ε)² = (1.885/0.0016)² ≈ 1.4e6 shots per energy
  before grouping.
- Sample-based quantum diagonalisation (`qiskit-addon-sqd` 0.14): sample bitstrings on hardware,
  `counts.counts_to_arrays`, repair particle number with `configuration_recovery.recover_configurations`,
  `subsampling.postselect_and_subsample` batches, then `fermion.diagonalize_fermionic_hamiltonian`
  classically in the spanned subspace. Report subspace dimension and the classical cost honestly;
  a subspace near the FCI dimension is a classical computation.
- Quantum Krylov / subspace expansion: report the basis size and the conditioning threshold.

## 9. Fault-tolerant route

Qubitised QPE on a DF or THC block encoding: about π λ / (2ε) walk steps for energy precision ε.
PREPARE (QROM loading of coefficients) and SELECT dominate the Toffoli count. For H2 below:
π · 1.885 / (2 · 0.0016) ≈ 1.9e3 walk steps. Hand (λ, number of terms or factorisation rank,
spin orbitals, ε) to `quantum-resource-estimation`.

## 10. Lattice models

- Fermi-Hubbard: H = -t Σ_{⟨ij⟩σ} (a†_iσ a_jσ + h.c.) + U Σ_i n_i↑ n_i↓ (`openfermion.fermi_hubbard`).
  Use JW with a snake ordering on 2D lattices; vertical hops carry strings of length ~2L_x, which
  swap networks or other encodings remove.
- Slater determinants (and HF states in a rotated basis) are prepared with N(M - N) Givens
  rotations for N particles in M modes.
- Heisenberg and transverse-field Ising models are spin models already: no fermion mapping.

## 11. Worked example: H2 / STO-3G at 0.7414 Å

PySCF 2.14 (verified run): E_nuc = 0.713754 Ha, E_HF = -1.116684 Ha, E_FCI = -1.137270 Ha. Building
H from section 1's integrals with interleaved spin orbitals and a Jordan-Wigner matrix
construction (a_j = Z^{⊗j} ⊗ |0⟩⟨1| ⊗ I) gives 15 Pauli terms including the identity:

| Term | Coefficient (Ha) | Term | Coefficient (Ha) |
|---|---|---|---|
| I | -0.0988639693 | Z0 Z1 | +0.1686221916 |
| Z0, Z1 | +0.1711977490 | Z0 Z2, Z1 Z3 | +0.1205448221 |
| Z2, Z3 | -0.2227859304 | Z0 Z3, Z1 Z2 | +0.1658670241 |
| X0 X1 Y2 Y3, Y0 Y1 X2 X3 | -0.0453222021 | Z2 Z3 | +0.1743484419 |
| X0 Y1 Y2 X3, Y0 X1 X2 Y3 | +0.0453222021 | | |

Checks: lowest eigenvalue -1.1372701746609 vs PySCF FCI -1.1372701746609 (difference 4e-16);
⟨1100|H|1100⟩ = E_HF to 4e-16; λ = 1.8851 Ha without the identity (1.9839 with it). The constant
-0.0989 already contains E_nuc; dropping it shifts every energy by that amount.

From-scratch check without OpenFermion (dense matrices, fine up to ~12 spin orbitals), using `h1`,
`eri`, `e_core` from section 1 and `e_fci = fci.FCI(mf).kernel()[0]`:

```python
import itertools, numpy as np
no = h1.shape[0]; ns = 2 * no                                   # interleaved spin orbitals P = 2p + spin
h1s, g = np.zeros((ns, ns)), np.zeros((ns,) * 4)
for p, q in itertools.product(range(no), repeat=2):
    for s in range(2): h1s[2 * p + s, 2 * q + s] = h1[p, q]
    for r, t in itertools.product(range(no), repeat=2):
        for s1, s2 in itertools.product(range(2), repeat=2):
            g[2 * p + s1, 2 * q + s1, 2 * r + s2, 2 * t + s2] = eri[p, q, r, t]
low = np.array([[0.0, 1.0], [0.0, 0.0]])
def a(j):                                                       # JW annihilator, mode 0 = leftmost factor
    m = np.eye(1)
    for k in range(ns): m = np.kron(m, np.diag([1.0, -1.0]) if k < j else (low if k == j else np.eye(2)))
    return m
A = [a(j) for j in range(ns)]
Hm = e_core * np.eye(2**ns) + sum(h1s[P, Q] * A[P].T @ A[Q] for P in range(ns) for Q in range(ns))
Hm += sum(0.5 * g[P, Q, R, S] * A[P].T @ A[R].T @ A[S] @ A[Q]
          for P, Q, R, S in itertools.product(range(ns), repeat=4) if g[P, Q, R, S])
assert abs(np.linalg.eigvalsh(Hm)[0] - e_fci) < 1e-8          # passed: difference 4e-16
```

Tapering to one qubit: H conserves N and S_z, so the ground state lives in span{|1100⟩, |0011⟩}
(HF and the double excitation). The 2 × 2 block gives

```
H_1q = -0.328717 I - 0.787967 Z + 0.181289 X        E0 = -0.328717 - sqrt(0.787967² + 0.181289²) = -1.137270 Ha
```

(the sign of the X term depends on phase conventions of the tapering Clifford). Correlation
energy: E_FCI - E_HF = -20.6 mHa, about 13 times chemical accuracy; the ground state is
0.9936 |1100⟩ - 0.1129 |0011⟩.

## Pitfalls

- Nuclear-repulsion or frozen-core constant dropped (energies off by a near-constant offset).
- Bohr / Angstrom mix-up: PennyLane `Molecule` defaults to Bohr; 0.7414 Bohr is a different molecule.
- Wrong multiplicity: PySCF `spin` is 2S (number of unpaired electrons), not 2S + 1.
- FCI or CCSD(T) reference in a different basis or active space than the quantum calculation.
- Chemical accuracy claimed against experiment instead of FCI in the same basis.
- Spin-orbital ordering mismatch between Hamiltonian and ansatz or HF circuit.
- An active space too small for correlation to matter, presented as a hard benchmark.

Related: `variational-quantum-algorithms`, `hamiltonian-simulation-methods`, `quantum-resource-estimation`, `quantum-measurement-estimation`, hub `quantum-computing`
