# Recovery and rewrite recipes

Step-by-step versions of the recovery matrix and history-rewriting rows in `SKILL.md`. Every recipe
starts by making the current state recoverable.

## 0. Safety first (always)

```bash
git status --short                       # what is dirty right now
git stash push -u -m "pre-recovery $(date +%s)"   # include untracked files
git branch rescue/pre-recovery HEAD
```

Never run `git gc --prune=now`, `git reflog expire --expire=now` or `git clean -fdx` while
recovering: they delete exactly the objects you are looking for.

## 1. Find a lost commit

```bash
git reflog --date=iso | head -40          # HEAD movements in this clone
git reflog show feat/x                    # movements of one branch (if it still exists)
git log -g --format='%h %gd %gs %s' | grep -i 'rebase\|reset\|checkout' | head
git fsck --unreachable --no-reflogs | awk '/commit/ {print $3}' \
  | xargs -n1 git log -1 --format='%h %ci %s' | sort -k2 | tail -20
```

Then `git branch rescue/found <sha>` and inspect with `git log -p rescue/found`.

## 2. Undo a rebase

```bash
git reflog | grep -m1 'rebase (start)'    # e.g. a1b2c3d HEAD@{12}: rebase (start): checkout origin/main
git reset --hard HEAD@{13}                # the entry just BEFORE the start line
# right after a finished rebase, ORIG_HEAD also points at the old tip:
git reset --hard ORIG_HEAD
```

With `--update-refs`, each moved branch has its own reflog: `git reflog show part1`.

## 3. Recover a dropped stash

```bash
git fsck --unreachable | awk '/commit/ {print $3}' | while read c; do
  git log -1 --format="%h %ci %s" "$c"; done | grep -i 'WIP on\|On '
git stash apply <oid>
```

Stash commits have messages `WIP on <branch>: ...` or `On <branch>: <message>`.

## 4. Recover staged-but-never-committed content

```bash
git fsck --lost-found                     # writes dangling blobs to .git/lost-found/other/
ls -t .git/lost-found/other | head
git show <oid> > recovered.txt            # blobs have no file name; identify by content
rg -l 'def compute_totals' .git/lost-found/other/
```

## 5. Revert a merge, then merge the branch again later

```bash
git revert -m 1 <merge-sha>               # mainline = parent 1 (the branch merged INTO)
# ... branch gets fixed ...
git revert <sha-of-the-revert>            # re-introduce the original changes first
git merge feature                         # then merge only the new fixes
```

Skipping the revert-of-revert silently drops the original changes: git considers them merged.

## 6. Split one commit into several

During `git rebase -i` mark the commit `edit` (in a written todo), then when the rebase stops:

```bash
git reset HEAD^                           # undo the commit, keep all changes unstaged
git add -p src/parser.py                  # first logical change
git commit -m "refactor: extract tokenizer"
git add -A src/ tests/
git commit -m "feat: support quoted fields"
git rebase --continue
```

To peel only a few hunks off the last commit: `git reset -p HEAD^`, `git commit --amend --no-edit`,
then commit the remaining working-tree changes separately.

## 7. Move commits to another branch

```bash
# 3 commits made on main by mistake, not pushed
git branch feat/oops                      # keep them
git reset --hard origin/main              # main back to remote
git switch feat/oops
```

Commits that belong on another existing branch: `git switch other && git cherry-pick <a>^..<b>`,
then remove them from the wrong branch with a rebase or reset.

## 8. Remove a file or secret from all history

Rotate the credential before anything else. Then:

```bash
git clone --mirror <url> repo-clean && cd repo-clean
git filter-repo --analyze                         # .git/filter-repo/analysis/*.txt: big blobs, paths
git filter-repo --sensitive-data-removal --invert-paths --path config/secrets.env
cat > ../replacements.txt <<'EOF'
literal:sk_test_EXAMPLE_ONLY==>***REMOVED***
regex:password\s*=\s*"[^"]+"==>password = "***REMOVED***"
EOF
git filter-repo --sensitive-data-removal --replace-text ../replacements.txt
```

`--replace-text` lines are `literal:` (default), `glob:` or `regex:` expressions, optionally
`==>replacement` (default replacement `***REMOVED***`). After the rewrite: force-push every ref,
have all collaborators re-clone (a stale clone pushing back reintroduces the data), close or
rebase open PRs, and ask the hosting provider to purge cached refs and views.

Alternative for a single recent commit not yet pushed: `git rm --cached <file>`,
`git commit --amend`, add the path to `.gitignore`.

## 9. Fix author or message on old commits

```bash
git rebase -r --exec 'git commit --amend --no-edit --reset-author' origin/main   # all commits, keeps merges
git commit --fixup=reword:<sha> && git rebase --autosquash origin/main            # one message
```

`--reset-author` uses the current `user.name`/`user.email`; check `git config user.email` first.

## 10. Rebase todo commands (for written todo files)

| Command | Effect |
|---|---|
| `pick <sha>` | use commit |
| `reword <sha>` | use commit, edit message (opens editor; prefer `--fixup=reword:` for agents) |
| `edit <sha>` | use commit, stop to amend or split |
| `squash <sha>` | meld into previous, combine messages |
| `fixup <sha>` | meld into previous, discard this message (`fixup -C` keeps this message instead) |
| `exec <cmd>` | run a shell command; non-zero exit stops the rebase |
| `drop <sha>` | remove commit |
| `break` | stop here; `git rebase --continue` resumes |
| `label` / `reset` / `merge` | used by `--rebase-merges` to rebuild merge topology |
| `update-ref refs/heads/<b>` | inserted by `--update-refs`; moves the branch to this point |

`rebase.missingCommitsCheck=error` makes git refuse a hand-written todo that silently drops a commit.
