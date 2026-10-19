---
name: haskell-effects
description: "Structuring effectful Haskell applications: the ReaderT-over-IO pattern, mtl classes, effectful and bluefin, handle records, testable interpreters, async-safe exceptions with GHC 9.10+ exception context, bracket-style resource handling, and an incremental migration recipe. Load when designing an app's architecture, migrating an effect stack, or making business logic testable without IO."
when_to_use: "Haskell services with ReaderT Env IO, RIO, mtl constraints (MonadReader/MonadError/MonadState), ExceptT stacks, effectful (Eff es, :>, interpret, send) or bluefin; questions like 'how do I test this without IO', 'which effect library', 'migrate from transformers'; errors 'There is no handler for ... in the context', 'No instance for (MonadUnliftIO (ExceptT ...))', ambiguous State types in Eff; exceptions swallowed or cleanup not running."
---

# Haskell effects and application architecture

Baseline: GHC 9.10-9.14, GHC2024; effectful 2.7 (effectful-core 2.7.1.2), bluefin 0.10.1,
unliftio 0.2.25, safe-exceptions 0.1.7, mtl 2.3.1 (ships with GHC 9.10). Effect libraries change
APIs between majors: check Hackage for the pinned version before writing handlers.

Deep material: [effectful cookbook](references/effectful-cookbook.md) (static effects,
higher-order handlers, unlifting, concurrency, plugin) |
[streaming and resources](references/streaming-resources.md) (conduit, streamly, ResourceT)

## 1. Pick one style per application

| Style | Performance | Type-level effect tracking | Use when |
|---|---|---|---|
| `ReaderT Env IO` + `MonadUnliftIO` (RIO pattern) | best and simplest: concrete monad, no dictionaries | none: anything in `App` may do any IO | most services; exceptions and concurrency stay in plain IO |
| mtl classes | good only when specialised; dictionary passing otherwise | coarse (`MonadReader`, `MonadError`, own classes) | libraries polymorphic over the monad; small stacks |
| effectful | close to ReaderT IO: `Eff` is IO plus an effect environment; static dispatch fastest | per effect (`Database :> es`) | apps wanting typed, swappable capabilities and pure test interpreters |
| bluefin | close to IO: `Eff` wraps IO, handles are values | per handle, scoped like `ST` | several effects of the same type, explicit capability passing |
| polysemy, free(r) monads | slow; resource safety hard | per effect | avoid for new code |

Rules: never mix two effect systems in one codebase; keep `IO` at the edges; express capabilities
as effects or handle records so tests swap real I/O for pure interpreters. Mutable state lives in
`IORef`/`TVar` inside the environment, not in `StateT`: StateT loses updates when an exception
unwinds and does not compose with threads.

## 2. ReaderT design pattern

```haskell
data Env = Env
  { envLog   :: !(Text -> IO ())
  , envNow   :: !(IO UTCTime)
  , envPool  :: !(Pool Connection)
  , envState :: !(IORef Counters)           -- mutable state: an IORef/TVar in Env
  }

newtype App a = App { unApp :: ReaderT Env IO a }
  deriving newtype (Functor, Applicative, Monad, MonadIO, MonadReader Env, MonadUnliftIO)

runApp :: Env -> App a -> IO a
runApp env (App m) = runReaderT m env

class HasLog env where logL :: env -> Text -> IO ()         -- one class per capability
instance HasLog Env where logL = envLog

logInfo :: (MonadReader env m, HasLog env, MonadIO m) => Text -> m ()
logInfo msg = asks logL >>= \f -> liftIO (f msg)
```

- `deriving newtype MonadUnliftIO` works for a newtype over `ReaderT r IO` (GND accepts the
  rank-2 `withRunInIO`; checked on 9.10 with a class of the same shape);
  `unliftio` then gives `bracket`, `async`, `timeout`, `pooledMapConcurrentlyN` in `App`.
- Has-classes keep helpers honest: `logInfo` cannot touch the pool. Without hand-written classes,
  `generic-lens` selects fields by type: `(MonadReader env m, HasType LogFn env) => ...`, with
  `asks getTyped` (fields need distinct newtypes and the record needs `deriving stock Generic`).
