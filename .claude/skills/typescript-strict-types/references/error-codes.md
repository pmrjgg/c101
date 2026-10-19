# TypeScript diagnostic catalogue (strict-mode work)

Codes verified against `tsc` 6.0.3 and 7.0.2 unless marked. Messages abbreviated.

## Assignability and inference

| Code | Message | Usual root cause | Fix |
|---|---|---|---|
| TS2322 | Type 'A' is not assignable to type 'B' | value widened (`let s = "a"` is `string`), indexed access returning `T \| undefined`, wrong union member | `as const` / `satisfies`, narrow, validate input |
| TS2345 | Argument of type 'A' is not assignable to parameter of type 'B' | same as TS2322 at a call site; `NoInfer` blocked an inference site; branded type expected | pass a value produced by the validating constructor |
| TS2375 | ... with 'exactOptionalPropertyTypes: true' | `{ p: undefined }` where `p?: T` | omit the key (`...(x && { p: x })`) or declare `p?: T \| undefined` |
| TS2379 | argument variant of TS2375 | same | same |
| TS1360 | Type 'X' does not satisfy the expected type 'Y' | `satisfies` failed, including `satisfies never` exhaustiveness | handle the reported variant |
| TS2589 | Type instantiation is excessively deep and possibly infinite | recursive conditional types, deep zod/ORM inference chains | annotate an intermediate result; simplify the type; split the schema |
| TS2590 | Expression produces a union type that is too complex to represent | template literal or union cross products | narrow the domain; use `string` plus runtime validation |

## Null and undefined

| Code | Message | Fix |
|---|---|---|
| TS2532 | Object is possibly 'undefined' | narrow (`if (!x) return`), `??`, `?.`, or validate |
| TS2531 | Object is possibly 'null' | same |
| TS18047 / TS18048 / TS18049 | 'x' is possibly 'null' / 'undefined' / 'null' or 'undefined' | same; named-variable form of TS2531/TS2532 |
| TS2564 | Property has no initializer and is not definitely assigned in the constructor | assign in the constructor, make it optional, or `!:` only for framework-injected fields with a comment |

## Implicit any and unsafe values

| Code | Message | Fix |
|---|---|---|
| TS7006 | Parameter 'x' implicitly has an 'any' type | annotate; for callbacks type the higher-order function |
| TS7005 / TS7034 | Variable implicitly has type 'any' | initialize or annotate |
| TS7016 | Could not find a declaration file for module 'x' | install `@types/x`; else a minimal `declare module "x" { export function f(a: string): number }` in `types/x.d.ts`, never `declare module "x";` (that is `any`) |
| TS7053 | Element implicitly has an 'any' type because expression of type 'string' can't be used to index | key the object by a union (`Record<Role, T>`), or check `key in obj` with a predicate |
| TS18046 | 'e' is of type 'unknown' | narrow (`e instanceof Error`) before use |

## Unions, properties and index signatures

| Code | Message | Fix |
|---|---|---|
| TS2339 | Property 'p' does not exist on type 'U' | narrow by discriminant or `in` first |
| TS4111 | Property 'p' comes from an index signature, so it must be accessed with ['p'] | bracket access, or declare the property (`noPropertyAccessFromIndexSignature`) |
| TS2353 | Object literal may only specify known properties | typo or stale DTO; excess property check only applies to fresh literals |
| TS2741 | Property 'p' is missing in type 'A' but required in type 'B' | supply it, or model the state as a separate union member |

## Control flow

| Code | Message | Flag |
|---|---|---|
| TS7029 | Fallthrough case in switch | `noFallthroughCasesInSwitch` |
| TS7030 | Not all code paths return a value | `noImplicitReturns` (no declared return type) |
| TS2366 | Function lacks ending return statement and return type does not include 'undefined' | declared return type, missing branch |
| TS4114 | This member must have an 'override' modifier | `noImplicitOverride` |
| TS2578 | Unused '@ts-expect-error' directive | the suppressed error was fixed: delete the comment |

## Modules and emit

| Code | Message | Fix |
|---|---|---|
| TS1484 | 'Foo' is a type and must be imported using a type-only import when 'verbatimModuleSyntax' is enabled | `import type { Foo }` |
| TS1205 | Re-exporting a type when 'isolatedModules'/'verbatimModuleSyntax' is enabled requires using 'export type' | `export type { Foo }` |
| TS2748 | Cannot access ambient const enums when 'isolatedModules'/'verbatimModuleSyntax' is enabled | replace with an `as const` object |
| TS1294 | This syntax is not allowed when 'erasableSyntaxOnly' is enabled | enums -> `as const`; parameter properties -> explicit fields; namespaces -> modules |
| TS2835 | Relative import paths need explicit file extensions ... Did you mean './lib.js'? | add `.js`, or write `.ts` with `rewriteRelativeImportExtensions` |
| TS2307 | Cannot find module 'x' or its corresponding type declarations | see the error table in `typescript-build-config` |
| TS2591 | Cannot find name 'process'. Do you need to install type definitions for node? | `"types": ["node"]` (TS 6 default `types` is `[]`) plus `@types/node` |
| TS9007 (6.0) / TS9013 (7.0) | explicit return type / expression type required with --isolatedDeclarations | annotate exported functions and constants |

## Config-level (TS 6 deprecation vs TS 7 removal)

| TS 6.0 | TS 7.0 | Example |
|---|---|---|
| TS5101 "Option 'baseUrl' is deprecated and will stop functioning in TypeScript 7.0" | TS5102 "Option 'baseUrl' has been removed" | move prefixes into `paths` |
| TS5107 "Option 'moduleResolution=node10' is deprecated" | TS5108 "... has been removed" | `nodenext` or `bundler` |
| TS5112 tsconfig.json is present but will not be loaded if files are specified on commandline | same | `tsc --ignoreConfig file.ts` or `tsc -p .` |

`"ignoreDeprecations": "6.0"` silences TS5101/TS5107 on 6.x only; it buys time, not compatibility.
