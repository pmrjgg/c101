---
name: combinatorics-generating-functions
description: "Counting and enumeration: twelvefold way, bijective and double-counting proofs, inclusion-exclusion and Mobius inversion, OGF/EGF and the symbolic method, recurrences to closed forms, Lagrange inversion, transfer matrices, Burnside/Polya, and coefficient asymptotics by singularity analysis, cross-checked by brute force and OEIS. Load when counting objects, solving or guessing a recurrence, or proving an enumeration identity."
when_to_use: "Count words, lattice paths, trees, partitions, colourings or tilings; find a closed form, generating function or asymptotic for a sequence; solve or guess a linear recurrence; prove a binomial identity bijectively; count up to rotation or reflection; check a formula against brute force and an OEIS A-number."
---

# Combinatorics and generating functions

A count is finished when it has four things: a formula or generating function (GF), a proof
(bijection, specification or algebra), an exact brute-force match for small n, and the OEIS
A-number with the offset checked. Use the hub's status labels: a brute-force match alone is
"Verified for n ≤ N", never "Proved".

## 1. Twelvefold way

n balls into k boxes, i.e. functions from an n-set to a k-set.

| Balls | Boxes | any | injective (≤ 1 per box) | surjective (≥ 1 per box) |
|---|---|---|---|---|
| labelled | labelled | kⁿ | k(k−1)···(k−n+1) | k! S(n,k) |
| unlabelled | labelled | C(n+k−1, n) | C(k, n) | C(n−1, k−1) |
| labelled | unlabelled | Σ_{j≤k} S(n,j) | 1 if n ≤ k else 0 | S(n,k) |
| unlabelled | unlabelled | p_{≤k}(n), partitions into at most k parts | 1 if n ≤ k else 0 | p_k(n) = p_{≤k}(n−k) |

S(n,k) (Stirling, second kind) satisfies S(n,k) = k S(n−1,k) + S(n−1,k−1), and Σ_k S(n,k) = B_n
(Bell). Row 2 also counts compositions: C(n−1, k−1) into k positive parts, C(n+k−1, k−1) into k
nonnegative parts. Check the corners n = 0 and k = 0 by brute force; conventions differ there.

```python
from sympy import binomial, ff, factorial
from sympy.functions.combinatorial.numbers import stirling, nT
from sympy.utilities.iterables import partitions
n, k = 7, 3
k**n, ff(k, n), factorial(k) * stirling(n, k)            # labelled into labelled
binomial(n + k - 1, n), binomial(k, n), binomial(n - 1, k - 1)
sum(stirling(n, j) for j in range(k + 1)), stirling(n, k)
sum(1 for _ in partitions(n, m=k)), nT(n, k)              # at most k parts (8), exactly k parts (4)
```

## 2. Bijective and double-counting proofs

Protocol: define both sets exactly, define the map, show it lands in the target, write the
inverse, and check both compositions are the identity: by argument, and by machine for small n.

- **Vandermonde** Σ_j C(m,j) C(n,r−j) = C(m+n,r). Take r-subsets S of M ⊔ N and split by
  j = |S ∩ M|. The map S ↦ (S ∩ M, S ∩ N) has inverse (A, B) ↦ A ∪ B.
- **Hockey stick** Σ_{i=r}^{n} C(i,r) = C(n+1,r+1). Classify the (r+1)-subsets of {1..n+1} by their
  largest element i+1; the other r elements form an r-subset of {1..i}.
- **Catalan by reflection.** Dyck paths use ±1 steps, have length 2n and never go below 0. A bad
  path touches −1; reflect every step after its first touch. The image ends at −2, and every path
  ending at −2 touches −1, so the map is a bijection onto paths with n−1 up-steps (it is an
  involution because the first touch is unchanged). C_n = C(2n,n) − C(2n,n+1) = C(2n,n)/(n+1).
- **Ballot.** With a > b votes, A is strictly ahead throughout in (a−b)/(a+b)·C(a+b,a) orders.
- **Double counting.** Count one set of pairs two ways. For Σ_k k C(n,k) = n 2^(n−1), count
  (committee, chair) pairs by committee first, then by chair first.

