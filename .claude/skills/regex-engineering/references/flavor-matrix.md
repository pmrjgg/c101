# Flavor matrix, flags, replacement and escaping

Extended reference for `regex-engineering` section 2. Rows marked "verified" were run locally (Python
3.13/3.14/3.15, Node 24, Go 1.27, BSD sed on macOS); others come from the engines' documentation and
should be rechecked for old runtime versions.

## Engines and their guarantees

| Engine | Used by | Algorithm | Worst case | Notes |
|---|---|---|---|---|
| PCRE2 | `grep -P`, `rg -P`, PHP `preg_*`, nginx, many C libs | backtracking (JIT optional) | exponential | match and depth limits configurable |
| Python `re` | stdlib | backtracking | exponential | no timeout; atomic groups and possessive quantifiers since 3.11 (verified) |
| Python `regex` (PyPI) | drop-in superset of `re` | backtracking | exponential, but `timeout=` raises `TimeoutError` (verified) | `\X`, `\p{...}`, variable-length lookbehind, full case folding `(?f)`, fuzzy matching |
| JavaScript (V8, SpiderMonkey, JSC) | browsers, Node, Deno, Bun | backtracking | exponential | no atomic/possessive (verified); `u`/`v` for Unicode |
| RE2 | Go `regexp`, `google-re2` (Python), `re2` (Node), RE2/J (Java) | automata (NFA/DFA) | linear | no lookaround, no backreferences (verified in Go) |
| Rust `regex` | Rust, ripgrep default, `sd` | automata | linear | `fancy-regex` crate adds lookaround/backrefs with backtracking |
| Java `java.util.regex` | JVM | backtracking | exponential | no timeout; interrupt-aware `CharSequence` wrapper is the usual workaround |
| .NET `System.Text.RegularExpressions` | C#, F#, PowerShell | backtracking by default; `RegexOptions.NonBacktracking` (.NET 7+) | exponential / linear | match timeout via constructor `TimeSpan`; NonBacktracking rejects atomic groups, backreferences, balancing groups, conditionals, lookarounds and `\G` |
| POSIX BRE/ERE | `grep`, `sed`, `awk` | implementation-defined | varies | leftmost-longest semantics, not leftmost-first |

## Syntax support

| Feature | PCRE2 | Python re | JS | Go | Rust | Java | .NET | POSIX ERE |
|---|---|---|---|---|---|---|---|---|
| Lazy `*?` | yes | yes | yes | yes | yes | yes | yes | no |
| Possessive `*+` | yes | 3.11+ | no | no | no | yes | no | no |
| Atomic `(?>...)` | yes | 3.11+ | no | no | no | yes | yes | no |
| Lookahead | yes | yes | yes | no | no | yes | yes | no |
| Lookbehind | bounded variable length (recent PCRE2) | fixed width | any length | no | no | bounded | any length | no |
| Backreference `\1` | yes | yes | yes | no | no | yes | yes | BRE only |
| Named backreference | `\k<n>`, `(?P=n)` | `(?P=n)` | `\k<n>` | no | no | `\k<n>` | `\k<n>` | no |
| Named group | `(?<n>)`, `(?'n')`, `(?P<n>)` | `(?P<n>)` only (verified 3.13-3.15) | `(?<n>)`; duplicate names across alternatives ES2025 | `(?P<n>)`; `(?<n>)` 1.22+ | `(?P<n>)`, `(?<n>)` 1.8+ | `(?<n>)` | `(?<n>)`, `(?'n')` | no |
| Inline flags | `(?imsx)`, `(?i:...)` | `(?aiLmsux)`, `(?i:...)` | scoped `(?i:...)` only, ES2025 (verified: `(?i)` is a syntax error) | `(?imsU)`, `(?i:...)`, no `x` (verified) | `(?imsuxUR)` | `(?idmsuxU)` | `(?imnsx)` | no |
| `\A` / `\z` | yes | `\A`, `\Z`; `\z` 3.14+ (verified) | no (`\A` is a literal `A` without `u`, an error with `u`; verified) | yes | yes | yes | yes | no |
| `\b` Unicode-aware | with UCP | yes | no (verified, even with `u`) | no (verified) | yes (default) | with `UNICODE_CHARACTER_CLASS` | yes | GNU `\b`, BSD `[[:<:]]` `[[:>:]]` |
| `\d` Unicode digits | with UCP | yes on `str` (verified) | no | no (verified) | yes (default; `(?-u:\d)` for ASCII) | with `UNICODE_CHARACTER_CLASS` | yes (`RegexOptions.ECMAScript` for ASCII) | no `\d` at all |
| `\p{L}` | yes | no | `u`/`v` | yes | yes | yes | yes | no |
| `\X` grapheme | yes | no (`regex` yes) | no (`Intl.Segmenter`) | no | no | `\X` (Java 9+) | no | no |
| Set operations in classes | no | no | `v`: `--`, `&&` | no | `--`, `&&`, `~~` | `&&` | subtraction `[a-z-[aeiou]]` | no |
| Counted repetition limit | large | large | large | 1000 (verified) | size limit | large | large | `RE_DUP_MAX` (often 255) |

