---
name: cpp-memory-raii
description: "C++ resource and value semantics: rule of zero and five, RAII wrappers with custom deleters and std::out_ptr, ownership and parameter-passing tables, a move-semantics checklist, smart-pointer choice, std::expected vs exceptions with safety guarantees, dangling-lifetime pitfalls and std::pmr allocation control. Load when designing C++ classes or APIs, fixing leaks, or reviewing ownership."
when_to_use: "Writing or reviewing .cpp/.hpp/.h code that owns FILE*, file descriptors, sockets or C library handles; choosing unique_ptr, shared_ptr or raw pointers; designing signatures and error returns (std::expected); ASan heap-use-after-free or leak reports; -Wdangling*, -Wpessimizing-move or bugprone-use-after-move findings; std::vector copying on growth; object slicing."
---

# C++ memory, RAII and value semantics

Baseline: C++20 everywhere, C++23 library types where the standard library ships them, C++26
types only behind their feature-test macro. Check availability before writing code against it:

| Facility | Std | libstdc++ | libc++ | MSVC STL | Gate macro |
|---|---|---|---|---|---|
| `std::expected` | 23 | 12 | 16 | 19.33 | `__cpp_lib_expected` |
| `std::out_ptr` / `std::inout_ptr` | 23 | 14 | 19 | 19.30 | `__cpp_lib_out_ptr` |
| `std::move_only_function` | 23 | 12 | - | 19.32 | `__cpp_lib_move_only_function` |
| `std::function_ref`, `std::copyable_function` | 26 | 16 | - | - | `__cpp_lib_function_ref`, `__cpp_lib_copyable_function` |
| `std::optional<T&>` | 26 | 16 | 22 | - | `__cpp_lib_optional_ref` |
| `std::inplace_vector` | 26 | 16 | - | - | `__cpp_lib_inplace_vector` |
| `std::indirect`, `std::polymorphic` | 26 | 16 | - | - | check `<version>` |

"-" = no release listed in cppreference's support tables (October 2026); Apple clang 21 with
libc++ 22 was checked locally: no `move_only_function`, `function_ref` or `inplace_vector`.

Deep material: [iterator invalidation by container](references/iterator-invalidation.md) |
[RAII patterns: generic handle, scope guard, aliasing, pmr-aware types, type erasure](references/raii-patterns.md)

## 1. Rule of zero; rule of five only inside tiny RAII wrappers

Decision procedure for every class:

1. All members already manage themselves (`std::string`, `std::vector`, smart pointers, handle
   wrappers) → **rule of zero**: declare no destructor, copy or move operation.
2. The class must own a raw resource → write a dedicated wrapper that owns exactly one resource
   (rule of five lives there), then use rule of zero in every class that holds the wrapper.
3. Pointer-shaped C handle (`FILE*`, `sqlite3*`, `SSL*`) → `std::unique_ptr<T, Deleter>` with a
   **function-object** deleter. No hand-written wrapper needed.
4. Non-pointer handle (`int` fd, socket, GL name, sentinel-valued `HANDLE`) → a move-only wrapper
   with a traits type for `invalid()` and `close()` (generic version in
   [raii-patterns](references/raii-patterns.md)).
5. Declaring any of destructor/copy/move suppresses the implicit moves: if you declare one, declare
   all five (`= default` / `= delete`). clang-tidy `cppcoreguidelines-special-member-functions`.

```cpp
struct FileCloser { void operator()(std::FILE* f) const noexcept { std::fclose(f); } };
using File = std::unique_ptr<std::FILE, FileCloser>;
static_assert(sizeof(File) == sizeof(std::FILE*));                              // stateless deleter: zero cost
static_assert(sizeof(std::unique_ptr<std::FILE, int (*)(std::FILE*)>) == 2 * sizeof(std::FILE*));
```

Both asserts hold on libc++ (checked). Function-pointer deleters double the size, and forming a
pointer to a standard library function (`&std::fclose`) is unspecified behavior per
[namespace.std]; always wrap the call in a struct.