- `rio` packages this pattern (`RIO env`, `HasLogFunc`, `logInfo`) with a curated prelude.
- Tests build an `Env` with fake functions (`envNow = pure t0`, `envLog = \m -> modifyIORef ref (m :)`).
  No mocking framework is needed.

## 3. mtl style

```haskell
transfer :: (MonadReader Limits m, MonadState Balances m, MonadError TransferError m)
         => AccountId -> AccountId -> Int -> m ()
{-# INLINABLE transfer #-}                       -- exported + polymorphic: let callers specialise
type Bank = ReaderT Limits (StateT Balances (ExceptT TransferError IO))
{-# SPECIALIZE transfer :: AccountId -> AccountId -> Int -> Bank () #-}   -- in the defining module
```

| Topic | Rule |
|---|---|
| speed | without specialisation every `>>=` goes through a dictionary; `INLINABLE` on exported functions, `SPECIALIZE` at the app monad, or `-fspecialise-aggressively -fexpose-all-unfoldings` for whole apps (compile-time cost); confirm in Core (`haskell-performance-space-leaks`) |
| `MonadError` vs exceptions | typed errors (`MonadError e`, `Either`) for domain failures the caller must handle; exceptions for infrastructure (network, DB, bugs). `ExceptT e IO` has two error channels: document which goes where |
| `ExceptT`/`StateT` over IO | no `MonadUnliftIO` instance exists for them ("No instance for (MonadUnliftIO (ExceptT ...))"), so `bracket`/`async` from unliftio do not apply: keep them inside pure layers or switch to ReaderT + exceptions |
| depth | more than 3 layers adds overhead and lifting noise; flatten into `Env` |
| mtl 2.3 | `Control.Monad.Except` gives `tryError`, `withError`, `handleError`, `mapError`, `modifyError`; mtl no longer re-exports `Control.Monad` (import `when` etc. yourself) |

**The n x m instances problem**: each custom class (`MonadClock`, `MonadDb`, ...) needs an instance
for every transformer (`ReaderT`, `StateT`, `ExceptT`, ...). Cut it with a lifting default:

```haskell
{-# LANGUAGE DefaultSignatures #-}
class Monad m => MonadClock m where
  now :: m UTCTime
  default now :: (MonadTrans t, MonadClock n, m ~ t n) => m UTCTime
  now = lift now
instance MonadClock IO where now = getCurrentTime
instance MonadClock m => MonadClock (ReaderT r m)      -- empty bodies, one line per transformer
instance MonadClock m => MonadClock (StateT s m)
```

## 4. effectful

```haskell
data Clock :: Effect where                       -- dynamic effect: a GADT of operations
  Now :: Clock m UTCTime
type instance DispatchOf Clock = Dynamic         -- needs TypeFamilies

now :: Clock :> es => Eff es UTCTime              -- smart constructor (or makeEffect ''Clock, effectful-th)
now = send Now

runClockIO :: IOE :> es => Eff (Clock : es) a -> Eff es a
runClockIO = interpret_ $ \case Now -> liftIO getCurrentTime        -- interpret_: 2.4+, first-order

runClockFixed :: UTCTime -> Eff (Clock : es) a -> Eff es a          -- test interpreter, no IOE
runClockFixed t = interpret_ $ \case Now -> pure t
```

