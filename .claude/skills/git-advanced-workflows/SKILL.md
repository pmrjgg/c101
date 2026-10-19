---
name: git-advanced-workflows
description: "Git beyond add/commit: fixup/autosquash rebase, stacked branches with update-refs, conflict prediction and resolution (zdiff3, rerere, merge-tree), worktrees for parallel tasks, cherry-pick backports, reflog recovery, pickaxe/line-log archaeology, safe force-push and history rewriting. Load when rebasing, untangling history, resolving conflicts, running parallel worktrees or recovering lost work."
when_to_use: "A branch has wip/fixup commits to squash before review; 'CONFLICT (content)' or 'could not apply <sha>' during rebase/merge/cherry-pick; conflicts in uv.lock, package-lock.json, pnpm-lock.yaml, go.sum or Cargo.lock; a commit or branch was lost (reset --hard, botched rebase, detached HEAD); several agents need separate checkouts; backporting fixes to a release branch; a secret was committed; 'who changed this line and why'."
---

# Git advanced workflows

Baseline: git >= 2.38 (`merge-tree --write-tree`, `--update-refs`); flags were checked against git
2.54 help and the rebase, merge-tree and range-diff flows in a scratch repository. Check `git --version` first; older versions are noted per row.
Agents cannot drive interactive editors: every `-i` rebase here is made non-interactive with
`GIT_SEQUENCE_EDITOR` (section 2). Bisection lives in `debugging-method`; do not repeat it here.

Deep material:
[recovery and rewrite recipes](references/recovery-and-rewrite-recipes.md) |
[conflict cookbook by file type](references/conflict-cookbook.md)

## 1. Per-repo config baseline

Set these with `git config --local` in the repo you are working in. Never change `--global` or
`--system` config without the user asking: it silently alters every other repo they own.

| Key | Value | Effect | Since |
|---|---|---|---|
| `merge.conflictStyle` | `zdiff3` | conflict hunks also show the merge-base version of the lines | 2.35 |
| `rerere.enabled` | `true` | records conflict resolutions and replays them on the next identical conflict | old |
| `rerere.autoUpdate` | `false` (keep) | replayed resolutions stay unstaged so you re-check them | old |
| `rebase.autoSquash` | `true` | `fixup!`/`squash!`/`amend!` commits are moved and folded in interactive rebases | old |
| `rebase.updateRefs` | `true` | rebasing the top of a stack moves every branch pointing into it | 2.38 |
| `rebase.autoStash` | `true` | stashes and re-applies a dirty tree around a rebase | old |
| `push.autoSetupRemote` | `true` | first `git push` creates the upstream with the same name | 2.37 |
| `push.useForceIfIncludes` | `true` | `--force-with-lease` also requires the remote tip to be in your reflog | 2.30 |
| `fetch.prune` | `true` | deleted remote branches disappear locally on fetch | old |
| `diff.algorithm` | `histogram` | fewer misaligned hunks on moved code | old |
| `blame.ignoreRevsFile` | `.git-blame-ignore-revs` | blame skips listed formatting commits | 2.23 |

```bash
git config --local merge.conflictStyle zdiff3
git config --local rerere.enabled true
git config --local rebase.autoSquash true
git config --local rebase.updateRefs true
git config --local rebase.autoStash true
git config --local push.autoSetupRemote true
git config --local fetch.prune true
git config --local diff.algorithm histogram
test -f .git-blame-ignore-revs && git config --local blame.ignoreRevsFile .git-blame-ignore-revs
```

`blame.ignoreRevsFile` pointing at a missing file makes `git blame` fail, hence the `test -f`.
`.git-blame-ignore-revs` holds one full 40-char SHA per line with a `#` comment naming the change;
GitHub and GitLab blame views read the same file.

## 2. Clean-history procedure

Goal: every commit in the PR is one reviewable idea, builds, and passes the fast tests.

