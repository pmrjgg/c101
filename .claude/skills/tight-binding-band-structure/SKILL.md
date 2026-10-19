---
name: tight-binding-band-structure
description: "Tight-binding models and band structures, covering the Bloch theorem, hopping Hamiltonians in k-space and their gauge conventions, high-symmetry k-paths, 1D chain, SSH and graphene examples, density of states, Zak phase and Fukui-Hatsugai Chern numbers, ribbon edge states, Wannier interpolation and the PythTB 2, Kwant and pybinding tools. Load when building or interpreting band structures or topological lattice models."
when_to_use: "Writing H(k) from a hopping list; plotting bands along Gamma-K-M or another high-symmetry path; graphene Dirac points or Fermi velocity; SSH winding number, Zak phase or end states; the Chern number of a lattice model; ribbon, slab or edge-state spectra; a DOS from a k-grid; porting PythTB 1.x code (tb_model, wf_array) to PythTB 2; Kwant, pybinding, Wannier90 or TBmodels work; eigenvectors or Berry phases that disagree between codes."
---

# Tight-binding band structures

Tight-binding bugs are bookkeeping bugs: a hopping counted twice, fractional k dotted with a Cartesian R,
bands plotted against point index instead of |Δk|, and a Berry phase computed in one gauge and read in
another. Eigenvalues forgive most of these; eigenvectors, Berry phases and edge states do not. The numbers
below were recomputed with NumPy and PythTB 2.0.0 in October 2026.

## 1. Bloch theorem and H(k)

- ψ_nk(r + R) = e^{ik·R}ψ_nk(r), so ψ_nk = e^{ik·r}u_nk(r) with u periodic. k is defined modulo reciprocal
  vectors G with b_i·a_j = 2πδ_ij; with lattice vectors as the rows of A, the rows of B = 2π(A⁻¹)ᵀ are the b_i.
- Bloch sum of orbital α at position τ_α: |k, α⟩ = N^{−1/2}Σ_R e^{ik·(R + τ_α)}|R, α⟩.
- With hoppings t_αβ(R) = ⟨0, α|H|R, β⟩: H_αβ(k) = Σ_R t_αβ(R)e^{ik·(R + τ_β − τ_α)}; solve H(k)c = E(k)c at
  each k. N_orb orbitals per cell give N_orb bands (twice that with spin).
- Non-orthogonal orbitals: H(k)c = E S(k)c with S built the same way (scipy.linalg.eigh(H, S)).

## 2. Building H(k)

1. Lattice vectors a_i as rows, reciprocal vectors b_i; assert a_i·b_j = 2πδ_ij.
2. Orbital positions τ_α (store fractional, convert to Cartesian once).
3. Hopping list (α, β, R, t) with each bond once. Add the conjugate t_βα(−R) = t_αβ(R)* in code, never in the list.
4. H(k) = onsite + Σ t e^{ik·d} + h.c. with d = R + τ_β − τ_α, all Cartesian (or k·d = 2π k_frac·d_frac with
   k in units of b_i and d in units of a_i).

| | Convention I (cell gauge, phase e^{ik·R}) | Convention II (position gauge, e^{ik·(R + τ_β − τ_α)}) |
|---|---|---|
| H(k + G) | H(k) | V(G)†H(k)V(G), V = diag(e^{iG·τ_α}) |
| Relation | H_I = D H_II D†, D = diag(e^{ik·τ_α}) | |
| Eigenvalues, Chern numbers | identical | identical |
| Berry phase along a loop | ignores intracell positions | 2π × Wannier centre/a (polarisation) |
| Closure of a discrete loop | u_N = u_0 | u_N = V(G)†u_0 |
| Typical use | textbook SSH formulas, FHS grids | PythTB |

```python
import numpy as np
def make_hk(onsite, hops, tau):
    """hops: (i, j, R, t) = <0,i|H|R,j>; R and tau Cartesian; position gauge (convention II)."""
    tau = np.asarray(tau, float)
    def hk(k):
        H = np.diag(np.asarray(onsite, complex))
        for i, j, R, t in hops:
            v = t*np.exp(1j*np.dot(k, np.asarray(R, float) + tau[j] - tau[i]))
            H[i, j] += v
            H[j, i] += np.conj(v)          # i == j with R != 0 correctly gives 2 Re(v)
        return H
    return hk
```

## 3. Worked lattices

