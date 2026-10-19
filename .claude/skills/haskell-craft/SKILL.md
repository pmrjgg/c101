---
name: haskell-craft
description: "Haskell expertise pack covering type classes, GADTs, type families, laziness and strictness with space-leak diagnosis, effect systems (mtl, effectful), streaming (conduit, streamly), STM and async, QuickCheck and Hedgehog property testing, GHC optimization flags and profiling, cabal and stack, and common pitfalls. Load when writing, reviewing, debugging or optimizing Haskell code."
when_to_use: "Any task touching .hs/.lhs files, *.cabal, cabal.project, stack.yaml or package.yaml, type-level programming, space leaks, slow Haskell code, concurrency with STM, or Haskell test suites."
---

# Haskell craft

Baseline: GHC 9.10-9.14 (9.14 is the first designated LTS series), `default-language: GHC2024`
(9.10+, otherwise GHC2021), cabal 3.12+ or stack 3.x, GHCup for toolchains, HLS for editor
feedback. Check the exact GHC in use (`ghc --numeric-version`) before using newer extensions
(`RequiredTypeArguments` 9.10, `type data` 9.6, `OverloadedRecordUpdate` still experimental).
Look up library APIs with `mcp__context7__resolve-library-id` then `mcp__context7__query-docs` or Hackage when unsure: effect and
streaming libraries change their APIs between major versions.

Deep material:
[performance, strictness and profiling](references/performance-profiling.md) |
[effects, streaming, STM and testing](references/effects-streaming-testing.md)

## 1. Orient in a repo

```bash
ghc --numeric-version; cabal --version; stack --version 2>/dev/null
ls *.cabal cabal.project* stack.yaml package.yaml hie.yaml fourmolu.yaml .hlint.yaml 2>/dev/null
grep -nE 'default-language|ghc-options|default-extensions' *.cabal package.yaml 2>/dev/null
grep -rhoE 'LANGUAGE [A-Za-z, ]+' src app test 2>/dev/null | sort | uniq -c | sort -rn | head
```

Record: build tool (cabal or stack; do not switch), GHC version, language edition, default
extensions, warnings policy, effect style (ReaderT, mtl, effectful, ...), test framework.

## 2. The gate

| Step | Command | Blocks when |
|---|---|---|
| Build all components | `cabal build all --enable-tests --enable-benchmarks` (stack: `stack build --test --bench --no-run-tests --no-run-benchmarks`) | errors or warnings (CI uses `-Werror`) |
| Tests | `cabal test all --test-show-details=direct` (stack: `stack test`) | failure |
| Lint | `hlint src app test` | new hints not in `.hlint.yaml` ignores |
| Format | `fourmolu --mode check src app test` or `ormolu --mode check $(git ls-files '*.hs')` | diff |
| Package sanity (libraries) | `cabal check` and `cabal outdated` | errors; missing upper bounds |
| Dead code (optional) | `weeder` | unused exports in apps |

Recommended warnings in the `common` stanza:

```cabal
common warnings
  ghc-options: -Wall -Wcompat -Widentities -Wincomplete-record-updates
               -Wincomplete-uni-patterns -Wmissing-deriving-strategies
               -Wpartial-fields -Wredundant-constraints -Wunused-packages
               -Wmissing-export-lists
```

Put `-Werror` in CI flags (`cabal build --ghc-options=-Werror`), not in the package, so
downstream users on newer GHCs are not broken by new warnings (9.14 moved
`-Wincomplete-record-selectors` into `-Wall`).

## 3. Types first: modelling decisions

| Situation | Encoding |
|---|---|
| closed set of alternatives | sum type; pattern match exhaustively (`-Wincomplete-patterns` is in `-Wall`) |
| invariant (non-empty, positive, validated email) | `newtype` with a smart constructor; export the type, not the constructor |
| units / IDs that must not mix | `newtype UserId = UserId Int64 deriving newtype (Eq, Ord, Show, Hashable)` |
| state machine with legal transitions | GADT indexed by a promoted state kind (`DataKinds`) |
| typed AST / interpreter | GADT `Expr a` |
| type-level function (map a type to a type) | closed type family; associated type family when tied to a class |
| per-type configuration of a class | associated type or `DefaultSignatures` |
| optional record fields | `Maybe` fields; never partial record selectors across sum constructors (`-Wpartial-fields`) |
| many related records with shared fields | `OverloadedRecordDot` + `DuplicateRecordFields`, or `NoFieldSelectors` |

Smart constructor template:

```haskell
module Domain.Email (Email, mkEmail, emailText) where

newtype Email = Email Text deriving stock (Eq, Ord, Show)

mkEmail :: Text -> Either Text Email
mkEmail t
  | "@" `T.isInfixOf` t, T.length t <= 254 = Right (Email (T.toLower t))
  | otherwise = Left ("invalid email: " <> t)

emailText :: Email -> Text
emailText (Email t) = t
```

