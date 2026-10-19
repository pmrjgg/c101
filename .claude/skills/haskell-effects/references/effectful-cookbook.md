# effectful cookbook (effectful 2.7 / effectful-core 2.7.1.2)

Every snippet type-checks against the effectful-core 2.7 signatures under
`{-# LANGUAGE GHC2024, TypeFamilies, OverloadedStrings #-}`.

## 1. Version notes that change code

| Version | Change |
|---|---|
| 2.4.0.0 | first-order handler helpers (`interpret_`, `reinterpret_`, `interpose_`, `impose_`); `throwError` requires `Show e` (`throwError_`, `throwErrorWith` added); `SeqForkUnlift` strategy |
| 2.6.0.0 | type-parameter order of `raise` changed; `ErrorWrapper` no longer caught by `catchSync`; `withConcEffToIO` removed |
| 2.6.1.0 | `MonadReader`/`MonadState`/`MonadError`/`MonadWriter` instances for `Eff` (dynamic variants) |
| 2.7.0.0 | `LocalEnv` lost its `handlerEs` parameter; GHC < 9.6 dropped; `stateM`/`modifyM` deprecated; `runStateMVar`-style Shared helpers deprecated; `Provider` dynamically dispatched |
| 2.7.1.2 | `runPureEff` runs in a separate thread (protects values from async exceptions) |

## 2. Dynamic effect: the full registration module

```haskell
module Registration
  ( Email, mkEmail, User (..), UserId (..), RegistrationError (..)
  , Database, EmailSender, Clock, register
  , DbOps (..), runDatabaseIO, runEmailIO, runClockIO
  , runDatabasePure, runEmailCapture, runClockFixed
  ) where

import Data.Map.Strict (Map)
import qualified Data.Map.Strict as Map
import Data.Text (Text)
import qualified Data.Text as T
import Data.Time (UTCTime, getCurrentTime)
import Effectful
import Effectful.Dispatch.Dynamic (interpret_, reinterpret_, send)
import Effectful.Error.Static (Error, throwError)
import Effectful.State.Static.Local (gets, modify, runState)

newtype Email = Email Text deriving stock (Eq, Ord, Show)

mkEmail :: Text -> Either Text Email
mkEmail raw
  | "@" `T.isInfixOf` t, T.length t <= 254 = Right (Email t)
  | otherwise                              = Left raw
  where t = T.toLower (T.strip raw)

newtype UserId = UserId Int deriving stock (Eq, Ord, Show)
data User = User { userId :: UserId, userEmail :: Email, createdAt :: UTCTime }
  deriving stock (Eq, Show)

data RegistrationError = InvalidEmail Text | AlreadyRegistered Email
  deriving stock (Eq, Show)

data Database :: Effect where
  FindUserByEmail :: Email -> Database m (Maybe User)
  InsertUser      :: Email -> UTCTime -> Database m User
type instance DispatchOf Database = Dynamic

data EmailSender :: Effect where
  SendWelcome :: Email -> EmailSender m ()
type instance DispatchOf EmailSender = Dynamic

data Clock :: Effect where
  Now :: Clock m UTCTime
type instance DispatchOf Clock = Dynamic

findUserByEmail :: Database :> es => Email -> Eff es (Maybe User)
findUserByEmail = send . FindUserByEmail
insertUser :: Database :> es => Email -> UTCTime -> Eff es User
insertUser e t = send (InsertUser e t)
sendWelcome :: EmailSender :> es => Email -> Eff es ()
sendWelcome = send . SendWelcome
now :: Clock :> es => Eff es UTCTime
now = send Now

register
  :: (Database :> es, EmailSender :> es, Clock :> es, Error RegistrationError :> es)
  => Text -> Eff es User
register raw = do
  email <- either (throwError . InvalidEmail) pure (mkEmail raw)
  findUserByEmail email >>= \case
    Just _  -> throwError (AlreadyRegistered email)
    Nothing -> do
      user <- insertUser email =<< now
      sendWelcome email
      pure user

data DbOps = DbOps                      -- thin record over your SQL layer
  { dbFindByEmail :: Email -> IO (Maybe User)
  , dbInsert      :: Email -> UTCTime -> IO User
  }

runDatabaseIO :: IOE :> es => DbOps -> Eff (Database : es) a -> Eff es a
runDatabaseIO ops = interpret_ $ \case
  FindUserByEmail e -> liftIO (dbFindByEmail ops e)
  InsertUser e t    -> liftIO (dbInsert ops e t)

runEmailIO :: IOE :> es => (Email -> IO ()) -> Eff (EmailSender : es) a -> Eff es a
runEmailIO deliver = interpret_ $ \case
  SendWelcome e -> liftIO (deliver e)

runClockIO :: IOE :> es => Eff (Clock : es) a -> Eff es a
runClockIO = interpret_ $ \case
  Now -> liftIO getCurrentTime

runDatabasePure :: Map Email User -> Eff (Database : es) a -> Eff es (a, Map Email User)
runDatabasePure seed = reinterpret_ (runState seed) $ \case
  FindUserByEmail e -> gets (Map.lookup e)
  InsertUser e t    -> do
    n <- gets (Map.size :: Map Email User -> Int)   -- State type must be known
    let u = User (UserId (n + 1)) e t
    modify (Map.insert e u)
    pure u

runEmailCapture :: Eff (EmailSender : es) a -> Eff es (a, [Email])
runEmailCapture = reinterpret_ (fmap (fmap reverse) . runState []) $ \case
  SendWelcome e -> modify (e :)

runClockFixed :: UTCTime -> Eff (Clock : es) a -> Eff es a
runClockFixed t = interpret_ $ \case
  Now -> pure t
```

