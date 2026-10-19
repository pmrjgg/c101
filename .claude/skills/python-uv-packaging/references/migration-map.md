# Migration map and command reference

Companion to `python-uv-packaging` section 8. Run `uvx migrate-to-uv --dry-run` first; use this page
to review its output and to translate what the tool cannot (scripts, CI, docs).

## Poetry -> uv

| Poetry | uv |
|---|---|
| `poetry new pkg` / `poetry init` | `uv init --lib pkg` / `uv init --bare --package` |
| `poetry add httpx` | `uv add httpx` |
| `poetry add --group dev pytest` | `uv add --dev pytest` |
| `poetry add --group docs mkdocs` | `uv add --group docs mkdocs` |
| `poetry add --optional typer` + `[tool.poetry.extras]` | `uv add --optional cli typer` |
| `poetry install` | `uv sync` |
| `poetry install --without dev` / `--only main` | `uv sync --no-dev` / `uv sync --no-default-groups` |
| `poetry sync` (1.x: `poetry install --sync`) | `uv sync` (always exact) |
| `poetry lock` (2.x keeps versions) | `uv lock` |
| `poetry update` / `poetry lock --regenerate` | `uv lock --upgrade` |
| `poetry update httpx` | `uv lock --upgrade-package httpx && uv sync` |
| `poetry run pytest` | `uv run pytest` |
| `poetry shell` (a plugin since Poetry 2) | `source .venv/bin/activate` (or just `uv run`) |
| `poetry show --tree` / `--outdated` | `uv tree` / `uv tree --outdated` |
| `poetry build` / `poetry publish` | `uv build` / `uv publish` |
| `poetry version minor` | `uv version --bump minor` |
| `poetry export -f requirements.txt` (a plugin since Poetry 2) | `uv export --format requirements.txt` |
| `poetry env use 3.12` | `uv python pin 3.12` |
| `poetry source add corp URL --priority explicit` | `[[tool.uv.index]] name = "corp", url = ..., explicit = true` |
| `[tool.poetry.scripts]` | `[project.scripts]` |
| `packages = [{ include = "pkg", from = "src" }]` | default for uv_build (`src/<name>`); flat: `module-root = ""` |

### Version constraint translation

| Poetry | PEP 440 | Note |
|---|---|---|
| `^1.2.3` | `>=1.2.3,<2.0.0` | caret: next major |
| `^1.2` | `>=1.2,<2.0` | |
| `^0.2.3` | `>=0.2.3,<0.3.0` | caret on 0.x bumps the minor |
| `^0.0.3` | `>=0.0.3,<0.0.4` | caret on 0.0.x bumps the patch |
| `~1.2.3` | `>=1.2.3,<1.3.0` | tilde: next minor |
| `~1.2` | `>=1.2,<1.3` | |
| `~1` | `>=1,<2` | |
| `1.2.*` | `==1.2.*` | |
| `python = "^3.10"` | `requires-python = ">=3.10"` | drop the implicit `<4.0` upper bound |

For libraries, consider loosening caret upper bounds to plain lower bounds after migration: caret caps
are the most common cause of unsatisfiable resolutions downstream. Applications can keep caps because
uv.lock pins exact versions anyway.

## Pipenv -> uv

| Pipenv | uv |
|---|---|
| `[packages]` in Pipfile | `[project].dependencies` |
| `[dev-packages]` | `[dependency-groups].dev` |
| `[requires] python_version = "3.12"` | `requires-python = ">=3.12"` + `uv python pin 3.12` |
| `pipenv install` / `pipenv sync` | `uv sync` / `uv sync --locked` |
| `pipenv run x` | `uv run x` |
| `pipenv lock -r` | `uv export --format requirements.txt` |
| `.env` auto-loading | `uv run --env-file .env x` (explicit; `UV_ENV_FILE` to default it) |

## pip-tools and plain pip

| Before | After (project mode) | After (keep requirements files) |
|---|---|---|
| `pip-compile requirements.in` | `uv add -r requirements.in` then `uv lock` | `uv pip compile requirements.in -o requirements.txt` |
| `pip-compile --upgrade-package x` | `uv lock --upgrade-package x` | `uv pip compile ... --upgrade-package x` |
| `pip-sync requirements.txt` | `uv sync` | `uv pip sync requirements.txt` |
| `pip install -e .` | `uv sync` (project is editable by default) | `uv pip install -e .` |
| `python -m venv .venv` | automatic | `uv venv` |
| `pipx install black` / `pipx run` | `uv tool install black` / `uvx black` | same |
| `pyenv install 3.13` | `uv python install 3.13` | same |

Conda: uv manages Python packages only. Keep conda or pixi when the project needs non-Python binaries
(CUDA toolkits, GDAL, compilers) from conda channels; do not mix `uv sync` into a conda env.

## Command reference (beyond the crib)

| Need | Command |
|---|---|
| upgrade everything in the lock | `uv lock --upgrade` (review `git diff uv.lock`) |
| upgrade one group | `uv lock --upgrade-group docs` |
| reproducible resolution as of a date | `uv lock --exclude-newer 2026-10-01T00:00:00Z` (or `exclude-newer` in `[tool.uv]`) |
| one-off extra package for a command | `uv run --with rich python script.py` |
| run with a different interpreter | `uv run --python 3.15 pytest` |
| ignore the project entirely | `uv run --no-project python -c "..."` |
| fresh throwaway env | `uv run --isolated --with pkg -- python` |
| which interpreter will be used | `uv python find` |
| list interpreters (installed / available) | `uv python list --only-installed` / `uv python list 3.15` |
| upgrade managed interpreters to latest patch | `uv python upgrade` |
| upgrade all global tools | `uv tool upgrade --all` |
| update uv itself (standalone installer) | `uv self update` |
| cache location / cleanup | `uv cache dir`, `uv cache clean <pkg>`, `uv cache prune` |
| which config, interpreter and indexes were used | `uv sync -v` (DEBUG lines: workspace root, config files, `.python-version`) |

## Environment variables worth knowing

| Variable | Effect |
|---|---|
| `UV_LOCKED=1` / `UV_FROZEN=1` | same as `--locked` / `--frozen` on every command |
| `UV_NO_DEV=1` | skip the dev group (production images) |
| `UV_NO_SYNC=1` | `uv run` without syncing first |
| `UV_PYTHON=3.13` | interpreter request for every command |
| `UV_PYTHON_DOWNLOADS=never` | never download interpreters |
| `UV_PROJECT_ENVIRONMENT=/opt/venv` | venv location instead of `.venv` |
| `UV_CACHE_DIR` / `UV_NO_CACHE=1` | cache location / disable |
| `UV_COMPILE_BYTECODE=1` | write `.pyc` at install time |
| `UV_LINK_MODE=copy` | copy instead of hardlink/clone from the cache |
| `UV_INDEX_<NAME>_USERNAME` / `_PASSWORD` | credentials for `[[tool.uv.index]] name = "<name>"` |
| `UV_DEFAULT_INDEX` / `UV_INDEX` | replace PyPI / add indexes (`UV_INDEX_URL`, `UV_EXTRA_INDEX_URL` are the deprecated spellings) |
| `UV_EXCLUDE_NEWER` | ignore distributions uploaded after a timestamp |
| `UV_OFFLINE=1` | never touch the network (air-gapped builds from a warm cache) |
