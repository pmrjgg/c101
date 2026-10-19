---
name: quantum-resource-estimation
description: "Fault-tolerant resource estimation: logical-level costing (logical qubits, T/Toffoli counts, rotation synthesis), error-budget split, code distance and factory sizing, physical qubits and runtime, reaction-time limits, tools (Microsoft QDK estimator, Qualtran, PennyLane, pyLIQTR, bartiq) and reporting with sensitivity tables. Load when asked how many qubits or how much time an algorithm needs."
when_to_use: "'How many qubits / how long would X take on a fault-tolerant machine?'; costing Shor, chemistry (QPE, qubitization), simulation or arithmetic circuits; T, Toffoli or rotation counts; choosing code distance, factory count or an error budget; running or checking the QDK resource estimator, Qualtran or PennyLane resource estimation; comparing with published estimates (RSA-2048, FeMoco); reviewing vendor or paper resource claims."
---

# Fault-tolerant resource estimation

An estimate is a chain: logical counts → error budget → code distance → patches and factories →
physical qubits and runtime. Each link has a default assumption that can move the answer by
10-1000x, so every number ships with its assumptions table and a sensitivity sweep. Code and
threshold background: `stabilizer-codes-surface-code`; logical counts for chemistry:
`quantum-chemistry-mapping` and `hamiltonian-simulation-methods`.

## 1. Logical costing

Count logical qubits Q (data plus every ancilla: arithmetic workspace, QROM outputs, block-encoding
registers, phase-gradient state), non-Clifford count (Toffoli or T), rotation count N_rot, and the
logical depth D_steps (sequential lattice-surgery steps).

| Primitive | Non-Clifford cost |
|---|---|
| Toffoli | 4 T with a temporary logical-AND (uncompute by measurement, 0 T); 7 T without |
| n-bit addition (ripple carry) | n - 1 Toffolis |
| n-bit comparison | ≈ n Toffolis |
| controlled SWAP of one qubit | 1 Toffoli |
| SELECT over L terms (unary iteration) | ≈ L Toffolis |
| QROM read of L words | L - 1 Toffolis; QROAM (select-swap) ⌈L/k⌉ + b(k - 1) for b-bit words |
| n × n multiplication | Θ(n²) Toffolis |
| arbitrary Z rotation to ε | ≈ 3 log2(1/ε) T (gridsynth), section 2 |

Arithmetic and data loading (QROM, PREPARE) usually dominate; an estimate that only counts the
"interesting" rotations is wrong by orders of magnitude.

## 2. Rotation synthesis

- Per-rotation precision ε_rot = ε_synth / N_rot; cost ≈ 3 log2(1/ε_rot) T each with gridsynth
  (Ross-Selinger), less with probabilistic mixing.
- Example: N_rot = 1e6, ε_synth = 3.3e-3 → ε_rot = 3.3e-9 → ≈ 85 T each → 8.5e7 T total.
- Phase-gradient alternative: prepare a b-bit gradient state once; each rotation becomes a b-bit
  addition (≈ b Toffolis, b ≈ log2(1/ε_rot)). Prefer it when angles live in quantum registers or
  when Toffolis from CCZ factories are cheaper than T states.

## 3. Error budget

```
eps_total = eps_logical + eps_distillation + eps_synthesis        default: thirds, and say so
eps_total target: 1e-2 to 1e-3 per run (a 1% failure means rerun 1 in 100 times)
```

## 4. Code distance

```
choose the smallest odd d with   Q_patches · D_steps · d · A (p/p_th)^((d+1)/2)  ≤  eps_logical
A ≈ 0.1, p_th ≈ 0.01 (surface code, circuit level);  patch = 2d² - 1 physical qubits
Q_patches ≈ 1.5-2 × Q (routing lanes);  each logical step lasts ≈ d rounds
```

The left side counts patch-rounds times the per-round logical error rate. qLDPC memory (for
example the [[144, 12, 12]] gross code) cuts memory overhead several-fold but makes logic,
routing and decoding harder; cost it only with a concrete logic scheme.

## 5. Magic-state factories

- 15-to-1: p_out ≈ 35 p_in³ per output state. At p_in = 1e-3: 3.5e-8, enough for ≲ 1e5 T gates
  at ε_distillation ~ 3e-3. Two levels: ≈ 1.5e-21.
- Requirement: p_out ≤ ε_distillation / N_T. Example: N_T = 1e8, ε_distillation = 3.3e-3 needs
  p_out ≤ 3.3e-11, so one level of 15-to-1 at p = 1e-3 fails (3.5 expected faulty T states).
