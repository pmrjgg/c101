# The 40 inventive principles, extended

Sub-principles paraphrased from Altshuller's list, each followed by software / computing examples
(S), science or engineering examples (P) and a prompt question to ask about the element in your
physical contradiction. Use the prompt literally: write one concrete instantiation per principle you
try, then judge feasibility.

## 1. Segmentation
Divide into independent parts; make it sectional (easy to assemble and disassemble); increase the
degree of fragmentation.
S: sharding, microservices or modules, chunked uploads, mini-batches, GEMM tiling, per-tenant queues.
P: modular satellites, domain decomposition, powdered vs bulk reagents.
Prompt: what if the element were split into N independent pieces, or into infinitely many?

## 2. Taking out
Separate the interfering part or property; extract only the part that is needed.
S: auth and TLS at the gateway, out-of-band control plane, moving a noisy batch job to its own pool.
P: remote compressor for a cryostat, isolating the reference arm of an interferometer.
Prompt: which part causes the harm, and can it live elsewhere?

## 3. Local quality
Non-uniform instead of uniform; each part does a different function; each part in the conditions
best for it.
S: per-table consistency, mixed precision, tiered storage, per-endpoint rate limits.
P: adaptive mesh refinement, functionally graded materials.
Prompt: which parts need the property and which do not?

## 4. Asymmetry
Replace symmetry with asymmetry; increase existing asymmetry.
S: leader and followers, read replicas, asymmetric crypto, big.LITTLE cores, skew-aware partitioning.
P: asymmetric airfoils, asymmetric tyre treads.
Prompt: what if the two sides or the two directions were treated differently?

## 5. Merging
Merge identical or similar objects or operations; make operations contiguous or parallel in time.
S: batching, group commit, syscall coalescing, kernel fusion, co-locating compute and data.
P: multiplexed assays, combined harvesters.
Prompt: which repeated or adjacent operations could be done once, together?

## 6. Universality
One part performs several functions, removing other parts.
S: event log as replication stream, audit trail and cache-invalidation feed; one schema for API and storage.
P: multi-mode instruments, multifunction tools.
Prompt: which existing part could also do the missing function?

## 7. Nested doll
Place one object inside another; let one pass through a cavity in another.
S: cache hierarchies, BVH and octrees, nested virtualisation, hierarchical rate limits.
P: multigrid solvers, telescoping masts.
Prompt: can the element be layered or recursive?

## 8. Anti-weight
Compensate a burden by joining it with something that provides lift, or by the environment.
S: CDN or edge absorbing read load, NIC or TLS offload, managed services carrying operational weight.
P: buoyancy, hydrofoils, magnetic levitation.
Prompt: what in the environment could carry this load for free?

## 9. Preliminary anti-action
Apply counter-actions in advance to control a known harmful effect; pre-stress against working stress.
S: idempotency keys before retries exist, preallocation against fragmentation, load shedding thresholds set before overload.
P: pre-stressed concrete, predistortion in RF amplifiers.
Prompt: which harm is predictable enough to counter before it happens?

## 10. Preliminary action
Perform the change in advance, fully or partly; pre-place objects where they will act without delay.
S: materialised views, indexes, AOT compilation, prefetching, pre-signed URLs, warm pools.
P: preconditioning in iterative solvers, pre-pasted materials.
Prompt: what could be computed or positioned before the request arrives?

## 11. Beforehand cushioning
Prepare emergency means to compensate for low reliability.
S: backups, write-ahead logs, circuit breakers, feature-flag kill switches, fallbacks, canaries.
P: fuses, airbags, checkpoint-restart in HPC.
Prompt: when this fails, what already-prepared thing limits the damage?

## 12. Equipotentiality
Change working conditions so the object need not be raised or lowered in a potential field.
S: zero-copy I/O, shared memory, Arrow-style formats across processes, same-NUMA placement.
P: service pits, canal locks, thermal equilibration chambers.
Prompt: where is energy or time spent moving data between levels that could stay level?