## Flags quick reference

| Meaning | Python | JS | Go/RE2 | Rust | Java | .NET |
|---|---|---|---|---|---|---|
| Case-insensitive | `re.I` | `i` | `(?i)` | `(?i)` / `case_insensitive(true)` | `CASE_INSENSITIVE` (+ `UNICODE_CASE`) | `IgnoreCase` |
| `^`/`$` per line | `re.M` | `m` | `(?m)` | `(?m)` | `MULTILINE` | `Multiline` |
| `.` matches `\n` | `re.S` | `s` | `(?s)` | `(?s)` | `DOTALL` | `Singleline` |
| Verbose | `re.X` | none | none | `(?x)` | `COMMENTS` | `IgnorePatternWhitespace` |
| ASCII classes | `re.A` | default | default | `(?-u)` | default | `ECMAScript` |
| Unicode mode | default for `str` | `u` / `v` | default for `\p` | default | `UNICODE_CHARACTER_CLASS` | default |
| Swap greediness | none | none | `(?U)` | `(?U)` | none | none |

## Replacement syntax

| Engine / tool | Numbered | Named | Whole match | Literal `$` or `\` |
|---|---|---|---|---|
| Python `re.sub` | `\1`, `\g<1>` | `\g<name>` | `\g<0>` | `\\`; or pass a function |
| JS `String.replace` | `$1` | `$<name>` | `$&` | `$$`; or pass a function |
| Go `ReplaceAllString` / `Expand` | `${1}` (`$1x` is group `1x`; verified) | `${name}` | `${0}` | `$$`; `ReplaceAllLiteralString` |
| Rust `Regex::replace` | `$1`, `${1}` | `$name`, `${name}` | `$0` | `$$`; `NoExpand` |
| Java `Matcher.replaceAll` | `$1` | `${name}` | `$0` | `Matcher.quoteReplacement(s)` |
| .NET `Regex.Replace` | `$1` | `${name}` | `$0` | `$$` |
| GNU/BSD sed | `\1` | none | `&` | `\&`, `\\` |
| perl `s///` | `$1` | `$+{name}` | `$&` | `\$` |
| sd | `$1`, `${1}` | `$name`, `${name}` | `$0` | `$$`; `-F` for literal find |

## Escaping literal input

| Language | Pattern side | Replacement side |
|---|---|---|
| Python | `re.escape(s)` | `s.replace("\\", "\\\\")` or a function replacer |
| JavaScript | `RegExp.escape(s)` (ES2025; Node 24 verified; escapes a leading alphanumeric as `\x61`) | function replacer `() => s` |
| Go | `regexp.QuoteMeta(s)` (verified) | `ReplaceAllLiteralString` |
| Rust | `regex::escape(s)` | `regex::NoExpand(s)` |
| Java | `Pattern.quote(s)` | `Matcher.quoteReplacement(s)` |
| .NET | `Regex.Escape(s)` | `s.Replace("$", "$$")` |
| Shell (`grep`, `rg`) | `grep -F` / `rg -F` (fixed strings) | n/a |

## GNU versus BSD command-line tools

| Behaviour | GNU (Linux) | BSD (macOS, FreeBSD) |
|---|---|---|
| In-place edit | `sed -i 's/a/b/' f` | `sed -i '' 's/a/b/' f` (verified) |
| ERE | `sed -E` (also `-r`) | `sed -E` |
| `\+`, `\?`, `\|` in BRE | extensions supported | not supported; use `-E` |
| Word boundaries | `\b`, `\<`, `\>` | `[[:<:]]`, `[[:>:]]` |
| `\n` in replacement | inserts newline | needs a literal backslash-newline |
| `grep -P` | if built with PCRE | availability varies by OS release; prefer `rg -P` or `perl` |

Portable choice for scripts that must run on both: `perl -pi -e` (same syntax everywhere) or `rg` +
`sd`; for read-only searches, `rg` everywhere.