| You want to | Command | Result at autosquash |
|---|---|---|
| add changes to an earlier commit, keep its message | `git commit --fixup=<sha>` | `fixup <sha>`: content folded, message dropped |
| add changes and replace the message | `git commit --fixup=amend:<sha>` (opens editor; not combinable with `-m`) | content folded, message replaced |
| only replace the message | `git commit --fixup=reword:<sha>` | message replaced, no content |
| fold and edit the combined message | `git commit --squash=<sha>` | messages concatenated for editing |

Steps:

```bash
git branch rescue/$(git branch --show-current)-$(date +%Y%m%d-%H%M)   # cheap undo point
git fetch origin
git rebase --autosquash origin/main            # non-interactive autosquash: git >= 2.44
# older git: GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash origin/main
git rebase -x 'uv run pytest -q -x' --reschedule-failed-exec origin/main   # test every commit
git range-diff @{u}...HEAD > /tmp/range-diff.txt   # old vs new series, attach to the PR
git push --force-with-lease --force-if-includes
```

- Commits that are not `fixup!` commits (`wip`, `more`, `address review`) need a written todo.
  Generate it, edit it, and feed it to git; the editor command receives the todo path as its
  argument, so `cp` replaces it:

```bash
git log --reverse --format='pick %h %s' origin/main..HEAD > .git/todo.plan
# edit .git/todo.plan: reorder lines, change "pick" to fixup / squash / reword / drop
GIT_SEQUENCE_EDITOR="cp $PWD/.git/todo.plan" git rebase -i origin/main
```

- A supplied todo replaces the autosquash ordering, so place `fixup!` lines yourself in that run.
- `-x` on an already rebased branch still replays every commit and runs the command after each
  one without changing hashes: a cheap "is every commit green" check.
- `range-diff` reading: `=` unchanged patch, `!` changed patch (diff of diffs follows), `<` only in
  old, `>` only in new. When `origin/main` moved, its new commits also appear as `>` rows; to hide
  them use the three-range form `git range-diff <old-base>..@{u} origin/main..HEAD`, with
  `<old-base>` from `git merge-base @{u} origin/main`.

## 3. Stacked branches

One branch per reviewable step, each based on the previous: `main <- part1 <- part2 <- part3`.

```bash
git switch part3
git rebase --update-refs origin/main     # moves part1, part2 and part3 in one pass
git push --force-with-lease --force-if-includes origin part1 part2 part3
```

The output ends with `Updated the following refs with --update-refs:` and the moved branches.
After part1 merges (squash-merged on the server, so its commits are not in main):

```bash
git fetch origin
git rebase --onto origin/main part1 part3 --update-refs   # replay only commits after part1
git branch -D part1
```

`git rebase --onto <new-base> <old-base> <branch>` replays `old-base..branch` onto `new-base`; use it
to transplant a branch started from the wrong base too.

When force-push is allowed:

| Branch | Who commits | Force-push | How |
|---|---|---|---|
| own feature branch, not yet reviewed | only you | yes | `--force-with-lease --force-if-includes` |
| own branch under review | you; reviewers read it | yes, announce it, attach range-diff | same; never plain `--force` |
| shared branch (pairing, integration, release prep) | several people or agents | never | `git revert`, or merge main into it |
| protected (`main`, `release/*`) | merge queue / PR only | never; server should reject it | `git revert` via PR |

`--force-with-lease` alone is defeated by a background `git fetch` that updates the remote-tracking
ref; `--force-if-includes` additionally requires that you have seen (reflog) the tip you overwrite.

## 4. Conflict playbook

1. Predict before merging or rebasing (no worktree changes, exit code 1 on conflict):

```bash
git merge-tree --write-tree --name-only --no-messages origin/main HEAD
# line 1: tree OID; following lines: conflicted paths; exit status 1 means conflicts
```

2. Read a zdiff3 hunk: ours, then the base, then theirs. Decide from the base what each side meant:

```text
<<<<<<< HEAD
timeout = 30
||||||| parent of 7ae3e69 (feat: raise timeout)
timeout = 10
=======
timeout = 20
>>>>>>> 7ae3e69 (feat: raise timeout)
```

   Base 10, upstream changed it to 30, the commit being replayed to 20: a semantic decision, not a
   textual one; ask or take the newer intent and say so in the commit message.

