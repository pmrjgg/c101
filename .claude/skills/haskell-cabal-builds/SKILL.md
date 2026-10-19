---
name: haskell-cabal-builds
description: "Haskell build and toolchain management. Covers GHCup and HLS, cabal.project with index-state, freeze files and constraints, PVP bounds and Hackage revisions, reading solver errors, multi-package repos, stack snapshots, GHC upgrades, Nix options, and CI with haskell-ci. Load when a Haskell build will not resolve, a GHC upgrade is planned, or CI and tooling need setting up."
when_to_use: "cabal reports 'Could not resolve dependencies', rejecting, backjump or conflict set; planning or doing a GHC major upgrade; HLS says it does not support the installed GHC; writing cabal.project, freeze files, index-state or source-repository-package stanzas; choosing or fixing version bounds before a Hackage upload; setting up multi-package repos, stack snapshots or Nix shells; creating or caching GitHub Actions CI for a Haskell project."
---

# Haskell builds with cabal

A cabal build has three layers: the `.cabal` file of each package (what it needs, as PVP version
ranges), `cabal.project` (which packages are local and how the whole plan is resolved), and the
store (built dependencies keyed by their full configuration). Reproducibility comes from pinning
the package index (`index-state`) and, for applications, the full plan (`cabal freeze`).

Baseline: GHCup, cabal-install 3.12+, GHC 9.6-9.14. Version-specific flags are marked.

## 1. Toolchain

```bash
ghcup list -t ghc                 # installed, recommended and available versions
ghcup install ghc 9.12.2 --set    # pick the latest patch of the series you target
ghcup install cabal latest --set
ghcup install hls latest --set
haskell-language-server-wrapper --probe-tools   # which GHC and HLS the editor will use
ghcup tui                         # interactive overview
```

- Each HLS binary supports a fixed set of GHC versions (`ghcup list -t hls` shows them). If the
  project's GHC is not covered, either switch GHC or build HLS for it with `ghcup compile hls`
  (see its `--help`).
- `hie.yaml` only when the implicit cradle guesses wrong (shared source dirs between
  components, custom Setup, mixed tools):

```yaml
cradle:
  cabal:
    - path: "src"
      component: "lib:mypkg"
    - path: "test"
      component: "test:spec"
```

- Format `.cabal` files with one tool and check it in CI: cabal-gild (`cabal-gild --io mypkg.cabal`,
  `--mode check` in CI) or cabal-fmt (`cabal-fmt -i mypkg.cabal`, `--check`).

| GHC | base | Notes for upgrades |
|---|---|---|
| 9.6 | 4.18 | mtl 2.3 era (fewer re-exports from `Control.Monad.*`) |
| 9.8 | 4.19 | `head`/`tail` warn under the `x-partial` category |
| 9.10 | 4.20 | `GHC2024` available; `foldl'` exported from Prelude |
| 9.12 | 4.21 | `MultilineStrings` extension |
| 9.14 | 4.22 | `-Wincomplete-record-selectors` joins `-Wall` |

Boot package versions for an installed compiler: `ghc-pkg list --global` with that GHC on PATH.

## 2. cabal.project essentials

```cabal
packages: mypkg-core/ mypkg-server/

with-compiler: ghc-9.12.2
index-state: hackage.haskell.org 2026-10-01T00:00:00Z

constraints: aeson ^>=2.2,
             any.text >=2.1

-- scoped: lift one bound on one edge, never a bare allow-newer
allow-newer: fancy-http:base

tests: True

source-repository-package
  type: git
  location: https://github.com/someorg/somepkg
  -- a full commit hash, never a branch name (cabal files have no end-of-line comments)
  tag: 0123456789abcdef0123456789abcdef01234567
  subdir: somepkg

package mypkg-server
  optimization: 2
  flags: +prometheus
  ghc-options: -fspecialise-aggressively -fexpose-all-unfoldings
```

- `cabal.project.local` (gitignored) holds personal settings: `optimization: False`,
  `profiling: True`, `documentation: False`. Never commit it.
- `package *` applies to every package including dependencies, so the whole store rebuilds:
  use it rarely (e.g. `-fwrite-ide-info` for tooling).
- Flags on the command line (`--ghc-options`, `-O2`) apply to local packages only.
- Every `allow-newer` and `source-repository-package` gets a comment with the upstream issue and
  date; delete it when a fixed release lands.

## 3. Bounds policy

