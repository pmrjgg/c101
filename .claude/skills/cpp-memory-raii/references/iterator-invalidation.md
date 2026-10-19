# Iterator, reference and pointer invalidation by container

"Iterators" below includes the past-the-end iterator unless stated. "References" covers
references and pointers to elements. When a row says references stay valid but iterators do
not, code that stores `T&`/`T*` is fine and code that stores iterators is not.

## Sequence containers

| Container | Operation | Invalidated |
|---|---|---|
| `vector` | `push_back`, `emplace_back` | reallocation (new size > `capacity()`): everything; otherwise only `end()` |
| `vector` | `insert`, `emplace` | reallocation: everything; otherwise iterators and references at or after the insertion point, and `end()` |
| `vector` | `erase`, `pop_back` | at or after the erased position, and `end()` |
| `vector` | `reserve(n)` | everything if capacity changes; nothing otherwise |
| `vector` | `resize`, `shrink_to_fit` | as insert/erase at the end; `shrink_to_fit` may reallocate (everything) |
| `vector` | `clear`, `assign`, `operator=` | everything (capacity kept by `clear`) |
| `vector` | `swap` | nothing is invalidated, but iterators now refer into the other vector; `end()` may be invalidated |
| `basic_string` | any non-const member except `operator[]`, `at`, `data`, `front`, `back`, `begin`, `rbegin`, `end`, `rend`; any non-member taking it by non-const reference (`swap`, `getline`, `>>`) | may invalidate everything (small-buffer storage moves with the object, so `swap` and move do invalidate) |
| `deque` | `push_front`, `push_back`, `emplace_front/back` | all iterators; references stay valid |
| `deque` | `insert` / `emplace` in the middle | everything |
| `deque` | erase of the first element only | the erased element only |
| `deque` | erase of the last element | the erased element and `end()` |
| `deque` | erase in the middle | everything |
| `deque` | `shrink_to_fit`, `clear` | everything |
| `list`, `forward_list` | `insert`, `emplace`, `push_*` | nothing |
| `list`, `forward_list` | `erase`, `pop_*`, `remove`, `unique` | erased elements only |
| `list`, `forward_list` | `splice`, `merge` | nothing; moved elements' iterators now refer into the destination |
| `array` | none of its operations reallocate | `swap` swaps element values, iterators keep pointing to the same slot |
| `inplace_vector` (C++26) | `push_back`, `emplace_back`, `try_*`, `unchecked_*`, `append_range` | only `end()` |
| `inplace_vector` | `insert`, `emplace`, `erase`, `pop_back`, `resize`, `clear`, `assign` | at or after the position (assume all for `clear`/`assign`) |
| `inplace_vector` | move construction/assignment, `swap` | all iterators (storage is inline, so it does not travel with the move) |
| `hive` (C++26, reference implementation `plf::hive`) | insert, erase | only erased elements; insertion never invalidates |

## Associative and unordered containers

| Container | Operation | Invalidated |
|---|---|---|
| `map`, `set`, `multimap`, `multiset` | `insert`, `emplace`, `try_emplace`, `insert_or_assign` | nothing |
| ordered associative | `erase` | erased elements only |
| ordered associative | `extract` (C++17) | iterators to the extracted element; references stay valid but must not be used while the node handle owns it |
| ordered associative | `merge` | nothing; transferred elements' iterators now refer into the target |
| `unordered_*` | `insert`, `emplace`, `operator[]` | if a rehash happens (size would exceed `max_load_factor() * bucket_count()`): all iterators, references stay valid; no rehash: nothing |
| `unordered_*` | `rehash`, `reserve` | all iterators; references stay valid |
| `unordered_*` | `erase` | erased elements only |
| `flat_map`, `flat_set` (C++23) | `insert`, `emplace`, `erase` | backed by vectors: assume all iterators and references are invalidated |

Open-addressing maps outside the standard (`absl::flat_hash_map`, `boost::unordered_flat_map`)
invalidate references on rehash as well: elements live in the slot array. Node-based variants
(`absl::node_hash_map`, `boost::unordered_node_map`) keep references stable.

## Views

`std::span`, `std::string_view`, `std::ranges` views and iterators into them are invalidated by
any operation that invalidates the underlying container's iterators, and by the container's
destruction. A view stored in a member is a lifetime contract: document it or store an owner.

## Safe rewrites

| Unsafe pattern | Safe pattern |
|---|---|
| range-for over `v` while `v.push_back(...)` | index loop with the size captured first: `for (std::size_t i = 0, n = v.size(); i < n; ++i)` |
| `auto& first = v[0]; v.push_back(x); use(first);` | copy the value, or `v.reserve(final_size)` before taking the reference and never exceed it |
| `for (auto it = c.begin(); it != c.end(); ++it) if (p(*it)) c.erase(it);` | `std::erase_if(c, p);` (C++20, all standard containers), or `it = c.erase(it)` in the loop without `++it` on erase |
| storing iterators into an `unordered_map` across inserts | store keys, or `reserve()` up front so no rehash happens |
| caching `string_view` into a `std::string` member that is later assigned | store an offset and length, or an owning `std::string` |
| handing out `T*` into a `vector<T>` that grows | `std::deque<T>` (`push_back` keeps references), `std::list`, or a slot map with generation counters |

## Detection

| Tool | Catches | Misses |
|---|---|---|
| ASan | use of memory freed by a reallocation (heap-use-after-free) | stale iterators into memory that is still allocated (insert without reallocation shifting elements) |
| libstdc++ `-D_GLIBCXX_DEBUG` | use of invalidated iterators (safe iterators), mismatched-container comparisons | changes the ABI: debug builds only, whole program |
| MSVC `_ITERATOR_DEBUG_LEVEL=2` (Debug default) | invalidated iterator use | Release builds |
| libc++ hardening (`_LIBCPP_HARDENING_MODE`) | out-of-range access, some iterator checks in debug mode | most invalidation scenarios |
| Clang `-Wdangling*`, GCC `-Wdangling-reference` | views/references to temporaries | runtime invalidation |
