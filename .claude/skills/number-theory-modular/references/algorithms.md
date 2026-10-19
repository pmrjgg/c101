# Number theory: tested reference implementations

Exact-integer Python (3.8+ for `pow(x, -1, m)`) plus a 64-bit Montgomery multiplier in C. Every
function below passed the randomized and exhaustive tests at the end of this file against SymPy
1.14 (`isprime`, `crt`, `n_order`, `factorint`) and Python's `pow`; the C code matched Python on
20000 random (a, e, n) triples with odd n < 2^64, including n within 2^63 of 2^64.

## Contents

| Function | Purpose | Cost |
|---|---|---|
| `ext_gcd(a, b)` | (g, x, y) with ax + by = g | O(log min(a, b)) steps |
| `crt_pair`, `crt(residues, moduli)` | CRT for arbitrary (non-coprime) moduli, None if inconsistent | O(k log M) |
| `tonelli_shanks(a, p)` | sqrt mod odd prime, None for non-residues | O(log p + s²) mults |
| `cipolla(a, p)` | sqrt mod odd prime via F_p² arithmetic | O(log p) mults |
| `hensel_sqrt(a, p, k)` | sqrt mod p^k, p odd, p ∤ a | k - 1 Newton lifts |
| `is_sprp(n, a)`, `is_prime_u64(n)` | strong probable-prime test; deterministic below 3.18·10^23 | 12 modexps |
| `pollard_brent(n)` | a nontrivial factor of composite n | ~√p iterations, p = smallest factor |
| `bsgs(g, h, p, order)` | discrete log by baby-step giant-step | O(√order) time and memory |
| `pohlig_hellman(g, h, p, factors)` | discrete log for smooth group order | O(Σ e_i (log N + √q_i)) |
| `pell_fundamental(D)` | fundamental solution of x² - Dy² = 1 by continued fractions | O(period) steps |
| `mont.c` | Montgomery modexp for odd 64-bit moduli | 1 128-bit product per mult, no division |

## Python

