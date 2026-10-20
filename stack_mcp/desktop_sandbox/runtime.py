"""The container behind one sandbox: hardened ``run`` argv, argv-only ``exec``, teardown and orphan reaping.

Nothing here goes through a shell. The container CLI runs with a minimal environment (PATH, HOME and the
variables that select a Docker/Podman context), so nothing else this process inherited can reach it, and
the container receives only the variables passed with ``-e`` below.
"""

from __future__ import annotations

import os
import secrets
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings

LABEL = "dev.c101.desktop-sandbox"
DISPLAY = ":99"
FALLBACK_UID = 10001  # the image's unprivileged user; used when the host user is root or unknown
CLI_ENV = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH",
           "DOCKER_TLS_VERIFY", "CONTAINER_HOST", "CONTAINER_CONNECTION", "XDG_RUNTIME_DIR", "TMPDIR")


class RuntimeFailure(RuntimeError):
    """The container CLI failed or is unavailable; the message is safe to show the agent."""


def cli_env() -> dict[str, str]:
    return {k: os.environ[k] for k in CLI_ENV if k in os.environ}


def container_user() -> tuple[int, int]:
    """Run as the host user (files in the exchange directory stay owned by them); never as root."""
    getuid = getattr(os, "getuid", None)
    uid = getuid() if getuid else 0
    gid = os.getgid() if getuid else 0
    return (uid, gid) if uid > 0 else (FALLBACK_UID, FALLBACK_UID)


# Docker parses --mount values as CSV (last source= wins): a path with these characters could bind another
# host directory, so such projects are refused rather than quoted.
_MOUNT_UNSAFE = set(',"=\n\r\'')


def run_argv(s: Settings, name: str, exchange: Path) -> list[str]:
    """``<cli> run`` for one sandbox. Every flag here is part of the security model (see the skill)."""
    if _MOUNT_UNSAFE & set(str(exchange)):
        raise RuntimeFailure(f"the project path {str(exchange)!r} contains one of , \" = ' or a newline, which "
                             "cannot be passed safely to --mount; move the project to a plain path")
    uid, gid = container_user()
    return [
        s.runtime, "run", "--detach", "--rm",
        "--name", name,
        "--label", f"{LABEL}=1",
        "--label", f"{LABEL}.owner-pid={os.getpid()}",
        "--network", s.network,
        "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777,size=512m",
        "--tmpfs", f"/home/sandbox:rw,nosuid,nodev,mode=0700,uid={uid},gid={gid},size=512m",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", str(s.pids),
        "--memory", s.memory, "--memory-swap", s.memory,
        "--cpus", s.cpus,
        "--user", f"{uid}:{gid}",
        "--workdir", "/exchange",
        "--mount", f"type=bind,source={exchange},target=/exchange",
        "--env", f"SCREEN={s.width}x{s.height}x24",
        "--env", f"MAX_LIFETIME={s.max_lifetime}",
        "--env", "HOME=/home/sandbox",
        "--env", f"DISPLAY={DISPLAY}",
        "--stop-timeout", "3",
        s.image,
    ]


def exec_argv(s: Settings, name: str, argv: list[str], *, detach: bool = False) -> list[str]:
    uid, gid = container_user()
    head = [s.runtime, "exec"]
    if detach:
        head.append("--detach")
    return [*head, "--user", f"{uid}:{gid}", "--env", f"DISPLAY={DISPLAY}", "--env", "HOME=/home/sandbox",
            name, *argv]