| Concept | Rule |
|---|---|
| dynamic vs static | dynamic (`send` + `interpret`) when tests need another interpreter; static (`StaticRep`, `evalStaticRep`) for one fixed implementation: fastest path, no handler indirection ([cookbook](references/effectful-cookbook.md)) |
| `interpret_` vs `interpret` | `_` variants ignore the `LocalEnv`; use `interpret` + `localSeqUnlift` for higher-order operations (an operation taking an `m a`) |
| `reinterpret_ h` | handler with private effects: `reinterpret_ (runState s0) $ \case ...` keeps the state hidden |
| `Eff es` order | `runEff . runA . runB $ action` handles `B` first: `action :: Eff (B : A : '[IOE]) a`; type-level list order equals reversed handler order |
| `IOE` | only `runEff` discharges it; code without `IOE :> es` cannot do arbitrary IO (`runPureEff` runs it) |
| `Error e` | `throwError` needs `Show e` (2.4+; `throwError_` does not); `runError` gives `Either (CallStack, e) a`, `runErrorNoCallStack` gives `Either e a`; implemented with exceptions, so state changes before the throw persist (use `bracketOnError` for rollback) |
| `Reader`/`State` | `Effectful.Reader.Static` (`runReader`, `ask`, `asks`, `local`); `Effectful.State.Static.Local` is thread-local, `...Shared` is shared across threads; `stateM`/`modifyM` are deprecated in 2.7 |
| missing handler | "There is no handler for 'X' in the context" means a `runX` is missing from the pipeline |
| ambiguous `gets Map.size` | the state type is not inferable: annotate (`gets (Map.size :: Map Email User -> Int)`) or add `-fplugin=Effectful.Plugin` (effectful-plugin 2.2) |
| concurrency | `Effectful.Concurrent.Async` (`Concurrent :> es`, `runConcurrent`): `withAsync`, `concurrently`, `race`, `mapConcurrently`, `pooledMapConcurrentlyN`; local state is copied per thread, shared state is visible |
| mtl compatibility | effectful-core 2.6.1+ has `MonadReader`/`MonadState`/`MonadError`/`MonadWriter` instances for `Eff`, served by the dynamic variants (`Effectful.Reader.Dynamic`, `Effectful.State.Dynamic`, `Effectful.Error.Dynamic`); their docs name this as the reason to pick them over `.Static` |

## 5. bluefin

Effects are value-level handles: a function's arguments say exactly which capabilities it uses,
and two `State Int` handles can coexist without type-level disambiguation.

```haskell
import Bluefin.Eff (Eff, runPureEff, (<:))       -- 0.10: `<:` preferred; older releases use `:>`
import Bluefin.Exception (Exception, throw, try)
import Bluefin.State (State, evalState, get, modify)

bump :: (e1 <: es, e2 <: es) => State Int e1 -> Exception String e2 -> Eff es ()
bump st ex = do
  n <- get st
  when (n >= 3) (throw ex ("limit reached at " <> show n))
  modify st (+ 1)

runBump :: Int -> Either String Int     -- runBump 2 == Right 2; runBump 5 == Left "limit reached at 3"
runBump k = runPureEff $ try $ \ex -> evalState 0 $ \st -> replicateM_ k (bump st ex) >> get st
```

- Scoping works like `ST`: the phantom `e` stops a handle from escaping its handler, so returning
  `st` from `evalState` is a type error.
- IO: `runEff $ \io -> effIO io (putStrLn "hi")`; unlift with `withEffToIO_`.
- Custom effects are records of `Eff` functions with a `Handle` instance (`Bluefin.Compound`,
  `useImplIn`, `mapHandle`); in 0.10 `Bluefin.State`/`Bluefin.Exception` are the older interface,
  with `Bluefin.Capability.*` as the replacement path.
- Fits teams who like the handle pattern and want effect tracking without a type-level effect list.

## 6. Handle pattern (records of functions)

```haskell
data UserRepo = UserRepo
  { findByEmail :: Email -> IO (Maybe User)
  , insertUser  :: Email -> UTCTime -> IO User }

newUserRepoPg :: Pool Connection -> UserRepo                      -- production
newUserRepoFake :: IO (UserRepo, IORef (Map Email User))           -- test: IORef-backed fake
newUserRepoFake = do
  ref <- newIORef Map.empty
  let ins e t = atomicModifyIORef' ref $ \m ->
        let u = User (UserId (Map.size m + 1)) e t in (Map.insert e u m, u)
  pure (UserRepo (\e -> Map.lookup e <$> readIORef ref) ins, ref)
```

Functions take the handles they need (`register :: UserRepo -> Mailer -> Clock -> Text -> IO
(Either RegistrationError User)`). There is no type-level machinery and it works with any style.
The costs: business logic stays in `IO`, and nothing stops a function from calling `IO` directly.
Use it inside a ReaderT app (handles as `Env` fields) or as a stepping stone to effectful.

