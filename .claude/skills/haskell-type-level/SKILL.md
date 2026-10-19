---
name: haskell-type-level
description: "Type-driven Haskell from newtypes to type-level programming: a modelling ladder, smart constructors and pattern synonyms, deriving strategies and DerivingVia, class laws and orphan rules, GADTs, DataKinds state machines, closed type families with TypeError, existentials and singletons, records. Load when modelling a domain in types or debugging type-level code."
when_to_use: "Designing data types or APIs in .hs files; code using GADTs, DataKinds, TypeFamilies, DerivingVia, PatternSynonyms, RequiredTypeArguments or type data; errors such as 'Reduction stack overflow', 'Illegal nested use of type family', 'is no smaller than the instance head', 'Could not deduce (KnownNat n)', 'is a rigid type variable bound by a pattern with constructor', 'Use of partial record field selector'; orphan or overlapping instance trouble."
---

# Haskell type-level modelling

Baseline: GHC 9.10-9.14, `default-language: GHC2024` in the cabal file. GHC2024 adds `DataKinds`,
`GADTs`, `LambdaCase`, `DerivingStrategies`, `RoleAnnotations`, `MonoLocalBinds` and others to
GHC2021. A bare `ghc` call on 9.10 still defaults to GHC2021, which is why `deriving stock` there
fails with "Illegal deriving strategy". Not in GHC2024, so still per module: `TypeFamilies`,
`TypeFamilyDependencies`, `UndecidableInstances`, `PatternSynonyms`, `DerivingVia`, `TypeData`,
`RequiredTypeArguments`, `AllowAmbiguousTypes`, `OverloadedRecordDot`.

| Feature | Since |
|---|---|
| `Generically` for `DerivingVia` (Semigroup/Monoid) | 9.4 (base-4.17) |
| `type data` (`TypeData`); `SNat`/`natSing`/`withKnownNat` in `GHC.TypeLits` | 9.6 (base-4.18) |
| `GHC.TypeError.Unsatisfiable` | 9.8 (base-4.19) |
| GHC2024 edition; `RequiredTypeArguments` (`forall a ->`); `-Wincomplete-record-selectors` | 9.10 |
| visible `forall` in data constructors; `-Wincomplete-record-selectors` in `-Wall`; promoted types in kinds without `DataKinds` is an error (was the `-Wdata-kinds-tc` warning); type applications in patterns need `TypeAbstractions` | 9.14 |

Check `ghc --numeric-version` before using a row. Deep material:
[typed AST, singletons and TypeLits](references/singletons-typelits.md) |
[type error decoder](references/type-errors.md)

## 1. Modelling ladder: take the cheapest rung that rules out the bug

| Rung | Encoding | Rules out | Cost |
|---|---|---|---|
| 0 | sum type, exhaustive `case` (`-Wincomplete-patterns` is in `-Wall`) | forgotten alternatives | none |
| 1 | `newtype` + smart constructor, constructor not exported | invalid values (empty, negative, unvalidated email) | one module |
| 2 | phantom type `newtype Id (t :: Type) = Id Int64` or `Html 'Escaped` | mixing IDs and units, unescaped data | role annotations |
| 3 | GADT indexed by a promoted kind (`Conn 'Connected`) | illegal state transitions | existentials to store values |
| 4 | typed AST `Expr a` | ill-typed programs in an embedded language | a typechecker from the untyped AST |
| 5 | type families, type-level lists, `TypeError` | invalid combinations computed from types | compile time, error quality |

Climb only when the bug class is real (a production incident or a reviewer finding) and the
lower rung cannot express it. Common domain decisions:

| Situation | Encoding |
|---|---|
| closed set of alternatives | sum type, exhaustive match |
| invariant (non-empty, positive, validated email) | `newtype` + smart constructor; export the type, not the constructor |
| units / IDs that must not mix | `newtype UserId = UserId Int64 deriving newtype (Eq, Ord, Show, Hashable)` |
| state machine with legal transitions | GADT indexed by a promoted state kind (section 4; worked example in section 9) |
| typed AST / interpreter | GADT `Expr a` |
| type-level function (type to type) | closed type family; associated family when tied to a class |
| per-type configuration of a class | associated type or `DefaultSignatures` |
| optional record fields | `Maybe` fields; never partial selectors across sum constructors |
| many records sharing field names | `OverloadedRecordDot` + `DuplicateRecordFields`, or `NoFieldSelectors` |