Test harness (tasty + tasty-hunit + tasty-hedgehog; the test group is in the skill):

```haskell
t0 :: UTCTime
t0 = UTCTime (fromGregorian 2026 1 1) 0

runTest :: Map Email User -> Eff '[Error RegistrationError, Database, EmailSender, Clock] a
        -> ((Either RegistrationError a, Map Email User), [Email])
runTest seed = runPureEff . runClockFixed t0 . runEmailCapture . runDatabasePure seed
             . runErrorNoCallStack @RegistrationError

ada :: Email
ada = either (error . T.unpack) id (mkEmail "ada@example.com")
```

Expected results: `register "Ada@Example.com"` stores one user with email `ada@example.com` and
sends one welcome mail. Registering `ada@example.com` then `ADA@example.com` gives
`Left (AlreadyRegistered ada)` and exactly one mail, because `mkEmail` lower-cases.

## 3. Static effect (one implementation, fastest)

```haskell
import Effectful.Dispatch.Static

data Log :: Effect
type instance DispatchOf Log = Static WithSideEffects     -- WithSideEffects: requires IOE
newtype instance StaticRep Log = Log (Text -> IO ())

runLog :: IOE :> es => (Text -> IO ()) -> Eff (Log : es) a -> Eff es a
runLog f = evalStaticRep (Log f)

logMsg :: Log :> es => Text -> Eff es ()
logMsg msg = do
  Log f <- getStaticRep
  unsafeEff_ (f msg)          -- safe here: the effect declared WithSideEffects
```

Use static dispatch when the effect has one reasonable implementation or must always behave the
same; the docs advise dynamic dispatch when unsure. `NoSideEffects` effects (pure state, reader)
need no `IOE`.

## 4. Higher-order effects (an operation that takes an action)

```haskell
data Transaction :: Effect where
  WithTransaction :: m a -> Transaction m a
type instance DispatchOf Transaction = Dynamic

withTransaction :: Transaction :> es => Eff es a -> Eff es a
withTransaction = send . WithTransaction

runTransactionIO :: IOE :> es => IO () -> IO () -> Eff (Transaction : es) a -> Eff es a
runTransactionIO begin commit = interpret $ \env -> \case
  WithTransaction action -> localSeqUnliftIO env $ \unlift -> bracket_ begin commit (unlift action)

runTransactionNoop :: Eff (Transaction : es) a -> Eff es a          -- tests
runTransactionNoop = interpret $ \env -> \case
  WithTransaction action -> localSeqUnlift env $ \unlift -> unlift action
```

`interpret` passes the `LocalEnv`; `localSeqUnlift` runs the operation's action in the caller's
effect context, and `localSeqUnliftIO` does the same down to `IO` (needed for `bracket_`). The `_`
handler variants cannot do this: use them only for first-order operations.

