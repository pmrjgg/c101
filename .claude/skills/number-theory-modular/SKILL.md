---
name: number-theory-modular
description: "Elementary and computational number theory: divisibility and Bezout, modular arithmetic, CRT, Euler/Fermat/Carmichael, orders and primitive roots, quadratic residues and square roots mod n, p-adic valuations and LTE, Diophantine techniques, multiplicative functions, primality and factoring tools, and pitfalls when implementing them. Load when solving congruences or integer equations, or when writing or reviewing modular-arithmetic code."
when_to_use: "Congruences and CRT systems, modular inverses, orders and primitive roots, Legendre/Jacobi symbols, square roots mod p or p^k, v_p(n!) or LTE, Pell and other Diophantine equations, divisor-sum identities, primality tests, factoring, discrete logs (BSGS, Pohlig-Hellman, Shor), and C/C++/Rust/Go/Java/Python code using % or pow(a, b, m): negative remainders, a*b mod m overflow, modulo bias, non-constant-time modexp."
---

# Number theory and modular arithmetic

Baseline (checked October 2026): CPython 3.13 ints, SymPy 1.14, gmpy2 2.3, python-flint 0.9.
Every fact below is stated with its hypotheses; most identities were re-checked exhaustively
over small ranges with exact integers. Use the status labels of hub `mathematics-toolkit`
(Proved / Known / Verified for finite range / Numerical evidence / False).
Tested implementations (extended Euclid, general CRT, Tonelli-Shanks, Cipolla, Hensel, Miller-Rabin,
Pollard-Brent, BSGS, Pohlig-Hellman, Pell, 64-bit Montgomery in C): [algorithms](references/algorithms.md).

## 1. Core facts with hypotheses

| Fact | Statement | Hypotheses / failure mode |
|---|---|---|
| Bezout | ax + by = g = gcd(a, b) has integer solutions; all are (x + k b/g, y - k a/g) | a, b not both 0 |
| Linear congruence | ax ≡ c (mod m) solvable iff g = gcd(a, m) divides c; then g solutions mod m | inverse exists iff g = 1 |
| CRT (coprime) | x ≡ a_i (mod m_i) has a unique solution mod M = Π m_i | m_i pairwise coprime |
| CRT (general) | solvable iff a_i ≡ a_j (mod gcd(m_i, m_j)) for all i, j; unique mod lcm(m_i) | check consistency before combining |
| Fermat | a^(p-1) ≡ 1 (mod p); a^p ≡ a for every a | p prime, p ∤ a for the first form |
| Euler | a^φ(n) ≡ 1 (mod n), φ(n) = n Π_{p\|n} (1 - 1/p) | gcd(a, n) = 1 (2^φ(4) = 4 ≡ 0 mod 4) |
| Carmichael λ | a^λ(n) ≡ 1 for every unit a; λ is the exponent of (Z/n)^× | λ(2) = 1, λ(4) = 2, λ(2^k) = 2^(k-2) (k ≥ 3), λ(p^k) = p^(k-1)(p-1), λ(lcm) = lcm of parts |
| Wilson | (n-1)! ≡ -1 (mod n) iff n is prime | n > 1; (n-1)! ≡ 0 (mod n) for composite n > 4 |
| Orders | a^m ≡ 1 iff ord_n(a) \| m; ord_n(a) \| λ(n) \| φ(n); ord(a^j) = ord(a)/gcd(j, ord(a)) | gcd(a, n) = 1 |
| Primitive roots | exist iff n ∈ {1, 2, 4, p^k, 2p^k}, p odd prime; there are φ(φ(n)) of them | none mod 8 or mod 15 |
| Primitive-root test | g generates (Z/p)^× iff g^((p-1)/q) ≢ 1 (mod p) for every prime q \| p - 1 | needs the factorisation of p - 1 |
| Lift to p^k | a primitive root g mod p is one mod every p^k iff g^(p-1) ≢ 1 (mod p²); otherwise g + p is | p odd |
| Exponent reduction | a^e ≡ a^(e mod φ(n)) only for gcd(a, n) = 1; in general a^e ≡ a^(e mod φ(n) + φ(n)) for e ≥ log2 n | the coprime-only form is a classic bug |