```python
from itertools import product, accumulate
from math import comb
def reflect(p, level=-1):                       # reflect the steps after the first visit to level
    h = 0
    for i, s in enumerate(p):
        h += s
        if h == level:
            return p[:i + 1] + tuple(-t for t in p[i + 1:])
for n in range(1, 9):
    paths = [p for p in product((1, -1), repeat=2 * n) if sum(p) == 0]
    bad = [p for p in paths if min(accumulate(p)) < 0]
    img = {reflect(p) for p in bad}
    assert all(sum(q) == -2 for q in img) and len(img) == len(bad) == comb(2 * n, n + 1)
    assert all(reflect(reflect(p)) == p for p in bad)            # the inverse map, checked
    assert len(paths) - len(bad) == comb(2 * n, n) // (n + 1)
```

## 3. Inclusion-exclusion and Möbius inversion

The number of elements with none of the properties A_1..A_m is Σ_{S⊆[m]} (−1)^|S| |A_S|, where A_S
is the intersection of the A_i for i in S and A_∅ is the whole set.

| Count | Bad property | Result |
|---|---|---|
| derangements D_n | i is a fixed point | n! Σ_{j=0}^n (−1)^j/j! = round(n!/e) for n ≥ 1; D_n = (n−1)(D_{n−1} + D_{n−2}) |
| surjections [n] → [k] | value i is missed | Σ_j (−1)^j C(k,j)(k−j)ⁿ = k! S(n,k) |
| Euler φ(n) | divisible by the prime p, p ∣ n | n Π_{p∣n} (1 − 1/p) |
| proper x-colourings | edge e is monochromatic | P(G,x) = Σ_{F⊆E} (−1)^e(F) x^c(F), with e(F) the number of edges in F and c(F) the number of components of (V,F) |

Möbius inversion on a locally finite poset: g(x) = Σ_{y≤x} f(y) holds for all x if and only if
f(x) = Σ_{y≤x} μ(y,x) g(y), where μ(x,x) = 1 and μ(x,z) = −Σ_{x≤y<z} μ(x,y).

- Subsets ordered by inclusion: μ(S,T) = (−1)^|T∖S|, which is exactly inclusion-exclusion.
- Divisibility: μ(d,n) = μ(n/d), the number-theoretic Möbius function. From Σ_{d∣n} φ(d) = n we get
  φ(n) = Σ_{d∣n} μ(d) n/d. Primitive words of length n over k letters: Σ_{d∣n} μ(d) k^(n/d);
  dividing by n counts Lyndon words (aperiodic necklaces).
- Chromatic polynomial by deletion-contraction: P(G) = P(G − e) − P(G / e). Merge parallel edges;
  a loop gives 0. A tree gives x(x−1)^(n−1), C_n gives (x−1)ⁿ + (−1)ⁿ(x−1), K_n gives
  x(x−1)···(x−n+1). `networkx.chromatic_polynomial(G)` returns a SymPy polynomial to check against.

## 4. Generating-function dictionary

Use an OGF A(z) = Σ a_n zⁿ for unlabelled objects and an EGF Â(z) = Σ a_n zⁿ/n! for labelled
objects (atoms carry distinct labels, and products relabel).

| Operation on a_n | OGF | EGF |
|---|---|---|
| shift a_{n+1} | (A(z) − a_0)/z | Â′(z) |
| n a_n | z A′(z) | z Â′(z) |
| partial sums Σ_{j≤n} a_j | A(z)/(1 − z) | — |
| convolution Σ_j a_j b_{n−j} | A(z) B(z) | — |
| binomial convolution Σ_j C(n,j) a_j b_{n−j} | — | Â(z) B̂(z) |
| cⁿ a_n | A(cz) | Â(cz) |

| Sequence | GF |
|---|---|
| C(n+m−1, m−1) | 1/(1 − z)^m (OGF) |
| Fibonacci F_n (F_0 = 0, F_1 = 1) | z/(1 − z − z²) |
| Catalan C_n | (1 − √(1 − 4z))/(2z) |
| S(n,k) for fixed k | z^k/((1−z)(1−2z)···(1−kz)) (OGF); (e^z − 1)^k/k! (EGF) |
| Bell, derangements, involutions | exp(e^z − 1), e^(−z)/(1 − z), exp(z + z²/2) (EGFs) |
| partitions, partitions into distinct parts | Π_{j≥1} 1/(1 − z^j), Π_{j≥1} (1 + z^j) |

