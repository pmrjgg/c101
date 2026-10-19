# CI and Docker recipes for uv projects

Companion to `python-uv-packaging` sections 9 and 10. Replace every `<full-commit-sha>` with the
40-character commit of the release you audited (the version goes in the trailing comment); SHA pinning
policy and runner hardening belong to `ci-pipelines`.

## GitHub Actions: check, test matrix, build, publish

```yaml
name: ci
on:
  push: { branches: [main], tags: ["v*"] }
  pull_request:

permissions: { contents: read }          # least privilege by default

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<full-commit-sha>          # vX
      - uses: astral-sh/setup-uv@<full-commit-sha>        # vX.Y.Z
        with: { enable-cache: true }
      - run: uv lock --check                              # stale lock fails fast
      - run: uv sync --locked --all-extras --dev
      - run: uv run --frozen ruff format --check
      - run: uv run --frozen ruff check
      - run: uv run --frozen mypy src

  test:
    needs: check
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest]
        python-version: ["3.12", "3.13", "3.14", "3.15"]
        include:
          - { os: macos-latest, python-version: "3.14" }
          - { os: windows-latest, python-version: "3.14" }
    steps:
      - uses: actions/checkout@<full-commit-sha>
      - uses: astral-sh/setup-uv@<full-commit-sha>
        with: { enable-cache: true, python-version: "${{ matrix.python-version }}" }
      - run: uv sync --locked --all-extras --dev
      - run: uv run --frozen pytest -q

  wheel-smoke:                            # the suite against the built wheel, not the editable tree
    needs: check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<full-commit-sha>
      - uses: astral-sh/setup-uv@<full-commit-sha>
        with: { enable-cache: true }
      - run: uv build --no-sources
      - run: uv run --isolated --no-project --with dist/*.whl --with pytest -- pytest tests -q

  build:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: [test, wheel-smoke]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<full-commit-sha>
      - uses: astral-sh/setup-uv@<full-commit-sha>
      - run: uv build --no-sources
      - uses: actions/upload-artifact@<full-commit-sha>
        with: { name: dist, path: dist/ }

  publish-testpypi:
    needs: build
    runs-on: ubuntu-latest
    environment: { name: testpypi }
    permissions: { id-token: write }      # OIDC, only in publish jobs
    steps:
      - uses: actions/download-artifact@<full-commit-sha>
        with: { name: dist, path: dist/ }
      - uses: astral-sh/setup-uv@<full-commit-sha>
      - run: uv publish --publish-url https://test.pypi.org/legacy/ --trusted-publishing always

  publish-pypi:
    needs: publish-testpypi
    runs-on: ubuntu-latest
    environment: { name: pypi }           # add required reviewers on this environment
    permissions: { id-token: write }
    steps:
      - uses: actions/download-artifact@<full-commit-sha>
        with: { name: dist, path: dist/ }
      - uses: astral-sh/setup-uv@<full-commit-sha>
      - run: uv publish --trusted-publishing always
```

Setup on the index side (once per project and per index): add a trusted publisher with owner,
repository, workflow file name (`ci.yml`) and environment name (`pypi` / `testpypi`). For a project
that does not exist yet, use a pending publisher. No `UV_PUBLISH_TOKEN` secret is needed or wanted.

Why two jobs: the build job runs arbitrary build code (backend, hooks); keeping `id-token: write` out
of it means a compromised build step cannot mint an upload token.

Cache notes:

- `enable-cache: true` keys the cache on the dependency files (uv.lock among them); a lock change
  creates a fresh entry.
- `uv cache prune --ci` removes wheels that are cheap to rebuild or re-download and keeps built-from-
  source wheels; setup-uv can prune automatically at the end of the job.
- Torch-sized dependencies: one cache per OS and Python version, or the restore costs more than it saves.

## Dockerfile: dependency layer, project layer, slim runtime

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# 1. dependencies only: cached until uv.lock or pyproject.toml changes
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable

# 2. the project itself, installed non-editable so the runtime stage needs no source tree
#    (.dockerignore must list .venv, .git, dist/ and __pycache__/)
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

FROM python:3.13-slim AS runtime
RUN useradd --system --uid 10001 app
COPY --from=build --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
USER app
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "shopapi.app:app"]
```

| Setting | Why |
|---|---|
| same base image in both stages | the venv's `python` symlink points at the base image interpreter |
| `UV_PYTHON_DOWNLOADS=never` | fail instead of silently downloading a second interpreter |
| `UV_COMPILE_BYTECODE=1` | faster cold start; costs build time |
| `UV_LINK_MODE=copy` | cache mount and target are on different filesystems; silences hardlink warnings |
| `UV_NO_DEV=1` | dev group never reaches the image |
| `--no-install-project` in layer 1 | source edits do not invalidate the dependency layer |
| `--frozen` in layer 1 | only the lock and root pyproject are present; mandatory for workspaces (`--no-install-workspace`) |
| `--locked` in layer 2 | full tree present, so assert the lock matches |
| `--no-editable` | copies the package into site-packages; runtime stage needs only `.venv` |

Pin the uv image tag (`0.13.1`) or its digest; `:latest` makes builds drift. Image scanning, SBOM and
size budgets are `container-images`.

## Other CI systems

The same five commands work anywhere uv is installed (versioned installer
`curl -LsSf https://astral.sh/uv/0.13.1/install.sh | sh`, or the `ghcr.io/astral-sh/uv` image):

```bash
uv lock --check
uv sync --locked --all-extras --dev
uv run --frozen ruff check && uv run --frozen mypy src
uv run --frozen pytest -q
uv build --no-sources
```

Cache directory: `UV_CACHE_DIR=.uv-cache` inside the workspace so the CI cache step can save it, and
`uv cache prune --ci` before saving.
