"""Settings for the desktop sandbox, from ``DESKTOP_SANDBOX_*`` variables (safe defaults, clamped).

bin/mcp-run exports only ``DESKTOP_SANDBOX_*`` lines of ~/.claude/stack.env to this server
(``--only DESKTOP_SANDBOX_``), so it gets none of the stack's keys from that file. It still inherits Claude
Code's own environment; runtime.cli_env() keeps all of that away from the container CLI and the container.
Anything that weakens isolation (network access) is opt-in by the user in that file, never a tool argument.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_IMAGE = "c101-desktop-sandbox:1"
NETWORKS = ("none", "bridge")
_SIZE = re.compile(r"^(\d{3,4})x(\d{3,4})$")
_MEMORY = re.compile(r"^\d{3,5}m$|^\d{1,2}g$")
_CPUS = re.compile(r"^\d{1,2}(\.\d{1,2})?$")
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/:@-]{0,200}$")
# Binary search order when DESKTOP_SANDBOX_RUNTIME is unset; PATH from Claude Code may be minimal.
RUNTIMES = ("docker", "podman")
EXTRA_PATHS = ("/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.orbstack/bin"),
               "/Applications/Docker.app/Contents/Resources/bin")


def _clamp(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(lo, min(hi, int(raw)))
    except ValueError:
        print(f"desktop-sandbox: ignoring {name}={raw!r} (not an integer)", file=sys.stderr)
        return default


def _match(name: str, default: str, pattern: re.Pattern[str]) -> str:
    raw = os.environ.get(name, "").strip()
    if raw and pattern.match(raw):
        return raw
    if raw:
        print(f"desktop-sandbox: ignoring {name}={raw!r} (invalid)", file=sys.stderr)
    return default


def find_runtime(choice: str = "") -> str:
    """Absolute path of the container CLI ('' when none is installed)."""
    names = [choice] if choice else list(RUNTIMES)
    search = os.pathsep.join([os.environ.get("PATH", "/usr/bin:/bin"), *EXTRA_PATHS])
    for n in names:
        if os.sep in n:
            if os.path.isfile(n) and os.access(n, os.X_OK):
                return n
            continue
        hit = shutil.which(n, path=search)
        if hit:
            return hit
    return ""


def project_dir() -> Path:
    """CLAUDE_PROJECT_DIR when set (Claude Code exports it), else the cwd."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


@dataclass(frozen=True)
class Settings:
    runtime: str
    image: str = DEFAULT_IMAGE
    network: str = "none"
    width: int = 1280
    height: int = 800
    memory: str = "2g"
    cpus: str = "2"
    pids: int = 512
    max_lifetime: int = 1800  # seconds; enforced by the container (sleep as the main process)
    idle_timeout: int = 600   # seconds without an action before the server stops the sandbox
    max_actions: int = 600
    project: Path = field(default_factory=project_dir)

    @property
    def state_root(self) -> Path:
        return self.project / ".stack" / "sandbox"


def load() -> Settings:
    runtime_choice = os.environ.get("DESKTOP_SANDBOX_RUNTIME", "").strip()
    network = os.environ.get("DESKTOP_SANDBOX_NETWORK", "none").strip() or "none"
    if network not in NETWORKS:
        print(f"desktop-sandbox: DESKTOP_SANDBOX_NETWORK={network!r} is not one of {NETWORKS}; using none",
              file=sys.stderr)
        network = "none"
    width, height = 1280, 800
    size = os.environ.get("DESKTOP_SANDBOX_SIZE", "").strip()
    m = _SIZE.match(size) if size else None
    if m:
        width = max(640, min(1920, int(m.group(1))))
        height = max(480, min(1200, int(m.group(2))))
    elif size:
        print(f"desktop-sandbox: ignoring DESKTOP_SANDBOX_SIZE={size!r} (want WIDTHxHEIGHT)", file=sys.stderr)
    return Settings(
        runtime=find_runtime(runtime_choice),
        image=_match("DESKTOP_SANDBOX_IMAGE", DEFAULT_IMAGE, _IMAGE),
        network=network,
        width=width,
        height=height,
        memory=_match("DESKTOP_SANDBOX_MEMORY", "2g", _MEMORY),
        cpus=_match("DESKTOP_SANDBOX_CPUS", "2", _CPUS),
        max_lifetime=60 * _clamp("DESKTOP_SANDBOX_MAX_MINUTES", 30, 1, 120),
        idle_timeout=60 * _clamp("DESKTOP_SANDBOX_IDLE_MINUTES", 10, 1, 60),
        max_actions=_clamp("DESKTOP_SANDBOX_MAX_ACTIONS", 600, 10, 5000),
    )
