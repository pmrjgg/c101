---
name: type-systems-inference
description: "Type system design and inference: soundness (progress and preservation), Hindley-Milner with levels and the value restriction, bidirectional checking, subtyping and variance, generics, traits/type classes and coherence, ownership and substructural types, effects, refinement and dependent types, gradual typing, and debugging hard type errors. Load when designing a checker, writing inference, judging soundness, or untangling a type error."
when_to_use: "Implementing or reviewing a type checker, inference engine or elaborator; a soundness question about a cast, feature or extension; variance errors (List<Dog> vs List<Animal>, in/out, ? extends/super, strictFunctionTypes); occurs-check, 'cannot infer', rigid or weak ('_weak1) type variable errors, Rust E0282/E0308; designing generics, traits or type classes; choosing or configuring mypy, pyright, ty or pyrefly."
---

# Type systems and inference

Designing, implementing and debugging type checkers. Language-specific depth lives in
`haskell-type-level`, `rust-traits-generics`, `rust-ownership-lifetimes`, `typescript-strict-types`,
`python-typing` and `kotlin-java-interop`; parsing and IR in `compiler-construction`; the summary
table stays in `cs-foundations` section 7.

## 1. Concept table (kept from `cs-foundations` section 7, with consequences)

| Concept | Fact | Consequence for design work |
|---|---|---|
| Soundness | progress + preservation, stated relative to an operational semantics | no semantics, no soundness claim; list every escape hatch |
| Hindley-Milner | principal types, decidable inference, let-polymorphism; exponential worst case, near-linear in practice | no annotations for rank-1 code; rank-n, GADTs and subtyping break principality |
| System F | impredicative; full inference undecidable (Wells 1999) | annotate, or check bidirectionally |
| Subtyping variance | functions contravariant in arguments, covariant in results; mutable containers invariant | covariant mutable arrays need run-time store checks |
| Bidirectional typing | check mode for introductions, infer mode for eliminations | annotations at a few predictable places |
| Linear / affine | use exactly / at most once | resources, protocols, Rust ownership |
| Dependent types | types indexed by values; checking evaluates terms | termination checking becomes part of type checking |
| Effects | monads, algebraic effects, effect rows | effect polymorphism is needed for usable higher-order code |
| Gradual typing | blame tracking; casts at boundaries cost time | sound gradual typing checks at run time; erased "optional" typing does not |
| Refinement types | predicates on types discharged by SMT | stay in decidable fragments or face timeouts |

## 2. Soundness workflow

1. Fix syntax, values and an operational semantics (small-step is easiest for progress).
2. Write syntax-directed rules: one rule per term form, so the rules are the algorithm.
3. Prove canonical forms (a value of type `A -> B` is a lambda), weakening, and substitution
   (`G, x:A |- e : B` and `G |- v : A` give `G |- e[v/x] : B`).
4. Progress: a closed well-typed term is a value or steps. Preservation: stepping keeps the type.
5. Mechanise small calculi in Lean 4, Agda or Rocq; test rules first with PLT Redex random testing.
6. State the result precisely: "sound for semantics S, excluding casts and FFI".

Classic breakers: polymorphism plus mutable references (section 3), covariant mutable fields,
unchecked casts, null, exceptions or effects missing from the semantics.

## 3. Hindley-Milner inference

Procedure: give each binder a fresh type variable; generate equality constraints at applications;
solve by unification with an occurs check over union-find variables; generalise at `let`;
instantiate schemes with fresh variables at each use. Level-based generalisation (Remy, as in OCaml)
replaces scanning the environment for free variables: each variable records the let-depth where it
was created, unification lowers levels when a variable escapes into an outer type, and after a
let-bound right-hand side the variables still deeper than the current level are generalisable.