## 4. Type classes

Rules:
1. A class needs laws or at least a clear contract and more than one sensible instance. One
   implementation plus a test fake is better served by a record of functions (handle pattern).
2. No orphan instances in libraries: define the instance next to the class or the type, or wrap
   in a newtype. Apps may confine orphans to one `Orphans` module with `{-# OPTIONS_GHC -Wno-orphans #-}`.
3. Derive explicitly with `DerivingStrategies`: `deriving stock`, `deriving newtype`,
   `deriving anyclass`, `deriving (Semigroup, Monoid) via (Sum Int)`.
4. Test lawful instances with `quickcheck-classes` / `hedgehog-classes`
   (`lawsCheck (monoidLaws (Proxy @MyType))`).
5. Avoid `OverlappingInstances`/`IncoherentInstances`; use per-instance `{-# OVERLAPPABLE #-}`
   only with a written reason.
6. Constraint-polymorphic code (`(MonadReader Env m, MonadIO m) => m a`) costs dictionary passing
   unless specialized; add `{-# INLINABLE #-}` to exported polymorphic functions on hot paths.

## 5. GADTs and type families

```haskell
{-# LANGUAGE GADTs, DataKinds, KindSignatures #-}
data DoorState = Opened | Closed

data Door (s :: DoorState) where
  MkOpen   :: Door 'Opened
  MkClosed :: Door 'Closed

close :: Door 'Opened -> Door 'Closed
close MkOpen = MkClosed          -- closing a closed door does not type-check

data Expr a where
  IntE  :: Int -> Expr Int
  BoolE :: Bool -> Expr Bool
  Add   :: Expr Int -> Expr Int -> Expr Int
  If    :: Expr Bool -> Expr a -> Expr a -> Expr a
  Eq    :: Expr Int -> Expr Int -> Expr Bool

eval :: Expr a -> a
eval (IntE n)   = n
eval (BoolE b)  = b
eval (Add x y)  = eval x + eval y
eval (If c t e) = if eval c then eval t else eval e
eval (Eq x y)   = eval x == eval y
```

```haskell
{-# LANGUAGE TypeFamilies, DataKinds, UndecidableInstances #-}
import GHC.TypeLits
import Data.Kind (Constraint)

type family Elem (x :: k) (xs :: [k]) :: Bool where
  Elem x '[]       = 'False
  Elem x (x ': xs) = 'True
  Elem x (y ': xs) = Elem x xs

type family Require (b :: Bool) (msg :: ErrorMessage) :: Constraint where
  Require 'True  _   = ()
  Require 'False msg = TypeError msg
```

Guidelines:
- Closed type families over open ones unless users must extend them.
- Keep type-level code at the edges (API typing), not in business logic; every type-level trick
  costs compile time and error-message quality. Provide `TypeError` messages for common misuse.
- Existentials (`data Some f where Some :: f a -> Some f`) to hide indices when storing GADTs in
  collections; recover with pattern matching plus a singleton or `Typeable`.
- Use `singletons` only when you need many value-type reflections; otherwise write the 5-line
  singleton GADT by hand.

## 6. Laziness and strictness (summary; full procedure in [performance-profiling](references/performance-profiling.md))

Default stance: lazy spine where streaming helps, strict data in accumulators and long-lived
state.

| Leak pattern | Fix |
|---|---|
| `foldl` building thunks | `foldl'` (exported from Prelude since base-4.20 / GHC 9.10) |
| `modifyIORef ref (+1)` in a loop | `modifyIORef'`, `atomicModifyIORef'` |
| lazy record fields accumulating thunks | `StrictData` per module or bang fields `!Int`; `{-# UNPACK #-}` small fields |
| `Data.Map` with `insertWith (+)` | `Data.Map.Strict` (values forced to WHNF) |
| `State`/`Writer` accumulating | `Control.Monad.State.Strict` plus forcing the state (`modify'`); avoid `Writer` (use `State` or `CPS` writer) |
| lazy IO (`readFile`, `getContents`) | strict `Data.Text.IO.readFile`/`Data.ByteString.readFile`, or streaming |
| `Text`/`ByteString` slice kept as a map key or cached (`T.take`, `TL.words`, `TL.toStrict` of one chunk) pins its whole parent buffer | `T.copy` / `BS.copy` before storing |
| holding a large list via sharing (`length xs` then `sum xs`) | single-pass fold (`foldl'` over a tuple with bangs, or `foldl` library) |
| WHNF not enough (`seq` only evaluates the outer constructor) | `deepseq`/`force` with `NFData`, or strict types all the way down |

Diagnose before fixing: `+RTS -s` (max residency, GC time), then `+RTS -hT` heap profile by
closure type (no profiling build needed); `-hi` info-table profiling for source locations.

