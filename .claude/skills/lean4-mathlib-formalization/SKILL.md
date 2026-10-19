---
name: lean4-mathlib-formalization
description: "Formal proofs in Lean 4 with Mathlib: project setup with lake and the Mathlib cache, faithful formalisation of statements (coercions, truncated subtraction, division conventions), choosing a tactic by goal shape, finding lemmas (exact?, Loogle, LeanSearch), structuring proofs, sorry-driven development, reading errors, and checking axioms. Load when a proof should be machine-checked or a Lean file must compile."
when_to_use: "Set up or update a Lean 4 + Mathlib project; translate an informal statement into Lean without changing its meaning; close a goal with the right tactic (norm_num, omega, linarith, nlinarith, positivity, ring, field_simp, gcongr, simp, aesop); find a Mathlib lemma by name, pattern or description; decode a Lean error; or audit a generated proof for sorry, extra axioms or statement drift."
---

# Lean 4 + Mathlib formalisation

Report "Proved (formal)" only when all of these hold:

- you give the file path and the exact build command, and the build exits with status 0;
- the file contains no `sorry` or `admit`;
- `#print axioms` lists only propext, Classical.choice and Quot.sound;
- you have re-read the formal statement against the informal one.

Mathlib renames lemmas often. Confirm any name you are not certain of with `#check` or `exact?`
before relying on it. The snippets target a 2025-2026 Mathlib and were not compiled here, so compile
them first.

## 1. Setup

```bash
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh   # elan toolchain manager
lake new proj math            # new project depending on Mathlib
cd proj
lake exe cache get            # download prebuilt Mathlib .olean files, before the first build
lake build                    # build everything; exit status 0 is the check
lake env lean Proj/Foo.lean   # check one file with the project's search path
```

- **Pins.** `lean-toolchain` pins the Lean version and `lake-manifest.json` pins the Mathlib commit.
  Commit both.
- **Never build Mathlib from source**; it takes hours. If `lake build` starts compiling Mathlib
  files, the cache did not match: the toolchain is mismatched or `cache get` was skipped.
- **Update deliberately.** Run `lake update` (or `lake update mathlib`), then copy Mathlib's
  toolchain (`cp .lake/packages/mathlib/lean-toolchain .`), then `lake exe cache get`, then
  `lake build`. Expect renamed lemmas; deprecation warnings name the replacement.
- **Imports.** Start with `import Mathlib` while exploring, then narrow the imports for CI speed.

## 2. Faithful statements

- **Truncated subtraction on ℕ.** (2 : ℕ) − 5 = 0. Add b ≤ a, or move to ℤ with `zify` / `push_cast`.
  `Nat.cast_sub (h : m ≤ n)` turns ↑(n − m) into ↑n − ↑m.
- **Division on ℕ and ℤ floors.** (7 : ℕ) / 2 = 3. On ℤ, `/` is Euclidean: (−7) / 2 = −4 and
  (−7) % 2 = 1 (confirm with `#eval`). State divisibility with `∣`, or cast to ℚ or ℝ.
- **Division by zero in fields.** x / 0 = 0 (`div_zero`) and 0⁻¹ = 0 (`inv_zero`), so a / b * b = a
  needs b ≠ 0.
- **Junk values.** Real.sqrt x = 0 for x < 0. Real.log 0 = 0 (`Real.log_zero`), and Real.log x is
  defined through the absolute value, so log(−x) = log x. Add 0 ≤ x or 0 < x when the informal
  statement assumes it.
- **Coercions.** Write casts explicitly in statements, as `(n : ℝ)`.
  - `push_cast` moves casts toward the leaves.
  - `norm_cast` and `exact_mod_cast h` close goals that differ from h only by casts.
  - `zify`, `qify` and `rify` lift ℕ goals to ℤ, ℚ or ℝ; `zify [h]` uses h : b ≤ a to handle
    subtraction.
- **Ranges.** `Finset.range n` is {0, ..., n − 1}; use `Finset.Icc 1 n` for 1..n.
- **Sum notation.** Write `∑ i ∈ s, f i`; the older `∑ i in s, f i` spelling is deprecated.
- **Quantifiers over ℕ** include 0. Add `0 < n` when that is intended.
- **Re-read.** Put the informal claim and the Lean statement side by side. Check that every
  hypothesis is used (the linter flags unused ones). Instantiate the theorem on a concrete case
  (`example : ... := my_thm 3`) to see that it says what you expect.

