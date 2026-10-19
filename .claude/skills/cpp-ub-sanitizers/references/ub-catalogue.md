# C and C++ undefined behavior catalogue

Each row: the rule, a minimal trigger, how it shows up in production, and what catches or
prevents it. UB means the compiler may assume it never happens; optimisers exploit that, so
symptoms appear far from the cause and change with flags, compilers and unrelated edits.

## Memory and lifetime

| UB | Trigger | Typical symptom | Detector / prevention |
|---|---|---|---|
| out-of-bounds read/write | `v[v.size()]`, `buf[n]` with `n` from input | corruption, crash later, security bug | ASan; `_GLIBCXX_ASSERTIONS` / `_LIBCPP_HARDENING_MODE`; `.at()` at trust boundaries; `std::span` |
| pointer arithmetic beyond one-past-the-end | `p + n` past the array even without dereferencing | optimiser assumes no wrap, deletes bounds checks written as `p + n < p` | UBSan `pointer-overflow`; compare indices, not pointers |
| use-after-free | iterator/reference into a vector after `push_back`; `string_view` of a freed string | intermittent garbage | ASan; hold indices; `[[clang::lifetimebound]]` |
| double free / mismatched `new[]`/`delete` / `malloc`/`delete` | manual ownership | heap corruption | ASan (`alloc_dealloc_mismatch`, default off on Darwin/Windows); RAII only |
| use-after-return / use-after-scope | returning `&local`; `[&]` lambda outliving the scope | stack garbage | ASan `detect_stack_use_after_return=1`; `-Wreturn-stack-address`; Clang `-Wdangling` |
| null dereference | missing check on a lookup | crash, or the compiler deletes a later null check | UBSan `null`; `-Wnull-dereference`; references or `gsl::not_null` |
| reading an object outside its lifetime | placement-new over storage, then using the old pointer | optimiser "remembers" old values | `std::launder` on the old pointer; prefer `std::optional`/`std::variant` storage |
| accessing bytes as an object that was never created | `reinterpret_cast<Header*>(buf)` on a received buffer | works until an optimiser relies on it | C++20 implicit object creation covers `malloc`/`memcpy`/`std::bit_cast` into implicit-lifetime types; C++23 `std::start_lifetime_as<T>(p)` (libstdc++ 16, MSVC 19.51); `memcpy` into a local |
| uninitialised read | `int x; if (c) x = 1; return x;` | random values, Release-only bugs | MSan; `-Wuninitialized -Wmaybe-uninitialized`; `-ftrivial-auto-var-init=pattern` in tests; C++26 erroneous behavior (still a bug) |
| dangling temporary in range-for (without P2718) | `for (auto& x : get().items())` | garbage | bind `auto&& tmp = get();`; fixed only where `__cpp_range_based_for >= 202211L` (GCC 15+, Clang 19+, MSVC 19.51) |
| modifying a string literal or a `const` object | `char* p = (char*)"abc"; p[0] = 'x';` | segfault (read-only page) or silent | `-Wwrite-strings`; never cast away `const` to write |
| `memcpy`/`memset` on non-trivially-copyable types | `memset(this, 0, sizeof *this)` on a class with a vptr or `std::string` | vptr or invariant destroyed | clang-tidy `bugprone-undefined-memory-manipulation`; constructors |
| `memcpy` with overlapping ranges | in-place shift with `memcpy` | corrupted data on some libc versions | ASan `memcpy-param-overlap`; `memmove` |
| deleting an incomplete type with a non-trivial destructor | `delete p` where `p` is a forward-declared `Impl*` | destructor silently skipped | `-Wdelete-incomplete`; `unique_ptr` with an out-of-line destructor |
| invalid iterator arithmetic / comparison | `it + n` past `end()`, comparing iterators of different containers | debug-mode asserts | `_GLIBCXX_DEBUG` (ABI-changing, debug builds only), MSVC `_ITERATOR_DEBUG_LEVEL=2` |

## Arithmetic

