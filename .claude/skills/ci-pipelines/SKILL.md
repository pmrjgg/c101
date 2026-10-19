---
name: ci-pipelines
description: "Fast, reliable, secure CI pipelines, GitHub Actions first with a GitLab CI mapping: stage order and budgets, least-privilege skeleton, concurrency cancellation, path filters and affected builds, matrices and test sharding, dependency and Docker caching, reusable workflows and composite actions, merge queues, release jobs with OIDC and attestations, debugging failed runs. Load when creating, speeding up, hardening or debugging a CI workflow."
when_to_use: "Editing .github/workflows/*.yml, action.yml, .gitlab-ci.yml or CI scripts; PR checks take over 10 minutes; a cache never hits; a required check stays Pending; a job fails only in CI; adding a release, deploy, matrix, shard or merge-queue job; zizmor or actionlint findings."
---

# CI pipelines

Pipeline engineering: speed, reliability, reuse. The security checklist for CI (template injection,
`pull_request_target`, runner trust, supply chain) lives in `security-review` section 8; review lines
live in `code-review-checklist`. This skill keeps a short hardening summary (section 8) and points there.
Action versions below were current in October 2026; let Renovate or pinact move them, do not hand-edit.

Deep material:
[GitHub Actions recipes and the full worked-example workflow](references/github-actions-recipes.md) |
[GitLab CI mapping and equivalent pipeline](references/gitlab-ci.md)

## 1. Stage order and budgets

Cheapest and most likely to fail first. Each stage has a wall-clock budget; a stage over budget is a bug.

| # | Stage | Typical tools | Budget (PR) | Runs on |
|---|---|---|---|---|
| 1 | Format and lint | ruff, eslint/biome, shellcheck, actionlint, zizmor | < 1 min | every PR |
| 2 | Type-check | mypy/pyright, tsc --noEmit, cargo check | < 2 min | every PR |
| 3 | Unit tests | pytest, vitest, go test, nextest | < 5 min per shard | every PR |
| 4 | Build | package, binary, image (no push on PRs) | < 3 min cached | every PR |
| 5 | Integration | Testcontainers, compose services | < 8 min per shard | PR when paths match, merge queue |
| 6 | E2E / deploy | Playwright, smoke tests, deploy to staging | < 15 min | merge queue / main |

Rules:
- PR feedback target: p50 wall clock under 10 minutes from push to all required checks green.
- Serialize with `needs:` only where it saves real money (E2E, image push, deploy behind tests); run
  independent cheap stages in parallel, since developer wait costs more than runner minutes.
- Required checks only on stable, deterministic jobs. A flaky job that is required trains people to
  click re-run; quarantine it (`testing-strategy` flaky-test section) before making it required.
- Make one aggregator job (`ci-ok`) the only required check, so path-skipped jobs do not block merges
  (a workflow skipped by `paths:` leaves its required checks Pending forever).
- `timeout-minutes` on every job: about 3x the job's p95. The default is 360 minutes.

## 2. Workflow skeleton

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]
  merge_group:                          # required checks must also run in the merge queue
permissions:
  contents: read                        # least privilege; jobs add only what they need
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}   # never cancel main builds
jobs:
  lint:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false    # no token left in .git/config for later steps
      - run: ./scripts/ci.sh lint       # real logic lives in the repo (section 6)
```

| Element | Why | Check |
|---|---|---|
| `merge_group` trigger | merge queue only runs workflows that list it; without it the queue waits forever | queue a PR, see checks start |
| top-level `permissions: contents: read` | `GITHUB_TOKEN` defaults may be write-all on older orgs | zizmor `excessive-permissions` |
| `concurrency` with `cancel-in-progress` on PRs | a new push cancels the stale run; every superseded run stops burning minutes | push twice, first run shows Cancelled |
| `timeout-minutes` | hung jobs otherwise burn 6 hours | actionlint does not enforce it; grep |
| `persist-credentials: false` | later steps (and uploaded artifacts) cannot reuse the token | zizmor `artipacked` |
| full 40-char SHA pins + `# vX.Y.Z` comment | tags are mutable; a hijacked tag runs in your CI | zizmor `unpinned-uses` |

Pin and keep fresh: `pinact run` (rewrites `uses:` to SHAs with version comments), `ratchet pin
.github/workflows/*.yml`, or Renovate with the `helpers:pinGitHubActionDigests` preset, which also opens
update PRs. Pin tool versions too: `uv` via `version:`, Node via `.nvmrc`, container images by digest.