## 3. Tactic by goal shape

| Goal shape | First tactic | Notes |
|---|---|---|
| closed numeric fact: 2^10 = 1024, (7 : ℝ)/2 < 4, Nat.Prime 97 | `norm_num` | extensions cover primality, divisibility, powers |
| decidable statement about small finite data (∀ x : Fin 5, ...) | `decide` | kernel evaluation; slow on large instances |
| linear arithmetic over ℕ or ℤ, with numeral ×, / and % | `omega` | handles truncated subtraction and division by numerals |
| linear (in)equalities over an ordered field, from hypotheses | `linarith` | nonlinear terms are opaque atoms |
| polynomial inequality | `nlinarith [sq_nonneg (a - b), mul_pos ha hb]` | multiplies pairs of hypotheses and hints; supply the right products |
| 0 < e, 0 ≤ e or e ≠ 0 with e built from positive pieces | `positivity` | syntactic; fails on subtraction |
| equality in a commutative (semi)ring | `ring` | `ring_nf` normalises without closing |
| equality with denominators | `field_simp` then `ring` | needs x ≠ 0 facts in context |
| f a ≤ f b from a ≤ b, with matching shape | `gcongr` | leaves side goals, often closed by positivity |
| upper or lower bounds of real expressions | `bound` | |
| rewriting with the simp set | `simp`, `simp only [...]`, `simp?` | `simp?` prints a stable `simp only` call |
| propositional or structural search | `aesop` | |
| mixed equalities, congruence closure, arithmetic | `grind` | recent toolchains only |
| Continuous f, Differentiable ℝ f, Measurable f | `fun_prop` | `continuity`, `measurability` are older and slower |
| ∃ x, P x | `use x`, `refine ⟨x, ?_⟩`, `exists x` | |
| goal and hypothesis differ only by casts | `exact_mod_cast h`, `push_cast`, `norm_cast` | |
| finitely many cases | `interval_cases n`, `fin_cases i`, `rcases` | |
| equality that is a linear combination of hypotheses | `linear_combination e₁ * h₁ + e₂ * h₂` | |

## 4. Finding lemmas

- **In the editor.** `exact?` closes the goal with a library term and prints `exact foo ...`.
  `apply?` lists lemmas whose conclusion unifies with the goal; `rw?` suggests rewrites; `simp?`
  and `hint` (tries common tactics) round out the set.
- **Naming conventions.** A name spells out its conclusion, with symbols as words: add, mul, sub,
  neg, div, inv, pow, zero, one, abs, sq, le, lt, succ.
  - Plain: `mul_comm : a * b = b * a`, `mul_pos : 0 < a → 0 < b → 0 < a * b`,
    `sub_nonneg : 0 ≤ a - b ↔ b ≤ a`.
  - `_of_` separates the conclusion from the hypotheses: `le_of_lt : a < b → a ≤ b`.
  - `_iff_` marks an iff: `Nat.lt_iff_add_one_le`.
  - `_left` / `_right` say which argument moves:
    `mul_le_mul_of_nonneg_left : b ≤ c → 0 ≤ a → a * b ≤ a * c`.
