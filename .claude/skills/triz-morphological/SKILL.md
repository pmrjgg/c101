---
name: triz-morphological
description: "Inventive problem solving with TRIZ and morphological analysis: formulate technical and physical contradictions, resolve them with the four separation principles and the 40 inventive principles (compact table with software and science examples), aim at the ideal final result using resources already present, and build, cross-consistency-prune and score a morphological box with the bundled script. Load when a design is stuck on a trade-off or the option space needs systematic enumeration."
when_to_use: "first-principles-decomposer and anyone facing an either-or trade-off (fast vs thorough, consistent vs available, flexible vs simple), a need for non-obvious design options, or a combinatorial design space to enumerate and prune. Not for choosing among already-known options (judge-panel, mediator-voting) or estimating numbers (delphi-method)."
---

# TRIZ and morphological analysis

TRIZ (Altshuller, from 1946, distilled from patent analysis) rests on one observation: inventive
solutions **eliminate** a contradiction instead of compromising on it, and the ways they do so repeat
across fields. Morphological analysis (Zwicky; extended by Ritchey's general morphological analysis
with cross-consistency assessment) enumerates a design space as the product of independent
parameters and prunes it systematically. Use TRIZ to find the move that dissolves the core
trade-off; use the morphological box to explore every coherent configuration around it.

## 0. Which tool

| Situation | Tool |
|---|---|
| "improving A worsens B" and the team is negotiating a compromise | contradiction formulation, separation principles, 40 principles |
| unclear what a perfect solution would even be | ideal final result and resource inventory |
| several independent design choices, combinations unclear | morphological box |
| a trade-off resolved, now need the full configuration | TRIZ first, then the box seeded with the resolution |

## 1. Formulate the contradiction

Name the function and the **control element** (the thing you can change). Then write the mirrored
pair of technical contradictions (TC) and derive the physical contradiction (PC):

```text
TC1: If <element> is <state A>, then <benefit X>, but <harm Y>.
TC2: If <element> is <state not-A>, then <benefit Y'>, but <harm X'>.
Main function served by: TC<1|2>     (pick the one that delivers the primary function)
PC:  <element> must be <A> in order to <X>, and must be <not-A> in order to <Y'>.
```

Rules:
- One element, two opposite requirements. If the PC names two different elements, it is not yet a
  physical contradiction; keep narrowing.
- **Intensify** the conflict (an ARIZ move): push the element to the extreme (zero tests, infinite
  tests) to see clearly what each side needs.
- If no contradiction exists, it is an optimisation problem; use first-principles bounds and
  ordinary engineering, not TRIZ.

## 2. Resolve with separation principles (try in this order)

| Separation | Question | Pattern | Software example | Science / engineering example |
|---|---|---|---|---|
| in time | are A and not-A needed at the same moment? | A at t1, not-A at t2 | strict checks in the merge queue, light checks on each push; LSM trees write fast now, compact later | pulsed lasers: high peak power, low average heat |
| in space | are they needed in the same place? | A here, not-A there | CQRS: write model normalised, read model denormalised; hot/cold tiers | bifocal lens; composite tool tips (hard edge, tough body) |
| on condition | are they needed under the same conditions? | switch on a condition | fast path / slow path; adaptive algorithms; per-tenant flags | non-Newtonian fluids; photochromic glass |
| between levels (parts vs whole) | must the parts and the whole share the property? | each part A, the whole not-A (or reverse) | unreliable nodes, reliable cluster (replication); weak per-op guarantees, strong session guarantees | bicycle chain: rigid links, flexible whole |

If one separation works, go to the 40 principles only to refine the mechanism. If none works,
reformulate the PC at a different element or system level.

## 3. Ideal final result (IFR) and resources

Ideality = (sum of useful functions) / (sum of costs + sum of harms). The IFR is the limit: the function
is performed while the system that performs it disappears.

```text
IFR: <the element> ITSELF, without complicating the system and without harm, during <operating time>
     in <operating zone>, achieves <function> while keeping <the good property>.
```

Then work backwards: what is the closest achievable approximation? Inventory **resources already
present**, because IFR solutions use them instead of adding parts:

