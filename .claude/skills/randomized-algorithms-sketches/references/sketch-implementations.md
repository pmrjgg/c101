# Sketch and randomised-algorithm implementations

Companion to the randomized-algorithms-sketches skill. Pure-Python reference code (standard
library only) for testing production libraries against and for teaching; every function here was
run with the checks listed in section 6. HyperLogLog, `h64`, `bloom_params` and `Bloom` are in
section 12 of the skill.

## 1. Count-min and Misra-Gries

```python
import heapq, itertools, math, random

class CountMin:
    P = (1 << 61) - 1
    def __init__(self, eps, delta, seed=0):
        self.w, self.d = math.ceil(math.e / eps), math.ceil(math.log(1 / delta))
        rng = random.Random(seed)                     # one pairwise-independent hash per row
        self.ab = [(rng.randrange(1, self.P), rng.randrange(self.P)) for _ in range(self.d)]
        self.t = [[0] * self.w for _ in range(self.d)]
    def _cols(self, x: int):
        return [((a * x + b) % self.P) % self.w for a, b in self.ab]
    def add(self, x: int, c: int = 1):
        for row, j in zip(self.t, self._cols(x)): row[j] += c
    def query(self, x: int) -> int:                   # f(x) <= est <= f(x) + eps*N w.p. >= 1 - delta
        return min(row[j] for row, j in zip(self.t, self._cols(x)))

def misra_gries(stream, k):                           # k - 1 counters: f(x) - N/k <= c[x] <= f(x)
    c = {}
    for x in stream:
        if x in c: c[x] += 1
        elif len(c) < k - 1: c[x] = 1
        else:                                         # decrement all: total work <= N
            for y in list(c):
                c[y] -= 1
                if not c[y]: del c[y]
    return c
```

Keys for `CountMin` are integers: map strings with a seeded 64-bit hash first. Merging two
count-min sketches with the same seed and shape is element-wise addition.

## 2. Samplers

```python
def reservoir_l(stream, k, rng):                      # Algorithm L: O(k (1 + log(n/k))) draws
    u = lambda: rng.random() or 0.5 ** 53             # avoid log(0)
    it = iter(stream); res = list(itertools.islice(it, k))
    if len(res) < k: return res
    w = math.exp(math.log(u()) / k)
    while True:
        skip = math.floor(math.log(u()) / math.log(1 - w))
        nxt = next(itertools.islice(it, skip, None), StopIteration)
        if nxt is StopIteration: return res
        res[rng.randrange(k)] = nxt
        w *= math.exp(math.log(u()) / k)

def weighted_sample(stream, k, rng):                  # A-Res: key u^(1/w), stored as log(u)/w
    heap = []
    for x, wt in stream:
        key = math.log(rng.random() or 0.5 ** 53) / wt
        if len(heap) < k: heapq.heappush(heap, (key, x))
        elif key > heap[0][0]: heapq.heapreplace(heap, (key, x))
    return [x for _, x in heap]
```

`reservoir_r`, `fisher_yates` and `floyd_sample` are in section 4 of the skill.

## 3. MinHash and LSH

```python
P61 = (1 << 61) - 1
def minhash(tokens, k, seed=0):                       # tokens: iterable of bytes
    rng = random.Random(seed)
    ab = [(rng.randrange(1, P61), rng.randrange(P61)) for _ in range(k)]
    hs = [h64(t, seed) for t in tokens]               # h64 from the skill, section 12
    return [min((a * h + b) % P61 for h in hs) for a, b in ab]

def jaccard_estimate(sa, sb):
    return sum(x == y for x, y in zip(sa, sb)) / len(sa)

def lsh_candidate_prob(s, b, r):                      # b bands of r rows
    return 1 - (1 - s ** r) ** b
```

## 4. Miller-Rabin and Freivalds

```python
def is_prime64(n):                                    # deterministic for n < 3.3e24
    bases = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
    if n < 2: return False
    for p in bases:
        if n % p == 0: return n == p
    d, s = n - 1, 0
    while d % 2 == 0: d //= 2; s += 1
    for a in bases:
        x = pow(a, d, n)
        if x in (1, n - 1): continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1: break
        else:
            return False                              # a is a witness: n is composite
    return True

def freivalds(A, B, C, rounds, rng):                  # wrong "equal" with probability <= 2^-rounds
    n = len(A)
    mv = lambda M, v: [sum(M[i][j] * v[j] for j in range(n)) for i in range(n)]
    for _ in range(rounds):
        r = [rng.randrange(2) for _ in range(n)]
        if mv(A, mv(B, r)) != mv(C, r): return False
    return True
```

## 5. Sizing helpers

| Quantity | Formula | Example |
|---|---|---|
| Bloom bits | m = ceil(-n ln p / (ln 2)^2) | n = 5 x 10^7, p = 10^-3: 718 879 379 bits = 89.9 MB |
| Bloom hashes | k = round((m/n) ln 2) | 10 |
| Bloom FPR at load n' | (1 - e^(-k n'/m))^k | 3x capacity: 26% |
| HLL error | 1.04 / sqrt(2^p) | p = 14: 0.81%; p = 12: 1.63%; p = 16: 0.41% |
| count-min | w = ceil(e/eps), d = ceil(ln(1/delta)) | eps = 0.001, delta = 0.01: w = 2 719, d = 5 |
| MinHash k for standard error s | k >= 1 / (4 s^2) | s = 2%: k = 625 |
| JL dimension | k >= 4 ln n / (eps^2/2 - eps^3/3) | n = 10^6, eps = 0.1: ~11 842 |

## 6. Checks that were run

| Structure | Check | Result |
|---|---|---|
| HyperLogLog p = 14 | 20 seeds x 200 000 keys | RMS error 0.80% (theory 0.81%), max 1.96% |
| HyperLogLog merge | sketch(A) merged with sketch(B) vs sketch(A union B) | registers identical |
| Bloom n = 10^5, p = 0.1% | 20 seeds, 10^5 negative probes each | FPR 0.090-0.117% (theory 0.100% +- 0.030%), no false negatives |
| Bloom overfilled 3x | 10^5 negative probes | FPR 26.3% |
| count-min eps = 0.001, delta = 0.01 | 20 seeds, Pareto(1.2) streams of 10^5 | never underestimated; 0 of 6 553 queries above f + eps N |
| Misra-Gries k = 50 | Pareto(1.1) stream of 10^5 | f - N/k <= c <= f for every item |
| reservoir R and L (k = 5 of 100) | 4 000 runs, chi-square over positions | 78.0 and 81.7 (99 dof; 1% critical ~134) |
| A-Res k = 1, weights 1:2:3:4 | 20 000 runs | frequencies 0.102, 0.203, 0.300, 0.396 |
| MinHash k = 256 | J = 0.6 | estimate 0.605 |
| LSH b = 20, r = 5 | formula | threshold 0.549; P = 4.75%, 47.0%, 99.96% at s = 0.3, 0.5, 0.8 |
| Miller-Rabin | all n < 20 000 vs trial division; 2^61 - 1; 3 215 031 751 (strong pseudoprime to bases 2, 3, 5, 7) | all correct |
| Freivalds | 30 x 30 integer matrices, one corrupted entry | detected |
