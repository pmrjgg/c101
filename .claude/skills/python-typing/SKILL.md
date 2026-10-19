---
name: python-typing
description: "Static typing for Python that catches real bugs: checker choice and strict config (mypy, pyright/basedpyright, Pyrefly 1.x, pre-1.0 ty), gradual adoption with baselines and ratchets, syntax through 3.15 (PEP 695/696, TypeIs, ReadOnly, override, deferred annotations), shape choice (dataclass, TypedDict, Protocol, pydantic), variance, overloads, ParamSpec, exhaustiveness, error fixes. Load when adding or fixing type hints or configuring a checker."
when_to_use: "Editing annotated .py/.pyi files, [tool.mypy]/[tool.pyright]/[tool.pyrefly] config or py.typed; errors such as union-attr, arg-type with 'list is invariant', no-untyped-def, import-untyped, override, no-any-return, reportOptionalMemberAccess; tasks: turn on strict mode, baseline and burn down type errors, type a decorator or overloaded API, review typed code."
---

# Python typing

Baseline (checked October 2026): mypy 2.4, pyright 1.1.41x and basedpyright, Pyrefly 1.4, ty 0.0.x;
code targets Python >= 3.12. Type-coverage metrics and ratchet mechanics in general are
`code-quality-metrics`; runtime validation in web services is `fastapi-pydantic-services`; the project
environment and tool installation are `python-uv-packaging`.

Deep material: [error code to fix table, extended](references/error-codes.md) |
[checker config templates and baselines](references/checker-configs.md)

## 1. Checker choice and configuration

| Checker | Strengths | Role |
|---|---|---|
| mypy 2.x | reference behaviour, plugins (pydantic, django-stubs), stable error codes, `-n auto` parallel workers (2.4) | default CI gate for existing codebases and plugin users |
| pyright | fast, thorough strict mode, `--verifytypes`, same engine as Pylance | CI gate for apps and libraries without mypy plugins |
| basedpyright | pyright fork with a native baseline file, `reportAny`, `recommended` and `all` modes | pyright users who need a baseline |
| Pyrefly 1.x | stable since May 2026, Rust-fast, good spec conformance, baseline, `pyrefly coverage`, `pyrefly init` migrates mypy/pyright config | gate for very large repos; editor |
| ty (Astral) | very fast, still 0.0.x (pre-1.0) | editor and advisory CI job, not the sole gate yet |

Rules: exactly **one gating checker**, version pinned in the dev group, run inside the project env
(`uv run mypy`, `uv run pyright`) so it sees installed packages and stubs. Editors may run a different
checker; CI decides. When checkers disagree, prefer code both accept over checker-specific ignores.

```toml
[tool.mypy]
files = ["src", "tests"]
python_version = "3.12"            # lowest supported version, not the dev machine's
strict = true                      # disallow-untyped-defs, warn-return-any, warn-unused-ignores, ...
warn_unreachable = true            # not part of strict; finds dead branches after bad narrowing
enable_error_code = ["ignore-without-code", "redundant-expr", "truthy-bool",
                     "possibly-undefined", "deprecated", "explicit-override"]
plugins = ["pydantic.mypy"]        # only when pydantic models are used

[[tool.mypy.overrides]]
module = ["legacy_vendor.*"]
ignore_missing_imports = true      # last resort for untyped deps (see import-untyped below)
```

mypy 2.0 changed defaults: `--local-partial-types` and `--strict-bytes` are on (`bytearray` and
`memoryview` no longer pass as `bytes`), `--allow-redefinition` now means the old
`--allow-redefinition-new`, and `--python-version 3.9` is rejected. Expect new errors on upgrade.

```toml
[tool.pyright]                     # or [tool.basedpyright] with typeCheckingMode = "recommended"
include = ["src", "tests"]
pythonVersion = "3.12"
typeCheckingMode = "strict"
```

## 2. Gradual adoption

1. **Annotate the public API first**: signatures of functions and classes imported by other modules.
   Every annotated boundary turns `Any` into checked types for all callers.
2. **Strict where new, lenient where old**: `strict = true` globally, then per-module relaxations for
   legacy packages, removed one package at a time:

```toml
[[tool.mypy.overrides]]
module = ["billing.legacy.*"]
disallow_untyped_defs = false
disallow_incomplete_defs = false
warn_return_any = false
```

