---
name: cpp-templates-concepts
description: "C++ generic and compile-time programming: concepts and requires-clauses with subsumption, if constexpr and folds, deducing this, CTAD and class-type NTTPs, constexpr/consteval/constinit, ranges and view-lifetime rules, C++26 static reflection, and keeping compile times under control. Load when writing or debugging templates, concepts, ranges pipelines or compile-time code."
when_to_use: "Template-heavy .hpp/.cpp/.cppm code; errors like 'constraints not satisfied', 'call to ... is ambiguous', 'deduced conflicting types', 'not a constant expression', 'std::ranges::dangling', 'function is not marked const' on a filter_view; replacing enable_if, tag dispatch or CRTP; ranges pipelines; enum-to-string or struct walking; builds dominated by template instantiation."
---

# C++ templates, concepts and compile-time code

Baseline: C++20 concepts and ranges everywhere; C++23 deducing `this`, `ranges::to`, `if consteval`
where the toolchain has them; C++26 reflection only behind its macro. Versions that matter:

| Feature | GCC | Clang | MSVC | Gate |
|---|---|---|---|---|
| deducing `this` (P0847) | 14 | 18 | 19.32 partial, 19.43 | `__cpp_explicit_this_parameter` |
| range-for temporary lifetime (P2718) | 15 | 19 | 19.51 | `__cpp_range_based_for >= 202211L` |
| `std::ranges::to` (P1206) | 14 partial, 15 (libstdc++) | 17 (libc++) | 19.34 | `__cpp_lib_ranges_to_container` |
| pack indexing `Ts...[0]` (P2662) | 15 | 19 | - | `__cpp_pack_indexing` |
| static reflection (P2996) + `template for` (P1306) | 16, `-std=c++26 -freflection` | upstreaming in progress; Bloomberg `clang-p2996` fork | - | `__cpp_impl_reflection`, `__cpp_lib_reflection` |

Deep material: [ranges adaptors, availability and custom views](references/ranges-adaptors.md) |
[C++26 reflection cookbook and fallbacks](references/reflection-cookbook.md)

## 1. Constrain every template

Pick the weakest standard concept that admits the algorithm:

| Requirement | Concept |
|---|---|
| arithmetic | `std::integral`, `std::signed_integral`, `std::unsigned_integral`, `std::floating_point` |
| type relations | `std::same_as`, `std::derived_from`, `std::convertible_to`, `std::common_with` |
| value semantics | `std::movable`, `std::copyable`, `std::semiregular`, `std::regular` |
| comparison | `std::equality_comparable`, `std::totally_ordered`, `std::three_way_comparable` |
| callables | `std::invocable<F, Args...>`, `std::regular_invocable`, `std::predicate`, `std::strict_weak_order<R, T, U>` |
| iterators | `std::input_iterator` < `forward_` < `bidirectional_` < `random_access_` < `contiguous_iterator`; `std::sentinel_for` |
| algorithm plumbing | `std::indirect_strict_weak_order<C, std::projected<I, Proj>>`, `std::indirect_unary_predicate`, `std::sortable`, `std::mergeable` |
| ranges | `std::ranges::input_range` (single pass), `forward_range` (multi-pass, may return iterators), `random_access_range`, `contiguous_range` (`data()`), `sized_range`, `borrowed_range`, `view`, `viewable_range` |

Custom concepts name a semantic requirement and are built from standard ones; a concept that
only lists syntax (`HasBegin`) is a smell:

```cpp
template <class T>
concept Hashable = std::regular<T> && requires(const T& t) {
    { std::hash<T>{}(t) } -> std::convertible_to<std::size_t>;
};
```

Subsumption picks the more constrained overload only when constraints are built from the
**same named concepts** (atomic constraints are identical only if they come from the same
concept definition). Checked on Clang 21:

```cpp
template <class T> concept Shape = requires(const T& s) { { s.area() } -> std::convertible_to<double>; };
template <class T> concept Solid = Shape<T> && requires(const T& s) { { s.volume() } -> std::convertible_to<double>; };
const char* describe(const Shape auto&) { return "shape"; }
const char* describe(const Solid auto&) { return "solid"; }   // Cube{} -> "solid": Solid subsumes Shape
// The same requirements spelled as two ad-hoc requires-expressions -> "call to 'f' is ambiguous".
```

Rules: put constraints in concepts, not repeated `requires requires`; disjunctions (`||`) weaken
subsumption; test your own types at the boundary, because iterators silently fail concepts
(missing `value_type`/`difference_type`, non-`const` `operator*`, missing post-increment):

