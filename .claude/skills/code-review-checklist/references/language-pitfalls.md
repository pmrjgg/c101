# Language-specific review pitfalls

Traps that recur in production code review, grouped by language. Each line is a check you can grep for
or reason about directly. For deep language questions, delegate to the matching expert agent
(`rust-expert`, `cpp-expert`, `go-expert`, `java-expert`, `kotlin-expert`, `haskell-expert`,
`julia-expert`).

## Python
- Mutable default arguments: `def f(x=[])` shares the list across calls. Use `None` and create inside.
- Late-binding closures in loops: `[lambda: i for i in range(3)]` all return 2. Bind with `lambda i=i: i`.
- Truthiness bugs: `if not value` treats `0`, `""`, `[]` as missing. Use `is None`.
- Bare `except:` catches `KeyboardInterrupt`/`SystemExit`; `except Exception` still hides bugs if broad.
- `datetime.utcnow()` returns naive datetimes (deprecated since 3.12); use `datetime.now(timezone.utc)`.
- Blocking calls in `async def` (`requests`, `time.sleep`, sync DB drivers) stall the event loop.
- `asyncio.create_task(...)` without keeping a reference can be garbage collected mid-flight.
- `subprocess` with `shell=True` and interpolated input; `yaml.load` without `SafeLoader`;
  `pickle`/`marshal` on untrusted data; `eval`/`exec`.
- `assert` for runtime validation is stripped with `-O`.
- Float money; `round()` uses banker's rounding.
- Iterating a dict while mutating it raises; copying with `dict(d)` is shallow.
- `is` for value comparison (`x is 1000`) works by accident for small ints only.

## JavaScript and TypeScript
- `==` coercion; `typeof null === "object"`; `NaN !== NaN` (use `Number.isNaN`).
- `parseInt(x)` without radix; `Number("")` is 0.
- Array `sort()` without comparator sorts lexicographically (`[10, 9, 1].sort()` gives `[1, 10, 9]`).
- Floating money; integer precision lost beyond 2^53 (IDs from 64-bit backends need strings or `BigInt`).
- Unhandled promise rejections; `forEach` with `async` callbacks does not await; `Promise.all` fails fast
  and leaves the rest running (use `allSettled` when partial results matter).
- `JSON.parse` on untrusted data fed into a recursive merge/clone or set-by-path helper (custom `deepMerge`,
  old lodash `merge`/`set`/`defaultsDeep`): prototype pollution via `__proto__`/`constructor.prototype`.
  Plain object spread is not affected; `Object.assign` only swaps the target's own prototype.
- TypeScript `as` casts and non-null `!` assertions bypass checks; `any` leaks through generics.
- `exhaustive switch` without a `never` check misses new union members.
- Date: `new Date("2026-10-19")` parses as UTC, `new Date("2026-10-19T00:00")` as local time.
- React: stale closures in effects, missing dependency arrays, keys from array index on reorderable lists.
- Node: synchronous `fs` calls in request handlers; `child_process.exec` with interpolated strings.

## Go
- Loop variable capture: fixed by per-iteration semantics only when `go.mod` declares `go 1.22` or later.
- Nil interface vs interface holding a nil pointer: `var p *T = nil; var i I = p; i != nil` is true.
- `append` may share the backing array: two slices from one base can overwrite each other.
- Map concurrent writes crash the process; use a mutex or `sync.Map` for specific patterns.
- Goroutine leaks: sends on unbuffered channels with no receiver after a timeout path returns.
- `defer` inside loops accumulates until function return (file handles stay open).
- `time.After` in a long-lived `select` loop allocates a timer per iteration (pre-Go 1.23 timers were not
  collected until fired); prefer a reused `time.Timer` or `context`.
- Errors compared with `==` instead of `errors.Is`/`errors.As` after wrapping with `%w`.
- `context.Background()` inside request handlers instead of the request context (no cancellation).
- Ignoring `rows.Err()` after iterating `sql.Rows`; not closing `rows` or `resp.Body`.
- Integer conversion `int(x)` from `int64`/`uint64` silently truncates on 32-bit.
- `http.Client{}` without `Timeout` waits forever.

