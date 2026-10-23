from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from stack_mcp.desktop_sandbox import server
from stack_mcp.desktop_sandbox.runtime import LABEL


def call(fn, **kw: Any):
    server.STATE.lock = None
    res = asyncio.run(fn(**kw))
    payload = json.loads(res.content[0].text)
    return res, payload


def test_actions_need_a_running_sandbox(cli) -> None:
    res, p = call(server.click, x=1, y=1)
    assert res.is_error and "sandbox_start" in p["error"]
    assert cli.calls == []


def test_start_refuses_without_image(cli) -> None:
    cli.image_present = False
    res, p = call(server.sandbox_start)
    assert res.is_error and "bin/desktop-sandbox --build" in p["next"]
    assert not any(c[1] in ("build", "pull", "run") for c in cli.calls)  # never builds or pulls itself


def test_full_cycle(cli, project: Path) -> None:
    res, p = call(server.sandbox_start)
    assert not res.is_error and p["network"] == "none" and p["exchange_sandbox"] == "/exchange"
    run = next(c for c in cli.calls if c[1] == "run")
    assert f"{LABEL}=1" in run and "--read-only" in run

    res, p = call(server.click, x=100, y=200, button="right", modifiers=["ctrl"], then_screenshot=True)
    assert not res.is_error and res.content[1].type == "image"
    assert ["xdotool", "mousemove", "--sync", "100", "200", "keydown", "ctrl", "click", "--repeat", "1",
            "--delay", "80", "3", "keyup", "ctrl"] in cli.execs()

    res, p = call(server.key, keys="ctrl+s")
    assert cli.execs()[-1][-2:] == ["--", "ctrl+s"]

    res, p = call(server.type_text, text="hello sandbox")
    assert cli.execs()[-1][-2:] == ["--", "hello sandbox"]

    res, p = call(server.zoom, x=10, y=10, width=100, height=50)
    assert not res.is_error and p["scale"] > 1

    res, p = call(server.window_list)
    assert p["untrusted"] is True and p["windows"][0]["title"] == "Untitled - Editor"
    assert p["windows"][0]["id"] == 0x400003

    res, p = call(server.launch, argv=["xclock"])
    detached = [c for c in cli.calls if c[1] == "exec" and "--detach" in c]
    assert detached and detached[-1][-1] == "xclock"

    box = server.STATE.box
    audit = box.audit_path.read_text().splitlines()
    assert all(json.loads(line)["ok"] for line in audit)
    assert "hello sandbox" not in box.audit_path.read_text()  # typed text: length + hash only

    res, p = call(server.sandbox_stop)
    assert not res.is_error and server.STATE.box is None
    assert any(c[1:3] == ["rm", "--force"] for c in cli.calls)


def test_secret_typing_refused_and_not_logged(cli) -> None:
    call(server.sandbox_start)
    secret = "sk-ant-api03-" + "Q" * 40
    res, p = call(server.type_text, text=secret)
    assert res.is_error and "refused" in p["error"]
    assert not any(secret in " ".join(c) for c in cli.calls)
    assert secret not in server.STATE.box.audit_path.read_text()


def test_action_budget(cli) -> None:
    call(server.sandbox_start)
    for _ in range(8):
        res, _p = call(server.move, x=5, y=5)
        assert not res.is_error
    res, p = call(server.move, x=5, y=5)
    assert res.is_error and "budget" in p["error"]
    res, p = call(server.screenshot)  # observing stays possible so the agent can report
    assert not res.is_error


def test_one_sandbox_per_server(cli) -> None:
    call(server.sandbox_start)
    res, p = call(server.sandbox_start)
    assert res.is_error and "already running" in p["error"]


def test_put_file_copies_and_refuses_planted_link(cli, project: Path) -> None:
    (project / "in.csv").write_text("a,b\n1,2\n")
    call(server.sandbox_start)
    res, p = call(server.put_file, source="in.csv")
    assert not res.is_error and p["sandbox_path"] == "/exchange/in.csv"
    box = server.STATE.box
    assert (box.exchange / "in.csv").read_text() == "a,b\n1,2\n"
    target = project / "victim.txt"
    target.write_text("original")
    (box.exchange / "trap.csv").symlink_to(target)
    res, p = call(server.put_file, source="in.csv", dest_name="trap.csv")
    assert not res.is_error  # the planted link was removed first, then a fresh file written
    assert target.read_text() == "original" and not (box.exchange / "trap.csv").is_symlink()
    res, p = call(server.put_file, source="in.csv", dest_name="in.csv")
    assert res.is_error and "already exists" in p["error"]


def test_lifespan_teardown_removes_container(cli) -> None:
    call(server.sandbox_start)

    async def go() -> None:
        async with server._lifespan(server.build_server()):
            pass

    server.STATE.lock = None
    asyncio.run(go())
    assert server.STATE.box is None
    assert any(c[1:3] == ["rm", "--force"] for c in cli.calls)