```python
from sympy import symbols, series, factorial, exp, sqrt
z = symbols("z")
def coeffs(F, N, egf=False):
    s = series(F, z, 0, N).removeO()        # pass N: the default truncation is z**6
    return [s.coeff(z, j) * (factorial(j) if egf else 1) for j in range(N)]
coeffs((1 - sqrt(1 - 4*z)) / (2*z), 8)      # [1, 1, 2, 5, 14, 42, 132, 429]
coeffs(exp(exp(z) - 1), 8, egf=True)        # Bell: [1, 1, 2, 5, 15, 52, 203, 877]
```

For hundreds of terms, iterate a recurrence or use truncated power-series arithmetic
(`sympy.polys.ring_series`): `series` on large expressions is slow.

## 5. Symbolic method (Flajolet-Sedgewick)

| Construction | Unlabelled (OGF) | Labelled (EGF) |
|---|---|---|
| A + B (disjoint union) | A + B | Â + B̂ |
| A × B (pairs; labelled product relabels) | A·B | Â·B̂ |
| SEQ(A), needs a_0 = 0 | 1/(1 − A) | 1/(1 − Â) |
| SET(A) | MSET: exp(Σ_{k≥1} A(z^k)/k) = Π_n (1 − zⁿ)^(−a_n); PSET: exp(Σ_{k≥1} (−1)^(k−1) A(z^k)/k) | exp(Â) |
| CYC(A) | Σ_{k≥1} (φ(k)/k) log(1/(1 − A(z^k))) | log(1/(1 − Â)) |
| exactly k components | SEQ_k: A^k | SEQ_k: Â^k, SET_k: Â^k/k!, CYC_k: Â^k/k |

Translations to know:

- Compositions: SEQ(SEQ_{≥1}(Z)) gives (1 − z)/(1 − 2z), so 2^(n−1) for n ≥ 1. With parts in
  {1, 2}: 1/(1 − z − z²), so F_{n+1}.
- Plane trees counted by nodes: G = Z × SEQ(G), so G = z/(1 − G) = (1 − √(1 − 4z))/2 and
  g_n = C_{n−1}. Binary trees counted by internal nodes: B = 1 + zB², the Catalan numbers.
- Labelled rooted trees: T = Z ⋆ SET(T), so T = z e^T (section 7). Set partitions
  SET(SET_{≥1}(Z)) give exp(e^z − 1); permutations SET(CYC(Z)) give 1/(1 − z); derangements
  SET(CYC_{≥2}(Z)) give e^(−z)/(1 − z).
- Integer partitions: MSET(SEQ_{≥1}(Z)) gives Π 1/(1 − z^j).

Write the specification first and list the objects for n ≤ 4 by hand; the GF then follows
mechanically.

## 6. Linear recurrences

For a_n = c_1 a_{n−1} + ... + c_d a_{n−d}, the characteristic polynomial is
χ(x) = x^d − c_1 x^(d−1) − ... − c_d. A root r of multiplicity m contributes
(α_0 + α_1 n + ... + α_{m−1} n^(m−1)) rⁿ; fit the α to the d initial values. The GF is P(z)/Q(z)
with Q(z) = 1 − c_1 z − ... − c_d z^d (χ reversed) and deg P < d when the recurrence holds from
n = d. Partial fractions finish it: [zⁿ] 1/(1 − rz)^m = C(n+m−1, m−1) rⁿ.

```python
from sympy import symbols, Function, rsolve, apart, sequence, fibonacci, oo
from sympy.concrete.guess import guess_generating_function_rational, find_simple_recurrence
n, z = symbols("n z"); a = Function("a")
rsolve(a(n) - a(n - 1) - a(n - 2), a(n), {a(0): 1, a(1): 2})     # Binet form
apart(1 / ((1 - z) * (1 - 2*z)), z)                              # -2/(2z-1) + 1/(z-1): a_n = 2^(n+1) - 1
data = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]
guess_generating_function_rational(data, X=z)                    # (z + 1)/(-z**2 - z + 1)
find_simple_recurrence(data)                                     # -a(n) - a(n + 1) + a(n + 2)
sequence(fibonacci(n), (n, 0, oo)).find_linear_recurrence(20, gfvar=z)   # ([1, 1], -z/(z**2 + z - 1))
```

