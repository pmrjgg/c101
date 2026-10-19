# Classical shadows: estimator code, test run, sample complexity

Companion to section 4 of the `quantum-measurement-estimation` skill. The code is NumPy only, so the
estimator can be unit-tested on a statevector before any hardware data exists.

## Random Pauli shadows in one page

Per shot, pick a basis for every qubit uniformly from {X, Y, Z}, rotate (X: H; Y: S-dagger then H;
Z: nothing) and measure in Z. With outcome b_q in {0, 1} and basis U_q, the snapshot
rho_hat = tensor over q of (3 U_q^dagger |b_q><b_q| U_q - I) is an unbiased estimator of rho.

For a Pauli string P with support S (locality k = |S|), the single-snapshot estimate is

    v = product over q in S of [ 3 (1 - 2 b_q) * 1(basis_q == P_q) ]

so a snapshot contributes 3^k times the product of outcomes when every basis on the support matches,
and 0 otherwise. The single-snapshot variance is at most 3^k, which is the 3^k in the sample
complexity. Combine snapshots with a median of means (K batch means, then their median) for
guarantees across many observables at once.

## Code

```python
import numpy as np

H = np.array([[1, 1], [1, -1]]) / np.sqrt(2)
SDG = np.diag([1, -1j])
ROT = {0: H, 1: H @ SDG, 2: np.eye(2)}          # measure X, Y, Z: apply ROT then measure Z

def kron_all(ms):
    out = np.array([[1.0 + 0j]])
    for m in ms:
        out = np.kron(out, m)
    return out

def collect_shadows(psi, n, N, rng):
    """Simulated Pauli-basis snapshots of statevector psi (qubit 0 = most significant bit).
    Returns bases (N, n) with 0=X, 1=Y, 2=Z and bits (N, n)."""
    bases = rng.integers(0, 3, size=(N, n))
    bits = np.empty((N, n), dtype=np.int8)
    keys, inv = np.unique(bases, axis=0, return_inverse=True)
    inv = inv.reshape(-1)                         # NumPy versions differ in the inverse's shape
    for idx, b in enumerate(keys):
        rows = np.flatnonzero(inv == idx)
        p = np.abs(kron_all([ROT[int(x)] for x in b]) @ psi) ** 2
        outs = rng.choice(2 ** n, size=len(rows), p=p / p.sum())
        bits[rows] = (outs[:, None] >> np.arange(n - 1, -1, -1)) & 1
    return bases, bits

def shadow_expval(bases, bits, pauli, K=10):
    """pauli: {qubit: 'X' | 'Y' | 'Z'}. Returns (median of K batch means, standard error of the mean)."""
    code = {"X": 0, "Y": 1, "Z": 2}
    v = np.ones(len(bases))
    for q, P in pauli.items():
        v *= 3 * (1 - 2 * bits[:, q]) * (bases[:, q] == code[P])
    return float(np.median([b.mean() for b in np.array_split(v, K)])), float(v.std(ddof=1) / np.sqrt(len(v)))
```

On hardware, replace `collect_shadows` with one circuit per sampled basis setting (or one shot per
random setting when the device allows many settings cheaply): append the basis rotations before the
measurements, record the bases next to the bitstrings, and convert bitstrings to the same (N, n)
array with qubit 0 in column 0. Check the column order on a known state first: Qiskit bitstrings are
little-endian.

## Test run (measured)

GHZ-4 state (|0000> + |1111>)/sqrt(2), N = 20,000 snapshots, K = 10, seed 1:

| Observable | Exact | Shadow estimate | Standard error |
|---|---|---|---|
| Z0 Z1 | 1 | 0.9878 | 0.0199 |
| Z0 | 0 | -0.0097 | 0.0122 |
| X0 X1 X2 X3 | 1 | 1.0125 | 0.0629 |
| Y0 Y1 X2 X3 | -1 | -1.1138 | 0.0667 |

```python
n = 4
psi = np.zeros(2 ** n, complex); psi[0] = psi[-1] = 1 / np.sqrt(2)
bases, bits = collect_shadows(psi, n, 20000, np.random.default_rng(1))
print(shadow_expval(bases, bits, {0: "Z", 1: "Z"}))
print(shadow_expval(bases, bits, {0: "Y", 1: "Y", 2: "X", 3: "X"}))
```

All four agree with the exact values within 2 sigma (the YYXX estimate is 1.7 sigma off). The error
grows with weight as expected: about 0.02 at k = 2 and 0.06-0.07 at k = 4, a factor close to
sqrt(3^4 / 3^2) = 3. The exact values follow from the GHZ identity: the expectation of the product of
(cos phi_q X + sin phi_q Y) over all qubits equals cos(sum of phi_q), so YYXX gives cos(pi) = -1.

## Sample complexity and when shadows win

| Quantity | Pauli shadows | Direct measurement |
|---|---|---|
| M Pauli observables of locality k to precision eps | N about 3^k log(M/delta)/eps^2 (median of means) | about M/eps^2 without grouping; fewer when the observables group well |
| one global observable (k = n) | 3^n/eps^2: hopeless beyond about 10 qubits | 1/eps^2 |
| all 2-local correlators on n qubits (M about 9n^2/2) | about 9 log(M)/eps^2 for all of them together | settings from a strength-2 covering array over {X, Y, Z}: 9 suffice for n <= 4 and the number grows like log n; each needs about 1/eps^2 |
| fidelity with a pure target state | use Clifford shadows instead (variance set by the observable's Frobenius norm, needs deep random Clifford circuits) | direct fidelity estimation |

Decision rule: shadows win when many low-weight observables are not known in advance or do not
group into few settings; grouped direct measurement wins for a fixed, small or high-weight set.
Derandomised shadows (Huang, Kueng, Preskill 2021) pick the bases deterministically for a known
observable list and close most of the gap to optimal grouping; locally biased shadows (Hadfield
et al. 2022) bias the basis distribution towards a Hamiltonian's dominant terms.

## Pitfalls

- Using the plain mean instead of median of means when bounding many observables simultaneously.
- Forgetting the factor 3 per support qubit (estimates shrink towards 0 by 3^-k).
- Basis bookkeeping off by one qubit when bitstrings are little-endian.
- Quoting the shadow estimate of a high-weight observable without its 3^k-inflated error bar.
