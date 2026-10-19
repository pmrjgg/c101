# loom, shuttle, paused time, Kani, state machines and test doubles

All snippets except Kani and testcontainers were compiled and run on Rust 1.99 (October 2026).

## 1. loom: exhaustive interleavings of a small model

```toml
[target.'cfg(loom)'.dev-dependencies]
loom = "0.7"

[lints.rust]
unexpected_cfgs = { level = "warn", check-cfg = ['cfg(loom)'] }
```

```rust
#[cfg(loom)]
pub(crate) use loom::sync::atomic::{AtomicUsize, Ordering};
#[cfg(not(loom))]
pub(crate) use std::sync::atomic::{AtomicUsize, Ordering};

pub struct Hits(AtomicUsize);
impl Hits {
    pub fn new() -> Self { Hits(AtomicUsize::new(0)) }
    pub fn hit(&self) { self.0.fetch_add(1, Ordering::Relaxed); }   // was: load + store (racy)
    pub fn get(&self) -> usize { self.0.load(Ordering::Acquire) }
}

#[cfg(all(test, loom))]
mod loom_tests {
    use super::*;
    #[test]
    fn two_threads_two_hits() {
        loom::model(|| {
            let h = loom::sync::Arc::new(Hits::new());
            let ts: Vec<_> = (0..2)
                .map(|_| { let h = loom::sync::Arc::clone(&h); loom::thread::spawn(move || h.hit()) })
                .collect();
            for t in ts { t.join().unwrap(); }
            assert_eq!(h.get(), 2);
        });
    }
}
```

```bash
RUSTFLAGS="--cfg loom" cargo test --release --lib loom_tests
LOOM_MAX_PREEMPTIONS=2 LOOM_LOG=trace RUSTFLAGS="--cfg loom" cargo test --release --lib loom_tests
```

With the racy `load` + `store` version the plain unit test passed and the loom model failed with
`left: 1, right: 2`. Environment knobs: `LOOM_MAX_PREEMPTIONS`, `LOOM_MAX_BRANCHES`,
`LOOM_MAX_PERMUTATIONS`, `LOOM_MAX_DURATION`, `LOOM_CHECKPOINT_FILE` + `LOOM_CHECKPOINT_INTERVAL`
(resume long runs), `LOOM_LOG`, `LOOM_LOCATION`. Only types from `loom::sync`, `loom::cell` and
`loom::thread` are modelled: std types inside the model are invisible to it.

## 2. shuttle: randomized schedules for bigger tests

```rust
use shuttle::sync::atomic::{AtomicUsize, Ordering};
use shuttle::sync::Arc;
use shuttle::thread;

#[test]
fn lost_update() {
    shuttle::check_random(|| {
        let n = Arc::new(AtomicUsize::new(0));
        let hs: Vec<_> = (0..2).map(|_| {
            let n = Arc::clone(&n);
            thread::spawn(move || { let v = n.load(Ordering::SeqCst); n.store(v + 1, Ordering::SeqCst); })
        }).collect();
        for h in hs { h.join().unwrap(); }
        assert_eq!(n.load(Ordering::SeqCst), 2);
    }, 1000);                                   // 1000 random schedules
}
```

On failure shuttle prints `failing schedule: <string>` and "pass that string to
`shuttle::replay` to replay the failure"; paste it into `shuttle::replay(test_fn, "<string>")`
for a deterministic reproduction. Other entry points: `check_pct(f, iterations, depth)`
(probabilistic concurrency testing, better at deep bugs), `check_dfs`, `replay_from_file`.
`shuttle::future::block_on` / `spawn` cover async code.

## 3. tokio paused time

```toml
[dev-dependencies]
tokio = { version = "1", features = ["macros", "rt", "time", "test-util"] }
```

```rust
#[tokio::test(start_paused = true)]
async fn timer_logic_without_waiting() {
    let start = tokio::time::Instant::now();
    tokio::time::sleep(std::time::Duration::from_secs(3600)).await;   // returns instantly
    assert!(start.elapsed() >= std::time::Duration::from_secs(3600));
}
```

Paused time auto-advances when every task is idle; `tokio::time::advance(d)` steps manually.
Use `flavor = "multi_thread"` tests separately to surface `Send` and race issues (paused time
needs the current-thread runtime).

## 4. proptest-state-machine (model-based testing)

