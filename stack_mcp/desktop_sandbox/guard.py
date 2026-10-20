"""Input guards: every tool argument is validated here before it reaches xdotool or the container CLI.

- Typed text: secrets (private keys, provider API keys and tokens, JWTs, card numbers that pass Luhn,
  long high-entropy tokens) are refused, so an agent cannot be talked into typing one.
- Keys: xdotool keysym grammar only (``ctrl+shift+t``, ``Return``), never anything option-like.
- Coordinates and regions: inside the virtual screen.
- Files copied in: under the project directory, regular files, not secret-looking, size-capped.
- Commands launched inside the sandbox: an argv list (no shell), bounded.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from pathlib import Path

MAX_TEXT = 4000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_ARGS = 32
MAX_ARG_CHARS = 1000
MODIFIERS = ("ctrl", "shift", "alt", "super", "meta")
BUTTONS = {"left": 1, "middle": 2, "right": 3}
SCROLL_BUTTONS = {"up": 4, "down": 5, "left": 6, "right": 7}

_KEYSYM = re.compile(r"^[A-Za-z0-9_]{1,32}$")
_EXCHANGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Anthropic/OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("Stripe key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}")),
)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_TOKEN = re.compile(r"[A-Za-z0-9+/=_-]{32,}")

# Source paths that are never copied into the sandbox, whatever the brief says.
SECRET_PATH_PARTS = {".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".netrc", ".git-credentials",
                     "Keychains", ".password-store", ".config"}
# Project trees never copied in: git internals (remotes, hooks, credentials helpers), the stack's runtime state
# (transcript-derived output, other sandboxes' exchange directories, which the container can rewrite), and
# Claude Code settings.
DENIED_TOP_DIRS = {".git", ".stack", ".claude"}
SECRET_NAMES = re.compile(r"(^|/)(\.env(\..*)?|stack\.env|.*\.pem|.*\.key|.*\.p12|.*\.pfx|id_[a-z0-9]+|"
                          r"credentials(\.json)?|secrets?(\.[a-z0-9]+)?|tokens?(\.[a-z0-9]+)?|\.npmrc|\.pypirc|"
                          r"\.yarnrc(\.yml)?|\.htpasswd|.*\.tfstate(\.backup)?|.*\.tfvars|.*\.kdbx|"
                          r"settings\.local\.json|service-account.*\.json)$", re.IGNORECASE)


class GuardError(ValueError):
    """An argument was refused; the message says why and what to do instead."""


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _entropy(s: str) -> float:
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def secret_kind(text: str) -> str | None:
    """Name of the first secret-like thing in ``text`` (None when clean)."""
    for kind, pat in SECRET_PATTERNS:
        if pat.search(text):
            return kind
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return "payment card number"
    for m in _TOKEN.finditer(text):
        tok = m.group(0)
        classes = sum(bool(re.search(p, tok)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
        if classes == 3 and _entropy(tok) >= 4.2:
            return "high-entropy token"
    return None


def text(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise GuardError("text must be a non-empty string")
    if len(value) > MAX_TEXT:
        raise GuardError(f"text is {len(value)} chars; type at most {MAX_TEXT} per call")
    if "\x00" in value:
        raise GuardError("text contains a NUL byte")
    kind = secret_kind(value)
    if kind:
        raise GuardError(f"refused: the text looks like a {kind}. Secrets are never typed into the sandbox; "
                         "if the task needs one, stop and return it to the user as an Open doubt")
    return value


def keys(combo: str) -> str:
    """``ctrl+shift+t`` / ``Return`` / ``alt+F4`` -> xdotool form; anything else is refused."""
    if not isinstance(combo, str) or not combo.strip():
        raise GuardError("keys must be a non-empty string like 'ctrl+s' or 'Return'")
    parts = [p for p in combo.strip().split("+")]
    if any(not p for p in parts) or len(parts) > 5:
        raise GuardError(f"malformed key combo {combo!r}")
    out = []
    for p in parts[:-1]:
        low = p.lower()
        if low == "cmd":
            low = "super"
        if low not in MODIFIERS:
            raise GuardError(f"{p!r} is not a modifier ({', '.join(MODIFIERS)})")
        out.append(low)
    last = parts[-1]
    if not _KEYSYM.match(last):
        raise GuardError(f"{last!r} is not an X keysym (letters, digits, underscore; e.g. Return, Tab, F5, a)")
    out.append(last)
    return "+".join(out)


def point(x: int, y: int, width: int, height: int) -> tuple[int, int]:
    if not (isinstance(x, int) and isinstance(y, int)):
        raise GuardError("x and y must be integers")
    if not (0 <= x < width and 0 <= y < height):
        raise GuardError(f"({x}, {y}) is outside the {width}x{height} screen; use coordinates from the "
                         "latest screenshot")
    return x, y


def region(x: int, y: int, w: int, h: int, width: int, height: int) -> tuple[int, int, int, int]:
    point(x, y, width, height)
    if not (isinstance(w, int) and isinstance(h, int)) or w < 8 or h < 8:
        raise GuardError("region width and height must be integers of at least 8 px")
    return x, y, min(w, width - x), min(h, height - y)


def bounded(name: str, value: int, lo: int, hi: int) -> int:
    if not isinstance(value, int) or not lo <= value <= hi:
        raise GuardError(f"{name} must be an integer in [{lo}, {hi}]")
    return value


def choice(name: str, value: str, table: dict[str, int]) -> int:
    if value not in table:
        raise GuardError(f"{name} must be one of {', '.join(table)}")
    return table[value]


def modifiers(mods: list[str] | None) -> list[str]:
    out = []
    for m in mods or []:
        low = str(m).lower()
        low = "super" if low == "cmd" else low
        if low not in MODIFIERS:
            raise GuardError(f"{m!r} is not a modifier ({', '.join(MODIFIERS)})")
        out.append(low)
    return out


def source_file(path: str, project: Path) -> Path:
    """A host file that may be copied into the sandbox: inside the project, regular, not a secret."""
    if not isinstance(path, str) or not path:
        raise GuardError("source must be a path relative to the project")
    p = (project / os.path.expanduser(path)).resolve()
    if p != project and project not in p.parents:
        raise GuardError(f"{path!r} is outside the project directory; only project files may enter the sandbox")
    rel = p.relative_to(project)
    if rel.parts and rel.parts[0] in DENIED_TOP_DIRS:
        raise GuardError(f"{path!r} is under {rel.parts[0]}/, which never enters the sandbox (git internals, stack "
                         "runtime state or Claude settings); copy the file elsewhere in the project first")
    if any(part in SECRET_PATH_PARTS for part in rel.parts) or SECRET_NAMES.search(rel.as_posix()):
        raise GuardError(f"{path!r} looks like a secret or credential file and is never copied into the sandbox")
    if not p.is_file():
        raise GuardError(f"{path!r} is not a regular file")
    if p.stat().st_size > MAX_FILE_BYTES:
        raise GuardError(f"{path!r} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    return p


def exchange_name(name: str) -> str:
    if not isinstance(name, str) or not _EXCHANGE_NAME.match(name) or ".." in name:
        raise GuardError("dest_name must be a plain file name (letters, digits, '._- ', no slashes)")
    return name


def argv(args: list[str]) -> list[str]:
    if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
        raise GuardError("argv must be a non-empty list of strings (no shell; one item per argument)")
    if len(args) > MAX_ARGS or any(len(a) > MAX_ARG_CHARS or "\x00" in a for a in args):
        raise GuardError(f"argv is limited to {MAX_ARGS} items of {MAX_ARG_CHARS} chars without NUL bytes")
    if args[0].startswith("-"):
        raise GuardError("argv[0] must be a program, not an option")
    for a in args:
        kind = secret_kind(a)
        if kind:
            raise GuardError(f"refused: an argument looks like a {kind}")
    return args
