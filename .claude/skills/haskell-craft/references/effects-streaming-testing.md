# Haskell effects, streaming, STM and testing patterns

Library APIs below match current major versions (effectful 2.x, conduit 1.3, streamly 0.10,
async 2.2, hedgehog 1.x, QuickCheck 2.14+). Confirm against the versions pinned in the project.

## 1. ReaderT design pattern

```haskell
data Env = Env
  { envLog    :: !(Text -> IO ())
  , envPool   :: !(Pool Connection)
  , envConfig :: !Config
  }

newtype App a = App { unApp :: ReaderT Env IO a }
  deriving newtype (Functor, Applicative, Monad, MonadIO, MonadReader Env, MonadUnliftIO)

runApp :: Env -> App a -> IO a
runApp env (App m) = runReaderT m env

-- capability classes keep functions honest about what they use
class HasLog env where logFn :: env -> Text -> IO ()
instance HasLog Env where logFn = envLog

logInfo :: (MonadReader env m, HasLog env, MonadIO m) => Text -> m ()
logInfo msg = do
  f <- asks logFn
  liftIO (f msg)
```

- Mutable state lives in `IORef`/`TVar` inside `Env`, not in `StateT` (StateT loses state on
  exceptions and does not compose with concurrency).
- Tests construct an `Env` with fake functions; no type-class mocking framework required.
- `unliftio` gives exception-safe `bracket`, `async`, `timeout` for any `MonadUnliftIO`.

## 2. mtl style

```haskell
transfer :: (MonadReader Env m, MonadError TransferError m, MonadIO m)
         => AccountId -> AccountId -> Amount -> m ()
```

- Fine for libraries that must stay monad-polymorphic; mark exported functions `INLINABLE`
  and specialize at the application's concrete monad.
- `ExceptT` over `IO` gives two error channels (typed errors and exceptions); document which
  errors go where, or keep typed errors only for domain failures.
- Avoid deep transformer stacks (> 3 layers); each layer adds overhead and lifting noise.

## 3. effectful

```haskell
{-# LANGUAGE DataKinds, GADTs, LambdaCase, TypeFamilies #-}
import Effectful
import Effectful.Dispatch.Dynamic
import Effectful.State.Static.Local (evalState, gets, modify)
import qualified Data.Map.Strict as Map

data FileSystem :: Effect where
  ReadFile  :: FilePath -> FileSystem m Text
  WriteFile :: FilePath -> Text -> FileSystem m ()
type instance DispatchOf FileSystem = Dynamic

readFile' :: FileSystem :> es => FilePath -> Eff es Text
readFile' = send . ReadFile
writeFile' :: FileSystem :> es => FilePath -> Text -> Eff es ()
writeFile' p = send . WriteFile p
-- or generate both with `makeEffect ''FileSystem` (effectful-th)

runFileSystemIO :: IOE :> es => Eff (FileSystem : es) a -> Eff es a
runFileSystemIO = interpret $ \_ -> \case
  ReadFile p    -> liftIO (T.readFile p)
  WriteFile p t -> liftIO (T.writeFile p t)

runFileSystemPure :: Map.Map FilePath Text -> Eff (FileSystem : es) a -> Eff es a
runFileSystemPure fs0 = reinterpret (evalState fs0) $ \_ -> \case
  ReadFile p    -> gets (Map.findWithDefault "" p)
  WriteFile p t -> modify (Map.insert p t)

-- business logic sees only the effects it needs
copyConfig :: FileSystem :> es => Eff es ()
copyConfig = readFile' "a.conf" >>= writeFile' "b.conf"

-- production: runEff . runFileSystemIO $ copyConfig
-- test:       runPureEff . runFileSystemPure (Map.fromList [("a.conf", "x=1")]) $ copyConfig
```

- Static effects (`Effectful.Reader.Static`, `State.Static.Local`, `Error.Static`) are the
  fast path; dynamic effects are for interpretable capabilities.
- `Error.Static`: `throwError`, `runErrorNoCallStack` returns `Either e a`.
- Concurrency: `Effectful.Concurrent.Async` mirrors `async`; state effects have Local (per thread)
  and Shared variants: pick deliberately.

## 4. Streaming

| Library | Strengths | Use when |
|---|---|---|
| conduit | mature, resource-safe (`ResourceT`), large ecosystem (http-conduit, conduit-extra, xml-conduit) | I/O pipelines in services |
| streamly | very fast (fusion), built-in concurrency combinators | high-throughput and concurrent stream processing |
| streaming / pipes | simple, principled | smaller pipelines, existing codebases |
| lazy `Text`/`ByteString` IO | zero dependencies | scripts; not when resources must close deterministically |

conduit:

```haskell
import Conduit
import qualified Data.Text as T

extractErrors :: FilePath -> FilePath -> IO ()
extractErrors inp out = runConduitRes $
     sourceFile inp
  .| decodeUtf8C
  .| linesUnboundedC
  .| filterC ("ERROR" `T.isInfixOf`)
  .| mapC (<> "\n")
  .| encodeUtf8C
  .| sinkFile out
```

Constant memory regardless of file size; files close when `runConduitRes` exits, even on
exceptions.

