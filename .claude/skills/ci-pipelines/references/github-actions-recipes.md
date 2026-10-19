# GitHub Actions recipes

SHAs below resolve to the tags in the trailing comments as of October 2026. Re-pin with `pinact run`
or let Renovate (`helpers:pinGitHubActionDigests`) bump them; never edit a SHA by hand.

## 1. Full worked-example workflow (Python + TS monorepo)

```yaml
# .github/workflows/ci.yml
name: ci
on:
  pull_request:
  push:
    branches: [main]
  merge_group:
permissions:
  contents: read
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  changes:
    runs-on: ubuntu-slim
    timeout-minutes: 5
    permissions: { contents: read, pull-requests: read }
    outputs:
      py: ${{ steps.f.outputs.py }}
      ts: ${{ steps.f.outputs.ts }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - id: f
        uses: dorny/paths-filter@ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d # v4.0.3
        with:
          filters: |
            py: ['apps/api/**', 'uv.lock', 'pyproject.toml']
            ts: ['packages/web/**', 'pnpm-lock.yaml', 'package.json']

  lint:
    needs: changes
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - uses: astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884 # v10.3.0
        with: { version: "0.13.1", enable-cache: true, cache-dependency-glob: uv.lock }
      - name: workflow lint
        run: |
          uvx zizmor==1.31.1 --min-severity=low .github/workflows
          docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.12 -color
      - if: needs.changes.outputs.py == 'true'
        run: uv run --locked ruff check . && uv run --locked ruff format --check . && uv run --locked mypy apps/api
      - if: needs.changes.outputs.ts == 'true'
        uses: pnpm/action-setup@ea17c68df8912ef543352723c149a84f56e3d413 # v6.1.0
      - if: needs.changes.outputs.ts == 'true'
        uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
        with: { node-version-file: .nvmrc, cache: pnpm }
      - if: needs.changes.outputs.ts == 'true'
        run: pnpm install --frozen-lockfile && pnpm -r lint && pnpm -r typecheck

  py-test:
    needs: changes
    if: needs.changes.outputs.py == 'true'
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    strategy:
      fail-fast: false
      matrix: { shard: [1, 2, 3, 4] }
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - uses: astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884 # v10.3.0
        with: { version: "0.13.1", enable-cache: true, cache-dependency-glob: uv.lock }
      - run: uv sync --locked
      - env: { SHARD: "${{ matrix.shard }}", COVERAGE_FILE: ".coverage.${{ matrix.shard }}" }
        run: >-
          uv run pytest apps/api --splits 4 --group "$SHARD"
          --cov=apps/api --cov-report= --junitxml="reports/junit-py-$SHARD.xml"
      - if: always()
        uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        with:
          name: py-${{ matrix.shard }}
          path: |
            reports/
            .coverage.*
          include-hidden-files: true
          retention-days: 3

  py-report:
    needs: py-test
    if: always() && needs.py-test.result != 'skipped'
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - uses: astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884 # v10.3.0
        with: { version: "0.13.1", enable-cache: true, cache-dependency-glob: uv.lock }
      - uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2
        with: { pattern: "py-*", path: merged, merge-multiple: true }
      - run: |
          uvx junitparser merge --glob 'merged/reports/junit-py-*.xml' junit-py.xml
          uv run coverage combine merged/
          uv run coverage report --fail-under=85
          uv run coverage xml -o coverage.xml

  ts-test:
    needs: changes
    if: needs.changes.outputs.ts == 'true'
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    strategy:
      fail-fast: false
      matrix: { shard: [1, 2] }
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - uses: pnpm/action-setup@ea17c68df8912ef543352723c149a84f56e3d413 # v6.1.0
      - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
        with: { node-version-file: .nvmrc, cache: pnpm }
      - run: pnpm install --frozen-lockfile
      - env: { SHARD: "${{ matrix.shard }}" }
        working-directory: packages/web
        run: pnpm exec vitest run --reporter=blob --shard="$SHARD/2" --coverage
      - if: always()
        uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        with:
          name: vitest-${{ matrix.shard }}
          path: packages/web/.vitest/
          include-hidden-files: true
          retention-days: 3

  ts-report:
    needs: ts-test
    if: always() && needs.ts-test.result != 'skipped'
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - uses: pnpm/action-setup@ea17c68df8912ef543352723c149a84f56e3d413 # v6.1.0
      - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
        with: { node-version-file: .nvmrc, cache: pnpm }
      - run: pnpm install --frozen-lockfile
      - uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2
        with: { pattern: "vitest-*", path: packages/web/.vitest, merge-multiple: true }
      - working-directory: packages/web
        run: pnpm exec vitest run --merge-reports --reporter=junit --outputFile=junit-ts.xml
      # Coverage across shards: the Vitest docs do not promise that --merge-reports merges coverage.
      # Check the merged output; otherwise upload coverage/coverage-final.json per shard and merge
      # with `npx nyc merge <dir> merged.json` before reporting.

  image:
    needs: [changes, py-test]
    if: needs.changes.outputs.py == 'true' && needs.py-test.result == 'success'
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    permissions: { contents: read, packages: write }
    outputs:
      digest: ${{ steps.build.outputs.digest }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
      - id: build
        uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc # v7.4.0
        with:
          context: .
          file: apps/api/Dockerfile
          push: ${{ github.ref == 'refs/heads/main' }}
          tags: ghcr.io/acme/api:${{ github.sha }}
          cache-from: type=gha,scope=api
          cache-to: type=gha,mode=max,scope=api
      # registry login (docker/login-action) omitted here; add it before build when push is true

  ci-ok:
    if: always()
    needs: [lint, py-test, py-report, ts-test, ts-report, image]
    runs-on: ubuntu-slim
    timeout-minutes: 5
    steps:
      - env:
          RESULTS: ${{ join(needs.*.result, ' ') }}
        run: |
          for r in $RESULTS; do
            case "$r" in success|skipped) ;; *) echo "a needed job ended: $r"; exit 1 ;; esac
          done
```