## 7. Exceptions and resources

| Need | Use |
|---|---|
| catch everything except async exceptions | `catchAny` / `tryAny` / `handleAny` (unliftio `UnliftIO.Exception`, safe-exceptions `Control.Exception.Safe`); effectful: `catchSync` / `trySync` (`Effectful.Exception`) |
| catch one type | `catch @IOException`, `try @MyError` (`TypeApplications`) |
| cleanup | `bracket acquire release use`, `bracket_`, `bracketOnError`, `finally`, `withFile` |
| rethrow with context | GHC 9.10+: `annotateIO ann action`; or wrap in a domain exception holding the cause |
| pure code failures | `Either`/`ExceptT`, not `error` or `throw` |

Sync vs async: async exceptions (`ThreadKilled`, async's `AsyncCancelled`, `timeout`'s `Timeout`)
are thrown *into* a thread to stop it. `catch (\(e :: SomeException) -> ...)` from `base` (also
`Control.Monad.Catch.catchAll` from `exceptions`) catches them too, so cancellation and timeouts
silently fail. unliftio's `catch` never catches async exceptions, and its `bracket` runs cleanup
under `uninterruptibleMask`. Catch-all-then-rethrow (record, clean up, `throwIO e`) is the only
legitimate catch of `SomeException`. Use `mask` only in library-level resource code.

GHC 9.10+ exception context (base-4.20), checked on 9.10.3:

```haskell
import Control.Exception (annotateIO, someExceptionContext)
import Control.Exception.Annotation (ExceptionAnnotation (..))
import Control.Exception.Backtrace (BacktraceMechanism (..), setBacktraceMechanismState)
import Control.Exception.Context (displayExceptionContext)

newtype RequestId = RequestId Int deriving stock Show
instance ExceptionAnnotation RequestId where
  displayExceptionAnnotation (RequestId n) = "request id: " <> show n

withRequestId :: Int -> IO a -> IO a
withRequestId rid = annotateIO (RequestId rid)   -- every exception escaping carries the id
-- displayException (e :: SomeException) on 9.10.3 prints:
--   user error (boom)
--   request id: 42
--   HasCallStack backtrace:
--     ...                                      (collectBacktraces, toExceptionWithBacktrace frames)
--     throwIO, called at Bt.hs:9:21 in main:Main
```

- `throw`/`throwIO` carry `HasCallStack` (base-4.20). The `HasCallStack` backtrace was on by
  default in the test. Others (`CostCentreBacktrace`, `ExecutionBacktrace`, `IPEBacktrace`) are
  switched on with `setBacktraceMechanismState`.
- 9.12 (base-4.21): rethrown exceptions get a `WhileHandling` annotation; `catchNoPropagate`,
  `rethrowIO`, `tryWithContext` rethrow without adding it. base-4.22 exports
  `displayExceptionWithInfo`.
- On 9.10 `displayException` of a `SomeException` includes the context lines; for a one-line
  message use `case e of SomeException inner -> displayException inner`.

## 8. Migration recipe: transformer stack to effectful, incrementally

1. Freeze behaviour: characterisation tests around the current `App`/`ExceptT` stack (golden
   outputs, HTTP-level tests).
2. Make leaf helpers polymorphic in `MonadIO m` / `MonadUnliftIO m` where they only need IO:
   `Eff es` has both instances when `IOE :> es`, so they run unchanged on either side.
3. Top-down switch: replace `runApp env` in `main` with
   `runEff . runErrorNoCallStack @AppError . runReader env`, importing `runReader` and
   `runErrorNoCallStack` from `Effectful.Reader.Dynamic` / `Effectful.Error.Dynamic`. Code with
   `MonadReader Env m` or `MonadError AppError m` constraints then compiles at `m ~ Eff es` through
   the effectful-core 2.6.1+ mtl instances. For your own classes, write one canonical instance:
   `instance Database :> es => MonadDb (Eff es) where findUser = send . FindUser`. Switch to the
   `.Static` modules once the mtl constraints are gone.
