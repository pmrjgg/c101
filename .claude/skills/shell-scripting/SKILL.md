---
name: shell-scripting
description: "Robust Bash and POSIX shell scripts: when to switch to a uv-run Python script, strict-mode header and its set -e caveats, quoting and arrays, safe file iteration, traps and temp dirs, getopts parsing, idempotent and atomic operations, macOS bash 3.2 and BSD vs GNU portability, shellcheck/shfmt/bats, safe curl/jq usage. Load when writing, reviewing or debugging a shell script, Makefile/justfile recipe or CI run step."
when_to_use: "Editing *.sh, *.bash, *.bats, a Makefile or justfile recipe, a Dockerfile RUN line or a CI run: block; shellcheck SC2086/SC2155/SC2164 findings; 'unbound variable', '$'\\r': command not found', 'bad substitution', 'declare: -A: invalid option' or exit 141; a script works on Linux but not macOS; deciding whether a script should become Python."
---

# Shell scripting

Line-level review items for shell stay in `code-review-checklist` (Shell pitfalls) and command
injection in `security-review`; this skill is how to write scripts that pass them.
Behaviors marked "bash 3.2" were checked on macOS `/bin/bash` 3.2.57.

Deep material:
[complete script template, the worked-example script and its bats tests](references/script-template.md) |
[GNU vs BSD vs BusyBox portability table](references/portability.md)

## 1. Shell or Python?

| Signal | Shell | Python (PEP 723 + `uv run --script`) |
|---|---|---|
| Length | < ~100 lines | > ~100 lines or growing |
| Work | glue: run commands, move files, check exit codes | logic: parsing, data structures, retries with state |
| Data | lines and simple fields | JSON beyond a `jq` one-liner, CSV with quoting, YAML, dates |
| Errors | fail fast and exit | partial failure handling, cleanup per item, typed errors |
| Platforms | Linux + macOS | also Windows |
| Tests | a few bats cases | real unit tests |

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27"]
# ///
import httpx
```
`uv add --script tool.py httpx` edits the block; `uv lock --script tool.py` writes `tool.py.lock` for
reproducible runs. `env -S` works on macOS and GNU coreutils >= 8.30; elsewhere call
`uv run --script tool.py`.

## 2. Header template

```bash
#!/usr/bin/env bash
# name.sh: one-line purpose. Usage: name.sh [-n] ARG
set -Eeuo pipefail
shopt -s inherit_errexit 2>/dev/null || true      # bash >= 4.4; silently absent on bash 3.2
trap 'printf "%s: error at line %s: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2' ERR