3. **Baseline the rest** so CI fails only on new errors:

| Checker | Create / update baseline | CI check |
|---|---|---|
| mypy | `uv run mypy \| uv run mypy-baseline sync` (writes `mypy-baseline.txt`) | `uv run mypy \| uv run mypy-baseline filter` (also fails when a fixed error is still listed, so the file only shrinks) |
| basedpyright | `uv run basedpyright --writebaseline` | `uv run basedpyright` (baselined errors ignored) |
| Pyrefly | `pyrefly check --baseline=baseline.json --update-baseline` | `pyrefly check --baseline=baseline.json` |

4. **Every ignore carries a code and a reason**: `# type: ignore[union-attr]  # PAY-412: SDK returns
   None before capture`. `warn_unused_ignores` (in strict) flags stale ones; `ignore-without-code`
   rejects bare `# type: ignore`.
5. **Ratchet type coverage**: `uv run mypy --any-exprs-report reports` writes `reports/any-exprs.txt`
   with `Coverage = (Exprs - Anys) / Exprs` per module. Fail CI when the total drops below the floor
   and raise the floor after each burn-down PR:
   `awk '$1=="Total" {sub("%","",$4); exit (($4 + 0) < 97.0)}' reports/any-exprs.txt` (the `+ 0`
   matters: after `sub` the field compares as a string and "100.00" < "97.0").
   Pyrefly: `pyrefly coverage check`. Ratchet policy: `code-quality-metrics`.

## 3. Modern syntax by version

| Python | Feature | Example |
|---|---|---|
| 3.10 | `X \| None`, builtin generics (3.9); ParamSpec, Concatenate, TypeGuard, TypeAlias | `def f(x: int \| None) -> list[str]` |
| 3.11 | Self, LiteralString, Never, assert_never, reveal_type, Required/NotRequired, TypeVarTuple, dataclass_transform | `def clone(self) -> Self` |
| 3.12 | PEP 695 type parameters and `type` aliases; `@override` (PEP 698); `Unpack[TD]` for `**kwargs` (PEP 692) | `def first[T](xs: Sequence[T]) -> T`, `type Pair[T] = tuple[T, T]` |
| 3.13 | TypeVar defaults (PEP 696), TypeIs (PEP 742), ReadOnly TypedDict items (PEP 705), `warnings.deprecated` (PEP 702) | `class Box[T = int]: ...` |
| 3.14 | annotations evaluated lazily by default (PEP 649/749), `annotationlib` | forward references need no quotes |
| 3.15 | TypedDict `closed=` / `extra_items=` (PEP 728), `TypeForm` (PEP 747), `disjoint_base` (PEP 800) | checker support varies: verify yours |

- The names above are importable from `typing_extensions` (4.16 has `TypeIs`, `ReadOnly`, `TypeForm`,
  `disjoint_base`) on older runtimes; syntax is not: PEP 695/696 forms are a `SyntaxError` before
  3.12 / 3.13, so libraries supporting 3.11 keep `TypeVar` objects.
- PEP 695 classes infer variance; old-style `TypeVar` needs `covariant=True` spelled out.
- 3.14: `def f(x: Later) -> Later` works before `Later` is defined. Once `requires-python >= 3.14`,
  drop `from __future__ import annotations` and quoted forward references. Code that reads annotations
  at runtime uses `typing.get_type_hints()` or `annotationlib.get_annotations(obj,
  format=Format.FORWARDREF)`; plain `get_annotations(obj)` raises `NameError` for undefined names.
- `@override` on every overriding method plus `explicit-override` makes renames in the base class fail
  loudly instead of silently creating a new method.

## 4. Shape choice

| Need | Use | Notes |
|---|---|---|
| internal record | `@dataclass(frozen=True, slots=True)` | immutable, hashable, no `__dict__`; `kw_only=True` past ~4 fields |
| JSON-shaped dict passed through | `TypedDict` (+ `NotRequired`, `ReadOnly`) | zero runtime cost, still a plain dict, no validation |
| small interface the consumer needs | `Protocol` | structural; define it next to the consumer, 1-3 methods |
| tuple compatibility | `NamedTuple` | unpacking, legacy APIs returning tuples |
| closed set | `Enum` (behaviour, persistence) or `Literal["a", "b"]` (strings at edges) | both give exhaustiveness checks |
| distinct IDs of one base type | `NewType("UserId", int)` | zero cost; stops `order_id` passed as `user_id` |
| untrusted data (HTTP, queue, file, env) | pydantic v2 model or `TypeAdapter`, msgspec `Struct`, attrs + cattrs | runtime validation and coercion |

