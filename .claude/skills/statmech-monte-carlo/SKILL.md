---
name: statmech-monte-carlo
description: "Statistical mechanics and Monte Carlo practice: ensembles, fluctuation formulas and exact partition-function checks, Metropolis-Hastings and heat-bath updates, Wolff/Swendsen-Wang clusters, parallel tempering and Wang-Landau, autocorrelation/blocking/jackknife errors, and finite-size scaling. Load when sampling a physical system or judging MC error bars."
when_to_use: "Writing or reviewing a Metropolis, heat-bath, cluster, parallel-tempering, Wang-Landau or umbrella-sampling code; quoting an error bar from correlated samples; estimating tau_int, blocking plateaus, R-hat or ESS; locating a transition with Binder cumulants or finite-size scaling; testing a sampler against Onsager or exact enumeration; seeding parallel RNG streams; deciding whether a quantum MC problem has a sign problem."
---

# Statistical mechanics and Monte Carlo

Monte Carlo results fail in five repeatable ways: an update that breaks balance or ergodicity,
error bars that ignore autocorrelation, correlated random streams, equilibration judged by
hope, and finite-size rounding read as a phase transition. Every sampler here is checked
against an exact result before it is trusted. Numbers marked "computed" come from the
benchmark in [Ising benchmark script and output](references/ising-benchmark.md) (NumPy + Numba,
October 2026).

## 1. Ensembles and fluctuation formulas

| Ensemble | Fixed | Weight | Potential | Fluctuation identities |
|---|---|---|---|---|
| Microcanonical | N, V, E | uniform on the shell | S = k_B ln Ω | 1/T = ∂S/∂E |
| Canonical | N, V, T | e^(−βE)/Z | F = −k_BT ln Z | C_V = Var(E)/(k_BT²); χ = βN·Var(m) |
| Grand canonical | μ, V, T | e^(−β(E − μN))/Ξ | Ω_G = −k_BT ln Ξ = −pV | Var(N) = ⟨N⟩ρk_BTκ_T |
| Isothermal-isobaric | N, p, T | e^(−β(E + pV))/Δ | G = −k_BT ln Δ | Var(V) = k_BT⟨V⟩κ_T; Var(H) = k_BT²C_p |

- Finite magnets have ⟨m⟩ = 0 by symmetry: use χ = βN(⟨m²⟩ − ⟨|m|⟩²) below T_c and βN⟨m²⟩ above.
- Equipartition (k_BT/2 per quadratic term) fails when k_BT ≪ ħω: Einstein solid
  C = 3Nk_B x²eˣ/(eˣ − 1)² with x = ħω/k_BT; Debye C = (12π⁴/5)Nk_B(T/Θ_D)³ for T ≪ Θ_D.
- Occupancies: Bose n = 1/(e^(β(ε−μ)) − 1), Fermi n = 1/(e^(β(ε−μ)) + 1); classical when
  nλ³ ≪ 1 with λ = h/sqrt(2πmk_BT). Ideal gas: pV = Nk_BT, μ = k_BT ln(nλ³), E = (3/2)Nk_BT.

## 2. Exact checks

- 1D Ising, periodic, zero field: Z = (2cosh βJ)^N + (2sinh βJ)^N; f = −k_BT ln(2cosh βJ) as
  N → ∞; u = −J tanh βJ; no transition at T > 0.
- 2D Ising, square lattice: T_c = 2J/(k_B ln(1 + √2)) = 2.269185 J/k_B; spontaneous
  magnetisation M = (1 − sinh⁻⁴(2βJ))^(1/8) for T < T_c; u(T_c) = −√2 J per spin; exponents
  β = 1/8, γ = 7/4, ν = 1, α = 0 (log); Binder crossing value U* ≈ 0.6107 (periodic square).
- Einstein and Debye solids, ideal gas (section 1).
- Unit test: enumerate all 2¹⁶ states of a periodic 4×4 lattice. Computed at T_c:
  e = −1.56562, ⟨|m|⟩ = 0.84386, c_v = 0.78327, U₄ = 0.61720. The checkerboard Metropolis code
  below gives e = −1.56306 ± 0.00248 (1e5 sweeps) and Wolff gives −1.56344 ± 0.00171: both within
  1.3σ.