PVP versions are A.B.C(.D): A.B is the major version (breaking), C the minor (additions), D a
patch. Libraries on Hackage give every dependency a lower and an upper bound.

| Form | Meaning | Use |
|---|---|---|
| `^>=2.2.1` | `>=2.2.1 && <2.3` | default for each dependency |
| `>=2.1 && <2.4` | explicit tested span | when several majors are known to work |
| `==2.2.*` | `>=2.2 && <2.3` | same as caret without a lower patch |
| no bound | anything | applications only, backed by a freeze file |

```bash
cabal gen-bounds          # suggests bounds for dependencies that lack them, from the current plan
cabal outdated            # dependencies whose upper bounds exclude the newest release
cabal outdated --exit-code    # CI: non-zero when something is outdated
cabal check               # package-description problems before `cabal upload`
```

- Lower bound: the oldest version actually built in CI (a `--prefer-oldest` job or an old
  `index-state` catches false lower bounds).
- Hackage metadata revisions change the bounds of an already-released version without a new
  upload (maintainer web UI). Tighten bounds when a new dependency release breaks an old
  version; relax upper bounds after testing. Revisions never change code.
- Applications: bounds optional; reproducibility comes from section 4.

## 4. Reproducibility

```bash
cabal freeze                        # cabal.project.freeze: every transitive version and flag
cabal build all --dry-run           # writes dist-newstyle/cache/plan.json without building
cabal-plan list-bins                # executables in the plan
cabal-plan topo                     # dependency order; cabal-plan dot for a graph
```

| Project kind | Pin |
|---|---|
| application or service | `index-state` + committed `cabal.project.freeze` |
| library | `index-state` in CI; plus a job without the pin to see what users get |
| CI cache key | hash of `dist-newstyle/cache/plan.json` after `--dry-run` |

Stack alternative: a snapshot fixes one version per package for one GHC.

```yaml
# stack.yaml (older stack versions call the first key resolver:)
snapshot: lts-24.11            # check stackage.org for the GHC each LTS uses
packages: [mypkg-core, mypkg-server]
extra-deps:
  - somepkg-1.2.3@rev:1        # pinned Hackage revision
  - git: https://github.com/someorg/otherpkg
    commit: 0123456789abcdef0123456789abcdef01234567
```

## 5. Reading solver failures

Abridged failure:

```text
Could not resolve dependencies:
[__0] trying: myapp-0.3.0 (user goal)
[__1] trying: base-4.21.0.0/installed-4.21.0.0 (dependency of myapp)
[__2] next goal: fancy-http (dependency of myapp)
[__2] rejecting: fancy-http-0.4.1 (conflict: base==4.21.0.0/installed-4.21.0.0, fancy-http => base>=4.14 && <4.21)
[__2] skipping: fancy-http-0.4.0, fancy-http-0.3.2 (has the same characteristics that caused the previous version to fail: excludes 'base' version 4.21.0.0)
[__2] fail (backjumping, conflict set: base, fancy-http, myapp)
After searching the rest of the dependency tree exhaustively, these were the goals I've had most trouble fulfilling: fancy-http, base, myapp
```

Reading order: the `rejecting:` line names the bound and who imposes it
(`fancy-http => base <4.21`); `base` is installed with GHC and cannot change, so the bound must;
the conflict set lists every package involved; the "most trouble" list says where to look first.

```bash
cabal build all --dry-run --constraint='fancy-http>=0.5'     # does a newer release lift the bound?
cabal build all --dry-run --allow-newer=fancy-http:base      # does the rest resolve without it?
cabal build all --dry-run --minimize-conflict-set            # smaller, clearer conflict set
cabal build all --dry-run -v3 2>&1 | grep -E 'rejecting|conflict'   # full solver trace
```

| Cause | Fix |
|---|---|
| a dependency's upper bound on a boot package (base, template-haskell) | newer release or Hackage revision; else scoped `allow-newer` plus an upstream issue |
| your own bound too tight | widen it and test |
| two dependencies need incompatible versions of a third | `--constraint` experiments to find a consistent pair; drop or replace one |
| "unknown package" or missing version | `cabal update`, or move `index-state` forward |
| automatic flag choice fails | `--constraint='pkg +flag'` or `-flag` |

## 6. GHC upgrades

1. On the old GHC: add `-Wcompat` to the common warnings stanza and fix what it reports.
2. Read the release notes and migration guide of every major you cross; list boot package
   versions with `ghc-pkg list --global`.
