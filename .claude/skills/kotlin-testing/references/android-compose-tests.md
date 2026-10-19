# Android, Compose and screenshot tests

Companion to `kotlin-testing`. Versions as of October 2026: Robolectric 4.17, Compose UI test 1.11+
(v2 rules; 1.13 in beta), Roborazzi 1.7x, kotlinx-coroutines-test 1.11.0. UI structure itself is
covered by `kotlin-compose`.

## 1. Module setup

```kotlin
android {
    testOptions {
        unitTests {
            isIncludeAndroidResources = true        // Robolectric needs merged resources and manifest
            all { it.useJUnitPlatform() }          // only if host tests use Jupiter or Kotest
        }
    }
}
dependencies {
    testImplementation("org.robolectric:robolectric:4.17")
    testImplementation(platform(libs.androidx.compose.bom))
    testImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")      // hosts ComponentActivity for createComposeRule
    testImplementation("io.github.takahirom.roborazzi:roborazzi:<version>")
    testImplementation("io.github.takahirom.roborazzi:roborazzi-compose:<version>")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.11.0")
    testRuntimeOnly("org.junit.vintage:junit-vintage-engine")         // Robolectric (JUnit 4) on the JUnit Platform
}
```

Robolectric's supported path is a JUnit 4 runner (`@RunWith(AndroidJUnit4::class)`). On a JUnit Platform
module those classes run through the Vintage engine, which JUnit 6 still ships but marks deprecated (it
logs an INFO discovery issue; `junit.vintage.discovery.issue.reporting.enabled=false` silences it).

## 2. ViewModel tests (no Robolectric needed)

```kotlin
class SearchViewModelTest {
    @get:Rule val main = MainDispatcherRule()                     // StandardTestDispatcher by default

    @Test fun `shows results for the last query only`() = runTest { // reuses Main's scheduler
        val vm = SearchViewModel(FakeSearchRepo(latency = 100.milliseconds))
        vm.state.test {
            assertEquals(SearchUi.Idle, awaitItem())
            vm.onQueryChanged("kotlin")
            assertEquals(SearchUi.Loading("kotlin"), awaitItem())
            assertIs<SearchUi.Results>(awaitItem())
            cancelAndIgnoreRemainingEvents()
        }
    }
}
```

Without the rule, plain JVM host tests fail with "Module with the Main dispatcher is missing" (or "had
failed to initialize" on Android host tests). `viewModelScope` dispatches on `Dispatchers.Main.immediate`,
which the test Main dispatcher replaces.

## 3. Compose UI tests on the JVM

```kotlin
import androidx.compose.ui.test.junit4.v2.createComposeRule      // v1 package is deprecated from ui-test 1.11

@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)                          // real rendering, needed for screenshots
@Config(qualifiers = RobolectricDeviceQualifiers.Pixel5)
class SearchScreenTest {
    @get:Rule val compose = createComposeRule()

    @Test fun `typing updates the field and shows results`() {
        var query = ""
        compose.setContent {
            SearchScreen(state = SearchUi.Results("kotlin", listOf("kotlinx.coroutines")), onQueryChanged = { query = it })
        }
        compose.onNodeWithTag("search-field").performTextInput("flow")
        compose.waitForIdle()                                    // v2: composition work is queued
        assertEquals("flow", query)
        compose.onNodeWithText("kotlinx.coroutines").assertIsDisplayed()
        compose.onRoot().captureRoboImage("src/test/screenshots/search_results.png")
    }
}
```

Timing rules for the v2 APIs (StandardTestDispatcher for composition; v1 used the unconfined one):

| Need | Call |
|---|---|
| let launched effects and recomposition run | `waitForIdle()`, or assert inside `runOnIdle { }` |
| step animations or `delay` in effects manually | `mainClock.autoAdvance = false`, then `mainClock.advanceTimeBy(ms)` |
| run queued work without moving the clock | `mainClock.scheduler.runCurrent()` |
| coroutines plus UI in one clock | `runComposeUiTest { setContent { }; mainClock.advanceTimeBy(1_000 + 16) }` |
| custom contexts or timeout | `ComposeUiTestConfig(effectContext, runTestContext, testTimeout)` (ui-test 1.13.0-alpha01+) |

Do not wrap a `createComposeRule` test in `runTest`: the two schedulers are independent and advancing one
does not move the other. v2 also forces touch input mode at the start of each test
(`ComposeUiTestConfig(inputMode = InputMode.Keyboard)` to change it).

## 4. Roborazzi workflow

| Goal | Gradle task (debug variant) | Property on the unit-test task |
|---|---|---|
| record goldens | `recordRoborazziDebug` | `roborazzi.test.record=true` |
| compare, report only | `compareRoborazziDebug` | `roborazzi.test.compare=true` |
| fail on any diff (CI) | `verifyRoborazziDebug` | `roborazzi.test.verify=true` |
| verify and refresh | `verifyAndRecordRoborazziDebug` | verify + record |
| delete outputs | `clearRoborazziDebug` | |

Images land in `build/outputs/roborazzi` unless a path is passed; the HTML report is
`build/reports/roborazzi/index.html`. Commit goldens, record on one OS and JDK (font rendering differs
between hosts), and review diffs as images in the PR. Capture variants: `onNodeWithTag(...).captureRoboImage()`,
`onView(isRoot()).captureRoboImage()` (Espresso), `view.captureRoboImage()`, or a composable lambda
`captureRoboImage { Text("Hello") }`. Desktop Compose (experimental) uses `roborazzi-compose-desktop`,
`runDesktopComposeUiTest` and `recordRoborazziDesktop`; plain JVM modules use the `Jvm` suffix.

## 5. Instrumented tests

```kotlin
class CheckoutFlowTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()   // v2 package as above
    @Test fun `pays with a saved card`() {
        compose.onNodeWithText("Checkout").performClick()
        compose.onNodeWithTag("pay-button").assertIsEnabled().performClick()
        compose.onNodeWithText("Payment complete").assertIsDisplayed()
    }
}
```

`./gradlew connectedDebugAndroidTest` runs them on a device or emulator. Kotest on device uses
`androidTestImplementation("io.kotest:kotest-runner-junit4:<version>")` and `@RunWith(KotestTestRunner::class)`.
Keep instrumented suites small (navigation, permissions, real rendering); push logic down to host tests.
