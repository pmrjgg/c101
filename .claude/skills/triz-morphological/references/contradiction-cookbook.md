# Software contradiction cookbook

Recurring physical contradictions in software and computing systems, with the separation that
usually resolves them, the principles involved and the patterns practice has converged on. This
replaces Altshuller's 39 x 39 matrix, whose physical parameters (weight, temperature, ...) map poorly
to software. The mapping below is engineering judgment distilled from widely used patterns, not a
statistical result: use it to seed ideas, then check feasibility.

| Element | Must be A to... | Must be not-A to... | Separation | Principles | Known resolutions |
|---|---|---|---|---|---|
| batch size | large: throughput | small: latency | condition, time | 15, 5, 19 | dynamic batching with a max wait; continuous batching in model serving |
| replication acknowledgement | synchronous: durability | asynchronous: latency | condition, space | 3, 4, 16 | majority-quorum ack, async to remote regions |
| lock granularity | coarse: simplicity | fine: concurrency | levels, space | 1, 17, 21 | striped locks, MVCC, optimistic concurrency, lock-free fast path |
| cache TTL | long: hit rate | short: freshness | condition | 23, 10, 15 | event-driven invalidation plus long TTL; stale-while-revalidate |
| log verbosity | high: debuggability | low: cost and overhead | time, condition | 15, 11, 34 | in-memory flight recorder flushed on error; dynamic levels; tail sampling |
| API surface | rich: power users | minimal: simplicity and stability | levels | 7, 3 | layered API (small stable core, convenience layer), progressive disclosure |
| security friction | strict: safety | lenient: usability | condition | 3, 15 | risk-based step-up authentication |
| test set per change | large: catch regressions | small: fast feedback | time, condition, levels | 16, 10, 1 | affected-test selection, merge queue, nightly full run, remote cache |
| schema | strict: integrity | flexible: evolution | space, levels | 3, 30, 40 | strict core columns plus an extension column; schema-on-read raw zone, curated zone on write |
| number of services | many: team autonomy | few: operational simplicity | levels | 1, 5, 33 | modular monolith (separate modules, single deployable) |
| timeout | long: avoid false failures | short: bound latency | condition | 15, 16, 23 | percentile-derived adaptive timeouts, deadline propagation, hedged requests |
| data placement | central: consistency | distributed: latency | space | 2, 3, 26 | home region per user, regional read replicas |
| isolation | strong (VM): security | light (process): density | levels, condition | 30, 39, 40 | microVMs, user-space kernels, sandboxes |
| model size | large: accuracy | small: latency and cost | condition, time | 3, 24, 40, 16 | cascades with escalation on uncertainty, speculative decoding, distillation |
| numeric precision | high: accuracy | low: speed and memory | space, levels | 3, 35, 40 | mixed precision with high-precision accumulators and master weights |
| consistency | strong: correctness | weak: availability and latency | condition | 3, 40 | per-operation consistency levels; CRDTs for commutative data |
| retries | many: success rate | few: avoid retry storms | condition, levels | 18, 23, 37 | cluster-wide retry budgets, exponential backoff with jitter |
| deployment speed | fast: velocity | slow: safety | time, space | 11, 16, 23 | progressive delivery with automated rollback on SLO burn |
| telemetry cardinality | high: debugging | low: cost | time, condition | 34, 16, 32 | short-retention raw events, aggregated long-term; exemplars; tail sampling |
| precomputation | much: speed | little: memory and staleness | condition | 10, 3 | memoise the hot subset; materialise only high-traffic views |
| personal data use | much: personalisation | little: privacy | space, levels | 2, 3, 13 | on-device personalisation, federated learning, differentially private aggregates |
| repository structure | one repo: atomic changes | many repos: autonomy, scale | levels | 1, 7 | monorepo with ownership files, sparse checkout, per-directory CI |
| code review depth | deep: quality | shallow: throughput | condition | 3, 16 | risk-tiered review (owners and critical paths deep, rest light) |
| on-call alert sensitivity | high: catch incidents | low: avoid fatigue | condition, time | 37, 23 | multi-window burn-rate alerts, separate fire and resolve thresholds |

## ARIZ-lite: when no row fits

1. State the mini-problem: keep the system as is, add nothing, achieve the function.
2. Name the conflicting pair (tool and object) and the operating zone and time.
3. Write TC1 and TC2; intensify both to extremes.
4. Write the PC at the operating zone: "the zone must be A and not-A".
5. Try separations in order: time, space, condition, levels.
6. Inventory resources in the zone (section 3 of SKILL.md); prefer solutions that use them.
7. If still stuck, move the PC up one system level (the system containing the element) or down one
   (its parts) and repeat.