4. Bottom-up alternative when `main` cannot change yet: convert one module to `Eff` and call it
   from the old stack through a `liftIO` boundary:
   `liftIO (runEff (runReader env (runDatabaseIO ops action)))`.
5. Convert capabilities one at a time: class to effect GADT, implementation to a `runX`
   interpreter, test fakes to pure interpreters. Run the characterisation tests after each step.
6. Delete the old classes, `App` and the mtl instances once nothing uses them; remove `IOE` from
   business-logic signatures last. That removal is the payoff: the compiler proves the logic is pure.

## 9. Testing effectful code

- **Pure interpreters**: `reinterpret_ (runState seed)` for repositories, captured lists for
  emitted messages, fixed clocks; run with `runPureEff`, no `IOE` anywhere.
- **Handler order decides what you observe**: with `runErrorNoCallStack` innermost the captured
  state and messages survive a failure; with it outermost a `Left` discards them.
- **Golden logs**: capture a `Log` effect and compare the rendered lines to a checked-in file
  (`tasty-golden`, accept intentional changes with `--accept`):

```haskell
data Log :: Effect where LogInfo :: Text -> Log m ()
type instance DispatchOf Log = Dynamic
runLogCapture :: Eff (Log : es) a -> Eff es (a, [Text])
runLogCapture = reinterpret_ (fmap (fmap reverse) . runState []) $ \case LogInfo t -> modify (t :)

goldenLog :: TestTree        -- scenario: the code under test with the other effects already interpreted
goldenLog = goldenVsString "registration log" "test/golden/register.log" $
  pure . LBS.fromStrict . TE.encodeUtf8 . T.unlines . snd . runPureEff . runLogCapture $ scenario
```

- **Properties over the pure core**: generate operation sequences, run them through the pure
  interpreters, compare with a model (example in section 10). Generator and shrinking advice:
  `haskell-testing-properties`.

## 10. Worked example: user registration with Database, Email and Clock

Type-checked against the effectful-core 2.7 signatures (`interpret_`, `reinterpret_`, `send`,
`runState`, `runErrorNoCallStack`, `throwError`). The full module is in the
[cookbook](references/effectful-cookbook.md); the `EmailSender` and `Clock` effects follow the
same shape as `Database`.

```haskell
data RegistrationError = InvalidEmail Text | AlreadyRegistered Email
  deriving stock (Eq, Show)                       -- Show: required by throwError

data Database :: Effect where
  FindUserByEmail :: Email -> Database m (Maybe User)
  InsertUser      :: Email -> UTCTime -> Database m User
type instance DispatchOf Database = Dynamic
-- EmailSender (SendWelcome :: Email -> EmailSender m ()) and Clock (Now) declared the same way,
-- smart constructors: findUserByEmail = send . FindUserByEmail, insertUser e t = send (InsertUser e t), ...

register :: (Database :> es, EmailSender :> es, Clock :> es, Error RegistrationError :> es)
         => Text -> Eff es User                   -- no IOE: cannot do arbitrary IO
register raw = do
  email <- either (throwError . InvalidEmail) pure (mkEmail raw)
  findUserByEmail email >>= \case
    Just _  -> throwError (AlreadyRegistered email)
    Nothing -> do
      user <- insertUser email =<< now
      sendWelcome email
      pure user

-- production: interpreters over IO
runDatabaseIO :: IOE :> es => DbOps -> Eff (Database : es) a -> Eff es a
runDatabaseIO ops = interpret_ $ \case
  FindUserByEmail e -> liftIO (dbFindByEmail ops e)
  InsertUser e t    -> liftIO (dbInsert ops e t)

main = print =<< ( runEff . runErrorNoCallStack @RegistrationError . runClockIO
                 . runEmailIO smtpDeliver . runDatabaseIO ops $ register "Ada@Example.com" )

-- tests: pure interpreters, Error handled innermost so state and sent mail stay observable
runDatabasePure :: Map Email User -> Eff (Database : es) a -> Eff es (a, Map Email User)
runDatabasePure seed = reinterpret_ (runState seed) $ \case
  FindUserByEmail e -> gets (Map.lookup e)
  InsertUser e t    -> do
    n <- gets (Map.size :: Map Email User -> Int)     -- annotation needed (or effectful-plugin)
    let u = User (UserId (n + 1)) e t
    modify (Map.insert e u) >> pure u

runEmailCapture :: Eff (EmailSender : es) a -> Eff es (a, [Email])
runEmailCapture = reinterpret_ (fmap (fmap reverse) . runState []) $ \case
  SendWelcome e -> modify (e :)

runTest :: Map Email User -> Eff '[Error RegistrationError, Database, EmailSender, Clock] a
        -> ((Either RegistrationError a, Map Email User), [Email])
runTest seed = runPureEff . runClockFixed t0 . runEmailCapture . runDatabasePure seed
             . runErrorNoCallStack @RegistrationError
```

