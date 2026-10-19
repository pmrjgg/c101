---
name: typescript-strict-types
description: "Type-safe TypeScript (6.x and Go-native 7.x): strictness flags and adoption order, discriminated unions, branded types, as const and satisfies, exhaustive switches, generics with const type parameters and NoInfer, narrowing and type predicates, runtime validation at boundaries (zod 4, valibot, Standard Schema), escape-hatch lint policy, a compiler-error-to-fix table and type tests. Load when writing, reviewing or fixing TypeScript types."
when_to_use: "Editing .ts/.tsx/.mts/.cts files; errors such as TS2322, TS2345, TS2532, TS18048, TS7006, TS2339, TS2589, TS1484, TS2375 or TS4111; turning on strict flags in a legacy codebase; replacing any/as/! casts; designing domain types or validating JSON, env or webhook input."
---

# TypeScript strict types

Baseline: TypeScript **6.0.x** (last JS-based compiler, full programmatic API) and **7.0.x** (Go-native
`tsc`, released July 2026, no stable programmatic API until 7.1). Diagnostics below were checked on
6.0.3 and 7.0.2; codes are identical unless noted. Check the repo first: `npx tsc -v`,
`grep -n '"typescript"' package.json`. Build and module settings live in `typescript-build-config`.

Deep material: [error code catalogue](references/error-codes.md) |
[legacy strictness migration scripts](references/legacy-migration.md)

## 1. Strictness flags

Since TS 6.0 `strict` defaults to `true` when unset; set it explicitly anyway so 5.x tools agree.

| Flag | Catches | Typical diagnostic | Adopt in new code |
|---|---|---|---|
| `strict` (bundle: `strictNullChecks`, `noImplicitAny`, `strictFunctionTypes`, `strictBindCallApply`, `strictPropertyInitialization`, `useUnknownInCatchVariables`, `noImplicitThis`, `alwaysStrict`) | null/undefined misuse, implicit any, unsound callbacks | TS2532, TS18048, TS7006 | always |
| `noUncheckedIndexedAccess` | `arr[i]` and `rec[key]` assumed present | TS2322 `string \| undefined` | always |
| `exactOptionalPropertyTypes` | `{ p: undefined }` passed where `p?: string` | TS2375 / TS2379 | new code; costly retrofit |
| `noImplicitOverride` | overriding a base method by accident | TS4114 | always |
| `noPropertyAccessFromIndexSignature` | `obj.typo` on index-signature types | TS4111 | always |
| `noFallthroughCasesInSwitch` | missing `break`/`return` | TS7029 | always |
| `noImplicitReturns` | some paths return nothing | TS7030 | always |
| `verbatimModuleSyntax` | type imports emitted as runtime imports | TS1484 | always (needed for type stripping) |
| `isolatedModules` | constructs single-file transpilers (esbuild, swc, Node) cannot handle | TS1205 (type re-export), TS2748 (ambient const enum) | `verbatimModuleSyntax` reports the same cases |
| `erasableSyntaxOnly` | enums, namespaces with values, parameter properties | TS1294 | when Node runs `.ts` directly |

### Adoption order for legacy code

1. Order: `strictNullChecks` (most real bugs), then `noImplicitAny`, then the remaining `strict`
   members, then `noUncheckedIndexedAccess`, and `exactOptionalPropertyTypes` last. A 5.x repo
   upgrading to 6.x gets `strict` by default: pin `"strict": false` first, then walk the flags.
2. Count errors per flag before choosing the order of directories:
   `npx tsc --noEmit -p . --strictNullChecks true 2>&1 | grep -c 'error TS'`
   (one run per flag; the script in [legacy-migration](references/legacy-migration.md) does all).
3. Turn the flag on globally, then suppress the backlog with `// @ts-expect-error <ticket>` on each line.
   Never `@ts-ignore`: `@ts-expect-error` fails with TS2578 once the error is fixed, so the backlog
   shrinks visibly. Gate CI on the count of `@ts-expect-error` not increasing (ratchet).
4. Fix by directory, leaf modules first (fewest dependents), shared types last.

## 2. Modelling

