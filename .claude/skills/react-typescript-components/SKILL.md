---
name: react-typescript-components
description: "React 19.x with TypeScript for maintainable UIs: effect discipline (you might not need an effect, useEffectEvent), state placement and server-state libraries, Actions with useActionState/useOptimistic, typed props and generic components, schema-validated forms, keys and identity, React Compiler and Profiler-led performance, accessibility and behaviour-focused tests. Load when writing, reviewing or debugging React components or hooks."
when_to_use: "Editing .tsx components or use* hooks; effects that loop, race or fire twice in Strict Mode; exhaustive-deps or react-hooks/set-state-in-effect warnings; hydration mismatch errors; slow typing or re-render storms; forms and validation; choosing where state lives; adopting React 19 Actions or the React Compiler; accessibility review of components."
---

# React components with TypeScript

Baseline (October 2026): React 19.3 (19.2 added `useEffectEvent` and `<Activity>`; 19.3 adds
`<ViewTransition>` and Fragment refs), `@types/react` 19.3, TanStack Query 5, React Compiler 1.x
(`babel-plugin-react-compiler`), eslint-plugin-react-hooks 7. Code below was compiled with TS 6 and the
tests run on Vitest 5 + Testing Library + MSW 3. Types in general: `typescript-strict-types`; test
mechanics: `typescript-testing-vitest`.

Deep material: [typing patterns](references/typing-patterns.md) |
[effect refactor catalogue](references/effect-refactors.md)

## 1. Do you need an effect?

| You want to | Do this | Not this |
|---|---|---|
| derive a value from props/state (filtered list, full name, totals) | compute during render; `useMemo` only if the Profiler shows it is costly | `useEffect(() => setFiltered(...), [items])` |
| respond to a user event (submit, click, toggle) | the event handler | an effect watching a "submitted" flag |
| reset state when an id changes | `key={id}` on the component | effect that resets state on `id` |
| adjust part of state when a prop changes | store the previous prop and compare during render, or derive | effect chain |
| fetch data | framework loader, Server Component, or TanStack Query | raw `useEffect` + `fetch` + `setState` |
| subscribe to an external store | `useSyncExternalStore` | effect + state copy |
| sync with a non-React system (socket, DOM API, map widget, analytics on mount) | `useEffect` with cleanup | |
| read latest props inside an effect without re-running it | `useEffectEvent` (19.2+) | omitting deps or a ref hack |

```tsx
function ChatRoom({ roomId, muted }: { roomId: string; muted: boolean }) {
  const [last, setLast] = useState("");
  const onMessage = useEffectEvent((m: string) => { if (!muted) setLast(m); });  // sees latest `muted`
  useEffect(() => {
    const conn = connect(roomId);
    conn.on("message", onMessage);
    return () => conn.close();
  }, [roomId]);                       // muting does not reconnect; effect events are never deps
  return <p aria-live="polite">{last}</p>;
}
```

## 2. Effect correctness

- Dependency arrays are complete: `eslint-plugin-react-hooks` (`reactHooks.configs.flat.recommended`)
  enforces `exhaustive-deps` and the compiler-derived rules (`set-state-in-effect`, `set-state-in-render`,
  `static-components`, `purity`, `refs`). Fix the code, not the array.
- Stale closures: a callback captured by a timer or subscription sees old state; use the updater form
  (`setCount(c => c + 1)`) or `useEffectEvent`.
- Races in async effects: ignore late responses.

```tsx
useEffect(() => {
  const ac = new AbortController();
  fetchProfile(userId, ac.signal).then(setProfile, err => { if (!ac.signal.aborted) setError(err); });
  return () => ac.abort();          // user switches quickly: the old response never lands
}, [userId]);
```

- Strict Mode (dev) mounts, unmounts and re-mounts every component once: double connections, double
  analytics events or leaked intervals mean a missing cleanup, not a Strict Mode bug.
- Objects and functions created during render change every render; as dependencies they re-run the
  effect every time. Create them inside the effect, or depend on primitives.

## 3. Where state lives

| Kind of state | Home |
|---|---|
| UI state of one component (open, hover, draft text) | `useState` / `useReducer` locally |
| shared by siblings | lift to the nearest common parent, pass props |
| low-frequency app-wide (theme, locale, session) | context with a stable value |
| high-frequency shared client state (editor, canvas, multi-panel selection) | external store: Zustand, Redux Toolkit, Jotai (selectors limit re-renders) |
| server data (lists, entities, pagination) | TanStack Query / framework loaders: cache, dedupe, refetch, invalidate |
| shareable view state (filters, sort, page, tab) | the URL (`useSearchParams`), parsed and validated |
| form drafts | the form (uncontrolled inputs or react-hook-form), not global state |

