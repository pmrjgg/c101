---
name: molecular-dynamics-setup
description: "Classical molecular dynamics set-up and analysis: force-field and ML-potential choice, units, time step from the fastest mode, constraints and HMR, thermostats/barostats that sample the right ensemble, PME, the equilibration protocol, NVE drift checks, and RDF/MSD/Green-Kubo observables with OpenMM, LAMMPS, GROMACS or ASE. Load when building, running or reviewing an MD simulation."
when_to_use: "Building, running or reviewing an OpenMM, GROMACS, LAMMPS or ASE simulation; choosing a force field, water model or ML potential (MACE, MACE-MP-0, NequIP/Allegro); picking a time step, constraints or hydrogen mass repartitioning; choosing thermostat, barostat and PME settings; energy drift in NVE; computing g(r), a diffusion coefficient from the MSD, a Green-Kubo viscosity or a finite-size correction; converting LJ reduced or LAMMPS units; validating the sampled ensemble."
---

# Molecular dynamics set-up

MD results fail in five repeatable ways: a thermostat or barostat that samples the wrong
ensemble, a time step beyond the fastest mode, cutoffs and electrostatics that do not match the
force field, runs that are single and shorter than the slowest correlation time, and analysis on
wrapped coordinates or uncorrected box sizes. APIs were checked in October 2026 against OpenMM
8.6, ASE 3.29, pymbar 4.0 and physical_validation 1.0. Deep material:
[LJ argon reproduction script and output](references/lj-argon-numpy.md).

## 1. Workflow

1. Build: PDBFixer (missing atoms, protonation states), packmol for mixtures (2.0 Å tolerance,
   target density), Moltemplate for LAMMPS molecular systems, Modeller/`gmx solvate` for water
   and 0.15 M neutralising ions.
2. Minimise (steepest descent or L-BFGS) until the largest force is ≲ 1000 kJ/(mol·nm).
3. NVT 100–500 ps with heavy-atom restraints (~1000 kJ/(mol·nm²)).
4. NPT 1–5 ns, releasing restraints in stages; wait for the density to plateau.
5. Production. Run ≥ 3 replicas from different velocity seeds (different starting structures
   when possible) and make each ≥ 10–20× the slowest correlation time of the observable.
6. Detect equilibration and block-average before quoting a number (section 8).

## 2. Force fields

| System | Force field | Partner / notes |
|---|---|---|
| Proteins | AMBER ff19SB | OPC water; OpenMM ships `amber19-all.xml` + `amber19/opc.xml` (loads in 8.6) |
| Proteins, membranes | CHARMM36m | CHARMM TIP3P; force-switch 1.0–1.2 nm and no dispersion correction for lipids |
| Organic liquids | OPLS-AA (LigParGen) | geometric combining rules for σ and ε |
| Ligands, small molecules | GAFF2 (AM1-BCC) or OpenFF Sage 2.x | `openmmforcefields`; match the protein force field's water |
| Metals and alloys | EAM / MEAM | LAMMPS `pair_style eam/alloy`, `meam` |
| Reactive chemistry | ReaxFF | dt 0.1–0.25 fs, charge equilibration every step |
| DFT-quality anything | MACE, MACE-MP-0 foundation models, NequIP/Allegro | extrapolation check below |

ML potentials need an extrapolation check: a committee of 3–5 models (force spread above
~0.1–0.2 eV/Å flags extrapolation), single-point DFT on sampled frames, and a watch for atoms
approaching unphysically close (holes in the learned surface). MACE-MP-0 inherits PBE errors from
its Materials Project training data; fine-tune for production.

Combining rules: AMBER and CHARMM use Lorentz-Berthelot (σ_ij = (σ_i + σ_j)/2,
ε_ij = sqrt(ε_iε_j)); OPLS uses geometric means for both. Never mix parameters across force
fields or combining rules.

## 3. Time step rules

