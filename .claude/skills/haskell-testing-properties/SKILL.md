---
name: haskell-testing-properties
description: "Haskell test suites. Covers tasty or hspec layout with discovery, choosing between Hedgehog, QuickCheck and falsify, generator and shrinking design, coverage-checked properties, law tests, model-based state-machine tests, and golden and doctest suites. Load when writing or improving Haskell tests, or designing properties for a new abstraction."
when_to_use: "Adding or fixing a Haskell test-suite stanza; writing Hedgehog or QuickCheck properties, generators or shrinkers; 'Gave up! Passed only N tests' or high discard counts; properties that pass only on trivial inputs; law tests for Eq, Ord, Semigroup, Monoid, Functor or aeson instances; model-based or state-machine tests of a stateful API; golden files or doctests; replaying a failing seed from CI."
---

# Haskell testing and properties

A property states what must hold for every input; the library generates inputs, and on failure
shrinks to a minimal counterexample. Good suites pair a few readable unit tests with properties
whose generators reach the interesting cases, verified by coverage checks rather than hope.

Baseline: tasty 1.5, tasty-hedgehog 1.4+, hedgehog 1.4+, QuickCheck 2.14+, hspec 2.11+.

## 1. Suite layout

```cabal
test-suite spec
  import:           warnings
  type:             exitcode-stdio-1.0
  hs-source-dirs:   test
  main-is:          Main.hs
  other-modules:    CodecSpec, PQueueSpec
  build-depends:    base, mypkg, aeson, aeson-pretty, bytestring, text,
                    tasty, tasty-hunit, tasty-hedgehog, tasty-quickcheck, tasty-golden,
                    hedgehog, QuickCheck
  ghc-options:      -threaded -rtsopts -with-rtsopts=-N
```

```haskell
module Main (main) where
import Test.Tasty (defaultMain, testGroup)
import qualified CodecSpec
import qualified PQueueSpec

main :: IO ()
main = defaultMain (testGroup "mypkg" [CodecSpec.tests, PQueueSpec.tests])

-- in each module
tests :: TestTree
tests = testGroup "Codec"
  [ testPropertyNamed "round trip" "hprop_roundTrip" hprop_roundTrip   -- Test.Tasty.Hedgehog
  , testCase "empty name rejected" (mkName "" @?= Nothing)            -- Test.Tasty.HUnit
  , QC.testProperty "idempotent normalise" prop_normalise ]           -- qualified Test.Tasty.QuickCheck
```

- tasty-hedgehog 1.2+ deprecates `testProperty` in favour of `testPropertyNamed`; import the
  QuickCheck runner qualified because both packages export `testProperty`.
- hspec: `test/Spec.hs` contains only `{-# OPTIONS_GHC -F -pgmF hspec-discover #-}`; modules
  named `*Spec.hs` export `spec :: Spec`; add `build-tool-depends: hspec-discover:hspec-discover`.
  Properties via `Test.Hspec.QuickCheck.prop` or the hspec-hedgehog package.
- tasty-discover does the same for tasty: one pragma in `Main.hs`, functions prefixed `prop_`
  (QuickCheck), `hprop_` (Hedgehog), `unit_` (HUnit), `test_` (any `TestTree`).

| Runner | Select tests | Example |
|---|---|---|
| tasty | `-p PATTERN` (awk-like) | `--test-options='-p "/PQueue/"'`, `-p '$NF == "round trip"'` |
| hspec | `--match`, `--skip` | `--test-options='--match "/Codec/"'` |

Pick tasty when mixing frameworks or needing per-library options; hspec for BDD-style suites.

## 2. Library choice

| | Hedgehog | QuickCheck | falsify |
|---|---|---|---|
| generators | explicit `Gen` values | `Arbitrary` type class (plus explicit `Gen`) | explicit generators |
| shrinking | integrated: shrinks follow the generator, invariants preserved | per-type `shrink`, written by hand, can break invariants | internal: shrinks the random sample, works through monadic bind |
| ecosystem | tasty-hedgehog, hspec-hedgehog, hedgehog-classes | largest: quickcheck-instances, quickcheck-classes, quickcheck-state-machine, quickcheck-dynamic | newer, smaller |
| stateful testing | built-in `Command` API | quickcheck-state-machine, quickcheck-lockstep | none built in |

Defaults: Hedgehog for new code; QuickCheck when the codebase or its dependencies already
provide `Arbitrary` instances; falsify when Hedgehog's integrated shrinking degrades on
monadic generators (its tasty runner is `Test.Tasty.Falsify`; check the API of your version).
One library per suite where possible.

