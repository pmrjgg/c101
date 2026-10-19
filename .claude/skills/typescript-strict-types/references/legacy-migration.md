# Turning on strictness in a legacy TypeScript codebase

## 1. Measure each flag before enabling anything

```bash
#!/usr/bin/env bash
# strict-census.sh: error count per flag, plus the five worst directories per flag.
set -euo pipefail
flags=(strictNullChecks noImplicitAny strictFunctionTypes strictPropertyInitialization \
       useUnknownInCatchVariables noUncheckedIndexedAccess exactOptionalPropertyTypes \
       noImplicitOverride noPropertyAccessFromIndexSignature noImplicitReturns)
base=$(npx tsc --noEmit -p . 2>&1 | grep -c 'error TS' || true)
echo "baseline errors: $base"
for f in "${flags[@]}"; do
  out=$(npx tsc --noEmit -p . --"$f" true 2>&1 || true)
  n=$(grep -c 'error TS' <<<"$out" || true)
  echo "$f: $((n - base)) new errors"
  grep -oE '^[^(]+' <<<"$out" | xargs -n1 dirname 2>/dev/null | sort | uniq -c | sort -rn | head -5
done
```

`strictPropertyInitialization` requires `strictNullChecks`; measure it with both on. With TS 6+, `strict`
is on unless the tsconfig sets `"strict": false`, so a legacy repo upgrading from 5.x may get the whole
backlog at once: set `"strict": false` explicitly first, then walk the flags.

## 2. Order

| Step | Flag | Why this position |
|---|---|---|
| 1 | `strictNullChecks` | finds the most real bugs; changes inferred types everywhere, so do it before annotating |
| 2 | `noImplicitAny` | annotations written after step 1 already carry `\| undefined` correctly |
| 3 | rest of `strict` (`strictFunctionTypes`, `strictBindCallApply`, `strictPropertyInitialization`, `useUnknownInCatchVariables`, `noImplicitThis`) | usually small counts |
| 4 | `noImplicitOverride`, `noFallthroughCasesInSwitch`, `noImplicitReturns` | mechanical |
| 5 | `noUncheckedIndexedAccess` | large counts in array-heavy code; many fixes are `for...of` instead of index loops |
| 6 | `exactOptionalPropertyTypes` | touches DTOs and spreads; do it last and only where APIs are stable |

## 3. Suppress the backlog, then ratchet

Mechanically insert `@ts-expect-error` above each error line after enabling a flag:

```bash
npx tsc --noEmit -p . 2>&1 | grep -oE '^[^(]+\([0-9]+' | sort -u |
while IFS='(' read -r file line; do
  echo "$file:$line"
done > .strict-backlog.txt
# Insert from the bottom of each file upward so line numbers stay valid:
sort -t: -k1,1 -k2,2nr .strict-backlog.txt | while IFS=: read -r f l; do
  sed -i.bak "${l}i\\
// @ts-expect-error STRICT-BACKLOG strictNullChecks
" "$f" && rm "$f.bak"
done
```

Indentation and JSX need care: inside JSX use `{/* @ts-expect-error STRICT-BACKLOG */}`. Run the
formatter afterwards and re-run `tsc`; lines where the error moved need a manual touch.

CI ratchet:

```bash
count=$(grep -rn 'STRICT-BACKLOG' src | wc -l | tr -d ' ')
max=$(cat .quality/strict-backlog-max)
if [ "$count" -gt "$max" ]; then echo "backlog grew: $count > $max"; exit 1; fi
if [ "$count" -lt "$max" ]; then echo "$count" > .quality/strict-backlog-max; fi   # commit the decrease
```

## 4. Fix patterns by flag

| Flag | Common pattern | Fix |
|---|---|---|
| `strictNullChecks` | `find()` result used directly | `const u = users.find(...); if (!u) throw new NotFound(id);` |
| `strictNullChecks` | optional chaining hides a real invariant | throw with a message at the point the invariant is established |
| `noImplicitAny` | untyped callback parameters | type the function that receives the callback (generic `T`) |
| `noImplicitAny` | `JSON.parse` result | validate with a schema at the boundary |
| `strictPropertyInitialization` | fields set in `init()` | move to the constructor or make the class a factory function |
| `useUnknownInCatchVariables` | `catch (e) { e.message }` | `const msg = e instanceof Error ? e.message : String(e)` |
| `noUncheckedIndexedAccess` | `for (let i = 0; i < a.length; i++) a[i].x` | `for (const item of a)` or `a.entries()` |
| `noUncheckedIndexedAccess` | `map[key]` known present | `Map` with `.get` + check, or a `Record<Union, T>` keyed by a finite union |
| `exactOptionalPropertyTypes` | `{ ...opts, timeout: opts.timeout }` copies `undefined` | conditional spread `...(opts.timeout !== undefined && { timeout: opts.timeout })` |

## 5. Counting `any`

```bash
# explicit and implicit any as reported by typescript-eslint (needs typed linting configured)
npx eslint . -f json | jq '[.[].messages[] | select(.ruleId | test("no-explicit-any|no-unsafe-"))] | length'
# type coverage percentage (third-party tool; check it supports your TS major before relying on it)
npx type-coverage --detail --strict
```

Record the number per directory in the PR description; the goal is monotonic decrease, not a big-bang.
