# C++ undefined behavior catalogue

Each row: the rule, a minimal trigger, how it shows up in production, and the tool that catches
it. UB means the compiler may assume it never happens; optimizers exploit that, so symptoms
appear far from the cause and change with flags.

## Memory and lifetime

| UB | Trigger | Typical symptom | Detector / prevention |
|---|---|---|---|
| out-of-bounds read/write | `v[v.size()]`, `buf[n]` with `n` from input | corruption, crash later, security bug | ASan; `_GLIBCXX_ASSERTIONS` / `_LIBCPP_HARDENING_MODE`; `.at()` at trust boundaries; `std::span` |
| use-after-free | iterator/reference into a vector after `push_back`; `string_view` of freed string | intermittent garbage | ASan; hold indices; `[[clang::lifetimebound]]` |
| double free / mismatched `new[]`/`delete` | manual ownership | heap corruption | ASan (`alloc_dealloc_mismatch`); RAII only |
| use-after-return / use-after-scope | returning `&local`, lambda `[&]` outliving scope | stack garbage | ASan `detect_stack_use_after_return=1`; `-Wreturn-stack-address` |
| null dereference | missing check on lookup | crash, or the compiler deletes a later null check | UBSan `null`; `-Wnull-dereference`; references or `not_null` |
| reading an object outside its lifetime | placement-new over storage, then using an old pointer | optimizer "remembers" old values | `std::launder` rules; prefer `std::optional`/`std::variant` storage |
| uninitialized read | `int x; if (cond) x = 1; return x;` | random values, Release-only bugs | MSan; `-Wuninitialized -Wmaybe-uninitialized`; `-ftrivial-auto-var-init=pattern` in tests; C++26 makes it erroneous behavior (still a bug) |
| dangling temporary in range-for (without P2718) | `for (auto& x : get().items())` | garbage | bind `auto&& tmp = get();`; C++23 P2718 fixes it only where `__cpp_range_based_for >= 202211L` (GCC 15+, Clang 19+), not on GCC 14 / Clang 18 |
| modifying a string literal or `const` object | `char* p = (char*)"abc"; p[0] = 'x';` | segfault (read-only page) or silent | `-Wwrite-strings`; never cast away const to write |
| invalid iterator arithmetic | `it + n` past `end()`, comparing iterators of different containers | debug-mode asserts | `_GLIBCXX_DEBUG` (ABI-changing, debug builds only), libc++ debug hardening mode |

## Arithmetic

| UB | Trigger | Detector / prevention |
|---|---|---|
| signed integer overflow | `int a = INT_MAX; a + 1`; `i * stride` in index math | UBSan `signed-integer-overflow`; `__builtin_add_overflow`; C++26 `std::add_sat`; widen to `int64_t` |
| shift by negative or >= width | `1 << 32`, `x << -1` | UBSan `shift`; mask the count |
| left-shift of negative values | `-1 << 3` (UB before C++20, defined since C++20) | build as C++20 |
| division by zero, `INT_MIN / -1` | user-controlled divisor | UBSan `integer-divide-by-zero`; validate |
| float → int out of range | `(int)1e20` | UBSan `float-cast-overflow`; clamp first |
| unsigned wraparound | defined (not UB) but often a bug: `size_t i = 0; i - 1` | `-Wsign-conversion`, clang `-fsanitize=unsigned-integer-overflow` (reports, not UB) |

## Type system

| UB | Trigger | Detector / prevention |
|---|---|---|
| strict aliasing violation | `*reinterpret_cast<float*>(&u32)` | `std::bit_cast<float>(u32)`, `std::memcpy`; `-Wstrict-aliasing`; `-fno-strict-aliasing` only as a stopgap |
| misaligned access | casting `char*` buffer to `uint32_t*` | UBSan `alignment`; `memcpy` into a local; `alignas` |
| invalid `bool` / enum value | reading bytes into a `bool`; casting an int outside the enumeration's value range to an unscoped enum without a fixed underlying type (scoped enums always have one, so any value of it is valid) | UBSan `bool`,`enum`; validate before casting |
| calling through wrong function type | casting function pointers | UBSan `function` (Clang); avoid casts |
| bad `static_cast` downcast | `static_cast<Derived&>(base)` when it is not a `Derived` | UBSan `vptr`; `dynamic_cast` at uncertain sites |
| object slicing (not UB, but a bug) | pass-by-value of polymorphic base | delete copy in polymorphic bases |
| violating `[[assume(expr)]]` / `std::unreachable()` | assumption false at runtime | treat as UB; only assert-then-assume after a proof |