## 2. Smart constructors and read-only pattern synonyms

```haskell
{-# LANGUAGE PatternSynonyms #-}
module Domain.Email (Email, pattern Email, mkEmail, emailText) where  -- MkEmail not exported

import qualified Data.Text as T

newtype Email = MkEmail T.Text deriving stock (Eq, Ord, Show)

mkEmail :: T.Text -> Either T.Text Email
mkEmail raw
  | "@" `T.isInfixOf` t, T.length t <= 254 = Right (MkEmail t)
  | otherwise                              = Left ("invalid email: " <> raw)
  where t = T.toLower (T.strip raw)

emailText :: Email -> T.Text
emailText (MkEmail t) = t

pattern Email :: T.Text -> Email      -- unidirectional: matches, cannot construct
pattern Email t <- MkEmail t
{-# COMPLETE Email #-}                -- otherwise -Wincomplete-patterns fires on every match
```

- Clients write `case e of Email t -> ...`; `Email "x"` as an expression is a compile error, so
  the invariant has exactly one entry point.
- Hiding the constructor also blocks `coerce :: Text -> Email`: `Coercible` needs it in scope.
- Types whose invariant depends on a parameter's instances (`Set a` needs `Ord a`) get
  `type role Set nominal` so `coerce` cannot swap in a newtype with a different `Ord`.
- Validate once at the boundary (parser, HTTP handler); internal functions take `Email`, never `Text`.

## 3. Type classes

Rules:
1. A class needs laws or a written contract **and** more than one sensible instance. One
   implementation plus a test fake is a record of functions (handle pattern, `haskell-effects`).
2. No orphan instances in libraries (`-Worphans` is in `-Wall`): define the instance next to the
   class or the type, or wrap the type in a newtype. Apps may confine orphans to one `Orphans`
   module with `{-# OPTIONS_GHC -Wno-orphans #-}`.
3. Derive explicitly; turn on `-Wmissing-deriving-strategies`.
4. Avoid `OverlappingInstances`/`IncoherentInstances`; a per-instance `{-# OVERLAPPABLE #-}` or
   `{-# OVERLAPPING #-}` needs a comment saying why.
5. Exported constraint-polymorphic functions on hot paths get `{-# INLINABLE f #-}` so callers can
   specialize (dictionary passing otherwise; see `haskell-performance-space-leaks`).

| Strategy | Generates | Use for |
|---|---|---|
| `deriving stock` | structural code (`Eq`, `Ord`, `Show`, `Functor`, `Generic`, `Lift`) | data types |
| `deriving newtype` | reuses the wrapped type's instance via `coerce` | `newtype UserId = UserId Int64 deriving newtype (Eq, Ord, Hashable)` |
| `deriving anyclass` | empty instance, class defaults (often `Generic`-based) | `ToJSON`, `NFData` |
| `deriving ... via T` | instance of a representationally equal type `T` | Monoid choice, generic recipes |

```haskell
{-# LANGUAGE DerivingVia #-}
import Data.Monoid (Sum (..))
import GHC.Generics (Generic, Generically (..))

newtype Score = Score Int
  deriving stock (Show)
  deriving newtype (Eq, Ord, Num)
  deriving (Semigroup, Monoid) via (Sum Int)          -- Score 2 <> Score 3 == Score 5

data Stats = Stats { hits :: Sum Int, misses :: Sum Int }
  deriving stock (Show, Generic)
  deriving (Semigroup, Monoid) via (Generically Stats) -- field-wise <>, mempty
```

Law tests (put them in the test suite of the package that owns the instance):

```haskell
import Test.QuickCheck.Classes (lawsCheck, lawsCheckMany, monoidLaws, eqLaws, ordLaws)
main :: IO ()
main = do
  let p = Proxy @Score                                       -- quickcheck-classes 0.6: Proxy a -> Laws
  lawsCheck (monoidLaws p)
  lawsCheckMany [("Score", [eqLaws p, ordLaws p, monoidLaws p])]
-- hedgehog-classes 0.2: lawsCheck (monoidLaws genScore) :: IO Bool, laws take a Gen a
```

