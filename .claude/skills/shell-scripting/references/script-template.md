# Script template, worked example and tests

The worked example from the main skill, complete. `backup.sh` passes `shellcheck -x` and
`shfmt -i 2 -ci -d` (v3.14.1) and was exercised on macOS `/bin/bash` 3.2.57 (mkdir-lock path). The bats
suite targets bats-core 1.14 with bats-support and bats-assert.

## 1. Final `backup.sh`

```bash
#!/usr/bin/env bash
# backup.sh: snapshot SRC into DEST/<UTC timestamp>, hard-linking unchanged files; keep the newest N.
# Runs on bash 3.2 (macOS /bin/bash) and bash 5.
set -Eeuo pipefail
shopt -s inherit_errexit 2>/dev/null || true # bash >= 4.4 only
trap 'printf "%s: error at line %s: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2' ERR

readonly PROG=${0##*/}
KEEP=7
DRY_RUN=0
VERBOSE=0
EXCLUDES=()
LOCK_DIR=""
PARTIAL=""

usage() {
  cat <<EOF
Usage: $PROG [-n] [-v] [-k KEEP] [-x PATTERN]... SRC DEST
  -n  dry run: print commands, change nothing
  -k  snapshots to keep (default $KEEP)
  -x  rsync exclude pattern (repeatable)
  -v  trace commands
Env: NOTIFY_URL  optional webhook for a JSON {"text": ...} notification
EOF
}

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() {
  log "error: $*"
  exit 1
}
usage_error() {
  printf '%s: %s\n' "$PROG" "$1" >&2
  usage >&2
  exit 2
}

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'dry-run:' >&2
    printf ' %q' "$@" >&2
    printf '\n' >&2
  else
    "$@"
  fi
}

cleanup() {
  if [ -n "$PARTIAL" ] && [ -d "$PARTIAL" ]; then rm -rf -- "$PARTIAL"; fi
  if [ -n "$LOCK_DIR" ]; then rmdir -- "$LOCK_DIR" 2>/dev/null || true; fi
}

acquire_lock() {
  local lock=$1/.backup.lock
  if command -v flock >/dev/null 2>&1; then # Linux (util-linux)
    exec 9>"$lock"
    flock -n 9 || die "another backup is running (lock $lock)"
  else # macOS/BSD: mkdir is atomic
    mkdir -- "$lock.d" 2>/dev/null || die "another backup is running (lock $lock.d)"
    LOCK_DIR=$lock.d
  fi
}

parse_args() {
  local opt
  while getopts ':hnvk:x:' opt; do
    case $opt in
      h)
        usage
        exit 0
        ;;
      n) DRY_RUN=1 ;;
      v) VERBOSE=1 ;;
      k) KEEP=$OPTARG ;;
      x) EXCLUDES+=(--exclude "$OPTARG") ;;
      :) usage_error "option -$OPTARG needs a value" ;;
      *) usage_error "unknown option -$OPTARG" ;;
    esac
  done
  shift $((OPTIND - 1))
  [ $# -eq 2 ] || usage_error "expected SRC and DEST"
  case $KEEP in '' | *[!0-9]* | 0) usage_error "-k needs a positive integer" ;; esac
  SRC=${1%/}
  DEST=${2%/}
}

snapshots() { # complete snapshots, oldest first (glob order = timestamp order)
  local d
  for d in "$1"/20*; do
    case $d in *.partial) continue ;; esac
    if [ -d "$d" ]; then printf '%s\n' "$d"; fi
  done
}

rotate() {
  local keep=$1 dir=$2 total excess d
  total=$(snapshots "$dir" | wc -l | tr -d ' ')
  excess=$((total - keep))
  if [ "$excess" -le 0 ]; then return 0; fi
  snapshots "$dir" | head -n "$excess" | while IFS= read -r d; do
    log "removing ${d##*/}"
    run rm -rf -- "${d:?}"
  done
}

copy_extras() { # extra paths listed one per line in SRC/.backup-extra
  local list=$SRC/.backup-extra line
  if [ ! -f "$list" ]; then return 0; fi
  while IFS= read -r line || [ -n "$line" ]; do
    case $line in '' | '#'*) continue ;; esac
    run cp -R -- "$line" "$1/"
  done <"$list"
}

notify() {
  if [ -z "${NOTIFY_URL:-}" ]; then return 0; fi
  local payload
  payload=$(jq -cn --arg text "backup $1 done ($2)" '{text: $text}')
  run curl -fsS --retry 3 --retry-all-errors --connect-timeout 5 --max-time 30 \
    -H 'Content-Type: application/json' -d "$payload" "$NOTIFY_URL" >/dev/null ||
    log "warning: notification failed"
}

main() {
  parse_args "$@"
  if [ "$VERBOSE" -eq 1 ]; then
    PS4='+ ${BASH_SOURCE##*/}:${LINENO}: '
    set -x
  fi
  [ -d "$SRC" ] || die "source is not a directory: $SRC"
  trap cleanup EXIT
  run mkdir -p -- "$DEST"
  if [ "$DRY_RUN" -eq 0 ]; then
    DEST=$(cd -- "$DEST" && pwd -P)
    acquire_lock "$DEST"
  fi

  local stamp latest size
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  # mv into an existing directory would nest the snapshot instead of failing
  if [ -e "$DEST/$stamp" ]; then die "snapshot $stamp already exists"; fi
  latest=$(snapshots "$DEST" | tail -n 1)
  PARTIAL=$DEST/$stamp.partial
  log "snapshot $SRC -> $DEST/$stamp${latest:+ (link-dest ${latest##*/})}"

  local -a cmd
  cmd=(rsync -a --delete)
  if [ -n "$latest" ]; then cmd+=(--link-dest="$latest"); fi
  cmd+=(${EXCLUDES[@]+"${EXCLUDES[@]}"} -- "$SRC/" "$PARTIAL/")
  run "${cmd[@]}"
  copy_extras "$PARTIAL"
  run mv -- "$PARTIAL" "$DEST/$stamp" # atomic rename: a snapshot is complete or absent
  PARTIAL=""

  rotate "$KEEP" "$DEST"
  size=unknown
  if [ -d "$DEST/$stamp" ]; then size=$(du -sh -- "$DEST/$stamp" | cut -f1); fi
  notify "$stamp" "$size"
  log "done: $stamp ($size)"
}

main "$@"
```

