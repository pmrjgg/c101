# pytest command cheat-sheet

Checked against pytest 9.1, pytest-xdist 3.8, pytest-randomly 5.0, pytest-split 0.11,
pytest-repeat 0.9, pytest-cov 7.1, pytest-timeout 2.4, syrupy 6.1 and inline-snapshot 0.36. Always
run through the project environment (`uv run pytest ...`). Plugin flags exist only when the plugin is
installed.

## Selecting

```bash
pytest -q -x                                    # quiet, stop at first failure
pytest tests/test_a.py::test_b -vv              # one test, full diff
pytest "tests/test_a.py::test_parse[compound]"  # one parametrized case by id (quote the brackets)
pytest -k "parse and not slow"                  # name expression
pytest -m "not integration and not slow"        # marker expression (markers must be registered)
pytest --lf                                     # last-failed only
pytest --lf --lfnf=none                         # ...and run nothing if nothing failed last time
pytest --ff                                     # failures first, then the rest
pytest --sw                                     # stepwise: stop at a failure, resume from it next run
pytest --collect-only -q                        # list test ids without running (alias: --co)
pytest --deselect tests/test_a.py::test_flaky   # skip one id without editing code
```

## Output and debugging

```bash
pytest -ra                                      # summary reasons for skips, xfails, errors
pytest -vv --showlocals --tb=long               # maximal failure context (-l == --showlocals)
pytest --tb=short | --tb=line | --tb=no         # less traceback noise
pytest -s                                       # no capture (prints and breakpoints work)
pytest -x --pdb                                 # post-mortem debugger on first failure (disables xdist)
pytest --trace tests/test_a.py::test_b          # break at the start of the test
pytest --pdbcls=IPython.terminal.debugger:TerminalPdb --pdb
PYTHONBREAKPOINT=0 pytest                       # make stray breakpoint() calls no-ops
pytest -o log_cli=true --log-cli-level=DEBUG    # live logging
pytest -W error::ResourceWarning                # one-off warnings-as-errors
pytest --setup-show -k test_b                   # fixture setup/teardown order with scopes
pytest --fixtures-per-test tests/test_a.py      # which fixtures each test uses, and from where
pytest --trace-config --co -q                   # loaded conftests and plugins
pytest --timeout=60 --timeout-method=thread     # pytest-timeout: dump stacks of hung tests
```

## Speed and isolation

```bash
pytest --durations=20 --durations-min=0.5       # slowest setup/call/teardown phases
pytest -n auto                                  # pytest-xdist, physical cores
pytest -n logical                               # logical cores (needs psutil)
pytest -n 8 --dist loadgroup                    # honour @pytest.mark.xdist_group(name=...)
pytest -n 8 --dist loadscope                    # keep modules/classes together
pytest -n 8 --dist worksteal                    # rebalance uneven durations
pytest -n 8 --maxprocesses=4                    # cap auto/logical
pytest -p randomly                              # shuffle (prints "Using --randomly-seed=N")
pytest --randomly-seed=1234                     # replay an order
pytest --randomly-seed=last                     # replay the previous run's seed
pytest -p no:randomly                           # disable shuffling
pytest --randomly-dont-reorganize               # keep order, still reseed random/Faker/numpy
pytest --count=200 -x tests/test_a.py::test_b   # pytest-repeat: hammer one test
pytest --store-durations                        # pytest-split: write .test_durations
pytest --splits 4 --group 1                     # pytest-split: shard 1 of 4 (1-based)
pytest --splits 4 --group 1 --splitting-algorithm least_duration
```

Finding the test that pollutes another (installed separately):

```bash
detect-test-pollution --failing-test tests/test_x.py::test_y --tests tests/
detect-test-pollution --fuzz --tests tests/     # shuffle repeatedly until something fails
```

## Coverage

```bash
pytest --cov=mypkg --cov-branch --cov-report=term-missing --cov-report=xml
pytest --cov=mypkg --cov-fail-under=85
coverage run --branch -m pytest && coverage report -m
diff-cover coverage.xml --compare-branch=origin/main --fail-under=80   # coverage of changed lines
```

Interpreting coverage numbers is covered in `testing-strategy`, not here.

## Snapshots

```bash
pytest --snapshot-update                        # syrupy: rewrite changed snapshots, delete unused
pytest --snapshot-update --snapshot-no-cleanup  # ...but keep unused ones (partial runs)
pytest --snapshot-warn-unused                   # do not fail on unused snapshots
pytest --inline-snapshot=create                 # inline-snapshot: fill empty snapshot() calls
pytest --inline-snapshot=fix                    # rewrite snapshots that currently fail
pytest --inline-snapshot=review                 # approve each change interactively
```

## Async

```bash
pytest --asyncio-mode=auto                      # one-off; prefer asyncio_mode in config
pytest --asyncio-debug                          # asyncio debug mode: slow callbacks, never-awaited coroutines
```

## Configuration keys worth knowing (pytest 9)

| Key | Type | Effect |
|---|---|---|
| `addopts` | list | default CLI options |
| `testpaths` | list | where to collect when no path is given |
| `strict` | bool | 9.0+: strict_config, strict_markers, strict_xfail, strict_parametrization_ids |
| `strict_xfail` / `xfail_strict` | bool | XPASS fails the run |
| `strict_parametrization_ids` | bool | duplicate parametrize ids are errors |
| `filterwarnings` | list | `"error"` first, then explicit ignores |
| `max_warnings` | string | 9.1+: fail a passing run that has too many warnings |
| `markers` | list | registered markers with descriptions |
| `minversion` | string | refuse to run on an older pytest |
| `required_plugins` | list | refuse to run without e.g. `pytest-xdist>=3` |
| `pythonpath` | list | sys.path additions (unpackaged apps only) |
| `norecursedirs` | list | directories never searched |
| `tmp_path_retention_policy` | string | `all`, `failed` or `none` |
| `faulthandler_timeout` | string | dump all thread stacks when a test exceeds N seconds |
| `log_cli`, `log_cli_level` | bool, string | live logging |
| `asyncio_mode` | string | `auto` or `strict` (pytest-asyncio) |
| `asyncio_default_fixture_loop_scope` | string | loop scope for async fixtures |
| `asyncio_default_test_loop_scope` | string | loop scope for async tests |