`quickcheck-classes` needs an `Arbitrary` instance; `hedgehog-classes` takes a generator. A
failing law prints the counterexample: turn it into a unit test before fixing.

## 4. GADTs

Typed expression evaluator: the index makes `eval` total with no runtime type checks.

```haskell
data Expr a where
  IntE  :: Int -> Expr Int
  BoolE :: Bool -> Expr Bool
  Add   :: Expr Int -> Expr Int -> Expr Int
  If    :: Expr Bool -> Expr a -> Expr a -> Expr a
  Eq    :: Expr Int -> Expr Int -> Expr Bool

eval :: Expr a -> a
eval = \case
  IntE n   -> n
  BoolE b  -> b
  Add x y  -> eval x + eval y
  If c t e -> if eval c then eval t else eval e
  Eq x y   -> eval x == eval y
```

Indexed state machine: each constructor fixes the index, so a function's type lists the states it
accepts.

```haskell
data DoorState = Opened | Closed
data Door (s :: DoorState) where
  MkOpen   :: Door 'Opened
  MkClosed :: Door 'Closed

close :: Door 'Opened -> Door 'Closed
close MkOpen = MkClosed            -- closing a closed door does not type-check
```

Storing GADTs in collections hides the index behind an existential; recover it with one of:

| Recovery | When | Code |
|---|---|---|
| match on the GADT constructor | every constructor determines the index | `stateOf (SomeConn c) = case c of CConnected{} -> Connected; ...` |
| hand-written singleton | phantom index not visible in the value, or a parser output | `data Ty a where TInt :: Ty Int; TBool :: Ty Bool` + `eqTy :: Ty a -> Ty b -> Maybe (a :~: b)` |
| `Typeable` | open set of types, plugin-like registries | `eqTypeRep (typeRep @a) (typeRep @Int)` gives `Maybe (a :~~: Int)` |

```haskell
data SomeExpr where SomeExpr :: Ty a -> Expr a -> SomeExpr   -- singleton travels with the value
typecheck :: UExpr -> Either String SomeExpr                  -- full version in the reference
```

An existential cannot escape: `unwrap :: Some f -> f a; unwrap (Some x) = x` fails with
"Couldn't match type 'a1' with 'a' ... 'a1' is a rigid type variable bound by a pattern with
constructor" [GHC-25897]. Continue in CPS (`withSome :: SomeConn -> (forall s. Conn s -> r) -> r`)
or return something that does not mention the index. A GADT match without a type signature fails
the same way ("Could not deduce 'p ~ Int' from the context: a ~ Int"): give GADT functions signatures.

## 5. Type families

| Kind | Syntax | Extensible | Use |
|---|---|---|---|
| closed | `type family F a where ...` | no; equations tried top to bottom, overlap allowed | default: `Elem`, `If`, table lookups |
| open | `type family F a` + `type instance F Int = ...` | by anyone, no overlap | only when users must extend it |
| associated | `class C f where type Elem f :: Type` | per instance | the type is part of a class's contract |
| data family | `data family Vec a` | per instance, injective | representation chosen per type |