Rule: validate once at the trust boundary into one of the precise shapes above; inner code never
re-checks and never sees `dict[str, Any]`.

## 5. Generics and callables

```python
from collections.abc import Callable, Mapping, Sequence, Sized
from typing import Concatenate
import functools

def longest[T: Sized](a: T, b: T) -> T: ...                 # bound: T is any subtype of Sized
def concat[S: (str, bytes)](a: S, b: S) -> S: ...           # constraints: exactly str or exactly bytes
def total(prices: Sequence[float]) -> float: ...            # read-only param: covariant Sequence, not list
def index(rows: Mapping[str, int]) -> dict[str, int]: ...   # accept abstract, return concrete

def timed[**P, R](fn: Callable[P, R]) -> Callable[P, R]:    # signature-preserving decorator
    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return fn(*args, **kwargs)
    return wrapper

def with_conn[**P, R](fn: Callable[Concatenate[Conn, P], R]) -> Callable[P, R]:
    def inner(*args: P.args, **kwargs: P.kwargs) -> R:      # injects the first argument
        return fn(open_conn(), *args, **kwargs)              # Conn, open_conn: your DB layer
    return inner
```

- **Variance**: `list[Derived]` is not a `list[Base]` (the callee could append a `Base`). mypy says
  "list is invariant ... Consider using Sequence". Same for `dict` values -> `Mapping`.
- `Callable[..., Any]` switches checking off; for keyword arguments, defaults or overloads use a
  callback `Protocol` with `__call__`.
- **Overloads** when the return type depends on argument types; the undecorated implementation must
  accept the union of all overloads, and callers passing a union get the union of returns:

```python
@overload
def parse_amount(raw: str) -> Decimal: ...
@overload
def parse_amount(raw: None) -> None: ...
def parse_amount(raw: str | None) -> Decimal | None:
    return None if raw is None else Decimal(raw)
```

- `TypeVarTuple` (`def call_soon[*Ts](cb: Callable[[*Ts], object], *args: *Ts) -> None`) only for
  variadic forwarding or shape-typed arrays; both mypy and pyright reject `call_soon(cb, 1, 2)` when
  `cb` takes `(int, str)`.

## 6. Narrowing and exhaustiveness

| Construct | Narrows | Note |
|---|---|---|
| `if x is None: return` | `T \| None` -> `T` | prefer early return over nested `if x is not None` |
| `isinstance(x, (A, B))` | unions of classes | not for protocols unless `@runtime_checkable` (checks names only) |
| `if mode in ("r", "w")` on a `Literal` | `Literal["r","w"]` in the if-branch | pyright also narrows a plain `str`; mypy does not, nor the else-branch |
| user guard `-> TypeIs[T]` | both branches | `T` must be a subtype of the input type |
| user guard `-> TypeGuard[T]` | if-branch only | for non-subtype narrowing such as `list[object]` -> `list[str]` |
| `match` with class/literal patterns | per case | combine with `assert_never` |

```python
def next_action(status: PaymentStatus) -> str:
    match status:
        case PaymentStatus.PENDING:
            return "wait"
        case PaymentStatus.SUCCEEDED:
            return "fulfil"
        case PaymentStatus.FAILED:
            return "notify"
        case _:
            assert_never(status)   # adding REFUNDED makes this line a type error
```

mypy then reports `Argument 1 to "assert_never" has incompatible type
"Literal[PaymentStatus.REFUNDED]"; expected "Never"  [arg-type]`: the new member must be handled.

## 7. Error to fix (mypy codes, pyright rule in brackets)