A guess from finitely many terms is a conjecture. Prove it in one of three ways:

1. A combinatorial decomposition (first letter, last step, root removal) that yields the recurrence.
2. A transfer matrix: if a_n = uᵀ Mⁿ v with M of size d × d, Cayley-Hamilton gives the recurrence
   with characteristic polynomial det(xI − M).
3. The degree rule. Suppose a has a rational GF with denominator degree ≤ d and numerator degree
   < d (a d-state transfer matrix gives this), and the guess has denominator degree d′. Then
   agreement of the first d + d′ terms proves equality, because the difference of the two GFs has
   a numerator of degree < d + d′.

## 7. Lagrange inversion

If T(z) = z φ(T(z)) with φ(0) ≠ 0, then for n ≥ 1:
[zⁿ] T^k = (k/n) [w^(n−k)] φ(w)ⁿ, and [zⁿ] H(T(z)) = (1/n) [w^(n−1)] H′(w) φ(w)ⁿ.

| Class | Equation | φ(w) | Count |
|---|---|---|---|
| binary trees by internal nodes (T = B − 1) | T = z(1+T)² | (1+w)² | (1/n) C(2n, n−1) = C_n |
| plane trees by nodes | G = z/(1 − G) | 1/(1−w) | (1/n) C(2n−2, n−1) = C_{n−1} |
| ternary trees | T = z(1+T)³ | (1+w)³ | (1/n) C(3n, n−1) = C(3n,n)/(2n+1): 1, 3, 12, 55, 273 |
| labelled rooted trees (EGF) | T = z e^T | e^w | n!·(1/n)·n^(n−1)/(n−1)! = n^(n−1); unrooted n^(n−2) (Cayley) |

```python
from sympy import symbols, series, exp, Rational, factorial
w = symbols("w")
[factorial(m) * Rational(1, m) * series(exp(m*w), w, 0, m).removeO().coeff(w, m - 1) for m in range(1, 7)]
# [1, 2, 9, 64, 625, 7776] == [m**(m-1) for m in 1..6]
```

## 8. Transfer-matrix method

Build a finite automaton whose states remember just enough: the last letters, or the profile of
the boundary in a tiling. With M[i][j] the number of one-step moves from state i to state j, the
number of length-n objects is a_n = uᵀ Mⁿ v. Consequences:

- The GF uᵀ (I − zM)⁻¹ v = P(z)/det(I − zM) is rational with denominator degree ≤ number of states.
- The recurrence comes from det(xI − M) (Cayley-Hamilton).
- Growth: a_n = O(ρⁿ n^(m−1)), with ρ the spectral radius of M and m the largest Jordan block
  among eigenvalues of modulus ρ. It can be smaller if u or v misses the dominant eigenspace. If M
  is nonnegative and primitive and u, v ≥ 0 are nonzero, Perron-Frobenius gives a_n ~ c ρⁿ with
  c > 0.
- States for avoiding one word w: the longest suffix of the word read so far that is a prefix of w
  (the KMP automaton). For a set of forbidden words, use Aho-Corasick states or the
  Goulden-Jackson cluster method.
- Tilings of a k × n strip: the state is which cells of the next column are already covered
  (2^k profiles). Domino tilings: 2 × n gives F_{n+1}; 3 × 2m gives 1, 3, 11, 41, 153 with
  f(m) = 4f(m−1) − f(m−2) and growth (2 + √3)^m.

## 9. Counting under symmetry

Burnside: the number of orbits is |X/G| = (1/|G|) Σ_{g∈G} |Fix(g)|. When g permutes positions
coloured with k colours, |Fix(g)| = k^c(g), where c(g) counts the cycles of g on the positions,
fixed points included.

