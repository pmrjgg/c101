# Ranges adaptors: availability, semantics, custom views

## Availability (C++23 adaptors and `ranges::to`)

Versions from cppreference's compiler-support tables (October 2026; "-" = no release listed). "libc++ local" is a probe
of Apple clang 21 with libc++ 22 (`clang++ -std=c++2c -fsyntax-only`); Apple's libc++ can lag
upstream. Gate production code on the macro, not on a compiler version.

| Facility | Paper | libstdc++ | libc++ | MSVC STL | libc++ local | Macro |
|---|---|---|---|---|---|---|
| `ranges::to` | P1206R7 | 14 partial, 15 | 17 | 19.34 | yes | `__cpp_lib_ranges_to_container` |
| `views::enumerate` | P2164R9 | 13 | 23 | 19.37 | no | `__cpp_lib_ranges_enumerate` |
| `views::zip`, `zip_transform`, `adjacent`, `adjacent_transform`, `pairwise` | P2321R2 | 13 | 15 partial, 22 | 19.37 | `zip`, `adjacent`, `pairwise` yes | `__cpp_lib_ranges_zip` |
| `views::chunk`, `views::slide` | P2442R1 | 13 | - | 19.33 | no | `__cpp_lib_ranges_chunk`, `__cpp_lib_ranges_slide` |
| `views::chunk_by` | P2443R1 | 13 | 18 | 19.33 | yes | `__cpp_lib_ranges_chunk_by` |
| `views::join_with` | P2441R2 | 13 | 21 | 19.34 | yes | `__cpp_lib_ranges_join_with` |
| `views::cartesian_product` | P2374R4 | 13 | - | 19.37 | no | `__cpp_lib_ranges_cartesian_product` |
| `views::stride` | P1899R3 | 13 | 23 | 19.34 | no | `__cpp_lib_ranges_stride` |
| `views::repeat` | P2474R2 | 13 | 17 | 19.36 | yes | `__cpp_lib_ranges_repeat` |
| `views::as_rvalue` | P2446R2 | 13 | 16 | 19.34 | yes | `__cpp_lib_ranges_as_rvalue` |
| `views::as_const` | P2278R4 | 13 | - | 19.36 | no | `__cpp_lib_ranges_as_const` |
| `views::cache_latest` (C++26) | P3138 | - | - | - | no | `__cpp_lib_ranges_cache_latest` (202411L) |
| `views::concat` (C++26) | P2542 | - | - | - | no | `__cpp_lib_ranges_concat` |

Polyfills when the library lacks an adaptor: range-v3 (`ranges::views::enumerate`, `chunk`,
`sliding`, `cartesian_product`), or a hand-written loop; do not mix range-v3 views and `std::`
views in one pipeline.

## What each adaptor does and how it bites

| Adaptor | Result | Gotcha |
|---|---|---|
| `filter(p)` | elements satisfying `p` | caches `begin()`: not const-iterable; modifying an element so it fails `p` is UB; `p` must be pure (equality-preserving) |
| `transform(f)` | `f(x)` per element | `f` runs on every dereference: twice per passing element when a `filter` follows; yields whatever `f` returns (usually prvalues: no addresses, no in-place mutation) |
| `take(n)` / `drop(n)` | prefix / suffix | `drop` on a non-random-access range walks `n` steps on `begin()` (cached) |
| `take_while(p)` / `drop_while(p)` | prefix while `p` | `drop_while` caches `begin()` like `filter` |
| `split(d)` / `lazy_split(d)` | subranges | `split` needs a forward range; subranges are `std::ranges::subrange`, convert with `std::string_view(sr.begin(), sr.end())` |
| `join` | flattens a range of ranges | inner ranges that are prvalues are cached once per outer element |
| `join_with(d)` | flattens with a delimiter | C++23 |
| `keys`, `values`, `elements<N>` | tuple element projection | `views::keys` over `std::map` |
| `reverse` | reversed view | needs a bidirectional range; `begin()` walks to the end once and caches it when the range is not common |
| `common` | same iterator and sentinel type | for passing to legacy algorithms expecting `begin/end` of one type |
| `enumerate` | `(index, ref)` tuples | index type is the range's difference type |
| `zip(a, b, ...)` | tuples of references | stops at the shortest; `zip_transform(f, a, b)` applies `f` |
| `adjacent<N>`, `pairwise` | sliding tuples of N neighbours | N is a compile-time constant; `slide(n)` is the run-time variant |
| `chunk(n)` | non-overlapping subranges of n | input ranges yield single-pass chunks |
| `chunk_by(pred)` | split where `pred(a, b)` is false | `chunk_by(std::ranges::less_equal{})` gives non-decreasing runs |
| `stride(n)` | every nth element | |
| `cartesian_product(a, b)` | all pairs | size = product of sizes: watch overflow and cost |
| `repeat(v, n)` | `v` n times (or forever) | combine with `take` when unbounded |
| `as_rvalue` | moves elements out | use with `ranges::to` to move-construct the result |
| `as_const` | read-only references | |
| `cache_latest` (C++26) | caches the last dereferenced value | put between an expensive `transform` and a `filter` |

