# Approximate matching: tested implementations

Companion to section 7 of the string-algorithms skill. Both functions were checked against the
plain Wagner-Fischer DP on 3 000 random pairs over {a, b, c} of length <= 10 (and every threshold
k <= 6 for the banded version).

## 1. Reference DP (the oracle)

```python
def levenshtein(a, b):                       # O(nm) time, O(m) space
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]
```

## 2. Myers / Hyyro bit-parallel edit distance

One machine word (here an arbitrary-precision Python int) holds the vertical deltas of a whole
DP column, so each text character costs O(ceil(m / w)) word operations. Pv/Mv encode +1/-1
vertical differences, Ph/Mh horizontal ones; `score` tracks the bottom cell.

```python
def myers_distance(a, b):                    # global Levenshtein distance between a and b
    m = len(a)
    if m == 0: return len(b)
    peq = {}
    for i, c in enumerate(a): peq[c] = peq.get(c, 0) | 1 << i
    mask, hb = (1 << m) - 1, 1 << (m - 1)
    pv, mv, score = mask, 0, m
    for c in b:
        eq = peq.get(c, 0)
        xv = eq | mv
        xh = ((((eq & pv) + pv) & mask) ^ pv) | eq
        ph = (mv | ~(xh | pv)) & mask
        mh = pv & xh
        if ph & hb: score += 1
        elif mh & hb: score -= 1
        ph = ((ph << 1) | 1) & mask          # "| 1": global distance (top row 0, 1, 2, ...)
        mh = (mh << 1) & mask
        pv = (mh | ~(xv | ph)) & mask
        mv = ph & xv
    return score
```

For approximate *search* (pattern a anywhere in text b, top row all zeros) drop the `| 1` and
report every position where `score <= k`. Production versions: `edlib` (mode "NW" global, "HW"
infix, "SHW" prefix), `rapidfuzz.distance.Levenshtein` (uses bit-parallel kernels internally and
takes `score_cutoff`).

## 3. Banded distance with a threshold

```python
def banded_distance(a, b, k):                # distance if <= k, else None; O((n + m) k)
    n, m = len(a), len(b)
    if abs(n - m) > k: return None
    INF = k + 1
    prev = {j: j for j in range(0, min(m, k) + 1)}
    for i in range(1, n + 1):
        cur = {}
        for j in range(max(0, i - k), min(m, i + k) + 1):
            best = prev.get(j, INF) + 1                       # delete a[i-1]
            if j > 0:
                best = min(best, cur.get(j - 1, INF) + 1,     # insert b[j-1]
                           prev.get(j - 1, INF) + (a[i - 1] != b[j - 1]))
            cur[j] = min(best, INF)
        prev = cur
    d = prev.get(m, INF)
    return d if d <= k else None
```

Why the band is safe: any alignment path through a cell with abs(i - j) > k already costs more
than k (each unit of diagonal offset needs one insertion or deletion), so cells outside the band
can be treated as k + 1. Use an array of width 2k + 1 instead of dicts in compiled languages, and
stop early when the whole band exceeds k.

## 4. Choosing among them

| n, m, k | Choice |
|---|---|
| one pair, m <= 64 | Myers in one word: O(n) |
| one pair, small k | banded, or Ukkonen's cut-off: O(nk) |
| one query vs a large dictionary | SymSpell or BK-tree candidates, verify with Myers |
| all pairs in a corpus | n-gram or MinHash blocking first, verify survivors |
| biological sequences with substitution matrices and gaps | parasail (SIMD Smith-Waterman / Needleman-Wunsch) |