Never copy props into state (`useState(props.value)` only captures the first value); derive, or make
the component fully controlled, or reset it with `key`.

## 4. React 19 APIs

| API | Use |
|---|---|
| `<form action={fn}>` | Actions: `fn(formData)` runs in a transition; uncontrolled fields reset after it completes |
| `useActionState(action, initial)` | `[state, formAction, isPending]`; action receives `(prevState, formData)` |
| `useFormStatus()` (react-dom) | `pending` for a submit button inside the form |
| `useOptimistic(value, reducer?)` | show the expected result while an async transition is pending; afterwards the (refetched) base value shows, so a failed request reverts by itself |
| `use(promise \| context)` | read context conditionally; unwrap a promise created outside render (cached), inside Suspense |
| `ref` as a prop | function components take `ref` directly; `forwardRef` is unnecessary |
| `<Context value={...}>` | provider without `.Provider` |
| `<Activity mode="hidden">` (19.2) | keep hidden UI's state and DOM (tabs, back navigation) while deprioritising it |
| `useEffectEvent` (19.2) | non-reactive logic called from effects |
| `<ViewTransition>` (19.3) | animate transitions with the View Transitions API |

Server Components, Server Actions (`"use server"`) and streaming SSR only through a framework that
implements them (Next.js App Router, React Router framework mode) and its conventions; a plain Vite SPA
uses client components only.

## 5. Typing components

```tsx
type ButtonProps = ComponentProps<"button"> & { variant: "primary" | "ghost" };   // includes `ref` in React 19
export function Button({ variant, className, ref, ...rest }: ButtonProps) {
  return <button ref={ref} className={`btn btn-${variant} ${className ?? ""}`} {...rest} />;
}

interface ListProps<T> { items: readonly T[]; getKey: (item: T) => string; render: (item: T) => ReactNode }
export function List<T>({ items, getKey, render }: ListProps<T>) {     // in arrow form: <T,>(props) =>
  return <ul>{items.map(i => <li key={getKey(i)}>{render(i)}</li>)}</ul>;
}
```

| Need | Type |
|---|---|
| children | `children: ReactNode` (`ReactElement` only when you clone or inspect it) |
| extend a native element | `ComponentProps<"input">` (includes `ref` in React 19 types) |
| mutually exclusive props | discriminated union: `{ variant: "link"; href: string } \| { variant: "button"; onClick: () => void }` |
| event handler | `(e: ChangeEvent<HTMLInputElement>) => void`; prefer `e.currentTarget` (the element the handler is on; `e.target` may be a child and is only `EventTarget` on most event types) |
| JSX return type | infer it; if needed `React.JSX.Element` (the global `JSX` namespace is gone in React 19 types) |
| style object | `CSSProperties` |

Context without `any` or fake defaults:

```tsx
const SessionContext = createContext<Session | undefined>(undefined);
export function useSession(): Session {
  const s = use(SessionContext);
  if (!s) throw new Error("useSession must be used inside <SessionProvider>");
  return s;
}
```

More patterns (polymorphic `as`, compound components, typed reducers): [typing-patterns](references/typing-patterns.md).

## 6. Forms

| Situation | Approach |
|---|---|
| simple form posting to a server or framework action | native `<form action>` + `useActionState`; schema-validate in the action |
| complex client form (dynamic arrays, cross-field rules, per-field async checks) | react-hook-form + `zodResolver` from `@hookform/resolvers/zod` (or the Standard Schema resolver) |
| input must reformat on every keystroke (masks, live counters) | controlled input |
| everything else | uncontrolled inputs (`name` + `defaultValue`), fewer re-renders |