## 13. The other way round
Invert the action; make moving parts fixed and fixed parts moving; turn it upside down.
S: push vs pull, inversion of control, moving compute to data, reverse-mode autodiff, client-side verification.
P: adjoint methods, rotating the workpiece rather than the tool.
Prompt: what if the direction, the actor or the frame were reversed?

## 14. Spheroidality, curvature
Curves instead of lines; rollers, balls, spirals; rotary motion.
S: ring buffers, consistent-hash rings, round-robin, log rotation, cyclic schedules.
P: arches and domes, ball bearings, centrifuges.
Prompt: could a linear, growing structure become cyclic and bounded?

## 15. Dynamics
Let characteristics change to be optimal at each stage; split into parts movable relative to each other; make rigid things adaptive.
S: autoscaling, adaptive timeouts, JIT recompilation, adaptive bitrate, dynamic batching.
P: adaptive step-size integrators, variable-geometry wings.
Prompt: which fixed parameter should follow the conditions?

## 16. Partial or excessive actions
If 100% is hard, do slightly less or more and simplify.
S: approximate counting (HyperLogLog), sampling, hedged requests, speculative execution, over-provisioning then trimming.
P: spin coating, overspray then trim.
Prompt: is exactness required, or would 99% plus a correction do?

## 17. Another dimension
Move into an extra dimension; multi-storey layouts; tilt; use the other side.
S: MVCC (time as a dimension), 2-D tiling of 1-D loops, multi-dimensional indexes, bitemporal tables.
P: multilayer PCBs, 3-D stacked memory, vertical farms.
Prompt: what if the element gained a time, layer or version axis?

## 18. Mechanical vibration
Oscillate; raise frequency; use resonance; replace mechanical with piezo or field-driven vibration.
S: jitter in retries and schedules, dithering, random restarts, perturbation in optimisation, fuzzing, chaos experiments.
P: ultrasonic cleaning, vibratory feeders.
Prompt: would deliberate randomness or perturbation break a harmful synchrony or local optimum?

## 19. Periodic action
Periodic instead of continuous; change the period; use pauses for another action.
S: heartbeats, periodic compaction and GC, checkpoint intervals, batch windows, polling with backoff.
P: pulsed lasers, PWM motor control.
Prompt: can continuous effort become pulses, with the gaps used for something else?

## 20. Continuity of useful action
Keep all parts working at full load; eliminate idle and intermittent motion.
S: pipelining, double buffering, overlapping transfer with compute, work stealing.
P: flywheels, continuous casting.
Prompt: where does the element sit idle waiting?

## 21. Skipping
Pass through harmful or hazardous stages at high speed.
S: short critical sections, lock-free fast paths, atomic blue-green cutover, short stop-the-world pauses.
P: flash pasteurisation, high-speed cutting before heat spreads.
Prompt: can the dangerous phase be made too short to matter?

## 22. Blessing in disguise
Use harmful factors for benefit; combine two harms to cancel; amplify a harm until it stops being harmful.
S: timeouts as failure detectors, errors as SLO signals, noise as regularisation, attack traffic as training data for detection.
P: waste-heat recovery, stochastic resonance, controlled burns.
Prompt: what useful signal or effect hides in the harm?

## 23. Feedback
Introduce feedback; change existing feedback's magnitude or sign.
S: closed-loop autoscaling, backpressure, profile-guided optimisation, adaptive concurrency limits.
P: adaptive optics, PID control.
Prompt: what measurement could steer the element automatically?

## 24. Intermediary
Use an intermediary carrier or process; temporarily join with an easily removed object.
S: queues, proxies, adapters, sidecars, indirection tables, staging tables.
P: catalysts, carrier gases.
Prompt: what mediator would decouple the two conflicting sides?

