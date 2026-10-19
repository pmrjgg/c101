"""Parser for ~/.claude/stack.env mirroring bin/mcp-run (KEY=VALUE, never executed).

Accepts an optional ``export `` prefix, matching single or double quotes, and
strips an inline `` # comment`` from unquoted values.  Only key *names* and
whether a value is non-empty are ever reported by the stack's tooling.
"""
from __future__ import annotations

import os
import re
from typing import Dict, Optional

from . import paths

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def env_path() -> str:
    return os.environ.get("CLAUDE_STACK_ENV") or os.path.join(paths.HOME_CLAUDE, "stack.env")


def parse(path: Optional[str] = None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(path or env_path(), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.lstrip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        if not _KEY.match(key):
            continue
        m = re.match(r'^"(.*)"$', val) or re.match(r"^'(.*)'$", val)
        if m:
            val = m.group(1)
        else:
            val = re.split(r"\s#", val, maxsplit=1)[0].strip()
        out[key] = val
    return out


def missing(names) -> list:
    have = {k for k, v in parse().items() if v}
    return [k for k in names if k not in have]
