---
name: first-principles
description: "First-principles decomposition: state the function instead of the solution, classify every constraint as physical, mathematical, resource, contractual, convention or preference, derive hard bounds (Fermi estimates, dimensional analysis, throughput and latency laws, information-theoretic limits, impossibility theorems), measure the distance to the bound, rebuild the solution space from invariants, and test proposals against the fundamentals. Load when a problem is stuck on inherited assumptions or a claim needs a sanity bound."
when_to_use: "first-principles-decomposer; feasibility checks (can this be done at all, how fast at best), challenging conventions in a design, deciding whether optimisation can still pay or the problem must change, and sanity-checking any number an expert or plan asserts. Not a licence to re-derive well-established results at length."
---

# First-principles reasoning

Reduce a problem to what physics, mathematics and binding commitments force, treat everything else
as a choice, then rebuild. The output is concrete: a constraint ledger, a set of bounds with
derivations, the gap between the current state and the bound, a rebuilt option space, and verdicts
on proposals. The discipline cuts both ways: it exposes conventions mistaken for laws ("a database
needs a single leader") and laws mistaken for conventions ("we'll just make the cross-ocean call
faster").

## 0. When to use

| Situation | Use? |
|---|---|
| a requirement or plan might be physically or mathematically impossible | yes, first |
| optimisation has stalled; unsure whether more effort can pay | yes (section 4) |
| the team says "this is how it is done" for a costly choice | yes, with Chesterton's fence (section 2) |
| an expert asserts a number that drives a decision | yes, as a sanity bound (section 6) |
| a well-known, well-tested method exists and fits | no; use it, cite it |

## 1. State the function, not the solution

Rewrite the request as the function to be performed, with its measurable boundary:

```markdown
Function: <verb> <object> <quality measure with number, percentile, boundary>
Example (bad):  "We need a faster cache cluster."
Example (good): "Return a user's profile to any client worldwide, end-to-end p99 < 10 ms,
                 data no staler than <X> seconds, at 50k reads/s peak."
```

Ask back (Open doubt) when the boundary is missing and the answer depends on it: client-side vs
server-side latency, percentile, staleness, peak vs average, per-tenant vs aggregate.

## 2. Constraint ledger

List every constraint the brief, the codebase or the experts impose, then classify it:

| Class | Test | Example | Changeable? |
|---|---|---|---|
| H-phys | violating it contradicts a physical law | fibre RTT Sydney to Virginia >= ~157 ms | never |
| H-math | a theorem forbids it (check its assumptions) | deterministic consensus with one crash in a fully asynchronous system (FLP) | never inside the theorem's assumptions |
| H-resource | current budget, hardware, people, time | 3 engineers, 2 GPUs, ship by March | yes, with money or time |
| contract | law, regulation, SLA, published API | data residency rule; public API v1 | yes, slowly, at negotiation cost |
| convention | industry practice, defaults, "how we do it" | one database per service; 3 replicas; nightly batch | yes, after Chesterton's fence |
| preference | stakeholder taste | language, framework | yes, by persuasion |

Interrogate each constraint with five questions and write the answers in the ledger:
1. What exactly enforces it: a law, a theorem, a contract, a person, a habit?
2. What happens if it is violated: impossible, illegal, someone objects, nothing?
3. Under which assumptions does the enforcing rule hold? (Theorems have preconditions; most
   "impossible" engineering claims die here, and so do most "we can beat it" claims.)
4. Who can waive it, at what cost?
5. **Chesterton's fence**: for conventions, why did it originate, and does that reason still hold?
   Conventions often encode a lesson from an incident; discard them only once you can state the
   lesson and show it no longer applies.

Ledger row format:

| Id | Constraint | Class | Enforced by | Assumptions | Waiver cost | Fence reason (conventions) |
|---|---|---|---|---|---|---|

## 3. Derive bounds

A bound is a number no solution can beat, derived from H-phys and H-math constraints, with the
derivation shown. Use the cheapest method that is tight enough to decide.

### 3.1 Fermi estimation

1. Write the target quantity as a product or sum of factors you can estimate.
2. Estimate each factor with a low and a high you would bet on; take the **geometric mean**
   `sqrt(low * high)` as the point estimate.
3. Track uncertainty in log space: if factor i spans a ratio r_i = high/low, the product's spread is
   roughly `exp(sqrt(sum((ln r_i / 2)^2)))` either side of the point estimate.
4. Cross-check with an independent decomposition; two routes within ~3x is a usable estimate.

### 3.2 Dimensional analysis

Buckingham pi: n variables built from k independent base dimensions form n - k independent
dimensionless groups, and any physical relation among the variables is a relation among those groups.
Procedure: list variables with dimensions, pick k repeating variables, form the groups, and reason in
groups. In systems work the dimensionless groups are the regime parameters:

| Group | Meaning | Regime change near |
|---|---|---|
| rho = lambda / mu | utilisation | 0.7-0.9: queueing delay explodes |
| working set / cache size | cache pressure | 1: hit rate collapses |
| delay / control time constant | loop stability | ~1: oscillation risk |
| arithmetic intensity / ridge point | compute vs memory bound | 1 |
| message size x rate / bandwidth | link utilisation | 1 |
| BDP / window | flow-control limit | > 1: window-limited |

Every formula you write must type-check in units; a units error found here is cheaper than a bug.

### 3.3 Laws for throughput, latency and capacity

| Law | Formula | Use |
|---|---|---|
| Little | L = lambda W | concurrency needed for a throughput at a latency |
| M/M/1 queue | W = (1/mu) / (1 - rho) | at rho 0.9 response time is 10x service time (queue wait 9x) |
| Amdahl | S(N) = 1 / ((1 - p) + p / N), max 1/(1 - p) | parallel speedup ceiling |
| Gustafson | S(N) = (1 - p) + p N | speedup when the problem grows with N |
| Universal Scalability Law | C(N) = N / (1 + a (N - 1) + b N (N - 1)), peak at N* = sqrt((1 - a) / b) | contention a and coherence b; fit to measurements |
| Roofline | P = min(P_peak, I x B), ridge I* = P_peak / B | compute- vs memory-bound kernels |
| bandwidth-delay product | BDP = B x RTT | in-flight bytes needed to fill a link (10 Gbit/s x 100 ms = 125 MB) |
| light in fibre | ~2 x 10^5 km/s: 5 us per km one way, ~1 ms RTT per 100 km of path | latency floor between sites |
| availability in series / parallel | prod A_i ; 1 - prod (1 - A_i) | composition (99.9% = 8.76 h/yr down, 99.99% = 52.6 min/yr) |
| at least one failure | 1 - (1 - p)^n | fleet-level failure odds |
| birthday bound | P(collision) ~ 1 - exp(-n^2 / (2 N)); 50% at n ~ 1.18 sqrt(N) | ID sizes (64-bit random IDs: 50% at ~5 x 10^9) |

Hardware and latency reference numbers with sources and caveats: [numbers and limits](references/numbers-and-limits.md).
Measure your own hardware when the decision hinges on a factor of 2.

### 3.4 Information-theoretic limits

| Limit | Statement | Typical use |
|---|---|---|
| identification | distinguishing N outcomes needs >= log2 N bits or binary decisions | minimum questions, key sizes, comparisons |
| comparison sorting | >= log2(n!) ~ n log2 n - 1.443 n comparisons | loophole: non-comparison sorts on bounded keys |
| source coding | average code length >= entropy H = -sum p log2 p (model-relative) | compression ceilings; better models lower H |
| channel capacity | C = B log2(1 + S/N) | link and sensor limits |
| sampling | band-limited signal needs rate > 2B | loophole: sparsity (compressed sensing) |
| erasure energy | >= kT ln 2 per bit erased (~2.87 x 10^-21 J at 300 K) | far below practice today; matters only for theory |

### 3.5 Impossibility theorems (check preconditions before invoking)

| Result | Forbids | Precondition that real systems relax |
|---|---|---|
| FLP (Fischer, Lynch, Paterson, 1985) | deterministic consensus with one crash fault, full asynchrony | partial synchrony (timeouts), randomisation, failure detectors |
| CAP (Gilbert and Lynch, 2002) | linearizability and availability during a partition | partitions are rare; PACELC adds the latency vs consistency trade otherwise |
| Byzantine agreement (Lamport, Shostak, Pease, 1982) | tolerating f traitors with n <= 3f in the oral-messages model | signatures relax some bounds in synchronous settings |
| Two Generals | guaranteed agreement over a lossy channel with finite messages | idempotency, retries, probabilistic guarantees |
| Halting problem, Rice's theorem | deciding non-trivial semantic properties of all programs | sound approximations, restricted languages, timeouts |
| No free lunch (Wolpert and Macready, 1997) | an optimiser best on all problems | real problems have structure; exploit it |
| Arrow (1951) | ranked voting with 3+ options meeting all fairness axioms | cardinal or approval ballots; relax independence of irrelevant alternatives |
| No-cloning | copying an unknown quantum state | teleportation (consumes the original) |
| diffraction limit (Abbe) | optical resolution below ~lambda / (2 NA) | super-resolution via nonlinear or stochastic tricks (STED, PALM) |

A proposal that appears to beat a bound is either wrong or relaxes a precondition. Find which; a
legitimate relaxation is often the insight.

## 4. Distance to the bound

Gap factor G = (current performance) / (bound), oriented so that G >= 1 means "worse than ideal"
(latency: current / floor; throughput: ceiling / current).

| G | Meaning | Move |
|---|---|---|
| > 100 | waste dominates | look for gross inefficiency: algorithm, architecture, data movement; redesign pays |
| 10-100 | real headroom | profile and remove overheads; targeted engineering |
| 2-10 | typical well-built system | diminishing returns; weigh changing the problem |
| < 2 | at the wall | only changing constraints helps: relax a requirement, batch, approximate, precompute, move data or compute |

Never optimise blind to G. Teams routinely spend weeks on kernels at G = 1.3 and ignore designs at
G = 50.

## 5. Rebuild the solution space from invariants

1. **Invariants**: properties every acceptable solution must have, from H-phys, H-math and contract
   rows ("an acknowledged write survives loss of one zone"). Derive their consequences as new bounds
   ("ack requires a cross-zone round trip, so write p50 >= inter-zone RTT").
2. **Degrees of freedom**: everything fixed only by conventions, preferences or current resources.
3. **Generate** options along these axes, one change at a time:
   - invert one convention (push vs pull, shared vs dedicated, sync vs async, server vs client);
   - move work in **time** (precompute, defer, batch), **space** (to the data, to the edge, to the
     client), **representation** (compress, approximate, quantise, encode), **agent** (hardware
     offload, third party, the user);
   - relax one soft constraint and price the relaxation.
4. **Prune** with bounds and invariants immediately. With 3+ independent degrees of freedom, build a
   morphological box (triz-morphological) instead of listing options freehand.
5. For each survivor compute its own bound and G; rank by (bound quality, cost of the conventions it
   breaks, risk).

## 6. Test proposals against the fundamentals

Run on every proposal, plan step or asserted number that matters:

- [ ] Units consistent in every formula; dimensionless groups identified.
- [ ] Limiting cases behave: n -> 0 and n -> infinity, load -> 0 and load -> capacity, failure
      probability -> 0 and -> 1, latency -> 0.
- [ ] Conservation: requests, bytes, money, energy in = out + stored + dropped.
- [ ] Does not beat a bound or theorem; if it seems to, the relaxed precondition is named.
- [ ] Independent Fermi estimate agrees within ~3x.
- [ ] First bottleneck named, with the load at which it saturates.
- [ ] Tail behaviour stated (p99, rho -> 1, correlated failures).
- [ ] Cost of each broken convention priced (tooling, migration, people, ecosystem).

## 7. Delegation

- Keep: the ledger, bounds, gap factor and verdicts; they need one consistent model.
- Spawn (parallel, one message, `run_in_background: false`) when a bound needs domain depth:
  physics-expert (physical limits, dimensional analysis), computer-science-expert (lower bounds,
  impossibility preconditions), mathematics-expert (a derivation or inequality), code-optimizer or
  tester (measure the actual hardware number when G hinges on it), quick-researcher (a datasheet
  figure; MEDIUM tier). Agents run on their tiers (config/models.json); pass no model/effort. At
  `budget="soft"` spawn nothing new and finish the ledger; at `budget="hard"` spawn only finishing
  agents and list unbounded items as Open doubts.
- Hand the rebuilt option space to triz-morphological (inside this agent). When options must be
  developed into plans: only if you are the main thread (no `<stack-context>` header), call the
  Workflow tool with name `plan-tournament`. Otherwise return `Workflow name=plan-tournament
  args={goal: "<function statement>", context: "<path to ledger and rebuilt options>"}` as an Open
  doubt for the main thread.

## Worked example 1: global reads from one region

Request: "every user worldwide reads their profile in under 10 ms p99, served from our single
us-east region". Function boundary clarified: end-to-end, client to response.

Bound: great-circle Sydney to northern Virginia is about 15,700 km. Light in fibre covers ~200,000
km/s, so the RTT floor is 2 x 15,700 / 200,000 = 157 ms before any routing detour (real paths add
tens of percent), TLS or server time. G >= 15.7 against a hard physical constraint: the requirement
is impossible as stated, not hard.

Rebuild: invariant "client receives profile data"; degrees of freedom: where data lives, how fresh it
must be, when it is fetched. Options: (a) read replicas or edge caches near users with bounded
staleness (PACELC: trade consistency for latency; staleness bound goes to the caller as an Open
doubt); (b) prefetch the profile at login and serve locally (moves work in time); (c) restate the
requirement as "10 ms p99 within region, 200 ms global". In-region RTT is around a millisecond, so
(a) and (b) can meet 10 ms where data is local.

## Worked example 2: is the GEMV kernel worth optimising?

y = A x with A of 16384 x 16384 fp32, on a GPU with ~3 TB/s memory bandwidth and ~60 TFLOP/s fp32
(use your datasheet). FLOPs = 2 n^2 = 5.37 x 10^8. Bytes >= 4 n^2 = 1.07 x 10^9 (reading A
dominates). Arithmetic intensity I = 0.5 FLOP/B; ridge point = 60 / 3 = 20 FLOP/B, so the kernel is
deeply memory-bound. Time floor = 1.07 x 10^9 / 3 x 10^12 = 0.36 ms; attainable ~1.5 TFLOP/s, 2.5% of
peak, by physics of the memory system, not by bad code.

Measured: 0.45 ms, so G = 1.25: stop tuning the kernel. Change the problem: batch k vectors into a
GEMM (intensity grows roughly with k while k is much smaller than n), store A in bf16 (halves bytes,
floor 0.18 ms; check accuracy), or exploit structure (sparsity, low rank).

## Pitfalls

- First-principles theatre: re-deriving textbook results at length. Cite them; derive only what is
  specific to the problem.
- Calling a convention physics, or physics a convention; the ledger's "enforced by" column prevents both.
- Invoking a theorem without checking its preconditions (FLP and CAP are the usual victims).
- Bounds without units, percentiles or boundaries; they cannot be compared to anything.
- Fermi estimates reported with false precision; give the range.
- Discarding a convention without stating the lesson it encodes.

## Output

Follow output-contract. `## Result`: function statement, the decisive bounds with G, verdict per
proposal (feasible / infeasible / feasible-if relaxed X), and the top rebuilt options.
`## Evidence`: derivations (or file anchors to them), sources for every hardware or physical number,
measurements with commands. `## Files`: ledger and derivations under your `out_dir`.
`## Open doubts`: boundary choices only the caller can make (percentile, staleness, budget).
`## Confidence`: high for bounds from physics or theorems with checked preconditions; lower for
bounds that rest on datasheet numbers you did not measure.