```python
def exact_small(L, T):                       # all 2^(L*L) states; L = 4 takes ~0.1 s
    N = L*L; idx = np.arange(2**N, dtype=np.int64)
    s = ((((idx[:, None] >> np.arange(N)) & 1)*2 - 1).astype(np.int8)).reshape(-1, L, L)
    E = -(s*np.roll(s, 1, 1) + s*np.roll(s, 1, 2)).sum((1, 2)).astype(float)
    M = s.sum((1, 2)).astype(float); w = np.exp(-(E - E.min())/T); Z = w.sum()
    avg = lambda a: (w*a).sum()/Z; m2, m4 = avg(M**2)/N**2, avg(M**4)/N**4
    return avg(E)/N, avg(abs(M))/N, (avg(E**2) - avg(E)**2)/T**2/N, 1 - m4/(3*m2**2)
```

## 3. Metropolis-Hastings procedure

1. Propose x′ ~ q(x′|x).
2. Accept with A = min(1, e^(−βΔE)·q(x|x′)/q(x′|x)); the q ratio corrects asymmetric proposals.
3. On rejection the old state is counted again: it is a sample.
4. Tune random-walk steps to ≈ 0.44 acceptance in 1D and ≈ 0.234 in high dimension
   (Roberts-Gelman-Gilks). Acceptance near 1 or 0 means the step is far too small or too large.
- Sequential (typewriter or checkerboard) sweeps violate detailed balance per sweep, but each
  single-site update satisfies it, so the sweep keeps the Boltzmann distribution invariant
  (global balance): correct.
- Heat bath (rejection-free) for Ising: P(s_i = +1) = 1/(1 + e^(−2βh_i)) with
  h_i = JΣ_j s_j + H. Same dynamic exponent as Metropolis.
- Ergodicity: single-site moves freeze at low T and cannot cross barriers; add cluster, swap or
  tempering moves.

## 4. RNG discipline

```python
ss = np.random.SeedSequence(20261019)                      # store ss.entropy with the results
rngs = [np.random.default_rng(s) for s in ss.spawn(n_workers)]   # PCG64, independent streams
rng_gpu = np.random.Generator(np.random.Philox(key=12345))       # counter-based alternative
```

Never reseed workers with nearby integers (seed + rank) or reuse one seed per task. A NumPy
`Generator` can be passed into `@numba.njit` functions (the benchmark does this). Record the
entropy, spawn keys, code version and parameters next to every result file (section 9).

## 5. Cluster updates

- Wolff: pick a random seed spin; add aligned neighbours with p_add = 1 − e^(−2βJ); flip the
  whole cluster; no rejection. The mean cluster size is an improved estimator of N⟨m²⟩.
- Swendsen-Wang: activate every aligned bond with p_add, find all clusters (union-find), flip
  each with probability 1/2.
- Critical slowing down in the 2D Ising model: local Metropolis or heat bath z ≈ 2.17,
  Swendsen-Wang z ≈ 0.2–0.3, Wolff z ≲ 0.3 (in sweeps). Computed at L = 64: Metropolis needs
  τ_int ≈ 335 sweeps, Wolff 3.4.
- Clusters fail for frustrated systems (spin glasses) and need a ghost spin in a field; use
  parallel tempering there.

## 6. Rough landscapes

- Parallel tempering: geometric ladder T_i = T_min(T_max/T_min)^(i/(n−1)); swap neighbours with
  A = min(1, exp[(β_i − β_j)(E_i − E_j)]); aim for 20–30 % swap acceptance. Energy-histogram
  overlap shrinks like 1/sqrt(C_V), so replicas grow like sqrt(N). Track replica round trips
  between T_min and T_max; few round trips mean the ladder fails even at good acceptance.
- Wang-Landau for the density of states: accept E → E′ with min(1, g(E)/g(E′)); after every move
  ln g(E) += ln f and H(E) += 1; when min H ≥ 0.8·mean H (80 % flatness) reset H and halve ln f
  (f → sqrt f), starting from ln f = 1, until ln f < 1e-8. The 1/t variant (set ln f = 1/t once
  ln f < 1/t, t in sweeps) removes the saturation error. Canonical averages then follow by
  reweighting with g(E).
- Umbrella sampling: windows with bias ½k(ξ − ξ_i)² that overlap in ξ; unbias with WHAM or MBAR.
  pymbar 4: `mbar = MBAR(u_kn, N_k)`, `res = mbar.compute_free_energy_differences()`, read
  `res["Delta_f"]` and `res["dDelta_f"]`; check window overlap before trusting the result.

## 7. Error analysis

