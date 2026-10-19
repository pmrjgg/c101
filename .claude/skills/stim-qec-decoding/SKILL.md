---
name: stim-qec-decoding
description: "Hands-on QEC simulation with Stim, Sinter and decoders (PyMatching, Fusion Blossom, BP-OSD, Chromobius, Tesseract): circuit language, detectors and observables, noise instructions, detector error models, threshold and Lambda sweeps with resume files, fits with confidence intervals, and circuit debugging. Load when logical error rates or thresholds must be produced numerically."
when_to_use: "Writing or debugging Stim circuits (DETECTOR, OBSERVABLE_INCLUDE, REPEAT, noise channels); 'non-deterministic detectors' or 'failed to decompose' errors; choosing a decoder for surface, color or qLDPC codes; running sinter collect sweeps, resume files and plots; computing per-round logical error rates, thresholds or Lambda with intervals; checking circuit distance; decoding hardware detection-event files."
---

# Stim, Sinter and decoders

A logical error rate is a measurement: it needs a circuit whose detectors are deterministic, a
decoder matched to the error model, enough logical errors for an interval, and a stated unit
(per shot or per round). Theory of the codes: `stabilizer-codes-surface-code`. Versions verified
here: stim 1.16, sinter 1.16, pymatching 2.4, chromobius 1.1, stimbposd 0.2, ldpc 2.4.

## 1. Circuit language

| Group | Instructions |
|---|---|
| reset / measure | `R RX RY`, `M MX MY`, `MR MRX` (measure then reset), `MPP X0*Z1` (Pauli-product measurement) |
| Clifford gates | `H S S_DAG SQRT_X X Y Z`, `CX CY CZ SWAP ISWAP` |
| annotations | `TICK`, `QUBIT_COORDS(x, y) q`, `DETECTOR(x, y, t) rec[-k] ...`, `OBSERVABLE_INCLUDE(k) rec[-k] ...`, `SHIFT_COORDS(dx, dy, dt)`, `REPEAT n { ... }` |
| noise | `DEPOLARIZE1(p)`, `DEPOLARIZE2(p)`, `X_ERROR(p)`, `Z_ERROR(p)`, `PAULI_CHANNEL_1(px, py, pz)`, `PAULI_CHANNEL_2(15 args)`, `HERALDED_ERASE(p)` |

`rec[-k]` is the k-th most recent measurement. A detector is a parity of measurements that is
deterministic without noise; an observable is a parity that equals a logical measurement.

```
R 0 1 2 3 4                        # d = 3 bit-flip repetition code: data 0 2 4, ancillas 1 3
TICK
CX 0 1 2 3
TICK
CX 2 1 4 3
TICK
MR 1 3
DETECTOR(1, 0) rec[-2]
DETECTOR(3, 0) rec[-1]
REPEAT 2 {
    TICK
    CX 0 1 2 3
    TICK
    CX 2 1 4 3
    TICK
    MR 1 3
    SHIFT_COORDS(0, 1)
    DETECTOR(1, 0) rec[-2] rec[-4]
    DETECTOR(3, 0) rec[-1] rec[-3]
}
M 0 2 4
DETECTOR(1, 1) rec[-2] rec[-3] rec[-5]
DETECTOR(3, 1) rec[-1] rec[-2] rec[-4]
OBSERVABLE_INCLUDE(0) rec[-1]
```

Generated circuits: `stim.Circuit.generated(task, distance=d, rounds=r, after_clifford_depolarization=p,
after_reset_flip_probability=p, before_measure_flip_probability=p, before_round_data_depolarization=p)`
with task in `repetition_code:memory`, `surface_code:rotated_memory_x`, `surface_code:rotated_memory_z`,
`surface_code:unrotated_memory_x|z`, `color_code:memory_xyz`.

## 2. Noise models

Uniform depolarizing through the generator arguments is the reproducible baseline. For a
superconducting-like model use SI1000 (2q gates p, 1q gates and idle p/10, measurement flip 5p,
reset flip 2p, idle during measurement/reset 2p) applied to a noiseless circuit layer by layer:

