# Analogy catalogue

Retrieve by the **abstract structure** column, never by the domain. Each row names the source's
canonical method (cite it when you transfer) and the breakpoints that most often invalidate the
transfer. "Contested" marks analogies that are popular but scientifically disputed: use them as idea
generators only.

## A. Feedback, control, oscillation

| Abstract structure | Source | Canonical method | Transfers | Typical breakpoints |
|---|---|---|---|---|
| decisions on delayed signals ignore what is already in flight | supply chains: bullwhip (Forrester, 1961; Sterman's beer game, 1989) | count the supply line; share end-demand upstream | autoscaling, cache warming, connection pools | asymmetric add/remove costs; capacity not conserved |
| actuation or measurement dead time | process control | lower loop gain; Smith predictor (1957); feedforward | autoscalers, rate limiters, admission control | variable delay; saturation |
| on/off control chatters around a setpoint | thermostats | hysteresis deadband | alert fire/resolve thresholds, scale tolerance | plant inertia differs |
| set-point regulation with disturbance | engineering PID | P, I, D terms; anti-windup; Ziegler-Nichols tuning (1942) | queue-depth or latency-target controllers | integral windup under saturation; nonlinearity |
| periodic agents synchronise and spike | routing updates (Floyd and Jacobson, 1993) | add randomised jitter to periods | cron storms, retry storms, cache expiry stampedes | none common; jitter is cheap |
| regulation via many redundant loops | physiology: homeostasis | negative feedback, set points | self-healing reconcilers | biological redundancy far higher |

## B. Flow, transport, congestion

| Abstract structure | Source | Canonical method | Transfers | Typical breakpoints |
|---|---|---|---|---|
| fair share of one bottleneck among independent senders | TCP congestion control (Jacobson, 1988) | AIMD converges to fairness (Chiu and Jain, 1989) | client-side rate limiting, distributed backoff | non-cooperating senders; multiple bottlenecks |
| density waves and jams in a 1-D flow | traffic: LWR model (Lighthill and Whitham, 1955; Richards, 1956) | kinematic waves, shock speed | pipeline backpressure, conveyor systems | agents reroute; discrete packets at low density |
| adding capacity worsens selfish equilibrium | road networks: Braess's paradox (1968) | analyse user equilibrium vs system optimum | selfish load balancing, multipath routing | centrally routed systems are immune |
| arrivals wait for servers | telephony (Erlang, 1909-1917) | Erlang B/C; Little's law L = lambda W (1961) | thread pools, call centres, API capacity | heavy-tailed service times; non-Poisson bursts |
| limit work in progress to cut lead time | Toyota production system: kanban | WIP limits; pull not push | streaming backpressure, team boards | rework loops; shared resources |
| flow through a network with capacities | network flows (Ford and Fulkerson, 1956) | max-flow min-cut | bipartite matching, image segmentation, bandwidth planning | non-conserved flows |
| random walks on graphs | electrical networks (Doyle and Snell, 1984) | effective resistance; commute time = 2 m R_eff (Chandra et al., 1989) | graph sparsification by effective resistance (Spielman and Srivastava, 2008), node similarity | directed graphs |

## C. Spreading, contagion, percolation, cascades

| Abstract structure | Source | Canonical method | Transfers | Typical breakpoints |
|---|---|---|---|---|
| spread via random contacts | epidemiology: SIR (Kermack and McKendrick, 1927) | R0, herd threshold | gossip and anti-entropy replication (Demers et al., 1987), worm modelling | contacts not random (topology), adaptive defenders |
| connectivity appears abruptly at a threshold | percolation theory | critical threshold, cluster statistics | network robustness: scale-free networks resist random failure, fail under hub attack (Albert, Jeong and Barabasi, 2000) | lattice vs network topology |
| agents copy predecessors, ignoring private signals | economics: information cascades (Bikhchandani, Hirshleifer and Welch, 1992) | preserve independent signals; reveal private information | Delphi anonymity, LLM panel conformity, review herding | when private signals are genuinely weak |
| load shifts to neighbours after failure | power grids | N-1 security criterion; load shedding | retry amplification in microservices; N+1 capacity | software retries add load rather than redistribute |
| layered defences with holes | accident theory: Swiss cheese model (Reason, 1990) | independent layers; remove correlated holes | defence in depth, layered tests | layers sharing a common cause |

## D. Search and optimisation from nature

| Abstract structure | Source | Canonical method | Transfers | Typical breakpoints |
|---|---|---|---|---|
| escape local optima by controlled randomness | metallurgy: annealing | simulated annealing (Kirkpatrick, Gelatt and Vecchi, 1983) | VLSI placement, scheduling | cooling schedule matters; slow on smooth problems |
| variation plus selection | evolution | genetic algorithms (Holland, 1975); evolution strategies; CMA-ES | design search, hyperparameters | evolution has no designer's objective; fitness evaluation cost |
| stigmergic path reinforcement | ant foraging | ant colony optimisation (Dorigo, 1992) | routing (AntNet, Di Caro and Dorigo, 1998), TSP | dynamic graphs need evaporation tuning |
| social information sharing in a swarm | flocking | particle swarm optimisation (Kennedy and Eberhart, 1995) | continuous optimisation | premature convergence |
| self vs non-self discrimination | immune system | negative selection (Forrest et al., 1994) | intrusion and anomaly detection | "self" drifts; high false positives |
| when to leave a depleting patch | foraging theory: marginal value theorem (Charnov, 1976) | leave when local gain rate falls to the average | information foraging (Pirolli and Card, 1999): when to stop reading a source | patches not independent |
| network that balances cost and robustness | slime mould (Physarum) | adaptive tube reinforcement model | transport network design (Tero et al., 2010) | slow; local optima |

## E. Statistical physics and computation

| Abstract structure | Source | Canonical method | Transfers | Typical breakpoints |
|---|---|---|---|---|
| coupled binary units minimising energy | Ising and spin-glass models | Boltzmann distribution, mean-field | Hopfield networks (1982), Boltzmann machines (Ackley, Hinton and Sejnowski, 1985) | learning rules have no physical counterpart |
| approximate an intractable distribution | free-energy minimisation | variational methods, mean field | variational inference, ELBO | mean-field independence too strong |
| reverse a noising process | non-equilibrium thermodynamics, diffusion | Langevin dynamics, score matching | diffusion generative models (Sohl-Dickstein et al., 2015; Ho et al., 2020) | discretisation choices dominate in practice |
| estimate integrals by random sampling | neutron transport (Metropolis and Ulam, 1949) | Monte Carlo; Metropolis algorithm (1953) | MCMC in statistics; path tracing for the rendering equation (Kajiya, 1986) | variance; correlated samples |
| concentrate samples where the integrand matters | physics: importance sampling | proposal distributions, MIS | rendering, rare-event simulation, off-policy RL | heavy-tailed weights |
| hardness peaks at a phase transition | random k-SAT (Mitchell, Selman and Levesque, 1992) | clause/variable ratio near 4.26 for 3-SAT | generating hard benchmark instances | structured industrial instances differ |
| erasing information costs energy | Landauer (1961) | kT ln 2 per bit erased | reversible computing limits | far below practical energy scales today |
| coarse-graining across scales | renormalisation group | iterative coarse-graining | deep learning as RG (Mehta and Schwab, 2014): contested | analogy formal only in special cases |

## F. Signals, estimation, coding

| Abstract structure | Source | Canonical method | Transfers | Typical breakpoints |
|---|---|---|---|---|
| estimate hidden state from noisy measurements | navigation (Kalman, 1960) | Kalman filter; EKF/UKF | SLAM, econometrics, sensor fusion, latency smoothing | non-Gaussian noise, strong nonlinearity |
| sparse signal from few measurements | compressed sensing (Candes, Romberg and Tao, 2006; Donoho, 2006) | L1 recovery, incoherent sampling | MRI acceleration (Lustig, Donoho and Pauly, 2007), single-pixel cameras | signal not sparse in any basis |
| tolerate random loss with redundancy | coding theory (Hamming, 1950; Reed and Solomon, 1960) | erasure and error-correcting codes | RAID, erasure-coded object storage, QR codes | correlated loss defeats independence assumptions |
| detect a known waveform in noise | radar | matched filtering | gravitational-wave searches (LIGO), template matching | unknown waveform |
| quantise without systematic error | signal processing | dithering | image and audio quantisation; stochastic rounding in low-precision training | adds noise |
| frequency-domain analysis | Fourier analysis | spectral decomposition | graph signal processing, spectral clustering | irregular domains |

## G. Economics, markets, mechanism design

| Abstract structure | Source | Canonical method | Transfers | Typical breakpoints |
|---|---|---|---|---|
| allocate a scarce item truthfully | auctions (Vickrey, 1961) | second-price sealed bid | ad auctions (with GSP variants), spot pricing, cluster allocation | repeated games, collusion |
| two-sided matching with preferences | economics (Gale and Shapley, 1962) | deferred acceptance | residency matching (Roth and Peranson, 1999), school choice, kidney exchange | couples and complementarities |
| reduce risk by combining uncorrelated bets | portfolio theory (Markowitz, 1952) | diversification | algorithm portfolios (Huberman, Lukose and Hogg, 1997), hedged requests (Dean and Barroso, 2013), multi-region | correlation spikes in crises and outages |
| pool independent risks | insurance | law of large numbers | statistical multiplexing, overcommit | correlated events (regional outage, systemic crisis) |
| shared resource overused | commons (Hardin, 1968; Ostrom, 1990) | quotas, local governance rules | CI runners, noisy neighbours, shared clusters | enforcement cost |
| metric becomes a target | Goodhart's law (1975), principal-agent theory | multiple metrics, audits | benchmark overfitting, reward hacking, OKR gaming | none; it transfers too well |
| value of deferring irreversible choices | real options (finance) | option pricing intuition: volatility raises the value of waiting | architecture decisions, staged rollouts | options are not free to hold |
| invariants by balanced entries | double-entry bookkeeping | debits = credits | ledgers, event sourcing, reconciliation jobs | none common |

## H. Safety and operations

| Abstract structure | Source | Canonical method | Transfers | Typical breakpoints |
|---|---|---|---|---|
| complex procedure, rare fatal omissions | aviation checklists | read-do and do-confirm lists | surgical safety checklist (Haynes et al., 2009), deploy runbooks | checklist fatigue if too long |
| team performance under stress | crew resource management (aviation) | explicit roles, challenge-and-response | incident response, blameless postmortems | flatter hierarchies differ |
| multi-team emergency coordination | Incident Command System (firefighting) | incident commander, ops, comms, planning roles | SRE incident management | small teams merge roles |
| safe state on loss of signal | railways: dead-man switch; air brakes engage on pressure loss | fail-safe defaults | leases and lock expiry, watchdogs, fail-closed security | fail-safe vs fail-secure conflict |
| contain a failure locally | ships' bulkheads, electrical circuit breakers | compartmentalise; trip on overload | bulkhead and circuit-breaker patterns (Nygard, 2007) | shared dependencies cross compartments |
| detect process drift statistically | statistical process control (Shewhart, 1920s) | control charts | SLO burn-rate alerting, anomaly detection | autocorrelated data inflate false alarms |
| ageing degrades systems over time | reliability: preventive maintenance | scheduled replacement | software rejuvenation by periodic restart (Huang et al., 1995) | hides leaks instead of fixing them |

## I. Biology and design

| Abstract structure | Source | Canonical method | Transfers | Typical breakpoints |
|---|---|---|---|---|
| pattern from local activation and inhibition | morphogenesis (Turing, 1952) | reaction-diffusion | procedural textures (Turk, 1991; Witkin and Kass, 1991) | parameter sensitivity |
| leaderless coordinated motion | flocks | boids rules (Reynolds, 1987) | swarm robotics, crowd simulation | communication limits |
| self-cleaning by surface structure | lotus leaf (Barthlott and Neinhuis, 1997) | micro/nano roughness plus hydrophobicity | coatings, textiles | abrasion destroys structure |
| hook-and-loop attachment | burdock burrs | Velcro (de Mestral) | fasteners | wear |
| reduce pressure wave at a medium transition | kingfisher beak | gradual cross-section change | train nose design for tunnel entry | widely reported; validate with CFD rather than the story |
| passive ventilation | termite mounds | stack effect, thermal mass | passively cooled buildings | later research questioned the simple chimney account of mounds: the source mechanism itself was uncertain |

## J. Mathematics and computing structure

| Abstract structure | Source | Canonical method | Transfers | Typical breakpoints |
|---|---|---|---|---|
| shortest arrival time through varying media | optics: Fermat's principle; eikonal equation | fast marching (Sethian, 1996), a continuous Dijkstra | path planning, geodesic distance on meshes | anisotropic media need other solvers |
| causality without a global clock | special relativity (cited by Lamport, 1978) | happened-before; logical clocks | vector clocks (Fidge, Mattern, 1988), causal consistency | none; it is the motivating analogy |
| rent or buy under uncertainty | ski rental (competitive analysis) | buy after renting cost equals buying cost: 2-competitive | spin-then-block locks (Karlin et al.), TCP keepalive, cache admission | known distributions allow better policies |
| align two sequences with edits | biology: Needleman-Wunsch (1970) | dynamic programming alignment | diff, spell correction, speech alignment | very long sequences need heuristics |
| seed-and-extend similarity search | bioinformatics: BLAST | k-mer seeds, extension, statistics | code clone detection, plagiarism detection | seed size vs sensitivity |
| reconstruct descent with modification | phylogenetics | parsimony, likelihood trees | manuscript stemmatics, malware lineage, language families | horizontal transfer breaks trees |
| connected components under incremental joins | percolation simulation | union-find (Newman and Ziff, 2000) | network reliability, clustering | deletions are hard |
| optimal stopping with one pass | secretary problem | observe ~1/e, then take the next best | hiring heuristics, online selection | recall allowed; known distributions |

## How to add an entry

Add a row only with: a structure stated without domain nouns, a citable canonical method, at least
one transfer that actually happened (cite it), and at least one known breakpoint. Mark contested
analogies explicitly.