- Necklaces (rotations, |G| = n): N(n,k) = (1/n) Σ_{d∣n} φ(d) k^(n/d).
- Bracelets (dihedral, |G| = 2n): N(n,k)/2 plus k^((n+1)/2)/2 for odd n, or (k+1) k^(n/2)/4 for even n.
- Pólya cycle index: Z_G = (1/|G|) Σ_g Π_i s_i^(c_i(g)). Substituting s_i = x_1^i + ... + x_k^i gives
  the pattern inventory. For cube faces under the 24 rotations,
  Z = (s₁⁶ + 3s₁²s₂² + 6s₁²s₄ + 6s₂³ + 8s₃²)/24, which gives (k⁶ + 3k⁴ + 12k³ + 8k²)/24
  colourings: 10 for k = 2, 57 for k = 3.

Write the group out explicitly from generators. Never trust a remembered list of classes.

```python
from sympy import symbols, expand, Rational
from sympy.combinatorics import Permutation, PermutationGroup
U, D, F, B, L, R = range(6)
G = PermutationGroup([Permutation([[F, R, B, L]], size=6),     # quarter turn about the U-D axis
                      Permutation([[U, F, D, B]], size=6)])    # quarter turn about the L-R axis
assert G.order() == 24
orbits = lambda k: sum(k**g.cycles for g in G.elements) // G.order()   # .cycles counts fixed points
orbits(2), orbits(3)                                                     # (10, 57)
r, b = symbols("r b"); s = lambda i: r**i + b**i
Z = Rational(1, 24) * (s(1)**6 + 3*s(1)**2*s(2)**2 + 6*s(1)**2*s(4) + 6*s(2)**3 + 8*s(3)**2)
expand(Z).coeff(r, 3).coeff(b, 3)                                        # 2 cubes with 3 red, 3 blue faces
```

Cross-check by brute force: canonicalise each of the k⁶ colourings as the minimum over its 24
images and count the distinct canonical forms.

## 10. Coefficient asymptotics

1. **Find the dominant singularity ρ**, the singularity of smallest modulus. Pringsheim: with
   nonnegative coefficients, one dominant singularity lies at z = ρ > 0. The growth is
   limsup a_n^(1/n) = 1/ρ.
2. **Transfer.** If A(z) ~ C(1 − z/ρ)^(−α) near ρ, with α ∉ {0, −1, −2, ...} and A analytic in a
   Δ-domain beyond ρ, then [zⁿ] A ~ C ρ^(−n) n^(α−1)/Γ(α) (Flajolet-Odlyzko).
3. **Poles.** A simple pole with A ~ C/(1 − z/ρ) gives a_n ~ C ρ^(−n). Several singularities on
   |z| = ρ (a GF in z², say) contribute separately, and periodic behaviour follows.
4. **Entire GFs: saddle point.** [zⁿ] F ≈ F(ζ)/(ζⁿ √(2π b(ζ))), where ζ solves a(ζ) = n with
   a(z) = zF′(z)/F(z) and b(z) = z a′(z) (for H-admissible F). For e^z this gives Stirling.
5. **Reference results.** n! ~ √(2πn)(n/e)ⁿ(1 + 1/(12n) + ...);
   C_n ~ 4ⁿ/(√π n^(3/2)), from √(1 − 4z) with α = −1/2 and Γ(−1/2) = −2√π;
   p(n) ~ exp(π√(2n/3))/(4n√3) (Hardy-Ramanujan). The partition GF has the unit circle as a
   natural boundary, so singularity analysis does not apply; the circle method does.

Ratio check against exact terms before reporting any asymptotic. If a_n ~ Cρ^(−n) n^(α−1), then
n(ρ a_{n+1}/a_n − 1) → α − 1. For Catalan (ρ = 1/4) it gives −1.4706 at n = 100 and −1.4970 at
n = 1000, with limit −3/2.

## 11. Verification

1. **Brute force** with itertools (`product`, `permutations`, `combinations`) in exact integers,
   for n = 0..N with N ≥ 10 where runtime allows, compared term by term with the formula.
