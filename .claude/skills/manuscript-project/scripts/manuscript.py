#!/usr/bin/env python3
"""manuscript.py - scaffold, validate, index, measure and restructure a markdown fiction project.

Layout (defaults; manuscript.md front matter may override chapter_dir / chapter_pattern):

    <project>/manuscript.md, chapters/NNN_slug.md, outline.md, bible/, style-sheet.md, reviews/, notes/

Standard library only (Python 3.9+). No network access. JSON on stdout.
Exit codes: 0 ok, 1 check failed (validate found errors), 2 usage or refusal.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_CHAPTER_DIR = "chapters"
DEFAULT_PATTERN = r"^(\d{3})_([a-z0-9][a-z0-9-]*)\.md$"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
START_MARK = "<!-- chapters:start -->"
END_MARK = "<!-- chapters:end -->"
STATUSES = ("outline", "draft", "revised", "final")
WORDS_PER_MINUTE = 250
WORD_RE = re.compile(r"[^\W_]+(?:['\u2019\-][^\W_]+)*")
FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
BREAK_RE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
H1_RE = re.compile(r"^#(?!#)\s+(.*\S)\s*$")
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "jr", "sr", "prof", "gen", "col", "capt", "lt", "sgt", "rev", "hon", "vs", "mt", "ft"}
SENT_BOUNDARY = re.compile(r"[.!?\u2026]+[\"\u201d\u2019')\]]*\s+")


class UsageError(Exception):
    """Bad invocation, bad project configuration or a refused operation (exit 2)."""


class FrontMatterError(ValueError):
    """Front matter that the YAML-subset parser cannot read."""


# ---------------------------------------------------------------------------------------------------------------
# Front matter (YAML subset: key: value, key: [a, b], quoted strings, ints, true/false/null)

def _split_flow_list(inner: str) -> List[str]:
    items: List[str] = []
    cur: List[str] = []
    quote = ""
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(inner):
                cur.append(inner[i + 1])
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == ",":
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    if quote:
        raise FrontMatterError("unterminated quote in list")
    tail = "".join(cur)
    if tail.strip() or items:
        items.append(tail)
    return items


def _quoted(s: str) -> Tuple[str, str]:
    """Parse a leading quoted string; return (value, rest)."""
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
            return "".join(out), s[i + 1:]
        out.append(c)
        i += 1
    raise FrontMatterError("unterminated quoted string")


def parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if s == "":
        return ""
    if s[0] in "\"'":
        val, rest = _quoted(s)
        rest = rest.strip()
        if rest and not rest.startswith("#"):
            raise FrontMatterError("unexpected text after quoted string")
        return val
    if s[0] == "[":
        depth_end = -1
        quote = ""
        for i, ch in enumerate(s):
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch == "]":
                depth_end = i
                break
        if depth_end < 0:
            raise FrontMatterError("unterminated list")
        rest = s[depth_end + 1:].strip()
        if rest and not rest.startswith("#"):
            raise FrontMatterError("unexpected text after list")
        return [parse_scalar(x) for x in _split_flow_list(s[1:depth_end])]
    cut = s.find(" #")
    if cut >= 0:
        s = s[:cut].rstrip()
    if re.fullmatch(r"-?(0|[1-9]\d*)", s):
        return int(s)
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    return s


KEY_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:(?:\s+(.*)|\s*)$")


def parse_front_matter_lines(lines: List[str], first_lineno: int = 2) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    for off, line in enumerate(lines):
        n = first_lineno + off
        line = line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            raise FrontMatterError("line %d: nested or indented values are not supported" % n)
        m = KEY_RE.match(line)
        if not m:
            raise FrontMatterError("line %d: expected 'key: value'" % n)
        key = m.group(1)
        if key in meta:
            raise FrontMatterError("line %d: duplicate key %r" % (n, key))
        try:
            meta[key] = parse_scalar(m.group(2) or "")
        except FrontMatterError as exc:
            raise FrontMatterError("line %d: %s" % (n, exc)) from exc
    return meta


def parse_front_matter(text: str) -> Tuple[Dict[str, Any], str, int]:
    """Return (meta, body, body_first_lineno). No front matter -> ({}, text, 1)."""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r").strip() != "---":
        return {}, text, 1
    for j in range(1, len(lines)):
        if lines[j].rstrip("\r").strip() in ("---", "..."):
            meta = parse_front_matter_lines(lines[1:j], 2)
            return meta, "\n".join(lines[j + 1:]), j + 2
    raise FrontMatterError("front matter opened with '---' on line 1 but never closed")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace", newline=None) as fh:
        return fh.read()


# ---------------------------------------------------------------------------------------------------------------
# Prose helpers (paragraphs, dialogue, sentences)

def prose_paragraphs(body: str) -> List[str]:
    """Paragraph texts of a chapter body: no headings, fenced code, HTML comments or scene-break rules."""
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    paras: List[str] = []
    cur: List[str] = []
    fence = ""
    for line in body.split("\n"):
        stripped = line.strip()
        fm = FENCE_RE.match(line)
        if fence:
            if fm and fm.group(1) == fence:
                fence = ""
            continue
        if fm:
            fence = fm.group(1)
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        if not stripped or HEADING_RE.match(line) or BREAK_RE.match(line):
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        cur.append(stripped)
    if cur:
        paras.append(" ".join(cur))
    return paras


def dialogue_spans(text: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    start = -1
    for i, ch in enumerate(text):
        if start < 0:
            if ch in '"\u201c':
                start = i
        elif ch in '"\u201d':
            spans.append((start, i + 1))
            start = -1
    if start >= 0:
        spans.append((start, len(text)))
    return spans


def count_sentences(text: str) -> int:
    count = 0
    start = 0
    for m in SENT_BOUNDARY.finditer(text):
        nxt = text[m.end():m.end() + 2]
        if not nxt:
            break
        c = nxt[0]
        ok = c.isupper() or c.isdigit() or (c in "\"\u201c\u2018'([" and (nxt[1:2].isupper() or nxt[1:2].isdigit()))
        if not ok:
            continue
        if m.group(0).rstrip().endswith(".") and re.fullmatch(r"\.\s+", m.group(0)):
            w = re.search(r"([A-Za-z]+)$", text[start:m.start()])
            if w and (w.group(1).lower() in ABBREVIATIONS or len(w.group(1)) == 1):
                continue
        if WORD_RE.search(text[start:m.start()]):
            count += 1
        start = m.end()
    if WORD_RE.search(text[start:]):
        count += 1
    return count


def measure_body(body: str) -> Dict[str, Any]:
    paras = prose_paragraphs(body)
    words = dwords = sentences = 0
    for p in paras:
        words += len(WORD_RE.findall(p))
        for s, e in dialogue_spans(p):
            dwords += len(WORD_RE.findall(p[s:e]))
        sentences += count_sentences(p)
    return {
        "words": words,
        "reading_minutes": round(words / float(WORDS_PER_MINUTE), 1),
        "dialogue_words": dwords,
        "dialogue_ratio": round(dwords / float(words), 4) if words else 0.0,
        "sentences": sentences,
        "avg_sentence_words": round(words / float(sentences), 2) if sentences else 0.0,
        "paragraphs": len(paras),
    }


def first_h1(body: str) -> Optional[str]:
    """Title if the first non-blank line (HTML comments ignored) is a level-1 heading."""
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    for line in body.split("\n"):
        if line.strip():
            m = H1_RE.match(line)
            return m.group(1) if m else None
    return None


# ---------------------------------------------------------------------------------------------------------------
# Project model

class Config:
    def __init__(self, root: str) -> None:
        self.root = root
        self.meta: Dict[str, Any] = {}
        self.chapter_dir = DEFAULT_CHAPTER_DIR
        self.pattern_src = DEFAULT_PATTERN
        self.pattern = re.compile(DEFAULT_PATTERN)
        self.problems: List[Tuple[str, str]] = []  # (code, message): fatal configuration errors
        self.has_manuscript = False

    @property
    def chapter_path(self) -> str:
        return os.path.join(self.root, self.chapter_dir)

    def rel(self, filename: str) -> str:
        return (self.chapter_dir.rstrip("/") + "/" + filename).replace(os.sep, "/")


def load_config(root: str) -> Config:
    if not os.path.isdir(root):
        raise UsageError("not a directory: %s" % root)
    cfg = Config(root)
    mpath = os.path.join(root, "manuscript.md")
    if os.path.isfile(mpath):
        cfg.has_manuscript = True
        try:
            meta, _body, _ln = parse_front_matter(read_text(mpath))
            cfg.meta = meta
        except FrontMatterError as exc:
            cfg.problems.append(("bad_front_matter", "manuscript.md: %s" % exc))
    cd = cfg.meta.get("chapter_dir", DEFAULT_CHAPTER_DIR)
    if not isinstance(cd, str) or not cd.strip():
        cfg.problems.append(("bad_config", "chapter_dir must be a non-empty string"))
    else:
        cd = cd.strip().rstrip("/")
        parts = cd.replace("\\", "/").split("/")
        if os.path.isabs(cd) or ".." in parts or cd in ("", "."):
            cfg.problems.append(("bad_config", "chapter_dir must be a relative path inside the project (got %r)" % cd))
        else:
            cfg.chapter_dir = cd
    pat = cfg.meta.get("chapter_pattern", DEFAULT_PATTERN)
    if not isinstance(pat, str):
        cfg.problems.append(("bad_config", "chapter_pattern must be a string"))
    else:
        try:
            rx = re.compile(pat)
            if rx.groups != 2:
                cfg.problems.append(("bad_config", "chapter_pattern needs exactly 2 groups (number, slug); it has %d" % rx.groups))
            else:
                cfg.pattern_src = pat
                cfg.pattern = rx
        except re.error as exc:
            cfg.problems.append(("bad_config", "chapter_pattern is not a valid regex: %s" % exc))
    return cfg


def strict_config(root: str) -> Config:
    cfg = load_config(root)
    if cfg.problems:
        raise UsageError("; ".join(m for _c, m in cfg.problems) + " (run: manuscript.py validate)")
    return cfg


class Chapter:
    def __init__(self, cfg: Config, filename: str, m: "re.Match[str]") -> None:
        self.filename = filename
        self.num_str = m.group(1)
        self.slug = m.group(2)
        try:
            self.number = int(self.num_str)
        except ValueError:
            raise UsageError("chapter_pattern group 1 must capture digits (file %s)" % filename) from None
        self.num_span = (m.start(1), m.end(1))
        self.slug_span = (m.start(2), m.end(2))
        self.path = os.path.join(cfg.chapter_path, filename)
        self.rel = cfg.rel(filename)


def scan_chapters(cfg: Config) -> Tuple[List[Chapter], List[Dict[str, str]], List[Dict[str, str]]]:
    """Return (chapters, errors, warnings) found in chapter_dir."""
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    chapters: List[Chapter] = []
    if not os.path.isdir(cfg.chapter_path):
        return chapters, errors, warnings
    for name in sorted(os.listdir(cfg.chapter_path)):
        if name.startswith("."):
            continue
        full = os.path.join(cfg.chapter_path, name)
        rel = cfg.rel(name)
        if os.path.isdir(full):
            warnings.append({"code": "directory_in_chapter_dir", "file": rel, "message": "directory inside chapter_dir (reviews and notes belong beside it, not inside)"})
            continue
        m = cfg.pattern.match(name)
        if m:
            chapters.append(Chapter(cfg, name, m))
        elif name.lower().endswith(".md"):
            errors.append({"code": "bad_name", "file": rel, "message": "does not match chapter_pattern %s" % cfg.pattern_src})
        else:
            warnings.append({"code": "non_chapter_file", "file": rel, "message": "non-markdown file inside chapter_dir"})
    chapters.sort(key=lambda c: (c.number, c.filename))
    return chapters, errors, warnings


def read_chapter(ch: Chapter) -> Tuple[Dict[str, Any], str]:
    try:
        meta, body, _ln = parse_front_matter(read_text(ch.path))
    except FrontMatterError as exc:
        raise UsageError("%s: %s" % (ch.rel, exc)) from exc
    return meta, body


def pad_width(chapters: List[Chapter]) -> int:
    padded = [len(c.num_str) for c in chapters if len(c.num_str) > 1 and c.num_str[0] == "0"]
    if padded:
        return max(padded)
    return 1 if chapters else 3


def swap_number(ch: Chapter, new_number: int, width: int) -> str:
    s, e = ch.num_span
    return ch.filename[:s] + str(new_number).zfill(width) + ch.filename[e:]


class Namer:
    """Builds new filenames from the naming scheme of an existing chapter (or the default)."""

    def __init__(self, chapters: List[Chapter]) -> None:
        self.width = pad_width(chapters)
        if chapters:
            c = chapters[0]
            spans = sorted([("num", c.num_span), ("slug", c.slug_span)], key=lambda t: t[1][0])
            parts: List[Tuple[str, str]] = []
            pos = 0
            for kind, (s, e) in spans:
                parts.append(("lit", c.filename[pos:s]))
                parts.append((kind, ""))
                pos = e
            parts.append(("lit", c.filename[pos:]))
            self.parts = parts
        else:
            self.parts = [("num", ""), ("lit", "_"), ("slug", ""), ("lit", ".md")]

    def render(self, number: int, slug: str) -> str:
        out = []
        for kind, lit in self.parts:
            if kind == "lit":
                out.append(lit)
            elif kind == "num":
                out.append(str(number).zfill(self.width))
            else:
                out.append(slug)
        return "".join(out)


def title_of(ch: Chapter, body: str) -> str:
    return first_h1(body) or ch.slug


def index_data(cfg: Config) -> Dict[str, Any]:
    chapters, _e, _w = scan_chapters(cfg)
    entries: List[Dict[str, Any]] = []
    by_status: Dict[str, int] = {}
    total = 0
    for ch in chapters:
        meta, body = read_chapter(ch)
        words = measure_body(body)["words"]
        status = meta.get("status") if isinstance(meta.get("status"), str) else ""
        pov = meta.get("pov") if isinstance(meta.get("pov"), str) else ""
        entries.append({
            "number": ch.number, "slug": ch.slug, "file": ch.rel, "title": title_of(ch, body),
            "words": words, "status": status, "pov": pov,
        })
        total += words
        key = status or "unset"
        by_status[key] = by_status.get(key, 0) + 1
    return {"chapters": entries, "totals": {"chapters": len(entries), "words": total, "by_status": by_status}}


def render_block(entries: List[Dict[str, Any]]) -> str:
    lines = []
    for e in entries:
        bits = ["- %s [%s](%s) - %s words" % (str(e["number"]).zfill(3), e["title"], e["file"], format(e["words"], ","))]
        if e.get("status"):
            bits.append(e["status"])
        lines.append(" - ".join(bits))
    return START_MARK + "\n" + ("\n".join(lines) + "\n" if lines else "") + END_MARK


def atomic_write(path: str, text: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".manuscript-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def emit(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------------------------------------------
# init

def yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    needs = (s == "" or s != s.strip() or s[0] in "[]{}&*!|>'\"%@`#-?:," or ": " in s or " #" in s or "\n" in s
             or re.fullmatch(r"-?\d+", s) or s.lower() in ("true", "false", "null", "~"))
    if needs:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'
    return s


def write_new(path: str, content: str, root: str, created: List[str], skipped: List[str]) -> None:
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        created.append(rel)
    except FileExistsError:
        skipped.append(rel)


def cmd_init(a: argparse.Namespace) -> int:
    root = a.dir
    if os.path.exists(root) and not os.path.isdir(root):
        raise UsageError("%s exists and is not a directory" % root)
    if a.chapters < 0 or a.chapters > 999:
        raise UsageError("--chapters must be between 0 and 999")
    created: List[str] = []
    skipped: List[str] = []
    dirs_created: List[str] = []
    for sub in ("", DEFAULT_CHAPTER_DIR, "bible", "reviews", "notes"):
        d = os.path.join(root, sub) if sub else root
        if not os.path.isdir(d):
            os.makedirs(d)
            dirs_created.append(sub or ".")
    cfg = Config(root)
    existing, _e, _w = scan_chapters(cfg)
    taken = {c.number for c in existing}
    planned: List[Tuple[int, str, str]] = []  # number, slug, title
    if a.start == 0:
        planned.append((0, "prologue", "Prologue"))
    for i in range(1, a.chapters + 1):
        planned.append((i, "chapter-%d" % i, "Chapter %d" % i))
    for num, slug, title in planned:
        path = os.path.join(cfg.chapter_path, "%03d_%s.md" % (num, slug))
        if num in taken and not os.path.exists(path):
            skipped.append(cfg.rel(os.path.basename(path)))
            continue
        write_new(path, "---\nstatus: outline\n---\n# %s\n\n" % title, root, created, skipped)

    fm = ["title: " + yaml_scalar(a.title)]
    if a.author:
        fm.append("author: " + yaml_scalar(a.author))
    fm.append("language: " + yaml_scalar(a.language))
    if a.pov:
        fm.append("pov: " + yaml_scalar(a.pov))
    if a.tense:
        fm.append("tense: " + yaml_scalar(a.tense))
    if a.genre:
        fm.append("genre: " + yaml_scalar(a.genre))
    if a.target_words is not None:
        fm.append("target_words: %d" % a.target_words)
    fm.append("chapter_dir: " + DEFAULT_CHAPTER_DIR)
    fm.append("chapter_pattern: '" + DEFAULT_PATTERN + "'")
    chapters_now, _e2, _w2 = scan_chapters(cfg)
    entries = []
    for ch in chapters_now:
        meta, body = read_chapter(ch)
        entries.append({"number": ch.number, "title": title_of(ch, body), "file": ch.rel, "words": measure_body(body)["words"],
                        "status": meta.get("status") if isinstance(meta.get("status"), str) else ""})
    manuscript = ("---\n" + "\n".join(fm) + "\n---\n# " + a.title + "\n\n## Logline\n\n"
                  "(One sentence: protagonist, goal, obstacle, stakes.)\n\n## Synopsis\n\n(One page.)\n\n"
                  "## Chapters\n\n" + render_block(entries) + "\n")
    write_new(os.path.join(root, "manuscript.md"), manuscript, root, created, skipped)
    write_new(os.path.join(root, "outline.md"), "# Outline\n\n" + "".join(
        "## %03d %s\n\n- Goal:\n- Conflict:\n- Outcome:\n\n" % (n, t) for n, _s, t in planned), root, created, skipped)
    write_new(os.path.join(root, "bible", "characters.md"), "# Characters\n\n## Name\n\n- Role:\n- Wants:\n- Voice:\n", root, created, skipped)
    write_new(os.path.join(root, "bible", "places.md"), "# Places\n\n## Place\n\n- Description:\n", root, created, skipped)
    write_new(os.path.join(root, "bible", "timeline.md"), "# Timeline\n\n- Day 1:\n", root, created, skipped)
    write_new(os.path.join(root, "bible", "glossary.md"), "# Glossary\n\nNames, invented terms and their spellings.\n\n- **Term**: definition\n", root, created, skipped)
    write_new(os.path.join(root, "style-sheet.md"), "# Style sheet\n\n- Spelling: %s\n- Numbers: spell out zero through one hundred and round numbers\n"
              "- Quotes: double for dialogue, single inside\n- Dashes: closed em dash\n- Ellipsis: ...\n\n## Name spellings\n\n## Banned phrases\n" % a.language,
              root, created, skipped)
    for keep in ("reviews", "notes"):
        write_new(os.path.join(root, keep, ".gitkeep"), "", root, created, skipped)
    emit({"command": "init", "dir": root, "created": sorted(created), "skipped": sorted(skipped), "directories_created": sorted(dirs_created)})
    return 0


# ---------------------------------------------------------------------------------------------------------------
# validate

def cmd_validate(a: argparse.Namespace) -> int:
    cfg = load_config(a.dir)
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    if not cfg.has_manuscript:
        errors.append({"code": "missing_manuscript", "file": "manuscript.md", "message": "manuscript.md not found"})
    for code, msg in cfg.problems:
        errors.append({"code": code, "file": "manuscript.md", "message": msg})
    chapters: List[Chapter] = []
    if not os.path.isdir(cfg.chapter_path):
        errors.append({"code": "missing_chapter_dir", "file": cfg.chapter_dir, "message": "chapter_dir %r does not exist" % cfg.chapter_dir})
    else:
        chapters, e2, w2 = scan_chapters(cfg)
        errors += e2
        warnings += w2
    seen: Dict[int, List[Chapter]] = {}
    for ch in chapters:
        seen.setdefault(ch.number, []).append(ch)
    for num, group in sorted(seen.items()):
        if len(group) > 1:
            for ch in group:
                errors.append({"code": "duplicate_number", "file": ch.rel, "message": "chapter number %d is used by %d files: %s"
                               % (num, len(group), ", ".join(g.filename for g in group))})
    for ch in chapters:
        try:
            meta, body, _ln = parse_front_matter(read_text(ch.path))
        except FrontMatterError as exc:
            errors.append({"code": "bad_chapter_front_matter", "file": ch.rel, "message": str(exc)})
            continue
        if first_h1(body) is None:
            warnings.append({"code": "missing_h1", "file": ch.rel, "message": "first line after front matter is not '# <Title>'"})
        status = meta.get("status")
        if status is not None and status not in STATUSES:
            warnings.append({"code": "bad_status", "file": ch.rel, "message": "status %r is not one of %s" % (status, "|".join(STATUSES))})
    nums = sorted(seen)
    for prev, nxt in zip(nums, nums[1:]):  # noqa: B905 (strict= needs 3.10; lengths differ by design)
        if nxt - prev > 1:
            missing = list(range(prev + 1, nxt))
            warnings.append({"code": "numbering_gap", "file": cfg.chapter_dir,
                             "message": "no chapter %s between %d and %d (renumber if unintended)" % (
                                 ", ".join(str(m) for m in missing[:10]) + (" ..." if len(missing) > 10 else ""), prev, nxt)})
    key = lambda d: (d["code"], d["file"], d["message"])  # noqa: E731
    errors.sort(key=key)
    warnings.sort(key=key)
    emit({"command": "validate", "dir": a.dir, "ok": not errors, "chapters": len(chapters), "errors": errors, "warnings": warnings})
    return 1 if errors else 0


# ---------------------------------------------------------------------------------------------------------------
# index / stats

def cmd_index(a: argparse.Namespace) -> int:
    cfg = strict_config(a.dir)
    data = index_data(cfg)
    out: Dict[str, Any] = {"command": "index", "dir": a.dir}
    out.update(data)
    if a.write:
        mpath = os.path.join(cfg.root, "manuscript.md")
        if not os.path.isfile(mpath):
            raise UsageError("manuscript.md not found; run init or create it with the markers %s ... %s" % (START_MARK, END_MARK))
        with open(mpath, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
        if text.count(START_MARK) != 1 or text.count(END_MARK) != 1:
            raise UsageError("manuscript.md must contain exactly one %s and one %s" % (START_MARK, END_MARK))
        s = text.index(START_MARK)
        e = text.index(END_MARK)
        if e < s:
            raise UsageError("%s comes before %s in manuscript.md" % (END_MARK, START_MARK))
        nl = "\r\n" if "\r\n" in text else "\n"
        block = render_block(data["chapters"]).replace("\n", nl)
        new_text = text[:s] + block + text[e + len(END_MARK):]
        changed = new_text != text
        if changed:
            atomic_write(mpath, new_text)
        out["written"] = True
        out["changed"] = changed
        out["file"] = "manuscript.md"
    else:
        out["written"] = False
    emit(out)
    return 0


def cmd_stats(a: argparse.Namespace) -> int:
    cfg = strict_config(a.dir)
    chapters, _e, _w = scan_chapters(cfg)
    if a.chapter is not None:
        want = parse_number(a.chapter)
        chapters = [c for c in chapters if c.number == want]
        if not chapters:
            raise UsageError("no chapter numbered %s" % a.chapter)
    rows = []
    tot = {"words": 0, "dialogue_words": 0, "sentences": 0, "paragraphs": 0}
    for ch in chapters:
        meta, body = read_chapter(ch)
        m = measure_body(body)
        row = {"number": ch.number, "slug": ch.slug, "file": ch.rel, "status": meta.get("status") if isinstance(meta.get("status"), str) else ""}
        row.update(m)
        rows.append(row)
        for k in tot:
            tot[k] += m[k]
    words = tot["words"]
    totals: Dict[str, Any] = dict(tot)
    totals.update({
        "chapters": len(rows),
        "reading_minutes": round(words / float(WORDS_PER_MINUTE), 1),
        "dialogue_ratio": round(tot["dialogue_words"] / float(words), 4) if words else 0.0,
        "avg_sentence_words": round(words / float(tot["sentences"]), 2) if tot["sentences"] else 0.0,
        "avg_chapter_words": round(words / float(len(rows)), 1) if rows else 0.0,
    })
    target = cfg.meta.get("target_words")
    if isinstance(target, int) and target > 0 and a.chapter is None:
        totals["target_words"] = target
        totals["pct_of_target"] = round(100.0 * words / target, 1)
    emit({"command": "stats", "dir": a.dir, "chapters": rows, "totals": totals})
    return 0


def parse_number(s: str) -> int:
    try:
        return int(str(s).strip())
    except ValueError:
        raise UsageError("not a chapter number: %r" % s) from None


# ---------------------------------------------------------------------------------------------------------------
# new / renumber / concat

def cmd_new(a: argparse.Namespace) -> int:
    cfg = strict_config(a.dir)
    if not SLUG_RE.match(a.slug):
        raise UsageError("invalid slug %r: use lowercase letters, digits and hyphens, starting with a letter or digit" % a.slug)
    chapters, _e, _w = scan_chapters(cfg)
    nums = [c.number for c in chapters]
    if len(set(nums)) != len(nums):
        raise UsageError("duplicate chapter numbers exist; run validate and renumber first")
    os.makedirs(cfg.chapter_path, exist_ok=True)
    namer = Namer(chapters)
    shifts: List[Chapter] = []
    if a.after is None:
        number = (max(nums) + 1) if nums else 1
    else:
        number = parse_number(a.after) + 1
        if number < 0:
            raise UsageError("--after must be >= -1")
        shifts = [c for c in chapters if c.number >= number]
    plan = []
    moving = {c.path for c in shifts}
    for ch in sorted(shifts, key=lambda c: c.number, reverse=True):
        dst = os.path.join(cfg.chapter_path, swap_number(ch, ch.number + 1, namer.width))
        if os.path.lexists(dst) and dst not in moving:
            raise UsageError("cannot shift %s: %s already exists" % (ch.rel, os.path.basename(dst)))
        plan.append((ch, dst))
    new_name = namer.render(number, a.slug)
    new_path = os.path.join(cfg.chapter_path, new_name)
    if os.path.lexists(new_path) and new_path not in moving:
        raise UsageError("%s already exists" % cfg.rel(new_name))
    shifted = []
    for ch, dst in plan:  # highest number first: every target is free by then
        os.rename(ch.path, dst)
        shifted.append({"from": ch.rel, "to": cfg.rel(os.path.basename(dst))})
    title = a.title or " ".join(w.capitalize() for w in a.slug.split("-"))
    try:
        with open(new_path, "x", encoding="utf-8", newline="\n") as fh:
            fh.write("---\nstatus: outline\n---\n# %s\n\n" % title)
    except FileExistsError:
        raise UsageError("%s already exists" % cfg.rel(new_name)) from None
    emit({"command": "new", "created": cfg.rel(new_name), "number": number, "shifted": shifted})
    return 0


def cmd_renumber(a: argparse.Namespace) -> int:
    cfg = strict_config(a.dir)
    chapters, _e, _w = scan_chapters(cfg)
    if a.start is not None:
        start = a.start
    else:
        start = 0 if chapters and chapters[0].number == 0 else 1
    width = pad_width(chapters) if chapters else 3
    mapping = []
    for i, ch in enumerate(chapters):
        new_no = start + i
        new_name = swap_number(ch, new_no, width)
        if new_name != ch.filename:
            mapping.append((ch, new_no, new_name))
    moving = {c.path for c, _n, _f in mapping}
    for ch, _no, new_name in mapping:
        dst = os.path.join(cfg.chapter_path, new_name)
        if os.path.lexists(dst) and dst not in moving:
            raise UsageError("cannot rename %s to %s: target exists" % (ch.rel, new_name))
    out_map = [{"from": ch.rel, "to": cfg.rel(nf), "number_from": ch.number, "number_to": no} for ch, no, nf in mapping]
    if a.apply and mapping:
        tmpdir = tempfile.mkdtemp(prefix=".renumber-", dir=cfg.chapter_path)
        try:
            staged = []
            for i, (ch, _no, nf) in enumerate(mapping):
                tmp = os.path.join(tmpdir, "%06d" % i)
                os.rename(ch.path, tmp)
                staged.append((tmp, os.path.join(cfg.chapter_path, nf)))
            for tmp, dst in staged:
                os.rename(tmp, dst)
        finally:
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass
    emit({"command": "renumber", "applied": bool(a.apply), "start": start, "mapping": out_map, "unchanged": len(chapters) - len(mapping)})
    return 0


def inside(path: str, directory: str) -> bool:
    p = os.path.realpath(path)
    d = os.path.realpath(directory)
    try:
        return os.path.commonpath([p, d]) == d
    except ValueError:
        return False


def cmd_concat(a: argparse.Namespace) -> int:
    cfg = strict_config(a.dir)
    out_path = a.out
    if inside(out_path, cfg.chapter_path):
        raise UsageError("refusing to write %s inside chapter_dir (%s)" % (out_path, cfg.chapter_dir))
    if os.path.isdir(out_path):
        raise UsageError("--out is a directory: %s" % out_path)
    if os.path.realpath(out_path) == os.path.realpath(os.path.join(cfg.root, "manuscript.md")):
        raise UsageError("refusing to overwrite manuscript.md")
    chapters, _e, _w = scan_chapters(cfg)
    texts = []
    words = 0
    for ch in chapters:
        _meta, body = read_chapter(ch)
        texts.append(body.strip("\n"))
        words += measure_body(body)["words"]
    data = "\n\n".join(texts) + ("\n" if texts else "")
    parent = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(parent, exist_ok=True)
    atomic_write(out_path, data)
    emit({"command": "concat", "out": out_path, "chapters": len(chapters), "words": words, "bytes": len(data.encode("utf-8"))})
    return 0


# ---------------------------------------------------------------------------------------------------------------
# CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="manuscript.py",
        description="Scaffold, validate, index, measure and restructure a markdown fiction project. JSON on stdout; "
                    "exit 0 ok, 1 validate found errors, 2 usage or refusal.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="{init,validate,index,stats,new,renumber,concat}")

    p = sub.add_parser("init", help="create the project layout; never overwrites existing files", description="Create the project layout in DIR. Existing files are never overwritten; they are listed under 'skipped'.")
    p.add_argument("dir")
    p.add_argument("--title", required=True)
    p.add_argument("--author")
    p.add_argument("--language", default="en-US")
    p.add_argument("--chapters", type=int, default=3, metavar="N", help="number of numbered chapters to create (default 3)")
    p.add_argument("--pov")
    p.add_argument("--tense")
    p.add_argument("--genre")
    p.add_argument("--target-words", type=int, dest="target_words", metavar="N")
    p.add_argument("--start", type=int, choices=(0, 1), default=1, help="1: chapters 001... (default); 0: also create 000_prologue.md")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("validate", help="check manuscript.md, chapter names, numbering and headings (exit 1 on errors)")
    p.add_argument("dir")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("index", help="list chapters with words, status, POV; --write refreshes the marker block in manuscript.md")
    p.add_argument("dir")
    p.add_argument("--write", action="store_true", help="rewrite ONLY the block between %s and %s in manuscript.md" % (START_MARK, END_MARK))
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("stats", help="words, reading time, dialogue ratio, sentences and paragraphs per chapter")
    p.add_argument("dir")
    p.add_argument("--chapter", metavar="NNN", help="only this chapter number")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("new", help="create a chapter (next number, or after NNN shifting later chapters up by one)")
    p.add_argument("dir")
    p.add_argument("--slug", required=True)
    p.add_argument("--title")
    p.add_argument("--after", metavar="NNN", help="insert after chapter NNN; later chapters are renamed highest first")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("renumber", help="make numbering contiguous in current order (dry run unless --apply)")
    p.add_argument("dir")
    p.add_argument("--apply", action="store_true", help="perform the renames (via a temporary directory, no collisions)")
    p.add_argument("--start", type=int, choices=(0, 1), help="first number (default: 0 if the first chapter is numbered 0, else 1)")
    p.set_defaults(func=cmd_renumber)

    p = sub.add_parser("concat", help="write the whole manuscript (front matter stripped, H1s kept) to --out")
    p.add_argument("dir")
    p.add_argument("--out", required=True, metavar="FILE", help="output file; refused when inside chapter_dir")
    p.set_defaults(func=cmd_concat)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except UsageError as exc:
        sys.stderr.write("manuscript.py: error: %s\n" % exc)
        return 2
    except BrokenPipeError:  # reader (e.g. head) closed the pipe early
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0
    except OSError as exc:
        sys.stderr.write("manuscript.py: error: %s\n" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
