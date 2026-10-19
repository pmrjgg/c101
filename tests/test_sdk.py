"""Tests for running the stack under the Claude Agent SDK (stack_sdk). No API calls."""
import asyncio
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import claude_agent_sdk  # noqa: F401
    HAVE_SDK = True
except ImportError:  # running under the system interpreter without the uv env
    HAVE_SDK = False


@unittest.skipUnless(HAVE_SDK, "claude-agent-sdk not installed (run via uv)")
class SdkAgentTests(unittest.TestCase):
    def test_every_agent_converts(self):
        from stack import frontmatter, paths, tiers
        from stack_sdk.agents import load_all
        loaded = load_all()
        self.assertEqual(len(loaded), len(paths.all_agent_files()))
        models = tiers.tier_models()
        cfg = tiers.load()
        for name, ag in loaded.items():
            d = ag.definition
            fm = frontmatter.read(ag.path)
            self.assertTrue(d.description and d.prompt, name)
            self.assertEqual(d.model, models[cfg["agents"][name]["tier"]], name)
            self.assertEqual(d.effort, fm.get("effort"), name)
            self.assertEqual(d.maxTurns, int(fm["maxTurns"]), name)
            self.assertEqual(set(ag.dropped) - {"color"}, set(), name)
            self.assertIn("delegation-protocol", d.skills or [], name)

    def test_tier_env_override(self):
        from stack_sdk.agents import load_agents
        os.environ["LOW_MODEL"] = "claude-haiku-test"
        try:
            self.assertEqual(load_agents()["file-summarizer"].model, "claude-haiku-test")
        finally:
            del os.environ["LOW_MODEL"]

    def test_disallowed_tools_list(self):
        from stack_sdk.agents import load_agents
        self.assertEqual(load_agents()["file-summarizer"].disallowedTools, ["Agent", "Edit", "NotebookEdit"])


