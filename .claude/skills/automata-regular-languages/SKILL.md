---
name: automata-regular-languages
description: "Finite automata and regular languages: DFA/NFA/epsilon-NFA, subset construction, Hopcroft and Moore minimisation, Thompson construction and state elimination, closure properties and product construction, pumping-lemma and Myhill-Nerode proofs, decision procedures and their costs, and lexer and regex-engine construction. Load when proving (non)regularity, building lexers or matchers, or reasoning about regex engine behaviour."
when_to_use: "Proving a language is or is not regular; converting a regex to an NFA/DFA or an automaton back to a regex; minimising or comparing automata; building a lexer or tokenizer state machine; checking whether two regexes or validators accept the same strings; explaining why a backtracking regex is slow or why backreferences and lookarounds are missing from RE2, Go and Rust; protocol or input validators written as state machines."
---

# Automata and regular languages

Constructions and proofs for regular languages, and how they show up in lexers and regex engines.
The Chomsky-hierarchy table stays in `cs-foundations` section 6; writing and debugging real regexes
(flavours, ReDoS fixes) is `regex-engineering`; parser construction is `compiler-construction`.

## 1. Definitions and conversions

- DFA: (Q, Sigma, delta: Q x Sigma -> Q, q0, F). Complete when delta is total; add a dead (sink)
  state to complete it.
- NFA: delta: Q x Sigma -> 2^Q; accepts if some run ends in F. epsilon-NFA: transitions on epsilon
  too; the epsilon-closure E(S) is everything reachable from S by epsilon moves.
