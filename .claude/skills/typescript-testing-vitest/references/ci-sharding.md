# Vitest in CI: sharding, merging and speed

## Sharded GitHub Actions workflow (Vitest 5 paths)

```yaml
name: test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4]
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4          # reads "packageManager" from package.json
      - uses: actions/setup-node@v4
        with: { node-version: 24, cache: pnpm }
      - run: pnpm install --frozen-lockfile
      - run: pnpm vitest run --shard=${{ matrix.shard }}/4 --reporter=blob --coverage
      - uses: actions/upload-artifact@v4
        if: ${{ !cancelled() }}
        with:
          name: blob-${{ matrix.shard }}
          path: .vitest/blob/              # Vitest 4.x: .vitest-reports/
          include-hidden-files: true       # .vitest is a dot-directory; upload-artifact skips those by default
          retention-days: 1

  merge:
    needs: test
    if: ${{ !cancelled() }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with: { node-version: 24, cache: pnpm }
      - run: pnpm install --frozen-lockfile
      - uses: actions/download-artifact@v4
        with:
          pattern: blob-*
          path: .vitest/blob/
          merge-multiple: true
      - run: pnpm vitest run --merge-reports --reporter=default --reporter=junit --coverage
```

- `--merge-reports` runs no tests; it replays the blobs and computes merged coverage, so coverage
  thresholds are enforced once on the whole suite (per-shard thresholds would fail spuriously).
- File-based attachments (screenshots, traces) live under `.vitest/attachments/` in 5.x; upload them
  from the shard jobs too if the merge job must link them.
- Shards split by file, so one huge test file caps the speedup; split files above ~30 s.

## Choosing the number of shards

```
expected wall time ~= setup + (total test time / shards) + merge
```

With 90 s install/setup, 41 s of tests and 30 s merge, 4 shards give ~90 + 10 + 30 s per pipeline, while
8 shards save only ~5 s more and double runner minutes. Shard when test time dominates setup, not before.
Cache the package store (`cache: pnpm`) and Playwright browsers (`~/.cache/ms-playwright`) first.

## Local speed checklist

| Symptom in the duration line | Likely cause | Fix |
|---|---|---|
| `environment` dominates | jsdom/happy-dom for files that never touch the DOM | `environment: "node"` per project |
| `import` dominates | barrel files (`index.ts` re-exporting everything), heavy SDKs imported at module top | import leaf modules; mock heavy SDKs |
| `setup` dominates | expensive `setupFiles` (DB connections, MSW per file) | move one-time work to `globalSetup`; keep per-file setup cheap |
| `transform` dominates | huge dependency graph transformed per run | `server.deps.inline` only what must be inlined; keep the Vitest cache directory between runs |
| `tests` dominates | real timers, sleeps, network | fake timers, MSW, smaller fixtures |

Pool and isolation:

| Setting | Effect | Safe when |
|---|---|---|
| `pool: "threads"` | lower startup than forks | no native addons, no `process.chdir`, no reliance on per-process globals |
| `pool: "forks"` (default) | full process isolation | native addons, segfault-prone code |
| `isolate: false` | reuses module graph across files in a worker | pure tests with no module-level state; verify with `--sequence.shuffle` |
| `fileParallelism: false` | one file at a time | shared external resources (one test DB) |
| `maxWorkers` | caps parallelism | CI runners with few cores or limited memory |

## Flaky tests in CI

- Re-run with `--retry=2` only as a temporary quarantine flag on named tests, never globally; record the
  flake rate and fix (see `testing-strategy` for run-count math).
- `--sequence.shuffle --sequence.seed=<n>` reproduces an order-dependent failure locally with the seed
  printed by CI.
- `--reporter=hanging-process` lists what keeps the process alive when a run never exits (open handles,
  un-`unref`ed intervals, DB pools).
