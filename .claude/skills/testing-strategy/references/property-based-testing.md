# Property-based testing reference

Framework snippets, generator design, stateful testing and failure handling. Pair with section 4 of
the SKILL.md for the property pattern catalog.

## Framework snippets

### Hypothesis (Python)
```python
from hypothesis import given, settings, example, strategies as st

@st.composite
def durations(draw):
    h = draw(st.integers(0, 999)); m = draw(st.integers(0, 59)); s = draw(st.integers(0, 59))
    return h * 3600 + m * 60 + s

@settings(max_examples=1000, deadline=None)   # deadline=None when timing varies (I/O, JIT)
@given(durations())
@example(0)                                     # pin known edge cases explicitly
def test_format_parse_roundtrip(secs):
    assert parse_duration(format_duration(secs)) == secs
```
- Failing examples are cached in `.hypothesis/` and replayed first; commit nothing from it, but copy the
  shrunk counterexample into an `@example(...)` or a plain test.
- Reproduce a CI failure locally with `pytest --hypothesis-seed=<seed printed in CI>`.
- `st.from_type(MyDataclass)` and `st.builds(MyClass, field=st.integers(0, 10))` derive generators.
- Health checks fail when `.filter()` rejects too much; replace filters with constructive generators.
- `hypothesis.event("bucket")` plus `--hypothesis-show-statistics` shows the input distribution.
- `hypothesis.target(score)` steers generation toward larger scores (search for worst cases).

### proptest (Rust)
```rust
use proptest::prelude::*;

proptest! {
    #![proptest_config(ProptestConfig::with_cases(1000))]
    #[test]
    fn roundtrip(h in 0u64..1000, m in 0u64..60, s in 0u64..60) {
        let secs = h * 3600 + m * 60 + s;
        prop_assert_eq!(parse_duration(&format_duration(secs)).unwrap(), secs);
    }

    #[test]
    fn sort_is_ordered(mut v in proptest::collection::vec(any::<i64>(), 0..200)) {
        my_sort(&mut v);
        prop_assert!(v.windows(2).all(|w| w[0] <= w[1]));
    }
}
```
- Failures persist to `proptest-regressions/<module>.txt`; commit these files so CI replays them.
- `PROPTEST_CASES=10000 cargo test` raises case count for a nightly job.
- Compose generators with `prop_compose!`, `prop_oneof![...]`, `Just(x)`, `.prop_map`, `.prop_flat_map`.
- Derive generators for your types with the `proptest-derive` crate (`#[derive(Arbitrary)]`).

### QuickCheck and Hedgehog (Haskell)
```haskell
import Test.QuickCheck
prop_reverseInvolutive :: [Int] -> Bool
prop_reverseInvolutive xs = reverse (reverse xs) == xs
main :: IO ()
main = quickCheck (withMaxSuccess 1000 prop_reverseInvolutive)
```
```haskell
import Hedgehog
import qualified Hedgehog.Gen as Gen
import qualified Hedgehog.Range as Range
prop_rev :: Property
prop_rev = property $ do
  xs <- forAll (Gen.list (Range.linear 0 100) Gen.alpha)
  reverse (reverse xs) === xs
```
QuickCheck needs hand-written `shrink` in `Arbitrary` instances; Hedgehog shrinks integrated with the
generator, which avoids shrinking to invalid values.

### fast-check (JS/TS)
```ts
import fc from 'fast-check';
import { test, expect } from 'vitest';

test('sort is an ordered permutation', () => {
  fc.assert(
    fc.property(fc.array(fc.integer()), (xs) => {
      const out = mySort([...xs]);
      for (let i = 1; i < out.length; i++) expect(out[i - 1]).toBeLessThanOrEqual(out[i]);
      expect([...out].sort((a, b) => a - b)).toEqual([...xs].sort((a, b) => a - b));
    }),
    { numRuns: 1000 },
  );
});
```
A failure prints `seed` and `path`; pass `{ seed, path }` back into `fc.assert` to replay it exactly.
`fc.commands` with `fc.modelRun` provides model-based (stateful) testing.