dt ≈ 1/10–1/20 of the fastest period (an X-H stretch at 3300 cm⁻¹ has a 10 fs period).

| Fastest motion | dt |
|---|---|
| Flexible bonds to hydrogen | 0.5–1 fs |
| X-H bonds constrained (SHAKE/RATTLE, LINCS; SETTLE for water) | 2 fs |
| + hydrogen mass repartitioning (H ≈ 3–4 amu, taken from the bonded heavy atom) | 4 fs |
| LJ argon (reduced units) | 0.002–0.005 τ (4–11 fs) |
| Metals (EAM) | 1–5 fs |
| ReaxFF | 0.1–0.25 fs |
| Coarse-grained (MARTINI) | 20–30 fs |

NVE drift target: < ~0.01 k_BT per degree of freedom per ns. Measure it before any thermostatted
production run and again after any change of dt, cutoff or constraint tolerance.

## 4. Thermostats and barostats

| Method | Canonical? | Use and parameters |
|---|---|---|
| Langevin (BAOAB / `LangevinMiddleIntegrator`) | yes | default sampling; γ ≈ 1 ps⁻¹ (≤ 0.1 ps⁻¹ when dynamics matter) |
| Nosé-Hoover chains | yes, if ergodic | dynamics; τ_T ≈ 0.5–1 ps; LAMMPS Tdamp ≈ 100 steps |
| Bussi stochastic velocity rescaling (v-rescale) | yes | GROMACS default choice; τ_T = 0.1–1 ps |
| Berendsen | no (suppresses fluctuations) | equilibration only |
| Andersen | yes | sampling only; destroys dynamics |
| Monte Carlo barostat (OpenMM) | yes | every 25 steps |
| C-rescale (Bernetti-Bussi; GROMACS ≥ 2021) | yes | default NPT; τ_p ≈ 2–5 ps |
| Parrinello-Rahman, MTTK | yes | production near equilibrium; oscillates if started far from it |
| Berendsen barostat | no | equilibration only |

For diffusion, viscosity or spectra use NVE or weak coupling (Langevin γ ≤ 0.1 ps⁻¹, Nosé-Hoover
or v-rescale τ_T ≥ 1 ps); strong Langevin friction lowers D directly.

## 5. Electrostatics and cutoffs

