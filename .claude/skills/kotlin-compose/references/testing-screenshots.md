# Compose testing and screenshots

Companion to the `kotlin-compose` skill. Test the stateless screen with fake state and callbacks; test
ViewModels without Compose (see `kotlin-testing`); keep screenshot tests for visual regressions only.

## Dependencies (Android)

```kotlin
dependencies {
    val composeBom = platform(libs.androidx.compose.bom)
    androidTestImplementation(composeBom)
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")   // needed by createComposeRule()
}
```

Compose tests also run on the JVM with Robolectric (`testImplementation` of the same artifacts plus
Robolectric, `@RunWith(AndroidJUnit4::class)`), which is what Roborazzi builds on.

## v1 to v2 test APIs

The v2 APIs (in `androidx.compose.ui:ui-test` and `ui-test-junit4` 1.11.0-alpha03 and later) run the
composition on `StandardTestDispatcher` instead of `UnconfinedTestDispatcher`, so launched coroutines are
queued until the test clock advances. The v1 APIs are deprecated but keep the old behavior.

| v1 (deprecated) | v2 |
|---|---|
| `androidx.compose.ui.test.junit4.createComposeRule` | `androidx.compose.ui.test.junit4.v2.createComposeRule` |
| `...junit4.createAndroidComposeRule` | `...junit4.v2.createAndroidComposeRule` |
| `...junit4.createEmptyComposeRule` | `...junit4.v2.createEmptyComposeRule` |
| `androidx.compose.ui.test.runComposeUiTest` | `androidx.compose.ui.test.v2.runComposeUiTest` |
| `...test.runAndroidComposeUiTest` | `...test.v2.runAndroidComposeUiTest` |

Fixes for tests that start failing after the switch: call `waitForIdle()` before asserting, assert inside
`runOnIdle { }`, or run queued work without moving time with `mainClock.scheduler.runCurrent()`. Do not
wrap Compose tests in `runTest { }`: it uses a separate scheduler, so `advanceTimeBy` does not move the
Compose clock. Prefer `runComposeUiTest { }` and `mainClock.advanceTimeBy(ms)`:

```kotlin
@Test fun showsDoneAfterDelay() = runComposeUiTest {
    setContent {
        var status by remember { mutableStateOf("Loading...") }
        LaunchedEffect(Unit) { delay(1000); status = "Done!" }
        Text(status)
    }
    onNodeWithText("Loading...").assertIsDisplayed()
    mainClock.advanceTimeBy(1000 + 16)          // one frame of slack
    onNodeWithText("Done!").assertIsDisplayed()
}
```

Compose UI 1.13 adds `ComposeUiTestConfig(effectContext, runTestContext, testTimeout)` passed to
`createComposeRule(config = ...)` or `runComposeUiTest(config = ...)`.

## Finders, actions and assertions

| Kind | APIs |
|---|---|
| single node | `onNodeWithText("Send")`, `onNodeWithTag("send")`, `onNodeWithContentDescription("Back")`, `onNode(hasText("Send") and hasClickAction())` |
| many nodes | `onAllNodesWithTag("row")`, `.onFirst()`, `.onChildren()`, `.assertCountEquals(3)` |
| matchers | `hasText`, `hasTestTag`, `hasContentDescription`, `hasClickAction`, `isToggleable`, `isFocused`, `hasAnyAncestor(...)` |
| actions | `performClick()`, `performTextInput("x")`, `performTextReplacement("x")`, `performScrollTo()`, `performScrollToIndex(40)`, `performTouchInput { swipeUp() }`, `performImeAction()` |
| assertions | `assertIsDisplayed()`, `assertDoesNotExist()`, `assertTextEquals("x")`, `assertIsOn()`, `assertIsEnabled()`, `assertIsSelected()` |
| debugging | `onRoot().printToLog("TREE")`, `onRoot(useUnmergedTree = true).printToLog("TREE")` |

Semantics: `Button { Text("Send") }` merges its children, so `onNodeWithText("Send")` finds the button;
use `useUnmergedTree = true` to reach the inner `Text`. Prefer finding by text or content description
(what users and accessibility services see); add `Modifier.testTag` for nodes without either. Expose tags
to UI Automator and Macrobenchmark with `Modifier.semantics { testTagsAsResourceId = true }` at the root.

Clock control: `mainClock.autoAdvance = false`, then `mainClock.advanceTimeBy(ms)` or
`advanceTimeByFrame()` to step animations deterministically.