```python
def ext_gcd(a, b):                      # returns (g, x, y), a*x + b*y = g >= 0
    x0, y0, x1, y1 = 1, 0, 0, 1
    while b:
        q, a, b = a // b, b, a % b
        x0, x1, y0, y1 = x1, x0 - q * x1, y1, y0 - q * y1
    return (a, x0, y0) if a >= 0 else (-a, -x0, -y0)
```

Checked: λ formula = `reduced_totient` = max element order for n < 600; Wilson for n < 500; the
primitive-root existence list for n < 400.

## 2. Quadratic residues and square roots

| Tool | Statement | Hypotheses |
|---|---|---|
| Euler's criterion | a^((p-1)/2) ≡ (a/p) (mod p) | p odd prime |
| Legendre symbol | (ab/p) = (a/p)(b/p); depends on a mod p only | p odd prime |
| Reciprocity | (p/q)(q/p) = (-1)^(((p-1)/2)((q-1)/2)) | p ≠ q odd primes; holds for Jacobi symbols of odd coprime m, n > 0 |
| First supplement | (-1/p) = (-1)^((p-1)/2): 1 iff p ≡ 1 (mod 4) | p odd prime |
| Second supplement | (2/p) = (-1)^((p²-1)/8): 1 iff p ≡ ±1 (mod 8) | p odd prime |
| Jacobi symbol | (a/n) = Π (a/p_i)^(e_i); computed like gcd in O(log² n) without factoring | n odd, positive |
| Jacobi trap | (a/n) = -1 ⇒ non-residue, but (a/n) = 1 does NOT imply a residue | (2/15) = 1 yet x² ≡ 2 (mod 15) has no root |

Square roots mod an odd prime p (all formulas verified for every p < 20000 in the class):

| Case | Root of x² ≡ a | Cost |
|---|---|---|
| p ≡ 3 (mod 4) | x = a^((p+1)/4) | one exponentiation |
| p ≡ 5 (mod 8) (Atkin) | v = (2a)^((p-5)/8), i = 2av², x = av(i - 1) | one exponentiation |
| any p (Tonelli-Shanks) | needs a non-residue z (expected 2 tries) | O(log p + s²) mults, 2^s the power of 2 in p - 1 |
| any p (Cipolla) | arithmetic in F_p(√(t² - a)) for a t with t² - a a non-residue | O(log p) mults, independent of s |

- Hensel: if f(r) ≡ 0 (mod p^k) and f'(r) ≢ 0 (mod p), the lift r' = r - f(r)·f'(r)^(-1) mod p^(k+1)
  is unique. If f'(r) ≡ 0 (mod p), either no lift or all p lifts work; decide by checking f(r) mod p^(k+1).
- Squares mod p^k, p odd, p ∤ a: exactly 2 roots (lift both). Mod 2^k (k ≥ 3), a odd: solvable iff
  a ≡ 1 (mod 8), and then exactly 4 roots ±r, ±r + 2^(k-1) (checked k ≤ 11).
- Composite n: solve mod each prime power, combine with CRT; for odd squarefree n and gcd(a, n) = 1
  there are 0 or 2^ω(n) roots. Square roots mod n = pq are as hard as factoring n (Rabin), so any
  "sqrt mod n" routine must factor n first.
- `sympy.ntheory.sqrt_mod(a, n, all_roots=True)` handles composite n (`sqrt_mod(17, 32, True)` →
  [7, 9, 23, 25]); `nthroot_mod(a, k, n, all_roots=True)` for k-th roots.

## 3. Valuations: Legendre, Kummer, Lucas, LTE