- PME/PPPM for anything charged, with an Ewald tolerance ~1e-5 (GROMACS `ewald-rtol` default;
  OpenMM's `ewaldErrorTolerance` defaults to 5e-4, tighten for free energies).
- Real-space cutoff 0.9–1.2 nm as the force field prescribes, plus a neighbour-list buffer
  (GROMACS `verlet-buffer-tolerance`, LAMMPS `neighbor` skin 2 Å in real units, 0.3σ in LJ).
- LJ long-range dispersion correction (`DispCorr = EnerPres`) for homogeneous fluids, unless the
  force field says otherwise (CHARMM36 lipids).
- Minimum image: every box length > 2r_c (in practice > 2(r_c + buffer)); keep ≥ 1.0–1.2 nm of
  solvent between a solute and the box edge.
- Net charge: Ewald sums add a uniform neutralising background; neutralise with counterions and
  apply finite-size corrections to charging free energies.

```
; GROMACS production .mdp (2 fs, h-bond constraints, PME, NPT)
integrator = md
dt = 0.002
nsteps = 5000000            ; 10 ns
constraints = h-bonds
constraint-algorithm = lincs
cutoff-scheme = Verlet
coulombtype = PME
rcoulomb = 1.0
rvdw = 1.0
DispCorr = EnerPres
tcoupl = V-rescale
tc-grps = System
tau-t = 1.0
ref-t = 300
pcoupl = C-rescale
tau-p = 2.0
ref-p = 1.0
compressibility = 4.5e-5
```

## 6. Units

| Code | Length | Time | Energy | Mass | T, p |
|---|---|---|---|---|---|
| LAMMPS `units real` | Å | fs | kcal/mol | g/mol | K, atm |
| LAMMPS `units metal` | Å | ps | eV | g/mol | K, bar |
| LAMMPS `units lj` | σ | τ | ε | m | ε/k_B, ε/σ³ |
| GROMACS, OpenMM | nm | ps | kJ/mol | amu | K, bar |
| ASE | Å | Å·sqrt(amu/eV) ≈ 10.18 fs (use `ase.units.fs`) | eV | amu | K |

Reduced LJ units: T* = k_BT/ε, ρ* = ρσ³ (number density), t* = t·sqrt(ε/(mσ²)) = t/τ,
p* = pσ³/ε, D* = Dτ/σ², η* = ησ²/sqrt(mε). Argon (ε/k_B = 119.8 K, σ = 3.405 Å, 39.948 g/mol):
τ = 2.156 ps, σ²/τ = 5.377e-4 cm²/s, sqrt(mε)/σ² = 9.035e-5 Pa·s (computed). Conversions:
1 kcal/mol = 4.184 kJ/mol, 1 eV = 96.485 kJ/mol, k_B = 0.0083145 kJ/(mol·K). Convert explicitly
and write the unit next to every number when moving between codes (`dimensional-analysis-units`).

## 7. Snippets

```python
# OpenMM 8.x: solvated protein, PME, 2 fs with h-bond constraints, NPT
import sys
from openmm import LangevinMiddleIntegrator, MonteCarloBarostat
from openmm.app import PDBFile, ForceField, Modeller, Simulation, PME, HBonds, StateDataReporter, DCDReporter
from openmm.unit import kelvin, picosecond, picoseconds, nanometer, bar, molar
pdb = PDBFile("protein_fixed.pdb")
ff = ForceField("amber14-all.xml", "amber14/tip3pfb.xml")   # ff19SB+OPC: "amber19-all.xml", "amber19/opc.xml" (4-site water box)
mod = Modeller(pdb.topology, pdb.positions)
mod.addSolvent(ff, model="tip3p", padding=1.0*nanometer, ionicStrength=0.15*molar)
system = ff.createSystem(mod.topology, nonbondedMethod=PME, nonbondedCutoff=1.0*nanometer,
                         constraints=HBonds)                 # HMR: hydrogenMass=4*amu with 0.004 ps
system.addForce(MonteCarloBarostat(1*bar, 300*kelvin, 25))
integrator = LangevinMiddleIntegrator(300*kelvin, 1/picosecond, 0.002*picoseconds)
sim = Simulation(mod.topology, system, integrator)
sim.context.setPositions(mod.positions)
sim.minimizeEnergy()
sim.context.setVelocitiesToTemperature(300*kelvin, 2026)
sim.reporters += [StateDataReporter(sys.stdout, 5000, step=True, potentialEnergy=True, temperature=True,
                                    density=True, speed=True),
                  DCDReporter("traj.dcd", 5000, enforcePeriodicBox=False)]   # unwrapped for MSD
sim.step(500_000)                                             # 1 ns
```

```
# LAMMPS: Rahman's liquid argon in reduced units (section 11)
units         lj
atom_style    atomic
lattice       fcc 0.8177                 # rho* = 1.374 g/cm3 * sigma^3 / m
region        box block 0 6 0 6 0 6      # 4*6^3 = 864 atoms
create_box    1 box
create_atoms  1 box
mass          1 1.0
velocity      all create 0.788 1964 mom yes rot yes dist gaussian
pair_style    lj/cut 2.5
pair_coeff    1 1 1.0 1.0 2.5
pair_modify   shift yes
neighbor      0.3 bin
neigh_modify  every 1 delay 0 check yes
timestep      0.005
fix           1 all nvt temp 0.788 0.788 0.5   # Tdamp = 100 steps; equilibration
thermo_style  custom step temp pe etotal press
thermo        500
run           20000
unfix         1
fix           2 all nve
compute       msd all msd com yes
fix           3 all ave/time 10 1 10 c_msd[4] file msd.dat
run           12000
```

```python
# ASE + MACE foundation model, Langevin at 1 ps^-1
import numpy as np
from ase import units
from ase.build import bulk
from ase.md.langevin import Langevin
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution, Stationary
from mace.calculators import mace_mp
atoms = bulk("Cu", "fcc", a=3.61, cubic=True).repeat((4, 4, 4))
atoms.calc = mace_mp(model="medium", default_dtype="float64")   # device="cuda" on a GPU
rng = np.random.default_rng(1)
MaxwellBoltzmannDistribution(atoms, temperature_K=600, rng=rng); Stationary(atoms)
dyn = Langevin(atoms, 2*units.fs, temperature_K=600, friction=0.001/units.fs, rng=rng)
dyn.attach(lambda: print(atoms.get_potential_energy()/len(atoms), atoms.get_temperature()), interval=100)
dyn.run(5000)
```

## 8. Analysis

```python
import numpy as np, MDAnalysis as mda
from MDAnalysis.analysis.rdf import InterRDF
from MDAnalysis.analysis.msd import EinsteinMSD
u = mda.Universe("system.pdb", "traj.dcd")
ow = u.select_atoms("resname HOH and name O")
rdf = InterRDF(ow, ow, nbins=300, range=(0.0, 12.0), exclusion_block=(1, 1)).run()
r_peak = rdf.results.bins[np.argmax(rdf.results.rdf)]          # water: about 2.8 Å
msd = EinsteinMSD(u, select="resname HOH and name O", msd_type="xyz", fft=True).run()
lag = np.arange(msd.n_frames)*u.trajectory.dt                   # ps; trajectory must be unwrapped
sel = (lag > 0.1*lag[-1]) & (lag < 0.5*lag[-1])                 # linear regime, not the ballistic start
D = np.polyfit(lag[sel], msd.results.timeseries[sel], 1)[0]/6  # Å^2/ps; x 1e-4 -> cm^2/s
```

- D from the MSD slope over 6t on unwrapped coordinates (`enforcePeriodicBox=False` in OpenMM,
  `gmx trjconv -pbc nojump`, LAMMPS `compute msd` with image flags). Fit the linear regime only.
- Finite-size (Yeh-Hummer) for cubic boxes: D_∞ = D_PBC + k_BTξ/(6πηL), ξ = 2.837297, with η the
  model's own shear viscosity at the same state point.
- Green-Kubo viscosity: η = (V/k_BT)∫₀^∞⟨P_xy(0)P_xy(t)⟩dt averaged over xy, xz, yz; write the
  pressure tensor every few fs, average many independent segments and read the plateau of the
  running integral (Einstein-Helfand is the integrated alternative).
- Equilibration and correlated errors with pymbar 4:

```python
from pymbar import timeseries
t0, g, neff = timeseries.detect_equilibration(A_t)              # A_t: density or energy per frame
idx = timeseries.subsample_correlated_data(A_t[t0:], g=g)
mean, err = A_t[t0:][idx].mean(), A_t[t0:][idx].std(ddof=1)/np.sqrt(len(idx))
```

## 9. Validation

- NVE conservation: drift below the section 3 target and fluctuations that scale as dt²
  (physical_validation `integrator.convergence` across 2–3 time steps).
- Ensemble: `physical_validation.kinetic_energy.distribution(data)` tests the kinetic-energy
  distribution; `ensemble.check(...)` compares two temperatures or pressures against the
  Boltzmann ratio. Berendsen runs fail this test.
- Structure and thermodynamics against experiment: density (water 0.997 g/cm³ at 298 K; TIP3P
  ≈ 0.98, OPC ≈ 0.997), first O-O peak of water near 2.8 Å, water D = 2.30e-5 cm²/s at 298 K
  (TIP3P gives ~5–6e-5, so its dynamics are too fast).
- Reproducibility: report mean ± standard error over ≥ 3 replicas, not one trajectory's blocks.

## 10. Performance

Measure ns/day. GPU paths: OpenMM CUDA/HIP/OpenCL platforms (mixed precision default), GROMACS
GPU-resident steps (`gmx mdrun -nb gpu -pme gpu -bonded gpu -update gpu`), LAMMPS KOKKOS
(`lmp -k on g 1 -sf kk -in in.lj`). Profile before buying hardware: GROMACS reports the PP/PME
load balance and tunes the PME grid and nstlist itself; LAMMPS prints the Pair/Neigh/Comm/Kspace
split; trade rcoulomb against PME grid spacing and the neighbour-list buffer against rebuild
frequency (`performance-optimization`).

## 11. Worked example: Rahman's liquid argon (computed)

N = 864, ε/k_B = 119.8 K, σ = 3.405 Å, 94.4 K, 1.374 g/cm³ → ρ* = 0.8177, T* = 0.788,
L = 10.185σ = 3.468 nm, τ = 2.156 ps. NumPy velocity Verlet, LJ truncated and shifted at 2.5σ,
dt = 0.005τ (10.8 fs), 4000 steps with velocity rescaling (equilibration only), 1000 NVE steps,
then 12,000 NVE production steps (60τ = 129 ps); script and output in the reference file.

1. NVE drift 2.0e-6 ε per atom per τ = 3.9e-4 k_BT per DOF per ns, far below the 0.01 target;
   std(E)/N = 9e-5 ε. ⟨T⟩ = 0.7959 (95.3 K): NVE settles 0.9 K above the rescaling target, so
   report the measured T, not the set point.
2. MSD slope over 5–30τ: D* = 0.0472, three segments 0.0413/0.0533/0.0442 → D* = 0.047 ± 0.004,
   D_PBC = (2.54 ± 0.19)e-5 cm²/s. Rahman reported 2.43e-5 cm²/s for the same N: agreement within
   0.6σ, partly helped by our 0.9 K higher temperature.
3. Green-Kubo running integral η* = 2.49, 2.38, 1.88, 1.64, 2.15 at 0.5, 1, 2, 3, 5τ: no clean
   plateau in 60τ, so η* = 2.0 ± 0.4, η = (1.8 ± 0.4)e-4 Pa·s.
4. Yeh-Hummer: ΔD* = T*ξ/(6πη*L*) = 0.7959 × 2.837297/(6π × 2.0 × 10.185) = 0.0059, i.e.
   ΔD = (0.32 ± 0.07)e-5 cm²/s and D_∞ = (2.85 ± 0.20)e-5 cm²/s: the box size alone hides a 12 %
   effect. Compare D_PBC with simulations at the same N, and D_∞ with experiment at the same T and
   density.

## 12. Pitfalls

- The flying ice cube: repeated simple velocity rescaling (or Berendsen) pumps energy into the
  centre-of-mass and slow modes; remove COM motion and use v-rescale, Nosé-Hoover or Langevin.
- MSD on wrapped coordinates (D collapses to ~0 after particles cross the box) or fitted over the
  ballistic or noisy long-lag region.
- Runs shorter than the correlation time of the observable; a single trajectory reported with
  block errors as if it were an ensemble.
- Strong thermostats (Langevin γ ≫ 1 ps⁻¹, Berendsen) when diffusion or viscosity are wanted.
- A cutoff and dispersion correction that differ from the force field's parametrisation; plain
  cutoffs for charged systems; boxes below 2r_c.
- ML potentials run outside their training domain without an uncertainty check.

Related: `physics-ode-integrators`, `statmech-monte-carlo`, `dimensional-analysis-units`, `uncertainty-propagation-fitting`, `performance-optimization`, `simulation-verification-validation`, hub `physics-toolkit`
