#!/usr/bin/env python3
"""prose_check.py - markdown-aware prose checks for fiction manuscripts (style, mechanics, consistency, readability).

Reads a file, several files or a project directory (chapters found through manuscript.md conventions: chapter_dir and
chapter_pattern, defaults chapters/ and ^(\\d{3})_([a-z0-9][a-z0-9-]*)\\.md$). Front matter, headings, fenced code and
HTML comments are skipped; reported line numbers are always the ORIGINAL file's. Dialogue is text inside straight or
curly double quotes. Word lists live in wordlists/<language>.json next to this script.

Standard library only (Python 3.9+). No network access: manuscript text never leaves the machine.
Exit codes: 0 ok, 2 usage. JSON on stdout (compact; the full flag list goes to --out).
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import re
import sys
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_CHAPTER_DIR = "chapters"
DEFAULT_PATTERN = r"^(\d{3})_([a-z0-9][a-z0-9-]*)\.md$"
SEV_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}
WORD_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*")          # counting words (hyphenated compound = 1)
TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")        # alphabetic tokens (hyphen splits)
OPEN_Q = '"“'
CLOSE_Q = '"”'
FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
BREAK_RE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
COMMENT_RE = re.compile(r"<!--.*?-->")
SENT_BOUNDARY = re.compile(r"[.!?…]+[\"”’')\]]*\s+")
LANG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*$")
STYLE_CHECKS = ["filter_words", "weak_verbs", "adverbs", "dialogue_tags", "intensifiers", "cliches", "ai_tells",
                "tell_emotion", "purple", "repetition", "rhythm"]
MECH_CHECKS = ["double_space", "quote_mix", "unbalanced_quotes", "dash", "ellipsis_style", "dialogue_punct",
               "repeated_word", "british_spelling", "number_style", "confused_word"]
REPEAT_ALLOWED = {"had", "that", "bye", "ha", "so", "no"}
SUFFIX_ADJ = ("ous", "ful", "less", "ive", "ish", "ic")
ISOLATED_CLOSED = {"anyone", "anything", "anyway", "sometime", "sometimes", "everyday", "everyone", "someone",
                   "somewhere", "anywhere", "altogether", "into", "onto", "maybe", "somehow", "somebody", "nobody",
                   "another", "forever", "already", "always", "cannot", "inside", "outside", "without", "within"}
GENERIC_BIBLE_WORDS = {"characters", "places", "timeline", "glossary", "notes", "names", "chapter", "style", "sheet",
                       "name", "role", "wants", "voice", "description", "place", "term", "definition"}


class UsageError(Exception):
    """Bad invocation or unreadable input (exit 2)."""


# ---------------------------------------------------------------------------------------------------------------
# Minimal front matter / project conventions (same YAML subset as manuscript.py)

def _parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return ""
    if s[0] in "\"'":
        q = s[0]
        out: List[str] = []
        i = 1
        while i < len(s):
            c = s[i]
            if q == '"' and c == "\\" and i + 1 < len(s) and s[i + 1] in '"\\':
                out.append(s[i + 1])
                i += 2
                continue
            if q == "'" and c == "'" and s[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            if c == q:
                return "".join(out)
            out.append(c)
            i += 1
        raise ValueError("unterminated quoted string")
    if s[0] == "[":
        end = s.find("]")
        if end < 0:
            raise ValueError("unterminated list")
        return [_parse_scalar(x) for x in s[1:end].split(",") if x.strip()]
    cut = s.find(" #")
    if cut >= 0:
        s = s[:cut].rstrip()
    if re.fullmatch(r"-?(0|[1-9]\d*)", s):
        return int(s)
    return s


def read_front_matter(text: str) -> Dict[str, Any]:
    lines = text.lstrip("﻿").split("\n")
    meta: Dict[str, Any] = {}
    if not lines or lines[0].strip() != "---":
        return meta
    for j in range(1, len(lines)):
        if lines[j].strip() in ("---", "..."):
            for line in lines[1:j]:
                m = re.match(r"^([A-Za-z_][\w-]*)\s*:(?:\s+(.*)|\s*)$", line.rstrip("\r"))
                if m:
                    try:
                        meta[m.group(1)] = _parse_scalar(m.group(2) or "")
                    except ValueError:
                        pass
            return meta
    return meta


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline=None) as fh:
            return fh.read()
    except OSError as exc:
        raise UsageError("cannot read %s: %s" % (path, exc)) from exc


def project_files(root: str) -> Tuple[List[str], Dict[str, Any]]:
    meta: Dict[str, Any] = {}
    mpath = os.path.join(root, "manuscript.md")
    if os.path.isfile(mpath):
        meta = read_front_matter(read_text(mpath))
    cdir = meta.get("chapter_dir", DEFAULT_CHAPTER_DIR)
    if not isinstance(cdir, str) or not cdir.strip() or os.path.isabs(cdir) or ".." in cdir.replace("\\", "/").split("/"):
        raise UsageError("%s: invalid chapter_dir" % mpath)
    pat = meta.get("chapter_pattern", DEFAULT_PATTERN)
    try:
        rx = re.compile(pat if isinstance(pat, str) else DEFAULT_PATTERN)
    except re.error as exc:
        raise UsageError("%s: invalid chapter_pattern: %s" % (mpath, exc)) from exc
    if rx.groups != 2:
        raise UsageError("%s: chapter_pattern needs exactly 2 groups" % mpath)
    full = os.path.join(root, cdir.strip().rstrip("/"))
    if not os.path.isdir(full):
        raise UsageError("%s: chapter directory %r not found (is this a manuscript project?)" % (root, cdir))
    found = []
    for name in os.listdir(full):
        m = rx.match(name)
        if m and not name.startswith(".") and os.path.isfile(os.path.join(full, name)):
            try:
                found.append((int(m.group(1)), name))
            except ValueError:
                raise UsageError("chapter_pattern group 1 must capture digits (file %s)" % name) from None
    found.sort()
    return [os.path.join(full, n) for _k, n in found], meta


def resolve_inputs(paths: Sequence[str]) -> Tuple[List[str], Dict[str, Any]]:
    files: List[str] = []
    meta: Dict[str, Any] = {}
    for p in paths:
        if os.path.isdir(p):
            fs, meta_p = project_files(p)
            files.extend(fs)
            meta = meta or meta_p
        elif os.path.isfile(p):
            files.append(p)
        else:
            raise UsageError("no such file or directory: %s" % p)
    seen = set()
    uniq = []
    for f in files:
        key = os.path.realpath(f)
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq, meta


# ---------------------------------------------------------------------------------------------------------------
# Word lists

def wordlist_dirs() -> List[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    real = os.path.dirname(os.path.realpath(__file__))
    out = [os.path.join(here, "wordlists")]
    if real != here:
        out.append(os.path.join(real, "wordlists"))
    return out


def phrase_regex(phrase: str) -> str:
    """Phrase -> regex source: spaces flex, apostrophes straight or curly, {p} pronoun, {pos} possessive, {w} word."""
    out = []
    for token in re.split(r"(\{p\}|\{pos\}|\{w\})", phrase):
        if token == "{p}":
            out.append(r"(?:he|she|they|I|we|you)")
        elif token == "{pos}":
            out.append(r"(?:his|her|their|my|your|our|its)")
        elif token == "{w}":
            out.append(r"\w+")
        else:
            buf = []
            prev_space = False
            for ch in token:
                if ch.isspace():
                    if not prev_space:
                        buf.append(r"\s+")
                    prev_space = True
                    continue
                prev_space = False
                buf.append("['’]" if ch in "'’" else re.escape(ch))
            out.append("".join(buf))
    return "".join(out)


def alternation(phrases: Iterable[str]) -> "Optional[re.Pattern[str]]":
    items = sorted(set(phrases), key=lambda s: (-len(s), s))
    if not items:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(phrase_regex(p) for p in items) + r")(?!\w)", re.I)


class WordLists:
    def __init__(self, data: Dict[str, Any], language: str) -> None:
        self.data = data
        self.language = language
        self.stop = set(w.lower() for w in data.get("stopwords", []))
        self.filter_rx = alternation(data.get("filter_words", []))
        self.intens_rx = alternation(data.get("intensifiers", []))
        self.cliche_rx = alternation(data.get("cliches", []))
        self.ai_rx = alternation(data.get("ai_tells", []))
        wp = data.get("weak_verb_patterns", {})
        items = sorted(wp.items()) if isinstance(wp, dict) else [("pattern%d" % i, p) for i, p in enumerate(wp)]
        self.weak = [(name, re.compile(p)) for name, p in items]
        self.bookisms = set(w.lower() for w in data.get("said_bookisms", []))
        self.neutral = set(w.lower() for w in data.get("neutral_tags", ["said", "asked", "replied", "answered"]))
        self.adjectives = set(w.lower() for w in data.get("adjectives", []))
        self.abbrev = set(w.lower() for w in data.get("abbreviations", []))
        self.ly_exceptions = set(w.lower() for w in data.get("ly_exceptions", []))
        emo = sorted(set(w.lower() for w in data.get("emotion_words", [])), key=lambda s: (-len(s), s))
        verbs = sorted(set(w.lower() for w in data.get("tell_verbs", [])), key=lambda s: (-len(s), s))
        self.tell_rxs: List[Tuple["re.Pattern[str]", str]] = []
        if emo and verbs:
            e = "|".join(re.escape(x) for x in emo)
            v = "|".join(re.escape(x) for x in verbs)
            adv = r"(?:\w+ly|very|so|too|quite|rather|more|less|a\s+bit|a\s+little)"
            nouns = r"(?:wave|surge|rush|pang|stab|twinge|flood|jolt|burst|flash|swell|knot)"
            self.tell_rxs = [
                (re.compile(r"(?<!\w)(?:filled|overcome|consumed|flooded|seized|gripped|overwhelmed|paralyzed)\s+(?:with|by)\s+(?:%s)(?!\w)" % e, re.I), "emotion named after filled/overcome with"),
                (re.compile(r"(?<!\w)%s\s+of\s+(?:%s)(?!\w)" % (nouns, e), re.I), "emotion named as a surge/wave of"),
                (re.compile(r"(?<!\w)(?:%s)\s+(?:%s\s+)?(?:%s)(?!\w)" % (v, adv, e), re.I), "state verb + emotion word"),
                (re.compile(r"(?<!\w)(?:with|in)\s+(?:(?:a|an|the|sheer|utter|pure|growing|rising|mounting|great)\s+)?(?:%s)(?!\w)" % e, re.I), "with/in + emotion word"),
            ]
        self.british_rx = None
        self.british: Dict[str, str] = {}
        for k, val in data.get("british_to_us", {}).items():
            self.british[re.sub(r"\s+", " ", k.lower())] = val
        if self.british:
            keys = sorted(self.british, key=lambda s: (-len(s), s))
            self.british_rx = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in keys) + r")(?!\w)", re.I)
        self.confused: List[Tuple["re.Pattern[str]", str]] = []
        for item in data.get("confused_words", []):
            if isinstance(item, dict) and "pattern" in item:
                self.confused.append((re.compile(item["pattern"]), item.get("hint", "commonly confused words")))


def load_wordlists(language: str) -> WordLists:
    if not LANG_RE.match(language):
        raise UsageError("invalid --language %r" % language)
    tried = []
    for d in wordlist_dirs():
        path = os.path.join(d, language + ".json")
        tried.append(path)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return WordLists(json.load(fh), language)
            except (OSError, ValueError) as exc:
                raise UsageError("cannot load word list %s: %s" % (path, exc)) from exc
    raise UsageError("no word list for language %r (looked for %s)" % (language, ", ".join(tried)))


# ---------------------------------------------------------------------------------------------------------------
# Document model

def scan_quotes(text: str) -> Tuple[List[Tuple[int, int]], bool, bool]:
    """Return (dialogue spans, balanced, unclosed)."""
    spans: List[Tuple[int, int]] = []
    start = -1
    stray = False
    for i, ch in enumerate(text):
        if start < 0:
            if ch in OPEN_Q:
                start = i
            elif ch == "”":
                stray = True
        elif ch in CLOSE_Q:
            spans.append((start, i + 1))
            start = -1
    unclosed = start >= 0
    if unclosed:
        spans.append((start, len(text)))
    return spans, (not unclosed and not stray), unclosed


class Para:
    __slots__ = ("lines", "text", "starts", "spans", "span_starts", "balanced", "unclosed", "nwords", "dwords")

    def __init__(self, lines: List[Tuple[int, str]]) -> None:
        self.lines = lines
        self.starts: List[int] = []
        parts = []
        pos = 0
        for _ln, t in lines:
            self.starts.append(pos)
            parts.append(t)
            pos += len(t) + 1
        self.text = " ".join(parts)
        self.spans, self.balanced, self.unclosed = scan_quotes(self.text)
        self.span_starts = [s for s, _e in self.spans]
        self.nwords = 0
        self.dwords = 0
        for m in WORD_RE.finditer(self.text):
            self.nwords += 1
            if self.in_dialogue(m.start()):
                self.dwords += 1

    def loc(self, off: int) -> Tuple[int, int]:
        i = max(bisect.bisect_right(self.starts, off) - 1, 0)
        return self.lines[i][0], off - self.starts[i] + 1

    def in_dialogue(self, off: int) -> bool:
        i = bisect.bisect_right(self.span_starts, off) - 1
        return i >= 0 and off < self.spans[i][1]


def mask_markdown(lines: List[str]) -> Tuple[List[str], List[str]]:
    """Return (masked, pre) per original line. masked: only prose, comments blanked in place (columns kept).
    pre: like masked but inline HTML comments left in (used by the double-space check)."""
    n = len(lines)
    masked = [""] * n
    pre = [""] * n
    start = 0
    if n and lines[0].lstrip("﻿").strip() == "---":
        for j in range(1, n):
            if lines[j].strip() in ("---", "..."):
                start = j + 1
                break
    fence = ""
    in_comment = False
    for idx in range(start, n):
        line = lines[idx]
        if fence:
            if line.strip().startswith(fence):
                fence = ""
            continue
        if in_comment:
            end = line.find("-->")
            if end < 0:
                continue
            line = " " * (end + 3) + line[end + 3:]
            in_comment = False
        fm = FENCE_RE.match(line)
        if fm:
            fence = fm.group(1)
            continue
        if HEADING_RE.match(line) or BREAK_RE.match(line):
            continue
        text = COMMENT_RE.sub(lambda m: " " * len(m.group(0)), line)
        k = text.find("<!--")
        if k >= 0:
            text = text[:k] + " " * (len(text) - k)
            in_comment = True
        pre[idx] = line
        masked[idx] = text if text.strip() else ""
    return masked, pre


class Doc:
    def __init__(self, path: str, display: Optional[str] = None) -> None:
        self.path = path
        self.display = display or path
        text = read_text(path)
        self.lines = text.split("\n")
        self.masked, self.pre = mask_markdown(self.lines)
        self.paras: List[Para] = []
        cur: List[Tuple[int, str]] = []
        for i, t in enumerate(self.masked):
            if t.strip():
                cur.append((i + 1, t.rstrip()))
            elif cur:
                self.paras.append(Para(cur))
                cur = []
        if cur:
            self.paras.append(Para(cur))
        self.words = sum(p.nwords for p in self.paras)
        self.dwords = sum(p.dwords for p in self.paras)
        self._sentences: Optional[List[Tuple[int, int, int, int]]] = None

    def sentences(self, abbrev: Iterable[str]) -> List[Tuple[int, int, int, int]]:
        """[(para_index, start, end, nwords)] in document order."""
        if self._sentences is None:
            ab = set(abbrev)
            out = []
            for pi, p in enumerate(self.paras):
                for s, e in split_sentences(p.text, ab):
                    out.append((pi, s, e, len(WORD_RE.findall(p.text[s:e]))))
            self._sentences = out
        return self._sentences


def split_sentences(text: str, abbrev: Iterable[str]) -> List[Tuple[int, int]]:
    ab = abbrev if isinstance(abbrev, set) else set(abbrev)
    out: List[Tuple[int, int]] = []
    start = 0
    for m in SENT_BOUNDARY.finditer(text):
        end = m.end()
        nxt = text[end:end + 2]
        if not nxt:
            break
        c = nxt[0]
        ok = c.isupper() or c.isdigit() or (c in "\"“‘'([" and (nxt[1:2].isupper() or nxt[1:2].isdigit()))
        if not ok:
            continue
        if re.fullmatch(r"\.\s+", m.group(0)):
            w = re.search(r"([A-Za-z]+)$", text[start:m.start()])
            if w and (w.group(1).lower() in ab or len(w.group(1)) == 1):
                continue
        if text[start:m.start()].strip():
            out.append((start, m.start() + len(m.group(0).rstrip())))
        start = end
    if text[start:].strip():
        out.append((start, len(text.rstrip())))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Flags

def collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def context(text: str, ms: int, me: int, width: int = 120) -> str:
    if len(text) <= width:
        return collapse(text)
    pre = max((width - (me - ms)) // 2, 0)
    a = max(ms - pre, 0)
    b = min(a + width, len(text))
    a = max(b - width, 0)
    snip = collapse(text[a:b])
    if a > 0:
        snip = "…" + snip[1:]
    if b < len(text):
        snip = snip[:-1] + "…"
    return snip[:width]


def mkflag(doc: Doc, p: Para, ms: int, me: int, check: str, severity: str, note: Optional[str] = None,
           match: Optional[str] = None, dialogue: bool = False) -> Dict[str, Any]:
    line, col = p.loc(ms)
    f: Dict[str, Any] = {
        "file": doc.display, "line": line, "col": col, "check": check,
        "match": collapse(match if match is not None else p.text[ms:me])[:60],
        "context": context(p.text, ms, me), "severity": severity,
    }
    if note:
        f["note"] = note
    if dialogue:
        f["in_dialogue"] = True
    return f


def scan(doc: Doc, rx: "Optional[re.Pattern[str]]", check: str, severity: str, narr_only: bool = False,
         dialogue_severity: Optional[str] = None, note: Optional[str] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if rx is None:
        return out
    for p in doc.paras:
        for m in rx.finditer(p.text):
            d = p.in_dialogue(m.start())
            if narr_only and d:
                continue
            out.append(mkflag(doc, p, m.start(), m.end(), check, (dialogue_severity or severity) if d else severity,
                              note=note, dialogue=d and not narr_only))
    return out


def top_flags(flags: List[Dict[str, Any]], top: int) -> List[Dict[str, Any]]:
    """Per check, the `top` most severe flags (ties by position), final list in file order."""
    by_check: Dict[str, List[Dict[str, Any]]] = {}
    for f in flags:
        by_check.setdefault(f["check"], []).append(f)
    keep: List[Dict[str, Any]] = []
    for check in sorted(by_check):
        items = sorted(by_check[check], key=lambda f: (SEV_RANK.get(f["severity"], 9), f["line"], f["col"]))
        keep.extend(items[:top])
    keep.sort(key=lambda f: (f["line"], f["col"], f["check"]))
    return keep


def is_ly_adverb(word: str, wl: WordLists) -> bool:
    w = word.lower()
    return len(w) >= 5 and w.endswith("ly") and w not in wl.ly_exceptions


def per_1000(n: int, words: int) -> float:
    return round(1000.0 * n / words, 2) if words else 0.0


# ---------------------------------------------------------------------------------------------------------------
# Style checks

def tag_events(doc: Doc, wl: WordLists) -> List[Dict[str, Any]]:
    """Dialogue tags: speech verb found within three words after a closing quote."""
    events: List[Dict[str, Any]] = []
    verbs = wl.bookisms | wl.neutral
    for p in doc.paras:
        t = p.text
        for s, e in p.spans:
            if e - s < 2 or t[e - 1] not in CLOSE_Q:
                continue
            before = t[e - 2]
            rest = t[e:e + 90]
            cut = len(rest)
            for q in OPEN_Q + CLOSE_Q:
                k = rest.find(q)
                if 0 <= k < cut:
                    cut = k
            stripped = rest.lstrip()
            lowercase_follow = bool(stripped) and stripped[0].islower()
            if not (before in ",?!—-" or lowercase_follow):
                continue
            toks = [(m.group(0).lower(), e + m.start(), e + m.end()) for m in TOKEN_RE.finditer(rest[:cut])][:4]
            for idx, (word, ms, me) in enumerate(toks[:3]):
                if word in verbs:
                    adv = None
                    for j in (idx - 1, idx + 1):
                        if 0 <= j < len(toks) and is_ly_adverb(toks[j][0], wl):
                            adv = toks[j]
                    events.append({"p": p, "word": word, "ms": ms, "me": me,
                                   "kind": "neutral" if word in wl.neutral else "bookism", "adv": adv})
                    break
    return events


def chk_dialogue_tags(doc: Doc, wl: WordLists, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for ev in ctx["events"]:
        if ev["kind"] == "bookism":
            out.append(mkflag(doc, ev["p"], ev["ms"], ev["me"], "dialogue_tags", "medium",
                              note="said-bookism: prefer said/asked or an action beat"))
    return out


def chk_adverbs(doc: Doc, wl: WordLists, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for ev in ctx["events"]:
        if ev["adv"]:
            a = ev["adv"]
            ms, me = min(ev["ms"], a[1]), max(ev["me"], a[2])
            out.append(mkflag(doc, ev["p"], ms, me, "adverbs", "medium", note="adverb on a dialogue tag"))
    for pi, s, e, _n in doc.sentences(wl.abbrev):
        p = doc.paras[pi]
        found = [m for m in TOKEN_RE.finditer(p.text, s, e) if is_ly_adverb(m.group(0), wl) and not p.in_dialogue(m.start())]
        if len(found) >= 2:
            out.append(mkflag(doc, p, found[0].start(), found[-1].end(), "adverbs", "low",
                              note="%d -ly adverbs in one sentence" % len(found),
                              match=", ".join(m.group(0) for m in found)))
    return out


def chk_tell_emotion(doc: Doc, wl: WordLists, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for p in doc.paras:
        covered: List[Tuple[int, int]] = []
        for rx, note in wl.tell_rxs:
            for m in rx.finditer(p.text):
                s, e = m.start(), m.end()
                if p.in_dialogue(s):
                    continue
                if any(s < ce and cs < e for cs, ce in covered):
                    continue
                if rx.pattern.startswith("(?<!\\w)(?:with|in)") and re.search(r"\bin\s+love\b", m.group(0), re.I):
                    continue
                covered.append((s, e))
                out.append(mkflag(doc, p, s, e, "tell_emotion", "medium", note="telling: %s; consider showing" % note))
    return out


def adjective_like(p: Para, m: "re.Match[str]", wl: WordLists) -> bool:
    w = m.group(0).lower()
    if w in wl.stop or p.in_dialogue(m.start()):
        return False
    return w in wl.adjectives or (len(w) >= 6 and w.endswith(SUFFIX_ADJ))


def chk_purple(doc: Doc, wl: WordLists, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    sim_rx = re.compile(r"(?<!\w)(?:like\s+(?:a|an|the)\s+\w+|as\s+\w+\s+as\s+(?:a|an|the)\s+\w+)", re.I)
    sep_ok = re.compile(r"^(?:\s+|\s*,\s*(?:and\s+)?|\s+and\s+)$", re.I)
    for p in doc.paras:
        toks = list(TOKEN_RE.finditer(p.text))
        i = 0
        while i < len(toks):
            if not adjective_like(p, toks[i], wl):
                i += 1
                continue
            j = i
            while j + 1 < len(toks) and adjective_like(p, toks[j + 1], wl) and sep_ok.match(p.text[toks[j].end():toks[j + 1].start()]):
                j += 1
            if j - i + 1 >= 3:
                out.append(mkflag(doc, p, toks[i].start(), toks[j].end(), "purple", "medium",
                                  note="stack of %d adjectives" % (j - i + 1)))
            i = j + 1
        sims = [m for m in sim_rx.finditer(p.text) if not p.in_dialogue(m.start())]
        ctx["similes"] += len(sims)
        if len(sims) >= 2:
            for m in sims:
                out.append(mkflag(doc, p, m.start(), m.end(), "purple", "low", note="%d similes in one paragraph" % len(sims)))
        for m in re.finditer(r"!", p.text):
            if not p.in_dialogue(m.start()):
                ctx["exclaims"] += 1
                out.append(mkflag(doc, p, m.start(), m.end(), "purple", "low", note="exclamation mark in narration"))
    return out


def chk_repetition(doc: Doc, wl: WordLists, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    skip = wl.stop | wl.neutral | wl.bookisms
    last: Dict[str, Tuple[int, int, int]] = {}
    idx = 0
    for p in doc.paras:
        for m in TOKEN_RE.finditer(p.text):
            if p.in_dialogue(m.start()):
                continue
            idx += 1
            w = m.group(0)
            lw = w.lower()
            if len(lw) < 4 or w[0].isupper() or lw in skip:
                continue
            prev = last.get(lw)
            if prev and idx - prev[0] <= 50:
                out.append(mkflag(doc, p, m.start(), m.end(), "repetition", "low",
                                  note="'%s' also on line %d (%d words earlier)" % (lw, prev[1], idx - prev[0])))
            line, col = p.loc(m.start())
            last[lw] = (idx, line, col)
    sents = doc.sentences(wl.abbrev)
    openers = []
    for pi, s, e, _n in sents:
        p = doc.paras[pi]
        if p.text[s:s + 1] in OPEN_Q:
            openers.append(None)
            continue
        m = TOKEN_RE.search(p.text, s, e)
        openers.append(m.group(0).lower() if m else None)
    i = 0
    while i < len(sents):
        if openers[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < len(sents) and openers[j + 1] == openers[i]:
            j += 1
        if j - i + 1 >= 3:
            pi, s, _e, _n = sents[i]
            out.append(mkflag(doc, doc.paras[pi], s, s + len(openers[i]), "repetition", "medium",
                              note="%d sentences in a row start with '%s'" % (j - i + 1, openers[i])))
        i = j + 1
    return out


def chk_rhythm(doc: Doc, wl: WordLists, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    sents = doc.sentences(wl.abbrev)
    for pi, s, e, n in sents:
        if n > 35:
            out.append(mkflag(doc, doc.paras[pi], s, e, "rhythm", "low", note="%d-word sentence" % n,
                              match=" ".join(doc.paras[pi].text[s:e].split()[:8]) + "..."))
    i = 0
    while i < len(sents):
        j = i
        lo = hi = sents[i][3]
        while j + 1 < len(sents):
            nl, nh = min(lo, sents[j + 1][3]), max(hi, sents[j + 1][3])
            if nh - nl > 3:
                break
            lo, hi = nl, nh
            j += 1
        if j - i + 1 >= 4 and lo >= 6:
            pi, s, e, _n = sents[i]
            out.append(mkflag(doc, doc.paras[pi], s, e, "rhythm", "low",
                              note="run of %d sentences of %d-%d words" % (j - i + 1, lo, hi),
                              match=" ".join(doc.paras[pi].text[s:e].split()[:8]) + "..."))
        i = max(j, i) + 1
    return out


def style_for_doc(doc: Doc, wl: WordLists, checks: List[str]) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {"events": tag_events(doc, wl), "similes": 0, "exclaims": 0}
    # purple must run for the simile/exclamation metrics even when not selected: cheap
    flags: List[Dict[str, Any]] = []
    simple = {
        "filter_words": lambda: scan(doc, wl.filter_rx, "filter_words", "low", narr_only=True),
        "weak_verbs": lambda: [f for name, rx in wl.weak for f in scan(doc, rx, "weak_verbs", "low", narr_only=True, note=name)],
        "intensifiers": lambda: scan(doc, wl.intens_rx, "intensifiers", "low", narr_only=True),
        "cliches": lambda: scan(doc, wl.cliche_rx, "cliches", "medium", dialogue_severity="low"),
        "ai_tells": lambda: scan(doc, wl.ai_rx, "ai_tells", "medium", dialogue_severity="low"),
    }
    complex_ = {
        "adverbs": chk_adverbs, "dialogue_tags": chk_dialogue_tags, "tell_emotion": chk_tell_emotion,
        "purple": chk_purple, "repetition": chk_repetition, "rhythm": chk_rhythm,
    }
    counts: Dict[str, int] = {}
    for c in STYLE_CHECKS:
        if c not in checks:
            continue
        res = simple[c]() if c in simple else complex_[c](doc, wl, ctx)
        # de-duplicate identical (line, col, check, note) hits from overlapping patterns
        seen = set()
        uniq = []
        for f in res:
            key = (f["line"], f["col"], f["check"], f.get("note", ""))
            if key not in seen:
                seen.add(key)
                uniq.append(f)
        counts[c] = len(uniq)
        flags.extend(uniq)
    flags.sort(key=lambda f: (f["line"], f["col"], f["check"]))
    if "purple" not in checks:
        chk_purple(doc, wl, ctx)
    sents = doc.sentences(wl.abbrev)
    lens = [n for _pi, _s, _e, n in sents]
    mean = sum(lens) / len(lens) if lens else 0.0
    sd = math.sqrt(sum((x - mean) ** 2 for x in lens) / len(lens)) if lens else 0.0
    ly = 0
    for p in doc.paras:
        ly += sum(1 for m in TOKEN_RE.finditer(p.text) if is_ly_adverb(m.group(0), wl))
    ev = ctx["events"]
    metrics: Dict[str, Any] = {
        "words": doc.words, "dialogue_words": doc.dwords,
        "dialogue_ratio": round(doc.dwords / float(doc.words), 4) if doc.words else 0.0,
        "sentences": len(lens), "paragraphs": len(doc.paras),
        "sentence_mean_words": round(mean, 2), "sentence_stdev_words": round(sd, 2),
        "pct_sentences_over_35": round(100.0 * sum(1 for x in lens if x > 35) / len(lens), 2) if lens else 0.0,
        "ly_adverbs_per_1000": per_1000(ly, doc.words),
        "similes_per_1000": per_1000(ctx["similes"], doc.words),
        "narration_exclamations_per_1000": per_1000(ctx["exclaims"], doc.words),
        "tags": {"neutral": sum(1 for x in ev if x["kind"] == "neutral"),
                 "bookisms": sum(1 for x in ev if x["kind"] == "bookism"),
                 "adverb_tags": sum(1 for x in ev if x["adv"])},
        "per_1000": {c: per_1000(n, doc.words) for c, n in counts.items()},
    }
    return {"file": doc.display, "words": doc.words, "metrics": metrics, "counts": counts, "flags": flags}


# ---------------------------------------------------------------------------------------------------------------
# Mechanics checks

def mech_for_doc(doc: Doc, wl: WordLists, checks: List[str], ignore: set) -> Dict[str, Any]:
    flags: List[Dict[str, Any]] = []
    info: Dict[str, Any] = {}
    want = set(checks)
    sd = cd = sa = ca = dots = ell = 0
    for p in doc.paras:
        sd += p.text.count('"')
        cd += p.text.count("“") + p.text.count("”")
        sa += len(re.findall(r"(?<=\w)'(?=\w)", p.text))
        ca += len(re.findall(r"(?<=\w)’(?=\w)", p.text))
        dots += len(re.findall(r"(?<!\.)\.\.\.(?!\.)", p.text))
        ell += p.text.count("…")
    info["quotes"] = {"straight_double": sd, "curly_double": cd, "straight_apostrophe": sa, "curly_apostrophe": ca,
                      "three_dots": dots, "ellipsis_char": ell}

    if "double_space" in want:
        for i, line in enumerate(doc.pre):
            if not line.strip() or "<!--" in line:
                continue
            for m in re.finditer(r"(?<=\S)  +(?=\S)", line):
                flags.append({"file": doc.display, "line": i + 1, "col": m.start() + 1, "check": "double_space", "match": "  ",
                              "context": context(line, m.start(), m.end()), "severity": "low", "note": "collapse to a single space"})

    for pi, p in enumerate(doc.paras):
        t = p.text
        if "quote_mix" in want:
            if sd and cd:
                minority = '"' if sd <= cd else None
                rxq = re.compile(r'"') if minority else re.compile("[“”]")
                for m in rxq.finditer(t):
                    flags.append(mkflag(doc, p, m.start(), m.end(), "quote_mix", "medium", note="straight and curly double quotes are mixed; use one style"))
            if sa and ca:
                rxa = re.compile(r"(?<=\w)'(?=\w)") if sa <= ca else re.compile(r"(?<=\w)’(?=\w)")
                for m in rxa.finditer(t):
                    flags.append(mkflag(doc, p, m.start(), m.end(), "quote_mix", "low", note="straight and curly apostrophes are mixed; use one style"))
        if "unbalanced_quotes" in want and not p.balanced:
            nxt = doc.paras[pi + 1] if pi + 1 < len(doc.paras) else None
            continued = p.unclosed and nxt is not None and nxt.text[:1] in OPEN_Q
            if not continued:
                pos = next((i for i, ch in enumerate(t) if ch in '"“”'), 0)
                flags.append(mkflag(doc, p, pos, pos + 1, "unbalanced_quotes", "medium",
                                    note="quotes do not pair up in this paragraph (fine only if the speech continues in the next paragraph)"))
        if "dash" in want:
            for m in re.finditer(r"(?<!-)--(?!-)", t):
                flags.append(mkflag(doc, p, m.start(), m.end(), "dash", "medium", note="use a closed em dash"))
            for m in re.finditer(r"(?<=\w) - (?=\w)", t):
                flags.append(mkflag(doc, p, m.start(), m.end(), "dash", "medium", note="spaced hyphen used as a dash; use a closed em dash"))
            for m in re.finditer(r"\s[—–]\s|\s[—–](?=\w)|(?<=\w)[—–]\s", t):
                flags.append(mkflag(doc, p, m.start(), m.end(), "dash", "low", note="spaced em/en dash; Chicago uses a closed em dash"))
        if "ellipsis_style" in want:
            if dots and ell:
                rxe = re.compile(r"(?<!\.)\.\.\.(?!\.)") if dots <= ell else re.compile("…")
                for m in rxe.finditer(t):
                    flags.append(mkflag(doc, p, m.start(), m.end(), "ellipsis_style", "low", note="'...' and the ellipsis character are mixed; use one"))
            for m in re.finditer(r"\.{4,}|(?<!\.)\. \. \.(?!\.)", t):
                flags.append(mkflag(doc, p, m.start(), m.end(), "ellipsis_style", "low", note="non-standard ellipsis"))
        if "dialogue_punct" in want:
            tag = r"(?:said|asked|replied|answered|whispered|murmured|muttered|shouted|cried|called|added|continued|told|snapped|growled)"
            for m in re.finditer(r"\.([\"”])\s+(?:(?:he|she|they|it|we)\b|(%s\b))" % tag, t):
                flags.append(mkflag(doc, p, m.start(), m.end(), "dialogue_punct", "medium", note="a tag after a closing quote needs a comma, not a period, inside the quote"))
            for m in re.finditer(r"[,]([\"”])\s+(?:He|She|They|It|We)\b", t):
                flags.append(mkflag(doc, p, m.start(), m.end(), "dialogue_punct", "medium", note="comma before the closing quote makes the next word part of the tag: lowercase it"))
            for m in re.finditer(r"[?!]([\"”])\s+(?:He|She|They|It|We)\s+%s\b" % tag, t):
                flags.append(mkflag(doc, p, m.start(), m.end(), "dialogue_punct", "medium", note="tag after ? or ! starts lowercase"))
        if "repeated_word" in want:
            for m in re.finditer(r"(?<![\w'’])([A-Za-z]+)\s+\1(?![\w'’])", t, re.I):
                if m.group(1).lower() not in REPEAT_ALLOWED:
                    flags.append(mkflag(doc, p, m.start(), m.end(), "repeated_word", "medium", note="repeated word"))
        if "british_spelling" in want and wl.british_rx is not None:
            for m in wl.british_rx.finditer(t):
                key = re.sub(r"\s+", " ", m.group(0).lower())
                if key in ignore:
                    continue
                us = wl.british[key]
                if m.group(0)[:1].isupper():
                    us = us[:1].upper() + us[1:]
                flags.append(mkflag(doc, p, m.start(), m.end(), "british_spelling", "medium", note="US: %s" % us))
        if "number_style" in want:
            for m in re.finditer(r"(?<![\w.:$#/\-])(?<!\d,)(\d{1,2}|100)(?!\d|,\d|\.\d|[\w:%/\-])", t):
                flags.append(mkflag(doc, p, m.start(), m.end(), "number_style", "low", note="spell out numbers up to one hundred in fiction (times and addresses excepted)"))
        if "confused_word" in want:
            for rx, hint in wl.confused:
                for m in rx.finditer(t):
                    flags.append(mkflag(doc, p, m.start(), m.end(), "confused_word", "low", note=hint))
    seen = set()
    uniq = []
    for f in flags:
        key = (f["line"], f["col"], f["check"], f.get("note", ""))
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    uniq.sort(key=lambda f: (f["line"], f["col"], f["check"]))
    counts = {c: 0 for c in checks}
    for f in uniq:
        counts[f["check"]] += 1
    return {"file": doc.display, "words": doc.words, "counts": counts, "info": info, "flags": uniq}


# ---------------------------------------------------------------------------------------------------------------
# Readability

def syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    n = len(re.findall(r"[aeiouy]+", w))
    if n > 1:
        if w.endswith("e") and not w.endswith("le"):
            n -= 1
        elif w.endswith("ed") and not w.endswith(("ted", "ded")):
            n -= 1
        elif w.endswith("es") and not w.endswith(("ses", "xes", "zes", "ches", "shes", "ces", "ges")):
            n -= 1
    return max(n, 1)


def read_stats(text_words: List[str], n_sent: int) -> Dict[str, float]:
    n_words = len(text_words)
    if n_words == 0 or n_sent == 0:
        return {"flesch": 0.0, "fk": 0.0, "wps": 0.0, "spw": 0.0, "long": 0.0}
    syl = sum(syllables(w) for w in text_words)
    wps = n_words / float(n_sent)
    spw = syl / float(n_words)
    long_pct = 100.0 * sum(1 for w in text_words if len(re.sub(r"[^A-Za-z]", "", w)) >= 7) / n_words
    return {"flesch": 206.835 - 1.015 * wps - 84.6 * spw, "fk": 0.39 * wps + 11.8 * spw - 15.59,
            "wps": wps, "spw": spw, "long": long_pct}


def readability_for_doc(doc: Doc, wl: WordLists, min_words: int) -> Dict[str, Any]:
    all_words: List[str] = []
    n_sent = 0
    paras = []
    for p in doc.paras:
        ws = WORD_RE.findall(p.text)
        sc = len(split_sentences(p.text, wl.abbrev))
        all_words.extend(ws)
        n_sent += sc
        if len(ws) >= min_words:
            st = read_stats(ws, sc)
            paras.append({"line": p.lines[0][0], "words": len(ws), "flesch_reading_ease": round(st["flesch"], 1),
                          "fk_grade": round(st["fk"], 1), "context": context(p.text, 0, 0)})
    st = read_stats(all_words, n_sent)
    paras.sort(key=lambda r: (r["flesch_reading_ease"], r["line"]))
    return {"file": doc.display, "words": len(all_words), "sentences": n_sent,
            "flesch_reading_ease": round(st["flesch"], 1), "fk_grade": round(st["fk"], 1),
            "avg_words_per_sentence": round(st["wps"], 2), "avg_syllables_per_word": round(st["spw"], 3),
            "pct_long_words": round(st["long"], 1), "hardest_paragraphs": paras[:10]}, all_words, n_sent


# ---------------------------------------------------------------------------------------------------------------
# Consistency

def edit_distance(a: str, b: str, limit: int = 3) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            best = min(best, v)
        if best > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def similar_names(a: str, b: str) -> bool:
    la, lb = a.lower(), b.lower()
    if la == lb or min(len(la), len(lb)) < 4:
        return False
    d = edit_distance(la, lb, 3)
    if d <= 2:
        return True
    return d == 3 and min(len(la), len(lb)) >= 6 and la[:3] == lb[:3]


def strip_possessive(w: str) -> str:
    return re.sub(r"['’]s$", "", w)


def bible_names(root: str, stop: set) -> List[str]:
    names = set()
    files = []
    bdir = os.path.join(root, "bible")
    if os.path.isdir(bdir):
        files += [os.path.join(bdir, n) for n in sorted(os.listdir(bdir)) if n.lower().endswith(".md")]
    ss = os.path.join(root, "style-sheet.md")
    if os.path.isfile(ss):
        files.append(ss)
    for f in files:
        for line in read_text(f).split("\n"):
            frags = []
            m = re.match(r"^\s{0,3}#{1,6}\s+(.+)$", line)
            if m:
                frags.append(m.group(1))
            frags += re.findall(r"\*\*(.+?)\*\*", line)
            m = re.match(r"^\|\s*([^|]+?)\s*\|", line)
            if m:
                frags.append(m.group(1))
            m = re.match(r"^\s*[-*]\s+([A-Z][\w'’ -]{2,40}?)\s*[:—]", line)
            if m:
                frags.append(m.group(1))
            for fr in frags:
                for t in TOKEN_RE.findall(fr):
                    t = strip_possessive(t)
                    if len(t) >= 4 and t[0].isupper() and not t.isupper() and t.lower() not in stop and t.lower() not in GENERIC_BIBLE_WORDS:
                        names.add(t)
    return sorted(names)


def loc_str(doc: Doc, p: Para, off: int) -> str:
    ln, col = p.loc(off)
    return "%s:%d:%d" % (doc.display, ln, col)


def consistency_report(root: str, files: List[str], wl: WordLists, top: int) -> Dict[str, Any]:
    stop = wl.stop
    caps: Dict[str, Dict[str, Any]] = {}
    lower_seen = set()
    cap_mid: Counter = Counter()
    low_mid: Counter = Counter()
    mid_loc: Dict[Tuple[str, bool], List[str]] = {}
    hy: Counter = Counter()
    hy_loc: Dict[Tuple[str, str], str] = {}
    openb: Counter = Counter()
    open_loc: Dict[Tuple[str, str], str] = {}
    uni: Counter = Counter()
    uni_loc: Dict[str, str] = {}
    n_files = 0
    for fi, path in enumerate(files):
        doc = Doc(path)
        n_files += 1
        for pi, p in enumerate(doc.paras):
            t = p.text
            sents = split_sentences(t, wl.abbrev)
            first_offsets = set()
            for s, e in sents:
                m = TOKEN_RE.search(t, s, e)
                if m:
                    first_offsets.add(m.start())
            prev_end = None
            prev_tok = None
            for m in TOKEN_RE.finditer(t):
                word = strip_possessive(m.group(0))
                lw = word.lower()
                off = m.start()
                before = t[off - 1] if off > 0 else ""
                initial = off in first_offsets or before in OPEN_Q

                if word == lw:
                    lower_seen.add(lw)
                if word[:1].isupper() and not word.isupper() and len(word) >= 3:
                    rec = caps.setdefault(word, {"count": 0, "paras": set(), "locs": [], "files": set()})
                    rec["count"] += 1
                    rec["paras"].add((fi, pi))
                    rec["files"].add(doc.display)
                    if len(rec["locs"]) < 3:
                        rec["locs"].append(loc_str(doc, p, off))
                if not initial and lw not in stop and len(lw) >= 3:
                    if word[:1].isupper() and not word.isupper():
                        cap_mid[lw] += 1
                        lst = mid_loc.setdefault((lw, True), [])
                        if not lst:
                            lst.append(loc_str(doc, p, off))
                    elif word == lw:
                        low_mid[lw] += 1
                        lst = mid_loc.setdefault((lw, False), [])
                        if not lst:
                            lst.append(loc_str(doc, p, off))
                uni[lw] += 1
                if lw not in uni_loc:
                    uni_loc[lw] = loc_str(doc, p, off)
                if prev_tok is not None and prev_end is not None:
                    gap = t[prev_end:off]
                    key = (prev_tok, lw)
                    if gap == "-":
                        hy[key] += 1
                        hy_loc.setdefault(key, loc_str(doc, p, off))
                    elif gap.strip() == "" and gap:
                        openb[key] += 1
                        open_loc.setdefault(key, loc_str(doc, p, off))
                prev_end = m.end()
                prev_tok = lw
    # name variants
    cands = {w: r for w, r in caps.items() if w.lower() not in lower_seen and w.lower() not in stop and r["count"] >= 2}
    if len(cands) > 1500:
        cands = dict(sorted(cands.items(), key=lambda kv: (-kv[1]["count"], kv[0]))[:1500])
    forms = sorted(cands)
    parent = {w: w for w in forms}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    cooccur: Dict[str, int] = {}
    for i, a in enumerate(forms):
        for b in forms[i + 1:]:
            if similar_names(a, b):
                parent[find(a)] = find(b)
                both = len(cands[a]["paras"] & cands[b]["paras"])
                cooccur[a] = max(cooccur.get(a, 0), both)
                cooccur[b] = max(cooccur.get(b, 0), both)
    groups: Dict[str, List[str]] = {}
    for w in forms:
        groups.setdefault(find(w), []).append(w)
    name_variants = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda w: (-cands[w]["count"], w))
        both = max(cooccur.get(w, 0) for w in members)
        name_variants.append({
            "dominant": members[0],
            "variants": [{"form": w, "count": cands[w]["count"], "files": len(cands[w]["files"]), "first": cands[w]["locs"][0]} for w in members],
            "total": sum(cands[w]["count"] for w in members),
            "max_shared_paragraphs": both,
            "likely_distinct_names": both >= 2,
        })
    name_variants.sort(key=lambda g: (g["likely_distinct_names"], -g["total"], g["dominant"]))
    # bible near misses
    bnames = bible_names(root, stop)
    near = []
    bset = set(bnames)
    for w, r in sorted(caps.items()):
        if w in bset or w.lower() in lower_seen or w.lower() in stop or len(w) < 4:
            continue
        for b in bnames:
            if similar_names(w, b):
                near.append({"canonical": b, "variant": w, "count": r["count"], "first": r["locs"][0], "locations": r["locs"]})
                break
    near.sort(key=lambda x: (-x["count"], x["variant"]))
    # hyphenation
    keys = set(hy)
    for (a, b) in openb:
        if a + b in uni and len(a) >= 3 and len(b) >= 3 and (a + b) not in ISOLATED_CLOSED:
            keys.add((a, b))
    hyph = []
    for a, b in sorted(keys):
        h, o, c = hy.get((a, b), 0), openb.get((a, b), 0), uni.get(a + b, 0)
        if (a + b) in ISOLATED_CLOSED:
            continue
        present = [(n, f) for n, f in ((h, "hyphen"), (o, "open"), (c, "closed")) if n > 0]
        if len(present) < 2:
            continue
        item: Dict[str, Any] = {"forms": {}, "counts": {}, "first": {}}
        for n, f in present:
            text = {"hyphen": a + "-" + b, "open": a + " " + b, "closed": a + b}[f]
            item["forms"][f] = text
            item["counts"][f] = n
            item["first"][f] = {"hyphen": hy_loc.get((a, b)), "open": open_loc.get((a, b)), "closed": uni_loc.get(a + b)}[f]
        item["total"] = sum(n for n, _f in present)
        hyph.append(item)
    hyph.sort(key=lambda x: (-x["total"], sorted(x["forms"].values())[0]))
    # capitalization
    capvar = []
    for lw in sorted(set(cap_mid) & set(low_mid)):
        if lw == "i":
            continue
        capvar.append({"term": lw, "capitalized": cap_mid[lw], "lowercase": low_mid[lw],
                       "first_capitalized": mid_loc[(lw, True)][0], "first_lowercase": mid_loc[(lw, False)][0]})
    capvar.sort(key=lambda x: (-min(x["capitalized"], x["lowercase"]), -(x["capitalized"] + x["lowercase"]), x["term"]))
    return {"files": n_files, "name_variants": name_variants, "bible_near_misses": near,
            "hyphenation_variants": hyph, "capitalization_variants": capvar}


# ---------------------------------------------------------------------------------------------------------------
# CLI plumbing

def positive_int(s: str) -> int:
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("not an integer: %r" % s) from None
    if v < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return v


def choose_language(arg_lang: Optional[str], meta: Dict[str, Any], warnings: List[str]) -> WordLists:
    if arg_lang:
        return load_wordlists(arg_lang)
    proj = meta.get("language")
    if isinstance(proj, str) and proj:
        try:
            return load_wordlists(proj)
        except UsageError as exc:
            warnings.append("%s; falling back to en-US" % exc)
    return load_wordlists("en-US")


def parse_checks(raw: Optional[str], allowed: List[str]) -> List[str]:
    if not raw:
        return list(allowed)
    out = []
    for c in raw.split(","):
        c = c.strip()
        if not c:
            continue
        if c not in allowed:
            raise UsageError("unknown check %r; choose from %s" % (c, ", ".join(allowed)))
        if c not in out:
            out.append(c)
    if not out:
        raise UsageError("--checks is empty")
    return out


def dump(obj: Any, pretty: bool = True) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=1 if pretty else None,
                      separators=None if pretty else (",", ":"))


def write_out(path: Optional[str], obj: Any) -> None:
    if not path:
        return
    parent = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(dump(obj) + "\n")
    except OSError as exc:
        raise UsageError("cannot write --out %s: %s" % (path, exc)) from exc


def totals_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    tot: Counter = Counter()
    for r in rows:
        tot.update(r["counts"])
    return dict(sorted(tot.items()))


def cmd_style(a: argparse.Namespace) -> int:
    files, meta = resolve_inputs(a.paths)
    warnings: List[str] = []
    wl = choose_language(a.language, meta, warnings)
    checks = parse_checks(a.checks, STYLE_CHECKS)
    rows = [style_for_doc(Doc(f), wl, checks) for f in files]
    words = sum(r["words"] for r in rows)
    totals = {"files": len(rows), "words": words, "counts": totals_counts(rows)}
    totals["per_1000"] = {c: per_1000(n, words) for c, n in totals["counts"].items()}
    full = {"command": "style", "language": wl.language, "checks": checks, "files": rows, "totals": totals, "warnings": warnings}
    write_out(a.out, full)
    shown = []
    for r in rows:
        r2 = dict(r)
        r2["flags"] = top_flags(r["flags"], a.top)
        shown.append(r2)
    short = dict(full)
    short["files"] = shown
    short["top_per_check"] = a.top
    short["out"] = a.out
    sys.stdout.write(dump(short, False) + "\n")
    return 0


def cmd_mechanics(a: argparse.Namespace) -> int:
    files, meta = resolve_inputs(a.paths)
    warnings: List[str] = []
    wl = choose_language(a.language, meta, warnings)
    checks = parse_checks(a.checks, MECH_CHECKS)
    ignore = set(re.sub(r"\s+", " ", w.strip().lower()) for w in (a.ignore or "").split(",") if w.strip())
    rows = [mech_for_doc(Doc(f), wl, checks, ignore) for f in files]
    words = sum(r["words"] for r in rows)
    totals = {"files": len(rows), "words": words, "counts": totals_counts(rows)}
    full = {"command": "mechanics", "language": wl.language, "checks": checks, "files": rows, "totals": totals, "warnings": warnings}
    write_out(a.out, full)
    shown = []
    for r in rows:
        r2 = dict(r)
        r2["flags"] = top_flags(r["flags"], a.top)
        shown.append(r2)
    short = dict(full)
    short["files"] = shown
    short["top_per_check"] = a.top
    short["out"] = a.out
    sys.stdout.write(dump(short, False) + "\n")
    return 0


def cmd_consistency(a: argparse.Namespace) -> int:
    if not os.path.isdir(a.project):
        raise UsageError("not a directory: %s" % a.project)
    files, meta = project_files(a.project)
    if not files:
        raise UsageError("no chapter files found in %s" % a.project)
    warnings: List[str] = []
    wl = choose_language(a.language, meta, warnings)
    rep = consistency_report(a.project, files, wl, a.top)
    full = {"command": "consistency", "project": a.project, "language": wl.language, "warnings": warnings}
    full.update(rep)
    write_out(a.out, full)
    short = dict(full)
    short["counts"] = {"name_variants": len(rep["name_variants"]), "bible_near_misses": len(rep["bible_near_misses"]),
                       "hyphenation_variants": len(rep["hyphenation_variants"]), "capitalization_variants": len(rep["capitalization_variants"])}
    for k in ("name_variants", "bible_near_misses", "hyphenation_variants", "capitalization_variants"):
        short[k] = rep[k][:a.top]
    short["top"] = a.top
    short["out"] = a.out
    sys.stdout.write(dump(short, False) + "\n")
    return 0


def cmd_readability(a: argparse.Namespace) -> int:
    files, meta = resolve_inputs(a.paths)
    warnings: List[str] = []
    wl = choose_language(a.language, meta, warnings)
    rows = []
    all_words: List[str] = []
    all_sent = 0
    for f in files:
        row, ws, ns = readability_for_doc(Doc(f), wl, a.min_words)
        rows.append(row)
        all_words.extend(ws)
        all_sent += ns
    st = read_stats(all_words, all_sent)
    total = {"files": len(rows), "words": len(all_words), "sentences": all_sent,
             "flesch_reading_ease": round(st["flesch"], 1), "fk_grade": round(st["fk"], 1),
             "avg_words_per_sentence": round(st["wps"], 2), "avg_syllables_per_word": round(st["spw"], 3),
             "pct_long_words": round(st["long"], 1)}
    out = {"command": "readability", "language": wl.language, "long_word_definition": "7 or more letters",
           "min_paragraph_words": a.min_words, "files": rows, "total": total, "warnings": warnings}
    write_out(a.out, out)
    sys.stdout.write(dump(out, False) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="prose_check.py",
        description="Markdown-aware prose checks for fiction: style, mechanics, consistency, readability. "
                    "Input is a file, several files or a project directory. JSON on stdout; exit 0 ok, 2 usage.")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="{style,mechanics,consistency,readability}")

    def common(p: argparse.ArgumentParser, top_default: Optional[int]) -> None:
        p.add_argument("--language", help="word list language (default: manuscript.md language, else en-US)")
        p.add_argument("--out", metavar="FILE", help="write the full JSON result (all flags) to FILE")
        if top_default is not None:
            p.add_argument("--top", type=positive_int, default=top_default, metavar="N",
                           help="flags/items kept on stdout per check per file (default %d); --out keeps all" % top_default)

    p = sub.add_parser("style", help="filter words, weak verbs, adverbs, dialogue tags, intensifiers, cliches, AI tells, "
                       "telling of emotion, purple prose, repetition, rhythm")
    p.add_argument("paths", nargs="+", metavar="PATH")
    p.add_argument("--checks", help="comma list from: " + ",".join(STYLE_CHECKS) + " (default all)")
    common(p, 15)
    p.set_defaults(func=cmd_style)

    p = sub.add_parser("mechanics", help="double spaces, quote/ellipsis/dash style, dialogue punctuation, repeated words, "
                       "British spellings, number style, confused words")
    p.add_argument("paths", nargs="+", metavar="PATH")
    p.add_argument("--checks", help="comma list from: " + ",".join(MECH_CHECKS) + " (default all)")
    p.add_argument("--ignore", metavar="WORDS", help="comma list of British spellings to accept (names, dialect), e.g. grey,towards")
    common(p, 15)
    p.set_defaults(func=cmd_mechanics)

    p = sub.add_parser("consistency", help="name and term variants, hyphenation and capitalization variants across a project")
    p.add_argument("project", metavar="PROJECT_DIR")
    common(p, 30)
    p.set_defaults(func=cmd_consistency)

    p = sub.add_parser("readability", help="Flesch Reading Ease, Flesch-Kincaid grade, sentence and word length, hardest paragraphs")
    p.add_argument("paths", nargs="+", metavar="PATH")
    p.add_argument("--min-words", type=positive_int, default=25, metavar="N", help="shortest paragraph considered for hot spots (default 25)")
    common(p, None)
    p.set_defaults(func=cmd_readability)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except UsageError as exc:
        sys.stderr.write("prose_check.py: error: %s\n" % exc)
        return 2
    except BrokenPipeError:  # reader (e.g. head) closed the pipe early
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0
    except OSError as exc:
        sys.stderr.write("prose_check.py: error: %s\n" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
