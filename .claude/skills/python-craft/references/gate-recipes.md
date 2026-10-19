# Gate recipes and tool mapping

How to run the python-craft gate in projects that are not (yet) uv + ruff + mypy/pyright + pytest,
without migrating their tooling inside an unrelated change.

## 1. Find the project's own commands first

```bash
grep -nE 'ruff|black|isort|flake8|pylint|mypy|pyright|pytest|tox|nox' Makefile justfile noxfile.py tox.ini 2>/dev/null | head -40
grep -nE 'run:|uses:' .github/workflows/*.yml 2>/dev/null | grep -iE 'ruff|mypy|pyright|pytest|tox|nox|uv|poetry' | head -40
grep -nE '^\s*- (id|repo):' .pre-commit-config.yaml 2>/dev/null
```

The CI job is the contract. If CI runs `make check`, run `make check`; if it runs `nox -s tests`,
run that. Use the table below only when there is no project command.

## 2. Tool mapping (legacy → ruff era)

| Project uses | Run it as | ruff equivalent (only if the project already adopted ruff) |
|---|---|---|
| black | `black --check .` | `ruff format --check .` |
| isort | `isort --check-only --diff .` | `ruff check --select I .` |
| flake8 (+ plugins) | `flake8` | `ruff check` with E, F, W plus plugin codes (B, SIM, C4, ...) |
| pyupgrade | `pyupgrade --py312-plus <files>` | `ruff check --select UP` |
| pylint | `pylint <pkg>` | partial: `PL` rules; keep pylint if CI runs it |
| bandit | `bandit -r src` | `ruff check --select S` |
| pydocstyle | `pydocstyle` | `ruff check --select D` |

## 3. Environment runners

| Manager | Install the env | Run a tool inside it |
|---|---|---|
| uv | `uv sync --locked` | `uv run <tool>` |
| Poetry | `poetry install --sync` | `poetry run <tool>` |
| Hatch | `hatch env create` | `hatch run <env>:<script>` |
| PDM | `pdm sync` | `pdm run <tool>` |
| pip-tools | `python -m venv .venv && .venv/bin/pip-sync requirements*.txt` | `.venv/bin/<tool>` |
| tox | `tox -e py313 --notest` | `tox -e lint`, `tox -e py313` |
| nox | (per session) | `nox -s lint tests` |

Never install into the system interpreter. If there is no env at all, `uv venv && uv pip install -e '.[dev]'`
creates a throwaway one without touching project files.

## 4. Type checker invocations

| Checker | Touched modules only | Whole project at its config |
|---|---|---|
| mypy | `uv run mypy --strict src/pkg/mod_a.py src/pkg/mod_b.py` | `uv run mypy` (reads `[tool.mypy]`) |
| pyright | `uv run pyright src/pkg/mod_a.py` (strictness from config or `# pyright: strict` header) | `uv run pyright` |
| basedpyright | `uv run basedpyright src/pkg/mod_a.py` | `uv run basedpyright` (honours its baseline file) |
| pyrefly | `uv run pyrefly check src/pkg/mod_a.py` | `uv run pyrefly check` |

`mypy --strict` on a file list still follows imports; errors in imported, untouched modules are
reported too. Filter to your files (`| grep -E '^src/pkg/(mod_a|mod_b)\.py'`) and record the rest as
pre-existing, or use the project's baseline. Compare against the base commit before calling an error new.

## 5. Tests and coverage

```bash
uv run pytest -q                                   # project config decides paths, markers, warnings
uv run pytest -q -x --lf                           # iterate on the last failures
uv run pytest -q --cov=src/pkg --cov-report=term-missing:skip-covered   # pytest-cov, if installed
uv run pytest -q -p no:randomly tests/test_x.py::test_y                 # isolate an order-dependent failure
```

Do not lower `fail_under`, delete assertions or add `xfail` to get green; a failing pre-existing test
is reported under Open doubts with its output.

## 6. Dependency audit

```bash
req="$(mktemp)"
uv export --no-hashes --format requirements-txt -o "$req"    # the locked set, not the dev machine's env
uvx pip-audit -r "$req"
```

Poetry: `poetry export --without-hashes -f requirements.txt -o "$req"` (needs the export plugin on
Poetry 2). Report each finding with package, installed version, fixed version and whether the
vulnerable code path is reachable.

## 7. Minimal CI job (when the project has none and the brief asks for one)

```yaml
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy
      - run: uv run pytest -q
```

Pin action versions to what the repository already uses; hardening, caching and matrices are in
`ci-pipelines`.
