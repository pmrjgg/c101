# Stdlib idioms and data modelling

Reach-for-first standard library answers, so new code does not reinvent them. Respect the
project's `requires-python` floor: version-gated items are marked.

## 1. Data shapes

```python
from dataclasses import dataclass, field, replace
from enum import StrEnum                     # 3.11+

class Status(StrEnum):
    OPEN = "open"
    PAID = "paid"

@dataclass(frozen=True, slots=True, kw_only=True)
class Invoice:
    id: int
    status: Status = Status.OPEN
    lines: tuple[Line, ...] = ()             # immutable collection for a frozen value
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.id <= 0:
            raise ValueError(f"invoice id must be positive, got {self.id}")

paid = replace(inv, status=Status.PAID)      # copy with changes
```

| Choose | When | Avoid when |
|---|---|---|
| `dataclass` | internal values and records | you need validation from untrusted input (use pydantic) |
| `NamedTuple` | tuple compatibility (unpacking, legacy APIs) | fields will grow; positional access invites bugs |
| `TypedDict` | JSON you pass through or do not own | you need methods or defaults |
| pydantic `BaseModel` | boundaries: HTTP, config, files | hot inner loops (validation cost) |
| `attrs` | already a dependency; converters and validators on fields | adding a dependency for what dataclasses do |

## 2. Collections and iteration

| Need | Use |
|---|---|
| count things | `collections.Counter(items).most_common(10)` |
| group things | `defaultdict(list)`; sorted input: `itertools.groupby` |
| FIFO / bounded history | `collections.deque(maxlen=N)` |
| top-k | `heapq.nlargest(k, items, key=...)` |
| sorted insert / lookup | `bisect.insort`, `bisect.bisect_left` |
| chunks of n | `itertools.batched(it, n)` (3.12+) |
| sliding pairs | `itertools.pairwise(it)` |
| flatten one level | `itertools.chain.from_iterable(nested)` |
| first match or default | `next((x for x in xs if pred(x)), None)` |
| dedupe preserving order | `list(dict.fromkeys(xs))` |
| merge dicts | `a \| b` (right wins) |

## 3. Functions and resources

- `functools.cache` / `lru_cache(maxsize=N)` for pure functions of hashable args; on methods it keeps
  `self` alive: use `cached_property` or a module-level cache keyed by id.
- `functools.partial` instead of lambdas that only fix arguments; `functools.wraps` on every decorator
  (type it with `ParamSpec`, see `python-typing`).
- `contextlib.contextmanager` for setup/teardown pairs, `ExitStack` for a dynamic number of resources,
  `suppress(FileNotFoundError)` for a deliberate ignore, `chdir` (3.11+) for scoped cwd changes.
- `operator.attrgetter` / `itemgetter` as sort keys.

## 4. Paths, files and processes

```python
from pathlib import Path
import subprocess, tempfile

cfg = Path(__file__).parent / "data" / "defaults.toml"
text = cfg.read_text(encoding="utf-8")
for p in Path("logs").glob("**/*.log"): ...

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "result.json"

res = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True,
                     text=True, timeout=30)
```

- Write files atomically: write to a temp file in the same directory, then `os.replace(tmp, target)`.
- `tomllib` (3.11+) reads TOML; it cannot write. `json.dumps(..., ensure_ascii=False, indent=2)` for
  human-readable output.
- `shutil.which("tool")` before calling an external binary; never build a shell string from input.

## 5. Time

- `datetime.now(UTC)` (`from datetime import UTC`, 3.11+; older: `timezone.utc`). Store and compare in
  UTC, convert at the edges with `zoneinfo.ZoneInfo`.
- `time.monotonic()` / `perf_counter()` for durations; never subtract wall-clock times to time code.
- Parse ISO 8601 with `datetime.fromisoformat` (accepts most ISO forms since 3.11).

## 6. Logging

```python
import logging
logger = logging.getLogger(__name__)          # per module; configure once in main()

def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info("processing %d files", n)     # lazy %-args, not f-strings
    try:
        run()
    except Exception:
        logger.exception("run failed")        # logs the traceback
        raise
```

Libraries never call `basicConfig` or add handlers beyond `logging.NullHandler()`. Never log secrets,
tokens or full request bodies.

## 7. Numbers

- Money: integer minor units or `decimal.Decimal` built from strings (`Decimal("0.10")`, never from a
  float). `fractions.Fraction` for exact rationals.
- `math.isclose(a, b, rel_tol=1e-9)` for float comparison; `math.fsum` for accurate sums.
- `statistics.median`, `quantiles`, `fmean` before pulling in NumPy for small data.

## 8. Entry points

```python
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)    # argparse; testable by passing argv
    ...
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

Expose it as `[project.scripts] mytool = "mypkg.cli:main"`; keep imports of heavy libraries inside
the subcommand that needs them so `--help` stays fast.