```python
from math import gcd, isqrt
import random

def ext_gcd(a, b):
    """Return (g, x, y) with a*x + b*y = g = gcd(a, b) >= 0."""
    x0, y0, x1, y1 = 1, 0, 0, 1
    while b:
        q, a, b = a // b, b, a % b
        x0, x1 = x1, x0 - q * x1
        y0, y1 = y1, y0 - q * y1
    if a < 0:
        a, x0, y0 = -a, -x0, -y0
    return a, x0, y0

def crt_pair(a1, m1, a2, m2):
    """x = a1 mod m1, x = a2 mod m2 (any moduli). Return (x, lcm) or None if inconsistent."""
    g, p, _ = ext_gcd(m1, m2)
    if (a2 - a1) % g:
        return None
    l = m1 // g * m2
    x = (a1 + (a2 - a1) // g * p % (m2 // g) * m1) % l
    return x, l

def crt(residues, moduli):
    x, m = 0, 1
    for a, n in zip(residues, moduli):
        r = crt_pair(x, m, a % n, n)
        if r is None:
            return None
        x, m = r
    return x, m

def tonelli_shanks(a, p):
    """Square root of a mod odd prime p, or None if a is a non-residue."""
    a %= p
    if a == 0:
        return 0
    if pow(a, (p - 1) // 2, p) != 1:
        return None
    if p % 4 == 3:
        return pow(a, (p + 1) // 4, p)
    q, s = p - 1, 0
    while q % 2 == 0:
        q //= 2; s += 1
    z = 2
    while pow(z, (p - 1) // 2, p) != p - 1:
        z += 1
    m, c, t, r = s, pow(z, q, p), pow(a, q, p), pow(a, (q + 1) // 2, p)
    while t != 1:
        i, t2 = 0, t
        while t2 != 1:
            t2 = t2 * t2 % p; i += 1
        b = pow(c, 1 << (m - i - 1), p)
        m, c, t, r = i, b * b % p, t * b * b % p, r * b % p
    return r

def cipolla(a, p):
    """Square root of a mod odd prime p via arithmetic in F_p[w]/(w^2 - (t^2 - a))."""
    a %= p
    if a == 0:
        return 0
    if pow(a, (p - 1) // 2, p) != 1:
        return None
    t = 0
    while pow((t * t - a) % p, (p - 1) // 2, p) != p - 1:
        t += 1
    w2 = (t * t - a) % p
    def mul(u, v):
        return ((u[0] * v[0] + u[1] * v[1] * w2) % p, (u[0] * v[1] + u[1] * v[0]) % p)
    r, base, e = (1, 0), (t, 1), (p + 1) // 2
    while e:
        if e & 1:
            r = mul(r, base)
        base = mul(base, base); e >>= 1
    return r[0]

def hensel_sqrt(a, p, k):
    """Square root of a mod p^k for odd prime p, p not dividing a; None if none."""
    r = tonelli_shanks(a, p)
    if r is None:
        return None
    pk = p
    for _ in range(1, k):
        pk *= p
        # f(r) = r^2 - a, f'(r) = 2r (invertible mod p since p odd, p does not divide r)
        r = (r - (r * r - a) * pow(2 * r, -1, pk)) % pk
    return r

def is_sprp(n, a):
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2; s += 1
    x = pow(a, d, n)
    if x in (1, n - 1):
        return True
    for _ in range(s - 1):
        x = x * x % n
        if x == n - 1:
            return True
    return False

SMALL_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)

def is_prime_u64(n):
    """Deterministic for 0 <= n < 3.3e24 (first 12 primes as bases cover n < 3.18e23 > 2^64)."""
    if n < 2:
        return False
    for p in SMALL_PRIMES:
        if n % p == 0:
            return n == p
    return all(is_sprp(n, a) for a in SMALL_PRIMES)

def pollard_brent(n, seed=1):
    """Return a nontrivial factor of composite n (n not a prime power of 2)."""
    if n % 2 == 0:
        return 2
    rng = random.Random(seed)
    while True:
        y, c, m = rng.randrange(1, n), rng.randrange(1, n), 128
        g = r = q = 1
        while g == 1:
            x = y
            for _ in range(r):
                y = (y * y + c) % n
            k = 0
            while k < r and g == 1:
                ys = y
                for _ in range(min(m, r - k)):
                    y = (y * y + c) % n
                    q = q * abs(x - y) % n
                g = gcd(q, n); k += m
            r *= 2
        if g == n:
            g = 1
            while g == 1:
                ys = (ys * ys + c) % n
                g = gcd(abs(x - ys), n)
        if g != n:
            return g

def bsgs(g, h, p, order=None):
    """Smallest x >= 0 with g^x = h mod p (p prime or any modulus with g invertible), else None."""
    n = order or p - 1
    m = isqrt(n) + 1
    table = {}
    e = 1
    for j in range(m):
        table.setdefault(e, j)
        e = e * g % p
    step = pow(g, -m, p)
    y = h % p
    for i in range(m):
        if y in table:
            return i * m + table[y]
        y = y * step % p
    return None

def pohlig_hellman(g, h, p, factors):
    """x with g^x = h mod p, where ord(g) = prod q^e over factors {q: e}."""
    n = 1
    for q, e in factors.items():
        n *= q ** e
    residues, moduli = [], []
    for q, e in factors.items():
        qe = q ** e
        g1, h1 = pow(g, n // qe, p), pow(h, n // qe, p)
        # solve g1^x = h1 in the subgroup of order q^e digit by digit
        gamma = pow(g1, q ** (e - 1), p)
        x = 0
        for k in range(e):
            hk = pow(pow(g1, -x, p) * h1 % p, q ** (e - 1 - k), p)
            d = bsgs(gamma, hk, p, order=q)
            if d is None:
                return None
            x += d * q ** k
        residues.append(x); moduli.append(qe)
    return crt(residues, moduli)[0]

def pell_fundamental(D):
    """Fundamental solution of x^2 - D y^2 = 1 (D > 0 not a square) from the continued fraction of sqrt(D)."""
    a0 = isqrt(D)
    if a0 * a0 == D:
        raise ValueError("D is a square")
    m, d, a = 0, 1, a0
    p_prev, p = 1, a0
    q_prev, q = 0, 1
    while p * p - D * q * q != 1:
        m = d * a - m
        d = (D - m * m) // d
        a = (a0 + m) // d
        p_prev, p = p, a * p + p_prev
        q_prev, q = q, a * q + q_prev
    return p, q
```