## 3. Caching recipes

| Ecosystem | Recipe | Key inputs |
|---|---|---|
| Python (uv) | `astral-sh/setup-uv` with `enable-cache: true`, `cache-dependency-glob: uv.lock` | uv.lock, python arch |
| Node (pnpm) | `pnpm/action-setup` (version from `packageManager`), then `actions/setup-node` with `cache: pnpm`; or `pnpm/action-setup` `cache: true` alone | pnpm-lock.yaml |
| Node (npm) | `actions/setup-node` `cache: npm` (automatic when `packageManager` names npm) | package-lock.json |
| Go | `actions/setup-go` (caches module and build cache by default, keyed on go.sum) | go.sum |
| Rust | `Swatinem/rust-cache` after toolchain install; set `shared-key` across jobs that build the same target | Cargo.lock, toolchain |
| Anything else | `actions/cache` with explicit key and restore-keys | lockfile hash |
| Docker layers | `docker/build-push-action` `cache-from: type=gha,scope=<image>` and `cache-to: type=gha,mode=max,scope=<image>` | Dockerfile + context |

Key design for `actions/cache`:
```yaml
key: ${{ runner.os }}-${{ runner.arch }}-poetry-1.8-${{ hashFiles('**/poetry.lock') }}
restore-keys: |
  ${{ runner.os }}-${{ runner.arch }}-poetry-1.8-
```
- Key = OS + arch + tool + tool version + lockfile hash. A key with no hash never invalidates; a key
  hashing source files never hits.
- A `restore-keys` prefix hit restores stale content and reports `cache-hit: false`; the step then saves
  a fresh entry under the exact key at job end.
- Cache what is expensive to recreate and cheap to download (package stores, compiler caches), not
  `node_modules` or `.venv` built for one OS/arch (fragile across runner image updates).
- Limits: default 10 GB per repository with LRU eviction, entries unused for 7 days are evicted;
  `gh cache list --sort size_in_bytes` shows what fills it. Matrix jobs writing distinct large caches
  evict each other.

Measure the hit rate, do not assume it:
```bash
for id in $(gh run list -w ci -L 50 --json databaseId -q '.[].databaseId'); do
  gh run view "$id" --log | grep -oE 'Cache restored from key|Cache not found for input keys'
done | sort | uniq -c        # hit rate = restored / (restored + not found)
```
Target above 90% on PRs. Below that: key includes something that changes per run (timestamps,
`github.sha`), or the cache is saved only on branches PRs cannot read.

Trust boundaries: a run can restore caches from its own ref and the base/default branch; PR caches are
invisible to `main`. Poisoning comes from jobs that run untrusted code in the default-branch context
(`pull_request_target`, `workflow_run`, `issue_comment`). Those jobs must not save caches, and release
jobs should build without restoring caches (setup-uv's default `enable-cache: auto` already skips
release, tag-push, `pull_request_target` and `workflow_run` events).

## 4. Selective work

| Need | Mechanism | Caveat |
|---|---|---|
| Skip a whole workflow for docs-only changes | `on.pull_request.paths-ignore: ['**/*.md', 'docs/**']` | a skipped workflow leaves required checks Pending; only for non-required workflows |
| Skip individual jobs | `dorny/paths-filter` job emitting outputs; `if: needs.changes.outputs.py == 'true'` | needs `pull-requests: read`; required check = aggregator |
| JS monorepo affected packages | `turbo run test --affected` (= `--filter=...[main...HEAD]`), override base with `TURBO_SCM_BASE`; or `--filter=...[origin/main]` | a too-shallow checkout marks everything changed; fetch history |
| Nx | `npx nx affected -t lint test build --base=origin/main --head=HEAD` (`nrwl/nx-set-shas` computes base on main) | same history requirement |
| Bazel / Pants / Buck | remote cache + `bazel test //...`; the cache makes unaffected targets free | remote cache write only from trusted branches |
| Dynamic matrix | plan job prints JSON to `$GITHUB_OUTPUT`; consumer uses `matrix: ${{ fromJSON(needs.plan.outputs.matrix) }}` | an empty matrix fails the run; guard the consumer with an `if:` on the plan output (recipe in the reference) |