Design notes:
- `snapshots()` prints one path per line; names are generated timestamps, so line-based handling is
  safe here. For arbitrary filenames use `find -print0` and `read -d ''`.
- The `rotate()` pipeline runs its `while` loop in a subshell; it only performs side effects, so lost
  variables do not matter.
- `run()` prints with `%q`, so a dry-run line can be pasted into a shell verbatim.
- The ERR trap reports the failing line; `die` exits directly, so expected failures do not produce a
  second "error at line" message.

## 2. bats tests (`test/backup.bats`)

```bash
#!/usr/bin/env bats
# test/backup.bats: run with `bats test/` (bats-core >= 1.5 for `run -N`; BATS_LIB_PATH set by CI)

setup() {
  bats_load_library bats-support
  bats_load_library bats-assert
  SCRIPT="$BATS_TEST_DIRNAME/../backup.sh"
  SRC="$BATS_TEST_TMPDIR/src"
  DST="$BATS_TEST_TMPDIR/dst"
  mkdir -p "$SRC/a" "$SRC/.cache"
  echo one >"$SRC/a/f1"
  echo two >"$SRC/f2"
  echo junk >"$SRC/.cache/x"
}

@test "missing DEST is a usage error (exit 2)" {
  run "$SCRIPT" "$SRC"
  assert_failure 2
  assert_output --partial "Usage:"
}

@test "-k must be a positive integer" {
  run "$SCRIPT" -k abc "$SRC" "$DST"
  assert_failure 2
  run "$SCRIPT" -k 0 "$SRC" "$DST"
  assert_failure 2
}

@test "dry run prints commands and creates nothing" {
  run "$SCRIPT" -n -x .cache "$SRC" "$DST"
  assert_success
  assert_output --partial "dry-run: rsync -a --delete --exclude .cache --"
  [ ! -e "$DST" ]
}

@test "snapshot honours excludes and hard-links unchanged files" {
  run "$SCRIPT" -x .cache "$SRC" "$DST"
  assert_success
  sleep 1
  run "$SCRIPT" -x .cache "$SRC" "$DST"
  assert_success
  snaps=("$DST"/20*)
  [ "${#snaps[@]}" -eq 2 ]
  [ ! -e "${snaps[1]}/.cache" ]
  [ "${snaps[0]}/f2" -ef "${snaps[1]}/f2" ]
}

@test "rotation keeps the newest KEEP snapshots" {
  for _ in 1 2 3; do
    run "$SCRIPT" -k 2 "$SRC" "$DST"
    assert_success
    sleep 1
  done
  snaps=("$DST"/20*)
  [ "${#snaps[@]}" -eq 2 ]
}

@test "refuses to run while another backup holds the lock" {
  mkdir -p "$DST"
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$DST/.backup.lock"
    flock -n 9
  else
    mkdir "$DST/.backup.lock.d"
  fi
  run "$SCRIPT" "$SRC" "$DST"
  assert_failure 1
  assert_output --partial "another backup is running"
}

@test "an existing snapshot directory is never nested into" {
  mkdir -p "$DST/$(date -u +%Y%m%dT%H%M%SZ)"
  run "$SCRIPT" "$SRC" "$DST"
  # either the same second (refused) or the next second (new snapshot); never a nested .partial
  if [ "$status" -ne 0 ]; then assert_output --partial "already exists"; fi
  run find "$DST" -mindepth 2 -name '*.partial'
  assert_output ""
}
```