```cpp
static_assert(std::forward_iterator<MyIter>);
static_assert(std::ranges::random_access_range<MyView> && std::ranges::view<MyView>);
```

## 2. Modernize legacy idioms

| Legacy | Modern | Notes |
|---|---|---|
| `std::enable_if_t<cond, int> = 0` | `requires cond` / constrained parameter | clang-tidy `modernize-use-constraints`; `bugprone-incorrect-enable-if` for broken legacy ones |
| tag dispatch on `iterator_category` | `if constexpr (std::random_access_iterator<I>)` | the discarded branch is not instantiated (templates only) |
| `void_t` detection idiom | `if constexpr (requires { t.reserve(n); })` | inline requires-expression |
| recursive variadic `print(T, Rest...)` | fold: `((os << args << ' '), ...);` / `(... + xs)` | no recursion depth, faster compiles |
| recursive `std::tuple_element` / `std::get` tricks to pick the I-th pack element | C++26 pack indexing `Ts...[I]`, `args...[0]` | GCC 15, Clang 19 |
| `std::is_same<T, U>::value`, `std::decay<T>::type` | `std::is_same_v`, `std::same_as`, `std::remove_cvref_t` | `modernize-type-traits` |
| CRTP `static_cast<Derived&>(*this)` | deducing this: `template <class Self> auto f(this Self&& self)` | section 9 |
| const / non-const / `&&` getter triplets | one deducing-this getter | below |

```cpp
struct Text {
    std::string s;
    template <class Self>
    auto&& str(this Self&& self) { return std::forward<Self>(self).s; }
};
// t.str() -> std::string&, std::as_const(t).str() -> const std::string&, std::move(t).str() -> std::string&&
```

Deducing-this rules: `Self` is the static type of the object expression (a derived class when
called on one); there is no `this` inside, use `self.`; the function cannot be `virtual`,
`static`, or cv/ref-qualified; `this auto self` (by value) copies the object, which is what
coroutine lambdas need (`cpp-concurrency-atomics`) and enables recursive lambdas:
`auto fib = [](this auto self, int n) -> int { return n < 2 ? n : self(n - 1) + self(n - 2); };`

## 3. Deduction control

- CTAD: `std::vector v{1, 2, 3};`, `std::scoped_lock lk(m1, m2);`. Write deduction guides for
  constructors whose parameters do not name the class parameters:
  `template <class It> Buffer(It, It) -> Buffer<std::iter_value_t<It>>;`
- CTAD trap (checked): `std::vector b{a.begin(), a.end()};` deduces
  `std::vector<std::vector<int>::iterator>` (braces prefer `initializer_list`);
  `std::vector c(a.begin(), a.end());` deduces `std::vector<int>`; `std::vector e{a};` copies.
- Class-type non-type template parameters (C++20) take structural literal types (all members
  public and structural, no `mutable`); floating-point NTTPs are allowed too:

```cpp
template <std::size_t N>
struct FixedString {
    char data[N]{};
    consteval FixedString(const char (&s)[N]) { std::ranges::copy(s, data); }
    constexpr std::string_view view() const { return {data, N - 1}; }
};
template <FixedString Name> struct Metric { static constexpr std::string_view name = Name.view(); };
static_assert(Metric<"latency_ms">::name == "latency_ms");
```

- `template <auto V>` (C++17) accepts any NTTP type: `constant<42>`, `constant<&f>`.
- Block deduction from one argument with `std::type_identity_t<T>` (C++20):
  `template <class T> void fill(std::vector<T>& v, std::type_identity_t<T> value);` lets
  `fill(doubles, 1)` compile; without it Clang reports
  "deduced conflicting types for parameter 'T' ('double' vs. 'int')".

## 4. Compile-time work

| Tool | Use | Checked behaviour |
|---|---|---|
| `constexpr` function | runs at compile time when a constant is required | UB in a constant evaluation is a hard error: `static_assert(add(INT_MAX, 1) > 0)` fails with "value 2147483648 is outside the range of representable values of type 'int'" |
| transient allocation (C++20) | `std::vector`/`std::string` inside constexpr code | allocation must be freed before evaluation ends: copy results into `std::array` |
| `consteval` | must run at compile time: checked IDs, units, format strings | `throw` on a bad input makes the call "not a constant expression" |
| `std::format_string` | `std::format("{:d}", "text")` | rejected at compile time (consteval constructor) |
| `if consteval` (C++23) | separate compile-time and run-time implementations | replaces `std::is_constant_evaluated()`; consteval calls allowed only in the first branch |
| `constinit` | guarantee static (not dynamic) initialisation of a global | fixes the static-init-order fiasco for that variable; still mutable, so `const` or atomic for threads |

