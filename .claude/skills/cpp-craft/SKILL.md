---
name: cpp-craft
description: "Modern C++ (C++20, C++23, C++26) expertise pack covering RAII and value semantics, move semantics, templates and concepts, constexpr, ranges, coroutines, the memory model and atomics, an undefined-behavior catalogue, sanitizers (ASan, UBSan, TSan), CMake presets, Catch2 and GoogleTest, and performance and SIMD. Load when writing, reviewing, debugging or optimizing C++ code or its CMake build."
when_to_use: "Any task touching .cpp/.hpp/.cc/.h files, CMakeLists.txt or CMakePresets.json, crashes or heisenbugs in native code, data races, template errors, C++ performance or vectorization work."
---

# C++ craft

Baseline: C++20 everywhere, C++23 where the toolchain supports it (GCC 14+, Clang 18+, MSVC
17.10+), C++26 features only behind a feature-test macro check. C++26 was finalized in 2026 and
includes static reflection, contracts, `std::execution`, `std::simd`, `std::inplace_vector`,
hardened standard library preconditions and erroneous behavior for uninitialized reads; trivial
relocatability was removed. Compiler support lags: check the cppreference compiler-support page
before using any C++26 feature, and guard with `__cpp_lib_*` / `__cpp_*` macros.

Deep material:
[UB catalogue with detectors](references/ub-catalogue.md) |
[CMake presets, sanitizers, hardening, tests](references/build-sanitizers-testing.md) |
[concurrency, memory model, coroutines](references/concurrency-coroutines.md) |
[performance and SIMD](references/performance-simd.md)

## 1. Orient in a repo

```bash
cmake --version; c++ --version
ls CMakePresets.json CMakeUserPresets.json vcpkg.json conanfile.* .clang-tidy .clang-format 2>/dev/null
grep -rnE 'CMAKE_CXX_STANDARD|cxx_std_' CMakeLists.txt cmake/ 2>/dev/null
cmake --list-presets 2>/dev/null
grep -rn 'fsanitize' CMake* cmake/ 2>/dev/null | head
```

Record: standard level, compilers in CI, package manager (vcpkg manifest, Conan 2, FetchContent),
warnings policy, sanitizer jobs, test framework. If `compile_commands.json` is missing, configure
with `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` so clang-tidy and clangd work.

## 2. The gate

| Step | Command | Blocks when |
|---|---|---|
| Configure + build, warnings as errors | `cmake --preset dev && cmake --build --preset dev` | any warning in project code |
| Tests | `ctest --preset dev --output-on-failure -j` | any failure |
| ASan + UBSan | `cmake --workflow --preset asan` | any report (`-fno-sanitize-recover=all`) |
| TSan (if threads) | `cmake --workflow --preset tsan` | any race report |
| Static analysis | `run-clang-tidy -p build/dev -quiet` (or `clang-tidy` on changed files) | new findings in enabled checks |
| Format | `git clang-format --diff origin/main` | any diff |

Presets, flags and the warning set are in [build-sanitizers-testing](references/build-sanitizers-testing.md).
A change to threading code without a TSan run is not done.

## 3. Resource and value semantics

Rules:
1. **Rule of zero**: members are RAII types (`std::unique_ptr`, `std::vector`, `std::string`,
   handle wrappers); the class declares no destructor, copy or move operations.
2. If you must manage a resource directly, write a tiny dedicated RAII wrapper (rule of five
   in that wrapper only), then rule of zero everywhere else.
3. Polymorphic base classes: `virtual ~Base() = default;` and delete copy (slicing), or make the
   destructor protected non-virtual if deletion through the base is not allowed.
4. No owning raw pointers, no naked `new`/`delete`. `std::make_unique`; `std::make_shared` only
   when ownership is genuinely shared.
5. Prefer values and `std::optional`/`std::variant` to heap-allocated polymorphism when the set of
   alternatives is closed.

Parameter passing:

| Intent | Signature |
|---|---|
| observe a cheap trivially-copyable value (<= 2 words) | `T` |
| observe anything else | `const T&`; text `std::string_view`; contiguous `std::span<const T>` |
| mutate caller's object | `T&` |
| sink (callee stores it) | `T` by value, then `std::move` into place (one extra move, simplest); `T&&` + `const T&` overloads only in measured hot paths |
| forward generically | `template <class U> void f(U&& u)` with `std::forward<U>(u)` |
| transfer unique ownership | `std::unique_ptr<T>` by value |
| share ownership | `std::shared_ptr<T>` by value only if the callee keeps a copy; otherwise pass `T&` |
| optional reference | `T*` (non-owning, documented), or `std::optional<T&>` with C++26 |
| non-owning callable | template `F&&`, or `std::function_ref` (C++26) |
| stored callable | `std::move_only_function` (C++23) or `std::function` |

Returns: by value (copy elision is mandatory for prvalues, NRVO usual). `std::expected<T, E>`
(C++23) for recoverable failures, `std::optional<T>` for "no value". Never return references or
views to locals or to members of temporaries.

## 4. Move semantics checklist

- `std::move` is a cast; it moves nothing. Moved-from objects are valid but unspecified: only
  assign to them or destroy them (standard containers are empty after move in practice, but do
  not rely on it for your types without documenting it).
- Mark move constructor and move assignment `noexcept`; otherwise `std::vector` copies on
  reallocation (`std::move_if_noexcept`). `static_assert(std::is_nothrow_move_constructible_v<T>);`
- Do not `return std::move(local);` (blocks NRVO; `-Wpessimizing-move`). Do `return std::move(member);`
  only when deliberately moving out of `*this` in an rvalue-qualified method.
- `const` objects cannot be moved from; `const` locals that are returned are copied.
- After `auto x = std::move(y);` any later read of `y` is a bug unless re-assigned
  (clang-tidy `bugprone-use-after-move`).

## 5. Error handling decision table

| Situation | Mechanism |
|---|---|
| precondition violated (programmer bug) | `assert`, C++26 contracts (`pre`, `post`, `contract_assert`) or a project `CHECK` macro that terminates |
| expected, frequent failure the caller handles locally (parse, lookup, validation) | `std::expected<T, Error>` / `std::optional<T>` |
| rare failure that must unwind many frames (OOM, I/O failure deep in a call tree) | exceptions, if the codebase allows them |
| hard real-time, `-fno-exceptions` codebases, ABI boundaries | error codes / `std::expected`, never exceptions across a C ABI |
| destructors, move operations, swap | never throw (`noexcept`) |

Exception safety guarantees to state for every mutating operation: nothrow, strong (commit or
roll back; copy-and-swap), or basic (invariants hold, state unspecified).

## 6. Templates and concepts

- Constrain every template with concepts; SFINAE (`enable_if`) only for C++17 compatibility.
- Use standard concepts first: `std::integral`, `std::floating_point`, `std::invocable<F, Args...>`,
  `std::ranges::range`, `std::ranges::random_access_range`, `std::copyable`, `std::regular`,
  `std::totally_ordered`, `std::convertible_to`.
- A concept names a semantic requirement, not a syntactic accident. Prefer
  `template <std::ranges::input_range R>` to ad-hoc `requires requires { r.begin(); }`.
- `if constexpr` instead of tag dispatch; fold expressions instead of recursive variadics.
- C++23 deducing `this` (`void f(this auto&& self)`) replaces CRTP and const/non-const overload
  duplication.
- Keep template definitions in headers or modules; explicit instantiation (`extern template`)
  to cut compile time for common instantiations.
- Error-message hygiene: put `static_assert(Concept<T>, "why")` at the top of complex templates.

```cpp
template <std::ranges::input_range R, class Proj = std::identity>
  requires std::totally_ordered<std::indirect_result_t<Proj&, std::ranges::iterator_t<R>>>
auto max_by(R&& r, Proj proj = {}) {
    return std::ranges::max(std::forward<R>(r), {}, proj);   // precondition: r non-empty
}
```

