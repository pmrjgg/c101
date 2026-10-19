# Cross-discipline false friends

Terms that mean different, often incompatible, things in different fields. When one of these appears
in two or more expert reports, add a glossary row before comparing claims (SKILL.md section 3).

## Terms

| Term | Meanings by field | Typical synthesis bug |
|---|---|---|
| accuracy | ML: fraction correct. Metrology: closeness to true value (vs precision = repeatability). Numerics: error vs exact solution. Simulation: drift of a conserved quantity | "99% accurate" classifier compared with "1e-6 accurate" solver |
| precision | ML: TP/(TP+FP). Numerics: mantissa bits (fp32 ~7 decimal digits, fp64 ~16). Metrology: repeatability | ML precision target treated as numeric tolerance |
| recall / sensitivity | ML recall = medicine sensitivity = true-positive rate | duplicate requirements counted twice |
| consistency | CAP: linearizability. ACID: invariants preserved by transactions. Numerics: local truncation error vanishes as h goes to 0 (consistency + stability => convergence, Lax equivalence). Statistics: estimator converges in probability | "consistent" database vs "consistent" scheme |
| stable / stability | Sorting: equal keys keep order. Numerics: errors do not grow. Control: bounded output (BIBO, Lyapunov). API: no breaking changes | "stable algorithm" accepted by the wrong owner |
| order | Complexity O(n). Method order p (error proportional to h^p). Memory order (acquire/release). Order statistics | O(n^2) vs second-order accurate |
| convergence | Optimisation: objective reaches minimum. Numerics: refinement study. Probability: in distribution / probability / almost surely. Delphi: opinions approach each other | "converged" training run vs converged mesh |
| error | Numerics: truncation vs rounding. Statistics: standard error vs residual. Software: exception. ML: loss | error budgets mixed across meanings |
| bias | Statistics: E[estimator] minus truth. ML: additive term; also fairness. Cognitive bias. Electronics: bias voltage | "remove bias" means different interventions |
| variance | Statistics. ML bias-variance trade-off. Finance: volatility squared | |
| kernel | OS kernel. GPU compute kernel. ML kernel function (RKHS). Convolution filter. Linear-algebra null space. Kernel density estimation | performance claim about "the kernel" routed to the wrong expert |
| model | ML trained weights. Physics equations. Formal methods state machine. MVC layer. Data schema | |
| state | Quantum state vector / density matrix. Application state. State machine state | |
| parameter | ML learned weights vs hyperparameters. Statistics population quantity. Function argument. Physical constant | "tune the parameters" ambiguous between training and config |
| sample | Statistics: a set of observations. DSP: one value. ML: one example. Monte Carlo: one draw | "1000 samples" means 1000 sets vs 1000 points |
| normalisation | DB normal forms. Feature scaling / batch norm. Probabilities summing to 1. Unicode normalisation | |
| regression | Statistics model. Software: reintroduced bug | |
| resolution | Display pixels. Metrology smallest increment. DNS / dependency / conflict resolution | |
| thread | OS thread. GPU thread (one SIMT lane). Conversation | "10k threads" cheap on GPU, expensive on OS |
| warp / wavefront | NVIDIA warp = 32 lanes; AMD wavefront 64 (or 32 on RDNA) | occupancy math off by 2x |
| token | LLM token. Auth token. Lexer token. Blockchain token | |
| entropy | Thermodynamics (J/K). Shannon (bits). OS randomness pool. Decision-tree impurity | |
| temperature | Physics. LLM sampling. Simulated-annealing control parameter | |
| energy | Physics. Energy-based models. Objective function in optimisation | conservation reasoning applied to an objective |
| field | Physics field. DB column. Algebraic field. Struct member | |
| ring | Algebra. Consistent-hashing ring. Ring buffer. CPU protection ring | |
| vector | Mathematics. Dynamic array (std::vector). Attack vector. Embedding | |
| tensor | Multilinear map with a transformation law (physics). N-d array (ML) | physics expert expects covariance rules ML code does not obey |
| dimension | Physical dimension (L, M, T). Array axis. Vector-space dimension. Warehouse dimension | |
| unit | Physical unit. Unit test. systemd unit | |
| transaction | DB ACID. Payment. Blockchain | |
| commit | Git. DB commit. Consensus: entry committed by a quorum | "committed" in Raft is not "fsynced on all replicas" |
| replication | DB replicas. Science: independent repetition of an experiment | "replicated result" |
| validation / verification | ML validation set. Input validation. Systems engineering: validation = right product, verification = product built right | |
| significance | p-value. Effect size (practical significance). Significant figures | "significant improvement" with tiny effect |
| confidence | Frequentist confidence interval. Bayesian credible interval. Agent self-confidence | |
| probability / likelihood | Statistics: P(data given params) as function of params is a likelihood, not a probability | |
| utilisation | Queueing rho = lambda/mu. OS sampled CPU busy % | |
| load | Unix load average (runnable + uninterruptible tasks). Requests per second. Electrical load | |
| capacity | Shannon capacity. Storage size. Max throughput at SLO | |
| availability | Fraction of time serving. CAP: every non-failing node answers | 99.99% availability vs CAP-available |
| partition | Network partition. Table partition. Set partition. Disk partition | |
| atomic | DB all-or-nothing. CPU atomic instruction. Physics | |
| isolation | DB isolation level. Process / tenant isolation. Electrical isolation | |
| idempotent | Mathematics f(f(x)) = f(x). HTTP: repeated request, same effect | |
| linear | Linear algebra. Linearizability. Linear time. Linear types | |
| real-time | Hard deadline guarantees vs "live / fast" | "real-time" requirement silently weakened |
| deterministic | Same input same output. Deterministic simulation testing. DFA | |
| gate | Logic gate. Quantum gate. Release / quality gate | |
| noise | Signal noise. Quantum channel noise. Noisy neighbour. Label noise | |
| fidelity | Quantum state fidelity. Mock/test fidelity. Visual fidelity | |
| coherence | Cache coherence. Quantum coherence time. Optical coherence | |
| shot | Quantum circuit repetition. Few-shot prompt example | |
| epoch | ML pass over the data. Unix epoch. Consensus term | |
| pipeline | CPU pipeline. CI pipeline. ML pipeline. Graphics pipeline | |
| frame | Video frame. Stack frame. L2 frame. Reference frame | sim step vs render frame |
| render | Graphics. Server-side HTML rendering | |
| velocity | Physics. Agile story points per sprint | |

