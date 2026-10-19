---
name: randomized-algorithms-sketches
description: "Randomised algorithms and probabilistic data structures: Las Vegas vs Monte Carlo, amplification, tail bounds (Markov, Chebyshev, Chernoff, Hoeffding, union, birthday), hash families, sampling, sketches (Bloom/cuckoo/binary fuse, count-min, HyperLogLog, KLL/t-digest, MinHash/LSH, JL) with sizing formulas, classic randomised algorithms, reproducible RNGs. Load when designing with randomness, sizing a sketch, or bounding a failure probability."
when_to_use: "Sizing a Bloom/cuckoo filter, HyperLogLog, count-min or quantile sketch; distinct counts, heavy hitters or percentiles over streams too big to store; near-duplicate detection; sampling from streams or huge ranges; 'what is the probability this fails'; primality or matrix-product checks; seeding RNGs for reproducible parallel runs; tokens generated with random or Math.random."
---

# Randomised algorithms and sketches

Randomness with stated failure probabilities, sketches with sizing formulas, and seeds you can
replay. Full distribution facts are in `probability-distributions-limits`; expected-cost proofs in
`amortized-recurrence-analysis`; hub `cs-foundations` section 5. Tested implementations of every
structure below: [sketch implementations](references/sketch-implementations.md).

## 1. Error types and amplification

| Type | Guarantee | Example | Amplify |
|---|---|---|---|
| Las Vegas | always correct, random running time | randomised quicksort, treaps | stop at c x E[T]: fails with prob <= 1/c (Markov), giving Monte Carlo |
| Monte Carlo, one-sided | "no" answers always right (or "yes") | Miller-Rabin (composite is certain), Freivalds | k independent runs: error <= eps^k (2^-k for eps = 1/2) |
| Monte Carlo, two-sided | error <= 1/3 either way | BPP algorithms | majority of k runs: error <= exp(-k/18) by Hoeffding, so k = ceil(18 ln(1/delta)) |

Monte Carlo becomes Las Vegas when answers are verifiable: repeat until the check passes
(expected 1/p runs for success probability p).

## 2. Tail-bound cheat sheet

| Bound | Statement | Requires |
|---|---|---|
| Markov | P(X >= a) <= E[X] / a | X >= 0 |
| Chebyshev | P(abs(X - mu) >= t sigma) <= 1 / t^2 | finite variance; pairwise independence suffices for sums |
| Chernoff, upper | P(X >= (1 + d) mu) <= exp(-d^2 mu / 3), 0 < d <= 1 | X a sum of independent variables in [0, 1], mu = E[X] |
| Chernoff, lower | P(X <= (1 - d) mu) <= exp(-d^2 mu / 2), 0 < d < 1 | same |
| Hoeffding | P(abs(mean - E[mean]) >= t) <= 2 exp(-2 n t^2 / (b - a)^2) | n independent variables in [a, b] |
| union bound | P(A_1 or ... or A_k) <= sum P(A_i) | nothing |
| birthday | n keys in m slots: expected colliding pairs n(n - 1) / (2m) ~ n^2 / (2m) | uniform hashing; 50% collision at n ~ 1.18 sqrt(m) |
| coupon collector | all n coupons after n H_n ~ n ln n draws; P(> n ln n + cn) <= e^-c | uniform draws |

Conditions and further inequalities (Bernstein, Azuma, bounded differences) are in
`probability-distributions-limits`.

## 3. Hashing for algorithms

| Family / hash | Property | Use |
|---|---|---|
| ((a x + b) mod p) mod m, p prime, a in [1, p), b in [0, p) | universal: P(collision) <= 1/m | hash tables, count-min rows |
| multiply-shift: (a x mod 2^w) >> (w - l), a odd | approximately universal: P(collision) <= 2 / 2^l | fast integer hashing |
| (a x + b) mod p, a, b uniform | pairwise independent | count-min (pairwise suffices), Chebyshev arguments |
| 5-independent polynomials or simple tabulation | expected O(1) linear probing | open addressing analyses (some 4-independent families fail) |
| xxh3, wyhash / rapidhash | fast, good distribution, not keyed for security | trusted keys, checksums, sketches |
| SipHash (keyed) | DoS resistant with a secret key | untrusted keys (HashDoS) |

