# React + TypeScript typing patterns

All snippets compile with TypeScript 6.0 and `@types/react` 19.3 under `strict` and
`noUncheckedIndexedAccess`; lines marked `@ts-expect-error` really are errors.

## 1. Extending native elements

```tsx
type ButtonProps = ComponentProps<"button"> & { variant: "primary" | "ghost" };   // includes ref
export function Button({ variant, className, ref, ...rest }: ButtonProps) {
  return <button ref={ref} className={`btn btn-${variant} ${className ?? ""}`} {...rest} />;
}
```

`ComponentPropsWithoutRef<"button">` when the component must not accept a ref. Default `type="button"`
inside forms, or every button submits.

## 2. Discriminated props (mutually exclusive variants)

```tsx
type LinkOrButton =
  | ({ kind: "link" } & ComponentPropsWithoutRef<"a">)
  | ({ kind: "button" } & ComponentPropsWithoutRef<"button">);

export function Action(props: LinkOrButton) {
  if (props.kind === "link") { const { kind, ...rest } = props; return <a {...rest} />; }
  const { kind, ...rest } = props;
  return <button type="button" {...rest} />;
}
// @ts-expect-error href is not allowed on the button variant
<Action kind="button" href="/x" />;
```

Destructure after narrowing; destructuring before the check loses the correlation between fields.

## 3. Polymorphic `as` prop

```tsx
type BoxProps<E extends ElementType> =
  { as?: E; children?: ReactNode } & Omit<ComponentPropsWithoutRef<E>, "as" | "children">;

export function Box<E extends ElementType = "div">({ as, ...rest }: BoxProps<E>) {
  const Tag: ElementType = as ?? "div";
  return <Tag {...rest} />;
}
<Box as="a" href="/x">link</Box>;
// @ts-expect-error href is not a div prop
<Box href="/x">no</Box>;
```

Polymorphic components are expensive for the checker in large design systems; prefer a small set of
explicit components (`<LinkButton>`, `<Button>`) unless the flexibility is used widely.

## 4. Generic components

```tsx
interface SelectProps<V extends string> {
  label: string; value: V; options: readonly { value: V; label: string }[]; onChange: (v: V) => void;
}
export function Select<V extends string>({ label, value, options, onChange }: SelectProps<V>) {
  return (
    <label>{label}
      <select value={value} onChange={e => {
        const hit = options.find(o => o.value === e.currentTarget.value);   // no cast: map back to V
        if (hit) onChange(hit.value);
      }}>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}
<Select label="Size" value="m" options={[{ value: "s", label: "S" }, { value: "m", label: "M" }] as const}
        onChange={v => { /* v: "s" | "m" */ }} />;
```

In `.tsx` arrow functions write `<T,>(props: P<T>) => ...`; `<T>` alone parses as JSX.

## 5. Typed reducer with a discriminated state

```tsx
type State =
  | { status: "idle" } | { status: "loading" }
  | { status: "error"; message: string } | { status: "done"; ids: readonly string[] };
type Action =
  | { type: "start" } | { type: "fail"; message: string }
  | { type: "succeed"; ids: readonly string[] } | { type: "reset" };

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case "start": return { status: "loading" };
    case "fail": return { status: "error", message: a.message };
    case "succeed": return { status: "done", ids: a.ids };
    case "reset": return { status: "idle" };
  }
}
const [state, dispatch] = useReducer(reducer, { status: "idle" });
```

With `noImplicitReturns` and an exhaustive `switch`, adding an action type without a case fails to compile.

## 6. Compound components with a guarded context

```tsx
type TabsCtx = { active: string; setActive: (id: string) => void };
const Ctx = createContext<TabsCtx | undefined>(undefined);
function useTabs(): TabsCtx {
  const v = use(Ctx);
  if (!v) throw new Error("Tabs.* must be used inside <Tabs>");
  return v;
}
export function Tabs({ initial, children }: { initial: string; children: ReactNode }) {
  const [active, setActive] = useState(initial);
  return <Ctx value={{ active, setActive }}><div role="tablist">{children}</div></Ctx>;
}
Tabs.Tab = function Tab({ id, children }: { id: string; children: ReactNode }) {
  const { active, setActive } = useTabs();
  return <button role="tab" aria-selected={active === id} onClick={() => setActive(id)}>{children}</button>;
};
```

A full accessible tabs widget also needs arrow-key navigation and `aria-controls`; use React Aria or Radix
primitives rather than hand-rolling.

## 7. Hooks

```tsx
export function useToggle(initial = false) {
  const [on, setOn] = useState(initial);
  return [on, () => setOn(o => !o)] as const;   // readonly tuple, not (boolean | (() => void))[]
}
```

- Return objects when a hook returns more than two values (`{ data, error, refetch }`), tuples for two.
- Type the hook's return explicitly when it is part of a public API (enables `isolatedDeclarations` and
  stable `expectTypeOf` tests).
- `useRef<HTMLInputElement>(null)` for DOM refs (`RefObject<HTMLInputElement | null>` in React 19 types);
  `useRef<number | undefined>(undefined)` for mutable values.

## 8. Events and forms

| Event | Type |
|---|---|
| input change | `ChangeEvent<HTMLInputElement>` |
| select change | `ChangeEvent<HTMLSelectElement>` |
| form submit (manual handler) | `SubmitEvent<HTMLFormElement>` with `e.preventDefault()` (`FormEvent` is marked deprecated in `@types/react` 19.3); prefer `<form action>` |
| key | `KeyboardEvent<HTMLElement>`; compare `e.key` (`"Enter"`, `"Escape"`) |
| pointer | `PointerEvent<HTMLElement>` covers mouse, pen and touch |

Read `FormData` with `String(formData.get("name") ?? "")` and validate with a schema; `formData.get`
returns `FormDataEntryValue | null` (string or `File`).

## 9. Things that are not types

- Prop drilling five levels is a design smell, not a typing problem: compose with `children` first,
  context second.
- `React.FC` adds nothing in React 19 (no implicit `children` since 18); plain functions with typed props
  are the convention.
- `defaultProps` on function components is gone in React 19; use default parameter values.