| Resource type | Software examples | Physical examples |
|---|---|---|
| substances / data | logs, telemetry, existing indexes, build graph, test history | waste materials, ambient air, the product itself |
| fields / signals | events already emitted, clocks, health checks, error codes | gravity, heat, pressure, magnetism |
| time | idle periods, nights, the wait while another step runs | pre- and post-operation periods |
| space | unused capacity, spare bits, padding, slack in schedules | voids, other side of a surface |
| functions | side effects already happening (a cache warmed by traffic) | existing motion, vibration |
| information | correlations in history (which tests fail together) | gradients, differences between parts |

## 4. The 40 inventive principles (compact)

Use them as prompts once the contradiction is clear: for each candidate principle, write one
concrete instantiation for the element in the PC. Extended sub-principles and more examples:
[40 principles extended](references/40-principles-extended.md). Altshuller's 39 x 39 contradiction
matrix maps parameter pairs to principles but fits software poorly; use the software-oriented
[contradiction cookbook](references/contradiction-cookbook.md) instead.

| # | Principle | Core move | Software example | Science / engineering example |
|---|---|---|---|---|
| 1 | Segmentation | divide into independent parts | sharding, microservices, tiling a GEMM | domain decomposition in PDE solvers |
| 2 | Taking out | extract the disturbing or the only needed part | move auth to a gateway; isolate the noisy job | move the vibrating pump off the optical table |
| 3 | Local quality | make each part fit its local job | per-table consistency levels; mixed precision | adaptive mesh refinement; graded materials |
| 4 | Asymmetry | replace symmetric with asymmetric | read replicas; big.LITTLE cores; split hot keys | asymmetric airfoils |
| 5 | Merging | combine identical or adjacent operations | batching, group commit, kernel fusion | multiplexed assays in one plate |
| 6 | Universality | one part performs several functions | the log as replication stream and audit trail | multi-mode instruments |
| 7 | Nested doll | place one inside another | cache hierarchies, BVHs, octrees | multigrid; telescoping structures |
| 8 | Anti-weight | counter a burden with a lifting force | offload to CDN or NIC; let the platform carry load | hydrofoils; magnetic levitation |
| 9 | Preliminary anti-action | apply the counter-action in advance | idempotency keys before retries; preallocate | pre-stressed concrete; amplifier predistortion |
| 10 | Preliminary action | do the work before it is needed | materialised views, AOT compilation, prefetch | preconditioning iterative solvers |
| 11 | Beforehand cushioning | prepare emergency means in advance | feature flags, circuit breakers, backups, WAL | fuses, airbags, HPC checkpoints |
| 12 | Equipotentiality | avoid raising and lowering | zero-copy, shared-memory columnar formats | service pits instead of lifting the car |
| 13 | The other way round | invert the action or the frame | push vs pull; move compute to data; reverse-mode autodiff | adjoint methods; rotate the part, not the tool |
| 14 | Spheroidality | linear to curved, rotary, cyclic | ring buffers, consistent-hash rings, log rotation | arches, domes, rollers |
| 15 | Dynamics | make characteristics adaptive | autoscaling, adaptive timeouts, JIT | adaptive step-size ODE solvers |
| 16 | Partial or excessive action | do slightly less or more, then correct | HyperLogLog, sampling; hedged requests | spin-coating: excess then spin off |
| 17 | Another dimension | add a dimension or a layer | MVCC (time), R-trees, 2-D tiling | multilayer PCBs, 3-D chip stacking |
| 18 | Mechanical vibration | use oscillation or perturbation | retry jitter, dithering, random restarts, fuzzing | ultrasonic cleaning, vibratory feeders |
| 19 | Periodic action | continuous to periodic | heartbeats, periodic compaction, checkpoints | pulsed lasers, PWM |
| 20 | Continuity of useful action | remove idle and intermittent motion | pipelining, double buffering, work stealing | flywheels |
| 21 | Skipping | do harmful phases very fast | short critical sections; atomic cutover | flash pasteurisation |
| 22 | Blessing in disguise | turn harm into benefit | timeouts as failure detectors; noise as regularisation | waste-heat recovery; stochastic resonance |
| 23 | Feedback | introduce or adjust feedback | PGO, backpressure, closed-loop autoscaling | adaptive optics |
| 24 | Intermediary | add a mediator | proxies, queues, adapters, indirection | catalysts |
| 25 | Self-service | the system serves or repairs itself | reconciliation loops, self-tuning, self-describing data | self-sharpening blades, self-healing polymers |
| 26 | Copying | use cheap copies instead of the original | replicas, snapshots, shadow traffic, mocks | wind-tunnel models, digital twins |
| 27 | Cheap short-living objects | disposable instead of durable | ephemeral environments, spot instances, arenas | disposable pipette tips |
| 28 | Mechanics substitution | replace mechanical action with a field | polling to events or interrupts; manual ops to automation | optical tweezers |
| 29 | Pneumatics and hydraulics | use fluid or elastic parts | queues as shock absorbers; elastic pools | air cushions, hydraulic presses |
| 30 | Flexible shells, thin films | thin flexible layers | sidecars, facades, strangler-fig wrappers | membranes, coatings |
| 31 | Porous materials | introduce voids | sparse structures, gaps in key spaces, padding against false sharing | filters, aerogels |
| 32 | Colour changes | change visibility or markers | trace IDs, taint tracking, canary labels | indicators, fluorescent tags |
| 33 | Homogeneity | interacting parts of the same material | same runtime and serialisation end to end | same metal to avoid galvanic corrosion |
| 34 | Discarding and recovering | discard or regenerate spent parts | GC, TTLs, log compaction, cache rebuild | rocket stages, dissolvable capsules |
| 35 | Parameter changes | change state, concentration, flexibility | row to columnar; quantisation; compression | freeze-drying |
| 36 | Phase transitions | exploit threshold effects | introsort switching; degraded modes | heat pipes, phase-change materials |
| 37 | Thermal expansion | use expansion under a stimulus | exponential backoff; elastic scaling | bimetal strips |
| 38 | Strong oxidants | intensify the environment | chaos at raised fault rates; mutation testing | accelerated life testing |
| 39 | Inert atmosphere | neutral environment | sandboxes, hermetic builds, deterministic simulation | argon shielding, gloveboxes |
| 40 | Composite materials | combine materials | Timsort, hybrid logical clocks, hybrid quantum-classical | carbon-fibre composites |

