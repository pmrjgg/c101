"""Fake container CLI: every test runs without Docker, recording the argv the server would run."""

from __future__ import annotations

import io
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image

from stack_mcp.desktop_sandbox import runtime, server
from stack_mcp.desktop_sandbox.config import Settings


def _png(w: int = 1280, h: int = 800) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (40, 50, 60)).save(buf, format="PNG")
    return buf.getvalue()


class FakeCLI:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.image_present = True
        self.ps_output = b""

    def __call__(self, argv: list[str], *, timeout: float = 30.0, check: bool = True):
        self.calls.append(list(argv))
        sub = argv[1]
        out, rc = b"", 0
        if sub == "image":
            rc = 0 if self.image_present else 1
        elif sub == "ps":
            out = self.ps_output
        elif sub == "inspect":
            out = b"true\n"
        elif sub == "exec":
            cmd = argv[argv.index("HOME=/home/sandbox") + 2:]
            if cmd[0] == "import":
                out = _png()
            elif cmd[:2] == ["xdotool", "getdisplaygeometry"]:
                out = b"1280 800\n"
            elif cmd[:2] == ["xprop", "-root"]:
                out = b"_NET_CLIENT_LIST(WINDOW): window id # 0x400003\n"
            elif cmd[:2] == ["xdotool", "getwindowname"]:
                out = b"Untitled - Editor\n"
            elif cmd[:2] == ["xdotool", "getwindowgeometry"]:
                out = b"WINDOW=4194307\nX=10\nY=20\nWIDTH=300\nHEIGHT=200\nSCREEN=0\n"
        return subprocess.CompletedProcess(argv, rc, out, b"")

    def execs(self) -> list[list[str]]:
        return [c[c.index("HOME=/home/sandbox") + 2:] for c in self.calls if c[1] == "exec"]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, project: Path) -> Iterator[FakeCLI]:
    fake = FakeCLI()
    monkeypatch.setattr(runtime, "run", fake)
    server.STATE.box = None
    server.STATE.lock = None
    server.STATE.settings = Settings(runtime="/usr/bin/fake-docker", project=project, max_actions=8)
    yield fake
    server.STATE.box = None
    server.STATE.settings = None
    server.STATE.lock = None