```rust
use proptest::prelude::*;
use proptest_state_machine::{prop_state_machine, ReferenceStateMachine, StateMachineTest};
use std::collections::VecDeque;

#[derive(Clone, Debug)]
enum Op { Push(u32), Pop }

struct RefRing;
impl ReferenceStateMachine for RefRing {
    type State = (VecDeque<u32>, usize);          // (items, capacity)
    type Transition = Op;
    fn init_state() -> BoxedStrategy<Self::State> { (1usize..5).prop_map(|cap| (VecDeque::new(), cap)).boxed() }
    fn transitions(_: &Self::State) -> BoxedStrategy<Op> {
        prop_oneof![any::<u32>().prop_map(Op::Push), Just(Op::Pop)].boxed()
    }
    fn apply(mut s: Self::State, op: &Op) -> Self::State {
        match op {
            Op::Push(v) => { if s.0.len() < s.1 { s.0.push_back(*v); } }
            Op::Pop => { s.0.pop_front(); }
        }
        s
    }
}

struct RingTest;
impl StateMachineTest for RingTest {
    type SystemUnderTest = Ring;
    type Reference = RefRing;
    fn init_test(r: &<RefRing as ReferenceStateMachine>::State) -> Ring { Ring::new(r.1) }
    fn apply(mut sut: Ring, r: &<RefRing as ReferenceStateMachine>::State, op: Op) -> Ring {
        match op { Op::Push(v) => { sut.push(v); } Op::Pop => { sut.pop(); } }
        assert_eq!(sut.len(), r.0.len());          // `r` is the model state after the op
        sut
    }
    fn check_invariants(sut: &Ring, r: &<RefRing as ReferenceStateMachine>::State) {
        assert!(sut.len() <= r.1);
    }
}

prop_state_machine! {
    #[test]
    fn ring_matches_model(sequential 1..30 => RingTest);
}
```

Shrinking removes transitions until the shortest failing sequence remains. Add
`preconditions` to skip transitions that are invalid in the current model state.

## 5. Kani bounded proofs

```bash
cargo install --locked kani-verifier && cargo kani setup
cargo kani --harness parse_u64_never_panics
```

```rust
#[cfg(kani)]
mod proofs {
    #[kani::proof]
    #[kani::unwind(21)]                  // loop bound + 1
    fn parse_u64_never_panics() {
        let bytes: [u8; 20] = kani::any();
        let len: usize = kani::any();
        kani::assume(len <= bytes.len());
        let _ = super::parse_u64(&bytes[..len]);   // proves: no panic, no overflow for any input <= 20 bytes
    }
}
```

Good targets: parsers of fixed-size headers, index arithmetic, unsafe kernels with small inputs.
Kani checks arithmetic overflow, out-of-bounds and `unwrap` panics by default.

## 6. Test doubles

Hand-written fake (preferred):

```rust
pub trait Store { fn get(&self, id: u64) -> Result<Option<String>, String>; }
struct FakeStore(std::collections::HashMap<u64, String>);
impl Store for FakeStore {
    fn get(&self, id: u64) -> Result<Option<String>, String> { Ok(self.0.get(&id).cloned()) }
}
```

mockall when interactions matter:

```rust
#[cfg_attr(test, mockall::automock)]
pub trait Store { fn get(&self, id: u64) -> Result<Option<String>, String>; }

#[test]
fn greets_known_user() {
    let mut m = MockStore::new();
    m.expect_get().with(mockall::predicate::eq(7)).times(1).returning(|_| Ok(Some("ana".into())));
    assert_eq!(greeting(&m, 7), "hello ana");
}
```

wiremock for HTTP clients:

```rust
#[tokio::test]
async fn client_handles_503() {
    let server = wiremock::MockServer::start().await;
    wiremock::Mock::given(wiremock::matchers::method("GET"))
        .and(wiremock::matchers::path("/v1/status"))
        .respond_with(wiremock::ResponseTemplate::new(503))
        .expect(1)                       // verified when `server` drops
        .mount(&server)
        .await;
    let resp = reqwest::get(format!("{}/v1/status", server.uri())).await.unwrap();
    assert_eq!(resp.status().as_u16(), 503);
}
```

Databases: `#[sqlx::test(migrations = "./migrations")] async fn t(pool: PgPool)` creates a fresh
database per test on the server in `DATABASE_URL` (fixtures via `fixtures("users")`); without a
local server use testcontainers (`testcontainers-modules` with the `postgres` feature:
`Postgres::default().start().await?`, then `get_host().await?` and `get_host_port_ipv4(5432).await?`;
use the `testcontainers` re-exported by `testcontainers_modules` to avoid version skew). See the
`rust-axum-services` skill for an end-to-end HTTP + database test.