| UB | Trigger | Detector / prevention |
|---|---|---|
| signed integer overflow | `int a = INT_MAX; a + 1`; `i * stride` in index math; `std::abs(INT_MIN)`, `-INT_MIN` | UBSan `signed-integer-overflow`; `__builtin_add_overflow`/`_sub_`/`_mul_`; C++26 `std::add_sat`; widen to `std::int64_t` |
| shift by negative or >= width | `1 << 32`, `x << -1` | UBSan `shift`; mask the count |
| left shift of negative values | `-1 << 3` (UB before C++20, defined since C++20 as two's complement) | build as C++20 |
| division by zero, `INT_MIN / -1`, `INT_MIN % -1` | user-controlled divisor | UBSan `integer-divide-by-zero`; validate |
| float to int out of range (including NaN) | `(int)1e20`, `(int)NAN` | UBSan `float-cast-overflow` (in Clang's `undefined`, not GCC's); clamp and check `std::isfinite` first |
| float division by zero | `x / 0.0` | IEEE 754 defines it (inf/NaN) and implementations follow Annex F; UBSan `float-divide-by-zero` is opt-in |
| out-of-range integer conversion | `int8_t(300)` | not UB: implementation-defined before C++20, modular since C++20; `-Wconversion`, Clang `-fsanitize=implicit-conversion` |
| unsigned wraparound | defined, but often a bug: `size_t i = 0; i - 1` | `-Wsign-conversion`; Clang `-fsanitize=unsigned-integer-overflow` (reports, not UB); `std::ssize`, `std::cmp_less` for mixed-sign comparisons |

## Type system

| UB | Trigger | Detector / prevention |
|---|---|---|
| strict-aliasing violation | `*reinterpret_cast<float*>(&u32)`; union type punning in C++ (allowed in C) | TySan (`-fsanitize=type`, Clang 20+); `-Wstrict-aliasing` (GCC levels 1-3, default 3); `std::bit_cast<float>(u32)`, `std::memcpy`; `char`, `unsigned char` and `std::byte` may alias anything; `-fno-strict-aliasing` only as a stopgap |
| misaligned access | casting a `char*` buffer to `uint32_t*`; packed structs | UBSan `alignment`; `memcpy` into a local; `alignas`; `std::assume_aligned` only when true |
| invalid `bool` / enum value | reading bytes into a `bool`; casting an int outside the value range of an unscoped enum without a fixed underlying type (scoped enums always have one, so any value of the underlying type is valid) | UBSan `bool`, `enum`; validate before casting |
| calling through the wrong function type | casting function pointers | UBSan `function` (Clang); avoid casts |
| bad `static_cast` downcast | `static_cast<Derived&>(base)` when it is not a `Derived` | UBSan `vptr` (not in Clang's `undefined` group: add it; needs RTTI); `dynamic_cast` at uncertain sites |
| object slicing (not UB, but a bug) | pass-by-value of a polymorphic base | delete copy in polymorphic bases; clang-tidy `cppcoreguidelines-slicing` |
| violating `[[assume(expr)]]` / reaching `std::unreachable()` | the assumption is false at run time | treat as UB; only assert-then-assume after a proof |
| deleting through a base pointer without a virtual destructor | `std::unique_ptr<Base>` holding a `Derived` with members (derived destructor skipped) | `-Wdelete-non-virtual-dtor` (in `-Wall`); virtual or protected destructor |

## Concurrency

| UB | Trigger | Detector / prevention |
|---|---|---|
| data race | two threads, one writes, no happens-before | TSan; mutexes or atomics; ownership transfer via queues |
| race on a `std::shared_ptr` object itself (not the pointee) | one thread assigns `sp = x` while another copies `sp` | TSan; `std::atomic<std::shared_ptr<T>>` where `__cpp_lib_atomic_shared_ptr` is defined (not libc++: use a mutex there) |
| destroying a locked mutex / unlocking from a non-owner thread | lifecycle bug; `co_await` while holding a `std::mutex` | TSan; scoped locks; coroutine-aware mutexes |
| non-atomic flag polled in a loop | `while (!stop) {}` (loop hoisted or deleted) | TSan reports the race; `std::atomic<bool>`, `std::stop_token` |
| `std::thread` destroyed while joinable | early return or exception | not UB but `std::terminate`; use `std::jthread` |

## Library preconditions (UB if violated)

- `front()`, `back()`, `pop_back()` on an empty container; `operator*` on an empty
  `std::optional` (`.value()` throws `bad_optional_access` instead).
- `*e` or `e->` on a `std::expected` holding an error, `e.error()` on one holding a value
  (`.value()` throws `bad_expected_access<E>`).
- `std::sort` / `std::ranges::sort` with a comparator that is not a strict weak ordering
  (`<=`, NaN-containing floats): out-of-bounds reads in some implementations. Handle NaN
  explicitly, or sort floats with a total order:
  `std::ranges::sort(v, [](double a, double b) { return std::strong_order(a, b) < 0; });`
- `std::string_view` / `std::span` constructed from a pointer and a wrong length.
- `std::vector::reserve` does not create elements: `operator[]` beyond `size()` is out of bounds
  even within capacity.
- Iterator invalidation rules per container (vector: reallocation invalidates everything;
  unordered: rehash invalidates iterators but not references; deque: insertion at the ends
  invalidates iterators but not references).
- `std::memcpy`/`std::memset` with a null pointer, even for size 0 (C rule inherited by C++;
  C2y relaxes it via N3322, older compilers and libraries still assume non-null).
- `printf`-family format/argument mismatch: `-Wformat=2`; prefer `std::format`/`std::print`
  (checked at compile time).
- `std::accumulate` / `std::reduce` overflowing a signed accumulator type: pass an `int64_t`
  initial value.
- `std::midpoint`, `std::cmp_less`, `std::in_range` (C++20) exist precisely to avoid
  overflow and mixed-sign pitfalls: use them.

## Program-level

| UB | Trigger | Detector / prevention |
|---|---|---|
| ODR violation | two different inline definitions or struct layouts with the same name in different TUs (different `#define` before an include, mixed header-only library versions) | ASan `detect_odr_violation=2`, LTO `-Wodr`; one config header; anonymous namespaces for TU-local helpers |
| infinite loop without side effects | `while (!flag) {}` on a non-atomic flag | the compiler deletes or hoists the loop; make the flag atomic. C++26 (P2809) defines trivial infinite loops such as `while (true);`, not loops that read non-atomic flags |
| static initialisation order | a global in TU A uses a global in TU B during dynamic init | ASan `check_initialization_order=1` (checked: reports `initialization-order-fiasco`); function-local statics; `constinit` |
| exceptions escaping `noexcept` | throwing in a `noexcept` function or destructor | defined: `std::terminate`; clang-tidy `bugprone-exception-escape` |
| reserved identifiers | names starting with `_Upper` or containing `__`; adding declarations to `namespace std` | `-Wreserved-identifier` (Clang); clang-tidy `cert-dcl58-cpp` |

## C++26 changes that move UB

| Change | Paper | Effect |
|---|---|---|
| erroneous behavior for uninitialised reads | P2795 | reading an uninitialised automatic variable yields an implementation-chosen value and is a diagnosable bug, not UB; `[[indeterminate]]` restores the old semantics for a variable (GCC 16 implements it) |
| hardened standard library | P3471 | hardened implementations check listed preconditions as contract assertions |
| contracts | P2900 | `pre`, `post`, `contract_assert` with ignore/observe/enforce/quick-enforce semantics |
| trivial infinite loops | P2809 | `while (true);` and similar are no longer UB |
| preprocessing is never undefined | P2843 | former preprocessor UB becomes ill-formed or defined (GCC 16 implements it) |

## Sanitizer quick reference

```bash
# ASan + UBSan (combinable)
CXXFLAGS="-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer -g -O1"
export ASAN_OPTIONS=detect_stack_use_after_return=1:strict_string_checks=1:abort_on_error=1
# Linux only: prepend detect_leaks=1 (Apple clang's runtime aborts on it)
export UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1
# TSan (separate build; not combinable with ASan)
CXXFLAGS="-fsanitize=thread -g -O1"
export TSAN_OPTIONS=halt_on_error=1:second_deadlock_stack=1
# MSan (Clang, Linux; every linked library including libc++ must be instrumented)
CXXFLAGS="-fsanitize=memory -fsanitize-memory-track-origins=2 -fno-omit-frame-pointer -g -O1"
```

Suppressions belong in a checked-in file with a reason per entry
(`TSAN_OPTIONS=suppressions=tsan.supp`); a suppression without an upstream bug link is a
review blocker.
