"""The stack's hooks as Agent SDK Python callbacks.

When an SDK session does not load this repo's ``.claude/settings.json`` (it runs
in another directory, or ``setting_sources`` excludes the project), the command
hooks there do not fire. These callbacks run the *same* handlers in-process
(``stack.hooks.run_handler``): depth guard + spawn rules + token budgets on every
Agent/Task call, SubagentStop telemetry for the learner, and the per-prompt
budget note. SessionEnd has no SDK callback; the runner triggers learning itself
when the query finishes.
"""
from __future__ import annotations

import asyncio
from typing import Any

from claude_agent_sdk import HookMatcher

from stack import hooks as stack_hooks


def _plain(d: Any) -> dict:
    return {k: v for k, v in dict(d).items()}


async def pre_agent(input_data: Any, tool_use_id: str | None, context: Any) -> dict:
    out = await asyncio.to_thread(stack_hooks.run_handler, "pre-agent", _plain(input_data))
    return out or {}


async def subagent_stop(input_data: Any, tool_use_id: str | None, context: Any) -> dict:
    # Ingestion can take a moment on big sessions; never block the event loop.
    await asyncio.to_thread(stack_hooks.run_handler, "subagent-stop", _plain(input_data))
    return {}


async def prompt_submit(input_data: Any, tool_use_id: str | None, context: Any) -> dict:
    out = await asyncio.to_thread(stack_hooks.run_handler, "prompt-submit", _plain(input_data))
    return out or {}


def python_hooks(timeout: float = 30.0) -> dict[str, list[HookMatcher]]:
    return {
        "PreToolUse": [HookMatcher(matcher="Agent|Task", hooks=[pre_agent], timeout=timeout)],
        "SubagentStop": [HookMatcher(hooks=[subagent_stop], timeout=120.0)],
        "UserPromptSubmit": [HookMatcher(hooks=[prompt_submit], timeout=timeout)],
    }
