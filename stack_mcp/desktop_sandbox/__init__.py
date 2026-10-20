"""desktop-sandbox: the ``desktop-sandbox`` MCP stdio server (sandboxed computer use).

Drives a disposable Linux desktop (Xvfb + openbox + xdotool) inside a hardened container: no network by
default, read-only root filesystem, every capability dropped, no-new-privileges, an unprivileged user,
memory/CPU/PID limits, a hard lifetime enforced by the container itself, and a single bind mount (the
per-sandbox exchange directory under ``.stack/sandbox/``). The host desktop, the user's apps, files,
keychain and keys are never reachable from it. Works the same in interactive Claude Code and under the
Claude Agent SDK, which is why it is the stack's unattended computer-use route.

The server is agent-scoped: config/mcp.servers.json defines it and ``bin/stack mcp sync`` inlines it only
into the agents that use it, so it connects while such an agent runs and exits when the agent finishes;
the container starts only on ``sandbox_start`` and is removed when the server exits.
"""

__version__ = "1.0.0"