Aggregator job, the single required check:
```yaml
  ci-ok:
    if: always()
    needs: [lint, py-test, ts-test, image]
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

## 5. Matrices and sharding

Compatibility grids:
```yaml
strategy:
  fail-fast: false                      # see every failing cell, not just the first
  max-parallel: 6                       # protect shared resources (DB, rate-limited APIs)
  matrix:
    os: [ubuntu-24.04, macos-15]
    python: ["3.12", "3.13"]
    include:
      - { os: ubuntu-24.04, python: "3.14", experimental: true }
    exclude:
      - { os: macos-15, python: "3.12" }
continue-on-error: ${{ matrix.experimental == true }}   # only for explicitly experimental cells
```
Matrix size = product of axis lengths - excluded cells + `include` entries that match no existing cell
(matching entries only add keys); a matrix is capped at 256 jobs. Test the
full grid on `main`/nightly and a reduced grid (newest + oldest supported) on PRs.

Sharding a slow suite:

| Runner | Shard command | Merge |
|---|---|---|
| pytest | `pytest --splits N --group i` (pytest-split, durations in `.test_durations` from `--store-durations`); in-machine `-n auto` (xdist) | `coverage combine`; `junitparser merge --glob` |
| vitest | `vitest run --reporter=blob --shard=i/N` (writes `.vitest/blob/`) | `vitest run --merge-reports` |
| Playwright | `npx playwright test --shard=i/N`, `reporter: 'blob'` in CI, `fullyParallel: true` for balance | `npx playwright merge-reports --reporter html ./all-blob-reports` |
| Go | `go test $(go list ./... \| awk -v n=N -v i=I 'NR % n == i - 1')` | `go tool covdata merge` or concatenated profiles |
| Jest | `jest --shard=i/N` | merge coverage with nyc/istanbul |

Shard count: `N = ceil(T_serial / (T_target - T_setup))`. Example: 550 s serial, 180 s target, 35 s setup
gives ceil(550/145) = 4. Runner cost = `N x T_setup + T_serial`, so each shard adds one setup; stop when
setup dominates. Re-store durations weekly (scheduled job) or shards drift out of balance.
Upload per-shard reports with `actions/upload-artifact` (`include-hidden-files: true` for `.vitest/`
and `.coverage.*`), then merge in one final job with `actions/download-artifact` `pattern:` +
`merge-multiple: true`.

## 6. Reuse

| Mechanism | Unit | Use for | Versioning |
|---|---|---|---|
| Reusable workflow (`on: workflow_call`) | whole jobs with their own runners, permissions, environments | org-wide pipeline shapes (build-test-release) | `uses: org/ci/.github/workflows/py.yml@<sha>` |
| Composite action (`runs: using: composite`) | steps inside the caller's job | repeated setup (toolchain + cache + install) | `uses: org/actions/setup-py@<sha>` or local `./.github/actions/setup` |
| Repo script (`just ci`, `make ci`, `scripts/ci.sh`) | the actual logic | everything that should run identically on a laptop | lives with the code |

```yaml
# .github/workflows/py.yml (callee)
on:
  workflow_call:
    inputs:
      python-version: { type: string, required: true }
      shards: { type: number, default: 1 }
    secrets:
      PYPI_TOKEN: { required: false }
```
Callers pass `with:` and either named `secrets:` or `secrets: inherit` (inherit only within one org).
The caller's `permissions:` cap what the callee can request. Keep YAML thin: a step that is more than
5 lines of shell belongs in `scripts/` where `shellcheck` and local runs reach it (`shell-scripting`).

## 7. Release and deploy jobs

```yaml
  release:
    needs: [ci-ok, image]               # image job exposes outputs.digest
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-24.04
    environment: production             # required reviewers + branch rules live on the environment
    permissions:
      contents: read
      id-token: write                   # OIDC: only in this job
      attestations: write
      artifact-metadata: write
      packages: write
    steps:
      - uses: aws-actions/configure-aws-credentials@<sha> # pin like every other action
        with: { role-to-assume: "arn:aws:iam::123456789012:role/deploy-prod", aws-region: eu-west-1 }
      - env: { IMAGE_DIGEST: "${{ needs.image.outputs.digest }}" }
        run: ./scripts/promote.sh "$IMAGE_DIGEST"    # retag the tested digest, never rebuild
      - uses: actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4.2.2
        with:
          subject-name: ghcr.io/acme/api
          subject-digest: ${{ needs.image.outputs.digest }}
          push-to-registry: true
