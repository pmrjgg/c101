# Typed ASTs, singletons, Typeable and TypeLits

All code below compiles with `-Wall` on GHC 9.10.3 under `{-# LANGUAGE GHC2024 #-}`.

## 1. Typechecking an untyped AST into a GADT

A parser produces an untyped tree; the typechecker turns it into the typed `Expr a`. A
hand-written singleton `Ty a` stays with the expression inside the existential, so callers can
recover `a`.

```haskell
import Data.Type.Equality ((:~:) (Refl))

data Expr a where
  IntE  :: Int -> Expr Int
  BoolE :: Bool -> Expr Bool
  Add   :: Expr Int -> Expr Int -> Expr Int
  If    :: Expr Bool -> Expr a -> Expr a -> Expr a
  Eq    :: Expr Int -> Expr Int -> Expr Bool

data UExpr = UInt Int | UBool Bool | UAdd UExpr UExpr | UIf UExpr UExpr UExpr | UEq UExpr UExpr

data Ty a where                    -- singleton for the index
  TInt  :: Ty Int
  TBool :: Ty Bool

eqTy :: Ty a -> Ty b -> Maybe (a :~: b)
eqTy TInt  TInt  = Just Refl
eqTy TBool TBool = Just Refl
eqTy _     _     = Nothing

data SomeExpr where
  SomeExpr :: Ty a -> Expr a -> SomeExpr

typecheck :: UExpr -> Either String SomeExpr
typecheck = \case
  UInt n    -> Right (SomeExpr TInt (IntE n))
  UBool b   -> Right (SomeExpr TBool (BoolE b))
  UAdd x y  -> SomeExpr TInt <$> (Add <$> expect TInt x <*> expect TInt y)
  UEq x y   -> SomeExpr TBool <$> (Eq <$> expect TInt x <*> expect TInt y)
  UIf c t e -> do
    c' <- expect TBool c
    SomeExpr ty t' <- typecheck t           -- branch type decides the result type
    e' <- expect ty e
    pure (SomeExpr ty (If c' t' e'))
  where
    expect :: Ty a -> UExpr -> Either String (Expr a)
    expect want u = do
      SomeExpr got ex <- typecheck u
      maybe (Left "type mismatch") (\Refl -> Right ex) (eqTy want got)

render :: SomeExpr -> String       -- matching the singleton recovers the index
render (SomeExpr TInt e)  = show (eval e)
render (SomeExpr TBool e) = show (eval e)
```

`typecheck (UIf (UEq (UInt 1) (UInt 1)) (UAdd (UInt 2) (UInt 3)) (UInt 0))` renders `5`;
`typecheck (UAdd (UInt 1) (UBool True))` gives `Left "type mismatch"`.

## 2. Hand-written singletons for a promoted kind

Use them when the index is phantom: the runtime value does not reveal it, so it has to travel
separately.

```haskell
data ConnState = Disconnected | Connected deriving stock (Show, Eq)

type SState :: ConnState -> Type
data SState s where
  SDisconnected :: SState 'Disconnected
  SConnected    :: SState 'Connected

class KnownState s where stateSing :: SState s          -- type -> singleton, implicitly
instance KnownState 'Disconnected where stateSing = SDisconnected
instance KnownState 'Connected    where stateSing = SConnected

demote :: SState s -> ConnState                          -- singleton -> plain value
demote = \case SDisconnected -> Disconnected; SConnected -> Connected

withState :: ConnState -> (forall s. KnownState s => SState s -> r) -> r   -- value -> type
withState Disconnected k = k SDisconnected
withState Connected    k = k SConnected

newtype Handle (s :: ConnState) = Handle Int             -- phantom: Int says nothing about s
data SomeHandle where SomeHandle :: SState s -> Handle s -> SomeHandle

send :: Handle 'Connected -> String -> IO ()
send (Handle fd) msg = putStrLn ("fd " <> show fd <> ": " <> msg)

trySend :: SomeHandle -> String -> IO ()
trySend (SomeHandle s h) msg = case s of
  SConnected    -> send h msg                             -- refines s ~ 'Connected
  SDisconnected -> putStrLn "dropped: not connected"

stateName :: forall s. KnownState s => Handle s -> String
stateName _ = show (demote (stateSing @s))
```

