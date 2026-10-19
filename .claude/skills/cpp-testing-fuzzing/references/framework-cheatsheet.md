# GoogleTest, GMock, Catch2 and doctest cheat sheet

## Wiring each framework into CMake

```cmake
include(FetchContent)
# GoogleTest 1.17.x requires C++17
FetchContent_Declare(googletest GIT_REPOSITORY https://github.com/google/googletest.git
                     GIT_TAG <release tag or commit> FIND_PACKAGE_ARGS NAMES GTest)
FetchContent_MakeAvailable(googletest)
add_executable(unit_tests cache_test.cpp)
target_link_libraries(unit_tests PRIVATE mylib GTest::gtest_main GTest::gmock)
include(GoogleTest)
gtest_discover_tests(unit_tests DISCOVERY_MODE PRE_TEST)

# Catch2 v3
FetchContent_Declare(Catch2 GIT_REPOSITORY https://github.com/catchorg/Catch2.git GIT_TAG v3.8.1
                     FIND_PACKAGE_ARGS 3)
FetchContent_MakeAvailable(Catch2)
list(APPEND CMAKE_MODULE_PATH ${catch2_SOURCE_DIR}/extras)   # only needed when fetched
include(Catch)
target_link_libraries(cat_tests PRIVATE mylib Catch2::Catch2WithMain)
catch_discover_tests(cat_tests ADD_TAGS_AS_LABELS)

# doctest: targets doctest::doctest and doctest::doctest_with_main; doctest_discover_tests()
# comes from doctest's scripts/cmake/doctest.cmake (include(doctest) once it is on the module path)
```

`gtest_discover_tests` options: `TEST_PREFIX`, `TEST_SUFFIX`, `EXTRA_ARGS`, `WORKING_DIRECTORY`,
`PROPERTIES`, `DISCOVERY_TIMEOUT`, `DISCOVERY_MODE <POST_BUILD|PRE_TEST>` (3.18), default from
`CMAKE_GTEST_DISCOVER_TESTS_DISCOVERY_MODE`. `catch_discover_tests` options: `TEST_SPEC`,
`EXTRA_ARGS`, `REPORTER`, `OUTPUT_DIR` (per-test report files, safe with `-j`), `DISCOVERY_MODE`,
`SKIP_IS_FAILURE`, `ADD_TAGS_AS_LABELS`; on Apple silicon with the Xcode generator use `PRE_TEST`.

## GoogleTest assertions

| Family | Macros |
|---|---|
| boolean / equality | `EXPECT_TRUE`, `EXPECT_EQ`, `EXPECT_NE`, `EXPECT_LT/LE/GT/GE` (`ASSERT_` forms abort the test) |
| strings (C) | `EXPECT_STREQ`, `EXPECT_STRCASEEQ` (for `std::string` use `EXPECT_EQ`) |
| floating point | `EXPECT_DOUBLE_EQ` (4 ULP), `EXPECT_NEAR(a, b, abs_err)` |
| exceptions | `EXPECT_THROW(stmt, Type)`, `EXPECT_ANY_THROW`, `EXPECT_NO_THROW` |
| matchers | `EXPECT_THAT(value, matcher)` |
| death | `EXPECT_DEATH(stmt, regex)`, `EXPECT_EXIT(stmt, ExitedWithCode(n) / KilledBySignal(SIGABRT), regex)`, `EXPECT_DEBUG_DEATH` |
| control | `GTEST_SKIP() << why`, `FAIL() << why`, `SUCCEED()`, `ADD_FAILURE()` |
| context | `SCOPED_TRACE(msg)` (adds a trace line to failures inside the scope) |

Fixtures: `class F : public ::testing::Test { protected: void SetUp() override; void TearDown() override; };`
then `TEST_F(F, Name)`. Suite-level setup: `static void SetUpTestSuite()`. Global:
`::testing::AddGlobalTestEnvironment(new Env)` before `RUN_ALL_TESTS()`.

Parameter generators: `Values(a, b)`, `ValuesIn(container)`, `Range(begin, end, step)`, `Bool()`,
`Combine(g1, g2)`; name generator `PrintToStringParamName()` or a lambda taking
`const ::testing::TestParamInfo<T>&` returning a valid identifier.

Runner flags: `--gtest_filter=Pos*:-*Slow*`, `--gtest_list_tests`, `--gtest_shuffle`,
`--gtest_random_seed=N`, `--gtest_repeat=N`, `--gtest_fail_fast`, `--gtest_break_on_failure`,
`--gtest_brief=1`, `--gtest_output=xml:report.xml`, `--gtest_death_test_style=threadsafe`.

