# RAII patterns

Every listing here compiled with `clang++ -std=c++23 -Wall -Wextra` (Apple clang 21, libc++ 22)
and ran clean under `-fsanitize=address,undefined`.

## Generic owner for non-pointer handles

Write the rule of five once; each handle kind supplies a traits type.

```cpp
template <class Traits>
class UniqueHandle {
public:
    using handle_type = typename Traits::handle_type;
    UniqueHandle() noexcept = default;
    explicit UniqueHandle(handle_type h) noexcept : h_(h) {}
    UniqueHandle(UniqueHandle&& o) noexcept : h_(std::exchange(o.h_, Traits::invalid())) {}
    UniqueHandle& operator=(UniqueHandle&& o) noexcept {
        reset(std::exchange(o.h_, Traits::invalid()));
        return *this;
    }
    UniqueHandle(const UniqueHandle&) = delete;
    UniqueHandle& operator=(const UniqueHandle&) = delete;
    ~UniqueHandle() { reset(); }

    [[nodiscard]] handle_type get() const noexcept { return h_; }
    [[nodiscard]] handle_type release() noexcept { return std::exchange(h_, Traits::invalid()); }
    void reset(handle_type h = Traits::invalid()) noexcept {
        if (h_ != Traits::invalid() && h_ != h) Traits::close(h_);
        h_ = h;
    }
    explicit operator bool() const noexcept { return h_ != Traits::invalid(); }
    friend void swap(UniqueHandle& a, UniqueHandle& b) noexcept { std::swap(a.h_, b.h_); }
private:
    handle_type h_ = Traits::invalid();
};

struct FdTraits {
    using handle_type = int;
    static constexpr int invalid() noexcept { return -1; }
    static void close(int fd) noexcept { ::close(fd); }
};
using Fd = UniqueHandle<FdTraits>;
static_assert(std::is_nothrow_move_constructible_v<Fd> && !std::is_copy_constructible_v<Fd>);
```

Other traits: sockets (`INVALID_SOCKET` / `closesocket` on Windows), OpenGL names
(`0` / `glDeleteBuffers(1, &h)`), Win32 `HANDLE` (two sentinels exist: `nullptr` for most
objects, `INVALID_HANDLE_VALUE` for `CreateFile`; pick per API, never mix).

## Pointer-shaped handles: unique_ptr, out_ptr, inout_ptr, shared ownership

```cpp
struct BufFree { void operator()(buf_t* b) const noexcept { buf_free(b); } };

std::unique_ptr<buf_t, BufFree> u;
buf_new(std::out_ptr(u));                 // int buf_new(buf_t** out)
buf_grow(std::inout_ptr(u));              // int buf_grow(buf_t** io): frees old, writes new

std::shared_ptr<buf_t> s;
buf_new(std::out_ptr(s, BufFree{}));      // shared_ptr needs the deleter here
// std::out_ptr(s)  -> static_assert: "Using std::shared_ptr<> without a deleter ... not supported"
// std::inout_ptr(s) -> static_assert: shared_ptr cannot release ownership
```

Without C++23: `buf_t* raw = nullptr; int rc = buf_new(&raw); std::unique_ptr<buf_t, BufFree> u(raw);`
(construct the owner on the very next line, before anything can throw or return).

## Scope guard

The standard has none (`std::experimental::scope_exit` is Library Fundamentals TS v3 only);
`gsl::finally` from GSL works, or this:

```cpp
template <class F>
class ScopeExit {
public:
    explicit ScopeExit(F f) noexcept(std::is_nothrow_move_constructible_v<F>) : f_(std::move(f)) {}
    ScopeExit(const ScopeExit&) = delete;
    ScopeExit& operator=(const ScopeExit&) = delete;
    ~ScopeExit() { if (active_) f_(); }
    void release() noexcept { active_ = false; }        // commit: skip the rollback
private:
    F f_;
    bool active_ = true;
};

void transfer(Account& from, Account& to, Money m) {
    from.debit(m);
    ScopeExit undo{[&] { from.credit(m); }};            // runs if credit below throws
    to.credit(m);
    undo.release();                                     // strong guarantee achieved
}
```

The callable must not throw (it runs in a destructor, possibly during unwinding).

