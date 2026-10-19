# Portability: GNU, BSD/macOS, BusyBox, POSIX sh

macOS userland differs by release (recent releases added `sha256sum`, `realpath`, and a grep built on
ugrep with `-P`). When a script must run on several systems, test each one in CI rather than trusting a
table; rows marked "varies" are release-dependent.

## 1. Shells

| Need | bash 3.2 (macOS `/bin/bash`) | bash 4.x/5.x | zsh (macOS login shell) | dash / POSIX sh | BusyBox ash |
|---|---|---|---|---|---|
| indexed arrays | yes | yes | yes, 1-based | no | no |
| associative arrays | no | yes | yes (`typeset -A`) | no | no |
| `[[ ]]` | yes | yes | yes | no | partial |
| `local` | yes | yes | yes | yes (not POSIX, but dash has it) | yes |
| `<( )` process substitution | yes | yes | yes | no | no |
| `$'\t'` ANSI-C quoting | yes | yes | yes | varies (POSIX.1-2024 added it; older dash lacks it) | varies |
| `mapfile` | no | yes | no | no | no |
| `${v,,}` case conversion | no | yes | different syntax `${(L)v}` | no | no |
| `read -d ''` | yes | yes | yes | no | no |
| `pipefail` | yes | yes | yes | varies (absent in older dash, including macOS `/bin/dash`) | varies |
| `inherit_errexit` | no | 4.4+ | n/a | n/a | n/a |
| `${!var}` indirection | yes | yes | `${(P)var}` | no | no |

Run scripts with their shebang interpreter; `sh script.sh` on Debian/Ubuntu runs dash and ignores
`#!/bin/bash`. zsh does not word-split unquoted variables by default, so a script "working in zsh" proves
nothing about bash.

## 2. Core utilities

| Task | GNU coreutils / findutils / sed | macOS / BSD | BusyBox | Portable approach |
|---|---|---|---|---|
| in-place sed | `sed -i 's/a/b/' f` | `sed -i '' 's/a/b/' f` | `sed -i` | write to temp and `mv`, or `perl -pi -e` |
| extended regex sed | `sed -E` (also `-r`) | `sed -E` | `sed -E`/`-r` | `sed -E` |
| `\n` in sed replacement | yes | varies (older BSD sed needs a backslash-newline) | yes | `awk` or `perl` |
| date from epoch | `date -u -d @1700000000 +%F` | `date -u -r 1700000000 +%F` | `date -u -d @1700000000` | `perl -MPOSIX -e 'print strftime("%F", gmtime(shift))' 1700000000` |
| date arithmetic | `date -d '+1 day' +%F` | `date -v+1d +%F` | limited | epoch seconds + 86400, or Python |
| ISO-8601 now (UTC) | `date -u +%Y-%m-%dT%H:%M:%SZ` | same | same | same (avoid `%N`, GNU only) |
| file size | `stat -c %s f` | `stat -f %z f` | `stat -c %s f` | `wc -c <f` |
| mtime (epoch) | `stat -c %Y f` | `stat -f %m f` | `stat -c %Y f` | `find f -newer ref` comparisons |
| canonical path | `readlink -f p`, `realpath p` | `readlink -f` (macOS 12.3+), `realpath` (varies) | `readlink -f` | `cd -- "$(dirname -- "$p")" && pwd -P` |
| PCRE grep | `grep -P` | varies (ugrep-based grep has `-P`) | no | `grep -E`, `perl -ne 'print if /.../'` |
| xargs, empty input | runs once unless `-r` | never runs; `-r` accepted | `-r` supported | always pass `-r` |
| xargs NUL input | `xargs -0` | `xargs -0` | `xargs -0` | `-print0 \| xargs -0` |
| find, print format | `find -printf '%s %p\n'` | no `-printf` | no | `-exec stat ... {} +` per platform or `-exec sh -c` |
| find, delete | `-delete` | `-delete` | `-delete` | `-exec rm -- {} +` most portable |
| sort by version | `sort -V` | `sort -V` (recent) | varies | avoid; compare fields with `sort -t. -k1,1n -k2,2n` |
| reverse lines | `tac` | `tail -r` | `tac` | `awk '{a[NR]=$0} END {for (i=NR;i;i--) print a[i]}'` |
| all but last line | `head -n -1` | no | varies | `sed '$d'` |
| timeout a command | `timeout 10 cmd` | not installed (Homebrew `gtimeout`) | `timeout` | `perl -e 'alarm shift; exec @ARGV' 10 cmd` |
| checksum | `sha256sum -c` | `shasum -a 256 -c` (recent macOS also has `sha256sum`) | `sha256sum` | `shasum -a 256` exists wherever Perl does |
| base64 decode | `base64 -d` | `base64 -d` (also `-D`) | `base64 -d` | `base64 -d` |
| temp dir | `mktemp -d` | `mktemp -d` | `mktemp -d` | `mktemp -d "${TMPDIR:-/tmp}/name.XXXXXX"` |
| file lock | `flock` | no `flock` (`lockf`, `shlock` exist) | `flock` | `mkdir` lock directory |
| install with parents | `install -D -m 0644 src dst` | no `-D` | varies | `mkdir -p "$(dirname "$dst")" && install -m 0644 src "$dst"` |
| move, no nesting | `mv -T src dst` | no `-T` | varies | `[ -e "$dst" ] && die; mv src dst` |
| numeric human sizes | `du -sh`, `numfmt` | `du -sh` (no `numfmt`) | `du -sh` | `du -sk` and compute |
| `cp` preserve all | `cp -a` | `cp -a` (macOS supports `-a`) | `cp -a` | `cp -a` or `rsync -a` |
| `ls` sorted by time | do not parse | do not parse | do not parse | `find ... -newer`, or glob of timestamped names |

## 3. Detecting the platform

```bash
case $(uname -s) in
  Linux) sed_inplace() { sed -i "$@"; } ;;
  Darwin | *BSD) sed_inplace() { sed -i '' "$@"; } ;;
  *) die "unsupported OS: $(uname -s)" ;;
esac
# feature detection beats OS detection where possible:
if sed --version >/dev/null 2>&1; then GNU_SED=1; else GNU_SED=0; fi
if command -v flock >/dev/null 2>&1; then HAVE_FLOCK=1; else HAVE_FLOCK=0; fi
```
Prefer feature detection (`command -v`, `--version` probes): Homebrew coreutils (`gsed`, `gdate`), Nix
and BusyBox all break OS-based assumptions.

## 4. Line endings and encodings

- Windows checkouts can turn `.sh` into CRLF: bash then fails with `$'\r': command not found`.
  `.gitattributes`: `*.sh text eol=lf` and `*.bats text eol=lf`; detect with `file script.sh` or
  `grep -c $'\r' script.sh`; shellcheck reports SC1017.
- A UTF-8 BOM before `#!` breaks the shebang; strip it.
- `LC_ALL=C` makes `sort`, `tr` and character classes byte-wise and fast; set it explicitly where
  ordering matters, since CI images and laptops differ in locale.