## 7. constexpr and compile-time work

- `constexpr` functions run at compile time when used in constant expressions; UB inside a
  constant evaluation is a compile error, so `static_assert`-driven tests catch UB for free.
- `consteval` forces compile-time evaluation (format-string checking, IDs). `if consteval`
  (C++23) to branch between compile-time and runtime implementations.
- `constinit` on globals guarantees static initialization (fixes the static init order fiasco
  for that variable); combine with `const` or atomics for thread safety.
- C++20 allows transient `std::vector`/`std::string` in constexpr (allocated and freed within the
  evaluation). Results must not keep the allocation; copy into `std::array`.
- C++26 static reflection (`^^T`, `[: :]` splicers, `std::meta`) generates enum-to-string,
  serialization and struct walking without macros; gate on compiler support.

## 8. Ranges

- Views are lazy and non-owning; never return a view over a local container or a temporary.
  Algorithms return `std::ranges::dangling` for rvalue ranges to catch some of this.
- `std::ranges::to<std::vector>()` (C++23) to materialize; `views::enumerate`, `views::zip`,
  `views::chunk`, `views::slide`, `views::join_with`, `views::cartesian_product` (C++23).
- `views::filter` caches `begin()`: do not mutate the underlying elements so they change the
  predicate result, and a `const` filter view is not iterable (pass views by value or `auto&&`).
- `views::transform` + `views::filter`: the transform may run twice per element; keep it cheap
  and pure.
- Projections replace lambdas: `std::ranges::sort(people, {}, &Person::age);`.
- C++23 (P2718) extends range-for temporary lifetime: `for (auto x : make().items())` is safe only
  when `__cpp_range_based_for >= 202211L` (GCC 15+, Clang 19+; check MSVC). On GCC 14, Clang 18 or
  C++20 it dangles: bind a named variable (`auto&& tmp = make(); for (auto x : tmp.items())`).

## 9. Concurrency (summary; details in [concurrency-coroutines](references/concurrency-coroutines.md))

- A data race (unsynchronized conflicting access, at least one write) is UB. Every shared
  mutable object is protected by a mutex or is atomic. `volatile` is not synchronization.
- Prefer `std::jthread` (joins on destruction, `std::stop_token`) to `std::thread`.
- Lock multiple mutexes with `std::scoped_lock(a, b)`; never call unknown code (callbacks,
  virtuals) while holding a lock.
- Atomics: default `seq_cst`; relax only with a written argument (release/acquire pairs for
  publication, relaxed for counters). Pad hot atomics to separate cache lines (64 bytes; 128 on
  Apple silicon and some Intel parts with adjacent-line prefetch).
- Coroutines: parameters taken by reference and lambda captures dangle after the first suspend.
  Take coroutine parameters by value.

## 10. Performance procedure (summary; details in [performance-simd](references/performance-simd.md))

1. Build `RelWithDebInfo` (`-O2 -g`) plus `-fno-omit-frame-pointer`; measure with Google
   Benchmark or nanobench, repeated runs, CPU frequency pinned where possible.
2. Profile: `perf record -g ./bench` / `perf report --stdio --no-children --percent-limit 2 | head -60`
   (full report to `.stack/out/<agent>/`), or VTune / Instruments; allocations with
   `heaptrack`; cache behavior with `perf stat -e cache-misses,branch-misses`.
3. Fix the top item, re-measure, keep only statistically clear wins.

