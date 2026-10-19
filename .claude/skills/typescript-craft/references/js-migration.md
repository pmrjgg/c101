# JavaScript to strict TypeScript migration

A staged procedure for moving a JavaScript codebase (or a loose TypeScript one) to strict
TypeScript without a big-bang rewrite. Flag-by-flag detail and error codes: `typescript-strict-types`;
tsconfig and module settings: `typescript-build-config`; mechanical rewrites at scale: `codemod-automation`.

## 1. Stages

| Stage | Change | Gate that must stay green |
|---|---|---|
| 0. Baseline | record test results, lint state, bundle output; pin the package manager | existing tests |
| 1. Tooling | add `typescript`, `tsconfig.json` with `allowJs: true`, `checkJs: false`, `noEmit: true`; `@types/node` and `"types": ["node"]` for Node code | `tsc --noEmit` (0 errors: nothing is checked yet) |
| 2. JSDoc check (optional) | `// @ts-check` on selected `.js` files, JSDoc types for exports | `tsc --noEmit` on checked files |
| 3. Rename leaves | `.js` -> `.ts` starting from leaf modules (no internal imports), then upwards | `tsc --noEmit`, tests |
| 4. Strict null | `strictNullChecks: true` with an `@ts-expect-error` backlog | backlog count ratchets down |
| 5. Full strict | `strict: true`, then `noUncheckedIndexedAccess`, `noImplicitOverride`, `exactOptionalPropertyTypes` last | backlog count ratchets down |
| 6. Close | remove `allowJs`, enforce `no-explicit-any` and type-aware lint in CI | full gate |

TS 6 defaults `strict` to `true`: when adding TypeScript at stage 1, set `"strict": false`
explicitly and turn flags on in stages 4-5.

## 2. Ordering the files

```bash
# leaves first: files that import nothing local
npx madge --extensions js,ts --json src | jq -r 'to_entries | map(select(.value | length == 0)) | .[].key'
# biggest blast radius last: most-imported modules
npx madge --extensions js,ts --json src | jq -r '[.[]] | flatten | group_by(.) | map({f: .[0], n: length}) | sort_by(-.n) | .[:15][] | "\(.n) \(.f)"'
```

Rename with `git mv` so history follows (`git log --follow`). Keep each commit to one directory
or one flag so a reviewer can read it and a revert is cheap.

## 3. Backlog suppression and the ratchet

```bash
# suppress every current error with a tagged @ts-expect-error (one-off script or ts-migrate style tool),
# then count and gate
grep -rn '@ts-expect-error TS-MIGRATION' src | wc -l > .ts-backlog-count
test "$(grep -rn '@ts-expect-error TS-MIGRATION' src | wc -l)" -le "$(cat .ts-backlog-count)"
```

- `@ts-expect-error`, never `@ts-ignore`: it fails with TS2578 once the error is fixed, so dead
  suppressions cannot accumulate.
- Gate CI on the count not increasing; lower the stored count in the same PR that fixes errors.
- Count errors per flag before choosing the order:
  `npx tsc --noEmit -p . --strictNullChecks 2>&1 | grep -c 'error TS'`.

## 4. Typing the edges first

| Edge | Approach |
|---|---|
| HTTP request bodies, query strings, webhooks | schema (zod 4 / valibot) -> inferred type; parse at the handler |
| environment variables | one validated `config.ts`; nothing else reads `process.env` |
| `JSON.parse`, `localStorage`, `postMessage` | `unknown` + schema |
| database rows | the query library's generated or inferred types (Prisma, Drizzle, Kysely, sqlc) |
| untyped dependency | `@types/x` if it exists; otherwise a minimal `declare module "x"` with only the functions you call, never `declare module "x";` (makes everything `any`) |
| shared domain objects | discriminated unions and branded IDs in one `types.ts` per domain |

## 5. Common conversions

| JavaScript pattern | TypeScript |
|---|---|
| object used as a map with dynamic keys | `Map<K, V>` or `Record<K, V>` with `noUncheckedIndexedAccess` |
| `options = options \|\| {}` | default parameter `options: Options = {}` |
| string constants object | `const Status = { Active: "active", ... } as const; type Status = (typeof Status)[keyof typeof Status];` |
| `module.exports = {...}` / `require` | ESM `export` / `import` (check `"type"` and resolution mode first) |
| function that returns different shapes | discriminated union return type |
| prototype-based classes | `class` with explicit fields; `override` on overridden methods |
| `arguments` | rest parameters `...args: T[]` |
| duck-typed checks (`if (x.then)`) | type predicates backed by the same check |

## 6. Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| thousands of errors after renaming one folder | renamed a hub module first | revert; rename leaves first |
| type errors "fixed" with `as any` everywhere | pressure to go green | backlog `@ts-expect-error` instead; `no-explicit-any` in lint |
| runtime breaks although `tsc` is clean | types describe the wrong runtime shape (no validation at the edge) | schema at the boundary; tests on the edge |
| imports break after `.js` -> `.ts` under Node | resolution mode (`nodenext` needs `.js` in specifiers) | `./x.js` specifiers or `rewriteRelativeImportExtensions` |
| build time doubles | `allowJs` + `checkJs` over the whole repo | scope `include`; project references per package |
| tests stop running | test runner config still matches only `*.test.js` | update `include` globs in the runner config |
