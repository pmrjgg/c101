# Core before and after: the meanVar loop

Abridged, simplified `-ddump-simpl -dsuppress-all -dsuppress-uniques` output for the `meanVar`
example (SKILL.md section 12.2). Exact names, argument order and worker shapes vary between GHC
versions: look for the features called out below, not for identical text.

## Before: polymorphic, lazy accumulators

```text
meanVar
  = \ @a $dFractional n f ->
      let { $dNum = $p1Fractional $dFractional } in
      letrec {
        go = \ i s ss ->
          case i of { I# i# ->
          case n of { I# n# ->
          case ==# i# n# of {
            __DEFAULT ->
              let { x = f (I# i#) } in
              go (I# (+# i# 1#)) (+ $dNum s x) (+ $dNum ss (* $dNum x x));
            1# -> ... } } } } in
      go (I# 0#) (fromInteger $dNum (IS 0#)) (fromInteger $dNum (IS 0#))
```

What to see:

- `@a $dFractional`: the function is still polymorphic, so every arithmetic operation is an
  unknown call through `$dNum`; `+` and `*` cannot be inlined.
- `(+ $dNum s x)` passed as a lazy argument to `go` is allocated as a thunk on every iteration:
  this is the `s`/`ss` thunk chain that grows with `n`.
- `let { x = f (I# i#) }`: one more thunk per iteration.
- `I# (+# i# 1#)`: the loop counter is boxed again for every call.

## After: specialised to Double, strict accumulators

```text
$w$s$wgo                                  -- name and result shape vary by GHC version
  = \ i# s## ss## ->
      case ==# i# n# of {
        __DEFAULT ->
          case f (I# i#) of { D# x## ->
          $w$s$wgo (+# i# 1#) (+## s## x##) (+## ss## (*## x## x##)) };
        1# -> ... }
```

What to see:

- No dictionary arguments: `+##` and `*##` are primitive `Double#` operations.
- The accumulators travel as unboxed `Double#` values: no thunks and no `D#` boxes in the loop.
- `f (I# i#)` still boxes its argument and result because `f` is an unknown function. If that
  call dominates the profile, make `meanVar` `INLINE` so that `f` is known at the call site.

## Checking allocation in STG

`-ddump-stg-final -dsuppress-all` on the same module shows what the loop allocates: every `let`
in STG is a heap allocation. After the fix the hot loop body contains only `case` expressions
and the tail call, and tasty-bench under `+RTS -T` reports near-zero allocation per run apart
from the result tuple.