```python
import stim
ONE_Q = {"H", "S", "S_DAG", "SQRT_X", "SQRT_X_DAG", "X", "Y", "Z", "C_XYZ", "C_ZYX"}
TWO_Q = {"CX", "CZ", "CY", "SWAP", "ISWAP", "ISWAP_DAG", "CXSWAP", "SWAPCX"}
MEAS_RESET = {"M", "MX", "MY", "MR", "MRX", "MRY", "R", "RX", "RY"}

def si1000(c: stim.Circuit, p: float, n: int | None = None) -> stim.Circuit:
    n = c.num_qubits if n is None else n
    out, used, mr = stim.Circuit(), set(), False
    for inst in c:
        if isinstance(inst, stim.CircuitRepeatBlock):
            out.append(stim.CircuitRepeatBlock(inst.repeat_count, si1000(inst.body_copy(), p, n)))
            continue
        name, qs = inst.name, [t.value for t in inst.targets_copy() if t.is_qubit_target]
        if name == "TICK":
            idle = [q for q in range(n) if q not in used]
            if idle:
                out.append("DEPOLARIZE1", idle, 2 * p if mr else p / 10)
            out.append("TICK"); used, mr = set(), False
            continue
        flip = "Z_ERROR" if name.endswith("X") else "X_ERROR"
        if name in ("M", "MX", "MY", "MR", "MRX", "MRY"): out.append(flip, qs, 5 * p)
        out.append(inst)
        if name in ("R", "RX", "RY", "MR", "MRX", "MRY"): out.append(flip, qs, 2 * p)
        if name in TWO_Q: out.append("DEPOLARIZE2", qs, p)
        elif name in ONE_Q: out.append("DEPOLARIZE1", qs, p / 10)
        used.update(qs); mr |= name in MEAS_RESET
    return out

c = si1000(stim.Circuit.generated("surface_code:rotated_memory_z", distance=5, rounds=5), 1e-3)
```

Tested on rotated memory_z (CX form, no CZ compilation): per-round p_L at p = 1e-3 was 5.2e-4,
5.4e-5, 4.9e-6 for d = 3, 5, 7 (Λ ≈ 10); at p = 5e-3 it was 1.2e-2, 6.2e-3, 3.1e-3 (Λ ≈ 2). Keep
measurement and reset errors in every model and use rounds ≥ d.

## 3. Detector error model

```python
dem = circuit.detector_error_model(decompose_errors=True)   # required for matching decoders
print(dem.num_detectors, dem.num_observables, dem.num_errors)
```

Text form: `error(0.001) D3 D7`, `error(0.0005) D2 ^ D5 L0` (`^` separates graphlike pieces),
`detector(1, 0, 0) D0`. Options: `allow_gauge_detectors`, `approximate_disjoint_errors`,
`ignore_decomposition_failures`, `flatten_loops`.

| Error | Meaning | Fix |
|---|---|---|
| non-deterministic detectors / observables | a detector compares measurements that are random without noise: wrong `rec` offsets, an X check included in the first round of memory_z, wrong CNOT order | inspect `detslice-svg`; never "fix" with `allow_gauge_detectors` |
| failed to decompose errors into graphlike components | hyperedges (Y errors on color codes, qLDPC checks) | hypergraph decoder with `decompose_errors=False`, or `ignore_decomposition_failures=True` only knowingly |

`circuit.explain_detector_error_model_errors()` maps each DEM term back to circuit faults.

## 4. Decoders

| Code family | Decoder | Package and entry point |
|---|---|---|
| surface, repetition, toric | MWPM (sparse blossom) | `pymatching.Matching.from_detector_error_model(dem)`, `.decode_batch(dets)`; sinter name `pymatching` |
| same, X/Z-correlated (Y errors) | correlated matching | pymatching 2.4: `enable_correlations=True` in both calls above |
| surface, parallel MWPM | fusion blossom | `fusion-blossom`; sinter name `fusion_blossom` |
| qLDPC (bivariate bicycle, HGP) | BP+OSD, BP+LSD | `stimbposd` (`BPOSD`, `sinter_decoders()`), `ldpc` (`BpOsdDecoder`, `BpLsdDecoder`, `SinterBpOsdDecoder`) |
| color codes | Chromobius | `chromobius.compile_decoder_for_dem`, `chromobius.sinter_decoders()`; detectors need a 4th coordinate encoding basis and color (generated `color_code:memory_xyz` has it) |
| qLDPC and color, accuracy over speed | Tesseract (search based) | `tesseract-decoder`: `make_tesseract_sinter_decoders_dict()` |

