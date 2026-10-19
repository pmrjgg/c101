---
name: python-uv-packaging
description: "Python project and environment management with uv: lifecycle (init, add, lock, sync, run), --locked vs --frozen, pyproject.toml anatomy (PEP 621, PEP 735 groups, build backends, entry points), workspaces, custom indexes such as PyTorch CPU/CUDA, PEP 723 scripts, uvx tools, Python versions, migration from pip/Poetry, trusted publishing, CI and Docker. Load when creating, configuring, packaging or fixing a Python project's dependencies."
when_to_use: "Touching pyproject.toml, uv.lock, requirements*.txt, poetry.lock, Pipfile, .python-version or a '# /// script' block; errors such as 'needs to be updated, but --locked was provided', 'No solution found when resolving dependencies', 'Failed to build', a CUDA torch wheel where CPU was wanted; tasks: new project, add or upgrade deps, migrate to uv, build or publish a wheel, uv in CI or Docker."
---

# Python packaging with uv

Baseline: **uv 0.13.x** (October 2026) on CPython 3.12-3.15. uv replaces pip, pip-tools, virtualenv,
pipx, pyenv and Poetry. Flags move between minor releases: check `uv help <command>` before scripting
anything unusual. Neighbours: CI wiring in general is `ci-pipelines`, image hardening is
`container-images`, upgrade cadence and changelog review is `dependency-upgrades`.

Deep material: [CI and Docker recipes](references/ci-docker-recipes.md) |
[migration map and command reference](references/migration-map.md)

## 1. Lifecycle crib

| Task | Command | Writes |
|---|---|---|
| new application (packaged, src layout, console script) | `uv init --app myapp` | pyproject, `src/myapp/`, `.python-version` |
| flat application, no build system | `uv init --app --no-package myapp` | `main.py`, no `[build-system]` |
| library (src layout, `py.typed`, uv_build) | `uv init --lib mylib` | `src/mylib/py.typed` |
| pyproject only, in an existing directory | `uv init --bare --package --name shopapi` | pyproject only |
| runtime dependency | `uv add 'httpx>=0.28'` | `[project].dependencies`, uv.lock, .venv |
| dev tool | `uv add --dev pytest` | `[dependency-groups].dev` |
| other local group | `uv add --group docs mkdocs-material` | `[dependency-groups].docs` |
| published opt-in extra | `uv add --optional cli typer` | `[project.optional-dependencies].cli` |
| remove | `uv remove httpx` | pyproject, lock, env |
| resolve only / bump one package | `uv lock` / `uv lock --upgrade-package httpx` | uv.lock |
| env equals lock exactly | `uv sync` (removes extraneous packages; `--inexact` keeps them) | .venv |
| run inside the project env | `uv run pytest -q` (locks and syncs first, inexact) | |
| interpreter | `uv python install 3.14 && uv python pin 3.14` | `.python-version` |
| CLI tools outside the project | `uv tool install ruff`; one-off `uvx ruff check` | `~/.local/bin` |
| inspect | `uv tree --depth 1`, `uv tree --outdated`, `uv tree --invert --package urllib3` | |

- In uv 0.13 applications are packaged by default (`uv help init`); pass `--no-package` for a flat app.
- `uv add` records a lower bound at the resolved version (`--bounds lower`, the default);
  `--bounds major|minor|exact` changes that.
- `uv init` derives `requires-python` from the newest interpreter it finds. With 3.15 installed a new
  project gets `>=3.15`, which excludes most users: pass `--python 3.12` (your real floor).

## 2. `--locked` vs `--frozen`

| Mode | When uv.lock is stale or missing | Use in |
|---|---|---|
| default | re-locks and rewrites uv.lock | local development |
| `--locked` / `UV_LOCKED=1` | fails: "The lockfile at `uv.lock` needs to be updated, but `--locked` was provided." | CI, release builds |
| `--frozen` / `UV_FROZEN=1` | installs uv.lock as is, never compares with pyproject | Docker dependency layers, workspace partial copies, offline |
| `uv lock --check` | exit 1 when stale | pre-commit hook, first CI step |

Commit uv.lock for applications **and** libraries: it makes CI reproducible, and consumers never see it
(they resolve from `[project].dependencies`). Never hand-edit it; on a merge conflict take either side
and run `uv lock`.

## 3. pyproject anatomy