## 5. The hub's FileSystem example (dynamic, IO and pure interpreters)

```haskell
data FileSystem :: Effect where
  ReadFile  :: FilePath -> FileSystem m Text
  WriteFile :: FilePath -> Text -> FileSystem m ()
type instance DispatchOf FileSystem = Dynamic
-- or generate the smart constructors and DispatchOf with `makeEffect ''FileSystem` (effectful-th)

readFile' :: FileSystem :> es => FilePath -> Eff es Text
readFile' = send . ReadFile
writeFile' :: FileSystem :> es => FilePath -> Text -> Eff es ()
writeFile' p = send . WriteFile p

runFileSystemIO :: IOE :> es => Eff (FileSystem : es) a -> Eff es a
runFileSystemIO = interpret $ \_ -> \case
  ReadFile p    -> liftIO (T.readFile p)
  WriteFile p t -> liftIO (T.writeFile p t)

runFileSystemPure :: Map.Map FilePath Text -> Eff (FileSystem : es) a -> Eff es a
runFileSystemPure fs0 = reinterpret (evalState fs0) $ \_ -> \case
  ReadFile p    -> gets (Map.findWithDefault "" p)
  WriteFile p t -> modify (Map.insert p t)

copyConfig :: FileSystem :> es => Eff es ()
copyConfig = readFile' "a.conf" >>= writeFile' "b.conf"
-- production: runEff . runFileSystemIO $ copyConfig
-- test:       runPureEff . runFileSystemPure (Map.fromList [("a.conf", "x=1")]) $ copyConfig
```

## 6. Unlifting strategies (passing Eff code to IO callbacks)

| Strategy | Behaviour | Use for |
|---|---|---|
| `SeqUnlift` (default for `withRunInIO`) | unlift function only usable on the creating thread; otherwise a runtime error pointing at `ConcUnlift` | callbacks run synchronously (`bracket`, `withFile`) |
| `SeqForkUnlift` (2.4+) | runs unlifted actions in a cloned environment; changes do not propagate either way | running unlifted code outside the scope of the effects it captured |
| `ConcUnlift Ephemeral (Limited n)` / `ConcUnlift Persistent Unlimited` | usable from other threads; `Persistence` decides whether thread-local effect state survives between calls, `Limit` caps the threads | web-server handlers, thread pools, callbacks invoked concurrently |

```haskell
withEffToIO (ConcUnlift Persistent Unlimited) $ \runInIO ->
  Warp.run 8080 (\req respond -> runInIO (handle req) >>= respond)   -- handlers on many threads
```

`withEffToIO`, `withSeqEffToIO` and `withUnliftStrategy` need `IOE :> es`. Prefer `withEffToIO`
over the `MonadUnliftIO` instance: it names the strategy at the call site and reports errors
better.

## 7. Concurrency inside Eff

- `Effectful.Concurrent.Async` mirrors `async` (`withAsync`, `async`, `wait`, `concurrently`,
  `race`, `mapConcurrently`, `pooledMapConcurrentlyN`); needs `Concurrent :> es`, discharged by
  `runConcurrent :: IOE :> es => Eff (Concurrent : es) a -> Eff es a`.
- Effect state across threads: `Reader` is thread local (a child keeps the `local` value it
  started with); `State`/`Writer` `.Static.Local` are copied per thread and invisible to the
  parent; `.Static.Shared` updates are visible everywhere.
- `Error` thrown in a child does not reach the parent: `withAsync` + `wait`, or rethrow manually.
- Apart from the `withAsync` family, `Concurrent` can escape the scope of scoped operations:
  prefer structured combinators (see `haskell-concurrency-stm`).

## 8. Ergonomics

- Ambiguous effect types (`gets Map.size`, two `State` effects): add
  `ghc-options: -fplugin=Effectful.Plugin` (effectful-plugin 2.2), or annotate.
- Several instances of one effect type: the `Effectful.Labeled.*` modules, or wrap the payload in
  distinct newtypes.
- `:>>` (list membership) is deprecated because it slows GHC: list constraints one by one.
- "There is no handler for 'X' in the context" is the `TypeError` raised when `X :> es` reaches
  the end of the effect list: a `runX` is missing between the call site and `runEff`.