### jqwik (Java) and Kotest (Kotlin)
```java
@Property(tries = 1000)
boolean reverseTwiceIsIdentity(@ForAll List<Integer> xs) {
    var copy = new ArrayList<>(xs);
    Collections.reverse(copy); Collections.reverse(copy);
    return copy.equals(xs);
}
```
```kotlin
class ConcatProps : StringSpec({
    "length of concatenation" {
        checkAll<String, String> { a, b -> (a + b).length shouldBe a.length + b.length }
    }
})
```

### rapid (Go)
```go
func TestSortProps(t *testing.T) {
    rapid.Check(t, func(t *rapid.T) {
        xs := rapid.SliceOf(rapid.Int()).Draw(t, "xs")
        ys := slices.Clone(xs)
        MySort(ys)
        if !slices.IsSorted(ys) {
            t.Fatalf("not sorted: %v", ys)
        }
    })
}
```
`pgregory.net/rapid` shrinks automatically and supports state machines (`t.Repeat` with action maps).
The standard library `testing/quick` is frozen and does not shrink; prefer rapid or native fuzzing.

### Julia
Supposition.jl provides Hypothesis-style generation and shrinking; for quick randomized checks,
`@testset` loops over `rand` inputs with a fixed `Random.seed!` work but do not shrink.

## Stateful (model-based) testing

Generate random sequences of operations, apply each to the real system and to a simple model, and
assert they agree after every step.

```python
from collections import OrderedDict
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

class LRUMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.real = LRUCache(capacity=3)
        self.model = OrderedDict()

    @rule(k=st.integers(0, 5), v=st.integers())
    def put(self, k, v):
        self.real.put(k, v)
        self.model[k] = v
        self.model.move_to_end(k)
        if len(self.model) > 3:
            self.model.popitem(last=False)

    @rule(k=st.integers(0, 5))
    def get(self, k):
        expected = self.model.get(k)
        if k in self.model:
            self.model.move_to_end(k)
        assert self.real.get(k) == expected

    @invariant()
    def size_bounded(self):
        assert len(self.real) <= 3

TestLRU = LRUMachine.TestCase
```
Equivalents: `proptest-state-machine` (Rust), `fc.commands` (fast-check), jqwik action chains,
`quickcheck-state-machine` / `quickcheck-dynamic` (Haskell), rapid state machines (Go).

Good targets: caches, allocators, queues, file-system-like APIs, CRDT merges, connection pools, any
API where bugs appear only after a specific sequence of calls.

## Generator design rules

1. Generate what the code accepts. If the function requires sorted input, generate unsorted lists and
   sort them; do not filter for sortedness.
2. Small key spaces surface collisions: draw keys from `integers(0, 5)` rather than all integers when
   testing maps and caches.
3. Mix sizes: empty and single-element collections are where most bugs live; frameworks bias toward them,
   do not override that bias without reason.
4. Avoid generating with the code under test (a generator that calls `format()` to make inputs for
   `parse()` hides bugs in `format()` from the round trip).
5. Keep each example fast: a property that takes 50 ms per example times 1000 examples is a 50 s test.
6. Record the seed in CI logs and make it replayable.

## When a property fails

1. Read the shrunk counterexample; it is usually the clearest bug report you will get.
2. Decide: code bug, or wrong property? A wrong property (the spec allows that output) is fixed by
   correcting the property, with the reasoning stated, never by narrowing the generator to avoid the case.
3. Add the counterexample as an explicit example test.
4. Fix the code; rerun the property with a higher example count once.

## Choosing properties when you are stuck

- What must never happen? (crash, negative balance, duplicate ID, data loss)
- What is preserved? (count, sum, set of elements, ordering of equal keys, total money)
- What can be undone? (encode/decode, compress/decompress, serialize/deserialize, apply/revert)
- What does a slower obvious implementation compute? (brute force, naive loop, old version)
- What changes predictably when the input changes predictably? (metamorphic relations)
