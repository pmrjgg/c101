---
name: analogical-transfer
description: "Structure-mapping across domains: abstract a problem to its relations, constraints and dimensionless regime, retrieve structurally (not superficially) similar problems from other fields using a seed catalogue and search, build an explicit correspondence, check which relations survive the mapping, transfer the source domain's canonical method, and validate the transfer by derivation, precedent, simulation or adversarial check. Load when a problem looks stuck within its own field or when another field may already have solved its structure."
when_to_use: "analogy-mapper and cross-domain-synthesizer; design or research problems with no good in-field answer, recurring failure patterns (oscillation, contention, cascade, drift), or when an expert ensemble needs a cross-domain idea. Not for problems with a known in-field method (use it) or as a substitute for evidence."
---

# Analogical transfer

An analogy is useful when the **relations** between things carry over, not when the things look
alike. Structure-mapping theory (Gentner, 1983) states the rules this skill operationalises: map
relational structure and drop object attributes; prefer **systematic** mappings, where connected
systems of higher-order relations (causes, constrains, trades off against) carry over together;
keep correspondences one-to-one and connected. Two empirical facts drive the procedure: people (and
models) retrieve analogues by surface similarity while structural similarity is what makes them
useful (Gentner, Rattermann and Forbus, 1993), and spontaneous transfer is rare without abstraction
or two worked analogues (Gick and Holyoak, 1980, 1983). So: abstract first, retrieve by structure,
map explicitly, check for breakage, then validate as you would any hypothesis.

## 0. When to use

| Signal | Use analogy? |
|---|---|
| in-field methods exhausted or clearly misfit | yes |
| a recognisable dynamic: oscillation, contention, cascade, diffusion, drift, selection, matching | yes; strong prior that another field has a canonical method |
| need a novel design option for an ensemble or debate | yes, as idea generation, labelled speculative until validated |
| a known, well-tested in-field method exists | no; use it |
| decision needs evidence, not ideas | no; analogies generate hypotheses, they never prove |

## 1. Abstract the target

Write the relational skeleton. Drop every domain noun you can.

```markdown
## Target skeleton
Entities (roles, not names): controller, capacity units, demand, measurement
Relations (first order): capacity serves demand; controller sets capacity; measurement observes utilisation
Higher-order relations: measurement lags reality (CAUSES stale input); capacity takes time to arrive
  (DELAYS effect); controller output FEEDS BACK into the measured signal
Objective: track demand with utilisation near a target, minimal churn
Constraints: capacity is discrete; adding is slow, removing is fast; demand is noisy
Invariants: capacity x per-unit throughput >= demand at steady state
Regime: delay / response-time ratio about 1; gain multiplicative; utilisation saturates at 100%
Symptom: sustained oscillation or runaway, not noise
```

Then climb an **abstraction ladder** of three rungs; each rung is a retrieval cue:

| Rung | Example |
|---|---|
| concrete | "autoscaler oscillates between 6 and 40 pods under steady traffic" |
| domain-general | "feedback controller acting on a delayed, stale measurement overshoots" |
| mathematical | "discrete-time loop with dead time and multiplicative gain; stability depends on gain x delay" |

The mathematical rung is the most powerful cue: the same equation means the same behaviour, whatever
the field (heat equation, logistic growth, M/M/1 queue, harmonic oscillator, percolation, random walk).
Also write the **dimensionless groups** (ratios that set the regime): delay/time-constant,
utilisation rho = lambda/mu, working set/cache size, signal/noise, read/write ratio. Analogies hold
only within matching regimes.

## 2. Retrieve candidates

Goal: at least 5 candidates from at least 3 fields, at least one **far** (different field family)
and at least one **near** (adjacent discipline). Sources, in order of cost:

1. **Seed catalogue** below and the full [analogy catalogue](references/analogy-catalog.md): match on
   the "abstract structure" column, never on the domain column.
2. **Same mathematics**: ask "where else does this equation or this dimensionless group appear?"
   (`mathematics-expert` or `physics-expert` for one targeted call if you cannot answer).