| Profile symptom | First fix |
|---|---|
| `malloc`/`operator new` hot | `reserve`, reuse buffers, `std::pmr::monotonic_buffer_resource` per request, small-buffer types |
| `shared_ptr` refcount atomics hot | pass `T&`/`const T&`, move instead of copy |
| node containers (`std::map`, `std::list`, `std::unordered_map`) hot | sorted `std::vector` / `std::flat_map` (C++23), open-addressing maps (abseil, boost::unordered_flat_map) |
| virtual calls in inner loop | `std::variant` + `std::visit`, templates, or sort by type and batch |
| branch-misses high | branchless select, sort data, `[[likely]]` only with measurement |
| loop not vectorized | check `-Rpass-missed=loop-vectorize` (Clang) / `-fopt-info-vec-missed` (GCC); fix aliasing (`__restrict`), stride, early exits |
| string building | `std::format_to` into a reserved buffer, `std::string_view` slicing |

## 11. Undefined behavior: top offenders (full list in [ub-catalogue](references/ub-catalogue.md))

| UB | Detector |
|---|---|
| out-of-bounds access, use-after-free, double free, use-after-return | ASan (`detect_stack_use_after_return=1`), hardened library modes |
| signed overflow, shift past width, misaligned access, bad enum/bool values | UBSan |
| data race | TSan |
| uninitialized read | MSan (Clang, whole program instrumented), `-ftrivial-auto-var-init=pattern` in tests; erroneous behavior in C++26 |
| strict-aliasing violation (`reinterpret_cast` punning) | `-fstrict-aliasing -Wstrict-aliasing`, review; use `std::bit_cast` / `memcpy` |
| dangling references / views / iterators | ASan, `-Wdangling` family, clang `[[clang::lifetimebound]]`, review |
| ODR violations (different definitions across TUs) | ASan `detect_odr_violation`, LTO warnings, `-Wodr` |

## 12. Pitfalls (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| crash only in Release | UB optimized differently (uninit, overflow, aliasing) | run ASan+UBSan on Release-like `-O2` build |
| `std::vector` copies on growth | move ctor not `noexcept` | mark `noexcept`, `static_assert` it |
| slow `std::unordered_map` | node allocation, poor hash | reserve, better hash, flat map |
| iterator invalid after `push_back` | reallocation | indices, `reserve`, or `std::deque`/stable storage |
| static init order crash | cross-TU global dependency | function-local static, `constinit` |
| `std::string_view` garbage | view of a temporary `std::string` | own the string; `lifetimebound` |
| lambda captures dangle | `[&]` lambda stored or run asynchronously | capture by value or `shared_from_this` |
| deadlock | inconsistent lock order, callback under lock | `std::scoped_lock`, lock hierarchy, release before callbacks |
| `std::vector<bool>` surprises | proxy references, not a container of `bool` | `std::vector<char>` or `std::bitset`/`boost::dynamic_bitset` |
| implicit narrowing | `int` ← `size_t`, `float` ← `double` | `-Wconversion -Wsign-conversion`, brace init |
| exception escapes destructor | `std::terminate` | catch inside destructor, log |
| slow builds | heavy headers, templates everywhere | modules or PCH, forward declarations, explicit instantiation, `-ftime-trace` (Clang) |

## 13. Review checklist

- [ ] No owning raw pointers; RAII for every resource; rule of zero except in wrappers.
- [ ] Move operations `noexcept`; no use-after-move; no `return std::move(local)`.
- [ ] Parameters follow the table in section 3; no views or references escaping their owner.
- [ ] Templates constrained by concepts; error messages readable.
- [ ] Errors: `std::expected`/exceptions chosen per section 5; destructors never throw.
- [ ] Shared state synchronized; atomics orderings justified in comments; TSan run.
- [ ] ASan+UBSan run clean on the test suite; new code has tests under sanitizers.
- [ ] `-Wall -Wextra -Wpedantic -Wconversion -Wshadow` clean; clang-tidy clean on changed files.
- [ ] Performance claims backed by a benchmark diff, not intuition.
- [ ] Public headers self-contained (include what you use), no `using namespace` in headers.

## 14. Worked example: from leaky handle code to RAII + expected

Before (leaks on early return, unclear ownership, errors as magic ints):

