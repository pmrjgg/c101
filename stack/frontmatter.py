"""Minimal, lossless YAML-frontmatter reader/editor for agent and skill files.

Agent/skill frontmatter in this stack uses only flat ``key: value`` pairs, plus
optional block lists (``key:`` followed by ``  - item`` lines) and one-line JSON flow
lists of objects (inline ``mcpServers`` definitions; JSON is valid YAML flow syntax).  We do not need
a YAML library: we parse exactly that subset and, when editing, replace only
the lines of the keys being changed so comments, ordering and the body are
preserved byte for byte.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Dict, List, Optional, Tuple, Union

Value = Union[str, List[Union[str, dict]]]

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*))?$")


class FrontmatterError(ValueError):
    pass


def split(text: str) -> Tuple[List[str], str]:
    """Return (frontmatter lines without the --- fences, body text)."""
    if not text.startswith("---"):
        raise FrontmatterError("file does not start with a '---' frontmatter fence")
    lines = text.split("\n")
    if lines[0].strip() != "---":
        raise FrontmatterError("first line must be exactly '---'")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:])
    raise FrontmatterError("unterminated frontmatter (no closing '---')")


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        return inner.replace('\\"', '"') if v[0] == '"' else inner.replace("''", "'")
    return v


def _parse_inline_list(v: str) -> Optional[List[Union[str, dict]]]:
    v = v.strip()
    if v.startswith("[") and v.endswith("]") and "{" in v:
        try:
            return json.loads(v)  # inline server definitions: [{"name": {...}}, "built-in"]
        except ValueError:
            pass
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_unquote(x) for x in inner.split(",") if x.strip()] if inner else []
    return None


def parse(text: str) -> Dict[str, Value]:
    fm, _ = split(text)
    out: Dict[str, Value] = {}
    key: Optional[str] = None
    for raw in fm:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = _KEY_RE.match(raw)
        if m and not raw.startswith((" ", "\t")):
            key, val = m.group(1), (m.group(2) or "")
            lst = _parse_inline_list(val)
            if lst is not None:
                out[key] = lst
            elif val.strip() in ("", "|", ">", "|-", ">-"):
                out[key] = [] if val.strip() == "" else ""
            else:
                out[key] = _unquote(val)
            continue
        if key is None:
            continue
        s = raw.strip()
        cur = out.get(key)
        if s.startswith("- ") and isinstance(cur, list):
            cur.append(_unquote(s[2:]))
        elif isinstance(cur, str):  # folded/literal block scalar continuation
            out[key] = (cur + " " + s).strip()
        elif isinstance(cur, list) and not cur:
            # 'key:' followed by an indented mapping (e.g. hooks, mcpServers objects)
            out[key] = s
    return out


def read(path: str) -> Dict[str, Value]:
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read())


def _format_scalar(v: str) -> str:
    if v == "" or re.search(r"[:#\[\]{},&*!|>'\"%@`]", v) or v != v.strip():
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def _format_value(v) -> str:
    if isinstance(v, (list, tuple)) and any(isinstance(x, dict) for x in v):
        return json.dumps(list(v), separators=(", ", ": "))
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_format_scalar(str(x)) for x in v) + "]"
    return _format_scalar(str(v))


def set_keys(text: str, updates: Dict[str, Optional[Union[str, List[str]]]]) -> str:
    """Set (or delete, with value None) keys, preserving everything else.

    Scalars are written as ``key: value``; lists as an inline ``key: [a, b]``.
    """
    fm, body = split(text)
    fm = list(fm)
    for key, val in updates.items():
        idx = None
        for i, raw in enumerate(fm):
            m = _KEY_RE.match(raw)
            if m and m.group(1) == key and not raw.startswith((" ", "\t")):
                idx = i
                break
        if idx is not None:
            # Remove continuation lines belonging to the old value.
            end = idx + 1
            while end < len(fm) and (fm[end].startswith((" ", "\t")) or not fm[end].strip()):
                if not fm[end].strip():
                    break
                end += 1
            if val is None:
                del fm[idx:end]
            else:
                fm[idx:end] = ["%s: %s" % (key, _format_value(val))]
        elif val is not None:
            fm.append("%s: %s" % (key, _format_value(val)))
    return "---\n" + "\n".join(fm) + "\n---\n" + body


def write_atomic(path: str, text: str) -> None:
    real = os.path.realpath(path)  # edit the symlink target, keep the link
    d = os.path.dirname(real)
    fd, tmp = tempfile.mkstemp(prefix=".fm-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            os.chmod(tmp, os.stat(real).st_mode & 0o777)
        except OSError:
            pass
        os.replace(tmp, real)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def update_file(path: str, updates: Dict[str, Optional[Union[str, List[str]]]]) -> bool:
    """Apply updates; return True if the file changed."""
    with open(path, encoding="utf-8") as fh:
        old = fh.read()
    new = set_keys(old, updates)
    if new == old:
        return False
    write_atomic(path, new)
    return True