```
- Build once, promote the same digest through staging and production
  (`docker buildx imagetools create --tag ghcr.io/acme/api:1.4.0 ghcr.io/acme/api@sha256:...`).
- Cloud trust policy pins `sub` to `repo:acme/app:environment:production`, not the whole repo.
- Provenance: `actions/attest` (v4; `actions/attest-build-provenance` v4 is now a wrapper around it).
  SBOM: generate with syft/`anchore/sbom-action`, attest with `actions/attest` `sbom-path:`.
  Consumers verify with `gh attestation verify oci://ghcr.io/acme/api@sha256:... --owner acme`.

## 8. Hardening summary (depth in `security-review`)

- Never interpolate `${{ github.event.* }}` (titles, branch names, bodies) into `run:`; pass via `env:`
  and quote: `env: { TITLE: "${{ github.event.pull_request.title }}" }` then `"$TITLE"`.
- `pull_request_target` and `workflow_run` never check out and execute PR code with secrets or write tokens.
- Secrets only in the jobs that need them; prefer OIDC over long-lived cloud keys.
- Lint every workflow change: `actionlint` (syntax, expressions, shellcheck on `run:`) and
  `zizmor .github/workflows` (`--min-severity=medium` while burning down a backlog). In CI use
  `zizmorcore/zizmor-action` with `security-events: write`; it uploads SARIF and does not fail the job by
  default, so make the code-scanning check required or set `advanced-security: false` to print findings.

## 9. Debugging failed runs

1. Read the first error, not the last; later failures are usually consequences.
2. `gh run view <run-id> --log-failed` (only failed steps); `gh run view <run-id> --job <job-id> --log`.
3. Re-run failed jobs only: `gh run rerun <run-id> --failed`; with debug logging add `--debug`
   (or set repository secret/variable `ACTIONS_STEP_DEBUG=true`; `ACTIONS_RUNNER_DEBUG=true` for runner
   diagnostics). Passing on rerun without changes = flaky: record it, follow `testing-strategy`.
4. Reproduce in the same environment: the runner image or container (`docker run --rm -v "$PWD":/src
   -w /src <image> ./scripts/ci.sh test`), or `act -j <job>` for workflow logic (act images differ from
   hosted runners; trust it for YAML wiring, not for toolchain behavior).
5. Keep evidence: `if: failure()` step uploading logs, screenshots, `core` files with
   `actions/upload-artifact`, short retention (`retention-days: 7`).
6. Environment diffs (locale, timezone, CPU count, file ordering, missing services) follow the
   `debugging-method` environment table.

| Symptom | Likely cause | Fix |
|---|---|---|
| Required check stuck at "Expected, waiting for status to be reported" | workflow skipped by `paths`/branch filter, or no `merge_group` trigger | aggregator job; add `merge_group` |
| `Resource not accessible by integration` | missing `permissions:` entry (e.g. `pull-requests: write`) or fork PR read-only token | add the narrow permission; fork PRs cannot get write |
| Cache restored but install still slow | caching `restore-keys` partial hit, lockfile changed | expected once; check the key |
| Exit 137 in a step | OOM-kill on the runner | less parallelism (`-n 2`), bigger runner |
| Works on PR, fails on main | `if:` conditions on event, secrets absent on PR, cache scope | diff the `github` context (`toJSON(github)` into env, print) |
| Scheduled workflow stopped | public repo with no activity for 60 days auto-disables schedules | re-enable; keep the repo active or dispatch manually |

## 10. GitLab CI mapping

| GitHub Actions | GitLab CI |
|---|---|
| job `needs:` | `needs:` (DAG; without it jobs wait for the previous `stage:`) |
| `if:` on jobs/steps | `rules: - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'` |
| `paths` filter | `rules: - changes: { paths: [api/**/*], compare_to: refs/heads/main }` |
| `actions/cache` key from lockfile | `cache: { key: { files: [uv.lock] }, paths: [.cache/uv] }` (max 2 files) |
| `strategy.matrix` | `parallel: { matrix: [ { PY: ["3.12", "3.13"] } ] }` |
| shard i/N | `parallel: 4` with `$CI_NODE_INDEX` / `$CI_NODE_TOTAL` |
| `concurrency` cancel | `interruptible: true` + `workflow: auto_cancel: on_new_commit: interruptible` |
| reusable workflow / composite action | `include:` (local/project/remote/template) and CI/CD components `include: - component: $CI_SERVER_FQDN/org/comp/name@1.2.0` with `inputs:` |
| `environment:` with reviewers | `environment: { name: production }` + protected environments with approvals |
| OIDC `id-token: write` | `id_tokens: { AWS_TOKEN: { aud: sts.amazonaws.com } }` |
| `timeout-minutes` | `timeout: 15m` |