New decoder: subclass `sinter.Decoder` with `compile_decoder_for_dem(*, dem)` returning a
`sinter.CompiledDecoder` that implements `decode_shots_bit_packed(*, bit_packed_detection_event_data)`;
pass it as `custom_decoders={"name": MyDecoder()}`.

## 5. Sinter at scale

```python
import sinter, stim
tasks = [sinter.Task(circuit=stim.Circuit.generated("surface_code:rotated_memory_z", distance=d, rounds=d,
            after_clifford_depolarization=p, after_reset_flip_probability=p,
            before_measure_flip_probability=p, before_round_data_depolarization=p),
         json_metadata={"d": d, "p": p, "r": d})
         for d in (3, 5, 7) for p in (0.001, 0.002, 0.003, 0.005, 0.007, 0.01)]
if __name__ == "__main__":          # mandatory: workers are spawned processes
    stats = sinter.collect(num_workers=24, tasks=tasks, decoders=["pymatching"], max_shots=5_000_000,
                           max_errors=500, save_resume_filepath="stats.csv", count_detection_events=True)
```

CLI equivalent (circuit files named `d=5,p=0.001,r=5.stim` so `--metadata_func auto` parses them):

```bash
sinter collect --circuits circuits/*.stim --decoders pymatching --max_shots 5_000_000 \
  --max_errors 500 --processes 24 --save_resume_filepath stats.csv --metadata_func auto
sinter plot --in stats.csv --x_func "metadata['p']" --group_func "metadata['d']" \
  --failure_units_per_shot_func "metadata['r']" --xaxis "[log]p" --yaxis "[log]per-round p_L" --out thr.png
```

Rerunning with the same resume file continues where it stopped. Aim for 100-1000 logical errors
per point; `max_shots` caps the cost at low p.

## 6. Analysis

```
per-round:  p_round = (1 - (1 - 2 p_shot)^(1/r)) / 2      sinter.shot_error_rate_to_piece_error_rate(p_shot, pieces=r)
interval:   fit = sinter.fit_binomial(num_shots=N, num_hits=k, max_likelihood_factor=1000)  -> fit.low, fit.best, fit.high
Lambda:     slope of ln p_L(d) vs d over >= 3 distances;  Lambda = exp(-2 * slope)
threshold:  crossing of the d curves (interpolate ln(p_L,7/p_L,3) vs ln p); report the bracketing grid points
```

`sinter.read_stats_from_csv_files("stats.csv")` reloads results; `sinter.plot_error_rate(ax=ax,
stats=stats, x_func=..., group_func=..., failure_units_per_shot_func=...)` draws them with intervals.
Zero errors at a point give only an upper bound (fit.high); never plot it as a value.

## 7. Debugging

```python
open("t.svg", "w").write(str(circuit.diagram("timeslice-svg")))   # gates per TICK
open("d.svg", "w").write(str(circuit.diagram("detslice-svg")))    # detector regions: wrong shapes = wrong detectors
open("m.svg", "w").write(str(circuit.diagram("matchgraph-svg")))  # decoding graph
assert len(circuit.shortest_graphlike_error()) == d                # circuit distance
errs = circuit.search_for_undetectable_logical_errors(dont_explore_detection_event_sets_with_size_above=4,
    dont_explore_edges_with_degree_above=4, dont_explore_edges_increasing_symptom_degree=False)
dets, obs = circuit.compile_detector_sampler(seed=7).sample(100_000, separate_observables=True)
pred = pymatching.Matching.from_detector_error_model(dem).decode_batch(dets)
print((pred != obs).any(axis=1).mean())                            # manual spot check
```

## 8. Custom circuits (new layouts, qLDPC schedules)

1. Noise off: `circuit.without_noise().compile_detector_sampler().sample(1000, separate_observables=True)`
   must return all zeros for detectors and observables.
2. `circuit.detector_error_model(decompose_errors=...)` must succeed without gauge options.
3. Inject single faults: `c2 = c[:k] + stim.Circuit("X_ERROR(1) 7") + c[k:]`; exactly the expected
   detectors fire; a full logical string flips the observable with no detector firing.
