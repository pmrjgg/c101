# Computational checking cheat-sheet

Install into an isolated environment, never into the system Python. Shell state does not persist
between Bash tool calls, so never rely on `activate`: call the venv's interpreter explicitly, or use
one self-contained `uv run --with ...` command per check.

```bash
uv venv .stack/mathenv && uv pip install --python .stack/mathenv sympy mpmath numpy scipy python-flint z3-solver networkx
.stack/mathenv/bin/python -I <out_dir>/check.py
uv run -q --with sympy --with mpmath --with python-flint python -I <out_dir>/check.py   # no venv needed
```

## 1. SymPy

```python
from sympy import (symbols, Function, Eq, solve, simplify, factor, expand, cancel, apart, limit,
                   series, summation, product, integrate, diff, oo, Rational, sqrt, nsimplify,
                   Matrix, rsolve, dsolve, binomial, factorial, isprime, factorint, gcd, together)

n, k = symbols("n k", integer=True, positive=True)
x, y = symbols("x y", real=True)
a = Function("a")

summation(binomial(n, k), (k, 0, n))                 # 2**n
rsolve(a(n) - a(n-1) - a(n-2), a(n), {a(0): 0, a(1): 1})   # Binet form
simplify(integrate(x**2 * (1 - x)**3, (x, 0, 1)))    # 1/60 (Beta(3, 4))
series(1/(1 - x - x**2), x, 0, 8)                    # Fibonacci coefficients
Matrix([[2, 1], [1, 2]]).eigenvals()                 # {3: 1, 1: 1}
factor(x**4 + 4)                                     # (x**2 - 2*x + 2)*(x**2 + 2*x + 2)
nsimplify(1.4142135623730951)                        # sqrt(2) -- a guess, verify it
```

Assumptions matter: `sqrt(x**2)` simplifies to `x` only with `x` declared positive. Declare
`positive=True`, `integer=True`, `real=True` to match the problem, and re-check with a numeric
substitution at a few random exact rationals:

```python
import random
from sympy import Rational
expr_lhs, expr_rhs = ..., ...
for _ in range(20):
    v = Rational(random.randint(-10**6, 10**6), random.randint(1, 10**6))
    assert simplify(expr_lhs.subs(x, v) - expr_rhs.subs(x, v)) == 0
```

`simplify(e) == 0` returning False does not prove e ≠ 0 (simplification is incomplete); test
numerically at high precision or use `e.equals(0)`, which may return None (unknown).

## 2. Exact enumeration patterns

```python
from fractions import Fraction
from itertools import combinations, permutations, product
from math import comb, gcd

# verify a claim exhaustively for small n, exact arithmetic
def claim(n): return sum(Fraction(1, k*k) for k in range(1, n+1)) <= 2 - Fraction(1, n)
assert all(claim(n) for n in range(1, 2001))

# counterexample hunt for a graph statement
import networkx as nx
for g in nx.graph_atlas_g():                          # all graphs up to 7 vertices
    if g.number_of_nodes() and not property_holds(g):
        print(nx.to_dict_of_lists(g)); break
```

For graphs beyond 7 vertices use `geng` (nauty) to enumerate non-isomorphic graphs:
`geng -c 9 | python check.py` (connected graphs on 9 vertices, graph6 format, read with
`nx.from_graph6_bytes`).

## 3. High precision and constant recognition

```python
from mpmath import mp, mpf, nsum, inf, zeta, pi, quad, identify, pslq, findroot
mp.dps = 60
s = nsum(lambda k: 1/k**2, [1, inf]); print(s - pi**2/6)        # ~1e-60
c = quad(lambda t: t**2/(1 + t**4), [0, inf])                   # pi/(2*sqrt(2))
identify(c, ["pi", "sqrt(2)"])                                   # proposes a closed form
pslq([c, pi/mp.sqrt(2)], maxcoeff=10**6, maxsteps=10**6)         # integer relation
```

Protocol: compute at dps = 30 and dps = 60; agreement to ~30 digits plus a matching closed form is
strong evidence. Report as "Numerical evidence (60 digits)", never as "Proved".

## 4. Rigorous numerics