Replace optional-field bags with discriminated unions: every state carries exactly its own fields.

```ts
type Result<T, E = Error> = { kind: "ok"; value: T } | { kind: "err"; error: E };

type Fetch<T> =
  | { state: "idle" }
  | { state: "loading"; startedAt: number }
  | { state: "done"; data: T }
  | { state: "failed"; error: Error; retryable: boolean };
```

Exhaustiveness: the `default` branch must receive `never`; adding a variant breaks the build.

```ts
export function assertNever(x: never, msg = "unhandled variant"): never {
  throw new Error(`${msg}: ${JSON.stringify(x)}`);
}
function render(f: Fetch<string>): string {
  switch (f.state) {
    case "idle": return "";
    case "loading": return "...";
    case "done": return f.data;
    case "failed": return f.retryable ? "retry" : f.error.message;
    default: return assertNever(f);   // TS2345 if a state is missing
  }
}
```

`x satisfies never;` as a statement also works (TS1360) but `return x satisfies never` in a function
returning `string` reports two errors; prefer `assertNever`.

Branded types stop mixing structurally identical primitives. Create them only through validating
constructors so a brand is a proof:

```ts
type UserId = string & { readonly __brand: "UserId" };
type Cents = number & { readonly __brand: "Cents" };
function toUserId(s: string): UserId {
  if (!/^usr_[a-z0-9]{12}$/.test(s)) throw new RangeError(`bad user id ${s}`);
  return s as UserId;                       // the only `as` allowed: after the proof
}
```

Template literal types for string formats:

```ts
type Route = `/${string}`;
type CssLength = `${number}px` | `${number}rem`;
type EventName = `order.${"created" | "paid"}`;
```

Inputs are `readonly`: `function total(items: readonly LineItem[])`, `ReadonlyMap<K, V>`,
`Readonly<Config>`. A function that cannot mutate its argument cannot surprise its caller.

## 3. Literals and objects

Prefer `as const` objects over `enum`. Enums emit runtime code, numeric enums reverse-map and accept
any number in older versions, and `erasableSyntaxOnly` (Node type stripping) rejects them (TS1294).

```ts
export const Role = { Admin: "admin", Member: "member", Guest: "guest" } as const;
export type Role = (typeof Role)[keyof typeof Role];      // "admin" | "member" | "guest"
export const ROLES = Object.values(Role);                  // runtime list for validation
```

`satisfies` checks a value against a type without widening it, so literal keys and values survive:

```ts
type Route = { path: `/${string}`; auth: boolean };
const routes = {
  home: { path: "/", auth: false },
  orders: { path: "/orders", auth: true },
} satisfies Record<string, Route>;
routes.orders.path;          // type "/orders"; routes.nope -> TS2339 (annotation would allow any key)
```

| Want | Write |
|---|---|
| check shape, keep literal types | `const x = {...} satisfies T` |
| check shape, deeply readonly literals | `const x = {...} as const satisfies T` |
| widen to `T` on purpose (mutable later) | `const x: T = {...}` |
| assert a fact the compiler cannot see | `as T` plus a comment naming the proof |

## 4. Generics

| Rule | Example |
|---|---|
| constrain to what you use | `function byId<T extends { id: string }>(xs: readonly T[], id: string): T \| undefined` |
| let inference work from arguments; do not make callers pass `<T>` | `groupBy(orders, o => o.status)` |
| `const` type parameter to keep literals (TS 5.0+) | `function pick<const K extends readonly string[]>(keys: K): K[number]` |
| `NoInfer<T>` blocks an inference site (TS 5.4+) | `function fsm<S extends string>(states: S[], initial: NoInfer<S>)` -> `fsm(["idle","busy"], "done")` is TS2345 |
| a type parameter used once is not generic | `<T>(x: T): void` -> `(x: unknown): void` |
| return types that depend on input use overloads or conditional types, not `any` | see section 8 |

## 5. Narrowing