- Options: multi-level or larger-distance 15-to-1 designs (Litinski 2019 tables), CCZ factories
  for Toffoli-heavy code, magic-state cultivation (Gidney-Shutty-Jones 2024) for a small footprint.
- Number of factories = ⌈required T rate / rate per factory⌉; required rate = N_T / target runtime.
  Add factory footprint (and its routing) to the physical-qubit count.

## 6. Runtime

```
runtime = max( D_steps · d · t_cycle,                  surface-code clock
               N_T / (n_factories · rate),             magic-state supply
               D_T,seq · t_react )                     reaction limit: sequential non-Clifford depth × (decode + feed-forward)
t_cycle ≈ 0.4-1 µs superconducting, ~ms trapped ions and neutral atoms   (a 1000x swing)
```

A 10 µs reaction time (the Gidney-Ekerå 2019 assumption) with 1e7 sequential T layers already
imposes 100 s, whatever the factories do.

## 7. Tools (check APIs with context7 before use; verified names below)

| Tool | Entry points | Notes |
|---|---|---|
| Microsoft QDK (`pip install qdk`; the `qsharp` package is deprecated in its favour) | `qdk.estimator.LogicalCounts({...}).estimate(params)`, `qdk.qsharp.estimate(entry_expr, params)`, `qdk.qiskit.estimate(circuit, params)`; params `EstimatorParams()` with `qubit_params.name` in `qubit_gate_ns_e3`, `qubit_gate_ns_e4`, `qubit_gate_us_e3`, `qubit_gate_us_e4`, `qubit_maj_ns_e4`, `qubit_maj_ns_e6`, `qec_scheme.name` in `surface_code`, `floquet_code`, `error_budget` | QDK 1.33; newer architecture/ISA API in `qdk.qre` (`pip install "qdk[qre]"`, `qre.estimate(application, architecture, isa_query, ...)`); a Pareto (qubits vs time) mode exists, check field names |
| Qualtran 0.7 | `bloq.call_graph()`, `get_cost_value(bloq, QECGatesCost())`, `get_cost_value(bloq, QubitCount())` from `qualtran.resource_counting`; `qualtran.surface_code`: `AlgorithmSummary`, `PhysicalParameters`, `PhysicalCostModel`, `FifteenToOne`, `CCZ2TFactory`, `get_ccz2t_costs_from_grid_search` | best for structured block encodings and arithmetic |
| PennyLane 0.45 | `qml.estimator` (resource operators such as `QROM`, `SelectPauli`, `Qubitization`, `QubitizeTHC`, `DoubleFactorization`, `TrotterProduct`, `ResourceConfig`); `qml.specs(qnode)()` for concrete circuits | chemistry-oriented |
| pyLIQTR (MIT LL), bartiq (PsiQuantum, symbolic) | see their docs | symbolic or problem-specific pipelines |

```python
from qdk.estimator import LogicalCounts, EstimatorParams
p = EstimatorParams(); p.qubit_params.name = "qubit_gate_ns_e3"; p.qec_scheme.name = "surface_code"; p.error_budget = 0.01
r = LogicalCounts({"numQubits": 100, "tCount": 100_000_000, "measurementCount": 0}).estimate(p)
pc = r["physicalCounts"]
print(pc["physicalQubits"], pc["runtime"], r["logicalQubit"]["codeDistance"], pc["breakdown"]["numTfactories"])
```

## 8. Cross-checks

- Hand estimate and tool should agree within ~2x. Otherwise list where they differ: factory design
  and count, routing overhead, synthesis cost, error-model prefactor, cycle time.
- Published anchors (fetch exact figures via the paper-researcher agent): RSA-2048 at ~20M noisy
  qubits and ~8 h (Gidney-Ekerå 2019) and under 1M qubits in under a week (Gidney 2025), both at
  p = 1e-3 and 1 µs cycles; FeMoco with THC block encodings (Lee et al. 2021) at a few million
  physical qubits and days of runtime. A new estimate far below an anchor needs a named reason.

## 9. Sensitivity table

From section 4 with Q_patches = 200, D_steps = 1e8, A = 0.1, p_th = 0.01, ε_logical = 0.01/3,
clock-limited runtime, factories excluded:

| p | d | data + routing qubits | t_cycle 1 µs | 10 µs | 1 ms |
|---|---|---|---|---|---|
| 1e-3 | 27 | 2.9e5 | 0.75 h | 7.5 h | 31 days |
| 5e-4 | 21 | 1.8e5 | 0.58 h | 5.8 h | 24 days |
| 1e-4 | 13 | 6.7e4 | 0.36 h | 3.6 h | 15 days |

```python
def min_distance(q_patches, d_steps, p, eps_logical, A=0.1, p_th=0.01):
    for d in range(3, 201, 2):
        if q_patches * d_steps * d * A * (p / p_th) ** ((d + 1) / 2) <= eps_logical:
            return d

for p in (1e-3, 5e-4, 1e-4):                 # reproduces the table above
    d = min_distance(200, 1e8, p, 0.01 / 3)
    print(p, d, 200 * (2 * d * d - 1), [round(1e8 * d * tc / 3600, 2) for tc in (1e-6, 1e-5, 1e-3)])
```

Highlight the dominant term in each cell (clock, factories or reaction); here it is the clock,
and the cycle time moves the answer far more than the physical error rate does.

## 10. Worked example

Q = 100 logical qubits (200 patches with routing), D_steps = 1e8, p = 1e-3, ε_logical = 0.01.
Condition: 200 · 1e8 · d · 0.1 · 10^{-(d+1)/2} ≤ 0.01, i.e. d · 10^{-(d+1)/2} ≤ 5e-12.

| d | d · 10^{-(d+1)/2} | verdict |
|---|---|---|
| 21 | 2.1e-10 | fail |
| 23 | 2.3e-11 | fail |
| 25 | 2.5e-12 | pass |

Patch 2 · 25² - 1 = 1249 → 2.5e5 physical qubits before factories. Runtime 1e8 · 25 · 1 µs =
2500 s ≈ 42 min if factories deliver 1e8 T in that time (4e4 T/s). If 0.01 is the total budget
split in thirds, d = 27 (2.7e-13 against 1.7e-12): 1457 per patch, 2.9e5 qubits, 45 min.

Tool cross-check (QDK 1.33, `LogicalCounts({"numQubits": 100, "tCount": 1e8})`, error budget 0.01):

| Qubit model | Logical qubits after layout | d | Physical qubits | of which factories | Runtime |
|---|---|---|---|---|---|
| `qubit_gate_ns_e3` (p = 1e-3, 400 ns cycle) | 230 | 23 | 709,820 | 466,480 (14 factories) | 920 s (15 min) |
| `qubit_gate_us_e3` (µs-scale gates) | 230 | 23 | 402,180 | 158,840 (11 factories) | 16 days |

QDK lays out Q algorithmic qubits as 2Q + ⌈√(8Q)⌉ + 1 logical patches (230 for Q = 100), close to
the 2x routing assumption. The algorithm part agrees (243,340 vs 2.5e5); the factor 2.8 in totals is the factory footprint
the hand estimate left open, and the runtime gap is the 400 ns vs 1 µs cycle. Report: "~0.3M
data and routing qubits plus 0.2-0.5M in factories (0.5-0.8M total), 15-45 min at p = 1e-3 and
0.4-1 µs cycles; ~16 days on µs-gate hardware".

## 11. Reporting template

| Assumption | Value |
|---|---|
| physical error p, error model | 1e-3, circuit-level depolarizing |
| t_cycle, reaction time | 1 µs, 10 µs |
| code, decoder latency | rotated surface code, ≤ 10 µs |
| factory | design, p_out, footprint, rate |
| error budget split | ε_logical / ε_distillation / ε_synthesis |
| tool and version | e.g. QDK 1.33, Qualtran 0.7 |

Outputs as ranges with the dominant term named. List omissions (leakage, correlated bursts, I/O,
classical co-processing, compilation overheads). Label each claim Proven, Evidence or Conjecture.

## Pitfalls

- T gates counted but the ancillas of Toffoli ladders, comparators and adders missed.
- QROM / data-loading / PREPARE cost ignored, or state preparation assumed free.
- All T gates assumed parallel beyond what factories can supply; reaction-time limit ignored.
- Physical counts taken from memory experiments (2d² - 1 per patch, no routing, no factories).
- Per-round and per-operation logical error rates mixed (a step is ≈ d rounds).
- One tool output reported to six significant figures as if it were a measurement.

Related: `stabilizer-codes-surface-code`, `hamiltonian-simulation-methods`, `quantum-chemistry-mapping`, `stim-qec-decoding`, hub `quantum-computing`