## Units and scale traps

| Trap | Rule |
|---|---|
| bits vs bytes | network in bit/s, storage and memory in B/s; 1 Gbit/s = 125 MB/s |
| KB vs KiB | 1 KB = 1000 B, 1 KiB = 1024 B; disks use decimal, RAM binary |
| percentiles | not averageable: the mean of per-host p99s is not the fleet p99; merge histograms or sketches |
| percent vs percentage points | 10% to 12% is +2 pp, +20% relative |
| per-core / per-socket / per-node / cluster | normalise before comparing throughput |
| mean vs median | skewed latency, cost and effort data: compare medians or full distributions |
| dB | power: 10 log10; amplitude: 20 log10 |
| log | natural vs base 2 vs base 10; entropy in bits uses log2 |
| float width | fp32 about 7 significant digits, fp64 about 16, bf16 about 3 |
| rates | per second vs per minute vs per day; QPS vs RPS vs TPS |
| time base | wall clock vs CPU time vs simulated time vs GPU time |
| population | all users vs DAU vs concurrent users vs sessions |
| billion | 1e9 (short scale); some non-English sources use long scale |
| currency and date | nominal vs real money; time-zone and fiscal-year boundaries |

## Procedure for an unclear term

1. Quote each usage with `file:line`.
2. Ask: what is the unit, the aggregation (per what), the population, and the measurement boundary?
3. If a report does not say, the owning expert gets a one-line clarification brief (sent to that
   expert's agent type; no model/effort on the call) or you mark the claim `unverified`.
4. Pick canonical terms that carry the distinction in the name (`t_e2e_p99_ms`, `energy_drift_rel`).
