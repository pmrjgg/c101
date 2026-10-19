"""Prompt-injection tripwire for untrusted web content, and the risky-action classifier.

Stdlib only: it runs inside hooks on every web-tool result and every risky tool call.

* ``scan(text)`` scores tool output against heuristic rules: text addressed to an AI agent,
  instruction overrides, fake role or tool-call markup, requests to send secrets, secret
  paths, exfiltration-shaped URLs, hidden or smuggled characters, pipe-to-shell commands,
  persona switches and secrecy demands. Levels: ``low`` (< medium), ``medium``, ``high``.
* ``risky_action(tool, tool_input, project_dir)`` names what a tool call would do that an
  injected instruction could abuse (network egress or pipe-to-shell in Bash, secret reads,
  git push, writes outside ``.stack/``, typing into web forms), or returns None.
* Taint state (``mark`` / ``taint_of``): which agents in a session have ingested flagged
  content, kept in ``<data>/sessions/<session>.taint.json``.

These are tripwires, not a guarantee: paraphrases, other languages and text inside images get
through. The containment comes from the tool limits on web-reading agents (see
``config/policy.json`` ``web_content``), which this module helps enforce.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
import unicodedata
from typing import Any, Dict, List, NamedTuple, Optional

from . import paths

MAX_SCAN_CHARS = 400_000

# (rule, weight, compiled regex). A rule counts once per scan; weights add up.
_I = re.I | re.M
RULES = [
    ("instruction-override", 4, re.compile(
        r"\b(ignore|disregard|forget|override|bypass)\b(?:[^.\n]|\.(?=\S)){0,40}\b(previous|prior|above|earlier|all|any|your|the|these)\b"
        r"(?:[^.\n]|\.(?=\S)){0,30}\b(instructions?|prompts?|rules|directions|guidelines|guardrails|context)\b", _I)),
    ("addressed-to-ai", 3, re.compile(
        r"\b(if you are an? (ai|llm|language model|assistant|agent|bot)|(attention|note|message|instructions?) (to|for) "
        r"(the )?(ai|llm|assistant|agent|model|claude|chatgpt|gpt)s?|(dear|hey|hello) (ai|assistant|agent|llm|claude|model)|"
        r"(ai|llm) (agents?|assistants?|models?|crawlers?)[ ,]+(must|should|are (required|instructed)|please))\b", _I)),
    ("new-instructions", 3, re.compile(
        r"\b(new|updated|real|actual|hidden|secret|true|system|developer)\s+(instructions?|directives?|task|objective|"
        r"orders|prompt)\s*[:\-]", _I)),
    # chat-template tokens and role tags also appear in AI documentation, so alone they stay below medium
    ("role-markup", 2, re.compile(
        r"(<\|?(system|im_start|im_end|assistant|user)\|?>|\[/?INST\]|</?(system|system-reminder|assistant|tool_call|"
        r"tool_use|instructions?)>)", _I)),
    ("tool-call-markup", 4, re.compile(r"(<invoke\s+name=|<function_calls>|<parameter\s+name=|\"tool_use\"\s*:)", _I)),
    ("send-secrets", 4, re.compile(
        r"\b(send|post|upload|exfiltrate|forward|leak|transmit|email|include|append|embed|paste|share)\b(?:[^.\n]|\.(?=\S)){0,60}"
        r"\b(api[_ -]?keys?|access tokens?|tokens|credentials?|passwords?|secrets?|env(ironment)? (vars?|variables)|"
        r"stack\.env|ssh keys?|private keys?|cookies|session ids?|system prompt|conversation|chat history)\b", _I)),
    ("secret-paths", 2, re.compile(
        r"(\.ssh/|\.aws/|\.gnupg/|\.claude/stack\.env|\bstack\.env\b|\bid_(rsa|ed25519|ecdsa)\b|\.netrc\b|\.npmrc\b|"
        r"\bkeychain\b|security find-(generic|internet)-password)", _I)),
    ("pipe-to-shell", 2, re.compile(
        r"((curl|wget)\b[^\n|]{0,200}\|\s*(sudo\s+)?(ba|z|da)?sh\b|\bbase64\s+(-d|--decode)\b[^\n]{0,80}\|\s*(ba|z)?sh\b|"
        r"\beval\s*\$\(\s*(curl|wget)\b)", _I)),
    ("exfil-url", 3, re.compile(
        r"(https?://[^\s)\"'<>]*(\{\{|\$\{|%7B%7B|%24%7B)[^\s)\"'<>]*|"
        r"!\[[^\]]*\]\(https?://[^)\s]*\?[^)\s]*=(\{|\$|%7B|[A-Za-z0-9+/_-]{32,})[^)\s]*\))", _I)),
    ("persona-switch", 3, re.compile(
        r"(\byou are now (a|an|in|the)\b|\bfrom now on,? you (are|will|must)\b|\b(developer|god|jailbreak|dan) mode\b|"
        r"\bact as an? (unrestricted|unfiltered|jailbroken)\b)", _I)),
    ("secrecy-demand", 3, re.compile(
        r"\b(do not|don't|never) (tell|inform|mention|reveal|show|alert|notify)\b(?:[^.\n]|\.(?=\S)){0,30}\b(the )?(user|human|"
        r"operator|owner|anyone)\b", _I)),
    ("ascii-smuggling", 4, re.compile("[\U000E0000-\U000E007F]")),
    ("zero-width-run", 2, re.compile("[​‌‍⁠﻿]{3,}")),
]


class Scan(NamedTuple):
    score: int
    level: str  # "low" | "medium" | "high"
    hits: List[str]  # rule names, in rule order
    digest: str  # sha256 of the scanned text (for logs; the text itself is never stored)


def thresholds(pol: Optional[dict] = None) -> Dict[str, int]:
    wc = (pol or {}).get("web_content") or {}
    return {"medium": int(wc.get("medium", 3)), "high": int(wc.get("high", 6))}


def flatten(obj: Any, limit: int = MAX_SCAN_CHARS) -> str:
    """Every string leaf of a tool response (MCP content blocks, dicts, lists), up to ``limit`` chars."""
    out: List[str] = []
    size = 0

    def walk(o: Any) -> None:
        nonlocal size
        if size >= limit:
            return
        if isinstance(o, str):
            out.append(o[: limit - size])
            size += len(out[-1])
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)

    walk(obj)
    return "\n".join(out)


def scan(text: str, pol: Optional[dict] = None) -> Scan:
    text = text[:MAX_SCAN_CHARS]
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
    raw_hits = {name for name, _, rx in RULES if name in ("ascii-smuggling", "zero-width-run") and rx.search(text)}
    # NFKC folds full-width and compatibility forms; dropping zero-width characters defeats w​o​r​d splitting
    norm = unicodedata.normalize("NFKC", text)
    norm = re.sub("[​‌‍⁠﻿\U000E0000-\U000E007F]", "", norm)
    hits = [name for name, _, rx in RULES if name in raw_hits or (name not in ("ascii-smuggling", "zero-width-run") and rx.search(norm))]
    weights = {name: w for name, w, _ in RULES}
    score = sum(weights[h] for h in hits)
    th = thresholds(pol)
    level = "high" if score >= th["high"] else "medium" if score >= th["medium"] else "low"
    return Scan(score, level, hits, digest)


# --- risky actions ------------------------------------------------------------------------------

EGRESS_CMDS = {"curl", "wget", "nc", "ncat", "netcat", "socat", "telnet", "ssh", "scp", "sftp", "ftp", "rsync",
               "aria2c", "httpie", "xh", "lynx", "w3m"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
INTERPRETERS = {"python", "python3", "node", "perl", "ruby", "php", "deno", "bun"}
WRAPPERS = {"sudo", "env", "time", "nohup", "exec", "command", "builtin", "nice", "timeout", "xargs", "stdbuf"}
_SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|&\n]|\$\(|`")
_INLINE_NET = re.compile(r"\b(urllib|requests|httpx|aiohttp|socket|http\.client|fetch\s*\(|net/http|LWP::|fsockopen|"
                         r"URLSession|Net::HTTP|Deno\.connect)", re.I)
_SECRET_PATH = re.compile(r"((^|[\s/'\"=~])\.(ssh|aws|gnupg|netrc|npmrc|pypirc|git-credentials)\b|\bstack\.env\b|"
                          r"(^|[\s/'\"=])\.env(\.[A-Za-z0-9_-]+)?(\s|$|['\"])|\bid_(rsa|ed25519|ecdsa)\b|"
                          r"\bcredentials\.json\b|\bsecurity\s+find-(generic|internet)-password\b)", re.I)


_ARG_FLAGS = {"-u", "-g", "-C", "-p", "-n", "-s", "-k", "-o", "-e", "--user", "--group", "--signal", "--kill-after"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_DURATION = re.compile(r"^\d+(\.\d+)?[smhd]?$")


def _segments(cmd: str) -> List[List[str]]:
    """Command words of each pipeline/list segment; wrappers (sudo, env, timeout...), their options
    and VAR=value assignments are skipped so the head is the program that actually runs."""
    out = []
    for seg in _SEGMENT_SPLIT.split(cmd):
        words = seg.strip().split()
        i = 0
        while i < len(words):
            w = words[i]
            if _ASSIGN.match(w):
                i += 1
                continue
            if os.path.basename(w) in WRAPPERS and i + 1 < len(words):
                i += 1
                while i < len(words) and (words[i].startswith("-") or _DURATION.match(words[i]) or _ASSIGN.match(words[i])):
                    i += 2 if words[i] in _ARG_FLAGS else 1
                continue
            break
        words = words[i:]
        if words:
            out.append([os.path.basename(words[0])] + words[1:])
    return out


def risky_bash(cmd: str) -> Optional[str]:
    segs = _segments(cmd)
    heads = [w[0] for w in segs]
    # pipe into a shell, or into an interpreter reading its program from stdin
    for i, w in enumerate(segs[1:], 1):
        if "|" in cmd and (w[0] in SHELLS or (w[0] in INTERPRETERS and (len(w) == 1 or w[1] == "-"))):
            return "pipe-to-shell (output of another command executed by %s)" % w[0]
    for w in segs:
        if w[0] in SHELLS and "-c" in w[1:]:
            inner = " ".join(w[w.index("-c") + 1:]).strip().strip("'\"")
            why = risky_bash(inner) if inner and inner != cmd else None
            if why:
                return why + " (inside %s -c)" % w[0]
        if w[0] == "eval":
            return "eval of constructed commands"
    if any(h in EGRESS_CMDS for h in heads):
        return "network egress from Bash (%s)" % next(h for h in heads if h in EGRESS_CMDS)
    if any(w[0] in INTERPRETERS for w in segs) and _INLINE_NET.search(cmd):
        return "network access from an inline interpreter"
    if any(w[0] == "git" and len(w) > 1 and (w[1] == "push" or (w[1] == "remote" and len(w) > 2 and w[2] in ("add", "set-url")))
           for w in segs):
        return "git push / remote change"
    if _SECRET_PATH.search(cmd) or any(w[0] in ("printenv",) or (w[0] in ("env", "set", "export") and len(w) == 1)
                                       for w in segs):
        return "reading credentials or environment secrets"
    for w in segs:
        if w[0] == "rm" and any(a.startswith("-") and ("r" in a or "R" in a) for a in w[1:]):
            targets = [a for a in w[1:] if not a.startswith("-")]
            if any(".stack/" not in t and not t.startswith(".stack") for t in targets):
                return "recursive delete outside .stack/"
    return None


WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
FORM_TOOLS = ("mcp__playwright__browser_type", "mcp__playwright__browser_fill_form",
              "mcp__playwright__browser_file_upload", "mcp__playwright__browser_press_key")


MEMORY_PREFIX = "mcp__neural-memory__"
# Read-only NeuralMemory tools; every other tool of that server can write persistent memory.
MEMORY_READ_TOOLS = ("nmem_recall", "nmem_context", "nmem_recap", "nmem_situation", "nmem_health", "nmem_stats")


def under_root(path: str, project_dir: str, root: str = ".stack") -> bool:
    if not path:
        return False
    p = os.path.realpath(os.path.join(project_dir, os.path.expanduser(path)))
    base = os.path.realpath(os.path.join(project_dir, root))
    return p == base or p.startswith(base + os.sep)


def risky_action(tool: str, tool_input: dict, project_dir: str, write_root: str = ".stack") -> Optional[str]:
    tool_input = tool_input or {}
    if tool == "Bash":
        return risky_bash(str(tool_input.get("command") or ""))
    if tool in WRITE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if not under_root(str(path), project_dir, write_root):
            return "writing outside %s/ (%s)" % (write_root, path or "?")
        return None
    if tool in FORM_TOOLS:
        return "typing into or uploading to a web page"
    if tool.startswith(MEMORY_PREFIX) and tool[len(MEMORY_PREFIX):] not in MEMORY_READ_TOOLS:
        return "writing persistent memory (%s)" % tool[len(MEMORY_PREFIX):]
    return None


# --- taint state --------------------------------------------------------------------------------

def _taint_path(session_id: str) -> str:
    d = os.path.join(paths.data_dir(), "sessions")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s.taint.json" % re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown"))


def mark(session_id: str, agent_key: str, tool: str, url: str, res: Scan) -> dict:
    """Record that ``agent_key`` ingested flagged content; returns the agent's taint record."""
    path = _taint_path(session_id)
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(path, encoding="utf-8") as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            st = {}
        rec = st.setdefault(agent_key, {"first": time.time(), "events": 0, "score": 0, "level": "low",
                                        "urls": [], "rules": []})
        rec["events"] += 1
        if res.score > rec["score"]:
            rec["score"], rec["level"] = res.score, res.level
        if url and url not in rec["urls"]:
            rec["urls"] = (rec["urls"] + [url])[-5:]
        rec["rules"] = sorted(set(rec["rules"]) | set(res.hits))
        rec["last_tool"] = tool
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(st, fh)
        os.replace(path + ".tmp", path)
    return rec


def taint_of(session_id: str, agent_key: str) -> Optional[dict]:
    try:
        with open(_taint_path(session_id), encoding="utf-8") as fh:
            return json.load(fh).get(agent_key)
    except (OSError, ValueError):
        return None


def log_event(event: dict) -> None:
    """Append to <data>/injection.jsonl (rule names, score, URL, digest; never the content)."""
    try:
        with open(os.path.join(paths.data_dir(), "injection.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
    except OSError:
        pass


def url_of(tool_input: dict) -> str:
    ti = tool_input or {}
    for k in ("url", "urls", "uri", "link"):
        v = ti.get(k)
        if isinstance(v, list) and v:
            v = v[0]
        if isinstance(v, str) and v:
            return v[:300]
    return ""