def test_tool_surface_and_annotations() -> None:
    tools = {t.name: t for t in asyncio.run(server.build_server().list_tools())}
    assert set(tools) == {f.__name__ for f in server.ALL_TOOLS}
    assert tools["screenshot"].annotations.read_only_hint
    assert not tools["click"].annotations.read_only_hint
    assert all(t.annotations.open_world_hint is False for t in tools.values())
    props = tools["sandbox_start"].input_schema.get("properties") or {}
    assert not props  # isolation is configured by the user, never by tool arguments


def test_put_file_refuses_source_swapped_after_check(cli, project: Path, monkeypatch) -> None:
    (project / "in.csv").write_text("a,b\n")
    secret = project.parent / "outside-secret.txt"
    secret.write_text("TOP SECRET")
    call(server.sandbox_start)
    real = server.guard.source_file

    def check_then_swap(path, proj):
        p = real(path, proj)
        p.unlink()
        p.symlink_to(secret)  # the race the container could win
        return p

    monkeypatch.setattr(server.guard, "source_file", check_then_swap)
    res, p = call(server.put_file, source="in.csv")
    assert res.is_error and "changed" in p["error"]
    assert not (server.STATE.box.exchange / "in.csv").exists()


def test_put_file_refuses_exchange_sources(cli, project: Path) -> None:
    call(server.sandbox_start)
    out = server.STATE.box.exchange / "made-by-sandbox.txt"
    out.write_text("x")
    res, p = call(server.put_file, source=str(out.relative_to(project)))
    assert res.is_error and ".stack/" in p["error"]


def test_refused_argv_secret_is_redacted_in_audit(cli) -> None:
    call(server.sandbox_start)
    secret = "AKIAABCDEFGHIJKLMNOP"
    res, _p = call(server.launch, argv=["app", secret])
    assert res.is_error
    log = server.STATE.box.audit_path.read_text()
    assert secret not in log and "redacted" in log


def test_typed_text_audit_is_keyed(cli) -> None:
    call(server.sandbox_start)
    call(server.type_text, text="1234")
    import hashlib
    log = server.STATE.box.audit_path.read_text()
    assert hashlib.sha256(b"1234").hexdigest()[:16] not in log and '"hmac"' in log


def test_saved_screenshots_count_against_budget(cli) -> None:
    call(server.sandbox_start)
    before = server.STATE.box.actions
    res, p = call(server.screenshot, save=True)
    assert not res.is_error and p["saved"].startswith(".stack/sandbox/")
    assert server.STATE.box.actions == before + 1
    call(server.screenshot)
    assert server.STATE.box.actions == before + 1


def test_build_passes_validated_packages(monkeypatch, tmp_path) -> None:
    from stack_mcp.desktop_sandbox.config import Settings
    seen = []
    monkeypatch.setattr(server.subprocess, "call", lambda argv: seen.append(argv) or 0)
    s = Settings(runtime="/x/docker", project=tmp_path)
    assert server.build_image(s, "libreoffice-calc, firefox-esr", "debian:bookworm-slim@sha256:" + "a" * 64) == 0
    argv = seen[-1]
    assert ["--build-arg", "EXTRA_PACKAGES=libreoffice-calc firefox-esr"] == argv[argv.index("--build-arg"):][:2]
    assert argv[-1].endswith("image")
    for bad in ("libreoffice; rm -rf /", "--privileged", "$(id)"):
        assert server.build_image(s, bad) == 2


def test_profiles_resolve_and_are_valid() -> None:
    profiles = server.load_profiles()
    rec = server.profile_packages("recommended")
    assert set(server.profile_packages("operator")) | set(server.profile_packages("tester")) == set(rec)
    assert "libreoffice-calc" in rec and "openjfx" not in rec and len(rec) == len(set(rec))
    assert all(server._DEB_PACKAGE.match(p) for name in profiles for p in server.profile_packages(name))
    with pytest.raises(ValueError):
        server.profile_packages("nope")
    with pytest.raises(ValueError):
        server.profile_packages("a", {"a": {"include": ["a"]}})


def test_build_with_profile_labels_image(monkeypatch, tmp_path) -> None:
    from stack_mcp.desktop_sandbox.config import Settings
    seen = []
    monkeypatch.setattr(server.subprocess, "call", lambda argv: seen.append(argv) or 0)
    s = Settings(runtime="/x/docker", project=tmp_path)
    assert server.build_image(s, "gimp", "", "operator") == 0
    argv = seen[-1]
    label = argv[argv.index("--label") + 1]
    assert label.startswith("dev.c101.desktop-sandbox.packages=libreoffice-calc") and label.endswith(" gimp")
    assert server.build_image(s, "", "", "bogus") == 2


# --- command line: implied build, rejected combinations, serve hint -------------------------------------