```tsx
async function signupAction(_prev: FormState, formData: FormData): Promise<FormState> {
  const values = { email: String(formData.get("email") ?? ""), name: String(formData.get("name") ?? "") };
  const parsed = Signup.safeParse(values);
  if (!parsed.success) return { ok: false, errors: z.flattenError(parsed.error).fieldErrors, values };
  await api.signup(parsed.data);
  return { ok: true };
}
// in the component
const [state, formAction, isPending] = useActionState(signupAction, initialState);
<form action={formAction} aria-busy={isPending} noValidate>
  <label htmlFor="email">Email</label>
  <input id="email" name="email" type="email" defaultValue={state.values.email}
    aria-invalid={state.errors.email ? true : undefined}
    aria-describedby={state.errors.email ? "email-error" : undefined} />
  {state.errors.email && <p id="email-error">{state.errors.email[0]}</p>}
  <SubmitButton />   {/* useFormStatus().pending disables it: no double submit */}
</form>
```

- Return the submitted values in the error state and feed them to `defaultValue`: the form resets after
  every action.
- `noValidate` when the schema owns validation; otherwise native constraints (`type="email"`, `required`)
  block submission before the action runs and your messages never appear.
- Every error is linked with `aria-describedby` and the field gets `aria-invalid`; focus the first
  invalid field after a failed submit on long forms.

## 7. Lists and identity

- Keys come from data ids. Array index keys break state (inputs, focus, animations) when items are
  inserted, removed or reordered.
- Changing `key` resets a subtree deliberately: `<ProfileForm key={userId} />`.
- Never define a component inside another component: it is a new type every render, so its state and DOM
  are destroyed each time (`react-hooks/static-components` flags it).

## 8. Performance

1. Measure: React DevTools Profiler ("Record why each component rendered"), commit durations, renders per
   interaction. Optimise only components on the critical interaction.
2. React Compiler on (memoizes components and hooks at build time):
   - Next.js 16+: `reactCompiler: true` in `next.config.ts` plus `babel-plugin-react-compiler`.
   - Vite with `@vitejs/plugin-react` 6: `babel({ presets: [reactCompilerPreset()] })` from
     `@rolldown/plugin-babel` (a Rust port via `react({ compiler: true })` is experimental).
   - Then delete `useMemo`/`useCallback`/`memo` noise added without evidence; keep code compiler-friendly
     (pure render, no mutation of props/state, rules of hooks); `"use no memo"` opts a file out.
3. Without the compiler: `memo`, `useMemo`, `useCallback` only where the Profiler shows wasted renders
   of expensive subtrees.
4. Long lists: virtualize (TanStack Virtual `useVirtualizer`) beyond a few hundred rows.
5. Code-split routes and heavy widgets: `lazy(() => import("./Chart"))` inside `<Suspense>`.
6. Keep context values stable and split contexts by update frequency; a context holding
   `{ user, theme, cart }` re-renders every consumer on any change.
7. `useDeferredValue`/`useTransition` keep typing responsive while expensive results catch up.

## 9. Accessibility

| Rule | Check |
|---|---|
| semantic elements first: `<button>`, `<a href>`, `<nav>`, `<main>`, `<table>` | no `onClick` on `div`/`span` (jsx-a11y `click-events-have-key-events`, `no-static-element-interactions`) |
| every input has a label | `getByLabelText` works in tests |
| dialogs manage focus | native `<dialog>` with `showModal()`, or React Aria / Radix primitives; focus returns to the trigger |
| keyboard: everything operable, focus visible | tab through the page; `:focus-visible` styles never removed |
| async status announced | `aria-live="polite"` region for loading/result counts; `role="alert"` for errors |
| images | meaningful `alt`, or `alt=""` for decorative |

Lint with `eslint-plugin-jsx-a11y` (`jsxA11y.flatConfigs.recommended`), test with axe (jsdom smoke check;
Playwright + `@axe-core/playwright` for colour contrast and layout-dependent rules). Visual polish:
`graphic-design`.

## 10. Testing

- Vitest + Testing Library: role queries with accessible names, `userEvent.setup()`, `findBy*` for async.
- MSW for network, one `QueryClient` per test with `retry: false`.
- Playwright for critical journeys (checkout, signup) across real browsers.
- Assert behaviour (text, roles, enabled/pressed/expanded states, URL), never component state, hook
  internals or CSS classes. Details: `typescript-testing-vitest`.

## 11. Pitfalls

- `setState` during render without a guard: infinite render loop ("Too many re-renders").
- Objects/arrays created in render used as effect or memo dependencies: effect runs every render.
- Hydration mismatches: `Date.now()`, `Math.random()`, `toLocaleString()` without a fixed locale/time zone,
  or `typeof window` branches during render; render stable output and update in an effect, or use
  `useSyncExternalStore` with a server snapshot.