## 7. Effects: pick one style per application

| Style | Performance | When |
|---|---|---|
| `ReaderT Env IO` + `MonadUnliftIO` (the ReaderT design pattern) | best, simple | most services; exceptions and concurrency stay in IO |
| mtl classes (`MonadReader`, `MonadError`, `MonadState`) | good when specialized | libraries polymorphic over the monad; small stacks |
| `effectful` | close to ReaderT IO | apps that want typed, interpretable effects and test interpreters |
| `bluefin` | close to IO | effects as explicit value-level handles |
| `polysemy`, free monads | slow | avoid for new code |

Rules: do not mix two effect systems in one codebase; keep `IO` at the edges; express
"capabilities" as effects or handle records so tests swap real I/O for pure interpreters.
Patterns and examples in [effects-streaming-testing](references/effects-streaming-testing.md).

## 8. Concurrency

- Use the `async` library, never raw `forkIO` for work whose result or failure matters:
  `concurrently`, `race`, `mapConcurrently_`, `withAsync` (child cancelled when scope exits).
- STM for shared state with invariants: `TVar`, `TMVar`, `TBQueue` (bounded). Keep
  transactions short and IO-free; `retry` to block until state changes; `orElse` for choice.
- Compile with `-threaded` and run with `+RTS -N` (or `-with-rtsopts=-N`), otherwise the program
  uses one capability and blocking FFI calls stall all threads.
- Exceptions: catching `SomeException` also catches async exceptions (`ThreadKilled`, `timeout`,
  `cancel`) and breaks cancellation. Use `catchAny`/`tryAny` from `unliftio` or `safe-exceptions`
  (they rethrow async exceptions), or catch specific exception types.
- Resource safety: `bracket`, `finally`, `withFile`; `mask` only inside library code.

## 9. Testing

- Unit: `tasty` (with `tasty-hunit`, `tasty-hedgehog`, `tasty-quickcheck`) or `hspec` with
  `hspec-discover`.
- Property tests for every pure function with an algebraic contract: round-trips
  (`decode . encode = Just`), idempotence, invariants after operations, model-based equivalence
  against a simple reference implementation.
- Hedgehog (integrated shrinking, explicit generators) for new code; QuickCheck when the
  ecosystem already uses `Arbitrary` instances.

```haskell
prop_roundtrip :: Property
prop_roundtrip = property $ do
  cfg <- forAll genConfig
  tripping cfg encodeConfig decodeConfig          -- Hedgehog's round-trip helper

genConfig :: Gen Config
genConfig = Config
  <$> Gen.text (Range.linear 1 32) Gen.alphaNum
  <*> Gen.int (Range.linear 1 64)
  <*> Gen.list (Range.linear 0 10) (Gen.element [Debug, Info, Warn])
```

```haskell
prop_sortIdempotent :: [Int] -> Property
prop_sortIdempotent xs =
  cover 10 (length xs > 20) "long lists" $
    sort (sort xs) === sort xs
-- quickCheck (checkCoverage prop_sortIdempotent) fails if coverage targets are missed
```

## 10. GHC performance quick levers (details in [performance-profiling](references/performance-profiling.md))

| Lever | Use |
|---|---|
| `-O2` for executables and hot libraries | default `-O1` is fine for most code |
| `{-# INLINABLE f #-}` on exported polymorphic functions | lets callers specialize across modules |
| `{-# SPECIALIZE f :: Int -> Int #-}` | force a monomorphic copy |
| `-fspecialise-aggressively -fexpose-all-unfoldings` | whole-program specialization for apps (compile-time cost) |
| strict, unpacked fields | `data P = P {-# UNPACK #-} !Double {-# UNPACK #-} !Double` |
| `Text`/`ByteString`/unboxed `Vector` | never `String` or `[a]` for bulk data |
| `-fllvm` | numeric inner loops; needs a supported LLVM |
| RTS: `-A64m` (allocation area), `-N`, `--nonmoving-gc` for large heaps with latency goals | measure with `+RTS -s` |

Inspect Core when performance matters: `-ddump-simpl -dsuppress-all -dsuppress-uniques -ddump-to-file`.