@pytest.fixture
def cmdline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """main() with nothing real behind it: records build_image calls and whether serving started."""
    from stack_mcp.desktop_sandbox.config import Settings

    class Rec:
        builds: list[tuple[str, str, str]] = []
        served = False

    rec = Rec()
    rec.builds = []
    monkeypatch.setattr(server.STATE, "settings", Settings(runtime="/x/docker", project=tmp_path))
    monkeypatch.setattr(server, "build_image",
                        lambda s, packages="", base="", profile="": rec.builds.append((packages, base, profile)) or 0)
    monkeypatch.setattr(server, "_install_exit_handlers", lambda: None)

    class FakeServer:
        def run(self, transport: str) -> None:
            rec.served = True

    monkeypatch.setattr(server, "build_server", lambda: FakeServer())
    yield rec
    monkeypatch.setattr(server.STATE, "settings", None)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--profile", "recommended", "--packages", "krita inkscape libreoffice gimp"],
         ("krita inkscape libreoffice gimp", "", "recommended")),
        (["--packages", "gimp"], ("gimp", "", "")),
        (["--base", "debian:bookworm-slim"], ("", "debian:bookworm-slim", "")),
        (["--build", "--profile", "operator"], ("", "", "operator")),
        (["--build"], ("", "", "")),
    ],
    ids=["users-command", "packages-only", "base-only", "explicit-build", "bare-build"],
)
def test_build_options_run_a_build(cmdline, capsys, argv, expected) -> None:
    assert server.main(argv) == 0
    assert cmdline.builds == [expected] and not cmdline.served
    out, err = capsys.readouterr()
    assert out == ""
    implied = "--build" not in argv
    assert ("running --build" in err) is implied


@pytest.mark.parametrize(
    "argv",
    [["--check", "--build"], ["--check", "--profile", "recommended"], ["--check", "--packages", "gimp"],
     ["--list-profiles", "--build"], ["--list-profiles", "--base", "x"], ["--list-profiles", "--check"]],
    ids=["check-build", "check-profile", "check-packages", "list-build", "list-base", "list-check"],
)
def test_incompatible_combinations_are_rejected(cmdline, capsys, argv) -> None:
    with pytest.raises(SystemExit) as exc:
        server.main(argv)
    assert exc.value.code == 2
    assert cmdline.builds == [] and not cmdline.served
    assert "cannot be combined" in capsys.readouterr().err


def test_plain_serve_is_unchanged_without_a_tty(cmdline, capsys, monkeypatch) -> None:
    monkeypatch.setattr(server.sys, "stdin", type("Pipe", (), {"isatty": lambda self: False})())
    assert server.main([]) == 0
    assert cmdline.served and cmdline.builds == []
    out, err = capsys.readouterr()
    assert out == "" and "waiting for an MCP client" not in err  # Claude Code's launch: one status line only


def test_serve_from_a_terminal_explains_itself_on_stderr_only(cmdline, capsys, monkeypatch) -> None:
    monkeypatch.setattr(server.sys, "stdin", type("Tty", (), {"isatty": lambda self: True})())
    assert server.main([]) == 0
    assert cmdline.served  # still serves
    out, err = capsys.readouterr()
    assert out == ""  # stdout is the MCP channel
    for needle in ("MCP", "--build --profile recommended", "--check", "Ctrl-C"):
        assert needle in err


def test_help_mentions_the_implied_build(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        server._parse(["--help"])
    assert exc.value.code == 0
    assert "implies --build" in capsys.readouterr().out


# --- build_image output and docker flags ----------------------------------------------------------------

def _fake_run(monkeypatch, context: str = "desktop-linux") -> None:
    monkeypatch.setattr(server.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, context + "\n", ""))


def test_build_reports_packages_runtime_and_context(monkeypatch, tmp_path, capsys) -> None:
    from stack_mcp.desktop_sandbox.config import Settings
    monkeypatch.setattr(server.subprocess, "call", lambda argv: 0)
    _fake_run(monkeypatch)
    s = Settings(runtime="/x/docker", project=tmp_path)
    assert server.build_image(s, "krita gimp", "", "operator") == 0
    out, err = capsys.readouterr()
    assert out == ""
    assert "building image" in err and "docker (context 'desktop-linux')" in err
    assert "packages (" in err and "krita gimp" in err and "build finished" in err


def test_failed_build_says_so_and_returns_its_exit_code(monkeypatch, tmp_path, capsys) -> None:
    from stack_mcp.desktop_sandbox.config import Settings
    monkeypatch.setattr(server.subprocess, "call", lambda argv: 100)
    _fake_run(monkeypatch)
    assert server.build_image(Settings(runtime="/x/docker", project=tmp_path), "gimp") == 100
    assert "FAILED (exit 100)" in capsys.readouterr().err


@pytest.mark.parametrize(("runtime", "tty", "plain"),
                         [("/x/docker", False, True), ("/x/docker", True, False), ("/x/podman", False, False)],
                         ids=["docker-piped", "docker-tty", "podman-piped"])
def test_progress_plain_only_for_docker_without_a_terminal(monkeypatch, tmp_path, runtime, tty, plain) -> None:
    from stack_mcp.desktop_sandbox.config import Settings
    seen: list[list[str]] = []
    monkeypatch.setattr(server.subprocess, "call", lambda argv: seen.append(argv) or 0)
    _fake_run(monkeypatch)
    monkeypatch.setattr(server.sys, "stderr", type("Err", (), {
        "isatty": lambda self: tty, "write": lambda self, s: len(s), "flush": lambda self: None})())
    assert server.build_image(Settings(runtime=runtime, project=tmp_path), "gimp") == 0
    assert ("--progress=plain" in seen[-1]) is plain