`std::out_ptr` / `std::inout_ptr` (C++23) adapt C APIs that return a handle through `T**`:

| API shape | Adapter | Behaviour |
|---|---|---|
| `int open(const char*, T** out)` writes a new handle | `std::out_ptr(p)` | temporary converts to `T**` / `void**`; at the end of the full-expression calls `p.reset(written)` |
| `int grow(T** inout)` frees the old handle and writes a new one | `std::inout_ptr(p)` | releases `p` first, passes the old value in, resets with the new one; not usable with `shared_ptr` |
| handle stored in a `shared_ptr` | `std::out_ptr(sp, deleter)` | the deleter argument is mandatory for `shared_ptr` |

Rules: use the adapter only as a call argument, never store it, and do not read `p` elsewhere
in the same full-expression (it is reset only when the temporary dies). If the C API allocates
even on failure (sqlite3_open does), `out_ptr` still takes ownership, so the error path
closes it automatically.

## 2. Ownership table

| Need | Type | Notes |
|---|---|---|
| sole owner, heap | `std::unique_ptr<T>` from `std::make_unique<T>(...)` | one pointer wide with a stateless deleter |
| owned buffer, uninitialised | `std::make_unique_for_overwrite<T[]>(n)` (C++20) | skips value-initialisation of PODs |
| genuinely shared lifetime | `std::shared_ptr<T>` from `std::make_shared` | one allocation; atomic refcount on every copy |
| pointer into a shared object | aliasing ctor `std::shared_ptr<M>(owner, &owner->m)` | keeps the owner alive, points at the member |
| observer that may outlive the owner | `std::weak_ptr<T>`, `if (auto sp = w.lock())` | breaks cycles: parent holds `shared_ptr`, child holds `weak_ptr` |
| object hands out owning refs to itself | `std::enable_shared_from_this<T>` (public base) | `shared_from_this()` throws `std::bad_weak_ptr` unless already owned (C++17): create via a factory |
| non-owning, never null | `T&` or `gsl::not_null<T*>` (`#include <gsl/gsl>`) | references cannot be reseated; `not_null` can |
| non-owning, nullable | `T*` documented as non-owning, or `std::optional<T&>` (C++26) | no owning raw pointers (`cppcoreguidelines-owning-memory`) |
| maybe-a-value | `std::optional<T>` | no heap |
| closed set of alternatives | `std::variant<A, B, C>` + `std::visit` | no heap, no vtable, exhaustive with overloaded lambdas |
| open set, value semantics | type erasure; C++26 `std::polymorphic<Base>` | see section 7 |
| deep-copied heap member (pimpl) | C++26 `std::indirect<Impl>`; else `unique_ptr<Impl>` + explicit copy | out-of-line destructor for incomplete `Impl` |

`shared_ptr` facts: the control block is thread-safe, the `shared_ptr` object itself is not
(concurrent `sp = x` and copy of `sp` is a data race: use `std::atomic<std::shared_ptr<T>>` or a
mutex, see `cpp-concurrency-atomics`). With `make_shared`, outstanding `weak_ptr`s keep the whole
allocation (object storage included) alive after the object is destroyed; for large objects with
long-lived weak observers, allocate separately: `std::shared_ptr<Big>(new Big(...))`.

## 3. Parameter passing and returns