1D chain (on-site ε₀, hopping −t, spacing a): E = ε₀ − 2t cos ka, bandwidth 4t, band-bottom mass
m* = ħ²/(2ta²), DOS per site ρ(E) = 1/(π√(4t² − (E − ε₀)²)) with inverse-square-root van Hove edges.

SSH (sites A, B per cell, intracell hopping v, intercell w, convention I, a = 1):
H(k) = [[0, v + we^{−ik}], [v + we^{ik}, 0]], E = ±√(v² + w² + 2vw cos k), gap 2|v − w| at k = π. Chiral
symmetry σ_zHσ_z = −H pairs ±E. The winding of h(k) = v + we^{ik} around 0 is ν = 1 for |w| > |v| and 0 for
|w| < |v|; the gap closes at |v| = |w|.

Graphene (C-C distance a = 1.42 Å, H = −tΣ_NN, t ≈ 2.7 eV):
- a₁ = (a/2)(3, √3), a₂ = (a/2)(3, −√3); neighbours δ₁ = (a/2)(1, √3), δ₂ = (a/2)(1, −√3), δ₃ = (−a, 0).
- H(k) = [[0, −tf(k)], [−tf(k)*, 0]], f = Σ_j e^{ik·δ_j}, E = ±t|f|, |f|² = 3 + 2cos(k·a₁) + 2cos(k·a₂) + 2cos(k·(a₁ − a₂)).
- Γ = 0 (E = ±3t), M = (2π/3a, 0) (E = ±t, van Hove), K = (2π/3a, 2π/(3√3a)) and K′ = (2π/3a, −2π/(3√3a)) (E = 0).
- Near K: E = ±ħv_F|q| with v_F = 3ta/(2ħ) = 8.74 × 10⁵ m/s. Low-energy DOS with spin and valley:
  ρ(E) = 2|E|/(πħ²v_F²) per unit area.
- A next-nearest hopping t′ (H = −tΣ_NN − t′Σ_NNN) adds −t′(|f|² − 3) to both bands and breaks the ±E symmetry.

## 4. k-paths through the Brillouin zone and band plots

| Lattice | Path | Special points (fractional, units of b₁, b₂) |
|---|---|---|
| chain | −π/a → π/a | |
| square | Γ-X-M-Γ | X = (½, 0), M = (½, ½) |
| hexagonal, a₁ = a(1, 0), a₂ = a(½, √3/2) | Γ-K-M-Γ | K = (⅔, ⅓), M = (½, ½); \|ΓK\| = 4π/3a, \|ΓM\| = 2π/(√3a) |
| 3D Bravais lattices | standard tables | seekpath (Hinuma et al.) or Setyawan-Curtarolo conventions |

Here a is the lattice constant (√3 × the C-C distance for graphene). Confirm special points numerically
(E(K) = 0 for graphene) before trusting a table, because the coordinates change with the choice of a₁, a₂.

- The x-axis is the cumulative Cartesian |Δk|, never the point index or fractional steps; give each segment a
  number of points proportional to its length.
- eigvalsh returns sorted energies, so a symmetry-protected crossing plots as two touching sorted bands; track
  bands by eigenvector overlap when the crossing matters.

```python
def kpath(nodes_frac, B, n=300):
    nodes = np.asarray(nodes_frac, float) @ B                      # to Cartesian
    seg = np.linalg.norm(np.diff(nodes, axis=0), axis=1)
    cnt = np.maximum(2, np.round(n*seg/seg.sum()).astype(int))
    ks = np.vstack([np.linspace(nodes[i], nodes[i + 1], c, endpoint=(i == len(seg) - 1))
                    for i, c in enumerate(cnt)])
    dist = np.r_[0, np.cumsum(np.linalg.norm(np.diff(ks, axis=0), axis=1))]
    return ks, dist, np.r_[0, np.cumsum(seg)]                      # k-points, x-axis, node positions
# E = np.array([np.linalg.eigvalsh(hk(k)) for k in ks]); plt.plot(dist, E, 'k'); plt.xticks(nodes_x, labels)
```

## 5. Density of states