| Code | Typical cause | Fix |
|---|---|---|
| `union-attr` [reportOptionalMemberAccess] | `find(x).upper()` with `str \| None` | narrow (`if s is None: raise/return`), never `assert` for user input |
| `arg-type` + "list is invariant" [reportArgumentType] | `list[Derived]` into `list[Base]` | parameter becomes `Sequence[Base]` |
| `return-value` [reportReturnType] | wrong branch type, missing `return None` | fix the logic or widen the declared return honestly |
| `no-untyped-def` [reportMissingParameterType] | unannotated function in strict code | annotate; `-> None` for procedures |
| `import-untyped` | package without `py.typed` or stubs | `uv add --dev types-<pkg>`; else local stubs (`stubgen`); last resort per-module `ignore_missing_imports` |
| `import-not-found` [reportMissingImports] | checker outside the project env | run via `uv run`; check `mypy_path` / `extraPaths` |
| `assignment` | one variable reused for two types | new name per meaning (pyright accepts it silently: declared type becomes the union) |
| `override` [reportIncompatibleMethodOverride] | subclass narrows a parameter or widens a return (Liskov) | accept the base type, or composition instead of inheritance |
| `typeddict-item` / `typeddict-unknown-key` | missing required key / extra key in a literal | `NotRequired[...]` for optional keys; separate TypedDict per payload version |
| [reportTypedDictNotRequiredAccess] | `payload["customer_id"]` on a `NotRequired` key (mypy is silent) | `payload.get("customer_id")` or `"customer_id" in payload` first |
| `no-any-return` | returning a value from `json.loads` or an untyped call | validate (`TypeAdapter(T).validate_python`) or annotate the local |
| `type-arg` | bare `list`, `dict` in annotations | `list[str]`, `dict[str, int]` |
| `unused-ignore` | ignore no longer needed | delete it (this is the ratchet working) |

Full table with more codes: [error-codes.md](references/error-codes.md).

## 8. Investigation tools

- `reveal_type(expr)` (all checkers; import it from `typing`, 3.11+, or Pyrefly reports
  `unimported-directive`) and `reveal_locals()` (mypy only, never imported): run the checker, read the
  note, delete the call.
- Import cycles caused by annotations: `if TYPE_CHECKING: from .orders import Order`, then use `Order`
  in annotations (no quotes needed on 3.14+).
- Untyped dependency: `uv run stubgen -p vendorlib -o stubs`, edit the generated `.pyi`, point
  `mypy_path = "stubs"` (pyright: `stubPath`) at it; upstream the stubs if they are good.
- Library completeness: `uv run pyright --verifytypes billing --ignoreexternal` prints
  "Type completeness score: N%" and every exported symbol with unknown types.
- Coverage by module: `mypy --any-exprs-report reports` (`types-of-anys.txt` says where the Any came from).

## 9. Runtime interplay

- Annotations are never enforced at runtime. Data from outside (JSON, env, DB rows without a typed
  driver) must be validated: `WEBHOOK = TypeAdapter(WebhookPayload)` at import time, then
  `WEBHOOK.validate_json(body)` per request (pydantic validates TypedDicts and dataclasses too).
- `cast(T, x)` asserts without checking: allowed only with a comment saying why it is true
  (`# cast: SDK stub says Any, docs guarantee str`); `redundant-cast` flags casts that became useless.
- Stop `Any` from leaking: strict already sets `disallow_any_generics` and `warn_return_any`; add
  `disallow_any_unimported` for modules wrapping untyped SDKs; basedpyright `reportAny` is stricter still.
- `typing.TYPE_CHECKING` blocks are invisible at runtime: never put code there that runtime needs.

## 10. Pitfalls

| Pitfall | Why it hurts | Fix |
|---|---|---|
| `x: str \| None = None` used as `str` in code the checker skips (untyped defs, `Any` flows, relaxed modules) | crashes on the default path; invisible until the module is strict | narrow at the top of the function; `def f(x: str = None)` is already an `[assignment]` error (implicit Optional is banned) |
| `list[...]` / `dict[...]` parameters where read-only was meant | callers with subclass lists get invariance errors | `Sequence`, `Mapping`, `Iterable` in parameters |
| `dict[str, Any]` everywhere | the checker verifies nothing downstream | TypedDict or dataclass at the boundary |
| `# type: ignore` without a code | hides future unrelated errors on the same line | `ignore-without-code` + `[code]` + reason |
| tests typed loosely or excluded from checking | the API misuse that tests exercise is never checked | include `tests` in `files`; annotate fixtures |
| `types-*` stubs drifting from the runtime version | checker approves calls that fail at runtime | pin stubs with the package (`types-requests` vs `requests`), upgrade together |
| `cast` / `Any` to silence an error | the bug moves, it does not disappear | fix the type; if impossible, a coded ignore with ticket |
| `TypeIs[list[str]]` on a `list[object]` input | rejected: narrowed type is not a subtype (invariance) | `TypeGuard`, or input `Sequence[object]` -> `TypeIs[Sequence[str]]` |
| checker run outside the venv | false `import-not-found`, missing stubs | `uv run mypy` |
| `ReadOnly` items in a TypedDict validated by pydantic | pydantic emits a `UserWarning` (no runtime protection); fails suites running with `-W error` | keep `ReadOnly` on internal TypedDicts; frozen dataclass after validation |
| different checker versions locally and in CI | "passes on my machine" | pin in the dev group, same command everywhere |