4. `shortest_graphlike_error()` (or the hyperedge search) equals the design distance.
Only then run a sweep.

## 9. Experimental data

```python
dets = stim.read_shot_data_file(path="detection_events.b8", format="b8", num_detectors=dem.num_detectors)
obs = stim.read_shot_data_file(path="obs_flips_actual.01", format="01", num_observables=dem.num_observables)
```

Decode with a DEM reweighted from calibration (per-gate p fitted to device data) or from detection
statistics; edge probability from detector correlations:

```
p_ij = 1/2 - 1/2 sqrt(1 - 4 (<x_i x_j> - <x_i><x_j>) / (1 - 2<x_i> - 2<x_j> + 4<x_i x_j>))
```

Compare with simulation at the fitted p; correlated matching usually helps on hardware data.

## 10. Performance

- One DEM per task, built once; `decode_batch` on whole arrays, never a Python loop per shot.
- Bit-packed sampling and decoding (`sample(..., bit_packed=True)`, `decode_batch(...,
  bit_packed_shots=True, bit_packed_predictions=True)`) for 1e8+ shots.
- Processes, not threads: `num_workers` ≈ physical cores; cap `max_shots` at low p.
- `count_detection_events=True` records the detection fraction: expect a few times p per detector;
  far off means the noise model or circuit is not what you think.

## 11. Worked example: rotated memory_z threshold and Λ

Section 5 sweep (uniform p on all four generator arguments, rounds = d, pymatching, 24 workers,
1.5 s wall). Per-round p_L with sinter's likelihood interval (factor 1000):

| p | d = 3 (shots / errors / p_L) | d = 5 | d = 7 | Λ fit |
|---|---|---|---|---|
| 0.001 | 854,835 / 648 / 2.53e-4 | 4,149,156 / 557 / 2.69e-5 | 5,000,000 / 101 / 2.89e-6 [1.95e-6, 4.09e-6] | 9.4 |
| 0.002 | 210,466 / 583 / 9.25e-4 | 588,868 / 608 / 2.07e-4 | 2,090,188 / 571 / 3.90e-5 | 4.9 |
| 0.003 | 72,977 / 505 / 2.32e-3 | 195,652 / 610 / 6.25e-4 | 400,998 / 576 / 2.06e-4 | 3.4 |
| 0.005 | 27,921 / 508 / 6.14e-3 | 58,163 / 782 / 2.72e-3 | 68,676 / 691 / 1.45e-3 | 2.1 |
| 0.007 | 15,633 / 502 / 1.09e-2 | 15,633 / 509 / 6.69e-3 | 21,026 / 731 / 5.12e-3 | 1.5 |
| 0.010 | 9,489 / 555 / 2.03e-2 | 6,417 / 530 / 1.77e-2 | 9,762 / 990 / 1.59e-2 | 1.1 |

No crossing up to 1%, so a second pass (5000 errors per point) refined it: Λ(5→7) = 1.013 at
p = 0.011 and 0.972 at 0.012; Λ(3→5) = 1.002 at 0.012. Threshold ≈ 1.1-1.2% for this model,
which has no idle noise on waiting qubits; SI1000 (section 2) is clearly worse at equal p
(Λ ≈ 2 already at p = 5e-3). At p = 0.001, Λ ≈ 9.4 ≈ p_th/p, as the scaling law predicts. The
d = 7, p = 0.001 point hit the 5e6-shot cap with 101 errors; its interval is ±40%, so quote it
with the interval or collect more.

## Pitfalls

- `decompose_errors=True` missing: PyMatching rejects hyperedges.
- Per-shot and per-round rates mixed, or different round counts across distances in one plot.
- Too few errors at low p: with 0 errors only `fit.high` is meaningful.
- Observable in the wrong basis: memory_x detects Z errors; a Z-only noise model on memory_z
  shows nothing.
- Thresholds quoted without the noise model and decoder (section 11's 1.1% is not SI1000's number).
- `sinter.collect` outside `if __name__ == "__main__":` re-executes the script in every worker.

Related: `stabilizer-codes-surface-code`, `quantum-resource-estimation`, `quantum-circuit-simulators`, hub `quantum-computing`