| Result | Exact statement | Conditions |
|---|---|---|
| Legendre | v_p(n!) = Σ_{i≥1} floor(n/p^i) = (n - s_p(n))/(p - 1), s_p = base-p digit sum | p prime |
| Kummer | v_p(C(m+n, m)) = number of carries when adding m and n in base p | p prime |
| Lucas | C(n, k) ≡ Π C(n_i, k_i) (mod p), digits in base p; C(n, k) odd iff (k & n) == k | p prime; C(n_i, k_i) = 0 if k_i > n_i |
| LTE, minus | v_p(x^n - y^n) = v_p(x - y) + v_p(n) for all n ≥ 1 | p odd, p \| x - y, p ∤ x, p ∤ y |
| LTE, plus | v_p(x^n + y^n) = v_p(x + y) + v_p(n) | p odd, p \| x + y, p ∤ xy, n odd |
| LTE, p = 2, n odd | v_2(x^n - y^n) = v_2(x - y) | x, y odd |
| LTE, p = 2, n even | v_2(x^n - y^n) = v_2(x - y) + v_2(x + y) + v_2(n) - 1 | x, y odd |
| LTE, p = 2, 4 \| x - y | v_2(x^n - y^n) = v_2(x - y) + v_2(n) | x, y odd |

Failures when a condition is dropped: p | x gives v_3(6² - 3²) = 3, not 1 + 0; the odd-p formula at
p = 2 gives v_2(3² - 1) = 2, true value 3. Every row was checked for |x|, |y| ≤ 60, n ≤ 24 and
p ∈ {2, 3, 5, 7, 11}. Compute v_p with `sympy.multiplicity(p, n)` or `gmpy2.remove(n, p)` → (n/p^k, k).

## 4. Diophantine techniques

| Technique | Use when | Example |
|---|---|---|
| Modular obstruction | an equation has no solutions for a residue reason | squares mod 4 ∈ {0,1}, mod 8 ∈ {0,1,4}, mod 3 ∈ {0,1}, mod 5 ∈ {0,±1}; cubes mod 9 and mod 7 ∈ {0,±1}; fourth powers mod 16 ∈ {0,1}; so x² + y² ≠ 4k + 3 and x³ + y³ + z³ ≠ 9k ± 4 |
| Sums of squares | representability questions | n = x² + y² iff every prime ≡ 3 (mod 4) has even exponent; n = x² + y² + z² iff n ≠ 4^a(8b + 7) (Legendre); every n is a sum of 4 squares (Lagrange) |
| Factor in Z[i], Z[ω], Z[√d] | x² + y² = z^k, x² + 2 = y³ | only when the ring is a UFD (class number 1); Z[√-5] is not: 6 = 2·3 = (1 + √-5)(1 - √-5) |
| Infinite descent | a minimal solution yields a smaller one | x⁴ + y⁴ = z² has no positive solutions; √2 irrational |
| Vieta jumping | symmetric quadratic in two variables | (a² + b²)/(ab + 1) = k ∈ Z ⇒ k is a square: take a minimal solution, the other root a' = kb - a = (b² - k)/a is a smaller non-negative solution, descend to a' = 0 |
| Pell x² - Dy² = 1 | D > 0 not a square | CF of √D with period r: fundamental solution is the convergent p_{r-1}/q_{r-1} (r even) or p_{2r-1}/q_{2r-1} (r odd); all solutions ±(x₁ + y₁√D)^k; x² - Dy² = -1 is solvable iff r is odd |
| Bound, then search | finitely many candidates after an inequality | 1/a + 1/b + 1/c = 1 with a ≤ b ≤ c forces a ≤ 3, then b ≤ 4: enumeration gives exactly (2,3,6), (2,4,4), (3,3,3) |

Pell check: √61 = [7; (1, 4, 3, 1, 2, 2, 1, 3, 4, 1, 14)], period 11 (odd), so x² - 61y² = -1 is
solvable and the fundamental solution of the +1 equation is (1766319049, 226153980);
`sympy.solvers.diophantine.diophantine.diop_DN(61, 1)` agrees. Other tools: `diophantine(eq)`
(SymPy), `qfbsolve` and `bnfisintnorm` (PARI/GP), class numbers and integral points from LMFDB.

