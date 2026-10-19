"""MCP stdio server ``image``: ``python -m stack_mcp.image_router`` (launched by bin/image-router).

One server exposes one tool per kind of image operation, each bound to the endpoint/model
configured for that operation in ~/.claude/stack.env (read at call time), plus local tools
that need no model. An operation's tool is listed only while that operation is configured
(URL + KEY + MODEL, or API=local for TRACE / UPSCALE); ``svg_transform`` only while
IMAGE_VECTOR_MANIPULATION_MODEL is set to something other than ``claude``. ``image_ops_status``
and the local tools are always listed. The server advertises ``tools.listChanged`` and sends
``notifications/tools/list_changed`` (on ``subscriptions/listen`` streams for 2026-07-28+
clients) when the set changes: the env file is watched (mtime, every
``IMAGE_ROUTER_WATCH_INTERVAL`` seconds, default 2; 0 disables) and re-checked on every tool
call, so clients that cache tools/list see tools appear or disappear without a reconnect
(clients that ignore list_changed need /mcp reconnect).

stdout carries JSON-RPC only (the SDK diverts fd 1 to stderr while serving); diagnostics go
to stderr. ``--mode`` is accepted and ignored for compatibility with v1 launch lines.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import anyio
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.stdio import stdio_server
from mcp.shared.subscriptions import ToolsListChanged
from mcp_types import ToolAnnotations

from . import __version__
from .config import env_file_path, env_file_state, load_all, snapshot_boot_env
from .tools import ALL_TOOLS, LOCAL_TOOL_NAMES, READ_ONLY_TOOLS, hidden_tools

SERVER_NAME = "image"

INSTRUCTIONS = """\
Image operations, each bound to the endpoint + model the user configured for it in ~/.claude/stack.env
(IMAGE_<OP>_URL / _KEY / _MODEL; OpenRouter, Opper, fal or OpenAI-compatible; no fallbacks): image_generate
(GEN), image_generate_with_references (REF), image_edit (EDIT, masked inpaint with `mask`),
image_generate_transparent (TRANSPARENT), image_segment (SEGMENT), image_remove_background (BG_REMOVAL),
image_upscale (UPSCALE), vector_generate (VECTOR), image_vectorize (TRACE). Only configured operations are
listed; image_ops_status shows every operation and the exact env names a missing one needs. Local tools (no model):
image_info, mask_convert, svg_optimize, svg_inspect, svg_render (PNG preview of an SVG), svg_layers,
svg_layerize, layers_compose, export_pdf (layered vector PDF). Vector manipulation is done by you (edit the
SVG text) unless svg_transform is listed. Inputs: local paths (relative to the project), URLs or data URIs.
Outputs go to .stack/images/<YYYYMMDD>/ with a JSON sidecar. Masks: WHITE = edit, BLACK = keep.
The tool list follows the env file (tools/list_changed is sent when an operation is configured or removed)."""

# Tools that write files and replace an existing file when given an explicit output_path.
OVERWRITING_TOOLS = frozenset(
    {"svg_optimize", "mask_convert", "svg_render", "svg_layerize", "layers_compose", "export_pdf", "svg_transform"}
)


def watch_interval() -> float:
    try:
        return max(0.0, float(os.environ.get("IMAGE_ROUTER_WATCH_INTERVAL", "2")))
    except ValueError:
        return 2.0


@asynccontextmanager
async def _watch_env(server: ImageServer) -> AsyncIterator[dict[str, Any]]:
    """Lifespan: poll the env file while serving and announce tool-list changes."""
    interval = watch_interval()
    async with anyio.create_task_group() as tg:
        if interval > 0:
            tg.start_soon(server.watch_env_file, interval)
        try:
            yield {}
        finally:
            tg.cancel_scope.cancel()


class ImageServer(MCPServer):
    """MCPServer whose tool list shows only configured operations (see tools.hidden_tools).

    It remembers what the client was last told (the hidden set of the last tools/list) and
    notifies ``tools/list_changed`` when the env file changes that.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        kwargs.setdefault("lifespan", _watch_env)
        super().__init__(*args, **kwargs)
        self._advertised: frozenset[str] | None = None  # tools hidden in the last tools/list reply
        # latest request session per client connection (stdio: one), for notifications
        self._sessions: dict[int, Any] = {}
        self._env_state = env_file_state()

    async def list_tools(self) -> list[Any]:
        tools = await super().list_tools()
        hidden = hidden_tools()
        self._advertised = hidden
        return [t for t in tools if t.name not in hidden]

    def _remember(self, ctx: Any) -> None:
        session = getattr(ctx, "session", None)
        if session is None:
            return
        key = id(getattr(session, "_connection", session))  # one entry per connection
        self._sessions.pop(key, None)
        self._sessions[key] = session
        while len(self._sessions) > 8:
            self._sessions.pop(next(iter(self._sessions)))

    async def _handle_list_tools(self, ctx: Any, params: Any) -> Any:
        self._remember(ctx)
        return await super()._handle_list_tools(ctx, params)

    async def _handle_call_tool(self, ctx: Any, params: Any) -> Any:
        self._remember(ctx)
        await self.check_tools_changed()
        return await super()._handle_call_tool(ctx, params)

    async def check_tools_changed(self) -> bool:
        """Notify the client when the hidden tool set differs from the last tools/list."""
        if self._advertised is None:
            return False  # the client has not listed tools yet: nothing to correct
        hidden = hidden_tools()
        if hidden == self._advertised:
            return False
        self._advertised = hidden  # announce once; the client's next tools/list confirms it
        await self.notify_tools_changed()
        return True

    async def notify_tools_changed(self) -> None:
        """notifications/tools/list_changed: on the connection (handshake-era clients) and on the
        subscription bus (2026-07-28+ clients listening via subscriptions/listen)."""
        try:
            await self._subscriptions.publish(ToolsListChanged())
        except Exception as exc:  # pragma: no cover - the in-memory bus does not fail
            print(f"image: list_changed publish failed: {type(exc).__name__}", file=sys.stderr)
        for key, session in list(self._sessions.items()):
            try:
                await session.send_tool_list_changed()
            except Exception:
                self._sessions.pop(key, None)  # connection gone

    async def watch_env_file(self, interval: float) -> None:
        while True:
            await anyio.sleep(interval)
            state = env_file_state()
            if state != self._env_state:
                self._env_state = state
                try:
                    await self.check_tools_changed()
                except Exception as exc:  # never let the watcher take the server down
                    print(f"image: env watch failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    async def run_stdio_async(self) -> None:
        """stdio transport, advertising tools.listChanged."""
        async with stdio_server() as (read_stream, write_stream):
            await self._lowlevel_server.run(
                read_stream,
                write_stream,
                self._lowlevel_server.create_initialization_options(NotificationOptions(tools_changed=True)),
            )


def build_server() -> ImageServer:
    server = ImageServer(
        name=SERVER_NAME,
        title="Image operations (per-operation BYOK endpoints + local SVG/PDF tools)",
        instructions=INSTRUCTIONS,
        version=__version__,
        log_level="WARNING",
    )
    for fn in ALL_TOOLS:
        name = fn.__name__
        local = name in LOCAL_TOOL_NAMES
        read_only = name in READ_ONLY_TOOLS
        server.add_tool(
            fn,
            name=name,
            annotations=ToolAnnotations(
                read_only_hint=read_only,
                # an explicit output_path replaces an existing file; default names never do
                destructive_hint=name in OVERWRITING_TOOLS,
                # every call of a writing tool creates a new file (collision-free names)
                idempotent_hint=read_only,
                open_world_hint=not local,
            ),
            structured_output=False,
        )
    return server


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="image-router",
        description="MCP stdio server 'image': per-operation image endpoints (OpenRouter / Opper / fal / OpenAI-compatible) "
        "plus local SVG, layer and PDF tools.",
    )
    p.add_argument("--mode", default=None, help="ignored (v1 compatibility: one server now exposes every tool)")
    p.add_argument("--check", action="store_true", help="print per-operation configuration (no keys) to stderr and exit")
    return p.parse_args(argv)


def status_lines() -> list[str]:
    lines = [f"env file: {env_file_path()} ({'found' if env_file_path().is_file() else 'missing'})"]
    for op, cfg in load_all().items():
        if op == "VECTOR_MANIPULATION" and cfg.is_claude:
            lines.append(f"  {op:<20} claude (agent edits SVG; svg_transform hidden)")
            continue
        if cfg.configured:
            lines.append(f"  {op:<20} {cfg.api} {cfg.host or ''} {cfg.model or ''}".rstrip())
        else:
            why = cfg.error or ("missing " + ", ".join(cfg.missing_env))
            lines.append(f"  {op:<20} NOT CONFIGURED ({why})")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    if args.check:
        print("\n".join(status_lines()), file=sys.stderr)
        return 0
    # bin/mcp-run exported the env file into our environment: remember those values so a line
    # deleted or blanked later does not keep applying through the inherited copy
    snapshot_boot_env()
    configured = [op for op, c in load_all().items() if c.configured and not (op == "VECTOR_MANIPULATION" and c.is_claude)]
    print(
        f"image-router {__version__}: server '{SERVER_NAME}', configured ops: {', '.join(configured) or 'none'}",
        file=sys.stderr,
    )
    build_server().run("stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
