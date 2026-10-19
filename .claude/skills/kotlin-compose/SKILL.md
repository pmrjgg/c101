---
name: kotlin-compose
description: "Jetpack Compose and Compose Multiplatform UI engineering: the state and recomposition model, remember, rememberSaveable and derivedStateOf, effect APIs, state hoisting with a single UiState, stability and strong skipping, deferred reads, lazy-list keys, Modifier order, type-safe navigation, compiler reports, and UI and screenshot tests. Load when building Compose screens or fixing recomposition, state or performance bugs."
when_to_use: "Editing @Composable code, composeCompiler { } blocks, stability_config.conf, NavHost/NavDisplay routes or Compose UI tests; symptoms such as janky LazyColumn scrolling, recomposition storms, state lost on rotation, effects that restart every recomposition or never restart, endless recomposition from a backwards write, '@Composable invocations can only happen from the context of a @Composable function', flaky createComposeRule tests after moving to the v2 test APIs."
---

# Compose

Baseline (October 2026): Jetpack Compose 1.11/1.12 through the BOM, the Compose compiler shipped with
Kotlin (plugin `org.jetbrains.kotlin.plugin.compose`, always the Kotlin version, 2.4.x), Compose
Multiplatform 1.12.2, Navigation Compose 2.10 (maintenance mode) and Navigation 3 1.2, lifecycle 2.10+.
Flow semantics live in `kotlin-coroutines-flow`, shared non-UI code in `kotlin-multiplatform`, build
setup in `kotlin-gradle-builds`.

Deep material: [performance diagnostics](references/performance-diagnostics.md) |
[testing and screenshots](references/testing-screenshots.md)

## 1. Mental model

Composition runs composables to build a tree of UI nodes. When a snapshot state object changes, Compose
re-runs (recomposes) only the restart scopes that read it, and skips a restartable composable whose
parameters all compare equal. Therefore composables must be idempotent, fast and free of side effects:
they can run once per frame during an animation, be skipped, run in any order or be abandoned mid-way.

| Phase | Work | A state read here invalidates |
|---|---|---|
| composition | runs composables, updates the tree | composition, then layout and draw of that scope |
| layout | measure and place (`Modifier.layout`, `Modifier.offset { }`) | layout and draw |
| draw | `Canvas`, `Modifier.drawBehind { }`, `graphicsLayer { }` | draw only |

Rule: read fast-changing state (scroll, animation) in the latest phase that can use it.

## 2. State APIs

| Need | API | Notes |
|---|---|---|
| local state across recompositions | `var n by remember { mutableIntStateOf(0) }` | `mutableIntStateOf`/`Long`/`Float` avoid boxing |
| survive rotation and process death | `rememberSaveable { mutableStateOf(x) }` | Bundle-saveable types, `@Parcelize`, or a `Saver` |
| result changes less often than its inputs | `val show by remember { derivedStateOf { listState.firstVisibleItemIndex > 0 } }` | not for plain combinations like `"$first $last"` |
| expensive value of inputs | `remember(a, b) { compute(a, b) }` | better: compute in the ViewModel |
| Compose state to Flow | `snapshotFlow { listState.firstVisibleItemIndex }` | cold; emits on change |
| external source to State | `produceState(initialValue, key) { value = load(key) }` | coroutine scoped to the composition |
| Flow to State | `collectAsStateWithLifecycle()` | stops collecting below STARTED; in common code via `org.jetbrains.androidx.lifecycle:lifecycle-runtime-compose` |
| observable collections | `mutableStateListOf()`, `mutableStateMapOf()` | for UI-local lists only |

```kotlin
data class Filter(val query: String, val unreadOnly: Boolean)
val FilterSaver = listSaver<Filter, Any>(
    save = { listOf(it.query, it.unreadOnly) },
    restore = { Filter(it[0] as String, it[1] as Boolean) },
)
@Composable
fun FilterBar(modifier: Modifier = Modifier) {
    var filter by rememberSaveable(stateSaver = FilterSaver) { mutableStateOf(Filter("", false)) }
    // ...
}
```