## 5. Multiplicative functions

| Function | Formula on n = Π p^e | Dirichlet form |
|---|---|---|
| τ (divisor count) | Π (e + 1) | 1 * 1 |
| σ (divisor sum) | Π (p^(e+1) - 1)/(p - 1) | id * 1 |
| φ (Euler) | n Π (1 - 1/p) | μ * id |
| μ (Möbius) | (-1)^k if squarefree with k primes, else 0 | inverse of 1 |

- Convolution (f * g)(n) = Σ_{d|n} f(d) g(n/d): commutative, associative, identity ε = [n = 1];
  multiplicative * multiplicative is multiplicative.
- Möbius inversion: g = f * 1 ⇔ f = g * μ. Identities: Σ_{d|n} φ(d) = n; Σ_{d|n} μ(d) = [n = 1];
  Σ_{d|n} μ(d)/d = φ(n)/n (all three checked for n < 500).
- Summatory estimates (numbers at x = 10^6 in brackets): Σ_{n≤x} τ(n) = x ln x + (2γ - 1)x + O(√x)
  [13970034 vs 13969942]; Σ φ(n) = 3x²/π² + O(x log x) [relative gap 5e-9]; Σ σ(n) = π²x²/12 +
  O(x log x) [1.3e-6]; the density of coprime pairs is 6/π².

Analytic facts to cite with their exact statements (status Known, with a source):

| Theorem | Statement |
|---|---|
| Prime number theorem | π(x) ~ x/ln x; π(x) = Li(x) + O(x e^(-c√(ln x))); π(10^6) = 78498, x/ln x = 72382, li(10^6) ≈ 78628 |
| Mertens | Σ_{p≤x} (ln p)/p = ln x + O(1); Σ_{p≤x} 1/p = ln ln x + M + O(1/ln x), M ≈ 0.2614972128; Π_{p≤x} (1 - 1/p) ~ e^(-γ)/ln x |
| Dirichlet | gcd(a, q) = 1 ⇒ infinitely many primes p ≡ a (mod q), each class with density 1/φ(q) |
| Bertrand (Chebyshev) | for n ≥ 1 there is a prime in (n, 2n] |
| Equivalences | Σ_{n≤x} μ(n) = o(x) is equivalent to the PNT; stronger error terms usually need RH: label "Proved assuming RH" |

## 6. Python and library calls

| Task | Stdlib | SymPy 1.14 | gmpy2 2.3 | PARI/GP |
|---|---|---|---|---|
| inverse mod m | `pow(a, -1, m)` (3.8+, ValueError if not invertible) | `mod_inverse(a, m)` | `invert(a, m)` | `Mod(a, m)^-1` |
| gcd, lcm, Bezout | `math.gcd(*xs)`, `math.lcm(*xs)` (3.9+) | `igcd`, `ilcm`, `gcdex(a, b)` → (x, y, g) | `gcd`, `lcm`, `gcdext(a, b)` → (g, s, t) | `gcd`, `lcm`, `gcdext` |
| integer roots | `math.isqrt(n)` (3.8+) | `integer_nthroot(n, k)` → (root, exact) | `isqrt`, `iroot(n, k)` | `sqrtint`, `sqrtnint` |
| factor | none | `factorint(n)` → {p: e} | none | `factor(n)` |
| primality | none | `isprime(n)` (deterministic below 2^64, strong BPSW above) | `is_prime(n, 25)` (Miller-Rabin), `is_bpsw_prp(n)` | `isprime(n)` proves, `ispseudoprime(n)` is BPSW |
| order, primitive root | none | `n_order(a, n)`, `primitive_root(p)` (None if none), `is_primitive_root(a, p)` | none | `znorder(Mod(a, n))`, `znprimroot(n)` |
| discrete log | none | `discrete_log(n, a, b)` solves b^x ≡ a (mod n) | none | `znlog(h, g)` |
| roots mod n | none | `sqrt_mod(a, n, all_roots=True)`, `nthroot_mod(a, k, n, True)` | none | `sqrt(Mod(a, p))`, `sqrtn` |
| CRT | none | `crt(moduli, residues)` → (x, lcm) or None; `solve_congruence((r1, m1), ...)` | none | `chinese(Mod(a, m), Mod(b, n))` |
| symbols, functions | none | `jacobi_symbol`, `legendre_symbol`, `totient`, `reduced_totient`, `mobius`, `divisor_sigma` from `sympy` | `jacobi`, `legendre`, `kronecker` | `kronecker`, `eulerphi`, `moebius`, `sigma` |

