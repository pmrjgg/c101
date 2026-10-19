# jcstress recipes

jcstress (OpenJDK Code Tools, latest release 0.16 on Maven Central) runs small actor methods
concurrently millions of times and tallies the observed outcomes. Use it for memory-model
properties of lock-free or racy code; it is not a load-testing tool.

## Project setup

```bash
mvn archetype:generate -DinteractiveMode=false \
  -DarchetypeGroupId=org.openjdk.jcstress -DarchetypeArtifactId=jcstress-java-test-archetype \
  -DgroupId=com.acme -DartifactId=concurrency-tests -Dversion=1.0
cd concurrency-tests && mvn clean verify
java -jar target/jcstress.jar -h                 # all options
java -jar target/jcstress.jar -t StoreBuffering  # run tests whose name matches
java -jar target/jcstress.jar -m quick           # shorter preset, typical for CI
```

Keep jcstress tests in a separate module so their long runtime stays out of the unit-test
build; run them nightly on a machine with many cores (outcomes depend on hardware).

## Annotations

| Annotation / type | Role |
|---|---|
| `@JCStressTest` | marks the test class |
| `@State` | the shared object; a fresh instance per trial |
| `@Actor` | a method run concurrently with the other actors |
| `@Arbiter` | runs after all actors finished; reads the final state |
| `@Outcome(id = {...}, expect = Expect.X, desc = "...")` | classifies observed results |
| `Expect.ACCEPTABLE`, `ACCEPTABLE_INTERESTING`, `FORBIDDEN` | allowed, allowed but notable, a bug |
| `II_Result`, `JJ_Result`, `I_Result`, `ZZ_Result` ... | result holders (`r1`, `r2`, ...) typed by letter: I int, J long, Z boolean |

## Store buffering (shows why plain fields are not sequentially consistent)

```java
import org.openjdk.jcstress.annotations.*;
import org.openjdk.jcstress.infra.results.II_Result;
import static org.openjdk.jcstress.annotations.Expect.*;

@JCStressTest
@Outcome(id = {"0, 1", "1, 0", "1, 1"}, expect = ACCEPTABLE, desc = "some interleaving")
@Outcome(id = "0, 0", expect = ACCEPTABLE_INTERESTING, desc = "both reads saw stale values")
@State
public class StoreBuffering {
    int x, y;
    @Actor public void actor1(II_Result r) { x = 1; r.r1 = y; }
    @Actor public void actor2(II_Result r) { y = 1; r.r2 = x; }
}
```

Make `x` and `y` `volatile` and change the `"0, 0"` outcome to `FORBIDDEN`: the test then
proves sequential consistency for those accesses.

## Lost update on a racy counter

```java
@JCStressTest
@Outcome(id = "2", expect = ACCEPTABLE, desc = "both increments applied")
@Outcome(id = "1", expect = ACCEPTABLE_INTERESTING, desc = "lost update: count++ is not atomic")
@State
public class RacyCounter {
    volatile int count;                                      // volatile does not make ++ atomic
    @Actor public void a() { count++; }
    @Actor public void b() { count++; }
    @Arbiter public void check(I_Result r) { r.r1 = count; }
}
```

Replace the field with `AtomicInteger` (`incrementAndGet`) and mark `"1"` `FORBIDDEN`.

## Unsafe publication

```java
@JCStressTest
@Outcome(id = "42", expect = ACCEPTABLE, desc = "fully constructed")
@Outcome(id = "-1", expect = ACCEPTABLE, desc = "not yet published")
@Outcome(id = "0", expect = ACCEPTABLE_INTERESTING, desc = "published before field write became visible")
@State
public class UnsafePublication {
    static class Holder { int value; Holder() { value = 42; } }   // make value final to forbid "0"
    Holder h;
    @Actor public void writer() { h = new Holder(); }
    @Actor public void reader(I_Result r) { Holder l = h; r.r1 = (l == null) ? -1 : l.value; }
}
```

With `final int value` the JMM forbids observing `0`; with a `volatile Holder h` it is also
forbidden. Whether `0` actually shows up depends on CPU architecture (weakly ordered ARM
machines show more), which is why a passing run on x86 is not proof of correctness.

## Reading results

The HTML report (`results/index.html`) lists, per test, how often each outcome occurred.
Any `FORBIDDEN` count above zero fails the run. `ACCEPTABLE_INTERESTING` outcomes document real
reorderings; if code depends on them not happening, the code is wrong even when tests pass.