3. On a branch: `with-compiler: ghc-X.Y.Z` in cabal.project, `cabal update`, then
   `cabal build all --dry-run`; fix solver failures with section 5, one at a time.
4. Bump bounds: `base`, `template-haskell`, `ghc-prim`, `containers`, `bytestring`, `text`,
   `filepath` follow the compiler.
5. GHC pre-releases: dependencies that do not build yet come from the head.hackage overlay
   repository (copy the repository stanza from the head.hackage README); never ship with it.
6. Fix new warnings: `x-partial` (`head`/`tail`, 9.8+) by pattern matching or `NonEmpty`;
   redundant `import Data.List (foldl')` (9.10+) via qualified imports while older GHCs stay
   supported; `-Wincomplete-record-selectors` in `-Wall` (9.14) by pattern matching or total
   accessors (`-Wno-error=incomplete-record-selectors` only as a temporary bridge).
7. `default-language: GHC2024` once the minimum GHC is 9.10 (needs a Cabal that knows it,
   3.12+); it adds `DataKinds`, `DerivingStrategies`, `DisambiguateRecordFields`,
   `ExplicitNamespaces`, `GADTs`, `LambdaCase`, `MonoLocalBinds`, `RoleAnnotations`.
   `MonoLocalBinds` can break local polymorphic bindings: add signatures.
8. Full test suite, then benchmarks: optimisation behaviour shifts between majors.

## 7. Multi-package repos

```cabal
cabal-version: 3.4
name:          mypkg-core

common warnings
  ghc-options: -Wall -Wcompat -Widentities -Wincomplete-uni-patterns
               -Wincomplete-record-updates -Wredundant-constraints -Wunused-packages

common deps
  build-depends: base >=4.18 && <4.22, text ^>=2.1, containers >=0.6 && <0.8

library
  import:          warnings, deps
  hs-source-dirs:  src
  exposed-modules: MyPkg.Core

library testlib
  import:          warnings, deps
  -- public would expose it to other packages as mypkg-core:testlib
  visibility:      private
  hs-source-dirs:  testlib
  exposed-modules: MyPkg.Gen
  build-depends:   mypkg-core, hedgehog

test-suite spec
  import:         warnings, deps
  type:           exitcode-stdio-1.0
  hs-source-dirs: test
  main-is:        Main.hs
  build-depends:  mypkg-core, mypkg-core:testlib
```

- `common` stanzas need `cabal-version: 2.2+`; public sub-libraries need 3.0+.
- One repl over several packages: `cabal repl --enable-multi-repl mypkg-core mypkg-server`
  (cabal 3.12+, GHC 9.4+); reloads see edits across packages.
- `-Wunused-packages` keeps `build-depends` honest; enable it in the shared stanza.

## 8. Nix

| Option | Choose when | Cost |
|---|---|---|
| no Nix: GHCup + cabal | default | lowest |
| Nix for system libraries only (zlib, libpq) + cabal in `nix develop` | native deps are the pain | low |
| nixpkgs `haskellPackages` (`developPackage`, `callCabal2nix`, `shellFor`) | the nixpkgs package set has what you need | versions follow the nixpkgs snapshot; overrides such as `doJailbreak`, `dontCheck` |
| haskell.nix | plans driven by cabal.project or stack.yaml, cross-compilation, large monorepos | slow evaluation without its binary cache, steep learning curve |

Avoid Nix when the team does not already use it, when macOS developers lack a binary cache, or
when GHC versions change faster than the package set.

## 9. CI

Generated: list the compilers in the `.cabal` file and let haskell-ci write the workflow.

```bash
# mypkg.cabal: tested-with: GHC ==9.8.4 || ==9.10.2 || ==9.12.2   (latest patch of each series)
haskell-ci github cabal.project    # writes .github/workflows/haskell-ci.yml
haskell-ci regenerate              # after editing tested-with
```

