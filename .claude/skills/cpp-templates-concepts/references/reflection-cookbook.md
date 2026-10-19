# C++26 static reflection cookbook and fallbacks

Status (October 2026): P2996R13 reflection, P1306R5 expansion statements (`template for`),
P3491 `define_static_*`, P3096 parameter reflection, P3394 annotations and P3293 base splicing
were adopted for C++26 in June 2025. GCC 16 implements them behind `-std=c++26 -freflection`;
upstream Clang/libc++ support was being merged during 2026, with Bloomberg's `clang-p2996` fork
as the long-standing implementation; MSVC has none listed. The listings below follow the
adopted paper text and were **not compiled here**: compile them against your toolchain before
relying on them, and keep the fallback path.

## Gate and build

```cpp
#if defined(__cpp_impl_reflection) && __has_include(<meta>)
#  include <meta>
#  define PROJECT_HAS_REFLECTION 1
#else
#  define PROJECT_HAS_REFLECTION 0
#endif
```

```bash
g++-16 -std=c++26 -freflection -c reflect.cpp      # GCC 16
```

`__cpp_impl_reflection` is predefined by the compiler only when reflection is enabled; GCC moved
its value from 202506L to 202603L during 2026, so test for presence, not a specific value.

## Vocabulary

| Construct | Meaning |
|---|---|
| `^^T`, `^^ns::f`, `^^obj` | reflect an entity into a `std::meta::info` constant |
| `[: r :]` | splice back an expression; `typename [: r :]` for a type, `template [: r :]` for a template |
| `obj.[: m :]` | access the member reflected by `m` |
| `template for (constexpr auto x : R)` | expansion statement: the body is instantiated once per element |
| `std::define_static_array(vec)` | turns a consteval `std::vector<info>` into static storage usable by `template for` |
| `std::meta::access_context::current()` / `unprivileged()` / `unchecked()` | which members a query may see |

Metafunctions used most (all `consteval`):

| Function | Returns |
|---|---|
| `enumerators_of(info enum_type)` | `std::vector<info>` in declaration order |
| `members_of(info r, access_context ctx)` | all members |
| `nonstatic_data_members_of(info type, access_context ctx)` | data members in declaration order |
| `static_data_members_of(info type, access_context ctx)` | static data members |
| `identifier_of(info r)` / `has_identifier(info r)` | `std::string_view` name / whether one exists |
| `display_string_of(info r)` | human-readable description, for diagnostics only |
| `type_of(info r)` | reflection of the entity's type |
| `is_enumerable_type(info r)` | whether `enumerators_of` may be called (complete enum) |

## Enum to string and back

```cpp
template <class E, bool Enumerable = std::meta::is_enumerable_type(^^E)>
    requires std::is_enum_v<E>
constexpr std::string_view enum_to_string(E value) {
    if constexpr (Enumerable)
        template for (constexpr auto e : std::define_static_array(std::meta::enumerators_of(^^E)))
            if (value == [:e:]) return std::meta::identifier_of(e);
    return "<unnamed>";
}

template <class E>
    requires std::is_enum_v<E>
constexpr std::optional<E> enum_from_string(std::string_view name) {
    template for (constexpr auto e : std::define_static_array(std::meta::enumerators_of(^^E)))
        if (name == std::meta::identifier_of(e)) return [:e:];
    return std::nullopt;
}

template <class E>
constexpr std::size_t enum_count = std::meta::enumerators_of(^^E).size();   // transient vector
```

Unlike `magic_enum`, this has no value-range limit and handles values far outside -128..127
and duplicate values (it returns the first matching enumerator's name).

## Walking a struct

```cpp
template <class T>
void dump(const T& obj) {
    constexpr auto ctx = std::meta::access_context::unchecked();      // include private members
    template for (constexpr auto m :
                  std::define_static_array(std::meta::nonstatic_data_members_of(^^T, ctx)))
        std::println("{} = {}", std::meta::identifier_of(m), obj.[:m:]);
}

struct Point { int x; double y; };
static_assert(std::meta::nonstatic_data_members_of(^^Point,
              std::meta::access_context::unchecked()).size() == 2);
```

Use `access_context::current()` in library code so a function only sees members accessible at
the call site; `unchecked()` deliberately bypasses access control and belongs in serializers
that are part of the type's own contract.

Typical uses: serialization (JSON, binary), hashing all members, equality and ordering for
aggregates, command-line parsers generated from a struct, struct-of-arrays transforms,
debug printers. Keep the generated code in one header and test it with `static_assert`s.

## Fallbacks without standard reflection

| Need | Library | API | Limits |
|---|---|---|---|
| enum name and parse | magic_enum (`#include <magic_enum/magic_enum.hpp>`) | `magic_enum::enum_name(e)`, `enum_cast<E>("RED")`, `enum_values<E>()`, `enum_count<E>()`, `enum_contains<E>(v)` | compiler-specific `__PRETTY_FUNCTION__` scan of `MAGIC_ENUM_RANGE_MIN..MAX` (default -128..127, per-enum override via `magic_enum::customize::enum_range<E>`); compile time grows with the range; newer releases use standard reflection automatically when available |
| aggregate fields | Boost.PFR (`#include <boost/pfr.hpp>`, C++14+) | `boost::pfr::for_each_field(obj, f)`, `boost::pfr::get<I>(obj)`, `boost::pfr::tuple_size_v<T>`, `boost::pfr::get_name<I, T>()` and `names_as_array<T>()` (C++20 builds) | aggregates only (no base classes, no user-declared constructors); names need a C++20 build |
| anything else | X-macros or a hand-written `visit_fields(T&, F)` per type | code generation | must be kept in sync by hand: add a `static_assert(sizeof(T) == ...)` tripwire |

```cpp
// magic_enum
enum class Color { red, green, blue };
static_assert(magic_enum::enum_name(Color::green) == "green");
auto c = magic_enum::enum_cast<Color>("blue");                  // std::optional<Color>

// Boost.PFR
struct Point { int x; double y; };
double sum = 0;
boost::pfr::for_each_field(Point{1, 2.5}, [&](const auto& f) { sum += f; });   // 3.5
static_assert(boost::pfr::tuple_size_v<Point> == 2);
```

Migration path: put the fallback and the reflection version behind one project function
(`project::enum_name(e)`, `project::for_each_member(obj, f)`), select by
`PROJECT_HAS_REFLECTION`, and run the same unit tests in both configurations.
