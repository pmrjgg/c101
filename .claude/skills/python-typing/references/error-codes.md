# Error code to fix table (extended)

Companion to `python-typing` section 7. Codes and rule names were produced by mypy 2.4 (`--strict`,
`--warn-unreachable` and the optional codes listed) and pyright 1.1.41x (`strict`) on sample files.
mypy code goes in `# type: ignore[code]`; pyright rule goes in `# pyright: ignore[rule]`.

## Optional, None and narrowing

| mypy code | pyright rule | Message shape | Fix |
|---|---|---|---|
| `union-attr` | reportOptionalMemberAccess | Item "None" of "str \| None" has no attribute "upper" | early return / raise on None; `if (u := find(x)) is None: ...` |
| `arg-type` | reportArgumentType | Argument 1 to "len" has incompatible type "str \| None" | narrow before the call |
| `return-value` | reportReturnType | Incompatible return value type (got "str \| None", expected "str") | narrow, or return type `str \| None` and make callers handle it |
| `possibly-undefined` (optional) | reportPossiblyUnboundVariable | Name "y" may be undefined | assign in every branch or before the `if` |
| `unreachable` (`warn_unreachable`) | (none) | Statement is unreachable | usually a wrong annotation upstream (e.g. param typed `int`, code checks `is None`) |
| `truthy-bool` / `truthy-function` | reportUnnecessaryComparison | Function "main" could always be true in boolean context | call it, or compare explicitly (`if x is not None`) |
| `redundant-expr` (optional) | reportUnnecessaryComparison | Left operand of "and" is always true | remove the dead check or fix the type |
| `comparison-overlap` (strict) | reportUnnecessaryComparison | Non-overlapping equality check (int vs Literal['a']) | real bug: comparing different types |

## Calls and signatures

| mypy code | pyright rule | Message shape | Fix |
|---|---|---|---|
| `call-arg` | reportCallIssue | Too many arguments / Unexpected keyword argument | fix the call; for wrappers use `ParamSpec` |
| `call-overload` | reportCallIssue | No overload variant of "f" matches argument types | add the missing overload or convert the argument |
| `arg-type` (+ "list is invariant") | reportArgumentType | expected "list[Base]" | `Sequence[Base]` / `Mapping[K, Base]` parameter |
| `no-untyped-def` | reportMissingParameterType, reportUnknownParameterType | Function is missing a type annotation | annotate (`-> None` for procedures) |
| `no-untyped-call` | reportUnknownVariableType (at use) | Call to untyped function "legacy" in typed context | annotate the callee or wrap it in a typed facade |
| `untyped-decorator` | reportUntypedFunctionDecorator | Untyped decorator makes function "decorated" untyped | type the decorator with `ParamSpec` (section 5 of the skill) |
| `func-returns-value` | (none) | "noret" does not return a value | do not use the result of a `-> None` function |
| `empty-body` | reportReturnType | Missing return statement (body is `...`) | implement, or mark `@abstractmethod`, or put the method in a `Protocol` |
| `return` | reportReturnType | Missing return statement | add the final `return` or `raise` |
| `override` | reportIncompatibleMethodOverride | Argument 1 of "f" is incompatible with supertype "A" | keep the base signature (Liskov), widen params / narrow returns only |
| `explicit-override` (optional) | reportImplicitOverride (basedpyright and pyright, off by default) | Method "f" is not using @override | add `@override` |
| `abstract` | reportAbstractUsage | Cannot instantiate abstract class "Shape" | instantiate a concrete subclass |

## Attributes, names, operators

| mypy code | pyright rule | Message shape | Fix |
|---|---|---|---|
| `attr-defined` | reportAttributeAccessIssue | "str" has no attribute "nope" | typo, or wrong type upstream; for dynamic attrs declare them on the class |
| `name-defined` | reportUndefinedVariable | Name "x" is not defined | import it; under `TYPE_CHECKING` for annotation-only use |
| `operator` | reportOperatorIssue | Unsupported operand types for + ("int" and "str") | convert explicitly |
| `index` / `call-overload` on `__getitem__` | reportIndexIssue, reportCallIssue | Invalid index type | narrow the key type |
| `no-redef` | reportRedeclaration | Name "k" already defined | rename; for real overloads use `@overload` |
| `misc` | varies | catch-all | read the message; prefer fixing over ignoring because `misc` ignores hide a lot |

## Variables and containers

| mypy code | pyright rule | Message shape | Fix |
|---|---|---|---|
| `var-annotated` | reportUnknownVariableType (later) | Need type annotation for "items" | `items: list[Order] = []` |
| `assignment` | reportAssignmentType (declared variables only) | Incompatible types in assignment | new variable name per meaning |
| `list-item` / `dict-item` | reportAssignmentType | List item 1 has incompatible type | fix the literal or widen the declared element type |
| `type-arg` | reportMissingTypeArgument | Missing type arguments for generic type "list" | `list[str]` |
| `no-any-return` | reportUnknownVariableType / basedpyright reportAny | Returning Any from function declared to return "int" | validate or annotate the intermediate value |
| `typeddict-item` | reportReturnType / reportAssignmentType | Missing key "amount" for TypedDict | add key or mark `NotRequired` |
| `typeddict-unknown-key` | reportAssignmentType | Extra key "extra" for TypedDict | remove key, or 3.15 `extra_items=` / separate TypedDict |
| `typeddict-readonly-mutated` | reportTypedDictNotRequiredAccess / "Could not assign item" | ReadOnly TypedDict key "id" is mutated | build a new dict instead of mutating |
| (none in mypy) | reportTypedDictNotRequiredAccess | Could not access item in TypedDict | `.get(key)` or `key in d` before indexing |
| `narrowed-type-not-subtype` | reportGeneralTypeIssues | Narrowed type "list[str]" is not a subtype of input type "list[object]" | `TypeGuard` instead of `TypeIs`, or covariant input type |

## Imports and stubs

| mypy code | pyright rule | Message shape | Fix |
|---|---|---|---|
| `import-untyped` | reportMissingTypeStubs | Library stubs not installed for "yaml" | `uv add --dev types-PyYAML`; the hint names the stub package |
| `import-not-found` | reportMissingImports | Cannot find implementation or library stub | checker not running in the project env; missing dependency |
| (none) | reportMissingModuleSource | Import could be resolved from stubs but not source | runtime package missing in the env; install it |
| `attr-defined` on a module | reportPrivateImportUsage | Module "pkg" does not explicitly export attribute | import from the defining module, or the library adds `__all__` |

mypy 2.0 removed the bundled special-casing of legacy stub packages, so `ignore_missing_imports`
now applies uniformly to every package; scope it with `[[tool.mypy.overrides]] module = [...]`.

## Async

| mypy code | pyright rule | Message shape | Fix |
|---|---|---|---|
| `unused-coroutine` (default on) | reportUnusedCoroutine | Value of type "Coroutine[Any, Any, int]" must be used | add `await` (see `python-asyncio`) |
| `unused-awaitable` (optional) | (none; ruff RUF006 covers `create_task`) | Value of type "Task[int]" must be used | keep a reference or use a TaskGroup |

## Housekeeping codes

| mypy code | Meaning | Action |
|---|---|---|
| `unused-ignore` | a `# type: ignore` no longer suppresses anything | delete it |
| `ignore-without-code` (optional) | bare `# type: ignore` | add the code in brackets |
| `redundant-cast` | `cast` to the type the value already has | delete the cast |
| `deprecated` (optional) | call to a `@deprecated` function or overload | migrate to the replacement named in the message |
