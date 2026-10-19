# Effect refactor catalogue

Each entry: the smell, why it hurts, the replacement. Apply one at a time and keep the tests green
(role-based tests survive these refactors unchanged; tests that assert state do not).

## 1. Derived state stored in state

```tsx
// before: two renders per change, and a frame showing stale data
const [visible, setVisible] = useState<Todo[]>([]);
useEffect(() => { setVisible(todos.filter(t => !t.done)); }, [todos]);

// after: computed during render
const visible = todos.filter(t => !t.done);
// only if the Profiler shows the filter is expensive and the compiler is off:
const visible = useMemo(() => todos.filter(t => !t.done), [todos]);
```

## 2. Event logic in an effect

```tsx
// before: runs on mount too, and again if `product` changes
useEffect(() => { if (product.isInCart) showToast(`Added ${product.name}`); }, [product]);

// after: in the handler that caused it
function handleBuy() { addToCart(product); showToast(`Added ${product.name}`); }
```

## 3. Resetting state when an id changes

```tsx
// before
useEffect(() => { setComment(""); }, [userId]);

// after: a new key is a new component instance with fresh state
<Profile userId={userId} key={userId} />
```

## 4. Adjusting some state when a prop changes

```tsx
// before
useEffect(() => { setSelection(null); }, [items]);

// after: store the id, derive the selection
const [selectedId, setSelectedId] = useState<string | null>(null);
const selection = items.find(i => i.id === selectedId) ?? null;   // vanishes when the item does
```

## 5. Fetching in an effect

```tsx
// before: no cache, no dedupe, race-prone, waterfalls, manual loading/error state
useEffect(() => { fetch(`/api/orders?status=${status}`).then(r => r.json()).then(setOrders); }, [status]);

// after (client): TanStack Query; the signal cancels superseded requests
const { data, error, isPending } = useQuery({
  queryKey: ["orders", status],
  queryFn: ({ signal }) => fetchOrders(status, signal),
});
// after (framework): a route loader or Server Component fetches before render
```

If a raw effect is unavoidable, use an `AbortController` (or an `ignore` flag) and clean up.

## 6. Effect chains

```tsx
// before: three renders, hard to follow
useEffect(() => { if (card.gold) setGoldCount(c => c + 1); }, [card]);
useEffect(() => { if (goldCount > 3) { setRound(r => r + 1); setGoldCount(0); } }, [goldCount]);
useEffect(() => { if (round > 5) setGameOver(true); }, [round]);

// after: compute the next state in the event handler (or a reducer), once
function placeCard(next: Card) {
  dispatch({ type: "place", card: next });   // reducer updates gold, round and gameOver together
}
const isGameOver = round > 5;               // derived, not stored
```

## 7. Subscribing to an external store

```tsx
// before
const [online, setOnline] = useState(navigator.onLine);
useEffect(() => {
  const on = () => setOnline(true), off = () => setOnline(false);
  addEventListener("online", on); addEventListener("offline", off);
  return () => { removeEventListener("online", on); removeEventListener("offline", off); };
}, []);

// after
function subscribe(cb: () => void) {
  addEventListener("online", cb); addEventListener("offline", cb);
  return () => { removeEventListener("online", cb); removeEventListener("offline", cb); };
}
const online = useSyncExternalStore(subscribe, () => navigator.onLine, () => true);  // 3rd arg: server snapshot
```

## 8. Reading latest props inside an effect

```tsx
// before: either a missing dependency (stale theme) or a reconnect on every theme change
useEffect(() => {
  const c = createConnection(roomId);
  c.on("connected", () => showNotification("Connected", theme));
  c.connect();
  return () => c.disconnect();
}, [roomId, theme]);

// after (React 19.2+)
const onConnected = useEffectEvent(() => showNotification("Connected", theme));
useEffect(() => {
  const c = createConnection(roomId);
  c.on("connected", onConnected);
  c.connect();
  return () => c.disconnect();
}, [roomId]);
```

Effect events are called only from effects, never passed to children or listed as dependencies.

## 9. Debouncing a search box

```tsx
// before: timer effect + second state copy
useEffect(() => { const t = setTimeout(() => setDebounced(q), 300); return () => clearTimeout(t); }, [q]);

// after: let React deprioritise the expensive part
const deferredQ = useDeferredValue(q);
const results = useQuery({ queryKey: ["search", deferredQ], queryFn: ({ signal }) => search(deferredQ, signal) });
```

`useDeferredValue` does not reduce request count by itself; when the server needs fewer calls keep a
debounce (or `staleTime`), but put it in the query layer, not in an effect that copies state.

## 10. Legitimate effects (keep them, with cleanup)

| Effect | Cleanup |
|---|---|
| WebSocket / SSE connection | close it |
| third-party widget (map, chart, editor) | destroy the instance |
| `IntersectionObserver` / `ResizeObserver` | `disconnect()` |
| document title, `scrollIntoView` after navigation | none needed |
| analytics page view | none; make it idempotent (Strict Mode runs it twice in dev) |

## Review checklist

- Can this value be computed from props and state during render?
- Is this a reaction to a specific user event? Move it to the handler.
- Is it data fetching? Move it to the data layer.
- Does every effect have a cleanup if it subscribes, starts a timer, or creates an instance?
- Would `key` express "start over" better than resetting state?
