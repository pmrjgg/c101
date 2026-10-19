# Extended refactoring catalogue

Mechanics for refactorings beyond the six in `SKILL.md` section 4. Same rule: run the tests (or at
least the compiler/type checker) after every numbered step; commit when green.

## Replace Conditional with Polymorphism

Use when the same type switch appears in two or more places.
1. Create a base type (abstract class / interface / trait / protocol) with one method per switch.
2. Create one subtype per case; move each branch body into the matching subtype method.
3. Add a factory that maps the old type tag to the subtype (the only remaining switch).
4. Replace each switch with a call through the base type, one switch per commit.
5. Delete the type tag field if nothing else reads it.

Table-driven alternative (preferred when cases differ only in data): `RATES = {(kind, country): rate}`
or `HANDLERS = {"csv": parse_csv, "json": parse_json}`; unknown keys must raise or fall back
exactly as the old `else` branch did.

## Introduce Parameter Object

1. Create an immutable record (`@dataclass(frozen=True)`, Java `record`, Kotlin `data class`, Rust struct, TS `interface` + `readonly`) with the clumped parameters.
2. Add a new function taking the record; the old function builds the record and delegates.
3. Migrate callers; move behaviour that only uses those fields onto the record (it often attracts methods).
4. Remove the old signature (or keep it deprecated in a library).

## Extract Class

1. Pick the field group and the methods that use only that group (LCOM4 components show them).
2. Create the new class; give the old class a field holding an instance.
3. Move fields one at a time (Encapsulate Field first if accessed directly), then methods.
4. Decide exposure: does the old class's API keep delegating methods, or do callers use the new class directly?

## Inline Class

Reverse of Extract Class, for a class that no longer earns its keep: move its members into the
single user, then delete it.

## Encapsulate Variable / Field

1. Add getter/setter (or property) around the variable.
2. Replace all direct accesses with the accessors (LSP "find references").
3. Restrict visibility of the variable.
4. Now changes (validation, lazy computation, change of representation) happen in one place.

## Replace Primitive with Object (value type)

1. Create the value type with validation in the constructor (`Money(amount: Decimal, currency: str)`, `EmailAddress`, `TenantId(NewType)`).
2. Change the field type; convert at the boundaries (parsing input, serialization output).
3. Move operations on the primitive (formatting, comparisons, arithmetic) onto the type.
4. Python `NewType` is zero-cost but does not validate; use a frozen dataclass when validation matters. TS branded types: `type UserId = string & { readonly __brand: "UserId" }`.

## Replace Temp with Query

1. Check the temp is assigned once and its expression has no side effects.
2. Extract the expression into a function (or property).
3. Replace references to the temp with the call; remove the temp.
Skip in hot loops when the expression is expensive and the compiler will not hoist it.

## Decompose Conditional / Consolidate Conditional Expression

- Decompose: extract the condition and each branch into named functions (`if is_summer(date): charge = summer_charge(qty)`).
- Consolidate: several conditions with the same result become one named predicate (`if is_ineligible(emp): return 0`).

## Replace Nested Conditional with Guard Clauses

1. Find conditions that end the function early (invalid input, special cases).
2. Turn each into `if cond: return/raise` at the top.
3. Unindent the main path. Check that cleanup still runs (use `with`, `try/finally`, `defer`, RAII).

## Split Loop

One loop computing two things becomes two loops. Do it before extracting either computation;
measure only if the loop is hot (two passes over a large list in a hot path).

## Replace Loop with Pipeline

`for` + `if` + `append` becomes `filter`/`map`/comprehension/iterator chain. Keep it readable:
more than ~3 chained stages or nested lambdas is worse than the loop.

## Pull Up / Push Down Method or Field

- Pull up: identical methods in sibling subclasses move to the parent (check they are truly identical, including overrides they call).
- Push down: parent behaviour used by only one subclass moves into it.

## Replace Inheritance with Delegation

1. Add a field in the subclass holding an instance of the former parent.
2. For each parent method the subclass's users need, add a delegating method.
3. Remove the inheritance. Breaks `isinstance` checks and Liskov-based callers: search for them first.

## Remove Dead Code

1. Prove it is dead: coverage over production-like traffic, `vulture` (Python), `staticcheck` U1000 (Go), `ts-prune`/`knip` (TS), compiler warnings (Rust/Java), plus dynamic uses (reflection, routes, plugins, config).
2. Delete in its own commit; git keeps it if needed.

## Slide Statements

Move related statements next to each other before extracting them. Only across statements with
no data dependency or side-effect ordering between them.

## Substitute Algorithm

Replace an implementation wholesale with a clearer one. Requires the strongest oracle: golden
master plus differential testing on generated inputs (property-based with the old function as the
reference implementation).

## Smell detection commands

| Smell | Command |
|---|---|
| long / complex functions | `lizard -C 15 -L 60 -w src/` |
| cognitive complexity | `complexipy src/` (Python), ESLint `sonarjs/cognitive-complexity`, `gocognit -over 15 .` |
| duplication | `jscpd --min-lines 6 src/` |
| long parameter lists | `lizard -a 5 -w src/` (argument count threshold) |
| cohesion (LCOM4) | per `code-quality-metrics` section 4 |
| dead code | `vulture src/ --min-confidence 80`, `staticcheck ./...`, `knip` |