| Technique | Use for |
|---|---|
| `typeof x === "string"`, `Array.isArray(x)` | primitives, arrays |
| `x instanceof Date` | classes in the same realm (not across iframes or worker boundaries) |
| `"code" in err` | object unions without a discriminant |
| `switch (x.kind)` / `if (x.kind === "ok")` | discriminated unions (best) |
| `function isUser(x: unknown): x is User` | reusable checks; the body must actually prove it |
| inferred predicates (TS 5.5+) | `xs.filter(x => x !== undefined)` yields `T[]` with no annotation |
| `function assertUser(x: unknown): asserts x is User` | throw-or-continue at boundaries |
| `catch (e: unknown)` then `e instanceof Error ? e.message : String(e)` | `useUnknownInCatchVariables` (in `strict`) |

Narrowing is lost when the compiler cannot prove nothing changed:

```ts
if (order.discount) {
  items.forEach(i => apply(i, order.discount));   // TS2345: property narrowing is dropped in callbacks
  await save();
  apply(1, order.discount);                        // compiles, yet save() may have cleared it (unsound)
}
const discount = order.discount;                   // fix: copy to a const, narrow the const
if (discount) items.forEach(i => apply(i, discount));
```

A `let` narrowed before a closure stays narrowed inside it only if it is never assigned after the
closure is created (TS 5.4+); otherwise copy to a `const`. The compiler does not invalidate property
narrowing after calls, so re-read mutable state after any `await`.

## 6. Boundaries: unknown until validated

Network responses, `JSON.parse`, `localStorage`, `postMessage`, `process.env`, queue messages and
webhook bodies are `unknown`. Validate once at the edge, then pass precise types inward. `as` on
`await res.json()` is a lie that typecheckers cannot catch.

```ts
import * as z from "zod";                                  // zod 4

const Order = z.object({
  id: z.string().regex(/^ord_[A-Za-z0-9]{10}$/).brand<"OrderId">(),
  total: z.number().int().nonnegative(),
  email: z.email(),
  placedAt: z.coerce.date(),
});
export type Order = z.infer<typeof Order>;

const r = Order.safeParse(await res.json());
if (!r.success) throw new Error(z.prettifyError(r.error));  // or z.flattenError(r.error) for forms
```

| Library | Strength | Parse call |
|---|---|---|
| zod 4 | ecosystem, JSON Schema export, `z.infer` | `Schema.parse(x)` / `.safeParse(x)` |
| valibot 1 | tree-shakable, small bundles (frontend) | `v.parse(Schema, x)` / `v.safeParse` |
| arktype 2 | TS-syntax strings, fast | `Schema(x)` returns data or `ArkErrors` |

All three implement Standard Schema (`schema["~standard"]`), so a library or helper can accept any:

```ts
import type { StandardSchemaV1 } from "@standard-schema/spec";
export async function validate<S extends StandardSchemaV1>(
  schema: S, input: unknown,
): Promise<StandardSchemaV1.InferOutput<S>> {
  let result = schema["~standard"].validate(input);
  if (result instanceof Promise) result = await result;
  if (result.issues) throw new Error(JSON.stringify(result.issues, null, 2));
  return result.value;
}
```

Environment: parse `process.env` once at startup and export the typed result; never read
`process.env.X` deep in the code.

```ts
const Env = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]),
  PORT: z.coerce.number().int().min(1).max(65535).default(3000),
  DATABASE_URL: z.url(),
});
export const env = Env.parse(process.env);   // crash at boot, not at the first request
```

## 7. Escape-hatch policy

| Hatch | Policy |
|---|---|
| `any` | banned (`no-explicit-any: error`); use `unknown` and narrow |
| `as T` | only for facts proven elsewhere; comment the proof; never on parsed input |
| `x!` | banned outside tests (`no-non-null-assertion`); narrow or throw with a message |
| `// @ts-expect-error` | allowed with a reason (`ban-ts-comment` with `allow-with-description`) |
| `// @ts-ignore` | banned |
| `Function`, `{}`, `Object` | banned; use a signature, `object`, or `Record<string, unknown>` |

typescript-eslint (type-aware rules need the TS 6 API; typescript-eslint 8.71 peers `typescript <6.1`):