2. **OEIS.** Look up 10-20 terms (drop leading trivial terms if needed), cite the A-number, and
   check that the OEIS definition matches your objects and offset:
   ```bash
   curl -s "https://oeis.org/search?q=1,2,3,5,8,13,21,34,55,89&fmt=json" | python3 -c "import json,sys; d=json.load(sys.stdin); r=d.get('results') if isinstance(d,dict) else d; print([('A%06d' % x['number'], x['name']) for x in (r or [])[:3]])"
   ```
   The JSON is a dict with "results" in older API versions and a bare list in newer ones; the
   one-liner handles both.
3. **SageMath** when installed: `sage -c 'print(Partitions(30).cardinality())'`, plus species,
   posets and `graphs.nauty_geng`.
4. **Labels.** "Verified for n ≤ N" from brute force; "Proved" only with an argument.

## 12. Worked example: binary strings with no "11"

Let a_n count binary strings of length n with no two adjacent 1s.

1. **Specification.** A valid string is ε, "1", "0"·S or "10"·S with S valid, so
   A = 1 + z + zA + z²A and A(z) = (1 + z)/(1 − z − z²).
2. **Transfer matrix.** The state is the last bit. M = [[1,1],[1,0]] (after a 0 comes 0 or 1;
   after a 1 only 0), and a_n = (1,1) M^(n−1) (1,1)ᵀ for n ≥ 1. det(I − zM) = 1 − z − z², the
   same denominator.
3. **Closed form.** a_n = a_{n−1} + a_{n−2} with a_0 = 1, a_1 = 2, so a_n = F_{n+2}.
4. **Growth.** ρ(M) = φ = (1+√5)/2. The dominant pole 1/φ is simple, so
   a_n ~ (φ²/√5) φⁿ ≈ 1.1708 φⁿ. Exactly, a_n = (φ^(n+2) − ψ^(n+2))/√5 with ψ = −1/φ, and
   |ψ^(n+2)/√5| < 1/2, so a_n = round(φ^(n+2)/√5).
5. **Checks.**

```python
from itertools import product
from sympy import Matrix, fibonacci, symbols, series
z = symbols("z")
brute = [sum("11" not in "".join(p) for p in product("01", repeat=n)) for n in range(21)]
gf = series((1 + z) / (1 - z - z**2), z, 0, 21).removeO()
M = Matrix([[1, 1], [1, 0]])
assert brute == [gf.coeff(z, n) for n in range(21)] == [fibonacci(n + 2) for n in range(21)]
assert all((Matrix([[1, 1]]) * M**(n - 1) * Matrix([1, 1]))[0] == brute[n] for n in range(1, 21))
print(brute[:10], M.eigenvals())   # [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]  {1/2 ± sqrt(5)/2: 1}
```

The OEIS search on 1, 2, 3, 5, 8, ... returns A000045 (Fibonacci), so a_n = A000045(n+2) after the
offset shift. Status: Proved (specification and transfer matrix agree), and Verified for n ≤ 20.

## 13. Pitfalls

- **Offset errors.** Whether the empty object counts, C_n vs C_{n−1}, F_0 = 0. State the offset
  next to every formula and every A-number.
- **The wrong GF type.** An OGF for labelled objects (or an EGF for unlabelled ones) makes products
  count the wrong thing.
- **SEQ(A) with a_0 ≠ 0.** Then 1/(1 − A) is not a formal power series.
- **MSET, PSET and SEQ confused.** They mean repetition allowed, distinct, and ordered.
- **Burnside per conjugacy class** without weighting by class size. Colouring faces vs vertices vs
  edges uses different permutation actions.
- **A guessed recurrence reported as a theorem.** Also, too few terms: fit at least 2 × order + a few.
- **`series` truncation.** The default is order 6. `partitions()` yields the same dict each time:
  copy it before storing.
- **Asymptotics from the wrong singularity.** It must be the smallest modulus. Do not ignore
  periodicity, and do not apply the transfer theorem at a natural boundary.
- **Floats in counts.** Use Python ints or SymPy Integers; doubles are exact only below 2⁵³.
- **Stirling kinds.** SymPy's `stirling(n, k)` is the second kind; use `kind=1` (and `signed=True`)
  for the first kind.

Related: `number-theory-modular`, `probability-distributions-limits`, `graph-theory-probabilistic-method`, `sympy-symbolic-verification`, `proof-techniques-and-writing`, `real-complex-analysis`, hub `mathematics-toolkit`