## Compose Multiplatform tests

```kotlin
// commonTest; dependency org.jetbrains.compose.ui:ui-test (same version as Compose Multiplatform)
class CounterTest {
    @OptIn(ExperimentalTestApi::class)
    @Test fun increments() = runComposeUiTest {                 // androidx.compose.ui.test.v2
        setContent { Counter() }
        onNodeWithTag("plus").performClick()
        onNodeWithTag("count").assertTextEquals("1")
    }
}
```

Run per platform: `./gradlew :shared:jvmTest` (desktop needs the desktop runtime for the host OS in
`jvmTest`), `:shared:iosSimulatorArm64Test`, `:shared:wasmJsTest`, and instrumented Android with
`:shared:connectedAndroidTest`. Common tests do not run as Android local (host) tests.

## Screenshot testing

| Tool | Renders with | Strengths | Watch out |
|---|---|---|---|
| Roborazzi | Robolectric native graphics on the JVM | captures any composable or screen in JVM tests, interaction then capture, experimental desktop and iOS support | Robolectric version coupling; rendering differs slightly from devices |
| Paparazzi | Android layoutlib, no device or emulator | fast, deterministic, simple rule API | no real interaction; View/Compose features layoutlib lacks |
| Compose Preview Screenshot Testing | `@Preview` functions in `src/screenshotTest` | reuses previews, Android Studio integration | alpha; standalone plugin setup is being replaced by AGP test suites |

Roborazzi:

```kotlin
// plugin id("io.github.takahirom.roborazzi"); testImplementation roborazzi + roborazzi-compose
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class InboxScreenshotTest {
    @get:Rule val rule = createComposeRule()
    @Test fun inboxWithMessages() {
        rule.setContent { AppTheme { InboxScreen(sampleState, {}, {}, {}) } }
        rule.onRoot().captureRoboImage()                  // file named after the test by default
    }
}
```

Tasks: `./gradlew recordRoborazziDebug` (baseline into `build/outputs/roborazzi` unless configured),
`compareRoborazziDebug` (writes `_compare.png` diffs), `verifyRoborazziDebug` (fails on differences),
`verifyAndRecordRoborazziDebug`. The property `-Proborazzi.test.record=true` does the same through the
regular unit-test task.

Paparazzi:

```kotlin
// plugin id("app.cash.paparazzi")
class InboxPaparazziTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = PIXEL_5, theme = "android:Theme.Material.Light.NoActionBar")
    @Test fun inbox() = paparazzi.snapshot { AppTheme { InboxScreen(sampleState, {}, {}, {}) } }
}
```

Tasks: `recordPaparazziDebug` (goldens in `src/test/snapshots`), `verifyPaparazziDebug` (diffs in
`build/paparazzi/failures`). Store goldens with Git LFS.

Compose Preview Screenshot Testing: plugin `com.android.compose.screenshot`, property
`android.experimental.enableScreenshotTest=true`, previews annotated with `@PreviewTest` under
`src/screenshotTest/kotlin`, tasks `updateDebugScreenshotTest` (references in
`src/screenshotTestDebug/reference`) and `validateDebugScreenshotTest` (HTML report under
`build/reports/screenshotTest/preview/debug/`).

Rules for every tool: pin fonts, locale, time zone and animations (disable or freeze the clock); record
goldens on CI or one agreed machine; review diffs like code; keep the set small (key screens, states and
themes) so failures stay meaningful.

## Previews as test fixtures

```kotlin
class InboxStateProvider : PreviewParameterProvider<InboxUiState> {
    override val values = sequenceOf(InboxUiState(), InboxUiState(messages = sampleMessages), InboxUiState(userMessage = "Offline"))
}

@PreviewLightDark
@PreviewFontScale
@Composable
fun InboxPreview(@PreviewParameter(InboxStateProvider::class) state: InboxUiState) = AppTheme { InboxScreen(state, {}, {}, {}) }
```

Multipreview annotations (`@PreviewLightDark`, `@PreviewFontScale`, `@PreviewScreenSizes`,
`@PreviewDynamicColors`, ui-tooling-preview 1.6+) each render their own variants for every parameter
value; stacking two does not produce their cross product. The same previews feed Compose Preview
Screenshot Testing. In Compose Multiplatform, `androidx.compose.ui.tooling.preview.Preview` works in
`commonMain` since 1.10.