```toml
[project]
name = "shopapi"
version = "0.4.0"                    # or dynamic = ["version"] with hatch-vcs and similar
requires-python = ">=3.12"           # lower bound only
license = "MIT"                      # PEP 639 SPDX expression -> Metadata 2.4 License-Expression
dependencies = ["flask>=3.1", "httpx>=0.28"]   # lower bounds; no == pins in libraries

[project.optional-dependencies]      # extras: published, users opt in with shopapi[cli]
cli = ["typer>=0.15"]

[project.scripts]                    # console commands
shopapi = "shopapi.cli:main"

[project.entry-points."shopapi.plugins"]   # plugin discovery via importlib.metadata
csv = "shopapi.export:CsvExporter"

[dependency-groups]                  # PEP 735: local only, never in published metadata
test = ["pytest>=8", "respx>=0.22"]
dev = [{ include-group = "test" }, "mypy>=1.15", "ruff>=0.15"]
docs = ["mkdocs-material>=9.6"]

[tool.uv]
default-groups = ["dev"]             # synced by default; "all" selects every group

[build-system]
requires = ["uv_build>=0.13.1,<0.14"]   # upper bound recommended by uv for its own backend
build-backend = "uv_build"
```

| Build backend | Pick when | Notes |
|---|---|---|
| `uv_build` | pure Python | expects `src/<name>/__init__.py`; flat layout: `[tool.uv.build-backend] module-root = ""`; no C/Rust extensions |
| `hatchling` | build hooks, version from git tags (hatch-vcs), custom file selection | |
| `setuptools` | legacy `setup.py` projects, simple C extensions | |
| `maturin` / `scikit-build-core` | Rust / C++ extensions | `uv init --build-backend maturin` |

- **src layout**: tests import the installed package, not the working-tree copy, so a file missing from
  the wheel fails tests instead of shipping.
- **py.typed**: empty marker inside the package of a typed library (PEP 561); without it type checkers
  ignore your annotations downstream (`python-typing`).
- Versions: `uv version --short`; `uv version --bump minor` (0.4.0 -> 0.5.0);
  `uv version --bump patch --bump beta` (-> 0.4.1b1); add `--dry-run` to preview.

## 4. Sources and indexes

`[tool.uv.sources]` says *where* a dependency comes from; `[project].dependencies` still says *what*.
Sources are uv-only: published metadata carries only the `[project]` requirements and other build
frontends ignore sources, so prove the package still builds that way with `uv build --no-sources`.

```toml
[tool.uv.sources]
shared   = { workspace = true }                                   # workspace member
utils    = { path = "../utils", editable = true }                 # local checkout
patched  = { git = "https://github.com/org/patched", rev = "<commit-sha>" }   # tag/branch also allowed
internal = { index = "corp" }                                     # private index, this package only

[[tool.uv.index]]
name = "corp"
url = "https://pypi.corp.example/simple/"
explicit = true            # only packages that name this index may come from it
```

**PyTorch CPU or CUDA wheels.** Torch from PyPI pulls the CUDA `nvidia-*` packages on Linux; choose the
index explicitly:

```toml
[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[tool.uv.sources]
torch = [
  { index = "pytorch-cpu",   marker = "sys_platform != 'linux'" },
  { index = "pytorch-cu128", marker = "sys_platform == 'linux'" },
]
```

Pick the CUDA tag that the uv PyTorch guide and pytorch.org list for your driver (cu126, cu128, cu130 at
the time of writing). To choose CPU vs CUDA per install instead of per platform, use extras plus
`[tool.uv] conflicts = [[{ extra = "cpu" }, { extra = "cu128" }]]` and an `extra = "..."` key on each source.

**Cross-platform locks.** uv.lock is universal (all platforms) by default.

```toml
[tool.uv]
environments = ["sys_platform == 'darwin'", "sys_platform == 'linux'"]     # solve only these (disjoint)
required-environments = ["sys_platform == 'linux' and platform_machine == 'aarch64'"]  # wheels must exist
```

`required-environments` turns "works on my Mac, no wheel on the ARM server" into a lock-time error.

**Credentials.** Never in pyproject or uv.lock. For index `corp`: `UV_INDEX_CORP_USERNAME` and
`UV_INDEX_CORP_PASSWORD` (name uppercased, non-alphanumerics -> `_`), injected by the CI secret store.
The default `index-strategy = "first-index"` stops at the first index that has a package name, which
blocks dependency-confusion attacks; do not switch to `unsafe-best-match` to fix a resolution error.

## 5. Workspaces

One lockfile, one `.venv`, several packages (monorepo of services plus shared libs).

```toml
# root pyproject.toml
[tool.uv.workspace]
members = ["packages/*"]
exclude = ["packages/legacy"]

# packages/api/pyproject.toml
[project]
dependencies = ["core"]
[tool.uv.sources]
core = { workspace = true }          # `uv add core` inside packages/api writes this
```

| Task | Command |
|---|---|
| test one member | `uv run --package api pytest packages/api` |
| install every member | `uv sync --all-packages` |
| lock check for all | `uv lock --check` (single lock at the root) |
| export one member | `uv export --package api --no-dev --format requirements.txt` |

Use a workspace when members share a dependency set and release together; use path sources instead
when packages need conflicting versions of the same dependency (one lock means one version).