## 25. Self-service
The object serves itself; it uses its own waste.
S: reconciliation loops, self-tuning (this stack's learner), self-balancing trees, self-describing data, TCP self-clocking.
P: self-sharpening blades, self-healing polymers.
Prompt: could the element maintain or correct itself from signals it already produces?

## 26. Copying
Use cheap copies instead of expensive, fragile or unavailable originals; use images of them.
S: replicas, snapshots, copy-on-write, shadow traffic, mocks and fakes, digital twins.
P: wind-tunnel models, simulations, phantoms in medical imaging.
Prompt: what cheap copy could take the risk or load instead of the original?

## 27. Cheap short-living objects
Replace an expensive durable object with many cheap short-lived ones.
S: ephemeral environments, immutable infrastructure, spot instances, arena allocation, per-request processes.
P: disposable pipette tips and syringes.
Prompt: what if we replaced instead of repaired?

## 28. Mechanics substitution
Replace mechanical means with sensory, optical, acoustic, electric or magnetic fields; structured or moving fields.
S: polling to events or interrupts, manual runbooks to automation, physical keys to cryptographic keys.
P: optical tweezers, non-contact measurement.
Prompt: what "touch" could become a signal?

## 29. Pneumatics and hydraulics
Use gas or liquid parts: inflatable, liquid-filled, air cushion, hydrostatic.
S: queues and buffers as shock absorbers, elastic capacity pools, burstable credits.
P: air cushions, hydraulic presses.
Prompt: what rigid capacity could become elastic?

## 30. Flexible shells and thin films
Use flexible shells or thin films instead of solid structures; isolate with them.
S: sidecars, facades, strangler-fig wrappers around legacy systems, thin API layers, containers vs VMs.
P: membranes, protective coatings.
Prompt: could a thin wrapper do what a rebuild would do?

## 31. Porous materials
Make it porous or add porous elements; fill the pores with something useful.
S: sparse data structures, gaps in ordered keys for inserts, schedule slack, padding against false sharing, Bloom filters as admission holes.
P: filters, aerogels, porous catalysts.
Prompt: where would deliberate empty space make the element work better?

## 32. Colour changes
Change colour or transparency; add markers; use luminescent tracers.
S: trace IDs, taint tracking, canary labels, feature-flag tags on telemetry, red-black tree colouring.
P: pH indicators, fluorescent labelling.
Prompt: what marker would make the invisible state visible?

## 33. Homogeneity
Make interacting objects of the same material.
S: one runtime and serialisation end to end, homogeneous node pools, a single time base.
P: same-metal joints to avoid galvanic corrosion.
Prompt: which conversions or mismatches disappear if both sides are the same?

## 34. Discarding and recovering
Let spent parts go away or transform during operation; restore consumables in operation.
S: garbage collection, TTLs, log compaction, cache eviction and rebuild, regenerating derived state from the source of truth.
P: rocket stages, dissolvable stitches.
Prompt: which part could be thrown away and regenerated instead of maintained?

## 35. Parameter changes
Change physical state, concentration, flexibility, temperature.
S: row to columnar, compression, quantisation, consistency level, batch size, serialisation format.
P: freeze-drying, liquefying gases for transport.
Prompt: which representation change makes the conflict disappear?

## 36. Phase transitions
Use effects that occur at phase changes.
S: hybrid algorithms that switch at a threshold (introsort, Timsort runs), degraded or read-only modes, tier transitions.
P: heat pipes, phase-change thermal storage.
Prompt: is there a threshold where switching mode resolves both needs?

## 37. Thermal expansion
Use expansion and contraction under a stimulus; combine materials with different coefficients.
S: exponential backoff, congestion windows, elastic scaling, two thresholds reacting differently (hysteresis).
P: bimetal strips, shrink fitting.
Prompt: what should grow or shrink automatically with stress?

## 38. Strong oxidants
Intensify the environment to accelerate a process.
S: chaos experiments at raised fault rates, soak and stress tests, mutation testing, importance sampling of rare events.
P: oxygen-enriched combustion, accelerated life testing.
Prompt: what would surface the rare failure faster?

## 39. Inert atmosphere
Replace the environment with an inert one; add neutral parts.
S: sandboxes, hermetic builds, deterministic simulation testing, pure functions, read-only root filesystems.
P: argon shielding, gloveboxes.
Prompt: what environmental influence should be removed entirely?

## 40. Composite materials
Change from uniform to composite.
S: Timsort and introsort, hybrid logical clocks, polyglot persistence, model cascades, hybrid quantum-classical algorithms.
P: carbon-fibre composites, reinforced concrete.
Prompt: which two partial solutions, combined, cover each other's weaknesses?