```haskell
tests = testGroup "register"
  [ testCase "new user is stored and welcomed" $ do
      let ((r, db), sent) = runTest Map.empty (register "Ada@Example.com")
      fmap userEmail r @?= Right ada    -- ada = either (error . T.unpack) id (mkEmail "ada@example.com")
      (Map.size db, sent) @?= (1, [ada])
  , testCase "duplicate is rejected, no second email" $ do
      let ((r, _), sent) = runTest Map.empty (register "ada@example.com" >> register "ADA@example.com")
      r @?= Left (AlreadyRegistered ada)
      sent @?= [ada]
  , testProperty "one user and one welcome per distinct email" $ property $ do
      locals <- forAll (Gen.list (Range.linear 0 40) (Gen.element ["ada", "Ada", "bob", "cy"]))
      let raws = map (<> "@example.com") locals
          ((_, db), sent) = runTest Map.empty (traverse_ (tryError @RegistrationError . register) raws)
          distinct = nubOrd [e | Right e <- map mkEmail raws]
      Map.size db === length distinct
      sent === distinct ]
```

Run with `cabal test --test-show-details=direct`. The suite needs no database, SMTP server or
clock; the production pipeline differs only in the interpreters.

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| timeouts never fire, `cancel` hangs, Ctrl-C ignored | `catch` of `SomeException` (base) or `catchAll` swallowing async exceptions | `catchAny`/`tryAny`/`catchSync`; rethrow in catch-alls |
| state lost after an exception | `StateT` over IO | `IORef`/`TVar` in `Env`, or effectful `State` |
| "No instance for (MonadUnliftIO (ExceptT ...))" | unliftio needs a stateless monad | ReaderT + exceptions; keep `ExceptT` in pure layers |
| slow mtl code in hot paths | dictionary passing | `INLINABLE` + `SPECIALIZE`, check Core |
| "There is no handler for 'X' in the context" | missing `runX` in the pipeline | add the interpreter; read the effect list in the error |
| ambiguous `State` type in effectful | polymorphic accessor (`gets Map.size`) | annotate, or effectful-plugin |
| `throwError` "No instance for (Show e)" (effectful) | 2.4+ requires `Show e` | derive `Show` or use `throwError_` |
| errors in a forked effectful thread vanish | `Error` does not cross threads | `withAsync` + `wait` from `Effectful.Concurrent.Async` |
| runtime error "...have a look at UnliftStrategy (ConcUnlift)" | `SeqUnlift` unlift function used from another thread | `withEffToIO (ConcUnlift Persistent Unlimited)` (cookbook) |
| business logic needs `IOE` "just for logging" | missing capability | add a `Log` effect; keep `IOE` out of logic |
| two effect systems in one codebase | partial migration left behind | finish the recipe in section 8 or roll back |

Review checklist: one effect style; business logic testable without `IO`; async-safe catching;
resources acquired with `bracket`/`with*`; test interpreters cover every capability.

Related: `haskell-concurrency-stm`, `haskell-type-level`, `haskell-testing-properties`,
`haskell-performance-space-leaks`, `haskell-cabal-builds`, hub `haskell-craft`.