3. **Search by structure**: phrase queries with the skeleton, not the surface domain.
   - `mcp__exa__web_search_exa` with "remedy for oscillation caused by delayed feedback in a control loop"
   - `mcp__jina__search_arxiv` with up to 5 parallel queries, one per rung or per field family
   - precedent queries: "<source method> applied to <target field>" (for example
     "supply chain bullwhip autoscaling")
4. **Blind retrieval for breadth**: spawn 3-5 `web-searcher` retrievers (MEDIUM tier; no
   model/effort on the call) in one message with `run_in_background: false`, one per field family
   (physical sciences, life sciences, economics and operations research, control and engineering,
   mathematics and CS). Give them **only the skeleton**, never the target's
   domain nouns; that is what stops surface retrieval. Each returns up to 3 candidates with the
   source domain's canonical method and one citation.

Record each candidate: source domain, source problem, canonical method (with citation), why it
seemed to match (which skeleton relations).

## 3. Map

For each shortlisted candidate (keep 2-4), build the correspondence table:

| Source element or relation | Target element or relation | Kind | Survives? | Note |
|---|---|---|---|---|
| retailer's order quantity | desired replica count | object | n/a | |
| shipment lead time | pod startup time | relation (DELAYS) | yes | |
| ordering on recent sales, ignoring the supply line | scaling on stale utilisation x current replicas | higher-order (CAUSES overshoot) | yes | the solution-critical relation |
| warehouse stock is conserved | capacity is not conserved (pods can be killed instantly) | constraint | modified | removal is fast, adding slow |

