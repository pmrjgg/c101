# PyO3 and maturin in depth

Checked against PyO3 0.30.1 (October 2026), maturin 1.15, CPython 3.10-3.15 and 3.14t.

## 1. PyO3 API changes you will meet in older code

| Release | Change | Action |
|---|---|---|
| 0.21 | `Bound<'py, T>` API introduced; GIL Refs (`&'py PyAny`) deprecated | port signatures to `&Bound<'py, PyAny>` |
| 0.23 | GIL Refs removed; `IntoPyObject` replaces `IntoPy`/`ToPyObject`; `Vec<u8>`/`&[u8]` convert to `bytes`; `#[pyclass]` must be `Sync`; free-threaded 3.13t support (`gil_used = false`) | add `Mutex`/atomics or `#[pyclass(frozen)]` |
| 0.26 | `Python::with_gil` -> `Python::attach`, `allow_threads` -> `detach`, `prepare_freethreaded_python` -> `Python::initialize`; `PyObject` deprecated (use `Py<PyAny>`); `GILOnceCell` -> `PyOnceLock`; `GILProtected` deprecated (`Mutex` + `MutexExt::lock_py_attached`) | rename; review init races (`PyOnceLock` may deadlock where racy init worked) |
| 0.27 | `FromPyObject` gains a lifetime and `Error` type; `extract_bound` -> `extract`; `.downcast()` -> `.cast()`, `DowncastError` -> `CastError` | update custom `FromPyObject` impls |
| 0.28 | free-threading is opt-out: `#[pymodule(gil_used = true)]` to keep the GIL; multi-phase module init (PEP 489); MSRV 1.83 | audit unsafe code before claiming thread safety |
| 0.29 | drops CPython 3.7 and 3.13t (free-threaded support from 3.14t); `abi3t`/`abi3t-py315` features (PEP 803); Windows uses `raw-dylib` linking; `From<Utf8Error> for PyErr` removed | use `PyUnicodeDecodeError::new_err_from_utf8` |
| 0.30 | drops CPython 3.8 (lowest abi3 feature `abi3-py39`); MSRV 1.85; `#[pyclass]` no longer derives `FromPyObject` for `Clone` types; `PyMutex` moved to `pyo3::sync`; meson-python supported | add `#[pyclass(from_py_object)]` where you relied on the old behaviour |

Feature flags in 0.30: `abi3`, `abi3-py39` ... `abi3-py315`, `abi3t`, `abi3t-py315`,
`auto-initialize` (embedding: `Python::attach` initialises the interpreter),
`experimental-async` (`async fn` in `#[pyfunction]`/`#[pymethods]`),
`experimental-inspect` (introspection data for stub generation with `pyo3-introspection`),
`multiple-pymethods`. `extension-module` and `generate-import-lib` are deprecated no-ops.

## 2. Project files

```toml
# Cargo.toml (crate foo-py)
[lib]
name = "foo_py"                  # == #[pymodule] name == [tool.maturin] module-name
crate-type = ["cdylib"]          # add "rlib" only if Rust tests need to link it

[dependencies]
pyo3 = { version = "0.30", features = ["abi3-py39"] }
```

```toml
# pyproject.toml
[build-system]
requires = ["maturin>=1.9.4,<2"]
build-backend = "maturin"

[project]
name = "foo-py"
requires-python = ">=3.9"
classifiers = ["Programming Language :: Rust", "Programming Language :: Python :: Implementation :: CPython"]
dynamic = ["version"]            # version taken from Cargo.toml

[tool.maturin]
module-name = "foo_py"
# python-source = "python"      # mixed Rust/Python layout: python/foo_py/__init__.py + .pyi + py.typed
```

Layouts:
- Pure Rust: `foo_py.pyi` next to `Cargo.toml`; maturin adds `py.typed` automatically.
- Mixed: Rust module as `foo_py._native` (`module-name = "foo_py._native"`), Python package in
  `python/foo_py/` with its own `__init__.py`, `.pyi` files and an empty `py.typed`.

Stub for the worked example:

```python
# foo_py.pyi
class FooError(Exception): ...
class Checksummer:
    def __init__(self, level: int = 0) -> None: ...
    def checksum(self, data: bytes) -> int: ...
```

## 3. Local loop

```bash
uv venv --python 3.13 && source .venv/bin/activate
uv pip install maturin pytest
maturin develop --release --uv          # --release matters for benchmarks; debug for fast iteration
pytest -q
maturin build --release --out dist -i python3.14t   # extra free-threaded wheel
```

`maturin develop` installs into the active virtualenv only. Editable mixed projects rebuild
the Rust part on `maturin develop`; Python files are picked up live.

## 4. Free-threaded CPython