| Intent | Signature | Notes |
|---|---|---|
| observe a cheap trivially copyable value (<= 2 words: `int`, `double`, `std::span`, `std::string_view`) | `T` | registers on SysV ABIs; Windows x64 passes structs over 8 bytes via a hidden copy, still cheap |
| observe anything else | `const T&` | |
| observe text | `std::string_view` | not null-terminated: never pass `.data()` to C APIs; never store |
| observe a contiguous sequence | `std::span<const T>` | accepts vector, array, C array |
| mutate the caller's object | `T&` | |
| sink (callee keeps it) | `T` by value, then `std::move` into place | one extra move; `const T&` + `T&&` overloads only in measured hot paths |
| forward generically | `template <class U> void f(U&& u)` + `std::forward<U>(u)` | constrain it, or it hijacks copy construction (`bugprone-forwarding-reference-overload`) |
| transfer unique ownership | `std::unique_ptr<T>` by value | call site shows `std::move(p)` |
| share ownership | `std::shared_ptr<T>` by value, only if the callee stores a copy | otherwise `T&`: no refcount traffic |
| callable used during the call | template `F&&`, or `std::function_ref<R(A)>` (C++26) | `function_ref` must not outlive the callable it refers to |
| callable stored, move-only captures | `std::move_only_function<R(A)>` (C++23) | libc++ lacks it: `std::function` or a small hand-rolled erasure |
| callable stored, copyable | `std::function<R(A)>` / `std::copyable_function` (C++26) | |
| "out" parameter | return a value, a struct with named fields, or `std::expected` | output params hide data flow |

Returns: by value. C++17 guarantees elision for prvalues; NRVO is the norm for a single named
local; returning a local or a `T&&` parameter by name moves implicitly (C++20 P1825, simplified
by C++23 P2266). Mark resource- and
error-returning functions `[[nodiscard]]`. Never return a reference or view to a local, to a
parameter bound to a temporary (`bugprone-return-const-ref-from-parameter`) or into a temporary.

## 4. Move checklist

- [ ] Move constructor and move assignment are `noexcept` and asserted:
      `static_assert(std::is_nothrow_move_constructible_v<T>);`. `std::vector` reallocates with
      `std::move_if_noexcept`: measured on 1000 `emplace_back`s, a throwing move gave **1023 copies,
      0 moves**; `noexcept` gave 0 copies, 1023 moves. `= default` moves are `noexcept` when every
      member's are; `performance-noexcept-move-constructor` flags the rest.
- [ ] No `return std::move(local);`: it blocks NRVO (`-Wpessimizing-move`, in `-Wall`); moving a
      returned parameter is redundant (`-Wredundant-move`: Clang `-Wall`, GCC `-Wextra`).
      `return std::move(member_);` only in `&&`-qualified getters.
- [ ] Moved-from objects: valid but unspecified. Only assign, destroy or call precondition-free
      members. `unique_ptr`/`shared_ptr` are null after move; a moved-from `std::string` may keep its
      characters (small-buffer optimisation), so `clear()` before reuse. Document your own types'
      moved-from state (prefer "empty").
- [ ] Any read after `auto x = std::move(y);` without reassignment is a bug: clang-tidy
      `bugprone-use-after-move` (understands `clear()`/assignment as reinitialisation).
- [ ] `const` objects cannot be moved: `std::move(const_obj)` silently copies
      (`performance-move-const-arg`); do not make locals `const` if you return or move them.
- [ ] `std::forward` for forwarding references, `std::move` for rvalue references:
      `bugprone-move-forwarding-reference`, `cppcoreguidelines-missing-std-forward`,
      `cppcoreguidelines-rvalue-reference-param-not-moved`.
- [ ] Self-move-assignment leaves the object valid: implement with `std::exchange`, never
      "release then steal" (`-Wself-move` catches literal `x = std::move(x)`).

## 5. Errors: mechanism choice and safety guarantees

| Situation | Mechanism |
|---|---|
| precondition violated (programmer bug) | `assert`, C++26 contracts (`pre`, `post`, `contract_assert`), or a project `CHECK` that terminates; never an error code |
| expected failure the caller handles nearby (parse, lookup, validation, I/O on user input) | `std::expected<T, E>` (`E` a small enum or struct); `std::optional<T>` when there is no reason to report |
| rare failure that must cross many frames (allocation failure, deep I/O) | exceptions, where the codebase allows them |
| `-fno-exceptions`, hard real-time, C ABI boundary, callbacks from C | `std::expected` or error codes; never let an exception cross `extern "C"` |
| destructors, `swap`, moves, deallocation | never fail: `noexcept` (destructors are implicitly `noexcept`; throwing from one calls `std::terminate`) |