## 3. Effects

| API | Runs | Restart and cleanup | Typical use |
|---|---|---|---|
| `LaunchedEffect(k1, k2)` | a coroutine on entering the composition | cancelled and relaunched when any key changes, cancelled on leave | load on id change, show a snackbar for a state value, animations |
| `DisposableEffect(k)` | non-suspending setup | `onDispose { }` must be the last statement; runs on key change and on leave | register and unregister listeners |
| `SideEffect { }` | after every successful recomposition | none | push Compose state into non-Compose objects |
| `rememberCoroutineScope()` | scope bound to the call site | cancelled on leave | launch from event handlers (`onClick`) |
| `rememberUpdatedState(v)` | latest value without restarting | none | callbacks used inside long-lived effects |

Key rules: list as keys every value whose change must restart the effect; `LaunchedEffect(Unit)` lives as
long as the call site, so treat it as suspiciously as `while (true)`; never launch coroutines from the
composable body; read lambdas through `rememberUpdatedState` instead of keying on them.

```kotlin
@Composable
fun LifecycleLogger(onStart: () -> Unit, onStop: () -> Unit) {
    val owner = LocalLifecycleOwner.current                  // androidx.lifecycle.compose
    val currentOnStart by rememberUpdatedState(onStart)
    val currentOnStop by rememberUpdatedState(onStop)
    DisposableEffect(owner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_START) currentOnStart()
            else if (event == Lifecycle.Event.ON_STOP) currentOnStop()
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }
}
```

## 4. Architecture

- Split each screen into a stateful route (gets the ViewModel, collects state) and a stateless screen
  `XScreen(state, onEvent..., modifier)` that previews and tests need.
- One immutable `UiState` per screen, exposed as `StateFlow<UiState>` and changed with
  `_state.update { it.copy(...) }`; events flow up as callbacks.
- Model one-off outcomes as state (`userMessage: String?` cleared by `onMessageShown`); see
  `kotlin-coroutines-flow` for the `Channel` alternative.

```kotlin
data class InboxUiState(
    val messages: ImmutableList<MessageUi> = persistentListOf(),
    val refreshing: Boolean = false,
    val userMessage: String? = null,
)

class InboxViewModel(private val repo: InboxRepository) : ViewModel() {
    private val _state = MutableStateFlow(InboxUiState())
    val state: StateFlow<InboxUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            repo.messages().collect { rows -> _state.update { it.copy(messages = rows.map(::toUi).toImmutableList()) } }
        }
    }
    fun refresh() {
        viewModelScope.launch {
            _state.update { it.copy(refreshing = true) }
            val ok = repo.refresh()
            _state.update { it.copy(refreshing = false, userMessage = if (ok) null else "Refresh failed") }
        }
    }
    fun messageShown() = _state.update { it.copy(userMessage = null) }
}

@Composable
fun InboxRoute(vm: InboxViewModel, onOpen: (Long) -> Unit) {
    val state by vm.state.collectAsStateWithLifecycle()
    InboxScreen(state, onRefresh = vm::refresh, onOpen = onOpen, onMessageShown = vm::messageShown)
}
```

## 5. Performance

| Parameter type | Inferred stability |
|---|---|
| primitives, `String`, function types | stable (lambdas always count as stable) |
| class with only `val`s of stable types, compiled by the Compose compiler | stable |
| any class with a `var` property | unstable |
| `List`, `Set`, `Map` (interfaces that may be mutable) | unstable: use `ImmutableList` etc. from `kotlinx-collections-immutable`, a `@Immutable` wrapper, or the stability file |
| class from a module without the Compose compiler (data layer, libraries, `java.time`) | unstable: stability file, Compose runtime + `@Stable` in that module, or a UI model |
| `@Stable` / `@Immutable` | stable by contract, never verified: a wrong annotation breaks updates |