## 3. Property catalogue

| Pattern | Statement | Typical target |
|---|---|---|
| round trip | `decode (encode x) == Right x`: Hedgehog `tripping x encode eitherDecode` | codecs, parsers/printers |
| idempotence | `f (f x) == f x` | normalisation, formatting, sorting |
| invariant after operation | `valid (insert k v m)` | balanced trees, heaps, smart constructors |
| model or oracle | `toSortedList (fromList xs) == sort xs` | data structures, optimised rewrites |
| metamorphic | `length (search (q <> extra)) <= length (search q)` | search, ranking, numerics without an oracle |
| algebraic laws | associativity, identity, `fmap id == id` | instances (section 6) |
| easy to check, hard to compute | output sorted and a permutation of the input | solvers, schedulers |

Never restate the implementation inside the property; compare against something simpler
(a list, a `Map`, a brute-force search) or a relation the output must satisfy.

## 4. Generators

```haskell
genUser :: Gen User
genUser = do
  name  <- Gen.text (Range.linear 1 40) Gen.alphaNum
  age   <- Gen.int (Range.linear 0 120)
  email <- genEmail
  either (const Gen.discard) pure (mkUser name age email)   -- valid parts make this branch dead

genTree :: Gen (Tree Int)
genTree = Gen.recursive Gen.choice
  [ pure Leaf ]
  [ Gen.subterm2 genTree genTree (\l r -> Node l 0 r) ]
```

| Range | Use |
|---|---|
| `Range.linear 0 100` | size grows linearly with the test size |
| `Range.linearFrom 0 (-100) 100` | shrink towards an origin inside the range |
| `Range.exponential 1 1000000` | values spanning orders of magnitude |
| `Range.constant 0 10` | ignore size (small fixed domains) |

- `Gen.frequency [(9, genTypical), (1, genEdge)]` to seed edge cases (empty, max bound,
  duplicates); `Gen.element`, `Gen.choice`, `Gen.sized`, `Gen.set`/`Gen.map` for distinct keys.
- QuickCheck equivalents: `chooseInt`, `frequency`, `oneof`, `elements`, `sized`, `resize`,
  `listOf`, `vectorOf`; `shrink` via `genericShrink` or by shrinking the constructor inputs.
- Build valid values by construction: generate inputs to a smart constructor that it always
  accepts, or sort/dedupe generated data (`sort <$> list`), instead of filtering.
- Filter-heavy generators: Hedgehog stops after too many discards (`withDiscards`), QuickCheck
  reports "Gave up! Passed only N tests". Above ~10% discards, restructure the generator.

## 5. Distribution and coverage

```haskell
-- QuickCheck: checkCoverage turns cover into a statistical test that fails when unmet
prop_insertValid :: [Int] -> Int -> Property
prop_insertValid xs x =
  classify (null xs) "empty" $
  cover 20 (length xs > 10) "long" $
  tabulate "size bucket" [show (length xs `div` 10 * 10)] $
  valid (insert x (fromList xs))
-- quickCheck (checkCoverage prop_insertValid)

-- Hedgehog: cover fails the property when its percentage is not reached
hprop_insertValid :: Property
hprop_insertValid = property $ do
  xs <- forAll (Gen.list (Range.linear 0 50) (Gen.int (Range.linear 0 100)))
  classify "empty" (null xs)
  cover 20 "long" (length xs > 10)
  cover 5 "has duplicates" (length xs /= length (nubOrd xs))
  assert (valid (foldr insert empty xs))
```

Targets: each interesting class at 5-20%, every listed edge case at 1% or more. A property that
passes while "has duplicates" sits at 0% has not tested duplicates at all.

## 6. Law testing

```haskell
import Data.Proxy (Proxy (..))
import Test.QuickCheck.Classes (Laws (..), eqLaws, ordLaws, semigroupLaws, monoidLaws, jsonLaws)

lawTests :: TestTree
lawTests = testGroup "laws"
  [ testGroup (lawsTypeclass l) [QC.testProperty n p | (n, p) <- lawsProperties l]
  | l <- [eqLaws pq, ordLaws pq, semigroupLaws pq, monoidLaws pq, jsonLaws cfg] ]
  where
    pq  = Proxy :: Proxy (PQueue Int)    -- needs Arbitrary (PQueue Int)
    cfg = Proxy :: Proxy Config
```

