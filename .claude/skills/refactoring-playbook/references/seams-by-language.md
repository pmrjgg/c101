# Seams by language

How to break a hidden dependency (clock, randomness, I/O, globals, singletons) so legacy code can
be put under characterization tests before refactoring. Prefer the first column (explicit
injection); use the later ones only to get the first tests in place.

| Language | Explicit injection (preferred) | Object seam | Link / module seam (test only) |
|---|---|---|---|
| Python | parameter with default: `def run(now=datetime.now, rng=random.Random(0))` | Protocol + fake class | `monkeypatch.setattr(module, "name", fake)`; patch where it is looked up, not where defined |
| Java | constructor injection; `java.time.Clock` parameter | extract interface + fake | package-private factory method overridden in a test subclass |
| Kotlin | constructor parameter with default; `java.time.Clock`, or the stdlib/kotlinx clock your Kotlin version provides | interface + fake | `mockk` `mockkStatic`/`mockkObject` for top-level and object singletons |
| Go | function field or interface parameter: `type Clock interface{ Now() time.Time }` | small interface defined at the consumer | package-level `var now = time.Now` swapped in tests (not parallel-safe) |
| Rust | generic parameter or `&dyn Trait`; pass `impl Rng` (seeded `StdRng::seed_from_u64(0)`) | trait + test impl | `#[cfg(test)]` alternative module; feature-gated fakes |
| TypeScript | constructor/function parameter; `{ now = () => new Date() } = {}` | interface + fake object | `vi.mock("./module")` / `jest.mock`; `vi.useFakeTimers()` / `vi.setSystemTime()` |
| C++ | constructor parameter (reference/pointer to interface); template parameter | virtual interface + fake | link seam: link a fake `.o` instead of the real one; preprocessor seam as a last resort |
| C# | constructor injection; `TimeProvider` (.NET 8+) | interface + fake | `InternalsVisibleTo` + virtual methods |

## Patterns

### Clock

```python
class InvoiceService:
    def __init__(self, repo: Repo, now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._repo, self._now = repo, now
```

Tests pass `now=lambda: datetime(2026, 1, 31, 23, 59, tzinfo=UTC)`. Avoid freezing the global clock
when injection is possible: global freezes leak across tests and hide the dependency.

### Randomness

Pass a seeded generator object (`random.Random(42)`, `numpy.random.default_rng(42)`,
`StdRng::seed_from_u64(42)`), never reseed the global generator inside library code.

### File system

Accept paths or file-like objects instead of hard-coded locations; tests use `tmp_path` (pytest),
`t.TempDir()` (Go), `tempfile` crate (Rust), `@TempDir` (JUnit 5).

### Network / database

Introduce a repository or gateway interface at the boundary; characterization tests use a fake or
a recorded transcript (VCR-style cassettes, WireMock, `httpx.MockTransport`, `responses`);
integration tests use a real container (Testcontainers).

### Singletons and globals

1. Wrap access in a function (`get_config()`), replace direct uses.
2. Make the function read from a parameter with the global as default.
3. Push the parameter up one caller at a time until construction happens at the composition root.

### Static / free function calls inside logic

Extract the call into a method (Extract and Override Call) or pass the function as a parameter
(`send: Callable[[Email], None] = smtp_send`).

## Test-only seams to remove after the refactor

- `monkeypatch`/`mock.patch` on internals: replace with constructor injection once the code is
  restructured; patches on private names break on every rename.
- Subclass-and-override test doubles: replace with the extracted interface's fake.
- Package-level mutable function variables in Go: replace with injected interfaces; they block
  `t.Parallel()`.