```python
class TVar:
    def __init__(self, level): self.ref, self.level = None, level      # ref: bound type
class TCon:
    def __init__(self, name, args=()): self.name, self.args = name, list(args)  # "->", "int", "list"

def prune(t):                          # follow bindings, compressing the chain
    while isinstance(t, TVar) and t.ref is not None:
        if isinstance(t.ref, TVar) and t.ref.ref is not None: t.ref = t.ref.ref
        t = t.ref
    return t

def occurs_adjust(v, t):               # occurs check + level lowering in one walk
    t = prune(t)
    if t is v: raise TypeError("occurs check: infinite type")
    if isinstance(t, TVar): t.level = min(t.level, v.level)
    else:
        for a in t.args: occurs_adjust(v, a)

def unify(a, b):
    a, b = prune(a), prune(b)
    if a is b: return
    if isinstance(b, TVar): a, b = b, a
    if isinstance(a, TVar): occurs_adjust(a, b); a.ref = b; return
    if a.name != b.name or len(a.args) != len(b.args):
        raise TypeError(f"cannot unify {a.name} with {b.name}")
    for x, y in zip(a.args, b.args): unify(x, y)

def gen_vars(t, level, acc):           # variables created deeper than this let
    t = prune(t)
    if isinstance(t, TVar):
        if t.level > level and t not in acc: acc.append(t)
    else:
        for a in t.args: gen_vars(a, level, acc)
    return acc

def instantiate(scheme, level):        # scheme = (quantified vars, type)
    qs, t = scheme
    fresh = {id(q): TVar(level) for q in qs}
    def go(t):
        t = prune(t)
        if isinstance(t, TVar): return fresh.get(id(t), t)
        return TCon(t.name, [go(a) for a in t.args])
    return go(t)

def infer(env, e, level):              # e: ("var", x) | ("lam", x, b) | ("app", f, a) | ("let", x, rhs, b)
    k = e[0]
    if k == "var": return instantiate(env[e[1]], level)
    if k == "lam":
        a = TVar(level)
        return TCon("->", [a, infer({**env, e[1]: ([], a)}, e[2], level)])
    if k == "app":
        r = TVar(level)
        unify(infer(env, e[1], level), TCon("->", [infer(env, e[2], level), r]))
        return r
    t = infer(env, e[2], level + 1)                                  # let
    qs = gen_vars(t, level, []) if e[2][0] in ("var", "lam") else [] # value restriction
    return infer({**env, e[1]: (qs, t)}, e[3], level)
```