```python
def tau_int(x, c=5.0):                       # Sokal window: smallest M with M >= c*tau(M)
    x = np.asarray(x, float) - np.mean(x); n = len(x)
    f = np.fft.rfft(x, 2*n); acf = np.fft.irfft(f*np.conj(f))[:n]; acf /= acf[0]
    taus = 1 + 2*np.cumsum(acf[1:]); Ms = np.arange(1, n); ok = Ms >= c*taus
    M = int(Ms[np.argmax(ok)]) if ok.any() else n - 1
    return taus[M-1], taus[M-1]*np.sqrt(2*(2*M + 1)/n)      # tau_int and its error
def blocking_error(x):                       # Flyvbjerg-Petersen: read the plateau
    x = np.asarray(x, float); errs = []
    while len(x) >= 32:
        errs.append(x.std(ddof=1)/np.sqrt(len(x)))
        x = 0.5*(x[:len(x)//2*2:2] + x[1:len(x)//2*2:2])
    return errs
def jackknife(blocks, estimator):            # blocks: (nb, ...) block means; estimator: nonlinear map
    nb = len(blocks); full = estimator(blocks.mean(0))
    jk = np.array([estimator((blocks.sum(0) - b)/(nb - 1)) for b in blocks])
    return full, np.sqrt((nb - 1)/nb*((jk - jk.mean(0))**2).sum(0))
```

- τ_int = 1 + 2Σρ(t) with the Sokal window M ≥ 5τ; N_eff = N/τ_int; σ_mean = σ·sqrt(τ_int/N).
- Blocking must reach a plateau; no plateau means the run is too short to quote any error.
  Computed (4×4): the naive error 0.00161 rises to the plateau 0.00248.
- Burn-in: start from ordered and random configurations and discard until their traces agree;
  never a fixed fraction.
- Nonlinear estimators (U₄, χ, ratios, crossing temperatures): jackknife over ≥ 20 blocks
  longer than τ_int.
- Several chains (parameter inference): R̂ < 1.01 and bulk and tail ESS > 400 (ArviZ
  `az.rhat`, `az.ess` on an array of shape (chain, draw) via `az.convert_to_dataset`).
- The slowest observable sets the run length: at L = 64, τ_int(E) = 120 but τ_int(|m|) = 335.

## 8. Finite-size scaling

- Binder cumulant U₄ = 1 − ⟨m⁴⟩/(3⟨m²⟩²) → 2/3 when ordered and → 0 when disordered (Gaussian);
  curves for L and 2L cross near T_c with corrections ~L^(−ω−1/ν).
- χ_max ∝ L^(γ/ν) (7/4 in 2D Ising); ⟨|m|⟩(T_c) ∝ L^(−β/ν); the pseudo-critical shift
  T_c(L) − T_c ∝ L^(−1/ν); C_V peaks grow as L^(α/ν) (logarithmically in 2D Ising).
- Data collapse: plot L^(−γ/ν)χ against L^(1/ν)(T − T_c)/T_c for ≥ 3 sizes, fitting T_c, ν and
  γ/ν with a correction term (1 + bL^(−ω)).
- First-order transitions show double-peaked energy histograms and scale with volume L^d.
- Never quote critical exponents from a single L; rounding and shifting of peaks ∝ L^(−1/ν).

## 9. Code: checkerboard Metropolis and Wolff

```python
import numpy as np, numba as nb, math
def metropolis_sweeps(s, beta, nsweeps, rng):   # s: (L, L) int8 of +-1, L even; returns E, M per sweep
    L = s.shape[0]; par = (np.add.outer(np.arange(L), np.arange(L)) % 2).astype(bool)
    acc = np.exp(-beta*np.arange(9))            # acceptance for dE = 0..8 (J = 1)
    E = np.empty(nsweeps); M = np.empty(nsweeps)
    for t in range(nsweeps):
        for mask in (par, ~par):                # one sublattice at a time: neighbours are fixed
            nbr = np.roll(s, 1, 0) + np.roll(s, -1, 0) + np.roll(s, 1, 1) + np.roll(s, -1, 1)
            dE = 2*s*nbr
            s[mask & (rng.random(s.shape) < acc[np.maximum(dE, 0)])] *= -1
        M[t] = s.sum(); E[t] = -(s*(np.roll(s, 1, 0) + np.roll(s, 1, 1))).sum()
    return E, M

@nb.njit
def wolff_run(s, beta, nclusters, rng, stack):  # stack: np.empty((L*L, 2), np.int64)
    L = s.shape[0]; p = 1.0 - math.exp(-2.0*beta)
    M = np.empty(nclusters); C = np.empty(nclusters)
    for t in range(nclusters):
        i = int(rng.random()*L); j = int(rng.random()*L); s0 = s[i, j]; s[i, j] = -s0
        stack[0, 0] = i; stack[0, 1] = j; sp = 1; size = 1
        while sp > 0:                           # explicit stack: no recursion limit
            sp -= 1; ci = stack[sp, 0]; cj = stack[sp, 1]
            for d in range(4):
                ni = (ci + (d == 0) - (d == 1)) % L; nj = (cj + (d == 2) - (d == 3)) % L
                if s[ni, nj] == s0 and rng.random() < p:
                    s[ni, nj] = -s0             # flip on push: each site enters once
                    stack[sp, 0] = ni; stack[sp, 1] = nj; sp += 1; size += 1
        M[t] = s.sum(); C[t] = size
    return M, C
```