@unittest.skipUnless(HAVE_SDK, "claude-agent-sdk not installed (run via uv)")
class SdkOptionsTests(unittest.TestCase):
    def test_in_repo_uses_filesystem_and_settings(self):
        from stack_sdk.options import StackRunConfig, build_options
        o = build_options(StackRunConfig(cwd=ROOT))
        self.assertEqual(o.extra_args.get("agent"), "delegator")
        self.assertIsNone(o.agents)
        self.assertIsNone(o.hooks)  # settings.json command hooks run instead
        self.assertIn("project", o.setting_sources)
        self.assertEqual(o.model, "claude-opus-5-5")
        self.assertEqual(o.task_budget, {"total": 400_000_000})
        self.assertEqual(o.skills, "all")
        self.assertEqual(o.permission_mode, "dontAsk")
        self.assertEqual(o.extra_args.get("permission-prompts"), "none")
        self.assertEqual(o.env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"], "1")
        self.assertIn("mcp__exa", o.allowed_tools)
        self.assertIn("Workflow", o.allowed_tools)

    def test_elsewhere_is_self_contained(self):
        from stack_sdk.options import StackRunConfig, build_options
        tmp = tempfile.mkdtemp()
        try:
            o = build_options(StackRunConfig(cwd=tmp))
            self.assertIn("delegator", o.agents)
            self.assertEqual(o.system_prompt["type"], "preset")
            self.assertTrue(o.system_prompt["append"].startswith("You are the delegator"))
            self.assertEqual(o.env["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"], "8")
            self.assertEqual(set(o.hooks), {"PreToolUse", "PostToolUse", "SubagentStop", "UserPromptSubmit"})
            for name, cfg in o.mcp_servers.items():
                blob = json.dumps(cfg)
                self.assertNotIn("CLAUDE_PROJECT_DIR", blob, name)
                if cfg.get("type") == "http":
                    self.assertNotIn("headers", cfg, name)  # auth only via headersHelper
                    self.assertIn(ROOT + "/bin/mcp-headers", cfg["headersHelper"], name)
                elif cfg["command"] == "sh":  # launcher pinned to this repo
                    self.assertIn('d="%s"' % ROOT, cfg["args"][-1], name)
                else:
                    self.assertTrue(cfg["command"].startswith("/") or cfg["command"] == "npx", name)
            for name, ag in o.agents.items():  # subagents' inline servers are pinned too
                for e in ag.mcpServers or []:
                    if isinstance(e, dict):
                        self.assertNotIn("CLAUDE_PROJECT_DIR", json.dumps(e), name)
        finally:
            shutil.rmtree(tmp)

    def test_main_thread_is_pinned_and_models_restricted(self):
        from stack_sdk.options import StackRunConfig, build_options
        with self.assertRaises(ValueError):
            build_options(StackRunConfig(cwd=ROOT, model="claude-sonnet-5-5"))
        with self.assertRaises(ValueError):
            build_options(StackRunConfig(cwd=ROOT, main_agent=None, model="claude-fable-5-1"))
        o = build_options(StackRunConfig(cwd=ROOT))
        self.assertEqual((o.model, o.effort), ("claude-opus-5-5", "high"))
        self.assertEqual(json.loads(o.settings)["availableModels"],
                         ["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5"])

    def test_hook_strips_per_call_model_and_forces_foreground(self):
        from stack import hooks
        tmp = tempfile.mkdtemp()
        os.environ.update(CLAUDE_STACK_DATA=os.path.join(tmp, "data"), CLAUDE_STACK_FOREGROUND="1")
        try:
            inp = {"tool_name": "Agent", "session_id": "S", "transcript_path": os.path.join(tmp, "x.jsonl"),
                   "tool_input": {"subagent_type": "tester", "prompt": "x", "model": "haiku", "effort": "low",
                                  "run_in_background": True}}
            out = hooks.run_handler("pre-agent", inp)["hookSpecificOutput"]["updatedInput"]
            self.assertNotIn("model", out)
            self.assertNotIn("effort", out)
            self.assertIs(out["run_in_background"], False)
        finally:
            os.environ.pop("CLAUDE_STACK_DATA", None)
            os.environ.pop("CLAUDE_STACK_FOREGROUND", None)
            shutil.rmtree(tmp)

    def test_python_pre_agent_hook_denies_over_depth(self):
        from stack_sdk import hooks
        tmp = tempfile.mkdtemp()
        os.environ["CLAUDE_STACK_DATA"] = os.path.join(tmp, "data")
        os.environ["CLAUDE_STACK_MAX_DEPTH"] = "1"
        try:
            transcript = os.path.join(tmp, "s.jsonl")
            open(transcript, "w").close()
            sub = os.path.join(tmp, "s", "subagents")
            os.makedirs(sub)
            with open(os.path.join(sub, "agent-z.meta.json"), "w") as fh:
                json.dump({"agentType": "planner", "spawnDepth": 1}, fh)
            inp = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": "S", "agent_id": "z",
                   "agent_type": "planner", "transcript_path": transcript, "cwd": tmp,
                   "tool_input": {"subagent_type": "tester", "prompt": "x"}, "tool_use_id": "t"}
            out = asyncio.run(hooks.pre_agent(inp, "t", {"signal": None}))
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        finally:
            os.environ.pop("CLAUDE_STACK_DATA", None)
            os.environ.pop("CLAUDE_STACK_MAX_DEPTH", None)
            shutil.rmtree(tmp)

    def test_run_drops_parent_session_identity(self):
        import claude_agent_sdk
        from stack_sdk import __main__ as cli
        seen = {}

        async def fake_query(prompt, options):
            seen.update({v: os.environ.get(v) for v in cli.PARENT_SESSION_VARS})
            return
            yield

        saved = {v: os.environ.get(v) for v in cli.PARENT_SESSION_VARS}
        os.environ.update({v: "parent-value" for v in cli.PARENT_SESSION_VARS})
        real = claude_agent_sdk.query
        claude_agent_sdk.query = fake_query
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                cli.main(["run", "x", "--cwd", ROOT, "--json"])
            self.assertEqual(seen, {v: None for v in cli.PARENT_SESSION_VARS})
        finally:
            claude_agent_sdk.query = real
            for v, val in saved.items():
                os.environ.pop(v, None)
                if val is not None:
                    os.environ[v] = val


if __name__ == "__main__":
    unittest.main()