```python
from mpmath import iv
iv.dps = 30
f = lambda x: x**3 - 2*x - 5
print(f(iv.mpf([2.09, 2.1])))          # interval containing 0 ⇒ root may be inside; exclusion if not

from flint import arb, acb, ctx       # python-flint: ball arithmetic with rigorous error bounds
ctx.dps = 30                          # default is 53 bits (~15 digits)
print(arb(2).sqrt())                  # [1.41421356237309504880168872421 +/- 6.27e-31]
```

Interval Newton or bisection with interval evaluation proves existence/uniqueness of roots;
evaluating an inequality on a grid of intervals that covers the domain proves it on that domain
(the computer-assisted proof pattern). In Julia: IntervalArithmetic.jl and IntervalRootFinding.jl.

## 5. Z3 (SMT)

```python
from z3 import Ints, Reals, Solver, And, Or, Not, sat, unsat, ForAll, Implies
x, y = Ints("x y")
s = Solver()
s.add(x*x + y*y == 3)
print(s.check())                       # unsat (no integer solutions); nonlinear integer: may be 'unknown'

a, b = Reals("a b")
s = Solver()
s.add(Not(Implies(And(a > 0, b > 0), a*b > 0)))
print(s.check())                       # unsat ⇒ the implication holds over the reals (nlsat is complete for real arithmetic)
```

Use bounded variables (`And(0 <= x, x < 100)`) to turn infinite questions into finite checks.

## 6. Lean 4 with Mathlib

```bash
mkdir -p <out_dir> && cd <out_dir> && lake +leanprover-community/mathlib4:lean-toolchain new scratch math   # under out_dir, never in the user's tree
cd <out_dir>/scratch && lake exe cache get                             # download compiled Mathlib (several GB)
cd <out_dir>/scratch && lake env lean Scratch/Basic.lean               # check a file (cwd does not persist between calls)
```

```lean
import Mathlib

theorem sum_odd (n : ℕ) : ∑ i ∈ Finset.range n, (2 * i + 1) = n ^ 2 := by
  induction n with
  | zero => simp
  | succ n ih => rw [Finset.sum_range_succ, ih]; ring

example (a b : ℝ) (ha : 0 ≤ a) (hb : 0 ≤ b) : a * b ≤ (a ^ 2 + b ^ 2) / 2 := by
  nlinarith [sq_nonneg (a - b)]

example : Nat.Prime 1009 := by norm_num
```

Tactic map: arithmetic normalisation `norm_num`; decidable finite facts `decide`; linear integer
arithmetic `omega`; linear real arithmetic `linarith`; nonlinear with hints `nlinarith [...]`;
positivity goals `positivity`; ring identities `ring`; field identities `field_simp` then `ring`;
monotonicity `gcongr`; library search `exact?`, `apply?`, `rw?`. A proof that compiles with no
`sorry` (check `#print axioms thm` lists only standard axioms) is a formal proof of the stated
theorem; read the statement to confirm it is the one you meant.

## 7. Julia

```julia
using Symbolics, IntervalArithmetic
@variables x
Symbolics.simplify((x^2 - 1)/(x - 1))      # x + 1 (on the domain x ≠ 1)
f(x) = x^3 - 2x - 5
f(interval(2.09, 2.1))                     # rigorous enclosure
```

## 8. OEIS and other databases

```bash
curl -s "https://oeis.org/search?q=1,1,2,5,14,42,132&fmt=json" | python -c "import json,sys; d=json.load(sys.stdin); print([ (r['number'], r['name']) for r in (d if isinstance(d, list) else d.get('results') or [])[:5]])"
```

The JSON shape has changed over time (list vs object with `results`); the one-liner handles both.
Other references: LMFDB (number theory), House of Graphs (graphs), the Inverse Symbolic Calculator
for constants, DLMF for special functions (dlmf.nist.gov).

## 9. Reporting computational checks

| Field | Example |
|---|---|
| Statement checked | Σ_{k≤n} 1/k² ≤ 2 - 1/n |
| Domain | 1 ≤ n ≤ 2000 |
| Arithmetic | exact rationals (`fractions.Fraction`) |
| Result | holds for all; tightest at n = 1 (equality) |
| Code | `<out_dir>/check_basel.py`, run with `.stack/mathenv/bin/python -I <out_dir>/check_basel.py`, exit 0 |
| Status label | Verified for finite range |
