# Test command cheat-sheet

Single test, randomized order, repetition, coverage, and diff coverage per ecosystem. Always record the
exact command and exit code in Evidence.

## Python (pytest)
```bash
pytest -q -x                                   # stop at first failure
pytest tests/test_a.py::test_b -vv             # single test, verbose diff
pytest -k "parse and not slow"                 # by expression
pytest --lf                                    # last-failed only
pytest -n auto                                 # parallel (pytest-xdist)
pytest -p randomly --randomly-seed=1234        # random order, reproducible (pytest-randomly)
pytest --count=200 -x tests/test_a.py::test_b  # repetition (pytest-repeat)
pytest --durations=20                          # slowest tests
pytest --cov=mypkg --cov-branch --cov-report=term-missing --cov-report=xml
coverage run --branch -m pytest && coverage report -m
diff-cover coverage.xml --compare-branch=origin/main --fail-under=80
```

## Go
```bash
go test ./...                                  # all packages
go test -run '^TestParse$/^empty$' ./parser    # test and subtest by regex
go test -count=1 ./...                         # bypass the test cache
go test -race ./...
go test -shuffle=on ./...                      # prints the seed; replay with -shuffle=<seed>
go test -count=300 -run '^TestX$' ./pkg        # repetition
go test -coverprofile=c.out -covermode=atomic -coverpkg=./... ./...
go tool cover -func=c.out | tail -1            # total
go tool cover -html=c.out -o coverage.html
go test -fuzz=FuzzX -fuzztime=60s ./pkg
```

## Rust
```bash
cargo test parse_ -- --nocapture               # filter by name substring, show output
cargo test -- --test-threads=1                 # serialize (isolate shared-state flakiness)
cargo nextest run                              # process-per-test isolation, better reporting
cargo nextest run --retries 2                  # surfaces flaky tests as FLAKY in the report
cargo llvm-cov --html                          # coverage report in target/llvm-cov/html
cargo llvm-cov --lcov --output-path lcov.info
cargo +nightly miri test                       # UB detection in unsafe code (slow; scope it)
cargo mutants --in-diff changes.diff
```

## JavaScript / TypeScript
```bash
npx vitest run                                 # single run (no watch)
npx vitest run -t "parses durations"           # by test name
npx vitest run --coverage                      # requires @vitest/coverage-v8 or -istanbul
npx vitest run --sequence.shuffle              # random order
npx jest -t "parses durations" --runInBand     # serial, easier debugging
npx jest --coverage
npx jest --randomize --seed=1234               # Jest 29.2+
npx playwright test --repeat-each=20 --workers=4 --retries=0
npx playwright test --trace on && npx playwright show-trace test-results/**/trace.zip
npx stryker run
```

## Java / Kotlin
```bash
mvn -Dtest='InvoiceTest#totalsZeroQuantity' test
mvn verify jacoco:report                       # with the jacoco-maven-plugin configured
./gradlew test --tests 'com.acme.InvoiceTest.totalsZeroQuantity'
./gradlew test jacocoTestReport
mvn -Dsurefire.rerunFailingTestsCount=0 test   # make sure retries are not masking flakiness
mvn org.pitest:pitest-maven:mutationCoverage -DtargetClasses='com.acme.billing.*'
```
JUnit 5 random method order: `junit.jupiter.testmethod.order.default = org.junit.jupiter.api.MethodOrderer$Random`
in `junit-platform.properties`. Repetition: `@RepeatedTest(200)`.

## C / C++
```bash
ctest --output-on-failure -R parser            # by regex
ctest --repeat until-fail:200 -R parser        # CMake 3.17+
./unit_tests --gtest_filter='Parser.*' --gtest_repeat=200 --gtest_shuffle --gtest_random_seed=42
# clang source-based coverage
clang++ -fprofile-instr-generate -fcoverage-mapping ... -o tests && LLVM_PROFILE_FILE=t.profraw ./tests
llvm-profdata merge -sparse t.profraw -o t.profdata
llvm-cov report ./tests -instr-profile=t.profdata
# gcc: --coverage then gcovr -r . --html-details coverage.html
```

## Haskell
```bash
cabal test --test-show-details=direct
cabal test --enable-coverage                   # hpc report under dist-newstyle
stack test --coverage
```

## Julia
```bash
julia --project -e 'using Pkg; Pkg.test()'
julia --project -e 'using Pkg; Pkg.test(coverage=true)'
```

## Reading results into Evidence
```markdown
Command: pytest -q --cov=billing --cov-branch tests/billing
Exit: 0
Result: 214 passed, 0 failed, 3 skipped (unchanged from baseline 3), 0 errors in 18.2s
Diff coverage (diff-cover, branch): 91% of 47 changed lines
```