```cpp
int load(const char* path, Config* out) {
    FILE* f = fopen(path, "rb");
    if (!f) return -1;
    char* buf = (char*)malloc(4096);
    if (fread(buf, 1, 4096, f) == 0) return -2;      // leaks f and buf
    *out = parse(buf);
    free(buf); fclose(f);
    return 0;
}
```

After (C++23):

```cpp
struct FileCloser { void operator()(std::FILE* f) const noexcept { std::fclose(f); } };
using File = std::unique_ptr<std::FILE, FileCloser>;

enum class LoadError { open_failed, read_failed, parse_failed };

std::expected<Config, LoadError> load(const std::filesystem::path& path) {
    File f{std::fopen(path.c_str(), "rb")};
    if (!f) return std::unexpected(LoadError::open_failed);
    std::vector<char> buf(4096);
    const auto n = std::fread(buf.data(), 1, buf.size(), f.get());
    if (n == 0) return std::unexpected(LoadError::read_failed);
    buf.resize(n);
    return parse(std::span<const char>(buf));         // parse returns std::expected<Config, LoadError>
}
```

Every exit path releases both resources, the error type is closed and documented, the caller
chooses `value_or`, `and_then`, or a `switch` on the error. (On Windows, `path.c_str()` is
`wchar_t*`; use `_wfopen` or `std::ifstream` there.)

## 15. Worked example: publication with atomics

```cpp
struct Snapshot { std::vector<int> data; };
std::atomic<std::shared_ptr<const Snapshot>> current;   // C++20, not in libc++; may use a lock

void publish(std::vector<int> d) {
    current.store(std::make_shared<const Snapshot>(Snapshot{std::move(d)}));   // seq_cst
}
int read_first() {
    auto s = current.load();           // reader holds its own reference; no data race
    return s && !s->data.empty() ? s->data.front() : -1;
}
```

Readers never see a half-built snapshot because the object is fully constructed before the
store and is immutable afterwards. Check `current.is_lock_free()` before using this on a
latency-critical path; libstdc++ implements it with a small spinlock, so an RCU or hazard-pointer
scheme (C++26 `<rcu>`, `<hazard_pointer>`, or folly) may be needed there.
Portability: libc++ (Apple Clang, so macOS) does not implement `std::atomic<std::shared_ptr>`
(P0718). Gate on `__cpp_lib_atomic_shared_ptr`; otherwise use a mutex-guarded `shared_ptr`,
`std::atomic_load`/`std::atomic_store` on a plain `std::shared_ptr` (deprecated in C++20, removed
in C++26), or `folly::atomic_shared_ptr` / `boost::atomic_shared_ptr`.

## Delegation hints

- Sanitizer findings with unclear root cause: `debugger` with the path of the saved report
  (`... 2>&1 | tee .stack/out/<agent>/<YYYYMMDD-HHMM>-asan.log`) and the reproducer command;
  never paste the report into the brief.
- Hot-loop vectorization and layout work with a benchmark target: `code-optimizer`.
- Memory-safety review of parsers and network-facing code: `security-auditor`.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `cmake-presets` | creating, fixing or modernizing a CMake build |
| `cpp-concurrency-atomics` | C++ concurrency and the memory model: choosing mutex, atomic, condition variable, latch or semaphore; memory orders with publication patterns; lock disciplin... |
| `cpp-memory-raii` | designing C++ classes or APIs, fixing leaks, or reviewing ownership |
| `cpp-simd-performance` | a C++ hot path, allocation pattern or vectorization needs a measured speedup |
| `cpp-templates-concepts` | writing or debugging templates, concepts, ranges pipelines or compile-time code |
| `cpp-testing-fuzzing` | adding or restructuring C++ tests, or fuzzing a parser or decoder |
| `cpp-ub-sanitizers` | Hunting undefined behavior in C and C++: a UB catalogue by category; ASan, UBSan, TSan and MSan plus Clang's TySan and RTSan with their runtime options; hard... |