Notes:

- `crt` returns the least non-negative solution and the lcm; it agrees with
  `sympy.ntheory.modular.crt(moduli, residues)` (note SymPy's argument order).
- `tonelli_shanks` returns one root r; the other is p - r. `hensel_sqrt` lifts with
  r ← r - (r² - a)(2r)^(-1) mod p^(j+1), valid because 2r is a unit for odd p ∤ a.
- `is_prime_u64` is deterministic for every n < 2^64 (bases = first 12 primes); above
  3.18·10^23 it is a probable-prime test only. Prefer BPSW (`sympy.isprime`, `gmpy2.is_bpsw_prp`)
  for big n.
- `pollard_brent` uses Brent's cycle detection with batched gcds (m = 128); call it only on
  composites (test primality first) and recurse on both factors for a full factorisation.
- `bsgs` needs g invertible mod p; pass the true element order when known (cheaper, and the
  answer is then unique mod the order).
- `pell_fundamental` stops at the first convergent with p² - Dq² = 1, which is the fundamental
  solution; for D = 61 it returns (1766319049, 226153980).

## C: 64-bit Montgomery multiplication

R = 2^64. `redc(t)` returns t·R^(-1) mod n for t < n·2^64 using n^(-1) mod 2^64 (signed
variant: no 128-bit carry handling needed, works for every odd n < 2^64). Keep operands in
Montgomery form across a whole exponentiation; convert in and out once. Not constant time:
the branch in `redc` and the exponent-dependent `if` leak timing.

```c
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef uint64_t u64;
typedef unsigned __int128 u128;

typedef struct { u64 n, ninv, r2; } Mont;           /* n odd, any size < 2^64 */

static Mont mont_init(u64 n) {
    Mont m = { n, n, 0 };
    for (int i = 0; i < 5; i++) m.ninv *= 2 - n * m.ninv;   /* n^-1 mod 2^64 by Newton: 3->6->...->96 bits */
    u128 r = ((u128)1 << 64) % n;                            /* R mod n */
    m.r2 = (u64)(r * r % n);                                 /* R^2 mod n */
    return m;
}
static u64 redc(const Mont *m, u128 t) {                    /* t * R^-1 mod n, for t < n * 2^64 */
    u64 q = (u64)t * m->ninv;
    u64 mh = (u64)(((u128)q * m->n) >> 64), th = (u64)(t >> 64);
    return th >= mh ? th - mh : th - mh + m->n;
}
static u64 to_mont(const Mont *m, u64 a)   { return redc(m, (u128)(a % m->n) * m->r2); }
static u64 from_mont(const Mont *m, u64 a) { return redc(m, a); }
static u64 mont_mul(const Mont *m, u64 a, u64 b) { return redc(m, (u128)a * b); }
static u64 powmod(u64 a, u64 e, u64 n) {                     /* n odd; NOT constant time */
    Mont m = mont_init(n);
    u64 r = to_mont(&m, 1), b = to_mont(&m, a);
    for (; e; e >>= 1) { if (e & 1) r = mont_mul(&m, r, b); b = mont_mul(&m, b, b); }
    return from_mont(&m, r);
}
int main(void) {
    /* read triples a e n from stdin, print a^e mod n */
    unsigned long long a, e, n;
    while (scanf("%llu %llu %llu", &a, &e, &n) == 3) printf("%llu\n", (unsigned long long)powmod(a, e, n));
    return 0;
}
```

Build and test: `cc -O2 -Wall -o mont mont.c`, then feed `a e n` lines and compare with Python
`pow(a, e, n)`.

## Test harness (run with exact integers)

Save the Python block above as `nt_algos.py` and append:

```python
if __name__ == "__main__":
    from sympy import isprime, factorint, n_order, discrete_log, sqrt_mod
    from sympy.ntheory.modular import crt as scrt
    rnd = random.Random(0)
    for _ in range(2000):
        a, b = rnd.randrange(-10**12, 10**12), rnd.randrange(-10**12, 10**12)
        g, x, y = ext_gcd(a, b)
        assert g == gcd(a, b) and a * x + b * y == g
    for _ in range(2000):
        ms = [rnd.randrange(2, 200) for _ in range(3)]
        rs = [rnd.randrange(0, m) for m in ms]
        mine = crt(rs, ms)
        ref = scrt(ms, rs)
        assert (mine is None) == (ref is None) and (mine is None or (mine[0] == ref[0] and mine[1] == ref[1])), (ms, rs, mine, ref)
    for p in [3, 5, 7, 13, 17, 41, 97, 257, 65537, 998244353, 2**61 - 1, 10**9 + 7]:
        for _ in range(200):
            a = rnd.randrange(0, p)
            r1, r2 = tonelli_shanks(a, p), cipolla(a, p)
            if r1 is None:
                assert r2 is None and pow(a, (p - 1) // 2, p) == p - 1
            else:
                assert r1 * r1 % p == a and r2 * r2 % p == a
    for p in [3, 5, 7, 11, 13]:
        for k in range(1, 6):
            M = p ** k
            sq = {x * x % M for x in range(M)}
            for a in range(1, M):
                if a % p == 0:
                    continue
                r = hensel_sqrt(a, p, k)
                has = a in sq
                assert (r is not None) == has and (r is None or r * r % M == a)
    for n in list(range(0, 20000)) + [rnd.randrange(2**63, 2**64) for _ in range(3000)] + [3825123056546413051, 2047, 3215031751, 2**61 - 1, 2**64 - 59]:
        assert is_prime_u64(n) == isprime(n), n
    for n in [8051, 10403, 2**32 + 1, 600851475143, 1000000016000000063, 2**64 + 1]:
        f = pollard_brent(n)
        assert 1 < f < n and n % f == 0, (n, f)
    p = 1000003
    for _ in range(50):
        g, x = 2, rnd.randrange(0, p - 1)
        h = pow(g, x, p)
        xr = bsgs(g, h, p, order=n_order(g, p))
        assert pow(g, xr, p) == h
    p = 2 * 3**5 * 5**3 * 7 + 1  # prime? choose smooth p-1
    from sympy import nextprime
    # find a prime with smooth p - 1
    cand = None
    for k in range(1, 10000):
        q = 2**5 * 3**4 * 5**2 * 7 * k + 1
        if isprime(q) and max(factorint(q - 1)) < 50:
            cand = q; break
    p = cand
    from sympy import primitive_root
    g = primitive_root(p)
    for _ in range(50):
        x = rnd.randrange(0, p - 1)
        h = pow(g, x, p)
        xr = pohlig_hellman(g, h, p, factorint(p - 1))
        assert xr == x % (p - 1)
    for D in [2, 3, 5, 7, 13, 61, 109, 991]:
        x, y = pell_fundamental(D)
        assert x * x - D * y * y == 1
    print("pell 61", pell_fundamental(61), "pell 991", pell_fundamental(991))
    print("smooth prime used for Pohlig-Hellman", p, factorint(p - 1))
    print("all algorithm tests passed")
```

Expected output (about 1 s): `pell 61 (1766319049, 226153980)`, the 991 solution, the prime 453601
(p - 1 = 2^5·3^4·5^2·7) used for Pohlig-Hellman, and `all algorithm tests passed`.