## shared_ptr aliasing constructor

Hand out a pointer to a part while keeping the whole alive:

```cpp
struct Atlas { Image page; std::string name; };

std::shared_ptr<const Image> page_of(std::shared_ptr<const Atlas> atlas) {
    return std::shared_ptr<const Image>(atlas, &atlas->page);   // shares atlas's control block
}
// auto page = page_of(atlas); atlas.reset();  -> page still valid; use_count was 2 before reset
```

## Allocator-aware type for std::pmr

```cpp
class Record {
public:
    using allocator_type = std::pmr::polymorphic_allocator<>;
    explicit Record(allocator_type alloc = {}) : name_(alloc), tags_(alloc) {}
    Record(const Record& o, allocator_type alloc) : name_(o.name_, alloc), tags_(o.tags_, alloc) {}
    Record(Record&& o, allocator_type alloc)
        : name_(std::move(o.name_), alloc), tags_(std::move(o.tags_), alloc) {}
    Record(const Record&) = default;
    Record(Record&&) noexcept = default;
    Record& operator=(const Record&) = default;
    Record& operator=(Record&&) = default;
    allocator_type get_allocator() const noexcept { return name_.get_allocator(); }
private:
    std::pmr::string name_;
    std::pmr::vector<std::pmr::string> tags_;
};

std::array<std::byte, 4096> buf;
std::pmr::monotonic_buffer_resource arena(buf.data(), buf.size());
std::pmr::vector<Record> recs(&arena);
recs.emplace_back();                      // uses-allocator construction: the Record gets &arena
std::pmr::vector<Record> copy(recs);      // measured: copy.get_allocator().resource() != &arena
std::pmr::vector<Record> copy2(recs, &arena);   // explicit: stays in the arena
```

`allocator_type` plus the allocator-extended constructors are what make containers pass the
resource down (uses-allocator construction). Forgetting them silently puts nested data on the
default resource.

## Type erasure instead of an inheritance hierarchy

Value semantics (copyable, no slicing, no `unique_ptr<Base>` at call sites), any type with an
`area()` member, one virtual call per operation:

```cpp
class Shape {
    struct Concept {
        virtual ~Concept() = default;
        virtual double area() const = 0;
        virtual std::unique_ptr<Concept> clone() const = 0;
    };
    template <class T>
    struct Model final : Concept {
        T value;
        explicit Model(T v) : value(std::move(v)) {}
        double area() const override { return value.area(); }
        std::unique_ptr<Concept> clone() const override { return std::make_unique<Model>(*this); }
    };
    std::unique_ptr<Concept> self_;
public:
    template <class T>
        requires (!std::same_as<std::remove_cvref_t<T>, Shape>)
              && requires(const T& t) { { t.area() } -> std::convertible_to<double>; }
    Shape(T t) : self_(std::make_unique<Model<T>>(std::move(t))) {}
    Shape(const Shape& o) : self_(o.self_->clone()) {}
    Shape(Shape&&) noexcept = default;
    Shape& operator=(Shape o) noexcept { self_ = std::move(o.self_); return *this; }
    double area() const { return self_->area(); }
};

struct Circle { double r; double area() const { return 3.14159265 * r * r; } };
struct Rect { double w, h; double area() const { return w * h; } };
std::vector<Shape> shapes{Circle{1}, Rect{2, 3}};   // copies deep-copy via clone()
```

The `requires (!std::same_as<...>)` guard stops the converting constructor from hijacking copy
construction of `Shape` itself. Add a small-buffer optimisation only after a profile shows the
allocation matters. C++26 `std::polymorphic<Base>` gives the same value semantics for an existing
virtual hierarchy.

## Polymorphic base skeleton

```cpp
class Node {
public:
    virtual ~Node() = default;
    virtual std::unique_ptr<Node> clone() const = 0;
    virtual void accept(Visitor& v) = 0;
protected:
    Node() = default;
    Node(const Node&) = default;              // usable by derived clone() only
    Node& operator=(const Node&) = delete;    // no slicing assignment through the base
};

class Leaf final : public Node {
public:
    std::unique_ptr<Node> clone() const override { return std::make_unique<Leaf>(*this); }
    void accept(Visitor& v) override { v.visit(*this); }
};
```