```js
// eslint.config.js
import eslint from "@eslint/js";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

export default defineConfig(
  eslint.configs.recommended,
  tseslint.configs.strictTypeChecked,
  { languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } } },
  { rules: {
      "@typescript-eslint/switch-exhaustiveness-check": "error",
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/ban-ts-comment": ["error", { "ts-expect-error": "allow-with-description" }],
  } },
  { files: ["**/*.test.ts"], rules: { "@typescript-eslint/no-non-null-assertion": "off" } },
);
```

`strictTypeChecked` includes `no-unsafe-assignment`, `-member-access`, `-return`, `-call`, `-argument`,
`no-unnecessary-condition` and `no-explicit-any`. `tseslint.config()` is deprecated in favour of ESLint's
`defineConfig`. On TS 7 only: oxlint with `oxlint-tsgolint` (`oxlint --type-aware`, rules under
`typescript/*`) runs the same rule family on the Go checker; keep TS 6 via the alias in
`typescript-build-config` if you stay on typescript-eslint.

## 8. Advanced types, with restraint

| Utility | Use |
|---|---|
| `Pick<T, K>` / `Omit<T, K>` | DTO subsets (`Omit` is not distributive over unions; map the union instead) |
| `Partial` / `Required` / `Readonly` | patches, normalized configs, frozen inputs |
| `Record<K, V>` | exhaustive maps when `K` is a finite union (`Record<Role, Perm[]>`) |
| `Awaited<T>`, `ReturnType<F>`, `Parameters<F>` | derive from functions you do not own |

```ts
type Getters<T> = { [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K] };   // key remapping
type ElementOf<T> = T extends readonly (infer E)[] ? E : never;                         // infer
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
```

Stop rule: if a reviewer needs more than a minute to read the type, or it hits TS2589 (excessively deep
instantiation), replace it with a runtime check, an overload list, or two explicit types. Duplication
is cheaper than a type nobody can change.

## 9. Error -> fix

| Code | Message (short) | Fix |
|---|---|---|
| TS2322 / TS2345 | not assignable | find where the value widened (`let`, missing `as const`, `string` from `JSON`); use `satisfies`, a literal union, or validate |
| TS2532 / TS18048 | object / `x` possibly undefined | narrow (`if (!x) return`), default (`?? 0`), or validate; never `!` |
| TS7006 | parameter implicitly any | annotate the parameter; for callbacks, type the higher-order function instead |
| TS2339 | property missing on union | narrow by discriminant first |
| TS2589 | instantiation excessively deep | simplify the recursive or conditional type; add an explicit annotation at the call |
| TS1484 | type-only import required | `import type { Foo }` or `import { type Foo }` |
| TS2375 | `exactOptionalPropertyTypes` | omit the key, or declare `p?: string \| undefined` if `undefined` is meaningful |
| TS4111 | index-signature property | `obj["key"]`, or declare the key in the type |
| TS2835 | missing `.js` extension (nodenext) | `./lib.js` or `rewriteRelativeImportExtensions` |
| TS2591 | cannot find `process` | add `"types": ["node"]` (TS 6 defaults `types` to `[]`) |

More codes and their usual root causes: [error-codes](references/error-codes.md).

## 10. Type tests and the compiler

- Library or shared-utility types need tests. Vitest: `expectTypeOf(fn).parameter(0).toEqualTypeOf<UserId>()`
  in `*.test-d.ts` run by `vitest --typecheck` (see `typescript-testing-vitest`); standalone: `tsd`.
  `toMatchTypeOf` is deprecated (expect-type 1.2+); use `toExtend` or `toMatchObjectType`.
- Negative tests: a line that must not compile gets `// @ts-expect-error` above it; if it starts
  compiling, TS2578 fails the check.
- TS 7.0: typically 8-12x faster type checks (Microsoft: VS Code 125.7 s -> 10.6 s) with the same codes for
  nearly everything (isolatedDeclarations errors differ: TS9007 on 6.0, TS9013 on 7.0).
  6.0 deprecations are hard errors (TS5102/TS5108). No stable API until 7.1, so typescript-eslint
  type-aware rules, Vue/Svelte/Astro/Angular tooling and ts-morph still need 6.x installed alongside.
  Check every tool's `peerDependencies` (`npm view <pkg> peerDependencies`) before upgrading.