Strong skipping is the default since Kotlin 2.0.20: every restartable composable can skip, unstable
parameters compare by instance (`===`), stable ones by `equals`, and every lambda in a composable is
remembered with its captures as keys. In Kotlin 2.4 the `StrongSkipping` and `IntrinsicRemember` feature
flags are error-deprecated (removal in 2.5), so it cannot be turned off; opt out per function with
`@NonSkippableComposable` and per lambda with `@DontMemoize`. Stability still matters: a repository that
maps rows to new objects on every emission defeats `===`, so unstable rows recompose every time, while
stable rows compare with `equals` and skip.

```kotlin
// build.gradle.kts of each UI module
composeCompiler {
    stabilityConfigurationFiles.add(rootProject.layout.projectDirectory.file("stability_config.conf"))
}
```
```
// stability_config.conf: one class per line; wildcards match whole name segments only
java.time.Instant
com.example.core.model.*
com.example.core.model.**
com.example.Page<*,_>
```

| Instead of | Write | Read moves to |
|---|---|---|
| `Modifier.offset(y = scroll.value.dp)` | `Modifier.offset { IntOffset(0, scroll.value) }` | layout |
| `Modifier.background(animatedColor)` | `Modifier.drawBehind { drawRect(animatedColor) }` | draw |
| `Modifier.alpha(fade)` with animated `fade` | `Modifier.graphicsLayer { alpha = fade }` | draw |
| passing `scroll: Int` into a child | passing `scrollProvider: () -> Int` | the child |

- Backwards write: writing state that was already read in the same composition (`count++` in the body)
  recomposes forever. Write state only in event handlers and effects.
- Lazy lists: `items(list, key = { it.id }, contentType = { it.kind })`. Keys must be unique and
  Bundle-saveable on Android (primitives, `String`, `Parcelable`); they keep item state and scroll
  position when items move. `contentType` lets compositions be reused across items of the same type.
- Sort and filter outside composition (ViewModel), or `remember(list, comparator) { ... }`.

## 6. Modifier rules

| Chain | Effect |
|---|---|
| `padding(16.dp).background(c)` vs `background(c).padding(16.dp)` | first leaves the padding uncolored, second colors it |
| `clickable { }.padding(16.dp)` vs `padding(16.dp).clickable { }` | first makes the padding clickable, second does not |
| `size(50.dp).size(100.dp)` | 50 dp: the first size fixes the constraints (`requiredSize` overrides) |
| `clip(shape).background(c)` vs `background(c).clip(shape)` | first clips the background, second only clips what follows |
| `Modifier.weight(1f)`, `matchParentSize()` | scoped: only on direct children of `Row`/`Column` or `Box` |

Every UI-emitting composable takes `modifier: Modifier = Modifier` as its first optional parameter and
applies it once, to its root element, at the start of the chain. Build custom modifiers by chaining
existing ones; for new behavior implement `Modifier.Node` (`composed { }` is no longer recommended):

```kotlin
fun Modifier.unreadDot(color: Color) = this then UnreadDotElement(color)

private data class UnreadDotElement(val color: Color) : ModifierNodeElement<UnreadDotNode>() {
    override fun create() = UnreadDotNode(color)
    override fun update(node: UnreadDotNode) { node.color = color }    // data class = equals/hashCode
}
private class UnreadDotNode(var color: Color) : DrawModifierNode, Modifier.Node() {
    override fun ContentDrawScope.draw() {
        drawContent()
        drawCircle(color, radius = 4.dp.toPx(), center = Offset(size.width - 6.dp.toPx(), 6.dp.toPx()))
    }
}
```

## 7. Navigation

Navigation Compose 2.8+ has type-safe routes (the `kotlinx-serialization` plugin is required).
Navigation 2 is in maintenance mode (critical fixes only); Navigation 3 (`androidx.navigation3`, 1.0
stable since November 2025, 1.2 in September 2026) hands the back stack to the app.