- **Injectivity**: `type family Wrap a = r | r -> a` (`TypeFamilyDependencies`) lets GHC infer `a`
  from `Wrap a`. Two equations with the same RHS are rejected ("violates the family's injectivity
  annotation").
- **UndecidableInstances guard**: GHC demands it for a nested family call in an equation
  (`Len (_ ': xs) = 1 + Len xs` gives "Illegal nested use of type family") and for instance
  contexts no smaller than the head. Turn it on per module, and only after checking that recursion
  shrinks an argument. Runaway recursion stops at `-freduction-depth` (default 200, "Reduction
  stack overflow; size = 201"); raise it for deep but finite lists, `0` disables the check.
- **Custom errors** for common misuse:

```haskell
import GHC.TypeLits (ErrorMessage (..), TypeError)        -- also exported by GHC.TypeError
type family Check (ok :: Bool) (from :: k) (to :: k) :: Constraint where
  Check 'True  _    _  = ()
  Check 'False from to = TypeError ('Text "Illegal transition: " ':<>: 'ShowType from
                                    ':<>: 'Text " -> " ':<>: 'ShowType to)

-- 9.8+: reject an instance with a message instead of "No instance for ..."
instance Unsatisfiable ('Text "Functions have no Pretty instance; wrap them in a newtype")
  => Pretty (a -> b) where pretty = unsatisfiable
```

`ErrorMessage` combinators: `'Text`, `'ShowType`, `':<>:` (same line), `':$$:` (new line).
`GHC.TypeError.Assert :: Bool -> Constraint -> Constraint` packages the `Check` pattern.

## 6. DataKinds and kinds

- Promotion: `data ConnState = Disconnected | Connected` gives types `'Disconnected :: ConnState`.
  Tick promoted constructors (`-Wunticked-promoted-constructors`) where a type of the same name
  exists. Type-level lists: `'[Int, Bool]`, `x ': xs`; tuples: `'(a, b)`.
- Give every type-level declaration a standalone kind signature (`type Elem :: k -> [k] -> Bool`);
  polykinded inference otherwise produces surprising kinds.
- `type data Phase = Parsed | Checked` (`TypeData`, 9.6+) declares type-level-only constructors:
  no unused value constructors, no tick ambiguity.
- `GHC.TypeLits`: `natVal (Proxy @n) :: Integer` needs `KnownNat n`; `symbolVal` needs
  `KnownSymbol s`; runtime to type via `someNatVal :: Integer -> Maybe SomeNat`; evidence as
  values with `natSing`, `fromSNat`, `withKnownNat` (9.6+); compare with `sameNat`, `cmpNat`. GHC
  solves arithmetic (`+`, `*`, `<=?`, `CmpNat`) only on literals; for `n + 1 ~ 1 + n` use the
  `ghc-typelits-natnormalise` plugin.
- A function whose type variable appears only in constraints (`greet :: forall s. KnownSymbol s =>
  String`) is rejected as ambiguous. Choose between `AllowAmbiguousTypes`, so callers write
  `greet @"x"`, or a required type argument (9.10+), so callers write `greet "x"`:

```haskell
{-# LANGUAGE RequiredTypeArguments #-}
symName :: forall (s :: Symbol) -> KnownSymbol s => String
symName s = symbolVal (Proxy @s)          -- symName "required" == "required"
sizeOfT :: forall a -> Storable a => Int
sizeOfT a = sizeOf (undefined :: a)       -- sizeOfT Double == 8
```

## 7. Records

| Need | Extension / tool | Note |
|---|---|---|
| `p.name` access, also nested (`c.owner.name`) | `OverloadedRecordDot` (via `GHC.Records.HasField`) | the default for new code |
| same field name in several records | `DuplicateRecordFields` | combine with dot syntax; bare ambiguous selectors fail |
| no top-level selector functions | `NoFieldSelectors` | frees names like `id`, `name` |
| computed ("virtual") field | `instance HasField "initial" Person Char where getField p = T.head p.name` | `p.initial` works like a field |
| record update syntax via `HasField` | `OverloadedRecordUpdate` | experimental, needs `RebindableSyntax`; use plain update or lenses |
| partial selectors | `-Wpartial-fields` (definition site), `-Wincomplete-record-selectors` (use site) | give each constructor its own record type instead |

```haskell
data Shape = Circle { radius :: Double } | Rect { w :: Double, h :: Double }  -- -Wpartial-fields
area s = pi * radius s ^ 2   -- 9.10+: "The application of the record field 'radius' may fail for ... Rect"
-- fix: data Shape = SCircle Circle | SRect Rect, with one record type per constructor
```

## 8. Costs and boundaries

- Keep type-level machinery at API edges (a typed protocol, a state machine module, a query
  builder); business logic sees plain types. Every trick costs compile time and error quality.
- Measure before and after: `cabal build -v1 --ghc-options=-ddump-timings` (per-pass time/alloc)
  on the heavy module. A module that jumps by seconds after a type-level change gets split.
- Error quality: write the `TypeError`/`Unsatisfiable` messages users will see; debug with
  `-fprint-explicit-kinds`, `-fprint-potential-instances`, `:kind! F Int` in GHCi.
- `singletons` libraries (`singletons`, `singletons-th`, `singletons-base`) pay off when many
  functions must exist at value and type level (promotion with defunctionalisation). Costs:
  Template Haskell, slow builds, orphan `Sing` instances, and `singletons-base` 3.5.1 supports only
  the newest GHC (9.14), so it pins your compiler. One or two reflected kinds: write the
  five-line singleton GADT by hand ([reference](references/singletons-typelits.md)).
- Phantom-indexed newtypes cost nothing at runtime; GADT constructors are ordinary heap objects;
  `KnownNat` constraints are dictionaries passed at runtime.

## 9. Worked example: connection state machine with a checked transition table

Goal: illegal transitions (`Connecting -> Closed`) fail at compile time with a readable message;
valid sources for "disconnect" and "close" come from one table. Compiled and run on GHC 9.10.3.

```haskell
{-# LANGUAGE GHC2024 #-}               -- DataKinds, GADTs, KindSignatures, LambdaCase
{-# LANGUAGE TypeFamilies #-}          -- no UndecidableInstances: Elem shrinks its list argument
module Conn (ConnState (..), Conn, SomeConn (..), Host, Socket (..), newConn, open, connected,
             disconnect, close, stateOf) where

import Data.Kind (Constraint, Type)
import GHC.TypeLits (ErrorMessage (..), TypeError)

data ConnState = Disconnected | Connecting | Connected | Closed deriving stock (Show, Eq)
type Host = String
newtype Socket = Socket Int deriving stock Show

type Transitions :: [(ConnState, ConnState)]
type Transitions =
  '[ '( 'Disconnected, 'Connecting), '( 'Connecting, 'Connected), '( 'Connecting, 'Disconnected)
   , '( 'Connected, 'Disconnected), '( 'Disconnected, 'Closed), '( 'Connected, 'Closed) ]

type Elem :: k -> [k] -> Bool
type family Elem x xs where
  Elem _ '[]       = 'False
  Elem x (x ': _)  = 'True
  Elem x (_ ': xs) = Elem x xs

type Legal :: ConnState -> ConnState -> Constraint
type Legal from to = Check (Elem '(from, to) Transitions) from to

type Check :: Bool -> ConnState -> ConnState -> Constraint
type family Check ok from to where
  Check 'True  _    _  = ()
  Check 'False from to = TypeError
    (     'Text "Illegal connection transition: "
    ':<>: 'ShowType from ':<>: 'Text " -> " ':<>: 'ShowType to
    ':$$: 'Text "Legal transitions are listed in Conn.Transitions" )

type Conn :: ConnState -> Type
data Conn s where
  CDisconnected :: Conn 'Disconnected
  CConnecting   :: Host -> Conn 'Connecting
  CConnected    :: Host -> Socket -> Conn 'Connected
  CClosed       :: Conn 'Closed
deriving stock instance Show (Conn s)

newConn :: Conn 'Disconnected
newConn = CDisconnected

open :: Host -> Conn 'Disconnected -> Conn 'Connecting          -- fixed edges: plain types
open h CDisconnected = CConnecting h

connected :: Socket -> Conn 'Connecting -> Conn 'Connected
connected sock (CConnecting h) = CConnected h sock

disconnect :: Legal s 'Disconnected => Conn s -> IO (Conn 'Disconnected)  -- table-checked
disconnect _ = pure CDisconnected

close :: Legal s 'Closed => Conn s -> IO (Conn 'Closed)
close = \case
  CConnected _ (Socket fd) -> putStrLn ("closing fd " <> show fd) >> pure CClosed
  _                        -> pure CClosed

data SomeConn where SomeConn :: Conn s -> SomeConn                 -- for Map Int SomeConn

stateOf :: SomeConn -> ConnState                                   -- index recovered by matching
stateOf (SomeConn c) = case c of
  CDisconnected -> Disconnected; CConnecting{} -> Connecting
  CConnected{}  -> Connected;    CClosed       -> Closed
```

```haskell
main = do                                   -- prints "closing fd 7", CClosed, then the pool states
  let c0 = open "db.internal" newConn       -- Disconnected -> Connecting
  c1 <- disconnect c0                       -- Connecting -> Disconnected: in the table
  c2 <- close (connected (Socket 7) (open "db.internal" c1))
  print c2
  print (Map.map stateOf (Map.fromList [(1 :: Int, SomeConn c0), (2, SomeConn c2)]))
  -- fromList [(1,Connecting),(2,Closed)]
```

The illegal call `close (open "db.internal" newConn)` fails with exactly this message (9.10.3):

```text
error: [GHC-64725]
    • Illegal connection transition: Connecting -> Closed
      Legal transitions are listed in Conn.Transitions
```

Keep that guarantee in CI with a compile-fail check (`test/compile-fail/IllegalTransition.hs`
holds the bad call):

```bash
if ghc -fno-code -isrc test/compile-fail/IllegalTransition.hs > out.txt 2>&1; then
  echo "illegal transition compiled"; exit 1; fi
grep -q 'Illegal connection transition: Connecting -> Closed' out.txt
```

Design notes: fixed edges (`open`, `connected`) use concrete indices; only operations that are
legal from several states consult the table. Allowing `Connecting -> Closed` is a one-line change
to `Transitions`. Adding `UndecidableInstances` would only be needed if an equation nested family
calls (for example `If (Elem x xs) ...`).

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| "Illegal deriving strategy: stock" | module compiled as GHC2021 (bare `ghc`, old cabal file) | `default-language: GHC2024` or `DerivingStrategies` |
| "Illegal nested use of type family" | family call inside another family's arguments | `UndecidableInstances` after checking termination, or restructure |
| "Reduction stack overflow; size = 201" | non-terminating family or long type-level list | fix the recursion; `-freduction-depth=N` only for genuinely deep input |
| "Could not deduce (KnownSymbol s0) ... ambiguous" | type variable only in constraints | `AllowAmbiguousTypes` + `@s`, or `forall s ->` |
| "'a1' is a rigid type variable bound by a pattern with constructor" | returning an existential's hidden type | CPS (`withSome`) or a singleton |
| "Could not deduce 'p ~ Int' from the context: a ~ Int" | GADT match in a function without a signature | write the signature (`eval :: Expr a -> a`) |
| "Couldn't match type: n + 1 with: 1 + n ... '+' is a non-injective type family" | GHC does not normalise symbolic arithmetic | `-fplugin GHC.TypeLits.Normalise` (ghc-typelits-natnormalise) |
| "Could not deduce (KnownNat (n + 1))" | no evidence for a computed literal | `-fplugin GHC.TypeLits.KnownNat.Solver` (ghc-typelits-knownnat), or carry the evidence |
| "Couldn't match kind 'k' with 'Nat'" | `forall n. Proxy n` is poly-kinded | annotate: `forall (n :: Nat).` |
| `p.name` ambiguous / `HasField` not solved | field not in scope or record from another package not exporting it | import the field; check `NoFieldSelectors` exports |
| two libraries define the same orphan | orphan instances | newtype wrapper owned by your package |
| `Show` used for persistence | not a stable format | `aeson`, `binary`, `cborg` with round-trip tests |
| `-Wincomplete-patterns` on a pattern synonym match | missing `{-# COMPLETE #-}` | add the pragma next to the synonym |
| compile times explode after type-level change | heavy families, TH, `Generic` on huge types | move machinery to one module, measure with `-ddump-timings` |
| `coerce` breaks a `Set`/`Map` invariant | representational role on an `Ord`-dependent parameter | `type role T nominal` |

Review checklist: illegal states unrepresentable where cheap; constructors of invariant-carrying
types hidden; strategies explicit; laws tested; type-level code confined to API edges with
readable custom errors. Type-level API trade-offs: ask `architect` or a second `haskell-expert`.

Related: `haskell-effects`, `haskell-concurrency-stm`, `haskell-testing-properties`,
`haskell-performance-space-leaks`, `haskell-cabal-builds`, hub `haskell-craft`.
