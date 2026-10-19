---
name: string-algorithms
description: "String and sequence algorithms with production implementations: single- and multi-pattern exact search (prefix function/KMP, Z, Horspool, two-way, Aho-Corasick), rolling hashes with collision math, suffix arrays with LCP, suffix automata, BWT/FM-index, approximate matching (banded and bit-parallel edit distance, BK-trees, n-gram indexes), and Unicode correctness. Load when searching, indexing, deduplicating or comparing text, logs or sequences."
when_to_use: "Substring or multi-keyword search over logs or documents; 'find repeated/common substrings'; fuzzy name or typo matching; deduplicating text; building a full-text or sequence index; hand-rolled hashing of substrings; string code that slows down on large or adversarial input; length, offset or comparison bugs with accents, emoji or Turkish i."
---

# String algorithms

Exact and approximate matching, indexes, and Unicode hygiene. Regex practice is in
`regex-engineering`; fuzzy near-duplicate detection at scale (MinHash/LSH) in
`randomized-algorithms-sketches`; hub `cs-foundations` section 5. Tested bit-parallel and banded
edit distance: [approximate matching code](references/approximate-matching.md).

## 1. Decision table

| Task | Algorithm | Cost | Use in production |
|---|---|---|---|
| one pattern, one text | two-way (Crochemore-Perrin) / SIMD prefilter | O(n + m), O(1) space | `memchr::memmem` (Rust), glibc `memmem`, Python `str.find` (two-way for long needles since 3.10) |
| one pattern, need failure structure | prefix function (KMP) or Z-function | O(n + m) | section 2 |
| short pattern, large alphabet, many texts | Horspool | sublinear average, O(nm) worst | simple tools |
| many fixed patterns | Aho-Corasick | O(n + sum m + z) | Rust `aho-corasick` (Teddy SIMD for small sets), `pyahocorasick` |
| many regexes over streams | automata with SIMD | linear-ish | ripgrep, Vectorscan (open fork of Hyperscan) |
| many queries on one fixed text | suffix array + LCP, FM-index | O(m log n) or O(m) per query | `libsais`, `pydivsufsort`, sdsl-lite |
| substring equality, repeats | rolling hash (verify matches) | O(1) per comparison after O(n) | section 3 |
| edit distance <= k | banded DP / Myers bit-parallel | O(nk) / O(n ceil(m/w)) | `rapidfuzz`, `edlib` |
| alignment with scoring matrices | Smith-Waterman / Needleman-Wunsch, SIMD | O(nm) | `parasail`, `edlib` (unit costs) |
| fuzzy lookup in a dictionary | BK-tree, SymSpell, trigram index | sublinear in practice | PostgreSQL `pg_trgm`, rapidfuzz `process.extract` |

## 2. Prefix function and Z-function

pi[i] = length of the longest proper border (prefix that is also a suffix) of s[0..i].
z[i] = length of the longest common prefix of s and s[i:]. Both run in O(n): the pointer k in
the prefix function rises by at most 1 per character and every fallback lowers it.

```python
def prefix_function(s):
    pi = [0] * len(s)
    for i in range(1, len(s)):
        k = pi[i - 1]
        while k and s[i] != s[k]: k = pi[k - 1]     # walk the border chain (border tree)
        if s[i] == s[k]: k += 1
        pi[i] = k
    return pi

def z_function(s):
    n = len(s); z = [0] * n; l = r = 0
    if n: z[0] = n
    for i in range(1, n):
        if i < r: z[i] = min(r - i, z[i - l])        # reuse the rightmost match box [l, r)
        while i + z[i] < n and s[z[i]] == s[i + z[i]]: z[i] += 1
        if i + z[i] > r: l, r = i, i + z[i]
    return z

def occurrences(p, t):              # pattern + sentinel + text; sentinel occurs in neither
    pi, m = prefix_function(list(p) + [None] + list(t)), len(p)
    return [i - 2 * m for i, v in enumerate(pi) if v == m]

def smallest_period(s):
    p = len(s) - prefix_function(s)[-1]
    return p, len(s) % p == 0       # full repetition of s[:p] only when p divides n
```