- PyO3 >= 0.28 marks modules as supporting free-threading unless `#[pymodule(gil_used = true)]`.
  With `gil_used = true` the interpreter re-enables the GIL on import and prints a
  `RuntimeWarning` naming the module.
- abi3 is ignored for free-threaded builds (PyO3 warns); publish a version-specific `cp314t`
  wheel next to the abi3 wheel. `abi3t` (PEP 803) only covers 3.15+.
- `#[pyclass]` data is shared between real threads: use `#[pyclass(frozen)]` with `Mutex`,
  `RwLock` or atomics; a mutable pyclass raises `RuntimeError: Already borrowed` on overlap.
- Holding a Rust lock while calling back into Python can deadlock with other attached threads:
  use `MutexExt::lock_py_attached` or release the lock before touching Python objects.
- Verify: `python3.14t -c "import foo_py, sys; print(sys._is_gil_enabled())"` must print `False`.

## 5. CI (GitHub Actions)

Start from `maturin generate-ci github > .github/workflows/CI.yml`, then keep this shape
(action majors current as of October 2026):

```yaml
jobs:
  linux:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        target: [x86_64, aarch64]
        manylinux: [auto, musllinux_1_2]
    steps:
      - uses: actions/checkout@v7
      - uses: PyO3/maturin-action@v1
        with:
          target: ${{ matrix.target }}
          manylinux: ${{ matrix.manylinux }}
          args: --release --out dist
          sccache: true
      - uses: actions/upload-artifact@v7
        with: { name: "wheels-linux-${{ matrix.target }}-${{ matrix.manylinux }}", path: dist }
  macos:
    runs-on: macos-latest
    strategy: { matrix: { target: [x86_64, aarch64] } }
    steps:
      - uses: actions/checkout@v7
      - uses: PyO3/maturin-action@v1
        with: { target: "${{ matrix.target }}", args: --release --out dist }
      - uses: actions/upload-artifact@v7
        with: { name: "wheels-macos-${{ matrix.target }}", path: dist }
  test:
    needs: [linux]
    runs-on: ubuntu-latest
    strategy: { matrix: { python: ["3.9", "3.13", "3.14t"] } }
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
        with: { python-version: "${{ matrix.python }}" }
      - run: |
          uv venv && uv pip install maturin pytest
          . .venv/bin/activate
          maturin develop --release --uv && pytest -q
  publish:
    needs: [linux, macos, test]
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-latest
    environment: pypi
    permissions: { id-token: write }          # PyPI trusted publishing, no API token
    steps:
      - uses: actions/download-artifact@v8
        with: { pattern: "wheels-*", merge-multiple: true, path: dist }
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Add a Windows job and an sdist job (`command: sdist`) the same way. Check Linux wheels with
`auditwheel show dist/*.whl`; manylinux tags guarantee the glibc floor, musllinux covers Alpine.

## 6. Testing patterns

```python
# tests/test_foo.py
import threading, pytest, foo_py

def fnv1a(data: bytes, level: int = 0) -> int:
    h = 2166136261 ^ level
    for b in data:
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h

def test_matches_reference():
    assert foo_py.Checksummer().checksum(b"hello") == fnv1a(b"hello")

def test_error_type():
    with pytest.raises(foo_py.FooError, match="invalid argument"):
        foo_py.Checksummer(10)

def test_threads_share_one_object():
    c, out = foo_py.Checksummer(), []
    def work():
        for _ in range(2000):
            out.append(c.checksum(b"hello" * 100))
    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(out) == 16000 and len(set(out)) == 1
```

Rust-side unit tests belong in the safe `foo` crate (no Python needed). Tests inside the
`cdylib` crate that call into Python need `auto-initialize` and an interpreter at test time.

## 7. Errors and fixes

| Error | Fix |
|---|---|
| `ImportError: dynamic module does not define module export function (PyInit_foo)` | names disagree: `[lib] name`, `#[pymodule]`, `module-name` |
| `Undefined symbols for architecture arm64: "_Py..."` | building the extension with plain cargo; use maturin (sets `PYO3_BUILD_EXTENSION_MODULE` and link args) |
| `the trait Sync is not implemented` on a `#[pyclass]` | wrap state in `Mutex`/atomics, or `#[pyclass(unsendable)]` for single-threaded apps only |
| closure passed to `detach` is not `Ungil`/`Send` | do not capture `Python<'py>`, `Bound`, `Rc` or non-`Sync` references; extract plain Rust data first |
| `PanicException` in Python | a Rust panic crossed into Python; return `PyResult` errors instead |
| wheel rejected by PyPI with a `linux_x86_64` tag | build inside the manylinux container (maturin-action) |