## Lifetime rules

1. A view must not outlive the range it refers to. `owning_view` (from `views::all` on an
   rvalue container, C++20 P2415) is the exception: `auto v = make_vector() | views::filter(p);`
   owns the vector and is safe to return.
2. Algorithms called on an rvalue, non-borrowed range return `std::ranges::dangling` instead of
   an iterator: the compiler rejects dereferencing it. Borrowed ranges (`std::span`,
   `std::string_view`, `subrange`, `views::iota`, types opting into `enable_borrowed_range`)
   return real iterators.
3. Store views as data members only when the owner of the underlying range provably outlives
   them; otherwise store the container and build the view on demand.
4. Pass views to functions by value (they are cheap to copy) or as `auto&&`/`R&&` templates;
   `const V&` breaks caching views like `filter` and `drop_while`.

## Custom view skeleton

Compiled and ran with Apple clang 21 (`-std=c++23 -Wall -Wextra`): prints `0 9 36 81`.

```cpp
class step_view : public std::ranges::view_interface<step_view> {   // provides empty(), front(), ...
public:
    class iterator {
    public:
        using value_type = long;                    // both required for std::input_iterator
        using difference_type = std::ptrdiff_t;
        iterator() = default;                       // required for std::forward_iterator
        iterator(long cur, long step) : cur_(cur), step_(step) {}
        long operator*() const { return cur_; }     // const operator* is required
        iterator& operator++() { cur_ += step_; return *this; }
        iterator operator++(int) { auto tmp = *this; ++*this; return tmp; }
        friend bool operator==(const iterator&, const iterator&) = default;
    private:
        long cur_ = 0, step_ = 1;
    };
    struct sentinel {
        long last = 0;
        friend bool operator==(const iterator& it, const sentinel& s) { return *it >= s.last; }
    };
    step_view() = default;                          // views must be default-initializable or movable
    step_view(long first, long last, long step) : first_(first), last_(last), step_(step) {}
    iterator begin() const { return {first_, step_}; }
    sentinel end() const { return {last_}; }
private:
    long first_ = 0, last_ = 0, step_ = 1;
};
// iterators do not point into the view object, so results of algorithms on temporaries are safe
template <> inline constexpr bool std::ranges::enable_borrowed_range<step_view> = true;

static_assert(std::forward_iterator<step_view::iterator>);
static_assert(std::sentinel_for<step_view::sentinel, step_view::iterator>);
static_assert(std::ranges::forward_range<step_view> && std::ranges::view<step_view>);

struct squares_fn : std::ranges::range_adaptor_closure<squares_fn> {   // C++23: makes it pipeable
    template <std::ranges::viewable_range R>
    constexpr auto operator()(R&& r) const {
        return std::views::transform(std::forward<R>(r), [](auto x) { return x * x; });
    }
};
inline constexpr squares_fn squares{};

auto v = step_view{0, 10, 3} | squares | std::ranges::to<std::vector>();   // {0, 9, 36, 81}
auto it = std::ranges::find(step_view{0, 100, 7}, 21);                     // borrowed: *it == 21
```

Checklist for a new view: `static_assert` the iterator and range concepts you promise;
`begin()`/`end()` const when they do not cache; if `begin()` must cache, provide only the
non-const overload (and document that the view is not const-iterable); declare
`enable_borrowed_range` only when iterators survive the view's destruction.
