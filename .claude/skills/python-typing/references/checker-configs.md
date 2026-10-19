# Checker configuration templates and baseline workflows

Companion to `python-typing` sections 1 and 2. All commands run inside the project environment
(`uv run ...`); pin the checker in the dev group (`uv add --dev mypy==<version>` or a lower bound plus
the lock). Config keys below were loaded by mypy 2.4, pyright 1.1.41x, basedpyright and Pyrefly 1.4.

## mypy (application or library)

```toml
[tool.mypy]
files = ["src", "tests"]
python_version = "3.12"
strict = true
warn_unreachable = true
enable_error_code = [
  "ignore-without-code",   # bare "# type: ignore" is an error
  "redundant-expr",        # always-true/false sub-expressions
  "truthy-bool",           # objects without __bool__ used in boolean context
  "possibly-undefined",    # variables bound in only some branches
  "deprecated",            # calls to @deprecated APIs
  "explicit-override",     # overriding methods must use @override
  "unused-awaitable",      # async code: unused Task/Future values
]
plugins = ["pydantic.mypy"]          # if pydantic models are used
mypy_path = "stubs"                  # local .pyi for untyped vendors (stubgen output, edited)

[tool.pydantic-mypy]                 # pydantic plugin options
init_forbid_extra = true
init_typed = true

[[tool.mypy.overrides]]
module = ["billing.legacy.*"]        # relaxed island, shrinks over time
disallow_untyped_defs = false
disallow_incomplete_defs = false
warn_return_any = false

[[tool.mypy.overrides]]
module = ["vendor_sdk.*"]            # untyped third party with no stubs available
ignore_missing_imports = true
```

Useful flags: `-n auto` (parallel workers, mypy 2.4), `--any-exprs-report DIR`, `--html-report DIR`
(needs lxml), `--warn-unused-configs` (not part of strict; flags override sections that match no
module),
`--no-native-parser` (2.4 fallback to the legacy parser if the new default parser misbehaves).

mypy 2.0 upgrade checklist:

| Change | Typical new errors | Action |
|---|---|---|
| `--local-partial-types` default on | `Need type annotation` for variables initialised to `None`/`[]` at module or class level and filled elsewhere | annotate the variable at its definition |
| `--strict-bytes` default on | `bytearray` / `memoryview` passed where `bytes` is declared | widen to `bytes \| bytearray \| memoryview` or `collections.abc.Buffer` |
| `--allow-redefinition` semantics changed | different redefinition errors if you used the flag | review; `--allow-redefinition-old` restores the old behaviour temporarily |
| `--python-version 3.9` rejected | config error | target 3.10 or newer |

## pyright / basedpyright

```toml
[tool.pyright]
include = ["src", "tests"]
exclude = ["**/__pycache__", "build", "dist"]
pythonVersion = "3.12"
typeCheckingMode = "strict"
reportMissingTypeStubs = "warning"        # untyped deps: warn, do not block
reportImplicitOverride = "error"          # same intent as mypy explicit-override
reportUnnecessaryTypeIgnoreComment = "error"
stubPath = "stubs"
```

basedpyright accepts the same keys under `[tool.basedpyright]`, adds `typeCheckingMode =
"recommended"` (strict plus extra rules such as `reportAny` as warnings) and `"all"`, and supports a
native baseline:

```bash
uv run basedpyright --writebaseline      # writes .basedpyright/baseline.json; commit it
uv run basedpyright                      # later runs report only errors not in the baseline
```

Library completeness:

```bash
uv run pyright --verifytypes billing --ignoreexternal     # "Type completeness score: 100%"
uv run pyright --verifytypes billing --outputjson > reports/verifytypes.json
```

## Pyrefly 1.x

```toml
[tool.pyrefly]
project-includes = ["src", "tests"]
python-version = "3.12"
```

```bash
uvx pyrefly init                              # migrate an existing mypy/pyright config
uv run pyrefly check                          # project mode, reads [tool.pyrefly]
uv run pyrefly check --baseline=baseline.json --update-baseline   # create/refresh baseline
uv run pyrefly check --baseline=baseline.json                     # CI: only new errors fail
uv run pyrefly check --baseline=baseline.json --error-stale-baseline   # also fail on fixed-but-listed
uv run pyrefly suppress                       # add ignore comments for current errors (one-shot)
uv run pyrefly coverage check                 # type coverage threshold (see --help for options)
```

Pyrefly's defaults are more permissive than mypy `--strict` about implicit `Any`; check its config
reference for the error kinds you want raised to `error` before making it the gate.

## ty (pre-1.0)

```bash
uvx ty check src          # fast advisory pass; config under [tool.ty]
```

Treat its findings as hints until it reaches 1.0: rules and defaults still change between releases.

## Baseline workflow with mypy-baseline

```bash
uv add --dev mypy-baseline
uv run mypy | uv run mypy-baseline sync           # writes mypy-baseline.txt (line numbers stripped)
uv run mypy | uv run mypy-baseline filter         # CI: exit 1 on new errors, or on fixed errors still listed
uv run mypy-baseline top-files                    # where to burn down next
uv run mypy-baseline history                      # how the baseline changed over time
```

Rules: the baseline only shrinks; each PR that fixes errors runs `sync` and commits the smaller file;
new code never lands in the baseline (review rejects baseline growth unless a checker upgrade caused it,
in which case the upgrade PR re-syncs and says so).

## CI gate (GitHub Actions step list)

```yaml
- run: uv sync --locked --dev
- run: uv run mypy | uv run mypy-baseline filter
- run: uv run mypy --any-exprs-report reports
- run: awk '$1=="Total" {sub("%","",$4); exit (($4 + 0) < 97.0)}' reports/any-exprs.txt
- run: uv run pyright --verifytypes billing --ignoreexternal   # libraries only
```

## Stubs for untyped dependencies

| Situation | Action |
|---|---|
| typeshed has stubs (`types-requests`, `types-PyYAML`) | `uv add --dev types-<name>`, pin alongside the runtime package |
| package ships inline types but no `py.typed` | ask upstream to add `py.typed`; meanwhile `stubgen` or per-module ignore |
| no stubs anywhere | `uv run stubgen -p vendorlib -o stubs` (add `--include-docstrings` if useful), trim to the API you use, set `mypy_path` / `stubPath` |
| stubs exist but lag the runtime | pin both versions together; add a test exercising the drifted API |