## 11. Worked example: bring `billing/` to strict

Start: 41 modules, mypy in default mode passes. After `strict = true` (section 1 config,
`files = ["src"]`), `uv run mypy` ends with **Found 312 errors in 23 files (checked 41 source files)**.

```bash
uv add --dev mypy mypy-baseline types-requests
uv run mypy | uv run mypy-baseline sync           # mypy-baseline.txt, 312 entries
git add pyproject.toml mypy-baseline.txt
# CI from now on (same command, same paths, so entries match):
uv run mypy | uv run mypy-baseline filter         # new errors fail; fixed ones must be synced
```

Burn-down order (each step one PR, baseline re-synced, count after the step):

| Step | Change | Errors left |
|---|---|---|
| 1 | annotate public API of `billing.api`, `billing.charges` (signatures only) | 188 |
| 2 | Optional narrowing: early returns for `str \| None` lookups | 97 |
| 3 | `WebhookPayload` TypedDict + `TypeAdapter` validation replaces `dict[str, Any]` | 41 |
| 4 | `PaymentGateway` Protocol replaces the untyped SDK client in signatures | 19 |
| 5 | overloads for `parse_amount`, `@override` on gateway fakes, `NewType` for `ChargeId` | 7 |
| 6 | `assert_never` on `PaymentStatus`, last coded ignores removed | 0 |

The core after step 6 (mypy `--strict` and pyright `strict` both report 0 errors):

```python
class PaymentStatus(Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

class WebhookPayload(TypedDict):
    id: str                                    # not ReadOnly: pydantic warns it cannot enforce it
    status: Literal["pending", "succeeded", "failed"]
    amount: str
    currency: str
    customer_id: NotRequired[str]

WEBHOOK = TypeAdapter(WebhookPayload)          # runtime validation at the trust boundary

@dataclass(frozen=True, slots=True)
class Charge:
    id: str
    amount: Decimal
    status: PaymentStatus

class PaymentGateway(Protocol):                # consumer-side, structural: fakes need no inheritance
    def capture(self, charge_id: str, amount: Decimal) -> bool: ...

def settle(body: bytes, gateway: PaymentGateway) -> Charge:
    payload = WEBHOOK.validate_json(body)      # bad status -> ValidationError, never a KeyError later
    charge = Charge(payload["id"], parse_amount(payload["amount"]), PaymentStatus(payload["status"]))
    if charge.status is PaymentStatus.SUCCEEDED and not gateway.capture(charge.id, charge.amount):
        raise RuntimeError(f"capture failed for {charge.id}")
    return charge
```

Bugs the burn-down found (the point of the exercise): a `None` customer id sent to the CRM on
refunds (step 2), `amount` summed as `str` in one report path (step 3), and a fake gateway whose
`capture` took `float` and hid a rounding issue in tests (step 4: passing it where a `PaymentGateway`
is expected became an `arg-type` error).

Close-out:

```bash
uv run mypy --any-exprs-report reports && tail -1 reports/any-exprs.txt   # Total ... 97.1%
uv run pyright --verifytypes billing --ignoreexternal | grep 'completeness score'
```

CI keeps `mypy-baseline filter` (now an empty baseline), adds the coverage floor of 97.0 from
section 2, and removes the `billing.legacy.*` override. Done when the baseline is empty, every
remaining ignore has a code and a ticket, and the coverage gate is enforced.

Related: `python-uv-packaging`, `python-asyncio`, `pytest-patterns`, `fastapi-pydantic-services`,
`python-performance-profiling`, `code-quality-metrics`, `code-review-checklist`, `refactoring-playbook`;
hub `coding-general`.