| Method | Use when | Notes |
|---|---|---|
| Histogram of E_n(k) on a uniform grid | quick look | bin ≳ the energy step between neighbouring k; noisy |
| Gaussian or Lorentzian broadening σ | smooth curves in 1D and 2D | σ ≈ 2-3 × max\|∇_kE\|·Δk; smears van Hove peaks |
| Linear tetrahedron (Blöchl corrections) | 3D, sharp features, N(E_F) | no σ; standard in DFT codes |
| Kernel polynomial method (Chebyshev, Jackson kernel) | 10⁵-10⁷ sites, disorder | resolution ≈ bandwidth/N_moments; in Kwant and pybinding |

Normalise ∫ρ dE = N_orb per cell (× 2 for spin) and refine the k-grid until features stop moving.

```python
def dos_gauss(evals, E, sigma):            # evals: (Nk, Nbands) on a uniform grid; result per cell
    e = evals.ravel()[:, None]
    return np.exp(-(E[None, :] - e)**2/(2*sigma**2)).sum(0)/(np.sqrt(2*np.pi)*sigma*evals.shape[0])
```

Moment sum rules on uniform grids: (1/N_k)Σ_kΣ_n E_n = Σ_α ε_α, and (1/N_k)Σ_kΣ_n E_n² = Σ_α ε_α² plus the
sum of |t|² over every neighbour of every orbital. Graphene: 6t² per cell, ⟨E²⟩ = 3t² per band (checked).

## 6. Topology: Berry phase, Chern number, edge states

Berry connection A = i⟨u|∇_k u⟩, Berry phase γ = ∮A·dk, discretised and gauge invariant as
γ = −Im ln Π_j⟨u_j|u_{j+1}⟩ with the loop closed as in §2. Curvature Ω = ∂_xA_y − ∂_yA_x, Chern number
C = (1/2π)∫_BZ Ω.

- Winding of a chiral 1D model with off-diagonal block h(k): ν = (1/2π)∮d arg h(k), computed with np.unwrap.
- Zak phase of the SSH lower band (NumPy and PythTB agree):

| Gauge and cell | trivial v = 1, w = 0.5 | topological v = 0.5, w = 1 |
|---|---|---|
| convention I | 0 | π |
| convention II, orbitals at 0 and ½ (PythTB with that geometry) | +π/2 | −π/2 |
| convention II, inversion-centred cell, orbitals at −¼ and +¼ | 0 | π |

  Only differences, or values in a cell that respects inversion or chiral symmetry, are invariants.
- Chern number by Fukui-Hatsugai-Suzuki (J. Phys. Soc. Jpn. 74, 1674 (2005)): on an N × N grid, links
  U_μ(k) = det⟨u(k)|u(k + μ̂)⟩/|det| over the occupied set (the determinant copes with touching bands inside
  the set), plaquette F(k) = −arg[U_x(k)U_y(k + x̂)U_x(k + ŷ)⁻¹U_y(k)⁻¹], C = (1/2π)Σ_k F(k). It is an integer
  once N resolves the curvature, with no smooth gauge needed. PythTB 2 berry_flux uses the same −Im ln sign.

```python
def chern_fhs(hk, N=30, nocc=1):           # hk(kx, ky) periodic on [0, 2π)² (convention I)
    ks = np.linspace(0, 2*np.pi, N, endpoint=False)
    U = [[np.linalg.eigh(hk(kx, ky))[1][:, :nocc] for ky in ks] for kx in ks]
    link = lambda A, B: (lambda z: z/abs(z))(np.linalg.det(A.conj().T @ B))
    F = 0.0
    for i in range(N):
        for j in range(N):
            i1, j1 = (i + 1) % N, (j + 1) % N
            F -= np.angle(link(U[i][j], U[i1][j])*link(U[i1][j], U[i1][j1])
                          *link(U[i1][j1], U[i][j1])*link(U[i][j1], U[i][j]))
    return F/(2*np.pi)
def qwz(kx, ky, u):                        # Qi-Wu-Zhang, d = (sin kx, sin ky, u + cos kx + cos ky)
    dz = u + np.cos(kx) + np.cos(ky)
    return np.array([[dz, np.sin(kx) - 1j*np.sin(ky)], [np.sin(kx) + 1j*np.sin(ky), -dz]])
# lower band: C = +1 for -2 < u < 0, -1 for 0 < u < 2, 0 for |u| > 2
```

- Edge states in ribbons: keep a₁ periodic, take W cells along a₂ (H(k₁) of size W·N_orb), plot E(k₁) and
  locate each state by its weight near either edge. Bulk-boundary correspondence: the net number of chiral
  modes crossing the gap on one edge equals the total C of the occupied bands.
