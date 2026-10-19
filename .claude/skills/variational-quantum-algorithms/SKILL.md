---
name: variational-quantum-algorithms
description: "Variational algorithm design and trainability: VQE ansatz, optimiser and gradient choices, parameter-shift rules, barren-plateau diagnosis (global cost, depth, noise, Lie-algebra dimension) and the simulability tension, QAOA with QUBO/Ising mapping, warm starts and classical baselines. Load when proposing, debugging or reviewing VQE, QAOA or QML training."
when_to_use: "VQE, QAOA or QML training code (Qiskit, PennyLane, CUDA-Q, numpy); picking an ansatz, optimiser or gradient method; 'gradients vanish', 'loss flat at random init', 'energy stuck above Hartree-Fock', 'optimizer never converges'; writing QUBO or Ising penalties; MaxCut, scheduling or portfolio QAOA; shot budgets for a variational loop; reviewing claims that a variational method beats a classical solver."
---

# Variational quantum algorithms

A variational result is only as good as three numbers that are rarely computed up front: the
shot bill of the loop, the gradient variance at the target size, and the best classical answer
on the same instances. Every section below produces one of them.

Deep material: [QAOA MaxCut script and full output](references/qaoa-maxcut-script.md) |
[trainability checks: shift rules and plateau scan](references/trainability-checks.md)

## 1. Loop anatomy and budget

```
|psi(theta)> = U(theta)|ref>      E(theta) = sum_j c_j <psi|P_j|psi>      theta <- optimiser(E, grad E)
total shots = iterations x circuits per step x shots per circuit
```

| Gradient source | Circuits per step (P parameters, G measurement groups) |
|---|---|
| two-term parameter shift | (2P + 1) G: energy plus two shifted circuits per parameter |
| four-term rule (controlled rotations) | 4 per such parameter |
| finite differences | (P + 1) G; step must exceed shot noise, result is biased |
| SPSA | 2 G per iteration whatever P is (plus calibration) |
| quantum natural gradient | parameter shift plus metric circuits (block-diagonal: about 1 per layer; full: O(P^2)) |
| gradient-free (COBYLA, Nelder-Mead) | G per function evaluation, many evaluations |

Worked bill: H with lambda = sum|c_j| = 10 Ha at chemical accuracy eps = 1.6 mHa needs up to
(lambda/eps)^2 = 3.9e7 shots per energy before grouping (derivation and grouping savings:
`quantum-measurement-estimation`). With P = 20, parameter shift and 100 iterations:
100 x 41 x 3.9e7 = 1.6e11 shots, about 190 days at an assumed 1e4 shots/s. Grouping or shadows
recover 10-100x; the rest has to come from fewer parameters or a cheaper objective. Put this
table in the proposal before any code runs.

A shifted-difference gradient has sigma(dE) = sqrt(sigma_+^2 + sigma_-^2)/2 = sigma_E/sqrt(2) for
the two-term rule, so a gradient component smaller than sigma_E/sqrt(2) is invisible.

## 2. Ansatz

| Ansatz | Size | Use | Watch out |
|---|---|---|---|
| UCCSD (Trotterised) | O(N_occ^2 N_virt^2) doubles | chemistry reference, small molecules | thousands of CNOTs beyond ~12 qubits |
| k-UpCCGSD (Lee et al. 2019) | k layers of paired doubles + generalised singles, O(kN) parameters | cheaper chemistry | k grows with correlation strength |
| ADAPT-VQE (Grimsley et al. 2019) | grows one pool operator per step, picked by max abs(dE/dtheta) | compact chemistry circuits | each step measures the gradient of every pool operator; stop when the gradient norm < eps (1e-3 typical) |
| qubit-ADAPT (Tang et al. 2021) | Pauli-string pool; minimal complete pools have 2n - 2 elements | hardware-shallow ADAPT | more iterations than fermionic ADAPT |
| hardware-efficient (RY/RZ layers + CZ/CX entanglers) | L x n | demos, small n | barren plateaus with depth, no symmetry; expressive is not trainable |
| symmetry-preserving Givens circuits (Arrazola et al. 2022) | particle-number-conserving 2-qubit blocks | fixed N, S_z fermionic states | needs the correct reference determinant |
| QAOA (problem-inspired) | 2p | combinatorial optimisation | section 9 |

Initialise chemistry ansatze at the Hartree-Fock reference (theta = 0 reproduces E_HF) and seed
doubles from MP2 amplitudes t_ij^ab = <ij||ab> / (e_i + e_j - e_a - e_b). An exact-simulator
energy at theta = 0 that differs from E_HF signals a sign, qubit-ordering or mapping bug
(`quantum-chemistry-mapping`).