```kotlin
@Serializable object Inbox
@Serializable data class Conversation(val id: Long)

NavHost(navController, startDestination = Inbox) {
    composable<Inbox> { InboxRoute(viewModel { InboxViewModel(repo) }, onOpen = { navController.navigate(Conversation(it)) }) }
    composable<Conversation> { entry -> ConversationRoute(entry.toRoute<Conversation>().id) }
}   // in a ViewModel: savedStateHandle.toRoute<Conversation>()
```

```kotlin
@Serializable data object InboxKey : NavKey
@Serializable data class ConversationKey(val id: Long) : NavKey

val backStack = rememberNavBackStack(InboxKey)               // saveable list of keys owned by the app
NavDisplay(
    backStack = backStack,
    onBack = { backStack.removeLastOrNull() },
    entryDecorators = listOf(rememberSaveableStateHolderNavEntryDecorator(), rememberViewModelStoreNavEntryDecorator()),
    entryProvider = entryProvider {
        entry<InboxKey> { InboxRoute(viewModel { InboxViewModel(repo) }, onOpen = { backStack.add(ConversationKey(it)) }) }
        entry<ConversationKey> { key -> ConversationRoute(key.id) }
    },
)
```

Choose Navigation 3 for new Compose-only apps and adaptive multi-pane layouts (scenes); keep Navigation 2
for existing graphs. `rememberViewModelStoreNavEntryDecorator` comes from
`androidx.lifecycle:lifecycle-viewmodel-navigation3` and scopes ViewModels to entries. Compose
Multiplatform: `org.jetbrains.androidx.navigation:navigation-compose` (type-safe routes in common code)
and `org.jetbrains.androidx.navigation3:navigation3-ui` (Alpha on non-Android targets as of CMP 1.10;
check its status before adopting).

## 8. Diagnostics

| Tool | Answers | How |
|---|---|---|
| Layout Inspector (Android Studio) | which composables recompose or skip, how often | enable recomposition counts, reset, run the scenario |
| Compose compiler reports | why a composable cannot skip, which classes are unstable | `reportsDestination` / `metricsDestination`, release build |
| composition tracing | where frame time goes, with composable names | `androidx.compose.runtime:runtime-tracing` + system trace |
| Macrobenchmark `FrameTimingMetric` | jank (`frameDurationCpuMs`, `frameOverrunMs`) | `:macrobenchmark` module, physical device |
| baseline profiles | startup and first-scroll jank from JIT | `androidx.baselineprofile` plugin, `./gradlew :app:generateBaselineProfile` |

```kotlin
composeCompiler {
    reportsDestination = layout.buildDirectory.dir("compose_compiler")
    metricsDestination = layout.buildDirectory.dir("compose_compiler")
}
// ./gradlew :app:assembleRelease, then read build/compose_compiler/*-classes.txt and *-composables.txt
```

Report reading, profile generation and benchmark code: [performance-diagnostics](references/performance-diagnostics.md).
Hand deep profiling to the `code-optimizer` agent with the recomposition counts and reports attached.

## 9. Testing

| Layer | Tool |
|---|---|
| screen logic | stateless `XScreen(state, callbacks)` + `createComposeRule()`; v2 rules in `androidx.compose.ui.test.junit4.v2` (ui-test 1.11+) use `StandardTestDispatcher` |
| finders | `onNodeWithText`, `onNodeWithTag` (with `Modifier.testTag`), `onNodeWithContentDescription`, `onAllNodesWithTag`; `useUnmergedTree = true` for text inside merged nodes |
| actions and checks | `performClick`, `performTextInput`, `performScrollToIndex`, `assertIsDisplayed`, `assertTextEquals`, `assertCountEquals` |
| synchronization | `waitForIdle()`, `runOnIdle { }`, `mainClock.advanceTimeBy(ms)` |
| shared UI (CMP) | `runComposeUiTest { }` from `androidx.compose.ui.test.v2`, `@OptIn(ExperimentalTestApi::class)`, dependency `org.jetbrains.compose.ui:ui-test` |
| screenshots | Roborazzi (JVM/Robolectric), Paparazzi (layoutlib), Compose Preview Screenshot Testing (`@PreviewTest`, alpha) |

