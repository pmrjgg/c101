from __future__ import annotations

import asyncio
import json
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