Branch protection / ruleset: require only `ci-ok`. Enable the merge queue on `main`.

## 2. Keeping pytest-split durations fresh

```yaml
# .github/workflows/durations.yml
on:
  schedule: [{ cron: "17 3 * * 1" }]     # weekly; off the hour to avoid the top-of-hour rush
  workflow_dispatch:
permissions: { contents: write, pull-requests: write }
jobs:
  durations:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - uses: astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884 # v10.3.0
        with: { version: "0.13.1" }
      - run: uv sync --locked && uv run pytest apps/api --store-durations
      - env:
          GH_TOKEN: ${{ github.token }}
          TITLE: "chore(ci): refresh test durations"
        run: ./scripts/open-pr.sh .test_durations "$TITLE"   # gh auth setup-git; push branch; gh pr create
```
Write permissions are confined to this workflow and the token reaches only the step that pushes;
the main CI keeps `contents: read`.

## 3. Dynamic matrix from a plan job

```yaml
  plan:
    runs-on: ubuntu-slim
    outputs:
      matrix: ${{ steps.p.outputs.matrix }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false, fetch-depth: 0 }
      - id: p
        run: |
          pkgs=$(./scripts/affected-packages.sh origin/main | jq -Rnc '[inputs | select(length > 0)]')
          echo "matrix={\"pkg\":$pkgs}" >> "$GITHUB_OUTPUT"
          echo "packages=$pkgs" >> "$GITHUB_STEP_SUMMARY"
  test:
    needs: plan
    if: fromJSON(needs.plan.outputs.matrix).pkg[0] != null
    strategy:
      fail-fast: false
      matrix: ${{ fromJSON(needs.plan.outputs.matrix) }}
    runs-on: ubuntu-24.04
    steps:
      - env: { PKG: "${{ matrix.pkg }}" }
        run: ./scripts/ci.sh test "$PKG"
```
The guard prevents an empty matrix, which fails the workflow.