Bloom filters need k hashes: derive them as g_i(x) = h1(x) + i h2(x) mod m from one 128-bit hash
(Kirsch-Mitzenmacher); the false-positive rate is asymptotically unchanged.

## 4. Sampling

```python
def reservoir_r(stream, k, rng):            # uniform k-sample of a stream, one pass, O(k) memory
    res = []
    for i, x in enumerate(stream):
        if i < k: res.append(x)
        else:
            j = rng.randrange(i + 1)
            if j < k: res[j] = x
    return res

def fisher_yates(a, rng):                   # uniform shuffle in place
    for i in range(len(a) - 1, 0, -1):
        j = rng.randrange(i + 1); a[i], a[j] = a[j], a[i]

def floyd_sample(n, k, rng):                # k distinct values from range(n), O(k), no range materialised
    s = set()
    for j in range(n - k, n):
        t = rng.randrange(j + 1)
        s.add(j if t in s else t)
    return s
```

- **Algorithm L** skips ahead geometrically: O(k (1 + log(n/k))) random draws instead of n.
- **Weighted (A-Res, Efraimidis-Spirakis)**: key u^(1/w) per item, keep the k largest keys (use
  log(u) / w to avoid underflow).
- **Priority sampling** for subset-sum estimation, **stratified** sampling when strata sizes are
  known (variance drops by the between-strata share).
- Sorting with a random comparator (`sort(() => Math.random() - 0.5)`) is biased and can break
  sort invariants; use Fisher-Yates.

## 5. Membership filters

| Filter | Bits per key at FPR p | Deletes | Notes |
|---|---|---|---|
| Bloom | m/n = -ln p / (ln 2)^2 = 1.44 log2(1/p): 9.6 at 1%, 14.4 at 0.1% | no | k = (m/n) ln 2 hashes (7 at 1%, 10 at 0.1%); k random memory accesses |
| blocked Bloom | slightly more than Bloom for the same p | no | one cache line per query: much faster |
| counting Bloom | ~4x Bloom (4-bit counters) | yes | counter overflow must saturate |
| cuckoo filter | ~(log2(1/p) + 3) / 0.955 | yes | smaller than Bloom below ~0.4% FPR (~3% with semi-sorting); inserts can fail near full |
| quotient filter | similar to cuckoo | yes | mergeable, resizable, cache friendly |
| XOR / binary fuse | ~1.23 / ~1.13 x log2(1/p) | no (static) | built once from the full key set |

The FPR is (1 - e^(-kn/m))^k: past the design capacity it explodes (measured below: 0.1% design
FPR becomes 26% at 3x capacity). Plan rotation or scalable filters up front.

## 6. Counting and quantiles

| Sketch | Error | Space | Notes |
|---|---|---|---|
| HyperLogLog / HLL++ | standard error 1.04 / sqrt(m) | m registers of 6 bits: m = 2^14 is 12 KB for 0.81% | HLL++: 64-bit hash, sparse mode for small sets, empirical small-range bias correction; merge = register-wise max (same p and hash) |
| count-min | f <= est <= f + eps N with prob >= 1 - delta | w = ceil(e / eps), d = ceil(ln(1 / delta)) counters | non-negative updates; conservative update helps in practice |
| count sketch | abs(est - f) <= eps norm2(f) | O(1/eps^2 x log(1/delta)) | signed updates, unbiased, median of rows |
| Misra-Gries / Space-Saving | error <= N/k with k counters | k counters | deterministic heavy hitters: every item above N/k is kept |
| KLL | rank error eps | ~O((1/eps) log log(1/delta)) | mergeable, worst-case guarantees (DataSketches default k = 200 documents ~1.65% normalised rank error) |
| t-digest | small relative error at the tails in practice | ~compression parameter centroids | good p99/p99.9, no worst-case bound; REQ sketch when tail guarantees are needed |