- Graphene: zigzag edges carry a flat E = 0 band for 2π/3 < |k₁| ≤ π (one state per edge at k₁ = π); armchair
  ribbons have no edge band and are metallic in nearest-neighbour tight binding only when the number of dimer
  lines is 3m − 1.

```python
def ribbon_hk(onsite, hops, W):
    """hops: (i, j, (n1, n2), t) = <cell 0, i|H|cell (n1, n2), j>; periodic along a1, W cells along a2."""
    no = len(onsite)
    def hk(k1):
        H = np.zeros((W*no, W*no), complex)
        for m in range(W):
            H[m*no:(m + 1)*no, m*no:(m + 1)*no] += np.diag(onsite)
            for i, j, (n1, n2), t in hops:
                if 0 <= m + n2 < W:
                    v = t*np.exp(1j*k1*n1)
                    H[m*no + i, (m + n2)*no + j] += v
                    H[(m + n2)*no + j, m*no + i] += np.conj(v)
        return H
    return hk
hops = [(0, 1, (0, 0), -1.0), (1, 0, (1, 0), -1.0), (1, 0, (0, 1), -1.0)]   # A at (⅓, ⅓), B at (⅔, ⅔)
zz = ribbon_hk([0.0, 0.0], hops, 20)       # zigzag edges along a1 = a(1, 0)
# smallest |E|: 1.02 at k1 = 0, 0.22 at 0.6π, 4e-5 at 0.8π (85% on the edge cells), 0 at π (100%)
```

## 7. Tools

PythTB 2.0 (run with 2.0.0). Version 1.x scripts break: tb_model is deprecated, and wf_array and solve_on_grid
are gone (use WFArray with solve_model).

```python
from pythtb import Lattice, TBModel, Mesh, WFArray
lat = Lattice([[1.0, 0.0], [0.5, np.sqrt(3)/2]], [[1/3, 1/3], [2/3, 2/3]], periodic_dirs=[0, 1])
m = TBModel(lat)
m.set_onsite([-0.2, 0.2])
m.set_hop(-1.0, 0, 1, [0, 0]); m.set_hop(-1.0, 1, 0, [1, 0]); m.set_hop(-1.0, 1, 0, [0, 1])
k_vec, k_dist, k_node = m.k_path([[0, 0], [2/3, 1/3], [0.5, 0.5], [0, 0]], 301, report=False)
evals = m.solve_ham(k_vec)                  # shape (301, 2); k_node = [0, 4.189, 6.283, 9.911] for a = 1
mesh = Mesh(['k', 'k']); mesh.build_grid((31, 31))
wf = WFArray(lat, mesh); wf.solve_model(m)
wf.chern_number((0, 1), [0])                # 0 here; PythTB's Haldane example (t2 = 0.15i) gives -1
# 1D model: mesh = Mesh(['k']); mesh.build_grid((101,)); wf = WFArray(lat1d, mesh); wf.solve_model(m1d)
# then wf.berry_phase(0, [0]) is the Zak phase; m1d.cut_piece(20, 0, glue_edges=False).solve_ham() is the open chain
```

Kwant does transport: Landauer conductance G = (e²/h)ΣT from scattering matrices, with leads and disorder.
PyPI offers no wheel for CPython 3.13 on macOS arm64 (the source build failed here); install from conda-forge.
The snippet uses the long-stable 1.4/1.5 API but was not executed for this skill:

```python
import kwant
lat = kwant.lattice.chain(a=1, norbs=1)
syst = kwant.Builder()
syst[(lat(i) for i in range(10))] = 0.0
syst[lat.neighbors()] = -1.0
lead = kwant.Builder(kwant.TranslationalSymmetry((-1,)))
lead[lat(0)] = 0.0
lead[lat.neighbors()] = -1.0
syst.attach_lead(lead); syst.attach_lead(lead.reversed())
fsyst = syst.finalized()
kwant.smatrix(fsyst, 0.5).transmission(1, 0)    # expect 1 inside the band (|E| < 2t), 0 outside
```

- pybinding: large real-space models with strain and fields, and KPM DOS or LDOS for millions of sites. Its
  releases have been sparse, so check that a wheel exists for your Python before relying on it.