```cpp
constexpr auto sorted_squares(std::array<int, 4> in) {
    std::vector<int> v(in.begin(), in.end());          // transient heap allocation
    for (int& x : v) x *= x;
    std::ranges::sort(v);
    std::array<int, 4> out{};
    std::ranges::copy(v, out.begin());                 // nothing allocated escapes
    return out;
}
static_assert(sorted_squares({3, -1, 2, 0}) == std::array{0, 1, 4, 9});

struct EventId {
    std::uint32_t value = 0;
    consteval EventId(std::string_view s) {
        if (s.empty() || s.size() > 16) throw "event id must be 1..16 chars";   // compile error
        for (char c : s) value = value * 31 + static_cast<unsigned char>(c);
    }
};
constexpr EventId kLogin{"login"};
```

Use `static_assert` tests over constexpr code as free UB checks: overflow, out-of-bounds,
use of an inactive union member and reads of uninitialised values are rejected during constant
evaluation. Limits when evaluation is legitimately heavy: Clang `-fconstexpr-steps=N`
(default 1048576), GCC `-fconstexpr-ops-limit=N` (default 33554432) and
`-fconstexpr-loop-limit=N` (default 262144).

## 5. Ranges

- Views are lazy and non-owning (except `owning_view` over an rvalue). Never return a view over
  a local container or temporary. Algorithms return `std::ranges::dangling` for non-borrowed
  rvalue ranges: `*std::ranges::max_element(make_vector())` fails with
  "indirection requires pointer operand (... 'std::ranges::dangling' invalid)".
- Materialise with `| std::ranges::to<std::vector>()` (C++23) or
  `std::ranges::to<std::vector<std::string>>()`; until then, construct from `begin()`/`end()` of a
  `common_view`.