Notes:
- `run` captures stdout and stderr together in `$output`; use `run --separate-stderr` when the
  distinction matters.
- `$BATS_TEST_TMPDIR` is unique per test and removed afterwards; never write fixtures to `/tmp` directly.
- `sleep 1` separates snapshots because names have one-second resolution; the last test covers the
  collision itself.
- Without `bats_load_library`, vendor the helpers as git submodules and `load
  'test_helper/bats-support/load'` and `load 'test_helper/bats-assert/load'` in `setup()`.

## 3. CI job (both platforms)

```yaml
  shell:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-24.04, macos-15]    # bash 5.x + flock / bash 3.2 + mkdir lock
    runs-on: ${{ matrix.os }}
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - id: bats
        uses: bats-core/bats-action@77d6fb60505b4d0d1d73e48bd035b55074bbfb43 # 4.0.0
        with: { bats-version: 1.14.0 }
      - if: runner.os == 'Linux'
        run: shellcheck -x backup.sh     # preinstalled on Ubuntu runner images
      - env: { BATS_LIB_PATH: "${{ steps.bats.outputs.lib-path }}" }
        run: /bin/bash --version | head -1 && bats test/
```
On macOS the tests call `"$SCRIPT"`, whose shebang `#!/usr/bin/env bash` resolves to `/bin/bash` 3.2
unless Homebrew bash is earlier on `PATH`; print the version in the log so the tested bash is visible.

## 4. Minimal template (copy for new scripts)

Passes `shellcheck` and `shfmt -i 2 -ci -d`; runs on bash 3.2.

```bash
#!/usr/bin/env bash
# NAME: purpose in one line.
set -Eeuo pipefail
shopt -s inherit_errexit 2>/dev/null || true
trap 'printf "%s: error at line %s: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2' ERR

readonly PROG=${0##*/}
DRY_RUN=0
tmp=""

usage() {
  cat <<EOF
Usage: $PROG [-n] [-h] ARG
  -n  dry run
EOF
}
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() {
  log "error: $*"
  exit 1
}
usage_error() {
  printf '%s: %s\n' "$PROG" "$1" >&2
  usage >&2
  exit 2
}
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'dry-run:' >&2
    printf ' %q' "$@" >&2
    printf '\n' >&2
  else
    "$@"
  fi
}
cleanup() { if [ -n "$tmp" ]; then rm -rf -- "$tmp"; fi; }

main() {
  local opt
  while getopts ':hn' opt; do
    case $opt in
      h)
        usage
        exit 0
        ;;
      n) DRY_RUN=1 ;;
      *) usage_error "unknown option -$OPTARG" ;;
    esac
  done
  shift $((OPTIND - 1))
  [ $# -eq 1 ] || usage_error "expected ARG"

  trap cleanup EXIT
  tmp=$(mktemp -d)
  log "working in $tmp on $1"
  run touch -- "$tmp/marker"
}

main "$@"
```