readonly PROG=${0##*/}
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT                       # runs on success, errors, INT and TERM; not on KILL

usage() { printf 'Usage: %s [-n] ARG\n' "$PROG"; }
die() { printf '%s: %s\n' "$PROG" "$*" >&2; exit 1; }

main() {
  # parse args, validate, do work
  :
}

main "$@"
```
| Flag | Meaning |
|---|---|
| `-e` | exit on an unchecked non-zero status (with the caveats in section 3) |
| `-E` | ERR trap is inherited by functions, command substitutions and subshells |
| `-u` | unset variable is an error (use `${VAR:-}` for optional env vars) |
| `-o pipefail` | a pipeline fails if any stage fails, not only the last |
| `inherit_errexit` | `$(...)` subshells keep `-e` |

One EXIT trap per script: a second `trap ... EXIT` replaces the first, so put all cleanup in one
`cleanup()` function. `main "$@"` at the bottom means a truncated download never runs half a script.

## 3. set -e caveats (reproduced on bash 3.2 unless noted)

| Situation | Behavior | Do instead |
|---|---|---|
| `if f; then`, `while f`, `f && x`, `f \|\| x`, `! f` | `-e` is ignored for `f`, and for every command inside `f` if it is a function | check status explicitly inside the function (`cmd \|\| return 1`) |
| `x=$(false; echo hi)` | without `inherit_errexit`, the subshell continues; `x=hi`, no exit | `shopt -s inherit_errexit` (bash >= 4.4) or one command per substitution |
| `x=$(false)` | assignment takes the substitution status: script exits | fine |
| `echo "$(false)"` | status is `echo`'s: no exit | assign first, then use |
| `local x=$(cmd)` / `export x=$(cmd)` / `readonly x=$(cmd)` | status of `local` (0) masks `cmd` (SC2155) | `local x; x=$(cmd)` |
| `cmd \| head -1` with `pipefail` | writer gets SIGPIPE, pipeline exits 141 | `cmd \| head -1 \|\| true` when early close is expected, or `sed -n 1p` |
| `[ "$v" = y ] && do_x` as last line of a function | function returns 1 when false, caller exits | `if [ "$v" = y ]; then do_x; fi` |
| `((i++))` when `i` is 0 | expression value 0 = status 1: exits on bash >= 4.1 (3.2 continues) | `i=$((i + 1))` |
| `grep` with no match | status 1 is a failure | `grep ... \|\| true`, or test `$?` = 1 vs >1 |

Where failure must stop the script regardless of context, write it out: `cp "$a" "$b" || die "copy failed"`.

## 4. Quoting and arrays

- Always quote expansions: `"$var"`, `"$@"`, `"${arr[@]}"`, `"$(cmd)"`. Unquoted expansions split on
  `IFS` and glob (`*` in a filename becomes a file list).
- Build commands as arrays, never strings or `eval`:
  ```bash
  cmd=(rsync -a --delete)
  if [ -n "$latest" ]; then cmd+=(--link-dest="$latest"); fi
  cmd+=(-- "$src/" "$dst/")
  "${cmd[@]}"
  ```
- Empty array with `set -u` on bash < 4.4: `"${arr[@]}"` aborts with "unbound variable"; write
  `${arr[@]+"${arr[@]}"}` in scripts that must run on macOS `/bin/bash`.
- `printf '%s\n' "$x"` over `echo "$x"` (echo mangles `-n`, `-e`, backslashes). `printf '%q '` prints a
  copy-pasteable command.
- `read -r` always (without `-r` backslashes are eaten); `IFS= read -r line` keeps leading spaces.
- Required inputs: `: "${API_URL:?API_URL must be set}"`; defaults: `"${LOG_LEVEL:-info}"`.
- `--` before user-supplied paths so `-rf` as a filename is not an option: `rm -- "$f"`, `grep -- "$pat" "$f"`.

## 5. Files safely

```bash
# iterate any filename (spaces, newlines, leading dashes)
find . -type f -name '*.log' -print0 |
  while IFS= read -r -d '' f; do gzip -- "$f"; done
find . -type f -name '*.log' -mtime +7 -exec rm -- {} +     # batch exec, no loop needed

# globs instead of ls
shopt -s nullglob                                            # no match -> empty list, not the literal
for f in "$dir"/*.csv; do process "$f"; done

rm -rf -- "${build_dir:?}/"                                  # aborts if build_dir is empty or unset

# atomic write: temp file in the SAME directory, then rename (rename is atomic within one filesystem)
out=config.json
tmpf=$(mktemp "$out.XXXXXX")
render >"$tmpf" && mv -f -- "$tmpf" "$out"
```
- Never parse `ls` (SC2045/SC2012); never `for f in $(cat list)` (splits on spaces): use
  `while IFS= read -r f; do ...; done <list`.
- The pipe `find | while read` runs the loop in a subshell: variables set inside are lost. Use
  `while ...; done < <(find ... -print0)` when the loop must set variables (bash, not POSIX sh).
- Locking against concurrent runs:
  ```bash
  exec 9>"/var/lock/$PROG.lock"; flock -n 9 || die "already running"   # Linux (util-linux)
  mkdir "$lockdir" 2>/dev/null || die "already running"                # portable; rmdir in cleanup
  ```
  macOS has no `flock(1)` (it has `lockf` and `shlock`); a `mkdir` lock survives `kill -9`, so print
  its path in the error message for manual removal.

## 6. Argument parsing

```bash
DRY_RUN=0 VERBOSE=0 OUT=""
while getopts ':hnvo:' opt; do
  case $opt in
    h) usage; exit 0 ;;
    n) DRY_RUN=1 ;;
    v) VERBOSE=1 ;;
    o) OUT=$OPTARG ;;
    :) printf '%s: -%s needs a value\n' "$PROG" "$OPTARG" >&2; usage >&2; exit 2 ;;
    *) printf '%s: unknown option -%s\n' "$PROG" "$OPTARG" >&2; usage >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
[ $# -ge 1 ] || { usage >&2; exit 2; }
```
- Leading `:` in the optstring = silent mode: missing value -> `:` with the option in `OPTARG`;
  unknown option -> `?`.
- Long options (`--dry-run`): a `while [ $# -gt 0 ]; do case $1 in --dry-run) ...; shift;; --out)
  OUT=${2:?}; shift 2;; --) shift; break;; -*) usage_error;; *) break;; esac; done` loop. GNU
  `getopt(1)` is not on macOS by default.
- Dry run wraps every side effect: `run() { if [ "$DRY_RUN" -eq 1 ]; then printf 'dry-run:'; printf ' %q' "$@"; printf '\n'; else "$@"; fi; }`.
- Exit codes: 0 success, 1 runtime failure, 2 usage error. Document any others in `usage`.

## 7. Portability

| Feature | bash 3.2 (macOS `/bin/bash`) | bash >= 4 | POSIX sh / dash |
|---|---|---|---|
| Associative arrays `declare -A` | no ("invalid option") | yes | no |
| `mapfile` / `readarray` | no (command not found) | yes | no |
| `${var,,}` / `${var^^}` | no ("bad substitution") | yes | no (`tr '[:upper:]' '[:lower:]'`) |
| `inherit_errexit` | no | 4.4+ | n/a |
| Empty `"${a[@]}"` under `set -u` | error | fine from 4.4 | no arrays |
| `[[ ]]`, arrays, `local -a`, `+=`, `$'..'`, `<( )` | yes | yes | no (SC3010, SC3030) |

Choose explicitly: either stay bash-3.2-safe (and test with `/bin/bash` on a Mac), or require a newer
bash and fail clearly:
```bash
if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then die "needs bash >= 4 (macOS: brew install bash)"; fi
```

| Task | GNU (Linux) | BSD (macOS) | Portable choice |
|---|---|---|---|
| in-place edit | `sed -i 's/a/b/' f` | `sed -i '' 's/a/b/' f` | `sed 's/a/b/' f >"$t" && mv "$t" f` or `perl -pi -e` |
| date math | `date -d '+1 day' +%F` | `date -v+1d +%F` | compute in epoch seconds or use Python |
| file size / mtime | `stat -c '%s %Y' f` | `stat -f '%z %m' f` | `wc -c <f` |
| PCRE grep | `grep -P` | recent macOS grep is ugrep with `-P`; older BSD grep lacks it | `grep -E` or `perl -ne` |
| empty input to xargs | runs once unless `-r` | never runs; `-r` accepted | `xargs -r` |
| canonical path | `readlink -f` | `readlink -f` since macOS 12.3 | `cd -- "$(dirname -- "$p")" && pwd -P` |
| `timeout`, `tac`, `numfmt` | coreutils | absent (Homebrew `gtimeout`) | avoid or check with `command -v` |

POSIX `sh` scripts: `#!/bin/sh`, lint with `shellcheck -s sh`, test under `dash`. More rows:
[portability table](references/portability.md).

## 8. Tooling

| Tool | Command | Notes |
|---|---|---|
| shellcheck | `shellcheck -x script.sh` (`-x` follows `source`d files); `-s sh` for POSIX; `-o all` for optional checks | key codes: SC2086 unquoted var, SC2046 unquoted `$(...)`, SC2155 local masks status, SC2164 `cd` without `\|\| exit`, SC2115 `rm -rf "$x/"*` without `:?`, SC2045/SC2012 parsing ls, SC1017 CRLF |
| shfmt | `shfmt -i 2 -ci -w .` (2-space indent, indented `case`); CI: `shfmt -i 2 -ci -d .` | flags override `.editorconfig` entirely when any is given |
| syntax | `bash -n script.sh` | parse only |
| bats-core | `bats test/` with bats-support + bats-assert (`run`, `assert_success`, `assert_failure 2`, `assert_output --partial`) | `run` captures stdout+stderr into `$output`, status in `$status` |
| tracing | `PS4='+ ${BASH_SOURCE}:${LINENO}: ' bash -x script.sh` | behind `DEBUG=1` or `-v`; never trace scripts that handle secrets |

Disable a shellcheck finding only on its line with a reason:
`# shellcheck disable=SC2046  # word splitting of the digest list is intended`.

## 9. Network and JSON

```bash
curl -fsSL --retry 3 --retry-all-errors --connect-timeout 5 --max-time 60 -o "$tmp/data.json" "$url"
code=$(curl -sS -o "$tmp/body" -w '%{http_code}' "$url")   # when the status itself matters
case $code in 2??) ;; 404) die "not found: $url" ;; *) die "HTTP $code from $url" ;; esac

jq -e '.ready == true' "$tmp/data.json" >/dev/null || die "service not ready"   # -e: false/null -> exit 1
jq -r '.items[] | [.id, .name] | @tsv' "$tmp/data.json" |
  while IFS=$'\t' read -r id name; do printf '%s=%s\n' "$id" "$name"; done
payload=$(jq -cn --arg msg "$message" --argjson n "$count" '{text: $msg, count: $n}')
```
- `-f` makes HTTP >= 400 a failure (exit 22); `--fail-with-body` keeps the error body. `--retry-all-errors`
  (curl >= 7.71) also retries on non-transient errors; combine with `--retry-max-time`.
- Never build JSON by string concatenation; `jq --arg` escapes quotes and newlines.
- Never `curl ... | sh` an unpinned installer. Download a pinned version, verify, then run:
  ```bash
  curl -fsSLo "$tmp/tool.tgz" "https://example.com/tool/v1.2.3/tool-linux-amd64.tgz"
  echo "$EXPECTED_SHA256  $tmp/tool.tgz" | sha256sum -c -      # macOS: shasum -a 256 -c -
  ```

## 10. Idempotency and logging

| Operation | Idempotent form |
|---|---|
| create dir | `mkdir -p -- "$d"` |
| symlink (replace existing) | `ln -sfn -- "$target" "$link"` |
| install file with mode | `install -m 0644 -- src "$dest"` (`-D` creates parents, GNU only) |
| append a line once | `grep -qxF -- "$line" "$f" \|\| printf '%s\n' "$line" >>"$f"` |
| create user/resource | check first (`id -u app >/dev/null 2>&1 \|\| useradd app`) |
| download | skip if checksum already matches |

- Every step safe to re-run after a failure halfway; prefer "converge to state" over "do action".
- Logs to stderr with UTC timestamps, data to stdout: `log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }`.
- `set -x` only behind `DEBUG=1` or `-v`.
- Script-relative paths, never the caller's cwd: `cd -- "$(dirname -- "${BASH_SOURCE[0]}")"` or
  `here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)`.

## 11. Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| `cd dir` unguarded (or inside a condition where `-e` is off) | commands run in the wrong directory; `rm` deletes the wrong tree | `cd -- "$dir" \|\| die "cd $dir"` |
| unquoted `$@` / `$*` | arguments with spaces split | `"$@"` |
| `[ $x = y ]` with empty `x` | `[: =: unary operator expected` | `[ "$x" = y ]` or `[[ $x == y ]]` |
| `for f in $(cat file)` | splits on spaces, globs | `while IFS= read -r f; do ...; done <file` |
| CRLF line endings | `$'\r': command not found`, `cd: /tmp\r: No such file` | `dos2unix`, `.gitattributes`: `*.sh text eol=lf`; shellcheck SC1017 |
| `sudo` inside scripts | hangs on a password prompt in CI, partial root-owned files | require root up front (`[ "$(id -u)" -eq 0 ] \|\| die "run as root"`) or document |
| relying on the caller's cwd | works from repo root only | script-relative paths (section 10) |
| `mv src existing_dir` | nests `src` inside instead of replacing | check `[ -e "$dst" ]` first; `mv -T` on GNU |
| `trap` set twice for EXIT | first cleanup silently dropped | one `cleanup()` |
| secrets in `set -x` output or argv | visible in logs and `ps` | pass via env or files, disable tracing around them |

## 12. Worked example: hardening a 60-line backup script

Before: `backup.sh SRC DEST [KEEP]` with backticks, string-built rsync options, `cd $DEST` unguarded,
`ls`-parsed rotation, `rm -rf $DEST/$d`, a JSON payload built by string concatenation, no locking.

```bash
$ shellcheck -f gcc backup-before.sh | grep -oE 'SC[0-9]+' | sort | uniq -c | sort -rn
  23 SC2086      5 SC2006      3 SC2012      2 SC2004
   1 SC2181      1 SC2164      1 SC2115      1 SC2013          # 37 findings
```

Changes (full script and tests: [script template](references/script-template.md)):
1. Header from section 2; `main "$@"`; `usage_error` exits 2; `getopts ':hnvk:x:'` with `-k KEEP`
   validated as a positive integer and repeatable `-x PATTERN` collected into an array.
2. rsync command built as an array; excludes appended with `${EXCLUDES[@]+"${EXCLUDES[@]}"}` (bash 3.2).
3. Snapshot written to `$DEST/$stamp.partial`, then `mv` (atomic); `cleanup()` on EXIT removes a
   leftover `.partial` and the lock; refuses to run if `$DEST/$stamp` already exists.
4. Lock: `flock -n 9` when `flock` exists, else `mkdir "$DEST/.backup.lock.d"`.
5. Rotation from a glob of `20*` (timestamps sort lexically), never `ls`; `rm -rf -- "${d:?}"`.
6. `-n` dry run through `run()`; notification JSON from `jq -cn --arg`, `curl -fsS --retry 3
   --retry-all-errors`, and a failed notification only logs a warning.

```bash
$ shellcheck -x backup.sh && shfmt -i 2 -ci -d backup.sh && echo clean     # shfmt v3.14.1
clean
$ /bin/bash ./backup.sh -n -x .cache src dst      # macOS bash 3.2: prints commands, creates nothing
dry-run: mkdir -p -- dst
dry-run: rsync -a --delete --exclude .cache -- src/ dst/20261019T141349Z.partial/
dry-run: mv -- dst/20261019T141349Z.partial dst/20261019T141349Z
$ for i in 1 2 3; do /bin/bash ./backup.sh -k 2 -x .cache src dst 2>/dev/null; sleep 1; done; ls dst
20261019T141350Z  20261019T141351Z                    # oldest rotated away
$ [ dst/20261019T141350Z/f2 -ef dst/20261019T141351Z/f2 ] && echo hard-linked
hard-linked
$ mkdir dst/.backup.lock.d; /bin/bash ./backup.sh src dst; echo "rc=$?"
... error: another backup is running (lock .../dst/.backup.lock.d)
rc=1
$ /bin/bash ./backup.sh -k abc src dst; echo "rc=$?"   # usage error
rc=2
```
bats suite (7 tests: usage, `-k` validation, dry run, snapshot + hard links, rotation, lock, existing
snapshot) runs in CI on `ubuntu-24.04` (bash 5.2, `flock` path) and `macos-15` (`/bin/bash` 3.2,
`mkdir` lock path). Result: shellcheck 37 -> 0, 60 -> 162 lines, every side effect behind `run()`.

Related: `ci-pipelines`, `container-images`, `regex-engineering`, `python-uv-packaging`,
`codemod-automation`, `git-advanced-workflows`, `code-review-checklist`, `security-review`, hub `coding-general`.