3. See the commits on both sides that touched the file: `git log --merge -p -- <path>` (works
   during merge, cherry-pick, revert and rebase).
4. Whole-file picks: `git checkout --ours -- <path>` or `--theirs`. During a rebase the sides are
   swapped: `--ours` is the branch you are rebasing onto, `--theirs` is your commit being replayed.
5. Generated files and lockfiles: take one side, regenerate, never hand-merge.

| File | Take | Regenerate with |
|---|---|---|
| `uv.lock` | upstream side | `uv lock` |
| `poetry.lock` | upstream side | `poetry lock` |
| `package-lock.json` | upstream side | `npm install` |
| `pnpm-lock.yaml` | upstream side | `pnpm install` |
| `yarn.lock` | upstream side | `yarn install` |
| `go.sum` | upstream side | `go mod tidy` |
| `Cargo.lock` | upstream side | `cargo build` or `cargo update -p <crate>` for the one you added |
| generated code (protobuf, OpenAPI clients, sqlc) | either | rerun the generator from the merged spec |

   Resolve the manifest (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`) by hand first;
   the lockfile follows from it. More file types: [conflict cookbook](references/conflict-cookbook.md).

6. Run the fast tests before `git add` + `git rebase --continue`. A resolution that compiles but
   breaks a test is a new bug inside an old commit.
7. With `rerere.enabled`, the second identical conflict resolves itself (`Resolved 'x' using previous
   resolution.`); `git rerere forget <path>` drops a wrong recorded resolution.

## 5. Worktrees for parallel agent tasks

```bash
git fetch origin
git worktree add -b task-x ../repo-task-x origin/main    # new branch, new directory
cd ../repo-task-x && uv sync                              # per-worktree venv / node_modules / target
git worktree list
git worktree remove ../repo-task-x                        # refuses if dirty; --force discards
git worktree prune                                        # forget worktrees deleted with rm -rf
```

- One branch per worktree: git refuses to check out a branch already checked out elsewhere
  (`-f` overrides; do not).
- Untracked files are not copied: `.env`, local config, build caches, `node_modules`. Copy only
  non-secret config explicitly; never copy credential files between worktrees.
- Shared across worktrees: objects, refs, stashes, config, hooks. A `git stash` made in one is
  visible (and poppable) in all; `git branch -D` from one deletes the branch for all.
- Build output must stay per worktree (`target/`, `dist/`, `.venv/`), or parallel builds corrupt
  each other.
- Remove worktrees when the task ends; stale ones keep their branch locked.

## 6. Archaeology

| Question | Command |
|---|---|
| when did this string appear or disappear | `git log -S'parse_tenant' -p --all` (pickaxe: commits that change its occurrence count) |
| commits whose diff matches a regex (also moves inside a file) | `git log -G'timeout\s*=' -p` |
| history of one function | `git log -L :compute_totals:billing/invoice.py` (add `*.py diff=python` to `.gitattributes` for good function detection) |
| history of a line range | `git log -L 120,160:billing/invoice.py` |
| who last changed these lines, ignoring moves and whitespace | `git blame -w -C -C -C -L 120,160 billing/invoice.py` |
| blame without formatting commits | `git blame --ignore-revs-file .git-blame-ignore-revs <path>` |
| merged-PR view of main | `git log --first-parent --oneline main` |
| newest commit whose message matches | `git show :/'rate limit'` |
| which tags/branches contain a fix | `git tag --contains <sha>`, `git branch -r --contains <sha>` |
| which commit introduced a regression | `git bisect run` (procedure in `debugging-method`) |

`-C -C -C` makes blame follow lines copied from any file in any commit; it is slow on big repos,
so scope with `-L`.

## 7. Recovery matrix

Before any risky operation: `git branch rescue/<name> HEAD` (and `git stash -u` if dirty).

| Situation | Recovery |
|---|---|
| uncommitted edits lost, they were staged once | `git fsck --lost-found`; dangling blobs land in `.git/lost-found/other/`, inspect with `git show <oid>` |
| uncommitted edits lost, never staged | git never saw them: editor local history, IDE backups, `.orig` files |
| stash dropped | `git fsck --unreachable \| grep commit`, then `git stash apply <oid>` |
| bad last commit, not pushed | `git commit --amend` or `git reset --soft HEAD~1` (keeps changes staged) |
| bad commit already pushed / shared | `git revert <sha>` |
| bad merge pushed | `git revert -m 1 <merge-sha>` (keeps parent 1, the mainline); re-merging the branch later needs a revert of the revert |
| deleted branch | `git reflog` (or `git log -g`), find the tip, `git branch rescue <sha>` |
| botched rebase | `git reflog` shows `rebase (start)`; `git reset --hard <sha-before-start>` or `ORIG_HEAD` right after |
| commits made on a detached HEAD, then switched away | `git reflog`, `git branch rescue <sha>`; git also prints the SHA when leaving |
| `reset --hard` to the wrong commit | `git reset --hard HEAD@{1}` |

Reflog entries expire (default 90 days reachable, 30 days unreachable) and are local to one clone:
a fresh clone has no reflog. Step-by-step versions:
[recovery and rewrite recipes](references/recovery-and-rewrite-recipes.md).

## 8. Backports

```bash
git switch -c backport/1.4-fix-tenant-leak origin/release/1.4
git cherry -v origin/release/1.4 origin/main | grep '^+'   # commits in main not yet in release
git cherry-pick -x a1b2c3d                 # appends "(cherry picked from commit a1b2c3d...)"
git cherry-pick -x a1b2c3d^..f6e5d4c       # inclusive range A..B
```

- `git cherry` compares patch IDs: `-` means an equivalent change is already present (even under a
  different SHA), `+` means missing.
- Resolve with the section 4 playbook; release branches often lack refactors the fix depends on:
  backport the smallest prerequisite or rewrite the fix, never the whole refactor.
- PR title `[1.4] <original title>`, body names the original SHA and PR; run the release branch's
  own test command, which may differ from main's.

## 9. History rewriting and big repos

Leaked secret: rotate it first. Rewriting removes it from future clones, not from forks, caches,
CI logs or anyone who already fetched.

```bash
# fresh mirror clone; filter-repo refuses to run in a non-fresh clone without --force
git clone --mirror git@host:org/repo.git repo-rewrite && cd repo-rewrite
git filter-repo --sensitive-data-removal --invert-paths --path secrets.env
printf 'literal:AKIAEXAMPLEKEY==>REDACTED\n' > ../expr.txt
git filter-repo --sensitive-data-removal --replace-text ../expr.txt
```

`git filter-repo` is a separate tool (`uvx git-filter-repo` or a package manager). Coordinate:
freeze merges, force-push all refs, everyone re-clones (old clones re-push the secret),
ask the host to purge cached views and PR refs.

Split a commit (inside `git rebase -i` with `edit`, or on the last commit):

```bash
git reset -p HEAD^        # select hunks to take OUT of the commit (they stay in the worktree)
git commit --amend --no-edit
git add -p && git commit -m "second half"
```

Big repos:

| Need | Command |
|---|---|
| clone without historical blobs (fetched on demand) | `git clone --filter=blob:none <url>` |
| clone without trees too (CI that only builds HEAD) | `git clone --filter=tree:0 <url>` |
| only some directories in the worktree | `git sparse-checkout set services/billing libs/common` (cone mode, the default) |
| background gc, commit-graph, prefetch | `git maintenance start` |
| size report before rewriting | `git filter-repo --analyze` (writes `.git/filter-repo/analysis/`) |

## 10. Pitfalls

- Rebasing published history that others built on: their next pull duplicates every commit.
- Plain `--force`: overwrites commits pushed by others since your last fetch.
- `git add -A` / `git commit -a` staging build output, `.env` or large binaries; stage paths
  explicitly and check `git status --short` before committing.
- `git stash` without `-u` leaves untracked files behind, and `git clean -fd` later deletes them.
- Commits on a detached HEAD (after `git checkout <sha>` or during a stopped rebase) look fine until
  you switch away; branch them first.
- Hand-merging lockfiles: produces a lock that matches no resolver run; CI installs differ from local.
- Formatting and logic in one commit: unreviewable diff, useless blame; format in its own commit and
  add its SHA to `.git-blame-ignore-revs`.
- A `fixup!` that depends on an intermediate commit conflicts when autosquash moves it upward:
  target the right commit or reorder by hand.
- Resolving `--ours`/`--theirs` with merge semantics during a rebase (they are swapped).
- `git rebase -x` with a slow suite: use the fastest meaningful command (`pytest -q -x` on the
  touched package), run the full suite once on the tip.

## 11. Worked example: 14 messy commits to 4 reviewable ones

Branch `feat/rate-limit`, 14 commits: 4 real ones, 7 `fixup!` commits made with
`git commit --fixup` during review, `wip`, `more tests`, `fmt`. Main has since bumped dependencies.

```bash
git switch feat/rate-limit
git branch rescue/rate-limit-20261019
git fetch origin
git log --oneline origin/main..HEAD | wc -l                     # 14
git merge-tree --write-tree --name-only --no-messages origin/main HEAD; echo "exit=$?"
# 3f1c...                  <- tree
# pyproject.toml
# uv.lock
# exit=1                   <- conflicts predicted in exactly these two files
```

Plan the todo (written with the file tool, then fed to git):

```text
pick 1a2b3c4 build: add redis client dependency
fixup 9e8d7c6 fixup! build: add redis client dependency
pick 2b3c4d5 refactor: extract TokenBucket from middleware
fixup 5d6e7f8 fmt
fixup 8f9a0b1 fixup! refactor: extract TokenBucket from middleware
pick 3c4d5e6 feat: per-tenant limits in RateLimitMiddleware
fixup 0a1b2c3 wip
fixup 4e5f6a7 fixup! feat: per-tenant limits in RateLimitMiddleware
fixup 6b7c8d9 fixup! feat: per-tenant limits in RateLimitMiddleware
fixup 7c8d9e0 more tests
pick 4d5e6f7 feat: X-RateLimit-* response headers
fixup b1c2d3e fixup! feat: X-RateLimit-* response headers
fixup c2d3e4f fixup! feat: X-RateLimit-* response headers
fixup d3e4f5a fixup! feat: X-RateLimit-* response headers
```

```bash
GIT_SEQUENCE_EDITOR="cp $PWD/.git/todo.plan" git rebase -i origin/main
# CONFLICT (content): Merge conflict in pyproject.toml
# CONFLICT (content): Merge conflict in uv.lock
# error: could not apply 1a2b3c4... build: add redis client dependency
```

`pyproject.toml` zdiff3 hunk: upstream bumped `httpx>=0.28`, our commit added `redis>=5.2`;
keep both lines by hand. `uv.lock`: never edit; take upstream's and regenerate:

```bash
git checkout --ours -- uv.lock      # during rebase "ours" = origin/main's version
uv lock                             # re-resolves with redis added
git add pyproject.toml uv.lock
uv run pytest -q -x                 # green before continuing
git rebase --continue
```

The remaining picks apply cleanly. Verify every commit, compare, publish:

```bash
git log --oneline origin/main..HEAD | wc -l                     # 4
git rebase -x 'uv run pytest -q -x' origin/main                 # 4 exec runs, all pass
git range-diff $(git merge-base @{u} origin/main)..@{u} origin/main..HEAD > /tmp/rd.txt
git push --force-with-lease --force-if-includes
```

`/tmp/rd.txt` shows the 14 old commits collapsing into 4 (`<` rows for the fixups, `!` rows for the
4 survivors with their folded diffs). Paste it into the PR under "History rewritten", note that
`uv.lock` was regenerated with `uv lock`, delete `rescue/rate-limit-20261019` after merge.

Related: `debugging-method` (bisect), `refactoring-playbook` (commit discipline),
`codemod-automation` (mechanical commits per shard), `security-review` (secret leaks), `code-review-checklist`,
`api-contract-design`, `sql-query-tuning`, hub `coding-general`.