## 11. Pitfalls (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| memory grows, `+RTS -s` max residency huge | thunk build-up (section 6) | strict accumulators, strict maps, heap profile |
| `Prelude.head: empty list` in production | partial functions | `NonEmpty`, pattern match, `listToMaybe`; GHC 9.8+ warns via `-Wx-partial` |
| `read: no parse` | `read` on input | `readMaybe` (`Text.Read`) or a real parser (megaparsec, attoparsec) |
| O(n^2) dedup | `nub` | `nubOrd` (`Data.Containers.ListUtils`) or `Set` |
| timeouts never fire / cancel ignored | catching `SomeException` | `catchAny` from unliftio/safe-exceptions |
| thread silently dies | exception in `forkIO` thread | `async` + `wait`/`link`, or `withAsync` |
| `BlockedIndefinitelyOnMVar/STM` | deadlock: no thread can fill the var | redesign ownership; STM with timeouts via `registerDelay` |
| program uses one core | missing `-threaded` / `+RTS -N` | add both |
| slow polymorphic code | dictionary passing, no specialization | `INLINABLE`/`SPECIALIZE`, check Core |
| `Integer` arithmetic slow | defaulting to `Integer` | type annotations; `-Wtype-defaults` |
| compile times explode | heavy TH, type families, `-O2` everywhere | split modules, `-O1` for non-hot packages, avoid deriving huge `Generic` instances unnecessarily |
| orphan instance conflicts | two libraries define the same orphan | newtype wrappers |
| `Show` used for serialization | not a stable format | `aeson`, `binary`, `cborg` with tests |
| dependency hell | missing bounds or mixed snapshots | cabal `index-state` + `cabal.project.freeze`; stack LTS snapshot |

## 12. Review checklist

- [ ] Types make illegal states unrepresentable where cheap; smart constructors hide raw constructors.
- [ ] No partial functions on untrusted data; `-Wall` clean with the warning set above.
- [ ] Accumulators, state and long-lived records strict; no `foldl`, `modifyIORef` (lazy), lazy maps.
- [ ] Exceptions: async-safe catching, resources acquired with `bracket`/`with*`.
- [ ] Concurrency via `async`/STM; transactions short; bounded queues.
- [ ] Effects style consistent with the codebase; business logic testable without IO.
- [ ] Properties cover round-trips and invariants; generators shrink well; coverage checked.
- [ ] Exported polymorphic hot functions `INLINABLE`; Core inspected for claimed optimizations.
- [ ] Cabal bounds present for libraries; `cabal check` clean; no unused packages.

## 13. Worked example: fixing a space leak in an aggregation

Before: counting words in a 2 GB log uses 6 GB of RAM.

```haskell
countWords :: FilePath -> IO (Map Text Int)
countWords path = do
  contents <- readFile path                                 -- lazy String IO
  pure (foldl (\m w -> Map.insertWith (+) (T.pack w) 1 m) Map.empty (words contents))
```

Problems: `String` (40 bytes per char), lazy `foldl` builds a chain of thunks, `Data.Map.Lazy`
stores `1 + (1 + (1 + ...))` thunks per key, and lazy IO keeps the handle open.

After (constant memory in the file size, proportional to distinct words):

```haskell
import qualified Data.Map.Strict as Map
import qualified Data.Text as T
import qualified Data.Text.Lazy as TL
import qualified Data.Text.Lazy.IO as TLIO
import Data.List (foldl')                  -- redundant on base >= 4.20 (Prelude exports it)

countWords :: FilePath -> IO (Map.Map T.Text Int)
countWords path = do
  contents <- TLIO.readFile path            -- lazy Text, consumed chunk by chunk in one pass
  let !m = foldl' step Map.empty (TL.words contents)
  pure m
  where
    step acc w = Map.insertWith (+) (T.copy (TL.toStrict w)) 1 acc   -- copy: unpin the chunk
```

`Data.Map.Strict.insertWith` forces the count, `foldl'` forces the map at each step, and the lazy
`Text` stream is consumed once. `T.copy` matters: `TL.words` yields slices of the lazy chunks and
`TL.toStrict` of a one-chunk value returns that slice as-is, so an uncopied key would keep its
whole 16-32 KB chunk alive. Verify with `+RTS -s`: max residency should track the number of
distinct words, not the file size. For production pipelines use `conduit`/`streamly` with
explicit resource handling instead of lazy `Text` IO.

## Delegation hints

- Space leaks and RTS tuning with profiles in hand: `code-optimizer` with the `.prof`/`.eventlog` paths.
- Law and property design for a new abstraction: `tester`, giving the path
  `.claude/skills/haskell-craft/SKILL.md` and the line range of section 9 (Testing) in the brief
  (paths, not pasted text).
- Type-level API design trade-offs: `architect` or a second `haskell-expert` pass for review.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `haskell-cabal-builds` | a Haskell build will not resolve, a GHC upgrade is planned, or CI and tooling need setting up |
| `haskell-concurrency-stm` | writing threaded Haskell, sharing state through STM, or debugging blocked or killed threads |
| `haskell-effects` | designing an app's architecture, migrating an effect stack, or making business logic testable without IO |
| `haskell-performance-space-leaks` | Haskell code is slow, allocation-heavy or its memory keeps growing |
| `haskell-testing-properties` | writing or improving Haskell tests, or designing properties for a new abstraction |
| `haskell-type-level` | modelling a domain in types or debugging type-level code |