`std::expected` composition (C++23 monadic members):

```cpp
std::expected<int, Error> port = read_file(path)          // expected<std::string, Error>
    .and_then(parse_config)                                // fn returns expected<Config, Error>, same E
    .transform([](const Config& c) { return c.port; })     // maps the value
    .or_else([](Error e) -> std::expected<int, Error> {    // recover or re-raise
        if (e.code == Errc::not_found) return 8080;
        return std::unexpected(e);
    });
```

`transform_error` maps `E`. `.value()` on an error throws `std::bad_expected_access<E>`; `*e` on an
error and `e.error()` on a value are undefined behaviour. `std::expected<void, E>` for actions.

Exception-safety guarantee per mutating operation (state it in the doc comment):

| Guarantee | Meaning | How |
|---|---|---|
| nothrow | cannot fail | `noexcept`; only non-throwing operations |
| strong | commit or roll back | do all throwing work on a copy or new object, then commit with `noexcept` swaps |
| basic | invariants hold, nothing leaks, value unspecified | RAII members; restore invariants before any throw point |

Copy-and-swap gives strong assignment in one function, at the cost of always allocating
(no reuse of the target's capacity); hand-write copy assignment for hot large containers.

```cpp
Widget& operator=(Widget other) noexcept { swap(*this, other); return *this; }   // copy and move
friend void swap(Widget& a, Widget& b) noexcept { using std::swap; swap(a.items_, b.items_); }
```

## 6. Lifetime pitfalls

| Construct | Why it dangles | Fix | Detector |
|---|---|---|---|
| `std::string_view sv = make_string();` | view of a temporary destroyed at `;` | own a `std::string` | Clang `-Wdangling-gsl` (on by default) |
| `return local_string;` from a `string_view` function | view of a local | return `std::string` | `-Wreturn-stack-address` |
| `std::span<const int> s = make_vector();` | const-element span binds to an rvalue container | name the container first | Clang `-Wdangling-gsl`; ASan |
| `[&]` lambda stored, queued, or given to a thread | captured locals die first | capture by value, `std::move` in, or `[self = shared_from_this()]` | ASan stack-use-after-return/scope |
| `[=]` in a member function | captures `this`, not members (implicit capture deprecated in C++20) | `[=, this]` explicitly, or copy the member: `[v = member_]` | `-Wdeprecated-this-capture` (Clang) |
| `const auto& x = std::max(a, b + 1);` / `auto p = std::minmax(1, 2);` | reference to a temporary argument | take by value | GCC `-Wdangling-reference` (in `-Wextra`; suppress false positives with `[[gnu::no_dangling]]`) |
| `for (auto& x : make().items())` | `make()` result dies before the loop body (pre-P2718) | `auto&& tmp = make(); for (auto& x : tmp.items())` | fixed in C++23 only when `__cpp_range_based_for >= 202211L` (GCC 15+, Clang 19+, MSVC 19.51) |
| reference or iterator kept across `push_back`/`insert`/rehash | reallocation or invalidation | indices, `reserve` before taking references, node containers | ASan heap-use-after-free; table below |
| coroutine taking `const T&` | frame keeps the reference past the first suspension | parameters by value | see `cpp-concurrency-atomics` |

Annotate APIs so the compiler catches misuse at call sites (Clang; checked on Apple clang 21):

```cpp
const Value& find(const Map& m [[clang::lifetimebound]], Key k);        // -Wdangling at `find(make_map(), k)`
std::string_view name() const [[clang::lifetimebound]];                 // ties result to *this
void remember(std::string_view s [[clang::lifetime_capture_by(out)]],   // Clang 20+:
              std::vector<std::string_view>& out);                      // -Wdangling-capture on temporaries
```

libc++ already annotates `vector<string_view>::push_back` style captures: `v.push_back(make())`
for `std::vector<std::string_view> v` warns with `-Wdangling-capture`. GCC adds
`-Wdangling-pointer=2` (in `-Wall`) for pointers to out-of-scope locals.

Iterator invalidation, short form (full table, including `deque`, `flat_map`, `inplace_vector`
and `string`, in [iterator-invalidation](references/iterator-invalidation.md)):

| Container | Insert | Erase |
|---|---|---|
| `vector`, `string` | reallocation: all; else at/after the point (and `end()`) | at/after the point |
| `deque` | at either end: all iterators, references stay valid; middle: all | ends: erased only (plus `end()` at the back); middle: all |
| `list`, `forward_list`, `map`, `set` | none | erased elements only |
| `unordered_*` | rehash: all iterators, references stay valid; no rehash: none | erased elements only |

## 7. Polymorphic bases

- Base destructor is either `public` and `virtual` or `protected` and non-virtual (deleting a
  derived object through a base pointer with a non-virtual destructor is UB). Warnings:
  `-Wdelete-non-virtual-dtor` (in `-Wall`), `-Wnon-virtual-dtor`; clang-tidy
  `cppcoreguidelines-virtual-class-destructor`.
- Prevent slicing: no public copy or move in the polymorphic base (protected copy constructor if
  derived classes implement `virtual std::unique_ptr<Base> clone() const`, deleted otherwise;
  deleted copy assignment); clang-tidy `cppcoreguidelines-slicing`.
- `override` on every override (`-Wsuggest-override` GCC, `-Winconsistent-missing-override`
  Clang); `final` on leaf classes and leaf overrides lets the compiler devirtualise.
- Prefer non-inheritance designs when the hierarchy exists only for dispatch:

| Situation | Use |
|---|---|
| closed set of types known at compile time | `std::variant` + `std::visit` |
| one operation (callback, strategy) | `std::function` / `std::move_only_function` / template parameter |
| open set, value semantics, several operations | type erasure (concept/model: one internal virtual base, value-semantic handle; full example in [raii-patterns](references/raii-patterns.md)), or C++26 `std::polymorphic<Base>` |
| open set, plugins, reference semantics | classic virtual base + `std::unique_ptr<Base>` |

## 8. Allocation control

`std::pmr` (`<memory_resource>`) picks the allocation strategy at run time: every
`std::pmr::vector<T>` has the same type whatever resource backs it.

```cpp
void handle(const Request& req) {
    std::array<std::byte, 16 * 1024> stack_buf;                       // first 16 KiB on the stack
    std::pmr::monotonic_buffer_resource arena(stack_buf.data(), stack_buf.size());  // then heap
    std::pmr::vector<std::pmr::string> fields(&arena);                // strings use the arena too
    parse_into(req, fields);                                          // many small allocations
}                                                                     // freed at once, no per-object free
```

| Resource | Use | Watch out |
|---|---|---|
| `monotonic_buffer_resource` | per-request or per-frame scratch | never frees until destruction or `release()`: not for long-lived, churning containers |
| `unsynchronized_pool_resource` | single-thread reuse of many same-sized blocks | not thread-safe |
| `synchronized_pool_resource` | shared pools across threads | lock cost |
| `null_memory_resource()` as upstream | prove "no heap after this point" | exhaustion throws `std::bad_alloc` |

pmr pitfalls (checked): copy construction does **not** propagate the resource (the copy uses the
default resource; `polymorphic_allocator::select_on_container_copy_construction`), so pass it
explicitly: `std::pmr::vector<T> copy(src, &arena);`. Move assignment between containers on
different resources copies element-wise. Nothing allocated from an arena may outlive it.
Allocator-aware element types need `using allocator_type = std::pmr::polymorphic_allocator<>;`
plus allocator-extended constructors (skeleton in [raii-patterns](references/raii-patterns.md)).

Fixed-capacity, no-heap containers: `std::inplace_vector<T, N>` (C++26, libstdc++ 16):
`push_back` throws `std::bad_alloc` when full, `try_push_back` reports failure without throwing
(its return type changed at `__cpp_lib_inplace_vector >= 202603L`; check your library),
`unchecked_push_back` is UB when full; moving or swapping invalidates all iterators. Elsewhere:
`boost::container::static_vector`, or small-buffer types with heap fallback
(`absl::InlinedVector`, `llvm::SmallVector`).

## 9. Worked example: leaky loader to RAII + expected, then C-handle wrappers

Before: leaks the `FILE*` and the buffer on the early return, errors are magic ints.

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

Evidence: on macOS (no LeakSanitizer) `leaks --atExit -- ./old` exited 1 with
"1 leak for 5120 total leaked bytes" for an empty input (`/dev/null`); the `FILE*` was not reported
because libc keeps open streams reachable. Memory tools miss handle leaks: count fds
(`lsof -p <pid>`, `ls /proc/<pid>/fd`) as well.

After (C++23): every exit path releases both resources, the error type is closed.

```cpp
enum class LoadError { open_failed, read_failed, empty };
std::expected<Config, LoadError> parse(std::span<const char> bytes);   // empty -> LoadError::empty

std::expected<Config, LoadError> load(const std::filesystem::path& path) {
    File f{std::fopen(path.c_str(), "rb")};          // File from section 1
    if (!f) return std::unexpected(LoadError::open_failed);
    std::vector<char> buf(4096);
    const std::size_t n = std::fread(buf.data(), 1, buf.size(), f.get());
    if (std::ferror(f.get())) return std::unexpected(LoadError::read_failed);
    buf.resize(n);
    return parse(buf);
}
// caller: auto size = load(p).transform([](const Config& c) { return c.text.size(); }).value_or(0);
```

On Windows `path.c_str()` is `const wchar_t*`: use `_wfopen` or `std::ifstream` there.

Move-only handle for a C library, rule of zero via `unique_ptr` + `out_ptr`:

```cpp
extern "C" {                                          // the C API
typedef struct kv_db kv_db;
int  kv_open(const char* path, kv_db** out);         // 0 on success; allocates *out even on failure
void kv_close(kv_db* db);
int  kv_put(kv_db* db, const char* k, const char* v);
}
struct KvClose { void operator()(kv_db* p) const noexcept { kv_close(p); } };

class KvStore {                                       // move-only because its member is
public:
    static std::expected<KvStore, int> open(const std::string& path) {
        std::unique_ptr<kv_db, KvClose> h;
        if (int rc = kv_open(path.c_str(), std::out_ptr(h)); rc != 0)
            return std::unexpected(rc);               // h owns the half-open handle: closed here
        return KvStore{std::move(h)};
    }
    std::expected<void, int> put(const std::string& k, const std::string& v) {
        if (int rc = kv_put(h_.get(), k.c_str(), v.c_str()); rc != 0) return std::unexpected(rc);
        return {};
    }
private:
    explicit KvStore(std::unique_ptr<kv_db, KvClose> h) noexcept : h_(std::move(h)) {}
    std::unique_ptr<kv_db, KvClose> h_;
};
static_assert(!std::is_copy_constructible_v<KvStore> && std::is_nothrow_move_constructible_v<KvStore>);
```

Non-pointer handle: the rule of five, written once, in a tiny wrapper:

```cpp
class UniqueFd {
public:
    UniqueFd() noexcept = default;
    explicit UniqueFd(int fd) noexcept : fd_(fd) {}
    UniqueFd(UniqueFd&& o) noexcept : fd_(std::exchange(o.fd_, -1)) {}
    UniqueFd& operator=(UniqueFd&& o) noexcept { reset(std::exchange(o.fd_, -1)); return *this; }
    UniqueFd(const UniqueFd&) = delete;
    UniqueFd& operator=(const UniqueFd&) = delete;
    ~UniqueFd() { reset(); }
    [[nodiscard]] int get() const noexcept { return fd_; }
    [[nodiscard]] int release() noexcept { return std::exchange(fd_, -1); }
    void reset(int fd = -1) noexcept { if (fd_ >= 0 && fd_ != fd) ::close(fd_); fd_ = fd; }
    explicit operator bool() const noexcept { return fd_ >= 0; }
private:
    int fd_ = -1;
};
static_assert(std::is_nothrow_move_constructible_v<UniqueFd> && std::is_nothrow_move_assignable_v<UniqueFd>);
```

`std::exchange` makes self-move safe (the old value is detached before `reset` runs). Verify:

```bash
clang++ -std=c++23 -Wall -Wextra -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all loader.cpp -o loader
./loader                                   # Linux: LeakSanitizer runs at exit; macOS: use leaks below
clang++ -std=c++23 -g loader.cpp -o loader_plain && leaks --atExit -- ./loader_plain   # exit 0 = no leaks
```

All snippets in this section compiled and ran clean under ASan+UBSan (Apple clang 21, libc++ 22)
with a stub `kv_*` implementation, including the `open("")` failure path.

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `std::vector` copies elements on growth | move constructor not `noexcept` | mark `noexcept`, `static_assert` it |
| double close / double free | wrapper is copyable (implicit copy of the raw handle) | delete copy; move with `std::exchange` |
| leak on an early return or exception | manual cleanup at the end of the function | RAII for every acquisition, including `malloc`ed buffers |
| `shared_ptr` graph never freed | ownership cycle | `weak_ptr` for back and parent links |
| `std::bad_weak_ptr` thrown | `shared_from_this()` in a constructor or on a stack object | static `create()` factory returning `shared_ptr` |
| memory stays high after objects die | `make_shared` block pinned by long-lived `weak_ptr`s | allocate the object separately |
| derived part missing after copy | slicing through a by-value base | no public base copy, `clone()`, or type erasure |
| crash deleting through base pointer | non-virtual base destructor | `virtual ~Base() = default;` or protected destructor |
| `std::move` "does nothing" | object is `const`, or the target has no move constructor | drop `const`; check `std::is_nothrow_move_constructible_v` |
| moved-from string still has text | small-buffer optimisation | `clear()` before reuse; never rely on moved-from values |
| garbage from a `string_view` member | view stored beyond the owner's life | store `std::string`; annotate with `lifetimebound` |
| C API reads past the text end | `string_view::data()` is not null-terminated | pass `std::string` / `.c_str()` |
| pmr copy silently allocates on the heap | copy construction uses the default resource | pass the resource to the copy constructor |
| `std::terminate` during stack unwinding | a destructor threw | catch inside the destructor, log, never rethrow |
| `std::vector<bool>` surprises (`auto& b = v[0]` fails, no `data()`) | proxy references, not a container of `bool` | `std::vector<char>`, `std::bitset`, `boost::dynamic_bitset` |

## 11. Review checklist

- [ ] No owning raw pointers, no naked `new`/`delete`/`malloc`/`free` outside RAII wrappers.
- [ ] Each wrapper owns exactly one resource; all other classes follow the rule of zero.
- [ ] Moves `noexcept` and asserted; no use-after-move; no `return std::move(local)`.
- [ ] Signatures follow section 3; no views or references escaping their owner.
- [ ] Error mechanism chosen per section 5; guarantees stated for mutating operations.
- [ ] Polymorphic bases: virtual or protected destructor, copying deleted, `override`/`final`.
- [ ] Public headers self-contained (include what you use), no `using namespace` in headers.
- [ ] ASan(+LSan on Linux) clean on the tests; Clang `-Wdangling*` and GCC
      `-Wdangling-reference` clean; clang-tidy `bugprone-use-after-move`,
      `cppcoreguidelines-owning-memory`, `cppcoreguidelines-special-member-functions` clean.

Related: `cpp-templates-concepts`, `cpp-concurrency-atomics`, `cpp-ub-sanitizers`,
`cpp-testing-fuzzing`, `cpp-simd-performance`, hub `cpp-craft`.