The value restriction (Wright 1995, SML'97) generalises only syntactic values; OCaml's relaxed value
restriction (Garrigue 2004) also generalises variables that occur only covariantly, so
`List.map Fun.id []` stays polymorphic while `ref []` gets a weak variable `'_weak1`. Complexity:
nested lets can double type size at each level (exponential worst case, DEXPTIME-complete); real
programs infer in near-linear time.

## 4. Bidirectional typing

```text
G |- x => A                 if x : A in G
G |- (e : A) => A           if G |- e <= A                    annotation
G |- \x. e <= A -> B        if G, x : A |- e <= B
G |- f e => B               if G |- f => A -> B and G |- e <= A
G |- e <= B                 if G |- e => A and A <: B         subsumption
```

Checking pushes known types inward, so higher-rank arguments, GADT matches and dependent types need
annotations only at predictable points. Dunfield and Krishnaswami ("complete and easy", 2013) extend
this to predicative higher-rank polymorphism: an ordered context holds type variables, existential
variables `^a` (solved to monotypes) and scope markers; every judgment threads an input context to an
output context; subtyping solves existentials through instantiation rules that respect context order
(which enforces scoping); an application judgment instantiates `forall` with fresh existentials.
Annotations are required on top-level definitions (by convention), lambdas in inference position,
higher-rank parameters, GADT pattern matches and polymorphic recursion.

## 5. Subtyping and variance

| Position | Variance | Declaration-site | Use-site |
|---|---|---|---|
| Produced / returned (read-only) | covariant | Kotlin `out T`, Scala `+T`, C# `out` | Java `? extends T` |
| Consumed / argument (write-only) | contravariant | Kotlin `in T`, Scala `-T`, C# `in` | Java `? super T` |
| Read and written | invariant | default | exact type |

PECS: Producer Extends, Consumer Super (`<T> void copy(List<? super T> dst, List<? extends T> src)`).
Structural typing (TypeScript, Go interfaces, OCaml objects) compares shapes; nominal typing (Java,
Kotlin, C#, Rust traits) compares declarations. Known holes:

```java
Object[] objs = new String[1];
objs[0] = 42;                                    // compiles; ArrayStoreException at run time
```

```ts
class Animal { name = "" }
class Dog extends Animal { bark() {} }
const sink = { put(d: Dog) { d.bark(); } };
const any: { put(a: Animal): void } = sink;      // accepted: method parameters are bivariant
any.put(new Animal());                           // TypeError at run time
```

`strictFunctionTypes` makes function-typed properties (`put: (a: Animal) => void`) contravariant;
method-syntax members stay bivariant by design.

## 6. Implementing polymorphism

| Strategy | Languages | Run-time cost | Build cost | Notes |
|---|---|---|---|---|
| Monomorphisation | Rust, C++, Swift (when specialised) | none | code size, compile time | use `dyn Trait` or type erasure on cold paths |
| Erasure | Java, Kotlin, TypeScript | casts, boxing | small | no `new T()` or `is List<String>`; Kotlin `inline fun <reified T>` |
| Dictionary passing | Haskell, Swift witness tables, Go (GC-shape stenciling + dictionaries) | indirect calls | small | GHC specialises with `SPECIALIZE`/`INLINABLE` |

Higher-kinded types: Haskell (`Functor f`), Scala (`F[_]`); Rust has none (GATs cover some uses).
Coherence: one instance per (class, type) program-wide. Rust's orphan rule permits an impl only if
the trait or the type is local; Haskell allows orphan instances with a warning (`-Worphans`), at the
price of possible incoherence. Associated types (Rust `type Item`, Haskell associated families),
type families and GADTs add type-level computation and need annotations at use sites.

## 7. Substructural and ownership types

| Discipline | Rule | Where |
|---|---|---|
| Linear | exactly once | Linear Haskell (`a %1 -> b`), session types |
| Affine | at most once | Rust moves (values may be dropped) |
| Uniqueness | the only reference | Clean; Rust `&mut` behaves similarly |
| Regions / lifetimes | references cannot outlive their region | Rust lifetimes, Cyclone, MLKit |

Rust borrow checking: NLL (MIR-based, liveness-based lifetimes) rejects some correct programs, such as
returning a borrow from one branch and mutating in another (`get_mut` then `insert` on a miss);
Polonius, the in-development successor (nightly `-Zpolonius`), accepts that case. Session types
encode protocols (send, receive, choice) so that both endpoints are dual by construction.

## 8. Effects, refinement and dependent types

- Algebraic effects: OCaml 5 has effect handlers without effect types; Koka types effects with
  row-polymorphic effect rows; Effekt uses capability passing. Rows let `map` be polymorphic in the
  callback's effects.
- Refinement types check predicates with SMT: Liquid Haskell (`{-@ type Pos = {v:Int | v > 0} @-}`),
  F* (dependent types plus SMT), Flux (Rust). Quantifiers and non-linear arithmetic cause timeouts.
- Dependent types (Lean 4, Agda, Idris 2, Rocq): checking compares types by evaluation, so a
  non-terminating term would make checking undecidable and the logic inconsistent; hence
  termination checking (structural recursion, Lean's `termination_by`/`decreasing_by`, `partial`
  as an opt-out that hides the body from the logic).

## 9. Gradual and practical checkers

- TypeScript is unsound by design: `any`, method bivariance, `as` casts, `!` non-null assertions,
  unchecked index access without `noUncheckedIndexedAccess`. `satisfies` checks a value against a
  type without widening its inferred type; conditional types distribute over unions; mapped types
  transform keys.
- Python: mypy (reference, plugins), pyright (fast, strict mode) and basedpyright (stricter fork),
  ty (Astral) and pyrefly (Meta), both young and Rust-based; they differ on inference for
  unannotated code, so pin one per repo. Ruby: Sorbet (`sig`, `T.let`).
- Soundness holes to grep for in review: TS `any`/`as`; Java raw types, unchecked casts, covariant
  arrays; Kotlin platform types (`String!`), `lateinit`, `as List<String>`; Python `Any`, `cast`,
  `# type: ignore`; C# array covariance.

## 10. Implementation techniques

- Binders: named terms need capture-avoiding substitution; de Bruijn indices remove alpha-equivalence
  issues (watch shifting bugs); locally nameless uses indices for bound and names for free
  variables; de Bruijn levels suit values in normalisation by evaluation.
- Unification with union-find (path compression plus rank, or the `prune` trick above).
- Elaborate the surface AST into a typed core IR with explicit type applications and dictionaries
  (GHC Core, Lean kernel terms) and re-check the core with a small trusted checker.
- Errors: report expected vs actual, the provenance of the expectation (annotation at line 12,
  argument 2 of `f`), and never leak internal variable names like `t1234`.
- Testing: generate well-typed terms with type-directed generators and check they type-check and
  evaluate without getting stuck; mutate them into ill-typed terms that must be rejected; compare
  with a reference checker (differential testing).

## 11. Debugging hard type errors

1. Minimise: delete code until the error changes; keep the smallest reproducer.
2. Localise: add annotations at boundaries and bisect to the expression where expected and actual
   first diverge.
3. Ask the checker: GHCi `:t expr` and typed holes (`_` reports the hole's type and relevant
   bindings); `reveal_type(x)` in mypy/pyright; Rust `let () = x;` (the error prints `x`'s type); TS
   twoslash `// ^?` or hover; OCaml/Merlin type-at-point.
4. Recognise the usual causes: variance (`List<Dog>` as `List<Animal>`), implicit conversions or
   literal widening (`"a"` vs `string`), lifetime elision defaults, Haskell's monomorphism
   restriction and defaulting, Kotlin platform types.

## 12. Pitfalls

- Claiming soundness without a semantics, or for the core calculus while shipping casts.
- Generalising non-values (references, mutable caches): the counterexample in section 13.
- Omitting the occurs check: infinite types and a non-terminating unifier.
- Generalising by scanning the environment (quadratic) instead of levels.
- Covariant mutable containers; trusting TypeScript assignability as a safety proof.
- Bidirectional systems without an annotation rule: programs with no way to type them.
- Orphan instances producing two incoherent instances in one program.

## 13. Worked example: `compose`, then the value restriction

`let compose = fun f -> fun g -> fun x -> f (g x)`, inferred at level 1 inside a top-level let:

| Step | Constraint or action | Substitution |
|---|---|---|
| binders | `f : a`, `g : b`, `x : c` | |
| `g x` | `b = c -> d` (fresh `d`) | `b := c -> d` |
| `f (g x)` | `a = d -> e` (fresh `e`) | `a := d -> e` |
| result | `a -> b -> c -> e` | `(d -> e) -> (c -> d) -> c -> e` |
| generalise | `c`, `d`, `e` have level 1 > 0 | `forall c d e` |

Renaming `d, e, c` to `'b, 'c, 'a` gives `('b -> 'c) -> ('a -> 'b) -> 'a -> 'c`; OCaml prints the
alpha-equivalent `('a -> 'b) -> ('c -> 'a) -> 'c -> 'b`.

Why `let r = ref []` must not be generalised: if `r : forall a. a list ref`, then

```ocaml
r := [1];                      (* instantiate a := int *)
print_string (List.hd !r)      (* instantiate a := string: an int read as a string *)
```

type-checks and crashes. `ref []` is an application, not a syntactic value, so the skeleton above
sets `qs = []`; OCaml reports `val r : '_weak1 list ref`, fixes `'_weak1 = int` at the first use, and
rejects the second line ("... has type int but an expression was expected of type string").

Related: `haskell-type-level`, `rust-traits-generics`, `rust-ownership-lifetimes`, `typescript-strict-types`, `python-typing`, `kotlin-java-interop`, `compiler-construction`, hub `cs-foundations`