## GMock

| Piece | Syntax |
|---|---|
| declare | `MOCK_METHOD(Ret, name, (Args...), (const, override, noexcept))` |
| default behaviour | `ON_CALL(m, f(_)).WillByDefault(Return(0));` |
| expectation | `EXPECT_CALL(m, f(Gt(3))).Times(2).WillOnce(Return(1)).WillRepeatedly(Return(0));` |
| cardinality | `Times(n)`, `AtLeast(n)`, `AtMost(n)`, `Between(a, b)`, `.RetiresOnSaturation()` |
| actions | `Return(v)`, `ReturnRef(x)`, `ReturnArg<0>()`, `Throw(e)`, `DoAll(SaveArg<0>(&x), Return(1))`, or a lambda `.WillOnce([](int x) { return x * 2; })` |
| order | `::testing::InSequence seq;` in scope, or `Sequence s;` + `.InSequence(s)` per expectation |
| strictness | `NiceMock<M>` (silent), `NaggyMock<M>` (default, warns), `StrictMock<M>` (fails on uninteresting calls) |
| verify early | `::testing::Mock::VerifyAndClearExpectations(&m);` |

Rules: one behaviour per test; expectations set before the code under test runs; prefer fakes
(in-memory repository, fake clock) over mocks for state; mock only interfaces you own.

## Catch2 v3 macros

| Need | Macro |
|---|---|
| check / stop | `CHECK(expr)` continues, `REQUIRE(expr)` stops the test case; `_FALSE` variants |
| matchers | `CHECK_THAT(x, m)`, `REQUIRE_THAT(x, m)`; combine with `&&`, `||`, `!` |
| exceptions | `REQUIRE_THROWS(e)`, `REQUIRE_THROWS_AS(e, T)`, `REQUIRE_THROWS_WITH(e, ContainsSubstring("x"))`, `REQUIRE_THROWS_MATCHES(e, T, Message("..."))`, `REQUIRE_NOTHROW(e)` |
| context | `INFO(msg)` (scoped), `UNSCOPED_INFO(msg)`, `CAPTURE(a, b)` |
| fixtures | `TEST_CASE_METHOD(Fixture, "name", "[tag]")` |
| type-parameterized | `TEMPLATE_TEST_CASE("name", "[tag]", int, float)` with `TestType` (`<catch2/catch_template_test_macros.hpp>`) |
| skipping | `SKIP("reason")` (3.3+); `SKIP_IS_FAILURE` in discovery turns skips red |
| scenario style | `SCENARIO`, `GIVEN`, `WHEN`, `THEN` (sections underneath) |

Matcher headers: `catch2/matchers/catch_matchers_string.hpp` (`StartsWith`, `EndsWith`,
`ContainsSubstring`, `Equals`, `Matches`), `catch_matchers_floating_point.hpp` (`WithinAbs`,
`WithinRel`, `WithinULP`), `catch_matchers_container_properties.hpp` (`IsEmpty`, `SizeIs`),
`catch_matchers_contains.hpp` (`Contains`), `catch_matchers_quantifiers.hpp` (`AllMatch`,
`AnyMatch`, `NoneMatch`), `catch_matchers_range_equals.hpp` (`RangeEquals`,
`UnorderedRangeEquals`), `catch_matchers_predicate.hpp` (`Predicate`), `catch_matchers_exception.hpp`
(`Message`, `MessageMatches`), or all at once via `catch2/matchers/catch_matchers_all.hpp` (slower
to compile).

CLI: test spec `"[a][b]"` (both tags), `"[a],[b]"` (either), `"~[slow]"` (exclude), hidden tag
`[.]` runs only when named; `--list-tests`, `-a` abort on first failure, `-x N`, `-d yes`
(durations), `--warn NoAssertions`, `--allow-running-no-tests`, `--order decl|lex|rand`,
`--rng-seed time|random-device|N`, `--shard-count/--shard-index`, reporters `-r
console|compact|junit|xml|json|tap|teamcity|sonarqube|automake` with `::out=file` (several `-r`
allowed), `--skip-benchmarks`, `--benchmark-samples N` (default 100).

## doctest in one table

| Catch2 | doctest |
|---|---|
| `TEST_CASE("n", "[t]")` | `TEST_CASE("n" * doctest::test_suite("t"))` |
| `SECTION` | `SUBCASE` |
| `Catch::Approx` | `doctest::Approx` |
| main | `#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN` in one TU, or `doctest::doctest_with_main` |
| tests inside production headers | allowed; `DOCTEST_CONFIG_DISABLE` strips them from release builds |