- quickcheck-classes-base covers base classes; quickcheck-classes adds aeson (`jsonLaws`:
  partial isomorphism, and `toEncoding` agreeing with `toJSON`) and more.
- hedgehog-classes takes generators instead of proxies:
  `lawsCheckMany [("Config", [eqLaws genConfig, jsonLaws genConfig])]`; check that a release
  supports your GHC before adopting it.
- Functor and Traversable laws need generators for the container (`functorLaws (Proxy :: Proxy Tree)`).
- An `Eq` instance on an abstract type compares observable content (e.g. `toSortedList`), not
  internal shape, or the laws reject valid structures.

## 7. State-machine testing

Model a stateful API (mutable heap, cache, database wrapper, HTTP service) as commands with
preconditions, model updates and postconditions; Hedgehog generates and shrinks command
sequences.

```haskell
newtype Model (v :: Type -> Type) = Model [Int]               -- sorted list is the oracle
data Push (v :: Type -> Type) = Push Int deriving (Show)
data Pop  (v :: Type -> Type) = Pop      deriving (Show)
instance FunctorB Push where bmap _ (Push n) = Push n          -- Data.Functor.Barbie (barbies)
instance TraversableB Push where btraverse _ (Push n) = pure (Push n)
instance FunctorB Pop where bmap _ Pop = Pop
instance TraversableB Pop where btraverse _ Pop = pure Pop

cmdPush, cmdPop :: (MonadGen g, MonadIO m) => Heap -> Command g m Model
cmdPush h = Command (\_ -> Just (Push <$> Gen.int (Range.linear (-100) 100)))
                    (\(Push n) -> liftIO (pushHeap h n))
                    [ Update (\(Model xs) (Push n) _ -> Model (insert n xs)) ]
cmdPop h = Command (\(Model xs) -> if null xs then Nothing else Just (pure Pop))
                   (\Pop -> liftIO (popHeap h))                -- IO (Maybe Int)
                   [ Require (\(Model xs) Pop -> not (null xs))
                   , Update (\(Model xs) Pop _ -> Model (drop 1 xs))
                   , Ensure (\(Model before) _ Pop out -> out === listToMaybe before) ]

hprop_heapModel :: Property
hprop_heapModel = withTests 300 . property $ do
  h <- evalIO newHeap
  actions <- forAll $ Gen.sequential (Range.linear 1 100) (Model []) [cmdPush h, cmdPop h]
  evalIO (clearHeap h)              -- after forAll: runs again for every shrink attempt
  executeSequential (Model []) actions
```

- `Require` keeps shrunk sequences valid; without it shrinking produces impossible histories.
- `Gen.parallel` plus `executeParallel` checks linearizability of thread-safe implementations.
- QuickCheck side: quickcheck-state-machine, quickcheck-lockstep or quickcheck-dynamic.

## 8. Golden and doc tests

```haskell
import Test.Tasty.Golden (goldenVsString)
import qualified Data.Aeson.Encode.Pretty as P

goldenConfig :: TestTree
goldenConfig = goldenVsString "config JSON shape" "test/golden/config.json"
  (pure (P.encodePretty' P.defConfig { P.confCompare = compare } sampleConfig))   -- sorted keys
```

- Accept intentional changes with `cabal test --test-options=--accept`, then review the golden
  diff in version control like code.
- Round-trip properties cannot catch a renamed field (both directions change together); a
  golden file of the wire format can. Use both for any persisted or public format.
- Doctests: examples in Haddock (`-- >>> inc 41` followed by `-- 42`, and `-- prop> \xs -> ...`).
  Run with cabal-docspec after `cabal build` (binary from its GitHub releases), or doctest
  through `cabal repl --with-compiler=doctest` (see the doctest README for your version), or
  doctest-parallel as a test-suite.

## 9. Running

```bash
cabal test --test-show-details=direct                        # stream output, see shrunk counterexamples
cabal test spec --test-options='-p "/PQueue/" --hedgehog-tests 2000'
cabal test --test-options='--quickcheck-tests 10000'
cabal test --test-options="--hedgehog-replay '<string printed by the failure>'"
cabal test --test-options='--quickcheck-replay=<seed printed by the failure>'
cabal test --test-options='--timeout 60s'                    # tasty: fail hung tests
```