## 6. PEP 723 scripts

The default replacement for a shell script that grows past ~50 lines, parses data or needs a library
(the shell side of that decision is `shell-scripting`).

```bash
uv init --script tool.py --python 3.13      # writes the metadata block
uv add --script tool.py 'httpx>=0.28'       # edits the block
uv lock --script tool.py                    # writes tool.py.lock next to it (commit it)
uv run tool.py                              # ephemeral env, cached
```

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "httpx>=0.28",
# ]
# ///
```

After `chmod +x tool.py`, `./tool.py` runs anywhere uv is installed. `uv run --with rich tool.py` adds
a dependency for one run without editing the file.

## 7. Quality tooling

```toml
[tool.ruff]
line-length = 100                      # target version comes from requires-python
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]   # add "ASYNC" for asyncio code
```

- Ruff 0.16 (July 2026) widened the default rule set to roughly 400 rules; an explicit `lint.select`
  pins your policy so a ruff upgrade does not change it. `target-version` is only needed when it must
  differ from `requires-python`.
- `uv run ruff check --fix && uv run ruff format`; in CI `uv run ruff format --check`.
- Type checkers must run **inside the project env** so they see installed dependencies and stubs:
  `uv run mypy src`, `uv run pyright`, `uv run pyrefly check` (config: `python-typing`). Pin the
  checker in the `dev` group so CI and editors agree.
- Hooks: `uvx pre-commit install` (or `uvx prek install`, a faster reimplementation, or
  `uvx lefthook install`). Add `uv lock --check` as a local hook.

## 8. Migration

| From | Steps |
|---|---|
| `requirements.txt` | `uv init --bare --package --name app`, `uv add -r requirements.txt -c constraints.txt`, `uv add --dev -r requirements-dev.txt`, delete the txt files |
| Poetry, Pipenv, pip-tools, PDM | `uvx migrate-to-uv --dry-run`, then `uvx migrate-to-uv` (rewrites pyproject, locks unless `--skip-lock`) |
| pip-tools workflow you must keep | `uv pip compile requirements.in -o requirements.txt`; `uv pip sync requirements.txt` |
| consumers that need a requirements file | `uv export --format requirements.txt --no-dev -o requirements.txt` (hashes included; `--no-hashes` to drop) |
| PEP 751 consumers | `uv export --format pylock.toml -o pylock.toml` |
| SBOM | `uv export --format cyclonedx1.5` |

`uv add -r` keeps the original specifiers (`flask==3.1.3` stays pinned): relax pins in libraries to
lower bounds afterwards. Poetry's `^1.2` means `>=1.2,<2`; the translation table and edge cases
(caret on 0.x, `python = "^3.10"`) are in [the migration map](references/migration-map.md).

## 9. Build and publish

```bash
uv build --no-sources                 # sdist + wheel into dist/, as pypa/build would see it
unzip -l dist/*.whl                   # every module present? py.typed? no tests/ or .env?
tar tzf dist/*.tar.gz | head -50      # sdist: README, LICENSE, pyproject, src only
uv run --isolated --no-project --with dist/*.whl -- python -c "import shopapi"   # clean env
uv run --isolated --no-project --with dist/*.whl --with pytest -- pytest tests -q     # suite vs wheel
uv publish --index testpypi --dry-run && uv publish --index testpypi                  # rehearsal
```

TestPyPI needs an index entry with `publish-url = "https://test.pypi.org/legacy/"` and `explicit = true`.
Production releases use **PyPI trusted publishing** (OIDC): register the repository, workflow file and
environment as a trusted publisher on PyPI, give only the publish job `permissions: id-token: write`,
and run `uv publish` with no token (trusted publishing is `automatic` on GitHub Actions). Build in a
separate job so build steps never hold the OIDC permission. Full workflow:
[CI and Docker recipes](references/ci-docker-recipes.md).

## 10. CI, Docker and Python versions

```yaml
- uses: astral-sh/setup-uv@<full-commit-sha>   # vX.Y.Z, pin SHA per ci-pipelines
  with: { enable-cache: true, python-version: "${{ matrix.python-version }}" }
- run: uv sync --locked --all-extras --dev     # fails on a stale lock
- run: uv run --frozen pytest -q               # env already synced; skip re-resolution
- run: uv run --frozen mypy src
```

- Matrix `python-version: ["3.12", "3.13", "3.14", "3.15"]`; add `"3.14t"` (free-threaded) only when
  you ship C extensions or claim free-threading support.
- 3.15 (October 2026) turns on UTF-8 mode by default (PEP 686): `open()` without `encoding=` now means
  UTF-8 everywhere, including Windows. Pass `encoding="utf-8"` explicitly and delete code that relies on
  the locale encoding; run the suite on 3.15 to find stragglers.
- System interpreter only (distro Python, base image): `UV_PYTHON_DOWNLOADS=never`.
- Dependency-only Docker layer, then the project:

```dockerfile
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 UV_PYTHON_DOWNLOADS=never
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-editable
```

Workspaces must use `--frozen --no-install-workspace` for the first layer (member pyprojects are not
copied yet). Multi-stage layout, non-root user and image size are `container-images`.

## 11. Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| `uv pip install x` into the project `.venv` | works locally, missing in CI; next `uv sync` removes it | `uv add x` (or `--group`); `uv pip` is for non-project envs |
| upper bound in `requires-python` (`<3.13`, Poetry `^3.10`) | users on newer Python cannot install; lock covers fewer versions than CI tests | lower bound only; uv ignores dependency upper bounds anyway |
| committed `.venv` or `__pycache__` | huge diffs, wrong platform binaries | `.gitignore` (uv init writes one) |
| production image with dev tools | pytest, mypy in prod, bigger attack surface | `UV_NO_DEV=1` or `uv sync --no-dev` |
| editable project install only | missing package data never noticed until users install the wheel | test the built wheel (section 9) or `uv sync --no-editable` in one CI job |
| platform wheel absent from lock | "no wheel for linux/aarch64" at deploy time | `required-environments`, test on the target arch |
| unpinned build backend | sdist builds break when the backend releases a breaking version | `uv_build>=0.13.1,<0.14` as uv recommends; other backends need a floor that supports your metadata (PEP 639 license expressions) |
| `index-strategy = "unsafe-best-match"` to fix a conflict | dependency confusion exposure | `explicit = true` index plus per-package source |
| secrets in `[[tool.uv.index]] url` | credential leaked to git and uv.lock | `UV_INDEX_<NAME>_USERNAME/PASSWORD` env vars |
| `--frozen` in CI test jobs | stale lock passes CI, breaks next `uv sync` | `--locked` in CI, `--frozen` only after a locked sync |

## 12. Worked example: requirements.txt Flask app to a published uv project

Start: `app.py`, `requirements.txt` (`flask==3.1.3`, `requests>=2.32`, `gunicorn`),
`requirements-dev.txt` (`pytest`), no tests of the packaging itself.

```bash
uv init --bare --package --name shopapi --python 3.12      # pyproject + uv_build backend only
mkdir -p src/shopapi && git mv app.py src/shopapi/app.py
touch src/shopapi/__init__.py src/shopapi/py.typed
uv add -r requirements.txt                                 # flask==3.1.3 kept: relax to >=3.1 for a library
uv add --dev -r requirements-dev.txt && uv add --dev ruff mypy
uv add --group docs mkdocs-material
git rm requirements.txt requirements-dev.txt
uv run flask --app shopapi.app routes                      # app still boots from the src layout
uv run ruff check --fix src && uv run ruff format src && uv run mypy --strict src
```

One dependency (an embedding helper) needs torch. Resolved from PyPI, the lock pulls 15 `nvidia-*`
CUDA packages for Linux (several GB); the service only needs CPU inference, so add the `pytorch-cpu`
index from section 4 with `explicit = true` and `torch = { index = "pytorch-cpu" }`, then
`uv add 'torch>=2.8'`. Check the lock:
`grep -n 'download.pytorch.org/whl/cpu' uv.lock` shows `torch` resolved from the CPU index on every
platform (on Linux the version carries a `+cpu` local tag).

CI (full YAML in the reference): `uv lock --check`, `uv sync --locked --all-extras --dev`,
`uv run --frozen pytest`. The lab project (58 packages including torch) syncs in 0.18 s locally from a
warm cache (`rm -rf .venv && time uv sync --locked`); with setup-uv restoring the uv cache, expect
about 2 s in CI, while a cold cache is dominated by the torch download.

Release the reusable core as a library wheel:

```bash
uv version --bump minor                    # 0.1.0 -> 0.2.0
uv build --no-sources
unzip -l dist/shopapi-0.2.0-py3-none-any.whl   # shopapi/__init__.py, app.py, py.typed, dist-info
uv run --isolated --no-project --with dist/shopapi-0.2.0-py3-none-any.whl -- python -c "import shopapi"
git tag v0.2.0 && git push --tags          # tag triggers build job, then publish job (OIDC) to TestPyPI
                                           # then PyPI; no API token stored anywhere
```

Done when: no requirements files remain, `uv lock --check` passes, CI runs `--locked`, the wheel
installs in a clean env, and PyPI's file details say the release was uploaded via Trusted Publishing.

Related: `python-typing`, `python-asyncio`, `pytest-patterns`, `python-performance-profiling`,
`fastapi-pydantic-services`, `ci-pipelines`, `container-images`, `dependency-upgrades`,
`shell-scripting`, `testing-strategy`, `security-review`; hub `coding-general`.