## 5. Morphological box

1. **Function**: what the configuration must achieve, with acceptance criteria.
2. **Parameters**: 4-7 independent dimensions of the solution (choices, not criteria). Test of
   independence: you can change one without the definition of another changing.
3. **Values**: 2-5 per parameter, mutually exclusive, collectively covering the realistic options;
   include `none` where meaningful. Box size = product of value counts.
4. **Cross-consistency assessment (CCA)**: judge every pair of values from different parameters
   (sum over parameter pairs of k_i x k_j cells). Mark incompatible pairs with a type and a reason:
   `L` logical (contradiction in terms), `E` empirical (known not to work), `N` normative (violates a
   policy or invariant). Add `requires` rules ("remote execution requires a content-addressed
   cache"). A value incompatible with every value of another parameter is dead; delete it.
5. **Enumerate and prune** with the script (backtracking, stdlib):

   ```bash
   STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
   python3 "$STACK/.claude/skills/triz-morphological/scripts/morph_box.py" box.json --top 10 --diverse 5
   ```

   See the [script](scripts/morph_box.py) header for the JSON format (parameters, incompatible,
   requires, criteria weights, per-value scores 1-5).
6. **Score** surviving configurations on weighted criteria; take the top N and a **diverse
   shortlist** (greedy max-min Hamming distance). Additive scores ignore interactions; experts review
   the shortlist, they do not rubber-stamp the top row.
7. **Iterate**: when a top configuration violates something nobody wrote down, that is an unstated
   invariant. Add it (new parameter or rule) and rerun. Expect 2-3 iterations.
8. **Flag novelty**: configurations not in current practice are the inventive candidates; send the
   best one through first-principles feasibility and an adversarial check.

Sizing: keep boxes under ~5,000 raw configurations and under ~400 pairwise cells, or CCA judgments
become unreliable. Larger spaces: split into sub-boxes per subsystem, or have parallel `validator` agents
(MEDIUM tier), or the owning domain expert, judge CCA cells per parameter pair (one message,
`run_in_background: false`, no model/effort on the calls; each returns only incompatible pairs with
reasons).

## Worked example: CI is too slow but must stay thorough

Function: give PR authors a trustworthy signal fast. Today all 14k tests run per PR: 45 minutes.

- TC1: run all tests per PR, then confidence is high, but feedback takes 45 minutes.
- TC2: run few tests, then feedback is fast, but regressions escape.
- PC: the PR's test set must be **large** (catch regressions) and **small** (fast feedback).
- Separation: time (small set per push, full set in the merge queue or nightly); space (shard across
  machines); condition (only tests whose dependencies changed); levels (each PR runs few, the system
  of PR lane + gate + nightly runs everything).
- IFR: the change itself selects exactly the tests that could fail, and they run instantly from cache
  without extra machines. Resources present: the build graph, test failure history, idle capacity at
  night.
- Principles: 16 partial action (affected tests), 10 preliminary action (remote build cache),
  26 copying (reuse cached artefacts), 1 segmentation (sharding), 34 discarding (quarantine flaky
  tests), 39 inert atmosphere (hermetic builds make caching sound).

Morphological box (run 1): pr_selection {affected, ml-predicted, all, none} x gate_selection {all,
affected} x execution {single, sharded, remote-exec} x cache {none, local, remote-cas} x flakes
{retry-once, quarantine, none} = 216. CCA: pr all + gate affected (N: PR stricter than the gate),
flakes none + either gate value (E: flakes block the queue, so `none` is dead), remote-exec requires
remote-cas (E). Survivors: 98 (54.6% pruned).

The top row was `ml-predicted PR, affected gate, remote-exec, remote-cas, quarantine`: nothing ever
runs the full suite. Unstated invariant found; run 2 adds `safety_net {none, nightly-full}` and
"gate affected requires nightly-full". Box 432, survivors 154 (64.3% pruned). Top: the same row plus
`nightly-full` (score 3.87); the diverse shortlist adds `affected PR, full gate, sharded,
remote-cas, quarantine, no nightly` (3.63), the conservative alternative. Both go to a feasibility
check: remote-cas soundness depends on hermetic builds (verify with tester), and ML-predicted
selection needs failure history of sufficient size (quick check of CI history). Full JSON and output:
[worked example data](references/worked-example-ci.md).

## Delegation

- Keep: contradiction formulation, separation choice, IFR; they need one coherent view.
- Spawn in parallel when useful: domain experts to instantiate principles in their field (one
  message, 3-5 calls with `run_in_background: false`, each returns 3 concrete instantiations with
  feasibility notes); CCA judges per parameter pair for large boxes; adversarial-verifier on the chosen inventive configuration.
- At `remaining_depth="0"`, run everything yourself; the script needs no agents. At
  `budget="soft"` spawn no new experts or judges; at `budget="hard"` spawn only finishing agents
  (file-summarizer, quality-control, validator, source-summarizer) and list unjudged cells as Open
  doubts.

## Pitfalls

- Compromise disguised as resolution ("run half the tests"): a resolution makes the conflict vanish
  for the main function.
- Contradiction on two elements ("speed vs cost") instead of one element with two states.
- Parameters that are criteria ("cheapness") instead of choices.
- Values that overlap ("sharded", "parallel"), making the box double-count.
- CCA cells marked incompatible without a reason; unauditable pruning hides good options.
- Treating the top additive score as the answer.

## Output

Follow output-contract. `## Result`: the PC, the separation and principles used, the IFR, the chosen
configuration plus the diverse alternatives with scores. `## Evidence`: CCA reasons for every pruned
pair, script output, feasibility checks. `## Files`: `box.json`, script output, contradiction worksheet
under your `out_dir`. `## Open doubts`: criteria weights the caller should confirm, unverified
feasibility of novel configurations. `## Confidence`: based on feasibility checks, not on the score.