Libraries: Apache DataSketches (Java, C++, Python: HLL, CPC, theta, KLL, REQ, frequent items),
Redis 8 (HyperLogLog `PFADD/PFCOUNT/PFMERGE` plus built-in Bloom, cuckoo, count-min, top-k and
t-digest types), ClickHouse `uniq`, `uniqCombined`, `uniqHLL12`, `uniqTheta`, PostgreSQL `hll`
extension.

## 7. Similarity and dimension reduction

- **MinHash**: P(min-hashes agree) = Jaccard J; with k hashes the estimate has standard error
  sqrt(J(1 - J)/k) <= 1/(2 sqrt k) (k = 256: <= 3.1%).
- **LSH banding**: b bands of r rows; P(candidate) = 1 - (1 - s^r)^b, an S-curve with threshold
  ~(1/b)^(1/r). b = 20, r = 5: threshold 0.549; candidate probability 4.75% at s = 0.3, 47% at
  0.5, 99.96% at 0.8.
- **SimHash** (random hyperplanes) for cosine similarity: P(bit agrees) = 1 - theta/pi.
- **Johnson-Lindenstrauss**: k >= 4 ln n / (eps^2/2 - eps^3/3) dimensions preserve all pairwise
  distances within 1 +- eps (n = 10^6, eps = 0.1: k >= ~11 842; sparse or fast JL transforms
  for speed).
- Python: `datasketch` (MinHash, MinHashLSH with a Jaccard threshold). Always verify exact
  similarity on candidate pairs: LSH only proposes.

## 8. Classic randomised algorithms

| Algorithm | Guarantee |
|---|---|
| quickselect / quicksort, random pivot | expected O(n) / O(n log n); introselect for a worst-case fallback |
| Karger min-cut | one contraction run succeeds with prob >= 1 / C(n, 2); C(n, 2) ln n runs fail with prob <= 1/n; Karger-Stein O(n^2 log^3 n) total |
| Miller-Rabin | deterministic for n < 3.3 x 10^24 (covers 64 bits) with bases 2, 3, 5, ..., 37 (first 12 primes) |
| Freivalds (check A B = C) | O(n^2) per round, false "equal" with prob <= 1/2 per round |
| Schwartz-Zippel (polynomial identity) | non-zero polynomial of degree d is zero at a random point of S^n with prob <= d / abs(S) |
| treaps, skip lists | O(log n) expected and with high probability |
| randomised rounding of LPs | set cover O(log n) approximation; MAX-SAT (1 - 1/e) |

Number-theoretic background for Miller-Rabin is in `number-theory-modular`.

## 9. RNG engineering

```python
import numpy as np, secrets
ss = np.random.SeedSequence(20261019)                # log the seed with every result
rngs = [np.random.default_rng(s) for s in ss.spawn(8)]   # independent PCG64 streams per worker
token = secrets.token_urlsafe(32)                    # security tokens: OS CSPRNG only
```

- Seed and log every run; derive per-worker streams with `SeedSequence.spawn` instead of
  seed + i. For simulation PCG64 or xoshiro256**; never `random`, `Math.random` or
  `rand()` for tokens, keys, nonces or password resets.
- Expected bounds assume the adversary does not know the coins. A fixed, logged or leaked seed
  lets an adaptive adversary build worst cases (hash flooding, Bloom pollution, quicksort
  killers); use secret per-process seeds for anything facing untrusted input.

## 10. Validation

- Run each sketch over >= 20 seeds and compare the empirical error distribution (RMS, max) with
  the theoretical bound; one lucky seed proves nothing.
- Test merges: merging sketches of parts must equal (HLL: register-for-register) or match the
  sketch of the whole; parameters and seeds must agree.
- Property tests: a Bloom filter never returns a false negative; count-min never underestimates;
  a reservoir is uniform (chi-square over many runs).

## 11. Pitfalls

- Merging sketches built with different p, hash functions or seeds: silently wrong numbers.
- Python's built-in `hash()` of `str` is randomised per process: sketches persisted or merged
  across processes need an explicit seeded hash (BLAKE2b, xxh3).
- Deriving "independent" hashes as `h(x) mod m1`, `h(x) mod m2`: correlated, not independent.
- Bloom filters run past design capacity; count-min on rare items in heavy-tailed streams
  (overestimates of ~eps N dwarf small counts).