- SymPy ≥ 1.13 moved `totient`, `reduced_totient`, `mobius`, `divisor_sigma`, `jacobi_symbol`,
  `legendre_symbol`, `primepi`, `primenu`, `primeomega` to `sympy.functions.combinatorial.numbers`;
  importing them from `sympy.ntheory` raises SymPyDeprecationWarning. Import them from `sympy`.
- `crt` (default `check=True`) accepts non-coprime moduli: `crt([4, 6], [1, 3])` → (9, 12);
  `crt([4, 6], [1, 2])` → None. Note the argument order: moduli first.
- gmpy2 `mpz` beats Python ints by about 20x on 4096-bit `powmod` and about 60x on million-bit
  products (measured here); switch when profiles show big-integer arithmetic dominating.
- SageMath: `Mod(a, n).multiplicative_order()`, `primitive_root(n)`, `discrete_log(Mod(h, p), Mod(g, p))`,
  `CRT_list(residues, moduli)`, `is_prime` (proves) vs `is_pseudoprime`. LMFDB (lmfdb.org): number fields,
  class numbers, elliptic curves, modular forms, Dirichlet characters; cite the LMFDB label.

## 7. Primality and factoring

| n or factor size | Method | Note |
|---|---|---|
| n ≤ 10^12 | trial division to √n | ≤ 10^6 divisions |
| n < 2^64 | Miller-Rabin with bases 2, 3, 5, ..., 37 (first 12 primes) | deterministic: the least strong pseudoprime to all 12 is 318665857834031151167461 > 2^64; the first 11 bases fail at 3825123056546413051 < 2^64 |
| n < 2^64 | Miller-Rabin with 7 bases 2, 325, 9375, 28178, 450775, 9780504, 1795265022 (Sinclair 2011) | reduce each base mod n; a base ≡ 0 counts as a pass |
| any n, probable prime | BPSW = strong base-2 test + strong Lucas test | no known counterexample, none below 2^64 |
| any n, certificate | ECPP (PARI `isprime`, Primo), or Pocklington/BLS when n - 1 is partly factored | needed for "Proved" on a large prime |
| factor < 10^7 | trial division / sieve | |
| factor < ~10^15-10^18 | Pollard rho (Brent) | ~√p iterations; pure Python is fine to ~10^12 |
| p - 1 smooth | Pollard p - 1 | cheap to try first |
| factor ≲ 40 digits | ECM | cost depends on the factor size, not n |
| n ≲ 100 digits | SIQS (yafu, msieve) | |
| larger n | GNFS (CADO-NFS) | RSA-250 (829 bits) took a large cluster effort in 2020 |

Carmichael numbers (561 = 3·11·17, 1105, 1729, 2465, 2821, 6601, 8911 are all of them below 10^4)
pass the Fermat test for every coprime base. Korselt: n is Carmichael iff n is squarefree, composite
and p - 1 | n - 1 for every p | n; there are infinitely many (Alford-Granville-Pomerance 1994). Never
ship a plain Fermat test. Strong pseudoprimes to base 2 below 10^4: 2047 = 23·89, 3277, 4033, 4681, 8321.
When to stop: a number over ~60 digits with no factor after minutes of rho and ECM goes to PARI
`factor`, yafu or CADO-NFS (or a lookup in factordb.com), and is reported as "not factored".