`occurrences("aba", "abababa") == [0, 2, 4]` (overlapping); `smallest_period("abcabcabc") ==
(3, True)`; `smallest_period("abcab") == (3, False)`. Uses: compression check (s = u^k), counting
prefix occurrences via the border tree, and the Z-array for "longest prefix of p starting at
each position of t" (compute on p + sentinel + t).

## 3. Rolling hash done safely

Polynomial hash H(s) = sum s[i] B^(n-1-i) mod p with p = 2^61 - 1 (a Mersenne prime: fast
reduction) and a **random** base B chosen at runtime. For two different strings of length n,
H(x) - H(y) is a non-zero polynomial of degree <= n - 1 in B, so P(collision) <= (n - 1) / p per
comparison (about 4 x 10^-13 for n = 10^6). Over many comparisons use the union bound, so
**always verify** a hash match before acting on it.

- mod 2^64 (natural overflow) is broken for every base: Thue-Morse strings of length ~2^11 collide.
- Fixed bases or small primes (10^9 + 7) are attackable and hit the birthday bound at ~sqrt(p)
  distinct substrings; double hashing with two primes squares the denominator.

```python
import random
M61 = (1 << 61) - 1
class RollingHash:
    def __init__(self, s, base=None):
        self.b = base or random.SystemRandom().randrange(1 << 20, M61 - 1)
        self.h, self.pw = [0], [1]
        for c in s:
            self.h.append((self.h[-1] * self.b + ord(c)) % M61)
            self.pw.append(self.pw[-1] * self.b % M61)
    def get(self, i, j):                             # hash of s[i:j] in O(1)
        return (self.h[j] - self.h[i] * self.pw[j - i]) % M61

def longest_repeated_substring(s):                   # O(n log n) expected
    rh = RollingHash(s)
    def find(L):
        seen = {}
        for i in range(len(s) - L + 1):
            key = rh.get(i, i + L)
            for j in seen.get(key, ()):
                if s[j:j + L] == s[i:i + L]: return i  # verified, not just hashed
            seen.setdefault(key, []).append(i)
        return -1
    lo, hi, best = 1, len(s) - 1, ""
    while lo <= hi:                                  # "a repeat of length L exists" is monotone
        mid = (lo + hi) // 2; i = find(mid)
        if i >= 0: best, lo = s[i:i + mid], mid + 1
        else: hi = mid - 1
    return best
```

In C++ or Rust compute (a * b) mod 2^61 - 1 with a 128-bit product and the shift-add reduction.

## 4. Aho-Corasick

Build a trie of the patterns, then BFS to set failure links (longest proper suffix of the node's
string that is also a trie node) and output (dictionary) links (nearest failure ancestor that ends
a pattern). Scanning is O(n + z) after O(sum m) construction (times alphabet for a full DFA).

| Semantics | Reports | Rust `aho-corasick` |
|---|---|---|
| overlapping, all matches | every (pattern, end) pair | `MatchKind::Standard` with `find_overlapping_iter` |
| leftmost-first | first pattern in priority order at the leftmost position (regex-like) | `MatchKind::LeftmostFirst` |
| leftmost-longest | longest match at the leftmost position (tokenisers) | `MatchKind::LeftmostLongest` |

```python
import ahocorasick                                   # pyahocorasick
A = ahocorasick.Automaton()
for idx, word in enumerate(words):
    A.add_word(word, (idx, word))
A.make_automaton()
hits = [(end - len(w) + 1, idx) for end, (idx, w) in A.iter(text)]   # overlapping matches
```

Memory for 10^6+ patterns: the NFA form (failure transitions, ~tens of bytes per state) is
compact; a full DFA is |states| x |alphabet| and fastest; double-array tries (darts, cedar)
compress static dictionaries. The Rust crate picks NFA vs DFA by size unless told otherwise.

## 5. Suffix array toolkit

| Item | Cost / formula |
|---|---|
| construction | SA-IS / libsais O(n); prefix doubling O(n log n) with radix sort (O(n log^2 n) with a comparison sort, below) |
| LCP array | Kasai O(n) |
| pattern search | O(m log n) by binary search; O(m + log n) with LCP-LR arrays |
| distinct substrings | n(n+1)/2 - sum(LCP) |
| longest repeated substring | max LCP |
| longest common substring of s, t | max LCP over adjacent suffixes from different strings in s + sentinel + t |
| alternative | suffix automaton: <= 2n - 1 states, <= 3n - 4 transitions, online construction |