Save the seeds and configuration next to the numbers:

```python
import json, csv, platform                     # child = the ss.spawn(...) entry that seeded this run
meta = {"L": L, "T": T, "sweeps": nsweeps, "seed_entropy": ss.entropy, "spawn_key": list(child.spawn_key),
        "numpy": np.__version__, "numba": nb.__version__, "python": platform.python_version()}
json.dump(meta, open(f"ising_L{L}_T{T}.json", "w"), indent=1)
with open(f"ising_L{L}_T{T}.csv", "w", newline="") as fh:
    csv.writer(fh).writerows([("E", "M"), *zip(E, M)])
```

## 10. Quantum Monte Carlo pointers

- Path-integral MC (bosons, helium; worm algorithm), stochastic series expansion with loop
  updates (unfrustrated spin models), variational MC (NetKet for neural-network wavefunctions),
  diffusion MC (fixed-node for fermions), auxiliary-field QMC.
- Sign problem: with negative weights the average sign ⟨s⟩ ~ e^(−βNΔf) decays exponentially
  and errors grow as 1/⟨s⟩. Report ⟨s⟩ with every result and treat a vanishing sign (fermions
  away from special fillings, frustrated magnets) as a hard stop to report, not a tuning issue.
  Sign-free cases include the half-filled Hubbard model on bipartite lattices (DQMC) and
  unfrustrated Heisenberg models (SSE).

## 11. Worked example: 2D Ising at L = 16, 32, 64 (computed)

Wolff runs of 2e5 clusters per (L, T) after 5000 equilibration clusters from random starts;
Binder errors by jackknife over 40 blocks.

| T | 2.25 | 2.26 | 2.27 | 2.28 | 2.29 |
|---|---|---|---|---|---|
| U₄, L = 16 | 0.6209 | 0.6169 | 0.6119 | 0.6056 | 0.5995 |
| U₄, L = 32 | 0.6287 | 0.6199 | 0.6104 | 0.5980 | 0.5848 |
| U₄, L = 64 | 0.6398 | 0.6272 | 0.6100 | 0.5830 | 0.5496 |

Crossings: 16/32 at T = 2.2666 ± 0.0012 and 32/64 at T = 2.2695 ± 0.0011, so T_c = 2.2695(11)
from the largest pair against Onsager's 2.269185 (0.3σ), with U ≈ 0.610 at the crossing
(U* = 0.6107). The drift between pairs is the correction to scaling: quote the largest pair or
extrapolate.

| L | Metropolis τ_int(\|m\|) at T_c | Metropolis τ_int(E) | Wolff τ_int(\|m\|) at T = 2.27 | Wolff ⟨C⟩/N |
|---|---|---|---|---|
| 16 | 21.1 ± 0.6 | 11.9 ± 0.3 | 2.33 sweeps | 0.547 |
| 32 | 81.4 ± 3.3 | 37.3 ± 1.0 | 2.80 sweeps | 0.457 |
| 64 | 335 ± 19 | 120 ± 4 | 3.35 sweeps | 0.383 |

Metropolis τ grows with effective exponents 1.95 (16 → 32) and 2.04 (32 → 64), approaching the
asymptotic z ≈ 2.17 from below (corrections to scaling at small L); Wolff's effective z is ≈ 0.26
and its cluster fraction falls as L^(−1/4) = L^(γ/ν − 2). At L = 64 one Wolff sweep-equivalent
buys ~100× more independent samples than a Metropolis sweep.

## 12. Pitfalls

- Naive σ/√N on correlated samples: at L = 64 near T_c it understates the |m| error by
  sqrt(τ_int) ≈ 18×.
- Correlated RNG streams (seed + rank, one seed reused across tasks).
- Equilibrating only from an ordered start: below T_c it looks equilibrated immediately; compare
  ordered and random starts.
- Non-ergodic low-T single-spin updates, or cluster moves applied with a field or frustration.
- Finite-size rounding of a smooth crossover read as a transition; exponents from one size.
- Reporting U₄ crossings or χ peaks without jackknife errors, or computing ratios of averages
  from averages of ratios.

Related: `probability-distributions-limits`, `statistical-inference-bayesian`, `molecular-dynamics-setup`, `physics-ode-integrators`, `uncertainty-propagation-fitting`, `quantum-mechanics-methods`, hub `physics-toolkit`