Full equivalent pipeline: [GitLab CI mapping](references/gitlab-ci.md).

## 11. Pitfalls

| Pitfall | Consequence | Do instead |
|---|---|---|
| `uses: x@v3`, `image: node:latest`, `pip install tool` unpinned | silent breakage or supply-chain compromise | SHA pins, digests, lockfiles, pinned tool versions |
| Cache key without lockfile hash, or with `github.sha` | never invalidates / never hits | OS + arch + tool version + lockfile hash |
| Printing a derived secret (decoded, concatenated) | GitHub masks only registered values | `echo "::add-mask::$DERIVED"` before any use |
| `continue-on-error: true` on real checks | red tests shown as green | only for explicit experimental matrix cells |
| Matrix explosion (4 OS x 5 versions x 3 DBs = 60 jobs) | queue time, cost, flaky surface | reduced PR grid, full grid nightly |
| `curl`, `apt-get`, registry pulls with no retry | network blips fail builds | `curl --retry 3 --retry-all-errors`, tool retry flags, mirrors |
| Scheduled workflows in public repos | disabled after 60 days without repo activity | monitor; `workflow_dispatch` fallback |
| `fetch-depth: 1` with affected/diff tooling | everything "changed" or wrong base | `fetch-depth: 0` or `--filter=blob:none` |
| Logic in 40-line `run:` blocks | untestable, unlinted, differs from local | `scripts/ci.sh`, `just` recipes |
| Path-filtered required workflow | PRs blocked by Pending checks | job-level filters + aggregator |

## 12. Worked example: Python + TS monorepo CI, 18 min to 6 min

Repo: `apps/api` (FastAPI, uv workspace, 1,900 pytest tests), `packages/web` (TS, pnpm, 640 vitest
tests), `apps/api/Dockerfile`. Baseline from `gh run list -w ci -L 40 --json createdAt,updatedAt`:
p50 18m10s; every push reinstalled everything; no cancellation; image built from scratch.

Changes, in order of payoff:
1. Concurrency cancellation on PRs (stale runs were 38% of minutes).
2. Caches: setup-uv keyed on `uv.lock`, setup-node `cache: pnpm`; hit rate over 50 runs: 94%.
3. `changes` job with `dorny/paths-filter`: Python-only PRs (61% of PRs) skip TS lint and vitest.
4. Shards: pytest 4 (ceil(550 / (180 - 35)) = 4), vitest 2; merge job combines JUnit and coverage.
5. Docker build with `type=gha` cache scoped `api`, pushed only on `main`.
6. `pinact run` pinned all 12 actions; `zizmor .github/workflows` and `actionlint` report 0 findings.

Core of `.github/workflows/ci.yml` (full file: [recipes](references/github-actions-recipes.md)):
```yaml
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
        run: uv run pytest apps/api --splits 4 --group "$SHARD" --cov=apps/api --cov-report= --junitxml="reports/junit-py-$SHARD.xml"
      - uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        with:
          name: py-${{ matrix.shard }}
          path: |
            reports/
            .coverage.*
          include-hidden-files: true    # .coverage.* is a dotfile
          retention-days: 3
```

Result over the next 40 PR runs:

| Stage | Before | After |
|---|---|---|
| Dependency install (uv + pnpm) | 3m30s | 31s (cache hit) |
| pytest | 9m10s serial | 4 shards, slowest 2m35s |
| vitest | 4m20s | 2 shards, slowest 2m05s; skipped on 61% of PRs |
| Image build | 6m00s cold | 1m10s with `type=gha` cache |
| PR wall clock p50 | 18m10s | 6m05s |
| Runner minutes per PR | 31 | 19 (shards add setup, skips and cancels remove more) |

Verification: `actionlint` exit 0; `zizmor .github/workflows` reports no findings; forced a lockfile change
and saw a cache miss then a hit on the next run; queued a PR in the merge queue and saw `ci-ok` report.

Related: `container-images`, `shell-scripting`, `observability-instrumentation`, `dependency-upgrades`,
`git-advanced-workflows`, `pytest-patterns`, `typescript-testing-vitest`, `security-review`,
`testing-strategy`, `debugging-method`, hub `coding-general`.