```kotlin
class InboxScreenTest {
    @get:Rule val rule = createComposeRule()                     // androidx.compose.ui.test.junit4.v2
    @Test fun failureMessageAndRefresh() {
        var refreshes = 0
        rule.setContent {
            InboxScreen(InboxUiState(userMessage = "Refresh failed"), onRefresh = { refreshes++ }, onOpen = {}, onMessageShown = {})
        }
        rule.onNodeWithText("Refresh failed").assertIsDisplayed()
        rule.onNodeWithTag("refresh").performClick()
        rule.runOnIdle { assertEquals(1, refreshes) }
    }
}

class InboxStateProvider : PreviewParameterProvider<InboxUiState> {
    override val values = sequenceOf(InboxUiState(), InboxUiState(messages = sampleMessages), InboxUiState(refreshing = true))
}
@Preview @Composable
fun InboxPreview(@PreviewParameter(InboxStateProvider::class) state: InboxUiState) = InboxScreen(state, {}, {}, {})
```

Screenshot tool setup and the v1-to-v2 migration: [testing-screenshots](references/testing-screenshots.md).

## 10. Compose Multiplatform specifics

- Targets: Android, iOS (Stable since CMP 1.8), desktop, web via Wasm (Beta since CMP 1.9).
- Gradle: plugins `org.jetbrains.compose` and `org.jetbrains.kotlin.plugin.compose`. The `compose.*`
  dependency aliases are deprecated since CMP 1.10: put coordinates in the catalog
  (`org.jetbrains.compose.foundation:foundation`, `org.jetbrains.compose.material3:material3`,
  `org.jetbrains.compose.components:components-resources`, `org.jetbrains.compose.ui:ui-tooling-preview`).
- Resources: `src/commonMain/composeResources/{drawable,font,values,files}`, qualifiers such as
  `values-de`, `drawable-dark`, `drawable-xxhdpi`. A generated `Res` class (internal, package
  `{group}.{module}.generated.resources`) gives `stringResource(Res.string.app_name)`,
  `pluralStringResource(Res.plurals.x, n, n)`, `painterResource(Res.drawable.logo)`, `Font(Res.font.inter)`,
  `Res.readBytes("files/data.json")`; outside composition use `suspend getString(Res.string.x)`.
  Configure with `compose.resources { publicResClass = true; packageOfResClass = "..." }`. Modules on the
  Android-KMP library plugin need `androidResources { enable = true }`.
- Previews: `androidx.compose.ui.tooling.preview.Preview` works in `commonMain` since CMP 1.10.
- Interop: `UIKitView(factory = { MKMapView() }, modifier = Modifier.size(300.dp))` and
  `UIKitViewController(factory = ..., modifier = ...)`, tuned with `properties = UIKitInteropProperties(...)`;
  on Android `AndroidView(factory = { ctx -> MapView(ctx) }, update = { ... }, onRelease = { ... })`.
- iOS host: `fun MainViewController() = ComposeUIViewController { App() }`, wrapped in a SwiftUI
  `UIViewControllerRepresentable`. Info.plist needs `CADisableMinimumFrameDurationOnPhone`, otherwise the app
  crashes at runtime.
- iOS lifecycle (with `lifecycle-runtime-compose` in common): `viewWillAppear` = ON_START,
  `didBecomeActive` = ON_RESUME, `willResignActive` = ON_PAUSE, `didEnterBackground` and `viewDidDisappear`
  = ON_STOP, leaving the window hierarchy = ON_DESTROY. Desktop needs `kotlinx-coroutines-swing` for
  `Dispatchers.Main`.

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| whole screen recomposes while scrolling | scroll state read in the screen body | `derivedStateOf`, or lambda modifiers that read in layout/draw |
| every row recomposes when one item changes | unstable row model plus new instances per emission | stable UI model (`ImmutableList`), keep instances, keys |
| item state jumps to another row after insert | no `key` in `items` | `key = { it.id }` |
| state resets on rotation | `remember` instead of `rememberSaveable`, or state in the composable instead of the ViewModel | `rememberSaveable` for UI state, ViewModel for screen state |
| effect restarts on every recomposition | key is a new object or lambda each time | stable keys; `rememberUpdatedState` for callbacks |
| effect never sees new values | constant key with captured values | add the value as a key, or `rememberUpdatedState` |
| `@Stable` class updates do not show | the annotation lies (mutable fields without snapshot state) | real immutability or `mutableStateOf` fields |
| tests pass locally, fail after v2 rules | `StandardTestDispatcher` queues coroutines | `waitForIdle()`, `runOnIdle { }`, `mainClock` |
| 'Starting in Kotlin 2.0, the Compose Compiler Gradle plugin is required when compose is enabled' | pre-2.0 `kotlinCompilerExtensionVersion` setup | apply `org.jetbrains.kotlin.plugin.compose` (Kotlin version), delete the old option |