## 3. Optimiser

| Situation | Optimiser | Settings |
|---|---|---|
| exact statevector, smooth | L-BFGS-B / BFGS (scipy) | analytic or adjoint gradients, gtol 1e-6..1e-8 |
| up to ~10 parameters | COBYLA, Nelder-Mead | rhobeg 0.1-0.5 rad; Nelder-Mead degrades quickly with dimension |
| shot noise, many parameters | SPSA | a_k = a/(A + k + 1)^0.602, c_k = c/(k + 1)^0.101, A ~ 0.1 maxiter |
| shot noise, gradients affordable | Adam on parameter-shift gradients | learning rate 0.01-0.1 |
| ill-conditioned landscape | quantum natural gradient | metric tensor cost above; PennyLane `QNGOptimizer(stepsize, approx='block-diag')` |

SPSA calibration: set c near the standard deviation of one energy estimate at the planned shots
(the perturbation must beat the noise), estimate the mean gradient magnitude g0 from 10-25 SPSA
gradients at theta_0, then a = delta (A + 1)^0.602 / g0 so the first step moves the parameters by
delta = 0.1-0.2 rad. PennyLane `SPSAOptimizer(maxiter, alpha=0.602, gamma=0.101, c=0.2, A, a)`
uses the same gains.

Stopping rule: stop when the improvement over a window is not significant, z = dE /
sqrt(sigma_1^2 + sigma_2^2) < 2 for fresh estimates at both ends. A tolerance such as
abs(dE) < 1e-6 with sigma_E = 1e-3 either never triggers or triggers on noise.

## 4. Gradient rules