## Concurrency

| UB | Trigger | Detector / prevention |
|---|---|---|
| data race | two threads, one writes, no happens-before | TSan; mutexes or atomics; ownership transfer via queues |
| race on `std::shared_ptr` object itself (not the pointee) | one thread assigns `sp = x` while another copies `sp` | TSan; `std::atomic<std::shared_ptr<T>>` where `__cpp_lib_atomic_shared_ptr` is defined (not libc++/Apple Clang: use a mutex there) |
| destroying a locked mutex / unlocking from another thread | lifecycle bug | TSan; `std::unique_lock` scoped |
| `std::thread` destroyed while joinable | early return/exception | not UB but `std::terminate`; use `std::jthread` |

## Library preconditions (UB if violated)

- `front()`, `back()`, `pop_back()` on an empty container; `operator*` on empty `std::optional`;
  `.value()` throws but `*opt` is UB.
- `std::sort` with a comparator that is not a strict weak ordering (e.g. `<=`, or NaN floats):
  out-of-bounds reads in some implementations. Use `std::ranges::sort` with a correct comparator;
  for floats handle NaN explicitly or use `std::strong_order`.
- `std::string_view` / `std::span` constructed from a pointer and a wrong length.
- `std::vector::reserve` does not create elements; `operator[]` beyond `size()` is OOB even within
  capacity.
- Iterator invalidation rules per container (vector: insert/erase/reallocation invalidate;
  unordered: rehash invalidates iterators, not references; deque: insertion at ends invalidates
  iterators, not references).
- Calling `std::expected::value()` on an error throws `bad_expected_access`; `*e` on an error is UB.

## Program-level

| UB | Trigger | Detector / prevention |
|---|---|---|
| ODR violation | two different inline definitions/struct layouts with the same name in different TUs (different `#define` before an include, header-only lib versions mixed) | ASan `detect_odr_violation=2`, LTO `-Wodr`; one config header; anonymous namespaces for TU-local helpers |
| infinite loop without side effects | `while (!flag) {}` on a non-atomic flag | compiler deletes or hoists the loop; make the flag atomic. C++26 made trivial infinite loops (`while(true);`) defined, not loops that read non-atomic flags |
| static initialization order | global in TU A uses global in TU B | function-local statics, `constinit` |
| exceptions escaping `noexcept` | throwing in a `noexcept` function | `std::terminate` (defined); clang-tidy `bugprone-exception-escape` |
| reserved identifiers | names starting with `_Upper` or containing `__` | `-Wreserved-identifier` (Clang) |

## Sanitizer quick reference

```bash
# ASan + UBSan (combinable)
CXXFLAGS="-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer -g -O1"
export ASAN_OPTIONS=detect_stack_use_after_return=1:strict_string_checks=1:abort_on_error=1
# Linux only: prepend detect_leaks=1 (Apple Clang's runtime aborts on it)
export UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1
# TSan (separate build; not combinable with ASan)
CXXFLAGS="-fsanitize=thread -g -O1"
export TSAN_OPTIONS=halt_on_error=1:second_deadlock_stack=1
# MSan (Clang only; every linked library including libc++ must be instrumented)
CXXFLAGS="-fsanitize=memory -fsanitize-memory-track-origins=2 -g -O1"
```

Suppressions belong in a checked-in file with a reason per entry
(`TSAN_OPTIONS=suppressions=tsan.supp`); a suppression without an upstream bug link is a
review blocker. On macOS, leak detection is not supported by Apple Clang's ASan runtime; run
leak checks on Linux CI.

## Triage of a sanitizer report

1. Read the first frame in project code, the access kind (READ/WRITE, size), and for ASan the
   "allocated by" and "freed by" stacks; for TSan the two conflicting stacks and the mutexes held.
2. Reproduce with a minimal test; keep it as a regression test.
3. Fix the ownership or synchronization design, not the symptom (no extra copies to "move the
   crash", no sleeps to "fix" races).
4. Re-run the full suite under the same sanitizer.
