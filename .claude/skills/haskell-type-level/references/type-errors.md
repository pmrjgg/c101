# Type-level error decoder

Messages and codes below were reproduced on GHC 9.10.3. Look up any code with
`https://errors.haskell.org/messages/GHC-<code>/`. Wording drifts between releases; the code is stable.

## 1. Error table

| Code | Message (abridged) | Usual cause | Fix |
|---|---|---|---|
| GHC-64725 | your `TypeError` text, e.g. "Illegal connection transition: Connecting -> Closed" | a custom error family reduced to `TypeError` | the call is illegal by design; change the call or the table |
| GHC-22250 | your `Unsatisfiable` text | instance guarded by `Unsatisfiable` (9.8+) | use the suggested alternative |
| GHC-22979 | "Illegal nested use of type family 'Elem' in the arguments of the type-family application" | family call nested in an equation RHS | `UndecidableInstances` after checking termination |
| GHC-22979 | "The constraint 'C x' is no smaller than the instance head" | instance context as large as the head | `UndecidableInstances`, or restructure the instance |
| GHC-40404 | "Reduction stack overflow; size = 201 / When simplifying the following type: ..." | infinite or very deep family recursion | fix the base case; `-freduction-depth=N` (0 = unlimited) only for deep finite input |
| GHC-05175 | "Type family equation right-hand sides overlap; this violates the family's injectivity annotation" | two equations of an injective family share a RHS | make RHSs distinct or drop the annotation |
| GHC-25897 | "Couldn't match type 'a1' with 'a' ... 'a1' is a rigid type variable bound by a pattern with constructor" | an existential's hidden type returned | CPS or carry a singleton |
| GHC-25897 | "Could not deduce 'p ~ Int' from the context: a ~ Int ... bound by a pattern with constructor" | GADT match in a function without a signature | add the signature |
| GHC-25897 | "Couldn't match kind 'k' with 'Nat'" | unannotated `forall n. Proxy n` became poly-kinded | `forall (n :: Nat).` |
| GHC-39999 | "Could not deduce 'KnownSymbol s0' ... The type variable 's0' is ambiguous ... In the ambiguity check" | variable only in constraints | `AllowAmbiguousTypes` + `@s`, or `forall s ->` (9.10+) |
| GHC-39999 | "No instance for 'Typeable a0' arising from a use of 'Dyn'" | literal with an ambiguous type (often `OverloadedStrings`) | annotate the literal |
| GHC-83865 | "Couldn't match type: n + 1 with: 1 + n ... NB: '+' is a non-injective type family" | symbolic arithmetic | `ghc-typelits-natnormalise` plugin |
| GHC-83865 | "Couldn't match type 'True' with 'False' / Expected: Door False, Actual: Door True" | wrong index, the intended rejection | fix the call site |
| GHC-87139 | "Illegal deriving strategy: stock" / "...: via" | `DerivingStrategies` / `DerivingVia` off (GHC2021 default) | GHC2024 or the extension |
| GHC-15013 | "Illegal type-level data declaration" | `type data` without `TypeData` | add `TypeData` (9.6+) |
| GHC-82712 | warning "Use of partial record field selector" | `-Wpartial-fields` on a multi-constructor record | one record type per constructor |
| GHC-17335 | warning "The application of the record field 'radius' may fail for the following constructors: Rect" | `-Wincomplete-record-selectors` (9.10+, in `-Wall` from 9.14) | pattern match instead of the selector |
| GHC-28007 | warning "Misplaced LANGUAGE pragma" | pragma after the `module` line | move it above `module` |

## 2. Debugging workflow for a type-level error

1. Read the innermost "When simplifying the following type" or "Expected/Actual" pair first; the
   outer context lines only locate the expression.
2. Ask GHCi what a family reduces to: after `:load Conn.hs` and `:module + *Conn` (exposes
   unexported names), `:kind! Elem '( 'Connecting, 'Closed) Transitions` prints `= False` and
   `:kind! Legal 'Connected 'Closed` prints `= () :: Constraint`. `:info Conn` lists constructors
   and instances.
3. Show hidden detail: `-fprint-explicit-kinds` (kind arguments), `-fprint-explicit-foralls`,
   `-fprint-potential-instances` (all candidate instances), `-fprint-expanded-synonyms`.
4. Shrink: copy the failing expression into a scratch module with only the needed types and
   compile with `ghc -fno-code Scratch.hs` (seconds, no linking).
5. Explore with holes: replace a subterm with `_` (typed hole) to see the expected type and the
   relevant bindings in scope.
6. Last resort: `-ddump-tc-trace` (very long) to see which constraint the solver gets stuck on.
7. `-fdefer-type-errors` lets the rest of a module compile while you explore, but do not use it
   as a "should not compile" test: unused evidence never forces the deferred error. Use a
   compile-fail script that runs `ghc -fno-code` and greps the message instead.

## 3. Compile-time budget checks

| Signal | Command | Threshold to act |
|---|---|---|
| per-pass time and allocation | `cabal build --ghc-options=-ddump-timings` | one module dominating the build |
| typechecker load | look at the `Renamer/typechecker` lines in the timings | seconds on a small module |
| reduction depth | errors at `-freduction-depth` 200 | any; inspect the recursion |
| generated code size | `-ddump-simpl -ddump-to-file` + `wc -l` | `Generic`/TH instances in tens of thousands of lines |