## 8. Implementation pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| sign of % | C/C++/Java/Go/Rust/JS: -7 % 3 == -1 (sign of the dividend); Python: 2 (sign of the divisor) | `((a % m) + m) % m`; Rust `a.rem_euclid(m)`; Java `Math.floorMod(a, m)`; Python `math.fmod` is the C-like one |
| a*b mod m overflow | m = 2^64 - 59, a = m - 2, b = m - 3: u64 `a*b % m` = 3782, true 6 | m < 2^32: u64 product; m < 2^64: `unsigned __int128` (GCC/Clang), Rust `u128`, Go `bits.Mul64` + `bits.Rem64` (1.14+), Java `Math.multiplyHigh` (9+) or BigInteger; hot loops: Montgomery ([algorithms](references/algorithms.md)) |
| silent wraparound | numpy int64 arrays wrap silently (2^62·4 → 0) | Python ints, `dtype=object`, or gmpy2 |
| floats on big ints | `int(math.sqrt(10**30 - 1))` = 10^15 (wrong); doubles hold integers exactly only to 2^53; JS numbers likewise | `math.isqrt`, `gmpy2.iroot`, JS `BigInt` |
| modulo bias | `rand() % n` favours small residues unless n divides RAND_MAX + 1 | rejection sampling (Lemire's method), `secrets.randbelow`, `random.randrange`, Java `nextInt(bound)` |
| timing leaks | square-and-multiply branches and memory access depend on secret exponent bits; `pow` and `gmpy2.powmod` are not constant time | `gmpy2.powmod_sec` (odd modulus), Montgomery ladder, vetted libraries (OpenSSL `BN_mod_exp_mont_consttime`, libsodium, Go crypto, Rust `crypto-bigint`); constant-time compares |
| Fermat inverse a^(m-2) | wrong when m is not prime | `pow(a, -1, m)` (raises if gcd ≠ 1) |
| φ-reduction of exponents | wrong when gcd(a, n) > 1 | reduce mod λ(n) only for units; else use the e ≥ log2 n form (section 1) |
| Miller-Rabin with base ≥ n | false "composite" or crash for small n | reduce the base mod n, special-case n < 4 and bases ≡ 0 |

## 9. Discrete log and order finding

- Order of a mod n with λ(n) (or φ(n)) factored: r = λ(n); for each prime q | r, while q | r and
  a^(r/q) ≡ 1, set r = r/q. Cost O(Σ e_i log n) multiplications; `n_order` does this.
- Discrete log g^x ≡ h in a group of order N:

| Algorithm | Cost | Use |
|---|---|---|
| baby-step giant-step | O(√N) time and memory | N ≲ 10^14 |
| Pollard rho / kangaroo | O(√N) time, O(1) memory; kangaroo for x in a known interval | large N, little memory |
| Pohlig-Hellman | O(Σ e_i (log N + √q_i)) for N = Π q_i^(e_i) | smooth N: the reason DH groups need a large prime-order subgroup |
| index calculus / NFS-DL | subexponential | (Z/p)^× with large p |
| generic only | √N | elliptic-curve groups (no index calculus): a 256-bit curve gives about 128-bit security |

- `discrete_log` in SymPy combines trial multiplication, BSGS, Pollard rho, index calculus and
  Pohlig-Hellman; for p = nextprime(10^30), whose p - 1 has no prime factor above 5·10^8, it takes ~10 ms.
- Shor's algorithm finds r = ord_N(a) in poly(log N) quantum time. Factoring reduces to it: choose
  random a; if gcd(a, N) > 1, done; else if r is even and a^(r/2) ≢ -1 (mod N), then gcd(a^(r/2) ± 1, N)
  are nontrivial factors. For odd N with k distinct prime factors (not a prime power) a random unit
  succeeds with probability ≥ 1 - 1/2^(k-1). Example N = 15, a = 7: r = 4, 7² ≡ 4, gcd(3, 15) = 3,
  gcd(5, 15) = 5. The measured phase s/r is turned into r by continued fractions
  (`Fraction(s, 2**t).limit_denominator(N)`), then confirmed with `pow(a, r, N) == 1`. Shor also
  solves discrete logs (abelian hidden subgroup). Check circuit outputs classically with `n_order`.

## 10. Verification

1. Exhaustive over residues for small moduli: every a mod n for n ≤ 10^3-10^4 (status: Verified for
   finite range); for "for all n" statements this is falsification, not proof.
2. Random large tests: fixed seed, 256-2048-bit inputs, compare against gmpy2/SymPy/PARI; add
   adversarial inputs: 0, 1, m - 1, negatives, m = 1, p = 2, prime powers, Carmichael numbers and the
   strong pseudoprimes of section 7.
3. Exact arithmetic only: Python int, `gmpy2.mpz`, `fractions.Fraction`; no floats, no fixed-width
   numpy integers.
4. Two independent methods for each computed object (Tonelli vs Cipolla, CRT vs brute force,
   `factorint` vs PARI `factor`); verify the defining property (x² ≡ a, g^x ≡ h, Π p^e = n).

## 11. Worked example: LTE

Claim: v_3(2^(3^k) + 1) = k + 1 for every k ≥ 0.

Proof. Let n = 3^k, which is odd, so 2^n + 1 = 2^n - (-1)^n. Apply LTE (minus form) with p = 3,
x = 2, y = -1. Conditions: p = 3 is odd; 3 | x - y = 3; 3 ∤ 2 and 3 ∤ -1. Hence
v_3(2^n - (-1)^n) = v_3(3) + v_3(3^k) = 1 + k. ∎ (Equivalently the plus form with x = 2, y = 1:
3 | 2 + 1, 3 ∤ 2, n odd.) Status: Proved, LTE being Known.

Check. 2^(3^30) has 3^30 ≈ 2.06·10^14 bits (~26 TB), so test the valuation with modular arithmetic:
v_3(N) = k + 1 iff 3^(k+1) | N and 3^(k+2) ∤ N.

```python
from sympy import multiplicity
for k in range(31):
    n = 3**k
    assert (pow(2, n, 3**(k + 1)) + 1) % 3**(k + 1) == 0     # 3^(k+1) divides 2^n + 1
    assert (pow(2, n, 3**(k + 2)) + 1) % 3**(k + 2) != 0     # 3^(k+2) does not
for k in range(13):                                          # full integers, 2^(3^12) has 531441 bits
    assert multiplicity(3, 2**(3**k) + 1) == k + 1
print("ok")
```

Result: all assertions pass in under a second (Verified for k ≤ 30; full integers for k ≤ 12).
Report: "Proved (LTE); verified for 0 ≤ k ≤ 30 with exact modular arithmetic."

## Pitfalls

- Citing CRT, Euler or LTE without checking coprimality or p ∤ xy; quoting the odd-p LTE at p = 2.
- Treating (a/n) = 1 (Jacobi) as "a is a square mod n".
- Looking for a primitive root mod 8, 12, 15 or any n outside {1, 2, 4, p^k, 2p^k}.
- Fermat tests, or Miller-Rabin with ad hoc bases, in place of BPSW or the deterministic sets.
- `%` on negative numbers in C-family code, a*b mod m in 64-bit, numpy int64 for big products.
- Importing `totient`/`jacobi_symbol` from `sympy.ntheory` (deprecated); passing `crt` residues first.
- Reporting "verified for n ≤ 10^6" as Proved; assuming a factor search that found nothing means prime.
- Non-constant-time modular exponentiation or comparisons in code handling secrets (send to
  `security-auditor`).

Related: `combinatorics-generating-functions`, `proof-techniques-and-writing`, `sympy-symbolic-verification`,
`lean4-mathlib-formalization`, `quantum-algorithm-primitives`, `randomized-algorithms-sketches`,
`security-review`, hub `mathematics-toolkit`.
