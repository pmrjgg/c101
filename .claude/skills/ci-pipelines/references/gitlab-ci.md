# GitLab CI mapping

Concept map from GitHub Actions, then the worked-example pipeline rewritten for GitLab. Check keyword
availability against your GitLab version (`/help` shows it); components and `auto_cancel` need a
recent release.

## 1. Concepts

| GitHub Actions | GitLab CI | Notes |
|---|---|---|
| workflow file per concern | one `.gitlab-ci.yml` plus `include:` | split by `include: local:` |
| `on:` triggers | `workflow: rules:` | e.g. MR pipelines plus default branch, no duplicate branch pipelines |
| `jobs.<id>.needs` | `needs:` | DAG; jobs without `needs` wait for all earlier stages |
| `if:` | `rules: - if:` | first matching rule wins; `when: never` to exclude |
| `paths` / paths-filter | `rules: - changes: { paths: [...], compare_to: refs/heads/main }` | without `compare_to`, branch pipelines compare to the previous push |
| `actions/cache` | `cache: { key: { files: [lockfile] }, paths: [...] }` | `key:files` takes at most two files; `policy: pull` for read-only |
| matrix | `parallel: matrix:` | each cell gets the variables |
| shards | `parallel: N` | `$CI_NODE_INDEX` (1-based) and `$CI_NODE_TOTAL` |
| concurrency cancel | `interruptible: true` + `workflow: auto_cancel: on_new_commit: interruptible` | |
| reusable workflow | `include: project:` / `include: component:` | components are versioned and take `inputs:` |
| composite action | `extends:` / YAML anchors / `!reference` | |
| artifacts | `artifacts: { paths, reports: { junit, coverage_report } }` | JUnit reports render in the MR widget |
| environments + reviewers | `environment: name:` + protected environments with approval rules | |
| OIDC | `id_tokens:` | audience per cloud |
| `timeout-minutes` | `timeout:` | job timeout cannot exceed the project/runner limit |

## 2. Worked example in GitLab

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  auto_cancel:
    on_new_commit: interruptible

default:
  interruptible: true
  timeout: 15m

variables:
  UV_CACHE_DIR: "$CI_PROJECT_DIR/.cache/uv"
  UV_VERSION: "0.13.1"

.py-rules: &py-rules
  rules:
    - changes: { paths: ["apps/api/**/*", "uv.lock", "pyproject.toml"], compare_to: refs/heads/main }

.uv:
  image: ghcr.io/astral-sh/uv:0.13.1-python3.13-trixie-slim
  cache:
    key: { files: [uv.lock] }
    paths: [.cache/uv]
  before_script:
    - uv sync --locked
  after_script:
    - uv cache prune --ci

py-test:
  extends: .uv
  stage: test
  <<: *py-rules
  parallel: 4
  variables:
    COVERAGE_FILE: ".coverage.$CI_NODE_INDEX"
  script:
    - uv run pytest apps/api --splits "$CI_NODE_TOTAL" --group "$CI_NODE_INDEX"
      --cov=apps/api --cov-report= --junitxml="reports/junit-py-$CI_NODE_INDEX.xml"
  artifacts:
    when: always
    expire_in: 3 days
    paths: [".coverage.*"]
    reports:
      junit: reports/junit-py-*.xml

py-report:
  extends: .uv
  stage: report
  <<: *py-rules
  needs: [py-test]
  script:
    - uv run coverage combine
    - uv run coverage report --fail-under=85
    - uv run coverage xml -o coverage.xml
  coverage: '/TOTAL.*\s+(\d+%)$/'
  artifacts:
    reports:
      coverage_report: { coverage_format: cobertura, path: coverage.xml }

ts-test:
  image: node:24-slim
  stage: test
  rules:
    - changes: { paths: ["packages/web/**/*", "pnpm-lock.yaml"], compare_to: refs/heads/main }
  parallel: 2
  cache:
    key: { files: [pnpm-lock.yaml] }
    paths: [.pnpm-store]
  script:
    - npm install -g pnpm@12.14.0
    - pnpm config set store-dir .pnpm-store
    - pnpm install --frozen-lockfile
    - cd packages/web && pnpm exec vitest run --shard="$CI_NODE_INDEX/$CI_NODE_TOTAL" --reporter=junit --outputFile="junit-$CI_NODE_INDEX.xml"
  artifacts:
    when: always
    reports: { junit: "packages/web/junit-*.xml" }

image:
  stage: build
  <<: *py-rules
  needs: [py-test]
  image: docker:29
  services: [docker:29-dind]
  script:
    - docker buildx create --use
    - docker buildx build -f apps/api/Dockerfile
      --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache:api
      --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache:api,mode=max
      -t "$CI_REGISTRY_IMAGE/api:$CI_COMMIT_SHA" .

deploy-prod:
  stage: deploy
  needs: [image, py-report]
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  environment: { name: production }
  interruptible: false
  id_tokens:
    AWS_TOKEN: { aud: sts.amazonaws.com }
  script:
    - ./scripts/promote.sh "$CI_REGISTRY_IMAGE/api:$CI_COMMIT_SHA"
```

Notes:
- Without `workflow: rules`, a push to an MR branch can create both a branch and an MR pipeline.
- `coverage combine` without arguments picks up `.coverage.*` from artifacts of all `needs:` jobs, since
  artifacts of needed jobs are downloaded into the project directory.
- The registry cache (`type=registry`) replaces `type=gha`; use a dedicated `cache:` tag.
- Image tags such as `docker:29` and the uv image tag are examples; pin to what your runners support and
  by digest for production.
- Deploy jobs set `interruptible: false` so a new commit never cancels a half-finished deploy.