| Gate generator G in exp(-i theta G) | Rule | Evaluations |
|---|---|---|
| eigenvalues +-r (RX, RY, RZ, RZZ: G = P/2, r = 1/2) | df = r [f(theta + pi/(4r)) - f(theta - pi/(4r))] = [f(theta + pi/2) - f(theta - pi/2)]/2 | 2 |
| controlled rotation, G = P1 (x) P/2 with P1 the projector on control 1, eigenvalues {0, +-1/2} | df = d+ [f(theta + pi/2) - f(theta - pi/2)] - d- [f(theta + 3pi/2) - f(theta - 3pi/2)], d+- = (sqrt2 +- 1)/(4 sqrt2) | 4 |
| R distinct eigenvalue differences (multi-frequency) | generalised shift rules (Wierichs, Izaac, Wang, Lin 2022) | 2R |
| exp(-i(theta G + H')) with H' not commuting with G | stochastic parameter shift (Banchi, Crooks 2021) | sampled |
| simulator only | backprop or adjoint differentiation | not shot-compatible |

Check every rule against central finite differences on an exact simulator before trusting it.
Measured on random 2-qubit states and observables (script in
[trainability checks](references/trainability-checks.md)):

| Case | abs(rule - finite difference) |
|---|---|
| two-term rule on RX | 3.9e-11 |
| four-term rule on CRX | 5.6e-11 |
| two-term rule wrongly applied to CRX | 5.2e-2 |

```python
two  = lambda f, t: (f(t + np.pi/2) - f(t - np.pi/2)) / 2
dp, dm = (np.sqrt(2) + 1) / (4 * np.sqrt(2)), (np.sqrt(2) - 1) / (4 * np.sqrt(2))
four = lambda f, t: dp*(f(t + np.pi/2) - f(t - np.pi/2)) - dm*(f(t + 3*np.pi/2) - f(t - 3*np.pi/2))
fd   = lambda f, t, h=1e-6: (f(t + h) - f(t - h)) / (2 * h)
assert abs(two(f, 0.37) - fd(f, 0.37)) < 1e-8          # f = exact expectation as a function of one angle
```

## 5. Barren-plateau diagnostics

Procedure (exact simulator, the real ansatz, the real cost, the real initialisation):
1. Build the circuit for n = 4, 6, ..., 16 (or the largest simulable n) at the intended depth L(n).
2. Draw 200 parameter vectors from the initialisation you will actually use.
3. Compute dC/dtheta_k exactly (parameter shift) for a few k: first layer, middle, last.
4. Fit log10 Var against n. A straight line means exponential decay (a plateau); a straight line
   in log Var against log n means polynomial decay (trainable at scale).
5. Convert to shots: resolving a typical gradient needs N >~ 1/Var shots per component.

Measured scan (RY layers + CZ ladder, gradient of the first angle, 200 samples):

| n | Var, global cost, L = n | Var, local cost, L = n | Var, global, L = 3 | Var, local, L = 3 |
|---|---|---|---|---|
| 4 | 3.6e-3 | 5.3e-3 | 2.7e-3 | 5.7e-3 |
| 8 | 1.3e-5 | 8.1e-4 | 9.2e-5 | 1.3e-3 |
| 12 | 2.8e-7 | 2.6e-4 | 4.6e-7 | 6.5e-4 |

Global cost 1 - abs(<0|psi>)^2 loses about half a decade per qubit even at depth 3; the local
cost 1 - (1/n) sum_j P(q_j = 0) falls like n^-2 at depth 3. At n = 12 the global gradient needs
2-4e6 shots per component just to read its sign. Full table (n = 2..12) and script:
[trainability checks](references/trainability-checks.md).

| Cause | Signature | Source |
|---|---|---|
| global cost (fidelity, projector on the all-zero state) | exponential in n even at shallow depth | Cerezo et al., Nat. Commun. 2021 |
| 2-design expressivity (deep random circuits) | Var ~ 2^-n scale | McClean et al. 2018; Holmes et al. 2022 |
| hardware noise | exponential in depth under local Pauli noise, local cost or not | Wang et al., Nat. Commun. 2021 |
| entanglement between visible and hidden qubits | volume-law entanglement kills gradients | Ortiz Marrero et al., PRX Quantum 2021 |
| large dynamical Lie algebra g | deep circuits: Var = P_g(rho) P_g(O) / dim g for simple g | Ragone et al., Nat. Commun. 2024 |

Dynamical Lie algebra check: close the generators {i G_k} under commutators
(PennyLane `qp.lie_closure(generators)`) and track dim g against n. Polynomial dim g removes the
expressivity cause (but see section 6); dim g ~ 4^n predicts a plateau for deep circuits.

## 6. Simulability tension

Cerezo et al. (Nat. Commun. 16, 7907, 2025) argue that the structures that provably avoid barren
plateaus (small dynamical Lie algebra, local cost in a shallow light cone, small-angle starts)
confine the dynamics to a polynomial subspace, and that the same structure usually yields a
classical surrogate of the loss, possibly after a one-off quantum data-acquisition phase. Their
caveats: average-case arguments, smart initialisations, models outside the assumptions, and
possible superpolynomial advantages.

When claiming trainability:
- state the mechanism (which cause from section 5 is removed and why);
- run a classical surrogate on the same instance: g-sim when dim g is poly(n), Pauli propagation
  (PauliPropagation.jl, weight or coefficient truncation) for local observables in shallow or
  small-angle circuits, MPS with bond dimension chi for low entanglement;
- report the quantum and surrogate losses side by side, with the surrogate's cost.

## 7. Mitigations

| Mitigation | Effect | Caveat |
|---|---|---|
| local cost function | polynomial gradients at log depth | different objective; check its optimum matches the global one |
| layerwise training (Skolik et al. 2021) | train a few layers, freeze, grow | can stall in local minima |
| identity-block initialisation (Grant et al. 2019) | blocks U(theta) U(theta)^dagger = I at start | helps only near the start |
| warm start from a classical solution (HF, GW cut, MPS) | starts in a high-gradient region | that region may be classically simulable |
| parameter transfer from small instances | QAOA angles concentrate across instance families | same graph family only |
| problem-inspired ansatz (UCC, Givens, QAOA) | symmetry restricts the search space | depth |

Record which mitigations and which initialisation distribution were used; without them a
trainability result cannot be reproduced.

## 8. QUBO and Ising mapping

Quantum convention: x_i = (1 - z_i)/2, so bit 0 is Z eigenvalue +1. For
min x^T Q x + q^T x + c with upper-triangular Q (Q_ij multiplies x_i x_j):

```
J_ij  = Q_ij / 4                                   (i < j)
h_i   = -q_i/2 - sum_{j != i} Q_ij / 4             (Q_ij taken from whichever triangle holds the pair)
const = c + sum_i q_i/2 + sum_{i<j} Q_ij / 4
H     = sum_i h_i Z_i + sum_{i<j} J_ij Z_i Z_j + const
```

Constraints:
- equality A x = b becomes the penalty A_pen ||A x - b||^2. Pick A_pen above the largest
  objective gain any violation can buy, then confirm on small instances (brute force) that the
  argmin is feasible. Bisect for the smallest A_pen that keeps the argmin feasible across a test
  set: too small gives an infeasible optimum, too large flattens the landscape (objective
  differences shrink relative to the energy scale) and ruins QAOA ratios.
- inequalities need slack variables (binary-encoded), which cost qubits.
- one-hot groups (sum_i x_i = 1) can avoid penalties entirely with XY mixers
  B = sum (X_i X_j + Y_i Y_j)/2 over the group and a feasible start state (Hadfield et al. 2019).

```python
from qiskit_optimization.applications import Maxcut
from qiskit_optimization.converters import QuadraticProgramToQubo
qp = Maxcut(G).to_quadratic_program()          # networkx graph in, maximisation problem out
qubo = QuadraticProgramToQubo(penalty=None).convert(qp)   # constraints -> penalties (none for MaxCut)
op, offset = qubo.to_ising()                   # SparsePauliOp + constant; variable i -> qubit i
import dimod
bqm = dimod.BinaryQuadraticModel.from_qubo({(0, 1): 2.0, (0, 0): -1.0})
h, J, off = bqm.to_ising()                     # dimod spins: x = (s + 1)/2, so s = -z (see pitfalls)
```

`from qiskit_optimization.translators import from_docplex_mp` turns a docplex model into a
QuadraticProgram. Check every mapping by brute force on n <= 20: the lowest eigenvalue of the
Ising operator plus offset must equal the classical optimum, with the sign of the objective
(maximisation becomes minimisation) accounted for.

## 9. QAOA specifics

```
|gamma, beta> = prod_{l=1..p} exp(-i beta_l B) exp(-i gamma_l C) |+>^n,      B = sum_i X_i
MaxCut: C = sum_{(i,j) in E} (1 - Z_i Z_j)/2  (maximise);  exp(-i gamma (1 - ZZ)/2) = phase x RZZ(-gamma)
p = 1, D-regular triangle-free graph: <C_e> = 1/2 + (1/2) sin(4 beta) sin(gamma) cos^(D-1)(gamma)
   optimum beta = pi/8, gamma = arctan(1/sqrt(D - 1)); D = 3 gives 0.6925 per edge
every 3-regular graph: p = 1 ratio >= 0.6924 (Farhi, Goldstone, Gutmann 2014)
```

The p = 1 formula reproduces 10.3868 = 15 x 0.6925 on the Petersen graph (3-regular, girth 5).
- Search region: for integer-valued C, beta has period pi/2 and gamma period 2pi, and
  (gamma, beta) -> (-gamma, -beta) leaves the objective unchanged, so a grid over
  gamma in [0, pi], beta in [0, pi/2) covers everything at p = 1.
- INTERP (Zhou et al. 2020) to go from p to p + 1:
  gamma_i^(p+1) = ((i - 1)/p) gamma_{i-1}^(p) + ((p - i + 1)/p) gamma_i^(p), i = 1..p+1, with
  gamma_0 = gamma_{p+1} = 0; same for beta. Optimised angles look like a ramp: gamma rises with
  l, beta falls. Without a p - 1 solution, start from a linear ramp
  gamma_l = (l/(p+1)) gamma_max, beta_l = (1 - l/(p+1)) beta_max and tune the two scales on a
  small instance.
- Parameter concentration: optimal angles for random graphs of one family agree across instances
  (Brandao et al. 2018); reuse them as the start point and skip most of the outer loop.
- CVaR objective (Barkoutsos et al. 2020): minimise the mean of the best alpha fraction
  (alpha = 0.1-0.25) of sampled energies instead of the mean of all of them; it rewards
  sampling the optimum, which is what the user wants.
- Cost per layer: abs(E) RZZ (2 CNOT or CZ each, or one native RZZ on IBM Heron with fractional
  gates, angle range 0 < theta <= pi/2) plus n RX, plus routing SWAPs on sparse couplers (3
  CNOT each). Count after transpilation (`qiskit-transpilation`).

## 10. Benchmark protocol

- Same instances, same seeds, at least 10-20 instances per size; report distributions.
- Metrics: approximation ratio r = <C>/C_opt (or energy error against the exact value), success
  probability p_s of sampling the optimum per shot, and time to solution
  TTS_99 = t_run ln(0.01) / ln(1 - p_s), with t_run including classical overhead.
- Report classical wall-clock next to quantum wall-clock, at equal target accuracy.

| Problem | Baselines to run, not cite |
|---|---|
| MaxCut | brute force (n <= ~30), Goemans-Williamson SDP (0.878 guarantee) with hyperplane rounding, Burer-Monteiro, simulated annealing (dwave-samplers `SimulatedAnnealingSampler`), tabu (`TabuSampler`), Gurobi/HiGHS MIP, OR-Tools CP-SAT |
| general QUBO | SA, tabu, parallel tempering, MIP solvers, CP-SAT |
| VQE energies | HF, MP2, CCSD(T), DMRG for quasi-1D systems, FCI or selected CI in small active spaces |

## 11. Worked example: MaxCut, 10-node 3-regular graph

Instance `networkx.random_regular_graph(3, 10, seed=7)` (networkx 3.7): 15 edges, brute-force optimum 13 cut
edges (2 optimal bitstrings, one cut up to the global flip). Exact statevector QAOA, p = 1 by a
121 x 61 grid over gamma in [0, pi], beta in [0, pi/2] then BFGS; p = 2, 3 from INTERP then
BFGS. GW via cvxpy (SCS) with 1000 hyperplane roundings; SA with 200 Metropolis sweeps and 100
restarts. Full script and output: [QAOA MaxCut script](references/qaoa-maxcut-script.md).

```python
psi = np.full(2**n, 2 ** (-n / 2), dtype=complex)            # |+>^n
for g, b in zip(gammas, betas):
    psi = np.exp(-1j * g * C) * psi                           # C = cut size of every bitstring (diagonal)
    psi = apply_mixer(psi, b)                                 # exp(-i b X) on every qubit
F = np.vdot(psi, C * psi).real; P_opt = np.abs(psi[C == C.max()]) ** 2
shots_99 = ceil(log(0.01) / log(1 - P_opt.sum()))
```

| Method | <cut> | ratio to 13 | P(optimum) per sample | samples for 99% |
|---|---|---|---|---|
| QAOA p = 1 (gamma 0.588, beta 0.365) | 10.078 | 0.775 | 0.038 | 120 |
| QAOA p = 2 (INTERP + BFGS) | 11.063 | 0.851 | 0.139 | 31 |
| QAOA p = 3 (gamma 0.436, 0.870, 1.003; beta 0.539, 0.409, 0.231) | 11.716 | 0.901 | 0.314 | 13 |
| GW SDP value (upper bound) | 13.10 | - | - | - |
| GW hyperplane rounding | 12.16 mean | 0.936 | 0.515 | 7 |
| simulated annealing | 13 in 100/100 restarts | 1.000 | 1.0 | 1 |

Verdict for the write-up: noiseless p = 3 QAOA samples the optimum in about 13 shots, yet SA
solves every restart and GW rounding beats the QAOA mean, so there is no advantage on this
instance. These are exact-expectation results: on hardware the training itself sees shot noise
and gate noise (`quantum-noise-mitigation`), and every number above degrades.

## Pitfalls

| Pitfall | Consequence | Fix |
|---|---|---|
| optimising exact expectations, then presenting the result as a hardware result | overstated quality | train with shots (and noise) or label it noiseless |
| weak baselines (random, greedy) | invented advantage | run section 10 baselines on the same instances |
| over-parameterised hardware-efficient ansatz sold as 'expressive' | plateau, no symmetry, no gain | diagnose with section 5; prefer problem-inspired circuits |
| convergence tolerance below the 1/sqrt(shots) noise floor | optimiser chases noise, or stops at random | significance-based stopping (section 3) |
| penalty weight too small or too large | infeasible optimum, or a flat landscape | brute-force feasibility check and bisection (section 8) |
| dimod spins taken as Pauli Z eigenvalues | linear terms flip sign (dimod s = 2x - 1, quantum z = 1 - 2x) | negate h, keep J, when building Pauli-Z operators from dimod |
| qubit order mismatch in Ising readout | wrong bitstring reported as optimum | Qiskit bitstrings are little-endian; variable i is qubit i (rightmost character) |
| same shots used to train and to report | winner's-curse bias | re-estimate the final energy with fresh shots |
| choosing p, alpha or layers after seeing test results | overfitted benchmark | fix hyperparameters on separate instances |
| gradient rule for the wrong generator spectrum | silently wrong gradients (5e-2 error above) | check against finite differences |

Related: `quantum-measurement-estimation`, `quantum-noise-mitigation`, `pennylane-differentiable`,
`qiskit-primitives-runtime`, `qiskit-transpilation`, `quantum-chemistry-mapping`,
`quantum-circuit-simulators`, hub `quantum-computing`.