- epsilon-elimination: delta'(q, a) = E(delta(E({q}), a)), and q is accepting if E({q}) meets F.
- All four (DFA, NFA, epsilon-NFA, regular expressions) describe exactly the regular languages
  (Kleene's theorem).

| From -> To | Construction | Size bound |
|---|---|---|
| regex (length m) -> epsilon-NFA | Thompson | at most 2m states, one accepting state |
| regex -> epsilon-free NFA | Glushkov / position automaton | (symbol occurrences) + 1 states |
| regex -> DFA directly | Brzozowski derivatives, followpos | up to exponential |
| NFA (n states) -> DFA | subset construction | up to 2^n, and that is tight |
| DFA -> minimal DFA | Hopcroft or Moore | at most n, unique up to renaming |
| automaton -> regex | state elimination | can be exponential |

## 2. Subset construction

DFA states are sets of NFA states: start at E({q0}); for each set S and symbol a, the successor is
E(union of delta(q, a) for q in S); a set is accepting if it contains an accepting NFA state. Only
reachable sets are built. The empty set is the dead state.

```python
def determinise(delta, start, accepts, alphabet, eps=None):
    def closure(S):
        stack, seen = list(S), set(S)
        while stack:
            for r in delta.get((stack.pop(), eps), ()):
                if r not in seen: seen.add(r); stack.append(r)
        return frozenset(seen)
    q0 = closure({start}); states, work, trans = {q0}, [q0], {}
    while work:
        S = work.pop()
        for a in alphabet:
            T = closure({r for q in S for r in delta.get((q, a), ())})
            trans[S, a] = T
            if T not in states: states.add(T); work.append(T)
    return states, trans, q0, {S for S in states if S & accepts}
```

Worked table for `(a|b)*abb` with NFA 0 -a-> {0, 1}, 0 -b-> {0}, 1 -b-> {2}, 2 -b-> {3}, accepting 3:

| DFA state | on a | on b | accepting |
|---|---|---|---|
| A = {0} | B | A | |
| B = {0, 1} | B | C | |
| C = {0, 2} | B | D | |
| D = {0, 3} | B | A | yes |

Four states, already minimal: each remembers how much of `abb` the input currently ends with.

Blow-up: L_n = "the n-th symbol from the end is a" = `(a|b)* a (a|b){n-1}`. An NFA needs n + 1
states (guess the position); every DFA needs 2^n, because any two distinct strings of length n
differ at some position i from the end and are separated by appending i - 1 symbols.

## 3. Minimisation

Procedure: remove unreachable states, complete with a dead state, then merge indistinguishable
states (p and q are equivalent when no suffix leads one to accept and the other to reject).

- Moore: start from {F, Q - F}; repeatedly split blocks by the signature (own block, block of each
  successor); stop when no block splits. At most n - 2 rounds; O(|Sigma| n^2) worst case; simple and
  fine for thousands of states.
- Hopcroft: O(|Sigma| n log n) by processing "splitters" and re-queueing only the smaller half:

```text
P := {F, Q \ F};  W := {smaller of F, Q \ F}
while W not empty:
    remove A from W
    for c in Sigma:
        X := { q | delta(q, c) in A }
        for Y in P with Y & X and Y \ X both non-empty:
            replace Y in P by Y & X and Y \ X
            if Y in W: replace Y in W by both halves
            else:      add the smaller half to W
```

- Brzozowski: determinise(reverse(determinise(reverse(A)))) is minimal; exponential worst case, but
  short to implement and sometimes fast in practice.
- The minimal complete DFA is unique, so "same minimal DFA" is an equivalence test.

## 4. Thompson construction and state elimination

| Regex | Fragment (s = new start, f = new accept) |
|---|---|
| epsilon | s -eps-> f |
| a | s -a-> f |
| R \| S | s -eps-> start(R), s -eps-> start(S); accept(R) -eps-> f, accept(S) -eps-> f |
| R S | accept(R) is merged with (or eps-linked to) start(S) |
| R* | s -eps-> start(R), s -eps-> f, accept(R) -eps-> start(R), accept(R) -eps-> f |

Each state has at most two outgoing epsilon edges or one symbol edge, so simulating the NFA on a set
of current states costs O(n x m) for input length n and regex length m (Thompson's algorithm, the
Pike VM when captures are tracked).

State elimination (automaton to regex): add a fresh start and a fresh accepting state with epsilon
edges, label edges with regexes, then remove states one at a time; removing r rewrites every pair
of neighbours p, q as `R(p,q) | R(p,r) R(r,r)* R(r,q)`. The result depends on the order; remove
states with few in-edges times out-edges first to keep it small.

## 5. Closure properties and product construction

| Operation | Construction | Cost |
|---|---|---|
| Union | NFA: new start with two epsilon edges; DFA: product | O(n1 + n2); product O(n1 x n2) |
| Intersection | product automaton | O(n1 x n2) |
| Complement | complete DFA, swap accepting and non-accepting | linear on a DFA; an NFA must be determinised first |
| Difference A - B | A intersect complement(B) | O(n1 x n2) on DFAs |
| Concatenation, star | Thompson fragments | linear |
| Reversal | reverse edges, swap start and accepting | linear (yields an NFA) |
| Homomorphism, inverse homomorphism, quotient | substitute or simulate | polynomial |

```python
def product(d1, s1, f1, d2, s2, f2, alphabet, mode="and"):   # both DFAs complete
    start, seen, work, delta = (s1, s2), {(s1, s2)}, [(s1, s2)], {}
    while work:
        p, q = work.pop()
        for a in alphabet:
            t = (d1[p][a], d2[q][a]); delta[(p, q), a] = t
            if t not in seen: seen.add(t); work.append(t)
    accept = {(p, q) for p, q in seen if
              ((p in f1) and (q in f2) if mode == "and" else
               (p in f1) or (q in f2) if mode == "or" else (p in f1) and (q not in f2))}
    return seen, delta, start, accept
```

## 6. Proving non-regularity

Pumping lemma (template; it is a game against an adversary):

1. Assume L is regular with pumping length p (p is unknown: keep it symbolic).
2. Choose one string s in L with |s| >= p; you pick s, and it may depend on p.
3. For every split s = xyz with |xy| <= p and |y| >= 1 (the adversary picks; handle them all),
4. exhibit an i >= 0 with x y^i z not in L. Contradiction, so L is not regular.

The lemma is necessary, not sufficient: some non-regular languages pump (for example
{a^i b^j c^k : i = 0 or j = k}), so failing to find a contradiction proves nothing.

Myhill-Nerode: x and y are equivalent when, for every suffix z, xz and yz are both in L or both out.
L is regular if and only if there are finitely many classes, and the number of classes is the number
of states of the minimal complete DFA. Proof template: exhibit an infinite set of strings, pairwise
distinguished by some suffix. This also proves lower bounds on DFA size (section 2's 2^n).

Closure arguments are often shortest: if L were regular, so would be L intersect `a*b*`; for "equal
numbers of a's and b's" that intersection is {a^n b^n}, known non-regular.

## 7. Decision procedures and their costs

| Problem | DFA | NFA or regex |
|---|---|---|
| Membership of w | O(\|w\|) | O(\|w\| x n) by set simulation |
| Emptiness | reachability of an accepting state: linear | linear (NL-complete) |
| Finiteness | no cycle on a path from start to an accepting state: linear | linear on the trimmed automaton |
| Universality | complement, then emptiness: linear | PSPACE-complete |
| Equivalence | minimise and compare, or Hopcroft-Karp union-find: near-linear | PSPACE-complete |
| Inclusion L(A) within L(B) | emptiness of A x complement(B): O(n1 x n2) | PSPACE-complete |

In practice, antichain algorithms and bisimulation up to congruence decide NFA inclusion and
equivalence without full determinisation on many real inputs. Extensions raise the cost:
equivalence of regexes with squaring is EXPSPACE-complete, with complement non-elementary.

## 8. Practical: lexers and regex engines

- Lexers: build one DFA for the union of token patterns, labelling each accepting state with its
  token. Maximal munch: keep running, remember the last accepting position, emit the longest match;
  break ties by rule priority (keywords listed before identifiers). Backing up to the last accept is
  linear per token but can go quadratic overall on adversarial token sets (tokens `a` and `a*b` on
  `aaaa...`); Reps (1998) gives a linear-time maximal-munch tokenizer. Generators: re2c, flex, logos.
- Engines: backtracking (PCRE2, Java, Python `re`, JavaScript, .NET by default) is exponential in the
  worst case; automata-based engines (RE2, Go `regexp`, Rust `regex`, Hyperscan) run in O(n x m)
  using lazily built DFAs (falling back when the state cache thrashes), Pike VMs for capture groups,
  and one-pass DFAs where the pattern allows.
- Not regular: backreferences (`(a*)b\1` matches {a^n b a^n}; matching with backreferences is
  NP-complete), recursion and balancing groups (PCRE `(?R)`, .NET), so linear-time engines omit them.
  Lookaround is regular in theory (intersections and complements) but expensive to compile, which
  is why RE2-family engines leave it out.
- Unicode: automata-based engines compile character classes to automata over UTF-8 bytes, so a
  large class becomes many states; byte vs code point semantics differ between engines.

## 9. Pitfalls

- Complementing an incomplete DFA (missing transitions) or an NFA directly: wrong language.
- Forgetting the epsilon-closure of the start state, or of each successor, in subset construction.
- Minimising before removing unreachable states, or with an incomplete transition function.
- Pumping-lemma "proofs" that choose the split or the pumping length, or try to prove regularity.
- Treating "regex" features (backreferences, recursion) as regular when reasoning about complexity.
- Testing equivalence of two validators by sampling strings instead of comparing minimal DFAs or
  running an inclusion check both ways.
- Lexer rules where priority and longest match disagree (`if` vs `ifx`, `<` vs `<=`) without a test.

## 10. Worked example

**{a^n b^n : n >= 0} is not regular.** Pumping: assume regular with pumping length p; take
s = a^p b^p. Any split with |xy| <= p puts y inside the a's: y = a^k with k >= 1. Then
x y^2 z = a^(p+k) b^p is not in L. Contradiction. Myhill-Nerode, more directly: the strings a^i
(i >= 0) are pairwise distinguishable, since a^i b^i is in L but a^j b^i is not for j != i. Infinitely
many classes, so no DFA exists.

**DFA for binary numbers (most significant bit first) divisible by 3.** Track the value mod 3:
reading bit b turns remainder r into (2r + b) mod 3. Start 0, accept {0}; the empty string counts as
0 (if it must be rejected, add a separate non-accepting start state, giving 4 states).

| state (remainder) | on 0 | on 1 | accepting |
|---|---|---|---|
| 0 | 0 | 1 | yes |
| 1 | 2 | 0 | |
| 2 | 1 | 2 | |

Minimisation from a careless design: tracking the value mod 6 (states 0-5, accept {0, 3}). Moore
refinement: P0 = {0, 3} | {1, 2, 4, 5}. Signatures (successor blocks on 0, 1): 1 and 4 go to (B, A),
2 and 5 to (B, B), so P1 = {0, 3} | {1, 4} | {2, 5}. Next round: 0 and 3 both go to ({0,3}, {1,4}),
1 and 4 to ({2,5}, {0,3}), 2 and 5 to ({1,4}, {2,5}): stable. Three blocks, which are exactly the
remainders mod 3. Lower bound by Myhill-Nerode: the empty string, `1` and `10` (values 0, 1, 2) are
pairwise distinguishable (suffix empty separates 0 from the others; suffix `1` gives 3 vs 5,
separating `1` from `10`), so 3 states is minimal.

Regex by state elimination: eliminating state 2 gives state 1 a loop `01*0`; eliminating state 1
gives state 0 a loop `1(01*0)*1`; result `(0|1(01*0)*1)*`.

Check all three artefacts against arithmetic on every string up to length 12:

```python
import itertools, re

def run(delta, start, accept, s):
    q = start
    for ch in s: q = delta[q][ch]
    return q in accept

def moore(states, alphabet, delta, accept):
    part = {q: q in accept for q in states}
    while True:
        sig = {q: (part[q],) + tuple(part[delta[q][a]] for a in alphabet) for q in states}
        ids = {s: i for i, s in enumerate(sorted(set(sig.values()), key=repr))}
        new = {q: ids[sig[q]] for q in states}
        if len(set(new.values())) == len(set(part.values())): return new
        part = new

mod6 = {r: {"0": 2 * r % 6, "1": (2 * r + 1) % 6} for r in range(6)}
assert len(set(moore(range(6), "01", mod6, {0, 3}).values())) == 3      # {0,3} {1,4} {2,5}
mod3 = {r: {"0": 2 * r % 3, "1": (2 * r + 1) % 3} for r in range(3)}
for n in range(13):
    for bits in itertools.product("01", repeat=n):
        s = "".join(bits)
        want = int(s or "0", 2) % 3 == 0
        assert run(mod3, 0, {0}, s) == want
        assert bool(re.fullmatch(r"(0|1(01*0)*1)*", s)) == want
```

The regex nests stars, so on long non-matching input a backtracking engine may slow down; use the
DFA (or a linear-time engine) for untrusted input.

Related: `regex-engineering`, `compiler-construction`, `type-systems-inference`, `formal-verification-tla-dafny`, hub `cs-foundations`