- Point estimates reported without the error band and failure probability.

## 12. Worked example: 500M events per day

Requirements: daily distinct users and a "seen before" check on event IDs.

**Distinct counts.** One HLL with p = 14 per hour (16 384 registers, 12 KB packed), merged
register-wise into daily (and weekly) counts. Error does not grow with merging: the merged sketch
equals the sketch of the union. Standard error 1.04/128 = 0.81%, so ~95% of days within +-1.6%.

**Seen-before filter.** 50M distinct IDs per rotation window at 0.1% FPR:
m = ceil(-50e6 ln(0.001) / (ln 2)^2) = 718 879 379 bits = 89.9 MB, k = round(14.38 x 0.693) = 10.

```python
import hashlib, math
def h64(data: bytes, seed: int = 0) -> int:
    return int.from_bytes(hashlib.blake2b(data, digest_size=8,
                          salt=seed.to_bytes(16, "little")).digest(), "little")

class HyperLogLog:
    def __init__(self, p=14, seed=0):
        self.p, self.m, self.seed, self.reg = p, 1 << p, seed, bytearray(1 << p)
    def add(self, item: bytes):
        x = h64(item, self.seed)
        j, w = x >> (64 - self.p), x & ((1 << (64 - self.p)) - 1)
        rank = (64 - self.p) - w.bit_length() + 1      # leading zeros + 1
        if rank > self.reg[j]: self.reg[j] = rank
    def merge(self, other):
        assert (self.p, self.seed) == (other.p, other.seed)
        self.reg = bytearray(map(max, self.reg, other.reg))
    def estimate(self):
        m = self.m
        e = 0.7213 / (1 + 1.079 / m) * m * m / sum(2.0 ** -r for r in self.reg)
        zeros = self.reg.count(0)
        return m * math.log(m / zeros) if e <= 2.5 * m and zeros else e  # linear counting

def bloom_params(n, p):
    m = math.ceil(-n * math.log(p) / math.log(2) ** 2)
    return m, max(1, round(m / n * math.log(2)))

class Bloom:
    def __init__(self, n, p, seed=0):
        self.m, self.k = bloom_params(n, p)
        self.salt, self.bits = seed.to_bytes(16, "little"), bytearray((self.m + 7) // 8)
    def _idx(self, item: bytes):
        d = hashlib.blake2b(item, digest_size=16, salt=self.salt).digest()
        h1, h2 = int.from_bytes(d[:8], "little"), int.from_bytes(d[8:], "little") | 1
        return [(h1 + i * h2) % self.m for i in range(self.k)]   # Kirsch-Mitzenmacher
    def add(self, item: bytes):
        for i in self._idx(item): self.bits[i >> 3] |= 1 << (i & 7)
    def __contains__(self, item: bytes):
        return all(self.bits[i >> 3] >> (i & 7) & 1 for i in self._idx(item))
```

Validation run for this skill (CPython, 20 seeds each):
- HLL p = 14 on 200 000 distinct keys: RMS relative error 0.80% (theory 0.81%), worst seed
  1.96%; merging sketches of two overlapping sets reproduced the union sketch exactly; 1 000
  keys (small range, linear counting) estimated 997.8.
- Bloom scaled to n = 10^5 at 0.1% (m = 1 437 759, k = 10), 10^5 non-member probes per seed:
  FPR mean 0.105%, range 0.090-0.117%, inside the predicted 0.100% +- 0.030% (3 sigma); no
  false negatives. Loading the same filter with 3x its design capacity raised the FPR to 26.3%.

Operations: rotate the seen-before filter per window (current plus previous filter, query both)
or use a scalable Bloom filter whose stages tighten the FPR; alert when the inserted count passes
the design n. 500M events/day is ~5 800/s on average: a C/Rust/Java implementation or Redis 8's
built-in Bloom type handles 10x peaks on one core; pure Python is reference code only.

Related: `probability-distributions-limits`, `amortized-recurrence-analysis`, `data-structure-selection`, `string-algorithms`, `number-theory-modular`, `algorithm-design-paradigms`, hub `cs-foundations`
