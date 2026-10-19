"""End-to-end: launch the real server over stdio and speak raw JSON-RPC.

Covers initialize, tools/list (svg_transform appears only after the env file changes - no
restart), image_ops_status, an unconfigured operation's error, a local tool, and the
bin/image-router launcher itself (with the ignored --mode flag).
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from .conftest import EXTRA_ENV, FIXTURES

REPO = Path(__file__).resolve().parents[3]
LAUNCHER = REPO / "bin" / "image-router"
TIMEOUT = 60.0

# Nothing configured: only image_ops_status and the local tools are listed.
EXPECTED_TOOLS = {
    "image_ops_status", "image_info", "mask_convert", "svg_optimize", "svg_inspect", "svg_render", "svg_layers",
    "svg_layerize", "layers_compose", "export_pdf",
}


class StdioSession:
    def __init__(self, cmd: list[str], cwd: Path, env: dict[str, str]):
        self.proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self.lines: queue.Queue[str] = queue.Queue()
        self.stderr: list[str] = []
        self.notifications: list[dict] = []
        threading.Thread(target=self._pump, args=(self.proc.stdout, self.lines.put), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc.stderr, self.stderr.append), daemon=True).start()
        self._id = 0

    @staticmethod
    def _pump(stream, sink) -> None:
        for line in stream:
            sink(line)

    def send(self, obj: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        while True:
            try:
                line = self.lines.get(timeout=TIMEOUT)
            except queue.Empty:
                raise AssertionError(f"no reply to {method}; stderr:\n{''.join(self.stderr)}") from None
            reply = json.loads(line)  # stdout must carry JSON-RPC only
            if reply.get("id") == self._id:
                return reply
            if "method" in reply and "id" not in reply:
                self.notifications.append(reply)

    def wait_notification(self, method: str, timeout: float = 15.0) -> dict:
        """Wait for a server notification without sending anything."""
        import time

        deadline = time.monotonic() + timeout
        while True:
            found = next((n for n in self.notifications if n.get("method") == method), None)
            if found:
                return found
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"no {method} notification; stderr:\n{''.join(self.stderr)}")
            try:
                msg = json.loads(self.lines.get(timeout=remaining))
            except queue.Empty:
                continue
            if "method" in msg and "id" not in msg:
                self.notifications.append(msg)

    def initialize(self) -> dict:
        init = self.request(
            "initialize",
            {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "0"}},
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return init

    def call(self, name: str, arguments: dict) -> tuple[bool, dict]:
        res = self.request("tools/call", {"name": name, "arguments": arguments})["result"]
        return res["isError"], json.loads(res["content"][0]["text"])

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def server_env(tmp_path: Path, isolated: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("IMAGE_") and k not in EXTRA_ENV}
    env["CLAUDE_STACK_ENV"] = str(tmp_path / "stack.env")
    env["CLAUDE_PROJECT_DIR"] = str(isolated)
    env["PYTHONPATH"] = str(REPO) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def test_stdio_handshake_status_and_unconfigured_error(isolated: Path, tmp_path: Path, server_env):
    s = StdioSession([sys.executable, "-m", "stack_mcp.image_router"], isolated, server_env)
    try:
        init = s.initialize()
        assert init["result"]["serverInfo"]["name"] == "image"
        assert "tools" in init["result"]["capabilities"]

        tools = s.request("tools/list")["result"]["tools"]
        assert {t["name"] for t in tools} == EXPECTED_TOOLS
        render = next(t for t in tools if t["name"] == "svg_render")
        assert "svg_path" in render["inputSchema"]["required"] and render["description"]

        is_error, status = s.call("image_ops_status", {})
        assert not is_error and status["ok"]
        assert status["configured"] == ["VECTOR_MANIPULATION"]  # only the 'claude' default
        assert all(not o["configured"] for op, o in status["ops"].items() if op != "VECTOR_MANIPULATION")
        assert status["svg_transform_exposed"] is False

        is_error, err = s.call("image_generate", {"prompt": "a red fox"})
        assert is_error and err["ok"] is False
        assert err["missing_env"] == ["IMAGE_GEN_URL", "IMAGE_GEN_MODEL", "IMAGE_GEN_KEY"]
        assert "IMAGE_GEN_KEY" in err["error"]

        bad = s.request("tools/call", {"name": "image_generate", "arguments": {"prompt": "x", "n": 9}})["result"]
        assert bad["isError"] is True  # schema validation (n <= 4)

        (isolated / "scene.svg").write_bytes((FIXTURES / "scene.svg").read_bytes())
        is_error, render = s.call("svg_render", {"svg_path": "scene.svg", "width": 100})
        assert not is_error and (render["width"], render["height"]) == (100, 60)

        # configuration is read at call time: enabling external vector manipulation lists svg_transform
        (tmp_path / "stack.env").write_text(
            "IMAGE_VECTOR_MANIPULATION_URL=https://openrouter.ai/api/v1\nIMAGE_VECTOR_MANIPULATION_KEY=sk-or-test-vm-0123456789abcdef\nIMAGE_VECTOR_MANIPULATION_MODEL=openai/gpt-5.4\nIMAGE_GEN_URL=https://openrouter.ai/api/v1\n"
        )
        names = {t["name"] for t in s.request("tools/list")["result"]["tools"]}
        assert names == EXPECTED_TOOLS | {"svg_transform"}
        is_error, err = s.call("image_generate", {"prompt": "x"})
        assert err["missing_env"] == ["IMAGE_GEN_MODEL", "IMAGE_GEN_KEY"]
    finally:
        s.close()
    assert not list(isolated.glob(".stack/images/**/*.png"))


@pytest.mark.skipif(not LAUNCHER.exists(), reason="launcher missing")
def test_bin_image_router_launcher(isolated: Path, server_env):
    s = StdioSession(["bash", str(LAUNCHER), "--mode", "all"], isolated, server_env)
    try:
        assert s.initialize()["result"]["serverInfo"]["name"] == "image"
        assert {t["name"] for t in s.request("tools/list")["result"]["tools"]} == EXPECTED_TOOLS
        is_error, status = s.call("image_ops_status", {})
        assert not is_error and "GEN" in status["ops"]
    finally:
        s.close()


def test_tool_list_changes_are_announced(isolated: Path, tmp_path: Path, server_env):
    """Clients cache tools/list: the server advertises listChanged and notifies when the env file
    adds or removes svg_transform - from the file watcher, and on the next tool call."""
    server_env["IMAGE_ROUTER_WATCH_INTERVAL"] = "0.2"
    s = StdioSession([sys.executable, "-m", "stack_mcp.image_router"], isolated, server_env)
    try:
        init = s.initialize()
        assert init["result"]["capabilities"]["tools"]["listChanged"] is True
        assert "svg_transform" not in {t["name"] for t in s.request("tools/list")["result"]["tools"]}
        (tmp_path / "stack.env").write_text("IMAGE_VECTOR_MANIPULATION_URL=https://openrouter.ai/api/v1\nIMAGE_VECTOR_MANIPULATION_KEY=sk-or-test-vm-0123456789abcdef\nIMAGE_VECTOR_MANIPULATION_MODEL=openai/gpt-5.4\n")
        s.wait_notification("notifications/tools/list_changed")  # no request needed: the watcher saw it
        assert "svg_transform" in {t["name"] for t in s.request("tools/list")["result"]["tools"]}
        assert sum(n["method"] == "notifications/tools/list_changed" for n in s.notifications) == 1  # no duplicates
    finally:
        s.close()

    server_env["IMAGE_ROUTER_WATCH_INTERVAL"] = "0"  # watcher off: the next tool call notices instead
    (tmp_path / "stack.env").write_text("")
    s = StdioSession([sys.executable, "-m", "stack_mcp.image_router"], isolated, server_env)
    try:
        s.initialize()
        s.request("tools/list")
        s.call("image_ops_status", {})  # several requests on one connection: still one notification
        (tmp_path / "stack.env").write_text("IMAGE_VECTOR_MANIPULATION_URL=https://openrouter.ai/api/v1\nIMAGE_VECTOR_MANIPULATION_KEY=sk-or-test-vm-0123456789abcdef\nIMAGE_VECTOR_MANIPULATION_MODEL=openai/gpt-5.4\n")
        is_error, status = s.call("image_ops_status", {})
        assert not is_error and status["svg_transform_exposed"] is True
        assert sum(n["method"] == "notifications/tools/list_changed" for n in s.notifications) == 1
        count = len(s.notifications)
        s.call("image_ops_status", {})
        assert len(s.notifications) == count  # announced once, not on every call
    finally:
        s.close()


def test_env_lines_deleted_after_launch_through_mcp_run(isolated: Path, tmp_path: Path, server_env):
    """The real launch chain: bin/mcp-run exports the env file, then the file changes under the server."""
    mcp_run = REPO / "bin" / "mcp-run"
    if not mcp_run.exists():
        pytest.skip("bin/mcp-run missing")
    env_file = tmp_path / "stack.env"
    env_file.write_text("IMAGE_GEN_URL=https://llm.example.test/v1\nIMAGE_GEN_KEY=sk-test-0123456789abcdef\n"
                        "IMAGE_GEN_MODEL=gpt-image-1\nIMAGE_GEN_API=openai\nIMAGE_VECTOR_MANIPULATION_URL=https://openrouter.ai/api/v1\nIMAGE_VECTOR_MANIPULATION_KEY=sk-or-test-vm-0123456789abcdef\nIMAGE_VECTOR_MANIPULATION_MODEL=openai/gpt-5.4\n")
    server_env["IMAGE_ROUTER_WATCH_INTERVAL"] = "0"
    s = StdioSession(["bash", str(mcp_run), sys.executable, "-m", "stack_mcp.image_router"], isolated, server_env)
    try:
        s.initialize()
        _, status = s.call("image_ops_status", {})
        assert status["ops"]["GEN"]["adapter"] == "openai" and status["svg_transform_exposed"] is True
        env_file.write_text("IMAGE_GEN_URL=https://openrouter.ai/api/v1\nIMAGE_GEN_KEY=sk-or-test-0123456789abcdef\n"
                            "IMAGE_GEN_MODEL=google/gemini-nano-banana-2.1\n")
        _, status = s.call("image_ops_status", {})
        gen = status["ops"]["GEN"]
        assert (gen["adapter"], gen["adapter_source"], gen["url_host"]) == ("openrouter", "detected", "openrouter.ai")
        assert status["svg_transform_exposed"] is False
        assert "svg_transform" not in {t["name"] for t in s.request("tools/list")["result"]["tools"]}
    finally:
        s.close()