- hspec: `--seed N` reproduces a run, `--qc-max-success N` raises the test count.
- CI: cache the cabal store keyed on `dist-newstyle/cache/plan.json` (see `haskell-cabal-builds`);
  run the default counts per push and a nightly job with 10-50x more tests; paste the replay
  string into the bug report whenever a property fails.

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| property can never fail | restates the implementation | compare with a model or a relation |
| "Gave up!" or discard limit hit | filtering generator | build valid values directly (section 4) |
| passes, but bugs slip through | generator never reaches the edge cases | `cover`/`checkCoverage`, `Gen.frequency` with edge cases |
| shrunk counterexample is invalid | hand-written `shrink` ignores invariants | shrink constructor inputs, or Hedgehog |
| orphan `Arbitrary` instances clash | instances spread over test modules | newtype wrappers or one internal test-support library |
| flaky properties | time, randomness or IO inside the property | inject clock and RNG; seed explicitly |
| `Double` round trip fails on precision | exact equality on floats | compare with a tolerance, or generate representable values |
| golden test accepted blindly | `--accept` without review | review the diff in the PR |
| state machine explores impossible histories | missing `Require` | add preconditions |
| deprecation warnings from tasty-hedgehog | `testProperty` | `testPropertyNamed` |
| suite too slow | large sizes, huge test counts on every push | cap ranges, `withTests`, nightly heavy runs |

## 11. Worked example: a JSON codec and a priority queue against a sorted-list model

Codec: round trip plus a golden file.

```haskell
data Level = Debug | Info | Warn deriving (Eq, Show, Generic, Enum, Bounded)
data Config = Config { name :: Text, workers :: Int, levels :: [Level] }
  deriving (Eq, Show, Generic)
instance ToJSON Level
instance FromJSON Level
instance ToJSON Config
instance FromJSON Config

genConfig :: Gen Config
genConfig = Config
  <$> Gen.text (Range.linear 0 32) Gen.unicode           -- non-ASCII exercises escaping
  <*> Gen.int (Range.linearFrom 1 minBound maxBound)     -- shrinks towards 1
  <*> Gen.list (Range.linear 0 5) Gen.enumBounded

hprop_jsonRoundTrip :: Property
hprop_jsonRoundTrip = property $ do
  cfg <- forAll genConfig
  cover 10 "empty name" (T.null (name cfg))
  cover 10 "non-ASCII name" (T.any (> '\DEL') (name cfg))
  tripping cfg encode eitherDecode
```

Priority queue: random operation sequences checked step by step against `Data.List.insert` on
a sorted list (the model), plus the structural invariant.

```haskell
data Op = Ins Int | Pop deriving (Eq, Show)

genOp :: Gen Op
genOp = Gen.frequency [(3, Ins <$> Gen.int (Range.linearFrom 0 (-1000) 1000)), (1, pure Pop)]

hprop_pqMatchesModel :: Property
hprop_pqMatchesModel = property $ do
  ops <- forAll (Gen.list (Range.linear 0 200) genOp)
  cover 20 "two or more pops" (length (filter (== Pop) ops) >= 2)
  cover 10 "duplicate keys" (hasDuplicates [x | Ins x <- ops])
  let go pq model [] = do
        assert (PQ.valid pq)                              -- heap-order invariant
        PQ.toSortedList pq === model
      go pq model (Ins x : rest) = go (PQ.insert x pq) (L.insert x model) rest
      go pq model (Pop : rest) = do
        let r = PQ.popMin pq
        fmap fst r === listToMaybe model                  -- popped minimum agrees with the model
        go (maybe pq snd r) (drop 1 model) rest
  go PQ.empty [] ops
```

`hasDuplicates` can be `\xs -> length xs /= length (nubOrd xs)`. Add `lawTests` (section 6) for
`Eq`, `Ord` and `Semigroup` (merge) on `PQueue Int`, with `Eq` defined through `toSortedList`.

Run it:

```bash
cabal test --test-show-details=direct --test-options='-p "/PQueue/" --hedgehog-tests 1000'
```

What a real bug looks like (illustrative): a merge that drops equal keys fails within a few dozen
tests and shrinks to `ops = [Ins 0, Ins 0, Pop, Pop]`, with the failing `===` showing
`Nothing` against `Just 0`. Fix, rerun with the printed `--hedgehog-replay` string to confirm,
then keep the counterexample as a HUnit regression test.

Acceptance: both properties pass 1000 tests with every `cover` met; the golden file matches the
documented wire format; the law tests pass for every instance the module exports.

Related: `haskell-cabal-builds`, `haskell-performance-space-leaks`, `haskell-effects`, `haskell-concurrency-stm`, hub `haskell-craft`