## 12. Worked example: a recomposition storm on an inbox list

Before: 400 messages; scrolling is janky and toggling one message makes every visible row flash in the
Layout Inspector.

```kotlin
data class Message(val id: Long, val sender: String, val preview: String, val labels: List<String>)

@Composable
fun InboxList(messages: List<Message>, selected: Set<Long>, onToggle: (Long) -> Unit) {
    val listState = rememberLazyListState()
    val elevated = listState.firstVisibleItemIndex > 0 || listState.firstVisibleItemScrollOffset > 0
    Column {
        TopBar(elevated = elevated)
        LazyColumn(state = listState) {
            items(messages) { m -> MessageRow(m, selected = m.id in selected, onToggle = { onToggle(m.id) }) }
        }
    }
}
```

Diagnosis: (1) `firstVisibleItemScrollOffset` is read in composition, so `InboxList` recomposes on every
scrolled pixel; (2) `Message` is unstable (`labels: List<String>`) and the repository maps rows to new
`Message` objects on each emission, so strong skipping's `===` check fails for every row; (3) without keys,
rows are identified by position. The classes report confirms (2):
`unstable class Message { ... unstable val labels: List<String> <runtime stability> = Unstable }`.

After:

```kotlin
data class MessageUi(val id: Long, val sender: String, val preview: String, val labels: ImmutableList<String>)

@Composable
fun InboxList(
    messages: ImmutableList<MessageUi>, selected: ImmutableSet<Long>,
    onToggle: (Long) -> Unit, modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()
    val elevated by remember {
        derivedStateOf { listState.firstVisibleItemIndex > 0 || listState.firstVisibleItemScrollOffset > 0 }
    }
    Column(modifier) {
        TopBar(elevated = elevated)                                   // recomposes when the Boolean flips
        LazyColumn(state = listState, modifier = Modifier.testTag("inbox")) {
            items(messages, key = { it.id }) { m ->
                MessageRow(m, selected = m.id in selected, onToggle = onToggle)   // row calls onToggle(m.id)
            }
        }
    }
}
```

The mapper builds `MessageUi` with `labels.toImmutableList()`; the classes report now shows
`stable class MessageUi`. Verify with the same scenario (Layout Inspector, counts reset, fling from the top
to message 200, then toggle message 3). Example readings from this scenario:

| Composable | Before | After |
|---|---|---|
| `InboxList` recompositions during the fling | 312 | 2 (initial state and the elevation flip) |
| `MessageRow` recompositions during the fling | 2,540 | 0 (rows entering the viewport compose, they do not recompose) |
| rows recomposed by toggling one message | 11 (all visible) | 1 |
| rows recomposed after a new message arrives at the top | 11, scroll jumps | 0 recomposed, 1 composed, position kept |

Lock it in: a Macrobenchmark scroll test with `FrameTimingMetric` on the `inbox` tag, and a
`createComposeRule` test asserting that toggling message 3 changes only its checkbox state.

Related: `kotlin-coroutines-flow`, `kotlin-multiplatform`, `kotlin-gradle-builds`, `kotlin-testing`,
`kotlin-java-interop`, `performance-optimization`, hub `kotlin-craft`