## Rust
- `unwrap()`/`expect()` on input-derived values in library or server code (panic = crash or poisoned state).
- `as` casts truncate or saturate silently; use `try_from`.
- `unsafe` blocks without a `// SAFETY:` comment stating the invariant; invariants that depend on code
  outside the block (any safe function in the module can break them).
- Holding a `std::sync::Mutex` guard across `.await`; blocking calls (`std::fs`, `std::thread::sleep`)
  in async tasks (use `spawn_blocking` or async equivalents).
- Cancel safety: futures in `tokio::select!` that lose data when dropped (e.g. partially read frames).
- `RefCell` double borrow panics at runtime; `Rc` cycles leak.
- `Send`/`Sync` manually implemented without proof.
- Integer overflow panics in debug and wraps in release unless `overflow-checks` set; use `checked_*`
  where it matters.
- `impl Drop` doing I/O that can fail silently; drop order surprises in temporaries.
- Feature flags: code compiled only under a feature is not tested by default CI.

## Java and Kotlin
- `equals` without `hashCode`; mutable fields used in `hashCode` of keys in a `HashMap`.
- `Optional.get()` without presence check; returning `null` from `Optional`-returning methods.
- `SimpleDateFormat` is not thread-safe; prefer `java.time`.
- `ConcurrentHashMap` compound operations (`get` then `put`) are not atomic; use `compute`/`merge`.
- `synchronized` on a boxed value or a string literal (shared monitor).
- Virtual threads: pinning when blocking inside `synchronized` (JDK 21-23; JDK 24 removed most pinning
  for `synchronized`), and thread-locals multiplied per virtual thread.
- Resource leaks without try-with-resources; streams from `Files.lines` must be closed.
- `BigDecimal.equals` compares scale (`2.0` vs `2.00`); use `compareTo`.
- Kotlin: platform types from Java (`String!`) can be null; `!!` on them; `lateinit` accessed before init;
  coroutines launched in `GlobalScope`; `runBlocking` on a dispatcher thread; catching
  `CancellationException` and not rethrowing.
- Jackson/serialization: polymorphic typing enabled on untrusted input (`activateDefaultTyping`).

## C and C++
- Undefined behaviour: signed overflow, out-of-bounds, use-after-free, data races, strict aliasing
  violations, uninitialized reads, null dereference, shifting by >= width.
- `size_t` arithmetic underflow in bounds checks (`if (len - 1 < n)`).
- Integer overflow in allocation sizes (`malloc(n * sizeof(T))`); use checked multiplication.
- Iterator and reference invalidation after `push_back`/`insert`/`erase`.
- `std::string_view`/`std::span` outliving the owner; returning references to locals or temporaries.
- Missing virtual destructor in polymorphic bases; slicing on pass-by-value.
- Rule of 0/3/5 violations with raw owning pointers.
- `std::move` then use; moving from `const` silently copies.
- Format strings from user input (`printf(user)`).
- Exceptions thrown through C APIs or destructors (`noexcept` destructors call `std::terminate`).
- Review with sanitizers on: `-fsanitize=address,undefined` and a TSan build for concurrent code.

## SQL
- String-built queries; dynamic identifiers (table/column names) not allowlisted.
- `NOT IN (subquery)` with NULLs returns no rows; prefer `NOT EXISTS`.
- `COUNT(column)` skips NULLs vs `COUNT(*)`.
- Implicit casts defeating indexes (`WHERE varchar_col = 123`), functions on indexed columns.
- Missing `ORDER BY` with `LIMIT` (nondeterministic pages); `OFFSET` pagination on large tables.
- Transactions spanning user think time or external calls; long transactions blocking vacuum.
- `UPDATE`/`DELETE` without a `WHERE` that matches the intended key; test with `SELECT` first.

## Shell
- Unquoted variables (word splitting and globbing), `for f in $(ls)`, missing `set -euo pipefail`.
- `cd dir && rm -rf *` when `cd` fails without `-e`; `rm -rf "$DIR/"` with an empty `$DIR`.
- `curl | sh` installs; `eval` on input; `[ $x = y ]` failing when `$x` is empty.
- `local x=$(cmd)` masks the exit code of `cmd`.