## 11. Pitfalls

- `any` from untyped dependencies leaks through generics: `JSON.parse`, `res.json()`, untyped
  `require`, `@types` gaps. `no-unsafe-*` rules flag the first use; wrap the source in a typed function.
- `{}` means "any non-nullish value" and `Object` is the same; neither means "object with no keys".
- Numeric enums: `enum E { A }` creates `E[0] === "A"`; values are plain numbers at runtime.
- Index signatures (`[k: string]: T`) hide typos; `Record<string, T>` lookups typed as present unless
  `noUncheckedIndexedAccess` is on.
- Overloads are matched top-down: put the most specific first; the implementation signature is invisible.
- `Omit<Union, K>` collapses the union; use the distributive form above.
- `as const` on a function argument does nothing for the parameter type; use a `const` type parameter.
- Type guards that lie (`return true`) are worse than `as`: the compiler trusts them everywhere.
- `object` spread loses brands and readonly-ness; re-validate or re-brand after transformations.

## 12. Worked example: payments module

Before: `interface Payment { id: string; status: string; amount?: number; failureReason?: string;
refundedAt?: string }`, webhook handler does `const p = req.body as Payment`, `tsc` clean,
`npx eslint . --rule '{"@typescript-eslint/no-explicit-any":"error"}' -f json | jq '[.[].messages[]] | length'`
reports **47** `any` uses (scenario figures below are illustrative). A bug shipped: refunded payments were shown as "unknown".

1. Model states as a union derived from the boundary schema (zod 4):

```ts
import * as z from "zod";
export const PaymentId = z.string().regex(/^pay_[A-Za-z0-9]{14}$/).brand<"PaymentId">();
export type PaymentId = z.infer<typeof PaymentId>;
const Cents = z.number().int().nonnegative().brand<"Cents">();
const base = { id: PaymentId, amount: Cents };

export const PaymentEvent = z.discriminatedUnion("status", [
  z.object({ ...base, status: z.literal("pending") }),
  z.object({ ...base, status: z.literal("succeeded"), capturedAt: z.coerce.date() }),
  z.object({ ...base, status: z.literal("failed"), reason: z.string().min(1) }),
  z.object({ ...base, status: z.literal("refunded"), refundedAt: z.coerce.date() }),
]);
export type Payment = z.infer<typeof PaymentEvent>;
export const parseWebhook = (body: unknown): Payment => PaymentEvent.parse(body);
```

2. Exhaustive rendering. The first version omitted `refunded`; the compiler now reports it:

```ts
export function ledgerLine(p: Payment): string {
  switch (p.status) {
    case "pending": return `${p.id} pending ${p.amount}`;
    case "succeeded": return `${p.id} captured ${p.capturedAt.toISOString()}`;
    case "failed": return `${p.id} failed: ${p.reason}`;
    default: return assertNever(p);
    // error TS2345: Argument of type '{ status: "refunded"; refundedAt: Date; ... }'
    //               is not assignable to parameter of type 'never'.
  }
}
```

Adding ``case "refunded": return `${p.id} refunded ${p.refundedAt.toISOString()}`;`` fixes it.
`charge("pay_123")` against `charge(id: PaymentId)` is now TS2345; only `PaymentId.parse(...)` output
is accepted.

3. Lint gate: `strictTypeChecked` plus `switch-exhaustiveness-check`; CI step
   `npx eslint . --max-warnings 0`. Burn-down by directory: 47 -> 18 (webhooks, repository) -> 6
   (reports) -> 0; two `as` casts remain, each with a comment naming the proof.
4. Verify: `npx tsc6 --noEmit` (6.0) and `npx tsc --noEmit` (7.0) both clean;
   `vitest --typecheck` with `expectTypeOf(parseWebhook).returns.toEqualTypeOf<Payment>()`; a webhook
   fixture with `status: "chargeback"` now fails at the boundary with a readable zod message instead of
   rendering "unknown".

Related: `typescript-build-config`, `typescript-testing-vitest`, `node-runtime-patterns`,
`react-typescript-components`, `code-review-checklist`, `code-quality-metrics`, hub `coding-general`.
