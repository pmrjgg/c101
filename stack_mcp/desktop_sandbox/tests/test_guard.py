from __future__ import annotations

from pathlib import Path

import pytest

from stack_mcp.desktop_sandbox import guard
from stack_mcp.desktop_sandbox.guard import GuardError


@pytest.mark.parametrize("secret", [
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "AKIAABCDEFGHIJKLMNOP",
    "sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345",
    "ghp_" + "a1B2" * 9,
    "xoxb-123456789012-abcdefghij",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "4111 1111 1111 1111",
    "token: Zx9qT4mW8rL2vB7nK5pD3sF6hJ1gC0aYeXuQ",
])
def test_secrets_are_refused(secret: str) -> None:
    with pytest.raises(GuardError, match="refused"):
        guard.text("my value is " + secret)


@pytest.mark.parametrize("ok", [
    "Quarterly report 2026", "hello world", "1234 5678", "https://example.com/docs/getting-started",
    "the order number is 4111 1111 1111 1112", "/exchange/report-final-v2.pdf", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
])
def test_ordinary_text_passes(ok: str) -> None:
    assert guard.text(ok) == ok


def test_text_limits() -> None:
    with pytest.raises(GuardError):
        guard.text("")
    with pytest.raises(GuardError):
        guard.text("x" * (guard.MAX_TEXT + 1))
    with pytest.raises(GuardError):
        guard.text("a\x00b")


@pytest.mark.parametrize("combo,want", [
    ("Return", "Return"), ("ctrl+s", "ctrl+s"), ("Ctrl+Shift+t", "ctrl+shift+t"), ("cmd+q", "super+q"),
    ("alt+F4", "alt+F4"), ("Page_Down", "Page_Down"),
])
def test_keys_ok(combo: str, want: str) -> None:
    assert guard.keys(combo) == want


@pytest.mark.parametrize("combo", ["", "ctrl+", "--window 1 a", "ctrl+$(id)", "foo+a", "a;b", "+", "ctrl++"])
def test_keys_refused(combo: str) -> None:
    with pytest.raises(GuardError):
        guard.keys(combo)


def test_points_and_regions() -> None:
    assert guard.point(0, 0, 1280, 800) == (0, 0)
    for x, y in ((1280, 0), (-1, 5), (5, 800)):
        with pytest.raises(GuardError):
            guard.point(x, y, 1280, 800)
    with pytest.raises(GuardError):
        guard.point(1.5, 2, 1280, 800)  # type: ignore[arg-type]
    assert guard.region(1200, 700, 500, 500, 1280, 800) == (1200, 700, 80, 100)
    with pytest.raises(GuardError):
        guard.region(0, 0, 4, 4, 1280, 800)


def test_source_file_rules(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("a,b\n")
    (tmp_path / ".env").write_text("X=1\n")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("Host x\n")
    (tmp_path / "server.pem").write_text("pem\n")
    assert guard.source_file("data.csv", tmp_path) == (tmp_path / "data.csv").resolve()
    for bad in (".env", ".ssh/config", "server.pem", "../outside.txt", "/etc/hosts", "missing.txt"):
        with pytest.raises(GuardError):
            guard.source_file(bad, tmp_path)


def test_source_file_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("nope")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "link.txt").symlink_to(outside)
    with pytest.raises(GuardError, match="outside the project"):
        guard.source_file("link.txt", proj)


def test_exchange_name_and_argv() -> None:
    assert guard.exchange_name("report v2.pdf") == "report v2.pdf"
    for bad in ("../x", "a/b", ".hidden", "", "x" * 200):
        with pytest.raises(GuardError):
            guard.exchange_name(bad)
    assert guard.argv(["xclock"]) == ["xclock"]
    for bad in ([], ["-rf"], "xclock", ["a"] * 40, ["echo", "AKIAABCDEFGHIJKLMNOP"]):
        with pytest.raises(GuardError):
            guard.argv(bad)  # type: ignore[arg-type]


def test_denied_trees_and_more_credential_names(tmp_path: Path) -> None:
    for rel in (".git/config", ".stack/sandbox/x/exchange/out.txt", ".claude/settings.local.json", ".npmrc",
                "infra/prod.tfstate", "conf/service-account-prod.json"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
        with pytest.raises(GuardError):
            guard.source_file(rel, tmp_path)
