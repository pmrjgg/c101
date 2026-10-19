# Conflict cookbook by file type

Rule for every row: understand both intents from the zdiff3 base section first, resolve, then run
the fastest test that exercises the file before `git add`.

## Which side is which

| Operation | `--ours` / `<<<<<<<` side | `--theirs` / `>>>>>>>` side |
|---|---|---|
| `git merge feature` (on main) | main (current branch) | feature |
| `git rebase main` (on feature) | main plus already-replayed commits | the feature commit being replayed |
| `git cherry-pick <sha>` | current branch | the picked commit |
| `git revert <sha>` | current branch | the inverse of `<sha>` |
| `git stash pop` | current tree | the stash |

## Lockfiles and dependency manifests

| Ecosystem | Manifest (resolve by hand) | Lock (take upstream, regenerate) | Check |
|---|---|---|---|
| Python uv | `pyproject.toml` | `uv.lock`: `uv lock` | `uv lock --check`, `uv sync --locked` |
| Python Poetry | `pyproject.toml` | `poetry.lock`: `poetry lock` | `poetry check --lock` |
| Python pip-tools | `requirements.in` | `requirements.txt`: `pip-compile` | rerun, diff empty |
| npm | `package.json` | `package-lock.json`: `npm install` | `npm ci` |
| pnpm | `package.json`, `pnpm-workspace.yaml` | `pnpm-lock.yaml`: `pnpm install` | `pnpm install --frozen-lockfile` |
| Yarn (berry) | `package.json` | `yarn.lock`: `yarn install` | `yarn install --immutable` |
| Go | `go.mod` | `go.sum`: `go mod tidy` | `go mod verify`, `go build ./...` |
| Rust | `Cargo.toml` | `Cargo.lock`: `cargo build` (or `cargo update -p <crate>`) | `cargo build --locked` |
| Java Gradle | `build.gradle(.kts)`, version catalog | `gradle.lockfile`: `./gradlew dependencies --write-locks` | build |
| Ruby | `Gemfile` | `Gemfile.lock`: `bundle install` | `BUNDLE_FROZEN=true bundle install` |

If both sides added the same dependency at different versions, pick the higher compatible one in
the manifest and say so in the commit message.

## Generated and derived files

| File | Resolution |
|---|---|
| protobuf / gRPC stubs | resolve `.proto`, rerun `buf generate` |
| OpenAPI clients / server stubs | resolve the spec, rerun the generator, `git diff --exit-code` on output |
| sqlc / ORM-generated models | resolve SQL / schema, rerun generator |
| snapshot files (`__snapshots__`, `.snap`) | take either, rerun tests with update flag, review the snapshot diff |
| minified / bundled assets | take either, rebuild |
| `CHANGELOG.md` | keep both entries, order by the file's convention |

## Database migrations

- Two branches both added migration `0042_*`: renumber yours (Django: `makemigrations --merge`
  creates a merge migration; Alembic: two heads, run `alembic merge heads` or re-point
  `down_revision`; Rails: timestamps rarely collide, check `schema.rb` order).
- Resolve `schema.rb` / `structure.sql` / model snapshots by regenerating from the merged migrations,
  not by hand.
- Run the migration chain from an empty database once after resolving.

## Code

| Shape | Approach |
|---|---|
| both sides edited the same function body | rewrite it with both intents; add a test that pins each intent |
| one side renamed/moved, other side edited | apply the edit at the new location; `git log --merge -p -- <old> <new>`; `diff.renames` is on by default |
| one side deleted a file the other edited (`CONFLICT (modify/delete)`) | decide whether the edit still matters; port it to the replacement or `git rm` |
| import blocks | take the union, then run the formatter / import sorter (`ruff check --select I --fix`, `goimports`, `eslint --fix`) |
| formatting-only conflicts after a mass reformat | take one side, rerun the formatter on the file |
| both added different functions at the same spot | keep both, order by the file's convention |

## Config and data files

- YAML/JSON/TOML: resolve by key, then validate (`python -c 'import tomllib,sys;tomllib.load(open(sys.argv[1],"rb"))' pyproject.toml`, `jq . file.json`, `yq . file.yaml`).
- Translation catalogs (`.po`, `.xliff`): take one side, re-extract and merge with the toolchain.
- Binary files (images, fonts): `git checkout --ours/--theirs -- <path>`; never textual merge.

## When to stop and ask

- The base shows both sides changed a business rule (limits, prices, permissions) differently.
- The conflict is in a security-sensitive path (auth, crypto, access control).
- Resolving requires deleting someone else's tests.

Record the open question in the PR rather than guessing; a wrong silent resolution is worse than
a blocked rebase.