- One broad context for everything: re-render storms on every update.
- Effect chains (effect sets A, another effect watches A and sets B): compute in render or in the handler.
- Subscriptions and timers without cleanup: leaks and duplicate events after Strict Mode re-mounts.
- `use(fetchThing())` with a promise created during render: a new promise each render suspends forever.
- `useOptimistic` setter called outside a transition or action: React warns and the value is not kept.

## 12. Worked example: OrdersPage refactor

Before: 6 effects (sync filters from props to state, refetch on filter change, reset page on filter
change, debounce search, update selection count, scroll to top), duplicated `orders`/`filteredOrders`
state, row variants via optional props, index keys. Profiler: 14 renders of the page per keystroke in
search; one race (fast typing showed results for an older query); axe: 2 violations (unlabelled search
input, clickable `div` rows).

After:

```tsx
const StatusFilter = z.union([Status, z.literal("all")]);
function useFilters(): [Filters, (next: Partial<Filters>) => void] {      // URL is the state
  const [params, setParams] = useSearchParams();
  const parsed = Status.safeParse(params.get("status"));
  const filters: Filters = { q: params.get("q") ?? "", status: parsed.success ? parsed.data : "all" };
  const update = (next: Partial<Filters>) => setParams(prev => {
    const p = new URLSearchParams(prev);
    for (const [k, v] of Object.entries(next)) { if (v === "" || v === "all") p.delete(k); else p.set(k, String(v)); }
    return p;
  }, { replace: true });
  return [filters, update];
}

type RowProps =
  | { variant: "order"; order: Order; onToggle: (id: OrderId, next: Status) => Promise<void> }
  | { variant: "skeleton" }
  | { variant: "error"; message: string; onRetry: () => void };

function OrderRow({ order, onToggle }: { order: Order; onToggle: (id: OrderId, next: Status) => Promise<void> }) {
  const [status, setOptimisticStatus] = useOptimistic(order.status);
  const [isPending, startTransition] = useTransition();
  const next: Status = status === "open" ? "paid" : "open";
  return (
    <li>
      {order.customer}: {status}
      <button aria-pressed={status === "paid"} disabled={isPending}
        onClick={() => startTransition(async () => { setOptimisticStatus(next); await onToggle(order.id, next); })}>
        Mark {next} <span className="visually-hidden">for {order.customer}</span>
      </button>
    </li>
  );
}

// in OrdersPage
const [filters, setFilters] = useFilters();
const deferredQ = useDeferredValue(filters.q);                          // replaces the debounce effect
const query = useInfiniteQuery({
  queryKey: ["orders", { ...filters, q: deferredQ }],
  queryFn: ({ pageParam, signal }) => fetchOrderPage({ ...filters, q: deferredQ }, pageParam, signal),
  initialPageParam: null as string | null,
  getNextPageParam: last => last.nextCursor,                            // keyset cursor; null = last page
});
```

`fetchOrderPage` sends `?after=<last id>&limit=50`, validates the response with zod, and passes the
query's `signal` to `fetch`, so superseded searches are cancelled (the race is gone). The status
`<select>` parses its value with `StatusFilter` instead of a cast; the search input has a `<label>`;
rows are `<li>` with real buttons.

Tests (role queries only; all pass on Vitest 5 + MSW 3 + react-router 7 `MemoryRouter`):

```tsx
const list = screen.getByRole("list", { name: "Orders" });
await within(list).findByRole("button", { name: "Mark paid for Ada" });
await user.click(screen.getByRole("button", { name: "Load more" }));     // request has after=ord_2
await user.click(await screen.findByRole("button", { name: "Mark paid for Ada", pressed: false }));
expect(screen.getByRole("button", { name: "Mark open for Ada", pressed: true })).toBeDisabled();  // optimistic
await waitFor(() => expect(screen.getByRole("button", { name: "Mark open for Ada" })).toBeEnabled());
```

Build: React Compiler enabled; 11 manual `useMemo`/`useCallback` removed. Results (scenario figures,
illustrative): renders per keystroke 14 -> 2 (input + deferred list), effects 6 -> 0 in the page (one
remains in a chart widget for a non-React library), axe violations 2 -> 0.

Related: `typescript-strict-types`, `typescript-testing-vitest`, `typescript-build-config`,
`node-runtime-patterns`, `graphic-design`, `code-review-checklist`, hub `coding-general`.