- Wannier90: DFT bands → maximally localised Wannier functions → a real-space H(R) table (seedname_hr.dat) that
  interpolates bands on any path. Read it with PythTB (its W90 class) or TBmodels; WannierBerri does Berry
  curvature and anomalous Hall; Z2Pack computes Z₂ and Chern numbers from Wannier charge centres. Checks: the
  interpolated bands match DFT inside the frozen window, spreads are small, and |t(R)| decays with |R|.

## 8. Validation

| Check | Expectation |
|---|---|
| Hermiticity | max\|H(k) − H(k)†\| < 1e-12 at random k |
| Periodicity | E_n(k + G) = E_n(k) in both gauges |
| Time reversal (spinless, real hoppings) | E(−k) = E(k) |
| Chiral or sublattice symmetry | spectrum symmetric under E → −E (SSH, nearest-neighbour graphene) |
| Limits | t → 0 gives flat bands at ε_α; a chain has bandwidth 4t; graphene ±3t at Γ, ±t at M, 0 at K |
| Sum rules | trace and second moment of §5 |
| DOS normalisation | ∫ρ dE = N_orb per cell (× 2 for spin) |
| Chern number | integer to 1e-10; unchanged when the grid doubles; zero summed over all bands |
| Phase diagram | invariants change only where the bulk gap closes (scan the parameter) |

## 9. Pitfalls and worked example

Worked example, SSH with v = 0.5, w = 1 (topological) against v = 1, w = 0.5 (trivial):

```python
v, w, N = 0.5, 1.0, 20
k = np.linspace(-np.pi, np.pi, 2001)
ph = np.unwrap(np.angle(v + w*np.exp(1j*k))); nu = (ph[-1] - ph[0])/(2*np.pi)   # 1.0 (0.0 if v, w swapped)
H = np.zeros((2*N, 2*N)); i = np.arange(N); j = np.arange(N - 1)
H[2*i, 2*i + 1] = H[2*i + 1, 2*i] = v      # intracell A_n-B_n
H[2*j + 1, 2*j + 2] = H[2*j + 2, 2*j + 1] = w      # intercell B_n-A_n+1
E, U = np.linalg.eigh(H)
idx = np.argsort(abs(E))[:2]; E[idx]       # ±7.15e-07; next level 0.513
```

- Winding 1 against 0. The open 40-site chain has two modes at ±7.15 × 10⁻⁷ ≈ ±w(1 − (v/w)²)(v/w)^N
  = ±0.75 × 2⁻²⁰, well inside the bulk gap (the next level is 0.513). Each mode has 93.75% of its weight on the
  four sites at each end; the left end mode lives on sublattice A only, with amplitude ratio −v/w = −0.5 per cell
  (decay length 1/ln(w/v) = 1.44 cells). The trivial chain's lowest |E| is 0.510: no end modes.
- Zak phases as in the §6 table. PythTB with orbitals at 0 and ½ returns ±π/2, and cut_piece(20, 0) reproduces
  the ±7.15 × 10⁻⁷ pair.
- Graphene with t = 2.7 eV and a = 1.42 Å: E(Γ) = ±8.1 eV, E(M) = ±2.7 eV, E(K) = 1e-15 eV; the slope at K gives
  v_F = 8.737 × 10⁵ m/s = 3ta/2ħ; path lengths |ΓK| = 2.418/a, |KM| = 1.209/a, |MΓ| = 2.094/a; ⟨E²⟩ = 3t² per band.

Pitfalls:
- Fractional k dotted with Cartesian R (or the reverse); check b_i·a_j = 2πδ_ij first.
- Listing both i→j and j→i and then adding h.c. as well doubles the bandwidth.
- Gauge mixing: convention-I eigenvectors with convention-II positions give wrong Berry phases and Wannier
  centres; an FHS grid in convention II without the V(G) closure gives a non-integer C.
- Plotting against point index instead of |Δk| distorts every segment.
- A "Zak phase π" depends on the cell choice; end modes depend on the termination (cut through w or v bonds).
- Single-band links where bands touch inside the occupied set: use determinants (non-Abelian links).
- The Chern sign convention differs between papers (−Im ln against +arg); validate on QWZ or Haldane first.
- DOS broadening too small gives spikes, too large hides van Hove peaks; spin factor 2.
- Finite-size splitting of edge modes, ∝ e^{−L/ξ}, is not a gap; grow L and watch it vanish exponentially.

Related: `quantum-mechanics-methods`, `schrodinger-numerics`, `matrix-decompositions-conditioning`, `simulation-verification-validation`, hub `physics-toolkit`