The four pieces are the singleton GADT, the `Known*` class, `demote` and the CPS `with*`. That is
what `singletons-th` generates. For one or two kinds, write them by hand.

## 3. The singletons libraries (when hand-writing stops scaling)

- `singletons`: the core vocabulary (`Sing`, `SingI`/`sing`, `SingKind`/`Demote`, `fromSing`,
  `toSing`, `SomeSing`, `withSomeSing`).
- `singletons-th`: Template Haskell that promotes term-level functions to type families and
  singles them (`$(singletons [d| ... |])`, `$(genSingletons [''ConnState])`).
- `singletons-base`: promoted and singled `base`/Prelude. Version 3.5.1 supports only GHC 9.14 and
  defines orphan `Sing`/`SingKind` instances.

Worth it when many functions must exist at both levels, for example a dependently typed protocol
or units library. Not worth it for one state machine: the TH slows builds and pins the compiler
version. Check the generated names against the version you pin.

## 4. Typeable: open-world recovery

```haskell
import Type.Reflection (Typeable, typeRep, eqTypeRep, (:~~:) (HRefl))

data Dyn where Dyn :: Typeable a => a -> Dyn

fromDyn :: forall b. Typeable b => Dyn -> Maybe b
fromDyn (Dyn (x :: a)) = case eqTypeRep (typeRep @a) (typeRep @b) of
  Just HRefl -> Just x
  Nothing    -> Nothing
-- fromDyn @Int (Dyn (42 :: Int)) == Just 42; fromDyn @Int (Dyn "x") == Nothing
```

`Data.Typeable.eqT :: (Typeable a, Typeable b) => Maybe (a :~: b)` is the same check for kind
`Type`; `Data.Dynamic` (`toDyn`, `fromDynamic`) packages it. Prefer a closed singleton when the
set of types is known: the compiler then checks matches for exhaustiveness.

## 5. GHC.TypeLits recipes

```haskell
import GHC.TypeLits
import Data.Proxy (Proxy (..))

newtype Vec (n :: Nat) a = Vec [a] deriving stock Show

fromList :: forall n a. KnownNat n => [a] -> Maybe (Vec n a)    -- runtime check, typed result
fromList xs
  | length xs == fromIntegral (natVal (Proxy @n)) = Just (Vec xs)
  | otherwise                                     = Nothing

withRuntimeLength :: forall a r. [a] -> (forall n. KnownNat n => Vec n a -> r) -> r
withRuntimeLength xs k = case someNatVal (fromIntegral (length xs)) of   -- Integer -> Maybe SomeNat
  Just (SomeNat (_ :: Proxy n)) -> k (Vec xs :: Vec n a)
  Nothing                       -> error "negative length"
```

Observed on 9.10.3: `fromList @3 "abc" == Just (Vec "abc")`, `fromList @2 "abc" == Nothing`,
`withRuntimeLength "hello"` sees `n = 5`; `fromSNat (natSing @5) == 5`;
`withKnownNat (natSing @5) (natVal (Proxy @5)) == 5`; `sameNat (Proxy @2) (Proxy @2) == Just Refl`;
`cmpNat (Proxy @2) (Proxy @3) == LTI` (an `OrderingI`, which carries evidence).

| Need | API |
|---|---|
| literal to value | `natVal`, `symbolVal`, `charVal` with `KnownNat`/`KnownSymbol`/`KnownChar` |
| value to type | `someNatVal`, `someSymbolVal`, then CPS |
| first-class evidence (9.6+) | `SNat`/`SSymbol`/`SChar`, `natSing`, `fromSNat`, `withKnownNat` |
| compare / test equality | `cmpNat`, `sameNat`, `sameSymbol` |
| arithmetic in types | `+`, `*`, `-`, `^`, `Div`, `Mod`, `Log2`, `CmpNat`, `<=?` (literals only) |
| symbolic arithmetic | plugins `ghc-typelits-natnormalise` (`GHC.TypeLits.Normalise`), `ghc-typelits-knownnat` (`GHC.TypeLits.KnownNat.Solver`) |

`GHC.TypeNats` has the same API returning `Natural` instead of `Integer`.