```python
def suffix_array(seq):                     # seq: list of ints; prefix doubling
    n = len(seq); sa = list(range(n)); rank = list(seq); k = 1
    if n <= 1: return sa
    while True:
        key = lambda i: (rank[i], rank[i + k] if i + k < n else -1)
        sa.sort(key=key)
        new = [0] * n
        for a, b in zip(sa, sa[1:]): new[b] = new[a] + (key(a) != key(b))
        rank = new
        if rank[sa[-1]] == n - 1: return sa
        k <<= 1

def lcp_kasai(seq, sa):                    # lcp[i] = LCP(suffix sa[i-1], suffix sa[i]), lcp[0] = 0
    n = len(seq); rank = [0] * n; lcp = [0] * n; h = 0
    for i, p in enumerate(sa): rank[p] = i
    for p in range(n):
        if rank[p] > 0:
            q = sa[rank[p] - 1]
            while p + h < n and q + h < n and seq[p + h] == seq[q + h]: h += 1
            lcp[rank[p]] = h
            if h: h -= 1                   # LCP drops by at most 1 when p advances
        else:
            h = 0
    return lcp
```

Check: "banana" has 21 - (1 + 3 + 0 + 0 + 2) = 15 distinct substrings.

## 6. BWT and FM-index

BWT[i] = character preceding suffix SA[i]. Backward search for P processes P right to left:
[sp, ep) <- [C[c] + occ(c, sp), C[c] + occ(c, ep)), O(m) rank queries. occ is answered from
checkpoints every s positions plus a popcount or scan inside the block (larger s: less memory,
slower rank). Locating each hit costs O(s_A) LF steps with SA samples every s_A positions. Space:
about n log sigma bits plus samples, far below a plain SA (n log n bits).

Implementations: sdsl-lite (wavelet-tree CSAs), the r-index (space proportional to the number of
BWT runs, for highly repetitive collections such as pangenomes), BWA-MEM2 and bowtie2 (FM-index
read aligners). minimap2 is the long-read reference but seeds with minimizers, not an FM-index.

## 7. Approximate matching

| Need | Method | Cost |
|---|---|---|
| exact Levenshtein | Wagner-Fischer DP, two rows | O(nm) time, O(min(n, m)) space |
| distance only if <= k | banded DP (cells with abs(i - j) <= k) | O((n + m) k) |
| distance, words of w bits | Myers / Hyyro bit-parallel | O(n ceil(m / w)) |
| transpositions count 1 | Damerau-Levenshtein (a metric) vs OSA (restricted, violates the triangle inequality) | O(nm) |
| person and place names | Jaro-Winkler (prefix bonus) | O(nm) worst |
| SQL fuzzy search | trigram index: PostgreSQL `pg_trgm` GIN/GiST, `similarity()`, `%` | index lookup + verify |
| dictionary within distance d | BK-tree (needs a true metric: not OSA); SymSpell (pre-computed deletions) | sublinear in practice |

Lower bound: no O(n^(2 - eps)) algorithm for exact edit distance unless SETH fails
(Backurs-Indyk), so for long pairs bound k (banded), use bit-parallelism, or approximate; for
many pairs filter with n-grams or MinHash first and verify survivors exactly.

## 8. Unicode correctness