streamly (0.10 API; check the module names for the version in use):

```haskell
import qualified Streamly.Data.Fold as Fold
import qualified Streamly.Data.Stream.Prelude as Stream

totalSize :: [Url] -> IO Int
totalSize urls =
    Stream.fold Fold.sum
  $ Stream.parMapM (Stream.maxThreads 16) fetchSize    -- bounded concurrency
  $ Stream.fromList urls
```

## 5. STM and async patterns

```haskell
withdraw :: TVar Int -> Int -> STM ()
withdraw acc n = do
  bal <- readTVar acc
  when (bal < n) retry                  -- block until another transaction changes acc
  writeTVar acc (bal - n)

transfer :: TVar Int -> TVar Int -> Int -> IO ()
transfer from to n = atomically $ withdraw from n >> modifyTVar' to (+ n)

-- wait for a flag with a timeout (needs -threaded)
awaitFlag :: Int -> TVar Bool -> IO Bool
awaitFlag micros flag = do
  timedOut <- registerDelay micros
  atomically $ (readTVar flag >>= check >> pure True)
       `orElse` (readTVar timedOut >>= check >> pure False)
```

Bounded worker pool:

```haskell
import UnliftIO.Async (pooledMapConcurrentlyN_)
processAll :: [Job] -> IO ()
processAll = pooledMapConcurrentlyN_ 8 runJob     -- max 8 at once; any exception cancels the rest
```

Producer/consumer with backpressure:

```haskell
pipeline :: IO ()
pipeline = do
  q <- newTBQueueIO 1000
  concurrently_
    (mapM_ (atomically . writeTBQueue q . Just) inputs >> atomically (writeTBQueue q Nothing))
    (let loop = atomically (readTBQueue q) >>= maybe (pure ()) (\x -> handle x >> loop) in loop)
```

Rules:
- STM transactions must be short; a long transaction touching hot `TVar`s is re-run on every
  conflict and can starve.
- No `unsafeIOToSTM`; side effects happen after `atomically` returns.
- `stm-containers` (`StmContainers.Map`) for concurrent maps with fine-grained contention.
- `race a b` cancels the loser; `concurrently a b` waits for both and propagates the first
  exception, cancelling the other.
- `link` an `Async` to propagate its exception to the parent when you cannot `wait` on it.

## 6. Exceptions done right

| Need | Use |
|---|---|
| catch everything except async exceptions | `catchAny` / `tryAny` (unliftio, safe-exceptions) |
| catch a specific exception | `catch @IOException` / `try @MyError` (`TypeApplications`) |
| cleanup | `bracket acquire release use`, `finally`, `withFile` |
| rethrow with context | `annotated-exception` or wrap in a domain exception with the cause |
| pure code failures | `Either`/`ExceptT`, not `error` |

## 7. Test suite layout

```cabal
test-suite spec
  import:           warnings
  type:             exitcode-stdio-1.0
  hs-source-dirs:   test
  main-is:          Main.hs
  build-depends:    base, mylib, tasty, tasty-hunit, tasty-hedgehog, hedgehog
  ghc-options:      -threaded -rtsopts -with-rtsopts=-N
```

```haskell
main :: IO ()
main = defaultMain $ testGroup "mylib"
  [ testCase "parses example" $ parse "x=1" @?= Right (Config [("x", 1)])
  , testProperty "roundtrip" prop_roundtrip          -- tasty-hedgehog
  ]
```

## 8. Property-testing patterns

| Property | Shape |
|---|---|
| round-trip | `decode (encode x) === Just x` (Hedgehog `tripping`) |
| idempotence | `f (f x) === f x` (normalization, formatting, sort) |
| invariant preservation | after any sequence of operations, `valid state` |
| model-based | `toList (insert k v m) === Map.toList (Map.insert k v model)` |
| metamorphic | `search (q <> filter) ⊆ search q` |
| no crash on any input | parser returns `Left` or `Right`, never throws (`evaluate (force (parse s))`) |

QuickCheck generator hygiene:

```haskell
instance Arbitrary Config where
  arbitrary = Config <$> listOf1 genKey <*> chooseInt (1, 64)
  shrink    = genericShrink                         -- requires Generic
genKey :: Gen Text
genKey = T.pack <$> listOf1 (elements ['a'..'z'])
```

- Bias generators toward boundaries (`frequency [(1, pure 0), (1, pure maxBound), (8, arbitrary)]`).
- Use `cover`/`checkCoverage` (QuickCheck) or `cover`/`classify` (Hedgehog) to prove the
  interesting cases are generated.
- Stateful systems: Hedgehog state machine testing (`Hedgehog` commands with `Callback`s) or
  `quickcheck-dynamic` for model-based testing of APIs with real side effects.
- Keep failing seeds: Hedgehog prints a `recheckAt` line; QuickCheck's `--quickcheck-replay`
  (tasty) reproduces the run. Convert the shrunk counterexample into a unit test.

## 9. Doctest and golden tests

- `doctest` / `cabal-docspec` for `>>>` examples in Haddock so documentation stays correct.
- `tasty-golden` (`goldenVsString`) for pretty-printers and code generators; accept changes
  with `--accept` after review.
