# Streaming and resource lifetimes

Library versions at time of writing: conduit 1.3.6.1, streamly 0.11.1 (core modules come from
`streamly-core`). Streaming APIs move between majors, so check the pinned version.

## 1. Pick a streaming library

| Library | Strengths | Use when |
|---|---|---|
| conduit | mature, resource-safe (`ResourceT`), large ecosystem (http-conduit, conduit-extra, xml-conduit) | I/O pipelines in services |
| streamly | very fast (stream fusion), built-in concurrency combinators | high-throughput and concurrent stream processing |
| streaming / pipes | simple, principled | smaller pipelines, existing codebases |
| lazy `Text`/`ByteString` IO | zero dependencies | scripts only; resources do not close deterministically |

## 2. conduit: constant memory, deterministic cleanup

```haskell
import Conduit
import qualified Data.Text as T

extractErrors :: FilePath -> FilePath -> IO ()
extractErrors inp out = runConduitRes $
     sourceFile inp                       -- MonadResource: file handle registered in ResourceT
  .| decodeUtf8C
  .| linesUnboundedC
  .| filterC ("ERROR" `T.isInfixOf`)
  .| mapC (<> "\n")
  .| encodeUtf8C
  .| sinkFile out
```

Memory stays constant whatever the file size; both files close when `runConduitRes` exits, also on
exceptions. `linesUnboundedC` holds one whole line in memory, so hostile input with a 2 GB line
still blows up: use a bounded line splitter for untrusted data.

## 3. streamly: bounded concurrent mapping

```haskell
import qualified Streamly.Data.Fold as Fold
import qualified Streamly.Data.Stream as Stream            -- fromList, fold (streamly-core)
import qualified Streamly.Data.Stream.Prelude as Stream    -- parMapM, maxThreads (streamly)

totalSize :: [Url] -> IO Int
totalSize urls =
    Stream.fold Fold.sum
  $ Stream.parMapM (Stream.maxThreads 16) fetchSize       -- at most 16 concurrent fetches
  $ Stream.fromList urls
```

`maxBuffer n` bounds buffered results and `ordered True` keeps input order. In 0.11 `parEval` is
deprecated in favour of `parBuffered`.

## 4. Resource lifetimes: bracket vs ResourceT

| Lifetime shape | Tool |
|---|---|
| resource used inside one scope | `bracket` / `withFile` / `withResource` (unliftio `bracket` cleans up under `uninterruptibleMask`) |
| several nested resources | nested `with*` calls, or `managed`'s `Managed` monad |
| lifetime does not nest (opened in one stage, closed in another; streaming) | `ResourceT`: `allocate acquire release` returns a `ReleaseKey`; `release key` frees early, `runResourceT` frees the rest |
| pooled connections | `resource-pool` `withResource pool action`; never return the raw connection |

Rules: acquire in the masked part (`bracket` does this for you); never `forkIO` with a resource
from an enclosing `bracket` unless the child is joined before the bracket exits (`withAsync` +
`wait`); lazy IO (`readFile` from `Prelude`) keeps the handle open until the whole string is
consumed. Use strict `Data.Text.IO.readFile` / `Data.ByteString.readFile` or a stream.