| Level | Example ("e" + U+0301 acute, "👍🏽") | APIs |
|---|---|---|
| bytes (UTF-8) | 3 bytes; 8 bytes | Rust `str::len`, Go `len` |
| UTF-16 code units | 2; 4 (two surrogate pairs) | Java `String.length()`, JS `.length` |
| code points | 2; 2 | Python `len`, Rust `.chars().count()` |
| grapheme clusters (UAX #29) | 1; 1 | Python `regex` `\X`, Rust `unicode-segmentation`, ICU `BreakIterator`, JS `Intl.Segmenter` |

- Normalise before comparing or hashing: NFC for storage and equality, NFKC for identifiers and
  search (UAX #15): `unicodedata.normalize("NFC", s)`.
- Caseless matching uses `casefold()`, not `lower()`: "ß".casefold() == "ss"; Turkish dotted and
  dotless i need locale-aware rules ("İ".lower() is "i" + U+0307 in Python).
- Sorting for humans: ICU collation (`Intl.Collator`, PyICU, `icu::Collator`), never code-point
  order.
- Identifier spoofing: UTS #39 confusable skeletons (ICU SpoofChecker) for usernames and domains.

## 9. Pitfalls

- `s += t` in a loop is quadratic in many runtimes: build with `"".join(parts)`, `StringBuilder`,
  `String::with_capacity`.
- Hidden copies: slicing `s[i:j]` in Python and `substring` in Java allocate; pass indices.
- Naive `find` loops are O(nm) on adversarial input (`"a" * m + "b"` in `"a" * n`).
- Treating a hash match as equality: always verify (section 3).
- A sentinel that occurs in the alphabet (`$` in log lines): use out-of-alphabet integers.
- Mixing byte offsets and character offsets across APIs (regex spans vs UTF-8 buffers, JS UTF-16
  indices vs Python code points).

## 10. Worked example: longest substring present in at least k of N log files

Build one integer sequence: file i contributes its characters (as code + N) followed by a unique
sentinel i. Sentinels are distinct and smaller than every character, so no LCP crosses a file
boundary and the N sentinel suffixes sort first. Then slide a window over SA positions: extend
right, shrink left while the left suffix's file is duplicated or more than k files are present,
and read the window's common prefix as the minimum LCP inside it via a monotone deque.

```python
from collections import deque
def longest_common_in_k(strs, k):
    N = len(strs)
    if k <= 1: return max(strs, key=len, default="")
    seq, owner = [], []
    for i, s in enumerate(strs):
        seq += [ord(c) + N for c in s] + [i]; owner += [i] * len(s) + [-1]
    sa = suffix_array(seq); lcp = lcp_kasai(seq, sa)
    cnt, distinct, l = [0] * N, 0, N           # SA[0..N-1] are the sentinel suffixes
    dq, best_len, best_pos = deque(), 0, 0     # dq: indices in (l, r], lcp increasing
    for r in range(N, len(sa)):
        o = owner[sa[r]]; cnt[o] += 1; distinct += cnt[o] == 1
        if r > l:
            while dq and lcp[dq[-1]] >= lcp[r]: dq.pop()
            dq.append(r)
        while l < r and (cnt[owner[sa[l]]] > 1 or distinct > k):
            o2 = owner[sa[l]]; cnt[o2] -= 1; distinct -= cnt[o2] == 0; l += 1
            while dq and dq[0] <= l: dq.popleft()
        if distinct >= k and dq and lcp[dq[0]] > best_len:
            best_len, best_pos = lcp[dq[0]], sa[r]
    return "".join(chr(c - N) for c in seq[best_pos:best_pos + best_len])
```

Cost: O(L) for the window after the suffix array (L = total length plus N): SA-IS keeps the whole
pipeline linear; this prefix-doubling demo is O(L log^2 L). Example:
`longest_common_in_k(["xabcdy", "zabcdq", "abce", "bcd"], k)` returns "abcd" for k = 2, "abc" for
k = 3 and "bc" for k = 4.

Verification run for this skill: 1 500 seeded corpora (N <= 5 files of length <= 9 over {a, b, c},
k in [1, N]) against a brute force that tests every substring of every file with `in`; lengths
always match and the returned string occurs in >= k files. The same run checked the prefix
function, Z-function, periods, distinct-substring counts and the hash-based longest repeat on
3 000 random strings against naive definitions.

For real logs: normalise first (strip timestamps and IDs, or the answer is a timestamp prefix),
use libsais on bytes, and for fuzzy near-duplicate lines use MinHash/LSH from
`randomized-algorithms-sketches`, then verify candidate pairs exactly.

Related: `regex-engineering`, `randomized-algorithms-sketches`, `data-structure-selection`, `dynamic-programming-patterns`, `algorithm-design-paradigms`, `np-hardness-reductions`, hub `cs-foundations`