Hand-written with haskell-actions/setup:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        ghc: ['9.8', '9.10', '9.12']
    steps:
      - uses: actions/checkout@v4
      - uses: haskell-actions/setup@v2
        id: setup
        with: {ghc-version: '${{ matrix.ghc }}', cabal-version: latest}
      - run: cabal update && cabal build all --enable-tests --dry-run
      - uses: actions/cache/restore@v4
        id: cache
        with:
          path: ${{ steps.setup.outputs.cabal-store }}
          key: ${{ runner.os }}-ghc-${{ steps.setup.outputs.ghc-version }}-${{ hashFiles('dist-newstyle/cache/plan.json') }}
          restore-keys: ${{ runner.os }}-ghc-${{ steps.setup.outputs.ghc-version }}-
      - run: cabal build all --enable-tests --only-dependencies
      - uses: actions/cache/save@v4
        if: steps.cache.outputs.cache-hit != 'true'
        with:
          path: ${{ steps.setup.outputs.cabal-store }}
          key: ${{ steps.cache.outputs.cache-primary-key }}
      - run: cabal build all --enable-tests --ghc-options=-Werror
      - run: cabal test all --test-show-details=direct
      - run: cabal check
```

- `-Werror` only in CI, never in the `.cabal` file: downstream users on a newer GHC would fail on
  new warnings.
- Optionally cache `dist-newstyle` keyed on the source hash for faster incremental builds.

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| build broke with no code change | no `index-state`, a new upload changed the plan | pin `index-state`; freeze apps |
| random breakage after a dependency release | bare `allow-newer` | scope it to `pkg:dep` |
| non-reproducible source dependency | `source-repository-package` on a branch | full commit hash |
| downstream fails on a new GHC | `-Werror` in `ghc-options` of the `.cabal` file | `--ghc-options=-Werror` in CI only |
| `cabal check` complains about `-O2` | optimisation in the package file | `optimization: 2` per package in cabal.project |
| HLS "does not support GHC" | HLS binary built for other GHCs | matching HLS or a compiled one |
| stale CI caches, missing packages | key based on the `.cabal` file only | key on `plan.json` |
| whole store rebuilds | options under `package *` | scope options to named packages |
| teammate's settings leak into builds | committed `cabal.project.local` | gitignore it |
| matrix tests old compilers only | `tested-with` not updated | update, `haskell-ci regenerate` |
| upgrade stalls for days | GHC and dependency upgrades mixed together | upgrade GHC first, dependencies after |

## 11. Worked example: GHC 9.6 to 9.12 with bounds fixes and a refreshed CI matrix

1. Baseline: CI green on 9.6. Add `-Wcompat` to `common warnings`, fix the warnings, merge.
2. `ghcup install ghc 9.12.2`; on a branch set `with-compiler: ghc-9.12.2`; `cabal update`.
3. `cabal build all --dry-run` fails with
   `rejecting: base-4.21.0.0/installed-4.21.0.0 (conflict: myapp => base>=4.17 && <4.19)`:
   the bound is ours. Change the shared `deps` stanza to `base >=4.18 && <4.22` (and
   `template-haskell`, `containers` likewise after checking `ghc-pkg list --global`).
4. The next failure is a dependency, `fancy-http => base<4.21` (section 5 output). Hackage shows
   no newer release and no revision. Add `allow-newer: fancy-http:base` with a comment linking
   the upstream issue; confirm it builds and its tests pass on 9.12 before relying on it.
5. Compile errors and warnings:
   - `import Data.List (foldl')` is now redundant (Prelude exports it): switch to
     `import qualified Data.List as L` and `L.foldl'` while 9.8 remains supported;
   - `x-partial` warnings on `head`: pattern match or use `NonEmpty`;
   - Template Haskell changes in a TH-heavy module: bump the `template-haskell` bound and use
     th-abstraction's compatibility layer where constructors changed.
6. `cabal test all --test-show-details=direct`; then benchmarks with `+RTS -s` to catch
   allocation regressions (see `haskell-performance-space-leaks`).
7. Policy "three latest majors": `tested-with: GHC ==9.8.4 || ==9.10.2 || ==9.12.2`,
   `haskell-ci regenerate` (or the matrix `['9.8', '9.10', '9.12']`), drop `with-compiler` from
   cabal.project so CI controls the compiler, and `ghcup install hls` for 9.12 locally.
8. Release: a minor version bump (widened bounds are not a breaking change); run `cabal check`,
   then upload. Remove the `allow-newer` line as soon as `fancy-http` publishes a fixed version
   or a revision.

Acceptance: `cabal build all --enable-tests --dry-run` resolves on 9.8, 9.10 and 9.12 without
local edits; CI green on all three with `-Werror`; no unexplained `allow-newer`.

Related: `haskell-testing-properties`, `haskell-performance-space-leaks`, `haskell-effects`, `haskell-type-level`, hub `haskell-craft`