Mapping rules (Gentner's constraints, operationally):
- **One-to-one**: one source element maps to one target element. If you need many-to-one, the
  analogy is probably at the wrong abstraction level.
- **Parallel connectivity**: if relation R(a, b) maps to R'(a', b'), then a maps to a' and b to b'.
- **Systematicity**: prefer the candidate whose mapped relations form a connected causal chain over
  one with more but disconnected matches.
- Attributes (colour, size, material, brand) are not mapped. If the mapping relies on them, it is
  a surface analogy; discard it.

## 4. Check which relations survive

Run the disanalogy checklist on every relation the transferred solution relies on (the
**solution-critical** relations). One breakage on a solution-critical relation invalidates the
transfer unless you can adapt it (section 6).

| Dimension | Question | Classic breakage |
|---|---|---|
| conservation | is the quantity conserved in both? | information can be copied; fluid analogies for data break at replication and caching |
| agency | passive elements or strategic agents? | traffic-as-fluid breaks when drivers reroute (Braess's paradox); policy changes behaviour (Lucas critique) |
| independence | are events independent in both? | insurance pooling and statistical multiplexing fail under correlated failures |
| linearity | does superposition hold in both? | linear-circuit intuitions on saturating systems |
| regime | same range of the dimensionless groups? | laminar vs turbulent; queue behaviour near rho = 1 differs qualitatively from rho = 0.5 |
| time scales | same ratio of delay to dynamics? | control remedies tuned for slow plants on fast ones |
| memory | path dependence, hysteresis, irreversibility present in one only? | |
| topology and dimension | same network structure or dimensionality? | percolation thresholds depend on lattice and dimension |
| noise | same distribution class? | Gaussian-based methods on heavy-tailed latency |
| boundary | open vs closed system? | conservation reasoning on an open system |
| objective | same thing being optimised? | evolution does not optimise for the designer's objective |
| cost structure | what is cheap and expensive in each? | biology: material cheap, energy dear; software: copies free, coordination dear |
| observability and control | can you measure and actuate the same variables? | source remedy needs a sensor the target lacks |

## 5. Score and choose

```
s_r  = 1 (survives), 0.5 (survives with modification), 0 (breaks)
w_r  = 2 for higher-order relations (CAUSES, PREVENTS, TRADES-OFF, CONSTRAINS), 1 for first-order
S    = sum(w_r * s_r) / sum(w_r)                over mapped relations
Gate = every solution-critical relation has s_r >= 0.5
```

Rank candidates by S among those passing the gate; break ties by pragmatic relevance (does the source
method target the same objective?) and by precedent (has this transfer been done before?). S >= 0.7
with the gate passed is a strong analogy; 0.4-0.7 is a source of partial ideas; below 0.4, discard.

## 6. Transfer

1. State the source's canonical method precisely, with its citation (paper, textbook, standard).
2. Push it through the correspondence table, producing **candidate inferences**: statements about the
   target that the source makes you expect ("counting capacity in the supply line removes the
   overshoot").
3. At each relation marked `modified`, adapt the method and say how (discrete capacity, asymmetric
   add/remove cost, different noise).
4. List what the source says you should observe if the transfer is right (predictions). These are
   what validation tests.

## 7. Validate

A transferred solution is a hypothesis. Climb this ladder as far as the stakes require:

| Level | Check | Who |
|---|---|---|
| mapped | correspondence and survival check done | you |
| derived | source's governing relation re-derived in target variables; units consistent | you, or mathematics-expert / physics-expert |
| precedent | literature or practice shows the transfer working (search "<method> for <target>") | web-searcher, paper-researcher |
| simulated | toy model or prototype shows the predicted effect and a control does not | you via Bash, or tester |
| attacked | adversarial-verifier tried to break the candidate inference | adversarial-verifier |
| piloted | measured in the target system against an acceptance criterion | tester, caller |

Report the level reached; never present a `mapped`-only transfer as a recommendation.

## Seed catalogue (compact)

| Abstract structure | Source domain and problem | Canonical method | Known target transfers |
|---|---|---|---|
| delayed feedback overshoots | supply chains (bullwhip effect, beer game) | account for the supply line; share demand signal upstream | autoscaling, inventory of caches, retry budgets |
| dead time in a control loop | process control (shower with a long pipe) | lower gain, Smith predictor, feedforward | autoscaling, rate limiters |
| bang-bang control chatters | thermostats | hysteresis deadband | autoscaler tolerance, alert flapping |
| spread through contacts | epidemiology (SIR) | R0, herd threshold, rumour mongering | gossip protocols (Demers et al., 1987), worm propagation |
| many agents share a link fairly | TCP congestion control | AIMD (Chiu and Jain, 1989) | rate limiting, client backoff |
| escaping local optima | metallurgy (annealing) | simulated annealing (Kirkpatrick et al., 1983) | placement, scheduling |
| collective path finding | ant foraging | pheromone reinforcement (ACO) | routing (AntNet), TSP heuristics |
| diffusion of a quantity | heat conduction | heat equation, Green's functions | option pricing (Black-Scholes reduces to it), graph label propagation |
| random walk vs network flow | electrical networks | effective resistance (Doyle and Snell) | commute times, graph sparsification |
| density waves in a flow | traffic flow (LWR model) | kinematic waves, shock formation | packet queues, conveyor and pipeline backpressure |
| pull-based flow control | lean manufacturing (kanban) | WIP limits | reactive-streams backpressure, sprint WIP limits |
| redundancy against random loss | coding theory | erasure codes (Reed-Solomon) | storage (RAID, object stores), DNA storage |
| sparse signal, few measurements | signal processing | compressed sensing | MRI acceleration (Lustig et al., 2007) |
| energy minimisation in coupled units | statistical physics (Ising) | Boltzmann distribution, mean field | Hopfield networks, Boltzmann machines |
| state estimation from noisy sensors | navigation | Kalman filter | SLAM, econometrics, sensor fusion |
| contain a failure | ships (bulkheads), electricity (breakers) | compartmentalise, trip on overload | bulkhead and circuit-breaker patterns |
| tail risk under redundancy | finance (portfolio hedging) | diversify across uncorrelated assets | hedged requests (Dean and Barroso, 2013), multi-region |
| checklists for complex procedures | aviation | read-do and do-confirm checklists | surgery (Haynes et al., 2009), deploy runbooks |
| pattern formation from local rules | morphogenesis (Turing, 1952) | reaction-diffusion | procedural textures (Turk, 1991; Witkin and Kass, 1991) |
| coordinated motion without a leader | bird flocks | boids rules (Reynolds, 1987) | swarm robotics, drone formations |
| shortest path through varying media | optics (Fermat, Snell) | eikonal equation, fast marching | path planning, geodesic distances |
| matching two sides of a market | economics | deferred acceptance (Gale-Shapley) | residency matching, resource allocation |

The full catalogue (60+ entries with breakpoints) is in [analogy catalogue](references/analogy-catalog.md).

## Worked example (autoscaler)

Target: an in-house autoscaler oscillates or runs away under steady traffic. Skeleton as in section 1.

Candidates: (1) supply-chain bullwhip, (2) shower with a long pipe (dead time), (3) thermostat
hysteresis, (4) predator-prey cycles (far), (5) TCP AIMD.

| Candidate | S | Gate | Why |
|---|---|---|---|
| bullwhip | 0.85 | pass | ordering on stale signal while ignoring the supply line maps one-to-one; conservation modified |
| dead time | 0.80 | pass | same loop structure; remedy (lower gain) transfers directly |
| hysteresis | 0.60 | pass | explains chatter, not runaway; partial |
| AIMD | 0.50 | pass | asymmetric increase/decrease transfers; fairness objective does not |
| predator-prey | 0.25 | fail | two coupled populations, no setpoint, no controller; surface "cycles" only |

Candidate inferences: (a) basing the scale decision on replicas at sample time (the supply line)
removes the overshoot; (b) limiting step size reduces but does not remove oscillation; (c) a
deadband alone does not fix a runaway. Validation level reached: **simulated**. A 40-line toy model
(in [worksheets](references/worksheets.md)) gives: naive controller runs away (1 to 663 replicas);
step limit 2 leaves a 19-43 limit cycle; deadband plus scale-down window still runs away; consistent
basis settles at 31 (ideal 30). Inference (a) confirmed in the toy, (b) and (c) as predicted. Next
level: tester runs a staging load test with the consistent-basis change and a control run.

Note what the analogy did: the dead-time view alone suggests "lower the gain"; the bullwhip view
names the actual mechanism (decisions ignoring capacity already in flight) and its canonical fix.

## Delegation

- You keep: skeleton, mapping, survival check, scoring. These need one coherent mind.
- Spawn in parallel: blind retrievers per field family (section 2); one domain expert per shortlisted
  source domain to confirm you stated its canonical method correctly (the expert runs on its own tier
  and effort; pass no model/effort, or use quick-researcher for a cheap check); adversarial-verifier
  on the top candidate inference. Issue the parallel calls with `run_in_background: false`, because
  mapping needs their answers.
- At `remaining_depth="1"`, spawn only retrievers and verifiers (leaves); at 0, use the seed
  catalogue and your own search calls. At `budget="soft"` spawn no new retrievers: map what you
  have; at `budget="hard"` spawn only finishing agents (file-summarizer, quality-control,
  validator, source-summarizer) and list unchecked candidates as Open doubts.

## Pitfalls

- Mapping nouns instead of relations ("both have nodes").
- Stopping at the first analogy; the second one often names the mechanism (example above).
- Ignoring the regime: a correct analogy outside its dimensionless range is a wrong analogy.
- Treating precedent in a paper title as validation; read whether the transfer worked.
- Presenting a poetic analogy as evidence in a report; it is an idea until validated.

## Output

Follow output-contract. `## Result`: the chosen analogy, the correspondence of solution-critical
relations, the transferred method, predictions, and the validation level reached. `## Evidence`:
citations for the source method, survival-check outcomes, simulation or test outputs. `## Files`:
mapping worksheet under your `out_dir`. `## Open doubts`: relations marked `modified` that were not
validated and the check that would settle each. `## Confidence`: capped at low for `mapped`, medium
for `derived` or `precedent`, high only for `simulated` plus `attacked` or `piloted`.