- **Loogle** (https://loogle.lean-lang.org) searches by constants, name substrings and patterns:
  `Real.sqrt, Real.exp`, `"sum_range"`, `?a * ?b ≤ ?a * ?c`, `|- tsum _ = _`. The site documents
  the exact syntax.
- **LeanSearch** (https://leansearch.net) takes natural-language queries such as "square root of a
  product".
- **Inspect.** `#check @mul_pos` shows the full signature with implicit arguments, and `#print`
  shows a definition. Go-to-definition shows the source and the lemmas around it.

## 5. Proof structure

```lean
example (a b : ℝ) (h : ∃ x : ℝ, 0 < x ∧ x * a = b) (ha : 0 < a) : 0 < b := by
  obtain ⟨x, hx, rfl⟩ := h            -- destructure ∃ and ∧; rfl replaces b by x * a
  exact mul_pos hx ha

example (a b c : ℝ) (hab : a ≤ b) (hbc : b < c) : a < c + 1 := by
  calc a ≤ b := hab
    _ < c := hbc
    _ < c + 1 := by linarith

example (f : ℕ → ℕ) (h : ∀ n, f n ≤ f (n + 1)) : ¬ ∃ n, f (n + 1) < f n := by
  push_neg                             -- goal becomes ∀ n, f n ≤ f (n + 1)
  exact h

example (n : ℕ) (h : n = 0 ∨ n = 1) : n ^ 2 = n := by
  rcases h with rfl | rfl <;> norm_num
```

- **Introducing facts.** `have h : P := proof` or `have h : P := by tac`. `obtain ⟨x, hx⟩ := h`
  and `rcases` destructure; `rintro x ⟨y, rfl⟩` introduces and destructures in one step.
- **Induction.** `induction n with | zero => ... | succ n ih => ...`. For finsets use
  `induction s using Finset.induction_on`; its case names and binder layout have changed between
  Mathlib versions, so read them in the goal view.
- **Indirect proofs.** `by_contra h` then `push_neg at h`; `contrapose! h` negates and swaps goal
  and hypothesis.
- **Goal management.** `cases`, `constructor` (∧ and ↔), `refine ⟨?_, ?_⟩` (one goal per hole),
  and `·` to focus a goal.
- **Targeted rewriting.** `conv_lhs => rw [mul_comm]` rewrites only the left side;
  `nth_rw 2 [h]` rewrites only the second occurrence.

## 6. Sorry-driven development

```lean
-- skeleton: the statements must fit together before any leaf is proved
theorem main (n : ℕ) (hn : 2 ≤ n) : P n := by
  have h1 : Q n := lemma_q n hn       -- already proved
  have h2 : R n := by sorry           -- open leaf
  exact combine h1 h2
```

1. Write the whole skeleton with one `sorry` per lemma. `lake build` passes with "declaration uses
   'sorry'" warnings, which shows the statements compose.
2. Close the leaves first, keeping each lemma under about 20 lines, and rebuild after each one.
3. Never report a result whose dependencies still contain sorry; `#print axioms` exposes it as
   `sorryAx`.

## 7. Reading errors

| Message | Usual cause | Fix |
|---|---|---|
| type mismatch with ↑n on one side | a cast sits in a different place than expected | `push_cast at h ⊢`, `exact_mod_cast`, explicit `(n : ℝ)` in the statement |
| failed to synthesize HAdd ℕ ℝ ?m | mixed types without a cast | add a type ascription or a cast |
| failed to synthesize Fact (1 < p), DecidableEq, Fintype | missing instance | `haveI := Fact.mk hp`, `classical`, add `[Fintype α]` |
| motive is not type correct (from rw) | the rewritten term occurs inside a dependent type | `simp only [h]`, rw inside `conv`, `subst`, or `generalize` first |
| deterministic timeout, maxHeartbeats | heavy simp, decide or instance search | `simp only`, smaller lemmas; temporarily `set_option maxHeartbeats 400000 in` |
| maximum recursion depth in simp | a looping simp lemma (commutativity, say) | `simp only` without it, or `simp [-lemma]` |
| unknown identifier or constant | renamed lemma, missing import or namespace | `exact?`, `#check`, `open` the namespace, follow the deprecation hint |
| linarith failed | a nonlinear term or a missing fact | add the fact with `have`, or `nlinarith` with product hints |
| unsolved goals | the tactic left subgoals | read the goal view; focus with `·` |
| don't know how to synthesize placeholder | an implicit argument cannot be inferred | named argument `(α := ℝ)`, or `@lemma` with explicit arguments |

## 8. Trust check

```lean
#print axioms sum_odd
-- expected: a subset of [propext, Classical.choice, Quot.sound]
```

- **Allowed:** any subset of propext, Classical.choice and Quot.sound.
- **`sorryAx`:** sorry was used, directly or in a dependency.
- **`Lean.ofReduceBool`:** `native_decide` was used, which trusts the compiler. Say so in the
  report. Newer toolchains may list a further compiler-trust axiom; check what yours prints.
- **A user `axiom`:** the result is conditional on it. Pass it as a hypothesis instead (section 9).
- **Grep.** `grep -rnE '\bsorry\b|\badmit\b|^axiom |native_decide' Proj/` must come back empty, or
  every hit must be justified.
- **CI.** Require `lake build` to exit 0, the grep to come back empty, and a `Check.lean` whose
  `#print axioms` output is compared with the allowed list.

## 9. Scope

- **Formalise the crux, not the paper**: the step a referee would doubt, an inequality chain, a
  combinatorial identity, a case analysis.
- **Missing infrastructure becomes a hypothesis.** If Mathlib lacks something you need, write it as
  an explicit hypothesis, `theorem crux (hX : MissingStatement) : Claim`. That yields "Proved
  (formal) assuming X" with X visible; report the gap as an Open doubt. Never add an `axiom`.
- **Budget.** If the formalisation needs new definitions and API (hundreds of lines), stop and
  report. A careful paper proof plus a formal crux is usually the right deliverable.

## 10. AI-assisted proving

- Accept generated proofs only after `lake build` passes and the trust check is clean.
- **Statement drift**: the model proved a different theorem. Detectors:
  - hypotheses added (0 < n, x ≠ 0) or quantifiers narrowed (∀ n ≥ 1 instead of ∀ n);
  - truncated subtraction or division making the statement trivial ((a − b : ℕ) = 0);
  - junk values (x / 0 = 0, √ of a negative) carrying the proof;
  - vacuous hypotheses: exhibit an instance that satisfies them all, because contradictory
    hypotheses prove anything;
  - a weakened conclusion (≤ instead of <, ∃ instead of ∀).
- Quote the final Lean statement next to the informal one in the report.
- `exact?`, `aesop` and LLM provers only propose; the kernel decides.

## 11. Worked example

```lean
import Mathlib

open Finset in
theorem sum_odd (n : ℕ) : ∑ i ∈ range n, (2 * i + 1) = n ^ 2 := by
  induction n with
  | zero => simp
  | succ n ih =>
    rw [sum_range_succ, ih]
    ring

theorem am_gm2 (a b : ℝ) : a * b ≤ ((a + b) / 2) ^ 2 := by
  nlinarith [sq_nonneg (a - b)]

#print axioms sum_odd
#print axioms am_gm2
```

- **Induction step.** `Finset.sum_range_succ` states
  ∑ x ∈ range (n + 1), f x = ∑ x ∈ range n, f x + f n. After rewriting with it and with ih, the goal
  is n ^ 2 + (2 * n + 1) = (n + 1) ^ 2, and `ring` closes it (no subtraction occurs in ℕ).
- **Base case.** The empty sum is 0 and 0 ^ 2 = 0, which `simp` closes.
- **AM-GM.** ((a + b)/2)² − ab = (a − b)²/4. With the hint `sq_nonneg (a - b)`, the goal is linear
  in the monomials a², ab and b², so `nlinarith` closes it. Without the hint it may fail.
- **Axioms.** Expect a subset of [propext, Classical.choice, Quot.sound]. Proofs about ℝ typically
  print all three, as in 'am_gm2' depends on axioms: [propext, Classical.choice, Quot.sound].
- **Build.** `lake env lean Proj/Basic.lean` or `lake build` must exit 0, followed by the sorry grep.
- **Faithfulness.** `range n` = {0, ..., n−1}, so the theorem says Σ_{i=0}^{n−1} (2i + 1) = n², the
  sum of the first n odd numbers, for every n ≥ 0. The AM-GM form holds for all real a and b. The
  usual form √(ab) ≤ (a + b)/2 needs 0 ≤ a and 0 ≤ b, and involves Real.sqrt.

## 12. Pitfalls

- **Trusting a green editor without `lake build`** (stale .olean files, unsaved buffers).
- **sorry in a dependency, or `native_decide` left unreported.**
- **Statement mismatches.** ℕ subtraction, x / 0, the range offset, missing positivity hypotheses.
- **`decide` on large instances.** It times out; prefer `norm_num` or `omega`.
- **Non-terminal `simp`.** It makes proofs fragile; freeze it with `simp only [...]` from `simp?`.
- **Updating Mathlib without `lake exe cache get`.**
- **Lemma names from memory.** Confirm with `#check` or `exact?`.
- **`set_option maxHeartbeats 0`.** It hides performance problems instead of fixing them.

Related: `proof-techniques-and-writing`, `inequality-proving`, `sympy-symbolic-verification`, `number-theory-modular`, `haskell-craft`, hub `mathematics-toolkit`