- `views::filter` caches `begin()` (amortised O(1)): a filter view is not iterable through
  `const&` (Clang: "'this' argument to member function 'begin' has type 'const
  std::ranges::filter_view<...>', but function is not marked const"). Pass views by value or
  `auto&&`. Modifying an element through a filter iterator so it fails the predicate is UB.
- `transform | filter` runs the transform again on dereference: measured 6 calls for 4 elements
  with 2 passing. Keep transforms cheap and pure; filter first when possible; C++26
  `views::cache_latest` (`__cpp_lib_ranges_cache_latest`, 202411L) between the stages.
- Projections replace comparator lambdas: `std::ranges::sort(people, {}, &Person::age);`,
  `std::ranges::find(people, "bob", &Person::name);`.
- C++23 adaptors: `enumerate`, `zip`, `zip_transform`, `adjacent`, `chunk`, `slide`, `chunk_by`,
  `join_with`, `stride`, `cartesian_product`, `repeat`, `as_rvalue`, `as_const`. libc++ lags
  (Apple clang 21 / libc++ 22 checked: no `enumerate`, `chunk`, `slide`, `stride`,
  `cartesian_product`, `as_const`); gate on `__cpp_lib_ranges_*`. Table in
  [ranges-adaptors](references/ranges-adaptors.md).
- Custom views: derive from `std::ranges::view_interface<D>` (provides `empty`, `front`, `size`
  ...), opt into `std::ranges::enable_borrowed_range` only if iterators do not point into the
  view object; make your adaptor pipeable with `std::ranges::range_adaptor_closure<F>` (C++23).
- Pre-P2718 compilers: `for (auto x : make().items())` dangles; bind `auto&& tmp = make();`.

## 6. C++26 static reflection

Gate everything: `#if defined(__cpp_impl_reflection)` + `#include <meta>`. Syntax: `^^T` makes a
`std::meta::info`; `[: r :]` splices it back (`typename [: r :]` for types). Iterate with an
expansion statement over `std::define_static_array(...)`. Follows P2996R13 as adopted; not
compiled here (no GCC 16 on this machine):

```cpp
template <class E, bool Enumerable = std::meta::is_enumerable_type(^^E)>
    requires std::is_enum_v<E>
constexpr std::string_view enum_to_string(E value) {
    if constexpr (Enumerable)
        template for (constexpr auto e : std::define_static_array(std::meta::enumerators_of(^^E)))
            if (value == [:e:]) return std::meta::identifier_of(e);
    return "<unnamed>";
}

template <class T>
void dump(const T& obj) {                              // walk the data members
    constexpr auto ctx = std::meta::access_context::unchecked();   // or ::current()
    template for (constexpr auto m :
                  std::define_static_array(std::meta::nonstatic_data_members_of(^^T, ctx)))
        std::println("{} = {}", std::meta::identifier_of(m), obj.[:m:]);
}
```

`members_of`, `nonstatic_data_members_of` and `static_data_members_of` take an
`access_context` second argument; `enumerators_of`, `identifier_of`, `display_string_of`,
`type_of` take one `info`. Fallbacks without reflection: `magic_enum::enum_name(e)` (scans
`MAGIC_ENUM_RANGE_MIN..MAX`, default -128..127, via `__PRETTY_FUNCTION__`; switches to standard
reflection automatically when available) and Boost.PFR for aggregates
(`boost::pfr::for_each_field`, `boost::pfr::get<I>`, `boost::pfr::get_name<I, T>()`). More in
[reflection-cookbook](references/reflection-cookbook.md).

## 7. Diagnostics hygiene

1. Constrain at the API boundary so failures report at the call site with the concept chain
   (section 9 shows the exact Clang output), not 40 frames inside an algorithm.
2. `static_assert` with a message at the top of complex class templates:
   `static_assert(std::is_nothrow_move_constructible_v<T>, "Ring<T> needs a noexcept move");`
3. Flags: `-ftemplate-backtrace-limit=0` (full instantiation chain; GCC default 10),
   Clang `-fdiagnostics-show-template-tree` and `-fno-elide-type` for type diffs, GCC
   `-fconcepts-diagnostics-depth=N` to expand failed concept checks; GCC 16 nests template errors
   (`-fno-diagnostics-show-nesting` restores the flat form).
4. Minimal repro on Compiler Explorer (godbolt.org) against GCC, Clang and MSVC trunk before
   filing or working around a "compiler bug": most turn out to be ill-formed code one compiler
   accepted.
5. Put `static_assert(Concept<MyType>)` checks in a test TU so a refactor that breaks modelling
   fails in CI, not in a user's build.

## 8. Compile-time cost control

| Lever | How | When |
|---|---|---|
| measure first | Clang `-ftime-trace` (`-ftime-trace-granularity=<us>`, default 500) per TU, then `ClangBuildAnalyzer --all <build-dir> cap.bin && ClangBuildAnalyzer --analyze cap.bin`; GCC `-ftime-report`; MSVC `vcperf` (C++ Build Insights) | always, before changing anything |
| explicit instantiation | header: `extern template class Matrix<double>;` one .cpp: `template class Matrix<double>;` | a few heavy instantiations used in many TUs |
| shallower instantiation | folds and pack expansion instead of recursion; `[]<std::size_t... I>(std::index_sequence<I...>) { ... }(std::make_index_sequence<N>{})`; pack indexing instead of recursive `tuple_element` | deep recursion (GCC `-ftemplate-depth` default 900) |
| fewer heavy includes | forward declarations, pimpl or type erasure at module boundaries, include-what-you-use | a header shows up in every TU's trace |
| precompiled headers | CMake `target_precompile_headers(tgt PRIVATE <vector> <string> "big.h")` | stable third-party headers |
| modules | `FILE_SET CXX_MODULES` (CMake 3.28+, Ninja); see `cmake-presets` | new code, toolchains that support them |
| unity builds | `CMAKE_UNITY_BUILD=ON` | many small TUs; watch for anonymous-namespace collisions |

ClangBuildAnalyzer ranks the slowest files, template instantiations ("Templates that took
longest to instantiate") and headers; fix the top three, re-measure, stop when gains flatten.

## 9. Worked example: constrained max_by, then CRTP to deducing this

Part 1: `max_by` with a projection and an optional comparator, constrained like the standard
algorithms so misuse fails at the call site.

```cpp
template <std::ranges::forward_range R,                       // max_element returns an iterator
          class Proj = std::identity,
          std::indirect_strict_weak_order<std::projected<std::ranges::iterator_t<R>, Proj>>
              Comp = std::ranges::less>
    requires std::copy_constructible<std::ranges::range_value_t<R>>
constexpr std::optional<std::ranges::range_value_t<R>> max_by(R&& r, Proj proj = {}, Comp comp = {}) {
    auto it = std::ranges::max_element(r, comp, proj);        // first maximal element
    if (it == std::ranges::end(r)) return std::nullopt;       // empty range: no precondition
    return *it;
}

static_assert(max_by(std::vector{3, 9, 4}) == 9);
static_assert(!max_by(std::vector<int>{}).has_value());
static_assert(*max_by(std::vector{-7, 2, 5}, [](int x) { return x * x; }) == -7);
static_assert(*max_by(std::vector{1, 5, 3}, {}, std::ranges::greater{}) == 1);
// runtime: max_by(people, &Person::age)->name == "bob"; works on std::list (forward_range) too
```

Calling it on `std::vector<Opaque>` (no `operator<`) fails at the call, Clang 21:

```text
error: no matching function for call to 'max_by'
note: candidate template ignored: constraints not satisfied [with R = std::vector<Opaque> &, ...]
note: because 'std::indirect_strict_weak_order<std::ranges::less, std::projected<...>>' evaluated to false
note: because 'predicate<std::ranges::less &, Opaque &, Opaque &>' evaluated to false
```

The first draft constrained `R` with `input_range`: it compiled for vectors but promised to accept
single-pass ranges that `max_element` rejects deep inside. The constraint must match what the
body needs.

Part 2: a fluent-builder CRTP mixin, before:

```cpp
using Headers = std::vector<std::pair<std::string, std::string>>;
template <class Derived>
class FluentCrtp {
public:
    Derived& timeout(std::chrono::milliseconds t) { self().timeout_ = t; return self(); }
    Derived& header(std::string k, std::string v) {
        self().headers_.emplace_back(std::move(k), std::move(v));
        return self();
    }
private:
    Derived& self() { return static_cast<Derived&>(*this); }
    FluentCrtp() = default;
    friend Derived;                 // stops `struct B : FluentCrtp<A>` typos from compiling
};
struct OldRequest : FluentCrtp<OldRequest> { std::chrono::milliseconds timeout_{1000}; Headers headers_; };
```

After (C++23): no template parameter on the base, rvalue chains move, further-derived classes
get their own type back.

```cpp
struct Fluent {
    template <class Self>
    Self&& timeout(this Self&& self, std::chrono::milliseconds t) {
        self.timeout_ = t;
        return std::forward<Self>(self);
    }
    template <class Self>
    Self&& header(this Self&& self, std::string k, std::string v) {
        self.headers_.emplace_back(std::move(k), std::move(v));
        return std::forward<Self>(self);
    }
};
struct Request : Fluent { std::chrono::milliseconds timeout_{1000}; Headers headers_; };
struct TracedRequest : Request { std::string trace_id; };

auto r = Request{}.timeout(250ms).header("Accept", "json");     // moved out of the temporary
TracedRequest t; t.timeout(5ms).trace_id = "abc";               // Self = TracedRequest&
static_assert(std::same_as<decltype(Request{}.timeout(1ms)), Request&&>);
static_assert(std::same_as<decltype(t.header("a", "b")), TracedRequest&>);
```

Both parts compiled warning-free with `clang++ -std=c++23 -Wall -Wextra` (Apple clang 21) and
printed the expected values. Caveats: `auto&& x = Request{}.timeout(1s);` dangles (it binds to
the temporary); the base can only touch members the derived class makes accessible (as with
CRTP); add a trailing `requires requires { self.timeout_; }` so misuse fails with "no member named
'timeout_' in 'NoTimeout'" at the call (checked).

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| error 40 frames deep in `<algorithm>` | unconstrained template | constrain with the same concepts the body needs |
| "call to ... is ambiguous" between constrained overloads | ad-hoc requires-expressions do not subsume | factor into named concepts that build on each other |
| `std::vector{it1, it2}` holds iterators | braced CTAD prefers `initializer_list` | parentheses, or spell the type |
| "deduced conflicting types for parameter 'T'" | `T` deduced from two arguments | `std::type_identity_t<T>` on the secondary parameter |
| `if constexpr` branch still fails to compile | condition not dependent, or code outside a template | make it depend on a template parameter; `static_assert(false, "...")` in a discarded branch needs P2593 (accepted by Clang 21 even in C++20 mode; older compilers need a dependent false) |
| forwarding constructor hijacks copy | `template <class U> X(U&&)` beats `X(const X&)` for non-const lvalues | constrain: `requires (!std::same_as<std::remove_cvref_t<U>, X>)` |
| filter view "not marked const" | filter caches `begin()` | take views by value or `auto&&` |
| garbage from a returned view | view over a local container | return the container, or `ranges::to` |
| expensive transform runs twice | `transform \| filter` dereferences twice | filter first, `cache_latest`, or materialise |
| "constexpr evaluation hit maximum step limit" (Clang) / "operation count exceeds limit" (GCC) | step or depth limit | reduce work or raise `-fconstexpr-steps` / `-fconstexpr-ops-limit` |
| build time explodes after adding a header-only library | instantiation in every TU | `-ftime-trace`, `extern template`, PCH, move use behind a .cpp |

Related: `cpp-memory-raii`, `cpp-concurrency-atomics`, `cpp-ub-sanitizers`, `cmake-presets`,
`cpp-simd-performance`, hub `cpp-craft`.