## 4. Other ecosystems

```yaml
# Go: setup-go caches GOMODCACHE and GOCACHE keyed on go.sum by default
- uses: actions/setup-go@<sha> # v7.x
  with: { go-version-file: go.mod }
- run: go test -race -count=1 ./...

# Rust: toolchain from rust-toolchain.toml, then rust-cache
- run: rustup show active-toolchain || rustup toolchain install
- uses: Swatinem/rust-cache@<sha> # v2.x
  with: { shared-key: "ci", save-if: "${{ github.ref == 'refs/heads/main' }}" }
- run: cargo nextest run --workspace --locked

# Generic cache with explicit key
- uses: actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0
  with:
    path: ~/.cache/pre-commit
    key: ${{ runner.os }}-${{ runner.arch }}-pre-commit-${{ hashFiles('.pre-commit-config.yaml') }}
    restore-keys: ${{ runner.os }}-${{ runner.arch }}-pre-commit-
```
`save-if` on main only is a good default for large caches: PRs restore main's cache but do not fill the
10 GB quota with per-branch copies.

## 5. Reusable workflow and composite action

```yaml
# org/ci/.github/workflows/python.yml (callee)
on:
  workflow_call:
    inputs:
      python-version: { type: string, required: true }
      working-directory: { type: string, default: "." }
    outputs:
      coverage: { value: "${{ jobs.test.outputs.coverage }}" }
permissions: { contents: read }
jobs:
  test:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    outputs:
      coverage: ${{ steps.cov.outputs.percent }}
    defaults: { run: { working-directory: "${{ inputs.working-directory }}" } }
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - uses: astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884 # v10.3.0
        with: { python-version: "${{ inputs.python-version }}", enable-cache: true }
      - run: uv sync --locked && uv run pytest --cov --cov-report=json
      - id: cov
        run: echo "percent=$(jq .totals.percent_covered_display coverage.json)" >> "$GITHUB_OUTPUT"
```

```yaml
# caller
jobs:
  py:
    uses: org/ci/.github/workflows/python.yml@<sha> # v3.2.0
    with: { python-version: "3.13", working-directory: apps/api }
```

```yaml
# .github/actions/setup-web/action.yml (composite)
name: setup-web
description: pnpm + node + install with cache
runs:
  using: composite
  steps:
    - uses: pnpm/action-setup@ea17c68df8912ef543352723c149a84f56e3d413 # v6.1.0
    - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
      with: { node-version-file: .nvmrc, cache: pnpm }
    - shell: bash
      run: pnpm install --frozen-lockfile
```
Composite `run:` steps must declare `shell:`. Local composite actions need the repo checked out first.

## 6. Repo script as the single source of truth

```bash
#!/usr/bin/env bash
# scripts/ci.sh: identical on a laptop and in CI
set -Eeuo pipefail
cd "$(dirname "$0")/.."
case "${1:?usage: ci.sh lint|test|build}" in
  lint)  uv run --locked ruff check . && pnpm -r lint ;;
  test)  uv run --locked pytest "${@:2}" ;;
  build) docker buildx build -f apps/api/Dockerfile . ;;
  *) echo "unknown target: $1" >&2; exit 2 ;;
esac
```
`just` (`justfile` recipes) and `make` serve the same role; pick one per repo.

## 7. Failure evidence

```yaml
- if: failure()
  uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
  with:
    name: failure-${{ github.job }}-${{ strategy.job-index }}
    path: |
      test-results/
      playwright-report/
      **/*.log
    retention-days: 7
```
Print the effective context when a condition misbehaves:
`env: { CTX: "${{ toJSON(github) }}" }` then `run: echo "$CTX" | jq '{event_name, ref, head_ref, base_ref}'`.
