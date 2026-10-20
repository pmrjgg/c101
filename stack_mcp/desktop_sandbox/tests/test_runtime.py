from __future__ import annotations

import os
from pathlib import Path

import pytest

from stack_mcp.desktop_sandbox import runtime
from stack_mcp.desktop_sandbox.config import Settings, load


def _flag(argv: list[str], name: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv) if a == name]


def test_run_argv_is_hardened(tmp_path: Path) -> None:
    s = Settings(runtime="/usr/bin/docker", project=tmp_path)
    argv = runtime.run_argv(s, "c101-sandbox-x", tmp_path / "ex")
    assert argv[:2] == ["/usr/bin/docker", "run"]
    assert "--read-only" in argv and "--rm" in argv
    assert _flag(argv, "--network") == ["none"]
    assert _flag(argv, "--cap-drop") == ["ALL"]
    assert _flag(argv, "--security-opt") == ["no-new-privileges"]
    assert _flag(argv, "--memory") == _flag(argv, "--memory-swap") == ["2g"]
    assert _flag(argv, "--pids-limit") == ["512"]
    user = _flag(argv, "--user")[0]
    assert not user.startswith("0:")
    mounts = _flag(argv, "--mount")
    assert mounts == [f"type=bind,source={tmp_path / 'ex'},target=/exchange"]  # the only host path shared
    assert not any(a in argv for a in ("--privileged", "--pid", "--ipc", "-v", "--volume", "--device"))
    assert not any("docker.sock" in a for a in argv)
    envs = _flag(argv, "--env")
    assert all(e.split("=")[0] in {"SCREEN", "MAX_LIFETIME", "HOME", "DISPLAY"} for e in envs)
    assert argv[-1] == s.image


def test_cli_env_drops_everything_else(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak-000000000000")
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/d.sock")
    env = runtime.cli_env()
    assert "ANTHROPIC_API_KEY" not in env and env["DOCKER_HOST"] == "unix:///tmp/d.sock"


def test_root_host_user_maps_to_unprivileged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "getuid", lambda: 0)
    assert runtime.container_user() == (runtime.FALLBACK_UID, runtime.FALLBACK_UID)


def test_sanitize_exchange_removes_planted_links(tmp_path: Path) -> None:
    ex = tmp_path / "exchange"
    (ex / "sub").mkdir(parents=True)
    (ex / "ok.txt").write_text("fine")
    (ex / "evil").symlink_to(Path.home())
    (ex / "sub" / "key").symlink_to("/etc/passwd")
    setuid = ex / "suid"
    setuid.write_text("#!/bin/sh\n")
    setuid.chmod(0o4755)
    removed = runtime.sanitize_exchange(ex)
    assert sorted(removed) == ["evil", "sub/key"]
    assert (ex / "ok.txt").exists() and not (ex / "evil").is_symlink()
    assert not setuid.stat().st_mode & 0o4000


def test_reap_orphans_only_dead_owners(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake(argv, *, timeout=30.0, check=True):
        import subprocess
        calls.append(argv)
        out = f"c101-sandbox-dead 999999\nc101-sandbox-mine {os.getpid()}\nc101-sandbox-live 1\n".encode()
        return subprocess.CompletedProcess(argv, 0, out if argv[1] == "ps" else b"", b"")

    monkeypatch.setattr(runtime, "run", fake)
    monkeypatch.setattr(runtime, "_pid_alive", lambda pid: pid == 1)
    reaped = runtime.reap_orphans(Settings(runtime="/x/docker", project=tmp_path))
    assert reaped == ["c101-sandbox-dead"]
    assert ["/x/docker", "rm", "--force", "c101-sandbox-dead"] in calls


def test_settings_clamp_and_network_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DESKTOP_SANDBOX_NETWORK", "host")
    monkeypatch.setenv("DESKTOP_SANDBOX_SIZE", "9999x100")
    monkeypatch.setenv("DESKTOP_SANDBOX_MAX_MINUTES", "1000")
    monkeypatch.setenv("DESKTOP_SANDBOX_IMAGE", "evil; rm -rf /")
    monkeypatch.setenv("DESKTOP_SANDBOX_MEMORY", "unlimited")
    s = load()
    assert s.network == "none"  # 'host' is never accepted
    assert (s.width, s.height) == (1920, 480)
    assert s.max_lifetime == 120 * 60
    assert s.image == "c101-desktop-sandbox:1" and s.memory == "2g"
    monkeypatch.setenv("DESKTOP_SANDBOX_NETWORK", "bridge")
    assert load().network == "bridge"


def test_unsafe_mount_path_refused(tmp_path: Path) -> None:
    s = Settings(runtime="/usr/bin/docker", project=tmp_path)
    bad = tmp_path / "proj,source=,target=x" / "ex"
    with pytest.raises(runtime.RuntimeFailure, match="--mount"):
        runtime.run_argv(s, "n", bad)


def test_sanitize_all_and_usage(tmp_path: Path) -> None:
    s = Settings(runtime="/x", project=tmp_path)
    old = s.state_root / "old-id" / "exchange"
    old.mkdir(parents=True)
    (old / "link").symlink_to("/etc/passwd")
    (old / "big.bin").write_bytes(b"x" * 10_000)
    assert runtime.sanitize_all(s) == ["old-id/link"]
    total, entries, over = runtime.usage(old, max_bytes=1000, max_entries=10)
    assert over and total > 1000
    assert runtime.usage(old, max_bytes=10**9, max_entries=10)[2] is False


def test_sanitize_tolerates_vanishing_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ex = tmp_path / "ex"
    ex.mkdir()
    (ex / "a").write_text("1")
    real = Path.lstat

    def flaky(self: Path):
        if self.name == "a":
            raise FileNotFoundError(self)
        return real(self)

    monkeypatch.setattr(Path, "lstat", flaky)
    assert runtime.sanitize_exchange(ex) == []