def run(argv: list[str], *, timeout: float = 30.0, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        cp = subprocess.run(argv, capture_output=True, timeout=timeout, env=cli_env(), check=False)
    except FileNotFoundError as exc:
        raise RuntimeFailure(f"container CLI not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeFailure(f"{Path(argv[0]).name} {argv[1]} timed out after {timeout:.0f}s") from exc
    if check and cp.returncode != 0:
        err = cp.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeFailure(f"{Path(argv[0]).name} {argv[1]} failed ({cp.returncode}): "
                             f"{(err[-1] if err else 'no output')[:300]}")
    return cp


PACKAGES_LABEL = LABEL + ".packages"


def image_present(s: Settings) -> bool:
    return run([s.runtime, "image", "inspect", "--format", "{{.Id}}", s.image], check=False).returncode == 0


def image_packages(s: Settings) -> list[str]:
    """Extra Debian packages baked into the image (label written by ``--build``); [] when none or unknown."""
    cp = run([s.runtime, "image", "inspect", "--format", "{{ index .Config.Labels \"" + PACKAGES_LABEL + "\" }}",
              s.image], check=False)
    raw = cp.stdout.decode("utf-8", "replace").strip() if cp.returncode == 0 else ""
    return [] if raw in ("", "<no value>") else raw.split()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reap_orphans(s: Settings) -> list[str]:
    """Remove sandboxes whose owning server process is gone (killed before it could clean up)."""
    cp = run([s.runtime, "ps", "--all", "--filter", f"label={LABEL}=1",
              "--format", "{{.Names}} {{.Label \"" + LABEL + ".owner-pid\"}}"], check=False)
    reaped = []
    for line in cp.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        cname, pid = parts
        if pid.isdigit() and int(pid) != os.getpid() and not _pid_alive(int(pid)):
            run([s.runtime, "rm", "--force", cname], check=False)
            reaped.append(cname)
    return reaped


def sanitize_exchange(root: Path) -> list[str]:
    """Delete anything in the exchange directory that is not a regular file or directory.

    The container can write there; a symlink it plants (``x -> /Users/me/.ssh/id_rsa``) would otherwise
    be followed by host-side reads or by put_file writes.
    """
    removed: list[str] = []
    if not root.is_dir() or root.is_symlink():
        return removed
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for n in [*dirnames, *filenames]:
            p = Path(dirpath) / n
            try:  # the container may delete or replace entries while we walk
                mode = p.lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    p.unlink()
                    removed.append(str(p.relative_to(root)))
                elif stat.S_ISREG(mode) and mode & (stat.S_ISUID | stat.S_ISGID):
                    os.chmod(p, mode & ~(stat.S_ISUID | stat.S_ISGID), follow_symlinks=False)
            except (FileNotFoundError, NotImplementedError, PermissionError):
                continue
    return removed


def sanitize_all(s: Settings) -> list[str]:
    """Sanitize every sandbox's exchange directory, including ones whose server was killed (no stop ran)."""
    removed: list[str] = []
    if s.state_root.is_dir():
        for ex in s.state_root.glob("*/exchange"):
            removed += [f"{ex.parent.name}/{r}" for r in sanitize_exchange(ex)]
    return removed


def usage(root: Path, *, max_bytes: int, max_entries: int) -> tuple[int, int, bool]:
    """(bytes, entries, over) of a directory tree, stopping early once a cap is passed."""
    total = entries = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for n in [*dirnames, *filenames]:
            entries += 1
            try:
                st = (Path(dirpath) / n).lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(st.st_mode):
                total += st.st_blocks * 512 if hasattr(st, "st_blocks") else st.st_size
            if total > max_bytes or entries > max_entries:
                return total, entries, True
    return total, entries, False


@dataclass
class Sandbox:
    """One running container; created by :meth:`start`, gone after :meth:`stop`."""

    settings: Settings
    name: str
    root: Path
    started: float = field(default_factory=time.monotonic)
    last_action: float = field(default_factory=time.monotonic)
    actions: int = 0

    @property
    def exchange(self) -> Path:
        return self.root / "exchange"

    @property
    def audit_path(self) -> Path:
        return self.root / "audit.jsonl"

    @classmethod
    def start(cls, s: Settings) -> Sandbox:
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        root = s.state_root / sid
        (root / "exchange").mkdir(parents=True, mode=0o700)
        (root / "shots").mkdir(mode=0o700)
        box = cls(settings=s, name=f"c101-sandbox-{sid}", root=root)
        run(run_argv(s, box.name, box.exchange), timeout=60)
        try:
            box.wait_ready()
        except RuntimeFailure:
            box.stop()
            raise
        return box

    def wait_ready(self, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            # the entrypoint touches this only after Xvfb is up AND openbox manages the screen
            cp = run(exec_argv(self.settings, self.name, ["test", "-e", "/tmp/.sandbox-ready"]), check=False)
            if cp.returncode == 0:
                return
            last = cp.stderr.decode("utf-8", "replace").strip()[-200:]
            time.sleep(0.25)
        raise RuntimeFailure(f"the sandbox display did not come up within {timeout:.0f}s ({last or 'no output'})")

    def exec(self, argv: list[str], *, timeout: float = 20.0, detach: bool = False) -> bytes:
        self.last_action = time.monotonic()
        cp = run(exec_argv(self.settings, self.name, argv, detach=detach), timeout=timeout)
        return cp.stdout

    def alive(self) -> bool:
        cp = run([self.settings.runtime, "inspect", "--format", "{{.State.Running}}", self.name], check=False)
        return cp.returncode == 0 and cp.stdout.strip() == b"true"

    def remaining(self) -> int:
        return max(0, int(self.settings.max_lifetime - (time.monotonic() - self.started)))

    def stop(self) -> list[str]:
        run([self.settings.runtime, "rm", "--force", self.name], timeout=30, check=False)
        return sanitize_exchange(self.exchange)


def stop_quietly(box: Sandbox | None) -> None:
    """Best-effort teardown for exit paths (signals, atexit); never raises."""
    if box is None:
        return
    try:
        box.stop()
    except Exception as exc:  # pragma: no cover - exit path
        print(f"desktop-sandbox: teardown of {box.name} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
